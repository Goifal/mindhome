"""
Tests fuer WellnessAdvisor — Wellness-Checks, Ambient Actions, Pattern Learning.
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.wellness_advisor import WellnessAdvisor, _safe_redis


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def activity_mock():
    mock = AsyncMock()
    mock.detect_activity = AsyncMock(return_value={"activity": "focused"})
    return mock


@pytest.fixture
def mood_mock():
    mock = MagicMock()
    mock.get_current_mood = MagicMock(return_value={
        "mood": "neutral",
        "stress_level": 0.0,
    })
    mock.get_mood_trend = MagicMock(return_value="stable")
    mock.execute_suggested_actions = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def advisor(ha_mock, activity_mock, mood_mock, redis_mock):
    a = WellnessAdvisor(ha_mock, activity_mock, mood_mock)
    a.redis = redis_mock
    a._notify_callback = AsyncMock()
    return a


# ── _safe_redis ───────────────────────────────────────────────────────

class TestSafeRedis:

    @pytest.mark.asyncio
    async def test_returns_result_on_success(self, redis_mock):
        redis_mock.get = AsyncMock(return_value="value")
        result = await _safe_redis(redis_mock, "get", "key")
        assert result == "value"

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self, redis_mock):
        redis_mock.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        result = await _safe_redis(redis_mock, "get", "key")
        assert result is None

    @pytest.mark.asyncio
    async def test_setex_survives_failure(self, redis_mock):
        redis_mock.setex = AsyncMock(side_effect=ConnectionError("Redis down"))
        result = await _safe_redis(redis_mock, "setex", "key", 100, "value")
        assert result is None  # Kein Crash


# ── Stress Intervention ──────────────────────────────────────────────

class TestStressIntervention:

    @pytest.mark.asyncio
    async def test_no_nudge_when_neutral(self, advisor, mood_mock):
        mood_mock.get_current_mood.return_value = {"mood": "neutral", "stress_level": 0.1}
        await advisor._check_stress_intervention()
        advisor._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_nudge_when_stressed(self, advisor, mood_mock, redis_mock):
        mood_mock.get_current_mood.return_value = {"mood": "stressed", "stress_level": 0.8}
        redis_mock.get = AsyncMock(return_value=None)
        await advisor._check_stress_intervention()
        advisor._notify_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_declining_trend_shorter_cooldown(self, advisor, mood_mock, redis_mock):
        mood_mock.get_current_mood.return_value = {"mood": "stressed", "stress_level": 0.5}
        mood_mock.get_mood_trend.return_value = "declining"
        # Last nudge was 20 min ago — within 30 min cooldown but outside 15 min
        twenty_min_ago = (datetime.now() - timedelta(minutes=20)).isoformat()
        redis_mock.get = AsyncMock(return_value=twenty_min_ago)
        await advisor._check_stress_intervention()
        # Mit declining Trend: 15 Min Cooldown → 20 Min her → SOLLTE feuern
        advisor._notify_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_trend_hint_in_message(self, advisor, mood_mock, redis_mock):
        mood_mock.get_current_mood.return_value = {"mood": "stressed", "stress_level": 0.8}
        mood_mock.get_mood_trend.return_value = "declining"
        redis_mock.get = AsyncMock(return_value=None)
        await advisor._check_stress_intervention()
        call_args = advisor._notify_callback.call_args[0]
        msg = call_args[1]
        assert "absteigende Tendenz" in msg


# ── Late Night Pattern ───────────────────────────────────────────────

class TestLateNightPattern:

    @pytest.mark.asyncio
    async def test_track_first_night_returns_1(self, advisor, redis_mock):
        redis_mock.sismember = AsyncMock(return_value=False)
        result = await advisor._track_late_night_pattern()
        assert result == 1

    @pytest.mark.asyncio
    async def test_track_consecutive_nights(self, advisor, redis_mock):
        today = datetime.now().date().isoformat()
        yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()

        async def sismember_side_effect(key, date_str):
            return date_str in (today, yesterday)

        redis_mock.sismember = AsyncMock(side_effect=sismember_side_effect)
        result = await advisor._track_late_night_pattern()
        assert result >= 2


# ── Mood Ambient Actions ─────────────────────────────────────────────

class TestMoodAmbientActions:

    @pytest.mark.asyncio
    async def test_no_action_when_neutral(self, advisor, mood_mock):
        mood_mock.get_current_mood.return_value = {"mood": "neutral"}
        await advisor._check_mood_ambient_actions()
        mood_mock.execute_suggested_actions.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_action_without_executor(self, advisor, mood_mock):
        mood_mock.get_current_mood.return_value = {"mood": "stressed"}
        advisor.executor = None
        await advisor._check_mood_ambient_actions()
        mood_mock.execute_suggested_actions.assert_not_called()

    @pytest.mark.asyncio
    async def test_executes_when_stressed(self, advisor, mood_mock, redis_mock):
        mood_mock.get_current_mood.return_value = {"mood": "stressed"}
        advisor.executor = AsyncMock()
        mood_mock.execute_suggested_actions = AsyncMock(return_value=[
            {"action": "light.dimmen", "reason": "test", "result": {}},
        ])
        redis_mock.get = AsyncMock(return_value=None)
        await advisor._check_mood_ambient_actions()
        mood_mock.execute_suggested_actions.assert_called_once()
        advisor._notify_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_cooldown_prevents_spam(self, advisor, mood_mock, redis_mock):
        mood_mock.get_current_mood.return_value = {"mood": "stressed"}
        advisor.executor = AsyncMock()
        # Last action 10 min ago — within 30 min cooldown
        recent = (datetime.now() - timedelta(minutes=10)).isoformat()
        redis_mock.get = AsyncMock(return_value=recent)
        await advisor._check_mood_ambient_actions()
        mood_mock.execute_suggested_actions.assert_not_called()


# ── Hydration ─────────────────────────────────────────────────────────

class TestHydration:

    @pytest.mark.asyncio
    async def test_no_reminder_at_night(self, advisor):
        with patch("assistant.wellness_advisor.datetime") as dt_mock:
            dt_mock.now.return_value = datetime(2026, 3, 3, 3, 0)
            dt_mock.fromisoformat = datetime.fromisoformat
            await advisor._check_hydration()
        advisor._notify_callback.assert_not_called()


# ------------------------------------------------------------------
# Phase 11: Erweiterte Wellness-Features
# ------------------------------------------------------------------


class TestPhase11ExtendedWellness:

    @pytest.fixture
    def advisor(self, ha_mock, activity_mock, mood_mock):
        cfg = {"wellness": {"enabled": True}}
        with patch("assistant.wellness_advisor.yaml_config", cfg):
            w = WellnessAdvisor(ha_mock, activity_mock, mood_mock)
            w.redis = AsyncMock()
            w._notify_callback = AsyncMock()
            return w

    @pytest.mark.asyncio
    async def test_wellness_summary_default(self, advisor):
        advisor.redis.get = AsyncMock(return_value=None)
        result = await advisor.get_wellness_summary()
        assert result["score"] == 100
        assert result["hints"] == []

    @pytest.mark.asyncio
    async def test_wellness_summary_stressed(self, advisor):
        advisor.redis.get = AsyncMock(return_value=None)
        advisor.mood._current_mood = "stressed"
        result = await advisor.get_wellness_summary()
        assert result["score"] < 100
        assert any("Stimmung" in h for h in result["hints"])

    @pytest.mark.asyncio
    async def test_suggest_micro_break_pc(self, advisor):
        suggestion = await advisor.suggest_micro_break("pc")
        assert suggestion is not None
        assert len(suggestion) > 10

    @pytest.mark.asyncio
    async def test_suggest_micro_break_default(self, advisor):
        suggestion = await advisor.suggest_micro_break()
        assert suggestion is not None

    @pytest.mark.asyncio
    async def test_ambient_suggestion_no_mood(self, advisor):
        advisor.mood = None
        result = await advisor.get_ambient_suggestion()
        assert result is None

    @pytest.mark.asyncio
    async def test_ambient_suggestion_stressed(self, advisor):
        advisor.mood._current_mood = "stressed"
        result = await advisor.get_ambient_suggestion()
        assert result is not None
        assert "Licht" in result["action"]

    @pytest.mark.asyncio
    async def test_ambient_suggestion_neutral(self, advisor):
        advisor.mood._current_mood = "neutral"
        result = await advisor.get_ambient_suggestion()
        assert result is None
