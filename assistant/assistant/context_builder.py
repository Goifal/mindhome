"""
Context Builder - Sammelt alle relevanten Daten fuer den LLM-Prompt.
Holt Daten von Home Assistant, MindHome und Semantic Memory via REST API.

Phase 7: Raum-Profile und saisonale Anpassungen.
Phase 10: Multi-Room Presence Tracking.
"""

import logging
import math
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from .config import yaml_config
from .ha_client import HomeAssistantClient
from .semantic_memory import SemanticMemory

logger = logging.getLogger(__name__)

# Raum-Profile laden
_ROOM_PROFILES = {}
_SEASONAL_CONFIG = {}
_config_dir = Path(__file__).parent.parent / "config"
try:
    _room_file = _config_dir / "room_profiles.yaml"
    if _room_file.exists():
        with open(_room_file) as f:
            _rp = yaml.safe_load(f)
            _ROOM_PROFILES = _rp.get("rooms", {})
            _SEASONAL_CONFIG = _rp.get("seasonal", {})
        logger.info("Raum-Profile geladen: %d Raeume", len(_ROOM_PROFILES))
except Exception as e:
    logger.warning("room_profiles.yaml nicht geladen: %s", e)

# Relevante Entity-Typen fuer den Kontext
RELEVANT_DOMAINS = [
    "light", "climate", "cover", "scene", "person",
    "weather", "sensor", "binary_sensor", "media_player",
    "lock", "alarm_control_panel",
]


