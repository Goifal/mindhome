"""
Tests fuer brain.py _extract_tool_calls_from_text()

Testet alle 4 JSON-Parsing-Muster:
  1. Standard: {"name": "func", "arguments": {...}}
  2. XML-Tags: <tool_call>{"name": "func", "arguments": {...}}</tool_call>
  3. Code-Block: `func_name` ... ```json {...} ```
  4. Bare JSON: {"entity_id": "light.x", "state": "on"}

Regressionstests fuer:
  - Ungueltige JSON-Antworten (kein Crash)
  - Domain-basierte Funktionszuordnung
  - Unbekannte Funktionsnamen werden abgelehnt
"""

import json
import re
import pytest


# ============================================================
# Isolierte Parsing-Funktionen (aus brain.py extrahiert)
# ============================================================

# Erlaubte Funktionen (Subset aus FunctionExecutor._ALLOWED_FUNCTIONS)
_ALLOWED_FUNCTIONS = {
    "set_light", "set_cover", "set_climate", "set_switch",
    "play_media", "set_media_player", "lock_door",
    "get_weather", "get_lights", "get_switches", "get_covers",
    "get_media", "get_climate", "get_entity_state",
    "get_house_status", "get_room_climate", "get_calendar_events",
    "send_notification", "play_sound", "activate_scene",
    "get_alarms", "set_wakeup_alarm", "cancel_alarm",
}

_ARG_KEY_TO_FUNC = {
    "brightness": "set_light",
    "color_temp": "set_light",
    "color": "set_light",
    "position": "set_cover",
    "temperature": "set_climate",
    "hvac_mode": "set_climate",
}

_DOMAIN_TO_FUNC = {
    "light.": "set_light", "switch.": "set_switch",
    "cover.": "set_cover", "climate.": "set_climate",
    "media_player.": "play_media", "lock.": "lock_door",
}


def extract_tool_calls(text: str) -> list[dict]:
    """Isolierte Version von _extract_tool_calls_from_text."""

    # Muster 1: Standard
    m = re.search(
        r'\{\s*"name"\s*:\s*"(\w+)"\s*,\s*"arguments"\s*:\s*(\{[^}]*\})\s*\}',
        text,
    )
    if m:
        try:
            args = json.loads(m.group(2))
            name = m.group(1)
            if name in _ALLOWED_FUNCTIONS:
                return [{"function": {"name": name, "arguments": args}}]
        except (json.JSONDecodeError, ValueError):
            pass

    # Muster 2: XML-Tags
    m = re.search(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(1))
            name = obj.get("name", "")
            args = obj.get("arguments", {})
            if isinstance(args, str):
                args = json.loads(args)
            if name in _ALLOWED_FUNCTIONS:
                return [{"function": {"name": name, "arguments": args}}]
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # Muster 3: Code-Block
    m_func = re.search(r'`(\w+)`', text)
    m_json = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m_func and m_json:
        func_name = m_func.group(1)
        if func_name in _ALLOWED_FUNCTIONS:
            try:
                args = json.loads(m_json.group(1))
                return [{"function": {"name": func_name, "arguments": args}}]
            except (json.JSONDecodeError, ValueError):
                pass

    # Muster 4: Bare JSON
    m_bare = re.search(r'\{[^{}]*"(?:entity_id|room|state|position|adjust)"[^{}]*\}', text)
    if m_bare:
        try:
            args = json.loads(m_bare.group(0))
            func_name = None

            eid = args.get("entity_id", "")
            for prefix, fname in _DOMAIN_TO_FUNC.items():
                if eid.startswith(prefix):
                    func_name = fname
                    break

            if not func_name:
                for key in args:
                    if key in _ARG_KEY_TO_FUNC:
                        func_name = _ARG_KEY_TO_FUNC[key]
                        break

            if not func_name and "state" in args and ("room" in args or "entity_id" in args):
                eid = args.get("entity_id", "")
                if eid.startswith("cover."):
                    func_name = "set_cover"
                elif eid.startswith("climate."):
                    func_name = "set_climate"
                elif eid.startswith("switch."):
                    func_name = "set_switch"
                elif eid.startswith("media_player."):
                    func_name = "set_media_player"
                else:
                    func_name = "set_light"

            if func_name and func_name in _ALLOWED_FUNCTIONS:
                return [{"function": {"name": func_name, "arguments": args}}]
        except (json.JSONDecodeError, ValueError):
            pass

    return []


# ============================================================
# Muster 1: Standard JSON
# ============================================================

