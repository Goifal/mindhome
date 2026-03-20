"""
Tests fuer WellnessAdvisor — Wellness-Checks, Ambient Actions, Pattern Learning.
"""

import asyncio
from datetime import datetime, timedelta, timezone
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
        twenty_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
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
        today = datetime.now(timezone.utc).date().isoformat()
        yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()

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
        recent = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        redis_mock.get = AsyncMock(return_value=recent)
        await advisor._check_mood_ambient_actions()
        mood_mock.execute_suggested_actions.assert_not_called()


# ── Hydration ─────────────────────────────────────────────────────────

class TestHydration:

    @pytest.mark.asyncio
    async def test_no_reminder_at_night(self, advisor):
        with patch("assistant.wellness_advisor.datetime") as dt_mock:
            dt_mock.now.return_value = datetime(2026, 3, 3, 3, 0, tzinfo=timezone.utc)
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


# =====================================================================
# PC Break Reminders (comprehensive)
# =====================================================================


class TestPCBreakComprehensive:

    @pytest.fixture
    def advisor(self, ha_mock, activity_mock, mood_mock, redis_mock):
        cfg = {
            "wellness": {
                "enabled": True,
                "pc_break_reminder_minutes": 120,
                "entities": {"pc_power": "sensor.pc_power"},
                "hydration_reminder": True,
                "hydration_interval_hours": 2,
            },
            "timezone": "Europe/Berlin",
            "persons": {"titles": {"max": "Sir"}},
            "household": {"primary_user": "Max"},
        }
        with patch("assistant.wellness_advisor.yaml_config", cfg), \
             patch("assistant.wellness_advisor.get_person_title", return_value="Sir"):
            w = WellnessAdvisor(ha_mock, activity_mock, mood_mock)
        w.redis = redis_mock
        w._notify_callback = AsyncMock()
        w._ollama = None
        return w

    @pytest.mark.asyncio
    async def test_no_redis_returns_early(self, advisor):
        advisor.redis = None
        await advisor._check_pc_break()
        advisor._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_user_not_at_pc_resets_timer(self, advisor, ha_mock, activity_mock, redis_mock):
        """When PC power is low and activity is not focused, timer is deleted."""
        ha_mock.get_state = AsyncMock(return_value={"state": "5"})  # 5W < 30W
        activity_mock.detect_activity = AsyncMock(return_value={"activity": "relaxing"})
        await advisor._check_pc_break()
        redis_mock.delete.assert_called()
        advisor._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_pc_detected_via_power_sensor_starts_timer(self, advisor, ha_mock, redis_mock):
        """When PC power > 30W and no prior start, timer is set."""
        ha_mock.get_state = AsyncMock(return_value={"state": "150"})
        redis_mock.get = AsyncMock(return_value=None)
        await advisor._check_pc_break()
        redis_mock.setex.assert_called()
        advisor._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_pc_break_reminder_after_threshold(self, advisor, ha_mock, redis_mock):
        """After pc_break_minutes, a nudge is sent."""
        ha_mock.get_state = AsyncMock(return_value={"state": "150"})
        three_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()

        async def get_side_effect(key):
            if "pc_start" in key:
                return three_hours_ago
            return None

        redis_mock.get = AsyncMock(side_effect=get_side_effect)
        await advisor._check_pc_break()
        advisor._notify_callback.assert_called_once()
        call_args = advisor._notify_callback.call_args[0]
        assert call_args[0] == "pc_break"

    @pytest.mark.asyncio
    async def test_pc_break_cooldown_prevents_repeat(self, advisor, ha_mock, redis_mock):
        """Within 1h cooldown, no second reminder is sent."""
        ha_mock.get_state = AsyncMock(return_value={"state": "150"})
        three_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        recent = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()

        async def get_side_effect(key):
            if "pc_start" in key:
                return three_hours_ago
            if "last_break_reminder" in key:
                return recent
            return None

        redis_mock.get = AsyncMock(side_effect=get_side_effect)
        await advisor._check_pc_break()
        advisor._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_pc_break_stressed_mood_higher_urgency(self, advisor, ha_mock, mood_mock, redis_mock):
        """When user is stressed and at PC 2h+, urgency is medium."""
        ha_mock.get_state = AsyncMock(return_value={"state": "150"})
        mood_mock.get_current_mood.return_value = {"mood": "stressed", "stress_level": 0.7}
        three_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()

        async def get_side_effect(key):
            if "pc_start" in key:
                return three_hours_ago
            return None

        redis_mock.get = AsyncMock(side_effect=get_side_effect)
        await advisor._check_pc_break()
        advisor._notify_callback.assert_called_once()
        call_args = advisor._notify_callback.call_args[0]
        assert call_args[2] == "medium"

    @pytest.mark.asyncio
    async def test_pc_break_tired_mood_medium_urgency(self, advisor, ha_mock, mood_mock, redis_mock):
        """When user is tired, urgency is medium."""
        ha_mock.get_state = AsyncMock(return_value={"state": "150"})
        mood_mock.get_current_mood.return_value = {"mood": "tired", "stress_level": 0.1}
        three_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()

        async def get_side_effect(key):
            if "pc_start" in key:
                return three_hours_ago
            return None

        redis_mock.get = AsyncMock(side_effect=get_side_effect)
        await advisor._check_pc_break()
        advisor._notify_callback.assert_called_once()
        call_args = advisor._notify_callback.call_args[0]
        assert call_args[2] == "medium"

    @pytest.mark.asyncio
    async def test_pc_break_fallback_to_activity_engine(self, advisor, activity_mock, redis_mock):
        """When PC power sensor not configured, falls back to activity engine."""
        advisor.pc_power_sensor = ""
        activity_mock.detect_activity = AsyncMock(return_value={"activity": "focused"})
        redis_mock.get = AsyncMock(return_value=None)
        await advisor._check_pc_break()
        activity_mock.detect_activity.assert_called_once()
        redis_mock.setex.assert_called()

    @pytest.mark.asyncio
    async def test_pc_break_invalid_start_time_resets(self, advisor, ha_mock, redis_mock):
        """Invalid pc_start value resets the timer."""
        ha_mock.get_state = AsyncMock(return_value={"state": "150"})

        async def get_side_effect(key):
            if "pc_start" in key:
                return "not-a-valid-date"
            return None

        redis_mock.get = AsyncMock(side_effect=get_side_effect)
        await advisor._check_pc_break()
        redis_mock.setex.assert_called()
        advisor._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_pc_break_bytes_from_redis(self, advisor, ha_mock, redis_mock):
        """Redis returns bytes — should decode correctly."""
        ha_mock.get_state = AsyncMock(return_value={"state": "150"})
        three_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()

        async def get_side_effect(key):
            if "pc_start" in key:
                return three_hours_ago.encode()  # bytes
            return None

        redis_mock.get = AsyncMock(side_effect=get_side_effect)
        await advisor._check_pc_break()
        advisor._notify_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_pc_power_sensor_unavailable(self, advisor, ha_mock, activity_mock, redis_mock):
        """When PC power sensor returns 'unavailable', fall back to activity."""
        ha_mock.get_state = AsyncMock(return_value={"state": "unavailable"})
        activity_mock.detect_activity = AsyncMock(return_value={"activity": "focused"})
        redis_mock.get = AsyncMock(return_value=None)
        await advisor._check_pc_break()
        activity_mock.detect_activity.assert_called_once()

    @pytest.mark.asyncio
    async def test_pc_break_activity_detection_failure(self, advisor, redis_mock):
        """When activity detection fails, return early without crash."""
        advisor.pc_power_sensor = ""
        advisor.activity.detect_activity = AsyncMock(side_effect=RuntimeError("fail"))
        await advisor._check_pc_break()
        advisor._notify_callback.assert_not_called()


