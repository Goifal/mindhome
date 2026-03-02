"""
Context Builder - Sammelt alle relevanten Daten fuer den LLM-Prompt.
Holt Daten von Home Assistant, MindHome und Semantic Memory via REST API.

Phase 7: Raum-Profile und saisonale Anpassungen.
Phase 10: Multi-Room Presence Tracking.
"""

import logging
import math
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from .config import yaml_config, resolve_person_by_entity
from .function_calling import get_mindhome_room, get_entity_annotation, is_entity_hidden
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

# F-001/F-004/F-013-F-017: Prompt-Injection-Schutz fuer LLM-Kontext
_INJECTION_PATTERN = re.compile(
    r'\[(?:SYSTEM|INSTRUCTION|OVERRIDE|ADMIN|COMMAND|PROMPT|ROLE)\b'
    r'|IGNORE\s+(?:ALL\s+)?(?:PREVIOUS\s+)?INSTRUCTIONS'
    r'|SYSTEM\s*(?:MODE|OVERRIDE|INSTRUCTION)'
    r'|<\/?(?:system|instruction|admin|role|prompt)\b',
    re.IGNORECASE,
)


def _sanitize_for_prompt(text: str, max_len: int = 200, label: str = "") -> str:
    """Bereinigt externen Text bevor er in den LLM-Prompt eingebettet wird.

    Entfernt Newlines, Kontrollzeichen und verdaechtige Prompt-Injection-Patterns.
    """
    if not text or not isinstance(text, str):
        return ""
    # Kontrollzeichen und Newlines entfernen
    text = text.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
    # Mehrfach-Leerzeichen komprimieren
    text = re.sub(r'\s{2,}', ' ', text).strip()
    # Laenge begrenzen
    text = text[:max_len]
    # Injection-Patterns pruefen
    if _INJECTION_PATTERN.search(text):
        logger.warning(
            "Prompt-Injection-Verdacht in %s blockiert: %.80s",
            label or "Kontext", text,
        )
        return ""
    return text


# Relevante Entity-Typen fuer den Kontext
RELEVANT_DOMAINS = [
    "light", "climate", "cover", "scene", "person",
    "weather", "sensor", "binary_sensor", "media_player",
    "lock", "alarm_control_panel", "remote",
]


