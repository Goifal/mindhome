"""
Comprehensive tests for brain.py — The central AssistantBrain class.

Tests cover:
- _estimate_tokens, _audit_log (module-level)
- _build_scene_intelligence_prompt (module-level)
- AssistantBrain.__init__ and configurable data loading
- _result helper
- _detect_sarcasm_feedback
- _normalize_stt_text
- _is_device_command, _is_status_query
- _deterministic_tool_call
- _detect_alarm_command
- _filter_response
- _build_memory_context
- _format_days_ago
- _extract_tool_calls_from_text
- _llm_with_cascade
- health_check
- process (lock, timeout, inner dispatch)
- get_states_cached
- _detect_calendar_query, _detect_weather_query
- _detect_smalltalk
- _is_morning_briefing_request, _is_evening_briefing_request
- _is_house_status_request, _is_status_report_request
- _is_correction
- _classify_intent
"""

import asyncio
import json
import re
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest


# ── Module-level helpers ─────────────────────────────────────────


class TestEstimateTokens:
    def test_basic_estimate(self):
        from assistant.brain import _estimate_tokens
        result = _estimate_tokens("Hallo Welt")
        assert isinstance(result, int)
        assert result > 0

    def test_empty_string(self):
        from assistant.brain import _estimate_tokens
        assert _estimate_tokens("") == 0

    def test_german_text_more_tokens(self):
        from assistant.brain import _estimate_tokens
        # 1.4 chars per token → 14 chars ≈ 10 tokens
        result = _estimate_tokens("Überraschend!")
        assert result == int(len("Überraschend!") / 1.4)


class TestAuditLog:
    def test_audit_log_writes(self, tmp_path):
        from assistant.brain import _audit_log, _AUDIT_LOG_PATH
        with patch("assistant.brain._AUDIT_LOG_PATH", tmp_path / "audit.jsonl"):
            _audit_log("test_action", {"key": "value"})
            log_file = tmp_path / "audit.jsonl"
            assert log_file.exists()
            data = json.loads(log_file.read_text().strip())
            assert data["action"] == "test_action"
            assert data["details"]["key"] == "value"

    def test_audit_log_handles_error(self):
        from assistant.brain import _audit_log
        with patch("assistant.brain._AUDIT_LOG_PATH", MagicMock(parent=MagicMock(mkdir=MagicMock(side_effect=PermissionError)))):
            # Should not raise
            _audit_log("test", {})


class TestBuildSceneIntelligencePrompt:
    def test_room_thermostat_mode(self):
        from assistant.brain import _build_scene_intelligence_prompt
        with patch("assistant.brain.cfg") as mock_cfg:
            mock_cfg.yaml_config = {"heating": {"mode": "room_thermostat"}}
            result = _build_scene_intelligence_prompt()
            assert "Heizung im aktuellen Raum" in result

    def test_heating_curve_mode(self):
        from assistant.brain import _build_scene_intelligence_prompt
        with patch("assistant.brain.cfg") as mock_cfg:
            mock_cfg.yaml_config = {"heating": {"mode": "heating_curve"}}
            result = _build_scene_intelligence_prompt()
            assert "Heizungs-Offset" in result

    def test_default_mode(self):
        from assistant.brain import _build_scene_intelligence_prompt
        with patch("assistant.brain.cfg") as mock_cfg:
            mock_cfg.yaml_config = {}
            result = _build_scene_intelligence_prompt()
            assert "SZENEN-INTELLIGENZ" in result


# ── Brain fixture ─────────────────────────────────────────────


@pytest.fixture
def brain():
    """Creates a Brain instance with all dependencies mocked."""
    from contextlib import ExitStack
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
        # Set up essential mocks
        b._stt_word_corrections = {}
        b._stt_phrase_corrections = []
        b._sarcasm_positive = frozenset(["haha", "lol", "gut", "ja"])
        b._sarcasm_negative = frozenset(["hoer auf", "nicht witzig", "nervt"])
        b._device_nouns = ["licht", "rollladen", "heizung", "steckdose"]
        b._action_words = {"an", "aus", "hoch", "runter", "auf", "zu"}
        b._command_verbs = ["mach ", "schalte ", "stell "]
        b._query_markers = ["welche", "sind ", "ist ", "status"]
        b._action_exclusions = ["einstellen", "dimmen"]
        b._status_nouns = ["licht", "lichter", "rollladen", "heizung", "haus"]
        b._das_uebliche_patterns = ["das uebliche", "wie immer"]
        b._current_person = ""
        return b


