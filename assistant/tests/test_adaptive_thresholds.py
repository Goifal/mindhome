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
