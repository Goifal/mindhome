"""
Tests fuer DailySummarizer - Hierarchische Zusammenfassungen und Suche.
"""

import asyncio
import json
import pytest
from datetime import datetime, timedelta
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
def summarizer(ollama_mock):
    """DailySummarizer with mocked yaml_config, ollama, and no memory."""
    mock_settings = MagicMock()
    mock_settings.model_deep = "qwen3.5:27b"
    mock_settings.model_smart = "test-model"
    mock_settings.model_fast = "qwen3.5:7b"
    with (
        patch("assistant.summarizer.yaml_config", SUMMARIZER_CONFIG),
        patch("assistant.summarizer.settings", mock_settings),
        patch("assistant.config.settings", mock_settings),
    ):
        s = DailySummarizer(ollama_mock, memory=None)
    return s


@pytest.fixture
def summarizer_with_memory(ollama_mock):
    """DailySummarizer with a mock memory manager."""
    mock_settings = MagicMock()
    mock_settings.model_deep = "qwen3.5:27b"
    mock_settings.model_smart = "test-model"
    mock_settings.model_fast = "qwen3.5:7b"
    memory = MagicMock()
    memory.get_conversations_for_date = AsyncMock(return_value=[])
    with (
        patch("assistant.summarizer.yaml_config", SUMMARIZER_CONFIG),
        patch("assistant.summarizer.settings", mock_settings),
        patch("assistant.config.settings", mock_settings),
    ):
        s = DailySummarizer(ollama_mock, memory=memory)
    return s


# ============================================================
# Constructor / Config Tests
# ============================================================


class TestSummarizerInit:
    def test_default_config_values(self, ollama_mock):
        mock_settings = MagicMock()
        mock_settings.model_deep = "fallback-model"
        mock_settings.model_smart = "fallback-model"
        mock_settings.model_fast = "fallback-fast"
        with (
            patch("assistant.summarizer.yaml_config", {}),
            patch("assistant.summarizer.settings", mock_settings),
            patch("assistant.config.settings", mock_settings),
        ):
            s = DailySummarizer(ollama_mock)
        assert s.run_hour == 3
        assert s.run_minute == 0
        assert s.model == "fallback-model"
        assert s.max_tokens_daily == 512

    def test_custom_config(self, summarizer):
        assert summarizer.run_hour == 3
        assert summarizer.model == "test-model"
        assert summarizer.max_tokens_daily == 512
        assert summarizer.max_tokens_weekly == 384
        assert summarizer.max_tokens_monthly == 512


# ============================================================
# _get_system_prompt Tests
# ============================================================


class TestGetSystemPrompt:
    def test_returns_nonempty_string(self, summarizer):
        prompt = summarizer._get_system_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 50

    def test_contains_key_instructions(self, summarizer):
        prompt = summarizer._get_system_prompt()
        assert "Deutsch" in prompt
        assert "Zusammenfassung" in prompt


# ============================================================
# _build_daily_prompt Tests
# ============================================================


class TestBuildDailyPrompt:
    def test_includes_date(self, summarizer):
        prompt = summarizer._build_daily_prompt("2025-06-15", [])
        assert "2025-06-15" in prompt

    def test_includes_conversations(self, summarizer):
        convs = [
            {"role": "user", "content": "Hallo", "timestamp": "2025-06-15T10:00:00"},
            {"role": "assistant", "content": "Hi!", "timestamp": "2025-06-15T10:01:00"},
        ]
        prompt = summarizer._build_daily_prompt("2025-06-15", convs)
        assert "Hallo" in prompt
        assert "Hi!" in prompt
        assert "User" in prompt
        assert "Assistant" in prompt

    def test_max_words_instruction(self, summarizer):
        prompt = summarizer._build_daily_prompt("2025-06-15", [])
        assert "200" in prompt


# ============================================================
# _build_weekly_prompt Tests
# ============================================================


