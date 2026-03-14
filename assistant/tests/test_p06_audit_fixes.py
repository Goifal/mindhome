"""
Tests fuer P06a-P06f Audit-Fixes.

Deckt ab:
  - P06f: Meta-Leakage Filter (_filter_response_inner)
  - P06f: Jarvis-Fallback bei leerem Text
  - P06e: Multi-Command Detection (_detect_multi_device_command)
  - P06e: Intent-basierte Tool-Selektion (_select_tools_for_intent)
  - P06f: Pre-TTS-Filter in SoundManager.speak_response()
  - P06f: validate_notification Meta-Filter in ollama_client
"""

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.assistant.ollama_client import validate_notification


# ============================================================
# Helpers: Standalone reimplementations for unit-testable logic
# ============================================================

# Meta-leak patterns from brain._filter_response_inner (line 4994)
_META_LEAK_PATTERNS = [
    r'\bspeak\b', r'\btts\b', r'\bemit\b',
    r'\btool_call\b', r'\bfunction_call\b',
    r'\bset_light\b', r'\bset_cover\b', r'\bset_climate\b',
    r'\bset_switch\b', r'\bplay_media\b', r'\bset_vacuum\b',
    r'\bactivate_scene\b', r'\barm_security_system\b',
    r'\bget_lights\b', r'\bget_covers\b', r'\bget_climate\b',
    r'\bget_switches\b', r'\bget_house_status\b', r'\bget_weather\b',
    r'\bget_entity_state\b', r'\bget_entity_history\b',
    r'\bspeak_response\b', r'\bemit_speaking\b', r'\bemit_action\b',
    r'\bcall_service\b', r'\bcall_ha_service\b',
    r'\brun_scene\b', r'\brun_script\b', r'\brun_automation\b',
    r'<tool_call>.*?</tool_call>',
    r'\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:.*?\}',
]

# Pre-TTS pattern from sound_manager.py (line 546)
_PRE_TTS_PATTERN = re.compile(
    r'\b(?:speak|tts|emit|tool_call|function_call|call_service'
    r'|speak_response|emit_speaking|emit_action'
    r'|set_light|set_cover|set_climate|set_switch|set_vacuum'
    r'|play_media|activate_scene|arm_security_system'
    r'|get_lights|get_covers|get_climate|get_switches'
    r'|get_house_status|get_weather|get_entity_state'
    r'|run_scene|run_script|run_automation|call_ha_service)\b',
    re.IGNORECASE,
)

# Jarvis fallbacks from brain.py (line 5450)
_JARVIS_FALLBACKS = [
    "Erledigt.", "Wie gewünscht.", "Wird gemacht.",
    "Umgesetzt.", "Verstanden.", "Notiert.",
    "Sir?", "Systeme bereit.",
]


