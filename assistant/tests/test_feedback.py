"""Tests for assistant.feedback module."""

import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timedelta

from assistant.feedback import (
    FeedbackTracker,
    FEEDBACK_DELTAS,
    DEFAULT_SCORE,
    SCORE_SUPPRESS,
    SCORE_REDUCE,
    SCORE_NORMAL,
    SCORE_BOOST,
)


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.setex = AsyncMock()
    r.hincrby = AsyncMock()
    r.hgetall = AsyncMock(return_value={})
    r.lpush = AsyncMock()
    r.ltrim = AsyncMock()
    r.expire = AsyncMock()
    r.lrange = AsyncMock(return_value=[])
    r.scan = AsyncMock(return_value=(0, []))
    return r


@pytest.fixture
def tracker():
    with patch("assistant.feedback.yaml_config", {"feedback": {"auto_timeout_seconds": 120, "base_cooldown_seconds": 300}}):
        t = FeedbackTracker()
    return t


# ------------------------------------------------------------------
# Initialization
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initialize(tracker, mock_redis):
    await tracker.initialize(mock_redis)
    assert tracker.redis is mock_redis
    assert tracker._running is True
    # cleanup
    await tracker.stop()


@pytest.mark.asyncio
async def test_stop(tracker, mock_redis):
    await tracker.initialize(mock_redis)
    await tracker.stop()
    assert tracker._running is False


# ------------------------------------------------------------------
# track_notification
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_track_notification(tracker, mock_redis):
    tracker.redis = mock_redis
    await tracker.track_notification("n1", "door_open")
    assert "n1" in tracker._pending
    assert tracker._pending["n1"]["event_type"] == "door_open"
    mock_redis.hincrby.assert_called_once()


# ------------------------------------------------------------------
# record_feedback
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_feedback_from_pending(tracker, mock_redis):
    tracker.redis = mock_redis
    mock_redis.get.return_value = str(DEFAULT_SCORE)
    tracker._pending["n1"] = {"event_type": "door_open", "sent_at": datetime.now()}
    result = await tracker.record_feedback("n1", "thanked")
    assert result is not None
    assert result["event_type"] == "door_open"
    assert result["delta"] == FEEDBACK_DELTAS["thanked"]
    assert "n1" not in tracker._pending


@pytest.mark.asyncio
async def test_record_feedback_fallback_event_type(tracker, mock_redis):
    tracker.redis = mock_redis
    mock_redis.get.return_value = str(DEFAULT_SCORE)
    result = await tracker.record_feedback("door_open", "dismissed")
    assert result is not None
    assert result["event_type"] == "door_open"


@pytest.mark.asyncio
async def test_record_feedback_unknown_type(tracker, mock_redis):
    tracker.redis = mock_redis
    result = await tracker.record_feedback("n1", "invalid_feedback")
    assert result is None


# ------------------------------------------------------------------
# get_score
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_score_default(tracker, mock_redis):
    tracker.redis = mock_redis
    mock_redis.get.return_value = None
    score = await tracker.get_score("test_event")
    assert score == DEFAULT_SCORE


@pytest.mark.asyncio
async def test_get_score_from_redis(tracker, mock_redis):
    tracker.redis = mock_redis
    mock_redis.get.return_value = "0.75"
    score = await tracker.get_score("test_event")
    assert score == 0.75


@pytest.mark.asyncio
async def test_get_score_no_redis(tracker):
    tracker.redis = None
    score = await tracker.get_score("test_event")
    assert score == DEFAULT_SCORE


# ------------------------------------------------------------------
# should_notify
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_should_notify_critical_always(tracker, mock_redis):
    tracker.redis = mock_redis
    result = await tracker.should_notify("any_event", "critical")
    assert result["allow"] is True
    assert result["cooldown"] == 0


@pytest.mark.asyncio
async def test_should_notify_high_low_score(tracker, mock_redis):
    tracker.redis = mock_redis
    mock_redis.get.return_value = str(SCORE_SUPPRESS - 0.01)
    result = await tracker.should_notify("event", "high")
    assert result["allow"] is False


