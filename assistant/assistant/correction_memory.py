"""
Correction Memory - Strukturiertes Korrektur-Gedaechtnis.

Speichert User-Korrekturen strukturiert: Original-Aktion + Korrektur + Kontext.
Leitet Regeln ab wenn gleiche Korrektur-Muster 2+ mal auftreten.
Injiziert relevante Korrekturen als LLM-Kontext bei zukuenftigen Aktionen.

Sicherheit: Read-only Memory. Beeinflusst nur LLM-Kontext. Max 200 Eintraege.
"""

import json
import logging
import re
import time
from datetime import datetime
from typing import Optional

from .config import yaml_config

logger = logging.getLogger(__name__)

# Injection-Schutz: Gleiches Pattern wie context_builder.py
_INJECTION_PATTERN = re.compile(
    r'\[(?:SYSTEM|INSTRUCTION|OVERRIDE|ADMIN|COMMAND|PROMPT|ROLE)\b'
    r'|IGNORE\s+(?:ALL\s+)?(?:PREVIOUS\s+)?INSTRUCTIONS'
    r'|SYSTEM\s*(?:MODE|OVERRIDE|INSTRUCTION)'
    r'|<\/?(?:system|instruction|admin|role|prompt)\b',
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
        self._cfg = yaml_config.get("correction_memory", {})
        self._max_entries = self._cfg.get("max_entries", 200)
        self._max_context = self._cfg.get("max_context_entries", 3)
        self._rules_created_today = 0
        self._last_rules_day = ""

    async def initialize(self, redis_client):
        """Initialisiert mit Redis Client."""
        self.redis = redis_client
        self.enabled = self._cfg.get("enabled", True) and self.redis is not None
        logger.info("CorrectionMemory initialisiert (enabled=%s)", self.enabled)

    async def store_correction(self, original_action: str, original_args: dict,
                               correction_text: str, corrected_args: Optional[dict] = None,
                               person: str = "", room: str = ""):
        """Speichert eine strukturierte Korrektur."""
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
            "timestamp": datetime.now().isoformat(),
            "hour": datetime.now().hour,
        }

        await self.redis.lpush(
            "mha:correction_memory:entries",
            json.dumps(entry, ensure_ascii=False),
        )
        await self.redis.ltrim("mha:correction_memory:entries", 0, self._max_entries - 1)
        await self.redis.expire("mha:correction_memory:entries", 180 * 86400)

        logger.info("Korrektur gespeichert: %s -> %s (Person: %s)",
                     original_action, clean_text[:60], person or "unbekannt")

        # Regel-Ableitung pruefen
        await self._update_rules(entry)

    async def get_relevant_corrections(self, action_type: str = "",
                                       args: Optional[dict] = None,
                                       person: str = "") -> Optional[str]:
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
            current_hour = datetime.now().hour
            entry_hour = entry.get("hour", 12)
            hour_diff = min(abs(current_hour - entry_hour), 24 - abs(current_hour - entry_hour))
            if hour_diff <= 2:
                score += 0.5

            if score > 0:
                scored.append((score, entry))

        if not scored:
            return None

        # Top N nach Score sortieren
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:self._max_context]

        lines = ["BISHERIGE KORREKTUREN (beachte diese):"]
        for _, entry in top:
            text = entry.get("correction_text", "")
            action = entry.get("original_action", "")
            lines.append(f"- Bei '{action}': {text}")

        return "\n".join(lines)

    async def get_active_rules(self, action_type: str = "",
                               person: str = "") -> list[dict]:
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
            decayed_conf = rule.get("confidence", 0.5) - (age_days * CONFIDENCE_DECAY_PER_DAY)

            if decayed_conf < 0.4:
                # Regel abgelaufen — loeschen
                await self.redis.hdel("mha:correction_memory:rules", key)
                continue

            rule["confidence"] = round(decayed_conf, 3)

            # Filter: Aktionstyp und Person
            if action_type and rule.get("trigger") and rule["trigger"] != action_type:
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
            if orig_room and any(w in corr_text for w in ["zimmer", "raum", "kueche", "bad"]):
                pattern_type = "room_confusion"
            elif any(w in corr_text for w in ["hell", "dunkel", "laut", "leise", "grad", "temperatur"]):
                pattern_type = "param_preference"
            elif any(w in corr_text for w in ["nicht", "nein", "falsch"]):
                pattern_type = "wrong_device"

            key = f"{action}:{pattern_type}"
            if key not in patterns:
                patterns[key] = {"action": action, "type": pattern_type, "count": 0, "examples": []}
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

    async def _update_rules(self, new_entry: dict):
        """Wenn gleiches Korrektur-Muster 2+ mal → Regel ableiten."""
        if not self.redis:
            return

        # Rate Limit: Max N Regeln pro Tag
        today = datetime.now().strftime("%Y-%m-%d")
        if self._last_rules_day != today:
            self._rules_created_today = 0
            self._last_rules_day = today
        if self._rules_created_today >= RULES_PER_DAY_LIMIT:
            return

        # Aktuelle Eintraege laden und Muster suchen
        entries = await self._get_entries(limit=50)
        action = new_entry.get("original_action", "")
        if not action:
            return

        # Gleichartige Korrekturen zaehlen
        similar = []
        for e in entries:
            if e.get("original_action") != action:
                continue
            # Einfacher Aehnlichkeitscheck: Raum-basiert
            orig_room = e.get("original_args", {}).get("room", "")
            new_orig_room = new_entry.get("original_args", {}).get("room", "")
            if orig_room and new_orig_room and orig_room == new_orig_room:
                similar.append(e)

        if len(similar) < 2:
            return

        # Regel ableiten
        rule_key = f"{action}:{new_entry.get('original_args', {}).get('room', 'unknown')}"

        # Bestehende Regeln zaehlen
        existing_count = await self.redis.hlen("mha:correction_memory:rules")
        if existing_count and existing_count >= MAX_RULES:
            return

        # Haeufigsten Korrektur-Text finden
        correction_texts = [e.get("correction_text", "") for e in similar if e.get("correction_text")]
        if not correction_texts:
            return

        # Einfache Regel aus Template (NICHT LLM-generiert = keine Prompt Injection)
        hour = new_entry.get("hour", 12)
        time_hint = "abends" if hour >= 18 else ("morgens" if hour < 10 else "tagsueber")
        room = new_entry.get("original_args", {}).get("room", "")

        rule_text = f"Bei '{action}' {time_hint}: User korrigiert oft (Raum: {room})."
        rule_text = rule_text[:MAX_RULE_TEXT_LEN]

        confidence = min(1.0, 0.5 + len(similar) * 0.15)

        rule = {
            "type": "room_preference",
            "trigger": action,
            "condition": f"hour {'>=18' if hour >= 18 else ('<10' if hour < 10 else '10-18')}",
            "learned": f"room = {room}",
            "confidence": round(confidence, 2),
            "count": len(similar),
            "text": rule_text,
            "created_ts": time.time(),
            "person": new_entry.get("person", ""),
        }

        await self.redis.hset(
            "mha:correction_memory:rules",
            rule_key,
            json.dumps(rule, ensure_ascii=False),
        )
        await self.redis.expire("mha:correction_memory:rules", 365 * 86400)

        self._rules_created_today += 1
        logger.info("Neue Regel: %s (confidence: %.2f)", rule_text, confidence)

        # MCU-Persoenlichkeit: Lern-Bestaetigung in Queue pushen
        try:
            await self.redis.rpush("mha:learning_ack:pending", rule_text)
            # Max 10 pending, aelteste verwerfen
            await self.redis.ltrim("mha:learning_ack:pending", -10, -1)
        except Exception:
            pass

    def format_rules_for_prompt(self, rules: list[dict]) -> str:
        """Formatiert Regeln als Prompt-Abschnitt (Feature 7: Prompt Self-Refinement)."""
        if not rules:
            return ""

        lines = ["GELERNTE PRAEFERENZEN:"]
        for rule in rules[:5]:
            text = rule.get("text", "")
            confidence = rule.get("confidence", 0)
            if text and len(text) <= MAX_RULE_TEXT_LEN and confidence >= MIN_CONFIDENCE_FOR_RULE:
                # Sanitize bevor es in den Prompt geht
                clean = _sanitize(text)
                if clean:
                    lines.append(f"- {clean}")

        if len(lines) <= 1:
            return ""

        return "\n".join(lines)


def _sanitize(text: str, max_len: int = 200) -> str:
    """Bereinigt Text fuer Prompt-Injection-Schutz."""
    if not text or not isinstance(text, str):
        return ""
    text = text.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
    text = re.sub(r'\s{2,}', ' ', text).strip()
    text = text[:max_len]
    if _INJECTION_PATTERN.search(text):
        logger.warning("Prompt-Injection in Korrektur blockiert: %.80s", text)
        return ""
    return text