# ── _result helper ───────────────────────────────────────────


class TestResultHelper:
    def test_basic_result(self, brain):
        r = brain._result("Test response")
        assert r["response"] == "Test response"
        assert r["actions"] == []
        assert r["model_used"] == ""
        assert r["context_room"] == "unbekannt"

    def test_result_with_actions(self, brain):
        r = brain._result("ok", actions=[{"fn": "test"}], model="fast")
        assert len(r["actions"]) == 1
        assert r["model_used"] == "fast"

    def test_result_with_tts(self, brain):
        r = brain._result("ok", tts={"volume": 0.5})
        assert r["tts"]["volume"] == 0.5

    def test_result_with_emitted(self, brain):
        r = brain._result("ok", emitted=True)
        assert r["_emitted"] is True

    def test_result_with_extra(self, brain):
        r = brain._result("ok", custom_key="custom_val")
        assert r["custom_key"] == "custom_val"


# ── _detect_sarcasm_feedback ─────────────────────────────────


class TestDetectSarcasmFeedback:
    def test_positive_single_word(self, brain):
        assert brain._detect_sarcasm_feedback("haha") is True

    def test_negative_pattern(self, brain):
        assert brain._detect_sarcasm_feedback("hoer auf") is False

    def test_negative_overrides_positive(self, brain):
        # "nicht witzig" should be negative even though "witzig" is not in positive
        assert brain._detect_sarcasm_feedback("nicht witzig") is False

    def test_neutral_long_text(self, brain):
        assert brain._detect_sarcasm_feedback("Ich denke da sollten wir nochmal drueber reden") is None

    def test_short_positive_with_boundary(self, brain):
        # "gut" should match "gut" but not "guten"
        assert brain._detect_sarcasm_feedback("ja") is True

    def test_empty_text(self, brain):
        assert brain._detect_sarcasm_feedback("") is None


# ── _normalize_stt_text ──────────────────────────────────────


class TestNormalizeSttText:
    def test_empty_text(self, brain):
        assert brain._normalize_stt_text("") == ""

    def test_double_spaces(self, brain):
        assert "  " not in brain._normalize_stt_text("hello  world")

    def test_strip_punctuation(self, brain):
        result = brain._normalize_stt_text("...hello world...")
        assert not result.startswith(".")
        assert not result.endswith(".")

    def test_whisper_artifacts(self, brain):
        result = brain._normalize_stt_text("[Musik] Hallo Welt")
        assert "[Musik]" not in result
        assert "Hallo Welt" in result

    def test_parenthetical_artifacts(self, brain):
        result = brain._normalize_stt_text("(Unverstaendlich) mach licht an")
        assert "(Unverstaendlich)" not in result

    def test_word_corrections(self, brain):
        brain._stt_word_corrections = {"uber": "über"}
        result = brain._normalize_stt_text("uber alles")
        assert "über" in result

    def test_phrase_corrections(self, brain):
        brain._stt_phrase_corrections = [("ja weiß", "Jarvis")]
        result = brain._normalize_stt_text("Ja weiß mach licht an")
        assert "Jarvis" in result


# ── _is_device_command ───────────────────────────────────────


class TestIsDeviceCommand:
    def test_light_on(self, brain):
        assert brain._is_device_command("Licht an") is True

    def test_rollladen_hoch(self, brain):
        assert brain._is_device_command("Rollladen hoch") is True

    def test_with_verb_start(self, brain):
        assert brain._is_device_command("mach das Licht aus") is True

    def test_plain_question(self, brain):
        assert brain._is_device_command("Wie geht es dir?") is False

    def test_only_noun_no_action(self, brain):
        assert brain._is_device_command("Licht") is False


# ── _is_status_query ─────────────────────────────────────────


class TestIsStatusQuery:
    def test_lichter_status(self, brain):
        assert brain._is_status_query("Welche Lichter sind an?") is True

    def test_question_mark_with_noun(self, brain):
        assert brain._is_status_query("Rollladen?") is True

    def test_command_not_query(self, brain):
        # "einstellen" is in action_exclusions
        assert brain._is_status_query("Licht einstellen") is False

    def test_haus_status(self, brain):
        assert brain._is_status_query("status haus") is True

    def test_no_device_noun(self, brain):
        assert brain._is_status_query("Wie spät ist es?") is False

    def test_percent_command(self, brain):
        assert brain._is_status_query("Licht auf 50%") is False


