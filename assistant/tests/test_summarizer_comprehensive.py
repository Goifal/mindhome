"""
Comprehensive tests for DailySummarizer — covers summarize_week, summarize_month,
_generate_summary, _get_conversations_for_date, stop, set_notify_callback,
_store_personality_snapshot, and edge cases.

Complements the existing test_summarizer.py which covers init, prompts,
search/get summaries, summarize_day, store/get summary.
"""

import json
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock, AsyncMock

from assistant.summarizer import DailySummarizer, DAILY, WEEKLY, MONTHLY


# ============================================================
# Fixtures
# ============================================================

SUMMARIZER_CONFIG = {
    "summarizer": {
        "run_hour": 3,
        "run_minute": 0,
        "model": "test-model",
        "max_tokens_daily": 512,
        "max_tokens_weekly": 384,
        "max_tokens_monthly": 512,
    },
}


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.model_deep = "qwen3.5:27b"
    s.model_smart = "test-model"
    s.model_fast = "qwen3.5:7b"
    return s


@pytest.fixture
def summarizer(ollama_mock, mock_settings):
    with patch("assistant.summarizer.yaml_config", SUMMARIZER_CONFIG), \
         patch("assistant.summarizer.settings", mock_settings), \
         patch("assistant.config.settings", mock_settings):
        s = DailySummarizer(ollama_mock, memory=None)
    return s


@pytest.fixture
def summarizer_with_redis(summarizer, redis_mock):
    summarizer.redis = redis_mock
    return summarizer


@pytest.fixture
def summarizer_full(summarizer, redis_mock, chroma_mock):
    summarizer.redis = redis_mock
    summarizer.chroma_collection = chroma_mock
    return summarizer


# ============================================================
# _generate_summary Tests
# ============================================================

class TestGenerateSummary:
    @pytest.mark.asyncio
    async def test_generates_summary_successfully(self, summarizer, ollama_mock):
        ollama_mock.chat = AsyncMock(return_value={
            "message": {"content": "  Die Zusammenfassung.  "},
        })
        result = await summarizer._generate_summary("Test prompt", 512)
        assert result == "Die Zusammenfassung."
        ollama_mock.chat.assert_called_once()
        call_kwargs = ollama_mock.chat.call_args[1]
        assert call_kwargs["max_tokens"] == 512
        assert call_kwargs["model"] == "test-model"

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_response(self, summarizer, ollama_mock):
        ollama_mock.chat = AsyncMock(return_value={
            "message": {"content": ""},
        })
        result = await summarizer._generate_summary("Prompt", 512)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_missing_message(self, summarizer, ollama_mock):
        ollama_mock.chat = AsyncMock(return_value={})
        result = await summarizer._generate_summary("Prompt", 512)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self, summarizer, ollama_mock):
        ollama_mock.chat = AsyncMock(side_effect=Exception("LLM down"))
        result = await summarizer._generate_summary("Prompt", 512)
        assert result is None

    @pytest.mark.asyncio
    async def test_uses_system_prompt(self, summarizer, ollama_mock):
        ollama_mock.chat = AsyncMock(return_value={
            "message": {"content": "Summary"},
        })
        await summarizer._generate_summary("User prompt", 256)
        messages = ollama_mock.chat.call_args[1]["messages"]
        assert messages[0]["role"] == "system"
        assert "Deutsch" in messages[0]["content"]
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "User prompt"


# ============================================================
# _get_conversations_for_date Tests
# ============================================================

