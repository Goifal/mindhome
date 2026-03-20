"""
Tests fuer DiagnosticsEngine — Sensor-Watchdog, Wartungs-Assistent, Self-Diagnostik.
"""

from datetime import datetime, timedelta, timezone
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
        engine._alert_cooldowns["test:key"] = datetime.now(timezone.utc) - timedelta(minutes=241)
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

    def test_unannotated_entity_not_monitored(self, engine):
        """Ohne Annotation wird eine Entity nicht ueberwacht (nur annotierte Entities)."""
        with patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=None):
            assert engine._should_monitor("sensor.temperature") is False

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
        old_date = (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%d")
        tasks = [{"name": "Filter wechseln", "interval_days": 30, "last_done": old_date, "priority": "medium"}]
        eng = self._make_engine(tasks, ha_mock)
        due = eng.check_maintenance()
        assert len(due) == 1
        assert due[0]["name"] == "Filter wechseln"
        assert due[0]["days_overdue"] >= 10

    def test_task_not_yet_due(self, ha_mock):
        recent_date = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
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
        assert saved[0]["last_done"] == datetime.now(timezone.utc).strftime("%Y-%m-%d")

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

    @pytest.mark.asyncio
    async def test_morning_summary_mixed_severities(self, engine):
        engine.get_proactive_hints = AsyncMock(return_value=[
            {"message": "Sensor offline", "severity": "warning", "entity_id": "s1", "type": "offline"},
            {"message": "Battery low", "severity": "info", "entity_id": "s2", "type": "battery"},
        ])
        summary = await engine.get_morning_diagnostic_summary()
        assert "1 Warnungen" in summary
        assert "1 Hinweise" in summary


# =====================================================================
# check_entities (Entity-Diagnostik)
# =====================================================================


class TestCheckEntities:

    @pytest.fixture
    def engine(self, ha_mock):
        ann = {"role": "sensor", "diagnostics": True}
        with patch("assistant.diagnostics.yaml_config", DIAG_CONFIG), \
             patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=ann):
            eng = DiagnosticsEngine(ha_mock)
        # Override _should_monitor to always return True for these tests,
        # since we want to test the entity-check logic, not the filter logic.
        eng._should_monitor = MagicMock(return_value=True)
        return eng

    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self, engine):
        engine.enabled = False
        result = await engine.check_entities()
        assert result == []

    @pytest.mark.asyncio
    async def test_no_states_returns_empty(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=None)
        result = await engine.check_entities()
        assert result == []

    @pytest.mark.asyncio
    async def test_offline_entity_detected(self, engine, ha_mock):
        one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "sensor.door", "state": "unavailable",
             "last_changed": one_hour_ago,
             "attributes": {"friendly_name": "Door Sensor"}},
        ])
        result = await engine.check_entities()
        assert len(result) == 1
        assert result[0]["issue_type"] == "offline"
        assert "Door Sensor" in result[0]["message"]

    @pytest.mark.asyncio
    async def test_low_battery_detected(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "sensor.door", "state": "on",
             "last_changed": datetime.now(timezone.utc).isoformat(),
             "attributes": {"friendly_name": "Door Sensor", "battery_level": 10}},
        ])
        result = await engine.check_entities()
        battery_issues = [i for i in result if i["issue_type"] == "low_battery"]
        assert len(battery_issues) == 1
        assert battery_issues[0]["battery_level"] == 10

    @pytest.mark.asyncio
    async def test_critical_battery_severity(self, engine, ha_mock):
        """Battery <= 5% should be critical severity."""
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "sensor.door", "state": "on",
             "last_changed": datetime.now(timezone.utc).isoformat(),
             "attributes": {"friendly_name": "Door Sensor", "battery_level": 3}},
        ])
        result = await engine.check_entities()
        battery_issues = [i for i in result if i["issue_type"] == "low_battery"]
        assert len(battery_issues) == 1
        assert battery_issues[0]["severity"] == "critical"

    @pytest.mark.asyncio
    async def test_stale_sensor_detected(self, engine, ha_mock):
        """Motion sensor unchanged for 7+ hours should be flagged."""
        seven_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "sensor.motion_bath", "state": "off",
             "last_changed": seven_hours_ago,
             "attributes": {"friendly_name": "Motion Bath", "device_class": "motion"}},
        ])
        result = await engine.check_entities()
        stale_issues = [i for i in result if i["issue_type"] == "stale"]
        assert len(stale_issues) == 1

    @pytest.mark.asyncio
    async def test_auto_suppressed_entity_skipped(self, engine, ha_mock):
        """Auto-suppressed entities are not reported."""
        one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "sensor.broken", "state": "unavailable",
             "last_changed": one_hour_ago,
             "attributes": {"friendly_name": "Broken Sensor"}},
        ])
        engine._auto_suppressed["sensor.broken"] = {
            "since": datetime.now(timezone.utc),
            "type": "offline",
        }
        result = await engine.check_entities()
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_healthy_entities_no_issues(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "sensor.temp", "state": "22.5",
             "last_changed": datetime.now(timezone.utc).isoformat(),
             "attributes": {"friendly_name": "Temperature", "device_class": "temperature"}},
        ])
        result = await engine.check_entities()
        assert len(result) == 0


# =====================================================================
# Offline Streaks & Auto-Suppress
# =====================================================================


