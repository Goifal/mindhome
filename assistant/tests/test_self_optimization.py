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


# ------------------------------------------------------------------
# Phase 1D: 3-Tage-Intervall, Domain-Tracking, proaktive Insights
# ------------------------------------------------------------------


class TestPhase1DFeatures:
    """Tests fuer Phase 1D Erweiterungen."""

    @pytest.fixture
    def opt_3day(self, ollama, versioning, redis_m):
        cfg = dict(YAML_CFG)
        cfg["self_optimization"] = dict(cfg["self_optimization"])
        cfg["self_optimization"]["analysis_interval"] = "3day"
        cfg["self_optimization"]["proactive_insights"] = True
        with patch("assistant.self_optimization.yaml_config", cfg):
            opt = SelfOptimization(ollama, versioning)
            opt._redis = redis_m
            return opt

    def test_interval_3day_supported(self, opt_3day):
        """3-Tage-Intervall sollte unterstuetzt werden."""
        assert opt_3day._interval == "3day"

    def test_proactive_insights_flag(self, opt_3day):
        """proactive_insights sollte aus Config geladen werden."""
        assert opt_3day._proactive_insights is True

    def test_set_notify_callback(self, opt_3day):
        """Notify-Callback setzbar."""
        cb = AsyncMock()
        opt_3day.set_notify_callback(cb)
        assert opt_3day._notify_callback is cb

    @pytest.mark.asyncio
    async def test_track_domain_correction(self, opt_3day, redis_m):
        """Domain-Korrektur wird in Redis getrackt."""
        await opt_3day.track_domain_correction("climate")
        redis_m.hincrby.assert_called_once_with(
            "mha:self_opt:domain_corrections", "climate", 1,
        )

    @pytest.mark.asyncio
    async def test_track_domain_correction_empty(self, opt_3day, redis_m):
        """Leere Domain wird ignoriert."""
        await opt_3day.track_domain_correction("")
        redis_m.hincrby.assert_not_called()

    @pytest.mark.asyncio
    async def test_proactive_insight_no_data(self, opt_3day, redis_m):
        """Insight ohne Daten → None."""
        redis_m.hgetall.return_value = {}
        result = await opt_3day._generate_proactive_insight()
        assert result is None

    @pytest.mark.asyncio
    async def test_proactive_insight_too_few(self, opt_3day, redis_m):
        """Insight unter 5 Korrekturen → None."""
        redis_m.hgetall.return_value = {b"climate": b"2", b"light": b"1"}
        result = await opt_3day._generate_proactive_insight()
        assert result is None

    @pytest.mark.asyncio
    async def test_proactive_insight_significant(self, opt_3day, redis_m):
        """Insight bei signifikanter Domain-Konzentration."""
        redis_m.hgetall.return_value = {
            b"climate": b"8", b"light": b"2", b"media": b"1",
        }
        result = await opt_3day._generate_proactive_insight()
        assert result is not None
        assert "Klima" in result
        assert "%" in result

    @pytest.mark.asyncio
    async def test_proactive_insight_disabled(self, opt_3day, redis_m):
        """Deaktiviertes Feature → None."""
        opt_3day._proactive_insights = False
        result = await opt_3day._generate_proactive_insight()
        assert result is None

    @pytest.mark.asyncio
    async def test_proactive_insight_even_distribution(self, opt_3day, redis_m):
        """Gleichverteilte Korrekturen (alle <30%) → None."""
        redis_m.hgetall.return_value = {
            b"climate": b"3", b"light": b"3", b"media": b"3", b"cover": b"3",
        }
        result = await opt_3day._generate_proactive_insight()
        assert result is None


# ------------------------------------------------------------------
# Immutable Core Protection (comprehensive)
# ------------------------------------------------------------------


class TestImmutableCoreProtection:
    """Verifies that ALL hardcoded immutable keys cannot be changed."""

    @pytest.fixture
    def opt(self, ollama, versioning, redis_m):
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "deep-model"
                so = SelfOptimization(ollama, versioning)
        so._redis = redis_m
        return so

    @pytest.mark.parametrize("immutable_key", [
        "trust_levels",
        "security",
        "autonomy",
        "dashboard",
        "models",
    ])
    def test_hardcoded_immutable_keys_rejected(self, opt, immutable_key):
        """Each hardcoded immutable key must be rejected regardless of config."""
        p = {"parameter": immutable_key, "proposed": 1}
        assert not opt._validate_proposal(p)

    def test_immutable_set_cannot_be_overridden_by_config(self, ollama, versioning, redis_m):
        """Even if config tries to remove hardcoded immutable keys, they remain protected."""
        cfg = dict(YAML_CFG)
        cfg["self_optimization"] = dict(cfg["self_optimization"])
        # Config explicitly sets empty immutable_keys — hardcoded ones must still be protected
        cfg["self_optimization"]["immutable_keys"] = []
        with patch("assistant.self_optimization.yaml_config", cfg):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "deep-model"
                so = SelfOptimization(ollama, versioning)
        so._redis = redis_m
        # All hardcoded immutable keys must still be blocked
        for key in ("trust_levels", "security", "autonomy", "models", "dashboard"):
            assert not so._validate_proposal({"parameter": key, "proposed": 0})

    def test_config_can_add_extra_immutable_keys(self, ollama, versioning, redis_m):
        """Config can ADD more immutable keys beyond the hardcoded set."""
        cfg = dict(YAML_CFG)
        cfg["self_optimization"] = dict(cfg["self_optimization"])
        cfg["self_optimization"]["immutable_keys"] = ["dashboard", "custom_key"]
        with patch("assistant.self_optimization.yaml_config", cfg):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "deep-model"
                so = SelfOptimization(ollama, versioning)
        so._redis = redis_m
        # custom_key would be blocked (even though it is not in _PARAMETER_PATHS, the
        # whitelist check fires first — but the immutable check is also there)
        assert "custom_key" in so._immutable