@pytest.mark.asyncio
async def test_should_notify_high_ok_score(tracker, mock_redis):
    tracker.redis = mock_redis
    mock_redis.get.return_value = str(SCORE_NORMAL)
    result = await tracker.should_notify("event", "high")
    assert result["allow"] is True


@pytest.mark.asyncio
async def test_should_notify_medium_low_score(tracker, mock_redis):
    tracker.redis = mock_redis
    mock_redis.get.return_value = str(SCORE_REDUCE - 0.01)
    result = await tracker.should_notify("event", "medium")
    assert result["allow"] is False


@pytest.mark.asyncio
async def test_should_notify_medium_ok(tracker, mock_redis):
    tracker.redis = mock_redis
    mock_redis.get.return_value = str(SCORE_NORMAL)
    result = await tracker.should_notify("event", "medium")
    assert result["allow"] is True


@pytest.mark.asyncio
async def test_should_notify_low_insufficient(tracker, mock_redis):
    tracker.redis = mock_redis
    mock_redis.get.return_value = str(SCORE_NORMAL - 0.01)
    result = await tracker.should_notify("event", "low")
    assert result["allow"] is False


@pytest.mark.asyncio
async def test_should_notify_low_ok(tracker, mock_redis):
    tracker.redis = mock_redis
    mock_redis.get.return_value = str(SCORE_BOOST)
    result = await tracker.should_notify("event", "low")
    assert result["allow"] is True


# ------------------------------------------------------------------
# _calculate_cooldown
# ------------------------------------------------------------------


def test_cooldown_boost(tracker):
    cd = tracker._calculate_cooldown(SCORE_BOOST + 0.01)
    assert cd == int(300 * 0.6)


def test_cooldown_normal(tracker):
    cd = tracker._calculate_cooldown(SCORE_NORMAL)
    assert cd == 300


def test_cooldown_reduced(tracker):
    cd = tracker._calculate_cooldown(SCORE_REDUCE)
    assert cd == int(300 * 2.0)


def test_cooldown_very_low(tracker):
    cd = tracker._calculate_cooldown(SCORE_SUPPRESS)
    assert cd == int(300 * 5.0)


# ------------------------------------------------------------------
# get_stats / get_all_scores
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_stats_no_redis(tracker):
    tracker.redis = None
    result = await tracker.get_stats()
    assert result == {"error": "redis_unavailable"}


@pytest.mark.asyncio
async def test_get_stats_for_event(tracker, mock_redis):
    tracker.redis = mock_redis
    mock_redis.get.return_value = "0.6"
    mock_redis.hgetall.return_value = {"total_sent": 5, "thanked": 2}
    mock_redis.lrange.return_value = []
    result = await tracker.get_stats("door_open")
    assert "score" in result
    assert "cooldown_seconds" in result


@pytest.mark.asyncio
async def test_get_all_scores_empty(tracker, mock_redis):
    tracker.redis = mock_redis
    scores = await tracker.get_all_scores()
    assert scores == {}


# ------------------------------------------------------------------
# get_person_score
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_person_score(tracker, mock_redis):
    tracker.redis = mock_redis
    mock_redis.get.return_value = "0.8"
    score = await tracker.get_person_score("door_open", "Max")
    assert score == 0.8


@pytest.mark.asyncio
async def test_get_person_score_no_person(tracker, mock_redis):
    tracker.redis = mock_redis
    score = await tracker.get_person_score("door_open", "")
    assert score == DEFAULT_SCORE


# ------------------------------------------------------------------
# _check_timeouts
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_timeouts(tracker, mock_redis):
    tracker.redis = mock_redis
    mock_redis.get.return_value = str(DEFAULT_SCORE)
    tracker._pending["n1"] = {
        "event_type": "door_open",
        "sent_at": datetime.now() - timedelta(seconds=200),
    }
    await tracker._check_timeouts()
    assert "n1" not in tracker._pending
    # Score update + feedback entry + counter increment
    assert mock_redis.setex.call_count >= 1


@pytest.mark.asyncio
async def test_check_timeouts_not_expired(tracker, mock_redis):
    tracker.redis = mock_redis
    tracker._pending["n1"] = {
        "event_type": "door_open",
        "sent_at": datetime.now(),
    }
    await tracker._check_timeouts()
    assert "n1" in tracker._pending