class TestGetConversationsForDate:
    @pytest.mark.asyncio
    async def test_uses_memory_manager_first(self, summarizer, ollama_mock, mock_settings):
        memory = MagicMock()
        memory.get_conversations_for_date = AsyncMock(return_value=[
            {"role": "user", "content": "Hello", "timestamp": "2025-06-15T10:00:00"},
        ])
        with patch("assistant.summarizer.yaml_config", SUMMARIZER_CONFIG), \
             patch("assistant.summarizer.settings", mock_settings), \
             patch("assistant.config.settings", mock_settings):
            s = DailySummarizer(ollama_mock, memory=memory)

        result = await s._get_conversations_for_date("2025-06-15")
        assert len(result) == 1
        memory.get_conversations_for_date.assert_called_once_with("2025-06-15")

    @pytest.mark.asyncio
    async def test_fallback_to_redis(self, summarizer_with_redis, redis_mock):
        conv1 = json.dumps({"role": "user", "content": "Hi", "timestamp": "2025-06-15T09:00:00"})
        conv2 = json.dumps({"role": "assistant", "content": "Hello", "timestamp": "2025-06-15T09:01:00"})
        conv_other = json.dumps({"role": "user", "content": "Bye", "timestamp": "2025-06-16T10:00:00"})
        redis_mock.lrange = AsyncMock(return_value=[conv1, conv2, conv_other])

        result = await summarizer_with_redis._get_conversations_for_date("2025-06-15")
        assert len(result) == 2
        # Should be sorted by timestamp
        assert result[0]["content"] == "Hi"
        assert result[1]["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_no_redis_no_memory(self, summarizer):
        summarizer.redis = None
        summarizer.memory = None
        result = await summarizer._get_conversations_for_date("2025-06-15")
        assert result == []

    @pytest.mark.asyncio
    async def test_handles_malformed_json(self, summarizer_with_redis, redis_mock):
        valid = json.dumps({"role": "user", "content": "Valid", "timestamp": "2025-06-15T10:00:00"})
        redis_mock.lrange = AsyncMock(return_value=[valid, b"not json", b"{broken"])

        result = await summarizer_with_redis._get_conversations_for_date("2025-06-15")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_redis_error(self, summarizer_with_redis, redis_mock):
        redis_mock.lrange = AsyncMock(side_effect=Exception("Redis error"))
        result = await summarizer_with_redis._get_conversations_for_date("2025-06-15")
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_redis_conversations(self, summarizer_with_redis, redis_mock):
        redis_mock.lrange = AsyncMock(return_value=[])
        result = await summarizer_with_redis._get_conversations_for_date("2025-06-15")
        assert result == []


# ============================================================
# summarize_week Tests
# ============================================================

class TestSummarizeWeek:
    @pytest.mark.asyncio
    async def test_returns_existing_weekly_summary(self, summarizer_with_redis, redis_mock):
        """If weekly summary exists, return it without LLM call."""
        redis_mock.get = AsyncMock(return_value="Existing weekly summary")

        result = await summarizer_with_redis.summarize_week("2025-06-15")
        assert result == "Existing weekly summary"

    @pytest.mark.asyncio
    async def test_no_daily_summaries_returns_none(self, summarizer_with_redis, redis_mock):
        """If no daily summaries exist for the week, return None."""
        redis_mock.get = AsyncMock(return_value=None)

        result = await summarizer_with_redis.summarize_week("2025-06-15")
        assert result is None

    @pytest.mark.asyncio
    async def test_generates_weekly_from_dailies(self, summarizer_with_redis, redis_mock, ollama_mock):
        """Should generate weekly summary from daily summaries."""
        call_count = [0]

        async def mock_get(key):
            call_count[0] += 1
            # First call is for the weekly key itself -> None
            if "weekly" in key or call_count[0] == 1:
                return None
            # Some days have summaries
            if key.endswith("2025-06-10") or key.endswith("2025-06-12"):
                return f"Summary for {key}"
            return None

        redis_mock.get = AsyncMock(side_effect=mock_get)
        ollama_mock.chat = AsyncMock(return_value={
            "message": {"content": "Weekly summary generated."},
        })

        result = await summarizer_with_redis.summarize_week("2025-06-15")
        assert result == "Weekly summary generated."
        redis_mock.setex.assert_called()

    @pytest.mark.asyncio
    async def test_week_uses_default_end_date(self, summarizer_with_redis, redis_mock):
        """Without end_date, should default to yesterday."""
        redis_mock.get = AsyncMock(return_value=None)
        result = await summarizer_with_redis.summarize_week()
        # Should not raise
        assert result is None  # No daily summaries exist


# ============================================================
# summarize_month Tests
# ============================================================

class TestSummarizeMonth:
    @pytest.mark.asyncio
    async def test_returns_existing_monthly_summary(self, summarizer_with_redis, redis_mock):
        redis_mock.get = AsyncMock(return_value="Existing monthly summary")

        result = await summarizer_with_redis.summarize_month("2025-06")
        assert result == "Existing monthly summary"

    @pytest.mark.asyncio
    async def test_no_summaries_returns_none(self, summarizer_with_redis, redis_mock):
        redis_mock.get = AsyncMock(return_value=None)
        result = await summarizer_with_redis.summarize_month("2025-06")
        assert result is None

    @pytest.mark.asyncio
    async def test_generates_monthly_from_dailies(self, summarizer_with_redis, redis_mock, ollama_mock):
        """Should collect daily summaries for the month and generate monthly summary."""
        call_count = [0]

        async def mock_get(key):
            call_count[0] += 1
            # Monthly key check returns None
            if "monthly" in key:
                return None
            # A few daily summaries exist
            if key.endswith("2025-06-05") or key.endswith("2025-06-15"):
                return f"Daily summary for {key}"
            return None

        redis_mock.get = AsyncMock(side_effect=mock_get)
        ollama_mock.chat = AsyncMock(return_value={
            "message": {"content": "Monthly summary: June was productive."},
        })

        result = await summarizer_with_redis.summarize_month("2025-06")
        assert result == "Monthly summary: June was productive."
        redis_mock.setex.assert_called()

    @pytest.mark.asyncio
    async def test_month_defaults_to_last_month(self, summarizer_with_redis, redis_mock):
        """Without month param, should default to last month."""
        redis_mock.get = AsyncMock(return_value=None)
        result = await summarizer_with_redis.summarize_month()
        assert result is None  # No summaries exist

    @pytest.mark.asyncio
    async def test_february_handles_28_days(self, summarizer_with_redis, redis_mock):
        """February (non-leap year) should only check 28 days."""
        redis_mock.get = AsyncMock(return_value=None)
        result = await summarizer_with_redis.summarize_month("2025-02")
        assert result is None  # No error for Feb


# ============================================================
# stop Tests
# ============================================================

class TestStop:
    @pytest.mark.asyncio
    async def test_stop_no_task(self, summarizer):
        summarizer._task = None
        await summarizer.stop()
        assert summarizer._running is False

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, summarizer):
        import asyncio

        async def fake_loop():
            await asyncio.sleep(9999)

        summarizer._running = True
        summarizer._task = asyncio.create_task(fake_loop())

        await summarizer.stop()
        assert summarizer._running is False
        assert summarizer._task.cancelled()


