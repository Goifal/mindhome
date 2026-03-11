"""
Comprehensive tests for timer_manager.py — GeneralTimer + TimerManager.

Tests: GeneralTimer dataclass (remaining_seconds, is_done, format_remaining, to_dict, from_dict),
TimerManager (create_timer, cancel_timer, get_status, get_context_hints,
create_reminder, set_wakeup_alarm, cancel_alarm, get_alarms,
_persist_timer, _remove_timer, _restore_timers, _restore_reminders, _restore_alarms,
_timer_watcher, _reminder_watcher, _alarm_watcher, action whitelist).
"""

import asyncio
import json
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from assistant.timer_manager import (
    GeneralTimer,
    TimerManager,
    TIMER_ACTION_WHITELIST,
    KEY_TIMERS,
    KEY_REMINDERS,
    KEY_ALARMS,
)

_TZ = ZoneInfo("Europe/Berlin")


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def redis_mock():
    r = AsyncMock()
    r.hset = AsyncMock()
    r.hdel = AsyncMock()
    r.hgetall = AsyncMock(return_value={})
    r.get = AsyncMock(return_value=None)
    return r


@pytest.fixture
def tm():
    return TimerManager()


@pytest.fixture
def tm_redis(tm, redis_mock):
    tm.redis = redis_mock
    return tm


# ── GeneralTimer Dataclass ────────────────────────────────────────────

class TestGeneralTimer:

    def test_start(self):
        t = GeneralTimer(id="1", label="Test", duration_seconds=60)
        assert t.started_at == 0.0
        t.start()
        assert t.started_at > 0

    def test_remaining_seconds_not_started(self):
        t = GeneralTimer(id="1", label="Test", duration_seconds=60)
        assert t.remaining_seconds == 0.0

    def test_remaining_seconds_finished(self):
        t = GeneralTimer(id="1", label="Test", duration_seconds=60, finished=True, started_at=time.time())
        assert t.remaining_seconds == 0.0

    def test_remaining_seconds_active(self):
        t = GeneralTimer(id="1", label="Test", duration_seconds=120,
                         started_at=time.time() - 30)
        remaining = t.remaining_seconds
        assert 85 <= remaining <= 95

    def test_remaining_seconds_expired(self):
        t = GeneralTimer(id="1", label="Test", duration_seconds=10,
                         started_at=time.time() - 20)
        assert t.remaining_seconds == 0.0

    def test_remaining_seconds_display(self):
        t = GeneralTimer(id="1", label="Test", duration_seconds=120,
                         started_at=time.time() - 30)
        display = t.remaining_seconds_display
        assert isinstance(display, int)
        assert 85 <= display <= 95

    def test_is_done_finished(self):
        t = GeneralTimer(id="1", label="Test", duration_seconds=60, finished=True)
        assert t.is_done is True

    def test_is_done_expired(self):
        t = GeneralTimer(id="1", label="Test", duration_seconds=10,
                         started_at=time.time() - 20)
        assert t.is_done is True

    def test_is_done_active(self):
        t = GeneralTimer(id="1", label="Test", duration_seconds=120,
                         started_at=time.time())
        assert t.is_done is False

    def test_is_done_not_started(self):
        t = GeneralTimer(id="1", label="Test", duration_seconds=60)
        assert t.is_done is False

    def test_format_remaining_abgelaufen(self):
        t = GeneralTimer(id="1", label="Test", duration_seconds=10,
                         started_at=time.time() - 20)
        assert t.format_remaining() == "abgelaufen"

    def test_format_remaining_minutes(self):
        t = GeneralTimer(id="1", label="Test", duration_seconds=300,
                         started_at=time.time())
        result = t.format_remaining()
        assert "Minute" in result

    def test_format_remaining_hours_and_minutes(self):
        t = GeneralTimer(id="1", label="Test", duration_seconds=5400,
                         started_at=time.time())
        result = t.format_remaining()
        assert "Stunde" in result
        assert "Minute" in result

    def test_format_remaining_seconds(self):
        t = GeneralTimer(id="1", label="Test", duration_seconds=30,
                         started_at=time.time())
        result = t.format_remaining()
        assert "Sekunde" in result

    def test_to_dict(self):
        t = GeneralTimer(id="abc", label="Pizza", duration_seconds=600,
                         room="kueche", person="Max", started_at=1000.0)
        d = t.to_dict()
        assert d["id"] == "abc"
        assert d["label"] == "Pizza"
        assert d["duration_seconds"] == 600
        assert d["room"] == "kueche"
        assert d["person"] == "Max"
        assert d["started_at"] == 1000.0

    def test_from_dict(self):
        data = {
            "id": "abc", "label": "Pizza", "duration_seconds": 600,
            "room": "kueche", "person": "Max", "started_at": 1000.0,
            "finished": False, "action_on_expire": {"function": "set_light"},
        }
        t = GeneralTimer.from_dict(data)
        assert t.id == "abc"
        assert t.label == "Pizza"
        assert t.action_on_expire == {"function": "set_light"}

    def test_from_dict_defaults(self):
        data = {"id": "x", "label": "Y", "duration_seconds": 60}
        t = GeneralTimer.from_dict(data)
        assert t.room == ""
        assert t.person == ""
        assert t.started_at == 0.0
        assert t.finished is False
        assert t.action_on_expire is None