class TestOfflineStreaks:

    @pytest.fixture
    def engine(self, ha_mock):
        with patch("assistant.diagnostics.yaml_config", DIAG_CONFIG), \
             patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=None):
            return DiagnosticsEngine(ha_mock)

    def test_new_problematic_entity_starts_streak(self, engine):
        now = datetime.now(timezone.utc)
        engine._update_offline_streaks({"sensor.test"}, now)
        assert "sensor.test" in engine._offline_streak
        assert engine._offline_streak["sensor.test"]["count"] == 1

    def test_streak_increments(self, engine):
        now = datetime.now(timezone.utc)
        engine._update_offline_streaks({"sensor.test"}, now)
        engine._update_offline_streaks({"sensor.test"}, now)
        assert engine._offline_streak["sensor.test"]["count"] == 2

    def test_auto_suppress_after_threshold(self, engine):
        now = datetime.now(timezone.utc)
        for _ in range(engine._suppress_after_cycles):
            engine._update_offline_streaks({"sensor.test"}, now)
        assert "sensor.test" in engine._auto_suppressed

    def test_recovered_entity_clears_streak(self, engine):
        now = datetime.now(timezone.utc)
        engine._update_offline_streaks({"sensor.test"}, now)
        assert "sensor.test" in engine._offline_streak
        # Entity no longer problematic
        engine._update_offline_streaks(set(), now)
        assert "sensor.test" not in engine._offline_streak


# =====================================================================
# Entity Recovery
# =====================================================================


class TestEntityRecovery:

    @pytest.fixture
    def engine(self, ha_mock):
        with patch("assistant.diagnostics.yaml_config", DIAG_CONFIG), \
             patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=None):
            return DiagnosticsEngine(ha_mock)

    def test_recovery_of_suppressed_entity(self, engine):
        engine._auto_suppressed["sensor.test"] = {
            "since": datetime(2026, 3, 1, tzinfo=timezone.utc),
            "type": "offline",
            "suppressed_at": datetime(2026, 3, 5, tzinfo=timezone.utc),
        }
        result = engine.on_entity_recovered("sensor.test")
        assert result is not None
        assert result["entity_id"] == "sensor.test"
        assert "sensor.test" not in engine._auto_suppressed

    def test_recovery_of_non_suppressed_entity(self, engine):
        result = engine.on_entity_recovered("sensor.normal")
        assert result is None

    def test_recovery_clears_streak_and_cooldown(self, engine):
        engine._offline_streak["sensor.test"] = {"count": 2}
        engine._alert_cooldowns["offline:sensor.test"] = datetime.now(timezone.utc)
        engine.on_entity_recovered("sensor.test")
        assert "sensor.test" not in engine._offline_streak
        assert "offline:sensor.test" not in engine._alert_cooldowns

    def test_get_suppressed_entities(self, engine):
        engine._auto_suppressed["sensor.a"] = {"since": "2026-01-01", "type": "offline"}
        result = engine.get_suppressed_entities()
        assert "sensor.a" in result


# =====================================================================
# check_all
# =====================================================================


class TestCheckAll:

    @pytest.fixture
    def engine(self, ha_mock):
        with patch("assistant.diagnostics.yaml_config", DIAG_CONFIG), \
             patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=None):
            return DiagnosticsEngine(ha_mock)

    @pytest.mark.asyncio
    async def test_check_all_healthy(self, engine):
        engine.check_entities = AsyncMock(return_value=[])
        engine.check_maintenance = MagicMock(return_value=[])
        with patch.object(DiagnosticsEngine, "check_disk_space", return_value={"status": "ok", "free_pct": 50.0}):
            result = await engine.check_all()
        assert result["healthy"] is True
        assert result["issues"] == []

    @pytest.mark.asyncio
    async def test_check_all_with_issues(self, engine):
        engine.check_entities = AsyncMock(return_value=[
            {"entity_id": "sensor.test", "type": "offline", "message": "Offline"},
        ])
        engine.check_maintenance = MagicMock(return_value=[])
        with patch.object(DiagnosticsEngine, "check_disk_space", return_value={"status": "ok", "free_pct": 50.0}):
            result = await engine.check_all()
        assert result["healthy"] is False
        assert len(result["issues"]) == 1

    @pytest.mark.asyncio
    async def test_check_all_disk_warning(self, engine):
        engine.check_entities = AsyncMock(return_value=[])
        engine.check_maintenance = MagicMock(return_value=[])
        with patch.object(DiagnosticsEngine, "check_disk_space", return_value={"status": "warning", "free_pct": 5.0}):
            result = await engine.check_all()
        assert result["healthy"] is False
        disk_issues = [i for i in result["issues"] if i["type"] == "disk_space_low"]
        assert len(disk_issues) == 1

    @pytest.mark.asyncio
    async def test_check_all_disabled_engine(self, engine):
        engine.enabled = False
        engine.check_maintenance = MagicMock(return_value=[])
        with patch.object(DiagnosticsEngine, "check_disk_space", return_value={"status": "ok", "free_pct": 50.0}):
            result = await engine.check_all()
        # Entities not checked when disabled, but disk/maintenance still run
        assert result["issues"] == []


# =====================================================================
# System Status
# =====================================================================