class TestBuildWeeklyPrompt:
    def test_includes_week_identifier(self, summarizer):
        prompt = summarizer._build_weekly_prompt("2025-W25", ["day 1 summary"])
        assert "2025-W25" in prompt

    def test_includes_daily_summaries(self, summarizer):
        summaries = ["[2025-06-09]: Monday stuff", "[2025-06-10]: Tuesday stuff"]
        prompt = summarizer._build_weekly_prompt("2025-W25", summaries)
        assert "Monday stuff" in prompt
        assert "Tuesday stuff" in prompt

    def test_max_words_instruction(self, summarizer):
        prompt = summarizer._build_weekly_prompt("2025-W25", [])
        assert "150" in prompt


# ============================================================
# _build_monthly_prompt Tests
# ============================================================


class TestBuildMonthlyPrompt:
    def test_includes_month(self, summarizer):
        prompt = summarizer._build_monthly_prompt("2025-06", [])
        assert "2025-06" in prompt

    def test_includes_summaries(self, summarizer):
        summaries = ["[2025-06-01]: Day one"]
        prompt = summarizer._build_monthly_prompt("2025-06", summaries)
        assert "Day one" in prompt

    def test_max_words_instruction(self, summarizer):
        prompt = summarizer._build_monthly_prompt("2025-06", [])
        assert "200" in prompt


# ============================================================
# search_summaries Tests
# ============================================================


class TestSearchSummaries:
    @pytest.mark.asyncio
    async def test_no_chroma_returns_empty(self, summarizer):
        summarizer.chroma_collection = None
        result = await summarizer.search_summaries("test query")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_formatted_results(self, summarizer, chroma_mock):
        summarizer.chroma_collection = chroma_mock
        chroma_mock.query.return_value = {
            "documents": [["Summary about winter heating costs"]],
            "metadatas": [[{"date": "2025-01", "type": "monthly"}]],
            "distances": [[0.15]],
        }

        results = await summarizer.search_summaries("Winter Heizkosten", limit=3)
        assert len(results) == 1
        assert results[0]["content"] == "Summary about winter heating costs"
        assert results[0]["date"] == "2025-01"
        assert results[0]["summary_type"] == "monthly"
        assert results[0]["relevance"] == 0.15

        chroma_mock.query.assert_called_once_with(
            query_texts=["Winter Heizkosten"],
            n_results=3,
            where={"type": {"$in": [DAILY, WEEKLY, MONTHLY]}},
        )

    @pytest.mark.asyncio
    async def test_handles_empty_results(self, summarizer, chroma_mock):
        summarizer.chroma_collection = chroma_mock
        chroma_mock.query.return_value = {
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }
        results = await summarizer.search_summaries("nonexistent")
        assert results == []

    @pytest.mark.asyncio
    async def test_handles_chroma_exception(self, summarizer, chroma_mock):
        summarizer.chroma_collection = chroma_mock
        chroma_mock.query.side_effect = Exception("ChromaDB error")
        results = await summarizer.search_summaries("test")
        assert results == []


# ============================================================
# get_recent_summaries Tests
# ============================================================


class TestGetRecentSummaries:
    @pytest.mark.asyncio
    async def test_no_redis_returns_empty(self, summarizer):
        summarizer.redis = None
        result = await summarizer.get_recent_summaries()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_summaries_sorted(self, summarizer, redis_mock):
        summarizer.redis = redis_mock
        redis_mock.scan = AsyncMock(
            return_value=(
                0,
                [
                    "mha:summary:daily:2025-06-10",
                    "mha:summary:daily:2025-06-12",
                    "mha:summary:daily:2025-06-11",
                ],
            )
        )
        redis_mock.get = AsyncMock(return_value="Summary content")

        results = await summarizer.get_recent_summaries(limit=3)
        assert len(results) == 3
        # Should be sorted reverse (newest first)
        assert results[0]["date"] == "2025-06-12"
        assert results[1]["date"] == "2025-06-11"
        assert results[2]["date"] == "2025-06-10"

    @pytest.mark.asyncio
    async def test_respects_limit(self, summarizer, redis_mock):
        summarizer.redis = redis_mock
        keys = [f"mha:summary:daily:2025-06-{d:02d}" for d in range(1, 15)]
        redis_mock.scan = AsyncMock(return_value=(0, keys))
        redis_mock.get = AsyncMock(return_value="Content")

        results = await summarizer.get_recent_summaries(limit=5)
        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_handles_redis_exception(self, summarizer, redis_mock):
        summarizer.redis = redis_mock
        redis_mock.scan = AsyncMock(side_effect=Exception("Redis down"))
        results = await summarizer.get_recent_summaries()
        assert results == []


