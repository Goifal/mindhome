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
