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
        stored = json.dumps({
            "response": "Es sind 22 Grad.",
            "model": "qwen3.5:9b",
            "_ts": time.time(),
        })
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
        await cache.put("Wie warm?", "device_query", "22 Grad", "qwen3.5:9b",
                        room="wohnzimmer", tts=tts)
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

        cache._redis.get.return_value = json.dumps({
            "response": "cached", "model": "m", "_ts": time.time(),
        })
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
        cache._redis.get.return_value = json.dumps({
            "response": "cached", "model": "m", "_ts": time.time(),
        })
        await cache.get("Test", "device_query")
        assert cache._category_hits.get("device_query") == 1