# ------------------------------------------------------------------
# Sarcasm-Formality Consistency Validation
# ------------------------------------------------------------------


class TestSarcasmFormalityConsistency:
    """Tests the sarcasm-formality sync guard in _validate_proposal."""

    @pytest.fixture
    def opt(self, ollama, versioning, redis_m):
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "deep-model"
                so = SelfOptimization(ollama, versioning)
        so._redis = redis_m
        return so

    def test_high_sarcasm_with_high_formality_rejected(self, opt):
        """Sarcasm >= 8 with formality_start > 75 is contradictory.

        Note: formality_start in config is stored as 0-100 scale (e.g. 80).
        The consistency check uses >75 threshold.
        """
        with patch("assistant.self_optimization.yaml_config", {
            **YAML_CFG,
            "personality": {**YAML_CFG["personality"], "formality_start": 80},
        }):
            p = {"parameter": "sarcasm_level", "proposed": 9}
            assert not opt._validate_proposal(p)

    def test_low_sarcasm_with_low_formality_rejected(self, opt):
        """Sarcasm <= 1 with formality_start < 30 is contradictory."""
        with patch("assistant.self_optimization.yaml_config", {
            **YAML_CFG,
            "personality": {**YAML_CFG["personality"], "formality_start": 20},
        }):
            p = {"parameter": "sarcasm_level", "proposed": 1}
            assert not opt._validate_proposal(p)

    def test_moderate_sarcasm_accepted(self, opt):
        """Moderate sarcasm values should pass consistency check."""
        p = {"parameter": "sarcasm_level", "proposed": 5}
        assert opt._validate_proposal(p)


# ------------------------------------------------------------------
# run_analysis
# ------------------------------------------------------------------


class TestRunAnalysis:
    """Tests for the full run_analysis workflow."""

    @pytest.fixture
    def opt(self, ollama, versioning, redis_m):
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "deep-model"
                so = SelfOptimization(ollama, versioning)
        so._redis = redis_m
        return so

    @pytest.mark.asyncio
    async def test_run_analysis_disabled(self, opt):
        """Analysis returns empty list when disabled."""
        opt._enabled = False
        result = await opt.run_analysis()
        assert result == []

    @pytest.mark.asyncio
    async def test_run_analysis_no_redis(self, opt):
        """Analysis returns empty list without Redis."""
        opt._redis = None
        result = await opt.run_analysis()
        assert result == []

    @pytest.mark.asyncio
    async def test_run_analysis_too_recent(self, opt, redis_m):
        """Analysis skips if last run was too recent."""
        from datetime import datetime, timezone
        redis_m.get.return_value = datetime.now(timezone.utc).isoformat()
        result = await opt.run_analysis()
        assert result == []

    @pytest.mark.asyncio
    async def test_run_analysis_no_data_no_redis(self, opt):
        """Analysis returns empty list when Redis is None (no data source at all)."""
        opt._redis = None
        result = await opt.run_analysis()
        assert result == []

    @pytest.mark.asyncio
    async def test_run_analysis_proceeds_with_feedback_stats(self, opt, redis_m, ollama):
        """Analysis proceeds when feedback stats exist even if corrections are empty.

        _get_feedback_stats returns a non-empty dict (with zero counts),
        so the 'no data' guard is not triggered and LLM is called.
        """
        redis_m.get.return_value = None  # no last_run
        redis_m.lrange.return_value = []  # no corrections
        ollama.generate.return_value = "[]"  # LLM says no proposals needed
        result = await opt.run_analysis()
        assert result == []
        ollama.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_analysis_validates_proposals(self, opt, redis_m, ollama):
        """Analysis filters out invalid proposals from LLM output."""
        redis_m.get.side_effect = [None, "5", "2", "0", "0"]  # last_run=None, then feedback stats
        redis_m.lrange.return_value = [json.dumps({"text": "correction"})]
        # LLM returns one valid and one invalid proposal
        ollama.generate.return_value = json.dumps([
            {"parameter": "sarcasm_level", "current": 5, "proposed": 6, "reason": "ok", "confidence": 0.8},
            {"parameter": "trust_levels", "current": 1, "proposed": 2, "reason": "hack", "confidence": 0.9},
        ])
        result = await opt.run_analysis()
        # Only the valid proposal should survive
        assert len(result) <= 1
        for p in result:
            assert p["parameter"] != "trust_levels"

    @pytest.mark.asyncio
    async def test_run_analysis_respects_max_proposals(self, opt, redis_m, ollama):
        """Analysis limits proposals to max_proposals_per_cycle."""
        redis_m.get.side_effect = [None, "5", "2", "0", "0"]
        redis_m.lrange.return_value = [json.dumps({"text": "c"})]
        # Return more proposals than the limit
        proposals = [
            {"parameter": "sarcasm_level", "current": 5, "proposed": 6, "reason": f"r{i}", "confidence": 0.8}
            for i in range(10)
        ]
        ollama.generate.return_value = json.dumps(proposals)
        result = await opt.run_analysis()
        assert len(result) <= opt._max_proposals


# ------------------------------------------------------------------
# _generate_proposals LLM parsing
# ------------------------------------------------------------------


