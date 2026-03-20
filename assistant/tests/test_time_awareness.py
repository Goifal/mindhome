"""
Tests fuer TimeAwareness — Zeitgefuehl: Geraete-Laufzeiten, Zaehler, Kontext-Hints.
"""

import asyncio
from datetime import datetime, timezone
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

    @pytest.mark.asyncio
    async def test_mark_notified_no_redis(self, ta):
        """mark_notified with no redis does nothing (no crash)."""
        await ta._mark_notified("oven")
        # No assertion needed — just verifying no exception

    @pytest.mark.asyncio
    async def test_clear_device_timer_no_redis(self, ta):
        """clear_device_timer with no redis does nothing (no crash)."""
        await ta._clear_device_timer("oven")


# =====================================================================
# Lifecycle: initialize, start, stop, set_notify_callback, set_ollama
# =====================================================================


class TestLifecycle:

    @pytest.mark.asyncio
    async def test_initialize_sets_redis(self, ta, redis_mock):
        redis_mock.get = AsyncMock(return_value=None)
        redis_mock.set = AsyncMock()
        await ta.initialize(redis_client=redis_mock)
        assert ta.redis is redis_mock

    @pytest.mark.asyncio
    async def test_initialize_without_redis(self, ta):
        await ta.initialize(redis_client=None)
        assert ta.redis is None

    def test_set_notify_callback(self, ta):
        cb = AsyncMock()
        ta.set_notify_callback(cb)
        assert ta._notify_callback is cb

    def test_set_ollama(self, ta):
        ollama = MagicMock()
        ta.set_ollama(ollama)
        assert ta._ollama is ollama

    @pytest.mark.asyncio
    async def test_start_disabled_no_task(self, ta):
        ta.enabled = False
        await ta.start()
        assert ta._task is None
        assert ta._running is False

    @pytest.mark.asyncio
    async def test_start_creates_task(self, ta):
        ta.enabled = True
        ta.redis = AsyncMock()
        # Mock _check_loop to avoid real loop
        with patch.object(ta, '_check_loop', new_callable=AsyncMock):
            await ta.start()
        assert ta._running is True
        assert ta._task is not None
        ta._task.cancel()
        try:
            await ta._task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, ta):
        ta._running = True
        ta._task = asyncio.create_task(asyncio.sleep(100))
        await ta.stop()
        assert ta._running is False
        assert ta._task.cancelled()

    @pytest.mark.asyncio
    async def test_stop_without_task(self, ta):
        ta._running = True
        ta._task = None
        await ta.stop()
        assert ta._running is False


# =====================================================================
# _reset_daily_counters_if_needed
# =====================================================================


class TestResetDailyCounters:

    @pytest.mark.asyncio
    async def test_no_redis_returns_early(self, ta):
        await ta._reset_daily_counters_if_needed()
        # No crash

    @pytest.mark.asyncio
    async def test_same_day_no_reset(self, ta_with_redis, redis_mock):
        """Same date stored — no counters deleted."""
        from assistant.time_awareness import _LOCAL_TZ
        today = datetime.now(_LOCAL_TZ).strftime("%Y-%m-%d")
        redis_mock.get = AsyncMock(return_value=today)
        await ta_with_redis._reset_daily_counters_if_needed()
        # set is called to (re-)store today's date
        redis_mock.set.assert_called_with(KEY_COUNTER_DATE, today)

    @pytest.mark.asyncio
    async def test_new_day_resets_counters(self, ta_with_redis, redis_mock):
        """Different date stored — counters deleted."""
        redis_mock.get = AsyncMock(return_value="2020-01-01")

        # Mock scan_iter to return some counter keys
        async def mock_scan_iter(pattern):
            for key in [f"{KEY_COUNTER}coffee", f"{KEY_COUNTER}tea"]:
                yield key

        redis_mock.scan_iter = mock_scan_iter
        await ta_with_redis._reset_daily_counters_if_needed()
        redis_mock.delete.assert_called()

    @pytest.mark.asyncio
    async def test_first_day_no_stored_date(self, ta_with_redis, redis_mock):
        """No stored date — just stores today, no deletion."""
        redis_mock.get = AsyncMock(return_value=None)
        await ta_with_redis._reset_daily_counters_if_needed()
        redis_mock.set.assert_called()

    @pytest.mark.asyncio
    async def test_bytes_date_decoded(self, ta_with_redis, redis_mock):
        """Redis returns bytes for date — decoded correctly."""
        from assistant.time_awareness import _LOCAL_TZ
        today = datetime.now(_LOCAL_TZ).strftime("%Y-%m-%d")
        redis_mock.get = AsyncMock(return_value=today.encode())
        await ta_with_redis._reset_daily_counters_if_needed()
        redis_mock.set.assert_called_with(KEY_COUNTER_DATE, today)


# =====================================================================
# _send_alert
# =====================================================================


class TestSendAlert:

    @pytest.mark.asyncio
    async def test_send_with_callback(self, ta_with_redis):
        callback = AsyncMock()
        ta_with_redis._notify_callback = callback
        alert = {"type": "appliance_running", "device": "oven",
                 "message": "Ofen laeuft seit 65 Minuten.", "urgency": "medium"}
        await ta_with_redis._send_alert(alert)
        callback.assert_called_once_with(alert)

    @pytest.mark.asyncio
    async def test_send_without_callback(self, ta_with_redis):
        ta_with_redis._notify_callback = None
        alert = {"type": "test", "message": "test msg"}
        # Should not raise
        await ta_with_redis._send_alert(alert)

    @pytest.mark.asyncio
    async def test_callback_exception_handled(self, ta_with_redis):
        ta_with_redis._notify_callback = AsyncMock(side_effect=RuntimeError("oops"))
        alert = {"type": "test", "message": "test msg"}
        await ta_with_redis._send_alert(alert)
        # No exception propagated


# =====================================================================
# _llm_rewrite_alert
# =====================================================================