class TestSystemStatus:

    @pytest.fixture
    def engine(self, ha_mock):
        with patch("assistant.diagnostics.yaml_config", DIAG_CONFIG), \
             patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=None):
            return DiagnosticsEngine(ha_mock)

    @pytest.mark.asyncio
    async def test_no_ha_connection(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=None)
        result = await engine.get_system_status()
        assert "error" in result

    @pytest.mark.asyncio
    async def test_system_status_with_entities(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "sensor.temp", "state": "22", "attributes": {"friendly_name": "Temp"}},
            {"entity_id": "light.living", "state": "on", "attributes": {"friendly_name": "Living"}},
            {"entity_id": "sensor.broken", "state": "unavailable", "attributes": {"friendly_name": "Broken"}},
        ])
        result = await engine.get_system_status()
        assert result["total_entities"] == 3
        assert result["unavailable"] == 1
        assert result["healthy_percent"] < 100

    @pytest.mark.asyncio
    async def test_system_status_low_battery(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "sensor.door", "state": "on",
             "attributes": {"friendly_name": "Door", "battery_level": 10}},
        ])
        result = await engine.get_system_status()
        assert len(result["low_batteries"]) == 1
        assert result["low_batteries"][0]["level"] == 10

    @pytest.mark.asyncio
    async def test_system_status_domains_breakdown(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "sensor.a", "state": "on", "attributes": {}},
            {"entity_id": "sensor.b", "state": "on", "attributes": {}},
            {"entity_id": "light.c", "state": "on", "attributes": {}},
        ])
        result = await engine.get_system_status()
        assert "sensor" in result["domains"]
        assert result["domains"]["sensor"]["total"] == 2
        assert "light" in result["domains"]


# =====================================================================
# Disk Space Check
# =====================================================================


class TestDiskSpace:

    def test_disk_space_ok(self):
        mock_usage = MagicMock()
        mock_usage.total = 100 * (1024 ** 3)
        mock_usage.free = 50 * (1024 ** 3)
        with patch("assistant.diagnostics.shutil.disk_usage", return_value=mock_usage):
            result = DiagnosticsEngine.check_disk_space()
        assert result["status"] == "ok"
        assert result["free_pct"] == 50.0

    def test_disk_space_warning(self):
        mock_usage = MagicMock()
        mock_usage.total = 100 * (1024 ** 3)
        mock_usage.free = 5 * (1024 ** 3)
        with patch("assistant.diagnostics.shutil.disk_usage", return_value=mock_usage):
            result = DiagnosticsEngine.check_disk_space()
        assert result["status"] == "warning"
        assert result["free_pct"] == 5.0


# =====================================================================
# Correlate Root Cause
# =====================================================================


class TestCorrelateRootCause:

    @pytest.fixture
    def engine(self, ha_mock):
        with patch("assistant.diagnostics.yaml_config", DIAG_CONFIG), \
             patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=None):
            return DiagnosticsEngine(ha_mock)

    def test_less_than_3_entities_returns_none(self, engine):
        result = engine.correlate_root_cause(["sensor.a", "sensor.b"])
        assert result is None

    def test_3_entities_same_area(self, engine):
        entities = ["sensor.kueche_temp", "sensor.kueche_humidity", "sensor.kueche_motion"]
        result = engine.correlate_root_cause(entities)
        assert result is not None
        assert "kueche" in result
        assert "3" in result

    def test_entities_different_areas_no_correlation(self, engine):
        entities = ["sensor.kueche_temp", "sensor.bad_humidity", "sensor.schlafzimmer_motion"]
        result = engine.correlate_root_cause(entities)
        assert result is None

    def test_empty_list(self, engine):
        result = engine.correlate_root_cause([])
        assert result is None


# =====================================================================
# Repair Playbooks
# =====================================================================


class TestRepairPlaybook:

    @pytest.fixture
    def engine(self, ha_mock):
        with patch("assistant.diagnostics.yaml_config", DIAG_CONFIG), \
             patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=None):
            return DiagnosticsEngine(ha_mock)

    def test_battery_playbook(self, engine):
        steps = engine.get_repair_playbook("battery")
        assert len(steps) > 0
        assert any("Batterie" in s for s in steps)

    def test_offline_playbook(self, engine):
        steps = engine.get_repair_playbook("offline")
        assert len(steps) > 0
        assert any("Strom" in s or "Neustart" in s or "neu starten" in s for s in steps)

    def test_stale_playbook(self, engine):
        steps = engine.get_repair_playbook("stale")
        assert len(steps) > 0

    def test_unknown_type_fallback(self, engine):
        steps = engine.get_repair_playbook("unknown_type")
        assert len(steps) == 1
        assert "Kein Playbook" in steps[0]


# =====================================================================
# Cooldown cleanup
# =====================================================================


class TestCooldownCleanup:

    @pytest.fixture
    def engine(self, ha_mock):
        with patch("assistant.diagnostics.yaml_config", DIAG_CONFIG), \
             patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=None):
            return DiagnosticsEngine(ha_mock)

    def test_cooldown_cleanup_after_500_entries(self, engine):
        """When cooldown dict exceeds 500 entries, old ones are cleaned."""
        old_time = datetime.now(timezone.utc) - timedelta(hours=25)
        for i in range(501):
            engine._alert_cooldowns[f"test:{i}"] = old_time
        # Next call should trigger cleanup
        engine._check_cooldown("new_key")
        # Old entries should be removed (all were >24h old)
        assert len(engine._alert_cooldowns) < 10


# =====================================================================
# check_connectivity (Service Health Checks)
# =====================================================================


