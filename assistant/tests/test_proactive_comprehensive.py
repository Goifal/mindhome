"""
Comprehensive tests for proactive.py — ProactiveManager.

Tests: __init__, _is_quiet_hours, start/stop, _handle_event,
_handle_state_change (alarm, smoke, water, doorbell, person tracking),
_check_morning_briefing, _check_evening_briefing, _match_appliance,
batch queue, delivery pipeline.
"""

import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────


def _make_brain_mock():
    """Creates a minimal Brain mock for ProactiveManager."""
    brain = MagicMock()
    brain.ha = AsyncMock()
    brain.ha.get_states = AsyncMock(return_value=[])
    brain.ha.call_service = AsyncMock()
    brain.camera_manager = MagicMock()
    brain.camera_manager.describe_doorbell = AsyncMock(return_value=None)
    brain.conditional_commands = MagicMock()
    brain.conditional_commands.check_event = AsyncMock(return_value=[])
    brain._task_registry = MagicMock()
    brain._task_registry.create_task = MagicMock()
    brain._get_occupied_room = AsyncMock(return_value="wohnzimmer")
    brain.sound_manager = MagicMock()
    brain.sound_manager.speak_response = AsyncMock()
    brain.memory = MagicMock()
    brain.memory.redis = AsyncMock()
    brain.memory.redis.get = AsyncMock(return_value=None)
    brain.memory.redis.set = AsyncMock()
    brain.memory.redis.delete = AsyncMock()
    brain.routines = MagicMock()
    brain.routines.get_absence_summary = AsyncMock(return_value="")
    brain.routines.generate_morning_briefing = AsyncMock(
        return_value={"text": "", "actions": []}
    )
    brain.learning_observer = MagicMock()
    brain.learning_observer.observe_state_change = AsyncMock()
    brain.activity = MagicMock()
    brain.activity.set_manual_override = MagicMock()
    brain.activity.is_in_flow_state = MagicMock(return_value=False)
    brain.activity.get_focused_duration_minutes = MagicMock(return_value=0)
    brain._current_person = ""
    # Diagnostics / threat disabled by default
    brain.diagnostics = MagicMock()
    brain.diagnostics.enabled = False
    brain.threat_assessment = MagicMock()
    brain.threat_assessment.enabled = False
    return brain


@pytest.fixture
def brain_mock():
    return _make_brain_mock()


@pytest.fixture
def pm(brain_mock):
    with (
        patch(
            "assistant.proactive.yaml_config",
            {
                "proactive": {"enabled": True, "cooldown_seconds": 60},
                "ambient_presence": {"quiet_start": 22, "quiet_end": 7},
                "routines": {
                    "morning_briefing": {
                        "enabled": True,
                        "window_start_hour": 6,
                        "window_end_hour": 10,
                        "wakeup_sequence": {"enabled": False},
                    }
                },
                "appliance_monitor": {},
                "seasonal_actions": {"enabled": False},
                "observation_loop": {"enabled": False},
                "vacuum": {"enabled": False},
            },
        ),
        patch("assistant.proactive.settings") as mock_settings,
    ):
        mock_settings.ha_url = "http://localhost:8123"
        mock_settings.ha_token = "test_token"
        from assistant.proactive import ProactiveManager

        manager = ProactiveManager(brain_mock)
    return manager


# ── Init ──────────────────────────────────────────────────────────────


class TestProactiveInit:
    def test_default_enabled(self, pm):
        assert pm.enabled is True

    def test_event_handlers_populated(self, pm):
        assert "alarm_triggered" in pm.event_handlers
        assert "smoke_detected" in pm.event_handlers
        assert "water_leak" in pm.event_handlers
        assert "doorbell" in pm.event_handlers
        assert "person_arrived" in pm.event_handlers

    def test_quiet_hours_config(self, pm):
        assert pm._quiet_start == 22
        assert pm._quiet_end == 7


# ── Quiet Hours ───────────────────────────────────────────────────────


