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


# ── initialize ───────────────────────────────────────────

class TestInitialize:
    """Tests fuer initialize()."""

    @pytest.mark.asyncio
    async def test_initialize_with_redis(self, redis_mock, ollama_mock):
        r = SelfReport()
        await r.initialize(redis_mock, ollama_mock)
        assert r.redis is redis_mock
        assert r.ollama is ollama_mock
        assert r.enabled is True

    @pytest.mark.asyncio
    async def test_initialize_without_redis(self, ollama_mock):
        r = SelfReport()
        await r.initialize(None, ollama_mock)
        assert r.enabled is False


# ── rate limit Redis recovery ────────────────────────────

class TestRateLimitRedisRecovery:
    """Tests fuer rate limit Redis recovery path."""

    @pytest.mark.asyncio
    async def test_rate_limit_recovers_from_redis(self, report):
        report._last_report_day = ""
        report.redis.get = AsyncMock(side_effect=[
            # First call: recover last day from Redis
            b"2025-01-15",
            # Second call: get_latest_report -> cached
            json.dumps({"summary": "cached report", "data": {}, "generated_at": "2025-01-15T10:00:00"}),
        ])
        # Simulate today being 2025-01-15
        from unittest.mock import patch as _patch
        with _patch("assistant.self_report.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "2025-01-15"
            mock_dt.now.return_value.isoformat.return_value = "2025-01-15T10:00:00"
            result = await report.generate_report()
        assert result["summary"] == "cached report"

    @pytest.mark.asyncio
    async def test_rate_limit_redis_recovery_exception(self, report):
        """Redis exception during day recovery should not crash."""
        report._last_report_day = ""
        report.redis.get = AsyncMock(side_effect=[
            RuntimeError("Redis down"),  # recovery fails
            None,  # get_latest_report returns None
        ])
        report.ollama.generate = AsyncMock(return_value="Fresh report text here.")
        result = await report.generate_report()
        assert "summary" in result


# ── data collection from subsystems ──────────────────────

class TestDataCollection:
    """Tests fuer subsystem data collection paths."""

    @pytest.mark.asyncio
    async def test_feedback_data_collection(self, report):
        feedback_tracker = MagicMock()
        feedback_tracker.get_all_scores = AsyncMock(return_value={"weather": 0.8})
        report.ollama.generate = AsyncMock(return_value="Report with feedback data.")
        result = await report.generate_report(feedback_tracker=feedback_tracker)
        assert result["data"]["feedback"] == {"weather": 0.8}

    @pytest.mark.asyncio
    async def test_learning_observer_data_collection(self, report):
        observer = MagicMock()
        observer.get_learning_report = AsyncMock(return_value={"patterns": 5})
        report.ollama.generate = AsyncMock(return_value="Report with learning data.")
        result = await report.generate_report(learning_observer=observer)
        assert result["data"]["learning"] == {"patterns": 5}

    @pytest.mark.asyncio
    async def test_response_quality_data_collection(self, report):
        quality = MagicMock()
        quality.get_stats = AsyncMock(return_value={"device_command": {"score": 0.9}})
        report.ollama.generate = AsyncMock(return_value="Report with quality data.")
        result = await report.generate_report(response_quality=quality)
        assert "response_quality" in result["data"]

    @pytest.mark.asyncio
    async def test_error_patterns_data_collection(self, report):
        errors = MagicMock()
        errors.get_stats = AsyncMock(return_value={"last_24h": 3})
        report.ollama.generate = AsyncMock(return_value="Report with error data.")
        result = await report.generate_report(error_patterns=errors)
        assert result["data"]["errors"]["last_24h"] == 3

    @pytest.mark.asyncio
    async def test_self_optimization_data(self, report):
        opt = MagicMock()
        opt.generate_weekly_summary = AsyncMock(return_value={"proposals": 2})
        report.ollama.generate = AsyncMock(return_value="Report with opt data.")
        result = await report.generate_report(self_optimization=opt)
        assert result["data"]["self_optimization"] == {"proposals": 2}

    @pytest.mark.asyncio
    async def test_subsystem_exception_handled(self, report):
        """Exception in subsystem data collection should be caught."""
        outcome_tracker = MagicMock()
        outcome_tracker.get_stats = AsyncMock(side_effect=RuntimeError("boom"))
        report.ollama.generate = AsyncMock(return_value="Report despite errors.")
        result = await report.generate_report(outcome_tracker=outcome_tracker)
        assert "outcomes" not in result.get("data", {})

    @pytest.mark.asyncio
    async def test_self_optimization_exception_handled(self, report):
        opt = MagicMock()
        opt.generate_weekly_summary = AsyncMock(side_effect=RuntimeError("opt fail"))
        report.ollama.generate = AsyncMock(return_value="Report ok.")
        result = await report.generate_report(self_optimization=opt)
        assert "self_optimization" not in result.get("data", {})


# ── _generate_summary ────────────────────────────────────

class TestGenerateSummary:
    """Tests fuer _generate_summary() LLM call."""

    @pytest.mark.asyncio
    async def test_empty_data_returns_empty(self, report):
        result = await report._generate_summary({})
        assert result == ""

    @pytest.mark.asyncio
    async def test_no_ollama_returns_empty(self, report):
        report.ollama = None
        result = await report._generate_summary({"outcomes": {"set_light": {"score": 0.8, "total": 10}}})
        assert result == ""

    @pytest.mark.asyncio
    async def test_successful_llm_summary(self, report):
        report.ollama.generate = AsyncMock(return_value="Diese Woche war super. Score 80%.")
        data = {"outcomes": {"set_light": {"score": 0.8, "total": 10}}}
        result = await report._generate_summary(data)
        assert "Score 80%" in result

    @pytest.mark.asyncio
    async def test_llm_short_response_returns_empty(self, report):
        report.ollama.generate = AsyncMock(return_value="OK")
        data = {"outcomes": {"set_light": {"score": 0.8, "total": 10}}}
        result = await report._generate_summary(data)
        assert result == ""

    @pytest.mark.asyncio
    async def test_llm_exception_returns_empty(self, report):
        report.ollama.generate = AsyncMock(side_effect=RuntimeError("LLM down"))
        data = {"outcomes": {"set_light": {"score": 0.8, "total": 10}}}
        result = await report._generate_summary(data)
        assert result == ""

    @pytest.mark.asyncio
    async def test_summary_with_corrections(self, report):
        report.ollama.generate = AsyncMock(return_value="Korrekturen wurden analysiert. Alles gut.")
        data = {"corrections": {"total_corrections": 5, "active_rules": 2}}
        result = await report._generate_summary(data)
        assert len(result) > 20

    @pytest.mark.asyncio
    async def test_summary_with_quality_data(self, report):
        report.ollama.generate = AsyncMock(return_value="Qualitaet war gut diese Woche insgesamt.")
        data = {"response_quality": {"device_command": {"score": 0.9}}}
        result = await report._generate_summary(data)
        assert len(result) > 20

    @pytest.mark.asyncio
    async def test_summary_with_errors(self, report):
        report.ollama.generate = AsyncMock(return_value="Fehler waren minimal diese Woche ja.")
        data = {"errors": {"last_24h": 2}}
        result = await report._generate_summary(data)
        assert len(result) > 20

    @pytest.mark.asyncio
    async def test_summary_with_feedback(self, report):
        report.ollama.generate = AsyncMock(return_value="Feedback war gemischt diese Woche, ja.")
        data = {"feedback": {"weather": 0.9, "bad_topic": 0.1, "neutral": 0.5}}
        result = await report._generate_summary(data)
        assert len(result) > 20