# ── TimerManager Init & Callbacks ─────────────────────────────────────

class TestTimerManagerInit:

    @pytest.mark.asyncio
    async def test_initialize_no_redis(self, tm):
        await tm.initialize(None)
        assert tm.redis is None

    @pytest.mark.asyncio
    async def test_initialize_with_redis(self, tm, redis_mock):
        redis_mock.hgetall = AsyncMock(return_value={})
        await tm.initialize(redis_mock)
        assert tm.redis is redis_mock

    def test_set_notify_callback(self, tm):
        cb = AsyncMock()
        tm.set_notify_callback(cb)
        assert tm._notify_callback is cb

    def test_set_action_callback(self, tm):
        cb = AsyncMock()
        tm.set_action_callback(cb)
        assert tm._action_callback is cb


# ── Create Timer ──────────────────────────────────────────────────────

class TestCreateTimer:

    @pytest.mark.asyncio
    async def test_too_short(self, tm):
        result = await tm.create_timer(0)
        assert result["success"] is False
        assert "1 und 1440" in result["message"]

    @pytest.mark.asyncio
    async def test_too_long(self, tm):
        result = await tm.create_timer(1441)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_success_minutes(self, tm_redis):
        result = await tm_redis.create_timer(5, label="Test")
        assert result["success"] is True
        assert "timer_id" in result
        assert "5 Minuten" in result["message"]
        assert result["timer_id"] in tm_redis.timers

    @pytest.mark.asyncio
    async def test_success_hours(self, tm_redis):
        result = await tm_redis.create_timer(90, label="Kuchen")
        assert result["success"] is True
        assert "1 Stunde" in result["message"]
        assert "30 Minuten" in result["message"]

    @pytest.mark.asyncio
    async def test_singular_minute(self, tm_redis):
        result = await tm_redis.create_timer(1)
        assert "1 Minute" in result["message"]
        assert "Minuten" not in result["message"]

    @pytest.mark.asyncio
    async def test_auto_label(self, tm_redis):
        result = await tm_redis.create_timer(5)
        assert result["success"] is True
        timer = tm_redis.timers[result["timer_id"]]
        assert "5 Min" in timer.label

    @pytest.mark.asyncio
    async def test_action_hint_in_message(self, tm_redis):
        result = await tm_redis.create_timer(
            5, label="Test",
            action_on_expire={"function": "set_light", "args": {}},
        )
        assert "Aktion" in result["message"]

    @pytest.mark.asyncio
    async def test_persists_to_redis(self, tm_redis, redis_mock):
        await tm_redis.create_timer(5, label="Persist")
        redis_mock.hset.assert_called()

    @pytest.mark.asyncio
    async def test_watcher_task_created(self, tm_redis):
        result = await tm_redis.create_timer(5, label="Watch")
        tid = result["timer_id"]
        assert tid in tm_redis._tasks


# ── Cancel Timer ──────────────────────────────────────────────────────