# ============================================================
# summarize_day Tests
# ============================================================


class TestSummarizeDay:
    @pytest.mark.asyncio
    async def test_returns_existing_summary(self, summarizer, redis_mock):
        """If summary already exists in Redis, return it without LLM call."""
        summarizer.redis = redis_mock
        redis_mock.get = AsyncMock(return_value="Existing summary")

        result = await summarizer.summarize_day("2025-06-15")
        assert result == "Existing summary"

    @pytest.mark.asyncio
    async def test_no_conversations_returns_none(self, summarizer, redis_mock):
        summarizer.redis = redis_mock
        redis_mock.get = AsyncMock(return_value=None)
        redis_mock.lrange = AsyncMock(return_value=[])

        result = await summarizer.summarize_day("2025-06-15")
        assert result is None

    @pytest.mark.asyncio
    async def test_generates_summary_from_conversations(
        self,
        summarizer,
        redis_mock,
        ollama_mock,
    ):
        summarizer.redis = redis_mock
        # No existing summary
        redis_mock.get = AsyncMock(return_value=None)

        # Conversations from Redis fallback
        conv = json.dumps(
            {
                "role": "user",
                "content": "Wie ist das Wetter?",
                "timestamp": "2025-06-15T10:00:00",
            }
        )
        redis_mock.lrange = AsyncMock(return_value=[conv])

        ollama_mock.chat = AsyncMock(
            return_value={
                "message": {"content": "  Zusammenfassung des Tages.  "},
            }
        )

        result = await summarizer.summarize_day("2025-06-15")
        assert result == "Zusammenfassung des Tages."
        ollama_mock.chat.assert_called_once()
        redis_mock.setex.assert_called()

    @pytest.mark.asyncio
    async def test_uses_memory_manager_when_available(
        self,
        summarizer_with_memory,
        redis_mock,
        ollama_mock,
    ):
        s = summarizer_with_memory
        s.redis = redis_mock
        redis_mock.get = AsyncMock(return_value=None)

        s.memory.get_conversations_for_date = AsyncMock(
            return_value=[
                {"role": "user", "content": "Test", "timestamp": "2025-06-15T10:00:00"},
            ]
        )
        ollama_mock.chat = AsyncMock(
            return_value={
                "message": {"content": "Memory-based summary"},
            }
        )

        result = await s.summarize_day("2025-06-15")
        assert result == "Memory-based summary"
        s.memory.get_conversations_for_date.assert_called_once_with("2025-06-15")


# ============================================================
# _store_summary Tests
# ============================================================


class TestStoreSummary:
    @pytest.mark.asyncio
    async def test_stores_in_redis(self, summarizer, redis_mock):
        summarizer.redis = redis_mock
        summarizer.chroma_collection = None

        await summarizer._store_summary("2025-06-15", DAILY, "Test content")
        redis_mock.setex.assert_called_once_with(
            "mha:summary:daily:2025-06-15", 90 * 86400, "Test content"
        )

    @pytest.mark.asyncio
    async def test_stores_in_chroma(self, summarizer, redis_mock, chroma_mock):
        summarizer.redis = redis_mock
        summarizer.chroma_collection = chroma_mock

        await summarizer._store_summary("2025-06-15", DAILY, "Test content")
        chroma_mock.upsert.assert_called_once()
        call_kwargs = chroma_mock.upsert.call_args
        assert call_kwargs[1]["documents"] == ["Test content"]
        assert call_kwargs[1]["ids"] == ["summary_daily_2025-06-15"]

    @pytest.mark.asyncio
    async def test_no_redis_no_chroma_no_error(self, summarizer):
        summarizer.redis = None
        summarizer.chroma_collection = None
        # Should not raise
        await summarizer._store_summary("2025-06-15", DAILY, "Content")