class TestLLMRewriteAlert:

    @pytest.mark.asyncio
    async def test_no_ollama_returns_original(self, ta_with_redis):
        ta_with_redis._ollama = None
        result = await ta_with_redis._llm_rewrite_alert("Test alert", "appliance_running")
        assert result == "Test alert"

    @pytest.mark.asyncio
    async def test_llm_disabled_returns_original(self, ta_with_redis):
        ta_with_redis._ollama = AsyncMock()
        cfg = {"time_awareness": {"llm_rewrite": False}}
        with patch("assistant.time_awareness.yaml_config", cfg):
            result = await ta_with_redis._llm_rewrite_alert("Test alert", "appliance_running")
        assert result == "Test alert"

    @pytest.mark.asyncio
    async def test_llm_rewrite_success(self, ta_with_redis):
        ta_with_redis._ollama = AsyncMock()
        ta_with_redis._ollama.generate = AsyncMock(return_value="Rewritten alert message here.")
        cfg = {"time_awareness": {"llm_rewrite": True}}
        with patch("assistant.time_awareness.yaml_config", cfg), \
             patch("assistant.config.settings", MagicMock(model_fast="test-model")), \
             patch("assistant.ollama_client.strip_think_tags", return_value="Rewritten alert message here."):
            result = await ta_with_redis._llm_rewrite_alert(
                "Der Ofen laeuft seit 65 Minuten.", "appliance_running"
            )
        assert result == "Rewritten alert message here."

    @pytest.mark.asyncio
    async def test_llm_error_returns_original(self, ta_with_redis):
        ta_with_redis._ollama = AsyncMock()
        ta_with_redis._ollama.generate = AsyncMock(side_effect=RuntimeError("fail"))
        cfg = {"time_awareness": {"llm_rewrite": True}}
        original = "Der Ofen laeuft seit 65 Minuten."
        with patch("assistant.time_awareness.yaml_config", cfg), \
             patch("assistant.config.settings", MagicMock(model_fast="test-model")):
            result = await ta_with_redis._llm_rewrite_alert(original, "appliance_running")
        assert result == original

    @pytest.mark.asyncio
    async def test_llm_empty_response_returns_original(self, ta_with_redis):
        ta_with_redis._ollama = AsyncMock()
        ta_with_redis._ollama.generate = AsyncMock(return_value="")
        cfg = {"time_awareness": {"llm_rewrite": True}}
        original = "Der Ofen laeuft seit 65 Minuten."
        with patch("assistant.time_awareness.yaml_config", cfg), \
             patch("assistant.config.settings", MagicMock(model_fast="test-model")), \
             patch("assistant.ollama_client.strip_think_tags", return_value=""):
            result = await ta_with_redis._llm_rewrite_alert(original, "appliance_running")
        assert result == original


# =====================================================================
# _check_lights_empty_rooms
# =====================================================================


class TestCheckLightsEmptyRooms:

    @pytest.fixture
    def ta_lights(self, ha_mock, redis_mock):
        cfg = {
            "time_awareness": {
                "enabled": True,
                "thresholds": {"light_empty_room": 30},
            },
            "lighting": {"enabled": True},
            "multi_room": {"room_motion_sensors": {
                "wohnzimmer": "binary_sensor.motion_wohnzimmer",
            }},
            "activity": {"entities": {"pc_sensors": []}},
        }
        with patch("assistant.time_awareness.yaml_config", cfg):
            ta = TimeAwareness(ha_mock)
        ta.redis = redis_mock
        return ta

    @pytest.mark.asyncio
    async def test_lighting_disabled_returns_empty(self, ha_mock, redis_mock):
        cfg = {
            "time_awareness": {"enabled": True, "thresholds": {"light_empty_room": 30}},
            "lighting": {"enabled": False},
            "activity": {"entities": {"pc_sensors": []}},
        }
        with patch("assistant.time_awareness.yaml_config", cfg):
            ta = TimeAwareness(ha_mock)
        ta.redis = redis_mock
        result = await ta._check_lights_empty_rooms([])
        assert result == []

    @pytest.mark.asyncio
    async def test_light_in_active_room_no_alert(self, ta_lights, redis_mock):
        """Light on in room with motion — no alert."""
        states = [
            {"entity_id": "binary_sensor.motion_wohnzimmer", "state": "on"},
            {"entity_id": "light.wohnzimmer_decke", "state": "on",
             "attributes": {"friendly_name": "Wohnzimmer Decke"}},
        ]
        with patch("assistant.config.get_room_profiles",
                    return_value={"rooms": {"wohnzimmer": {"light_entities": ["light.wohnzimmer_decke"]}}}):
            result = await ta_lights._check_lights_empty_rooms(states)
        assert result == []

    @pytest.mark.asyncio
    async def test_light_in_empty_room_over_threshold(self, ta_lights, redis_mock):
        """Light on in empty room over threshold — alert (no auto-off)."""
        past_ts = str(datetime.now().timestamp() - 1900)  # ~31 min ago
        redis_mock.get.return_value = past_ts
        redis_mock.exists.return_value = 0  # not notified yet

        cfg = {
            "time_awareness": {"enabled": True, "thresholds": {"light_empty_room": 30}},
            "lighting": {"enabled": True},  # no auto_off_empty_room_minutes
            "multi_room": {"room_motion_sensors": {}},
            "activity": {"entities": {"pc_sensors": []}},
        }
        states = [
            {"entity_id": "light.kueche_decke", "state": "on",
             "attributes": {"friendly_name": "Kueche Decke"}},
        ]
        with patch("assistant.time_awareness.yaml_config", cfg), \
             patch("assistant.config.get_room_profiles",
                   return_value={"rooms": {"kueche": {"light_entities": ["light.kueche_decke"]}}}):
            result = await ta_lights._check_lights_empty_rooms(states)
        assert len(result) == 1
        assert result[0]["type"] == "light_empty_room"
        assert "Kueche Decke" in result[0]["message"]

    @pytest.mark.asyncio
    async def test_light_off_no_alert(self, ta_lights, redis_mock):
        """Light off — no alert."""
        states = [
            {"entity_id": "light.kueche", "state": "off"},
        ]
        with patch("assistant.config.get_room_profiles",
                    return_value={"rooms": {}}):
            result = await ta_lights._check_lights_empty_rooms(states)
        assert result == []

    @pytest.mark.asyncio
    async def test_light_auto_off_when_configured(self, ta_lights, ha_mock, redis_mock):
        """When auto_off_empty_room_minutes is set, light is turned off."""
        past_ts = str(datetime.now().timestamp() - 1900)
        redis_mock.get.return_value = past_ts
        redis_mock.exists.return_value = 0

        cfg = {
            "time_awareness": {"enabled": True, "thresholds": {"light_empty_room": 30}},
            "lighting": {"enabled": True, "auto_off_empty_room_minutes": 30, "default_transition": 2},
            "multi_room": {"room_motion_sensors": {}},
            "activity": {"entities": {"pc_sensors": []}},
        }

        states = [
            {"entity_id": "light.bad_decke", "state": "on",
             "attributes": {"friendly_name": "Bad Decke"}},
        ]
        with patch("assistant.time_awareness.yaml_config", cfg), \
             patch("assistant.config.get_room_profiles",
                   return_value={"rooms": {"bad": {"light_entities": ["light.bad_decke"]}}}):
            result = await ta_lights._check_lights_empty_rooms(states)

        assert len(result) == 1
        assert result[0]["type"] == "light_auto_off"
        ha_mock.call_service.assert_called_once()

    @pytest.mark.asyncio
    async def test_light_already_notified_no_alert(self, ta_lights, redis_mock):
        """Light already notified — no duplicate alert."""
        past_ts = str(datetime.now().timestamp() - 1900)
        redis_mock.get.return_value = past_ts
        redis_mock.exists.return_value = 1  # already notified

        states = [
            {"entity_id": "light.kueche_decke", "state": "on",
             "attributes": {"friendly_name": "Kueche Decke"}},
        ]
        with patch("assistant.config.get_room_profiles",
                    return_value={"rooms": {"kueche": {"light_entities": ["light.kueche_decke"]}}}):
            result = await ta_lights._check_lights_empty_rooms(states)
        assert result == []


