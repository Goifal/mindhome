"""
Tests fuer function_calling.py: _is_safe_cover(), _ALLOWED_FUNCTIONS,
_CALL_SERVICE_ALLOWED_KEYS, und execute() Dispatch.
"""

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pydantic_settings = pytest.importorskip("pydantic_settings")
from assistant.function_calling import FunctionExecutor, get_assistant_tools


# ---------------------------------------------------------------
# _is_safe_cover() Tests
# ---------------------------------------------------------------


class TestIsSafeCover:
    """Sicherheitsfilter: Garagentore/Tore duerfen nicht gesteuert werden."""

    def _make_executor(self):
        ha = AsyncMock()
        executor = FunctionExecutor(ha)
        return executor

    @pytest.mark.asyncio
    async def test_shutter_is_safe(self):
        ex = self._make_executor()
        state = {"attributes": {"device_class": "shutter"}}
        assert await ex._is_safe_cover("cover.wohnzimmer", state) is True

    @pytest.mark.asyncio
    async def test_garage_door_class_blocked(self):
        ex = self._make_executor()
        state = {"attributes": {"device_class": "garage_door"}}
        assert await ex._is_safe_cover("cover.some_cover", state) is False

    @pytest.mark.asyncio
    async def test_gate_class_blocked(self):
        ex = self._make_executor()
        state = {"attributes": {"device_class": "gate"}}
        assert await ex._is_safe_cover("cover.einfahrt", state) is False

    @pytest.mark.asyncio
    async def test_door_class_blocked(self):
        ex = self._make_executor()
        state = {"attributes": {"device_class": "door"}}
        assert await ex._is_safe_cover("cover.haustuer", state) is False

    @pytest.mark.asyncio
    async def test_garage_in_entity_id_blocked(self):
        ex = self._make_executor()
        state = {"attributes": {}}
        assert await ex._is_safe_cover("cover.garage_haupttor", state) is False

    @pytest.mark.asyncio
    async def test_gate_in_entity_id_blocked(self):
        ex = self._make_executor()
        state = {"attributes": {}}
        assert await ex._is_safe_cover("cover.garden_gate", state) is False

    @pytest.mark.asyncio
    async def test_tor_word_boundary_blocked(self):
        """'tor' als eigenstaendiges Wort wird blockiert."""
        ex = self._make_executor()
        state = {"attributes": {}}
        assert await ex._is_safe_cover("cover.hof_tor", state) is False
        assert await ex._is_safe_cover("cover.einfahrts_tor", state) is False
        assert await ex._is_safe_cover("cover.tor_sued", state) is False

    @pytest.mark.asyncio
    async def test_motor_not_blocked(self):
        """'motor' im Entity-Name darf NICHT als 'tor' erkannt werden."""
        ex = self._make_executor()
        state = {"attributes": {}}
        assert await ex._is_safe_cover("cover.motor_shutter", state) is True

    @pytest.mark.asyncio
    async def test_monitor_not_blocked(self):
        ex = self._make_executor()
        state = {"attributes": {}}
        assert await ex._is_safe_cover("cover.monitor_cover", state) is True

    @pytest.mark.asyncio
    async def test_rotor_not_blocked(self):
        ex = self._make_executor()
        state = {"attributes": {}}
        assert await ex._is_safe_cover("cover.rotor_blind", state) is True

    @pytest.mark.asyncio
    async def test_empty_state_safe(self):
        ex = self._make_executor()
        assert await ex._is_safe_cover("cover.schlafzimmer", {}) is True

    @pytest.mark.asyncio
    async def test_disabled_cover_blocked(self):
        """Cover mit enabled=False in CoverConfig wird blockiert."""
        ex = self._make_executor()
        state = {"attributes": {}}
        mock_configs = {"cover.test_cover": {"enabled": False}}
        with patch("assistant.cover_config.load_cover_configs", return_value=mock_configs):
            assert await ex._is_safe_cover("cover.test_cover", state) is False

    @pytest.mark.asyncio
    async def test_cover_type_garage_in_config_blocked(self):
        """CoverConfig mit cover_type=garage_door wird blockiert."""
        ex = self._make_executor()
        state = {"attributes": {}}
        mock_configs = {"cover.harmless_name": {"cover_type": "garage_door", "enabled": True}}
        with patch("assistant.cover_config.load_cover_configs", return_value=mock_configs):
            assert await ex._is_safe_cover("cover.harmless_name", state) is False


# ---------------------------------------------------------------
# _ALLOWED_FUNCTIONS Whitelist Tests
# ---------------------------------------------------------------