class TestCancelTimer:

    @pytest.mark.asyncio
    async def test_cancel_by_id(self, tm_redis):
        result = await tm_redis.create_timer(5, label="Cancel Me")
        tid = result["timer_id"]
        cancel_result = await tm_redis.cancel_timer(timer_id=tid)
        assert cancel_result["success"] is True
        assert "Cancel Me" in cancel_result["message"]
        assert tid not in tm_redis.timers

    @pytest.mark.asyncio
    async def test_cancel_by_label(self, tm_redis):
        await tm_redis.create_timer(5, label="Pizza")
        cancel_result = await tm_redis.cancel_timer(label="pizza")
        assert cancel_result["success"] is True
        assert "Pizza" in cancel_result["message"]

    @pytest.mark.asyncio
    async def test_cancel_not_found(self, tm_redis):
        result = await tm_redis.cancel_timer(label="nonexistent")
        assert result["success"] is False
        assert "nicht gefunden" in result["message"]


# ── Get Status ────────────────────────────────────────────────────────

class TestGetStatus:

    def test_no_timers(self, tm):
        result = tm.get_status()
        assert result["success"] is True
        assert "Keine Timer" in result["message"]

    def test_with_active_timer(self, tm):
        t = GeneralTimer(id="a", label="Test", duration_seconds=300,
                         started_at=time.time())
        tm.timers["a"] = t
        result = tm.get_status()
        assert "Aktive Timer" in result["message"]
        assert "Test" in result["message"]
        assert result["active_count"] == 1

    def test_with_done_timer(self, tm):
        t = GeneralTimer(id="a", label="Done", duration_seconds=10,
                         started_at=time.time() - 20)
        tm.timers["a"] = t
        result = tm.get_status()
        assert "Abgelaufene Timer" in result["message"]

    def test_mixed_timers(self, tm):
        active = GeneralTimer(id="a", label="Active", duration_seconds=300,
                              started_at=time.time())
        done = GeneralTimer(id="b", label="Done", duration_seconds=10,
                            started_at=time.time() - 20)
        tm.timers["a"] = active
        tm.timers["b"] = done
        result = tm.get_status()
        assert "Aktive Timer" in result["message"]
        assert "Abgelaufene Timer" in result["message"]


# ── Context Hints ─────────────────────────────────────────────────────

class TestContextHints:

    def test_no_timers(self, tm):
        hints = tm.get_context_hints()
        assert hints == []

    def test_active_timer_hint(self, tm):
        t = GeneralTimer(id="a", label="Pizza", duration_seconds=300,
                         started_at=time.time())
        tm.timers["a"] = t
        hints = tm.get_context_hints()
        assert len(hints) == 1
        assert "Pizza" in hints[0]


# ── Timer Watcher ─────────────────────────────────────────────────────

class TestTimerWatcher:

    @pytest.mark.asyncio
    async def test_watcher_fires_notification(self, tm_redis):
        notify = AsyncMock()
        tm_redis.set_notify_callback(notify)

        timer = GeneralTimer(id="w1", label="Watcher", duration_seconds=0,
                             started_at=time.time() - 10)
        tm_redis.timers["w1"] = timer

        with patch("assistant.timer_manager.get_person_title", return_value="Sir"):
            await tm_redis._timer_watcher(timer)

        notify.assert_called()
        call_data = notify.call_args[0][0]
        assert call_data["type"] == "timer_expired"
        assert "Watcher" in call_data["message"]

    @pytest.mark.asyncio
    async def test_watcher_executes_whitelisted_action(self, tm_redis):
        notify = AsyncMock()
        action_cb = AsyncMock(return_value={"success": True})
        tm_redis.set_notify_callback(notify)
        tm_redis.set_action_callback(action_cb)

        timer = GeneralTimer(
            id="w2", label="Light Off", duration_seconds=0,
            started_at=time.time() - 10,
            action_on_expire={"function": "set_light", "args": {"state": "off"}},
        )
        tm_redis.timers["w2"] = timer

        with patch("assistant.timer_manager.get_person_title", return_value="Sir"):
            await tm_redis._timer_watcher(timer)

        action_cb.assert_called_once_with("set_light", {"state": "off"})

    @pytest.mark.asyncio
    async def test_watcher_blocks_non_whitelisted_action(self, tm_redis):
        notify = AsyncMock()
        action_cb = AsyncMock()
        tm_redis.set_notify_callback(notify)
        tm_redis.set_action_callback(action_cb)

        timer = GeneralTimer(
            id="w3", label="Blocked", duration_seconds=0,
            started_at=time.time() - 10,
            action_on_expire={"function": "lock_door", "args": {}},
        )
        tm_redis.timers["w3"] = timer

        with patch("assistant.timer_manager.get_person_title", return_value="Sir"):
            await tm_redis._timer_watcher(timer)

        action_cb.assert_not_called()
        # Should still notify about blocked action
        calls = notify.call_args_list
        blocked_calls = [c for c in calls if c[0][0].get("type") == "timer_action_blocked"]
        assert len(blocked_calls) == 1

    @pytest.mark.asyncio
    async def test_watcher_action_error_handled(self, tm_redis):
        notify = AsyncMock()
        action_cb = AsyncMock(side_effect=RuntimeError("fail"))
        tm_redis.set_notify_callback(notify)
        tm_redis.set_action_callback(action_cb)

        timer = GeneralTimer(
            id="w4", label="ErrTimer", duration_seconds=0,
            started_at=time.time() - 10,
            action_on_expire={"function": "set_light", "args": {}},
        )
        tm_redis.timers["w4"] = timer

        with patch("assistant.timer_manager.get_person_title", return_value="Sir"):
            await tm_redis._timer_watcher(timer)
        # Should not crash


