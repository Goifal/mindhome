"""
Correction Memory - Strukturiertes Korrektur-Gedaechtnis.

Speichert User-Korrekturen strukturiert: Original-Aktion + Korrektur + Kontext.
Leitet Regeln ab wenn gleiche Korrektur-Muster 2+ mal auftreten.
Injiziert relevante Korrekturen als LLM-Kontext bei zukuenftigen Aktionen.

Sicherheit: Read-only Memory. Beeinflusst nur LLM-Kontext. Max 200 Eintraege.
"""

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional

from .config import yaml_config

logger = logging.getLogger(__name__)
from zoneinfo import ZoneInfo

_LOCAL_TZ = ZoneInfo(yaml_config.get("timezone", "Europe/Berlin"))

# Injection-Schutz: Gleiches Pattern wie context_builder.py
_INJECTION_PATTERN = re.compile(
    r"\[(?:SYSTEM|INSTRUCTION|OVERRIDE|ADMIN|COMMAND|PROMPT|ROLE)\b"
    r"|IGNORE\s+(?:ALL\s+)?(?:PREVIOUS\s+)?INSTRUCTIONS"
    r"|SYSTEM\s*(?:MODE|OVERRIDE|INSTRUCTION)"
    r"|<\/?(?:system|instruction|admin|role|prompt)\b",
    re.IGNORECASE,
)

# Max Regeln gleichzeitig aktiv
MAX_RULES = 20
MAX_RULE_TEXT_LEN = 200
MIN_CONFIDENCE_FOR_RULE = 0.6
RULES_PER_DAY_LIMIT = 5

# Confidence-Decay: 5% pro 30 Tage
CONFIDENCE_DECAY_PER_DAY = 0.05 / 30


