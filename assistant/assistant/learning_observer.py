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
            time_slot = f"{hour:02d}:{(minute // 15) * 15:02d}"  # 15-Min-Slots

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

            # In Redis-Liste speichern (max 500 letzte Aktionen)
            await self.redis.lpush(KEY_MANUAL_ACTIONS, json.dumps(action))
            await self.redis.ltrim(KEY_MANUAL_ACTIONS, 0, 499)
            await self.redis.expire(KEY_MANUAL_ACTIONS, 30 * 86400)

            # Pattern-Check: Wurde diese Aktion schon oefter zur gleichen Zeit gemacht?
            await self._check_pattern(action_key, time_slot, entity_id, new_state, person=person)

            # Wochentag-spezifischer Pattern-Check
            await self._check_weekday_pattern(action_key, time_slot, weekday, entity_id, new_state, person=person)
        except Exception as e:
            logger.debug("Learning Observer state_change Fehler: %s", e)

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
        # TTL auf 30 Tage setzen (nur wenn noch keine TTL gesetzt)
        if current_ttl is None or current_ttl < 0:
            await self.redis.expire(pattern_key, 30 * 86400)

        # Genug Wiederholungen fuer einen Vorschlag?
        if count >= self.min_repetitions:
            # Schon vorgeschlagen?
            suggested_key = f"{KEY_SUGGESTED}:{person_prefix}{action_key}:{time_slot}"
            already_suggested = await self.redis.get(suggested_key)
            if already_suggested:
                return

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
        await self.redis.expire(KEY_RESPONSES, 30 * 86400)

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
        cursor = 0
        while True:
            cursor, keys = await self.redis.scan(
                cursor, match=f"{KEY_PATTERNS}:*", count=50
            )
            for key in keys:
                key_str = key.decode() if isinstance(key, bytes) else key
                count = await self.redis.get(key)
                if count:
                    count_val = int(count)
                    if count_val >= 2:  # Ab 2 Wiederholungen anzeigen
                        suffix = key_str.replace(f"{KEY_PATTERNS}:", "")
                        # rsplit 2 → ["[person:]entity:state", "HH", "MM"]
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
            if cursor == 0:
                break

        # Wochentag-Muster lesen
        # Key: mha:learning:weekday_patterns:[person:]entity:state:HH:MM:weekday
        cursor = 0
        while True:
            cursor, keys = await self.redis.scan(
                cursor, match=f"{KEY_WEEKDAY_PATTERNS}:*", count=50
            )
            for key in keys:
                key_str = key.decode() if isinstance(key, bytes) else key
                count = await self.redis.get(key)
                if count:
                    count_val = int(count)
                    if count_val >= 2:
                        suffix = key_str.replace(f"{KEY_WEEKDAY_PATTERNS}:", "")
                        # rsplit 3 → ["[person:]entity:state", "HH", "MM", "weekday"]
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
            if cursor == 0:
                break

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
            logger.debug("Lern-Report Antworten lesen fehlgeschlagen: %s", e)

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
            lines.append(f"\n{suggestions} Vorschlaege gemacht: {accepted} akzeptiert, {declined} abgelehnt.")

        return "\n".join(lines)
