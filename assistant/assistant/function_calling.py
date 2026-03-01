"""
Function Calling - Definiert und fuehrt Funktionen aus die der Assistent nutzen kann.
MindHome Assistant ruft ueber diese Funktionen Home Assistant Aktionen aus.

Phase 10: Room-aware TTS, Person Messaging, Trust-Level Pre-Check.
"""

import copy
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

import assistant.config as cfg_module
from .config import settings, yaml_config, get_room_profiles
from .config_versioning import ConfigVersioning
from .ha_client import HomeAssistantClient

# ============================================================
# KERN-SCHUTZ: JARVIS darf seinen eigenen Kern NICHT aendern.
# - settings.yaml ist NICHT in _EDITABLE_CONFIGS
# - Kein exec/eval/subprocess/os.system in Tool-Pfaden
# - _EDITABLE_CONFIGS ist eine geschlossene Whitelist
# - Neue editierbare Configs MUESSEN hier explizit freigeschaltet werden
# - Immutable Keys (security, trust_levels, autonomy, models, dashboard)
#   sind in self_optimization.py per hardcoded frozenset geschuetzt
# ============================================================

# Config-Pfade fuer Phase 13.1 (Whitelist — nur diese darf Jarvis aendern)
_CONFIG_DIR = Path(__file__).parent.parent / "config"
_EDITABLE_CONFIGS = {
    "easter_eggs": _CONFIG_DIR / "easter_eggs.yaml",
    "opinion_rules": _CONFIG_DIR / "opinion_rules.yaml",
    "room_profiles": _CONFIG_DIR / "room_profiles.yaml",
}

logger = logging.getLogger(__name__)

# Room-Profiles: zentraler Cache aus config.py
_get_room_profiles = get_room_profiles


# ── Entity-Katalog: Echte Raum- und Entity-Namen fuer Tool-Beschreibungen ──
# Wird asynchron aus HA geladen und gecached (TTL 5 Min).
# Raumnamen kommen zusaetzlich aus room_profiles.yaml (immer verfuegbar).
_entity_catalog: dict[str, list[str]] = {}
_entity_catalog_ts: float = 0.0
_CATALOG_TTL = 300  # 5 Minuten

# ── MindHome Domain-Mapping: Entity-ID → Domain-Name ──
# Wird aus /api/devices + /api/domains geladen.
# Damit weiss der Assistant z.B. dass "switch.steckdose_fenster" eine "switch" Domain
# ist und KEIN "door_window" (Fenster-Kontakt).
_mindhome_device_domains: dict[str, str] = {}  # ha_entity_id → domain_name
_mindhome_device_rooms: dict[str, str] = {}    # ha_entity_id → room_name
_mindhome_rooms: list[str] = []                # Raumnamen aus MindHome


def _get_config_rooms() -> list[str]:
    """Liefert Raumnamen aus room_profiles.yaml (gecached)."""
    profiles = _get_room_profiles()
    return sorted(profiles.get("rooms", {}).keys())


async def _load_mindhome_domains(ha: HomeAssistantClient) -> None:
    """Laedt Geraete-Domains und Raeume von der MindHome Add-on API.

    Endpunkte:
      GET /api/domains → [{id, name, display_name_de, ...}]
      GET /api/devices → [{ha_entity_id, domain_id, room_id, name, ...}]
      GET /api/rooms   → [{id, name, ...}]

    Ergebnis wird in _mindhome_device_domains und _mindhome_rooms gecached.
    Damit weiss der Assistant z.B. dass "switch.steckdose_fenster" zur Domain
    "switch" gehoert und KEIN Fenster-Kontakt (door_window) ist.
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
            "MindHome Domain-Mapping geladen: %d Geraete, %d Raeume, %d Domains",
            len(device_domains), len(_mindhome_rooms), len(domain_map),
        )
    except Exception as e:
        logger.debug("MindHome Domain-Mapping nicht verfuegbar: %s", e)


def get_mindhome_domain(entity_id: str) -> str:
    """Gibt die MindHome-Domain fuer eine Entity-ID zurueck (z.B. 'door_window', 'switch').

    Wenn keine MindHome-Zuordnung existiert, wird '' zurueckgegeben.
    """
    return _mindhome_device_domains.get(entity_id, "")


def get_mindhome_room(entity_id: str) -> str:
    """Gibt den MindHome-Raum fuer eine Entity-ID zurueck."""
    return _mindhome_device_rooms.get(entity_id, "")


def is_window_or_door(entity_id: str, state: dict) -> bool:
    """Prueft zuverlaessig ob eine Entity ein Fenster/Tuer/Tor-Kontakt ist.

    Prueft in dieser Reihenfolge (erste Uebereinstimmung gewinnt):
    1. opening_sensors Config (explizit vom User konfiguriert)
    2. MindHome Domain-Zuordnung (vom User konfiguriert)
    3. HA device_class (automatisch von HA gesetzt)
    4. Fallback: binary_sensor mit window/door/fenster/tuer/tor/gate im entity_id

    Steckdosen, Schalter und Lichter werden NICHT als Fenster erkannt,
    auch wenn "fenster" im Entity-Namen vorkommt.
    """
    # 1. opening_sensors Config (zuverlaessigste Quelle)
    cfg = get_opening_sensor_config(entity_id)
    if cfg:
        return True

    # 2. MindHome-Domain (vom User konfiguriert)
    mh_domain = _mindhome_device_domains.get(entity_id, "")
    if mh_domain:
        return mh_domain == "door_window"

    # 3. HA device_class
    attrs = state.get("attributes", {}) if isinstance(state, dict) else {}
    device_class = attrs.get("device_class", "")
    if device_class in ("window", "door", "garage_door"):
        return True

    # 4. Fallback: Nur binary_sensor mit Keyword (inkl. Tor/Gate)
    ha_domain = entity_id.split(".")[0] if "." in entity_id else ""
    if ha_domain == "binary_sensor":
        lower_id = entity_id.lower()
        if any(kw in lower_id for kw in ("window", "door", "fenster", "tuer", "tor", "gate")):
            return True

    return False


def get_opening_sensor_config(entity_id: str) -> dict:
    """Liefert die Konfiguration eines Oeffnungs-Sensors (Fenster/Tuer/Tor).

    Liest aus settings.yaml → opening_sensors.entities.
    Gibt Defaults zurueck wenn kein Eintrag existiert.
    """
    from .config import yaml_config
    entities = yaml_config.get("opening_sensors", {}).get("entities", {}) or {}
    return entities.get(entity_id, {})


# --- Entity-Annotations: Beschreibungen + Rollen fuer Sensoren/Aktoren ---

# Standard-Rollen (vordefiniert, User kann eigene in entity_roles hinzufuegen)
_DEFAULT_ROLES_DICT = {
    # --- Temperatur & Klima ---
    "indoor_temp":    {"label": "Raumtemperatur", "icon": "\U0001f321\ufe0f"},
    "outdoor_temp":   {"label": "Aussentemperatur", "icon": "\U0001f324\ufe0f"},
    "water_temp":     {"label": "Wassertemperatur", "icon": "\U0001f30a"},
    "soil_temp":      {"label": "Bodentemperatur", "icon": "\U0001f33f"},
    "humidity":       {"label": "Luftfeuchtigkeit", "icon": "\U0001f4a7"},
    "pressure":       {"label": "Luftdruck", "icon": "\U0001f4a8"},
    "dew_point":      {"label": "Taupunkt", "icon": "\U0001f4a7"},
    # --- Luftqualitaet ---
    "co2":            {"label": "CO2-Sensor", "icon": "\U0001f32c\ufe0f"},
    "co":             {"label": "CO-Melder", "icon": "\u26a0\ufe0f"},
    "voc":            {"label": "VOC-Sensor (fluechtige Stoffe)", "icon": "\U0001f4a8"},
    "pm25":           {"label": "Feinstaub PM2.5", "icon": "\U0001f32b\ufe0f"},
    "pm10":           {"label": "Feinstaub PM10", "icon": "\U0001f32b\ufe0f"},
    "air_quality":    {"label": "Luftqualitaet", "icon": "\U0001f343"},
    "radon":          {"label": "Radon", "icon": "\u2622\ufe0f"},
    # --- Wetter ---
    "wind_speed":     {"label": "Windgeschwindigkeit", "icon": "\U0001f4a8"},
    "wind_direction": {"label": "Windrichtung", "icon": "\U0001f9ed"},
    "rain":           {"label": "Niederschlag/Regen", "icon": "\U0001f327\ufe0f"},
    "rain_sensor":    {"label": "Regensensor", "icon": "\U0001f327\ufe0f"},
    "uv_index":       {"label": "UV-Index", "icon": "\u2600\ufe0f"},
    "solar_radiation": {"label": "Sonneneinstrahlung", "icon": "\u2600\ufe0f"},
    # --- Licht & Helligkeit ---
    "light":          {"label": "Beleuchtung", "icon": "\U0001f4a1"},
    "dimmer":         {"label": "Dimmer", "icon": "\U0001f4a1"},
    "color_light":    {"label": "Farblicht/RGB", "icon": "\U0001f308"},
    "light_level":    {"label": "Lichtsensor", "icon": "\u2600\ufe0f"},
    # --- Sicherheit & Alarm ---
    "smoke":          {"label": "Rauchmelder", "icon": "\U0001f525"},
    "gas":            {"label": "Gasmelder", "icon": "\u26a0\ufe0f"},
    "water_leak":     {"label": "Wassermelder", "icon": "\U0001f6b0"},
    "tamper":         {"label": "Manipulationserkennung", "icon": "\U0001f6a8"},
    "alarm":          {"label": "Alarmanlage", "icon": "\U0001f6a8"},
    "siren":          {"label": "Sirene", "icon": "\U0001f4e2"},
    # --- Tueren, Fenster, Oeffnungen ---
    "window_contact": {"label": "Fensterkontakt", "icon": "\U0001fa9f"},
    "door_contact":   {"label": "Tuerkontakt", "icon": "\U0001f6aa"},
    "garage_door":    {"label": "Garagentor", "icon": "\U0001f3e0"},
    "gate":           {"label": "Tor/Einfahrt", "icon": "\U0001f3e0"},
    "lock":           {"label": "Schloss", "icon": "\U0001f510"},
    "doorbell":       {"label": "Tuerklingel", "icon": "\U0001f514"},
    # --- Bewegung & Anwesenheit ---
    "motion":         {"label": "Bewegungsmelder", "icon": "\U0001f3c3"},
    "presence":       {"label": "Anwesenheit", "icon": "\U0001f464"},
    "occupancy":      {"label": "Raumbelegung", "icon": "\U0001f465"},
    "bed_occupancy":  {"label": "Bettbelegung", "icon": "\U0001f6cf\ufe0f"},
    "vibration":      {"label": "Vibration", "icon": "\U0001f4f3"},
    # --- Energie & Strom ---
    "power_meter":    {"label": "Strommesser", "icon": "\u26a1"},
    "energy":         {"label": "Energiezaehler", "icon": "\U0001f4ca"},
    "voltage":        {"label": "Spannung", "icon": "\u26a1"},
    "current":        {"label": "Stromstaerke", "icon": "\u26a1"},
    "power_factor":   {"label": "Leistungsfaktor", "icon": "\U0001f4ca"},
    "frequency":      {"label": "Frequenz", "icon": "\U0001f4ca"},
    "battery":        {"label": "Batterie", "icon": "\U0001f50b"},
    "battery_charging": {"label": "Batterie laden", "icon": "\U0001f50b"},
    "solar":          {"label": "Solaranlage/PV", "icon": "\u2600\ufe0f"},
    "grid_feed":      {"label": "Netzeinspeisung", "icon": "\u26a1"},
    "grid_consumption": {"label": "Netzbezug", "icon": "\u26a1"},
    # --- Gas & Wasser Verbrauch ---
    "gas_consumption": {"label": "Gasverbrauch", "icon": "\U0001f525"},
    "water_consumption": {"label": "Wasserverbrauch", "icon": "\U0001f4a7"},
    # --- Heizung, Kuehlung, Klima ---
    "thermostat":     {"label": "Thermostat", "icon": "\U0001f321\ufe0f"},
    "heating":        {"label": "Heizung", "icon": "\U0001f525"},
    "cooling":        {"label": "Kuehlung", "icon": "\u2744\ufe0f"},
    "heat_pump":      {"label": "Waermepumpe", "icon": "\U0001f504"},
    "boiler":         {"label": "Warmwasserboiler", "icon": "\U0001f6bf"},
    "radiator":       {"label": "Heizkoerper", "icon": "\U0001f321\ufe0f"},
    "floor_heating":  {"label": "Fussbodenheizung", "icon": "\U0001f321\ufe0f"},
    # --- Lueftung ---
    "fan":            {"label": "Luefter", "icon": "\U0001f300"},
    "ventilation":    {"label": "Lueftungsanlage", "icon": "\U0001f32c\ufe0f"},
    "air_purifier":   {"label": "Luftreiniger", "icon": "\U0001f343"},
    "dehumidifier":   {"label": "Entfeuchter", "icon": "\U0001f4a7"},
    "humidifier":     {"label": "Befeuchter", "icon": "\U0001f4a7"},
    # --- Beschattung ---
    "blinds":         {"label": "Rolladen/Jalousie", "icon": "\U0001fa9f"},
    "shutter":        {"label": "Rollladen", "icon": "\U0001fa9f"},
    "awning":         {"label": "Markise", "icon": "\u2602\ufe0f"},
    "curtain":        {"label": "Vorhang", "icon": "\U0001fa9f"},
    # --- Steckdosen & Aktoren ---
    "outlet":         {"label": "Steckdose", "icon": "\U0001f50c"},
    "valve":          {"label": "Ventil", "icon": "\U0001f527"},
    "pump":           {"label": "Pumpe", "icon": "\U0001f504"},
    "motor":          {"label": "Motor", "icon": "\u2699\ufe0f"},
    "relay":          {"label": "Relais", "icon": "\U0001f50c"},
    # --- Garten & Aussen ---
    "irrigation":     {"label": "Bewaesserung", "icon": "\U0001f331"},
    "pool":           {"label": "Pool/Schwimmbad", "icon": "\U0001f3ca"},
    "soil_moisture":  {"label": "Bodenfeuchtigkeit", "icon": "\U0001f331"},
    "garden_light":   {"label": "Gartenbeleuchtung", "icon": "\U0001f33b"},
    # --- Medien & Unterhaltung ---
    "tv":             {"label": "Fernseher", "icon": "\U0001f4fa"},
    "speaker":        {"label": "Lautsprecher", "icon": "\U0001f50a"},
    "media_player":   {"label": "Mediaplayer", "icon": "\u25b6\ufe0f"},
    "receiver":       {"label": "AV-Receiver", "icon": "\U0001f3b5"},
    "projector":      {"label": "Beamer/Projektor", "icon": "\U0001f4fd\ufe0f"},
    "gaming":         {"label": "Spielkonsole", "icon": "\U0001f3ae"},
    # --- Kommunikation ---
    "phone":          {"label": "Telefon", "icon": "\U0001f4de"},
    # --- Netzwerk & IT ---
    "router":         {"label": "Router", "icon": "\U0001f4f6"},
    "server":         {"label": "Server", "icon": "\U0001f5a5\ufe0f"},
    "nas":            {"label": "NAS-Speicher", "icon": "\U0001f4be"},
    "printer":        {"label": "Drucker", "icon": "\U0001f5a8\ufe0f"},
    "pc":             {"label": "PC/Computer", "icon": "\U0001f4bb"},
    "adblocker":      {"label": "Adblocker", "icon": "\U0001f6e1\ufe0f"},
    "speedtest":      {"label": "Internet-Geschwindigkeit", "icon": "\U0001f4f6"},
    "signal_strength": {"label": "Signalstaerke", "icon": "\U0001f4f6"},
    "connectivity":   {"label": "Verbindungsstatus", "icon": "\U0001f4f6"},
    # --- Haushaltsgeraete ---
    "washing_machine": {"label": "Waschmaschine", "icon": "\U0001f9f9"},
    "dryer":          {"label": "Trockner", "icon": "\U0001f32c\ufe0f"},
    "dishwasher":     {"label": "Spuelmaschine", "icon": "\U0001f37d\ufe0f"},
    "oven":           {"label": "Backofen", "icon": "\U0001f373"},
    "fridge":         {"label": "Kuehlschrank", "icon": "\u2744\ufe0f"},
    "freezer":        {"label": "Gefrierschrank", "icon": "\u2744\ufe0f"},
    "vacuum":         {"label": "Staubsauger-Roboter", "icon": "\U0001f9f9"},
    "coffee_machine": {"label": "Kaffeemaschine", "icon": "\u2615"},
    "charger":        {"label": "Ladegeraet", "icon": "\U0001f50b"},
    # --- Fahrzeuge ---
    "ev_charger":     {"label": "Wallbox/E-Auto-Lader", "icon": "\U0001f50c"},
    "car":            {"label": "Auto/Fahrzeug", "icon": "\U0001f697"},
    "car_battery":    {"label": "Auto-Batterie/SoC", "icon": "\U0001f50b"},
    "car_location":   {"label": "Fahrzeug-Standort", "icon": "\U0001f4cd"},
    # --- Ueberwachung ---
    "camera":         {"label": "Kamera", "icon": "\U0001f4f7"},
    "intercom":       {"label": "Gegensprechanlage", "icon": "\U0001f4de"},
    # --- Sonstiges ---
    "scene":          {"label": "Szene", "icon": "\U0001f3ac"},
    "automation":     {"label": "Automatisierung", "icon": "\u2699\ufe0f"},
    "timer":          {"label": "Timer/Zaehler", "icon": "\u23f0"},
    "counter":        {"label": "Zaehler", "icon": "\U0001f522"},
    "distance":       {"label": "Entfernung", "icon": "\U0001f4cf"},
    "speed":          {"label": "Geschwindigkeit", "icon": "\U0001f4a8"},
    "weight":         {"label": "Gewicht/Waage", "icon": "\u2696\ufe0f"},
    "noise":          {"label": "Laermsensor", "icon": "\U0001f50a"},
    "problem":        {"label": "Problem/Stoerung", "icon": "\u26a0\ufe0f"},
    "update":         {"label": "Update verfuegbar", "icon": "\U0001f504"},
    "running":        {"label": "Geraet laeuft", "icon": "\u25b6\ufe0f"},
    "generic_sensor": {"label": "Sensor (allgemein)", "icon": "\U0001f4cb"},
    "generic_switch": {"label": "Schalter (allgemein)", "icon": "\U0001f4a1"},
}

_DEFAULT_ROLES = set(_DEFAULT_ROLES_DICT.keys())

# Auto-Erkennung: device_class → role (fuer Discovery-Endpoint)
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
    "gas": "gas",
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
    # Verbrauch
    "gas": "gas_consumption",
    "water": "water_consumption",
    # Geraete
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

_OUTDOOR_KEYWORDS = ("aussen", "outdoor", "balkon", "garten", "terrasse", "draussen", "exterior")
_WATER_TEMP_KEYWORDS = ("wasser", "water", "boiler", "pool")
_SOIL_TEMP_KEYWORDS = ("boden", "soil", "erde", "ground")

# Role-Keywords fuer natuerliche Sprache → Role-Matching in _find_entity()
_ROLE_KEYWORDS = {
    # Temperatur
    "outdoor_temp": ["aussen", "draussen", "outdoor", "balkon", "aussentemperatur", "gartentemperatur"],
    "indoor_temp": ["innen", "raum", "drinnen", "raumtemperatur", "zimmertemperatur"],
    "water_temp": ["wassertemperatur", "boiler", "warmwasser", "pooltemperatur"],
    "soil_temp": ["bodentemperatur", "erdtemperatur"],
    # Klima
    "humidity": ["feuchtigkeit", "feuchte", "luftfeuchte", "luftfeuchtigkeit"],
    "pressure": ["luftdruck", "druck", "barometer"],
    # Luftqualitaet
    "co2": ["co2", "kohlendioxid"],
    "co": ["kohlenmonoxid", "co-melder"],
    "voc": ["voc", "fluechtige", "organische"],
    "pm25": ["feinstaub", "pm2.5", "pm25", "partikel"],
    "air_quality": ["luftqualitaet", "luft qualitaet", "aqi"],
    # Wetter
    "wind_speed": ["wind", "windgeschwindigkeit", "windstaerke"],
    "rain": ["regen", "niederschlag", "rain"],
    "uv_index": ["uv", "uv-index", "sonnenbrand"],
    # Sicherheit
    "smoke": ["rauch", "rauchmelder"],
    "gas": ["gas", "gasmelder", "erdgas"],
    "water_leak": ["wasserleck", "leck", "wassermelder", "ueberschwemmung"],
    "alarm": ["alarm", "alarmanlage", "einbruch"],
    "tamper": ["manipulation", "tamper", "sabotage"],
    # Oeffnungen
    "window_contact": ["fenster", "window"],
    "door_contact": ["tuer", "tuerkontakt", "door", "haustuer", "eingangstuer"],
    "garage_door": ["garage", "garagentor"],
    "gate": ["tor", "einfahrt", "gate"],
    "lock": ["schloss", "verriegelt", "lock"],
    "doorbell": ["klingel", "tuerklingel", "doorbell"],
    # Bewegung
    "motion": ["bewegung", "motion", "bewegungsmelder"],
    "presence": ["anwesenheit", "zuhause", "abwesend", "presence"],
    "occupancy": ["belegung", "besetzt", "raumbelegung"],
    "bed_occupancy": ["bett", "bettbelegung", "bett sensor", "bed", "bed_occupancy", "schlafsensor"],
    # Energie
    "power_meter": ["strom", "leistung", "watt", "strommesser"],
    "energy": ["energie", "kwh", "energieverbrauch", "stromverbrauch"],
    "voltage": ["spannung", "volt"],
    "battery": ["batterie", "akku"],
    "solar": ["solar", "photovoltaik", "pv", "solaranlage"],
    "ev_charger": ["wallbox", "ladestation", "e-auto", "elektroauto"],
    # Verbrauch
    "gas_consumption": ["gasverbrauch", "gasverbrauch", "kubikmeter"],
    "water_consumption": ["wasserverbrauch"],
    # Heizung & Klima
    "thermostat": ["thermostat"],
    "heating": ["heizung", "heizen"],
    "cooling": ["kuehlung", "kuehlen", "klimaanlage"],
    "heat_pump": ["waermepumpe"],
    "boiler": ["boiler", "warmwasserspeicher"],
    "radiator": ["heizkoerper", "radiator"],
    "floor_heating": ["fussbodenheizung", "fbh"],
    # Lueftung
    "fan": ["luefter", "ventilator"],
    "ventilation": ["lueftung", "lueftungsanlage", "kwl"],
    "air_purifier": ["luftreiniger", "luftfilter"],
    # Beschattung
    "blinds": ["rolladen", "jalousie", "rollo"],
    "shutter": ["rollladen"],
    "awning": ["markise"],
    "curtain": ["vorhang", "gardine"],
    # Steckdosen & Aktoren
    "outlet": ["steckdose", "stecker"],
    "valve": ["ventil"],
    "pump": ["pumpe"],
    # Garten
    "irrigation": ["bewaesserung", "sprinkler", "gartenschlauch"],
    "pool": ["pool", "schwimmbad", "whirlpool"],
    "soil_moisture": ["bodenfeuchtigkeit", "erdfeuchte"],
    # Medien
    "tv": ["fernseher", "tv", "television"],
    "speaker": ["lautsprecher", "speaker", "box"],
    "media_player": ["mediaplayer", "player", "streamer"],
    "receiver": ["receiver", "verstaerker", "av-receiver"],
    # Kommunikation
    "phone": ["telefon", "phone", "sip", "anruf", "festnetz", "voip"],
    # Netzwerk
    "router": ["router", "wlan", "wifi"],
    "server": ["server"],
    "nas": ["nas", "netzwerkspeicher"],
    "pc": ["pc", "computer", "desktop", "rechner", "workstation"],
    "adblocker": ["adblocker", "adblock", "adguard", "pihole", "werbeblocker"],
    "speedtest": ["speedtest", "internetgeschwindigkeit", "internet speed", "internet geschwindigkeit", "bandbreite", "download speed", "upload speed"],
    # Haushaltsgeraete
    "washing_machine": ["waschmaschine", "waschen"],
    "dryer": ["trockner"],
    "dishwasher": ["spuelmaschine", "geschirrspueler"],
    "vacuum": ["staubsauger", "saugroboter", "roborock"],
    "coffee_machine": ["kaffeemaschine", "kaffee", "espresso"],
    # Fahrzeuge
    "car": ["auto", "fahrzeug", "pkw"],
    "car_battery": ["autobatterie", "soc", "ladestand"],
    # Ueberwachung
    "camera": ["kamera", "ueberwachung", "cam"],
}


def get_entity_annotation(entity_id: str) -> dict:
    """Liefert die Annotation fuer eine Entity aus settings.yaml.

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