# =====================================================================
# _check_windows_cold
# =====================================================================


class TestCheckWindowsCold:

    @pytest.fixture
    def ta_windows(self, ha_mock, redis_mock):
        cfg = {
            "time_awareness": {
                "enabled": True,
                "thresholds": {"window_open_cold": 120},
            },
            "activity": {"entities": {"pc_sensors": []}},
        }
        with patch("assistant.time_awareness.yaml_config", cfg):
            ta = TimeAwareness(ha_mock)
        ta.redis = redis_mock
        return ta

    @pytest.mark.asyncio
    async def test_no_weather_data_returns_empty(self, ta_windows):
        """No weather entity — no alerts."""
        states = [
            {"entity_id": "binary_sensor.window_kitchen", "state": "on"},
        ]
        with patch("assistant.function_calling.is_heating_relevant_opening", return_value=True), \
             patch("assistant.function_calling.get_opening_type", return_value="window"):
            result = await ta_windows._check_windows_cold(states)
        assert result == []

    @pytest.mark.asyncio
    async def test_warm_temperature_no_alert(self, ta_windows):
        """Outside temp >= 10 — no alerts."""
        states = [
            {"entity_id": "weather.home", "state": "sunny",
             "attributes": {"temperature": 15}},
            {"entity_id": "binary_sensor.window_kitchen", "state": "on",
             "attributes": {"friendly_name": "Kitchen Window"}},
        ]
        result = await ta_windows._check_windows_cold(states)
        assert result == []

    @pytest.mark.asyncio
    async def test_cold_window_open_over_threshold(self, ta_windows, redis_mock):
        """Cold weather + window open > threshold — alert."""
        past_ts = str(datetime.now().timestamp() - 7300)  # ~121 min
        redis_mock.get.return_value = past_ts
        redis_mock.exists.return_value = 0

        states = [
            {"entity_id": "weather.home", "state": "cloudy",
             "attributes": {"temperature": 2}},
            {"entity_id": "binary_sensor.window_kitchen", "state": "on",
             "attributes": {"friendly_name": "Kueche Fenster"}},
        ]
        with patch("assistant.function_calling.is_heating_relevant_opening", return_value=True), \
             patch("assistant.function_calling.get_opening_type", return_value="window"):
            result = await ta_windows._check_windows_cold(states)

        assert len(result) == 1
        assert result[0]["type"] == "window_open_cold"
        assert "2°C" in result[0]["message"]
        assert result[0]["urgency"] == "medium"

    @pytest.mark.asyncio
    async def test_window_closed_no_alert(self, ta_windows):
        """Window closed — no alert."""
        states = [
            {"entity_id": "weather.home", "state": "cloudy",
             "attributes": {"temperature": 2}},
            {"entity_id": "binary_sensor.window_kitchen", "state": "off",
             "attributes": {"friendly_name": "Kueche Fenster"}},
        ]
        with patch("assistant.function_calling.is_heating_relevant_opening", return_value=True), \
             patch("assistant.function_calling.get_opening_type", return_value="window"):
            result = await ta_windows._check_windows_cold(states)
        assert result == []

    @pytest.mark.asyncio
    async def test_door_type_label(self, ta_windows, redis_mock):
        """Door opening uses 'Eine Tuer' label."""
        past_ts = str(datetime.now().timestamp() - 7300)
        redis_mock.get.return_value = past_ts
        redis_mock.exists.return_value = 0

        states = [
            {"entity_id": "weather.home", "state": "cloudy",
             "attributes": {"temperature": -5}},
            {"entity_id": "binary_sensor.door_front", "state": "on",
             "attributes": {"friendly_name": "Haustuer"}},
        ]
        with patch("assistant.function_calling.is_heating_relevant_opening", return_value=True), \
             patch("assistant.function_calling.get_opening_type", return_value="door"):
            result = await ta_windows._check_windows_cold(states)

        assert len(result) == 1
        assert "Tuer" in result[0]["message"]

    @pytest.mark.asyncio
    async def test_outdoor_temp_sensor_fallback(self, ta_windows, redis_mock):
        """Outdoor temperature sensor (non-weather entity) used as fallback."""
        past_ts = str(datetime.now().timestamp() - 7300)
        redis_mock.get.return_value = past_ts
        redis_mock.exists.return_value = 0

        states = [
            {"entity_id": "sensor.outdoor_temperature", "state": "3",
             "attributes": {}},
            {"entity_id": "binary_sensor.window_bedroom", "state": "on",
             "attributes": {"friendly_name": "Schlafzimmer Fenster"}},
        ]
        with patch("assistant.function_calling.is_heating_relevant_opening", return_value=True), \
             patch("assistant.function_calling.get_opening_type", return_value="window"):
            result = await ta_windows._check_windows_cold(states)

        assert len(result) == 1
        assert result[0]["type"] == "window_open_cold"


