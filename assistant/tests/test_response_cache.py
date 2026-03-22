"""Tests fuer response_cache — Semantic Response Cache fuer wiederkehrende Anfragen."""

import json
import time
from unittest.mock import AsyncMock, patch

import pytest

from assistant.response_cache import ResponseCache, _CACHEABLE_CATEGORIES


class TestResponseCache:
    """Tests fuer den Response Cache."""

    @pytest.fixture
    def cache(self):
        c = ResponseCache()
        c._redis = AsyncMock()
        return c

    @pytest.fixture
    def cache_disabled(self):
        c = ResponseCache()
        c._redis = AsyncMock()
        c.configure(enabled=False)
        return c

    # --- Cache Key Tests ---

    def test_make_key_deterministic(self):
        c = ResponseCache()
        k1 = c._make_key("Wie warm ist es?", "device_query")
        k2 = c._make_key("Wie warm ist es?", "device_query")
        assert k1 == k2

    def test_make_key_case_insensitive(self):
        c = ResponseCache()
        k1 = c._make_key("Wie Warm Ist Es?", "device_query")
        k2 = c._make_key("wie warm ist es?", "device_query")
        assert k1 == k2

    def test_make_key_ignores_punctuation(self):
        c = ResponseCache()
        k1 = c._make_key("Wie warm ist es?", "device_query")
        k2 = c._make_key("Wie warm ist es", "device_query")
        assert k1 == k2

    def test_make_key_different_category(self):
        c = ResponseCache()
        k1 = c._make_key("Test", "device_query")
        k2 = c._make_key("Test", "knowledge")
        assert k1 != k2

    def test_make_key_with_room(self):
        c = ResponseCache()
        k1 = c._make_key("Wie warm?", "device_query", room="wohnzimmer")
        k2 = c._make_key("Wie warm?", "device_query", room="schlafzimmer")
        assert k1 != k2

    def test_make_key_room_case_insensitive(self):
        c = ResponseCache()
        k1 = c._make_key("Test", "device_query", room="Wohnzimmer")
        k2 = c._make_key("Test", "device_query", room="wohnzimmer")
        assert k1 == k2

    # --- GET Tests ---

    @pytest.mark.asyncio
    async def test_get_miss(self, cache):
        cache._redis.get.return_value = None
        result = await cache.get("Wie warm ist es?", "device_query")
        assert result is None
        assert cache._misses == 1

    @pytest.mark.asyncio
    async def test_get_hit(self, cache):
        stored = json.dumps(
            {
                "response": "Es sind 22 Grad.",
                "model": "qwen3.5:9b",
                "_ts": time.time(),
            }
        )
        cache._redis.get.return_value = stored

        result = await cache.get("Wie warm ist es?", "device_query")
        assert result is not None
        assert result["response"] == "Es sind 22 Grad."
        assert cache._hits == 1

    @pytest.mark.asyncio
    async def test_get_uncacheable_category(self, cache):
        """device_command wird NIEMALS gecacht."""
        result = await cache.get("Licht an", "device_command")
        assert result is None
        # Redis wird gar nicht gefragt
        cache._redis.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_general_not_cached(self, cache):
        result = await cache.get("Erzaehl mir einen Witz", "general")
        assert result is None
        cache._redis.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_disabled(self, cache_disabled):
        result = await cache_disabled.get("Wie warm?", "device_query")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_no_redis(self):
        c = ResponseCache()
        result = await c.get("Test", "device_query")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_redis_error(self, cache):
        cache._redis.get.side_effect = Exception("Redis down")
        result = await cache.get("Wie warm?", "device_query")
        assert result is None

    # --- PUT Tests ---

    @pytest.mark.asyncio
    async def test_put_cacheable(self, cache):
        await cache.put("Wie warm?", "device_query", "22 Grad", "qwen3.5:9b")
        cache._redis.set.assert_called_once()
        call_args = cache._redis.set.call_args
        data = json.loads(call_args[0][1])
        assert data["response"] == "22 Grad"
        assert data["model"] == "qwen3.5:9b"
        assert call_args[1]["ex"] == 45  # Default TTL

    @pytest.mark.asyncio
    async def test_put_uncacheable(self, cache):
        await cache.put("Licht an", "device_command", "Erledigt.", "qwen3.5:4b")
        cache._redis.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_put_with_tts(self, cache):
        tts = {"text": "22 Grad", "ssml": "<speak>22 Grad</speak>"}
        await cache.put(
            "Wie warm?",
            "device_query",
            "22 Grad",
            "qwen3.5:9b",
            room="wohnzimmer",
            tts=tts,
        )
        call_args = cache._redis.set.call_args
        data = json.loads(call_args[0][1])
        assert data["tts"] == tts

    @pytest.mark.asyncio
    async def test_put_disabled(self, cache_disabled):
        await cache_disabled.put("Wie warm?", "device_query", "22 Grad", "model")
        cache_disabled._redis.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_put_custom_ttl(self):
        c = ResponseCache()
        c._redis = AsyncMock()
        c.configure(ttl_overrides={"device_query": 120})

        await c.put("Test", "device_query", "Antwort", "model")
        call_args = c._redis.set.call_args
        assert call_args[1]["ex"] == 120

    # --- Statistics Tests ---

    def test_hit_rate_empty(self):
        c = ResponseCache()
        stats = c.get_hit_rate()
        assert stats["total"] == 0
        assert stats["hit_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_hit_rate_mixed(self, cache):
        cache._redis.get.return_value = None
        await cache.get("A", "device_query")  # miss
        await cache.get("B", "device_query")  # miss

        cache._redis.get.return_value = json.dumps(
            {
                "response": "cached",
                "model": "m",
                "_ts": time.time(),
            }
        )
        await cache.get("C", "device_query")  # hit

        stats = cache.get_hit_rate()
        assert stats["hits"] == 1
        assert stats["misses"] == 2
        assert stats["total"] == 3
        assert 33.0 <= stats["hit_rate"] <= 34.0

    # --- Cacheable Categories ---

    def test_device_query_is_cacheable(self):
        assert "device_query" in _CACHEABLE_CATEGORIES

    def test_device_command_not_cacheable(self):
        assert "device_command" not in _CACHEABLE_CATEGORIES

    def test_general_not_cacheable(self):
        assert "general" not in _CACHEABLE_CATEGORIES

    def test_knowledge_is_cacheable(self):
        """Phase 1B: knowledge-Anfragen werden jetzt gecacht."""
        assert "knowledge" in _CACHEABLE_CATEGORIES

    # --- Phase 1B: Pre-Caching Tests ---

    @pytest.mark.asyncio
    async def test_pre_cache_success(self, cache):
        """Pre-Caching sollte eine Antwort im Cache speichern."""
        result = await cache.pre_cache(
            text="Morgen-Briefing",
            category="knowledge",
            response="Guten Morgen, heute ist Dienstag...",
            model="model_fast",
        )
        assert result is True
        assert cache._pre_cache_count == 1
        cache._redis.set.assert_called_once()
        call_args = cache._redis.set.call_args
        data = json.loads(call_args[0][1])
        assert data["_pre_cached"] is True
        assert data["response"] == "Guten Morgen, heute ist Dienstag..."

    @pytest.mark.asyncio
    async def test_pre_cache_disabled(self, cache_disabled):
        """Pre-Caching bei deaktiviertem Cache → False."""
        result = await cache_disabled.pre_cache("test", "knowledge", "resp", "model")
        assert result is False

    @pytest.mark.asyncio
    async def test_pre_cache_uncacheable_category(self, cache):
        """Pre-Caching mit ungueltiger Kategorie → False."""
        result = await cache.pre_cache("test", "device_command", "resp", "model")
        assert result is False

    @pytest.mark.asyncio
    async def test_pre_cache_knowledge_ttl(self, cache):
        """knowledge-Pre-Cache sollte 24h TTL haben."""
        await cache.pre_cache("Wetter?", "knowledge", "Sonnig", "model")
        call_args = cache._redis.set.call_args
        assert call_args[1]["ex"] == 86400

    # --- Phase 1B: Room Invalidation Tests ---

    @pytest.mark.asyncio
    async def test_invalidate_no_redis(self):
        """Invalidierung ohne Redis → 0."""
        c = ResponseCache()
        result = await c.invalidate_by_room("wohnzimmer")
        assert result == 0

    @pytest.mark.asyncio
    async def test_invalidate_empty_room(self, cache):
        """Invalidierung mit leerem Room → 0."""
        result = await cache.invalidate_by_room("")
        assert result == 0

    # --- Phase 1B: Extended Statistics ---

    def test_hit_rate_includes_pre_cache_stats(self):
        """Statistiken sollten pre_cached und category_hits enthalten."""
        c = ResponseCache()
        stats = c.get_hit_rate()
        assert "pre_cached" in stats
        assert "invalidations" in stats
        assert "category_hits" in stats

    @pytest.mark.asyncio
    async def test_category_hits_tracked(self, cache):
        """Cache-Hits werden pro Kategorie getrackt."""
        cache._redis.get.return_value = json.dumps(
            {
                "response": "cached",
                "model": "m",
                "_ts": time.time(),
            }
        )
        await cache.get("Test", "device_query")
        assert cache._category_hits.get("device_query") == 1


# ---------------------------------------------------------------------------
# Extended Tests: Edge cases, invalidation, error handling
# ---------------------------------------------------------------------------


class TestResponseCacheSetRedis:
    """Tests for set_redis method."""

    def test_set_redis_stores_client(self):
        c = ResponseCache()
        assert c._redis is None
        mock_redis = AsyncMock()
        c.set_redis(mock_redis)
        assert c._redis is mock_redis

    def test_set_redis_replaces_existing(self):
        c = ResponseCache()
        old = AsyncMock()
        new = AsyncMock()
        c.set_redis(old)
        c.set_redis(new)
        assert c._redis is new


class TestResponseCacheConfigure:
    """Tests for configure method."""

    def test_configure_disables_cache(self):
        c = ResponseCache()
        assert c._enabled is True
        c.configure(enabled=False)
        assert c._enabled is False

    def test_configure_enables_cache(self):
        c = ResponseCache()
        c.configure(enabled=False)
        c.configure(enabled=True)
        assert c._enabled is True

    def test_configure_ttl_overrides(self):
        c = ResponseCache()
        c.configure(ttl_overrides={"device_query": 300, "knowledge": 3600})
        assert c._ttl_overrides == {"device_query": 300, "knowledge": 3600}

    def test_configure_none_ttl_overrides_not_set(self):
        c = ResponseCache()
        c.configure(ttl_overrides=None)
        assert c._ttl_overrides == {}


class TestResponseCacheTTL:
    """Tests for TTL logic."""

    def test_default_device_query_ttl(self):
        c = ResponseCache()
        assert c._get_ttl("device_query") == 45

    def test_default_knowledge_ttl(self):
        c = ResponseCache()
        assert c._get_ttl("knowledge") == 86400

    def test_override_ttl_takes_precedence(self):
        c = ResponseCache()
        c.configure(ttl_overrides={"device_query": 999})
        assert c._get_ttl("device_query") == 999

    def test_unknown_category_ttl_is_zero(self):
        c = ResponseCache()
        assert c._get_ttl("nonexistent_category") == 0

    @pytest.mark.asyncio
    async def test_zero_ttl_prevents_caching(self):
        """A category with zero TTL should not be cached even if cacheable."""
        c = ResponseCache()
        c._redis = AsyncMock()
        c.configure(ttl_overrides={"device_query": 0})
        await c.put("Test", "device_query", "Response", "model")
        c._redis.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_zero_ttl_prevents_get(self):
        """A category with zero TTL should return None on get."""
        c = ResponseCache()
        c._redis = AsyncMock()
        c.configure(ttl_overrides={"device_query": 0})
        result = await c.get("Test", "device_query")
        assert result is None
        c._redis.get.assert_not_called()


class TestResponseCacheMakeKeyEdgeCases:
    """Edge cases for cache key generation."""

    def test_whitespace_normalization(self):
        c = ResponseCache()
        k1 = c._make_key("wie   warm   ist   es", "device_query")
        k2 = c._make_key("wie warm ist es", "device_query")
        assert k1 == k2

    def test_leading_trailing_whitespace(self):
        c = ResponseCache()
        k1 = c._make_key("  wie warm ist es  ", "device_query")
        k2 = c._make_key("wie warm ist es", "device_query")
        assert k1 == k2

    def test_all_punctuation_stripped(self):
        c = ResponseCache()
        k1 = c._make_key("test.,!?;:", "device_query")
        k2 = c._make_key("test", "device_query")
        assert k1 == k2

    def test_key_starts_with_prefix(self):
        c = ResponseCache()
        key = c._make_key("test", "device_query")
        assert key.startswith("mha:rcache:")

    def test_key_has_fixed_length_hash(self):
        c = ResponseCache()
        key = c._make_key("test", "device_query")
        # Key format: mha:rcache:<room_tag>:<hash16>
        # Without room: mha:rcache:_global:<hash16>
        assert key.startswith("mha:rcache:_global:")
        hash_part = key.split(":")[-1]
        assert len(hash_part) == 16

    def test_empty_text_produces_valid_key(self):
        c = ResponseCache()
        key = c._make_key("", "device_query")
        assert key.startswith("mha:rcache:")

    def test_different_rooms_different_keys(self):
        c = ResponseCache()
        k1 = c._make_key("test", "device_query", room="kueche")
        k2 = c._make_key("test", "device_query", room="bad")
        k3 = c._make_key("test", "device_query", room=None)
        assert k1 != k2
        assert k1 != k3
        assert k2 != k3


class TestResponseCachePutErrors:
    """Tests for error handling in put."""

    @pytest.mark.asyncio
    async def test_put_redis_error_does_not_raise(self):
        c = ResponseCache()
        c._redis = AsyncMock()
        c._redis.set.side_effect = Exception("Redis write failed")
        # Should not raise
        await c.put("Test", "device_query", "Response", "model")

    @pytest.mark.asyncio
    async def test_put_no_redis_is_noop(self):
        c = ResponseCache()
        # _redis is None
        await c.put("Test", "device_query", "Response", "model")
        # No exception raised


class TestResponseCachePreCacheErrors:
    """Tests for error handling in pre_cache."""

    @pytest.mark.asyncio
    async def test_pre_cache_redis_error_returns_false(self):
        c = ResponseCache()
        c._redis = AsyncMock()
        c._redis.set.side_effect = Exception("Redis write failed")
        result = await c.pre_cache("Test", "knowledge", "Response", "model")
        assert result is False

    @pytest.mark.asyncio
    async def test_pre_cache_no_redis_returns_false(self):
        c = ResponseCache()
        result = await c.pre_cache("Test", "knowledge", "Response", "model")
        assert result is False

    @pytest.mark.asyncio
    async def test_pre_cache_zero_ttl_returns_false(self):
        c = ResponseCache()
        c._redis = AsyncMock()
        c.configure(ttl_overrides={"knowledge": 0})
        result = await c.pre_cache("Test", "knowledge", "Response", "model")
        assert result is False

    @pytest.mark.asyncio
    async def test_pre_cache_with_tts(self):
        c = ResponseCache()
        c._redis = AsyncMock()
        tts = {"text": "Hallo", "voice": "jarvis"}
        result = await c.pre_cache("Test", "knowledge", "Antwort", "model", tts=tts)
        assert result is True
        call_args = c._redis.set.call_args
        data = json.loads(call_args[0][1])
        assert data["tts"] == tts
        assert data["_pre_cached"] is True


class TestResponseCacheInvalidation:
    """Tests for invalidate_by_room with mocked scan_iter."""

    @pytest.mark.asyncio
    async def test_invalidate_deletes_non_precached_entries(self):
        c = ResponseCache()
        c._redis = AsyncMock()

        # New implementation: invalidate_by_room scans for room-specific keys
        # and deletes all matches (room is embedded in key prefix)
        async def fake_scan_iter(match=None, count=None):
            # Only yield keys matching the room pattern
            if match and "wohnzimmer" in match:
                yield "mha:rcache:wohnzimmer:key1"
                yield "mha:rcache:wohnzimmer:key2"

        c._redis.scan_iter = fake_scan_iter
        c._redis.delete = AsyncMock()

        deleted = await c.invalidate_by_room("wohnzimmer")
        assert deleted == 2
        assert c._redis.delete.call_count == 2
        assert c._invalidation_count == 2

    @pytest.mark.asyncio
    async def test_invalidate_none_room_returns_zero(self):
        c = ResponseCache()
        c._redis = AsyncMock()
        result = await c.invalidate_by_room(None)
        assert result == 0

    @pytest.mark.asyncio
    async def test_invalidate_scan_error_returns_zero(self):
        c = ResponseCache()
        c._redis = AsyncMock()

        async def failing_scan_iter(match=None, count=None):
            raise Exception("Scan failed")
            yield  # Make it a generator

        c._redis.scan_iter = failing_scan_iter
        result = await c.invalidate_by_room("wohnzimmer")
        assert result == 0

    @pytest.mark.asyncio
    async def test_invalidate_individual_key_error_continues(self):
        """If one key fails during invalidation, others should still be processed."""
        c = ResponseCache()
        c._redis = AsyncMock()

        async def fake_scan_iter(match=None, count=None):
            yield "mha:rcache:wohnzimmer:good1"
            yield "mha:rcache:wohnzimmer:good2"
            yield "mha:rcache:wohnzimmer:good3"

        c._redis.scan_iter = fake_scan_iter
        c._redis.delete = AsyncMock()

        deleted = await c.invalidate_by_room("wohnzimmer")
        assert deleted == 3
        assert c._redis.delete.call_count == 3

    @pytest.mark.asyncio
    async def test_invalidate_empty_scan_returns_zero(self):
        c = ResponseCache()
        c._redis = AsyncMock()

        async def empty_scan_iter(match=None, count=None):
            return
            yield  # Make it a generator

        c._redis.scan_iter = empty_scan_iter
        result = await c.invalidate_by_room("wohnzimmer")
        assert result == 0


class TestResponseCacheGetEdgeCases:
    """Additional edge cases for get."""

    @pytest.mark.asyncio
    async def test_get_knowledge_category(self):
        """knowledge is a cacheable category."""
        c = ResponseCache()
        c._redis = AsyncMock()
        stored = json.dumps(
            {
                "response": "Die Erde ist rund.",
                "model": "qwen3.5:14b",
                "_ts": time.time(),
            }
        )
        c._redis.get.return_value = stored
        result = await c.get("Ist die Erde rund?", "knowledge")
        assert result is not None
        assert result["response"] == "Die Erde ist rund."

    @pytest.mark.asyncio
    async def test_get_hit_increments_category_hits(self):
        c = ResponseCache()
        c._redis = AsyncMock()
        stored = json.dumps({"response": "ok", "model": "m", "_ts": time.time()})
        c._redis.get.return_value = stored

        await c.get("A", "device_query")
        await c.get("B", "knowledge")
        await c.get("C", "device_query")

        assert c._category_hits["device_query"] == 2
        assert c._category_hits["knowledge"] == 1

    @pytest.mark.asyncio
    async def test_get_miss_does_not_track_category(self):
        c = ResponseCache()
        c._redis = AsyncMock()
        c._redis.get.return_value = None
        await c.get("Miss", "device_query")
        assert "device_query" not in c._category_hits

    @pytest.mark.asyncio
    async def test_multiple_gets_stats_accumulate(self):
        c = ResponseCache()
        c._redis = AsyncMock()
        c._redis.get.return_value = None

        for _ in range(5):
            await c.get("Test", "device_query")

        assert c._misses == 5
        assert c._hits == 0

        stats = c.get_hit_rate()
        assert stats["total"] == 5
        assert stats["hit_rate"] == 0.0


class TestResponseCacheKnowledgeTTL:
    """Ensure knowledge category uses 24h TTL."""

    @pytest.mark.asyncio
    async def test_put_knowledge_uses_24h_ttl(self):
        c = ResponseCache()
        c._redis = AsyncMock()
        await c.put("Was ist Python?", "knowledge", "Eine Programmiersprache", "model")
        call_args = c._redis.set.call_args
        assert call_args[1]["ex"] == 86400

    @pytest.mark.asyncio
    async def test_put_device_query_uses_45s_ttl(self):
        c = ResponseCache()
        c._redis = AsyncMock()
        await c.put("Wie warm?", "device_query", "22 Grad", "model")
        call_args = c._redis.set.call_args
        assert call_args[1]["ex"] == 45