def get_all_roles() -> dict:
    """Liefert Standard-Rollen + eigene Rollen. Eigene ueberschreiben Standard."""
    roles = dict(_DEFAULT_ROLES_DICT)
    custom = yaml_config.get("entity_roles", {}) or {}
    roles.update(custom)
    return roles


def get_valid_roles() -> set:
    """Liefert alle gueltigen Rollen-IDs (Standard + eigene)."""
    custom_roles = set((yaml_config.get("entity_roles", {}) or {}).keys())
    return _DEFAULT_ROLES | custom_roles


def auto_detect_role(domain: str, device_class: str, unit: str, entity_id: str) -> str:
    """Erkennt die Rolle einer Entity aus HA-Attributen (fuer Discovery-Vorschlaege)."""
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
        if device_class in ("pressure", "atmospheric_pressure") or unit in ("hPa", "mbar"):
            return "pressure"
        # Luftqualitaet
        if device_class in ("co2", "carbon_dioxide") or (unit == "ppm" and "co2" in lower_eid):
            return "co2"
        if device_class == "carbon_monoxide":
            return "co"
        if device_class in ("volatile_organic_compounds", "volatile_organic_compounds_parts"):
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
        if device_class == "gas" or unit in ("m\u00b3",) and "gas" in lower_eid:
            return "gas_consumption"
        if device_class == "water" or unit in ("L", "m\u00b3") and "water" in lower_eid:
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
        if any(kw in lower_eid for kw in ("ventilat", "lueft", "fan")):
            return "fan"
        if any(kw in lower_eid for kw in ("bewaesser", "irrigat", "sprinkl")):
            return "irrigation"
        if any(kw in lower_eid for kw in ("ventil", "valve")):
            return "valve"
        if any(kw in lower_eid for kw in ("steckdose", "plug", "socket")):
            return "outlet"
        if any(kw in lower_eid for kw in ("pump", "pumpe")):
            return "pump"
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
        return ""

    if domain == "lock":
        return "lock"

    if domain == "light":
        # Farblicht vs Dimmer vs einfaches Licht (kann nur per Attribute unterschieden werden)
        if any(kw in lower_eid for kw in ("rgb", "color", "farb", "hue", "strip", "led_strip")):
            return "color_light"
        if any(kw in lower_eid for kw in ("dimm", "dim_")):
            return "dimmer"
        if any(kw in lower_eid for kw in ("garten", "garden", "aussen", "outdoor", "terrass")):
            return "garden_light"
        return "light"

    if domain == "fan":
        return "fan"

    if domain == "vacuum":
        return "vacuum"

    if domain == "camera":
        return "camera"

    if domain == "media_player":
        if any(kw in lower_eid for kw in ("tv", "fernseh", "television", "fire_tv", "apple_tv", "chromecast")):
            return "tv"
        if any(kw in lower_eid for kw in ("receiver", "avr", "denon", "marantz", "yamaha")):
            return "receiver"
        if any(kw in lower_eid for kw in ("sonos", "speaker", "echo", "homepod", "lautsprecher")):
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
    if any(kw in lower_id for kw in ("tor", "gate", "garage")):
        return "gate"
    if any(kw in lower_id for kw in ("tuer", "door")):
        return "door"
    return "window"


def is_heating_relevant_opening(entity_id: str, state: dict) -> bool:
    """Prueft ob ein Oeffnungs-Sensor heizungsrelevant ist.

    Ein Sensor ist heizungsrelevant wenn:
    - Er ein Fenster oder eine Tuer ist (NICHT ein Tor/Gate)
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

    # Fenster und Tueren sind standardmaessig heizungsrelevant
    return True


async def refresh_entity_catalog(ha: HomeAssistantClient) -> None:
    """Laedt verfuegbare Entities aus HA und cached Raum-/Geraete-Namen.

    Wird periodisch aufgerufen (z.B. alle 5 Min) um Tool-Beschreibungen
    mit echten Entity-Namen anzureichern.

    Laedt zusaetzlich Domain-Zuordnungen von der MindHome API,
    damit der Assistant weiss welche Geraete Fenster, Steckdosen, etc. sind.
    """
    global _entity_catalog, _entity_catalog_ts

    # MindHome Domain-Mapping laden (parallel zum HA-States-Abruf)
    import asyncio
    states_task = ha.get_states()
    mindhome_task = _load_mindhome_domains(ha)
    states, _ = await asyncio.gather(states_task, mindhome_task, return_exceptions=True)

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

        # Hidden-Entities ueberspringen
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
            # Nur explizit annotierte Sensors/Binary-Sensors im Katalog
            role = ann.get("role", "")
            if role:
                role_label = all_roles.get(role, {}).get("label", role)
                desc = ann.get("description", friendly or name)
                entry = f"{name} ({desc}) [{role_label}]"
                if domain == "sensor":
                    sensors.append(entry)
                else:
                    binary_sensors.append(entry)

    # Config-Raeume immer hinzufuegen
    for r in _get_config_rooms():
        rooms.add(r)
    # MindHome-Raeume (User-konfiguriert) immer hinzufuegen
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
    logger.info(
        "Entity-Katalog aktualisiert: %d rooms, %d lights, %d switches, %d covers, "
        "%d sensors, %d binary_sensors, %d scenes",
        len(rooms), len(lights), len(switches), len(covers),
        len(sensors), len(binary_sensors), len(scenes),
    )


def _get_room_names() -> list[str]:
    """Liefert aktuelle Raumnamen (aus Cache oder Config-Fallback)."""
    if _entity_catalog.get("rooms"):
        return _entity_catalog["rooms"]
    return _get_config_rooms()


def _inject_entity_hints(tool: dict) -> dict:
    """Fuegt verfuegbare Raum- und Entity-Namen in Tool-Beschreibungen ein.

    - Alle Tools mit 'room'-Parameter: Raumnamen-Liste anfuegen
    - set_switch/get_switches: Verfuegbare Switches anfuegen
    - set_cover/get_covers: Verfuegbare Covers anfuegen
    - set_light/get_lights: Verfuegbare Lights anfuegen
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
    if fname == "get_entity_state":
        combined = (_entity_catalog.get("sensors", []) +
                    _entity_catalog.get("binary_sensors", []))
        if combined:
            entity_hint = ", ".join(combined[:30])
            needs_copy = True
    catalog_key = _ENTITY_MAP.get(fname)
    if catalog_key and _entity_catalog.get(catalog_key):
        entities = _entity_catalog[catalog_key]
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
        if "Verfuegbare Raeume:" in desc:
            desc = desc.split("Verfuegbare Raeume:")[0].rstrip()
        if "Verfuegbare Geraete:" in desc:
            desc = desc.split("Verfuegbare Geraete:")[0].rstrip()
        rp["description"] = f"{desc} — Verfuegbare Raeume: {room_list}"

    # Entity-Liste in die Tool-Beschreibung injizieren
    if entity_hint:
        tool_desc = tool["function"].get("description", "")
        if "Verfuegbare Geraete:" in tool_desc:
            tool_desc = tool_desc.split("Verfuegbare Geraete:")[0].rstrip()
        tool["function"]["description"] = f"{tool_desc} — Verfuegbare Geraete: {entity_hint}"

    return tool


def _get_heating_mode() -> str:
    """Liefert den konfigurierten Heizungsmodus."""
    return yaml_config.get("heating", {}).get("mode", "room_thermostat")


def _get_climate_tool_description() -> str:
    """Dynamische Tool-Beschreibung je nach Heizungsmodus."""
    if _get_heating_mode() == "heating_curve":
        return (
            "Heizung steuern: Vorlauftemperatur-Offset zur Heizkurve anpassen. "
            "Positiver Offset = waermer, negativer Offset = kaelter."
        )
    return "Temperatur in einem Raum aendern. Fuer 'waermer' verwende adjust='warmer', fuer 'kaelter' verwende adjust='cooler' (aendert um 1°C)."


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