# ── Create Reminder ───────────────────────────────────────────────────

class TestCreateReminder:

    @pytest.mark.asyncio
    async def test_invalid_time_format(self, tm):
        result = await tm.create_reminder("25:99", "Test")
        assert result["success"] is False
        assert "Ungültige Uhrzeit" in result["message"]

    @pytest.mark.asyncio
    async def test_past_date(self, tm):
        yesterday = (datetime.now(_TZ) - timedelta(days=2)).strftime("%Y-%m-%d")
        result = await tm.create_reminder("08:00", "Test", date_str=yesterday)
        assert result["success"] is False
        assert "Vergangenheit" in result["message"]

    @pytest.mark.asyncio
    async def test_too_far_future(self, tm):
        far_date = (datetime.now(_TZ) + timedelta(days=10)).strftime("%Y-%m-%d")
        result = await tm.create_reminder("08:00", "Test", date_str=far_date)
        assert result["success"] is False
        assert "7 Tage" in result["message"]

    @pytest.mark.asyncio
    async def test_successful_reminder_today(self, tm_redis):
        # Use a time 30 mins from now
        future = datetime.now(_TZ) + timedelta(minutes=30)
        time_str = future.strftime("%H:%M")
        result = await tm_redis.create_reminder(time_str, "Meeting")
        assert result["success"] is True
        assert "reminder_id" in result
        assert "Meeting" in result["message"]
        assert "heute" in result["message"]

    @pytest.mark.asyncio
    async def test_successful_reminder_tomorrow(self, tm_redis):
        # Use a time 1 minute ago — auto-shifts to tomorrow
        past = datetime.now(_TZ) - timedelta(minutes=1)
        time_str = past.strftime("%H:%M")
        result = await tm_redis.create_reminder(time_str, "Tomorrow")
        assert result["success"] is True
        assert "morgen" in result["message"]


# ── Set Wakeup Alarm ─────────────────────────────────────────────────

class TestSetWakeupAlarm:

    @pytest.mark.asyncio
    async def test_invalid_time(self, tm):
        result = await tm.set_wakeup_alarm("99:99")
        assert result["success"] is False
        assert "Ungültige Uhrzeit" in result["message"]

    @pytest.mark.asyncio
    async def test_success_einmalig(self, tm_redis):
        # Alarm for 1 min from now
        future = datetime.now(_TZ) + timedelta(minutes=1)
        time_str = future.strftime("%H:%M")
        result = await tm_redis.set_wakeup_alarm(time_str, label="Morgen-Wecker")
        assert result["success"] is True
        assert "alarm_id" in result
        assert time_str in result["message"]

    @pytest.mark.asyncio
    async def test_success_daily(self, tm_redis):
        future = datetime.now(_TZ) + timedelta(minutes=1)
        time_str = future.strftime("%H:%M")
        result = await tm_redis.set_wakeup_alarm(time_str, repeat="daily")
        assert result["success"] is True
        assert "taeglich" in result["message"]

    @pytest.mark.asyncio
    async def test_success_weekdays(self, tm_redis):
        future = datetime.now(_TZ) + timedelta(minutes=1)
        time_str = future.strftime("%H:%M")
        result = await tm_redis.set_wakeup_alarm(time_str, repeat="weekdays")
        assert result["success"] is True
        assert "Mo-Fr" in result["message"]

    @pytest.mark.asyncio
    async def test_success_weekends(self, tm_redis):
        future = datetime.now(_TZ) + timedelta(minutes=1)
        time_str = future.strftime("%H:%M")
        result = await tm_redis.set_wakeup_alarm(time_str, repeat="weekends")
        assert result["success"] is True
        assert "Sa-So" in result["message"]