class TestCheckConnectivity:

    @pytest.fixture
    def engine(self, ha_mock):
        with patch("assistant.diagnostics.yaml_config", DIAG_CONFIG), \
             patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=None):
            return DiagnosticsEngine(ha_mock)

    @pytest.mark.asyncio
    async def test_all_services_connected(self, engine, ha_mock):
        """All services report connected when checks succeed."""
        ha_mock.is_available = AsyncMock(return_value=True)
        ha_mock._get_mindhome = AsyncMock(return_value={"status": "ok"})

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session), \
             patch("redis.asyncio.from_url", return_value=mock_redis), \
             patch("assistant.diagnostics.settings") as mock_settings:
            mock_settings.ollama_url = "http://localhost:11434"
            mock_settings.chroma_url = "http://localhost:8000"
            mock_settings.redis_url = "redis://localhost:6379"
            mock_settings.mindhome_url = "http://localhost:8099"
            result = await engine.check_connectivity()

        assert result["home_assistant"]["status"] == "connected"
        assert result["ollama"]["status"] == "connected"
        assert result["redis"]["status"] == "connected"
        assert result["chromadb"]["status"] == "connected"
        assert result["mindhome_addon"]["status"] == "connected"

    @pytest.mark.asyncio
    async def test_ha_disconnected(self, engine, ha_mock):
        """HA reports disconnected when is_available returns False."""
        ha_mock.is_available = AsyncMock(return_value=False)
        ha_mock._get_mindhome = AsyncMock(return_value=None)

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session), \
             patch("redis.asyncio.from_url", return_value=mock_redis), \
             patch("assistant.diagnostics.settings") as mock_settings:
            mock_settings.ollama_url = "http://localhost:11434"
            mock_settings.chroma_url = "http://localhost:8000"
            mock_settings.redis_url = "redis://localhost:6379"
            mock_settings.mindhome_url = "http://localhost:8099"
            result = await engine.check_connectivity()

        assert result["home_assistant"]["status"] == "disconnected"
        assert result["mindhome_addon"]["status"] == "disconnected"

    @pytest.mark.asyncio
    async def test_ha_exception_returns_error(self, engine, ha_mock):
        """HA check exception returns error status."""
        ha_mock.is_available = AsyncMock(side_effect=Exception("Connection refused"))
        ha_mock._get_mindhome = AsyncMock(side_effect=Exception("timeout"))

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session), \
             patch("redis.asyncio.from_url", return_value=mock_redis), \
             patch("assistant.diagnostics.settings") as mock_settings:
            mock_settings.ollama_url = "http://localhost:11434"
            mock_settings.chroma_url = "http://localhost:8000"
            mock_settings.redis_url = "redis://localhost:6379"
            mock_settings.mindhome_url = "http://localhost:8099"
            result = await engine.check_connectivity()

        assert result["home_assistant"]["status"] == "error"
        assert "disconnected" in result["mindhome_addon"]["status"]

    @pytest.mark.asyncio
    async def test_ollama_connection_failure(self, engine, ha_mock):
        """Ollama returns disconnected when connection fails."""
        ha_mock.is_available = AsyncMock(return_value=True)
        ha_mock._get_mindhome = AsyncMock(return_value={"status": "ok"})

        mock_session = AsyncMock()
        mock_session.get = MagicMock(side_effect=Exception("Connection refused"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session), \
             patch("redis.asyncio.from_url", return_value=mock_redis), \
             patch("assistant.diagnostics.settings") as mock_settings:
            mock_settings.ollama_url = "http://localhost:11434"
            mock_settings.chroma_url = "http://localhost:8000"
            mock_settings.redis_url = "redis://localhost:6379"
            mock_settings.mindhome_url = "http://localhost:8099"
            result = await engine.check_connectivity()

        assert result["ollama"]["status"] == "disconnected"
        assert result["chromadb"]["status"] == "disconnected"

    @pytest.mark.asyncio
    async def test_redis_connection_failure(self, engine, ha_mock):
        """Redis returns disconnected when ping fails."""
        ha_mock.is_available = AsyncMock(return_value=True)
        ha_mock._get_mindhome = AsyncMock(return_value={"status": "ok"})

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session), \
             patch("redis.asyncio.from_url", side_effect=Exception("Redis down")), \
             patch("assistant.diagnostics.settings") as mock_settings:
            mock_settings.ollama_url = "http://localhost:11434"
            mock_settings.chroma_url = "http://localhost:8000"
            mock_settings.redis_url = "redis://localhost:6379"
            mock_settings.mindhome_url = "http://localhost:8099"
            result = await engine.check_connectivity()

        assert result["redis"]["status"] == "disconnected"


# =====================================================================
# full_diagnostic (Complete Diagnostic Report)
# =====================================================================