# =====================================================================
# _check_heating_window_open
# =====================================================================


class TestCheckHeatingWindowOpen:

    @pytest.fixture
    def ta_heat(self, ha_mock, redis_mock):
        cfg = {
            "time_awareness": {"enabled": True},
            "activity": {"entities": {"pc_sensors": []}},
        }
        with patch("assistant.time_awareness.yaml_config", cfg):
            ta = TimeAwareness(ha_mock)
        ta.redis = redis_mock
        return ta

    @pytest.mark.asyncio
    async def test_no_heating_active(self, ta_heat):
        """No climate entity heating — no alerts."""
        states = [
            {"entity_id": "climate.living_room", "state": "off",
             "attributes": {"hvac_action": "idle"}},
        ]
        result = await ta_heat._check_heating_window_open(states)
        assert result == []

    @pytest.mark.asyncio
    async def test_heating_active_window_open(self, ta_heat, redis_mock):
        """Heating active + window open — alert."""
        redis_mock.exists.return_value = 0  # not notified

        states = [
            {"entity_id": "climate.wohnzimmer", "state": "heat",
             "attributes": {"hvac_action": "heating", "friendly_name": "Wohnzimmer"}},
            {"entity_id": "binary_sensor.window_wohnzimmer", "state": "on",
             "attributes": {"friendly_name": "Wohnzimmer Fenster"}},
        ]
        with patch("assistant.function_calling.is_heating_relevant_opening", return_value=True), \
             patch("assistant.function_calling.get_opening_type", return_value="window"):
            result = await ta_heat._check_heating_window_open(states)

        assert len(result) == 1
        assert result[0]["type"] == "heating_window_open"
        assert "Fenster" in result[0]["message"]
        assert "Heizung" in result[0]["message"]

    @pytest.mark.asyncio
    async def test_heating_active_window_closed(self, ta_heat):
        """Heating active + window closed — no alert."""
        states = [
            {"entity_id": "climate.wohnzimmer", "state": "heat",
             "attributes": {"hvac_action": "heating", "friendly_name": "Wohnzimmer"}},
            {"entity_id": "binary_sensor.window_wohnzimmer", "state": "off",
             "attributes": {"friendly_name": "Wohnzimmer Fenster"}},
        ]
        with patch("assistant.function_calling.is_heating_relevant_opening", return_value=True), \
             patch("assistant.function_calling.get_opening_type", return_value="window"):
            result = await ta_heat._check_heating_window_open(states)
        assert result == []

    @pytest.mark.asyncio
    async def test_heating_already_notified(self, ta_heat, redis_mock):
        """Already notified — no duplicate alert."""
        redis_mock.exists.return_value = 1  # already notified

        states = [
            {"entity_id": "climate.wohnzimmer", "state": "heat",
             "attributes": {"hvac_action": "heating", "friendly_name": "Wohnzimmer"}},
            {"entity_id": "binary_sensor.window_wohnzimmer", "state": "on",
             "attributes": {"friendly_name": "Wohnzimmer Fenster"}},
        ]
        with patch("assistant.function_calling.is_heating_relevant_opening", return_value=True), \
             patch("assistant.function_calling.get_opening_type", return_value="window"):
            result = await ta_heat._check_heating_window_open(states)
        assert result == []

    @pytest.mark.asyncio
    async def test_non_relevant_opening_ignored(self, ta_heat, redis_mock):
        """Non-heating-relevant opening (e.g. gate) ignored."""
        redis_mock.exists.return_value = 0

        states = [
            {"entity_id": "climate.wohnzimmer", "state": "heat",
             "attributes": {"hvac_action": "heating", "friendly_name": "Wohnzimmer"}},
            {"entity_id": "binary_sensor.gate", "state": "on",
             "attributes": {"friendly_name": "Garage Gate"}},
        ]
        with patch("assistant.function_calling.is_heating_relevant_opening", return_value=False):
            result = await ta_heat._check_heating_window_open(states)
        assert result == []

    @pytest.mark.asyncio
    async def test_door_type_label(self, ta_heat, redis_mock):
        """Door opening uses 'Eine Tuer' in message."""
        redis_mock.exists.return_value = 0

        states = [
            {"entity_id": "climate.flur", "state": "heat",
             "attributes": {"hvac_action": "heating", "friendly_name": "Flur"}},
            {"entity_id": "binary_sensor.door_front", "state": "on",
             "attributes": {"friendly_name": "Haustuer"}},
        ]
        with patch("assistant.function_calling.is_heating_relevant_opening", return_value=True), \
             patch("assistant.function_calling.get_opening_type", return_value="door"):
            result = await ta_heat._check_heating_window_open(states)

        assert len(result) == 1
        assert "Tuer" in result[0]["message"]


# =====================================================================
# _run_checks (integration)
# =====================================================================


