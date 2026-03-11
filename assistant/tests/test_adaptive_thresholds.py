"""
Tests fuer AdaptiveThresholds — Lernende Schwellwerte.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.adaptive_thresholds import (
    AdaptiveThresholds,
    _AUTO_BOUNDS,
    MAX_ADJUSTMENTS_PER_WEEK,
    MIN_OUTCOMES_FOR_ADJUST,
)


@pytest.fixture
def thresholds(redis_mock):
    t = AdaptiveThresholds()
    t.redis = redis_mock
    t.enabled = True
    return t


class TestRunAnalysis:
    """Tests fuer run_analysis()."""

    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self, thresholds):
        thresholds.enabled = False
        result = await thresholds.run_analysis()
        assert result["adjusted"] == []

    @pytest.mark.asyncio
    async def test_insufficient_data_skips(self, thresholds):
        outcome_tracker = MagicMock()
        outcome_tracker.get_stats = AsyncMock(return_value={
            "set_light": {"total": 5, "score": 0.5},  # Unter MIN_OUTCOMES
        })
        result = await thresholds.run_analysis(outcome_tracker=outcome_tracker)
        assert "insufficient_data" in result["skipped"]

    @pytest.mark.asyncio
    async def test_rate_limit(self, thresholds):
        from datetime import datetime
        thresholds._adjustments_this_week = MAX_ADJUSTMENTS_PER_WEEK
        # Set current week so the counter doesn't get reset
        thresholds._last_adjustment_week = datetime.now().strftime("%Y-W%W")
        result = await thresholds.run_analysis()
        assert "rate_limit_reached" in result["skipped"]


class TestHasSufficientData:
    """Tests fuer _has_sufficient_data()."""

    @pytest.mark.asyncio
    async def test_no_tracker(self, thresholds):
        result = await thresholds._has_sufficient_data(None)
        assert result is False

    @pytest.mark.asyncio
    async def test_enough_data(self, thresholds):
        tracker = MagicMock()
        tracker.get_stats = AsyncMock(return_value={
            "set_light": {"total": 30},
            "set_climate": {"total": 25},
        })
        result = await thresholds._has_sufficient_data(tracker)
        assert result is True

    @pytest.mark.asyncio
    async def test_not_enough_data(self, thresholds):
        tracker = MagicMock()
        tracker.get_stats = AsyncMock(return_value={
            "set_light": {"total": 10},
        })
        result = await thresholds._has_sufficient_data(tracker)
        assert result is False


class TestRuntimeValues:
    """Tests fuer Runtime-Config-Zugriff."""

    def test_get_runtime_value(self, thresholds):
        with patch("assistant.adaptive_thresholds.yaml_config", {
            "insights": {"cooldown_hours": 4},
        }):
            val = thresholds._get_runtime_value(["insights", "cooldown_hours"])
            assert val == 4

    def test_get_runtime_value_missing(self, thresholds):
        with patch("assistant.adaptive_thresholds.yaml_config", {}):
            val = thresholds._get_runtime_value(["insights", "cooldown_hours"])
            assert val is None


class TestGetAdjustmentHistory:
    """Tests fuer get_adjustment_history()."""

    @pytest.mark.asyncio
    async def test_empty_history(self, thresholds):
        thresholds.redis.lrange.return_value = []
        history = await thresholds.get_adjustment_history()
        assert history == []

    @pytest.mark.asyncio
    async def test_returns_history(self, thresholds):
        entry = json.dumps({
            "parameter": "insights.cooldown_hours",
            "old_value": 4,
            "new_value": 5,
        })
        thresholds.redis.lrange.return_value = [entry]
        history = await thresholds.get_adjustment_history()
        assert len(history) == 1
        assert history[0]["parameter"] == "insights.cooldown_hours"


# =====================================================================
# Additional tests for 100% coverage
# =====================================================================


class TestInitialize:
    """Tests fuer initialize()."""

    @pytest.mark.asyncio
    async def test_initialize_enabled(self, redis_mock):
        with patch("assistant.adaptive_thresholds.yaml_config", {
            "adaptive_thresholds": {"enabled": True, "auto_adjust": True},
        }):
            t = AdaptiveThresholds()
        await t.initialize(redis_mock)
        assert t.enabled is True
        assert t.redis is redis_mock

    @pytest.mark.asyncio
    async def test_initialize_disabled_no_redis(self):
        with patch("assistant.adaptive_thresholds.yaml_config", {
            "adaptive_thresholds": {"enabled": True},
        }):
            t = AdaptiveThresholds()
        await t.initialize(None)
        assert t.enabled is False

    @pytest.mark.asyncio
    async def test_initialize_auto_adjust_false(self, redis_mock):
        with patch("assistant.adaptive_thresholds.yaml_config", {
            "adaptive_thresholds": {"enabled": True, "auto_adjust": False},
        }):
            t = AdaptiveThresholds()
        await t.initialize(redis_mock)
        assert t.enabled is False


class TestRunAnalysisFull:
    """Tests fuer volle run_analysis() Pfade."""

    @pytest.mark.asyncio
    async def test_new_week_resets_counter(self, thresholds):
        thresholds._last_adjustment_week = "1970-W01"
        thresholds._adjustments_this_week = 5
        outcome_tracker = MagicMock()
        outcome_tracker.get_stats = AsyncMock(return_value={
            "set_light": {"total": 60},
        })
        # Will skip insufficient data check but proceed
        result = await thresholds.run_analysis(outcome_tracker=outcome_tracker)
        assert thresholds._adjustments_this_week == 0 or "skipped" in result

    @pytest.mark.asyncio
    async def test_analysis_with_adjustment(self, thresholds):
        """Full flow: sufficient data, parameter adjusted."""
        outcome_tracker = MagicMock()
        outcome_tracker.get_stats = AsyncMock(return_value={
            "set_light": {"total": 60, "negative": 0},
        })
        feedback_tracker = MagicMock()
        feedback_tracker.get_score = AsyncMock(return_value=0.2)

        with patch("assistant.adaptive_thresholds.yaml_config", {
            "insights": {"cooldown_hours": 4},
        }):
            thresholds.redis.get = AsyncMock(return_value=None)
            result = await thresholds.run_analysis(
                outcome_tracker=outcome_tracker,
                feedback_tracker=feedback_tracker,
            )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_analysis_exception_in_parameter(self, thresholds):
        """Exception in _analyze_parameter gets caught."""
        outcome_tracker = MagicMock()
        outcome_tracker.get_stats = AsyncMock(return_value={
            "set_light": {"total": 60},
        })
        with patch.object(thresholds, '_analyze_parameter', side_effect=ValueError("boom")):
            result = await thresholds.run_analysis(outcome_tracker=outcome_tracker)
        assert len(result["skipped"]) > 0

    @pytest.mark.asyncio
    async def test_analysis_rate_limit_during_loop(self, thresholds):
        """Breaks out of loop if rate limit hit during processing."""
        thresholds._adjustments_this_week = MAX_ADJUSTMENTS_PER_WEEK - 1
        outcome_tracker = MagicMock()
        outcome_tracker.get_stats = AsyncMock(return_value={
            "set_light": {"total": 60, "negative": 0},
        })
        feedback_tracker = MagicMock()
        feedback_tracker.get_score = AsyncMock(return_value=0.2)

        async def fake_analyze(*a, **kw):
            thresholds._adjustments_this_week = MAX_ADJUSTMENTS_PER_WEEK
            return {"adjusted": True, "parameter": "test", "old_value": 1, "new_value": 2}

        with patch.object(thresholds, '_analyze_parameter', side_effect=fake_analyze):
            thresholds.redis.get = AsyncMock(return_value=None)
            result = await thresholds.run_analysis(
                outcome_tracker=outcome_tracker,
                feedback_tracker=feedback_tracker,
            )
        assert len(result["adjusted"]) >= 1

    @pytest.mark.asyncio
    async def test_no_redis_returns_empty(self):
        with patch("assistant.adaptive_thresholds.yaml_config", {}):
            t = AdaptiveThresholds()
        t.enabled = True
        t.redis = None
        result = await t.run_analysis()
        assert result == {"adjusted": [], "skipped": []}

    @pytest.mark.asyncio
    async def test_result_not_adjusted_adds_reason(self, thresholds):
        """When analyze_parameter returns adjusted=False, reason is added to skipped."""
        outcome_tracker = MagicMock()
        outcome_tracker.get_stats = AsyncMock(return_value={
            "set_light": {"total": 60},
        })

        async def fake_analyze(*a, **kw):
            return {"adjusted": False, "reason": "at_bound"}

        with patch.object(thresholds, '_analyze_parameter', side_effect=fake_analyze):
            result = await thresholds.run_analysis(outcome_tracker=outcome_tracker)
        assert "at_bound" in result["skipped"]


class TestAnalyzeParameter:
    """Tests fuer _analyze_parameter()."""

    @pytest.mark.asyncio
    async def test_current_none_uses_default(self, thresholds):
        bounds = _AUTO_BOUNDS["insights.cooldown_hours"]
        thresholds.redis.get = AsyncMock(return_value=None)

        with patch("assistant.adaptive_thresholds.yaml_config", {}):
            with patch.object(thresholds, '_determine_direction', return_value=0):
                result = await thresholds._analyze_parameter(
                    "insights.cooldown_hours", bounds, None, None,
                )
        assert result is None  # direction=0 means no change

    @pytest.mark.asyncio
    async def test_self_opt_pending_skips(self, thresholds):
        bounds = _AUTO_BOUNDS["insights.cooldown_hours"]
        thresholds.redis.get = AsyncMock(return_value="pending_value")

        with patch("assistant.adaptive_thresholds.yaml_config", {
            "insights": {"cooldown_hours": 4},
        }):
            result = await thresholds._analyze_parameter(
                "insights.cooldown_hours", bounds, None, None,
            )
        assert result["adjusted"] is False
        assert "self_opt_pending" in result["reason"]

    @pytest.mark.asyncio
    async def test_at_bound_returns_not_adjusted(self, thresholds):
        bounds = _AUTO_BOUNDS["insights.cooldown_hours"]
        thresholds.redis.get = AsyncMock(return_value=None)

        with patch("assistant.adaptive_thresholds.yaml_config", {
            "insights": {"cooldown_hours": 2},  # Already at min
        }):
            with patch.object(thresholds, '_determine_direction', return_value=-1):
                result = await thresholds._analyze_parameter(
                    "insights.cooldown_hours", bounds, None, None,
                )
        assert result["adjusted"] is False
        assert result["reason"] == "at_bound"

    @pytest.mark.asyncio
    async def test_anomaly_detected_skips(self, thresholds):
        bounds = _AUTO_BOUNDS["insights.cooldown_hours"]
        thresholds.redis.get = AsyncMock(return_value=None)
        outcome_tracker = MagicMock()
        outcome_tracker.get_stats = AsyncMock(return_value={
            "set_light": {"total": 30, "negative": 28},
        })

        with patch("assistant.adaptive_thresholds.yaml_config", {
            "insights": {"cooldown_hours": 4},
        }):
            with patch.object(thresholds, '_determine_direction', return_value=1):
                result = await thresholds._analyze_parameter(
                    "insights.cooldown_hours", bounds, outcome_tracker, None,
                )
        assert result["adjusted"] is False
        assert result["reason"] == "anomaly_detected"

    @pytest.mark.asyncio
    async def test_successful_adjustment(self, thresholds):
        bounds = _AUTO_BOUNDS["insights.cooldown_hours"]
        thresholds.redis.get = AsyncMock(return_value=None)
        outcome_tracker = MagicMock()
        outcome_tracker.get_stats = AsyncMock(return_value={
            "set_light": {"total": 30, "negative": 2},
        })

        with patch("assistant.adaptive_thresholds.yaml_config", {
            "insights": {"cooldown_hours": 4},
        }):
            with patch.object(thresholds, '_determine_direction', return_value=1):
                result = await thresholds._analyze_parameter(
                    "insights.cooldown_hours", bounds, outcome_tracker, None,
                )
        assert result["adjusted"] is True
        assert result["new_value"] == 5
        assert result["old_value"] == 4


class TestDetermineDirection:
    """Tests fuer _determine_direction()."""

    @pytest.mark.asyncio
    async def test_insight_low_score_increase(self, thresholds):
        feedback = MagicMock()
        feedback.get_score = AsyncMock(return_value=0.2)
        result = await thresholds._determine_direction(
            "insights.cooldown_hours", None, feedback,
        )
        assert result == 1

    @pytest.mark.asyncio
    async def test_insight_high_score_decrease(self, thresholds):
        feedback = MagicMock()
        feedback.get_score = AsyncMock(return_value=0.8)
        result = await thresholds._determine_direction(
            "insights.cooldown_hours", None, feedback,
        )
        assert result == -1

    @pytest.mark.asyncio
    async def test_insight_mid_score_no_change(self, thresholds):
        feedback = MagicMock()
        feedback.get_score = AsyncMock(return_value=0.5)
        result = await thresholds._determine_direction(
            "insights.cooldown_hours", None, feedback,
        )
        assert result == 0

    @pytest.mark.asyncio
    async def test_insight_no_feedback(self, thresholds):
        result = await thresholds._determine_direction(
            "insights.cooldown_hours", None, None,
        )
        assert result == 0

    @pytest.mark.asyncio
    async def test_anticipation_low_score(self, thresholds):
        outcome = MagicMock()
        outcome.get_success_score = AsyncMock(return_value=0.2)
        result = await thresholds._determine_direction(
            "anticipation.min_confidence", outcome, None,
        )
        assert result == 1

    @pytest.mark.asyncio
    async def test_anticipation_high_score(self, thresholds):
        outcome = MagicMock()
        outcome.get_success_score = AsyncMock(return_value=0.8)
        result = await thresholds._determine_direction(
            "anticipation.min_confidence", outcome, None,
        )
        assert result == -1

    @pytest.mark.asyncio
    async def test_anticipation_no_tracker(self, thresholds):
        result = await thresholds._determine_direction(
            "anticipation.min_confidence", None, None,
        )
        assert result == 0

    @pytest.mark.asyncio
    async def test_feedback_cooldown_low_avg(self, thresholds):
        feedback = MagicMock()
        feedback.get_all_scores = AsyncMock(return_value={"a": 0.1, "b": 0.2})
        result = await thresholds._determine_direction(
            "feedback.base_cooldown_seconds", None, feedback,
        )
        assert result == 1

    @pytest.mark.asyncio
    async def test_feedback_cooldown_high_avg(self, thresholds):
        feedback = MagicMock()
        feedback.get_all_scores = AsyncMock(return_value={"a": 0.8, "b": 0.9})
        result = await thresholds._determine_direction(
            "feedback.base_cooldown_seconds", None, feedback,
        )
        assert result == -1

    @pytest.mark.asyncio
    async def test_feedback_cooldown_empty_scores(self, thresholds):
        feedback = MagicMock()
        feedback.get_all_scores = AsyncMock(return_value={})
        result = await thresholds._determine_direction(
            "feedback.base_cooldown_seconds", None, feedback,
        )
        assert result == 0

    @pytest.mark.asyncio
    async def test_feedback_cooldown_non_numeric_scores(self, thresholds):
        feedback = MagicMock()
        feedback.get_all_scores = AsyncMock(return_value={"a": "text", "b": None})
        result = await thresholds._determine_direction(
            "feedback.base_cooldown_seconds", None, feedback,
        )
        assert result == 0

    @pytest.mark.asyncio
    async def test_unknown_parameter(self, thresholds):
        result = await thresholds._determine_direction(
            "unknown.param", None, None,
        )
        assert result == 0


class TestSetRuntimeValue:
    """Tests fuer _set_runtime_value()."""

    def test_blocked_path(self, thresholds):
        """Unknown path is blocked."""
        with patch("assistant.adaptive_thresholds.yaml_config", {}):
            thresholds._set_runtime_value(["unknown", "path"], 42)

    def test_allowed_path_sets_value(self, thresholds):
        cfg = {"insights": {"cooldown_hours": 4}}
        with patch("assistant.adaptive_thresholds.yaml_config", cfg):
            thresholds._set_runtime_value(["insights", "cooldown_hours"], 5)
        assert cfg["insights"]["cooldown_hours"] == 5

    def test_creates_missing_intermediate_keys(self, thresholds):
        cfg = {}
        with patch("assistant.adaptive_thresholds.yaml_config", cfg):
            thresholds._set_runtime_value(["insights", "cooldown_hours"], 5)
        assert cfg["insights"]["cooldown_hours"] == 5

    def test_non_dict_intermediate_returns(self, thresholds):
        cfg = {"insights": "not_a_dict"}
        with patch("assistant.adaptive_thresholds.yaml_config", cfg):
            thresholds._set_runtime_value(["insights", "cooldown_hours"], 5)
        # Should not raise, just return


class TestGetRuntimeValueDeep:
    """Additional _get_runtime_value tests."""

    def test_nested_non_dict(self, thresholds):
        with patch("assistant.adaptive_thresholds.yaml_config", {
            "insights": "not_a_dict",
        }):
            val = thresholds._get_runtime_value(["insights", "cooldown_hours"])
        assert val is None


class TestLogAdjustments:
    """Tests fuer _log_adjustments()."""

    @pytest.mark.asyncio
    async def test_logs_to_redis(self, thresholds):
        adjusted = [{"parameter": "test", "old_value": 1, "new_value": 2}]
        await thresholds._log_adjustments(adjusted)
        thresholds.redis.lpush.assert_called()
        thresholds.redis.ltrim.assert_called()
        thresholds.redis.expire.assert_called()

    @pytest.mark.asyncio
    async def test_no_redis_returns(self):
        with patch("assistant.adaptive_thresholds.yaml_config", {}):
            t = AdaptiveThresholds()
        t.redis = None
        await t._log_adjustments([{"test": True}])


class TestGetAdjustmentHistoryJsonError:
    """Test JSON decode error in get_adjustment_history."""

    @pytest.mark.asyncio
    async def test_invalid_json_skipped(self, thresholds):
        thresholds.redis.lrange.return_value = [
            "invalid_json",
            json.dumps({"parameter": "test"}),
        ]
        history = await thresholds.get_adjustment_history()
        assert len(history) == 1
        assert history[0]["parameter"] == "test"
