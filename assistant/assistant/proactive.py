"""
Proactive Manager - Der MindHome Assistant spricht von sich aus.
Hoert auf Events von Home Assistant / MindHome und entscheidet ob
eine proaktive Meldung sinnvoll ist.

Phase 5: Vollstaendig mit FeedbackTracker integriert.
- Adaptive Cooldowns basierend auf Feedback-Score
- Auto-Timeout fuer unbeantwortete Meldungen
- Intelligente Filterung pro Event-Typ und Urgency

Phase 10: Diagnostik + Wartungs-Erinnerungen.
- Periodische Entity-Checks (offline, low battery, stale)
- Wartungskalender-Erinnerungen (sanft, LOW Priority)
"""

import asyncio
import json
import logging
import random
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import aiohttp
import yaml

from .config import settings, yaml_config, get_person_title
from .constants import (
    GEO_APPROACHING_COOLDOWN_MIN,
    GEO_ARRIVING_COOLDOWN_MIN,
    PROACTIVE_AMBIENT_CHECK_INTERVAL,
    PROACTIVE_BATCH_STARTUP_DELAY,
    PROACTIVE_DIAGNOSTICS_STARTUP_DELAY,
    PROACTIVE_SEASONAL_STARTUP_DELAY,
    PROACTIVE_THREAT_CHECK_INTERVAL,
    PROACTIVE_THREAT_STARTUP_DELAY,
    PROACTIVE_WS_RECONNECT_DELAY,
)
from .ollama_client import validate_notification
from .websocket import emit_proactive, emit_interrupt

logger = logging.getLogger(__name__)

# ── Room-Profile-Cache fuer proactive.py (vermeidet wiederholtes YAML-Parsen) ──
_room_profiles_cache: dict = {}
_room_profiles_ts: float = 0.0
_ROOM_PROFILES_TTL = 600  # 10 Min


def _get_room_profiles_cached() -> dict:
    """Liefert room_profiles.yaml aus Cache (oder laedt bei Bedarf von Disk)."""
    global _room_profiles_cache, _room_profiles_ts
    now = time.time()
    if _room_profiles_cache and (now - _room_profiles_ts) < _ROOM_PROFILES_TTL:
        return _room_profiles_cache
    try:
        _cfg = Path(__file__).parent.parent / "config" / "room_profiles.yaml"
        if _cfg.exists():
            with open(_cfg) as f:
                _room_profiles_cache = yaml.safe_load(f) or {}
        else:
            _room_profiles_cache = {}
    except Exception as e:
        logger.debug("Room-Profiles nicht ladbar: %s", e)
        if not _room_profiles_cache:
            _room_profiles_cache = {}
    _room_profiles_ts = now
    return _room_profiles_cache


# Event-Prioritaeten
CRITICAL = "critical"  # Immer melden (Alarm, Rauch, Wasser)
HIGH = "high"          # Melden wenn wach
MEDIUM = "medium"      # Melden wenn passend
LOW = "low"            # Melden wenn entspannt


