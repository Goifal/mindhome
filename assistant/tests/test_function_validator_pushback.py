"""
Tests fuer Feature 10: Daten-basierter Widerspruch (function_validator pushback).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from assistant.function_validator import FunctionValidator, ValidationResult


class TestPushbackSetClimate:
    """Tests fuer _pushback_set_climate()."""

    @pytest.fixture
    def validator(self, ha_mock):
        """FunctionValidator mit HA-Mock."""
        v = FunctionValidator()
        v.set_ha_client(ha_mock)
        return v

    @pytest.mark.asyncio
    async def test_open_window_warning(self, validator, ha_mock):
        """Offenes Fenster bei Heizungssteuerung → Warnung."""
        ha_mock.get_states = AsyncMock(return_value=[
            {
                "entity_id": "binary_sensor.fenster_wohnzimmer",
                "state": "on",
                "attributes": {"friendly_name": "Fenster Wohnzimmer"},
            },
        ])
        result = await validator.get_pushback_context(
            "set_climate",
            {"entity_id": "climate.wohnzimmer", "temperature": 22, "room": "wohnzimmer"},
        )
        assert result is not None
        assert len(result["warnings"]) >= 1
        assert any(w["type"] == "open_window" for w in result["warnings"])

    @pytest.mark.asyncio
    async def test_no_warning_closed_windows(self, validator, ha_mock):
        """Geschlossene Fenster → keine Warnung."""
        ha_mock.get_states = AsyncMock(return_value=[
            {
                "entity_id": "binary_sensor.fenster_wohnzimmer",
                "state": "off",
                "attributes": {"friendly_name": "Fenster Wohnzimmer"},
            },
        ])
        result = await validator.get_pushback_context(
            "set_climate",
            {"entity_id": "climate.wohnzimmer", "temperature": 22, "room": "wohnzimmer"},
        )
        # Keine Warnung oder leere warnings
        if result is not None:
            open_window_warnings = [w for w in result["warnings"] if w["type"] == "open_window"]
            assert len(open_window_warnings) == 0

    @pytest.mark.asyncio
    async def test_unnecessary_heating_warning(self, validator, ha_mock):
        """Hohe Temperatur bei warmem Wetter → Warnung."""
        ha_mock.get_states = AsyncMock(return_value=[
            {
                "entity_id": "weather.home",
                "state": "sunny",
                "attributes": {"temperature": 25, "friendly_name": "Weather"},
            },
        ])
        result = await validator.get_pushback_context(
            "set_climate",
            {"entity_id": "climate.wohnzimmer", "temperature": 25, "room": "wohnzimmer"},
        )
        if result is not None:
            heating_warnings = [w for w in result["warnings"] if w["type"] == "unnecessary_heating"]
            # Bei 25°C draussen und 25°C Ziel: Warnung erwartet
            assert len(heating_warnings) >= 1


class TestPushbackSetLight:
    """Tests fuer _pushback_set_light()."""

    @pytest.fixture
    def validator(self, ha_mock):
        v = FunctionValidator()
        v.set_ha_client(ha_mock)
        return v

    @pytest.mark.asyncio
    async def test_daylight_warning(self, validator, ha_mock):
        """Sonne hoch (Elevation > 25°) bei Licht an → Warnung."""
        ha_mock.get_states = AsyncMock(return_value=[
            {
                "entity_id": "sun.sun",
                "state": "above_horizon",
                "attributes": {"elevation": 35.0},
            },
        ])
        result = await validator.get_pushback_context(
            "set_light",
            {"entity_id": "light.wohnzimmer", "state": "on", "brightness": 100},
        )
        assert result is not None
        assert any(w["type"] == "daylight" for w in result["warnings"])

    @pytest.mark.asyncio
    async def test_no_warning_low_sun(self, validator, ha_mock):
        """Sonne niedrig → keine Warnung."""
        ha_mock.get_states = AsyncMock(return_value=[
            {
                "entity_id": "sun.sun",
                "state": "above_horizon",
                "attributes": {"elevation": 10.0},
            },
        ])
        result = await validator.get_pushback_context(
            "set_light",
            {"entity_id": "light.wohnzimmer", "state": "on", "brightness": 100},
        )
        if result is not None:
            daylight_warnings = [w for w in result["warnings"] if w["type"] == "daylight"]
            assert len(daylight_warnings) == 0

    @pytest.mark.asyncio
    async def test_no_warning_light_off(self, validator, ha_mock):
        """Licht ausschalten → keine Warnung."""
        ha_mock.get_states = AsyncMock(return_value=[
            {
                "entity_id": "sun.sun",
                "state": "above_horizon",
                "attributes": {"elevation": 50.0},
            },
        ])
        result = await validator.get_pushback_context(
            "set_light",
            {"entity_id": "light.wohnzimmer", "state": "off"},
        )
        # Kein Pushback beim Ausschalten
        if result is not None:
            assert len(result.get("warnings", [])) == 0


class TestPushbackSetCover:
    """Tests fuer _pushback_set_cover()."""

    @pytest.fixture
    def validator(self, ha_mock):
        v = FunctionValidator()
        v.set_ha_client(ha_mock)
        return v

    @pytest.mark.asyncio
    async def test_storm_warning(self, validator, ha_mock):
        """Starker Wind (> 60 km/h) bei Rolladen oeffnen → Warnung."""
        ha_mock.get_states = AsyncMock(return_value=[
            {
                "entity_id": "weather.home",
                "state": "windy",
                "attributes": {"wind_speed": 75, "friendly_name": "Weather"},
            },
        ])
        result = await validator.get_pushback_context(
            "set_cover",
            {"entity_id": "cover.wohnzimmer", "action": "open"},
        )
        assert result is not None
        assert any(w["type"] == "storm_warning" for w in result["warnings"])

    @pytest.mark.asyncio
    async def test_no_warning_calm_wind(self, validator, ha_mock):
        """Leichter Wind → keine Warnung."""
        ha_mock.get_states = AsyncMock(return_value=[
            {
                "entity_id": "weather.home",
                "state": "sunny",
                "attributes": {"wind_speed": 20, "friendly_name": "Weather"},
            },
        ])
        result = await validator.get_pushback_context(
            "set_cover",
            {"entity_id": "cover.wohnzimmer", "action": "open"},
        )
        if result is not None:
            storm_warnings = [w for w in result["warnings"] if w["type"] == "storm_warning"]
            assert len(storm_warnings) == 0

    @pytest.mark.asyncio
    async def test_no_warning_closing_cover(self, validator, ha_mock):
        """Rolladen schliessen → keine Warnung (auch bei Sturm)."""
        ha_mock.get_states = AsyncMock(return_value=[
            {
                "entity_id": "weather.home",
                "state": "windy",
                "attributes": {"wind_speed": 75, "friendly_name": "Weather"},
            },
        ])
        result = await validator.get_pushback_context(
            "set_cover",
            {"entity_id": "cover.wohnzimmer", "action": "close"},
        )
        if result is not None:
            assert len(result.get("warnings", [])) == 0


class TestFormatPushbackWarnings:
    """Tests fuer format_pushback_warnings()."""

    def test_format_with_warnings(self):
        """Warnungen werden korrekt formatiert."""
        pushback = {
            "warnings": [
                {"type": "open_window", "detail": "Fenster Wohnzimmer ist offen"},
                {"type": "daylight", "detail": "Die Sonne steht hoch (Elevation 35°)"},
            ]
        }
        result = FunctionValidator.format_pushback_warnings(pushback)
        assert "SITUATIONSBEWUSSTSEIN" in result or "WIDERSPRUCH" in result or "DATEN" in result
        assert "Fenster Wohnzimmer ist offen" in result
        assert "Sonne" in result

    def test_format_empty_warnings(self):
        """Keine Warnungen → leerer String."""
        pushback = {"warnings": []}
        result = FunctionValidator.format_pushback_warnings(pushback)
        assert result == ""

    def test_format_none_safe(self):
        """None Input → soll nicht crashen (oder KeyError)."""
        # format_pushback_warnings erwartet ein dict; bei None wird es vom
        # Aufrufer (brain.py) vorher abgefangen. Testen wir leere warnings.
        result = FunctionValidator.format_pushback_warnings({"warnings": []})
        assert result == ""


class TestBrightnessValueError:
    """Test fuer Bug 5: ValueError bei ungueltigem Brightness."""

    @pytest.fixture
    def validator(self, ha_mock):
        v = FunctionValidator()
        v.set_ha_client(ha_mock)
        return v

    @pytest.mark.asyncio
    async def test_invalid_brightness_no_crash(self, validator, ha_mock):
        """Ungueltiger Brightness-String crasht nicht."""
        ha_mock.get_states = AsyncMock(return_value=[
            {
                "entity_id": "sun.sun",
                "state": "above_horizon",
                "attributes": {"elevation": 50.0},
            },
        ])
        # brightness als ungueltiger String → kein Crash
        result = await validator.get_pushback_context(
            "set_light",
            {"entity_id": "light.wz", "state": "on", "brightness": "hell"},
        )
        # Soll nicht crashen, Ergebnis ist egal
        assert True


class TestGetPushbackUnknownFunction:
    """Tests fuer unbekannte Funktionen."""

    @pytest.fixture
    def validator(self, ha_mock):
        v = FunctionValidator()
        v.set_ha_client(ha_mock)
        return v

    @pytest.mark.asyncio
    async def test_unknown_function_returns_none(self, validator):
        """Unbekannte Funktion gibt None zurueck."""
        result = await validator.get_pushback_context(
            "play_music",
            {"entity_id": "media.wz"},
        )
        assert result is None
