"""
Tests fuer SelfOptimization — Proposals, Validation, Banned Phrases, Tracking.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.self_optimization import SelfOptimization, _PARAMETER_PATHS


YAML_CFG = {
    "self_optimization": {
        "enabled": True,
        "approval_mode": "manual",
        "analysis_interval": "weekly",
        "max_proposals_per_cycle": 3,
        "model": "test-model",
        "parameter_bounds": {
            "sarcasm_level": {"min": 0, "max": 10},
            "max_response_sentences": {"min": 1, "max": 10},
        },
        "immutable_keys": ["dashboard"],
    },
    "personality": {
        "sarcasm_level": 5,
        "opinion_intensity": 3,
        "formality_min": 0.3,
        "formality_start": 0.7,
    },
    "response_filter": {
        "max_response_sentences": 4,
    },
    "insights": {"cooldown_hours": 6},
    "anticipation": {"min_confidence": 0.7},
    "feedback": {"base_cooldown_seconds": 300},
    "spontaneous": {"max_per_day": 5},
}


@pytest.fixture
def ollama():
    m = AsyncMock()
    m.generate = AsyncMock(return_value='[{"parameter": "sarcasm_level", "current": 5, "proposed": 6, "reason": "test", "confidence": 0.8}]')
    return m


@pytest.fixture
def versioning():
    m = AsyncMock()
    m.create_snapshot = AsyncMock(return_value="snap_123")
    return m


@pytest.fixture
def redis_m():
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.set = AsyncMock()
    r.setex = AsyncMock()
    r.delete = AsyncMock()
    r.lpush = AsyncMock()
    r.ltrim = AsyncMock()
    r.lrange = AsyncMock(return_value=[])
    r.expire = AsyncMock()
    r.hgetall = AsyncMock(return_value={})
    r.hincrby = AsyncMock()
    r.hdel = AsyncMock()
    return r


@pytest.fixture
def opt(ollama, versioning, redis_m):
    with patch("assistant.self_optimization.yaml_config", YAML_CFG):
        with patch("assistant.self_optimization.settings") as s:
            s.model_deep = "deep-model"
            so = SelfOptimization(ollama, versioning)
    so._redis = redis_m
    return so


# ── is_enabled ───────────────────────────────────────────

class TestIsEnabled:
    def test_enabled(self, opt):
        assert opt.is_enabled()

    def test_disabled_when_off(self, ollama, versioning):
        cfg = {**YAML_CFG, "self_optimization": {**YAML_CFG["self_optimization"], "enabled": False}}
        with patch("assistant.self_optimization.yaml_config", cfg):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "x"
                so = SelfOptimization(ollama, versioning)
        assert not so.is_enabled()

    def test_disabled_when_approval_off(self, ollama, versioning):
        cfg = {**YAML_CFG, "self_optimization": {**YAML_CFG["self_optimization"], "approval_mode": "off"}}
        with patch("assistant.self_optimization.yaml_config", cfg):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "x"
                so = SelfOptimization(ollama, versioning)
        assert not so.is_enabled()


# ── _validate_proposal ───────────────────────────────────

class TestValidateProposal:
    def test_valid_proposal(self, opt):
        p = {"parameter": "sarcasm_level", "proposed": 6}
        assert opt._validate_proposal(p)

    def test_invalid_unknown_parameter(self, opt):
        p = {"parameter": "nonexistent_param", "proposed": 5}
        assert not opt._validate_proposal(p)

    def test_invalid_immutable_key(self, opt):
        p = {"parameter": "trust_levels", "proposed": 5}
        assert not opt._validate_proposal(p)

    def test_invalid_non_numeric(self, opt):
        p = {"parameter": "sarcasm_level", "proposed": "high"}
        assert not opt._validate_proposal(p)

    def test_invalid_below_min(self, opt):
        p = {"parameter": "sarcasm_level", "proposed": -1}
        assert not opt._validate_proposal(p)

    def test_invalid_above_max(self, opt):
        p = {"parameter": "sarcasm_level", "proposed": 15}
        assert not opt._validate_proposal(p)

    def test_valid_within_bounds(self, opt):
        p = {"parameter": "max_response_sentences", "proposed": 5}
        assert opt._validate_proposal(p)

    def test_valid_no_bounds_defined(self, opt):
        p = {"parameter": "opinion_intensity", "proposed": 4}
        assert opt._validate_proposal(p)

    def test_hardcoded_immutable_security(self, opt):
        # Security is hardcoded immutable, can't be overridden
        p = {"parameter": "security", "proposed": 1}
        assert not opt._validate_proposal(p)


# ── _get_current_values ──────────────────────────────────

class TestGetCurrentValues:
    def test_reads_values(self, opt):
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            values = opt._get_current_values()
        assert values.get("sarcasm_level") == 5
        assert values.get("max_response_sentences") == 4


# ── get_pending_proposals ────────────────────────────────

class TestGetPendingProposals:
    @pytest.mark.asyncio
    async def test_returns_cached(self, opt):
        opt._pending_proposals = [{"parameter": "x"}]
        result = await opt.get_pending_proposals()
        assert result == [{"parameter": "x"}]

    @pytest.mark.asyncio
    async def test_loads_from_redis(self, opt, redis_m):
        opt._pending_proposals = []
        redis_m.get.return_value = json.dumps([{"parameter": "y"}])
        result = await opt.get_pending_proposals()
        assert result == [{"parameter": "y"}]

    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self, opt):
        opt._enabled = False
        result = await opt.get_pending_proposals()
        assert result == []


# ── approve_proposal ─────────────────────────────────────

class TestApproveProposal:
    @pytest.mark.asyncio
    async def test_approve_disabled(self, opt):
        opt._enabled = False
        result = await opt.approve_proposal(0)
        assert not result["success"]

    @pytest.mark.asyncio
    async def test_approve_invalid_index(self, opt):
        opt._pending_proposals = []
        result = await opt.approve_proposal(0)
        assert not result["success"]

    @pytest.mark.asyncio
    async def test_approve_valid(self, opt, redis_m, versioning):
        opt._pending_proposals = [
            {"parameter": "sarcasm_level", "current": 5, "proposed": 6, "reason": "test", "confidence": 0.8},
        ]
        with patch.object(opt, "_apply_parameter", new_callable=AsyncMock) as mock_apply:
            mock_apply.return_value = {"success": True, "message": "sarcasm_level: 5 -> 6"}
            result = await opt.approve_proposal(0)
        assert result["success"]
        versioning.create_snapshot.assert_called_once()


# ── reject_proposal ──────────────────────────────────────

class TestRejectProposal:
    @pytest.mark.asyncio
    async def test_reject_disabled(self, opt):
        opt._enabled = False
        result = await opt.reject_proposal(0)
        assert not result["success"]

    @pytest.mark.asyncio
    async def test_reject_valid(self, opt, redis_m):
        opt._pending_proposals = [
            {"parameter": "sarcasm_level", "current": 5, "proposed": 6, "reason": "test", "confidence": 0.8},
        ]
        result = await opt.reject_proposal(0)
        assert result["success"]
        assert opt._pending_proposals == []

    @pytest.mark.asyncio
    async def test_reject_all(self, opt, redis_m):
        opt._pending_proposals = [{"parameter": "a"}, {"parameter": "b"}]
        result = await opt.reject_all()
        assert result["success"]
        assert "2" in result["message"]


# ── format_proposals_for_chat ────────────────────────────

class TestFormatProposals:
    def test_format_empty(self, opt):
        text = opt.format_proposals_for_chat([])
        assert "Keine" in text

    def test_format_with_proposals(self, opt):
        proposals = [
            {"parameter": "sarcasm_level", "current": 5, "proposed": 6, "reason": "Mehr Humor", "confidence": 0.8},
        ]
        text = opt.format_proposals_for_chat(proposals)
        assert "sarcasm_level" in text
        assert "80%" in text
        assert "Mehr Humor" in text


# ── Banned Phrases ───────────────────────────────────────

class TestBannedPhrases:
    @pytest.mark.asyncio
    async def test_track_filtered_phrase(self, opt, redis_m):
        await opt.track_filtered_phrase("Natuerlich gerne")
        redis_m.hincrby.assert_called()

    @pytest.mark.asyncio
    async def test_track_filtered_phrase_empty(self, opt, redis_m):
        await opt.track_filtered_phrase("")
        redis_m.hincrby.assert_not_called()

    @pytest.mark.asyncio
    async def test_detect_banned_phrases_filter(self, opt, redis_m):
        redis_m.hgetall.side_effect = [
            {"phrase1": "6", "phrase2": "2"},  # filter counts
            {},  # corrections
        ]
        result = await opt.detect_new_banned_phrases()
        assert len(result) == 1
        assert result[0]["phrase"] == "phrase1"
        assert result[0]["count"] == 6

    @pytest.mark.asyncio
    async def test_detect_banned_phrases_corrections(self, opt, redis_m):
        redis_m.hgetall.side_effect = [
            {},  # filter counts
            {"bad phrase": "3"},  # corrections
        ]
        result = await opt.detect_new_banned_phrases()
        assert len(result) == 1
        assert result[0]["source"] == "correction"

    @pytest.mark.asyncio
    async def test_detect_banned_phrases_no_redis(self, opt):
        opt._redis = None
        result = await opt.detect_new_banned_phrases()
        assert result == []

    def test_format_phrase_suggestions_empty(self, opt):
        assert opt.format_phrase_suggestions([]) == ""

    def test_format_phrase_suggestions(self, opt):
        suggestions = [{"phrase": "test", "count": 5, "source": "filter"}]
        text = opt.format_phrase_suggestions(suggestions)
        assert "test" in text
        assert "sperren" in text


# ── Character Break Tracking ────────────────────────────

class TestCharacterBreak:
    @pytest.mark.asyncio
    async def test_track_character_break(self, opt, redis_m):
        await opt.track_character_break("llm_voice", "Said something wrong")
        redis_m.hincrby.assert_called()

    @pytest.mark.asyncio
    async def test_track_character_break_no_redis(self, opt):
        opt._redis = None
        await opt.track_character_break("llm_voice")  # Should not raise

    @pytest.mark.asyncio
    async def test_get_character_break_stats(self, opt, redis_m):
        redis_m.hgetall.return_value = {"llm_voice": "3", "identity": "1"}
        stats = await opt.get_character_break_stats(days=1)
        assert len(stats) <= 1


# ── Health Status ────────────────────────────────────────

class TestHealthStatus:
    def test_health_status(self, opt):
        status = opt.health_status()
        assert status["enabled"] is True
        assert status["approval_mode"] == "manual"
        assert status["interval"] == "weekly"
        assert isinstance(status["pending_proposals"], int)


# ── Weekly Summary ───────────────────────────────────────

class TestWeeklySummary:
    @pytest.mark.asyncio
    async def test_generate_weekly_summary_empty(self, opt, redis_m):
        redis_m.hgetall.return_value = {}
        summary = await opt.generate_weekly_summary()
        # No proposals, no history, no phrases -> empty
        assert summary == ""

    @pytest.mark.asyncio
    async def test_generate_weekly_summary_with_proposals(self, opt, redis_m):
        opt._pending_proposals = [{"parameter": "x"}]
        redis_m.hgetall.return_value = {}
        summary = await opt.generate_weekly_summary()
        assert "1 Optimierungsvorschlag" in summary


# ── Feedback / Corrections ───────────────────────────────

class TestDataSources:
    @pytest.mark.asyncio
    async def test_get_recent_corrections_empty(self, opt, redis_m):
        redis_m.lrange.return_value = []
        result = await opt._get_recent_corrections()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_recent_corrections_with_data(self, opt, redis_m):
        redis_m.lrange.return_value = [json.dumps({"text": "correction1"})]
        result = await opt._get_recent_corrections()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_feedback_stats(self, opt, redis_m):
        redis_m.get.return_value = "5"
        stats = await opt._get_feedback_stats()
        assert isinstance(stats, dict)

    @pytest.mark.asyncio
    async def test_get_outcome_stats_no_tracker(self, opt):
        result = await opt._get_outcome_stats(None)
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_quality_stats_no_tracker(self, opt):
        result = await opt._get_quality_stats(None)
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_correction_patterns_no_memory(self, opt):
        result = await opt._get_correction_patterns(None)
        assert result == []


# ── Save Baseline ────────────────────────────────────────

class TestBaseline:
    @pytest.mark.asyncio
    async def test_save_baseline(self, opt, redis_m):
        await opt.save_baseline("sarcasm_level")
        redis_m.setex.assert_called()

    @pytest.mark.asyncio
    async def test_save_baseline_no_redis(self, opt):
        opt._redis = None
        await opt.save_baseline("sarcasm_level")  # Should not raise

    @pytest.mark.asyncio
    async def test_check_effectiveness_no_baseline(self, opt, redis_m):
        redis_m.get.return_value = None
        result = await opt.check_effectiveness("sarcasm_level")
        assert result is None
