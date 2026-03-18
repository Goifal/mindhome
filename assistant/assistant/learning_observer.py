"""
Learning Observer - Beobachtet manuelle Aktionen und schlaegt Automatisierungen vor.

Features:
- Erkennt wiederholte manuelle Aktionen (via HA State Changes)
- Zaehlt Muster: "Jeden Abend um 22:30 → Licht Erdgeschoss aus"
- Ab 3 Wiederholungen → Proaktiver Vorschlag
- Bei Bestätigung → Self-Automation erstellen
- Unterscheidet Jarvis-Aktionen von manuellen Aktionen

Ergaenzt die bestehende anticipation.py mit manuellen Aktions-Mustern.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

import redis.asyncio as aioredis

from .config import get_person_title

from .config import yaml_config

logger = logging.getLogger(__name__)

KEY_MANUAL_ACTIONS = "mha:learning:manual_actions"
KEY_PATTERNS = "mha:learning:patterns"
KEY_WEEKDAY_PATTERNS = "mha:learning:weekday_patterns"
KEY_SUGGESTED = "mha:learning:suggested"
KEY_RESPONSES = "mha:learning:responses"
JARVIS_ACTION_KEY = "mha:learning:jarvis_action"  # Marker fuer Jarvis-Aktionen
KEY_AUTOMATED = "mha:learning:automated"  # F-053: Tracks automated entity+timeslot pairs

WEEKDAY_NAMES_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

# B8: Redis-Keys fuer abstrakte Konzepte
KEY_ABSTRACT_CONCEPTS = "mha:learning:abstract_concepts"
KEY_CONCEPT_OBSERVATIONS = "mha:learning:concept_observations"

# [16] Auto-Learning: Device→Scene Trigger
KEY_SCENE_ACTIVATIONS = "mha:learning:scene_activations"
KEY_SCENE_DEVICE_PATTERNS = "mha:learning:scene_device_patterns"
KEY_SCENE_DEVICE_SUGGESTED = "mha:learning:scene_device_suggested"


def _parse_person_prefix(action: str) -> tuple[str, str]:
    """Extrahiert Person-Prefix aus einem Redis-Action-Key.

    Format mit Person: "julia:light.wohnzimmer:on" → ("julia", "light.wohnzimmer:on")
    Format ohne:       "light.wohnzimmer:on"       → ("", "light.wohnzimmer:on")

    Erkennung: Erster Teil vor ':' hat keinen Punkt → ist Person-Name (Entity-IDs haben immer Punkte).
    """
    parts = action.split(":", 1)
    if len(parts) == 2 and "." not in parts[0]:
        return parts[0], parts[1]
    return "", action


class LearningObserver:
    """Beobachtet manuelle Aktionen und schlaegt Automatisierungen vor."""

    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        self._ollama = None
        self._notify_callback = None

        learn_cfg = yaml_config.get("learning", {})
        self.enabled = learn_cfg.get("enabled", True)
        self.min_repetitions = learn_cfg.get("min_repetitions", 3)
        self.time_window_minutes = learn_cfg.get("time_window_minutes", 30)

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis."""
        self.redis = redis_client
        logger.info("LearningObserver initialisiert (enabled: %s)", self.enabled)

    def set_notify_callback(self, callback):
        """Setzt den Callback fuer Vorschlaege."""
        self._notify_callback = callback

    def set_ollama(self, ollama_client):
        """Setzt den OllamaClient fuer LLM-basierte Berichte."""
        self._ollama = ollama_client
        logger.info("LearningObserver: LLM-Rewrite aktiviert")

    async def mark_jarvis_action(self, entity_id: str):
        """Markiert eine Aktion als von Jarvis ausgefuehrt (nicht manuell)."""
        if not self.redis:
            return
        # Kurzzeitiger Marker (30 Sek) um state_changed Events zu ignorieren
        await self.redis.setex(f"{JARVIS_ACTION_KEY}:{entity_id}", 30, "1")

    async def observe_state_change(self, entity_id: str, new_state: str, old_state: str,
                                   person: str = ""):
        """Beobachtet State-Changes und erkennt manuelle Aktionen.

        Wird von proactive.py bei jedem state_changed aufgerufen.
        Ignoriert Jarvis-gesteuerte Aenderungen.

        Args:
            entity_id: HA Entity-ID
            new_state: Neuer Zustand
            old_state: Alter Zustand
            person: Person die die Aktion ausgeloest hat (wenn bekannt)
        """
        if not self.enabled or not self.redis:
            return

        # Nur relevante Domains
        if not any(entity_id.startswith(d) for d in ["light.", "cover.", "climate.", "switch.", "media_player."]):
            return

        # Jarvis-Aktion? → Ignorieren
        jarvis_marker = await self.redis.get(f"{JARVIS_ACTION_KEY}:{entity_id}")
        if jarvis_marker:
            return

        # Triviale Aenderungen ignorieren
        if new_state in ("unavailable", "unknown") or old_state in ("unavailable", "unknown"):
            return

        try:
            now = datetime.now()
            hour = now.hour
            minute = now.minute
            weekday = now.weekday()

            # Aktion aufzeichnen — mit Person-Prefix wenn bekannt
            action_key = f"{entity_id}:{new_state}"
            person_prefix = f"{person}:" if person else ""
            time_slot = f"{hour:02d}:{(minute // 5) * 5:02d}"  # 5-Min-Slots

            # F-053: Cycle detection — skip entities+timeslots that have already been
            # automated via a previous suggestion. Without this, the automation fires
            # a state change, which the observer counts again, leading to duplicate
            # suggestions or infinite observe->suggest->automate->observe loops.
            automated_key = f"{KEY_AUTOMATED}:{person_prefix}{action_key}:{time_slot}"
            if await self.redis.get(automated_key):
                return

            action = {
                "entity_id": entity_id,
                "new_state": new_state,
                "time_slot": time_slot,
                "weekday": weekday,
                "timestamp": now.isoformat(),
                "person": person,
            }

            # In Redis-Liste speichern (max 5000 letzte Aktionen, 365 Tage)
            await self.redis.lpush(KEY_MANUAL_ACTIONS, json.dumps(action))
            await self.redis.ltrim(KEY_MANUAL_ACTIONS, 0, 4999)
            await self.redis.expire(KEY_MANUAL_ACTIONS, 365 * 86400)

            # Pattern-Check: Wurde diese Aktion schon oefter zur gleichen Zeit gemacht?
            await self._check_pattern(action_key, time_slot, entity_id, new_state, person=person)

            # Wochentag-spezifischer Pattern-Check
            await self._check_weekday_pattern(action_key, time_slot, weekday, entity_id, new_state, person=person)
        except Exception as e:
            logger.warning("Learning Observer state_change Fehler: %s", e)

    async def _check_pattern(self, action_key: str, time_slot: str,
                             entity_id: str, new_state: str, person: str = ""):
        """Prueft ob ein Muster erkannt wurde."""
        person_prefix = f"{person}:" if person else ""
        pattern_key = f"{KEY_PATTERNS}:{person_prefix}{action_key}:{time_slot}"

        # Zaehler erhoehen (Pipeline fuer atomares incr+expire)
        pipe = self.redis.pipeline()
        pipe.incr(pattern_key)
        pipe.ttl(pattern_key)
        incr_result, current_ttl = await pipe.execute()
        count = incr_result
        # TTL auf 365 Tage setzen (nur wenn noch keine TTL gesetzt)
        if current_ttl is None or current_ttl < 0:
            await self.redis.expire(pattern_key, 365 * 86400)

        # Genug Wiederholungen fuer einen Vorschlag?
        if count >= self.min_repetitions:
            # Schon vorgeschlagen?
            suggested_key = f"{KEY_SUGGESTED}:{person_prefix}{action_key}:{time_slot}"
            already_suggested = await self.redis.get(suggested_key)
            if already_suggested:
                return

            # Konflikt-Check: Wuerde die Automatisierung Geraete-Konflikte erzeugen?
            conflict_hint = ""
            try:
                from .state_change_log import StateChangeLog
                hints = StateChangeLog.check_action_dependencies(
                    entity_id, {"entity_id": entity_id, "state": new_state}, {}
                )
                if hints:
                    conflict_hint = hints[0]
            except Exception as e:
                logger.debug("Abhaengigkeitspruefung fehlgeschlagen: %s", e)

            # Als vorgeschlagen markieren (7 Tage Cooldown)
            await self.redis.setex(suggested_key, 7 * 86400, "1")

            # Vorschlag generieren
            friendly = entity_id.split(".", 1)[1].replace("_", " ").title()
            action_de = "eingeschaltet" if new_state == "on" else "ausgeschaltet" if new_state == "off" else new_state

            title = get_person_title()
            person_hint = f" ({person})" if person else ""
            message = (
                f"{title}, mir ist aufgefallen, dass du{person_hint} {friendly} jeden Tag "
                f"um {time_slot} Uhr {action_de}. "
                f"Soll ich das automatisieren?"
            )
            if conflict_hint:
                message += f" Beachte: {conflict_hint}"

            logger.info("Learning: Muster erkannt - %s um %s (%dx, Person: %s)",
                        action_key, time_slot, count, person or "global")

            if self._notify_callback:
                await self._notify_callback({
                    "message": message,
                    "type": "learning_suggestion",
                    "entity_id": entity_id,
                    "new_state": new_state,
                    "time_slot": time_slot,
                    "count": count,
                    "person": person,
                })

    async def _check_weekday_pattern(self, action_key: str, time_slot: str,
                                     weekday: int, entity_id: str, new_state: str,
                                     person: str = ""):
        """Prueft Wochentag-spezifische Muster (z.B. nur Werktags)."""
        person_prefix = f"{person}:" if person else ""
        # F-053: Cycle detection for weekday-specific patterns
        automated_key = f"{KEY_AUTOMATED}:{person_prefix}{action_key}:{time_slot}:{weekday}"
        if await self.redis.get(automated_key):
            return

        pattern_key = f"{KEY_WEEKDAY_PATTERNS}:{person_prefix}{action_key}:{time_slot}:{weekday}"

        count = await self.redis.incr(pattern_key)
        if count == 1:
            await self.redis.expire(pattern_key, 60 * 86400)  # 60 Tage TTL

        # Erst ab 3 Wiederholungen am gleichen Wochentag
        if count < self.min_repetitions:
            return

        # Taeglich schon vorgeschlagen? Dann Wochentag-Vorschlag ueberspringen
        daily_suggested = await self.redis.get(f"{KEY_SUGGESTED}:{person_prefix}{action_key}:{time_slot}")
        if daily_suggested:
            return

        suggested_key = f"{KEY_SUGGESTED}:weekday:{person_prefix}{action_key}:{time_slot}:{weekday}"
        if await self.redis.get(suggested_key):
            return

        await self.redis.setex(suggested_key, 14 * 86400, "1")  # 14 Tage Cooldown

        friendly = entity_id.split(".", 1)[1].replace("_", " ").title()
        action_de = "eingeschaltet" if new_state == "on" else "ausgeschaltet" if new_state == "off" else new_state
        day_name = WEEKDAY_NAMES_DE[weekday]

        title = get_person_title()
        person_hint = f" ({person})" if person else ""
        message = (
            f"{title}, du{person_hint} schaltest {friendly} jeden {day_name} "
            f"um {time_slot} Uhr {action_de}. "
            f"Soll ich das fuer {day_name}s automatisieren?"
        )

        logger.info("Learning: Wochentag-Muster erkannt - %s am %s um %s (%dx, Person: %s)",
                     action_key, day_name, time_slot, count, person or "global")

        if self._notify_callback:
            await self._notify_callback({
                "message": message,
                "type": "learning_suggestion",
                "entity_id": entity_id,
                "new_state": new_state,
                "time_slot": time_slot,
                "weekday": weekday,
                "weekday_name": day_name,
                "count": count,
                "person": person,
            })

    async def handle_response(self, entity_id: str, time_slot: str,
                              accepted: bool, weekday: int = -1,
                              person: str = "") -> str:
        """Verarbeitet die Benutzer-Antwort auf einen Automatisierungs-Vorschlag.

        Args:
            entity_id: Die Entity die automatisiert werden soll
            time_slot: Der Zeitslot (z.B. "22:00")
            accepted: Ob der Vorschlag akzeptiert wurde
            weekday: Wochentag (-1 = taeglich)
            person: Person fuer die der Vorschlag gilt

        Returns:
            Antwort-Text fuer den Benutzer
        """
        if not self.redis:
            return "Mein Gedaechtnis ist gerade nicht ansprechbar. Redis antwortet nicht."

        response = {
            "entity_id": entity_id,
            "time_slot": time_slot,
            "weekday": weekday,
            "accepted": accepted,
            "timestamp": datetime.now().isoformat(),
            "person": person,
        }
        await self.redis.lpush(KEY_RESPONSES, json.dumps(response))
        await self.redis.ltrim(KEY_RESPONSES, 0, 499)
        await self.redis.expire(KEY_RESPONSES, 365 * 86400)

        if not accepted:
            logger.info("Learning: Vorschlag abgelehnt fuer %s um %s", entity_id, time_slot)
            return f"Verstanden, {get_person_title()}. Ich werde das nicht automatisieren."

        logger.info("Learning: Vorschlag akzeptiert fuer %s um %s (Wochentag: %d)",
                     entity_id, time_slot, weekday)

        # F-053: Mark this entity+timeslot as automated to prevent feedback loops.
        # The observer will skip state changes matching automated patterns, breaking
        # the observe->suggest->automate->observe cycle.
        # Use long TTL (90 days) so the marker outlives the automation.
        person_prefix = f"{person}:" if person else ""
        states_to_mark = ["on", "off"]  # Mark both directions to avoid partial loops
        for state in states_to_mark:
            automated_key = f"{KEY_AUTOMATED}:{person_prefix}{entity_id}:{state}:{time_slot}"
            await self.redis.setex(automated_key, 90 * 86400, "1")
        if weekday >= 0:
            for state in states_to_mark:
                automated_key = f"{KEY_AUTOMATED}:{person_prefix}{entity_id}:{state}:{time_slot}:{weekday}"
                await self.redis.setex(automated_key, 90 * 86400, "1")

        return (
            f"Sehr gut, {get_person_title()}. Ich habe die Automatisierung vorgemerkt. "
            f"Die Self-Automation wird {entity_id.split('.', 1)[1].replace('_', ' ').title()} "
            f"ab jetzt automatisch um {time_slot} Uhr schalten."
        )

    async def get_learned_patterns(self, person: str = "") -> list[dict]:
        """Gibt erkannte Muster zurueck, optional gefiltert nach Person.

        Args:
            person: Wenn gesetzt, nur Muster dieser Person zurueckgeben.
                    Leerer String = alle Muster (global + personenspezifisch).

        Returns:
            Liste von Muster-Dicts mit entity, time_slot, count, weekday, person
        """
        if not self.redis:
            return []

        patterns = []

        # Tages-Muster lesen
        # Key: mha:learning:patterns:[person:]entity:state:HH:MM
        # Achtung: time_slot ist HH:MM (enthaelt Doppelpunkt) → rsplit(":", 2)
        try:
            # Phase 1: Alle Keys per SCAN sammeln (kein GET pro Key)
            all_keys: list[str] = []
            cursor = 0
            while True:
                cursor, keys = await self.redis.scan(
                    cursor, match=f"{KEY_PATTERNS}:*", count=200
                )
                for key in keys:
                    all_keys.append(key.decode() if isinstance(key, bytes) else key)
                if cursor == 0:
                    break

            # Phase 2: Batch-GET via mget statt N einzelner GETs
            if all_keys:
                values = await self.redis.mget(*all_keys)
                for key_str, count in zip(all_keys, values):
                    if not count:
                        continue
                    count_val = int(count)
                    if count_val < 2:
                        continue
                    suffix = key_str.replace(f"{KEY_PATTERNS}:", "")
                    parts = suffix.rsplit(":", 2)
                    if len(parts) != 3 or not parts[1].isdigit():
                        continue
                    action, ts_hour, ts_min = parts
                    time_slot = f"{ts_hour}:{ts_min}"

                    pattern_person, entity_action = _parse_person_prefix(action)

                    if person and pattern_person != person:
                        continue

                    entity_state = entity_action.rsplit(":", 1)
                    patterns.append({
                        "action": entity_action,
                        "entity": entity_state[0] if len(entity_state) > 1 else entity_action,
                        "time_slot": time_slot,
                        "count": count_val,
                        "weekday": -1,
                        "person": pattern_person,
                    })
        except Exception as e:
            logger.warning("L4: Daily patterns SCAN failed: %s", e)

        # Wochentag-Muster lesen
        # Key: mha:learning:weekday_patterns:[person:]entity:state:HH:MM:weekday
        try:
            all_keys = []
            cursor = 0
            while True:
                cursor, keys = await self.redis.scan(
                    cursor, match=f"{KEY_WEEKDAY_PATTERNS}:*", count=200
                )
                for key in keys:
                    all_keys.append(key.decode() if isinstance(key, bytes) else key)
                if cursor == 0:
                    break

            if all_keys:
                values = await self.redis.mget(*all_keys)
                for key_str, count in zip(all_keys, values):
                    if not count:
                        continue
                    count_val = int(count)
                    if count_val < 2:
                        continue
                    suffix = key_str.replace(f"{KEY_WEEKDAY_PATTERNS}:", "")
                    parts = suffix.rsplit(":", 3)
                    if len(parts) != 4 or not parts[3].isdigit():
                        continue
                    action, ts_hour, ts_min, weekday_str = parts
                    time_slot = f"{ts_hour}:{ts_min}"
                    weekday_val = int(weekday_str)

                    pattern_person, entity_action = _parse_person_prefix(action)

                    if person and pattern_person != person:
                        continue

                    entity_state = entity_action.rsplit(":", 1)
                    patterns.append({
                        "action": entity_action,
                        "entity": entity_state[0] if len(entity_state) > 1 else entity_action,
                        "time_slot": time_slot,
                        "count": count_val,
                        "weekday": weekday_val,
                        "person": pattern_person,
                    })
        except Exception as e:
            logger.warning("L5: Weekday patterns SCAN failed: %s", e)

        # Nach Count sortieren (haeufigste zuerst)
        patterns.sort(key=lambda p: p["count"], reverse=True)
        return patterns[:20]  # Max 20

    # ------------------------------------------------------------------
    # Feature 8: Lern-Transparenz — "Was hast du gelernt?"
    # ------------------------------------------------------------------

    async def get_learning_report(self, period: str = "week") -> dict:
        """Erstellt einen Lern-Bericht ueber erkannte Muster und Vorschlaege.

        Args:
            period: Zeitraum ("week" oder "month")

        Returns:
            Dict mit patterns, total_observations, suggestions_made, accepted, declined
        """
        if not self.redis:
            return {
                "patterns": [],
                "total_observations": 0,
                "suggestions_made": 0,
                "accepted": 0,
                "declined": 0,
            }

        patterns = await self.get_learned_patterns()

        # Beobachtungen zaehlen
        total_observations = await self.redis.llen(KEY_MANUAL_ACTIONS) or 0

        # Vorschlag-Antworten auswerten
        suggestions_made = 0
        accepted = 0
        declined = 0

        try:
            responses_raw = await self.redis.lrange(KEY_RESPONSES, 0, 499)
            for raw in responses_raw:
                try:
                    entry = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                    suggestions_made += 1
                    if entry.get("accepted"):
                        accepted += 1
                    else:
                        declined += 1
                except (json.JSONDecodeError, AttributeError):
                    continue
        except Exception as e:
            logger.warning("Lern-Report Antworten lesen fehlgeschlagen: %s", e)

        return {
            "patterns": patterns,
            "total_observations": int(total_observations),
            "suggestions_made": suggestions_made,
            "accepted": accepted,
            "declined": declined,
        }

    def format_learning_report(self, report: dict) -> str:
        """Formatiert einen Lern-Bericht als natuerlichen Text.

        Args:
            report: Dict aus get_learning_report()

        Returns:
            Formatierter Text fuer LLM oder direkte Ausgabe
        """
        lines = []

        patterns = report.get("patterns", [])
        total = report.get("total_observations", 0)
        accepted = report.get("accepted", 0)
        declined = report.get("declined", 0)
        suggestions = report.get("suggestions_made", 0)

        if not patterns and total == 0:
            return "Noch keine Verhaltensmuster erfasst. Zu frueh fuer belastbare Daten."

        lines.append(f"{total} manuelle Aktionen erfasst.")

        if patterns:
            lines.append(f"\n{len(patterns)} erkannte Muster:")
            for p in patterns[:10]:
                entity = p.get("entity", p.get("action", "?"))
                friendly = entity.split(".", 1)[-1].replace("_", " ").title() if "." in entity else entity
                time_slot = p.get("time_slot", "?")
                count = p.get("count", 0)
                weekday = p.get("weekday", -1)
                if weekday >= 0 and weekday < len(WEEKDAY_NAMES_DE):
                    lines.append(f"- {friendly} um {time_slot} Uhr ({WEEKDAY_NAMES_DE[weekday]}s, {count}x)")
                else:
                    lines.append(f"- {friendly} um {time_slot} Uhr (taeglich, {count}x)")

        if suggestions > 0:
            lines.append(f"\n{suggestions} Vorschläge gemacht: {accepted} akzeptiert, {declined} abgelehnt.")

        return "\n".join(lines)

    async def format_learning_report_llm(self, report: dict) -> str:
        """LLM-basierte Version von format_learning_report.

        Generiert einen natuerlichsprachlichen Bericht im JARVIS-Stil
        statt einer Aufzaehlung. Fallback auf Template-Version bei Fehler.
        """
        # Template-Fallback generieren
        fallback = self.format_learning_report(report)
        if not self._ollama:
            return fallback
        cfg = yaml_config.get("learning", {})
        if not cfg.get("llm_report", True):
            return fallback
        try:
            from .config import settings
            from .ollama_client import strip_think_tags
            prompt = (
                "Du bist JARVIS, ein britischer Smart-Home-Butler. "
                "Fasse diesen Lern-Bericht in 3-5 Saetzen zusammen. "
                "Ich-Form, trocken-humorvoll, konkret mit Zahlen. "
                "Keine Aufzaehlung — fliessender Text.\n\n"
                f"Rohdaten:\n{fallback}\n\n"
                "Bericht:"
            )
            response = await asyncio.wait_for(
                self._ollama.generate(
                    prompt=prompt,
                    model=settings.model_fast,
                    temperature=0.5,
                    max_tokens=500,
                ),
                timeout=4.0,
            )
            text = strip_think_tags(response or "").strip()
            if text and len(text) > 20:
                return text
        except Exception as e:
            logger.debug("LearningObserver LLM-Report fehlgeschlagen: %s", e)
        return fallback

    # ------------------------------------------------------------------
    # B8: Dynamic Skill Acquisition — Abstrakte Konzepte
    # ------------------------------------------------------------------

    async def observe_abstract_action(self, actions: list[dict], trigger_text: str,
                                       person: str = ""):
        """B8: Beobachtet zusammengehoerige Aktionen und erkennt abstrakte Konzepte.

        Wenn ein User z.B. sagt "Feierabend" und dann Licht dimmt, Musik an,
        Heizung hoch → erkennt das als Konzept "Feierabend".

        Args:
            actions: Liste der ausgefuehrten Aktionen [{entity_id, new_state, ...}]
            trigger_text: Der User-Text der die Aktionen ausgeloest hat
            person: Person die das Konzept nutzt
        """
        if not self.enabled or not self.redis:
            return

        _cfg = yaml_config.get("dynamic_skills", {})
        if not _cfg.get("enabled", True):
            return

        # Mindestens 2 Aktionen fuer ein abstraktes Konzept
        if len(actions) < 2:
            return

        # Konzept-Erkennung: Trigger-Text auf abstrakte Begriffe pruefen
        _concept_name = self._extract_concept_name(trigger_text)
        if not _concept_name:
            return

        try:
            now = datetime.now()
            person_prefix = f"{person}:" if person else ""
            concept_key = f"{KEY_CONCEPT_OBSERVATIONS}:{person_prefix}{_concept_name}"

            # Aktionen serialisieren
            _action_set = sorted([
                f"{a.get('entity_id', '')}:{a.get('new_state', '')}"
                for a in actions if a.get("entity_id")
            ])
            _action_hash = "|".join(_action_set)

            observation = json.dumps({
                "actions": _action_set,
                "action_hash": _action_hash,
                "trigger": trigger_text[:200],
                "person": person,
                "hour": now.hour,
                "weekday": now.weekday(),
                "timestamp": now.isoformat(),
            }, ensure_ascii=False)

            await self.redis.lpush(concept_key, observation)
            await self.redis.ltrim(concept_key, 0, 29)
            await self.redis.expire(concept_key, 90 * 86400)

            # Pruefen ob genug Beobachtungen fuer Konzept-Erstellung
            _min_obs = _cfg.get("min_observations", 3)
            obs_count = await self.redis.llen(concept_key)
            if obs_count >= _min_obs:
                await self._maybe_create_concept(
                    _concept_name, concept_key, person, _cfg
                )

        except Exception as e:
            logger.debug("B8 Abstract Action Observation Fehler: %s", e)

    def _extract_concept_name(self, text: str) -> str:
        """B8: Extrahiert einen abstrakten Konzeptnamen aus dem User-Text.

        Erkennt Ausdruecke wie "Feierabend", "Filmabend", "Gute Nacht",
        "Morgenroutine" etc.
        """
        text_lower = text.lower().strip()

        # Bekannte abstrakte Konzepte (erweiterbar)
        _CONCEPT_TRIGGERS = {
            "feierabend": "feierabend",
            "filmabend": "filmabend",
            "gute nacht": "gute_nacht",
            "guten morgen": "guten_morgen",
            "morgenroutine": "morgenroutine",
            "abendroutine": "abendroutine",
            "party": "party",
            "partymodus": "party",
            "romantisch": "romantisch",
            "date night": "date_night",
            "kochmodus": "kochmodus",
            "kochen": "kochmodus",
            "arbeitsmodus": "arbeitsmodus",
            "konzentration": "konzentration",
            "entspannung": "entspannung",
            "chillen": "entspannung",
            "gaming": "gaming",
            "aufwachen": "aufwachen",
            "schlafenszeit": "gute_nacht",
            "gaeste kommen": "gaeste",
            "besuch kommt": "gaeste",
        }

        for trigger, concept in _CONCEPT_TRIGGERS.items():
            if trigger in text_lower:
                return concept

        return ""

    async def _maybe_create_concept(self, concept_name: str, obs_key: str,
                                     person: str, cfg: dict):
        """B8: Prueft Beobachtungen und erstellt ggf. ein abstraktes Konzept."""
        try:
            raw_obs = await self.redis.lrange(obs_key, 0, 29)
            if not raw_obs:
                return

            observations = []
            for r in raw_obs:
                try:
                    obs = json.loads(r) if isinstance(r, str) else json.loads(r.decode())
                    observations.append(obs)
                except (json.JSONDecodeError, TypeError):
                    continue

            if len(observations) < cfg.get("min_observations", 3):
                return

            # Pruefen ob Konzept schon existiert
            person_prefix = f"{person}:" if person else ""
            existing = await self.redis.hget(KEY_ABSTRACT_CONCEPTS, f"{person_prefix}{concept_name}")
            if existing:
                return

            # Kern-Aktionen extrahieren (Aktionen die in >50% der Beobachtungen vorkommen)
            from collections import Counter
            _action_counter = Counter()
            for obs in observations:
                for action in obs.get("actions", []):
                    _action_counter[action] += 1

            _threshold = len(observations) * 0.5
            _core_actions = [
                action for action, count in _action_counter.items()
                if count >= _threshold
            ]

            if len(_core_actions) < 2:
                return

            # Zeitanalyse: Typische Stunde
            hours = [obs.get("hour", 12) for obs in observations]
            _avg_hour = round(sum(hours) / len(hours))

            # Wochentag-Analyse
            weekdays = [obs.get("weekday", 0) for obs in observations]
            weekday_counts = Counter(weekdays)
            _primary_days = [d for d, c in weekday_counts.most_common(3) if c >= 2]

            concept = {
                "name": concept_name,
                "core_actions": _core_actions,
                "typical_hour": _avg_hour,
                "primary_weekdays": _primary_days,
                "observation_count": len(observations),
                "person": person,
                "created": datetime.now().isoformat(),
            }

            await self.redis.hset(
                KEY_ABSTRACT_CONCEPTS,
                f"{person_prefix}{concept_name}",
                json.dumps(concept, ensure_ascii=False),
            )
            await self.redis.expire(KEY_ABSTRACT_CONCEPTS, 365 * 86400)

            logger.info(
                "B8: Abstraktes Konzept '%s' erstellt (%d Kern-Aktionen, %d Beobachtungen, Person: %s)",
                concept_name, len(_core_actions), len(observations), person or "global",
            )

            # Vorschlag an User senden
            if self._notify_callback:
                friendly_actions = []
                for a in _core_actions[:5]:
                    parts = a.split(":", 1)
                    if len(parts) == 2:
                        entity = parts[0].split(".", 1)[-1].replace("_", " ").title()
                        friendly_actions.append(f"{entity} → {parts[1]}")

                title = get_person_title()
                msg = (
                    f"{title}, ich habe bemerkt, dass '{concept_name}' fuer dich "
                    f"folgendes bedeutet: {', '.join(friendly_actions)}. "
                    f"Soll ich mir das so merken?"
                )
                await self._notify_callback({
                    "message": msg,
                    "type": "concept_learned",
                    "concept": concept_name,
                    "actions": _core_actions,
                    "person": person,
                })

        except Exception as e:
            logger.debug("B8 Concept Creation Fehler: %s", e)

    async def get_concept(self, concept_name: str, person: str = "") -> Optional[dict]:
        """B8: Laedt ein abstraktes Konzept.

        Args:
            concept_name: Name des Konzepts (z.B. "feierabend")
            person: Person-spezifisch oder global

        Returns:
            Konzept-Dict oder None
        """
        if not self.redis:
            return None
        try:
            person_prefix = f"{person}:" if person else ""
            raw = await self.redis.hget(KEY_ABSTRACT_CONCEPTS, f"{person_prefix}{concept_name}")
            if not raw:
                # Fallback: Globales Konzept wenn kein person-spezifisches existiert
                if person:
                    raw = await self.redis.hget(KEY_ABSTRACT_CONCEPTS, concept_name)
            if raw:
                return json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode())
        except Exception as e:
            logger.debug("B8 Get Concept Fehler: %s", e)
        return None

    async def get_all_concepts(self, person: str = "") -> list[dict]:
        """B8: Listet alle gelernten Konzepte auf."""
        if not self.redis:
            return []
        try:
            all_data = await self.redis.hgetall(KEY_ABSTRACT_CONCEPTS)
            concepts = []
            for key, val in all_data.items():
                key_str = key.decode() if isinstance(key, bytes) else key
                if person and not key_str.startswith(f"{person}:") and ":" in key_str:
                    continue
                try:
                    concept = json.loads(val) if isinstance(val, str) else json.loads(val.decode())
                    concepts.append(concept)
                except (json.JSONDecodeError, TypeError):
                    continue
            return concepts
        except Exception as e:
            logger.debug("B8 Get All Concepts Fehler: %s", e)
            return []

    # ------------------------------------------------------------------
    # B12: Proaktives Selbst-Lernen — bei Wissenslücken aktiv fragen
    # ------------------------------------------------------------------

    _B12_COOLDOWN_KEY = "mha:learning:b12_last_ask"

    async def observe_knowledge_gap(self, user_text: str, tool_failed: bool = False,
                                     no_tool_match: bool = False, person: str = ""):
        """B12: Erkennt Wissenslücken und fragt proaktiv nach.

        Wird aufgerufen wenn:
        - Ein Tool fehlschlaegt (tool_failed=True)
        - Kein passendes Tool gefunden wurde (no_tool_match=True)
        - Der User etwas sagt das JARVIS nicht einordnen kann

        Args:
            user_text: Was der User gesagt hat
            tool_failed: Ob ein Tool-Call fehlgeschlagen ist
            no_tool_match: Ob kein Tool gefunden wurde
            person: Aktuelle Person
        """
        if not self.enabled or not self.redis or not self._notify_callback:
            return

        _sl_cfg = yaml_config.get("self_learning", {})
        if not _sl_cfg.get("enabled", True):
            return

        # Cooldown prüfen (max 1 Lern-Frage pro 30 Min)
        cooldown_min = _sl_cfg.get("cooldown_minutes", 30)
        try:
            last_ask = await self.redis.get(self._B12_COOLDOWN_KEY)
            if last_ask:
                last_dt = datetime.fromisoformat(last_ask.decode() if isinstance(last_ask, bytes) else last_ask)
                if (datetime.now() - last_dt).total_seconds() < cooldown_min * 60:
                    return
        except Exception as e:
            logger.debug("Cooldown-Pruefung fehlgeschlagen: %s", e)

        title = get_person_title(person) if person else get_person_title()

        message = None
        if tool_failed:
            message = (
                f"{title}, das hat nicht funktioniert wie erwartet. "
                f"Gibt es etwas das ich ueber dieses Geraet wissen sollte?"
            )
        elif no_tool_match:
            # Nur fragen wenn der User-Text kein einfacher Chat ist
            if len(user_text.split()) >= 4:
                message = (
                    f"Ich bin nicht sicher ob ich das richtig verstanden habe, {title}. "
                    f"Kannst du mir erklaeren was du mit '{user_text[:80]}' meinst?"
                )

        if message:
            try:
                await self.redis.set(
                    self._B12_COOLDOWN_KEY,
                    datetime.now().isoformat(),
                    ex=cooldown_min * 60,
                )
                await self._notify_callback({
                    "message": message,
                    "type": "knowledge_gap",
                    "person": person,
                })
            except Exception as e:
                logger.debug("B12: Lern-Frage fehlgeschlagen: %s", e)

    # ── [16] Auto-Learning: Device→Scene Trigger ─────────────────────

    async def observe_scene_activation(self, scene_name: str, person: str = ""):
        """[16] Trackt Szenen-Aktivierungen und korreliert mit vorherigen Device-Changes.

        Wenn nach einem bestimmten Device-Wechsel wiederholt die gleiche Szene
        aktiviert wird (>=3x), schlaegt Jarvis einen automatischen Trigger vor:
        "Soll ich Filmabend automatisch starten wenn der TV angeht?"

        Args:
            scene_name: Name der aktivierten Szene (z.B. "filmabend")
            person: Person die die Szene aktiviert hat
        """
        if not self.enabled or not self.redis:
            return

        scene_cfg = yaml_config.get("scenes", {})
        if not scene_cfg.get("auto_learning", {}).get("enabled", True):
            return

        try:
            # Letzte manuelle Device-Aenderungen der letzten 5 Minuten holen
            raw_actions = await self.redis.lrange(KEY_MANUAL_ACTIONS, 0, 19)
            if not raw_actions:
                return

            import time as _time
            now = _time.time()
            lookback_seconds = 300  # 5 Minuten

            recent_triggers = []
            for raw in raw_actions:
                try:
                    action = json.loads(raw if isinstance(raw, str) else raw.decode())
                    ts = datetime.fromisoformat(action.get("timestamp", ""))
                    age = now - ts.timestamp()
                    if age <= lookback_seconds:
                        eid = action.get("entity_id", "")
                        # Nur relevante Trigger-Domains (TV, Buttons, Switches)
                        if any(eid.startswith(d) for d in (
                            "media_player.", "remote.", "switch.",
                            "binary_sensor.", "input_boolean.",
                        )):
                            recent_triggers.append(eid)
                except Exception as e:
                    logger.debug("Szenen-Trigger Analyse fehlgeschlagen: %s", e)
                    continue

            if not recent_triggers:
                return

            # Fuer jeden Trigger-Candidate: Pattern zaehlen
            for trigger_entity in recent_triggers:
                pattern_key = (
                    f"{KEY_SCENE_DEVICE_PATTERNS}:{trigger_entity}:{scene_name}"
                )

                pipe = self.redis.pipeline()
                pipe.incr(pattern_key)
                pipe.ttl(pattern_key)
                incr_result, current_ttl = await pipe.execute()
                count = incr_result

                if current_ttl is None or current_ttl < 0:
                    await self.redis.expire(pattern_key, 60 * 86400)  # 60 Tage

                min_reps = scene_cfg.get(
                    "auto_learning", {},
                ).get("min_repetitions", self.min_repetitions)

                if count < min_reps:
                    continue

                # Schon vorgeschlagen oder schon konfiguriert?
                suggested_key = (
                    f"{KEY_SCENE_DEVICE_SUGGESTED}:{trigger_entity}:{scene_name}"
                )
                if await self.redis.get(suggested_key):
                    continue

                # Schon in device_trigger_map konfiguriert?
                existing_map = scene_cfg.get("device_trigger_map", {})
                if trigger_entity in existing_map:
                    existing_scenes = existing_map[trigger_entity]
                    if scene_name in existing_scenes:
                        continue

                # Als vorgeschlagen markieren (14 Tage Cooldown)
                await self.redis.setex(suggested_key, 14 * 86400, "1")

                # Vorschlag generieren
                friendly_entity = (
                    trigger_entity.split(".", 1)[1].replace("_", " ").title()
                )
                scene_label = scene_name.replace("_", " ").title()
                title = get_person_title(person) if person else get_person_title()

                message = (
                    f"{title}, mir ist aufgefallen, dass du nach dem Einschalten "
                    f"von {friendly_entity} oft '{scene_label}' aktivierst "
                    f"({count}x in den letzten Wochen). "
                    f"Soll ich '{scene_label}' automatisch starten, "
                    f"wenn {friendly_entity} eingeschaltet wird?"
                )

                logger.info(
                    "[16] Scene-Device-Pattern erkannt: %s → %s (%dx)",
                    trigger_entity, scene_name, count,
                )

                if self._notify_callback:
                    await self._notify_callback({
                        "message": message,
                        "type": "scene_device_suggestion",
                        "trigger_entity": trigger_entity,
                        "scene_name": scene_name,
                        "count": count,
                        "person": person,
                    })
                # Nur einen Vorschlag pro Aktivierung
                break

        except Exception as e:
            logger.debug("[16] Scene-Device-Learning Fehler: %s", e)