# ============================================================
# set_notify_callback Tests
# ============================================================

class TestSetNotifyCallback:
    def test_sets_callback(self, summarizer):
        callback = AsyncMock()
        summarizer.set_notify_callback(callback)
        assert summarizer._notify_callback is callback

    def test_replaces_existing_callback(self, summarizer):
        cb1 = AsyncMock()
        cb2 = AsyncMock()
        summarizer.set_notify_callback(cb1)
        summarizer.set_notify_callback(cb2)
        assert summarizer._notify_callback is cb2


# ============================================================
# _store_personality_snapshot Tests
# ============================================================

class TestStorePersonalitySnapshot:
    @pytest.mark.asyncio
    async def test_no_redis(self, summarizer):
        summarizer.redis = None
        # Should not raise
        await summarizer._store_personality_snapshot()

    @pytest.mark.asyncio
    async def test_stores_snapshot(self, summarizer_with_redis, redis_mock):
        redis_mock.get = AsyncMock(side_effect=[
            "100",   # total_interactions
            "85",    # positive_reactions
            "75",    # formality
            None,    # get_summary check (for monthly summary integration)
        ])
        redis_mock.lrange = AsyncMock(return_value=["0.6", "0.7", "0.8"])

        await summarizer_with_redis._store_personality_snapshot()

        # Should store snapshot in Redis
        setex_calls = redis_mock.setex.call_args_list
        assert len(setex_calls) >= 1
        # Find the personality snapshot call
        snapshot_call = None
        for c in setex_calls:
            if "personality:snapshot" in str(c):
                snapshot_call = c
                break
        assert snapshot_call is not None

        # Parse the stored JSON
        stored_json = snapshot_call[0][2]
        data = json.loads(stored_json)
        assert data["total_interactions"] == 100
        assert data["positive_reactions"] == 85
        assert data["acceptance_rate"] == 0.85
        assert data["formality_score"] == 75
        assert 0.6 <= data["avg_mood"] <= 0.8

    @pytest.mark.asyncio
    async def test_appends_to_existing_monthly_summary(
        self, summarizer_full, redis_mock, chroma_mock,
    ):
        """If monthly summary exists, snapshot data should be appended."""
        call_idx = [0]
        responses = [
            "50",                           # total_interactions
            "40",                           # positive_reactions
            "80",                           # formality
            "Existing monthly summary",     # existing monthly summary (_get_summary)
        ]

        async def mock_get(key):
            idx = call_idx[0]
            call_idx[0] += 1
            if idx < len(responses):
                return responses[idx]
            return None

        redis_mock.get = AsyncMock(side_effect=mock_get)
        redis_mock.lrange = AsyncMock(return_value=["0.5"])

        await summarizer_full._store_personality_snapshot()

        # Should have stored updated monthly summary with personality data
        # Check that setex was called with content containing "Personality-Evolution"
        setex_calls = redis_mock.setex.call_args_list
        found_updated = False
        for c in setex_calls:
            stored = str(c)
            if "Personality-Evolution" in stored and "Existing monthly summary" in stored:
                found_updated = True
                break
        assert found_updated

    @pytest.mark.asyncio
    async def test_handles_redis_errors(self, summarizer_with_redis, redis_mock):
        redis_mock.get = AsyncMock(side_effect=Exception("Redis connection lost"))
        # Should not raise
        await summarizer_with_redis._store_personality_snapshot()