class TestStandardJSON:
    """{"name": "func", "arguments": {...}}"""

    def test_set_light(self):
        text = '{"name": "set_light", "arguments": {"room": "wohnzimmer", "state": "on"}}'
        result = extract_tool_calls(text)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "set_light"
        assert result[0]["function"]["arguments"]["room"] == "wohnzimmer"

    def test_set_cover(self):
        text = '{"name": "set_cover", "arguments": {"room": "schlafzimmer", "position": 50}}'
        result = extract_tool_calls(text)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "set_cover"

    def test_with_surrounding_text(self):
        text = 'Ich werde das Licht einschalten. {"name": "set_light", "arguments": {"room": "kueche", "state": "on"}} Erledigt.'
        result = extract_tool_calls(text)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "set_light"

    def test_unknown_function_rejected(self):
        text = '{"name": "hack_system", "arguments": {"target": "admin"}}'
        result = extract_tool_calls(text)
        assert len(result) == 0

    def test_invalid_json_no_crash(self):
        text = '{"name": "set_light", "arguments": {INVALID}}'
        result = extract_tool_calls(text)
        assert len(result) == 0


# ============================================================
# Muster 2: XML-Tags
# ============================================================

class TestXMLTags:
    """<tool_call>{...}</tool_call>"""

    def test_basic_xml_tool_call(self):
        text = '<tool_call>{"name": "set_light", "arguments": {"room": "bad", "state": "off"}}</tool_call>'
        result = extract_tool_calls(text)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "set_light"

    def test_xml_with_string_arguments(self):
        """Arguments als JSON-String statt Object."""
        text = '<tool_call>{"name": "set_switch", "arguments": "{\\"room\\": \\"kueche\\", \\"state\\": \\"off\\"}"}</tool_call>'
        result = extract_tool_calls(text)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "set_switch"

    def test_xml_unknown_function(self):
        text = '<tool_call>{"name": "delete_everything", "arguments": {}}</tool_call>'
        result = extract_tool_calls(text)
        assert len(result) == 0


# ============================================================
# Muster 3: Code-Block
# ============================================================

class TestCodeBlock:
    """`func_name` ... ```json {...} ```"""

    def test_code_block_tool_call(self):
        text = 'Ich verwende `set_light` um das Licht zu schalten:\n```json\n{"room": "wohnzimmer", "state": "on"}\n```'
        result = extract_tool_calls(text)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "set_light"

    def test_code_block_unknown_function(self):
        text = '`unknown_func`\n```json\n{"key": "value"}\n```'
        result = extract_tool_calls(text)
        assert len(result) == 0

    def test_code_block_without_json_prefix(self):
        text = '`set_cover`\n```\n{"room": "wohnzimmer", "position": 100}\n```'
        result = extract_tool_calls(text)
        assert len(result) == 1


# ============================================================
# Muster 4: Bare JSON
# ============================================================

class TestBareJSON:
    """Bare JSON mit entity_id oder room+state."""

    def test_light_entity_id(self):
        text = '{"entity_id": "light.wohnzimmer", "state": "on"}'
        result = extract_tool_calls(text)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "set_light"

    def test_switch_entity_id(self):
        text = '{"entity_id": "switch.steckdose_kueche", "state": "off"}'
        result = extract_tool_calls(text)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "set_switch"

    def test_cover_entity_id(self):
        text = '{"entity_id": "cover.wohnzimmer", "position": 50}'
        result = extract_tool_calls(text)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "set_cover"

    def test_climate_entity_id(self):
        text = '{"entity_id": "climate.wohnzimmer", "temperature": 22}'
        result = extract_tool_calls(text)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "set_climate"

    def test_media_player_entity_id(self):
        text = '{"entity_id": "media_player.wohnzimmer", "state": "off"}'
        result = extract_tool_calls(text)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "play_media"

    def test_lock_entity_id(self):
        text = '{"entity_id": "lock.haustuer", "state": "locked"}'
        result = extract_tool_calls(text)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "lock_door"

    def test_room_state_default_light(self):
        """room + state ohne entity_id → Default: set_light."""
        text = '{"room": "wohnzimmer", "state": "on"}'
        result = extract_tool_calls(text)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "set_light"

    def test_brightness_key(self):
        """brightness Key → set_light."""
        text = '{"room": "wohnzimmer", "brightness": 50}'
        result = extract_tool_calls(text)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "set_light"

    def test_position_key(self):
        """position Key → set_cover."""
        text = '{"room": "wohnzimmer", "position": 100}'
        result = extract_tool_calls(text)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "set_cover"

    def test_invalid_bare_json_no_crash(self):
        text = '{"entity_id": "light.x", BROKEN}'
        result = extract_tool_calls(text)
        assert len(result) == 0


# ============================================================
# Edge Cases
# ============================================================

class TestToolCallEdgeCases:
    """Grenzfaelle und Fehlerfaelle."""

    def test_empty_string(self):
        assert extract_tool_calls("") == []

    def test_normal_text_no_json(self):
        assert extract_tool_calls("Das Licht ist jetzt an.") == []

    def test_partial_json(self):
        assert extract_tool_calls('{"name": "set_light"') == []

    def test_nested_json_no_crash(self):
        text = '{"name": "set_light", "arguments": {"room": "bad", "nested": {"deep": true}}}'
        # Nested JSON wird vom Regex nicht korrekt geparst (nur ein Level)
        # Aber es darf nicht crashen
        result = extract_tool_calls(text)
        # Kann leer sein weil nested {} das Regex stoert — Hauptsache kein Crash
        assert isinstance(result, list)
