"""
Tests fuer ResponseQualityTracker — Antwort-Qualitaets-Messung.
"""

import time
from unittest.mock import AsyncMock

import pytest

from assistant.response_quality import (
    ResponseQualityTracker,
    DEFAULT_SCORE,
    MIN_EXCHANGES_FOR_SCORE,
)


@pytest.fixture
def tracker(redis_mock):
    t = ResponseQualityTracker()
    t.redis = redis_mock
    t.enabled = True
    return t


class TestCheckFollowup:
    """Tests fuer check_followup()."""

    def test_no_previous_text(self, tracker):
        result = tracker.check_followup("Mach das Licht an")
        assert result is None

    def test_followup_within_window(self, tracker):
        tracker._last_user_text = "Mach das Licht an"
        tracker._last_response_time = time.time() - 10  # 10s ago
        tracker._last_response_category = "device_command"
        result = tracker.check_followup("Und die Heizung?")
        assert result is not None
        assert result["is_followup"] is True

    def test_no_followup_outside_window(self, tracker):
        tracker._last_user_text = "Mach das Licht an"
        tracker._last_response_time = time.time() - 120  # 2 min ago
        tracker._last_response_category = "device_command"
        result = tracker.check_followup("Wie wird das Wetter?")
        assert result is None

    def test_rephrase_detected(self, tracker):
        tracker._last_user_text = "Licht Wohnzimmer einschalten"
        tracker._last_response_time = time.time() - 30
        tracker._last_response_category = "device_command"
        # Gleiche Keywords in anderer Reihenfolge (hoher Overlap nach Stopword-Entfernung)
        result = tracker.check_followup("Wohnzimmer Licht einschalten")
        assert result is not None
        assert result["is_rephrase"] is True

    def test_disabled_returns_none(self, tracker):
        tracker.enabled = False
        tracker._last_user_text = "Test"
        result = tracker.check_followup("Test2")
        assert result is None


class TestRecordExchange:
    """Tests fuer record_exchange()."""

    @pytest.mark.asyncio
    async def test_clear_exchange(self, tracker):
        await tracker.record_exchange("device_command", person="Max")
        tracker.redis.hincrby.assert_called()
        tracker.redis.lpush.assert_called_once()

    @pytest.mark.asyncio
    async def test_thanked_exchange(self, tracker):
        await tracker.record_exchange("device_command", was_thanked=True)
        # "thanked" = clear quality
        tracker.redis.hincrby.assert_called()

    @pytest.mark.asyncio
    async def test_rephrased_exchange(self, tracker):
        await tracker.record_exchange("knowledge", was_rephrased=True)
        tracker.redis.hincrby.assert_called()

    @pytest.mark.asyncio
    async def test_disabled_no_record(self, tracker):
        tracker.enabled = False
        await tracker.record_exchange("device_command")
        tracker.redis.hincrby.assert_not_called()

    @pytest.mark.asyncio
    async def test_per_person_stats(self, tracker):
        await tracker.record_exchange("device_command", person="Lisa")
        # Should have calls for both global and per-person stats
        assert tracker.redis.hincrby.call_count >= 2


class TestDetectRephrase:
    """Tests fuer _detect_rephrase()."""

    def test_similar_texts(self, tracker):
        assert tracker._detect_rephrase(
            "Licht Wohnzimmer einschalten",
            "Wohnzimmer Licht einschalten",
        ) is True

    def test_different_texts(self, tracker):
        assert tracker._detect_rephrase(
            "Wie wird das Wetter morgen?",
            "Mach die Heizung an",
        ) is False

    def test_empty_texts(self, tracker):
        assert tracker._detect_rephrase("", "") is False
        assert tracker._detect_rephrase("Test", "") is False


class TestUpdateLastExchange:
    """Tests fuer update_last_exchange()."""

    def test_updates_state(self, tracker):
        tracker.update_last_exchange("Test text", "device_command")
        assert tracker._last_user_text == "Test text"
        assert tracker._last_response_category == "device_command"
        assert tracker._last_response_time > 0


class TestGetQualityScore:
    """Tests fuer get_quality_score()."""

    @pytest.mark.asyncio
    async def test_default_score(self, tracker):
        tracker.redis.get.return_value = None
        tracker.redis.hget.return_value = None
        score = await tracker.get_quality_score("device_command")
        assert score == DEFAULT_SCORE

    @pytest.mark.asyncio
    async def test_stored_score(self, tracker):
        tracker.redis.get.return_value = "0.92"
        score = await tracker.get_quality_score("device_command")
        assert score == 0.92

    @pytest.mark.asyncio
    async def test_no_score_below_min_exchanges(self, tracker):
        """Returns default when no stored score and total < MIN_EXCHANGES."""
        tracker.redis.get.return_value = None
        tracker.redis.hget.return_value = str(MIN_EXCHANGES_FOR_SCORE - 1)
        score = await tracker.get_quality_score("knowledge")
        assert score == DEFAULT_SCORE

    @pytest.mark.asyncio
    async def test_no_redis_returns_default(self):
        t = ResponseQualityTracker()
        t.redis = None
        t.enabled = True
        score = await t.get_quality_score("device_command")
        assert score == DEFAULT_SCORE


# ── initialize ───────────────────────────────────────────

