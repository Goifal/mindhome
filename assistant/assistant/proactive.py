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
import uuid
from datetime import datetime, timedelta
from typing import Optional

import aiohttp

from .config import settings, yaml_config
from .websocket import emit_proactive

logger = logging.getLogger(__name__)


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

        # Phase 15.4: Notification Batching (LOW sammeln)
        batch_cfg = proactive_cfg.get("batching", {})
        self.batch_enabled = batch_cfg.get("enabled", True)
        self.batch_interval = batch_cfg.get("interval_minutes", 30)
        self.batch_max_items = batch_cfg.get("max_items", 10)
        self._batch_queue: list[dict] = []

        # Phase 7.1: Morning Briefing Auto-Trigger
        mb_cfg = yaml_config.get("routines", {}).get("morning_briefing", {})
        self._mb_enabled = mb_cfg.get("enabled", True)
        self._mb_window_start = mb_cfg.get("window_start_hour", 6)
        self._mb_window_end = mb_cfg.get("window_end_hour", 10)
        self._mb_triggered_today = False
        self._mb_last_date = ""

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

            # LOW - Melden wenn entspannt
            "energy_price_low": (LOW, "Strom ist guenstig"),
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
            "energy_price_low": (LOW, "Guenstiger Strom"),
            "energy_price_high": (LOW, "Teurer Strom"),
            "solar_surplus": (LOW, "Solar-Ueberschuss"),
        }

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
                    await asyncio.sleep(10)  # Reconnect nach 10s

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
        event_type = event.get("event_type", "")
        event_data = event.get("data", {})

        if event_type == "state_changed":
            await self._handle_state_change(event_data)
        elif event_type == "mindhome_event":
            await self._handle_mindhome_event(event_data)

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

        # Tuerklingel
        elif "doorbell" in entity_id and new_val == "on":
            await self._notify("doorbell", MEDIUM, {
                "entity": entity_id,
            })

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

        # Phase 7.1 + 10.1: Bewegung erkannt → Morning Briefing + Musik-Follow
        elif entity_id.startswith("binary_sensor.") and "motion" in entity_id and new_val == "on":
            await self._check_morning_briefing()
            await self._check_music_follow(entity_id)

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

    async def _check_morning_briefing(self):
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

                self._mb_triggered_today = True
                await emit_proactive(text, "morning_briefing", MEDIUM)
                logger.info("Morning Briefing automatisch geliefert")

                # B3: Pending Tages-Zusammenfassung nach Briefing liefern
                if self.brain.memory.redis:
                    pending = await self.brain.memory.redis.get("jarvis:pending_summary")
                    if pending:
                        summary = pending.decode() if isinstance(pending, bytes) else pending
                        await asyncio.sleep(3)  # Kurze Pause nach dem Briefing
                        await emit_proactive(
                            f"Uebrigens, gestern zusammengefasst: {summary}",
                            "daily_summary", LOW,
                        )
                        await self.brain.memory.redis.delete("jarvis:pending_summary")
                        logger.info("Pending Tages-Zusammenfassung zugestellt")
        except Exception as e:
            logger.error("Morning Briefing Auto-Trigger Fehler: %s", e)

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
                if datetime.now() - last_dt < timedelta(minutes=15):
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
                if datetime.now() - last_dt < timedelta(minutes=10):
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

        # Phase 15.4: LOW-Meldungen batchen statt sofort senden
        if urgency == LOW and self.batch_enabled:
            description = self.event_handlers.get(event_type, (MEDIUM, event_type))[1]
            self._batch_queue.append({
                "event_type": event_type,
                "description": description,
                "data": data,
                "time": datetime.now().isoformat(),
            })
            if len(self._batch_queue) >= self.batch_max_items:
                # Queue voll — sofort senden
                asyncio.create_task(self._flush_batch())
            logger.debug("LOW-Meldung gequeued [%s]: %s (%d in Queue)",
                         event_type, description, len(self._batch_queue))
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
        prompt = self._build_notification_prompt(event_type, description, data, urgency)

        try:
            response = await self.brain.ollama.chat(
                messages=[
                    {"role": "system", "content": self._get_notification_system_prompt()},
                    {"role": "user", "content": prompt},
                ],
                model=settings.model_fast,
            )

            text = response.get("message", {}).get("content", description)

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
                if ("window" in eid or "door" in eid) and s.get("state") == "on":
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
                    {"role": "system", "content": self._get_notification_system_prompt()},
                    {"role": "user", "content": prompt},
                ],
                model=settings.model_fast,
            )
            return response.get("message", {}).get("content", "Alles ruhig, Sir.")
        except Exception as e:
            logger.error("Fehler beim Status-Bericht: %s", e)
            return "Status-Abfrage fehlgeschlagen. Systeme pruefen."

    def _get_person_title(self, person_name: str) -> str:
        """Gibt die korrekte Anrede fuer eine Person zurueck (Jarvis-Style)."""
        person_cfg = yaml_config.get("persons", {})
        titles = person_cfg.get("titles", {})

        # Hauptbenutzer = "Sir"
        if person_name.lower() == settings.user_name.lower():
            return titles.get(person_name.lower(), "Sir")
        # Andere: Titel aus Config oder Vorname
        return titles.get(person_name.lower(), person_name)

    def _build_status_report_prompt(self, status: dict) -> str:
        """Baut den Prompt fuer einen Status-Bericht."""
        person = status.get("person", "User")
        title = self._get_person_title(person)
        parts = [f"{person} (Anrede: \"{title}\") ist gerade angekommen. Erstelle einen kurzen Willkommens-Status-Bericht."]
        parts.append(f"WICHTIG: Sprich die Person mit \"{title}\" an, NICHT mit dem Vornamen.")

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

    def _get_notification_system_prompt(self) -> str:
        return f"""Du bist {settings.assistant_name}, die KI dieses Hauses.
Dein Stil: Souveraen, knapp, trocken-humorvoll. Wie ein brillanter britischer Butler.
Formuliere KURZE proaktive Meldungen. Maximal 1-3 Saetze. Deutsch.
Den Hauptbenutzer sprichst du mit "Sir" an, NICHT mit dem Vornamen.
Andere Haushaltsmitglieder mit ihrem Namen oder Titel.
Beispiele:
- "Es hat geklingelt, Sir."
- "Die Waschmaschine ist fertig. Nur falls es jemanden interessiert."
- "Willkommen zurueck, Sir. 22 Grad, alles ruhig."
- "Willkommen, Ms. Lisa. Sir ist im Buero."
- "Achtung: Rauchmelder Keller. Sofort pruefen."
- "Sir, der Strom ist gerade guenstig. Guter Zeitpunkt fuer die Waschmaschine."
"""

    # ------------------------------------------------------------------
    # Alert-Personality: Meldungen im Jarvis-Stil reformulieren
    # ------------------------------------------------------------------

    async def format_with_personality(self, raw_message: str, urgency: str = "low") -> str:
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
                    {"role": "system", "content": self._get_notification_system_prompt()},
                    {"role": "user", "content": (
                        f"Formuliere diese Meldung im Jarvis-Stil um (1-2 Saetze, Deutsch).\n"
                        f"Dringlichkeit: {urgency}\n"
                        f"Original: {raw_message}"
                    )},
                ],
                model=settings.model_fast,
            )
            text = response.get("message", {}).get("content", "").strip()
            return text if text else raw_message
        except Exception as e:
            logger.debug("Alert-Personality Fehler (Fallback auf Original): %s", e)
            return raw_message

    # ------------------------------------------------------------------
    # Phase 10: Periodische Diagnostik
    # ------------------------------------------------------------------

    async def _run_diagnostics_loop(self):
        """Periodischer Diagnostik-Check (Entity-Watchdog + Wartungs-Erinnerungen)."""
        # Initial 2 Minuten warten bis alles hochgefahren ist
        await asyncio.sleep(120)

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
        parts = [f"Event: {description}"]

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

        # Phase 7.4: Abschied mit Sicherheits-Check
        if data.get("departure_check"):
            person = data.get("person", "User")
            title = self._get_person_title(person)
            parts = [
                f"{person} (Anrede: \"{title}\") verlaesst gerade das Haus.",
                f"Formuliere einen kurzen Abschied. Sprich mit \"{title}\" an.",
                "Erwaehne KURZ ob alles gesichert ist (Fenster, Tueren, Alarm).",
                "Max 2 Saetze. Deutsch. Butler-Stil.",
            ]
            return "\n".join(parts)

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
                    "Beispiel: 'Sir, die Rolladen koennten jetzt runter — draussen wird es warm.'"
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
            parts.append("Beispiel: 'Nebenbei, Sir: [Aufgabe] koennte mal erledigt werden.'")
            return "\n".join(parts)

        # Phase 17: Sicherheitswarnung (Threat Assessment)
        if event_type == "threat_detected":
            threat_type = data.get("type", "unbekannt")
            message = data.get("message", "Sicherheitswarnung")
            return (
                f"Sicherheitswarnung ({threat_type}): {message}\n"
                "Formuliere als dringende, sachliche Warnung. Max 2 Saetze. Butler-Stil.\n"
                "Beispiel: 'Sir, naechtliche Bewegung im Eingangsbereich. Alle Bewohner sollten schlafen.'"
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
        """Periodisch gesammelte LOW-Meldungen als Zusammenfassung senden."""
        await asyncio.sleep(60)  # 1 Min. warten

        while self._running:
            try:
                if self._batch_queue:
                    await self._flush_batch()
            except Exception as e:
                logger.error("Batch-Flush Fehler: %s", e)

            await asyncio.sleep(self.batch_interval * 60)

    async def _flush_batch(self):
        """Sendet alle gesammelten LOW-Meldungen als eine Zusammenfassung."""
        if not self._batch_queue:
            return

        # Queue leeren (atomar)
        items = self._batch_queue[:self.batch_max_items]
        self._batch_queue = self._batch_queue[self.batch_max_items:]

        # Activity-Check: Nicht bei Schlaf/Call
        activity_result = await self.brain.activity.should_deliver(LOW)
        if activity_result["suppress"]:
            logger.info("Batch unterdrueckt: Aktivitaet=%s", activity_result["activity"])
            return

        # Zusammenfassung generieren
        summary_parts = []
        for item in items:
            summary_parts.append(f"- {item['description']}")
            if "message" in item.get("data", {}):
                summary_parts.append(f"  ({item['data']['message']})")

        prompt = (
            f"Du hast {len(items)} nebensaechliche Meldung(en) gesammelt. "
            f"Fasse sie in 1-3 kurzen Saetzen zusammen. Beilaeufig, Butler-Stil.\n\n"
            + "\n".join(summary_parts)
            + "\n\nBeispiel: 'Nebenbei, Sir: Der Strom war guenstig, "
            "ein Sensor haengt, und die Wartung ruft.'"
        )

        try:
            response = await self.brain.ollama.chat(
                messages=[
                    {"role": "system", "content": self._get_notification_system_prompt()},
                    {"role": "user", "content": prompt},
                ],
                model=settings.model_fast,
            )

            text = response.get("message", {}).get("content", "")
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

    async def _run_seasonal_loop(self):
        """Periodisch Rolladen-Timing pruefen und saisonal anpassen."""
        await asyncio.sleep(180)  # 3 Min. warten bis System stabil

        seasonal_cfg = yaml_config.get("seasonal_actions", {})
        check_interval = seasonal_cfg.get("check_interval_minutes", 30)
        auto_level = seasonal_cfg.get("auto_execute_level", 3)
        last_action_date = ""
        last_action_type = ""  # "open" oder "close"

        while self._running:
            try:
                now = datetime.now()
                today = now.strftime("%Y-%m-%d")
                current_minutes = now.hour * 60 + now.minute

                # Reset am neuen Tag
                if last_action_date != today:
                    last_action_type = ""
                    last_action_date = today

                # Cover-Timing von ContextBuilder holen
                states = await self.brain.ha.get_states()
                timing = self.brain.context_builder.get_cover_timing(states)
                open_time = timing.get("open_time", "07:30")
                close_time = timing.get("close_time", "19:00")
                season = timing.get("season", "")
                reason = timing.get("reason", "")

                # Zeiten parsen
                try:
                    ot_parts = open_time.split(":")
                    open_min = int(ot_parts[0]) * 60 + int(ot_parts[1])
                    ct_parts = close_time.split(":")
                    close_min = int(ct_parts[0]) * 60 + int(ct_parts[1])
                except (ValueError, IndexError):
                    open_min, close_min = 450, 1140  # 07:30, 19:00

                # Toleranz: ±15 Min um die optimale Zeit
                tolerance = 15

                # Morgens: Rolladen oeffnen
                if (last_action_type != "open"
                        and abs(current_minutes - open_min) <= tolerance):
                    await self._execute_seasonal_cover(
                        "open", 100, season, reason, auto_level,
                    )
                    last_action_type = "open"

                # Abends: Rolladen schliessen
                elif (last_action_type != "close"
                        and abs(current_minutes - close_min) <= tolerance):
                    await self._execute_seasonal_cover(
                        "close", 0, season, reason, auto_level,
                    )
                    last_action_type = "close"

                # Sommer-Hitzeschutz: Mitte des Tages pruefen
                elif (season == "summer" and last_action_type == "open"):
                    outside_temp = None
                    for s in (states or []):
                        if s.get("entity_id", "").startswith("weather."):
                            outside_temp = s.get("attributes", {}).get("temperature")
                            break
                    if outside_temp and outside_temp > 30 and 11 <= now.hour <= 15:
                        await self._execute_seasonal_cover(
                            "heat_protection", 20, season,
                            f"Hitzeschutz: {outside_temp}°C Aussentemperatur",
                            auto_level,
                        )
                        last_action_type = "close"

            except Exception as e:
                logger.error("Seasonal-Loop Fehler: %s", e)

            await asyncio.sleep(check_interval * 60)

    async def _execute_seasonal_cover(
        self, action: str, position: int, season: str, reason: str, auto_level: int,
    ):
        """Fuehrt saisonale Rolladen-Aktion aus oder schlaegt sie vor."""
        level = self.brain.autonomy.level

        if level >= auto_level:
            # Automatisch ausfuehren
            try:
                states = await self.brain.ha.get_states()
                count = 0
                for s in (states or []):
                    eid = s.get("entity_id", "")
                    if eid.startswith("cover."):
                        await self.brain.ha.call_service(
                            "cover", "set_cover_position",
                            {"entity_id": eid, "position": position},
                        )
                        count += 1

                if count > 0:
                    desc = "geoeffnet" if position > 50 else "geschlossen"
                    await self._notify("seasonal_cover", LOW, {
                        "action": action,
                        "message": f"Rolladen {desc} ({reason})",
                        "count": count,
                    })
                    logger.info(
                        "Seasonal: %d Rolladen auf %d%% (%s: %s)",
                        count, position, season, reason,
                    )
            except Exception as e:
                logger.error("Seasonal Cover-Aktion Fehler: %s", e)
        else:
            # Nur vorschlagen
            desc = "oeffnen" if position > 50 else "schliessen"
            await self._notify("seasonal_cover", LOW, {
                "action": action,
                "message": f"Rolladen {desc}? ({reason})",
                "suggestion": True,
            })

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
        await asyncio.sleep(180)  # 3 Min. warten bis System stabil

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

            # Energy Events pruefen
            try:
                if hasattr(self.brain, "energy_optimizer") and self.brain.energy_optimizer.enabled:
                    energy_alerts = await self.brain.energy_optimizer.check_energy_events()
                    for alert in energy_alerts:
                        urgency = LOW  # Energie-Alerts sind immer LOW
                        await self._notify(alert.get("type", "energy_event"), urgency, {
                            "message": alert.get("message", ""),
                        })
            except Exception as e:
                logger.debug("Energy Check Fehler: %s", e)

            # Alle 5 Minuten pruefen
            await asyncio.sleep(300)

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

        # 10 Min nach Start warten
        await asyncio.sleep(600)

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

                if states and report_energy:
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
                    msg = "Alles ruhig, Sir."
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