class TestFullDiagnostic:

    @pytest.fixture
    def engine(self, ha_mock):
        with patch("assistant.diagnostics.yaml_config", DIAG_CONFIG), \
             patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=None):
            return DiagnosticsEngine(ha_mock)

    @staticmethod
    async def _mock_to_thread(fn, *args):
        """Helper to mock asyncio.to_thread by calling the function directly."""
        return fn(*args)

    @pytest.mark.asyncio
    async def test_healthy_full_diagnostic(self, engine):
        """Full diagnostic with no issues returns healthy summary."""
        engine.check_entities = AsyncMock(return_value=[])
        engine.get_system_status = AsyncMock(return_value={"total_entities": 5})
        engine.check_connectivity = AsyncMock(return_value={
            "home_assistant": {"status": "connected"},
            "ollama": {"status": "connected"},
        })
        engine.check_system_resources = MagicMock(return_value={
            "disk": {"used_percent": 50}, "memory": {}, "warnings": [],
        })
        engine.check_maintenance = MagicMock(return_value=[])

        with patch("asyncio.to_thread", side_effect=self._mock_to_thread):
            result = await engine.full_diagnostic()

        assert result["summary"]["status"] == "healthy"
        assert result["summary"]["total_warnings"] == 0
        assert result["summary"]["disconnected_services"] == 0
        assert "timestamp" in result

    @pytest.mark.asyncio
    async def test_critical_diagnostic_with_disconnected_service(self, engine):
        """Full diagnostic with disconnected service sets critical status."""
        engine.check_entities = AsyncMock(return_value=[])
        engine.get_system_status = AsyncMock(return_value={"total_entities": 5})
        engine.check_connectivity = AsyncMock(return_value={
            "home_assistant": {"status": "disconnected"},
            "ollama": {"status": "connected"},
        })
        engine.check_system_resources = MagicMock(return_value={
            "disk": {}, "memory": {}, "warnings": [],
        })
        engine.check_maintenance = MagicMock(return_value=[])

        with patch("asyncio.to_thread", side_effect=self._mock_to_thread):
            result = await engine.full_diagnostic()

        assert result["summary"]["status"] == "critical"
        assert result["summary"]["disconnected_services"] == 1

    @pytest.mark.asyncio
    async def test_degraded_diagnostic_many_warnings(self, engine):
        """Full diagnostic with >3 warnings sets degraded status."""
        issues = [
            {"entity_id": f"sensor.s{i}", "issue_type": "offline",
             "message": f"Sensor {i} offline", "severity": "warning"}
            for i in range(4)
        ]
        engine.check_entities = AsyncMock(return_value=issues)
        engine.get_system_status = AsyncMock(return_value={"total_entities": 10})
        engine.check_connectivity = AsyncMock(return_value={
            "ha": {"status": "connected"},
        })
        engine.check_system_resources = MagicMock(return_value={
            "disk": {}, "memory": {}, "warnings": [],
        })
        engine.check_maintenance = MagicMock(return_value=[])

        with patch("asyncio.to_thread", side_effect=self._mock_to_thread):
            result = await engine.full_diagnostic()

        assert result["summary"]["status"] == "degraded"
        assert result["summary"]["total_warnings"] == 4

    @pytest.mark.asyncio
    async def test_warning_diagnostic_few_issues(self, engine):
        """Full diagnostic with 1-3 warnings sets warning status."""
        issues = [
            {"entity_id": "sensor.s1", "issue_type": "stale",
             "message": "Sensor stale", "severity": "info"}
        ]
        engine.check_entities = AsyncMock(return_value=issues)
        engine.get_system_status = AsyncMock(return_value={})
        engine.check_connectivity = AsyncMock(return_value={
            "ha": {"status": "connected"},
        })
        engine.check_system_resources = MagicMock(return_value={
            "disk": {}, "memory": {}, "warnings": [],
        })
        engine.check_maintenance = MagicMock(return_value=[])

        with patch("asyncio.to_thread", side_effect=self._mock_to_thread):
            result = await engine.full_diagnostic()

        assert result["summary"]["status"] == "warning"

    @pytest.mark.asyncio
    async def test_critical_entity_sets_critical_status(self, engine):
        """Full diagnostic with critical-severity entity sets critical."""
        issues = [
            {"entity_id": "sensor.s1", "issue_type": "low_battery",
             "message": "Battery critical", "severity": "critical"}
        ]
        engine.check_entities = AsyncMock(return_value=issues)
        engine.get_system_status = AsyncMock(return_value={})
        engine.check_connectivity = AsyncMock(return_value={})
        engine.check_system_resources = MagicMock(return_value={
            "disk": {}, "memory": {}, "warnings": [],
        })
        engine.check_maintenance = MagicMock(return_value=[])

        with patch("asyncio.to_thread", side_effect=self._mock_to_thread):
            result = await engine.full_diagnostic()

        assert result["summary"]["status"] == "critical"


# =====================================================================
# predict_failure
# =====================================================================


class TestPredictFailure:

    @pytest.fixture
    def engine(self, ha_mock):
        with patch("assistant.diagnostics.yaml_config", DIAG_CONFIG), \
             patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=None):
            return DiagnosticsEngine(ha_mock)

    @pytest.mark.asyncio
    async def test_no_states_returns_none(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=None)
        result = await engine.predict_failure("sensor.test")
        assert result is None

    @pytest.mark.asyncio
    async def test_entity_not_found_returns_none(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "sensor.other", "state": "22", "attributes": {}},
        ])
        result = await engine.predict_failure("sensor.test")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_last_updated_returns_none(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "sensor.test", "state": "22", "attributes": {},
             "last_updated": ""},
        ])
        result = await engine.predict_failure("sensor.test")
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_last_updated_returns_none(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "sensor.test", "state": "22", "attributes": {},
             "last_updated": "not-a-date"},
        ])
        result = await engine.predict_failure("sensor.test")
        assert result is None

    @pytest.mark.asyncio
    async def test_recent_sensor_returns_none(self, engine, ha_mock):
        """Sensor updated recently (< 6h) returns no prediction."""
        recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "sensor.test", "state": "22", "attributes": {},
             "last_updated": recent},
        ])
        result = await engine.predict_failure("sensor.test")
        assert result is None

    @pytest.mark.asyncio
    async def test_stale_sensor_warning(self, engine, ha_mock):
        """Sensor 6-24h stale generates warning prediction."""
        twelve_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "sensor.test", "state": "22",
             "attributes": {"friendly_name": "Test Sensor"},
             "last_updated": twelve_hours_ago},
        ])
        result = await engine.predict_failure("sensor.test")
        assert result is not None
        assert result["entity_id"] == "sensor.test"
        assert "Verzoegerung" in result["prediction"]
        assert 0.4 <= result["confidence"] <= 0.95
        assert result["days_until"] >= 1
        assert result["friendly_name"] == "Test Sensor"

    @pytest.mark.asyncio
    async def test_very_stale_sensor_high_confidence(self, engine, ha_mock):
        """Sensor > 24h stale generates high-confidence prediction."""
        two_days_ago = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "sensor.test", "state": "22",
             "attributes": {"friendly_name": "Test"},
             "last_updated": two_days_ago},
        ])
        result = await engine.predict_failure("sensor.test")
        assert result is not None
        assert "offline" in result["prediction"].lower() or "Batterie" in result["prediction"]
        assert result["confidence"] >= 0.7
        assert result["days_until"] == 1

    @pytest.mark.asyncio
    async def test_predict_failure_exception(self, engine, ha_mock):
        """Exception in predict_failure returns None."""
        ha_mock.get_states = AsyncMock(side_effect=Exception("Network error"))
        result = await engine.predict_failure("sensor.test")
        assert result is None