# ── Cancel Alarm ──────────────────────────────────────────────────────

class TestCancelAlarm:

    @pytest.mark.asyncio
    async def test_cancel_by_id(self, tm_redis, redis_mock):
        future = datetime.now(_TZ) + timedelta(minutes=5)
        time_str = future.strftime("%H:%M")
        created = await tm_redis.set_wakeup_alarm(time_str, label="Cancel")
        aid = created["alarm_id"]

        result = await tm_redis.cancel_alarm(alarm_id=aid)
        assert result["success"] is True
        assert aid not in tm_redis.timers

    @pytest.mark.asyncio
    async def test_cancel_by_label(self, tm_redis, redis_mock):
        alarm_data = json.dumps({"label": "Morning", "active": True, "time": "07:00"})
        redis_mock.hgetall = AsyncMock(return_value={b"id1": alarm_data.encode()})

        # Also create in-memory timer
        t = GeneralTimer(id="id1", label="Morning", duration_seconds=600, started_at=time.time())
        tm_redis.timers["id1"] = t

        result = await tm_redis.cancel_alarm(label="Morning")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_cancel_auto_single(self, tm_redis, redis_mock):
        alarm_data = json.dumps({"label": "Only", "active": True})
        redis_mock.hgetall = AsyncMock(return_value={b"only1": alarm_data.encode()})

        result = await tm_redis.cancel_alarm()
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_cancel_multiple_ambiguous(self, tm_redis, redis_mock):
        alarm1 = json.dumps({"label": "A", "active": True})
        alarm2 = json.dumps({"label": "B", "active": True})
        redis_mock.hgetall = AsyncMock(return_value={
            b"a1": alarm1.encode(), b"b1": alarm2.encode(),
        })

        result = await tm_redis.cancel_alarm()
        assert result["success"] is False
        assert "Mehrere" in result["message"]

    @pytest.mark.asyncio
    async def test_cancel_not_found(self, tm_redis, redis_mock):
        redis_mock.hgetall = AsyncMock(return_value={})
        result = await tm_redis.cancel_alarm(label="nonexistent")
        assert result["success"] is False
        assert "nicht gefunden" in result["message"]


# ── Get Alarms ────────────────────────────────────────────────────────

class TestGetAlarms:

    @pytest.mark.asyncio
    async def test_no_redis(self, tm):
        result = await tm.get_alarms()
        assert result["success"] is True
        assert "Keine Wecker" in result["message"]

    @pytest.mark.asyncio
    async def test_no_alarms(self, tm_redis, redis_mock):
        redis_mock.hgetall = AsyncMock(return_value={})
        result = await tm_redis.get_alarms()
        assert "Keine Wecker" in result["message"]

    @pytest.mark.asyncio
    async def test_with_alarms(self, tm_redis, redis_mock):
        alarm = json.dumps({"label": "Morgen", "time": "07:00", "repeat": "daily", "active": True})
        redis_mock.hgetall = AsyncMock(return_value={b"a1": alarm.encode()})
        result = await tm_redis.get_alarms()
        assert result["success"] is True
        assert "07:00" in result["message"]
        assert "taeglich" in result["message"]

    @pytest.mark.asyncio
    async def test_inactive_alarms_excluded(self, tm_redis, redis_mock):
        alarm = json.dumps({"label": "Old", "time": "06:00", "repeat": "", "active": False})
        redis_mock.hgetall = AsyncMock(return_value={b"a1": alarm.encode()})
        result = await tm_redis.get_alarms()
        assert "Keine Wecker" in result["message"]

    @pytest.mark.asyncio
    async def test_redis_error(self, tm_redis, redis_mock):
        redis_mock.hgetall = AsyncMock(side_effect=ConnectionError("down"))
        result = await tm_redis.get_alarms()
        assert "Keine Wecker" in result["message"]