class ProactiveManager:
    """Verwaltet proaktive Meldungen basierend auf HA-Events."""

    def __init__(self, brain):
        self.brain = brain
        self._task: Optional[asyncio.Task] = None
        self._diag_task: Optional[asyncio.Task] = None
        self._batch_task: Optional[asyncio.Task] = None
        self._seasonal_task: Optional[asyncio.Task] = None
        self._running = False

        # Konfiguration
        proactive_cfg = yaml_config.get("proactive", {})
        self.enabled = proactive_cfg.get("enabled", True)
        self.cooldown = proactive_cfg.get("cooldown_seconds", 300)
        self.silence_scenes = set(proactive_cfg.get("silence_scenes", []))

        # Quiet Hours: keine LOW/MEDIUM-Durchsagen in diesem Zeitfenster
        quiet_cfg = yaml_config.get("ambient_presence", {})
        self._quiet_start = int(quiet_cfg.get("quiet_start", 22))
        self._quiet_end = int(quiet_cfg.get("quiet_end", 7))

        # Phase 15.4: Notification Batching (LOW sammeln)
        batch_cfg = proactive_cfg.get("batching", {})
        self.batch_enabled = batch_cfg.get("enabled", True)
        self.batch_interval = batch_cfg.get("interval_minutes", 30)
        self.batch_max_items = batch_cfg.get("max_items", 10)
        self._batch_queue: list[dict] = []

        # F-033: Lock fuer shared state (batch_queue, mb_triggered etc.)
        self._state_lock = asyncio.Lock()

        # Phase 7.1: Morning Briefing Auto-Trigger
        mb_cfg = yaml_config.get("routines", {}).get("morning_briefing", {})
        self._mb_enabled = mb_cfg.get("enabled", True)
        self._mb_window_start = int(mb_cfg.get("window_start_hour", 6))
        self._mb_window_end = int(mb_cfg.get("window_end_hour", 10))
        self._mb_triggered_today = False
        self._mb_last_date = ""

        # Evening Briefing: JARVIS meldet Abend-Status (Sicherheit, Wetter morgen)
        eb_cfg = yaml_config.get("routines", {}).get("evening_briefing", {})
        self._eb_enabled = eb_cfg.get("enabled", True)
        self._eb_window_start = int(eb_cfg.get("window_start_hour", 20))
        self._eb_window_end = int(eb_cfg.get("window_end_hour", 22))
        self._eb_triggered_today = False
        self._eb_last_date = ""

        # Wakeup-Sequenz Config
        ws_cfg = mb_cfg.get("wakeup_sequence", {})
        self._ws_enabled = ws_cfg.get("enabled", False)
        self._ws_bedroom_sensor = ws_cfg.get("bedroom_motion_sensor", "")
        self._ws_window_start = ws_cfg.get("window_start_hour", 5)
        self._ws_window_end = ws_cfg.get("window_end_hour", 9)
        self._ws_briefing_delay = ws_cfg.get("briefing_delay_seconds", 45)

        # Event-Mapping: HA Event -> Prioritaet + Beschreibung
        self.event_handlers = {
            # CRITICAL - Immer melden
            "alarm_triggered": (CRITICAL, "Alarm ausgeloest"),
            "smoke_detected": (CRITICAL, "Rauch erkannt"),
            "water_leak": (CRITICAL, "Wasseraustritt erkannt"),

            # HIGH - Melden wenn wach
            "motion_detected_night": (HIGH, "Naechtliche Bewegung"),

            # MEDIUM - Melden wenn passend
            "person_arrived": (MEDIUM, "Person angekommen"),
            "person_left": (MEDIUM, "Person gegangen"),
            "washer_done": (MEDIUM, "Waschmaschine fertig"),
            "dryer_done": (MEDIUM, "Trockner fertig"),
            "doorbell": (MEDIUM, "Jemand hat geklingelt"),
            "night_motion_camera": (MEDIUM, "Naechtliche Bewegung erkannt"),

            # LOW - Melden wenn entspannt
            "weather_warning": (LOW, "Wetterwarnung"),
            "window_open_rain": (LOW, "Fenster offen bei Regen"),

            # Phase 10: Diagnostik + Wartung
            "entity_offline": (MEDIUM, "Entity offline"),
            "low_battery": (MEDIUM, "Batterie niedrig"),
            "stale_sensor": (LOW, "Sensor reagiert nicht"),
            "maintenance_due": (LOW, "Wartungsaufgabe faellig"),

            # Phase 10.1: Musik-Follow
            "music_follow": (LOW, "Musik folgen"),

            # Phase 7.4: Geo-Fence
            "person_approaching": (LOW, "Person naehert sich"),
            "person_arriving": (MEDIUM, "Person gleich zuhause"),

            # Phase 7.9: Saisonale Aktionen
            "seasonal_cover": (LOW, "Rolladen saisonal angepasst"),

            # Phase 17: Neue Features
            "conditional_executed": (MEDIUM, "Bedingte Aktion ausgefuehrt"),
            "learning_suggestion": (LOW, "Automatisierungs-Vorschlag"),
            "threat_detected": (HIGH, "Sicherheitswarnung"),
            "energy_price_high": (LOW, "Teurer Strom"),
            "solar_surplus": (LOW, "Solar-Ueberschuss"),
        }

    def _is_quiet_hours(self) -> bool:
        """Prueft ob gerade Quiet Hours aktiv sind (z.B. 22:00-07:00)."""
        hour = datetime.now().hour
        if self._quiet_start > self._quiet_end:
            # Ueber Mitternacht: z.B. 22-7
            return hour >= self._quiet_start or hour < self._quiet_end
        return self._quiet_start <= hour < self._quiet_end

    async def start(self):
        """Startet den Event Listener."""
        if not self.enabled:
            logger.info("Proaktive Meldungen deaktiviert")
            return

        self._running = True
        self._task = asyncio.create_task(self._listen_ha_events())
        # Phase 10: Periodische Diagnostik starten
        if hasattr(self.brain, "diagnostics") and self.brain.diagnostics.enabled:
            self._diag_task = asyncio.create_task(self._run_diagnostics_loop())
        # Phase 15.4: Batch-Loop starten
        if self.batch_enabled:
            self._batch_task = asyncio.create_task(self._run_batch_loop())
        # Phase 7.9: Saisonaler Rolladen-Loop
        seasonal_cfg = yaml_config.get("seasonal_actions", {})
        if seasonal_cfg.get("enabled", True):
            self._seasonal_task = asyncio.create_task(self._run_seasonal_loop())

        # Phase 11: Saugroboter-Automatik
        vacuum_cfg = yaml_config.get("vacuum", {})
        if vacuum_cfg.get("enabled") and vacuum_cfg.get("auto_clean", {}).get("enabled"):
            self._vacuum_task = asyncio.create_task(self._run_vacuum_automation())
        # Emergency Protocols laden
        self._emergency_protocols = yaml_config.get("emergency_protocols", {})

        # Phase 17: Threat Assessment Loop
        self._threat_task: Optional[asyncio.Task] = None
        if hasattr(self.brain, "threat_assessment") and self.brain.threat_assessment.enabled:
            self._threat_task = asyncio.create_task(self._run_threat_assessment_loop())

        # Ambient Presence Loop (Jarvis ist immer da)
        self._ambient_task: Optional[asyncio.Task] = None
        ambient_cfg = yaml_config.get("ambient_presence", {})
        if ambient_cfg.get("enabled", False):
            self._ambient_task = asyncio.create_task(self._run_ambient_presence_loop())

        logger.info("Proactive Manager gestartet (Feedback + Diagnostik + Batching + Saisonal + Notfall + Threat + Ambient)")

    async def stop(self):
        """Stoppt den Event Listener."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._diag_task:
            self._diag_task.cancel()
            try:
                await self._diag_task
            except asyncio.CancelledError:
                pass
        if self._batch_task:
            self._batch_task.cancel()
            try:
                await self._batch_task
            except asyncio.CancelledError:
                pass
        if self._seasonal_task:
            self._seasonal_task.cancel()
            try:
                await self._seasonal_task
            except asyncio.CancelledError:
                pass
        if hasattr(self, "_threat_task") and self._threat_task:
            self._threat_task.cancel()
            try:
                await self._threat_task
            except asyncio.CancelledError:
                pass
        if hasattr(self, "_ambient_task") and self._ambient_task:
            self._ambient_task.cancel()
            try:
                await self._ambient_task
            except asyncio.CancelledError:
                pass
        logger.info("Proactive Manager gestoppt")

    async def _listen_ha_events(self):
        """Hoert auf Home Assistant Events via WebSocket."""
        ha_url = settings.ha_url.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ha_url}/api/websocket"

        while self._running:
            try:
                await self._connect_and_listen(ws_url)
            except Exception as e:
                logger.error("HA WebSocket Fehler: %s", e)
                if self._running:
                    await asyncio.sleep(PROACTIVE_WS_RECONNECT_DELAY)

    async def _connect_and_listen(self, ws_url: str):
        """Verbindet sich mit HA WebSocket und verarbeitet Events."""
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(ws_url) as ws:
                # Auth
                auth_msg = await ws.receive_json()
                if auth_msg.get("type") == "auth_required":
                    await ws.send_json({
                        "type": "auth",
                        "access_token": settings.ha_token,
                    })
                auth_result = await ws.receive_json()
                if auth_result.get("type") != "auth_ok":
                    logger.error("HA WebSocket Auth fehlgeschlagen")
                    return

                logger.info("HA WebSocket verbunden")

                # Events abonnieren
                await ws.send_json({
                    "id": 1,
                    "type": "subscribe_events",
                    "event_type": "state_changed",
                })

                # MindHome Events abonnieren
                await ws.send_json({
                    "id": 2,
                    "type": "subscribe_events",
                    "event_type": "mindhome_event",
                })

                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        if data.get("type") == "event":
                            await self._handle_event(data.get("event", {}))
                    elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                        break

    async def _handle_event(self, event: dict):
        """Verarbeitet ein HA Event und entscheidet ob gemeldet werden soll."""
        try:
            event_type = event.get("event_type", "")
            event_data = event.get("data", {})

            if event_type == "state_changed":
                await self._handle_state_change(event_data)
            elif event_type == "mindhome_event":
                await self._handle_mindhome_event(event_data)
        except Exception as e:
            logger.error("Event-Handler Fehler fuer %s: %s", event.get("event_type", "?"), e)

    async def _handle_state_change(self, data: dict):
        """Verarbeitet HA State-Change Events."""
        entity_id = data.get("entity_id", "")
        new_state = data.get("new_state", {})
        old_state = data.get("old_state", {})

        if not new_state or not old_state:
            return

        new_val = new_state.get("state", "")
        old_val = old_state.get("state", "")

        if new_val == old_val:
            return

        # Alarmsystem
        if entity_id.startswith("alarm_control_panel.") and new_val == "triggered":
            await self._notify("alarm_triggered", CRITICAL, {
                "entity": entity_id,
                "state": new_val,
            })
            await self._execute_emergency_protocol("intrusion")

        # Rauchmelder
        elif entity_id.startswith("binary_sensor.smoke") and new_val == "on":
            await self._notify("smoke_detected", CRITICAL, {
                "entity": entity_id,
            })
            await self._execute_emergency_protocol("fire")

        # Wassersensor
        elif entity_id.startswith("binary_sensor.water") and new_val == "on":
            await self._notify("water_leak", CRITICAL, {
                "entity": entity_id,
            })
            await self._execute_emergency_protocol("water_leak")

        # Tuerklingel — mit Kamera-Beschreibung + Besucher-Management
        elif "doorbell" in entity_id and new_val == "on":
            camera_desc = None
            try:
                camera_desc = await self.brain.camera_manager.describe_doorbell()
            except Exception as e:
                logger.debug("Doorbell Kamera-Beschreibung fehlgeschlagen: %s", e)

            # Feature 12: Besucher-Management Integration
            visitor_info = None
            if hasattr(self.brain, "visitor_manager") and self.brain.visitor_manager.enabled:
                try:
                    visitor_info = await self.brain.visitor_manager.handle_doorbell(
                        camera_description=camera_desc or "",
                    )
                except Exception as e:
                    logger.debug("VisitorManager Doorbell-Handling fehlgeschlagen: %s", e)

            data = {"entity": entity_id}
            if camera_desc:
                data["camera_description"] = camera_desc
            if visitor_info:
                data["visitor_info"] = visitor_info
                if visitor_info.get("auto_unlocked"):
                    data["auto_unlocked"] = True
                if visitor_info.get("expected"):
                    data["expected_visitor"] = True
            await self._notify("doorbell", MEDIUM, data)

        # Person tracker (Phase 7: erweitert mit Abschied + Abwesenheits-Summary)
        elif entity_id.startswith("person."):
            name = new_state.get("attributes", {}).get("friendly_name", entity_id)
            if new_val == "home" and old_val != "home":
                # Phase 7.4: Willkommen + Abwesenheits-Summary
                status = await self._build_arrival_status(name)

                # Phase 7.8: Abwesenheits-Zusammenfassung
                absence_summary = ""
                if hasattr(self.brain, "routines"):
                    absence_summary = await self.brain.routines.get_absence_summary()
                if absence_summary:
                    status["absence_summary"] = absence_summary

                await self._notify("person_arrived", MEDIUM, {
                    "person": name,
                    "status_report": status,
                })

            elif old_val == "home" and new_val != "home":
                # Phase 7.4: Abschied mit Sicherheits-Hinweis
                await self._notify("person_left", MEDIUM, {
                    "person": name,
                    "departure_check": True,
                })

        # Phase 7.4: Geo-Fence Proximity (proximity.home Entity)
        elif entity_id.startswith("proximity.") or entity_id.startswith("sensor.") and "distance" in entity_id:
            await self._check_geo_fence(entity_id, new_val, old_val, new_state)

        # Phase 7.1 + 10.1: Bewegung erkannt → Morning/Evening Briefing + Musik-Follow + Nacht-Kamera + Follow-Me
        elif entity_id.startswith("binary_sensor.") and "motion" in entity_id and new_val == "on":
            await self._check_morning_briefing(motion_entity=entity_id)
            await self._check_evening_briefing()
            await self._check_music_follow(entity_id)
            await self._check_night_motion_camera(entity_id)
            await self._check_follow_me(entity_id)

        # Waschmaschine/Trockner (Power-Sensor faellt unter Schwellwert)
        elif "washer" in entity_id or "waschmaschine" in entity_id:
            if entity_id.startswith("sensor.") and new_val.replace(".", "").isdigit():
                try:
                    old_num = float(old_val) if old_val and old_val.replace(".", "").isdigit() else 0.0
                    if old_num > 10 and float(new_val) < 5:
                        await self._notify("washer_done", MEDIUM, {})
                except (ValueError, TypeError):
                    pass

        # Conditional Commands pruefen (Wenn-Dann-Logik)
        if hasattr(self.brain, "conditional_commands"):
            try:
                attrs = new_state.get("attributes", {})
                executed = await self.brain.conditional_commands.check_event(
                    entity_id, new_val, old_val, attrs,
                )
                for action in executed:
                    logger.info("Conditional ausgefuehrt: %s -> %s",
                                action.get("label", ""), action.get("action", ""))
                    await self._notify("conditional_executed", MEDIUM, {
                        "label": action.get("label", ""),
                        "action": action.get("action", ""),
                    })
            except Exception as e:
                logger.debug("Conditional-Check Fehler: %s", e)

        # Learning Observer: Manuelle Aktionen beobachten
        if hasattr(self.brain, "learning_observer"):
            try:
                await self.brain.learning_observer.observe_state_change(
                    entity_id, new_val, old_val,
                )
            except Exception as e:
                logger.debug("Learning Observer Fehler: %s", e)

    async def _check_morning_briefing(self, motion_entity: str = ""):
        """Phase 7.1: Prueft ob Morning Briefing bei erster Bewegung am Morgen geliefert werden soll."""
        if not self._mb_enabled:
            return

        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        # Reset am neuen Tag
        if self._mb_last_date != today:
            self._mb_triggered_today = False
            self._mb_last_date = today

        # Schon heute geliefert?
        if self._mb_triggered_today:
            return

        # Innerhalb des Morgen-Fensters?
        if not (self._mb_window_start <= now.hour < self._mb_window_end):
            return

        # Aufwach-Sequenz: Wenn Schlafzimmer-Sensor → stufenweises Aufwachen vor Briefing
        wakeup_done = False
        if (
            self._ws_enabled
            and self._ws_bedroom_sensor
            and motion_entity == self._ws_bedroom_sensor
            and self._ws_window_start <= now.hour < self._ws_window_end
        ):
            try:
                autonomy = getattr(self.brain, "autonomy", None)
                level = getattr(autonomy, "current_level", 3) if autonomy else 3
                wakeup_done = await self.brain.routines.execute_wakeup_sequence(
                    autonomy_level=level,
                )
                if wakeup_done:
                    logger.info("Aufwach-Sequenz ausgefuehrt, Briefing-Delay: %ds", self._ws_briefing_delay)
                    await asyncio.sleep(self._ws_briefing_delay)
            except Exception as e:
                logger.debug("Aufwach-Sequenz Fehler: %s", e)

        # Briefing generieren (routine_engine prueft intern ob schon geliefert via Redis)
        try:
            result = await self.brain.routines.generate_morning_briefing()
            text = result.get("text", "")
            if text:
                # Phase 17: Predictive Briefing anhaengen (Wetter-/Energievorschau)
                try:
                    predictive = await self.brain.get_predictive_briefing()
                    if predictive:
                        text = f"{text}\n{predictive}"
                except Exception as e:
                    logger.debug("Predictive Briefing Fehler: %s", e)

                # JARVIS-Begruessung: Person-aware Anrede
                _mb_persons = await self._get_persons_at_home()
                if len(_mb_persons) == 1:
                    _title = get_person_title(_mb_persons[0])
                elif len(_mb_persons) > 1:
                    _titles = []
                    for _p in _mb_persons:
                        _t = get_person_title(_p)
                        if _t not in _titles:
                            _titles.append(_t)
                    _title = ", ".join(_titles)
                else:
                    _title = get_person_title()
                _greetings = [
                    f"Guten Morgen, {_title}.",
                    f"Morgen, {_title}. Systeme laufen.",
                    "Guten Morgen. Alles bereit.",
                    f"Morgen, {_title}. Hier die Lage.",
                ]
                greeting = random.choice(_greetings)
                text = f"{greeting} {text}"

                self._mb_triggered_today = True
                await emit_proactive(text, "morning_briefing", MEDIUM)
                logger.info("Morning Briefing automatisch geliefert")

                # B3: Pending Tages-Zusammenfassung nach Briefing liefern
                if self.brain.memory.redis:
                    pending = await self.brain.memory.redis.get("mha:pending_summary")
                    if pending:
                        summary = pending.decode() if isinstance(pending, bytes) else pending
                        await asyncio.sleep(3)  # Kurze Pause nach dem Briefing
                        await emit_proactive(
                            f"Uebrigens, gestern zusammengefasst: {summary}",
                            "daily_summary", LOW,
                        )
                        await self.brain.memory.redis.delete("mha:pending_summary")
                        logger.info("Pending Tages-Zusammenfassung zugestellt")
        except Exception as e:
            logger.error("Morning Briefing Auto-Trigger Fehler: %s", e)

    async def _check_evening_briefing(self):
        """JARVIS Evening Briefing: Abend-Status bei erster Bewegung abends."""
        if not self._eb_enabled:
            return

        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        # Reset am neuen Tag
        if self._eb_last_date != today:
            self._eb_triggered_today = False
            self._eb_last_date = today

        if self._eb_triggered_today:
            return

        if not (self._eb_window_start <= now.hour < self._eb_window_end):
            return

        try:
            text = await self.generate_evening_briefing()
            if text:
                self._eb_triggered_today = True
                await emit_proactive(text, "evening_briefing", LOW)
                logger.info("Evening Briefing geliefert: %s", text[:80])
        except Exception as e:
            logger.debug("Evening Briefing Fehler: %s", e)

        # Persoenliche Daten pruefen (Geburtstags-Erinnerung fuer morgen)
        await self._check_personal_dates()

    async def generate_evening_briefing(self, person: str = "") -> str:
        """Generiert ein Abend-Briefing im JARVIS-Stil.

        Kann sowohl vom Auto-Trigger als auch per Sprachbefehl aufgerufen werden.

        Returns:
            Briefing-Text oder leerer String.
        """
        try:
            # Haus-Status sammeln
            states = await self.brain.ha.get_states()
            if not states:
                return ""

            # Offene Fenster/Tueren — is_window_or_door statt Keyword-Matching
            from .function_calling import is_window_or_door
            open_items = []
            for s in states:
                eid = s.get("entity_id", "")
                if is_window_or_door(eid, s) and s.get("state") == "on":
                    name = s.get("attributes", {}).get("friendly_name", eid)
                    open_items.append(name)

            # Unverriegelte Schloesser
            unlocked = []
            for s in states:
                if s.get("entity_id", "").startswith("lock.") and s.get("state") != "locked":
                    name = s.get("attributes", {}).get("friendly_name", s["entity_id"])
                    unlocked.append(name)

            # Wetter morgen (falls verfuegbar)
            _cond_map = {
                "sunny": "sonnig", "clear-night": "klare Nacht",
                "partlycloudy": "teilweise bewoelkt", "cloudy": "bewoelkt",
                "rainy": "Regen", "pouring": "Starkregen",
                "snowy": "Schnee", "snowy-rainy": "Schneeregen",
                "fog": "Nebel", "hail": "Hagel",
                "lightning": "Gewitter", "lightning-rainy": "Gewitter mit Regen",
                "windy": "windig", "windy-variant": "windig & bewoelkt",
                "exceptional": "Ausnahmewetter",
            }
            weather_tomorrow = ""
            for s in states:
                if s.get("entity_id", "").startswith("weather."):
                    forecast = s.get("attributes", {}).get("forecast", [])
                    if forecast and len(forecast) > 1:
                        tmrw = forecast[1]
                        cond = _cond_map.get(tmrw.get("condition", ""), tmrw.get("condition", "?"))
                        weather_tomorrow = (
                            f"Morgen {tmrw.get('temperature', '?')} Grad, {cond}."
                        )
                    break

            # Innentemperatur: Konfigurierte Sensoren (Mittelwert) bevorzugen
            temp = ""
            rt_sensors = yaml_config.get("room_temperature", {}).get("sensors", []) or []
            if rt_sensors:
                state_map = {s.get("entity_id"): s for s in states}
                sensor_temps = []
                for sid in rt_sensors:
                    st = state_map.get(sid, {})
                    try:
                        sensor_temps.append(float(st.get("state", "")))
                    except (ValueError, TypeError):
                        pass
                if sensor_temps:
                    avg = round(sum(sensor_temps) / len(sensor_temps), 1)
                    temp = f"Innen {avg} Grad."
            else:
                for s in states:
                    if s.get("entity_id", "").startswith("climate."):
                        t = s.get("attributes", {}).get("current_temperature")
                        if t is None:
                            continue
                        try:
                            t_val = float(t)
                            if -20 < t_val < 50:
                                temp = f"Innen {t_val:.1f} Grad."
                                break
                        except (ValueError, TypeError):
                            continue

            # Rolllaeden offen?
            covers_open = []
            for s in states:
                eid = s.get("entity_id", "")
                if eid.startswith("cover.") and s.get("state") == "open":
                    name = s.get("attributes", {}).get("friendly_name", eid)
                    covers_open.append(name)

            # Lichter noch an?
            lights_on = []
            for s in states:
                eid = s.get("entity_id", "")
                if eid.startswith("light.") and s.get("state") == "on":
                    name = s.get("attributes", {}).get("friendly_name", eid)
                    lights_on.append(name)

            # Prompt bauen
            parts = []
            if temp:
                parts.append(temp)
            if weather_tomorrow:
                parts.append(weather_tomorrow)
            if open_items:
                parts.append(f"Noch offen: {', '.join(open_items)}.")
            if unlocked:
                parts.append(f"Unverriegelt: {', '.join(unlocked)}.")

            # Proaktive Abend-Empfehlungen (JARVIS denkt mit)
            suggestions = []
            if covers_open:
                suggestions.append(f"Rolllaeden noch offen: {', '.join(covers_open[:3])}.")
            if lights_on and len(lights_on) >= 3:
                suggestions.append(f"{len(lights_on)} Lichter noch an.")
            if open_items:
                suggestions.append("Fenster vor der Nacht schliessen?")
            if unlocked:
                suggestions.append("Schloesser verriegeln?")
            if suggestions:
                parts.append("Vorschlaege: " + " ".join(suggestions))
            elif not open_items and not unlocked:
                parts.append("Alles gesichert.")

            if not parts:
                return ""

            # LLM-Polish im JARVIS-Stil
            # Person-aware Anrede: uebergebener Parameter hat Vorrang
            if person:
                _eb_person = person
            else:
                _eb_persons = await self._get_persons_at_home()
                _eb_person = _eb_persons[0] if len(_eb_persons) == 1 else ""
            _eb_title = get_person_title(_eb_person) if _eb_person else get_person_title()
            prompt = (
                f"Abend-Status-Bericht. Anrede: \"{_eb_title}\". "
                "Fasse zusammen, JARVIS-Butler-Stil, max 3 Saetze. "
                "Bei offenen Fenstern/Tueren/Rolllaeden: Kurz vorschlagen ob du sie schliessen sollst. "
                "Nicht fragen ob du helfen kannst — direkt anbieten was du tun wuerdest.\n"
                + "\n".join(parts)
            )

            response = await self.brain.ollama.chat(
                messages=[
                    {"role": "system", "content": self._get_notification_system_prompt(person=_eb_person)},
                    {"role": "user", "content": prompt},
                ],
                model=settings.model_notify,
                think=False,
                max_tokens=150,
            )
            text = validate_notification(
                response.get("message", {}).get("content", "")
            )
            return text or ""

        except Exception as e:
            logger.debug("Evening Briefing Fehler: %s", e)
            return ""

    async def _check_personal_dates(self):
        """Proaktive Erinnerung an persoenliche Daten (Geburtstage, Jahrestage).

        - days_until == 1: Abend-Erinnerung ("Morgen hat Lisa Geburtstag")
        - days_until == 0 + Nachmittags: Fallback falls Briefing verpasst
        Laeuft max 1x pro Tag (Redis-Flag).
        """
        if not hasattr(self.brain, "memory") or not self.brain.memory:
            return
        semantic = getattr(self.brain.memory, "semantic", None)
        if not semantic:
            return
        redis_client = getattr(self.brain.memory, "redis", None)
        if not redis_client:
            return

        today = datetime.now().strftime("%Y-%m-%d")
        flag_key = f"mha:personal_dates_checked:{today}"

        try:
            already = await redis_client.get(flag_key)
            if already:
                return
        except Exception:
            return

        try:
            upcoming = await semantic.get_upcoming_personal_dates(days_ahead=2)
            if not upcoming:
                await redis_client.setex(flag_key, 86400, "1")
                return

            now = datetime.now()
            for entry in upcoming:
                days = entry["days_until"]
                name = entry["person"].capitalize()
                label = entry.get("label", "Geburtstag")
                date_type = entry.get("date_type", "birthday")
                anni = entry.get("anniversary_years", 0)

                # Dedup per Person/Typ/Tag
                dedup_key = f"mha:personal_date_notified:{today}:{name}:{date_type}"
                if await redis_client.get(dedup_key):
                    continue

                if days == 1:
                    # Morgen -> Abend-Erinnerung
                    if date_type == "birthday":
                        if anni:
                            msg = f"Morgen hat {name} Geburtstag — wird {anni}. Falls noch ein Geschenk fehlt, jetzt waere der Moment."
                        else:
                            msg = f"Morgen hat {name} Geburtstag. Falls noch ein Geschenk fehlt, jetzt waere der Moment."
                    else:
                        suffix = f" ({anni}.)" if anni else ""
                        msg = f"Morgen ist {label}{suffix}."
                    await emit_proactive(msg, "personal_date_reminder", LOW)
                    await redis_client.setex(dedup_key, 86400, "1")
                    logger.info("Personal date reminder: %s (morgen)", name)

                elif days == 0 and now.hour >= 14:
                    # Heute nachmittags: Fallback falls Briefing verpasst
                    if date_type == "birthday":
                        msg = f"Zur Erinnerung: Heute hat {name} Geburtstag."
                    else:
                        msg = f"Zur Erinnerung: Heute ist {label}."
                    await emit_proactive(msg, "personal_date_today", MEDIUM)
                    await redis_client.setex(dedup_key, 86400, "1")
                    logger.info("Personal date fallback: %s (heute)", name)

            await redis_client.setex(flag_key, 86400, "1")

        except Exception as e:
            logger.debug("Personal dates check Fehler: %s", e)

    async def _check_night_motion_camera(self, motion_entity: str):
        """Nacht-Motion: Wenn nachts Bewegung erkannt wird, Kamera-Snapshot analysieren."""
        from datetime import datetime
        try:
            hour = datetime.now().hour
            # Nur nachts (22:00 - 06:00)
            if not (hour >= 22 or hour < 6):
                return

            # Nur Outdoor-Motion-Sensoren (indoor-Bewegung ist normal)
            eid_lower = motion_entity.lower()
            if not any(kw in eid_lower for kw in ("outdoor", "aussen", "garten", "einfahrt", "hof", "garage")):
                return

            # Cooldown: Max 1x pro 10 Minuten pro Sensor
            cooldown_key = f"mha:night_cam:{motion_entity}"
            if self.brain.memory and self.brain.memory.redis:
                already = await self.brain.memory.redis.get(cooldown_key)
                if already:
                    return
                await self.brain.memory.redis.setex(cooldown_key, 600, "1")

            # Kamera-Analyse
            if not hasattr(self.brain, "camera_manager"):
                return
            description = await self.brain.camera_manager.analyze_night_motion(motion_entity)
            if description:
                await self._notify("night_motion_camera", MEDIUM, {
                    "entity": motion_entity,
                    "camera_description": description,
                })
        except Exception as e:
            logger.debug("Nacht-Motion-Kamera fehlgeschlagen: %s", e)

    async def _check_follow_me(self, motion_entity: str):
        """Follow-Me: Transferiert Musik/Licht/Klima wenn Person den Raum wechselt."""
        try:
            if not hasattr(self.brain, "follow_me") or not self.brain.follow_me.enabled:
                return

            # Person identifizieren: Wenn nur 1 Person zuhause, ist es die.
            persons_home = await self._get_persons_at_home()
            person = persons_home[0] if len(persons_home) == 1 else ""

            # Veraltete Tracking-Eintraege bereinigen
            self.brain.follow_me.cleanup_stale_tracking()

            result = await self.brain.follow_me.handle_motion(motion_entity, person=person)
            if result and result.get("actions"):
                actions_desc = ", ".join(a["type"] for a in result["actions"])
                logger.info(
                    "Follow-Me Transfer: %s → %s (%s)",
                    result["from_room"], result["to_room"], actions_desc,
                )
        except Exception as e:
            logger.debug("Follow-Me Check fehlgeschlagen: %s", e)

    async def _check_music_follow(self, motion_entity: str):
        """Phase 10.1: Prueft ob Musik dem User in einen neuen Raum folgen soll."""
        try:
            multi_room_cfg = yaml_config.get("multi_room", {})
            if not multi_room_cfg.get("enabled"):
                return

            # Raum des Bewegungsmelders ermitteln
            motion_sensors = multi_room_cfg.get("room_motion_sensors", {})
            new_room = None
            for room_name, sensor_id in (motion_sensors or {}).items():
                if sensor_id == motion_entity:
                    new_room = room_name
                    break

            if not new_room:
                return

            # Aktiven Media Player finden (der gerade spielt)
            states = await self.brain.ha.get_states()
            playing_entity = None
            playing_room = None
            for s in (states or []):
                eid = s.get("entity_id", "")
                if eid.startswith("media_player.") and s.get("state") == "playing":
                    playing_entity = eid
                    # Raum des Players ermitteln
                    room_speakers = multi_room_cfg.get("room_speakers", {})
                    for room_name, speaker_id in (room_speakers or {}).items():
                        if speaker_id == eid:
                            playing_room = room_name
                            break
                    break

            if not playing_entity or not playing_room:
                return

            # Nur melden wenn der neue Raum NICHT der Raum ist in dem Musik laeuft
            if new_room.lower() == playing_room.lower():
                return

            # Cooldown: Nicht staendig fragen (1x pro 5 Minuten)
            cooldown_key = "music_follow"
            last_time = await self.brain.memory.get_last_notification_time(cooldown_key)
            if last_time:
                last_dt = datetime.fromisoformat(last_time)
                if datetime.now() - last_dt < timedelta(minutes=5):
                    return

            # Phase 10.1: Auto-Follow bei hohem Autonomie-Level
            auto_follow = multi_room_cfg.get("auto_follow", False)
            if auto_follow and self.brain.autonomy.level >= 4:
                # Automatisch Musik transferieren
                target_speaker = multi_room_cfg.get("room_speakers", {}).get(new_room)
                if target_speaker:
                    try:
                        await self.brain.ha.call_service(
                            "media_player", "join",
                            {"entity_id": target_speaker, "group_members": [playing_entity]},
                        )
                        logger.info("Auto-Follow: Musik von %s nach %s transferiert",
                                    playing_room, new_room)
                    except Exception as e:
                        logger.debug("Auto-Follow Transfer fehlgeschlagen: %s", e)

            await self._notify("music_follow", LOW, {
                "from_room": playing_room,
                "to_room": new_room,
                "player_entity": playing_entity,
                "auto_followed": auto_follow and self.brain.autonomy.level >= 4,
            })

        except Exception as e:
            logger.debug("Music-Follow Check fehlgeschlagen: %s", e)

    async def _check_geo_fence(self, entity_id: str, new_val: str, old_val: str, state: dict):
        """Phase 7.4: Geo-Fence Proximity — erkennt Annaeherung ans Zuhause.

        Nutzt proximity.home oder distance-Sensoren um zu erkennen wenn jemand
        sich dem Zuhause naehert (< threshold km) und bereitet den Empfang vor.
        """
        try:
            new_distance = float(new_val)
        except (ValueError, TypeError):
            return

        try:
            old_distance = float(old_val) if old_val else new_distance + 1
        except (ValueError, TypeError):
            old_distance = new_distance + 1

        # Konfigurierter Schwellwert (Standard: 2km)
        geo_cfg = yaml_config.get("geo_fence", {})
        threshold_near = geo_cfg.get("approaching_km", 2.0)
        threshold_close = geo_cfg.get("arriving_km", 0.5)

        # Annaeherung erkennen: Distanz faellt unter Schwellwert
        person_name = state.get("attributes", {}).get("friendly_name", "Jemand")

        # "Naehert sich" — unter 2km und kommt naeher
        if old_distance > threshold_near >= new_distance > threshold_close:
            cooldown_key = f"geo_approaching:{entity_id}"
            last = await self.brain.memory.get_last_notification_time(cooldown_key)
            if last:
                last_dt = datetime.fromisoformat(last)
                if datetime.now() - last_dt < timedelta(minutes=GEO_APPROACHING_COOLDOWN_MIN):
                    return
            await self.brain.memory.set_last_notification_time(cooldown_key)
            await self._notify("person_approaching", LOW, {
                "person": person_name,
                "distance_km": round(new_distance, 1),
                "entity": entity_id,
            })

        # "Gleich da" — unter 0.5km
        elif old_distance > threshold_close >= new_distance:
            cooldown_key = f"geo_arriving:{entity_id}"
            last = await self.brain.memory.get_last_notification_time(cooldown_key)
            if last:
                last_dt = datetime.fromisoformat(last)
                if datetime.now() - last_dt < timedelta(minutes=GEO_ARRIVING_COOLDOWN_MIN):
                    return
            await self.brain.memory.set_last_notification_time(cooldown_key)
            await self._notify("person_arriving", MEDIUM, {
                "person": person_name,
                "distance_km": round(new_distance, 1),
                "entity": entity_id,
            })

    async def _handle_mindhome_event(self, data: dict):
        """Verarbeitet MindHome-spezifische Events."""
        event_name = data.get("event", "")
        urgency = data.get("urgency", MEDIUM)
        await self._notify(event_name, urgency, data)

    async def _notify(self, event_type: str, urgency: str, data: dict):
        """Prueft ob gemeldet werden soll und erzeugt Meldung."""

        # Quiet Hours: Nur CRITICAL darf nachts durch
        if urgency != CRITICAL and self._is_quiet_hours():
            logger.info("Meldung unterdrueckt (Quiet Hours): [%s] %s", urgency, event_type)
            return

        # Autonomie-Level pruefen
        if urgency != CRITICAL:
            level = self.brain.autonomy.level
            if level < 2:  # Level 1 = nur Befehle
                return

        # Cooldown pruefen (mit adaptivem Cooldown aus Feedback)
        effective_cooldown = self.cooldown
        feedback = self.brain.feedback

        if urgency not in (CRITICAL, HIGH):
            # Feedback-basierte Entscheidung
            decision = await feedback.should_notify(event_type, urgency)
            if not decision["allow"]:
                logger.info(
                    "Meldung unterdrueckt [%s]: %s", event_type, decision["reason"]
                )
                return
            # Adaptiver Cooldown aus Feedback
            effective_cooldown = decision.get("cooldown", self.cooldown)

            # Cooldown pruefen
            last_time = await self.brain.memory.get_last_notification_time(event_type)
            if last_time:
                last_dt = datetime.fromisoformat(last_time)
                if datetime.now() - last_dt < timedelta(seconds=effective_cooldown):
                    return

        # Phase 15.4+: LOW und MEDIUM-Meldungen batchen statt sofort senden
        # MEDIUM wird kuerzere Batch-Intervalle haben (10 Min statt 30)
        if self.batch_enabled and urgency in (LOW, MEDIUM):
            description = self.event_handlers.get(event_type, (MEDIUM, event_type))[1]
            # F-033: Lock fuer shared batch_queue
            async with self._state_lock:
                self._batch_queue.append({
                    "event_type": event_type,
                    "urgency": urgency,
                    "description": description,
                    "data": data,
                    "time": datetime.now().isoformat(),
                })

                medium_items = sum(1 for b in self._batch_queue if b.get("urgency") == MEDIUM)
                should_flush = medium_items >= 5 or len(self._batch_queue) >= self.batch_max_items
                queue_len = len(self._batch_queue)

            if should_flush:
                _t = asyncio.create_task(self._flush_batch())
                _t.add_done_callback(
                    lambda t: logger.warning("_flush_batch fehlgeschlagen: %s", t.exception())
                    if t.exception() else None
                )
            logger.debug("%s-Meldung gequeued [%s]: %s (%d in Queue, %d MEDIUM)",
                         urgency.upper(), event_type, description,
                         queue_len, medium_items)
            return

        # CRITICAL: Interrupt-Kanal — sofort durchstellen, kein LLM-Polish noetig
        if urgency == CRITICAL:
            description = self.event_handlers.get(event_type, (CRITICAL, event_type))[1]
            protocol = ""
            actions_taken = []

            # Notfall-Protokoll Name ermitteln
            protocol_map = {
                "alarm_triggered": "intrusion",
                "smoke_detected": "fire",
                "water_leak": "water_leak",
            }
            protocol = protocol_map.get(event_type, event_type)

            # Direkt-Text bauen (kein LLM-Aufruf — Zeit ist kritisch)
            text = data.get("message", description)
            if "camera_description" in data:
                text += f" {data['camera_description']}"

            await emit_interrupt(text, event_type, protocol, actions_taken)
            await self.brain.memory.set_last_notification_time(event_type)

            logger.warning(
                "INTERRUPT [%s/%s] (protocol: %s): %s",
                event_type, urgency, protocol, text,
            )
            return

        # Phase 6: Activity Engine + Silence Matrix
        activity_result = await self.brain.activity.should_deliver(urgency)
        if activity_result["suppress"]:
            logger.info(
                "Meldung unterdrueckt [%s]: Aktivitaet=%s, Delivery=%s",
                event_type, activity_result["activity"], activity_result["delivery"],
            )
            return

        delivery_method = activity_result["delivery"]

        # Notification-ID generieren (fuer Feedback-Tracking)
        notification_id = f"notif_{uuid.uuid4().hex[:12]}"

        # Meldung generieren
        description = self.event_handlers.get(event_type, (MEDIUM, event_type))[1]

        # Feature 3: Geraete-Persoenlichkeit — narration statt LLM wenn moeglich
        narration_text = None
        entity_id = data.get("entity_id", "")
        narration_event_map = {
            "device_turned_off": "turned_off",
            "device_turned_on": "turned_on",
            "device_running_long": "running_long",
            "device_anomaly": "anomaly",
        }
        if entity_id and event_type in narration_event_map:
            try:
                # Person-aware Anrede fuer Device-Narration
                _narr_persons = await self._get_persons_at_home()
                _narr_person = _narr_persons[0] if len(_narr_persons) == 1 else ""
                narration_text = self.brain.personality.narrate_device_event(
                    entity_id, narration_event_map[event_type],
                    detail=data.get("detail", ""),
                    person=_narr_person,
                )
            except Exception:
                pass  # Fallback auf LLM-generierte Meldung

        if narration_text:
            text = narration_text
            await emit_proactive(text, event_type, urgency, notification_id)
            await self.brain.memory.set_last_notification_time(event_type)
            await feedback.track_notification(notification_id, event_type)
            logger.info(
                "Proaktive Meldung [%s/%s] (narration, id: %s, delivery: %s): %s",
                event_type, urgency, notification_id, delivery_method, text,
            )
            return

        prompt = self._build_notification_prompt(event_type, description, data, urgency)

        try:
            response = await self.brain.ollama.chat(
                messages=[
                    {"role": "system", "content": self._get_notification_system_prompt(urgency, person=data.get("person", ""))},
                    {"role": "user", "content": prompt},
                ],
                model=settings.model_notify,
                think=False,
                max_tokens=100,
            )

            text = validate_notification(
                response.get("message", {}).get("content", description)
            )
            # Fallback auf Original wenn Reasoning-Leak komplett entfernt wurde
            if not text:
                text = description

            # WebSocket: Proaktive Meldung senden (mit Notification-ID + Delivery)
            await emit_proactive(text, event_type, urgency, notification_id)

            # Cooldown setzen
            await self.brain.memory.set_last_notification_time(event_type)

            # Feedback-Tracker: Meldung registrieren (wartet auf Feedback)
            await feedback.track_notification(notification_id, event_type)

            logger.info(
                "Proaktive Meldung [%s/%s] (id: %s, delivery: %s, activity: %s): %s",
                event_type, urgency, notification_id, delivery_method,
                activity_result["activity"], text,
            )

        except Exception as e:
            logger.error("Fehler bei proaktiver Meldung: %s", e)

    async def _build_arrival_status(self, person_name: str) -> dict:
        """Baut einen Status-Bericht fuer eine ankommende Person."""
        status = {"person": person_name}
        try:
            # Haus-Status sammeln
            states = await self.brain.ha.get_states()
            if not states:
                return status

            # Wer ist noch zuhause?
            others_home = []
            for s in states:
                if s.get("entity_id", "").startswith("person."):
                    pname = s.get("attributes", {}).get("friendly_name", "")
                    if s.get("state") == "home" and pname.lower() != person_name.lower():
                        others_home.append(pname)
            status["others_home"] = others_home

            # Temperatur
            for s in states:
                if s.get("entity_id", "").startswith("climate."):
                    attrs = s.get("attributes", {})
                    status["temperature"] = attrs.get("current_temperature")
                    break

            # Wetter
            for s in states:
                if s.get("entity_id", "").startswith("weather."):
                    attrs = s.get("attributes", {})
                    status["weather"] = {
                        "temp": attrs.get("temperature"),
                        "condition": s.get("state"),
                    }
                    break

            # Offene Fenster/Tueren
            open_items = []
            for s in states:
                eid = s.get("entity_id", "")
                if not eid.startswith("binary_sensor."):
                    continue
                if ("window" in eid or "door" in eid or "fenster" in eid or "tuer" in eid) and s.get("state") == "on":
                    name = s.get("attributes", {}).get("friendly_name", eid)
                    open_items.append(name)
            if open_items:
                status["open_items"] = open_items

            # Aktive Lichter
            lights_on = sum(
                1 for s in states
                if s.get("entity_id", "").startswith("light.") and s.get("state") == "on"
            )
            status["lights_on"] = lights_on

        except Exception as e:
            logger.debug("Fehler beim Status-Bericht: %s", e)

        return status

    async def generate_status_report(self, person_name: str = "") -> str:
        """Generiert einen Jarvis-artigen Status-Bericht (kann auch manuell aufgerufen werden)."""
        status = await self._build_arrival_status(person_name or "User")
        prompt = self._build_status_report_prompt(status)

        try:
            response = await self.brain.ollama.chat(
                messages=[
                    {"role": "system", "content": self._get_notification_system_prompt(person=person_name)},
                    {"role": "user", "content": prompt},
                ],
                model=settings.model_notify,
                think=False,
                max_tokens=120,
            )
            return validate_notification(
                response.get("message", {}).get("content", f"Alles ruhig, {get_person_title(person_name)}.")
            )
        except Exception as e:
            logger.error("Fehler beim Status-Bericht: %s", e)
            return "Status-Abfrage fehlgeschlagen. Systeme pruefen."

    def _get_person_title(self, person_name: str) -> str:
        """Gibt die korrekte Anrede fuer eine Person zurueck (Jarvis-Style)."""
        person_cfg = yaml_config.get("persons", {})
        titles = person_cfg.get("titles", {})

        # Hauptbenutzer = konfigurierter Titel
        if person_name.lower() == settings.user_name.lower():
            return titles.get(person_name.lower(), get_person_title())
        # Andere: Titel aus Config oder Vorname
        return titles.get(person_name.lower(), person_name)

    async def _get_persons_at_home(self) -> list[str]:
        """Gibt die Liste der aktuell anwesenden Personen zurueck."""
        try:
            states = await self.brain.ha.get_states()
            if not states:
                return []
            persons = []
            for s in states:
                if s.get("entity_id", "").startswith("person."):
                    if s.get("state") == "home":
                        pname = s.get("attributes", {}).get("friendly_name", "")
                        if pname:
                            persons.append(pname)
            return persons
        except Exception:
            return []

    async def _resolve_title_for_notification(self, data: dict) -> str:
        """Bestimmt die korrekte Anrede fuer eine Notification."""
        # 1. Wenn Person explizit in data → deren Titel
        if data.get("person"):
            return get_person_title(data["person"])
        # 2. Sonst: wer ist zuhause?
        persons = await self._get_persons_at_home()
        if len(persons) == 1:
            return get_person_title(persons[0])
        elif len(persons) > 1:
            # Alle Anwesenden ansprechen
            titles = []
            for p in persons:
                t = get_person_title(p)
                if t not in titles:
                    titles.append(t)
            return ", ".join(titles)
        # 3. Fallback: primary_user
        return get_person_title()

    def _build_status_report_prompt(self, status: dict) -> str:
        """Baut den Prompt fuer einen Status-Bericht (JARVIS-Butler-Stil)."""
        person = status.get("person", "User")
        title = self._get_person_title(person)
        parts = [
            f"{person} (Anrede: \"{title}\") ist gerade angekommen.",
            f"Erstelle einen knappen Butler-Status-Bericht. Wie JARVIS aus dem MCU.",
            f"WICHTIG: Sprich die Person mit \"{title}\" an, NICHT mit dem Vornamen.",
            "STIL: Sachlich, kompakt. Daten zuerst, dann Auffaelligkeiten. Kein 'Willkommen zuhause!'.",
            f"BEISPIEL: '21 Grad, {title}. Post war da. Kueche-Fenster steht noch offen.'",
        ]

        others = status.get("others_home", [])
        if others:
            parts.append(f"Ebenfalls zuhause: {', '.join(others)}")
        else:
            parts.append("Niemand sonst ist zuhause.")

        temp = status.get("temperature")
        if temp:
            parts.append(f"Innentemperatur: {temp}°C")

        weather = status.get("weather", {})
        if weather:
            parts.append(f"Wetter: {weather.get('temp', '?')}°C, {weather.get('condition', '?')}")

        open_items = status.get("open_items", [])
        if open_items:
            parts.append(f"Offen: {', '.join(open_items)}")

        lights = status.get("lights_on", 0)
        parts.append(f"Lichter an: {lights}")

        parts.append("Maximal 3 Saetze. Deutsch.")
        return "\n".join(parts)

    def _get_notification_system_prompt(self, urgency: str = "low", person: str = "") -> str:
        """Holt den Notification-Prompt aus der PersonalityEngine.

        Nutzt den vollen Personality-Stack (Sarkasmus, Formality, Tageszeit,
        Mood) statt eines statischen Mini-Prompts.
        """
        try:
            return self.brain.personality.build_notification_prompt(urgency, person=person)
        except Exception as e:
            logger.debug("Personality-Notification-Prompt fehlgeschlagen: %s", e)
            # Fallback auf Minimal-Prompt
            _title = get_person_title(person) if person else get_person_title()
            return (
                f"Du bist {settings.assistant_name} — J.A.R.V.I.S. aus dem MCU. "
                "Proaktive Hausmeldung. 1-2 Saetze. Deutsch. Trocken-britisch. "
                f'Anrede = "{_title}". Nie alarmistisch, nie devot. '
                "VERBOTEN: Hallo, Achtung, Es tut mir leid, Guten Tag."
            )

    # ------------------------------------------------------------------
    # Alert-Personality: Meldungen im Jarvis-Stil reformulieren
    # ------------------------------------------------------------------

    async def format_with_personality(self, raw_message: str, urgency: str = "low", person: str = "") -> str:
        """Reformuliert eine nackte Alert-Meldung im Jarvis-Stil.

        Nutzt das Fast-Model (qwen3:4b) fuer minimale Latenz.
        Faellt auf raw_message zurueck bei Fehler.

        Args:
            raw_message: Original-Meldung (z.B. "Trink-Erinnerung: Ein Glas Wasser")
            urgency: Dringlichkeit (low/medium/high/critical)

        Returns:
            Reformulierte Meldung im Jarvis-Stil
        """
        if not raw_message or not raw_message.strip():
            return raw_message

        # Bei CRITICAL keine Zeit verschwenden — direkt durchreichen
        if urgency == "critical":
            return raw_message

        try:
            response = await self.brain.ollama.chat(
                messages=[
                    {"role": "system", "content": self._get_notification_system_prompt(urgency, person=person)},
                    {"role": "user", "content": (
                        f"[{urgency.upper()}] Reformuliere im JARVIS-Stil:\n{raw_message}"
                    )},
                ],
                model=settings.model_notify,
                think=False,
                max_tokens=100,
            )
            text = validate_notification(
                response.get("message", {}).get("content", "").strip()
            )
            return text if text else raw_message
        except Exception as e:
            logger.debug("Alert-Personality Fehler (Fallback auf Original): %s", e)
            return raw_message

    # ------------------------------------------------------------------
    # Phase 10: Periodische Diagnostik
    # ------------------------------------------------------------------

    async def _run_diagnostics_loop(self):
        """Periodischer Diagnostik-Check (Entity-Watchdog + Wartungs-Erinnerungen)."""
        await asyncio.sleep(PROACTIVE_DIAGNOSTICS_STARTUP_DELAY)

        while self._running:
            try:
                diag = self.brain.diagnostics
                result = await diag.check_all()

                # Entity-Probleme melden
                for issue in result.get("issues", []):
                    issue_type = issue.get("issue_type", "unknown")
                    event_type = {
                        "offline": "entity_offline",
                        "low_battery": "low_battery",
                        "stale": "stale_sensor",
                    }.get(issue_type, "entity_offline")

                    severity = issue.get("severity", "warning")
                    urgency = HIGH if severity == "critical" else MEDIUM if severity == "warning" else LOW

                    await self._notify(event_type, urgency, {
                        "entity": issue.get("entity_id", ""),
                        "message": issue.get("message", ""),
                    })

                # Wartungs-Erinnerungen (nur LOW)
                for task in result.get("maintenance_due", []):
                    await self._notify("maintenance_due", LOW, {
                        "task": task.get("name", ""),
                        "days_overdue": task.get("days_overdue", 0),
                        "description": task.get("description", ""),
                    })

            except Exception as e:
                logger.error("Diagnostik-Check Fehler: %s", e)

            # Warte bis zum naechsten Check
            interval = self.brain.diagnostics.check_interval * 60
            await asyncio.sleep(interval)

    def _build_notification_prompt(
        self, event_type: str, description: str, data: dict, urgency: str
    ) -> str:
        parts = [f"[{urgency.upper()}] {description}"]
        # Person-aware Anrede fuer alle Templates
        _title = get_person_title(data["person"]) if data.get("person") else get_person_title()

        if "person" in data:
            parts.append(f"Person: {data['person']}")
        if "entity" in data:
            parts.append(f"Entity: {data['entity']}")
        if "status_report" in data:
            status = data["status_report"]
            prompt = self._build_status_report_prompt(status)
            # Phase 7.8: Abwesenheits-Summary anhaengen
            if "absence_summary" in status:
                prompt += f"\n\nWaehrend der Abwesenheit: {status['absence_summary']}"
                prompt += "\nErwaehne kurz was waehrend der Abwesenheit passiert ist."
            return prompt

        # Phase 7.4: Abschied mit Sicherheits-Check (JARVIS-Butler-Stil)
        if data.get("departure_check"):
            person = data.get("person", "User")
            title = self._get_person_title(person)
            parts = [
                f"{person} (Anrede: \"{title}\") verlaesst gerade das Haus.",
                f"Sprich mit \"{title}\" an. KEIN 'Schoenen Tag!' oder 'Tschuess!'.",
                "Nur relevante Fakten: offene Fenster, unverriegelte Tueren, Alarm-Status.",
                f"Wenn alles gesichert ist: nur knapp bestaetigen. 'Alles gesichert, {title}.'",
                "Wenn etwas offen ist: sachlich erwaehnen. 'Fenster Kueche steht noch offen.'",
                "Max 2 Saetze. Deutsch. Butler der dem Herrn den Mantel reicht, nicht winkt.",
            ]
            return "\n".join(parts)

        # Nacht-Motion Kamera: Bewegung + Kamera-Beschreibung
        if event_type == "night_motion_camera":
            cam_desc = data.get("camera_description", "")
            return (
                f"Naechtliche Bewegung erkannt ({data.get('entity', 'Aussen')}).\n"
                f"Kamera zeigt: {cam_desc}\n"
                f"Formuliere eine knappe Sicherheitsmeldung im JARVIS-Stil.\n"
                f"Max 2 Saetze. Deutsch. Sachlich. Keine Panik wenn harmlos (Tier, Wind)."
            )

        # Phase 10.1: Musik-Follow Vorschlag
        if event_type == "music_follow":
            from_room = data.get("from_room", "")
            to_room = data.get("to_room", "")
            return (
                f"Musik laeuft gerade in {from_room}. Bewegung erkannt in {to_room}.\n"
                f"Frage kurz ob die Musik mitkommen soll.\n"
                f"Beispiel: 'Musik laeuft noch in {from_room}. Soll sie mitkommen?'\n"
                f"Max 1 Satz. Deutsch. Butler-Stil."
            )

        # Phase 7.9: Saisonale Rolladen-Meldungen
        if event_type == "seasonal_cover":
            msg = data.get("message", "Rolladen angepasst")
            is_suggestion = data.get("suggestion", False)
            if is_suggestion:
                return (
                    f"Saisonale Empfehlung: {msg}\n"
                    "Formuliere als hoeflichen Vorschlag. Max 1 Satz.\n"
                    f"Beispiel: '{_title}, die Rolladen koennten jetzt runter — draussen wird es warm.'"
                )
            return (
                f"Saisonale Aktion: {msg}\n"
                "Formuliere als kurze Info. Max 1 Satz.\n"
                "Beispiel: 'Rolladen sind angepasst — Hitzeschutz ist aktiv.'"
            )

        # Phase 10: Wartungs-Erinnerungen sanft formulieren
        if event_type == "maintenance_due":
            task_name = data.get("task", "Wartungsaufgabe")
            days = data.get("days_overdue", 0)
            desc = data.get("description", "")
            parts = [
                f"Wartungserinnerung: '{task_name}' ist faellig.",
            ]
            if days > 0:
                parts.append(f"Ueberfaellig seit {days} Tagen.")
            if desc:
                parts.append(f"Info: {desc}")
            parts.append("Formuliere eine sanfte, beilaeufige Erinnerung. Nicht dringend.")
            parts.append(f"Beispiel: 'Nebenbei, {_title}: [Aufgabe] koennte mal erledigt werden.'")
            return "\n".join(parts)

        # Tuerklingel — mit optionaler Kamera-Beschreibung + Besucher-Kontext
        if event_type == "doorbell":
            camera_desc = data.get("camera_description")
            visitor_info = data.get("visitor_info")

            # Feature 12: Besucher-Kontext in Meldung einbauen
            visitor_context = ""
            if visitor_info:
                if visitor_info.get("auto_unlocked"):
                    rec = visitor_info.get("recommendation", "")
                    visitor_context = f" {rec}" if rec else " Tuer wurde automatisch geoeffnet."
                elif visitor_info.get("expected"):
                    rec = visitor_info.get("recommendation", "")
                    visitor_context = f" {rec}" if rec else " Erwarteter Besuch."

            if camera_desc:
                return (
                    f"Tuerklingel. Kamera zeigt: {camera_desc}{visitor_context}\n"
                    "Beschreibe kurz wer/was vor der Tuer ist. Max 1-2 Saetze. Butler-Stil.\n"
                    f"Beispiel: 'Paketbote an der Tuer, {_title}. Sieht nach DHL aus.'"
                )
            return (
                f"Tuerklingel.{visitor_context}\n"
                "Melde kurz dass jemand geklingelt hat. Max 1 Satz. Butler-Stil.\n"
                f"Beispiel: 'Jemand an der Tuer, {_title}.'"
            )

        # Phase 17: Sicherheitswarnung (Threat Assessment)
        if event_type == "threat_detected":
            threat_type = data.get("type", "unbekannt")
            message = data.get("message", "Sicherheitswarnung")
            return (
                f"Sicherheitswarnung ({threat_type}): {message}\n"
                "Formuliere als dringende, sachliche Warnung. Max 2 Saetze. Butler-Stil.\n"
                f"Beispiel: '{_title}, naechtliche Bewegung im Eingangsbereich. Alle Bewohner sollten schlafen.'"
            )

        # Phase 17: Bedingte Aktion ausgefuehrt
        if event_type == "conditional_executed":
            label = data.get("label", "")
            action = data.get("action", "")
            return (
                f"Bedingte Aktion ausgefuehrt: {label} -> {action}\n"
                "Formuliere als kurze Info. Max 1 Satz. Butler-Stil.\n"
                "Beispiel: 'Die Rolladen wurden automatisch geschlossen — Regen erkannt.'"
            )

        parts.append(f"Dringlichkeit: {urgency}")

        # Wer ist gerade zuhause?
        parts.append("Formuliere eine kurze Meldung. Sprich die Bewohner mit Namen an wenn passend.")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Phase 15.4: Notification Batching
    # ------------------------------------------------------------------

    async def _run_batch_loop(self):
        """Periodisch gesammelte LOW+MEDIUM-Meldungen als Zusammenfassung senden.

        MEDIUM-Events werden nach max 10 Minuten gesendet,
        LOW-Events nach dem konfigurierten batch_interval (default 30 Min).
        """
        await asyncio.sleep(PROACTIVE_BATCH_STARTUP_DELAY)
        medium_check_interval = 10 * 60  # 10 Min fuer MEDIUM
        timer = 0

        while self._running:
            try:
                # F-033: Lock fuer shared batch_queue Zugriff
                async with self._state_lock:
                    has_items = bool(self._batch_queue)
                    has_medium = any(
                        b.get("urgency") == MEDIUM for b in self._batch_queue
                    ) if has_items else False

                if has_items:
                    # MEDIUM sofort flushen wenn Timer abgelaufen
                    if has_medium and timer >= medium_check_interval:
                        await self._flush_batch()
                        timer = 0
                    # LOW flushen nach Standard-Intervall
                    elif timer >= self.batch_interval * 60:
                        await self._flush_batch()
                        timer = 0
            except Exception as e:
                logger.error("Batch-Flush Fehler: %s", e)

            await asyncio.sleep(60)
            timer += 60

    async def _flush_batch(self):
        """Sendet alle gesammelten LOW+MEDIUM-Meldungen als eine Zusammenfassung.

        MEDIUM-Events werden im Batch hoeher priorisiert und zuerst erwaehnt.
        F-033: Lock fuer atomaren batch_queue Zugriff.
        """
        async with self._state_lock:
            if not self._batch_queue:
                return

            # Queue leeren (atomar unter Lock)
            items = self._batch_queue[:self.batch_max_items]
            self._batch_queue = self._batch_queue[self.batch_max_items:]

        # Sortieren: MEDIUM zuerst, dann LOW
        items.sort(key=lambda x: 0 if x.get("urgency") == MEDIUM else 1)

        # Quiet Hours: Batch nicht waehrend Ruhezeiten senden
        if self._is_quiet_hours():
            logger.info("Batch unterdrueckt (Quiet Hours, %d Items zurueck in Queue)", len(items))
            async with self._state_lock:
                self._batch_queue = items + self._batch_queue
            return

        # Activity-Check: Nicht bei Schlaf/Call (aber MEDIUM weniger streng)
        highest_urgency = MEDIUM if any(b.get("urgency") == MEDIUM for b in items) else LOW
        activity_result = await self.brain.activity.should_deliver(highest_urgency)
        if activity_result["suppress"]:
            logger.info("Batch unterdrueckt: Aktivitaet=%s", activity_result["activity"])
            # MEDIUM zurueck in Queue (sollen nicht verloren gehen)
            # F-033: Lock fuer atomaren batch_queue Zugriff nach await
            medium_items = [i for i in items if i.get("urgency") == MEDIUM]
            if medium_items:
                async with self._state_lock:
                    self._batch_queue = medium_items + self._batch_queue
            return

        # Zusammenfassung generieren
        medium_parts = []
        low_parts = []
        for item in items:
            line = f"- {item['description']}"
            if "message" in item.get("data", {}):
                line += f" ({item['data']['message']})"
            if item.get("urgency") == MEDIUM:
                medium_parts.append(line)
            else:
                low_parts.append(line)

        summary_parts = []
        if medium_parts:
            summary_parts.append("WICHTIG:")
            summary_parts.extend(medium_parts)
        if low_parts:
            summary_parts.append("Nebenbei:")
            summary_parts.extend(low_parts)

        # Person-aware Anrede fuer Batch
        _batch_persons = await self._get_persons_at_home()
        _batch_person = _batch_persons[0] if len(_batch_persons) == 1 else ""
        _batch_title = get_person_title(_batch_person) if _batch_person else get_person_title()
        prompt = (
            f"Du hast {len(items)} Meldung(en) gesammelt "
            f"({len(medium_parts)} wichtig, {len(low_parts)} nebensaechlich). "
            f"Fasse sie in 1-3 kurzen Saetzen zusammen. Butler-Stil. "
            f"Wichtige Meldungen zuerst erwaehnen.\n\n"
            + "\n".join(summary_parts)
            + f"\n\nBeispiel: '{_batch_title}, die Waschmaschine ist fertig und die Batterie "
            "vom Fenstersensor ist niedrig.'"
        )

        try:
            response = await self.brain.ollama.chat(
                messages=[
                    {"role": "system", "content": self._get_notification_system_prompt(person=_batch_person)},
                    {"role": "user", "content": prompt},
                ],
                model=settings.model_notify,
                think=False,
                max_tokens=150,
            )

            text = validate_notification(
                response.get("message", {}).get("content", "")
            )
            if text:
                notification_id = f"notif_{uuid.uuid4().hex[:12]}"
                await emit_proactive(text, "batch_summary", LOW, notification_id)
                await self.brain.feedback.track_notification(notification_id, "batch_summary")
                logger.info(
                    "Batch-Summary gesendet (%d Items, id: %s): %s",
                    len(items), notification_id, text,
                )

        except Exception as e:
            logger.error("Batch-Summary Fehler: %s", e)

    # ------------------------------------------------------------------
    # Phase 7.9: Saisonale Rolladen-Automatik
    # ------------------------------------------------------------------

    # ── Phase 11: Cover-Automation (Sonnenstand, Wetter, Temperatur, Zeitplan) ──

    async def _run_seasonal_loop(self):
        """Zentrale Cover-Automatik — ersetzt die alte saisonale Schleife.

        Prueft alle 15 Minuten:
        1. Wetter-Schutz (hoechste Prio): Sturm → Rolllaeden hoch, Regen → Markisen ein
        2. Sonnenstand-Tracking: Azimut+Elevation → betroffene Fenster abdunkeln
        3. Temperatur-basiert: Hitze → Sonnenschutz, Kaelte nachts → Isolierung
        4. Zeitplan + Anwesenheit: Morgens hoch, abends runter, Urlaubssimulation
        """
        await asyncio.sleep(PROACTIVE_SEASONAL_STARTUP_DELAY)

        seasonal_cfg = yaml_config.get("seasonal_actions", {})
        check_interval = seasonal_cfg.get("check_interval_minutes", 15)
        auto_level = seasonal_cfg.get("auto_execute_level", 3)
        cover_cfg = seasonal_cfg.get("cover_automation", {})
        last_action_date = ""
        last_schedule_action = ""  # "open" oder "close" (Zeitplan-Dedup)
        # Redis-Keys fuer Dedup von automatischen Aktionen
        _redis = getattr(self.brain, "memory", None)
        _redis = getattr(_redis, "redis", None) if _redis else None

        while self._running:
            try:
                now = datetime.now()
                today = now.strftime("%Y-%m-%d")

                if last_action_date != today:
                    last_schedule_action = ""
                    last_action_date = today

                states = await self.brain.ha.get_states()
                if not states:
                    await asyncio.sleep(check_interval * 60)
                    continue

                sun = self._get_sun_data(states)
                weather = self._get_weather_data(states)
                cover_profiles = self._load_cover_profiles()

                # 1. WETTER-SCHUTZ (hoechste Prioritaet)
                if cover_cfg.get("weather_protection", True):
                    await self._cover_weather_protection(
                        states, weather, cover_profiles, auto_level,
                        _redis,
                    )

                # 2. SONNENSTAND-TRACKING
                if cover_cfg.get("sun_tracking", True) and sun:
                    await self._cover_sun_tracking(
                        states, sun, weather, cover_profiles, cover_cfg,
                        auto_level, _redis,
                    )

                # 3. TEMPERATUR-BASIERT
                if cover_cfg.get("temperature_based", True):
                    await self._cover_temperature_logic(
                        states, weather, cover_cfg, auto_level, _redis,
                    )

                # 4. ZEITPLAN + ANWESENHEIT
                timing = self.brain.context_builder.get_cover_timing(states)
                last_schedule_action = await self._cover_schedule_logic(
                    states, timing, cover_cfg, auto_level,
                    last_schedule_action, _redis,
                )

            except Exception as e:
                logger.error("Cover-Automation Fehler: %s", e)

            await asyncio.sleep(check_interval * 60)

    # ── Cover-Automation Hilfsmethoden ──────────────────────

    @staticmethod
    def _get_sun_data(states: list) -> dict:
        """Extrahiert Sonnen-Daten (elevation, azimuth) aus HA states."""
        for s in (states or []):
            if s.get("entity_id") == "sun.sun":
                attrs = s.get("attributes", {})
                return {
                    "state": s.get("state", ""),
                    "elevation": attrs.get("elevation", 0),
                    "azimuth": attrs.get("azimuth", 180),
                }
        return {}

    @staticmethod
    def _get_weather_data(states: list) -> dict:
        """Extrahiert Wetter-Daten aus HA states."""
        for s in (states or []):
            if s.get("entity_id", "").startswith("weather."):
                attrs = s.get("attributes", {})
                try:
                    temp = float(attrs.get("temperature", 10))
                except (ValueError, TypeError):
                    temp = 10
                try:
                    wind = float(attrs.get("wind_speed", 0))
                except (ValueError, TypeError):
                    wind = 0
                return {
                    "temperature": temp,
                    "wind_speed": wind,
                    "condition": s.get("state", ""),
                }
        return {}

    @staticmethod
    def _load_cover_profiles() -> list:
        """Laedt Cover-Profile aus room_profiles.yaml (gecached)."""
        data = _get_room_profiles_cached()
        return data.get("cover_profiles", {}).get("covers", [])

    async def _auto_cover_action(
        self, entity_id: str, position: int, reason: str,
        auto_level: int, redis_client=None,
    ) -> bool:
        """Fuehrt eine automatische Cover-Aktion aus (oder schlaegt vor).

        Dedup: Gleiche entity+position nicht doppelt am selben Tag.
        """
        level = self.brain.autonomy.level

        # Dedup per Redis (30 Min Cooldown — kuerzer als vorher 1h,
        # damit Sonne nach kurzer Wolkendecke erneut Sonnenschutz ausloesen kann)
        if redis_client:
            dedup_key = f"mha:cover:auto:{entity_id}:{position}"
            already = await redis_client.get(dedup_key)
            if already:
                return False
            await redis_client.set(dedup_key, "1", ex=1800)  # 30 Min Cooldown

        if level >= auto_level:
            try:
                states = await self.brain.ha.get_states()
                state = next((s for s in (states or []) if s.get("entity_id") == entity_id), {})
                if not await self.brain.executor._is_safe_cover(entity_id, state):
                    return False
                await self.brain.ha.call_service(
                    "cover", "set_cover_position",
                    {"entity_id": entity_id, "position": position},
                )
                logger.info("Cover-Auto: %s -> %d%% (%s)", entity_id, position, reason)
                return True
            except Exception as e:
                logger.error("Cover-Auto Fehler fuer %s: %s", entity_id, e)
                return False
        else:
            desc = "oeffnen" if position > 50 else "schliessen"
            await self._notify("seasonal_cover", LOW, {
                "action": desc,
                "message": f"Rollladen {desc}? ({reason})",
                "suggestion": True,
            })
            return False

    async def _cover_weather_protection(
        self, states, weather, profiles, auto_level, redis_client,
    ):
        """Sturm → Rolllaeden HOCH. Regen → Markisen EINFAHREN."""
        seasonal_cfg = yaml_config.get("seasonal_actions", {})
        cover_cfg = seasonal_cfg.get("cover_automation", {})
        storm_speed = cover_cfg.get("storm_wind_speed", 50)
        wind = weather.get("wind_speed", 0)
        condition = weather.get("condition", "")

        # Sturmschutz: Alle Rolllaeden HOCH (damit Lamellen nicht brechen)
        if wind >= storm_speed:
            notified = False
            for s in (states or []):
                eid = s.get("entity_id", "")
                if not eid.startswith("cover."):
                    continue
                if not await self.brain.executor._is_safe_cover(eid, s):
                    continue
                # Markisen UND Rolllaeden hoch
                acted = await self._auto_cover_action(
                    eid, 100, f"Sturmschutz (Wind {wind} km/h)",
                    auto_level, redis_client,
                )
                if acted and not notified:
                    await self._notify("weather_cover_protection", MEDIUM, {
                        "message": f"Sturmwarnung: Rolllaeden zum Schutz hochgefahren (Wind {wind} km/h)",
                    })
                    notified = True

        # Regen/Hagel: Nur Markisen einfahren (Position 0)
        rp_data = _get_room_profiles_cached()
        markise_cfg = rp_data.get("markisen", {})
        markise_wind = markise_cfg.get("wind_retract_speed", 40)
        rain_retract = markise_cfg.get("rain_retract", True)

        rain_conditions = {"rainy", "pouring", "hail", "lightning-rainy"}
        if (rain_retract and condition in rain_conditions) or wind >= markise_wind:
            for s in (states or []):
                eid = s.get("entity_id", "")
                if not eid.startswith("cover."):
                    continue
                if self.brain.executor._is_markise(eid, s):
                    await self._auto_cover_action(
                        eid, 0,
                        f"Markise eingefahren ({condition}, Wind {wind} km/h)",
                        auto_level, redis_client,
                    )

    async def _cover_sun_tracking(
        self, states, sun, weather, profiles, cover_cfg, auto_level, redis_client,
    ):
        """Azimut-basiert: Betroffene Fenster abdunkeln bei Hitze + Sonne."""
        elevation = sun.get("elevation", 0)
        if elevation <= 0:
            return  # Sonne unter Horizont — nichts zu tun

        azimuth = sun.get("azimuth", 180)
        temp = weather.get("temperature", 20)
        heat_temp = cover_cfg.get("heat_protection_temp", 26)

        for cover in profiles:
            entity_id = cover.get("entity_id")
            if not entity_id or not cover.get("allow_auto"):
                continue
            if not cover.get("heat_protection"):
                continue

            start = cover.get("sun_exposure_start", 0)
            end = cover.get("sun_exposure_end", 360)

            # Fenster bekommt direkte Sonne UND Temperatur > Schwelle
            # Wraparound fuer Nordfenster (z.B. start=315, end=45 → NW bis NE)
            if start <= end:
                sun_hitting = start <= azimuth <= end
            else:
                sun_hitting = azimuth >= start or azimuth <= end
            if sun_hitting and temp >= heat_temp:
                await self._auto_cover_action(
                    entity_id, 20,
                    f"Sonnenschutz ({temp}°C, Azimut {azimuth}°)",
                    auto_level, redis_client,
                )
            elif not sun_hitting:
                # Sonne nicht mehr auf diesem Fenster — wieder oeffnen
                # (nur wenn vorher wegen Sonne geschlossen)
                if redis_client:
                    key = f"mha:cover:auto:{entity_id}:20"
                    was_sun_closed = await redis_client.get(key)
                    if was_sun_closed:
                        await self._auto_cover_action(
                            entity_id, 100,
                            "Sonne vorbei — Rollladen wieder offen",
                            auto_level, redis_client,
                        )

    async def _cover_temperature_logic(
        self, states, weather, cover_cfg, auto_level, redis_client,
    ):
        """Kaelte nachts → runter (Isolierung). Hitze → Sonnenschutz."""
        temp = weather.get("temperature", 10)
        hour = datetime.now().hour
        frost_temp = cover_cfg.get("frost_protection_temp", 3)
        night_insulation = cover_cfg.get("night_insulation", True)

        # Nachts + kalt → alle Rolllaeden runter (Isolierung)
        if night_insulation and (22 <= hour or hour < 6) and temp <= frost_temp:
            for s in (states or []):
                eid = s.get("entity_id", "")
                if not eid.startswith("cover."):
                    continue
                if not await self.brain.executor._is_safe_cover(eid, s):
                    continue
                if self.brain.executor._is_markise(eid, s):
                    continue  # Markisen bleiben raus
                await self._auto_cover_action(
                    eid, 0,
                    f"Nacht-Isolierung ({temp}°C aussen)",
                    auto_level, redis_client,
                )

    async def _cover_schedule_logic(
        self, states, timing, cover_cfg, auto_level,
        last_schedule_action, redis_client,
    ) -> str:
        """Morgens hoch, abends runter, Urlaubssimulation."""
        now = datetime.now()
        current_minutes = now.hour * 60 + now.minute
        open_time = timing.get("open_time", "07:30")
        close_time = timing.get("close_time", "19:00")
        season = timing.get("season", "")
        reason = timing.get("reason", "")

        try:
            ot = open_time.split(":")
            open_min = int(ot[0]) * 60 + int(ot[1])
            ct = close_time.split(":")
            close_min = int(ct[0]) * 60 + int(ct[1])
        except (ValueError, IndexError):
            open_min, close_min = 450, 1140

        tolerance = 15

        # Morgens: oeffnen (nur wenn Bett frei)
        if (last_schedule_action != "open"
                and abs(current_minutes - open_min) <= tolerance):
            if await self._is_bed_occupied(states):
                logger.info("Cover-Zeitplan: Oeffnung uebersprungen — Bett belegt")
            else:
                count = 0
                for s in (states or []):
                    eid = s.get("entity_id", "")
                    if not eid.startswith("cover."):
                        continue
                    if not await self.brain.executor._is_safe_cover(eid, s):
                        continue
                    if self.brain.executor._is_markise(eid, s):
                        continue
                    acted = await self._auto_cover_action(
                        eid, 100, f"Morgens oeffnen ({reason})",
                        auto_level, redis_client,
                    )
                    if acted:
                        count += 1
                if count > 0:
                    await self._notify("seasonal_cover", LOW, {
                        "action": "open",
                        "message": f"Rolllaeden geoeffnet ({reason})",
                        "count": count,
                    })
                return "open"

        # Abends: schliessen
        elif (last_schedule_action != "close"
                and abs(current_minutes - close_min) <= tolerance):
            count = 0
            for s in (states or []):
                eid = s.get("entity_id", "")
                if not eid.startswith("cover."):
                    continue
                if not await self.brain.executor._is_safe_cover(eid, s):
                    continue
                if self.brain.executor._is_markise(eid, s):
                    continue
                acted = await self._auto_cover_action(
                    eid, 0, f"Abends schliessen ({reason})",
                    auto_level, redis_client,
                )
                if acted:
                    count += 1
            if count > 0:
                await self._notify("seasonal_cover", LOW, {
                    "action": "close",
                    "message": f"Rolllaeden geschlossen ({reason})",
                    "count": count,
                })
            return "close"

        # Urlaubs-Simulation: Zufaellige Zeiten wenn vacation_mode aktiv
        if cover_cfg.get("presence_simulation", True):
            vacation_entity = cover_cfg.get("vacation_mode_entity", "")
            if not vacation_entity:
                logger.debug("Urlaubs-Simulation: vacation_mode_entity nicht konfiguriert — uebersprungen")
            elif vacation_entity:
                for s in (states or []):
                    if s.get("entity_id") == vacation_entity and s.get("state") == "on":
                        import random
                        # Morgens zufaellig oeffnen
                        if now.hour in (7, 8) and random.random() < 0.3:
                            for cs in (states or []):
                                eid = cs.get("entity_id", "")
                                if eid.startswith("cover.") and await self.brain.executor._is_safe_cover(eid, cs):
                                    if not self.brain.executor._is_markise(eid, cs):
                                        await self._auto_cover_action(
                                            eid, 100, "Urlaubssimulation (morgens)",
                                            auto_level, redis_client,
                                        )
                        # Abends zufaellig schliessen
                        elif now.hour in (19, 20, 21) and random.random() < 0.3:
                            for cs in (states or []):
                                eid = cs.get("entity_id", "")
                                if eid.startswith("cover.") and await self.brain.executor._is_safe_cover(eid, cs):
                                    if not self.brain.executor._is_markise(eid, cs):
                                        await self._auto_cover_action(
                                            eid, 0, "Urlaubssimulation (abends)",
                                            auto_level, redis_client,
                                        )
                        break

        return last_schedule_action

    async def _execute_seasonal_cover(
        self, action: str, position: int, season: str, reason: str, auto_level: int,
    ):
        """Kompatibilitaets-Wrapper fuer alte Aufrufe (z.B. aus routine_engine)."""
        states = await self.brain.ha.get_states()
        for s in (states or []):
            eid = s.get("entity_id", "")
            if eid.startswith("cover."):
                if not await self.brain.executor._is_safe_cover(eid, s):
                    continue
                await self._auto_cover_action(eid, position, reason, auto_level)

    # ── Phase 11: Saugroboter-Automatik ────────────────────

    async def _run_vacuum_automation(self):
        """Saugroboter-Automatik: wenn niemand zuhause + keine Stoerung."""
        await asyncio.sleep(PROACTIVE_SEASONAL_STARTUP_DELAY + 120)  # Spaeter starten

        vacuum_cfg = yaml_config.get("vacuum", {})
        auto_cfg = vacuum_cfg.get("auto_clean", {})
        robots = vacuum_cfg.get("robots", {})
        _redis = getattr(self.brain, "memory", None)
        _redis = getattr(_redis, "redis", None) if _redis else None

        while self._running:
            try:
                if not auto_cfg.get("when_nobody_home"):
                    await asyncio.sleep(900)
                    continue

                # Zeitfenster pruefen
                hour = datetime.now().hour
                start_h = auto_cfg.get("preferred_time_start", 10)
                end_h = auto_cfg.get("preferred_time_end", 16)
                if not (start_h <= hour < end_h):
                    await asyncio.sleep(900)
                    continue

                # Niemand zuhause?
                states = await self.brain.ha.get_states()
                persons_home = [
                    s for s in (states or [])
                    if s.get("entity_id", "").startswith("person.")
                    and s.get("state") == "home"
                ]
                if persons_home:
                    await asyncio.sleep(900)
                    continue

                # Aktive Kalender-Events pruefen (z.B. "meeting" im Titel)
                # HINWEIS: "schlafen" in not_during ist hier wirkungslos, da
                # der Check nur laeuft wenn niemand zuhause ist. "schlafen"
                # sollte aus der not_during-Config entfernt werden.
                not_during = auto_cfg.get("not_during", [])
                blocking = False
                for s in (states or []):
                    eid = s.get("entity_id", "")
                    if eid.startswith("calendar.") and s.get("state") == "on":
                        title = (s.get("attributes", {}).get("message") or "").lower()
                        if any(kw in title for kw in not_during):
                            blocking = True
                            break
                if blocking:
                    await asyncio.sleep(900)
                    continue

                # Mindestabstand pro Roboter pruefen
                min_hours = auto_cfg.get("min_hours_between", 24)
                for floor, robot in robots.items():
                    eid = robot.get("entity_id")
                    if not eid:
                        continue

                    if _redis:
                        last_key = f"mha:vacuum:{floor}:last_auto_clean"
                        last = await _redis.get(last_key)
                        if last:
                            try:
                                hours_since = (time.time() - float(last)) / 3600
                                if hours_since < min_hours:
                                    continue
                            except (ValueError, TypeError):
                                pass

                    # Starten!
                    await self.brain.ha.call_service("vacuum", "start", {"entity_id": eid})
                    if _redis:
                        await _redis.set(f"mha:vacuum:{floor}:last_auto_clean", str(time.time()))
                    nickname = robot.get("nickname", f"Saugroboter {floor.upper()}")
                    await self._notify("vacuum_auto_start", LOW, {
                        "message": f"{nickname} startet automatisch (niemand zuhause)",
                    })
                    logger.info("Vacuum-Auto: %s gestartet (%s)", eid, floor)

                # Wartung pruefen (1x pro Durchlauf)
                await self._check_vacuum_maintenance(robots, _redis)

            except Exception as e:
                logger.error("Vacuum-Automation Fehler: %s", e)

            await asyncio.sleep(900)  # 15 Minuten

    async def _check_vacuum_maintenance(self, robots: dict, redis_client=None):
        """Prueft Filter/Buerste/Mopp Verschleiss und erinnert."""
        maint_cfg = yaml_config.get("vacuum", {}).get("maintenance", {})
        if not maint_cfg.get("enabled", True):
            return
        warn_pct = maint_cfg.get("warn_at_percent", 10)

        for floor, robot in robots.items():
            eid = robot.get("entity_id")
            if not eid:
                continue

            state = await self.brain.ha.get_state(eid)
            if not state:
                continue
            attrs = state.get("attributes", {})
            nickname = robot.get("nickname", f"Saugroboter {floor.upper()}")

            # Mehrere gaengige Attribut-Namen pruefen (Dreame-Addon vs. Valetudo vs. Xiaomi Cloud)
            checks = {
                "Filter": attrs.get("filter_left") or attrs.get("filter_life_level"),
                "Hauptbuerste": attrs.get("main_brush_left") or attrs.get("brush_life_level") or attrs.get("main_brush_life_level"),
                "Seitenbuerste": attrs.get("side_brush_left") or attrs.get("side_brush_life_level"),
                "Mopp": attrs.get("mop_left") or attrs.get("mop_life_level"),
            }

            for part, remaining in checks.items():
                if remaining is None:
                    continue
                try:
                    remaining = int(remaining)
                except (ValueError, TypeError):
                    continue
                if remaining > warn_pct:
                    continue

                # Dedup: Nur 1x pro Tag pro Teil warnen
                if redis_client:
                    dedup_key = f"mha:vacuum:maint:{floor}:{part}"
                    already = await redis_client.get(dedup_key)
                    if already:
                        continue
                    await redis_client.set(dedup_key, "1", ex=86400)

                await self._notify("vacuum_maintenance", MEDIUM, {
                    "message": f"{nickname}: {part} bei {remaining}% — Wechsel empfohlen",
                })
                logger.info("Vacuum-Wartung: %s %s bei %d%%", floor, part, remaining)

    # ------------------------------------------------------------------
    # Bettbelegung
    # ------------------------------------------------------------------

    async def _is_bed_occupied(self, states=None) -> bool:
        """Prueft ob ein Bettbelegungssensor aktiv ist (jemand schlaeft)."""
        try:
            if states is None:
                states = await self.brain.ha.get_states()
            bed_sensors = [
                s for s in (states or [])
                if s.get("entity_id", "").startswith("binary_sensor.")
                and s.get("attributes", {}).get("device_class") == "occupancy"
                and any(kw in s.get("entity_id", "").lower()
                        for kw in ("bett", "bed", "matratze", "mattress"))
            ]
            if not bed_sensors:
                # Fallback: Occupancy-Sensoren in Schlafzimmern
                bed_sensors = [
                    s for s in (states or [])
                    if s.get("entity_id", "").startswith("binary_sensor.")
                    and s.get("attributes", {}).get("device_class") == "occupancy"
                    and any(kw in s.get("entity_id", "").lower()
                            for kw in ("schlafzimmer", "bedroom"))
                ]
            if bed_sensors:
                return any(s.get("state") == "on" for s in bed_sensors)
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------
    # Notfall-Protokolle
    # ------------------------------------------------------------------

    async def _execute_emergency_protocol(self, protocol_name: str):
        """Fuehrt ein konfiguriertes Notfall-Protokoll aus.

        Protokolle werden in settings.yaml definiert unter emergency_protocols.
        Beispiel:
            emergency_protocols:
              fire:
                actions:
                  - {domain: light, service: turn_on, target: all}
                  - {domain: lock, service: unlock, target: all}
                  - {domain: notify, service: notify, data: {message: "FEUERALARM!"}}
        """
        protocol = self._emergency_protocols.get(protocol_name)
        if not protocol:
            logger.debug("Kein Notfall-Protokoll fuer '%s' konfiguriert", protocol_name)
            return

        actions = protocol.get("actions", [])
        if not actions:
            return

        logger.warning("NOTFALL-PROTOKOLL '%s' wird ausgefuehrt (%d Aktionen)",
                        protocol_name, len(actions))

        executed = []
        for action in actions:
            domain = action.get("domain", "")
            service = action.get("service", "")
            target = action.get("target", "")
            data = action.get("data", {})

            if not domain or not service:
                continue

            try:
                if target == "all":
                    # Alle Entities dieser Domain
                    states = await self.brain.ha.get_states()
                    for s in (states or []):
                        eid = s.get("entity_id", "")
                        if eid.startswith(f"{domain}."):
                            await self.brain.ha.call_service(
                                domain, service,
                                {"entity_id": eid, **data},
                            )
                            executed.append(eid)
                elif target:
                    await self.brain.ha.call_service(
                        domain, service,
                        {"entity_id": target, **data},
                    )
                    executed.append(target)
                else:
                    await self.brain.ha.call_service(domain, service, data)
                    executed.append(f"{domain}.{service}")
            except Exception as e:
                logger.error("Notfall-Aktion fehlgeschlagen: %s.%s -> %s", domain, service, e)

        if executed:
            logger.warning("Notfall-Protokoll '%s': %d Aktionen ausgefuehrt: %s",
                            protocol_name, len(executed), executed)

    # ------------------------------------------------------------------
    # Phase 17: Threat Assessment Loop
    # ------------------------------------------------------------------

    async def _run_threat_assessment_loop(self):
        """Periodischer Sicherheits- + Energie-Check."""
        await asyncio.sleep(PROACTIVE_THREAT_STARTUP_DELAY)

        while self._running:
            # Threat Assessment
            try:
                threats = await self.brain.threat_assessment.assess_threats()
                for threat in threats:
                    urgency_map = {
                        "critical": CRITICAL,
                        "high": HIGH,
                        "medium": MEDIUM,
                        "low": LOW,
                    }
                    urgency = urgency_map.get(threat.get("urgency", "medium"), MEDIUM)
                    await self._notify("threat_detected", urgency, {
                        "type": threat.get("type", "unknown"),
                        "message": threat.get("message", ""),
                        "entity": threat.get("entity", ""),
                    })

                    # Eskalation fuer kritische Bedrohungen
                    if threat.get("urgency") == "critical":
                        try:
                            actions = await self.brain.threat_assessment.escalate_threat(threat)
                            if actions:
                                logger.info("Threat Eskalation: %s", ", ".join(actions))
                        except Exception as esc_err:
                            logger.warning("Threat Eskalation fehlgeschlagen: %s", esc_err)
            except Exception as e:
                logger.error("Threat Assessment Fehler: %s", e)

            # Predictive Foresight (Kalender + Wetter + HA-States)
            try:
                predictions = await self.brain.get_foresight_predictions()
                for pred in predictions:
                    urgency_map = {
                        "critical": CRITICAL,
                        "high": HIGH,
                        "medium": MEDIUM,
                        "low": LOW,
                    }
                    urgency = urgency_map.get(pred.get("urgency", "low"), LOW)
                    await self._notify(pred.get("type", "foresight"), urgency, {
                        "message": pred.get("message", ""),
                    })
            except Exception as e:
                logger.debug("Foresight Fehler: %s", e)

            # Energy Events pruefen + taegliches Kostentracking
            try:
                if hasattr(self.brain, "energy_optimizer") and self.brain.energy_optimizer.enabled:
                    energy_alerts = await self.brain.energy_optimizer.check_energy_events()
                    for alert in energy_alerts:
                        urgency = LOW  # Energie-Alerts sind immer LOW
                        await self._notify(alert.get("type", "energy_event"), urgency, {
                            "message": alert.get("message", ""),
                        })

                    # Taegliches Kostentracking (einmal pro Tag via Redis-Cooldown)
                    if self.brain.memory.redis:
                        tracked_key = "mha:energy:daily_tracked"
                        from datetime import datetime as _dt
                        today = _dt.now().strftime("%Y-%m-%d")
                        last_tracked = await self.brain.memory.redis.get(tracked_key)
                        if isinstance(last_tracked, bytes):
                            last_tracked = last_tracked.decode("utf-8", errors="ignore")
                        if not last_tracked or last_tracked != today:
                            await self.brain.energy_optimizer.track_daily_cost()
                            await self.brain.memory.redis.setex(tracked_key, 86400, today)
            except Exception as e:
                logger.debug("Energy Check Fehler: %s", e)

            await asyncio.sleep(PROACTIVE_THREAT_CHECK_INTERVAL)

    # ------------------------------------------------------------------
    # Ambient Presence: Jarvis ist immer da
    # ------------------------------------------------------------------

    async def _run_ambient_presence_loop(self):
        """Periodisches Status-Fluestern — Jarvis ist eine Praesenz, kein totes System."""
        import random

        ambient_cfg = yaml_config.get("ambient_presence", {})
        interval = ambient_cfg.get("interval_minutes", 60) * 60
        quiet_start = ambient_cfg.get("quiet_start", 22)
        quiet_end = ambient_cfg.get("quiet_end", 7)
        report_weather = ambient_cfg.get("report_weather", True)
        report_energy = ambient_cfg.get("report_energy", True)
        all_quiet_prob = ambient_cfg.get("all_quiet_probability", 0.2)

        await asyncio.sleep(PROACTIVE_AMBIENT_CHECK_INTERVAL)

        while self._running:
            try:
                hour = datetime.now().hour

                # Quiet Hours respektieren
                if quiet_start <= hour or hour < quiet_end:
                    await asyncio.sleep(interval)
                    continue

                # Nur bei "relaxing" Activity sprechen
                try:
                    detection = await self.brain.activity.detect_activity()
                    activity = detection.get("activity", "")
                except Exception:
                    activity = ""

                if activity != "relaxing":
                    await asyncio.sleep(interval)
                    continue

                # Autonomie-Level pruefen (mindestens Level 2)
                if self.brain.autonomy.level < 2:
                    await asyncio.sleep(interval)
                    continue

                # Status-Info sammeln
                observations = []
                states = await self.brain.ha.get_states()

                if states and report_weather:
                    for s in states:
                        if s.get("entity_id", "").startswith("weather."):
                            condition = s.get("state", "")
                            temp = s.get("attributes", {}).get("temperature")
                            if condition and temp is not None:
                                observations.append(f"Wetter: {condition}, {temp} Grad")
                            break

                if states and report_energy and hasattr(self.brain, "energy_optimizer") \
                        and self.brain.energy_optimizer.has_configured_entities:
                    for s in states:
                        eid = s.get("entity_id", "")
                        if "solar" in eid.lower() and "power" in eid.lower():
                            try:
                                power = float(s.get("state", 0))
                                if power > 100:
                                    observations.append(f"Solar: {power:.0f}W Ertrag")
                            except (ValueError, TypeError):
                                pass

                # Nachricht bauen
                if observations:
                    msg = " | ".join(observations)
                elif random.random() < all_quiet_prob:
                    _quiet_persons = await self._get_persons_at_home()
                    _quiet_person = _quiet_persons[0] if len(_quiet_persons) == 1 else ""
                    msg = f"Alles ruhig, {get_person_title(_quiet_person) if _quiet_person else get_person_title()}."
                else:
                    # Nichts zu berichten, nichts sagen
                    await asyncio.sleep(interval)
                    continue

                # Via Notification-System senden (nutzt Silence Matrix + Batching)
                await self._notify("ambient_status", LOW, {
                    "message": msg,
                })

            except Exception as e:
                logger.debug("Ambient Presence Fehler: %s", e)

            await asyncio.sleep(interval)