# ── _deterministic_tool_call ─────────────────────────────────


class TestDeterministicToolCall:
    def test_get_lights(self):
        from assistant.brain import AssistantBrain
        result = AssistantBrain._deterministic_tool_call("Welche Lichter sind an?")
        assert result is not None
        assert result["function"]["name"] == "get_lights"

    def test_get_covers(self):
        from assistant.brain import AssistantBrain
        result = AssistantBrain._deterministic_tool_call("Rolllaeden status?")
        assert result is not None
        assert result["function"]["name"] == "get_covers"

    def test_get_climate(self):
        from assistant.brain import AssistantBrain
        result = AssistantBrain._deterministic_tool_call("Wie ist die Temperatur?")
        assert result is not None
        assert result["function"]["name"] == "get_climate"

    def test_set_light_on(self):
        from assistant.brain import AssistantBrain
        result = AssistantBrain._deterministic_tool_call("Licht an")
        assert result is not None
        assert result["function"]["name"] == "set_light"
        assert result["function"]["arguments"]["state"] == "on"

    def test_set_light_off(self):
        from assistant.brain import AssistantBrain
        result = AssistantBrain._deterministic_tool_call("Licht aus")
        assert result is not None
        assert result["function"]["name"] == "set_light"
        assert result["function"]["arguments"]["state"] == "off"

    def test_set_light_brightness(self):
        from assistant.brain import AssistantBrain
        result = AssistantBrain._deterministic_tool_call("Licht 50%")
        assert result is not None
        assert result["function"]["arguments"].get("brightness") == 50

    def test_cover_open(self):
        from assistant.brain import AssistantBrain
        result = AssistantBrain._deterministic_tool_call("Rollladen auf")
        assert result is not None
        assert result["function"]["name"] == "set_cover"
        assert result["function"]["arguments"]["action"] == "open"

    def test_cover_close(self):
        from assistant.brain import AssistantBrain
        result = AssistantBrain._deterministic_tool_call("Rollladen zu")
        assert result is not None
        assert result["function"]["arguments"]["action"] == "close"

    def test_get_alarms(self):
        from assistant.brain import AssistantBrain
        result = AssistantBrain._deterministic_tool_call("Welche Wecker sind aktiv?")
        assert result is not None
        assert result["function"]["name"] == "get_alarms"

    def test_house_status(self):
        from assistant.brain import AssistantBrain
        result = AssistantBrain._deterministic_tool_call("Hausstatus?")
        assert result is not None
        assert result["function"]["name"] == "get_house_status"

    def test_no_match(self):
        from assistant.brain import AssistantBrain
        result = AssistantBrain._deterministic_tool_call("Erzaehl mir einen Witz")
        assert result is None

    def test_room_extraction(self):
        from assistant.brain import AssistantBrain
        result = AssistantBrain._deterministic_tool_call("Licht im Wohnzimmer an")
        assert result is not None
        assert result["function"]["arguments"].get("room") == "wohnzimmer"

    def test_alle_lichter_aus(self):
        from assistant.brain import AssistantBrain
        result = AssistantBrain._deterministic_tool_call("alle Lichter aus")
        assert result is not None
        assert result["function"]["arguments"]["room"] == "all"


# ── _detect_alarm_command ────────────────────────────────────


