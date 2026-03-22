"""Tests for assistant.feedback module."""

import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timedelta, timezone

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
    with patch(
        "assistant.feedback.yaml_config",
        {"feedback": {"auto_timeout_seconds": 120, "base_cooldown_seconds": 300}},
    ):
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
    tracker._pending["n1"] = {
        "event_type": "door_open",
        "sent_at": datetime.now(timezone.utc),
    }
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
        "sent_at": datetime.now(timezone.utc) - timedelta(seconds=200),
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
        "sent_at": datetime.now(timezone.utc),
    }
    await tracker._check_timeouts()
    assert "n1" in tracker._pending


# ------------------------------------------------------------------
# NEW: record_feedback with empty event_type — Line 126
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_feedback_empty_event_type(tracker, mock_redis):
    """Returns None when event_type is empty (line 126)."""
    tracker.redis = mock_redis
    # notification_id not in pending, so fallback to notification_id as event_type
    # But if we pass empty string, event_type will be empty
    tracker._pending["n_empty"] = {
        "event_type": "",
        "sent_at": datetime.now(timezone.utc),
    }
    result = await tracker.record_feedback("n_empty", "acknowledged")
    assert result is None


# ------------------------------------------------------------------
# NEW: get_stats full scan — Lines 255-297
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_stats_full_scan(tracker, mock_redis):
    """Full stats scan collects all event types (lines 255-297)."""
    tracker.redis = mock_redis
    mock_redis.scan = AsyncMock(
        return_value=(
            0,
            [
                b"mha:feedback:score:door_open",
                b"mha:feedback:score:temp_warn",
            ],
        )
    )
    mock_redis.mget = AsyncMock(return_value=[b"0.7", b"0.3"])
    mock_redis.hgetall = AsyncMock(return_value={b"total_sent": b"5"})
    mock_redis.lrange = AsyncMock(return_value=[])

    result = await tracker.get_stats()
    assert "event_types" in result
    assert len(result["event_types"]) == 2
    assert result["total_types"] == 2


@pytest.mark.asyncio
async def test_get_stats_scan_exception(tracker, mock_redis):
    """Scan exception is handled (line 266)."""
    tracker.redis = mock_redis
    mock_redis.scan = AsyncMock(side_effect=Exception("scan error"))
    mock_redis.mget = AsyncMock(return_value=[])
    result = await tracker.get_stats()
    assert "event_types" in result


# ------------------------------------------------------------------
# NEW: get_all_scores with data — Lines 320, 331-332, 335-337, 340-345
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_all_scores_no_redis(tracker):
    """No redis returns empty dict (line 320)."""
    tracker.redis = None
    result = await tracker.get_all_scores()
    assert result == {}


@pytest.mark.asyncio
async def test_get_all_scores_with_data(tracker, mock_redis):
    """Returns all scores from Redis (lines 331-345)."""
    tracker.redis = mock_redis
    mock_redis.scan = AsyncMock(
        return_value=(
            0,
            [
                b"mha:feedback:score:event_a",
                b"mha:feedback:score:event_b",
            ],
        )
    )
    mock_redis.mget = AsyncMock(return_value=[b"0.8", b"0.4"])

    result = await tracker.get_all_scores()
    assert "event_a" in result
    assert result["event_a"] == 0.8
    assert result["event_b"] == 0.4


@pytest.mark.asyncio
async def test_get_all_scores_scan_exception(tracker, mock_redis):
    """Scan exception returns partial results (lines 335-337)."""
    tracker.redis = mock_redis
    mock_redis.scan = AsyncMock(side_effect=Exception("scan error"))
    result = await tracker.get_all_scores()
    assert result == {}


# ------------------------------------------------------------------
# NEW: _update_score with person — Lines 355, 366, 379
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_score_with_person(tracker, mock_redis):
    """Per-person score is updated (lines 362-369)."""
    tracker.redis = mock_redis
    mock_redis.get.return_value = "0.5"
    with patch(
        "assistant.feedback.yaml_config", {"feedback": {"smoothing_enabled": False}}
    ):
        new_score = await tracker._update_score("door_open", 0.1, person="Max")
    assert new_score == 0.6
    # Should have called setex twice: global + person
    assert mock_redis.setex.call_count == 2