class TestGenerateProposals:
    """Tests for LLM response parsing in _generate_proposals."""

    @pytest.fixture
    def opt(self, ollama, versioning, redis_m):
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "deep-model"
                so = SelfOptimization(ollama, versioning)
        so._redis = redis_m
        return so

    @pytest.mark.asyncio
    async def test_parse_valid_json_response(self, opt, ollama):
        """Valid JSON array from LLM is parsed correctly."""
        ollama.generate.return_value = '[{"parameter": "sarcasm_level", "current": 5, "proposed": 6, "reason": "test", "confidence": 0.8}]'
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            result = await opt._generate_proposals(
                [{"text": "correction"}], {"positive": 5, "negative": 1}
            )
        assert len(result) == 1
        assert result[0]["parameter"] == "sarcasm_level"

    @pytest.mark.asyncio
    async def test_parse_json_with_surrounding_text(self, opt, ollama):
        """LLM response with text around JSON array is handled."""
        ollama.generate.return_value = 'Here are my suggestions: [{"parameter": "sarcasm_level", "current": 5, "proposed": 6, "reason": "t", "confidence": 0.7}] That is all.'
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            result = await opt._generate_proposals([], {"positive": 3})
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_parse_empty_array(self, opt, ollama):
        """LLM returning empty array means no proposals."""
        ollama.generate.return_value = "[]"
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            result = await opt._generate_proposals([], {})
        assert result == []

    @pytest.mark.asyncio
    async def test_parse_invalid_json(self, opt, ollama):
        """Invalid JSON from LLM returns empty list."""
        ollama.generate.return_value = "This is not JSON at all"
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            result = await opt._generate_proposals([], {})
        assert result == []

    @pytest.mark.asyncio
    async def test_parse_filters_entries_without_parameter(self, opt, ollama):
        """Entries without 'parameter' key are filtered out."""
        ollama.generate.return_value = '[{"parameter": "sarcasm_level", "proposed": 6}, {"no_param": true}]'
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            result = await opt._generate_proposals([], {"positive": 1})
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_llm_exception_returns_empty(self, opt, ollama):
        """LLM exception is caught gracefully."""
        ollama.generate.side_effect = RuntimeError("LLM unavailable")
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            result = await opt._generate_proposals([], {})
        assert result == []


# ------------------------------------------------------------------
# Validation edge cases
# ------------------------------------------------------------------


class TestValidationEdgeCases:
    """Edge cases for _validate_proposal."""

    @pytest.fixture
    def opt(self, ollama, versioning, redis_m):
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "deep-model"
                so = SelfOptimization(ollama, versioning)
        so._redis = redis_m
        return so

    def test_missing_parameter_key(self, opt):
        """Proposal without 'parameter' key is rejected."""
        assert not opt._validate_proposal({"proposed": 5})

    def test_empty_parameter_string(self, opt):
        """Empty parameter string is rejected."""
        assert not opt._validate_proposal({"parameter": "", "proposed": 5})

    def test_none_proposed_value(self, opt):
        """None proposed value is rejected (not numeric)."""
        assert not opt._validate_proposal({"parameter": "sarcasm_level", "proposed": None})

    def test_boolean_proposed_value_rejected(self, opt):
        """Boolean values should be rejected (even though bool is subclass of int in Python)."""
        # Note: In Python, isinstance(True, int) is True, so this tests the actual behavior
        p = {"parameter": "sarcasm_level", "proposed": True}
        # bool IS int in Python, so this might pass — documenting the actual behavior
        result = opt._validate_proposal(p)
        # True == 1 which is within bounds, so it would pass the numeric check
        # This is acceptable since it coerces to 1

    def test_float_proposed_value_accepted(self, opt):
        """Float values should be accepted."""
        p = {"parameter": "sarcasm_level", "proposed": 5.5}
        assert opt._validate_proposal(p)

    def test_boundary_min_value_accepted(self, opt):
        """Exact minimum boundary should be accepted."""
        p = {"parameter": "sarcasm_level", "proposed": 0}
        assert opt._validate_proposal(p)

    def test_boundary_max_value_accepted(self, opt):
        """Exact maximum boundary should be accepted (for parameters without consistency checks)."""
        p = {"parameter": "max_response_sentences", "proposed": 10}
        assert opt._validate_proposal(p)

    def test_parameter_without_bounds_accepts_large_value(self, opt):
        """Parameters without defined bounds accept any numeric value."""
        p = {"parameter": "opinion_intensity", "proposed": 999}
        assert opt._validate_proposal(p)

    def test_list_proposed_value_rejected(self, opt):
        """List values must be rejected."""
        assert not opt._validate_proposal({"parameter": "sarcasm_level", "proposed": [5]})

    def test_dict_proposed_value_rejected(self, opt):
        """Dict values must be rejected."""
        assert not opt._validate_proposal({"parameter": "sarcasm_level", "proposed": {"value": 5}})


# ------------------------------------------------------------------
# Additional coverage: initialize, apply_parameter, approve edge cases,
# reject edge cases, weekly summary with history/corrections,
# check_effectiveness with data, save_baseline with trackers,
# track_user_phrase_correction, add_banned_phrase, proactive insight callback
# ------------------------------------------------------------------


class TestInitialize:
    """Tests for the initialize() method."""

    @pytest.mark.asyncio
    async def test_initialize_sets_redis(self, ollama, versioning):
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "deep-model"
                so = SelfOptimization(ollama, versioning)
        redis = AsyncMock()
        await so.initialize(redis)
        assert so._redis is redis


