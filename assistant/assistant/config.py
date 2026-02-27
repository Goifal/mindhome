"""
Zentrale Konfiguration - liest .env und settings.yaml
"""

import logging
import os
import time
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Umgebungsvariablen aus .env"""

    # Home Assistant
    ha_url: str = "http://192.168.1.100:8123"
    ha_token: str = ""

    # MindHome
    mindhome_url: str = "http://192.168.1.100:8099"

    # Ollama
    ollama_url: str = "http://localhost:11434"
    model_fast: str = "qwen3:4b"
    model_notify: str = "qwen3:8b"
    model_smart: str = "qwen3:14b"
    model_deep: str = "qwen3:32b"

    # MindHome Assistant Server
    assistant_host: str = "0.0.0.0"
    assistant_port: int = 8200

    # API Key fuer /api/assistant/* Endpoints (auto-generiert wenn leer)
    assistant_api_key: str = ""

    # Redis + ChromaDB
    redis_url: str = "redis://localhost:6379"
    chroma_url: str = "http://localhost:8100"

    # User
    user_name: str = "Max"
    autonomy_level: int = 2
    language: str = "de"

    # Assistent-Identitaet
    assistant_name: str = "Jarvis"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


def load_yaml_config() -> dict:
    """Laedt settings.yaml — erzeugt sie aus .example wenn sie fehlt."""
    config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
    example_path = config_path.with_suffix(".yaml.example")

    if not config_path.exists() and example_path.exists():
        import shutil
        shutil.copy2(example_path, config_path)

    if config_path.exists():
        try:
            with open(config_path) as f:
                data = yaml.safe_load(f)
                if not isinstance(data, dict):
                    return {}
                return data
        except yaml.YAMLError:
            return {}
    return {}


# Globale Instanzen
settings = Settings()
yaml_config = load_yaml_config()

# settings.yaml ueberschreibt .env fuer bestimmte Werte
_yaml_name = yaml_config.get("assistant", {}).get("name")
if _yaml_name:
    settings.assistant_name = _yaml_name

# Modelle aus settings.yaml uebernehmen (wenn gesetzt)
_models = yaml_config.get("models", {})
if _models.get("fast"):
    settings.model_fast = _models["fast"]
if _models.get("notify"):
    settings.model_notify = _models["notify"]
if _models.get("smart"):
    settings.model_smart = _models["smart"]
if _models.get("deep"):
    settings.model_deep = _models["deep"]

# Household → user_name, persons, trust_levels synchronisieren
_household = yaml_config.get("household") or {}
if _household.get("primary_user"):
    settings.user_name = _household["primary_user"]

_ROLE_TO_TRUST = {"owner": 2, "member": 1, "guest": 0}


def apply_household_to_config() -> None:
    """Generiert persons.titles, trust_levels.persons und entity_to_name aus household.members."""
    global _entity_to_name
    household = yaml_config.get("household") or {}
    members = household.get("members") or []
    primary = household.get("primary_user") or settings.user_name

    # persons.titles: Existierende Titel als Basis, Members ergaenzen
    existing_titles = (yaml_config.get("persons") or {}).get("titles") or {}
    titles = dict(existing_titles)
    trust_persons = {}
    entity_map: dict[str, str] = {}

    # Hauptbenutzer immer als Owner
    trust_persons[primary.lower()] = 2

    # Primary User Entity-Mapping
    primary_entity = (household.get("primary_user_entity") or "").strip()
    if primary_entity and primary:
        entity_map[primary_entity.lower()] = primary

    for m in members:
        name = (m.get("name") or "").strip()
        if not name:
            continue
        role = m.get("role", "member")

        # Inline-Titel hat Vorrang vor auto-generiertem Name-Titel
        member_title = (m.get("title") or "").strip()
        if member_title:
            titles[name.lower()] = member_title
        elif name.lower() not in titles:
            titles[name.lower()] = name

        trust_persons[name.lower()] = _ROLE_TO_TRUST.get(role, 0)

        # Entity-Mapping: person.anna → Anna
        ha_entity = (m.get("ha_entity") or "").strip()
        if ha_entity:
            entity_map[ha_entity.lower()] = name

    # In yaml_config eintragen (fuer personality.py etc.)
    yaml_config.setdefault("persons", {})["titles"] = titles
    yaml_config.setdefault("trust_levels", {})["persons"] = trust_persons
    if "trust_levels" in yaml_config and "default" not in yaml_config["trust_levels"]:
        yaml_config["trust_levels"]["default"] = 0

    # Entity-to-Name Mapping fuer proactive.py / context_builder.py
    _entity_to_name = entity_map

    # user_name aktualisieren
    if primary:
        settings.user_name = primary


apply_household_to_config()


# Entity-to-Name Mapping: Wird von apply_household_to_config() befuellt.
# Erlaubt proactive.py und context_builder.py Personen per entity_id statt
# per friendly_name zu identifizieren (zuverlaessiger).
_entity_to_name: dict[str, str] = {}


def resolve_person_by_entity(entity_id: str) -> str:
    """Gibt den konfigurierten Member-Namen fuer eine HA entity_id zurueck.

    Beispiel: resolve_person_by_entity("person.anna") → "Anna"
    Fallback: leerer String (dann wird friendly_name verwendet).
    """
    return _entity_to_name.get(entity_id.lower(), "")


# Active-Person Tracking: Wird von brain.py gesetzt wenn eine Person
# identifiziert wird (Sprache, Praesenz, Speaker-Recognition).
# Damit kann get_person_title() ohne Argument den richtigen Titel liefern.
_active_person: str = ""


def set_active_person(name: str) -> None:
    """Setzt die aktuell aktive Person (vom brain/proactive Modul)."""
    global _active_person
    _active_person = name or ""


def get_active_person() -> str:
    """Gibt die aktuell aktive Person zurueck."""
    return _active_person


def _lookup_title(titles: dict, name: str) -> str:
    """Sucht einen Titel mit Fallback auf Vornamen-Match.

    Versucht zuerst den exakten Namen (lowercase), dann nur den Vornamen.
    So passt 'Anna Mueller' (HA friendly_name) auf Config-Key 'anna'.
    """
    if not name:
        return ""
    key = name.lower().strip()
    # Exakter Match
    title = titles.get(key)
    if title:
        return title
    # Vornamen-Match (HA liefert manchmal 'Max Mueller', Config hat nur 'max')
    if " " in key:
        first = key.split()[0]
        title = titles.get(first)
        if title:
            return title
    return ""


def get_person_title(name: str = "") -> str:
    """Gibt den konfigurierten Titel fuer eine Person zurueck.

    Reihenfolge:
    1. Explizit uebergebener Name → dessen Titel
    2. Aktive Person (von brain.py gesetzt) → deren Titel
    3. Fallback: primary_user Titel
    4. Fallback: 'Sir'

    Name-Matching ist robust: 'Anna Mueller' findet auch Config-Key 'anna'.
    """
    titles = (yaml_config.get("persons") or {}).get("titles") or {}
    if name:
        title = _lookup_title(titles, name)
        if title:
            return title
    # Aktive Person (gesetzt durch brain.py bei Gespraech oder proactive bei Praesenz)
    if not name and _active_person:
        title = _lookup_title(titles, _active_person)
        if title:
            return title
    # Fallback: primary user Titel
    primary = (yaml_config.get("household") or {}).get("primary_user", "")
    if primary:
        title = _lookup_title(titles, primary)
        if title:
            return title
    return "Sir"


# ── Room-Profile-Cache (zentral, von function_calling.py + proactive.py genutzt) ──
_room_profiles_cache: dict = {}
_room_profiles_ts: float = 0.0
_ROOM_PROFILES_TTL = 120  # 2 Min (Kompromiss zwischen Aktualitaet und I/O)
_ROOM_PROFILES_PATH = Path(__file__).parent.parent / "config" / "room_profiles.yaml"


def get_room_profiles() -> dict:
    """Liefert room_profiles.yaml aus Cache (oder laedt bei Bedarf von Disk)."""
    global _room_profiles_cache, _room_profiles_ts
    now = time.time()
    if _room_profiles_cache and (now - _room_profiles_ts) < _ROOM_PROFILES_TTL:
        return _room_profiles_cache
    try:
        if _ROOM_PROFILES_PATH.exists():
            with open(_ROOM_PROFILES_PATH) as f:
                _room_profiles_cache = yaml.safe_load(f) or {}
        else:
            _room_profiles_cache = {}
    except Exception as e:
        logger.debug("Room-Profiles nicht ladbar: %s", e)
        if not _room_profiles_cache:
            _room_profiles_cache = {}
    _room_profiles_ts = now
    return _room_profiles_cache