class TestRunChecks:

    @pytest.fixture
    def ta_full(self, ha_mock, redis_mock):
        cfg = {
            "time_awareness": {
                "enabled": True,
                "check_interval_minutes": 5,
                "thresholds": {
                    "oven": 60, "iron": 30, "light_empty_room": 30,
                    "window_open_cold": 120, "pc_no_break": 360,
                    "washer": 180, "dryer": 150, "dishwasher": 180,
                },
                "counters": {"coffee_machine": True},
            },
            "lighting": {"enabled": True},
            "multi_room": {"room_motion_sensors": {}},
            "activity": {"entities": {"pc_sensors": []}},
        }
        with patch("assistant.time_awareness.yaml_config", cfg):
            ta = TimeAwareness(ha_mock)
        ta.redis = redis_mock
        ta._notify_callback = AsyncMock()
        return ta

    @pytest.mark.asyncio
    async def test_run_checks_no_states(self, ta_full, ha_mock):
        """When HA returns no states, no alerts."""
        ha_mock.get_states = AsyncMock(return_value=None)
        await ta_full._run_checks()
        ta_full._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_checks_empty_states(self, ta_full, ha_mock, redis_mock):
        """Empty states list — no alerts."""
        ha_mock.get_states = AsyncMock(return_value=[])
        redis_mock.get = AsyncMock(return_value=None)
        with patch("assistant.config.get_room_profiles",
                    return_value={"rooms": {}}):
            await ta_full._run_checks()
        ta_full._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_checks_with_oven_alert(self, ta_full, ha_mock, redis_mock):
        """Oven running 65 min produces alert sent via callback."""
        past_ts = str(datetime.now().timestamp() - 3900)  # ~65 min
        redis_mock.get.return_value = past_ts
        redis_mock.exists.return_value = 0

        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "switch.oven", "state": "on"},
        ])
        with patch("assistant.config.get_room_profiles",
                    return_value={"rooms": {}}):
            await ta_full._run_checks()

        ta_full._notify_callback.assert_called()
        alert = ta_full._notify_callback.call_args[0][0]
        assert alert["type"] == "appliance_running"
        assert alert["device"] == "oven"


# =====================================================================
# _check_pc_session edge cases
# =====================================================================


class TestCheckPcSessionExtended:

    @pytest.mark.asyncio
    async def test_pc_with_active_state(self, ta_with_redis, redis_mock):
        """PC sensor with 'active' state is recognized."""
        cfg = {"activity": {"entities": {"pc_sensors": ["sensor.pc_active"]}}}
        redis_mock.get.return_value = None
        with patch("assistant.time_awareness.yaml_config", cfg):
            states = [{"entity_id": "sensor.pc_active", "state": "active"}]
            result = await ta_with_redis._check_pc_session(states)
        # First check — timer started, no alert yet
        assert result is None
        redis_mock.set.assert_called()

    @pytest.mark.asyncio
    async def test_pc_already_notified_no_duplicate(self, ta_with_redis, redis_mock):
        """PC over threshold but already notified — no alert."""
        cfg = {"activity": {"entities": {"pc_sensors": ["sensor.pc_active"]}}}
        past_ts = str(datetime.now().timestamp() - 360 * 60 - 60)
        redis_mock.get.return_value = past_ts
        redis_mock.exists.return_value = 1  # already notified
        with patch("assistant.time_awareness.yaml_config", cfg):
            states = [{"entity_id": "sensor.pc_active", "state": "on"}]
            result = await ta_with_redis._check_pc_session(states)
        assert result is None

    @pytest.mark.asyncio
    async def test_pc_message_contains_hours(self, ta_with_redis, redis_mock):
        """PC alert message contains hour count."""
        cfg = {"activity": {"entities": {"pc_sensors": ["sensor.pc_active"]}}}
        past_ts = str(datetime.now().timestamp() - 7 * 3600)  # 7h
        redis_mock.get.return_value = past_ts
        redis_mock.exists.return_value = 0
        with patch("assistant.time_awareness.yaml_config", cfg):
            states = [{"entity_id": "sensor.pc_active", "state": "on"}]
            result = await ta_with_redis._check_pc_session(states)
        assert result is not None
        assert "7 Stunden" in result["message"]


# =====================================================================
# Multiple appliance types
# =====================================================================


class TestMultipleApplianceTypes:

    @pytest.mark.asyncio
    async def test_washer_alert(self, ta_with_redis, redis_mock):
        """Washer running 185 min produces alert."""
        past_ts = str(datetime.now().timestamp() - 185 * 60)
        redis_mock.get.return_value = past_ts
        redis_mock.exists.return_value = 0
        states = [{"entity_id": "switch.waschmaschine", "state": "on"}]
        result = await ta_with_redis._check_appliance(
            states, ["switch.waschmaschine"], 180, "washer",
            "Waschmaschine laeuft seit {minutes} Minuten."
        )
        assert result is not None
        assert result["device"] == "washer"

    @pytest.mark.asyncio
    async def test_dryer_alert(self, ta_with_redis, redis_mock):
        """Dryer running 155 min produces alert."""
        past_ts = str(datetime.now().timestamp() - 155 * 60)
        redis_mock.get.return_value = past_ts
        redis_mock.exists.return_value = 0
        states = [{"entity_id": "switch.trockner", "state": "active"}]
        result = await ta_with_redis._check_appliance(
            states, ["switch.trockner"], 150, "dryer",
            "Trockner laeuft seit {minutes} Minuten."
        )
        assert result is not None
        assert result["device"] == "dryer"

    @pytest.mark.asyncio
    async def test_dishwasher_alert(self, ta_with_redis, redis_mock):
        """Dishwasher running 185 min produces alert."""
        past_ts = str(datetime.now().timestamp() - 185 * 60)
        redis_mock.get.return_value = past_ts
        redis_mock.exists.return_value = 0
        states = [{"entity_id": "switch.geschirrspueler", "state": "on"}]
        result = await ta_with_redis._check_appliance(
            states, ["switch.geschirrspueler"], 180, "dishwasher",
            "Geschirrspueler laeuft seit {minutes} Minuten."
        )
        assert result is not None
        assert result["device"] == "dishwasher"


# =====================================================================
# _run_checks — full integration covering all appliance branches
# =====================================================================