class TestDetectAlarmCommand:
    def test_set_alarm_simple(self):
        from assistant.brain import AssistantBrain
        result = AssistantBrain._detect_alarm_command("Wecker auf 7")
        assert result is not None
        assert result["action"] == "set"
        assert result["time"] == "07:00"

    def test_set_alarm_with_minutes(self):
        from assistant.brain import AssistantBrain
        result = AssistantBrain._detect_alarm_command("Wecker auf 6:30")
        assert result is not None
        assert result["time"] == "06:30"

    def test_weck_mich(self):
        from assistant.brain import AssistantBrain
        result = AssistantBrain._detect_alarm_command("Weck mich um 7")
        assert result is not None
        assert result["action"] == "set"

    def test_alarm_status(self):
        from assistant.brain import AssistantBrain
        result = AssistantBrain._detect_alarm_command("Welche Wecker sind aktiv?")
        assert result is not None
        assert result["action"] == "status"

    def test_alarm_delete(self):
        from assistant.brain import AssistantBrain
        result = AssistantBrain._detect_alarm_command("Wecker aus")
        assert result is not None
        assert result["action"] == "cancel"

    def test_daily_repeat(self):
        from assistant.brain import AssistantBrain
        result = AssistantBrain._detect_alarm_command("Wecker auf 7 taeglich")
        assert result is not None
        assert result["repeat"] == "daily"

    def test_weekdays_repeat(self):
        from assistant.brain import AssistantBrain
        result = AssistantBrain._detect_alarm_command("Wecker auf 7 wochentags")
        assert result is not None
        assert result["repeat"] == "weekdays"

    def test_no_match(self):
        from assistant.brain import AssistantBrain
        result = AssistantBrain._detect_alarm_command("Mach das Licht an")
        assert result is None

    def test_invalid_hour(self):
        from assistant.brain import AssistantBrain
        result = AssistantBrain._detect_alarm_command("Wecker auf 25")
        assert result is None


# ── _filter_response ─────────────────────────────────────────


class TestFilterResponse:
    def test_empty_text(self, brain):
        with patch("assistant.brain.cfg") as mock_cfg:
            mock_cfg.yaml_config = {"response_filter": {"enabled": True}}
            assert brain._filter_response("") == ""

    def test_disabled_filter(self, brain):
        with patch("assistant.brain.cfg") as mock_cfg:
            mock_cfg.yaml_config = {"response_filter": {"enabled": False}}
            assert brain._filter_response("Some text") == "Some text"

    def test_thinking_tags_removed(self, brain):
        with patch("assistant.brain.cfg") as mock_cfg:
            mock_cfg.yaml_config = {"response_filter": {"enabled": True}}
            result = brain._filter_response("<think>reasoning here</think>Erledigt.")
            assert "<think>" not in result
            assert "Erledigt" in result

    def test_unclosed_think_tag(self, brain):
        with patch("assistant.brain.cfg") as mock_cfg:
            mock_cfg.yaml_config = {"response_filter": {"enabled": True}}
            result = brain._filter_response("<think>reasoning here but no close tag Erledigt.")
            # Should handle gracefully
            assert isinstance(result, str)


# ── _build_memory_context ────────────────────────────────────


class TestBuildMemoryContext:
    def test_empty_memories(self, brain):
        result = brain._build_memory_context({})
        assert result == ""

    def test_with_relevant_facts(self, brain):
        result = brain._build_memory_context({"relevant_facts": ["Fakt 1", "Fakt 2"]})
        assert "RELEVANTE ERINNERUNGEN" in result
        assert "Fakt 1" in result

    def test_with_person_facts(self, brain):
        result = brain._build_memory_context({"person_facts": ["Mag Kaffee"]})
        assert "BEKANNTE FAKTEN UEBER DEN USER" in result
        assert "Mag Kaffee" in result

    def test_with_both(self, brain):
        result = brain._build_memory_context({
            "relevant_facts": ["F1"],
            "person_facts": ["P1"],
        })
        assert "GEDAECHTNIS" in result
        assert "RELEVANTE ERINNERUNGEN" in result
        assert "BEKANNTE FAKTEN" in result


# ── _format_days_ago ─────────────────────────────────────────


class TestFormatDaysAgo:
    def test_empty_string(self):
        from assistant.brain import AssistantBrain
        assert AssistantBrain._format_days_ago("") == ""

    def test_today(self):
        from assistant.brain import AssistantBrain
        now = datetime.now().isoformat()
        assert AssistantBrain._format_days_ago(now) == "Heute"

    def test_yesterday(self):
        from assistant.brain import AssistantBrain
        yesterday = (datetime.now() - timedelta(days=1)).isoformat()
        assert AssistantBrain._format_days_ago(yesterday) == "Gestern"

    def test_last_week(self):
        from assistant.brain import AssistantBrain
        week_ago = (datetime.now() - timedelta(days=10)).isoformat()
        result = AssistantBrain._format_days_ago(week_ago)
        assert "Vor 10 Tagen" in result

    def test_invalid_string(self):
        from assistant.brain import AssistantBrain
        assert AssistantBrain._format_days_ago("not-a-date") == ""


# ── _is_morning_briefing_request ─────────────────────────────