class TestQuietHours:
    def test_quiet_at_23(self, pm):
        with patch("assistant.proactive.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 23
            assert pm._is_quiet_hours() is True

    def test_quiet_at_3(self, pm):
        with patch("assistant.proactive.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 3
            assert pm._is_quiet_hours() is True

    def test_not_quiet_at_12(self, pm):
        with patch("assistant.proactive.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 12
            assert pm._is_quiet_hours() is False

    def test_not_quiet_at_7(self, pm):
        with patch("assistant.proactive.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 7
            assert pm._is_quiet_hours() is False

    def test_quiet_hours_no_wraparound(self, pm):
        pm._quiet_start = 14
        pm._quiet_end = 18
        with patch("assistant.proactive.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 15
            assert pm._is_quiet_hours() is True
            mock_dt.now.return_value.hour = 12
            assert pm._is_quiet_hours() is False


# ── Handle Event ──────────────────────────────────────────────────────


class TestHandleEvent:
    @pytest.mark.asyncio
    async def test_state_changed_dispatches(self, pm):
        with patch.object(
            pm, "_handle_state_change", new_callable=AsyncMock
        ) as mock_sc:
            await pm._handle_event(
                {
                    "event_type": "state_changed",
                    "data": {
                        "entity_id": "light.test",
                        "new_state": {"state": "on"},
                        "old_state": {"state": "off"},
                    },
                }
            )
            mock_sc.assert_called_once()

    @pytest.mark.asyncio
    async def test_mindhome_event_dispatches(self, pm):
        with patch.object(
            pm, "_handle_mindhome_event", new_callable=AsyncMock
        ) as mock_mh:
            await pm._handle_event(
                {
                    "event_type": "mindhome_event",
                    "data": {"type": "test"},
                }
            )
            mock_mh.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_event_ignored(self, pm):
        # Should not raise
        await pm._handle_event({"event_type": "unknown", "data": {}})


# ── Handle State Change ──────────────────────────────────────────────


class TestHandleStateChange:
    @pytest.mark.asyncio
    async def test_alarm_triggered(self, pm):
        with (
            patch.object(pm, "_notify", new_callable=AsyncMock) as mock_notify,
            patch.object(pm, "_execute_emergency_protocol", new_callable=AsyncMock),
        ):
            await pm._handle_state_change(
                {
                    "entity_id": "alarm_control_panel.home",
                    "new_state": {"state": "triggered"},
                    "old_state": {"state": "armed_away"},
                }
            )
            mock_notify.assert_called()
            call_args = mock_notify.call_args_list[0]
            assert call_args[0][0] == "alarm_triggered"

    @pytest.mark.asyncio
    async def test_smoke_detected(self, pm):
        with (
            patch.object(pm, "_notify", new_callable=AsyncMock) as mock_notify,
            patch.object(pm, "_execute_emergency_protocol", new_callable=AsyncMock),
        ):
            await pm._handle_state_change(
                {
                    "entity_id": "binary_sensor.smoke_kitchen",
                    "new_state": {"state": "on"},
                    "old_state": {"state": "off"},
                }
            )
            mock_notify.assert_called()
            assert mock_notify.call_args_list[0][0][0] == "smoke_detected"

    @pytest.mark.asyncio
    async def test_water_leak(self, pm):
        with (
            patch.object(pm, "_notify", new_callable=AsyncMock) as mock_notify,
            patch.object(pm, "_execute_emergency_protocol", new_callable=AsyncMock),
        ):
            await pm._handle_state_change(
                {
                    "entity_id": "binary_sensor.water_leak_basement",
                    "new_state": {"state": "on"},
                    "old_state": {"state": "off"},
                }
            )
            mock_notify.assert_called()
            assert mock_notify.call_args_list[0][0][0] == "water_leak"

    @pytest.mark.asyncio
    async def test_same_state_ignored(self, pm):
        with patch.object(pm, "_notify", new_callable=AsyncMock) as mock_notify:
            await pm._handle_state_change(
                {
                    "entity_id": "light.kitchen",
                    "new_state": {"state": "on"},
                    "old_state": {"state": "on"},
                }
            )
            mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_new_state_ignored(self, pm):
        with patch.object(pm, "_notify", new_callable=AsyncMock) as mock_notify:
            await pm._handle_state_change(
                {
                    "entity_id": "light.kitchen",
                    "new_state": {},
                    "old_state": {"state": "off"},
                }
            )
            mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_doorbell(self, pm, brain_mock):
        brain_mock.camera_manager.describe_doorbell = AsyncMock(
            return_value="Person mit Paket"
        )
        with patch.object(pm, "_notify", new_callable=AsyncMock) as mock_notify:
            # Patch away visitor_manager
            brain_mock.visitor_manager = MagicMock()
            brain_mock.visitor_manager.enabled = False
            await pm._handle_state_change(
                {
                    "entity_id": "binary_sensor.doorbell",
                    "new_state": {"state": "on"},
                    "old_state": {"state": "off"},
                }
            )
            mock_notify.assert_called()
            call_data = mock_notify.call_args_list[0][0][2]
            assert "camera_description" in call_data

    @pytest.mark.asyncio
    async def test_person_arrived(self, pm, brain_mock):
        with (
            patch.object(pm, "_notify", new_callable=AsyncMock) as mock_notify,
            patch.object(
                pm,
                "_build_arrival_status",
                new_callable=AsyncMock,
                return_value={"temp": 21},
            ),
            patch("assistant.proactive.resolve_person_by_entity", return_value="Max"),
            patch(
                "assistant.proactive.yaml_config",
                {
                    "return_briefing": {"enabled": False},
                    "proactive": {"departure_shopping_reminder": False},
                },
            ),
        ):
            await pm._handle_state_change(
                {
                    "entity_id": "person.max",
                    "new_state": {
                        "state": "home",
                        "attributes": {"friendly_name": "Max"},
                    },
                    "old_state": {"state": "away"},
                }
            )
            mock_notify.assert_called()
            assert mock_notify.call_args_list[0][0][0] == "person_arrived"

    @pytest.mark.asyncio
    async def test_person_left(self, pm, brain_mock):
        with (
            patch.object(pm, "_notify", new_callable=AsyncMock) as mock_notify,
            patch("assistant.proactive.resolve_person_by_entity", return_value="Max"),
            patch(
                "assistant.proactive.yaml_config",
                {
                    "return_briefing": {"enabled": False},
                    "proactive": {"departure_shopping_reminder": False},
                },
            ),
            patch.object(
                pm, "_get_open_shopping_items", new_callable=AsyncMock, return_value=[]
            ),
        ):
            await pm._handle_state_change(
                {
                    "entity_id": "person.max",
                    "new_state": {
                        "state": "away",
                        "attributes": {"friendly_name": "Max"},
                    },
                    "old_state": {"state": "home"},
                }
            )
            mock_notify.assert_called()
            assert mock_notify.call_args_list[0][0][0] == "person_left"

    @pytest.mark.asyncio
    async def test_sensor_no_old_state_defaults_to_zero(self, pm):
        """For sensors without old_state, should default to '0'."""
        with (
            patch.object(pm, "_notify", new_callable=AsyncMock),
            patch.object(
                pm, "_check_appliance_power", new_callable=AsyncMock
            ) as mock_appliance,
            patch.object(pm, "_check_power_close", new_callable=AsyncMock),
        ):
            await pm._handle_state_change(
                {
                    "entity_id": "sensor.power",
                    "new_state": {"state": "100"},
                    "old_state": None,
                }
            )
            # Should have been called with old_val defaulted to "0"
            mock_appliance.assert_called()


# ── Match Appliance ──────────────────────────────────────────────────


class TestMatchAppliance:
    def test_match_washer(self, pm):
        pm._appliance_patterns = {"washer": ["washer", "waschmaschine"]}
        assert pm._match_appliance("sensor.waschmaschine_power") == "washer"

    def test_match_dryer(self, pm):
        pm._appliance_patterns = {"dryer": ["dryer", "trockner"]}
        assert pm._match_appliance("sensor.trockner_power") == "dryer"

    def test_no_match(self, pm):
        pm._appliance_patterns = {"washer": ["washer"]}
        assert pm._match_appliance("sensor.temperature") is None


# ── Start / Stop ─────────────────────────────────────────────────────


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_disabled(self, pm):
        pm.enabled = False
        await pm.start()
        assert pm._task is None

    @pytest.mark.asyncio
    async def test_stop(self, pm):
        import asyncio

        pm._running = True

        async def noop():
            pass

        task = asyncio.ensure_future(noop())
        await task  # complete it first
        pm._task = task
        pm._diag_task = None
        pm._batch_task = None
        pm._seasonal_task = None

        await pm.stop()
        assert pm._running is False


# ── Delivery ─────────────────────────────────────────────────────────


class TestDelivery:
    @pytest.mark.asyncio
    async def test_deliver_websocket_only(self, pm):
        with patch(
            "assistant.proactive.emit_proactive", new_callable=AsyncMock
        ) as mock_emit:
            await pm._deliver("Test message", "test_event", "medium")
            mock_emit.assert_called_once_with(
                "Test message", "test_event", "medium", ""
            )

    @pytest.mark.asyncio
    async def test_deliver_with_tts(self, pm, brain_mock):
        with patch("assistant.proactive.emit_proactive", new_callable=AsyncMock):
            await pm._deliver(
                "Test message",
                "test_event",
                "medium",
                delivery_method="tts_loud",
                room="wohnzimmer",
            )
            brain_mock._task_registry.create_task.assert_called()


# ── Morning Briefing Check ───────────────────────────────────────────


class TestCheckMorningBriefing:
    @pytest.mark.asyncio
    async def test_disabled(self, pm):
        pm._mb_enabled = False
        with patch.object(pm, "_notify", new_callable=AsyncMock) as mock_notify:
            await pm._check_morning_briefing()
            mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_already_triggered_today(self, pm):
        today = datetime.now().strftime("%Y-%m-%d")
        pm._mb_last_date = today
        pm._mb_triggered_today = True
        with patch.object(pm, "_notify", new_callable=AsyncMock) as mock_notify:
            await pm._check_morning_briefing()
            mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_outside_window(self, pm):
        pm._mb_window_start = 6
        pm._mb_window_end = 10
        noon = datetime(2026, 3, 11, 12, 0)
        with patch("assistant.proactive.datetime", wraps=datetime) as mock_dt:
            mock_dt.now.return_value = noon
            with patch.object(pm, "_notify", new_callable=AsyncMock) as mock_notify:
                await pm._check_morning_briefing()
                mock_notify.assert_not_called()


# ── Rate-Limiting ────────────────────────────────────────────────────


class TestCoverRateLimiting:
    @pytest.mark.asyncio
    async def test_rate_limit_not_reached(self, pm):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value="3")
        result = await pm._check_cover_rate_limit("cover.test", redis)
        assert result is False

    @pytest.mark.asyncio
    async def test_rate_limit_reached(self, pm):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value="6")
        result = await pm._check_cover_rate_limit("cover.test", redis)
        assert result is True

    @pytest.mark.asyncio
    async def test_rate_limit_no_redis(self, pm):
        result = await pm._check_cover_rate_limit("cover.test", None)
        assert result is False

    @pytest.mark.asyncio
    async def test_increment_rate(self, pm):
        redis = AsyncMock()
        pipe = AsyncMock()
        redis.pipeline = MagicMock(return_value=pipe)
        pipe.execute = AsyncMock(return_value=[1, True])
        await pm._increment_cover_rate("cover.test", redis)
        pipe.incr.assert_called_once()
        pipe.expire.assert_called_once()


# ── Reason-State ─────────────────────────────────────────────────────


class TestCoverReasonState:
    @pytest.mark.asyncio
    async def test_set_and_get_reason(self, pm):
        redis = AsyncMock()
        redis.set = AsyncMock()
        await pm._set_cover_reason("cover.test", 50, "Sonnenschutz", redis)
        redis.set.assert_called_once()
        call_args = redis.set.call_args
        assert "mha:cover:reason:cover.test" in str(call_args)

    @pytest.mark.asyncio
    async def test_get_reason_empty(self, pm):
        pm.brain.memory.redis.get = AsyncMock(return_value=None)
        result = await pm.get_cover_reason("cover.test")
        assert result == {}


# ── Dry-Run Modus ────────────────────────────────────────────────────


class TestDryRunMode:
    @pytest.mark.asyncio
    async def test_dry_run_flag_prevents_action(self, pm):
        """Dry-Run mode should log but not call HA service."""
        pm.brain.ha.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "cover.test",
                    "state": "open",
                    "attributes": {"current_position": 100, "device_class": "shutter"},
                },
            ]
        )
        pm.brain.executor = MagicMock()
        pm.brain.executor._is_safe_cover = AsyncMock(return_value=True)
        pm.brain.executor._translate_cover_position_from_ha = MagicMock(
            return_value=100
        )
        pm.brain.autonomy = MagicMock()
        pm.brain.autonomy.level = 5

        result = await pm._auto_cover_action(
            "cover.test",
            0,
            "Test",
            3,
            None,
            dry_run=True,
        )
        assert result is False
        pm.brain.ha.call_service.assert_not_called()