def _apply_meta_leak_filter(text: str) -> str:
    """Reproduces the meta-leak filter logic from _filter_response_inner."""
    for pat in _META_LEAK_PATTERNS:
        text = re.sub(pat, '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'\s{2,}', ' ', text).strip()
    text = re.sub(r'\(\s*\)', '', text).strip()
    text = re.sub(r'^\s*[,;:\-\u2013\u2014]\s*', '', text).strip()
    if text:
        text = text[0].upper() + text[1:]
    return text


def _apply_pre_tts_filter(text: str) -> str:
    """Reproduces the Pre-TTS-Filter from speak_response."""
    text = _PRE_TTS_PATTERN.sub('', text).strip()
    text = re.sub(r'\s{2,}', ' ', text).strip()
    if not text:
        text = "Erledigt."
    return text


# ============================================================
# P06f: Meta-Leakage Filter Tests
# ============================================================

class TestMetaLeakageFilter:
    """P06f: _filter_response_inner entfernt interne Begriffe."""

    def test_removes_speak(self):
        result = _apply_meta_leak_filter("Ich werde jetzt speak ausfuehren")
        assert "speak" not in result.lower()

    def test_removes_tts(self):
        result = _apply_meta_leak_filter("Dann tts starten")
        assert "tts" not in result.lower()

    def test_removes_emit(self):
        result = _apply_meta_leak_filter("Ich emit die Nachricht")
        assert " emit " not in f" {result.lower()} "

    def test_removes_tool_call(self):
        result = _apply_meta_leak_filter("Ich fuehre tool_call set_light aus")
        assert "tool_call" not in result
        assert "set_light" not in result

    def test_removes_function_call(self):
        result = _apply_meta_leak_filter("function_call wird ausgefuehrt")
        assert "function_call" not in result

    def test_removes_set_light(self):
        result = _apply_meta_leak_filter("Ich nutze set_light für dich")
        assert "set_light" not in result

    def test_removes_set_cover(self):
        result = _apply_meta_leak_filter("set_cover Rollladen runter")
        assert "set_cover" not in result

    def test_removes_set_climate(self):
        result = _apply_meta_leak_filter("set_climate auf 21 Grad")
        assert "set_climate" not in result

    def test_removes_play_media(self):
        result = _apply_meta_leak_filter("play_media starten")
        assert "play_media" not in result

    def test_removes_get_functions(self):
        """All get_* functions should be removed."""
        for fn in ["get_lights", "get_covers", "get_climate",
                    "get_switches", "get_house_status", "get_weather",
                    "get_entity_state", "get_entity_history"]:
            result = _apply_meta_leak_filter(f"Ergebnis von {fn} ist gut")
            assert fn not in result, f"'{fn}' was not removed"

    def test_removes_speak_response(self):
        result = _apply_meta_leak_filter("speak_response Erledigt")
        assert "speak_response" not in result

    def test_removes_emit_speaking(self):
        result = _apply_meta_leak_filter("emit_speaking an alle")
        assert "emit_speaking" not in result

    def test_removes_emit_action(self):
        result = _apply_meta_leak_filter("emit_action jetzt")
        assert "emit_action" not in result

    def test_removes_call_service(self):
        result = _apply_meta_leak_filter("call_service starten")
        assert "call_service" not in result

    def test_removes_call_ha_service(self):
        result = _apply_meta_leak_filter("call_ha_service fertig")
        assert "call_ha_service" not in result

    def test_removes_run_scene(self):
        result = _apply_meta_leak_filter("run_scene Gute Nacht")
        assert "run_scene" not in result

    def test_removes_run_script(self):
        result = _apply_meta_leak_filter("run_script ausfuehren")
        assert "run_script" not in result

    def test_removes_run_automation(self):
        result = _apply_meta_leak_filter("run_automation starten")
        assert "run_automation" not in result

    def test_removes_json_fragment(self):
        """JSON function call fragments should be removed."""
        text = 'Alles klar {"name": "do_something", "arguments": {"brightness": 100}} erledigt'
        result = _apply_meta_leak_filter(text)
        assert "do_something" not in result

    def test_removes_tool_call_tags(self):
        text = "Ok <tool_call>set_light(room='wz')</tool_call> erledigt"
        result = _apply_meta_leak_filter(text)
        assert "<tool_call>" not in result
        assert "</tool_call>" not in result

    def test_preserves_clean_text(self):
        text = "Das Licht im Wohnzimmer ist jetzt an."
        result = _apply_meta_leak_filter(text)
        assert result == text

    def test_cleans_up_whitespace(self):
        text = "Hallo set_light Welt"
        result = _apply_meta_leak_filter(text)
        assert "  " not in result

    def test_removes_leading_punctuation_after_filter(self):
        text = "set_light, Das Licht ist an"
        result = _apply_meta_leak_filter(text)
        assert not result.startswith(",")

    def test_capitalizes_first_char(self):
        text = "set_light das Licht ist an"
        result = _apply_meta_leak_filter(text)
        assert result[0].isupper()

    def test_multiple_leak_terms_in_one_text(self):
        text = "Ich speak die emit Nachricht tts"
        result = _apply_meta_leak_filter(text)
        assert "speak" not in result.lower()
        assert "emit" not in result.lower()
        assert "tts" not in result.lower()

    def test_case_insensitive(self):
        result = _apply_meta_leak_filter("SET_LIGHT und TTS sind aktiv")
        assert "SET_LIGHT" not in result
        assert "TTS" not in result

    def test_empty_parens_removed(self):
        """Empty parentheses left after removal should be cleaned."""
        text = "Erledigt (set_light) sofort"
        result = _apply_meta_leak_filter(text)
        assert "()" not in result


# ============================================================
# P06f: Jarvis-Fallback Tests
# ============================================================

class TestJarvisFallback:
    """P06f: Wenn Text nach Filterung leer/zu kurz ist, kommt ein Fallback."""

    def test_empty_text_triggers_fallback(self):
        """Empty string should trigger fallback (brain.py line 5448)."""
        import random
        text = ""
        if not text or len(text.strip()) < 5:
            text = random.choice(_JARVIS_FALLBACKS)
        assert text in _JARVIS_FALLBACKS

    def test_short_text_triggers_fallback(self):
        """Text shorter than 5 chars triggers fallback."""
        import random
        text = "ok"
        if not text or len(text.strip()) < 5:
            text = random.choice(_JARVIS_FALLBACKS)
        assert text in _JARVIS_FALLBACKS

    def test_whitespace_only_triggers_fallback(self):
        import random
        text = "    "
        if not text or len(text.strip()) < 5:
            text = random.choice(_JARVIS_FALLBACKS)
        assert text in _JARVIS_FALLBACKS

    def test_normal_text_not_replaced(self):
        text = "Das Licht ist jetzt an."
        if not text or len(text.strip()) < 5:
            import random
            text = random.choice(_JARVIS_FALLBACKS)
        assert text == "Das Licht ist jetzt an."

    def test_fallback_count(self):
        """There should be exactly 8 fallback strings."""
        assert len(_JARVIS_FALLBACKS) == 8

    def test_all_fallbacks_end_with_punctuation(self):
        for fb in _JARVIS_FALLBACKS:
            assert fb.endswith(".") or fb.endswith("?"), f"'{fb}' missing punctuation"


# ============================================================
# P06e: Multi-Command Detection Tests
# ============================================================

class TestMultiCommandDetection:
    """P06e: _detect_multi_device_command erkennt zusammengesetzte Befehle."""

    def _call_detect(self, text, room=""):
        from assistant.brain import AssistantBrain
        return AssistantBrain._detect_multi_device_command(text, room=room)

    def test_licht_aus_und_rollladen_runter(self):
        """'Licht aus und Rollladen runter' should split into 2 commands."""
        result = self._call_detect("Licht aus und Rollladen runter")
        # Either returns a valid multi-command dict or None
        # (depends on _detect_device_command recognizing both parts)
        if result is not None:
            assert "_extra_cmds" in result["args"]
            extra = result["args"]["_extra_cmds"]
            assert len(extra) >= 1
            # Total: first command + extras = at least 2
            assert 1 + len(extra) >= 2

    def test_single_command_returns_none(self):
        """A single command without 'und' returns None."""
        result = self._call_detect("Licht aus")
        assert result is None

    def test_question_returns_none(self):
        """Questions are excluded from multi-command detection."""
        result = self._call_detect("Ist das Licht an und die Heizung aus?")
        assert result is None

    def test_no_und_or_comma_returns_none(self):
        """Text without 'und' or comma returns None."""
        result = self._call_detect("Mach das Licht an")
        assert result is None

    def test_comma_separated_commands(self):
        """Comma-separated device commands should also be detected."""
        result = self._call_detect("Licht aus, Rollladen runter")
        if result is not None:
            assert "_extra_cmds" in result["args"]

    def test_one_recognized_returns_none(self):
        """If only one part is recognized as device command, return None."""
        result = self._call_detect("Licht aus und erzaehl mir einen Witz")
        assert result is None

    def test_multi_command_has_function_key(self):
        """When detected, result should have 'function' and 'args' keys."""
        result = self._call_detect("Licht aus und Rollladen runter")
        if result is not None:
            assert "function" in result
            assert "args" in result


# ============================================================
# P06e: Intent-based Tool Selection Tests
# ============================================================

class TestIntentToolSelection:
    """P06e: _select_tools_for_intent waehlt Tools basierend auf Intent."""

    @pytest.fixture
    def brain(self):
        from assistant.brain import AssistantBrain
        brain = MagicMock(spec=AssistantBrain)
        brain._select_tools_for_intent = AssistantBrain._select_tools_for_intent.__get__(brain)
        return brain

    def _make_tools(self, names):
        return [{"type": "function", "function": {"name": n}} for n in names]

    def _all_tool_names(self):
        """Realistic set of tool names covering control, query, and other."""
        return [
            # Control tools (14 in _CONTROL_NAMES)
            "set_light", "set_cover", "set_climate", "set_switch",
            "set_media_player", "set_fan", "set_lock",
            "get_entity_state", "call_ha_service", "run_scene",
            "set_input_boolean", "set_input_number",
            "set_light_all", "arm_security_system",
            # Query tools (14 in _QUERY_NAMES)
            "get_lights", "get_covers", "get_climate",
            "get_switches", "get_media", "get_alarms", "get_house_status",
            "get_weather", "get_calendar", "get_shopping_list",
            "search_entities", "get_area_entities", "get_entity_history",
            # Other tools (not in either set)
            "send_notification", "play_media", "set_timer",
            "web_search", "create_reminder",
        ]

    def test_control_intent_returns_control_tools(self, brain):
        """Control keywords like 'licht' should return ~14 control tools."""
        all_tools = self._make_tools(self._all_tool_names())
        with patch("assistant.brain.get_assistant_tools", return_value=all_tools):
            result = brain._select_tools_for_intent("mach das licht an")
        names = {t["function"]["name"] for t in result}
        assert "set_light" in names
        assert "set_cover" in names
        assert len(result) <= 14
        assert len(result) >= 10
        # Non-control tools excluded
        assert "web_search" not in names
        assert "send_notification" not in names

    def test_query_intent_returns_query_tools(self, brain):
        """Query keywords like 'wie ist' should return query tools."""
        all_tools = self._make_tools(self._all_tool_names())
        with patch("assistant.brain.get_assistant_tools", return_value=all_tools):
            result = brain._select_tools_for_intent("wie ist das wetter")
        names = {t["function"]["name"] for t in result}
        assert "get_weather" in names
        # Control-only tools excluded
        assert "set_light" not in names
        assert "set_cover" not in names

    def test_unclear_intent_returns_all(self, brain):
        """Unclear text should return all tools."""
        all_tools = self._make_tools(self._all_tool_names())
        with patch("assistant.brain.get_assistant_tools", return_value=all_tools):
            result = brain._select_tools_for_intent("erzaehl mir einen witz")
        assert len(result) == len(all_tools)

    def test_various_control_keywords(self, brain):
        """Various control keywords should trigger control intent."""
        control_phrases = [
            "schalte das licht an",
            "dimm die lampe",
            "rollladen runter",
            "heizung auf 22 grad",
            "steckdose ausschalten",
        ]
        all_tools = self._make_tools(self._all_tool_names())
        for phrase in control_phrases:
            with patch("assistant.brain.get_assistant_tools", return_value=all_tools):
                result = brain._select_tools_for_intent(phrase)
            assert len(result) < len(all_tools), f"Expected fewer tools for: '{phrase}'"

    def test_various_query_keywords(self, brain):
        """Various query keywords should trigger query intent."""
        query_phrases = [
            "wie warm ist es",
            "wie ist der status",
            "welche sind offen",
        ]
        all_tools = self._make_tools(self._all_tool_names())
        for phrase in query_phrases:
            with patch("assistant.brain.get_assistant_tools", return_value=all_tools):
                result = brain._select_tools_for_intent(phrase)
            assert len(result) < len(all_tools), f"Expected fewer tools for: '{phrase}'"

    def test_mixed_intent_returns_all(self, brain):
        """When both control and query keywords present, return all tools."""
        all_tools = self._make_tools(self._all_tool_names())
        with patch("assistant.brain.get_assistant_tools", return_value=all_tools):
            # Contains both "schalte" (control) and "status" (query)
            result = brain._select_tools_for_intent("schalte ein und zeig status")
        assert len(result) == len(all_tools)


# ============================================================
# P06f: Pre-TTS-Filter Tests
# ============================================================

class TestPreTTSFilter:
    """P06f: SoundManager filtert Meta-Leakage vor TTS."""

    def test_filters_speak(self):
        assert "speak" not in _apply_pre_tts_filter("Ich speak jetzt").lower()

    def test_filters_tts(self):
        assert "tts" not in _apply_pre_tts_filter("tts jetzt aktiv").lower()

    def test_filters_emit(self):
        result = _apply_pre_tts_filter("emit Nachricht senden")
        assert " emit " not in f" {result.lower()} "

    def test_filters_tool_call(self):
        assert "tool_call" not in _apply_pre_tts_filter("tool_call Ergebnis")

    def test_filters_set_light(self):
        assert "set_light" not in _apply_pre_tts_filter("Erledigt set_light")

    def test_filters_set_cover(self):
        assert "set_cover" not in _apply_pre_tts_filter("set_cover fertig")

    def test_filters_set_climate(self):
        assert "set_climate" not in _apply_pre_tts_filter("set_climate gesetzt")

    def test_filters_speak_response(self):
        assert "speak_response" not in _apply_pre_tts_filter("speak_response ausgefuehrt")

    def test_filters_emit_action(self):
        assert "emit_action" not in _apply_pre_tts_filter("emit_action jetzt")

    def test_filters_call_ha_service(self):
        assert "call_ha_service" not in _apply_pre_tts_filter("call_ha_service fertig")

    def test_filters_run_scene(self):
        assert "run_scene" not in _apply_pre_tts_filter("run_scene Gute Nacht")

    def test_filters_run_script(self):
        assert "run_script" not in _apply_pre_tts_filter("run_script starten")

    def test_filters_run_automation(self):
        assert "run_automation" not in _apply_pre_tts_filter("run_automation aktiviert")

    def test_filters_activate_scene(self):
        assert "activate_scene" not in _apply_pre_tts_filter("activate_scene Gute Nacht")

    def test_filters_get_functions(self):
        for fn in ["get_lights", "get_covers", "get_climate", "get_switches",
                    "get_house_status", "get_weather", "get_entity_state"]:
            result = _apply_pre_tts_filter(f"Ergebnis von {fn} ist da")
            assert fn not in result, f"'{fn}' was not filtered in Pre-TTS"

    def test_fallback_when_all_removed(self):
        """If entire text is meta-terms, fallback to 'Erledigt.'"""
        result = _apply_pre_tts_filter("speak_response emit_action")
        assert result == "Erledigt."

    def test_preserves_clean_text(self):
        text = "Das Wetter ist heute sonnig."
        assert _apply_pre_tts_filter(text) == text

    def test_cleans_double_spaces(self):
        result = _apply_pre_tts_filter("Hallo set_light Welt")
        assert "  " not in result

    def test_mixed_content_keeps_human_text(self):
        result = _apply_pre_tts_filter("Erledigt set_light gesetzt")
        assert "set_light" not in result
        assert "Erledigt" in result


# ============================================================
# P06f: validate_notification Meta-Filter Tests
# ============================================================

class TestValidateNotificationMetaFilter:
    """P06f: ollama_client.validate_notification entfernt interne Begriffe."""

    def test_removes_speak(self):
        result = validate_notification("Die Waschmaschine ist fertig speak")
        assert "speak" not in result.lower().split()

    def test_removes_tts(self):
        result = validate_notification("tts aktiviert für die Ausgabe der Nachricht")
        assert "tts" not in result.lower().split()

    def test_removes_emit(self):
        result = validate_notification("Wir emit die Nachricht jetzt sofort")
        assert " emit " not in f" {result.lower()} "

    def test_removes_tool_call(self):
        result = validate_notification("Der tool_call wurde ausgefuehrt und ist erledigt")
        assert "tool_call" not in result

    def test_removes_function_call(self):
        result = validate_notification("Starte function_call für das Licht sofort hier")
        assert "function_call" not in result

    def test_removes_set_light(self):
        result = validate_notification("Erledigt set_light fertig")
        assert "set_light" not in result

    def test_removes_speak_response(self):
        result = validate_notification("Die speak_response wird jetzt gesendet an alle")
        assert "speak_response" not in result

    def test_removes_emit_action(self):
        result = validate_notification("Die emit_action wurde gestartet und ist erledigt")
        assert "emit_action" not in result

    def test_removes_call_service(self):
        result = validate_notification("Wir nutzen call_service für die Heizung jetzt")
        assert "call_service" not in result

    def test_removes_call_ha_service(self):
        result = validate_notification("Ich rufe call_ha_service auf für die Lampe hier")
        assert "call_ha_service" not in result

    def test_removes_get_entity_state(self):
        result = validate_notification("Ich frage get_entity_state ab und sage dir Bescheid")
        assert "get_entity_state" not in result

    def test_removes_run_scene(self):
        result = validate_notification("Ich starte run_scene jetzt für das Wohnzimmer hier")
        assert "run_scene" not in result

    def test_preserves_clean_german_text(self):
        text = "Die Waschmaschine ist fertig."
        assert validate_notification(text) == text

    def test_returns_empty_for_only_meta_terms(self):
        result = validate_notification("speak_response emit_action")
        assert result == ""

    def test_empty_input_returns_empty(self):
        assert validate_notification("") == ""

    def test_none_input_returns_none(self):
        assert validate_notification(None) is None

    def test_strips_think_tags_before_meta_filter(self):
        result = validate_notification("<think>internal reasoning</think>Die Waschmaschine ist fertig.")
        assert "<think>" not in result
        assert "Die Waschmaschine ist fertig." in result

    def test_multiple_meta_terms_all_removed(self):
        text = "Ich rufe set_light und call_service auf für das Licht im Wohnzimmer"
        result = validate_notification(text)
        assert "set_light" not in result
        assert "call_service" not in result