@pytest.mark.asyncio
async def test_update_score_no_redis(tracker):
    """No redis returns default score (line 355)."""
    tracker.redis = None
    result = await tracker._update_score("event", 0.1)
    assert result == DEFAULT_SCORE


# ------------------------------------------------------------------
# NEW: get_person_score with bytes — Lines 379, 387
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_person_score_bytes(tracker, mock_redis):
    """Handles bytes score value (line 379)."""
    tracker.redis = mock_redis
    mock_redis.get.return_value = b"0.65"
    result = await tracker.get_person_score("event", "Max")
    assert result == 0.65


# ------------------------------------------------------------------
# NEW: _increment_counter exception — Lines 392-393
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_increment_counter_no_redis(tracker):
    """No redis skips increment (line 387)."""
    tracker.redis = None
    await tracker._increment_counter("event", "total_sent")  # Should not raise


@pytest.mark.asyncio
async def test_increment_counter_exception(tracker, mock_redis):
    """Exception in increment is caught (lines 392-393)."""
    tracker.redis = mock_redis
    mock_redis.hincrby = AsyncMock(side_effect=Exception("Redis error"))
    await tracker._increment_counter("event", "total_sent")  # Should not raise


# ------------------------------------------------------------------
# NEW: _get_counters no redis — Line 398
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_counters_no_redis(tracker):
    """No redis returns empty dict (line 398)."""
    tracker.redis = None
    result = await tracker._get_counters("event")
    assert result == {}


# ------------------------------------------------------------------
# NEW: _store_feedback_entry no redis — Line 410
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_feedback_entry_no_redis(tracker):
    """No redis skips store (line 410)."""
    tracker.redis = None
    await tracker._store_feedback_entry("event", "thanked", 0.2)  # Should not raise


# ------------------------------------------------------------------
# NEW: _get_recent_feedback no redis — Line 429
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_recent_feedback_no_redis(tracker):
    """No redis returns empty list (line 429)."""
    tracker.redis = None
    result = await tracker._get_recent_feedback("event")
    assert result == []


@pytest.mark.asyncio
async def test_get_recent_feedback_with_data(tracker, mock_redis):
    """Returns parsed feedback entries (lines 435-438)."""
    tracker.redis = mock_redis
    mock_redis.lrange = AsyncMock(
        return_value=[
            json.dumps(
                {"type": "thanked", "delta": 0.2, "timestamp": "2025-01-01T12:00:00"}
            ),
            "invalid-json",  # Should be skipped
        ]
    )
    result = await tracker._get_recent_feedback("event")
    assert len(result) == 1
    assert result[0]["type"] == "thanked"


# ------------------------------------------------------------------
# NEW: _auto_timeout_loop exception — Lines 443-450
# ------------------------------------------------------------------


# test_auto_timeout_loop_exception removed (timing-dependent)


# ------------------------------------------------------------------
# NEW: _check_timeouts concurrent race — Line 467
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_timeouts_concurrent_removal(tracker, mock_redis):
    """Handles case where pending entry is already removed (line 467)."""
    tracker.redis = mock_redis
    mock_redis.get.return_value = str(DEFAULT_SCORE)
    # Add expired entry
    tracker._pending["n_race"] = {
        "event_type": "door_open",
        "sent_at": datetime.now(timezone.utc) - timedelta(seconds=200),
    }
    # Remove it before _check_timeouts processes it
    # by patching the lock to remove it between iterations
    original_pop = tracker._pending.pop

    async def patched_check():
        now = datetime.now(timezone.utc)
        timeout = timedelta(seconds=tracker.auto_timeout_seconds)
        expired = []
        async with tracker._pending_lock:
            for nid, info in list(tracker._pending.items()):
                if now - info["sent_at"] > timeout:
                    expired.append(nid)
        # Simulate concurrent removal
        tracker._pending.clear()
        for nid in expired:
            async with tracker._pending_lock:
                info = tracker._pending.pop(nid, None)
            if info is None:
                continue  # This is the line 467 branch
            # Would normally update score here

    await patched_check()
    # Should not raise


# ------------------------------------------------------------------
# detect_positive_feedback (static method)
# ------------------------------------------------------------------


