"""
Follow-Me Engine - JARVIS folgt dir von Raum zu Raum.

Erkennt Raumwechsel via Motion-Sensoren und zieht automatisch nach:
- Musik: Pause im alten Raum, Resume im neuen Raum
- Licht: Alten Raum aus, neuen Raum mit Profil einschalten
- Klima: Alten Raum Eco, neuen Raum Komfort-Temperatur

Pro-Person Profile aus settings.yaml konfigurierbar.
Cooldown verhindert Ping-Pong bei schnellen Raumwechseln.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from .config import yaml_config
from .ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)


class FollowMeEngine:
    """Erkennt Raumwechsel und transferiert Musik/Licht/Klima."""

    def __init__(self, ha_client: HomeAssistantClient):
        self.ha = ha_client
        self._load_config()

        # Tracking: Person → letzter bekannter Raum + Zeitpunkt
        self._person_room: dict[str, str] = {}
        self._last_transfer: dict[str, datetime] = {}

    def _load_config(self):
        """Laedt Konfiguration aus settings.yaml."""
        cfg = yaml_config.get("follow_me", {})
        self.enabled = cfg.get("enabled", False)
        self.cooldown_seconds = cfg.get("cooldown_seconds", 60)
        self.transfer_music = cfg.get("transfer_music", True)
        self.transfer_lights = cfg.get("transfer_lights", True)
        self.transfer_climate = cfg.get("transfer_climate", False)
        self.profiles: dict = cfg.get("profiles", {})

    def get_profile(self, person: str) -> dict:
        """Holt das Follow-Me Profil einer Person."""
        return self.profiles.get(person, self.profiles.get(person.lower(), {}))

    async def handle_motion(self, motion_entity: str, person: str = "") -> Optional[dict]:
        """Verarbeitet ein Motion-Event und fuehrt ggf. Transfer durch.

        Args:
            motion_entity: Entity-ID des Bewegungsmelders
            person: Name der Person (wenn bekannt)

        Returns:
            Transfer-Info dict oder None wenn kein Transfer noetig.
        """
        if not self.enabled:
            return None

        # Reload config for hot-changes
        self._load_config()
        if not self.enabled:
            return None

        # Raum des Bewegungsmelders ermitteln
        multi_room_cfg = yaml_config.get("multi_room", {})
        motion_sensors = multi_room_cfg.get("room_motion_sensors", {})
        new_room = None
        for room_name, sensor_id in (motion_sensors or {}).items():
            if sensor_id == motion_entity:
                new_room = room_name
                break

        if not new_room:
            return None

        # Person bestimmen (Fallback: "default")
        person_key = person or "default"
        old_room = self._person_room.get(person_key)

        # Gleicher Raum → kein Transfer
        if old_room and old_room.lower() == new_room.lower():
            return None

        # Cooldown pruefen
        last = self._last_transfer.get(person_key)
        if last and datetime.now() - last < timedelta(seconds=self.cooldown_seconds):
            return None

        # Raumwechsel registrieren
        self._person_room[person_key] = new_room
        self._last_transfer[person_key] = datetime.now()

        if not old_room:
            # Erster bekannter Aufenthaltsort → kein Transfer noetig
            return None

        # Pruefen ob Person allein im alten Raum war
        # (wenn andere noch da sind, nichts abschalten)
        others_in_old_room = [
            p for p, r in self._person_room.items()
            if r and r.lower() == old_room.lower() and p != person_key
        ]

        logger.info(
            "Follow-Me: %s wechselt von %s nach %s (andere in %s: %d)",
            person_key, old_room, new_room, old_room, len(others_in_old_room),
        )

        result = {
            "person": person_key,
            "from_room": old_room,
            "to_room": new_room,
            "actions": [],
        }

        room_speakers = multi_room_cfg.get("room_speakers", {})
        profile = self.get_profile(person_key)

        # 1. Musik transferieren
        if self.transfer_music:
            action = await self._transfer_music(
                old_room, new_room, room_speakers, others_in_old_room,
            )
            if action:
                result["actions"].append(action)

        # 2. Licht transferieren
        if self.transfer_lights:
            action = await self._transfer_lights(
                old_room, new_room, profile, others_in_old_room,
            )
            if action:
                result["actions"].append(action)

        # 3. Klima anpassen
        if self.transfer_climate:
            action = await self._transfer_climate(
                old_room, new_room, profile, others_in_old_room,
            )
            if action:
                result["actions"].append(action)

        if result["actions"]:
            return result
        return None

    async def _transfer_music(
        self, old_room: str, new_room: str,
        room_speakers: dict, others_in_old: list,
    ) -> Optional[dict]:
        """Transferiert Musik vom alten in den neuen Raum."""
        old_speaker = self._find_speaker(old_room, room_speakers)
        new_speaker = self._find_speaker(new_room, room_speakers)

        if not old_speaker or not new_speaker:
            return None

        # Pruefen ob im alten Raum Musik laeuft
        state = await self.ha.get_state(old_speaker)
        if not state or state.get("state") != "playing":
            return None

        try:
            # Pause im alten Raum (nur wenn allein)
            if not others_in_old:
                await self.ha.call_service(
                    "media_player", "media_pause",
                    {"entity_id": old_speaker},
                )

            # Play im neuen Raum
            await self.ha.call_service(
                "media_player", "media_play",
                {"entity_id": new_speaker},
            )

            logger.info("Follow-Me Musik: %s → %s", old_room, new_room)
            return {"type": "music", "from": old_room, "to": new_room}

        except Exception as e:
            logger.debug("Follow-Me Musik-Transfer fehlgeschlagen: %s", e)
            return None

    async def _transfer_lights(
        self, old_room: str, new_room: str,
        profile: dict, others_in_old: list,
    ) -> Optional[dict]:
        """Schaltet Licht im neuen Raum ein, im alten aus."""
        try:
            # Neuen Raum einschalten mit Profil-Werten
            brightness = profile.get("light_brightness", 80)
            color_temp = profile.get("light_color_temp")

            service_data = {
                "entity_id": f"light.{new_room.lower().replace(' ', '_')}",
                "brightness_pct": brightness,
            }
            if color_temp:
                # Kelvin → Mireds umrechnen
                service_data["color_temp_kelvin"] = color_temp

            await self.ha.call_service("light", "turn_on", service_data)

            # Alten Raum ausschalten (nur wenn allein)
            if not others_in_old:
                await self.ha.call_service(
                    "light", "turn_off",
                    {"entity_id": f"light.{old_room.lower().replace(' ', '_')}"},
                )

            logger.info("Follow-Me Licht: %s aus → %s an (%d%%)", old_room, new_room, brightness)
            return {"type": "lights", "from": old_room, "to": new_room}

        except Exception as e:
            logger.debug("Follow-Me Licht-Transfer fehlgeschlagen: %s", e)
            return None

    async def _transfer_climate(
        self, old_room: str, new_room: str,
        profile: dict, others_in_old: list,
    ) -> Optional[dict]:
        """Setzt Klima im neuen Raum auf Komfort, im alten auf Eco."""
        try:
            comfort_temp = profile.get("comfort_temp", 22)

            # Neuen Raum auf Komfort
            await self.ha.call_service("climate", "set_temperature", {
                "entity_id": f"climate.{new_room.lower().replace(' ', '_')}",
                "temperature": comfort_temp,
            })

            # Alten Raum auf Eco (nur wenn allein)
            if not others_in_old:
                eco_temp = comfort_temp - 3
                await self.ha.call_service("climate", "set_temperature", {
                    "entity_id": f"climate.{old_room.lower().replace(' ', '_')}",
                    "temperature": eco_temp,
                })

            logger.info("Follow-Me Klima: %s→Eco, %s→%d°C", old_room, new_room, comfort_temp)
            return {"type": "climate", "from": old_room, "to": new_room}

        except Exception as e:
            logger.debug("Follow-Me Klima-Transfer fehlgeschlagen: %s", e)
            return None

    def _find_speaker(self, room: str, room_speakers: dict) -> Optional[str]:
        """Findet den Speaker fuer einen Raum."""
        room_lower = room.lower().replace(" ", "_")
        for cfg_room, entity_id in (room_speakers or {}).items():
            if cfg_room.lower() == room_lower:
                return entity_id
        return None

    def health_status(self) -> dict:
        """Status fuer Diagnostik."""
        return {
            "enabled": self.enabled,
            "cooldown_seconds": self.cooldown_seconds,
            "transfer_music": self.transfer_music,
            "transfer_lights": self.transfer_lights,
            "transfer_climate": self.transfer_climate,
            "tracked_persons": len(self._person_room),
            "profiles": list(self.profiles.keys()),
        }
