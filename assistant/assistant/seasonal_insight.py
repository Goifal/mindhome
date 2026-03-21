"""
SeasonalInsightEngine — Saisonale Muster-Erkennung.

Phase 18: MCU-Upgrade — Jarvis lernt ueber Jahreszeiten:
- Vergleicht aktuellen Monat mit Vorjahr
- Erkennt Saisonwechsel und schlaegt Anpassungen vor
- Erkennt Start/Ende der Heizsaison

Nur lesende Beobachtungen, keine Auto-Ausfuehrung.
Alle Daten in Redis mit TTL (max 2 Jahre).
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import redis.asyncio as aioredis

from .circuit_breaker import registry as cb_registry
from .config import yaml_config, get_person_title

_LOCAL_TZ = ZoneInfo(yaml_config.get("timezone", "Europe/Berlin"))

logger = logging.getLogger(__name__)

# Redis-Key-Prefix
_PREFIX = "mha:seasonal"

# Saisonale Zuordnung
_SEASONS = {
    12: "winter", 1: "winter", 2: "winter",
    3: "fruehling", 4: "fruehling", 5: "fruehling",
    6: "sommer", 7: "sommer", 8: "sommer",
    9: "herbst", 10: "herbst", 11: "herbst",
}

_SEASON_LABELS = {
    "winter": "Winter",
    "fruehling": "Fruehling",
    "sommer": "Sommer",
    "herbst": "Herbst",
}


class SeasonalInsightEngine:
    """Erkennt jahreszeitlich wiederkehrende Muster im User-Verhalten."""

    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._notify_callback = None
        self._ollama = None
        self._ha = None  # HomeAssistantClient fuer Haus-Status in LLM-Prompts

        cfg = yaml_config.get("seasonal_insights", {})
        self.enabled = cfg.get("enabled", True)
        self.check_interval = cfg.get("check_interval_hours", 24) * 3600
        self.min_history_months = cfg.get("min_history_months", 2)

        # Hybrid detection: combine month-based season with outdoor temp + daylight
        si_cfg = yaml_config.get("seasonal_insight", {})
        self._hybrid_detection = si_cfg.get("hybrid_detection", False)

    def set_ollama(self, ollama_client):
        """Setzt den OllamaClient fuer LLM-basierte Saisontipps."""
        self._ollama = ollama_client

    def set_ha(self, ha_client):
        """Setzt den HA-Client fuer Haus-Status-Kontext."""
        self._ha = ha_client

    async def get_current_season(self) -> tuple[str, float]:
        """Returns (season_name, confidence) using hybrid detection if enabled."""
        if self._hybrid_detection:
            return await self._detect_season_hybrid()
        now = datetime.now(_LOCAL_TZ)
        season = _SEASONS.get(now.month, "unbekannt")
        return season, 1.0

    async def _detect_season_hybrid(self) -> tuple[str, float]:
        """Hybrid season detection combining month, outdoor temp, and daylight hours.

        Returns:
            Tuple of (season_name, confidence 0.0-1.0).
            Falls back to month-based detection if HA data unavailable.
        """
        now = datetime.now(_LOCAL_TZ)
        month_season = _SEASONS.get(now.month, "unbekannt")
        confidence = 1.0

        if not self._ha:
            return month_season, confidence

        # Temperature-based season hints
        _TEMP_SEASON_HINTS = {
            "winter": (-10, 8),    # typical winter range
            "fruehling": (5, 18),
            "sommer": (18, 40),
            "herbst": (5, 16),
        }

        outdoor_temp: Optional[float] = None
        daylight_hours: Optional[float] = None

        try:
            states = await self._ha.get_states()
            if not states:
                return month_season, confidence

            for s in states:
                eid = s.get("entity_id", "")
                state_val = s.get("state", "")

                # Outdoor temperature sensor
                if (
                    "outdoor" in eid.lower()
                    or "aussen" in eid.lower()
                    or "outside" in eid.lower()
                ) and eid.startswith("sensor.") and "temperature" in eid.lower():
                    try:
                        outdoor_temp = float(state_val)
                    except (ValueError, TypeError):
                        pass

                # Sunrise/sunset for daylight calculation
                if eid == "sun.sun":
                    attrs = s.get("attributes", {})
                    sunrise = attrs.get("next_rising", "")
                    sunset = attrs.get("next_setting", "")
                    if sunrise and sunset:
                        try:
                            rise_dt = datetime.fromisoformat(sunrise.replace("Z", "+00:00"))
                            set_dt = datetime.fromisoformat(sunset.replace("Z", "+00:00"))
                            # Approximate daylight hours
                            diff = (set_dt - rise_dt).total_seconds() / 3600
                            if 0 < diff < 24:
                                daylight_hours = diff
                        except (ValueError, TypeError):
                            pass

        except Exception as e:
            logger.debug("Hybrid season HA-Abfrage fehlgeschlagen: %s", e)
            return month_season, confidence

        # Evaluate: does outdoor temp agree with month-based season?
        if outdoor_temp is not None:
            expected_range = _TEMP_SEASON_HINTS.get(month_season)
            if expected_range:
                low, high = expected_range
                if low <= outdoor_temp <= high:
                    # Temperature confirms month-based season
                    confidence = min(1.0, confidence + 0.05)
                else:
                    # Temperature disagrees — check which season fits better
                    confidence = max(0.5, confidence - 0.2)
                    for season, (s_low, s_high) in _TEMP_SEASON_HINTS.items():
                        if s_low <= outdoor_temp <= s_high and season != month_season:
                            # Temperature suggests different season (transitional period)
                            logger.debug(
                                "Hybrid detection: month=%s, temp=%.1f°C suggests %s",
                                month_season, outdoor_temp, season,
                            )
                            # Don't override, just reduce confidence
                            break

        # Daylight hours as additional signal
        # Winter: <10h, Spring: 10-14h, Summer: >14h, Autumn: 10-14h
        if daylight_hours is not None:
            _DAYLIGHT_SEASONS = {
                "winter": (0, 10),
                "fruehling": (10, 14),
                "sommer": (14, 24),
                "herbst": (10, 14),
            }
            expected_daylight = _DAYLIGHT_SEASONS.get(month_season)
            if expected_daylight:
                d_low, d_high = expected_daylight
                if d_low <= daylight_hours <= d_high:
                    confidence = min(1.0, confidence + 0.05)
                else:
                    confidence = max(0.4, confidence - 0.15)

        return month_season, round(confidence, 2)

    async def initialize(
        self,
        redis_client: Optional[aioredis.Redis] = None,
        notify_callback=None,
    ):
        """Initialisiert die Engine."""
        self.redis = redis_client
        self._notify_callback = notify_callback

        if self.enabled and self.redis:
            self._running = True
            self._task = asyncio.create_task(self._seasonal_loop())
            self._task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
            logger.info("SeasonalInsightEngine initialisiert")

    async def stop(self):
        """Stoppt die Engine."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def log_seasonal_action(self, action: str, args: dict, person: str = "") -> None:
        """Loggt eine Aktion fuer saisonale Analyse.

        Wird bei jeder ausgefuehrten Aktion aufgerufen.
        Aggregiert pro Monat fuer kompakte Speicherung.
        """
        if not self.redis or not self.enabled:
            return

        now = datetime.now(_LOCAL_TZ)
        month_key = now.strftime("%Y-%m")
        redis_key = f"{_PREFIX}:monthly:{month_key}"

        try:
            # Inkrementiere Action-Counter fuer diesen Monat
            await self.redis.hincrby(redis_key, action, 1)
            # TTL: 2 Jahre (730 Tage)
            await self.redis.expire(redis_key, 730 * 86400)
        except Exception as e:
            logger.debug("Seasonal Log fehlgeschlagen: %s", e)

    async def _seasonal_loop(self):
        """Hintergrund-Loop fuer saisonale Checks."""
        # Startup-Delay: 30 Minuten (nicht kritisch, warten bis System stabil)
        await asyncio.sleep(1800)

        while self._running:
            try:
                insight = await self._check_seasonal_patterns()
                if insight and self._notify_callback:
                    await self._notify_callback(
                        insight,
                        urgency="low",
                        event_type="seasonal_insight",
                    )
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.debug("Seasonal-Loop Fehler: %s", e)

            await asyncio.sleep(self.check_interval)

    async def _check_seasonal_patterns(self) -> Optional[str]:
        """Prueft auf saisonale Muster und gibt Insight zurueck."""
        if not self.redis:
            return None

        now = datetime.now(_LOCAL_TZ)
        current_month = now.month
        current_season = _SEASONS.get(current_month, "unbekannt")
        title = get_person_title()

        # Cooldown: Max 1 Seasonal Insight pro Woche
        cooldown_key = f"{_PREFIX}:insight_cooldown"
        try:
            if await self.redis.exists(cooldown_key):
                return None
        except Exception as e:
            logger.debug("Seasonal-Insight Cooldown-Pruefung fehlgeschlagen: %s", e)
            return None

        # Saisonwechsel erkennen
        transition_insight = await self._check_seasonal_transition(current_season, title)
        if transition_insight:
            try:
                await self.redis.setex(cooldown_key, 7 * 86400, "1")
            except Exception as e:
                logger.debug("Redis cooldown set failed: %s", e)
            return transition_insight

        # Vorjahres-Vergleich
        yoy_insight = await self._check_year_over_year(current_month, title)
        if yoy_insight:
            try:
                await self.redis.setex(cooldown_key, 7 * 86400, "1")
            except Exception as e:
                logger.debug("Redis cooldown set failed: %s", e)
            return yoy_insight

        return None

    async def _check_seasonal_transition(self, current_season: str, title: str) -> Optional[str]:
        """Erkennt Saisonwechsel und gibt kontextsensitive Tipps.

        Nutzt optional LLM + HA-Status fuer situationsbezogene Vorschlaege.
        Fallback auf statische Templates wenn LLM nicht verfuegbar.
        """
        if not self.redis:
            return None

        # Wurde Saisonwechsel schon gemeldet?
        flag_key = f"{_PREFIX}:transition_notified:{current_season}"
        try:
            if await self.redis.exists(flag_key):
                return None
        except Exception as e:
            logger.debug("Saisonwechsel-Flag Pruefung fehlgeschlagen: %s", e)
            return None

        season_label = _SEASON_LABELS.get(current_season, current_season)

        # LLM-basierter kontextsensitiver Tipp (mit HA-Status)
        llm_tip = await self._llm_seasonal_tip(current_season, season_label, title)
        if llm_tip:
            try:
                await self.redis.setex(flag_key, 180 * 86400, "1")
            except Exception as e:
                logger.debug("Redis seasonal flag set failed: %s", e)
            return llm_tip

        # Fallback: Statische Tipps
        tips = {
            "fruehling": (
                f"{title}, der {season_label} naht. "
                f"Soll ich die Heizprogramme anpassen und die Rolladen-Zeiten auf die laengeren Tage umstellen?"
            ),
            "sommer": (
                f"{title}, es wird {season_label}. "
                f"Soll ich die Nacht-Kühlung aktivieren und die Rollladen-Automatik auf Sonnenschutz umstellen?"
            ),
            "herbst": (
                f"{title}, der {season_label} kommt. "
                f"Soll ich die Heizprogramme fuer die kuehlen Abende vorbereiten?"
            ),
            "winter": (
                f"{title}, {season_label} steht vor der Tuer. "
                f"Soll ich die Heizung auf Winter-Modus umstellen und die Frost-Ueberwachung aktivieren?"
            ),
        }

        tip = tips.get(current_season)
        if tip:
            try:
                await self.redis.setex(flag_key, 180 * 86400, "1")
            except Exception as e:
                logger.debug("Redis seasonal flag set failed: %s", e)

        return tip

    async def _llm_seasonal_tip(self, season: str, season_label: str, title: str) -> Optional[str]:
        """Generiert einen kontextsensitiven Saisontipp via LLM.

        Berücksichtigt den aktuellen Haus-Status (Heizung, Rolladen, etc.)
        fuer relevantere Vorschlaege.
        """
        cfg = yaml_config.get("seasonal_insights", {})
        if not cfg.get("llm_tips", True) or not self._ollama:
            return None

        # Haus-Kontext sammeln (optional, verbessert Relevanz)
        house_context = ""
        if self._ha:
            try:
                states = await self._ha.get_states()
                if states:
                    # Relevante Haus-Infos fuer Saisonwechsel
                    climate_states = []
                    cover_states = []
                    for s in states:
                        eid = s.get("entity_id", "")
                        if eid.startswith("climate."):
                            mode = s.get("state", "off")
                            temp = s.get("attributes", {}).get("temperature", "")
                            name = s.get("attributes", {}).get("friendly_name", eid)
                            climate_states.append(f"{name}: {mode}" + (f" ({temp}°C)" if temp else ""))
                        elif eid.startswith("cover."):
                            pos = s.get("attributes", {}).get("current_position", "")
                            name = s.get("attributes", {}).get("friendly_name", eid)
                            if pos:
                                cover_states.append(f"{name}: {pos}%")
                    if climate_states:
                        house_context += f"Heizung/Klima: {', '.join(climate_states[:5])}\n"
                    if cover_states:
                        house_context += f"Rolladen: {', '.join(cover_states[:5])}\n"
            except Exception as e:
                logger.debug("HA-Status fuer saisonalen Kontext fehlgeschlagen: %s", e)

        # Circuit Breaker Pruefung vor LLM-Aufruf
        cb = cb_registry.get("seasonal_insight")
        if cb and not cb.is_available:
            logger.debug("SeasonalInsight: Circuit Breaker OPEN — LLM-Aufruf uebersprungen")
            return None

        try:
            from .config import settings
            response = await asyncio.wait_for(
                self._ollama.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Du bist J.A.R.V.I.S., ein trocken-britischer Smart-Home-Butler. "
                                "Generiere einen Saisonwechsel-Hinweis mit konkreten Vorschlaegen "
                                "basierend auf dem aktuellen Haus-Status. 2-3 Saetze, Butler-Ton. "
                                "Frage am Ende ob du die Anpassungen vornehmen sollst."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"Saisonwechsel: Es wird {season_label}.\n"
                                f"Anrede: {title}\n"
                                f"{house_context or 'Kein Haus-Status verfuegbar.'}"
                            ),
                        },
                    ],
                    model=settings.model_smart,
                    temperature=0.5,
                    max_tokens=500,
                    think=False,
                    tier="smart",
                ),
                timeout=5.0,
            )
            content = (response.get("message", {}).get("content", "") or "").strip()
            if "<think>" in content:
                think_end = content.find("</think>")
                if think_end != -1:
                    content = content[think_end + 8:].strip()

            if content and len(content) > 20:
                if cb:
                    cb.record_success()
                return content

        except asyncio.TimeoutError:
            if cb:
                cb.record_failure()
        except Exception as e:
            logger.debug("Seasonal LLM-Tipp Fehler: %s", e)
            if cb:
                cb.record_failure()

        return None

    async def _check_year_over_year(self, current_month: int, title: str) -> Optional[str]:
        """Vergleicht Aktionen mit Vorjahres-Monat."""
        if not self.redis:
            return None

        now = datetime.now(_LOCAL_TZ)
        current_key = f"{_PREFIX}:monthly:{now.strftime('%Y-%m')}"
        last_year_key = f"{_PREFIX}:monthly:{now.year - 1}-{now.month:02d}"

        try:
            raw_current = await self.redis.hgetall(current_key)
            raw_last = await self.redis.hgetall(last_year_key)

            if not raw_last:
                return None  # Keine Vorjahres-Daten

            current_data = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in raw_current.items()} if raw_current else {}
            last_year_data = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in raw_last.items()}

            # Vergleiche Heizungs-Aktionen
            heat_current = int(current_data.get("set_climate", 0))
            heat_last = int(last_year_data.get("set_climate", 0))

            if heat_last > 10 and heat_current < heat_last * 0.3:
                return (
                    f"Nebenbei bemerkt, {title} — letztes Jahr um diese Zeit "
                    f"hast du die Heizung deutlich haeufiger angepasst. "
                    f"Soll ich die Einstellungen ueberpruefen?"
                )

            if heat_current > heat_last * 2 and heat_last > 5:
                return (
                    f"{title}, die Heizungsanpassungen sind diesen Monat doppelt so haeufig "
                    f"wie letztes Jahr. Stimmt etwas mit der Grundeinstellung nicht?"
                )

        except Exception as e:
            logger.debug("YoY-Vergleich fehlgeschlagen: %s", e)

        return None

    async def get_status(self) -> dict:
        """Gibt den Status der Engine zurueck."""
        status = {
            "enabled": self.enabled,
            "running": self._running,
            "check_interval_hours": self.check_interval // 3600,
            "hybrid_detection": self._hybrid_detection,
        }

        if self.redis:
            try:
                # Wie viele Monate haben wir Daten?
                cursor = 0
                months_with_data = 0
                while True:
                    cursor, keys = await self.redis.scan(
                        cursor, match=f"{_PREFIX}:monthly:*", count=50,
                    )
                    months_with_data += len(keys)
                    if cursor == 0:
                        break
                status["months_with_data"] = months_with_data
            except Exception as e:
                logger.warning("Seasonal data scan failed: %s", e)
                status["months_with_data"] = -1

        return status
