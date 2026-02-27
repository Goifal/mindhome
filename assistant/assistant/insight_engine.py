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
  - Energie-Verbrauch ueber Baseline
  - Abwesenheit + Geraete/Licht an
  - Temperatur-Trend: Raum kuehlt ungewoehnlich ab
  - Fenster offen + Temperatur faellt
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config, get_person_title
from .ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)

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

        # Schwellwerte
        thresholds = cfg.get("thresholds", {})
        self.frost_temp = thresholds.get("frost_temp_c", 2)
        self.energy_anomaly_pct = thresholds.get("energy_anomaly_percent", 30)
        self.away_minutes = thresholds.get("away_device_minutes", 120)
        self.temp_drop_degrees = thresholds.get("temp_drop_degrees_per_2h", 3)

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
        except Exception:
            pass
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

        thresholds = cfg.get("thresholds", {})
        self.frost_temp = thresholds.get("frost_temp_c", 2)
        self.energy_anomaly_pct = thresholds.get("energy_anomaly_percent", 30)
        self.away_minutes = thresholds.get("away_device_minutes", 120)
        self.temp_drop_degrees = thresholds.get("temp_drop_degrees_per_2h", 3)

        # Loop starten wenn gerade aktiviert wurde
        if self.enabled and not was_enabled and not self._running:
            self._running = True
            self._task = asyncio.create_task(self._insight_loop())
            logger.info("InsightEngine via Hot-Reload gestartet")

    # ------------------------------------------------------------------
    # Hintergrund-Loop
    # ------------------------------------------------------------------

    async def _insight_loop(self):
        """Prueft periodisch auf Insights."""
        # Erster Check nach kurzem Delay (System stabilisieren lassen)
        await asyncio.sleep(120)

        while self._running:
            try:
                if self.enabled:
                    insights = await self._run_all_checks()
                    for insight in insights:
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

                # Offene Tueren
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

        now = datetime.now()
        end = now + timedelta(hours=24)
        all_events = []

        for cal_entity in calendar_entities[:3]:  # Max 3 Kalender
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

    async def _run_all_checks(self) -> list[dict]:
        """Fuehrt alle aktivierten Checks aus."""
        data = await self._gather_data()
        if not data["states"]:
            return []

        insights = []

        check_methods = [
            (self.check_weather_windows, self._check_weather_windows),
            (self.check_frost_heating, self._check_frost_heating),
            (self.check_calendar_travel, self._check_calendar_travel),
            (self.check_energy_anomaly, self._check_energy_anomaly),
            (self.check_away_devices, self._check_away_devices),
            (self.check_temp_drop, self._check_temp_drop),
            (self.check_window_temp, self._check_window_temp_drop),
            (True, self._check_calendar_weather_cross),
            (True, self._check_comfort_contradiction),
        ]

        for enabled, method in check_methods:
            if not enabled:
                continue
            try:
                result = await method(data)
                if result and not await self._is_on_cooldown(result["check"]):
                    insights.append(result)
                    await self._set_cooldown(result["check"])
            except Exception as e:
                logger.debug("Check %s fehlgeschlagen: %s", method.__name__, e)

        return insights

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
                        fc_local = fc_dt.astimezone().replace(tzinfo=None)
                        hours_until = (fc_local - datetime.now()).total_seconds() / 3600
                        if hours_until <= 0:
                            time_hint = "jetzt"
                        elif hours_until < 1:
                            time_hint = "in Kuerze"
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
                f"Frostschaeden waeren vermeidbar."
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
            hints.append("Heizung laeuft im Normalmodus")

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
        """Energie-Verbrauch deutlich ueber Baseline."""
        if not self.redis:
            return None

        try:
            # 7-Tage-Durchschnitt aus Redis
            values = []
            for i in range(1, 8):
                day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                raw = await self.redis.get(f"mha:energy:daily:{day}")
                if raw:
                    day_data = json.loads(raw)
                    val = day_data.get("consumption_wh", 0)
                    if val > 0:
                        values.append(val)

            if len(values) < 3:
                return None

            avg = sum(values) / len(values)
            if avg <= 0:
                return None

            # Heutigen Verbrauch ermitteln
            today_key = f"mha:energy:daily:{datetime.now().strftime('%Y-%m-%d')}"
            today_raw = await self.redis.get(today_key)
            if not today_raw:
                return None

            today_data = json.loads(today_raw)
            today_val = today_data.get("consumption_wh", 0)
            if today_val <= 0:
                return None

            # Hochrechnung auf Tagesende
            now = datetime.now()
            hours_passed = now.hour + now.minute / 60.0
            if hours_passed < 6:
                return None  # Zu frueh fuer sinnvolle Hochrechnung

            projected = today_val / hours_passed * 24
            increase_pct = ((projected - avg) / avg) * 100

            if increase_pct < self.energy_anomaly_pct:
                return None

            return {
                "check": "energy_anomaly",
                "urgency": "low",
                "message": (
                    f"{await self._get_title_for_home()}, der Stromverbrauch heute liegt {increase_pct:.0f}% ueber "
                    f"dem Durchschnitt. "
                    f"Laeuft etwas, das nicht laufen sollte?"
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
                await self.redis.setex(away_key, 86400, datetime.now().isoformat())
                return None  # Gerade erst gegangen
            try:
                since_dt = datetime.fromisoformat(away_since)
                minutes_away = (datetime.now() - since_dt).total_seconds() / 60
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
        """Temperatur in einem Raum faellt ungewoehnlich schnell."""
        if not self.redis or not data["temperatures"]:
            return None

        try:
            now = datetime.now()
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

            return {
                "check": "temp_drop",
                "urgency": "low",
                "message": (
                    f"{await self._get_title_for_home()}, die Raumtemperatur faellt ungewoehnlich — "
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
            check_methods = [
                (self.check_weather_windows, self._check_weather_windows),
                (self.check_frost_heating, self._check_frost_heating),
                (self.check_calendar_travel, self._check_calendar_travel),
                (self.check_energy_anomaly, self._check_energy_anomaly),
                (self.check_away_devices, self._check_away_devices),
                (self.check_temp_drop, self._check_temp_drop),
                (self.check_window_temp, self._check_window_temp_drop),
                (True, self._check_trend_prediction),  # Trend-Prediction immer aktiv
            ]

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
                    json.dumps({"ts": datetime.now().isoformat(), "temps": temps}),
                )
                await self.redis.ltrim("mha:insight:temp_history", 0, 5)
                await self.redis.expire("mha:insight:temp_history", 6 * 3600)
            except Exception:
                pass

    async def _check_trend_prediction(self, data: dict) -> Optional[dict]:
        """Einfache lineare Trend-Extrapolation fuer Raumtemperaturen."""
        if not self.redis:
            return None

        # Aktuellen Snapshot speichern
        await self._store_temp_snapshot(data)

        try:
            snapshots_raw = await self.redis.lrange("mha:insight:temp_history", 0, 5)
        except Exception:
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
            newest_ts = datetime.fromisoformat(snapshots[0]["ts"])
            oldest_ts = datetime.fromisoformat(snapshots[-1]["ts"])
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

        now = datetime.now()

        # Termine in den naechsten 18 Stunden suchen
        for event in data["calendar_events"]:
            start = event.get("start")
            if not start:
                continue
            try:
                if isinstance(start, str):
                    event_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    event_dt = event_dt.replace(tzinfo=None) if event_dt.tzinfo else event_dt
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
                    time_hint = "in Kuerze"
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

        MCU-JARVIS-Feature: Heizung laeuft + Fenster offen = Energieverschwendung.
        Licht an + niemand im Raum = unnoetig.
        """
        # Heizung laeuft + Fenster offen im gleichen Bereich
        if data.get("open_windows") and data.get("climate"):
            heating_rooms = []
            for c in data["climate"]:
                hvac = c.get("hvac_action", "")
                if hvac in ("heating", "cooling"):
                    name = c.get("name", "")
                    heating_rooms.append(name)

            if heating_rooms and data["open_windows"]:
                # Vereinfachter Match: Gibt es ein offenes Fenster
                # waehrend eine Heizung laeuft?
                title = await self._get_title_for_home()
                heating_str = heating_rooms[0]
                window_str = data["open_windows"][0]

                return {
                    "check": "comfort_contradiction",
                    "urgency": "low",
                    "message": (
                        f"{title}, die Heizung in {heating_str} laeuft, "
                        f"waehrend {window_str} offen steht. "
                        f"Energetisch... nicht ganz optimal."
                    ),
                    "data": {
                        "heating": heating_rooms,
                        "windows": data["open_windows"],
                    },
                }

        return None

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
                "calendar_weather_cross": True,
                "comfort_contradiction": True,
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
            except Exception:
                status["active_cooldowns"] = -1

        return status
