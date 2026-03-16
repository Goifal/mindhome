"""
Comprehensive tests for DeviceHealthMonitor.

Covers: initialization, check_all, _check_value_anomaly, _check_stale_sensor,
_check_hvac_efficiency, baseline management, cooldown escalation, exclusion
logic, get_status, get_baseline_info, start/stop, error handling.
"""

import asyncio
import math
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Patch yaml_config and function_calling BEFORE importing the module
# ---------------------------------------------------------------------------

_yaml_cfg = {}


def _get_yaml(key, default=None):
    return _yaml_cfg.get(key, default)


@pytest.fixture(autouse=True)
def _reset_yaml_cfg():
    """Reset yaml config between tests."""
    _yaml_cfg.clear()
    yield
    _yaml_cfg.clear()


@pytest.fixture
def patch_deps():
    """Patch yaml_config, function_calling, and state_change_log for every test."""
    with (
        patch("assistant.device_health.yaml_config") as mock_yaml,
        patch("assistant.device_health.is_entity_hidden", return_value=False) as mock_hidden,
        patch("assistant.device_health.get_entity_annotation", return_value=None) as mock_ann,
    ):
        mock_yaml.get = MagicMock(side_effect=_get_yaml)
        yield {
            "yaml_config": mock_yaml,
            "is_entity_hidden": mock_hidden,
            "get_entity_annotation": mock_ann,
        }


def _make_monitor(ha_mock, deps):
    """Create a DeviceHealthMonitor with patched dependencies."""
    from assistant.device_health import DeviceHealthMonitor
    return DeviceHealthMonitor(ha_mock)


# ---------------------------------------------------------------------------
# Test: Initialization
# ---------------------------------------------------------------------------

