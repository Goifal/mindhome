"""
Lokale Cover-Konfiguration (JSON-basiert).

Speichert Cover-Typ (shutter, garage_door, etc.) und enabled-Status
direkt auf dem Assistant, ohne Umweg ueber das Addon.

Zusaetzlich: Gruppen, Szenen, Zeitplaene, Sensor-Zuordnungen
und Cover-Automation-Log (letzte Aktionen) — alles lokal.
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("mindhome-assistant")

_DATA_DIR = Path("/app/data")
_COVER_CONFIG_FILE = _DATA_DIR / "cover_configs.json"
_COVER_GROUPS_FILE = _DATA_DIR / "cover_groups.json"
_COVER_SCENES_FILE = _DATA_DIR / "cover_scenes.json"
_COVER_SCHEDULES_FILE = _DATA_DIR / "cover_schedules.json"
_COVER_SENSORS_FILE = _DATA_DIR / "cover_sensors.json"
_COVER_LOG_FILE = _DATA_DIR / "cover_action_log.json"


def _ensure_dir():
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


# ── Cover-Configs (per-entity Typ/enabled) ────────────────────────

def load_cover_configs() -> dict:
    """Cover-Configs aus lokaler JSON-Datei laden."""
    try:
        if _COVER_CONFIG_FILE.exists():
            return json.loads(_COVER_CONFIG_FILE.read_text())
    except Exception as e:
        logger.warning("Cover-Config laden fehlgeschlagen: %s", e)
    return {}


def save_cover_configs(configs: dict) -> None:
    """Cover-Configs in lokale JSON-Datei speichern."""
    try:
        _ensure_dir()
        _COVER_CONFIG_FILE.write_text(json.dumps(configs, indent=2, ensure_ascii=False))
    except Exception as e:
        logger.error("Cover-Config speichern fehlgeschlagen: %s", e)
        raise


# ── Generische Liste-mit-IDs Helfer ──────────────────────────────

def _load_list(filepath: Path) -> list:
    try:
        if filepath.exists():
            data = json.loads(filepath.read_text())
            if isinstance(data, list):
                return data
    except Exception as e:
        logger.warning("Laden von %s fehlgeschlagen: %s", filepath.name, e)
    return []


def _save_list(filepath: Path, items: list) -> None:
    _ensure_dir()
    filepath.write_text(json.dumps(items, indent=2, ensure_ascii=False))


def _next_id(items: list) -> int:
    if not items:
        return 1
    return max(item.get("id", 0) for item in items) + 1


def _find_by_id(items: list, item_id: int) -> Optional[dict]:
    for item in items:
        if item.get("id") == item_id:
            return item
    return None


# ── Cover-Gruppen ────────────────────────────────────────────────

def load_cover_groups() -> list:
    return _load_list(_COVER_GROUPS_FILE)


def save_cover_groups(groups: list) -> None:
    _save_list(_COVER_GROUPS_FILE, groups)


def create_cover_group(data: dict) -> dict:
    groups = load_cover_groups()
    new_group = {
        "id": _next_id(groups),
        "name": data.get("name", "Neue Gruppe"),
        "entity_ids": data.get("entity_ids", []),
    }
    groups.append(new_group)
    save_cover_groups(groups)
    return new_group


def update_cover_group(group_id: int, data: dict) -> Optional[dict]:
    groups = load_cover_groups()
    group = _find_by_id(groups, group_id)
    if not group:
        return None
    if "name" in data:
        group["name"] = data["name"]
    if "entity_ids" in data:
        group["entity_ids"] = data["entity_ids"]
    save_cover_groups(groups)
    return group


def delete_cover_group(group_id: int) -> bool:
    groups = load_cover_groups()
    new_groups = [g for g in groups if g.get("id") != group_id]
    if len(new_groups) == len(groups):
        return False
    save_cover_groups(new_groups)
    return True


# ── Cover-Szenen ─────────────────────────────────────────────────

def load_cover_scenes() -> list:
    return _load_list(_COVER_SCENES_FILE)


def save_cover_scenes(scenes: list) -> None:
    _save_list(_COVER_SCENES_FILE, scenes)


def create_cover_scene(data: dict) -> dict:
    scenes = load_cover_scenes()
    new_scene = {
        "id": _next_id(scenes),
        "name": data.get("name", "Neue Szene"),
        "positions": data.get("positions", {}),
    }
    scenes.append(new_scene)
    save_cover_scenes(scenes)
    return new_scene


def update_cover_scene(scene_id: int, data: dict) -> Optional[dict]:
    scenes = load_cover_scenes()
    scene = _find_by_id(scenes, scene_id)
    if not scene:
        return None
    if "name" in data:
        scene["name"] = data["name"]
    if "positions" in data:
        scene["positions"] = data["positions"]
    save_cover_scenes(scenes)
    return scene


def delete_cover_scene(scene_id: int) -> bool:
    scenes = load_cover_scenes()
    new_scenes = [s for s in scenes if s.get("id") != scene_id]
    if len(new_scenes) == len(scenes):
        return False
    save_cover_scenes(new_scenes)
    return True


# ── Cover-Zeitplaene ─────────────────────────────────────────────

def load_cover_schedules() -> list:
    return _load_list(_COVER_SCHEDULES_FILE)


def save_cover_schedules(schedules: list) -> None:
    _save_list(_COVER_SCHEDULES_FILE, schedules)


def create_cover_schedule(data: dict) -> dict:
    schedules = load_cover_schedules()
    new_schedule = {
        "id": _next_id(schedules),
        "time_str": data.get("time_str", "08:00"),
        "position": data.get("position", 100),
        "entity_id": data.get("entity_id"),
        "group_id": data.get("group_id"),
        "days": data.get("days", [0, 1, 2, 3, 4, 5, 6]),
        "is_active": data.get("is_active", True),
    }
    schedules.append(new_schedule)
    save_cover_schedules(schedules)
    return new_schedule


def update_cover_schedule(schedule_id: int, data: dict) -> Optional[dict]:
    schedules = load_cover_schedules()
    schedule = _find_by_id(schedules, schedule_id)
    if not schedule:
        return None
    for key in ("time_str", "position", "entity_id", "group_id", "days", "is_active"):
        if key in data:
            schedule[key] = data[key]
    save_cover_schedules(schedules)
    return schedule


def delete_cover_schedule(schedule_id: int) -> bool:
    schedules = load_cover_schedules()
    new_schedules = [s for s in schedules if s.get("id") != schedule_id]
    if len(new_schedules) == len(schedules):
        return False
    save_cover_schedules(new_schedules)
    return True


# ── Cover-Sensor-Zuordnungen ────────────────────────────────────

def load_cover_sensors() -> list:
    return _load_list(_COVER_SENSORS_FILE)


def save_cover_sensors(sensors: list) -> None:
    _save_list(_COVER_SENSORS_FILE, sensors)


def create_cover_sensor(data: dict) -> dict:
    sensors = load_cover_sensors()
    new_sensor = {
        "id": _next_id(sensors),
        "entity_id": data.get("entity_id", ""),
        "role": data.get("role", ""),
    }
    sensors.append(new_sensor)
    save_cover_sensors(sensors)
    return new_sensor


def delete_cover_sensor(sensor_id: int) -> bool:
    sensors = load_cover_sensors()
    new_sensors = [s for s in sensors if s.get("id") != sensor_id]
    if len(new_sensors) == len(sensors):
        return False
    save_cover_sensors(new_sensors)
    return True


def get_sensor_by_role(role: str) -> Optional[str]:
    """Gibt die entity_id des ersten Sensors mit der angegebenen Rolle zurueck."""
    for s in load_cover_sensors():
        if s.get("role") == role:
            return s.get("entity_id")
    return None


def get_sensors_by_role(role: str) -> list:
    """Gibt alle entity_ids mit der angegebenen Rolle zurueck."""
    return [s.get("entity_id") for s in load_cover_sensors() if s.get("role") == role]


# ── Cover-Aktions-Log (fuer Dashboard) ──────────────────────────

_MAX_LOG_ENTRIES = 50


def log_cover_action(entity_id: str, position: int, reason: str) -> None:
    """Loggt eine automatische Cover-Aktion fuer das Dashboard."""
    try:
        entries = _load_list(_COVER_LOG_FILE)
        entries.insert(0, {
            "ts": time.time(),
            "entity_id": entity_id,
            "position": position,
            "reason": reason,
        })
        # Max Eintraege begrenzen
        if len(entries) > _MAX_LOG_ENTRIES:
            entries = entries[:_MAX_LOG_ENTRIES]
        _save_list(_COVER_LOG_FILE, entries)
    except Exception as e:
        logger.warning("Cover-Log schreiben fehlgeschlagen: %s", e)


def load_cover_action_log(limit: int = 10) -> list:
    """Laedt die letzten Cover-Aktionen fuer das Dashboard."""
    entries = _load_list(_COVER_LOG_FILE)
    return entries[:limit]