class CorrectionMemory:
    """Speichert und lernt aus User-Korrekturen."""

    def __init__(self):
        self.redis = None
        self.enabled = False
        self._ollama = None  # MCU Sprint 4: Kausales Lernen
        self._cfg = yaml_config.get("correction_memory", {})
        self._max_entries = self._cfg.get("max_entries", 500)
        self._max_context = self._cfg.get("max_context_entries", 3)
        self._rules_created_today = 0
        self._last_rules_day = ""
        self._rules_lock = asyncio.Lock()
        self._cross_domain_enabled = self._cfg.get("cross_domain_rules", True)

    async def initialize(self, redis_client):
        """Initialisiert mit Redis Client."""
        self.redis = redis_client
        self.enabled = self._cfg.get("enabled", True) and self.redis is not None
        logger.info("CorrectionMemory initialisiert (enabled=%s)", self.enabled)

    def set_ollama(self, ollama_client):
        """Setzt den OllamaClient fuer LLM-basierte Regel-Begruendungen."""
        self._ollama = ollama_client

    async def store_correction(
        self,
        original_action: str,
        original_args: dict,
        correction_text: str,
        corrected_args: Optional[dict] = None,
        person: str = "",
        room: str = "",
        causal_context: Optional[dict] = None,
    ):
        """Speichert eine strukturierte Korrektur mit optionalem kausalem Kontext.

        Args:
            original_action: Die urspruengliche Aktion die korrigiert wird.
            original_args: Die urspruenglichen Parameter.
            correction_text: Der Korrektur-Text des Users.
            corrected_args: Die korrigierten Parameter.
            person: Person die korrigiert hat.
            room: Raum-Kontext.
            causal_context: Optionaler kausaler Kontext zum Zeitpunkt der Korrektur
                (z.B. Fenster-Status, Wetter, Aktivitaet). Ermoeglicht Root-Cause-
                Analyse: WARUM wurde korrigiert, nicht nur WAS.
        """
        if not self.enabled or not self.redis:
            return

        # Sanitize correction text
        clean_text = _sanitize(correction_text)
        if not clean_text:
            return

        entry = {
            "original_action": original_action,
            "original_args": original_args,
            "correction_text": clean_text[:200],
            "corrected_args": corrected_args or {},
            "person": person,
            "room": room,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "hour": datetime.now(_LOCAL_TZ).hour,
        }

        # Kausaler Kontext: Umgebungsbedingungen zum Zeitpunkt der Korrektur
        if causal_context:
            # Nur relevante, kompakte Felder speichern (max 500 Bytes)
            _allowed_keys = {
                "windows_open", "outdoor_temp", "activity",
                "weather", "season", "occupancy",
            }
            entry["causal_context"] = {
                k: v for k, v in causal_context.items()
                if k in _allowed_keys and v is not None
            }

        try:
            await self.redis.lpush(
                "mha:correction_memory:entries",
                json.dumps(entry, ensure_ascii=False),
            )
            await self.redis.ltrim(
                "mha:correction_memory:entries", 0, self._max_entries - 1
            )
        except Exception as e:
            logger.warning("Korrektur-Speicherung fehlgeschlagen: %s", e)
            return

        logger.info(
            "Korrektur gespeichert: %s -> %s (Person: %s)",
            original_action,
            clean_text[:60],
            person or "unbekannt",
        )

        # Regel-Ableitung pruefen
        await self._update_rules(entry)

    async def get_relevant_corrections(
        self, action_type: str = "", args: Optional[dict] = None, person: str = ""
    ) -> Optional[str]:
        """Gibt relevante Korrekturen als LLM-Kontext zurueck."""
        if not self.enabled or not self.redis:
            return None

        entries = await self._get_entries()
        if not entries:
            return None

        # Scoring: Relevanteste Korrekturen finden
        scored = []
        for entry in entries:
            score = 0.0

            # Aktionstyp-Match
            if action_type and entry.get("original_action") == action_type:
                score += 2.0

            # Raum-Match
            if args and entry.get("original_args", {}).get("room") == args.get("room"):
                score += 1.0

            # Person-Match (Feature 6)
            if person and entry.get("person") == person:
                score += 1.0

            # Tageszeit-Aehnlichkeit (mit Mitternachts-Wrap)
            current_hour = datetime.now(_LOCAL_TZ).hour
            entry_hour = entry.get("hour", 12)
            hour_diff = min(
                abs(current_hour - entry_hour), 24 - abs(current_hour - entry_hour)
            )
            if hour_diff <= 2:
                score += 0.5

            # Kausaler Kontext-Match: Wenn die aktuelle Situation dem
            # kausalen Kontext der Korrektur aehnelt, ist die Korrektur
            # besonders relevant (gleiche Ursache → gleiche Korrektur).
            _entry_ctx = entry.get("causal_context", {})
            if _entry_ctx and args:
                _current_ctx = args.get("_causal_context", {})
                if _current_ctx:
                    # Fenster-Status-Match
                    if (
                        _entry_ctx.get("windows_open")
                        and _current_ctx.get("windows_open")
                    ):
                        score += 1.5  # Starker Indikator: gleiche Ursache
                    # Aktivitaets-Match
                    if (
                        _entry_ctx.get("activity")
                        and _entry_ctx.get("activity") == _current_ctx.get("activity")
                    ):
                        score += 1.0
                    # Wetter-Match
                    if (
                        _entry_ctx.get("weather")
                        and _entry_ctx.get("weather") == _current_ctx.get("weather")
                    ):
                        score += 0.5

            if score > 0:
                scored.append((score, entry))

        if not scored:
            return None

        # Top N nach Score sortieren
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[: self._max_context]

        lines = ["BISHERIGE KORREKTUREN (beachte diese):"]
        for _, entry in top:
            text = entry.get("correction_text", "")
            action = entry.get("original_action", "")
            lines.append(f"- Bei '{action}': {text}")

        return "\n".join(lines)

    async def get_active_rules(
        self, action_type: str = "", person: str = ""
    ) -> list[dict]:
        """Gibt aktive Regeln zurueck (fuer Prompt Self-Refinement)."""
        if not self.enabled or not self.redis:
            return []

        raw = await self.redis.hgetall("mha:correction_memory:rules")
        if not raw:
            return []

        rules = []
        now = time.time()
        for key, val in raw.items():
            try:
                rule = json.loads(val)
            except json.JSONDecodeError:
                continue

            # Confidence-Decay anwenden
            created_ts = rule.get("created_ts", now)
            age_days = (now - created_ts) / 86400
            decayed_conf = rule.get("confidence", 0.5) - (
                age_days * CONFIDENCE_DECAY_PER_DAY
            )

            if decayed_conf < 0.4:
                # Regel abgelaufen — loeschen
                await self.redis.hdel("mha:correction_memory:rules", key)
                continue

            rule["confidence"] = round(decayed_conf, 3)

            # Filter: Aktionstyp
            if action_type and rule.get("trigger") and rule["trigger"] != action_type:
                continue

            # Filter: Person — globale Regeln (kein person-Feld) immer einschliessen,
            # person-spezifische Regeln nur wenn sie zur aktuellen Person gehoeren
            rule_person = rule.get("person", "")
            if person and rule_person and rule_person != person:
                continue

            rules.append(rule)

        # Nach Confidence sortieren, max 5
        rules.sort(key=lambda r: r.get("confidence", 0), reverse=True)
        return rules[:5]

    async def get_stats(self) -> dict:
        """Statistiken fuer Self-Report."""
        if not self.redis:
            return {}

        entry_count = await self.redis.llen("mha:correction_memory:entries")
        rules_raw = await self.redis.hgetall("mha:correction_memory:rules")
        rule_count = len(rules_raw) if rules_raw else 0

        # Top Korrektur-Typen zaehlen
        entries = await self._get_entries(limit=100)
        type_counts = {}
        for e in entries:
            action = e.get("original_action", "unknown")
            type_counts[action] = type_counts.get(action, 0) + 1

        return {
            "total_corrections": entry_count or 0,
            "active_rules": rule_count,
            "top_correction_types": dict(
                sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            ),
        }

    async def get_correction_patterns(self) -> list[dict]:
        """Haeufigste Korrektur-Muster fuer Self-Optimization."""
        if not self.redis:
            return []

        entries = await self._get_entries(limit=100)
        patterns = {}
        for e in entries:
            action = e.get("original_action", "unknown")
            # Einfache Muster-Erkennung: Raum-Verwechslung, Parameter-Fehler
            orig_room = e.get("original_args", {}).get("room", "")
            corr_text = e.get("correction_text", "").lower()

            pattern_type = "other"
            if orig_room and any(
                w in corr_text for w in ["zimmer", "raum", "kueche", "bad"]
            ):
                pattern_type = "room_confusion"
            elif any(
                w in corr_text
                for w in ["hell", "dunkel", "laut", "leise", "grad", "temperatur"]
            ):
                pattern_type = "param_preference"
            elif any(w in corr_text for w in ["nicht", "nein", "falsch"]):
                pattern_type = "wrong_device"

            key = f"{action}:{pattern_type}"
            if key not in patterns:
                patterns[key] = {
                    "action": action,
                    "type": pattern_type,
                    "count": 0,
                    "examples": [],
                }
            patterns[key]["count"] += 1
            if len(patterns[key]["examples"]) < 3:
                patterns[key]["examples"].append(corr_text[:80])

        return sorted(patterns.values(), key=lambda p: p["count"], reverse=True)[:10]

    # --- Private Methoden ---

    async def _get_entries(self, limit: int = 0) -> list[dict]:
        """Laedt Korrektur-Eintraege aus Redis."""
        if not self.redis:
            return []

        n = limit or self._max_entries
        raw = await self.redis.lrange("mha:correction_memory:entries", 0, n - 1)
        entries = []
        for item in raw:
            try:
                entries.append(json.loads(item))
            except json.JSONDecodeError:
                continue
        return entries

    @staticmethod
    def _classify_correction(entry: dict) -> str:
        """Bestimmt den Korrektur-Typ anhand des Korrektur-Texts.

        Returns:
            Einer von: room_confusion, param_preference, wrong_device, person_preference, other
        """
        corr_text = (entry.get("correction_text") or "").lower()
        orig_args = entry.get("original_args") or {}
        corr_args = entry.get("corrected_args") or {}

        # Raum-Verwechslung: Korrektur erwaehnt Raumnamen
        if any(
            w in corr_text
            for w in [
                "zimmer",
                "raum",
                "kueche",
                "bad",
                "buero",
                "schlafzimmer",
                "wohnzimmer",
                "flur",
                "keller",
                "dachboden",
                "garage",
                "falscher raum",
                "falsches zimmer",
                "anderer raum",
            ]
        ):
            return "room_confusion"

        # Parameter-Praeferenz: Helligkeit, Temperatur, Lautstaerke etc.
        if any(
            w in corr_text
            for w in [
                "hell",
                "dunkel",
                "heller",
                "dunkler",
                "dimm",
                "laut",
                "leise",
                "lauter",
                "leiser",
                "grad",
                "temperatur",
                "waermer",
                "kaelter",
                "prozent",
                "%",
                "brightness",
                "zu viel",
                "zu wenig",
            ]
        ):
            return "param_preference"

        # Parameter-Aenderung erkennbar aus corrected_args vs original_args
        if corr_args and orig_args:
            shared_keys = set(orig_args.keys()) & set(corr_args.keys())
            changed = [
                k for k in shared_keys if orig_args[k] != corr_args[k] and k != "room"
            ]
            if changed:
                return "param_preference"

        # Falsches Geraet
        if any(
            w in corr_text
            for w in [
                "nicht",
                "nein",
                "falsch",
                "andere",
                "anderes",
                "meine ich nicht",
                "gemeint",
                "sondern",
            ]
        ):
            return "wrong_device"

        # Personen-Praeferenz
        if entry.get("person"):
            return "person_preference"

        return "other"

    def _compute_similarity(self, entry: dict, new_entry: dict) -> float:
        """Multi-dimensionaler Aehnlichkeits-Score zwischen zwei Korrekturen.

        Beruecksichtigt: Action, Raum, Person, Tageszeit, Korrektur-Typ, Parameter.
        Returns:
            Score zwischen 0.0 und 1.0
        """
        score = 0.0
        max_score = 0.0

        # 1. Gleiche Original-Aktion (Pflicht — wird schon vorher gefiltert)
        # 2. Raum-Match (+2.0)
        max_score += 2.0
        orig_room = (entry.get("original_args") or {}).get("room", "")
        new_room = (new_entry.get("original_args") or {}).get("room", "")
        if orig_room and new_room and orig_room == new_room:
            score += 2.0

        # 3. Person-Match (+1.5)
        max_score += 1.5
        if entry.get("person") and new_entry.get("person"):
            if entry["person"] == new_entry["person"]:
                score += 1.5

        # 4. Korrektur-Typ-Match (+2.0) — wichtigstes Signal
        max_score += 2.0
        entry_type = self._classify_correction(entry)
        new_type = self._classify_correction(new_entry)
        if entry_type == new_type and entry_type != "other":
            score += 2.0

        # 5. Tageszeit-Aehnlichkeit (+1.0)
        max_score += 1.0
        entry_hour = entry.get("hour", 12)
        new_hour = new_entry.get("hour", 12)
        hour_diff = min(abs(entry_hour - new_hour), 24 - abs(entry_hour - new_hour))
        if hour_diff <= 2:
            score += 1.0
        elif hour_diff <= 4:
            score += 0.5

        # 6. Parameter-Aehnlichkeit (+1.5) — gleiche Parameter korrigiert
        max_score += 1.5
        orig_args_e = entry.get("original_args") or {}
        orig_args_n = new_entry.get("original_args") or {}
        # Gleiche Parameter-Keys (ausser room)
        keys_e = set(k for k in orig_args_e if k != "room")
        keys_n = set(k for k in orig_args_n if k != "room")
        if keys_e and keys_n:
            overlap = keys_e & keys_n
            if overlap:
                score += 1.5 * (len(overlap) / max(len(keys_e), len(keys_n)))

        return score / max_score if max_score > 0 else 0.0

    async def _update_rules(self, new_entry: dict):
        """Wenn gleiches Korrektur-Muster 2+ mal → Regel ableiten.

        Multi-dimensionale Similarity: Beruecksichtigt Raum, Person,
        Tageszeit, Parameter und Korrektur-Typ.
        """
        if not self.redis:
            return

        # Rate Limit: Max N Regeln pro Tag — lock prevents concurrent overcount
        today = datetime.now(_LOCAL_TZ).strftime("%Y-%m-%d")
        async with self._rules_lock:
            if self._last_rules_day != today:
                self._rules_created_today = 0
                self._last_rules_day = today
            if self._rules_created_today >= RULES_PER_DAY_LIMIT:
                return
            self._rules_created_today += 1

        # Aktuelle Eintraege laden und Muster suchen
        entries = await self._get_entries(limit=50)
        action = new_entry.get("original_action", "")
        if not action:
            return

        # Multi-dimensionale Similarity statt reinem Raum-Match
        similar = []
        for e in entries:
            if e.get("original_action") != action:
                continue
            sim_score = self._compute_similarity(e, new_entry)
            if sim_score >= 0.4:  # Mindest-Aehnlichkeit 40%
                similar.append((sim_score, e))

        if len(similar) < 2:
            return

        # Bestehende Regeln zaehlen
        existing_count = await self.redis.hlen("mha:correction_memory:rules")
        if existing_count and existing_count >= MAX_RULES:
            return

        # Korrektur-Typ bestimmen fuer differenzierte Regel
        correction_type = self._classify_correction(new_entry)
        room = (new_entry.get("original_args") or {}).get("room", "")
        person = new_entry.get("person", "")
        hour = new_entry.get("hour", 12)
        time_hint = (
            "abends" if hour >= 18 else ("morgens" if hour < 10 else "tagsueber")
        )

        # Regel-Key: action + typ + kontext
        context_key = person or room or "global"
        rule_key = f"{action}:{correction_type}:{context_key}"

        # Haeufigsten Korrektur-Text finden
        correction_texts = [
            e.get("correction_text", "") for _, e in similar if e.get("correction_text")
        ]
        if not correction_texts:
            return

        # Differenzierte Regel-Texte je nach Korrektur-Typ
        if correction_type == "room_confusion" and room:
            rule_text = f"Bei '{action}' im Raum '{room}': User meint oft einen anderen Raum. Rueckfragen!"
        elif correction_type == "param_preference":
            # Parameter-Werte aus Korrekturen extrahieren
            corr_args = new_entry.get("corrected_args") or {}
            param_hints = [f"{k}={v}" for k, v in corr_args.items() if k != "room"]
            if param_hints:
                rule_text = (
                    f"Bei '{action}': User bevorzugt {', '.join(param_hints[:3])}."
                )
            else:
                rule_text = f"Bei '{action}' {time_hint}: User korrigiert Parameter-Werte. Nachfragen!"
        elif correction_type == "wrong_device":
            rule_text = f"Bei '{action}': User meint oft ein anderes Geraet. Praezise nachfragen!"
        elif correction_type == "person_preference" and person:
            rule_text = (
                f"Bei '{action}' fuer {person}: User hat spezifische Praeferenz."
            )
        else:
            rule_text = f"Bei '{action}' {time_hint}: User korrigiert oft."

        rule_text = rule_text[:MAX_RULE_TEXT_LEN]

        # Gewichtete Confidence basierend auf Similarity-Scores
        avg_sim = sum(s for s, _ in similar) / len(similar)
        confidence = min(1.0, 0.4 + len(similar) * 0.1 + avg_sim * 0.3)

        rule = {
            "type": correction_type,
            "trigger": action,
            "condition": f"hour {'>=18' if hour >= 18 else ('<10' if hour < 10 else '10-18')}",
            "learned": f"type={correction_type}, room={room}"
            if room
            else f"type={correction_type}",
            "confidence": round(confidence, 2),
            "count": len(similar),
            "text": rule_text,
            "created_ts": time.time(),
            "person": person,
        }
        # F2: Strukturierte Praeferenz-Werte fuer param_preference Regeln
        if correction_type == "param_preference":
            corr_args = new_entry.get("corrected_args") or {}
            preferred = {k: v for k, v in corr_args.items() if k != "room"}
            if preferred:
                rule["preferred_params"] = preferred
        if room:
            rule["room"] = room

        # MCU Sprint 4: Kausales Lernen — LLM fragt WARUM die Korrektur noetig war
        llm_reason = await self._get_llm_reason(new_entry, rule)
        if llm_reason:
            rule["reason"] = llm_reason

        await self.redis.hset(
            "mha:correction_memory:rules",
            rule_key,
            json.dumps(rule, ensure_ascii=False),
        )
        await self.redis.expire("mha:correction_memory:rules", 365 * 86400)

        logger.info(
            "Neue Regel [%s]: %s (confidence: %.2f, similar: %d%s)",
            correction_type,
            rule_text,
            confidence,
            len(similar),
            f", reason: {llm_reason}" if llm_reason else "",
        )

        # Cross-Domain: propagate generic correction patterns to other domains
        if self._cross_domain_enabled:
            try:
                await self._propagate_cross_domain(
                    rule_key,
                    rule,
                    correction_type,
                    action,
                    person,
                )
            except Exception as e:
                logger.warning("Cross-Domain-Propagation fehlgeschlagen: %s", e)

        # MCU-Persoenlichkeit: Lern-Bestaetigung in Queue pushen
        try:
            await self.redis.rpush("mha:learning_ack:pending", rule_text)
            # Max 10 pending, aelteste verwerfen
            await self.redis.ltrim("mha:learning_ack:pending", -10, -1)
        except Exception as e:
            logger.debug("Correction memory queue push failed: %s", e)

    # Domain-generic correction types that apply across domains
    _GENERIC_CORRECTION_TYPES = {"room_confusion", "wrong_device"}

    # Mapping: action prefix -> related domains
    _DOMAIN_ACTIONS = {
        "set_light": "light",
        "set_climate": "climate",
        "set_cover": "cover",
        "set_switch": "switch",
        "set_media": "media",
    }

    async def _propagate_cross_domain(
        self,
        source_rule_key: str,
        source_rule: dict,
        correction_type: str,
        action: str,
        person: str,
    ):
        """Propagates generic correction patterns to other domains.

        E.g., if the user keeps saying the wrong room for light commands,
        the same confusion likely applies to climate/cover commands too.
        """
        if not self.redis:
            return

        if correction_type not in self._GENERIC_CORRECTION_TYPES:
            return

        # Determine which domain this action belongs to
        source_domain = self._DOMAIN_ACTIONS.get(action, "")
        if not source_domain:
            return

        # Propagate to other domains with reduced confidence
        propagated = 0
        for target_action, target_domain in self._DOMAIN_ACTIONS.items():
            if target_domain == source_domain or target_action == action:
                continue

            # Rate Limit: Max N Regeln pro Tag (shared with _update_rules)
            if self._rules_created_today >= RULES_PER_DAY_LIMIT:
                break

            # MAX_RULES Check: nicht ueber Limit hinaus erstellen
            existing_count = await self.redis.hlen("mha:correction_memory:rules")
            if existing_count and existing_count >= MAX_RULES:
                break

            context_key = person or source_rule.get("room", "") or "global"
            cross_key = f"{target_action}:{correction_type}:{context_key}"

            # Don't overwrite existing rules
            existing = await self.redis.hget("mha:correction_memory:rules", cross_key)
            if existing:
                continue

            cross_rule = {
                **source_rule,
                "trigger": target_action,
                "confidence": round(source_rule.get("confidence", 0.5) * 0.7, 2),
                "cross_domain_source": action,
                "text": source_rule.get("text", "").replace(
                    f"'{action}'", f"'{target_action}'"
                ),
            }

            await self.redis.hset(
                "mha:correction_memory:rules",
                cross_key,
                json.dumps(cross_rule, ensure_ascii=False),
            )
            self._rules_created_today += 1
            propagated += 1

        if propagated > 0:
            logger.info(
                "Cross-Domain: Regel '%s' auf %d weitere Domaenen propagiert",
                correction_type,
                propagated,
            )

    # --- Expliziter Teaching Mode ---
    # Erlaubt dem User, direkt Bedeutungen beizubringen:
    # "Wenn ich 'Filmabend' sage, meine ich: Wohnzimmer-Licht dimmen, TV an, Rollos runter"

    async def teach(self, phrase: str, meaning: str, person: str = "default") -> str:
        """Speichert eine explizite Lehre: Phrase -> Bedeutung.

        Beispiel: teach("Filmabend", "Wohnzimmer-Licht dimmen, TV an, Rollos runter")
        """
        if not self.enabled or not self.redis:
            return "Teaching nicht verfuegbar (Redis nicht verbunden)."

        phrase_normalized = phrase.strip().lower()
        if not phrase_normalized or not meaning.strip():
            return "Phrase und Bedeutung duerfen nicht leer sein."

        # Injection-Schutz
        clean_meaning = _sanitize(meaning, max_len=500)
        if not clean_meaning:
            return "Bedeutung wurde als unsicher erkannt und blockiert."

        clean_phrase = _sanitize(phrase.strip(), max_len=100)
        if not clean_phrase:
            return "Phrase wurde als unsicher erkannt und blockiert."

        teaching = {
            "phrase": clean_phrase,
            "phrase_normalized": phrase_normalized,
            "meaning": clean_meaning,
            "person": person,
            "taught_at": datetime.now(timezone.utc).isoformat(),
            "times_used": 0,
        }

        redis_key = f"mha:teaching:{phrase_normalized}"
        try:
            await self.redis.set(
                redis_key,
                json.dumps(teaching, ensure_ascii=False),
            )
            # Phrase in Index-Set speichern fuer list_teachings()
            await self.redis.sadd("mha:teaching:index", phrase_normalized)
            # 1 Jahr TTL
            await self.redis.expire(redis_key, 365 * 86400)
        except Exception as e:
            logger.warning("Teaching-Speicherung fehlgeschlagen: %s", e)
            return "Fehler beim Speichern."

        logger.info(
            "Teaching gespeichert: '%s' -> '%s' (Person: %s)",
            phrase_normalized,
            clean_meaning[:60],
            person,
        )
        return (
            f"Verstanden! Wenn du '{phrase.strip()}' sagst, werde ich: {clean_meaning}"
        )

    async def get_teaching(self, text: str) -> str | None:
        """Prueft ob eine gelernte Phrase im Text vorkommt (Fuzzy/Substring-Match).

        'mach mal Filmabend' matched 'Filmabend'.
        Gibt die zugehoerige Bedeutung zurueck oder None.
        """
        if not self.enabled or not self.redis:
            return None

        text_lower = text.strip().lower()
        if not text_lower:
            return None

        # Alle bekannten Phrasen aus dem Index laden
        try:
            phrases = await self.redis.smembers("mha:teaching:index")
        except Exception as e:
            logger.warning("Teaching-Index Lesen fehlgeschlagen: %s", e)
            return None

        if not phrases:
            return None

        # Substring-Match: Laengste Phrase zuerst pruefen (greedy)
        matched_phrase = None
        for phrase in sorted(phrases, key=len, reverse=True):
            if phrase in text_lower:
                matched_phrase = phrase
                break

        if not matched_phrase:
            return None

        # Teaching laden
        redis_key = f"mha:teaching:{matched_phrase}"
        try:
            raw = await self.redis.get(redis_key)
            if not raw:
                return None
            teaching = json.loads(raw)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Teaching Lesen fehlgeschlagen: %s", e)
            return None

        # Usage-Counter erhoehen (fire-and-forget mit Error-Callback)
        task = asyncio.create_task(self.increment_teaching_usage(matched_phrase))
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

        return teaching.get("meaning")

    async def list_teachings(self, person: str = "default") -> list[dict]:
        """Gibt alle gelernten Phrasen mit Bedeutungen zurueck.

        Format: [{"phrase": "Filmabend", "meaning": "...", "taught_at": "...", "times_used": 3}]
        """
        if not self.enabled or not self.redis:
            return []

        try:
            phrases = await self.redis.smembers("mha:teaching:index")
        except Exception as e:
            logger.warning("Teaching-Index Lesen fehlgeschlagen: %s", e)
            return []

        if not phrases:
            return []

        teachings = []
        for phrase in sorted(phrases):
            redis_key = f"mha:teaching:{phrase}"
            try:
                raw = await self.redis.get(redis_key)
                if not raw:
                    # Verwaister Index-Eintrag — aufraeumen
                    await self.redis.srem("mha:teaching:index", phrase)
                    continue
                teaching = json.loads(raw)
            except (json.JSONDecodeError, Exception):
                continue

            # Person-Filter: nur passende oder globale Eintraege
            teaching_person = teaching.get("person", "default")
            if (
                person != "default"
                and teaching_person != "default"
                and teaching_person != person
            ):
                continue

            teachings.append(
                {
                    "phrase": teaching.get("phrase", phrase),
                    "meaning": teaching.get("meaning", ""),
                    "taught_at": teaching.get("taught_at", ""),
                    "times_used": teaching.get("times_used", 0),
                }
            )

        return teachings

    async def forget_teaching(self, phrase: str) -> bool:
        """Entfernt eine gelernte Phrase. Gibt True zurueck wenn gefunden und geloescht."""
        if not self.enabled or not self.redis:
            return False

        phrase_normalized = phrase.strip().lower()
        redis_key = f"mha:teaching:{phrase_normalized}"

        try:
            deleted = await self.redis.delete(redis_key)
            await self.redis.srem("mha:teaching:index", phrase_normalized)
        except Exception as e:
            logger.warning("Teaching-Loeschung fehlgeschlagen: %s", e)
            return False

        if deleted:
            logger.info("Teaching geloescht: '%s'", phrase_normalized)
            return True
        return False

    async def increment_teaching_usage(self, phrase: str):
        """Zaehlt wie oft ein Teaching verwendet wurde."""
        if not self.redis:
            return

        phrase_normalized = phrase.strip().lower()
        redis_key = f"mha:teaching:{phrase_normalized}"

        try:
            raw = await self.redis.get(redis_key)
            if not raw:
                return
            teaching = json.loads(raw)
            teaching["times_used"] = teaching.get("times_used", 0) + 1
            await self.redis.set(
                redis_key,
                json.dumps(teaching, ensure_ascii=False),
            )
        except Exception as e:
            logger.debug("Teaching-Usage Update fehlgeschlagen: %s", e)

    # ------------------------------------------------------------------
    # MCU Sprint 4: Kausales Lernen via LLM
    # ------------------------------------------------------------------

    async def _get_llm_reason(self, correction: dict, rule: dict) -> str:
        """Fragt das LLM WARUM eine Korrektur noetig war.

        Nutzt Fast-Tier fuer minimale Latenz (2s Timeout).
        Bei LLM-Ausfall: leerer String (Regel ohne Begruendung).

        Args:
            correction: Korrektur-Eintrag.
            rule: Erstellte Regel.

        Returns:
            Ein-Satz-Begruendung oder leerer String.
        """
        if not self._ollama:
            return ""

        try:
            action = correction.get("original_action", "")
            correction_text = correction.get("correction_text", "")
            room = correction.get("room", "")
            hour = correction.get("hour", 12)
            time_hint = (
                "abends" if hour >= 18 else ("morgens" if hour < 10 else "tagsueber")
            )

            prompt = (
                f"Der Benutzer hat folgende Korrektur vorgenommen:\n"
                f"Aktion: {action}\n"
                f"Korrektur: {correction_text}\n"
                f"Raum: {room or 'unbekannt'}\n"
                f"Tageszeit: {time_hint}\n\n"
                f"Warum hat der Benutzer diese Korrektur vorgenommen? "
                f"Antworte in EINEM kurzen Satz auf Deutsch."
            )

            from .config import settings

            response = await asyncio.wait_for(
                self._ollama.chat(
                    messages=[{"role": "user", "content": prompt}],
                    model=settings.model_fast,
                ),
                timeout=2.0,
            )

            reason = response.get("message", {}).get("content", "").strip()
            # <think> Bloecke entfernen
            reason = re.sub(r"<think>.*?</think>", "", reason, flags=re.DOTALL).strip()

            if reason and 5 < len(reason) < 150:
                return _sanitize(reason, max_len=150)

        except asyncio.TimeoutError:
            logger.debug("LLM reason timeout (2s)")
        except Exception as e:
            logger.debug("LLM reason Fehler: %s", e)

        return ""

    def format_rules_for_prompt(self, rules: list[dict]) -> str:
        """Formatiert Regeln als Prompt-Abschnitt (Feature 7: Prompt Self-Refinement)."""
        if not rules:
            return ""

        lines = ["GELERNTE PRAEFERENZEN:"]
        for rule in rules[:5]:
            text = rule.get("text", "")
            confidence = rule.get("confidence", 0)
            if (
                text
                and len(text) <= MAX_RULE_TEXT_LEN
                and confidence >= MIN_CONFIDENCE_FOR_RULE
            ):
                # Sanitize bevor es in den Prompt geht
                clean = _sanitize(text)
                if clean:
                    # MCU Sprint 4: Begruendung mit ausgeben wenn vorhanden
                    reason = rule.get("reason", "")
                    if reason:
                        clean_reason = _sanitize(reason, max_len=100)
                        if clean_reason:
                            lines.append(f"- {clean} (Grund: {clean_reason})")
                        else:
                            lines.append(f"- {clean}")
                    else:
                        lines.append(f"- {clean}")

        if len(lines) <= 1:
            return ""

        return "\n".join(lines)


def _sanitize(text: str, max_len: int = 200) -> str:
    """Bereinigt Text fuer Prompt-Injection-Schutz."""
    if not text or not isinstance(text, str):
        return ""
    text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    text = re.sub(r"\s{2,}", " ", text).strip()
    text = text[:max_len]
    if _INJECTION_PATTERN.search(text):
        logger.warning("Prompt-Injection in Korrektur blockiert: %.80s", text)
        return ""
    return text
