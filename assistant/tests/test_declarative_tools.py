"""Tests for assistant.declarative_tools module."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

import pytest

from assistant.declarative_tools import (
    DEFAULT_MAX_TOOLS,
    TIME_RANGE_MAP,
    VALID_FORMULAS,
    VALID_OPERATIONS,
    VALID_TYPES,
    DeclarativeToolExecutor,
    DeclarativeToolRegistry,
    _get_max_tools,
    _slugify,
    generate_suggestions,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_valid_types_is_frozenset(self):
        assert isinstance(VALID_TYPES, frozenset)
        assert "entity_comparison" in VALID_TYPES
        assert "trend_analyzer" in VALID_TYPES

    def test_valid_operations(self):
        assert "difference" in VALID_OPERATIONS
        assert "ratio" in VALID_OPERATIONS

    def test_valid_formulas(self):
        assert "average" in VALID_FORMULAS
        assert "sum" in VALID_FORMULAS

    def test_time_range_map(self):
        assert TIME_RANGE_MAP["1h"] == 1
        assert TIME_RANGE_MAP["7d"] == 168
        assert TIME_RANGE_MAP["30d"] == 720


# ---------------------------------------------------------------------------
# _get_max_tools
# ---------------------------------------------------------------------------


class TestGetMaxTools:
    @patch("assistant.declarative_tools.yaml_config", {})
    def test_default(self):
        assert _get_max_tools() == DEFAULT_MAX_TOOLS

    @patch(
        "assistant.declarative_tools.yaml_config",
        {"declarative_tools": {"max_tools": 10}},
    )
    def test_configured(self):
        assert _get_max_tools() == 10


# ---------------------------------------------------------------------------
# _slugify
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_basic(self):
        assert _slugify("Hello World") == "hello_world"

    def test_special_chars(self):
        result = _slugify("Temp (Büro)")
        assert all(c.isalnum() or c == "_" for c in result)

    def test_truncation(self):
        long_name = "a" * 100
        assert len(_slugify(long_name)) <= 40

    def test_empty_string(self):
        assert _slugify("") == "entity"


# ---------------------------------------------------------------------------
# DeclarativeToolRegistry
# ---------------------------------------------------------------------------


class TestDeclarativeToolRegistry:
    @patch(
        "assistant.declarative_tools.TOOLS_FILE",
        Path("/tmp/nonexistent_declarative_test_empty.yaml"),
    )
    def test_load_empty(self):
        reg = DeclarativeToolRegistry()
        assert reg.list_tools() == []

    @patch(
        "assistant.declarative_tools.TOOLS_FILE",
        Path("/tmp/nonexistent_declarative_test_empty.yaml"),
    )
    def test_get_tool_not_found(self):
        reg = DeclarativeToolRegistry()
        assert reg.get_tool("nonexistent") is None

    @patch(
        "assistant.declarative_tools.TOOLS_FILE",
        Path("/tmp/nonexistent_declarative_test_empty.yaml"),
    )
    def test_delete_tool_not_found(self):
        reg = DeclarativeToolRegistry()
        result = reg.delete_tool("nonexistent")
        assert result["success"] is False

    @patch(
        "assistant.declarative_tools.TOOLS_FILE",
        Path("/tmp/nonexistent_declarative_test.yaml"),
    )
    def test_create_tool_invalid_name(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool("bad name!!", {"type": "entity_comparison"})
        assert result["success"] is False

    @patch(
        "assistant.declarative_tools.TOOLS_FILE",
        Path("/tmp/nonexistent_declarative_test.yaml"),
    )
    def test_create_tool_invalid_type(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool(
            "test_tool",
            {
                "type": "invalid_type",
                "description": "Test",
                "config": {"entity": "sensor.x"},
            },
        )
        assert result["success"] is False
        assert "Unbekannter Typ" in result["message"]

    @patch(
        "assistant.declarative_tools.TOOLS_FILE",
        Path("/tmp/nonexistent_declarative_test.yaml"),
    )
    def test_create_tool_no_description(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool(
            "test_tool",
            {
                "type": "entity_comparison",
                "config": {"entity_a": "a", "entity_b": "b"},
            },
        )
        assert result["success"] is False
        assert "Beschreibung" in result["message"]

    @patch(
        "assistant.declarative_tools.TOOLS_FILE",
        Path("/tmp/nonexistent_declarative_test.yaml"),
    )
    def test_create_tool_no_config(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool(
            "test_tool",
            {
                "type": "entity_comparison",
                "description": "Test tool",
            },
        )
        assert result["success"] is False
        assert "Config" in result["message"]


# ---------------------------------------------------------------------------
# Validation: type-specific
# ---------------------------------------------------------------------------


class TestValidationEntityComparison:
    @patch(
        "assistant.declarative_tools.TOOLS_FILE",
        Path("/tmp/nonexistent_declarative_test.yaml"),
    )
    def test_missing_entity_a(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool(
            "test",
            {
                "type": "entity_comparison",
                "description": "Test",
                "config": {"entity_b": "sensor.b"},
            },
        )
        assert result["success"] is False
        assert "entity_a" in result["message"]

    @patch(
        "assistant.declarative_tools.TOOLS_FILE",
        Path("/tmp/nonexistent_declarative_test.yaml"),
    )
    def test_invalid_operation(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool(
            "test",
            {
                "type": "entity_comparison",
                "description": "Test",
                "config": {
                    "entity_a": "sensor.a",
                    "entity_b": "sensor.b",
                    "operation": "multiply",
                },
            },
        )
        assert result["success"] is False
        assert "Ungueltige Operation" in result["message"]


class TestValidationMultiEntityFormula:
    @patch(
        "assistant.declarative_tools.TOOLS_FILE",
        Path("/tmp/nonexistent_declarative_test.yaml"),
    )
    def test_fewer_than_2_entities(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool(
            "test",
            {
                "type": "multi_entity_formula",
                "description": "Test",
                "config": {"entities": {"a": "sensor.a"}, "formula": "average"},
            },
        )
        assert result["success"] is False
        assert "Mindestens 2" in result["message"]


class TestValidationThresholdMonitor:
    @patch(
        "assistant.declarative_tools.TOOLS_FILE",
        Path("/tmp/nonexistent_declarative_test.yaml"),
    )
    def test_no_entity(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool(
            "test",
            {
                "type": "threshold_monitor",
                "description": "Test",
                "config": {"thresholds": {"min": 10}},
            },
        )
        assert result["success"] is False
        assert "entity" in result["message"]

    @patch(
        "assistant.declarative_tools.TOOLS_FILE",
        Path("/tmp/nonexistent_declarative_test.yaml"),
    )
    def test_no_thresholds(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool(
            "test",
            {
                "type": "threshold_monitor",
                "description": "Test",
                "config": {"entity": "sensor.x", "thresholds": {}},
            },
        )
        assert result["success"] is False
        assert "Schwellwert" in result["message"]


class TestValidationEventCounter:
    @patch(
        "assistant.declarative_tools.TOOLS_FILE",
        Path("/tmp/nonexistent_declarative_test.yaml"),
    )
    def test_no_count_state(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool(
            "test",
            {
                "type": "event_counter",
                "description": "Test",
                "config": {"entities": ["sensor.x"]},
            },
        )
        assert result["success"] is False
        assert "count_state" in result["message"]


class TestValidationEntityAggregator:
    @patch(
        "assistant.declarative_tools.TOOLS_FILE",
        Path("/tmp/nonexistent_declarative_test.yaml"),
    )
    def test_invalid_aggregation(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool(
            "test",
            {
                "type": "entity_aggregator",
                "description": "Test",
                "config": {
                    "entities": ["sensor.a", "sensor.b"],
                    "aggregation": "median",
                },
            },
        )
        assert result["success"] is False
        assert "Ungueltige Aggregation" in result["message"]


class TestValidationScheduleChecker:
    @patch(
        "assistant.declarative_tools.TOOLS_FILE",
        Path("/tmp/nonexistent_declarative_test.yaml"),
    )
    def test_no_schedules(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool(
            "test",
            {
                "type": "schedule_checker",
                "description": "Test",
                "config": {"schedules": []},
            },
        )
        assert result["success"] is False
        assert "Schedule" in result["message"]


class TestValidationStateDuration:
    @patch(
        "assistant.declarative_tools.TOOLS_FILE",
        Path("/tmp/nonexistent_declarative_test.yaml"),
    )
    def test_no_target_state(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool(
            "test",
            {
                "type": "state_duration",
                "description": "Test",
                "config": {"entity": "sensor.x"},
            },
        )
        assert result["success"] is False
        assert "target_state" in result["message"]


class TestValidationTimeComparison:
    @patch(
        "assistant.declarative_tools.TOOLS_FILE",
        Path("/tmp/nonexistent_declarative_test.yaml"),
    )
    def test_invalid_period(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool(
            "test",
            {
                "type": "time_comparison",
                "description": "Test",
                "config": {"entity": "sensor.x", "compare_period": "next_year"},
            },
        )
        assert result["success"] is False
        assert "Ungueltiger compare_period" in result["message"]


class TestValidationTrendAnalyzer:
    @patch(
        "assistant.declarative_tools.TOOLS_FILE",
        Path("/tmp/nonexistent_declarative_test.yaml"),
    )
    def test_no_entity(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool(
            "test",
            {
                "type": "trend_analyzer",
                "description": "Test",
                "config": {"time_range": "24h"},
            },
        )
        assert result["success"] is False
        assert "entity" in result["message"]


# ---------------------------------------------------------------------------
# DeclarativeToolExecutor
# ---------------------------------------------------------------------------


class TestDeclarativeToolExecutor:
    def _make_executor(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        return executor, ha

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self):
        executor, _ = self._make_executor()
        result = await executor.execute("nonexistent")
        assert result["success"] is False
        assert "nicht gefunden" in result["message"]

    def test_parse_time_range_default(self):
        executor, _ = self._make_executor()
        assert executor._parse_time_range({}) == 24

    def test_parse_time_range_7d(self):
        executor, _ = self._make_executor()
        assert executor._parse_time_range({"time_range": "7d"}) == 168

    @pytest.mark.asyncio
    async def test_get_numeric_value_success(self):
        executor, ha = self._make_executor()
        ha.get_state = AsyncMock(return_value={"state": "21.5"})
        val = await executor._get_numeric_value("sensor.temp")
        assert val == 21.5

    @pytest.mark.asyncio
    async def test_get_numeric_value_none(self):
        executor, ha = self._make_executor()
        ha.get_state = AsyncMock(return_value=None)
        val = await executor._get_numeric_value("sensor.temp")
        assert val is None

    @pytest.mark.asyncio
    async def test_get_numeric_value_non_numeric(self):
        executor, ha = self._make_executor()
        ha.get_state = AsyncMock(return_value={"state": "unavailable"})
        val = await executor._get_numeric_value("sensor.temp")
        assert val is None


# ---------------------------------------------------------------------------
# Executor: _exec_entity_comparison
# ---------------------------------------------------------------------------


class TestExecEntityComparison:
    @pytest.mark.asyncio
    async def test_difference(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        ha.get_state = AsyncMock(
            side_effect=[
                {
                    "state": "22.0",
                    "attributes": {
                        "friendly_name": "Innen",
                        "unit_of_measurement": "°C",
                    },
                },
                {
                    "state": "15.0",
                    "attributes": {
                        "friendly_name": "Aussen",
                        "unit_of_measurement": "°C",
                    },
                },
                {"state": "22.0", "attributes": {"friendly_name": "Innen"}},
                {"state": "15.0", "attributes": {"friendly_name": "Aussen"}},
                {"state": "22.0", "attributes": {"unit_of_measurement": "°C"}},
            ]
        )
        config = {
            "entity_a": "sensor.innen",
            "entity_b": "sensor.aussen",
            "operation": "difference",
        }
        result = await executor._exec_entity_comparison(config, "Temp Vergleich")
        assert result["success"] is True
        assert result["result"] == 7.0


# ---------------------------------------------------------------------------
# Executor: _exec_threshold_monitor
# ---------------------------------------------------------------------------


class TestExecThresholdMonitor:
    @pytest.mark.asyncio
    async def test_value_in_range(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        ha.get_state = AsyncMock(
            return_value={
                "state": "21.5",
                "attributes": {
                    "friendly_name": "Wohnzimmer",
                    "unit_of_measurement": "°C",
                },
            }
        )
        config = {"entity": "sensor.temp", "thresholds": {"min": 19, "max": 24}}
        result = await executor._exec_threshold_monitor(config, "Temp check")
        assert result["success"] is True
        assert result["in_range"] is True

    @pytest.mark.asyncio
    async def test_value_too_high(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        ha.get_state = AsyncMock(
            return_value={
                "state": "30.0",
                "attributes": {
                    "friendly_name": "Wohnzimmer",
                    "unit_of_measurement": "°C",
                },
            }
        )
        config = {"entity": "sensor.temp", "thresholds": {"min": 19, "max": 24}}
        result = await executor._exec_threshold_monitor(config, "Temp check")
        assert result["success"] is True
        assert result["in_range"] is False
        assert "ZU HOCH" in result["message"]


# ---------------------------------------------------------------------------
# generate_suggestions
# ---------------------------------------------------------------------------


class TestGenerateSuggestions:
    def test_empty_states(self):
        result = generate_suggestions([], {})
        assert result == []

    def test_temp_sensor_suggestions(self):
        states = [
            {
                "entity_id": "sensor.temp_innen",
                "state": "21",
                "attributes": {
                    "device_class": "temperature",
                    "unit_of_measurement": "°C",
                    "friendly_name": "Innen Temperatur",
                },
            },
            {
                "entity_id": "sensor.temp_aussen",
                "state": "10",
                "attributes": {
                    "device_class": "temperature",
                    "unit_of_measurement": "°C",
                    "friendly_name": "Aussen Temperatur",
                },
            },
        ]
        result = generate_suggestions(states, {})
        names = [s["name"] for s in result]
        assert "innen_vs_aussen" in names

    def test_skips_existing_tools(self):
        states = [
            {
                "entity_id": "sensor.temp_innen",
                "state": "21",
                "attributes": {
                    "device_class": "temperature",
                    "unit_of_measurement": "°C",
                    "friendly_name": "Innen",
                },
            },
            {
                "entity_id": "sensor.temp_aussen",
                "state": "10",
                "attributes": {
                    "device_class": "temperature",
                    "unit_of_measurement": "°C",
                    "friendly_name": "Aussen",
                },
            },
        ]
        existing = {"innen_vs_aussen": {}}
        result = generate_suggestions(states, existing)
        names = [s["name"] for s in result]
        assert "innen_vs_aussen" not in names

    def test_humidity_sensor_suggestions(self):
        states = [
            {
                "entity_id": "sensor.luftfeuchtigkeit_wz",
                "state": "55",
                "attributes": {
                    "device_class": "humidity",
                    "unit_of_measurement": "%",
                    "friendly_name": "WZ Feuchte",
                },
            },
        ]
        result = generate_suggestions(states, {})
        names = [s["name"] for s in result]
        assert "luftfeuchtigkeit_check" in names

    def test_binary_window_suggestions(self):
        states = [
            {
                "entity_id": "binary_sensor.fenster_wz",
                "state": "off",
                "attributes": {"device_class": "window", "friendly_name": "Fenster WZ"},
            },
        ]
        result = generate_suggestions(states, {})
        names = [s["name"] for s in result]
        assert "fenster_oeffnungen" in names


# =====================================================================
# Additional comprehensive tests
# =====================================================================


class TestRegistryCreateToolSuccess:
    """Tests for successful tool creation and persistence."""

    @patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/test_decl_create.yaml"))
    def test_create_valid_entity_comparison(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool(
            "temp_diff",
            {
                "type": "entity_comparison",
                "description": "Temperatur-Differenz innen/aussen",
                "config": {
                    "entity_a": "sensor.temp_innen",
                    "entity_b": "sensor.temp_aussen",
                    "operation": "difference",
                },
            },
        )
        assert result["success"] is True
        assert "gespeichert" in result["message"]
        # Verify it's retrievable
        tool = reg.get_tool("temp_diff")
        assert tool is not None
        assert tool["name"] == "temp_diff"
        assert tool["type"] == "entity_comparison"
        # Cleanup
        import os

        try:
            os.unlink("/tmp/test_decl_create.yaml")
        except OSError:
            pass

    @patch(
        "assistant.declarative_tools.TOOLS_FILE", Path("/tmp/test_decl_create2.yaml")
    )
    def test_create_valid_threshold_monitor(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool(
            "humidity_check",
            {
                "type": "threshold_monitor",
                "description": "Feuchtigkeits-Check",
                "config": {
                    "entity": "sensor.humidity",
                    "thresholds": {"min": 30, "max": 70},
                },
            },
        )
        assert result["success"] is True
        import os

        try:
            os.unlink("/tmp/test_decl_create2.yaml")
        except OSError:
            pass


class TestRegistryDeleteToolSuccess:
    @patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/test_decl_del.yaml"))
    def test_delete_existing_tool(self):
        reg = DeclarativeToolRegistry()
        reg.create_tool(
            "to_delete",
            {
                "type": "threshold_monitor",
                "description": "Test",
                "config": {"entity": "sensor.x", "thresholds": {"min": 10}},
            },
        )
        assert reg.get_tool("to_delete") is not None
        result = reg.delete_tool("to_delete")
        assert result["success"] is True
        assert reg.get_tool("to_delete") is None
        import os

        try:
            os.unlink("/tmp/test_decl_del.yaml")
        except OSError:
            pass


class TestRegistryListTools:
    @patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/test_decl_list.yaml"))
    def test_list_tools_returns_all(self):
        reg = DeclarativeToolRegistry()
        reg.create_tool(
            "tool_a",
            {
                "type": "threshold_monitor",
                "description": "A",
                "config": {"entity": "sensor.a", "thresholds": {"min": 1}},
            },
        )
        reg.create_tool(
            "tool_b",
            {
                "type": "threshold_monitor",
                "description": "B",
                "config": {"entity": "sensor.b", "thresholds": {"max": 99}},
            },
        )
        tools = reg.list_tools()
        assert len(tools) == 2
        names = {t["name"] for t in tools}
        assert names == {"tool_a", "tool_b"}
        import os

        try:
            os.unlink("/tmp/test_decl_list.yaml")
        except OSError:
            pass


class TestRegistryMaxToolsLimit:
    @patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/test_decl_max.yaml"))
    @patch("assistant.declarative_tools._get_max_tools", return_value=2)
    def test_max_tools_reached(self, mock_max):
        reg = DeclarativeToolRegistry()
        reg.create_tool(
            "t1",
            {
                "type": "threshold_monitor",
                "description": "1",
                "config": {"entity": "sensor.a", "thresholds": {"min": 1}},
            },
        )
        reg.create_tool(
            "t2",
            {
                "type": "threshold_monitor",
                "description": "2",
                "config": {"entity": "sensor.b", "thresholds": {"min": 1}},
            },
        )
        result = reg.create_tool(
            "t3",
            {
                "type": "threshold_monitor",
                "description": "3",
                "config": {"entity": "sensor.c", "thresholds": {"min": 1}},
            },
        )
        assert result["success"] is False
        assert "Maximum" in result["message"]
        import os

        try:
            os.unlink("/tmp/test_decl_max.yaml")
        except OSError:
            pass

    @patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/test_decl_upd.yaml"))
    @patch("assistant.declarative_tools._get_max_tools", return_value=2)
    def test_update_existing_tool_at_limit(self, mock_max):
        """Updating an existing tool should work even when at max limit."""
        reg = DeclarativeToolRegistry()
        reg.create_tool(
            "t1",
            {
                "type": "threshold_monitor",
                "description": "1",
                "config": {"entity": "sensor.a", "thresholds": {"min": 1}},
            },
        )
        reg.create_tool(
            "t2",
            {
                "type": "threshold_monitor",
                "description": "2",
                "config": {"entity": "sensor.b", "thresholds": {"min": 1}},
            },
        )
        # Update t1 should succeed
        result = reg.create_tool(
            "t1",
            {
                "type": "threshold_monitor",
                "description": "Updated",
                "config": {"entity": "sensor.a", "thresholds": {"min": 5}},
            },
        )
        assert result["success"] is True
        import os

        try:
            os.unlink("/tmp/test_decl_upd.yaml")
        except OSError:
            pass


class TestRegistryValidToolNames:
    @patch(
        "assistant.declarative_tools.TOOLS_FILE",
        Path("/tmp/nonexistent_declarative_test.yaml"),
    )
    def test_valid_name_with_hyphens(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool(
            "my-tool-name",
            {
                "type": "threshold_monitor",
                "description": "Test",
                "config": {"entity": "sensor.x", "thresholds": {"min": 10}},
            },
        )
        assert result["success"] is True

    @patch(
        "assistant.declarative_tools.TOOLS_FILE",
        Path("/tmp/nonexistent_declarative_test.yaml"),
    )
    def test_empty_name_rejected(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool(
            "",
            {
                "type": "threshold_monitor",
                "description": "T",
                "config": {"entity": "s", "thresholds": {"min": 1}},
            },
        )
        assert result["success"] is False

    @patch(
        "assistant.declarative_tools.TOOLS_FILE",
        Path("/tmp/nonexistent_declarative_test.yaml"),
    )
    def test_special_chars_rejected(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool(
            "tool with spaces!",
            {
                "type": "threshold_monitor",
                "description": "T",
                "config": {"entity": "s", "thresholds": {"min": 1}},
            },
        )
        assert result["success"] is False


class TestRegistryLoadErrors:
    @patch("assistant.declarative_tools.TOOLS_FILE")
    def test_load_corrupted_yaml(self, mock_path):
        """Loading a corrupted YAML file should result in empty tools."""
        mock_path.exists.return_value = True
        with patch("builtins.open", mock_open(read_data="{{invalid: yaml: [")):
            reg = DeclarativeToolRegistry()
        assert reg.list_tools() == []


class TestValidationMultiEntityFormulaInvalidFormula:
    @patch(
        "assistant.declarative_tools.TOOLS_FILE",
        Path("/tmp/nonexistent_declarative_test.yaml"),
    )
    def test_invalid_formula(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool(
            "test",
            {
                "type": "multi_entity_formula",
                "description": "Test",
                "config": {"entities": {"a": "s.a", "b": "s.b"}, "formula": "median"},
            },
        )
        assert result["success"] is False
        assert "Ungueltige Formel" in result["message"]


# ---------------------------------------------------------------------------
# Executor: _exec_multi_entity_formula
# ---------------------------------------------------------------------------


class TestExecMultiEntityFormula:
    def _make_executor(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        return executor, ha

    @pytest.mark.asyncio
    async def test_average_formula(self):
        executor, ha = self._make_executor()
        state_map = {
            "sensor.a": {"state": "20.0", "attributes": {"friendly_name": "A"}},
            "sensor.b": {"state": "24.0", "attributes": {"friendly_name": "B"}},
        }
        ha.get_state = AsyncMock(side_effect=lambda eid: state_map.get(eid))
        config = {
            "entities": {"temp_a": "sensor.a", "temp_b": "sensor.b"},
            "formula": "average",
        }
        result = await executor._exec_multi_entity_formula(config, "Avg Test")
        assert result["success"] is True
        assert result["result"] == 22.0

    @pytest.mark.asyncio
    async def test_sum_formula(self):
        executor, ha = self._make_executor()
        state_map = {
            "sensor.a": {"state": "100", "attributes": {"friendly_name": "A"}},
            "sensor.b": {"state": "200", "attributes": {"friendly_name": "B"}},
        }
        ha.get_state = AsyncMock(side_effect=lambda eid: state_map.get(eid))
        config = {"entities": {"e1": "sensor.a", "e2": "sensor.b"}, "formula": "sum"}
        result = await executor._exec_multi_entity_formula(config, "Sum")
        assert result["success"] is True
        assert result["result"] == 300.0

    @pytest.mark.asyncio
    async def test_no_values_available(self):
        executor, ha = self._make_executor()
        ha.get_state = AsyncMock(return_value=None)
        config = {"entities": {"a": "sensor.a", "b": "sensor.b"}, "formula": "average"}
        result = await executor._exec_multi_entity_formula(config, "Test")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_weighted_average(self):
        executor, ha = self._make_executor()
        state_map = {
            "sensor.a": {"state": "20.0", "attributes": {"friendly_name": "A"}},
            "sensor.b": {"state": "30.0", "attributes": {"friendly_name": "B"}},
        }
        ha.get_state = AsyncMock(side_effect=lambda eid: state_map.get(eid))
        config = {
            "entities": {"a": "sensor.a", "b": "sensor.b"},
            "formula": "weighted_average",
            "weights": {"a": 3, "b": 1},
        }
        result = await executor._exec_multi_entity_formula(config, "WA")
        assert result["success"] is True
        # (20*3 + 30*1) / 4 = 22.5
        assert result["result"] == 22.5


# ---------------------------------------------------------------------------
# Executor: _exec_event_counter
# ---------------------------------------------------------------------------


class TestExecEventCounter:
    @pytest.mark.asyncio
    async def test_counts_on_states(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        ha.get_history = AsyncMock(
            return_value=[
                {"state": "on"},
                {"state": "off"},
                {"state": "on"},
                {"state": "on"},
            ]
        )
        ha.get_state = AsyncMock(
            return_value={"attributes": {"friendly_name": "Light"}}
        )
        config = {"entities": ["light.test"], "count_state": "on", "time_range": "24h"}
        result = await executor._exec_event_counter(config, "Count")
        assert result["success"] is True
        assert result["count"] == 3

    @pytest.mark.asyncio
    async def test_string_entity_converted_to_list(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        ha.get_history = AsyncMock(return_value=[{"state": "on"}])
        ha.get_state = AsyncMock(return_value={"attributes": {"friendly_name": "Test"}})
        config = {"entities": "light.single", "count_state": "on"}
        result = await executor._exec_event_counter(config, "Single")
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_no_history_returns_zero(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        ha.get_history = AsyncMock(return_value=None)
        config = {"entities": ["sensor.x"], "count_state": "on"}
        result = await executor._exec_event_counter(config, "Empty")
        assert result["count"] == 0


# ---------------------------------------------------------------------------
# Executor: _exec_entity_aggregator
# ---------------------------------------------------------------------------


class TestExecEntityAggregator:
    @pytest.mark.asyncio
    async def test_average_aggregation(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        state_map = {
            "sensor.wz": {
                "state": "20.0",
                "attributes": {"friendly_name": "WZ", "unit_of_measurement": "°C"},
            },
            "sensor.sz": {
                "state": "22.0",
                "attributes": {"friendly_name": "SZ", "unit_of_measurement": "°C"},
            },
        }
        ha.get_state = AsyncMock(side_effect=lambda eid: state_map.get(eid))
        config = {"entities": ["sensor.wz", "sensor.sz"], "aggregation": "average"}
        result = await executor._exec_entity_aggregator(config, "Avg Temp")
        assert result["success"] is True
        assert result["result"] == 21.0

    @pytest.mark.asyncio
    async def test_min_aggregation(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        state_map = {
            "sensor.a": {
                "state": "18.0",
                "attributes": {"friendly_name": "A", "unit_of_measurement": "°C"},
            },
            "sensor.b": {
                "state": "22.0",
                "attributes": {"friendly_name": "B", "unit_of_measurement": "°C"},
            },
        }
        ha.get_state = AsyncMock(side_effect=lambda eid: state_map.get(eid))
        config = {"entities": ["sensor.a", "sensor.b"], "aggregation": "min"}
        result = await executor._exec_entity_aggregator(config, "Min")
        assert result["result"] == 18.0

    @pytest.mark.asyncio
    async def test_no_values(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        ha.get_state = AsyncMock(return_value=None)
        config = {"entities": ["sensor.a", "sensor.b"], "aggregation": "average"}
        result = await executor._exec_entity_aggregator(config, "No data")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Executor: _exec_trend_analyzer
# ---------------------------------------------------------------------------


class TestExecTrendAnalyzer:
    @pytest.mark.asyncio
    async def test_stable_trend(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        # 10 identical values -> stable
        history = [{"state": "21.0"} for _ in range(10)]
        ha.get_history = AsyncMock(return_value=history)
        ha.get_state = AsyncMock(
            return_value={
                "attributes": {"friendly_name": "Temp", "unit_of_measurement": "°C"},
            }
        )
        config = {"entity": "sensor.temp", "time_range": "24h"}
        result = await executor._exec_trend_analyzer(config, "Trend")
        assert result["success"] is True
        assert result["trend"] == "stabil"

    @pytest.mark.asyncio
    async def test_rising_trend(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        history = [{"state": str(15 + i)} for i in range(10)]
        ha.get_history = AsyncMock(return_value=history)
        ha.get_state = AsyncMock(
            return_value={
                "attributes": {"friendly_name": "Temp", "unit_of_measurement": "°C"},
            }
        )
        config = {"entity": "sensor.temp", "time_range": "24h"}
        result = await executor._exec_trend_analyzer(config, "Rising")
        assert result["success"] is True
        assert result["trend"] == "steigend"

    @pytest.mark.asyncio
    async def test_no_history(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        ha.get_history = AsyncMock(return_value=None)
        config = {"entity": "sensor.temp"}
        result = await executor._exec_trend_analyzer(config, "No data")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_non_numeric_values_only(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        history = [{"state": "unavailable"}, {"state": "unknown"}]
        ha.get_history = AsyncMock(return_value=history)
        ha.get_state = AsyncMock(
            return_value={"attributes": {"friendly_name": "Broken"}}
        )
        config = {"entity": "sensor.broken"}
        result = await executor._exec_trend_analyzer(config, "Broken")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Executor: _exec_schedule_checker
# ---------------------------------------------------------------------------


class TestExecScheduleChecker:
    @pytest.mark.asyncio
    async def test_no_active_schedule(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        config = {"schedules": [{"start": "03:00", "end": "04:00", "label": "Nacht"}]}
        # Patch datetime to be outside the schedule
        with patch("assistant.declarative_tools.datetime") as mock_dt:
            from datetime import datetime as real_datetime

            fake_now = real_datetime(2026, 3, 20, 12, 0, 0)
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = real_datetime.fromisoformat
            result = await executor._exec_schedule_checker(config, "Schedule")
        assert result["success"] is True
        assert result["active"] is False

    @pytest.mark.asyncio
    async def test_active_schedule(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        config = {"schedules": [{"start": "00:00", "end": "23:59", "label": "Always"}]}
        result = await executor._exec_schedule_checker(config, "Schedule")
        assert result["success"] is True
        assert result["active"] is True
        assert result["schedule"] == "Always"


# ---------------------------------------------------------------------------
# Executor: _exec_state_duration
# ---------------------------------------------------------------------------


class TestExecStateDuration:
    @pytest.mark.asyncio
    async def test_duration_calculation(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        history = [
            {"state": "on", "last_changed": "2026-03-20T08:00:00+00:00"},
            {"state": "off", "last_changed": "2026-03-20T10:00:00+00:00"},
            {"state": "on", "last_changed": "2026-03-20T12:00:00+00:00"},
            {"state": "off", "last_changed": "2026-03-20T13:00:00+00:00"},
        ]
        ha.get_history = AsyncMock(return_value=history)
        ha.get_state = AsyncMock(
            return_value={"attributes": {"friendly_name": "Heizung"}}
        )
        config = {
            "entity": "climate.heizung",
            "target_state": "on",
            "time_range": "24h",
        }
        result = await executor._exec_state_duration(config, "Duration")
        assert result["success"] is True
        # on from 08:00-10:00 (2h) + on from 12:00-13:00 (1h) = 3h = 10800s
        assert result["duration_seconds"] == 10800.0
        assert result["duration_hours"] == 3.0

    @pytest.mark.asyncio
    async def test_no_history(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        ha.get_history = AsyncMock(return_value=None)
        config = {"entity": "sensor.x", "target_state": "on"}
        result = await executor._exec_state_duration(config, "No data")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Executor: _exec_time_comparison
# ---------------------------------------------------------------------------


class TestExecTimeComparison:
    @pytest.mark.asyncio
    async def test_yesterday_comparison(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        current_history = [{"state": "22.0"}, {"state": "23.0"}]
        full_history = [
            {"state": "19.0"},
            {"state": "20.0"},
            {"state": "22.0"},
            {"state": "23.0"},
        ]
        ha.get_history = AsyncMock(side_effect=[current_history, full_history])
        ha.get_state = AsyncMock(
            return_value={
                "attributes": {"friendly_name": "Temp", "unit_of_measurement": "°C"},
            }
        )
        config = {"entity": "sensor.temp", "compare_period": "yesterday"}
        result = await executor._exec_time_comparison(config, "Compare")
        assert result["success"] is True
        assert result["current"] == 22.5  # avg(22, 23)
        assert result["previous"] == 19.5  # avg(19, 20)
        assert result["diff"] == 3.0

    @pytest.mark.asyncio
    async def test_no_current_data(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        ha.get_history = AsyncMock(return_value=None)
        ha.get_state = AsyncMock(return_value={"attributes": {"friendly_name": "X"}})
        config = {"entity": "sensor.x", "compare_period": "yesterday"}
        result = await executor._exec_time_comparison(config, "No data")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Executor: _exec_entity_comparison additional operations
# ---------------------------------------------------------------------------


class TestExecEntityComparisonOperations:
    def _make_exec(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        return executor, ha

    @pytest.mark.asyncio
    async def test_ratio(self):
        executor, ha = self._make_exec()
        ha.get_state = AsyncMock(
            side_effect=[
                {
                    "state": "30.0",
                    "attributes": {"friendly_name": "A", "unit_of_measurement": "W"},
                },
                {
                    "state": "10.0",
                    "attributes": {"friendly_name": "B", "unit_of_measurement": "W"},
                },
                {"state": "30.0", "attributes": {"friendly_name": "A"}},
                {"state": "10.0", "attributes": {"friendly_name": "B"}},
                {"state": "30.0", "attributes": {"unit_of_measurement": "W"}},
            ]
        )
        config = {"entity_a": "sensor.a", "entity_b": "sensor.b", "operation": "ratio"}
        result = await executor._exec_entity_comparison(config, "Ratio")
        assert result["success"] is True
        assert result["result"] == 3.0

    @pytest.mark.asyncio
    async def test_percentage_change(self):
        executor, ha = self._make_exec()
        ha.get_state = AsyncMock(
            side_effect=[
                {"state": "110.0", "attributes": {"friendly_name": "New"}},
                {"state": "100.0", "attributes": {"friendly_name": "Old"}},
                {"state": "110.0", "attributes": {"friendly_name": "New"}},
                {"state": "100.0", "attributes": {"friendly_name": "Old"}},
                {"state": "110.0", "attributes": {}},
            ]
        )
        config = {
            "entity_a": "sensor.new",
            "entity_b": "sensor.old",
            "operation": "percentage_change",
        }
        result = await executor._exec_entity_comparison(config, "Pct")
        assert result["success"] is True
        assert result["result"] == 10.0

    @pytest.mark.asyncio
    async def test_entity_a_unavailable(self):
        executor, ha = self._make_exec()
        ha.get_state = AsyncMock(return_value=None)
        config = {
            "entity_a": "sensor.a",
            "entity_b": "sensor.b",
            "operation": "difference",
        }
        result = await executor._exec_entity_comparison(config, "Fail")
        assert result["success"] is False
        assert "sensor.a" in result["message"]

    @pytest.mark.asyncio
    async def test_entity_b_unavailable(self):
        executor, ha = self._make_exec()
        ha.get_state = AsyncMock(
            side_effect=[
                {"state": "20.0"},
                None,
            ]
        )
        config = {
            "entity_a": "sensor.a",
            "entity_b": "sensor.b",
            "operation": "difference",
        }
        result = await executor._exec_entity_comparison(config, "Fail B")
        assert result["success"] is False
        assert "sensor.b" in result["message"]


# ---------------------------------------------------------------------------
# Executor: execute with unknown type and exception
# ---------------------------------------------------------------------------


class TestExecutorExecuteEdgeCases:
    @pytest.mark.asyncio
    async def test_execute_unknown_type(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        # Inject a tool with unknown type directly
        executor.registry._tools["bad_tool"] = {
            "type": "nonexistent_type",
            "description": "Bad",
            "config": {},
        }
        result = await executor.execute("bad_tool")
        assert result["success"] is False
        assert "Unbekannter Typ" in result["message"]

    @pytest.mark.asyncio
    async def test_execute_handler_exception(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        executor.registry._tools["crash_tool"] = {
            "type": "threshold_monitor",
            "description": "Crash",
            "config": {"entity": "sensor.x", "thresholds": {"min": 10}},
        }
        # Make get_state raise an exception
        ha.get_state = AsyncMock(side_effect=RuntimeError("Boom"))
        result = await executor.execute("crash_tool")
        assert result["success"] is False
        assert "Fehler" in result["message"]


# ---------------------------------------------------------------------------
# Executor helper methods
# ---------------------------------------------------------------------------


class TestExecutorHelpers:
    def _make_exec(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        return executor, ha

    @pytest.mark.asyncio
    async def test_get_entity_name_with_friendly_name(self):
        executor, ha = self._make_exec()
        ha.get_state = AsyncMock(
            return_value={
                "attributes": {"friendly_name": "Living Room Temp"},
            }
        )
        name = await executor._get_entity_name("sensor.lr_temp")
        assert name == "Living Room Temp"

    @pytest.mark.asyncio
    async def test_get_entity_name_fallback_to_entity_id(self):
        executor, ha = self._make_exec()
        ha.get_state = AsyncMock(return_value=None)
        name = await executor._get_entity_name("sensor.missing")
        assert name == "sensor.missing"

    @pytest.mark.asyncio
    async def test_get_entity_unit_with_unit(self):
        executor, ha = self._make_exec()
        ha.get_state = AsyncMock(
            return_value={
                "attributes": {"unit_of_measurement": "kWh"},
            }
        )
        unit = await executor._get_entity_unit("sensor.energy")
        assert unit == "kWh"

    @pytest.mark.asyncio
    async def test_get_entity_unit_no_state(self):
        executor, ha = self._make_exec()
        ha.get_state = AsyncMock(return_value=None)
        unit = await executor._get_entity_unit("sensor.missing")
        assert unit == ""

    def test_parse_time_range_unknown_returns_default(self):
        executor, _ = self._make_exec()
        assert executor._parse_time_range({"time_range": "99y"}) == 24


# ---------------------------------------------------------------------------
# Executor: _exec_threshold_monitor additional cases
# ---------------------------------------------------------------------------


class TestExecThresholdMonitorEdgeCases:
    @pytest.mark.asyncio
    async def test_value_too_low(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        ha.get_state = AsyncMock(
            return_value={
                "state": "5.0",
                "attributes": {"friendly_name": "Temp", "unit_of_measurement": "°C"},
            }
        )
        config = {"entity": "sensor.temp", "thresholds": {"min": 15, "max": 25}}
        result = await executor._exec_threshold_monitor(config, "Low")
        assert result["in_range"] is False
        assert "ZU NIEDRIG" in result["message"]

    @pytest.mark.asyncio
    async def test_value_unavailable(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        ha.get_state = AsyncMock(return_value={"state": "unavailable"})
        config = {"entity": "sensor.temp", "thresholds": {"min": 15}}
        result = await executor._exec_threshold_monitor(config, "Unavailable")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_custom_ok_label(self):
        ha = AsyncMock()
        with patch(
            "assistant.declarative_tools.TOOLS_FILE",
            Path("/tmp/nonexistent_declarative_test.yaml"),
        ):
            executor = DeclarativeToolExecutor(ha)
        ha.get_state = AsyncMock(
            return_value={
                "state": "20.0",
                "attributes": {"friendly_name": "Temp", "unit_of_measurement": "°C"},
            }
        )
        config = {
            "entity": "sensor.temp",
            "thresholds": {"min": 15, "max": 25},
            "labels": {"ok": "Alles gut"},
        }
        result = await executor._exec_threshold_monitor(config, "Custom label")
        assert result["in_range"] is True
        assert "Alles gut" in result["message"]
