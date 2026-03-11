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
        await tracker.record_error("timeout", action_type="llm_chat", model="qwen3.5:9b")
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
        await tracker.record_error("timeout", action_type="llm_chat", model="qwen3.5:9b")
        # Mitigation sollte aktiviert werden
        assert tracker.redis.setex.call_count >= 1

    @pytest.mark.asyncio
    async def test_no_mitigation_below_threshold(self, tracker):
        tracker.redis.incr.return_value = 2  # Unter Threshold
        await tracker.record_error("timeout", action_type="llm_chat", model="qwen3.5:9b")
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
        result = await tracker.get_mitigation("llm_chat", "qwen3.5:9b")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_mitigation(self, tracker):
        mitigation = {
            "type": MITIGATION_USE_FALLBACK,
            "reason": "3x timeout",
            "original_model": "qwen3.5:9b",
        }
        tracker.redis.get.return_value = json.dumps(mitigation)
        result = await tracker.get_mitigation(action_type="llm_chat", model="qwen3.5:9b")
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

    @pytest.mark.asyncio
    async def test_stats_with_data(self, tracker):
        import time
        now = time.time()
        entries = [
            json.dumps({"error_type": "timeout", "ts": now - 3600}).encode(),
            json.dumps({"error_type": "timeout", "ts": now - 100}).encode(),
            json.dumps({"error_type": "service_unavailable", "ts": now - 200}).encode(),
            json.dumps({"error_type": "bad_params", "ts": now - 100000}).encode(),  # >24h ago
        ]
        tracker.redis.lrange = AsyncMock(return_value=entries)
        tracker.redis.scan = AsyncMock(return_value=(0, [b"key1", b"key2"]))

        stats = await tracker.get_stats()
        assert stats["total_recent"] == 4
        assert stats["last_24h"] == 3
        assert stats["by_type"]["timeout"] == 2
        assert stats["by_type"]["service_unavailable"] == 1
        assert stats["active_mitigations"] == 2

    @pytest.mark.asyncio
    async def test_stats_scan_multiple_pages(self, tracker):
        tracker.redis.lrange = AsyncMock(return_value=[])
        tracker.redis.scan = AsyncMock(side_effect=[
            (5, [b"k1"]),
            (0, [b"k2", b"k3"]),
        ])
        stats = await tracker.get_stats()
        assert stats["active_mitigations"] == 3

    @pytest.mark.asyncio
    async def test_stats_scan_exception(self, tracker):
        tracker.redis.lrange = AsyncMock(return_value=[])
        tracker.redis.scan = AsyncMock(side_effect=RuntimeError("scan failed"))
        stats = await tracker.get_stats()
        assert stats["active_mitigations"] == 0

    @pytest.mark.asyncio
    async def test_stats_no_redis(self):
        from assistant.error_patterns import ErrorPatternTracker
        t = ErrorPatternTracker()
        t.redis = None
        t.enabled = True
        stats = await t.get_stats()
        assert stats == {}

    @pytest.mark.asyncio
    async def test_stats_invalid_json_entries(self, tracker):
        tracker.redis.lrange = AsyncMock(return_value=[
            b"not json at all",
            json.dumps({"error_type": "timeout", "ts": 0}).encode(),
        ])
        tracker.redis.scan = AsyncMock(return_value=(0, []))
        stats = await tracker.get_stats()
        assert stats["total_recent"] == 2
        assert stats["by_type"].get("timeout", 0) == 1


# ── initialize ───────────────────────────────────────────

class TestInitialize:
    """Tests fuer initialize()."""

    @pytest.mark.asyncio
    async def test_initialize_with_redis(self, redis_mock):
        from assistant.error_patterns import ErrorPatternTracker
        t = ErrorPatternTracker()
        await t.initialize(redis_mock)
        assert t.redis is redis_mock
        assert t.enabled is True

    @pytest.mark.asyncio
    async def test_initialize_with_none(self):
        from assistant.error_patterns import ErrorPatternTracker
        t = ErrorPatternTracker()
        await t.initialize(None)
        assert t.enabled is False


# ── _activate_mitigation ─────────────────────────────────

