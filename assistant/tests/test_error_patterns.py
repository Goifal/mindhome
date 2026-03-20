"""
Tests fuer ErrorPatternTracker — Wiederkehrende Fehlermuster.
"""

import json
import time
from unittest.mock import AsyncMock

import pytest

from assistant.error_patterns import (
    ErrorPatternTracker,
    ERROR_TYPES,
    MITIGATION_USE_FALLBACK,
    MITIGATION_WARN_USER,
    MITIGATION_SKIP_ENTITY,
)


@pytest.fixture
def tracker(redis_mock):
    t = ErrorPatternTracker()
    t.redis = redis_mock
    t.enabled = True
    t._min_occurrences = 3
    return t


# ============================================================
# record_error
# ============================================================

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
        setex_calls = [c for c in tracker.redis.setex.call_args_list]
        mitigation_calls = [c for c in setex_calls if "mitigation" in str(c)]
        assert len(mitigation_calls) == 0

    @pytest.mark.asyncio
    async def test_error_entry_structure(self, tracker):
        """Recorded error entry should contain expected fields."""
        tracker.redis.incr = AsyncMock(return_value=1)
        await tracker.record_error(
            "timeout",
            action_type="llm_chat",
            model="qwen3.5:9b",
            context="Connection timed out",
        )
        entry_json = tracker.redis.lpush.call_args[0][1]
        entry = json.loads(entry_json)
        assert entry["error_type"] == "timeout"
        assert entry["action_type"] == "llm_chat"
        assert entry["model"] == "qwen3.5:9b"
        assert entry["context"] == "Connection timed out"
        assert "timestamp" in entry
        assert "ts" in entry

    @pytest.mark.asyncio
    async def test_recent_list_trimmed_to_200(self, tracker):
        """Recent error list should be trimmed to 200 entries."""
        tracker.redis.incr = AsyncMock(return_value=1)
        await tracker.record_error("timeout")
        tracker.redis.ltrim.assert_called_once()
        trim_args = tracker.redis.ltrim.call_args[0]
        assert trim_args[2] == 199  # 0 to 199 = 200 entries

    @pytest.mark.asyncio
    async def test_recent_list_has_30_day_ttl(self, tracker):
        """Recent error list should have 30-day TTL."""
        tracker.redis.incr = AsyncMock(return_value=1)
        await tracker.record_error("timeout")
        # Check expire was called for the recent list
        expire_calls = tracker.redis.expire.call_args_list
        recent_expire = [c for c in expire_calls if "recent" in str(c)]
        assert len(recent_expire) >= 1
        ttl = recent_expire[0][0][1]
        assert ttl == 30 * 86400

    @pytest.mark.asyncio
    async def test_pattern_key_has_2h_ttl(self, tracker):
        """Pattern counter key should have 2h TTL."""
        tracker.redis.incr = AsyncMock(return_value=1)
        await tracker.record_error("timeout", action_type="llm_chat")
        expire_calls = tracker.redis.expire.call_args_list
        pattern_expire = [c for c in expire_calls if "pattern" in str(c)]
        assert len(pattern_expire) >= 1
        ttl = pattern_expire[0][0][1]
        assert ttl == 7200


# ============================================================
# record_error additional paths
# ============================================================

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

    @pytest.mark.asyncio
    async def test_empty_context_stored_as_empty(self, tracker):
        """Empty context should be stored as empty string."""
        tracker.redis.incr = AsyncMock(return_value=1)
        await tracker.record_error("timeout", context="")
        entry_json = tracker.redis.lpush.call_args[0][1]
        entry = json.loads(entry_json)
        assert entry["context"] == ""

    @pytest.mark.asyncio
    async def test_all_valid_error_types_accepted(self, tracker):
        """All valid error types should be stored as-is, not normalized."""
        tracker.redis.incr = AsyncMock(return_value=1)
        for error_type in ERROR_TYPES:
            tracker.redis.lpush.reset_mock()
            await tracker.record_error(error_type)
            entry_json = tracker.redis.lpush.call_args[0][1]
            entry = json.loads(entry_json)
            assert entry["error_type"] == error_type

    @pytest.mark.asyncio
    async def test_no_redis_returns_early(self):
        """Without redis, record_error should not crash."""
        t = ErrorPatternTracker()
        t.redis = None
        t.enabled = True
        await t.record_error("timeout")
        # No exception


# ============================================================
# get_mitigation
# ============================================================

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

    @pytest.mark.asyncio
    async def test_no_redis_returns_none(self):
        """Without redis, get_mitigation should return None."""
        t = ErrorPatternTracker()
        t.redis = None
        t.enabled = True
        result = await t.get_mitigation("llm_chat", "model")
        assert result is None

    @pytest.mark.asyncio
    async def test_model_not_found_falls_to_action(self, tracker):
        """When model-specific mitigation not found, falls back to action-type."""
        action_mit = {"type": "warn_user", "reason": "test"}
        tracker.redis.get = AsyncMock(side_effect=[
            None,  # model mitigation -> not found
            json.dumps(action_mit),  # action mitigation -> found
        ])
        result = await tracker.get_mitigation(action_type="set_light", model="some_model")
        assert result is not None
        assert result["type"] == "warn_user"


