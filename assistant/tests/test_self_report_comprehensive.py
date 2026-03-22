"""
Comprehensive tests for SelfReport — covering edge cases, data formatting,
LLM prompt construction, Redis persistence, and rate limiting.
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.self_report import SelfReport


# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def report(redis_mock, ollama_mock):
    r = SelfReport()
    r.redis = redis_mock
    r.ollama = ollama_mock
    r.enabled = True
    r._last_report_day = ""
    return r


# ── Report structure and metadata ────────────────────────────


class TestReportStructure:
    """Verify the generated report dict has the correct shape."""

    @pytest.mark.asyncio
    async def test_report_contains_generated_at_iso(self, report):
        """generated_at should be a valid UTC ISO timestamp."""
        report.ollama.generate = AsyncMock(return_value="Ein guter Bericht hier ja.")
        outcome = MagicMock()
        outcome.get_stats = AsyncMock(return_value={"x": {"score": 0.5, "total": 1}})
        outcome.get_weekly_trends = AsyncMock(return_value={})

        result = await report.generate_report(outcome_tracker=outcome)
        ts = result["generated_at"]
        # Should be parseable as ISO format
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None or "+" in ts or ts.endswith("Z")

    @pytest.mark.asyncio
    async def test_report_data_key_is_dict(self, report):
        """data key should always be a dict."""
        report.ollama.generate = AsyncMock(return_value="Report summary text here ok.")
        feedback = MagicMock()
        feedback.get_all_scores = AsyncMock(return_value={"test": 0.5})
        result = await report.generate_report(feedback_tracker=feedback)
        assert isinstance(result["data"], dict)

    @pytest.mark.asyncio
    async def test_report_no_subsystems_uses_fallback(self, report):
        """With no subsystem data and no LLM, fallback summary is used."""
        report.ollama = None
        result = await report.generate_report()
        assert "summary" in result
        # Fallback should mention not enough data
        assert (
            "nicht genug Daten" in result["summary"].lower()
            or len(result["summary"]) > 0
        )


# ── Redis persistence ────────────────────────────────────────


class TestRedisPersistence:
    """Verify that reports are persisted correctly to Redis."""

    @pytest.mark.asyncio
    async def test_report_stored_with_14_day_ttl(self, report):
        """Latest report is stored with 14-day TTL."""
        report.ollama.generate = AsyncMock(
            return_value="Report content that is long enough."
        )
        outcome = MagicMock()
        outcome.get_stats = AsyncMock(return_value={"a": {"score": 0.7, "total": 5}})
        outcome.get_weekly_trends = AsyncMock(return_value={})

        await report.generate_report(outcome_tracker=outcome)

        # Check setex was called with 14 * 86400 seconds
        setex_calls = report.redis.setex.call_args_list
        latest_call = [c for c in setex_calls if c[0][0] == "mha:self_report:latest"]
        assert len(latest_call) > 0
        assert latest_call[0][0][1] == 14 * 86400

    @pytest.mark.asyncio
    async def test_history_limited_to_12_entries(self, report):
        """History list is trimmed to 12 entries."""
        report.ollama.generate = AsyncMock(
            return_value="History test report with enough content."
        )
        outcome = MagicMock()
        outcome.get_stats = AsyncMock(return_value={"b": {"score": 0.6, "total": 3}})
        outcome.get_weekly_trends = AsyncMock(return_value={})

        await report.generate_report(outcome_tracker=outcome)

        report.redis.ltrim.assert_called_with("mha:self_report:history", 0, 11)

    @pytest.mark.asyncio
    async def test_history_has_365_day_expiry(self, report):
        """History list expires after 365 days."""
        report.ollama.generate = AsyncMock(
            return_value="Expiry test report content here ok."
        )
        outcome = MagicMock()
        outcome.get_stats = AsyncMock(return_value={"c": {"score": 0.9, "total": 1}})
        outcome.get_weekly_trends = AsyncMock(return_value={})

        await report.generate_report(outcome_tracker=outcome)

        report.redis.expire.assert_called_with("mha:self_report:history", 365 * 86400)

    @pytest.mark.asyncio
    async def test_last_day_stored_in_redis(self, report):
        """The current day is stored in Redis for rate-limit recovery."""
        report.ollama.generate = AsyncMock(
            return_value="Day cache test report with content ok."
        )
        outcome = MagicMock()
        outcome.get_stats = AsyncMock(return_value={"d": {"score": 0.5, "total": 2}})
        outcome.get_weekly_trends = AsyncMock(return_value={})

        await report.generate_report(outcome_tracker=outcome)

        day_calls = [
            c
            for c in report.redis.setex.call_args_list
            if c[0][0] == "mha:self_report:last_day"
        ]
        assert len(day_calls) > 0
        assert day_calls[0][0][1] == 86400

    @pytest.mark.asyncio
    async def test_last_day_redis_save_failure_non_fatal(self, report):
        """Exception when saving last_day to Redis should not crash."""
        call_count = 0
        original_setex = report.redis.setex

        async def conditional_setex(key, ttl, value):
            nonlocal call_count
            call_count += 1
            if key == "mha:self_report:last_day":
                raise RuntimeError("Redis write failed")
            return await original_setex(key, ttl, value)

        report.redis.setex = AsyncMock(side_effect=conditional_setex)
        report.ollama.generate = AsyncMock(
            return_value="Report despite Redis issue ok ok."
        )
        outcome = MagicMock()
        outcome.get_stats = AsyncMock(return_value={"e": {"score": 0.4, "total": 1}})
        outcome.get_weekly_trends = AsyncMock(return_value={})

        result = await report.generate_report(outcome_tracker=outcome)
        assert "summary" in result


# ── Rate limiting ─────────────────────────────────────────────


class TestRateLimiting:
    """Tests for the one-report-per-day rate limit."""

    @pytest.mark.asyncio
    async def test_same_day_returns_cached_report(self, report):
        """Calling generate_report twice on the same day returns cached."""
        report.ollama.generate = AsyncMock(
            return_value="First report of the day with content."
        )
        outcome = MagicMock()
        outcome.get_stats = AsyncMock(return_value={"f": {"score": 0.8, "total": 10}})
        outcome.get_weekly_trends = AsyncMock(return_value={})

        result1 = await report.generate_report(outcome_tracker=outcome)

        # Now _last_report_day is set to today
        # Set up redis to return the cached report
        report.redis.get = AsyncMock(return_value=json.dumps(result1))
        result2 = await report.generate_report(outcome_tracker=outcome)
        assert result2["summary"] == result1["summary"]

    @pytest.mark.asyncio
    async def test_rate_limit_no_cache_generates_new(self, report):
        """When rate limit triggers but no cached report exists, generate new."""
        report._last_report_day = ""
        report.redis.get = AsyncMock(
            side_effect=[
                b"2099-01-01",  # Recovery: last day = today (fake future)
                None,  # get_latest_report returns None
            ]
        )
        report.ollama.generate = AsyncMock(
            return_value="New report generated despite rate limit."
        )

        with patch("assistant.self_report.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "2099-01-01"
            mock_dt.now.return_value.isoformat.return_value = (
                "2099-01-01T10:00:00+00:00"
            )
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = await report.generate_report()

        # No data so fallback is used
        assert "summary" in result


# ── get_latest_report edge cases ──────────────────────────────


class TestGetLatestReportEdgeCases:
    """Edge cases for get_latest_report."""

    @pytest.mark.asyncio
    async def test_invalid_json_returns_none(self, report):
        """Corrupt JSON in Redis returns None."""
        report.redis.get = AsyncMock(return_value=b"not valid json{{{")
        result = await report.get_latest_report()
        assert result is None

    @pytest.mark.asyncio
    async def test_redis_none_returns_none(self, report):
        """When redis is None, returns None."""
        report.redis = None
        result = await report.get_latest_report()
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_bytes_returns_none(self, report):
        """Empty bytes from Redis returns None (invalid JSON)."""
        report.redis.get = AsyncMock(return_value=b"")
        result = await report.get_latest_report()
        # Empty string is falsy, so returns None
        assert result is None


# ── _format_fallback edge cases ──────────────────────────────


class TestFormatFallbackEdgeCases:
    """Edge cases for the fallback formatter."""

    def test_all_data_sections_present(self, report):
        """Fallback with all data sections populated."""
        data = {
            "outcomes": {
                "set_light": {"score": 0.9, "total": 50},
                "set_climate": {"score": 0.6, "total": 20},
            },
            "corrections": {"total_corrections": 10, "active_rules": 5},
            "response_quality": {
                "device_command": {"score": 0.88},
                "information": {"score": 0.75},
            },
            "errors": {"last_24h": 7},
        }
        result = report._format_fallback(data)
        assert "set_light" in result
        assert "set_climate" in result
        assert "90%" in result
        assert "60%" in result
        assert "10 gesamt" in result
        assert "5 Regeln" in result
        assert "device_command" in result
        assert "7" in result

    def test_fallback_with_only_corrections(self, report):
        data = {"corrections": {"total_corrections": 3, "active_rules": 1}}
        result = report._format_fallback(data)
        assert "3 gesamt" in result
        assert "1 Regeln" in result

    def test_fallback_with_only_quality(self, report):
        data = {"response_quality": {"chat": {"score": 0.95}}}
        result = report._format_fallback(data)
        assert "chat" in result
        assert "95%" in result

    def test_fallback_with_only_errors(self, report):
        data = {"errors": {"last_24h": 0}}
        result = report._format_fallback(data)
        assert "0" in result


# ── _generate_summary prompt construction ────────────────────


class TestSummaryPromptConstruction:
    """Verify the LLM prompt is correctly constructed from data."""

    @pytest.mark.asyncio
    async def test_prompt_includes_outcome_scores(self, report):
        """Outcome data appears in the LLM prompt."""
        report.ollama.generate = AsyncMock(
            return_value="Summary with outcome scores and results."
        )
        data = {
            "outcomes": {
                "set_light": {"score": 0.75, "total": 17},
            },
        }
        await report._generate_summary(data)
        call_args = report.ollama.generate.call_args
        prompt = call_args[1]["prompt"] if "prompt" in call_args[1] else call_args[0][0]
        assert "set_light" in prompt
        assert "0.75" in prompt
        assert "17" in prompt

    @pytest.mark.asyncio
    async def test_prompt_includes_feedback_high_and_low(self, report):
        """Feedback with high/low scores appears in the prompt."""
        report.ollama.generate = AsyncMock(
            return_value="Feedback analysis in the summary report."
        )
        data = {
            "feedback": {"weather": 0.9, "energy_tip": 0.1, "neutral_thing": 0.5},
        }
        await report._generate_summary(data)
        call_args = report.ollama.generate.call_args
        prompt = call_args[1].get("prompt", "")
        assert "weather" in prompt
        assert "energy_tip" in prompt

    @pytest.mark.asyncio
    async def test_prompt_uses_correct_temperature(self, report):
        """LLM is called with temperature 0.6."""
        report.ollama.generate = AsyncMock(
            return_value="Temperature test report content ok ok."
        )
        data = {"outcomes": {"x": {"score": 0.5, "total": 1}}}
        await report._generate_summary(data)
        call_args = report.ollama.generate.call_args
        assert call_args[1]["temperature"] == 0.6

    @pytest.mark.asyncio
    async def test_prompt_uses_max_500_tokens(self, report):
        """LLM is called with max_tokens=500."""
        report.ollama.generate = AsyncMock(
            return_value="Token limit test report content ok ok."
        )
        data = {"outcomes": {"x": {"score": 0.5, "total": 1}}}
        await report._generate_summary(data)
        call_args = report.ollama.generate.call_args
        assert call_args[1]["max_tokens"] == 500

    @pytest.mark.asyncio
    async def test_empty_whitespace_response_returns_empty(self, report):
        """LLM returning only whitespace should return empty string."""
        report.ollama.generate = AsyncMock(return_value="   \n\t  ")
        data = {"outcomes": {"x": {"score": 0.5, "total": 1}}}
        result = await report._generate_summary(data)
        # After strip(), length is 0 which is < 20
        assert result == ""

    @pytest.mark.asyncio
    async def test_summary_with_non_numeric_feedback_values(self, report):
        """Feedback with non-numeric values should be filtered out."""
        report.ollama.generate = AsyncMock(
            return_value="Summary despite weird feedback values ok."
        )
        data = {
            "feedback": {
                "good_score": 0.9,
                "text_value": "not_a_number",
                "bad_score": 0.1,
            },
        }
        await report._generate_summary(data)
        call_args = report.ollama.generate.call_args
        prompt = call_args[1].get("prompt", "")
        # text_value should not appear in high/low scores
        assert "text_value" not in prompt


# ── initialize edge cases ─────────────────────────────────────


class TestInitializeEdgeCases:
    """Edge cases for the initialize method."""

    @pytest.mark.asyncio
    async def test_initialize_config_disabled(self, redis_mock, ollama_mock):
        """When config has enabled=False, report stays disabled."""
        r = SelfReport()
        r._cfg = {"enabled": False}
        await r.initialize(redis_mock, ollama_mock)
        assert r.enabled is False

    @pytest.mark.asyncio
    async def test_initialize_sets_ollama(self, redis_mock, ollama_mock):
        """Ollama client is stored after initialize."""
        r = SelfReport()
        await r.initialize(redis_mock, ollama_mock)
        assert r.ollama is ollama_mock


# ── Multiple subsystem data collection ────────────────────────


class TestMultiSubsystemCollection:
    """Test collecting data from multiple subsystems simultaneously."""

    @pytest.mark.asyncio
    async def test_all_subsystems_provide_data(self, report):
        """All subsystems contribute their data to the report."""
        outcome = MagicMock()
        outcome.get_stats = AsyncMock(
            return_value={"light": {"score": 0.8, "total": 10}}
        )
        outcome.get_weekly_trends = AsyncMock(return_value={"trend": "up"})

        correction = MagicMock()
        correction.get_stats = AsyncMock(
            return_value={"total_corrections": 3, "active_rules": 1}
        )
        correction.get_correction_patterns = AsyncMock(
            return_value=[{"pattern": "temp"}]
        )

        feedback = MagicMock()
        feedback.get_all_scores = AsyncMock(return_value={"weather": 0.85})

        observer = MagicMock()
        observer.get_learning_report = AsyncMock(return_value={"patterns_found": 7})

        quality = MagicMock()
        quality.get_stats = AsyncMock(return_value={"cmd": {"score": 0.92}})

        errors = MagicMock()
        errors.get_stats = AsyncMock(return_value={"last_24h": 2})

        opt = MagicMock()
        opt.generate_weekly_summary = AsyncMock(return_value={"proposals": 1})

        report.ollama.generate = AsyncMock(
            return_value="Full report with all subsystem data ok."
        )

        result = await report.generate_report(
            outcome_tracker=outcome,
            correction_memory=correction,
            feedback_tracker=feedback,
            learning_observer=observer,
            response_quality=quality,
            error_patterns=errors,
            self_optimization=opt,
        )

        data = result["data"]
        assert "outcomes" in data
        assert "outcome_trends" in data
        assert "corrections" in data
        assert "correction_patterns" in data
        assert "feedback" in data
        assert "learning" in data
        assert "response_quality" in data
        assert "errors" in data
        assert "self_optimization" in data

    @pytest.mark.asyncio
    async def test_learning_observer_without_method_skipped(self, report):
        """Learning observer without get_learning_report is skipped."""
        observer = MagicMock(spec=[])  # No methods at all
        report.ollama.generate = AsyncMock(
            return_value="Report without learning data ok ok."
        )
        result = await report.generate_report(learning_observer=observer)
        assert "learning" not in result.get("data", {})

    @pytest.mark.asyncio
    async def test_self_optimization_returns_none_skipped(self, report):
        """Self-optimization returning None is not added to data."""
        opt = MagicMock()
        opt.generate_weekly_summary = AsyncMock(return_value=None)
        report.ollama.generate = AsyncMock(
            return_value="Report without opt data content ok."
        )
        result = await report.generate_report(self_optimization=opt)
        assert "self_optimization" not in result.get("data", {})