class TestRunChecksIntegration:
    """Cover the remaining _run_checks branches: iron, washer, dryer,
    dishwasher, lights, pc_session alert appends, and _send_alert loop."""

    @pytest.fixture
    def ta_int(self, ha_mock, redis_mock):
        cfg = {
            "time_awareness": {
                "enabled": True,
                "check_interval_minutes": 5,
                "thresholds": {
                    "oven": 60, "iron": 30, "light_empty_room": 30,
                    "window_open_cold": 120, "pc_no_break": 360,
                    "washer": 180, "dryer": 150, "dishwasher": 180,
                },
                "counters": {"coffee_machine": True},
            },
            "lighting": {"enabled": True},
            "multi_room": {"room_motion_sensors": {}},
            "activity": {"entities": {"pc_sensors": ["sensor.pc_active"]}},
        }
        with patch("assistant.time_awareness.yaml_config", cfg):
            ta = TimeAwareness(ha_mock)
        ta.redis = redis_mock
        ta._notify_callback = AsyncMock()
        return ta

    @pytest.mark.asyncio
    async def test_run_checks_iron_alert(self, ta_int, ha_mock, redis_mock):
        """Iron running over threshold via _run_checks sends alert."""
        past_ts = str(datetime.now().timestamp() - 35 * 60)
        redis_mock.get.return_value = past_ts
        redis_mock.exists.return_value = 0
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "switch.buegeleisen", "state": "on"},
        ])
        with patch("assistant.config.get_room_profiles", return_value={"rooms": {}}):
            await ta_int._run_checks()
        ta_int._notify_callback.assert_called()
        alert = ta_int._notify_callback.call_args[0][0]
        assert alert["device"] == "iron"

    @pytest.mark.asyncio
    async def test_run_checks_washer_alert(self, ta_int, ha_mock, redis_mock):
        """Washer running over threshold via _run_checks sends alert."""
        past_ts = str(datetime.now().timestamp() - 185 * 60)
        redis_mock.get.return_value = past_ts
        redis_mock.exists.return_value = 0
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "switch.waschmaschine", "state": "on"},
        ])
        with patch("assistant.config.get_room_profiles", return_value={"rooms": {}}):
            await ta_int._run_checks()
        ta_int._notify_callback.assert_called()
        alert = ta_int._notify_callback.call_args[0][0]
        assert alert["device"] == "washer"

    @pytest.mark.asyncio
    async def test_run_checks_dryer_alert(self, ta_int, ha_mock, redis_mock):
        """Dryer running over threshold via _run_checks sends alert."""
        past_ts = str(datetime.now().timestamp() - 155 * 60)
        redis_mock.get.return_value = past_ts
        redis_mock.exists.return_value = 0
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "switch.trockner", "state": "active"},
        ])
        with patch("assistant.config.get_room_profiles", return_value={"rooms": {}}):
            await ta_int._run_checks()
        ta_int._notify_callback.assert_called()
        alert = ta_int._notify_callback.call_args[0][0]
        assert alert["device"] == "dryer"

    @pytest.mark.asyncio
    async def test_run_checks_dishwasher_alert(self, ta_int, ha_mock, redis_mock):
        """Dishwasher running over threshold via _run_checks sends alert."""
        past_ts = str(datetime.now().timestamp() - 185 * 60)
        redis_mock.get.return_value = past_ts
        redis_mock.exists.return_value = 0
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "switch.geschirrspueler", "state": "on"},
        ])
        with patch("assistant.config.get_room_profiles", return_value={"rooms": {}}):
            await ta_int._run_checks()
        ta_int._notify_callback.assert_called()
        alert = ta_int._notify_callback.call_args[0][0]
        assert alert["device"] == "dishwasher"

    @pytest.mark.asyncio
    async def test_run_checks_pc_session_alert(self, ta_int, ha_mock, redis_mock):
        """PC session over threshold via _run_checks sends alert."""
        from assistant.time_awareness import KEY_COUNTER_DATE, _LOCAL_TZ
        past_ts = str(datetime.now().timestamp() - 7 * 3600)
        today = datetime.now(_LOCAL_TZ).strftime("%Y-%m-%d")
        redis_mock.get.side_effect = lambda key: {
            KEY_COUNTER_DATE: today,
        }.get(key, past_ts)
        redis_mock.exists.return_value = 0
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "sensor.pc_active", "state": "on"},
        ])
        # Must also patch yaml_config during _run_checks so _check_pc_session
        # reads the right pc_sensors list
        run_cfg = {
            "time_awareness": {"enabled": True, "thresholds": {}, "counters": {}},
            "lighting": {"enabled": True},
            "multi_room": {"room_motion_sensors": {}},
            "activity": {"entities": {"pc_sensors": ["sensor.pc_active"]}},
        }
        with patch("assistant.config.get_room_profiles", return_value={"rooms": {}}), \
             patch("assistant.function_calling.is_heating_relevant_opening", return_value=False), \
             patch("assistant.time_awareness.yaml_config", run_cfg):
            await ta_int._run_checks()
        ta_int._notify_callback.assert_called()
        alert = ta_int._notify_callback.call_args[0][0]
        assert alert["type"] == "pc_no_break"

    @pytest.mark.asyncio
    async def test_run_checks_light_alerts_extended(self, ta_int, ha_mock, redis_mock):
        """Light alerts from _check_lights_empty_rooms are added to alerts list."""
        redis_mock.get.return_value = None
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "switch.nothing", "state": "off"},
        ])
        light_alert = {"type": "light_empty_room", "device": "light_kitchen",
                        "message": "Light on", "urgency": "low"}
        with patch.object(ta_int, "_check_lights_empty_rooms",
                          new_callable=AsyncMock, return_value=[light_alert]):
            await ta_int._run_checks()
        ta_int._notify_callback.assert_called()
        sent = ta_int._notify_callback.call_args[0][0]
        assert sent["type"] == "light_empty_room"


# =====================================================================
# _check_lights_empty_rooms — deeper branch coverage
# =====================================================================


