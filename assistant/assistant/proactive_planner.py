"""
ProactiveSequencePlanner — Multi-Step-Planung bei Kontext-Aenderungen.

Phase 18: MCU-Upgrade — Jarvis plant voraus bei:
- Person-Ankunft: Unlock → Licht → Klima → Willkommen
- Wetter-Aenderung: Fenster → Rollladen → Heizung anpassen
- Gaeste-Event: Vorbereitung → Licht → Musik → Tuer

Safety: Security-Aktionen (unlock, alarm) IMMER mit Bestaetigung,
egal welches Autonomie-Level.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config, get_person_title

logger = logging.getLogger(__name__)

# Redis-Key-Prefix
_PREFIX = "mha:proactive_planner"


class ProactiveSequencePlanner:
    """Plant Multi-Step-Aktionen bei grossen Kontext-Aenderungen."""

    def __init__(self, ha, anticipation=None):
        """
        Args:
            ha: HomeAssistantClient-Instanz
            anticipation: AnticipationEngine fuer gelernte Ketten (optional)
        """
        self.ha = ha
        self.anticipation = anticipation
        self.redis: Optional[aioredis.Redis] = None

        cfg = yaml_config.get("proactive_planner", {})
        self.enabled = cfg.get("enabled", True)
        self.min_autonomy_for_auto = cfg.get("min_autonomy_for_auto", 4)

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert den Planner mit Redis-Verbindung."""
        self.redis = redis_client
        if self.enabled:
            logger.info("ProactiveSequencePlanner initialisiert")

    async def plan_from_context_change(
        self, trigger: str, context: dict, autonomy_level: int = 2,
    ) -> Optional[dict]:
        """Erstellt einen Aktionsplan bei Kontext-Aenderung.

        Args:
            trigger: Art der Aenderung (person_arrived, weather_changed, calendar_event_soon)
            context: Aktueller Kontext-Dict
            autonomy_level: Aktuelles Autonomie-Level (1-5)

        Returns:
            Plan-Dict mit 'actions', 'message', 'needs_confirmation' oder None
        """
        if not self.enabled:
            return None

        # Cooldown pruefen (max 1 Plan pro 30 Min pro Trigger-Typ)
        if self.redis:
            cooldown_key = f"{_PREFIX}:cooldown:{trigger}"
            try:
                if await self.redis.exists(cooldown_key):
                    return None
            except Exception as e:
                logger.debug("Cooldown check failed: %s", e)

        plan = None

        if trigger == "person_arrived":
            person = context.get("person", {}).get("name", "")
            plan = await self._plan_arrival_sequence(person, context)
        elif trigger == "weather_changed":
            plan = await self._plan_weather_sequence(context)
        elif trigger == "calendar_event_soon":
            plan = await self._plan_guest_sequence(context)

        if not plan:
            return None

        # Cooldown setzen
        if self.redis:
            try:
                await self.redis.setex(cooldown_key, 1800, "1")  # 30 Min
            except Exception as e:
                logger.debug("Cooldown set failed: %s", e)

        # Autonomie-Level bestimmt ob Auto-Ausfuehrung oder Frage
        auto_execute = autonomy_level >= self.min_autonomy_for_auto
        # Safety: Security-Aktionen NIE automatisch
        has_security_action = any(
            a.get("type") in ("unlock_door", "arm_security", "lock_door")
            for a in plan.get("actions", [])
        )
        if has_security_action:
            auto_execute = False

        plan["needs_confirmation"] = not auto_execute
        return plan

    async def _plan_arrival_sequence(self, person: str, context: dict) -> Optional[dict]:
        """Person kommt nach Hause: Licht → Klima → Willkommen."""
        title = get_person_title(person)
        hour = datetime.now().hour

        actions = []

        # Licht einschalten (wenn dunkel)
        if hour >= 17 or hour < 7:
            actions.append({
                "type": "set_light",
                "args": {"state": "on", "brightness": 70},
                "description": "Willkommens-Beleuchtung",
            })

        # Klima anpassen (wenn Eco-Modus aktiv)
        house = context.get("house", {})
        climate = house.get("climate", [])
        eco_active = any(
            c.get("preset_mode") == "eco" or c.get("hvac_mode") == "off"
            for c in climate if isinstance(c, dict)
        )
        if eco_active:
            actions.append({
                "type": "set_climate",
                "args": {"preset_mode": "home"},
                "description": "Heizung auf Home-Modus",
            })

        if not actions:
            return None

        actions_desc = ", ".join(a["description"] for a in actions)
        return {
            "trigger": "person_arrived",
            "person": person,
            "actions": actions,
            "message": f"{title} kommt nach Hause. Soll ich {actions_desc}?",
            "auto_message": f"Willkommen, {title}. {actions_desc} — erledigt.",
        }

    async def _plan_weather_sequence(self, context: dict) -> Optional[dict]:
        """Wetter aendert sich signifikant: Fenster/Rollladen/Heizung anpassen."""
        weather = context.get("weather", {})
        house = context.get("house", {})
        condition = str(weather.get("condition", "")).lower()
        open_windows = house.get("open_windows", [])

        actions = []
        title = get_person_title()

        # Regen/Sturm + Fenster offen
        rain_conditions = {"rainy", "pouring", "lightning-rainy", "lightning", "hail"}
        if condition in rain_conditions and open_windows:
            actions.append({
                "type": "notify",
                "args": {"message": f"Fenster {', '.join(open_windows[:3])} bei {condition} offen"},
                "description": f"Fenster-Warnung ({condition})",
            })

        # Starker Regen → Rollladen-Schutz vorschlagen
        if condition in ("pouring", "hail", "lightning-rainy"):
            actions.append({
                "type": "set_cover",
                "args": {"position": 0},
                "description": "Rollladen als Schutz runterfahren",
            })

        if not actions:
            return None

        actions_desc = ", ".join(a["description"] for a in actions)
        return {
            "trigger": "weather_changed",
            "actions": actions,
            "message": f"{title}, Wetter aendert sich ({condition}). Soll ich {actions_desc}?",
            "auto_message": f"Wetter-Anpassung: {actions_desc}.",
        }

    async def _plan_guest_sequence(self, context: dict) -> Optional[dict]:
        """Gaeste erwartet: Licht → Musik → Check."""
        title = get_person_title()

        actions = []
        hour = datetime.now().hour

        # Angenehme Beleuchtung
        if hour >= 16 or hour < 8:
            actions.append({
                "type": "set_light",
                "args": {"brightness": 80, "color_temp": "warm"},
                "description": "Angenehme Beleuchtung",
            })

        # Hintergrundmusik (immer bei Gaeste-Event)
        actions.append({
            "type": "play_media",
            "args": {"content_type": "ambient"},
            "description": "Hintergrundmusik",
        })

        if not actions:
            return None

        actions_desc = ", ".join(a["description"] for a in actions)
        return {
            "trigger": "calendar_event_soon",
            "actions": actions,
            "message": f"{title}, Gaeste kommen bald. Soll ich {actions_desc} vorbereiten?",
            "auto_message": f"Gaeste-Vorbereitung: {actions_desc}.",
        }

    async def get_status(self) -> dict:
        """Gibt den Status des Planners zurueck."""
        status = {
            "enabled": self.enabled,
            "min_autonomy_for_auto": self.min_autonomy_for_auto,
        }

        if self.redis:
            try:
                cursor = 0
                active_cooldowns = 0
                while True:
                    cursor, keys = await self.redis.scan(
                        cursor, match=f"{_PREFIX}:cooldown:*", count=50,
                    )
                    active_cooldowns += len(keys)
                    if cursor == 0:
                        break
                status["active_cooldowns"] = active_cooldowns
            except Exception as e:
                logger.warning("Cooldown scan failed: %s", e)
                status["active_cooldowns"] = -1

        return status