class TestAllowedFunctions:
    """Nur explizit erlaubte Funktionen duerfen via execute() aufgerufen werden."""

    def test_core_functions_present(self):
        expected = {
            "set_light", "set_climate", "set_cover", "play_media",
            "call_service", "activate_scene", "send_notification",
            "lock_door", "set_wakeup_alarm", "broadcast",
        }
        for fn in expected:
            assert fn in FunctionExecutor._ALLOWED_FUNCTIONS, f"{fn} fehlt in Whitelist"

    def test_total_count_reasonable(self):
        """Whitelist sollte nicht leer und nicht uebertrieben gross sein."""
        count = len(FunctionExecutor._ALLOWED_FUNCTIONS)
        assert 20 <= count <= 60, f"Whitelist hat {count} Eintraege — pruefen!"

    def test_internal_methods_excluded(self):
        """Private/interne Methoden duerfen nicht in der Whitelist sein."""
        forbidden = [
            "_is_safe_cover", "_find_entity", "_find_speaker_in_room",
            "execute", "set_config_versioning", "__init__",
            "close", "_exec_set_light",  # Kein _exec_ Prefix!
        ]
        for fn in forbidden:
            assert fn not in FunctionExecutor._ALLOWED_FUNCTIONS, f"{fn} sollte nicht in Whitelist sein"

    @pytest.mark.asyncio
    async def test_execute_rejects_unknown_function(self):
        ha = AsyncMock()
        ex = FunctionExecutor(ha)
        result = await ex.execute("drop_database", {})
        assert result["success"] is False
        assert "Unbekannte" in result["message"]

    @pytest.mark.asyncio
    async def test_execute_rejects_private_method(self):
        ha = AsyncMock()
        ex = FunctionExecutor(ha)
        result = await ex.execute("_is_safe_cover", {})
        assert result["success"] is False


# ---------------------------------------------------------------
# _CALL_SERVICE_ALLOWED_KEYS Tests
# ---------------------------------------------------------------


class TestCallServiceWhitelist:
    """Nur erlaubte Keys werden an HA call_service weitergegeben."""

    def test_standard_keys_allowed(self):
        expected = {
            "brightness", "brightness_pct", "temperature",
            "position", "volume_level", "rgb_color",
        }
        for key in expected:
            assert key in FunctionExecutor._CALL_SERVICE_ALLOWED_KEYS, f"{key} fehlt"

    def test_dangerous_keys_not_in_whitelist(self):
        """Gefaehrliche Keys die nie an HA gehen duerfen."""
        forbidden = [
            "domain", "service", "entity_id",  # Meta-Keys, werden separat behandelt
            "password", "token", "api_key",
            "script", "command", "shell",
        ]
        for key in forbidden:
            assert key not in FunctionExecutor._CALL_SERVICE_ALLOWED_KEYS, f"{key} sollte nicht erlaubt sein"


# ---------------------------------------------------------------
# Tool-Definitionen Tests
# ---------------------------------------------------------------


class TestToolDefinitions:
    """Prueft dass alle Tools korrekt definiert sind."""

    def _get_tools(self):
        return get_assistant_tools()

    def _tool_names(self):
        return [t["function"]["name"] for t in self._get_tools()]

    def test_set_light_has_brighter_dimmer(self):
        """Relative Steuerung: state='brighter'/'dimmer' muss vorhanden sein."""
        tools = self._get_tools()
        light_tool = next(t for t in tools if t["function"]["name"] == "set_light")
        state_enum = light_tool["function"]["parameters"]["properties"]["state"]["enum"]
        assert "brighter" in state_enum
        assert "dimmer" in state_enum

    def test_set_climate_has_adjust(self):
        """Relative Steuerung: adjust='warmer'/'cooler' muss vorhanden sein."""
        tools = self._get_tools()
        climate_tool = next((t for t in tools if t["function"]["name"] == "set_climate"), None)
        if climate_tool:
            params = climate_tool["function"]["parameters"]
            # Im room_thermostat Modus gibt es adjust
            if "adjust" in params.get("properties", {}):
                adjust_enum = params["properties"]["adjust"]["enum"]
                assert "warmer" in adjust_enum
                assert "cooler" in adjust_enum

    def test_play_media_has_volume_up_down(self):
        """Relative Lautstaerke: volume_up/volume_down muss vorhanden sein."""
        tools = self._get_tools()
        media_tool = next(t for t in tools if t["function"]["name"] == "play_media")
        action_enum = media_tool["function"]["parameters"]["properties"]["action"]["enum"]
        assert "volume_up" in action_enum
        assert "volume_down" in action_enum

    def test_set_cover_has_adjust(self):
        """Relative Position: adjust='up'/'down' muss vorhanden sein."""
        tools = self._get_tools()
        cover_tool = next(t for t in tools if t["function"]["name"] == "set_cover")
        params = cover_tool["function"]["parameters"]
        assert "adjust" in params["properties"]
        adjust_enum = params["properties"]["adjust"]["enum"]
        assert "up" in adjust_enum
        assert "down" in adjust_enum

    def test_all_tools_have_required_fields(self):
        """Jedes Tool muss type, function.name, function.parameters haben."""
        for tool in self._get_tools():
            assert tool.get("type") == "function"
            func = tool.get("function", {})
            assert func.get("name"), f"Tool ohne Name: {tool}"
            assert func.get("parameters"), f"Tool {func.get('name')} ohne Parameters"

    def test_every_allowed_function_has_handler(self):
        """Jede Funktion in _ALLOWED_FUNCTIONS muss eine _exec_ Methode haben."""
        ha = AsyncMock()
        ex = FunctionExecutor(ha)
        for fn_name in FunctionExecutor._ALLOWED_FUNCTIONS:
            handler = getattr(ex, f"_exec_{fn_name}", None)
            assert handler is not None, f"_exec_{fn_name} fehlt fuer erlaubte Funktion '{fn_name}'"