# =====================================================================
# get_maintenance_tasks / _load_maintenance_tasks / _save_maintenance_tasks
# =====================================================================


class TestMaintenanceFileIO:

    @pytest.fixture
    def engine(self, ha_mock):
        with patch("assistant.diagnostics.yaml_config", DIAG_CONFIG), \
             patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=None):
            return DiagnosticsEngine(ha_mock)

    def test_get_maintenance_tasks_delegates_to_load(self, engine):
        """get_maintenance_tasks() returns result from _load_maintenance_tasks()."""
        tasks = [{"name": "Test", "interval_days": 30}]
        engine._load_maintenance_tasks = MagicMock(return_value=tasks)
        result = engine.get_maintenance_tasks()
        assert result == tasks

    def test_load_maintenance_tasks_from_file(self, engine):
        """_load_maintenance_tasks reads and parses YAML file."""
        yaml_data = "tasks:\n  - name: Filter\n    interval_days: 30\n"
        with patch("pathlib.Path.exists", return_value=True), \
             patch("builtins.open", mock_open(read_data=yaml_data)):
            result = engine._load_maintenance_tasks()
        assert len(result) == 1
        assert result[0]["name"] == "Filter"

    def test_load_maintenance_tasks_file_missing(self, engine):
        """_load_maintenance_tasks returns [] when file doesn't exist."""
        with patch("pathlib.Path.exists", return_value=False):
            result = engine._load_maintenance_tasks()
        assert result == []

    def test_load_maintenance_tasks_exception(self, engine):
        """_load_maintenance_tasks returns [] on parse error."""
        with patch("pathlib.Path.exists", return_value=True), \
             patch("builtins.open", side_effect=IOError("Permission denied")):
            result = engine._load_maintenance_tasks()
        assert result == []

    def test_save_maintenance_tasks_writes_yaml(self, engine):
        """_save_maintenance_tasks writes tasks to YAML file."""
        tasks = [{"name": "Test", "interval_days": 30}]
        m = mock_open()
        with patch("builtins.open", m):
            engine._save_maintenance_tasks(tasks)
        m.assert_called_once()

    def test_save_maintenance_tasks_exception(self, engine):
        """_save_maintenance_tasks handles write errors gracefully."""
        with patch("builtins.open", side_effect=IOError("Disk full")):
            # Should not raise
            engine._save_maintenance_tasks([{"name": "Test"}])


# =====================================================================
# get_user_facing_status (User-Facing Degradation Status)
# =====================================================================