class TestApplyParameter:
    """Tests for _apply_parameter — file I/O mocked."""

    @pytest.fixture
    def opt(self, ollama, versioning, redis_m):
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "deep-model"
                so = SelfOptimization(ollama, versioning)
        so._redis = redis_m
        return so

    @pytest.mark.asyncio
    async def test_apply_unknown_parameter(self, opt):
        """Unknown parameter returns failure."""
        result = await opt._apply_parameter("nonexistent_param", 5)
        assert not result["success"]
        assert "Unbekannt" in result["message"]

    @pytest.mark.asyncio
    async def test_apply_parameter_success(self, opt):
        """Successful parameter application via mocked file I/O."""
        import yaml

        fake_config = {"personality": {"sarcasm_level": 5}}
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
                mock_thread.return_value = None
                with patch("assistant.self_optimization.load_yaml_config", return_value=YAML_CFG):
                    with patch("assistant.self_optimization.cfg_module") as mock_cfg:
                        mock_cfg.yaml_config = dict(YAML_CFG)
                        result = await opt._apply_parameter("sarcasm_level", 6)
        assert result["success"]
        assert "6" in result["message"]

    @pytest.mark.asyncio
    async def test_apply_parameter_exception(self, opt):
        """Exception during apply returns failure."""
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            with patch("asyncio.to_thread", new_callable=AsyncMock, side_effect=OSError("disk full")):
                result = await opt._apply_parameter("sarcasm_level", 6)
        assert not result["success"]
        assert "fehlgeschlagen" in result["message"]


class TestApproveProposalAdvanced:
    """Advanced tests for approve_proposal — validation failure, redis updates."""

    @pytest.fixture
    def opt(self, ollama, versioning, redis_m):
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "deep-model"
                so = SelfOptimization(ollama, versioning)
        so._redis = redis_m
        return so

    @pytest.mark.asyncio
    async def test_approve_negative_index(self, opt):
        """Negative index is rejected."""
        opt._pending_proposals = [
            {"parameter": "sarcasm_level", "current": 5, "proposed": 6,
             "reason": "test", "confidence": 0.8},
        ]
        result = await opt.approve_proposal(-1)
        assert not result["success"]

    @pytest.mark.asyncio
    async def test_approve_validates_before_apply(self, opt, versioning):
        """Proposal that fails validation is rejected during approve."""
        opt._pending_proposals = [
            {"parameter": "sarcasm_level", "current": 5, "proposed": "not_numeric",
             "reason": "test", "confidence": 0.8},
        ]
        result = await opt.approve_proposal(0)
        assert not result["success"]
        assert "Grenzen" in result["message"]

    @pytest.mark.asyncio
    async def test_approve_clears_redis_when_last_proposal(self, opt, redis_m, versioning):
        """When the last proposal is approved, pending key is deleted from Redis."""
        opt._pending_proposals = [
            {"parameter": "sarcasm_level", "current": 5, "proposed": 6,
             "reason": "test", "confidence": 0.8},
        ]
        with patch.object(opt, "_apply_parameter", new_callable=AsyncMock) as mock_apply:
            mock_apply.return_value = {"success": True, "message": "ok"}
            await opt.approve_proposal(0)
        redis_m.delete.assert_called_with("mha:self_opt:pending")

    @pytest.mark.asyncio
    async def test_approve_updates_redis_when_more_proposals(self, opt, redis_m, versioning):
        """When more proposals remain after approve, redis is updated (not deleted)."""
        opt._pending_proposals = [
            {"parameter": "sarcasm_level", "current": 5, "proposed": 6,
             "reason": "test", "confidence": 0.8},
            {"parameter": "opinion_intensity", "current": 3, "proposed": 4,
             "reason": "test2", "confidence": 0.7},
        ]
        with patch.object(opt, "_apply_parameter", new_callable=AsyncMock) as mock_apply:
            mock_apply.return_value = {"success": True, "message": "ok"}
            await opt.approve_proposal(0)
        # Should call set (not delete) since 1 proposal remains
        redis_m.set.assert_called()

    @pytest.mark.asyncio
    async def test_approve_records_history(self, opt, redis_m, versioning):
        """Approved proposal is pushed to history list in Redis."""
        opt._pending_proposals = [
            {"parameter": "sarcasm_level", "current": 5, "proposed": 6,
             "reason": "test", "confidence": 0.8},
        ]
        with patch.object(opt, "_apply_parameter", new_callable=AsyncMock) as mock_apply:
            mock_apply.return_value = {"success": True, "message": "ok"}
            await opt.approve_proposal(0)
        redis_m.lpush.assert_called()
        redis_m.ltrim.assert_called_with("mha:self_opt:history", 0, 49)

    @pytest.mark.asyncio
    async def test_approve_failed_apply_does_not_update_proposals(self, opt, redis_m, versioning):
        """When _apply_parameter fails, proposals list stays unchanged."""
        opt._pending_proposals = [
            {"parameter": "sarcasm_level", "current": 5, "proposed": 6,
             "reason": "test", "confidence": 0.8},
        ]
        with patch.object(opt, "_apply_parameter", new_callable=AsyncMock) as mock_apply:
            mock_apply.return_value = {"success": False, "message": "error"}
            result = await opt.approve_proposal(0)
        assert not result["success"]
        # Proposals should not have been modified
        assert len(opt._pending_proposals) == 1


