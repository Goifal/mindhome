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

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import redis.asyncio as aioredis

from .config import yaml_config

_LOCAL_TZ = ZoneInfo(yaml_config.get("timezone", "Europe/Berlin"))
from .ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)

KEY_KNOWN_DEVICES = "mha:security:known_devices"
KEY_THREAT_NOTIFIED = "mha:security:notified:"


class ThreatAssessment:
    """Proaktive Sicherheitsanalyse für das Smart Home."""

    # Strukturierte Notfall-Playbooks für verschiedene Szenarien.
    # Jeder Schritt hat eine action (Callable-Name), Beschreibung und Priorität.
    EMERGENCY_PLAYBOOKS: dict[str, dict] = {
        "power_outage": {
            "name": "Stromausfall",
            "urgency": "critical",
            "steps": [
                {
                    "step": 1,
                    "action": "check_battery_systems",
                    "description": "Prüfen welche Systeme noch online sind (batteriebetrieben)",
                    "ha_actions": [],  # Nur Status-Abfrage, keine Aktionen
                },
                {
                    "step": 2,
                    "action": "notify_all_persons",
                    "description": "Alle Personen per Telefon benachrichtigen (Push-Notification)",
                    "ha_actions": [{"service": "notify", "action": "notify", "data_template": "power_outage"}],
                },
                {
                    "step": 3,
                    "action": "activate_emergency_lighting",
                    "description": "Notbeleuchtung aktivieren falls verfügbar",
                    "ha_actions": [{"service": "light", "action": "turn_on", "entity_filter": "notlicht|emergency"}],
                },
                {
                    "step": 4,
                    "action": "secure_garage_doors",
                    "description": "Offene Garagentore/Einfahrtstore sichern falls möglich",
                    "ha_actions": [{"service": "cover", "action": "close_cover", "entity_filter": "garage|tor|gate"}],
                },
                {
                    "step": 5,
                    "action": "log_incident",
                    "description": "Vorfall mit Zeitstempel protokollieren",
                    "ha_actions": [],
                },
            ],
        },
        "water_damage": {
            "name": "Wasserschaden",
            "urgency": "critical",
            "steps": [
                {
                    "step": 1,
                    "action": "identify_water_source",
                    "description": "Betroffenen Bereich identifizieren (welcher Wassersensor hat ausgelöst)",
                    "ha_actions": [],  # Kontext-Auswertung aus trigger_context
                },
                {
                    "step": 2,
                    "action": "critical_alert_all",
                    "description": "Kritischer Alarm an alle Personen",
                    "ha_actions": [{"service": "notify", "action": "notify", "data_template": "water_damage"}],
                },
                {
                    "step": 3,
                    "action": "close_water_valve",
                    "description": "Wasserventil schließen falls Smart-Ventil vorhanden",
                    "ha_actions": [{"service": "valve", "action": "close_valve", "entity_filter": "water|wasser"}],
                },
                {
                    "step": 4,
                    "action": "disable_electrical_circuits",
                    "description": "Betroffene Stromkreise abschalten falls Smart-Breaker vorhanden",
                    "ha_actions": [{"service": "switch", "action": "turn_off", "entity_filter": "breaker|sicherung"}],
                },
                {
                    "step": 5,
                    "action": "camera_snapshot",
                    "description": "Kamera-Snapshot zur Dokumentation falls verfügbar",
                    "ha_actions": [{"service": "camera", "action": "snapshot", "entity_filter": "camera."}],
                },
                {
                    "step": 6,
                    "action": "suggest_emergency_service",
                    "description": "Vorschlag: Notdienst anrufen",
                    "ha_actions": [],  # Nur Hinweis an Nutzer
                    "user_message": "Bitte Notdienst für Wasserschaden kontaktieren!",
                },
            ],
        },
        "break_in": {
            "name": "Einbruch",
            "urgency": "critical",
            "steps": [
                {
                    "step": 1,
                    "action": "activate_all_lights",
                    "description": "Alle Lichter einschalten (Abschreckung)",
                    "ha_actions": [{"service": "light", "action": "turn_on", "entity_filter": "light."}],
                },
                {
                    "step": 2,
                    "action": "silent_alarm_owner",
                    "description": "Stiller Alarm an Eigentümer (NICHT über Lautsprecher!)",
                    "ha_actions": [{"service": "notify", "action": "notify", "data_template": "break_in_silent"}],
                    "silent": True,  # Keine Sprachausgabe über Lautsprecher
                },
                {
                    "step": 3,
                    "action": "camera_snapshots_entries",
                    "description": "Kamera-Snapshots aller Eingangsbereiche",
                    "ha_actions": [{"service": "camera", "action": "snapshot", "entity_filter": "camera."}],
                },
                {
                    "step": 4,
                    "action": "lock_all_smart_locks",
                    "description": "Alle Smart-Locks verriegeln",
                    "ha_actions": [{"service": "lock", "action": "lock", "entity_filter": "lock."}],
                },
                {
                    "step": 5,
                    "action": "record_incident",
                    "description": "Zeitstempel + auslösenden Sensor aufzeichnen",
                    "ha_actions": [],
                },
            ],
        },
        "fire_smoke": {
            "name": "Brand/Rauch",
            "urgency": "critical",
            "steps": [
                {
                    "step": 1,
                    "action": "all_lights_on",
                    "description": "Alle Lichter an (Fluchtweg beleuchten)",
                    "ha_actions": [{"service": "light", "action": "turn_on", "entity_filter": "light."}],
                },
                {
                    "step": 2,
                    "action": "open_all_covers",
                    "description": "Alle Rollläden/Abdeckungen öffnen (Fluchtweg freihalten)",
                    "ha_actions": [{"service": "cover", "action": "open_cover", "entity_filter": "cover."}],
                },
                {
                    "step": 3,
                    "action": "critical_alert_location",
                    "description": "Kritischer Alarm mit Raumangabe",
                    "ha_actions": [{"service": "notify", "action": "notify", "data_template": "fire_smoke"}],
                },
                {
                    "step": 4,
                    "action": "ventilation_off",
                    "description": "Lüftung ausschalten (Rauchausbreitung verhindern)",
                    "ha_actions": [{"service": "fan", "action": "turn_off", "entity_filter": "fan.|climate."}],
                },
                {
                    "step": 5,
                    "action": "suggest_fire_department",
                    "description": "Hinweis: Feuerwehr 112 anrufen",
                    "ha_actions": [],
                    "user_message": "SOFORT Feuerwehr anrufen: 112!",
                },
            ],
        },
        "medical_emergency": {
            "name": "Medizinischer Notfall",
            "urgency": "critical",
            "steps": [
                {
                    "step": 1,
                    "action": "ask_confirmation",
                    "description": "Bestätigung einholen: 'Brauchst du Hilfe?'",
                    "ha_actions": [],
                    "user_message": "Brauchst du Hilfe?",
                    "requires_confirmation": True,
                },
                {
                    "step": 2,
                    "action": "call_emergency_contact",
                    "description": "Notfallkontakt anrufen",
                    "ha_actions": [{"service": "notify", "action": "notify", "data_template": "medical_emergency"}],
                },
                {
                    "step": 3,
                    "action": "unlock_front_door",
                    "description": "Haustür für Rettungsdienst entriegeln",
                    "ha_actions": [{"service": "lock", "action": "unlock", "entity_filter": "haustuer|front_door|eingang"}],
                },
                {
                    "step": 4,
                    "action": "pathway_lights_on",
                    "description": "Alle Weg-Beleuchtungen einschalten",
                    "ha_actions": [{"service": "light", "action": "turn_on", "entity_filter": "light."}],
                },
                {
                    "step": 5,
                    "action": "provide_address_info",
                    "description": "Adresse + Situationsbeschreibung an Notfallkontakt übermitteln",
                    "ha_actions": [{"service": "notify", "action": "notify", "data_template": "medical_address"}],
                },
            ],
        },
    }

    def __init__(self, ha_client: HomeAssistantClient):
        self.ha = ha_client
        self.redis: Optional[aioredis.Redis] = None
        # Laufzeitschutz: Verhindert parallele Ausführung desselben Playbooks
        self._running_playbooks: set[str] = set()

        security_cfg = yaml_config.get("security", {})
        _raw_enabled = security_cfg.get("threat_assessment", True)
        self.enabled = bool(_raw_enabled) and str(_raw_enabled).lower() not in ("false", "0", "no", "off")
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

        try:
            states = await asyncio.wait_for(self.ha.get_states(), timeout=15)
        except asyncio.TimeoutError:
            logger.warning("get_states() timed out in threat assessment")
            return []
        if not states:
            return []

        weather_ctx = self._get_weather_context(states)
        threats = []
        now = datetime.now(_LOCAL_TZ)
        is_night = now.hour >= self.night_start or now.hour < self.night_end

        # 1. Nächtliche Bewegung wenn alle schlafen
        if is_night:
            night_threats = await self._check_night_motion(states, weather_ctx)
            threats.extend(night_threats)

        # 2. Offene Fenster/Türen bei Sturm
        storm_threats = self._check_storm_windows(states, weather_ctx)
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

    def _check_storm_windows(self, states: list[dict], weather_ctx: dict = None) -> list[dict]:
        """Prueft ob Fenster bei Sturmwarnung offen sind."""
        threats = []

        # Windgeschwindigkeit aus bereits extrahiertem Wetter-Kontext verwenden
        if weather_ctx:
            wind_speed_val = weather_ctx.get("wind_speed", 0)
        else:
            wind_speed = None
            for s in states:
                if s.get("entity_id", "").startswith("weather."):
                    wind_speed = s.get("attributes", {}).get("wind_speed")
                    break
            if wind_speed is None:
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
        """Prueft ob unbekannte Geräte im Netzwerk sind.

        Im Gaeste-Modus werden keine unbekannten Geräte gemeldet,
        da Gaeste-Handys im WLAN erwartet sind.
        """
        threats = []
        if not self.redis:
            return []

        # Gaeste-Modus: Keine Unknown-Device-Warnungen
        try:
            guest_val = await self.redis.get("mha:routine:guest_mode")
            if guest_val is not None:
                if (guest_val.decode() if isinstance(guest_val, bytes) else guest_val) == "active":
                    return []
        except Exception as e:
            logger.debug("Unhandled: %s", e)
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

        try:
            states = await asyncio.wait_for(self.ha.get_states(), timeout=10.0)
        except asyncio.TimeoutError:
            return {"score": -1, "level": "unknown", "details": ["HA-Timeout (10s)"]}
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
        now = datetime.now(_LOCAL_TZ)
        is_night = now.hour >= self.night_start or now.hour < self.night_end
        anyone_home = any(
            s.get("entity_id", "").startswith("person.") and s.get("state") == "home"
            for s in states
        )
        if is_night and not anyone_home:
            score -= 10
            details.append("Nacht + niemand zuhause")

        # Device-Dependency-Konflikte: Compound-Severity
        try:
            from .state_change_log import StateChangeLog
            _state_dict = {
                s["entity_id"]: s.get("state", "")
                for s in states if "entity_id" in s
            }
            _scl = StateChangeLog.__new__(StateChangeLog)
            _conflicts = _scl.detect_conflicts(_state_dict)
            _active = [c for c in _conflicts if c.get("affected_active")]
            if _active:
                # Eskalierend: 1=-5, 2=-15, 3+=-25
                _n = len(_active)
                _penalty = 5 if _n == 1 else (15 if _n == 2 else 25)
                score -= _penalty
                _hints = [c.get("hint", "") for c in _active[:3]]
                details.append(f"Geraete-Konflikte ({_n}): {'; '.join(_hints)}")
        except Exception as _dep_err:
            logger.debug("Threat-Assessment Dependency-Check: %s", _dep_err)

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

        # Stufe 2: Rollladen/Covers schliessen bei Einbruch-Verdacht
        _dyn_cfg = yaml_config.get("dynamic_emergency", {})
        if _dyn_cfg.get("enabled", True) and threat_type in (
            "door_open_empty", "lock_open_empty", "glass_break", "intrusion",
        ):
            try:
                states = await self.ha.get_states()
                covers_closed = 0
                for s in (states or []):
                    eid = s.get("entity_id", "")
                    # Rollaeden schliessen (sicher, reversibel)
                    if eid.startswith("cover.") and s.get("state") == "open":
                        await self.ha.call_service("cover", "close_cover", {"entity_id": eid})
                        covers_closed += 1
                if covers_closed > 0:
                    actions_taken.append(f"{covers_closed} Rollaeden geschlossen")
            except Exception as e:
                logger.warning("Eskalation Covers fehlgeschlagen: %s", e)

            # Stufe 3: Sirene — NUR mit Bestaetigung (F-009 respektiert)
            _confirm_actions = _dyn_cfg.get("require_confirmation_for", ["lock", "siren"])
            if "siren" not in _confirm_actions:
                try:
                    for s in (states or []):
                        eid = s.get("entity_id", "")
                        if eid.startswith("siren.") and s.get("state") != "on":
                            await self.ha.call_service("siren", "turn_on", {"entity_id": eid})
                    actions_taken.append("Sirene aktiviert")
                except Exception as e:
                    logger.warning("Eskalation Sirene fehlgeschlagen: %s", e)
            else:
                actions_taken.append(
                    "WARNUNG: Sirene verfuegbar — Sprachbestaetigung erforderlich"
                )

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

    async def execute_playbook(
        self,
        scenario: str,
        trigger_context: dict,
        ha_client: HomeAssistantClient,
    ) -> list[dict]:
        """Führt ein Notfall-Playbook Schritt für Schritt aus.

        Sicherheitsprüfungen:
        - Verhindert parallele Ausführung desselben Szenarios
        - Jeder Schritt wird einzeln ausgeführt und protokolliert
        - Bei Fehlern wird der Schritt als fehlgeschlagen markiert,
          das Playbook läuft aber weiter (best-effort)

        Args:
            scenario: Szenario-Schlüssel (z.B. "fire_smoke", "break_in")
            trigger_context: Kontext des Auslösers (entity_id, room, timestamp etc.)
            ha_client: HomeAssistant-Client für Service-Aufrufe

        Returns:
            Liste der ausgeführten Schritte mit Erfolgs-/Fehlerstatus
        """
        playbook = self.EMERGENCY_PLAYBOOKS.get(scenario)
        if not playbook:
            logger.warning("Unbekanntes Notfall-Szenario: %s", scenario)
            return [{"step": 0, "action": "lookup", "success": False,
                      "error": f"Unbekanntes Szenario: {scenario}"}]

        # Schutz gegen parallele Ausführung desselben Playbooks
        if scenario in self._running_playbooks:
            logger.warning(
                "Playbook '%s' (%s) läuft bereits — doppelte Ausführung verhindert",
                playbook["name"], scenario,
            )
            return [{"step": 0, "action": "guard", "success": False,
                      "error": f"Playbook {scenario} läuft bereits"}]

        self._running_playbooks.add(scenario)
        executed_steps: list[dict] = []
        start_time = datetime.now(timezone.utc)

        logger.warning(
            "=== NOTFALL-PLAYBOOK GESTARTET: %s (%s) === Auslöser: %s",
            playbook["name"], scenario, trigger_context,
        )

        try:
            states = await asyncio.wait_for(ha_client.get_states(), timeout=10)
        except (asyncio.TimeoutError, Exception) as e:
            logger.error("Kann HA-States nicht laden für Playbook %s: %s", scenario, e)
            states = []

        for step_def in playbook["steps"]:
            step_num = step_def["step"]
            action_name = step_def["action"]
            description = step_def["description"]
            step_result = {
                "step": step_num,
                "action": action_name,
                "description": description,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "success": False,
                "details": [],
            }

            logger.info(
                "Playbook %s — Schritt %d: %s", playbook["name"], step_num, description,
            )

            try:
                # Bestätigungs-Schritte werden übersprungen (async UI nötig)
                if step_def.get("requires_confirmation"):
                    step_result["success"] = True
                    step_result["details"].append(
                        f"Bestätigung angefordert: {step_def.get('user_message', '')}"
                    )
                    executed_steps.append(step_result)
                    continue

                # HA-Service-Aktionen ausführen
                ha_actions = step_def.get("ha_actions", [])
                if not ha_actions:
                    # Reiner Log-/Hinweis-Schritt (kein HA-Service-Aufruf)
                    user_msg = step_def.get("user_message")
                    if user_msg:
                        step_result["details"].append(f"Nutzerhinweis: {user_msg}")
                    # Logging-Schritte (z.B. log_incident, record_incident)
                    if "log" in action_name or "record" in action_name:
                        step_result["details"].append(
                            f"Vorfall protokolliert: {playbook['name']} um {start_time.isoformat()}, "
                            f"Auslöser: {trigger_context}"
                        )
                    # Identifikations-Schritte (Kontext-Auswertung)
                    if "identify" in action_name or "check" in action_name:
                        trigger_entity = trigger_context.get("entity_id", "unbekannt")
                        trigger_room = trigger_context.get("room", "unbekannt")
                        step_result["details"].append(
                            f"Quelle: {trigger_entity}, Raum: {trigger_room}"
                        )
                    step_result["success"] = True
                    executed_steps.append(step_result)
                    continue

                # HA-Service-Aufrufe ausführen
                for ha_action in ha_actions:
                    service_domain = ha_action["service"]
                    service_action = ha_action["action"]
                    entity_filter = ha_action.get("entity_filter", "")

                    # Passende Entities finden
                    matching_entities = []
                    if entity_filter and states:
                        filter_parts = [f.lower() for f in entity_filter.split("|")]
                        for s in states:
                            eid = s.get("entity_id", "").lower()
                            if any(fp in eid for fp in filter_parts):
                                matching_entities.append(s.get("entity_id"))

                    if not matching_entities:
                        step_result["details"].append(
                            f"Keine passenden Entities für Filter '{entity_filter}' gefunden"
                        )
                        # Kein Fehler — Gerät existiert einfach nicht im System
                        step_result["success"] = True
                        continue

                    # Service für jede passende Entity aufrufen
                    for entity_id in matching_entities:
                        try:
                            await ha_client.call_service(
                                service_domain,
                                service_action,
                                {"entity_id": entity_id},
                            )
                            step_result["details"].append(
                                f"{service_domain}.{service_action} → {entity_id}: OK"
                            )
                        except Exception as svc_err:
                            step_result["details"].append(
                                f"{service_domain}.{service_action} → {entity_id}: FEHLER ({svc_err})"
                            )
                            logger.error(
                                "Playbook %s Schritt %d — Service-Fehler: %s.%s → %s: %s",
                                scenario, step_num, service_domain, service_action,
                                entity_id, svc_err,
                            )

                    step_result["success"] = True

            except Exception as step_err:
                step_result["success"] = False
                step_result["error"] = str(step_err)
                logger.error(
                    "Playbook %s Schritt %d fehlgeschlagen: %s",
                    scenario, step_num, step_err,
                )

            executed_steps.append(step_result)

        # Playbook abgeschlossen
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        self._running_playbooks.discard(scenario)

        succeeded = sum(1 for s in executed_steps if s.get("success"))
        total = len(executed_steps)
        logger.warning(
            "=== NOTFALL-PLAYBOOK ABGESCHLOSSEN: %s (%s) === "
            "%d/%d Schritte erfolgreich, Dauer: %.1fs",
            playbook["name"], scenario, succeeded, total, duration,
        )

        return executed_steps

    async def _was_notified(self, key: str, cooldown_minutes: int = 30) -> bool:
        if not self.redis:
            return False
        val = await self.redis.get(f"{KEY_THREAT_NOTIFIED}{key}")
        return val is not None

    async def _mark_notified(self, key: str, cooldown_minutes: int = 30):
        if not self.redis:
            return
        await self.redis.setex(f"{KEY_THREAT_NOTIFIED}{key}", cooldown_minutes * 60, "1")
