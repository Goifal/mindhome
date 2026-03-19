"""
Predictive Maintenance - Vorhersage von Geraeteausfaellen.

Medium Effort Feature: Erweitert das bestehende Device-Health-Monitoring um:
- Lebensdauer-Tracking (Installation, Betriebsstunden)
- Batterie-Drain-Rate-Berechnung
- Degradationserkennung (Leistungsabfall ueber Zeit)
- Wartungsplanung basierend auf tatsaechlicher Nutzung

Konfigurierbar in der Jarvis Assistant UI unter "Intelligenz".
"""

import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config

logger = logging.getLogger(__name__)

REDIS_KEY_DEVICE_LIFECYCLE = "mha:maintenance:lifecycle"
REDIS_KEY_BATTERY_HISTORY = "mha:maintenance:battery"
REDIS_KEY_PREDICTIONS = "mha:maintenance:predictions"
REDIS_KEY_DEVICE_HEALTH_SCORE = "mha:maintenance:health_score"

# Typische Lebensdauern in Tagen (Defaults)
DEFAULT_LIFESPANS = {
    "motion_sensor": 1825,      # 5 Jahre
    "temperature_sensor": 1825,
    "humidity_sensor": 1825,
    "door_sensor": 1825,
    "window_sensor": 1825,
    "smoke_detector": 3650,     # 10 Jahre
    "water_leak_sensor": 1825,
    "smart_plug": 2555,         # 7 Jahre
    "light_bulb": 1095,         # 3 Jahre (LED)
    "thermostat": 2555,
    "lock": 1825,
    "camera": 1825,
    "default": 1825,
}

# Batterie-Drain Schwellen (Prozent pro Woche)
DRAIN_THRESHOLDS = {
    "normal": 2.0,
    "concerning": 5.0,
    "critical": 10.0,
}


class DeviceLifecycleEntry:
    """Lebenszyklus-Daten fuer ein Geraet."""

    def __init__(self, entity_id: str, data: dict = None):
        data = data or {}
        self.entity_id = entity_id
        self.device_type = data.get("device_type", "default")
        self.installed_date = data.get("installed_date")
        self.last_battery_level = data.get("last_battery_level")
        self.last_battery_date = data.get("last_battery_date")
        self.battery_history: list[dict] = data.get("battery_history", [])
        self.health_score = data.get("health_score", 100.0)
        self.failure_count = data.get("failure_count", 0)
        self.last_failure_date = data.get("last_failure_date")
        self.total_offline_hours = data.get("total_offline_hours", 0.0)
        self.notes = data.get("notes", "")

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "device_type": self.device_type,
            "installed_date": self.installed_date,
            "last_battery_level": self.last_battery_level,
            "last_battery_date": self.last_battery_date,
            "battery_history": self.battery_history[-30:],  # Letzte 30 Eintraege
            "health_score": round(self.health_score, 1),
            "failure_count": self.failure_count,
            "last_failure_date": self.last_failure_date,
            "total_offline_hours": round(self.total_offline_hours, 1),
            "notes": self.notes,
        }


