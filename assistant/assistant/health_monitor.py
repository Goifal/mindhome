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
from .constants import HEALTH_MONITOR_STARTUP_DELAY, REDIS_HEALTH_SNAPSHOT_TTL

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
        # Defaults: Waermepumpen, Prozessor/System-Temps, Batterie-Temps, Netzwerk-Geraete
        self._default_excludes = [
            "aquarea", "heatpump", "waermepumpe",
            "processor", "prozessor", "cpu_temp",
            "batterie_temp", "battery_temp",
            "tablet_", "steckdose_", "socket_",
            "inlet", "outlet", "discharge", "defrost",
            "solar_temp", "buffer_temp", "pool_temp",
            "pipe_temp", "eva_outlet", "main_hex",
            "sterilization", "backup_heater",
            "zone_1_", "zone_2_", "zone1_", "zone2_",
            "taupunkt", "dew_point",
        ]
        user_excludes = cfg.get("exclude_patterns", [])
        if isinstance(user_excludes, str):
            user_excludes = [p.strip() for p in user_excludes.splitlines() if p.strip()]
        self._exclude_patterns = [p.lower() for p in (self._default_excludes + user_excludes)]
        # Humidor-Ueberwachung (eigene Schwellwerte, separat vom Raumklima)
        humidor_cfg = yaml_config.get("humidor", {})
        self.humidor_enabled = humidor_cfg.get("enabled", False)
        self.humidor_entity = (humidor_cfg.get("sensor_entity") or "").strip()
        self.humidor_target = humidor_cfg.get("target_humidity", 70)
        self.humidor_warn_below = humidor_cfg.get("warn_below", 62)
        self.humidor_warn_above = humidor_cfg.get("warn_above", 75)

        # Nach Startup erste Runde nur loggen, nicht melden (Cooldowns leer)
        self._first_check = True

    async def initialize(self, redis_client: Optional[redis.Redis] = None):
        """Initialisiert mit Redis-Verbindung."""
        self.redis = redis_client
        logger.info("Health Monitor initialisiert (Intervall: %d Min.)", self.check_interval)

    def set_notify_callback(self, callback) -> None:
        """Setzt die Callback-Funktion fuer Warnungen."""
        self._notify_callback = callback

    async def start(self) -> None:
        """Startet den periodischen Check-Loop."""
        if not self.enabled:
            logger.info("Health Monitor deaktiviert")
            return
        self._running = True
        self._task = asyncio.create_task(self._check_loop())
        logger.info("Health Monitor gestartet")

    async def stop(self) -> None:
        """Stoppt den Check-Loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _check_loop(self):
        """Periodischer Gesundheits-Check.

        F-058: Erkennt grosse Zeitspruenge die auf NTP-Probleme hindeuten.
        """
        await asyncio.sleep(HEALTH_MONITOR_STARTUP_DELAY)

        _last_check_time = datetime.now()
        while self._running:
            try:
                # F-058: Zeitsprung-Erkennung (NTP-Ausfall)
                now = datetime.now()
                elapsed = (now - _last_check_time).total_seconds()
                expected = self.check_interval * 60
                if elapsed > expected * 3:
                    logger.warning(
                        "F-058: Grosser Zeitsprung erkannt (%.0fs statt ~%.0fs) — "
                        "NTP-Synchronisation pruefen",
                        elapsed, expected,
                    )
                _last_check_time = now

                alerts = await self.check_all()
                if self._first_check:
                    # Erste Runde nach Startup: Cooldowns befuellen aber
                    # nur kritische Alerts (high urgency) tatsaechlich senden
                    self._first_check = False
                    critical = [a for a in alerts if a.get("urgency") == "high"]
                    if critical:
                        for alert in critical:
                            await self._send_alert(alert)
                    if alerts:
                        logger.info(
                            "Health Monitor: %d Alerts nach Startup unterdrueckt (nur %d kritische gesendet)",
                            len(alerts) - len(critical), len(critical),
                        )
                else:
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
            await self.redis.expire(key, REDIS_HEALTH_SNAPSHOT_TTL)

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

            # Feuchtigkeits-Check (Humidor-Sensoren separat behandeln)
            elif device_class == "humidity" or "humid" in entity_id.lower() or "feuchte" in entity_id.lower():
                _is_humidor = "humidor" in entity_id.lower() or "humidor" in friendly_name.lower()
                if _is_humidor:
                    # Humidor: nur den konfigurierten Sensor pruefen, Rest ignorieren
                    if self.humidor_enabled and self.humidor_entity and entity_id.lower() == self.humidor_entity.lower():
                        alert = self._check_humidor(entity_id, friendly_name, value)
                    else:
                        alert = None
                else:
                    alert = self._check_humidity(entity_id, friendly_name, value)
                if alert:
                    alerts.append(alert)

            # Temperatur-Check deaktiviert — zu viele Fehlalarme bei normaler
            # Raumtemperatur. Heizungs-/Klimasteuerung erfolgt ueber die
            # Climate-Domain und Circadian Engine.
            # elif device_class == "temperature":
            #     ...

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

    def _check_humidor(self, entity_id: str, name: str, percent: float) -> Optional[dict]:
        """Prueft Humidor-Luftfeuchtigkeit mit eigenen Schwellwerten."""
        if percent < self.humidor_warn_below:
            diff = self.humidor_target - percent
            return self._make_alert(
                entity_id, "humidor_low", "medium",
                f"Humidor: Feuchtigkeit bei {int(percent)}% — {int(diff)}% unter Zielwert ({self.humidor_target}%). Wasser nachfuellen!",
                {"sensor": name, "value": percent, "unit": "%", "target": self.humidor_target},
            )
        elif percent > self.humidor_warn_above:
            return self._make_alert(
                entity_id, "humidor_high", "low",
                f"Humidor: Feuchtigkeit bei {int(percent)}% — ueber {self.humidor_warn_above}%. Deckel kurz oeffnen.",
                {"sensor": name, "value": percent, "unit": "%", "target": self.humidor_target},
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

            await self.redis.setex("mha:health:last_hydration", 86400, now.isoformat())
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

    async def get_trend_summary(self, lookback_hours: int = 6) -> Optional[str]:
        """Kompakter Trend-String fuer den LLM-Kontext.

        Vergleicht aktuelle Werte mit dem Durchschnitt der letzten Stunden
        und gibt einen einzeiligen Trend zurueck.

        Returns:
            z.B. "Raumklima 78/100 | CO2 steigend (520→680ppm) | Luft stabil"
            oder None wenn keine Daten.
        """
        if not self.redis:
            return None

        try:
            import json
            now = datetime.now()
            status = await self.get_status()
            if not status.get("sensors"):
                return None

            # Aktuelle Durchschnitte pro Typ
            current = {}
            for sensor in status["sensors"]:
                s_type = sensor.get("type", "")
                if s_type:
                    current.setdefault(s_type, []).append(sensor.get("value", 0))
            current_avg = {
                t: round(sum(v) / len(v), 1) for t, v in current.items() if v
            }

            # Historische Snapshots laden
            historical = {}  # type -> [values]
            for h in range(1, lookback_hours + 1):
                ts = now - timedelta(hours=h)
                key = f"mha:health:snapshot:{ts.strftime('%Y-%m-%d:%H')}"
                raw = await self.redis.get(key)
                if raw:
                    snap = json.loads(raw)
                    for t, v in snap.items():
                        if t != "score" and isinstance(v, (int, float)):
                            historical.setdefault(t, []).append(v)

            if not historical and not current_avg:
                return None

            # Trend-Strings bauen
            parts = [f"Raumklima {status.get('score', 0)}/100"]
            _type_labels = {"co2": "CO2", "humidity": "Luft", "temperature": "Temp"}

            for s_type, label in _type_labels.items():
                cur = current_avg.get(s_type)
                if cur is None:
                    continue
                hist_vals = historical.get(s_type, [])
                if hist_vals:
                    hist_avg = sum(hist_vals) / len(hist_vals)
                    diff = cur - hist_avg
                    unit = {"co2": "ppm", "humidity": "%", "temperature": "°C"}.get(s_type, "")
                    if abs(diff) < 0.5:
                        parts.append(f"{label} stabil ({cur:.0f}{unit})")
                    else:
                        trend = "steigend" if diff > 0 else "fallend"
                        parts.append(f"{label} {trend} ({hist_avg:.0f}→{cur:.0f}{unit})")
                else:
                    unit = {"co2": "ppm", "humidity": "%", "temperature": "°C"}.get(s_type, "")
                    parts.append(f"{label} {cur:.0f}{unit}")

            return " | ".join(parts) if len(parts) > 1 else None

        except Exception as e:
            logger.debug("Trend-Summary Fehler: %s", e)
            return None
