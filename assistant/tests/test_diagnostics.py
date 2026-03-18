"""
Tests fuer DiagnosticsEngine — Sensor-Watchdog, Wartungs-Assistent, Self-Diagnostik.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from assistant.diagnostics import DiagnosticsEngine


# =====================================================================
# Fixtures
# =====================================================================

DIAG_CONFIG = {
    "diagnostics": {
        "enabled": True,
        "check_interval_minutes": 30,
        "battery_warning_threshold": 20,
        "stale_sensor_minutes": 360,
        "offline_threshold_minutes": 30,
        "alert_cooldown_minutes": 240,
        "monitor_domains": ["sensor", "binary_sensor", "light", "switch"],
        "exclude_patterns": ["weather.", "sun.", "forecast"],
        "monitored_entities": [],
    },
    "maintenance": {"enabled": True},
}


@pytest.fixture
def engine(ha_mock):
    """DiagnosticsEngine mit gemockter Config."""
    with patch("assistant.diagnostics.yaml_config", DIAG_CONFIG), \
         patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
         patch("assistant.diagnostics.get_entity_annotation", return_value=None):
        return DiagnosticsEngine(ha_mock)


# =====================================================================
# _format_duration (static)
# =====================================================================


class TestFormatDuration:
    @pytest.mark.parametrize(
        "minutes, expected",
        [
            (5, "5 Minuten"),
            (0, "0 Minuten"),
            (59, "59 Minuten"),
        ],
    )
    def test_under_60_minutes(self, minutes, expected):
        assert DiagnosticsEngine._format_duration(minutes) == expected

    def test_exactly_one_hour(self):
        assert DiagnosticsEngine._format_duration(60) == "1 Stunde"

    def test_hours_with_remaining_minutes(self):
        assert DiagnosticsEngine._format_duration(90) == "1 Std 30 Min"

    def test_exact_multiple_hours(self):
        assert DiagnosticsEngine._format_duration(120) == "2 Stunden"

    def test_23_hours_59_min(self):
        assert DiagnosticsEngine._format_duration(1439) == "23 Std 59 Min"

    def test_exactly_one_day(self):
        assert DiagnosticsEngine._format_duration(1440) == "1 Tag"

    def test_one_day_with_hours(self):
        result = DiagnosticsEngine._format_duration(1500)  # 25 hours
        assert "1 Tag" in result
        assert "1 Std" in result

    def test_multiple_days(self):
        result = DiagnosticsEngine._format_duration(2880)  # 48 hours
        assert "2 Tagen" in result

    def test_multiple_days_with_hours(self):
        result = DiagnosticsEngine._format_duration(3000)  # 50 hours
        assert "2 Tagen" in result
        assert "2 Std" in result


# =====================================================================
# _check_cooldown
# =====================================================================


class TestCheckCooldown:
    def test_first_call_returns_true(self, engine):
        assert engine._check_cooldown("test:key") is True

    def test_second_call_within_cooldown_returns_false(self, engine):
        engine._check_cooldown("test:key")
        assert engine._check_cooldown("test:key") is False

    def test_different_keys_independent(self, engine):
        engine._check_cooldown("key_a")
        assert engine._check_cooldown("key_b") is True

    def test_expired_cooldown_returns_true(self, engine):
        engine._check_cooldown("test:key")
        # Manually expire the cooldown
        engine._alert_cooldowns["test:key"] = datetime.now() - timedelta(minutes=241)
        assert engine._check_cooldown("test:key") is True


# =====================================================================
# _should_monitor
# =====================================================================


class TestShouldMonitor:
    def test_hidden_entity_excluded(self, ha_mock):
        with patch("assistant.diagnostics.yaml_config", DIAG_CONFIG), \
             patch("assistant.diagnostics.is_entity_hidden", return_value=True), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=None):
            eng = DiagnosticsEngine(ha_mock)
            assert eng._should_monitor("sensor.temperature") is False

    def test_annotated_entity_with_role_monitored(self, ha_mock):
        ann = {"role": "temperature", "diagnostics": True}
        with patch("assistant.diagnostics.yaml_config", DIAG_CONFIG), \
             patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=ann):
            eng = DiagnosticsEngine(ha_mock)
            assert eng._should_monitor("sensor.temp") is True

    def test_annotated_entity_diagnostics_disabled(self, ha_mock):
        ann = {"role": "temperature", "diagnostics": False}
        with patch("assistant.diagnostics.yaml_config", DIAG_CONFIG), \
             patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=ann):
            eng = DiagnosticsEngine(ha_mock)
            assert eng._should_monitor("sensor.temp") is False

    def test_valid_domain_monitored(self, engine):
        with patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=None):
            assert engine._should_monitor("sensor.temperature") is True

    def test_excluded_domain_not_monitored(self, engine):
        with patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=None):
            assert engine._should_monitor("automation.my_rule") is False

    def test_exclude_pattern_blocks(self, engine):
        with patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=None):
            assert engine._should_monitor("sensor.weather.temperature") is False

    def test_forecast_pattern_blocks(self, engine):
        with patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=None):
            assert engine._should_monitor("sensor.forecast_tomorrow") is False

    def test_whitelist_mode(self, ha_mock):
        cfg = dict(DIAG_CONFIG)
        cfg = {**DIAG_CONFIG, "diagnostics": {
            **DIAG_CONFIG["diagnostics"],
            "monitored_entities": ["sensor.specific"],
        }}
        with patch("assistant.diagnostics.yaml_config", cfg), \
             patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=None):
            eng = DiagnosticsEngine(ha_mock)
            assert eng._should_monitor("sensor.specific") is True
            assert eng._should_monitor("sensor.other") is False


# =====================================================================
# check_maintenance
# =====================================================================


class TestCheckMaintenance:
    def _make_engine(self, tasks, ha_mock):
        with patch("assistant.diagnostics.yaml_config", DIAG_CONFIG), \
             patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=None):
            eng = DiagnosticsEngine(ha_mock)
        eng._load_maintenance_tasks = MagicMock(return_value=tasks)
        return eng

    def test_overdue_task(self, ha_mock):
        old_date = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d")
        tasks = [{"name": "Filter wechseln", "interval_days": 30, "last_done": old_date, "priority": "medium"}]
        eng = self._make_engine(tasks, ha_mock)
        due = eng.check_maintenance()
        assert len(due) == 1
        assert due[0]["name"] == "Filter wechseln"
        assert due[0]["days_overdue"] >= 10

    def test_task_not_yet_due(self, ha_mock):
        recent_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        tasks = [{"name": "Filter wechseln", "interval_days": 30, "last_done": recent_date, "priority": "low"}]
        eng = self._make_engine(tasks, ha_mock)
        due = eng.check_maintenance()
        assert len(due) == 0

    def test_never_done_task_always_due(self, ha_mock):
        tasks = [{"name": "Ersteinrichtung", "interval_days": 90, "last_done": None, "priority": "high"}]
        eng = self._make_engine(tasks, ha_mock)
        due = eng.check_maintenance()
        assert len(due) == 1
        assert due[0]["last_done"] is None

    def test_invalid_date_treated_as_due(self, ha_mock):
        tasks = [{"name": "Test", "interval_days": 30, "last_done": "not-a-date", "priority": "low"}]
        eng = self._make_engine(tasks, ha_mock)
        due = eng.check_maintenance()
        assert len(due) == 1
        assert due[0]["last_done"] is None

    def test_zero_interval_skipped(self, ha_mock):
        tasks = [{"name": "No interval", "interval_days": 0, "last_done": None}]
        eng = self._make_engine(tasks, ha_mock)
        due = eng.check_maintenance()
        assert len(due) == 0

    def test_maintenance_disabled(self, ha_mock):
        cfg = {**DIAG_CONFIG, "maintenance": {"enabled": False}}
        with patch("assistant.diagnostics.yaml_config", cfg), \
             patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=None):
            eng = DiagnosticsEngine(ha_mock)
        eng._load_maintenance_tasks = MagicMock(return_value=[
            {"name": "Task", "interval_days": 1, "last_done": None},
        ])
        assert eng.check_maintenance() == []

    def test_description_forwarded(self, ha_mock):
        tasks = [{"name": "Filter", "interval_days": 1, "last_done": None, "priority": "low", "description": "Luftfilter tauschen"}]
        eng = self._make_engine(tasks, ha_mock)
        due = eng.check_maintenance()
        assert due[0]["description"] == "Luftfilter tauschen"


# =====================================================================
# complete_task / get_task_history
# =====================================================================


class TestCompleteTask:
    def test_complete_existing_task(self, engine):
        tasks = [{"name": "Filter wechseln", "interval_days": 30, "last_done": "2025-01-01", "history": []}]
        engine._load_maintenance_tasks = MagicMock(return_value=tasks)
        engine._save_maintenance_tasks = MagicMock()
        result = engine.complete_task("Filter wechseln")
        assert result is True
        engine._save_maintenance_tasks.assert_called_once()
        saved = engine._save_maintenance_tasks.call_args[0][0]
        assert saved[0]["last_done"] == datetime.now().strftime("%Y-%m-%d")

    def test_complete_nonexistent_task(self, engine):
        engine._load_maintenance_tasks = MagicMock(return_value=[])
        engine._save_maintenance_tasks = MagicMock()
        result = engine.complete_task("Nope")
        assert result is False
        engine._save_maintenance_tasks.assert_not_called()

    def test_complete_task_case_insensitive(self, engine):
        tasks = [{"name": "Filter Wechseln", "interval_days": 30, "history": []}]
        engine._load_maintenance_tasks = MagicMock(return_value=tasks)
        engine._save_maintenance_tasks = MagicMock()
        assert engine.complete_task("filter wechseln") is True

    def test_get_task_history_exists(self, engine):
        tasks = [{"name": "Filter", "history": ["2025-01-01", "2025-02-01"]}]
        engine._load_maintenance_tasks = MagicMock(return_value=tasks)
        history = engine.get_task_history("Filter")
        assert len(history) == 2

    def test_get_task_history_nonexistent(self, engine):
        engine._load_maintenance_tasks = MagicMock(return_value=[])
        assert engine.get_task_history("Nope") == []

    def test_history_limited_to_10_entries(self, engine):
        existing_history = [f"2025-01-{i:02d}" for i in range(1, 11)]
        tasks = [{"name": "Task", "interval_days": 1, "history": existing_history}]
        engine._load_maintenance_tasks = MagicMock(return_value=tasks)
        engine._save_maintenance_tasks = MagicMock()
        engine.complete_task("Task")
        saved = engine._save_maintenance_tasks.call_args[0][0]
        assert len(saved[0]["history"]) == 10


# =====================================================================
# check_system_resources
# =====================================================================


class TestCheckSystemResources:
    def test_disk_normal(self, engine):
        mock_usage = MagicMock()
        mock_usage.total = 100 * (1024 ** 3)
        mock_usage.used = 50 * (1024 ** 3)
        mock_usage.free = 50 * (1024 ** 3)
        with patch("assistant.diagnostics.shutil.disk_usage", return_value=mock_usage), \
             patch("assistant.diagnostics.Path.exists", return_value=False):
            result = engine.check_system_resources()
        assert result["disk"]["used_percent"] == 50.0
        assert not result["warnings"]

    def test_disk_critical_warning(self, engine):
        mock_usage = MagicMock()
        mock_usage.total = 100 * (1024 ** 3)
        mock_usage.used = 95 * (1024 ** 3)
        mock_usage.free = 5 * (1024 ** 3)
        with patch("assistant.diagnostics.shutil.disk_usage", return_value=mock_usage), \
             patch("assistant.diagnostics.Path.exists", return_value=False):
            result = engine.check_system_resources()
        assert any("kritisch" in w for w in result["warnings"])

    def test_disk_low_warning(self, engine):
        mock_usage = MagicMock()
        mock_usage.total = 100 * (1024 ** 3)
        mock_usage.used = 85 * (1024 ** 3)
        mock_usage.free = 15 * (1024 ** 3)
        with patch("assistant.diagnostics.shutil.disk_usage", return_value=mock_usage), \
             patch("assistant.diagnostics.Path.exists", return_value=False):
            result = engine.check_system_resources()
        assert any("niedrig" in w for w in result["warnings"])

    def test_memory_critical(self, engine):
        mock_usage = MagicMock()
        mock_usage.total = 100 * (1024 ** 3)
        mock_usage.used = 50 * (1024 ** 3)
        mock_usage.free = 50 * (1024 ** 3)
        meminfo = "MemTotal:        8000000 kB\nMemAvailable:     500000 kB\n"
        with patch("assistant.diagnostics.shutil.disk_usage", return_value=mock_usage), \
             patch("assistant.diagnostics.Path.exists", return_value=True), \
             patch("builtins.open", mock_open(read_data=meminfo)):
            result = engine.check_system_resources()
        assert result["memory"]["used_percent"] > 90
        assert any("RAM kritisch" in w for w in result["warnings"])

    def test_memory_high(self, engine):
        mock_usage = MagicMock()
        mock_usage.total = 100 * (1024 ** 3)
        mock_usage.used = 50 * (1024 ** 3)
        mock_usage.free = 50 * (1024 ** 3)
        meminfo = "MemTotal:        8000000 kB\nMemAvailable:    1400000 kB\n"
        with patch("assistant.diagnostics.shutil.disk_usage", return_value=mock_usage), \
             patch("assistant.diagnostics.Path.exists", return_value=True), \
             patch("builtins.open", mock_open(read_data=meminfo)):
            result = engine.check_system_resources()
        assert result["memory"]["used_percent"] > 80
        assert any("RAM hoch" in w for w in result["warnings"])

    def test_disk_error_handled(self, engine):
        with patch("assistant.diagnostics.shutil.disk_usage", side_effect=OSError("fail")), \
             patch("assistant.diagnostics.Path.exists", return_value=False):
            result = engine.check_system_resources()
        assert "error" in result["disk"]


# =====================================================================
# health_status
# =====================================================================


class TestHealthStatus:
    def test_active_when_enabled(self, engine):
        assert engine.health_status() == "active"

    def test_disabled(self, ha_mock):
        cfg = {**DIAG_CONFIG, "diagnostics": {**DIAG_CONFIG["diagnostics"], "enabled": False}}
        with patch("assistant.diagnostics.yaml_config", cfg), \
             patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=None):
            eng = DiagnosticsEngine(ha_mock)
        assert eng.health_status() == "disabled"


# ------------------------------------------------------------------
# Phase 8: Proaktive Diagnostik-Hinweise
# ------------------------------------------------------------------


class TestPhase8ProactiveDiagnostics:

    @pytest.fixture
    def engine(self, ha_mock):
        with patch("assistant.diagnostics.yaml_config", DIAG_CONFIG), \
             patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=None):
            return DiagnosticsEngine(ha_mock)

    @pytest.mark.asyncio
    async def test_proactive_hints_disabled(self, engine):
        engine.enabled = False
        hints = await engine.get_proactive_hints()
        assert hints == []

    @pytest.mark.asyncio
    async def test_proactive_hints_no_issues(self, engine):
        engine.check_entities = AsyncMock(return_value=[])
        engine.check_system_resources = MagicMock(return_value={})
        hints = await engine.get_proactive_hints()
        assert hints == []

    @pytest.mark.asyncio
    async def test_proactive_hints_low_battery(self, engine):
        engine.check_entities = AsyncMock(return_value=[
            {"entity_id": "sensor.door", "friendly_name": "Tuersensor",
             "status": "low_battery", "battery_level": 15},
        ])
        engine.check_system_resources = MagicMock(return_value={})
        hints = await engine.get_proactive_hints()
        assert len(hints) == 1
        assert hints[0]["type"] == "battery"
        assert "15%" in hints[0]["message"]

    @pytest.mark.asyncio
    async def test_morning_summary_empty(self, engine):
        engine.get_proactive_hints = AsyncMock(return_value=[])
        summary = await engine.get_morning_diagnostic_summary()
        assert summary == ""

    @pytest.mark.asyncio
    async def test_morning_summary_with_warnings(self, engine):
        engine.get_proactive_hints = AsyncMock(return_value=[
            {"message": "Sensor offline", "severity": "warning", "entity_id": "s1", "type": "offline"},
        ])
        summary = await engine.get_morning_diagnostic_summary()
        assert "1 Warnungen" in summary
        assert "Sensor offline" in summary