# ── State-Machine ────────────────────────────────────────────────────


class TestCoverStateMachine:
    def test_initial_state_is_idle(self, pm):
        cs = pm._get_cover_state("cover.test")
        assert cs.state == pm.CoverState.IDLE

    def test_transition_records_history(self, pm):
        cs = pm._get_cover_state("cover.test2")
        cs.transition(pm.CoverState.SUN_PROTECTED, "Sonnenschutz")
        assert cs.state == pm.CoverState.SUN_PROTECTED
        assert len(cs.history) == 1
        assert cs.history[0][2] == pm.CoverState.SUN_PROTECTED

    def test_no_op_transition(self, pm):
        cs = pm._get_cover_state("cover.test3")
        cs.transition(pm.CoverState.IDLE, "no change")
        assert len(cs.history) == 0

    def test_to_dict(self, pm):
        cs = pm._get_cover_state("cover.test4")
        cs.transition(pm.CoverState.STORM_SECURED, "Sturm")
        d = cs.to_dict()
        assert d["state"] == pm.CoverState.STORM_SECURED
        assert "entity_id" in d

    def test_get_all_cover_states(self, pm):
        pm._get_cover_state("cover.a")
        pm._get_cover_state("cover.b")
        states = pm.get_all_cover_states()
        assert len(states) >= 2


