"""
Health Monitor - Raumklima & Gesundheits-Ueberwachung.

Phase 15.1: Ueberwacht CO2, Luftfeuchtigkeit, Temperatur via HA-Sensoren.
Gibt proaktive Warnungen bei ungesunden Werten.
Erinnerung an Trinkwasser (Hydration-Reminder).
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

import redis.asyncio as redis

from .config import yaml_config

logger = logging.getLogger(__name__)

# Schwellwerte (Defaults, ueberschreibbar via settings.yaml)
DEFAULTS = {
    "check_interval_minutes": 10,
    "co2_warn": 1000,
    "co2_critical": 1500,
    "humidity_low": 30,
    "humidity_high": 70,
    "temp_low": 16,
    "temp_high": 27,
    "hydration_interval_hours": 2,
    "hydration_start_hour": 8,
    "hydration_end_hour": 22,
}


class HealthMonitor:
    """Ueberwacht Raumklima-Sensoren und gibt Gesundheits-Warnungen."""

    def __init__(self, ha_client):
        self.ha = ha_client
        self.redis: Optional[redis.Redis] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._notify_callback = None

        # Config laden
        cfg = yaml_config.get("health_monitor", {})
        self.enabled = cfg.get("enabled", True)
        self.check_interval = cfg.get("check_interval_minutes", DEFAULTS["check_interval_minutes"])
        self.co2_warn = cfg.get("co2_warn", DEFAULTS["co2_warn"])
        self.co2_critical = cfg.get("co2_critical", DEFAULTS["co2_critical"])
        self.humidity_low = cfg.get("humidity_low", DEFAULTS["humidity_low"])
        self.humidity_high = cfg.get("humidity_high", DEFAULTS["humidity_high"])
        self.temp_low = cfg.get("temp_low", DEFAULTS["temp_low"])
        self.temp_high = cfg.get("temp_high", DEFAULTS["temp_high"])
        self.hydration_interval = cfg.get("hydration_interval_hours", DEFAULTS["hydration_interval_hours"])
        self.hydration_start = cfg.get("hydration_start_hour", DEFAULTS["hydration_start_hour"])
        self.hydration_end = cfg.get("hydration_end_hour", DEFAULTS["hydration_end_hour"])

        # Cooldowns (entity_id -> letzte Warnung)
        self._alert_cooldowns: dict[str, datetime] = {}
        self._alert_cooldown_minutes = cfg.get("alert_cooldown_minutes", 60)

        # Exclude-Patterns: Entities deren ID einen dieser Substrings enthaelt werden ignoriert
        self._exclude_patterns = [p.lower() for p in cfg.get("exclude_patterns", [])]

    async def initialize(self, redis_client: Optional[redis.Redis] = None):
        """Initialisiert mit Redis-Verbindung."""
        self.redis = redis_client
        logger.info("Health Monitor initialisiert (Intervall: %d Min.)", self.check_interval)

    def set_notify_callback(self, callback):
        """Setzt die Callback-Funktion fuer Warnungen."""
        self._notify_callback = callback

    async def start(self):
        """Startet den periodischen Check-Loop."""
        if not self.enabled:
            logger.info("Health Monitor deaktiviert")
            return
        self._running = True
        self._task = asyncio.create_task(self._check_loop())
        logger.info("Health Monitor gestartet")

    async def stop(self):
        """Stoppt den Check-Loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _check_loop(self):
        """Periodischer Gesundheits-Check."""
        await asyncio.sleep(180)  # 3 Min. warten bis HA bereit

        while self._running:
            try:
                alerts = await self.check_all()
                for alert in alerts:
                    await self._send_alert(alert)

                # Hydration-Reminder
                hydration = await self._check_hydration()
                if hydration:
                    await self._send_alert(hydration)

                # Phase 15.1: Stuendlichen Snapshot fuer Trend-Dashboard speichern
                await self._save_trend_snapshot()

            except Exception as e:
                logger.error("Health Monitor Check Fehler: %s", e)

            await asyncio.sleep(self.check_interval * 60)

    async def _save_trend_snapshot(self):
        """Phase 15.1: Speichert stuendlichen Snapshot der Sensorwerte in Redis."""
        if not self.redis:
            return

        try:
            import json
            status = await self.get_status()
            if not status.get("sensors"):
                return

            # Durchschnittswerte pro Typ
            type_values = {}
            for sensor in status["sensors"]:
                s_type = sensor.get("type", "")
                value = sensor.get("value", 0)
                if s_type:
                    type_values.setdefault(s_type, []).append(value)

            snapshot = {}
            for s_type, values in type_values.items():
                if values:
                    snapshot[s_type] = round(sum(values) / len(values), 1)
            snapshot["score"] = status.get("score", 0)

            # In Redis mit Stunden-Key speichern
            now = datetime.now()
            key = f"mha:health:snapshot:{now.strftime('%Y-%m-%d:%H')}"
            await self.redis.set(key, json.dumps(snapshot))
            await self.redis.expire(key, 168 * 3600)  # 7 Tage

        except Exception as e:
            logger.debug("Health-Snapshot Fehler: %s", e)

    async def check_all(self) -> list[dict]:
        """Prueft alle relevanten Sensoren und gibt Warnungen zurueck."""
        states = await self.ha.get_states()
        if not states:
            return []

        alerts = []

        for state in states:
            entity_id = state.get("entity_id", "")
            if not entity_id.startswith("sensor."):
                continue

            attrs = state.get("attributes", {})
            friendly_name = attrs.get("friendly_name", entity_id)

            # Exclude-Filter: entity_id UND friendly_name pruefen
            check_str = f"{entity_id} {friendly_name}".lower()
            if any(pat in check_str for pat in self._exclude_patterns):
                continue

            value_str = state.get("state", "")
            device_class = attrs.get("device_class", "")

            try:
                value = float(value_str)
            except (ValueError, TypeError):
                continue

            # CO2-Check
            if device_class == "carbon_dioxide" or "co2" in entity_id.lower():
                alert = self._check_co2(entity_id, friendly_name, value)
                if alert:
                    alerts.append(alert)

            # Feuchtigkeits-Check
            elif device_class == "humidity" or "humid" in entity_id.lower() or "feuchte" in entity_id.lower():
                alert = self._check_humidity(entity_id, friendly_name, value)
                if alert:
                    alerts.append(alert)

            # Temperatur-Check (nur Indoor-Sensoren)
            elif device_class == "temperature":
                alert = self._check_temperature(entity_id, friendly_name, value)
                if alert:
                    alerts.append(alert)

        return alerts

    def _check_co2(self, entity_id: str, name: str, ppm: float) -> Optional[dict]:
        """Prueft CO2-Wert."""
        if ppm >= self.co2_critical:
            return self._make_alert(
                entity_id, "co2_critical", "high",
                f"{name}: CO2 bei {int(ppm)} ppm — sofort lueften!",
                {"sensor": name, "value": ppm, "unit": "ppm"},
            )
        elif ppm >= self.co2_warn:
            return self._make_alert(
                entity_id, "co2_warn", "medium",
                f"{name}: CO2 bei {int(ppm)} ppm — Lueften empfohlen.",
                {"sensor": name, "value": ppm, "unit": "ppm"},
            )
        return None

    def _check_humidity(self, entity_id: str, name: str, percent: float) -> Optional[dict]:
        """Prueft Luftfeuchtigkeit."""
        if percent < self.humidity_low:
            return self._make_alert(
                entity_id, "humidity_low", "medium",
                f"{name}: Luft zu trocken ({int(percent)}%). Befeuchter einschalten?",
                {"sensor": name, "value": percent, "unit": "%"},
            )
        elif percent > self.humidity_high:
            return self._make_alert(
                entity_id, "humidity_high", "medium",
                f"{name}: Luft zu feucht ({int(percent)}%). Lueften empfohlen.",
                {"sensor": name, "value": percent, "unit": "%"},
            )
        return None

    def _check_temperature(self, entity_id: str, name: str, temp: float) -> Optional[dict]:
        """Prueft Raumtemperatur."""
        if temp < self.temp_low:
            return self._make_alert(
                entity_id, "temp_low", "low",
                f"{name}: Nur {temp:.1f}°C — etwas kuhl.",
                {"sensor": name, "value": temp, "unit": "°C"},
            )
        elif temp > self.temp_high:
            return self._make_alert(
                entity_id, "temp_high", "low",
                f"{name}: {temp:.1f}°C — ziemlich warm.",
                {"sensor": name, "value": temp, "unit": "°C"},
            )
        return None

    def _make_alert(self, entity_id: str, alert_type: str, urgency: str,
                    message: str, data: dict) -> Optional[dict]:
        """Erstellt einen Alert wenn Cooldown abgelaufen."""
        cooldown_key = f"{entity_id}:{alert_type}"
        last = self._alert_cooldowns.get(cooldown_key)
        if last and datetime.now() - last < timedelta(minutes=self._alert_cooldown_minutes):
            return None

        self._alert_cooldowns[cooldown_key] = datetime.now()
        return {
            "entity_id": entity_id,
            "alert_type": alert_type,
            "urgency": urgency,
            "message": message,
            "data": data,
        }

    async def _check_hydration(self) -> Optional[dict]:
        """Prueft ob ein Trink-Reminder faellig ist."""
        now = datetime.now()
        hour = now.hour

        if hour < self.hydration_start or hour >= self.hydration_end:
            return None

        if not self.redis:
            return None

        try:
            last_reminder = await self.redis.get("mha:health:last_hydration")
            if last_reminder:
                last_dt = datetime.fromisoformat(last_reminder)
                if now - last_dt < timedelta(hours=self.hydration_interval):
                    return None

            await self.redis.set("mha:health:last_hydration", now.isoformat())
            return {
                "entity_id": "health.hydration",
                "alert_type": "hydration_reminder",
                "urgency": "low",
                "message": "Trink-Erinnerung: Ein Glas Wasser waere jetzt gut.",
                "data": {},
            }
        except Exception as e:
            logger.debug("Hydration-Check Fehler: %s", e)
            return None

    async def _send_alert(self, alert: dict):
        """Sendet einen Alert ueber den Notify-Callback."""
        if self._notify_callback:
            try:
                await self._notify_callback(
                    alert["alert_type"],
                    alert["urgency"],
                    alert["message"],
                )
            except Exception as e:
                logger.error("Health Alert Fehler: %s", e)
        else:
            logger.info("Health Alert (kein Callback): %s", alert["message"])

    async def get_status(self) -> dict:
        """Gibt den aktuellen Gesundheits-Status aller Sensoren zurueck."""
        states = await self.ha.get_states()
        if not states:
            return {"sensors": [], "score": 0}

        sensors = []
        total_score = 0
        count = 0

        for state in states:
            entity_id = state.get("entity_id", "")
            if not entity_id.startswith("sensor."):
                continue

            attrs = state.get("attributes", {})
            friendly_name = attrs.get("friendly_name", entity_id)

            # Exclude-Filter: entity_id UND friendly_name pruefen
            check_str = f"{entity_id} {friendly_name}".lower()
            if any(pat in check_str for pat in self._exclude_patterns):
                continue

            device_class = attrs.get("device_class", "")

            try:
                value = float(state.get("state", ""))
            except (ValueError, TypeError):
                continue

            if device_class == "carbon_dioxide" or "co2" in entity_id.lower():
                score = self._score_co2(value)
                sensors.append({"name": friendly_name, "type": "co2", "value": value, "unit": "ppm", "score": score})
                total_score += score
                count += 1
            elif device_class == "humidity" or "humid" in entity_id.lower():
                score = self._score_humidity(value)
                sensors.append({"name": friendly_name, "type": "humidity", "value": value, "unit": "%", "score": score})
                total_score += score
                count += 1
            elif device_class == "temperature":
                score = self._score_temperature(value)
                sensors.append({"name": friendly_name, "type": "temperature", "value": value, "unit": "°C", "score": score})
                total_score += score
                count += 1

        avg_score = int(total_score / count) if count > 0 else 0
        return {"sensors": sensors, "score": avg_score, "total_sensors": count}

    @staticmethod
    def _score_co2(ppm: float) -> int:
        if ppm < 600:
            return 100
        elif ppm < 800:
            return 85
        elif ppm < 1000:
            return 65
        elif ppm < 1200:
            return 45
        elif ppm < 1500:
            return 25
        return 10

    @staticmethod
    def _score_humidity(percent: float) -> int:
        if 40 <= percent <= 60:
            return 100
        elif 30 <= percent < 40 or 60 < percent <= 70:
            return 70
        elif 20 <= percent < 30 or 70 < percent <= 80:
            return 40
        return 15

    @staticmethod
    def _score_temperature(temp: float) -> int:
        if 20 <= temp <= 23:
            return 100
        elif 18 <= temp < 20 or 23 < temp <= 25:
            return 75
        elif 16 <= temp < 18 or 25 < temp <= 27:
            return 50
        return 25
