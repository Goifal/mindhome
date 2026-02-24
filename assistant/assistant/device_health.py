"""
Device Health Monitor - Geraete-Beziehung & Anomalie-Erkennung.

Phase 15.3: Erkennt ungewoehnliches Geraeteverhalten anhand historischer Baselines.
- Rolling-Average Baseline (30 Tage, konfigurierbar)
- Anomalie-Erkennung: Alert bei Abweichung > 2 Standardabweichungen
- Stale-Device-Erkennung: Sensoren ohne Aenderung (Batterie-Warnung)
- HVAC-Effizienz: Heizung/Klima erreicht Zieltemperatur nicht
- Energie-Anomalien: Verbrauch deutlich ueber Durchschnitt

Alerts haben Urgency "low" und werden ueber Phase 15.4 gebatcht.
"""

import asyncio
import json
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config
from .ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)

DEFAULTS = {
    "check_interval_minutes": 60,
    "baseline_history_days": 30,
    "stddev_multiplier": 2.0,
    "min_samples": 10,
    "stale_sensor_days": 3,
    "hvac_timeout_minutes": 120,
    "hvac_temp_tolerance": 1.0,
    "alert_cooldown_minutes": 1440,
    "track_domains": ["sensor", "climate", "binary_sensor"],
    "exclude_patterns": ["weather.", "sun.", "automation.", "update."],
    "energy_sensor_keywords": ["energy", "power", "verbrauch", "strom"],
}