class ContextBuilder:
    """Baut den vollstaendigen Kontext fuer das LLM zusammen."""

    def __init__(self, ha_client: HomeAssistantClient):
        self.ha = ha_client
        self.semantic: Optional[SemanticMemory] = None
        self._activity_engine = None

    def set_semantic_memory(self, semantic: SemanticMemory):
        """Setzt die Referenz zum Semantic Memory."""
        self.semantic = semantic

    def set_activity_engine(self, activity_engine):
        """Setzt die Referenz zur Activity Engine (Phase 6)."""
        self._activity_engine = activity_engine

    async def build(
        self, trigger: str = "voice", user_text: str = "", person: str = ""
    ) -> dict:
        """
        Sammelt den kompletten Kontext.

        Args:
            trigger: Was den Kontext ausloest ("voice", "proactive", "api")
            user_text: User-Eingabe fuer semantische Suche
            person: Name der Person

        Returns:
            Strukturierter Kontext als Dict
        """
        context = {}

        # Zeitkontext
        now = datetime.now()
        context["time"] = {
            "datetime": now.strftime("%Y-%m-%d %H:%M"),
            "weekday": self._weekday_german(now.weekday()),
            "time_of_day": self._get_time_of_day(now.hour),
        }

        # Haus-Status von HA
        states = await self.ha.get_states()
        if states:
            context["house"] = self._extract_house_status(states)
            context["person"] = self._extract_person(states)
            context["room"] = self._guess_current_room(states)

        # MindHome-Daten (optional, falls MindHome installiert)
        mindhome_data = await self._get_mindhome_data()
        if mindhome_data:
            context["mindhome"] = mindhome_data

        # Aktivitaets-Erkennung (Phase 6)
        if self._activity_engine:
            try:
                detection = await self._activity_engine.detect_activity()
                context["activity"] = {
                    "current": detection["activity"],
                    "confidence": detection["confidence"],
                }
            except Exception as e:
                logger.debug("Activity Engine Fehler: %s", e)

        # Phase 7: Raum-Profil zum Kontext hinzufuegen
        current_room = context.get("room", "")
        room_profile = self._get_room_profile(current_room)
        if room_profile:
            context["room_profile"] = room_profile

        # Phase 7: Saisonale Daten
        context["seasonal"] = self._get_seasonal_context(states)

        # Phase 10: Multi-Room Presence
        if states:
            context["room_presence"] = self._build_room_presence(states)

        # Warnungen
        context["alerts"] = self._extract_alerts(states or [])

        # Semantisches Gedaechtnis - relevante Fakten zur Anfrage
        if self.semantic and user_text:
            context["memories"] = await self._get_relevant_memories(
                user_text, person
            )

        return context

    async def _get_relevant_memories(
        self, user_text: str, person: str = ""
    ) -> dict:
        """Holt relevante Fakten aus dem semantischen Gedaechtnis."""
        memories = {"relevant_facts": [], "person_facts": []}

        if not self.semantic:
            return memories

        try:
            # Fakten die zur aktuellen Anfrage passen
            relevant = await self.semantic.search_facts(
                query=user_text, limit=3, person=person or None
            )
            memories["relevant_facts"] = [
                f["content"] for f in relevant if f.get("relevance", 0) > 0.3
            ]

            # Allgemeine Fakten ueber die Person (Praeferenzen)
            if person:
                person_facts = await self.semantic.get_facts_by_person(person)
                # Top-5 mit hoechster Confidence
                memories["person_facts"] = [
                    f["content"] for f in person_facts[:5]
                    if f.get("confidence", 0) >= 0.6
                ]
        except Exception as e:
            logger.error("Fehler beim Laden semantischer Erinnerungen: %s", e)

        return memories

    def _extract_house_status(self, states: list[dict]) -> dict:
        """Extrahiert den Haus-Status aus HA States."""
        house = {
            "temperatures": {},
            "lights": [],
            "presence": {"home": [], "away": []},
            "weather": {},
            "active_scenes": [],
            "security": "unknown",
            "media": [],
        }

        for state in states:
            entity_id = state.get("entity_id", "")
            s = state.get("state", "")
            attrs = state.get("attributes", {})
            domain = entity_id.split(".")[0] if "." in entity_id else ""

            # Temperaturen
            if domain == "climate":
                room = attrs.get("friendly_name", entity_id)
                house["temperatures"][room] = {
                    "current": attrs.get("current_temperature"),
                    "target": attrs.get("temperature"),
                    "mode": s,
                }

            # Lichter (nur die an sind)
            elif domain == "light" and s == "on":
                name = attrs.get("friendly_name", entity_id)
                brightness = attrs.get("brightness")
                if brightness:
                    pct = round(brightness / 255 * 100)
                    house["lights"].append(f"{name}: {pct}%")
                else:
                    house["lights"].append(f"{name}: an")

            # Personen
            elif domain == "person":
                name = attrs.get("friendly_name", entity_id)
                if s == "home":
                    house["presence"]["home"].append(name)
                else:
                    house["presence"]["away"].append(name)

            # Wetter (Met.no via HA Integration)
            elif domain == "weather" and not house["weather"]:
                house["weather"] = {
                    "temp": attrs.get("temperature"),
                    "condition": s,
                    "humidity": attrs.get("humidity"),
                    "wind_speed": attrs.get("wind_speed"),
                    "wind_bearing": attrs.get("wind_bearing"),
                    "pressure": attrs.get("pressure"),
                }
                # Forecast (naechste Stunden falls vorhanden)
                forecast = attrs.get("forecast", [])
                if forecast:
                    upcoming = []
                    for entry in forecast[:4]:
                        upcoming.append({
                            "time": entry.get("datetime", ""),
                            "temp": entry.get("temperature"),
                            "condition": entry.get("condition", ""),
                            "precipitation": entry.get("precipitation"),
                        })
                    house["weather"]["forecast"] = upcoming

            # Sun Entity (sun.sun — exakte Sonnenauf-/-untergangszeiten)
            elif entity_id == "sun.sun":
                house["sun"] = {
                    "state": s,  # "above_horizon" / "below_horizon"
                    "sunrise": attrs.get("next_rising", ""),
                    "sunset": attrs.get("next_setting", ""),
                    "elevation": attrs.get("elevation"),
                }

            # Alarm
            elif domain == "alarm_control_panel":
                house["security"] = s

            # Medien
            elif domain == "media_player" and s == "playing":
                name = attrs.get("friendly_name", entity_id)
                title = attrs.get("media_title", "")
                house["media"].append(f"{name}: {title}" if title else name)

        return house

    def _extract_person(self, states: list[dict]) -> dict:
        """Findet die aktive Person."""
        for state in states:
            if state.get("entity_id", "").startswith("person."):
                if state.get("state") == "home":
                    return {
                        "name": state.get("attributes", {}).get(
                            "friendly_name", "User"
                        ),
                        "last_room": "unbekannt",
                    }
        return {"name": "User", "last_room": "unbekannt"}

    def _guess_current_room(self, states: list[dict]) -> str:
        """Versucht den aktuellen Raum zu erraten (letzte Bewegung)."""
        latest_motion = None
        latest_room = "unbekannt"

        for state in states:
            entity_id = state.get("entity_id", "")
            if (
                "motion" in entity_id
                and state.get("state") == "on"
            ):
                last_changed = state.get("last_changed", "")
                if not latest_motion or last_changed > latest_motion:
                    latest_motion = last_changed
                    name = state.get("attributes", {}).get(
                        "friendly_name", entity_id
                    )
                    latest_room = name.replace("Bewegung ", "").replace(" Motion", "")

        return latest_room

    def _extract_alerts(self, states: list[dict]) -> list[str]:
        """Extrahiert aktive Warnungen."""
        alerts = []
        for state in states:
            entity_id = state.get("entity_id", "")
            s = state.get("state", "")

            # Rauchmelder, Wassermelder, etc.
            if any(x in entity_id for x in ["smoke", "water_leak", "gas"]):
                if s == "on":
                    name = state.get("attributes", {}).get(
                        "friendly_name", entity_id
                    )
                    alerts.append(f"ALARM: {name}")

            # Fenster/Tueren offen bei Alarm
            if "door" in entity_id or "window" in entity_id:
                if s == "on":
                    name = state.get("attributes", {}).get(
                        "friendly_name", entity_id
                    )
                    alerts.append(f"Offen: {name}")

        return alerts

    async def _get_mindhome_data(self) -> Optional[dict]:
        """Holt optionale MindHome-Daten."""
        try:
            data = {}
            presence = await self.ha.get_presence()
            if presence:
                data["presence"] = presence
            energy = await self.ha.get_energy()
            if energy:
                data["energy"] = energy
            return data if data else None
        except Exception as e:
            logger.debug("MindHome nicht verfuegbar: %s", e)
            return None

    @staticmethod
    def _get_time_of_day(hour: int) -> str:
        if 5 <= hour < 8:
            return "early_morning"
        elif 8 <= hour < 12:
            return "morning"
        elif 12 <= hour < 18:
            return "afternoon"
        elif 18 <= hour < 22:
            return "evening"
        return "night"

    @staticmethod
    def _weekday_german(weekday: int) -> str:
        days = [
            "Montag", "Dienstag", "Mittwoch", "Donnerstag",
            "Freitag", "Samstag", "Sonntag",
        ]
        return days[weekday]

    # ------------------------------------------------------------------
    # Phase 7: Raum-Profile
    # ------------------------------------------------------------------

    @staticmethod
    def _get_room_profile(room_name: str) -> Optional[dict]:
        """Holt das Raum-Profil fuer den aktuellen Raum."""
        if not room_name or not _ROOM_PROFILES:
            return None

        room_lower = room_name.lower().replace(" ", "_")
        # Direkte Suche
        if room_lower in _ROOM_PROFILES:
            return _ROOM_PROFILES[room_lower]
        # Fuzzy: Teilwort-Match
        for key, profile in _ROOM_PROFILES.items():
            if key in room_lower or room_lower in key:
                return profile
        return None

    # ------------------------------------------------------------------
    # Phase 7: Saisonale Anpassungen
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Phase 10: Multi-Room Presence
    # ------------------------------------------------------------------

    def _build_room_presence(self, states: list[dict]) -> dict:
        """Baut ein Bild welche Personen in welchen Raeumen sind.

        Nutzt Bewegungsmelder + Person-Entities + konfigurierte Mappings.

        Returns:
            Dict mit:
                persons_by_room: {room: [person_names]}
                active_rooms: [rooms_with_recent_motion]
                speakers_by_room: {room: entity_id}
        """
        multi_room_cfg = yaml_config.get("multi_room", {})
        if not multi_room_cfg.get("enabled", True):
            return {}

        timeout_minutes = multi_room_cfg.get("presence_timeout_minutes", 15)
        room_sensors = multi_room_cfg.get("room_motion_sensors", {})
        room_speakers = multi_room_cfg.get("room_speakers", {})
        now = datetime.now()

        # Aktive Raeume basierend auf Motion-Sensoren
        active_rooms = []
        for room_name, sensor_id in (room_sensors or {}).items():
            for state in states:
                if state.get("entity_id") == sensor_id:
                    if state.get("state") == "on":
                        active_rooms.append(room_name)
                    elif state.get("last_changed"):
                        try:
                            changed = datetime.fromisoformat(
                                state["last_changed"].replace("Z", "+00:00")
                            ).replace(tzinfo=None)
                            if (now - changed).total_seconds() / 60 < timeout_minutes:
                                active_rooms.append(room_name)
                        except (ValueError, TypeError):
                            pass
                    break

        # Fallback: Motion-Sensoren aus HA States durchsuchen
        if not active_rooms:
            for state in states:
                eid = state.get("entity_id", "")
                if "motion" in eid and state.get("state") == "on":
                    name = state.get("attributes", {}).get("friendly_name", eid)
                    room = name.replace("Bewegung ", "").replace(" Motion", "").lower()
                    if room not in active_rooms:
                        active_rooms.append(room)

        # Personen die zuhause sind
        persons_home = []
        for state in states:
            if state.get("entity_id", "").startswith("person."):
                if state.get("state") == "home":
                    persons_home.append(
                        state.get("attributes", {}).get("friendly_name", "User")
                    )

        # Einfache Zuordnung: Personen zum aktivsten Raum
        persons_by_room = {}
        if active_rooms and persons_home:
            # Erste Naeherung: Alle Personen im zuletzt aktiven Raum
            primary_room = active_rooms[0]
            persons_by_room[primary_room] = persons_home

        return {
            "persons_by_room": persons_by_room,
            "active_rooms": active_rooms,
            "speakers_by_room": room_speakers or {},
        }

    def get_person_room(self, person_name: str, states: list[dict] = None) -> Optional[str]:
        """Ermittelt in welchem Raum eine Person wahrscheinlich ist.

        Fuer Phase 10.2: Delegations-Routing.
        """
        # Erst konfigurierte preferred_room pruefen
        person_profiles = yaml_config.get("persons", {}).get("profiles", {})
        person_key = person_name.lower()
        if person_key in (person_profiles or {}):
            return person_profiles[person_key].get("preferred_room")

        # Fallback: Aktueller Raum (letzte Bewegung)
        if states:
            return self._guess_current_room(states)
        return None

    def _get_seasonal_context(self, states: Optional[list]) -> dict:
        """Ermittelt saisonale Kontextdaten."""
        now = datetime.now()
        month = now.month

        # Jahreszeit bestimmen
        if month in (3, 4, 5):
            season = "spring"
        elif month in (6, 7, 8):
            season = "summer"
        elif month in (9, 10, 11):
            season = "autumn"
        else:
            season = "winter"

        # Tageslaenge (vereinfacht fuer Mitteleuropa)
        day_of_year = now.timetuple().tm_yday
        sunrise_hour = 7 - 2 * math.cos(2 * math.pi * (day_of_year - 172) / 365)
        sunset_hour = 17 + 2 * math.cos(2 * math.pi * (day_of_year - 172) / 365)
        daylight_hours = sunset_hour - sunrise_hour

        seasonal_data = {
            "season": season,
            "daylight_hours": round(daylight_hours, 1),
            "sunrise_approx": f"{int(sunrise_hour)}:{int((sunrise_hour % 1) * 60):02d}",
            "sunset_approx": f"{int(sunset_hour)}:{int((sunset_hour % 1) * 60):02d}",
        }

        # Saisonale Config anhaengen
        if season in _SEASONAL_CONFIG:
            sc = _SEASONAL_CONFIG[season]
            seasonal_data["temp_offset"] = sc.get("temp_offset", 0)
            seasonal_data["briefing_extras"] = sc.get("briefing_extras", [])
            seasonal_data["ventilation_hint"] = sc.get("ventilation", "")
            seasonal_data["cover_hint"] = sc.get("cover_hint", "")

        # Daten aus HA-Entities uebernehmen (echte Werte statt Berechnungen)
        if states:
            for state in states:
                eid = state.get("entity_id", "")
                # Aussentemperatur vom Wetter-Entity
                if eid.startswith("weather."):
                    seasonal_data["outside_temp"] = state.get("attributes", {}).get("temperature")
                # Echte Sonnenzeiten von sun.sun
                elif eid == "sun.sun":
                    sun_attrs = state.get("attributes", {})
                    rising = sun_attrs.get("next_rising", "")
                    setting = sun_attrs.get("next_setting", "")
                    if rising:
                        try:
                            r = datetime.fromisoformat(rising.replace("Z", "+00:00"))
                            seasonal_data["sunrise_approx"] = r.strftime("%H:%M")
                        except (ValueError, TypeError):
                            pass
                    if setting:
                        try:
                            s_time = datetime.fromisoformat(setting.replace("Z", "+00:00"))
                            seasonal_data["sunset_approx"] = s_time.strftime("%H:%M")
                        except (ValueError, TypeError):
                            pass

        return seasonal_data
