"""
Tests fuer ErrorPatternTracker — Wiederkehrende Fehlermuster.
"""

import json
from unittest.mock import AsyncMock

import pytest

from assistant.error_patterns import (
    ErrorPatternTracker,
    MITIGATION_USE_FALLBACK,
    MITIGATION_WARN_USER,
)


@pytest.fixture
def tracker(redis_mock):
    t = ErrorPatternTracker()
    t.redis = redis_mock
    t.enabled = True
    t._min_occurrences = 3
    return t


class TestRecordError:
    """Tests fuer record_error()."""

    @pytest.mark.asyncio
    async def test_records_error(self, tracker):
        tracker.redis.incr.return_value = 1
        await tracker.record_error("timeout", action_type="llm_chat", model="qwen3:14b")
        tracker.redis.lpush.assert_called_once()
        tracker.redis.incr.assert_called()

    @pytest.mark.asyncio
    async def test_disabled_no_record(self, tracker):
        tracker.enabled = False
        await tracker.record_error("timeout")
        tracker.redis.lpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_activates_mitigation_at_threshold(self, tracker):
        tracker.redis.incr.return_value = 3  # Threshold erreicht
        await tracker.record_error("timeout", action_type="llm_chat", model="qwen3:14b")
        # Mitigation sollte aktiviert werden
        assert tracker.redis.setex.call_count >= 1

    @pytest.mark.asyncio
    async def test_no_mitigation_below_threshold(self, tracker):
        tracker.redis.incr.return_value = 2  # Unter Threshold
        await tracker.record_error("timeout", action_type="llm_chat", model="qwen3:14b")
        # Nur lpush + expire, kein mitigation setex
        # incr wird aufgerufen, aber kein setex fuer mitigation
        setex_calls = [c for c in tracker.redis.setex.call_args_list]
        mitigation_calls = [c for c in setex_calls if "mitigation" in str(c)]
        assert len(mitigation_calls) == 0


class TestGetMitigation:
    """Tests fuer get_mitigation()."""

    @pytest.mark.asyncio
    async def test_no_mitigation(self, tracker):
        tracker.redis.get.return_value = None
        result = await tracker.get_mitigation("llm_chat", "qwen3:14b")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_mitigation(self, tracker):
        mitigation = {
            "type": MITIGATION_USE_FALLBACK,
            "reason": "3x timeout",
            "original_model": "qwen3:14b",
        }
        tracker.redis.get.return_value = json.dumps(mitigation)
        result = await tracker.get_mitigation(action_type="llm_chat", model="qwen3:14b")
        assert result is not None
        assert result["type"] == MITIGATION_USE_FALLBACK

    @pytest.mark.asyncio
    async def test_disabled_returns_none(self, tracker):
        tracker.enabled = False
        result = await tracker.get_mitigation("llm_chat")
        assert result is None


class TestGetStats:
    """Tests fuer get_stats()."""

    @pytest.mark.asyncio
    async def test_empty_stats(self, tracker):
        tracker.redis.lrange.return_value = []
        tracker.redis.scan.return_value = (0, [])
        stats = await tracker.get_stats()
        assert stats["total_recent"] == 0
        assert stats["last_24h"] == 0
        assert stats["active_mitigations"] == 0