# ── Room Matching ────────────────────────────────────────────────────


class TestRoomMatching:
    def test_fallback_heuristic(self, pm):
        room = pm._get_room_for_cover("cover.wohnzimmer_links")
        assert room == "wohnzimmer"

    def test_config_mapping(self, pm):
        with (
            patch(
                "assistant.proactive.yaml_config",
                {
                    "seasonal_actions": {
                        "cover_automation": {
                            "room_mapping": {"cover.spezial_42": "buero"},
                        },
                    },
                },
            ),
            patch(
                "assistant.proactive._get_room_profiles_cached",
                return_value={"cover_profiles": {"covers": []}},
            ),
        ):
            room = pm._get_room_for_cover("cover.spezial_42")
            assert room == "buero"


# ── Cover Summary ────────────────────────────────────────────────────


class TestCoverSummary:
    @pytest.mark.asyncio
    async def test_summary_empty(self, pm):
        pm.brain.ha.get_states = AsyncMock(return_value=[])
        result = await pm.get_cover_summary()
        assert result == ""

    @pytest.mark.asyncio
    async def test_summary_with_covers(self, pm):
        pm.brain.ha.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "cover.wz",
                    "attributes": {
                        "current_position": 100,
                        "friendly_name": "Wohnzimmer",
                    },
                },
                {
                    "entity_id": "cover.sz",
                    "attributes": {
                        "current_position": 0,
                        "friendly_name": "Schlafzimmer",
                    },
                },
            ]
        )
        pm.brain.executor = MagicMock()
        pm.brain.executor._translate_cover_position_from_ha = MagicMock(
            side_effect=lambda eid, pos: pos
        )
        result = await pm.get_cover_summary()
        assert "offen" in result or "geschlossen" in result