class TestGetUserFacingStatus:

    @pytest.fixture
    def engine(self, ha_mock):
        with patch("assistant.diagnostics.yaml_config", DIAG_CONFIG), \
             patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=None):
            return DiagnosticsEngine(ha_mock)

    @pytest.mark.asyncio
    async def test_all_healthy_returns_none(self, engine, ha_mock):
        """No issues returns None."""
        ha_mock.is_available = AsyncMock(return_value=True)

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()

        mock_usage = MagicMock()
        mock_usage.total = 100 * (1024 ** 3)
        mock_usage.free = 50 * (1024 ** 3)

        import asyncio

        async def _fast_loop_time():
            return 0.5

        mock_loop = MagicMock()
        mock_loop.time = MagicMock(side_effect=[0.0, 0.5])

        with patch("aiohttp.ClientSession", return_value=mock_session), \
             patch("redis.asyncio.from_url", return_value=mock_redis), \
             patch("assistant.diagnostics.shutil.disk_usage", return_value=mock_usage), \
             patch("assistant.diagnostics.Path.exists", return_value=False), \
             patch("asyncio.get_event_loop", return_value=mock_loop), \
             patch("asyncio.to_thread", return_value=None), \
             patch("assistant.diagnostics.settings") as mock_settings:
            mock_settings.ollama_url = "http://localhost:11434"
            mock_settings.redis_url = "redis://localhost:6379"
            result = await engine.get_user_facing_status()

        assert result is None

    @pytest.mark.asyncio
    async def test_ha_disconnected_warning(self, engine, ha_mock):
        """HA unavailable generates warning message."""
        ha_mock.is_available = AsyncMock(return_value=False)

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()

        mock_usage = MagicMock()
        mock_usage.total = 100 * (1024 ** 3)
        mock_usage.free = 50 * (1024 ** 3)

        mock_loop = MagicMock()
        mock_loop.time = MagicMock(side_effect=[0.0, 0.5])

        with patch("aiohttp.ClientSession", return_value=mock_session), \
             patch("redis.asyncio.from_url", return_value=mock_redis), \
             patch("assistant.diagnostics.shutil.disk_usage", return_value=mock_usage), \
             patch("assistant.diagnostics.Path.exists", return_value=False), \
             patch("asyncio.get_event_loop", return_value=mock_loop), \
             patch("asyncio.to_thread", return_value=None), \
             patch("assistant.diagnostics.settings") as mock_settings:
            mock_settings.ollama_url = "http://localhost:11434"
            mock_settings.redis_url = "redis://localhost:6379"
            result = await engine.get_user_facing_status()

        assert result is not None
        assert result["severity"] == "warning"
        assert "Haussteuerung" in result["message"]

    @pytest.mark.asyncio
    async def test_multiple_warnings_combined(self, engine, ha_mock):
        """Multiple warnings are combined into single message."""
        ha_mock.is_available = AsyncMock(return_value=False)

        mock_resp = AsyncMock()
        mock_resp.status = 500  # Ollama unhealthy
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=Exception("Redis down"))
        mock_redis.aclose = AsyncMock()

        mock_usage = MagicMock()
        mock_usage.total = 100 * (1024 ** 3)
        mock_usage.free = 50 * (1024 ** 3)

        mock_loop = MagicMock()
        mock_loop.time = MagicMock(side_effect=[0.0, 0.5])

        with patch("aiohttp.ClientSession", return_value=mock_session), \
             patch("redis.asyncio.from_url", return_value=mock_redis), \
             patch("assistant.diagnostics.shutil.disk_usage", return_value=mock_usage), \
             patch("assistant.diagnostics.Path.exists", return_value=False), \
             patch("asyncio.get_event_loop", return_value=mock_loop), \
             patch("asyncio.to_thread", return_value=None), \
             patch("assistant.diagnostics.settings") as mock_settings:
            mock_settings.ollama_url = "http://localhost:11434"
            mock_settings.redis_url = "redis://localhost:6379"
            result = await engine.get_user_facing_status()

        assert result is not None
        assert result["severity"] == "warning"
        assert "Ausserdem" in result["message"]

    @pytest.mark.asyncio
    async def test_disk_space_critical(self, engine, ha_mock):
        """Very low disk space generates warning."""
        ha_mock.is_available = AsyncMock(return_value=True)

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()

        mock_usage = MagicMock()
        mock_usage.total = 100 * (1024 ** 3)
        mock_usage.free = 3 * (1024 ** 3)  # Only 3% free

        mock_loop = MagicMock()
        mock_loop.time = MagicMock(side_effect=[0.0, 0.5])

        with patch("aiohttp.ClientSession", return_value=mock_session), \
             patch("redis.asyncio.from_url", return_value=mock_redis), \
             patch("assistant.diagnostics.shutil.disk_usage", return_value=mock_usage), \
             patch("assistant.diagnostics.Path.exists", return_value=False), \
             patch("asyncio.get_event_loop", return_value=mock_loop), \
             patch("asyncio.to_thread", return_value=None), \
             patch("assistant.diagnostics.settings") as mock_settings:
            mock_settings.ollama_url = "http://localhost:11434"
            mock_settings.redis_url = "redis://localhost:6379"
            result = await engine.get_user_facing_status()

        assert result is not None
        assert "Speicherplatz" in result["message"]

    @pytest.mark.asyncio
    async def test_disk_space_low_info(self, engine, ha_mock):
        """Moderately low disk space (5-10%) generates info."""
        ha_mock.is_available = AsyncMock(return_value=True)

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()

        mock_usage = MagicMock()
        mock_usage.total = 100 * (1024 ** 3)
        mock_usage.free = 8 * (1024 ** 3)  # 8% free

        mock_loop = MagicMock()
        mock_loop.time = MagicMock(side_effect=[0.0, 0.5])

        with patch("aiohttp.ClientSession", return_value=mock_session), \
             patch("redis.asyncio.from_url", return_value=mock_redis), \
             patch("assistant.diagnostics.shutil.disk_usage", return_value=mock_usage), \
             patch("assistant.diagnostics.Path.exists", return_value=False), \
             patch("asyncio.get_event_loop", return_value=mock_loop), \
             patch("asyncio.to_thread", return_value=None), \
             patch("assistant.diagnostics.settings") as mock_settings:
            mock_settings.ollama_url = "http://localhost:11434"
            mock_settings.redis_url = "redis://localhost:6379"
            result = await engine.get_user_facing_status()

        assert result is not None
        assert result["severity"] == "info"
        assert "Speicherplatz" in result["message"]

    @pytest.mark.asyncio
    async def test_memory_critical(self, engine, ha_mock):
        """Very high memory usage generates warning."""
        ha_mock.is_available = AsyncMock(return_value=True)

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()

        mock_usage = MagicMock()
        mock_usage.total = 100 * (1024 ** 3)
        mock_usage.free = 50 * (1024 ** 3)

        meminfo = {"MemTotal": 8000000, "MemAvailable": 200000}  # ~97.5% used

        mock_loop = MagicMock()
        mock_loop.time = MagicMock(side_effect=[0.0, 0.5])

        import asyncio
        with patch("aiohttp.ClientSession", return_value=mock_session), \
             patch("redis.asyncio.from_url", return_value=mock_redis), \
             patch("assistant.diagnostics.shutil.disk_usage", return_value=mock_usage), \
             patch("assistant.diagnostics.Path.exists", return_value=True), \
             patch("asyncio.get_event_loop", return_value=mock_loop), \
             patch("asyncio.to_thread", return_value=meminfo), \
             patch("assistant.diagnostics.settings") as mock_settings:
            mock_settings.ollama_url = "http://localhost:11434"
            mock_settings.redis_url = "redis://localhost:6379"
            result = await engine.get_user_facing_status()

        assert result is not None
        assert "Arbeitsspeicher" in result["message"]

    @pytest.mark.asyncio
    async def test_ollama_timeout(self, engine, ha_mock):
        """Ollama timeout generates warning."""
        import asyncio as _asyncio
        ha_mock.is_available = AsyncMock(return_value=True)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(side_effect=_asyncio.TimeoutError())
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()

        mock_usage = MagicMock()
        mock_usage.total = 100 * (1024 ** 3)
        mock_usage.free = 50 * (1024 ** 3)

        with patch("aiohttp.ClientSession", return_value=mock_session), \
             patch("redis.asyncio.from_url", return_value=mock_redis), \
             patch("assistant.diagnostics.shutil.disk_usage", return_value=mock_usage), \
             patch("assistant.diagnostics.Path.exists", return_value=False), \
             patch("asyncio.to_thread", return_value=None), \
             patch("assistant.diagnostics.settings") as mock_settings:
            mock_settings.ollama_url = "http://localhost:11434"
            mock_settings.redis_url = "redis://localhost:6379"
            result = await engine.get_user_facing_status()

        assert result is not None
        assert result["severity"] == "warning"
        assert "langsamer" in result["message"]