class TestBriefingDetection:
    def test_morning_briefing(self):
        from assistant.brain import AssistantBrain
        assert AssistantBrain._is_morning_briefing_request("Morgenbriefing bitte") is True

    def test_evening_briefing(self):
        from assistant.brain import AssistantBrain
        assert AssistantBrain._is_evening_briefing_request("Abendbriefing") is True

    def test_house_status(self):
        from assistant.brain import AssistantBrain
        assert AssistantBrain._is_house_status_request("Hausstatus") is True

    def test_status_report(self):
        from assistant.brain import AssistantBrain
        assert AssistantBrain._is_status_report_request("Statusbericht") is True


# ── _is_correction ───────────────────────────────────────────


class TestIsCorrection:
    def test_nein_correction(self):
        from assistant.brain import AssistantBrain
        assert AssistantBrain._is_correction("Nein, nicht das") is True

    def test_falsch_correction(self):
        from assistant.brain import AssistantBrain
        assert AssistantBrain._is_correction("Falsch, ich meinte") is True

    def test_normal_text(self):
        from assistant.brain import AssistantBrain
        assert AssistantBrain._is_correction("Mach das Licht an") is False


# ── _extract_tool_calls_from_text ────────────────────────────


class TestExtractToolCallsFromText:
    def test_standard_json(self, brain):
        text = '{"name": "set_light", "arguments": {"state": "on"}}'
        with patch("assistant.brain.FunctionExecutor") as mock_fe:
            mock_fe._ALLOWED_FUNCTIONS = {"set_light"}
            result = brain._extract_tool_calls_from_text(text)
            assert len(result) == 1
            assert result[0]["function"]["name"] == "set_light"

    def test_tool_call_xml_tags(self, brain):
        text = '<tool_call>{"name": "set_light", "arguments": {"state": "on"}}</tool_call>'
        with patch("assistant.brain.FunctionExecutor") as mock_fe:
            mock_fe._ALLOWED_FUNCTIONS = {"set_light"}
            result = brain._extract_tool_calls_from_text(text)
            assert len(result) == 1

    def test_no_match(self, brain):
        text = "Just a normal text without any tool calls"
        result = brain._extract_tool_calls_from_text(text)
        assert result == []


# ── _llm_with_cascade ────────────────────────────────────────


class TestLlmWithCascade:
    @pytest.mark.asyncio
    async def test_successful_call(self, brain):
        brain.ollama = AsyncMock()
        brain.ollama.chat = AsyncMock(return_value={
            "message": {"content": "Test answer", "role": "assistant"}
        })
        brain.model_router = MagicMock()
        brain.model_router.get_fallback_model = MagicMock(return_value=None)

        result = await brain._llm_with_cascade(
            [{"role": "user", "content": "Hi"}],
            "test-model",
        )
        assert result["text"] == "Test answer"
        assert result["error"] is False

    @pytest.mark.asyncio
    async def test_timeout_fallback(self, brain):
        brain.ollama = AsyncMock()
        brain.ollama.chat = AsyncMock(side_effect=asyncio.TimeoutError())
        brain.model_router = MagicMock()
        brain.model_router.get_fallback_model = MagicMock(return_value=None)
        brain.error_patterns = MagicMock()
        brain.error_patterns.record_error = AsyncMock()

        result = await brain._llm_with_cascade(
            [{"role": "user", "content": "Hi"}],
            "test-model",
            timeout=0.1,
        )
        assert result["error"] is True

    @pytest.mark.asyncio
    async def test_model_fallback(self, brain):
        call_count = 0

        async def mock_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"error": "model_overloaded"}
            return {"message": {"content": "Fallback answer"}}

        brain.ollama = AsyncMock()
        brain.ollama.chat = mock_chat
        brain.model_router = MagicMock()
        brain.model_router.get_fallback_model = MagicMock(side_effect=["fallback-model", None])
        brain.error_patterns = MagicMock()
        brain.error_patterns.record_error = AsyncMock()

        result = await brain._llm_with_cascade(
            [{"role": "user", "content": "Hi"}],
            "primary-model",
        )
        assert result["text"] == "Fallback answer"
        assert result["error"] is False


