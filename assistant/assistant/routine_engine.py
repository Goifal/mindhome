"""
Routine Engine - Phase 7: Jarvis strukturiert deinen Tag.

Orchestriert wiederkehrende Routinen:
- Morning Briefing: Begruessung + Wetter + Kalender + Haus-Status
- Gute-Nacht: Sicherheits-Check + Morgen-Vorschau + Haus herunterfahren
- Abschied/Willkommen: Kontext-sensitives Verhalten bei Gehen/Kommen

Nutzt bestehende Module:
- context_builder.py für Haus-Status
- proactive.py für Event-Delivery
- function_calling.py für Aktionen
- personality.py für Stil und Begruessungen
"""

import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Europe/Berlin")

import redis.asyncio as redis

from .config import settings, yaml_config, get_person_title, get_all_bed_sensors
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
            "personal_memory", "device_conflicts",
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

    def reload_config(self):
        """Hot-Reload: Aktualisiert gecachte Routines-Config aus yaml_config."""
        routines_cfg = yaml_config.get("routines", {})

        mb_cfg = routines_cfg.get("morning_briefing", {})
        self.briefing_enabled = mb_cfg.get("enabled", True)
        self.briefing_modules = mb_cfg.get("modules", [
            "greeting", "weather", "calendar", "house_status", "travel",
            "personal_memory", "device_conflicts",
        ])
        self.weekday_style = mb_cfg.get("weekday_style", "kurz")
        self.weekend_style = mb_cfg.get("weekend_style", "ausfuehrlich")
        self.morning_actions = mb_cfg.get("morning_actions", {})

        gn_cfg = routines_cfg.get("good_night", {})
        self.goodnight_enabled = gn_cfg.get("enabled", True)
        self.goodnight_triggers = gn_cfg.get("triggers", [
            "gute nacht", "ich gehe schlafen", "schlaf gut",
        ])
        self.goodnight_checks = gn_cfg.get("checks", [
            "windows", "doors", "alarm", "lights",
        ])
        self.goodnight_actions = gn_cfg.get("actions", {})

        gm_cfg = routines_cfg.get("guest_mode", {})
        self.guest_triggers = gm_cfg.get("triggers", [
            "ich habe besuch", "ich hab besuch", "gaeste kommen",
        ])
        self.guest_restrictions = gm_cfg.get("restrictions", {})

        logger.info("RoutineEngine Config hot-reloaded")

    async def initialize(self, redis_client: Optional[redis.Redis] = None):
        """Initialisiert mit Redis."""
        self.redis = redis_client

    def set_executor(self, executor):
        """Setzt den FunctionExecutor für Aktionen."""
        self._executor = executor

    def set_personality(self, personality):
        """Setzt die PersonalityEngine für personality-konsistente Prompts."""
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

        # Check: Heute schon gebrieft? Atomarer SET NX verhindert doppelte Ausfuehrung
        if not force and self.redis:
            today = datetime.now(tz=_TZ).strftime("%Y-%m-%d")
            lock_key = f"{KEY_MORNING_DONE}:lock"
            acquired = await self.redis.set(lock_key, today, ex=86400, nx=True)
            if not acquired:
                # Lock existiert bereits — prüfen ob heutiges Datum
                done = await self.redis.get(KEY_MORNING_DONE)
                if done is not None:
                    done = done.decode() if isinstance(done, bytes) else done
                if done == today:
                    logger.info("Morning Briefing bereits heute ausgeführt")
                    return {"text": "", "actions": []}

        # Bausteine sammeln
        parts = []
        now = datetime.now(tz=_TZ)
        is_weekend = now.weekday() >= 5
        style = self.weekend_style if is_weekend else self.weekday_style

        # Phase 17.4: Sleep-Awareness — nach später Nacht kuerzeres Briefing
        sleep_hint = await self._get_sleep_awareness()
        if sleep_hint:
            # Spaete Nacht → kuerzerer Stil, egal ob Wochentag
            if sleep_hint.get("was_late"):
                style = "kurz"
            parts.append(sleep_hint.get("briefing_note", ""))

        for module in self.briefing_modules:
            content = await self._get_briefing_module(module, person, style)
            if content:
                parts.append(content)

        if not parts:
            return {"text": "", "actions": []}

        # LLM formuliert das Briefing natürlich
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

        # Begleit-Aktionen ausführen
        actions = await self._execute_morning_actions()

        # Als erledigt markieren
        if self.redis:
            try:
                today = datetime.now(tz=_TZ).strftime("%Y-%m-%d")
                await self.redis.setex(KEY_MORNING_DONE, 86400, today)
                await self.redis.setex(KEY_LAST_BRIEFING, 86400, now.isoformat())
            except Exception as e:
                logger.warning("Redis setex für Morning Briefing fehlgeschlagen: %s", e)

        logger.info("Morning Briefing generiert (%d Bausteine, %d Aktionen)", len(parts), len(actions))
        return {"text": text, "actions": actions}

    async def _get_briefing_module(self, module: str, person: str, style: str) -> str:
        """Holt Daten für einen Briefing-Baustein."""
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
            elif module == "personal_memory":
                return await self._get_personal_memory_briefing(person)
            elif module == "device_conflicts":
                return await self._get_device_conflicts_briefing()
        except Exception as e:
            logger.debug("Briefing-Modul '%s' fehlgeschlagen: %s", module, e)
        return ""

    async def _get_device_conflicts_briefing(self) -> str:
        """Prueft DEVICE_DEPENDENCIES gegen aktuelle States fuer das Briefing."""
        try:
            states = await self.ha.get_states()
            if not states:
                return ""
            state_dict = {s["entity_id"]: s.get("state", "") for s in states if "entity_id" in s}
            from .state_change_log import StateChangeLog
            scl = StateChangeLog.__new__(StateChangeLog)
            conflicts = scl.detect_conflicts(state_dict)
            if not conflicts:
                return ""
            lines = [f"Aktuelle Geraete-Konflikte ({len(conflicts)}):"]
            for c in conflicts[:5]:
                room_info = f" ({c['room']})" if c.get("room") else ""
                lines.append(f"- {c['hint']}{room_info}")
            return "\n".join(lines)
        except Exception as e:
            logger.debug("Device-Conflicts Briefing Fehler: %s", e)
            return ""

    async def _get_personal_memory_briefing(self, person: str) -> str:
        """Liefert relevante Erinnerungen und anstehende Daten fuer das Briefing."""
        if not self._semantic_memory or not person:
            return ""

        parts = []
        try:
            # Anstehende persoenliche Daten (naechste 7 Tage)
            upcoming = await self._semantic_memory.get_upcoming_personal_dates(days_ahead=7)
            for entry in upcoming:
                if entry["days_until"] > 0:  # Heute wird schon in greeting abgedeckt
                    name = entry["person"].capitalize()
                    label = entry.get("label", "")
                    days = entry["days_until"]
                    day_text = f"in {days} Tagen" if days > 1 else "morgen"
                    parts.append(f"{name}: {label} {day_text}")

            # Gespeicherte Absichten/Plaene (intent-Fakten)
            intent_facts = await self._semantic_memory.get_facts_by_category("intent")
            for f in intent_facts:
                content = f.get("content", "")
                if content and f.get("confidence", 0) >= 0.5:
                    parts.append(f"Geplant: {content}")

            # Offene Gespraeche aus der letzten Session
            if self.redis:
                from .memory import MemoryManager
                pending_key = "mha:conversations:pending"
                pending_raw = await self.redis.lrange(pending_key, 0, 2)
                import json as _json
                for raw in (pending_raw or []):
                    try:
                        item = _json.loads(raw if isinstance(raw, str) else raw.decode())
                        topic = item.get("topic", "")
                        if topic:
                            parts.append(f"Offenes Thema: {topic}")
                    except Exception:
                        pass
        except Exception as e:
            logger.debug("Personal Memory Briefing fehlgeschlagen: %s", e)

        if parts:
            return "Persoenliche Erinnerungen:\n" + "\n".join(f"- {p}" for p in parts[:5])
        return ""

    async def _get_greeting_context(self, person: str) -> str:
        """Kontextdaten für die Begruessung, inkl. Geburtstags-Check."""
        now = datetime.now(tz=_TZ)
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
        auf State-Attribute für aeltere HA-Versionen.
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

        # Wetter-Zustand übersetzen
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
            # F2: Regenwahrscheinlichkeit
            precip_prob = today_fc.get("precipitation_probability")
            if precip_prob is not None:
                try:
                    if int(precip_prob) > 50:
                        parts.append(f"Regenwahrscheinlichkeit {precip_prob}%")
                except (ValueError, TypeError):
                    pass
            result += ". " + ", ".join(parts)

        # F1: Sonnenstand-Kontext
        sun_state = None
        for state in states:
            if state.get("entity_id") == "sun.sun":
                sun_state = state
                break
        if sun_state:
            sun_attrs = sun_state.get("attributes", {})
            elevation = sun_attrs.get("elevation", 0)
            if elevation < -6:
                result += ". Es ist noch dunkel draußen"
            elif elevation < 0:
                result += ". Es daemmert gerade"

        # F2: Unwetter-Warnung + Kleidungsempfehlung
        try:
            wind_gust = attrs.get("wind_gust_speed") or attrs.get("wind_gust")
            if wind_gust:
                gust_val = float(wind_gust)
                if gust_val > 60:
                    result += f". ACHTUNG: Sturmböen bis {gust_val:.0f} km/h erwartet"
                elif gust_val > 40:
                    result += f". Starke Windboeen ({gust_val:.0f} km/h) möglich"
        except (ValueError, TypeError):
            pass

        # Kleidungsempfehlung
        try:
            temp_val = float(temp)
            rain_conditions = {"rainy", "pouring", "hail", "lightning-rainy"}
            is_rainy = condition in rain_conditions
            if temp_val < 5 and is_rainy:
                result += ". Warme Kleidung und Regenschirm empfohlen"
            elif temp_val < 5:
                result += ". Warme Kleidung empfohlen"
            elif is_rainy:
                result += ". Regenschirm mitnehmen"
            elif temp_val > 30:
                result += ". Leichte Kleidung, viel Wasser trinken"
        except (ValueError, TypeError):
            pass

        return result

    async def _get_forecast_via_service(self, entity_id: str) -> list:
        """Holt Forecast über weather.get_forecasts Service (HA 2024.3+).

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
            # HA gibt ggf. {"service_response": {entity: {forecast: [...]}}} zurück
            if isinstance(result, dict) and "service_response" in result:
                result = result["service_response"]
            # HA gibt verschiedene Formate zurück je nach Version
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
            logger.debug("weather.get_forecasts nicht verfügbar (aeltere HA?): %s", e)
        return []

    @staticmethod
    def _translate_weather(condition: str) -> str:
        """Übersetzt HA Weather-Zustaende ins Deutsche."""
        translations = {
            "sunny": "sonnig",
            "clear-night": "klare Nacht",
            "partlycloudy": "teilweise bewölkt",
            "cloudy": "bewölkt",
            "rainy": "Regen",
            "pouring": "starker Regen",
            "snowy": "Schnee",
            "snowy-rainy": "Schneeregen",
            "fog": "Nebel",
            "hail": "Hagel",
            "lightning": "Gewitter",
            "lightning-rainy": "Gewitter mit Regen",
            "windy": "windig",
            "windy-variant": "windig und bewölkt",
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
            except Exception as e:
                logger.debug("Energy briefing error: %s", e)

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

        # Offene Fenster/Türen — kategorisiert nach Typ
        from .function_calling import is_window_or_door, get_opening_type
        open_windows_doors = []
        open_gates = []
        for state in states:
            entity_id = state.get("entity_id", "")
            if is_window_or_door(entity_id, state) and state.get("state") == "on":
                name = state.get("attributes", {}).get("friendly_name", entity_id)
                if get_opening_type(entity_id, state) == "gate":
                    open_gates.append(name)
                else:
                    open_windows_doors.append(name)
        if open_windows_doors:
            parts.append(f"Offen: {', '.join(open_windows_doors)}")
        if open_gates:
            parts.append(f"Tore offen: {', '.join(open_gates)}")

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
        """Baut den Prompt für das LLM um das Briefing zu formulieren."""
        title = get_person_title(person) if not person or person.lower() == settings.user_name.lower() else person
        prompt = f"Erstelle ein Morning Briefing für {title}.\n\n"
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
        """System Prompt für das Morning Briefing.

        Nutzt die PersonalityEngine für personality-konsistente Prompts
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
            "VERBOTEN: leider, Entschuldigung, Es tut mir leid, Wie kann ich helfen?, Gerne!, Natürlich!"
        )

    async def _get_sleep_awareness(self) -> dict:
        """Prueft ob der User letzte Nacht spät ins Bett ging.

        Phase 17.4: Liest das Late-Night-Pattern aus Redis
        (geschrieben vom WellnessAdvisor) und passt das Briefing an.

        Returns:
            Dict mit was_late (bool), briefing_note (str) oder leeres Dict.
        """
        if not self.redis:
            return {}

        try:
            # Gestern = die Nacht die gerade vorbei ist
            # Late-Night-Nudge schreibt das Datum des Tages in dem
            # der User nach Mitternacht noch wach war.
            today = datetime.now(tz=_TZ).date().isoformat()
            yesterday = (datetime.now(tz=_TZ).date() - timedelta(days=1)).isoformat()

            # Prüfen ob heute (nach Mitternacht) oder gestern als Late-Night vermerkt
            key = "mha:wellness:latenight_dates"
            was_late_today = await self.redis.sismember(key, today)
            was_late_yesterday = await self.redis.sismember(key, yesterday)

            if not was_late_today and not was_late_yesterday:
                return {}

            # Konsekutive Nächte zaehlen
            consecutive = 0
            check_date = datetime.now(tz=_TZ).date()
            for _ in range(7):
                is_member = await self.redis.sismember(key, check_date.isoformat())
                if is_member:
                    consecutive += 1
                    check_date = check_date - timedelta(days=1)
                else:
                    break

            if consecutive >= 3:
                note = (
                    f"SCHLAF-HINWEIS: User war {consecutive} Nächte in Folge nach Mitternacht wach. "
                    "Briefing kurz halten. Sanft auf Schlafmangel hinweisen. "
                    "'Kurze Nacht, Sir.' reicht — nicht belehren."
                )
            elif was_late_today:
                note = (
                    "SCHLAF-HINWEIS: User war letzte Nacht nach Mitternacht noch wach. "
                    "Briefing kuerzer halten. Beilaeufig erwaehnen: 'Nach der kurzen Nacht...' "
                    "Kein Vortrag über Schlafhygiene."
                )
            else:
                return {}

            logger.info("Sleep-Awareness: Late-Night erkannt (consecutive=%d)", consecutive)
            return {"was_late": True, "briefing_note": note}

        except Exception as e:
            logger.debug("Sleep-Awareness Check fehlgeschlagen: %s", e)
            return {}

    async def _execute_morning_actions(self) -> list[dict]:
        """Fuehrt die Begleit-Aktionen beim Morning Briefing aus."""
        actions = []
        if not self._executor:
            return actions

        if self.morning_actions.get("covers_up", False):
            # Wakeup-Sequenz hat Rollläden schon hochgefahren?
            wakeup_done = False
            if self.redis:
                try:
                    today = datetime.now(tz=_TZ).strftime("%Y-%m-%d")
                    done = await self.redis.get("mha:routine:wakeup_done_today")
                    if isinstance(done, bytes):
                        done = done.decode("utf-8", errors="ignore")
                    wakeup_done = bool(done and done.startswith(today))
                except Exception as e:
                    logger.debug("Unhandled: %s", e)
            if wakeup_done:
                logger.info("Morning covers_up übersprungen: Wakeup-Sequenz hat Rollläden schon gefahren")
            else:
                # Bettsensor prüfen: Wenn noch jemand im Bett liegt,
                # Rollläden NICHT hochfahren (Schlafzimmer-Schutz)
                bed_occupied = await self._is_bed_occupied()
                if bed_occupied:
                    logger.info("Morning covers_up übersprungen: Bettsensor belegt")
                else:
                    result = await self._executor.execute("set_cover", {
                        "room": "all", "position": 100,
                    })
                    actions.append({"function": "set_cover", "result": result})

        if self.morning_actions.get("lights_soft", False):
            lights_room = self.morning_actions.get("lights_soft_room", "wohnzimmer")
            lights_brightness = self.morning_actions.get("lights_soft_brightness", 30)
            result = await self._executor.execute("set_light", {
                "room": lights_room, "state": "on", "brightness": lights_brightness,
            })
            actions.append({"function": "set_light", "result": result})

        return actions

    # ------------------------------------------------------------------
    # Aufwach-Sequenz (kontextreiches Aufwachen)
    # ------------------------------------------------------------------

    async def execute_wakeup_sequence(self, autonomy_level: int = 3) -> bool:
        """Fuehrt die stufenweise Aufwach-Sequenz aus.

        Rollläden stufenweise, sanftes Licht, Kaffee — dann Briefing.
        Nur einmal pro Tag, nur im Zeitfenster, nur bei ausreichendem Autonomie-Level.

        Returns:
            True wenn Sequenz ausgeführt wurde.
        """
        ws_cfg = yaml_config.get("routines", {}).get("morning_briefing", {}).get("wakeup_sequence", {})
        if not ws_cfg.get("enabled", False):
            return False

        min_level = ws_cfg.get("min_autonomy_level", 3)
        if autonomy_level < min_level:
            return False

        # Zeitfenster prüfen
        now = datetime.now(tz=_TZ)
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
                if isinstance(done, bytes):
                    done = done.decode("utf-8", errors="ignore")
                if done and done.startswith(today):
                    return False
            except Exception as e:
                logger.debug("Unhandled: %s", e)
        # Bettsensor prüfen
        bed_occupied = await self._is_bed_occupied()
        if bed_occupied:
            logger.info("Aufwach-Sequenz übersprungen: Bettsensor belegt")
            return False

        logger.info("Aufwach-Sequenz gestartet")
        steps = ws_cfg.get("steps", {})

        # 1. Rollläden stufenweise oeffnen
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
                today = datetime.now(tz=_TZ).strftime("%Y-%m-%d")
                await self.redis.setex("mha:routine:wakeup_done_today", 86400, today)
            except Exception as e:
                logger.debug("Unhandled: %s", e)
        logger.info("Aufwach-Sequenz abgeschlossen")
        return True

    async def _wakeup_covers_gradual(self, cfg: dict):
        """Rollläden stufenweise über X Minuten oeffnen."""
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
            # Dependency-Check (z.B. Kaffeemaschine + Wasserleitung)
            try:
                from .state_change_log import StateChangeLog
                states = await self.ha.get_states() or []
                hints = StateChangeLog.check_action_dependencies(
                    "set_switch", {"entity_id": entity, "state": "on"}, states,
                )
                if hints:
                    logger.info("Wakeup coffee: Dependency-Warnung: %s", hints[0])
            except Exception:
                pass
            await self.ha.call_service(
                "homeassistant", "turn_on", {"entity_id": entity},
            )
            logger.info("Wakeup: Kaffeemaschine eingeschaltet (%s)", entity)
        except Exception as e:
            logger.debug("Wakeup coffee fehlgeschlagen: %s", e)

    async def _is_bed_occupied(self) -> bool:
        """Prueft ob ein Bettsensor belegt ist (für Cover-Schutz)."""
        # Zentral aus room_profiles.yaml, Fallback auf settings.yaml
        bed_sensors = get_all_bed_sensors()
        if not bed_sensors:
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

    async def is_goodnight_intent(self, text: str) -> bool:
        """Prueft ob der Text ein Gute-Nacht-Intent ist.

        1. Wetter-Ausschluss (schnell)
        2. Keyword-Matching gegen konfigurierte + erweiterte Trigger-Liste
        3. LLM-Fallback (fast model, 2s Timeout) fuer natuerliche Formulierungen
        """
        text_lower = text.lower().strip()
        # Wetter-Fragen mit "nacht" ausschliessen
        _weather_excludes = ["wie kalt", "wie warm", "temperatur", "wetter",
                             "grad", "regnet", "schneit"]
        if any(ex in text_lower for ex in _weather_excludes):
            logger.debug("Goodnight-Check: Wetter-Ausschluss fuer '%s'", text_lower)
            return False

        # Gezielte Geraetebefehle sind kein Gute-Nacht-Intent
        _device_excludes = ["rollladen", "rolladen", "licht", "lampe", "heizung",
                            "thermostat", "markise", "jalousie", "steckdose",
                            "schalter", "klimaanlage", "ventilator"]
        if any(dev in text_lower for dev in _device_excludes):
            logger.debug("Goodnight-Check: Geraete-Befehl ausgeschlossen fuer '%s'", text_lower)
            return False

        # Erweiterte Defaults (zusaetzlich zu konfigurierten Triggern)
        _extended_triggers = [
            "nacht", "schlafe", "ab ins bett", "geh ins bett",
            "gehe ins bett", "bin muede", "ich bin müde", "geh schlafen",
            "gehe schlafen", "geh pennen", "bis morgen",
            "feierabend", "leg mich hin", "lege mich hin",
            "bin im bett", "ich schlaf jetzt",
        ]
        all_triggers = list(self.goodnight_triggers) + _extended_triggers

        matched = any(trigger in text_lower for trigger in all_triggers)
        logger.debug(
            "Goodnight-Check: text='%s', enabled=%s, keyword_matched=%s",
            text_lower, self.goodnight_enabled, matched,
        )
        if matched:
            return True

        # LLM-Fallback: Nur fuer kurze Saetze (< 80 Zeichen), um Kosten zu begrenzen
        if len(text_lower) > 80:
            return False

        try:
            llm_result = await asyncio.wait_for(
                self.ollama.chat(
                    messages=[{
                        "role": "system",
                        "content": (
                            "Ist der folgende Satz ein Gute-Nacht-Intent? "
                            "Also moechte die Person schlafen gehen oder sich verabschieden fuer die Nacht? "
                            "Antworte NUR mit 'ja' oder 'nein'."
                        ),
                    }, {
                        "role": "user",
                        "content": text,
                    }],
                    model=settings.model_fast,
                    temperature=0.0, max_tokens=5, think=False,
                ),
                timeout=2.0,
            )
            answer = llm_result.get("message", {}).get("content", "").strip().lower()
            is_goodnight = answer.startswith("ja")
            if is_goodnight:
                logger.info("Goodnight-Check: LLM-Classifier erkannt fuer '%s'", text_lower)
            return is_goodnight
        except Exception as e:
            logger.debug("Goodnight LLM-Classifier fehlgeschlagen: %s", e)
            return False

    async def execute_goodnight(self, person: str = "") -> dict:
        """
        Fuehrt die Gute-Nacht-Routine aus.

        Returns:
            Dict mit:
                text: str - Gute-Nacht-Text mit Vorschau + Status
                actions: list - Ausgefuehrte Aktionen
                issues: list - Offene Probleme (Fenster, Türen)
        """
        if not self.goodnight_enabled:
            return {"text": f"Gute Nacht, {get_person_title(person)}. Alles unter Kontrolle.", "actions": [], "issues": []}

        logger.info("Gute-Nacht-Routine gestartet fuer '%s'", person or "unbekannt")

        # 1. Sicherheits-Check (max 15s)
        try:
            issues = await asyncio.wait_for(self._run_safety_checks(), timeout=15.0)
            logger.info("Gute-Nacht: Sicherheits-Check fertig (%d Issues)", len(issues))
        except asyncio.TimeoutError:
            logger.warning("Gute-Nacht: Sicherheits-Check Timeout (15s)")
            issues = []
        except Exception as e:
            logger.warning("Gute-Nacht: Sicherheits-Check Fehler: %s", e)
            issues = []

        # 2. Morgen-Vorschau (max 10s)
        try:
            tomorrow_info = await asyncio.wait_for(self._get_tomorrow_preview(), timeout=10.0)
            logger.info("Gute-Nacht: Morgen-Vorschau fertig")
        except asyncio.TimeoutError:
            logger.warning("Gute-Nacht: Morgen-Vorschau Timeout (10s)")
            tomorrow_info = ""
        except Exception as e:
            logger.warning("Gute-Nacht: Morgen-Vorschau Fehler: %s", e)
            tomorrow_info = ""

        # 3. Aktionen ausfuehren (max 15s, wenn keine kritischen Issues)
        actions = []
        if not any(i.get("critical", False) for i in issues):
            try:
                actions = await asyncio.wait_for(self._execute_goodnight_actions(), timeout=15.0)
                logger.info("Gute-Nacht: %d Aktionen ausgefuehrt", len(actions))
            except asyncio.TimeoutError:
                logger.warning("Gute-Nacht: Aktionen Timeout (15s)")
            except Exception as e:
                logger.warning("Gute-Nacht: Aktionen Fehler: %s", e)
        else:
            logger.info("Gute-Nacht: Kritische Issues — Aktionen uebersprungen")

        # 4. LLM formuliert den Text (max 15s)
        try:
            text = await asyncio.wait_for(
                self._generate_goodnight_text(person, issues, tomorrow_info, actions),
                timeout=15.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Gute-Nacht: LLM-Text Timeout (15s) — Fallback")
            title = get_person_title(person)
            text = f"Gute Nacht, {title}. Alles erledigt."
            if issues:
                issue_msgs = [i["message"] for i in issues[:3]]
                text = f"Gute Nacht, {title}. Hinweis: {'; '.join(issue_msgs)}."
        except Exception as e:
            logger.warning("Gute-Nacht: LLM-Text Fehler: %s — Fallback", e)
            title = get_person_title(person)
            text = f"Gute Nacht, {title}. Alles unter Kontrolle."

        # Timestamp speichern
        if self.redis:
            try:
                await self.redis.setex(KEY_LAST_GOODNIGHT, 86400, datetime.now(tz=_TZ).isoformat())
            except Exception as e:
                logger.debug("Gute-Nacht: Timestamp nicht gespeichert: %s", e)

        logger.info(
            "Gute-Nacht: %d Aktionen, %d Issues — Routine abgeschlossen",
            len(actions), len(issues),
        )
        return {"text": text, "actions": actions, "issues": issues}

    async def _run_safety_checks(self) -> list[dict]:
        """Prueft Fenster, Türen, Alarm, Lichter vor dem Schlafen."""
        issues = []
        states = await self.ha.get_states()
        if not states:
            return issues

        for check in self.goodnight_checks:
            if check == "windows":
                from .function_calling import is_window_or_door, get_opening_type
                for state in states:
                    eid = state.get("entity_id", "")
                    if is_window_or_door(eid, state) and state.get("state") == "on":
                        name = state.get("attributes", {}).get("friendly_name", eid)
                        opening_type = get_opening_type(eid, state)
                        type_label = "Tor" if opening_type == "gate" else "Fenster/Tür"
                        issues.append({
                            "type": "window_open" if opening_type != "gate" else "gate_open",
                            "entity": eid,
                            "name": name,
                            "message": f"{name} ist noch offen ({type_label})",
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

        # Device-Dependency Konflikte (naechtliche Sicherheitsrelevanz)
        try:
            state_dict = {s["entity_id"]: s.get("state", "") for s in states if "entity_id" in s}
            from .state_change_log import StateChangeLog
            scl = StateChangeLog.__new__(StateChangeLog)
            conflicts = scl.detect_conflicts(state_dict)
            for c in conflicts[:3]:
                room_info = f" ({c['room']})" if c.get("room") else ""
                issues.append({
                    "type": "device_conflict",
                    "name": c.get("hint", "Geraete-Konflikt"),
                    "message": f"{c['hint']}{room_info}",
                    "critical": False,
                })
        except Exception as e:
            logger.debug("Goodnight Device-Conflict Check Fehler: %s", e)

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
                        raw_cond = tomorrow.get("condition", "?")
                        cond = self._translate_weather(raw_cond)
                        precipitation = tomorrow.get("precipitation")
                        text = f"Morgen: {temp_low}-{temp_high}°C, {cond}"
                        try:
                            if precipitation and float(precipitation) > 0:
                                text += f", {precipitation}mm Niederschlag"
                        except (ValueError, TypeError):
                            pass
                        # F3: Regenwahrscheinlichkeit
                        precip_prob = tomorrow.get("precipitation_probability")
                        if precip_prob is not None:
                            try:
                                if int(precip_prob) > 40:
                                    text += f", Regenwahrscheinlichkeit {precip_prob}%"
                            except (ValueError, TypeError):
                                pass
                        # F3: Wind morgen
                        wind_tomorrow = tomorrow.get("wind_speed")
                        if wind_tomorrow:
                            try:
                                w_val = float(wind_tomorrow)
                                if w_val > 40:
                                    text += f", starker Wind ({w_val:.0f} km/h)"
                            except (ValueError, TypeError):
                                pass
                        # F3: Kleidungsempfehlung für morgen
                        try:
                            t_low = float(temp_low) if temp_low != "?" else None
                            rain_conds = {"rainy", "pouring", "hail", "lightning-rainy"}
                            is_rainy = raw_cond in rain_conds
                            if t_low is not None:
                                if t_low < 5 and is_rainy:
                                    text += ". Warme Kleidung und Regenschirm einplanen"
                                elif t_low < 5:
                                    text += ". Warme Kleidung einplanen"
                                elif is_rainy:
                                    text += ". Regenschirm nicht vergessen"
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
                    night_room = gn_actions.get("heating_night_room", "schlafzimmer")
                    night_temp = gn_actions.get("heating_night_temp", 18)
                    result = await self._executor.execute("set_climate", {
                        "room": night_room, "temperature": night_temp,
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
                logger.warning("Gute-Nacht Rollläden-runter fehlgeschlagen: %s", e)
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

        prompt = f"Gute-Nacht für {title}.\n\nDATEN:\n"
        for p in parts:
            prompt += f"- {p}\n"
        prompt += "\nFormuliere eine kurze Gute-Nacht-Zusammenfassung. Max 3 Saetze."
        prompt += "\nBei offenen Fenster/Türen: Erwaehne und frage ob so lassen."
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

    _UMLAUT_MAP = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})

    async def is_guest_trigger(self, text: str) -> bool:
        """Prueft ob der Text den Gaeste-Modus aktiviert.

        1. Keyword-Matching gegen konfigurierte + erweiterte Trigger-Liste
        2. LLM-Fallback (fast model, 2s Timeout) fuer natuerliche Formulierungen
        """
        text_lower = text.lower().strip().translate(self._UMLAUT_MAP)

        # Erweiterte Defaults (zusaetzlich zu konfigurierten Triggern)
        _extended_triggers = [
            "besuch kommt", "besuch da", "freunde kommen",
            "wir bekommen besuch", "wir haben besuch", "wir kriegen besuch",
            "gleich kommen gaeste", "gleich kommt besuch",
            "meine eltern kommen", "familie kommt",
            "jemand kommt vorbei", "kommt jemand vorbei",
            "bekommen gaeste", "erwarte besuch", "erwarte gaeste",
        ]
        all_triggers = list(self.guest_triggers) + _extended_triggers

        if any(trigger in text_lower for trigger in all_triggers):
            return True

        # LLM-Fallback: Nur fuer kurze Saetze (< 80 Zeichen)
        if len(text_lower) > 80:
            return False

        try:
            llm_result = await asyncio.wait_for(
                self.ollama.chat(
                    messages=[{
                        "role": "system",
                        "content": (
                            "Kuendigt der folgende Satz an, dass Gaeste/Besuch kommen oder da sind? "
                            "Antworte NUR mit 'ja' oder 'nein'."
                        ),
                    }, {
                        "role": "user",
                        "content": text,
                    }],
                    model=settings.model_fast,
                    temperature=0.0, max_tokens=5, think=False,
                ),
                timeout=2.0,
            )
            answer = llm_result.get("message", {}).get("content", "").strip().lower()
            is_guest = answer.startswith("ja")
            if is_guest:
                logger.info("Guest-Check: LLM-Classifier erkannt fuer '%s'", text_lower)
            return is_guest
        except Exception as e:
            logger.debug("Guest LLM-Classifier fehlgeschlagen: %s", e)
            return False

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
            return "Kein Executor verfügbar."

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
            return "Kein Executor verfügbar."

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
        return "Gaeste-Modus beendet. Zurück zum Normalbetrieb."

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
        """Gibt den Prompt-Zusatz für den Gaeste-Modus zurück."""
        restrictions = self.guest_restrictions
        parts = ["GAESTE-MODUS AKTIV:"]
        if restrictions.get("hide_personal_info"):
            parts.append("- Keine persoenlichen Infos preisgeben (Kalender, Gewohnheiten, etc.)")
        if restrictions.get("formal_tone"):
            parts.append("- Formeller Ton. Kein Insider-Humor.")
        if restrictions.get("restrict_security"):
            parts.append("- Kein Zugriff auf Alarm, Türschloesser, Sicherheitskameras.")
        parts.append("- Bei persoenlichen Fragen: Hoeflich ablehnen.")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Abwesenheits-Log (Feature 7.8)
    # ------------------------------------------------------------------

    async def log_absence_event(self, event_type: str, description: str):
        """Loggt ein Event während der Abwesenheit."""
        if not self.redis:
            return
        now = datetime.now(tz=_TZ).isoformat()
        entry = f"{now}|{event_type}|{description}"
        await self.redis.rpush(KEY_ABSENCE_LOG, entry)
        await self.redis.expire(KEY_ABSENCE_LOG, 30 * 86400)

    async def get_absence_summary(self) -> str:
        """Gibt eine Zusammenfassung der Events während der Abwesenheit zurück."""
        if not self.redis:
            return ""

        entries = await self.redis.lrange(KEY_ABSENCE_LOG, 0, -1)
        if not entries:
            return ""

        # Events parsen und filtern
        events = []
        for entry in entries:
            if isinstance(entry, bytes):
                entry = entry.decode("utf-8", errors="ignore")
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
                     "Fasse Events während der Abwesenheit zusammen. "
                     "Kurz, nur Relevantes. Max 2 Saetze. Deutsch. Butler-Stil."},
                    {"role": "user", "content": f"Events während der Abwesenheit:\n{event_text}"},
                ],
                model=settings.model_fast,
            )
            summary = response.get("message", {}).get("content", "")
        except Exception as e:
            logger.error("Abwesenheits-Summary Fehler: %s", e)
            summary = f"{len(events)} Events während der Abwesenheit."

        # Log löschen nach Zusammenfassung
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
            return "Redis nicht verfügbar für Abwesenheits-Simulation."

        await self.redis.setex(KEY_VACATION_SIM, 30 * 86400, "active")
        self._vacation_task = asyncio.create_task(self._run_vacation_simulation())
        logger.info("Abwesenheits-Simulation gestartet")
        return f"Das Haus wird bewohnt wirken, {get_person_title()}. Alles Weitere übernehme ich."

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
        return f"Abwesenheits-Simulation beendet. Willkommen zurück, {get_person_title()}."

    async def _run_vacation_simulation(self):
        """Hauptloop der Abwesenheits-Simulation (nur Licht).

        Bug 7: Cover-Aktionen (covers_up/covers_down) werden NICHT mehr hier gesteuert
        — das macht proactive._cover_schedule_logic() über vacation_simulation.* Config.
        Bug 9: Config wird bei jedem Zyklus frisch gelesen (Hot-Reload).
        """
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

                # Bug 9: Config bei jedem Zyklus frisch lesen (Hot-Reload)
                sim_cfg = yaml_config.get("vacation_simulation", {})
                morning_lights = int(sim_cfg.get("morning_hour", 7))
                evening_lights = int(sim_cfg.get("evening_hour", 18))
                night_off = int(sim_cfg.get("night_hour", 23))
                variation_minutes = int(sim_cfg.get("variation_minutes", 30))

                now = datetime.now(tz=_TZ)
                hour = now.hour

                # Morgens: NUR Licht an (Cover macht proactive.py)
                if hour == morning_lights:
                    variation = random.randint(-variation_minutes, variation_minutes)
                    await asyncio.sleep(max(0, variation * 60))
                    await self._sim_action("light_random_on")

                # Abends: NUR Lichter an (Cover macht proactive.py)
                elif hour == evening_lights:
                    variation = random.randint(-variation_minutes, variation_minutes)
                    await asyncio.sleep(max(0, variation * 60))
                    await self._sim_action("light_random_on")

                # Nachts: Alle Lichter aus
                elif hour == night_off:
                    variation = random.randint(-variation_minutes, variation_minutes)
                    await asyncio.sleep(max(0, variation * 60))
                    await self._sim_action("all_lights_off")

                # Zufaellige Licht-Wechsel tagsueber
                elif morning_lights < hour < night_off:
                    if random.random() < 0.3:
                        await self._sim_action("light_toggle_random")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Vacation-Simulation Fehler: %s", e)

            await asyncio.sleep(random.randint(1800, 5400))

    async def _sim_action(self, action_type: str):
        """Fuehrt eine Simulations-Aktion aus (nur Licht, keine Covers)."""
        # Bug 7: Cover-Aktionen entfernt — proactive.py steuert Covers
        if action_type in ("covers_up", "covers_down"):
            logger.debug("Vacation-Sim: Cover-Aktion '%s' übersprungen (proactive.py)", action_type)
            return

        try:
            states = await self.ha.get_states()
            if not states:
                return

            if action_type == "light_random_on":
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
        """Holt Verkehrs-Infos für das Morning Briefing.

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
                        info += f" — {delay} Min Verzögerung"
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
            except Exception as e:
                logger.debug("Unhandled: %s", e)
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
        except Exception as e:
            logger.debug("Unhandled: %s", e)
        if migrated:
            logger.info(
                "YAML-Geburtstage migriert: %d/%d in Semantic Memory",
                migrated, len(birthdays),
            )
        return migrated

    # ------------------------------------------------------------------
    # Multi-Day Planning: Vorausplanung fuer die naechsten N Tage
    # ------------------------------------------------------------------

    async def plan_ahead(
        self,
        days: int,
        calendar_events: list,
        ha_client,
    ) -> list[dict]:
        """Plant Vorbereitungen fuer die naechsten N Tage basierend auf Kalender-Events.

        Analysiert Kalender-Eintraege und generiert Vorbereitungsaufgaben:
        - Gaeste kommen → Gaestezimmer vorbereiten (Temperatur, Reinigung)
        - Frueher Termin → frueheren Wecker vorschlagen
        - Urlaub/Ferien → Urlaubs-Checkliste ausloesen
        - Geburtstag → Feier-Vorbereitung vorschlagen

        Kann taeglich vom Proactive System aufgerufen werden.

        Args:
            days: Anzahl Tage in die Zukunft (z.B. 7)
            calendar_events: Liste von Kalender-Events, jeweils dict mit
                             "summary", "start" (ISO-Str oder datetime),
                             "end" (optional), "description" (optional)
            ha_client: HomeAssistant-Client fuer Aktionen

        Returns:
            Liste von Vorbereitungs-Plaenen pro Tag/Event
        """
        if not calendar_events:
            return []

        now = datetime.now(tz=_TZ)
        plans: list[dict] = []

        for event in calendar_events:
            summary = event.get("summary", "")
            description = event.get("description", "")
            combined_text = f"{summary} {description}".lower()

            # Start-Zeitpunkt parsen
            start_raw = event.get("start", "")
            if isinstance(start_raw, datetime):
                event_start = start_raw if start_raw.tzinfo else start_raw.replace(tzinfo=_TZ)
            elif isinstance(start_raw, str) and start_raw:
                try:
                    event_start = datetime.fromisoformat(start_raw)
                    if event_start.tzinfo is None:
                        event_start = event_start.replace(tzinfo=_TZ)
                except (ValueError, TypeError):
                    logger.debug("plan_ahead: Ungueliges Datum '%s', uebersprungen", start_raw)
                    continue
            else:
                continue

            # Nur Events innerhalb des Planungshorizonts
            delta_days = (event_start.date() - now.date()).days
            if delta_days < 0 or delta_days > days:
                continue

            event_date = event_start.strftime("%Y-%m-%d")
            preparations: list[dict] = []

            # --- Gaeste / Besuch erkennen ---
            guest_keywords = [
                "gast", "gaeste", "besuch", "besucher", "einladung",
                "dinner", "abendessen", "feier", "party", "guest",
            ]
            if any(kw in combined_text for kw in guest_keywords):
                # Gaestezimmer vorheizen (4h vorher)
                preparations.append({
                    "action": "set_climate",
                    "entity": "climate.gaestezimmer",
                    "target": 21,
                    "when": "4h before",
                    "description": "Gaestezimmer auf 21°C vorheizen",
                })
                # Reinigung einplanen (am Morgen des Tages)
                preparations.append({
                    "action": "notify",
                    "message": "Gaeste kommen heute — Gaestezimmer vorbereiten",
                    "when": "morning_of_day",
                    "description": "Erinnerung: Gaestezimmer vorbereiten",
                })
                # Wohnzimmer auch angenehm temperieren
                preparations.append({
                    "action": "set_climate",
                    "entity": "climate.wohnzimmer",
                    "target": 22,
                    "when": "2h before",
                    "description": "Wohnzimmer auf 22°C fuer Gaeste",
                })

            # --- Frueher Termin (vor 8:00) → frueherer Wecker ---
            early_keywords = ["meeting", "termin", "besprechung", "arzt", "flug", "zug"]
            if event_start.hour < 8 and event_start.hour > 0:
                is_early_event = any(kw in combined_text for kw in early_keywords) or True
                if is_early_event:
                    # Wecker 90 Minuten vor dem Termin vorschlagen
                    wake_time = event_start - timedelta(minutes=90)
                    preparations.append({
                        "action": "suggest_alarm",
                        "time": wake_time.strftime("%H:%M"),
                        "when": "evening_before",
                        "description": (
                            f"Frueher Termin um {event_start.strftime('%H:%M')} — "
                            f"Wecker auf {wake_time.strftime('%H:%M')} empfohlen"
                        ),
                    })
                    # Morgenroutine frueher starten
                    preparations.append({
                        "action": "set_wakeup_time",
                        "time": wake_time.strftime("%H:%M"),
                        "when": "evening_before",
                        "description": "Aufwach-Sequenz frueher starten",
                    })

            # --- Urlaub / Ferien erkennen ---
            vacation_keywords = [
                "urlaub", "ferien", "vacation", "holiday", "verreisen",
                "abwesenheit", "away", "reise",
            ]
            if any(kw in combined_text for kw in vacation_keywords):
                # Urlaubs-Checkliste: Heizung absenken
                preparations.append({
                    "action": "set_climate_all",
                    "target": 16,
                    "when": "on_departure",
                    "description": "Alle Raeume auf 16°C Absenktemperatur",
                })
                # Anwesenheitssimulation starten
                preparations.append({
                    "action": "start_vacation_simulation",
                    "when": "on_departure",
                    "description": "Anwesenheitssimulation aktivieren",
                })
                # Fenster-Check
                preparations.append({
                    "action": "check_windows",
                    "when": "1h before departure",
                    "description": "Alle Fenster geschlossen? Sicherheitscheck",
                })
                # Erinnerung: Muell, Post, etc.
                preparations.append({
                    "action": "notify",
                    "message": "Urlaubs-Checkliste: Muell, Post umleiten, Kuehlschrank",
                    "when": "1d before",
                    "description": "Urlaubs-Vorbereitungs-Erinnerung",
                })

            # --- Geburtstag erkennen ---
            birthday_keywords = [
                "geburtstag", "birthday", "geb.", "bday",
            ]
            if any(kw in combined_text for kw in birthday_keywords):
                preparations.append({
                    "action": "notify",
                    "message": f"Geburtstag: {summary} — Geschenk und Feier vorbereiten",
                    "when": "2d before",
                    "description": "Erinnerung: Geburtstagsgeschenk besorgen",
                })
                preparations.append({
                    "action": "notify",
                    "message": f"Heute ist Geburtstag: {summary}",
                    "when": "morning_of_day",
                    "description": "Geburtstags-Erinnerung am Morgen",
                })
                # Festliche Beleuchtung vorschlagen
                preparations.append({
                    "action": "set_scene",
                    "scene": "celebration",
                    "when": "morning_of_day",
                    "description": "Festliche Beleuchtung aktivieren",
                })

            # Nur Events mit Vorbereitungen aufnehmen
            if preparations:
                plans.append({
                    "day": event_date,
                    "event": summary,
                    "preparations": preparations,
                })

        logger.info(
            "plan_ahead: %d Vorbereitungen fuer %d Tage generiert",
            len(plans), days,
        )
        return plans

    # ------------------------------------------------------------------
    # Phase 5C: Erweiterte Routinen
    # ------------------------------------------------------------------

    async def weather_precaution_routine(self) -> Optional[str]:
        """Wetter-Vorsorge: 2h vor Regen → Fenster-/Markisen-Warnung.

        Returns:
            Warntext oder None
        """
        try:
            if not self.redis:
                return None

            forecast_raw = await self.redis.get("mha:weather:forecast")
            if not forecast_raw:
                return None

            import json
            forecast = json.loads(forecast_raw)

            # Naechste 2-3 Stunden pruefen
            rain_conditions = {"rainy", "pouring", "hail", "lightning-rainy", "snowy"}
            upcoming_rain = None

            if isinstance(forecast, list):
                for f in forecast[:3]:  # Naechste 3 Stunden
                    condition = f.get("condition", "")
                    if condition in rain_conditions:
                        upcoming_rain = f
                        break

            if not upcoming_rain:
                return None

            # Cooldown (1x pro Tag)
            cooldown_key = "mha:routine:weather_precaution_done"
            if await self.redis.get(cooldown_key):
                return None
            await self.redis.setex(cooldown_key, 86400, "1")

            condition = upcoming_rain.get("condition", "Regen")
            hour = upcoming_rain.get("hour", "")
            return (
                f"Wetter-Vorsorge: {condition.title()} erwartet"
                f"{f' gegen {hour} Uhr' if hour else ' in den naechsten Stunden'}. "
                f"Sollen Fenster und Markisen geschlossen werden?"
            )
        except Exception as e:
            logger.debug("Weather precaution routine failed: %s", e)
            return None

    async def calendar_health_check(self) -> Optional[str]:
        """Kalender-Gesundheitscheck: 6h+ Meeting-Block → Pausen-Vorschlag.

        Returns:
            Vorschlag-Text oder None
        """
        try:
            if not self.ha:
                return None

            states = await self.ha.get_states()
            if not states:
                return None

            # Kalender-Events suchen
            calendar_events = []
            for s in states:
                eid = s.get("entity_id", "")
                if eid.startswith("calendar.") and s.get("state") == "on":
                    attrs = s.get("attributes", {})
                    start = attrs.get("start_time", "")
                    end = attrs.get("end_time", "")
                    if start and end:
                        calendar_events.append({"start": start, "end": end})

            if len(calendar_events) >= 3:
                return (
                    f"Heute stehen {len(calendar_events)} Kalender-Events an. "
                    f"Soll ich eine Mittagspause blocken?"
                )
        except Exception as e:
            logger.debug("Calendar health check failed: %s", e)
        return None

    async def energy_routine(self) -> Optional[str]:
        """Energie-Routine: Solar-Ende in 30 Min → Waschmaschine starten?

        Returns:
            Vorschlag-Text oder None
        """
        try:
            if not self.ha:
                return None

            states = await self.ha.get_states()
            if not states:
                return None

            solar_power = 0
            for s in states:
                eid = s.get("entity_id", "")
                if "solar" in eid or "pv" in eid:
                    try:
                        solar_power = float(s.get("state", 0))
                    except (ValueError, TypeError):
                        pass
                    break

            # Solar produziert, aber Sonne geht bald unter
            from datetime import datetime
            hour = datetime.now().hour
            if solar_power > 200 and hour >= 16:
                return (
                    f"Solar produziert noch {solar_power:.0f}W, aber die Sonne geht "
                    f"bald unter. Energieintensive Geraete jetzt starten?"
                )
        except Exception as e:
            logger.debug("Energy routine failed: %s", e)
        return None

    async def incomplete_routine_recovery(self) -> Optional[str]:
        """Prueeft ob gestrige Routinen unterbrochen wurden.

        Returns:
            Hinweis-Text oder None
        """
        try:
            if not self.redis:
                return None

            import json
            key = "mha:routine:last_goodnight"
            raw = await self.redis.get(key)
            if not raw:
                return None

            data = json.loads(raw)
            if data.get("completed") is False:
                incomplete = data.get("incomplete_steps", [])
                if incomplete:
                    steps = ", ".join(incomplete[:3])
                    return (
                        f"Die Gute-Nacht-Routine wurde gestern nicht abgeschlossen. "
                        f"Offene Schritte: {steps}. Soll ich das nachholen?"
                    )
        except Exception as e:
            logger.debug("Incomplete routine recovery failed: %s", e)
        return None

    async def habit_intervention(self) -> Optional[str]:
        """Gewohnheits-Intervention: TV nach 23:30 → Wind-Down-Erinnerung.

        Returns:
            Hinweis-Text oder None
        """
        try:
            from datetime import datetime
            now = datetime.now()
            if now.hour < 23 or (now.hour == 23 and now.minute < 30):
                return None

            if not self.ha:
                return None

            states = await self.ha.get_states()
            if not states:
                return None

            tv_on = False
            for s in states:
                eid = s.get("entity_id", "")
                if eid.startswith("media_player.") and s.get("state") == "playing":
                    tv_on = True
                    break

            if tv_on:
                if self.redis:
                    cooldown_key = "mha:routine:habit_intervention_done"
                    if await self.redis.get(cooldown_key):
                        return None
                    await self.redis.setex(cooldown_key, 86400, "1")

                return (
                    "Es ist nach 23:30 und der Fernseher laeuft noch. "
                    "Soll ich eine Wind-Down-Erinnerung fuer morgen um 22:30 setzen?"
                )
        except Exception as e:
            logger.debug("Habit intervention failed: %s", e)
        return None
