"""
Function Validator - Prueft Function Calls auf Sicherheit und Plausibilitaet.
Verhindert gefaehrliche oder unsinnige Aktionen.

Feature 10: Daten-basierter Widerspruch — prueft Live-Daten vor Ausfuehrung
und liefert konkreten Pushback-Kontext (offene Fenster, leerer Raum, etc.).
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from .config import yaml_config

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    ok: bool
    needs_confirmation: bool = False
    reason: Optional[str] = None


class FunctionValidator:
    """Validiert Function Calls vor der Ausfuehrung."""

    def __init__(self):
        # Aktionen die Bestaetigung brauchen (statisch)
        security = yaml_config.get("security", {})
        confirm_list = security.get("require_confirmation", [])
        self.require_confirmation = set(confirm_list)

    def _get_climate_config(self) -> dict:
        """Liest Climate-Limits und Heizungsmodus live aus yaml_config."""
        from .config import yaml_config as cfg
        security = cfg.get("security", {})
        limits = security.get("climate_limits", {})
        heating = cfg.get("heating", {})
        return {
            "temp_min": limits.get("min", 15),
            "temp_max": limits.get("max", 28),
            "heating_mode": heating.get("mode", "room_thermostat"),
            "offset_min": heating.get("curve_offset_min", -5),
            "offset_max": heating.get("curve_offset_max", 5),
        }

    def validate(self, function_name: str, arguments: dict) -> ValidationResult:
        """
        Prueft einen Function Call.

        Args:
            function_name: Name der Funktion
            arguments: Parameter

        Returns:
            ValidationResult mit ok, needs_confirmation, reason
        """
        # Bestaetigung pruefen
        for confirm_rule in self.require_confirmation:
            parts = confirm_rule.split(":")
            if len(parts) == 2:
                func, value = parts
                if function_name == func:
                    # Pruefen ob der kritische Wert gesetzt ist
                    for arg_value in arguments.values():
                        if str(arg_value) == value:
                            return ValidationResult(
                                ok=False,
                                needs_confirmation=True,
                                reason=f"Sicherheitsbestaetigung noetig fuer {function_name}:{value}",
                            )

        # Spezifische Validierungen
        validator = getattr(self, f"_validate_{function_name}", None)
        if validator:
            return validator(arguments)

        return ValidationResult(ok=True)

    def _validate_set_climate(self, args: dict) -> ValidationResult:
        cc = self._get_climate_config()
        if cc["heating_mode"] == "heating_curve":
            return self._validate_climate_curve(args, cc)
        return self._validate_climate_room(args, cc)

    def _validate_climate_curve(self, args: dict, cc: dict) -> ValidationResult:
        """Validiert Offset fuer Heizkurven-Modus."""
        offset = args.get("offset")
        if offset is not None:
            try:
                offset = float(offset)
            except (ValueError, TypeError):
                return ValidationResult(ok=False, reason=f"Offset '{offset}' ist keine gueltige Zahl")
            if offset < cc["offset_min"]:
                return ValidationResult(
                    ok=False,
                    reason=f"Offset {offset}°C unter Minimum ({cc['offset_min']}°C)",
                )
            if offset > cc["offset_max"]:
                return ValidationResult(
                    ok=False,
                    reason=f"Offset {offset}°C ueber Maximum ({cc['offset_max']}°C)",
                )
        return ValidationResult(ok=True)

    def _validate_climate_room(self, args: dict, cc: dict) -> ValidationResult:
        """Validiert absolute Temperatur fuer Raumthermostat-Modus."""
        temp = args.get("temperature")
        if temp is not None:
            try:
                temp = float(temp)
            except (ValueError, TypeError):
                return ValidationResult(ok=False, reason=f"Temperatur '{temp}' ist keine gueltige Zahl")
            if temp < cc["temp_min"]:
                return ValidationResult(
                    ok=False,
                    reason=f"Temperatur {temp}°C unter Minimum ({cc['temp_min']}°C)",
                )
            if temp > cc["temp_max"]:
                return ValidationResult(
                    ok=False,
                    reason=f"Temperatur {temp}°C ueber Maximum ({cc['temp_max']}°C)",
                )
        return ValidationResult(ok=True)

    def _validate_set_light(self, args: dict) -> ValidationResult:
        brightness = args.get("brightness")
        if brightness is not None:
            try:
                brightness = int(brightness)
            except (ValueError, TypeError):
                return ValidationResult(ok=False, reason=f"Helligkeit '{brightness}' ist keine gueltige Zahl")
            # Qwen3 sendet manchmal 0-255 (HA-Skala) statt 0-100 (Prozent)
            if 101 <= brightness <= 255:
                brightness = round(brightness / 255 * 100)
                args["brightness"] = brightness
            if brightness < 0 or brightness > 100:
                return ValidationResult(
                    ok=False,
                    reason=f"Helligkeit {brightness}% ausserhalb 0-100",
                )
        return ValidationResult(ok=True)

    def _validate_set_cover(self, args: dict) -> ValidationResult:
        position = args.get("position")
        if position is not None:
            try:
                position = int(position)
            except (ValueError, TypeError):
                return ValidationResult(ok=False, reason=f"Position '{position}' ist keine gueltige Zahl")
            if position < 0 or position > 100:
                return ValidationResult(
                    ok=False,
                    reason=f"Position {position}% ausserhalb 0-100",
                )
        return ValidationResult(ok=True)