# =====================================================================
# Stress Intervention (comprehensive)
# =====================================================================


class TestStressInterventionComprehensive:

    @pytest.fixture
    def advisor(self, ha_mock, activity_mock, mood_mock, redis_mock):
        cfg = {
            "wellness": {"enabled": True, "stress_check": True},
            "timezone": "Europe/Berlin",
            "persons": {"titles": {"max": "Sir"}},
            "household": {"primary_user": "Max"},
        }
        with patch("assistant.wellness_advisor.yaml_config", cfg), \
             patch("assistant.wellness_advisor.get_person_title", return_value="Sir"):
            w = WellnessAdvisor(ha_mock, activity_mock, mood_mock)
        w.redis = redis_mock
        w._notify_callback = AsyncMock()
        w._ollama = None
        return w

    @pytest.mark.asyncio
    async def test_stress_check_disabled(self, advisor, mood_mock):
        advisor.stress_check = False
        mood_mock.get_current_mood.return_value = {"mood": "stressed", "stress_level": 0.8}
        await advisor._check_stress_intervention()
        advisor._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_redis_returns_early(self, advisor, mood_mock):
        advisor.redis = None
        mood_mock.get_current_mood.return_value = {"mood": "stressed", "stress_level": 0.8}
        await advisor._check_stress_intervention()
        advisor._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_frustrated_sends_nudge(self, advisor, mood_mock, redis_mock):
        """Frustrated mood also triggers intervention."""
        mood_mock.get_current_mood.return_value = {"mood": "frustrated", "stress_level": 0.4}
        redis_mock.get = AsyncMock(return_value=None)
        await advisor._check_stress_intervention()
        advisor._notify_callback.assert_called_once()
        assert advisor._notify_callback.call_args[0][0] == "stress_detected"

    @pytest.mark.asyncio
    async def test_high_stress_medium_urgency(self, advisor, mood_mock, redis_mock):
        """High stress level (>=0.7) yields medium urgency."""
        mood_mock.get_current_mood.return_value = {"mood": "stressed", "stress_level": 0.8}
        redis_mock.get = AsyncMock(return_value=None)
        await advisor._check_stress_intervention()
        call_args = advisor._notify_callback.call_args[0]
        assert call_args[2] == "medium"

    @pytest.mark.asyncio
    async def test_cooldown_prevents_duplicate(self, advisor, mood_mock, redis_mock):
        """Within cooldown window, no second nudge."""
        mood_mock.get_current_mood.return_value = {"mood": "stressed", "stress_level": 0.5}
        recent = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        redis_mock.get = AsyncMock(return_value=recent)
        await advisor._check_stress_intervention()
        advisor._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_stress_cooldown_bytes_from_redis(self, advisor, mood_mock, redis_mock):
        """Redis returning bytes for cooldown — decoded correctly."""
        mood_mock.get_current_mood.return_value = {"mood": "stressed", "stress_level": 0.5}
        recent = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat().encode()
        redis_mock.get = AsyncMock(return_value=recent)
        await advisor._check_stress_intervention()
        advisor._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_expired_cooldown_allows_nudge(self, advisor, mood_mock, redis_mock):
        """After cooldown expires (30min default), nudge fires again."""
        mood_mock.get_current_mood.return_value = {"mood": "stressed", "stress_level": 0.5}
        old = (datetime.now(timezone.utc) - timedelta(minutes=35)).isoformat()
        redis_mock.get = AsyncMock(return_value=old)
        await advisor._check_stress_intervention()
        advisor._notify_callback.assert_called_once()