# ============================================================
# _get_summary Tests
# ============================================================


class TestGetSummary:
    @pytest.mark.asyncio
    async def test_returns_none_without_redis(self, summarizer):
        summarizer.redis = None
        result = await summarizer._get_summary("2025-06-15", DAILY)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_stored_value(self, summarizer, redis_mock):
        summarizer.redis = redis_mock
        redis_mock.get = AsyncMock(return_value="Stored summary")
        result = await summarizer._get_summary("2025-06-15", DAILY)
        assert result == "Stored summary"
        redis_mock.get.assert_called_with("mha:summary:daily:2025-06-15")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "summary_type,prefix",
        [
            (DAILY, "daily"),
            (WEEKLY, "weekly"),
            (MONTHLY, "monthly"),
        ],
    )
    async def test_key_format_per_type(
        self, summarizer, redis_mock, summary_type, prefix
    ):
        summarizer.redis = redis_mock
        redis_mock.get = AsyncMock(return_value=None)
        await summarizer._get_summary("2025-06", summary_type)
        redis_mock.get.assert_called_with(f"mha:summary:{prefix}:2025-06")

    @pytest.mark.asyncio
    async def test_decodes_bytes_value(self, summarizer, redis_mock):
        """Bytes values from Redis are decoded to str."""
        summarizer.redis = redis_mock
        redis_mock.get = AsyncMock(return_value=b"Summary in bytes")
        result = await summarizer._get_summary("2025-06-15", DAILY)
        assert result == "Summary in bytes"


# ============================================================
# summarize_week Tests
# ============================================================


class TestSummarizeWeek:
    @pytest.mark.asyncio
    async def test_returns_existing_weekly_summary(self, summarizer, redis_mock):
        """If weekly summary already exists, return it without LLM call."""
        summarizer.redis = redis_mock
        redis_mock.get = AsyncMock(return_value="Existing weekly summary")

        result = await summarizer.summarize_week("2025-06-15")
        assert result == "Existing weekly summary"

    @pytest.mark.asyncio
    async def test_no_daily_summaries_returns_none(self, summarizer, redis_mock):
        """No daily summaries for the week returns None."""
        summarizer.redis = redis_mock
        redis_mock.get = AsyncMock(return_value=None)

        result = await summarizer.summarize_week("2025-06-15")
        assert result is None

    @pytest.mark.asyncio
    async def test_generates_weekly_summary(self, summarizer, redis_mock, ollama_mock):
        """Generates a weekly summary from daily summaries."""
        summarizer.redis = redis_mock

        call_count = [0]

        async def get_side_effect(key):
            call_count[0] += 1
            # First call checks weekly summary (not existing)
            if "weekly" in key:
                return None
            # Daily summaries: return content for some days
            if "2025-06-12" in key or "2025-06-14" in key:
                return f"Summary for {key}"
            return None

        redis_mock.get = AsyncMock(side_effect=get_side_effect)
        ollama_mock.chat = AsyncMock(
            return_value={
                "message": {"content": "  Weekly summary text  "},
            }
        )

        result = await summarizer.summarize_week("2025-06-15")
        assert result == "Weekly summary text"
        ollama_mock.chat.assert_called_once()
        redis_mock.setex.assert_called()

    @pytest.mark.asyncio
    async def test_default_end_date_uses_yesterday(self, summarizer, redis_mock):
        """When no end_date is provided, defaults to yesterday."""
        summarizer.redis = redis_mock
        redis_mock.get = AsyncMock(return_value=None)

        result = await summarizer.summarize_week()
        assert result is None  # No daily summaries found
        # Verify it was called (checks for weekly key)
        redis_mock.get.assert_called()

    @pytest.mark.asyncio
    async def test_stores_summary_on_success(self, summarizer, redis_mock, ollama_mock):
        """Weekly summary is stored in Redis and ChromaDB when generated."""
        summarizer.redis = redis_mock

        async def get_side_effect(key):
            if "weekly" in key:
                return None
            if "2025-06-10" in key:
                return "Monday summary"
            return None

        redis_mock.get = AsyncMock(side_effect=get_side_effect)
        ollama_mock.chat = AsyncMock(
            return_value={
                "message": {"content": "Weekly result"},
            }
        )

        result = await summarizer.summarize_week("2025-06-15")
        assert result == "Weekly result"
        # setex called for storing weekly summary
        redis_mock.setex.assert_called()