# ============================================================
# get_stats
# ============================================================

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

    @pytest.mark.asyncio
    async def test_stats_by_type_aggregation(self, tracker):
        """Verify correct aggregation of error types."""
        now = time.time()
        entries = [
            json.dumps({"error_type": "timeout", "ts": now - 100}).encode(),
            json.dumps({"error_type": "timeout", "ts": now - 200}).encode(),
            json.dumps({"error_type": "timeout", "ts": now - 300}).encode(),
            json.dumps({"error_type": "entity_not_found", "ts": now - 100}).encode(),
        ]
        tracker.redis.lrange = AsyncMock(return_value=entries)
        tracker.redis.scan = AsyncMock(return_value=(0, []))
        stats = await tracker.get_stats()
        assert stats["by_type"]["timeout"] == 3
        assert stats["by_type"]["entity_not_found"] == 1
        assert stats["last_24h"] == 4

    @pytest.mark.asyncio
    async def test_stats_entries_older_than_24h_not_in_last_24h(self, tracker):
        """Entries older than 24h should not be counted in last_24h."""
        old_ts = time.time() - 2 * 86400  # 2 days ago
        entries = [
            json.dumps({"error_type": "timeout", "ts": old_ts}).encode(),
        ]
        tracker.redis.lrange = AsyncMock(return_value=entries)
        tracker.redis.scan = AsyncMock(return_value=(0, []))
        stats = await tracker.get_stats()
        assert stats["total_recent"] == 1
        assert stats["last_24h"] == 0


# ============================================================
# initialize
# ============================================================

class TestInitialize:
    """Tests fuer initialize()."""

    @pytest.mark.asyncio
    async def test_initialize_with_redis(self, redis_mock):
        t = ErrorPatternTracker()
        await t.initialize(redis_mock)
        assert t.redis is redis_mock
        assert t.enabled is True

    @pytest.mark.asyncio
    async def test_initialize_with_none(self):
        t = ErrorPatternTracker()
        await t.initialize(None)
        assert t.enabled is False

    @pytest.mark.asyncio
    async def test_initialize_preserves_config(self):
        """Config settings should be preserved after initialization."""
        t = ErrorPatternTracker()
        min_occ = t._min_occurrences
        ttl_hours = t._mitigation_ttl_hours
        await t.initialize(None)
        assert t._min_occurrences == min_occ
        assert t._mitigation_ttl_hours == ttl_hours


# ============================================================
# _activate_mitigation
# ============================================================

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

    @pytest.mark.asyncio
    async def test_mitigation_ttl_matches_config(self, tracker):
        """TTL of the mitigation key should match _mitigation_ttl_hours * 3600."""
        tracker._mitigation_ttl_hours = 2
        await tracker._activate_mitigation("timeout", "llm_chat", "qwen3.5:9b", 3)
        call_args = tracker.redis.setex.call_args[0]
        ttl = call_args[1]
        assert ttl == 2 * 3600

    @pytest.mark.asyncio
    async def test_mitigation_contains_activated_at(self, tracker):
        """Mitigation data should include activated_at timestamp."""
        await tracker._activate_mitigation("timeout", "llm_chat", "qwen3.5:9b", 3)
        val = json.loads(tracker.redis.setex.call_args[0][2])
        assert "activated_at" in val

    @pytest.mark.asyncio
    async def test_mitigation_reason_contains_count(self, tracker):
        """Mitigation reason should mention the error count."""
        await tracker._activate_mitigation("timeout", "llm_chat", "qwen3.5:9b", 5)
        val = json.loads(tracker.redis.setex.call_args[0][2])
        assert "5x" in val["reason"] or "5" in val["reason"]

    @pytest.mark.asyncio
    async def test_bad_params_creates_fix_params_mitigation(self, tracker):
        """bad_params error type creates a fix_params mitigation."""
        await tracker._activate_mitigation("bad_params", "set_light", "model", 3)
        tracker.redis.setex.assert_called_once()
        call_args = tracker.redis.setex.call_args
        stored = json.loads(call_args[0][2])
        assert stored["type"] == "fix_params"
        assert "bad_params" in stored["reason"]

    @pytest.mark.asyncio
    async def test_model_overloaded_no_mitigation_without_model(self, tracker):
        """model_overloaded without model should not create mitigation."""
        await tracker._activate_mitigation("model_overloaded", "llm_chat", "", 3)
        tracker.redis.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_model_overloaded_creates_retry_delay(self, tracker):
        """model_overloaded with model creates retry_delay mitigation."""
        await tracker._activate_mitigation("model_overloaded", "llm_chat", "qwen2.5:14b", 3)
        tracker.redis.setex.assert_called_once()
        call_args = tracker.redis.setex.call_args
        stored = json.loads(call_args[0][2])
        assert stored["type"] == "retry_delay"
        assert stored["retry_delay_seconds"] == 90  # min(30*3, 120)


# ============================================================
# ERROR_TYPES constant
# ============================================================

class TestErrorTypesConstant:
    """Verify the ERROR_TYPES tuple."""

    def test_known_types(self):
        assert "timeout" in ERROR_TYPES
        assert "service_unavailable" in ERROR_TYPES
        assert "entity_not_found" in ERROR_TYPES
        assert "bad_params" in ERROR_TYPES
        assert "model_overloaded" in ERROR_TYPES
        assert "unknown" in ERROR_TYPES

    def test_count(self):
        assert len(ERROR_TYPES) == 6