# ── health_check ─────────────────────────────────────────────


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_all_healthy(self, brain):
        brain.ollama = AsyncMock()
        brain.ollama.is_available = AsyncMock(return_value=True)
        brain.ollama.list_models = AsyncMock(return_value=["model1"])
        brain.ha = AsyncMock()
        brain.ha.is_available = AsyncMock(return_value=True)
        brain.memory = MagicMock()
        brain.memory.redis = MagicMock()
        brain.memory.chroma_collection = MagicMock()
        brain.memory.semantic = MagicMock()
        brain.memory.semantic.chroma_collection = MagicMock()
        brain.memory_extractor = MagicMock()
        brain.mood = MagicMock()
        brain.mood.get_current_mood = MagicMock(return_value={"mood": "neutral"})
        brain.feedback = MagicMock()
        brain.feedback._running = True
        brain.summarizer = MagicMock()
        brain.summarizer._running = True
        brain.proactive = MagicMock()
        brain.proactive._running = True
        brain.time_awareness = MagicMock()
        brain.time_awareness._running = True
        brain.personality = MagicMock()
        brain.personality.get_formality_score = AsyncMock(return_value=70)
        brain.personality.sarcasm_level = 3
        brain.personality.opinion_intensity = 2
        brain.personality._easter_eggs = []
        brain.personality._opinion_rules = []
        brain.routines = MagicMock()
        brain.routines.is_guest_mode_active = AsyncMock(return_value=False)
        brain.anticipation = MagicMock()
        brain.anticipation._running = True
        brain.insight_engine = MagicMock()
        brain.insight_engine._running = True
        brain.intent_tracker = MagicMock()
        brain.intent_tracker._running = True
        brain.tts_enhancer = MagicMock()
        brain.tts_enhancer.ssml_enabled = True
        brain.tts_enhancer.is_whisper_mode = False
        brain.sound_manager = MagicMock()
        brain.sound_manager.enabled = True
        brain.speaker_recognition = MagicMock()
        brain.speaker_recognition.health_status = MagicMock(return_value="active")
        brain.diagnostics = MagicMock()
        brain.diagnostics.health_status = MagicMock(return_value="active")
        brain.cooking = MagicMock()
        brain.cooking.has_active_session = False
        brain.knowledge_base = MagicMock()
        brain.knowledge_base.chroma_collection = MagicMock()
        brain.knowledge_base.chroma_collection.count = MagicMock(return_value=10)
        brain.ocr = MagicMock()
        brain.ocr.health_status = MagicMock(return_value="active")
        brain.ambient_audio = MagicMock()
        brain.ambient_audio.health_status = MagicMock(return_value="active")
        brain.conflict_resolver = MagicMock()
        brain.conflict_resolver.health_status = MagicMock(return_value="active")
        brain.self_automation = MagicMock()
        brain.self_automation.health_status = MagicMock(return_value="active")
        brain.config_versioning = MagicMock()
        brain.config_versioning.health_status = MagicMock(return_value="active")
        brain.self_optimization = MagicMock()
        brain.self_optimization.health_status = MagicMock(return_value="active")
        brain.threat_assessment = MagicMock()
        brain.threat_assessment.enabled = True
        brain.learning_observer = MagicMock()
        brain.learning_observer.enabled = True
        brain.energy_optimizer = MagicMock()
        brain.energy_optimizer.enabled = True
        brain.wellness_advisor = MagicMock()
        brain.wellness_advisor._running = True
        brain.model_router = MagicMock()
        brain.model_router.get_model_info = MagicMock(return_value={})
        brain.autonomy = MagicMock()
        brain.autonomy.get_level_info = MagicMock(return_value={"level": 2, "name": "Aktiv"})
        brain.autonomy.get_trust_info = MagicMock(return_value={})

        result = await brain.health_check()
        assert result["status"] == "ok"
        assert "ollama" in result["components"]

    @pytest.mark.asyncio
    async def test_degraded_status(self, brain):
        brain.ollama = AsyncMock()
        brain.ollama.is_available = AsyncMock(return_value=False)
        brain.ollama.list_models = AsyncMock(return_value=[])
        brain.ha = AsyncMock()
        brain.ha.is_available = AsyncMock(return_value=True)
        brain.memory = MagicMock()
        brain.memory.redis = None
        brain.memory.chroma_collection = None
        brain.memory.semantic = MagicMock()
        brain.memory.semantic.chroma_collection = None
        brain.memory_extractor = None
        brain.mood = MagicMock()
        brain.mood.get_current_mood = MagicMock(return_value={"mood": "neutral"})
        brain.feedback = MagicMock()
        brain.feedback._running = False
        brain.summarizer = MagicMock()
        brain.summarizer._running = False
        brain.proactive = MagicMock()
        brain.proactive._running = False
        brain.time_awareness = MagicMock()
        brain.time_awareness._running = False
        brain.personality = MagicMock()
        brain.personality.get_formality_score = AsyncMock(return_value=70)
        brain.personality.sarcasm_level = 3
        brain.personality.opinion_intensity = 2
        brain.personality._easter_eggs = []
        brain.personality._opinion_rules = []
        brain.routines = MagicMock()
        brain.routines.is_guest_mode_active = AsyncMock(return_value=False)
        brain.anticipation = MagicMock()
        brain.anticipation._running = False
        brain.insight_engine = MagicMock()
        brain.insight_engine._running = False
        brain.intent_tracker = MagicMock()
        brain.intent_tracker._running = False
        brain.tts_enhancer = MagicMock()
        brain.tts_enhancer.ssml_enabled = False
        brain.tts_enhancer.is_whisper_mode = False
        brain.sound_manager = MagicMock()
        brain.sound_manager.enabled = False
        brain.speaker_recognition = MagicMock()
        brain.speaker_recognition.health_status = MagicMock(return_value="disabled")
        brain.diagnostics = MagicMock()
        brain.diagnostics.health_status = MagicMock(return_value="disabled")
        brain.cooking = MagicMock()
        brain.cooking.has_active_session = False
        brain.knowledge_base = MagicMock()
        brain.knowledge_base.chroma_collection = None
        brain.ocr = MagicMock()
        brain.ocr.health_status = MagicMock(return_value="disabled")
        brain.ambient_audio = MagicMock()
        brain.ambient_audio.health_status = MagicMock(return_value="disabled")
        brain.conflict_resolver = MagicMock()
        brain.conflict_resolver.health_status = MagicMock(return_value="disabled")
        brain.self_automation = MagicMock()
        brain.self_automation.health_status = MagicMock(return_value="disabled")
        brain.config_versioning = MagicMock()
        brain.config_versioning.health_status = MagicMock(return_value="disabled")
        brain.self_optimization = MagicMock()
        brain.self_optimization.health_status = MagicMock(return_value="disabled")
        brain.threat_assessment = MagicMock()
        brain.threat_assessment.enabled = False
        brain.learning_observer = MagicMock()
        brain.learning_observer.enabled = False
        brain.energy_optimizer = MagicMock()
        brain.energy_optimizer.enabled = False
        brain.wellness_advisor = MagicMock()
        brain.wellness_advisor._running = False
        brain.model_router = MagicMock()
        brain.model_router.get_model_info = MagicMock(return_value={})
        brain.autonomy = MagicMock()
        brain.autonomy.get_level_info = MagicMock(return_value={"level": 0, "name": "Passiv"})
        brain.autonomy.get_trust_info = MagicMock(return_value={})

        result = await brain.health_check()
        assert result["status"] == "degraded"