# =====================================================================
# Hydration Reminders (comprehensive)
# =====================================================================


class TestHydrationComprehensive:

    @pytest.fixture
    def advisor(self, ha_mock, activity_mock, mood_mock, redis_mock):
        cfg = {
            "wellness": {
                "enabled": True,
                "hydration_reminder": True,
                "hydration_interval_hours": 2,
            },
            "timezone": "Europe/Berlin",
            "persons": {"titles": {"max": "Sir"}},
            "household": {"primary_user": "Max"},
        }
        with patch("assistant.wellness_advisor.yaml_config", cfg), \
             patch("assistant.wellness_advisor.get_person_title", return_value="Sir"):
            w = WellnessAdvisor(ha_mock, activity_mock, mood_mock)
        w.redis = redis_mock
        w._notify_callback = AsyncMock()
        w._ollama = None
        return w

    @pytest.mark.asyncio
    async def test_hydration_disabled(self, advisor):
        advisor.hydration_check = False
        await advisor._check_hydration()
        advisor._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_redis_returns_early(self, advisor):
        advisor.redis = None
        await advisor._check_hydration()
        advisor._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_user_sleeping_skipped(self, advisor, activity_mock, redis_mock):
        """No reminder if user is sleeping."""
        redis_mock.get = AsyncMock(return_value=None)
        activity_mock.detect_activity = AsyncMock(return_value={"activity": "sleeping"})
        with patch("assistant.wellness_advisor.datetime") as mock_dt:
            from assistant.wellness_advisor import _LOCAL_TZ
            mock_dt.now.return_value = datetime(2026, 3, 20, 14, 0, tzinfo=_LOCAL_TZ)
            mock_dt.fromisoformat = datetime.fromisoformat
            await advisor._check_hydration()
        advisor._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_hydration_sends_nudge_when_due(self, advisor, activity_mock, redis_mock):
        """Hydration nudge sent when interval elapsed and user active."""
        old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        redis_mock.get = AsyncMock(return_value=old)
        activity_mock.detect_activity = AsyncMock(return_value={"activity": "focused"})
        with patch("assistant.wellness_advisor.datetime") as mock_dt:
            from assistant.wellness_advisor import _LOCAL_TZ
            mock_dt.now.return_value = datetime(2026, 3, 20, 14, 0, tzinfo=_LOCAL_TZ)
            mock_dt.fromisoformat = datetime.fromisoformat
            await advisor._check_hydration()
        advisor._notify_callback.assert_called_once()
        assert advisor._notify_callback.call_args[0][0] == "hydration"

    @pytest.mark.asyncio
    async def test_hydration_stressed_short_message(self, advisor, mood_mock, activity_mock, redis_mock):
        """When stressed, hydration message is terse ('Wasser')."""
        mood_mock.get_current_mood.return_value = {"mood": "stressed", "stress_level": 0.7}
        old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        redis_mock.get = AsyncMock(return_value=old)
        activity_mock.detect_activity = AsyncMock(return_value={"activity": "focused"})
        with patch("assistant.wellness_advisor.datetime") as mock_dt:
            from assistant.wellness_advisor import _LOCAL_TZ
            mock_dt.now.return_value = datetime(2026, 3, 20, 14, 0, tzinfo=_LOCAL_TZ)
            mock_dt.fromisoformat = datetime.fromisoformat
            await advisor._check_hydration()
        call_msg = advisor._notify_callback.call_args[0][1]
        assert "Wasser" in call_msg

    @pytest.mark.asyncio
    async def test_hydration_activity_detection_failure(self, advisor, activity_mock, redis_mock):
        """Activity detection failure prevents nudge (graceful)."""
        redis_mock.get = AsyncMock(return_value=None)
        activity_mock.detect_activity = AsyncMock(side_effect=RuntimeError("fail"))
        with patch("assistant.wellness_advisor.datetime") as mock_dt:
            from assistant.wellness_advisor import _LOCAL_TZ
            mock_dt.now.return_value = datetime(2026, 3, 20, 14, 0, tzinfo=_LOCAL_TZ)
            mock_dt.fromisoformat = datetime.fromisoformat
            await advisor._check_hydration()
        advisor._notify_callback.assert_not_called()