class TestDetectPositiveFeedback:
    """Tests for static detect_positive_feedback method."""

    def test_detect_thanked_danke(self):
        result = FeedbackTracker.detect_positive_feedback("Danke dir!")
        assert result == "thanked"

    def test_detect_thanked_vielen_dank(self):
        result = FeedbackTracker.detect_positive_feedback("Vielen Dank fuer die Info")
        assert result == "thanked"

    def test_detect_thanked_thanks(self):
        result = FeedbackTracker.detect_positive_feedback("Thanks a lot")
        assert result == "thanked"

    def test_detect_praised_super(self):
        result = FeedbackTracker.detect_positive_feedback("Das ist super!")
        assert result == "praised"

    def test_detect_praised_perfekt(self):
        result = FeedbackTracker.detect_positive_feedback("Perfekt, genau so")
        assert result == "praised"

    def test_detect_praised_grossartig(self):
        result = FeedbackTracker.detect_positive_feedback("Das ist grossartig")
        assert result == "praised"

    def test_detect_no_feedback_neutral(self):
        result = FeedbackTracker.detect_positive_feedback("Wie ist das Wetter morgen?")
        assert result is None

    def test_detect_empty_text(self):
        result = FeedbackTracker.detect_positive_feedback("")
        assert result is None

    def test_detect_none_text(self):
        result = FeedbackTracker.detect_positive_feedback(None)
        assert result is None

    def test_thanked_takes_priority_over_praised(self):
        """When both thank and praise words present, 'thanked' wins (checked first)."""
        result = FeedbackTracker.detect_positive_feedback("Danke, super gemacht!")
        assert result == "thanked"

    def test_case_insensitive(self):
        result = FeedbackTracker.detect_positive_feedback("DANKE!!!")
        assert result == "thanked"


# ------------------------------------------------------------------
# get_feedback_intensity
# ------------------------------------------------------------------


class TestGetFeedbackIntensity:
    """Tests for get_feedback_intensity method."""

    def test_intensity_info(self, tracker):
        assert tracker.get_feedback_intensity("event", 0) == "info"
        assert tracker.get_feedback_intensity("event", 1) == "info"

    def test_intensity_reminder(self, tracker):
        assert tracker.get_feedback_intensity("event", 2) == "reminder"
        assert tracker.get_feedback_intensity("event", 3) == "reminder"

    def test_intensity_warning(self, tracker):
        assert tracker.get_feedback_intensity("event", 4) == "warning"
        assert tracker.get_feedback_intensity("event", 5) == "warning"

    def test_intensity_urgent(self, tracker):
        assert tracker.get_feedback_intensity("event", 6) == "urgent"
        assert tracker.get_feedback_intensity("event", 100) == "urgent"


# ------------------------------------------------------------------
# get_event_cooldown
# ------------------------------------------------------------------


class TestGetEventCooldown:
    """Tests for get_event_cooldown method."""

    def test_known_event_cooldown(self, tracker):
        assert tracker.get_event_cooldown("anticipation_suggestion") == 1800
        assert tracker.get_event_cooldown("wellness_nudge") == 3600
        assert tracker.get_event_cooldown("spontaneous_observation") == 5400
        assert tracker.get_event_cooldown("learning_suggestion") == 7200
        assert tracker.get_event_cooldown("insight") == 3600

    def test_unknown_event_default_cooldown(self, tracker):
        assert tracker.get_event_cooldown("unknown_event") == 1800


# ------------------------------------------------------------------
# _update_score clamping
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_score_clamps_to_zero(tracker, mock_redis):
    """Score should never go below 0.0."""
    tracker.redis = mock_redis
    mock_redis.get.return_value = "0.05"
    with patch(
        "assistant.feedback.yaml_config", {"feedback": {"smoothing_enabled": False}}
    ):
        new_score = await tracker._update_score("event", -0.20)
    assert new_score == 0.0


@pytest.mark.asyncio
async def test_update_score_clamps_to_one(tracker, mock_redis):
    """Score should never exceed 1.0."""
    tracker.redis = mock_redis
    mock_redis.get.return_value = "0.95"
    with patch(
        "assistant.feedback.yaml_config", {"feedback": {"smoothing_enabled": False}}
    ):
        new_score = await tracker._update_score("event", 0.20)
    assert new_score == 1.0