# ── Debug-Assistent ──────────────────────────────────────────────────


class TestDebugAssistant:
    @pytest.mark.asyncio
    async def test_debug_no_entity(self, pm):
        pm.brain.ha.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "cover.test",
                    "attributes": {"current_position": 50, "friendly_name": "Test"},
                },
            ]
        )
        result = await pm.debug_cover_state()
        assert "Cover-Status" in result

    @pytest.mark.asyncio
    async def test_debug_specific_entity(self, pm):
        pm.brain.ha.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "cover.test",
                    "attributes": {"current_position": 50, "friendly_name": "Test"},
                },
            ]
        )
        pm.brain.memory.redis.get = AsyncMock(return_value=None)
        result = await pm.debug_cover_state("cover.test")
        assert "Test" in result
        assert "Position" in result

    @pytest.mark.asyncio
    async def test_debug_not_found(self, pm):
        pm.brain.ha.get_states = AsyncMock(return_value=[])
        result = await pm.debug_cover_state("cover.nonexistent")
        assert "nicht gefunden" in result


# ── Config-Assistent ─────────────────────────────────────────────────


class TestConfigAssistant:
    @pytest.mark.asyncio
    async def test_config_help(self, pm):
        with (
            patch(
                "assistant.proactive.yaml_config",
                {
                    "seasonal_actions": {
                        "cover_automation": {
                            "weather_protection": True,
                            "heat_protection_temp": 26,
                            "storm_wind_speed": 50,
                        },
                    },
                },
            ),
            patch(
                "assistant.proactive._get_room_profiles_cached",
                return_value={
                    "cover_profiles": {"covers": []},
                    "markisen": {},
                },
            ),
        ):
            result = await pm.get_cover_config_help()
            assert "Konfiguration" in result
            assert "26" in result