class PredictiveMaintenance:
    """Vorhersage von Geraeteausfaellen und Wartungsbedarf."""

    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None

        cfg = yaml_config.get("predictive_maintenance", {})
        self.enabled = cfg.get("enabled", True)
        self.lookback_days = cfg.get("lookback_days", 90)
        self.failure_probability_threshold = cfg.get("failure_probability_threshold", 0.7)
        self.battery_drain_alert_pct = cfg.get("battery_drain_alert_pct_per_week", 5.0)

        # Typische Lebensdauern (konfigurierbar)
        self._lifespans = {**DEFAULT_LIFESPANS, **cfg.get("typical_lifespans", {})}

        # Geraete-Lifecycle Cache
        self._devices: dict[str, DeviceLifecycleEntry] = {}

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis."""
        self.redis = redis_client
        if self.redis and self.enabled:
            await self._load_devices()
        logger.info("PredictiveMaintenance initialisiert (enabled: %s)", self.enabled)

    async def _load_devices(self):
        """Laedt Geraete-Lifecycle-Daten aus Redis."""
        if not self.redis:
            return
        try:
            raw = await self.redis.get(REDIS_KEY_DEVICE_LIFECYCLE)
            if raw:
                data = json.loads(raw)
                for entity_id, entry_data in data.items():
                    self._devices[entity_id] = DeviceLifecycleEntry(entity_id, entry_data)
        except Exception as e:
            logger.debug("Lifecycle-Daten laden fehlgeschlagen: %s", e)

    async def _save_devices(self):
        """Speichert Geraete-Lifecycle-Daten in Redis."""
        if not self.redis:
            return
        try:
            data = {eid: entry.to_dict() for eid, entry in self._devices.items()}
            await self.redis.set(
                REDIS_KEY_DEVICE_LIFECYCLE,
                json.dumps(data, ensure_ascii=False),
                ex=86400 * 365,  # 1 Jahr
            )
        except Exception as e:
            logger.debug("Lifecycle-Daten speichern fehlgeschlagen: %s", e)

    def _get_or_create(self, entity_id: str) -> DeviceLifecycleEntry:
        """Gibt einen Lifecycle-Eintrag zurueck oder erstellt einen neuen."""
        if entity_id not in self._devices:
            self._devices[entity_id] = DeviceLifecycleEntry(entity_id)
        return self._devices[entity_id]

    async def record_battery_level(self, entity_id: str, battery_level: float):
        """Zeichnet einen Batterie-Stand auf.

        Args:
            entity_id: Entity-ID (z.B. "sensor.motion_kitchen_battery")
            battery_level: Batteriestand in Prozent (0-100)
        """
        if not self.enabled:
            return

        entry = self._get_or_create(entity_id)
        now = datetime.now(timezone.utc).isoformat()

        entry.battery_history.append({
            "level": battery_level,
            "date": now,
        })
        # Max 90 Eintraege behalten
        entry.battery_history = entry.battery_history[-90:]

        entry.last_battery_level = battery_level
        entry.last_battery_date = now

        await self._save_devices()

    async def record_device_offline(self, entity_id: str, offline_duration_hours: float):
        """Zeichnet eine Offline-Phase auf."""
        if not self.enabled:
            return

        entry = self._get_or_create(entity_id)
        entry.total_offline_hours += offline_duration_hours
        entry.failure_count += 1
        entry.last_failure_date = datetime.now(timezone.utc).isoformat()

        # Health-Score reduzieren
        entry.health_score = max(0, entry.health_score - min(10, offline_duration_hours))

        await self._save_devices()

    async def register_device(
        self,
        entity_id: str,
        device_type: str = "default",
        installed_date: str = None,
        notes: str = "",
    ):
        """Registriert ein Geraet fuer Lifecycle-Tracking.

        Args:
            entity_id: Entity-ID
            device_type: Geraetetyp (z.B. "motion_sensor", "thermostat")
            installed_date: Installationsdatum (ISO)
            notes: Notizen
        """
        entry = self._get_or_create(entity_id)
        entry.device_type = device_type
        if installed_date:
            entry.installed_date = installed_date
        if notes:
            entry.notes = notes

        await self._save_devices()
        logger.info("Geraet registriert: %s (Typ: %s)", entity_id, device_type)

    def calculate_battery_drain_rate(self, entity_id: str) -> Optional[dict]:
        """Berechnet die Batterie-Drain-Rate.

        Returns:
            Dict mit pct_per_week, days_until_empty, severity oder None
        """
        entry = self._devices.get(entity_id)
        if not entry or len(entry.battery_history) < 2:
            return None

        history = entry.battery_history
        # Letzte vs. aelteste Messung
        newest = history[-1]
        # Mindestens 7 Tage zurueckliegende Messung suchen
        oldest_valid = None
        for h in history:
            try:
                h_date = datetime.fromisoformat(h["date"])
                n_date = datetime.fromisoformat(newest["date"])
                if (n_date - h_date).days >= 7:
                    oldest_valid = h
                    break
            except (ValueError, TypeError):
                continue

        if not oldest_valid:
            # Weniger als 7 Tage Daten — nehme was da ist
            oldest_valid = history[0]

        try:
            start_date = datetime.fromisoformat(oldest_valid["date"])
            end_date = datetime.fromisoformat(newest["date"])
            days_elapsed = max(1, (end_date - start_date).days)
        except (ValueError, TypeError):
            return None

        level_drop = oldest_valid["level"] - newest["level"]
        if level_drop <= 0:
            return {"pct_per_week": 0, "days_until_empty": None, "severity": "normal"}

        pct_per_day = level_drop / days_elapsed
        pct_per_week = pct_per_day * 7

        days_until_empty = None
        if pct_per_day > 0 and newest["level"] > 0:
            days_until_empty = int(newest["level"] / pct_per_day)

        severity = "normal"
        if pct_per_week >= DRAIN_THRESHOLDS["critical"]:
            severity = "critical"
        elif pct_per_week >= DRAIN_THRESHOLDS["concerning"]:
            severity = "concerning"

        return {
            "pct_per_week": round(pct_per_week, 2),
            "pct_per_day": round(pct_per_day, 2),
            "days_until_empty": days_until_empty,
            "current_level": newest["level"],
            "severity": severity,
            "measurement_days": days_elapsed,
        }

    def calculate_health_score(self, entity_id: str) -> dict:
        """Berechnet einen Gesundheits-Score (0-100) fuer ein Geraet.

        Faktoren:
        - Alter (relativ zur typischen Lebensdauer)
        - Batterie-Drain-Rate
        - Offline-Haeufigkeit
        - Aktuelle Verfuegbarkeit
        """
        entry = self._devices.get(entity_id)
        if not entry:
            return {"score": 100, "factors": {}, "risk": "low"}

        score = 100.0
        factors = {}

        # Alter
        if entry.installed_date:
            try:
                installed = datetime.fromisoformat(entry.installed_date)
                age_days = (datetime.now(timezone.utc) - installed).days
                lifespan = self._lifespans.get(entry.device_type, self._lifespans["default"])
                age_ratio = age_days / lifespan
                age_penalty = min(40, age_ratio * 40)  # Max 40 Punkte Abzug
                score -= age_penalty
                factors["age"] = {
                    "days": age_days,
                    "lifespan_days": lifespan,
                    "ratio": round(age_ratio, 2),
                    "penalty": round(age_penalty, 1),
                }
            except (ValueError, TypeError):
                pass

        # Batterie-Drain
        drain = self.calculate_battery_drain_rate(entity_id)
        if drain:
            if drain["severity"] == "critical":
                score -= 30
                factors["battery_drain"] = {"severity": "critical", "penalty": 30}
            elif drain["severity"] == "concerning":
                score -= 15
                factors["battery_drain"] = {"severity": "concerning", "penalty": 15}

        # Offline-Haeufigkeit
        if entry.failure_count > 0:
            offline_penalty = min(20, entry.failure_count * 5)
            score -= offline_penalty
            factors["offline_events"] = {
                "count": entry.failure_count,
                "total_hours": entry.total_offline_hours,
                "penalty": offline_penalty,
            }

        score = max(0, min(100, score))

        risk = "low"
        if score < 30:
            risk = "critical"
        elif score < 50:
            risk = "high"
        elif score < 70:
            risk = "medium"

        return {
            "score": round(score, 1),
            "factors": factors,
            "risk": risk,
            "entity_id": entity_id,
            "device_type": entry.device_type,
        }

    def predict_failures(self) -> list[dict]:
        """Gibt eine Liste von vorhergesagten Ausfaellen zurueck.

        Returns:
            Liste sortiert nach Dringlichkeit
        """
        predictions = []

        for entity_id, entry in self._devices.items():
            health = self.calculate_health_score(entity_id)

            if health["risk"] in ("high", "critical"):
                prediction = {
                    "entity_id": entity_id,
                    "device_type": entry.device_type,
                    "health_score": health["score"],
                    "risk": health["risk"],
                    "factors": health["factors"],
                }

                # Batterie-Vorhersage
                drain = self.calculate_battery_drain_rate(entity_id)
                if drain and drain.get("days_until_empty"):
                    prediction["battery_days_remaining"] = drain["days_until_empty"]
                    prediction["battery_level"] = drain["current_level"]

                predictions.append(prediction)

        # Sortieren: Kritisch zuerst, dann nach Score
        predictions.sort(key=lambda p: (
            0 if p["risk"] == "critical" else 1,
            p["health_score"],
        ))

        return predictions

    def get_maintenance_suggestions(self) -> list[dict]:
        """Gibt wartungsrelevante Vorschlaege zurueck.

        Z.B. "Batterie von Bewegungsmelder Flur in ~14 Tagen leer"
        """
        suggestions = []

        for entity_id, entry in self._devices.items():
            # Batterie-Warnung
            drain = self.calculate_battery_drain_rate(entity_id)
            if drain and drain.get("days_until_empty") and drain["days_until_empty"] <= 30:
                suggestions.append({
                    "type": "battery_replacement",
                    "entity_id": entity_id,
                    "urgency": "high" if drain["days_until_empty"] <= 7 else "medium",
                    "description": f"Batterie von {entity_id} in ca. {drain['days_until_empty']} Tagen leer "
                                   f"(aktuell: {drain['current_level']}%, Drain: {drain['pct_per_week']:.1f}%/Woche).",
                    "days_remaining": drain["days_until_empty"],
                })

            # Alter-Warnung
            if entry.installed_date:
                try:
                    installed = datetime.fromisoformat(entry.installed_date)
                    age_days = (datetime.now(timezone.utc) - installed).days
                    lifespan = self._lifespans.get(entry.device_type, self._lifespans["default"])
                    if age_days >= lifespan * 0.9:
                        suggestions.append({
                            "type": "end_of_life",
                            "entity_id": entity_id,
                            "urgency": "medium",
                            "description": f"{entity_id} ist {age_days // 365} Jahre alt "
                                           f"(typische Lebensdauer: {lifespan // 365} Jahre). Ersatz planen.",
                            "age_days": age_days,
                            "lifespan_days": lifespan,
                        })
                except (ValueError, TypeError):
                    pass

        suggestions.sort(key=lambda s: 0 if s["urgency"] == "high" else 1)
        return suggestions

    def get_context_hint(self) -> str:
        """Gibt einen Kontext-Hinweis fuer den LLM-Prompt zurueck."""
        if not self.enabled:
            return ""

        suggestions = self.get_maintenance_suggestions()
        if not suggestions:
            return ""

        high_urgency = [s for s in suggestions if s["urgency"] == "high"]
        if high_urgency:
            first = high_urgency[0]
            return f"WARTUNGSHINWEIS: {first['description']}"

        return ""

    def get_overview(self) -> dict:
        """Gibt eine Uebersicht ueber alle getackten Geraete zurueck."""
        total = len(self._devices)
        healthy = sum(1 for d in self._devices.values()
                      if self.calculate_health_score(d.entity_id)["risk"] == "low")
        at_risk = total - healthy

        return {
            "total_tracked": total,
            "healthy": healthy,
            "at_risk": at_risk,
            "predictions": self.predict_failures()[:5],
            "suggestions": self.get_maintenance_suggestions()[:5],
        }