# =====================================================================
# Proactive hints edge cases (stale/offline statuses)
# =====================================================================


class TestProactiveHintsEdgeCases:

    @pytest.fixture
    def engine(self, ha_mock):
        with patch("assistant.diagnostics.yaml_config", DIAG_CONFIG), \
             patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=None):
            return DiagnosticsEngine(ha_mock)

    @pytest.mark.asyncio
    async def test_stale_entity_hint(self, engine):
        """Stale entity generates appropriate hint."""
        engine.check_entities = AsyncMock(return_value=[
            {"entity_id": "sensor.motion", "friendly_name": "Motion Bath",
             "status": "stale", "stale_minutes": 780},  # 13 hours
        ])
        engine.check_system_resources = MagicMock(return_value={})
        hints = await engine.get_proactive_hints()
        assert len(hints) == 1
        assert hints[0]["type"] == "stale"
        assert hints[0]["severity"] == "warning"  # > 12h
        assert "13h" in hints[0]["message"]

    @pytest.mark.asyncio
    async def test_stale_short_duration_info_severity(self, engine):
        """Stale entity with < 12h gets info severity."""
        engine.check_entities = AsyncMock(return_value=[
            {"entity_id": "sensor.motion", "friendly_name": "Motion",
             "status": "stale", "stale_minutes": 420},  # 7 hours
        ])
        engine.check_system_resources = MagicMock(return_value={})
        hints = await engine.get_proactive_hints()
        assert len(hints) == 1
        assert hints[0]["severity"] == "info"

    @pytest.mark.asyncio
    async def test_offline_entity_hint(self, engine):
        """Offline entity generates offline hint."""
        engine.check_entities = AsyncMock(return_value=[
            {"entity_id": "sensor.door", "friendly_name": "Door Sensor",
             "status": "offline"},
        ])
        engine.check_system_resources = MagicMock(return_value={})
        hints = await engine.get_proactive_hints()
        assert len(hints) == 1
        assert hints[0]["type"] == "offline"
        assert hints[0]["severity"] == "warning"

    @pytest.mark.asyncio
    async def test_proactive_hints_exception_handled(self, engine):
        """Exception in proactive hints returns empty list."""
        engine.check_entities = AsyncMock(side_effect=Exception("Network error"))
        hints = await engine.get_proactive_hints()
        assert hints == []

    @pytest.mark.asyncio
    async def test_morning_summary_info_only(self, engine):
        """Morning summary with only info hints."""
        engine.get_proactive_hints = AsyncMock(return_value=[
            {"message": "Battery low", "severity": "info", "entity_id": "s1", "type": "battery"},
            {"message": "Battery low 2", "severity": "info", "entity_id": "s2", "type": "battery"},
        ])
        summary = await engine.get_morning_diagnostic_summary()
        assert "2 Hinweise" in summary
        assert "Warnungen" not in summary


# =====================================================================
# check_system_resources edge cases
# =====================================================================


class TestCheckSystemResourcesEdgeCases:

    @pytest.fixture
    def engine(self, ha_mock):
        with patch("assistant.diagnostics.yaml_config", DIAG_CONFIG), \
             patch("assistant.diagnostics.is_entity_hidden", return_value=False), \
             patch("assistant.diagnostics.get_entity_annotation", return_value=None):
            return DiagnosticsEngine(ha_mock)

    def test_memory_error_handled(self, engine):
        """Memory read error is handled gracefully."""
        mock_usage = MagicMock()
        mock_usage.total = 100 * (1024 ** 3)
        mock_usage.used = 50 * (1024 ** 3)
        mock_usage.free = 50 * (1024 ** 3)
        with patch("assistant.diagnostics.shutil.disk_usage", return_value=mock_usage), \
             patch("assistant.diagnostics.Path.exists", return_value=True), \
             patch("builtins.open", side_effect=PermissionError("No access")):
            result = engine.check_system_resources()
        assert "error" in result["memory"]

    def test_no_meminfo_path(self, engine):
        """No /proc/meminfo returns no memory data."""
        mock_usage = MagicMock()
        mock_usage.total = 100 * (1024 ** 3)
        mock_usage.used = 50 * (1024 ** 3)
        mock_usage.free = 50 * (1024 ** 3)
        with patch("assistant.diagnostics.shutil.disk_usage", return_value=mock_usage), \
             patch("assistant.diagnostics.Path.exists", return_value=False):
            result = engine.check_system_resources()
        assert result["memory"] == {}
        assert not result["warnings"]
