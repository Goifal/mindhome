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

from .config import yaml_config

logger = logging.getLogger(__name__)

KEY_MANUAL_ACTIONS = "mha:learning:manual_actions"
KEY_PATTERNS = "mha:learning:patterns"
KEY_SUGGESTED = "mha:learning:suggested"
JARVIS_ACTION_KEY = "mha:learning:jarvis_action"  # Marker fuer Jarvis-Aktionen


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

            action = {
                "entity_id": entity_id,
                "new_state": new_state,
                "time_slot": time_slot,
                "weekday": weekday,
                "timestamp": now.isoformat(),
            }

            # In Redis-Liste speichern (max 100 letzte Aktionen)
            await self.redis.lpush(KEY_MANUAL_ACTIONS, json.dumps(action))
            await self.redis.ltrim(KEY_MANUAL_ACTIONS, 0, 99)

            # Pattern-Check: Wurde diese Aktion schon oefter zur gleichen Zeit gemacht?
            await self._check_pattern(action_key, time_slot, entity_id, new_state)
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

            message = (
                f"Sir, mir ist aufgefallen, dass Sie {friendly} jeden Tag "
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
