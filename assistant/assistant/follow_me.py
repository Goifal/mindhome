"""
Follow-Me Engine - JARVIS folgt dir von Raum zu Raum.

Erkennt Raumwechsel via Motion-Sensoren und zieht automatisch nach:
- Musik: Pause im alten Raum, Resume im neuen Raum
- Licht: Alten Raum aus, neuen Raum mit Profil einschalten
- Klima: Alten Raum Eco, neuen Raum Komfort-Temperatur

Pro-Person Profile aus settings.yaml konfigurierbar.
Cooldown verhindert Ping-Pong bei schnellen Raumwechseln.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from .config import yaml_config
from .ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)
from zoneinfo import ZoneInfo

_LOCAL_TZ = ZoneInfo(yaml_config.get("timezone", "Europe/Berlin"))


class FollowMeEngine:
    """Erkennt Raumwechsel und transferiert Musik/Licht/Klima."""

    def __init__(self, ha_client: HomeAssistantClient):
        self.ha = ha_client
        self._load_config()

        # Tracking: Person → letzter bekannter Raum + Zeitpunkt
        self._person_room: dict[str, str] = {}
        self._last_transfer: dict[str, datetime] = {}
        self._tracking_lock = asyncio.Lock()

    def _load_config(self):
        """Laedt Konfiguration aus settings.yaml."""
        cfg = yaml_config.get("follow_me", {})
        self.enabled = cfg.get("enabled", True)
        self.cooldown_seconds = cfg.get("cooldown_seconds", 60)
        self.transfer_music = cfg.get("transfer_music", True)
        self.transfer_lights = cfg.get("transfer_lights", True)
        self.transfer_climate = cfg.get("transfer_climate", False)
        self.profiles: dict = cfg.get("profiles", {})

    def get_profile(self, person: str) -> dict:
        """Holt das Follow-Me Profil einer Person."""
        return self.profiles.get(person, self.profiles.get(person.lower(), {}))

    async def handle_motion(
        self, motion_entity: str, person: str = ""
    ) -> Optional[dict]:
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
        motion_sensors = multi_room_cfg.get("room_motion_sensors") or {}
        if not motion_sensors:
            logger.debug("Follow-Me: room_motion_sensors nicht konfiguriert")
            return None
        new_room = None
        for room_name, sensor_id in motion_sensors.items():
            if sensor_id == motion_entity:
                new_room = room_name
                break

        if not new_room:
            return None

        # Person bestimmen (Fallback: "default")
        person_key = person or "default"

        async with self._tracking_lock:
            old_room = self._person_room.get(person_key)

            # Gleicher Raum → kein Transfer
            if old_room and old_room.lower() == new_room.lower():
                return None

            # Cooldown pruefen
            last = self._last_transfer.get(person_key)
            if last and datetime.now(timezone.utc) - last < timedelta(
                seconds=self.cooldown_seconds
            ):
                return None

            # Raumwechsel registrieren
            self._person_room[person_key] = new_room
            self._last_transfer[person_key] = datetime.now(timezone.utc)

            if not old_room:
                # Erster bekannter Aufenthaltsort → kein Transfer noetig
                return None

            # Pruefen ob Person allein im alten Raum war
            # (wenn andere noch da sind, nichts abschalten)
            others_in_old_room = [
                p
                for p, r in self._person_room.items()
                if r and r.lower() == old_room.lower() and p != person_key
            ]

        logger.info(
            "Follow-Me: %s wechselt von %s nach %s (andere in %s: %d)",
            person_key,
            old_room,
            new_room,
            old_room,
            len(others_in_old_room),
        )

        result = {
            "person": person_key,
            "from_room": old_room,
            "to_room": new_room,
            "actions": [],
        }

        room_speakers = multi_room_cfg.get("room_speakers", {})
        profile = self.get_profile(person_key)

        # 1-3: Musik, Licht, Klima parallel transferieren
        transfer_coros = []
        if self.transfer_music:
            transfer_coros.append(
                self._transfer_music(
                    old_room,
                    new_room,
                    room_speakers,
                    others_in_old_room,
                )
            )
        if self.transfer_lights:
            transfer_coros.append(
                self._transfer_lights(
                    old_room,
                    new_room,
                    profile,
                    others_in_old_room,
                )
            )
        if self.transfer_climate:
            transfer_coros.append(
                self._transfer_climate(
                    old_room,
                    new_room,
                    profile,
                    others_in_old_room,
                )
            )

        if transfer_coros:
            actions = await asyncio.gather(*transfer_coros, return_exceptions=True)
            for action in actions:
                if isinstance(action, dict):
                    result["actions"].append(action)

        if result["actions"]:
            return result
        return None

    async def _transfer_music(
        self,
        old_room: str,
        new_room: str,
        room_speakers: dict,
        others_in_old: list,
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
                    "media_player",
                    "media_pause",
                    {"entity_id": old_speaker},
                )

            # Play im neuen Raum
            await self.ha.call_service(
                "media_player",
                "media_play",
                {"entity_id": new_speaker},
            )

            logger.info("Follow-Me Musik: %s → %s", old_room, new_room)
            return {"type": "music", "from": old_room, "to": new_room}

        except Exception as e:
            logger.warning("Follow-Me Musik-Transfer fehlgeschlagen: %s", e)
            return None

    async def _transfer_lights(
        self,
        old_room: str,
        new_room: str,
        profile: dict,
        others_in_old: list,
    ) -> Optional[dict]:
        """Schaltet Licht im neuen Raum ein, im alten aus.

        Nutzt light_entities aus room_profiles.yaml wenn vorhanden,
        sonst Fallback auf generisches light.{room_name} Pattern.
        """
        try:
            from .config import get_room_profiles

            room_profiles = get_room_profiles().get("rooms", {})
            transition = int(
                yaml_config.get("lighting", {}).get("default_transition", 2)
            )

            # Neuen Raum einschalten mit Profil-Werten
            brightness = profile.get("light_brightness", 80)
            color_temp = profile.get("light_color_temp")

            # Echte light_entities aus room_profiles nutzen
            new_room_cfg = room_profiles.get(new_room, {})
            new_entities = new_room_cfg.get("light_entities", [])
            if not new_entities:
                new_entities = [f"light.{new_room.lower().replace(' ', '_')}"]

            for entity_id in new_entities:
                service_data = {
                    "entity_id": entity_id,
                    "brightness_pct": brightness,
                    "transition": transition,
                }
                # Per-Lampe Helligkeit aus room_profiles (Tag/Nacht)
                per_light = new_room_cfg.get("light_brightness", {}).get(entity_id)
                if per_light:
                    hour = datetime.now(_LOCAL_TZ).hour
                    if 7 <= hour < 21:
                        bri = per_light.get("day", brightness)
                    else:
                        bri = per_light.get("night", brightness)
                    service_data["brightness_pct"] = bri
                if color_temp:
                    service_data["color_temp_kelvin"] = color_temp
                await self.ha.call_service("light", "turn_on", service_data)

            # Alten Raum ausschalten (nur wenn allein)
            if not others_in_old:
                old_room_cfg = room_profiles.get(old_room, {})
                old_entities = old_room_cfg.get("light_entities", [])
                if not old_entities:
                    old_entities = [f"light.{old_room.lower().replace(' ', '_')}"]
                for entity_id in old_entities:
                    await self.ha.call_service(
                        "light",
                        "turn_off",
                        {"entity_id": entity_id, "transition": transition},
                    )

            logger.info(
                "Follow-Me Licht: %s aus → %s an (%d%%)", old_room, new_room, brightness
            )
            return {"type": "lights", "from": old_room, "to": new_room}

        except Exception as e:
            logger.warning("Follow-Me Licht-Transfer fehlgeschlagen: %s", e)
            return None

    async def _transfer_climate(
        self,
        old_room: str,
        new_room: str,
        profile: dict,
        others_in_old: list,
    ) -> Optional[dict]:
        """Setzt Klima im neuen Raum auf Komfort, im alten auf Eco."""
        try:
            comfort_temp = profile.get("comfort_temp", 22)

            # Neuen Raum auf Komfort
            await self.ha.call_service(
                "climate",
                "set_temperature",
                {
                    "entity_id": f"climate.{new_room.lower().replace(' ', '_')}",
                    "temperature": comfort_temp,
                },
            )

            # Alten Raum auf Eco (nur wenn allein)
            if not others_in_old:
                eco_temp = comfort_temp - profile.get("eco_temp_offset", 3)
                await self.ha.call_service(
                    "climate",
                    "set_temperature",
                    {
                        "entity_id": f"climate.{old_room.lower().replace(' ', '_')}",
                        "temperature": eco_temp,
                    },
                )

            logger.info(
                "Follow-Me Klima: %s→Eco, %s→%d°C", old_room, new_room, comfort_temp
            )
            return {"type": "climate", "from": old_room, "to": new_room}

        except Exception as e:
            logger.warning("Follow-Me Klima-Transfer fehlgeschlagen: %s", e)
            return None

    def _find_speaker(self, room: str, room_speakers: dict) -> Optional[str]:
        """Findet den Speaker fuer einen Raum."""
        room_lower = room.lower().replace(" ", "_")
        for cfg_room, entity_id in (room_speakers or {}).items():
            if cfg_room.lower() == room_lower:
                return entity_id
        return None

    def cleanup_stale_tracking(self, max_age_hours: int = 8):
        """Raeumt veraltete Person-Room-Eintraege auf."""
        now = datetime.now(timezone.utc)
        stale = [
            p
            for p, t in self._last_transfer.items()
            if now - t > timedelta(hours=max_age_hours)
        ]
        for p in stale:
            self._person_room.pop(p, None)
            self._last_transfer.pop(p, None)
        if stale:
            logger.debug(
                "Follow-Me: %d veraltete Tracking-Eintraege bereinigt", len(stale)
            )

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

    # ------------------------------------------------------------------
    # Phase 7: Praesenz-basierte Kontextanreicherung
    # ------------------------------------------------------------------

    def get_person_location(self, person: str) -> Optional[str]:
        """Gibt den letzten bekannten Raum einer Person zurueck."""
        return self._person_room.get(person)

    def get_all_person_locations(self) -> dict[str, str]:
        """Gibt alle bekannten Person-Raum-Zuordnungen zurueck."""
        return dict(self._person_room)

    def get_occupied_rooms(self) -> list[str]:
        """Gibt alle aktuell belegten Raeume zurueck."""
        return list(set(self._person_room.values()))

    def is_room_occupied(self, room: str) -> bool:
        """Prueft ob ein Raum belegt ist."""
        room_lower = room.lower().replace(" ", "_")
        return any(
            r.lower().replace(" ", "_") == room_lower
            for r in self._person_room.values()
        )

    def get_persons_in_room(self, room: str) -> list[str]:
        """Gibt alle Personen in einem bestimmten Raum zurueck."""
        room_lower = room.lower().replace(" ", "_")
        return [
            p
            for p, r in self._person_room.items()
            if r.lower().replace(" ", "_") == room_lower
        ]

    async def get_context_for_person(self, person: str) -> str:
        """Gibt Praesenz-Kontext fuer LLM-Prompt zurueck.

        Returns:
            Kontext-String z.B. "Person ist im Wohnzimmer. Auch anwesend: Partner."
        """
        location = self.get_person_location(person)
        if not location:
            return ""

        others = [p for p in self.get_persons_in_room(location) if p != person]
        context = f"Person ist im {location}."
        if others:
            context += f" Auch anwesend: {', '.join(others)}."
        return context

    # ------------------------------------------------------------------
    # Rueckkehr-Erkennung & Verweildauer
    # ------------------------------------------------------------------

    def detect_return_intent(self, person: str, room: str, seconds_away: float) -> bool:
        """Erkennt ob eine Person nur kurz weg war und zurueckkehrt.

        Wenn jemand innerhalb von 10 Sekunden zurueckkehrt, war es kein
        echter Raumwechsel — z.B. kurz zur Tuer gegangen und sofort zurueck.

        Args:
            person: Name der Person.
            room: Raum in den die Person zurueckkehrt.
            seconds_away: Wie lange die Person weg war (in Sekunden).

        Returns:
            True wenn es eine Rueckkehr ist (Transfer sollte NICHT stattfinden).
        """
        if seconds_away <= 10.0:
            logger.debug(
                "Rueckkehr erkannt: %s war nur %.1fs weg von %s — kein Transfer",
                person,
                seconds_away,
                room,
            )
            return True
        return False

    def detect_lingering(self, person: str, room: str, seconds_present: float) -> bool:
        """Erkennt ob eine Person sich in einem Raum niedergelassen hat.

        Erst nach 180 Sekunden gilt eine Person als wirklich angekommen,
        nicht nur durchlaufend (z.B. auf dem Weg zur Kueche durch den Flur).

        Args:
            person: Name der Person.
            room: Aktueller Raum.
            seconds_present: Wie lange die Person schon im Raum ist (in Sekunden).

        Returns:
            True wenn die Person sich niedergelassen hat (>= 180s).
        """
        if seconds_present >= 180.0:
            logger.debug(
                "Verweildauer erreicht: %s ist seit %.0fs in %s — angekommen",
                person,
                seconds_present,
                room,
            )
            return True
        return False
