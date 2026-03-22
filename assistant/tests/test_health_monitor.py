"""
Tests fuer HealthMonitor — Raumklima-Ueberwachung, Alerts, Scoring.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.health_monitor import HealthMonitor, DEFAULTS


YAML_CFG = {
    "health_monitor": {
        "enabled": True,
        "check_interval_minutes": 10,
        "co2_warn": 1000,
        "co2_critical": 1500,
        "humidity_low": 30,
        "humidity_high": 70,
        "temp_low": 16,
        "temp_high": 27,
        "alert_cooldown_minutes": 60,
    },
    "humidor": {
        "enabled": False,
    },
}


@pytest.fixture
def ha():
    m = AsyncMock()
    m.get_states = AsyncMock(return_value=[])
    return m


@pytest.fixture
def redis_m():
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.set = AsyncMock()
    r.setex = AsyncMock()
    r.expire = AsyncMock()
    return r


@pytest.fixture
def monitor(ha, redis_m):
    with patch("assistant.health_monitor.yaml_config", YAML_CFG):
        hm = HealthMonitor(ha)
    hm.redis = redis_m
    return hm


# ── Init & Config ────────────────────────────────────────


class TestInit:
    def test_defaults_loaded(self, monitor):
        assert monitor.co2_warn == 1000
        assert monitor.co2_critical == 1500
        assert monitor.humidity_low == 30
        assert monitor.check_interval == 10

    def test_enabled(self, monitor):
        assert monitor.enabled

    @pytest.mark.asyncio
    async def test_initialize(self, monitor, redis_m):
        await monitor.initialize(redis_m)
        assert monitor.redis is redis_m

    def test_set_notify_callback(self, monitor):
        cb = AsyncMock()
        monitor.set_notify_callback(cb)
        assert monitor._notify_callback is cb


# ── CO2 Checks ───────────────────────────────────────────


class TestCO2:
    def test_co2_below_warn(self, monitor):
        assert monitor._check_co2("sensor.co2", "CO2", 800) is None

    def test_co2_warn(self, monitor):
        alert = monitor._check_co2("sensor.co2", "CO2", 1100)
        assert alert is not None
        assert alert["alert_type"] == "co2_warn"
        assert alert["urgency"] == "medium"

    def test_co2_critical(self, monitor):
        alert = monitor._check_co2("sensor.co2", "CO2", 1600)
        assert alert is not None
        assert alert["alert_type"] == "co2_critical"
        assert alert["urgency"] == "high"


# ── Humidity Checks ──────────────────────────────────────


class TestHumidity:
    def test_humidity_normal(self, monitor):
        assert monitor._check_humidity("sensor.h", "Luft", 50) is None

    def test_humidity_too_low(self, monitor):
        alert = monitor._check_humidity("sensor.h", "Luft", 20)
        assert alert is not None
        assert alert["alert_type"] == "humidity_low"

    def test_humidity_too_high(self, monitor):
        alert = monitor._check_humidity("sensor.h", "Luft", 80)
        assert alert is not None
        assert alert["alert_type"] == "humidity_high"


# ── Temperature Checks ──────────────────────────────────


class TestTemperature:
    def test_temp_normal(self, monitor):
        assert monitor._check_temperature("sensor.t", "Temp", 22) is None

    def test_temp_too_low(self, monitor):
        alert = monitor._check_temperature("sensor.t", "Temp", 14)
        assert alert is not None
        assert alert["alert_type"] == "temp_low"

    def test_temp_too_high(self, monitor):
        alert = monitor._check_temperature("sensor.t", "Temp", 30)
        assert alert is not None
        assert alert["alert_type"] == "temp_high"


# ── Humidor ──────────────────────────────────────────────


class TestHumidor:
    def test_humidor_normal(self, monitor):
        monitor.humidor_target = 70
        monitor.humidor_warn_below = 62
        monitor.humidor_warn_above = 75
        assert monitor._check_humidor("sensor.h", "Humidor", 68) is None

    def test_humidor_too_low(self, monitor):
        monitor.humidor_target = 70
        monitor.humidor_warn_below = 62
        monitor.humidor_warn_above = 75
        alert = monitor._check_humidor("sensor.h", "Humidor", 58)
        assert alert is not None
        assert alert["alert_type"] == "humidor_low"

    def test_humidor_too_high(self, monitor):
        monitor.humidor_target = 70
        monitor.humidor_warn_below = 62
        monitor.humidor_warn_above = 75
        alert = monitor._check_humidor("sensor.h", "Humidor", 80)
        assert alert is not None
        assert alert["alert_type"] == "humidor_high"


# ── Alert Cooldown ───────────────────────────────────────


class TestAlertCooldown:
    def test_make_alert_first_time(self, monitor):
        alert = monitor._make_alert("sensor.x", "co2_warn", "medium", "msg", {})
        assert alert is not None

    def test_make_alert_cooldown_active(self, monitor):
        # First call sets cooldown
        monitor._make_alert("sensor.x", "co2_warn", "medium", "msg", {})
        # Second call within cooldown returns None
        alert = monitor._make_alert("sensor.x", "co2_warn", "medium", "msg", {})
        assert alert is None

    def test_make_alert_different_type_no_cooldown(self, monitor):
        monitor._make_alert("sensor.x", "co2_warn", "medium", "msg", {})
        alert = monitor._make_alert("sensor.x", "co2_critical", "high", "msg2", {})
        assert alert is not None


# ── Scoring ──────────────────────────────────────────────


class TestScoring:
    def test_score_co2_excellent(self):
        assert HealthMonitor._score_co2(400) == 100

    def test_score_co2_bad(self):
        assert HealthMonitor._score_co2(2000) == 10

    def test_score_co2_moderate(self):
        assert HealthMonitor._score_co2(900) == 65

    def test_score_humidity_optimal(self):
        assert HealthMonitor._score_humidity(50) == 100

    def test_score_humidity_low(self):
        assert HealthMonitor._score_humidity(25) == 40

    def test_score_humidity_extreme(self):
        assert HealthMonitor._score_humidity(10) == 15

    def test_score_temperature_ideal(self):
        assert HealthMonitor._score_temperature(21) == 100

    def test_score_temperature_cool(self):
        assert HealthMonitor._score_temperature(19) == 75

    def test_score_temperature_extreme(self):
        assert HealthMonitor._score_temperature(10) == 25


# ── check_all ────────────────────────────────────────────


class TestCheckAll:
    @pytest.mark.asyncio
    async def test_check_all_empty_states(self, monitor, ha):
        ha.get_states.return_value = []
        alerts = await monitor.check_all()
        assert alerts == []

    @pytest.mark.asyncio
    async def test_check_all_co2_alert(self, monitor, ha):
        ha.get_states.return_value = [
            {
                "entity_id": "sensor.wohnzimmer_co2",
                "state": "1200",
                "attributes": {
                    "device_class": "carbon_dioxide",
                    "friendly_name": "CO2",
                },
            }
        ]
        alerts = await monitor.check_all()
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "co2_warn"

    @pytest.mark.asyncio
    async def test_check_all_excludes_heatpump(self, monitor, ha):
        ha.get_states.return_value = [
            {
                "entity_id": "sensor.aquarea_temperature",
                "state": "50",
                "attributes": {
                    "device_class": "temperature",
                    "friendly_name": "Aquarea Temp",
                },
            }
        ]
        alerts = await monitor.check_all()
        assert alerts == []

    @pytest.mark.asyncio
    async def test_check_all_non_numeric_skipped(self, monitor, ha):
        ha.get_states.return_value = [
            {
                "entity_id": "sensor.co2_status",
                "state": "unavailable",
                "attributes": {
                    "device_class": "carbon_dioxide",
                    "friendly_name": "CO2",
                },
            }
        ]
        alerts = await monitor.check_all()
        assert alerts == []


# ── get_status ───────────────────────────────────────────


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_get_status_empty(self, monitor, ha):
        ha.get_states.return_value = []
        status = await monitor.get_status()
        assert status["sensors"] == []
        assert status["score"] == 0

    @pytest.mark.asyncio
    async def test_get_status_with_sensors(self, monitor, ha):
        ha.get_states.return_value = [
            {
                "entity_id": "sensor.room_co2",
                "state": "500",
                "attributes": {
                    "device_class": "carbon_dioxide",
                    "friendly_name": "CO2",
                },
            },
            {
                "entity_id": "sensor.room_humidity",
                "state": "50",
                "attributes": {"device_class": "humidity", "friendly_name": "Luft"},
            },
        ]
        status = await monitor.get_status()
        assert len(status["sensors"]) == 2
        assert status["score"] > 0


# ── Hydration ────────────────────────────────────────────


class TestHydration:
    @pytest.mark.asyncio
    async def test_hydration_outside_hours(self, monitor, redis_m):
        with patch("assistant.health_monitor.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 1, 5, 0)  # 5 AM
            mock_dt.fromisoformat = datetime.fromisoformat
            result = await monitor._check_hydration()
        assert result is None

    @pytest.mark.asyncio
    async def test_hydration_no_redis(self, monitor):
        monitor.redis = None
        with patch("assistant.health_monitor.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 1, 12, 0)
            result = await monitor._check_hydration()
        assert result is None

    @pytest.mark.asyncio
    async def test_hydration_reminder_sent(self, monitor, redis_m):
        redis_m.get.return_value = None
        with patch("assistant.health_monitor.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 1, 12, 0)
            mock_dt.fromisoformat = datetime.fromisoformat
            result = await monitor._check_hydration()
        assert result is not None
        assert result["alert_type"] == "hydration_reminder"


# ── Send Alert ───────────────────────────────────────────


class TestSendAlert:
    @pytest.mark.asyncio
    async def test_send_alert_with_callback(self, monitor):
        cb = AsyncMock()
        monitor._notify_callback = cb
        alert = {"alert_type": "co2_warn", "urgency": "medium", "message": "Test"}
        await monitor._send_alert(alert)
        cb.assert_called_once_with("co2_warn", "medium", "Test")

    @pytest.mark.asyncio
    async def test_send_alert_no_callback(self, monitor):
        monitor._notify_callback = None
        alert = {"alert_type": "co2_warn", "urgency": "medium", "message": "Test"}
        await monitor._send_alert(alert)  # Should not raise


# ── Trend Summary ────────────────────────────────────────


class TestTrendSummary:
    @pytest.mark.asyncio
    async def test_trend_summary_no_redis(self, monitor):
        monitor.redis = None
        result = await monitor.get_trend_summary()
        assert result is None

    @pytest.mark.asyncio
    async def test_trend_summary_no_sensors(self, monitor, ha, redis_m):
        ha.get_states.return_value = []
        result = await monitor.get_trend_summary()
        assert result is None