class ContextBuilder:
    """Baut den vollstaendigen Kontext fuer das LLM zusammen."""

    def __init__(self, ha_client: HomeAssistantClient):
        self.ha = ha_client
        self.semantic: Optional[SemanticMemory] = None
        self._activity_engine = None
        self._health_monitor = None
        self._redis = None
        # Weather-Warning-Cache (aendert sich selten, spart Iteration pro Request)
        self._weather_cache: list[str] = []
        self._weather_cache_ts: float = 0.0
        self._WEATHER_CACHE_TTL = 300.0  # 5 Minuten

    def set_semantic_memory(self, semantic: SemanticMemory):
        """Setzt die Referenz zum Semantic Memory."""
        self.semantic = semantic

    def set_redis(self, redis_client):
        """Setzt Redis-Client fuer Guest-Mode-Check."""
        self._redis = redis_client

    def set_activity_engine(self, activity_engine):
        """Setzt die Referenz zur Activity Engine (Phase 6)."""
        self._activity_engine = activity_engine

    def set_health_monitor(self, health_monitor):
        """Setzt die Referenz zum Health Monitor (fuer Trend-Indikatoren)."""
        self._health_monitor = health_monitor

    async def build(
        self, trigger: str = "voice", user_text: str = "", person: str = "",
        profile=None,
    ) -> dict:
        """
        Sammelt den kompletten Kontext.

        Args:
            trigger: Was den Kontext ausloest ("voice", "proactive", "api")
            user_text: User-Eingabe fuer semantische Suche
            person: Name der Person
            profile: Optionales RequestProfile fuer selektive Subsystem-Aktivierung.
                     Wenn None, werden alle Subsysteme aktiviert (Rueckwaertskompatibel).

        Returns:
            Strukturierter Kontext als Dict
        """
        context = {}

        # Zeitkontext — immer (trivial, kein I/O)
        now = datetime.now()
        context["time"] = {
            "datetime": now.strftime("%Y-%m-%d %H:%M"),
            "weekday": self._weekday_german(now.weekday()),
            "time_of_day": self._get_time_of_day(now.hour),
        }

        # --- Parallele I/O-Phase: Alle unabhaengigen Calls gleichzeitig ---
        import asyncio

        parallel_tasks: list[tuple[str, object]] = []

        # Haus-Status von HA
        if not profile or profile.need_house_status:
            parallel_tasks.append(("states", self.ha.get_states()))

        # MindHome-Daten (optional, falls MindHome installiert)
        if not profile or profile.need_mindhome_data:
            parallel_tasks.append(("mindhome", self._get_mindhome_data()))

        # Aktivitaets-Erkennung (Phase 6)
        if (not profile or profile.need_activity) and self._activity_engine:
            parallel_tasks.append(("activity", self._activity_engine.detect_activity()))

        # Health-Trend-Indikatoren (Raumklima-Trends aus Snapshots)
        if self._health_monitor:
            parallel_tasks.append(("health_trend", self._health_monitor.get_trend_summary()))

        # Semantisches Gedaechtnis — Guest-Mode-Check + Fakten parallel holen
        need_memories = not profile or profile.need_memories
        if need_memories and self._redis:
            parallel_tasks.append(("guest_mode", self._redis.get("mha:routine:guest_mode")))

        if parallel_tasks:
            _keys, _coros = zip(*parallel_tasks)
            _results = await asyncio.gather(*_coros, return_exceptions=True)
            _result_map = dict(zip(_keys, _results))
        else:
            _result_map = {}

        # --- Ergebnisse verarbeiten (sync, kein I/O) ---

        # Haus-Status
        states = _result_map.get("states")
        if isinstance(states, BaseException):
            logger.warning("get_states Fehler: %s", states)
            states = None
        if states:
            context["house"] = self._extract_house_status(states)
            context["person"] = self._extract_person(states)
            context["room"] = self._guess_current_room(states)

        # MindHome-Daten
        mindhome_data = _result_map.get("mindhome")
        if isinstance(mindhome_data, BaseException):
            logger.debug("MindHome nicht verfuegbar: %s", mindhome_data)
            mindhome_data = None
        if mindhome_data:
            context["mindhome"] = mindhome_data

        # Aktivitaet
        activity_result = _result_map.get("activity")
        if isinstance(activity_result, BaseException):
            logger.debug("Activity Engine Fehler: %s", activity_result)
        elif activity_result:
            context["activity"] = {
                "current": activity_result["activity"],
                "confidence": activity_result["confidence"],
            }

        # Phase 7: Raum-Profil zum Kontext hinzufuegen
        if not profile or profile.need_room_profile:
            current_room = context.get("room", "")
            room_profile = self._get_room_profile(current_room)
            if room_profile:
                context["room_profile"] = room_profile

        # Phase 7: Saisonale Daten (abhaengig von states)
        if states:
            context["seasonal"] = self._get_seasonal_context(states)

            # Phase 10: Multi-Room Presence
            context["room_presence"] = self._build_room_presence(states)

            # Wetter-Warnungen
            weather_warnings = self._check_weather_warnings(states)
            if weather_warnings:
                context.setdefault("weather_warnings", []).extend(weather_warnings)

            # Warnungen
            context["alerts"] = self._extract_alerts(states)

            # MCU-JARVIS: Anomalie-Kontext — ungewoehnliche Zustaende erkennen
            if yaml_config.get("mcu_intelligence", {}).get("anomaly_detection", True):
                anomalies = self._detect_anomalies(states)
                if anomalies:
                    context["anomalies"] = anomalies

        # Health-Trend-Indikatoren
        health_trend = _result_map.get("health_trend")
        if isinstance(health_trend, BaseException):
            logger.debug("Health-Trend Fehler: %s", health_trend)
        elif health_trend:
            context["health_trend"] = health_trend

        # Semantisches Gedaechtnis - relevante Fakten zur Anfrage
        # Im Guest-Mode keine persoenlichen Fakten preisgeben
        if need_memories:
            guest_mode_active = False
            guest_val = _result_map.get("guest_mode")
            if guest_val is not None and not isinstance(guest_val, BaseException):
                if isinstance(guest_val, bytes):
                    guest_val = guest_val.decode()
                guest_mode_active = guest_val == "active"

            if self.semantic and user_text and not guest_mode_active:
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

        mem_cfg = yaml_config.get("memory", {})
        max_relevant = int(mem_cfg.get("max_relevant_facts_in_context", 3))
        max_person = int(mem_cfg.get("max_person_facts_in_context", 5))
        min_confidence = float(mem_cfg.get("min_confidence_for_context", 0.6))

        try:
            # Fakten die zur aktuellen Anfrage passen
            relevant = await self.semantic.search_facts(
                query=user_text, limit=max_relevant, person=person or None
            )
            memories["relevant_facts"] = [
                sanitized for f in relevant
                if f.get("relevance", 0) > 0.3
                and (sanitized := _sanitize_for_prompt(f["content"], 500, "semantic_fact"))
            ]

            # Allgemeine Fakten ueber die Person (Praeferenzen)
            if person:
                person_facts = await self.semantic.get_facts_by_person(person)
                memories["person_facts"] = [
                    sanitized for f in person_facts[:max_person]
                    if f.get("confidence", 0) >= min_confidence
                    and (sanitized := _sanitize_for_prompt(f["content"], 500, "person_fact"))
                ]
        except Exception as e:
            logger.error("Fehler beim Laden semantischer Erinnerungen: %s", e)

        return memories

    def _extract_house_status(self, states: list[dict]) -> dict:
        """Extrahiert den Haus-Status aus HA States."""
        house = {
            "temperatures": {},
            "lights": [],
            "covers": [],
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

            # Hidden-Entities komplett ueberspringen
            if is_entity_hidden(entity_id):
                continue

            # Temperaturen (nur echte Raumthermostate, keine Waermepumpen/Fehler)
            if domain == "climate":
                current_temp = attrs.get("current_temperature")
                if current_temp is None:
                    continue
                try:
                    temp_val = float(current_temp)
                except (ValueError, TypeError):
                    continue
                # Sensor-Fehler (-128°C) und Nicht-Raum-Geraete (Waermepumpe >50°C) filtern
                if temp_val < -20 or temp_val > 50:
                    continue
                # MindHome-Raumnamen bevorzugen (konsistent mit function_calling)
                mh_room = get_mindhome_room(entity_id)
                if mh_room:
                    room = _sanitize_for_prompt(mh_room, 50, "climate_name")
                else:
                    room = _sanitize_for_prompt(attrs.get("friendly_name", entity_id), 50, "climate_name")
                if room:
                    # Duplikat-Schutz: bei gleichem Key Entity-Suffix anhaengen
                    if room in house["temperatures"]:
                        suffix = entity_id.split(".", 1)[-1] if "." in entity_id else entity_id
                        room = f"{room} ({suffix})"
                    house["temperatures"][room] = {
                        "current": current_temp,
                        "target": attrs.get("temperature"),
                        "mode": s,
                    }

            # Lichter (nur die an sind)
            elif domain == "light" and s == "on":
                # MindHome-Raumnamen bevorzugen (konsistent mit function_calling)
                mh_room = get_mindhome_room(entity_id)
                if mh_room:
                    name = _sanitize_for_prompt(mh_room, 50, "light_name")
                else:
                    name = _sanitize_for_prompt(attrs.get("friendly_name", entity_id), 50, "light_name")
                if not name:
                    continue
                brightness = attrs.get("brightness")
                if brightness:
                    pct = round(brightness / 255 * 100)
                    house["lights"].append(f"{name}: {pct}%")
                else:
                    house["lights"].append(f"{name}: an")

            # Personen
            elif domain == "person":
                name = _sanitize_for_prompt(attrs.get("friendly_name", entity_id), 50, "person_name")
                if not name:
                    continue
                if s == "home":
                    house["presence"]["home"].append(name)
                else:
                    house["presence"]["away"].append(name)

            # Wetter (Met.no via HA Integration)
            # F-037: Wetter-Beschreibungen sanitisieren
            elif domain == "weather" and not house["weather"]:
                house["weather"] = {
                    "temp": attrs.get("temperature"),
                    "condition": _sanitize_for_prompt(s, 50, "weather_condition"),
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
                            "condition": _sanitize_for_prompt(
                                entry.get("condition", ""), 50, "forecast_condition"
                            ),
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
                    "azimuth": attrs.get("azimuth"),   # Phase 11: Sonnenrichtung
                }

            # Alarm
            elif domain == "alarm_control_panel":
                house["security"] = s

            # Medien
            elif domain == "media_player" and s == "playing":
                name = _sanitize_for_prompt(attrs.get("friendly_name", entity_id), 50, "media_name")
                title = _sanitize_for_prompt(attrs.get("media_title", ""), 100, "media_title")
                if name:
                    house["media"].append(f"{name}: {title}" if title else name)

            # Cover-Status (Rolllaeden/Jalousien/Garagentore)
            elif domain == "cover" and s not in ("unavailable", "unknown"):
                mh_room = get_mindhome_room(entity_id)
                if mh_room:
                    name = _sanitize_for_prompt(mh_room, 50, "cover_name")
                else:
                    name = _sanitize_for_prompt(
                        attrs.get("friendly_name", entity_id), 50, "cover_name"
                    )
                if name:
                    pos = attrs.get("current_position")
                    if pos is not None:
                        house["covers"].append(f"{name}: {pos}%")
                    else:
                        state_de = {"open": "offen", "closed": "geschlossen",
                                    "opening": "oeffnet", "closing": "schliesst"}.get(s, s)
                        house["covers"].append(f"{name}: {state_de}")

            # Annotierte Switches (vom User im UI markierte Schalter)
            elif domain == "switch" and s not in ("unavailable", "unknown"):
                ann = get_entity_annotation(entity_id)
                role = ann.get("role", "")
                if role:
                    desc = ann.get("description", "")
                    if not desc:
                        desc = _sanitize_for_prompt(
                            attrs.get("friendly_name", entity_id), 50, "switch_name"
                        )
                    else:
                        desc = _sanitize_for_prompt(desc, 50, "switch_desc")
                    if desc:
                        switch_text = "an" if s == "on" else "aus"
                        house.setdefault("switches", []).append(f"{desc}: {switch_text}")

            # Fernbedienungen (Harmony etc.)
            elif domain == "remote":
                name = _sanitize_for_prompt(attrs.get("friendly_name", entity_id), 50, "remote_name")
                if name:
                    activity = attrs.get("current_activity", "PowerOff")
                    info = f"{name}: {activity}" if activity and activity != "PowerOff" else f"{name}: aus"
                    house.setdefault("remotes", []).append(info)

            # Energie-Sensoren (Strom-Verbrauch)
            elif domain == "sensor" and s not in ("unavailable", "unknown", ""):
                unit = attrs.get("unit_of_measurement", "")
                if unit in ("W", "kW", "kWh", "Wh"):
                    name = _sanitize_for_prompt(
                        attrs.get("friendly_name", entity_id), 60, "energy_name"
                    )
                    if name:
                        house.setdefault("energy", []).append(f"{name}: {s} {unit}")

                # Nur explizit annotierte Sensoren (User waehlt im UI aus)
                ann = get_entity_annotation(entity_id)
                role = ann.get("role", "")
                if role and role not in ("power_meter", "energy"):
                    desc = ann.get("description", "")
                    if not desc:
                        desc = _sanitize_for_prompt(
                            attrs.get("friendly_name", entity_id), 60, "sensor_name"
                        )
                    else:
                        desc = _sanitize_for_prompt(desc, 60, "sensor_desc")
                    if desc:
                        val_str = f"{s} {unit}".strip() if unit else s
                        house.setdefault("annotated_sensors", []).append({
                            "text": f"{desc}: {val_str}",
                            "_role": role,
                            "_state": s,
                        })

            # Nur explizit annotierte Binary-Sensoren (User waehlt im UI aus)
            elif domain == "binary_sensor" and s not in ("unavailable", "unknown"):
                ann = get_entity_annotation(entity_id)
                role = ann.get("role", "")
                if role:
                    desc = ann.get("description", "")
                    if not desc:
                        desc = _sanitize_for_prompt(
                            attrs.get("friendly_name", entity_id), 60, "binary_name"
                        )
                    else:
                        desc = _sanitize_for_prompt(desc, 60, "binary_desc")
                    if desc:
                        # Menschenlesbare Zustaende je nach Rolle
                        _BINARY_STATE_MAP_ON = {
                            "window_contact": "offen", "door_contact": "offen",
                            "garage_door": "offen", "gate": "offen",
                            "motion": "Bewegung erkannt", "occupancy": "belegt",
                            "presence": "anwesend", "vibration": "Vibration erkannt",
                            "water_leak": "WASSER ERKANNT", "smoke": "RAUCH ERKANNT",
                            "gas": "GAS ERKANNT", "co": "CO ERKANNT",
                            "tamper": "MANIPULATION ERKANNT", "alarm": "ALARM AKTIV",
                            "connectivity": "verbunden",
                            "running": "laeuft", "problem": "PROBLEM",
                            "update": "Update verfuegbar", "doorbell": "klingelt",
                            "rain_sensor": "Regen erkannt",
                        }
                        _BINARY_STATE_MAP_OFF = {
                            "window_contact": "geschlossen", "door_contact": "geschlossen",
                            "garage_door": "geschlossen", "gate": "geschlossen",
                            "connectivity": "getrennt",
                            "running": "aus", "rain_sensor": "kein Regen",
                        }
                        if s == "on":
                            state_text = _BINARY_STATE_MAP_ON.get(role, "aktiv")
                        else:
                            state_text = _BINARY_STATE_MAP_OFF.get(role, "inaktiv")
                        house.setdefault("annotated_sensors", []).append({
                            "text": f"{desc}: {state_text}",
                            "_role": role,
                            "_state": s,
                        })

            # Schloesser (Lock-Status) — alle lock.* Entities
            elif domain == "lock" and s in ("locked", "unlocked"):
                ann = get_entity_annotation(entity_id)
                desc = ann.get("description", "")
                if not desc:
                    desc = _sanitize_for_prompt(
                        attrs.get("friendly_name", entity_id), 50, "lock_name"
                    )
                else:
                    desc = _sanitize_for_prompt(desc, 50, "lock_desc")
                if desc:
                    lock_text = "verriegelt" if s == "locked" else "entriegelt"
                    house.setdefault("locks", []).append(f"{desc}: {lock_text}")

            # Kalender (naechster Termin aus HA State-Attribut)
            # state="on" = Termin findet GERADE statt
            # state="off" = kein aktueller Termin, aber start_time zeigt den naechsten
            elif domain == "calendar":
                summary = attrs.get("message", "")
                start = attrs.get("start_time", "")
                if summary and s == "on":
                    summary = _sanitize_for_prompt(summary, 100, "calendar_summary")
                    if summary:
                        house.setdefault("calendar", []).append(
                            f"{summary}" + (f" um {start}" if start else "")
                        )
                elif s == "off" and start:
                    # Naechster anstehender Termin (nicht aktiv)
                    summary = _sanitize_for_prompt(
                        attrs.get("message", ""), 100, "calendar_next"
                    )
                    if summary:
                        house.setdefault("calendar", []).append(
                            f"[naechster] {summary} um {start}"
                        )

        # Annotierte Sensoren: Priorisiert sortieren + auf Text reduzieren
        # Niedrige Zahl = hoehere Prioritaet (wird zuerst angezeigt)
        _ROLE_PRIORITY = {
            # Alarme & Sicherheit (immer zuerst!)
            "water_leak": 0, "smoke": 0, "gas": 0, "co": 0,
            "tamper": 0, "alarm": 0,
            # Oeffnungen (offene Fenster/Tueren wichtig)
            "window_contact": 1, "door_contact": 1,
            "garage_door": 1, "gate": 1, "lock": 1, "doorbell": 1,
            # Aktivitaet
            "motion": 2, "presence": 2, "occupancy": 2,
            # Temperatur
            "outdoor_temp": 3, "indoor_temp": 4, "water_temp": 4, "soil_temp": 5,
            # Raumklima
            "humidity": 5, "co2": 5, "voc": 5, "pm25": 5, "pm10": 5,
            "air_quality": 5, "pressure": 6,
            # Wetter
            "wind_speed": 6, "rain": 6, "rain_sensor": 6, "uv_index": 6,
            # Energie
            "solar": 7, "power_meter": 7, "energy": 7, "ev_charger": 7,
            # Geraete-Status
            "running": 8, "problem": 8, "connectivity": 8, "update": 8,
            # Sonstiges
            "light_level": 9, "vibration": 9, "battery": 9, "noise": 9,
        }
        _CRITICAL_ROLES = {"water_leak", "smoke", "gas", "co", "tamper", "alarm"}
        if house.get("annotated_sensors"):
            house["annotated_sensors"].sort(
                key=lambda x: _ROLE_PRIORITY.get(x.get("_role", ""), 99)
            )
            sensor_limit = yaml_config.get("sensor_context_limit", 20)
            # Critical alarm sensors (active) are always included
            critical = [e for e in house["annotated_sensors"]
                        if e.get("_role") in _CRITICAL_ROLES
                        and e.get("_state") in ("on", "detected", "aktiv")]
            rest = [e for e in house["annotated_sensors"] if e not in critical]
            remaining_slots = max(sensor_limit - len(critical), 0)
            combined = critical + rest[:remaining_slots]
            house["sensors"] = [e["text"] for e in combined]
            del house["annotated_sensors"]

        # Mittelwert aus konfigurierten Sensoren (hat Vorrang vor climate entities)
        rt_sensors = yaml_config.get("room_temperature", {}).get("sensors", []) or []
        if rt_sensors:
            state_map = {s_item.get("entity_id"): s_item for s_item in states}
            sensor_temps = []
            for sid in rt_sensors:
                st = state_map.get(sid, {})
                try:
                    sensor_temps.append(float(st.get("state", "")))
                except (ValueError, TypeError):
                    pass
            if sensor_temps:
                house["avg_temperature"] = round(sum(sensor_temps) / len(sensor_temps), 1)

        return house

    def _extract_person(self, states: list[dict]) -> dict:
        """Findet die aktive Person."""
        for state in states:
            eid = state.get("entity_id", "")
            if eid.startswith("person."):
                if state.get("state") == "home":
                    # Entity-ID-Mapping hat Vorrang (zuverlaessiger als friendly_name)
                    name = resolve_person_by_entity(eid)
                    if not name:
                        name = state.get("attributes", {}).get(
                            "friendly_name", "User"
                        )
                    return {"name": name, "last_room": "unbekannt"}
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

    def _check_weather_warnings(self, states: list[dict]) -> list[str]:
        """Prueft Wetter-Daten auf Warnwuerdiges (5-Min-Cache)."""
        import time as _time
        now = _time.time()
        if self._weather_cache_ts and (now - self._weather_cache_ts) < self._WEATHER_CACHE_TTL:
            return self._weather_cache

        warnings = []
        weather_cfg = yaml_config.get("weather_warnings", {})
        if not weather_cfg.get("enabled", True):
            return warnings

        temp_warn_high = float(weather_cfg.get("temp_high", 35))
        temp_warn_low = float(weather_cfg.get("temp_low", -5))
        wind_warn = float(weather_cfg.get("wind_speed_high", 60))
        warn_conditions = weather_cfg.get("warn_conditions", [
            "lightning", "lightning-rainy", "hail", "exceptional",
        ])

        for state in states:
            if not state.get("entity_id", "").startswith("weather."):
                continue

            attrs = state.get("attributes", {})
            condition = state.get("state", "")
            temp = attrs.get("temperature")
            wind = attrs.get("wind_speed")

            # Extreme Temperatur
            if temp is not None:
                try:
                    t = float(temp)
                    if t >= temp_warn_high:
                        warnings.append(f"Hitzewarnung: {t}°C Aussentemperatur")
                    elif t <= temp_warn_low:
                        warnings.append(f"Kaeltewarnung: {t}°C Aussentemperatur")
                except (ValueError, TypeError):
                    pass

            # Starker Wind
            if wind is not None:
                try:
                    w = float(wind)
                    if w >= wind_warn:
                        warnings.append(f"Sturmwarnung: Wind {w} km/h")
                except (ValueError, TypeError):
                    pass

            # Gefaehrliche Wetterbedingungen
            if condition in warn_conditions:
                label = self._translate_weather_warning(condition)
                warnings.append(f"Wetterwarnung: {label}")

            # Forecast-Check: Kommt was Extremes?
            forecast = attrs.get("forecast", [])
            for fc in forecast[:3]:
                fc_cond = fc.get("condition", "")
                if fc_cond in warn_conditions:
                    fc_time = fc.get("datetime", "bald")
                    label = self._translate_weather_warning(fc_cond)
                    warnings.append(f"Wettervorwarnung: {label} erwartet ({fc_time[:16]})")
                    break  # Nur eine Vorwarnung

            break  # Nur erste Weather-Entity

        self._weather_cache = warnings
        self._weather_cache_ts = now
        return warnings

    @staticmethod
    def _translate_weather_warning(condition: str) -> str:
        """Uebersetzt gefaehrliche Wetterbedingungen."""
        translations = {
            "lightning": "Gewitter",
            "lightning-rainy": "Gewitter mit Regen",
            "hail": "Hagel",
            "exceptional": "Extreme Wetterlage",
        }
        return translations.get(condition, condition)

    def _extract_alerts(self, states: list[dict]) -> list[str]:
        """Extrahiert aktive Warnungen."""
        from .function_calling import is_window_or_door, get_opening_type
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

            # Fenster/Tueren offen — kategorisiert (Fenster/Tuer vs Tor)
            if is_window_or_door(entity_id, state):
                if s == "on":
                    name = state.get("attributes", {}).get(
                        "friendly_name", entity_id
                    )
                    opening_type = get_opening_type(entity_id, state)
                    label = "Tor offen" if opening_type == "gate" else "Offen"
                    alerts.append(f"{label}: {name}")

        return alerts

    @staticmethod
    def _detect_anomalies(states: list[dict]) -> list[str]:
        """Erkennt ungewoehnliche Zustaende im Haus.

        MCU-JARVIS-Feature: Liefert beilaeufige Beobachtungen fuer den
        System-Prompt, die der LLM in seine Antwort einfliessen lassen kann.

        Beispiel: 'Waschmaschine seit 3 Stunden im Pause-Modus.'
        """
        anomalies = []
        now = datetime.now()

        for state in states:
            eid = state.get("entity_id", "")
            s = state.get("state", "")
            attrs = state.get("attributes", {})
            name = attrs.get("friendly_name", eid)

            # Geraet seit langer Zeit in ungewoehnlichem Zustand
            last_changed = attrs.get("last_changed") or state.get("last_changed", "")
            if last_changed:
                try:
                    if isinstance(last_changed, str):
                        changed_dt = datetime.fromisoformat(
                            last_changed.replace("Z", "+00:00")
                        )
                        changed_dt = changed_dt.replace(tzinfo=None)
                    else:
                        changed_dt = None
                except (ValueError, TypeError):
                    changed_dt = None
            else:
                changed_dt = None

            # Waschmaschine/Trockner laenger als 3 Stunden aktiv
            if changed_dt and any(kw in eid for kw in ("washer", "dryer", "wasch", "trockner")):
                if s in ("on", "running", "paused"):
                    hours = (now - changed_dt).total_seconds() / 3600
                    if hours >= 3:
                        mode = "Pause" if s == "paused" else "aktiv"
                        anomalies.append(
                            f"{name} seit {hours:.0f} Stunden im {mode}-Modus."
                        )

            # Niedrige Batterie (<15%) — dringender als der Standard-Check
            battery = attrs.get("battery_level") or attrs.get("battery")
            if battery is not None:
                try:
                    bat_val = int(float(battery))
                    if bat_val <= 10:
                        anomalies.append(
                            f"{name}: Batterie bei {bat_val}% — Wechsel empfohlen."
                        )
                except (ValueError, TypeError):
                    pass

        return anomalies[:3]  # Max 3 Anomalien im Kontext

    async def _get_mindhome_data(self) -> Optional[dict]:
        """Holt optionale MindHome-Daten (parallel fuer Geschwindigkeit)."""
        import asyncio

        try:
            presence, energy = await asyncio.gather(
                self.ha.get_presence(),
                self.ha.get_energy(),
                return_exceptions=True,
            )
            data = {}
            if isinstance(presence, dict):
                data["presence"] = presence
            if isinstance(energy, dict):
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
    # Phase 7.7: Lernfaehiges Override
    # ------------------------------------------------------------------

    @staticmethod
    def get_room_override(room_name: str, override_type: str) -> Optional[dict]:
        """Prueft ob ein gelerntes Override fuer den Raum existiert.

        Override-Typen: temperature, light, cover, scene.
        Overrides werden in room_profiles.yaml unter rooms.{room}.overrides gespeichert
        und koennen durch User-Feedback gelernt werden.
        """
        if not room_name or not _ROOM_PROFILES:
            return None

        room_lower = room_name.lower().replace(" ", "_")
        profile = _ROOM_PROFILES.get(room_lower)
        if not profile:
            # Fuzzy match
            for key, p in _ROOM_PROFILES.items():
                if key in room_lower or room_lower in key:
                    profile = p
                    break
        if not profile:
            return None

        overrides = profile.get("overrides", {})
        if override_type in overrides:
            override = overrides[override_type]
            # Zeitbasiert: Pruefen ob Override gerade aktiv
            now = datetime.now()
            if "active_hours" in override:
                start_h, end_h = override["active_hours"]
                if start_h <= end_h:
                    if not (start_h <= now.hour < end_h):
                        return None
                else:
                    # Midnight-Crossing: z.B. 22-6
                    if not (now.hour >= start_h or now.hour < end_h):
                        return None
            return override
        return None

    @staticmethod
    def learn_room_override(room_name: str, override_type: str, value: dict):
        """Speichert ein gelerntes Override fuer einen Raum in die YAML-Datei.

        Wird aufgerufen wenn der User eine Einstellung korrigiert und Jarvis
        sich die Aenderung fuer diesen Raum merken soll.
        """
        room_lower = room_name.lower().replace(" ", "_")
        if room_lower not in _ROOM_PROFILES:
            _ROOM_PROFILES[room_lower] = {"name": room_name}

        profile = _ROOM_PROFILES[room_lower]
        if "overrides" not in profile:
            profile["overrides"] = {}
        profile["overrides"][override_type] = {
            **value,
            "learned_at": datetime.now().isoformat(),
        }

        # In YAML schreiben
        try:
            room_file = Path(__file__).parent.parent / "config" / "room_profiles.yaml"
            if room_file.exists():
                with open(room_file) as f:
                    data = yaml.safe_load(f) or {}
            else:
                data = {}
            data.setdefault("rooms", {})[room_lower] = profile
            import tempfile
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=str(room_file.parent), suffix=".yaml.tmp",
            )
            try:
                with os.fdopen(tmp_fd, "w") as tmp_f:
                    yaml.safe_dump(data, tmp_f, allow_unicode=True, default_flow_style=False)
                os.replace(tmp_path, str(room_file))
            except Exception:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise
            logger.info("Raum-Override gelernt: %s.%s = %s", room_lower, override_type, value)
        except Exception as e:
            logger.error("Fehler beim Speichern des Raum-Overrides: %s", e)

    # ------------------------------------------------------------------
    # Phase 7.9: Saisonale Rolladen-Steuerung
    # ------------------------------------------------------------------

    def get_cover_timing(self, states: Optional[list] = None) -> dict:
        """Berechnet optimale Rolladen-Zeiten basierend auf Saison + Sonnenstand.

        Returns:
            Dict mit open_time, close_time, reason
        """
        seasonal = self._get_seasonal_context(states)
        sunrise = seasonal.get("sunrise_approx", "07:00")
        sunset = seasonal.get("sunset_approx", "19:00")
        season = seasonal.get("season", "summer")
        outside_temp = seasonal.get("outside_temp")

        # Rolladen-Oeffnung: 30 Min nach Sonnenaufgang (im Sommer frueher)
        try:
            sr_parts = sunrise.split(":")
            sr_hour, sr_min = int(sr_parts[0]), int(sr_parts[1])
        except (ValueError, IndexError):
            sr_hour, sr_min = 7, 0

        offset_open = 30 if season == "summer" else 15
        open_min = max(0, min(1439, sr_hour * 60 + sr_min + offset_open))
        open_time = f"{open_min // 60:02d}:{open_min % 60:02d}"

        # Rolladen-Schliessung: Bei Sonnenuntergang (im Sommer spaeter wegen Hitze)
        try:
            ss_parts = sunset.split(":")
            ss_hour, ss_min = int(ss_parts[0]), int(ss_parts[1])
        except (ValueError, IndexError):
            ss_hour, ss_min = 19, 0

        # Hitze-Schutz: Im Sommer bei hohen Temperaturen frueher schliessen
        offset_close = 0
        reason = "Standard-Timing nach Sonnenstand"
        if season == "summer" and outside_temp and outside_temp > 28:
            offset_close = -60  # 1h frueher bei Hitze
            reason = f"Hitzeschutz (Aussen: {outside_temp}°C)"
        elif season == "winter":
            offset_close = -15  # Im Winter etwas frueher
            reason = "Winter: Frueher schliessen fuer Isolierung"

        close_min = max(0, min(1439, ss_hour * 60 + ss_min + offset_close))
        close_time = f"{close_min // 60:02d}:{close_min % 60:02d}"

        return {
            "open_time": open_time,
            "close_time": close_time,
            "season": season,
            "reason": reason,
            "sunrise": sunrise,
            "sunset": sunset,
        }

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

        timeout_minutes = int(multi_room_cfg.get("presence_timeout_minutes", 15))
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
            eid = state.get("entity_id", "")
            if eid.startswith("person."):
                if state.get("state") == "home":
                    pname = resolve_person_by_entity(eid)
                    if not pname:
                        pname = state.get("attributes", {}).get("friendly_name", "User")
                    persons_home.append(pname)

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
        person_profiles = yaml_config.get("person_profiles", {}).get("profiles", {})
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
