"""
Threat Assessment - Proaktive Sicherheits-Analyse.

Features:
- Ungewöhnliche Bewegung nachts (wenn alle schlafen)
- Offene Fenster bei Sturmwarnung
- Unbekannte Geräte im Netzwerk (via HA device_tracker)
- Tür offen + niemand zuhause
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
    """Proaktive Sicherheitsanalyse für das Smart Home."""

    def __init__(self, ha_client: HomeAssistantClient):
        self.ha = ha_client
        self.redis: Optional[aioredis.Redis] = None

        security_cfg = yaml_config.get("security", {})
        self.enabled = security_cfg.get("threat_assessment", True)
        self.night_start = security_cfg.get("night_start_hour", 23)
        self.night_end = security_cfg.get("night_end_hour", 6)

        # Bekannte Geräte-Patterns: Entity-IDs die diese Substrings enthalten
        # werden nie als "unbekannt" gemeldet (z.B. "ps5", "amazon", "watch")
        self._known_device_patterns = [
            p.lower() for p in security_cfg.get("known_device_patterns", [])
        ]

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis."""
        self.redis = redis_client
        logger.info("ThreatAssessment initialisiert (enabled: %s)", self.enabled)

    @staticmethod
    def _get_weather_context(states: list[dict]) -> dict:
        """Extrahiert Wetter-Kontext für Fehlalarm-Filterung."""
        for s in states:
            if s.get("entity_id", "").startswith("weather."):
                attrs = s.get("attributes", {})
                condition = s.get("state", "")
                try:
                    wind = float(attrs.get("wind_speed", 0))
                except (ValueError, TypeError):
                    wind = 0.0
                rain_conditions = {"rainy", "pouring", "hail", "lightning-rainy"}
                return {
                    "condition": condition,
                    "wind_speed": wind,
                    "is_stormy": wind > 50 or condition in rain_conditions,
                    "is_rainy": condition in rain_conditions,
                }
        return {"condition": "", "wind_speed": 0, "is_stormy": False, "is_rainy": False}

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

        weather_ctx = self._get_weather_context(states)
        threats = []
        now = datetime.now()
        is_night = now.hour >= self.night_start or now.hour < self.night_end

        # 1. Nächtliche Bewegung wenn alle schlafen
        if is_night:
            night_threats = await self._check_night_motion(states, weather_ctx)
            threats.extend(night_threats)

        # 2. Offene Fenster/Türen bei Sturm
        storm_threats = self._check_storm_windows(states)
        threats.extend(storm_threats)

        # 3. Tür offen + niemand zuhause
        empty_threats = self._check_doors_nobody_home(states)
        threats.extend(empty_threats)

        # 4. Unbekannte Geräte im Netzwerk
        device_threats = await self._check_unknown_devices(states)
        threats.extend(device_threats)

        # 5. Rauchmelder / Feueralarm
        smoke_threats = self._check_smoke_fire(states)
        threats.extend(smoke_threats)

        # 6. Wasserleck-Sensoren
        water_threats = self._check_water_leak(states)
        threats.extend(water_threats)

        return threats

    async def _check_night_motion(self, states: list[dict], weather_ctx: dict = None) -> list[dict]:
        """Prueft ob nachts Bewegung erkannt wird obwohl alle schlafen.

        Wetter-Filter: Outdoor-Sensoren (garten, terrasse, einfahrt) werden bei
        starkem Wind/Regen unterdrueckt (Fehlalarme durch Aeste, Regen etc.).
        """
        threats = []
        weather_ctx = weather_ctx or {}

        # Sind alle zuhause und es ist Nacht?
        all_home = True
        for s in states:
            if s.get("entity_id", "").startswith("person."):
                if s.get("state") != "home":
                    all_home = False
                    break

        if not all_home:
            return []

        # Outdoor-Bereiche die bei schlechtem Wetter Fehlalarme ausloesen
        outdoor_areas = {"garten", "terrasse", "einfahrt", "carport", "balkon", "hof"}
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
                # Wetter-Filter: Outdoor-Sensoren bei Sturm/Regen unterdruecken
                is_outdoor = any(oa in area for oa in outdoor_areas)
                if is_outdoor and weather_ctx.get("is_stormy"):
                    logger.debug(
                        "Nacht-Bewegung unterdrueckt (Wetter-Filter): %s (Wind: %.0f, %s)",
                        eid, weather_ctx.get("wind_speed", 0), weather_ctx.get("condition", ""),
                    )
                    continue

                key = f"night_motion_{eid}"
                if not await self._was_notified(key, cooldown_minutes=30):
                    await self._mark_notified(key, cooldown_minutes=30)
                    friendly = s.get("attributes", {}).get("friendly_name", eid)
                    threats.append({
                        "type": "night_motion",
                        "message": f"Nächtliche Bewegung erkannt: {friendly}. Alle Bewohner sollten schlafen.",
                        "urgency": "high",
                        "entity": eid,
                    })

        return threats

    def _check_storm_windows(self, states: list[dict]) -> list[dict]:
        """Prueft ob Fenster bei Sturmwarnung offen sind."""
        threats = []

        # Windgeschwindigkeit prüfen
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
        wind_threshold = float(yaml_config.get("weather_warnings", {}).get("wind_speed_high", 60))
        if wind_speed_val < wind_threshold:  # kein Sturm
            return []

        # Offene Fenster/Türen bei Sturm — kategorisiert (Tore separat)
        from .function_calling import is_window_or_door, get_opening_type
        open_windows = []
        open_gates = []
        for s in states:
            eid = s.get("entity_id", "")
            if not is_window_or_door(eid, s):
                continue
            if s.get("state") != "on":
                continue
            friendly = s.get("attributes", {}).get("friendly_name", eid)
            if get_opening_type(eid, s) == "gate":
                open_gates.append(friendly)
            else:
                open_windows.append(friendly)

        if open_windows:
            threats.append({
                "type": "storm_windows",
                "message": f"Sturmwarnung ({wind_speed_val:.0f} km/h)! {len(open_windows)} Fenster/Türen noch offen: {', '.join(open_windows)}.",
                "urgency": "high",
            })
        if open_gates:
            threats.append({
                "type": "storm_gates",
                "message": f"Sturmwarnung ({wind_speed_val:.0f} km/h)! {len(open_gates)} Tore offen: {', '.join(open_gates)}.",
                "urgency": "high",
            })

        return threats

    def _check_doors_nobody_home(self, states: list[dict]) -> list[dict]:
        """Prueft ob Türen offen sind wenn niemand zuhause ist."""
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

        # Offene Türen/Fenster/Tore — konsistent mit is_window_or_door()
        from .function_calling import is_window_or_door, get_opening_type
        for s in states:
            eid = s.get("entity_id", "")
            if not is_window_or_door(eid, s):
                continue
            if s.get("state") != "on":
                continue
            friendly = s.get("attributes", {}).get("friendly_name", eid)
            opening_type = get_opening_type(eid, s)
            type_label = {"door": "Tür", "gate": "Tor", "window": "Fenster"}.get(opening_type, "Fenster")
            threats.append({
                "type": f"{opening_type}_open_empty",
                "message": f"{friendly} ({type_label}) ist offen und niemand ist zuhause!",
                "urgency": "critical",
            })

        # Entriegelte Schlösser
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
        """Prueft ob unbekannte Geräte im Netzwerk sind."""
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

        # Bekannte Geräte aus Redis holen
        known_raw = await self.redis.smembers(KEY_KNOWN_DEVICES)
        known = {d.decode() if isinstance(d, bytes) else d for d in known_raw} if known_raw else set()

        # Beim ersten Mal: Alle aktuellen Geräte als "bekannt" speichern
        if not known:
            for device in tracked_devices:
                await self.redis.sadd(KEY_KNOWN_DEVICES, device)
            return []

        # Unbekannte Geräte
        for device in tracked_devices:
            if device not in known:
                # Config-Allowlist: Patterns wie "ps5", "amazon", "watch" überspringen
                device_lower = device.lower()
                if any(pat in device_lower for pat in self._known_device_patterns):
                    # Auto-learn: Als bekannt speichern damit kein erneuter Check
                    await self.redis.sadd(KEY_KNOWN_DEVICES, device)
                    logger.debug("Gerät per Allowlist akzeptiert: %s", device)
                    continue

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
                        "message": f"Unbekanntes Gerät im Netzwerk: {name}.",
                        "urgency": "medium",
                        "entity": device,
                    })

        return threats

    def _check_smoke_fire(self, states: list[dict]) -> list[dict]:
        """Prueft Rauchmelder und Feuer-Sensoren.

        Nutzt primaer device_class (smoke, carbon_monoxide) für zuverlaessige
        Erkennung. Keyword-Fallback nur für echte Alarm-Sensoren, NICHT für
        CO2-Luftqualitaetssensoren (die sind kein Notfall).
        """
        threats = []
        # device_class Werte die HA für echte Alarm-Sensoren verwendet
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
                    "message": f"ALARM: {friendly} hat ausgelöst! Sofortige Pruefung erforderlich!",
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
                    "message": f"Wasserleck erkannt: {friendly}! Bitte umgehend prüfen.",
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
            return {"score": -1, "level": "unknown", "details": ["Keine HA-Daten verfügbar"]}

        score = 100
        details = []

        # Türen/Fenster/Tore prüfen — konsistent mit is_window_or_door()
        from .function_calling import is_window_or_door, get_opening_type
        open_doors = 0
        open_windows = 0
        open_gates = 0
        for s in states:
            eid = s.get("entity_id", "")
            if not is_window_or_door(eid, s):
                continue
            if s.get("state") != "on":
                continue
            opening_type = get_opening_type(eid, s)
            if opening_type == "gate":
                open_gates += 1
            elif opening_type == "door":
                open_doors += 1
            else:
                open_windows += 1

        if open_doors > 0:
            score -= open_doors * 15
            details.append(f"{open_doors} Tür(en) offen")
        if open_windows > 0:
            score -= open_windows * 5
            details.append(f"{open_windows} Fenster offen")
        if open_gates > 0:
            score -= open_gates * 10
            details.append(f"{open_gates} Tor(e) offen")

        # Schlösser prüfen
        unlocked = 0
        for s in states:
            if s.get("entity_id", "").startswith("lock.") and s.get("state") == "unlocked":
                unlocked += 1
        if unlocked > 0:
            score -= unlocked * 20
            details.append(f"{unlocked} Schloss/Schlösser entriegelt")

        # Rauchmelder prüfen
        smoke_active = any(
            s.get("state") == "on"
            and s.get("entity_id", "").startswith("binary_sensor.")
            and any(kw in s.get("entity_id", "").lower() for kw in ["smoke", "rauch", "fire", "feuer"])
            for s in states
        )
        if smoke_active:
            score -= 50
            details.append("Rauchmelder aktiv!")

        # Wasserleck prüfen
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
        """Fuehrt Eskalations-Aktionen für kritische Bedrohungen aus.

        F-009: Nur Benachrichtigungs-Aktionen (Lichter) werden automatisch ausgeführt.
        Physische Sicherheits-Aktionen (Schlösser) erfordern Owner-Bestaetigung
        die über den Notification-Callback angefordert wird.

        Args:
            threat: Bedrohungs-Dict aus assess_threats()

        Returns:
            Liste der ausgeführten Aktionen
        """
        actions_taken = []
        threat_type = threat.get("type", "")
        urgency = threat.get("urgency", "medium")

        if urgency != "critical":
            return actions_taken

        # Bei Rauch/Feuer: Alle Lichter an (sicher — keine Bestaetigung noetig)
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

        # F-009: Bei offenen Türen + niemand da: NUR WARNUNG, keine Auto-Verriegelung
        # Automatisches Verriegeln kann Bewohner aussperren bei Fehlalarmen
        if threat_type in ("door_open_empty", "lock_open_empty"):
            entity = threat.get("entity", "")
            if entity.startswith("lock."):
                logger.warning(
                    "Bedrohung erkannt: %s offen bei leerem Haus. "
                    "Automatische Verriegelung deaktiviert (F-009). "
                    "Benachrichtigung wird gesendet.", entity,
                )
                actions_taken.append(
                    f"WARNUNG: {entity} ist offen bei leerem Haus — "
                    f"bitte manuell verriegeln oder per Sprache bestätigen"
                )

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
