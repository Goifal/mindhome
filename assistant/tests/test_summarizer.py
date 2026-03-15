"""
Tests fuer DailySummarizer - Hierarchische Zusammenfassungen und Suche.
"""

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
    with patch("assistant.summarizer.yaml_config", SUMMARIZER_CONFIG), \
         patch("assistant.summarizer.settings", mock_settings), \
         patch("assistant.config.settings", mock_settings):
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
    with patch("assistant.summarizer.yaml_config", SUMMARIZER_CONFIG), \
         patch("assistant.summarizer.settings", mock_settings), \
         patch("assistant.config.settings", mock_settings):
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
        with patch("assistant.summarizer.yaml_config", {}), \
             patch("assistant.summarizer.settings", mock_settings), \
             patch("assistant.config.settings", mock_settings):
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
        redis_mock.scan = AsyncMock(return_value=(
            0,
            [
                "mha:summary:daily:2025-06-10",
                "mha:summary:daily:2025-06-12",
                "mha:summary:daily:2025-06-11",
            ],
        ))
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
        self, summarizer, redis_mock, ollama_mock,
    ):
        summarizer.redis = redis_mock
        # No existing summary
        redis_mock.get = AsyncMock(return_value=None)

        # Conversations from Redis fallback
        conv = json.dumps({
            "role": "user",
            "content": "Wie ist das Wetter?",
            "timestamp": "2025-06-15T10:00:00",
        })
        redis_mock.lrange = AsyncMock(return_value=[conv])

        ollama_mock.chat = AsyncMock(return_value={
            "message": {"content": "  Zusammenfassung des Tages.  "},
        })

        result = await summarizer.summarize_day("2025-06-15")
        assert result == "Zusammenfassung des Tages."
        ollama_mock.chat.assert_called_once()
        redis_mock.setex.assert_called()

    @pytest.mark.asyncio
    async def test_uses_memory_manager_when_available(
        self, summarizer_with_memory, redis_mock, ollama_mock,
    ):
        s = summarizer_with_memory
        s.redis = redis_mock
        redis_mock.get = AsyncMock(return_value=None)

        s.memory.get_conversations_for_date = AsyncMock(return_value=[
            {"role": "user", "content": "Test", "timestamp": "2025-06-15T10:00:00"},
        ])
        ollama_mock.chat = AsyncMock(return_value={
            "message": {"content": "Memory-based summary"},
        })

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
    @pytest.mark.parametrize("summary_type,prefix", [
        (DAILY, "daily"),
        (WEEKLY, "weekly"),
        (MONTHLY, "monthly"),
    ])
    async def test_key_format_per_type(self, summarizer, redis_mock, summary_type, prefix):
        summarizer.redis = redis_mock
        redis_mock.get = AsyncMock(return_value=None)
        await summarizer._get_summary("2025-06", summary_type)
        redis_mock.get.assert_called_with(f"mha:summary:{prefix}:2025-06")
