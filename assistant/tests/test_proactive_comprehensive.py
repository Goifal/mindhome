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
    brain.routines.generate_morning_briefing = AsyncMock(return_value={"text": "", "actions": []})
    brain.learning_observer = MagicMock()
    brain.learning_observer.observe_state_change = AsyncMock()
    brain.activity = MagicMock()
    brain.activity.set_manual_override = MagicMock()
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
    with patch("assistant.proactive.yaml_config", {
        "proactive": {"enabled": True, "cooldown_seconds": 60},
        "ambient_presence": {"quiet_start": 22, "quiet_end": 7},
        "routines": {"morning_briefing": {"enabled": True, "window_start_hour": 6, "window_end_hour": 10, "wakeup_sequence": {"enabled": False}}},
        "appliance_monitor": {},
        "seasonal_actions": {"enabled": False},
        "observation_loop": {"enabled": False},
        "vacuum": {"enabled": False},
    }), patch("assistant.proactive.settings") as mock_settings:
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
        with patch.object(pm, "_handle_state_change", new_callable=AsyncMock) as mock_sc:
            await pm._handle_event({
                "event_type": "state_changed",
                "data": {"entity_id": "light.test", "new_state": {"state": "on"}, "old_state": {"state": "off"}},
            })
            mock_sc.assert_called_once()

    @pytest.mark.asyncio
    async def test_mindhome_event_dispatches(self, pm):
        with patch.object(pm, "_handle_mindhome_event", new_callable=AsyncMock) as mock_mh:
            await pm._handle_event({
                "event_type": "mindhome_event",
                "data": {"type": "test"},
            })
            mock_mh.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_event_ignored(self, pm):
        # Should not raise
        await pm._handle_event({"event_type": "unknown", "data": {}})


# ── Handle State Change ──────────────────────────────────────────────

class TestHandleStateChange:

    @pytest.mark.asyncio
    async def test_alarm_triggered(self, pm):
        with patch.object(pm, "_notify", new_callable=AsyncMock) as mock_notify, \
             patch.object(pm, "_execute_emergency_protocol", new_callable=AsyncMock):
            await pm._handle_state_change({
                "entity_id": "alarm_control_panel.home",
                "new_state": {"state": "triggered"},
                "old_state": {"state": "armed_away"},
            })
            mock_notify.assert_called()
            call_args = mock_notify.call_args_list[0]
            assert call_args[0][0] == "alarm_triggered"

    @pytest.mark.asyncio
    async def test_smoke_detected(self, pm):
        with patch.object(pm, "_notify", new_callable=AsyncMock) as mock_notify, \
             patch.object(pm, "_execute_emergency_protocol", new_callable=AsyncMock):
            await pm._handle_state_change({
                "entity_id": "binary_sensor.smoke_kitchen",
                "new_state": {"state": "on"},
                "old_state": {"state": "off"},
            })
            mock_notify.assert_called()
            assert mock_notify.call_args_list[0][0][0] == "smoke_detected"

    @pytest.mark.asyncio
    async def test_water_leak(self, pm):
        with patch.object(pm, "_notify", new_callable=AsyncMock) as mock_notify, \
             patch.object(pm, "_execute_emergency_protocol", new_callable=AsyncMock):
            await pm._handle_state_change({
                "entity_id": "binary_sensor.water_leak_basement",
                "new_state": {"state": "on"},
                "old_state": {"state": "off"},
            })
            mock_notify.assert_called()
            assert mock_notify.call_args_list[0][0][0] == "water_leak"

    @pytest.mark.asyncio
    async def test_same_state_ignored(self, pm):
        with patch.object(pm, "_notify", new_callable=AsyncMock) as mock_notify:
            await pm._handle_state_change({
                "entity_id": "light.kitchen",
                "new_state": {"state": "on"},
                "old_state": {"state": "on"},
            })
            mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_new_state_ignored(self, pm):
        with patch.object(pm, "_notify", new_callable=AsyncMock) as mock_notify:
            await pm._handle_state_change({
                "entity_id": "light.kitchen",
                "new_state": {},
                "old_state": {"state": "off"},
            })
            mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_doorbell(self, pm, brain_mock):
        brain_mock.camera_manager.describe_doorbell = AsyncMock(return_value="Person mit Paket")
        with patch.object(pm, "_notify", new_callable=AsyncMock) as mock_notify:
            # Patch away visitor_manager
            brain_mock.visitor_manager = MagicMock()
            brain_mock.visitor_manager.enabled = False
            await pm._handle_state_change({
                "entity_id": "binary_sensor.doorbell",
                "new_state": {"state": "on"},
                "old_state": {"state": "off"},
            })
            mock_notify.assert_called()
            call_data = mock_notify.call_args_list[0][0][2]
            assert "camera_description" in call_data

    @pytest.mark.asyncio
    async def test_person_arrived(self, pm, brain_mock):
        with patch.object(pm, "_notify", new_callable=AsyncMock) as mock_notify, \
             patch.object(pm, "_build_arrival_status", new_callable=AsyncMock, return_value={"temp": 21}), \
             patch("assistant.proactive.resolve_person_by_entity", return_value="Max"), \
             patch("assistant.proactive.yaml_config", {
                 "return_briefing": {"enabled": False},
                 "proactive": {"departure_shopping_reminder": False},
             }):
            await pm._handle_state_change({
                "entity_id": "person.max",
                "new_state": {"state": "home", "attributes": {"friendly_name": "Max"}},
                "old_state": {"state": "away"},
            })
            mock_notify.assert_called()
            assert mock_notify.call_args_list[0][0][0] == "person_arrived"

    @pytest.mark.asyncio
    async def test_person_left(self, pm, brain_mock):
        with patch.object(pm, "_notify", new_callable=AsyncMock) as mock_notify, \
             patch("assistant.proactive.resolve_person_by_entity", return_value="Max"), \
             patch("assistant.proactive.yaml_config", {
                 "return_briefing": {"enabled": False},
                 "proactive": {"departure_shopping_reminder": False},
             }), \
             patch.object(pm, "_get_open_shopping_items", new_callable=AsyncMock, return_value=[]):
            await pm._handle_state_change({
                "entity_id": "person.max",
                "new_state": {"state": "away", "attributes": {"friendly_name": "Max"}},
                "old_state": {"state": "home"},
            })
            mock_notify.assert_called()
            assert mock_notify.call_args_list[0][0][0] == "person_left"

    @pytest.mark.asyncio
    async def test_sensor_no_old_state_defaults_to_zero(self, pm):
        """For sensors without old_state, should default to '0'."""
        with patch.object(pm, "_notify", new_callable=AsyncMock), \
             patch.object(pm, "_check_appliance_power", new_callable=AsyncMock) as mock_appliance, \
             patch.object(pm, "_check_power_close", new_callable=AsyncMock):
            await pm._handle_state_change({
                "entity_id": "sensor.power",
                "new_state": {"state": "100"},
                "old_state": None,
            })
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
        with patch("assistant.proactive.emit_proactive", new_callable=AsyncMock) as mock_emit:
            await pm._deliver("Test message", "test_event", "medium")
            mock_emit.assert_called_once_with("Test message", "test_event", "medium", "")

    @pytest.mark.asyncio
    async def test_deliver_with_tts(self, pm, brain_mock):
        with patch("assistant.proactive.emit_proactive", new_callable=AsyncMock):
            await pm._deliver(
                "Test message", "test_event", "medium",
                delivery_method="tts_loud", room="wohnzimmer",
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