# ============================================================
# summarize_month Tests
# ============================================================


class TestSummarizeMonth:
    @pytest.mark.asyncio
    async def test_returns_existing_monthly_summary(self, summarizer, redis_mock):
        """If monthly summary exists, return it."""
        summarizer.redis = redis_mock
        redis_mock.get = AsyncMock(return_value="Existing monthly summary")

        result = await summarizer.summarize_month("2025-06")
        assert result == "Existing monthly summary"

    @pytest.mark.asyncio
    async def test_no_daily_summaries_returns_none(self, summarizer, redis_mock):
        """No summaries for the month returns None."""
        summarizer.redis = redis_mock
        redis_mock.get = AsyncMock(return_value=None)

        result = await summarizer.summarize_month("2025-02")
        assert result is None

    @pytest.mark.asyncio
    async def test_generates_monthly_summary(self, summarizer, redis_mock, ollama_mock):
        """Generates monthly summary from daily summaries."""
        summarizer.redis = redis_mock

        async def get_side_effect(key):
            if "monthly" in key:
                return None
            if "2025-06-01" in key or "2025-06-15" in key:
                return f"Daily summary for {key}"
            return None

        redis_mock.get = AsyncMock(side_effect=get_side_effect)
        ollama_mock.chat = AsyncMock(
            return_value={
                "message": {"content": "Monthly summary text"},
            }
        )

        result = await summarizer.summarize_month("2025-06")
        assert result == "Monthly summary text"
        ollama_mock.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_default_month_uses_last_month(self, summarizer, redis_mock):
        """When no month is provided, defaults to last month."""
        summarizer.redis = redis_mock
        redis_mock.get = AsyncMock(return_value=None)

        result = await summarizer.summarize_month()
        assert result is None
        redis_mock.get.assert_called()

    @pytest.mark.asyncio
    async def test_handles_february_dates(self, summarizer, redis_mock):
        """February only generates dates up to 28/29."""
        summarizer.redis = redis_mock
        redis_mock.get = AsyncMock(return_value=None)

        result = await summarizer.summarize_month("2025-02")
        assert result is None
        # Should not crash on invalid Feb 30/31 dates

    @pytest.mark.asyncio
    async def test_stores_monthly_summary(self, summarizer, redis_mock, ollama_mock):
        """Monthly summary is stored."""
        summarizer.redis = redis_mock

        async def get_side_effect(key):
            if "monthly" in key:
                return None
            if "2025-01-05" in key:
                return "Day 5 summary"
            return None

        redis_mock.get = AsyncMock(side_effect=get_side_effect)
        ollama_mock.chat = AsyncMock(
            return_value={
                "message": {"content": "January summary"},
            }
        )

        result = await summarizer.summarize_month("2025-01")
        assert result == "January summary"
        redis_mock.setex.assert_called()


# ============================================================
# initialize Tests
# ============================================================


class TestInitialize:
    @pytest.mark.asyncio
    async def test_sets_redis_and_chroma(self, summarizer, redis_mock, chroma_mock):
        """Initialize sets redis and chroma_collection."""
        await summarizer.initialize(redis_mock, chroma_mock)
        assert summarizer.redis is redis_mock
        assert summarizer.chroma_collection is chroma_mock
        assert summarizer._running is True
        assert summarizer._task is not None
        # Clean up
        await summarizer.stop()

    @pytest.mark.asyncio
    async def test_cancels_existing_task(self, summarizer, redis_mock, chroma_mock):
        """If a task is already running, it gets cancelled on re-initialize."""
        # First init
        await summarizer.initialize(redis_mock, chroma_mock)
        first_task = summarizer._task

        # Second init should cancel the first task
        await summarizer.initialize(redis_mock, chroma_mock)
        assert first_task.cancelled()
        # Clean up
        await summarizer.stop()

    @pytest.mark.asyncio
    async def test_initialize_without_existing_task(self, summarizer, redis_mock):
        """Initialize works when no prior task exists."""
        await summarizer.initialize(redis_mock)
        assert summarizer._running is True
        assert summarizer._task is not None
        await summarizer.stop()


