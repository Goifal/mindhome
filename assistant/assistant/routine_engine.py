"""
Routine Engine - Phase 7: Jarvis strukturiert deinen Tag.

Orchestriert wiederkehrende Routinen:
- Morning Briefing: Begruessung + Wetter + Kalender + Haus-Status
- Gute-Nacht: Sicherheits-Check + Morgen-Vorschau + Haus herunterfahren
- Abschied/Willkommen: Kontext-sensitives Verhalten bei Gehen/Kommen

Nutzt bestehende Module:
- context_builder.py fuer Haus-Status
- proactive.py fuer Event-Delivery
- function_calling.py fuer Aktionen
- personality.py fuer Stil und Begruessungen
"""

import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import Optional

# F-050: DST limitation — datetime.now() returns naive (timezone-unaware) datetimes.
# During DST transitions (spring forward / fall back), routines scheduled by wall-clock
# hour may fire twice, be skipped, or shift by one hour. To fix properly, use
# timezone-aware datetimes throughout:
#   from zoneinfo import ZoneInfo
#   now = datetime.now(ZoneInfo("Europe/Berlin"))
# This requires propagating tz-aware datetimes to all Redis timestamps and comparisons.

import redis.asyncio as redis

from .config import settings, yaml_config, get_person_title
from .ha_client import HomeAssistantClient
from .ollama_client import OllamaClient
from .websocket import emit_speaking

logger = logging.getLogger(__name__)

# Redis Keys
KEY_LAST_BRIEFING = "mha:routine:last_briefing"
KEY_LAST_GOODNIGHT = "mha:routine:last_goodnight"
KEY_MORNING_DONE = "mha:routine:morning_done_today"
KEY_GREETING_HISTORY = "mha:routine:greeting_history"
KEY_ABSENCE_LOG = "mha:routine:absence_log"
KEY_GUEST_MODE = "mha:routine:guest_mode"
KEY_VACATION_SIM = "mha:routine:vacation_simulation"