class TestCheckLightsEmptyRoomsDeep:
    """Cover uncovered branches: invalid auto_off_minutes, motion_to_room
    mapping, heuristic motion sensor detection, person zone, manual override,
    and auto-off service failure fallback."""

    @pytest.fixture
    def ta_ld(self, ha_mock, redis_mock):
        cfg = {
            "time_awareness": {
                "enabled": True,
                "thresholds": {"light_empty_room": 30},
            },
            "lighting": {"enabled": True},
            "multi_room": {"room_motion_sensors": {
                "kitchen": "binary_sensor.motion_kitchen",
            }},
            "activity": {"entities": {"pc_sensors": []}},
        }
        with patch("assistant.time_awareness.yaml_config", cfg):
            ta = TimeAwareness(ha_mock)
        ta.redis = redis_mock
        return ta

    @pytest.mark.asyncio
    async def test_invalid_auto_off_minutes_falls_back(self, ta_ld, redis_mock):
        """Invalid auto_off_empty_room_minutes value falls back to threshold."""
        past_ts = str(datetime.now().timestamp() - 2400)
        redis_mock.get.return_value = past_ts
        redis_mock.exists.return_value = 0
        states = [
            {"entity_id": "light.bad_main", "state": "on",
             "attributes": {"friendly_name": "Bad Licht"}},
        ]
        cfg = {
            "lighting": {"enabled": True, "auto_off_empty_room_minutes": "not_a_number"},
            "multi_room": {"room_motion_sensors": {}},
        }
        with patch("assistant.time_awareness.yaml_config") as mock_cfg, \
             patch("assistant.config.get_room_profiles",
                   return_value={"rooms": {}}):
            mock_cfg.get.side_effect = lambda k, default=None: cfg.get(k, default)
            alerts = await ta_ld._check_lights_empty_rooms(states)
        # Should still produce alert using fallback threshold
        assert len(alerts) == 1
        assert alerts[0]["type"] == "light_empty_room"

    @pytest.mark.asyncio
    async def test_motion_sensor_room_mapping(self, ta_ld, redis_mock):
        """Configured motion sensor maps to room correctly — light not alerted."""
        states = [
            {"entity_id": "binary_sensor.motion_kitchen", "state": "on"},
            {"entity_id": "light.kitchen_lamp", "state": "on",
             "attributes": {"friendly_name": "Kitchen Lamp"}},
        ]
        cfg = {
            "lighting": {"enabled": True},
            "multi_room": {"room_motion_sensors": {
                "kitchen": "binary_sensor.motion_kitchen",
            }},
        }
        with patch("assistant.time_awareness.yaml_config") as mock_cfg, \
             patch("assistant.config.get_room_profiles",
                   return_value={"rooms": {"kitchen": {"light_entities": ["light.kitchen_lamp"]}}}):
            mock_cfg.get.side_effect = lambda k, default=None: cfg.get(k, default)
            alerts = await ta_ld._check_lights_empty_rooms(states)
        assert alerts == []

    @pytest.mark.asyncio
    async def test_heuristic_motion_sensor_detection(self, ta_ld, redis_mock):
        """binary_sensor.motion_* without config still detects active room."""
        states = [
            {"entity_id": "binary_sensor.motion_garage", "state": "on"},
            {"entity_id": "light.garage_ceiling", "state": "on",
             "attributes": {"friendly_name": "Garage Ceiling"}},
        ]
        cfg = {
            "lighting": {"enabled": True},
            "multi_room": {"room_motion_sensors": {}},
        }
        with patch("assistant.time_awareness.yaml_config") as mock_cfg, \
             patch("assistant.config.get_room_profiles",
                   return_value={"rooms": {"garage": {"light_entities": ["light.garage_ceiling"]}}}):
            mock_cfg.get.side_effect = lambda k, default=None: cfg.get(k, default)
            alerts = await ta_ld._check_lights_empty_rooms(states)
        assert alerts == []

    @pytest.mark.asyncio
    async def test_person_zone_active_room(self, ta_ld, redis_mock):
        """Person zone attribute marks room as active."""
        states = [
            {"entity_id": "person.user1", "state": "home",
             "attributes": {"zone": "Office"}},
            {"entity_id": "light.office_desk", "state": "on",
             "attributes": {"friendly_name": "Office Desk Light"}},
        ]
        cfg = {
            "lighting": {"enabled": True},
            "multi_room": {"room_motion_sensors": {}},
        }
        with patch("assistant.time_awareness.yaml_config") as mock_cfg, \
             patch("assistant.config.get_room_profiles",
                   return_value={"rooms": {"office": {"light_entities": ["light.office_desk"]}}}):
            mock_cfg.get.side_effect = lambda k, default=None: cfg.get(k, default)
            alerts = await ta_ld._check_lights_empty_rooms(states)
        assert alerts == []

    @pytest.mark.asyncio
    async def test_manual_override_skips_light(self, ta_ld, redis_mock):
        """Light with manual override active should be skipped."""
        past_ts = str(datetime.now().timestamp() - 2400)
        redis_mock.get.return_value = past_ts
        redis_mock.exists.return_value = 0
        states = [
            {"entity_id": "light.living_manual", "state": "on",
             "attributes": {"friendly_name": "Living Manual"}},
        ]
        cfg = {
            "lighting": {"enabled": True},
            "multi_room": {"room_motion_sensors": {}},
        }
        # Mock light engine with manual override
        mock_le = AsyncMock()
        mock_le.is_manual_override_active = AsyncMock(return_value=True)
        ta_ld._light_engine = mock_le
        with patch("assistant.time_awareness.yaml_config") as mock_cfg, \
             patch("assistant.config.get_room_profiles",
                   return_value={"rooms": {}}):
            mock_cfg.get.side_effect = lambda k, default=None: cfg.get(k, default)
            alerts = await ta_ld._check_lights_empty_rooms(states)
        assert alerts == []

    @pytest.mark.asyncio
    async def test_manual_override_exception_continues(self, ta_ld, redis_mock):
        """Exception in manual override check is caught — light still checked."""
        past_ts = str(datetime.now().timestamp() - 2400)
        redis_mock.get.return_value = past_ts
        redis_mock.exists.return_value = 0
        states = [
            {"entity_id": "light.study_lamp", "state": "on",
             "attributes": {"friendly_name": "Study Lamp"}},
        ]
        cfg = {
            "lighting": {"enabled": True},
            "multi_room": {"room_motion_sensors": {}},
        }
        mock_le = AsyncMock()
        mock_le.is_manual_override_active = AsyncMock(side_effect=RuntimeError("LE error"))
        ta_ld._light_engine = mock_le
        with patch("assistant.time_awareness.yaml_config") as mock_cfg, \
             patch("assistant.config.get_room_profiles",
                   return_value={"rooms": {}}):
            mock_cfg.get.side_effect = lambda k, default=None: cfg.get(k, default)
            alerts = await ta_ld._check_lights_empty_rooms(states)
        # Light should still produce alert despite LE error
        assert len(alerts) == 1

    @pytest.mark.asyncio
    async def test_auto_off_service_failure_fallback(self, ta_ld, ha_mock, redis_mock):
        """call_service failure during auto-off falls back to hint alert."""
        past_ts = str(datetime.now().timestamp() - 2400)
        redis_mock.get.return_value = past_ts
        redis_mock.exists.return_value = 0
        ha_mock.call_service = AsyncMock(side_effect=RuntimeError("HA down"))
        states = [
            {"entity_id": "light.kitchen_spot", "state": "on",
             "attributes": {"friendly_name": "Kitchen Spot"}},
        ]
        cfg = {
            "lighting": {"enabled": True, "auto_off_empty_room_minutes": 20, "default_transition": 2},
            "multi_room": {"room_motion_sensors": {}},
        }
        with patch("assistant.time_awareness.yaml_config") as mock_cfg, \
             patch("assistant.config.get_room_profiles",
                   return_value={"rooms": {}}):
            mock_cfg.get.side_effect = lambda k, default=None: cfg.get(k, default)
            alerts = await ta_ld._check_lights_empty_rooms(states)
        assert len(alerts) == 1
        assert alerts[0]["type"] == "light_empty_room"

    @pytest.mark.asyncio
    async def test_motion_sensor_null_skipped(self, ta_ld, redis_mock):
        """Motion sensor with None value in config is skipped."""
        states = [
            {"entity_id": "light.hallway_light", "state": "on",
             "attributes": {"friendly_name": "Hallway"}},
        ]
        cfg = {
            "lighting": {"enabled": True},
            "multi_room": {"room_motion_sensors": {"hallway": None}},
        }
        redis_mock.get.return_value = None  # first check
        with patch("assistant.time_awareness.yaml_config") as mock_cfg, \
             patch("assistant.config.get_room_profiles",
                   return_value={"rooms": {}}):
            mock_cfg.get.side_effect = lambda k, default=None: cfg.get(k, default)
            alerts = await ta_ld._check_lights_empty_rooms(states)
        # Under threshold (first check), no alert
        assert alerts == []