# ============================================================
# stop Tests
# ============================================================


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, summarizer, redis_mock):
        """stop() cancels the nightly task."""
        await summarizer.initialize(redis_mock)
        assert summarizer._running is True
        task = summarizer._task

        await summarizer.stop()
        assert summarizer._running is False
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_stop_without_task(self, summarizer):
        """stop() works fine when no task has been started."""
        await summarizer.stop()
        assert summarizer._running is False


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
# _generate_summary Tests
# ============================================================


class TestGenerateSummary:
    @pytest.mark.asyncio
    async def test_returns_stripped_content(self, summarizer, ollama_mock):
        ollama_mock.chat = AsyncMock(
            return_value={
                "message": {"content": "  Summary with spaces  "},
            }
        )
        result = await summarizer._generate_summary("prompt", 512)
        assert result == "Summary with spaces"

    @pytest.mark.asyncio
    async def test_empty_content_returns_none(self, summarizer, ollama_mock):
        ollama_mock.chat = AsyncMock(
            return_value={
                "message": {"content": ""},
            }
        )
        result = await summarizer._generate_summary("prompt", 512)
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_message_returns_none(self, summarizer, ollama_mock):
        ollama_mock.chat = AsyncMock(return_value={})
        result = await summarizer._generate_summary("prompt", 512)
        assert result is None

    @pytest.mark.asyncio
    async def test_exception_returns_none(self, summarizer, ollama_mock):
        ollama_mock.chat = AsyncMock(side_effect=Exception("LLM error"))
        result = await summarizer._generate_summary("prompt", 512)
        assert result is None

    @pytest.mark.asyncio
    async def test_uses_configured_model(self, summarizer, ollama_mock):
        ollama_mock.chat = AsyncMock(
            return_value={
                "message": {"content": "result"},
            }
        )
        await summarizer._generate_summary("prompt", 256)
        call_kwargs = ollama_mock.chat.call_args[1]
        assert call_kwargs["model"] == "test-model"
        assert call_kwargs["max_tokens"] == 256


# ============================================================
# _get_conversations_for_date Tests
# ============================================================


