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

        # 5. Rauchmelder / Feueralarm
        smoke_threats = self._check_smoke_fire(states)
        threats.extend(smoke_threats)

        # 6. Wasserleck-Sensoren
        water_threats = self._check_water_leak(states)
        threats.extend(water_threats)

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

        if not wind_speed:
            return []
        try:
            wind_speed_val = float(wind_speed)
        except (ValueError, TypeError):
            return []
        if wind_speed_val < 50:  # < 50 km/h = kein Sturm
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
                "message": f"Sturmwarnung ({wind_speed_val:.0f} km/h)! {len(open_windows)} Fenster noch offen: {', '.join(open_windows)}.",
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

    def _check_smoke_fire(self, states: list[dict]) -> list[dict]:
        """Prueft Rauchmelder und Feuer-Sensoren.

        Nutzt primaer device_class (smoke, carbon_monoxide) fuer zuverlaessige
        Erkennung. Keyword-Fallback nur fuer echte Alarm-Sensoren, NICHT fuer
        CO2-Luftqualitaetssensoren (die sind kein Notfall).
        """
        threats = []
        # device_class Werte die HA fuer echte Alarm-Sensoren verwendet
        alarm_device_classes = {"smoke", "carbon_monoxide", "gas"}
        # Keywords nur als Fallback wenn kein device_class gesetzt
        smoke_keywords = ["smoke", "rauch", "fire", "feuer", "kohlenmonoxid", "carbon_monoxide"]
        # Explizit KEINE CO2-Sensoren — das sind Luftqualitaets-Sensoren, kein Notfall
        co2_exclude = ["co2", "kohlendioxid", "air_quality", "luftqualitaet", "iaq"]

        for s in states:
            eid = s.get("entity_id", "")
            if not eid.startswith("binary_sensor."):
                continue
            if s.get("state") != "on":
                continue

            attrs = s.get("attributes", {})
            device_class = (attrs.get("device_class") or "").lower()
            eid_lower = eid.lower()
            friendly = attrs.get("friendly_name", eid)

            # Methode 1: device_class (zuverlaessig)
            is_alarm = device_class in alarm_device_classes

            # Methode 2: Keyword-Fallback (nur wenn kein device_class)
            if not is_alarm and not device_class:
                if any(kw in eid_lower for kw in smoke_keywords):
                    # CO2-Sensoren ausschliessen
                    if not any(ex in eid_lower for ex in co2_exclude):
                        is_alarm = True

            if is_alarm:
                logger.warning("Rauchmelder/Gas-Alarm: %s (%s, device_class=%s)",
                               friendly, eid, device_class or "none")
                threats.append({
                    "type": "smoke_fire",
                    "message": f"ALARM: {friendly} hat ausgeloest! Sofortige Pruefung erforderlich!",
                    "urgency": "critical",
                    "entity": eid,
                })

        return threats

    def _check_water_leak(self, states: list[dict]) -> list[dict]:
        """Prueft Wasserleck-Sensoren (Waschmaschine, Bad, Keller)."""
        threats = []
        water_keywords = ["water", "wasser", "leak", "leck", "moisture", "feucht", "flood"]

        for s in states:
            eid = s.get("entity_id", "")
            if not eid.startswith("binary_sensor."):
                continue
            if s.get("state") != "on":
                continue

            eid_lower = eid.lower()
            if any(kw in eid_lower for kw in water_keywords):
                friendly = s.get("attributes", {}).get("friendly_name", eid)
                threats.append({
                    "type": "water_leak",
                    "message": f"Wasserleck erkannt: {friendly}! Bitte umgehend pruefen.",
                    "urgency": "critical",
                    "entity": eid,
                })

        return threats

    async def get_security_score(self) -> dict:
        """Berechnet einen Sicherheits-Score (0-100) basierend auf aktuellem Zustand.

        Returns:
            Dict mit score, level, details
        """
        if not self.enabled:
            return {"score": -1, "level": "disabled", "details": []}

        states = await self.ha.get_states()
        if not states:
            return {"score": -1, "level": "unknown", "details": ["Keine HA-Daten verfuegbar"]}

        score = 100
        details = []

        # Tueren/Fenster pruefen
        open_doors = 0
        open_windows = 0
        for s in states:
            eid = s.get("entity_id", "")
            if not eid.startswith("binary_sensor."):
                continue
            if s.get("state") != "on":
                continue
            if "door" in eid or "tuer" in eid:
                open_doors += 1
            elif "window" in eid or "fenster" in eid:
                open_windows += 1

        if open_doors > 0:
            score -= open_doors * 15
            details.append(f"{open_doors} Tuer(en) offen")
        if open_windows > 0:
            score -= open_windows * 5
            details.append(f"{open_windows} Fenster offen")

        # Schloesser pruefen
        unlocked = 0
        for s in states:
            if s.get("entity_id", "").startswith("lock.") and s.get("state") == "unlocked":
                unlocked += 1
        if unlocked > 0:
            score -= unlocked * 20
            details.append(f"{unlocked} Schloss/Schloesser entriegelt")

        # Rauchmelder pruefen
        smoke_active = any(
            s.get("state") == "on"
            and s.get("entity_id", "").startswith("binary_sensor.")
            and any(kw in s.get("entity_id", "").lower() for kw in ["smoke", "rauch", "fire", "feuer"])
            for s in states
        )
        if smoke_active:
            score -= 50
            details.append("Rauchmelder aktiv!")

        # Wasserleck pruefen
        water_active = any(
            s.get("state") == "on"
            and s.get("entity_id", "").startswith("binary_sensor.")
            and any(kw in s.get("entity_id", "").lower() for kw in ["water", "wasser", "leak", "leck"])
            for s in states
        )
        if water_active:
            score -= 30
            details.append("Wasserleck erkannt!")

        # Nachtzeit + niemand zuhause
        now = datetime.now()
        is_night = now.hour >= self.night_start or now.hour < self.night_end
        anyone_home = any(
            s.get("entity_id", "").startswith("person.") and s.get("state") == "home"
            for s in states
        )
        if is_night and not anyone_home:
            score -= 10
            details.append("Nacht + niemand zuhause")

        score = max(0, score)

        if score >= 90:
            level = "excellent"
        elif score >= 70:
            level = "good"
        elif score > 50:
            level = "warning"
        else:
            level = "critical"

        if not details:
            details.append("Alles in Ordnung")

        return {"score": score, "level": level, "details": details}

    async def escalate_threat(self, threat: dict) -> list[str]:
        """Fuehrt Eskalations-Aktionen fuer kritische Bedrohungen aus.

        Args:
            threat: Bedrohungs-Dict aus assess_threats()

        Returns:
            Liste der ausgefuehrten Aktionen
        """
        actions_taken = []
        threat_type = threat.get("type", "")
        urgency = threat.get("urgency", "medium")

        if urgency != "critical":
            return actions_taken

        # Bei Rauch/Feuer: Alle Lichter an
        if threat_type == "smoke_fire":
            try:
                lights = await self.ha.get_states()
                for s in (lights or []):
                    eid = s.get("entity_id", "")
                    if eid.startswith("light.") and s.get("state") == "off":
                        await self.ha.call_service("light", "turn_on", {"entity_id": eid})
                actions_taken.append("Alle Lichter eingeschaltet")
            except Exception as e:
                logger.warning("Eskalation Lichter fehlgeschlagen: %s", e)

        # Bei offenen Tueren + niemand da: Schloesser verriegeln
        if threat_type in ("door_open_empty", "lock_open_empty"):
            entity = threat.get("entity", "")
            if entity.startswith("lock."):
                try:
                    await self.ha.call_service("lock", "lock", {"entity_id": entity})
                    actions_taken.append(f"{entity} verriegelt")
                except Exception as e:
                    logger.warning("Eskalation Schloss fehlgeschlagen: %s", e)

        return actions_taken

    async def _was_notified(self, key: str, cooldown_minutes: int = 30) -> bool:
        if not self.redis:
            return False
        val = await self.redis.get(f"{KEY_THREAT_NOTIFIED}{key}")
        return val is not None

    async def _mark_notified(self, key: str, cooldown_minutes: int = 30):
        if not self.redis:
            return
        await self.redis.setex(f"{KEY_THREAT_NOTIFIED}{key}", cooldown_minutes * 60, "1")
