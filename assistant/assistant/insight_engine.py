"""
InsightEngine — Jarvis denkt voraus.

Phase 17.3: Hintergrund-Analyse die Datenquellen kreuz-referenziert
und proaktiv Hinweise gibt.

Architektur:
  1. Daten sammeln (HA States, Kalender, Energie-Baselines)
  2. Regel-basierte Checks (schnell, kein LLM)
  3. Hinweis-Text direkt generiert (Template-basiert)
  4. Delivery via Callback → brain._handle_insight → Silence Matrix → TTS

Checks:
  - Regen/Sturm in Forecast + Fenster offen
  - Frost morgen + Heizung auf Abwesend/aus
  - Kalender-Event morgen frueh (Reise-Keywords → Alarm-Hinweis)
  - Energie-Verbrauch überBaseline
  - Abwesenheit + Geraete/Licht an
  - Temperatur-Trend: Raum kuehlt ungewoehnlich ab
  - Fenster offen + Temperatur faellt
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config, settings, get_person_title
from .ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)
from zoneinfo import ZoneInfo
_LOCAL_TZ = ZoneInfo(yaml_config.get("timezone", "Europe/Berlin"))

# Redis-Key-Prefix
_PREFIX = "mha:insight"

# Reise-Keywords im Kalender
_TRAVEL_KEYWORDS = [
    "flug", "flight", "hotel", "reise", "urlaub", "vacation",
    "zug", "train", "bahn", "abflug", "departure", "airport",
    "flughafen", "check-in", "checkin", "boarding",
]

# Wetter-Conditions die Regen/Sturm bedeuten
_RAIN_CONDITIONS = [
    "rainy", "pouring", "lightning-rainy", "lightning",
    "hail", "exceptional",
]

_STORM_CONDITIONS = [
    "pouring", "lightning-rainy", "lightning", "windy",
    "exceptional", "hail",
]


class InsightEngine:
    """Kreuz-referenziert Datenquellen und gibt proaktive Hinweise."""

    def __init__(self, ha: HomeAssistantClient, activity=None):
        self.ha = ha
        self.activity = activity
        self.redis: Optional[aioredis.Redis] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._notify_callback = None
        self._ollama = None

        # Konfiguration aus YAML
        cfg = yaml_config.get("insights", {})
        self.enabled = cfg.get("enabled", True)
        self.check_interval = cfg.get("check_interval_minutes", 30) * 60
        self.cooldown_hours = cfg.get("cooldown_hours", 4)

        # Einzelne Checks ein/ausschaltbar
        checks_cfg = cfg.get("checks", {})
        self.check_weather_windows = checks_cfg.get("weather_windows", True)
        self.check_frost_heating = checks_cfg.get("frost_heating", True)
        self.check_calendar_travel = checks_cfg.get("calendar_travel", True)
        self.check_energy_anomaly = checks_cfg.get("energy_anomaly", True)
        self.check_away_devices = checks_cfg.get("away_devices", True)
        self.check_temp_drop = checks_cfg.get("temp_drop", True)
        self.check_window_temp = checks_cfg.get("window_temp_drop", True)
        self.check_calendar_weather_cross = checks_cfg.get("calendar_weather_cross", True)
        self.check_comfort_contradiction = checks_cfg.get("comfort_contradiction", True)

        # Phase 18: Neue 3D+ Cross-Reference Checks
        insight_checks_cfg = yaml_config.get("insight_checks", {})
        self.check_guest_preparation = insight_checks_cfg.get("guest_preparation", True)
        self.check_away_security_full = insight_checks_cfg.get("away_security_full", True)
        self.check_health_work_pattern = insight_checks_cfg.get("health_work_pattern", True)
        self.check_humidity_contradiction = insight_checks_cfg.get("humidity_contradiction", True)
        self.check_night_security = insight_checks_cfg.get("night_security", True)
        self.check_heating_vs_sun = insight_checks_cfg.get("heating_vs_sun", True)
        self.check_forgotten_devices = insight_checks_cfg.get("forgotten_devices", True)

        # Schwellwerte
        thresholds = cfg.get("thresholds", {})
        self.frost_temp = thresholds.get("frost_temp_c", 2)
        self.energy_anomaly_pct = thresholds.get("energy_anomaly_percent", 30)
        self.away_minutes = thresholds.get("away_device_minutes", 120)
        self.temp_drop_degrees = thresholds.get("temp_drop_degrees_per_2h", 3)

        # H4+H5: Konfigurierbare Limits
        self.startup_delay = cfg.get("startup_delay_seconds", 120)
        self.max_calendars = cfg.get("max_calendars", 3)
        self.max_temp_snapshots = cfg.get("max_temp_snapshots", 6)

        # Wetter-Aktions-Cooldown: verhindert wiederholte Vorschlaege innerhalb 60 Min
        self._weather_action_cooldown: dict[str, datetime] = {}

        # LLM-basierte Kausalanalyse
        _llm_causal_cfg = yaml_config.get("insight_llm_causal", {})
        self._llm_causal_enabled = _llm_causal_cfg.get("enabled", True)
        self._llm_causal_cooldown = _llm_causal_cfg.get("cooldown_seconds", 1800)

    async def initialize(
        self,
        redis_client: Optional[aioredis.Redis] = None,
        ollama=None,
    ):
        """Initialisiert die Engine und startet den Hintergrund-Loop."""
        self.redis = redis_client
        self._ollama = ollama

        if self.enabled:
            self._running = True
            self._task = asyncio.create_task(self._insight_loop())
            self._task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
            logger.info(
                "InsightEngine initialisiert (Intervall: %d Min, Cooldown: %d Std)",
                self.check_interval // 60,
                self.cooldown_hours,
            )

    def set_notify_callback(self, callback):
        """Setzt den Callback fuer Insight-Meldungen."""
        self._notify_callback = callback

    async def _get_title_for_home(self) -> str:
        """Ermittelt die Anrede basierend auf anwesenden Personen."""
        try:
            states = await self.ha.get_states()
            if states:
                persons = []
                for s in states:
                    if s.get("entity_id", "").startswith("person.") and s.get("state") == "home":
                        name = s.get("attributes", {}).get("friendly_name", "")
                        if name:
                            persons.append(name)
                if len(persons) == 1:
                    return get_person_title(persons[0])
                elif len(persons) > 1:
                    seen = set()
                    titles = []
                    for p in persons:
                        t = get_person_title(p)
                        if t not in seen:
                            seen.add(t)
                            titles.append(t)
                    return ", ".join(titles)
        except Exception as e:
            logger.debug("Person titles retrieval failed: %s", e)
        return get_person_title()

    async def stop(self):
        """Stoppt die Engine."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def reload_config(self):
        """Laedt Konfiguration aus yaml_config neu."""
        cfg = yaml_config.get("insights", {})
        was_enabled = self.enabled
        self.enabled = cfg.get("enabled", True)
        self.check_interval = cfg.get("check_interval_minutes", 30) * 60
        self.cooldown_hours = cfg.get("cooldown_hours", 4)

        checks_cfg = cfg.get("checks", {})
        self.check_weather_windows = checks_cfg.get("weather_windows", True)
        self.check_frost_heating = checks_cfg.get("frost_heating", True)
        self.check_calendar_travel = checks_cfg.get("calendar_travel", True)
        self.check_energy_anomaly = checks_cfg.get("energy_anomaly", True)
        self.check_away_devices = checks_cfg.get("away_devices", True)
        self.check_temp_drop = checks_cfg.get("temp_drop", True)
        self.check_window_temp = checks_cfg.get("window_temp_drop", True)
        self.check_calendar_weather_cross = checks_cfg.get("calendar_weather_cross", True)
        self.check_comfort_contradiction = checks_cfg.get("comfort_contradiction", True)

        # Phase 18: 3D+ Cross-Reference Checks
        insight_checks_cfg = yaml_config.get("insight_checks", {})
        self.check_guest_preparation = insight_checks_cfg.get("guest_preparation", True)
        self.check_away_security_full = insight_checks_cfg.get("away_security_full", True)
        self.check_health_work_pattern = insight_checks_cfg.get("health_work_pattern", True)
        self.check_humidity_contradiction = insight_checks_cfg.get("humidity_contradiction", True)
        self.check_night_security = insight_checks_cfg.get("night_security", True)
        self.check_heating_vs_sun = insight_checks_cfg.get("heating_vs_sun", True)
        self.check_forgotten_devices = insight_checks_cfg.get("forgotten_devices", True)

        thresholds = cfg.get("thresholds", {})
        self.frost_temp = thresholds.get("frost_temp_c", 2)
        self.energy_anomaly_pct = thresholds.get("energy_anomaly_percent", 30)
        self.away_minutes = thresholds.get("away_device_minutes", 120)
        self.temp_drop_degrees = thresholds.get("temp_drop_degrees_per_2h", 3)

        # H4+H5: Konfigurierbare Limits
        self.startup_delay = cfg.get("startup_delay_seconds", 120)
        self.max_calendars = cfg.get("max_calendars", 3)
        self.max_temp_snapshots = cfg.get("max_temp_snapshots", 6)

        # Loop starten wenn gerade aktiviert wurde
        if self.enabled and not was_enabled and not self._running:
            self._running = True
            self._task = asyncio.create_task(self._insight_loop())
            self._task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
            logger.info("InsightEngine via Hot-Reload gestartet")

    # ------------------------------------------------------------------
    # Hintergrund-Loop
    # ------------------------------------------------------------------

    async def _insight_loop(self):
        """Prueft periodisch auf Insights."""
        # H4: Konfigurierbarer Startup-Delay (System stabilisieren lassen)
        await asyncio.sleep(self.startup_delay)

        while self._running:
            try:
                if self.enabled:
                    insights = await self._run_all_checks()
                    for insight in insights:
                        # LLM-Rewrite: Insight-Text natuerlicher formulieren
                        insight = await self._rewrite_insight(insight)
                        if self._notify_callback:
                            await self._notify_callback(insight)
                        logger.info(
                            "Insight [%s]: %s",
                            insight.get("check"),
                            insight.get("message", "")[:80],
                        )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("InsightEngine Loop Fehler: %s", e)

            await asyncio.sleep(self.check_interval)

    async def _rewrite_insight(self, insight: dict) -> dict:
        """Formuliert Insight-Text via LLM natuerlicher — im Jarvis-Butler-Stil.

        Nutzt das Fast-Modell fuer minimale Latenz. Bei Fehler oder wenn kein
        OllamaClient vorhanden, wird der Original-Text unveraendert zurueckgegeben.
        """
        cfg = yaml_config.get("insights", {})
        if not cfg.get("llm_rewrite", True) or not self._ollama:
            return insight

        original = insight.get("message", "")
        if not original or len(original) < 15:
            return insight

        title = await self._get_title_for_home()
        urgency = insight.get("urgency", "low")

        try:
            response = await asyncio.wait_for(
                self._ollama.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Du bist J.A.R.V.I.S., ein trocken-britischer Smart-Home-Butler. "
                                "Formuliere den folgenden Hinweis in 1-2 Saetzen natuerlich um. "
                                "Behalte ALLE Fakten exakt bei (Zahlen, Geraete, Raeume). "
                                f"Anrede: {title}. "
                                f"Dringlichkeit: {urgency}. "
                                "Keine Aufzaehlungen, keine Emojis, knapp und souveraen."
                            ),
                        },
                        {"role": "user", "content": original},
                    ],
                    model=settings.model_fast,
                    temperature=0.4,
                    max_tokens=500,
                    think=False,
                    tier="fast",
                ),
                timeout=4.0,
            )
            content = (response.get("message", {}).get("content", "") or "").strip()
            # Think-Tags entfernen
            if "<think>" in content:
                think_end = content.find("</think>")
                if think_end != -1:
                    content = content[think_end + 8:].strip()

            if content and 10 < len(content) < len(original) * 3:
                insight["message"] = content
                insight["_original_message"] = original
        except asyncio.TimeoutError:
            logger.debug("Insight-Rewrite Timeout — behalte Original")
        except Exception as e:
            logger.debug("Insight-Rewrite Fehler: %s", e)

        return insight

    # ------------------------------------------------------------------
    # Daten sammeln
    # ------------------------------------------------------------------

    async def _gather_data(self) -> dict:
        """Sammelt alle benoetigten Daten parallel."""
        data = {
            "states": [],
            "calendar_events": [],
            "weather": None,
            "forecast": [],
            "open_windows": [],
            "open_doors": [],
            "lights_on": [],
            "climate": [],
            "persons_home": [],
            "persons_away": [],
            "alarm_state": None,
            "temperatures": {},
        }

        try:
            # HA States (ein Call fuer alles)
            states = await self.ha.get_states()
            if not states:
                return data

            data["states"] = states

            # States durchparsen
            for s in states:
                eid = s.get("entity_id", "")
                state = s.get("state", "")
                attrs = s.get("attributes", {})

                # Wetter
                if eid.startswith("weather.") and not data["weather"]:
                    data["weather"] = {
                        "condition": state,
                        "temp": attrs.get("temperature"),
                        "humidity": attrs.get("humidity"),
                    }
                    forecast = attrs.get("forecast", [])
                    if forecast:
                        data["forecast"] = forecast[:5]

                # Offene Fenster
                elif (eid.startswith("binary_sensor.") and
                      state == "on" and
                      any(kw in eid for kw in ("window", "fenster"))):
                    name = attrs.get("friendly_name", eid)
                    data["open_windows"].append(name)

                # Offene Türen
                elif (eid.startswith("binary_sensor.") and
                      state == "on" and
                      any(kw in eid for kw in ("door", "tuer", "eingang"))):
                    # Ausschluss: Garagentore, Briefkasten etc.
                    if not any(x in eid for x in ("garage", "briefkasten", "mailbox")):
                        name = attrs.get("friendly_name", eid)
                        data["open_doors"].append(name)

                # Lichter an
                elif eid.startswith("light.") and state == "on":
                    name = attrs.get("friendly_name", eid)
                    data["lights_on"].append(name)

                # Climate / Heizung
                elif eid.startswith("climate.") and state != "unavailable":
                    data["climate"].append({
                        "entity_id": eid,
                        "name": attrs.get("friendly_name", eid),
                        "state": state,
                        "current_temp": attrs.get("current_temperature"),
                        "target_temp": attrs.get("temperature"),
                        "preset_mode": attrs.get("preset_mode", ""),
                        "hvac_action": attrs.get("hvac_action", ""),
                    })

                # Personen
                elif eid.startswith("person."):
                    name = attrs.get("friendly_name", eid)
                    if state == "home":
                        data["persons_home"].append(name)
                    else:
                        data["persons_away"].append(name)

                # Alarm
                elif eid.startswith("alarm_control_panel."):
                    data["alarm_state"] = state

                # Temperatur-Sensoren
                elif (eid.startswith("sensor.") and
                      "temperature" in eid and
                      state not in ("unavailable", "unknown", "")):
                    try:
                        data["temperatures"][eid] = {
                            "name": attrs.get("friendly_name", eid),
                            "value": float(state),
                        }
                    except (ValueError, TypeError):
                        pass

            # Kalender-Events (naechste 24h) — States durchreichen, kein doppelter API-Call
            try:
                calendar_events = await self._get_upcoming_events(states=states)
                data["calendar_events"] = calendar_events
            except Exception as e:
                logger.debug("Kalender-Abfrage fehlgeschlagen: %s", e)

        except Exception as e:
            logger.error("Datensammlung fehlgeschlagen: %s", e)

        return data

    async def _get_upcoming_events(self, states: list[dict] = None) -> list[dict]:
        """Holt Kalender-Events der naechsten 24 Stunden."""
        if not states:
            states = await self.ha.get_states()
        if not states:
            return []

        calendar_entities = [
            s["entity_id"] for s in states
            if s.get("entity_id", "").startswith("calendar.")
            and "holiday" not in s["entity_id"]
            and "birthday" not in s["entity_id"]
            and "geburtstag" not in s["entity_id"]
            and "feiertag" not in s["entity_id"]
            and "abfall" not in s["entity_id"]
            and "muell" not in s["entity_id"]
        ]

        if not calendar_entities:
            return []

        now = datetime.now(timezone.utc)
        end = now + timedelta(hours=24)
        all_events = []

        for cal_entity in calendar_entities[:self.max_calendars]:  # H5: Konfigurierbar
            try:
                result = await self.ha.call_service_with_response(
                    "calendar", "get_events",
                    {
                        "entity_id": cal_entity,
                        "start_date_time": now.isoformat(),
                        "end_date_time": end.isoformat(),
                    },
                )
                if isinstance(result, dict):
                    for entity_data in result.values():
                        if isinstance(entity_data, dict):
                            all_events.extend(entity_data.get("events", []))
                        elif isinstance(entity_data, list):
                            all_events.extend(entity_data)
            except Exception as e:
                logger.debug("Kalender %s fehlgeschlagen: %s", cal_entity, e)

        return all_events

    # ------------------------------------------------------------------
    # Regel-basierte Checks
    # ------------------------------------------------------------------

    def _get_check_list(self) -> list[tuple]:
        """Returns the canonical list of (enabled_flag, method) pairs for all checks."""
        return [
            (self.check_weather_windows, self._check_weather_windows),
            (self.check_frost_heating, self._check_frost_heating),
            (self.check_calendar_travel, self._check_calendar_travel),
            (self.check_energy_anomaly, self._check_energy_anomaly),
            (self.check_away_devices, self._check_away_devices),
            (self.check_temp_drop, self._check_temp_drop),
            (self.check_window_temp, self._check_window_temp_drop),
            (self.check_calendar_weather_cross, self._check_calendar_weather_cross),
            (self.check_comfort_contradiction, self._check_comfort_contradiction),
            # Phase 18: 3D+ Cross-Reference Checks
            (self.check_guest_preparation, self._check_guest_preparation),
            (self.check_away_security_full, self._check_away_security_full),
            (self.check_health_work_pattern, self._check_health_work_pattern),
            (self.check_humidity_contradiction, self._check_humidity_contradiction),
            (True, self._check_trend_prediction),  # Trend-Prediction immer aktiv
            (self.check_night_security, self._check_night_security),
            (self.check_heating_vs_sun, self._check_heating_vs_sun),
            (self.check_forgotten_devices, self._check_forgotten_devices),
            (True, self._check_device_dependency_conflicts),  # DEVICE_DEPENDENCIES
            (self._llm_causal_enabled, self._check_llm_causal),  # LLM-basierte Kausalanalyse
        ]

    async def _run_all_checks(self) -> list[dict]:
        """Fuehrt alle aktivierten Checks aus."""
        data = await self._gather_data()
        if not data["states"]:
            return []

        insights = []

        check_methods = self._get_check_list()

        for enabled, method in check_methods:
            if not enabled:
                continue
            try:
                result = await method(data)
                if result and not await self._is_on_cooldown(result["check"]):
                    insights.append(result)
                    await self._set_cooldown(result["check"])
            except Exception as e:
                logger.warning("Check %s fehlgeschlagen: %s", method.__name__, e)

        return insights

    async def _check_llm_causal(self, data: dict) -> Optional[dict]:
        """LLM-basierte Kausalanalyse: Findet ungewoehnliche Korrelationen.

        Gibt dem LLM eine kompakte Daten-Zusammenfassung und fragt nach
        EINER ungewoehnlichen Korrelation die kein Mensch als Regel kodiert haette.
        """
        if not self._ollama:
            return None

        # Eigener Cooldown (laenger als Standard wegen LLM-Kosten)
        if self.redis:
            _ck = "mha:insight:llm_causal_last"
            last = await self.redis.get(_ck)
            if last:
                return None

        # Kompakte Daten-Summary erstellen
        summary_parts = []

        # Temperaturen
        temps = data.get("temperatures", {})
        if temps:
            temp_lines = [f"  {k}: {v}°C" for k, v in list(temps.items())[:8]]
            summary_parts.append("Temperaturen:\n" + "\n".join(temp_lines))

        # Offene Fenster/Tueren
        if data.get("open_windows"):
            summary_parts.append(f"Offene Fenster: {len(data['open_windows'])}")
        if data.get("open_doors"):
            summary_parts.append(f"Offene Tueren: {len(data['open_doors'])}")

        # Wetter (keys: condition, temp, humidity — aus _gather_data)
        weather = data.get("weather")
        if weather and isinstance(weather, dict):
            w_state = weather.get("condition", "")
            w_temp = weather.get("temp", "?")
            summary_parts.append(f"Wetter: {w_state}, {w_temp}°C")

        # Anwesende
        if data.get("persons_home"):
            _names = []
            for p in data["persons_home"][:5]:
                if isinstance(p, dict):
                    _names.append(p.get("name", "?"))
                elif isinstance(p, str):
                    _names.append(p)
            if _names:
                summary_parts.append(f"Anwesend: {', '.join(_names)}")
        if data.get("persons_away"):
            summary_parts.append(f"Abwesend: {len(data['persons_away'])} Personen")

        # Alarm
        if data.get("alarm_state"):
            _alarm = data["alarm_state"]
            if isinstance(_alarm, dict):
                summary_parts.append(f"Alarm: {_alarm.get('state', '?')}")
            elif isinstance(_alarm, str):
                summary_parts.append(f"Alarm: {_alarm}")

        # Kalender
        if data.get("calendar_events"):
            events = data["calendar_events"][:3]
            cal_lines = []
            for e in events:
                if isinstance(e, dict):
                    cal_lines.append(f"  {e.get('summary', '?')} ({e.get('start', '?')})")
                elif isinstance(e, str):
                    cal_lines.append(f"  {e}")
            if cal_lines:
                summary_parts.append("Naechste Termine:\n" + "\n".join(cal_lines))

        # Lichter an
        if data.get("lights_on"):
            summary_parts.append(f"Lichter an: {len(data['lights_on'])}")

        # Klima
        if data.get("climate"):
            climate_lines = []
            for c in data["climate"][:4]:
                if isinstance(c, dict):
                    eid = c.get("entity_id", "?")
                    attrs = c.get("attributes", {}) if isinstance(c.get("attributes"), dict) else {}
                    cur = attrs.get("current_temperature", "?")
                    target = attrs.get("temperature", "?")
                    climate_lines.append(f"  {eid}: {cur}°C (Ziel: {target}°C)")
            if climate_lines:
                summary_parts.append("Klima:\n" + "\n".join(climate_lines))

        if len(summary_parts) < 3:
            return None  # Zu wenig Daten fuer sinnvolle Analyse

        data_summary = "\n".join(summary_parts)

        try:
            response = await asyncio.wait_for(
                self._ollama.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Du bist ein Smart-Home-Analyst. Analysiere die Hausdaten und finde "
                                "EINE ungewoehnliche Korrelation oder ein Problem das kein Mensch "
                                "als einfache Regel kodiert haette. Denke ueber Zusammenhaenge nach: "
                                "Wetter + offene Fenster + Heizung, Termine + Anwesenheit + Sicherheit, "
                                "Energiemuster + Tageszeit + Verhalten.\n"
                                "Antworte mit EINEM kurzen Satz (max 100 Woerter). "
                                "Wenn alles normal ist, antworte NUR mit 'NICHTS'."
                            ),
                        },
                        {
                            "role": "user",
                            "content": f"Aktuelle Hausdaten:\n{data_summary}",
                        },
                    ],
                    model_tier="fast",
                    temperature=0.3,
                    max_tokens=200,
                ),
                timeout=8.0,
            )

            content = ""
            if isinstance(response, dict):
                msg = response.get("message", {})
                content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
            elif hasattr(response, "message"):
                content = getattr(response.message, "content", str(response.message))

            content = content.strip()

            # Think-Tags entfernen
            if "<think>" in content:
                think_end = content.find("</think>")
                if think_end != -1:
                    content = content[think_end + 8:].strip()

            if not content or content.upper() == "NICHTS" or len(content) < 10:
                # Cooldown trotzdem setzen
                if self.redis:
                    await self.redis.setex(_ck, self._llm_causal_cooldown, "1")
                return None

            # Cooldown setzen
            if self.redis:
                await self.redis.setex(_ck, self._llm_causal_cooldown, "1")

            return {
                "check": "llm_causal",
                "message": content,
                "urgency": "medium",
                "data": {"source": "llm_causal_analysis", "summary_length": len(data_summary)},
            }

        except asyncio.TimeoutError:
            logger.debug("LLM Causal Check Timeout")
        except Exception as e:
            logger.debug("LLM Causal Check Fehler: %s", e)

        return None

    async def _check_device_dependency_conflicts(self, data: dict) -> Optional[dict]:
        """Prueft aktive Device-Dependency-Konflikte via DEVICE_DEPENDENCIES."""
        try:
            from .state_change_log import StateChangeLog
            states = data.get("states", [])
            if not states:
                return None
            state_dict = {
                s["entity_id"]: s.get("state", "")
                for s in states if "entity_id" in s
            }
            scl = StateChangeLog.__new__(StateChangeLog)
            conflicts = scl.detect_conflicts(state_dict)
            active = [c for c in conflicts if c.get("affected_active")]
            if not active:
                return None
            # Deduplizieren: gleiche hint nur einmal zaehlen
            seen_hints: set[str] = set()
            unique_active: list[dict] = []
            for c in active:
                h = c.get("hint", "")
                if h not in seen_hints:
                    seen_hints.add(h)
                    unique_active.append(c)
            if not unique_active:
                return None
            hints = [c.get("hint", "") for c in unique_active[:3]]
            count = len(unique_active)
            return {
                "check": "device_dependency_conflicts",
                "message": f"{count} Geraete-Konflikt(e): {'; '.join(hints)}",
                "urgency": "medium" if count < 3 else "high",
                "data": {"conflicts": unique_active[:5], "count": count},
            }
        except Exception as e:
            logger.debug("Device-Dependency-Insight Fehler: %s", e)
            return None

    async def _check_weather_windows(self, data: dict) -> Optional[dict]:
        """Regen/Sturm in Forecast + Fenster offen."""
        if not data["open_windows"] or not data["forecast"]:
            return None

        for fc in data["forecast"][:3]:
            condition = str(fc.get("condition", "")).lower()
            precipitation = fc.get("precipitation", 0) or 0

            if condition in _RAIN_CONDITIONS or precipitation > 2:
                fc_time = fc.get("datetime", "")
                # Zeitpunkt formatieren
                time_hint = ""
                if fc_time:
                    try:
                        fc_dt = datetime.fromisoformat(fc_time.replace("Z", "+00:00"))
                        fc_local = fc_dt.astimezone(_LOCAL_TZ)
                        hours_until = (fc_local - datetime.now(_LOCAL_TZ)).total_seconds() / 3600
                        if hours_until <= 0:
                            time_hint = "jetzt"
                        elif hours_until < 1:
                            time_hint = "in Kürze"
                        elif hours_until < 2:
                            time_hint = "in etwa einer Stunde"
                        elif hours_until < 3:
                            time_hint = f"in etwa {int(hours_until)} Stunden"
                        else:
                            time_hint = f"gegen {fc_local.strftime('%H:%M')} Uhr"
                    except (ValueError, TypeError):
                        time_hint = "bald"

                windows = ", ".join(data["open_windows"][:3])
                extra = f" (und {len(data['open_windows']) - 3} weitere)" if len(data["open_windows"]) > 3 else ""

                is_storm = condition in _STORM_CONDITIONS
                urgency = "high" if is_storm else "medium"
                weather_word = "Sturm" if is_storm else "Regen"

                return {
                    "check": "weather_windows",
                    "urgency": urgency,
                    "message": (
                        f"{await self._get_title_for_home()}, {time_hint} zieht {weather_word} auf — "
                        f"{windows}{extra} {'stehen' if len(data['open_windows']) > 1 else 'steht'} "
                        f"noch offen."
                    ),
                    "data": {
                        "condition": condition,
                        "windows": data["open_windows"],
                        "forecast_time": fc_time,
                    },
                }

        return None

    async def _check_frost_heating(self, data: dict) -> Optional[dict]:
        """Frost in Forecast + Heizung aus oder auf Away."""
        if not data["forecast"] or not data["climate"]:
            return None

        # Frost in naechsten 24h?
        frost_forecast = None
        for fc in data["forecast"]:
            temp = fc.get("temperature")
            templow = fc.get("templow", temp)
            check_temp = templow if templow is not None else temp
            if check_temp is not None and check_temp <= self.frost_temp:
                frost_forecast = fc
                break

        if not frost_forecast:
            return None

        # Heizung checken
        heating_issues = []
        for cl in data["climate"]:
            state = cl.get("state", "")
            preset = cl.get("preset_mode", "").lower()
            if state == "off":
                heating_issues.append(f"{cl['name']} ist aus")
            elif preset in ("away", "eco", "abwesend"):
                heating_issues.append(f"{cl['name']} ist auf {preset}")

        if not heating_issues:
            return None

        frost_temp = frost_forecast.get("templow") or frost_forecast.get("temperature")

        return {
            "check": "frost_heating",
            "urgency": "medium",
            "message": (
                f"{await self._get_title_for_home()}, es werden {frost_temp}°C erwartet — "
                f"{', '.join(heating_issues)}. "
                f"Frostschäden wären vermeidbar."
            ),
            "data": {
                "frost_temp": frost_temp,
                "heating_issues": heating_issues,
            },
        }

    async def _check_calendar_travel(self, data: dict) -> Optional[dict]:
        """Reise-Event im Kalender + Alarm deaktiviert."""
        if not data["calendar_events"]:
            return None

        travel_event = None
        for ev in data["calendar_events"]:
            summary = str(ev.get("summary", "")).lower()
            if any(kw in summary for kw in _TRAVEL_KEYWORDS):
                travel_event = ev
                break

        if not travel_event:
            return None

        # Wann ist das Event?
        ev_start = travel_event.get("start", "")
        if isinstance(ev_start, dict):
            ev_start = ev_start.get("dateTime", ev_start.get("date", ""))
        ev_summary = travel_event.get("summary", "Termin")

        # Hinweise sammeln
        hints = []

        # Alarm-Status
        if data["alarm_state"] and data["alarm_state"] in ("disarmed", "off"):
            hints.append("Die Alarmanlage ist noch deaktiviert")

        # Fenster offen
        if data["open_windows"]:
            count = len(data["open_windows"])
            hints.append(f"{count} Fenster {'sind' if count > 1 else 'ist'} noch offen")

        # Heizung normal (sollte auf Away)
        normal_heating = [
            cl["name"] for cl in data["climate"]
            if cl.get("state") not in ("off", "unavailable")
            and cl.get("preset_mode", "").lower() not in ("away", "eco", "abwesend")
        ]
        if normal_heating:
            hints.append("Heizung läuft im Normalmodus")

        if not hints:
            return None

        return {
            "check": "calendar_travel",
            "urgency": "low",
            "message": (
                f'{await self._get_title_for_home()}, "{ev_summary}" steht an. '
                f"{' — '.join(hints)}. "
                f"Soll ich das Haus vorbereiten?"
            ),
            "data": {
                "event": ev_summary,
                "event_start": str(ev_start),
                "hints": hints,
            },
        }

    async def _check_energy_anomaly(self, data: dict) -> Optional[dict]:
        """Energie-Verbrauch deutlich überBaseline."""
        if not self.redis:
            return None

        try:
            # 7-Tage-Durchschnitt + heutiger Verbrauch per mget laden
            now_ts = datetime.now(timezone.utc)
            all_keys = [
                f"mha:energy:daily:{(now_ts - timedelta(days=i)).strftime('%Y-%m-%d')}"
                for i in range(1, 8)
            ]
            today_key = f"mha:energy:daily:{now_ts.strftime('%Y-%m-%d')}"
            all_keys.append(today_key)
            raw_results = await self.redis.mget(all_keys)

            values = []
            for raw in raw_results[:7]:
                if raw:
                    try:
                        day_data = json.loads(raw)
                        val = day_data.get("consumption_wh", 0)
                        if val > 0:
                            values.append(val)
                    except (json.JSONDecodeError, TypeError):
                        continue

            if len(values) < 3:
                return None

            avg = sum(values) / len(values)
            if avg <= 0:
                return None

            # Heutigen Verbrauch aus dem letzten mget-Ergebnis
            today_raw = raw_results[7]
            if not today_raw:
                return None

            today_data = json.loads(today_raw)
            today_val = today_data.get("consumption_wh", 0)
            if today_val <= 0:
                return None

            # Hochrechnung auf Tagesende
            now = datetime.now(_LOCAL_TZ)
            hours_passed = now.hour + now.minute / 60.0
            if hours_passed < 1:
                return None  # Zu frueh fuer sinnvolle Hochrechnung (Division-by-zero-Schutz)

            projected = today_val / hours_passed * 24
            increase_pct = ((projected - avg) / avg) * 100

            if increase_pct < self.energy_anomaly_pct:
                return None

            # Dynamische Urgency: >500% = high, >200% = medium, sonst low
            if increase_pct > 500:
                _urgency = "high"
            elif increase_pct > 200:
                _urgency = "medium"
            else:
                _urgency = "low"

            return {
                "check": "energy_anomaly",
                "urgency": _urgency,
                "message": (
                    f"{await self._get_title_for_home()}, der Stromverbrauch heute liegt {increase_pct:.0f}% über "
                    f"dem Durchschnitt. "
                    f"Läuft etwas, das nicht laufen sollte?"
                ),
                "data": {
                    "projected_wh": round(projected),
                    "avg_wh": round(avg),
                    "increase_pct": round(increase_pct),
                },
            }

        except Exception as e:
            logger.debug("Energie-Check fehlgeschlagen: %s", e)
            return None

    async def _check_away_devices(self, data: dict) -> Optional[dict]:
        """Niemand zu Hause + Lichter/Geraete an."""
        away_key = f"{_PREFIX}:away_since"

        # Jemand da? → Tracker loeschen
        if data["persons_home"]:
            if self.redis:
                await self.redis.delete(away_key)
            return None

        if not data["persons_away"]:
            return None

        # Wie lange schon weg?
        if self.redis:
            away_since = await self.redis.get(away_key)
            if not away_since:
                await self.redis.setex(away_key, 86400, datetime.now(timezone.utc).isoformat())
                return None  # Gerade erst gegangen
            try:
                away_since = away_since.decode() if isinstance(away_since, bytes) else away_since
                since_dt = datetime.fromisoformat(away_since)
                minutes_away = (datetime.now(timezone.utc) - since_dt).total_seconds() / 60
                if minutes_away < self.away_minutes:
                    return None  # Noch nicht lang genug weg
            except (ValueError, TypeError):
                return None
        else:
            return None

        # Was ist noch an?
        issues = []
        if data["lights_on"]:
            lights = ", ".join(data["lights_on"][:3])
            extra = f" (+{len(data['lights_on']) - 3})" if len(data["lights_on"]) > 3 else ""
            issues.append(f"Licht: {lights}{extra}")

        if data["open_windows"]:
            windows = ", ".join(data["open_windows"][:2])
            issues.append(f"Fenster offen: {windows}")

        if not issues:
            # Abwesenheits-Tracker aufraeumen
            if self.redis:
                await self.redis.delete(away_key)
            return None

        hours_away = minutes_away / 60

        return {
            "check": "away_devices",
            "urgency": "low",
            "message": (
                f"{await self._get_title_for_home()}, du bist seit {hours_away:.0f} Stunden weg — "
                f"{'. '.join(issues)}."
            ),
            "data": {
                "hours_away": round(hours_away, 1),
                "lights_on": data["lights_on"],
                "open_windows": data["open_windows"],
            },
        }

    async def _check_temp_drop(self, data: dict) -> Optional[dict]:
        """Temperatur in einem Raum fällt ungewöhnlich schnell."""
        if not self.redis or not data["temperatures"]:
            return None

        try:
            now = datetime.now(timezone.utc)
            # Snapshot von vor 2h holen
            snapshot_key = f"mha:health:snapshot:{(now - timedelta(hours=2)).strftime('%Y-%m-%d:%H')}"
            snapshot_raw = await self.redis.get(snapshot_key)
            if not snapshot_raw:
                return None

            snapshot = json.loads(snapshot_raw)
            old_temp = snapshot.get("temperature")
            if old_temp is None:
                return None

            # Aktuellen Durchschnitt berechnen
            current_temps = [t["value"] for t in data["temperatures"].values()]
            if not current_temps:
                return None

            current_avg = sum(current_temps) / len(current_temps)
            drop = old_temp - current_avg

            if drop < self.temp_drop_degrees:
                return None

            # Ursache ermitteln
            cause_hint = ""
            if data["open_windows"]:
                cause_hint = f" Fenster offen: {', '.join(data['open_windows'][:2])}."
            elif any(cl.get("state") == "off" for cl in data["climate"]):
                cause_hint = " Heizung ist aus."

            # Dynamische Urgency: <16°C oder >5°C Drop = high, <18°C = medium
            if current_avg < 16 or drop > 5:
                _urgency = "high"
            elif current_avg < 18:
                _urgency = "medium"
            else:
                _urgency = "low"

            return {
                "check": "temp_drop",
                "urgency": _urgency,
                "message": (
                    f"{await self._get_title_for_home()}, die Raumtemperatur fällt ungewöhnlich — "
                    f"{drop:.1f} Grad in 2 Stunden, jetzt bei {current_avg:.1f}°C.{cause_hint}"
                ),
                "data": {
                    "old_temp": old_temp,
                    "current_temp": round(current_avg, 1),
                    "drop": round(drop, 1),
                },
            }

        except Exception as e:
            logger.debug("Temperatur-Trend-Check fehlgeschlagen: %s", e)
            return None

    async def _check_window_temp_drop(self, data: dict) -> Optional[dict]:
        """Fenster offen + Aussentemperatur deutlich unter Innentemperatur."""
        if not data["open_windows"] or not data["weather"]:
            return None

        outside_temp = data["weather"].get("temp")
        if outside_temp is None:
            return None

        # Innentemperatur aus Climate-Entities
        inside_temps = [
            cl["current_temp"] for cl in data["climate"]
            if cl.get("current_temp") is not None
        ]
        if not inside_temps:
            return None

        inside_avg = sum(inside_temps) / len(inside_temps)
        diff = inside_avg - outside_temp

        # Nur relevant wenn draussen deutlich kaelter
        # Schwelle: temp_drop_degrees * 2.5 (Default: 3 * 2.5 = 7.5°C)
        window_temp_threshold = self.temp_drop_degrees * 2.5
        if diff < window_temp_threshold:
            return None

        windows = ", ".join(data["open_windows"][:3])
        return {
            "check": "window_temp_drop",
            "urgency": "low",
            "message": (
                f"{await self._get_title_for_home()}, bei {outside_temp:.0f}°C draussen und offenem {windows} "
                f"heizen wir gerade die Nachbarschaft mit — "
                f"drinnen {inside_avg:.0f}°C."
            ),
            "data": {
                "outside_temp": outside_temp,
                "inside_temp": round(inside_avg, 1),
                "diff": round(diff, 1),
                "windows": data["open_windows"],
            },
        }

    # ------------------------------------------------------------------
    # Cooldown-Management
    # ------------------------------------------------------------------

    async def _is_on_cooldown(self, check_name: str) -> bool:
        """Prueft ob ein Check im Cooldown ist."""
        if not self.redis:
            return False
        key = f"{_PREFIX}:cooldown:{check_name}"
        return await self.redis.exists(key) > 0

    async def _set_cooldown(self, check_name: str):
        """Setzt Cooldown fuer einen Check."""
        if not self.redis:
            return
        key = f"{_PREFIX}:cooldown:{check_name}"
        ttl = self.cooldown_hours * 3600
        await self.redis.setex(key, ttl, "1")

    # ------------------------------------------------------------------
    # On-Demand Check (fuer Inline-Nutzung im Conversation Flow)
    # ------------------------------------------------------------------

    async def run_checks_now(self) -> list[dict]:
        """Fuehrt alle Checks SOFORT aus, OHNE Cooldown zu setzen.

        Wird vom Brain im Conversation Flow aufgerufen um aktuelle
        Insights in den LLM-Kontext zu injizieren. Kein Cooldown,
        da die Insights hier nicht per TTS zugestellt werden sondern
        als Kontext-Sektion fuer das LLM dienen.

        Returns:
            Liste von Insight-Dicts (check, message, urgency, data)
        """
        if not self.enabled:
            return []

        try:
            data = await self._gather_data()
            if not data["states"]:
                return []

            insights = []
            check_methods = self._get_check_list()

            for enabled, method in check_methods:
                if not enabled:
                    continue
                try:
                    result = await method(data)
                    if result:
                        insights.append(result)
                except Exception as e:
                    logger.debug("On-Demand Check Fehler: %s", e)

            return insights
        except Exception as e:
            logger.debug("run_checks_now Fehler: %s", e)
            return []

    # ------------------------------------------------------------------
    # Trend-Prediction: Temperatur-Extrapolation
    # ------------------------------------------------------------------

    async def _store_temp_snapshot(self, data: dict) -> None:
        """Speichert aktuelle Raumtemperaturen fuer Trend-Analyse."""
        if not self.redis:
            return
        temps = {}
        for state in data.get("states", []):
            eid = state.get("entity_id", "")
            if eid.startswith("climate."):
                current = state.get("attributes", {}).get("current_temperature")
                if current is not None:
                    try:
                        temp_val = float(current)
                        if -20 < temp_val < 50:
                            name = state.get("attributes", {}).get("friendly_name", eid)
                            temps[name] = temp_val
                    except (ValueError, TypeError):
                        pass
        if temps:
            try:
                await self.redis.lpush(
                    "mha:insight:temp_history",
                    json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "temps": temps}),
                )
                await self.redis.ltrim("mha:insight:temp_history", 0, self.max_temp_snapshots - 1)
                await self.redis.expire("mha:insight:temp_history", 6 * 3600)
            except Exception as e:
                logger.debug("Temp snapshot error: %s", e)

    async def _check_trend_prediction(self, data: dict) -> Optional[dict]:
        """Einfache lineare Trend-Extrapolation fuer Raumtemperaturen."""
        if not self.redis:
            return None

        # Aktuellen Snapshot speichern
        await self._store_temp_snapshot(data)

        try:
            snapshots_raw = await self.redis.lrange("mha:insight:temp_history", 0, self.max_temp_snapshots - 1)  # H5
        except Exception as e:
            logger.debug("Insight-Analyse fehlgeschlagen: %s", e)
            return None

        if len(snapshots_raw) < 3:
            return None

        try:
            snapshots = [json.loads(s) for s in snapshots_raw]
        except (json.JSONDecodeError, TypeError):
            return None

        newest = snapshots[0].get("temps", {})
        oldest = snapshots[-1].get("temps", {})
        try:
            newest_ts = datetime.fromisoformat(snapshots[0].get("ts", ""))
            oldest_ts = datetime.fromisoformat(snapshots[-1].get("ts", ""))
            hours_diff = (newest_ts - oldest_ts).total_seconds() / 3600
        except (KeyError, ValueError):
            return None

        if hours_diff < 0.25:  # Mindestens 15 Min Beobachtungsfenster
            return None

        for room in newest:
            if room in oldest:
                try:
                    rate_per_hour = (newest[room] - oldest[room]) / hours_diff
                    predicted_2h = newest[room] + rate_per_hour * 2

                    if predicted_2h < 17 and rate_per_hour < -0.5:
                        return {
                            "check": "trend_prediction",
                            "urgency": "medium",
                            "message": (
                                f"{room}: Temperatur faellt ({rate_per_hour:+.1f}°C/h). "
                                f"In 2 Stunden voraussichtlich {predicted_2h:.0f}°C."
                            ),
                        }
                except (TypeError, ZeroDivisionError):
                    continue

        return None

    # ------------------------------------------------------------------
    # Status & Diagnostik
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # MCU-JARVIS: Kreuz-Referenz Checks (Kalender x Wetter, Komfort-Widersprueche)
    # ------------------------------------------------------------------

    async def _check_calendar_weather_cross(self, data: dict) -> Optional[dict]:
        """Kalender-Termin morgen frueh + schlechtes Wetter = Empfehlung.

        MCU-JARVIS wuerde sagen: 'Du hast morgen frueh einen Termin,
        und es soll regnen. Schirm nicht vergessen.'
        """
        if not data.get("calendar_events") or not data.get("forecast"):
            return None

        now = datetime.now(timezone.utc)

        # Termine in den naechsten 18 Stunden suchen
        for event in data["calendar_events"]:
            start = event.get("start")
            if not start:
                continue
            try:
                if isinstance(start, str):
                    event_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    if event_dt.tzinfo is None:
                        event_dt = event_dt.replace(tzinfo=timezone.utc)
                else:
                    continue
            except (ValueError, TypeError):
                continue

            hours_until = (event_dt - now).total_seconds() / 3600
            if hours_until < 1 or hours_until > 18:
                continue

            # Schlechtes Wetter im gleichen Zeitfenster?
            for fc in data["forecast"][:5]:
                condition = str(fc.get("condition", "")).lower()
                if condition not in _RAIN_CONDITIONS:
                    continue

                summary = event.get("summary", "Termin")
                if hours_until < 3:
                    time_hint = "in Kürze"
                elif hours_until < 6:
                    time_hint = f"in {int(hours_until)} Stunden"
                else:
                    time_hint = f"morgen um {event_dt.strftime('%H:%M')}"

                title = await self._get_title_for_home()
                weather_word = "Sturm" if condition in _STORM_CONDITIONS else "Regen"

                return {
                    "check": "calendar_weather_cross",
                    "urgency": "medium",
                    "message": (
                        f"{title}, du hast {time_hint} '{summary}' — "
                        f"und es soll {weather_word} geben. "
                        f"{'Schirm einpacken.' if condition not in _STORM_CONDITIONS else 'Regenkleidung empfohlen.'}"
                    ),
                    "data": {
                        "event": summary,
                        "weather": condition,
                        "hours_until": round(hours_until, 1),
                    },
                }

        return None

    async def _check_comfort_contradiction(self, data: dict) -> Optional[dict]:
        """Erkennt Komfort-Widersprueche im Haus.

        MCU-JARVIS-Feature: Heizung läuft + Fenster offen = Energieverschwendung.
        Licht an + niemand im Raum = unnoetig.
        """
        # Heizung läuft + Fenster offen im gleichen Bereich
        if data.get("open_windows") and data.get("climate"):
            heating_rooms = []
            for c in data["climate"]:
                hvac = c.get("hvac_action", "")
                if hvac in ("heating", "cooling"):
                    name = c.get("name", "")
                    heating_rooms.append(name)

            if heating_rooms and data["open_windows"]:
                # Vereinfachter Match: Gibt es ein offenes Fenster
                # während eine Heizung läuft?
                title = await self._get_title_for_home()
                heating_str = heating_rooms[0]
                window_str = data["open_windows"][0]

                return {
                    "check": "comfort_contradiction",
                    "urgency": "low",
                    "message": (
                        f"{title}, die Heizung in {heating_str} läuft, "
                        f"während {window_str} offen steht. "
                        f"Energetisch... nicht ganz optimal."
                    ),
                    "data": {
                        "heating": heating_rooms,
                        "windows": data["open_windows"],
                    },
                }

        return None

    # ------------------------------------------------------------------
    # Phase 18: 3D+ Cross-Reference Checks
    # ------------------------------------------------------------------

    _GUEST_KEYWORDS = [
        "gast", "gaeste", "besuch", "party", "feier", "einladung",
        "dinner", "abendessen", "geburtstag", "grillen", "brunch",
    ]

    async def _check_guest_preparation(self, data: dict) -> Optional[dict]:
        """Kalender[Gaeste-Keywords] + Haus nicht bereit → Hinweis.

        3D+ Cross-Reference: Kalender × Sicherheit × Klima × Beleuchtung × Türen.
        Prueft: Alarm scharf, Lichter aus, Temperatur unbequem, Türen offen.
        """
        events = data.get("calendar_events", [])
        if not events:
            return None

        # Gaeste-Event in den naechsten 4 Stunden?
        guest_event = None
        now = datetime.now(timezone.utc)
        for ev in events:
            title_lower = ev.get("summary", "").lower()
            start_raw = ev.get("start", "")
            if not any(kw in title_lower for kw in self._GUEST_KEYWORDS):
                continue
            # FIX-C3: Handle dict and date-only start formats
            if isinstance(start_raw, dict):
                start_str = start_raw.get("dateTime", start_raw.get("date", ""))
            else:
                start_str = str(start_raw)
            if not start_str or "T" not in start_str:
                continue  # Skip all-day events
            try:
                start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=timezone.utc)
                hours_until = (start_dt - now).total_seconds() / 3600
                if 0 < hours_until <= 4:
                    guest_event = ev
                    break
            except (ValueError, TypeError, AttributeError):
                continue

        if not guest_event:
            return None

        # Haus-Zustand pruefen: offene Probleme sammeln
        issues = []

        # Alarm noch scharf?
        states = data.get("states", [])
        for s in states:
            eid = s.get("entity_id", "")
            if "alarm_control_panel" in eid and s.get("state") in ("armed_away", "armed_home"):
                issues.append("Alarm ist noch scharf")
                break

        # Alle Lichter aus?
        lights_on = 0
        for s in states:
            if s.get("entity_id", "").startswith("light.") and s.get("state") == "on":
                lights_on += 1
        if lights_on == 0:
            issues.append("Alle Lichter sind aus")

        # Temperatur: Zu kalt (<19°C) oder zu warm (>26°C) fuer Gaeste?
        climate_data = data.get("climate", [])
        uncomfortable_rooms = []
        for cl in climate_data:
            current_temp = cl.get("current_temp")
            if current_temp is not None:
                if current_temp < 19:
                    uncomfortable_rooms.append(f"{cl['name']} nur {current_temp:.0f}°C")
                elif current_temp > 26:
                    uncomfortable_rooms.append(f"{cl['name']} {current_temp:.0f}°C")
        if uncomfortable_rooms:
            issues.append(f"Temperatur: {', '.join(uncomfortable_rooms[:2])}")

        # Offene Türen pruefen (Haustuer etc.)
        open_doors = data.get("open_doors", [])
        if open_doors:
            issues.append(f"Türen offen: {', '.join(open_doors[:2])}")

        if not issues:
            return None

        title = await self._get_title_for_home()
        event_title = guest_event.get("summary", "Gaeste")
        issues_str = " und ".join(issues)

        return {
            "check": "guest_preparation",
            "urgency": "medium",
            "message": (
                f"{title}, '{event_title}' steht in Kürze an. "
                f"Allerdings: {issues_str}. Soll ich das Haus vorbereiten?"
            ),
            "data": {"event": event_title, "issues": issues},
        }

    async def _check_away_security_full(self, data: dict) -> Optional[dict]:
        """Abwesend + offene Fenster/Türen + Alarm aus → priorisierte Sicherheits-Checkliste.

        3D+ Cross-Reference: Anwesenheit × Fenster × Türen × Alarm × Licht.
        Offene Türen werden als kritischer gewichtet als Fenster.
        """
        states = data.get("states", [])
        if not states:
            return None

        # Alle Personen away?
        person_entities = [
            s for s in states if s.get("entity_id", "").startswith("person.")
        ]
        if not person_entities:
            return None  # Keine Person-Entities — kann Anwesenheit nicht bestimmen

        persons_home = [
            s.get("attributes", {}).get("friendly_name", "")
            for s in person_entities if s.get("state") == "home"
        ]
        if persons_home:
            return None  # Jemand ist zuhause

        # Probleme sammeln (nach Prioritaet sortiert)
        issues = []

        # Offene Türen (hoechste Prioritaet — Sicherheitsrisiko)
        open_doors = data.get("open_doors", [])
        if open_doors:
            doors = open_doors[:3]
            issues.append(f"Türen offen: {', '.join(doors)}")

        # Offene Fenster
        if data.get("open_windows"):
            windows = data["open_windows"][:3]
            issues.append(f"Fenster offen: {', '.join(windows)}")

        # Alarm aus
        alarm_armed = False
        for s in states:
            if "alarm_control_panel" in s.get("entity_id", ""):
                if s.get("state") in ("armed_away", "armed_home", "armed_night"):
                    alarm_armed = True
        if not alarm_armed:
            issues.append("Alarm nicht aktiviert")

        # Lichter an
        lights_on = []
        for s in states:
            eid = s.get("entity_id", "")
            if eid.startswith("light.") and s.get("state") == "on":
                name = s.get("attributes", {}).get("friendly_name", eid)
                lights_on.append(name)
        if lights_on:
            issues.append(f"Lichter an: {', '.join(lights_on[:3])}")

        # Offene Tuer allein reicht fuer Hinweis (kritischer als Fenster)
        min_issues = 1 if open_doors else 2
        if len(issues) < min_issues:
            return None

        title = await self._get_title_for_home()
        issues_str = "; ".join(issues)

        return {
            "check": "away_security_full",
            "urgency": "high",
            "message": (
                f"{title}, niemand ist zuhause, aber: {issues_str}. "
                f"Soll ich Maßnahmen ergreifen?"
            ),
            "data": {"issues": issues},
        }

    async def _check_health_work_pattern(self, data: dict) -> Optional[dict]:
        """Arbeitszeit >8h + spaete Uhrzeit + optional schlechtes Raumklima.

        3D+ Cross-Reference: Aktivitaet × Zeit × Raumklima (Temperatur + Luftfeuchtigkeit).
        Raumklima-Probleme verstaerken die Dringlichkeit.
        """
        if not self.activity:
            return None

        hour = datetime.now(_LOCAL_TZ).hour
        if hour < 18:  # Erst abends relevant
            return None

        try:
            activity = self.activity.current_activity
            if activity not in ("focused", "working"):
                return None

            # Wie lange aktiv?
            duration_h = getattr(self.activity, "current_duration_hours", 0) or 0
            if duration_h < 8:
                return None

            # Raumklima pruefen: Temperatur oder Luftfeuchtigkeit problematisch?
            climate_hints = []
            climate_data = data.get("climate", [])
            for cl in climate_data:
                current_temp = cl.get("current_temp")
                if current_temp is not None and current_temp > 25:
                    climate_hints.append(f"{cl['name']} bei {current_temp:.0f}°C")

            # Aussen-Luftfeuchtigkeit als Indikator (>65% = schwuel)
            weather = data.get("weather") or {}
            humidity = weather.get("humidity")
            if humidity is not None and humidity > 65:
                climate_hints.append(f"Luftfeuchtigkeit {humidity}%")

            title = await self._get_title_for_home()

            urgency = "low"
            climate_suffix = ""
            if climate_hints:
                urgency = "medium"
                climate_suffix = f" Dazu: {', '.join(climate_hints[:2])}."

            return {
                "check": "health_work_pattern",
                "urgency": urgency,
                "message": (
                    f"{title}, du arbeitest seit über{int(duration_h)} Stunden. "
                    f"Eine Pause wäre jetzt keine schlechte Idee.{climate_suffix}"
                ),
                "data": {
                    "hours": duration_h,
                    "climate_issues": climate_hints,
                },
            }
        except Exception as e:
            logger.debug("Insight-Analyse fehlgeschlagen: %s", e)
            return None

    async def _check_humidity_contradiction(self, data: dict) -> Optional[dict]:
        """Entfeuchter aktiv + Fenster offen bei Regen/hoher Luftfeuchtigkeit = Widerspruch.

        3D Cross-Reference: Geraete × Fenster × Wetter × Sensoren.
        Nutzt neben Forecast auch Indoor-Luftfeuchtigkeits-Sensoren.
        """
        # Fenster offen?
        if not data.get("open_windows"):
            return None

        # Regnet es oder ist Aussen-Luftfeuchtigkeit hoch?
        is_humid_outside = False
        humidity_detail = ""
        forecast = data.get("forecast", [])
        for fc in forecast[:1]:
            cond = str(fc.get("condition", "")).lower()
            precip = fc.get("precipitation", 0) or 0
            if cond in _RAIN_CONDITIONS or precip > 2:
                is_humid_outside = True
                humidity_detail = "bei Regen"
                break

        # Alternativ: Aussen-Luftfeuchtigkeit > 80%
        if not is_humid_outside:
            weather = data.get("weather") or {}
            outdoor_humidity = weather.get("humidity")
            if outdoor_humidity is not None and outdoor_humidity > 80:
                is_humid_outside = True
                humidity_detail = f"bei {outdoor_humidity}% Luftfeuchtigkeit draussen"

        if not is_humid_outside:
            return None

        # Entfeuchter / Klimaanlage im Entfeuchter-Modus?
        states = data.get("states", [])
        dehumidifier_on = False
        for s in states:
            eid = s.get("entity_id", "")
            if ("dehumid" in eid or "entfeuchter" in eid) and s.get("state") == "on":
                dehumidifier_on = True
                break
            # Klima im Dry-Modus
            if "climate" in eid and s.get("attributes", {}).get("hvac_mode") == "dry":
                dehumidifier_on = True
                break

        if not dehumidifier_on:
            return None

        # Indoor-Sensor pruefen fuer konkretere Meldung
        indoor_humidity = None
        for s in states:
            eid = s.get("entity_id", "")
            if eid.startswith("sensor.") and "humidity" in eid:
                try:
                    val = float(s.get("state", ""))
                    if 10 < val < 100:  # Plausibilitaetscheck
                        indoor_humidity = val
                        break
                except (ValueError, TypeError):
                    pass

        title = await self._get_title_for_home()
        windows = ", ".join(data["open_windows"][:2])

        indoor_hint = ""
        if indoor_humidity is not None and indoor_humidity > 60:
            indoor_hint = f" Innen bereits {indoor_humidity:.0f}%."

        return {
            "check": "humidity_contradiction",
            "urgency": "low",
            "message": (
                f"{title}, der Entfeuchter läuft während {windows} "
                f"{humidity_detail} offen steht. Das arbeitet gegeneinander.{indoor_hint}"
            ),
            "data": {
                "windows": data["open_windows"],
                "indoor_humidity": indoor_humidity,
            },
        }

    # ------------------------------------------------------------------
    # Night Security Check
    # ------------------------------------------------------------------

    async def _check_night_security(self, data: dict) -> Optional[dict]:
        """Nach 23 Uhr: Fenster/Türen offen + Person zuhause → Erinnerung.

        Kreuz-referenziert: Uhrzeit × offene Fenster/Türen × Anwesenheit × Aktivitaet.
        """
        now = datetime.now(_LOCAL_TZ)
        if now.hour < 23 and now.hour >= 6:
            return None

        # Nur wenn jemand zuhause ist
        persons_home = data.get("persons_home", [])
        if not persons_home:
            return None

        open_windows = data.get("open_windows", [])
        open_doors = data.get("open_doors", [])
        if not open_windows and not open_doors:
            return None

        # Alarm-Status pruefen — wenn scharf, ist alles ok
        alarm_state = data.get("alarm_state")
        if alarm_state and alarm_state.startswith("armed"):
            return None

        # Aktivitaets-Check: Wenn jemand aktiv arbeitet, nicht stoeren
        if self.activity:
            try:
                if self.activity.current_activity == "working" and \
                   self.activity.current_duration_hours < 2:
                    return None
            except (AttributeError, TypeError):
                pass

        issues = []
        if open_windows:
            windows = ", ".join(open_windows[:3])
            extra = f" (+{len(open_windows) - 3})" if len(open_windows) > 3 else ""
            issues.append(f"Fenster offen: {windows}{extra}")
        if open_doors:
            doors = ", ".join(open_doors[:2])
            issues.append(f"Türen offen: {doors}")

        urgency = "medium"
        if open_doors:
            urgency = "high"

        # Temperatur-Hinweis: Wenn es draussen kalt ist
        temp_hint = ""
        weather = data.get("weather") or {}
        outdoor_temp = weather.get("temperature")
        if outdoor_temp is not None and outdoor_temp < 10:
            temp_hint = f" Draussen sind es {outdoor_temp:.0f}°C."

        title = await self._get_title_for_home()
        issue_text = ". ".join(issues)

        return {
            "check": "night_security",
            "urgency": urgency,
            "message": (
                f"{title}, es ist nach 23 Uhr. {issue_text}.{temp_hint} "
                f"Alles zu fuer die Nacht?"
            ),
            "data": {
                "open_windows": open_windows,
                "open_doors": open_doors,
                "hour": now.hour,
            },
        }

    # ------------------------------------------------------------------
    # Heating vs Sun Check
    # ------------------------------------------------------------------

    async def _check_heating_vs_sun(self, data: dict) -> Optional[dict]:
        """Heizung läuft + sonnig + warm draussen → Sonne nutzen statt heizen.

        Kreuz-referenziert: Klima-Geraete × Wetter × Aussentemperatur × Rollladen.
        """
        weather = data.get("weather") or {}
        condition = str(weather.get("condition", "")).lower()
        outdoor_temp = weather.get("temperature")

        # Sonnig/klar und warm genug?
        sunny_conditions = ["sunny", "clear-night", "partlycloudy"]
        if condition not in sunny_conditions:
            return None
        if outdoor_temp is None or outdoor_temp < 18:
            return None

        # Aktiv heizende Klimageraete finden
        climate_data = data.get("climate", [])
        heating_rooms = []
        for cl in climate_data:
            hvac_action = cl.get("hvac_action", "")
            state = cl.get("state", "")
            if hvac_action == "heating" or (state == "heat" and hvac_action != "idle"):
                heating_rooms.append(cl.get("name", "Unbekannt"))

        if not heating_rooms:
            return None

        # Rollladen-Status pruefen: Sind Rollladen geschlossen?
        covers_closed = []
        for s in data.get("states", []):
            eid = s.get("entity_id", "")
            if eid.startswith("cover."):
                state = s.get("state", "")
                pos = s.get("attributes", {}).get("current_position")
                name = s.get("attributes", {}).get("friendly_name", eid)
                if state == "closed" or (pos is not None and pos < 20):
                    covers_closed.append(name)

        rooms_text = ", ".join(heating_rooms[:3])
        title = await self._get_title_for_home()

        cover_hint = ""
        if covers_closed:
            cover_names = ", ".join(covers_closed[:2])
            extra = f" (+{len(covers_closed) - 2})" if len(covers_closed) > 2 else ""
            cover_hint = f" Die Rollladen ({cover_names}{extra}) sind noch geschlossen."

        return {
            "check": "heating_vs_sun",
            "urgency": "low",
            "message": (
                f"{title}, die Heizung läuft in {rooms_text}, "
                f"aber draussen sind es {outdoor_temp:.0f}°C bei Sonnenschein.{cover_hint} "
                f"Sonne rein lassen statt heizen?"
            ),
            "data": {
                "heating_rooms": heating_rooms,
                "outdoor_temp": outdoor_temp,
                "covers_closed": covers_closed,
                "condition": condition,
            },
        }

    # ------------------------------------------------------------------
    # Forgotten Devices Check
    # ------------------------------------------------------------------

    async def _check_forgotten_devices(self, data: dict) -> Optional[dict]:
        """Media Player / TV an + alle weg oder Schlafenszeit → Erinnerung.

        Kreuz-referenziert: Media-Player-Status × Anwesenheit × Uhrzeit.
        """
        # Alle weg ODER nach Mitternacht + keine Aktivitaet
        persons_home = data.get("persons_home", [])
        persons_away = data.get("persons_away", [])
        now = datetime.now(_LOCAL_TZ)
        is_late_night = 0 <= now.hour < 5

        all_away = len(persons_home) == 0 and len(persons_away) > 0
        if not all_away and not is_late_night:
            return None

        # Media Player / TV finden die laufen
        active_media = []
        for s in data.get("states", []):
            eid = s.get("entity_id", "")
            if eid.startswith("media_player."):
                state = s.get("state", "")
                if state in ("playing", "paused", "on"):
                    name = s.get("attributes", {}).get("friendly_name", eid)
                    media_title = s.get("attributes", {}).get("media_title", "")
                    if media_title:
                        active_media.append(f"{name} ({media_title})")
                    else:
                        active_media.append(name)

        if not active_media:
            return None

        title = await self._get_title_for_home()
        devices = ", ".join(active_media[:3])
        extra = f" (+{len(active_media) - 3})" if len(active_media) > 3 else ""

        if all_away:
            reason = "niemand zuhause ist"
            urgency = "medium"
        else:
            reason = f"es {now.hour} Uhr nachts ist"
            urgency = "low"

        return {
            "check": "forgotten_devices",
            "urgency": urgency,
            "message": (
                f"{title}, {devices}{extra} läuft noch, "
                f"obwohl {reason}. Ausschalten?"
            ),
            "data": {
                "active_media": active_media,
                "all_away": all_away,
                "hour": now.hour,
            },
        }

    # ------------------------------------------------------------------
    # Wetter-Aktions-Vorschlaege: konkrete Handlungsempfehlungen
    # ------------------------------------------------------------------

    def _weather_action_on_cooldown(self, action_key: str) -> bool:
        """Prueft ob eine Wetter-Aktion im 60-Minuten-Cooldown ist."""
        last = self._weather_action_cooldown.get(action_key)
        if last is None:
            return False
        return (datetime.now(timezone.utc) - last).total_seconds() < 3600

    def _set_weather_action_cooldown(self, action_key: str) -> None:
        """Setzt Cooldown fuer eine Wetter-Aktion (60 Min)."""
        self._weather_action_cooldown[action_key] = datetime.now(timezone.utc)
        # Abgelaufene Eintraege aufraeumen (aelter als 2h)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
        expired = [k for k, v in self._weather_action_cooldown.items() if v < cutoff]
        for k in expired:
            del self._weather_action_cooldown[k]

    async def get_weather_action_suggestions(self, ha_client) -> list[dict]:
        """Gibt konkrete, aktionierbare Wetter-Vorschlaege zurueck.

        Analysiert aktuelles Wetter, Forecast, Cover-Positionen und
        Fenstersensoren und leitet daraus strukturierte Handlungsempfehlungen ab.

        Returns:
            Liste von Suggestion-Dicts mit action, entity/message, target,
            reason, urgency (critical/high/medium/low).
        """
        suggestions: list[dict] = []

        try:
            states = await ha_client.get_states()
            if not states:
                logger.debug("Wetter-Aktions-Vorschlaege: keine HA-States verfuegbar")
                return suggestions
        except Exception as e:
            logger.warning("Wetter-Aktions-Vorschlaege: HA-States Fehler: %s", e)
            return suggestions

        # -- Daten aus States extrahieren --
        weather_data: dict = {}
        forecast: list[dict] = []
        covers: list[dict] = []
        open_windows: list[dict] = []
        indoor_temps: list[float] = []

        for s in states:
            eid = s.get("entity_id", "")
            state = s.get("state", "")
            attrs = s.get("attributes", {})

            # Wetter-Entity (erste gefundene)
            if eid.startswith("weather.") and not weather_data:
                weather_data = {
                    "condition": state,
                    "temp": attrs.get("temperature"),
                    "humidity": attrs.get("humidity"),
                    "wind_speed": attrs.get("wind_speed"),
                }
                fc_list = attrs.get("forecast", [])
                if fc_list:
                    forecast = fc_list[:8]

            # Cover-Entities (Markise, Rollladen etc.)
            elif eid.startswith("cover."):
                position = attrs.get("current_position")
                covers.append({
                    "entity_id": eid,
                    "name": attrs.get("friendly_name", eid),
                    "state": state,
                    "position": position,
                    "is_open": state == "open" or (position is not None and position > 20),
                })

            # Fenstersensoren
            elif (eid.startswith("binary_sensor.") and
                  any(kw in eid for kw in ("window", "fenster"))):
                if state == "on":
                    open_windows.append({
                        "entity_id": eid,
                        "name": attrs.get("friendly_name", eid),
                    })

            # Innentemperatur aus Climate-Entities
            elif eid.startswith("climate.") and state != "unavailable":
                current = attrs.get("current_temperature")
                if current is not None:
                    try:
                        indoor_temps.append(float(current))
                    except (ValueError, TypeError):
                        pass

        # -- Forecast analysieren --
        rain_forecast: Optional[dict] = None
        storm_forecast: Optional[dict] = None
        cold_night_forecast: Optional[dict] = None
        hours_until_rain: float = 0
        hours_until_storm: float = 0

        now = datetime.now(_LOCAL_TZ)

        for fc in forecast:
            condition = str(fc.get("condition", "")).lower()
            fc_time = fc.get("datetime", "")
            precipitation = fc.get("precipitation", 0) or 0
            wind_speed = fc.get("wind_speed", 0) or 0
            templow = fc.get("templow")

            # Zeitdifferenz berechnen
            hours_ahead = 0.0
            if fc_time:
                try:
                    fc_dt = datetime.fromisoformat(fc_time.replace("Z", "+00:00"))
                    fc_local = fc_dt.astimezone(_LOCAL_TZ)
                    hours_ahead = (fc_local - now).total_seconds() / 3600
                except (ValueError, TypeError):
                    pass

            # Regen erkennen
            if not rain_forecast and (condition in _RAIN_CONDITIONS or precipitation > 2):
                rain_forecast = fc
                hours_until_rain = hours_ahead

            # Sturm erkennen (Wind > 60 km/h oder Sturm-Condition)
            if not storm_forecast and (
                condition in _STORM_CONDITIONS or wind_speed > 60
            ):
                storm_forecast = fc
                hours_until_storm = hours_ahead

            # Kalte Nacht erkennen (Temperatur < 5°C)
            if not cold_night_forecast and templow is not None and templow < 5:
                cold_night_forecast = fc

        # -- Vorschlag 1: Regen erwartet + Markise/Cover ausgefahren --
        if rain_forecast:
            open_covers = [c for c in covers if c["is_open"]]
            for cover in open_covers:
                action_key = f"rain_cover:{cover['entity_id']}"
                if self._weather_action_on_cooldown(action_key):
                    continue

                # Zeitangabe fuer Reason
                if hours_until_rain <= 0:
                    time_hint = "Regen aktuell"
                elif hours_until_rain < 1:
                    time_hint = "Regen in Kürze erwartet"
                else:
                    time_hint = f"Regen in {int(hours_until_rain)}h erwartet"

                suggestions.append({
                    "action": "set_cover",
                    "entity": cover["entity_id"],
                    "target": "close",
                    "reason": time_hint,
                    "urgency": "high" if hours_until_rain < 1 else "medium",
                })
                self._set_weather_action_cooldown(action_key)

        # -- Vorschlag 2: Sturm erwartet + Fenster offen --
        if storm_forecast and open_windows:
            action_key = "storm_windows_open"
            if not self._weather_action_on_cooldown(action_key):
                window_names = [w["name"] for w in open_windows[:4]]
                windows_str = ", ".join(window_names)

                if hours_until_storm <= 0:
                    time_hint = "Sturm aktiv"
                elif hours_until_storm < 1:
                    time_hint = "Sturm in Kürze"
                else:
                    time_hint = f"Sturm in {int(hours_until_storm)}h"

                suggestions.append({
                    "action": "notify",
                    "message": f"{time_hint} — Fenster noch offen: {windows_str}",
                    "urgency": "critical" if hours_until_storm < 1 else "high",
                })
                self._set_weather_action_cooldown(action_key)

                # Auch offene Covers bei Sturm einfahren
                open_covers = [c for c in covers if c["is_open"]]
                for cover in open_covers:
                    cover_key = f"storm_cover:{cover['entity_id']}"
                    if self._weather_action_on_cooldown(cover_key):
                        continue
                    suggestions.append({
                        "action": "set_cover",
                        "entity": cover["entity_id"],
                        "target": "close",
                        "reason": f"{time_hint} — {cover['name']} einfahren",
                        "urgency": "critical" if hours_until_storm < 1 else "high",
                    })
                    self._set_weather_action_cooldown(cover_key)

        # -- Vorschlag 3: Kalte Nacht (<5°C) + Covers offen → Daemmung --
        if cold_night_forecast:
            open_covers = [c for c in covers if c["is_open"]]
            for cover in open_covers:
                action_key = f"cold_night_cover:{cover['entity_id']}"
                if self._weather_action_on_cooldown(action_key):
                    continue

                templow = cold_night_forecast.get("templow", "?")
                suggestions.append({
                    "action": "set_cover",
                    "entity": cover["entity_id"],
                    "target": "close",
                    "reason": f"Nacht wird kalt ({templow}°C) — Rollladen schliessen fuer Daemmung",
                    "urgency": "low",
                })
                self._set_weather_action_cooldown(action_key)

        # -- Vorschlag 4: Starke Sonne + Innentemperatur steigt → Suedseiten-Covers --
        current_condition = str(weather_data.get("condition", "")).lower()
        outdoor_temp = weather_data.get("temp")

        if (current_condition in ("sunny", "partlycloudy") and
                outdoor_temp is not None and outdoor_temp > 24 and
                indoor_temps):
            avg_indoor = sum(indoor_temps) / len(indoor_temps)

            # Innen > 25°C bei Sonne = Beschattung sinnvoll
            if avg_indoor > 25:
                # Suedseiten-Covers finden (Heuristik: 'sued', 'south', 'terrasse',
                # 'balkon', 'markise' im Namen)
                south_keywords = ("sued", "south", "terrasse", "balkon", "markise",
                                  "wintergarten", "wohnzimmer")
                open_covers = [
                    c for c in covers
                    if c["is_open"] and any(
                        kw in c["entity_id"].lower() or kw in c["name"].lower()
                        for kw in south_keywords
                    )
                ]

                # Falls keine explizit suedlichen Covers, alle offenen vorschlagen
                if not open_covers:
                    open_covers = [c for c in covers if c["is_open"]]

                for cover in open_covers:
                    action_key = f"sun_heat_cover:{cover['entity_id']}"
                    if self._weather_action_on_cooldown(action_key):
                        continue

                    suggestions.append({
                        "action": "set_cover",
                        "entity": cover["entity_id"],
                        "target": "close",
                        "reason": (
                            f"Sonne bei {outdoor_temp:.0f}°C — "
                            f"Innentemperatur {avg_indoor:.0f}°C, Beschattung empfohlen"
                        ),
                        "urgency": "medium" if avg_indoor < 28 else "high",
                    })
                    self._set_weather_action_cooldown(action_key)

        logger.debug(
            "Wetter-Aktions-Vorschlaege: %d Vorschlaege generiert", len(suggestions)
        )
        return suggestions

    async def get_status(self) -> dict:
        """Gibt den aktuellen Status der Engine zurueck."""
        status = {
            "enabled": self.enabled,
            "running": self._running,
            "check_interval_minutes": self.check_interval // 60,
            "cooldown_hours": self.cooldown_hours,
            "checks": {
                "weather_windows": self.check_weather_windows,
                "frost_heating": self.check_frost_heating,
                "calendar_travel": self.check_calendar_travel,
                "energy_anomaly": self.check_energy_anomaly,
                "away_devices": self.check_away_devices,
                "temp_drop": self.check_temp_drop,
                "window_temp_drop": self.check_window_temp,
                "calendar_weather_cross": self.check_calendar_weather_cross,
                "comfort_contradiction": self.check_comfort_contradiction,
                "guest_preparation": self.check_guest_preparation,
                "away_security_full": self.check_away_security_full,
                "health_work_pattern": self.check_health_work_pattern,
                "humidity_contradiction": self.check_humidity_contradiction,
                "night_security": self.check_night_security,
                "heating_vs_sun": self.check_heating_vs_sun,
                "forgotten_devices": self.check_forgotten_devices,
            },
        }

        # Aktive Cooldowns zaehlen
        if self.redis:
            try:
                cooldown_count = 0
                cursor = 0
                while True:
                    cursor, keys = await self.redis.scan(
                        cursor, match=f"{_PREFIX}:cooldown:*", count=50
                    )
                    cooldown_count += len(keys)
                    if cursor == 0:
                        break
                status["active_cooldowns"] = cooldown_count
            except Exception as e:
                logger.debug("Cooldown-Status Abruf fehlgeschlagen: %s", e)
                status["active_cooldowns"] = -1

        return status
