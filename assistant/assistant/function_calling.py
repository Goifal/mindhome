"""
Function Calling - Definiert und fuehrt Funktionen aus die der Assistent nutzen kann.
MindHome Assistant ruft über diese Funktionen Home Assistant Aktionen aus.

Phase 10: Room-aware TTS, Person Messaging, Trust-Level Pre-Check.
"""

import asyncio
import copy
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

import assistant.config as cfg_module
from .config import settings, yaml_config, get_room_profiles
from .config_versioning import ConfigVersioning
from .declarative_tools import (
    DeclarativeToolExecutor,
    get_registry as get_decl_registry,
)
from .ha_client import HomeAssistantClient

# ============================================================
# KERN-SCHUTZ: JARVIS darf seinen eigenen Kern NICHT ändern.
# - settings.yaml ist NICHT in _EDITABLE_CONFIGS
# - Kein exec/eval/subprocess/os.system in Tool-Pfaden
# - _EDITABLE_CONFIGS ist eine geschlossene Whitelist
# - Neue editierbare Configs MUESSEN hier explizit freigeschaltet werden
# - Immutable Keys (security, trust_levels, autonomy, models, dashboard)
#   sind in self_optimization.py per hardcoded frozenset geschuetzt
# ============================================================

# Config-Pfade für Phase 13.1 (Whitelist — nur diese darf Jarvis ändern)
_CONFIG_DIR = Path(__file__).parent.parent / "config"
_EDITABLE_CONFIGS = {
    "easter_eggs": _CONFIG_DIR / "easter_eggs.yaml",
    "opinion_rules": _CONFIG_DIR / "opinion_rules.yaml",
    "room_profiles": _CONFIG_DIR / "room_profiles.yaml",
}

from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
_LOCAL_TZ = ZoneInfo(yaml_config.get("timezone", "Europe/Berlin"))

# Room-Profiles: zentraler Cache aus config.py
_get_room_profiles = get_room_profiles


# ── Entity-Katalog: Echte Raum- und Entity-Namen für Tool-Beschreibungen ──
# Wird asynchron aus HA geladen und gecached (TTL 5 Min).
# Raumnamen kommen zusaetzlich aus room_profiles.yaml (immer verfügbar).
_entity_catalog: dict[str, list[str]] = {}
_entity_catalog_ts: float = 0.0
_CATALOG_TTL = 300  # 5 Minuten
_entity_catalog_lock = asyncio.Lock()  # R2: Schutz vor konkurrierenden Refresh-Aufrufen

# ── MindHome Domain-Mapping: Entity-ID → Domain-Name ──
# Wird aus /api/devices + /api/domains geladen.
# Damit weiss der Assistant z.B. dass "switch.steckdose_fenster" eine "switch" Domain
# ist und KEIN "door_window" (Fenster-Kontakt).
_mindhome_device_domains: dict[str, str] = {}  # ha_entity_id → domain_name
_mindhome_device_rooms: dict[str, str] = {}  # ha_entity_id → room_name
_mindhome_rooms: list[str] = []  # Raumnamen aus MindHome


def _get_config_rooms() -> list[str]:
    """Liefert Raumnamen aus room_profiles.yaml (gecached)."""
    profiles = _get_room_profiles()
    return sorted(profiles.get("rooms", {}).keys())


async def _load_mindhome_domains(ha: HomeAssistantClient) -> None:
    """Laedt Geräte-Domains und Räume von der MindHome Add-on API.

    Endpunkte:
      GET /api/domains → [{id, name, display_name_de, ...}]
      GET /api/devices → [{ha_entity_id, domain_id, room_id, name, ...}]
      GET /api/rooms   → [{id, name, ...}]

    Ergebnis wird in _mindhome_device_domains und _mindhome_rooms gecached.
    Damit weiss der Assistant z.B. dass "switch.steckdose_fenster" zur Domain
    "switch" gehört und KEIN Fenster-Kontakt (door_window) ist.
    """
    global _mindhome_device_domains, _mindhome_device_rooms, _mindhome_rooms
    try:
        import asyncio

        domains_data, devices_data, rooms_data = await asyncio.gather(
            ha.mindhome_get("/api/domains"),
            ha.mindhome_get("/api/devices"),
            ha.mindhome_get("/api/rooms"),
            return_exceptions=True,
        )

        # Fix: Exception-Objekte einzeln pruefen statt still zu akzeptieren
        for name, result in [
            ("domains", domains_data),
            ("devices", devices_data),
            ("rooms", rooms_data),
        ]:
            if isinstance(result, BaseException):
                logger.warning("MindHome API '%s' fehlgeschlagen: %s", name, result)

        # Domain-ID → Domain-Name Mapping
        domain_map: dict[int, str] = {}
        if isinstance(domains_data, list):
            for d in domains_data:
                did = d.get("id")
                dname = d.get("name", "")
                if did is not None and dname:
                    domain_map[did] = dname

        # Room-ID → Room-Name Mapping
        room_map: dict[int, str] = {}
        if isinstance(rooms_data, list):
            for r in rooms_data:
                rid = r.get("id")
                rname = r.get("name", "")
                if rid is not None and rname:
                    room_map[rid] = rname
            _mindhome_rooms = sorted(room_map.values())

        # Entity → Domain + Room zuordnen
        device_domains: dict[str, str] = {}
        device_rooms: dict[str, str] = {}
        if isinstance(devices_data, list):
            for dev in devices_data:
                entity_id = dev.get("ha_entity_id", "")
                if not entity_id:
                    continue
                d_id = dev.get("domain_id")
                r_id = dev.get("room_id")
                if d_id is not None and d_id in domain_map:
                    device_domains[entity_id] = domain_map[d_id]
                if r_id is not None and r_id in room_map:
                    device_rooms[entity_id] = room_map[r_id]

        _mindhome_device_domains = device_domains
        _mindhome_device_rooms = device_rooms
        logger.info(
            "MindHome Domain-Mapping geladen: %d Geräte, %d Räume, %d Domains",
            len(device_domains),
            len(_mindhome_rooms),
            len(domain_map),
        )
    except Exception as e:
        logger.debug("MindHome Domain-Mapping nicht verfügbar: %s", e)


def get_mindhome_domain(entity_id: str) -> str:
    """Gibt die MindHome-Domain für eine Entity-ID zurück (z.B. 'door_window', 'switch').

    Wenn keine MindHome-Zuordnung existiert, wird '' zurückgegeben.
    """
    return _mindhome_device_domains.get(entity_id, "")


def get_mindhome_room(entity_id: str) -> str:
    """Gibt den MindHome-Raum für eine Entity-ID zurück."""
    return _mindhome_device_rooms.get(entity_id, "")


# Woerter die "tor" als Substring enthalten aber KEINE Tore sind.
# Verhindert False-Positives bei z.B. "system_monitor", "motor_status".
_TOR_FALSE_POSITIVES = (
    "monitor",
    "motor",
    "actuator",
    "senator",
    "factor",
    "vector",
    "sector",
    "doctor",
    "director",
    "operator",
    "generator",
    "collector",
    "connector",
    "detector",
    "protector",
    "reactor",
    "torsion",
    "tortoise",
    "history",
    "factory",
    "store",
    "story",
    "restore",
    "storage",
    "tutorial",
    "editor",
    "visitor",
    "mentor",
    "process",
    "prozess",
)


def _has_tor_keyword(entity_id_lower: str) -> bool:
    """Prueft ob 'tor' in der Entity-ID ein echtes Tor (Gate) bedeutet.

    Erkennt: gartentor, tor_sensor, einfahrtstor, garagentor
    Ignoriert: system_monitor, motor_status, actuator_valve, detector
    """
    if "tor" not in entity_id_lower:
        return False
    # Blocklist: Wenn ein bekanntes False-Positive-Wort vorkommt → kein Tor
    if any(fp in entity_id_lower for fp in _TOR_FALSE_POSITIVES):
        return False
    return True


def is_window_or_door(entity_id: str, state: dict) -> bool:
    """Prueft zuverlaessig ob eine Entity ein Fenster/Tür/Tor-Kontakt ist.

    Prueft in dieser Reihenfolge (erste Übereinstimmung gewinnt):
    1. opening_sensors Config (explizit vom User konfiguriert)
    2. Negative-Filter: Non-Physical binary_sensors (System Monitor etc.)
    3. MindHome Domain-Zuordnung (vom User konfiguriert)
    4. HA device_class (automatisch von HA gesetzt)
    5. Fallback: binary_sensor mit window/door/fenster/tuer/tor/gate im entity_id

    Steckdosen, Schalter und Lichter werden NICHT als Fenster erkannt,
    auch wenn "fenster" im Entity-Namen vorkommt.
    """
    # 1. opening_sensors Config (zuverlaessigste Quelle — User hat explizit konfiguriert)
    cfg = get_opening_sensor_config(entity_id)
    if cfg:
        return True

    # 2. Negative-Filter: Entities die definitiv KEINE physischen Oeffnungssensoren sind.
    #    Verhindert False-Positives durch System Monitor Prozess-Sensoren,
    #    die über MindHome-Domain oder Keyword-Fallback faelschlich erkannt werden.
    attrs = state.get("attributes", {}) if isinstance(state, dict) else {}
    device_class = attrs.get("device_class", "")
    if device_class in ("running", "connectivity", "plug", "power", "update"):
        return False

    # 3. MindHome-Domain (vom User konfiguriert)
    mh_domain = _mindhome_device_domains.get(entity_id, "")
    if mh_domain:
        return mh_domain == "door_window"

    # 4. HA device_class
    if device_class in ("window", "door", "garage_door"):
        return True

    # 5. Fallback: Nur binary_sensor mit Keyword (inkl. Tor/Gate)
    ha_domain = entity_id.split(".")[0] if "." in entity_id else ""
    if ha_domain == "binary_sensor":
        lower_id = entity_id.lower()
        # Einfache Substring-Keywords (selten False-Positives)
        if any(kw in lower_id for kw in ("window", "door", "fenster", "tuer", "gate")):
            return True
        # "tor" mit Blocklist-Check um False-Positives
        # wie "monitor", "motor", "actuator" zu vermeiden
        if _has_tor_keyword(lower_id):
            return True

    return False


def get_opening_sensor_config(entity_id: str) -> dict:
    """Liefert die Konfiguration eines Oeffnungs-Sensors (Fenster/Tür/Tor).

    Liest aus settings.yaml → opening_sensors.entities.
    Gibt Defaults zurück wenn kein Eintrag existiert.
    """
    from .config import yaml_config

    entities = yaml_config.get("opening_sensors", {}).get("entities", {}) or {}
    return entities.get(entity_id, {})


# --- Entity-Annotations: Beschreibungen + Rollen für Sensoren/Aktoren ---

# Standard-Rollen (vordefiniert, User kann eigene in entity_roles hinzufuegen)
_DEFAULT_ROLES_DICT = {
    # --- Temperatur & Klima ---
    "indoor_temp": {"label": "Raumtemperatur", "icon": "\U0001f321\ufe0f"},
    "outdoor_temp": {"label": "Aussentemperatur", "icon": "\U0001f324\ufe0f"},
    "water_temp": {"label": "Wassertemperatur", "icon": "\U0001f30a"},
    "soil_temp": {"label": "Bodentemperatur", "icon": "\U0001f33f"},
    "humidity": {"label": "Luftfeuchtigkeit", "icon": "\U0001f4a7"},
    "pressure": {"label": "Luftdruck", "icon": "\U0001f4a8"},
    "dew_point": {"label": "Taupunkt", "icon": "\U0001f4a7"},
    # --- Luftqualitaet ---
    "co2": {"label": "CO2-Sensor", "icon": "\U0001f32c\ufe0f"},
    "co": {"label": "CO-Melder", "icon": "\u26a0\ufe0f"},
    "voc": {"label": "VOC-Sensor (flüchtige Stoffe)", "icon": "\U0001f4a8"},
    "pm25": {"label": "Feinstaub PM2.5", "icon": "\U0001f32b\ufe0f"},
    "pm10": {"label": "Feinstaub PM10", "icon": "\U0001f32b\ufe0f"},
    "air_quality": {"label": "Luftqualität", "icon": "\U0001f343"},
    "radon": {"label": "Radon", "icon": "\u2622\ufe0f"},
    # --- Wetter ---
    "wind_speed": {"label": "Windgeschwindigkeit", "icon": "\U0001f4a8"},
    "wind_direction": {"label": "Windrichtung", "icon": "\U0001f9ed"},
    "rain": {"label": "Niederschlag/Regen", "icon": "\U0001f327\ufe0f"},
    "rain_sensor": {"label": "Regensensor", "icon": "\U0001f327\ufe0f"},
    "uv_index": {"label": "UV-Index", "icon": "\u2600\ufe0f"},
    "solar_radiation": {"label": "Sonneneinstrahlung", "icon": "\u2600\ufe0f"},
    # --- Licht & Helligkeit ---
    "light": {"label": "Beleuchtung", "icon": "\U0001f4a1"},
    "dimmer": {"label": "Dimmer", "icon": "\U0001f4a1"},
    "color_light": {"label": "Farblicht/RGB", "icon": "\U0001f308"},
    "light_level": {"label": "Lichtsensor", "icon": "\u2600\ufe0f"},
    # --- Sicherheit & Alarm ---
    "smoke": {"label": "Rauchmelder", "icon": "\U0001f525"},
    "gas": {"label": "Gasmelder", "icon": "\u26a0\ufe0f"},
    "water_leak": {"label": "Wassermelder", "icon": "\U0001f6b0"},
    "tamper": {"label": "Manipulationserkennung", "icon": "\U0001f6a8"},
    "alarm": {"label": "Alarmanlage", "icon": "\U0001f6a8"},
    "siren": {"label": "Sirene", "icon": "\U0001f4e2"},
    # --- Türen, Fenster, Oeffnungen ---
    "window_contact": {"label": "Fensterkontakt", "icon": "\U0001fa9f"},
    "door_contact": {"label": "Türkontakt", "icon": "\U0001f6aa"},
    "garage_door": {"label": "Garagentor", "icon": "\U0001f3e0"},
    "gate": {"label": "Tor/Einfahrt", "icon": "\U0001f3e0"},
    "lock": {"label": "Schloss", "icon": "\U0001f510"},
    "doorbell": {"label": "Türklingel", "icon": "\U0001f514"},
    # --- Bewegung & Anwesenheit ---
    "motion": {"label": "Bewegungsmelder", "icon": "\U0001f3c3"},
    "presence": {"label": "Anwesenheit", "icon": "\U0001f464"},
    "occupancy": {"label": "Raumbelegung", "icon": "\U0001f465"},
    "bed_occupancy": {"label": "Bettbelegung", "icon": "\U0001f6cf\ufe0f"},
    "chair_occupancy": {"label": "Stuhlbelegung", "icon": "\U0001fa91"},
    "vibration": {"label": "Vibration", "icon": "\U0001f4f3"},
    # --- Energie & Strom ---
    "power_meter": {"label": "Strommesser", "icon": "\u26a1"},
    "energy": {"label": "Energiezähler", "icon": "\U0001f4ca"},
    "voltage": {"label": "Spannung", "icon": "\u26a1"},
    "current": {"label": "Stromstärke", "icon": "\u26a1"},
    "power_factor": {"label": "Leistungsfaktor", "icon": "\U0001f4ca"},
    "frequency": {"label": "Frequenz", "icon": "\U0001f4ca"},
    "battery": {"label": "Batterie", "icon": "\U0001f50b"},
    "battery_charging": {"label": "Batterie laden", "icon": "\U0001f50b"},
    "solar": {"label": "Solaranlage/PV", "icon": "\u2600\ufe0f"},
    "grid_feed": {"label": "Netzeinspeisung", "icon": "\u26a1"},
    "grid_consumption": {"label": "Netzbezug", "icon": "\u26a1"},
    # --- Gas & Wasser Verbrauch ---
    "gas_consumption": {"label": "Gasverbrauch", "icon": "\U0001f525"},
    "water_consumption": {"label": "Wasserverbrauch", "icon": "\U0001f4a7"},
    # --- Heizung, Kuehlung, Klima ---
    "thermostat": {"label": "Thermostat", "icon": "\U0001f321\ufe0f"},
    "heating": {"label": "Heizung", "icon": "\U0001f525"},
    "cooling": {"label": "Kühlung", "icon": "\u2744\ufe0f"},
    "heat_pump": {"label": "Wärmepumpe", "icon": "\U0001f504"},
    "boiler": {"label": "Warmwasserboiler", "icon": "\U0001f6bf"},
    "radiator": {"label": "Heizkörper", "icon": "\U0001f321\ufe0f"},
    "floor_heating": {"label": "Fußbodenheizung", "icon": "\U0001f321\ufe0f"},
    # --- Lueftung ---
    "fan": {"label": "Lüfter", "icon": "\U0001f300"},
    "ventilation": {"label": "Lüftungsanlage", "icon": "\U0001f32c\ufe0f"},
    "air_purifier": {"label": "Luftreiniger", "icon": "\U0001f343"},
    "dehumidifier": {"label": "Entfeuchter", "icon": "\U0001f4a7"},
    "humidifier": {"label": "Befeuchter", "icon": "\U0001f4a7"},
    # --- Beschattung ---
    "blinds": {"label": "Rolladen/Jalousie", "icon": "\U0001fa9f"},
    "shutter": {"label": "Rollladen", "icon": "\U0001fa9f"},
    "awning": {"label": "Markise", "icon": "\u2602\ufe0f"},
    "curtain": {"label": "Vorhang", "icon": "\U0001fa9f"},
    # --- Steckdosen & Aktoren ---
    "outlet": {"label": "Steckdose", "icon": "\U0001f50c"},
    "valve": {"label": "Ventil", "icon": "\U0001f527"},
    "pump": {"label": "Pumpe", "icon": "\U0001f504"},
    "motor": {"label": "Motor", "icon": "\u2699\ufe0f"},
    "relay": {"label": "Relais", "icon": "\U0001f50c"},
    # --- Garten & Aussen ---
    "irrigation": {"label": "Bewässerung", "icon": "\U0001f331"},
    "pool": {"label": "Pool/Schwimmbad", "icon": "\U0001f3ca"},
    "soil_moisture": {"label": "Bodenfeuchtigkeit", "icon": "\U0001f331"},
    "garden_light": {"label": "Gartenbeleuchtung", "icon": "\U0001f33b"},
    # --- Medien & Unterhaltung ---
    "tv": {"label": "Fernseher", "icon": "\U0001f4fa"},
    "speaker": {"label": "Lautsprecher", "icon": "\U0001f50a"},
    "media_player": {"label": "Mediaplayer", "icon": "\u25b6\ufe0f"},
    "receiver": {"label": "AV-Receiver", "icon": "\U0001f3b5"},
    "projector": {"label": "Beamer/Projektor", "icon": "\U0001f4fd\ufe0f"},
    "gaming": {"label": "Spielkonsole", "icon": "\U0001f3ae"},
    # --- Kommunikation ---
    "phone": {"label": "Telefon", "icon": "\U0001f4de"},
    # --- Netzwerk & IT ---
    "router": {"label": "Router", "icon": "\U0001f4f6"},
    "server": {"label": "Server", "icon": "\U0001f5a5\ufe0f"},
    "nas": {"label": "NAS-Speicher", "icon": "\U0001f4be"},
    "printer": {"label": "Drucker", "icon": "\U0001f5a8\ufe0f"},
    "pc": {"label": "PC/Computer", "icon": "\U0001f4bb"},
    "adblocker": {"label": "Adblocker", "icon": "\U0001f6e1\ufe0f"},
    "speedtest": {"label": "Internet-Geschwindigkeit", "icon": "\U0001f4f6"},
    "signal_strength": {"label": "Signalstärke", "icon": "\U0001f4f6"},
    "connectivity": {"label": "Verbindungsstatus", "icon": "\U0001f4f6"},
    # --- Haushaltsgeraete ---
    "washing_machine": {"label": "Waschmaschine", "icon": "\U0001f9f9"},
    "dryer": {"label": "Trockner", "icon": "\U0001f32c\ufe0f"},
    "dishwasher": {"label": "Spülmaschine", "icon": "\U0001f37d\ufe0f"},
    "oven": {"label": "Backofen", "icon": "\U0001f373"},
    "fridge": {"label": "Kühlschrank", "icon": "\u2744\ufe0f"},
    "freezer": {"label": "Gefrierschrank", "icon": "\u2744\ufe0f"},
    "vacuum": {"label": "Staubsauger-Roboter", "icon": "\U0001f9f9"},
    "coffee_machine": {"label": "Kaffeemaschine", "icon": "\u2615"},
    "charger": {"label": "Ladegerät", "icon": "\U0001f50b"},
    # --- Fahrzeuge ---
    "ev_charger": {"label": "Wallbox/E-Auto-Lader", "icon": "\U0001f50c"},
    "car": {"label": "Auto/Fahrzeug", "icon": "\U0001f697"},
    "car_battery": {"label": "Auto-Batterie/SoC", "icon": "\U0001f50b"},
    "car_location": {"label": "Fahrzeug-Standort", "icon": "\U0001f4cd"},
    # --- Überwachung ---
    "camera": {"label": "Kamera", "icon": "\U0001f4f7"},
    "intercom": {"label": "Gegensprechanlage", "icon": "\U0001f4de"},
    # --- Sonstiges ---
    "scene": {"label": "Szene", "icon": "\U0001f3ac"},
    "automation": {"label": "Automatisierung", "icon": "\u2699\ufe0f"},
    "zone": {"label": "Zone", "icon": "\U0001f4cd"},
    "timer": {"label": "Timer/Zähler", "icon": "\u23f0"},
    "counter": {"label": "Zähler", "icon": "\U0001f522"},
    "distance": {"label": "Entfernung", "icon": "\U0001f4cf"},
    "speed": {"label": "Geschwindigkeit", "icon": "\U0001f4a8"},
    "weight": {"label": "Gewicht/Waage", "icon": "\u2696\ufe0f"},
    "noise": {"label": "Lärmsensor", "icon": "\U0001f50a"},
    "problem": {"label": "Problem/Störung", "icon": "\u26a0\ufe0f"},
    "update": {"label": "Update verfügbar", "icon": "\U0001f504"},
    "running": {"label": "Gerät läuft", "icon": "\u25b6\ufe0f"},
    "generic_sensor": {"label": "Sensor (allgemein)", "icon": "\U0001f4cb"},
    "generic_switch": {"label": "Schalter (allgemein)", "icon": "\U0001f4a1"},
}

_DEFAULT_ROLES = set(_DEFAULT_ROLES_DICT.keys())

# Auto-Erkennung: device_class → role (für Discovery-Endpoint)
_DEVICE_CLASS_TO_ROLE = {
    # Temperatur & Klima
    "temperature": "indoor_temp",
    "humidity": "humidity",
    "pressure": "pressure",
    "atmospheric_pressure": "pressure",
    # Luftqualitaet
    "co2": "co2",
    "carbon_dioxide": "co2",
    "carbon_monoxide": "co",
    "volatile_organic_compounds": "voc",
    "volatile_organic_compounds_parts": "voc",
    "pm25": "pm25",
    "pm10": "pm10",
    "aqi": "air_quality",
    "nitrogen_dioxide": "air_quality",
    "ozone": "air_quality",
    # Wetter
    "wind_speed": "wind_speed",
    "precipitation": "rain",
    "precipitation_intensity": "rain",
    "irradiance": "solar_radiation",
    # Licht
    "illuminance": "light_level",
    # Sicherheit
    "smoke": "smoke",
    "gas": "gas",  # binary_sensor: Gasdetektor
    "moisture": "water_leak",
    "tamper": "tamper",
    "safety": "alarm",
    "problem": "problem",
    # Oeffnungen
    "window": "window_contact",
    "door": "door_contact",
    "garage_door": "garage_door",
    "opening": "window_contact",
    "lock": "lock",
    # Bewegung & Anwesenheit
    "motion": "motion",
    "occupancy": "occupancy",
    "presence": "presence",
    "vibration": "vibration",
    "moving": "motion",
    "sound": "noise",
    # Energie & Strom
    "power": "power_meter",
    "energy": "energy",
    "battery": "battery",
    "battery_charging": "battery_charging",
    "voltage": "voltage",
    "current": "current",
    "power_factor": "power_factor",
    "frequency": "frequency",
    "apparent_power": "power_meter",
    "reactive_power": "power_meter",
    # Verbrauch (gas bereits oben als Detektor — sensor.gas wird in auto_detect_role behandelt)
    "water": "water_consumption",
    # Geräte
    "connectivity": "connectivity",
    "plug": "outlet",
    "running": "running",
    "update": "update",
    "signal_strength": "signal_strength",
    # Sonstiges
    "distance": "distance",
    "speed": "speed",
    "weight": "weight",
    "duration": "timer",
}

_OUTDOOR_KEYWORDS = (
    "aussen",
    "outdoor",
    "balkon",
    "garten",
    "terrasse",
    "draußen",
    "exterior",
    "outside",
    "patio",
    "roof",
    "dach",
    "carport",
    "garage",
    "weather",
    "wetter",
    "yard",
    "hof",
    "pergola",
    "veranda",
    "loggia",
    "wintergarten",
)
_WATER_TEMP_KEYWORDS = (
    "wasser",
    "water",
    "boiler",
    "pool",
    "heisswasser",
    "hot_water",
    "brauchwasser",
    "warmwasser",
    "zirkulation",
    "ruecklauf",
    "vorlauf",
    "flow_temp",
    "return_temp",
    "dhw",
)
_SOIL_TEMP_KEYWORDS = (
    "boden",
    "soil",
    "erde",
    "ground",
    "earth",
    "gewaechshaus",
    "greenhouse",
    "hochbeet",
    "raised_bed",
    "kompost",
    "compost",
)

# Role-Keywords für natürliche Sprache → Role-Matching in _find_entity()
_ROLE_KEYWORDS = {
    # Temperatur
    "outdoor_temp": [
        "aussen",
        "draußen",
        "outdoor",
        "balkon",
        "aussentemperatur",
        "gartentemperatur",
        "outside temperature",
        "exterior",
        "patio",
        "garden temperature",
        "weather temperature",
    ],
    "indoor_temp": [
        "innen",
        "raum",
        "drinnen",
        "raumtemperatur",
        "zimmertemperatur",
        "indoor",
        "room temperature",
        "inside temperature",
    ],
    "water_temp": [
        "wassertemperatur",
        "boiler",
        "warmwasser",
        "pooltemperatur",
        "water temperature",
        "hot water",
        "dhw",
        "flow temperature",
        "return temperature",
    ],
    "soil_temp": [
        "bodentemperatur",
        "erdtemperatur",
        "soil temperature",
        "ground temperature",
        "greenhouse",
    ],
    # Klima
    "humidity": [
        "feuchtigkeit",
        "feuchte",
        "luftfeuchte",
        "luftfeuchtigkeit",
        "humidity",
        "relative humidity",
        "moisture",
    ],
    "pressure": [
        "luftdruck",
        "druck",
        "barometer",
        "air pressure",
        "barometric",
        "atmospheric",
    ],
    # Luftqualitaet
    "co2": ["co2", "kohlendioxid", "carbon dioxide"],
    "co": ["kohlenmonoxid", "co-melder", "carbon monoxide"],
    "voc": ["voc", "fluechtige", "organische", "volatile organic", "tvoc"],
    "pm25": ["feinstaub", "pm2.5", "pm25", "partikel", "particulate", "fine dust"],
    "air_quality": [
        "luftqualitaet",
        "luft qualitaet",
        "aqi",
        "air quality",
        "air quality index",
    ],
    # Wetter
    "wind_speed": [
        "wind",
        "windgeschwindigkeit",
        "windstaerke",
        "wind speed",
        "wind gust",
        "windboee",
    ],
    "rain": ["regen", "niederschlag", "rain", "precipitation", "rainfall"],
    "uv_index": ["uv", "uv-index", "sonnenbrand", "ultraviolet"],
    # Sicherheit
    "smoke": ["rauch", "rauchmelder", "smoke", "smoke detector"],
    "gas": ["gas", "gasmelder", "erdgas", "gas detector", "natural gas"],
    "water_leak": [
        "wasserleck",
        "leck",
        "wassermelder",
        "überschwemmung",
        "water leak",
        "flood",
        "leak detector",
    ],
    "alarm": [
        "alarm",
        "alarmanlage",
        "einbruch",
        "security",
        "burglar",
        "intrusion",
        "sicherheit",
    ],
    "tamper": ["manipulation", "tamper", "sabotage", "tampering"],
    # Oeffnungen
    "window_contact": ["fenster", "window", "window sensor", "fensterkontakt"],
    "door_contact": [
        "tuer",
        "tuerkontakt",
        "door",
        "haustuer",
        "eingangstuer",
        "front door",
        "entrance",
        "door sensor",
    ],
    "garage_door": ["garage", "garagentor", "garage door"],
    "gate": ["tor", "einfahrt", "gate", "driveway"],
    "lock": ["schloss", "verriegelt", "lock", "deadbolt", "locked", "unlocked"],
    "doorbell": ["klingel", "tuerklingel", "doorbell", "ring", "chime"],
    # Bewegung
    "motion": [
        "bewegung",
        "motion",
        "bewegungsmelder",
        "motion sensor",
        "motion detector",
        "pir",
    ],
    "presence": [
        "anwesenheit",
        "zuhause",
        "abwesend",
        "presence",
        "home",
        "away",
        "at home",
        "not home",
    ],
    "occupancy": [
        "belegung",
        "besetzt",
        "raumbelegung",
        "occupancy",
        "occupied",
        "room occupancy",
    ],
    "bed_occupancy": [
        "bett",
        "bettbelegung",
        "bett sensor",
        "bed",
        "bed_occupancy",
        "schlafsensor",
        "bed sensor",
        "sleep sensor",
        "bed occupancy",
    ],
    "chair_occupancy": [
        "stuhl",
        "stuhlbelegung",
        "stuhlsensor",
        "chair",
        "sitzflaeche",
        "sitzsensor",
        "chair sensor",
        "seat sensor",
        "chair occupancy",
    ],
    # Energie
    "power_meter": [
        "strom",
        "leistung",
        "watt",
        "strommesser",
        "power",
        "power meter",
        "power consumption",
        "wattage",
    ],
    "energy": [
        "energie",
        "kwh",
        "energieverbrauch",
        "stromverbrauch",
        "energy",
        "energy consumption",
        "electricity",
    ],
    "voltage": ["spannung", "volt", "voltage"],
    "battery": ["batterie", "akku", "battery", "charge level"],
    "solar": [
        "solar",
        "photovoltaik",
        "pv",
        "solaranlage",
        "photovoltaic",
        "solar panel",
        "solar power",
    ],
    "ev_charger": [
        "wallbox",
        "ladestation",
        "e-auto",
        "elektroauto",
        "ev charger",
        "electric vehicle",
        "charging station",
        "evse",
    ],
    # Verbrauch
    "gas_consumption": [
        "gasverbrauch",
        "kubikmeter",
        "gas consumption",
        "gas meter",
        "gas usage",
    ],
    "water_consumption": [
        "wasserverbrauch",
        "water consumption",
        "water meter",
        "water usage",
    ],
    # Heizung & Klima
    "thermostat": ["thermostat", "temperature setpoint", "solltemperatur"],
    "heating": ["heizung", "heizen", "heating", "heat"],
    "cooling": [
        "kuehlung",
        "kühlen",
        "klimaanlage",
        "cooling",
        "air conditioning",
        "ac",
        "hvac",
    ],
    "heat_pump": ["waermepumpe", "heat pump"],
    "boiler": ["boiler", "warmwasserspeicher", "hot water tank"],
    "radiator": ["heizkoerper", "radiator"],
    "floor_heating": [
        "fussbodenheizung",
        "fbh",
        "underfloor heating",
        "floor heating",
        "ufh",
    ],
    # Lueftung
    "fan": ["luefter", "ventilator", "fan", "exhaust"],
    "ventilation": [
        "lueftung",
        "lueftungsanlage",
        "kwl",
        "ventilation",
        "hrv",
        "erv",
        "air exchange",
    ],
    "air_purifier": ["luftreiniger", "luftfilter", "air purifier", "air filter"],
    # Beschattung
    "blinds": ["rolladen", "jalousie", "rollo", "blinds", "shades", "roller shutter"],
    "shutter": ["rollladen", "shutter"],
    "awning": ["markise", "awning"],
    "curtain": ["vorhang", "gardine", "curtain", "drape"],
    # Steckdosen & Aktoren
    "outlet": ["steckdose", "stecker", "outlet", "plug", "socket"],
    "valve": ["ventil", "valve"],
    "pump": ["pumpe", "pump"],
    # Garten
    "irrigation": [
        "bewaesserung",
        "sprinkler",
        "gartenschlauch",
        "irrigation",
        "watering",
        "lawn",
    ],
    "pool": ["pool", "schwimmbad", "whirlpool", "swimming pool", "hot tub", "spa"],
    "soil_moisture": [
        "bodenfeuchtigkeit",
        "erdfeuchte",
        "soil moisture",
        "soil humidity",
    ],
    # Medien
    "tv": ["fernseher", "tv", "television"],
    "speaker": ["lautsprecher", "speaker", "box", "sonos", "echo", "homepod"],
    "media_player": ["mediaplayer", "player", "streamer", "media player"],
    "receiver": ["receiver", "verstaerker", "av-receiver", "amplifier", "av receiver"],
    # Kommunikation
    "phone": [
        "telefon",
        "phone",
        "sip",
        "anruf",
        "festnetz",
        "voip",
        "landline",
        "call",
    ],
    # Netzwerk
    "router": ["router", "wlan", "wifi", "access point", "mesh"],
    "server": ["server"],
    "nas": ["nas", "netzwerkspeicher", "network storage"],
    "pc": ["pc", "computer", "desktop", "rechner", "workstation"],
    "adblocker": [
        "adblocker",
        "adblock",
        "adguard",
        "pihole",
        "werbeblocker",
        "ad blocker",
        "dns filter",
    ],
    "speedtest": [
        "speedtest",
        "internetgeschwindigkeit",
        "internet speed",
        "internet geschwindigkeit",
        "bandbreite",
        "download speed",
        "upload speed",
        "bandwidth",
    ],
    # Haushaltsgeraete
    "washing_machine": [
        "waschmaschine",
        "waschen",
        "washing machine",
        "washer",
        "laundry",
    ],
    "dryer": ["trockner", "dryer", "tumble dryer"],
    "dishwasher": ["spuelmaschine", "geschirrspueler", "dishwasher"],
    "vacuum": [
        "staubsauger",
        "saugroboter",
        "roborock",
        "vacuum",
        "robot vacuum",
        "roomba",
    ],
    "coffee_machine": [
        "kaffeemaschine",
        "kaffee",
        "espresso",
        "coffee",
        "coffee machine",
        "coffee maker",
    ],
    # Fahrzeuge
    "car": ["auto", "fahrzeug", "pkw", "car", "vehicle"],
    "car_battery": [
        "autobatterie",
        "soc",
        "ladestand",
        "car battery",
        "state of charge",
        "ev battery",
    ],
    # Überwachung
    "camera": [
        "kamera",
        "überwachung",
        "cam",
        "camera",
        "surveillance",
        "cctv",
        "webcam",
    ],
    "intercom": [
        "gegensprech",
        "sprechanlage",
        "tuersprechanlage",
        "klingelanlage",
        "intercom",
        "door station",
        "video doorbell",
    ],
    # Zonen
    "zone": [
        "zone",
        "zonen",
        "bereich",
        "gebiet",
        "standort",
        "geofence",
        "area",
        "location",
    ],
    # --- Fehlende Rollen (für vollstaendiges LLM-Matching) ---
    # Temperatur & Klima
    "dew_point": ["taupunkt", "dew point"],
    # Luftqualitaet
    "pm10": ["pm10", "feinstaub pm10", "grobstaub", "coarse dust", "particulate pm10"],
    "radon": ["radon", "radon sensor", "radioaktiv"],
    # Wetter
    "wind_direction": ["windrichtung", "wind direction", "wind bearing"],
    "rain_sensor": ["regensensor", "regenmelder", "rain sensor", "rain detector"],
    "solar_radiation": [
        "sonneneinstrahlung",
        "solarstrahlung",
        "irradiance",
        "solar radiation",
        "sun intensity",
    ],
    # Licht & Helligkeit
    "light": ["licht", "lampe", "beleuchtung", "leuchte", "light", "lamp", "lighting"],
    "dimmer": [
        "dimmer",
        "dimmen",
        "dimmbar",
        "dimmschalter",
        "dimmer switch",
        "dimmable",
    ],
    "color_light": [
        "farblicht",
        "rgb",
        "farbig",
        "bunt",
        "farbwechsel",
        "color light",
        "rgb light",
        "hue",
        "color changing",
    ],
    "light_level": [
        "lichtsensor",
        "helligkeit",
        "lichtstaerke",
        "lux",
        "light sensor",
        "light level",
        "illuminance",
        "brightness sensor",
    ],
    # Sicherheit
    "siren": ["sirene", "alarmsirene", "siren", "horn"],
    # Bewegung & Anwesenheit
    "vibration": [
        "vibration",
        "erschuetterung",
        "vibrationssensor",
        "vibration sensor",
        "shock sensor",
    ],
    # Energie & Strom
    "current": ["stromstaerke", "ampere", "current", "amps"],
    "power_factor": ["leistungsfaktor", "cos phi", "power factor"],
    "frequency": ["frequenz", "hertz", "netzfrequenz", "frequency", "grid frequency"],
    "battery_charging": [
        "batterie laden",
        "akku laden",
        "ladevorgang",
        "battery charging",
        "charging",
    ],
    "grid_feed": [
        "netzeinspeisung",
        "einspeisung",
        "einspeisen",
        "grid feed",
        "feed-in",
        "grid export",
    ],
    "grid_consumption": [
        "netzbezug",
        "strombezug",
        "netzverbrauch",
        "grid consumption",
        "grid import",
    ],
    # Heizung & Klima
    "dehumidifier": [
        "entfeuchter",
        "luftentfeuchter",
        "raumentfeuchter",
        "dehumidifier",
    ],
    "humidifier": ["befeuchter", "luftbefeuchter", "raumbefeuchter", "humidifier"],
    # Steckdosen & Aktoren
    "motor": ["motor", "antrieb", "motor", "actuator", "drive"],
    "relay": ["relais", "schaltrelais", "relay", "switch relay"],
    # Garten
    "garden_light": [
        "gartenlicht",
        "gartenbeleuchtung",
        "gartenlampe",
        "aussenleuchte",
        "garden light",
        "outdoor light",
        "landscape light",
    ],
    # Medien & Unterhaltung
    "projector": ["beamer", "projektor", "projector"],
    "gaming": [
        "spielkonsole",
        "konsole",
        "playstation",
        "xbox",
        "nintendo",
        "gaming",
        "game console",
    ],
    # Netzwerk & IT
    "printer": ["drucker", "printer", "3d-drucker", "3d printer"],
    "signal_strength": ["signalstaerke", "empfang", "signal strength", "rssi", "snr"],
    "connectivity": [
        "verbindung",
        "verbindungsstatus",
        "online",
        "erreichbar",
        "connectivity",
        "connection status",
    ],
    # Haushaltsgeraete
    "oven": ["backofen", "ofen", "herd", "oven", "stove"],
    "fridge": ["kuehlschrank", "kuehl", "fridge", "refrigerator"],
    "freezer": ["gefrierschrank", "gefrier", "tiefkuehl", "freezer", "deep freeze"],
    "charger": ["ladegeraet", "lader", "charger"],
    # Fahrzeuge
    "car_location": [
        "auto standort",
        "fahrzeug standort",
        "auto position",
        "wo ist mein auto",
        "car location",
        "vehicle location",
        "car tracker",
    ],
    # Sonstiges
    "scene": ["szene", "scene"],
    "automation": ["automatisierung", "automation"],
    "timer": ["timer", "countdown", "stoppuhr", "timer", "stopwatch"],
    "counter": ["zaehler", "counter"],
    "distance": ["entfernung", "abstand", "distance"],
    "speed": ["geschwindigkeit", "speed", "tempo"],
    "weight": ["gewicht", "waage", "weight", "scale"],
    "noise": [
        "laerm",
        "lautstaerke",
        "geraeusch",
        "dezibel",
        "noise",
        "sound level",
        "decibel",
    ],
    "problem": ["problem", "stoerung", "fehler", "problem", "fault", "error"],
    "update": ["update", "aktualisierung", "firmware", "update available"],
    "running": ["laeuft", "aktiv", "in betrieb", "running", "active"],
    "generic_sensor": ["sensor", "messwert", "sensor", "reading"],
    "generic_switch": ["schalter", "switch"],
}


def _load_entity_roles_from_yaml():
    """Laedt Entity-Roles aus entity_roles_defaults.yaml (wenn vorhanden).

    Merged YAML-Daten über die Python-Defaults. Struktur:
      roles:
        indoor_temp:
          label: "Raumtemperatur"
          icon: "🌡️"
          keywords: ["innen", "raum", ...]
      device_class_to_role:
        temperature: "indoor_temp"
    """
    path = _CONFIG_DIR / "entity_roles_defaults.yaml"
    if not path.exists():
        return
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
        raw_roles = data.get("roles") or {}
        for role_id, info in raw_roles.items():
            if not isinstance(info, dict):
                continue
            _DEFAULT_ROLES_DICT[role_id] = {
                "label": info.get("label", role_id),
                "icon": info.get("icon", ""),
            }
            kw = info.get("keywords")
            if kw and isinstance(kw, list):
                _ROLE_KEYWORDS[role_id] = kw
        dc = data.get("device_class_to_role")
        if isinstance(dc, dict):
            _DEVICE_CLASS_TO_ROLE.update(dc)
        # _DEFAULT_ROLES aktualisieren
        _DEFAULT_ROLES.update(_DEFAULT_ROLES_DICT.keys())
        logger.debug("Entity-Roles aus YAML geladen (%d Rollen)", len(raw_roles))
    except Exception as e:
        logger.warning("entity_roles_defaults.yaml nicht ladbar: %s", e)


def reload_entity_roles():
    """Laedt Entity-Roles aus YAML neu (für Hot-Reload)."""
    _load_entity_roles_from_yaml()
    # User-Overrides aus settings.yaml erneut anwenden
    custom = yaml_config.get("entity_roles", {}) or {}
    for role_id, info in custom.items():
        if isinstance(info, dict):
            _DEFAULT_ROLES_DICT[role_id] = {
                "label": info.get("label", role_id),
                "icon": info.get("icon", ""),
            }
            kw = info.get("keywords")
            if kw and isinstance(kw, list):
                _ROLE_KEYWORDS[role_id] = kw
    _DEFAULT_ROLES.update(_DEFAULT_ROLES_DICT.keys())


# Beim Import laden
_load_entity_roles_from_yaml()


def get_entity_annotation(entity_id: str) -> dict:
    """Liefert die Annotation für eine Entity aus settings.yaml.

    Returns dict mit keys: description, role, room, hidden.
    Returns leeres dict wenn keine Annotation existiert.
    """
    annotations = yaml_config.get("entity_annotations", {}) or {}
    return annotations.get(entity_id, {})


def get_all_annotations() -> dict:
    """Liefert alle Entity-Annotations aus settings.yaml."""
    return yaml_config.get("entity_annotations", {}) or {}


def is_entity_hidden(entity_id: str) -> bool:
    """Prueft ob eine Entity als hidden markiert ist (vom LLM-Kontext ausgeschlossen)."""
    ann = get_entity_annotation(entity_id)
    return bool(ann.get("hidden", False))


def is_entity_annotated(entity_id: str) -> bool:
    """Prueft ob eine Entity in den Annotationen eingetragen ist."""
    annotations = yaml_config.get("entity_annotations", {}) or {}
    return entity_id in annotations


def get_all_roles() -> dict:
    """Liefert Standard-Rollen + eigene Rollen. Eigene überschreiben Standard."""
    roles = dict(_DEFAULT_ROLES_DICT)
    custom = yaml_config.get("entity_roles", {}) or {}
    roles.update(custom)
    return roles


def get_valid_roles() -> set:
    """Liefert alle gültigen Rollen-IDs (Standard + eigene)."""
    custom_roles = set((yaml_config.get("entity_roles", {}) or {}).keys())
    return _DEFAULT_ROLES | custom_roles


def auto_detect_role(domain: str, device_class: str, unit: str, entity_id: str) -> str:
    """Erkennt die Rolle einer Entity aus HA-Attributen (für Discovery-Vorschlaege)."""
    lower_eid = entity_id.lower()

    if domain == "binary_sensor":
        return _DEVICE_CLASS_TO_ROLE.get(device_class, "")

    if domain == "sensor":
        # Temperatur (mit Kontext-Erkennung: aussen/wasser/boden/innen)
        if device_class == "temperature" or unit in ("\u00b0C", "\u00b0F"):
            if any(kw in lower_eid for kw in _OUTDOOR_KEYWORDS):
                return "outdoor_temp"
            if any(kw in lower_eid for kw in _WATER_TEMP_KEYWORDS):
                return "water_temp"
            if any(kw in lower_eid for kw in _SOIL_TEMP_KEYWORDS):
                return "soil_temp"
            return "indoor_temp"
        # Klima
        if device_class == "humidity" or unit == "%rH":
            return "humidity"
        if device_class in ("pressure", "atmospheric_pressure") or unit in (
            "hPa",
            "mbar",
        ):
            return "pressure"
        # Luftqualitaet
        if device_class in ("co2", "carbon_dioxide") or (
            unit == "ppm" and "co2" in lower_eid
        ):
            return "co2"
        if device_class == "carbon_monoxide":
            return "co"
        if device_class in (
            "volatile_organic_compounds",
            "volatile_organic_compounds_parts",
        ):
            return "voc"
        if device_class == "pm25":
            return "pm25"
        if device_class == "pm10":
            return "pm10"
        if device_class in ("aqi", "nitrogen_dioxide", "ozone", "sulphur_dioxide"):
            return "air_quality"
        # Wetter
        if device_class == "wind_speed" or unit in ("m/s", "km/h", "mph"):
            if "wind" in lower_eid:
                return "wind_speed"
        if device_class in ("precipitation", "precipitation_intensity"):
            return "rain"
        if device_class == "irradiance" or unit in ("W/m\u00b2",):
            return "solar_radiation"
        if "uv" in lower_eid and (unit == "UV index" or "uv" in device_class):
            return "uv_index"
        # Licht
        if device_class == "illuminance" or unit in ("lx", "lux"):
            return "light_level"
        # Energie & Strom
        if device_class == "power" or unit in ("W", "kW"):
            if any(kw in lower_eid for kw in ("solar", "pv", "photovoltaik")):
                return "solar"
            if any(kw in lower_eid for kw in ("grid_feed", "einspeis")):
                return "grid_feed"
            if any(kw in lower_eid for kw in ("grid_consum", "netzbezug")):
                return "grid_consumption"
            return "power_meter"
        if device_class == "energy" or unit in ("kWh", "Wh"):
            if any(kw in lower_eid for kw in ("solar", "pv", "photovoltaik")):
                return "solar"
            return "energy"
        if device_class == "battery":
            return "battery"
        if device_class == "voltage" or unit == "V":
            return "voltage"
        if device_class == "current" or unit == "A":
            return "current"
        if device_class == "power_factor":
            return "power_factor"
        if device_class == "frequency" or unit == "Hz":
            return "frequency"
        # Verbrauch
        if device_class == "gas" or (unit in ("m\u00b3",) and "gas" in lower_eid):
            return "gas_consumption"
        if device_class == "water" or (
            unit in ("L", "m\u00b3") and "water" in lower_eid
        ):
            return "water_consumption"
        # Sonstiges
        if device_class == "signal_strength" or unit in ("dBm", "dB"):
            return "signal_strength"
        if device_class == "distance" or unit in ("m", "cm", "mm", "km"):
            if "entfern" in lower_eid or "distance" in lower_eid:
                return "distance"
        if device_class == "speed":
            return "speed"
        if device_class == "weight" or unit in ("kg", "g", "lb"):
            return "weight"
        if device_class == "duration":
            return "timer"
        if device_class == "sound_pressure" or unit == "dB":
            return "noise"
        # Fallback auf Mapping
        return _DEVICE_CLASS_TO_ROLE.get(device_class, "")

    if domain == "switch":
        if device_class == "outlet":
            return "outlet"
        if any(kw in lower_eid for kw in ("ventilat", "lueft", "fan", "exhaust")):
            return "fan"
        if any(
            kw in lower_eid
            for kw in (
                "bewaesser",
                "irrigat",
                "sprinkl",
                "water",
                "watering",
                "rasen",
                "lawn",
            )
        ):
            return "irrigation"
        if any(kw in lower_eid for kw in ("ventil", "valve")):
            return "valve"
        if any(kw in lower_eid for kw in ("steckdose", "plug", "socket", "outlet")):
            return "outlet"
        if any(kw in lower_eid for kw in ("pump", "pumpe")):
            return "pump"
        if any(kw in lower_eid for kw in ("heiz", "heat", "boiler")):
            return "heating"
        return ""

    if domain == "cover":
        if device_class in ("blind", "shutter"):
            return "blinds"
        if device_class == "awning":
            return "awning"
        if device_class == "curtain":
            return "curtain"
        if device_class == "garage":
            return "garage_door"
        if device_class == "gate":
            return "gate"
        if device_class == "window":
            return "blinds"
        return ""

    if domain == "lock":
        return "lock"

    if domain == "light":
        # Farblicht vs Dimmer vs einfaches Licht (kann nur per Attribute unterschieden werden)
        if any(
            kw in lower_eid
            for kw in ("rgb", "color", "farb", "hue", "strip", "led_strip")
        ):
            return "color_light"
        if any(kw in lower_eid for kw in ("dimm", "dim_")):
            return "dimmer"
        if any(
            kw in lower_eid
            for kw in ("garten", "garden", "aussen", "outdoor", "terrass")
        ):
            return "garden_light"
        return "light"

    if domain == "fan":
        return "fan"

    if domain == "vacuum":
        return "vacuum"

    if domain == "camera":
        return "camera"

    if domain == "media_player":
        if any(
            kw in lower_eid
            for kw in (
                "tv",
                "fernseh",
                "television",
                "fire_tv",
                "apple_tv",
                "chromecast",
            )
        ):
            return "tv"
        if any(
            kw in lower_eid for kw in ("receiver", "avr", "denon", "marantz", "yamaha")
        ):
            return "receiver"
        if any(
            kw in lower_eid
            for kw in ("sonos", "speaker", "echo", "homepod", "lautsprecher")
        ):
            return "speaker"
        return "media_player"

    return ""


def get_opening_type(entity_id: str, state: dict) -> str:
    """Bestimmt den Typ eines Oeffnungs-Sensors: window, door, oder gate.

    Prioritaet:
    1. opening_sensors Config (explizit vom User)
    2. HA device_class Mapping
    3. Keyword-Fallback
    """
    # 1. User-Config
    cfg = get_opening_sensor_config(entity_id)
    if cfg.get("type"):
        return cfg["type"]

    # 2. device_class
    attrs = state.get("attributes", {}) if isinstance(state, dict) else {}
    device_class = attrs.get("device_class", "")
    if device_class == "garage_door":
        return "gate"
    if device_class == "door":
        return "door"
    if device_class == "window":
        return "window"

    # 3. Keyword-Fallback
    lower_id = entity_id.lower()
    # "tor" mit Blocklist-Check um False-Positives (monitor, motor, ...) zu vermeiden
    if _has_tor_keyword(lower_id) or any(kw in lower_id for kw in ("gate", "garage")):
        return "gate"
    if any(kw in lower_id for kw in ("tuer", "door")):
        return "door"
    return "window"


def is_heating_relevant_opening(entity_id: str, state: dict) -> bool:
    """Prueft ob ein Oeffnungs-Sensor heizungsrelevant ist.

    Ein Sensor ist heizungsrelevant wenn:
    - Er ein Fenster oder eine Tür ist (NICHT ein Tor/Gate)
    - Er in einem beheizten Bereich liegt (heated != false)

    Tore (Garagentore, Gartentore) sind NIE heizungsrelevant,
    es sei denn der User hat heated=true explizit gesetzt.
    """
    if not is_window_or_door(entity_id, state):
        return False

    cfg = get_opening_sensor_config(entity_id)
    opening_type = get_opening_type(entity_id, state)

    # Expliziter heated-Wert aus Config hat Vorrang
    if "heated" in cfg:
        return bool(cfg["heated"])

    # Tore/Gates sind standardmaessig nicht heizungsrelevant
    if opening_type == "gate":
        return False

    # Fenster und Türen sind standardmaessig heizungsrelevant
    return True


async def refresh_entity_catalog(ha: HomeAssistantClient) -> None:
    """Laedt verfügbare Entities aus HA und cached Raum-/Geräte-Namen.

    Wird periodisch aufgerufen (z.B. alle 5 Min) um Tool-Beschreibungen
    mit echten Entity-Namen anzureichern.

    Laedt zusaetzlich Domain-Zuordnungen von der MindHome API,
    damit der Assistant weiss welche Geräte Fenster, Steckdosen, etc. sind.
    """
    global _entity_catalog, _entity_catalog_ts

    # R2: Lock verhindert parallele Refreshes (z.B. bei gleichzeitigen Requests)
    async with _entity_catalog_lock:
        # Falls ein anderer Refresh gerade fertig wurde, TTL prüfen
        if _entity_catalog and (time.time() - _entity_catalog_ts) < _CATALOG_TTL:
            return

        await _refresh_entity_catalog_inner(ha)


async def _refresh_entity_catalog_inner(ha: HomeAssistantClient) -> None:
    """Innerer Refresh ohne Lock (wird von refresh_entity_catalog aufgerufen)."""
    global _entity_catalog, _entity_catalog_ts, _tools_cache

    # MindHome Domain-Mapping laden (parallel zum HA-States-Abruf)
    import asyncio

    states_task = ha.get_states()
    mindhome_task = _load_mindhome_domains(ha)
    states, mindhome_result = await asyncio.gather(
        states_task, mindhome_task, return_exceptions=True
    )

    if isinstance(mindhome_result, BaseException):
        logger.warning("MindHome domain loading failed: %s", mindhome_result)

    if isinstance(states, BaseException) or not states:
        if isinstance(states, BaseException):
            logger.warning("HA States Fehler: %s", states)
        return

    rooms: set[str] = set()
    lights: list[str] = []
    switches: list[str] = []
    covers: list[str] = []
    sensors: list[str] = []
    binary_sensors: list[str] = []
    scenes: list[str] = []

    annotations = get_all_annotations()
    all_roles = get_all_roles()

    for state in states:
        eid = state.get("entity_id", "")
        attrs = state.get("attributes", {})
        friendly = attrs.get("friendly_name", "")
        if "." not in eid:
            continue
        domain, name = eid.split(".", 1)

        # Hidden-Entities überspringen
        if is_entity_hidden(eid):
            continue

        # Annotation-Hint erzeugen (Beschreibung/Rolle an den Eintrag anhaengen)
        ann = annotations.get(eid, {})
        ann_hint = ""
        if ann.get("description"):
            ann_hint = f" [{ann['description'][:40]}]"
        elif ann.get("role"):
            role_label = all_roles.get(ann["role"], {}).get("label", ann["role"])
            ann_hint = f" [{role_label}]"

        if domain == "light":
            entry = f"{name} ({friendly})" if friendly else name
            lights.append(f"{entry}{ann_hint}" if ann_hint else entry)
            rooms.add(name)
        elif domain == "switch":
            entry = f"{name} ({friendly})" if friendly else name
            switches.append(f"{entry}{ann_hint}" if ann_hint else entry)
        elif domain == "cover":
            entry = f"{name} ({friendly})" if friendly else name
            covers.append(f"{entry}{ann_hint}" if ann_hint else entry)
        elif domain == "scene":
            scenes.append(f"{name} ({friendly})" if friendly else name)
        elif domain in ("sensor", "binary_sensor"):
            # Annotierte Sensors bevorzugt, sonst auto_detect_role als Fallback
            role = ann.get("role", "")
            if not role:
                device_class = attrs.get("device_class", "")
                unit = attrs.get("unit_of_measurement", "")
                role = auto_detect_role(domain, device_class, unit, eid)
            if role:
                role_label = all_roles.get(role, {}).get("label", role)
                desc = ann.get("description", friendly or name)
                entry = f"{name} ({desc}) [{role_label}]"
                if domain == "sensor":
                    sensors.append(entry)
                else:
                    binary_sensors.append(entry)

    # Config-Räume immer hinzufuegen
    for r in _get_config_rooms():
        rooms.add(r)
    # MindHome-Räume (User-konfiguriert) immer hinzufuegen
    for r in _mindhome_rooms:
        rooms.add(r.lower())

    _entity_catalog = {
        "rooms": sorted(rooms),
        "lights": sorted(lights),
        "switches": sorted(switches),
        "covers": sorted(covers),
        "sensors": sorted(sensors),
        "binary_sensors": sorted(binary_sensors),
        "scenes": sorted(scenes),
    }
    _entity_catalog_ts = time.time()
    # Tools-Cache invalidieren NACH Entity-Katalog-Update (atomarer Swap)
    with _tools_cache_lock:
        _tools_cache = None
    logger.info(
        "Entity-Katalog aktualisiert: %d rooms, %d lights, %d switches, %d covers, "
        "%d sensors, %d binary_sensors, %d scenes",
        len(rooms),
        len(lights),
        len(switches),
        len(covers),
        len(sensors),
        len(binary_sensors),
        len(scenes),
    )


def _get_room_names() -> list[str]:
    """Liefert aktuelle Raumnamen (aus Cache oder Config-Fallback)."""
    catalog = _entity_catalog  # Snapshot-Referenz gegen Mid-Refresh-Reads
    if catalog.get("rooms"):
        return catalog["rooms"]
    return _get_config_rooms()


def _inject_entity_hints(tool: dict) -> dict:
    """Fuegt verfügbare Raum- und Entity-Namen in Tool-Beschreibungen ein.

    - Alle Tools mit 'room'-Parameter: Raumnamen-Liste anfuegen
    - set_switch/get_switches: Verfügbare Switches anfuegen
    - set_cover/get_covers: Verfügbare Covers anfuegen
    - set_light/get_lights: Verfügbare Lights anfuegen
    """
    func = tool.get("function", {})
    fname = func.get("name", "")
    params = func.get("parameters", {})
    props = params.get("properties", {})
    needs_copy = False

    # --- Room-Hints ---
    rooms = _get_room_names()
    room_prop = props.get("room")
    if rooms and room_prop:
        needs_copy = True

    # --- Entity-Hints (Switches, Covers, Lights, Sensors, Scenes) ---
    entity_hint = ""
    _ENTITY_MAP = {
        "set_switch": "switches",
        "get_switches": "switches",
        "set_cover": "covers",
        "get_covers": "covers",
        "set_light": "lights",
        "get_lights": "lights",
        "activate_scene": "scenes",
    }
    # get_entity_state bekommt Sensoren + Binary-Sensoren kombiniert
    # Priorisierung: Manuell annotierte und relevante Rollen (Power, Energy, Climate) zuerst
    catalog = _entity_catalog  # Snapshot-Referenz gegen Mid-Refresh-Reads
    if fname == "get_entity_state":
        combined = catalog.get("sensors", []) + catalog.get("binary_sensors", [])
        if combined:
            # Prioritaets-Rollen: Diese sind am häufigsten abgefragt
            _priority_roles = (
                "Strommesser",
                "Energie",
                "Innentemperatur",
                "Luftfeuchtigkeit",
                "CO2",
                "Batterie",
            )
            priority = [e for e in combined if any(r in e for r in _priority_roles)]
            rest = [e for e in combined if e not in priority]
            ordered = priority + rest
            entity_hint = ", ".join(ordered[:30])
            needs_copy = True
    # elif statt if — verhindert dass get_entity_state-Hint überschrieben wird
    elif (catalog_key := _ENTITY_MAP.get(fname)) and catalog.get(catalog_key):
        entities = catalog[catalog_key]
        if entities:
            entity_hint = ", ".join(entities[:30])  # Max 30 um Token zu sparen
            needs_copy = True

    if not needs_copy:
        return tool

    tool = copy.deepcopy(tool)

    # Room-Liste injizieren
    if rooms and room_prop:
        rp = tool["function"]["parameters"]["properties"]["room"]
        room_list = ", ".join(rooms)
        desc = rp.get("description", "Raumname")
        if "Verfügbare Räume:" in desc:
            desc = desc.split("Verfügbare Räume:")[0].rstrip()
        if "Verfügbare Geräte:" in desc:
            desc = desc.split("Verfügbare Geräte:")[0].rstrip()
        rp["description"] = f"{desc} — Verfügbare Räume: {room_list}"

    # Entity-Liste in die Tool-Beschreibung injizieren
    if entity_hint:
        tool_desc = tool["function"].get("description", "")
        if "Verfügbare Geräte:" in tool_desc:
            tool_desc = tool_desc.split("Verfügbare Geräte:")[0].rstrip()
        tool["function"]["description"] = (
            f"{tool_desc} — Verfügbare Geräte: {entity_hint}"
        )

    return tool


def _get_heating_mode() -> str:
    """Liefert den konfigurierten Heizungsmodus."""
    return yaml_config.get("heating", {}).get("mode", "room_thermostat")


def _get_climate_tool_description() -> str:
    """Dynamische Tool-Beschreibung je nach Heizungsmodus."""
    if _get_heating_mode() == "heating_curve":
        return (
            "Heizung steuern: Vorlauftemperatur-Offset zur Heizkurve anpassen. "
            "Positiver Offset = wärmer, negativer Offset = kälter."
        )
    return "Temperatur in einem Raum ändern. Für 'wärmer' verwende adjust='warmer', für 'kälter' verwende adjust='cooler' (ändert um 1°C)."


def _get_climate_tool_parameters() -> dict:
    """Dynamische Tool-Parameter je nach Heizungsmodus."""
    if _get_heating_mode() == "heating_curve":
        heating = yaml_config.get("heating", {})
        omin = heating.get("curve_offset_min", -5)
        omax = heating.get("curve_offset_max", 5)
        return {
            "type": "object",
            "properties": {
                "offset": {
                    "type": "number",
                    "description": f"Offset zur Heizkurve in Grad Celsius ({omin} bis {omax})",
                },
                "mode": {
                    "type": "string",
                    "enum": ["heat", "cool", "auto", "off"],
                    "description": "Heizmodus (optional)",
                },
            },
            "required": ["offset"],
        }
    return {
        "type": "object",
        "properties": {
            "room": {
                "type": "string",
                "description": "Raumname VOLLSTAENDIG inkl. Personen-Praefix falls genannt (z.B. 'manuel buero', 'julia buero'). NICHT den Personennamen weglassen!",
            },
            "temperature": {
                "type": "number",
                "description": "Zieltemperatur in Grad Celsius (optional bei adjust='warmer'/'cooler')",
            },
            "adjust": {
                "type": "string",
                "enum": ["warmer", "cooler"],
                "description": "Relative Anpassung: 'warmer' = +1°C, 'cooler' = -1°C. Wenn gesetzt, wird temperature ignoriert.",
            },
            "mode": {
                "type": "string",
                "enum": ["heat", "cool", "auto", "off"],
                "description": "Heizmodus (optional)",
            },
        },
        "required": ["room"],
    }


# Ollama Tool-Definitionen (Function Calling Format)
# ASSISTANT_TOOLS wird als Funktion gebaut, damit set_climate
# bei jedem Aufruf den aktuellen heating.mode aus yaml_config liest.
_ASSISTANT_TOOLS_STATIC = None


def _get_assistant_tools_static() -> list:
    """Lazy initialization of static tools list."""
    global _ASSISTANT_TOOLS_STATIC
    if _ASSISTANT_TOOLS_STATIC is not None:
        return _ASSISTANT_TOOLS_STATIC
    _ASSISTANT_TOOLS_STATIC = [
        {
            "type": "function",
            "function": {
                "name": "set_light",
                "description": "Licht in einem Raum ein-/ausschalten oder dimmen. Alle Lampen sind dim2warm — Farbtemperatur wird automatisch über die Helligkeit geregelt (Hardware). Für 'heller' verwende state='brighter', für 'dunkler' verwende state='dimmer'. Für Etagen: room='eg' oder room='og'. Wenn der User ein bestimmtes Licht meint (z.B. 'Stehlampe', 'Deckenlampe'), setze den device-Parameter.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "room": {
                            "type": "string",
                            "description": "Raumname VOLLSTAENDIG angeben inkl. Personen-Praefix falls genannt (z.B. 'buero_manuel', 'buero_julia', 'wohnzimmer', 'schlafzimmer'). NICHT den Personennamen weglassen! Für ganze Etage: 'eg' oder 'og'. Für alle: 'all'.",
                        },
                        "device": {
                            "type": "string",
                            "description": "Optionaler Gerätename wenn ein bestimmtes Licht gemeint ist (z.B. 'stehlampe', 'deckenlampe', 'nachttisch'). Ohne device wird das Hauptlicht im Raum geschaltet.",
                        },
                        "state": {
                            "type": "string",
                            "enum": ["on", "off", "brighter", "dimmer"],
                            "description": "Ein, aus, heller (+15%) oder dunkler (-15%)",
                        },
                        "brightness": {
                            "type": "integer",
                            "description": "Helligkeit 0-100 Prozent (optional, nur bei state='on'). WICHTIG: Wenn der User einen konkreten Wert nennt (z.B. 'auf 10%'), diesen EXAKT übernehmen — NICHT den aktuellen Kontextwert verwenden. Ohne Angabe wird adaptive Helligkeit nach Tageszeit berechnet.",
                        },
                        "transition": {
                            "type": "integer",
                            "description": "Übergangsdauer in Sekunden (optional, für sanftes Dimmen)",
                        },
                    },
                    "required": ["room", "state"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_lights",
                "description": "NUR zum Abfragen/Auflisten: Zeigt alle Lichter mit Name, Raum-Zuordnung und aktuellem Status (an/aus, Helligkeit). NICHT zum Schalten verwenden — dafuer set_light nutzen.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "room": {
                            "type": "string",
                            "description": "Raumname zum Filtern inkl. Personen-Praefix (z.B. 'manuel buero', optional, ohne = alle Lichter)",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "set_climate",
                "description": _get_climate_tool_description(),
                "parameters": _get_climate_tool_parameters(),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "activate_scene",
                "description": "Eine Szene aktivieren (z.B. filmabend, gute_nacht, gemuetlich, aufwachen, kochen, arbeiten, lesen, romantisch, putzen, musik, energiesparen). Optional mit Raum, Helligkeits- oder Temperatur-Override.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "scene": {
                            "type": "string",
                            "description": "Name der Szene",
                        },
                        "room": {
                            "type": "string",
                            "description": "Raum (optional, z.B. wohnzimmer, schlafzimmer)",
                        },
                        "brightness_override": {
                            "type": "integer",
                            "description": "Helligkeit ueberschreiben (0-100, optional)",
                        },
                        "temperature_override": {
                            "type": "number",
                            "description": "Temperatur ueberschreiben in Grad (optional)",
                        },
                    },
                    "required": ["scene"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "deactivate_scene",
                "description": "Eine aktive Szene beenden und vorherigen Zustand wiederherstellen (z.B. 'filmabend aus', 'szene beenden')",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "scene": {
                            "type": "string",
                            "description": "Name der Szene zum Beenden",
                        },
                    },
                    "required": ["scene"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "set_cover",
                "description": "Rollladen oder Markise steuern. NIEMALS für Garagentore! action: open/close/stop/half. position: 0-100%. Für Etagen: room='eg' oder room='og'. Für Markisen: type='markise'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "room": {
                            "type": "string",
                            "description": "Raumname VOLLSTAENDIG (z.B. 'buero_manuel', 'wohnzimmer'). Für ganze Etage: 'eg' oder 'og'. Für alle: 'all'. Für alle Markisen: 'markisen'.",
                        },
                        "action": {
                            "type": "string",
                            "enum": ["open", "close", "stop", "half"],
                            "description": "open=ganz oeffnen/hoch, close=ganz schließen/runter, stop=anhalten, half=halb offen.",
                        },
                        "position": {
                            "type": "integer",
                            "description": "Exakte Position 0 (zu) bis 100 (offen). Nur für Prozent-Angaben.",
                        },
                        "adjust": {
                            "type": "string",
                            "enum": ["up", "down"],
                            "description": "Relative Anpassung: 'up'=+20% offener, 'down'=-20% weiter zu.",
                        },
                        "type": {
                            "type": "string",
                            "enum": ["rollladen", "markise"],
                            "description": "Cover-Typ filtern (optional). Markisen haben eigene Sicherheits-Checks.",
                        },
                    },
                    "required": ["room"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_covers",
                "description": "NUR zum Abfragen: Zeigt alle Rollläden/Jalousien mit Name, Raum und Position (0=zu, 100=offen). NICHT zum Steuern — dafuer set_cover nutzen.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "room": {
                            "type": "string",
                            "description": "Raumname zum Filtern inkl. Personen-Praefix falls relevant (z.B. 'manuel buero', optional)",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "configure_cover_automation",
                "description": "Cover-Automatik konfigurieren: Wetter-Integration wechseln, Sonnenpruefung beim Aufwachen, Vorhersage-Schutz, Schwellwerte ändern. Nutze dies wenn der User sagt: 'Wechsle die Wetter-Integration', 'Nimm weather.home statt forecast', 'Aendere Hitzeschutz auf 28 Grad', 'Schalte Vorhersage-Schutz aus', 'Zeig die Cover-Automatik Einstellungen'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["get", "set"],
                            "description": "get=aktuelle Einstellungen anzeigen, set=Einstellungen ändern",
                        },
                        "weather_entity": {
                            "type": "string",
                            "description": "Wetter-Entity für Cover-Automatik (z.B. 'weather.forecast_home', 'weather.home'). Leer = automatische Erkennung.",
                        },
                        "forecast_weather_protection": {
                            "type": "boolean",
                            "description": "Vorhersage-basierten Wetterschutz aktivieren/deaktivieren",
                        },
                        "forecast_lookahead_hours": {
                            "type": "integer",
                            "description": "Vorhersage-Zeitraum in Stunden (1-8)",
                        },
                        "wakeup_sun_check": {
                            "type": "boolean",
                            "description": "Sonnenstand beim Aufwachen prüfen (verhindert Oeffnung bei Dunkelheit)",
                        },
                        "wakeup_min_sun_elevation": {
                            "type": "number",
                            "description": "Min. Sonnenhoehe in Grad (-12 bis 5). -6=buergerl. Daemmerung, 0=Sonnenaufgang",
                        },
                        "heat_protection_temp": {
                            "type": "number",
                            "description": "Hitzeschutz ab Aussentemperatur (Grad Celsius)",
                        },
                        "frost_protection_temp": {
                            "type": "number",
                            "description": "Frostschutz ab Temperatur (Grad Celsius)",
                        },
                        "storm_wind_speed": {
                            "type": "number",
                            "description": "Sturmschutz ab Windgeschwindigkeit (km/h)",
                        },
                        "weather_protection": {
                            "type": "boolean",
                            "description": "Wetter/Sturmschutz aktivieren/deaktivieren",
                        },
                        "sun_tracking": {
                            "type": "boolean",
                            "description": "Sonnenstand-Tracking aktivieren/deaktivieren",
                        },
                        "temperature_based": {
                            "type": "boolean",
                            "description": "Temperatur-basierte Steuerung aktivieren/deaktivieren",
                        },
                        "wakeup_fallback_max_minutes": {
                            "type": "integer",
                            "description": "Max. Minuten nach Aufwachzeit bis Oeffnung erzwungen wird (30-240)",
                        },
                        "night_insulation": {
                            "type": "boolean",
                            "description": "Nacht-Isolation (Rolladen nachts als Daemmung) an/aus",
                        },
                        "night_start_hour": {
                            "type": "integer",
                            "description": "Nacht-Start Stunde (0-23)",
                        },
                        "night_end_hour": {
                            "type": "integer",
                            "description": "Nacht-Ende Stunde (0-23)",
                        },
                        "presence_simulation": {
                            "type": "boolean",
                            "description": "Anwesenheitssimulation bei Abwesenheit an/aus",
                        },
                        "inverted_position": {
                            "type": "boolean",
                            "description": "Invertierte Position (0=offen statt 100=offen)",
                        },
                        "hysteresis_temp": {
                            "type": "number",
                            "description": "Temperatur-Hysterese in Grad (vermeidet staendiges Auf/Zu)",
                        },
                        "hysteresis_wind": {
                            "type": "number",
                            "description": "Wind-Hysterese in km/h",
                        },
                        "glare_protection": {
                            "type": "boolean",
                            "description": "Blendschutz (teilweises Schließen bei direkter Sonne) an/aus",
                        },
                        "gradual_morning": {
                            "type": "boolean",
                            "description": "Schrittweises Oeffnen am Morgen an/aus",
                        },
                        "wave_open": {
                            "type": "boolean",
                            "description": "Wellen-Oeffnung (Raum für Raum zeitversetzt) an/aus",
                        },
                        "heating_integration": {
                            "type": "boolean",
                            "description": "Heizungs-Integration (Rolladen als Daemmung bei aktiver Heizung) an/aus",
                        },
                        "co2_ventilation": {
                            "type": "boolean",
                            "description": "CO2-basierte Lueftung (oeffnet bei hohem CO2) an/aus",
                        },
                        "privacy_mode": {
                            "type": "boolean",
                            "description": "Sichtschutz-Modus (abends Rolladen schließen) an/aus",
                        },
                        "privacy_close_hour": {
                            "type": "integer",
                            "description": "Privacy ab Uhrzeit (15-22). Null = sobald es dunkel ist.",
                        },
                        "presence_aware": {
                            "type": "boolean",
                            "description": "Anwesenheits-basierte Steuerung an/aus",
                        },
                        "manual_override_hours": {
                            "type": "number",
                            "description": "Stunden die manuelle Übersteuerung aktiv bleibt (0.5-12)",
                        },
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "play_media",
                "description": "Musik oder Medien steuern: abspielen, pausieren, stoppen, Lautstärke ändern. Für 'leiser' verwende action='volume_down', für 'lauter' verwende action='volume_up'. Für eine bestimmte Lautstärke verwende action='volume' mit volume-Parameter.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "room": {
                            "type": "string",
                            "description": "Raumname (z.B. 'Wohnzimmer', 'Manuel Buero')",
                        },
                        "action": {
                            "type": "string",
                            "enum": [
                                "play",
                                "pause",
                                "stop",
                                "next",
                                "previous",
                                "volume",
                                "volume_up",
                                "volume_down",
                                "source",
                            ],
                            "description": "Medien-Aktion. 'volume' = Lautstärke auf Wert setzen, 'volume_up' = lauter (+10%), 'volume_down' = leiser (-10%), 'source' = Eingangsquelle wechseln (z.B. HDMI, TV, Bluetooth)",
                        },
                        "source": {
                            "type": "string",
                            "description": "Eingangsquelle fuer action='source' (z.B. 'HDMI1', 'TV', 'Bluetooth', 'AUX')",
                        },
                        "query": {
                            "type": "string",
                            "description": "Suchanfrage für Musik (z.B. 'Jazz', 'Beethoven', 'Chill Playlist')",
                        },
                        "media_type": {
                            "type": "string",
                            "enum": [
                                "music",
                                "podcast",
                                "audiobook",
                                "playlist",
                                "channel",
                            ],
                            "description": "Art des Mediums (Standard: music)",
                        },
                        "volume": {
                            "type": "number",
                            "description": "Lautstärke 0-100 (Prozent). Nur bei action='volume'. Z.B. 20 für 20%, 50 für 50%",
                        },
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "recommend_music",
                "description": "Smart DJ: Empfiehlt und spielt kontextbewusste Musik basierend auf Stimmung, Aktivität und Tageszeit. 'recommend' zeigt Vorschlag, 'play' spielt direkt ab, 'feedback' speichert Bewertung, 'status' zeigt aktuellen Kontext.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["recommend", "play", "feedback", "status"],
                            "description": "DJ-Aktion: recommend=Vorschlag anzeigen, play=direkt abspielen, feedback=Bewertung, status=Kontext anzeigen",
                        },
                        "positive": {
                            "type": "boolean",
                            "description": "Feedback: true=gefaellt, false=gefaellt nicht (nur bei action=feedback)",
                        },
                        "room": {
                            "type": "string",
                            "description": "Zielraum für Wiedergabe (optional)",
                        },
                        "genre": {
                            "type": "string",
                            "description": "Optionaler Genre-Override (z.B. 'party_hits', 'focus_lofi', 'jazz_dinner')",
                        },
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_media",
                "description": "NUR zum Abfragen: Zeigt alle Media Player mit Wiedergabestatus, Titel und Lautstärke. NICHT zum Steuern — dafuer play_media nutzen.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "room": {
                            "type": "string",
                            "description": "Raumname zum Filtern inkl. Personen-Praefix falls relevant (z.B. 'manuel buero', optional)",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "arm_security_system",
                "description": "Sicherheits-Alarmanlage (Einbruchschutz) scharf oder unscharf schalten.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": ["arm_home", "arm_away", "disarm"],
                            "description": "Sicherheitsmodus: arm_home=zuhause scharf, arm_away=abwesend scharf, disarm=entschaerfen",
                        },
                    },
                    "required": ["mode"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "lock_door",
                "description": "Tür ver- oder entriegeln",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "door": {
                            "type": "string",
                            "description": "Name der Tür",
                        },
                        "action": {
                            "type": "string",
                            "enum": ["lock", "unlock"],
                            "description": "Verriegeln oder entriegeln",
                        },
                    },
                    "required": ["door", "action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_climate",
                "description": "NUR zum Abfragen: Zeigt alle Thermostate/Heizungen mit Raum, Ist-Temperatur, Soll-Temperatur und Modus. NICHT zum Steuern — dafuer set_climate nutzen.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "room": {
                            "type": "string",
                            "description": "Raumname zum Filtern inkl. Personen-Praefix falls relevant (z.B. 'manuel buero', optional)",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_switches",
                "description": "Zeigt alle Steckdosen/Schalter (switch.*) mit Status (an/aus) und Leistungsdaten (Watt) falls verfügbar. Nutze dies auch für Fragen nach Stromverbrauch, Watt, Energie einzelner Geräte.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "room": {
                            "type": "string",
                            "description": "Raumname zum Filtern inkl. Personen-Praefix falls relevant (z.B. 'manuel buero', optional)",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "set_switch",
                "description": "Steckdose oder Schalter ein- oder ausschalten.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "room": {
                            "type": "string",
                            "description": "Raumname VOLLSTAENDIG inkl. Personen-Praefix falls genannt (z.B. 'manuel buero', 'julia buero', 'kueche') oder Name der Steckdose/des Schalters. NICHT den Personennamen weglassen!",
                        },
                        "state": {
                            "type": "string",
                            "enum": ["on", "off"],
                            "description": "Einschalten oder ausschalten",
                        },
                    },
                    "required": ["room", "state"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "send_notification",
                "description": "Benachrichtigung senden (optional gezielt in einen Raum)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Nachricht",
                        },
                        "target": {
                            "type": "string",
                            "enum": ["phone", "speaker", "dashboard"],
                            "description": "Ziel der Benachrichtigung",
                        },
                        "room": {
                            "type": "string",
                            "description": "Raum für TTS-Ausgabe (optional, nur bei target=speaker)",
                        },
                    },
                    "required": ["message"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "play_sound",
                "description": "Einen Sound-Effekt abspielen (z.B. Chime, Ping, Alert)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sound": {
                            "type": "string",
                            "enum": [
                                "listening",
                                "confirmed",
                                "warning",
                                "alarm",
                                "doorbell",
                                "greeting",
                                "error",
                                "goodnight",
                            ],
                            "description": "Sound-Event Name",
                        },
                        "room": {
                            "type": "string",
                            "description": "Raum in dem der Sound abgespielt werden soll (optional)",
                        },
                    },
                    "required": ["sound"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_entity_state",
                "description": "Status einer Home Assistant Entity abfragen (Temperatur, Watt, Strom, Feuchte, etc.). Funktioniert mit sensor.*, switch.*, light.*, climate.*, weather.* (z.B. weather.forecast_home), lock.*, media_player.*, binary_sensor.*, person.*. Für Stromverbrauch/Watt eines Geräts: nutze get_switches.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entity_id": {
                            "type": "string",
                            "description": "Entity-ID (z.B. sensor.temperatur_buero, weather.forecast_home, switch.steckdose_kueche)",
                        },
                    },
                    "required": ["entity_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_entity_history",
                "description": "Historische Daten einer Entity abrufen (z.B. Temperaturverlauf, Schalthistorie, Energieverbrauch der letzten Stunden/Tage). Nutze dies wenn der User nach Verlaeufen, Trends oder vergangenen Werten fragt.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entity_id": {
                            "type": "string",
                            "description": "Entity-ID (z.B. sensor.temperatur_buero, switch.steckdose_kueche)",
                        },
                        "hours": {
                            "type": "integer",
                            "description": "Anzahl zurückliegender Stunden (Standard: 24, Max: 720 = 30 Tage)",
                        },
                    },
                    "required": ["entity_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "send_message_to_person",
                "description": "Nachricht an eine bestimmte Person senden (TTS in deren Raum oder Push)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "person": {
                            "type": "string",
                            "description": "Name der Person (z.B. Lisa, Max)",
                        },
                        "message": {
                            "type": "string",
                            "description": "Die Nachricht",
                        },
                        "urgency": {
                            "type": "string",
                            "enum": ["low", "medium", "high"],
                            "description": "Dringlichkeit (optional, default: medium)",
                        },
                    },
                    "required": ["person", "message"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "transfer_playback",
                "description": "Musik-Wiedergabe von einem Raum in einen anderen übertragen",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "from_room": {
                            "type": "string",
                            "description": "Quell-Raum (wo die Musik gerade läuft)",
                        },
                        "to_room": {
                            "type": "string",
                            "description": "Ziel-Raum (wohin die Musik soll)",
                        },
                    },
                    "required": ["to_room"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_calendar_events",
                "description": "Kalender-Termine abrufen. Nutze dies wenn der User nach Terminen fragt, z.B. 'Was steht morgen an?', 'Was steht heute an?', 'Habe ich morgen Termine?', 'Was steht diese Woche an?'. Immer bevorzugt für zeitbezogene Fragen zu Plaenen und Terminen.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "timeframe": {
                            "type": "string",
                            "enum": ["today", "tomorrow", "week"],
                            "description": "Zeitraum: heute, morgen oder diese Woche",
                        },
                    },
                    "required": ["timeframe"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_calendar_event",
                "description": "Einen neuen Kalender-Termin erstellen",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Titel des Termins",
                        },
                        "date": {
                            "type": "string",
                            "description": "Datum im Format YYYY-MM-DD",
                        },
                        "start_time": {
                            "type": "string",
                            "description": "Startzeit im Format HH:MM (optional, ganztaegig wenn leer)",
                        },
                        "end_time": {
                            "type": "string",
                            "description": "Endzeit im Format HH:MM (optional, +1h wenn leer)",
                        },
                        "description": {
                            "type": "string",
                            "description": "Beschreibung (optional)",
                        },
                    },
                    "required": ["title", "date"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delete_calendar_event",
                "description": "Einen Kalender-Termin löschen",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Titel des Termins (oder Teil davon)",
                        },
                        "date": {
                            "type": "string",
                            "description": "Datum des Termins im Format YYYY-MM-DD",
                        },
                    },
                    "required": ["title", "date"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "reschedule_calendar_event",
                "description": "Einen Kalender-Termin verschieben (neues Datum/Uhrzeit)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Titel des bestehenden Termins",
                        },
                        "old_date": {
                            "type": "string",
                            "description": "Bisheriges Datum im Format YYYY-MM-DD",
                        },
                        "new_date": {
                            "type": "string",
                            "description": "Neues Datum im Format YYYY-MM-DD",
                        },
                        "new_start_time": {
                            "type": "string",
                            "description": "Neue Startzeit HH:MM (optional)",
                        },
                        "new_end_time": {
                            "type": "string",
                            "description": "Neue Endzeit HH:MM (optional)",
                        },
                    },
                    "required": ["title", "old_date", "new_date"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "set_presence_mode",
                "description": "Anwesenheitsmodus des Hauses setzen",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": ["home", "away", "sleep", "vacation"],
                            "description": "Anwesenheitsmodus",
                        },
                    },
                    "required": ["mode"],
                },
            },
        },
        # --- Phase 13.1: Config-Selbstmodifikation ---
        {
            "type": "function",
            "function": {
                "name": "edit_config",
                "description": "Eigene Konfiguration anpassen (Easter Eggs, Meinungen, Raum-Profile). Nutze dies um dich selbst zu verbessern.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "config_file": {
                            "type": "string",
                            "enum": ["easter_eggs", "opinion_rules", "room_profiles"],
                            "description": "Welche Konfiguration ändern (easter_eggs, opinion_rules, room_profiles)",
                        },
                        "action": {
                            "type": "string",
                            "enum": ["add", "remove", "update"],
                            "description": "Aktion: hinzufuegen, entfernen oder aktualisieren",
                        },
                        "key": {
                            "type": "string",
                            "description": "Schluessel/Name des Eintrags (z.B. 'star_wars' für Easter Egg, 'high_temp' für Opinion)",
                        },
                        "data": {
                            "type": "object",
                            "description": "Die Daten des Eintrags (z.B. {trigger: 'möge die macht', response: 'Immer, Sir.', enabled: true})",
                        },
                    },
                    "required": ["config_file", "action", "key"],
                },
            },
        },
        # --- Phase 15.2: Einkaufsliste ---
        {
            "type": "function",
            "function": {
                "name": "manage_shopping_list",
                "description": "Einkaufsliste verwalten (Artikel hinzufuegen, anzeigen, abhaken, entfernen)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["add", "list", "complete", "clear_completed"],
                            "description": "Aktion: hinzufuegen, auflisten, abhaken, abgehakte entfernen",
                        },
                        "item": {
                            "type": "string",
                            "description": "Artikelname (für add/complete)",
                        },
                    },
                    "required": ["action"],
                },
            },
        },
        # --- Phase 15.2: Vorrats-Tracking ---
        {
            "type": "function",
            "function": {
                "name": "manage_inventory",
                "description": "Vorratsmanagement: Artikel mit Ablaufdatum hinzufuegen, entfernen, auflisten, Menge ändern. Warnt bei bald ablaufenden Artikeln.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "add",
                                "remove",
                                "list",
                                "update_quantity",
                                "check_expiring",
                            ],
                            "description": "Aktion: hinzufuegen, entfernen, auflisten, Menge ändern, Ablauf prüfen",
                        },
                        "item": {
                            "type": "string",
                            "description": "Artikelname",
                        },
                        "quantity": {
                            "type": "integer",
                            "description": "Menge (Default: 1)",
                        },
                        "expiry_date": {
                            "type": "string",
                            "description": "Ablaufdatum im Format YYYY-MM-DD (optional)",
                        },
                        "category": {
                            "type": "string",
                            "enum": ["kuehlschrank", "gefrier", "vorrat", "sonstiges"],
                            "description": "Lagerort/Kategorie",
                        },
                    },
                    "required": ["action"],
                },
            },
        },
        # --- Smart Shopping: Verbrauchsprognose + Rezept-Zutaten ---
        {
            "type": "function",
            "function": {
                "name": "smart_shopping",
                "description": "Intelligente Einkaufslistenverwaltung: Verbrauchsprognose (wann wird etwas alle?), fehlende Rezept-Zutaten auf Liste setzen, Einkaufsmuster anzeigen.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "predictions",
                                "add_ingredients",
                                "record_purchase",
                                "shopping_pattern",
                            ],
                            "description": "predictions: Verbrauchsprognose anzeigen. add_ingredients: Rezept-Zutaten auf Einkaufsliste. record_purchase: Einkauf protokollieren. shopping_pattern: Einkaufstag-Muster.",
                        },
                        "item": {
                            "type": "string",
                            "description": "Artikelname (fuer record_purchase)",
                        },
                        "ingredients": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Zutatenliste (fuer add_ingredients)",
                        },
                    },
                    "required": ["action"],
                },
            },
        },
        # --- Konversations-Gedaechtnis++ ---
        {
            "type": "function",
            "function": {
                "name": "conversation_memory",
                "description": "Verwaltet Projekte, offene Fragen und Tages-Zusammenfassungen. Nutze dies wenn der User ueber laufende Projekte spricht, Fragen fuer spaeter merken will, oder nach frueheren Gespraechen fragt.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "create_project",
                                "update_project",
                                "list_projects",
                                "delete_project",
                                "add_question",
                                "answer_question",
                                "list_questions",
                                "save_summary",
                                "get_summary",
                            ],
                            "description": "create_project/update_project/list_projects/delete_project: Projekt-Verwaltung. add_question/answer_question/list_questions: Offene Fragen. save_summary/get_summary: Tages-Zusammenfassung.",
                        },
                        "name": {
                            "type": "string",
                            "description": "Projektname (fuer create/update/delete_project)",
                        },
                        "description": {
                            "type": "string",
                            "description": "Beschreibung (fuer create_project)",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["active", "paused", "done"],
                            "description": "Projektstatus (fuer update_project)",
                        },
                        "note": {
                            "type": "string",
                            "description": "Notiz zum Projekt (fuer update_project)",
                        },
                        "milestone": {
                            "type": "string",
                            "description": "Meilenstein (fuer update_project)",
                        },
                        "question": {
                            "type": "string",
                            "description": "Frage-Text (fuer add_question/answer_question)",
                        },
                        "answer": {
                            "type": "string",
                            "description": "Antwort (fuer answer_question)",
                        },
                        "summary": {
                            "type": "string",
                            "description": "Zusammenfassung (fuer save_summary)",
                        },
                        "topics": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Themen-Liste (fuer save_summary)",
                        },
                        "date": {
                            "type": "string",
                            "description": "Datum YYYY-MM-DD (fuer get_summary, optional)",
                        },
                        "person": {
                            "type": "string",
                            "description": "Person (optional, fuer Zuordnung)",
                        },
                    },
                    "required": ["action"],
                },
            },
        },
        # --- Multi-Room Audio Sync ---
        {
            "type": "function",
            "function": {
                "name": "multi_room_audio",
                "description": "Verwaltet Speaker-Gruppen fuer synchrone Multi-Room-Wiedergabe. Erstelle Gruppen wie 'Erdgeschoss' oder 'Party', spiele Musik synchron auf allen Speakern einer Gruppe.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "create_group",
                                "delete_group",
                                "modify_group",
                                "list_groups",
                                "play",
                                "stop",
                                "pause",
                                "volume",
                                "status",
                                "discover_speakers",
                            ],
                            "description": "create_group/delete_group/modify_group/list_groups: Gruppen verwalten. play/stop/pause: Wiedergabe steuern. volume: Lautstaerke. status: Gruppen-Status. discover_speakers: Verfuegbare Speaker erkennen.",
                        },
                        "group_name": {
                            "type": "string",
                            "description": "Name der Speaker-Gruppe",
                        },
                        "speakers": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Liste von media_player Entity-IDs (fuer create_group/modify_group)",
                        },
                        "add_speakers": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Speaker zur Gruppe hinzufuegen (fuer modify_group)",
                        },
                        "remove_speakers": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Speaker aus Gruppe entfernen (fuer modify_group)",
                        },
                        "query": {
                            "type": "string",
                            "description": "Musik-Suchbegriff (fuer play)",
                        },
                        "volume": {
                            "type": "integer",
                            "description": "Lautstaerke 0-100 (fuer volume)",
                        },
                        "speaker": {
                            "type": "string",
                            "description": "Einzelner Speaker in der Gruppe (fuer volume)",
                        },
                        "description": {
                            "type": "string",
                            "description": "Beschreibung der Gruppe",
                        },
                    },
                    "required": ["action"],
                },
            },
        },
        # --- Phase 16.2: Was kann Jarvis? ---
        {
            "type": "function",
            "function": {
                "name": "list_capabilities",
                "description": "Zeigt was der Assistent alles kann. Nutze dies wenn der User fragt was du kannst.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        # --- Automationen (lesen + schreiben) ---
        {
            "type": "function",
            "function": {
                "name": "list_ha_automations",
                "description": "Zeigt alle Home Assistant Automationen mit Triggern, Bedingungen und Aktionen an. Nutze dies wenn der User fragt: 'Welche Automationen habe ich?', 'Was macht die Automation XY?', 'Zeig mir meine Automationen'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filter": {
                            "type": "string",
                            "description": "Optionaler Suchbegriff zum Filtern nach Name/Alias (z.B. 'licht', 'heizung')",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_automation",
                "description": "Erstellt eine neue Home Assistant Automation aus natürlicher Sprache. Der User beschreibt was passieren soll, Jarvis generiert die Automation und fragt nach Bestaetigung.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "description": {
                            "type": "string",
                            "description": "Natürlichsprachliche Beschreibung der Automation (z.B. 'Wenn ich nach Hause komme, mach das Licht an')",
                        },
                    },
                    "required": ["description"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "confirm_automation",
                "description": "Bestaetigt eine vorgeschlagene Automation und aktiviert sie in Home Assistant.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pending_id": {
                            "type": "string",
                            "description": "ID der ausstehenden Automation (wird bei create_automation zurückgegeben)",
                        },
                    },
                    "required": ["pending_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_jarvis_automations",
                "description": "Zeigt alle von Jarvis erstellten Automationen an.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delete_jarvis_automation",
                "description": "Loescht eine von Jarvis erstellte Automation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "automation_id": {
                            "type": "string",
                            "description": "ID der Automation (z.B. jarvis_abc12345_20260218)",
                        },
                    },
                    "required": ["automation_id"],
                },
            },
        },
        # --- Neue Features: Timer, Broadcast, Kamera, Conditionals, Energie, Web-Suche ---
        {
            "type": "function",
            "function": {
                "name": "set_timer",
                "description": "Setzt einen allgemeinen Timer/Erinnerung. Z.B. 'Erinnere mich in 30 Minuten an die Wäsche' oder 'In 20 Minuten Licht aus'. WICHTIG: duration_minutes ist IMMER in Minuten, NIEMALS in Sekunden. '30 Sekunden' = 1 Minute (aufrunden), '5 Minuten' = 5.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "duration_minutes": {
                            "type": "integer",
                            "description": "Dauer in MINUTEN (1-1440). NICHT Sekunden! Wenn der User Sekunden sagt, in Minuten umrechnen (aufrunden). '30 Sekunden' → 1, '2 Minuten' → 2, '1 Stunde' → 60",
                        },
                        "label": {
                            "type": "string",
                            "description": "Bezeichnung des Timers (z.B. 'Wäsche', 'Pizza', 'Anruf')",
                        },
                        "room": {
                            "type": "string",
                            "description": "Raum in dem die Timer-Benachrichtigung erfolgen soll",
                        },
                        "action_on_expire": {
                            "type": "object",
                            "description": 'Optionale Aktion bei Ablauf. Format: {"function": "set_light", "args": {"room": "kueche", "state": "off"}}',
                        },
                    },
                    "required": ["duration_minutes", "label"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "cancel_timer",
                "description": "Bricht einen laufenden Timer ab.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": "Bezeichnung des Timers zum Abbrechen (z.B. 'Wäsche')",
                        },
                    },
                    "required": ["label"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_timer_status",
                "description": "Zeigt den Status aller aktiven Timer an. 'Wie lange noch?' oder 'Welche Timer laufen?'",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        # Phase 5A: Zeitgesteuerte Geraeteaktionen
        {
            "type": "function",
            "function": {
                "name": "schedule_action",
                "description": "Plant eine Geraete-Aktion fuer eine bestimmte Uhrzeit. Z.B. 'Schalte Licht um 19 Uhr ein', 'Jeden Morgen um 6:30 Kaffeemaschine an', 'Rolllaeden um 7 Uhr hoch'. NICHT fuer Erinnerungen — nur fuer Geraete-Aktionen!",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "Aktion: set_light, set_climate, set_cover, play_media, pause_media, stop_media, set_volume",
                            "enum": [
                                "set_light",
                                "set_climate",
                                "set_cover",
                                "play_media",
                                "pause_media",
                                "stop_media",
                                "set_volume",
                            ],
                        },
                        "action_args": {
                            "type": "object",
                            "description": 'Argumente fuer die Aktion (wie beim direkten Aufruf). Z.B. {"room": "kueche", "state": "on"} oder {"room": "wohnzimmer", "temperature": 22}',
                        },
                        "target_time": {
                            "type": "string",
                            "description": "Uhrzeit im Format HH:MM (z.B. '19:00', '06:30')",
                        },
                        "target_date": {
                            "type": "string",
                            "description": "Optionales Datum YYYY-MM-DD. Leer = heute.",
                        },
                        "repeat": {
                            "type": "string",
                            "description": "Wiederholung: once (einmalig), daily (taeglich), weekdays (Mo-Fr), weekends (Sa-So), weekly (woechentlich)",
                            "enum": ["once", "daily", "weekdays", "weekends", "weekly"],
                        },
                    },
                    "required": ["action", "action_args", "target_time"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_scheduled_actions",
                "description": "Zeigt alle geplanten Geraete-Aktionen an. 'Was ist geplant?' oder 'Welche Aktionen sind zeitgesteuert?'",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "cancel_scheduled_action",
                "description": "Storniert eine geplante Geraete-Aktion.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action_id": {
                            "type": "string",
                            "description": "ID der geplanten Aktion (aus list_scheduled_actions)",
                        },
                    },
                    "required": ["action_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "set_reminder",
                "description": "Setzt eine Erinnerung für eine bestimmte Uhrzeit. Z.B. 'Erinnere mich um 15 Uhr an den Anruf' oder 'Um 18:30 Abendessen kochen'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "time": {
                            "type": "string",
                            "description": "Uhrzeit im Format HH:MM (z.B. '15:00', '06:30')",
                        },
                        "label": {
                            "type": "string",
                            "description": "Woran erinnert werden soll (z.B. 'Anruf bei Mama', 'Medikamente nehmen')",
                        },
                        "date": {
                            "type": "string",
                            "description": "Datum im Format YYYY-MM-DD. Wenn leer, wird heute oder morgen automatisch gewählt.",
                        },
                        "room": {
                            "type": "string",
                            "description": "Raum für die TTS-Benachrichtigung",
                        },
                    },
                    "required": ["time", "label"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "set_wakeup_alarm",
                "description": "Stellt einen Wecker für eine bestimmte Uhrzeit. Z.B. 'Weck mich um 6:30' oder 'Stell einen Wecker für 7 Uhr'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "time": {
                            "type": "string",
                            "description": "Weckzeit im Format HH:MM (z.B. '06:30', '07:00')",
                        },
                        "label": {
                            "type": "string",
                            "description": "Bezeichnung des Weckers (Standard: 'Wecker')",
                        },
                        "room": {
                            "type": "string",
                            "description": "Raum in dem geweckt werden soll (für Licht + TTS)",
                        },
                        "repeat": {
                            "type": "string",
                            "enum": ["", "daily", "weekdays", "weekends"],
                            "description": "Wiederholung: leer=einmalig, 'daily'=taeglich, 'weekdays'=Mo-Fr, 'weekends'=Sa-So",
                        },
                    },
                    "required": ["time"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "cancel_alarm",
                "description": "Loescht einen Wecker. Z.B. 'Loesch den Wecker' oder 'Wecker aus'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": "Bezeichnung des Weckers zum Löschen",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_alarms",
                "description": "Zeigt alle aktiven Wecker an. 'Welche Wecker habe ich?' oder 'Wecker Status'.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "broadcast",
                "description": "Sendet eine Durchsage an ALLE Lautsprecher im Haus. Für Ankuendigungen wie 'Essen ist fertig!' oder 'Bitte alle runterkommen.'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Die Durchsage-Nachricht",
                        },
                    },
                    "required": ["message"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "send_intercom",
                "description": "Gezielte Durchsage an eine bestimmte Person oder einen bestimmten Raum. Für 'Sag Julia dass das Essen fertig ist' oder 'Durchsage im Wohnzimmer: Komm mal bitte'. Für Durchsagen an ALLE verwende stattdessen 'broadcast'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Die Durchsage-Nachricht",
                        },
                        "target_room": {
                            "type": "string",
                            "description": "Zielraum (z.B. 'Wohnzimmer', 'Schlafzimmer', 'Kueche')",
                        },
                        "target_person": {
                            "type": "string",
                            "description": "Zielperson (z.B. 'Julia', 'Manuel'). Der Raum wird automatisch ermittelt.",
                        },
                    },
                    "required": ["message"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_camera_view",
                "description": "Holt und beschreibt ein Kamera-Bild. Z.B. 'Wer ist an der Tür?' oder 'Zeig mir die Garage'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "camera_name": {
                            "type": "string",
                            "description": "Name oder Raum der Kamera (z.B. 'haustuer', 'garage', 'garten')",
                        },
                    },
                    "required": ["camera_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_conditional",
                "description": "Erstellt einen temporaeren bedingten Befehl: 'Wenn X passiert, dann Y'. Z.B. 'Wenn es regnet, Rolladen runter' oder 'Wenn Papa ankommt, sag ihm Bescheid'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "trigger_type": {
                            "type": "string",
                            "enum": [
                                "state_change",
                                "person_arrives",
                                "person_leaves",
                                "state_attribute",
                            ],
                            "description": "Art des Triggers",
                        },
                        "trigger_value": {
                            "type": "string",
                            "description": "Trigger-Wert. Bei state_change: 'entity_id:state' (z.B. 'sensor.regen:on'). Bei person_arrives/leaves: Name (z.B. 'papa'). Bei state_attribute: 'entity_id|attribut|operator|wert' (pipe-getrennt, z.B. 'sensor.aussen|temperature|>|25')",
                        },
                        "action_function": {
                            "type": "string",
                            "description": "Auszufuehrende Funktion (z.B. 'set_cover', 'send_notification', 'set_light')",
                        },
                        "action_args": {
                            "type": "object",
                            "description": "Argumente für die Aktion",
                        },
                        "label": {
                            "type": "string",
                            "description": "Beschreibung (z.B. 'Rolladen bei Regen runter')",
                        },
                        "ttl_hours": {
                            "type": "integer",
                            "description": "Gültigkeitsdauer in Stunden (default 24, max 168)",
                        },
                        "one_shot": {
                            "type": "boolean",
                            "description": "Nur einmal ausführen (default true)",
                        },
                    },
                    "required": [
                        "trigger_type",
                        "trigger_value",
                        "action_function",
                        "action_args",
                    ],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_conditionals",
                "description": "Zeigt alle aktiven bedingten Befehle (Wenn-Dann-Regeln) an.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_energy_report",
                "description": "Zeigt einen Energie-Bericht mit Strompreis, Solar-Ertrag, Verbrauch und Empfehlungen.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Sucht im Internet nach Informationen. Nur für Wissensfragen die nicht aus dem Gedaechtnis beantwortet werden koennen. Z.B. 'Was ist die Hauptstadt von Australien?' oder 'Aktuelle Nachrichten'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Die Suchanfrage",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_security_score",
                "description": "Zeigt den aktuellen Sicherheits-Score des Hauses (0-100). Prueft offene Türen, Fenster, Schlösser, Rauchmelder und Wassersensoren. Nutze dies wenn der User nach Sicherheit, Haus-Status oder offenen Türen/Fenstern fragt.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_room_climate",
                "description": "Zeigt Raumklima-Daten: CO2, Luftfeuchtigkeit, Temperatur und Gesundheitsbewertung. Nutze dies wenn der User nach Raumklima, Luftqualitaet oder Raumgesundheit fragt.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_active_intents",
                "description": "Zeigt gemerkte Vorhaben die aus früheren Gespraechen erkannt wurden, z.B. 'Eltern kommen am Wochenende'. Nutze dies NUR wenn der User explizit nach gemerkten Vorhaben fragt, z.B. 'Was habe ich mir vorgenommen?', 'Was hast du dir gemerkt?'. NICHT für Kalender-Termine oder 'Was steht morgen an?' verwenden.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_wellness_status",
                "description": "Zeigt den Wellness-Status des Users: PC-Nutzungsdauer, Stress-Level, letzte Mahlzeit, Hydration. Nutze dies wenn der User fragt wie es ihm geht, ob er eine Pause braucht oder nach seinem Wohlbefinden fragt.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_device_health",
                "description": "Zeigt den Geräte-Gesundheitsstatus: Anomalien, inaktive Sensoren, HVAC-Effizienz. Nutze dies wenn der User nach Hardware-Problemen, Geräte-Status oder Sensor-Zustand fragt.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_house_status",
                "description": "Gibt den kompletten Haus-Status zurück: Temperaturen, Lichter, Anwesenheit, Wetter, Sicherheit, offene Fenster/Türen, Medien, offline Geräte. IMMER nutzen wenn der User nach Hausstatus, Status, Überblick oder Zusammenfassung fragt.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_full_status_report",
                "description": "Narrativer JARVIS-Statusbericht: Hausstatus, Termine, Wetter, Energie, offene Erinnerungen — alles in einem kurzen Briefing. Für 'Statusbericht', 'Briefing', 'Was gibts Neues', 'Lagebericht'.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Aktuelles Wetter von Home Assistant abrufen. Nutze dies wenn der User nach Wetter, Temperatur draußen, Regen oder Wind fragt. Standardmaessig nur aktuelles Wetter, Vorhersage nur wenn explizit gewuenscht.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "include_forecast": {
                            "type": "boolean",
                            "description": "Nur auf true setzen wenn der User EXPLIZIT nach Vorhersage, morgen, später oder den kommenden Tagen fragt (default: false)",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_learned_patterns",
                "description": "Zeigt erkannte Verhaltensmuster: Welche manuellen Aktionen der User regelmaessig wiederholt. Z.B. 'Jeden Abend Licht aus um 22:30'. Nutze dies wenn der User fragt was Jarvis gelernt hat oder welche Muster erkannt wurden.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "describe_doorbell",
                "description": "Beschreibt wer oder was gerade vor der Haustuer steht (via Türkamera). Nutze dies wenn der User fragt 'Wer ist an der Tür?', 'Wer hat geklingelt?' oder 'Was ist vor der Tür?'.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "manage_visitor",
                "description": "Besucher-Management: Bekannte Besucher verwalten, erwartete Besucher anlegen, Besucher-History ansehen, Tür oeffnen ('Lass ihn rein'). Nutze dies bei: 'Mama kommt heute', 'Lass ihn rein', 'Wer hat uns besucht?', 'Besucher hinzufuegen', 'Oeffne die Tür für den Besuch'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "add_known",
                                "remove_known",
                                "list_known",
                                "expect",
                                "cancel_expected",
                                "grant_entry",
                                "history",
                                "status",
                            ],
                            "description": "Aktion: add_known=Besucher speichern, remove_known=entfernen, list_known=alle zeigen, expect=Besucher erwarten, cancel_expected=Erwartung aufheben, grant_entry=Tür oeffnen, history=Besuchs-History, status=Übersicht",
                        },
                        "person_id": {
                            "type": "string",
                            "description": "Eindeutige ID des Besuchers (z.B. 'mama', 'handwerker_mueller')",
                        },
                        "name": {
                            "type": "string",
                            "description": "Anzeigename des Besuchers",
                        },
                        "relationship": {
                            "type": "string",
                            "description": "Beziehung: Familie, Freund, Handwerker, Nachbar, etc.",
                        },
                        "notes": {
                            "type": "string",
                            "description": "Zusaetzliche Notizen zum Besucher",
                        },
                        "expected_time": {
                            "type": "string",
                            "description": "Erwartete Ankunftszeit (z.B. '15:00', 'nachmittags')",
                        },
                        "auto_unlock": {
                            "type": "boolean",
                            "description": "Tür automatisch oeffnen wenn Besucher klingelt (nur bei expect)",
                        },
                        "door": {
                            "type": "string",
                            "description": "Tür-Name für grant_entry (default: haustuer)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximale Anzahl History-Eintraege (default: 20)",
                        },
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "manage_protocol",
                "description": "Verwaltet benannte Protokolle (Multi-Step-Sequenzen). Protokolle sind gespeicherte Ablaeufe wie 'Filmabend' oder 'Gute Nacht'. Nutze dies wenn der User ein Protokoll erstellen, ausführen, auflisten, löschen oder rueckgaengig machen will. Beispiel: 'Erstelle Protokoll Filmabend: Licht 20%, Rolladen zu' oder 'Fuehre Filmabend aus' oder 'Zeig meine Protokolle'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["create", "execute", "undo", "list", "delete"],
                            "description": "Aktion: create (erstellen), execute (ausführen), undo (rueckgaengig), list (auflisten), delete (löschen)",
                        },
                        "name": {
                            "type": "string",
                            "description": "Name des Protokolls (z.B. 'Filmabend', 'Party', 'Morgenroutine')",
                        },
                        "description": {
                            "type": "string",
                            "description": "Nur bei action=create: Natürliche Beschreibung der Schritte (z.B. 'Licht auf 20%, Rolladen zu, TV an')",
                        },
                    },
                    "required": ["action"],
                },
            },
        },
        # ── Phase 11: Saugroboter (Dreame, 2 Etagen) ──────────
        {
            "type": "function",
            "function": {
                "name": "set_vacuum",
                "description": "Saugroboter steuern. Raum angeben → richtiger Roboter (EG/OG) wird automatisch gewählt. Ohne Raum → ganzes Stockwerk oder alle. Saugstaerke und Modus einstellbar.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["start", "stop", "pause", "dock", "clean_room"],
                            "description": "start=ganzes Stockwerk saugen, clean_room=bestimmten Raum saugen, stop=anhalten, pause=pausieren, dock=zur Ladestation",
                        },
                        "room": {
                            "type": "string",
                            "description": "Raumname für gezieltes Saugen (z.B. 'wohnzimmer', 'kueche'). Oder 'eg'/'og' für ganzes Stockwerk. Ohne → beide Roboter.",
                        },
                        "fan_speed": {
                            "type": "string",
                            "enum": ["quiet", "standard", "strong", "turbo"],
                            "description": "Saugstaerke: quiet=leise, standard=normal, strong=stark, turbo=maximal. User sagt 'leise saugen' → quiet, 'volle Power' → turbo.",
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["vacuum", "mop", "vacuum_and_mop"],
                            "description": "Reinigungsmodus: vacuum=nur saugen, mop=nur wischen, vacuum_and_mop=saugen+wischen. Default: vacuum.",
                        },
                        "repeat": {
                            "type": "integer",
                            "description": "Wie oft der Raum gereinigt werden soll (1-3). Default 1. User sagt '2x saugen' → 2.",
                        },
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_vacuum",
                "description": "Status aller Saugroboter abfragen: Akku, Status, letzter Lauf, Wartungszustand, Reinigungsverlauf.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        # --- Workshop-Modus: Reparatur & Werkstatt ---
        {
            "type": "function",
            "function": {
                "name": "manage_repair",
                "description": (
                    "Werkstatt-Assistent: Projekte verwalten, Diagnose, Code/3D/Schaltplan generieren, "
                    "Berechnungen, Simulation, 3D-Drucker, Roboterarm, Inventar, Journal. "
                    "Nutze dieses Tool wenn der User etwas reparieren, bauen, basteln, konstruieren, "
                    "programmieren, loeten, 3d-drucken, oder simulieren will."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "create_project",
                                "list_projects",
                                "get_project",
                                "update_project",
                                "complete_project",
                                "add_note",
                                "add_part",
                                "diagnose",
                                "generate_code",
                                "generate_3d",
                                "generate_schematic",
                                "generate_website",
                                "generate_bom",
                                "generate_docs",
                                "generate_tests",
                                "calculate",
                                "simulate",
                                "troubleshoot",
                                "suggest_improvements",
                                "compare_components",
                                "scan_object",
                                "search_library",
                                "add_workshop_item",
                                "list_workshop",
                                "set_budget",
                                "add_expense",
                                "printer_status",
                                "start_print",
                                "pause_print",
                                "cancel_print",
                                "arm_move",
                                "arm_gripper",
                                "arm_home",
                                "arm_pick_tool",
                                "start_timer",
                                "pause_timer",
                                "journal_add",
                                "journal_get",
                                "save_snippet",
                                "get_snippet",
                                "safety_checklist",
                                "calibration_guide",
                                "analyze_error_log",
                                "evaluate_measurement",
                                "lend_tool",
                                "return_tool",
                                "list_lent",
                                "create_from_template",
                                "get_stats",
                                "switch_project",
                                "export_project",
                                "check_device",
                                "link_device",
                                "get_power",
                            ],
                            "description": "Die auszufuehrende Werkstatt-Aktion",
                        },
                        "project_id": {
                            "type": "string",
                            "description": "Projekt-ID (8-stellig, z.B. 'a1b2c3d4'). Wird bei den meisten Aktionen benötigt.",
                        },
                        "title": {
                            "type": "string",
                            "description": "Projekt-Titel (für create_project)",
                        },
                        "description": {
                            "type": "string",
                            "description": "Beschreibung/Anforderung/Symptom",
                        },
                        "category": {
                            "type": "string",
                            "enum": [
                                "reparatur",
                                "bau",
                                "maker",
                                "erfindung",
                                "renovierung",
                            ],
                            "description": "Projekt-Kategorie",
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["niedrig", "normal", "hoch", "dringend"],
                            "description": "Projekt-Prioritaet",
                        },
                        "status": {
                            "type": "string",
                            "enum": [
                                "erstellt",
                                "diagnose",
                                "teile_bestellt",
                                "in_arbeit",
                                "pausiert",
                                "fertig",
                            ],
                            "description": "Neuer Projekt-Status (für update_project)",
                        },
                        "language": {
                            "type": "string",
                            "enum": [
                                "arduino",
                                "python",
                                "cpp",
                                "html",
                                "javascript",
                                "yaml",
                                "micropython",
                            ],
                            "description": "Programmiersprache für Code-Generation",
                        },
                        "calc_type": {
                            "type": "string",
                            "enum": [
                                "resistor_divider",
                                "led_resistor",
                                "wire_gauge",
                                "ohms_law",
                                "3d_print_weight",
                                "screw_torque",
                                "convert",
                                "power_supply",
                            ],
                            "description": "Berechnungstyp",
                        },
                        "calc_params": {
                            "type": "object",
                            "description": 'Parameter für die Berechnung (z.B. {"v_in": 12, "v_out": 3.3})',
                        },
                        "item": {
                            "type": "string",
                            "description": "Artikelname / Werkzeugname",
                        },
                        "quantity": {"type": "integer", "description": "Menge"},
                        "cost": {"type": "number", "description": "Kosten in Euro"},
                        "person": {
                            "type": "string",
                            "description": "Personenname (für Verleih, Skills)",
                        },
                        "text": {
                            "type": "string",
                            "description": "Freitext (Messwert, Log, Notiz, etc.)",
                        },
                        "filename": {
                            "type": "string",
                            "description": "Dateiname für File-Operationen",
                        },
                        "minutes": {
                            "type": "integer",
                            "description": "Timer-Dauer in Minuten",
                        },
                        "template": {"type": "string", "description": "Template-Name"},
                        "entity_id": {"type": "string", "description": "HA Entity-ID"},
                        "x": {"type": "number", "description": "Arm X-Position"},
                        "y": {"type": "number", "description": "Arm Y-Position"},
                        "z": {"type": "number", "description": "Arm Z-Position"},
                        "budget": {"type": "number", "description": "Budget in Euro"},
                        "component_a": {
                            "type": "string",
                            "description": "Erste Komponente (Vergleich)",
                        },
                        "component_b": {
                            "type": "string",
                            "description": "Zweite Komponente (Vergleich)",
                        },
                        "query": {
                            "type": "string",
                            "description": "Suchbegriff (Library/Projekte)",
                        },
                        "camera": {
                            "type": "string",
                            "description": "Kamera-Name fuer scan_object (z.B. 'werkstatt', 'haustuer')",
                        },
                    },
                    "required": ["action"],
                },
            },
        },
        # ── Fernbedienung (Harmony etc.) ──────────────────────────
        {
            "type": "function",
            "function": {
                "name": "remote_control",
                "description": "Fernbedienung steuern (Logitech Harmony etc.). Kann Aktivitäten starten/stoppen und IR-Befehle senden. Beispiele: 'Schalte den Fernseher ein' → activity='Fernsehen', 'Stell auf ARD um' → command='InputHdmi1' oder device+command, 'Mach alles aus' → action='off'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "remote": {
                            "type": "string",
                            "description": "Name der Fernbedienung oder Raum (z.B. 'wohnzimmer', 'schlafzimmer'). Optional wenn nur eine Fernbedienung konfiguriert ist.",
                        },
                        "action": {
                            "type": "string",
                            "enum": ["on", "off", "activity", "command"],
                            "description": "on=einschalten (optional mit activity), off=alles ausschalten, activity=Aktivität wechseln, command=IR-Befehl senden.",
                        },
                        "activity": {
                            "type": "string",
                            "description": "Name der Harmony-Aktivität (z.B. 'Fernsehen', 'Watch TV', 'Musik hören', 'Netflix'). Nur bei action='on' oder 'activity'.",
                        },
                        "command": {
                            "type": "string",
                            "description": "IR-Befehl (z.B. 'VolumeUp', 'VolumeDown', 'Mute', 'ChannelUp', 'ChannelDown', 'Play', 'Pause', 'InputHdmi1'). Nur bei action='command'.",
                        },
                        "device": {
                            "type": "string",
                            "description": "Zielgerät für den IR-Befehl (z.B. 'Samsung TV', 'Yamaha Receiver'). Optional — ohne device wird der Befehl an die aktive Aktivität gesendet.",
                        },
                        "num_repeats": {
                            "type": "integer",
                            "description": "Befehl mehrfach senden (z.B. 5x VolumeUp). Standard: 1.",
                        },
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_remotes",
                "description": "Zeigt alle Fernbedienungen mit aktuellem Status, aktiver Aktivität und verfügbaren Aktivitäten/Geräten. Nutze dies wenn der User fragt was die Fernbedienung kann, welche Aktivitäten es gibt oder was gerade läuft.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "remote": {
                            "type": "string",
                            "description": "Name/Raum zum Filtern (optional)",
                        },
                    },
                    "required": [],
                },
            },
        },
        # ── Deklarative Tools (Phase 13.3) ────────────────────────
        {
            "type": "function",
            "function": {
                "name": "create_declarative_tool",
                "description": "Erstellt ein neues deklaratives Analyse-Tool. Deklarative Tools fuehren vordefinierte Berechnungen auf HA-Entities aus (NUR Lese-Zugriff). Verfügbare Typen: entity_comparison (Vergleich zweier Entities), multi_entity_formula (Kombination mehrerer Entities mit average/weighted_average/sum/min/max/difference), event_counter (zählt State-Änderungen), threshold_monitor (prueft ob Wert in Bereich), trend_analyzer (Trend über Zeitraum), entity_aggregator (Aggregation über mehrere Entities), schedule_checker (zeitbasierte Checks), state_duration (wie lange war ein Zustand aktiv, z.B. Heizung lief X Stunden), time_comparison (Vergleich einer Entity mit sich selbst über verschiedene Zeitraeume: yesterday/last_week/last_month).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Eindeutiger Name für das Tool (z.B. 'stromvergleich', 'raumtemperaturen'). Nur Buchstaben, Zahlen, _ und -.",
                        },
                        "description": {
                            "type": "string",
                            "description": "Kurze Beschreibung was das Tool tut.",
                        },
                        "type": {
                            "type": "string",
                            "enum": [
                                "entity_comparison",
                                "multi_entity_formula",
                                "event_counter",
                                "threshold_monitor",
                                "trend_analyzer",
                                "entity_aggregator",
                                "schedule_checker",
                                "state_duration",
                                "time_comparison",
                            ],
                            "description": "Typ des Tools.",
                        },
                        "config_json": {
                            "type": "string",
                            "description": 'Tool-Konfiguration als JSON-String. Beispiele: entity_comparison: {"entity_a": "sensor.strom_heute", "entity_b": "sensor.strom_gestern", "operation": "difference"}. entity_aggregator: {"entities": ["sensor.temp_wohn", "sensor.temp_schlaf"], "aggregation": "average"}. threshold_monitor: {"entity": "sensor.luftfeuchtigkeit", "thresholds": {"min": 40, "max": 60}}. trend_analyzer: {"entity": "sensor.temperatur", "time_range": "24h"}. event_counter: {"entities": ["binary_sensor.tuer"], "count_state": "on", "time_range": "24h"}. state_duration: {"entity": "climate.wohnzimmer", "target_state": "heating", "time_range": "24h"}. time_comparison: {"entity": "sensor.strom", "compare_period": "yesterday", "aggregation": "average"}.',
                        },
                    },
                    "required": ["name", "description", "type", "config_json"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_declarative_tools",
                "description": "Listet alle benutzerdefinierten deklarativen Analyse-Tools auf.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delete_declarative_tool",
                "description": "Loescht ein deklaratives Analyse-Tool.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name des Tools das gelöscht werden soll.",
                        },
                    },
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_declarative_tool",
                "description": "Fuehrt ein deklaratives Analyse-Tool aus und gibt das Ergebnis zurück. Nutze list_declarative_tools um verfügbare Tools zu sehen.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name des auszufuehrenden Tools.",
                        },
                    },
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "suggest_declarative_tools",
                "description": "Analysiert alle Home-Assistant-Entities und schlaegt passende Analyse-Tools vor die dem User helfen koennten. Gibt Vorschlaege zurück mit Name, Beschreibung, Typ, Config und Begruendung. Der User muss jeden Vorschlag bestätigen bevor er erstellt wird. Nutze diese Funktion wenn der User fragt welche Tools sinnvoll wären oder wenn du proaktiv Vorschlaege machen willst.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        # C6: Semantic History Search — Durchsucht vergangene Gespraeche
        {
            "type": "function",
            "function": {
                "name": "search_history",
                "description": "Durchsucht die Gespraechs-Historie nach vergangenen Interaktionen. Nutze dieses Tool wenn der User fragt 'Was habe ich gestern gesagt?', 'Wann haben wir ueber X geredet?', 'Was war das mit dem Licht letzte Woche?' oder aehnliche Fragen zur Vergangenheit.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Suchbegriff oder Thema das in der Historie gesucht werden soll.",
                        },
                        "days_back": {
                            "type": "integer",
                            "description": "Wie viele Tage zurueck suchen (Standard: 7, Max: 30).",
                        },
                        "person": {
                            "type": "string",
                            "description": "Optional: Nur Gespraeche dieser Person durchsuchen.",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        # C9: Automation-Debugging — Analysiert HA-Automatisierungen
        {
            "type": "function",
            "function": {
                "name": "debug_automation",
                "description": "Analysiert Home-Assistant-Automatisierungen und deren letzte Ausfuehrungen. Nutze dieses Tool wenn der User fragt warum eine Automatisierung nicht funktioniert hat, wann sie zuletzt gelaufen ist, oder welche Automatisierungen aktiv sind. Gibt Trigger, Bedingungen, Aktionen und letzte Ausfuehrungszeiten zurueck.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "automation_name": {
                            "type": "string",
                            "description": "Name oder Teil des Namens der Automatisierung. Leer lassen fuer eine Uebersicht aller Automatisierungen.",
                        },
                        "show_trace": {
                            "type": "boolean",
                            "description": "Wenn true, wird der letzte Ausfuehrungs-Trace angezeigt (detailliert).",
                        },
                    },
                    "required": [],
                },
            },
        },
        # Phase 1.5: Memory-Augmented Reasoning — LLM kann aktiv Fakten abrufen
        {
            "type": "function",
            "function": {
                "name": "retrieve_memory",
                "description": "Durchsucht das Langzeitgedaechtnis nach gespeicherten Fakten ueber Personen, Vorlieben, Gewohnheiten oder fruehere Gespraeche. Nutze dieses Tool wenn dir Kontext fehlt, z.B. bei 'Wie mag Max sein Licht?', 'Was ist Julias Lieblingstemperatur?' oder wenn du unsicher bist ob ein Fakt bekannt ist.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Suchbegriff oder Frage an das Gedaechtnis.",
                        },
                        "person": {
                            "type": "string",
                            "description": "Optional: Nur Fakten dieser Person suchen.",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "retrieve_history",
                "description": "Ruft die letzten Aktionen und Gespraeche ab. Nutze dieses Tool wenn du wissen musst was zuletzt passiert ist, z.B. 'Was habe ich gerade gemacht?', 'Welche Geraete wurden zuletzt gesteuert?' oder um Kontext fuer Folgefragen zu bekommen.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Anzahl der letzten Eintraege (Standard: 5, Max: 20).",
                        },
                    },
                    "required": [],
                },
            },
        },
        # Phase 1.3: Verification Tool — LLM kann Geraetezustand nach Aktion pruefen
        {
            "type": "function",
            "function": {
                "name": "verify_device_state",
                "description": "Prueft den aktuellen Zustand eines Geraets nach einer Aktion. Nutze dieses Tool um zu verifizieren ob eine Aktion (Licht, Heizung, Rollladen etc.) tatsaechlich gewirkt hat. Gibt den aktuellen State und relevante Attribute zurueck.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entity_id": {
                            "type": "string",
                            "description": "Die HA Entity-ID des Geraets (z.B. light.wohnzimmer, climate.schlafzimmer).",
                        },
                        "expected_state": {
                            "type": "string",
                            "description": "Optional: Erwarteter Zustand (on/off/heat/cool etc.) zum Vergleich.",
                        },
                    },
                    "required": ["entity_id"],
                },
            },
        },
        # ==============================================================
        # Personal Assistant Tools
        # ==============================================================
        {
            "type": "function",
            "function": {
                "name": "manage_tasks",
                "description": "Aufgaben/Todo-Listen verwalten. Aufgaben hinzufuegen, auflisten, erledigen, entfernen. Auch wiederkehrende Aufgaben (taeglich, woechentlich, monatlich).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "add",
                                "list",
                                "complete",
                                "remove",
                                "add_recurring",
                                "list_recurring",
                                "delete_recurring",
                            ],
                            "description": "Aktion: hinzufuegen, auflisten, erledigen, entfernen, wiederkehrende erstellen/auflisten/loeschen",
                        },
                        "title": {
                            "type": "string",
                            "description": "Aufgabentext (fuer add, complete, remove, add_recurring, delete_recurring)",
                        },
                        "person": {
                            "type": "string",
                            "description": "Person der die Aufgabe zugewiesen wird (optional)",
                        },
                        "due_date": {
                            "type": "string",
                            "description": "Faelligkeitsdatum YYYY-MM-DD (optional)",
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["low", "medium", "high", "urgent"],
                            "description": "Prioritaet (default: medium)",
                        },
                        "recurrence": {
                            "type": "string",
                            "enum": ["daily", "weekly", "monthly", "weekday"],
                            "description": "Wiederholungstyp (fuer add_recurring)",
                        },
                        "weekday": {
                            "type": "string",
                            "description": "Wochentag fuer woechentliche Aufgaben (z.B. 'montag')",
                        },
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "manage_notes",
                "description": "Notizen erstellen, durchsuchen, auflisten und loeschen. Fuer schnelle Memos, Ideen, Informationen die man sich merken will.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["add", "list", "search", "delete", "categories"],
                            "description": "Aktion: hinzufuegen, auflisten, suchen, loeschen, Kategorien anzeigen",
                        },
                        "content": {
                            "type": "string",
                            "description": "Notiztext (fuer add) oder Suchbegriff (fuer search)",
                        },
                        "category": {
                            "type": "string",
                            "enum": [
                                "haushalt",
                                "arbeit",
                                "ideen",
                                "einkauf",
                                "gesundheit",
                                "technik",
                                "finanzen",
                                "familie",
                                "rezept",
                                "sonstiges",
                            ],
                            "description": "Kategorie (optional, default: sonstiges)",
                        },
                        "person": {
                            "type": "string",
                            "description": "Person der die Notiz zugeordnet wird (optional)",
                        },
                        "note_id": {
                            "type": "string",
                            "description": "Notiz-ID (fuer delete)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximale Anzahl Ergebnisse (default: 10)",
                        },
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "manage_family",
                "description": "Familien-Profile verwalten: Mitglieder hinzufuegen, auflisten, aktualisieren. Gruppen-Nachrichten senden.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "add_member",
                                "list_members",
                                "get_member",
                                "update_member",
                                "remove_member",
                                "send_family_message",
                                "create_group",
                            ],
                            "description": "Aktion auf der Familien-Verwaltung",
                        },
                        "name": {
                            "type": "string",
                            "description": "Name der Person",
                        },
                        "relationship": {
                            "type": "string",
                            "enum": [
                                "partner",
                                "spouse",
                                "child",
                                "parent",
                                "sibling",
                                "grandparent",
                                "grandchild",
                                "roommate",
                                "friend",
                                "other",
                            ],
                            "description": "Beziehungstyp (fuer add_member)",
                        },
                        "birth_year": {
                            "type": "integer",
                            "description": "Geburtsjahr (fuer add_member, optional)",
                        },
                        "interests": {
                            "type": "string",
                            "description": "Interessen/Hobbys kommagetrennt (optional)",
                        },
                        "message": {
                            "type": "string",
                            "description": "Nachricht (fuer send_family_message)",
                        },
                        "group": {
                            "type": "string",
                            "description": "Gruppenname (fuer send_family_message oder create_group, default: all)",
                        },
                        "members": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Mitglieder-Namen (fuer create_group)",
                        },
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_personal_dates",
                "description": "Anstehende Geburtstage, Jahrestage und persoenliche Termine abfragen.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "days_ahead": {
                            "type": "integer",
                            "description": "Wie viele Tage vorausschauen (default: 30)",
                        },
                        "person": {
                            "type": "string",
                            "description": "Termine nur fuer eine bestimmte Person (optional)",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "manage_meals",
                "description": "Essensplanung: Gerichte aus Vorraeten vorschlagen, Wochenplan erstellen, Mahlzeiten protokollieren, Zutaten pruefen.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "suggest",
                                "weekly_plan",
                                "log_meal",
                                "history",
                                "check_ingredients",
                                "current_plan",
                            ],
                            "description": "suggest: Was kochen mit Vorraeten. weekly_plan: Wochenplan erstellen. log_meal: Mahlzeit protokollieren. history: Essenshistorie. check_ingredients: Fehlende Zutaten zur Einkaufsliste. current_plan: Aktuellen Wochenplan anzeigen.",
                        },
                        "meal": {
                            "type": "string",
                            "description": "Gerichtsname (fuer log_meal)",
                        },
                        "meal_type": {
                            "type": "string",
                            "enum": [
                                "fruehstueck",
                                "mittagessen",
                                "abendessen",
                                "snack",
                            ],
                            "description": "Mahlzeitentyp (default: abendessen)",
                        },
                        "portions": {
                            "type": "integer",
                            "description": "Anzahl Portionen (optional)",
                        },
                        "rating": {
                            "type": "integer",
                            "description": "Bewertung 1-5 (fuer log_meal, optional)",
                        },
                        "preferences": {
                            "type": "string",
                            "description": "Wuensche fuer den Wochenplan (z.B. 'viel Gemuese', 'keine Pasta')",
                        },
                        "ingredients": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Zutatenliste (fuer check_ingredients)",
                        },
                        "days": {
                            "type": "integer",
                            "description": "Anzahl Tage fuer History (default: 7)",
                        },
                    },
                    "required": ["action"],
                },
            },
        },
    ]
    return _ASSISTANT_TOOLS_STATIC


_tools_cache: list | None = None
_tools_cache_ts: float = 0
_TOOLS_CACHE_TTL: int = 60  # Sekunden (entity_catalog hat 5min TTL, 60s ist sicher)
_tools_cache_lock = __import__("threading").Lock()


def get_assistant_tools() -> list:
    """Liefert Tool-Definitionen mit aktuellem Climate-Schema und Entity-Katalog.

    Ergebnis wird fuer 60 Sekunden gecacht — entity_catalog hat 5min TTL,
    also ist 60s sicher. Spart ~5-30ms pro Request durch Vermeidung von
    Climate-Tool-Rebuild und Entity-Hint-Injection.
    """
    global _tools_cache, _tools_cache_ts
    if _tools_cache is not None and (time.time() - _tools_cache_ts) < _TOOLS_CACHE_TTL:
        return _tools_cache

    with _tools_cache_lock:
        # Double-check after acquiring lock
        if (
            _tools_cache is not None
            and (time.time() - _tools_cache_ts) < _TOOLS_CACHE_TTL
        ):
            return _tools_cache

        tools = []
        for tool in _get_assistant_tools_static():
            fname = tool.get("function", {}).get("name", "")
            if fname == "set_climate":
                t = {
                    "type": "function",
                    "function": {
                        "name": "set_climate",
                        "description": _get_climate_tool_description(),
                        "parameters": _get_climate_tool_parameters(),
                    },
                }
                tools.append(_inject_entity_hints(t))
            elif fname == "activate_scene":
                tools.append(_inject_entity_hints(_build_activate_scene_tool(tool)))
            else:
                tools.append(_inject_entity_hints(tool))

        _tools_cache = tools
        _tools_cache_ts = time.time()
    return tools


def _build_activate_scene_tool(base_tool: dict) -> dict:
    """Baut activate_scene Tool mit Trigger-Map aus Settings."""
    tool = copy.deepcopy(base_tool)
    trigger_map = yaml_config.get("scenes", {}).get("trigger_map", {})
    if trigger_map:
        lines = []
        for scene_id, triggers in trigger_map.items():
            if triggers:
                lines.append(f"  '{scene_id}': {', '.join(triggers)}")
        if lines:
            mapping = "\n".join(lines)
            tool["function"]["description"] = (
                "Eine Szene aktivieren. WICHTIG: Verwende EXAKT die scene-ID aus dieser Zuordnung. "
                "Wenn der User einen der Ausloeser-Begriffe sagt, aktiviere die zugehoerige Szene:\n"
                + mapping
            )
    return tool


class FunctionExecutor:
    """Fuehrt Function Calls des Assistenten aus."""

    def __init__(self, ha_client: HomeAssistantClient):
        self.ha = ha_client
        self._entity_cache: dict[str, list[dict]] = {}
        self._config_versioning: Optional[ConfigVersioning] = None
        self._last_broadcast_time: float = 0.0

    def set_config_versioning(self, versioning: ConfigVersioning):
        """Setzt ConfigVersioning für Backup-vor-Schreiben."""
        self._config_versioning = versioning

    async def _mark_cover_jarvis_acting(self, entity_id: str):
        """Setzt jarvis_acting Flag UND manual_override fuer Voice-Befehle.

        jarvis_acting: Verhindert dass proactive.py den State-Change
        als externen Manual Override erkennt (z.B. von HA UI/Button).
        manual_override: Blockiert die automatische Cover-Steuerung
        (Solar, Zeitplan etc.) fuer die konfigurierte Override-Dauer.
        Beide Flags sind noetig weil Voice-Befehle vom User kommen
        (→ Automatik soll pausieren) aber ueber Jarvis ausgefuehrt
        werden (→ kein falscher Override-Alarm).
        """
        redis = getattr(self, "_redis", None)
        if redis:
            try:
                await redis.set(f"mha:cover:jarvis_acting:{entity_id}", "1", ex=300)
                # Voice-Befehl = User-Intention → Automatik pausieren
                from .config import yaml_config

                override_hours = (
                    yaml_config.get("seasonal_actions", {})
                    .get("cover_automation", {})
                    .get("manual_override_hours", 2)
                )
                override_ttl = int(override_hours * 3600)
                await redis.set(
                    f"mha:cover:manual_override:{entity_id}", "1", ex=override_ttl
                )
            except Exception as e:
                logger.debug("Redis Cover-Jarvis-Acting Flag fehlgeschlagen: %s", e)

    # Whitelist erlaubter Tool-Funktionsnamen (verhindert Zugriff auf interne Methoden)
    _ALLOWED_FUNCTIONS = frozenset(
        {
            "set_light",
            "set_light_all",
            "get_lights",
            "set_climate",
            "set_climate_curve",
            "set_climate_room",
            "activate_scene",
            "deactivate_scene",
            "set_cover",
            "set_cover_all",
            "get_covers",
            "get_media",
            "get_climate",
            "get_switches",
            "set_switch",
            "call_service",
            "play_media",
            "transfer_playback",
            "arm_security_system",
            "lock_door",
            "send_notification",
            "send_message_to_person",
            "play_sound",
            "get_entity_state",
            "get_entity_history",
            "get_calendar_events",
            "create_calendar_event",
            "delete_calendar_event",
            "reschedule_calendar_event",
            "set_presence_mode",
            "edit_config",
            "manage_shopping_list",
            "list_capabilities",
            "list_ha_automations",
            "create_automation",
            "confirm_automation",
            "list_jarvis_automations",
            "delete_jarvis_automation",
            "manage_inventory",
            "smart_shopping",
            "conversation_memory",
            "multi_room_audio",
            "set_timer",
            "cancel_timer",
            "get_timer_status",
            "schedule_action",
            "list_scheduled_actions",
            "cancel_scheduled_action",
            "set_location_trigger",
            "list_location_triggers",
            "cancel_location_trigger",
            "set_reminder",
            "set_wakeup_alarm",
            "cancel_alarm",
            "get_alarms",
            "broadcast",
            "send_intercom",
            "get_camera_view",
            "create_conditional",
            "list_conditionals",
            "get_energy_report",
            "web_search",
            "get_security_score",
            "get_room_climate",
            "get_active_intents",
            "get_wellness_status",
            "get_house_status",
            "get_full_status_report",
            "get_weather",
            "get_device_health",
            "get_learned_patterns",
            "describe_doorbell",
            "manage_protocol",
            "recommend_music",
            "manage_visitor",
            "set_vacuum",
            "get_vacuum",
            "manage_repair",
            "configure_cover_automation",
            "remote_control",
            "get_remotes",
            "create_declarative_tool",
            "list_declarative_tools",
            "delete_declarative_tool",
            "run_declarative_tool",
            "suggest_declarative_tools",
            "search_history",
            "debug_automation",
            "retrieve_memory",
            "retrieve_history",
            "verify_device_state",
            "manage_tasks",
            "manage_notes",
            "manage_family",
            "get_personal_dates",
            "manage_meals",
        }
    )

    # LLMs übersetzen deutsche Raumnamen manchmal ins Englische
    _EN_TO_DE_ROOMS: dict[str, str] = {
        "living_room": "wohnzimmer",
        "livingroom": "wohnzimmer",
        "living room": "wohnzimmer",
        "bedroom": "schlafzimmer",
        "kitchen": "kueche",
        "office": "buero",
        "bathroom": "bad",
        "bath": "bad",
        "hallway": "flur",
        "corridor": "flur",
        "hall": "flur",
        "garage": "garage",
        "balcony": "balkon",
        "terrace": "terrasse",
        "garden": "garten",
        "basement": "keller",
        "laundry": "waschkueche",
        "guest_room": "gaestezimmer",
        "guestroom": "gaestezimmer",
        "guest room": "gaestezimmer",
        "kids_room": "kinderzimmer",
        "kidsroom": "kinderzimmer",
        "kids room": "kinderzimmer",
        "dining_room": "esszimmer",
        "diningroom": "esszimmer",
        "dining room": "esszimmer",
    }

    # Gerätetyp-Woerter die LLMs manchmal in den Raumnamen packen
    _DEVICE_TYPE_WORDS = {
        # Deutsch
        "licht",
        "lampe",
        "leuchte",
        "beleuchtung",
        "rollladen",
        "rolladen",
        "jalousie",
        "rollo",
        "heizung",
        "thermostat",
        "klima",
        "klimaanlage",
        "steckdose",
        "schalter",
        "dose",
        "lautsprecher",
        "speaker",
        "media",
        "musik",
        "tuer",
        "schloss",
        "lock",
        "fenster",
        "sensor",
        # Englisch
        "light",
        "lights",
        "lamp",
        "blind",
        "blinds",
        "shutter",
        "cover",
        "switch",
        "plug",
        "outlet",
        "heater",
        "heating",
        "thermostat",
        "climate",
        "door",
        "window",
    }

    @classmethod
    def _clean_room(cls, room: str) -> str:
        """Bereinigt room-Parameter: Prefixe, Gerätetypen, EN->DE.

        LLMs schicken manchmal:
        - 'licht.buero' statt 'buero' (Domain-Prefix)
        - 'living_room' statt 'wohnzimmer' (englische Übersetzung)
        - 'schlafzimmer rollladen' statt 'schlafzimmer' (Gerätetyp im Raum)
        """
        if not room:
            return room

        # 1. Domain-Prefix strippen (z.B. "light.wohnzimmer" -> "wohnzimmer")
        for prefix in (
            "licht.",
            "light.",
            "schalter.",
            "switch.",
            "rollladen.",
            "rolladen.",
            "cover.",
            "steckdose.",
            "lampe.",
            "climate.",
            "media_player.",
            "lock.",
            "sensor.",
            "binary_sensor.",
        ):
            if room.lower().startswith(prefix):
                room = room[len(prefix) :]
                break

        # 2. Gerätetyp-Woerter entfernen (z.B. "schlafzimmer rollladen" -> "schlafzimmer")
        parts = room.replace("_", " ").split()
        if len(parts) > 1:
            cleaned = [p for p in parts if p.lower() not in cls._DEVICE_TYPE_WORDS]
            if cleaned:
                original = room
                room = " ".join(cleaned)
                if room != original:
                    logger.info(
                        "Room device-word cleanup: '%s' -> '%s'", original, room
                    )

        # 3. Englisch -> Deutsch Übersetzung
        room_lower = room.lower().strip()
        if room_lower in cls._EN_TO_DE_ROOMS:
            translated = cls._EN_TO_DE_ROOMS[room_lower]
            logger.info("Room EN->DE: '%s' -> '%s'", room, translated)
            return translated

        # 4. Fuzzy-Match gegen bekannte Raumnamen aus room_profiles
        # Korrigiert STT-Fehler wie "wohn zimer" → "wohnzimmer"
        room_profiles = yaml_config.get("room_profiles", {}).get("rooms", {})
        if room_profiles and room_lower not in {rn.lower() for rn in room_profiles}:
            # Normalisieren: Leerzeichen entfernen + Umlaut-Varianten
            room_collapsed = room_lower.replace(" ", "").replace("_", "")
            room_collapsed = (
                room_collapsed.replace("ae", "ä").replace("oe", "ö").replace("ue", "ü")
            )
            room_collapsed_noum = room_lower.replace(" ", "").replace("_", "")

            best_match = None
            best_dist = 999
            for known_room in room_profiles:
                known_lower = known_room.lower()
                # Exakter Match nach Collapse
                known_collapsed = known_lower.replace(" ", "").replace("_", "")
                if (
                    room_collapsed == known_collapsed
                    or room_collapsed_noum == known_collapsed
                ):
                    best_match = known_room
                    best_dist = 0
                    break
                # Levenshtein-Distanz (einfache Implementierung)
                dist = cls._levenshtein(room_collapsed_noum, known_collapsed)
                if dist < best_dist:
                    best_dist = dist
                    best_match = known_room

            # Threshold: Max 2 Edits bei kurzen Räumen, max 3 bei langen
            max_dist = 2 if len(room_collapsed_noum) <= 8 else 3
            if best_match and best_dist <= max_dist:
                logger.info(
                    "Fuzzy Room-Match: '%s' -> '%s' (dist=%d)",
                    room,
                    best_match,
                    best_dist,
                )
                return best_match

        return room

    @staticmethod
    def _levenshtein(s1: str, s2: str) -> int:
        """Berechnet Levenshtein-Distanz zwischen zwei Strings."""
        if len(s1) < len(s2):
            return FunctionExecutor._levenshtein(s2, s1)
        if len(s2) == 0:
            return len(s1)
        prev_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            curr_row = [i + 1]
            for j, c2 in enumerate(s2):
                # Einfuegen, Löschen, Ersetzen
                insertions = prev_row[j + 1] + 1
                deletions = curr_row[j] + 1
                substitutions = prev_row[j] + (c1 != c2)
                curr_row.append(min(insertions, deletions, substitutions))
            prev_row = curr_row
        return prev_row[-1]

    # Funktionen die nur Owner (Trust >= 2) ausfuehren darf
    _SECURITY_FUNCTIONS = frozenset(
        {
            "lock_door",
            "arm_security_system",
            "set_presence_mode",
        }
    )

    async def execute(self, function_name: str, arguments: dict) -> dict:
        """
        Fuehrt eine Funktion aus.

        Args:
            function_name: Name der Funktion
            arguments: Parameter als Dict

        Returns:
            Ergebnis-Dict mit success und message
        """
        if function_name not in self._ALLOWED_FUNCTIONS:
            return {
                "success": False,
                "message": f"Unbekannte Funktion: {function_name}",
            }
        handler = getattr(self, f"_exec_{function_name}", None)
        if not handler:
            return {
                "success": False,
                "message": f"Unbekannte Funktion: {function_name}",
            }

        # Trust-Enforcement: Pruefe ob aktuelle Person die Funktion ausfuehren darf
        try:
            import assistant.main as _main_mod
            from .request_context import get_current_person

            _brain = _main_mod.brain
            # Concurrent-safe: ContextVar statt Instance-Attribut (Per-Person Locks)
            _person = get_current_person() or getattr(_brain, "_current_person", "") or ""
            if _brain and hasattr(_brain, "autonomy"):
                trust_result = _brain.autonomy.can_person_act(
                    _person,
                    function_name,
                )
                if not trust_result.get("allowed", True):
                    _reason = trust_result.get("reason", "Keine Berechtigung.")
                    logger.warning(
                        "Trust-Check BLOCKIERT: %s darf '%s' nicht ausfuehren (%s)",
                        _person or "unknown",
                        function_name,
                        _reason,
                    )
                    return {"success": False, "message": _reason}
        except Exception as e:
            logger.error(
                "Trust-Check fehlgeschlagen (fail-closed): %s", e, exc_info=True
            )
            return {
                "success": False,
                "message": "Sicherheitspruefung fehlgeschlagen. Bitte erneut versuchen.",
            }

        try:
            # Phase 18: Pre-Execution Consequence Check
            consequence_hint = await self._check_consequences(function_name, arguments)

            # Zentralen ha_client Dependency-Check fuer diesen Call
            # ueberspringen — _check_consequences hat bereits geprueft
            # Counter statt Boolean: async-safe bei konkurrierenden execute()-Aufrufen
            self.ha._skip_dep_check_depth = (
                getattr(self.ha, "_skip_dep_check_depth", 0) + 1
            )
            try:
                result = await handler(arguments)
            finally:
                self.ha._skip_dep_check_depth = max(
                    0, getattr(self.ha, "_skip_dep_check_depth", 1) - 1
                )

            # Phase 18: Consequence-Hint an Ergebnis anfuegen
            # WICHTIG: Hint ist rein informativ — Aktion wurde BEREITS ausgefuehrt.
            # Das LLM soll den User beilaeufig informieren, aber die Aktion
            # NICHT rueckgaengig machen oder als Fehler darstellen.
            if consequence_hint and isinstance(result, dict) and result.get("success"):
                existing_msg = result.get("message", "")
                result["message"] = (
                    f"{existing_msg} (Info-Hinweis, Aktion wurde ausgefuehrt: {consequence_hint})"
                )
                result["consequence_hint"] = consequence_hint

            return result
        except Exception as e:
            # F-088: Exception-Details NICHT an LLM/User leaken
            logger.error("Fehler bei %s: %s", function_name, e, exc_info=True)
            return {
                "success": False,
                "message": "Suboptimal. Ich versuche einen anderen Weg.",
            }

    async def execute_parallel(self, calls: list[tuple[str, dict]]) -> list[dict]:
        """N4: Fuehrt mehrere Funktionen parallel aus.

        Args:
            calls: Liste von (function_name, arguments) Tuples

        Returns:
            Liste von Ergebnis-Dicts in gleicher Reihenfolge
        """
        if not calls:
            return []
        if len(calls) == 1:
            return [await self.execute(calls[0][0], calls[0][1])]
        results = await asyncio.gather(
            *(self.execute(name, args) for name, args in calls),
            return_exceptions=True,
        )
        return [
            r
            if isinstance(r, dict)
            else {"success": False, "message": "Paralleler Aufruf fehlgeschlagen"}
            for r in results
        ]

    # ── Phase 18: Pre-Execution Consequence Check ──────────────

    async def _check_consequences(self, func_name: str, args: dict) -> Optional[str]:
        """Prueft vor Ausfuehrung ob die Aktion im Kontext sinnvoll ist.

        Nutzt Entity-Annotation-Rollen fuer praezises Matching.
        Beruecksichtigt Raum-Zuordnung (same_room).
        Blockiert NICHT — gibt nur einen Hinweis-String zurueck.

        Returns:
            Hinweis-String oder None
        """
        from .config import yaml_config

        if not yaml_config.get("consequence_checks", {}).get("enabled", True):
            return None

        try:
            from .state_change_log import StateChangeLog

            hour = datetime.now(_LOCAL_TZ).hour
            states_raw = None  # Lazy-Load

            async def _get_states():
                nonlocal states_raw
                if states_raw is None:
                    states_raw = await self.ha.get_states() or []
                return states_raw

            def _role(entity_id: str) -> str:
                return StateChangeLog._get_entity_role(entity_id)

            def _room(entity_id: str) -> str:
                return StateChangeLog._get_entity_room(entity_id)

            def _entities_by_role(
                all_states: list, role: str, state_val: str = None
            ) -> list[dict]:
                """Findet alle Entities mit bestimmter Rolle (und optionalem State)."""
                result = []
                for s in all_states:
                    eid = s.get("entity_id", "")
                    if _role(eid) == role:
                        if state_val is None or s.get("state") == state_val:
                            result.append(s)
                return result

            def _friendly(s: dict) -> str:
                return s.get("attributes", {}).get(
                    "friendly_name", s.get("entity_id", "")
                )

            target_room = (args.get("room") or "").lower()

            # ── Regel: Heizung/Klima + Fenster offen (room-aware) ──
            if func_name in ("set_climate", "set_climate_room"):
                _states = await _get_states()
                open_windows = _entities_by_role(_states, "window_contact", "on")
                if target_room:
                    room_windows = [
                        s for s in open_windows if _room(s["entity_id"]) == target_room
                    ]
                    if room_windows:
                        names = ", ".join(_friendly(s) for s in room_windows[:2])
                        return f"Fenster {names} im {target_room.capitalize()} offen — Heizung wird ineffizient."
                elif open_windows:
                    names = ", ".join(_friendly(s) for s in open_windows[:2])
                    return f"Fenster {names} offen — Heizung wird ineffizient."

            # ── Regel: Heizung hoch bei extremer Kaelte draussen ──
            if func_name in ("set_climate", "set_climate_room"):
                temp_arg = args.get("temperature")
                if temp_arg is not None:
                    try:
                        target_temp = float(temp_arg)
                        if target_temp >= 24:
                            _states = await _get_states()
                            outdoor = _entities_by_role(_states, "outdoor_temperature")
                            for s in outdoor:
                                try:
                                    outside = float(s.get("state", 0))
                                    if outside <= -5:
                                        return (
                                            f"Bei {outside}\u00b0C Aussentemperatur wird die "
                                            f"Heizung auf {target_temp}\u00b0C Muehe haben."
                                        )
                                except (ValueError, TypeError):
                                    pass
                    except (ValueError, TypeError):
                        pass

            # ── Regel: Medien laut + spaet nachts ──
            if func_name == "play_media" and (hour >= 22 or hour < 6):
                return f"Es ist {hour} Uhr — Lautstaerke beachten."

            # ── Regel: Alarm scharf + Fenster/Tuer offen ──
            if func_name == "arm_security_system":
                _states = await _get_states()
                open_openings = _entities_by_role(
                    _states, "window_contact", "on"
                ) + _entities_by_role(_states, "door_contact", "on")
                if open_openings:
                    names = ", ".join(_friendly(s) for s in open_openings[:3])
                    return f"{names} noch offen — Alarm kann nicht sicher geschaltet werden."

            # ── Regel: Alle Lichter aus + jemand noch aktiv ──
            if func_name == "set_light_all":
                state = str(args.get("state", "")).lower()
                if state == "off" and 8 <= hour <= 23:
                    import assistant.main as main_module

                    if hasattr(main_module, "brain") and hasattr(
                        main_module.brain, "activity"
                    ):
                        activity = main_module.brain.activity.current_activity
                        if activity in ("focused", "working", "watching"):
                            return "Jemand scheint noch aktiv zu sein."

            # ── Regel: Licht aus + Bewegung im selben Raum ──
            if func_name == "set_light":
                state = str(args.get("state", "")).lower()
                if state == "off" and target_room:
                    _states = await _get_states()
                    motion_sensors = _entities_by_role(_states, "motion", "on")
                    for s in motion_sensors:
                        if _room(s["entity_id"]) == target_room:
                            return f"Im {target_room.capitalize()} wurde gerade Bewegung erkannt."

            # ── Regel: Rollladen oeffnen bei Sturm ──
            if func_name in ("set_cover", "set_cover_all"):
                position = args.get("position")
                action = str(args.get("action", "")).lower()
                if position is not None or action in ("open", "up"):
                    _states = await _get_states()
                    wind_sensors = _entities_by_role(_states, "wind_speed")
                    for s in wind_sensors:
                        try:
                            wind = float(s.get("state", 0))
                            if wind >= 60:
                                return f"Windgeschwindigkeit {wind} km/h — Rolllaeden besser geschlossen lassen."
                        except (ValueError, TypeError):
                            pass

            # ── Regel: Bewaesserung bei Regen ──
            if func_name in ("set_switch",):
                eid_arg = str(args.get("entity_id", "")).lower()
                if "irrigation" in eid_arg or "bewaesserung" in eid_arg:
                    _states = await _get_states()
                    rain_sensors = _entities_by_role(_states, "rain", "on")
                    if rain_sensors:
                        return "Es regnet gerade — Bewaesserung ist unnoetig."

            # ── Regel: Garagentor oeffnen nachts ──
            if func_name in ("set_cover",):
                eid_arg = str(args.get("entity_id", "")).lower()
                if "garage" in eid_arg and (hour >= 23 or hour < 5):
                    return f"Es ist {hour} Uhr — Garagentor oeffnen um diese Zeit?"

            # ── Dependency-basierte Konflikte via StateChangeLog ──
            try:
                _states = await _get_states()
                dep_hints = StateChangeLog.check_action_dependencies(
                    func_name,
                    args,
                    _states,
                )
                if dep_hints:
                    # Maximal 2 Hints um das LLM nicht zu ueberladen
                    return " | ".join(dep_hints[:2])
            except Exception as e:
                logger.debug("Abhaengigkeitspruefung fehlgeschlagen: %s", e)

            return None
        except Exception as e:
            logger.debug("Consequence-Check Fehler: %s", e)
            return None

    # ── Phase 11: Adaptive Helligkeit (dim2warm) ──────────────
    # Default-Kurve als Fallback (wird von settings.yaml überschrieben)
    _CIRCADIAN_BRIGHTNESS_CURVE_DEFAULT = [
        {"time": "00:00", "pct": 5},
        {"time": "01:00", "pct": 5},
        {"time": "02:00", "pct": 5},
        {"time": "03:00", "pct": 5},
        {"time": "04:00", "pct": 5},
        {"time": "05:00", "pct": 5},
        {"time": "06:00", "pct": 10},
        {"time": "07:00", "pct": 40},
        {"time": "08:00", "pct": 70},
        {"time": "09:00", "pct": 90},
        {"time": "10:00", "pct": 100},
        {"time": "11:00", "pct": 100},
        {"time": "12:00", "pct": 100},
        {"time": "13:00", "pct": 100},
        {"time": "14:00", "pct": 100},
        {"time": "15:00", "pct": 100},
        {"time": "16:00", "pct": 100},
        {"time": "17:00", "pct": 90},
        {"time": "18:00", "pct": 80},
        {"time": "19:00", "pct": 60},
        {"time": "20:00", "pct": 40},
        {"time": "21:00", "pct": 25},
        {"time": "22:00", "pct": 10},
        {"time": "23:00", "pct": 5},
    ]

    @staticmethod
    def _get_circadian_curve():
        """Liefert Circadian-Kurve aus settings.yaml (oder Default)."""
        curve = (
            yaml_config.get("lighting", {}).get("circadian", {}).get("brightness_curve")
        )
        if curve and isinstance(curve, list) and len(curve) >= 2:
            return curve
        return FunctionExecutor._CIRCADIAN_BRIGHTNESS_CURVE_DEFAULT

    @staticmethod
    def _interpolate_circadian(curve, key, now_h, now_m):
        """Interpoliert Wert aus zeitbasierter Kurve."""
        now_min = now_h * 60 + now_m
        prev_entry = curve[-1]
        for entry in curve:
            parts = entry["time"].split(":")
            if len(parts) < 2:
                prev_entry = entry
                continue
            entry_min = int(parts[0]) * 60 + int(parts[1])
            if entry_min > now_min:
                prev_parts = prev_entry["time"].split(":")
                if len(prev_parts) < 2:
                    return entry[key]
                prev_min = int(prev_parts[0]) * 60 + int(prev_parts[1])
                if prev_min > entry_min:
                    prev_min -= 1440
                span = entry_min - prev_min
                if span <= 0:
                    return entry[key]
                elapsed = now_min - prev_min
                if elapsed < 0:
                    elapsed += 1440
                ratio = elapsed / span
                return prev_entry[key] + (entry[key] - prev_entry[key]) * ratio
            prev_entry = entry
        return curve[-1][key]

    @staticmethod
    @staticmethod
    def _parse_brightness(args: dict) -> int | None:
        """Parst und validiert den Brightness-Parameter (1-100%). Gibt None zurueck bei Fehler."""
        try:
            bri = str(args.get("brightness", "")).replace("%", "").strip()
            return max(1, min(100, int(float(bri))))
        except (ValueError, TypeError):
            return None

    def get_adaptive_brightness(self, room: str, entity_id: str = "") -> int:
        """Berechnet Helligkeit basierend auf Tageszeit + Raum-Profil.

        Wenn lighting.circadian.enabled: nutzt interpolierte Helligkeitskurve.
        Sonst: Minuten-basierte lineare Interpolation (default/night).

        Per-Lampe Helligkeit: Wenn in room_profiles.yaml für diese entity_id
        individuelle Tag/Nacht-Werte definiert sind, werden diese verwendet.

        dim2warm-Lampen regeln Farbtemperatur über die Helligkeit
        in Hardware — je dunkler, desto waermer.
        """
        now = datetime.now(_LOCAL_TZ)
        minutes = now.hour * 60 + now.minute
        profiles = _get_room_profiles()
        room_cfg = profiles.get("rooms", {}).get(room, {})
        default_bright = room_cfg.get("default_brightness", 70)
        night_bright = room_cfg.get("night_brightness", 20)

        # Per-Lampe Helligkeit aus room_profiles (hat Vorrang)
        if entity_id:
            per_light = room_cfg.get("light_brightness", {}).get(entity_id)
            if per_light and isinstance(per_light, dict):
                default_bright = per_light.get("day", default_bright)
                night_bright = per_light.get("night", night_bright)

        # Zirkadiane Beleuchtung: feinere Kurve wenn aktiviert
        lighting_cfg = yaml_config.get("lighting", {})
        circadian = lighting_cfg.get("circadian", {})
        if circadian.get("enabled"):
            # Interpolierte Kurve liefert 0-100%, skaliert auf Raum-Profil
            curve_pct = FunctionExecutor._interpolate_circadian(
                FunctionExecutor._get_circadian_curve(), "pct", now.hour, now.minute
            )
            # Skaliere Kurve auf Raum-spezifischen Bereich (night..default)
            scaled = night_bright + (default_bright - night_bright) * (curve_pct / 100)
            return max(1, int(scaled))

        # Fallback: Minuten-basierte Interpolation (sanfte Übergaenge)
        # 06:00-09:00 (360-540): aufsteigend (night → default)
        # 09:00-17:00 (540-1020): volle Helligkeit (default)
        # 17:00-21:00 (1020-1260): absteigend (default → night)
        # 21:00-06:00: minimal (night)
        if 360 <= minutes < 540:  # Morgens: aufsteigend
            ratio = (minutes - 360) / 180
            return int(night_bright + (default_bright - night_bright) * ratio)
        elif 540 <= minutes < 1020:  # Tagsueber: volle Helligkeit
            return default_bright
        elif 1020 <= minutes < 1260:  # Abends: absteigend
            ratio = (minutes - 1020) / 240
            return int(default_bright - (default_bright - night_bright) * ratio)
        else:  # Nachts: minimal
            return night_bright

    async def _exec_set_light_floor(self, floor: str, args: dict, state: str) -> dict:
        """Alle Lichter einer Etage steuern (eg/og)."""
        profiles = _get_room_profiles()
        floor_rooms = [
            r
            for r, cfg in profiles.get("rooms", {}).items()
            if cfg.get("floor") == floor
        ]
        if not floor_rooms:
            return {
                "success": False,
                "message": f"Keine Räume für Etage '{floor.upper()}' konfiguriert",
            }

        # brighter/dimmer: pro Lampe aktuelle Helligkeit lesen und anpassen
        if state in ("brighter", "dimmer"):
            step = 15
            count = 0
            for room_name in floor_rooms:
                entity_id = await self._find_entity("light", room_name)
                if not entity_id:
                    continue
                current_brightness = 50
                ha_state = await self.ha.get_state(entity_id)
                if ha_state and ha_state.get("state") == "on":
                    raw = ha_state.get("attributes", {}).get("brightness", 128)
                    current_brightness = round(raw / 255 * 100)
                new_brightness = (
                    current_brightness + step
                    if state == "brighter"
                    else current_brightness - step
                )
                new_brightness = max(5, min(100, new_brightness))
                await self.ha.call_service(
                    "light",
                    "turn_on",
                    {"entity_id": entity_id, "brightness_pct": new_brightness},
                )
                count += 1
            direction = "heller" if state == "brighter" else "dunkler"
            return {
                "success": count > 0,
                "message": f"{count} Lichter im {floor.upper()} {direction}",
            }

        service = "turn_on" if state == "on" else "turn_off"
        count = 0
        for room_name in floor_rooms:
            entity_id = await self._find_entity("light", room_name)
            if not entity_id:
                continue
            service_data: dict = {"entity_id": entity_id}
            if state == "on":
                if "brightness" in args:
                    bri_pct = self._parse_brightness(args)
                    if bri_pct is not None:
                        service_data["brightness_pct"] = bri_pct
                else:
                    service_data["brightness_pct"] = self.get_adaptive_brightness(
                        room_name, entity_id
                    )
            await self.ha.call_service("light", service, service_data)
            count += 1

        return {
            "success": count > 0,
            "message": f"{count} Lichter im {floor.upper()} {state}",
        }

    async def _exec_set_light(self, args: dict) -> dict:
        room = args.get("room")
        state = args.get("state")
        device = args.get("device")
        person = args.pop("_person", "")

        # LLM-Fallback: entity_id statt room akzeptieren
        if not room and args.get("entity_id"):
            eid = args.get("entity_id", "")
            if eid.startswith("light."):
                room = eid.split(".", 1)[1]
            else:
                room = eid

        # LLM-Cleanup: Domain-Prefix aus room strippen
        room = self._clean_room(room)

        # State ableiten wenn nicht explizit angegeben
        if not state:
            state = "on"

        if not room:
            return {"success": False, "message": "Kein Raum angegeben"}

        # Phase 11: Etagen-Steuerung (eg/og)
        # Normalisierung: "obergeschoss"/"oben" -> "og", "erdgeschoss"/"unten" -> "eg"
        _floor_map = {
            "obergeschoss": "og",
            "oben": "og",
            "erster stock": "og",
            "erdgeschoss": "eg",
            "unten": "eg",
            "parterre": "eg",
        }
        _room_lower = room.lower()
        if _room_lower in _floor_map:
            _room_lower = _floor_map[_room_lower]
        if _room_lower in ("eg", "og"):
            return await self._exec_set_light_floor(_room_lower, args, state)

        # Sonderfall: "all" -> alle Lichter schalten
        if room.lower() == "all":
            return await self._exec_set_light_all(args, state)

        entity_id = await self._find_entity(
            "light", room, device_hint=device, person=person
        )
        if not entity_id:
            # Cross-Domain-Fallback: Vielleicht ist es ein Switch (z.B. Siebtraegermaschine)
            switch_id = await self._find_entity("switch", room, person=person)
            if switch_id:
                logger.info(
                    "set_light cross-domain fallback: '%s' -> switch %s",
                    room,
                    switch_id,
                )
                service = "turn_on" if state == "on" else "turn_off"
                success = await self.ha.call_service(
                    "switch", service, {"entity_id": switch_id}
                )
                return {"success": success, "message": f"Schalter {room} {state}"}
            return {"success": False, "message": f"Kein Licht in '{room}' gefunden"}

        # Relative Helligkeit: brighter/dimmer
        if state in ("brighter", "dimmer"):
            current_brightness = 50  # Fallback
            ha_state = await self.ha.get_state(entity_id)
            if ha_state and ha_state.get("state") == "on":
                attrs = ha_state.get("attributes", {})
                # HA gibt brightness als 0-255 zurück
                raw = attrs.get("brightness", 128)
                current_brightness = round(raw / 255 * 100)
            step = 15
            new_brightness = (
                current_brightness + step
                if state == "brighter"
                else current_brightness - step
            )
            new_brightness = max(5, min(100, new_brightness))
            service_data = {"entity_id": entity_id, "brightness_pct": new_brightness}
            # Default-Transition anwenden
            _lt = yaml_config.get("lighting", {}).get("default_transition")
            if _lt:
                try:
                    service_data["transition"] = int(_lt)
                except (ValueError, TypeError):
                    pass
            success = await self.ha.call_service("light", "turn_on", service_data)
            direction = "heller" if state == "brighter" else "dunkler"
            return {
                "success": success,
                "message": f"Licht {room} {direction} auf {new_brightness}%",
            }

        service_data = {"entity_id": entity_id}
        brightness_pct = None
        if "brightness" in args and state == "on":
            brightness_pct = self._parse_brightness(args)
            if brightness_pct is not None:
                service_data["brightness_pct"] = brightness_pct
        elif state == "on" and "brightness" not in args:
            # Phase 11: Adaptive Helligkeit wenn keine explizite Angabe
            brightness_pct = self.get_adaptive_brightness(room, entity_id)
            # Outcome-Learning: CorrectionMemory-Regeln koennen Brightness ueberschreiben
            try:
                import assistant.main as _main_mod

                _brain = _main_mod.brain
                if _brain and hasattr(_brain, "correction_memory"):
                    _rules = await _brain.correction_memory.get_active_rules(
                        action_type="set_light",
                        person=person,
                    )
                    for _rule in _rules:
                        if _rule.get("confidence", 0) > 0.6:
                            _rule_text = _rule.get("text", "").lower()
                            if "brightness" in _rule_text or "helligkeit" in _rule_text:
                                import re

                                _bri_match = re.search(r"(\d{1,3})\s*%?", _rule_text)
                                if _bri_match:
                                    _learned_bri = int(_bri_match.group(1))
                                    if 1 <= _learned_bri <= 100:
                                        logger.info(
                                            "CorrectionMemory Brightness Override: %d%% -> %d%% (person=%s)",
                                            brightness_pct,
                                            _learned_bri,
                                            person,
                                        )
                                        brightness_pct = _learned_bri
                                        break
            except Exception as e:
                logger.debug("CorrectionMemory Brightness-Lookup fehlgeschlagen: %s", e)
            service_data["brightness_pct"] = brightness_pct
        # Phase 9: Transition-Parameter (sanftes Dimmen) — muss int/float sein
        if "transition" in args:
            try:
                service_data["transition"] = int(args.get("transition", 2))
            except (ValueError, TypeError):
                # LLM schickt manchmal "smooth" statt Zahl — Default 2s
                service_data["transition"] = 2
        else:
            # Kein expliziter Transition: Default aus lighting-Config (on + off)
            _lt = yaml_config.get("lighting", {}).get("default_transition")
            if _lt:
                try:
                    if int(_lt) > 0:
                        service_data["transition"] = int(_lt)
                except (ValueError, TypeError):
                    pass
        # dim2warm: Farbtemperatur wird in Hardware über Helligkeit geregelt.
        # Kein color_temp_kelvin an HA senden — Lampen machen das selbst.

        logger.info(
            "set_light: %s -> %s (service_data=%s)", room, entity_id, service_data
        )

        service = "turn_on" if state == "on" else "turn_off"
        success = await self.ha.call_service("light", service, service_data)
        # Manual Override markieren wenn User explizit Helligkeit gesetzt hat
        if "brightness" in args or state in ("brighter", "dimmer"):
            le = getattr(self, "_light_engine", None)
            if le:
                try:
                    await le.record_manual_override(entity_id)
                except Exception as e:
                    if isinstance(e, asyncio.CancelledError):
                        raise
                    logger.debug("record_manual_override failed: %s", e)
        extras = []
        if brightness_pct is not None:
            extras.append(f"{brightness_pct}%")
        if "transition" in args:
            extras.append(f"Transition: {args['transition']}s")
        extra_str = f" ({', '.join(extras)})" if extras else ""
        return {
            "success": success,
            "message": f"Licht {room} {state}{extra_str}",
            "entity_id": entity_id,
        }

    async def _exec_set_light_all(self, args: dict, state: str) -> dict:
        """Alle Lichter ein- oder ausschalten."""
        states = await self.ha.get_states()
        if not states:
            return {
                "success": False,
                "message": "Die Systeme antworten gerade nicht. Ich versuche es gleich erneut.",
            }

        service = "turn_on" if state == "on" else "turn_off"
        count = 0
        # Bulk-Op: Dependency-Check ueberspringen — wird bereits vom Executor geprueft
        self.ha._skip_dep_check_depth = getattr(self.ha, "_skip_dep_check_depth", 0) + 1
        try:
            for s in states:
                eid = s.get("entity_id", "")
                if not eid.startswith("light."):
                    continue
                if not is_entity_annotated(eid) or is_entity_hidden(eid):
                    continue
                if s.get("state") != state or (state == "on" and "brightness" in args):
                    service_data = {"entity_id": eid}
                    if state == "on":
                        if "brightness" in args:
                            bri_pct = self._parse_brightness(args)
                            if bri_pct is not None:
                                service_data["brightness_pct"] = bri_pct
                        else:
                            # Adaptive Helligkeit wenn keine explizite Angabe
                            room_name = eid.split(".", 1)[1] if "." in eid else ""
                            service_data["brightness_pct"] = (
                                self.get_adaptive_brightness(room_name, eid)
                            )
                    await self.ha.call_service("light", service, service_data)
                    count += 1
        finally:
            self.ha._skip_dep_check_depth = max(
                0, getattr(self.ha, "_skip_dep_check_depth", 1) - 1
            )

        return {
            "success": True,
            "message": f"Alle Lichter {state} ({count} geschaltet)",
        }

    async def _exec_get_lights(self, args: dict) -> dict:
        """Alle Lichter mit Name, Raum-Zuordnung und Status auflisten."""
        room_filter = self._clean_room(args.get("room", ""))

        # Geräte aus MindHome DB laden (enthält Raum-Zuordnung)
        try:
            devices = await self.ha.search_devices(domain="light", room=room_filter)
        except Exception as e:
            logger.debug("MindHome light-devices nicht ladbar: %s", e)
            devices = None

        # HA-States für aktuellen Status laden
        states = await self.ha.get_states()
        if not states:
            return {
                "success": False,
                "message": "Die Systeme antworten gerade nicht. Ich versuche es gleich erneut.",
            }

        # State-Lookup: entity_id -> state-dict
        state_map = {}
        for s in states:
            eid = s.get("entity_id", "")
            if eid.startswith("light."):
                state_map[eid] = s

        lights = []

        if devices:
            # MindHome DB hat Raum-Zuordnung
            for dev in devices:
                eid = dev.get("ha_entity_id", "")
                name = dev.get("name", eid)
                room = dev.get("room", "—")
                ha = state_map.get(eid, {})
                status = ha.get("state", "unknown")
                attrs = ha.get("attributes", {})
                brightness = ""
                if status == "on" and "brightness" in attrs:
                    bri_pct = round(attrs["brightness"] / 255 * 100)
                    brightness = f" ({bri_pct}%)"
                lights.append(f"- {name} [{room}]: {status}{brightness}")
        else:
            # Fallback: alle light-Entities aus HA (ohne Raum-Zuordnung)
            search_norm = self._normalize_name(room_filter) if room_filter else ""
            for eid, ha in state_map.items():
                if search_norm:
                    entity_name = eid.split(".", 1)[1]
                    friendly = ha.get("attributes", {}).get("friendly_name", "")
                    if search_norm not in self._normalize_name(
                        entity_name
                    ) and search_norm not in self._normalize_name(friendly):
                        continue
                attrs = ha.get("attributes", {})
                friendly = attrs.get("friendly_name", eid)
                status = ha.get("state", "unknown")
                brightness = ""
                if status == "on" and "brightness" in attrs:
                    bri_pct = round(attrs["brightness"] / 255 * 100)
                    brightness = f" ({bri_pct}%)"
                lights.append(f"- {friendly}: {status}{brightness}")

        if not lights:
            msg = (
                f"Keine Lichter in '{room_filter}' gefunden."
                if room_filter
                else "Keine Lichter gefunden."
            )
            return {"success": False, "message": msg}

        on_count = sum(1 for l in lights if ": on" in l)
        header = f"{len(lights)} Lichter"
        if room_filter:
            header += f" in '{room_filter}'"
        header += f" ({on_count} an, {len(lights) - on_count} aus):\n"

        return {"success": True, "message": header + "\n".join(lights)}

    async def _exec_get_covers(self, args: dict) -> dict:
        """Alle Rollläden/Jalousien mit Status auflisten."""
        room_filter = self._clean_room(args.get("room", ""))

        try:
            devices = await self.ha.search_devices(domain="cover", room=room_filter)
        except Exception as e:
            logger.debug("MindHome cover-devices nicht ladbar: %s", e)
            devices = None

        states = await self.ha.get_states()
        if not states:
            return {
                "success": False,
                "message": "Die Systeme antworten gerade nicht. Ich versuche es gleich erneut.",
            }

        state_map = {}
        for s in states:
            eid = s.get("entity_id", "")
            if eid.startswith("cover."):
                state_map[eid] = s

        covers = []
        if devices:
            for dev in devices:
                eid = dev.get("ha_entity_id", "")
                name = dev.get("name", eid)
                room = dev.get("room", "—")
                ha = state_map.get(eid, {})
                status = ha.get("state", "unknown")
                attrs = ha.get("attributes", {})
                pos = attrs.get("current_position")
                if pos is not None:
                    try:
                        pos = self._translate_cover_position_from_ha(eid, int(pos))
                    except (ValueError, TypeError):
                        pass
                pos_str = f" ({pos}%)" if pos is not None else ""
                covers.append(f"- {name} [{room}]: {status}{pos_str}")
        else:
            search_norm = self._normalize_name(room_filter) if room_filter else ""
            for eid, ha in state_map.items():
                if search_norm:
                    entity_name = eid.split(".", 1)[1]
                    friendly = ha.get("attributes", {}).get("friendly_name", "")
                    if search_norm not in self._normalize_name(
                        entity_name
                    ) and search_norm not in self._normalize_name(friendly):
                        continue
                attrs = ha.get("attributes", {})
                friendly = attrs.get("friendly_name", eid)
                status = ha.get("state", "unknown")
                pos = attrs.get("current_position")
                if pos is not None:
                    try:
                        pos = self._translate_cover_position_from_ha(eid, int(pos))
                    except (ValueError, TypeError):
                        pass
                pos_str = f" ({pos}%)" if pos is not None else ""
                covers.append(f"- {friendly}: {status}{pos_str}")

        if not covers:
            msg = (
                f"Keine Rollläden in '{room_filter}' gefunden."
                if room_filter
                else "Keine Rollläden gefunden."
            )
            return {"success": False, "message": msg}

        open_count = sum(1 for c in covers if ": open" in c)
        header = f"{len(covers)} Rollläden"
        if room_filter:
            header += f" in '{room_filter}'"
        header += f" ({open_count} offen, {len(covers) - open_count} zu):\n"
        return {"success": True, "message": header + "\n".join(covers)}

    async def _exec_get_media(self, args: dict) -> dict:
        """Alle Media Player mit Status auflisten."""
        room_filter = self._clean_room(args.get("room", ""))

        states = await self.ha.get_states()
        if not states:
            return {
                "success": False,
                "message": "Die Systeme antworten gerade nicht. Ich versuche es gleich erneut.",
            }

        search_norm = self._normalize_name(room_filter) if room_filter else ""
        players = []
        for s in states:
            eid = s.get("entity_id", "")
            if not eid.startswith("media_player."):
                continue
            if search_norm:
                entity_name = eid.split(".", 1)[1]
                friendly = s.get("attributes", {}).get("friendly_name", "")
                if search_norm not in self._normalize_name(
                    entity_name
                ) and search_norm not in self._normalize_name(friendly):
                    continue
            attrs = s.get("attributes", {})
            friendly = attrs.get("friendly_name", eid)
            status = s.get("state", "unknown")
            details = []
            title = attrs.get("media_title")
            artist = attrs.get("media_artist")
            if title:
                details.append(title)
            if artist:
                details.append(artist)
            vol = attrs.get("volume_level")
            if vol is not None:
                details.append(f"Vol: {round(vol * 100)}%")
            detail_str = f" — {', '.join(details)}" if details else ""
            players.append(f"- {friendly}: {status}{detail_str}")

        if not players:
            msg = (
                f"Keine Media Player in '{room_filter}' gefunden."
                if room_filter
                else "Keine Media Player gefunden."
            )
            return {"success": False, "message": msg}

        playing = sum(1 for p in players if ": playing" in p)
        header = f"{len(players)} Media Player"
        if room_filter:
            header += f" in '{room_filter}'"
        header += f" ({playing} aktiv):\n"
        return {"success": True, "message": header + "\n".join(players)}

    async def _exec_get_climate(self, args: dict) -> dict:
        """Alle Thermostate/Heizungen mit Status auflisten."""
        room_filter = self._clean_room(args.get("room", ""))

        try:
            devices = await self.ha.search_devices(domain="climate", room=room_filter)
        except Exception as e:
            logger.debug("MindHome climate-devices nicht ladbar: %s", e)
            devices = None

        states = await self.ha.get_states()
        if not states:
            return {
                "success": False,
                "message": "Die Systeme antworten gerade nicht. Ich versuche es gleich erneut.",
            }

        state_map = {}
        for s in states:
            eid = s.get("entity_id", "")
            if eid.startswith("climate."):
                state_map[eid] = s

        thermostats = []
        if devices:
            for dev in devices:
                eid = dev.get("ha_entity_id", "")
                name = dev.get("name", eid)
                room = dev.get("room", "—")
                ha = state_map.get(eid, {})
                mode = ha.get("state", "unknown")
                attrs = ha.get("attributes", {})
                current = attrs.get("current_temperature")
                target = attrs.get("temperature")
                parts = [mode]
                if current is not None:
                    parts.append(f"Ist: {current}°C")
                if target is not None:
                    parts.append(f"Soll: {target}°C")
                thermostats.append(f"- {name} [{room}]: {', '.join(parts)}")
        else:
            search_norm = self._normalize_name(room_filter) if room_filter else ""
            for eid, ha in state_map.items():
                if search_norm:
                    entity_name = eid.split(".", 1)[1]
                    friendly = ha.get("attributes", {}).get("friendly_name", "")
                    if search_norm not in self._normalize_name(
                        entity_name
                    ) and search_norm not in self._normalize_name(friendly):
                        continue
                attrs = ha.get("attributes", {})
                friendly = attrs.get("friendly_name", eid)
                mode = ha.get("state", "unknown")
                current = attrs.get("current_temperature")
                target = attrs.get("temperature")
                parts = [mode]
                if current is not None:
                    parts.append(f"Ist: {current}°C")
                if target is not None:
                    parts.append(f"Soll: {target}°C")
                thermostats.append(f"- {friendly}: {', '.join(parts)}")

        if not thermostats:
            msg = (
                f"Keine Thermostate in '{room_filter}' gefunden."
                if room_filter
                else "Keine Thermostate gefunden."
            )
            return {"success": False, "message": msg}

        heating = sum(1 for t in thermostats if "heat" in t.lower())
        header = f"{len(thermostats)} Thermostate"
        if room_filter:
            header += f" in '{room_filter}'"
        header += f" ({heating} heizen):\n"
        return {"success": True, "message": header + "\n".join(thermostats)}

    async def _exec_get_switches(self, args: dict) -> dict:
        """Alle Steckdosen/Schalter mit Status und Leistungsdaten auflisten."""
        room_filter = self._clean_room(args.get("room", ""))

        try:
            devices = await self.ha.search_devices(domain="switch", room=room_filter)
        except Exception as e:
            logger.debug("MindHome switch-devices nicht ladbar: %s", e)
            devices = None

        states = await self.ha.get_states()
        if not states:
            return {
                "success": False,
                "message": "Die Systeme antworten gerade nicht. Ich versuche es gleich erneut.",
            }

        state_map = {}
        # Sensor-Map für zugehoerige Power-Sensoren (sensor.*_power, sensor.*_current etc.)
        sensor_map: dict[str, dict] = {}
        for s in states:
            eid = s.get("entity_id", "")
            if eid.startswith("switch."):
                state_map[eid] = s
            elif eid.startswith("sensor."):
                sensor_map[eid] = s

        def _get_power_info(switch_eid: str, ha_state: dict) -> str:
            """Extrahiert Leistungsdaten aus Switch-Attributen oder zugehoerenden Sensoren."""
            parts = []
            attrs = ha_state.get("attributes", {})
            # Direkte Power-Attribute (viele Smart Plugs)
            for key in (
                "current_power_w",
                "current_power",
                "load_power",
                "power",
                "wattage",
            ):
                val = attrs.get(key)
                if val is not None:
                    try:
                        parts.append(f"{float(val):.1f} W")
                    except (ValueError, TypeError):
                        pass
                    break
            # Zugehoerige Sensor-Entities: switch.xyz → sensor.xyz_power / sensor.xyz_energy
            base = switch_eid.split(".", 1)[1] if "." in switch_eid else ""
            if base and not parts:
                for suffix in (
                    "_power",
                    "_current_consumption",
                    "_electric_consumption",
                    "_watt",
                    "_current_power",
                ):
                    sensor_eid = f"sensor.{base}{suffix}"
                    s_state = sensor_map.get(sensor_eid)
                    if s_state and s_state.get("state") not in (
                        None,
                        "unknown",
                        "unavailable",
                    ):
                        unit = s_state.get("attributes", {}).get(
                            "unit_of_measurement", "W"
                        )
                        parts.append(f"{s_state['state']} {unit}")
                        break
            return ", ".join(parts)

        switches = []
        if devices:
            for dev in devices:
                eid = dev.get("ha_entity_id", "")
                name = dev.get("name", eid)
                room = dev.get("room", "—")
                ha = state_map.get(eid, {})
                status = ha.get("state", "unknown")
                power = _get_power_info(eid, ha)
                entry = f"- {name} [{room}]: {status}"
                if power:
                    entry += f" ({power})"
                switches.append(entry)
        else:
            search_norm = self._normalize_name(room_filter) if room_filter else ""
            for eid, ha in state_map.items():
                if search_norm:
                    entity_name = eid.split(".", 1)[1]
                    friendly = ha.get("attributes", {}).get("friendly_name", "")
                    if search_norm not in self._normalize_name(
                        entity_name
                    ) and search_norm not in self._normalize_name(friendly):
                        continue
                attrs = ha.get("attributes", {})
                friendly = attrs.get("friendly_name", eid)
                status = ha.get("state", "unknown")
                power = _get_power_info(eid, ha)
                entry = f"- {friendly}: {status}"
                if power:
                    entry += f" ({power})"
                switches.append(entry)

        if not switches:
            msg = (
                f"Keine Schalter in '{room_filter}' gefunden."
                if room_filter
                else "Keine Schalter gefunden."
            )
            return {"success": False, "message": msg}

        on_count = sum(1 for s in switches if ": on" in s)
        header = f"{len(switches)} Schalter/Steckdosen"
        if room_filter:
            header += f" in '{room_filter}'"
        header += f" ({on_count} an, {len(switches) - on_count} aus):\n"
        return {"success": True, "message": header + "\n".join(switches)}

    async def _exec_set_switch(self, args: dict) -> dict:
        """Steckdose oder Schalter ein-/ausschalten."""
        room = args.get("room")
        state = args.get("state")

        # LLM-Fallback: entity_id statt room
        if not room and args.get("entity_id"):
            eid = args.get("entity_id", "")
            room = eid.split(".", 1)[1] if "." in eid else eid
        room = self._clean_room(room)

        if not state:
            state = "off"
        if not room:
            return {"success": False, "message": "Kein Raum/Name angegeben"}

        entity_id = await self._find_entity("switch", room)
        if not entity_id:
            return {"success": False, "message": f"Kein Schalter in '{room}' gefunden"}

        service = "turn_on" if state == "on" else "turn_off"
        logger.info("set_switch: %s -> %s (%s)", room, entity_id, service)
        success = await self.ha.call_service(
            "switch", service, {"entity_id": entity_id}
        )
        return {"success": success, "message": f"Schalter {room} {state}"}

    async def _exec_set_climate(self, args: dict) -> dict:
        heating = yaml_config.get("heating", {})
        mode = heating.get("mode", "room_thermostat")

        if mode == "heating_curve":
            return await self._exec_set_climate_curve(args, heating)
        return await self._exec_set_climate_room(args)

    async def _exec_set_climate_curve(self, args: dict, heating: dict) -> dict:
        """Heizkurven-Modus: Offset auf zentrales Entity setzen."""
        try:
            offset = float(args.get("offset", 0))
        except (ValueError, TypeError):
            return {
                "success": False,
                "message": f"Ungültiger Offset: {args.get('offset')}",
            }
        entity_id = heating.get("curve_entity", "")
        if not entity_id:
            return {
                "success": False,
                "message": "Kein Heizungs-Entity konfiguriert (heating.curve_entity)",
            }

        # Aktuellen Zustand holen um Basis-Temperatur zu ermitteln
        states = await self.ha.get_states()
        current_state = None
        for s in states or []:
            if s.get("entity_id") == entity_id:
                current_state = s
                break

        if not current_state:
            return {"success": False, "message": f"Entity {entity_id} nicht gefunden"}

        # Basis-Temperatur der Heizkurve (vom Regler geliefert)
        attrs = current_state.get("attributes", {})
        base_temp = attrs.get("temperature")
        if base_temp is None:
            return {
                "success": False,
                "message": f"Der Temperatursensor {entity_id} antwortet gerade nicht.",
            }

        # Offset-Grenzen aus Config erzwingen
        offset_min = heating.get("curve_offset_min", -5)
        offset_max = heating.get("curve_offset_max", 5)
        offset = max(offset_min, min(offset_max, offset))

        # Offset wird absolut zur Basis-Temperatur gesetzt (nicht kumulativ)
        new_temp = float(base_temp) + offset

        service_data = {"entity_id": entity_id, "temperature": new_temp}
        if "mode" in args:
            service_data["hvac_mode"] = args.get("mode", "")

        success = await self.ha.call_service("climate", "set_temperature", service_data)
        sign = "+" if offset >= 0 else ""
        return {
            "success": success,
            "message": f"Heizung: Offset {sign}{offset}°C (Vorlauf {new_temp}°C)",
        }

    async def _exec_set_climate_room(self, args: dict) -> dict:
        """Raumthermostat-Modus: Temperatur pro Raum setzen."""
        room = args.get("room")
        # LLM-Fallback: entity_id statt room
        if not room and args.get("entity_id"):
            eid = args.get("entity_id", "")
            room = eid.split(".", 1)[1] if "." in eid else eid
        room = self._clean_room(room)
        if not room:
            return {"success": False, "message": "Kein Raum angegeben"}
        entity_id = await self._find_entity("climate", room)
        if not entity_id:
            return {
                "success": False,
                "message": f"Kein Thermostat in '{room}' gefunden",
            }

        # Relative Anpassung: warmer/cooler
        adjust = args.get("adjust")
        if adjust in ("warmer", "cooler"):
            ha_state = await self.ha.get_state(entity_id)
            current_temp = 21.0  # Fallback
            if ha_state:
                attrs = ha_state.get("attributes", {})
                current_temp = float(attrs.get("temperature", 21.0))
            step = 1.0
            temp = current_temp + step if adjust == "warmer" else current_temp - step
            # Sicherheitsgrenzen
            security = yaml_config.get("security", {}).get("climate_limits", {})
            temp = max(security.get("min", 5), min(security.get("max", 30), temp))
        elif "temperature" in args:
            try:
                temp = float(args.get("temperature", 0))
            except (ValueError, TypeError):
                return {
                    "success": False,
                    "message": f"Ungültige Temperatur: {args.get('temperature', '')}",
                }
        else:
            return {"success": False, "message": "Keine Temperatur angegeben"}

        service_data = {"entity_id": entity_id, "temperature": temp}
        if "mode" in args:
            service_data["hvac_mode"] = args.get("mode", "")

        success = await self.ha.call_service("climate", "set_temperature", service_data)
        direction = ""
        if adjust == "warmer":
            direction = "waermer auf "
        elif adjust == "cooler":
            direction = "kaelter auf "
        return {"success": success, "message": f"{room} {direction}{temp}°C"}

    # Standard Mood-Szenen: Multi-Device-Orchestrierung fuer natuerliche Kommandos
    # wie "Mach es gemuetlich" oder "Filmabend". Konfigurierbar via scenes.mood_scenes.
    _DEFAULT_MOOD_SCENES = {
        "gemuetlich": {
            "label": "Gemuetlich",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "data": {"brightness_pct": 30, "color_temp_kelvin": 2700},
                },
                {"domain": "cover", "service": "close_cover", "data": {}},
            ],
            "climate_offset": 1.0,
        },
        "filmabend": {
            "label": "Filmabend",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "data": {"brightness_pct": 10, "color_temp_kelvin": 2200},
                },
                {"domain": "cover", "service": "close_cover", "data": {}},
                {"domain": "media_player", "service": "turn_on", "data": {}},
            ],
        },
        "party": {
            "label": "Party",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "data": {"brightness_pct": 100, "rgb_color": [255, 100, 50]},
                },
                {"domain": "cover", "service": "close_cover", "data": {}},
            ],
        },
        "konzentration": {
            "label": "Konzentration",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "data": {"brightness_pct": 80, "color_temp_kelvin": 5000},
                },
            ],
        },
        "gute_nacht": {
            "label": "Gute Nacht",
            "actions": [
                {"domain": "light", "service": "turn_off", "data": {}},
                {"domain": "cover", "service": "close_cover", "data": {}},
            ],
            "climate_offset": -2.0,
        },
        "aufwachen": {
            "label": "Aufwachen",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "data": {"brightness_pct": 60, "color_temp_kelvin": 4000},
                },
                {"domain": "cover", "service": "open_cover", "data": {}},
            ],
            "climate_offset": 1.0,
        },
        "hell": {
            "label": "Hell",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "data": {"brightness_pct": 100, "color_temp_kelvin": 5000},
                },
                {"domain": "cover", "service": "open_cover", "data": {}},
            ],
        },
        "kochen": {
            "label": "Kochen",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "data": {"brightness_pct": 100, "color_temp_kelvin": 4500},
                },
            ],
        },
        "essen": {
            "label": "Essen",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "data": {"brightness_pct": 60, "color_temp_kelvin": 2700},
                },
            ],
        },
        "schlafen": {
            "label": "Schlafen",
            "actions": [
                {"domain": "light", "service": "turn_off", "data": {}},
                {"domain": "cover", "service": "close_cover", "data": {}},
            ],
            "climate_offset": -1.0,
        },
        "lesen": {
            "label": "Lesen",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "data": {"brightness_pct": 40, "color_temp_kelvin": 3000},
                },
            ],
        },
        "arbeiten": {
            "label": "Arbeiten",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "data": {"brightness_pct": 80, "color_temp_kelvin": 5000},
                },
            ],
        },
        "meeting": {
            "label": "Meeting",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "data": {"brightness_pct": 90, "color_temp_kelvin": 4500},
                },
            ],
        },
        "spielen": {
            "label": "Spielen",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "data": {"brightness_pct": 80, "color_temp_kelvin": 4000},
                },
            ],
        },
        "morgens": {
            "label": "Bad Morgens",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "data": {"brightness_pct": 100, "color_temp_kelvin": 5000},
                },
            ],
            "climate_offset": 2.0,
        },
        "abends": {
            "label": "Bad Abends",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "data": {"brightness_pct": 20, "color_temp_kelvin": 2200},
                },
            ],
        },
        "romantisch": {
            "label": "Romantisch",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "data": {"brightness_pct": 5, "color_temp_kelvin": 2200},
                },
                {"domain": "cover", "service": "close_cover", "data": {}},
            ],
        },
        "energiesparen": {
            "label": "Energiesparen",
            "actions": [
                {"domain": "light", "service": "turn_off", "data": {}},
            ],
            "climate_offset": -3.0,
        },
        "putzen": {
            "label": "Putzen",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "data": {"brightness_pct": 100, "color_temp_kelvin": 5000},
                },
                {"domain": "cover", "service": "open_cover", "data": {}},
            ],
        },
        "musik": {
            "label": "Musik",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "data": {"brightness_pct": 40, "color_temp_kelvin": 2700},
                },
                {"domain": "media_player", "service": "turn_on", "data": {}},
            ],
        },
    }

    # Mood-Aliases: Natuerliche Sprache → Szenen-Key
    _MOOD_ALIASES = {
        "cozy": "gemuetlich",
        "chill": "gemuetlich",
        "chillen": "gemuetlich",
        "relax": "gemuetlich",
        "entspannung": "gemuetlich",
        "film": "filmabend",
        "kino": "filmabend",
        "movie": "filmabend",
        "feiern": "party",
        "feier": "party",
        "fokus": "konzentration",
        "focus": "konzentration",
        "nacht": "gute_nacht",
        "bett": "gute_nacht",
        # Neue Szenen-Aliases
        "aufstehen": "aufwachen",
        "wecken": "aufwachen",
        "alles_an": "hell",
        "voll_hell": "hell",
        "maximale_helligkeit": "hell",
        "essen_machen": "kochen",
        "cooking": "kochen",
        "abendessen": "essen",
        "dinner": "essen",
        "mahlzeit": "essen",
        "ins_bett": "schlafen",
        "schlafenszeit": "schlafen",
        "pennen": "schlafen",
        "buch": "lesen",
        "reading": "lesen",
        "arbeit": "arbeiten",
        "buero": "arbeiten",
        "office": "arbeiten",
        "work": "arbeiten",
        "videocall": "meeting",
        "zoom": "meeting",
        "teams": "meeting",
        "kinder": "spielen",
        "toben": "spielen",
        "frueh": "morgens",
        "morgenroutine": "morgens",
        "baden": "abends",
        "entspannen_bad": "abends",
        "candle_light": "romantisch",
        "date": "romantisch",
        "zweisamkeit": "romantisch",
        "romantic": "romantisch",
        "romantik": "romantisch",
        "sparen": "energiesparen",
        "eco": "energiesparen",
        "strom_sparen": "energiesparen",
        "sauber_machen": "putzen",
        "aufraemen": "putzen",
        "cleaning": "putzen",
        "musik_hoeren": "musik",
        "sound": "musik",
        "anlage": "musik",
    }

    async def _exec_activate_scene(self, args: dict) -> dict:
        scene = args.get("scene")
        if not scene:
            return {"success": False, "message": "Keine Szene angegeben"}

        # Mood-Scene Check: natuerliche Sprache → Multi-Device-Orchestrierung
        scene_lower = scene.lower().replace(" ", "_").replace("-", "_")
        mood_scenes_cfg = yaml_config.get("scenes", {}).get("mood_scenes", {})
        mood_scenes = {**self._DEFAULT_MOOD_SCENES, **mood_scenes_cfg}

        mood_key = self._MOOD_ALIASES.get(scene_lower, scene_lower)

        if mood_key in mood_scenes:
            # [3] Rate-Limiting: 30s Cooldown pro Szene
            redis = getattr(self, "_redis", None)
            if redis:
                cooldown_key = f"mha:scene:cooldown:{mood_key}"
                try:
                    if await redis.get(cooldown_key):
                        label = mood_scenes[mood_key].get("label", mood_key)
                        return {
                            "success": True,
                            "message": f"'{label}' ist bereits aktiv.",
                        }
                    await redis.setex(cooldown_key, 30, "1")
                except Exception as e:
                    logger.debug("Redis Szenen-Cooldown fehlgeschlagen: %s", e)

            mood = mood_scenes[mood_key]
            actions_done = []
            errors = []
            room = args.get("room", "")

            # [4] Transition-Dauer aus Config (z.B. filmabend=5s, gute_nacht=7s)
            _transition = (
                yaml_config.get("narration", {})
                .get("scene_transitions", {})
                .get(mood_key, 3)
            )

            # [5] Snapshot fuer Undo: Aktuellen Zustand betroffener Entities speichern
            snapshot = []
            states = await self.ha.get_states()

            if states and redis:
                for action in mood.get("actions", []):
                    _dom = action.get("domain", "")
                    for s in states or []:
                        eid = s.get("entity_id", "")
                        if (
                            eid.startswith(f"{_dom}.")
                            and is_entity_annotated(eid)
                            and not is_entity_hidden(eid)
                        ):
                            snapshot.append(
                                {
                                    "entity_id": eid,
                                    "state": s.get("state", "off"),
                                    "brightness": s.get("attributes", {}).get(
                                        "brightness"
                                    ),
                                    "color_temp": s.get("attributes", {}).get(
                                        "color_temp"
                                    ),
                                    "temperature": s.get("attributes", {}).get(
                                        "temperature"
                                    ),
                                }
                            )
                try:
                    import json as _json

                    await redis.setex(
                        f"mha:scene:snapshot:{mood_key}", 3600, _json.dumps(snapshot)
                    )
                except Exception as e:
                    logger.debug(
                        "Redis Szenen-Snapshot Speicherung fehlgeschlagen: %s", e
                    )

            for action in mood.get("actions", []):
                domain = action["domain"]
                service = action["service"]
                data = dict(action.get("data", {}))

                # [7] User-Overrides anwenden (z.B. "filmabend aber heller")
                if domain == "light" and args.get("brightness_override") is not None:
                    data["brightness_pct"] = max(
                        0, min(100, int(args["brightness_override"]))
                    )

                # [10] Room-spezifische Scene-Overrides
                if room:
                    room_overrides = yaml_config.get("scenes", {}).get(
                        "room_overrides", {}
                    )
                    room_scene_cfg = room_overrides.get(room.lower(), {}).get(
                        mood_key, {}
                    )
                    if room_scene_cfg:
                        data.update(room_scene_cfg)

                # [6] Entities finden + Error-Handling pro Entity
                try:
                    if not states:
                        states = await self.ha.get_states()
                    for s in states or []:
                        eid = s.get("entity_id", "")
                        if not eid.startswith(f"{domain}."):
                            continue
                        # [1] Nur annotierte, nicht-versteckte Entities steuern
                        if not is_entity_annotated(eid) or is_entity_hidden(eid):
                            continue
                        # Raum-Filter wenn angegeben
                        if room and room.lower() not in eid.lower():
                            _area = s.get("attributes", {}).get("area", "")
                            if room.lower() not in (_area or "").lower():
                                continue
                        # Cover-Sicherheitspruefung
                        if domain == "cover" and hasattr(self, "_is_safe_cover"):
                            if not await self._is_safe_cover(eid, s):
                                continue
                        svc_data = {**data, "entity_id": eid}
                        # [4] Smooth transition fuer Lichter
                        if (
                            domain == "light"
                            and service == "turn_on"
                            and _transition > 0
                        ):
                            svc_data["transition"] = _transition
                        # [11] dim2warm: Farbtemperatur nicht an HA senden —
                        # Hardware regelt color_temp ueber Helligkeit.
                        # Nur tunable_white bekommt color_temp_kelvin.
                        if domain == "light" and (
                            "color_temp_kelvin" in svc_data or "rgb_color" in svc_data
                        ):
                            _room_name = _mindhome_device_rooms.get(eid, "")
                            _profiles = _get_room_profiles()
                            _room_cfg = _profiles.get("rooms", {}).get(_room_name, {})
                            _lt = _room_cfg.get("light_type", "standard")
                            if _lt == "dim2warm":
                                # dim2warm: nur Helligkeit senden
                                svc_data.pop("color_temp_kelvin", None)
                                svc_data.pop("rgb_color", None)
                            elif _lt == "standard":
                                # Standard: kein Farbsupport
                                svc_data.pop("color_temp_kelvin", None)
                                svc_data.pop("rgb_color", None)
                        try:
                            await self.ha.call_service(domain, service, svc_data)
                        except Exception as e:
                            errors.append(f"{eid}: {e}")
                            logger.warning("Mood-Scene Fehler bei %s: %s", eid, e)
                except Exception as e:
                    errors.append(f"{domain}.{service}: {e}")
                    logger.warning("Mood-Scene %s/%s Fehler: %s", domain, service, e)

                actions_done.append(f"{domain}.{service}")

            # [2] Optionaler Klima-Offset mit Bounds-Check
            if "climate_offset" in mood:
                try:
                    # [7] Temperature-Override hat Vorrang vor Offset
                    if args.get("temperature_override") is not None:
                        target_temp = max(
                            15.0, min(26.0, float(args["temperature_override"]))
                        )
                        if not states:
                            states = await self.ha.get_states()
                        for s in states or []:
                            eid = s.get("entity_id", "")
                            if eid.startswith("climate.") and is_entity_annotated(eid):
                                await self.ha.call_service(
                                    "climate",
                                    "set_temperature",
                                    {"entity_id": eid, "temperature": target_temp},
                                )
                    else:
                        offset = float(mood["climate_offset"])
                        if not states:
                            states = await self.ha.get_states()
                        for s in states or []:
                            eid = s.get("entity_id", "")
                            if eid.startswith("climate.") and is_entity_annotated(eid):
                                current_temp = s.get("attributes", {}).get(
                                    "temperature"
                                )
                                if current_temp is not None:
                                    new_temp = max(
                                        15.0, min(26.0, float(current_temp) + offset)
                                    )
                                    await self.ha.call_service(
                                        "climate",
                                        "set_temperature",
                                        {"entity_id": eid, "temperature": new_temp},
                                    )
                except Exception as e:
                    logger.warning("Mood-Scene Klima-Offset Fehler: %s", e)

            # [9] Active Scene Tracking
            if redis:
                try:
                    current = await redis.get("mha:scene:active")
                    if current:
                        current = (
                            current.decode() if isinstance(current, bytes) else current
                        )
                        if current != mood_key:
                            logger.info("Szenen-Wechsel: %s → %s", current, mood_key)
                    await redis.setex("mha:scene:active", 7200, mood_key)
                except Exception as e:
                    logger.debug("Redis aktive Szene setzen fehlgeschlagen: %s", e)

            # [8] Scene History tracken
            if redis:
                try:
                    import json as _json
                    import time as _time

                    entry = _json.dumps(
                        {
                            "scene": mood_key,
                            "label": mood.get("label", mood_key),
                            "person": getattr(self, "_current_person", ""),
                            "room": room,
                            "ts": _time.time(),
                        }
                    )
                    await redis.zadd("mha:scene:history", {entry: _time.time()})
                except Exception as e:
                    logger.debug("Scene-History Tracking fehlgeschlagen: %s", e)

            # [15] Inner-State: Szene beeinflusst Jarvis' Stimmung
            try:
                inner = getattr(self, "_brain", None)
                if inner:
                    inner = getattr(inner, "inner_state", None)
                if inner and hasattr(inner, "on_scene_activated"):
                    await inner.on_scene_activated(mood_key)
            except Exception as e:
                logger.debug("Inner-State Szenen-Update fehlgeschlagen: %s", e)

            # [16] Auto-Learning: Device→Scene Pattern tracken
            try:
                brain = getattr(self, "_brain", None)
                if brain and hasattr(brain, "learning_observer"):
                    observer = brain.learning_observer
                    if hasattr(observer, "observe_scene_activation"):
                        _person = getattr(self, "_current_person", "") or ""
                        task = asyncio.create_task(
                            observer.observe_scene_activation(mood_key, person=_person)
                        )
                        task.add_done_callback(
                            lambda t: t.exception() if not t.cancelled() else None
                        )
            except Exception as e:
                logger.debug("Auto-Learning Szenen-Beobachtung fehlgeschlagen: %s", e)

            # [6] Return-Message mit Error-Info
            msg = f"Stimmung '{mood.get('label', mood_key)}' aktiviert ({', '.join(actions_done)})"
            if errors:
                msg += f". {len(errors)} Fehler: {', '.join(errors[:3])}"
            return {"success": len(errors) == 0, "message": msg}

        # Fallback: Standard HA-Scene aktivieren
        entity_id = await self._find_entity("scene", scene)
        if not entity_id:
            entity_id = f"scene.{scene}"

        success = await self.ha.call_service(
            "scene", "turn_on", {"entity_id": entity_id}
        )
        return {"success": success, "message": f"Szene '{scene}' aktiviert"}

    async def _exec_deactivate_scene(self, args: dict) -> dict:
        """[5] Szene beenden und vorherigen Zustand wiederherstellen."""
        scene = args.get("scene", "")
        scene_key = scene.lower().replace(" ", "_").replace("-", "_")
        scene_key = self._MOOD_ALIASES.get(scene_key, scene_key)

        redis = getattr(self, "_redis", None)
        if not redis:
            return {"success": False, "message": "Kein Redis verfuegbar"}

        import json as _json

        try:
            raw = await redis.get(f"mha:scene:snapshot:{scene_key}")
        except Exception as e:
            logger.debug("Redis Szenen-Snapshot Abruf fehlgeschlagen: %s", e)
            raw = None
        if not raw:
            # Kein Snapshot — versuche aktive Szene zu beenden
            try:
                active = await redis.get("mha:scene:active")
                if active:
                    active = active.decode() if isinstance(active, bytes) else active
                    await redis.delete("mha:scene:active")
                    return {
                        "success": True,
                        "message": f"'{active}' als aktive Szene entfernt (kein Snapshot vorhanden)",
                    }
            except Exception as e:
                logger.debug("Redis aktive Szene entfernen fehlgeschlagen: %s", e)
            return {
                "success": False,
                "message": f"Kein Snapshot fuer '{scene}' vorhanden",
            }

        snapshot = _json.loads(raw if isinstance(raw, str) else raw.decode())
        restored = 0
        for item in snapshot:
            eid = item.get("entity_id", "")
            domain = eid.split(".")[0] if eid else ""
            try:
                if item.get("state") == "off":
                    await self.ha.call_service(domain, "turn_off", {"entity_id": eid})
                else:
                    svc_data = {"entity_id": eid}
                    if item.get("brightness") is not None:
                        svc_data["brightness"] = item["brightness"]
                    if item.get("color_temp") is not None:
                        svc_data["color_temp"] = item["color_temp"]
                    await self.ha.call_service(domain, "turn_on", svc_data)
                restored += 1
            except Exception as e:
                logger.warning("Scene-Undo Fehler bei %s: %s", eid, e)

        try:
            await redis.delete(f"mha:scene:snapshot:{scene_key}")
            await redis.delete("mha:scene:active")
            await redis.delete(f"mha:scene:cooldown:{scene_key}")
        except Exception as e:
            logger.debug("Redis Szenen-Cleanup fehlgeschlagen: %s", e)

        return {
            "success": True,
            "message": f"'{scene}' beendet — {restored} Geraete zurueckgesetzt",
        }

    # ── Phase 11: Cover-Steuerung (Rollladen + Markise) ──────
    # Garagentore und andere gefaehrliche Cover-Typen NIEMALS automatisch steuern
    _EXCLUDED_COVER_CLASSES = {"garage_door", "gate", "door"}

    async def _is_safe_cover(self, entity_id: str, state: dict) -> bool:
        """Prueft ob ein Cover sicher automatisch gesteuert werden darf."""
        attrs = state.get("attributes", {})
        device_class = attrs.get("device_class", "")
        if device_class in self._EXCLUDED_COVER_CLASSES:
            return False
        eid_lower = entity_id.lower()
        if "garage" in eid_lower or "gate" in eid_lower:
            return False
        if re.search(r"(?:^|[_.\-\s])tor(?:$|[_.\-\s])", eid_lower):
            return False
        try:
            from .cover_config import load_cover_configs

            configs = load_cover_configs()
            if configs and isinstance(configs, dict):
                conf = configs.get(entity_id, {})
                if conf.get("cover_type") in self._EXCLUDED_COVER_CLASSES:
                    return False
                if conf.get("enabled") is False:
                    return False
        except Exception as e:
            # Bei JSON-Ladefehler: Nur warnen, aber Cover nicht pauschal blockieren.
            # device_class und entity_id-Pattern-Checks oben reichen als Sicherheitsnetz.
            logger.warning(
                "CoverConfig laden fehlgeschlagen für %s: %s — erlaube basierend auf device_class/entity_id",
                entity_id,
                e,
            )
        return True

    def _is_markise(self, entity_id: str, state: dict) -> bool:
        """Prueft ob ein Cover eine Markise ist (entity_id, device_class oder cover_profiles)."""
        eid_lower = entity_id.lower()
        if "markise" in eid_lower or "awning" in eid_lower:
            return True
        # HA device_class pruefen
        attrs = state.get("attributes", {}) if isinstance(state, dict) else {}
        if attrs.get("device_class") == "awning":
            return True
        profiles = _get_room_profiles()
        for c in profiles.get("cover_profiles", {}).get("covers", []):
            if c.get("entity_id") == entity_id and c.get("type") == "markise":
                return True
        return False

    def _is_cover_inverted(self, entity_id: str) -> bool:
        """Prueft ob ein Cover invertierte Positionswerte hat.

        Manche HA-Integrationen (Shelly, MQTT) nutzen invertierte Semantik:
        Position 0 = offen (oben), Position 100 = geschlossen (unten).
        Jarvis nutzt: 0 = geschlossen, 100 = offen.

        Konfigurierbar pro Cover in cover_configs.json oder room_profiles.yaml.
        Global via settings.yaml > cover_automation > inverted_position.
        """
        # 1. Per-Cover Config (cover_configs.json)
        try:
            from .cover_config import load_cover_configs

            configs = load_cover_configs()
            if configs and isinstance(configs, dict):
                conf = configs.get(entity_id, {})
                if "inverted" in conf:
                    return bool(conf["inverted"])
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("Cover-Inversions-Check fehlgeschlagen: %s", e)

        # 2. Per-Cover in room_profiles.yaml
        profiles = _get_room_profiles()
        for c in profiles.get("cover_profiles", {}).get("covers", []):
            if c.get("entity_id") == entity_id and "inverted" in c:
                return bool(c["inverted"])

        # 3. Globale Einstellung (alle Covers invertiert)
        from .config import yaml_config

        cover_cfg = yaml_config.get("seasonal_actions", {}).get("cover_automation", {})
        return bool(cover_cfg.get("inverted_position", False))

    def _translate_cover_position(self, entity_id: str, position: int) -> int:
        """Übersetzt Jarvis-Position (0=zu, 100=offen) in HA-Position.

        Bei invertierten Covers wird 0↔100 getauscht.
        """
        if self._is_cover_inverted(entity_id):
            return 100 - position
        return position

    def _translate_cover_position_from_ha(self, entity_id: str, position: int) -> int:
        """Übersetzt HA-Position zurück in Jarvis-Position (0=zu, 100=offen)."""
        if self._is_cover_inverted(entity_id):
            return 100 - position
        return position

    def _resolve_cover_position(self, args: dict) -> tuple:
        """Bestimmt Position + Adjust aus action/state/adjust/position Args.

        Returns:
            (position: int | None, adjust: str | None, is_stop: bool)
        """
        _ACTION_TO_POS = {
            "open": 100,
            "close": 0,
            "half": 50,
            "auf": 100,
            "offen": 100,
            "hoch": 100,
            "up": 100,
            "closed": 0,
            "zu": 0,
            "runter": 0,
            "down": 0,
            "halb": 50,
        }
        action = str(args.get("action", "")).lower().strip()
        state_val = str(args.get("state", "")).lower().strip()
        effective = action or state_val

        if effective == "stop":
            return None, None, True

        adjust = args.get("adjust")
        if adjust in ("up", "down"):
            return None, adjust, False

        if effective in _ACTION_TO_POS and "position" not in args:
            return _ACTION_TO_POS[effective], None, False

        if "position" in args:
            try:
                return max(0, min(100, int(args.get("position", 0)))), None, False
            except (ValueError, TypeError):
                return 0, None, False

        return 0, None, False  # Fallback: close

    async def _exec_set_cover(self, args: dict) -> dict:
        room = args.get("room")
        cover_type = args.get("type")  # rollladen | markise | None

        # LLM-Fallback: entity_id statt room
        if not room and args.get("entity_id"):
            eid = args.get("entity_id", "")
            room = eid.split(".", 1)[1] if "." in eid else eid
        room = self._clean_room(room)

        if not room:
            return {"success": False, "message": "Kein Raum angegeben"}

        # Phase 11: Etagen-Steuerung (eg/og)
        if room.lower() in ("eg", "og"):
            return await self._exec_set_cover_floor(room.lower(), args, cover_type)

        # Phase 11: Markisen-Steuerung
        if room.lower() == "markisen" or cover_type == "markise":
            return await self._exec_set_cover_markisen(args)

        # "all" → alle Rollläden (keine Markisen, keine Garagentore)
        position, adjust, is_stop = self._resolve_cover_position(args)
        if room.lower() == "all":
            if is_stop:
                return await self._exec_set_cover_all_action("stop_cover")
            final_pos = position if position is not None else 0
            # Ohne expliziten Typ: nur Rollläden (Markisen haben eigene Sicherheits-Checks)
            effective_type = cover_type or "rollladen"
            return await self._exec_set_cover_all(final_pos, effective_type)

        # Einzelraum
        entity_id = await self._find_entity("cover", room)

        if is_stop:
            if not entity_id:
                return {
                    "success": False,
                    "message": f"Kein Rollladen in '{room}' gefunden",
                }
            states = await self.ha.get_states()
            entity_state = next(
                (s for s in (states or []) if s.get("entity_id") == entity_id), {}
            )
            if not await self._is_safe_cover(entity_id, entity_state):
                return {
                    "success": False,
                    "message": f"'{room}' ist ein Garagentor/Tor — nicht erlaubt.",
                }
            await self._mark_cover_jarvis_acting(entity_id)
            success = await self.ha.call_service(
                "cover", "stop_cover", {"entity_id": entity_id}
            )
            return {"success": success, "message": f"Rollladen {room} gestoppt"}

        # Relative Anpassung
        if adjust in ("up", "down"):
            if not entity_id:
                return {
                    "success": False,
                    "message": f"Kein Rollladen in '{room}' gefunden",
                }
            current_position = 50
            ha_state = await self.ha.get_state(entity_id)
            if ha_state:
                try:
                    ha_pos = int(
                        ha_state.get("attributes", {}).get("current_position", 50)
                    )
                    # HA-Position in Jarvis-Position übersetzen (0=zu, 100=offen)
                    current_position = self._translate_cover_position_from_ha(
                        entity_id, ha_pos
                    )
                except (ValueError, TypeError):
                    current_position = 50
            step = 20
            position = (
                current_position + step if adjust == "up" else current_position - step
            )
            position = max(0, min(100, position))

        if position is None:
            position = 0

        if not entity_id:
            try:
                all_states = await self.ha.get_states()
                available = [
                    s.get("entity_id")
                    for s in (all_states or [])
                    if s.get("entity_id", "").startswith("cover.")
                ]
            except Exception as e:
                if isinstance(e, asyncio.CancelledError):
                    raise
                available = []
            return {
                "success": False,
                "message": f"Kein Rollladen in '{room}' gefunden. Verfügbar: {', '.join(available) if available else 'keine'}",
            }

        # Sicherheitscheck
        states = await self.ha.get_states()
        entity_state = next(
            (s for s in (states or []) if s.get("entity_id") == entity_id), {}
        )
        if not await self._is_safe_cover(entity_id, entity_state):
            return {
                "success": False,
                "message": f"'{room}' ist ein Garagentor/Tor — nicht erlaubt.",
            }

        ha_position = self._translate_cover_position(entity_id, position)
        await self._mark_cover_jarvis_acting(entity_id)
        success = await self.ha.call_service(
            "cover",
            "set_cover_position",
            {"entity_id": entity_id, "position": ha_position},
        )
        direction = ""
        if adjust == "up":
            direction = "hoch auf "
        elif adjust == "down":
            direction = "runter auf "
        label = "Markise" if self._is_markise(entity_id, entity_state) else "Rollladen"
        return {"success": success, "message": f"{label} {room} {direction}{position}%"}

    async def _exec_set_cover_floor(
        self, floor: str, args: dict, cover_type: str = None
    ) -> dict:
        """Alle Rollläden/Markisen einer Etage steuern."""
        profiles = _get_room_profiles()
        floor_rooms = [
            r
            for r, cfg in profiles.get("rooms", {}).items()
            if cfg.get("floor") == floor
        ]
        if not floor_rooms:
            return {
                "success": False,
                "message": f"Keine Räume für Etage '{floor.upper()}' konfiguriert",
            }

        position, adjust, is_stop = self._resolve_cover_position(args)
        if position is None and not is_stop and adjust is None:
            position = 0

        states = await self.ha.get_states()
        if not states:
            return {
                "success": False,
                "message": "Die Geräte reagieren gerade nicht. Einen Moment.",
            }

        count = 0
        last_pos = position  # Track actual position for message
        for room_name in floor_rooms:
            for s in states:
                eid = s.get("entity_id", "")
                if not eid.startswith("cover."):
                    continue
                friendly = (s.get("attributes", {}).get("friendly_name") or eid).lower()
                room_lower = room_name.lower().replace("_", " ")
                if room_lower not in friendly and room_name not in eid.lower():
                    continue
                if not await self._is_safe_cover(eid, s):
                    continue
                # Typ-Filter: nur Rollläden oder nur Markisen
                if cover_type == "markise" and not self._is_markise(eid, s):
                    continue
                if cover_type == "rollladen" and self._is_markise(eid, s):
                    continue

                await self._mark_cover_jarvis_acting(eid)
                if is_stop:
                    await self.ha.call_service(
                        "cover", "stop_cover", {"entity_id": eid}
                    )
                elif adjust in ("up", "down"):
                    # Relative Anpassung pro Cover
                    current_position = 50
                    try:
                        ha_pos = int(
                            s.get("attributes", {}).get("current_position", 50)
                        )
                        current_position = self._translate_cover_position_from_ha(
                            eid, ha_pos
                        )
                    except (ValueError, TypeError):
                        current_position = 50
                    step = 20
                    final_pos = (
                        current_position + step
                        if adjust == "up"
                        else current_position - step
                    )
                    final_pos = max(0, min(100, final_pos))
                    last_pos = final_pos
                    ha_pos = self._translate_cover_position(eid, final_pos)
                    await self.ha.call_service(
                        "cover",
                        "set_cover_position",
                        {"entity_id": eid, "position": ha_pos},
                    )
                else:
                    final_pos = position if position is not None else 0
                    last_pos = final_pos
                    ha_pos = self._translate_cover_position(eid, final_pos)
                    await self.ha.call_service(
                        "cover",
                        "set_cover_position",
                        {"entity_id": eid, "position": ha_pos},
                    )
                count += 1

        if is_stop:
            action_str = "gestoppt"
        elif adjust == "up":
            action_str = "hoch angepasst"
        elif adjust == "down":
            action_str = "runter angepasst"
        else:
            action_str = f"auf {last_pos}%"
        return {
            "success": count > 0,
            "message": f"{count} Rollläden im {floor.upper()} {action_str}",
        }

    async def _exec_set_cover_markisen(self, args: dict) -> dict:
        """Alle Markisen steuern — mit eigenen Wind/Regen-Sicherheits-Checks."""
        states = await self.ha.get_states()
        if not states:
            return {
                "success": False,
                "message": "Die Geräte reagieren gerade nicht. Einen Moment.",
            }

        position, adjust, is_stop = self._resolve_cover_position(args)

        # Sicherheits-Check: Bei Wind/Regen Markisen nicht ausfahren
        # Gilt auch bei adjust="up" (oeffnet Markise weiter)
        wants_open = (position is not None and position > 0) or adjust == "up"
        if wants_open and not is_stop:
            profiles = _get_room_profiles()
            markise_cfg = profiles.get("markisen", {})
            wind_limit = markise_cfg.get("wind_retract_speed", 40)
            rain_retract = markise_cfg.get("rain_retract", True)

            for s in states:
                eid = s.get("entity_id", "")
                if eid.startswith("weather."):
                    attrs = s.get("attributes", {})
                    try:
                        wind = float(attrs.get("wind_speed", 0))
                    except (ValueError, TypeError):
                        wind = 0
                    condition = s.get("state", "")
                    if wind >= wind_limit:
                        return {
                            "success": False,
                            "message": f"Markise NICHT ausgefahren — Wind {wind} km/h (Limit: {wind_limit} km/h)",
                        }
                    if rain_retract and condition in (
                        "rainy",
                        "pouring",
                        "hail",
                        "lightning-rainy",
                    ):
                        return {
                            "success": False,
                            "message": f"Markise NICHT ausgefahren — Wetter: {condition}",
                        }
                    break

        count = 0
        last_pos = position  # Track actual position for message
        for s in states:
            eid = s.get("entity_id", "")
            if not eid.startswith("cover."):
                continue
            if not self._is_markise(eid, s):
                continue
            await self._mark_cover_jarvis_acting(eid)
            if is_stop:
                await self.ha.call_service("cover", "stop_cover", {"entity_id": eid})
            elif adjust in ("up", "down"):
                # Relative Anpassung pro Markise
                current_position = 50
                try:
                    ha_pos = int(s.get("attributes", {}).get("current_position", 50))
                    current_position = self._translate_cover_position_from_ha(
                        eid, ha_pos
                    )
                except (ValueError, TypeError):
                    current_position = 50
                step = 20
                final_pos = (
                    current_position + step
                    if adjust == "up"
                    else current_position - step
                )
                final_pos = max(0, min(100, final_pos))
                last_pos = final_pos
                ha_pos = self._translate_cover_position(eid, final_pos)
                await self.ha.call_service(
                    "cover",
                    "set_cover_position",
                    {"entity_id": eid, "position": ha_pos},
                )
            else:
                final_pos = position if position is not None else 0
                last_pos = final_pos
                ha_pos = self._translate_cover_position(eid, final_pos)
                await self.ha.call_service(
                    "cover",
                    "set_cover_position",
                    {"entity_id": eid, "position": ha_pos},
                )
            count += 1

        if count == 0:
            return {"success": False, "message": "Keine Markisen gefunden"}
        if is_stop:
            action_str = "gestoppt"
        elif adjust == "up":
            action_str = "hoch angepasst"
        elif adjust == "down":
            action_str = "runter angepasst"
        else:
            action_str = f"auf {last_pos}%"
        return {"success": True, "message": f"{count} Markise(n) {action_str}"}

    async def _exec_set_cover_all(self, position: int, cover_type: str = None) -> dict:
        """Alle Rollläden auf eine Position setzen (Garagentore ausgeschlossen)."""
        states = await self.ha.get_states()
        if not states:
            return {
                "success": False,
                "message": "Die Geräte reagieren gerade nicht. Einen Moment.",
            }

        count = 0
        skipped = []
        # Bulk-Op: Dependency-Check ueberspringen — wird bereits vom Executor geprueft
        self.ha._skip_dep_check_depth = getattr(self.ha, "_skip_dep_check_depth", 0) + 1
        try:
            for s in states:
                eid = s.get("entity_id", "")
                if not eid.startswith("cover."):
                    continue
                if not is_entity_annotated(eid) or is_entity_hidden(eid):
                    continue
                if not await self._is_safe_cover(eid, s):
                    skipped.append(s.get("attributes", {}).get("friendly_name", eid))
                    continue
                # Typ-Filter
                if cover_type == "rollladen" and self._is_markise(eid, s):
                    continue
                if cover_type == "markise" and not self._is_markise(eid, s):
                    continue
                ha_pos = self._translate_cover_position(eid, position)
                await self._mark_cover_jarvis_acting(eid)
                await self.ha.call_service(
                    "cover",
                    "set_cover_position",
                    {"entity_id": eid, "position": ha_pos},
                )
                count += 1
        finally:
            self.ha._skip_dep_check_depth = max(
                0, getattr(self.ha, "_skip_dep_check_depth", 1) - 1
            )

        msg = f"Alle Rollläden auf {position}% ({count} geschaltet)"
        if skipped:
            msg += f". Übersprungen: {', '.join(skipped)}"
        return {"success": True, "message": msg}

    async def _exec_set_cover_all_action(self, service: str) -> dict:
        """Alle Rollläden: stop_cover etc."""
        states = await self.ha.get_states()
        if not states:
            return {
                "success": False,
                "message": "Die Geräte reagieren gerade nicht. Einen Moment.",
            }
        count = 0
        self.ha._skip_dep_check_depth = getattr(self.ha, "_skip_dep_check_depth", 0) + 1
        try:
            for s in states:
                eid = s.get("entity_id", "")
                if not eid.startswith("cover."):
                    continue
                if not is_entity_annotated(eid) or is_entity_hidden(eid):
                    continue
                if not await self._is_safe_cover(eid, s):
                    continue
                await self._mark_cover_jarvis_acting(eid)
                await self.ha.call_service("cover", service, {"entity_id": eid})
                count += 1
        finally:
            self.ha._skip_dep_check_depth = max(
                0, getattr(self.ha, "_skip_dep_check_depth", 1) - 1
            )
        return {"success": True, "message": f"{count} Rollläden: {service}"}

    # ── Cover-Automatik Konfiguration ──────────────────────

    async def _exec_configure_cover_automation(self, args: dict) -> dict:
        """Cover-Automatik Settings lesen/schreiben (inkl. Wetter-Integration)."""
        action = args.get("action", "get")

        cover_cfg = yaml_config.get("seasonal_actions", {}).get("cover_automation", {})

        if action == "get":
            # Welche weather-Entity wird aktuell genutzt?
            configured = cover_cfg.get("weather_entity", "")
            if not configured:
                # Auto-Detection: schauen welche weather-Entity existiert
                states = await self.ha.get_states()
                for s in states or []:
                    eid = s.get("entity_id", "")
                    if eid == "weather.forecast_home":
                        configured = eid
                        break
                    if eid.startswith("weather.") and not configured:
                        configured = eid
                configured = configured or "(keine weather-Entity gefunden)"

            return {
                "success": True,
                "settings": {
                    "weather_entity": cover_cfg.get("weather_entity", "")
                    or f"auto ({configured})",
                    "weather_protection": cover_cfg.get("weather_protection", True),
                    "forecast_weather_protection": cover_cfg.get(
                        "forecast_weather_protection", True
                    ),
                    "forecast_lookahead_hours": cover_cfg.get(
                        "forecast_lookahead_hours", 4
                    ),
                    "sun_tracking": cover_cfg.get("sun_tracking", True),
                    "temperature_based": cover_cfg.get("temperature_based", True),
                    "heat_protection_temp": cover_cfg.get("heat_protection_temp", 26),
                    "frost_protection_temp": cover_cfg.get("frost_protection_temp", 3),
                    "storm_wind_speed": cover_cfg.get("storm_wind_speed", 50),
                    "wakeup_sun_check": cover_cfg.get("wakeup_sun_check", True),
                    "wakeup_min_sun_elevation": cover_cfg.get(
                        "wakeup_min_sun_elevation", -6
                    ),
                    "wakeup_fallback_max_minutes": cover_cfg.get(
                        "wakeup_fallback_max_minutes", 120
                    ),
                    "night_insulation": cover_cfg.get("night_insulation", True),
                    "night_start_hour": cover_cfg.get("night_start_hour", 22),
                    "night_end_hour": cover_cfg.get("night_end_hour", 6),
                    "presence_simulation": cover_cfg.get("presence_simulation", True),
                    "inverted_position": cover_cfg.get("inverted_position", False),
                    "hysteresis_temp": cover_cfg.get("hysteresis_temp", 2),
                    "hysteresis_wind": cover_cfg.get("hysteresis_wind", 10),
                    "glare_protection": cover_cfg.get("glare_protection", False),
                    "gradual_morning": cover_cfg.get("gradual_morning", False),
                    "wave_open": cover_cfg.get("wave_open", False),
                    "heating_integration": cover_cfg.get("heating_integration", False),
                    "co2_ventilation": cover_cfg.get("co2_ventilation", False),
                    "privacy_mode": cover_cfg.get("privacy_mode", False),
                    "privacy_close_hour": cover_cfg.get("privacy_close_hour", None),
                    "presence_aware": cover_cfg.get("presence_aware", False),
                    "manual_override_hours": cover_cfg.get("manual_override_hours", 2),
                },
            }

        # action == "set"
        import yaml as _yaml

        SETTINGS_PATH = Path("/app/config/settings.yaml")

        ALLOWED_KEYS = {
            "weather_entity",
            "weather_protection",
            "forecast_weather_protection",
            "forecast_lookahead_hours",
            "sun_tracking",
            "temperature_based",
            "heat_protection_temp",
            "frost_protection_temp",
            "storm_wind_speed",
            "wakeup_sun_check",
            "wakeup_min_sun_elevation",
            "wakeup_fallback_max_minutes",
            "night_insulation",
            "night_start_hour",
            "night_end_hour",
            "presence_simulation",
            "inverted_position",
            "hysteresis_temp",
            "hysteresis_wind",
            "glare_protection",
            "gradual_morning",
            "wave_open",
            "heating_integration",
            "co2_ventilation",
            "privacy_mode",
            "privacy_close_hour",
            "presence_aware",
            "manual_override_hours",
        }

        changes = {}
        for key in ALLOWED_KEYS:
            if key in args:
                changes[key] = args[key]

        if not changes:
            return {
                "success": False,
                "message": "Keine aenderbaren Einstellungen angegeben.",
            }

        # Validierung weather_entity
        if "weather_entity" in changes:
            we = changes["weather_entity"]
            if we and not we.startswith("weather."):
                return {
                    "success": False,
                    "message": f"Ungültige Weather-Entity: '{we}'. Muss mit 'weather.' beginnen.",
                }

        try:
            import fcntl

            def _locked_yaml_update():
                with open(SETTINGS_PATH, "r+") as f:
                    fcntl.flock(f, fcntl.LOCK_EX)
                    try:
                        f.seek(0)
                        config = _yaml.safe_load(f.read()) or {}
                        if "seasonal_actions" not in config:
                            config["seasonal_actions"] = {}
                        if "cover_automation" not in config["seasonal_actions"]:
                            config["seasonal_actions"]["cover_automation"] = {}

                        for k, v in changes.items():
                            config["seasonal_actions"]["cover_automation"][k] = v

                        f.seek(0)
                        f.truncate()
                        _yaml.safe_dump(
                            config,
                            f,
                            allow_unicode=True,
                            default_flow_style=False,
                            sort_keys=False,
                        )
                    finally:
                        fcntl.flock(f, fcntl.LOCK_UN)

            await asyncio.to_thread(_locked_yaml_update)

            # In-Memory Config aktualisieren
            import assistant.config as _cfg

            _ca = _cfg.yaml_config.get("seasonal_actions", {})
            if "cover_automation" not in _ca:
                _ca["cover_automation"] = {}
            _ca["cover_automation"].update(changes)

            # Beschreibung für Antwort
            desc_parts = []
            _labels = {
                "weather_entity": "Wetter-Entity",
                "weather_protection": "Wetterschutz",
                "forecast_weather_protection": "Vorhersage-Schutz",
                "forecast_lookahead_hours": "Vorhersage-Zeitraum",
                "sun_tracking": "Sonnenstand-Tracking",
                "temperature_based": "Temperatur-Steuerung",
                "heat_protection_temp": "Hitzeschutz-Temp",
                "frost_protection_temp": "Frostschutz-Temp",
                "storm_wind_speed": "Sturmschutz-Wind",
                "wakeup_sun_check": "Aufwach-Sonnenpruefung",
                "wakeup_min_sun_elevation": "Min. Sonnenhoehe",
                "wakeup_fallback_max_minutes": "Aufwach-Fallback (Min.)",
                "night_insulation": "Nacht-Isolation",
                "night_start_hour": "Nacht-Start (Stunde)",
                "night_end_hour": "Nacht-Ende (Stunde)",
                "presence_simulation": "Anwesenheitssimulation",
                "inverted_position": "Invertierte Position",
                "hysteresis_temp": "Hysterese Temperatur",
                "hysteresis_wind": "Hysterese Wind",
                "glare_protection": "Blendschutz",
                "gradual_morning": "Schrittweises Oeffnen",
                "wave_open": "Wellen-Oeffnung",
                "heating_integration": "Heizungs-Integration",
                "co2_ventilation": "CO2-Lueftung",
                "privacy_mode": "Sichtschutz-Modus",
                "privacy_close_hour": "Privacy ab Uhrzeit",
                "presence_aware": "Anwesenheits-Erkennung",
                "manual_override_hours": "Manueller Override (Std.)",
            }
            for k, v in changes.items():
                label = _labels.get(k, k)
                if isinstance(v, bool):
                    desc_parts.append(f"{label}: {'an' if v else 'aus'}")
                else:
                    desc_parts.append(f"{label}: {v}")

            return {
                "success": True,
                "message": f"Cover-Automatik aktualisiert: {', '.join(desc_parts)}",
                "changes": changes,
            }
        except Exception as e:
            logger.error("Fehler beim Speichern: %s", e)
            return {
                "success": False,
                "message": "Fehler beim Speichern der Einstellungen.",
            }

    # ── Phase 11: Saugroboter (Dreame, 2 Etagen) ──────────

    @staticmethod
    def _normalize_room_key(room: str) -> str:
        """Normalisiert Raumnamen für Config-Lookup (Umlaute, Leerzeichen, Case)."""
        r = room.lower().strip()
        r = (
            r.replace("ä", "ae")
            .replace("ö", "oe")
            .replace("ü", "ue")
            .replace("ß", "ss")
        )
        r = r.replace(" ", "_")
        return r

    def _resolve_vacuum_room(self, room: str, robots: dict) -> tuple:
        """Findet den richtigen Roboter + Segment-ID für einen Raum.

        Returns:
            (robot_config: dict | None, segment_id: int | None)
        """
        room_norm = self._normalize_room_key(room)
        # Direkte Zuordnung: Raum in robots.{floor}.rooms (exakt oder normalisiert)
        for floor, robot in robots.items():
            rooms_map = robot.get("rooms", {})
            # Exakter Match
            if room in rooms_map:
                return robot, rooms_map[room]
            # Normalisierter Match (Umlaute, Case)
            if room_norm in rooms_map:
                return robot, rooms_map[room_norm]
            # Fuzzy: Config-Keys auch normalisieren
            for cfg_key, seg_id in rooms_map.items():
                if self._normalize_room_key(cfg_key) == room_norm:
                    return robot, seg_id
        # Fallback: Raum-Profil → floor → Roboter (OHNE Segment)
        _cfg_dir = Path(__file__).parent.parent / "config"
        try:
            with open(_cfg_dir / "room_profiles.yaml") as f:
                profiles = yaml.safe_load(f) or {}
        except Exception as e:
            if isinstance(e, asyncio.CancelledError):
                raise
            profiles = {}
        room_floor = profiles.get("rooms", {}).get(room, {}).get("floor")
        if not room_floor:
            # Auch normalisiert versuchen
            for rname, rdata in profiles.get("rooms", {}).items():
                if self._normalize_room_key(rname) == room_norm:
                    room_floor = rdata.get("floor")
                    break
        if room_floor and room_floor in robots:
            return robots[room_floor], None
        return None, None

    # Fan-Speed Mapping: Deutsche Begriffe → HA fan_speed Werte
    _FAN_SPEED_MAP = {
        "quiet": "quiet",
        "leise": "quiet",
        "silent": "quiet",
        "standard": "standard",
        "normal": "standard",
        "strong": "strong",
        "stark": "strong",
        "medium": "strong",
        "turbo": "turbo",
        "max": "turbo",
        "voll": "turbo",
        "maximal": "turbo",
    }

    # Reinigungsmodus Mapping
    _CLEAN_MODE_MAP = {
        "vacuum": "sweeping",
        "saugen": "sweeping",
        "mop": "mopping",
        "wischen": "mopping",
        "vacuum_and_mop": "sweeping_and_mopping",
        "beides": "sweeping_and_mopping",
    }

    async def _set_vacuum_fan_speed(self, entity_id: str, fan_speed: str) -> bool:
        """Setzt die Saugstaerke vor dem Start."""
        if not fan_speed or fan_speed.lower() not in self._FAN_SPEED_MAP:
            logger.warning("Unbekannte fan_speed '%s', ueberspringe", fan_speed)
            return False
        resolved = self._FAN_SPEED_MAP.get(fan_speed.lower(), fan_speed)
        return await self.ha.call_service(
            "vacuum",
            "set_fan_speed",
            {
                "entity_id": entity_id,
                "fan_speed": resolved,
            },
        )

    async def _set_vacuum_mode(self, entity_id: str, mode: str) -> bool:
        """Setzt den Reinigungsmodus (saugen/wischen/beides) via select-Entity."""
        if not mode or mode.lower() not in self._CLEAN_MODE_MAP:
            logger.warning("Unbekannter Reinigungsmodus '%s', ueberspringe", mode)
            return False
        resolved = self._CLEAN_MODE_MAP.get(mode.lower(), mode)
        # Offizielle Dreame-Integration: select.{name}_cleaning_mode
        # Entity-ID aus vacuum entity ableiten
        base = entity_id.replace("vacuum.", "")
        select_eid = f"select.{base}_cleaning_mode"
        success = await self.ha.call_service(
            "select",
            "select_option",
            {
                "entity_id": select_eid,
                "option": resolved,
            },
        )
        if not success:
            # Fallback: number/select mit anderem Naming
            select_eid2 = f"select.{base}_mop_mode"
            success = await self.ha.call_service(
                "select",
                "select_option",
                {
                    "entity_id": select_eid2,
                    "option": resolved,
                },
            )
        return success

    async def _track_vacuum_clean(self, floor: str, room: str = "") -> None:
        """Speichert den Reinigungszeitpunkt in Redis für den Verlauf."""
        try:
            redis = getattr(self, "_redis", None)
            if not redis:
                _mem = getattr(self, "memory", None) or getattr(
                    getattr(self, "brain", None), "memory", None
                )
                redis = getattr(_mem, "redis", None) if _mem else None
            if not redis:
                return
            import time as _time

            key = f"mha:vacuum:{floor}:last_clean"
            if room:
                key = f"mha:vacuum:{floor}:room:{room}:last_clean"
            await redis.set(key, str(int(_time.time())), ex=86400 * 7)  # 7 Tage TTL
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Vacuum cleanup tracking fehlgeschlagen: %s", e)

    async def _exec_set_vacuum(self, args: dict) -> dict:
        """Saugroboter steuern — waehlt automatisch EG/OG-Roboter.

        Unterstuetzt offizielle Dreame-Integration:
        - Saugstaerke (fan_speed): quiet/standard/strong/turbo
        - Reinigungsmodus: vacuum/mop/vacuum_and_mop
        - Raum-spezifisches Saugen via Segment-IDs
        - Wiederholungen (repeat=1-3)
        """
        action = args.get("action", "start")
        room = self._clean_room(args.get("room"))
        fan_speed = args.get("fan_speed", "")
        mode = args.get("mode", "")
        try:
            repeat = int(min(max(int(args.get("repeat", 1)), 1), 3))
        except (ValueError, TypeError):
            repeat = 1
        vacuum_cfg = yaml_config.get("vacuum", {})
        if not vacuum_cfg.get("enabled", True):
            return {
                "success": False,
                "message": "Saugroboter-Steuerung ist deaktiviert",
            }
        robots = vacuum_cfg.get("robots", {})
        if not robots:
            return {
                "success": False,
                "message": "Keine Saugroboter konfiguriert (settings.yaml → vacuum.robots)",
            }

        _VALID_ACTIONS = {"start", "stop", "pause", "dock", "clean_room"}
        if action not in _VALID_ACTIONS:
            return {
                "success": False,
                "message": f"Unbekannte Aktion '{action}'. Erlaubt: {', '.join(sorted(_VALID_ACTIONS))}",
            }

        # Stop/Pause/Dock → alle Roboter (kein fan_speed/mode noetig)
        if action in ("stop", "pause", "dock"):
            service_map = {"stop": "stop", "pause": "pause", "dock": "return_to_base"}
            service = service_map[action]
            results = []
            for floor, robot in robots.items():
                eid = robot.get("entity_id")
                if eid:
                    success = await self.ha.call_service(
                        "vacuum", service, {"entity_id": eid}
                    )
                    results.append(success)
            if not results:
                return {
                    "success": False,
                    "message": "Keine Saugroboter mit entity_id konfiguriert",
                }
            action_de = {
                "stop": "gestoppt",
                "pause": "pausiert",
                "dock": "zur Ladestation",
            }
            return {
                "success": any(results),
                "message": f"Saugroboter {action_de.get(action, action)}",
            }

        # --- Ab hier: Start/Clean --- Vorbereitungen (fan_speed + mode) ---

        async def _prepare_robot(entity_id: str):
            """Fan-Speed und Modus setzen bevor der Roboter startet."""
            if fan_speed:
                await self._set_vacuum_fan_speed(entity_id, fan_speed)
            if mode:
                await self._set_vacuum_mode(entity_id, mode)

        # Raum-genaues Saugen (clean_room ODER start mit Raum-Angabe)
        if (
            action in ("clean_room", "start")
            and room
            and room.lower() not in ("eg", "og")
        ):
            robot, segment_id = self._resolve_vacuum_room(room, robots)
            if not robot:
                return {
                    "success": False,
                    "message": f"Kein Saugroboter für '{room}' konfiguriert",
                }
            entity_id = robot.get("entity_id")
            if not entity_id:
                return {
                    "success": False,
                    "message": "Keine entity_id für Saugroboter konfiguriert",
                }
            nickname = robot.get("nickname", "der Kleine")

            if segment_id is not None:
                # Segment-ID als int sicherstellen (Dreame/Roborock erwarten int)
                try:
                    segment_id = int(segment_id)
                except (ValueError, TypeError):
                    return {
                        "success": False,
                        "message": f"Segment-ID '{segment_id}' ist keine gueltige Zahl",
                    }
                await _prepare_robot(entity_id)
                # Offizielle Dreame-Integration: vacuum.send_command
                # Tasshack-Fallback: dreame_vacuum.vacuum_clean_segment
                success = await self.ha.call_service(
                    "vacuum",
                    "send_command",
                    {
                        "entity_id": entity_id,
                        "command": "app_segment_clean",
                        "params": {"segments": [segment_id], "repeat": repeat},
                    },
                )
                if not success:
                    # Fallback: Tasshack-Service
                    success = await self.ha.call_service(
                        "dreame_vacuum",
                        "vacuum_clean_segment",
                        {
                            "entity_id": entity_id,
                            "segments": [segment_id],
                            "repeat": repeat,
                        },
                    )
                if not success:
                    # Letzter Fallback: params als Liste (aeltere Roborock/Miio)
                    success = await self.ha.call_service(
                        "vacuum",
                        "send_command",
                        {
                            "entity_id": entity_id,
                            "command": "app_segment_clean",
                            "params": [segment_id],
                        },
                    )
                if success:
                    await self._track_vacuum_clean(robot.get("floor", "?"), room)
                _mode_hint = ""
                if mode:
                    _modes_de = {
                        "vacuum": "saugt",
                        "mop": "wischt",
                        "vacuum_and_mop": "saugt+wischt",
                    }
                    _mode_hint = f" ({_modes_de.get(mode, mode)})"
                _repeat_hint = f" ({repeat}x)" if repeat > 1 else ""
                return {
                    "success": success,
                    "message": f"{nickname}{_mode_hint} {room}{_repeat_hint}",
                }
            else:
                _floor = robot.get("floor", "?")
                return {
                    "success": False,
                    "message": (
                        f"Raum '{room}' hat keine Segment-ID. Ohne Segment-ID würde der "
                        f"komplette Roboter starten und das ganze Stockwerk saugen. "
                        f"In settings.yaml unter vacuum.robots.{_floor}.rooms die Segment-ID "
                        f"für '{room}' eintragen."
                    ),
                }

        # Ganzes Stockwerk (explizit "sauge EG" / "sauge OG")
        if action == "start" and room and room.lower() in ("eg", "og"):
            robot = robots.get(room.lower())
            if not robot or not robot.get("entity_id"):
                return {
                    "success": False,
                    "message": f"Kein Roboter für {room.upper()} konfiguriert",
                }
            eid = robot["entity_id"]
            await _prepare_robot(eid)
            success = await self.ha.call_service("vacuum", "start", {"entity_id": eid})
            if success:
                await self._track_vacuum_clean(room.lower())
            return {
                "success": success,
                "message": f"{robot.get('nickname', 'Saugroboter')} startet im {room.upper()}",
            }

        # Start ohne Raum → alle starten
        results = []
        names = []
        for floor, robot in robots.items():
            eid = robot.get("entity_id")
            if eid:
                await _prepare_robot(eid)
                success = await self.ha.call_service(
                    "vacuum", "start", {"entity_id": eid}
                )
                results.append(success)
                names.append(robot.get("nickname", f"Roboter {floor.upper()}"))
                if success:
                    await self._track_vacuum_clean(floor)
        if not results:
            return {
                "success": False,
                "message": "Keine Saugroboter mit entity_id konfiguriert",
            }
        return {"success": any(results), "message": f"{', '.join(names)} gestartet"}

    async def _exec_get_vacuum(self, args: dict) -> dict:
        """Status aller Saugroboter abfragen — inkl. Reinigungsverlauf und Wartung."""
        vacuum_cfg = yaml_config.get("vacuum", {})
        robots = vacuum_cfg.get("robots", {})
        if not robots:
            return {"success": False, "message": "Keine Saugroboter konfiguriert"}

        # Redis für Reinigungsverlauf
        redis = None
        try:
            _mem = getattr(self, "memory", None) or getattr(
                getattr(self, "brain", None), "memory", None
            )
            redis = getattr(_mem, "redis", None) if _mem else None
        except Exception as e:
            if isinstance(e, asyncio.CancelledError):
                raise
            logger.warning("Vacuum-Status: Redis-Zugriff fehlgeschlagen: %s", e)

        status_list = []
        for floor, robot in robots.items():
            entity_id = robot.get("entity_id")
            if not entity_id:
                status_list.append(
                    {
                        "name": robot.get("name", f"Saugroboter {floor.upper()}"),
                        "floor": floor.upper(),
                        "state": "nicht konfiguriert (entity_id fehlt)",
                    }
                )
                continue
            state = await self.ha.get_state(entity_id)
            if state:
                attrs = state.get("attributes", {})
                _state_de = {
                    "cleaning": "saugt gerade",
                    "docked": "an Ladestation",
                    "returning": "faehrt zur Ladestation",
                    "paused": "pausiert",
                    "idle": "bereit",
                    "error": "FEHLER",
                }
                entry = {
                    "name": robot.get("name", f"Saugroboter {floor.upper()}"),
                    "nickname": robot.get("nickname", ""),
                    "floor": floor.upper(),
                    "state": _state_de.get(
                        state.get("state", ""), state.get("state", "unknown")
                    ),
                    "battery": f"{attrs.get('battery_level', '?')}%",
                }
                # Aktuelle Saugstaerke
                fan_speed = attrs.get("fan_speed")
                if fan_speed:
                    entry["saugstaerke"] = fan_speed
                # Aktuelle Reinigungsfläche (laufender Durchgang)
                if attrs.get("total_clean_area"):
                    entry["gereinigt_m2"] = attrs["total_clean_area"]
                if attrs.get("cleaning_time"):
                    entry["reinigungszeit_min"] = attrs["cleaning_time"]
                # Fehlermeldung
                status_raw = attrs.get("status")
                if status_raw and "error" in str(status_raw).lower():
                    entry["fehler"] = status_raw
                # Verfügbare Saugstaerken
                fan_speeds = attrs.get("fan_speed_list")
                if fan_speeds:
                    entry["verfügbare_stufen"] = fan_speeds
                # Wartungszustand
                maint = {}
                for key, label in [
                    ("filter_left", "Filter"),
                    ("filter_life_left", "Filter"),
                    ("main_brush_left", "Hauptbuerste"),
                    ("main_brush_life_left", "Hauptbuerste"),
                    ("side_brush_left", "Seitenbuerste"),
                    ("side_brush_life_left", "Seitenbuerste"),
                    ("mop_left", "Mopp"),
                    ("mop_life_left", "Mopp"),
                    ("sensor_dirty_left", "Sensoren"),
                ]:
                    val = attrs.get(key)
                    if val is not None and label not in maint:
                        try:
                            val_int = int(val)
                            maint[label] = f"{val_int}%"
                            if val_int < 15:
                                maint[label] += " ⚠ WECHSELN"
                        except (ValueError, TypeError):
                            maint[label] = str(val)
                if maint:
                    entry["wartung"] = maint

                # Reinigungsverlauf aus Redis
                if redis:
                    try:
                        last_clean = await redis.get(f"mha:vacuum:{floor}:last_clean")
                        if last_clean:
                            import time as _time

                            ago_sec = int(_time.time()) - int(last_clean)
                            if ago_sec < 3600:
                                entry["letzter_lauf"] = f"vor {ago_sec // 60} Minuten"
                            elif ago_sec < 86400:
                                entry["letzter_lauf"] = f"vor {ago_sec // 3600} Stunden"
                            else:
                                entry["letzter_lauf"] = f"vor {ago_sec // 86400} Tagen"
                        # Raum-spezifischer Verlauf
                        rooms_map = robot.get("rooms", {})
                        room_history = {}
                        for rname in rooms_map:
                            last_room = await redis.get(
                                f"mha:vacuum:{floor}:room:{rname}:last_clean"
                            )
                            if last_room:
                                import time as _time

                                ago = int(_time.time()) - int(last_room)
                                if ago < 86400:
                                    room_history[rname] = f"vor {ago // 3600}h"
                                else:
                                    room_history[rname] = f"vor {ago // 86400}d"
                        if room_history:
                            entry["raum_verlauf"] = room_history
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.warning("Vacuum-Raumverlauf Fehler: %s", e)

                status_list.append(entry)
            else:
                status_list.append(
                    {
                        "name": robot.get("name", f"Saugroboter {floor.upper()}"),
                        "floor": floor.upper(),
                        "state": "nicht erreichbar",
                    }
                )

        return {"success": True, "robots": status_list}

    # Erlaubte Service-Data Keys für _exec_call_service (Whitelist)
    _CALL_SERVICE_ALLOWED_KEYS = frozenset(
        {
            "brightness",
            "brightness_pct",
            "color_temp",
            "rgb_color",
            "hs_color",
            "effect",
            "color_name",
            "transition",
            "temperature",
            "target_temp_high",
            "target_temp_low",
            "hvac_mode",
            "fan_mode",
            "swing_mode",
            "preset_mode",
            "humidity",
            "target_humidity",
            "mode",
            "position",
            "tilt_position",
            "volume_level",
            "media_content_id",
            "media_content_type",
            "source",
            "message",
            "title",
            "data",
            "option",
            "value",
            "code",
        }
    )

    # Fix: lock und alarm_control_panel aus generischem Gateway entfernt —
    # diese muessen ueber dedizierte Funktionen (lock_door, set_alarm) mit
    # Confirmation-Flow laufen, nicht ueber das generische call_service.
    _CALL_SERVICE_ALLOWED_DOMAINS = frozenset(
        {
            "light",
            "switch",
            "climate",
            "cover",
            "fan",
            "media_player",
            "scene",
            "humidifier",
            "input_boolean",
            "input_number",
            "input_select",
            "input_text",
            "notify",
            "number",
            "select",
            "button",
            "vacuum",
            "homeassistant",
            "group",
            "shopping_list",
            "calendar",
            "timer",
            "counter",
        }
    )

    async def _exec_call_service(self, args: dict) -> dict:
        """Generischer HA Service-Aufruf (für Routinen wie Guest WiFi)."""
        domain = args.get("domain", "")
        service = args.get("service", "")
        entity_id = args.get("entity_id", "")
        if not domain or not service:
            return {"success": False, "message": "domain und service erforderlich"}

        if domain not in self._CALL_SERVICE_ALLOWED_DOMAINS:
            logger.warning("call_service: Blockierte Domain '%s.%s'", domain, service)
            return {
                "success": False,
                "message": f"Domain '{domain}' ist nicht erlaubt.",
            }

        # Sicherheitscheck: Cover-Services für Garagentore blockieren
        # Bypass-sicher: Prueft ALLE Domains wenn entity_id ein Cover ist
        is_cover_entity = entity_id.startswith("cover.")
        is_cover_domain = domain == "cover"

        if is_cover_domain and not entity_id:
            # Cover-Domain ohne entity_id blockieren — koennte alle Cover betreffen
            return {
                "success": False,
                "message": "cover-Service ohne entity_id nicht erlaubt (Sicherheitssperre).",
            }

        if is_cover_entity or is_cover_domain:
            states = await self.ha.get_states()
            entity_state = next(
                (s for s in (states or []) if s.get("entity_id") == entity_id), {}
            )
            if not await self._is_safe_cover(entity_id, entity_state):
                return {
                    "success": False,
                    "message": f"Sicherheitssperre: '{entity_id}' ist ein Garagentor/Tor und darf nicht automatisch gesteuert werden.",
                }

        service_data = {"entity_id": entity_id} if entity_id else {}
        # Nur erlaubte Service-Data Keys übernehmen (Whitelist)
        for k, v in args.items():
            if k in self._CALL_SERVICE_ALLOWED_KEYS:
                service_data[k] = v
        success = await self.ha.call_service(domain, service, service_data)
        return {"success": success, "message": f"{domain}.{service} ausgeführt"}

    async def _exec_play_media(self, args: dict) -> dict:
        action = args.get("action", "play")
        room = args.get("room")
        if not room and args.get("entity_id"):
            eid = args.get("entity_id", "")
            room = eid.split(".", 1)[1] if "." in eid else eid
        room = self._clean_room(room)
        entity_id = await self._find_entity("media_player", room) if room else None

        if not entity_id:
            states = await self.ha.get_states()
            # Bei stop/pause ohne Room: ALLE aktiven Player stoppen
            if action in ("stop", "pause") and not room:
                _active_states = {"playing", "paused", "buffering", "on"}
                active_players = [
                    s["entity_id"]
                    for s in (states or [])
                    if s.get("entity_id", "").startswith("media_player.")
                    and s.get("state") in _active_states
                ]
                if active_players:
                    service = "media_stop" if action == "stop" else "media_pause"
                    all_ok = True
                    for pid in active_players:
                        ok = await self.ha.call_service(
                            "media_player", service, {"entity_id": pid}
                        )
                        if not ok:
                            all_ok = False
                    logger.info(
                        "play_media %s: %d aktive Player gestoppt: %s",
                        action,
                        len(active_players),
                        active_players,
                    )
                    return {
                        "success": all_ok,
                        "message": f"Medien: {action} ({len(active_players)} Player)",
                    }
            # Sonst: ersten verfuegbaren Player nehmen (fuer play etc.)
            for s in states or []:
                if s.get("entity_id", "").startswith("media_player."):
                    entity_id = s["entity_id"]
                    break

        if not entity_id:
            return {"success": False, "message": "Kein Media Player gefunden"}

        # Foundation F.5: Musik-Suche via query
        query = args.get("query")
        media_type = args.get("media_type", "music")
        if query and action == "play":
            success = await self.ha.call_service(
                "media_player",
                "play_media",
                {
                    "entity_id": entity_id,
                    "media_content_id": query,
                    "media_content_type": media_type,
                },
            )
            return {"success": success, "message": f"Suche '{query}' wird abgespielt"}

        # Volume-Steuerung (absolut und relativ)
        if action in ("volume", "volume_up", "volume_down"):
            if action == "volume":
                volume_pct = args.get("volume")
                if volume_pct is None:
                    return {"success": False, "message": "Keine Lautstärke angegeben"}
            else:
                # Relative Steuerung: aktuelle Lautstärke holen und anpassen
                state = await self.ha.get_state(entity_id)
                current = 0.5
                if state and "attributes" in state:
                    current = state["attributes"].get("volume_level", 0.5)
                step = 0.1  # ±10%
                new_level = current + step if action == "volume_up" else current - step
                volume_pct = max(0, min(100, round(new_level * 100)))

            volume_level = max(0.0, min(1.0, float(volume_pct) / 100.0))
            success = await self.ha.call_service(
                "media_player",
                "volume_set",
                {"entity_id": entity_id, "volume_level": volume_level},
            )
            direction = (
                "lauter"
                if action == "volume_up"
                else "leiser"
                if action == "volume_down"
                else ""
            )
            msg = (
                f"Lautstärke {direction} auf {int(volume_pct)}%"
                if direction
                else f"Lautstärke auf {int(volume_pct)}%"
            )
            return {"success": success, "message": msg}

        # Source/Input-Switching
        if action == "source":
            source_name = args.get("source", "")
            if not source_name:
                # Verfuegbare Quellen auflisten
                state = await self.ha.get_state(entity_id)
                sources = (state or {}).get("attributes", {}).get("source_list", [])
                if sources:
                    return {
                        "success": True,
                        "message": f"Verfuegbare Quellen: {', '.join(sources)}",
                    }
                return {
                    "success": False,
                    "message": "Keine Quelle angegeben und keine Quellenliste verfuegbar",
                }
            success = await self.ha.call_service(
                "media_player",
                "select_source",
                {"entity_id": entity_id, "source": source_name},
            )
            return {"success": success, "message": f"Quelle gewechselt: {source_name}"}

        service_map = {
            "play": "media_play",
            "pause": "media_pause",
            "stop": "media_stop",
            "next": "media_next_track",
            "previous": "media_previous_track",
        }
        service = service_map.get(action, "media_play")
        success = await self.ha.call_service(
            "media_player", service, {"entity_id": entity_id}
        )
        return {"success": success, "message": f"Medien: {action}"}

    async def _exec_transfer_playback(self, args: dict) -> dict:
        """Phase 10.1: Übertraegt Musik-Wiedergabe von einem Raum zum anderen."""
        from_room = self._clean_room(args.get("from_room"))
        to_room = self._clean_room(args.get("to_room", ""))

        if not to_room:
            return {"success": False, "message": "Kein Zielraum angegeben"}

        to_entity = await self._find_entity("media_player", to_room)
        if not to_entity:
            return {
                "success": False,
                "message": f"Kein Media Player in '{to_room}' gefunden",
            }

        # Quell-Player finden (explizit oder aktiven suchen)
        from_entity = None
        if from_room:
            from_entity = await self._find_entity("media_player", from_room)
        else:
            # Aktiven Player finden
            states = await self.ha.get_states()
            for s in states or []:
                eid = s.get("entity_id", "")
                if eid.startswith("media_player.") and s.get("state") == "playing":
                    from_entity = eid
                    from_room = s.get("attributes", {}).get("friendly_name", eid)
                    break

        if not from_entity:
            return {"success": False, "message": "Keine aktive Wiedergabe gefunden"}

        if from_entity == to_entity:
            return {"success": True, "message": "Musik läuft bereits in diesem Raum"}

        # Aktuellen Zustand vom Quell-Player holen
        states = await self.ha.get_states()
        source_state = None
        for s in states or []:
            if s.get("entity_id") == from_entity:
                source_state = s
                break

        if not source_state or source_state.get("state") != "playing":
            return {"success": False, "message": f"In '{from_room}' läuft nichts"}

        attrs = source_state.get("attributes", {})
        media_content_id = attrs.get("media_content_id", "")
        media_content_type = attrs.get("media_content_type", "music")
        volume = attrs.get("volume_level", 0.5)

        # 1. Volume auf Ziel-Player setzen
        await self.ha.call_service(
            "media_player",
            "volume_set",
            {"entity_id": to_entity, "volume_level": volume},
        )

        # 2. Wiedergabe auf Ziel-Player starten
        success = False
        if media_content_id:
            success = await self.ha.call_service(
                "media_player",
                "play_media",
                {
                    "entity_id": to_entity,
                    "media_content_id": media_content_id,
                    "media_content_type": media_content_type,
                },
            )
        else:
            # Fallback: media_title aus bereits geladenem State als Suche nutzen
            media_title = attrs.get("media_title", "")
            if media_title:
                success = await self.ha.call_service(
                    "media_player",
                    "play_media",
                    {
                        "entity_id": to_entity,
                        "media_content_id": media_title,
                        "media_content_type": media_content_type or "music",
                    },
                )
            else:
                return {
                    "success": False,
                    "message": f"Kein übertragbarer Inhalt in '{from_room}' gefunden (weder Content-ID noch Titel)",
                }

        # 3. Quell-Player stoppen
        if success:
            await self.ha.call_service(
                "media_player",
                "media_stop",
                {"entity_id": from_entity},
            )

        return {
            "success": success,
            "message": f"Musik läuft jetzt im {to_room}."
            if success
            else f"Der Transfer nach {to_room} kam nicht zustande.",
        }

    async def _exec_arm_security_system(self, args: dict) -> dict:
        mode = args.get("mode")
        if not mode:
            return {
                "success": False,
                "message": "Kein Modus angegeben (arm_home, arm_away oder disarm).",
            }
        states = await self.ha.get_states()
        entity_id = None
        for s in states or []:
            if s.get("entity_id", "").startswith("alarm_control_panel."):
                entity_id = s["entity_id"]
                break

        if not entity_id:
            return {"success": False, "message": "Keine Alarmanlage gefunden"}

        service_map = {
            "arm_home": "alarm_arm_home",
            "arm_away": "alarm_arm_away",
            "disarm": "alarm_disarm",
        }
        service = service_map.get(mode)
        if not service:
            valid = ", ".join(service_map.keys())
            return {
                "success": False,
                "message": f"Unbekannter Alarm-Modus '{mode}'. Gültig: {valid}",
            }
        success = await self.ha.call_service(
            "alarm_control_panel", service, {"entity_id": entity_id}
        )
        return {"success": success, "message": f"Alarm: {mode}"}

    async def _exec_lock_door(self, args: dict) -> dict:
        door = args.get("door", "")
        action = args.get("action", "")
        if not door or not action:
            return {"success": False, "message": "door und action erforderlich"}

        # Fix: Nur lock/unlock als gueltige Aktionen akzeptieren
        if action not in ("lock", "unlock"):
            return {
                "success": False,
                "message": f"Ungueltige Aktion '{action}'. Erlaubt: lock, unlock",
            }

        entity_id = await self._find_entity("lock", door)
        if not entity_id:
            return {"success": False, "message": f"Kein Schloss '{door}' gefunden"}

        # Fix: Unlock erfordert explizite Bestaetigung via Confirmation-Flow
        if action == "unlock":
            return {
                "success": False,
                "requires_confirmation": True,
                "message": f"Sicherheitsabfrage: Tuer '{door}' wirklich entriegeln?",
                "confirmation_action": "lock_door",
                "confirmation_args": args,
            }

        success = await self.ha.call_service("lock", action, {"entity_id": entity_id})
        return {"success": success, "message": f"Tür {door}: {action}"}

    async def _exec_send_notification(self, args: dict) -> dict:
        message = args.get("message", "")
        if not message:
            return {"success": False, "message": "message erforderlich"}
        target = args.get("target", "phone")
        volume = args.get("volume")  # Phase 9: Optional volume (0.0-1.0)
        room = self._clean_room(
            args.get("room")
        )  # Phase 10: Optional room for TTS routing

        if target == "phone":
            success = await self.ha.call_service(
                "notify", "notify", {"message": message}
            )
        elif target == "speaker":
            # TTS über Piper (Wyoming): tts.speak mit TTS-Entity + Media-Player
            tts_entity = await self._find_tts_entity()

            # Phase 10: Room-aware Speaker-Auswahl
            if room:
                speaker_entity = await self._find_speaker_in_room(room)
            else:
                speaker_entity = await self._find_tts_speaker()

            # Phase 9: Volume setzen vor TTS
            if speaker_entity and volume is not None:
                await self.ha.call_service(
                    "media_player",
                    "volume_set",
                    {"entity_id": speaker_entity, "volume_level": volume},
                )

            # Alexa/Echo: Keine Audio-Dateien, stattdessen notify.alexa_media
            alexa_speakers = yaml_config.get("sounds", {}).get("alexa_speakers", [])
            if speaker_entity and speaker_entity in alexa_speakers:
                svc_name = "alexa_media_" + speaker_entity.replace(
                    "media_player.", "", 1
                )
                success = await self.ha.call_service(
                    "notify",
                    svc_name,
                    {"message": message, "data": {"type": "tts"}},
                )
            elif tts_entity and speaker_entity:
                success = await self.ha.call_service(
                    "tts",
                    "speak",
                    {
                        "entity_id": tts_entity,
                        "media_player_entity_id": speaker_entity,
                        "message": message,
                    },
                )
            elif speaker_entity:
                # Fallback: Legacy TTS Service
                success = await self.ha.call_service(
                    "tts",
                    "speak",
                    {
                        "entity_id": speaker_entity,
                        "message": message,
                    },
                )
            else:
                # Letzter Fallback: persistent_notification
                success = await self.ha.call_service(
                    "persistent_notification", "create", {"message": message}
                )
        else:
            success = await self.ha.call_service(
                "persistent_notification", "create", {"message": message}
            )
        room_info = f" (Raum: {room})" if room else ""
        return {"success": success, "message": f"Benachrichtigung gesendet{room_info}"}

    async def _exec_send_message_to_person(self, args: dict) -> dict:
        """Phase 10.2: Sendet eine Nachricht an eine bestimmte Person.

        Routing-Logik:
        1. Person zu Hause → TTS im Raum der Person
        2. Person weg → Push-Notification auf Handy
        """
        person = args.get("person", "")
        message = args.get("message", "")
        if not person or not message:
            return {"success": False, "message": "person und message erforderlich"}
        person_lower = person.lower()

        # Person-Profil laden
        person_profiles = yaml_config.get("person_profiles", {}).get("profiles", {})
        profile = person_profiles.get(person_lower, {})

        # Prüfen ob Person zuhause ist
        states = await self.ha.get_states()
        person_home = False
        for state in states or []:
            if state.get("entity_id", "").startswith("person."):
                name = state.get("attributes", {}).get("friendly_name", "")
                if name.lower() == person_lower and state.get("state") == "home":
                    person_home = True
                    break

        if person_home:
            # TTS im Raum der Person
            preferred_room = profile.get("preferred_room")
            tts_entity = await self._find_tts_entity()

            speaker = None
            if preferred_room:
                speaker = await self._find_speaker_in_room(preferred_room)
            if not speaker:
                speaker = await self._find_tts_speaker()

            if speaker:
                alexa_speakers = yaml_config.get("sounds", {}).get("alexa_speakers", [])
                if speaker in alexa_speakers:
                    svc_name = "alexa_media_" + speaker.replace("media_player.", "", 1)
                    success = await self.ha.call_service(
                        "notify",
                        svc_name,
                        {"message": message, "data": {"type": "tts"}},
                    )
                elif tts_entity:
                    success = await self.ha.call_service(
                        "tts",
                        "speak",
                        {
                            "entity_id": tts_entity,
                            "media_player_entity_id": speaker,
                            "message": message,
                        },
                    )
                else:
                    success = False
                room_info = f" im {preferred_room}" if preferred_room else ""
                return {
                    "success": success,
                    "message": f"Nachricht an {person} per TTS{room_info} gesendet",
                    "delivery": "tts",
                }

        # Person nicht zuhause oder kein Speaker → Push
        notify_service = profile.get("notify_service", "notify.notify")
        # Service-Name extrahieren (z.B. "notify.max_phone" → domain="notify", service="max_phone")
        parts = notify_service.split(".", 1)
        if len(parts) == 2:
            success = await self.ha.call_service(
                parts[0],
                parts[1],
                {
                    "message": message,
                    "title": f"Nachricht von {settings.assistant_name}",
                },
            )
        else:
            success = await self.ha.call_service(
                "notify", "notify", {"message": message}
            )

        return {
            "success": success,
            "message": f"Push-Nachricht an {person} gesendet",
            "delivery": "push",
        }

    async def _exec_play_sound(self, args: dict) -> dict:
        """Phase 9: Spielt einen Sound-Effekt ab."""
        sound = args.get("sound", "")
        if not sound:
            return {"success": False, "message": "sound erforderlich"}
        room = self._clean_room(args.get("room"))

        speaker_entity = None
        if room:
            speaker_entity = await self._find_entity("media_player", room)
        if not speaker_entity:
            speaker_entity = await self._find_tts_speaker()

        if not speaker_entity:
            return {"success": False, "message": "Kein Speaker gefunden"}

        # Sound als TTS-Chime abspielen (oder Media-File wenn vorhanden)
        # Kurze TTS-Nachricht als Ersatz für Sound-Files
        sound_texts = {
            "listening": ".",
            "confirmed": ".",
            "warning": "Hinweis.",
            "alarm": "Alarm!",
            "doorbell": "Es klingelt.",
            "greeting": ".",
            "error": "Fehler.",
            "goodnight": ".",
        }

        text = sound_texts.get(sound, ".")
        if text == ".":
            # Minimaler Sound — nur Volume-Ping
            return {"success": True, "message": f"Sound '{sound}' gespielt"}

        tts_entity = await self._find_tts_entity()
        if tts_entity:
            success = await self.ha.call_service(
                "tts",
                "speak",
                {
                    "entity_id": tts_entity,
                    "media_player_entity_id": speaker_entity,
                    "message": text,
                },
            )
        else:
            success = False

        return {"success": success, "message": f"Sound '{sound}' gespielt"}

    async def _exec_get_entity_state(self, args: dict) -> dict:
        entity_id = args.get("entity_id", "")
        if not entity_id:
            return {"success": False, "message": "entity_id erforderlich"}
        state = await self.ha.get_state(entity_id)

        # Fallback: Fuzzy-Match wenn exakter ID nicht gefunden
        if not state and "." in entity_id:
            domain, search = entity_id.split(".", 1)
            found = await self._find_entity(domain, search)
            if found:
                state = await self.ha.get_state(found)
                entity_id = found

        if not state:
            return {"success": False, "message": f"Entity '{entity_id}' nicht gefunden"}

        current = state.get("state", "unknown")
        attrs = state.get("attributes", {})
        friendly_name = attrs.get("friendly_name", entity_id)
        unit = attrs.get("unit_of_measurement", "")

        # Annotation-Beschreibung in Antwort einbauen
        annotation = get_entity_annotation(entity_id)
        desc = annotation.get("description", "")
        role = annotation.get("role", "")

        label = desc or friendly_name
        display = f"{label}: {current}"
        if unit:
            display += f" {unit}"
        if role:
            all_roles = get_all_roles()
            role_label = all_roles.get(role, {}).get("label", role)
            display += f" (Rolle: {role_label})"

        return {
            "success": True,
            "message": display,
            "state": current,
            "attributes": attrs,
        }

    async def _exec_get_entity_history(self, args: dict) -> dict:
        """Historische Daten einer Entity abrufen."""
        entity_id = args.get("entity_id", "")
        hours = int(args.get("hours", 24))

        if not entity_id:
            return {"success": False, "message": "Entity-ID erforderlich"}

        # Fuzzy-Match wenn exakter ID nicht gefunden
        state = await self.ha.get_state(entity_id)
        if not state and "." in entity_id:
            domain, search = entity_id.split(".", 1)
            found = await self._find_entity(domain, search)
            if found:
                entity_id = found

        try:
            history = await self.ha.get_history(entity_id, hours=hours)
        except Exception as e:
            logger.error("get_entity_history Fehler: %s", e)
            return {"success": False, "message": "Fehler beim Abrufen der Historie."}

        if not history:
            return {
                "success": True,
                "message": f"Keine Historie für '{entity_id}' in den letzten {hours}h",
            }

        # Numerische Werte: Min/Max/Avg berechnen
        numeric_vals = []
        for entry in history:
            try:
                numeric_vals.append(float(entry.get("state", "")))
            except (ValueError, TypeError):
                pass

        friendly_name = entity_id
        if state:
            friendly_name = state.get("attributes", {}).get("friendly_name", entity_id)
            unit = state.get("attributes", {}).get("unit_of_measurement", "")
        else:
            unit = ""

        lines = [
            f"Historie {friendly_name} (letzte {hours}h, {len(history)} Eintraege):"
        ]

        if numeric_vals:
            avg = sum(numeric_vals) / len(numeric_vals)
            lines.append(
                f"Min: {min(numeric_vals):.1f}{unit} | "
                f"Max: {max(numeric_vals):.1f}{unit} | "
                f"Durchschnitt: {avg:.1f}{unit}"
            )
            # Trend: Vergleiche erste und letzte 20%
            n = len(numeric_vals)
            if n >= 5:
                first_avg = sum(numeric_vals[: n // 5]) / (n // 5)
                last_avg = sum(numeric_vals[-(n // 5) :]) / (n // 5)
                diff = last_avg - first_avg
                if abs(diff) > 0.1:
                    trend = "steigend" if diff > 0 else "fallend"
                    lines.append(f"Trend: {trend} ({diff:+.1f}{unit})")

        # Letzte Änderungen (max 10)
        changes = []
        prev_state = None
        for entry in history:
            s = entry.get("state", "")
            if s != prev_state and s not in ("unavailable", "unknown"):
                ts = entry.get("last_changed", "")
                if ts:
                    ts_short = ts[11:16] if len(ts) > 16 else ts  # HH:MM
                    changes.append(f"{ts_short}: {s}{unit}")
                prev_state = s
        if changes:
            # Letzte 10 Änderungen
            shown = changes[-10:]
            lines.append("Letzte Änderungen: " + " → ".join(shown))

        return {"success": True, "message": "\n".join(lines)}

    def _get_write_calendar(self) -> Optional[str]:
        """Ersten konfigurierten Kalender für Schreib-Operationen zurückgeben."""
        configured = yaml_config.get("calendar", {}).get("entities", [])
        if isinstance(configured, str):
            return configured
        if configured:
            return configured[0]
        return None

    async def _exec_get_calendar_events(self, args: dict) -> dict:
        """Phase 11.3: Kalender-Termine abrufen via HA Calendar Entity."""
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        _tz_name = yaml_config.get("timezone", "Europe/Berlin")
        try:
            _tz = ZoneInfo(_tz_name)
        except Exception as e:
            if isinstance(e, asyncio.CancelledError):
                raise
            _tz = ZoneInfo("Europe/Berlin")
        timeframe = args.get("timeframe", "today")
        now = datetime.now(_tz)

        if timeframe == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = now.replace(hour=23, minute=59, second=59, microsecond=0)
        elif timeframe == "tomorrow":
            tomorrow = now + timedelta(days=1)
            start = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
            end = tomorrow.replace(hour=23, minute=59, second=59, microsecond=0)
        else:  # week
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = (now + timedelta(days=7)).replace(
                hour=23, minute=59, second=59, microsecond=0
            )

        # HA erwartet naive datetime-Strings (ohne TZ-Offset) im lokalen Format
        start_str = start.strftime("%Y-%m-%dT%H:%M:%S")
        end_str = end.strftime("%Y-%m-%dT%H:%M:%S")
        logger.info("Kalender: Zeitraum %s -> %s bis %s", timeframe, start_str, end_str)

        # Kalender-Entities bestimmen: Config hat Vorrang, sonst alle aus HA
        configured = yaml_config.get("calendar", {}).get("entities", [])
        if isinstance(configured, str):
            configured = [configured]

        if configured:
            calendar_entities = configured
            logger.info(
                "Kalender: %d konfigurierte Entities: %s",
                len(calendar_entities),
                calendar_entities,
            )
        else:
            # Alle calendar.* Entities aus HA sammeln
            states = await self.ha.get_states()
            all_cal_entities = [
                s["entity_id"]
                for s in (states or [])
                if s.get("entity_id", "").startswith("calendar.")
            ]
            logger.info(
                "Kalender: %d Entities in HA gefunden: %s",
                len(all_cal_entities),
                all_cal_entities,
            )

            # Bekannte Noise-Kalender ausfiltern (Feiertage, Geburtstage etc.)
            _NOISE_KEYWORDS = [
                "feiertag",
                "holiday",
                "birthday",
                "geburtstag",
                "abfall",
                "muell",
                "garbage",
                "waste",
                "trash",
                "schulferien",
                "school",
                "vacation",
            ]
            calendar_entities = [
                eid
                for eid in all_cal_entities
                if not any(kw in eid.lower() for kw in _NOISE_KEYWORDS)
            ]
            # Wenn nach Filter nichts uebrig, alle verwenden
            if not calendar_entities and all_cal_entities:
                calendar_entities = all_cal_entities
                logger.info(
                    "Kalender: Noise-Filter hat alles entfernt, nutze alle %d",
                    len(calendar_entities),
                )
            elif len(calendar_entities) < len(all_cal_entities):
                filtered_out = set(all_cal_entities) - set(calendar_entities)
                logger.info(
                    "Kalender: %d nach Filter (entfernt: %s)",
                    len(calendar_entities),
                    filtered_out,
                )

        if not calendar_entities:
            return {
                "success": False,
                "message": "Kein Kalender in Home Assistant gefunden",
            }

        logger.info(
            "Kalender: Abfrage von %d Entities: %s",
            len(calendar_entities),
            calendar_entities,
        )

        # Alle Kalender abfragen und Events sammeln
        all_events = []
        for cal_entity in calendar_entities:
            events_found = False
            # Methode 1: Service-Call mit ?return_response (HA 2024.x+)
            try:
                result = await self.ha.call_service_with_response(
                    "calendar",
                    "get_events",
                    {
                        "entity_id": cal_entity,
                        "start_date_time": start_str,
                        "end_date_time": end_str,
                    },
                )
                logger.info("Kalender %s service result: %s", cal_entity, result)

                if isinstance(result, dict):
                    # Response-Format: {entity_id: {"events": [...]}}
                    for entity_data in result.values():
                        if isinstance(entity_data, dict):
                            evts = entity_data.get("events", [])
                            if evts:
                                all_events.extend(evts)
                                events_found = True
                        elif isinstance(entity_data, list) and entity_data:
                            all_events.extend(entity_data)
                            events_found = True
            except Exception as e:
                logger.warning(
                    "Kalender %s Service-Call fehlgeschlagen: %s", cal_entity, e
                )

            # Methode 2: Direkte Calendar REST API als Fallback
            if not events_found:
                try:
                    rest_result = await self.ha.api_get(
                        f"/api/calendars/{cal_entity}?start={start_str}&end={end_str}"
                    )
                    logger.info("Kalender %s REST result: %s", cal_entity, rest_result)
                    if isinstance(rest_result, list) and rest_result:
                        all_events.extend(rest_result)
                except Exception as e:
                    logger.warning(
                        "Kalender %s REST-Fallback fehlgeschlagen: %s", cal_entity, e
                    )

        if not all_events:
            label = {"today": "heute", "tomorrow": "morgen", "week": "diese Woche"}.get(
                timeframe, timeframe
            )
            return {"success": True, "message": f"Keine Termine {label}."}

        # Startzeit aus Event extrahieren (HA gibt dict oder string zurück)
        def _parse_event_start(ev):
            raw = ev.get("start", "")
            if isinstance(raw, dict):
                raw = raw.get("dateTime") or raw.get("date") or ""
            return str(raw) if raw else ""

        # Datum-Validierung: Nur Events im angefragten Zeitraum behalten
        # (HA gibt manchmal Events ausserhalb des Bereichs zurück)
        validated_events = []
        for ev in all_events:
            raw_start = _parse_event_start(ev)
            if not raw_start:
                validated_events.append(ev)
                continue
            try:
                if "T" in raw_start:
                    ev_dt = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
                    ev_local = ev_dt.astimezone(_tz)
                else:
                    # Ganztaegig: nur Datum, als Mitternacht behandeln
                    ev_local = datetime.strptime(raw_start[:10], "%Y-%m-%d").replace(
                        tzinfo=_tz
                    )
                if start <= ev_local <= end:
                    validated_events.append(ev)
                else:
                    logger.warning(
                        "Kalender: Event '%s' am %s liegt ausserhalb %s-%s, übersprungen",
                        ev.get("summary", "?"),
                        ev_local.isoformat(),
                        start_str,
                        end_str,
                    )
            except (ValueError, TypeError) as e:
                logger.warning(
                    "Kalender: Event-Datum nicht parsebar: %s (%s)", raw_start, e
                )
                validated_events.append(ev)  # Im Zweifel behalten

        all_events = validated_events
        if not all_events:
            label = {"today": "heute", "tomorrow": "morgen", "week": "diese Woche"}.get(
                timeframe, timeframe
            )
            return {"success": True, "message": f"Keine Termine {label}."}

        # Nach Startzeit sortieren
        all_events.sort(key=lambda ev: _parse_event_start(ev) or "9999")

        # Strukturierte Rohdaten — LLM formuliert im JARVIS-Stil
        label = {"today": "heute", "tomorrow": "morgen", "week": "diese Woche"}.get(
            timeframe, timeframe
        )
        lines = [f"TERMINE {label.upper()} ({len(all_events)}):"]
        for ev in all_events[:15]:
            summary = ev.get("summary", "Kein Titel")
            location = ev.get("location", "")
            description = ev.get("description", "")
            raw_start = _parse_event_start(ev)

            # Zeit formatieren
            if "T" in raw_start:
                try:
                    dt = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
                    dt_local = dt.astimezone(_tz)
                    time_str = dt_local.strftime("%H:%M")
                except (ValueError, TypeError):
                    time_str = raw_start
            else:
                time_str = "ganztaegig"

            line = f"- {time_str} | {summary}"
            if location:
                line += f" | Ort: {location}"
            if description:
                line += f" | Info: {description[:80]}"
            lines.append(line)

        return {
            "success": True,
            "message": "\n".join(lines),
            "events": all_events[:15],
        }

    async def _exec_create_calendar_event(self, args: dict) -> dict:
        """Phase 11.3: Neuen Kalender-Termin erstellen via HA."""
        from datetime import datetime, timedelta

        title = args.get("title", "")
        date_str = args.get("date", "")
        if not title or not date_str:
            return {"success": False, "message": "title und date erforderlich"}
        start_time = args.get("start_time", "")
        end_time = args.get("end_time", "")
        description = args.get("description", "")

        # Kalender-Entity: Config oder erster aus HA
        calendar_entity = self._get_write_calendar()
        if not calendar_entity:
            states = await self.ha.get_states()
            for s in states or []:
                eid = s.get("entity_id", "")
                if eid.startswith("calendar."):
                    calendar_entity = eid
                    break

        if not calendar_entity:
            return {
                "success": False,
                "message": "Kein Kalender in Home Assistant gefunden",
            }

        service_data = {
            "entity_id": calendar_entity,
            "summary": title,
        }

        if start_time:
            # Termin mit Uhrzeit — ISO8601-Format für HA
            service_data["start_date_time"] = f"{date_str}T{start_time}:00"
            if end_time:
                service_data["end_date_time"] = f"{date_str}T{end_time}:00"
            else:
                # Standard: +1 Stunde
                try:
                    start_dt = datetime.strptime(
                        f"{date_str} {start_time}", "%Y-%m-%d %H:%M"
                    )
                    end_dt = start_dt + timedelta(hours=1)
                    service_data["end_date_time"] = end_dt.strftime("%Y-%m-%dT%H:%M:%S")
                except ValueError:
                    service_data["end_date_time"] = f"{date_str}T{start_time}:00"
        else:
            # Ganztaegiger Termin
            service_data["start_date"] = date_str
            try:
                end_date = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
                service_data["end_date"] = end_date.strftime("%Y-%m-%d")
            except ValueError:
                service_data["end_date"] = date_str

        if description:
            service_data["description"] = description

        success = await self.ha.call_service("calendar", "create_event", service_data)

        time_info = f" um {start_time}" if start_time else " (ganztaegig)"
        return {
            "success": success,
            "message": f"Termin '{title}' am {date_str}{time_info} erstellt"
            if success
            else f"Termin konnte nicht erstellt werden",
        }

    async def _exec_delete_calendar_event(self, args: dict) -> dict:
        """Phase 11.3: Kalender-Termin löschen.

        Sucht den Termin per Titel+Datum und loescht ihn via calendar.delete_event.
        """
        from datetime import datetime, timedelta

        title = args.get("title", "")
        date_str = args.get("date", "")
        if not title or not date_str:
            return {"success": False, "message": "title und date erforderlich"}

        # Kalender-Entity: Config oder erster aus HA
        calendar_entity = self._get_write_calendar()
        if not calendar_entity:
            states = await self.ha.get_states()
            for s in states or []:
                if s.get("entity_id", "").startswith("calendar."):
                    calendar_entity = s.get("entity_id")
                    break

        if not calendar_entity:
            return {
                "success": False,
                "message": "Kein Kalender in Home Assistant gefunden",
            }

        # Events für den Tag abrufen um das richtige Event zu finden
        try:
            start = f"{date_str}T00:00:00"
            end_date = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
            end = end_date.strftime("%Y-%m-%dT00:00:00")

            result = await self.ha.call_service_with_response(
                "calendar",
                "get_events",
                {
                    "entity_id": calendar_entity,
                    "start_date_time": start,
                    "end_date_time": end,
                },
            )

            # Event per Titel suchen
            events = []
            if isinstance(result, dict):
                for key, val in result.items():
                    if isinstance(val, dict):
                        events = val.get("events", [])
                        break

            target_event = None
            title_lower = title.lower()
            for event in events:
                if title_lower in event.get("summary", "").lower():
                    target_event = event
                    break

            if not target_event:
                return {
                    "success": False,
                    "message": f"Termin '{title}' am {date_str} nicht gefunden",
                }

            # Event löschen
            uid = target_event.get("uid", "")
            if uid:
                success = await self.ha.call_service(
                    "calendar",
                    "delete_event",
                    {"entity_id": calendar_entity, "uid": uid},
                )
            else:
                # Fallback: Ohne UID löschen (Startzeit nutzen)
                # HA gibt start/end als ISO-String oder als Dict mit date/dateTime zurück
                evt_start = target_event.get("start", start)
                evt_end = target_event.get("end", end)
                if isinstance(evt_start, dict):
                    evt_start = evt_start.get("dateTime", evt_start.get("date", start))
                if isinstance(evt_end, dict):
                    evt_end = evt_end.get("dateTime", evt_end.get("date", end))
                success = await self.ha.call_service(
                    "calendar",
                    "delete_event",
                    {
                        "entity_id": calendar_entity,
                        "start_date_time": evt_start,
                        "end_date_time": evt_end,
                        "summary": target_event.get("summary", title),
                    },
                )

            return {
                "success": success,
                "message": f"Termin '{title}' am {date_str} gelöscht"
                if success
                else "Termin konnte nicht gelöscht werden",
            }
        except Exception as e:
            logger.error("Kalender-Delete Fehler: %s", e)
            return {"success": False, "message": "Der Kalender macht Schwierigkeiten."}

    async def _exec_reschedule_calendar_event(self, args: dict) -> dict:
        """Phase 11.3: Kalender-Termin verschieben (Delete + Re-Create).

        Atomisch: Wenn Create fehlschlaegt, wird der alte Termin wiederhergestellt.
        """
        title = args.get("title", "")
        old_date = args.get("old_date", "")
        new_date = args.get("new_date", "")
        if not title or not old_date or not new_date:
            return {
                "success": False,
                "message": "title, old_date und new_date erforderlich",
            }
        new_start = args.get("new_start_time", "")
        new_end = args.get("new_end_time", "")

        # Alten Termin finden um Start/End für Rollback zu merken
        old_start_time = args.get("old_start_time", "")
        old_end_time = args.get("old_end_time", "")

        # 1. Alten Termin löschen
        delete_result = await self._exec_delete_calendar_event(
            {
                "title": title,
                "date": old_date,
            }
        )

        if not delete_result.get("success"):
            return {
                "success": False,
                "message": f"Der Termin laesst sich nicht verschieben: {delete_result.get('message', '')}",
            }

        # 2. Neuen Termin erstellen
        create_result = await self._exec_create_calendar_event(
            {
                "title": title,
                "date": new_date,
                "start_time": new_start,
                "end_time": new_end,
            }
        )

        if create_result.get("success"):
            return {
                "success": True,
                "message": f"Termin '{title}' verschoben von {old_date} nach {new_date}",
            }

        # 3. Rollback: Alten Termin wiederherstellen
        logger.warning(
            "Reschedule-Rollback: Stelle alten Termin '%s' am %s wieder her",
            title,
            old_date,
        )
        rollback_result = await self._exec_create_calendar_event(
            {
                "title": title,
                "date": old_date,
                "start_time": old_start_time,
                "end_time": old_end_time,
            }
        )
        if rollback_result.get("success"):
            return {
                "success": False,
                "message": f"Neuer Termin konnte nicht erstellt werden. Alter Termin '{title}' am {old_date} wiederhergestellt.",
            }
        return {
            "success": False,
            "message": f"Das ist unangenehm — der alte Termin wurde entfernt, aber der neue liess sich nicht anlegen und die Wiederherstellung schlug fehl. Bitte den Termin '{title}' manuell neu erstellen.",
        }

    async def _exec_set_presence_mode(self, args: dict) -> dict:
        mode = args.get("mode", "")

        # Versuche input_select für Anwesenheitsmodus zu finden
        states = await self.ha.get_states()
        entity_id = None
        for s in states or []:
            eid = s.get("entity_id", "")
            if eid.startswith("input_select.") and any(
                kw in eid for kw in ("presence", "anwesenheit", "presence_mode")
            ):
                entity_id = eid
                break

        if entity_id:
            success = await self.ha.call_service(
                "input_select",
                "select_option",
                {"entity_id": entity_id, "option": mode},
            )
            return {"success": success, "message": f"Anwesenheit: {mode}"}

        # Fallback: HA Event über REST API feuern
        success = await self.ha.fire_event("mindhome_presence_mode", {"mode": mode})
        if not success:
            # Letzter Fallback: input_boolean dynamisch suchen
            presence_entity = None
            for s in states or []:
                eid = s.get("entity_id", "")
                if eid.startswith("input_boolean.") and any(
                    kw in eid
                    for kw in ("zu_hause", "zuhause", "home", "presence", "anwesen")
                ):
                    presence_entity = eid
                    break
            if not presence_entity:
                return {
                    "success": False,
                    "message": "Kein Anwesenheits-Entity gefunden. Erstelle input_select oder input_boolean für Anwesenheit in Home Assistant.",
                }
            success = await self.ha.call_service(
                "input_boolean",
                "turn_on" if mode == "home" else "turn_off",
                {"entity_id": presence_entity},
            )
        return {"success": success, "message": f"Anwesenheit: {mode}"}

    async def _find_speaker_in_room(self, room: str) -> Optional[str]:
        """Phase 10.1: Findet einen TTS-Speaker in einem bestimmten Raum.

        Sucht zuerst in der Konfiguration (room_speakers),
        dann per Entity-Name-Matching (nur echte Speaker, keine TVs).
        """
        # 1. Konfiguriertes Mapping prüfen
        room_speakers = yaml_config.get("multi_room", {}).get("room_speakers", {})
        room_lower = room.lower().replace(" ", "_")
        for cfg_room, entity_id in (room_speakers or {}).items():
            if cfg_room.lower() == room_lower:
                return entity_id

        # 2. Entity-Name-Matching (nur echte Speaker, keine TVs/Receiver)
        states = await self.ha.get_states()
        if not states:
            return None
        for state in states:
            entity_id = state.get("entity_id", "")
            attributes = state.get("attributes", {})
            if room_lower in entity_id.lower() and self._is_tts_speaker(
                entity_id, attributes
            ):
                return entity_id
        return None

    async def _find_tts_entity(self) -> Optional[str]:
        """Findet die Piper TTS-Entity (tts.piper o.ae.)."""
        states = await self.ha.get_states()
        if not states:
            return None
        for state in states:
            entity_id = state.get("entity_id", "")
            if entity_id.startswith("tts.") and "piper" in entity_id:
                return entity_id
        # Fallback: Erste TTS-Entity
        for state in states:
            entity_id = state.get("entity_id", "")
            if entity_id.startswith("tts."):
                return entity_id
        return None

    # Entities die KEINE TTS-Speaker sind (TVs, Receiver, Streaming-Boxen)
    # Hinweis: Alexa/Echo nicht mehr ausgeschlossen — wird über
    # sounds.alexa_speakers Config behandelt (notify statt Audio)
    _EXCLUDED_SPEAKER_PATTERNS = (
        "tv",
        "fernseher",
        "television",
        "fire_tv",
        "firetv",
        "apple_tv",
        "appletv",
        "chromecast",
        "roku",
        "shield",
        "receiver",
        "avr",
        "denon",
        "marantz",
        "yamaha_receiver",
        "onkyo",
        "pioneer",
        "soundbar",
        "xbox",
        "playstation",
        "ps5",
        "ps4",
        "nintendo",
        "kodi",
        "plex",
        "emby",
        "jellyfin",
        "vlc",
        "mpd",
    )

    def _is_tts_speaker(self, entity_id: str, attributes: dict = None) -> bool:
        """Prueft ob ein media_player ein TTS-faehiger Speaker ist (kein TV etc.)."""
        if not entity_id.startswith("media_player."):
            return False
        entity_lower = entity_id.lower()
        for pattern in self._EXCLUDED_SPEAKER_PATTERNS:
            if pattern in entity_lower:
                return False
        if attributes:
            device_class = (attributes.get("device_class") or "").lower()
            if device_class in ("tv", "receiver"):
                return False
        return True

    async def _find_tts_speaker(self) -> Optional[str]:
        """Findet einen TTS-faehigen Speaker (kein TV/Receiver)."""
        states = await self.ha.get_states()
        if not states:
            return None
        for state in states:
            entity_id = state.get("entity_id", "")
            attributes = state.get("attributes", {})
            if self._is_tts_speaker(entity_id, attributes):
                return entity_id
        return None

    # ------------------------------------------------------------------
    # Phase 13.1: Config-Selbstmodifikation
    # ------------------------------------------------------------------

    async def _exec_edit_config(self, args: dict) -> dict:
        """Phase 13.1: Jarvis passt eigene Config-Dateien an (Whitelist-geschuetzt).

        SICHERHEIT:
        - NUR easter_eggs.yaml, opinion_rules.yaml, room_profiles.yaml (Whitelist)
        - settings.yaml ist NICHT editierbar (nicht in _EDITABLE_CONFIGS)
        - Snapshot vor jeder Änderung (Rollback jederzeit möglich)
        - yaml.safe_dump() verhindert Code-Injection
        """
        config_file = args.get("config_file", "")
        action = args.get("action", "")
        key = args.get("key", "")
        data = args.get("data", {})

        yaml_path = _EDITABLE_CONFIGS.get(config_file)
        if not yaml_path:
            return {
                "success": False,
                "message": f"Config '{config_file}' ist nicht editierbar",
            }

        try:
            # Snapshot vor Änderung (Rollback-Sicherheitsnetz)
            if self._config_versioning and self._config_versioning.is_enabled():
                await self._config_versioning.create_snapshot(
                    config_file,
                    yaml_path,
                    reason=f"edit_config:{action}:{key}",
                    changed_by="jarvis",
                )

            # Config laden (blocking I/O in thread)
            def _read_yaml():
                if yaml_path.exists():
                    with open(yaml_path) as f:
                        return yaml.safe_load(f) or {}
                return {}

            config = await asyncio.to_thread(_read_yaml)

            # Aktion ausführen
            if action == "add":
                if not data:
                    return {
                        "success": False,
                        "message": "Keine Daten zum Hinzufuegen angegeben",
                    }
                if key in config:
                    return {
                        "success": False,
                        "message": f"'{key}' existiert bereits. Nutze 'update' stattdessen.",
                    }
                config[key] = data
                msg = f"'{key}' zu {config_file} hinzugefuegt"
            elif action == "update":
                if key not in config:
                    return {
                        "success": False,
                        "message": f"'{key}' nicht in {config_file} gefunden",
                    }
                if isinstance(config[key], dict) and isinstance(data, dict):
                    config[key].update(data)
                else:
                    config[key] = data
                msg = f"'{key}' in {config_file} aktualisiert"
            elif action == "remove":
                if key not in config:
                    return {
                        "success": False,
                        "message": f"'{key}' nicht in {config_file} gefunden",
                    }
                del config[key]
                msg = f"'{key}' aus {config_file} entfernt"
            else:
                return {"success": False, "message": f"Unbekannte Aktion: {action}"}

            # Zurückschreiben (blocking I/O in thread)
            def _write_yaml():
                with open(yaml_path, "w") as f:
                    yaml.safe_dump(
                        config,
                        f,
                        allow_unicode=True,
                        default_flow_style=False,
                        sort_keys=False,
                    )

            await asyncio.to_thread(_write_yaml)

            # Cache invalidieren damit Änderungen sofort wirken
            if config_file == "room_profiles":
                cfg_module._room_profiles_cache.clear()
                cfg_module._room_profiles_ts = 0.0
                logger.info("Room-Profiles-Cache invalidiert nach edit_config")

            logger.info(
                "Config-Selbstmodifikation: %s (%s -> %s)", config_file, action, key
            )
            return {"success": True, "message": msg}

        except Exception as e:
            logger.error("Config-Edit fehlgeschlagen: %s", e)
            logger.warning("Config-Edit Exception Details: %s %s", type(e).__name__, e)
            return {
                "success": False,
                "message": "Die Konfiguration laesst sich gerade nicht ändern. Bitte spaeter erneut versuchen.",
            }

    # ------------------------------------------------------------------
    # Phase 15.2: Einkaufsliste (via HA Shopping List oder lokal)
    # ------------------------------------------------------------------

    async def _exec_manage_shopping_list(self, args: dict) -> dict:
        """Phase 15.2: Einkaufsliste verwalten über Home Assistant."""
        action = args.get("action", "")
        item = args.get("item", "")

        if action == "add":
            if not item:
                return {"success": False, "message": "Kein Artikel angegeben"}
            success = await self.ha.call_service(
                "shopping_list", "add_item", {"name": item}
            )
            return {
                "success": success,
                "message": f"'{item}' auf die Einkaufsliste gesetzt"
                if success
                else "Einkaufsliste nicht verfügbar",
            }

        elif action == "list":
            # Shopping List über HA API abrufen
            try:
                items = await self.ha.api_get("/api/shopping_list")
                if not items:
                    return {"success": True, "message": "Die Einkaufsliste ist leer."}
                open_items = [i["name"] for i in items if not i.get("complete")]
                done_items = [i["name"] for i in items if i.get("complete")]
                parts = []
                if open_items:
                    parts.append(
                        "Einkaufsliste:\n" + "\n".join(f"- {i}" for i in open_items)
                    )
                if done_items:
                    parts.append(f"Erledigt: {', '.join(done_items)}")
                if not open_items and not done_items:
                    return {"success": True, "message": "Die Einkaufsliste ist leer."}
                return {"success": True, "message": "\n".join(parts)}
            except Exception as e:
                logger.debug("Einkaufsliste Fehler: %s", e)
                return {"success": False, "message": "Einkaufsliste nicht verfügbar"}

        elif action == "complete":
            if not item:
                return {
                    "success": False,
                    "message": "Kein Artikel zum Abhaken angegeben",
                }
            success = await self.ha.call_service(
                "shopping_list", "complete_item", {"name": item}
            )
            # Smart Shopping: Einkauf protokollieren (fuer Verbrauchsprognose)
            if success and hasattr(self, "_smart_shopping") and self._smart_shopping:
                try:
                    await self._smart_shopping.record_purchase(item)
                except Exception as _e:
                    logger.debug("SmartShopping record_purchase: %s", _e)
            return {
                "success": success,
                "message": f"'{item}' abgehakt"
                if success
                else "Artikel nicht gefunden",
            }

        elif action == "clear_completed":
            success = await self.ha.call_service("shopping_list", "complete_all", {})
            return {
                "success": success,
                "message": "Abgehakte Artikel entfernt"
                if success
                else "Fehler beim Aufraumen",
            }

        return {"success": False, "message": f"Unbekannte Aktion: {action}"}

    # ------------------------------------------------------------------
    # Smart Shopping: Verbrauchsprognose + Rezept-Zutaten
    # ------------------------------------------------------------------

    async def _exec_smart_shopping(self, args: dict) -> dict:
        """Smart Shopping: Verbrauchsprognose, Rezept-Zutaten, Einkaufsmuster."""
        action = args.get("action", "")
        shopping = getattr(self, "_smart_shopping", None)

        if not shopping:
            return {"success": False, "message": "Smart Shopping nicht verfuegbar"}

        if action == "predictions":
            predictions = await shopping.get_predictions()
            if not predictions:
                return {
                    "success": True,
                    "message": "Noch keine Verbrauchsdaten vorhanden. Wenn du Artikel von der Einkaufsliste abhakst, lerne ich dein Verbrauchsmuster.",
                }
            lines = ["Verbrauchsprognose:"]
            for p in predictions[:10]:
                days = p.get("avg_days", 0)
                conf = int(p.get("confidence", 0) * 100)
                next_d = p.get("next_expected", "")[:10]
                lines.append(
                    f"- {p['item']}: alle ~{days} Tage (naechster Kauf: {next_d}, Sicherheit: {conf}%)"
                )
            return {"success": True, "message": "\n".join(lines)}

        elif action == "add_ingredients":
            ingredients = args.get("ingredients", [])
            if not ingredients:
                return {"success": False, "message": "Keine Zutaten angegeben"}
            result = await shopping.add_missing_ingredients(ingredients)
            return {"success": True, "message": result["message"]}

        elif action == "record_purchase":
            item_name = args.get("item", "")
            if not item_name:
                return {"success": False, "message": "Kein Artikel angegeben"}
            return await shopping.record_purchase(item_name)

        elif action == "shopping_pattern":
            pattern = await shopping.get_shopping_day_pattern()
            if not pattern:
                return {
                    "success": True,
                    "message": "Noch keine Einkaufsmuster erkannt. Ich lerne aus abgehakten Einkaufslisteneintraegen.",
                }
            msg = f"Dein ueblicher Einkaufstag: {pattern['preferred_day']} ({pattern['total_trips']} Einkauefe insgesamt)."
            counts = pattern.get("day_counts", {})
            if counts:
                sorted_days = sorted(counts.items(), key=lambda x: x[1], reverse=True)
                msg += " Verteilung: " + ", ".join(f"{d}: {c}x" for d, c in sorted_days)
            return {"success": True, "message": msg}

        return {"success": False, "message": f"Unbekannte Aktion: {action}"}

    # ------------------------------------------------------------------
    # Konversations-Gedaechtnis++
    # ------------------------------------------------------------------

    async def _exec_conversation_memory(self, args: dict) -> dict:
        """Projekte, offene Fragen, Tages-Zusammenfassungen."""
        action = args.get("action", "")
        cm = getattr(self, "_conversation_memory", None)

        if not cm:
            return {
                "success": False,
                "message": "Konversationsgedaechtnis nicht verfuegbar",
            }

        if action == "create_project":
            return await cm.create_project(
                name=args.get("name", ""),
                description=args.get("description", ""),
                person=args.get("person", ""),
            )

        elif action == "update_project":
            return await cm.update_project(
                name=args.get("name", ""),
                status=args.get("status", ""),
                note=args.get("note", ""),
                milestone=args.get("milestone", ""),
            )

        elif action == "list_projects":
            projects = await cm.get_projects(
                status=args.get("status", ""),
                person=args.get("person", ""),
            )
            if not projects:
                return {"success": True, "message": "Keine Projekte vorhanden."}
            lines = [f"Projekte ({len(projects)}):"]
            for p in projects:
                ms = len(p.get("milestones", []))
                notes = len(p.get("notes", []))
                status_icon = {"active": "▶", "paused": "⏸", "done": "✓"}.get(
                    p.get("status", ""), "?"
                )
                lines.append(
                    f"  {status_icon} {p.get('name', '?')} ({p.get('status', '?')}) — {ms} Meilensteine, {notes} Notizen"
                )
                if p.get("description"):
                    lines.append(f"    {p['description']}")
                for m in p.get("milestones", [])[-3:]:
                    lines.append(f"    ✓ {m['text']} ({m['date'][:10]})")
                for n in p.get("notes", [])[-2:]:
                    lines.append(f"    📝 {n['text'][:60]} ({n['date'][:10]})")
            return {"success": True, "message": "\n".join(lines)}

        elif action == "delete_project":
            return await cm.delete_project(name=args.get("name", ""))

        elif action == "add_question":
            return await cm.add_question(
                question=args.get("question", ""),
                context=args.get("description", ""),
                person=args.get("person", ""),
            )

        elif action == "answer_question":
            return await cm.answer_question(
                question_search=args.get("question", ""),
                answer=args.get("answer", ""),
            )

        elif action == "list_questions":
            questions = await cm.get_open_questions(person=args.get("person", ""))
            if not questions:
                return {"success": True, "message": "Keine offenen Fragen."}
            lines = [f"Offene Fragen ({len(questions)}):"]
            for q in questions:
                age = q.get("created_at", "")[:10]
                lines.append(f"  ❓ {q['question']} (seit {age})")
                if q.get("context"):
                    lines.append(f"     Kontext: {q['context'][:50]}")
            return {"success": True, "message": "\n".join(lines)}

        elif action == "save_summary":
            return await cm.save_daily_summary(
                summary=args.get("summary", ""),
                topics=args.get("topics", []),
                date=args.get("date", ""),
            )

        elif action == "get_summary":
            s = await cm.get_daily_summary(date=args.get("date", ""))
            if not s:
                return {
                    "success": True,
                    "message": "Keine Zusammenfassung fuer diesen Tag.",
                }
            topics = ", ".join(s.get("topics", []))
            return {
                "success": True,
                "message": f"Zusammenfassung ({s['date']}): {s['summary']}\nThemen: {topics}",
            }

        return {"success": False, "message": f"Unbekannte Aktion: {action}"}

    # ------------------------------------------------------------------
    # Multi-Room Audio Sync
    # ------------------------------------------------------------------

    async def _exec_multi_room_audio(self, args: dict) -> dict:
        """Speaker-Gruppen und synchrone Multi-Room-Wiedergabe."""
        action = args.get("action", "")
        mra = getattr(self, "_multi_room_audio", None)

        if not mra:
            return {"success": False, "message": "Multi-Room Audio nicht verfuegbar"}

        if action == "create_group":
            return await mra.create_group(
                name=args.get("group_name", ""),
                speakers=args.get("speakers", []),
                description=args.get("description", ""),
            )

        elif action == "delete_group":
            return await mra.delete_group(name=args.get("group_name", ""))

        elif action == "modify_group":
            return await mra.modify_group(
                name=args.get("group_name", ""),
                add_speakers=args.get("add_speakers"),
                remove_speakers=args.get("remove_speakers"),
            )

        elif action == "list_groups":
            groups = await mra.list_groups()
            if not groups:
                return {
                    "success": True,
                    "message": "Keine Audio-Gruppen vorhanden. Erstelle eine mit 'create_group'.",
                }
            lines = [f"Audio-Gruppen ({len(groups)}):"]
            for g in groups:
                n_speakers = len(g.get("speakers", []))
                lines.append(
                    f"  🔊 {g['name']} ({n_speakers} Speaker, Vol: {g.get('volume', '?')}%)"
                )
                if g.get("description"):
                    lines.append(f"    {g['description']}")
                for s in g.get("speakers", []):
                    vol = g.get("speaker_volumes", {}).get(s, "?")
                    lines.append(f"    - {s} ({vol}%)")
            return {"success": True, "message": "\n".join(lines)}

        elif action == "play":
            return await mra.play_to_group(
                group_name=args.get("group_name", ""),
                query=args.get("query", ""),
            )

        elif action == "stop":
            return await mra.stop_group(group_name=args.get("group_name", ""))

        elif action == "pause":
            return await mra.pause_group(group_name=args.get("group_name", ""))

        elif action == "volume":
            vol = args.get("volume", 40)
            return await mra.set_group_volume(
                group_name=args.get("group_name", ""),
                volume=vol,
                speaker=args.get("speaker", ""),
            )

        elif action == "status":
            return await mra.get_group_status(group_name=args.get("group_name", ""))

        elif action == "discover_speakers":
            speakers = await mra.discover_speakers()
            if not speakers:
                return {"success": True, "message": "Keine Speaker gefunden."}
            lines = [f"Verfuegbare Speaker ({len(speakers)}):"]
            for s in speakers:
                lines.append(f"  🔊 {s['name']} ({s['entity_id']}) — {s['state']}")
            return {"success": True, "message": "\n".join(lines)}

        return {"success": False, "message": f"Unbekannte Aktion: {action}"}

    # ------------------------------------------------------------------
    # Phase 16.2: Capabilities — Was kann Jarvis?
    # ------------------------------------------------------------------

    async def _exec_list_capabilities(self, args: dict) -> dict:
        """Phase 16.2: Listet alle Faehigkeiten des Assistenten."""
        capabilities = {
            "smart_home": [
                "Licht steuern (an/aus/dimmen, pro Raum)",
                "Heizung/Klima regeln (Temperatur, Modus)",
                "Rollläden steuern",
                "Szenen aktivieren (Filmabend, Gute Nacht, etc.)",
                "Alarmanlage steuern",
                "Türen ver-/entriegeln",
                "Anwesenheitsmodus setzen (Home/Away/Sleep/Vacation)",
            ],
            "medien": [
                "Musik abspielen/pausieren/stoppen",
                "Naechster/vorheriger Titel",
                "Musik zwischen Räumen übertragen",
                "Sound-Effekte abspielen",
            ],
            "kommunikation": [
                "Nachrichten an Personen senden (TTS oder Push)",
                "Benachrichtigungen (Handy, Speaker, Dashboard)",
                "Proaktive Meldungen (Alarm, Türklingel, Waschmaschine, etc.)",
            ],
            "gedaechtnis": [
                "'Merk dir X' — Fakten speichern",
                "'Was weisst du über X?' — Wissen abrufen",
                "'Vergiss X' — Fakten löschen",
                "Automatische Fakten-Extraktion aus Gespraechen",
                "Langzeit-Erinnerungen und Tages-Zusammenfassungen",
            ],
            "wissen": [
                "Allgemeine Wissensfragen beantworten",
                "Kalender-Termine anzeigen und erstellen",
                "'Was wäre wenn'-Simulationen",
                "Wissensdatenbank (Dokumente, RAG)",
                "Kochen mit Schritt-für-Schritt-Anleitung + Timer",
            ],
            "haushalt": [
                "Einkaufsliste verwalten (hinzufuegen, anzeigen, abhaken)",
                "Vorrats-Tracking mit Ablaufdaten (Kuehlschrank, Gefrier, Vorrat)",
                "Raumklima-Monitor (CO2, Feuchte, Temperatur, Trink-Erinnerung)",
                "Zeitgefuehl (Ofen zu lange an, PC-Pause, etc.)",
                "Wartungs-Erinnerungen (Rauchmelder, Filter, etc.)",
                "System-Diagnostik (Sensoren, Batterien, Netzwerk)",
            ],
            "persoenlichkeit": [
                "Anpassbarer Sarkasmus-Level (1-5)",
                "Eigene Meinungen zu Aktionen",
                "Easter Eggs (z.B. 'Ich bin Iron Man')",
                "Running Gags und Selbstironie",
                "Charakter-Entwicklung (wird vertrauter mit der Zeit)",
                "Stimmungserkennung und emotionale Reaktionen",
            ],
            "sicherheit": [
                "Gaeste-Modus (versteckt persoenliche Infos)",
                "Vertrauensstufen pro Person (Gast/Mitbewohner/Owner)",
                "PIN-geschuetztes Dashboard",
                "Nacht-Routinen mit Sicherheits-Check",
            ],
            "selbstverbesserung": [
                "Korrektur-Lernen ('Nein, ich meinte...')",
                "Eigene Config anpassen (Easter Eggs, Meinungen, Räume)",
                "Feedback-basierte Optimierung proaktiver Meldungen",
            ],
            "automationen": [
                "Alle HA-Automationen anzeigen mit Triggern, Bedingungen und Aktionen",
                "Automationen aus natürlicher Sprache erstellen ('Wenn ich nach Hause komme, Licht an')",
                "Vorschau + Bestaetigung vor Aktivierung",
                "Jarvis-Automationen auflisten und löschen",
            ],
        }

        lines = ["Das kann ich für dich tun:\n"]
        for category, items in capabilities.items():
            label = category.replace("_", " ").title()
            lines.append(f"{label}:")
            for item in items:
                lines.append(f"  - {item}")
            lines.append("")

        return {"success": True, "message": "\n".join(lines)}

    # ------------------------------------------------------------------
    # Automationen (read-only)
    # ------------------------------------------------------------------

    async def _exec_list_ha_automations(self, args: dict) -> dict:
        """Listet alle HA-Automationen mit Triggern, Bedingungen und Aktionen (read-only)."""
        search = (args.get("filter") or "").lower()

        try:
            automations = await self.ha.get_automations()
        except Exception as e:
            return {
                "success": False,
                "message": f"Automationen laden fehlgeschlagen: {e}",
            }

        results = []
        for auto in automations:
            alias = (
                auto.get("alias")
                or auto.get("attributes", {}).get("friendly_name")
                or auto.get("id", "?")
            )
            if search and search not in str(alias).lower():
                continue

            entry = {
                "id": auto.get("id", auto.get("entity_id", "?")),
                "alias": alias,
            }
            # Config-Felder (wenn von /api/config/automation/config)
            for key in ("trigger", "condition", "action", "mode", "description"):
                if key in auto:
                    entry[key] = auto[key]

            # State-Felder (wenn aus get_states)
            attrs = auto.get("attributes", {})
            if "last_triggered" in attrs:
                entry["last_triggered"] = attrs["last_triggered"]
            state = auto.get("state")
            if state:
                entry["enabled"] = state == "on"

            results.append(entry)

        return {
            "success": True,
            "count": len(results),
            "automations": results,
        }

    async def _exec_create_automation(self, args: dict) -> dict:
        """Erstellt eine Automation aus natürlicher Sprache."""
        import assistant.main as main_module

        brain = main_module.brain
        try:
            self_auto = brain.self_automation
        except AttributeError:
            return {
                "success": False,
                "message": "Self-Automation Modul nicht verfügbar.",
            }

        description = args.get("description", "")
        if not description:
            return {"success": False, "message": "Keine Beschreibung angegeben."}

        try:
            return await self_auto.generate_automation(description)
        except Exception as e:
            return {
                "success": False,
                "message": f"Automation-Erstellung fehlgeschlagen: {e}",
            }

    async def _exec_confirm_automation(self, args: dict) -> dict:
        """Bestaetigt eine ausstehende Automation."""
        import assistant.main as main_module

        brain = main_module.brain
        try:
            self_auto = brain.self_automation
        except AttributeError:
            return {
                "success": False,
                "message": "Self-Automation Modul nicht verfügbar.",
            }

        pending_id = args.get("pending_id", "")
        if not pending_id:
            return {"success": False, "message": "Keine Pending-ID angegeben."}

        try:
            return await self_auto.confirm_automation(pending_id)
        except Exception as e:
            return {
                "success": False,
                "message": f"Automation-Bestaetigung fehlgeschlagen: {e}",
            }

    async def _exec_list_jarvis_automations(self, args: dict) -> dict:
        """Listet alle Jarvis-Automationen auf."""
        import assistant.main as main_module

        brain = main_module.brain
        try:
            return await brain.self_automation.list_jarvis_automations()
        except Exception as e:
            return {
                "success": False,
                "message": f"Automationen laden fehlgeschlagen: {e}",
            }

    async def _exec_delete_jarvis_automation(self, args: dict) -> dict:
        """Loescht eine Jarvis-Automation."""
        import assistant.main as main_module

        brain = main_module.brain

        automation_id = args.get("automation_id", "")
        if not automation_id:
            return {"success": False, "message": "Keine Automation-ID angegeben."}

        return await brain.self_automation.delete_jarvis_automation(automation_id)

    @staticmethod
    def _normalize_name(text: str) -> str:
        """Normalisiert Umlaute und Sonderzeichen für Entity-Matching."""
        n = text.lower()
        # Unicode-Umlaute und ASCII-Digraphen in einem Schritt normalisieren
        n = (
            n.replace("ü", "ue")
            .replace("ä", "ae")
            .replace("ö", "oe")
            .replace("ß", "ss")
        )
        # LLM-Varianten: "bureau" statt "buero"/"büro"
        n = n.replace("bureau", "buero")
        return n.replace(" ", "_")

    async def _find_entity(
        self, domain: str, search: str, device_hint: str = "", person: str = ""
    ) -> Optional[str]:
        """Findet eine Entity anhand von Domain und Suchbegriff.

        Matching-Strategie (Best-Match statt First-Match):
        1. MindHome Device-DB (schnell, DB-basiert) — bester Match
        2. Fallback: Alle HA-States durchsuchen — bester Match
        Exakter Match > kuerzester Partial-Match (spezifischstes Ergebnis)

        device_hint: Optionaler Gerätename (z.B. 'stehlampe', 'deckenlampe')
                     zur Disambiguierung bei mehreren Geräten im selben Raum.
        person: Optionaler Personenname (z.B. 'Manuel', 'Julia')
                zur Disambiguierung wenn mehrere Räume gleich heissen
                (z.B. 'Manuel Buero' vs 'Julia Buero').
        """
        if not search:
            return None

        search_norm = self._normalize_name(search)
        hint_norm = self._normalize_name(device_hint) if device_hint else ""
        person_norm = self._normalize_name(person) if person else ""

        # Spezifische Geräte-Begriffe: werden bei der Auswahl deprioritisiert,
        # wenn kein device_hint angegeben ist, damit das Hauptgeraet im Raum
        # bevorzugt wird (z.B. Deckenlampe statt Stehlampe).
        _SPECIFIC_DEVICE_TERMS = {
            "stehlampe",
            "stehleuchte",
            "nachttisch",
            "nachttischlampe",
            "leselampe",
            "tischlampe",
            "tischleuchte",
            "led_strip",
            "ledstrip",
            "lichterkette",
            "nachtlicht",
            "spot",
        }

        # MindHome Device-Search (schnell, DB-basiert)
        try:
            devices = await self.ha.search_devices(domain=domain, room=search)
            if devices:
                logger.info(
                    "_find_entity: DB lieferte %d Treffer für '%s' (domain=%s, hint='%s'): %s",
                    len(devices),
                    search,
                    domain,
                    device_hint or "",
                    [
                        (d.get("name"), d.get("room"), d.get("ha_entity_id"))
                        for d in devices
                    ],
                )

                # Wenn device_hint angegeben: zuerst nach Gerätename filtern
                if hint_norm:
                    for dev in devices:
                        dev_name = self._normalize_name(dev.get("name", ""))
                        eid_name = self._normalize_name(
                            dev.get("ha_entity_id", "").split(".", 1)[-1]
                        )
                        if hint_norm in dev_name or hint_norm in eid_name:
                            logger.info(
                                "_find_entity: Device-Hint '%s' matched -> %s",
                                device_hint,
                                dev["ha_entity_id"],
                            )
                            return dev["ha_entity_id"]
                    # Hint passt auf kein Gerät -> weiter ohne Hint
                    logger.info(
                        "_find_entity: Device-Hint '%s' matched kein DB-Ergebnis, ignoriere Hint",
                        device_hint,
                    )

                # Best-Match: Exakt > kuerzester Partial (mit Match-Pruefung!)
                best = None
                best_score = float("inf")
                for dev in devices:
                    eid = dev.get("ha_entity_id", "")
                    # Domain-Check: Entities aus falscher Domain überspringen
                    # (DB kann z.B. sensor.* liefern obwohl domain=light)
                    if domain and eid and not eid.startswith(f"{domain}."):
                        logger.debug(
                            "_find_entity: Überspringe %s (domain=%s erwartet)",
                            eid,
                            domain,
                        )
                        continue
                    dev_name = self._normalize_name(dev.get("name", ""))
                    dev_room = self._normalize_name(dev.get("room", "") or "")
                    eid_name = self._normalize_name(eid.split(".", 1)[-1])

                    matched = False
                    # Exakter Raum-Match hat höchste Prioritaet
                    if dev_room == search_norm:
                        matched = True
                    # Exakter Name-Match
                    elif search_norm == dev_name:
                        logger.info(
                            "_find_entity: Exakter Name-Match -> %s",
                            dev["ha_entity_id"],
                        )
                        return dev["ha_entity_id"]
                    # Partial Match: bidirektional (Suchbegriff IN Entity ODER Entity IN Suchbegriff)
                    elif (
                        search_norm in dev_name
                        or search_norm in dev_room
                        or dev_room in search_norm
                        or dev_name in search_norm
                    ):
                        matched = True

                    # Annotation-Bonus: Role/Description match
                    annotation = get_entity_annotation(eid)
                    annotation_bonus = 0
                    if annotation:
                        if annotation.get("hidden"):
                            continue
                        ann_role = annotation.get("role", "")
                        ann_desc = self._normalize_name(
                            annotation.get("description", "")
                        )
                        # Role-Keywords matchen
                        if ann_role:
                            role_kws = _ROLE_KEYWORDS.get(ann_role, [])
                            if any(kw in search_norm for kw in role_kws):
                                annotation_bonus = -800
                                matched = True
                        # Beschreibung matchen
                        if ann_desc and search_norm in ann_desc:
                            annotation_bonus = min(annotation_bonus, -200)
                            matched = True
                        # Raum-Override aus Annotation
                        ann_room = annotation.get("room", "")
                        if ann_room:
                            ann_room_norm = self._normalize_name(ann_room)
                            if ann_room_norm == search_norm:
                                annotation_bonus = min(annotation_bonus, -600)
                                matched = True

                    if matched:
                        name_len = len(dev_name) + len(dev_room)
                        # Ohne device_hint: Spezifische Geräte mit Malus versehen,
                        # damit "Wohnzimmer Licht" vor "Stehlampe Wohnzimmer" gewählt wird
                        penalty = 0
                        if not hint_norm:
                            combined = f"{dev_name} {eid_name}"
                            if any(term in combined for term in _SPECIFIC_DEVICE_TERMS):
                                penalty = 1000
                        # Name-Match Bonus: Suchbegriff im Gerätenamen → bevorzugen
                        # ("Licht Badezimmer" bei Suche "badezimmer" → Bonus)
                        name_bonus = 0
                        if search_norm in dev_name or search_norm in eid_name:
                            name_bonus = -10
                        # Person-Kontext: Wenn der Personenname im Raum/Gerät vorkommt,
                        # Bonus geben (z.B. Manuel sagt "Buero" -> "Manuel Buero" bevorzugen)
                        person_bonus = 0
                        if person_norm:
                            combined_for_person = f"{dev_name} {dev_room}"
                            if person_norm in combined_for_person:
                                person_bonus = -500
                        score = (
                            name_len
                            + penalty
                            + name_bonus
                            + person_bonus
                            + annotation_bonus
                        )
                        if score < best_score:
                            best = dev["ha_entity_id"]
                            best_score = score
                if best:
                    logger.info(
                        "_find_entity: Best Match -> %s (score=%d)", best, best_score
                    )
                    return best
                # Kein Match in DB-Ergebnissen — weiter zu HA-Fallback
                logger.info(
                    "_find_entity: Kein Name/Raum-Match in %d DB-Ergebnissen, HA-Fallback",
                    len(devices),
                )
            else:
                logger.info(
                    "_find_entity: DB lieferte 0 Treffer für '%s', HA-Fallback", search
                )
        except Exception as e:
            logger.debug("MindHome device search failed, using HA fallback: %s", e)

        # Fallback: Alle HA-States durchsuchen
        states = await self.ha.get_states()
        if not states:
            return None

        best_match = None
        best_len = float("inf")

        for state in states:
            entity_id = state.get("entity_id", "")
            if not entity_id.startswith(f"{domain}."):
                continue

            # Hidden-Entities überspringen
            if is_entity_hidden(entity_id):
                continue

            name = entity_id.split(".", 1)[1]
            name_norm = self._normalize_name(name)
            friendly = state.get("attributes", {}).get("friendly_name", "")
            friendly_norm = self._normalize_name(friendly) if friendly else ""

            # Device-Hint: Gerätename muss im entity oder friendly_name vorkommen
            if hint_norm:
                if hint_norm in name_norm or (
                    friendly_norm and hint_norm in friendly_norm
                ):
                    # Zusaetzlich prüfen ob auch der Raum passt
                    if search_norm in name_norm or (
                        friendly_norm and search_norm in friendly_norm
                    ):
                        logger.info(
                            "_find_entity: HA-Fallback Hint-Match -> %s", entity_id
                        )
                        return entity_id

            # Exakter Match → sofort zurück
            if search_norm == name_norm or search_norm == friendly_norm:
                return entity_id

            # Partial Match → besten (kuerzesten) merken (bidirektional)
            matched = False
            if search_norm in name_norm or name_norm in search_norm:
                matched = True
            elif friendly_norm and (
                search_norm in friendly_norm or friendly_norm in search_norm
            ):
                matched = True

            # Annotation-Match im HA-Fallback
            annotation = get_entity_annotation(entity_id)
            annotation_bonus = 0
            if annotation:
                ann_role = annotation.get("role", "")
                ann_desc = self._normalize_name(annotation.get("description", ""))
                if ann_role:
                    role_kws = _ROLE_KEYWORDS.get(ann_role, [])
                    if any(kw in search_norm for kw in role_kws):
                        annotation_bonus = -800
                        matched = True
                if ann_desc and search_norm in ann_desc:
                    annotation_bonus = min(annotation_bonus, -200)
                    matched = True

            if matched:
                penalty = 0
                if not hint_norm:
                    combined = f"{name_norm} {friendly_norm}"
                    if any(term in combined for term in _SPECIFIC_DEVICE_TERMS):
                        penalty = 1000
                score = len(name_norm) + penalty + annotation_bonus
                if score < best_len:
                    best_match = entity_id
                    best_len = score

        # Phase 3: Erweiterter Fuzzy-Search — Einzelwort-Matching
        # Wenn Phase 1+2 nichts finden, versuche Teilwörter des Suchbegriffs
        # gegen alle Entities im Domain zu matchen
        if not best_match:
            search_words = [w for w in search_norm.split() if len(w) > 3]
            if search_words:
                all_entities = [
                    s
                    for s in (states or await self.ha.get_states() or [])
                    if s.get("entity_id", "").startswith(f"{domain}.")
                    and not self.is_entity_hidden(s.get("entity_id", ""))
                ]
                word_matches: list[tuple[int, int, str]] = []
                for entity in all_entities:
                    eid = entity.get("entity_id", "").lower()
                    fname = (
                        entity.get("attributes", {}).get("friendly_name", "") or ""
                    ).lower()
                    eid_norm = self._normalize_name(
                        eid.split(".", 1)[1] if "." in eid else eid
                    )
                    fname_norm = self._normalize_name(fname)
                    match_count = sum(
                        1 for w in search_words if w in eid_norm or w in fname_norm
                    )
                    if match_count > 0:
                        word_matches.append(
                            (match_count, len(fname_norm), entity.get("entity_id"))
                        )
                if word_matches:
                    word_matches.sort(
                        key=lambda x: (-x[0], x[1])
                    )  # Meiste Treffer, kürzester Name
                    best_match = word_matches[0][2]
                    logger.info(
                        "_find_entity: Fuzzy-Match '%s' -> %s (%d Wort-Treffer)",
                        search,
                        best_match,
                        word_matches[0][0],
                    )

        if not best_match:
            # Diagnose: Alle verfügbaren Entities dieser Domain loggen
            available = [
                f"{s.get('entity_id')} ('{s.get('attributes', {}).get('friendly_name', '')}')"
                for s in (states or [])
                if s.get("entity_id", "").startswith(f"{domain}.")
            ]
            logger.warning(
                "_find_entity: KEIN Match für '%s' (norm='%s') in domain '%s'. "
                "Verfügbare Entities: %s",
                search,
                search_norm,
                domain,
                available[:20],
            )

        return best_match

    # ------------------------------------------------------------------
    # Phase 15.2: Vorrats-Tracking
    # ------------------------------------------------------------------

    async def _exec_manage_inventory(self, args: dict) -> dict:
        """Verwaltet den Vorrat."""
        import assistant.main as main_module

        brain = main_module.brain
        try:
            inventory = brain.inventory
        except AttributeError:
            return {"success": False, "message": "Vorrats-Tracking nicht verfügbar."}

        action = args["action"]
        item = args.get("item", "")
        quantity = args.get("quantity", 1)
        expiry = args.get("expiry_date", "")
        category = args.get("category", "sonstiges")

        if action == "add":
            if not item:
                return {"success": False, "message": "Kein Artikel angegeben."}
            return await inventory.add_item(item, quantity, expiry, category)

        elif action == "remove":
            if not item:
                return {"success": False, "message": "Kein Artikel angegeben."}
            return await inventory.remove_item(item)

        elif action == "list":
            return await inventory.list_items(
                category if category != "sonstiges" else ""
            )

        elif action == "update_quantity":
            if not item:
                return {"success": False, "message": "Kein Artikel angegeben."}
            return await inventory.update_quantity(item, quantity)

        elif action == "check_expiring":
            expiring = await inventory.check_expiring(days_ahead=3)
            if not expiring:
                return {
                    "success": True,
                    "message": "Keine Artikel laufen in den nächsten 3 Tagen ab.",
                }
            lines = [f"{len(expiring)} Artikel laufen bald ab:"]
            for item_data in expiring:
                days = item_data["days_left"]
                if days < 0:
                    lines.append(
                        f"- {item_data['name']}: ABGELAUFEN seit {abs(days)} Tag(en)!"
                    )
                elif days == 0:
                    lines.append(f"- {item_data['name']}: läuft HEUTE ab!")
                else:
                    lines.append(f"- {item_data['name']}: noch {days} Tag(e)")
            return {"success": True, "message": "\n".join(lines)}

        return {"success": False, "message": f"Unbekannte Aktion: {action}"}

    # ------------------------------------------------------------------
    # Workshop-Modus: Reparatur & Werkstatt
    # ------------------------------------------------------------------

    async def _exec_manage_repair(self, args: dict) -> dict:
        """Dispatch für alle Workshop-Aktionen."""
        import assistant.main as main_module

        brain = main_module.brain
        planner = brain.repair_planner
        generator = brain.workshop_generator

        action = args["action"]
        pid = args.get("project_id", "")

        # --- Projekt-CRUD ---
        if action == "create_project":
            return await planner.create_project(
                title=args.get("title", "Neues Projekt"),
                description=args.get("description", ""),
                category=args.get("category", "maker"),
                priority=args.get("priority", "normal"),
            )
        elif action == "list_projects":
            projects = await planner.list_projects(
                status_filter=args.get("status"), category_filter=args.get("category")
            )
            return {"success": True, "projects": projects, "count": len(projects)}
        elif action == "get_project":
            p = await planner.get_project(pid)
            return p if p else {"success": False, "message": "Projekt nicht gefunden"}
        elif action == "update_project":
            updates = {}
            for k in ("status", "title", "category", "priority", "description"):
                if k in args:
                    updates[k] = args[k]
            return await planner.update_project(pid, **updates)
        elif action == "complete_project":
            return await planner.complete_project(pid, notes=args.get("text", ""))
        elif action == "add_note":
            return await planner.add_project_note(pid, args.get("text", ""))
        elif action == "add_part":
            return await planner.add_part(
                pid, args.get("item", ""), args.get("quantity", 1), args.get("cost", 0)
            )

        # --- LLM-Features ---
        elif action == "diagnose":
            return {
                "success": True,
                "message": await planner.diagnose_problem(
                    args.get("description", ""), args.get("person", "")
                ),
            }
        elif action == "simulate":
            return {
                "success": True,
                "message": await planner.simulate_design(
                    pid, args.get("description", "")
                ),
            }
        elif action == "troubleshoot":
            return {
                "success": True,
                "message": await planner.troubleshoot(pid, args.get("description", "")),
            }
        elif action == "suggest_improvements":
            return {"success": True, "message": await planner.suggest_improvements(pid)}
        elif action == "compare_components":
            return {
                "success": True,
                "message": await planner.compare_components(
                    args.get("component_a", ""),
                    args.get("component_b", ""),
                    use_case=args.get("description", ""),
                ),
            }
        elif action == "safety_checklist":
            return {
                "success": True,
                "message": await planner.generate_safety_checklist(pid),
            }
        elif action == "calibration_guide":
            return {
                "success": True,
                "message": await planner.calibration_guide(args.get("description", "")),
            }
        elif action == "analyze_error_log":
            return {
                "success": True,
                "message": await planner.analyze_error_log(pid, args.get("text", "")),
            }
        elif action == "evaluate_measurement":
            return {
                "success": True,
                "message": await planner.evaluate_measurement(
                    pid, args.get("text", "")
                ),
            }

        # --- Generator ---
        elif action == "generate_code":
            if not generator:
                return {
                    "success": False,
                    "message": "Workshop-Generator nicht verfügbar",
                }
            return await generator.generate_code(
                pid,
                args.get("description", ""),
                language=args.get("language", "arduino"),
            )
        elif action == "generate_3d":
            if not generator:
                return {
                    "success": False,
                    "message": "Workshop-Generator nicht verfügbar",
                }
            return await generator.generate_3d_model(pid, args.get("description", ""))
        elif action == "generate_schematic":
            if not generator:
                return {
                    "success": False,
                    "message": "Workshop-Generator nicht verfügbar",
                }
            return await generator.generate_schematic(pid, args.get("description", ""))
        elif action == "generate_website":
            if not generator:
                return {
                    "success": False,
                    "message": "Workshop-Generator nicht verfügbar",
                }
            return await generator.generate_website(pid, args.get("description", ""))
        elif action == "generate_bom":
            if not generator:
                return {
                    "success": False,
                    "message": "Workshop-Generator nicht verfügbar",
                }
            return await generator.generate_bom(pid)
        elif action == "generate_docs":
            if not generator:
                return {
                    "success": False,
                    "message": "Workshop-Generator nicht verfügbar",
                }
            return await generator.generate_documentation(pid)
        elif action == "generate_tests":
            if not generator:
                return {
                    "success": False,
                    "message": "Workshop-Generator nicht verfügbar",
                }
            return await generator.generate_tests(pid, args.get("filename", ""))

        # --- Berechnungen ---
        elif action == "calculate":
            if not generator:
                return {
                    "success": False,
                    "message": "Workshop-Generator nicht verfügbar",
                }
            return generator.calculate(
                args.get("calc_type", ""), **args.get("calc_params", {})
            )

        # --- Scanner ---
        elif action == "scan_object":
            return await planner.scan_object(
                description=args.get("description", ""),
                camera_name=args.get("camera", args.get("camera_name", "")),
            )

        # --- Library ---
        elif action == "search_library":
            if hasattr(brain, "workshop_library") and brain.workshop_library:
                results = await brain.workshop_library.search(args.get("query", ""))
                return {"success": True, "results": results}
            return {"success": False, "message": "Workshop-Library nicht verfügbar"}

        # --- Werkstatt-Inventar ---
        elif action == "add_workshop_item":
            return await planner.add_workshop_item(
                args.get("item", ""),
                quantity=args.get("quantity", 1),
                category=args.get("category", "werkzeug"),
            )
        elif action == "list_workshop":
            items = await planner.list_workshop(category=args.get("category"))
            return {"success": True, "items": items}

        # --- Budget ---
        elif action == "set_budget":
            return await planner.set_project_budget(pid, args.get("budget", 0))
        elif action == "add_expense":
            return await planner.add_expense(
                pid, args.get("item", ""), args.get("cost", 0)
            )

        # --- 3D-Drucker ---
        elif action == "printer_status":
            return await planner.get_printer_status()
        elif action == "start_print":
            return await planner.start_print(
                project_id=pid, filename=args.get("filename", "")
            )
        elif action == "pause_print":
            return await planner.pause_print()
        elif action == "cancel_print":
            return await planner.cancel_print()

        # --- Roboterarm ---
        elif action == "arm_move":
            return await planner.arm_move(
                args.get("x", 0), args.get("y", 0), args.get("z", 0)
            )
        elif action == "arm_gripper":
            return await planner.arm_gripper(args.get("description", "open"))
        elif action == "arm_home":
            return await planner.arm_home()
        elif action == "arm_pick_tool":
            return await planner.arm_pick_tool(args.get("item", ""))

        # --- Timer ---
        elif action == "start_timer":
            return await planner.start_timer(pid)
        elif action == "pause_timer":
            return await planner.pause_timer(pid)

        # --- Journal ---
        elif action == "journal_add":
            return await planner.add_journal_entry(args.get("text", ""))
        elif action == "journal_get":
            return await planner.get_journal()

        # --- Snippets ---
        elif action == "save_snippet":
            return await planner.save_snippet(
                args.get("item", ""),
                args.get("text", ""),
                language=args.get("language", ""),
            )
        elif action == "get_snippet":
            return await planner.get_snippet(args.get("item", ""))

        # --- Verleih ---
        elif action == "lend_tool":
            return await planner.lend_tool(args.get("item", ""), args.get("person", ""))
        elif action == "return_tool":
            return await planner.return_tool(args.get("item", ""))
        elif action == "list_lent":
            return {"success": True, "lent_tools": await planner.list_lent_tools()}

        # --- Templates ---
        elif action == "create_from_template":
            return await planner.create_from_template(
                args.get("template", ""), title=args.get("title", "")
            )

        # --- Stats ---
        elif action == "get_stats":
            return await planner.get_workshop_stats()

        # --- Multi-Project ---
        elif action == "switch_project":
            return await planner.switch_project(pid)
        elif action == "export_project":
            if not generator:
                return {
                    "success": False,
                    "message": "Workshop-Generator nicht verfügbar",
                }
            path = await generator.export_project(pid)
            return (
                {"success": True, "zip_path": path}
                if path
                else {"success": False, "message": "Keine Dateien"}
            )

        # --- Devices ---
        elif action == "check_device":
            return await planner.check_device_online(args.get("entity_id", ""))
        elif action == "link_device":
            return await planner.link_device_to_project(pid, args.get("entity_id", ""))
        elif action == "get_power":
            return await planner.get_power_consumption(args.get("entity_id", ""))

        return {"success": False, "message": f"Unbekannte Aktion: {action}"}

    # ------------------------------------------------------------------
    # Neue Features: Timer, Broadcast, Kamera, Conditionals, Energie, Web
    # ------------------------------------------------------------------

    async def _exec_set_timer(self, args: dict) -> dict:
        """Setzt einen allgemeinen Timer."""
        import assistant.main as main_module

        brain = main_module.brain
        return await brain.timer_manager.create_timer(
            duration_minutes=args["duration_minutes"],
            label=args.get("label", ""),
            room=args.get("room", ""),
            person=args.get("person", ""),
            action_on_expire=args.get("action_on_expire"),
        )

    async def _exec_cancel_timer(self, args: dict) -> dict:
        """Bricht einen Timer ab."""
        import assistant.main as main_module

        brain = main_module.brain
        return await brain.timer_manager.cancel_timer(label=args.get("label", ""))

    async def _exec_get_timer_status(self, args: dict) -> dict:
        """Zeigt Timer-Status an."""
        import assistant.main as main_module

        brain = main_module.brain
        return brain.timer_manager.get_status()

    # Phase 5A: Zeitgesteuerte Geraeteaktionen
    async def _exec_schedule_action(self, args: dict) -> dict:
        """Plant eine Geraete-Aktion fuer eine bestimmte Uhrzeit."""
        import assistant.main as main_module

        brain = main_module.brain
        return await brain.timer_manager.create_scheduled_action(
            action=args["action"],
            action_args=args.get("action_args", {}),
            target_time=args["target_time"],
            target_date=args.get("target_date", ""),
            repeat=args.get("repeat", "once"),
            person=args.get("person", ""),
            room=args.get("room", ""),
        )

    async def _exec_list_scheduled_actions(self, args: dict) -> dict:
        """Zeigt alle geplanten Geraete-Aktionen an."""
        import assistant.main as main_module

        brain = main_module.brain
        actions = await brain.timer_manager.list_scheduled_actions()
        if not actions:
            return {
                "success": True,
                "message": "Keine geplanten Aktionen.",
                "actions": [],
            }
        lines = []
        for a in actions:
            action_name = a.get("action", "").replace("_", " ").title()
            repeat = a.get("repeat", "once")
            repeat_de = {
                "once": "einmalig",
                "daily": "taeglich",
                "weekdays": "Mo-Fr",
                "weekends": "Sa-So",
                "weekly": "woechentlich",
            }.get(repeat, repeat)
            lines.append(
                f"{a.get('target_time', '?')}: {action_name} ({repeat_de}) [ID: {a.get('id', '?')}]"
            )
        return {"success": True, "message": "\n".join(lines), "actions": actions}

    async def _exec_cancel_scheduled_action(self, args: dict) -> dict:
        """Storniert eine geplante Geraete-Aktion."""
        import assistant.main as main_module

        brain = main_module.brain
        return await brain.timer_manager.cancel_scheduled_action(
            action_id=args["action_id"],
        )

    # Phase 5B: Standort-basierte Trigger
    async def _exec_set_location_trigger(self, args: dict) -> dict:
        """Erstellt einen standortbasierten Trigger."""
        import assistant.main as main_module

        brain = main_module.brain
        if not hasattr(brain, "self_automation") or not brain.self_automation:
            return {"success": False, "message": "Self-Automation nicht verfuegbar"}

        zone = args.get("zone", "")
        event = args.get("event", "leave")
        actions = args.get("actions", [])

        if not zone or not actions:
            return {"success": False, "message": "Zone und Aktionen sind erforderlich"}

        # Automation via self_automation erstellen
        trigger = {
            "platform": "zone",
            "zone": f"zone.{zone}" if not zone.startswith("zone.") else zone,
            "event": event,
        }
        action_list = []
        for act in actions:
            if isinstance(act, dict):
                action_list.append(act)
            elif isinstance(act, str):
                action_list.append({"function": act})

        result = {
            "success": True,
            "message": (
                f"Standort-Trigger erstellt: Wenn {zone} "
                f"{'betreten' if event == 'enter' else 'verlassen'} wird, "
                f"werden {len(action_list)} Aktionen ausgefuehrt."
            ),
            "trigger": trigger,
            "actions": action_list,
        }
        return result

    async def _exec_list_location_triggers(self, args: dict) -> dict:
        """Listet standortbasierte Trigger auf."""
        return {
            "success": True,
            "message": "Standort-Trigger werden ueber 'list_jarvis_automations' verwaltet.",
            "triggers": [],
        }

    async def _exec_cancel_location_trigger(self, args: dict) -> dict:
        """Loescht einen standortbasierten Trigger."""
        return {
            "success": True,
            "message": "Nutze 'delete_jarvis_automation' um Standort-Trigger zu loeschen.",
        }

    async def _exec_set_reminder(self, args: dict) -> dict:
        """Setzt eine Erinnerung für eine bestimmte Uhrzeit."""
        import assistant.main as main_module

        brain = main_module.brain
        return await brain.timer_manager.create_reminder(
            time_str=args["time"],
            label=args["label"],
            date_str=args.get("date", ""),
            room=args.get("room", ""),
            person=args.get("person", ""),
        )

    async def _exec_set_wakeup_alarm(self, args: dict) -> dict:
        """Stellt einen Wecker."""
        time_str = args.get("time", "")
        if not time_str:
            return {
                "success": False,
                "message": "Keine Uhrzeit angegeben. Format: HH:MM",
            }
        import assistant.main as main_module

        brain = main_module.brain
        return await brain.timer_manager.set_wakeup_alarm(
            time_str=time_str,
            label=args.get("label", "Wecker"),
            room=args.get("room", ""),
            repeat=args.get("repeat", ""),
        )

    async def _exec_cancel_alarm(self, args: dict) -> dict:
        """Loescht einen Wecker."""
        import assistant.main as main_module

        brain = main_module.brain
        return await brain.timer_manager.cancel_alarm(
            label=args.get("label", ""),
        )

    async def _exec_get_alarms(self, args: dict) -> dict:
        """Zeigt alle aktiven Wecker an."""
        import assistant.main as main_module

        brain = main_module.brain
        return await brain.timer_manager.get_alarms()

    # ------------------------------------------------------------------
    # Intercom Helpers
    # ------------------------------------------------------------------

    _BROADCAST_COOLDOWN_SECONDS = 30

    async def _send_tts_to_speaker(self, speaker: str, message: str) -> bool:
        """Sendet TTS an einen einzelnen Speaker (Piper oder Alexa).

        Returns:
            True wenn erfolgreich, False bei Fehler.
        """
        alexa_speakers = yaml_config.get("sounds", {}).get("alexa_speakers", [])
        try:
            if speaker in alexa_speakers:
                svc_name = "alexa_media_" + speaker.replace("media_player.", "", 1)
                await self.ha.call_service(
                    "notify",
                    svc_name,
                    {"message": message, "data": {"type": "tts"}},
                )
            else:
                tts_entity = yaml_config.get("tts", {}).get("entity", "tts.piper")
                await self.ha.call_service(
                    "tts",
                    "speak",
                    {
                        "entity_id": tts_entity,
                        "media_player_entity_id": speaker,
                        "message": message,
                    },
                )
            return True
        except Exception as e:
            logger.debug("TTS an %s fehlgeschlagen: %s", speaker, e)
            return False

    async def _exec_broadcast(self, args: dict) -> dict:
        """Sendet eine Durchsage an alle TTS-faehigen Lautsprecher."""
        message = args.get("message", "")
        if not message:
            return {"success": False, "message": "Keine Nachricht angegeben."}

        # Rate-Limiting
        now = time.time()
        cooldown = yaml_config.get("intercom", {}).get(
            "broadcast_cooldown_seconds",
            self._BROADCAST_COOLDOWN_SECONDS,
        )
        if now - self._last_broadcast_time < cooldown:
            remaining = int(cooldown - (now - self._last_broadcast_time))
            return {
                "success": False,
                "message": f"Durchsage-Cooldown. Bitte {remaining}s warten.",
            }
        self._last_broadcast_time = now

        # TTS-faehige Speaker finden (konfigurierte + auto-erkannte)
        room_speakers_cfg = yaml_config.get("multi_room", {}).get("room_speakers", {})
        speakers = []
        seen = set()

        # 1. Konfigurierte Room-Speakers haben Vorrang
        for eid in (room_speakers_cfg or {}).values():
            if eid and eid not in seen:
                speakers.append(eid)
                seen.add(eid)

        # 2. Auto-Discovery: nur echte TTS-Speaker (keine TVs/Receiver)
        states = await self.ha.get_states()
        for s in states or []:
            eid = s.get("entity_id", "")
            attrs = s.get("attributes", {})
            if eid not in seen and self._is_tts_speaker(eid, attrs):
                speakers.append(eid)
                seen.add(eid)

        if not speakers:
            return {"success": False, "message": "Keine Lautsprecher gefunden."}

        # TTS an alle Speaker senden
        count = 0
        failed = []
        for speaker in speakers:
            ok = await self._send_tts_to_speaker(speaker, message)
            if ok:
                count += 1
            else:
                failed.append(speaker)

        result = {
            "success": count > 0,
            "message": f'Durchsage an {count}/{len(speakers)} Lautsprecher: "{message}"',
            "delivered": count,
        }
        if failed:
            result["failed_speakers"] = failed
        return result

    async def _exec_send_intercom(self, args: dict) -> dict:
        """Gezielte Durchsage an Person oder Raum."""
        message = args.get("message", "")
        if not message:
            return {"success": False, "message": "Keine Nachricht angegeben."}

        target_room = args.get("target_room", "")
        target_person = args.get("target_person", "")

        # Person → Raum aufloesen
        if target_person and not target_room:
            import assistant.main as main_module

            brain = main_module.brain
            if hasattr(brain, "context_builder"):
                states = await self.ha.get_states()
                target_room = (
                    brain.context_builder.get_person_room(
                        target_person,
                        states=states,
                    )
                    or ""
                )

        if not target_room:
            return {
                "success": False,
                "message": f"Raum für {'Person ' + target_person if target_person else 'Durchsage'} nicht ermittelt. Bitte Raum angeben.",
            }

        # Speaker im Zielraum finden
        speaker = await self._find_speaker_in_room(target_room)
        if not speaker:
            return {
                "success": False,
                "message": f"Kein Lautsprecher im Raum '{target_room}' gefunden.",
            }

        # JARVIS-Prefix bei Person: "Julia, das Essen ist fertig"
        tts_message = message
        if target_person:
            tts_message = f"{target_person}, {message}"

        # Speaker-Verfügbarkeit prüfen
        speaker_state = await self.ha.get_state(speaker)
        if speaker_state and speaker_state.get("state") == "unavailable":
            return {
                "success": False,
                "message": f"Der Lautsprecher '{speaker}' schweigt sich aus. Nicht erreichbar.",
            }

        # TTS senden
        ok = await self._send_tts_to_speaker(speaker, tts_message)
        target_desc = (
            f"{target_person} im {target_room}" if target_person else target_room
        )
        if ok:
            return {
                "success": True,
                "message": f'Durchsage an {target_desc}: "{message}"',
            }
        return {
            "success": False,
            "message": f"Die Durchsage an {target_desc} kam nicht durch. Ich pruefe die Verbindung.",
        }

    async def _exec_get_camera_view(self, args: dict) -> dict:
        """Holt und beschreibt ein Kamera-Bild."""
        import assistant.main as main_module

        brain = main_module.brain
        return await brain.camera_manager.get_camera_view(
            camera_name=args.get("camera_name", ""),
        )

    async def _exec_create_conditional(self, args: dict) -> dict:
        """Erstellt einen bedingten Befehl."""
        import assistant.main as main_module

        brain = main_module.brain
        try:
            return await brain.conditional_commands.create_conditional(
                trigger_type=args["trigger_type"],
                trigger_value=args["trigger_value"],
                action_function=args["action_function"],
                action_args=args.get("action_args", {}),
                label=args.get("label", ""),
                ttl_hours=args.get("ttl_hours", 24),
                one_shot=args.get("one_shot", True),
            )
        except Exception as e:
            return {
                "success": False,
                "message": f"Bedingter Befehl fehlgeschlagen: {e}",
            }

    async def _exec_list_conditionals(self, args: dict) -> dict:
        """Listet bedingte Befehle auf."""
        import assistant.main as main_module

        brain = main_module.brain
        try:
            return await brain.conditional_commands.list_conditionals()
        except Exception as e:
            return {
                "success": False,
                "message": f"Bedingte Befehle laden fehlgeschlagen: {e}",
            }

    async def _exec_get_energy_report(self, args: dict) -> dict:
        """Zeigt Energie-Bericht an."""
        import assistant.main as main_module

        brain = main_module.brain
        try:
            result = await brain.energy_optimizer.get_energy_report()
            if isinstance(result, dict) and "message" in result:
                return result
            return {"success": True, "message": str(result)}
        except Exception as e:
            logger.error("Energie-Report fehlgeschlagen: %s", e)
            return {
                "success": False,
                "message": "Energie-Report konnte nicht erstellt werden.",
            }

    async def _exec_web_search(self, args: dict) -> dict:
        """Fuehrt eine Web-Suche durch."""
        import assistant.main as main_module

        brain = main_module.brain
        try:
            return await brain.web_search.search(query=args.get("query", ""))
        except Exception as e:
            logger.error("Web-Suche fehlgeschlagen: %s", e)
            return {
                "success": False,
                "message": "Web-Suche konnte nicht durchgeführt werden.",
            }

    async def _exec_get_security_score(self, args: dict) -> dict:
        """Gibt den aktuellen Sicherheits-Score zurück."""
        import assistant.main as main_module

        brain = main_module.brain
        try:
            result = await brain.threat_assessment.get_security_score()
            score = result["score"]
            level = result["level"]
            details = result.get("details", [])
            details_str = ", ".join(details) if details else "Alles in Ordnung"
            # Human-readable message so short-text refinement skip doesn't output raw JSON
            _level_map = {
                "good": "gut",
                "warning": "Warnung",
                "critical": "kritisch",
                "disabled": "deaktiviert",
            }
            _level_de = _level_map.get(level, level)
            if score < 0:
                message = "Der Sicherheits-Check ist deaktiviert."
            else:
                message = (
                    f"Sicherheits-Score: {score}/100 ({_level_de}). {details_str}."
                )
            return {
                "success": True,
                "score": score,
                "level": level,
                "details": details_str,
                "message": message,
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Sicherheits-Check fehlgeschlagen: {e}",
            }

    async def _exec_get_room_climate(self, args: dict) -> dict:
        """Gibt Raumklima-Daten zurück."""
        import assistant.main as main_module

        brain = main_module.brain
        try:
            result = await brain.health_monitor.get_status()
            if isinstance(result, dict):
                message = result.get("message", "")
                if not message:
                    # Strukturierte Daten in lesbaren Text umwandeln
                    parts = []
                    for key, val in result.items():
                        if key not in ("success", "message"):
                            parts.append(f"{key}: {val}")
                    message = ", ".join(parts) if parts else str(result)
                return {"success": True, "message": message}
            return {"success": True, "message": str(result)}
        except Exception as e:
            return {"success": False, "message": f"Raumklima-Check fehlgeschlagen: {e}"}

    async def _exec_get_active_intents(self, args: dict) -> dict:
        """Gibt aktive Vorhaben/Intents zurück."""
        import assistant.main as main_module
        from datetime import datetime

        brain = main_module.brain
        try:
            intents = await brain.intent_tracker.get_active_intents()
            if not intents:
                return {
                    "success": True,
                    "message": "Keine anstehenden Vorhaben gemerkt.",
                }
            # Abgelaufene Intents filtern
            now = datetime.now(timezone.utc)
            active = []
            for intent in intents:
                deadline = intent.get("deadline", "")
                if deadline:
                    try:
                        dl = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
                        if dl < now:
                            continue  # Abgelaufen — nicht anzeigen
                    except (ValueError, TypeError):
                        pass
                active.append(intent)
            if not active:
                return {"success": True, "message": "Keine anstehenden Vorhaben."}
            # Menschenlesbares Format statt RAW JSON
            lines = []
            for intent in active:
                desc = intent.get("intent", intent.get("description", "?"))
                deadline = intent.get("deadline", "")
                person = intent.get("person", "")
                reminder = intent.get("reminder_text", "")
                line = f"- {desc}"
                if deadline:
                    line += f" (bis {deadline})"
                if reminder:
                    line += f" — {reminder}"
                if person:
                    line += f" [{person}]"
                lines.append(line)
            return {
                "success": True,
                "message": f"{len(active)} offene Vorhaben:\n" + "\n".join(lines),
            }
        except Exception as e:
            return {"success": False, "message": f"Intent-Abfrage fehlgeschlagen: {e}"}

    async def _exec_get_wellness_status(self, args: dict) -> dict:
        """Gibt den Wellness-Status des Users zurück."""
        import assistant.main as main_module

        brain = main_module.brain
        try:
            status = {}

            # Mood/Stress
            mood_data = brain.mood.get_current_mood()
            status["mood"] = mood_data.get("mood", "neutral")
            status["stress_level"] = mood_data.get("stress_level", 0.0)

            # PC-Nutzungsdauer aus Redis
            if brain.memory.redis:
                pc_start = await brain.memory.redis.get("mha:wellness:pc_start")
                if pc_start:
                    from datetime import datetime

                    try:
                        start_dt = datetime.fromisoformat(pc_start)
                        minutes = (
                            datetime.now(timezone.utc) - start_dt
                        ).total_seconds() / 60
                        status["pc_minutes"] = round(minutes)
                    except (ValueError, TypeError):
                        pass

                last_hydration = await brain.memory.redis.get(
                    "mha:wellness:last_hydration"
                )
                if last_hydration:
                    status["last_hydration"] = last_hydration

            # Aktivität
            try:
                detection = await brain.activity.detect_activity()
                status["activity"] = detection.get("activity", "unknown")
            except Exception as e:
                logger.debug("Activity-Detection fehlgeschlagen: %s", e)

            return {"success": True, "message": str(status), **status}
        except Exception as e:
            return {"success": False, "message": f"Wellness-Check fehlgeschlagen: {e}"}

    async def _exec_get_house_status(self, args: dict) -> dict:
        """Gibt den Haus-Status zurück — konfigurierbar via settings.yaml.

        In settings.yaml unter house_status.sections kann der User festlegen
        welche Bereiche angezeigt werden:
          house_status:
            sections:
              - presence      # Wer ist zuhause/unterwegs
              - temperatures  # Raumtemperaturen
              - weather       # Aktuelles Wetter
              - lights        # Welche Lichter sind an
              - security      # Sicherheitsstatus
              - media         # Aktive Mediengeraete
              - open_items    # Offene Fenster/Türen
              - offline       # Offline-Geräte
        """
        import assistant.main as main_module
        from .config import yaml_config as _cfg

        brain = main_module.brain
        try:
            states = await brain.ha.get_states()
            if not states:
                return {"success": False, "message": "Home Assistant nicht erreichbar"}

            house = brain.context_builder._extract_house_status(states)

            # Konfigurierbare Sektionen (Default: alle)
            hs_cfg = _cfg.get("house_status", {})
            all_sections = [
                "presence",
                "temperatures",
                "weather",
                "lights",
                "security",
                "media",
                "open_items",
                "offline",
            ]
            enabled_sections = hs_cfg.get("sections", all_sections)

            parts = []

            # Anwesenheit
            if "presence" in enabled_sections:
                presence = house.get("presence", {})
                home = presence.get("home", [])
                away = presence.get("away", [])
                if home:
                    parts.append(f"Zuhause: {', '.join(home)}")
                if away:
                    parts.append(f"Unterwegs: {', '.join(away)}")

            # Temperaturen
            if "temperatures" in enabled_sections:
                # Prioritaet: Konfigurierte Sensoren → Mittelwert
                rt_cfg = _cfg.get("room_temperature", {})
                rt_sensors = rt_cfg.get("sensors", []) or []
                if rt_sensors:
                    state_map = {s.get("entity_id"): s for s in states}
                    sensor_temps = []
                    for sid in rt_sensors:
                        st = state_map.get(sid, {})
                        try:
                            sensor_temps.append(float(st.get("state", "")))
                        except (ValueError, TypeError):
                            pass
                    if sensor_temps:
                        avg = round(sum(sensor_temps) / len(sensor_temps), 1)
                        parts.append(f"Temperaturen: {avg}°C Durchschnitt")
                else:
                    # Fallback: climate entities einzeln
                    temps = house.get("temperatures", {})
                    if temps:
                        temp_rooms = hs_cfg.get("temperature_rooms", [])
                        temp_strs = []
                        for room, data in temps.items():
                            if temp_rooms and room.lower() not in [
                                r.lower() for r in temp_rooms
                            ]:
                                continue
                            current = data.get("current")
                            if current is None:
                                continue
                            target = data.get("target")
                            if target:
                                temp_strs.append(
                                    f"{room}: {current}°C (Soll {target}°C)"
                                )
                            else:
                                temp_strs.append(f"{room}: {current}°C")
                        if temp_strs:
                            parts.append(f"Temperaturen: {', '.join(temp_strs)}")

            # Wetter
            if "weather" in enabled_sections:
                weather = house.get("weather", {})
                if weather:
                    _cond_map = {
                        "sunny": "Sonnig",
                        "clear-night": "Klare Nacht",
                        "partlycloudy": "Teilweise bewölkt",
                        "cloudy": "Bewölkt",
                        "rainy": "Regen",
                        "pouring": "Starkregen",
                        "snowy": "Schnee",
                        "snowy-rainy": "Schneeregen",
                        "fog": "Nebel",
                        "hail": "Hagel",
                        "lightning": "Gewitter",
                        "lightning-rainy": "Gewitter mit Regen",
                        "windy": "Windig",
                        "windy-variant": "Windig & bewölkt",
                        "exceptional": "Ausnahmewetter",
                    }
                    cond = weather.get("condition", "?")
                    cond_de = _cond_map.get(cond, cond)
                    parts.append(
                        f"Wetter: {cond_de}, "
                        f"{weather.get('temp', '?')}°C, "
                        f"Luftfeuchte {weather.get('humidity', '?')}%"
                    )

            # Lichter
            if "lights" in enabled_sections:
                lights = house.get("lights", [])
                if lights:
                    parts.append(f"Lichter an: {', '.join(lights)}")
                else:
                    parts.append("Alle Lichter aus")

            # Sicherheit
            if "security" in enabled_sections:
                security = house.get("security", "unknown")
                parts.append(f"Sicherheit: {security}")

            # Medien
            if "media" in enabled_sections:
                media = house.get("media", [])
                if media:
                    parts.append(f"Medien aktiv: {', '.join(str(m) for m in media)}")

            # Offene Fenster/Türen — kategorisiert nach Typ (Fenster/Tür vs Tor)
            if "open_items" in enabled_sections:
                open_windows_doors = []
                open_gates = []
                for s in states:
                    eid = s.get("entity_id", "")
                    if is_window_or_door(eid, s) and s.get("state") == "on":
                        name = s.get("attributes", {}).get("friendly_name", eid)
                        if get_opening_type(eid, s) == "gate":
                            open_gates.append(name)
                        else:
                            open_windows_doors.append(name)
                if open_windows_doors:
                    parts.append(f"Offen: {', '.join(open_windows_doors)}")
                if open_gates:
                    parts.append(f"Tore offen: {', '.join(open_gates)}")

            # Offline Geräte
            if "offline" in enabled_sections:
                unavailable = []
                for s in states:
                    if s.get("state") == "unavailable":
                        name = s.get("attributes", {}).get(
                            "friendly_name", s.get("entity_id", "?")
                        )
                        unavailable.append(name)
                if unavailable:
                    parts.append(
                        f"Offline ({len(unavailable)}): {', '.join(unavailable[:10])}"
                    )

            if not parts:
                parts.append(
                    "Keine Sektionen konfiguriert. Pruefe house_status.sections in settings.yaml."
                )

            message = "\n".join(parts)
            return {"success": True, "message": message}
        except Exception as e:
            return {"success": False, "message": f"Haus-Status fehlgeschlagen: {e}"}

    async def _exec_get_full_status_report(self, args: dict) -> dict:
        """Aggregiert alle Datenquellen für einen narrativen JARVIS-Statusbericht."""
        import assistant.main as main_module

        brain = main_module.brain
        report_parts = []

        # 1. Haus-Status
        try:
            house_result = await self._exec_get_house_status({})
            if house_result.get("success"):
                report_parts.append(f"HAUSSTATUS:\n{house_result['message']}")
        except Exception as e:
            logger.debug("Status-Report: Hausstatus fehlgeschlagen: %s", e)

        # 2. Kalender-Termine
        try:
            cal_result = await self._exec_get_calendar_events({"timeframe": "today"})
            if cal_result.get("success") and cal_result.get("message"):
                report_parts.append(f"TERMINE HEUTE:\n{cal_result['message']}")
        except Exception as e:
            logger.debug("Status-Report: Kalender fehlgeschlagen: %s", e)

        # 3. Wetter
        try:
            weather_result = await self._exec_get_weather({"include_forecast": True})
            if weather_result.get("success") and weather_result.get("message"):
                report_parts.append(f"WETTER:\n{weather_result['message']}")
        except Exception as e:
            logger.debug("Status-Report: Wetter fehlgeschlagen: %s", e)

        # 4. Energie
        try:
            if hasattr(brain, "energy_optimizer") and brain.energy_optimizer.enabled:
                energy_result = await brain.energy_optimizer.get_energy_report()
                if isinstance(energy_result, dict) and energy_result.get("success"):
                    report_parts.append(f"ENERGIE:\n{energy_result.get('message', '')}")
        except Exception as e:
            logger.debug("Status-Report: Energie fehlgeschlagen: %s", e)

        # 5. Offene Erinnerungen / Intents (via _exec um abgelaufene zu filtern)
        try:
            intent_result = await self._exec_get_active_intents({})
            if intent_result.get("success") and "Keine" not in intent_result.get(
                "message", "Keine"
            ):
                report_parts.append(f"OFFENE ERINNERUNGEN:\n{intent_result['message']}")
        except Exception as e:
            logger.debug("Status-Report: Intents fehlgeschlagen: %s", e)

        if not report_parts:
            return {
                "success": False,
                "message": "Keine Daten für Statusbericht verfügbar.",
            }

        raw_report = "\n\n".join(report_parts)
        return {"success": True, "message": raw_report}

    async def _exec_get_weather(self, args: dict) -> dict:
        """Aktuelles Wetter und Vorhersage von Home Assistant."""
        include_forecast = args.get("include_forecast", False)

        states = await self.ha.get_states()
        if not states:
            return {
                "success": False,
                "message": "Die Systeme antworten gerade nicht. Ich versuche es gleich erneut.",
            }

        weather_entity = None
        for s in states:
            if s.get("entity_id", "").startswith("weather."):
                weather_entity = s
                break

        if not weather_entity:
            return {
                "success": False,
                "message": "Keine Wetter-Entity in Home Assistant gefunden.",
            }

        attrs = weather_entity.get("attributes", {})
        condition = weather_entity.get("state", "unbekannt")
        temp = attrs.get("temperature")
        humidity = attrs.get("humidity")
        wind_speed = attrs.get("wind_speed")
        wind_bearing = attrs.get("wind_bearing")
        pressure = attrs.get("pressure")

        # Wetter-Zustand übersetzen
        condition_map = {
            "sunny": "Sonnig",
            "clear-night": "Klare Nacht",
            "partlycloudy": "Teilweise bewölkt",
            "cloudy": "Bewölkt",
            "rainy": "Regen",
            "pouring": "Starkregen",
            "snowy": "Schnee",
            "snowy-rainy": "Schneeregen",
            "fog": "Nebel",
            "hail": "Hagel",
            "lightning": "Gewitter",
            "lightning-rainy": "Gewitter mit Regen",
            "windy": "Windig",
            "windy-variant": "Windig & bewölkt",
            "exceptional": "Ausnahmewetter",
        }
        condition_de = condition_map.get(condition, condition)

        # Windrichtung bestimmen
        wind_dir = ""
        if wind_bearing is not None:
            directions = [
                "Nord",
                "Nordost",
                "Ost",
                "Suedost",
                "Sued",
                "Suedwest",
                "West",
                "Nordwest",
            ]
            try:
                idx = round(float(wind_bearing) / 45) % 8
                wind_dir = directions[idx]
            except (ValueError, TypeError):
                pass

        # Rohdaten sammeln — LLM formuliert im JARVIS-Stil
        parts = []

        # Aktuelles Wetter immer mitliefern
        current = (
            f"AKTUELL: {condition_de}, {temp}°C"
            if temp is not None
            else f"AKTUELL: {condition_de}"
        )
        if humidity is not None:
            current += f", Luftfeuchtigkeit {humidity}%"
        if wind_speed is not None and wind_dir:
            current += f", Wind {wind_speed} km/h aus {wind_dir}"
        elif wind_speed is not None:
            current += f", Wind {wind_speed} km/h"
        if pressure is not None:
            current += f", Luftdruck {pressure} hPa"
        parts.append(current)

        if include_forecast:
            # Vorhersage via weather.get_forecasts Service (ab HA 2024.x)
            entity_id = weather_entity["entity_id"]
            forecast = []
            try:
                result = await self.ha.call_service_with_response(
                    "weather",
                    "get_forecasts",
                    {"entity_id": entity_id, "type": "daily"},
                )
                # HA gibt ggf. {"service_response": {entity: {forecast: [...]}}} zurück
                if isinstance(result, dict) and "service_response" in result:
                    result = result["service_response"]
                if isinstance(result, list):
                    # Format 1: [{entity_id: {forecast: [...]}}]
                    for item in result:
                        if isinstance(item, dict):
                            for key, val in item.items():
                                if isinstance(val, dict) and "forecast" in val:
                                    forecast = val["forecast"] or []
                                    break
                        if forecast:
                            break
                elif isinstance(result, dict):
                    # Format 2: {entity_id: {forecast: [...]}}
                    for key, val in result.items():
                        if isinstance(val, dict) and "forecast" in val:
                            forecast = val["forecast"] or []
                            break
            except Exception as e:
                logger.warning("weather.get_forecasts fehlgeschlagen: %s", e)

            # Fallback: alte Methode (attrs.forecast, HA < 2024)
            if not forecast:
                forecast = attrs.get("forecast", [])

            if forecast:
                for entry in forecast[:3]:
                    dt = entry.get("datetime", "")
                    fc_temp_hi = entry.get("temperature", "?")
                    fc_temp_lo = entry.get("templow")
                    fc_cond = condition_map.get(
                        entry.get("condition", ""), entry.get("condition", "?")
                    )
                    fc_wind = entry.get("wind_speed")
                    fc_precip = entry.get("precipitation")
                    fc_humidity = entry.get("humidity")
                    day_label = dt[:10] if len(dt) >= 10 else dt
                    line = f"VORHERSAGE {day_label}: {fc_cond}, Hoch {fc_temp_hi}°C"
                    if fc_temp_lo is not None:
                        line += f", Tief {fc_temp_lo}°C"
                    if fc_wind is not None:
                        line += f", Wind {fc_wind} km/h"
                    if fc_precip is not None and fc_precip > 0:
                        line += f", Niederschlag {fc_precip} mm"
                    if fc_humidity is not None:
                        line += f", Luftfeuchtigkeit {fc_humidity}%"
                    parts.append(line)
            else:
                # Keine Vorhersage verfügbar — still weglassen statt Fehlermeldung
                # Das LLM/Humanizer antwortet dann nur mit den aktuellen Daten
                logger.info(
                    "Wetter-Vorhersage nicht verfügbar (HA-Integration liefert keine Prognosedaten)"
                )

        return {"success": True, "message": "\n".join(parts)}

    async def _exec_get_device_health(self, args: dict) -> dict:
        """Gibt den Geräte-Gesundheitsstatus zurück."""
        import assistant.main as main_module

        brain = main_module.brain
        try:
            status = await brain.device_health.get_status()
            # Aktuelle Anomalien prüfen
            alerts = await brain.device_health.check_all()
            alert_msgs = [a.get("message", "") for a in alerts[:5]] if alerts else []
            return {
                "success": True,
                "message": f"{len(alerts)} Anomalie(n)"
                if alerts
                else "Alle Geräte normal",
                "alerts": alert_msgs,
                **status,
            }
        except Exception as e:
            return {"success": False, "message": f"Geräte-Check fehlgeschlagen: {e}"}

    async def _exec_get_learned_patterns(self, args: dict) -> dict:
        """Gibt erkannte Verhaltensmuster zurück."""
        import assistant.main as main_module

        brain = main_module.brain
        try:
            patterns = await brain.learning_observer.get_learned_patterns()
            if not patterns:
                return {
                    "success": True,
                    "message": "Noch keine Muster erkannt.",
                    "patterns": [],
                }
            summaries = []
            for p in patterns:
                summaries.append(
                    {
                        "action": p.get("action", ""),
                        "time": p.get("time_slot", ""),
                        "count": p.get("count", 0),
                        "weekday": p.get("weekday", -1),
                    }
                )
            return {
                "success": True,
                "count": len(summaries),
                "message": f"{len(summaries)} Muster erkannt",
                "patterns": summaries,
            }
        except Exception as e:
            return {"success": False, "message": f"Muster-Abfrage fehlgeschlagen: {e}"}

    async def _exec_describe_doorbell(self, args: dict) -> dict:
        """Beschreibt was die Türkamera zeigt."""
        import assistant.main as main_module

        brain = main_module.brain
        try:
            description = await brain.camera_manager.describe_doorbell()
            if description:
                return {"success": True, "message": description}
            return {
                "success": False,
                "message": "Türkamera nicht verfügbar oder kein Bild erhalten.",
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Türkamera-Abfrage fehlgeschlagen: {e}",
            }

    async def _exec_manage_protocol(self, args: dict) -> dict:
        """Verwaltet benannte Protokolle (create, execute, undo, list, delete)."""
        import assistant.main as main_module

        brain = main_module.brain
        engine = brain.protocol_engine
        action = args.get("action", "")
        name = args.get("name", "")
        description = args.get("description", "")

        person = getattr(brain, "_current_person", "") or ""

        try:
            if action == "create":
                if not name or not description:
                    return {
                        "success": False,
                        "message": "Name und Beschreibung werden für 'create' benötigt.",
                    }
                return await engine.create_protocol(name, description, person=person)
            elif action == "execute":
                if not name:
                    return {
                        "success": False,
                        "message": "Name wird für 'execute' benötigt.",
                    }
                return await engine.execute_protocol(name, person=person)
            elif action == "undo":
                if not name:
                    return {
                        "success": False,
                        "message": "Name wird für 'undo' benötigt.",
                    }
                return await engine.undo_protocol(name)
            elif action == "list":
                protocols = await engine.list_protocols()
                if not protocols:
                    return {
                        "success": True,
                        "message": "Noch keine Protokolle gespeichert.",
                    }
                lines = [f"{len(protocols)} Protokoll(e):"]
                for p in protocols:
                    lines.append(f"- {p['name']} ({p['steps']} Schritte)")
                return {
                    "success": True,
                    "message": "\n".join(lines),
                    "protocols": protocols,
                }
            elif action == "delete":
                if not name:
                    return {
                        "success": False,
                        "message": "Name wird für 'delete' benötigt.",
                    }
                return await engine.delete_protocol(name)
            else:
                return {"success": False, "message": f"Unbekannte Aktion: {action}"}
        except Exception as e:
            return {"success": False, "message": f"Protokoll-Fehler: {e}"}

    async def _exec_recommend_music(self, args: dict) -> dict:
        """Feature 11: Smart DJ — kontextbewusste Musikempfehlungen."""
        import assistant.main as main_module

        brain = main_module.brain
        dj = brain.music_dj
        action = args.get("action", "recommend")
        person = getattr(brain, "_current_person", "") or ""

        try:
            if action == "recommend":
                return await dj.get_recommendation(person=person)
            elif action == "play":
                return await dj.play_recommendation(
                    person=person,
                    room=args.get("room"),
                    genre_override=args.get("genre"),
                )
            elif action == "feedback":
                positive = args.get("positive", True)
                return await dj.record_feedback(positive=positive, person=person)
            elif action == "status":
                return await dj.get_music_status()
            else:
                return {"success": False, "message": f"Unbekannte DJ-Aktion: {action}"}
        except Exception as e:
            return {"success": False, "message": f"Music-DJ Fehler: {e}"}

    async def _exec_manage_visitor(self, args: dict) -> dict:
        """Feature 12: Besucher-Management — Besucher verwalten und Tür-Workflows."""
        import assistant.main as main_module

        brain = main_module.brain
        vm = brain.visitor_manager
        action = args.get("action", "status")

        try:
            if action == "add_known":
                pid = args.get("person_id", "")
                name = args.get("name", "")
                if not pid or not name:
                    return {
                        "success": False,
                        "message": "person_id und name sind erforderlich.",
                    }
                return await vm.add_known_visitor(
                    person_id=pid,
                    name=name,
                    relationship=args.get("relationship", ""),
                    notes=args.get("notes", ""),
                )
            elif action == "remove_known":
                pid = args.get("person_id", "")
                if not pid:
                    return {"success": False, "message": "person_id ist erforderlich."}
                return await vm.remove_known_visitor(pid)
            elif action == "list_known":
                return await vm.list_known_visitors()
            elif action == "expect":
                pid = args.get("person_id", "")
                if not pid:
                    return {"success": False, "message": "person_id ist erforderlich."}
                auto_unlock = args.get("auto_unlock", False)
                # auto_unlock erfordert Owner-Trust (= lock_door Berechtigung)
                if auto_unlock:
                    person = getattr(brain, "_current_person", "") or ""
                    trust_check = brain.autonomy.can_person_act(person, "lock_door")
                    if not trust_check["allowed"]:
                        return {
                            "success": False,
                            "message": trust_check.get(
                                "reason", "Keine Berechtigung für Auto-Unlock."
                            ),
                        }
                return await vm.expect_visitor(
                    person_id=pid,
                    name=args.get("name", ""),
                    expected_time=args.get("expected_time", ""),
                    auto_unlock=auto_unlock,
                    notes=args.get("notes", ""),
                )
            elif action == "cancel_expected":
                pid = args.get("person_id", "")
                if not pid:
                    return {"success": False, "message": "person_id ist erforderlich."}
                return await vm.cancel_expected(pid)
            elif action == "grant_entry":
                # grant_entry entriegelt die Tür — erfordert Owner-Trust (wie lock_door)
                person = getattr(brain, "_current_person", "") or ""
                trust_check = brain.autonomy.can_person_act(person, "lock_door")
                if not trust_check["allowed"]:
                    return {
                        "success": False,
                        "message": trust_check.get("reason", "Keine Berechtigung."),
                    }
                door = args.get("door", "haustuer")
                return await vm.grant_entry(door=door)
            elif action == "history":
                limit = max(1, min(int(args.get("limit", 20)), 100))
                return await vm.get_visit_history(limit=limit)
            elif action == "status":
                return await vm.get_status()
            else:
                return {
                    "success": False,
                    "message": f"Unbekannte Besucher-Aktion: {action}",
                }
        except Exception as e:
            return {"success": False, "message": f"Besucher-Management Fehler: {e}"}

    # ── Fernbedienung (Harmony etc.) ──────────────────────────────

    async def _find_remote_entity(self, remote_hint: str | None) -> str | None:
        """Findet remote.* Entity anhand Raum-Name oder Konfiguration."""
        cfg = yaml_config.get("remote", {})
        remotes = cfg.get("remotes", {})

        if not remote_hint and len(remotes) == 1:
            # Nur eine Fernbedienung konfiguriert → direkt nehmen
            return list(remotes.values())[0].get("entity_id")

        if remote_hint:
            hint = self._clean_room(remote_hint)
            # In Konfig suchen
            for key, rcfg in remotes.items():
                if hint in key.lower() or hint in rcfg.get("name", "").lower():
                    return rcfg.get("entity_id")
            # Direkt in HA suchen
            entity_id = await self._find_entity("remote", hint)
            if entity_id:
                return entity_id

        # Fallback: erste remote.* Entity aus HA
        states = await self.ha.get_states()
        for s in states or []:
            eid = s.get("entity_id", "")
            if eid.startswith("remote."):
                return eid
        return None

    async def _exec_remote_control(self, args: dict) -> dict:
        """Fernbedienung steuern: Aktivität starten/stoppen, IR-Befehle senden."""
        cfg = yaml_config.get("remote", {})
        if not cfg.get("enabled", True):
            return {
                "success": False,
                "message": "Fernbedienung-Steuerung ist deaktiviert. Aktiviere sie im Fernbedienung-Tab.",
            }

        action = args.get("action", "on")
        remote_hint = args.get("remote")
        entity_id = await self._find_remote_entity(remote_hint)

        if not entity_id:
            return {
                "success": False,
                "message": "Keine Fernbedienung gefunden. Bitte im Fernbedienung-Tab konfigurieren.",
            }

        activity = args.get("activity")
        command = args.get("command")
        device = args.get("device")
        num_repeats = max(1, min(args.get("num_repeats", 1), 20))

        # Aktivitäten-Aliase aus Config auflösen
        cfg = yaml_config.get("remote", {})
        for _key, rcfg in cfg.get("remotes", {}).items():
            if rcfg.get("entity_id") == entity_id and activity:
                aliases = rcfg.get("activities", {})
                # Alias-Lookup (case-insensitive)
                for alias_key, alias_val in aliases.items():
                    if activity.lower() in (alias_key.lower(), alias_val.lower()):
                        activity = alias_val
                        break
                break

        if action == "off":
            success = await self.ha.call_service(
                "remote", "turn_off", {"entity_id": entity_id}
            )
            return {
                "success": success,
                "message": "Fernbedienung ausgeschaltet — alle Geräte aus.",
            }

        elif action in ("on", "activity"):
            service_data = {"entity_id": entity_id}
            if activity:
                service_data["activity"] = activity
            success = await self.ha.call_service("remote", "turn_on", service_data)
            msg = (
                f"Aktivität '{activity}' gestartet."
                if activity
                else "Fernbedienung eingeschaltet."
            )
            return {"success": success, "message": msg}

        elif action == "command":
            if not command:
                return {"success": False, "message": "Kein Befehl angegeben."}
            service_data = {
                "entity_id": entity_id,
                "command": command,
            }
            if device:
                service_data["device"] = device
            if num_repeats > 1:
                service_data["num_repeats"] = num_repeats
            success = await self.ha.call_service("remote", "send_command", service_data)
            repeat_hint = f" (x{num_repeats})" if num_repeats > 1 else ""
            device_hint = f" an {device}" if device else ""
            return {
                "success": success,
                "message": f"Befehl '{command}'{device_hint} gesendet{repeat_hint}.",
            }

        return {"success": False, "message": f"Unbekannte Aktion: {action}"}

    async def _exec_get_remotes(self, args: dict) -> dict:
        """Listet alle Fernbedienungen mit Status und verfügbaren Aktivitäten."""
        remote_hint = args.get("remote")
        states = await self.ha.get_states()
        if not states:
            return {"success": False, "message": "Home Assistant nicht erreichbar."}

        cfg = yaml_config.get("remote", {})
        remotes_cfg = cfg.get("remotes", {})
        results = []

        for s in states:
            eid = s.get("entity_id", "")
            if not eid.startswith("remote."):
                continue
            if remote_hint:
                hint = self._clean_room(remote_hint)
                if (
                    hint not in eid.lower()
                    and hint
                    not in s.get("attributes", {}).get("friendly_name", "").lower()
                ):
                    continue

            attrs = s.get("attributes", {})
            name = attrs.get("friendly_name", eid)
            current_activity = attrs.get("current_activity", "PowerOff")
            available = attrs.get("activity_list", [])
            is_on = s.get("state") == "on"

            # Config-Aliase hinzufuegen
            aliases = {}
            for _key, rcfg in remotes_cfg.items():
                if rcfg.get("entity_id") == eid:
                    aliases = rcfg.get("activities", {})
                    break

            results.append(
                {
                    "entity_id": eid,
                    "name": name,
                    "is_on": is_on,
                    "current_activity": current_activity,
                    "available_activities": available,
                    "configured_aliases": aliases,
                }
            )

        if not results:
            return {
                "success": True,
                "message": "Keine Fernbedienungen gefunden.",
                "remotes": [],
            }

        return {"success": True, "remotes": results, "count": len(results)}

    # ── Deklarative Tools (Phase 13.3) ────────────────────────
    def _decl_tools_enabled(self) -> bool:
        """Prueft ob deklarative Tools aktiviert sind."""
        return yaml_config.get("declarative_tools", {}).get("enabled", True)

    async def _exec_create_declarative_tool(self, args: dict) -> dict:
        """Erstellt ein deklaratives Analyse-Tool."""
        if not self._decl_tools_enabled():
            return {
                "success": False,
                "message": "Analyse-Tools sind deaktiviert. Aktivierung über Einstellungen.",
            }
        import json as _json

        name = args.get("name", "").strip()
        description = args.get("description", "").strip()
        tool_type = args.get("type", "").strip()
        config_json = args.get("config_json", "")

        if not name or not description or not tool_type:
            return {
                "success": False,
                "message": "name, description und type sind erforderlich.",
            }

        try:
            config = (
                _json.loads(config_json)
                if isinstance(config_json, str)
                else config_json
            )
        except _json.JSONDecodeError as e:
            return {"success": False, "message": f"Ungültiges JSON in config_json: {e}"}

        registry = get_decl_registry()
        return registry.create_tool(
            name,
            {
                "type": tool_type,
                "description": description,
                "config": config,
            },
        )

    async def _exec_list_declarative_tools(self, args: dict) -> dict:
        """Listet alle deklarativen Tools."""
        registry = get_decl_registry()
        tools = registry.list_tools()
        if not tools:
            return {
                "success": True,
                "message": "Keine deklarativen Tools vorhanden.",
                "tools": [],
            }

        lines = [f"{len(tools)} deklarative Tool(s):"]
        for t in tools:
            lines.append(
                f"  - {t['name']} ({t.get('type', '?')}): {t.get('description', '')}"
            )
        return {"success": True, "message": "\n".join(lines), "tools": tools}

    async def _exec_delete_declarative_tool(self, args: dict) -> dict:
        """Loescht ein deklaratives Tool."""
        name = args.get("name", "").strip()
        if not name:
            return {"success": False, "message": "name ist erforderlich."}
        registry = get_decl_registry()
        return registry.delete_tool(name)

    async def _exec_run_declarative_tool(self, args: dict) -> dict:
        """Fuehrt ein deklaratives Tool aus."""
        if not self._decl_tools_enabled():
            return {"success": False, "message": "Analyse-Tools sind deaktiviert."}
        name = args.get("name", "").strip()
        if not name:
            return {"success": False, "message": "name ist erforderlich."}
        executor = DeclarativeToolExecutor(self.ha)
        return await executor.execute(name)

    # ── C6: Semantic History Search ──────────────────────────────

    async def _exec_search_history(self, args: dict) -> dict:
        """C6: Durchsucht Gespraechs-Archive in Redis nach einem Suchbegriff."""
        query = args.get("query", "").strip()
        if not query:
            return {
                "success": False,
                "message": "Suchbegriff (query) ist erforderlich.",
            }

        days_back = min(int(args.get("days_back", 7)), 30)
        person_filter = args.get("person", "").lower().strip()

        _cfg = yaml_config.get("semantic_history_search", {})
        if not _cfg.get("enabled", True):
            return {"success": False, "message": "History-Suche ist deaktiviert."}

        try:
            import redis.asyncio as aioredis
            from .config import settings

            _redis_url = settings.get("REDIS_URL", "redis://localhost:6379")
            redis_client = aioredis.from_url(_redis_url, decode_responses=True)
        except Exception as e:
            return {
                "success": False,
                "message": f"Redis-Verbindung fehlgeschlagen: {e}",
            }

        try:
            from datetime import datetime, timedelta

            query_lower = query.lower()
            query_words = set(query_lower.split())
            matches = []

            for day_offset in range(days_back):
                date = (
                    datetime.now(timezone.utc) - timedelta(days=day_offset)
                ).strftime("%Y-%m-%d")
                archive_key = f"mha:archive:{date}"

                try:
                    entries = await redis_client.lrange(archive_key, 0, -1)
                except Exception as e:
                    logger.debug(
                        "Redis Archiv-Abruf fehlgeschlagen fuer %s: %s", archive_key, e
                    )
                    continue

                for entry_raw in entries:
                    try:
                        import json

                        entry = (
                            json.loads(entry_raw)
                            if isinstance(entry_raw, str)
                            else json.loads(entry_raw.decode())
                        )
                    except (json.JSONDecodeError, TypeError, AttributeError):
                        continue

                    content = entry.get("content", "").lower()
                    role = entry.get("role", "")
                    timestamp = entry.get("timestamp", "")

                    # Person-Filter
                    if (
                        person_filter
                        and entry.get("person", "").lower() != person_filter
                    ):
                        continue

                    # Keyword-Match: Mindestens 1 Query-Wort im Content
                    if any(w in content for w in query_words):
                        _score = sum(1 for w in query_words if w in content)
                        matches.append(
                            {
                                "date": date,
                                "timestamp": timestamp,
                                "role": role,
                                "content": entry.get("content", "")[:300],
                                "person": entry.get("person", ""),
                                "score": _score,
                            }
                        )

            # Nach Relevanz sortieren
            matches.sort(key=lambda m: m["score"], reverse=True)
            matches = matches[:15]  # Max 15 Treffer

            if not matches:
                return {
                    "success": True,
                    "message": f"Keine Treffer fuer '{query}' in den letzten {days_back} Tagen gefunden.",
                    "results": [],
                }

            # Ergebnis formatieren
            lines = [f"{len(matches)} Treffer fuer '{query}':\n"]
            for m in matches:
                _role_de = "User" if m["role"] == "user" else "Jarvis"
                _ts = m.get("timestamp", m.get("date", "?"))
                _person = f" ({m['person']})" if m.get("person") else ""
                lines.append(f"[{_ts}] {_role_de}{_person}: {m['content']}")

            # Auch in action_outcomes suchen
            _action_matches = []
            try:
                redis_client2 = aioredis.from_url(_redis_url, decode_responses=True)
                try:
                    raw_actions = await redis_client2.lrange(
                        "mha:action_outcomes", 0, 499
                    )
                    for raw in raw_actions:
                        try:
                            import json

                            a = (
                                json.loads(raw)
                                if isinstance(raw, str)
                                else json.loads(raw.decode())
                            )
                            _action_str = json.dumps(
                                a.get("args", {}), ensure_ascii=False
                            ).lower()
                            if any(
                                w in _action_str or w in a.get("action", "").lower()
                                for w in query_words
                            ):
                                _action_matches.append(
                                    f"[{a.get('timestamp', '?')}] Aktion: {a.get('action', '?')} "
                                    f"Args: {json.dumps(a.get('args', {}), ensure_ascii=False)[:150]}"
                                )
                        except (json.JSONDecodeError, TypeError):
                            continue
                finally:
                    await redis_client2.aclose()
            except Exception as e:
                logger.debug("Redis Aktions-History Abruf fehlgeschlagen: %s", e)

            if _action_matches:
                lines.append(f"\n{len(_action_matches)} passende Aktionen:")
                lines.extend(_action_matches[:5])

            return {
                "success": True,
                "message": "\n".join(lines),
                "results": matches,
            }

        except Exception as e:
            return {"success": False, "message": f"Suche fehlgeschlagen: {e}"}
        finally:
            await redis_client.aclose()

    # ── C9: Automation-Debugging ──────────────────────────────

    async def _exec_debug_automation(self, args: dict) -> dict:
        """C9: Analysiert HA-Automatisierungen und deren Status."""
        automation_name = args.get("automation_name", "").strip()
        show_trace = args.get("show_trace", False)

        _cfg = yaml_config.get("automation_debugging", {})
        if not _cfg.get("enabled", True):
            return {
                "success": False,
                "message": "Automation-Debugging ist deaktiviert.",
            }

        try:
            states = await self.ha.get_states()
            if not states:
                return {"success": False, "message": "Keine HA-States verfuegbar."}
        except Exception as e:
            return {"success": False, "message": f"HA nicht erreichbar: {e}"}

        # Alle Automatisierungen filtern
        automations = [
            s for s in states if s.get("entity_id", "").startswith("automation.")
        ]

        if not automations:
            return {
                "success": True,
                "message": "Keine Automatisierungen in Home Assistant gefunden.",
            }

        # Optional nach Name filtern
        if automation_name:
            name_lower = automation_name.lower()
            filtered = [
                a
                for a in automations
                if name_lower
                in a.get("attributes", {}).get("friendly_name", "").lower()
                or name_lower in a.get("entity_id", "").lower()
            ]
            if not filtered:
                # Fuzzy-Fallback
                filtered = [
                    a
                    for a in automations
                    if any(
                        w in a.get("attributes", {}).get("friendly_name", "").lower()
                        for w in name_lower.split()
                    )
                ]
            automations = filtered

        if not automations:
            return {
                "success": True,
                "message": f"Keine Automatisierung mit '{automation_name}' gefunden. "
                f"Versuche es ohne Filter fuer eine Uebersicht.",
            }

        lines = [f"{len(automations)} Automatisierung(en) gefunden:\n"]

        for auto in automations[:10]:
            eid = auto.get("entity_id", "")
            attrs = auto.get("attributes", {})
            name = attrs.get("friendly_name", eid)
            state = auto.get("state", "?")
            last_triggered = attrs.get("last_triggered", "nie")
            current_state_str = "AKTIV" if state == "on" else "DEAKTIVIERT"

            lines.append(f"**{name}** ({eid})")
            lines.append(f"  Status: {current_state_str}")
            lines.append(f"  Zuletzt ausgeloest: {last_triggered}")

            # Trace laden wenn gewuenscht
            if show_trace:
                try:
                    trace_data = await self.ha.call_api(
                        "GET", f"api/config/automation/trace/{eid}"
                    )
                    if (
                        trace_data
                        and isinstance(trace_data, list)
                        and len(trace_data) > 0
                    ):
                        latest_trace = trace_data[0]
                        _trace_state = latest_trace.get("state", "?")
                        _trace_ts = latest_trace.get("timestamp", "?")
                        _trigger = latest_trace.get("trigger", {})
                        _trigger_desc = _trigger.get("description", str(_trigger)[:200])
                        lines.append(f"  Letzter Trace ({_trace_ts}): {_trace_state}")
                        lines.append(f"  Trigger: {_trigger_desc}")

                        # Fehler im Trace?
                        _trace_error = latest_trace.get("error", "")
                        if _trace_error:
                            lines.append(f"  FEHLER: {_trace_error}")
                    else:
                        lines.append("  Kein Trace verfuegbar.")
                except Exception as trace_e:
                    lines.append(f"  Trace nicht ladbar: {trace_e}")

            lines.append("")

        # Zusammenfassung
        _active = sum(1 for a in automations if a.get("state") == "on")
        _inactive = len(automations) - _active
        lines.append(f"Zusammenfassung: {_active} aktiv, {_inactive} deaktiviert")

        # Probleme erkennen
        problems = []
        for auto in automations:
            attrs = auto.get("attributes", {})
            lt = attrs.get("last_triggered")
            if lt and lt != "None":
                try:
                    from datetime import datetime, timedelta

                    lt_dt = datetime.fromisoformat(lt.replace("Z", "+00:00"))
                    age_days = (datetime.now(lt_dt.tzinfo) - lt_dt).days
                    if age_days > 30 and auto.get("state") == "on":
                        name = attrs.get("friendly_name", auto.get("entity_id", "?"))
                        problems.append(
                            f"'{name}' ist aktiv aber seit {age_days} Tagen nicht ausgeloest worden"
                        )
                except (ValueError, TypeError):
                    pass

        if problems:
            lines.append(f"\nMoegliche Probleme:")
            for p in problems[:5]:
                lines.append(f"- {p}")

        return {
            "success": True,
            "message": "\n".join(lines),
            "automation_count": len(automations),
        }

    async def _exec_suggest_declarative_tools(self, args: dict) -> dict:
        """Generiert Tool-Vorschlaege basierend auf vorhandenen HA-Entities."""
        if not self._decl_tools_enabled():
            return {"success": False, "message": "Analyse-Tools sind deaktiviert."}

        from .declarative_tools import generate_suggestions

        try:
            states = await self.ha.get_states()
        except Exception as e:
            return {"success": False, "message": f"HA nicht erreichbar: {e}"}

        if not states:
            return {
                "success": True,
                "message": "Keine Entities in Home Assistant gefunden.",
                "suggestions": [],
            }

        registry = get_decl_registry()
        existing = {t["name"]: t for t in registry.list_tools()}
        suggestions = generate_suggestions(states, existing)

        if not suggestions:
            return {
                "success": True,
                "message": "Keine neuen Vorschlaege — alle sinnvollen Tools existieren bereits oder es fehlen passende Entities.",
                "suggestions": [],
            }

        lines = [f"{len(suggestions)} Vorschlag/Vorschlaege für neue Analyse-Tools:\n"]
        for i, s in enumerate(suggestions, 1):
            lines.append(f"{i}. **{s['name']}** ({s['type']})")
            lines.append(f"   {s['description']}")
            lines.append(f"   Grund: {s['reason']}\n")

        lines.append(
            "Frage den User welche Vorschlaege er annehmen möchte. "
            "Erstelle die gewuenschten Tools dann mit create_declarative_tool."
        )

        return {
            "success": True,
            "message": "\n".join(lines),
            "suggestions": suggestions,
        }

    # ------------------------------------------------------------------
    # Phase 1.5: Memory-Augmented Reasoning Tools
    # ------------------------------------------------------------------

    async def _exec_retrieve_memory(self, args: dict) -> dict:
        """Durchsucht semantisches Langzeitgedaechtnis nach Fakten."""
        query = args.get("query", "")
        if not query:
            return {"success": False, "message": "Kein Suchbegriff angegeben."}

        person = args.get("person")
        try:
            import assistant.main as main_module

            brain = getattr(main_module, "brain", None)
            if not brain or not hasattr(brain, "semantic_memory"):
                return {"success": False, "message": "Gedaechtnis nicht verfuegbar."}

            facts = await brain.semantic_memory.search_facts(
                query,
                limit=5,
                person=person,
            )
            if not facts:
                return {
                    "success": True,
                    "message": f"Keine Fakten zu '{query}' gefunden.",
                }

            lines = [f"Gefundene Fakten zu '{query}':"]
            for f in facts:
                content = f.get("content", "")
                confidence = f.get("confidence", 0)
                category = f.get("category", "")
                person_tag = f.get("person", "")
                meta = f" [{category}]" if category else ""
                person_info = f" (Person: {person_tag})" if person_tag else ""
                lines.append(
                    f"- {content}{meta}{person_info} (Konfidenz: {confidence:.0%})"
                )

            return {"success": True, "message": "\n".join(lines)}
        except Exception as e:
            logger.error("retrieve_memory fehlgeschlagen: %s", e)
            return {"success": False, "message": "Gedaechtnissuche fehlgeschlagen."}

    async def _exec_retrieve_history(self, args: dict) -> dict:
        """Ruft die letzten Aktionen und Gespraeche ab."""
        limit = min(args.get("limit", 5), 20)
        try:
            import assistant.main as main_module

            brain = getattr(main_module, "brain", None)
            if not brain or not brain.memory:
                return {"success": False, "message": "Gedaechtnis nicht verfuegbar."}

            conversations = await brain.memory.get_recent_conversations(limit=limit)
            if not conversations:
                return {
                    "success": True,
                    "message": "Keine aktuellen Gespraeche gefunden.",
                }

            lines = [f"Letzte {len(conversations)} Interaktionen:"]
            for conv in conversations:
                role = conv.get("role", "?")
                content = conv.get("content", "")[:200]
                ts = conv.get("timestamp", "")
                time_str = ts.split("T")[1][:5] if "T" in ts else ts[:16]
                lines.append(f"- [{time_str}] {role}: {content}")

            return {"success": True, "message": "\n".join(lines)}
        except Exception as e:
            logger.error("retrieve_history fehlgeschlagen: %s", e)
            return {"success": False, "message": "Verlaufsabfrage fehlgeschlagen."}

    # ------------------------------------------------------------------
    # Phase 1.3: Verification Tool — State nach Aktion pruefen
    # ------------------------------------------------------------------

    async def _exec_verify_device_state(self, args: dict) -> dict:
        """Prueft den aktuellen Zustand eines Geraets nach einer Aktion."""
        entity_id = args.get("entity_id", "")
        if not entity_id:
            return {"success": False, "message": "Keine entity_id angegeben."}

        expected = args.get("expected_state")

        try:
            state = await self.ha.get_state(entity_id)
            if not state:
                return {
                    "success": False,
                    "message": f"Entity {entity_id} nicht gefunden.",
                }

            current = state.get("state", "unknown")
            attrs = state.get("attributes", {})

            info_parts = [f"Entity: {entity_id}", f"Zustand: {current}"]

            # Relevante Attribute je nach Domain
            if entity_id.startswith("light."):
                brightness = attrs.get("brightness")
                if brightness is not None:
                    info_parts.append(f"Helligkeit: {round(brightness / 255 * 100)}%")
            elif entity_id.startswith("climate."):
                temp = attrs.get("temperature")
                current_temp = attrs.get("current_temperature")
                if temp is not None:
                    info_parts.append(f"Zieltemperatur: {temp}°C")
                if current_temp is not None:
                    info_parts.append(f"Aktuelle Temperatur: {current_temp}°C")
            elif entity_id.startswith("cover."):
                position = attrs.get("current_position")
                if position is not None:
                    info_parts.append(f"Position: {position}%")

            result = {
                "success": True,
                "message": " | ".join(info_parts),
                "state": current,
            }

            if expected:
                if current == expected:
                    result["verified"] = True
                    result["message"] += f" ✓ (erwartet: {expected})"
                else:
                    result["verified"] = False
                    result["message"] += (
                        f" ✗ (erwartet: {expected}, tatsaechlich: {current})"
                    )

            return result
        except Exception as e:
            logger.error("verify_device_state fehlgeschlagen: %s", e)
            return {"success": False, "message": f"State-Abfrage fehlgeschlagen: {e}"}

    # ==================================================================
    # Personal Assistant Tools
    # ==================================================================

    async def _exec_manage_tasks(self, args: dict) -> dict:
        """Aufgaben/Todo-Listen verwalten."""
        import assistant.main as main_module

        brain = main_module.brain
        try:
            tm = brain.task_manager
        except AttributeError:
            return {"success": False, "message": "Task Manager nicht verfuegbar."}

        action = args.get("action", "")

        if action == "add":
            return await tm.add_task(
                title=args.get("title", ""),
                person=args.get("person", ""),
                due_date=args.get("due_date", ""),
                priority=args.get("priority", "medium"),
            )
        elif action == "list":
            return await tm.list_tasks(
                person=args.get("person", ""),
            )
        elif action == "complete":
            return await tm.complete_task(title=args.get("title", ""))
        elif action == "remove":
            return await tm.remove_task(title=args.get("title", ""))
        elif action == "add_recurring":
            return await tm.add_recurring_task(
                title=args.get("title", ""),
                recurrence=args.get("recurrence", ""),
                weekday=args.get("weekday", ""),
                person=args.get("person", ""),
            )
        elif action == "list_recurring":
            return await tm.list_recurring_tasks()
        elif action == "delete_recurring":
            return await tm.delete_recurring_task(title=args.get("title", ""))

        return {"success": False, "message": f"Unbekannte Aktion: {action}"}

    async def _exec_manage_notes(self, args: dict) -> dict:
        """Notizen verwalten."""
        nm = getattr(self, "_note_manager", None)
        if not nm:
            return {"success": False, "message": "Notiz-System nicht verfuegbar."}

        action = args.get("action", "")

        if action == "add":
            return await nm.add_note(
                content=args.get("content", ""),
                category=args.get("category", "sonstiges"),
                person=args.get("person", ""),
            )
        elif action == "list":
            return await nm.list_notes(
                category=args.get("category", ""),
                person=args.get("person", ""),
                limit=args.get("limit", 10),
            )
        elif action == "search":
            return await nm.search_notes(
                query=args.get("content", ""),
                limit=args.get("limit", 5),
            )
        elif action == "delete":
            return await nm.delete_note(note_id=args.get("note_id", ""))
        elif action == "categories":
            return await nm.get_note_categories()

        return {"success": False, "message": f"Unbekannte Aktion: {action}"}

    async def _exec_manage_family(self, args: dict) -> dict:
        """Familien-Profile verwalten."""
        fm = getattr(self, "_family_manager", None)
        if not fm:
            return {"success": False, "message": "Family Manager nicht verfuegbar."}

        action = args.get("action", "")

        if action == "add_member":
            return await fm.add_member(
                name=args.get("name", ""),
                relationship=args.get("relationship", "other"),
                birth_year=args.get("birth_year", 0),
                interests=args.get("interests", ""),
            )
        elif action == "list_members":
            members = await fm.get_all_members()
            if not members:
                return {"success": True, "message": "Noch keine Familienmitglieder eingetragen."}
            lines = []
            for m in members:
                name = m.get("name", "?").title()
                rel = m.get("relationship", "")
                interests = m.get("interests", "")
                rel_hint = f" ({rel})" if rel and rel != "other" else ""
                int_hint = f" - Interessen: {interests}" if interests else ""
                lines.append(f"- {name}{rel_hint}{int_hint}")
            return {"success": True, "message": "Familie:\n" + "\n".join(lines)}
        elif action == "get_member":
            member = await fm.get_member(args.get("name", ""))
            if not member:
                return {"success": False, "message": f"{args.get('name', '?')} nicht gefunden."}
            lines = [f"{k}: {v}" for k, v in member.items() if v and k != "name_key"]
            return {"success": True, "message": "\n".join(lines)}
        elif action == "update_member":
            kwargs = {}
            for field in ("relationship", "birth_year", "interests"):
                if field in args:
                    kwargs[field] = args[field]
            return await fm.update_member(name=args.get("name", ""), **kwargs)
        elif action == "remove_member":
            return await fm.remove_member(name=args.get("name", ""))
        elif action == "send_family_message":
            return await fm.send_family_message(
                message=args.get("message", ""),
                group=args.get("group", "all"),
            )
        elif action == "create_group":
            return await fm.create_group(
                group_name=args.get("group", ""),
                members=args.get("members", []),
            )

        return {"success": False, "message": f"Unbekannte Aktion: {action}"}

    async def _exec_get_personal_dates(self, args: dict) -> dict:
        """Anstehende persoenliche Termine abfragen."""
        pd = getattr(self, "_personal_dates", None)
        if not pd:
            return {"success": False, "message": "Personal Dates nicht verfuegbar."}

        person = args.get("person", "")
        days_ahead = args.get("days_ahead", 30)

        if person:
            dates = await pd.get_person_dates(person)
            if not dates:
                return {
                    "success": True,
                    "message": f"Keine gespeicherten Termine fuer {person}.",
                }
        else:
            dates = await pd.get_upcoming_dates(days_ahead)
            if not dates:
                return {
                    "success": True,
                    "message": f"Keine persoenlichen Termine in den naechsten {days_ahead} Tagen.",
                }

        lines = []
        for d in dates:
            person_name = d.get("person", "?").title()
            date_type = d.get("date_type", "")
            label = d.get("label", "")
            date_mm_dd = d.get("date_mm_dd", "")
            days_until = d.get("days_until")

            type_text = label or {
                "birthday": "Geburtstag",
                "anniversary": "Jahrestag",
                "wedding": "Hochzeitstag",
            }.get(date_type, date_type or "Termin")

            time_hint = ""
            if days_until is not None:
                if days_until == 0:
                    time_hint = " (HEUTE!)"
                elif days_until == 1:
                    time_hint = " (morgen)"
                elif days_until <= 7:
                    time_hint = f" (in {days_until} Tagen)"

            lines.append(f"- {person_name}: {type_text} am {date_mm_dd}{time_hint}")

        return {"success": True, "message": "Persoenliche Termine:\n" + "\n".join(lines)}

    async def _exec_manage_meals(self, args: dict) -> dict:
        """Essensplanung verwalten."""
        mp = getattr(self, "_meal_planner", None)
        if not mp:
            return {"success": False, "message": "Essensplanung nicht verfuegbar."}

        action = args.get("action", "")

        if action == "suggest":
            return await mp.suggest_from_inventory(
                portions=args.get("portions", 0),
            )
        elif action == "weekly_plan":
            return await mp.create_weekly_plan(
                preferences=args.get("preferences", ""),
                portions=args.get("portions", 0),
            )
        elif action == "log_meal":
            return await mp.log_meal(
                meal=args.get("meal", ""),
                meal_type=args.get("meal_type", "abendessen"),
                portions=args.get("portions", 0),
                rating=args.get("rating", 0),
            )
        elif action == "history":
            return await mp.get_meal_history(
                days=args.get("days", 7),
            )
        elif action == "check_ingredients":
            return await mp.add_missing_to_shopping(
                recipe_ingredients=args.get("ingredients", []),
            )
        elif action == "current_plan":
            return await mp.get_current_plan()

        return {"success": False, "message": f"Unbekannte Aktion: {action}"}