# ── Persistence ───────────────────────────────────────────────────────

class TestPersistence:

    @pytest.mark.asyncio
    async def test_persist_timer_no_redis(self, tm):
        timer = GeneralTimer(id="p1", label="Test", duration_seconds=60)
        await tm._persist_timer(timer)
        # No error

    @pytest.mark.asyncio
    async def test_persist_timer_with_redis(self, tm_redis, redis_mock):
        timer = GeneralTimer(id="p1", label="Test", duration_seconds=60)
        await tm_redis._persist_timer(timer)
        redis_mock.hset.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_timer_no_redis(self, tm):
        await tm._remove_timer("x")
        # No error

    @pytest.mark.asyncio
    async def test_remove_timer_with_redis(self, tm_redis, redis_mock):
        await tm_redis._remove_timer("x")
        redis_mock.hdel.assert_called_once_with(KEY_TIMERS, "x")


# ── Restore Timers ───────────────────────────────────────────────────

class TestRestoreTimers:

    @pytest.mark.asyncio
    async def test_restore_no_redis(self, tm):
        await tm._restore_timers()
        assert tm.timers == {}

    @pytest.mark.asyncio
    async def test_restore_empty(self, tm_redis, redis_mock):
        redis_mock.hgetall = AsyncMock(return_value={})
        await tm_redis._restore_timers()
        assert tm_redis.timers == {}

    @pytest.mark.asyncio
    async def test_restore_active_timer(self, tm_redis, redis_mock):
        timer_data = {
            "id": "r1", "label": "Restored", "duration_seconds": 600,
            "started_at": time.time() - 10, "finished": False,
        }
        redis_mock.hgetall = AsyncMock(return_value={
            b"r1": json.dumps(timer_data).encode(),
        })
        await tm_redis._restore_timers()
        assert "r1" in tm_redis.timers

    @pytest.mark.asyncio
    async def test_restore_expired_timer_removed(self, tm_redis, redis_mock):
        timer_data = {
            "id": "old", "label": "Old", "duration_seconds": 10,
            "started_at": time.time() - 100, "finished": False,
        }
        redis_mock.hgetall = AsyncMock(return_value={
            b"old": json.dumps(timer_data).encode(),
        })
        await tm_redis._restore_timers()
        assert "old" not in tm_redis.timers
        redis_mock.hdel.assert_called()

    @pytest.mark.asyncio
    async def test_restore_error_handled(self, tm_redis, redis_mock):
        redis_mock.hgetall = AsyncMock(side_effect=ConnectionError("down"))
        await tm_redis._restore_timers()
        # Should not crash


# ── Timer Action Whitelist ───────────────────────────────────────────

class TestTimerActionWhitelist:

    def test_whitelist_contains_safe_actions(self):
        assert "set_light" in TIMER_ACTION_WHITELIST
        assert "set_climate" in TIMER_ACTION_WHITELIST
        assert "play_media" in TIMER_ACTION_WHITELIST

    def test_whitelist_excludes_dangerous_actions(self):
        assert "lock_door" not in TIMER_ACTION_WHITELIST
        assert "unlock_door" not in TIMER_ACTION_WHITELIST
        assert "arm_security_system" not in TIMER_ACTION_WHITELIST

    def test_is_frozenset(self):
        assert isinstance(TIMER_ACTION_WHITELIST, frozenset)


# ── Reminders Status ─────────────────────────────────────────────────

class TestRemindersStatus:

    def test_no_reminders(self, tm):
        result = tm.get_reminders_status()
        assert result["success"] is True
        assert "Keine aktiven" in result["message"]

    def test_with_active_reminder(self, tm):
        t = GeneralTimer(id="r1", label="Meeting", duration_seconds=600,
                         started_at=time.time())
        tm.timers["r1"] = t
        result = tm.get_reminders_status()
        assert "Meeting" in result["message"]