class RoutineEngine:
    """Orchestriert taeglich wiederkehrende Routinen."""

    def __init__(self, ha_client: HomeAssistantClient, ollama: OllamaClient):
        self.ha = ha_client
        self.ollama = ollama
        self.redis: Optional[redis.Redis] = None
        self._executor = None  # Wird von brain.py gesetzt
        self._personality = None  # Wird von brain.py gesetzt
        self._semantic_memory = None  # Wird von brain.py gesetzt
        self._vacation_task: Optional[asyncio.Task] = None

        # Konfiguration
        routines_cfg = yaml_config.get("routines", {})

        # Morning Briefing Config
        mb_cfg = routines_cfg.get("morning_briefing", {})
        self.briefing_enabled = mb_cfg.get("enabled", True)
        self.briefing_modules = mb_cfg.get("modules", [
            "greeting", "weather", "calendar", "house_status", "travel",
        ])
        self.weekday_style = mb_cfg.get("weekday_style", "kurz")
        self.weekend_style = mb_cfg.get("weekend_style", "ausfuehrlich")
        self.morning_actions = mb_cfg.get("morning_actions", {})

        # Good Night Config
        gn_cfg = routines_cfg.get("good_night", {})
        self.goodnight_enabled = gn_cfg.get("enabled", True)
        self.goodnight_triggers = gn_cfg.get("triggers", [
            "gute nacht", "ich gehe schlafen", "schlaf gut",
        ])
        self.goodnight_checks = gn_cfg.get("checks", [
            "windows", "doors", "alarm", "lights",
        ])
        self.goodnight_actions = gn_cfg.get("actions", {})

        # Guest Mode Config
        gm_cfg = routines_cfg.get("guest_mode", {})
        self.guest_triggers = gm_cfg.get("triggers", [
            "ich habe besuch", "ich hab besuch", "gaeste kommen",
        ])
        self.guest_restrictions = gm_cfg.get("restrictions", {})

        logger.info("RoutineEngine initialisiert")

    async def initialize(self, redis_client: Optional[redis.Redis] = None):
        """Initialisiert mit Redis."""
        self.redis = redis_client

    def set_executor(self, executor):
        """Setzt den FunctionExecutor fuer Aktionen."""
        self._executor = executor

    def set_personality(self, personality):
        """Setzt die PersonalityEngine fuer personality-konsistente Prompts."""
        self._personality = personality

    # ------------------------------------------------------------------
    # Morning Briefing (Feature 7.1)
    # ------------------------------------------------------------------

    async def generate_morning_briefing(self, person: str = "", force: bool = False) -> dict:
        """
        Generiert ein Morning Briefing.

        Args:
            person: Name der Person
            force: True = Redis-Sperre ignorieren (manueller Request)

        Returns:
            Dict mit:
                text: str - Briefing-Text
                actions: list - Ausgefuehrte Begleit-Aktionen
        """
        if not self.briefing_enabled:
            return {"text": "", "actions": []}

        # Check: Heute schon gebrieft? (nur bei Auto-Trigger, nicht bei manuellem Request)
        if not force and self.redis:
            today = datetime.now().strftime("%Y-%m-%d")
            done = await self.redis.get(KEY_MORNING_DONE)
            if done is not None:
                done = done.decode() if isinstance(done, bytes) else done
            if done == today:
                logger.info("Morning Briefing bereits heute ausgefuehrt")
                return {"text": "", "actions": []}

        # Bausteine sammeln
        parts = []
        now = datetime.now()
        is_weekend = now.weekday() >= 5
        style = self.weekend_style if is_weekend else self.weekday_style

        for module in self.briefing_modules:
            content = await self._get_briefing_module(module, person, style)
            if content:
                parts.append(content)

        if not parts:
            return {"text": "", "actions": []}

        # LLM formuliert das Briefing natuerlich
        briefing_prompt = self._build_briefing_prompt(parts, style, person, now)
        try:
            response = await self.ollama.chat(
                messages=[
                    {"role": "system", "content": self._get_briefing_system_prompt(style)},
                    {"role": "user", "content": briefing_prompt},
                ],
                model=settings.model_fast,
            )
            text = response.get("message", {}).get("content", "")
        except Exception as e:
            logger.error("Morning Briefing LLM Fehler: %s", e)
            text = "\n".join(parts)

        # Begleit-Aktionen ausfuehren
        actions = await self._execute_morning_actions()

        # Als erledigt markieren
        if self.redis:
            try:
                today = datetime.now().strftime("%Y-%m-%d")
                await self.redis.setex(KEY_MORNING_DONE, 86400, today)
                await self.redis.setex(KEY_LAST_BRIEFING, 86400, now.isoformat())
            except Exception as e:
                logger.warning("Redis setex fuer Morning Briefing fehlgeschlagen: %s", e)

        logger.info("Morning Briefing generiert (%d Bausteine, %d Aktionen)", len(parts), len(actions))
        return {"text": text, "actions": actions}

    async def _get_briefing_module(self, module: str, person: str, style: str) -> str:
        """Holt Daten fuer einen Briefing-Baustein."""
        try:
            if module == "greeting":
                return await self._get_greeting_context(person)
            elif module == "weather":
                return await self._get_weather_briefing()
            elif module == "calendar":
                return await self._get_calendar_briefing()
            elif module == "energy":
                return await self._get_energy_briefing()
            elif module == "house_status":
                return await self._get_house_status_briefing()
            elif module == "travel":
                return await self.get_travel_briefing()
        except Exception as e:
            logger.debug("Briefing-Modul '%s' fehlgeschlagen: %s", module, e)
        return ""

    async def _get_greeting_context(self, person: str) -> str:
        """Kontextdaten fuer die Begruessung, inkl. Geburtstags-Check."""
        now = datetime.now()
        weekday = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"][now.weekday()]
        context = f"Tag: {weekday}, {now.strftime('%d.%m.%Y')}, {now.strftime('%H:%M')} Uhr"

        # Geburtstags-Check (YAML-Konfiguration)
        birthday = self._check_birthday(person, now)
        if birthday:
            context += f". {birthday}"

        # Semantic Memory: Heutige persoenliche Daten
        if self._semantic_memory:
            try:
                upcoming = await self._semantic_memory.get_upcoming_personal_dates(days_ahead=1)
                for entry in upcoming:
                    if entry["days_until"] == 0:
                        name = entry["person"].capitalize()
                        label = entry.get("label", "Geburtstag")
                        anni = entry.get("anniversary_years", 0)
                        # Nicht doppelt melden (YAML + Semantic)
                        if name.lower() in context.lower():
                            continue
                        if entry.get("date_type") == "birthday" and anni:
                            context += f". {name} hat heute {label} ({anni}. Geburtstag)"
                        elif entry.get("date_type") == "birthday":
                            context += f". {name} hat heute {label}"
                        else:
                            suffix = f" ({anni}.)" if anni else ""
                            context += f". Heute ist {label}{suffix}"
            except Exception as e:
                logger.debug("Semantic Memory Datumscheck fehlgeschlagen: %s", e)

        return context

    def _check_birthday(self, person: str, now: datetime) -> str:
        """Prueft ob heute jemand Geburtstag hat.

        Konfiguriert in settings.yaml unter persons.birthdays.
        """
        persons_cfg = yaml_config.get("persons", {})
        birthdays = persons_cfg.get("birthdays", {})

        today = now.strftime("%m-%d")
        messages = []

        for name, date_str in birthdays.items():
            # Format: "YYYY-MM-DD" oder "MM-DD"
            try:
                parsed_date = datetime.strptime(date_str, "%Y-%m-%d")
                bday = parsed_date.strftime("%m-%d")
            except (ValueError, TypeError):
                bday = date_str[-5:] if len(date_str) > 5 else date_str
            if bday == today:
                if name.lower() == (person or "").lower():
                    try:
                        birth_year = int(date_str[:4]) if len(date_str) == 10 else None
                        age = now.year - birth_year if birth_year else None
                        age_text = f" ({age}. Geburtstag)" if age else ""
                        messages.append(f"GEBURTSTAG: {name} hat heute Geburtstag{age_text}")
                    except (ValueError, TypeError):
                        messages.append(f"GEBURTSTAG: {name} hat heute Geburtstag")
                else:
                    messages.append(f"GEBURTSTAG: {name} hat heute Geburtstag")

        return ". ".join(messages)

    async def _get_weather_briefing(self) -> str:
        """Holt Wetter-Daten.

        Nutzt weather.get_forecasts Service (HA 2024.3+) mit Fallback
        auf State-Attribute fuer aeltere HA-Versionen.
        """
        states = await self.ha.get_states()
        if not states:
            return ""

        # Weather-Entity finden
        weather_entity = None
        for state in states:
            if state.get("entity_id", "").startswith("weather."):
                weather_entity = state
                break

        if not weather_entity:
            return ""

        entity_id = weather_entity.get("entity_id", "")
        attrs = weather_entity.get("attributes", {})
        temp = attrs.get("temperature", "?")
        condition = weather_entity.get("state", "?")
        humidity = attrs.get("humidity", "?")
        wind_speed = attrs.get("wind_speed")

        # Wetter-Zustand uebersetzen
        condition_de = self._translate_weather(condition)
        result = f"Wetter: {temp}°C, {condition_de}, Luftfeuchtigkeit {humidity}%"
        if wind_speed:
            result += f", Wind {wind_speed} km/h"

        # Forecast holen via Service (HA 2024.3+)
        forecast = await self._get_forecast_via_service(entity_id)

        # Fallback: State-Attribute (aeltere HA-Versionen)
        if not forecast:
            forecast = attrs.get("forecast", [])

        if forecast:
            today_fc = forecast[0] if forecast else {}
            high = today_fc.get("temperature", "?")
            low = today_fc.get("templow", "?")
            fc_cond = self._translate_weather(today_fc.get("condition", ""))
            precipitation = today_fc.get("precipitation")
            parts = [f"Heute: {low}-{high}°C, {fc_cond}"]
            try:
                if precipitation and float(precipitation) > 0:
                    parts.append(f"{precipitation}mm Niederschlag")
            except (ValueError, TypeError):
                pass
            result += ". " + ", ".join(parts)

        return result

    async def _get_forecast_via_service(self, entity_id: str) -> list:
        """Holt Forecast ueber weather.get_forecasts Service (HA 2024.3+).

        Returns:
            Forecast-Liste oder leere Liste bei Fehler/alter HA-Version
        """
        try:
            result = await self.ha.call_service_with_response(
                "weather", "get_forecasts",
                {"entity_id": entity_id, "type": "daily"},
            )
            if not result:
                return []
            # HA gibt verschiedene Formate zurueck je nach Version
            # Format 1: [{entity_id: {forecast: [...]}}]
            if isinstance(result, list):
                for item in result:
                    if isinstance(item, dict):
                        for key, value in item.items():
                            if isinstance(value, dict) and "forecast" in value:
                                return value["forecast"]
            # Format 2: {entity_id: {forecast: [...]}}
            elif isinstance(result, dict):
                for key, value in result.items():
                    if isinstance(value, dict) and "forecast" in value:
                        return value["forecast"]
        except Exception as e:
            logger.debug("weather.get_forecasts nicht verfuegbar (aeltere HA?): %s", e)
        return []

    @staticmethod
    def _translate_weather(condition: str) -> str:
        """Uebersetzt HA Weather-Zustaende ins Deutsche."""
        translations = {
            "sunny": "sonnig",
            "clear-night": "klare Nacht",
            "partlycloudy": "teilweise bewoelkt",
            "cloudy": "bewoelkt",
            "rainy": "Regen",
            "pouring": "starker Regen",
            "snowy": "Schnee",
            "snowy-rainy": "Schneeregen",
            "fog": "Nebel",
            "hail": "Hagel",
            "lightning": "Gewitter",
            "lightning-rainy": "Gewitter mit Regen",
            "windy": "windig",
            "windy-variant": "windig und bewoelkt",
            "exceptional": "Ausnahmezustand",
        }
        return translations.get(condition, condition)

    async def _get_calendar_briefing(self) -> str:
        """Holt Kalender-Daten."""
        states = await self.ha.get_states()
        if not states:
            return ""
        events = []
        for state in states:
            entity_id = state.get("entity_id", "")
            if entity_id.startswith("calendar."):
                attrs = state.get("attributes", {})
                message = attrs.get("message", "")
                start = attrs.get("start_time", "")
                if message:
                    events.append(f"{start}: {message}" if start else message)
        if events:
            return "Termine: " + "; ".join(events[:3])
        return ""

    async def _get_energy_briefing(self) -> str:
        """Holt Energie-Daten: HA-Sensoren + MindHome Add-on Fallback."""
        parts = []

        # 1. Echte HA-Sensoren abfragen (Stromzaehler, Solar, Preis)
        try:
            states = await self.ha.get_states()
            if states:
                for state in states:
                    eid = state.get("entity_id", "")
                    attrs = state.get("attributes", {})
                    device_class = attrs.get("device_class", "")
                    value_str = state.get("state", "")
                    name = attrs.get("friendly_name", eid)
                    unit = attrs.get("unit_of_measurement", "")

                    try:
                        value = float(value_str)
                    except (ValueError, TypeError):
                        continue

                    # Gesamt-Stromverbrauch heute
                    if device_class == "energy" and "daily" in eid.lower():
                        parts.append(f"Verbrauch heute: {value:.1f} {unit}")

                    # Solar-Ertrag
                    elif "solar" in eid.lower() and device_class in ("energy", "power"):
                        if device_class == "power":
                            parts.append(f"Solar aktuell: {value:.0f} {unit}")
                        else:
                            parts.append(f"Solar-Ertrag: {value:.1f} {unit}")

                    # Strompreis (z.B. Tibber, aWATTar)
                    elif "price" in eid.lower() or "tarif" in eid.lower():
                        if "electricity" in eid.lower() or "strom" in eid.lower():
                            parts.append(f"Strompreis: {value:.2f} {unit}")
        except Exception as e:
            logger.debug("Energie-Sensoren Fehler: %s", e)

        # 2. Fallback: MindHome Add-on Daten
        if not parts:
            try:
                energy = await self.ha.get_energy()
                if energy:
                    solar = energy.get("solar_forecast", "")
                    price = energy.get("current_price", "")
                    if solar:
                        parts.append(f"Solar: {solar}")
                    if price:
                        parts.append(f"Strompreis: {price}")
            except Exception:
                pass

        return "Energie: " + ", ".join(parts) if parts else ""

    async def _get_house_status_briefing(self) -> str:
        """Holt den Haus-Status."""
        states = await self.ha.get_states()
        if not states:
            return ""

        parts = []
        # Temperaturen: Konfigurierte Sensoren (Mittelwert) bevorzugen
        rt_sensors = yaml_config.get("room_temperature", {}).get("sensors", []) or []
        if rt_sensors:
            state_map = {s.get("entity_id"): s for s in states}
            sensor_temps = []
            for sid in rt_sensors:
                st = state_map.get(sid, {})
                try:
                    sensor_temps.append(float(st.get("state", "")))
                except (ValueError, TypeError):
                    pass
            if sensor_temps:
                avg = round(sum(sensor_temps) / len(sensor_temps), 1)
                parts.append(f"Raumtemperatur: {avg}°C Durchschnitt")
        else:
            # Fallback: climate entities (gefiltert)
            for state in states:
                if state.get("entity_id", "").startswith("climate."):
                    attrs = state.get("attributes", {})
                    temp = attrs.get("current_temperature")
                    if temp is None:
                        continue
                    try:
                        temp_val = float(temp)
                        if temp_val < -20 or temp_val > 50:
                            continue
                    except (ValueError, TypeError):
                        continue
                    room = attrs.get("friendly_name", "?")
                    parts.append(f"{room}: {temp}°C")

        # Offene Fenster/Tueren — MindHome-Domain + device_class pruefen
        # statt keyword-matching (verhindert false positives wie Steckdosen)
        from .function_calling import is_window_or_door
        open_items = []
        for state in states:
            entity_id = state.get("entity_id", "")
            if is_window_or_door(entity_id, state) and state.get("state") == "on":
                name = state.get("attributes", {}).get("friendly_name", entity_id)
                open_items.append(name)
        if open_items:
            parts.append(f"Offen: {', '.join(open_items)}")

        # Lichter
        lights_on = sum(
            1 for s in states
            if s.get("entity_id", "").startswith("light.") and s.get("state") == "on"
        )
        if lights_on > 0:
            parts.append(f"Lichter an: {lights_on}")

        return "Haus: " + ", ".join(parts) if parts else ""

    def _build_briefing_prompt(
        self, parts: list[str], style: str, person: str, now: datetime
    ) -> str:
        """Baut den Prompt fuer das LLM um das Briefing zu formulieren."""
        title = get_person_title(person) if not person or person.lower() == settings.user_name.lower() else person
        prompt = f"Erstelle ein Morning Briefing fuer {title}.\n\n"
        prompt += "DATEN:\n"
        for part in parts:
            prompt += f"- {part}\n"
        prompt += f"\nStil: {style}. "
        if style == "kurz":
            prompt += "Maximal 3 Saetze. Nur das Wichtigste."
        else:
            prompt += "Bis 5 Saetze. Mehr Details, entspannter Ton."
        return prompt

    def _get_briefing_system_prompt(self, style: str) -> str:
        """System Prompt fuer das Morning Briefing.

        Nutzt die PersonalityEngine fuer personality-konsistente Prompts
        (Sarkasmus, Formality, Tageszeit-Stil) statt eines statischen Prompts.
        """
        if self._personality:
            try:
                return self._personality.build_routine_prompt(
                    routine_type="morning", style=style,
                )
            except Exception as e:
                logger.debug("Personality-Routine-Prompt fehlgeschlagen: %s", e)
        # Fallback
        return (
            f"Du bist {settings.assistant_name}, die KI dieses Hauses — J.A.R.V.I.S. aus dem MCU.\n"
            f"Erstelle ein Morning Briefing. Stil: {style}.\n"
            "Beginne mit kontextueller Begruessung. Dann Wetter, Termine, Haus-Status.\n"
            f'Sprich den Hauptbenutzer mit "{get_person_title()}" an. Deutsch. Butler-Stil.\n'
            "VERBOTEN: leider, Entschuldigung, Es tut mir leid, Wie kann ich helfen?, Gerne!, Natuerlich!"
        )

    async def _execute_morning_actions(self) -> list[dict]:
        """Fuehrt die Begleit-Aktionen beim Morning Briefing aus."""
        actions = []
        if not self._executor:
            return actions

        if self.morning_actions.get("covers_up", False):
            # Wakeup-Sequenz hat Rolllaeden schon hochgefahren?
            wakeup_done = False
            if self.redis:
                try:
                    today = datetime.now().strftime("%Y-%m-%d")
                    done = await self.redis.get("mha:routine:wakeup_done_today")
                    wakeup_done = bool(done and done.startswith(today))
                except Exception:
                    pass

            if wakeup_done:
                logger.info("Morning covers_up uebersprungen: Wakeup-Sequenz hat Rolllaeden schon gefahren")
            else:
                # Bettsensor pruefen: Wenn noch jemand im Bett liegt,
                # Rolllaeden NICHT hochfahren (Schlafzimmer-Schutz)
                bed_occupied = await self._is_bed_occupied()
                if bed_occupied:
                    logger.info("Morning covers_up uebersprungen: Bettsensor belegt")
                else:
                    result = await self._executor.execute("set_cover", {
                        "room": "all", "position": 100,
                    })
                    actions.append({"function": "set_cover", "result": result})

        if self.morning_actions.get("lights_soft", False):
            result = await self._executor.execute("set_light", {
                "room": "wohnzimmer", "state": "on", "brightness": 30,
            })
            actions.append({"function": "set_light", "result": result})

        return actions

    # ------------------------------------------------------------------
    # Aufwach-Sequenz (kontextreiches Aufwachen)
    # ------------------------------------------------------------------

    async def execute_wakeup_sequence(self, autonomy_level: int = 3) -> bool:
        """Fuehrt die stufenweise Aufwach-Sequenz aus.

        Rolllaeden stufenweise, sanftes Licht, Kaffee — dann Briefing.
        Nur einmal pro Tag, nur im Zeitfenster, nur bei ausreichendem Autonomie-Level.

        Returns:
            True wenn Sequenz ausgefuehrt wurde.
        """
        ws_cfg = yaml_config.get("routines", {}).get("morning_briefing", {}).get("wakeup_sequence", {})
        if not ws_cfg.get("enabled", False):
            return False

        min_level = ws_cfg.get("min_autonomy_level", 3)
        if autonomy_level < min_level:
            return False

        # Zeitfenster pruefen
        now = datetime.now()
        start_h = ws_cfg.get("window_start_hour", 5)
        end_h = ws_cfg.get("window_end_hour", 9)
        if not (start_h <= now.hour < end_h):
            return False

        # Nur einmal pro Tag
        if self.redis:
            today = now.strftime("%Y-%m-%d")
            flag_key = "mha:routine:wakeup_done_today"
            try:
                done = await self.redis.get(flag_key)
                if done and done.startswith(today):
                    return False
            except Exception:
                pass

        # Bettsensor pruefen
        bed_occupied = await self._is_bed_occupied()
        if bed_occupied:
            logger.info("Aufwach-Sequenz uebersprungen: Bettsensor belegt")
            return False

        logger.info("Aufwach-Sequenz gestartet")
        steps = ws_cfg.get("steps", {})

        # 1. Rolllaeden stufenweise oeffnen
        if steps.get("covers_gradual", {}).get("enabled", False):
            await self._wakeup_covers_gradual(steps["covers_gradual"])

        # 2. Sanftes Licht
        if steps.get("lights_soft", {}).get("enabled", False):
            await self._wakeup_lights_soft(steps["lights_soft"])

        # 3. Kaffeemaschine
        if steps.get("coffee_machine", {}).get("enabled", False):
            await self._wakeup_coffee(steps["coffee_machine"])

        # Flag setzen
        if self.redis:
            try:
                today = datetime.now().strftime("%Y-%m-%d")
                await self.redis.setex("mha:routine:wakeup_done_today", 86400, today)
            except Exception:
                pass

        logger.info("Aufwach-Sequenz abgeschlossen")
        return True

    async def _wakeup_covers_gradual(self, cfg: dict):
        """Rolllaeden stufenweise ueber X Minuten oeffnen."""
        if not self._executor:
            return

        room = cfg.get("room", "schlafzimmer")
        duration = cfg.get("duration_seconds", 180)
        interval = cfg.get("step_interval_seconds", 30)
        steps = max(1, duration // interval)
        step_size = 100 // steps

        for i in range(1, steps + 1):
            position = min(100, i * step_size)
            try:
                await self._executor.execute("set_cover", {
                    "room": room, "position": position,
                })
                logger.debug("Wakeup covers: %d%% (%s)", position, room)
            except Exception as e:
                logger.debug("Wakeup cover step fehlgeschlagen: %s", e)

            if i < steps:
                await asyncio.sleep(interval)

    async def _wakeup_lights_soft(self, cfg: dict):
        """Sanftes Aufwach-Licht einschalten."""
        if not self._executor:
            return

        room = cfg.get("room", "schlafzimmer")
        brightness = cfg.get("brightness", 20)
        transition = cfg.get("transition", 10)

        try:
            await self._executor.execute("set_light", {
                "room": room,
                "state": "on",
                "brightness": brightness,
                "transition": transition,
            })
            logger.debug("Wakeup light: %d%% in %s", brightness, room)
        except Exception as e:
            logger.debug("Wakeup light fehlgeschlagen: %s", e)

    async def _wakeup_coffee(self, cfg: dict):
        """Kaffeemaschine einschalten."""
        entity = cfg.get("entity", "")
        if not entity:
            return

        try:
            await self.ha.call_service(
                "homeassistant", "turn_on", entity_id=entity,
            )
            logger.info("Wakeup: Kaffeemaschine eingeschaltet (%s)", entity)
        except Exception as e:
            logger.debug("Wakeup coffee fehlgeschlagen: %s", e)

    async def _is_bed_occupied(self) -> bool:
        """Prueft ob ein Bettsensor belegt ist (fuer Cover-Schutz)."""
        activity_cfg = yaml_config.get("activity", {})
        bed_sensors = activity_cfg.get("entities", {}).get("bed_sensors", [
            "binary_sensor.bed_occupancy",
            "binary_sensor.bett",
        ])
        try:
            states = await self.ha.get_states()
            if not states:
                return False
            for state in states:
                if state.get("entity_id", "") in bed_sensors:
                    if state.get("state") == "on":
                        return True
        except Exception as e:
            logger.debug("Bettsensor-Check fehlgeschlagen: %s", e)
        return False

    # ------------------------------------------------------------------
    # Gute-Nacht-Routine (Feature 7.3)
    # ------------------------------------------------------------------

    def is_goodnight_intent(self, text: str) -> bool:
        """Prueft ob der Text ein Gute-Nacht-Intent ist."""
        text_lower = text.lower().strip()
        return any(trigger in text_lower for trigger in self.goodnight_triggers)

    async def execute_goodnight(self, person: str = "") -> dict:
        """
        Fuehrt die Gute-Nacht-Routine aus.

        Returns:
            Dict mit:
                text: str - Gute-Nacht-Text mit Vorschau + Status
                actions: list - Ausgefuehrte Aktionen
                issues: list - Offene Probleme (Fenster, Tueren)
        """
        if not self.goodnight_enabled:
            return {"text": f"Gute Nacht, {get_person_title(person)}. Alles unter Kontrolle.", "actions": [], "issues": []}

        # 1. Sicherheits-Check
        issues = await self._run_safety_checks()

        # 2. Morgen-Vorschau
        tomorrow_info = await self._get_tomorrow_preview()

        # 3. Aktionen ausfuehren (wenn keine kritischen Issues)
        actions = []
        if not any(i.get("critical", False) for i in issues):
            actions = await self._execute_goodnight_actions()

        # 4. LLM formuliert den Text
        text = await self._generate_goodnight_text(person, issues, tomorrow_info, actions)

        # Timestamp speichern
        if self.redis:
            await self.redis.setex(KEY_LAST_GOODNIGHT, 86400, datetime.now().isoformat())

        logger.info(
            "Gute-Nacht: %d Aktionen, %d Issues",
            len(actions), len(issues),
        )
        return {"text": text, "actions": actions, "issues": issues}

    async def _run_safety_checks(self) -> list[dict]:
        """Prueft Fenster, Tueren, Alarm, Lichter vor dem Schlafen."""
        issues = []
        states = await self.ha.get_states()
        if not states:
            return issues

        for check in self.goodnight_checks:
            if check == "windows":
                from .function_calling import is_window_or_door
                for state in states:
                    eid = state.get("entity_id", "")
                    if is_window_or_door(eid, state) and state.get("state") == "on":
                        name = state.get("attributes", {}).get("friendly_name", eid)
                        issues.append({
                            "type": "window_open",
                            "entity": eid,
                            "name": name,
                            "message": f"{name} ist noch offen",
                            "critical": False,
                        })

            elif check == "doors":
                for state in states:
                    eid = state.get("entity_id", "")
                    if eid.startswith("lock.") and state.get("state") == "unlocked":
                        name = state.get("attributes", {}).get("friendly_name", eid)
                        issues.append({
                            "type": "door_unlocked",
                            "entity": eid,
                            "name": name,
                            "message": f"{name} ist nicht verriegelt",
                            "critical": True,
                        })

            elif check == "alarm":
                for state in states:
                    if state.get("entity_id", "").startswith("alarm_control_panel."):
                        if state.get("state") == "disarmed":
                            issues.append({
                                "type": "alarm_off",
                                "entity": state["entity_id"],
                                "name": "Alarmanlage",
                                "message": "Alarm ist deaktiviert",
                                "critical": False,
                            })

            elif check == "lights":
                lights_on = []
                for state in states:
                    eid = state.get("entity_id", "")
                    if eid.startswith("light.") and state.get("state") == "on":
                        name = state.get("attributes", {}).get("friendly_name", eid)
                        lights_on.append(name)
                if lights_on:
                    issues.append({
                        "type": "lights_on",
                        "name": ", ".join(lights_on),
                        "message": f"{len(lights_on)} Licht(er) noch an: {', '.join(lights_on)}",
                        "critical": False,
                    })

            elif check == "appliances":
                appliance_keywords = ["ofen", "herd", "buegeleisen", "iron", "oven"]
                for state in states:
                    eid = state.get("entity_id", "")
                    if any(kw in eid for kw in appliance_keywords) and state.get("state") == "on":
                        name = state.get("attributes", {}).get("friendly_name", eid)
                        issues.append({
                            "type": "appliance_on",
                            "entity": eid,
                            "name": name,
                            "message": f"{name} ist noch an!",
                            "critical": True,
                        })

        return issues

    async def _get_tomorrow_preview(self) -> str:
        """Holt eine Vorschau auf morgen."""
        parts = []

        # Wetter morgen
        states = await self.ha.get_states()
        if states:
            for state in states:
                if state.get("entity_id", "").startswith("weather."):
                    entity_id = state.get("entity_id", "")
                    # Forecast via Service (HA 2024.3+)
                    forecast = await self._get_forecast_via_service(entity_id)
                    # Fallback: State-Attribute
                    if not forecast:
                        forecast = state.get("attributes", {}).get("forecast", [])
                    if len(forecast) >= 2:
                        tomorrow = forecast[1]
                        temp_high = tomorrow.get("temperature", "?")
                        temp_low = tomorrow.get("templow", "?")
                        cond = self._translate_weather(tomorrow.get("condition", "?"))
                        precipitation = tomorrow.get("precipitation")
                        text = f"Morgen: {temp_low}-{temp_high}°C, {cond}"
                        try:
                            if precipitation and float(precipitation) > 0:
                                text += f", {precipitation}mm Niederschlag"
                        except (ValueError, TypeError):
                            pass
                        parts.append(text)
                    break

        # Kalender morgen
        # (vereinfacht — nutzt gleiche Calendar-Entities)
        if states:
            for state in states:
                eid = state.get("entity_id", "")
                if eid.startswith("calendar."):
                    attrs = state.get("attributes", {})
                    message = attrs.get("message", "")
                    start = attrs.get("start_time", "")
                    if message and start:
                        parts.append(f"Erster Termin: {start} - {message}")
                    break

        return ". ".join(parts) if parts else ""

    async def _execute_goodnight_actions(self) -> list[dict]:
        """Fuehrt die Gute-Nacht-Aktionen aus."""
        actions = []
        if not self._executor:
            return actions

        gn_actions = self.goodnight_actions

        if gn_actions.get("lights_off", False):
            try:
                result = await self._executor.execute("set_light", {
                    "room": "all", "state": "off",
                })
                actions.append({"function": "set_light:off", "result": result})
            except Exception as e:
                logger.warning("Gute-Nacht Lichter-aus fehlgeschlagen: %s", e)
                actions.append({"function": "set_light:off", "result": {"error": str(e)}})

        if gn_actions.get("heating_night", False):
            try:
                heating = yaml_config.get("heating", {})
                if heating.get("mode") == "heating_curve":
                    night_offset = heating.get("night_offset", -2)
                    result = await self._executor.execute("set_climate", {
                        "offset": night_offset,
                    })
                else:
                    result = await self._executor.execute("set_climate", {
                        "room": "schlafzimmer", "temperature": 18,
                    })
                actions.append({"function": "set_climate:night", "result": result})
            except Exception as e:
                logger.warning("Gute-Nacht Heizung-Nacht fehlgeschlagen: %s", e)
                actions.append({"function": "set_climate:night", "result": {"error": str(e)}})

        if gn_actions.get("covers_down", False):
            try:
                result = await self._executor.execute("set_cover", {
                    "room": "all", "position": 0,
                })
                actions.append({"function": "set_cover:down", "result": result})
            except Exception as e:
                logger.warning("Gute-Nacht Rolllaeden-runter fehlgeschlagen: %s", e)
                actions.append({"function": "set_cover:down", "result": {"error": str(e)}})

        if gn_actions.get("alarm_arm_home", False):
            try:
                result = await self._executor.execute("arm_security_system", {
                    "mode": "arm_home",
                })
                actions.append({"function": "arm_security_system:arm_home", "result": result})
            except Exception as e:
                logger.warning("Gute-Nacht Alarmanlage fehlgeschlagen: %s", e)
                actions.append({"function": "arm_security_system:arm_home", "result": {"error": str(e)}})

        return actions

    async def _generate_goodnight_text(
        self, person: str, issues: list[dict],
        tomorrow_info: str, actions: list[dict],
    ) -> str:
        """Generiert den Gute-Nacht-Text via LLM."""
        title = get_person_title(person) if not person or person.lower() == settings.user_name.lower() else person

        parts = []
        if tomorrow_info:
            parts.append(f"Morgen-Vorschau: {tomorrow_info}")

        if issues:
            issue_texts = [i["message"] for i in issues]
            parts.append(f"Offene Punkte: {'; '.join(issue_texts)}")
        else:
            parts.append("Sicherheits-Check: Alles in Ordnung.")

        if actions:
            action_names = [a["function"] for a in actions]
            parts.append(f"Ausgefuehrt: {', '.join(action_names)}")

        prompt = f"Gute-Nacht fuer {title}.\n\nDATEN:\n"
        for p in parts:
            prompt += f"- {p}\n"
        prompt += "\nFormuliere eine kurze Gute-Nacht-Zusammenfassung. Max 3 Saetze."
        prompt += "\nBei offenen Fenster/Tueren: Erwaehne und frage ob so lassen."
        prompt += "\nBei kritischen Issues: Deutlich warnen."

        # Personality-konsistenter Prompt (Sarkasmus, Formality, Tageszeit)
        if self._personality:
            try:
                system_prompt = self._personality.build_routine_prompt(
                    routine_type="goodnight",
                )
            except Exception:
                title = get_person_title(person)
                system_prompt = (
                    f"Du bist {settings.assistant_name}. Butler-Stil, kurz, trocken. Deutsch. "
                    f"Sprich den User mit '{title}' an. Kein unterwuerfiger Ton."
                )
        else:
            title = get_person_title(person)
            system_prompt = (
                f"Du bist {settings.assistant_name}. Butler-Stil, kurz, trocken. Deutsch. "
                f"Sprich den User mit '{title}' an. Kein unterwuerfiger Ton."
            )
        try:
            response = await self.ollama.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                model=settings.model_fast,
            )
            return response.get("message", {}).get("content", f"Gute Nacht, {get_person_title(person)}. Systeme fahren runter.")
        except Exception as e:
            logger.error("Gute-Nacht LLM Fehler: %s", e)
            # Fallback ohne LLM
            text = f"Gute Nacht, {get_person_title(person)}"
            if issues:
                text += f". Noch offen: {issues[0]['message']}"
            return text + "."

    # ------------------------------------------------------------------
    # Gaeste-Modus (Feature 7.6)
    # ------------------------------------------------------------------

    def is_guest_trigger(self, text: str) -> bool:
        """Prueft ob der Text den Gaeste-Modus aktiviert."""
        text_lower = text.lower().strip()
        return any(trigger in text_lower for trigger in self.guest_triggers)

    async def activate_guest_mode(self) -> str:
        """Aktiviert den Gaeste-Modus.

        F-049: TTL auf 24h begrenzt (statt 7 Tage), um versehentliches
        Haengenbleiben zu verhindern. Kann jederzeit neu aktiviert werden.
        """
        # F-049: Max 24h statt 7 Tage — verhindert Stuck-Guest-Mode
        guest_ttl = int(self.guest_restrictions.get("max_duration_hours", 24)) * 3600
        if self.redis:
            try:
                await self.redis.setex(KEY_GUEST_MODE, guest_ttl, "active")
            except Exception as e:
                logger.warning("Guest-Mode Redis-Fehler: %s", e)
        logger.info("Gaeste-Modus aktiviert")

        parts = ["Gaeste-Modus aktiviert."]

        # Gaeste-WLAN automatisch aktivieren wenn konfiguriert
        wifi_cfg = self.guest_restrictions.get("guest_wifi", {})
        if wifi_cfg.get("auto_enable", False) and self._executor:
            try:
                wifi_entity = wifi_cfg.get("switch_entity", "switch.guest_wifi")
                result = await self._executor.execute("call_service", {
                    "domain": "switch",
                    "service": "turn_on",
                    "entity_id": wifi_entity,
                })
                ssid = wifi_cfg.get("ssid", "Gast")
                password = wifi_cfg.get("password", "")
                parts.append(f"Gaeste-WLAN '{ssid}' ist aktiv.")
                if password:
                    parts.append(f"Passwort: {password}")
                logger.info("Gaeste-WLAN aktiviert: %s", wifi_entity)
            except Exception as e:
                logger.warning("Gaeste-WLAN konnte nicht aktiviert werden: %s", e)
                parts.append("Gaeste-WLAN konnte ich nicht aktivieren.")
        elif self.guest_restrictions.get("suggest_guest_wifi"):
            parts.append("Soll ich das Gaeste-WLAN aktivieren?")

        return " ".join(parts)

    async def activate_guest_wifi(self) -> str:
        """Aktiviert das Gaeste-WLAN explizit (auf User-Befehl)."""
        wifi_cfg = self.guest_restrictions.get("guest_wifi", {})
        wifi_entity = wifi_cfg.get("switch_entity", "switch.guest_wifi")

        if not self._executor:
            return "Kein Executor verfuegbar."

        try:
            await self._executor.execute("call_service", {
                "domain": "switch",
                "service": "turn_on",
                "entity_id": wifi_entity,
            })
            ssid = wifi_cfg.get("ssid", "Gast")
            password = wifi_cfg.get("password", "")
            msg = f"Gaeste-WLAN '{ssid}' ist jetzt aktiv."
            if password:
                msg += f" Passwort: {password}"
            return msg
        except Exception as e:
            logger.error("Gaeste-WLAN Fehler: %s", e)
            return "Das Gaeste-WLAN konnte nicht aktiviert werden."

    async def deactivate_guest_wifi(self) -> str:
        """Deaktiviert das Gaeste-WLAN."""
        wifi_cfg = self.guest_restrictions.get("guest_wifi", {})
        wifi_entity = wifi_cfg.get("switch_entity", "switch.guest_wifi")

        if not self._executor:
            return "Kein Executor verfuegbar."

        try:
            await self._executor.execute("call_service", {
                "domain": "switch",
                "service": "turn_off",
                "entity_id": wifi_entity,
            })
            return "Gaeste-WLAN deaktiviert."
        except Exception as e:
            logger.error("Gaeste-WLAN Fehler: %s", e)
            return "Das Gaeste-WLAN konnte nicht deaktiviert werden."

    async def deactivate_guest_mode(self) -> str:
        """Deaktiviert den Gaeste-Modus."""
        if self.redis:
            try:
                await self.redis.delete(KEY_GUEST_MODE)
            except Exception as e:
                logger.warning("Guest-Mode Redis-Fehler: %s", e)
        logger.info("Gaeste-Modus deaktiviert")
        return "Gaeste-Modus beendet. Zurueck zum Normalbetrieb."

    async def is_guest_mode_active(self) -> bool:
        """Prueft ob der Gaeste-Modus aktiv ist."""
        if not self.redis:
            return False
        try:
            val = await self.redis.get(KEY_GUEST_MODE)
            if val is not None and isinstance(val, bytes):
                val = val.decode()
            return val == "active"
        except Exception as e:
            logger.debug("Guest-Mode Check fehlgeschlagen: %s", e)
            return False

    def get_guest_mode_prompt(self) -> str:
        """Gibt den Prompt-Zusatz fuer den Gaeste-Modus zurueck."""
        restrictions = self.guest_restrictions
        parts = ["GAESTE-MODUS AKTIV:"]
        if restrictions.get("hide_personal_info"):
            parts.append("- Keine persoenlichen Infos preisgeben (Kalender, Gewohnheiten, etc.)")
        if restrictions.get("formal_tone"):
            parts.append("- Formeller Ton. Kein Insider-Humor.")
        if restrictions.get("restrict_security"):
            parts.append("- Kein Zugriff auf Alarm, Tuerschloesser, Sicherheitskameras.")
        parts.append("- Bei persoenlichen Fragen: Hoeflich ablehnen.")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Abwesenheits-Log (Feature 7.8)
    # ------------------------------------------------------------------

    async def log_absence_event(self, event_type: str, description: str):
        """Loggt ein Event waehrend der Abwesenheit."""
        if not self.redis:
            return
        now = datetime.now().isoformat()
        entry = f"{now}|{event_type}|{description}"
        await self.redis.rpush(KEY_ABSENCE_LOG, entry)
        await self.redis.expire(KEY_ABSENCE_LOG, 30 * 86400)

    async def get_absence_summary(self) -> str:
        """Gibt eine Zusammenfassung der Events waehrend der Abwesenheit zurueck."""
        if not self.redis:
            return ""

        entries = await self.redis.lrange(KEY_ABSENCE_LOG, 0, -1)
        if not entries:
            return ""

        # Events parsen und filtern
        events = []
        for entry in entries:
            parts = entry.split("|", 2)
            if len(parts) == 3:
                events.append({
                    "time": parts[0],
                    "type": parts[1],
                    "description": parts[2],
                })

        if not events:
            return ""

        # Phase 7.8: Relevanz-Filter — unwichtige Events herausfiltern
        irrelevant_types = {"motion_idle", "sensor_update", "heartbeat", "ping"}
        noise_keywords = ["unavailable", "unknown", "idle", "standby"]
        filtered = []
        for e in events:
            # Typ-basierter Filter
            if e["type"] in irrelevant_types:
                continue
            # Keyword-basierter Noise-Filter
            desc_lower = e["description"].lower()
            if any(kw in desc_lower for kw in noise_keywords):
                continue
            filtered.append(e)

        # Deduplizierung: Gleiche Events zusammenfassen
        seen_descs = set()
        deduplicated = []
        for e in filtered:
            desc_key = e["type"] + ":" + e["description"][:50]
            if desc_key not in seen_descs:
                seen_descs.add(desc_key)
                deduplicated.append(e)

        events = deduplicated
        if not events:
            return ""

        # LLM fasst zusammen
        event_text = "\n".join(
            f"- {e['time'][:16]}: {e['description']}" for e in events
        )
        try:
            response = await self.ollama.chat(
                messages=[
                    {"role": "system", "content": f"Du bist {settings.assistant_name}. "
                     "Fasse Events waehrend der Abwesenheit zusammen. "
                     "Kurz, nur Relevantes. Max 2 Saetze. Deutsch. Butler-Stil."},
                    {"role": "user", "content": f"Events waehrend der Abwesenheit:\n{event_text}"},
                ],
                model=settings.model_fast,
            )
            summary = response.get("message", {}).get("content", "")
        except Exception as e:
            logger.error("Abwesenheits-Summary Fehler: %s", e)
            summary = f"{len(events)} Events waehrend der Abwesenheit."

        # Log loeschen nach Zusammenfassung
        await self.redis.delete(KEY_ABSENCE_LOG)

        return summary

    # ------------------------------------------------------------------
    # Abwesenheits-Simulation (Vacation Mode)
    # ------------------------------------------------------------------

    async def start_vacation_simulation(self) -> str:
        """Startet die Abwesenheits-Simulation.

        Simuliert Anwesenheit durch zufaellige Licht/Rolladen-Aktionen
        basierend auf typischen Tagesablaeufen.
        """
        if not self.redis:
            return "Redis nicht verfuegbar fuer Abwesenheits-Simulation."

        await self.redis.setex(KEY_VACATION_SIM, 30 * 86400, "active")
        self._vacation_task = asyncio.create_task(self._run_vacation_simulation())
        logger.info("Abwesenheits-Simulation gestartet")
        return f"Ich werde dafuer sorgen, dass das Haus bewohnt aussieht, {get_person_title()}."

    async def stop_vacation_simulation(self) -> str:
        """Stoppt die Abwesenheits-Simulation."""
        if self.redis:
            await self.redis.delete(KEY_VACATION_SIM)
        if hasattr(self, "_vacation_task") and self._vacation_task:
            self._vacation_task.cancel()
            try:
                await self._vacation_task
            except asyncio.CancelledError:
                pass
        logger.info("Abwesenheits-Simulation gestoppt")
        return f"Abwesenheits-Simulation beendet. Willkommen zurueck, {get_person_title()}."

    async def _run_vacation_simulation(self):
        """Hauptloop der Abwesenheits-Simulation."""
        sim_cfg = yaml_config.get("vacation_simulation", {})
        # Typische Zeiten (konfigurierbar)
        morning_lights = int(sim_cfg.get("morning_hour", 7))
        evening_lights = int(sim_cfg.get("evening_hour", 18))
        night_off = int(sim_cfg.get("night_hour", 23))
        variation_minutes = int(sim_cfg.get("variation_minutes", 30))

        while True:
            try:
                if not self.redis:
                    break
                active = await self.redis.get(KEY_VACATION_SIM)
                if not active:
                    break
                active_str = active.decode() if isinstance(active, bytes) else active
                if active_str != "active":
                    break

                now = datetime.now()
                hour = now.hour

                # Morgens: Rolladen hoch, ein Licht an
                if hour == morning_lights:
                    variation = random.randint(-variation_minutes, variation_minutes)
                    await asyncio.sleep(max(0, variation * 60))
                    await self._sim_action("covers_up")
                    await asyncio.sleep(random.randint(60, 300))
                    await self._sim_action("light_random_on")

                # Abends: Lichter an
                elif hour == evening_lights:
                    variation = random.randint(-variation_minutes, variation_minutes)
                    await asyncio.sleep(max(0, variation * 60))
                    await self._sim_action("light_random_on")
                    await asyncio.sleep(random.randint(300, 900))
                    await self._sim_action("covers_down")

                # Nachts: Alles aus
                elif hour == night_off:
                    variation = random.randint(-variation_minutes, variation_minutes)
                    await asyncio.sleep(max(0, variation * 60))
                    await self._sim_action("all_lights_off")

                # Zufaellige Licht-Wechsel tagsüber (alle 1-3 Stunden)
                elif morning_lights < hour < night_off:
                    if random.random() < 0.3:  # 30% Chance pro Stunde
                        await self._sim_action("light_toggle_random")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Vacation-Simulation Fehler: %s", e)

            # Naechster Check in 30-90 Minuten
            await asyncio.sleep(random.randint(1800, 5400))

    async def _sim_action(self, action_type: str):
        """Fuehrt eine Simulations-Aktion aus."""
        try:
            states = await self.ha.get_states()
            if not states:
                return

            if action_type == "covers_up":
                for s in states:
                    eid = s.get("entity_id", "")
                    if eid.startswith("cover."):
                        # Sicherheitsfilter: Garagentore/Tore ueberspringen
                        if self._executor and not await self._executor._is_safe_cover(eid, s):
                            continue
                        await self.ha.call_service("cover", "set_cover_position",
                                                   {"entity_id": eid, "position": 100})
                logger.info("Vacation-Sim: Rolladen hoch")

            elif action_type == "covers_down":
                for s in states:
                    eid = s.get("entity_id", "")
                    if eid.startswith("cover."):
                        # Sicherheitsfilter: Garagentore/Tore ueberspringen
                        if self._executor and not await self._executor._is_safe_cover(eid, s):
                            continue
                        await self.ha.call_service("cover", "set_cover_position",
                                                   {"entity_id": eid, "position": 0})
                logger.info("Vacation-Sim: Rolladen runter")

            elif action_type == "light_random_on":
                lights = [s for s in states if s.get("entity_id", "").startswith("light.")
                          and s.get("state") == "off"]
                if lights:
                    target = random.choice(lights)
                    brightness = random.randint(40, 80)
                    await self.ha.call_service("light", "turn_on",
                                               {"entity_id": target["entity_id"], "brightness_pct": brightness})
                    logger.info("Vacation-Sim: %s an (%d%%)",
                                target["entity_id"], brightness)

            elif action_type == "all_lights_off":
                for s in states:
                    if s.get("entity_id", "").startswith("light.") and s.get("state") == "on":
                        await self.ha.call_service("light", "turn_off",
                                                   {"entity_id": s["entity_id"]})
                logger.info("Vacation-Sim: Alle Lichter aus")

            elif action_type == "light_toggle_random":
                lights = [s for s in states if s.get("entity_id", "").startswith("light.")]
                if lights:
                    target = random.choice(lights)
                    service = "turn_off" if target.get("state") == "on" else "turn_on"
                    data = {"entity_id": target["entity_id"]}
                    if service == "turn_on":
                        data["brightness_pct"] = random.randint(30, 90)
                    await self.ha.call_service("light", service, data)
                    logger.info("Vacation-Sim: %s %s", target["entity_id"], service)

        except Exception as e:
            logger.error("Vacation-Sim Aktion '%s' fehlgeschlagen: %s", action_type, e)

    # ------------------------------------------------------------------
    # Verkehr & Pendler-Info (Travel Time)
    # ------------------------------------------------------------------

    async def get_travel_briefing(self) -> str:
        """Holt Verkehrs-Infos fuer das Morning Briefing.

        Nutzt HA travel_time Sensoren (Google/Waze/HERE Integration).
        """
        states = await self.ha.get_states()
        if not states:
            return ""

        travel_infos = []
        for state in states:
            entity_id = state.get("entity_id", "")
            # travel_time Sensoren erkennen
            if not (entity_id.startswith("sensor.") and
                    any(kw in entity_id.lower() for kw in ["travel_time", "fahrzeit", "commute", "pendel", "route"])):
                continue

            attrs = state.get("attributes", {})
            friendly = attrs.get("friendly_name", entity_id)
            duration = state.get("state", "")
            unit = attrs.get("unit_of_measurement", "min")
            route = attrs.get("route", "")

            try:
                duration_val = float(duration)
            except (ValueError, TypeError):
                continue

            info = f"{friendly}: {int(duration_val)} {unit}"
            if route:
                info += f" (via {route})"

            # Verzoegerung erkennen
            duration_normal = attrs.get("duration_in_traffic", None)
            if duration_normal:
                try:
                    normal_val = float(duration_normal)
                    if duration_val > normal_val * 1.2:  # 20% laenger als normal
                        delay = int(duration_val - normal_val)
                        info += f" — {delay} Min Verzoegerung"
                except (ValueError, TypeError):
                    pass

            travel_infos.append(info)

        if not travel_infos:
            return ""

        return "Verkehr: " + "; ".join(travel_infos)

    # ------------------------------------------------------------------
    # Migration: YAML-Geburtstage -> Semantic Memory
    # ------------------------------------------------------------------

    async def migrate_yaml_birthdays(self, semantic_memory) -> int:
        """Einmalige Migration der YAML-Geburtstage in Semantic Memory.

        Laeuft nur einmal (Redis-Flag mha:migration:yaml_birthdays_done).
        Returns:
            Anzahl migrierter Eintraege.
        """
        if not self.redis or not semantic_memory:
            return 0

        flag_key = "mha:migration:yaml_birthdays_done"
        try:
            already_done = await self.redis.get(flag_key)
            if already_done:
                return 0
        except Exception:
            return 0

        persons_cfg = yaml_config.get("persons", {})
        birthdays = persons_cfg.get("birthdays", {})
        if not birthdays:
            # Kein YAML -> Flag setzen und fertig
            try:
                await self.redis.set(flag_key, "1")
            except Exception:
                pass
            return 0

        migrated = 0
        for name, date_str in birthdays.items():
            try:
                # Format: "YYYY-MM-DD" oder "MM-DD"
                if len(date_str) == 10:
                    year = date_str[:4]
                    mm_dd = date_str[5:]
                else:
                    year = ""
                    mm_dd = date_str[-5:] if len(date_str) >= 5 else date_str

                success = await semantic_memory.store_personal_date(
                    date_type="birthday",
                    person_name=name,
                    date_mm_dd=mm_dd,
                    year=year,
                )
                if success:
                    migrated += 1
            except Exception as e:
                logger.debug("Migration Geburtstag '%s' fehlgeschlagen: %s", name, e)

        try:
            await self.redis.set(flag_key, "1")
        except Exception:
            pass

        if migrated:
            logger.info(
                "YAML-Geburtstage migriert: %d/%d in Semantic Memory",
                migrated, len(birthdays),
            )
        return migrated
