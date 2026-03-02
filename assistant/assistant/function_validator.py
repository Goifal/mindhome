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
            # LLM sendet manchmal "dunkler"/"heller" als brightness statt als state
            _brightness_to_state = {
                "dunkler": "dimmer", "dimmer": "dimmer",
                "heller": "brighter", "brighter": "brighter",
            }
            if isinstance(brightness, str) and brightness.lower() in _brightness_to_state:
                args["state"] = _brightness_to_state[brightness.lower()]
                del args["brightness"]
                return ValidationResult(ok=True)
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
        # Nutzt is_heating_relevant_opening um Tore/unbeheizte Bereiche auszuschliessen
        if checks.get("open_windows", True):
            from .function_calling import is_heating_relevant_opening, get_opening_sensor_config
            for state in states:
                eid = state.get("entity_id", "")
                if not is_heating_relevant_opening(eid, state):
                    continue
                if state.get("state") != "on":
                    continue
                # Raum-Match: opening_sensors Config oder friendly_name Fallback
                cfg = get_opening_sensor_config(eid)
                sensor_room = (cfg.get("room") or "").lower()
                friendly = (state.get("attributes", {}).get("friendly_name") or eid).lower()
                if sensor_room == room or (not sensor_room and room in friendly):
                    window_name = state.get("attributes", {}).get("friendly_name", eid)
                    target_t = args.get("temperature", "?")
                    warnings.append({
                        "type": "open_window",
                        "detail": f"{window_name} ist offen",
                        "room": room,
                        "alternative": f"Erst {window_name} schliessen, dann Heizung auf {target_t}°C",
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
                    "alternative": "Absenktemperatur (18°C) setzen oder Timer fuer 30 Minuten",
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
                                    "alternative": "Fenster oeffnen statt heizen — draussen warm genug",
                                })
                        except (ValueError, TypeError):
                            pass
                        break

        result = {"warnings": warnings} if warnings else None
        if result:
            result["severity"] = self._calculate_severity(warnings)
        return result

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
        if brightness is not None:
            try:
                if int(brightness) == 0:
                    return None
            except (ValueError, TypeError):
                pass  # Ungueltige Brightness → trotzdem pruefen

        room = (args.get("room") or "").lower()

        states = await self.ha.get_states()
        if not states:
            return None

        # Check: Helles Tageslicht? (lighting.daylight_off aus settings.yaml)
        from .config import yaml_config as _fv_yaml_config
        _daylight_enabled = _fv_yaml_config.get("lighting", {}).get("daylight_off", True)
        if _daylight_enabled and checks.get("daylight", True):
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

        result = {"warnings": warnings} if warnings else None
        if result:
            result["severity"] = self._calculate_severity(warnings)
        return result

    async def _pushback_set_cover(
        self, args: dict, checks: dict
    ) -> Optional[dict]:
        """Pushback fuer Rolladen: Sturmwarnung, Kaelte, Markisen-Regen."""
        warnings = []
        action = (args.get("action") or args.get("state") or "").lower()
        position = args.get("position")
        room = (args.get("room") or "").lower()

        states = await self.ha.get_states()
        if not states:
            return None

        # Wetterdaten holen
        outside_temp = None
        wind_speed = 0
        condition = ""
        for state in states:
            eid = state.get("entity_id", "")
            if eid.startswith("weather."):
                attrs = state.get("attributes", {})
                try:
                    outside_temp = float(attrs.get("temperature", 10))
                except (ValueError, TypeError):
                    outside_temp = 10
                try:
                    wind_speed = float(attrs.get("wind_speed", 0))
                except (ValueError, TypeError):
                    wind_speed = 0
                condition = state.get("state", "")
                break

        is_opening = action in ("open", "auf", "offen", "hoch", "up")
        if position is not None:
            try:
                is_opening = is_opening or int(position) > 50
            except (ValueError, TypeError):
                pass

        # Sturmwarnung bei Oeffnen
        if is_opening and checks.get("storm_warning", True):
            if wind_speed > 60:
                warnings.append({
                    "type": "storm_warning",
                    "detail": f"Starker Wind mit {wind_speed} km/h",
                    "alternative": "Rolllaeden geschlossen lassen zum Schutz",
                })

        # Rollladen hoch bei extremer Kaelte
        if is_opening and outside_temp is not None and outside_temp < 0:
            warnings.append({
                "type": "cold_outside",
                "detail": f"Aussentemperatur {outside_temp}°C — Kaelte kommt rein",
                "alternative": "Rollladen auf 20% — Licht rein, Isolierung bleibt",
            })

        # Markise bei Regen/Wind
        cover_type = args.get("type", "")
        is_markise = cover_type == "markise" or room == "markisen"
        if is_markise and is_opening:
            rain_conditions = {"rainy", "pouring", "hail", "lightning-rainy"}
            if condition in rain_conditions:
                warnings.append({
                    "type": "rain_markise",
                    "detail": f"Wetter: {condition} — Markise wird nass/beschaedigt",
                    "alternative": "Markise eingefahren lassen",
                })
            if wind_speed >= 40:
                warnings.append({
                    "type": "wind_markise",
                    "detail": f"Wind {wind_speed} km/h — Markise kann beschaedigt werden",
                    "alternative": "Markise erst bei Windstille ausfahren",
                })

        result = {"warnings": warnings} if warnings else None
        if result:
            result["severity"] = self._calculate_severity(warnings)
        return result

    # ------------------------------------------------------------------
    # MCU-JARVIS: Eskalations-Stufen (4-Tier Severity)
    # ------------------------------------------------------------------

    # Severity-Gewichte pro Warning-Typ
    _SEVERITY_WEIGHTS = {
        # Stufe 1: Beilaeuifig (Info)
        "daylight": 1,
        "empty_room": 1,
        # Stufe 2: Einwand (Effizienz)
        "open_window": 2,
        "unnecessary_heating": 2,
        "cold_outside": 2,
        # Stufe 3: Sorge (Sicherheit/Schaden)
        "storm_warning": 3,
        "rain_markise": 3,
        "wind_markise": 3,
    }

    @staticmethod
    def _calculate_severity(warnings: list[dict]) -> int:
        """Berechnet die Eskalationsstufe basierend auf den Warnungen.

        4-Stufen-Modell wie MCU-JARVIS:
        1 = beilaeufig: "Uebrigens..." (Info, kein Risiko)
        2 = Einwand: "Darf ich anmerken..." (Effizienz-Bedenken)
        3 = Sorge: "{title}, kurzer Einwand —" (Sicherheit/Schaden)
        4 = Resignation: "Wie du wuenschst, {title}." (nach ignorierter Warnung)

        Returns:
            Severity 1-3 (4 wird zur Laufzeit bei Wiederholung gesetzt)
        """
        if not warnings:
            return 1
        max_weight = max(
            FunctionValidator._SEVERITY_WEIGHTS.get(w.get("type", ""), 1)
            for w in warnings
        )
        # Mehrere Warnungen gleichzeitig → Stufe mindestens 2
        if len(warnings) >= 2 and max_weight < 2:
            max_weight = 2
        return min(3, max_weight)

    @staticmethod
    def format_pushback_warnings(pushback: dict) -> str:
        """Formatiert Pushback-Warnungen als JARVIS-artiger Kontext mit Alternativen.

        Phase 11: Statt generischem "Fenster offen" liefert dies Erklaerung + Vorschlag.

        Args:
            pushback: Dict mit warnings-Liste aus get_pushback_context()

        Returns:
            Formatierter Warntext fuer den LLM-Prompt
        """
        warnings = pushback.get("warnings", [])
        if not warnings:
            return ""

        lines = [
            "SITUATIONSBEWUSSTSEIN — Erklaere dem User WARUM die Aktion problematisch "
            "sein koennte und schlage eine Alternative vor. Ton: Butler, nicht belehrend. "
            "Fuehre die Aktion trotzdem aus, aber erwaehne den Hinweis:"
        ]
        for w in warnings:
            detail = w.get("detail", "")
            alt = w.get("alternative", "")
            if alt:
                lines.append(f"- {detail}. Vorschlag: {alt}")
            else:
                lines.append(f"- {detail}")
        return "\n".join(lines)