# ============================================================
# _store_summary edge cases
# ============================================================

class TestStoreSummaryEdgeCases:
    @pytest.mark.asyncio
    async def test_stores_weekly_type_correctly(self, summarizer_full, redis_mock, chroma_mock):
        await summarizer_full._store_summary("2025-W25", WEEKLY, "Week summary")
        redis_mock.setex.assert_called_once_with(
            "mha:summary:weekly:2025-W25", 90 * 86400, "Week summary"
        )
        chroma_mock.upsert.assert_called_once()
        upsert_kwargs = chroma_mock.upsert.call_args[1]
        assert upsert_kwargs["ids"] == ["summary_weekly_2025-W25"]
        meta = upsert_kwargs["metadatas"][0]
        assert meta["type"] == WEEKLY

    @pytest.mark.asyncio
    async def test_stores_monthly_type(self, summarizer_full, redis_mock, chroma_mock):
        await summarizer_full._store_summary("2025-06", MONTHLY, "Month summary")
        redis_mock.setex.assert_called_once_with(
            "mha:summary:monthly:2025-06", 90 * 86400, "Month summary"
        )

    @pytest.mark.asyncio
    async def test_chroma_error_does_not_affect_redis(self, summarizer_full, redis_mock, chroma_mock):
        """ChromaDB failure should not prevent Redis storage."""
        chroma_mock.upsert.side_effect = Exception("ChromaDB error")
        await summarizer_full._store_summary("2025-06-15", DAILY, "Content")
        redis_mock.setex.assert_called_once()  # Redis should still work