# ── Weather Event Handler ────────────────────────────────────────────


class TestWeatherEventHandler:
    @pytest.mark.asyncio
    async def test_wind_spike_triggers_storm(self, pm):
        pm.brain.memory.redis.get = AsyncMock(return_value=None)
        pm.brain.memory.redis.set = AsyncMock()
        with (
            patch(
                "assistant.proactive.yaml_config",
                {
                    "seasonal_actions": {"cover_automation": {"storm_wind_speed": 50}},
                },
            ),
            patch(
                "assistant.cover_config.get_sensor_by_role", return_value="sensor.wind"
            ),
        ):
            # This should log a warning about wind spike
            await pm._handle_weather_event("sensor.wind", "55", "20")

    @pytest.mark.asyncio
    async def test_non_weather_entity_ignored(self, pm):
        with patch(
            "assistant.cover_config.get_sensor_by_role", return_value="sensor.wind"
        ):
            # Should not raise
            await pm._handle_weather_event("light.wohnzimmer", "on", "off")


# ── Anomaly Detection ────────────────────────────────────────────────


class TestAnomalyDetection:
    @pytest.mark.asyncio
    async def test_anomaly_tracking(self, pm):
        redis = AsyncMock()
        redis.incr = AsyncMock(return_value=1)
        redis.expire = AsyncMock()
        await pm._track_cover_anomaly("cover.test", redis)
        redis.incr.assert_called_once()

    @pytest.mark.asyncio
    async def test_anomaly_triggers_notification_at_4(self, pm):
        redis = AsyncMock()
        redis.incr = AsyncMock(return_value=4)
        redis.delete = AsyncMock()
        with patch.object(pm, "_notify", new_callable=AsyncMock) as mock_notify:
            await pm._track_cover_anomaly("cover.test", redis)
            mock_notify.assert_called_once()
            assert "Ping-Pong" in str(mock_notify.call_args)
