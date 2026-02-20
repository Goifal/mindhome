"""
Threat Assessment - Proaktive Sicherheits-Analyse.

Features:
- Ungewoehnliche Bewegung nachts (wenn alle schlafen)
- Offene Fenster bei Sturmwarnung
- Unbekannte Geraete im Netzwerk (via HA device_tracker)
- Tuer offen + niemand zuhause
- Zusammenfassende Sicherheitsbewertung

Wird periodisch von proactive.py aufgerufen.
"""

import logging
from datetime import datetime
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config
from .ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)

KEY_KNOWN_DEVICES = "mha:security:known_devices"
KEY_THREAT_NOTIFIED = "mha:security:notified:"


class ThreatAssessment:
    """Proaktive Sicherheitsanalyse fuer das Smart Home."""

    def __init__(self, ha_client: HomeAssistantClient):
        self.ha = ha_client
        self.redis: Optional[aioredis.Redis] = None

        security_cfg = yaml_config.get("security", {})
        self.enabled = security_cfg.get("threat_assessment", True)
        self.night_start = security_cfg.get("night_start_hour", 23)
        self.night_end = security_cfg.get("night_end_hour", 6)

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis."""
        self.redis = redis_client
        logger.info("ThreatAssessment initialisiert (enabled: %s)", self.enabled)

    async def assess_threats(self) -> list[dict]:
        """Fuehrt eine Sicherheitsbewertung durch.

        Returns:
            Liste von erkannten Bedrohungen/Warnungen
        """
        if not self.enabled:
            return []

        states = await self.ha.get_states()
        if not states:
            return []

        threats = []
        now = datetime.now()
        is_night = now.hour >= self.night_start or now.hour < self.night_end

        # 1. Naechtliche Bewegung wenn alle schlafen
        if is_night:
            night_threats = await self._check_night_motion(states)
            threats.extend(night_threats)

        # 2. Offene Fenster/Tueren bei Sturm
        storm_threats = self._check_storm_windows(states)
        threats.extend(storm_threats)

        # 3. Tuer offen + niemand zuhause
        empty_threats = self._check_doors_nobody_home(states)
        threats.extend(empty_threats)

        # 4. Unbekannte Geraete im Netzwerk
        device_threats = await self._check_unknown_devices(states)
        threats.extend(device_threats)

        return threats

    async def _check_night_motion(self, states: list[dict]) -> list[dict]:
        """Prueft ob nachts Bewegung erkannt wird obwohl alle schlafen."""
        threats = []

        # Sind alle zuhause und es ist Nacht?
        all_home = True
        for s in states:
            if s.get("entity_id", "").startswith("person."):
                if s.get("state") != "home":
                    all_home = False
                    break

        if not all_home:
            return []

        # Bewegung in "oeffentlichen" Bereichen
        suspicious_areas = ["flur", "eingang", "garage", "keller", "garten"]
        for s in states:
            eid = s.get("entity_id", "")
            if not eid.startswith("binary_sensor.") or "motion" not in eid:
                continue
            if s.get("state") != "on":
                continue

            area = eid.split(".", 1)[1].lower()
            if any(sa in area for sa in suspicious_areas):
                key = f"night_motion_{eid}"
                if not await self._was_notified(key, cooldown_minutes=30):
                    await self._mark_notified(key, cooldown_minutes=30)
                    friendly = s.get("attributes", {}).get("friendly_name", eid)
                    threats.append({
                        "type": "night_motion",
                        "message": f"Naechtliche Bewegung erkannt: {friendly}. Alle Bewohner sollten schlafen.",
                        "urgency": "high",
                        "entity": eid,
                    })

        return threats

    def _check_storm_windows(self, states: list[dict]) -> list[dict]:
        """Prueft ob Fenster bei Sturmwarnung offen sind."""
        threats = []

        # Windgeschwindigkeit pruefen
        wind_speed = None
        for s in states:
            if s.get("entity_id", "").startswith("weather."):
                wind_speed = s.get("attributes", {}).get("wind_speed")
                break

        if not wind_speed or float(wind_speed) < 50:  # < 50 km/h = kein Sturm
            return []

        # Offene Fenster bei Sturm
        open_windows = []
        for s in states:
            eid = s.get("entity_id", "")
            if ("window" in eid or "fenster" in eid) and s.get("state") == "on":
                friendly = s.get("attributes", {}).get("friendly_name", eid)
                open_windows.append(friendly)

        if open_windows:
            threats.append({
                "type": "storm_windows",
                "message": f"Sturmwarnung ({wind_speed} km/h)! {len(open_windows)} Fenster noch offen: {', '.join(open_windows)}.",
                "urgency": "high",
            })

        return threats

    def _check_doors_nobody_home(self, states: list[dict]) -> list[dict]:
        """Prueft ob Tueren offen sind wenn niemand zuhause ist."""
        threats = []

        # Ist jemand zuhause?
        anyone_home = False
        for s in states:
            if s.get("entity_id", "").startswith("person."):
                if s.get("state") == "home":
                    anyone_home = True
                    break

        if anyone_home:
            return []

        # Offene Tueren
        for s in states:
            eid = s.get("entity_id", "")
            if ("door" in eid or "tuer" in eid) and eid.startswith("binary_sensor."):
                if s.get("state") == "on":
                    friendly = s.get("attributes", {}).get("friendly_name", eid)
                    threats.append({
                        "type": "door_open_empty",
                        "message": f"{friendly} ist offen und niemand ist zuhause!",
                        "urgency": "critical",
                    })

        # Entriegelte Schloesser
        for s in states:
            eid = s.get("entity_id", "")
            if eid.startswith("lock.") and s.get("state") == "unlocked":
                friendly = s.get("attributes", {}).get("friendly_name", eid)
                threats.append({
                    "type": "lock_open_empty",
                    "message": f"{friendly} ist entriegelt und niemand ist zuhause!",
                    "urgency": "critical",
                })

        return threats

    async def _check_unknown_devices(self, states: list[dict]) -> list[dict]:
        """Prueft ob unbekannte Geraete im Netzwerk sind."""
        threats = []
        if not self.redis:
            return []

        # Device Tracker Entities
        tracked_devices = []
        for s in states:
            eid = s.get("entity_id", "")
            if eid.startswith("device_tracker.") and s.get("state") == "home":
                tracked_devices.append(eid)

        if not tracked_devices:
            return []

        # Bekannte Geraete aus Redis holen
        known_raw = await self.redis.smembers(KEY_KNOWN_DEVICES)
        known = {d.decode() if isinstance(d, bytes) else d for d in known_raw} if known_raw else set()

        # Beim ersten Mal: Alle aktuellen Geraete als "bekannt" speichern
        if not known:
            for device in tracked_devices:
                await self.redis.sadd(KEY_KNOWN_DEVICES, device)
            return []

        # Unbekannte Geraete
        for device in tracked_devices:
            if device not in known:
                key = f"unknown_device_{device}"
                if not await self._was_notified(key, cooldown_minutes=60):
                    await self._mark_notified(key, cooldown_minutes=60)
                    friendly = None
                    for s in states:
                        if s.get("entity_id") == device:
                            friendly = s.get("attributes", {}).get("friendly_name")
                            break
                    name = friendly or device
                    threats.append({
                        "type": "unknown_device",
                        "message": f"Unbekanntes Geraet im Netzwerk: {name}.",
                        "urgency": "medium",
                        "entity": device,
                    })

        return threats

    async def _was_notified(self, key: str, cooldown_minutes: int = 30) -> bool:
        if not self.redis:
            return False
        val = await self.redis.get(f"{KEY_THREAT_NOTIFIED}{key}")
        return val is not None

    async def _mark_notified(self, key: str, cooldown_minutes: int = 30):
        if not self.redis:
            return
        await self.redis.setex(f"{KEY_THREAT_NOTIFIED}{key}", cooldown_minutes * 60, "1")
