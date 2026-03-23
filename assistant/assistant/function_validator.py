"""
Function Validator - Prueft Function Calls auf Sicherheit und Plausibilitaet.
Verhindert gefaehrliche oder unsinnige Aktionen.

Feature 10: Daten-basierter Widerspruch — prueft Live-Daten vor Ausfuehrung
und liefert konkreten Pushback-Kontext (offene Fenster, leerer Raum, etc.).
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config

logger = logging.getLogger(__name__)

REDIS_PUSHBACK_KEY = "mha:pushback_overrides"
REDIS_SECURITY_AUDIT_KEY = "mha:security:audit"

# MCU Sprint 4: Security-critical function names
_SECURITY_ACTIONS = frozenset(
    {
        "lock_door",
        "unlock_door",
        "set_lock",
        "set_alarm",
        "arm_alarm",
        "disarm_alarm",
        "set_trust_level",
        "emergency_stop",
        "factory_reset",
    }
)


@dataclass
class ValidationResult:
    ok: bool
    needs_confirmation: bool = False
    reason: Optional[str] = None


class FunctionValidator:
    """Validiert Function Calls vor der Ausfuehrung."""

    def __init__(self):
        # Feature 10: HA-Client fuer Live-Daten-Pushback (gesetzt via set_ha_client)
        self.ha = None
        self.redis: Optional[aioredis.Redis] = None
        self._pushback_overrides: dict[str, list[float]] = {}
        self._pushback_lock = asyncio.Lock()

    @property
    def require_confirmation(self) -> set:
        """Liest require_confirmation live aus yaml_config (Hot-Reload-faehig)."""
        security = yaml_config.get("security", {})
        return set(security.get("require_confirmation", []))

    def set_ha_client(self, ha_client) -> None:
        """Setzt den HA-Client fuer Live-Daten-Abfragen (Feature 10)."""
        self.ha = ha_client

    def set_redis(self, redis_client: Optional[aioredis.Redis]) -> None:
        """Setzt den Redis-Client fuer Pushback-Learning."""
        self.redis = redis_client

    async def _load_pushback_overrides(self) -> None:
        """Laedt Pushback-Overrides aus Redis in den lokalen Cache."""
        if not self.redis:
            return
        try:
            raw = await self.redis.get(REDIS_PUSHBACK_KEY)
            if raw:
                raw = raw.decode() if isinstance(raw, bytes) else raw
                self._pushback_overrides = json.loads(raw)
        except Exception as e:
            logger.warning("Pushback-Overrides laden fehlgeschlagen: %s", e)

    async def _save_pushback_overrides(self) -> None:
        """Speichert Pushback-Overrides in Redis."""
        if not self.redis:
            return
        try:
            await self.redis.set(
                REDIS_PUSHBACK_KEY, json.dumps(self._pushback_overrides)
            )
        except Exception as e:
            logger.warning("Pushback-Overrides speichern fehlgeschlagen: %s", e)

    async def record_pushback_override(
        self, action_type: str, context_key: str
    ) -> None:
        """Zeichnet auf, dass der User einen Pushback uebergangen hat."""
        if not self.redis:
            return

        pushback_cfg = yaml_config.get("pushback", {})
        if not pushback_cfg.get("learning_enabled", True):
            return

        async with self._pushback_lock:
            await self._load_pushback_overrides()

            key = f"{action_type}:{context_key}"
            now = time.time()
            suppress_days = pushback_cfg.get("suppress_duration_days", 30)
            cutoff = now - (suppress_days * 86400)

            timestamps = self._pushback_overrides.get(key, [])
            timestamps = [t for t in timestamps if t > cutoff]
            timestamps.append(now)
            self._pushback_overrides[key] = timestamps

            await self._save_pushback_overrides()
            logger.debug(
                "Pushback-Override aufgezeichnet: %s (count=%d)", key, len(timestamps)
            )

    async def is_pushback_suppressed(self, action_type: str, context_key: str) -> bool:
        """Prueft ob ein Pushback unterdrueckt werden soll (zu oft uebergangen)."""
        pushback_cfg = yaml_config.get("pushback", {})
        if not pushback_cfg.get("learning_enabled", True):
            return False

        async with self._pushback_lock:
            await self._load_pushback_overrides()

            key = f"{action_type}:{context_key}"
            timestamps = self._pushback_overrides.get(key, [])
            if not timestamps:
                return False

            suppress_days = pushback_cfg.get("suppress_duration_days", 30)
            cutoff = time.time() - (suppress_days * 86400)
            recent = [t for t in timestamps if t > cutoff]

            suppress_after = pushback_cfg.get("suppress_after_overrides", 5)
            if len(recent) >= suppress_after:
                logger.debug(
                    "Pushback unterdrueckt: %s (%d Overrides)", key, len(recent)
                )
                return True
            return False

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

        # MCU Sprint 4: Security Audit Log for critical actions
        if function_name in _SECURITY_ACTIONS:
            self._log_security_action(function_name, arguments)

        # Spezifische Validierungen
        validator = getattr(self, f"_validate_{function_name}", None)
        if validator:
            result = validator(arguments)
            if function_name in _SECURITY_ACTIONS:
                self._log_security_action(
                    function_name,
                    arguments,
                    result="blocked" if not result.ok else "validated",
                )
            return result

        return ValidationResult(ok=True)

    def _log_security_action(
        self, action: str, args: dict, result: str = "attempted", person: str = ""
    ) -> None:
        """MCU Sprint 4: Logs security action to Redis audit trail."""
        if not self.redis:
            return
        try:
            from datetime import datetime, timezone

            entry = json.dumps(
                {
                    "action": action,
                    "person": person or args.get("person", "unknown"),
                    "result": result,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "entity": args.get("entity_id", ""),
                }
            )
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._async_audit_log(entry))
            task.add_done_callback(
                lambda t: logger.warning("Fire-and-forget Task fehlgeschlagen: %s", t.exception()) if not t.cancelled() and t.exception() else None
            )
        except RuntimeError:
            pass  # No event loop

    async def _async_audit_log(self, entry: str) -> None:
        """Writes audit entry to Redis list."""
        await self.redis.lpush(REDIS_SECURITY_AUDIT_KEY, entry)
        await self.redis.ltrim(REDIS_SECURITY_AUDIT_KEY, 0, 499)  # Max 500
        await self.redis.expire(REDIS_SECURITY_AUDIT_KEY, 7776000)  # 90 days

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
                return ValidationResult(
                    ok=False, reason=f"Offset '{offset}' ist keine gueltige Zahl"
                )
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
                return ValidationResult(
                    ok=False, reason=f"Temperatur '{temp}' ist keine gueltige Zahl"
                )
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
                "dunkler": "dimmer",
                "dimmer": "dimmer",
                "heller": "brighter",
                "brighter": "brighter",
            }
            if (
                isinstance(brightness, str)
                and brightness.lower() in _brightness_to_state
            ):
                args["state"] = _brightness_to_state[brightness.lower()]
                del args["brightness"]
                return ValidationResult(ok=True)
            try:
                brightness = int(brightness)
            except (ValueError, TypeError):
                return ValidationResult(
                    ok=False,
                    reason=f"Helligkeit '{brightness}' ist keine gueltige Zahl",
                )
            # LLM sendet manchmal 0-255 (HA-Skala) statt 0-100 (Prozent)
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
                return ValidationResult(
                    ok=False, reason=f"Position '{position}' ist keine gueltige Zahl"
                )
            if position < 0 or position > 100:
                return ValidationResult(
                    ok=False,
                    reason=f"Position {position}% ausserhalb 0-100",
                )
        return ValidationResult(ok=True)

    # ------------------------------------------------------------------
    # Feature 10: Daten-basierter Widerspruch (Live-Pushback)
    # ------------------------------------------------------------------

    async def get_pushback_context(self, func_name: str, args: dict) -> Optional[dict]:
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
            result = await checker(args, pushback_cfg.get("checks", {}))
        except Exception as e:
            logger.debug("Pushback-Check fehlgeschlagen fuer %s: %s", func_name, e)
            return None

        if not result or not result.get("warnings"):
            return None

        room = (args.get("room") or "").lower()
        filtered = []
        for w in result["warnings"]:
            wtype = w.get("type", "")
            ctx = w.get("room", room) or wtype
            if await self.is_pushback_suppressed(func_name, f"{wtype}:{ctx}"):
                continue
            filtered.append(w)

        if not filtered:
            return None
        result["warnings"] = filtered
        result["severity"] = self._calculate_severity(filtered)
        return result

    async def _pushback_set_climate(self, args: dict, checks: dict) -> Optional[dict]:
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
            from .function_calling import (
                is_heating_relevant_opening,
                get_opening_sensor_config,
            )

            for state in states:
                eid = state.get("entity_id", "")
                if not is_heating_relevant_opening(eid, state):
                    continue
                if state.get("state") != "on":
                    continue
                # Raum-Match: opening_sensors Config oder friendly_name Fallback
                cfg = get_opening_sensor_config(eid)
                sensor_room = (cfg.get("room") or "").lower()
                friendly = (
                    state.get("attributes", {}).get("friendly_name") or eid
                ).lower()
                if sensor_room == room or (not sensor_room and room in friendly):
                    window_name = state.get("attributes", {}).get("friendly_name", eid)
                    target_t = args.get("temperature", "?")
                    warnings.append(
                        {
                            "type": "open_window",
                            "detail": f"{window_name} ist offen",
                            "room": room,
                            "alternative": f"Erst {window_name} schliessen, dann Heizung auf {target_t}°C",
                        }
                    )

        # Check: Niemand im Raum?
        if checks.get("empty_room", True):
            room_occupied = False
            for state in states:
                eid = state.get("entity_id", "")
                if not eid.startswith("binary_sensor.motion"):
                    continue
                friendly = (
                    state.get("attributes", {}).get("friendly_name") or eid
                ).lower()
                if room in friendly and state.get("state") == "on":
                    room_occupied = True
                    break
            if not room_occupied:
                # Nur warnen wenn kein Motion in den letzten Minuten
                warnings.append(
                    {
                        "type": "empty_room",
                        "detail": f"Kein Bewegungsmelder aktiv in {room.title()}",
                        "room": room,
                        "alternative": "Absenktemperatur (18°C) setzen oder Timer fuer 30 Minuten",
                    }
                )

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
                            outside_temp = float(
                                state.get("attributes", {}).get("temperature", 0)
                            )
                            if outside_temp >= 20:
                                warnings.append(
                                    {
                                        "type": "unnecessary_heating",
                                        "detail": f"Draussen sind es {outside_temp}°C",
                                        "alternative": "Fenster oeffnen statt heizen — draussen warm genug",
                                    }
                                )
                        except (ValueError, TypeError):
                            pass
                        break

        # Phase 2B: Spitzenstrom-Warnung bei hoher Heiz-Temperatur
        if checks.get("peak_tariff", True):
            _target = args.get("temperature")
            if _target:
                try:
                    _t = float(_target)
                except (ValueError, TypeError):
                    _t = 0
                if _t >= 23:
                    for state in states:
                        eid = state.get("entity_id", "")
                        if (
                            "tariff" in eid
                            or "strompreis" in eid
                            or "electricity_price" in eid
                        ):
                            try:
                                price = float(state.get("state", 0))
                                if price > 0.30:
                                    warnings.append(
                                        {
                                            "type": "peak_tariff",
                                            "detail": f"Strompreis aktuell {price:.2f} EUR/kWh (Spitze)",
                                            "alternative": f"Guenstiger in 1-2h oder {_t - 2:.0f}°C setzen",
                                        }
                                    )
                            except (ValueError, TypeError):
                                pass
                            break

        result = {"warnings": warnings} if warnings else None
        if result:
            result["severity"] = self._calculate_severity(warnings)
        return result

    async def _pushback_set_light(self, args: dict, checks: dict) -> Optional[dict]:
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

        _daylight_enabled = _fv_yaml_config.get("lighting", {}).get(
            "daylight_off", True
        )
        if _daylight_enabled and checks.get("daylight", True):
            for state in states:
                eid = state.get("entity_id", "")
                if eid == "sun.sun":
                    elevation = state.get("attributes", {}).get("elevation", 0)
                    try:
                        if float(elevation) > 25:
                            warnings.append(
                                {
                                    "type": "daylight",
                                    "detail": f"Die Sonne steht hoch (Elevation {elevation}°)",
                                }
                            )
                    except (ValueError, TypeError):
                        pass
                    break

        result = {"warnings": warnings} if warnings else None
        if result:
            result["severity"] = self._calculate_severity(warnings)
        return result

    async def _pushback_set_cover(self, args: dict, checks: dict) -> Optional[dict]:
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
                warnings.append(
                    {
                        "type": "storm_warning",
                        "detail": f"Starker Wind mit {wind_speed} km/h",
                        "alternative": "Rolllaeden geschlossen lassen zum Schutz",
                    }
                )

        # Rollladen hoch bei extremer Kaelte
        if is_opening and outside_temp is not None and outside_temp < 0:
            warnings.append(
                {
                    "type": "cold_outside",
                    "detail": f"Aussentemperatur {outside_temp}°C — Kaelte kommt rein",
                    "alternative": "Rollladen auf 20% — Licht rein, Isolierung bleibt",
                }
            )

        # Phase 2B: Solar-Ertrag-Verlust bei geschlossenen Rollladen
        is_closing = not is_opening
        if is_closing and checks.get("solar_loss", True):
            for state in states:
                eid = state.get("entity_id", "")
                if "solar" in eid or "pv" in eid or "photovoltaic" in eid:
                    try:
                        power = float(state.get("state", 0))
                        if power > 100:  # > 100W Solar-Produktion
                            warnings.append(
                                {
                                    "type": "solar_loss",
                                    "detail": f"Solar produziert gerade {power:.0f}W",
                                    "alternative": "Rollladen offen lassen — Solar-Ertrag maximieren",
                                }
                            )
                    except (ValueError, TypeError):
                        pass
                    break

        # Markise bei Regen/Wind
        cover_type = args.get("type", "")
        is_markise = cover_type == "markise" or room == "markisen"
        if is_markise and is_opening:
            rain_conditions = {"rainy", "pouring", "hail", "lightning-rainy"}
            if condition in rain_conditions:
                warnings.append(
                    {
                        "type": "rain_markise",
                        "detail": f"Wetter: {condition} — Markise wird nass/beschaedigt",
                        "alternative": "Markise eingefahren lassen",
                    }
                )
            if wind_speed >= 40:
                warnings.append(
                    {
                        "type": "wind_markise",
                        "detail": f"Wind {wind_speed} km/h — Markise kann beschaedigt werden",
                        "alternative": "Markise erst bei Windstille ausfahren",
                    }
                )

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
        "solar_loss": 2,
        "peak_tariff": 2,
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

    def check_state_age(
        self, entity_id: str, last_changed: str, max_age_minutes: int = 10
    ) -> bool:
        """Prueft ob der State aktuell genug fuer Pushback ist.

        Veraltete States (>10min) sollten keinen Pushback ausloesen,
        da sich die Situation geaendert haben koennte.
        """
        try:
            from datetime import datetime, timezone

            last = datetime.fromisoformat(last_changed.replace("Z", "+00:00"))
            age_minutes = (datetime.now(timezone.utc) - last).total_seconds() / 60
            return age_minutes <= max_age_minutes
        except (ValueError, TypeError):
            return True  # Im Zweifel Pushback erlauben