# Ollama Tool-Definitionen (Qwen 2.5 Function Calling Format)
# ASSISTANT_TOOLS wird als Funktion gebaut, damit set_climate
# bei jedem Aufruf den aktuellen heating.mode aus yaml_config liest.
_ASSISTANT_TOOLS_STATIC = [
    {
        "type": "function",
        "function": {
            "name": "set_light",
            "description": "Licht in einem Raum ein-/ausschalten oder dimmen. Alle Lampen sind dim2warm — Farbtemperatur wird automatisch ueber die Helligkeit geregelt (Hardware). Fuer 'heller' verwende state='brighter', fuer 'dunkler' verwende state='dimmer'. Fuer Etagen: room='eg' oder room='og'. Wenn der User ein bestimmtes Licht meint (z.B. 'Stehlampe', 'Deckenlampe'), setze den device-Parameter.",
            "parameters": {
                "type": "object",
                "properties": {
                    "room": {
                        "type": "string",
                        "description": "Raumname VOLLSTAENDIG angeben inkl. Personen-Praefix falls genannt (z.B. 'buero_manuel', 'buero_julia', 'wohnzimmer', 'schlafzimmer'). NICHT den Personennamen weglassen! Fuer ganze Etage: 'eg' oder 'og'. Fuer alle: 'all'.",
                    },
                    "device": {
                        "type": "string",
                        "description": "Optionaler Geraetename wenn ein bestimmtes Licht gemeint ist (z.B. 'stehlampe', 'deckenlampe', 'nachttisch'). Ohne device wird das Hauptlicht im Raum geschaltet.",
                    },
                    "state": {
                        "type": "string",
                        "enum": ["on", "off", "brighter", "dimmer"],
                        "description": "Ein, aus, heller (+15%) oder dunkler (-15%)",
                    },
                    "brightness": {
                        "type": "integer",
                        "description": "Helligkeit 0-100 Prozent (optional, nur bei state='on'). WICHTIG: Wenn der User einen konkreten Wert nennt (z.B. 'auf 10%'), diesen EXAKT uebernehmen — NICHT den aktuellen Kontextwert verwenden. Ohne Angabe wird adaptive Helligkeit nach Tageszeit berechnet.",
                    },
                    "transition": {
                        "type": "integer",
                        "description": "Uebergangsdauer in Sekunden (optional, fuer sanftes Dimmen)",
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
            "description": "Eine Szene aktivieren (z.B. filmabend, gute_nacht, gemuetlich)",
            "parameters": {
                "type": "object",
                "properties": {
                    "scene": {
                        "type": "string",
                        "description": "Name der Szene",
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
            "description": "Rollladen oder Markise steuern. NIEMALS fuer Garagentore! action: open/close/stop/half. position: 0-100%. Fuer Etagen: room='eg' oder room='og'. Fuer Markisen: type='markise'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "room": {
                        "type": "string",
                        "description": "Raumname VOLLSTAENDIG (z.B. 'buero_manuel', 'wohnzimmer'). Fuer ganze Etage: 'eg' oder 'og'. Fuer alle: 'all'. Fuer alle Markisen: 'markisen'.",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["open", "close", "stop", "half"],
                        "description": "open=ganz oeffnen/hoch, close=ganz schliessen/runter, stop=anhalten, half=halb offen.",
                    },
                    "position": {
                        "type": "integer",
                        "description": "Exakte Position 0 (zu) bis 100 (offen). Nur fuer Prozent-Angaben.",
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
            "description": "NUR zum Abfragen: Zeigt alle Rolllaeden/Jalousien mit Name, Raum und Position (0=zu, 100=offen). NICHT zum Steuern — dafuer set_cover nutzen.",
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
            "name": "play_media",
            "description": "Musik oder Medien steuern: abspielen, pausieren, stoppen, Lautstaerke aendern. Fuer 'leiser' verwende action='volume_down', fuer 'lauter' verwende action='volume_up'. Fuer eine bestimmte Lautstaerke verwende action='volume' mit volume-Parameter.",
            "parameters": {
                "type": "object",
                "properties": {
                    "room": {
                        "type": "string",
                        "description": "Raumname (z.B. 'Wohnzimmer', 'Manuel Buero')",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["play", "pause", "stop", "next", "previous", "volume", "volume_up", "volume_down"],
                        "description": "Medien-Aktion. 'volume' = Lautstaerke auf Wert setzen, 'volume_up' = lauter (+10%), 'volume_down' = leiser (-10%)",
                    },
                    "query": {
                        "type": "string",
                        "description": "Suchanfrage fuer Musik (z.B. 'Jazz', 'Beethoven', 'Chill Playlist')",
                    },
                    "media_type": {
                        "type": "string",
                        "enum": ["music", "podcast", "audiobook", "playlist", "channel"],
                        "description": "Art des Mediums (Standard: music)",
                    },
                    "volume": {
                        "type": "number",
                        "description": "Lautstaerke 0-100 (Prozent). Nur bei action='volume'. Z.B. 20 fuer 20%, 50 fuer 50%",
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
            "description": "Smart DJ: Empfiehlt und spielt kontextbewusste Musik basierend auf Stimmung, Aktivitaet und Tageszeit. 'recommend' zeigt Vorschlag, 'play' spielt direkt ab, 'feedback' speichert Bewertung, 'status' zeigt aktuellen Kontext.",
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
                        "description": "Zielraum fuer Wiedergabe (optional)",
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
            "description": "NUR zum Abfragen: Zeigt alle Media Player mit Wiedergabestatus, Titel und Lautstaerke. NICHT zum Steuern — dafuer play_media nutzen.",
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
            "description": "Tuer ver- oder entriegeln",
            "parameters": {
                "type": "object",
                "properties": {
                    "door": {
                        "type": "string",
                        "description": "Name der Tuer",
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
            "description": "NUR zum Abfragen: Zeigt alle Steckdosen/Schalter (switch.*) mit Name, Raum und Status (an/aus). NICHT zum Steuern.",
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
                        "description": "Raum fuer TTS-Ausgabe (optional, nur bei target=speaker)",
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
                            "listening", "confirmed", "warning",
                            "alarm", "doorbell", "greeting",
                            "error", "goodnight",
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
            "description": "Status einer Home Assistant Entity abfragen. Funktioniert mit allen Entity-Typen: sensor.*, switch.*, light.*, climate.*, weather.* (z.B. weather.forecast_home fuer Wetterdaten), lock.*, media_player.*, binary_sensor.*, person.* etc.",
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
            "description": "Musik-Wiedergabe von einem Raum in einen anderen uebertragen",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_room": {
                        "type": "string",
                        "description": "Quell-Raum (wo die Musik gerade laeuft)",
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
            "description": "Kalender-Termine abrufen. Nutze dies wenn der User nach Terminen fragt, z.B. 'Was steht morgen an?', 'Was steht heute an?', 'Habe ich morgen Termine?', 'Was steht diese Woche an?'. Immer bevorzugt fuer zeitbezogene Fragen zu Plaenen und Terminen.",
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
            "description": "Einen Kalender-Termin loeschen",
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
                        "description": "Welche Konfiguration aendern (easter_eggs, opinion_rules, room_profiles)",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["add", "remove", "update"],
                        "description": "Aktion: hinzufuegen, entfernen oder aktualisieren",
                    },
                    "key": {
                        "type": "string",
                        "description": "Schluessel/Name des Eintrags (z.B. 'star_wars' fuer Easter Egg, 'high_temp' fuer Opinion)",
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
                        "description": "Artikelname (fuer add/complete)",
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
            "description": "Vorratsmanagement: Artikel mit Ablaufdatum hinzufuegen, entfernen, auflisten, Menge aendern. Warnt bei bald ablaufenden Artikeln.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add", "remove", "list", "update_quantity", "check_expiring"],
                        "description": "Aktion: hinzufuegen, entfernen, auflisten, Menge aendern, Ablauf pruefen",
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
    # --- Phase 13.2: Self Automation ---
    {
        "type": "function",
        "function": {
            "name": "create_automation",
            "description": "Erstellt eine neue Home Assistant Automation aus natuerlicher Sprache. Der User beschreibt was passieren soll, Jarvis generiert die Automation und fragt nach Bestaetigung.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Natuerlichsprachliche Beschreibung der Automation (z.B. 'Wenn ich nach Hause komme, mach das Licht an')",
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
                        "description": "ID der ausstehenden Automation (wird bei create_automation zurueckgegeben)",
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
            "description": "Setzt einen allgemeinen Timer/Erinnerung. Z.B. 'Erinnere mich in 30 Minuten an die Waesche' oder 'In 20 Minuten Licht aus'. WICHTIG: duration_minutes ist IMMER in Minuten, NIEMALS in Sekunden. '30 Sekunden' = 1 Minute (aufrunden), '5 Minuten' = 5.",
            "parameters": {
                "type": "object",
                "properties": {
                    "duration_minutes": {
                        "type": "integer",
                        "description": "Dauer in MINUTEN (1-1440). NICHT Sekunden! Wenn der User Sekunden sagt, in Minuten umrechnen (aufrunden). '30 Sekunden' → 1, '2 Minuten' → 2, '1 Stunde' → 60",
                    },
                    "label": {
                        "type": "string",
                        "description": "Bezeichnung des Timers (z.B. 'Waesche', 'Pizza', 'Anruf')",
                    },
                    "room": {
                        "type": "string",
                        "description": "Raum in dem die Timer-Benachrichtigung erfolgen soll",
                    },
                    "action_on_expire": {
                        "type": "object",
                        "description": "Optionale Aktion bei Ablauf. Format: {\"function\": \"set_light\", \"args\": {\"room\": \"kueche\", \"state\": \"off\"}}",
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
                        "description": "Bezeichnung des Timers zum Abbrechen (z.B. 'Waesche')",
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
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": "Setzt eine Erinnerung fuer eine bestimmte Uhrzeit. Z.B. 'Erinnere mich um 15 Uhr an den Anruf' oder 'Um 18:30 Abendessen kochen'.",
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
                        "description": "Datum im Format YYYY-MM-DD. Wenn leer, wird heute oder morgen automatisch gewaehlt.",
                    },
                    "room": {
                        "type": "string",
                        "description": "Raum fuer die TTS-Benachrichtigung",
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
            "description": "Stellt einen Wecker fuer eine bestimmte Uhrzeit. Z.B. 'Weck mich um 6:30' oder 'Stell einen Wecker fuer 7 Uhr'.",
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
                        "description": "Raum in dem geweckt werden soll (fuer Licht + TTS)",
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
                        "description": "Bezeichnung des Weckers zum Loeschen",
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
            "description": "Sendet eine Durchsage an ALLE Lautsprecher im Haus. Fuer Ankuendigungen wie 'Essen ist fertig!' oder 'Bitte alle runterkommen.'",
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
            "description": "Gezielte Durchsage an eine bestimmte Person oder einen bestimmten Raum. Fuer 'Sag Julia dass das Essen fertig ist' oder 'Durchsage im Wohnzimmer: Komm mal bitte'. Fuer Durchsagen an ALLE verwende stattdessen 'broadcast'.",
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
            "description": "Holt und beschreibt ein Kamera-Bild. Z.B. 'Wer ist an der Tuer?' oder 'Zeig mir die Garage'.",
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
                        "enum": ["state_change", "person_arrives", "person_leaves", "state_attribute"],
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
                        "description": "Argumente fuer die Aktion",
                    },
                    "label": {
                        "type": "string",
                        "description": "Beschreibung (z.B. 'Rolladen bei Regen runter')",
                    },
                    "ttl_hours": {
                        "type": "integer",
                        "description": "Gueltigkeitsdauer in Stunden (default 24, max 168)",
                    },
                    "one_shot": {
                        "type": "boolean",
                        "description": "Nur einmal ausfuehren (default true)",
                    },
                },
                "required": ["trigger_type", "trigger_value", "action_function", "action_args"],
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
            "description": "Sucht im Internet nach Informationen. Nur fuer Wissensfragen die nicht aus dem Gedaechtnis beantwortet werden koennen. Z.B. 'Was ist die Hauptstadt von Australien?' oder 'Aktuelle Nachrichten'.",
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
            "description": "Zeigt den aktuellen Sicherheits-Score des Hauses (0-100). Prueft offene Tueren, Fenster, Schloesser, Rauchmelder und Wassersensoren. Nutze dies wenn der User nach Sicherheit, Haus-Status oder offenen Tueren/Fenstern fragt.",
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
            "description": "Zeigt gemerkte Vorhaben die aus frueheren Gespraechen erkannt wurden, z.B. 'Eltern kommen am Wochenende'. Nutze dies NUR wenn der User explizit nach gemerkten Vorhaben fragt, z.B. 'Was habe ich mir vorgenommen?', 'Was hast du dir gemerkt?'. NICHT fuer Kalender-Termine oder 'Was steht morgen an?' verwenden.",
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
            "description": "Zeigt den Geraete-Gesundheitsstatus: Anomalien, inaktive Sensoren, HVAC-Effizienz. Nutze dies wenn der User nach Hardware-Problemen, Geraete-Status oder Sensor-Zustand fragt.",
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
            "description": "Gibt den kompletten Haus-Status zurueck: Temperaturen, Lichter, Anwesenheit, Wetter, Sicherheit, offene Fenster/Tueren, Medien, offline Geraete. IMMER nutzen wenn der User nach Hausstatus, Status, Ueberblick oder Zusammenfassung fragt.",
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
            "description": "Narrativer JARVIS-Statusbericht: Hausstatus, Termine, Wetter, Energie, offene Erinnerungen — alles in einem kurzen Briefing. Fuer 'Statusbericht', 'Briefing', 'Was gibts Neues', 'Lagebericht'.",
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
            "description": "Aktuelles Wetter von Home Assistant abrufen. Nutze dies wenn der User nach Wetter, Temperatur draussen, Regen oder Wind fragt. Standardmaessig nur aktuelles Wetter, Vorhersage nur wenn explizit gewuenscht.",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_forecast": {
                        "type": "boolean",
                        "description": "Nur auf true setzen wenn der User EXPLIZIT nach Vorhersage, morgen, spaeter oder den kommenden Tagen fragt (default: false)",
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
            "description": "Beschreibt wer oder was gerade vor der Haustuer steht (via Tuerkamera). Nutze dies wenn der User fragt 'Wer ist an der Tuer?', 'Wer hat geklingelt?' oder 'Was ist vor der Tuer?'.",
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
            "description": "Besucher-Management: Bekannte Besucher verwalten, erwartete Besucher anlegen, Besucher-History ansehen, Tuer oeffnen ('Lass ihn rein'). Nutze dies bei: 'Mama kommt heute', 'Lass ihn rein', 'Wer hat uns besucht?', 'Besucher hinzufuegen', 'Oeffne die Tuer fuer den Besuch'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add_known", "remove_known", "list_known", "expect", "cancel_expected", "grant_entry", "history", "status"],
                        "description": "Aktion: add_known=Besucher speichern, remove_known=entfernen, list_known=alle zeigen, expect=Besucher erwarten, cancel_expected=Erwartung aufheben, grant_entry=Tuer oeffnen, history=Besuchs-History, status=Uebersicht",
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
                        "description": "Tuer automatisch oeffnen wenn Besucher klingelt (nur bei expect)",
                    },
                    "door": {
                        "type": "string",
                        "description": "Tuer-Name fuer grant_entry (default: haustuer)",
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
            "description": "Verwaltet benannte Protokolle (Multi-Step-Sequenzen). Protokolle sind gespeicherte Ablaeufe wie 'Filmabend' oder 'Gute Nacht'. Nutze dies wenn der User ein Protokoll erstellen, ausfuehren, auflisten, loeschen oder rueckgaengig machen will. Beispiel: 'Erstelle Protokoll Filmabend: Licht 20%, Rolladen zu' oder 'Fuehre Filmabend aus' oder 'Zeig meine Protokolle'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "execute", "undo", "list", "delete"],
                        "description": "Aktion: create (erstellen), execute (ausfuehren), undo (rueckgaengig), list (auflisten), delete (loeschen)",
                    },
                    "name": {
                        "type": "string",
                        "description": "Name des Protokolls (z.B. 'Filmabend', 'Party', 'Morgenroutine')",
                    },
                    "description": {
                        "type": "string",
                        "description": "Nur bei action=create: Natuerliche Beschreibung der Schritte (z.B. 'Licht auf 20%, Rolladen zu, TV an')",
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
            "description": "Saugroboter steuern. Raum angeben → richtiger Roboter (EG/OG) wird automatisch gewaehlt. Ohne Raum → ganzes Stockwerk oder alle.",
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
                        "description": "Raumname fuer gezieltes Saugen (z.B. 'wohnzimmer', 'kueche'). Oder 'eg'/'og' fuer ganzes Stockwerk. Ohne → beide Roboter.",
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
            "description": "Status aller Saugroboter abfragen: Akku, Status, letzter Lauf, Wartungszustand.",
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
                            "create_project", "list_projects", "get_project", "update_project",
                            "complete_project", "add_note", "add_part", "diagnose",
                            "generate_code", "generate_3d", "generate_schematic",
                            "generate_website", "generate_bom", "generate_docs",
                            "generate_tests", "calculate", "simulate", "troubleshoot",
                            "suggest_improvements", "compare_components",
                            "scan_object", "search_library",
                            "add_workshop_item", "list_workshop",
                            "set_budget", "add_expense",
                            "printer_status", "start_print", "pause_print", "cancel_print",
                            "arm_move", "arm_gripper", "arm_home", "arm_pick_tool",
                            "start_timer", "pause_timer",
                            "journal_add", "journal_get",
                            "save_snippet", "get_snippet",
                            "safety_checklist", "calibration_guide",
                            "analyze_error_log", "evaluate_measurement",
                            "lend_tool", "return_tool", "list_lent",
                            "create_from_template", "get_stats",
                            "switch_project", "export_project",
                            "check_device", "link_device", "get_power",
                        ],
                        "description": "Die auszufuehrende Werkstatt-Aktion",
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Projekt-ID (8-stellig, z.B. 'a1b2c3d4'). Wird bei den meisten Aktionen benoetigt.",
                    },
                    "title": {"type": "string", "description": "Projekt-Titel (fuer create_project)"},
                    "description": {"type": "string", "description": "Beschreibung/Anforderung/Symptom"},
                    "category": {
                        "type": "string",
                        "enum": ["reparatur", "bau", "maker", "erfindung", "renovierung"],
                        "description": "Projekt-Kategorie",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["niedrig", "normal", "hoch", "dringend"],
                        "description": "Projekt-Prioritaet",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["erstellt", "diagnose", "teile_bestellt", "in_arbeit", "pausiert", "fertig"],
                        "description": "Neuer Projekt-Status (fuer update_project)",
                    },
                    "language": {
                        "type": "string",
                        "enum": ["arduino", "python", "cpp", "html", "javascript", "yaml", "micropython"],
                        "description": "Programmiersprache fuer Code-Generation",
                    },
                    "calc_type": {
                        "type": "string",
                        "enum": ["resistor_divider", "led_resistor", "wire_gauge", "ohms_law",
                                 "3d_print_weight", "screw_torque", "convert", "power_supply"],
                        "description": "Berechnungstyp",
                    },
                    "calc_params": {
                        "type": "object",
                        "description": "Parameter fuer die Berechnung (z.B. {\"v_in\": 12, \"v_out\": 3.3})",
                    },
                    "item": {"type": "string", "description": "Artikelname / Werkzeugname"},
                    "quantity": {"type": "integer", "description": "Menge"},
                    "cost": {"type": "number", "description": "Kosten in Euro"},
                    "person": {"type": "string", "description": "Personenname (fuer Verleih, Skills)"},
                    "text": {"type": "string", "description": "Freitext (Messwert, Log, Notiz, etc.)"},
                    "filename": {"type": "string", "description": "Dateiname fuer File-Operationen"},
                    "minutes": {"type": "integer", "description": "Timer-Dauer in Minuten"},
                    "template": {"type": "string", "description": "Template-Name"},
                    "entity_id": {"type": "string", "description": "HA Entity-ID"},
                    "x": {"type": "number", "description": "Arm X-Position"},
                    "y": {"type": "number", "description": "Arm Y-Position"},
                    "z": {"type": "number", "description": "Arm Z-Position"},
                    "budget": {"type": "number", "description": "Budget in Euro"},
                    "component_a": {"type": "string", "description": "Erste Komponente (Vergleich)"},
                    "component_b": {"type": "string", "description": "Zweite Komponente (Vergleich)"},
                    "query": {"type": "string", "description": "Suchbegriff (Library/Projekte)"},
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
            "description": "Fernbedienung steuern (Logitech Harmony etc.). Kann Aktivitaeten starten/stoppen und IR-Befehle senden. Beispiele: 'Schalte den Fernseher ein' → activity='Fernsehen', 'Stell auf ARD um' → command='InputHdmi1' oder device+command, 'Mach alles aus' → action='off'.",
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
                        "description": "on=einschalten (optional mit activity), off=alles ausschalten, activity=Aktivitaet wechseln, command=IR-Befehl senden.",
                    },
                    "activity": {
                        "type": "string",
                        "description": "Name der Harmony-Aktivitaet (z.B. 'Fernsehen', 'Watch TV', 'Musik hoeren', 'Netflix'). Nur bei action='on' oder 'activity'.",
                    },
                    "command": {
                        "type": "string",
                        "description": "IR-Befehl (z.B. 'VolumeUp', 'VolumeDown', 'Mute', 'ChannelUp', 'ChannelDown', 'Play', 'Pause', 'InputHdmi1'). Nur bei action='command'.",
                    },
                    "device": {
                        "type": "string",
                        "description": "Zielgeraet fuer den IR-Befehl (z.B. 'Samsung TV', 'Yamaha Receiver'). Optional — ohne device wird der Befehl an die aktive Aktivitaet gesendet.",
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
            "description": "Zeigt alle Fernbedienungen mit aktuellem Status, aktiver Aktivitaet und verfuegbaren Aktivitaeten/Geraeten. Nutze dies wenn der User fragt was die Fernbedienung kann, welche Aktivitaeten es gibt oder was gerade laeuft.",
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
]


def get_assistant_tools() -> list:
    """Liefert Tool-Definitionen mit aktuellem Climate-Schema und Entity-Katalog.

    - Climate-Tool wird bei jedem Aufruf neu gebaut (Heizungsmodus)
    - Room-Parameter werden mit echten Raumnamen angereichert
    - Entity-Katalog (Switches, Covers, Lights) wird aus HA-Cache injiziert
    """
    tools = []
    for tool in _ASSISTANT_TOOLS_STATIC:
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
        else:
            tools.append(_inject_entity_hints(tool))
    return tools


# ASSISTANT_TOOLS: Immer die dynamische Version verwenden
ASSISTANT_TOOLS = get_assistant_tools()


class FunctionExecutor:
    """Fuehrt Function Calls des Assistenten aus."""

    def __init__(self, ha_client: HomeAssistantClient):
        self.ha = ha_client
        self._entity_cache: dict[str, list[dict]] = {}
        self._config_versioning: Optional[ConfigVersioning] = None
        self._last_broadcast_time: float = 0.0

    def set_config_versioning(self, versioning: ConfigVersioning):
        """Setzt ConfigVersioning fuer Backup-vor-Schreiben."""
        self._config_versioning = versioning

    # Whitelist erlaubter Tool-Funktionsnamen (verhindert Zugriff auf interne Methoden)
    _ALLOWED_FUNCTIONS = frozenset({
        "set_light", "set_light_all", "get_lights", "set_climate", "set_climate_curve",
        "set_climate_room", "activate_scene", "set_cover", "set_cover_all",
        "get_covers", "get_media", "get_climate", "get_switches", "set_switch",
        "call_service", "play_media", "transfer_playback", "arm_security_system",
        "lock_door", "send_notification", "send_message_to_person",
        "play_sound", "get_entity_state", "get_calendar_events",
        "create_calendar_event", "delete_calendar_event",
        "reschedule_calendar_event", "set_presence_mode", "edit_config",
        "manage_shopping_list", "list_capabilities", "create_automation",
        "confirm_automation", "list_jarvis_automations",
        "delete_jarvis_automation", "manage_inventory",
        "set_timer", "cancel_timer", "get_timer_status",
        "set_reminder", "set_wakeup_alarm", "cancel_alarm", "get_alarms",
        "broadcast", "send_intercom",
        "get_camera_view", "create_conditional", "list_conditionals",
        "get_energy_report", "web_search", "get_security_score",
        "get_room_climate", "get_active_intents", "get_wellness_status",
        "get_house_status", "get_full_status_report", "get_weather",
        "get_device_health", "get_learned_patterns", "describe_doorbell",
        "manage_protocol", "recommend_music", "manage_visitor",
        "set_vacuum", "get_vacuum",
        "manage_repair",
        "remote_control", "get_remotes",
    })

    # Qwen3 uebersetzt deutsche Raumnamen oft ins Englische
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

    # Geraetetyp-Woerter die Qwen3 manchmal in den Raumnamen packt
    _DEVICE_TYPE_WORDS = {
        # Deutsch
        "licht", "lampe", "leuchte", "beleuchtung",
        "rollladen", "rolladen", "jalousie", "rollo",
        "heizung", "thermostat", "klima", "klimaanlage",
        "steckdose", "schalter", "dose",
        "lautsprecher", "speaker", "media", "musik",
        "tuer", "schloss", "lock",
        "fenster", "sensor",
        # Englisch
        "light", "lights", "lamp", "blind", "blinds",
        "shutter", "cover", "switch", "plug", "outlet",
        "heater", "heating", "thermostat", "climate",
        "door", "window",
    }

    @classmethod
    def _clean_room(cls, room: str) -> str:
        """Bereinigt room-Parameter: Prefixe, Geraetetypen, EN->DE.

        Qwen3 schickt manchmal:
        - 'licht.buero' statt 'buero' (Domain-Prefix)
        - 'living_room' statt 'wohnzimmer' (englische Uebersetzung)
        - 'schlafzimmer rollladen' statt 'schlafzimmer' (Geraetetyp im Raum)
        """
        if not room:
            return room

        # 1. Domain-Prefix strippen (z.B. "light.wohnzimmer" -> "wohnzimmer")
        for prefix in ("licht.", "light.", "schalter.", "switch.",
                       "rollladen.", "rolladen.", "cover.",
                       "steckdose.", "lampe.", "climate.", "media_player.",
                       "lock.", "sensor.", "binary_sensor."):
            if room.lower().startswith(prefix):
                room = room[len(prefix):]
                break

        # 2. Geraetetyp-Woerter entfernen (z.B. "schlafzimmer rollladen" -> "schlafzimmer")
        parts = room.replace("_", " ").split()
        if len(parts) > 1:
            cleaned = [p for p in parts if p.lower() not in cls._DEVICE_TYPE_WORDS]
            if cleaned:
                original = room
                room = " ".join(cleaned)
                if room != original:
                    logger.info("Room device-word cleanup: '%s' -> '%s'", original, room)

        # 3. Englisch -> Deutsch Uebersetzung
        room_lower = room.lower().strip()
        if room_lower in cls._EN_TO_DE_ROOMS:
            translated = cls._EN_TO_DE_ROOMS[room_lower]
            logger.info("Room EN->DE: '%s' -> '%s'", room, translated)
            return translated

        return room

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
            return {"success": False, "message": f"Unbekannte Funktion: {function_name}"}
        handler = getattr(self, f"_exec_{function_name}", None)
        if not handler:
            return {"success": False, "message": f"Unbekannte Funktion: {function_name}"}

        try:
            return await handler(arguments)
        except Exception as e:
            logger.error("Fehler bei %s: %s", function_name, e)
            return {"success": False, "message": f"Da lief etwas schief: {e}"}

    # ── Phase 11: Adaptive Helligkeit (dim2warm) ──────────────
    # Zirkadiane Helligkeitskurve (Prozent pro Stunde)
    _CIRCADIAN_BRIGHTNESS_CURVE = [
        {"time": "05:00", "pct": 10},
        {"time": "06:00", "pct": 40},
        {"time": "07:00", "pct": 70},
        {"time": "08:00", "pct": 90},
        {"time": "09:00", "pct": 100},
        {"time": "12:00", "pct": 100},
        {"time": "16:00", "pct": 100},
        {"time": "18:00", "pct": 80},
        {"time": "19:00", "pct": 60},
        {"time": "20:00", "pct": 40},
        {"time": "21:00", "pct": 25},
        {"time": "22:00", "pct": 10},
        {"time": "23:00", "pct": 5},
    ]

    @staticmethod
    def _interpolate_circadian(curve, key, now_h, now_m):
        """Interpoliert Wert aus zeitbasierter Kurve."""
        now_min = now_h * 60 + now_m
        prev_entry = curve[-1]
        for entry in curve:
            parts = entry["time"].split(":")
            entry_min = int(parts[0]) * 60 + int(parts[1])
            if entry_min > now_min:
                prev_parts = prev_entry["time"].split(":")
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
    def _get_adaptive_brightness(room: str) -> int:
        """Berechnet Helligkeit basierend auf Tageszeit + Raum-Profil.

        Wenn lighting.circadian.enabled: nutzt interpolierte Helligkeitskurve.
        Sonst: Minuten-basierte lineare Interpolation (default/night).

        dim2warm-Lampen regeln Farbtemperatur ueber die Helligkeit
        in Hardware — je dunkler, desto waermer.
        """
        now = datetime.now()
        minutes = now.hour * 60 + now.minute
        profiles = _get_room_profiles()
        room_cfg = profiles.get("rooms", {}).get(room, {})
        default_bright = room_cfg.get("default_brightness", 70)
        night_bright = room_cfg.get("night_brightness", 20)

        # Zirkadiane Beleuchtung: feinere Kurve wenn aktiviert
        lighting_cfg = yaml_config.get("lighting", {})
        circadian = lighting_cfg.get("circadian", {})
        if circadian.get("enabled"):
            # Interpolierte Kurve liefert 0-100%, skaliert auf Raum-Profil
            curve_pct = FunctionCalling._interpolate_circadian(
                FunctionCalling._CIRCADIAN_BRIGHTNESS_CURVE, "pct",
                now.hour, now.minute
            )
            # Skaliere Kurve auf Raum-spezifischen Bereich (night..default)
            scaled = night_bright + (default_bright - night_bright) * (curve_pct / 100)
            return max(1, int(scaled))

        # Fallback: Minuten-basierte Interpolation (sanfte Uebergaenge)
        # 06:00-09:00 (360-540): aufsteigend (night → default)
        # 09:00-17:00 (540-1020): volle Helligkeit (default)
        # 17:00-21:00 (1020-1260): absteigend (default → night)
        # 21:00-06:00: minimal (night)
        if 360 <= minutes < 540:      # Morgens: aufsteigend
            ratio = (minutes - 360) / 180
            return int(night_bright + (default_bright - night_bright) * ratio)
        elif 540 <= minutes < 1020:   # Tagsueber: volle Helligkeit
            return default_bright
        elif 1020 <= minutes < 1260:  # Abends: absteigend
            ratio = (minutes - 1020) / 240
            return int(default_bright - (default_bright - night_bright) * ratio)
        else:                          # Nachts: minimal
            return night_bright

    async def _exec_set_light_floor(self, floor: str, args: dict, state: str) -> dict:
        """Alle Lichter einer Etage steuern (eg/og)."""
        profiles = _get_room_profiles()
        floor_rooms = [
            r for r, cfg in profiles.get("rooms", {}).items()
            if cfg.get("floor") == floor
        ]
        if not floor_rooms:
            return {"success": False, "message": f"Keine Raeume fuer Etage '{floor.upper()}' konfiguriert"}

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
                new_brightness = current_brightness + step if state == "brighter" else current_brightness - step
                new_brightness = max(5, min(100, new_brightness))
                await self.ha.call_service("light", "turn_on", {"entity_id": entity_id, "brightness_pct": new_brightness})
                count += 1
            direction = "heller" if state == "brighter" else "dunkler"
            return {"success": count > 0, "message": f"{count} Lichter im {floor.upper()} {direction}"}

        service = "turn_on" if state == "on" else "turn_off"
        count = 0
        for room_name in floor_rooms:
            entity_id = await self._find_entity("light", room_name)
            if not entity_id:
                continue
            service_data: dict = {"entity_id": entity_id}
            if state == "on":
                if "brightness" in args:
                    try:
                        bri = str(args["brightness"]).replace("%", "").strip()
                        service_data["brightness_pct"] = max(1, min(100, int(float(bri))))
                    except (ValueError, TypeError):
                        pass
                else:
                    service_data["brightness_pct"] = self._get_adaptive_brightness(room_name)
            await self.ha.call_service("light", service, service_data)
            count += 1

        return {"success": count > 0, "message": f"{count} Lichter im {floor.upper()} {state}"}

    async def _exec_set_light(self, args: dict) -> dict:
        room = args.get("room")
        state = args.get("state")
        device = args.get("device")
        person = args.pop("_person", "")

        # Qwen3-Fallback: entity_id statt room akzeptieren
        if not room and args.get("entity_id"):
            eid = args["entity_id"]
            if eid.startswith("light."):
                room = eid.split(".", 1)[1]
            else:
                room = eid

        # Qwen3-Cleanup: Domain-Prefix aus room strippen
        room = self._clean_room(room)

        # State ableiten wenn nicht explizit angegeben
        if not state:
            if args.get("brightness"):
                state = "on"
            else:
                state = "off"

        if not room:
            return {"success": False, "message": "Kein Raum angegeben"}

        # Phase 11: Etagen-Steuerung (eg/og)
        # Normalisierung: "obergeschoss"/"oben" -> "og", "erdgeschoss"/"unten" -> "eg"
        _floor_map = {
            "obergeschoss": "og", "oben": "og", "erster stock": "og",
            "erdgeschoss": "eg", "unten": "eg", "parterre": "eg",
        }
        _room_lower = room.lower()
        if _room_lower in _floor_map:
            _room_lower = _floor_map[_room_lower]
        if _room_lower in ("eg", "og"):
            return await self._exec_set_light_floor(_room_lower, args, state)

        # Sonderfall: "all" -> alle Lichter schalten
        if room.lower() == "all":
            return await self._exec_set_light_all(args, state)

        entity_id = await self._find_entity("light", room, device_hint=device, person=person)
        if not entity_id:
            # Cross-Domain-Fallback: Vielleicht ist es ein Switch (z.B. Siebtraegermaschine)
            switch_id = await self._find_entity("switch", room, person=person)
            if switch_id:
                logger.info("set_light cross-domain fallback: '%s' -> switch %s", room, switch_id)
                service = "turn_on" if state == "on" else "turn_off"
                success = await self.ha.call_service("switch", service, {"entity_id": switch_id})
                return {"success": success, "message": f"Schalter {room} {state}"}
            return {"success": False, "message": f"Kein Licht in '{room}' gefunden"}

        # Relative Helligkeit: brighter/dimmer
        if state in ("brighter", "dimmer"):
            current_brightness = 50  # Fallback
            ha_state = await self.ha.get_state(entity_id)
            if ha_state and ha_state.get("state") == "on":
                attrs = ha_state.get("attributes", {})
                # HA gibt brightness als 0-255 zurueck
                raw = attrs.get("brightness", 128)
                current_brightness = round(raw / 255 * 100)
            step = 15
            new_brightness = current_brightness + step if state == "brighter" else current_brightness - step
            new_brightness = max(5, min(100, new_brightness))
            service_data = {"entity_id": entity_id, "brightness_pct": new_brightness}
            success = await self.ha.call_service("light", "turn_on", service_data)
            direction = "heller" if state == "brighter" else "dunkler"
            return {"success": success, "message": f"Licht {room} {direction} auf {new_brightness}%"}

        service_data = {"entity_id": entity_id}
        brightness_pct = None
        if "brightness" in args and state == "on":
            try:
                bri = str(args["brightness"]).replace("%", "").strip()
                brightness_pct = max(1, min(100, int(float(bri))))
                service_data["brightness_pct"] = brightness_pct
            except (ValueError, TypeError):
                pass
        elif state == "on" and "brightness" not in args:
            # Phase 11: Adaptive Helligkeit wenn keine explizite Angabe
            brightness_pct = self._get_adaptive_brightness(room)
            service_data["brightness_pct"] = brightness_pct
        # Phase 9: Transition-Parameter (sanftes Dimmen) — muss int/float sein
        if "transition" in args:
            try:
                service_data["transition"] = int(args["transition"])
            except (ValueError, TypeError):
                # LLM schickt manchmal "smooth" statt Zahl — Default 2s
                service_data["transition"] = 2
        elif state == "on":
            # Kein expliziter Transition: Default aus lighting-Config
            _lt = yaml_config.get("lighting", {}).get("default_transition")
            if _lt and int(_lt) > 0:
                service_data["transition"] = int(_lt)
        # dim2warm: Farbtemperatur wird in Hardware ueber Helligkeit geregelt.
        # Kein color_temp_kelvin an HA senden — Lampen machen das selbst.

        logger.info("set_light: %s -> %s (service_data=%s)", room, entity_id, service_data)

        service = "turn_on" if state == "on" else "turn_off"
        success = await self.ha.call_service("light", service, service_data)
        extras = []
        if brightness_pct is not None:
            extras.append(f"{brightness_pct}%")
        if "transition" in args:
            extras.append(f"Transition: {args['transition']}s")
        extra_str = f" ({', '.join(extras)})" if extras else ""
        return {"success": success, "message": f"Licht {room} {state}{extra_str}", "entity_id": entity_id}

    async def _exec_set_light_all(self, args: dict, state: str) -> dict:
        """Alle Lichter ein- oder ausschalten."""
        states = await self.ha.get_states()
        if not states:
            return {"success": False, "message": "Die Geraete sind momentan nicht ansprechbar. Ich versuche es gleich erneut."}

        service = "turn_on" if state == "on" else "turn_off"
        count = 0
        for s in states:
            eid = s.get("entity_id", "")
            if eid.startswith("light.") and s.get("state") != state:
                service_data = {"entity_id": eid}
                if state == "on":
                    if "brightness" in args:
                        try:
                            bri = str(args["brightness"]).replace("%", "").strip()
                            service_data["brightness_pct"] = max(1, min(100, int(float(bri))))
                        except (ValueError, TypeError):
                            pass
                    else:
                        # Adaptive Helligkeit wenn keine explizite Angabe
                        room_name = eid.split(".", 1)[1] if "." in eid else ""
                        service_data["brightness_pct"] = self._get_adaptive_brightness(room_name)
                await self.ha.call_service("light", service, service_data)
                count += 1

        return {"success": True, "message": f"Alle Lichter {state} ({count} geschaltet)"}

    async def _exec_get_lights(self, args: dict) -> dict:
        """Alle Lichter mit Name, Raum-Zuordnung und Status auflisten."""
        room_filter = self._clean_room(args.get("room", ""))

        # Geraete aus MindHome DB laden (enthaelt Raum-Zuordnung)
        try:
            devices = await self.ha.search_devices(domain="light", room=room_filter)
        except Exception as e:
            logger.debug("MindHome light-devices nicht ladbar: %s", e)
            devices = None

        # HA-States fuer aktuellen Status laden
        states = await self.ha.get_states()
        if not states:
            return {"success": False, "message": "Kann gerade nicht auf die Geraete zugreifen."}

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
                    if (search_norm not in self._normalize_name(entity_name)
                            and search_norm not in self._normalize_name(friendly)):
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
            msg = f"Keine Lichter in '{room_filter}' gefunden." if room_filter else "Keine Lichter gefunden."
            return {"success": False, "message": msg}

        on_count = sum(1 for l in lights if ": on" in l)
        header = f"{len(lights)} Lichter"
        if room_filter:
            header += f" in '{room_filter}'"
        header += f" ({on_count} an, {len(lights) - on_count} aus):\n"

        return {"success": True, "message": header + "\n".join(lights)}

    async def _exec_get_covers(self, args: dict) -> dict:
        """Alle Rolllaeden/Jalousien mit Status auflisten."""
        room_filter = self._clean_room(args.get("room", ""))

        try:
            devices = await self.ha.search_devices(domain="cover", room=room_filter)
        except Exception as e:
            logger.debug("MindHome cover-devices nicht ladbar: %s", e)
            devices = None

        states = await self.ha.get_states()
        if not states:
            return {"success": False, "message": "Kann gerade nicht auf die Geraete zugreifen."}

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
                    if (search_norm not in self._normalize_name(entity_name)
                            and search_norm not in self._normalize_name(friendly)):
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
            msg = f"Keine Rolllaeden in '{room_filter}' gefunden." if room_filter else "Keine Rolllaeden gefunden."
            return {"success": False, "message": msg}

        open_count = sum(1 for c in covers if ": open" in c)
        header = f"{len(covers)} Rolllaeden"
        if room_filter:
            header += f" in '{room_filter}'"
        header += f" ({open_count} offen, {len(covers) - open_count} zu):\n"
        return {"success": True, "message": header + "\n".join(covers)}

    async def _exec_get_media(self, args: dict) -> dict:
        """Alle Media Player mit Status auflisten."""
        room_filter = self._clean_room(args.get("room", ""))

        states = await self.ha.get_states()
        if not states:
            return {"success": False, "message": "Kann gerade nicht auf die Geraete zugreifen."}

        search_norm = self._normalize_name(room_filter) if room_filter else ""
        players = []
        for s in states:
            eid = s.get("entity_id", "")
            if not eid.startswith("media_player."):
                continue
            if search_norm:
                entity_name = eid.split(".", 1)[1]
                friendly = s.get("attributes", {}).get("friendly_name", "")
                if (search_norm not in self._normalize_name(entity_name)
                        and search_norm not in self._normalize_name(friendly)):
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
            msg = f"Keine Media Player in '{room_filter}' gefunden." if room_filter else "Keine Media Player gefunden."
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
            return {"success": False, "message": "Kann gerade nicht auf die Geraete zugreifen."}

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
                    if (search_norm not in self._normalize_name(entity_name)
                            and search_norm not in self._normalize_name(friendly)):
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
            msg = f"Keine Thermostate in '{room_filter}' gefunden." if room_filter else "Keine Thermostate gefunden."
            return {"success": False, "message": msg}

        heating = sum(1 for t in thermostats if "heat" in t.lower())
        header = f"{len(thermostats)} Thermostate"
        if room_filter:
            header += f" in '{room_filter}'"
        header += f" ({heating} heizen):\n"
        return {"success": True, "message": header + "\n".join(thermostats)}

    async def _exec_get_switches(self, args: dict) -> dict:
        """Alle Steckdosen/Schalter mit Status auflisten."""
        room_filter = self._clean_room(args.get("room", ""))

        try:
            devices = await self.ha.search_devices(domain="switch", room=room_filter)
        except Exception as e:
            logger.debug("MindHome switch-devices nicht ladbar: %s", e)
            devices = None

        states = await self.ha.get_states()
        if not states:
            return {"success": False, "message": "Kann gerade nicht auf die Geraete zugreifen."}

        state_map = {}
        for s in states:
            eid = s.get("entity_id", "")
            if eid.startswith("switch."):
                state_map[eid] = s

        switches = []
        if devices:
            for dev in devices:
                eid = dev.get("ha_entity_id", "")
                name = dev.get("name", eid)
                room = dev.get("room", "—")
                ha = state_map.get(eid, {})
                status = ha.get("state", "unknown")
                switches.append(f"- {name} [{room}]: {status}")
        else:
            search_norm = self._normalize_name(room_filter) if room_filter else ""
            for eid, ha in state_map.items():
                if search_norm:
                    entity_name = eid.split(".", 1)[1]
                    friendly = ha.get("attributes", {}).get("friendly_name", "")
                    if (search_norm not in self._normalize_name(entity_name)
                            and search_norm not in self._normalize_name(friendly)):
                        continue
                attrs = ha.get("attributes", {})
                friendly = attrs.get("friendly_name", eid)
                status = ha.get("state", "unknown")
                switches.append(f"- {friendly}: {status}")

        if not switches:
            msg = f"Keine Schalter in '{room_filter}' gefunden." if room_filter else "Keine Schalter gefunden."
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

        # Qwen3-Fallback: entity_id statt room
        if not room and args.get("entity_id"):
            eid = args["entity_id"]
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
        success = await self.ha.call_service("switch", service, {"entity_id": entity_id})
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
            return {"success": False, "message": f"Ungueltiger Offset: {args.get('offset')}"}
        entity_id = heating.get("curve_entity", "")
        if not entity_id:
            return {"success": False, "message": "Kein Heizungs-Entity konfiguriert (heating.curve_entity)"}

        # Aktuellen Zustand holen um Basis-Temperatur zu ermitteln
        states = await self.ha.get_states()
        current_state = None
        for s in (states or []):
            if s.get("entity_id") == entity_id:
                current_state = s
                break

        if not current_state:
            return {"success": False, "message": f"Entity {entity_id} nicht gefunden"}

        # Basis-Temperatur der Heizkurve (vom Regler geliefert)
        attrs = current_state.get("attributes", {})
        base_temp = attrs.get("temperature")
        if base_temp is None:
            return {"success": False, "message": f"Der Temperatursensor {entity_id} antwortet gerade nicht."}

        # Offset-Grenzen aus Config erzwingen
        offset_min = heating.get("curve_offset_min", -5)
        offset_max = heating.get("curve_offset_max", 5)
        offset = max(offset_min, min(offset_max, offset))

        # Offset wird absolut zur Basis-Temperatur gesetzt (nicht kumulativ)
        new_temp = float(base_temp) + offset

        service_data = {"entity_id": entity_id, "temperature": new_temp}
        if "mode" in args:
            service_data["hvac_mode"] = args["mode"]

        success = await self.ha.call_service("climate", "set_temperature", service_data)
        sign = "+" if offset >= 0 else ""
        return {"success": success, "message": f"Heizung: Offset {sign}{offset}°C (Vorlauf {new_temp}°C)"}

    async def _exec_set_climate_room(self, args: dict) -> dict:
        """Raumthermostat-Modus: Temperatur pro Raum setzen."""
        room = args.get("room")
        # Qwen3-Fallback: entity_id statt room
        if not room and args.get("entity_id"):
            eid = args["entity_id"]
            room = eid.split(".", 1)[1] if "." in eid else eid
        room = self._clean_room(room)
        if not room:
            return {"success": False, "message": "Kein Raum angegeben"}
        entity_id = await self._find_entity("climate", room)
        if not entity_id:
            return {"success": False, "message": f"Kein Thermostat in '{room}' gefunden"}

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
            temp = float(args["temperature"])
        else:
            return {"success": False, "message": "Keine Temperatur angegeben"}

        service_data = {"entity_id": entity_id, "temperature": temp}
        if "mode" in args:
            service_data["hvac_mode"] = args["mode"]

        success = await self.ha.call_service("climate", "set_temperature", service_data)
        direction = ""
        if adjust == "warmer":
            direction = "waermer auf "
        elif adjust == "cooler":
            direction = "kaelter auf "
        return {"success": success, "message": f"{room} {direction}{temp}°C"}

    async def _exec_activate_scene(self, args: dict) -> dict:
        scene = args.get("scene")
        if not scene:
            return {"success": False, "message": "Keine Szene angegeben"}
        entity_id = await self._find_entity("scene", scene)
        if not entity_id:
            # Versuche direkt mit scene.name
            entity_id = f"scene.{scene}"

        success = await self.ha.call_service(
            "scene", "turn_on", {"entity_id": entity_id}
        )
        return {"success": success, "message": f"Szene '{scene}' aktiviert"}

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
        if re.search(r'(?:^|[_.\s])tor(?:$|[_.\s])', eid_lower):
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
            logger.warning("CoverConfig laden fehlgeschlagen fuer %s: %s — erlaube basierend auf device_class/entity_id", entity_id, e)
        return True

    def _is_markise(self, entity_id: str, state: dict) -> bool:
        """Prueft ob ein Cover eine Markise ist (entity_id oder cover_profiles)."""
        eid_lower = entity_id.lower()
        if "markise" in eid_lower or "awning" in eid_lower:
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
        except Exception:
            pass

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
        """Uebersetzt Jarvis-Position (0=zu, 100=offen) in HA-Position.

        Bei invertierten Covers wird 0↔100 getauscht.
        """
        if self._is_cover_inverted(entity_id):
            return 100 - position
        return position

    def _translate_cover_position_from_ha(self, entity_id: str, position: int) -> int:
        """Uebersetzt HA-Position zurueck in Jarvis-Position (0=zu, 100=offen)."""
        if self._is_cover_inverted(entity_id):
            return 100 - position
        return position

    def _resolve_cover_position(self, args: dict) -> tuple:
        """Bestimmt Position + Adjust aus action/state/adjust/position Args.

        Returns:
            (position: int | None, adjust: str | None, is_stop: bool)
        """
        _ACTION_TO_POS = {
            "open": 100, "close": 0, "half": 50,
            "auf": 100, "offen": 100, "hoch": 100, "up": 100,
            "closed": 0, "zu": 0, "runter": 0, "down": 0,
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
                return max(0, min(100, int(args["position"]))), None, False
            except (ValueError, TypeError):
                return 0, None, False

        return 0, None, False  # Fallback: close

    async def _exec_set_cover(self, args: dict) -> dict:
        room = args.get("room")
        cover_type = args.get("type")  # rollladen | markise | None

        # Qwen3-Fallback: entity_id statt room
        if not room and args.get("entity_id"):
            eid = args["entity_id"]
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

        # "all" → alle Rolllaeden (keine Markisen, keine Garagentore)
        position, adjust, is_stop = self._resolve_cover_position(args)
        if room.lower() == "all":
            if is_stop:
                return await self._exec_set_cover_all_action("stop_cover")
            final_pos = position if position is not None else 0
            # Ohne expliziten Typ: nur Rolllaeden (Markisen haben eigene Sicherheits-Checks)
            effective_type = cover_type or "rollladen"
            return await self._exec_set_cover_all(final_pos, effective_type)

        # Einzelraum
        entity_id = await self._find_entity("cover", room)

        if is_stop:
            if not entity_id:
                return {"success": False, "message": f"Kein Rollladen in '{room}' gefunden"}
            states = await self.ha.get_states()
            entity_state = next((s for s in (states or []) if s.get("entity_id") == entity_id), {})
            if not await self._is_safe_cover(entity_id, entity_state):
                return {"success": False, "message": f"'{room}' ist ein Garagentor/Tor — nicht erlaubt."}
            success = await self.ha.call_service("cover", "stop_cover", {"entity_id": entity_id})
            return {"success": success, "message": f"Rollladen {room} gestoppt"}

        # Relative Anpassung
        if adjust in ("up", "down"):
            if not entity_id:
                return {"success": False, "message": f"Kein Rollladen in '{room}' gefunden"}
            current_position = 50
            ha_state = await self.ha.get_state(entity_id)
            if ha_state:
                try:
                    ha_pos = int(ha_state.get("attributes", {}).get("current_position", 50))
                    # HA-Position in Jarvis-Position uebersetzen (0=zu, 100=offen)
                    current_position = self._translate_cover_position_from_ha(entity_id, ha_pos)
                except (ValueError, TypeError):
                    current_position = 50
            step = 20
            position = current_position + step if adjust == "up" else current_position - step
            position = max(0, min(100, position))

        if position is None:
            position = 0

        if not entity_id:
            try:
                all_states = await self.ha.get_states()
                available = [s.get("entity_id") for s in (all_states or []) if s.get("entity_id", "").startswith("cover.")]
            except Exception:
                available = []
            return {"success": False, "message": f"Kein Rollladen in '{room}' gefunden. Verfuegbar: {', '.join(available) if available else 'keine'}"}

        # Sicherheitscheck
        states = await self.ha.get_states()
        entity_state = next((s for s in (states or []) if s.get("entity_id") == entity_id), {})
        if not await self._is_safe_cover(entity_id, entity_state):
            return {"success": False, "message": f"'{room}' ist ein Garagentor/Tor — nicht erlaubt."}

        ha_position = self._translate_cover_position(entity_id, position)
        success = await self.ha.call_service(
            "cover", "set_cover_position",
            {"entity_id": entity_id, "position": ha_position},
        )
        direction = ""
        if adjust == "up":
            direction = "hoch auf "
        elif adjust == "down":
            direction = "runter auf "
        label = "Markise" if self._is_markise(entity_id, entity_state) else "Rollladen"
        return {"success": success, "message": f"{label} {room} {direction}{position}%"}

    async def _exec_set_cover_floor(self, floor: str, args: dict, cover_type: str = None) -> dict:
        """Alle Rolllaeden/Markisen einer Etage steuern."""
        profiles = _get_room_profiles()
        floor_rooms = [
            r for r, cfg in profiles.get("rooms", {}).items()
            if cfg.get("floor") == floor
        ]
        if not floor_rooms:
            return {"success": False, "message": f"Keine Raeume fuer Etage '{floor.upper()}' konfiguriert"}

        position, adjust, is_stop = self._resolve_cover_position(args)
        if position is None and not is_stop and adjust is None:
            position = 0

        states = await self.ha.get_states()
        if not states:
            return {"success": False, "message": "Die Geraete reagieren gerade nicht. Einen Moment."}

        count = 0
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
                # Typ-Filter: nur Rolllaeden oder nur Markisen
                if cover_type == "markise" and not self._is_markise(eid, s):
                    continue
                if cover_type == "rollladen" and self._is_markise(eid, s):
                    continue

                if is_stop:
                    await self.ha.call_service("cover", "stop_cover", {"entity_id": eid})
                else:
                    final_pos = position if position is not None else 0
                    ha_pos = self._translate_cover_position(eid, final_pos)
                    await self.ha.call_service("cover", "set_cover_position", {"entity_id": eid, "position": ha_pos})
                count += 1

        action_str = "gestoppt" if is_stop else f"auf {position}%"
        return {"success": count > 0, "message": f"{count} Rolllaeden im {floor.upper()} {action_str}"}

    async def _exec_set_cover_markisen(self, args: dict) -> dict:
        """Alle Markisen steuern — mit eigenen Wind/Regen-Sicherheits-Checks."""
        states = await self.ha.get_states()
        if not states:
            return {"success": False, "message": "Die Geraete reagieren gerade nicht. Einen Moment."}

        position, adjust, is_stop = self._resolve_cover_position(args)

        # Sicherheits-Check: Bei Wind/Regen Markisen nicht ausfahren
        if position is not None and position > 0 and not is_stop:
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
                        return {"success": False, "message": f"Markise NICHT ausgefahren — Wind {wind} km/h (Limit: {wind_limit} km/h)"}
                    if rain_retract and condition in ("rainy", "pouring", "hail", "lightning-rainy"):
                        return {"success": False, "message": f"Markise NICHT ausgefahren — Wetter: {condition}"}
                    break

        count = 0
        for s in states:
            eid = s.get("entity_id", "")
            if not eid.startswith("cover."):
                continue
            if not self._is_markise(eid, s):
                continue
            if is_stop:
                await self.ha.call_service("cover", "stop_cover", {"entity_id": eid})
            else:
                final_pos = position if position is not None else 0
                ha_pos = self._translate_cover_position(eid, final_pos)
                await self.ha.call_service("cover", "set_cover_position", {"entity_id": eid, "position": ha_pos})
            count += 1

        if count == 0:
            return {"success": False, "message": "Keine Markisen gefunden"}
        action_str = "gestoppt" if is_stop else f"auf {position}%"
        return {"success": True, "message": f"{count} Markise(n) {action_str}"}

    async def _exec_set_cover_all(self, position: int, cover_type: str = None) -> dict:
        """Alle Rolllaeden auf eine Position setzen (Garagentore ausgeschlossen)."""
        states = await self.ha.get_states()
        if not states:
            return {"success": False, "message": "Die Geraete reagieren gerade nicht. Einen Moment."}

        count = 0
        skipped = []
        for s in states:
            eid = s.get("entity_id", "")
            if not eid.startswith("cover."):
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
            await self.ha.call_service("cover", "set_cover_position", {"entity_id": eid, "position": ha_pos})
            count += 1

        msg = f"Alle Rolllaeden auf {position}% ({count} geschaltet)"
        if skipped:
            msg += f". Uebersprungen: {', '.join(skipped)}"
        return {"success": True, "message": msg}

    async def _exec_set_cover_all_action(self, service: str) -> dict:
        """Alle Rolllaeden: stop_cover etc."""
        states = await self.ha.get_states()
        if not states:
            return {"success": False, "message": "Die Geraete reagieren gerade nicht. Einen Moment."}
        count = 0
        for s in states:
            eid = s.get("entity_id", "")
            if not eid.startswith("cover."):
                continue
            if not await self._is_safe_cover(eid, s):
                continue
            await self.ha.call_service("cover", service, {"entity_id": eid})
            count += 1
        return {"success": True, "message": f"{count} Rolllaeden: {service}"}

    # ── Phase 11: Saugroboter (Dreame, 2 Etagen) ──────────

    @staticmethod
    def _normalize_room_key(room: str) -> str:
        """Normalisiert Raumnamen fuer Config-Lookup (Umlaute, Leerzeichen, Case)."""
        r = room.lower().strip()
        r = r.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
        r = r.replace(" ", "_")
        return r

    def _resolve_vacuum_room(self, room: str, robots: dict) -> tuple:
        """Findet den richtigen Roboter + Segment-ID fuer einen Raum.

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
        except Exception:
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

    async def _exec_set_vacuum(self, args: dict) -> dict:
        """Saugroboter steuern — waehlt automatisch EG/OG-Roboter."""
        action = args.get("action", "start")
        room = self._clean_room(args.get("room"))
        vacuum_cfg = yaml_config.get("vacuum", {})
        if not vacuum_cfg.get("enabled", True):
            return {"success": False, "message": "Saugroboter-Steuerung ist deaktiviert"}
        robots = vacuum_cfg.get("robots", {})
        if not robots:
            return {"success": False, "message": "Keine Saugroboter konfiguriert (settings.yaml → vacuum.robots)"}

        # Raum-genaues Saugen (clean_room ODER start mit Raum-Angabe)
        # Wenn ein konkreter Raum genannt wird → NUR diesen Raum saugen, nie das ganze Haus
        if action in ("clean_room", "start") and room and room.lower() not in ("eg", "og"):
            robot, segment_id = self._resolve_vacuum_room(room, robots)
            if not robot:
                return {"success": False, "message": f"Kein Saugroboter fuer '{room}' konfiguriert"}
            entity_id = robot.get("entity_id")
            if not entity_id:
                return {"success": False, "message": "Keine entity_id fuer Saugroboter konfiguriert"}
            nickname = robot.get("nickname", "der Kleine")

            if segment_id is not None:
                # Dreame (Tasshack): dreame_vacuum.vacuum_clean_segment
                # Fallback: vacuum.send_command mit app_segment_clean (Roborock/Miio)
                success = await self.ha.call_service("dreame_vacuum", "vacuum_clean_segment", {
                    "entity_id": entity_id,
                    "segments": [segment_id],
                })
                if not success:
                    success = await self.ha.call_service("vacuum", "send_command", {
                        "entity_id": entity_id,
                        "command": "app_segment_clean",
                        "params": [segment_id],
                    })
                return {"success": success, "message": f"{nickname} saugt {room}"}
            else:
                # KEIN stiller Fallback — wenn Raum gewuenscht aber kein Segment → Fehler
                _floor = robot.get("floor", "?")
                return {
                    "success": False,
                    "message": (
                        f"Raum '{room}' hat keine Segment-ID. Ohne Segment-ID wuerde der "
                        f"komplette Roboter starten und das ganze Stockwerk saugen. "
                        f"In settings.yaml unter vacuum.robots.{_floor}.rooms die Segment-ID "
                        f"fuer '{room}' eintragen."
                    ),
                }

        # Ganzes Stockwerk (explizit "sauge EG" / "sauge OG")
        if action == "start" and room and room.lower() in ("eg", "og"):
            robot = robots.get(room.lower())
            if not robot or not robot.get("entity_id"):
                return {"success": False, "message": f"Kein Roboter fuer {room.upper()} konfiguriert"}
            success = await self.ha.call_service("vacuum", "start", {"entity_id": robot["entity_id"]})
            return {"success": success, "message": f"{robot.get('nickname', 'Saugroboter')} startet im {room.upper()}"}

        # Stop/Pause/Dock → alle Roboter
        if action in ("stop", "pause", "dock"):
            service_map = {"stop": "stop", "pause": "pause", "dock": "return_to_base"}
            service = service_map[action]
            results = []
            for floor, robot in robots.items():
                eid = robot.get("entity_id")
                if eid:
                    success = await self.ha.call_service("vacuum", service, {"entity_id": eid})
                    results.append(success)
            action_de = {"stop": "gestoppt", "pause": "pausiert", "dock": "zur Ladestation"}
            return {"success": any(results), "message": f"Saugroboter {action_de.get(action, action)}"}

        # Start ohne Raum → alle starten
        results = []
        names = []
        for floor, robot in robots.items():
            eid = robot.get("entity_id")
            if eid:
                success = await self.ha.call_service("vacuum", "start", {"entity_id": eid})
                results.append(success)
                names.append(robot.get("nickname", f"Roboter {floor.upper()}"))
        return {"success": any(results), "message": f"{', '.join(names)} gestartet"}

    async def _exec_get_vacuum(self, args: dict) -> dict:
        """Status aller Saugroboter abfragen."""
        vacuum_cfg = yaml_config.get("vacuum", {})
        robots = vacuum_cfg.get("robots", {})
        if not robots:
            return {"success": False, "message": "Keine Saugroboter konfiguriert"}

        status_list = []
        for floor, robot in robots.items():
            entity_id = robot.get("entity_id")
            if not entity_id:
                status_list.append({
                    "name": robot.get("name", f"Saugroboter {floor.upper()}"),
                    "floor": floor.upper(),
                    "state": "nicht konfiguriert (entity_id fehlt)",
                })
                continue
            state = await self.ha.get_state(entity_id)
            if state:
                attrs = state.get("attributes", {})
                entry = {
                    "name": robot.get("name", f"Saugroboter {floor.upper()}"),
                    "nickname": robot.get("nickname", ""),
                    "floor": floor.upper(),
                    "state": state.get("state", "unknown"),
                    "battery": attrs.get("battery_level", "?"),
                }
                # Dreame-spezifische Attribute
                if attrs.get("total_clean_area"):
                    entry["area_cleaned_m2"] = attrs["total_clean_area"]
                if attrs.get("cleaning_time"):
                    entry["cleaning_time_min"] = attrs["cleaning_time"]
                # Wartungszustand
                maint = {}
                for key, label in [("filter_left", "Filter"), ("main_brush_left", "Hauptbuerste"),
                                   ("side_brush_left", "Seitenbuerste"), ("mop_left", "Mopp")]:
                    val = attrs.get(key)
                    if val is not None:
                        maint[label] = f"{val}%"
                if maint:
                    entry["wartung"] = maint
                status_list.append(entry)
            else:
                status_list.append({
                    "name": robot.get("name", f"Saugroboter {floor.upper()}"),
                    "floor": floor.upper(),
                    "state": "nicht erreichbar",
                })

        return {"success": True, "robots": status_list}

    # Erlaubte Service-Data Keys fuer _exec_call_service (Whitelist)
    _CALL_SERVICE_ALLOWED_KEYS = frozenset({
        "brightness", "brightness_pct", "color_temp", "rgb_color", "hs_color",
        "effect", "color_name", "transition",
        "temperature", "target_temp_high", "target_temp_low", "hvac_mode",
        "fan_mode", "swing_mode", "preset_mode",
        "position", "tilt_position",
        "volume_level", "media_content_id", "media_content_type", "source",
        "message", "title", "data",
        "option", "value", "code",
    })

    _CALL_SERVICE_ALLOWED_DOMAINS = frozenset({
        "light", "switch", "climate", "cover", "fan",
        "media_player", "scene",
        "input_boolean", "input_number", "input_select", "input_text",
        "notify", "number", "select", "button",
        "vacuum", "lock", "alarm_control_panel",
        "shopping_list", "calendar", "timer", "counter",
    })

    async def _exec_call_service(self, args: dict) -> dict:
        """Generischer HA Service-Aufruf (fuer Routinen wie Guest WiFi)."""
        domain = args.get("domain", "")
        service = args.get("service", "")
        entity_id = args.get("entity_id", "")
        if not domain or not service:
            return {"success": False, "message": "domain und service erforderlich"}

        if domain not in self._CALL_SERVICE_ALLOWED_DOMAINS:
            logger.warning("call_service: Blockierte Domain '%s.%s'", domain, service)
            return {"success": False, "message": f"Domain '{domain}' ist nicht erlaubt."}

        # Sicherheitscheck: Cover-Services fuer Garagentore blockieren
        # Bypass-sicher: Prueft ALLE Domains wenn entity_id ein Cover ist
        is_cover_entity = entity_id.startswith("cover.")
        is_cover_domain = domain == "cover"

        if is_cover_domain and not entity_id:
            # Cover-Domain ohne entity_id blockieren — koennte alle Cover betreffen
            return {"success": False, "message": "cover-Service ohne entity_id nicht erlaubt (Sicherheitssperre)."}

        if is_cover_entity or is_cover_domain:
            states = await self.ha.get_states()
            entity_state = next((s for s in (states or []) if s.get("entity_id") == entity_id), {})
            if not await self._is_safe_cover(entity_id, entity_state):
                return {"success": False, "message": f"Sicherheitssperre: '{entity_id}' ist ein Garagentor/Tor und darf nicht automatisch gesteuert werden."}

        service_data = {"entity_id": entity_id} if entity_id else {}
        # Nur erlaubte Service-Data Keys uebernehmen (Whitelist)
        for k, v in args.items():
            if k in self._CALL_SERVICE_ALLOWED_KEYS:
                service_data[k] = v
        success = await self.ha.call_service(domain, service, service_data)
        return {"success": success, "message": f"{domain}.{service} ausgefuehrt"}

    async def _exec_play_media(self, args: dict) -> dict:
        action = args.get("action", "play")
        room = args.get("room")
        if not room and args.get("entity_id"):
            eid = args["entity_id"]
            room = eid.split(".", 1)[1] if "." in eid else eid
        room = self._clean_room(room)
        entity_id = await self._find_entity("media_player", room) if room else None

        if not entity_id:
            # Ersten aktiven Player nehmen
            states = await self.ha.get_states()
            for s in (states or []):
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
                "media_player", "play_media",
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
                    return {"success": False, "message": "Keine Lautstaerke angegeben"}
            else:
                # Relative Steuerung: aktuelle Lautstaerke holen und anpassen
                state = await self.ha.get_state(entity_id)
                current = 0.5
                if state and "attributes" in state:
                    current = state["attributes"].get("volume_level", 0.5)
                step = 0.1  # ±10%
                new_level = current + step if action == "volume_up" else current - step
                volume_pct = max(0, min(100, round(new_level * 100)))

            volume_level = max(0.0, min(1.0, float(volume_pct) / 100.0))
            success = await self.ha.call_service(
                "media_player", "volume_set",
                {"entity_id": entity_id, "volume_level": volume_level},
            )
            direction = "lauter" if action == "volume_up" else "leiser" if action == "volume_down" else ""
            msg = f"Lautstaerke {direction} auf {int(volume_pct)}%" if direction else f"Lautstaerke auf {int(volume_pct)}%"
            return {"success": success, "message": msg}

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
        """Phase 10.1: Uebertraegt Musik-Wiedergabe von einem Raum zum anderen."""
        from_room = self._clean_room(args.get("from_room"))
        to_room = self._clean_room(args.get("to_room", ""))

        if not to_room:
            return {"success": False, "message": "Kein Zielraum angegeben"}

        to_entity = await self._find_entity("media_player", to_room)
        if not to_entity:
            return {"success": False, "message": f"Kein Media Player in '{to_room}' gefunden"}

        # Quell-Player finden (explizit oder aktiven suchen)
        from_entity = None
        if from_room:
            from_entity = await self._find_entity("media_player", from_room)
        else:
            # Aktiven Player finden
            states = await self.ha.get_states()
            for s in (states or []):
                eid = s.get("entity_id", "")
                if eid.startswith("media_player.") and s.get("state") == "playing":
                    from_entity = eid
                    from_room = s.get("attributes", {}).get("friendly_name", eid)
                    break

        if not from_entity:
            return {"success": False, "message": "Keine aktive Wiedergabe gefunden"}

        if from_entity == to_entity:
            return {"success": True, "message": "Musik laeuft bereits in diesem Raum"}

        # Aktuellen Zustand vom Quell-Player holen
        states = await self.ha.get_states()
        source_state = None
        for s in (states or []):
            if s.get("entity_id") == from_entity:
                source_state = s
                break

        if not source_state or source_state.get("state") != "playing":
            return {"success": False, "message": f"In '{from_room}' laeuft nichts"}

        attrs = source_state.get("attributes", {})
        media_content_id = attrs.get("media_content_id", "")
        media_content_type = attrs.get("media_content_type", "music")
        volume = attrs.get("volume_level", 0.5)

        # 1. Volume auf Ziel-Player setzen
        await self.ha.call_service(
            "media_player", "volume_set",
            {"entity_id": to_entity, "volume_level": volume},
        )

        # 2. Wiedergabe auf Ziel-Player starten
        success = False
        if media_content_id:
            success = await self.ha.call_service(
                "media_player", "play_media",
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
                    "media_player", "play_media",
                    {
                        "entity_id": to_entity,
                        "media_content_id": media_title,
                        "media_content_type": media_content_type or "music",
                    },
                )
            else:
                return {
                    "success": False,
                    "message": f"Kein uebertragbarer Inhalt in '{from_room}' gefunden (weder Content-ID noch Titel)",
                }

        # 3. Quell-Player stoppen
        if success:
            await self.ha.call_service(
                "media_player", "media_stop",
                {"entity_id": from_entity},
            )

        return {
            "success": success,
            "message": f"Musik laeuft jetzt im {to_room}." if success
                       else f"Der Transfer nach {to_room} kam nicht zustande.",
        }

    async def _exec_arm_security_system(self, args: dict) -> dict:
        mode = args.get("mode")
        if not mode:
            return {"success": False, "message": "Kein Modus angegeben (arm_home, arm_away oder disarm)."}
        states = await self.ha.get_states()
        entity_id = None
        for s in (states or []):
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
            return {"success": False, "message": f"Unbekannter Alarm-Modus '{mode}'. Gueltig: {valid}"}
        success = await self.ha.call_service(
            "alarm_control_panel", service, {"entity_id": entity_id}
        )
        return {"success": success, "message": f"Alarm: {mode}"}

    async def _exec_lock_door(self, args: dict) -> dict:
        door = args["door"]
        action = args["action"]
        entity_id = await self._find_entity("lock", door)
        if not entity_id:
            return {"success": False, "message": f"Kein Schloss '{door}' gefunden"}

        success = await self.ha.call_service(
            "lock", action, {"entity_id": entity_id}
        )
        return {"success": success, "message": f"Tuer {door}: {action}"}

    async def _exec_send_notification(self, args: dict) -> dict:
        message = args["message"]
        target = args.get("target", "phone")
        volume = args.get("volume")  # Phase 9: Optional volume (0.0-1.0)
        room = self._clean_room(args.get("room"))  # Phase 10: Optional room for TTS routing

        if target == "phone":
            success = await self.ha.call_service(
                "notify", "notify", {"message": message}
            )
        elif target == "speaker":
            # TTS ueber Piper (Wyoming): tts.speak mit TTS-Entity + Media-Player
            tts_entity = await self._find_tts_entity()

            # Phase 10: Room-aware Speaker-Auswahl
            if room:
                speaker_entity = await self._find_speaker_in_room(room)
            else:
                speaker_entity = await self._find_tts_speaker()

            # Phase 9: Volume setzen vor TTS
            if speaker_entity and volume is not None:
                await self.ha.call_service(
                    "media_player", "volume_set",
                    {"entity_id": speaker_entity, "volume_level": volume},
                )

            # Alexa/Echo: Keine Audio-Dateien, stattdessen notify.alexa_media
            alexa_speakers = yaml_config.get("sounds", {}).get("alexa_speakers", [])
            if speaker_entity and speaker_entity in alexa_speakers:
                svc_name = "alexa_media_" + speaker_entity.replace("media_player.", "", 1)
                success = await self.ha.call_service(
                    "notify", svc_name,
                    {"message": message, "data": {"type": "tts"}},
                )
            elif tts_entity and speaker_entity:
                success = await self.ha.call_service(
                    "tts", "speak",
                    {
                        "entity_id": tts_entity,
                        "media_player_entity_id": speaker_entity,
                        "message": message,
                    },
                )
            elif speaker_entity:
                # Fallback: Legacy TTS Service
                success = await self.ha.call_service(
                    "tts", "speak",
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
        person = args["person"]
        message = args["message"]
        person_lower = person.lower()

        # Person-Profil laden
        person_profiles = yaml_config.get("person_profiles", {}).get("profiles", {})
        profile = person_profiles.get(person_lower, {})

        # Pruefen ob Person zuhause ist
        states = await self.ha.get_states()
        person_home = False
        for state in (states or []):
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
                        "notify", svc_name,
                        {"message": message, "data": {"type": "tts"}},
                    )
                elif tts_entity:
                    success = await self.ha.call_service(
                        "tts", "speak",
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
                parts[0], parts[1], {"message": message, "title": f"Nachricht von {settings.assistant_name}"}
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
        sound = args["sound"]
        room = self._clean_room(args.get("room"))

        speaker_entity = None
        if room:
            speaker_entity = await self._find_entity("media_player", room)
        if not speaker_entity:
            speaker_entity = await self._find_tts_speaker()

        if not speaker_entity:
            return {"success": False, "message": "Kein Speaker gefunden"}

        # Sound als TTS-Chime abspielen (oder Media-File wenn vorhanden)
        # Kurze TTS-Nachricht als Ersatz fuer Sound-Files
        sound_texts = {
            "listening": ".",
            "confirmed": ".",
            "warning": "Achtung.",
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
                "tts", "speak",
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
        entity_id = args["entity_id"]
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

        return {"success": True, "message": display, "state": current, "attributes": attrs}

    def _get_write_calendar(self) -> Optional[str]:
        """Ersten konfigurierten Kalender fuer Schreib-Operationen zurueckgeben."""
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
            end = (now + timedelta(days=7)).replace(hour=23, minute=59, second=59, microsecond=0)

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
            logger.info("Kalender: %d konfigurierte Entities: %s", len(calendar_entities), calendar_entities)
        else:
            # Alle calendar.* Entities aus HA sammeln
            states = await self.ha.get_states()
            all_cal_entities = [
                s["entity_id"] for s in (states or [])
                if s.get("entity_id", "").startswith("calendar.")
            ]
            logger.info("Kalender: %d Entities in HA gefunden: %s", len(all_cal_entities), all_cal_entities)

            # Bekannte Noise-Kalender ausfiltern (Feiertage, Geburtstage etc.)
            _NOISE_KEYWORDS = [
                "feiertag", "holiday", "birthday", "geburtstag",
                "abfall", "muell", "garbage", "waste", "trash",
                "schulferien", "school", "vacation",
            ]
            calendar_entities = [
                eid for eid in all_cal_entities
                if not any(kw in eid.lower() for kw in _NOISE_KEYWORDS)
            ]
            # Wenn nach Filter nichts uebrig, alle verwenden
            if not calendar_entities and all_cal_entities:
                calendar_entities = all_cal_entities
                logger.info("Kalender: Noise-Filter hat alles entfernt, nutze alle %d", len(calendar_entities))
            elif len(calendar_entities) < len(all_cal_entities):
                filtered_out = set(all_cal_entities) - set(calendar_entities)
                logger.info("Kalender: %d nach Filter (entfernt: %s)", len(calendar_entities), filtered_out)

        if not calendar_entities:
            return {"success": False, "message": "Kein Kalender in Home Assistant gefunden"}

        logger.info("Kalender: Abfrage von %d Entities: %s", len(calendar_entities), calendar_entities)

        # Alle Kalender abfragen und Events sammeln
        all_events = []
        for cal_entity in calendar_entities:
            events_found = False
            # Methode 1: Service-Call mit ?return_response (HA 2024.x+)
            try:
                result = await self.ha.call_service_with_response(
                    "calendar", "get_events",
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
                logger.warning("Kalender %s Service-Call fehlgeschlagen: %s", cal_entity, e)

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
                    logger.warning("Kalender %s REST-Fallback fehlgeschlagen: %s", cal_entity, e)

        if not all_events:
            label = {"today": "heute", "tomorrow": "morgen", "week": "diese Woche"}.get(timeframe, timeframe)
            return {"success": True, "message": f"Keine Termine {label}."}

        # Startzeit aus Event extrahieren (HA gibt dict oder string zurueck)
        def _parse_event_start(ev):
            raw = ev.get("start", "")
            if isinstance(raw, dict):
                raw = raw.get("dateTime") or raw.get("date") or ""
            return str(raw) if raw else ""

        # Datum-Validierung: Nur Events im angefragten Zeitraum behalten
        # (HA gibt manchmal Events ausserhalb des Bereichs zurueck)
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
                    ev_local = datetime.strptime(raw_start[:10], "%Y-%m-%d").replace(tzinfo=_tz)
                if start <= ev_local <= end:
                    validated_events.append(ev)
                else:
                    logger.warning("Kalender: Event '%s' am %s liegt ausserhalb %s-%s, uebersprungen",
                                   ev.get("summary", "?"), ev_local.isoformat(),
                                   start_str, end_str)
            except (ValueError, TypeError) as e:
                logger.warning("Kalender: Event-Datum nicht parsebar: %s (%s)", raw_start, e)
                validated_events.append(ev)  # Im Zweifel behalten

        all_events = validated_events
        if not all_events:
            label = {"today": "heute", "tomorrow": "morgen", "week": "diese Woche"}.get(timeframe, timeframe)
            return {"success": True, "message": f"Keine Termine {label}."}

        # Nach Startzeit sortieren
        all_events.sort(key=lambda ev: _parse_event_start(ev) or "9999")

        # Strukturierte Rohdaten — LLM formuliert im JARVIS-Stil
        label = {"today": "heute", "tomorrow": "morgen", "week": "diese Woche"}.get(timeframe, timeframe)
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

        title = args["title"]
        date_str = args["date"]
        start_time = args.get("start_time", "")
        end_time = args.get("end_time", "")
        description = args.get("description", "")

        # Kalender-Entity: Config oder erster aus HA
        calendar_entity = self._get_write_calendar()
        if not calendar_entity:
            states = await self.ha.get_states()
            for s in (states or []):
                eid = s.get("entity_id", "")
                if eid.startswith("calendar."):
                    calendar_entity = eid
                    break

        if not calendar_entity:
            return {"success": False, "message": "Kein Kalender in Home Assistant gefunden"}

        service_data = {
            "entity_id": calendar_entity,
            "summary": title,
        }

        if start_time:
            # Termin mit Uhrzeit — ISO8601-Format fuer HA
            service_data["start_date_time"] = f"{date_str}T{start_time}:00"
            if end_time:
                service_data["end_date_time"] = f"{date_str}T{end_time}:00"
            else:
                # Standard: +1 Stunde
                try:
                    start_dt = datetime.strptime(f"{date_str} {start_time}", "%Y-%m-%d %H:%M")
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

        success = await self.ha.call_service(
            "calendar", "create_event", service_data
        )

        time_info = f" um {start_time}" if start_time else " (ganztaegig)"
        return {
            "success": success,
            "message": f"Termin '{title}' am {date_str}{time_info} erstellt" if success
                       else f"Termin konnte nicht erstellt werden",
        }

    async def _exec_delete_calendar_event(self, args: dict) -> dict:
        """Phase 11.3: Kalender-Termin loeschen.

        Sucht den Termin per Titel+Datum und loescht ihn via calendar.delete_event.
        """
        from datetime import datetime, timedelta

        title = args["title"]
        date_str = args["date"]

        # Kalender-Entity: Config oder erster aus HA
        calendar_entity = self._get_write_calendar()
        if not calendar_entity:
            states = await self.ha.get_states()
            for s in (states or []):
                if s.get("entity_id", "").startswith("calendar."):
                    calendar_entity = s.get("entity_id")
                    break

        if not calendar_entity:
            return {"success": False, "message": "Kein Kalender in Home Assistant gefunden"}

        # Events fuer den Tag abrufen um das richtige Event zu finden
        try:
            start = f"{date_str}T00:00:00"
            end_date = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
            end = end_date.strftime("%Y-%m-%dT00:00:00")

            result = await self.ha.call_service_with_response(
                "calendar", "get_events",
                {"entity_id": calendar_entity, "start_date_time": start, "end_date_time": end},
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
                return {"success": False, "message": f"Termin '{title}' am {date_str} nicht gefunden"}

            # Event loeschen
            uid = target_event.get("uid", "")
            if uid:
                success = await self.ha.call_service(
                    "calendar", "delete_event",
                    {"entity_id": calendar_entity, "uid": uid},
                )
            else:
                # Fallback: Ohne UID loeschen (Startzeit nutzen)
                # HA gibt start/end als ISO-String oder als Dict mit date/dateTime zurueck
                evt_start = target_event.get("start", start)
                evt_end = target_event.get("end", end)
                if isinstance(evt_start, dict):
                    evt_start = evt_start.get("dateTime", evt_start.get("date", start))
                if isinstance(evt_end, dict):
                    evt_end = evt_end.get("dateTime", evt_end.get("date", end))
                success = await self.ha.call_service(
                    "calendar", "delete_event",
                    {
                        "entity_id": calendar_entity,
                        "start_date_time": evt_start,
                        "end_date_time": evt_end,
                        "summary": target_event.get("summary", title),
                    },
                )

            return {
                "success": success,
                "message": f"Termin '{title}' am {date_str} geloescht" if success
                           else "Termin konnte nicht geloescht werden",
            }
        except Exception as e:
            logger.error("Kalender-Delete Fehler: %s", e)
            return {"success": False, "message": f"Der Kalender macht Schwierigkeiten: {e}"}

    async def _exec_reschedule_calendar_event(self, args: dict) -> dict:
        """Phase 11.3: Kalender-Termin verschieben (Delete + Re-Create).

        Atomisch: Wenn Create fehlschlaegt, wird der alte Termin wiederhergestellt.
        """
        title = args["title"]
        old_date = args["old_date"]
        new_date = args["new_date"]
        new_start = args.get("new_start_time", "")
        new_end = args.get("new_end_time", "")

        # Alten Termin finden um Start/End fuer Rollback zu merken
        old_start_time = args.get("old_start_time", "")
        old_end_time = args.get("old_end_time", "")

        # 1. Alten Termin loeschen
        delete_result = await self._exec_delete_calendar_event({
            "title": title,
            "date": old_date,
        })

        if not delete_result.get("success"):
            return {
                "success": False,
                "message": f"Der Termin laesst sich nicht verschieben: {delete_result.get('message', '')}",
            }

        # 2. Neuen Termin erstellen
        create_result = await self._exec_create_calendar_event({
            "title": title,
            "date": new_date,
            "start_time": new_start,
            "end_time": new_end,
        })

        if create_result.get("success"):
            return {
                "success": True,
                "message": f"Termin '{title}' verschoben von {old_date} nach {new_date}",
            }

        # 3. Rollback: Alten Termin wiederherstellen
        logger.warning("Reschedule-Rollback: Stelle alten Termin '%s' am %s wieder her", title, old_date)
        rollback_result = await self._exec_create_calendar_event({
            "title": title,
            "date": old_date,
            "start_time": old_start_time,
            "end_time": old_end_time,
        })
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
        mode = args["mode"]

        # Versuche input_select fuer Anwesenheitsmodus zu finden
        states = await self.ha.get_states()
        entity_id = None
        for s in (states or []):
            eid = s.get("entity_id", "")
            if eid.startswith("input_select.") and any(
                kw in eid for kw in ("presence", "anwesenheit", "presence_mode")
            ):
                entity_id = eid
                break

        if entity_id:
            success = await self.ha.call_service(
                "input_select", "select_option",
                {"entity_id": entity_id, "option": mode},
            )
            return {"success": success, "message": f"Anwesenheit: {mode}"}

        # Fallback: HA Event ueber REST API feuern
        success = await self.ha.fire_event(
            "mindhome_presence_mode", {"mode": mode}
        )
        if not success:
            # Letzter Fallback: input_boolean dynamisch suchen
            presence_entity = None
            for s in (states or []):
                eid = s.get("entity_id", "")
                if eid.startswith("input_boolean.") and any(
                    kw in eid for kw in ("zu_hause", "zuhause", "home", "presence", "anwesen")
                ):
                    presence_entity = eid
                    break
            if not presence_entity:
                return {
                    "success": False,
                    "message": "Kein Anwesenheits-Entity gefunden. Erstelle input_select oder input_boolean fuer Anwesenheit in Home Assistant.",
                }
            success = await self.ha.call_service(
                "input_boolean", "turn_on" if mode == "home" else "turn_off",
                {"entity_id": presence_entity},
            )
        return {"success": success, "message": f"Anwesenheit: {mode}"}

    async def _find_speaker_in_room(self, room: str) -> Optional[str]:
        """Phase 10.1: Findet einen TTS-Speaker in einem bestimmten Raum.

        Sucht zuerst in der Konfiguration (room_speakers),
        dann per Entity-Name-Matching (nur echte Speaker, keine TVs).
        """
        # 1. Konfiguriertes Mapping pruefen
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
            if room_lower in entity_id.lower() and self._is_tts_speaker(entity_id, attributes):
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
    # Hinweis: Alexa/Echo nicht mehr ausgeschlossen — wird ueber
    # sounds.alexa_speakers Config behandelt (notify statt Audio)
    _EXCLUDED_SPEAKER_PATTERNS = (
        "tv", "fernseher", "television", "fire_tv", "firetv", "apple_tv",
        "appletv", "chromecast", "roku", "shield", "receiver", "avr",
        "denon", "marantz", "yamaha_receiver", "onkyo", "pioneer",
        "soundbar", "xbox", "playstation", "ps5", "ps4", "nintendo",
        "kodi", "plex", "emby", "jellyfin", "vlc", "mpd",
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
        - Snapshot vor jeder Aenderung (Rollback jederzeit moeglich)
        - yaml.safe_dump() verhindert Code-Injection
        """
        config_file = args["config_file"]
        action = args["action"]
        key = args["key"]
        data = args.get("data", {})

        yaml_path = _EDITABLE_CONFIGS.get(config_file)
        if not yaml_path:
            return {"success": False, "message": f"Config '{config_file}' ist nicht editierbar"}

        try:
            # Snapshot vor Aenderung (Rollback-Sicherheitsnetz)
            if self._config_versioning and self._config_versioning.is_enabled():
                await self._config_versioning.create_snapshot(
                    config_file, yaml_path,
                    reason=f"edit_config:{action}:{key}",
                    changed_by="jarvis",
                )

            # Config laden
            if yaml_path.exists():
                with open(yaml_path) as f:
                    config = yaml.safe_load(f) or {}
            else:
                config = {}

            # Aktion ausfuehren
            if action == "add":
                if not data:
                    return {"success": False, "message": "Keine Daten zum Hinzufuegen angegeben"}
                if key in config:
                    return {"success": False, "message": f"'{key}' existiert bereits. Nutze 'update' stattdessen."}
                config[key] = data
                msg = f"'{key}' zu {config_file} hinzugefuegt"
            elif action == "update":
                if key not in config:
                    return {"success": False, "message": f"'{key}' nicht in {config_file} gefunden"}
                if isinstance(config[key], dict) and isinstance(data, dict):
                    config[key].update(data)
                else:
                    config[key] = data
                msg = f"'{key}' in {config_file} aktualisiert"
            elif action == "remove":
                if key not in config:
                    return {"success": False, "message": f"'{key}' nicht in {config_file} gefunden"}
                del config[key]
                msg = f"'{key}' aus {config_file} entfernt"
            else:
                return {"success": False, "message": f"Unbekannte Aktion: {action}"}

            # Zurueckschreiben
            with open(yaml_path, "w") as f:
                yaml.safe_dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

            # Cache invalidieren damit Aenderungen sofort wirken
            if config_file == "room_profiles":
                cfg_module._room_profiles_cache.clear()
                cfg_module._room_profiles_ts = 0.0
                logger.info("Room-Profiles-Cache invalidiert nach edit_config")

            logger.info("Config-Selbstmodifikation: %s (%s -> %s)", config_file, action, key)
            return {"success": True, "message": msg}

        except Exception as e:
            logger.error("Config-Edit fehlgeschlagen: %s", e)
            return {"success": False, "message": f"Die Konfiguration laesst sich gerade nicht aendern: {e}"}

    # ------------------------------------------------------------------
    # Phase 15.2: Einkaufsliste (via HA Shopping List oder lokal)
    # ------------------------------------------------------------------

    async def _exec_manage_shopping_list(self, args: dict) -> dict:
        """Phase 15.2: Einkaufsliste verwalten ueber Home Assistant."""
        action = args["action"]
        item = args.get("item", "")

        if action == "add":
            if not item:
                return {"success": False, "message": "Kein Artikel angegeben"}
            success = await self.ha.call_service(
                "shopping_list", "add_item", {"name": item}
            )
            return {"success": success, "message": f"'{item}' auf die Einkaufsliste gesetzt" if success
                    else "Einkaufsliste nicht verfuegbar"}

        elif action == "list":
            # Shopping List ueber HA API abrufen
            try:
                items = await self.ha.api_get("/api/shopping_list")
                if not items:
                    return {"success": True, "message": "Die Einkaufsliste ist leer."}
                open_items = [i["name"] for i in items if not i.get("complete")]
                done_items = [i["name"] for i in items if i.get("complete")]
                parts = []
                if open_items:
                    parts.append("Einkaufsliste:\n" + "\n".join(f"- {i}" for i in open_items))
                if done_items:
                    parts.append(f"Erledigt: {', '.join(done_items)}")
                if not open_items and not done_items:
                    return {"success": True, "message": "Die Einkaufsliste ist leer."}
                return {"success": True, "message": "\n".join(parts)}
            except Exception as e:
                logger.debug("Einkaufsliste Fehler: %s", e)
                return {"success": False, "message": "Einkaufsliste nicht verfuegbar"}

        elif action == "complete":
            if not item:
                return {"success": False, "message": "Kein Artikel zum Abhaken angegeben"}
            success = await self.ha.call_service(
                "shopping_list", "complete_item", {"name": item}
            )
            return {"success": success, "message": f"'{item}' abgehakt" if success
                    else "Artikel nicht gefunden"}

        elif action == "clear_completed":
            success = await self.ha.call_service(
                "shopping_list", "complete_all", {}
            )
            return {"success": success, "message": "Abgehakte Artikel entfernt" if success
                    else "Fehler beim Aufraumen"}

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
                "Rolllaeden steuern",
                "Szenen aktivieren (Filmabend, Gute Nacht, etc.)",
                "Alarmanlage steuern",
                "Tueren ver-/entriegeln",
                "Anwesenheitsmodus setzen (Home/Away/Sleep/Vacation)",
            ],
            "medien": [
                "Musik abspielen/pausieren/stoppen",
                "Naechster/vorheriger Titel",
                "Musik zwischen Raeumen uebertragen",
                "Sound-Effekte abspielen",
            ],
            "kommunikation": [
                "Nachrichten an Personen senden (TTS oder Push)",
                "Benachrichtigungen (Handy, Speaker, Dashboard)",
                "Proaktive Meldungen (Alarm, Tuerklingel, Waschmaschine, etc.)",
            ],
            "gedaechtnis": [
                "'Merk dir X' — Fakten speichern",
                "'Was weisst du ueber X?' — Wissen abrufen",
                "'Vergiss X' — Fakten loeschen",
                "Automatische Fakten-Extraktion aus Gespraechen",
                "Langzeit-Erinnerungen und Tages-Zusammenfassungen",
            ],
            "wissen": [
                "Allgemeine Wissensfragen beantworten",
                "Kalender-Termine anzeigen und erstellen",
                "'Was waere wenn'-Simulationen",
                "Wissensdatenbank (Dokumente, RAG)",
                "Kochen mit Schritt-fuer-Schritt-Anleitung + Timer",
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
                "Eigene Config anpassen (Easter Eggs, Meinungen, Raeume)",
                "Feedback-basierte Optimierung proaktiver Meldungen",
            ],
            "automationen": [
                "Automationen aus natuerlicher Sprache erstellen ('Wenn ich nach Hause komme, Licht an')",
                "Sicherheits-Whitelist (nur erlaubte Services)",
                "Vorschau + Bestaetigung vor Aktivierung",
                "Jarvis-Automationen auflisten und loeschen",
                "Kill-Switch: Alle Jarvis-Automationen deaktivieren",
            ],
        }

        lines = ["Das kann ich fuer dich tun:\n"]
        for category, items in capabilities.items():
            label = category.replace("_", " ").title()
            lines.append(f"{label}:")
            for item in items:
                lines.append(f"  - {item}")
            lines.append("")

        return {"success": True, "message": "\n".join(lines)}

    # ------------------------------------------------------------------
    # Phase 13.2: Self Automation
    # ------------------------------------------------------------------

    async def _exec_create_automation(self, args: dict) -> dict:
        """Phase 13.2: Erstellt eine Automation aus natuerlicher Sprache."""
        import assistant.main as main_module
        brain = main_module.brain
        self_auto = brain.self_automation

        description = args.get("description", "")
        if not description:
            return {"success": False, "message": "Keine Beschreibung angegeben."}

        return await self_auto.generate_automation(description)

    async def _exec_confirm_automation(self, args: dict) -> dict:
        """Phase 13.2: Bestaetigt eine ausstehende Automation."""
        import assistant.main as main_module
        brain = main_module.brain
        self_auto = brain.self_automation

        pending_id = args.get("pending_id", "")
        if not pending_id:
            return {"success": False, "message": "Keine Pending-ID angegeben."}

        return await self_auto.confirm_automation(pending_id)

    async def _exec_list_jarvis_automations(self, args: dict) -> dict:
        """Phase 13.2: Listet alle Jarvis-Automationen auf."""
        import assistant.main as main_module
        brain = main_module.brain
        return await brain.self_automation.list_jarvis_automations()

    async def _exec_delete_jarvis_automation(self, args: dict) -> dict:
        """Phase 13.2: Loescht eine Jarvis-Automation."""
        import assistant.main as main_module
        brain = main_module.brain

        automation_id = args.get("automation_id", "")
        if not automation_id:
            return {"success": False, "message": "Keine Automation-ID angegeben."}

        return await brain.self_automation.delete_jarvis_automation(automation_id)

    @staticmethod
    def _normalize_name(text: str) -> str:
        """Normalisiert Umlaute und Sonderzeichen fuer Entity-Matching."""
        n = text.lower()
        # Unicode-Umlaute zuerst
        n = n.replace("ü", "u").replace("ä", "a").replace("ö", "o").replace("ß", "ss")
        # Dann ASCII-Digraphen
        n = n.replace("ue", "u").replace("ae", "a").replace("oe", "o")
        # LLM-Varianten: "bureau" statt "buero"/"büro"
        n = n.replace("bureau", "buro")
        return n.replace(" ", "_")

    async def _find_entity(self, domain: str, search: str, device_hint: str = "", person: str = "") -> Optional[str]:
        """Findet eine Entity anhand von Domain und Suchbegriff.

        Matching-Strategie (Best-Match statt First-Match):
        1. MindHome Device-DB (schnell, DB-basiert) — bester Match
        2. Fallback: Alle HA-States durchsuchen — bester Match
        Exakter Match > kuerzester Partial-Match (spezifischstes Ergebnis)

        device_hint: Optionaler Geraetename (z.B. 'stehlampe', 'deckenlampe')
                     zur Disambiguierung bei mehreren Geraeten im selben Raum.
        person: Optionaler Personenname (z.B. 'Manuel', 'Julia')
                zur Disambiguierung wenn mehrere Raeume gleich heissen
                (z.B. 'Manuel Buero' vs 'Julia Buero').
        """
        if not search:
            return None

        search_norm = self._normalize_name(search)
        hint_norm = self._normalize_name(device_hint) if device_hint else ""
        person_norm = self._normalize_name(person) if person else ""

        # Spezifische Geraete-Begriffe: werden bei der Auswahl deprioritisiert,
        # wenn kein device_hint angegeben ist, damit das Hauptgeraet im Raum
        # bevorzugt wird (z.B. Deckenlampe statt Stehlampe).
        _SPECIFIC_DEVICE_TERMS = {
            "stehlampe", "stehleuchte", "nachttisch", "nachttischlampe",
            "leselampe", "tischlampe", "tischleuchte", "led_strip",
            "ledstrip", "lichterkette", "nachtlicht", "spot",
        }

        # MindHome Device-Search (schnell, DB-basiert)
        try:
            devices = await self.ha.search_devices(domain=domain, room=search)
            if devices:
                logger.info("_find_entity: DB lieferte %d Treffer fuer '%s' (domain=%s, hint='%s'): %s",
                            len(devices), search, domain, device_hint or "",
                            [(d.get("name"), d.get("room"), d.get("ha_entity_id")) for d in devices])

                # Wenn device_hint angegeben: zuerst nach Geraetename filtern
                if hint_norm:
                    for dev in devices:
                        dev_name = self._normalize_name(dev.get("name", ""))
                        eid_name = self._normalize_name(dev.get("ha_entity_id", "").split(".", 1)[-1])
                        if hint_norm in dev_name or hint_norm in eid_name:
                            logger.info("_find_entity: Device-Hint '%s' matched -> %s", device_hint, dev["ha_entity_id"])
                            return dev["ha_entity_id"]
                    # Hint passt auf kein Geraet -> weiter ohne Hint
                    logger.info("_find_entity: Device-Hint '%s' matched kein DB-Ergebnis, ignoriere Hint", device_hint)

                # Best-Match: Exakt > kuerzester Partial (mit Match-Pruefung!)
                best = None
                best_score = float("inf")
                for dev in devices:
                    eid = dev.get("ha_entity_id", "")
                    # Domain-Check: Entities aus falscher Domain ueberspringen
                    # (DB kann z.B. sensor.* liefern obwohl domain=light)
                    if domain and eid and not eid.startswith(f"{domain}."):
                        logger.debug("_find_entity: Ueberspringe %s (domain=%s erwartet)", eid, domain)
                        continue
                    dev_name = self._normalize_name(dev.get("name", ""))
                    dev_room = self._normalize_name(dev.get("room", "") or "")
                    eid_name = self._normalize_name(eid.split(".", 1)[-1])

                    matched = False
                    # Exakter Raum-Match hat hoechste Prioritaet
                    if dev_room == search_norm:
                        matched = True
                    # Exakter Name-Match
                    elif search_norm == dev_name:
                        logger.info("_find_entity: Exakter Name-Match -> %s", dev["ha_entity_id"])
                        return dev["ha_entity_id"]
                    # Partial Match: bidirektional (Suchbegriff IN Entity ODER Entity IN Suchbegriff)
                    elif (search_norm in dev_name or search_norm in dev_room
                          or dev_room in search_norm or dev_name in search_norm):
                        matched = True

                    # Annotation-Bonus: Role/Description match
                    annotation = get_entity_annotation(eid)
                    annotation_bonus = 0
                    if annotation:
                        if annotation.get("hidden"):
                            continue
                        ann_role = annotation.get("role", "")
                        ann_desc = self._normalize_name(annotation.get("description", ""))
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
                        # Ohne device_hint: Spezifische Geraete mit Malus versehen,
                        # damit "Wohnzimmer Licht" vor "Stehlampe Wohnzimmer" gewaehlt wird
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
                        # Person-Kontext: Wenn der Personenname im Raum/Geraet vorkommt,
                        # Bonus geben (z.B. Manuel sagt "Buero" -> "Manuel Buero" bevorzugen)
                        person_bonus = 0
                        if person_norm:
                            combined_for_person = f"{dev_name} {dev_room}"
                            if person_norm in combined_for_person:
                                person_bonus = -500
                        score = name_len + penalty + name_bonus + person_bonus + annotation_bonus
                        if score < best_score:
                            best = dev["ha_entity_id"]
                            best_score = score
                if best:
                    logger.info("_find_entity: Best Match -> %s (score=%d)", best, best_score)
                    return best
                # Kein Match in DB-Ergebnissen — weiter zu HA-Fallback
                logger.info("_find_entity: Kein Name/Raum-Match in %d DB-Ergebnissen, HA-Fallback", len(devices))
            else:
                logger.info("_find_entity: DB lieferte 0 Treffer fuer '%s', HA-Fallback", search)
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

            # Hidden-Entities ueberspringen
            if is_entity_hidden(entity_id):
                continue

            name = entity_id.split(".", 1)[1]
            name_norm = self._normalize_name(name)
            friendly = state.get("attributes", {}).get("friendly_name", "")
            friendly_norm = self._normalize_name(friendly) if friendly else ""

            # Device-Hint: Geraetename muss im entity oder friendly_name vorkommen
            if hint_norm:
                if hint_norm in name_norm or (friendly_norm and hint_norm in friendly_norm):
                    # Zusaetzlich pruefen ob auch der Raum passt
                    if search_norm in name_norm or (friendly_norm and search_norm in friendly_norm):
                        logger.info("_find_entity: HA-Fallback Hint-Match -> %s", entity_id)
                        return entity_id

            # Exakter Match → sofort zurueck
            if search_norm == name_norm or search_norm == friendly_norm:
                return entity_id

            # Partial Match → besten (kuerzesten) merken (bidirektional)
            matched = False
            if search_norm in name_norm or name_norm in search_norm:
                matched = True
            elif friendly_norm and (search_norm in friendly_norm or friendly_norm in search_norm):
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

        if not best_match:
            # Diagnose: Alle verfuegbaren Entities dieser Domain loggen
            available = [
                f"{s.get('entity_id')} ('{s.get('attributes', {}).get('friendly_name', '')}')"
                for s in (states or [])
                if s.get("entity_id", "").startswith(f"{domain}.")
            ]
            logger.warning(
                "_find_entity: KEIN Match fuer '%s' (norm='%s') in domain '%s'. "
                "Verfuegbare Entities: %s",
                search, search_norm, domain, available[:20]
            )

        return best_match

    # ------------------------------------------------------------------
    # Phase 15.2: Vorrats-Tracking
    # ------------------------------------------------------------------

    async def _exec_manage_inventory(self, args: dict) -> dict:
        """Verwaltet den Vorrat."""
        # Inventory Manager aus dem brain holen
        from .brain import AssistantBrain
        import assistant.main as main_module
        brain = main_module.brain
        inventory = brain.inventory

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
            return await inventory.list_items(category if category != "sonstiges" else "")

        elif action == "update_quantity":
            if not item:
                return {"success": False, "message": "Kein Artikel angegeben."}
            return await inventory.update_quantity(item, quantity)

        elif action == "check_expiring":
            expiring = await inventory.check_expiring(days_ahead=3)
            if not expiring:
                return {"success": True, "message": "Keine Artikel laufen in den naechsten 3 Tagen ab."}
            lines = [f"{len(expiring)} Artikel laufen bald ab:"]
            for item_data in expiring:
                days = item_data["days_left"]
                if days < 0:
                    lines.append(f"- {item_data['name']}: ABGELAUFEN seit {abs(days)} Tag(en)!")
                elif days == 0:
                    lines.append(f"- {item_data['name']}: laeuft HEUTE ab!")
                else:
                    lines.append(f"- {item_data['name']}: noch {days} Tag(e)")
            return {"success": True, "message": "\n".join(lines)}

        return {"success": False, "message": f"Unbekannte Aktion: {action}"}

    # ------------------------------------------------------------------
    # Workshop-Modus: Reparatur & Werkstatt
    # ------------------------------------------------------------------

    async def _exec_manage_repair(self, args: dict) -> dict:
        """Dispatch fuer alle Workshop-Aktionen."""
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
                priority=args.get("priority", "normal"))
        elif action == "list_projects":
            projects = await planner.list_projects(
                status_filter=args.get("status"),
                category_filter=args.get("category"))
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
                pid, args.get("item", ""), args.get("quantity", 1),
                args.get("cost", 0))

        # --- LLM-Features ---
        elif action == "diagnose":
            return {"success": True,
                    "message": await planner.diagnose_problem(
                        args.get("description", ""), args.get("person", ""))}
        elif action == "simulate":
            return {"success": True,
                    "message": await planner.simulate_design(
                        pid, args.get("description", ""))}
        elif action == "troubleshoot":
            return {"success": True,
                    "message": await planner.troubleshoot(
                        pid, args.get("description", ""))}
        elif action == "suggest_improvements":
            return {"success": True,
                    "message": await planner.suggest_improvements(pid)}
        elif action == "compare_components":
            return {"success": True,
                    "message": await planner.compare_components(
                        args.get("component_a", ""), args.get("component_b", ""),
                        use_case=args.get("description", ""))}
        elif action == "safety_checklist":
            return {"success": True,
                    "message": await planner.generate_safety_checklist(pid)}
        elif action == "calibration_guide":
            return {"success": True,
                    "message": await planner.calibration_guide(
                        args.get("description", ""))}
        elif action == "analyze_error_log":
            return {"success": True,
                    "message": await planner.analyze_error_log(
                        pid, args.get("text", ""))}
        elif action == "evaluate_measurement":
            return {"success": True,
                    "message": await planner.evaluate_measurement(
                        pid, args.get("text", ""))}

        # --- Generator ---
        elif action == "generate_code":
            if not generator:
                return {"success": False,
                        "message": "Workshop-Generator nicht verfuegbar"}
            return await generator.generate_code(
                pid, args.get("description", ""),
                language=args.get("language", "arduino"))
        elif action == "generate_3d":
            if not generator:
                return {"success": False,
                        "message": "Workshop-Generator nicht verfuegbar"}
            return await generator.generate_3d_model(
                pid, args.get("description", ""))
        elif action == "generate_schematic":
            if not generator:
                return {"success": False,
                        "message": "Workshop-Generator nicht verfuegbar"}
            return await generator.generate_schematic(
                pid, args.get("description", ""))
        elif action == "generate_website":
            if not generator:
                return {"success": False,
                        "message": "Workshop-Generator nicht verfuegbar"}
            return await generator.generate_website(
                pid, args.get("description", ""))
        elif action == "generate_bom":
            if not generator:
                return {"success": False,
                        "message": "Workshop-Generator nicht verfuegbar"}
            return await generator.generate_bom(pid)
        elif action == "generate_docs":
            if not generator:
                return {"success": False,
                        "message": "Workshop-Generator nicht verfuegbar"}
            return await generator.generate_documentation(pid)
        elif action == "generate_tests":
            if not generator:
                return {"success": False,
                        "message": "Workshop-Generator nicht verfuegbar"}
            return await generator.generate_tests(
                pid, args.get("filename", ""))

        # --- Berechnungen ---
        elif action == "calculate":
            if not generator:
                return {"success": False,
                        "message": "Workshop-Generator nicht verfuegbar"}
            return generator.calculate(
                args.get("calc_type", ""), **args.get("calc_params", {}))

        # --- Scanner ---
        elif action == "scan_object":
            return await planner.scan_object(
                description=args.get("description", ""))

        # --- Library ---
        elif action == "search_library":
            if hasattr(brain, 'workshop_library') and brain.workshop_library:
                results = await brain.workshop_library.search(
                    args.get("query", ""))
                return {"success": True, "results": results}
            return {"success": False,
                    "message": "Workshop-Library nicht verfuegbar"}

        # --- Werkstatt-Inventar ---
        elif action == "add_workshop_item":
            return await planner.add_workshop_item(
                args.get("item", ""), quantity=args.get("quantity", 1),
                category=args.get("category", "werkzeug"))
        elif action == "list_workshop":
            items = await planner.list_workshop(
                category=args.get("category"))
            return {"success": True, "items": items}

        # --- Budget ---
        elif action == "set_budget":
            return await planner.set_project_budget(
                pid, args.get("budget", 0))
        elif action == "add_expense":
            return await planner.add_expense(
                pid, args.get("item", ""), args.get("cost", 0))

        # --- 3D-Drucker ---
        elif action == "printer_status":
            return await planner.get_printer_status()
        elif action == "start_print":
            return await planner.start_print(
                project_id=pid, filename=args.get("filename", ""))
        elif action == "pause_print":
            return await planner.pause_print()
        elif action == "cancel_print":
            return await planner.cancel_print()

        # --- Roboterarm ---
        elif action == "arm_move":
            return await planner.arm_move(
                args.get("x", 0), args.get("y", 0), args.get("z", 0))
        elif action == "arm_gripper":
            return await planner.arm_gripper(
                args.get("description", "open"))
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
                args.get("item", ""), args.get("text", ""),
                language=args.get("language", ""))
        elif action == "get_snippet":
            return await planner.get_snippet(args.get("item", ""))

        # --- Verleih ---
        elif action == "lend_tool":
            return await planner.lend_tool(
                args.get("item", ""), args.get("person", ""))
        elif action == "return_tool":
            return await planner.return_tool(args.get("item", ""))
        elif action == "list_lent":
            return {"success": True,
                    "lent_tools": await planner.list_lent_tools()}

        # --- Templates ---
        elif action == "create_from_template":
            return await planner.create_from_template(
                args.get("template", ""), title=args.get("title", ""))

        # --- Stats ---
        elif action == "get_stats":
            return await planner.get_workshop_stats()

        # --- Multi-Project ---
        elif action == "switch_project":
            return await planner.switch_project(pid)
        elif action == "export_project":
            if not generator:
                return {"success": False,
                        "message": "Workshop-Generator nicht verfuegbar"}
            path = await generator.export_project(pid)
            return ({"success": True, "zip_path": path} if path
                    else {"success": False, "message": "Keine Dateien"})

        # --- Devices ---
        elif action == "check_device":
            return await planner.check_device_online(
                args.get("entity_id", ""))
        elif action == "link_device":
            return await planner.link_device_to_project(
                pid, args.get("entity_id", ""))
        elif action == "get_power":
            return await planner.get_power_consumption(
                args.get("entity_id", ""))

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

    async def _exec_set_reminder(self, args: dict) -> dict:
        """Setzt eine Erinnerung fuer eine bestimmte Uhrzeit."""
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
            return {"success": False, "message": "Keine Uhrzeit angegeben. Format: HH:MM"}
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
                    "notify", svc_name,
                    {"message": message, "data": {"type": "tts"}},
                )
            else:
                tts_entity = yaml_config.get("tts", {}).get("entity", "tts.piper")
                await self.ha.call_service("tts", "speak", {
                    "entity_id": tts_entity,
                    "media_player_entity_id": speaker,
                    "message": message,
                })
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
            "broadcast_cooldown_seconds", self._BROADCAST_COOLDOWN_SECONDS,
        )
        if now - self._last_broadcast_time < cooldown:
            remaining = int(cooldown - (now - self._last_broadcast_time))
            return {"success": False, "message": f"Durchsage-Cooldown. Bitte {remaining}s warten."}
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
        for s in (states or []):
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
            "message": f"Durchsage an {count}/{len(speakers)} Lautsprecher: \"{message}\"",
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
                target_room = brain.context_builder.get_person_room(
                    target_person, states=states,
                ) or ""

        if not target_room:
            return {
                "success": False,
                "message": f"Raum fuer {'Person ' + target_person if target_person else 'Durchsage'} nicht ermittelt. Bitte Raum angeben.",
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

        # Speaker-Verfuegbarkeit pruefen
        speaker_state = await self.ha.get_state(speaker)
        if speaker_state and speaker_state.get("state") == "unavailable":
            return {"success": False, "message": f"Der Lautsprecher '{speaker}' schweigt sich aus. Nicht erreichbar."}

        # TTS senden
        ok = await self._send_tts_to_speaker(speaker, tts_message)
        target_desc = f"{target_person} im {target_room}" if target_person else target_room
        if ok:
            return {"success": True, "message": f"Durchsage an {target_desc}: \"{message}\""}
        return {"success": False, "message": f"Die Durchsage an {target_desc} kam nicht durch. Ich pruefe die Verbindung."}

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
        return await brain.conditional_commands.create_conditional(
            trigger_type=args["trigger_type"],
            trigger_value=args["trigger_value"],
            action_function=args["action_function"],
            action_args=args.get("action_args", {}),
            label=args.get("label", ""),
            ttl_hours=args.get("ttl_hours", 24),
            one_shot=args.get("one_shot", True),
        )

    async def _exec_list_conditionals(self, args: dict) -> dict:
        """Listet bedingte Befehle auf."""
        import assistant.main as main_module
        brain = main_module.brain
        return await brain.conditional_commands.list_conditionals()

    async def _exec_get_energy_report(self, args: dict) -> dict:
        """Zeigt Energie-Bericht an."""
        import assistant.main as main_module
        brain = main_module.brain
        return await brain.energy_optimizer.get_energy_report()

    async def _exec_web_search(self, args: dict) -> dict:
        """Fuehrt eine Web-Suche durch."""
        import assistant.main as main_module
        brain = main_module.brain
        return await brain.web_search.search(query=args.get("query", ""))

    async def _exec_get_security_score(self, args: dict) -> dict:
        """Gibt den aktuellen Sicherheits-Score zurueck."""
        import assistant.main as main_module
        brain = main_module.brain
        try:
            result = await brain.threat_assessment.get_security_score()
            details = result.get("details", [])
            return {
                "success": True,
                "score": result["score"],
                "level": result["level"],
                "details": ", ".join(details) if details else "Alles in Ordnung",
            }
        except Exception as e:
            return {"success": False, "message": f"Sicherheits-Check fehlgeschlagen: {e}"}

    async def _exec_get_room_climate(self, args: dict) -> dict:
        """Gibt Raumklima-Daten zurueck."""
        import assistant.main as main_module
        brain = main_module.brain
        try:
            result = await brain.health_monitor.get_status()
            return {"success": True, **result}
        except Exception as e:
            return {"success": False, "message": f"Raumklima-Check fehlgeschlagen: {e}"}

    async def _exec_get_active_intents(self, args: dict) -> dict:
        """Gibt aktive Vorhaben/Intents zurueck."""
        import assistant.main as main_module
        brain = main_module.brain
        try:
            intents = await brain.intent_tracker.get_active_intents()
            if not intents:
                return {"success": True, "message": "Keine anstehenden Vorhaben gemerkt.", "intents": []}
            summaries = []
            for intent in intents:
                summaries.append({
                    "intent": intent.get("intent", ""),
                    "deadline": intent.get("deadline", ""),
                    "person": intent.get("person", ""),
                    "reminder": intent.get("reminder_text", ""),
                })
            return {"success": True, "count": len(summaries), "intents": summaries}
        except Exception as e:
            return {"success": False, "message": f"Intent-Abfrage fehlgeschlagen: {e}"}

    async def _exec_get_wellness_status(self, args: dict) -> dict:
        """Gibt den Wellness-Status des Users zurueck."""
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
                        minutes = (datetime.now() - start_dt).total_seconds() / 60
                        status["pc_minutes"] = round(minutes)
                    except (ValueError, TypeError):
                        pass

                last_hydration = await brain.memory.redis.get("mha:wellness:last_hydration")
                if last_hydration:
                    status["last_hydration"] = last_hydration

            # Aktivitaet
            try:
                detection = await brain.activity.detect_activity()
                status["activity"] = detection.get("activity", "unknown")
            except Exception as e:
                logger.debug("Activity-Detection fehlgeschlagen: %s", e)

            return {"success": True, "message": str(status), **status}
        except Exception as e:
            return {"success": False, "message": f"Wellness-Check fehlgeschlagen: {e}"}

    async def _exec_get_house_status(self, args: dict) -> dict:
        """Gibt den Haus-Status zurueck — konfigurierbar via settings.yaml.

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
              - open_items    # Offene Fenster/Tueren
              - offline       # Offline-Geraete
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
                "presence", "temperatures", "weather", "lights",
                "security", "media", "open_items", "offline",
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
                            if temp_rooms and room.lower() not in [r.lower() for r in temp_rooms]:
                                continue
                            current = data.get("current")
                            if current is None:
                                continue
                            target = data.get("target")
                            if target:
                                temp_strs.append(f"{room}: {current}°C (Soll {target}°C)")
                            else:
                                temp_strs.append(f"{room}: {current}°C")
                        if temp_strs:
                            parts.append(f"Temperaturen: {', '.join(temp_strs)}")

            # Wetter
            if "weather" in enabled_sections:
                weather = house.get("weather", {})
                if weather:
                    _cond_map = {
                        "sunny": "Sonnig", "clear-night": "Klare Nacht",
                        "partlycloudy": "Teilweise bewoelkt", "cloudy": "Bewoelkt",
                        "rainy": "Regen", "pouring": "Starkregen",
                        "snowy": "Schnee", "snowy-rainy": "Schneeregen",
                        "fog": "Nebel", "hail": "Hagel",
                        "lightning": "Gewitter", "lightning-rainy": "Gewitter mit Regen",
                        "windy": "Windig", "windy-variant": "Windig & bewoelkt",
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

            # Offene Fenster/Tueren — kategorisiert nach Typ (Fenster/Tuer vs Tor)
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

            # Offline Geraete
            if "offline" in enabled_sections:
                unavailable = []
                for s in states:
                    if s.get("state") == "unavailable":
                        name = s.get("attributes", {}).get("friendly_name", s.get("entity_id", "?"))
                        unavailable.append(name)
                if unavailable:
                    parts.append(f"Offline ({len(unavailable)}): {', '.join(unavailable[:10])}")

            if not parts:
                parts.append("Keine Sektionen konfiguriert. Pruefe house_status.sections in settings.yaml.")

            message = "\n".join(parts)
            return {"success": True, "message": message}
        except Exception as e:
            return {"success": False, "message": f"Haus-Status fehlgeschlagen: {e}"}

    async def _exec_get_full_status_report(self, args: dict) -> dict:
        """Aggregiert alle Datenquellen fuer einen narrativen JARVIS-Statusbericht."""
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

        # 5. Offene Erinnerungen / Intents
        try:
            if hasattr(brain, "intent_tracker"):
                active = await brain.intent_tracker.get_active_intents()
                if active:
                    intent_lines = []
                    for intent in active[:5]:
                        desc = intent.get("description", intent.get("text", "?"))
                        intent_lines.append(f"- {desc}")
                    report_parts.append(f"OFFENE ERINNERUNGEN:\n" + "\n".join(intent_lines))
        except Exception as e:
            logger.debug("Status-Report: Intents fehlgeschlagen: %s", e)

        if not report_parts:
            return {"success": False, "message": "Keine Daten fuer Statusbericht verfuegbar."}

        raw_report = "\n\n".join(report_parts)
        return {"success": True, "message": raw_report}

    async def _exec_get_weather(self, args: dict) -> dict:
        """Aktuelles Wetter und Vorhersage von Home Assistant."""
        # Vorhersage immer mitliefern — LLM entscheidet was davon relevant ist
        include_forecast = True

        states = await self.ha.get_states()
        if not states:
            return {"success": False, "message": "Kann gerade nicht auf Home Assistant zugreifen."}

        weather_entity = None
        for s in states:
            if s.get("entity_id", "").startswith("weather."):
                weather_entity = s
                break

        if not weather_entity:
            return {"success": False, "message": "Keine Wetter-Entity in Home Assistant gefunden."}

        attrs = weather_entity.get("attributes", {})
        condition = weather_entity.get("state", "unbekannt")
        temp = attrs.get("temperature")
        humidity = attrs.get("humidity")
        wind_speed = attrs.get("wind_speed")
        wind_bearing = attrs.get("wind_bearing")
        pressure = attrs.get("pressure")

        # Wetter-Zustand uebersetzen
        condition_map = {
            "sunny": "Sonnig", "clear-night": "Klare Nacht",
            "partlycloudy": "Teilweise bewoelkt", "cloudy": "Bewoelkt",
            "rainy": "Regen", "pouring": "Starkregen",
            "snowy": "Schnee", "snowy-rainy": "Schneeregen",
            "fog": "Nebel", "hail": "Hagel",
            "lightning": "Gewitter", "lightning-rainy": "Gewitter mit Regen",
            "windy": "Windig", "windy-variant": "Windig & bewoelkt",
            "exceptional": "Ausnahmewetter",
        }
        condition_de = condition_map.get(condition, condition)

        # Windrichtung bestimmen
        wind_dir = ""
        if wind_bearing is not None:
            directions = ["Nord", "Nordost", "Ost", "Suedost",
                          "Sued", "Suedwest", "West", "Nordwest"]
            try:
                idx = round(float(wind_bearing) / 45) % 8
                wind_dir = directions[idx]
            except (ValueError, TypeError):
                pass

        # Rohdaten sammeln — LLM formuliert im JARVIS-Stil
        parts = []

        # Aktuelles Wetter immer mitliefern
        current = f"AKTUELL: {condition_de}, {temp}°C" if temp is not None else f"AKTUELL: {condition_de}"
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
                    "weather", "get_forecasts",
                    {"entity_id": entity_id, "type": "daily"},
                )
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
                    fc_cond = condition_map.get(entry.get("condition", ""), entry.get("condition", "?"))
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
                # Keine Vorhersage verfuegbar — still weglassen statt Fehlermeldung
                # Das LLM/Humanizer antwortet dann nur mit den aktuellen Daten
                logger.info("Wetter-Vorhersage nicht verfuegbar (HA-Integration liefert keine Prognosedaten)")

        return {"success": True, "message": "\n".join(parts)}

    async def _exec_get_device_health(self, args: dict) -> dict:
        """Gibt den Geraete-Gesundheitsstatus zurueck."""
        import assistant.main as main_module
        brain = main_module.brain
        try:
            status = await brain.device_health.get_status()
            # Aktuelle Anomalien pruefen
            alerts = await brain.device_health.check_all()
            alert_msgs = [a.get("message", "") for a in alerts[:5]] if alerts else []
            return {
                "success": True,
                "message": f"{len(alerts)} Anomalie(n)" if alerts else "Alle Geraete normal",
                "alerts": alert_msgs,
                **status,
            }
        except Exception as e:
            return {"success": False, "message": f"Geraete-Check fehlgeschlagen: {e}"}

    async def _exec_get_learned_patterns(self, args: dict) -> dict:
        """Gibt erkannte Verhaltensmuster zurueck."""
        import assistant.main as main_module
        brain = main_module.brain
        try:
            patterns = await brain.learning_observer.get_learned_patterns()
            if not patterns:
                return {"success": True, "message": "Noch keine Muster erkannt.", "patterns": []}
            summaries = []
            for p in patterns:
                summaries.append({
                    "action": p.get("action", ""),
                    "time": p.get("time_slot", ""),
                    "count": p.get("count", 0),
                    "weekday": p.get("weekday", -1),
                })
            return {
                "success": True,
                "count": len(summaries),
                "message": f"{len(summaries)} Muster erkannt",
                "patterns": summaries,
            }
        except Exception as e:
            return {"success": False, "message": f"Muster-Abfrage fehlgeschlagen: {e}"}

    async def _exec_describe_doorbell(self, args: dict) -> dict:
        """Beschreibt was die Tuerkamera zeigt."""
        import assistant.main as main_module
        brain = main_module.brain
        try:
            description = await brain.camera_manager.describe_doorbell()
            if description:
                return {"success": True, "message": description}
            return {
                "success": False,
                "message": "Tuerkamera nicht verfuegbar oder kein Bild erhalten.",
            }
        except Exception as e:
            return {"success": False, "message": f"Tuerkamera-Abfrage fehlgeschlagen: {e}"}

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
                    return {"success": False, "message": "Name und Beschreibung werden fuer 'create' benoetigt."}
                return await engine.create_protocol(name, description, person=person)
            elif action == "execute":
                if not name:
                    return {"success": False, "message": "Name wird fuer 'execute' benoetigt."}
                return await engine.execute_protocol(name, person=person)
            elif action == "undo":
                if not name:
                    return {"success": False, "message": "Name wird fuer 'undo' benoetigt."}
                return await engine.undo_protocol(name)
            elif action == "list":
                protocols = await engine.list_protocols()
                if not protocols:
                    return {"success": True, "message": "Noch keine Protokolle gespeichert."}
                lines = [f"{len(protocols)} Protokoll(e):"]
                for p in protocols:
                    lines.append(f"- {p['name']} ({p['steps']} Schritte)")
                return {"success": True, "message": "\n".join(lines), "protocols": protocols}
            elif action == "delete":
                if not name:
                    return {"success": False, "message": "Name wird fuer 'delete' benoetigt."}
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
        """Feature 12: Besucher-Management — Besucher verwalten und Tuer-Workflows."""
        import assistant.main as main_module
        brain = main_module.brain
        vm = brain.visitor_manager
        action = args.get("action", "status")

        try:
            if action == "add_known":
                pid = args.get("person_id", "")
                name = args.get("name", "")
                if not pid or not name:
                    return {"success": False, "message": "person_id und name sind erforderlich."}
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
                        return {"success": False, "message": trust_check.get("reason", "Keine Berechtigung fuer Auto-Unlock.")}
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
                # grant_entry entriegelt die Tuer — erfordert Owner-Trust (wie lock_door)
                person = getattr(brain, "_current_person", "") or ""
                trust_check = brain.autonomy.can_person_act(person, "lock_door")
                if not trust_check["allowed"]:
                    return {"success": False, "message": trust_check.get("reason", "Keine Berechtigung.")}
                door = args.get("door", "haustuer")
                return await vm.grant_entry(door=door)
            elif action == "history":
                limit = max(1, min(int(args.get("limit", 20)), 100))
                return await vm.get_visit_history(limit=limit)
            elif action == "status":
                return await vm.get_status()
            else:
                return {"success": False, "message": f"Unbekannte Besucher-Aktion: {action}"}
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
        for s in (states or []):
            eid = s.get("entity_id", "")
            if eid.startswith("remote."):
                return eid
        return None

    async def _exec_remote_control(self, args: dict) -> dict:
        """Fernbedienung steuern: Aktivitaet starten/stoppen, IR-Befehle senden."""
        cfg = yaml_config.get("remote", {})
        if not cfg.get("enabled", True):
            return {"success": False, "message": "Fernbedienung-Steuerung ist deaktiviert. Aktiviere sie im Fernbedienung-Tab."}

        action = args.get("action", "on")
        remote_hint = args.get("remote")
        entity_id = await self._find_remote_entity(remote_hint)

        if not entity_id:
            return {"success": False, "message": "Keine Fernbedienung gefunden. Bitte im Fernbedienung-Tab konfigurieren."}

        activity = args.get("activity")
        command = args.get("command")
        device = args.get("device")
        num_repeats = max(1, min(args.get("num_repeats", 1), 20))

        # Aktivitaeten-Aliase aus Config auflösen
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
            return {"success": success, "message": "Fernbedienung ausgeschaltet — alle Geraete aus."}

        elif action in ("on", "activity"):
            service_data = {"entity_id": entity_id}
            if activity:
                service_data["activity"] = activity
            success = await self.ha.call_service(
                "remote", "turn_on", service_data
            )
            msg = f"Aktivitaet '{activity}' gestartet." if activity else "Fernbedienung eingeschaltet."
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
            success = await self.ha.call_service(
                "remote", "send_command", service_data
            )
            repeat_hint = f" (x{num_repeats})" if num_repeats > 1 else ""
            device_hint = f" an {device}" if device else ""
            return {"success": success, "message": f"Befehl '{command}'{device_hint} gesendet{repeat_hint}."}

        return {"success": False, "message": f"Unbekannte Aktion: {action}"}

    async def _exec_get_remotes(self, args: dict) -> dict:
        """Listet alle Fernbedienungen mit Status und verfuegbaren Aktivitaeten."""
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
                if hint not in eid.lower() and hint not in s.get("attributes", {}).get("friendly_name", "").lower():
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

            results.append({
                "entity_id": eid,
                "name": name,
                "is_on": is_on,
                "current_activity": current_activity,
                "available_activities": available,
                "configured_aliases": aliases,
            })

        if not results:
            return {"success": True, "message": "Keine Fernbedienungen gefunden.", "remotes": []}

        return {"success": True, "remotes": results, "count": len(results)}
