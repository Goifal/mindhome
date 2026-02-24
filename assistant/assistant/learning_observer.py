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

    async def observe_state_change(self, entity_id: str, new_state: str, old_state: str):
        """Beobachtet State-Changes und erkennt manuelle Aktionen.

        Wird von proactive.py bei jedem state_changed aufgerufen.
        Ignoriert Jarvis-gesteuerte Aenderungen.
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

            # Aktion aufzeichnen
            action_key = f"{entity_id}:{new_state}"
            time_slot = f"{hour:02d}:{(minute // 15) * 15:02d}"  # 15-Min-Slots

            # F-053: Cycle detection — skip entities+timeslots that have already been
            # automated via a previous suggestion. Without this, the automation fires
            # a state change, which the observer counts again, leading to duplicate
            # suggestions or infinite observe->suggest->automate->observe loops.
            automated_key = f"{KEY_AUTOMATED}:{action_key}:{time_slot}"
            if await self.redis.get(automated_key):
                return

            action = {
                "entity_id": entity_id,
                "new_state": new_state,
                "time_slot": time_slot,
                "weekday": weekday,
                "timestamp": now.isoformat(),
            }

            # In Redis-Liste speichern (max 500 letzte Aktionen)
            await self.redis.lpush(KEY_MANUAL_ACTIONS, json.dumps(action))
            await self.redis.ltrim(KEY_MANUAL_ACTIONS, 0, 499)
            await self.redis.expire(KEY_MANUAL_ACTIONS, 30 * 86400)

            # Pattern-Check: Wurde diese Aktion schon oefter zur gleichen Zeit gemacht?
            await self._check_pattern(action_key, time_slot, entity_id, new_state)

            # Wochentag-spezifischer Pattern-Check
            await self._check_weekday_pattern(action_key, time_slot, weekday, entity_id, new_state)
        except Exception as e:
            logger.debug("Learning Observer state_change Fehler: %s", e)

    async def _check_pattern(self, action_key: str, time_slot: str,
                             entity_id: str, new_state: str):
        """Prueft ob ein Muster erkannt wurde."""
        pattern_key = f"{KEY_PATTERNS}:{action_key}:{time_slot}"

        # Zaehler erhoehen
        count = await self.redis.incr(pattern_key)
        # TTL auf 30 Tage setzen (nur beim ersten Mal)
        if count == 1:
            await self.redis.expire(pattern_key, 30 * 86400)

        # Genug Wiederholungen fuer einen Vorschlag?
        if count >= self.min_repetitions:
            # Schon vorgeschlagen?
            suggested_key = f"{KEY_SUGGESTED}:{action_key}:{time_slot}"
            already_suggested = await self.redis.get(suggested_key)
            if already_suggested:
                return

            # Als vorgeschlagen markieren (7 Tage Cooldown)
            await self.redis.setex(suggested_key, 7 * 86400, "1")

            # Vorschlag generieren
            friendly = entity_id.split(".", 1)[1].replace("_", " ").title()
            action_de = "eingeschaltet" if new_state == "on" else "ausgeschaltet" if new_state == "off" else new_state

            title = get_person_title()
            message = (
                f"{title}, mir ist aufgefallen, dass Sie {friendly} jeden Tag "
                f"um {time_slot} Uhr {action_de}. "
                f"Soll ich das automatisieren?"
            )

            logger.info("Learning: Muster erkannt - %s um %s (%dx)",
                        action_key, time_slot, count)

            if self._notify_callback:
                await self._notify_callback({
                    "message": message,
                    "type": "learning_suggestion",
                    "entity_id": entity_id,
                    "new_state": new_state,
                    "time_slot": time_slot,
                    "count": count,
                })

    async def _check_weekday_pattern(self, action_key: str, time_slot: str,
                                     weekday: int, entity_id: str, new_state: str):
        """Prueft Wochentag-spezifische Muster (z.B. nur Werktags)."""
        # F-053: Cycle detection for weekday-specific patterns
        automated_key = f"{KEY_AUTOMATED}:{action_key}:{time_slot}:{weekday}"
        if await self.redis.get(automated_key):
            return

        pattern_key = f"{KEY_WEEKDAY_PATTERNS}:{action_key}:{time_slot}:{weekday}"

        count = await self.redis.incr(pattern_key)
        if count == 1:
            await self.redis.expire(pattern_key, 60 * 86400)  # 60 Tage TTL

        # Erst ab 3 Wiederholungen am gleichen Wochentag
        if count < self.min_repetitions:
            return

        # Taeglich schon vorgeschlagen? Dann Wochentag-Vorschlag ueberspringen
        daily_suggested = await self.redis.get(f"{KEY_SUGGESTED}:{action_key}:{time_slot}")
        if daily_suggested:
            return

        suggested_key = f"{KEY_SUGGESTED}:weekday:{action_key}:{time_slot}:{weekday}"
        if await self.redis.get(suggested_key):
            return

        await self.redis.setex(suggested_key, 14 * 86400, "1")  # 14 Tage Cooldown

        friendly = entity_id.split(".", 1)[1].replace("_", " ").title()
        action_de = "eingeschaltet" if new_state == "on" else "ausgeschaltet" if new_state == "off" else new_state
        day_name = WEEKDAY_NAMES_DE[weekday]

        title = get_person_title()
        message = (
            f"{title}, Sie schalten {friendly} jeden {day_name} "
            f"um {time_slot} Uhr {action_de}. "
            f"Soll ich das fuer {day_name}s automatisieren?"
        )

        logger.info("Learning: Wochentag-Muster erkannt - %s am %s um %s (%dx)",
                     action_key, day_name, time_slot, count)

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
            })

    async def handle_response(self, entity_id: str, time_slot: str,
                              accepted: bool, weekday: int = -1) -> str:
        """Verarbeitet die Benutzer-Antwort auf einen Automatisierungs-Vorschlag.

        Args:
            entity_id: Die Entity die automatisiert werden soll
            time_slot: Der Zeitslot (z.B. "22:00")
            accepted: Ob der Vorschlag akzeptiert wurde
            weekday: Wochentag (-1 = taeglich)

        Returns:
            Antwort-Text fuer den Benutzer
        """
        if not self.redis:
            return "Fehler: Redis nicht verfuegbar."

        response = {
            "entity_id": entity_id,
            "time_slot": time_slot,
            "weekday": weekday,
            "accepted": accepted,
            "timestamp": datetime.now().isoformat(),
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
        states_to_mark = ["on", "off"]  # Mark both directions to avoid partial loops
        for state in states_to_mark:
            automated_key = f"{KEY_AUTOMATED}:{entity_id}:{state}:{time_slot}"
            await self.redis.setex(automated_key, 90 * 86400, "1")
        if weekday >= 0:
            for state in states_to_mark:
                automated_key = f"{KEY_AUTOMATED}:{entity_id}:{state}:{time_slot}:{weekday}"
                await self.redis.setex(automated_key, 90 * 86400, "1")

        return (
            f"Sehr gut, {get_person_title()}. Ich habe die Automatisierung vorgemerkt. "
            f"Die Self-Automation wird {entity_id.split('.', 1)[1].replace('_', ' ').title()} "
            f"ab jetzt automatisch um {time_slot} Uhr schalten."
        )

    async def get_learned_patterns(self) -> list[dict]:
        """Gibt alle erkannten Muster zurueck (fuer Status/Debug).

        Returns:
            Liste von Muster-Dicts mit entity, time_slot, count, weekday
        """
        if not self.redis:
            return []

        patterns = []

        # Tages-Muster lesen
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
                        # Parse: mha:learning:patterns:entity:state:timeslot
                        parts = key_str.replace(f"{KEY_PATTERNS}:", "").rsplit(":", 1)
                        if len(parts) == 2:
                            action, time_slot = parts
                            entity_state = action.rsplit(":", 1)
                            patterns.append({
                                "action": action,
                                "entity": entity_state[0] if len(entity_state) > 1 else action,
                                "time_slot": time_slot,
                                "count": count_val,
                                "weekday": -1,
                            })
            if cursor == 0:
                break

        # Nach Count sortieren (haeufigste zuerst)
        patterns.sort(key=lambda p: p["count"], reverse=True)
        return patterns[:20]  # Max 20
