"""
Tests for per-person last-action tracking (Cross-User-Leakage fix).

Verifies that _last_executed_actions is scoped per person with TTL,
preventing Person A's action from being referenced by Person B.
"""

import time
from contextlib import ExitStack
from unittest.mock import patch

import pytest


@pytest.fixture
def brain():
    """Creates a Brain instance with all dependencies mocked."""
    _BRAIN_PATCHES = [
        "HomeAssistantClient", "OllamaClient", "ContextBuilder", "ModelRouter",
        "PreClassifier", "PersonalityEngine", "FunctionExecutor", "FunctionValidator",
        "MemoryManager", "AutonomyManager", "FeedbackTracker", "ActivityEngine",
        "FollowMeEngine", "LightEngine", "ProactiveManager", "DailySummarizer",
        "MoodDetector", "ActionPlanner", "TimeAwareness", "RoutineEngine",
        "AnticipationEngine", "IntentTracker", "TTSEnhancer", "SoundManager",
        "SpeakerRecognition", "DiagnosticsEngine", "OCREngine",
        "AmbientAudioClassifier", "ConflictResolver", "HealthMonitor",
        "InventoryManager", "SmartShopping", "ConversationMemory", "MultiRoomAudio",
        "DeviceHealthMonitor", "InsightEngine", "SelfAutomation", "ConfigVersioning",
        "SelfOptimization", "CookingAssistant", "RepairPlanner", "WorkshopGenerator",
        "WorkshopLibrary", "KnowledgeBase", "RecipeStore", "TimerManager",
        "CameraManager", "ConditionalCommands", "EnergyOptimizer", "WebSearch",
        "ThreatAssessment", "LearningObserver", "WellnessAdvisor",
        "ProactiveSequencePlanner", "SeasonalInsightEngine", "CalendarIntelligence",
        "ExplainabilityEngine", "LearningTransfer", "DialogueStateManager",
        "ClimateModel", "PredictiveMaintenance", "SituationModel", "ProtocolEngine",
        "SpontaneousObserver", "MusicDJ", "VisitorManager", "OutcomeTracker",
        "CorrectionMemory", "ResponseQualityTracker", "ErrorPatternTracker",
        "SelfReport", "AdaptiveThresholds", "TaskRegistry",
    ]
    with ExitStack() as stack:
        for name in _BRAIN_PATCHES:
            stack.enter_context(patch(f"assistant.brain.{name}"))
        mock_cfg = stack.enter_context(patch("assistant.brain.cfg"))
        mock_cfg.yaml_config = {}
        from assistant.brain import AssistantBrain
        b = AssistantBrain()
        b._stt_word_corrections = {}
        b._stt_phrase_corrections = []
        b._sarcasm_positive = frozenset()
        b._sarcasm_negative = frozenset()
        b._device_nouns = []
        b._action_words = set()
        b._command_verbs = []
        b._query_markers = []
        b._action_exclusions = []
        b._status_nouns = []
        b._das_uebliche_patterns = []
        b._current_person = ""
        return b


class TestPerPersonActionTracking:
    """Verify per-person scoping of _last_executed_actions."""

    def test_set_and_get_action(self, brain):
        """Basic set/get for a single person."""
        brain._set_last_action("set_light", {"room": "wohnzimmer", "state": "on"}, "julia")
        action, args = brain._get_last_action("julia")
        assert action == "set_light"
        assert args["room"] == "wohnzimmer"

    def test_different_persons_isolated(self, brain):
        """Actions are isolated between persons."""
        brain._set_last_action("set_light", {"room": "wohnzimmer"}, "julia")
        brain._set_last_action("set_cover", {"room": "schlafzimmer"}, "tobias")

        action_j, args_j = brain._get_last_action("julia")
        action_t, args_t = brain._get_last_action("tobias")

        assert action_j == "set_light"
        assert args_j["room"] == "wohnzimmer"
        assert action_t == "set_cover"
        assert args_t["room"] == "schlafzimmer"

    def test_no_cross_user_leakage(self, brain):
        """Person B should NOT see Person A's action."""
        brain._set_last_action("set_light", {"room": "buero"}, "julia")
        action, args = brain._get_last_action("tobias")
        assert action == ""
        assert args == {}

    def test_ttl_expiry(self, brain):
        """Actions expire after TTL (5 minutes)."""
        brain._set_last_action("set_light", {"room": "wohnzimmer"}, "julia")

        # Manipulate timestamp to simulate TTL expiry
        key = "julia"
        action, args, _ = brain._last_executed_actions[key]
        brain._last_executed_actions[key] = (action, args, time.monotonic() - 301)

        result_action, result_args = brain._get_last_action("julia")
        assert result_action == ""
        assert result_args == {}
        # Entry should be cleaned up
        assert key not in brain._last_executed_actions

    def test_clear_action(self, brain):
        """Setting empty action clears the entry."""
        brain._set_last_action("set_light", {"room": "wohnzimmer"}, "julia")
        brain._set_last_action("", {}, "julia")
        action, args = brain._get_last_action("julia")
        assert action == ""

    def test_case_insensitive_person(self, brain):
        """Person keys are case-insensitive."""
        brain._set_last_action("set_light", {"room": "wohnzimmer"}, "Julia")
        action, _ = brain._get_last_action("julia")
        assert action == "set_light"

    def test_default_person(self, brain):
        """Empty person defaults to 'user'."""
        brain._set_last_action("set_light", {"room": "wohnzimmer"}, "")
        action, _ = brain._get_last_action("")
        assert action == "set_light"
        action2, _ = brain._get_last_action("user")
        assert action2 == "set_light"

    def test_args_are_copied(self, brain):
        """Args dict should be a copy, not a reference."""
        original_args = {"room": "wohnzimmer", "state": "on"}
        brain._set_last_action("set_light", original_args, "julia")
        original_args["room"] = "manipulated"  # Mutate original
        _, stored_args = brain._get_last_action("julia")
        assert stored_args["room"] == "wohnzimmer"  # Should be original value