class TestGetConversationsForDate:
    @pytest.mark.asyncio
    async def test_memory_manager_path(self, summarizer_with_memory, redis_mock):
        """Uses MemoryManager when available and returns data."""
        s = summarizer_with_memory
        s.redis = redis_mock
        s.memory.get_conversations_for_date = AsyncMock(
            return_value=[
                {"role": "user", "content": "Hi", "timestamp": "2025-06-15T10:00:00"},
            ]
        )
        result = await s._get_conversations_for_date("2025-06-15")
        assert len(result) == 1
        assert result[0]["content"] == "Hi"

    @pytest.mark.asyncio
    async def test_memory_empty_falls_to_redis(
        self, summarizer_with_memory, redis_mock
    ):
        """When memory returns empty, falls back to Redis."""
        s = summarizer_with_memory
        s.redis = redis_mock
        s.memory.get_conversations_for_date = AsyncMock(return_value=[])

        conv = json.dumps(
            {
                "role": "user",
                "content": "Fallback content",
                "timestamp": "2025-06-15T09:00:00",
            }
        )
        redis_mock.lrange = AsyncMock(return_value=[conv])

        result = await s._get_conversations_for_date("2025-06-15")
        assert len(result) == 1
        assert result[0]["content"] == "Fallback content"

    @pytest.mark.asyncio
    async def test_redis_fallback_filters_by_date(self, summarizer, redis_mock):
        """Redis fallback only returns conversations matching the date."""
        summarizer.redis = redis_mock
        convs = [
            json.dumps(
                {
                    "role": "user",
                    "content": "Right day",
                    "timestamp": "2025-06-15T10:00:00",
                }
            ),
            json.dumps(
                {
                    "role": "user",
                    "content": "Wrong day",
                    "timestamp": "2025-06-14T10:00:00",
                }
            ),
        ]
        redis_mock.lrange = AsyncMock(return_value=convs)

        result = await summarizer._get_conversations_for_date("2025-06-15")
        assert len(result) == 1
        assert result[0]["content"] == "Right day"

    @pytest.mark.asyncio
    async def test_redis_fallback_sorts_by_timestamp(self, summarizer, redis_mock):
        """Redis fallback sorts conversations by timestamp."""
        summarizer.redis = redis_mock
        convs = [
            json.dumps(
                {"role": "user", "content": "Later", "timestamp": "2025-06-15T14:00:00"}
            ),
            json.dumps(
                {
                    "role": "user",
                    "content": "Earlier",
                    "timestamp": "2025-06-15T08:00:00",
                }
            ),
        ]
        redis_mock.lrange = AsyncMock(return_value=convs)

        result = await summarizer._get_conversations_for_date("2025-06-15")
        assert result[0]["content"] == "Earlier"
        assert result[1]["content"] == "Later"

    @pytest.mark.asyncio
    async def test_no_redis_no_memory_returns_empty(self, summarizer):
        """Without Redis and memory, returns empty list."""
        summarizer.redis = None
        summarizer.memory = None
        result = await summarizer._get_conversations_for_date("2025-06-15")
        assert result == []

    @pytest.mark.asyncio
    async def test_handles_invalid_json_entries(self, summarizer, redis_mock):
        """Skips invalid JSON entries in Redis."""
        summarizer.redis = redis_mock
        convs = [
            "not valid json",
            json.dumps(
                {"role": "user", "content": "Valid", "timestamp": "2025-06-15T10:00:00"}
            ),
        ]
        redis_mock.lrange = AsyncMock(return_value=convs)

        result = await summarizer._get_conversations_for_date("2025-06-15")
        assert len(result) == 1
        assert result[0]["content"] == "Valid"

    @pytest.mark.asyncio
    async def test_redis_exception_returns_empty(self, summarizer, redis_mock):
        """Redis exception returns empty list."""
        summarizer.redis = redis_mock
        redis_mock.lrange = AsyncMock(side_effect=Exception("Redis error"))

        result = await summarizer._get_conversations_for_date("2025-06-15")
        assert result == []


# ============================================================
# _store_personality_snapshot Tests
# ============================================================


