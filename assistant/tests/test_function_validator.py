"""
Tests fuer FunctionValidator — Sicherheitsvalidierung von Function Calls.

Umfassende Tests fuer sicherheitskritische Logik:
- Temperatur-Validierung (Raum-Thermostat + Heizkurven-Modus)
- Helligkeits-Validierung (0-100, LLM-Brightness-Korrektur)
- Rolladen-Positions-Validierung
- Require-Confirmation Regeln
- Severity-Berechnung (4-Stufen-Eskalation)
- State-Age-Pruefung
- Edge-Cases und Fehlerbehandlung
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

from assistant.function_validator import FunctionValidator, ValidationResult


# =====================================================================
# Fixtures
# =====================================================================


def _make_validator(climate_config=None, require_confirmation=None, pushback_cfg=None):
    """Erstellt FunctionValidator mit gemockter Config."""
    security = {}
    if climate_config:
        security["climate_limits"] = climate_config.get("climate_limits", {})
    if require_confirmation:
        security["require_confirmation"] = require_confirmation

    yaml_mock = {"security": security}
    if pushback_cfg:
        yaml_mock["pushback"] = pushback_cfg

    heating = climate_config.get("heating", {}) if climate_config else {}
    if heating:
        yaml_mock["heating"] = heating

    with patch("assistant.function_validator.yaml_config", yaml_mock):
        return FunctionValidator()


@pytest.fixture
def validator():
    """Standard FunctionValidator mit Default-Config."""
    yaml_mock = {
        "security": {
            "climate_limits": {"min": 15, "max": 28},
            "require_confirmation": [],
        },
        "heating": {"mode": "room_thermostat"},
    }
    with patch("assistant.function_validator.yaml_config", yaml_mock):
        yield FunctionValidator()


@pytest.fixture
def curve_validator():
    """FunctionValidator im Heizkurven-Modus."""
    yaml_mock = {
        "security": {
            "climate_limits": {"min": 15, "max": 28},
            "require_confirmation": [],
        },
        "heating": {
            "mode": "heating_curve",
            "curve_offset_min": -5,
            "curve_offset_max": 5,
        },
    }
    # Muss sowohl am Import-Ort als auch am Quell-Ort gepatcht werden,
    # da _get_climate_config() yaml_config erneut aus assistant.config importiert.
    with patch("assistant.function_validator.yaml_config", yaml_mock), \
         patch("assistant.config.yaml_config", yaml_mock):
        yield FunctionValidator()


# =====================================================================
# Temperatur-Validierung (Raum-Thermostat-Modus)
# =====================================================================


class TestValidateClimateRoom:
    """Tests fuer Temperatur-Validierung im Raumthermostat-Modus."""

    def test_valid_temperature(self, validator):
        result = validator.validate("set_climate", {"temperature": 21})
        assert result.ok is True

    def test_temperature_at_minimum(self, validator):
        result = validator.validate("set_climate", {"temperature": 15})
        assert result.ok is True

    def test_temperature_at_maximum(self, validator):
        result = validator.validate("set_climate", {"temperature": 28})
        assert result.ok is True

    def test_temperature_below_minimum(self, validator):
        result = validator.validate("set_climate", {"temperature": 14})
        assert result.ok is False
        assert "Minimum" in result.reason

    def test_temperature_above_maximum(self, validator):
        result = validator.validate("set_climate", {"temperature": 30})
        assert result.ok is False
        assert "Maximum" in result.reason

    def test_temperature_invalid_string(self, validator):
        result = validator.validate("set_climate", {"temperature": "warm"})
        assert result.ok is False
        assert "gueltige Zahl" in result.reason

    def test_temperature_none_passes(self, validator):
        """Keine Temperatur angegeben → kein Fehler (andere Klimaparameter moeglich)."""
        result = validator.validate("set_climate", {"mode": "auto"})
        assert result.ok is True

    def test_temperature_float_boundary(self, validator):
        """Float knapp unter Minimum wird korrekt erkannt."""
        result = validator.validate("set_climate", {"temperature": 14.9})
        assert result.ok is False

    def test_temperature_string_number(self, validator):
        """Temperatur als String-Zahl wird korrekt geparst."""
        result = validator.validate("set_climate", {"temperature": "22"})
        assert result.ok is True


# =====================================================================
# Temperatur-Validierung (Heizkurven-Modus)
# =====================================================================


class TestValidateClimateCurve:
    """Tests fuer Offset-Validierung im Heizkurven-Modus."""

    def test_valid_offset(self, curve_validator):
        result = curve_validator.validate("set_climate", {"offset": 2})
        assert result.ok is True

    def test_offset_at_minimum(self, curve_validator):
        result = curve_validator.validate("set_climate", {"offset": -5})
        assert result.ok is True

    def test_offset_at_maximum(self, curve_validator):
        result = curve_validator.validate("set_climate", {"offset": 5})
        assert result.ok is True

    def test_offset_below_minimum(self, curve_validator):
        result = curve_validator.validate("set_climate", {"offset": -6})
        assert result.ok is False
        assert "Minimum" in result.reason

    def test_offset_above_maximum(self, curve_validator):
        result = curve_validator.validate("set_climate", {"offset": 6})
        assert result.ok is False
        assert "Maximum" in result.reason

    def test_offset_invalid_string(self, curve_validator):
        result = curve_validator.validate("set_climate", {"offset": "kalt"})
        assert result.ok is False
        assert "gueltige Zahl" in result.reason

    def test_no_offset_passes(self, curve_validator):
        """Kein Offset angegeben → kein Fehler."""
        result = curve_validator.validate("set_climate", {"mode": "heat"})
        assert result.ok is True


# =====================================================================
# Helligkeits-Validierung
# =====================================================================


class TestValidateSetLight:
    """Tests fuer Helligkeits-Validierung."""

    def test_valid_brightness(self, validator):
        result = validator.validate("set_light", {"brightness": 50})
        assert result.ok is True

    def test_brightness_zero(self, validator):
        result = validator.validate("set_light", {"brightness": 0})
        assert result.ok is True

    def test_brightness_100(self, validator):
        result = validator.validate("set_light", {"brightness": 100})
        assert result.ok is True

    def test_brightness_negative(self, validator):
        result = validator.validate("set_light", {"brightness": -1})
        assert result.ok is False
        assert "0-100" in result.reason

    def test_brightness_over_100_under_255_auto_scaled(self, validator):
        """Brightness 101-255 (HA-Skala) wird automatisch auf 0-100 skaliert."""
        result = validator.validate("set_light", {"brightness": 200})
        assert result.ok is True
        # 200/255*100 ≈ 78 — args werden in-place modifiziert

    def test_brightness_255_scaled_to_100(self, validator):
        """Brightness 255 wird auf 100 skaliert."""
        args = {"brightness": 255}
        result = validator.validate("set_light", args)
        assert result.ok is True
        assert args["brightness"] == 100

    def test_brightness_invalid_string(self, validator):
        result = validator.validate("set_light", {"brightness": "dunkel"})
        assert result.ok is False
        assert "gueltige Zahl" in result.reason

    def test_brightness_dimmer_string_converted_to_state(self, validator):
        """LLM sendet 'dunkler' als brightness → wird zu state='dimmer' konvertiert."""
        args = {"brightness": "dunkler"}
        result = validator.validate("set_light", args)
        assert result.ok is True
        assert args.get("state") == "dimmer"
        assert "brightness" not in args

    def test_brightness_brighter_string_converted(self, validator):
        """LLM sendet 'heller'/'brighter' als brightness → wird zu state='brighter'."""
        args = {"brightness": "heller"}
        result = validator.validate("set_light", args)
        assert result.ok is True
        assert args.get("state") == "brighter"

    def test_brightness_case_insensitive(self, validator):
        """Brightness-String-Konvertierung ist case-insensitive."""
        args = {"brightness": "DIMMER"}
        result = validator.validate("set_light", args)
        assert result.ok is True
        assert args.get("state") == "dimmer"

    def test_no_brightness_passes(self, validator):
        """Kein brightness → kein Fehler (z.B. nur state='on')."""
        result = validator.validate("set_light", {"state": "on"})
        assert result.ok is True


# =====================================================================
# Rolladen-Positions-Validierung
# =====================================================================


class TestValidateSetCover:
    """Tests fuer Rolladen-Positions-Validierung."""

    def test_valid_position(self, validator):
        result = validator.validate("set_cover", {"position": 50})
        assert result.ok is True

    def test_position_zero(self, validator):
        result = validator.validate("set_cover", {"position": 0})
        assert result.ok is True

    def test_position_100(self, validator):
        result = validator.validate("set_cover", {"position": 100})
        assert result.ok is True

    def test_position_negative(self, validator):
        result = validator.validate("set_cover", {"position": -1})
        assert result.ok is False
        assert "0-100" in result.reason

    def test_position_over_100(self, validator):
        result = validator.validate("set_cover", {"position": 101})
        assert result.ok is False
        assert "0-100" in result.reason

    def test_position_invalid_string(self, validator):
        result = validator.validate("set_cover", {"position": "halb"})
        assert result.ok is False
        assert "gueltige Zahl" in result.reason

    def test_no_position_passes(self, validator):
        """Kein position → kein Fehler (z.B. nur action='open')."""
        result = validator.validate("set_cover", {"action": "open"})
        assert result.ok is True


# =====================================================================
# Require-Confirmation Regeln
# =====================================================================


class TestRequireConfirmation:
    """Tests fuer sicherheitskritische Bestaetigungsanfragen."""

    def test_confirmation_required_for_matching_rule(self):
        """Matching rule triggert Bestaetigung."""
        yaml_mock = {
            "security": {
                "require_confirmation": ["unlock_door:unlock"],
            },
        }
        with patch("assistant.function_validator.yaml_config", yaml_mock):
            v = FunctionValidator()
            result = v.validate("unlock_door", {"action": "unlock"})
            assert result.ok is False
            assert result.needs_confirmation is True
            assert "Sicherheitsbestaetigung" in result.reason

    def test_no_confirmation_for_non_matching_value(self):
        """Nicht-matchender Wert triggert keine Bestaetigung."""
        yaml_mock = {
            "security": {
                "require_confirmation": ["unlock_door:unlock"],
            },
        }
        with patch("assistant.function_validator.yaml_config", yaml_mock):
            v = FunctionValidator()
            result = v.validate("unlock_door", {"action": "lock"})
            assert result.ok is True
            assert result.needs_confirmation is False

    def test_no_confirmation_for_different_function(self):
        """Andere Funktion triggert keine Bestaetigung."""
        yaml_mock = {
            "security": {
                "require_confirmation": ["unlock_door:unlock"],
            },
        }
        with patch("assistant.function_validator.yaml_config", yaml_mock):
            v = FunctionValidator()
            result = v.validate("set_light", {"state": "on"})
            assert result.ok is True

    def test_multiple_confirmation_rules(self):
        """Mehrere Confirmation-Regeln werden alle geprueft."""
        yaml_mock = {
            "security": {
                "require_confirmation": [
                    "unlock_door:unlock",
                    "disarm_alarm:disarm",
                ],
            },
        }
        with patch("assistant.function_validator.yaml_config", yaml_mock):
            v = FunctionValidator()
            result1 = v.validate("unlock_door", {"action": "unlock"})
            assert result1.needs_confirmation is True
            result2 = v.validate("disarm_alarm", {"action": "disarm"})
            assert result2.needs_confirmation is True

    def test_empty_confirmation_rules(self):
        """Leere Confirmation-Regeln → nie Bestaetigung noetig."""
        yaml_mock = {"security": {"require_confirmation": []}}
        with patch("assistant.function_validator.yaml_config", yaml_mock):
            v = FunctionValidator()
            result = v.validate("unlock_door", {"action": "unlock"})
            assert result.ok is True


# =====================================================================
# Unknown Function + Passthrough
# =====================================================================


class TestUnknownFunctionValidation:
    """Tests fuer Funktionen ohne spezifischen Validator."""

    def test_unknown_function_passes(self, validator):
        """Unbekannte Funktion ohne Confirmation-Rule → ok."""
        result = validator.validate("play_media", {"track": "test.mp3"})
        assert result.ok is True

    def test_empty_arguments(self, validator):
        """Leere Argumente → ok."""
        result = validator.validate("set_light", {})
        assert result.ok is True

    def test_validate_returns_validation_result(self, validator):
        """validate() gibt immer ein ValidationResult zurueck."""
        result = validator.validate("nonexistent_func", {"key": "value"})
        assert isinstance(result, ValidationResult)
        assert result.ok is True


# =====================================================================
# Severity-Berechnung
# =====================================================================


class TestSeverityCalculation:
    """Tests fuer die 4-Stufen-Eskalations-Severity."""

    def test_empty_warnings_severity_1(self):
        assert FunctionValidator._calculate_severity([]) == 1

    def test_single_info_warning_severity_1(self):
        warnings = [{"type": "daylight"}]
        assert FunctionValidator._calculate_severity(warnings) == 1

    def test_single_efficiency_warning_severity_2(self):
        warnings = [{"type": "open_window"}]
        assert FunctionValidator._calculate_severity(warnings) == 2

    def test_single_safety_warning_severity_3(self):
        warnings = [{"type": "storm_warning"}]
        assert FunctionValidator._calculate_severity(warnings) == 3

    def test_multiple_info_escalates_to_2(self):
        """Zwei Info-Warnungen zusammen eskalieren auf Stufe 2."""
        warnings = [{"type": "daylight"}, {"type": "empty_room"}]
        assert FunctionValidator._calculate_severity(warnings) == 2

    def test_mixed_warnings_highest_wins(self):
        """Bei gemischten Warnungen gewinnt die hoechste Stufe."""
        warnings = [{"type": "daylight"}, {"type": "storm_warning"}]
        assert FunctionValidator._calculate_severity(warnings) == 3

    def test_severity_capped_at_3(self):
        """Severity wird auf maximal 3 begrenzt (4 nur zur Laufzeit)."""
        warnings = [
            {"type": "storm_warning"},
            {"type": "rain_markise"},
            {"type": "wind_markise"},
        ]
        assert FunctionValidator._calculate_severity(warnings) == 3

    def test_unknown_warning_type_defaults_to_1(self):
        """Unbekannter Warning-Typ hat Gewicht 1."""
        warnings = [{"type": "unknown_type"}]
        assert FunctionValidator._calculate_severity(warnings) == 1

    def test_severity_weights_all_known_types(self):
        """Alle definierten Severity-Weights sind vorhanden."""
        weights = FunctionValidator._SEVERITY_WEIGHTS
        # Stufe 1
        assert weights["daylight"] == 1
        assert weights["empty_room"] == 1
        # Stufe 2
        assert weights["open_window"] == 2
        assert weights["unnecessary_heating"] == 2
        assert weights["cold_outside"] == 2
        assert weights["solar_loss"] == 2
        assert weights["peak_tariff"] == 2
        # Stufe 3
        assert weights["storm_warning"] == 3
        assert weights["rain_markise"] == 3
        assert weights["wind_markise"] == 3


# =====================================================================
# State-Age-Pruefung
# =====================================================================


class TestCheckStateAge:
    """Tests fuer State-Alter-Pruefung."""

    def test_fresh_state(self, validator):
        """Aktueller State (jetzt) ist frisch genug."""
        now = datetime.now(timezone.utc).isoformat()
        assert validator.check_state_age("sensor.test", now) is True

    def test_old_state(self, validator):
        """State aelter als max_age_minutes wird erkannt."""
        old = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
        assert validator.check_state_age("sensor.test", old, max_age_minutes=10) is False

    def test_custom_max_age(self, validator):
        """Benutzerdefiniertes max_age_minutes."""
        five_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        assert validator.check_state_age("sensor.test", five_min_ago, max_age_minutes=3) is False
        assert validator.check_state_age("sensor.test", five_min_ago, max_age_minutes=10) is True

    def test_invalid_timestamp_allows_pushback(self, validator):
        """Ungueltiger Timestamp → im Zweifel Pushback erlauben (True)."""
        assert validator.check_state_age("sensor.test", "not-a-date") is True

    def test_z_suffix_handled(self, validator):
        """ISO-Format mit Z-Suffix wird korrekt geparst."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"
        assert validator.check_state_age("sensor.test", now) is True


# =====================================================================
# ValidationResult Datenklasse
# =====================================================================


class TestValidationResult:
    """Tests fuer ValidationResult-Datenklasse."""

    def test_default_values(self):
        result = ValidationResult(ok=True)
        assert result.ok is True
        assert result.needs_confirmation is False
        assert result.reason is None

    def test_failed_with_reason(self):
        result = ValidationResult(ok=False, reason="Zu heiss")
        assert result.ok is False
        assert result.reason == "Zu heiss"

    def test_confirmation_needed(self):
        result = ValidationResult(ok=False, needs_confirmation=True, reason="Tuer oeffnen")
        assert result.ok is False
        assert result.needs_confirmation is True


# =====================================================================
# HA-Client Setter
# =====================================================================


class TestSetHaClient:
    """Tests fuer set_ha_client()."""

    def test_set_ha_client(self, validator):
        mock_ha = MagicMock()
        validator.set_ha_client(mock_ha)
        assert validator.ha is mock_ha

    def test_ha_initially_none(self, validator):
        assert validator.ha is None