# =====================================================================
# Send Nudge
# =====================================================================


class TestSendNudge:

    @pytest.fixture
    def advisor(self, ha_mock, activity_mock, mood_mock, redis_mock):
        cfg = {
            "wellness": {"enabled": True},
            "timezone": "Europe/Berlin",
        }
        with patch("assistant.wellness_advisor.yaml_config", cfg), \
             patch("assistant.wellness_advisor.get_person_title", return_value="Sir"):
            w = WellnessAdvisor(ha_mock, activity_mock, mood_mock)
        w.redis = redis_mock
        w._notify_callback = AsyncMock()
        w._ollama = None
        return w

    @pytest.mark.asyncio
    async def test_no_callback_logs_only(self, advisor):
        advisor._notify_callback = None
        await advisor._send_nudge("test", "message")
        # Should not raise

    @pytest.mark.asyncio
    async def test_callback_receives_correct_args(self, advisor):
        advisor.ha = None  # Skip conflict check
        await advisor._send_nudge("pc_break", "Take a break", "medium")
        advisor._notify_callback.assert_called_once_with("pc_break", "Take a break", "medium")

    @pytest.mark.asyncio
    async def test_callback_exception_handled(self, advisor):
        advisor.ha = None
        advisor._notify_callback = AsyncMock(side_effect=RuntimeError("oops"))
        # Should not raise
        await advisor._send_nudge("test", "msg")

    @pytest.mark.asyncio
    async def test_default_urgency_is_low(self, advisor):
        advisor.ha = None
        await advisor._send_nudge("test", "msg")
        advisor._notify_callback.assert_called_once_with("test", "msg", "low")


# =====================================================================
# Config & Lifecycle
# =====================================================================


