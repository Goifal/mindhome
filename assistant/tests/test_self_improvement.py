"""
Integrations-Tests fuer Self-Improvement Features.
Tests fuer: Feedback per-person, Self-Optimization Erweiterungen,
Personality learned_rules_section.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.feedback import FeedbackTracker, DEFAULT_SCORE
from assistant.self_optimization import SelfOptimization, _PARAMETER_PATHS
from assistant.personality import PersonalityEngine


# ============================================================
# Feedback Tracker: Per-Person Scores (Feature 6)
# ============================================================

class TestFeedbackPerPerson:
    """Tests fuer per-person Feedback-Scores."""

    @pytest.fixture
    def feedback(self, redis_mock):
        ft = FeedbackTracker()
        ft.redis = redis_mock
        return ft

    @pytest.mark.asyncio
    async def test_update_score_with_person(self, feedback, redis_mock):
        redis_mock.get.return_value = "0.5"
        await feedback._update_score("insight", 0.1, person="Max")
        # Global score + person score = 2 setex calls
        assert redis_mock.setex.call_count == 2

    @pytest.mark.asyncio
    async def test_update_score_without_person(self, feedback, redis_mock):
        redis_mock.get.return_value = "0.5"
        await feedback._update_score("insight", 0.1)
        # Nur global score = 1 setex call
        assert redis_mock.setex.call_count == 1

    @pytest.mark.asyncio
    async def test_get_person_score_default(self, feedback, redis_mock):
        redis_mock.get.return_value = None
        score = await feedback.get_person_score("insight", "Lisa")
        assert score == DEFAULT_SCORE

    @pytest.mark.asyncio
    async def test_get_person_score_stored(self, feedback, redis_mock):
        redis_mock.get.return_value = "0.72"
        score = await feedback.get_person_score("insight", "Lisa")
        assert score == 0.72

    @pytest.mark.asyncio
    async def test_get_person_score_no_person(self, feedback, redis_mock):
        score = await feedback.get_person_score("insight", "")
        assert score == DEFAULT_SCORE


# ============================================================
# Self-Optimization: Erweiterte Parameter (Feature 9d)
# ============================================================

class TestSelfOptimizationExtended:
    """Tests fuer erweiterte Self-Optimization."""

    def test_extended_parameter_paths(self):
        assert "insight_cooldown_hours" in _PARAMETER_PATHS
        assert "anticipation_min_confidence" in _PARAMETER_PATHS
        assert "feedback_base_cooldown" in _PARAMETER_PATHS
        assert "spontaneous_max_per_day" in _PARAMETER_PATHS

    def test_parameter_paths_valid(self):
        for param, path in _PARAMETER_PATHS.items():
            assert isinstance(path, list)
            assert len(path) >= 2

    @pytest.fixture
    def self_opt(self, redis_mock, ollama_mock):
        with patch("assistant.self_optimization.yaml_config", {
            "self_optimization": {
                "enabled": True,
                "approval_mode": "manual",
                "analysis_interval": "weekly",
                "max_proposals_per_cycle": 3,
                "model": "qwen3:14b",
                "parameter_bounds": {
                    "sarcasm_level": {"min": 1, "max": 5},
                    "insight_cooldown_hours": {"min": 2, "max": 8},
                },
            },
        }):
            versioning = MagicMock()
            so = SelfOptimization(ollama_mock, versioning)
            so._redis = redis_mock
            return so

    @pytest.mark.asyncio
    async def test_get_outcome_stats(self, self_opt):
        tracker = MagicMock()
        tracker.get_stats = AsyncMock(return_value={"set_light": {"score": 0.8}})
        stats = await self_opt._get_outcome_stats(tracker)
        assert "set_light" in stats

    @pytest.mark.asyncio
    async def test_get_quality_stats(self, self_opt):
        quality = MagicMock()
        quality.get_stats = AsyncMock(return_value={"device_command": {"score": 0.9}})
        stats = await self_opt._get_quality_stats(quality)
        assert "device_command" in stats

    @pytest.mark.asyncio
    async def test_get_correction_patterns(self, self_opt):
        memory = MagicMock()
        memory.get_correction_patterns = AsyncMock(return_value=[
            {"action": "set_light", "type": "room_confusion", "count": 5}
        ])
        patterns = await self_opt._get_correction_patterns(memory)
        assert len(patterns) == 1

    @pytest.mark.asyncio
    async def test_get_outcome_stats_none_tracker(self, self_opt):
        stats = await self_opt._get_outcome_stats(None)
        assert stats == {}


# ============================================================
# Personality: Learned Rules Section (Feature 7)
# ============================================================

class TestPersonalityLearnedRules:
    """Tests fuer build_learned_rules_section."""

    def test_empty_rules(self):
        result = PersonalityEngine.build_learned_rules_section([])
        assert result == ""

    def test_valid_rules(self):
        rules = [
            {"text": "Abends meint User Schlafzimmer", "confidence": 0.8},
            {"text": "Morgens bevorzugt Kueche", "confidence": 0.7},
        ]
        result = PersonalityEngine.build_learned_rules_section(rules)
        assert "GELERNTE PRAEFERENZEN" in result
        assert "Schlafzimmer" in result
        assert "Kueche" in result

    def test_low_confidence_filtered(self):
        rules = [
            {"text": "Unsichere Regel", "confidence": 0.3},
        ]
        result = PersonalityEngine.build_learned_rules_section(rules)
        assert result == ""

    def test_max_5_rules(self):
        rules = [
            {"text": f"Regel {i}", "confidence": 0.9}
            for i in range(10)
        ]
        result = PersonalityEngine.build_learned_rules_section(rules)
        # Should have header + 5 rules max
        lines = result.strip().split("\n")
        assert len(lines) <= 6  # 1 header + 5 rules

    def test_long_text_filtered(self):
        rules = [
            {"text": "x" * 250, "confidence": 0.9},  # Too long
        ]
        result = PersonalityEngine.build_learned_rules_section(rules)
        assert result == ""
