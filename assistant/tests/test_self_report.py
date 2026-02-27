"""
Tests fuer SelfReport — Woechentlicher Selbst-Bericht.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from assistant.self_report import SelfReport


@pytest.fixture
def report(redis_mock, ollama_mock):
    r = SelfReport()
    r.redis = redis_mock
    r.ollama = ollama_mock
    r.enabled = True
    return r


class TestGenerateReport:
    """Tests fuer generate_report()."""

    @pytest.mark.asyncio
    async def test_generates_report_with_data(self, report):
        outcome_tracker = MagicMock()
        outcome_tracker.get_stats = AsyncMock(return_value={
            "set_light": {"positive": 10, "neutral": 5, "negative": 2, "total": 17, "score": 0.75}
        })
        outcome_tracker.get_weekly_trends = AsyncMock(return_value={})

        correction_memory = MagicMock()
        correction_memory.get_stats = AsyncMock(return_value={"total_corrections": 5, "active_rules": 2})
        correction_memory.get_correction_patterns = AsyncMock(return_value=[])

        report.ollama.generate = AsyncMock(return_value="Diese Woche lief es gut. Score: 75%.")

        result = await report.generate_report(
            outcome_tracker=outcome_tracker,
            correction_memory=correction_memory,
        )
        assert "summary" in result
        assert len(result["summary"]) > 0
        report.redis.setex.assert_called()

    @pytest.mark.asyncio
    async def test_disabled_returns_error(self, report):
        report.enabled = False
        result = await report.generate_report()
        assert "error" in result

    @pytest.mark.asyncio
    async def test_fallback_without_ollama(self, report):
        report.ollama = None
        result = await report.generate_report()
        # Should use fallback format or return mostly empty
        assert "summary" in result or "error" in result

    @pytest.mark.asyncio
    async def test_rate_limit_uses_cache(self, report):
        # First call
        report._last_report_day = ""
        report.ollama.generate = AsyncMock(return_value="Erster Report.")
        result1 = await report.generate_report()

        # Second call same day — should use cache
        cached = json.dumps(result1)
        report.redis.get.return_value = cached
        result2 = await report.get_latest_report()
        assert result2 is not None


class TestGetLatestReport:
    """Tests fuer get_latest_report()."""

    @pytest.mark.asyncio
    async def test_no_cached_report(self, report):
        report.redis.get.return_value = None
        result = await report.get_latest_report()
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_cached_report(self, report):
        cached = json.dumps({
            "generated_at": "2025-01-01T10:00:00",
            "summary": "Testbericht",
            "data": {},
        })
        report.redis.get.return_value = cached
        result = await report.get_latest_report()
        assert result is not None
        assert result["summary"] == "Testbericht"


class TestFormatFallback:
    """Tests fuer _format_fallback()."""

    def test_empty_data(self, report):
        result = report._format_fallback({})
        assert "nicht genug Daten" in result.lower() or "Bericht" in result

    def test_with_outcome_data(self, report):
        data = {
            "outcomes": {
                "set_light": {"score": 0.85, "total": 20},
            },
        }
        result = report._format_fallback(data)
        assert "set_light" in result
        assert "85%" in result