class TestInitialize:
    """Tests fuer initialize()."""

    @pytest.mark.asyncio
    async def test_initialize_with_redis(self, redis_mock):
        t = ResponseQualityTracker()
        await t.initialize(redis_mock)
        assert t.redis is redis_mock
        assert t.enabled is True

    @pytest.mark.asyncio
    async def test_initialize_with_none(self):
        t = ResponseQualityTracker()
        await t.initialize(None)
        assert t.enabled is False


# ── get_person_score ─────────────────────────────────────

class TestGetPersonScore:
    """Tests fuer get_person_score()."""

    @pytest.mark.asyncio
    async def test_returns_stored_person_score(self, tracker):
        tracker.redis.get.return_value = "0.85"
        score = await tracker.get_person_score("device_command", "Max")
        assert score == 0.85

    @pytest.mark.asyncio
    async def test_no_stored_returns_default(self, tracker):
        tracker.redis.get.return_value = None
        score = await tracker.get_person_score("device_command", "Max")
        assert score == DEFAULT_SCORE

    @pytest.mark.asyncio
    async def test_no_redis_returns_default(self):
        t = ResponseQualityTracker()
        t.redis = None
        t.enabled = True
        score = await t.get_person_score("device_command", "Max")
        assert score == DEFAULT_SCORE

    @pytest.mark.asyncio
    async def test_empty_person_returns_default(self, tracker):
        score = await tracker.get_person_score("device_command", "")
        assert score == DEFAULT_SCORE


# ── get_stats ────────────────────────────────────────────

class TestGetStats:
    """Tests fuer get_stats()."""

    @pytest.mark.asyncio
    async def test_no_redis_returns_empty(self):
        t = ResponseQualityTracker()
        t.redis = None
        t.enabled = True
        stats = await t.get_stats()
        assert stats == {}

    @pytest.mark.asyncio
    async def test_returns_stats_with_data(self, tracker):
        tracker.redis.hgetall = AsyncMock(side_effect=[
            {b"clear": b"10", b"unclear": b"2", b"total": b"12"},  # device_command
            {},  # knowledge
            {},  # smalltalk
            {},  # analysis
        ])
        tracker.redis.get = AsyncMock(return_value="0.85")
        tracker.redis.hget = AsyncMock(return_value="12")
        stats = await tracker.get_stats()
        assert "device_command" in stats
        assert stats["device_command"]["score"] == 0.85
        assert stats["device_command"]["clear"] == 10.0

    @pytest.mark.asyncio
    async def test_empty_categories_excluded(self, tracker):
        tracker.redis.hgetall = AsyncMock(return_value={})
        stats = await tracker.get_stats()
        assert stats == {}


# ── _update_score ────────────────────────────────────────

class TestUpdateScore:
    """Tests fuer _update_score() EMA calculation."""

    @pytest.mark.asyncio
    async def test_no_redis_returns_early(self):
        t = ResponseQualityTracker()
        t.redis = None
        await t._update_score("device_command", 1.0)
        # No exception

    @pytest.mark.asyncio
    async def test_below_min_exchanges_no_update(self, tracker):
        tracker.redis.hget = AsyncMock(return_value=str(MIN_EXCHANGES_FOR_SCORE - 1))
        await tracker._update_score("device_command", 1.0)
        tracker.redis.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_ema_calculation(self, tracker):
        tracker.redis.hget = AsyncMock(return_value=str(MIN_EXCHANGES_FOR_SCORE + 5))
        tracker.redis.get = AsyncMock(return_value="0.5")
        await tracker._update_score("device_command", 1.0)
        # EMA: 0.1 * 1.0 + 0.9 * 0.5 = 0.55
        tracker.redis.setex.assert_called_once()
        call_args = tracker.redis.setex.call_args[0]
        new_score = float(call_args[2])
        assert abs(new_score - 0.55) < 0.01

    @pytest.mark.asyncio
    async def test_ema_with_no_existing_score(self, tracker):
        tracker.redis.hget = AsyncMock(return_value=str(MIN_EXCHANGES_FOR_SCORE + 5))
        tracker.redis.get = AsyncMock(return_value=None)
        await tracker._update_score("device_command", 0.0)
        # EMA: 0.1 * 0.0 + 0.9 * 0.5 (DEFAULT_SCORE) = 0.45
        tracker.redis.setex.assert_called_once()
        call_args = tracker.redis.setex.call_args[0]
        new_score = float(call_args[2])
        assert abs(new_score - 0.45) < 0.01

    @pytest.mark.asyncio
    async def test_ema_per_person(self, tracker):
        tracker.redis.hget = AsyncMock(return_value=str(MIN_EXCHANGES_FOR_SCORE + 5))
        tracker.redis.get = AsyncMock(return_value="0.8")
        await tracker._update_score("device_command", 1.0, person="Max")
        tracker.redis.setex.assert_called_once()
        key_arg = tracker.redis.setex.call_args[0][0]
        assert "person:Max" in key_arg

    @pytest.mark.asyncio
    async def test_score_clamped_to_0_1(self, tracker):
        tracker.redis.hget = AsyncMock(return_value=str(MIN_EXCHANGES_FOR_SCORE + 5))
        tracker.redis.get = AsyncMock(return_value="0.99")
        await tracker._update_score("device_command", 1.0)
        call_args = tracker.redis.setex.call_args[0]
        new_score = float(call_args[2])
        assert 0.0 <= new_score <= 1.0
