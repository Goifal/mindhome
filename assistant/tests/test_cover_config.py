"""
Tests fuer cover_config — JSON-basierte Cover-Konfiguration und CRUD-Operationen.
"""

import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from assistant.cover_config import (
    _next_id,
    _find_by_id,
    load_cover_configs,
    save_cover_configs,
    load_cover_groups,
    save_cover_groups,
    create_cover_group,
    update_cover_group,
    delete_cover_group,
    load_cover_scenes,
    save_cover_scenes,
    create_cover_scene,
    update_cover_scene,
    delete_cover_scene,
    load_cover_schedules,
    save_cover_schedules,
    create_cover_schedule,
    update_cover_schedule,
    delete_cover_schedule,
    load_cover_sensors,
    save_cover_sensors,
    create_cover_sensor,
    delete_cover_sensor,
    get_sensor_by_role,
    get_sensors_by_role,
    log_cover_action,
    load_cover_action_log,
    load_power_close_rules,
    save_power_close_rules,
    create_power_close_rule,
    update_power_close_rule,
    delete_power_close_rule,
)


# =====================================================================
# Fixture: Redirect _DATA_DIR to tmp_path
# =====================================================================


@pytest.fixture(autouse=True)
def tmp_data_dir(tmp_path):
    """Redirect all file paths to a temporary directory."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with (
        patch("assistant.cover_config._DATA_DIR", data_dir),
        patch(
            "assistant.cover_config._COVER_CONFIG_FILE", data_dir / "cover_configs.json"
        ),
        patch(
            "assistant.cover_config._COVER_GROUPS_FILE", data_dir / "cover_groups.json"
        ),
        patch(
            "assistant.cover_config._COVER_SCENES_FILE", data_dir / "cover_scenes.json"
        ),
        patch(
            "assistant.cover_config._COVER_SCHEDULES_FILE",
            data_dir / "cover_schedules.json",
        ),
        patch(
            "assistant.cover_config._COVER_SENSORS_FILE",
            data_dir / "cover_sensors.json",
        ),
        patch(
            "assistant.cover_config._COVER_LOG_FILE", data_dir / "cover_action_log.json"
        ),
        patch(
            "assistant.cover_config._POWER_CLOSE_FILE",
            data_dir / "cover_power_close.json",
        ),
    ):
        yield data_dir


# =====================================================================
# _next_id / _find_by_id
# =====================================================================


class TestHelpers:
    """Tests fuer _next_id und _find_by_id."""

    def test_next_id_empty_list(self):
        assert _next_id([]) == 1

    def test_next_id_single_item(self):
        assert _next_id([{"id": 1}]) == 2

    def test_next_id_multiple_items(self):
        items = [{"id": 1}, {"id": 5}, {"id": 3}]
        assert _next_id(items) == 6

    def test_next_id_no_int_ids(self):
        items = [{"id": "abc"}, {"name": "test"}]
        assert _next_id(items) == 1

    def test_find_by_id_found(self):
        items = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
        result = _find_by_id(items, 2)
        assert result == {"id": 2, "name": "b"}

    def test_find_by_id_not_found(self):
        items = [{"id": 1, "name": "a"}]
        assert _find_by_id(items, 99) is None

    def test_find_by_id_empty_list(self):
        assert _find_by_id([], 1) is None


# =====================================================================
# Cover Configs (dict-based)
# =====================================================================


class TestCoverConfigs:
    """Tests fuer load/save cover_configs (dict-basiert)."""

    def test_load_configs_no_file(self):
        result = load_cover_configs()
        assert result == {}

    def test_save_and_load_configs(self):
        configs = {"cover.wohnzimmer": {"type": "shutter", "enabled": True}}
        save_cover_configs(configs)
        loaded = load_cover_configs()
        assert loaded == configs

    def test_load_configs_invalid_json(self, tmp_data_dir):
        (tmp_data_dir / "cover_configs.json").write_text("not valid json")
        result = load_cover_configs()
        assert result == {}

    def test_load_configs_non_dict(self, tmp_data_dir):
        (tmp_data_dir / "cover_configs.json").write_text(json.dumps([1, 2, 3]))
        result = load_cover_configs()
        assert result == {}


# =====================================================================
# Cover Groups CRUD
# =====================================================================


class TestCoverGroups:
    """Tests fuer Cover-Gruppen CRUD."""

    def test_load_groups_empty(self):
        assert load_cover_groups() == []

    def test_create_group(self):
        group = create_cover_group({"name": "Wohnzimmer", "entity_ids": ["cover.wz1"]})
        assert group["id"] == 1
        assert group["name"] == "Wohnzimmer"
        assert group["entity_ids"] == ["cover.wz1"]

    def test_create_group_defaults(self):
        group = create_cover_group({})
        assert group["name"] == "Neue Gruppe"
        assert group["entity_ids"] == []

    def test_create_multiple_groups_increments_id(self):
        g1 = create_cover_group({"name": "G1"})
        g2 = create_cover_group({"name": "G2"})
        assert g1["id"] == 1
        assert g2["id"] == 2

    def test_update_group(self):
        create_cover_group({"name": "Alt"})
        result = update_cover_group(1, {"name": "Neu"})
        assert result is not None
        assert result["name"] == "Neu"

    def test_update_group_not_found(self):
        assert update_cover_group(99, {"name": "X"}) is None

    def test_delete_group(self):
        create_cover_group({"name": "Loeschen"})
        assert delete_cover_group(1) is True
        assert load_cover_groups() == []

    def test_delete_group_not_found(self):
        assert delete_cover_group(99) is False


# =====================================================================
# Cover Scenes CRUD
# =====================================================================


class TestCoverScenes:
    """Tests fuer Cover-Szenen CRUD."""

    def test_create_scene(self):
        scene = create_cover_scene(
            {
                "name": "Kino",
                "positions": {"cover.wz": 0, "cover.sz": 50},
            }
        )
        assert scene["id"] == 1
        assert scene["name"] == "Kino"
        assert scene["positions"]["cover.wz"] == 0

    def test_update_scene(self):
        create_cover_scene({"name": "Tag"})
        result = update_cover_scene(
            1, {"name": "Nacht", "positions": {"cover.wz": 100}}
        )
        assert result["name"] == "Nacht"
        assert result["positions"] == {"cover.wz": 100}

    def test_update_scene_not_found(self):
        assert update_cover_scene(99, {"name": "X"}) is None

    def test_delete_scene(self):
        create_cover_scene({"name": "Temp"})
        assert delete_cover_scene(1) is True
        assert load_cover_scenes() == []

    def test_delete_scene_not_found(self):
        assert delete_cover_scene(99) is False


# =====================================================================
# Cover Schedules CRUD
# =====================================================================


class TestCoverSchedules:
    """Tests fuer Cover-Zeitplaene CRUD."""

    def test_create_schedule_defaults(self):
        sched = create_cover_schedule({})
        assert sched["time_str"] == "08:00"
        assert sched["position"] == 100
        assert sched["days"] == [0, 1, 2, 3, 4, 5, 6]
        assert sched["is_active"] is True

    def test_create_schedule_clamps_position_high(self):
        sched = create_cover_schedule({"position": 200})
        assert sched["position"] == 100

    def test_create_schedule_clamps_position_low(self):
        sched = create_cover_schedule({"position": -10})
        assert sched["position"] == 0

    @pytest.mark.parametrize(
        "pos,expected",
        [
            (0, 0),
            (50, 50),
            (100, 100),
        ],
    )
    def test_create_schedule_valid_positions(self, pos, expected):
        sched = create_cover_schedule({"position": pos})
        assert sched["position"] == expected

    def test_update_schedule(self):
        create_cover_schedule({"time_str": "07:00"})
        result = update_cover_schedule(1, {"time_str": "22:00", "is_active": False})
        assert result["time_str"] == "22:00"
        assert result["is_active"] is False

    def test_update_schedule_not_found(self):
        assert update_cover_schedule(99, {"time_str": "12:00"}) is None

    def test_delete_schedule(self):
        create_cover_schedule({})
        assert delete_cover_schedule(1) is True
        assert load_cover_schedules() == []

    def test_delete_schedule_not_found(self):
        assert delete_cover_schedule(99) is False


# =====================================================================
# Cover Sensors
# =====================================================================


class TestCoverSensors:
    """Tests fuer Cover-Sensor-Zuordnungen."""

    def test_create_sensor(self):
        sensor = create_cover_sensor({"entity_id": "sensor.lux", "role": "light"})
        assert sensor["id"] == 1
        assert sensor["entity_id"] == "sensor.lux"
        assert sensor["role"] == "light"

    def test_delete_sensor(self):
        create_cover_sensor({"entity_id": "sensor.lux", "role": "light"})
        assert delete_cover_sensor(1) is True
        assert load_cover_sensors() == []

    def test_delete_sensor_not_found(self):
        assert delete_cover_sensor(99) is False

    def test_get_sensor_by_role_found(self):
        create_cover_sensor({"entity_id": "sensor.temp", "role": "temperature"})
        create_cover_sensor({"entity_id": "sensor.lux", "role": "light"})
        assert get_sensor_by_role("light") == "sensor.lux"

    def test_get_sensor_by_role_not_found(self):
        create_cover_sensor({"entity_id": "sensor.temp", "role": "temperature"})
        assert get_sensor_by_role("wind") is None

    def test_get_sensors_by_role_multiple(self):
        create_cover_sensor({"entity_id": "sensor.lux1", "role": "light"})
        create_cover_sensor({"entity_id": "sensor.lux2", "role": "light"})
        create_cover_sensor({"entity_id": "sensor.temp", "role": "temperature"})
        result = get_sensors_by_role("light")
        assert result == ["sensor.lux1", "sensor.lux2"]

    def test_get_sensors_by_role_none(self):
        assert get_sensors_by_role("nonexistent") == []


# =====================================================================
# Cover Action Log
# =====================================================================


class TestCoverActionLog:
    """Tests fuer Cover-Aktions-Log."""

    def test_log_action_creates_entry(self):
        log_cover_action("cover.wz", 50, "sunset")
        entries = load_cover_action_log()
        assert len(entries) == 1
        assert entries[0]["entity_id"] == "cover.wz"
        assert entries[0]["position"] == 50
        assert entries[0]["reason"] == "sunset"
        assert "ts" in entries[0]

    def test_log_action_prepends(self):
        log_cover_action("cover.a", 0, "first")
        log_cover_action("cover.b", 100, "second")
        entries = load_cover_action_log(limit=10)
        assert entries[0]["entity_id"] == "cover.b"
        assert entries[1]["entity_id"] == "cover.a"

    def test_log_action_max_50_entries(self):
        for i in range(55):
            log_cover_action(f"cover.{i}", i, f"reason_{i}")
        entries = load_cover_action_log(limit=100)
        assert len(entries) == 50

    def test_load_log_with_limit(self):
        for i in range(5):
            log_cover_action(f"cover.{i}", i, f"r{i}")
        entries = load_cover_action_log(limit=2)
        assert len(entries) == 2

    def test_load_log_empty(self):
        assert load_cover_action_log() == []


# =====================================================================
# Power-Close Rules CRUD
# =====================================================================


class TestPowerCloseRules:
    """Tests fuer Power-Close-Regeln CRUD."""

    def test_create_rule(self):
        rule = create_power_close_rule(
            {
                "power_sensor": "sensor.tv_power",
                "threshold": 80,
                "cover_ids": ["cover.wz"],
                "close_position": 10,
            }
        )
        assert rule["id"] == 1
        assert rule["power_sensor"] == "sensor.tv_power"
        assert rule["threshold"] == 80
        assert rule["cover_ids"] == ["cover.wz"]
        assert rule["close_position"] == 10
        assert rule["is_active"] is True

    def test_create_rule_defaults(self):
        rule = create_power_close_rule({})
        assert rule["power_sensor"] == ""
        assert rule["threshold"] == 50
        assert rule["cover_ids"] == []
        assert rule["close_position"] == 0
        assert rule["is_active"] is True

    def test_update_rule(self):
        create_power_close_rule({"power_sensor": "sensor.tv"})
        result = update_power_close_rule(1, {"threshold": 100, "is_active": False})
        assert result["threshold"] == 100
        assert result["is_active"] is False

    def test_update_rule_not_found(self):
        assert update_power_close_rule(99, {"threshold": 10}) is None

    def test_delete_rule(self):
        create_power_close_rule({})
        assert delete_power_close_rule(1) is True
        assert load_power_close_rules() == []

    def test_delete_rule_not_found(self):
        assert delete_power_close_rule(99) is False


# =====================================================================
# Zusaetzliche Tests fuer 100% Coverage
# =====================================================================


class TestSaveCoverConfigsCoverage:
    """Zusaetzliche Tests fuer save_cover_configs — Zeilen 53, 55-57."""

    def test_save_creates_backup(self, tmp_data_dir):
        """Wenn Datei existiert, wird ein Backup erstellt (Zeile 53)."""
        cfg_file = tmp_data_dir / "cover_configs.json"
        cfg_file.write_text(json.dumps({"old": True}))
        save_cover_configs({"new": True})
        bak_file = cfg_file.with_suffix(".json.bak")
        assert bak_file.exists()
        assert json.loads(bak_file.read_text()) == {"old": True}
        assert json.loads(cfg_file.read_text()) == {"new": True}

    def test_save_configs_error_raises(self, tmp_data_dir):
        """save_cover_configs wirft Exception bei Schreibfehler (Zeilen 55-57)."""
        with patch("assistant.cover_config._ensure_dir"):
            with patch("assistant.cover_config._COVER_CONFIG_FILE") as mock_file:
                mock_file.exists.return_value = False
                mock_file.write_text.side_effect = PermissionError("read-only")
                with pytest.raises(PermissionError):
                    save_cover_configs({"test": True})


class TestLoadListCoverage:
    """Zusaetzliche Tests fuer _load_list — Zeilen 68-69."""

    def test_load_list_non_list_data(self, tmp_data_dir):
        """_load_list gibt leere Liste zurueck wenn JSON kein Array ist (Zeile 68 implizit)."""
        groups_file = tmp_data_dir / "cover_groups.json"
        groups_file.write_text(json.dumps({"not": "a list"}))
        result = load_cover_groups()
        assert result == []

    def test_load_list_invalid_json(self, tmp_data_dir):
        """_load_list faengt JSONDecodeError ab (Zeilen 68-69)."""
        groups_file = tmp_data_dir / "cover_groups.json"
        groups_file.write_text("not valid json {{{")
        result = load_cover_groups()
        assert result == []


class TestSaveListCoverage:
    """Zusaetzliche Tests fuer _save_list — Zeilen 79-81."""

    def test_save_list_creates_backup(self, tmp_data_dir):
        """_save_list erstellt Backup wenn Datei existiert (Zeile 79 implizit)."""
        groups_file = tmp_data_dir / "cover_groups.json"
        groups_file.write_text(json.dumps([{"id": 1, "name": "Alt"}]))
        save_cover_groups([{"id": 1, "name": "Neu"}])
        bak = groups_file.with_suffix(".json.bak")
        assert bak.exists()

    def test_save_list_error_raises(self, tmp_data_dir):
        """_save_list wirft Exception bei Schreibfehler (Zeilen 79-81)."""
        from assistant.cover_config import _save_list

        with patch("assistant.cover_config._ensure_dir"):
            mock_path = MagicMock()
            mock_path.exists.return_value = False
            mock_path.write_text.side_effect = PermissionError("fs error")
            mock_path.name = "test.json"
            with pytest.raises(PermissionError):
                _save_list(mock_path, [{"id": 1}])


class TestUpdateCoverGroupCoverage:
    """Zusaetzliche Tests fuer update_cover_group — Zeile 128."""

    def test_update_group_entity_ids(self):
        """Update nur entity_ids (Zeile 128)."""
        create_cover_group({"name": "G1", "entity_ids": ["cover.a"]})
        result = update_cover_group(1, {"entity_ids": ["cover.b", "cover.c"]})
        assert result is not None
        assert result["entity_ids"] == ["cover.b", "cover.c"]
        assert result["name"] == "G1"  # Name nicht geaendert


class TestUpdateCoverScheduleCoverage:
    """Zusaetzliche Tests fuer update_cover_schedule — Zeilen 218-220, 224."""

    def test_update_schedule_invalid_position_string(self):
        """Position mit ungueltigem Wert wirft ValueError (Zeilen 218-220)."""
        create_cover_schedule({"position": 50})
        with pytest.raises(ValueError, match="Position must be between 0 and 100"):
            update_cover_schedule(1, {"position": 150})

    def test_update_schedule_invalid_position_negative(self):
        """Negative Position wirft ValueError (Zeilen 218-220)."""
        create_cover_schedule({"position": 50})
        with pytest.raises(ValueError):
            update_cover_schedule(1, {"position": -10})

    def test_update_schedule_clamps_valid_position(self):
        """Position wird auf 0-100 geclampt (Zeile 224)."""
        create_cover_schedule({"position": 50})
        result = update_cover_schedule(1, {"position": 75})
        assert result["position"] == 75


class TestLogCoverActionCoverage:
    """Zusaetzliche Tests fuer log_cover_action — Zeilen 303-304."""

    def test_log_cover_action_save_error(self, tmp_data_dir):
        """log_cover_action faengt Fehler beim Speichern ab (Zeilen 303-304)."""
        from assistant.cover_config import _save_list

        with patch(
            "assistant.cover_config._save_list", side_effect=Exception("write error")
        ):
            # Sollte nicht werfen, sondern Fehler loggen
            log_cover_action("cover.test", 50, "test_reason")
            # Kein Assert noetig — der Test prueft dass keine Exception ausbricht
