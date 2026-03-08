"""
Tests fuer TimeAwareness — Zeitgefuehl: Geraete-Laufzeiten, Zaehler, Kontext-Hints.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.time_awareness import (
    KEY_COUNTER,
    KEY_COUNTER_DATE,
    KEY_DEVICE_NOTIFIED,
    KEY_DEVICE_START,
    KEY_PC_SESSION,
    TimeAwareness,
)


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def ta(ha_mock):
    """TimeAwareness mit gemockter Config."""
    cfg = {
        "time_awareness": {
            "enabled": True,
            "check_interval_minutes": 5,
            "thresholds": {
                "oven": 60,
                "iron": 30,
                "light_empty_room": 30,
                "window_open_cold": 120,
                "pc_no_break": 360,
                "washer": 180,
                "dryer": 150,
                "dishwasher": 180,
            },
            "counters": {"coffee_machine": True},
        },
        "activity": {"entities": {"pc_sensors": ["sensor.pc_active"]}},
    }
    with patch("assistant.time_awareness.yaml_config", cfg):
        return TimeAwareness(ha_mock)


@pytest.fixture
def ta_with_redis(ta, redis_mock):
    """TimeAwareness mit Redis bereits initialisiert."""
    ta.redis = redis_mock
    return ta


# =====================================================================
# Constructor / Config
# =====================================================================


class TestTimeAwarenessInit:
    def test_default_thresholds(self, ta):
        assert ta.threshold_oven == 60
        assert ta.threshold_iron == 30
        assert ta.threshold_light_empty == 30
        assert ta.threshold_window_cold == 120
        assert ta.threshold_pc_no_break == 360
        assert ta.threshold_washer == 180
        assert ta.threshold_dryer == 150
        assert ta.threshold_dishwasher == 180

    def test_enabled_flag(self, ta):
        assert ta.enabled is True

    def test_coffee_tracking_enabled(self, ta):
        assert ta.track_coffee is True

    def test_disabled_config(self, ha_mock):
        cfg = {"time_awareness": {"enabled": False}}
        with patch("assistant.time_awareness.yaml_config", cfg):
            ta = TimeAwareness(ha_mock)
        assert ta.enabled is False


# =====================================================================
# get_counter_comment
# =====================================================================


class TestGetCounterComment:
    @pytest.mark.parametrize(
        "count, expected_fragment",
        [
            (2, "Zweiter Kaffee"),
            (3, "Kaffee Nummer drei"),
            (4, "Vier Kaffee"),
            (5, "Fuenfter Kaffee"),
        ],
    )
    def test_coffee_comments(self, ta, count, expected_fragment):
        result = ta.get_counter_comment("coffee", count)
        assert result is not None
        assert expected_fragment in result

    @pytest.mark.parametrize("count", [6, 7, 10, 99])
    def test_coffee_high_count(self, ta, count):
        result = ta.get_counter_comment("coffee", count)
        assert result is not None
        assert f"Kaffee Nummer {count}" in result
        assert "keine Empfehlung" in result

    def test_coffee_count_one_returns_none(self, ta):
        assert ta.get_counter_comment("coffee", 1) is None

    def test_coffee_count_zero_returns_none(self, ta):
        assert ta.get_counter_comment("coffee", 0) is None

    def test_non_coffee_counter_returns_none(self, ta):
        assert ta.get_counter_comment("tea", 5) is None

    def test_non_coffee_counter_high_count_returns_none(self, ta):
        assert ta.get_counter_comment("water", 10) is None


# =====================================================================
# increment_counter / get_counter
# =====================================================================


class TestCounters:
    @pytest.mark.asyncio
    async def test_increment_counter(self, ta_with_redis, redis_mock):
        redis_mock.incr.return_value = 3
        redis_mock.get.return_value = None  # no stored date triggers reset
        result = await ta_with_redis.increment_counter("coffee")
        assert result == 3
        redis_mock.incr.assert_called_with(KEY_COUNTER + "coffee")
        redis_mock.expire.assert_called()

    @pytest.mark.asyncio
    async def test_increment_counter_no_redis(self, ta):
        result = await ta.increment_counter("coffee")
        assert result == 0

    @pytest.mark.asyncio
    async def test_get_counter(self, ta_with_redis, redis_mock):
        redis_mock.get.return_value = "5"
        result = await ta_with_redis.get_counter("coffee")
        assert result == 5

    @pytest.mark.asyncio
    async def test_get_counter_no_value(self, ta_with_redis, redis_mock):
        redis_mock.get.return_value = None
        result = await ta_with_redis.get_counter("coffee")
        assert result == 0

    @pytest.mark.asyncio
    async def test_get_counter_no_redis(self, ta):
        result = await ta.get_counter("coffee")
        assert result == 0


# =====================================================================
# _check_appliance
# =====================================================================


class TestCheckAppliance:
    @pytest.mark.asyncio
    async def test_appliance_on_below_threshold(self, ta_with_redis, redis_mock):
        """Appliance running but under threshold - no alert."""
        redis_mock.get.return_value = None  # first check -> timer starts
        states = [{"entity_id": "switch.oven", "state": "on"}]
        result = await ta_with_redis._check_appliance(
            states, ["switch.oven"], 60, "oven", "Ofen laeuft seit {minutes} Minuten."
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_appliance_off_clears_timer(self, ta_with_redis, redis_mock):
        """Appliance off -> timer cleared."""
        states = [{"entity_id": "switch.oven", "state": "off"}]
        result = await ta_with_redis._check_appliance(
            states, ["switch.oven"], 60, "oven", "Ofen laeuft seit {minutes} Minuten."
        )
        assert result is None
        redis_mock.delete.assert_called()

    @pytest.mark.asyncio
    async def test_appliance_over_threshold_alert(self, ta_with_redis, redis_mock):
        """Appliance running over threshold and not notified -> alert."""
        past_ts = str(datetime.now().timestamp() - 3700)  # ~61 min ago
        redis_mock.get.return_value = past_ts
        redis_mock.exists.return_value = 0  # not notified yet
        states = [{"entity_id": "switch.oven", "state": "on"}]
        result = await ta_with_redis._check_appliance(
            states, ["switch.oven"], 60, "oven", "Ofen laeuft seit {minutes} Minuten."
        )
        assert result is not None
        assert result["type"] == "appliance_running"
        assert result["device"] == "oven"

    @pytest.mark.asyncio
    async def test_appliance_over_threshold_already_notified(self, ta_with_redis, redis_mock):
        """Appliance over threshold but already notified -> no alert."""
        past_ts = str(datetime.now().timestamp() - 3700)
        redis_mock.get.return_value = past_ts
        redis_mock.exists.return_value = 1  # already notified
        states = [{"entity_id": "switch.oven", "state": "on"}]
        result = await ta_with_redis._check_appliance(
            states, ["switch.oven"], 60, "oven", "Ofen laeuft seit {minutes} Minuten."
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_appliance_no_matching_entity(self, ta_with_redis, redis_mock):
        """No matching entity in states -> no alert."""
        states = [{"entity_id": "switch.something_else", "state": "on"}]
        result = await ta_with_redis._check_appliance(
            states, ["switch.oven"], 60, "oven", "Ofen laeuft."
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_appliance_heating_state(self, ta_with_redis, redis_mock):
        """Appliance with 'heating' state is considered active."""
        redis_mock.get.return_value = None
        states = [{"entity_id": "switch.oven", "state": "heating"}]
        result = await ta_with_redis._check_appliance(
            states, ["switch.oven"], 60, "oven", "Ofen seit {minutes} Min."
        )
        # First check starts timer, returns None (0 minutes)
        assert result is None
        # Verify timer was started in Redis
        redis_mock.set.assert_called()

    @pytest.mark.asyncio
    async def test_appliance_no_redis(self, ta, ha_mock):
        """No redis -> no alert (returns None)."""
        states = [{"entity_id": "switch.oven", "state": "on"}]
        result = await ta._check_appliance(
            states, ["switch.oven"], 60, "oven", "Ofen seit {minutes} Min."
        )
        assert result is None


# =====================================================================
# _check_pc_session
# =====================================================================


class TestCheckPcSession:
    @pytest.mark.asyncio
    async def test_pc_inactive_clears_session(self, ta_with_redis, redis_mock):
        cfg = {"activity": {"entities": {"pc_sensors": ["sensor.pc_active"]}}}
        with patch("assistant.time_awareness.yaml_config", cfg):
            states = [{"entity_id": "sensor.pc_active", "state": "off"}]
            result = await ta_with_redis._check_pc_session(states)
        assert result is None
        redis_mock.delete.assert_called()

    @pytest.mark.asyncio
    async def test_pc_active_under_threshold(self, ta_with_redis, redis_mock):
        cfg = {"activity": {"entities": {"pc_sensors": ["sensor.pc_active"]}}}
        redis_mock.get.return_value = None  # first check
        with patch("assistant.time_awareness.yaml_config", cfg):
            states = [{"entity_id": "sensor.pc_active", "state": "on"}]
            result = await ta_with_redis._check_pc_session(states)
        assert result is None

    @pytest.mark.asyncio
    async def test_pc_active_over_threshold_alert(self, ta_with_redis, redis_mock):
        cfg = {"activity": {"entities": {"pc_sensors": ["sensor.pc_active"]}}}
        past_ts = str(datetime.now().timestamp() - 360 * 60 - 60)  # > 360 min ago
        redis_mock.get.return_value = past_ts
        redis_mock.exists.return_value = 0
        with patch("assistant.time_awareness.yaml_config", cfg):
            states = [{"entity_id": "sensor.pc_active", "state": "on"}]
            result = await ta_with_redis._check_pc_session(states)
        assert result is not None
        assert result["type"] == "pc_no_break"
        assert "Stunden" in result["message"]

    @pytest.mark.asyncio
    async def test_pc_no_sensors_configured(self, ta_with_redis, redis_mock):
        cfg = {"activity": {"entities": {"pc_sensors": []}}}
        with patch("assistant.time_awareness.yaml_config", cfg):
            states = [{"entity_id": "sensor.pc_active", "state": "on"}]
            result = await ta_with_redis._check_pc_session(states)
        assert result is None


# =====================================================================
# get_context_hints
# =====================================================================


class TestGetContextHints:
    @pytest.mark.asyncio
    async def test_no_redis_returns_empty(self, ta):
        hints = await ta.get_context_hints()
        assert hints == []

    @pytest.mark.asyncio
    async def test_coffee_hint_when_count_gte_2(self, ta_with_redis, redis_mock):
        redis_mock.get.side_effect = lambda key: {
            KEY_COUNTER + "coffee": "3",
        }.get(key)
        hints = await ta_with_redis.get_context_hints()
        assert any("3 Kaffee" in h for h in hints)

    @pytest.mark.asyncio
    async def test_no_coffee_hint_when_count_lt_2(self, ta_with_redis, redis_mock):
        redis_mock.get.side_effect = lambda key: {
            KEY_COUNTER + "coffee": "1",
        }.get(key)
        hints = await ta_with_redis.get_context_hints()
        assert not any("Kaffee" in h for h in hints)

    @pytest.mark.asyncio
    async def test_pc_session_hint_over_2h(self, ta_with_redis, redis_mock):
        past_ts = str(datetime.now().timestamp() - 150 * 60)  # 150 min ago
        redis_mock.get.side_effect = lambda key: {
            KEY_COUNTER + "coffee": "0",
            KEY_DEVICE_START + "pc_session": past_ts,
        }.get(key)
        hints = await ta_with_redis.get_context_hints()
        assert any("PC" in h for h in hints)

    @pytest.mark.asyncio
    async def test_no_pc_hint_under_2h(self, ta_with_redis, redis_mock):
        past_ts = str(datetime.now().timestamp() - 60 * 60)  # 60 min ago
        redis_mock.get.side_effect = lambda key: {
            KEY_COUNTER + "coffee": "0",
            KEY_DEVICE_START + "pc_session": past_ts,
        }.get(key)
        hints = await ta_with_redis.get_context_hints()
        assert not any("PC" in h for h in hints)

    @pytest.mark.asyncio
    async def test_coffee_tracking_disabled(self, ha_mock, redis_mock):
        cfg = {
            "time_awareness": {
                "counters": {"coffee_machine": False},
            },
            "activity": {"entities": {"pc_sensors": []}},
        }
        with patch("assistant.time_awareness.yaml_config", cfg):
            ta = TimeAwareness(ha_mock)
        ta.redis = redis_mock
        redis_mock.get.return_value = None
        hints = await ta.get_context_hints()
        assert not any("Kaffee" in h for h in hints)


# =====================================================================
# Redis helpers
# =====================================================================


class TestRedisHelpers:
    @pytest.mark.asyncio
    async def test_was_notified_true(self, ta_with_redis, redis_mock):
        redis_mock.exists.return_value = 1
        assert await ta_with_redis._was_notified("oven") is True

    @pytest.mark.asyncio
    async def test_was_notified_false(self, ta_with_redis, redis_mock):
        redis_mock.exists.return_value = 0
        assert await ta_with_redis._was_notified("oven") is False

    @pytest.mark.asyncio
    async def test_was_notified_no_redis(self, ta):
        assert await ta._was_notified("oven") is False

    @pytest.mark.asyncio
    async def test_mark_notified(self, ta_with_redis, redis_mock):
        await ta_with_redis._mark_notified("oven")
        redis_mock.set.assert_called_with(KEY_DEVICE_NOTIFIED + "oven", "1")
        redis_mock.expire.assert_called_with(KEY_DEVICE_NOTIFIED + "oven", 3600)

    @pytest.mark.asyncio
    async def test_clear_device_timer(self, ta_with_redis, redis_mock):
        await ta_with_redis._clear_device_timer("oven")
        assert redis_mock.delete.call_count == 2

    @pytest.mark.asyncio
    async def test_get_running_minutes_first_check(self, ta_with_redis, redis_mock):
        redis_mock.get.return_value = None
        result = await ta_with_redis._get_running_minutes("switch.oven", "oven")
        assert result == 0.0
        redis_mock.set.assert_called()

    @pytest.mark.asyncio
    async def test_get_running_minutes_existing_timer(self, ta_with_redis, redis_mock):
        past_ts = str(datetime.now().timestamp() - 600)  # 10 min ago
        redis_mock.get.return_value = past_ts
        result = await ta_with_redis._get_running_minutes("switch.oven", "oven")
        assert result is not None
        assert 9.5 < result < 11.0  # ~10 minutes with tolerance

    @pytest.mark.asyncio
    async def test_get_running_minutes_invalid_value(self, ta_with_redis, redis_mock):
        redis_mock.get.return_value = "not-a-number"
        result = await ta_with_redis._get_running_minutes("switch.oven", "oven")
        assert result is None
        redis_mock.delete.assert_called()  # timer cleared

    @pytest.mark.asyncio
    async def test_get_running_minutes_no_redis(self, ta):
        result = await ta._get_running_minutes("switch.oven", "oven")
        assert result is None