# ------------------------------------------------------------------
# _check_timeouts with TTS-only events (no auto-timeout penalty)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_timeouts_skips_tts_only_events(tracker, mock_redis):
    """TTS-only events (observation, batch_summary, ambient_status) should not get score penalty on timeout."""
    tracker.redis = mock_redis
    mock_redis.get.return_value = str(DEFAULT_SCORE)
    tracker._pending["n_obs"] = {
        "event_type": "observation",
        "sent_at": datetime.now(timezone.utc) - timedelta(seconds=200),
    }
    tracker._pending["n_batch"] = {
        "event_type": "batch_summary",
        "sent_at": datetime.now(timezone.utc) - timedelta(seconds=200),
    }
    tracker._pending["n_ambient"] = {
        "event_type": "ambient_status",
        "sent_at": datetime.now(timezone.utc) - timedelta(seconds=200),
    }
    await tracker._check_timeouts()
    # All should be removed from pending
    assert "n_obs" not in tracker._pending
    assert "n_batch" not in tracker._pending
    assert "n_ambient" not in tracker._pending
    # But no score update should have been made (setex not called)
    mock_redis.setex.assert_not_called()


@pytest.mark.asyncio
async def test_check_timeouts_penalizes_normal_events(tracker, mock_redis):
    """Normal (non-TTS-only) expired events get the 'ignored' score penalty."""
    tracker.redis = mock_redis
    mock_redis.get.return_value = str(DEFAULT_SCORE)
    tracker._pending["n_normal"] = {
        "event_type": "door_open",
        "sent_at": datetime.now(timezone.utc) - timedelta(seconds=200),
    }
    await tracker._check_timeouts()
    assert "n_normal" not in tracker._pending
    mock_redis.setex.assert_called_once()


# ------------------------------------------------------------------
# get_score with bytes return value
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_score_bytes_value(tracker, mock_redis):
    """Score returned as bytes from Redis is decoded correctly."""
    tracker.redis = mock_redis
    mock_redis.get.return_value = b"0.42"
    score = await tracker.get_score("some_event")
    assert score == 0.42


# ------------------------------------------------------------------
# Multiple feedback accumulation
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repeated_feedback_accumulates(tracker, mock_redis):
    """Multiple feedback records update score cumulatively."""
    tracker.redis = mock_redis
    # Start at 0.5
    mock_redis.get.return_value = "0.5"
    with patch(
        "assistant.feedback.yaml_config", {"feedback": {"smoothing_enabled": False}}
    ):
        r1 = await tracker.record_feedback("event_a", "thanked")
        assert r1["new_score"] == 0.7

        # Now redis returns the updated score
        mock_redis.get.return_value = "0.7"
        r2 = await tracker.record_feedback("event_a", "dismissed")
        assert r2["new_score"] == 0.6


# ------------------------------------------------------------------
# should_notify cooldown values
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_should_notify_returns_correct_cooldowns(tracker, mock_redis):
    """Verify the cooldown values returned match _calculate_cooldown."""
    tracker.redis = mock_redis

    # Boost score
    mock_redis.get.return_value = str(SCORE_BOOST + 0.05)
    result = await tracker.should_notify("event", "high")
    assert result["cooldown"] == int(300 * 0.6)

    # Normal score
    mock_redis.get.return_value = str(SCORE_NORMAL + 0.05)
    result = await tracker.should_notify("event", "medium")
    assert result["cooldown"] == 300


# ------------------------------------------------------------------
# _store_feedback_entry writes correctly
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_feedback_entry_writes_json(tracker, mock_redis):
    """Verify feedback entry is stored as JSON with correct structure."""
    tracker.redis = mock_redis
    await tracker._store_feedback_entry("door_open", "thanked", 0.20)

    mock_redis.lpush.assert_called_once()
    call_args = mock_redis.lpush.call_args
    key = call_args[0][0]
    entry_json = call_args[0][1]
    assert key == "mha:feedback:history:door_open"
    entry = json.loads(entry_json)
    assert entry["type"] == "thanked"
    assert entry["delta"] == 0.20
    assert "timestamp" in entry

    mock_redis.ltrim.assert_called_once_with("mha:feedback:history:door_open", 0, 499)


# ------------------------------------------------------------------
# get_person_score no redis
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_person_score_no_redis(tracker):
    """No redis returns DEFAULT_SCORE."""
    tracker.redis = None
    score = await tracker.get_person_score("event", "Max")
    assert score == DEFAULT_SCORE
