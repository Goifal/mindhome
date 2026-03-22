"""
Tests fuer TimerManager — Timer, Format, Validierung, Cancel.

Testet:
- GeneralTimer Dataclass (remaining, format, to_dict/from_dict)
- TimerManager.create_timer() (Validierung, Limits, Aktionen)
- TimerManager.cancel_timer() (per ID und Label)
- TIMER_ACTION_WHITELIST (Sicherheit)
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.timer_manager import (
    GeneralTimer,
    TimerManager,
    TIMER_ACTION_WHITELIST,
)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def manager():
    mgr = TimerManager()
    mgr.redis = AsyncMock()
    mgr.redis.hset = AsyncMock()
    mgr.redis.hdel = AsyncMock()
    mgr.redis.hgetall = AsyncMock(return_value={})
    mgr.redis.get = AsyncMock(return_value=None)
    mgr.redis.set = AsyncMock()
    mgr.redis.delete = AsyncMock()
    return mgr


# ============================================================
# GeneralTimer Dataclass
# ============================================================


class TestGeneralTimer:
    def test_new_timer_not_started(self):
        t = GeneralTimer(id="t1", label="Test", duration_seconds=60)
        assert t.started_at == 0.0
        assert t.finished is False
        assert t.remaining_seconds == 0.0

    def test_start_sets_time(self):
        t = GeneralTimer(id="t1", label="Test", duration_seconds=60)
        t.start()
        assert t.started_at > 0
        assert not t.finished

    def test_remaining_seconds_decreases(self):
        t = GeneralTimer(id="t1", label="Test", duration_seconds=60)
        t.started_at = time.time() - 30  # 30s ago
        remaining = t.remaining_seconds
        assert 29 <= remaining <= 31

    def test_remaining_seconds_zero_when_done(self):
        t = GeneralTimer(id="t1", label="Test", duration_seconds=60)
        t.started_at = time.time() - 120  # 2 min ago, timer was 1 min
        assert t.remaining_seconds == 0.0

    def test_is_done_when_expired(self):
        t = GeneralTimer(id="t1", label="Test", duration_seconds=10)
        t.started_at = time.time() - 20
        assert t.is_done is True

    def test_is_done_when_finished_flag(self):
        t = GeneralTimer(id="t1", label="Test", duration_seconds=600)
        t.started_at = time.time()
        t.finished = True
        assert t.is_done is True

    def test_not_done_while_running(self):
        t = GeneralTimer(id="t1", label="Test", duration_seconds=600)
        t.started_at = time.time()
        assert t.is_done is False

    def test_format_remaining_minutes(self):
        t = GeneralTimer(id="t1", label="Test", duration_seconds=300)
        t.started_at = time.time()
        formatted = t.format_remaining()
        assert "Minute" in formatted

    def test_format_remaining_hours_and_minutes(self):
        t = GeneralTimer(id="t1", label="Test", duration_seconds=3900)  # 65 min
        t.started_at = time.time()
        formatted = t.format_remaining()
        assert "Stunde" in formatted
        assert "Minute" in formatted

    def test_format_remaining_abgelaufen(self):
        t = GeneralTimer(id="t1", label="Test", duration_seconds=10)
        t.started_at = time.time() - 20
        assert t.format_remaining() == "abgelaufen"

    def test_to_dict(self):
        t = GeneralTimer(
            id="t1", label="Pizza", duration_seconds=600, room="kueche", person="Max"
        )
        t.start()
        d = t.to_dict()
        assert d["id"] == "t1"
        assert d["label"] == "Pizza"
        assert d["duration_seconds"] == 600
        assert d["room"] == "kueche"
        assert d["person"] == "Max"
        assert d["started_at"] > 0

    def test_from_dict(self):
        data = {
            "id": "t2",
            "label": "Waesche",
            "duration_seconds": 1800,
            "room": "bad",
            "person": "Lisa",
            "started_at": time.time() - 100,
            "finished": False,
        }
        t = GeneralTimer.from_dict(data)
        assert t.id == "t2"
        assert t.label == "Waesche"
        assert t.room == "bad"

    def test_from_dict_missing_optional(self):
        data = {"id": "t3", "label": "Quick", "duration_seconds": 60}
        t = GeneralTimer.from_dict(data)
        assert t.room == ""
        assert t.person == ""
        assert t.action_on_expire is None

    def test_remaining_seconds_display_rounded(self):
        t = GeneralTimer(id="t1", label="Test", duration_seconds=60)
        t.started_at = time.time()
        display = t.remaining_seconds_display
        assert isinstance(display, int)
        assert 58 <= display <= 61


# ============================================================
# TimerManager.create_timer
# ============================================================


class TestCreateTimer:
    @pytest.mark.asyncio
    async def test_create_basic_timer(self, manager):
        result = await manager.create_timer(duration_minutes=5, label="Test")
        assert result["success"] is True
        assert "timer_id" in result
        assert "5 Minuten" in result["message"]

    @pytest.mark.asyncio
    async def test_create_1_minute_singular(self, manager):
        result = await manager.create_timer(duration_minutes=1, label="Quick")
        assert result["success"] is True
        assert "1 Minute" in result["message"]

    @pytest.mark.asyncio
    async def test_create_timer_with_hours(self, manager):
        result = await manager.create_timer(duration_minutes=90, label="Lang")
        assert result["success"] is True
        assert "Stunde" in result["message"]
        assert "30 Minuten" in result["message"]

    @pytest.mark.asyncio
    async def test_reject_zero_minutes(self, manager):
        result = await manager.create_timer(duration_minutes=0, label="Bad")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_reject_over_1440_minutes(self, manager):
        result = await manager.create_timer(duration_minutes=1441, label="Too long")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_default_label_if_empty(self, manager):
        result = await manager.create_timer(duration_minutes=10)
        assert result["success"] is True
        assert "10 Min" in result["message"]

    @pytest.mark.asyncio
    async def test_action_on_expire_hint(self, manager):
        action = {"function": "set_light", "args": {"room": "kueche", "state": "off"}}
        result = await manager.create_timer(
            duration_minutes=5,
            label="Kueche",
            action_on_expire=action,
        )
        assert result["success"] is True
        assert "Aktion" in result["message"]

    @pytest.mark.asyncio
    async def test_timer_stored_in_dict(self, manager):
        result = await manager.create_timer(duration_minutes=5, label="Stored")
        timer_id = result["timer_id"]
        assert timer_id in manager.timers
        assert manager.timers[timer_id].label == "Stored"


# ============================================================
# TimerManager.cancel_timer
# ============================================================


class TestCancelTimer:
    @pytest.mark.asyncio
    async def test_cancel_by_id(self, manager):
        result = await manager.create_timer(duration_minutes=5, label="CancelMe")
        timer_id = result["timer_id"]
        cancel_result = await manager.cancel_timer(timer_id=timer_id)
        assert cancel_result["success"] is True

    @pytest.mark.asyncio
    async def test_cancel_by_label(self, manager):
        await manager.create_timer(duration_minutes=5, label="Pizza Timer")
        cancel_result = await manager.cancel_timer(label="pizza")
        assert cancel_result["success"] is True

    @pytest.mark.asyncio
    async def test_cancel_unknown_timer(self, manager):
        result = await manager.cancel_timer(timer_id="nonexistent")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_cancel_empty_args(self, manager):
        result = await manager.cancel_timer()
        assert result["success"] is False


# ============================================================
# TIMER_ACTION_WHITELIST
# ============================================================


class TestTimerActionWhitelist:
    def test_safe_actions_present(self):
        for action in ["set_light", "set_climate", "set_cover", "play_media"]:
            assert action in TIMER_ACTION_WHITELIST

    def test_dangerous_actions_absent(self):
        for action in [
            "lock_door",
            "unlock_door",
            "arm_security_system",
            "factory_reset",
            "delete_all",
        ]:
            assert action not in TIMER_ACTION_WHITELIST

    def test_whitelist_is_frozenset(self):
        assert isinstance(TIMER_ACTION_WHITELIST, frozenset)