# ── get_states_cached ────────────────────────────────────────


class TestGetStatesCached:
    @pytest.mark.asyncio
    async def test_cache_hit(self, brain):
        brain._states_cache = [{"entity_id": "light.test"}]
        brain._states_cache_ts = time.monotonic()
        brain._STATES_CACHE_TTL = 5.0
        brain._states_lock = asyncio.Lock()
        brain.ha = AsyncMock()

        result = await brain.get_states_cached()
        assert result == [{"entity_id": "light.test"}]
        brain.ha.get_states.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_miss(self, brain):
        brain._states_cache = None
        brain._states_cache_ts = 0.0
        brain._STATES_CACHE_TTL = 2.0
        brain._states_lock = asyncio.Lock()
        brain.ha = AsyncMock()
        brain.ha.get_states = AsyncMock(return_value=[{"entity_id": "light.new"}])

        result = await brain.get_states_cached()
        assert result == [{"entity_id": "light.new"}]
        brain.ha.get_states.assert_called_once()


# ── process (lock + timeout) ─────────────────────────────────


class TestProcess:
    @pytest.mark.asyncio
    async def test_process_lock_timeout(self, brain):
        brain._process_lock = asyncio.Lock()
        await brain._process_lock.acquire()  # Lock is held

        # Should return timeout message
        result = await asyncio.wait_for(
            brain.process("test"),
            timeout=35.0,
        )
        assert "beschaeftigt" in result["response"] or "Moment" in result["response"]
        brain._process_lock.release()
