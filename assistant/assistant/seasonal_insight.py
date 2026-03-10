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
from datetime import datetime
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config, get_person_title

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

        cfg = yaml_config.get("seasonal_insights", {})
        self.enabled = cfg.get("enabled", True)
        self.check_interval = cfg.get("check_interval_hours", 24) * 3600
        self.min_history_months = cfg.get("min_history_months", 2)

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

        now = datetime.now()
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

        now = datetime.now()
        current_month = now.month
        current_season = _SEASONS.get(current_month, "unbekannt")
        title = get_person_title()

        # Cooldown: Max 1 Seasonal Insight pro Woche
        cooldown_key = f"{_PREFIX}:insight_cooldown"
        try:
            if await self.redis.exists(cooldown_key):
                return None
        except Exception:
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
        """Erkennt Saisonwechsel und gibt Tipps."""
        if not self.redis:
            return None

        # Wurde Saisonwechsel schon gemeldet?
        flag_key = f"{_PREFIX}:transition_notified:{current_season}"
        try:
            if await self.redis.exists(flag_key):
                return None
        except Exception:
            return None

        season_label = _SEASON_LABELS.get(current_season, current_season)

        # Typische Tipps pro Saison
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
                # Flag setzen: 180 Tage (damit naechste Saison wieder triggert)
                await self.redis.setex(flag_key, 180 * 86400, "1")
            except Exception as e:
                logger.debug("Redis seasonal flag set failed: %s", e)

        return tip

    async def _check_year_over_year(self, current_month: int, title: str) -> Optional[str]:
        """Vergleicht Aktionen mit Vorjahres-Monat."""
        if not self.redis:
            return None

        now = datetime.now()
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