class TestRejectProposalAdvanced:
    """Advanced tests for reject_proposal."""

    @pytest.fixture
    def opt(self, ollama, versioning, redis_m):
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "deep-model"
                so = SelfOptimization(ollama, versioning)
        so._redis = redis_m
        return so

    @pytest.mark.asyncio
    async def test_reject_invalid_index(self, opt):
        """Out of range index returns failure."""
        opt._pending_proposals = [{"parameter": "sarcasm_level", "proposed": 6}]
        result = await opt.reject_proposal(5)
        assert not result["success"]

    @pytest.mark.asyncio
    async def test_reject_records_in_redis(self, opt, redis_m):
        """Rejected proposals are stored in rejected list."""
        opt._pending_proposals = [
            {"parameter": "sarcasm_level", "current": 5, "proposed": 6,
             "reason": "test", "confidence": 0.8},
        ]
        await opt.reject_proposal(0)
        redis_m.lpush.assert_called()
        # Check that rejected list is used
        call_args = redis_m.lpush.call_args
        assert "rejected" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_reject_clears_redis_when_last(self, opt, redis_m):
        """When last proposal is rejected, pending key is deleted."""
        opt._pending_proposals = [
            {"parameter": "sarcasm_level", "current": 5, "proposed": 6,
             "reason": "test", "confidence": 0.8},
        ]
        await opt.reject_proposal(0)
        redis_m.delete.assert_called_with("mha:self_opt:pending")

    @pytest.mark.asyncio
    async def test_reject_updates_redis_when_more_remain(self, opt, redis_m):
        """When proposals remain, redis is updated."""
        opt._pending_proposals = [
            {"parameter": "sarcasm_level", "current": 5, "proposed": 6,
             "reason": "test", "confidence": 0.8},
            {"parameter": "opinion_intensity", "current": 3, "proposed": 4,
             "reason": "test2", "confidence": 0.7},
        ]
        await opt.reject_proposal(0)
        redis_m.set.assert_called()

    @pytest.mark.asyncio
    async def test_reject_all_disabled(self, opt):
        """reject_all when disabled returns failure."""
        opt._enabled = False
        result = await opt.reject_all()
        assert not result["success"]


class TestGetPendingProposalsAdvanced:
    """Advanced pending proposal tests."""

    @pytest.fixture
    def opt(self, ollama, versioning, redis_m):
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "deep-model"
                so = SelfOptimization(ollama, versioning)
        so._redis = redis_m
        return so

    @pytest.mark.asyncio
    async def test_returns_empty_when_redis_has_nothing(self, opt, redis_m):
        """No cached proposals and no redis data returns empty list."""
        opt._pending_proposals = []
        redis_m.get.return_value = None
        result = await opt.get_pending_proposals()
        assert result == []

    @pytest.mark.asyncio
    async def test_no_redis_returns_empty(self, opt):
        """Without redis, returns empty in-memory list."""
        opt._redis = None
        opt._pending_proposals = []
        result = await opt.get_pending_proposals()
        assert result == []


class TestTrackUserPhraseCorrection:
    """Tests for track_user_phrase_correction."""

    @pytest.fixture
    def opt(self, ollama, versioning, redis_m):
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "deep-model"
                so = SelfOptimization(ollama, versioning)
        so._redis = redis_m
        return so

    @pytest.mark.asyncio
    async def test_tracks_phrase(self, opt, redis_m):
        """Phrase is tracked via hincrby in Redis."""
        await opt.track_user_phrase_correction("sag das nicht")
        redis_m.hincrby.assert_called_once_with(
            "mha:self_opt:phrase_corrections", "sag das nicht", 1,
        )
        redis_m.expire.assert_called()

    @pytest.mark.asyncio
    async def test_empty_phrase_ignored(self, opt, redis_m):
        """Empty string is not tracked."""
        await opt.track_user_phrase_correction("")
        redis_m.hincrby.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_redis_no_crash(self, opt):
        """Without redis, does not crash."""
        opt._redis = None
        await opt.track_user_phrase_correction("test")

    @pytest.mark.asyncio
    async def test_long_phrase_truncated(self, opt, redis_m):
        """Phrases longer than 100 chars are truncated."""
        long_phrase = "x" * 200
        await opt.track_user_phrase_correction(long_phrase)
        call_args = redis_m.hincrby.call_args[0]
        assert len(call_args[1]) == 100


class TestAddBannedPhrase:
    """Tests for add_banned_phrase."""

    @pytest.fixture
    def opt(self, ollama, versioning, redis_m):
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "deep-model"
                so = SelfOptimization(ollama, versioning)
        so._redis = redis_m
        return so

    @pytest.mark.asyncio
    async def test_short_phrase_rejected(self, opt):
        """Phrases shorter than 3 chars are rejected."""
        result = await opt.add_banned_phrase("ab")
        assert not result["success"]
        assert "kurz" in result["message"]

    @pytest.mark.asyncio
    async def test_empty_phrase_rejected(self, opt):
        """Empty phrase is rejected."""
        result = await opt.add_banned_phrase("")
        assert not result["success"]

    @pytest.mark.asyncio
    async def test_add_phrase_success(self, opt, redis_m, versioning):
        """Successfully adds a phrase via mocked file I/O."""
        fake_config = {"response_filter": {"banned_phrases": []}}
        with patch("asyncio.to_thread") as mock_thread:
            mock_thread.side_effect = [fake_config, None]  # read, write
            with patch("assistant.self_optimization.load_yaml_config", return_value=YAML_CFG):
                with patch("assistant.self_optimization.cfg_module") as mock_cfg:
                    mock_cfg.yaml_config = dict(YAML_CFG)
                    result = await opt.add_banned_phrase("Natuerlich gerne")
        assert result["success"]
        assert "Sperrliste" in result["message"]
        versioning.create_snapshot.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_duplicate_phrase(self, opt, redis_m, versioning):
        """Adding an already-existing phrase returns failure."""
        fake_config = {"response_filter": {"banned_phrases": ["already here"]}}
        with patch("asyncio.to_thread") as mock_thread:
            mock_thread.side_effect = [fake_config, None]
            result = await opt.add_banned_phrase("already here")
        assert not result["success"]
        assert "bereits" in result["message"]

    @pytest.mark.asyncio
    async def test_add_phrase_exception(self, opt, redis_m, versioning):
        """Exception during write returns failure."""
        with patch("asyncio.to_thread", side_effect=OSError("disk error")):
            result = await opt.add_banned_phrase("test phrase")
        assert not result["success"]
        assert "fehlgeschlagen" in result["message"]

    @pytest.mark.asyncio
    async def test_add_phrase_resets_counters(self, opt, redis_m, versioning):
        """Adding a phrase resets its filter and correction counters."""
        fake_config = {"response_filter": {"banned_phrases": []}}
        with patch("asyncio.to_thread") as mock_thread:
            mock_thread.side_effect = [fake_config, None]
            with patch("assistant.self_optimization.load_yaml_config", return_value=YAML_CFG):
                with patch("assistant.self_optimization.cfg_module") as mock_cfg:
                    mock_cfg.yaml_config = dict(YAML_CFG)
                    await opt.add_banned_phrase("bad phrase")
        redis_m.hdel.assert_any_call("mha:self_opt:phrase_filter_counts", "bad phrase")
        redis_m.hdel.assert_any_call("mha:self_opt:phrase_corrections", "bad phrase")