class TestConfigLifecycle:

    @pytest.fixture
    def advisor(self, ha_mock, activity_mock, mood_mock, redis_mock):
        cfg = {
            "wellness": {"enabled": True},
            "timezone": "Europe/Berlin",
        }
        with patch("assistant.wellness_advisor.yaml_config", cfg), \
             patch("assistant.wellness_advisor.get_person_title", return_value="Sir"):
            w = WellnessAdvisor(ha_mock, activity_mock, mood_mock)
        w.redis = redis_mock
        return w

    @pytest.mark.asyncio
    async def test_initialize_sets_redis(self, advisor, redis_mock):
        advisor.redis = None
        await advisor.initialize(redis_client=redis_mock)
        assert advisor.redis is redis_mock

    def test_reload_config(self, advisor):
        new_cfg = {
            "enabled": False,
            "check_interval_minutes": 30,
            "pc_break_reminder_minutes": 60,
            "stress_check": False,
            "meal_reminders": False,
            "meal_times": {"lunch": 12, "dinner": 18},
            "late_night_nudge": False,
            "entities": {"pc_power": "", "kitchen_motion": ""},
            "hydration_reminder": False,
            "hydration_interval_hours": 3,
        }
        advisor.reload_config(new_cfg)
        assert advisor.enabled is False
        assert advisor.pc_break_minutes == 60
        assert advisor.stress_check is False
        assert advisor.hydration_check is False
        assert advisor.hydration_interval_hours == 3

    def test_set_ollama(self, advisor):
        mock_ollama = MagicMock()
        advisor.set_ollama(mock_ollama)
        assert advisor._ollama is mock_ollama

    def test_set_notify_callback(self, advisor):
        cb = AsyncMock()
        advisor.set_notify_callback(cb)
        assert advisor._notify_callback is cb

    @pytest.mark.asyncio
    async def test_start_disabled_no_task(self, advisor):
        advisor.enabled = False
        await advisor.start()
        assert advisor._task is None

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, advisor):
        advisor._running = True
        advisor._task = asyncio.create_task(asyncio.sleep(100))
        await advisor.stop()
        assert advisor._running is False
        assert advisor._task.cancelled()


# =====================================================================
# Addressing (edge cases)
# =====================================================================


class TestAddressingEdgeCases:

    @pytest.fixture
    def advisor(self, ha_mock, activity_mock, mood_mock, redis_mock):
        cfg = {
            "wellness": {"enabled": True},
            "timezone": "Europe/Berlin",
            "persons": {"titles": {"max": "Sir", "lisa": "Ma'am"}},
            "household": {"primary_user": "Max"},
        }
        with patch("assistant.wellness_advisor.yaml_config", cfg), \
             patch("assistant.wellness_advisor.get_person_title", return_value="Sir"):
            w = WellnessAdvisor(ha_mock, activity_mock, mood_mock)
        w.redis = redis_mock
        return w

    @pytest.mark.asyncio
    async def test_single_person_home(self, advisor, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "person.max", "state": "home",
             "attributes": {"friendly_name": "Max"}},
        ])
        with patch("assistant.wellness_advisor.yaml_config", {
            "persons": {"titles": {"max": "Sir"}},
            "household": {"primary_user": "Max"},
        }):
            result = await advisor._get_addressing()
        assert result == "Sir"

    @pytest.mark.asyncio
    async def test_two_persons_home(self, advisor, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "person.max", "state": "home",
             "attributes": {"friendly_name": "Max"}},
            {"entity_id": "person.lisa", "state": "home",
             "attributes": {"friendly_name": "Lisa"}},
        ])
        with patch("assistant.wellness_advisor.yaml_config", {
            "persons": {"titles": {"max": "Sir", "lisa": "Ma'am"}},
            "household": {"primary_user": "Max"},
        }):
            result = await advisor._get_addressing()
        assert "Sir" in result
        assert "Ma'am" in result

    @pytest.mark.asyncio
    async def test_ha_failure_fallback(self, advisor, ha_mock):
        """When HA fails, fall back to primary user."""
        ha_mock.get_states = AsyncMock(side_effect=ConnectionError("down"))
        with patch("assistant.wellness_advisor.yaml_config", {
            "persons": {"titles": {"max": "Sir"}},
            "household": {"primary_user": "Max"},
        }):
            result = await advisor._get_addressing()
        # Should not crash, falls back to primary user name
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_no_persons_no_primary_fallback(self, advisor, ha_mock):
        """When no person entities and no primary_user, use default title."""
        ha_mock.get_states = AsyncMock(return_value=[])
        with patch("assistant.wellness_advisor.yaml_config", {
            "persons": {"titles": {}},
            "household": {},
        }), patch("assistant.wellness_advisor.get_person_title", return_value="Sir"):
            result = await advisor._get_addressing()
        assert result == "Sir"
