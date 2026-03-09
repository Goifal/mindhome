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

    @patch("assistant.declarative_tools.yaml_config", {"declarative_tools": {"max_tools": 10}})
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
    @patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/nonexistent_declarative_test.yaml"))
    def test_load_empty(self):
        reg = DeclarativeToolRegistry()
        assert reg.list_tools() == []

    @patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/nonexistent_declarative_test.yaml"))
    def test_get_tool_not_found(self):
        reg = DeclarativeToolRegistry()
        assert reg.get_tool("nonexistent") is None

    @patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/nonexistent_declarative_test.yaml"))
    def test_delete_tool_not_found(self):
        reg = DeclarativeToolRegistry()
        result = reg.delete_tool("nonexistent")
        assert result["success"] is False

    @patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/nonexistent_declarative_test.yaml"))
    def test_create_tool_invalid_name(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool("bad name!!", {"type": "entity_comparison"})
        assert result["success"] is False

    @patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/nonexistent_declarative_test.yaml"))
    def test_create_tool_invalid_type(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool("test_tool", {
            "type": "invalid_type",
            "description": "Test",
            "config": {"entity": "sensor.x"},
        })
        assert result["success"] is False
        assert "Unbekannter Typ" in result["message"]

    @patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/nonexistent_declarative_test.yaml"))
    def test_create_tool_no_description(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool("test_tool", {
            "type": "entity_comparison",
            "config": {"entity_a": "a", "entity_b": "b"},
        })
        assert result["success"] is False
        assert "Beschreibung" in result["message"]

    @patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/nonexistent_declarative_test.yaml"))
    def test_create_tool_no_config(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool("test_tool", {
            "type": "entity_comparison",
            "description": "Test tool",
        })
        assert result["success"] is False
        assert "Config" in result["message"]


# ---------------------------------------------------------------------------
# Validation: type-specific
# ---------------------------------------------------------------------------

class TestValidationEntityComparison:
    @patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/nonexistent_declarative_test.yaml"))
    def test_missing_entity_a(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool("test", {
            "type": "entity_comparison",
            "description": "Test",
            "config": {"entity_b": "sensor.b"},
        })
        assert result["success"] is False
        assert "entity_a" in result["message"]

    @patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/nonexistent_declarative_test.yaml"))
    def test_invalid_operation(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool("test", {
            "type": "entity_comparison",
            "description": "Test",
            "config": {"entity_a": "sensor.a", "entity_b": "sensor.b", "operation": "multiply"},
        })
        assert result["success"] is False
        assert "Ungueltige Operation" in result["message"]


class TestValidationMultiEntityFormula:
    @patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/nonexistent_declarative_test.yaml"))
    def test_fewer_than_2_entities(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool("test", {
            "type": "multi_entity_formula",
            "description": "Test",
            "config": {"entities": {"a": "sensor.a"}, "formula": "average"},
        })
        assert result["success"] is False
        assert "Mindestens 2" in result["message"]


class TestValidationThresholdMonitor:
    @patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/nonexistent_declarative_test.yaml"))
    def test_no_entity(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool("test", {
            "type": "threshold_monitor",
            "description": "Test",
            "config": {"thresholds": {"min": 10}},
        })
        assert result["success"] is False
        assert "entity" in result["message"]

    @patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/nonexistent_declarative_test.yaml"))
    def test_no_thresholds(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool("test", {
            "type": "threshold_monitor",
            "description": "Test",
            "config": {"entity": "sensor.x", "thresholds": {}},
        })
        assert result["success"] is False
        assert "Schwellwert" in result["message"]


class TestValidationEventCounter:
    @patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/nonexistent_declarative_test.yaml"))
    def test_no_count_state(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool("test", {
            "type": "event_counter",
            "description": "Test",
            "config": {"entities": ["sensor.x"]},
        })
        assert result["success"] is False
        assert "count_state" in result["message"]


class TestValidationEntityAggregator:
    @patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/nonexistent_declarative_test.yaml"))
    def test_invalid_aggregation(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool("test", {
            "type": "entity_aggregator",
            "description": "Test",
            "config": {"entities": ["sensor.a", "sensor.b"], "aggregation": "median"},
        })
        assert result["success"] is False
        assert "Ungueltige Aggregation" in result["message"]


class TestValidationScheduleChecker:
    @patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/nonexistent_declarative_test.yaml"))
    def test_no_schedules(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool("test", {
            "type": "schedule_checker",
            "description": "Test",
            "config": {"schedules": []},
        })
        assert result["success"] is False
        assert "Schedule" in result["message"]


class TestValidationStateDuration:
    @patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/nonexistent_declarative_test.yaml"))
    def test_no_target_state(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool("test", {
            "type": "state_duration",
            "description": "Test",
            "config": {"entity": "sensor.x"},
        })
        assert result["success"] is False
        assert "target_state" in result["message"]


class TestValidationTimeComparison:
    @patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/nonexistent_declarative_test.yaml"))
    def test_invalid_period(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool("test", {
            "type": "time_comparison",
            "description": "Test",
            "config": {"entity": "sensor.x", "compare_period": "next_year"},
        })
        assert result["success"] is False
        assert "Ungueltiger compare_period" in result["message"]


class TestValidationTrendAnalyzer:
    @patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/nonexistent_declarative_test.yaml"))
    def test_no_entity(self):
        reg = DeclarativeToolRegistry()
        result = reg.create_tool("test", {
            "type": "trend_analyzer",
            "description": "Test",
            "config": {"time_range": "24h"},
        })
        assert result["success"] is False
        assert "entity" in result["message"]


# ---------------------------------------------------------------------------
# DeclarativeToolExecutor
# ---------------------------------------------------------------------------

class TestDeclarativeToolExecutor:
    def _make_executor(self):
        ha = AsyncMock()
        with patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/nonexistent_declarative_test.yaml")):
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
        with patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/nonexistent_declarative_test.yaml")):
            executor = DeclarativeToolExecutor(ha)
        ha.get_state = AsyncMock(side_effect=[
            {"state": "22.0", "attributes": {"friendly_name": "Innen", "unit_of_measurement": "°C"}},
            {"state": "15.0", "attributes": {"friendly_name": "Aussen", "unit_of_measurement": "°C"}},
            {"state": "22.0", "attributes": {"friendly_name": "Innen"}},
            {"state": "15.0", "attributes": {"friendly_name": "Aussen"}},
            {"state": "22.0", "attributes": {"unit_of_measurement": "°C"}},
        ])
        config = {"entity_a": "sensor.innen", "entity_b": "sensor.aussen", "operation": "difference"}
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
        with patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/nonexistent_declarative_test.yaml")):
            executor = DeclarativeToolExecutor(ha)
        ha.get_state = AsyncMock(return_value={
            "state": "21.5",
            "attributes": {"friendly_name": "Wohnzimmer", "unit_of_measurement": "°C"},
        })
        config = {"entity": "sensor.temp", "thresholds": {"min": 19, "max": 24}}
        result = await executor._exec_threshold_monitor(config, "Temp check")
        assert result["success"] is True
        assert result["in_range"] is True

    @pytest.mark.asyncio
    async def test_value_too_high(self):
        ha = AsyncMock()
        with patch("assistant.declarative_tools.TOOLS_FILE", Path("/tmp/nonexistent_declarative_test.yaml")):
            executor = DeclarativeToolExecutor(ha)
        ha.get_state = AsyncMock(return_value={
            "state": "30.0",
            "attributes": {"friendly_name": "Wohnzimmer", "unit_of_measurement": "°C"},
        })
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
            {"entity_id": "sensor.temp_innen", "state": "21", "attributes": {"device_class": "temperature", "unit_of_measurement": "°C", "friendly_name": "Innen Temperatur"}},
            {"entity_id": "sensor.temp_aussen", "state": "10", "attributes": {"device_class": "temperature", "unit_of_measurement": "°C", "friendly_name": "Aussen Temperatur"}},
        ]
        result = generate_suggestions(states, {})
        names = [s["name"] for s in result]
        assert "innen_vs_aussen" in names

    def test_skips_existing_tools(self):
        states = [
            {"entity_id": "sensor.temp_innen", "state": "21", "attributes": {"device_class": "temperature", "unit_of_measurement": "°C", "friendly_name": "Innen"}},
            {"entity_id": "sensor.temp_aussen", "state": "10", "attributes": {"device_class": "temperature", "unit_of_measurement": "°C", "friendly_name": "Aussen"}},
        ]
        existing = {"innen_vs_aussen": {}}
        result = generate_suggestions(states, existing)
        names = [s["name"] for s in result]
        assert "innen_vs_aussen" not in names

    def test_humidity_sensor_suggestions(self):
        states = [
            {"entity_id": "sensor.luftfeuchtigkeit_wz", "state": "55", "attributes": {"device_class": "humidity", "unit_of_measurement": "%", "friendly_name": "WZ Feuchte"}},
        ]
        result = generate_suggestions(states, {})
        names = [s["name"] for s in result]
        assert "luftfeuchtigkeit_check" in names

    def test_binary_window_suggestions(self):
        states = [
            {"entity_id": "binary_sensor.fenster_wz", "state": "off", "attributes": {"device_class": "window", "friendly_name": "Fenster WZ"}},
        ]
        result = generate_suggestions(states, {})
        names = [s["name"] for s in result]
        assert "fenster_oeffnungen" in names