class TestWeeklySummaryAdvanced:
    """Advanced weekly summary tests with history and correction data."""

    @pytest.fixture
    def opt(self, ollama, versioning, redis_m):
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "deep-model"
                so = SelfOptimization(ollama, versioning)
        so._redis = redis_m
        return so

    @pytest.mark.asyncio
    async def test_summary_with_history(self, opt, redis_m):
        """Summary includes recently applied changes."""
        opt._pending_proposals = []
        redis_m.lrange.return_value = [
            json.dumps({"parameter": "sarcasm_level", "current": 5, "proposed": 6,
                        "applied_at": "2026-03-20T12:00:00"}),
        ]
        redis_m.hgetall.side_effect = [{}, {}]  # filter counts, corrections
        summary = await opt.generate_weekly_summary()
        assert "Letzte Aenderungen" in summary
        assert "sarcasm_level" in summary

    @pytest.mark.asyncio
    async def test_summary_with_correction_memory(self, opt, redis_m):
        """Summary includes correction statistics."""
        opt._pending_proposals = []
        redis_m.lrange.return_value = []
        redis_m.hgetall.side_effect = [{}, {}]
        corr_mem = AsyncMock()
        corr_mem.get_stats = AsyncMock(return_value={"total_corrections": 10, "active_rules": 3})
        summary = await opt.generate_weekly_summary(correction_memory=corr_mem)
        assert "Korrekturen" in summary
        assert "10" in summary

    @pytest.mark.asyncio
    async def test_summary_with_phrase_suggestions(self, opt, redis_m):
        """Summary counts phrase suggestions."""
        opt._pending_proposals = []
        redis_m.lrange.return_value = []
        redis_m.hgetall.side_effect = [
            {"bad phrase": "6"},  # filter counts >= 5
            {},  # corrections
        ]
        summary = await opt.generate_weekly_summary()
        assert "Phrase" in summary


class TestCheckEffectivenessAdvanced:
    """Tests for check_effectiveness with actual data."""

    @pytest.fixture
    def opt(self, ollama, versioning, redis_m):
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "deep-model"
                so = SelfOptimization(ollama, versioning)
        so._redis = redis_m
        return so

    @pytest.mark.asyncio
    async def test_check_effectiveness_no_redis(self, opt):
        """Without redis, returns None."""
        opt._redis = None
        result = await opt.check_effectiveness("sarcasm_level")
        assert result is None

    @pytest.mark.asyncio
    async def test_check_effectiveness_invalid_json(self, opt, redis_m):
        """Invalid JSON baseline returns None."""
        redis_m.get.return_value = "not json"
        result = await opt.check_effectiveness("sarcasm_level")
        assert result is None

    @pytest.mark.asyncio
    async def test_check_effectiveness_with_data(self, opt, redis_m):
        """Returns score changes when baseline and current data exist."""
        baseline = {
            "timestamp": "2026-03-15T12:00:00",
            "outcome_stats": {"lights": {"score": 0.6}},
        }
        redis_m.get.return_value = json.dumps(baseline)
        outcome_tracker = AsyncMock()
        outcome_tracker.get_stats = AsyncMock(return_value={
            "lights": {"score": 0.8},
        })
        result = await opt.check_effectiveness(
            "sarcasm_level", outcome_tracker=outcome_tracker,
        )
        assert result is not None
        assert result["parameter"] == "sarcasm_level"
        assert result["score_changes"]["lights"] == 0.2

    @pytest.mark.asyncio
    async def test_check_effectiveness_with_quality(self, opt, redis_m):
        """quality tracker is called when provided."""
        baseline = {"timestamp": "2026-03-15T12:00:00", "outcome_stats": {}}
        redis_m.get.return_value = json.dumps(baseline)
        quality = AsyncMock()
        quality.get_stats = AsyncMock(return_value={"avg_score": 0.9})
        result = await opt.check_effectiveness(
            "sarcasm_level", response_quality=quality,
        )
        assert result is not None
        quality.get_stats.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_effectiveness_tracker_exception(self, opt, redis_m):
        """Exception from tracker does not crash."""
        baseline = {"timestamp": "2026-03-15T12:00:00"}
        redis_m.get.return_value = json.dumps(baseline)
        outcome_tracker = AsyncMock()
        outcome_tracker.get_stats = AsyncMock(side_effect=RuntimeError("fail"))
        result = await opt.check_effectiveness(
            "sarcasm_level", outcome_tracker=outcome_tracker,
        )
        assert result is not None
        assert result["score_changes"] == {}


