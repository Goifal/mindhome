"""
Tests fuer OutcomeTracker — Wirkungstracker fuer Jarvis-Aktionen.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.outcome_tracker import (
    OutcomeTracker,
    OUTCOME_POSITIVE,
    OUTCOME_NEUTRAL,
    OUTCOME_PARTIAL,
    OUTCOME_NEGATIVE,
    DEFAULT_SCORE,
    MIN_OUTCOMES_FOR_SCORE,
    _extract_state_key,
)


@pytest.fixture
def tracker(redis_mock, ha_mock):
    t = OutcomeTracker()
    t.redis = redis_mock
    t.ha = ha_mock
    t.enabled = True
    t._task_registry = MagicMock()
    t._task_registry.create_task = MagicMock()
    t._observation_delay = 0  # Kein Delay fuer Tests
    return t


class TestTrackAction:
    """Tests fuer track_action()."""

    @pytest.mark.asyncio
    async def test_disabled_tracker_returns(self, tracker):
        tracker.enabled = False
        await tracker.track_action("set_light", {"room": "wohnzimmer"}, {"success": True})
        tracker.redis.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_entity_no_tracking(self, tracker):
        tracker.ha.get_state = AsyncMock(return_value=None)
        await tracker.track_action("get_weather", {}, {"success": True})
        tracker.redis.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_tracks_action_with_entity(self, tracker):
        tracker.ha.get_state = AsyncMock(return_value={
            "state": "on",
            "attributes": {"brightness": 100},
        })
        await tracker.track_action(
            "set_light", {"room": "wohnzimmer"}, {"success": True},
            person="Max", room="wohnzimmer",
        )
        tracker.redis.setex.assert_called()

    @pytest.mark.asyncio
    async def test_max_pending_limit(self, tracker):
        tracker._pending_count = 20
        tracker.ha.get_state = AsyncMock(return_value={"state": "on", "attributes": {}})
        await tracker.track_action("set_light", {"room": "wz"}, {"success": True})
        # Sollte nicht tracken da max_pending erreicht
        tracker.redis.setex.assert_not_called()


class TestRecordVerbalFeedback:
    """Tests fuer record_verbal_feedback()."""

    @pytest.mark.asyncio
    async def test_positive_feedback(self, tracker):
        tracker.redis.get.return_value = "set_light"
        await tracker.record_verbal_feedback("positive")
        tracker.redis.lpush.assert_called()

    @pytest.mark.asyncio
    async def test_negative_feedback(self, tracker):
        tracker.redis.get.return_value = "set_climate"
        await tracker.record_verbal_feedback("negative", action_type="set_climate")
        tracker.redis.lpush.assert_called()

    @pytest.mark.asyncio
    async def test_unknown_feedback_ignored(self, tracker):
        await tracker.record_verbal_feedback("unknown_type")
        tracker.redis.lpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_disabled_feedback_ignored(self, tracker):
        tracker.enabled = False
        await tracker.record_verbal_feedback("positive")
        tracker.redis.lpush.assert_not_called()


class TestClassifyOutcome:
    """Tests fuer _classify_outcome()."""

    def test_same_state_is_neutral(self, tracker):
        after = {"state": "on", "attributes": {"brightness": 100}}
        now = {"state": "on", "attributes": {"brightness": 100}}
        assert tracker._classify_outcome(after, now, "set_light") == OUTCOME_NEUTRAL

    def test_different_state_is_negative(self, tracker):
        after = {"state": "on", "attributes": {}}
        now = {"state": "off", "attributes": {}}
        assert tracker._classify_outcome(after, now, "set_light") == OUTCOME_NEGATIVE

    def test_changed_attributes_is_partial(self, tracker):
        # 1 of 3 non-meta attrs changed = 33% < 50% = PARTIAL
        after = {"state": "on", "attributes": {"brightness": 100, "color_temp": 300, "rgb_color": [255, 255, 255]}}
        now = {"state": "on", "attributes": {"brightness": 50, "color_temp": 300, "rgb_color": [255, 255, 255]}}
        assert tracker._classify_outcome(after, now, "set_light") == OUTCOME_PARTIAL

    def test_empty_states_neutral(self, tracker):
        assert tracker._classify_outcome({}, {}, "set_light") == OUTCOME_NEUTRAL
        assert tracker._classify_outcome(None, None, "set_light") == OUTCOME_NEUTRAL


class TestGetScores:
    """Tests fuer Score-Abfragen."""

    @pytest.mark.asyncio
    async def test_default_score_when_no_data(self, tracker):
        tracker.redis.get.return_value = None
        tracker.redis.hget.return_value = None
        score = await tracker.get_success_score("set_light")
        assert score == DEFAULT_SCORE

    @pytest.mark.asyncio
    async def test_returns_stored_score(self, tracker):
        tracker.redis.get.return_value = "0.85"
        score = await tracker.get_success_score("set_light")
        assert score == 0.85

    @pytest.mark.asyncio
    async def test_person_score_default(self, tracker):
        tracker.redis.get.return_value = None
        score = await tracker.get_person_score("set_light", "Max")
        assert score == DEFAULT_SCORE

    @pytest.mark.asyncio
    async def test_person_score_stored(self, tracker):
        tracker.redis.get.return_value = "0.72"
        score = await tracker.get_person_score("set_light", "Max")
        assert score == 0.72


class TestExtractStateKey:
    """Tests fuer _extract_state_key()."""

    def test_dict_state(self):
        state = {"state": "on", "attributes": {"brightness": 100, "friendly_name": "Licht"}}
        result = _extract_state_key(state)
        assert result["state"] == "on"
        assert "brightness" in result["attributes"]
        assert "friendly_name" not in result["attributes"]

    def test_none_state(self):
        assert _extract_state_key(None) == {}

    def test_empty_dict(self):
        # Empty dict is falsy in Python, so _extract_state_key returns {}
        result = _extract_state_key({})
        assert result == {}


class TestGetStats:
    """Tests fuer get_stats()."""

    @pytest.mark.asyncio
    async def test_empty_stats(self, tracker):
        tracker.redis.scan.return_value = (0, [])
        stats = await tracker.get_stats()
        assert stats == {}
