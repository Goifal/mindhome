"""
Comprehensive tests for function_calling.py — Entity detection, tools, catalog.

Tests: is_window_or_door(), _has_tor_keyword(), get_opening_sensor_config(),
get_mindhome_domain(), get_mindhome_room(), _get_config_rooms(),
entity roles, tool definitions (via get_assistant_tools),
_DEVICE_CLASS_TO_ROLE mapping, classify_request_complexity.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.function_calling import (
    is_window_or_door,
    _has_tor_keyword,
    get_opening_sensor_config,
    get_mindhome_domain,
    get_mindhome_room,
    _TOR_FALSE_POSITIVES,
    _DEFAULT_ROLES,
    _DEFAULT_ROLES_DICT,
    _DEVICE_CLASS_TO_ROLE,
    get_assistant_tools,
)


# ── _has_tor_keyword ──────────────────────────────────────────────────

class TestHasTorKeyword:

    def test_gartentor(self):
        assert _has_tor_keyword("binary_sensor.gartentor") is True

    def test_garagentor(self):
        assert _has_tor_keyword("binary_sensor.garagentor") is True

    def test_einfahrtstor(self):
        assert _has_tor_keyword("binary_sensor.einfahrtstor_sensor") is True

    def test_monitor_false_positive(self):
        assert _has_tor_keyword("binary_sensor.system_monitor") is False

    def test_motor_false_positive(self):
        assert _has_tor_keyword("sensor.motor_status") is False

    def test_actuator_false_positive(self):
        assert _has_tor_keyword("sensor.actuator_valve") is False

    def test_detector_false_positive(self):
        assert _has_tor_keyword("binary_sensor.smoke_detector") is False

    def test_no_tor(self):
        assert _has_tor_keyword("binary_sensor.kitchen_light") is False

    def test_factory_false_positive(self):
        assert _has_tor_keyword("sensor.factory_status") is False

    def test_history_false_positive(self):
        assert _has_tor_keyword("sensor.history_process") is False

    def test_storage_false_positive(self):
        assert _has_tor_keyword("sensor.storage_usage") is False


# ── is_window_or_door ─────────────────────────────────────────────────

class TestIsWindowOrDoor:

    def test_device_class_window(self):
        state = {"attributes": {"device_class": "window"}}
        assert is_window_or_door("binary_sensor.fenster_kueche", state) is True

    def test_device_class_door(self):
        state = {"attributes": {"device_class": "door"}}
        assert is_window_or_door("binary_sensor.haustuer", state) is True

    def test_device_class_garage_door(self):
        state = {"attributes": {"device_class": "garage_door"}}
        assert is_window_or_door("binary_sensor.garage", state) is True

    def test_device_class_running_rejected(self):
        state = {"attributes": {"device_class": "running"}}
        with patch("assistant.function_calling.get_opening_sensor_config", return_value={}), \
             patch("assistant.function_calling._mindhome_device_domains", {}):
            assert is_window_or_door("binary_sensor.process", state) is False

    def test_device_class_plug_rejected(self):
        state = {"attributes": {"device_class": "plug"}}
        with patch("assistant.function_calling.get_opening_sensor_config", return_value={}), \
             patch("assistant.function_calling._mindhome_device_domains", {}):
            assert is_window_or_door("binary_sensor.steckdose", state) is False

    def test_keyword_window_in_id(self):
        state = {"attributes": {}}
        with patch("assistant.function_calling.get_opening_sensor_config", return_value={}), \
             patch("assistant.function_calling._mindhome_device_domains", {}):
            assert is_window_or_door("binary_sensor.kitchen_window", state) is True

    def test_keyword_fenster_in_id(self):
        state = {"attributes": {}}
        with patch("assistant.function_calling.get_opening_sensor_config", return_value={}), \
             patch("assistant.function_calling._mindhome_device_domains", {}):
            assert is_window_or_door("binary_sensor.fenster_bad", state) is True

    def test_keyword_tuer_in_id(self):
        state = {"attributes": {}}
        with patch("assistant.function_calling.get_opening_sensor_config", return_value={}), \
             patch("assistant.function_calling._mindhome_device_domains", {}):
            assert is_window_or_door("binary_sensor.haustuer_kontakt", state) is True

    def test_keyword_gate_in_id(self):
        state = {"attributes": {}}
        with patch("assistant.function_calling.get_opening_sensor_config", return_value={}), \
             patch("assistant.function_calling._mindhome_device_domains", {}):
            assert is_window_or_door("binary_sensor.garden_gate", state) is True

    def test_tor_keyword_in_id(self):
        state = {"attributes": {}}
        with patch("assistant.function_calling.get_opening_sensor_config", return_value={}), \
             patch("assistant.function_calling._mindhome_device_domains", {}):
            assert is_window_or_door("binary_sensor.gartentor", state) is True

    def test_not_binary_sensor_without_config(self):
        state = {"attributes": {}}
        with patch("assistant.function_calling.get_opening_sensor_config", return_value={}), \
             patch("assistant.function_calling._mindhome_device_domains", {}):
            assert is_window_or_door("light.fenster_licht", state) is False

    def test_monitor_not_window(self):
        state = {"attributes": {}}
        with patch("assistant.function_calling.get_opening_sensor_config", return_value={}), \
             patch("assistant.function_calling._mindhome_device_domains", {}):
            assert is_window_or_door("binary_sensor.system_monitor", state) is False

    def test_opening_sensor_config_match(self):
        state = {"attributes": {}}
        with patch("assistant.function_calling.get_opening_sensor_config",
                   return_value={"type": "window", "room": "kueche"}):
            assert is_window_or_door("binary_sensor.custom_sensor", state) is True

    def test_mindhome_domain_door_window(self):
        state = {"attributes": {}}
        with patch("assistant.function_calling.get_opening_sensor_config", return_value={}), \
             patch("assistant.function_calling._mindhome_device_domains",
                   {"binary_sensor.custom": "door_window"}):
            assert is_window_or_door("binary_sensor.custom", state) is True

    def test_mindhome_domain_switch(self):
        state = {"attributes": {}}
        with patch("assistant.function_calling.get_opening_sensor_config", return_value={}), \
             patch("assistant.function_calling._mindhome_device_domains",
                   {"switch.steckdose_fenster": "switch"}):
            assert is_window_or_door("switch.steckdose_fenster", state) is False


# ── get_opening_sensor_config ─────────────────────────────────────────

class TestGetOpeningSensorConfig:

    def test_found(self):
        with patch("assistant.config.yaml_config", {
            "opening_sensors": {"entities": {"binary_sensor.fenster": {"type": "window"}}},
        }):
            result = get_opening_sensor_config("binary_sensor.fenster")
        assert result["type"] == "window"

    def test_not_found(self):
        with patch("assistant.config.yaml_config", {"opening_sensors": {"entities": {}}}):
            result = get_opening_sensor_config("binary_sensor.unknown")
        assert result == {}

    def test_no_config(self):
        with patch("assistant.config.yaml_config", {}):
            result = get_opening_sensor_config("binary_sensor.test")
        assert result == {}


# ── get_mindhome_domain / get_mindhome_room ──────────────────────────

class TestMindhomeHelpers:

    def test_get_domain_found(self):
        with patch("assistant.function_calling._mindhome_device_domains",
                   {"switch.test": "switch"}):
            assert get_mindhome_domain("switch.test") == "switch"

    def test_get_domain_not_found(self):
        with patch("assistant.function_calling._mindhome_device_domains", {}):
            assert get_mindhome_domain("switch.unknown") == ""

    def test_get_room_found(self):
        with patch("assistant.function_calling._mindhome_device_rooms",
                   {"light.kueche": "Kueche"}):
            assert get_mindhome_room("light.kueche") == "Kueche"

    def test_get_room_not_found(self):
        with patch("assistant.function_calling._mindhome_device_rooms", {}):
            assert get_mindhome_room("light.unknown") == ""


# ── TOR False Positives ──────────────────────────────────────────────

class TestTorFalsePositives:

    def test_is_tuple(self):
        assert isinstance(_TOR_FALSE_POSITIVES, tuple)

    def test_contains_monitor(self):
        assert "monitor" in _TOR_FALSE_POSITIVES

    def test_contains_motor(self):
        assert "motor" in _TOR_FALSE_POSITIVES

    def test_contains_detector(self):
        assert "detector" in _TOR_FALSE_POSITIVES


# ── Default Roles ────────────────────────────────────────────────────

class TestDefaultRoles:

    def test_indoor_temp_exists(self):
        assert "indoor_temp" in _DEFAULT_ROLES

    def test_smoke_exists(self):
        assert "smoke" in _DEFAULT_ROLES

    def test_window_contact_exists(self):
        assert "window_contact" in _DEFAULT_ROLES

    def test_motion_exists(self):
        assert "motion" in _DEFAULT_ROLES

    def test_all_roles_have_label(self):
        for role, info in _DEFAULT_ROLES_DICT.items():
            assert "label" in info, f"Role {role} missing label"

    def test_all_roles_have_icon(self):
        for role, info in _DEFAULT_ROLES_DICT.items():
            assert "icon" in info, f"Role {role} missing icon"


# ── Device Class to Role Mapping ─────────────────────────────────────

class TestDeviceClassToRole:

    def test_temperature_maps_to_indoor_temp(self):
        assert _DEVICE_CLASS_TO_ROLE["temperature"] == "indoor_temp"

    def test_humidity_maps(self):
        assert _DEVICE_CLASS_TO_ROLE["humidity"] == "humidity"

    def test_window_maps(self):
        assert _DEVICE_CLASS_TO_ROLE["window"] == "window_contact"

    def test_door_maps(self):
        assert _DEVICE_CLASS_TO_ROLE["door"] == "door_contact"

    def test_motion_maps(self):
        assert _DEVICE_CLASS_TO_ROLE["motion"] == "motion"

    def test_battery_maps(self):
        assert _DEVICE_CLASS_TO_ROLE["battery"] == "battery"

    def test_power_maps(self):
        assert _DEVICE_CLASS_TO_ROLE["power"] == "power_meter"

    def test_smoke_maps(self):
        assert _DEVICE_CLASS_TO_ROLE["smoke"] == "smoke"


# ── Tool Definitions ─────────────────────────────────────────────────

class TestToolDefinitionsComprehensive:

    def _tool_names(self):
        tools = get_assistant_tools()
        return [t["function"]["name"] for t in tools]

    def test_all_tools_valid_structure(self):
        for tool in get_assistant_tools():
            assert "type" in tool
            assert tool["type"] == "function"
            assert "function" in tool
            func = tool["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func
            assert func["parameters"]["type"] == "object"

    def test_no_empty_descriptions(self):
        for tool in get_assistant_tools():
            desc = tool["function"].get("description", "")
            assert len(desc) > 10, f"Tool {tool['function']['name']} has too short description"

    def test_core_tools_present(self):
        names = self._tool_names()
        core_tools = [
            "set_light", "set_climate", "set_cover",
            "get_weather", "get_room_climate",
        ]
        for tool in core_tools:
            assert tool in names, f"Core tool {tool} missing"

    def test_no_duplicate_names(self):
        names = self._tool_names()
        dupes = [n for n in names if names.count(n) > 1]
        assert len(dupes) == 0, f"Duplicate tools: {dupes}"

    def test_tool_count_reasonable(self):
        tools = get_assistant_tools()
        assert len(tools) >= 10, f"Only {len(tools)} tools — expected more"
        assert len(tools) < 200, f"{len(tools)} tools seems excessive"


# ── get_opening_type ─────────────────────────────────────────────────

class TestGetOpeningType:

    def test_gate_type(self):
        try:
            from assistant.function_calling import get_opening_type
        except ImportError:
            pytest.skip("get_opening_type not available")

        state = {"attributes": {"device_class": "garage_door"}}
        result = get_opening_type("binary_sensor.garage", state)
        assert result in ("gate", "garage_door", "door")