# =====================================================================
# _check_windows_cold — outdoor temp sensor parsing edge case
# =====================================================================


class TestCheckWindowsColdDeep:
    """Cover outdoor_temperature parsing and invalid temp values."""

    @pytest.fixture
    def ta_wd(self, ha_mock, redis_mock):
        cfg = {
            "time_awareness": {
                "enabled": True,
                "thresholds": {"window_open_cold": 120},
            },
            "activity": {"entities": {"pc_sensors": []}},
        }
        with patch("assistant.time_awareness.yaml_config", cfg):
            ta = TimeAwareness(ha_mock)
        ta.redis = redis_mock
        return ta

    @pytest.mark.asyncio
    async def test_outdoor_temp_invalid_value(self, ta_wd, redis_mock):
        """Invalid outdoor temperature value is handled gracefully."""
        states = [
            {"entity_id": "sensor.outdoor_temperature", "state": "unavailable"},
            {"entity_id": "binary_sensor.window_kitchen", "state": "on",
             "attributes": {"friendly_name": "Kuechenfenster"}},
        ]
        # No weather entity, outdoor temp is invalid -> outside_temp stays None -> no alert
        alerts = await ta_wd._check_windows_cold(states)
        assert alerts == []

    @pytest.mark.asyncio
    async def test_outdoor_temp_cold_with_sensor(self, ta_wd, redis_mock):
        """Outdoor temp sensor below 10 triggers window check."""
        past_ts = str(datetime.now().timestamp() - 8000)
        redis_mock.get.return_value = past_ts
        redis_mock.exists.return_value = 0
        states = [
            {"entity_id": "sensor.outdoor_temperature", "state": "5.0"},
            {"entity_id": "binary_sensor.window_bath", "state": "on",
             "attributes": {"friendly_name": "Badfenster"}},
        ]
        with patch("assistant.function_calling.is_heating_relevant_opening", return_value=True), \
             patch("assistant.function_calling.get_opening_type", return_value="window"):
            alerts = await ta_wd._check_windows_cold(states)
        assert len(alerts) == 1
        assert "5.0°C" in alerts[0]["message"]


# =====================================================================
# _check_loop — real loop with error handling
# =====================================================================


class TestCheckLoopBehavior:
    @pytest.mark.asyncio
    async def test_check_loop_error_recovery(self, ta):
        """_check_loop catches errors from _run_checks and continues."""
        call_count = 0

        async def failing_checks():
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                raise RuntimeError("HA unreachable")
            # Stop loop on second call
            ta._running = False

        ta._running = True
        ta.check_interval = 0
        with patch.object(ta, "_run_checks", side_effect=failing_checks):
            await ta._check_loop()
        # Loop ran twice: first error was caught, second stopped loop
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_check_loop_stops_when_not_running(self, ta):
        """_check_loop exits immediately when _running is False."""
        ta._running = False
        ta.check_interval = 0
        with patch.object(ta, "_run_checks", new_callable=AsyncMock) as mock_checks:
            await ta._check_loop()
        mock_checks.assert_not_called()