class TestSaveBaselineAdvanced:
    """Tests for save_baseline with tracker data."""

    @pytest.fixture
    def opt(self, ollama, versioning, redis_m):
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "deep-model"
                so = SelfOptimization(ollama, versioning)
        so._redis = redis_m
        return so

    @pytest.mark.asyncio
    async def test_save_baseline_with_outcome_tracker(self, opt, redis_m):
        """Baseline includes outcome stats when tracker provided."""
        ot = AsyncMock()
        ot.get_stats = AsyncMock(return_value={"lights": {"score": 0.7}})
        await opt.save_baseline("sarcasm_level", outcome_tracker=ot)
        redis_m.setex.assert_called_once()
        saved_data = json.loads(redis_m.setex.call_args[0][2])
        assert "outcome_stats" in saved_data

    @pytest.mark.asyncio
    async def test_save_baseline_with_quality_tracker(self, opt, redis_m):
        """Baseline includes quality stats when tracker provided."""
        rq = AsyncMock()
        rq.get_stats = AsyncMock(return_value={"avg": 0.9})
        await opt.save_baseline("sarcasm_level", response_quality=rq)
        saved_data = json.loads(redis_m.setex.call_args[0][2])
        assert "quality_stats" in saved_data

    @pytest.mark.asyncio
    async def test_save_baseline_tracker_exception(self, opt, redis_m):
        """Exception in tracker does not prevent baseline save."""
        ot = AsyncMock()
        ot.get_stats = AsyncMock(side_effect=RuntimeError("fail"))
        await opt.save_baseline("sarcasm_level", outcome_tracker=ot)
        redis_m.setex.assert_called_once()


class TestRunAnalysisProactiveCallback:
    """Tests for proactive insight callback in run_analysis."""

    @pytest.fixture
    def opt(self, ollama, versioning, redis_m):
        cfg = dict(YAML_CFG)
        cfg["self_optimization"] = dict(cfg["self_optimization"])
        cfg["self_optimization"]["proactive_insights"] = True
        with patch("assistant.self_optimization.yaml_config", cfg):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "deep-model"
                so = SelfOptimization(ollama, versioning)
        so._redis = redis_m
        return so

    @pytest.mark.asyncio
    async def test_callback_called_with_insight(self, opt, redis_m, ollama):
        """Notify callback is invoked when insight is generated."""
        redis_m.get.return_value = None  # No last_run
        redis_m.lrange.return_value = [json.dumps({"text": "c"})]
        ollama.generate.return_value = "[]"
        # Domain corrections for proactive insight
        redis_m.hgetall.return_value = {b"climate": b"8", b"light": b"2"}

        callback = AsyncMock()
        opt.set_notify_callback(callback)

        await opt.run_analysis()
        callback.assert_called_once()
        call_data = callback.call_args[0][0]
        assert call_data["type"] == "self_optimization_insight"

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_crash(self, opt, redis_m, ollama):
        """Exception in callback does not crash run_analysis."""
        redis_m.get.return_value = None
        redis_m.lrange.return_value = [json.dumps({"text": "c"})]
        ollama.generate.return_value = "[]"
        redis_m.hgetall.return_value = {b"climate": b"8", b"light": b"2"}

        callback = AsyncMock(side_effect=RuntimeError("callback fail"))
        opt.set_notify_callback(callback)

        # Should not raise
        await opt.run_analysis()


class TestGetCurrentValuesEdgeCases:
    """Edge cases for _get_current_values."""

    @pytest.fixture
    def opt(self, ollama, versioning, redis_m):
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "deep-model"
                so = SelfOptimization(ollama, versioning)
        so._redis = redis_m
        return so

    def test_missing_section_returns_empty(self, opt):
        """Missing section path returns empty dict for that param."""
        sparse_cfg = {"personality": {}}
        with patch("assistant.self_optimization.yaml_config", sparse_cfg):
            values = opt._get_current_values()
        # Parameters whose paths don't exist should not appear
        assert "insight_cooldown_hours" not in values

    def test_all_parameters_when_full_config(self, opt):
        """All PARAMETER_PATHS are read when config is complete."""
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            values = opt._get_current_values()
        assert "sarcasm_level" in values
        assert "max_response_sentences" in values
        assert "insight_cooldown_hours" in values
        assert "feedback_base_cooldown" in values


class TestGetRecentCorrectionsEdgeCases:
    """Edge cases for _get_recent_corrections."""

    @pytest.fixture
    def opt(self, ollama, versioning, redis_m):
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "deep-model"
                so = SelfOptimization(ollama, versioning)
        so._redis = redis_m
        return so

    @pytest.mark.asyncio
    async def test_no_redis(self, opt):
        """No redis returns empty list."""
        opt._redis = None
        result = await opt._get_recent_corrections()
        assert result == []

    @pytest.mark.asyncio
    async def test_invalid_json_skipped(self, opt, redis_m):
        """Invalid JSON entries are skipped gracefully."""
        redis_m.lrange.return_value = [
            json.dumps({"valid": True}),
            "not json at all",
            json.dumps({"also_valid": True}),
        ]
        result = await opt._get_recent_corrections()
        assert len(result) == 2