# ============================================================
# summarize_day edge cases
# ============================================================

class TestSummarizeDayEdgeCases:
    @pytest.mark.asyncio
    async def test_llm_returns_none(self, summarizer_with_redis, redis_mock, ollama_mock):
        """If LLM fails, summarize_day should return None."""
        redis_mock.get = AsyncMock(return_value=None)
        conv = json.dumps({"role": "user", "content": "Test", "timestamp": "2025-06-15T10:00:00"})
        redis_mock.lrange = AsyncMock(return_value=[conv])
        ollama_mock.chat = AsyncMock(side_effect=Exception("LLM error"))

        result = await summarizer_with_redis.summarize_day("2025-06-15")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_redis(self, summarizer):
        """Without redis, _get_summary returns None, then _get_conversations_for_date returns []."""
        summarizer.redis = None
        result = await summarizer.summarize_day("2025-06-15")
        assert result is None

    @pytest.mark.asyncio
    async def test_single_message_conversation(self, summarizer_with_redis, redis_mock, ollama_mock):
        """A single user message should still produce a summary."""
        redis_mock.get = AsyncMock(return_value=None)
        conv = json.dumps({"role": "user", "content": "Guten Morgen!", "timestamp": "2025-06-15T08:00:00"})
        redis_mock.lrange = AsyncMock(return_value=[conv])
        ollama_mock.chat = AsyncMock(return_value={
            "message": {"content": "Kurze Begruessung am Morgen."},
        })

        result = await summarizer_with_redis.summarize_day("2025-06-15")
        assert result == "Kurze Begruessung am Morgen."


# ============================================================
# _get_summary edge cases
# ============================================================

class TestGetSummaryEdgeCases:
    @pytest.mark.asyncio
    async def test_handles_bytes_response(self, summarizer_with_redis, redis_mock):
        """Redis may return bytes; should decode them."""
        redis_mock.get = AsyncMock(return_value=b"Bytes summary content")
        result = await summarizer_with_redis._get_summary("2025-06-15", DAILY)
        assert result == "Bytes summary content"

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_key(self, summarizer_with_redis, redis_mock):
        redis_mock.get = AsyncMock(return_value=None)
        result = await summarizer_with_redis._get_summary("2099-01-01", DAILY)
        assert result is None


# ============================================================
# Build prompt edge cases
# ============================================================

class TestBuildPromptEdgeCases:
    def test_daily_prompt_empty_conversations(self, summarizer):
        prompt = summarizer._build_daily_prompt("2025-06-15", [])
        assert "2025-06-15" in prompt
        assert "200" in prompt  # Max words

    def test_daily_prompt_missing_fields(self, summarizer):
        """Conversations with missing fields should not crash."""
        convs = [
            {"role": "user"},  # no content, no timestamp
            {},  # completely empty
        ]
        prompt = summarizer._build_daily_prompt("2025-06-15", convs)
        assert "2025-06-15" in prompt

    def test_weekly_prompt_empty_summaries(self, summarizer):
        prompt = summarizer._build_weekly_prompt("2025-W25", [])
        assert "2025-W25" in prompt
        assert "150" in prompt

    def test_monthly_prompt_empty_summaries(self, summarizer):
        prompt = summarizer._build_monthly_prompt("2025-06", [])
        assert "2025-06" in prompt
        assert "200" in prompt

    def test_daily_prompt_many_conversations(self, summarizer):
        """Should handle a large number of conversations."""
        convs = [
            {"role": "user", "content": f"Message {i}", "timestamp": f"2025-06-15T{10+i%12}:00:00"}
            for i in range(50)
        ]
        prompt = summarizer._build_daily_prompt("2025-06-15", convs)
        assert "Message 0" in prompt
        assert "Message 49" in prompt