class TestInit:

    def test_defaults_applied(self, ha_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        assert mon.enabled is True
        assert mon.check_interval == 60
        assert mon.baseline_days == 30
        assert mon.stddev_multiplier == 2.0
        assert mon.min_samples == 10
        assert mon.stale_days == 3
        assert mon.hvac_timeout == 120
        assert mon.hvac_tolerance == 1.0
        assert mon.alert_cooldown == 1440
        assert mon.redis is None
        assert mon._notify_callback is None

    def test_custom_config(self, ha_mock, patch_deps):
        _yaml_cfg["device_health"] = {
            "enabled": False,
            "check_interval_minutes": 30,
            "stddev_multiplier": 3.0,
            "min_samples": 5,
            "stale_sensor_days": 7,
            "monitored_entities": ["sensor.abc"],
        }
        mon = _make_monitor(ha_mock, patch_deps)
        assert mon.enabled is False
        assert mon.check_interval == 30
        assert mon.stddev_multiplier == 3.0
        assert mon.min_samples == 5
        assert mon.stale_days == 7
        assert mon.monitored_entities == ["sensor.abc"]

    @pytest.mark.asyncio
    async def test_initialize_sets_redis(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        assert mon.redis is redis_mock

    def test_set_notify_callback(self, ha_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        cb = AsyncMock()
        mon.set_notify_callback(cb)
        assert mon._notify_callback is cb


# ---------------------------------------------------------------------------
# Test: start / stop
# ---------------------------------------------------------------------------

class TestStartStop:

    @pytest.mark.asyncio
    async def test_start_creates_task_when_enabled(self, ha_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        mon.enabled = True
        # Patch _check_loop so it doesn't actually run
        mon._check_loop = AsyncMock()
        await mon.start()
        assert mon._running is True
        assert mon._task is not None
        await mon.stop()

    @pytest.mark.asyncio
    async def test_start_noop_when_disabled(self, ha_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        mon.enabled = False
        await mon.start()
        assert mon._running is False
        assert mon._task is None

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, ha_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        mon._running = True
        # Create a long-sleeping task to cancel
        mon._task = asyncio.create_task(asyncio.sleep(3600))
        await mon.stop()
        assert mon._running is False
        assert mon._task.cancelled()

    @pytest.mark.asyncio
    async def test_stop_without_task(self, ha_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        mon._running = True
        mon._task = None
        await mon.stop()
        assert mon._running is False


# ---------------------------------------------------------------------------
# Test: _should_exclude
# ---------------------------------------------------------------------------

class TestShouldExclude:

    def test_hidden_entity_excluded(self, ha_mock, patch_deps):
        patch_deps["is_entity_hidden"].return_value = True
        mon = _make_monitor(ha_mock, patch_deps)
        assert mon._should_exclude("sensor.temp") is True

    def test_annotated_entity_with_diagnostics_true(self, ha_mock, patch_deps):
        patch_deps["get_entity_annotation"].return_value = {"role": "thermostat", "diagnostics": True}
        mon = _make_monitor(ha_mock, patch_deps)
        assert mon._should_exclude("climate.living") is False

    def test_annotated_entity_with_diagnostics_false(self, ha_mock, patch_deps):
        patch_deps["get_entity_annotation"].return_value = {"role": "thermostat", "diagnostics": False}
        mon = _make_monitor(ha_mock, patch_deps)
        assert mon._should_exclude("climate.living") is True

    def test_annotated_entity_default_diagnostics(self, ha_mock, patch_deps):
        # role present but no diagnostics key -> defaults True
        patch_deps["get_entity_annotation"].return_value = {"role": "motion_sensor"}
        mon = _make_monitor(ha_mock, patch_deps)
        assert mon._should_exclude("binary_sensor.motion") is False

    def test_monitored_entities_whitelist_match(self, ha_mock, patch_deps):
        _yaml_cfg["device_health"] = {"monitored_entities": ["sensor.abc"]}
        mon = _make_monitor(ha_mock, patch_deps)
        assert mon._should_exclude("sensor.abc") is False

    def test_monitored_entities_whitelist_no_match(self, ha_mock, patch_deps):
        _yaml_cfg["device_health"] = {"monitored_entities": ["sensor.abc"]}
        mon = _make_monitor(ha_mock, patch_deps)
        assert mon._should_exclude("sensor.xyz") is True

    def test_exclude_pattern_weather(self, ha_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        assert mon._should_exclude("weather.home") is True

    def test_exclude_pattern_sun(self, ha_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        assert mon._should_exclude("sun.sun") is True

    def test_domain_not_in_track_domains(self, ha_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        assert mon._should_exclude("light.kitchen") is True

    def test_tracked_sensor_domain_allowed(self, ha_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        assert mon._should_exclude("sensor.temperature") is False

    def test_entity_without_dot_not_excluded(self, ha_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        # no dot -> empty domain -> domain check skipped (empty is falsy)
        assert mon._should_exclude("nodomain") is False


# ---------------------------------------------------------------------------
# Test: check_all
# ---------------------------------------------------------------------------

class TestCheckAll:

    @pytest.mark.asyncio
    async def test_empty_states(self, ha_mock, patch_deps):
        ha_mock.get_states.return_value = []
        mon = _make_monitor(ha_mock, patch_deps)
        result = await mon.check_all()
        assert result == []

    @pytest.mark.asyncio
    async def test_none_states(self, ha_mock, patch_deps):
        ha_mock.get_states.return_value = None
        mon = _make_monitor(ha_mock, patch_deps)
        result = await mon.check_all()
        assert result == []

    @pytest.mark.asyncio
    async def test_excluded_entities_skipped(self, ha_mock, patch_deps):
        patch_deps["is_entity_hidden"].return_value = True
        ha_mock.get_states.return_value = [
            {"entity_id": "sensor.temp", "state": "22.5"},
        ]
        mon = _make_monitor(ha_mock, patch_deps)
        result = await mon.check_all()
        assert result == []

    @pytest.mark.asyncio
    async def test_sensor_non_numeric_skipped(self, ha_mock, redis_mock, patch_deps):
        ha_mock.get_states.return_value = [
            {"entity_id": "sensor.text_thing", "state": "unavailable"},
        ]
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        result = await mon.check_all()
        assert result == []

    @pytest.mark.asyncio
    async def test_climate_dispatched_to_hvac_check(self, ha_mock, redis_mock, patch_deps):
        ha_mock.get_states.return_value = [
            {"entity_id": "climate.living", "state": "heating",
             "attributes": {"current_temperature": 18, "temperature": 22, "friendly_name": "Living"}},
        ]
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        mon._check_hvac_efficiency = AsyncMock(return_value={"alert": True})
        result = await mon.check_all()
        mon._check_hvac_efficiency.assert_awaited_once()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_binary_sensor_dispatched_to_stale_check(self, ha_mock, redis_mock, patch_deps):
        ha_mock.get_states.return_value = [
            {"entity_id": "binary_sensor.motion", "state": "off", "last_changed": "2020-01-01T00:00:00Z"},
        ]
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        mon._check_stale_sensor = AsyncMock(return_value={"alert": True})
        result = await mon.check_all()
        mon._check_stale_sensor.assert_awaited_once()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_check_all_collects_multiple_alerts(self, ha_mock, redis_mock, patch_deps):
        ha_mock.get_states.return_value = [
            {"entity_id": "climate.a", "state": "heating",
             "attributes": {"current_temperature": 15, "temperature": 22, "friendly_name": "A"}},
            {"entity_id": "binary_sensor.b", "state": "off", "last_changed": "2020-01-01T00:00:00Z"},
            {"entity_id": "sensor.c", "state": "99.0"},
        ]
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        mon._check_hvac_efficiency = AsyncMock(return_value={"type": "hvac"})
        mon._check_stale_sensor = AsyncMock(return_value={"type": "stale"})
        mon._check_value_anomaly = AsyncMock(return_value={"type": "anomaly"})
        result = await mon.check_all()
        assert len(result) == 3


# ---------------------------------------------------------------------------
# Test: _check_value_anomaly
# ---------------------------------------------------------------------------

class TestCheckValueAnomaly:

    @pytest.mark.asyncio
    async def test_no_redis_returns_none(self, ha_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        mon.redis = None
        result = await mon._check_value_anomaly("sensor.t", 22.0, {})
        assert result is None

    @pytest.mark.asyncio
    async def test_no_baseline_returns_none(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        mon._get_baseline = AsyncMock(return_value=None)
        mon._add_sample = AsyncMock()
        result = await mon._check_value_anomaly("sensor.t", 22.0, {})
        assert result is None
        mon._add_sample.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_insufficient_samples_returns_none(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        mon._get_baseline = AsyncMock(return_value={"mean": 20.0, "stddev": 2.0, "samples": 5})
        mon._add_sample = AsyncMock()
        result = await mon._check_value_anomaly("sensor.t", 50.0, {})
        assert result is None

    @pytest.mark.asyncio
    async def test_low_stddev_returns_none(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        mon._get_baseline = AsyncMock(return_value={"mean": 20.0, "stddev": 0.0001, "samples": 100})
        mon._add_sample = AsyncMock()
        result = await mon._check_value_anomaly("sensor.t", 50.0, {})
        assert result is None

    @pytest.mark.asyncio
    async def test_within_threshold_returns_none(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        mon._get_baseline = AsyncMock(return_value={"mean": 20.0, "stddev": 5.0, "samples": 50})
        mon._add_sample = AsyncMock()
        # deviation = |21 - 20| / 5 = 0.2, well within 2.0
        result = await mon._check_value_anomaly("sensor.t", 21.0, {"state": "21.0"})
        assert result is None

    @pytest.mark.asyncio
    async def test_anomaly_detected_returns_alert(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        mon._get_baseline = AsyncMock(return_value={"mean": 20.0, "stddev": 2.0, "samples": 50})
        mon._add_sample = AsyncMock()
        mon._check_cooldown = AsyncMock(return_value=True)
        mon._mark_notified = AsyncMock()

        state = {"attributes": {"friendly_name": "Temp Sensor", "unit_of_measurement": "°C"}}
        # deviation = |30 - 20| / 2 = 5.0, above threshold 2.0
        result = await mon._check_value_anomaly("sensor.temp", 30.0, state)

        assert result is not None
        assert result["entity_id"] == "sensor.temp"
        assert result["alert_type"] == "device_anomaly"
        assert result["urgency"] == "low"
        assert result["data"]["current_value"] == 30.0
        assert result["data"]["baseline_mean"] == 20.0
        assert "über" in result["message"]
        mon._mark_notified.assert_awaited_once_with("sensor.temp")

    @pytest.mark.asyncio
    async def test_anomaly_below_mean(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        mon._get_baseline = AsyncMock(return_value={"mean": 20.0, "stddev": 2.0, "samples": 50})
        mon._add_sample = AsyncMock()
        mon._check_cooldown = AsyncMock(return_value=True)
        mon._mark_notified = AsyncMock()

        state = {"attributes": {"friendly_name": "Temp", "unit_of_measurement": "°C"}}
        result = await mon._check_value_anomaly("sensor.temp", 10.0, state)
        assert result is not None
        assert "unter" in result["message"]

    @pytest.mark.asyncio
    async def test_energy_anomaly_message(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        mon._get_baseline = AsyncMock(return_value={"mean": 100.0, "stddev": 10.0, "samples": 50})
        mon._add_sample = AsyncMock()
        mon._check_cooldown = AsyncMock(return_value=True)
        mon._mark_notified = AsyncMock()

        state = {"attributes": {"friendly_name": "Strom", "unit_of_measurement": "kWh"}}
        # entity contains energy keyword "strom", value above mean
        result = await mon._check_value_anomaly("sensor.strom_verbrauch", 200.0, state)
        assert result is not None
        assert "Verbrauch" in result["message"]
        assert "über Durchschnitt" in result["message"]

    @pytest.mark.asyncio
    async def test_energy_sensor_below_mean_uses_general_message(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        mon._get_baseline = AsyncMock(return_value={"mean": 100.0, "stddev": 10.0, "samples": 50})
        mon._add_sample = AsyncMock()
        mon._check_cooldown = AsyncMock(return_value=True)
        mon._mark_notified = AsyncMock()

        state = {"attributes": {"friendly_name": "Strom", "unit_of_measurement": "kWh"}}
        # energy entity but value BELOW mean -> uses general message
        result = await mon._check_value_anomaly("sensor.strom_verbrauch", 50.0, state)
        assert result is not None
        assert "Ungewöhnlicher Wert" in result["message"]

    @pytest.mark.asyncio
    async def test_cooldown_active_returns_none(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        mon._get_baseline = AsyncMock(return_value={"mean": 20.0, "stddev": 2.0, "samples": 50})
        mon._add_sample = AsyncMock()
        mon._check_cooldown = AsyncMock(return_value=False)

        result = await mon._check_value_anomaly("sensor.temp", 50.0, {})
        assert result is None


# ---------------------------------------------------------------------------
# Test: _check_stale_sensor
# ---------------------------------------------------------------------------

class TestCheckStaleSensor:

    @pytest.mark.asyncio
    async def test_no_last_changed_returns_none(self, ha_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        result = await mon._check_stale_sensor("binary_sensor.x", {"last_changed": ""})
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_date_returns_none(self, ha_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        result = await mon._check_stale_sensor("binary_sensor.x", {"last_changed": "not-a-date"})
        assert result is None

    @pytest.mark.asyncio
    async def test_recent_change_returns_none(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        result = await mon._check_stale_sensor("binary_sensor.x", {"last_changed": recent})
        assert result is None

    @pytest.mark.asyncio
    async def test_stale_sensor_motion(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        mon._check_cooldown = AsyncMock(return_value=True)
        mon._mark_notified = AsyncMock()

        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        state = {
            "last_changed": old,
            "attributes": {"friendly_name": "Motion Hallway", "device_class": "motion"},
        }
        result = await mon._check_stale_sensor("binary_sensor.motion_hall", state)
        assert result is not None
        assert result["alert_type"] == "stale_device"
        assert "Batterie prüfen oder Sensor defekt?" in result["message"]
        assert result["data"]["device_class"] == "motion"

    @pytest.mark.asyncio
    async def test_stale_sensor_door(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        mon._check_cooldown = AsyncMock(return_value=True)
        mon._mark_notified = AsyncMock()

        old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        state = {
            "last_changed": old,
            "attributes": {"friendly_name": "Front Door", "device_class": "door"},
        }
        result = await mon._check_stale_sensor("binary_sensor.door", state)
        assert result is not None
        assert "Sensor blockiert oder Batterie leer?" in result["message"]

    @pytest.mark.asyncio
    async def test_stale_sensor_window(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        mon._check_cooldown = AsyncMock(return_value=True)
        mon._mark_notified = AsyncMock()

        old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        state = {
            "last_changed": old,
            "attributes": {"friendly_name": "Window", "device_class": "window"},
        }
        result = await mon._check_stale_sensor("binary_sensor.window", state)
        assert result is not None
        assert "Sensor blockiert oder Batterie leer?" in result["message"]

    @pytest.mark.asyncio
    async def test_stale_sensor_generic_hint(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        mon._check_cooldown = AsyncMock(return_value=True)
        mon._mark_notified = AsyncMock()

        old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        state = {
            "last_changed": old,
            "attributes": {"friendly_name": "Sensor", "device_class": "smoke"},
        }
        result = await mon._check_stale_sensor("binary_sensor.smoke", state)
        assert result is not None
        assert "Batterie oder Verbindung prüfen." in result["message"]

    @pytest.mark.asyncio
    async def test_stale_sensor_cooldown_blocks(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        mon._check_cooldown = AsyncMock(return_value=False)

        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        state = {"last_changed": old, "attributes": {"friendly_name": "X", "device_class": "motion"}}
        result = await mon._check_stale_sensor("binary_sensor.x", state)
        assert result is None

    @pytest.mark.asyncio
    async def test_stale_sensor_z_suffix_timezone(self, ha_mock, redis_mock, patch_deps):
        """Z suffix in ISO dates should be handled correctly."""
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        mon._check_cooldown = AsyncMock(return_value=True)
        mon._mark_notified = AsyncMock()

        old = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        state = {"last_changed": old, "attributes": {"friendly_name": "X", "device_class": "motion"}}
        result = await mon._check_stale_sensor("binary_sensor.x", state)
        assert result is not None


# ---------------------------------------------------------------------------
# Test: _check_hvac_efficiency
# ---------------------------------------------------------------------------

class TestCheckHvacEfficiency:

    def _climate_state(self, current_temp, target_temp, action="heating", name="Thermostat"):
        return {
            "state": action,
            "attributes": {
                "current_temperature": current_temp,
                "temperature": target_temp,
                "friendly_name": name,
            },
        }

    @pytest.mark.asyncio
    async def test_missing_temps_returns_none(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        result = await mon._check_hvac_efficiency("climate.x", {"state": "heating", "attributes": {}})
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_temp_returns_none(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        state = {"state": "heating", "attributes": {"current_temperature": "abc", "temperature": 22}}
        result = await mon._check_hvac_efficiency("climate.x", state)
        assert result is None

    @pytest.mark.asyncio
    async def test_off_state_resets_timer(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        state = self._climate_state(18, 22, action="off")
        result = await mon._check_hvac_efficiency("climate.x", state)
        assert result is None
        redis_mock.delete.assert_awaited_with("mha:device:hvac_start:climate.x")

    @pytest.mark.asyncio
    async def test_idle_state_resets_timer(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        state = self._climate_state(18, 22, action="idle")
        result = await mon._check_hvac_efficiency("climate.x", state)
        assert result is None

    @pytest.mark.asyncio
    async def test_target_reached_resets_timer(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        # diff = |21.5 - 22| = 0.5 <= tolerance 1.0
        state = self._climate_state(21.5, 22, action="heating")
        result = await mon._check_hvac_efficiency("climate.x", state)
        assert result is None
        redis_mock.delete.assert_awaited()

    @pytest.mark.asyncio
    async def test_no_redis_returns_none(self, ha_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        mon.redis = None
        state = self._climate_state(18, 22, action="heating")
        result = await mon._check_hvac_efficiency("climate.x", state)
        assert result is None

    @pytest.mark.asyncio
    async def test_first_check_records_start_time(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        redis_mock.get.return_value = None  # no start time recorded yet

        state = self._climate_state(18, 22, action="heating")
        result = await mon._check_hvac_efficiency("climate.x", state)
        assert result is None
        redis_mock.set.assert_awaited()

    @pytest.mark.asyncio
    async def test_not_timed_out_yet(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        # Start time was 30 minutes ago (< 120 min timeout)
        start = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        redis_mock.get.return_value = start.encode()

        state = self._climate_state(18, 22, action="heating")
        result = await mon._check_hvac_efficiency("climate.x", state)
        assert result is None

    @pytest.mark.asyncio
    async def test_timeout_exceeded_returns_alert(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        mon._check_cooldown = AsyncMock(return_value=True)
        mon._mark_notified = AsyncMock()

        start = (datetime.now(timezone.utc) - timedelta(minutes=150)).isoformat()
        redis_mock.get.return_value = start.encode()

        state = self._climate_state(18, 22, action="heating", name="Living Heater")

        with patch("assistant.device_health.StateChangeLog", create=True) as mock_scl:
            mock_scl._get_entity_role.return_value = ""
            mock_scl._get_entity_room.return_value = ""
            with patch.dict("sys.modules", {"assistant.state_change_log": MagicMock()}):
                result = await mon._check_hvac_efficiency("climate.living", state)

        assert result is not None
        assert result["alert_type"] == "hvac_inefficiency"
        assert result["data"]["hvac_action"] == "heating"
        assert "heizt" in result["message"]
        mon._mark_notified.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cooling_action_message(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        mon._check_cooldown = AsyncMock(return_value=True)
        mon._mark_notified = AsyncMock()

        start = (datetime.now(timezone.utc) - timedelta(minutes=150)).isoformat()
        redis_mock.get.return_value = start.encode()

        state = self._climate_state(28, 22, action="cooling", name="AC")

        with patch("assistant.device_health.StateChangeLog", create=True) as mock_scl:
            mock_scl._get_entity_role.return_value = ""
            mock_scl._get_entity_room.return_value = ""
            with patch.dict("sys.modules", {"assistant.state_change_log": MagicMock()}):
                result = await mon._check_hvac_efficiency("climate.ac", state)

        assert result is not None
        assert "kuehlt" in result["message"]

    @pytest.mark.asyncio
    async def test_hvac_cooldown_blocks(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        mon._check_cooldown = AsyncMock(return_value=False)

        start = (datetime.now(timezone.utc) - timedelta(minutes=150)).isoformat()
        redis_mock.get.return_value = start.encode()

        state = self._climate_state(18, 22, action="heating")

        with patch("assistant.device_health.StateChangeLog", create=True) as mock_scl:
            mock_scl._get_entity_role.return_value = ""
            mock_scl._get_entity_room.return_value = ""
            with patch.dict("sys.modules", {"assistant.state_change_log": MagicMock()}):
                result = await mon._check_hvac_efficiency("climate.x", state)

        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_start_time_deletes_key(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        redis_mock.get.return_value = b"not-a-date"

        state = self._climate_state(18, 22, action="heating")
        result = await mon._check_hvac_efficiency("climate.x", state)
        assert result is None
        redis_mock.delete.assert_awaited_with("mha:device:hvac_start:climate.x")


# ---------------------------------------------------------------------------
# Test: Baseline management
# ---------------------------------------------------------------------------

class TestBaseline:

    @pytest.mark.asyncio
    async def test_get_baseline_no_redis(self, ha_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        result = await mon._get_baseline("sensor.t")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_baseline_empty(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        redis_mock.hgetall.return_value = {}
        result = await mon._get_baseline("sensor.t")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_baseline_success(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        redis_mock.hgetall.return_value = {
            b"mean": b"22.5",
            b"stddev": b"1.5",
            b"samples": b"100",
        }
        result = await mon._get_baseline("sensor.t")
        assert result == {"mean": 22.5, "stddev": 1.5, "samples": 100}

    @pytest.mark.asyncio
    async def test_get_baseline_string_keys(self, ha_mock, redis_mock, patch_deps):
        """Handle non-bytes keys from Redis."""
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        redis_mock.hgetall.return_value = {
            "mean": "22.5", "stddev": "1.5", "samples": "100",
        }
        result = await mon._get_baseline("sensor.t")
        assert result == {"mean": 22.5, "stddev": 1.5, "samples": 100}

    @pytest.mark.asyncio
    async def test_get_baseline_error_returns_none(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        redis_mock.hgetall.side_effect = Exception("redis down")
        result = await mon._get_baseline("sensor.t")
        assert result is None

    @pytest.mark.asyncio
    async def test_add_sample_no_redis(self, ha_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        # Should not raise
        await mon._add_sample("sensor.t", 22.0)

    @pytest.mark.asyncio
    async def test_add_sample_pipeline(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        mon._recalculate_baseline = AsyncMock()

        await mon._add_sample("sensor.t", 22.5)

        pipe = redis_mock._pipeline
        pipe.rpush.assert_called_once()
        pipe.expire.assert_called_once()
        pipe.execute.assert_awaited_once()
        mon._recalculate_baseline.assert_awaited_once_with("sensor.t")

    @pytest.mark.asyncio
    async def test_recalculate_baseline_no_redis(self, ha_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon._recalculate_baseline("sensor.t")
        # Should not raise

    @pytest.mark.asyncio
    async def test_recalculate_baseline_insufficient_data(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        # pipeline returns only 1 value total (< 2 required)
        pipe = redis_mock._pipeline
        pipe.execute.return_value = [[b"22.5"]] + [[] for _ in range(30)]

        await mon._recalculate_baseline("sensor.t")
        # hset should NOT be called because only 1 sample
        redis_mock.hset.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_recalculate_baseline_computes_correctly(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        values = [b"10.0", b"20.0", b"30.0"]
        pipe = redis_mock._pipeline
        pipe.execute.return_value = [values] + [[] for _ in range(30)]

        await mon._recalculate_baseline("sensor.t")

        redis_mock.hset.assert_awaited_once()
        call_kwargs = redis_mock.hset.call_args
        mapping = call_kwargs.kwargs.get("mapping") or call_kwargs[1].get("mapping")
        mean_val = float(mapping["mean"])
        stddev_val = float(mapping["stddev"])
        samples_val = int(mapping["samples"])

        assert abs(mean_val - 20.0) < 0.01
        expected_stddev = math.sqrt(((10 - 20) ** 2 + (20 - 20) ** 2 + (30 - 20) ** 2) / 2)
        assert abs(stddev_val - expected_stddev) < 0.01
        assert samples_val == 3


# ---------------------------------------------------------------------------
# Test: Cooldown & notification
# ---------------------------------------------------------------------------

class TestCooldown:

    @pytest.mark.asyncio
    async def test_check_cooldown_no_redis(self, ha_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        result = await mon._check_cooldown("sensor.t")
        assert result is True

    @pytest.mark.asyncio
    async def test_check_cooldown_not_notified(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        redis_mock.exists.return_value = 0
        result = await mon._check_cooldown("sensor.t")
        assert result is True

    @pytest.mark.asyncio
    async def test_check_cooldown_already_notified(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        redis_mock.exists.return_value = 1
        result = await mon._check_cooldown("sensor.t")
        assert result is False

    @pytest.mark.asyncio
    async def test_check_cooldown_redis_error(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        redis_mock.exists.side_effect = Exception("conn error")
        result = await mon._check_cooldown("sensor.t")
        assert result is True

    @pytest.mark.asyncio
    async def test_mark_notified_no_redis(self, ha_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon._mark_notified("sensor.t")
        # No error

    @pytest.mark.asyncio
    async def test_mark_notified_first_alert(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        redis_mock.incr.return_value = 1  # first alert

        await mon._mark_notified("sensor.t")

        redis_mock.incr.assert_awaited()
        redis_mock.set.assert_awaited_once()
        call_args = redis_mock.set.call_args
        # multiplier = min(2^0, 7) = 1 -> cooldown = 1440*60*1 = 86400
        assert call_args.kwargs.get("ex") == 1440 * 60 * 1

    @pytest.mark.asyncio
    async def test_mark_notified_escalation_second_alert(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        redis_mock.incr.return_value = 2  # second alert

        await mon._mark_notified("sensor.t")

        call_args = redis_mock.set.call_args
        # multiplier = min(2^1, 7) = 2 -> cooldown = 1440*60*2 = 172800
        assert call_args.kwargs.get("ex") == 1440 * 60 * 2

    @pytest.mark.asyncio
    async def test_mark_notified_escalation_third_alert(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        redis_mock.incr.return_value = 3  # third alert

        await mon._mark_notified("sensor.t")

        call_args = redis_mock.set.call_args
        # multiplier = min(2^2, 7) = 4 -> cooldown = 1440*60*4 = 345600
        assert call_args.kwargs.get("ex") == 1440 * 60 * 4

    @pytest.mark.asyncio
    async def test_mark_notified_escalation_caps_at_7(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        redis_mock.incr.return_value = 10  # many alerts

        await mon._mark_notified("sensor.t")

        call_args = redis_mock.set.call_args
        # multiplier = min(2^9, 7) = 7 -> cooldown = 1440*60*7 = 604800 (= 7 days)
        expected = min(1440 * 60 * 7, 7 * 86400)
        assert call_args.kwargs.get("ex") == expected

    @pytest.mark.asyncio
    async def test_mark_notified_redis_error_handled(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        redis_mock.incr.side_effect = Exception("redis down")
        # Should not raise
        await mon._mark_notified("sensor.t")


# ---------------------------------------------------------------------------
# Test: _send_alert
# ---------------------------------------------------------------------------

class TestSendAlert:

    @pytest.mark.asyncio
    async def test_send_alert_with_callback(self, ha_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        cb = AsyncMock()
        mon.set_notify_callback(cb)
        alert = {"message": "test alert"}
        await mon._send_alert(alert)
        cb.assert_awaited_once_with(alert)

    @pytest.mark.asyncio
    async def test_send_alert_no_callback(self, ha_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        # Should not raise, just log
        await mon._send_alert({"message": "test alert"})

    @pytest.mark.asyncio
    async def test_send_alert_callback_error(self, ha_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        cb = AsyncMock(side_effect=Exception("callback error"))
        mon.set_notify_callback(cb)
        # Should not raise
        await mon._send_alert({"message": "test alert"})


# ---------------------------------------------------------------------------
# Test: get_status / get_baseline_info
# ---------------------------------------------------------------------------

class TestStatusAndInfo:

    @pytest.mark.asyncio
    async def test_get_status_no_redis(self, ha_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        status = await mon.get_status()
        assert status == {"enabled": True, "baselines": 0, "alerts_today": 0}

    @pytest.mark.asyncio
    async def test_get_status_with_redis(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)

        # Mock scan_iter as an async generator
        async def baseline_iter(**kwargs):
            for key in [b"mha:device:baseline:sensor.a", b"mha:device:baseline:sensor.b"]:
                yield key

        async def notified_iter(**kwargs):
            for key in [b"mha:device:notified:sensor.a"]:
                yield key

        call_count = [0]

        def scan_iter_side_effect(**kwargs):
            call_count[0] += 1
            if "baseline" in kwargs.get("match", ""):
                return baseline_iter(**kwargs)
            return notified_iter(**kwargs)

        redis_mock.scan_iter = MagicMock(side_effect=scan_iter_side_effect)

        status = await mon.get_status()
        assert status["enabled"] is True
        assert status["baselines"] == 2
        assert status["active_cooldowns"] == 1

    @pytest.mark.asyncio
    async def test_get_status_redis_error(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        redis_mock.scan_iter = MagicMock(side_effect=Exception("err"))
        status = await mon.get_status()
        assert status == {"enabled": True, "baselines": 0}

    @pytest.mark.asyncio
    async def test_get_baseline_info_delegates(self, ha_mock, redis_mock, patch_deps):
        mon = _make_monitor(ha_mock, patch_deps)
        await mon.initialize(redis_mock)
        redis_mock.hgetall.return_value = {b"mean": b"20.0", b"stddev": b"2.0", b"samples": b"50"}
        result = await mon.get_baseline_info("sensor.t")
        assert result == {"mean": 20.0, "stddev": 2.0, "samples": 50}