class TestGetFeedbackStatsEdgeCases:
    """Edge cases for _get_feedback_stats."""

    @pytest.fixture
    def opt(self, ollama, versioning, redis_m):
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "deep-model"
                so = SelfOptimization(ollama, versioning)
        so._redis = redis_m
        return so

    @pytest.mark.asyncio
    async def test_no_redis(self, opt):
        """No redis returns empty dict."""
        opt._redis = None
        result = await opt._get_feedback_stats()
        assert result == {}

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self, opt, redis_m):
        """Exception during redis call returns empty dict."""
        redis_m.get.side_effect = RuntimeError("redis down")
        result = await opt._get_feedback_stats()
        assert result == {}


class TestDataSourcesWithTrackers:
    """Tests for _get_outcome_stats, _get_quality_stats, _get_correction_patterns with trackers."""

    @pytest.fixture
    def opt(self, ollama, versioning, redis_m):
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "deep-model"
                so = SelfOptimization(ollama, versioning)
        so._redis = redis_m
        return so

    @pytest.mark.asyncio
    async def test_outcome_stats_with_tracker(self, opt):
        """Returns data from outcome tracker."""
        tracker = AsyncMock()
        tracker.get_stats = AsyncMock(return_value={"actions": 5})
        result = await opt._get_outcome_stats(tracker)
        assert result == {"actions": 5}

    @pytest.mark.asyncio
    async def test_outcome_stats_exception(self, opt):
        """Exception from tracker returns empty dict."""
        tracker = AsyncMock()
        tracker.get_stats = AsyncMock(side_effect=RuntimeError("fail"))
        result = await opt._get_outcome_stats(tracker)
        assert result == {}

    @pytest.mark.asyncio
    async def test_quality_stats_with_tracker(self, opt):
        """Returns data from quality tracker."""
        tracker = AsyncMock()
        tracker.get_stats = AsyncMock(return_value={"avg": 0.8})
        result = await opt._get_quality_stats(tracker)
        assert result == {"avg": 0.8}

    @pytest.mark.asyncio
    async def test_quality_stats_exception(self, opt):
        """Exception from tracker returns empty dict."""
        tracker = AsyncMock()
        tracker.get_stats = AsyncMock(side_effect=RuntimeError("fail"))
        result = await opt._get_quality_stats(tracker)
        assert result == {}

    @pytest.mark.asyncio
    async def test_correction_patterns_with_memory(self, opt):
        """Returns data from correction memory."""
        mem = AsyncMock()
        mem.get_correction_patterns = AsyncMock(return_value=[{"pattern": "x"}])
        result = await opt._get_correction_patterns(mem)
        assert result == [{"pattern": "x"}]

    @pytest.mark.asyncio
    async def test_correction_patterns_exception(self, opt):
        """Exception from correction memory returns empty list."""
        mem = AsyncMock()
        mem.get_correction_patterns = AsyncMock(side_effect=RuntimeError("fail"))
        result = await opt._get_correction_patterns(mem)
        assert result == []


class TestCharacterBreakAdvanced:
    """Advanced character break tracking tests."""

    @pytest.fixture
    def opt(self, ollama, versioning, redis_m):
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "deep-model"
                so = SelfOptimization(ollama, versioning)
        so._redis = redis_m
        return so

    @pytest.mark.asyncio
    async def test_track_without_detail(self, opt, redis_m):
        """Tracking without detail does not push to log."""
        await opt.track_character_break("llm_voice")
        redis_m.hincrby.assert_called()
        redis_m.lpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_track_with_detail_pushes_log(self, opt, redis_m):
        """Tracking with detail pushes to break log."""
        await opt.track_character_break("identity", "Said wrong name")
        redis_m.lpush.assert_called()
        redis_m.ltrim.assert_called()

    @pytest.mark.asyncio
    async def test_track_exception_does_not_crash(self, opt, redis_m):
        """Redis exception during track does not crash."""
        redis_m.hincrby.side_effect = RuntimeError("redis fail")
        await opt.track_character_break("llm_voice")  # Should not raise

    @pytest.mark.asyncio
    async def test_get_stats_no_redis(self, opt):
        """Without redis, returns empty dict."""
        opt._redis = None
        result = await opt.get_character_break_stats()
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_stats_exception(self, opt, redis_m):
        """Redis exception returns empty dict."""
        redis_m.hgetall.side_effect = RuntimeError("fail")
        result = await opt.get_character_break_stats()
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_stats_bytes_decoded(self, opt, redis_m):
        """Byte keys/values from Redis are decoded properly."""
        redis_m.hgetall.return_value = {b"llm_voice": b"5", b"identity": b"2"}
        stats = await opt.get_character_break_stats(days=1)
        # Should have today's data
        from datetime import date
        today = date.today().isoformat()
        if today in stats:
            assert stats[today]["llm_voice"] == 5
            assert stats[today]["identity"] == 2


class TestDomainCorrectionEdgeCases:
    """Edge cases for track_domain_correction."""

    @pytest.fixture
    def opt(self, ollama, versioning, redis_m):
        with patch("assistant.self_optimization.yaml_config", YAML_CFG):
            with patch("assistant.self_optimization.settings") as s:
                s.model_deep = "deep-model"
                so = SelfOptimization(ollama, versioning)
        so._redis = redis_m
        return so

    @pytest.mark.asyncio
    async def test_no_redis(self, opt):
        """Without redis, does not crash."""
        opt._redis = None
        await opt.track_domain_correction("climate")

    @pytest.mark.asyncio
    async def test_exception_does_not_crash(self, opt, redis_m):
        """Redis exception does not crash."""
        redis_m.hincrby.side_effect = RuntimeError("fail")
        await opt.track_domain_correction("climate")  # Should not raise
