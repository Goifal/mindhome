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
        logger.info("Proactive Manager gestartet (Feedback + Diagnostik + Batching)")

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
        logger.info("Proactive Manager gestoppt")

    async def _listen_ha_events(self):
        """Hoert auf Home Assistant Events via WebSocket."""
        ha_url = settings.ha_url.replace("http://", "ws://").replace("https://", "wss://")
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

        # Rauchmelder
        elif entity_id.startswith("binary_sensor.smoke") and new_val == "on":
            await self._notify("smoke_detected", CRITICAL, {
                "entity": entity_id,
            })

        # Wassersensor
        elif entity_id.startswith("binary_sensor.water") and new_val == "on":
            await self._notify("water_leak", CRITICAL, {
                "entity": entity_id,
            })

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

        # Phase 10.1: Musik-Follow bei Raumwechsel
        elif entity_id.startswith("binary_sensor.") and "motion" in entity_id and new_val == "on":
            await self._check_music_follow(entity_id)

        # Waschmaschine/Trockner (Power-Sensor faellt unter Schwellwert)
        elif "washer" in entity_id or "waschmaschine" in entity_id:
            if entity_id.startswith("sensor.") and new_val.replace(".", "").isdigit():
                if float(old_val or "0") > 10 and float(new_val) < 5:
                    await self._notify("washer_done", MEDIUM, {})

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

            await self._notify("music_follow", LOW, {
                "from_room": playing_room,
                "to_room": new_room,
                "player_entity": playing_entity,
            })

        except Exception as e:
            logger.debug("Music-Follow Check fehlgeschlagen: %s", e)

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
            return response.get("message", {}).get("content", "Alles in Ordnung.")
        except Exception as e:
            logger.error("Fehler beim Status-Bericht: %s", e)
            return "Status nicht verfuegbar."

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