class DeviceHealthMonitor:
    """Ueberwacht Geraeteverhalten und erkennt Anomalien."""

    def __init__(self, ha_client: HomeAssistantClient):
        self.ha = ha_client
        self.redis: Optional[aioredis.Redis] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._notify_callback = None

        cfg = yaml_config.get("device_health", {})
        self.enabled = cfg.get("enabled", True)
        self.check_interval = cfg.get(
            "check_interval_minutes", DEFAULTS["check_interval_minutes"]
        )
        self.baseline_days = cfg.get(
            "baseline_history_days", DEFAULTS["baseline_history_days"]
        )
        self.stddev_multiplier = cfg.get(
            "stddev_multiplier", DEFAULTS["stddev_multiplier"]
        )
        self.min_samples = cfg.get("min_samples", DEFAULTS["min_samples"])
        self.stale_days = cfg.get(
            "stale_sensor_days", DEFAULTS["stale_sensor_days"]
        )
        self.hvac_timeout = cfg.get(
            "hvac_timeout_minutes", DEFAULTS["hvac_timeout_minutes"]
        )
        self.hvac_tolerance = cfg.get(
            "hvac_temp_tolerance", DEFAULTS["hvac_temp_tolerance"]
        )
        self.alert_cooldown = cfg.get(
            "alert_cooldown_minutes", DEFAULTS["alert_cooldown_minutes"]
        )
        self.track_domains = cfg.get(
            "track_domains", DEFAULTS["track_domains"]
        )
        self.exclude_patterns = cfg.get(
            "exclude_patterns", DEFAULTS["exclude_patterns"]
        )
        self.energy_keywords = cfg.get(
            "energy_sensor_keywords", DEFAULTS["energy_sensor_keywords"]
        )
        # Whitelist: Wenn gesetzt, NUR diese Entities überwachen
        self.monitored_entities: list[str] = cfg.get("monitored_entities", [])

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis-Verbindung."""
        self.redis = redis_client
        logger.info(
            "DeviceHealthMonitor initialisiert (Intervall: %d Min., "
            "Baseline: %d Tage, Schwelle: %.1fσ)",
            self.check_interval, self.baseline_days, self.stddev_multiplier,
        )

    def set_notify_callback(self, callback):
        """Setzt die Callback-Funktion fuer Anomalie-Warnungen."""
        self._notify_callback = callback

    async def start(self):
        """Startet den periodischen Check-Loop."""
        if not self.enabled:
            logger.info("DeviceHealthMonitor deaktiviert")
            return
        self._running = True
        self._task = asyncio.create_task(self._check_loop())
        logger.info("DeviceHealthMonitor gestartet")

    async def stop(self):
        """Stoppt den Check-Loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # ------------------------------------------------------------------
    # Hauptschleife
    # ------------------------------------------------------------------

    async def _check_loop(self):
        """Periodische Anomalie-Erkennung."""
        while self._running:
            try:
                alerts = await self.check_all()
                for alert in alerts:
                    await self._send_alert(alert)
                if alerts:
                    logger.info(
                        "DeviceHealth: %d Anomalie(n) erkannt", len(alerts)
                    )
            except Exception as e:
                logger.error("DeviceHealth check error: %s", e)
            await asyncio.sleep(self.check_interval * 60)

    async def check_all(self) -> list[dict]:
        """Fuehrt alle Checks durch und gibt Alert-Liste zurueck."""
        states = await self.ha.get_states()
        if not states:
            return []

        alerts = []

        for state in states:
            entity_id = state.get("entity_id", "")
            if self._should_exclude(entity_id):
                continue

            domain = entity_id.split(".")[0] if "." in entity_id else ""

            # 1) HVAC-Effizienz-Check (climate-Entities)
            if domain == "climate":
                alert = await self._check_hvac_efficiency(entity_id, state)
                if alert:
                    alerts.append(alert)
                continue

            # 2) Stale-Sensor-Check (binary_sensor ohne Aenderung)
            if domain == "binary_sensor":
                alert = await self._check_stale_sensor(entity_id, state)
                if alert:
                    alerts.append(alert)
                continue

            # 3) Numerische Anomalie-Erkennung (sensor-Entities)
            if domain == "sensor":
                raw = state.get("state", "")
                try:
                    value = float(raw)
                except (ValueError, TypeError):
                    continue

                alert = await self._check_value_anomaly(
                    entity_id, value, state
                )
                if alert:
                    alerts.append(alert)

        return alerts

    # ------------------------------------------------------------------
    # Check 1: Numerische Anomalie (Baseline-Vergleich)
    # ------------------------------------------------------------------

    async def _check_value_anomaly(
        self, entity_id: str, current_value: float, state: dict
    ) -> Optional[dict]:
        """Prueft ob der aktuelle Wert anomal gegenueber der Baseline ist."""
        if not self.redis:
            return None

        baseline = await self._get_baseline(entity_id)

        # Sample immer hinzufuegen (fuer zukuenftige Baseline)
        await self._add_sample(entity_id, current_value)

        if not baseline or baseline["samples"] < self.min_samples:
            return None

        mean = baseline["mean"]
        stddev = baseline["stddev"]
        if stddev < 0.001:
            return None

        deviation = abs(current_value - mean) / stddev
        if deviation <= self.stddev_multiplier:
            return None

        if not await self._check_cooldown(entity_id):
            return None

        name = state.get("attributes", {}).get("friendly_name", entity_id)
        unit = state.get("attributes", {}).get("unit_of_measurement", "")

        is_energy = any(kw in entity_id.lower() for kw in self.energy_keywords)
        if is_energy and current_value > mean:
            pct = ((current_value - mean) / mean * 100) if mean else 0
            message = (
                f"{name}: Verbrauch {current_value:.1f}{unit} — "
                f"{pct:.0f}% ueber Durchschnitt ({mean:.1f}{unit})."
            )
        else:
            direction = "ueber" if current_value > mean else "unter"
            message = (
                f"{name}: Ungewoehnlicher Wert {current_value:.1f}{unit} "
                f"({direction} Normal {mean:.1f}±{stddev:.1f}{unit})."
            )

        await self._mark_notified(entity_id)

        return {
            "entity_id": entity_id,
            "entity_name": name,
            "alert_type": "device_anomaly",
            "message": message,
            "urgency": "low",
            "data": {
                "current_value": current_value,
                "baseline_mean": round(mean, 2),
                "baseline_stddev": round(stddev, 2),
                "deviation_factor": round(deviation, 2),
                "unit": unit,
            },
        }

    # ------------------------------------------------------------------
    # Check 2: Stale Sensor (Bewegungsmelder, Tuerkontakte)
    # ------------------------------------------------------------------

    async def _check_stale_sensor(
        self, entity_id: str, state: dict
    ) -> Optional[dict]:
        """Prueft ob ein Binary-Sensor seit Tagen unveraendert ist."""
        last_changed = state.get("last_changed", "")
        if not last_changed:
            return None

        try:
            last_dt = datetime.fromisoformat(
                last_changed.replace("Z", "+00:00")
            )
            # Sicherstellen dass timezone-aware
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return None

        age_days = (datetime.now(timezone.utc) - last_dt).total_seconds() / 86400
        if age_days < self.stale_days:
            return None

        if not await self._check_cooldown(entity_id):
            return None

        name = state.get("attributes", {}).get("friendly_name", entity_id)
        device_class = state.get("attributes", {}).get("device_class", "")

        if device_class == "motion":
            hint = "Batterie pruefen oder Sensor defekt?"
        elif device_class in ("door", "window"):
            hint = "Sensor blockiert oder Batterie leer?"
        else:
            hint = "Batterie oder Verbindung pruefen."

        message = (
            f"{name}: Seit {int(age_days)} Tagen unveraendert. {hint}"
        )

        await self._mark_notified(entity_id)

        return {
            "entity_id": entity_id,
            "entity_name": name,
            "alert_type": "stale_device",
            "message": message,
            "urgency": "low",
            "data": {
                "days_unchanged": round(age_days, 1),
                "device_class": device_class,
                "last_changed": last_changed,
            },
        }

    # ------------------------------------------------------------------
    # Check 3: HVAC-Effizienz (Heizung/Klima erreicht Ziel nicht)
    # ------------------------------------------------------------------

    async def _check_hvac_efficiency(
        self, entity_id: str, state: dict
    ) -> Optional[dict]:
        """Prueft ob Klima-Geraet die Zieltemperatur nicht erreicht."""
        attrs = state.get("attributes", {})
        current_temp = attrs.get("current_temperature")
        target_temp = attrs.get("temperature")
        hvac_action = state.get("state", "off")

        if current_temp is None or target_temp is None:
            return None

        try:
            current_temp = float(current_temp)
            target_temp = float(target_temp)
        except (ValueError, TypeError):
            return None

        if hvac_action in ("off", "unavailable", "idle"):
            # Nicht aktiv → Timer zuruecksetzen
            if self.redis:
                await self.redis.delete(f"mha:device:hvac_start:{entity_id}")
            return None

        temp_diff = abs(current_temp - target_temp)
        if temp_diff <= self.hvac_tolerance:
            # Ziel erreicht → Timer zuruecksetzen
            if self.redis:
                await self.redis.delete(f"mha:device:hvac_start:{entity_id}")
            return None

        # Ziel nicht erreicht — seit wann?
        if not self.redis:
            return None

        hvac_key = f"mha:device:hvac_start:{entity_id}"
        start_raw = await self.redis.get(hvac_key)

        if not start_raw:
            await self.redis.set(
                hvac_key,
                datetime.now(timezone.utc).isoformat(),
                ex=self.hvac_timeout * 60 * 2,
            )
            return None

        try:
            start_dt = datetime.fromisoformat(
                start_raw.replace("Z", "+00:00") if isinstance(start_raw, str) else start_raw
            )
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            await self.redis.delete(hvac_key)
            return None

        elapsed_min = (datetime.now(timezone.utc) - start_dt).total_seconds() / 60
        if elapsed_min < self.hvac_timeout:
            return None

        if not await self._check_cooldown(entity_id):
            return None

        name = attrs.get("friendly_name", entity_id)
        action_de = "heizt" if hvac_action == "heating" else "kuehlt"

        message = (
            f"{name}: {action_de} seit {int(elapsed_min)} Min. auf "
            f"{target_temp:.0f}°C, aber nur {current_temp:.1f}°C erreicht."
        )

        await self._mark_notified(entity_id)
        await self.redis.delete(hvac_key)

        return {
            "entity_id": entity_id,
            "entity_name": name,
            "alert_type": "hvac_inefficiency",
            "message": message,
            "urgency": "low",
            "data": {
                "current_temp": current_temp,
                "target_temp": target_temp,
                "elapsed_minutes": round(elapsed_min),
                "hvac_action": hvac_action,
            },
        }

    # ------------------------------------------------------------------
    # Baseline-Verwaltung (Redis)
    # ------------------------------------------------------------------

    async def _get_baseline(self, entity_id: str) -> Optional[dict]:
        """Holt die Baseline (Mean + Stddev) fuer ein Entity."""
        if not self.redis:
            return None
        try:
            key = f"mha:device:baseline:{entity_id}"
            data = await self.redis.hgetall(key)
            if not data:
                return None
            return {
                "mean": float(data.get("mean", 0)),
                "stddev": float(data.get("stddev", 0)),
                "samples": int(data.get("samples", 0)),
            }
        except Exception as e:
            logger.debug("Baseline fetch error [%s]: %s", entity_id, e)
            return None

    async def _add_sample(self, entity_id: str, value: float):
        """Fuegt einen Sample-Wert hinzu und aktualisiert die Baseline."""
        if not self.redis:
            return
        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            sample_key = f"mha:device:sample:{entity_id}:{today}"

            await self.redis.rpush(sample_key, str(value))
            await self.redis.expire(
                sample_key, self.baseline_days * 86400 + 86400
            )

            await self._recalculate_baseline(entity_id)
        except Exception as e:
            logger.debug("Sample add error [%s]: %s", entity_id, e)

    async def _recalculate_baseline(self, entity_id: str):
        """Berechnet Mean + Stddev aus allen gespeicherten Samples."""
        if not self.redis:
            return
        try:
            all_values = []
            now = datetime.now(timezone.utc)

            for day_offset in range(self.baseline_days + 1):
                day = (now - timedelta(days=day_offset)).strftime("%Y-%m-%d")
                key = f"mha:device:sample:{entity_id}:{day}"
                samples = await self.redis.lrange(key, 0, -1)
                for s in samples:
                    try:
                        all_values.append(float(s))
                    except (ValueError, TypeError):
                        continue

            if len(all_values) < 2:
                return

            mean = sum(all_values) / len(all_values)
            variance = sum((v - mean) ** 2 for v in all_values) / len(
                all_values
            )
            stddev = math.sqrt(variance)

            baseline_key = f"mha:device:baseline:{entity_id}"
            await self.redis.hset(
                baseline_key,
                mapping={
                    "mean": str(round(mean, 4)),
                    "stddev": str(round(stddev, 4)),
                    "samples": str(len(all_values)),
                    "last_updated": now.isoformat(),
                },
            )
            await self.redis.expire(
                baseline_key, (self.baseline_days + 7) * 86400
            )
        except Exception as e:
            logger.debug("Baseline recalc error [%s]: %s", entity_id, e)

    # ------------------------------------------------------------------
    # Cooldown & Notification
    # ------------------------------------------------------------------

    async def _check_cooldown(self, entity_id: str) -> bool:
        """Prueft ob fuer dieses Entity ein Alert gesendet werden darf."""
        if not self.redis:
            return True
        try:
            key = f"mha:device:notified:{entity_id}"
            return await self.redis.exists(key) == 0
        except Exception:
            return True

    async def _mark_notified(self, entity_id: str):
        """Markiert Entity als benachrichtigt (Cooldown starten).

        F-057: Cooldown eskaliert mit der Anzahl der Alerts fuer dieselbe Entity.
        1. Alert: normaler Cooldown (24h Standard)
        2. Alert: 2x Cooldown (48h)
        3. Alert: 4x Cooldown (4 Tage)
        4+: 7 Tage max (Entity wahrscheinlich dauerhaft defekt)
        """
        if not self.redis:
            return
        try:
            key = f"mha:device:notified:{entity_id}"
            count_key = f"mha:device:alert_count:{entity_id}"
            # F-057: Alert-Zaehler inkrementieren
            count = await self.redis.incr(count_key)
            await self.redis.expire(count_key, 30 * 86400)  # 30 Tage TTL

            # Eskalierender Cooldown
            multiplier = min(2 ** (count - 1), 7)  # 1x, 2x, 4x, 7x max
            cooldown_seconds = self.alert_cooldown * 60 * multiplier
            max_cooldown = 7 * 86400  # Max 7 Tage
            cooldown_seconds = min(cooldown_seconds, max_cooldown)

            await self.redis.set(key, str(count), ex=int(cooldown_seconds))
            if count > 1:
                logger.info(
                    "F-057: Alert-Cooldown eskaliert fuer %s: %dx (Alert #%d)",
                    entity_id, multiplier, count,
                )
        except Exception as e:
            logger.debug("Notified mark error [%s]: %s", entity_id, e)

    async def _send_alert(self, alert: dict):
        """Sendet Alert ueber den registrierten Callback."""
        if self._notify_callback:
            try:
                await self._notify_callback(alert)
            except Exception as e:
                logger.error("Alert-Versand fehlgeschlagen: %s", e)
        else:
            logger.info("DeviceHealth: %s", alert["message"])

    # ------------------------------------------------------------------
    # Hilfs-Methoden
    # ------------------------------------------------------------------

    def _should_exclude(self, entity_id: str) -> bool:
        """Prüft ob Entity ausgeschlossen werden soll.

        Wenn monitored_entities gesetzt ist (Whitelist), werden NUR
        diese Entities überwacht. Alles andere wird ausgeschlossen.
        Sonst: Domain-Filter + Exclude-Patterns wie bisher.
        """
        # Whitelist-Modus: Nur explizit gewählte Entities
        if self.monitored_entities:
            return entity_id not in self.monitored_entities

        # Standard-Modus: Domain-Filter + Exclude-Patterns
        for pattern in self.exclude_patterns:
            if pattern in entity_id:
                return True
        domain = entity_id.split(".")[0] if "." in entity_id else ""
        if domain and domain not in self.track_domains:
            return True
        return False

    # ------------------------------------------------------------------
    # API fuer Kontext / Diagnostik
    # ------------------------------------------------------------------

    async def get_status(self) -> dict:
        """Gibt den aktuellen Status des DeviceHealthMonitors zurueck."""
        if not self.redis:
            return {"enabled": self.enabled, "baselines": 0, "alerts_today": 0}

        try:
            baseline_keys = []
            async for key in self.redis.scan_iter(
                match="mha:device:baseline:*", count=100
            ):
                baseline_keys.append(key)

            notified_keys = []
            async for key in self.redis.scan_iter(
                match="mha:device:notified:*", count=100
            ):
                notified_keys.append(key)

            return {
                "enabled": self.enabled,
                "baselines": len(baseline_keys),
                "active_cooldowns": len(notified_keys),
                "check_interval_min": self.check_interval,
                "stddev_threshold": self.stddev_multiplier,
            }
        except Exception:
            return {"enabled": self.enabled, "baselines": 0}

    async def get_baseline_info(self, entity_id: str) -> Optional[dict]:
        """Gibt Baseline-Daten fuer ein bestimmtes Entity zurueck."""
        return await self._get_baseline(entity_id)
