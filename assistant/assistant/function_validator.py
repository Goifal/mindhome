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
        # Feature 10: HA-Client fuer Live-Daten-Pushback (gesetzt via set_ha_client)
        self.ha = None

    def set_ha_client(self, ha_client) -> None:
        """Setzt den HA-Client fuer Live-Daten-Abfragen (Feature 10)."""
        self.ha = ha_client

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

    # ------------------------------------------------------------------
    # Feature 10: Daten-basierter Widerspruch (Live-Pushback)
    # ------------------------------------------------------------------

    async def get_pushback_context(
        self, func_name: str, args: dict
    ) -> Optional[dict]:
        """Prueft Live-Daten und liefert Kontext fuer intelligenten Widerspruch.

        Args:
            func_name: Name der geplanten Funktion
            args: Funktions-Argumente

        Returns:
            Dict mit warnings-Liste oder None
        """
        pushback_cfg = yaml_config.get("pushback", {})
        if not pushback_cfg.get("enabled", True) or not self.ha:
            return None

        checker = getattr(self, f"_pushback_{func_name}", None)
        if not checker:
            return None

        try:
            return await checker(args, pushback_cfg.get("checks", {}))
        except Exception as e:
            logger.debug("Pushback-Check fehlgeschlagen fuer %s: %s", func_name, e)
            return None

    async def _pushback_set_climate(
        self, args: dict, checks: dict
    ) -> Optional[dict]:
        """Pushback fuer Klimasteuerung: offene Fenster, leerer Raum."""
        warnings = []
        room = (args.get("room") or "").lower()

        if not room:
            return None

        states = await self.ha.get_states()
        if not states:
            return None

        # Check: Fenster offen im gleichen Raum?
        if checks.get("open_windows", True):
            for state in states:
                eid = state.get("entity_id", "")
                if not eid.startswith(("binary_sensor.fenster", "binary_sensor.window")):
                    continue
                friendly = (state.get("attributes", {}).get("friendly_name") or eid).lower()
                if room in friendly and state.get("state") == "on":
                    window_name = state.get("attributes", {}).get("friendly_name", eid)
                    warnings.append({
                        "type": "open_window",
                        "detail": f"{window_name} ist offen",
                        "room": room,
                    })

        # Check: Niemand im Raum?
        if checks.get("empty_room", True):
            room_occupied = False
            for state in states:
                eid = state.get("entity_id", "")
                if not eid.startswith("binary_sensor.motion"):
                    continue
                friendly = (state.get("attributes", {}).get("friendly_name") or eid).lower()
                if room in friendly and state.get("state") == "on":
                    room_occupied = True
                    break
            if not room_occupied:
                # Nur warnen wenn kein Motion in den letzten Minuten
                warnings.append({
                    "type": "empty_room",
                    "detail": f"Kein Bewegungsmelder aktiv in {room.title()}",
                    "room": room,
                })

        # Check: Hohe Temperatur + warmes Wetter
        if checks.get("unnecessary_heating", True):
            target_temp = args.get("temperature")
            if target_temp:
                try:
                    target_temp = float(target_temp)
                except (ValueError, TypeError):
                    target_temp = None
            if target_temp and target_temp >= 24:
                for state in states:
                    eid = state.get("entity_id", "")
                    if eid.startswith("weather."):
                        try:
                            outside_temp = float(state.get("attributes", {}).get("temperature", 0))
                            if outside_temp >= 20:
                                warnings.append({
                                    "type": "unnecessary_heating",
                                    "detail": f"Draussen sind es {outside_temp}°C",
                                })
                        except (ValueError, TypeError):
                            pass
                        break

        return {"warnings": warnings} if warnings else None

    async def _pushback_set_light(
        self, args: dict, checks: dict
    ) -> Optional[dict]:
        """Pushback fuer Licht: Tageslicht, leerer Raum."""
        warnings = []
        state_val = (args.get("state") or "").lower()

        # Nur bei Einschalten pruefen
        if state_val not in ("on", "brighter", ""):
            return None
        # Brightness=0 ist ausschalten
        brightness = args.get("brightness")
        if brightness is not None and int(brightness) == 0:
            return None

        room = (args.get("room") or "").lower()

        states = await self.ha.get_states()
        if not states:
            return None

        # Check: Helles Tageslicht?
        if checks.get("daylight", True):
            for state in states:
                eid = state.get("entity_id", "")
                if eid == "sun.sun":
                    elevation = state.get("attributes", {}).get("elevation", 0)
                    try:
                        if float(elevation) > 25:
                            warnings.append({
                                "type": "daylight",
                                "detail": f"Die Sonne steht hoch (Elevation {elevation}°)",
                            })
                    except (ValueError, TypeError):
                        pass
                    break

        return {"warnings": warnings} if warnings else None

    async def _pushback_set_cover(
        self, args: dict, checks: dict
    ) -> Optional[dict]:
        """Pushback fuer Rolladen: Sturmwarnung."""
        warnings = []
        action = (args.get("action") or args.get("state") or "").lower()

        # Nur bei Oeffnen pruefen
        if action not in ("open", "auf", "offen", "hoch", "up"):
            return None

        if not checks.get("storm_warning", True):
            return None

        states = await self.ha.get_states()
        if not states:
            return None

        for state in states:
            eid = state.get("entity_id", "")
            if eid.startswith("weather."):
                attrs = state.get("attributes", {})
                wind_speed = attrs.get("wind_speed", 0)
                try:
                    if float(wind_speed) > 60:
                        warnings.append({
                            "type": "storm_warning",
                            "detail": f"Starker Wind mit {wind_speed} km/h",
                        })
                except (ValueError, TypeError):
                    pass
                break

        return {"warnings": warnings} if warnings else None

    @staticmethod
    def format_pushback_warnings(pushback: dict) -> str:
        """Formatiert Pushback-Warnungen als LLM-Kontext-String.

        Args:
            pushback: Dict mit warnings-Liste aus get_pushback_context()

        Returns:
            Formatierter Warntext fuer den LLM-Prompt
        """
        warnings = pushback.get("warnings", [])
        if not warnings:
            return ""

        lines = ["DATEN-BASIERTER WIDERSPRUCH — Weise den Benutzer auf Folgendes hin:"]
        for w in warnings:
            lines.append(f"- {w['detail']}")
        lines.append("Fuehre die Aktion trotzdem aus, aber erwaehne die Warnung beilaeufig.")
        return "\n".join(lines)