class TestStorePersonalitySnapshot:
    @pytest.mark.asyncio
    async def test_stores_snapshot_in_redis(self, summarizer, redis_mock):
        """Stores a personality snapshot in Redis."""
        summarizer.redis = redis_mock
        redis_mock.get = AsyncMock(return_value=None)
        redis_mock.lrange = AsyncMock(return_value=["0.6", "0.7", "0.8"])

        await summarizer._store_personality_snapshot()

        # Verify setex was called for snapshot key
        calls = redis_mock.setex.call_args_list
        assert any("mha:personality:snapshot:" in str(c) for c in calls)

    @pytest.mark.asyncio
    async def test_appends_to_existing_monthly_summary(self, summarizer, redis_mock):
        """Appends personality evolution text to existing monthly summary."""
        summarizer.redis = redis_mock
        redis_mock.get = AsyncMock(
            side_effect=lambda key: (
                "50"
                if "total_interactions" in key
                else "40"
                if "positive_reactions" in key
                else "75"
                if "formality" in key
                else "Existing monthly summary"
                if "monthly" in key
                else None
            )
        )
        redis_mock.lrange = AsyncMock(return_value=["0.5", "0.6"])

        await summarizer._store_personality_snapshot()

        # setex called at least twice: once for snapshot, once for updated monthly
        assert redis_mock.setex.call_count >= 2

    @pytest.mark.asyncio
    async def test_handles_bytes_redis_values(self, summarizer, redis_mock):
        """Handles bytes values from Redis correctly."""
        summarizer.redis = redis_mock
        redis_mock.get = AsyncMock(
            side_effect=lambda key: (
                b"100"
                if "total_interactions" in key
                else b"80"
                if "positive_reactions" in key
                else b"70"
                if "formality" in key
                else None
            )
        )
        redis_mock.lrange = AsyncMock(return_value=[b"0.5", b"0.6"])

        await summarizer._store_personality_snapshot()
        redis_mock.setex.assert_called()

    @pytest.mark.asyncio
    async def test_no_redis_returns_early(self, summarizer):
        """Without Redis, returns without error."""
        summarizer.redis = None
        await summarizer._store_personality_snapshot()  # No exception

    @pytest.mark.asyncio
    async def test_exception_caught(self, summarizer, redis_mock):
        """Exceptions are caught and logged."""
        summarizer.redis = redis_mock
        redis_mock.get = AsyncMock(side_effect=Exception("Redis error"))

        await summarizer._store_personality_snapshot()  # No exception raised

    @pytest.mark.asyncio
    async def test_empty_mood_history_uses_default(self, summarizer, redis_mock):
        """Empty mood history defaults to 0.5 avg_mood."""
        summarizer.redis = redis_mock
        redis_mock.get = AsyncMock(return_value="10")
        redis_mock.lrange = AsyncMock(return_value=[])

        await summarizer._store_personality_snapshot()

        # Verify snapshot was stored with default avg_mood
        calls = redis_mock.setex.call_args_list
        for call in calls:
            if "snapshot" in str(call):
                stored_data = json.loads(call[0][2])
                assert stored_data["avg_mood"] == 0.5
                break


# ============================================================
# search_summaries Edge Cases
# ============================================================


class TestSearchSummariesEdgeCases:
    @pytest.mark.asyncio
    async def test_missing_metadatas(self, summarizer, chroma_mock):
        """Handles results with no metadatas."""
        summarizer.chroma_collection = chroma_mock
        chroma_mock.query.return_value = {
            "documents": [["Some summary"]],
            "distances": [[0.3]],
        }

        results = await summarizer.search_summaries("test")
        assert len(results) == 1
        assert results[0]["date"] == ""
        assert results[0]["summary_type"] == ""

    @pytest.mark.asyncio
    async def test_missing_distances(self, summarizer, chroma_mock):
        """Handles results with no distances."""
        summarizer.chroma_collection = chroma_mock
        chroma_mock.query.return_value = {
            "documents": [["Some summary"]],
            "metadatas": [[{"date": "2025-01", "type": "monthly"}]],
        }

        results = await summarizer.search_summaries("test")
        assert len(results) == 1
        assert results[0]["relevance"] == 0


# ============================================================
# get_recent_summaries Edge Cases
# ============================================================


class TestGetRecentSummariesEdgeCases:
    @pytest.mark.asyncio
    async def test_handles_bytes_keys(self, summarizer, redis_mock):
        """Handles bytes keys from Redis scan."""
        summarizer.redis = redis_mock
        redis_mock.scan = AsyncMock(
            return_value=(
                0,
                [b"mha:summary:daily:2025-06-10", b"mha:summary:daily:2025-06-11"],
            )
        )
        redis_mock.get = AsyncMock(return_value=b"Summary bytes content")

        results = await summarizer.get_recent_summaries(limit=5)
        assert len(results) == 2
        assert results[0]["content"] == "Summary bytes content"

    @pytest.mark.asyncio
    async def test_skips_none_content(self, summarizer, redis_mock):
        """Skips keys where content is None."""
        summarizer.redis = redis_mock
        redis_mock.scan = AsyncMock(
            return_value=(
                0,
                ["mha:summary:daily:2025-06-10"],
            )
        )
        redis_mock.get = AsyncMock(return_value=None)

        results = await summarizer.get_recent_summaries()
        assert results == []
