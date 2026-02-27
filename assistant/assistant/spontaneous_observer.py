"""
SpontaneousObserver — Jarvis macht 1-2x taeglich unaufgeforderte, interessante Bemerkungen.

Feature 4: Spontane Beobachtungen — nicht reaktiv, sondern proaktiv-interessant.
Entdeckt Trends, Rekorde, Streaks und Fun Facts aus den Haus-Daten.

Architektur:
  1. Hintergrund-Loop mit zufaelligem Intervall (2-4 Stunden)
  2. Prueft verschiedene Observation-Checks (Energy, Streaks, Records, etc.)
  3. Delivery via Callback → brain._handle_spontaneous → Silence Matrix → TTS
  4. Max N pro Tag, nur waehrend aktiver Stunden
"""

import asyncio
import json
import logging
import random
from datetime import datetime
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config, get_person_title
from .ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)

_PREFIX = "mha:spontaneous"


class SpontaneousObserver:
    """Macht unaufgeforderte, interessante Beobachtungen."""

    def __init__(self, ha_client: HomeAssistantClient, activity_engine=None):
        self.ha = ha_client
        self.activity = activity_engine
        self.redis: Optional[aioredis.Redis] = None
        self._notify_callback = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

        cfg = yaml_config.get("spontaneous", {})
        self.enabled = cfg.get("enabled", True)
        self.max_per_day = cfg.get("max_per_day", 2)
        self.min_interval_hours = cfg.get("min_interval_hours", 3)
        self.active_hours = cfg.get("active_hours", {"start": 8, "end": 22})

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis und startet den Beobachtungs-Loop."""
        self.redis = redis_client
        if self._task and not self._task.done():
            self._task.cancel()
        if self.enabled and self.redis:
            self._running = True
            self._task = asyncio.create_task(self._observe_loop())
        logger.info("SpontaneousObserver initialisiert (enabled: %s)", self.enabled)

    def set_notify_callback(self, callback):
        """Setzt den Callback fuer Beobachtungen."""
        self._notify_callback = callback

    async def _get_title_for_present(self) -> str:
        """Gibt die korrekte Anrede fuer die anwesenden Personen zurueck."""
        try:
            states = await self.ha.get_states()
            if states:
                persons = []
                for s in states:
                    if s.get("entity_id", "").startswith("person.") and s.get("state") == "home":
                        pname = s.get("attributes", {}).get("friendly_name", "")
                        if pname:
                            persons.append(pname)
                if len(persons) == 1:
                    return get_person_title(persons[0])
                elif len(persons) > 1:
                    titles = []
                    for p in persons:
                        t = get_person_title(p)
                        if t not in titles:
                            titles.append(t)
                    return ", ".join(titles)
        except Exception:
            pass
        return get_person_title()

    async def stop(self):
        """Stoppt den Beobachtungs-Loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _observe_loop(self):
        """Hintergrund-Loop mit zufaelligem Intervall."""
        # Initiales Warten (30-60 Min nach Start)
        await asyncio.sleep(random.randint(1800, 3600))

        while self._running:
            try:
                if not self._within_active_hours():
                    await asyncio.sleep(1800)  # 30 Min warten
                    continue

                if await self._daily_count() >= self.max_per_day:
                    await asyncio.sleep(3600)  # 1 Stunde warten
                    continue

                observation = await self._find_interesting_observation()
                if observation and self._notify_callback:
                    await self._notify_callback(observation)
                    await self._increment_daily_count()
                    logger.info(
                        "Spontane Beobachtung geliefert: %s",
                        observation.get("type", "?"),
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("SpontaneousObserver Loop Fehler: %s", e)

            # Zufaellige Wartezeit: min_interval_hours bis 2x min_interval_hours
            wait_min = self.min_interval_hours * 3600
            wait_max = self.min_interval_hours * 2 * 3600
            await asyncio.sleep(random.uniform(wait_min, wait_max))

    def _within_active_hours(self) -> bool:
        """Prueft ob aktuell innerhalb der aktiven Stunden."""
        hour = datetime.now().hour
        start = self.active_hours.get("start", 8)
        end = self.active_hours.get("end", 22)
        return start <= hour < end

    async def _daily_count(self) -> int:
        """Gibt die Anzahl der heutigen Beobachtungen zurueck."""
        if not self.redis:
            return 999
        key = f"{_PREFIX}:daily_count:{datetime.now().strftime('%Y-%m-%d')}"
        count = await self.redis.get(key)
        return int(count) if count else 0

    async def _increment_daily_count(self):
        """Erhoeht den Tages-Zaehler."""
        if not self.redis:
            return
        key = f"{_PREFIX}:daily_count:{datetime.now().strftime('%Y-%m-%d')}"
        await self.redis.incr(key)
        await self.redis.expire(key, 48 * 3600)

    async def _on_cooldown(self, obs_type: str) -> bool:
        """Prueft ob ein Observation-Typ auf Cooldown ist."""
        if not self.redis:
            return True
        key = f"{_PREFIX}:cooldown:{obs_type}"
        return bool(await self.redis.get(key))

    async def _set_cooldown(self, obs_type: str, seconds: int):
        """Setzt einen Cooldown fuer einen Observation-Typ."""
        if not self.redis:
            return
        key = f"{_PREFIX}:cooldown:{obs_type}"
        await self.redis.setex(key, seconds, "1")

    async def _find_interesting_observation(self) -> Optional[dict]:
        """Sucht nach einer interessanten Beobachtung."""
        cfg = yaml_config.get("spontaneous", {})
        checks_cfg = cfg.get("checks", {})

        checks = []
        if checks_cfg.get("energy_comparison", True):
            checks.append(self._check_energy_comparison)
        if checks_cfg.get("streak", True):
            checks.append(self._check_weather_streak)
        if checks_cfg.get("usage_record", True):
            checks.append(self._check_usage_record)
        if checks_cfg.get("device_milestone", True):
            checks.append(self._check_device_milestone)
        if checks_cfg.get("house_efficiency", True):
            checks.append(self._check_house_efficiency)

        random.shuffle(checks)

        for check in checks:
            try:
                result = await check()
                if result and not await self._on_cooldown(result["type"]):
                    await self._set_cooldown(result["type"], 24 * 3600)
                    return result
            except Exception as e:
                logger.debug("Spontaneous Check Fehler: %s", e)
                continue

        return None

    # ------------------------------------------------------------------
    # Observation Checks
    # ------------------------------------------------------------------

    async def _check_energy_comparison(self) -> Optional[dict]:
        """Vergleicht Energie-Verbrauch mit Vorwoche."""
        if not self.redis:
            return None

        try:
            # Heutige und letzte Wochen-Daten aus Redis
            today_key = f"mha:energy:daily:{datetime.now().strftime('%Y-%m-%d')}"
            today_val = await self.redis.get(today_key)
            if not today_val:
                return None

            # 7 Tage zurueck
            from datetime import timedelta
            week_ago = datetime.now() - timedelta(days=7)
            week_key = f"mha:energy:daily:{week_ago.strftime('%Y-%m-%d')}"
            week_val = await self.redis.get(week_key)
            if not week_val:
                return None

            today_data = json.loads(today_val) if today_val.strip().startswith("{") else {"consumption_wh": float(today_val)}
            today_kwh = float(today_data.get("consumption_wh", 0))
            week_data = json.loads(week_val) if week_val.strip().startswith("{") else {"consumption_wh": float(week_val)}
            week_kwh = float(week_data.get("consumption_wh", 0))

            if week_kwh <= 0:
                return None

            diff_pct = ((today_kwh - week_kwh) / week_kwh) * 100

            if abs(diff_pct) >= 15:
                title = await self._get_title_for_present()
                if diff_pct > 0:
                    message = (
                        f"{title}, der Energieverbrauch liegt heute {diff_pct:.0f}% "
                        f"ueber dem gleichen Tag letzte Woche."
                    )
                else:
                    message = (
                        f"{title}, heute verbrauchen wir {abs(diff_pct):.0f}% weniger "
                        f"Energie als letzte Woche um diese Zeit. Gut so."
                    )
                return {
                    "message": message,
                    "type": "energy_comparison",
                    "urgency": "low",
                }
        except (ValueError, TypeError):
            pass
        return None

    async def _check_weather_streak(self) -> Optional[dict]:
        """Prueft auf Wetter-Streaks (z.B. X Tage Sonne in Folge)."""
        try:
            states = await self.ha.get_states()
            if not states:
                return None

            for state in states:
                if state.get("entity_id", "").startswith("weather."):
                    condition = state.get("state", "")
                    temp = state.get("attributes", {}).get("temperature")

                    if condition == "sunny" and temp:
                        try:
                            temp_f = float(temp)
                            if temp_f >= 25:
                                title = await self._get_title_for_present()
                                return {
                                    "message": (
                                        f"{title}, es hat draussen {temp_f:.0f} Grad "
                                        f"bei strahlendem Sonnenschein. "
                                        f"Vielleicht ein guter Moment fuer frische Luft."
                                    ),
                                    "type": "weather_streak",
                                    "urgency": "low",
                                }
                        except (ValueError, TypeError):
                            pass

                    if condition in ("snowy", "snowy-rainy"):
                        title = await self._get_title_for_present()
                        return {
                            "message": (
                                f"{title}, es schneit draussen. "
                                f"Falls die Rolllaeden noch oben sind, waere das "
                                f"zumindest ein schoener Anblick."
                            ),
                            "type": "weather_streak",
                            "urgency": "low",
                        }
                    break
        except Exception:
            pass
        return None

    async def _check_usage_record(self) -> Optional[dict]:
        """Prueft ob ein Nutzungs-Rekord erreicht wurde."""
        if not self.redis:
            return None

        try:
            # Anzahl manueller Aktionen heute
            from .learning_observer import KEY_MANUAL_ACTIONS
            actions_raw = await self.redis.lrange(KEY_MANUAL_ACTIONS, 0, 499)
            if not actions_raw:
                return None

            today = datetime.now().strftime("%Y-%m-%d")
            today_count = 0
            for raw in actions_raw:
                try:
                    entry = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                    if entry.get("timestamp", "").startswith(today):
                        today_count += 1
                except (json.JSONDecodeError, AttributeError):
                    continue

            # Record pruefen
            record_key = f"{_PREFIX}:record:daily_actions"
            prev_record = await self.redis.get(record_key)
            prev_record = int(prev_record) if prev_record else 0

            if today_count > prev_record and today_count >= 10:
                await self.redis.setex(record_key, 90 * 86400, str(today_count))
                title = await self._get_title_for_present()
                return {
                    "message": (
                        f"{title}, heute wurden bereits {today_count} Geraete "
                        f"manuell geschaltet — neuer Rekord. Offenbar ein aktiver Tag."
                    ),
                    "type": "usage_record",
                    "urgency": "low",
                }
        except Exception:
            pass
        return None

    async def _check_device_milestone(self) -> Optional[dict]:
        """Prueft auf Geraete-Meilensteine (z.B. Waschmaschine X-mal diese Woche)."""
        if not self.redis:
            return None

        try:
            from .learning_observer import KEY_MANUAL_ACTIONS
            actions_raw = await self.redis.lrange(KEY_MANUAL_ACTIONS, 0, 499)
            if not actions_raw:
                return None

            # Zaehle Aktionen pro Entity diese Woche
            from datetime import timedelta
            week_start = datetime.now() - timedelta(days=7)
            week_start_str = week_start.isoformat()

            entity_counts: dict[str, int] = {}
            for raw in actions_raw:
                try:
                    entry = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                    ts = entry.get("timestamp", "")
                    if ts >= week_start_str:
                        eid = entry.get("entity_id", "")
                        if eid:
                            entity_counts[eid] = entity_counts.get(eid, 0) + 1
                except (json.JSONDecodeError, AttributeError):
                    continue

            if not entity_counts:
                return None

            # Hoechste Nutzung finden
            top_entity = max(entity_counts, key=entity_counts.get)
            top_count = entity_counts[top_entity]

            if top_count >= 7:
                friendly = top_entity.split(".", 1)[-1].replace("_", " ").title()
                title = await self._get_title_for_present()
                return {
                    "message": (
                        f"{title}, {friendly} wurde diese Woche bereits "
                        f"{top_count} Mal betaetigt. Das meistgenutzte Geraet."
                    ),
                    "type": "device_milestone",
                    "urgency": "low",
                }
        except Exception:
            pass
        return None

    async def _check_house_efficiency(self) -> Optional[dict]:
        """Analysiert die Haus-Effizienz und macht eine smarte Beobachtung.

        MCU-JARVIS-Feature: 'Sir, mir ist aufgefallen, dass das Haus heute
        besonders effizient laeuft — 18% weniger Heiz-Zyklen als ueblich.'
        """
        try:
            states = await self.ha.get_states()
            if not states:
                return None

            # Zaehle aktive Geraete vs. anwesende Personen
            lights_on = 0
            heating_active = 0
            persons_home = 0

            for s in states:
                eid = s.get("entity_id", "")
                state = s.get("state", "")

                if eid.startswith("light.") and state == "on":
                    lights_on += 1
                elif eid.startswith("climate."):
                    hvac = s.get("attributes", {}).get("hvac_action", "")
                    if hvac in ("heating", "cooling"):
                        heating_active += 1
                elif eid.startswith("person.") and state == "home":
                    persons_home += 1

            title = await self._get_title_for_present()

            # Niemand da aber alles laeuft
            if persons_home == 0 and (lights_on > 2 or heating_active > 2):
                return {
                    "message": (
                        f"{title}, das Haus verbraucht gerade Ressourcen "
                        f"({lights_on} Lichter, {heating_active} Heizungen) "
                        f"fuer eine leere Wohnung. Nur so als Beobachtung."
                    ),
                    "type": "house_efficiency",
                    "urgency": "low",
                }

            # Alles optimiert (positives Feedback)
            if persons_home > 0 and lights_on <= 1 and heating_active <= 1:
                hour = datetime.now().hour
                if 10 <= hour <= 20:
                    return {
                        "message": (
                            f"{title}, das Haus laeuft heute bemerkenswert effizient. "
                            f"Nur {lights_on} Licht und {heating_active} Heizung{'en' if heating_active != 1 else ''} aktiv. "
                            f"Vorbildlich."
                        ),
                        "type": "house_efficiency",
                        "urgency": "low",
                    }

        except Exception:
            pass
        return None