class TestActivateMitigation:
    """Tests fuer _activate_mitigation() all paths."""

    @pytest.mark.asyncio
    async def test_timeout_with_model(self, tracker):
        await tracker._activate_mitigation("timeout", "llm_chat", "qwen3.5:9b", 3)
        tracker.redis.setex.assert_called_once()
        key_arg = tracker.redis.setex.call_args[0][0]
        assert "model:qwen3.5:9b" in key_arg
        val = json.loads(tracker.redis.setex.call_args[0][2])
        assert val["type"] == "use_fallback"

    @pytest.mark.asyncio
    async def test_service_unavailable_with_action(self, tracker):
        await tracker._activate_mitigation("service_unavailable", "set_light", "", 3)
        tracker.redis.setex.assert_called_once()
        key_arg = tracker.redis.setex.call_args[0][0]
        assert "set_light" in key_arg
        val = json.loads(tracker.redis.setex.call_args[0][2])
        assert val["type"] == "warn_user"

    @pytest.mark.asyncio
    async def test_entity_not_found_with_action(self, tracker):
        from assistant.error_patterns import MITIGATION_SKIP_ENTITY
        await tracker._activate_mitigation("entity_not_found", "set_climate", "", 3)
        tracker.redis.setex.assert_called_once()
        val = json.loads(tracker.redis.setex.call_args[0][2])
        assert val["type"] == MITIGATION_SKIP_ENTITY

    @pytest.mark.asyncio
    async def test_timeout_without_model_no_action(self, tracker):
        """timeout without model should not create mitigation."""
        await tracker._activate_mitigation("timeout", "llm_chat", "", 3)
        tracker.redis.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_error_type_no_action(self, tracker):
        """Unknown error type should not create mitigation."""
        await tracker._activate_mitigation("unknown", "something", "model", 3)
        tracker.redis.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_redis_returns_early(self, tracker):
        tracker.redis = None
        await tracker._activate_mitigation("timeout", "llm_chat", "model", 3)
        # No exception


# ── get_mitigation additional paths ──────────────────────

class TestGetMitigationPaths:
    """Additional tests for get_mitigation()."""

    @pytest.mark.asyncio
    async def test_action_type_mitigation(self, tracker):
        """Gets action-type specific mitigation when no model."""
        mitigation = {"type": "warn_user", "reason": "3x service_unavailable"}
        tracker.redis.get = AsyncMock(return_value=json.dumps(mitigation))
        result = await tracker.get_mitigation(action_type="set_light")
        assert result is not None
        assert result["type"] == "warn_user"

    @pytest.mark.asyncio
    async def test_model_mitigation_takes_priority(self, tracker):
        """Model-specific mitigation found first."""
        model_mit = {"type": "use_fallback", "original_model": "qwen3.5:9b"}
        tracker.redis.get = AsyncMock(return_value=json.dumps(model_mit))
        result = await tracker.get_mitigation(action_type="llm_chat", model="qwen3.5:9b")
        assert result["type"] == "use_fallback"

    @pytest.mark.asyncio
    async def test_invalid_json_returns_none(self, tracker):
        """Invalid JSON in stored mitigation falls through."""
        tracker.redis.get = AsyncMock(side_effect=[
            "not json",  # model mitigation
            None,        # action mitigation
        ])
        result = await tracker.get_mitigation(action_type="set_light", model="some_model")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_model_no_action(self, tracker):
        """Neither model nor action_type returns None."""
        result = await tracker.get_mitigation()
        assert result is None


# ── record_error additional paths ────────────────────────

class TestRecordErrorPaths:
    """Additional tests for record_error()."""

    @pytest.mark.asyncio
    async def test_unknown_error_type_normalized(self, tracker):
        """Unknown error type should be normalized to 'unknown'."""
        tracker.redis.incr = AsyncMock(return_value=1)
        await tracker.record_error("weird_error", action_type="something")
        # The pattern key should contain "unknown"
        incr_calls = tracker.redis.incr.call_args_list
        assert any("unknown" in str(c) for c in incr_calls)

    @pytest.mark.asyncio
    async def test_no_model_no_model_counter(self, tracker):
        """When model is empty, model-specific counter not incremented."""
        tracker.redis.incr = AsyncMock(return_value=1)
        await tracker.record_error("timeout", action_type="llm_chat", model="")
        # Only one incr call (pattern counter), no model counter
        assert tracker.redis.incr.call_count == 1

    @pytest.mark.asyncio
    async def test_model_specific_threshold_triggers_mitigation(self, tracker):
        """Model-specific counter reaching threshold triggers mitigation."""
        tracker.redis.incr = AsyncMock(side_effect=[1, 3])  # pattern=1, model=3
        await tracker.record_error("timeout", action_type="llm_chat", model="qwen3.5:9b")
        tracker.redis.setex.assert_called()  # mitigation activated

    @pytest.mark.asyncio
    async def test_context_truncated(self, tracker):
        """Long context is truncated to 200 chars."""
        tracker.redis.incr = AsyncMock(return_value=1)
        long_context = "x" * 500
        await tracker.record_error("timeout", context=long_context)
        entry_json = tracker.redis.lpush.call_args[0][1]
        entry = json.loads(entry_json)
        assert len(entry["context"]) == 200
