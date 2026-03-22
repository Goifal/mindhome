"""
Proactive Manager - Der MindHome Assistant spricht von sich aus.
Hoert auf Events von Home Assistant / MindHome und entscheidet ob
eine proaktive Meldung sinnvoll ist.

Phase 5: Vollstaendig mit FeedbackTracker integriert.
- Adaptive Cooldowns basierend auf Feedback-Score
- Auto-Timeout für unbeantwortete Meldungen
- Intelligente Filterung pro Event-Typ und Urgency

Phase 10: Diagnostik + Wartungs-Erinnerungen.
- Periodische Entity-Checks (offline, low battery, stale)
- Wartungskalender-Erinnerungen (sanft, LOW Priority)
"""

import asyncio
import collections
import json
import logging
import random
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import aiohttp
import yaml

from .config import (
    settings,
    yaml_config,
    get_person_title,
    set_active_person,
    resolve_person_by_entity,
    get_room_profiles,
)
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

_LOCAL_TZ = ZoneInfo(yaml_config.get("timezone", "Europe/Berlin"))

logger = logging.getLogger(__name__)

# Room-Profiles: zentraler Cache aus config.py
_get_room_profiles_cached = get_room_profiles


# Event-Prioritäten
CRITICAL = "critical"  # Immer melden (Alarm, Rauch, Wasser)
HIGH = "high"  # Melden wenn wach
MEDIUM = "medium"  # Melden wenn passend
LOW = "low"  # Melden wenn entspannt

# Domains fuer State-Change-Logging (Modul-Level statt pro Aufruf)
_LOG_DOMAINS = (
    "light.",
    "switch.",
    "climate.",
    "cover.",
    "media_player.",
    "binary_sensor.fenster",
    "binary_sensor.window",
    "binary_sensor.door",
    "binary_sensor.tuer",
    "alarm_control_panel.",
)


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
        self._personality_filter = proactive_cfg.get("personality_filter", True)

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
        self._batch_flushing = False  # Guard gegen konkurrierende Flushes
        self._batch_flush_lock = (
            asyncio.Lock()
        )  # Lock für concurrent _batch_flushing access

        # F-033: Lock für shared state (batch_queue, mb_triggered etc.)
        self._state_lock = asyncio.Lock()

        # Appliance completion detection: Power thresholds + idle confirmation
        appliance_cfg = yaml_config.get("appliance_monitor", {})
        self._appliance_power_high = float(
            appliance_cfg.get("power_running_threshold", 10)
        )
        self._appliance_power_low = float(appliance_cfg.get("power_idle_threshold", 5))
        self._appliance_confirm_minutes = int(
            appliance_cfg.get("idle_confirm_minutes", 5)
        )

        # Dynamische Geraete: devices ist eine Liste von {key, label, patterns}
        self._appliance_patterns = {}
        self.event_handlers = {}  # Fix: Vor devices-Loop initialisieren (war erst bei Z.145)
        devices = appliance_cfg.get("devices", [])
        if devices:
            for dev in devices:
                key = dev.get("key", "").strip()
                patterns = dev.get("patterns", [])
                if key and patterns:
                    self._appliance_patterns[key] = patterns
                    # Event-Handler dynamisch registrieren
                    event_type = f"{key}_done"
                    label = dev.get("label", key.replace("_", " ").title())
                    if event_type not in self.event_handlers:
                        self.event_handlers[event_type] = (MEDIUM, f"{label} fertig")
        else:
            # Fallback: Legacy-Format (washer_patterns, dryer_patterns, ...)
            self._appliance_patterns = {
                "washer": appliance_cfg.get(
                    "washer_patterns", ["washer", "waschmaschine"]
                ),
                "dryer": appliance_cfg.get("dryer_patterns", ["dryer", "trockner"]),
                "dishwasher": appliance_cfg.get(
                    "dishwasher_patterns",
                    ["dishwasher", "geschirrspueler", "spuelmaschine"],
                ),
                # F-091: Neue Geraete
                "oven": ["oven", "ofen", "backofen", "herd"],
                "coffee_machine": ["coffee", "kaffee", "kaffeemaschine", "espresso"],
                "ev_charger": ["ev_charger", "wallbox", "ladestation", "charger"],
                "heat_pump": ["heat_pump", "waermepumpe", "warmepumpe"],
                "3d_printer": ["3d_printer", "3d_drucker", "printer_3d"],
                "robot_vacuum": ["robot_vacuum", "saugroboter", "roborock", "roomba"],
            }
        self._appliance_confirm_task: Optional[asyncio.Task] = None

        # Power-Curve Profile: Per-Appliance Thresholds fuer genauere Erkennung
        # Jedes Profil definiert spezifische Leistungsschwellen (Watt)
        self._appliance_power_profiles = appliance_cfg.get(
            "power_profiles",
            {
                "washer": {
                    "running": 50,
                    "idle": 5,
                    "standby": 3,
                    "peak": 2000,
                    "confirm_minutes": 5,
                    "hysteresis": 5,
                },
                "dryer": {
                    "running": 100,
                    "idle": 10,
                    "standby": 5,
                    "peak": 3000,
                    "confirm_minutes": 8,
                    "hysteresis": 10,
                },
                "dishwasher": {
                    "running": 30,
                    "idle": 3,
                    "standby": 2,
                    "peak": 2200,
                    "confirm_minutes": 5,
                    "hysteresis": 3,
                },
                # F-091: Neue Geraete-Profile
                "oven": {
                    "running": 800,
                    "idle": 20,
                    "standby": 5,
                    "peak": 3500,
                    "confirm_minutes": 10,
                    "hysteresis": 20,
                },
                "coffee_machine": {
                    "running": 200,
                    "idle": 5,
                    "standby": 2,
                    "peak": 1200,
                    "confirm_minutes": 3,
                    "hysteresis": 10,
                },
                "ev_charger": {
                    "running": 1000,
                    "idle": 50,
                    "standby": 10,
                    "peak": 11000,
                    "confirm_minutes": 15,
                    "hysteresis": 50,
                },
                "heat_pump": {
                    "running": 500,
                    "idle": 30,
                    "standby": 10,
                    "peak": 5000,
                    "confirm_minutes": 20,
                    "hysteresis": 30,
                },
                "3d_printer": {
                    "running": 50,
                    "idle": 8,
                    "standby": 5,
                    "peak": 400,
                    "confirm_minutes": 5,
                    "hysteresis": 5,
                },
                "robot_vacuum": {
                    "running": 20,
                    "idle": 3,
                    "standby": 2,
                    "peak": 50,
                    "confirm_minutes": 3,
                    "hysteresis": 3,
                },
            },
        )

        # Phase 7.1: Morning Briefing Auto-Trigger
        mb_cfg = yaml_config.get("routines", {}).get("morning_briefing", {})
        self._mb_enabled = mb_cfg.get("enabled", True)
        self._mb_window_start = int(mb_cfg.get("window_start_hour", 6))
        self._mb_window_end = int(mb_cfg.get("window_end_hour", 10))
        self._mb_adaptive = mb_cfg.get("adaptive_time", True)  # D1: Lerne Aufwach-Zeit
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

        # Event-Mapping: HA Event -> Priorität + Beschreibung (Hardcoded Defaults)
        _PRIORITY_MAP = {
            "critical": CRITICAL,
            "high": HIGH,
            "medium": MEDIUM,
            "low": LOW,
        }
        _dynamic_handlers = (
            self.event_handlers
        )  # Preserve dynamische Appliance-Handler (Z.98-110)
        self.event_handlers = {
            "alarm_triggered": (CRITICAL, "Alarm ausgeloest"),
            "smoke_detected": (CRITICAL, "Rauch erkannt"),
            "water_leak": (CRITICAL, "Wasseraustritt erkannt"),
            "motion_detected_night": (HIGH, "Naechtliche Bewegung"),
            "person_arrived": (MEDIUM, "Person angekommen"),
            "person_left": (MEDIUM, "Person gegangen"),
            "washer_done": (MEDIUM, "Waschmaschine fertig"),
            "dryer_done": (MEDIUM, "Trockner fertig"),
            "dishwasher_done": (MEDIUM, "Geschirrspueler fertig"),
            "doorbell": (MEDIUM, "Jemand hat geklingelt"),
            "night_motion_camera": (MEDIUM, "Naechtliche Bewegung erkannt"),
            "weather_warning": (LOW, "Wetterwarnung"),
            "window_open_rain": (LOW, "Fenster offen bei Regen"),
            "entity_offline": (MEDIUM, "Entity offline"),
            "low_battery": (MEDIUM, "Batterie niedrig"),
            "stale_sensor": (LOW, "Sensor reagiert nicht"),
            "maintenance_due": (LOW, "Wartungsaufgabe faellig"),
            "music_follow": (LOW, "Musik folgen"),
            "person_approaching": (LOW, "Person naehert sich"),
            "person_arriving": (MEDIUM, "Person gleich zuhause"),
            "seasonal_cover": (LOW, "Rolladen saisonal angepasst"),
            "conditional_executed": (MEDIUM, "Bedingte Aktion ausgeführt"),
            "learning_suggestion": (LOW, "Automatisierungs-Vorschlag"),
            "threat_detected": (HIGH, "Sicherheitswarnung"),
            "energy_price_high": (LOW, "Teurer Strom"),
            "solar_surplus": (LOW, "Solar-Überschuss"),
            "scene_device_triggered": (LOW, "Szene durch Geraet aktiviert"),
            "shopping_reminder": (LOW, "Einkaufs-Erinnerung"),
            "window_open_cover_blocked": (LOW, "Fenster offen — Cover blockiert"),
            "cover_anomaly": (MEDIUM, "Cover-Anomalie erkannt"),
            "entity_recovered": (LOW, "Entity wieder online"),
            "scene_scheduled": (LOW, "Geplante Szene aktiviert"),
            "scene_suggested": (LOW, "Szenen-Vorschlag"),
            "observation": (LOW, "Spontane Beobachtung"),
            "ambient_status": (LOW, "Ambient-Status"),
        }
        # Dynamische Appliance-Handler (aus YAML devices) einfuegen — ueberschreiben Defaults
        self.event_handlers.update(_dynamic_handlers)
        # YAML-Overrides anwenden (Event-Handler konfigurierbar)
        yaml_handlers = proactive_cfg.get("event_handlers", {})
        for event_name, info in yaml_handlers.items():
            if isinstance(info, dict):
                prio = _PRIORITY_MAP.get(info.get("priority", "low"), LOW)
                desc = info.get("description", event_name)
                self.event_handlers[event_name] = (prio, desc)

        # Salience Scoring: Notification-Historie fuer Fatigue-Berechnung
        # Speichert Zeitstempel der letzten Benachrichtigungen (maxlen begrenzt Speicher)
        self._notification_timestamps: collections.deque[float] = collections.deque(
            maxlen=200
        )
        # Ignorierte Events pro Typ: zaehlt wie oft User aehnliche Events ignoriert hat
        # Begrenzt auf max 200 Event-Typen (aelteste werden bei Ueberlauf geloescht)
        self._dismissed_event_types: collections.Counter = collections.Counter()
        self._dismissed_max_types = 200
        self._salience_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Attention / Salience Scoring
    # ------------------------------------------------------------------

    # Schweregrad-Gewichtung pro Prioritaet
    _SEVERITY_SCORES = {
        CRITICAL: 1.0,
        HIGH: 0.8,
        MEDIUM: 0.5,
        LOW: 0.25,
    }

    # Aktivitaets-Schwellwerte: hoeher = schwieriger zu unterbrechen
    _ACTIVITY_THRESHOLDS = {
        "sleeping": 0.9,  # Schlaf: nur bei sehr hoher Salienz unterbrechen
        "in_call": 0.85,  # Telefonat/Videocall: fast nie unterbrechen
        "watching": 0.7,  # Film/TV: erhoehter Schwellwert
        "focused": 0.65,  # Konzentriertes Arbeiten
        "guests": 0.6,  # Gaeste da: zurueckhaltend
        "relaxing": 0.4,  # Entspannung: moderate Schwelle
        "idle": 0.2,  # Nichts los: fast alles durchlassen
        "away": 0.5,  # Abwesend: mittel (manche Events relevant)
        "unknown": 0.3,  # Unbekannt: eher durchlassen
    }

    def calculate_salience(self, event: dict, user_activity: str) -> float:
        """Berechnet wie unterbrechungswuerdig ein Event ist (0.0 - 1.0).

        Faktoren:
        - Event-Schweregrad (critical > high > medium > low)
        - Benutzer-Aktivitaet (sleeping = hohe Schwelle, idle = niedrige)
        - Tageszeit (nachts hoehere Schwelle fuer unwichtige Events)
        - Notification Fatigue (viele Meldungen → reduzierte Salienz)
        - Ignorier-Historie (oft ignorierte Event-Typen → reduzierte Salienz)

        Args:
            event: Event-Dict mit mindestens "event_type" und optional "urgency"
            user_activity: Aktuelle Aktivitaet des Users (sleeping, watching, idle, ...)

        Returns:
            Score 0.0-1.0 — der Aufrufer entscheidet ueber den Schwellwert
        """
        event_type = event.get("event_type", "")
        urgency = event.get("urgency", MEDIUM)

        # 1. Basis-Score aus Schweregrad
        base_score = self._SEVERITY_SCORES.get(urgency, 0.3)

        # 2. Tageszeit-Modifikator: nachts (22-7) sind LOW/MEDIUM weniger salient
        hour = datetime.now(_LOCAL_TZ).hour
        time_modifier = 1.0
        if self._quiet_start > self._quiet_end:
            is_night = hour >= self._quiet_start or hour < self._quiet_end
        else:
            is_night = self._quiet_start <= hour < self._quiet_end
        if is_night and urgency in (LOW, MEDIUM):
            time_modifier = 0.5  # Nachtabsenkung fuer unwichtige Events

        # 3. Notification Fatigue: je mehr Meldungen kuerzlich, desto weniger salient
        fatigue = self._notification_fatigue_score()

        # 4. Ignorier-Abzug: Wenn der User diesen Event-Typ oft ignoriert hat
        with self._salience_lock:
            dismiss_count = self._dismissed_event_types.get(event_type, 0)
        # Jedes Ignorieren reduziert Salienz um 5%, max 40% Reduktion
        dismiss_penalty = max(0.6, 1.0 - dismiss_count * 0.05)

        # 5. Aktivitaets-Relevanz: inverse Schwelle = wie leicht durchzukommen
        # Hohe Schwelle = schwer durchzukommen = Salienz wird relativ betrachtet
        activity_threshold = self._ACTIVITY_THRESHOLDS.get(user_activity, 0.3)
        # Je hoeher die Schwelle, desto mehr wird der Score gedaempft
        # (aber CRITICAL bleibt immer hoch)
        if urgency == CRITICAL:
            activity_modifier = 1.0  # CRITICAL ignoriert Aktivitaet
        else:
            # Invertierte Daempfung: hohe Schwelle = staerkere Reduktion
            activity_modifier = max(0.3, 1.0 - activity_threshold * 0.5)

        # Endgueltiger Score: alle Faktoren kombinieren
        score = (
            base_score * time_modifier * fatigue * dismiss_penalty * activity_modifier
        )

        # Auf 0.0-1.0 begrenzen
        return max(0.0, min(1.0, round(score, 3)))

    def _notification_fatigue_score(self) -> float:
        """Berechnet Ermuedungs-Multiplikator basierend auf kuerzlichen Benachrichtigungen.

        Zaehlt wie viele Notifications in der letzten Stunde gesendet wurden
        und gibt einen Multiplikator zurueck:
        - 1.0 = keine Ermuedung (0-2 Notifications/Stunde)
        - 0.7 = leichte Ermuedung (3-5 Notifications)
        - 0.5 = moderate Ermuedung (6-10 Notifications)
        - 0.3 = starke Ermuedung (>10 Notifications) — Unterbrechungen reduzieren

        Returns:
            Multiplikator 0.3-1.0 fuer Salienz-Berechnung
        """
        now = time.time()
        one_hour_ago = now - 3600

        # Zaehle Notifications der letzten Stunde
        with self._salience_lock:
            recent_count = sum(
                1 for ts in self._notification_timestamps if ts > one_hour_ago
            )

        if recent_count <= 2:
            return 1.0  # Keine Ermuedung
        elif recent_count <= 5:
            return 0.7  # Leichte Ermuedung
        elif recent_count <= 10:
            return 0.5  # Moderate Ermuedung
        else:
            return 0.3  # Starke Ermuedung — nur Wichtiges durchlassen

    def record_notification_sent(self, event_type: str = ""):
        """Registriert eine gesendete Notification fuer Fatigue-Tracking.

        Wird vom Notification-System aufgerufen wenn eine Meldung tatsaechlich
        zugestellt wurde.

        Args:
            event_type: Event-Typ (fuer zukuenftige Event-spezifische Fatigue)
        """
        with self._salience_lock:
            self._notification_timestamps.append(time.time())

    def record_notification_dismissed(self, event_type: str):
        """Registriert dass der User eine Notification ignoriert/dismissed hat.

        Erhoehte Dismiss-Zaehler fuehren zu reduzierter Salienz fuer diesen Event-Typ.

        Args:
            event_type: Der Event-Typ der ignoriert wurde
        """
        with self._salience_lock:
            self._dismissed_event_types[event_type] += 1
            # Memory-Leak Schutz: Alte Low-Count Eintraege entfernen
            if len(self._dismissed_event_types) > self._dismissed_max_types:
                # Behalte nur die haeufigsten Events
                self._dismissed_event_types = collections.Counter(
                    dict(
                        self._dismissed_event_types.most_common(
                            self._dismissed_max_types // 2
                        )
                    )
                )

    # ------------------------------------------------------------------
    # LED Status-Indikator: Systemzustand als Lichtfarbe
    # ------------------------------------------------------------------

    # Mapping: Status -> (RGB, Brightness in %)
    _STATUS_LED_MAP = {
        "healthy": {"rgb": (0, 255, 0), "brightness_pct": 30},
        "warning": {"rgb": (255, 165, 0), "brightness_pct": 50},
        "alert": {"rgb": (255, 0, 0), "brightness_pct": 100},
        "listening": {"rgb": (0, 100, 255), "brightness_pct": 60},
        "thinking": {
            "rgb": (128, 0, 255),
            "brightness_pct": 40,
            "effect": "slow_pulse",
        },
        "degraded": {"rgb": (255, 255, 0), "brightness_pct": 40},
    }

    async def update_status_light(self, ha_client, status: str):
        """Setzt die Status-LED auf die Farbe fuer den aktuellen Systemzustand.

        Liest die Entity-ID der Status-LED aus der Konfiguration:
        settings.yaml → status_led_entity (z.B. "light.status_led").
        Wenn keine Entity konfiguriert ist, wird nichts gemacht (graceful skip).

        Args:
            ha_client: HomeAssistant-Client mit call_service()
            status: Einer von "healthy", "warning", "alert", "listening",
                    "thinking", "degraded"
        """
        entity_id = settings.get("status_led_entity", None)
        if not entity_id:
            return

        led_config = self._STATUS_LED_MAP.get(status)
        if not led_config:
            logger.warning("Unbekannter Status-LED-Zustand: %s", status)
            return

        rgb = led_config["rgb"]
        brightness_pct = led_config["brightness_pct"]

        service_data = {
            "entity_id": entity_id,
            "rgb_color": list(rgb),
            "brightness_pct": brightness_pct,
        }

        # "thinking" unterstuetzt einen Puls-Effekt (wenn die LED das kann)
        if led_config.get("effect"):
            service_data["effect"] = led_config["effect"]

        try:
            await ha_client.call_service("light", "turn_on", service_data)
            logger.debug("Status-LED '%s' auf %s gesetzt", entity_id, status)
        except Exception as e:
            logger.debug("Status-LED Update fehlgeschlagen: %s", e)

    @staticmethod
    def _check_quiet(start: int, end: int) -> bool:
        """Prueft ob die aktuelle Stunde in einem Quiet-Window liegt."""
        hour = datetime.now(_LOCAL_TZ).hour
        if start > end:
            return hour >= start or hour < end
        return start <= hour < end

    def _is_quiet_hours(self, person: str = "") -> bool:
        """Prüft ob gerade Quiet Hours aktiv sind (z.B. 22:00-07:00).

        Wenn person angegeben: Per-Person Quiet Hours bevorzugen.
        """
        if person:
            from .config import get_member_config

            member_cfg = get_member_config(person)
            if member_cfg and "quiet_hours" in member_cfg:
                qh = member_cfg["quiet_hours"]
                return self._check_quiet(
                    qh.get("start", self._quiet_start), qh.get("end", self._quiet_end)
                )
        return self._check_quiet(self._quiet_start, self._quiet_end)

    # ------------------------------------------------------------------
    # Unified Delivery: WebSocket + TTS in einer Pipeline
    # ------------------------------------------------------------------

    async def _deliver(
        self,
        text: str,
        event_type: str,
        urgency: str,
        notification_id: str = "",
        delivery_method: str = "",
        volume: float = 0.8,
        room: str = "",
    ):
        """Einheitliche Zustellung: WebSocket-Notification + TTS.

        Schliesst die Lücke zwischen proaktiven Meldungen (bisher nur
        WebSocket) und Callback-Meldungen (bisher nur TTS).  Jetzt werden
        beide Kanaele bedient — die WebSocket-UI bekommt die Notification
        UND der Speaker spricht sie aus, sofern delivery_method es erlaubt.

        Args:
            text: Fertig formatierter Meldungstext
            event_type: Event-Typ (für Tracking)
            urgency: Dringlichkeit
            notification_id: ID für Feedback-Tracking
            delivery_method: tts_loud, tts_quiet, led_blink, suppress
            volume: Lautstärke 0.0-1.0 (aus ActivityEngine)
            room: Zielraum (auto-detect wenn leer)
        """
        # MCU Sprint 3: Flow-State deferral — suppress MEDIUM/LOW during focus
        if urgency in (LOW, MEDIUM) and hasattr(self.brain, "activity"):
            try:
                if self.brain.activity.is_in_flow_state(min_minutes=30):
                    _focus_min = self.brain.activity.get_focused_duration_minutes()
                    logger.info(
                        "Flow-State: %s unterdrückt (%s, focused seit %d min)",
                        event_type,
                        urgency,
                        _focus_min,
                    )
                    return
            except Exception:
                pass  # Graceful degradation

        # Personality filter: restyle raw message in Jarvis style
        # Graceful degradation: skip if personality or LLM not available
        if self._personality_filter and urgency != "critical":
            _personality = getattr(self.brain, "personality", None)
            _ollama = getattr(self.brain, "ollama", None)
            if _personality and _ollama:
                try:
                    text = await self.format_with_personality(text, urgency)
                except Exception as e:
                    logger.debug("Personality filter failed, using original: %s", e)
            else:
                logger.debug(
                    "Personality filter skipped: personality=%s, ollama=%s",
                    _personality is not None,
                    _ollama is not None,
                )

        # 1. WebSocket: Proaktive Meldung an alle Clients
        await emit_proactive(text, event_type, urgency, notification_id)
        # Feedback-Bridge: Letzten Event-Typ merken fuer Lob-Erkennung
        self.brain._last_proactive_event_type = event_type

        # 2. TTS: Nur wenn delivery_method Sprache erlaubt
        if delivery_method in ("tts_loud", "tts_quiet"):
            try:
                if not room:
                    room = await self.brain._get_occupied_room()
                tts_data = {"volume": volume}
                self.brain._task_registry.create_task(
                    self.brain.sound_manager.speak_response(
                        text,
                        room=room,
                        tts_data=tts_data,
                    ),
                    name="proactive_tts",
                )
            except Exception as e:
                logger.warning("Proaktive TTS fehlgeschlagen: %s", e)

    async def _send_critical_with_retry(
        self,
        text: str,
        event_type: str,
        protocol: str,
        max_retries: int = 3,
    ):
        """Sendet Critical Alert mit Retry und Lautstaerke-Escalation.

        Wiederholt den Alert bis zu max_retries Mal mit 30s Abstand,
        falls kein ACK empfangen wird. Volume steigt pro Versuch.
        """
        event_id = f"crit_{event_type}_{int(time.time())}"
        redis = getattr(self.brain.memory, "redis", None)
        if redis:
            try:
                await redis.setex(f"mha:critical:{event_id}", 300, "pending")
            except Exception as e:
                logger.debug("Critical Alert Redis-Write fehlgeschlagen: %s", e)

        for attempt in range(max_retries + 1):
            volume = min(1.0, 0.7 + attempt * 0.1)

            await emit_interrupt(text, event_type, protocol, [])

            try:
                room = await self.brain._get_occupied_room()
                self.brain._task_registry.create_task(
                    self.brain.sound_manager.speak_response(
                        text,
                        room=room,
                        tts_data={"volume": volume},
                    ),
                    name=f"critical_tts_{attempt}",
                )
            except Exception as e:
                logger.warning(
                    "Critical TTS (Versuch %d) fehlgeschlagen: %s", attempt, e
                )

            # MCU Sprint 3: Escalation — after 2nd retry, all rooms
            if attempt >= 2:
                try:
                    # Speak in ALL rooms (multi-room escalation)
                    if hasattr(self.brain, "multi_room_audio"):
                        room_speakers = yaml_config.get("multi_room_audio", {}).get(
                            "room_speakers", {}
                        )
                        for r_name, r_entity in room_speakers.items():
                            self.brain._task_registry.create_task(
                                self.brain.sound_manager.speak_response(
                                    text,
                                    room=r_name,
                                    tts_data={"volume": 1.0},
                                ),
                                name=f"critical_allrooms_{r_name}",
                            )
                        logger.info(
                            "Critical escalation: all rooms notified (attempt %d)",
                            attempt,
                        )
                except Exception as e:
                    logger.debug("Multi-room escalation fehlgeschlagen: %s", e)

            # MCU Sprint 3: After 3rd retry, flash lights in all rooms
            if attempt >= 3:
                try:
                    states = await self.brain.ha.get_states()
                    for s in states or []:
                        eid = s.get("entity_id", "")
                        if eid.startswith("light.") and s.get("state") == "on":
                            await self.brain.ha.call_service(
                                "light",
                                "turn_on",
                                {"entity_id": eid, "flash": "long"},
                            )
                    logger.info(
                        "Critical escalation: LED flash activated (attempt %d)", attempt
                    )
                except Exception as e:
                    logger.debug("LED flash escalation fehlgeschlagen: %s", e)

            if attempt < max_retries:
                await asyncio.sleep(30)
                # ACK pruefen
                if redis:
                    try:
                        ack = await redis.get(f"mha:critical:{event_id}")
                        if ack and ack == b"acked":
                            logger.info(
                                "Critical Alert %s acknowledged nach %d Versuchen",
                                event_id,
                                attempt + 1,
                            )
                            return
                    except Exception as e:
                        logger.debug("Critical Alert ACK-Check fehlgeschlagen: %s", e)

        logger.warning(
            "Critical Alert %s: Kein ACK nach %d Versuchen", event_id, max_retries + 1
        )

    async def _is_semantically_duplicate(
        self, message: str, window_minutes: int = 30
    ) -> bool:
        """Prueft ob eine semantisch aehnliche Notification kuerzlich gesendet wurde.

        Delegiert an den zentralen NotificationDedup-Service des Brains,
        damit Cross-Module Duplikate erkannt werden (Insight, Anticipation etc.).
        """
        try:
            dedup = getattr(self.brain, "notification_dedup", None)
            if dedup:
                return await dedup.is_duplicate(
                    message,
                    source="proactive",
                    window_minutes=window_minutes,
                )
        except Exception as e:
            logger.debug("Semantic Dedup Fehler: %s", e)
        return False

    @staticmethod
    def _loop_done_cb(t: asyncio.Task) -> None:
        """Callback fuer Long-Running Loop Tasks — loggt unerwartete Crashes."""
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            logger.error(
                "Proactive Loop-Task '%s' unerwartet beendet: %s", t.get_name(), exc
            )

    def _create_loop_task(self, coro, *, name: str = "") -> asyncio.Task:
        """Erstellt einen Loop-Task mit Error-Callback."""
        task = asyncio.create_task(coro, name=name or "")
        task.add_done_callback(self._loop_done_cb)
        return task

    async def start(self):
        """Startet den Event Listener."""
        if not self.enabled:
            logger.info("Proaktive Meldungen deaktiviert")
            return

        self._running = True
        self._task = self._create_loop_task(
            self._listen_ha_events(), name="proactive_ha_events"
        )
        # Phase 10: Periodische Diagnostik starten
        if hasattr(self.brain, "diagnostics") and self.brain.diagnostics.enabled:
            self._diag_task = self._create_loop_task(
                self._run_diagnostics_loop(), name="proactive_diagnostics"
            )
        # Phase 15.4: Batch-Loop starten
        if self.batch_enabled:
            self._batch_task = self._create_loop_task(
                self._run_batch_loop(), name="proactive_batch"
            )
        # Phase 7.9: Saisonaler Rolladen-Loop
        seasonal_cfg = yaml_config.get("seasonal_actions", {})
        if seasonal_cfg.get("enabled", True):
            self._seasonal_task = self._create_loop_task(
                self._run_seasonal_loop(), name="proactive_seasonal"
            )

        # Phase 18: Unaufgeforderte Beobachtungen
        obs_cfg = yaml_config.get("observation_loop", {})
        self._observation_task: Optional[asyncio.Task] = None
        if obs_cfg.get("enabled", True):
            self._observation_task = self._create_loop_task(
                self._run_observation_loop(), name="proactive_observation"
            )

        # Phase 11: Saugroboter-Automatik
        vacuum_cfg = yaml_config.get("vacuum", {})
        self._vacuum_task: Optional[asyncio.Task] = None
        self._vacuum_power_task: Optional[asyncio.Task] = None
        self._vacuum_scene_task: Optional[asyncio.Task] = None
        self._vacuum_presence_task: Optional[asyncio.Task] = None
        if vacuum_cfg.get("enabled") and vacuum_cfg.get("auto_clean", {}).get(
            "enabled"
        ):
            self._vacuum_task = self._create_loop_task(
                self._run_vacuum_automation(), name="proactive_vacuum"
            )
        # Steckdosen-Trigger für Saugroboter
        if vacuum_cfg.get("enabled") and vacuum_cfg.get("power_trigger", {}).get(
            "enabled"
        ):
            self._vacuum_power_task = self._create_loop_task(
                self._run_vacuum_power_trigger(), name="proactive_vacuum_power"
            )
        # Szenen-Trigger für Saugroboter
        if vacuum_cfg.get("enabled") and vacuum_cfg.get("scene_trigger", {}).get(
            "enabled"
        ):
            self._vacuum_scene_task = self._create_loop_task(
                self._run_vacuum_scene_trigger(), name="proactive_vacuum_scene"
            )
        # Anwesenheits-Monitor: Vacuum pausieren bei Heimkehr, fortsetzen bei Abwesenheit
        if vacuum_cfg.get("enabled") and vacuum_cfg.get("presence_guard", {}).get(
            "enabled"
        ):
            self._vacuum_presence_task = self._create_loop_task(
                self._run_vacuum_presence_monitor(), name="proactive_vacuum_presence"
            )
        # Emergency Protocols laden
        self._emergency_protocols = yaml_config.get("emergency_protocols", {})

        # Phase 17: Threat Assessment Loop
        self._threat_task: Optional[asyncio.Task] = None
        if (
            hasattr(self.brain, "threat_assessment")
            and self.brain.threat_assessment.enabled
        ):
            self._threat_task = self._create_loop_task(
                self._run_threat_assessment_loop(), name="proactive_threat"
            )

        # Ambient Presence Loop (Jarvis ist immer da)
        self._ambient_task: Optional[asyncio.Task] = None
        ambient_cfg = yaml_config.get("ambient_presence", {})
        if ambient_cfg.get("enabled", False):
            self._ambient_task = self._create_loop_task(
                self._run_ambient_presence_loop(), name="proactive_ambient"
            )

        # C3: Follow-up Loop — offene Themen proaktiv aufgreifen
        self._followup_task: Optional[asyncio.Task] = None
        followup_cfg = yaml_config.get("self_followup", {})
        if followup_cfg.get("enabled", True):
            self._followup_task = self._create_loop_task(
                self._run_followup_loop(), name="proactive_followup"
            )

        # E: Routine-Abweichungserkennung
        self._routine_task: Optional[asyncio.Task] = None
        routine_cfg = yaml_config.get("routine_deviation", {})
        if routine_cfg.get("enabled", True):
            self._routine_task = self._create_loop_task(
                self._run_routine_deviation_loop(), name="proactive_routine"
            )

        # Szenen-Scheduler: Cron-basierte Szenen-Aktivierung
        self._scene_schedule_task: Optional[asyncio.Task] = None
        scenes_cfg = yaml_config.get("scenes", {})
        if scenes_cfg.get("schedule_enabled", True):
            self._scene_schedule_task = self._create_loop_task(
                self._run_scene_schedule_loop(), name="proactive_scene_schedule"
            )

        # MCU Sprint 3: Kalender-Trigger Loop
        self._calendar_task: Optional[asyncio.Task] = None
        cal_trigger_cfg = yaml_config.get("calendar_triggers", {})
        if cal_trigger_cfg.get("enabled", True):
            self._calendar_task = self._create_loop_task(
                self._run_calendar_trigger_loop(), name="proactive_calendar"
            )

        logger.info(
            "Proactive Manager gestartet (Feedback + Diagnostik + Batching + Saisonal + Notfall + Threat + Ambient + Follow-up + Routine + Szenen-Schedule + Kalender)"
        )

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
        # Phase 18: Observation-Task sauber beenden
        if hasattr(self, "_observation_task") and self._observation_task:
            self._observation_task.cancel()
            try:
                await self._observation_task
            except asyncio.CancelledError:
                pass
        # C3: Follow-up Task beenden
        if hasattr(self, "_followup_task") and self._followup_task:
            self._followup_task.cancel()
            try:
                await self._followup_task
            except asyncio.CancelledError:
                pass
        # Phase 11: Vacuum-Tasks sauber beenden
        for _vt_attr in (
            "_vacuum_task",
            "_vacuum_power_task",
            "_vacuum_scene_task",
            "_vacuum_presence_task",
        ):
            _vt = getattr(self, _vt_attr, None)
            if _vt:
                _vt.cancel()
                try:
                    await _vt
                except asyncio.CancelledError:
                    pass
        logger.info("Proactive Manager gestoppt")

    async def _listen_ha_events(self):
        """Hoert auf Home Assistant Events via WebSocket."""
        ha_url = (
            settings.ha_url.rstrip("/")
            .replace("http://", "ws://")
            .replace("https://", "wss://")
        )
        ws_url = f"{ha_url}/api/websocket"

        _reconnect_attempt = 0
        _max_backoff = 300  # Max 5 Minuten
        while self._running:
            try:
                await self._connect_and_listen(ws_url)
                _reconnect_attempt = 0  # Reset nach erfolgreicher Verbindung
            except Exception as e:
                _reconnect_attempt += 1
                backoff = min(
                    PROACTIVE_WS_RECONNECT_DELAY * (2 ** (_reconnect_attempt - 1)),
                    _max_backoff,
                )
                logger.error(
                    "HA WebSocket Fehler (Versuch %d, naechster in %ds): %s",
                    _reconnect_attempt,
                    backoff,
                    e,
                )
                if self._running:
                    await asyncio.sleep(backoff)

    async def _connect_and_listen(self, ws_url: str):
        """Verbindet sich mit HA WebSocket und verarbeitet Events."""
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(ws_url) as ws:
                # Auth
                auth_msg = await asyncio.wait_for(ws.receive_json(), timeout=30)
                if auth_msg.get("type") == "auth_required":
                    await asyncio.wait_for(
                        ws.send_json(
                            {
                                "type": "auth",
                                "access_token": settings.ha_token,
                            }
                        ),
                        timeout=30,
                    )  # T6: WS send timeout
                auth_result = await asyncio.wait_for(ws.receive_json(), timeout=30)
                if auth_result.get("type") != "auth_ok":
                    logger.error("HA WebSocket Auth fehlgeschlagen")
                    return

                logger.info("HA WebSocket verbunden")

                # Events abonnieren
                await asyncio.wait_for(
                    ws.send_json(
                        {
                            "id": 1,
                            "type": "subscribe_events",
                            "event_type": "state_changed",
                        }
                    ),
                    timeout=30,
                )  # T6

                # MindHome Events abonnieren
                await asyncio.wait_for(
                    ws.send_json(
                        {
                            "id": 2,
                            "type": "subscribe_events",
                            "event_type": "mindhome_event",
                        }
                    ),
                    timeout=30,
                )  # T6

                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            data = json.loads(msg.data)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        if data.get("type") == "event":
                            await self._handle_event(data.get("event", {}))
                    elif msg.type in (
                        aiohttp.WSMsgType.ERROR,
                        aiohttp.WSMsgType.CLOSED,
                    ):
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
            logger.error(
                "Event-Handler Fehler für %s: %s", event.get("event_type", "?"), e
            )

    async def _handle_state_change(self, data: dict):
        """Verarbeitet HA State-Change Events."""
        entity_id = data.get("entity_id", "")
        new_state = data.get("new_state", {})
        old_state = data.get("old_state", {})

        if not new_state:
            return
        if not old_state:
            # Power-Sensoren: Beim ersten Update nach Systemstart old_state=None
            # → auf "0" defaulten damit Power-Close getriggert werden kann
            if entity_id.startswith("sensor."):
                old_state = {"state": "0"}
            else:
                return

        new_val = new_state.get("state", "")
        old_val = old_state.get("state", "")

        if new_val == old_val:
            return

        # Entity-Recovery: unavailable → online erkennen
        if old_val == "unavailable" and new_val != "unavailable":
            try:
                await self._on_entity_recovered(entity_id, new_val, new_state)
            except Exception as _rec_err:
                logger.warning("Entity-Recovery Fehler: %s", _rec_err)

        # State-Change-Log: Relevante Aenderungen mit Quelle protokollieren
        if any(entity_id.startswith(d) for d in _LOG_DOMAINS):
            try:
                if hasattr(self.brain, "state_change_log"):
                    friendly = new_state.get("attributes", {}).get(
                        "friendly_name", entity_id
                    )
                    await self.brain.state_change_log.log_change(
                        entity_id,
                        old_val,
                        new_val,
                        new_state,
                        friendly_name=friendly,
                    )
            except Exception as _scl_err:
                logger.warning("State-Change-Log Fehler: %s", _scl_err)

        # Event-basierte Wetter-Sensoren: Sofort-Reaktion auf kritische Änderungen
        try:
            await self._handle_weather_event(entity_id, new_val, old_val)
        except Exception as _we:
            logger.warning("Weather-Event-Handler Fehler: %s", _we)

        # Alarmsystem
        if entity_id.startswith("alarm_control_panel.") and new_val == "triggered":
            await self._notify(
                "alarm_triggered",
                CRITICAL,
                {
                    "entity": entity_id,
                    "state": new_val,
                },
            )
            await self._execute_emergency_protocol("intrusion")

        # Rauchmelder
        elif entity_id.startswith("binary_sensor.smoke") and new_val == "on":
            await self._notify(
                "smoke_detected",
                CRITICAL,
                {
                    "entity": entity_id,
                },
            )
            await self._execute_emergency_protocol("fire")

        # Wassersensor
        elif entity_id.startswith("binary_sensor.water") and new_val == "on":
            await self._notify(
                "water_leak",
                CRITICAL,
                {
                    "entity": entity_id,
                },
            )
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
            if (
                hasattr(self.brain, "visitor_manager")
                and self.brain.visitor_manager.enabled
            ):
                try:
                    visitor_info = await self.brain.visitor_manager.handle_doorbell(
                        camera_description=camera_desc or "",
                    )
                except Exception as e:
                    logger.debug(
                        "VisitorManager Doorbell-Handling fehlgeschlagen: %s", e
                    )

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
            try:
                await self.brain.ha.log_activity(
                    "proactive",
                    "doorbell",
                    "Tuerklingel betaetigt"
                    + (f" — {camera_desc[:100]}" if camera_desc else ""),
                    arguments={"entity_id": entity_id},
                )
            except Exception as e:
                logger.debug("Aktivitaetslog Tuerklingel fehlgeschlagen: %s", e)

        # Person tracker (Phase 7: erweitert mit Abschied + Abwesenheits-Summary)
        elif entity_id.startswith("person."):
            # Config-Name (via ha_entity Mapping) bevorzugen, Fallback: friendly_name
            name = resolve_person_by_entity(entity_id)
            if not name:
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

                # MCU-JARVIS: Rückkehr-Briefing aus gesammelten Events
                _rb_cfg = yaml_config.get("return_briefing", {})
                if _rb_cfg.get("enabled", True):
                    return_briefing = await self._build_return_briefing(name)
                    if return_briefing:
                        status["return_briefing"] = return_briefing

                await self._notify(
                    "person_arrived",
                    MEDIUM,
                    {
                        "person": name,
                        "status_report": status,
                    },
                )
                try:
                    await self.brain.ha.log_activity(
                        "presence",
                        "person_arrived",
                        f"{name} ist angekommen",
                        arguments={"person": name},
                    )
                except Exception as e:
                    logger.debug("Aktivitaetslog Ankunft fehlgeschlagen: %s", e)

                # MCU Sprint 3: Orchestrierte Ankunfts-Begrüßung nach >4h Abwesenheit
                _arrival_cfg = yaml_config.get("arrival_greeting", {})
                if _arrival_cfg.get("enabled", True) and hasattr(
                    self.brain, "anticipation"
                ):
                    try:
                        _away_hours = status.get("away_hours", 0)
                        if _away_hours >= 4:
                            _suggestions = (
                                await self.brain.anticipation.get_suggestions(
                                    person=name
                                )
                            )
                            _auto_actions = [
                                s for s in _suggestions if s.get("confidence", 0) >= 0.7
                            ][:3]

                            _executed = []
                            for s in _auto_actions:
                                try:
                                    if hasattr(self.brain, "executor"):
                                        await self.brain.executor.execute(
                                            s["action"], s.get("args", {})
                                        )
                                        _executed.append(
                                            s.get("description", s["action"])
                                        )
                                except Exception as _ex_err:
                                    logger.debug("Arrival action failed: %s", _ex_err)

                            if _executed:
                                _title = get_person_title(name)
                                _actions_text = ", ".join(_executed[:-1])
                                if len(_executed) > 1:
                                    _actions_text += f" und {_executed[-1]}"
                                else:
                                    _actions_text = _executed[0]

                                _absence = status.get("absence_summary", "")
                                _absence_part = (
                                    f" Während du weg warst: {_absence}"
                                    if _absence
                                    else ""
                                )

                                _greeting = (
                                    f"Willkommen zurück, {_title}. "
                                    f"Ich habe mir erlaubt: {_actions_text}.{_absence_part}"
                                )
                                await self._deliver(
                                    _greeting,
                                    event_type="arrival_greeting",
                                    urgency=MEDIUM,
                                    volume=0.7,
                                )
                                logger.info(
                                    "Arrival greeting: %d actions for %s",
                                    len(_executed),
                                    name,
                                )
                    except Exception as _ag_err:
                        logger.debug("Arrival greeting fehlgeschlagen: %s", _ag_err)

                # Phase 18: Proactive Planner — Multi-Step-Plan bei Ankunft
                if (
                    hasattr(self.brain, "proactive_planner")
                    and self.brain.proactive_planner.enabled
                ):
                    try:
                        _plan_ctx = {
                            "person": {"name": name},
                            "house": status,
                        }
                        _autonomy = getattr(self.brain, "autonomy", None)
                        _auto_lvl = _autonomy.level if _autonomy is not None else 2
                        _plan = (
                            await self.brain.proactive_planner.plan_from_context_change(
                                "person_arrived",
                                _plan_ctx,
                                _auto_lvl,
                            )
                        )
                        if _plan:
                            if _plan.get("needs_confirmation"):
                                _plan_msg = _plan.get("message", "")
                            else:
                                _plan_msg = _plan.get("auto_message", "")
                                # LLM-Polish: "Ich habe mir erlaubt..." Butler-Stil
                                if _plan_msg:
                                    _plan_msg = await self._polish_auto_action(
                                        _plan_msg
                                    )
                            if _plan_msg:
                                await self._notify(
                                    "person_arrived",
                                    LOW,
                                    {
                                        "message": _plan_msg,
                                    },
                                )
                    except Exception as _pp_err:
                        logger.debug("Proactive Planner (person_arrived): %s", _pp_err)

            elif old_val == "home" and new_val != "home":
                # Phase 7.4: Abschied mit Sicherheits-Hinweis
                # Einkaufsliste pruefen und an departure_check anhaengen
                _shopping_enabled = yaml_config.get("proactive", {}).get(
                    "departure_shopping_reminder", True
                )
                _shopping_items = (
                    await self._get_open_shopping_items() if _shopping_enabled else []
                )
                _departure_data = {
                    "person": name,
                    "departure_check": True,
                }
                if _shopping_items:
                    _departure_data["shopping_items"] = _shopping_items
                    _departure_data["shopping_count"] = len(_shopping_items)
                await self._notify("person_left", MEDIUM, _departure_data)
                try:
                    await self.brain.ha.log_activity(
                        "presence",
                        "person_left",
                        f"{name} hat das Haus verlassen",
                        arguments={"person": name},
                    )
                except Exception as e:
                    logger.debug("Aktivitaetslog Abwesenheit fehlgeschlagen: %s", e)
                # MCU-JARVIS: Abwesenheits-Akkumulator starten
                if yaml_config.get("return_briefing", {}).get("enabled", True):
                    await self._start_absence_accumulator(name)

        # Phase 18: Wetter-Änderung → Proactive Planner
        elif entity_id.startswith("weather."):
            _rain_conditions = {
                "rainy",
                "pouring",
                "lightning-rainy",
                "lightning",
                "hail",
            }
            _old_cond = old_val.lower() if old_val else ""
            _new_cond = new_val.lower() if new_val else ""
            # Nur bei signifikanten Änderungen (Richtung schlecht)
            if _new_cond in _rain_conditions and _old_cond not in _rain_conditions:
                if (
                    hasattr(self.brain, "proactive_planner")
                    and self.brain.proactive_planner.enabled
                ):
                    try:
                        _w_ctx = {
                            "weather": {"condition": _new_cond},
                            "house": {"open_windows": []},
                        }
                        # Offene Fenster ermitteln
                        _states = await self.brain.ha.get_states()
                        for _s in _states or []:
                            _eid = _s.get("entity_id", "")
                            if (
                                _eid.startswith("binary_sensor.")
                                and "window" in _eid
                                and _s.get("state") == "on"
                            ):
                                _w_ctx["house"]["open_windows"].append(
                                    _eid.replace("binary_sensor.", "").replace("_", " ")
                                )
                        _autonomy = getattr(self.brain, "autonomy", None)
                        _auto_lvl = _autonomy.level if _autonomy is not None else 2
                        _plan = (
                            await self.brain.proactive_planner.plan_from_context_change(
                                "weather_changed",
                                _w_ctx,
                                _auto_lvl,
                            )
                        )
                        if _plan:
                            if _plan.get("needs_confirmation"):
                                _plan_msg = _plan.get("message", "")
                            else:
                                _plan_msg = _plan.get("auto_message", "")
                                if _plan_msg:
                                    _plan_msg = await self._polish_auto_action(
                                        _plan_msg
                                    )
                            if _plan_msg:
                                await self._notify(
                                    "weather_warning",
                                    LOW,
                                    {
                                        "message": _plan_msg,
                                    },
                                )
                    except Exception as _wp_err:
                        logger.debug("Proactive Planner (weather_changed): %s", _wp_err)

        # Phase 7.4: Geo-Fence Proximity (proximity.home Entity)
        elif (
            entity_id.startswith("proximity.") or entity_id.startswith("sensor.")
        ) and "distance" in entity_id:
            await self._check_geo_fence(entity_id, new_val, old_val, new_state)

        # Phase 7.1 + 10.1: Bewegung erkannt → Morning/Evening Briefing + Musik-Follow + Nacht-Kamera + Follow-Me
        elif (
            entity_id.startswith("binary_sensor.")
            and "motion" in entity_id
            and new_val == "on"
        ):
            await self._check_morning_briefing(motion_entity=entity_id)
            await self._check_evening_briefing()
            await self._check_music_follow(entity_id)
            await self._check_night_motion_camera(entity_id)
            await self._check_follow_me(entity_id)
            await self._check_presence_lighting(entity_id, new_val)

        # Bettsensor + Lux-Sensor Events → LightEngine
        if entity_id.startswith("binary_sensor.") or entity_id.startswith("sensor."):
            await self._check_bed_sensor_event(entity_id, new_val, old_val)
            await self._check_lux_sensor_event(entity_id, new_val)

        # Waschmaschine / Trockner / Geschirrspueler: Power-basierte Erkennung
        # mit Idle-Bestaetigung (wartet X Minuten bevor "fertig" gemeldet wird)
        if entity_id.startswith("sensor."):
            await self._check_appliance_power(entity_id, new_val, old_val)

        # Device-Dependency Konflikte: Rollen-basierte Erkennung
        try:
            await self._check_device_dependency_conflict(entity_id, new_val, old_val)
        except Exception as _ddc_err:
            logger.debug("Device-Dependency-Conflict Fehler: %s", _ddc_err)

        # Feature 2: Manual Override Detection für Covers
        # Ignoriere: unavailable/unknown (offline/online), opening/closing (Bewegungs-Abschlüsse)
        _non_physical = {"unavailable", "unknown", ""}
        _transitional = {
            "opening",
            "closing",
        }  # opening->open / closing->closed sind keine neuen Aktionen
        if (
            entity_id.startswith("cover.")
            and new_val != old_val
            and old_val not in _non_physical
            and new_val not in _non_physical
            and old_val not in _transitional
        ):
            try:
                redis_client = getattr(
                    getattr(self.brain, "memory", None), "redis", None
                )
                if redis_client:
                    acting_key = f"mha:cover:jarvis_acting:{entity_id}"
                    jarvis_triggered = await redis_client.get(acting_key)
                    if not jarvis_triggered:
                        override_hours = (
                            yaml_config.get("seasonal_actions", {})
                            .get("cover_automation", {})
                            .get("manual_override_hours", 2)
                        )
                        override_ttl = int(override_hours * 3600)
                        override_key = f"mha:cover:manual_override:{entity_id}"
                        await redis_client.set(override_key, "1", ex=override_ttl)
                        logger.info(
                            "Cover Manual Override: %s manuell bedient (%s -> %s), Automatik pausiert für %dh",
                            entity_id,
                            old_val,
                            new_val,
                            override_hours,
                        )
                    else:
                        logger.debug(
                            "Cover state change %s (%s -> %s) — jarvis_acting gesetzt, kein Override",
                            entity_id,
                            old_val,
                            new_val,
                        )
            except Exception as e:
                logger.debug("Cover Manual Override Detection Fehler: %s", e)

        # Power-Close: Echtzeit-Reaktion auf Stromverbrauch-Sensoren
        if entity_id.startswith("sensor."):
            await self._check_power_close(entity_id, new_val, old_val)

        # Conditional Commands prüfen (Wenn-Dann-Logik)
        if hasattr(self.brain, "conditional_commands"):
            try:
                attrs = new_state.get("attributes", {})
                executed = await self.brain.conditional_commands.check_event(
                    entity_id,
                    new_val,
                    old_val,
                    attrs,
                )
                for action in executed:
                    logger.info(
                        "Conditional ausgeführt: %s -> %s",
                        action.get("label", ""),
                        action.get("action", ""),
                    )
                    await self._notify(
                        "conditional_executed",
                        MEDIUM,
                        {
                            "label": action.get("label", ""),
                            "action": action.get("action", ""),
                        },
                    )
            except Exception as e:
                logger.debug("Conditional-Check Fehler: %s", e)

        # Scene Device-Trigger: Geraet wechselt Status → Szene aktivieren
        await self._check_scene_device_trigger(entity_id, new_val, old_val)

        # Learning Observer: Manuelle Aktionen beobachten
        if hasattr(self.brain, "learning_observer"):
            try:
                # Person aus letzter Interaktion ableiten (wer hat zuletzt mit Jarvis gesprochen?)
                observer_person = getattr(self.brain, "_current_person", "") or ""
                await self.brain.learning_observer.observe_state_change(
                    entity_id,
                    new_val,
                    old_val,
                    person=observer_person,
                )
            except Exception as e:
                logger.debug("Learning Observer Fehler: %s", e)

    # States die als "aktiv/an" gelten fuer Device-Trigger
    _ACTIVE_STATES = {"on", "playing", "home", "active", "open", "detected"}

    async def _check_scene_device_trigger(
        self, entity_id: str, new_val: str, old_val: str
    ):
        """Prueft ob ein Geraete-Statuswechsel eine Szene aktivieren soll."""
        try:
            device_trigger_map = yaml_config.get("scenes", {}).get(
                "device_trigger_map", {}
            )
            if not device_trigger_map or entity_id not in device_trigger_map:
                return

            # Nur bei Wechsel zu "aktiv" triggern (nicht bei off/idle)
            new_lower = new_val.lower() if new_val else ""
            old_lower = old_val.lower() if old_val else ""
            if new_lower not in self._ACTIVE_STATES:
                return
            if old_lower in self._ACTIVE_STATES:
                return  # War schon aktiv, kein neuer Trigger

            scene_ids = device_trigger_map[entity_id]
            if not scene_ids:
                return

            # Szenen-Config laden um Aktivitaet + Transition zu ermitteln
            scenes_cfg = yaml_config.get("scenes", {})
            device_trigger_modes = scenes_cfg.get("device_trigger_modes", {})

            for scene_id in scene_ids:
                # [A] Cooldown: Prueft den gleichen Key wie _exec_activate_scene (30s)
                # damit Device-Trigger + Voice-Aktivierung sich gegenseitig blockieren
                redis = (
                    getattr(self.brain.memory, "redis", None)
                    if hasattr(self.brain, "memory")
                    else None
                )
                if redis:
                    cooldown_key = f"mha:scene:cooldown:{scene_id}"
                    try:
                        if await redis.get(cooldown_key):
                            logger.debug(
                                "Scene Device-Trigger: Cooldown aktiv fuer '%s'",
                                scene_id,
                            )
                            continue
                    except Exception as e:
                        logger.warning(
                            "Cooldown-Check fuer Szene '%s' fehlgeschlagen: %s",
                            scene_id,
                            e,
                        )

                # [B] UND-Modus: Alle anderen Trigger-Entities muessen ebenfalls aktiv sein
                trigger_mode = device_trigger_modes.get(scene_id, "or")
                if trigger_mode == "and":
                    all_trigger_entities = [
                        eid
                        for eid, sids in device_trigger_map.items()
                        if scene_id in sids
                    ]
                    if len(all_trigger_entities) > 1:
                        states = await self.brain.ha.get_states() or []
                        state_map = {
                            s.get("entity_id", ""): s.get("state", "").lower()
                            for s in states
                        }
                        all_active = all(
                            state_map.get(eid, "").lower() in self._ACTIVE_STATES
                            if eid != entity_id
                            else True
                            for eid in all_trigger_entities
                        )
                        if not all_active:
                            logger.debug(
                                "Scene Device-Trigger UND-Modus: %s aktiv, aber nicht alle Trigger fuer '%s' erfuellt",
                                entity_id,
                                scene_id,
                            )
                            continue

                # Cooldown wird von _exec_activate_scene gesetzt (gleicher Key)

                # [D] Szenen-Aktivitaet aus gespeicherter Config oder Defaults ableiten
                scene_data = scenes_cfg.get(scene_id, {})
                activity = scene_data.get("activity")

                if not activity:
                    _defaults = {
                        "filmabend": "watching",
                        "kino": "watching",
                        "schlafen": "sleeping",
                        "gute_nacht": "sleeping",
                        "aufwachen": "relaxing",
                        "gemuetlich": "relaxing",
                        "meditation": "focused",
                        "konzentration": "focused",
                        "telefonat": "in_call",
                        "meeting": "in_call",
                        "gaeste": "guests",
                        "nicht_stoeren": "focused",
                        "musik": "relaxing",
                        "arbeit": "focused",
                        "kochen": "relaxing",
                        "party": "guests",
                    }
                    activity = _defaults.get(scene_id, "relaxing")

                transition = scene_data.get("transition", 3)

                _silence_defaults = {
                    "filmabend",
                    "kino",
                    "schlafen",
                    "gute_nacht",
                    "meditation",
                    "konzentration",
                    "telefonat",
                    "meeting",
                    "nicht_stoeren",
                    "arbeit",
                }
                silence_default = scene_id in _silence_defaults
                silence = scene_data.get("silence", silence_default)

                # [E] Aktivitaets-Override setzen
                duration = max(transition * 20, 60)
                self.brain.activity.set_manual_override(
                    activity, duration_minutes=duration
                )

                # [F] Szenen-Aktionen ausfuehren (Licht, Cover, Klima)
                await self._execute_scene_actions(scene_id)

                logger.info(
                    "Scene Device-Trigger: %s (%s→%s) → Szene '%s' (activity=%s, silence=%s)",
                    entity_id,
                    old_val,
                    new_val,
                    scene_id,
                    activity,
                    silence,
                )

                await self._notify(
                    "scene_device_triggered",
                    LOW,
                    {
                        "scene_id": scene_id,
                        "entity_id": entity_id,
                        "activity": activity,
                        "new_state": new_val,
                    },
                )

                break  # Nur erste passende Szene aktivieren
        except Exception as e:
            logger.debug("Scene Device-Trigger Fehler: %s", e)

    async def _execute_scene_actions(self, scene_id: str):
        """Fuehrt die Mood-Scene-Aktionen aus (Licht, Cover, Klima etc.).

        Delegiert an FunctionExecutor._exec_activate_scene (brain.executor).
        """
        try:
            executor = getattr(self.brain, "executor", None)
            if executor and hasattr(executor, "_exec_activate_scene"):
                result = await executor._exec_activate_scene({"scene": scene_id})
                logger.debug(
                    "Scene-Actions fuer '%s' ausgefuehrt: %s",
                    scene_id,
                    result.get("message", ""),
                )
                return

            logger.warning(
                "Scene-Actions: brain.executor nicht verfuegbar fuer '%s'", scene_id
            )
        except Exception as e:
            logger.warning("Scene-Actions Fehler fuer '%s': %s", scene_id, e)

    def _match_appliance(self, entity_id: str) -> Optional[str]:
        """Prueft ob entity_id ein bekanntes Geraet matched. Gibt appliance-key zurueck oder None."""
        eid = entity_id.lower()
        for appliance, patterns in self._appliance_patterns.items():
            if any(p.lower() in eid for p in patterns):
                return appliance
        return None

    async def _check_device_dependency_conflict(
        self, entity_id: str, new_val: str, old_val: str
    ):
        """Prueft ob State-Aenderung einen Device-Dependency-Konflikt ausloest.

        Nutzt DEVICE_DEPENDENCIES aus state_change_log.py mit Rollen-basiertem
        Matching. Meldet nur HIGH/MEDIUM-Konflikte (CRITICAL wie Rauch/Wasser
        werden bereits direkt in _handle_state_change behandelt).
        """
        # Quiet Hours: Nicht-kritische Dependency-Checks komplett ueberspringen.
        # Spart CPU und verhindert Log-Spam (z.B. Bettsensor alle 30 Min).
        if self._is_quiet_hours():
            return

        from .state_change_log import StateChangeLog, DEVICE_DEPENDENCIES

        role = StateChangeLog._get_entity_role(entity_id)
        if not role:
            return

        # Nur Regeln pruefen die durch diese Rolle getriggert werden
        # severity=info Regeln sind nur fuer LLM-Kontext, nicht fuer Notifications
        eid_lower = entity_id.lower()
        matching_deps = [
            d
            for d in DEVICE_DEPENDENCIES
            if d["role"] == role
            and d["state"] == new_val
            and d.get("severity", "info") in ("critical", "high")
            and not any(p in eid_lower for p in d.get("exclude_entity_patterns", []))
        ]
        if not matching_deps:
            return

        # Cooldown: max 1 Dependency-Notification pro Entity pro 30 Min
        redis_client = getattr(getattr(self.brain, "memory", None), "redis", None)
        if redis_client:
            cooldown_key = f"mha:dep_conflict:{entity_id}"
            already = await redis_client.get(cooldown_key)
            if already:
                return

        entity_room = StateChangeLog._get_entity_room(entity_id)

        # Aktuelle States holen
        all_states = await self.brain.ha.get_states()
        if not all_states:
            return

        state_dict = {
            s["entity_id"]: s.get("state", "") for s in all_states if "entity_id" in s
        }
        entity_roles = {eid: StateChangeLog._get_entity_role(eid) for eid in state_dict}
        entity_rooms = {eid: StateChangeLog._get_entity_room(eid) for eid in state_dict}

        found_conflicts = []
        for dep in matching_deps:
            affects_domain = dep.get("affects", "")
            same_room = dep.get("same_room", False)

            # requires_state: Nur Konflikt wenn betroffenes Entity in bestimmtem State ist
            required_states = dep.get("requires_state")

            # Finde betroffene Entities
            for eid, st in state_dict.items():
                e_role = entity_roles.get(eid, "")
                e_domain = eid.split(".")[0] if "." in eid else ""
                if e_domain == affects_domain or e_role == affects_domain:
                    if (
                        same_room
                        and entity_room
                        and entity_rooms.get(eid, "") != entity_room
                    ):
                        continue
                    # requires_state: Nur Konflikt wenn Entity in passendem State
                    if required_states and st not in required_states:
                        continue
                    # Konflikt gefunden
                    room_info = f" ({entity_room})" if entity_room else ""
                    found_conflicts.append(
                        {
                            "hint": dep.get("hint", dep.get("effect", "")),
                            "effect": dep.get("effect", ""),
                            "room": entity_room,
                            "room_info": room_info,
                            "trigger": entity_id,
                            "affected": eid,
                        }
                    )
                    break  # Ein Treffer pro Regel reicht

        if not found_conflicts:
            return

        # Cooldown setzen (30 Minuten)
        if redis_client:
            await redis_client.set(cooldown_key, "1", ex=1800)

        # Urgency aus severity der gematchten Regeln ableiten
        has_critical = any(
            d.get("severity") == "critical"
            for d in matching_deps
            if d["role"] == role and d["state"] == new_val
        )
        urgency = HIGH if has_critical else MEDIUM

        hints = [c["hint"] for c in found_conflicts[:3]]
        await self._notify(
            "device_dependency_conflict",
            urgency,
            {
                "entity": entity_id,
                "role": role,
                "new_state": new_val,
                "conflicts": found_conflicts[:3],
                "hints": hints,
                "message": "; ".join(hints),
            },
        )
        try:
            await self.brain.ha.log_activity(
                "anomaly",
                "device_dependency_conflict",
                f"Geraetekonflikt: {entity_id} ({role}) → {'; '.join(hints[:2])}",
                arguments={
                    "entity_id": entity_id,
                    "role": role,
                    "conflicts": len(found_conflicts),
                },
            )
        except Exception as e:
            logger.debug("Aktivitaetslog Geraetekonflikt fehlgeschlagen: %s", e)

    async def _check_appliance_power(self, entity_id: str, new_val: str, old_val: str):
        """Appliance-Erkennung: Setzt idle-Marker bei Power-Drop, bestaetigt nach Wartezeit.

        Nutzt per-Appliance Power-Profile wenn vorhanden, ansonsten globale Schwellwerte.
        """
        appliance = self._match_appliance(entity_id)
        if not appliance:
            return
        if not new_val.replace(".", "", 1).isdigit():
            return

        redis_client = getattr(getattr(self.brain, "memory", None), "redis", None)
        if not redis_client:
            return

        try:
            new_num = float(new_val)
        except (ValueError, TypeError):
            return
        try:
            old_num = (
                float(old_val)
                if old_val and old_val not in ("unknown", "unavailable")
                else 0.0
            )
        except (ValueError, TypeError):
            old_num = 0.0

        # Per-Appliance Power-Profile verwenden (Fallback auf globale Schwellwerte)
        profile = self._appliance_power_profiles.get(appliance, {})
        power_high = float(profile.get("running", self._appliance_power_high))
        power_low = float(profile.get("idle", self._appliance_power_low))
        hysteresis = float(profile.get("hysteresis", 0))
        confirm_minutes = int(
            profile.get("confirm_minutes", self._appliance_confirm_minutes)
        )

        idle_key = f"mha:appliance:idle_since:{appliance}"
        running_key = f"mha:appliance:was_running:{appliance}"

        # F-091: Hysteresis — Geraet muss power_high + hysteresis ueberschreiten
        # um als "laufend" zu gelten, verhindert False-Positives bei Schwankungen
        if new_num >= power_high + hysteresis:
            # Geraet laeuft (wieder) — idle-Marker loeschen, running setzen
            await redis_client.set(running_key, entity_id, ex=86400)
            await redis_client.delete(idle_key)
            return

        if new_num < power_low and old_num >= power_high:
            # Power-Drop erkannt — war das Geraet vorher aktiv?
            was_running = await redis_client.get(running_key)
            if not was_running:
                return
            # Idle-Marker setzen (Timestamp) mit TTL
            await redis_client.set(
                idle_key, str(time.time()), ex=confirm_minutes * 60 + 120
            )
            logger.debug(
                "Appliance %s: Power-Drop erkannt, Idle-Timer gestartet (%d Min, Profil: high=%dW low=%dW)",
                appliance,
                confirm_minutes,
                power_high,
                power_low,
            )

            # Bestaetigungs-Task starten falls nicht schon laufend (Lock gegen Race Condition)
            async with self._state_lock:
                if (
                    not self._appliance_confirm_task
                    or self._appliance_confirm_task.done()
                ):
                    self._appliance_confirm_task = self._create_loop_task(
                        self._appliance_confirm_loop(),
                        name="proactive_appliance_confirm",
                    )

    async def _appliance_confirm_loop(self):
        """Prueft periodisch ob idle-Marker abgelaufen sind und meldet Geraete als fertig."""
        # Kuerzesten confirm_minutes aller Profile bestimmen fuer initialen Sleep
        min_confirm = self._appliance_confirm_minutes
        for profile in self._appliance_power_profiles.values():
            cm = int(profile.get("confirm_minutes", self._appliance_confirm_minutes))
            if cm < min_confirm:
                min_confirm = cm
        await asyncio.sleep(min_confirm * 60)

        redis_client = getattr(getattr(self.brain, "memory", None), "redis", None)
        if not redis_client:
            return

        for appliance in self._appliance_patterns:
            idle_key = f"mha:appliance:idle_since:{appliance}"
            running_key = f"mha:appliance:was_running:{appliance}"
            cooldown_key = f"mha:appliance:notified:{appliance}"

            idle_since_raw = await redis_client.get(idle_key)
            if not idle_since_raw:
                continue

            try:
                idle_since = float(idle_since_raw)
            except (ValueError, TypeError):
                continue

            # Per-device confirm_minutes aus Power-Profile (Fallback: global)
            profile = self._appliance_power_profiles.get(appliance, {})
            dev_confirm = int(
                profile.get("confirm_minutes", self._appliance_confirm_minutes)
            )

            elapsed = time.time() - idle_since
            if elapsed < dev_confirm * 60:
                continue

            # Cooldown pruefen (keine Doppel-Meldung innerhalb 1h)
            if await redis_client.get(cooldown_key):
                await redis_client.delete(idle_key)
                continue

            # Bestaetigt: Geraet ist fertig
            event_type = f"{appliance}_done"
            try:
                await self._notify(event_type, MEDIUM, {"appliance": appliance})
            except Exception as exc:
                logger.warning("Appliance %s: Notification failed: %s", appliance, exc)
            await redis_client.set(cooldown_key, "1", ex=3600)
            await redis_client.delete(idle_key)
            await redis_client.delete(running_key)
            logger.info(
                "Appliance %s: Fertig-Meldung gesendet (idle seit %.0fs, confirm=%dmin)",
                appliance,
                elapsed,
                dev_confirm,
            )

    async def _check_power_close(self, entity_id: str, new_val: str, old_val: str):
        """Echtzeit-Reaktion: Rollladen schliessen/oeffnen bei Stromverbrauch-Aenderung."""
        try:
            from assistant.cover_config import load_power_close_rules
        except ImportError:
            return

        try:
            new_num = float(new_val)
        except (ValueError, TypeError):
            return  # Kein numerischer Wert

        try:
            old_num = (
                float(old_val)
                if old_val and old_val not in ("unknown", "unavailable")
                else 0.0
            )
        except (ValueError, TypeError):
            old_num = 0.0

        rules = load_power_close_rules()
        if not rules:
            return

        for rule in rules:
            if not rule.get("is_active", True):
                continue
            if rule.get("power_sensor") != entity_id:
                continue

            threshold = rule.get("threshold", 50)
            close_pos = rule.get("close_position", 0)
            cover_ids = rule.get("cover_ids", [])
            if not cover_ids:
                continue

            redis_client = getattr(getattr(self.brain, "memory", None), "redis", None)
            auto_level = yaml_config.get("seasonal_actions", {}).get(
                "auto_execute_level", 2
            )

            # Schwellwert ueberschritten → Covers schliessen
            if new_num >= threshold and old_num < threshold:
                closed_count = 0
                for cid in cover_ids:
                    redis_key = f"mha:cover:power_close:{cid}"
                    acted = await self._auto_cover_action(
                        cid,
                        close_pos,
                        f"Stromverbrauch {entity_id} ({new_num:.0f} W >= {threshold} W)",
                        auto_level,
                        redis_client,
                        skip_power_lock=True,
                    )
                    if acted:
                        closed_count += 1
                        if redis_client:
                            try:
                                await redis_client.set(redis_key, "1", ex=86400)
                            except Exception as e:
                                logger.warning("Unhandled: %s", e)
                logger.info(
                    "Power-Close: %s über Schwelle (%s W >= %s W) → %d/%d Covers geschlossen",
                    entity_id,
                    new_num,
                    threshold,
                    closed_count,
                    len(cover_ids),
                )

            # Unter Schwellwert gefallen → Covers wieder oeffnen
            # Robuster Check: Auch wenn old_val unavailable/unknown war (z.B.
            # Smart-Plug schaltet ab: 42W → unavailable → 1W), prüfen wir
            # ob ein power_close-Lock existiert und der aktuelle Wert unter
            # dem Schwellwert liegt.
            elif new_num < threshold:
                # Nur reagieren wenn tatsächlich ein Übergang stattfand ODER
                # ein power_close-Lock existiert (= Covers wurden vorher geschlossen)
                has_any_lock = False
                if redis_client:
                    for cid in cover_ids:
                        try:
                            if await redis_client.get(f"mha:cover:power_close:{cid}"):
                                has_any_lock = True
                                break
                        except Exception as e:
                            logger.warning("Unhandled: %s", e)
                if not (old_num >= threshold or has_any_lock):
                    continue  # Kein Schwellen-Übergang und kein Lock → nichts tun
                # Nicht öffnen wenn jemand schläft — aber Lock trotzdem aufräumen
                states = await self.brain.ha.get_states()
                sleeping = await self._is_sleeping(states)
                opened_count = 0
                for cid in cover_ids:
                    redis_key = f"mha:cover:power_close:{cid}"
                    power_active = False
                    if redis_client:
                        try:
                            power_active = bool(await redis_client.get(redis_key))
                        except Exception as e:
                            logger.warning("Unhandled: %s", e)
                    if not power_active:
                        continue
                    # Lock immer aufräumen — Strom ist unter Schwelle,
                    # andere Automatiken sollen wieder greifen
                    if redis_client:
                        try:
                            await redis_client.delete(redis_key)
                        except Exception as e:
                            logger.warning("Unhandled: %s", e)
                    if sleeping:
                        continue  # Cover nicht öffnen, aber Lock ist weg
                    acted = await self._auto_cover_action(
                        cid,
                        100,
                        f"Stromverbrauch {entity_id} ({new_num:.0f} W < {threshold} W)",
                        auto_level,
                        redis_client,
                        skip_power_lock=True,
                    )
                    if acted:
                        opened_count += 1
                if sleeping:
                    logger.debug(
                        "Power-Close: %s unter Schwelle — Locks aufgeräumt, Öffnung übersprungen (Schlafmodus)",
                        entity_id,
                    )
                else:
                    logger.info(
                        "Power-Close: %s unter Schwelle (%s W < %s W) → %d/%d Covers geöffnet",
                        entity_id,
                        new_num,
                        threshold,
                        opened_count,
                        len(cover_ids),
                    )

    # ------------------------------------------------------------------
    # C3: Self-initiated Follow-ups — Offene Themen proaktiv aufgreifen
    # ------------------------------------------------------------------

    async def _run_followup_loop(self):
        """Periodischer Check auf offene Gespraechsthemen.

        Prueft alle 10 Minuten ob es unerledigte Themen gibt die
        JARVIS von sich aus ansprechen sollte (Butler-Instinkt).
        """
        await asyncio.sleep(120)  # 2 Min Startup-Delay
        logger.info("Follow-up Loop gestartet")

        while self._running:
            try:
                await self._check_pending_followups()
            except Exception as e:
                logger.debug("Follow-up Check Fehler: %s", e)

            await asyncio.sleep(600)  # Alle 10 Minuten

    async def _check_pending_followups(self):
        """Prueft offene Themen und generiert natuerliche Follow-ups."""
        followup_cfg = yaml_config.get("self_followup", {})
        if not followup_cfg.get("enabled", True):
            return

        # Quiet Hours: Keine Follow-ups nachts
        if self._is_quiet_hours():
            return

        # Offene Themen aus Memory laden
        pending = await self.brain.memory.get_pending_conversations()
        if not pending:
            return

        # Nur Themen die mindestens 15 Min alt sind (User hatte Zeit)
        min_age = followup_cfg.get("min_age_minutes", 15)
        max_per_check = followup_cfg.get("max_per_check", 1)
        candidates = [t for t in pending if t.get("age_minutes", 0) >= min_age]

        if not candidates:
            return

        # Cooldown: Max 1 Follow-up pro Stunde
        _cooldown_key = "mha:followup:last_check"
        if self.brain.memory.redis:
            try:
                last = await self.brain.memory.redis.get(_cooldown_key)
                if last:
                    last_dt = datetime.fromisoformat(last)
                    cooldown_min = followup_cfg.get("cooldown_minutes", 60)
                    if (
                        datetime.now(timezone.utc) - last_dt
                    ).total_seconds() < cooldown_min * 60:
                        return
            except Exception as e:
                logger.warning("Follow-up Cooldown-Check fehlgeschlagen: %s", e)

        # MCU Sprint 2: Also check ConversationMemory follow-ups
        if (
            hasattr(self.brain, "conversation_memory")
            and self.brain.conversation_memory
        ):
            try:
                cm_followups = (
                    await self.brain.conversation_memory.get_pending_followups()
                )
                for fu in cm_followups:
                    topic = fu.get("topic", "")
                    if topic and not any(
                        c.get("topic", "") == topic for c in candidates
                    ):
                        candidates.append(
                            {
                                "topic": topic,
                                "context": fu.get("context", ""),
                                "person": fu.get("person", ""),
                                "age_minutes": 120,  # Treat as old enough
                            }
                        )
            except Exception as e:
                logger.debug("ConversationMemory Follow-up Check fehlgeschlagen: %s", e)

        # Aeltestes Thema zuerst
        candidates.sort(key=lambda t: t.get("age_minutes", 0), reverse=True)
        delivered = 0

        for topic_entry in candidates[:max_per_check]:
            topic = topic_entry.get("topic", "")
            context = topic_entry.get("context", "")
            person = topic_entry.get("person", "")

            if not topic:
                continue

            # JARVIS-Stil Follow-up generieren via LLM
            followup_text = await self._generate_followup_message(
                topic,
                context,
                person,
            )

            if followup_text:
                await self._deliver(
                    followup_text,
                    event_type="pending_followup",
                    urgency=LOW,
                    delivery_method="tts_quiet",
                    volume=0.6,
                )
                # Thema als erledigt markieren (wurde angesprochen)
                await self.brain.memory.resolve_conversation(topic)
                delivered += 1
                logger.info("Follow-up geliefert: %s", topic)

        # Cooldown-Marker setzen
        if delivered > 0 and self.brain.memory.redis:
            try:
                await self.brain.memory.redis.set(
                    _cooldown_key,
                    datetime.now(timezone.utc).isoformat(),
                    ex=7200,
                )
            except Exception as e:
                logger.warning("Follow-up Cooldown-Marker setzen fehlgeschlagen: %s", e)

    async def _generate_followup_message(
        self,
        topic: str,
        context: str,
        person: str,
    ) -> str:
        """Generiert eine natuerliche Follow-up Nachricht im JARVIS-Stil."""
        title = get_person_title(person) if person else get_person_title()

        prompt = (
            f"Du bist JARVIS, ein Butler-KI. Generiere eine kurze, natuerliche "
            f"Follow-up Nachricht fuer {title}.\n\n"
            f"Offenes Thema: {topic}\n"
        )
        if context:
            prompt += f"Kontext: {context}\n"
        prompt += (
            f"\nRegeln:\n"
            f"- Maximal 1-2 Saetze\n"
            f"- Natuerlich, nicht aufdringlich\n"
            f"- JARVIS-typisch: hoeflich, knapp, butler-maessig\n"
            f"- Sprich {title} direkt an\n"
            f"- Kein 'Hallo' oder 'Guten Tag'\n"
            f"- Beispiel: '{title}, du wolltest mir noch von deinem Meeting erzaehlen.'\n"
        )

        try:
            from .ollama_client import OllamaClient

            ollama: OllamaClient = self.brain.ollama
            response = await asyncio.wait_for(
                ollama.chat(
                    model=self.brain.model_router.fast_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                ),
                timeout=8.0,
            )
            text = response.get("message", {}).get("content", "").strip()
            # Validierung: Nicht zu lang, nicht leer
            if text and len(text) < 300:
                return text
        except Exception as e:
            logger.debug("Follow-up LLM Fehler: %s", e)

        # Fallback: Statische Nachricht
        return (
            f"{title}, du hattest vorhin '{topic}' erwaehnt — soll ich daran erinnern?"
        )

    async def _check_morning_briefing(self, motion_entity: str = ""):
        """Phase 7.1: Prüft ob Morning Briefing bei erster Bewegung am Morgen geliefert werden soll.

        D1: Adaptive Briefing-Zeit — lernt die typische Aufwach-Zeit und passt
        das Zeitfenster automatisch an (+/- 1 Stunde um den Durchschnitt).
        """
        if not self._mb_enabled:
            return

        now = datetime.now(_LOCAL_TZ)
        today = now.strftime("%Y-%m-%d")

        # D1: Adaptives Zeitfenster aus gelernter Aufwach-Zeit
        window_start = self._mb_window_start
        window_end = self._mb_window_end
        if self._mb_adaptive and hasattr(self, "brain") and self.brain.memory.redis:
            try:
                raw = await self.brain.memory.redis.get("mha:briefing:avg_wakeup_hour")
                if raw:
                    avg_hour = float(raw)
                    window_start = max(4, int(avg_hour) - 1)
                    window_end = min(12, int(avg_hour) + 2)
            except Exception as e:
                logger.debug("Adaptive Briefing-Zeit Abruf fehlgeschlagen: %s", e)

        # Reset am neuen Tag — lock prevents double-trigger from concurrent motion events
        async with self._state_lock:
            if self._mb_last_date != today:
                self._mb_triggered_today = False
                self._mb_last_date = today

            # Schon heute geliefert?
            if self._mb_triggered_today:
                return

            # Innerhalb des Morgen-Fensters?
            if not (window_start <= now.hour < window_end):
                return

            # Claim trigger slot before releasing lock
            self._mb_triggered_today = True

        # D1: Aufwach-Zeit lernen (EMA über 7 Tage)
        if self._mb_adaptive and hasattr(self, "brain") and self.brain.memory.redis:
            try:
                _redis = self.brain.memory.redis
                _current_hour = now.hour + now.minute / 60.0
                _raw = await _redis.get("mha:briefing:avg_wakeup_hour")
                if _raw:
                    _avg = float(_raw)
                    _alpha = 0.15  # EMA-Faktor: ~7 Tage Glaettung
                    _new_avg = _avg * (1 - _alpha) + _current_hour * _alpha
                else:
                    _new_avg = _current_hour
                await _redis.setex(
                    "mha:briefing:avg_wakeup_hour", 30 * 86400, str(round(_new_avg, 2))
                )
                logger.debug(
                    "D1: Aufwach-Zeit gelernt: %.1f → avg=%.1f", _current_hour, _new_avg
                )
            except Exception as _e:
                logger.debug("D1: Aufwach-Zeit Tracking fehlgeschlagen: %s", _e)

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
                level = getattr(autonomy, "level", 3) if autonomy else 3
                wakeup_done = await self.brain.routines.execute_wakeup_sequence(
                    autonomy_level=level,
                )
                if wakeup_done:
                    logger.info(
                        "Aufwach-Sequenz ausgeführt, Briefing-Delay: %ds",
                        self._ws_briefing_delay,
                    )
                    await asyncio.sleep(self._ws_briefing_delay)
            except Exception as e:
                logger.debug("Aufwach-Sequenz Fehler: %s", e)

        # Briefing generieren (routine_engine prüft intern ob schon geliefert via Redis)
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

                # Cover-Zusammenfassung im Morgen-Briefing
                try:
                    cover_summary = await self.get_cover_summary()
                    if cover_summary:
                        text = f"{text}\n{cover_summary}"
                except Exception as e:
                    logger.debug("Cover-Summary Fehler: %s", e)

                # JARVIS-Begrüßung: Person-aware Anrede
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
                # Persoenlichkeits-konsistente Greetings basierend auf Sarkasmus-Level
                _sarcasm = getattr(self.brain, "personality", None)
                _sl = getattr(_sarcasm, "sarcasm_level", 2) if _sarcasm else 2
                if _sl >= 3:
                    _greetings = [
                        f"Morgen, {_title}. Systeme laufen. Du uebrigens auch.",
                        f"Guten Morgen, {_title}. Ich war schon wach.",
                        f"Morgen, {_title}. Hier die Lage — kurz, bevor du fragst.",
                        f"Guten Morgen. Alles im Griff, {_title}.",
                    ]
                else:
                    _greetings = [
                        f"Guten Morgen, {_title}.",
                        f"Morgen, {_title}. Systeme laufen.",
                        f"Guten Morgen. Alles bereit, {_title}.",
                        f"Morgen, {_title}. Hier die Lage.",
                    ]
                greeting = random.choice(_greetings)
                text = f"{greeting} {text}"

                await emit_proactive(text, "morning_briefing", MEDIUM)
                logger.info("Morning Briefing automatisch geliefert")

                # B3: Pending Tages-Zusammenfassung nach Briefing liefern
                if self.brain.memory and self.brain.memory.redis:
                    pending = await self.brain.memory.redis.get("mha:pending_summary")
                    if pending:
                        summary = (
                            pending.decode() if isinstance(pending, bytes) else pending
                        )
                        await asyncio.sleep(3)  # Kurze Pause nach dem Briefing
                        await emit_proactive(
                            f"Uebrigens, gestern zusammengefasst: {summary}",
                            "daily_summary",
                            LOW,
                        )
                        await self.brain.memory.redis.delete("mha:pending_summary")
                        logger.info("Pending Tages-Zusammenfassung zugestellt")
        except Exception as e:
            logger.error("Morning Briefing Auto-Trigger Fehler: %s", e)

    async def _check_evening_briefing(self):
        """JARVIS Evening Briefing: Abend-Status bei erster Bewegung abends."""
        if not self._eb_enabled:
            return

        now = datetime.now(_LOCAL_TZ)
        today = now.strftime("%Y-%m-%d")

        # Reset am neuen Tag — lock prevents double-trigger from concurrent events
        async with self._state_lock:
            if self._eb_last_date != today:
                self._eb_triggered_today = False
                self._eb_last_date = today

            if self._eb_triggered_today:
                return

            if not (self._eb_window_start <= now.hour < self._eb_window_end):
                return

            # Claim trigger slot before releasing lock
            self._eb_triggered_today = True

        try:
            text = await self.generate_evening_briefing()
            if text:
                await emit_proactive(text, "evening_briefing", LOW)
                logger.info("Evening Briefing geliefert: %s", text[:500])
        except Exception as e:
            logger.debug("Evening Briefing Fehler: %s", e)

        # Persönliche Daten prüfen (Geburtstags-Erinnerung für morgen)
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

            # Offene Fenster/Tueren — kategorisiert nach Typ
            from .function_calling import is_window_or_door, get_opening_type

            open_items = []
            open_gates = []
            for s in states:
                eid = s.get("entity_id", "")
                if is_window_or_door(eid, s) and s.get("state") == "on":
                    name = s.get("attributes", {}).get("friendly_name", eid)
                    opening_type = get_opening_type(eid, s)
                    if opening_type == "gate":
                        open_gates.append(name)
                    else:
                        open_items.append(name)

            # Unverriegelte Schloesser
            unlocked = []
            for s in states:
                if (
                    s.get("entity_id", "").startswith("lock.")
                    and s.get("state") != "locked"
                ):
                    name = s.get("attributes", {}).get("friendly_name", s["entity_id"])
                    unlocked.append(name)

            # Wetter morgen (falls verfügbar)
            _cond_map = {
                "sunny": "sonnig",
                "clear-night": "klare Nacht",
                "partlycloudy": "teilweise bewölkt",
                "cloudy": "bewölkt",
                "rainy": "Regen",
                "pouring": "Starkregen",
                "snowy": "Schnee",
                "snowy-rainy": "Schneeregen",
                "fog": "Nebel",
                "hail": "Hagel",
                "lightning": "Gewitter",
                "lightning-rainy": "Gewitter mit Regen",
                "windy": "windig",
                "windy-variant": "windig & bewölkt",
                "exceptional": "Ausnahmewetter",
            }
            weather_tomorrow = ""
            for s in states:
                if s.get("entity_id", "").startswith("weather."):
                    forecast = s.get("attributes", {}).get("forecast", [])
                    if forecast and len(forecast) > 1:
                        tmrw = forecast[1]
                        cond = _cond_map.get(
                            tmrw.get("condition", ""), tmrw.get("condition", "?")
                        )
                        weather_tomorrow = (
                            f"Morgen {tmrw.get('temperature', '?')} Grad, {cond}."
                        )
                    break

            # Innentemperatur: Konfigurierte Sensoren (Mittelwert) bevorzugen
            temp = ""
            rt_sensors = (
                yaml_config.get("room_temperature", {}).get("sensors", []) or []
            )
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

            # Lichter noch an? (nur wenn lighting.enabled)
            lighting_cfg = yaml_config.get("lighting", {})
            lights_on = []
            if lighting_cfg.get("enabled", True):
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
            if open_gates:
                parts.append(f"Tore offen: {', '.join(open_gates)}.")
            if unlocked:
                parts.append(f"Unverriegelt: {', '.join(unlocked)}.")

            # Proaktive Abend-Empfehlungen (JARVIS denkt mit)
            suggestions = []
            if covers_open:
                suggestions.append(
                    f"Rolllaeden noch offen: {', '.join(covers_open[:3])}."
                )
            if lights_on and len(lights_on) >= 3:
                suggestions.append(f"{len(lights_on)} Lichter noch an.")
            if open_items:
                suggestions.append("Fenster vor der Nacht schliessen?")
            if open_gates:
                suggestions.append("Tore schliessen?")
            if unlocked:
                suggestions.append("Schloesser verriegeln?")
            if suggestions:
                parts.append("Vorschläge: " + " ".join(suggestions))
            elif not open_items and not open_gates and not unlocked:
                parts.append("Alles gesichert.")

            if not parts:
                return ""

            # LLM-Polish im JARVIS-Stil
            # Person-aware Anrede: übergebener Parameter hat Vorrang
            if person:
                _eb_person = person
            else:
                _eb_persons = await self._get_persons_at_home()
                _eb_person = _eb_persons[0] if len(_eb_persons) == 1 else ""
            _eb_title = (
                get_person_title(_eb_person) if _eb_person else get_person_title()
            )
            prompt = (
                f'Abend-Status-Bericht. Anrede: "{_eb_title}". '
                "Fasse zusammen, JARVIS-Butler-Stil, max 3 Sätze. "
                "Bei offenen Rolllaeden: Direkt fragen 'Soll ich die Rolllaeden schliessen?'. "
                "Bei offenen Fenstern/Tueren: Kurz erwaehnen. "
                "VERBOTEN: 'Vorschlaege einreichen', 'naechsten Schritt bestätigen', "
                "'bitte bestätigen Sie'. Stattdessen direkt und knapp formulieren.\n"
                + "\n".join(parts)
            )

            response = await self.brain.ollama.chat(
                messages=[
                    {
                        "role": "system",
                        "content": self._get_notification_system_prompt(
                            person=_eb_person
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                model=settings.model_notify,
                think=False,
                max_tokens=500,
            )
            text = validate_notification(response.get("message", {}).get("content", ""))
            return text or ""

        except Exception as e:
            logger.debug("Evening Briefing Fehler: %s", e)
            return ""

    async def _check_personal_dates(self):
        """Proaktive Erinnerung an persönliche Daten (Geburtstage, Jahrestage).

        - days_until == 1: Abend-Erinnerung ("Morgen hat Lisa Geburtstag")
        - days_until == 0 + Nachmittags: Fallback falls Briefing verpasst
        Läuft max 1x pro Tag (Redis-Flag).
        """
        if not hasattr(self.brain, "memory") or not self.brain.memory:
            return
        semantic = getattr(self.brain.memory, "semantic", None)
        if not semantic:
            return
        redis_client = getattr(self.brain.memory, "redis", None)
        if not redis_client:
            return

        today = datetime.now(_LOCAL_TZ).strftime("%Y-%m-%d")
        flag_key = f"mha:personal_dates_checked:{today}"

        try:
            already = await redis_client.get(flag_key)
            if already:
                return
        except Exception as e:
            logger.warning("Error in _check_personal_dates: %s", e)
            return

        try:
            upcoming = await semantic.get_upcoming_personal_dates(days_ahead=2)
            if not upcoming:
                await redis_client.setex(flag_key, 86400, "1")
                return

            now = datetime.now(_LOCAL_TZ)
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
        """Motion-Kamera: Nachts oder bei Abwesenheit → Kamera-Snapshot analysieren."""
        from datetime import datetime

        try:
            hour = datetime.now(_LOCAL_TZ).hour
            is_night = hour >= 22 or hour < 6
            # Tagsueber: Nur analysieren wenn niemand zuhause
            _cam_cfg = yaml_config.get("cameras", {}).get("proactive_analysis", {})
            _away_mode = _cam_cfg.get("away_mode", True)
            is_away = False
            if _away_mode and hasattr(self.brain, "ha"):
                try:
                    is_away = not await self._is_anyone_home()
                except Exception as e:
                    logger.warning("Anwesenheitspruefung fehlgeschlagen: %s", e)
            if not is_night and not is_away:
                return

            # Nur Outdoor-Motion-Sensoren (indoor-Bewegung ist normal)
            eid_lower = motion_entity.lower()
            if not any(
                kw in eid_lower
                for kw in ("outdoor", "aussen", "garten", "einfahrt", "hof", "garage")
            ):
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
            description = await self.brain.camera_manager.analyze_night_motion(
                motion_entity
            )
            if description:
                await self._notify(
                    "night_motion_camera",
                    MEDIUM,
                    {
                        "entity": motion_entity,
                        "camera_description": description,
                    },
                )
        except Exception as e:
            logger.debug("Nacht-Motion-Kamera fehlgeschlagen: %s", e)

    async def _check_follow_me(self, motion_entity: str):
        """Follow-Me: Transferiert Musik/Licht/Klima wenn Person den Raum wechselt."""
        try:
            if not hasattr(self.brain, "follow_me") or not self.brain.follow_me.enabled:
                return

            # Person identifizieren: Wenn nur 1 Person zuhause, ist es die.
            persons_home = await self._get_persons_at_home() or []
            person = persons_home[0] if len(persons_home) == 1 else ""

            # Veraltete Tracking-Einträge bereinigen
            self.brain.follow_me.cleanup_stale_tracking()

            result = await self.brain.follow_me.handle_motion(
                motion_entity, person=person
            )
            if result and result.get("actions"):
                actions_desc = ", ".join(a["type"] for a in result["actions"])
                logger.info(
                    "Follow-Me Transfer: %s → %s (%s)",
                    result["from_room"],
                    result["to_room"],
                    actions_desc,
                )
        except Exception as e:
            logger.debug("Follow-Me Check fehlgeschlagen: %s", e)

    async def _get_open_shopping_items(self) -> list[str]:
        """Holt offene Eintraege von der HA-Einkaufsliste.

        Returns:
            Liste der nicht-erledigten Artikelnamen (leer wenn keine oder Fehler).
        """
        try:
            items = await self.brain.ha.api_get("/api/shopping_list")
            if not items or not isinstance(items, list):
                return []
            return [
                item.get("name", "")
                for item in items
                if not item.get("complete", False) and item.get("name")
            ]
        except Exception as e:
            logger.debug("Einkaufsliste nicht abrufbar: %s", e)
            return []

    async def _check_presence_lighting(self, entity_id: str, new_val: str):
        """Praesenz-Licht: Motion → LightEngine für Auto-On."""
        try:
            le = getattr(self.brain, "light_engine", None)
            if not le:
                return
            motion_sensors = (
                yaml_config.get("multi_room", {}).get("room_motion_sensors") or {}
            )
            room = None
            for room_name, sensor_id in motion_sensors.items():
                if sensor_id == entity_id:
                    room = room_name
                    break
            if not room:
                return
            if new_val == "on":
                await le.on_motion(entity_id, room)
            else:
                await le.on_motion_clear(entity_id, room)
        except Exception as e:
            logger.debug("Praesenz-Licht Check fehlgeschlagen: %s", e)

    async def _check_bed_sensor_event(self, entity_id: str, new_val: str, old_val: str):
        """Bettsensor → LightEngine für Sleep-Mode / Aufwach-Licht."""
        try:
            le = getattr(self.brain, "light_engine", None)
            if not le:
                return
            from .config import get_room_bed_sensors, get_bed_sensor_off_delay

            profiles = get_room_profiles()
            rooms = profiles.get("rooms", {})
            room = None
            room_cfg = None
            for room_name, rcfg in rooms.items():
                if entity_id in get_room_bed_sensors(rcfg):
                    room = room_name
                    room_cfg = rcfg
                    break
            if not room:
                return
            if new_val == "on" and old_val != "on":
                # Bei on: sofort, evtl. laufenden off-Timer abbrechen
                timer_key = f"_bed_off_timer_{entity_id}"
                existing = getattr(self, timer_key, None)
                if existing and not existing.done():
                    existing.cancel()
                    logger.debug(
                        "Bettsensor %s: off-delay abgebrochen (wieder belegt)",
                        entity_id,
                    )
                await le.on_bed_occupied(entity_id, room)
            elif new_val == "off" and old_val == "on":
                off_delay = get_bed_sensor_off_delay(room_cfg, entity_id)
                if off_delay > 0:
                    logger.debug(
                        "Bettsensor %s: off-delay %ds gestartet", entity_id, off_delay
                    )
                    timer_key = f"_bed_off_timer_{entity_id}"
                    task = asyncio.create_task(
                        self._delayed_bed_clear(
                            le, entity_id, room, off_delay, timer_key
                        )
                    )
                    task.add_done_callback(
                        lambda t: t.exception() if not t.cancelled() else None
                    )
                    setattr(self, timer_key, task)
                else:
                    await le.on_bed_clear(entity_id, room)
        except Exception as e:
            logger.debug("Bettsensor-Licht Check fehlgeschlagen: %s", e)

    async def _delayed_bed_clear(
        self, le, entity_id: str, room: str, delay: int, timer_key: str
    ):
        """Wartet delay Sekunden und fuehrt dann on_bed_clear aus, wenn nicht abgebrochen."""
        try:
            await asyncio.sleep(delay)
            logger.debug("Bettsensor %s: off-delay abgelaufen → bed_clear", entity_id)
            await le.on_bed_clear(entity_id, room)
        except asyncio.CancelledError:
            logger.debug("Bettsensor %s: off-delay wurde abgebrochen", entity_id)
        finally:
            if hasattr(self, timer_key):
                delattr(self, timer_key)

    async def _check_lux_sensor_event(self, entity_id: str, new_val: str):
        """Lux-Sensor → LightEngine für adaptive Helligkeit."""
        try:
            le = getattr(self.brain, "light_engine", None)
            if not le:
                return
            profiles = get_room_profiles()
            rooms = profiles.get("rooms", {})
            room = None
            for room_name, room_cfg in rooms.items():
                if room_cfg.get("lux_sensor") == entity_id:
                    room = room_name
                    break
            if not room:
                return
            try:
                lux_value = float(new_val)
            except (ValueError, TypeError):
                return
            await le.on_lux_change(entity_id, room, lux_value)
        except Exception as e:
            logger.debug("Lux-Sensor Check fehlgeschlagen: %s", e)

    async def _check_music_follow(self, motion_entity: str):
        """Phase 10.1: Prüft ob Musik dem User in einen neuen Raum folgen soll."""
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
            for s in states or []:
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

            # Nur melden wenn der neue Raum NICHT der Raum ist in dem Musik läuft
            if new_room.lower() == playing_room.lower():
                return

            # Cooldown: Nicht staendig fragen (1x pro 5 Minuten)
            cooldown_key = "music_follow"
            last_time = await self.brain.memory.get_last_notification_time(cooldown_key)
            if last_time:
                last_dt = datetime.fromisoformat(last_time)
                if datetime.now(timezone.utc) - last_dt < timedelta(minutes=5):
                    return

            # Phase 10.1: Auto-Follow bei hohem Autonomie-Level
            auto_follow = multi_room_cfg.get("auto_follow", False)
            _autonomy = getattr(self.brain, "autonomy", None)
            if auto_follow and _autonomy and _autonomy.level >= 4:
                # Automatisch Musik transferieren
                target_speaker = multi_room_cfg.get("room_speakers", {}).get(new_room)
                if target_speaker:
                    try:
                        await self.brain.ha.call_service(
                            "media_player",
                            "join",
                            {
                                "entity_id": target_speaker,
                                "group_members": [playing_entity],
                            },
                        )
                        logger.info(
                            "Auto-Follow: Musik von %s nach %s transferiert",
                            playing_room,
                            new_room,
                        )
                    except Exception as e:
                        logger.debug("Auto-Follow Transfer fehlgeschlagen: %s", e)

            await self._notify(
                "music_follow",
                LOW,
                {
                    "from_room": playing_room,
                    "to_room": new_room,
                    "player_entity": playing_entity,
                    "auto_followed": auto_follow and _autonomy and _autonomy.level >= 4,
                },
            )

        except Exception as e:
            logger.debug("Music-Follow Check fehlgeschlagen: %s", e)

    async def _check_geo_fence(
        self, entity_id: str, new_val: str, old_val: str, state: dict
    ):
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
                if datetime.now(timezone.utc) - last_dt < timedelta(
                    minutes=GEO_APPROACHING_COOLDOWN_MIN
                ):
                    return
            await self.brain.memory.set_last_notification_time(cooldown_key)
            await self._notify(
                "person_approaching",
                LOW,
                {
                    "person": person_name,
                    "distance_km": round(new_distance, 1),
                    "entity": entity_id,
                },
            )

        # "Gleich da" — unter 0.5km
        elif old_distance > threshold_close >= new_distance:
            cooldown_key = f"geo_arriving:{entity_id}"
            last = await self.brain.memory.get_last_notification_time(cooldown_key)
            if last:
                last_dt = datetime.fromisoformat(last)
                if datetime.now(timezone.utc) - last_dt < timedelta(
                    minutes=GEO_ARRIVING_COOLDOWN_MIN
                ):
                    return
            await self.brain.memory.set_last_notification_time(cooldown_key)
            await self._notify(
                "person_arriving",
                MEDIUM,
                {
                    "person": person_name,
                    "distance_km": round(new_distance, 1),
                    "entity": entity_id,
                },
            )

    async def _handle_mindhome_event(self, data: dict):
        """Verarbeitet MindHome-spezifische Events."""
        event_name = data.get("event", "")
        urgency = data.get("urgency", MEDIUM)
        await self._notify(event_name, urgency, data)

    async def _notify(self, event_type: str, urgency: str, data: dict):
        """Prüft ob gemeldet werden soll und erzeugt Meldung."""

        # MCU-JARVIS: Event für Rückkehr-Briefing akkumulieren
        try:
            await self._accumulate_event(event_type, urgency, data)
        except Exception as e:
            logger.warning("Error in _accumulate_event: %s", e)

        # Quiet Hours: Nur CRITICAL darf nachts durch
        if urgency != CRITICAL and self._is_quiet_hours():
            detail = data.get("entity") or data.get("task") or data.get("message") or ""
            logger.info(
                "Meldung unterdrückt (Quiet Hours): [%s] %s%s",
                urgency,
                event_type,
                f" ({detail})" if detail else "",
            )
            return

        # Autonomie-Level prüfen
        if urgency != CRITICAL:
            _autonomy = getattr(self.brain, "autonomy", None)
            level = _autonomy.level if _autonomy else 2
            if level < 2:  # Level 1 = nur Befehle
                return

        # Mood-Suppression: Bei Frustration/Stress nur HIGH+ durchlassen
        if urgency not in (CRITICAL, HIGH):
            try:
                mood_data = self.brain.mood.get_current_mood()
                mood = mood_data.get("mood", "neutral")
                if mood in ("frustrated", "stressed"):
                    detail = (
                        data.get("entity")
                        or data.get("task")
                        or data.get("message")
                        or ""
                    )
                    logger.info(
                        "Meldung unterdrückt (Mood=%s): [%s] %s%s",
                        mood,
                        urgency,
                        event_type,
                        f" ({detail})" if detail else "",
                    )
                    return
            except Exception as e:
                logger.warning("Error in Mood-Check: %s", e)

        # Scene-Suppression: Bei aktiver Szene LOW-Energy-Meldungen unterdrücken
        _SCENE_SUPPRESS_EVENTS = {"energy_price_high", "solar_surplus"}
        _SCENE_SUPPRESS_SCENES = {
            "filmabend",
            "kino",
            "party",
            "gute_nacht",
            "schlafen",
            "konzentration",
            "arbeiten",
            "meeting",
            "romantisch",
            "lesen",
        }
        if urgency == LOW and event_type in _SCENE_SUPPRESS_EVENTS:
            try:
                _scene_redis = getattr(self.brain.memory, "redis", None)
                if _scene_redis:
                    _active_scene = await _scene_redis.get("mha:scene:active")
                    if _active_scene:
                        _active_scene = (
                            _active_scene.decode()
                            if isinstance(_active_scene, bytes)
                            else _active_scene
                        )
                        if _active_scene in _SCENE_SUPPRESS_SCENES:
                            detail = data.get("entity") or data.get("message") or ""
                            logger.info(
                                "Meldung unterdrückt (Scene=%s): [%s] %s%s",
                                _active_scene,
                                urgency,
                                event_type,
                                f" ({detail})" if detail else "",
                            )
                            return
            except Exception as e:
                logger.warning("Szenen-Unterdrueckungspruefung fehlgeschlagen: %s", e)

        # D3: Kontextuelles Schweigen — Activity-basierte Unterdrückung
        # Film/Gäste/Schlaf → nur HIGH+ darf durch
        if urgency not in (CRITICAL, HIGH):
            try:
                _activity = getattr(self.brain, "activity", None)
                if _activity:
                    result = await _activity.should_deliver(urgency)
                    if result.get("suppress"):
                        activity = result.get("activity", "unknown")
                        detail = (
                            data.get("entity")
                            or data.get("task")
                            or data.get("message")
                            or ""
                        )
                        logger.info(
                            "D3: Meldung unterdrückt (Activity=%s): [%s] %s%s",
                            activity,
                            urgency,
                            event_type,
                            f" ({detail})" if detail else "",
                        )
                        return
            except Exception as e:
                logger.warning("D3: Activity-Check fehlgeschlagen: %s", e)

        # #10: Kalender-Vorpruefung — waehrend eines Termins nur HIGH+ durchlassen
        if urgency not in (CRITICAL, HIGH):
            try:
                cal = getattr(self.brain, "calendar_intelligence", None)
                if cal:
                    event = await cal.is_in_event()
                    if event:
                        detail = (
                            data.get("entity")
                            or data.get("task")
                            or data.get("message")
                            or ""
                        )
                        logger.info(
                            "Meldung unterdrückt (Kalender: %s): [%s] %s%s",
                            event.get("summary", "Termin"),
                            urgency,
                            event_type,
                            f" ({detail})" if detail else "",
                        )
                        return
            except Exception as e:
                logger.debug("Kalender-Check fehlgeschlagen: %s", e)

        # #4: Conversation-Awareness — bei aktiver Konversation LOW unterdrücken
        if urgency == LOW:
            try:
                last_ts = getattr(self.brain, "_last_interaction_ts", 0)
                if last_ts and (time.time() - last_ts) < 120:
                    detail = (
                        data.get("entity")
                        or data.get("task")
                        or data.get("message")
                        or ""
                    )
                    logger.info(
                        "Meldung unterdrückt (User aktiv): [%s] %s%s",
                        urgency,
                        event_type,
                        f" ({detail})" if detail else "",
                    )
                    return
            except Exception as e:
                logger.warning(
                    "User-Aktivitaetspruefung fuer Notification fehlgeschlagen: %s", e
                )

        # Cooldown prüfen (mit adaptivem Cooldown aus Feedback)
        effective_cooldown = self.cooldown
        feedback = self.brain.feedback

        if urgency not in (CRITICAL, HIGH):
            # Feedback-basierte Entscheidung
            decision = await feedback.should_notify(event_type, urgency)
            if not decision["allow"]:
                detail = (
                    data.get("entity") or data.get("task") or data.get("message") or ""
                )
                logger.info(
                    "Meldung unterdrückt [%s]%s: %s",
                    event_type,
                    f" ({detail})" if detail else "",
                    decision["reason"],
                )
                return
            # Adaptiver Cooldown aus Feedback
            effective_cooldown = decision.get("cooldown", self.cooldown)

            # Cooldown prüfen
            last_time = await self.brain.memory.get_last_notification_time(event_type)
            if last_time:
                try:
                    last_dt = datetime.fromisoformat(last_time)
                except (ValueError, TypeError):
                    last_dt = None
                if last_dt and datetime.now(timezone.utc) - last_dt < timedelta(
                    seconds=effective_cooldown
                ):
                    detail = data.get("entity") or data.get("message", "")
                    logger.info(
                        "Meldung unterdrueckt (Cooldown %ds): [%s] %s",
                        effective_cooldown,
                        event_type,
                        (detail[:80] if isinstance(detail, str) else "")
                        if detail
                        else "",
                    )
                    return

        # Phase 15.4+: LOW und MEDIUM-Meldungen batchen statt sofort senden
        # MEDIUM wird kuerzere Batch-Intervalle haben (10 Min statt 30)
        if self.batch_enabled and urgency in (LOW, MEDIUM):
            description = self.event_handlers.get(event_type, (MEDIUM, event_type))[1]
            # F-033: Lock für shared batch_queue
            async with self._state_lock:
                if len(self._batch_queue) >= 1000:
                    self._batch_queue = self._batch_queue[-500:]
                self._batch_queue.append(
                    {
                        "event_type": event_type,
                        "urgency": urgency,
                        "description": description,
                        "data": data,
                        "time": datetime.now(timezone.utc).isoformat(),
                    }
                )

                medium_items = sum(
                    1 for b in self._batch_queue if b.get("urgency") == MEDIUM
                )
                should_flush = (
                    medium_items >= 5 or len(self._batch_queue) >= self.batch_max_items
                )
                queue_len = len(self._batch_queue)

            if should_flush:
                _t = asyncio.create_task(self._flush_batch())
                _t.add_done_callback(
                    lambda t: (
                        logger.warning("_flush_batch fehlgeschlagen: %s", t.exception())
                        if t.exception()
                        else None
                    )
                )
            logger.debug(
                "%s-Meldung gequeued [%s]: %s (%d in Queue, %d MEDIUM)",
                urgency.upper(),
                event_type,
                description,
                queue_len,
                medium_items,
            )
            return

        # CRITICAL: Interrupt-Kanal — sofort durchstellen, kein LLM-Polish nötig
        if urgency == CRITICAL:
            description = self.event_handlers.get(event_type, (CRITICAL, event_type))[1]

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

            # #20: Critical Alert mit Retry und Escalation
            await self._send_critical_with_retry(
                text,
                event_type,
                protocol,
                max_retries=3,
            )

            # Inner-State: Security-Event → Jarvis wird besorgt
            _inner = getattr(self.brain, "inner_state", None)
            if _inner:
                _tr = getattr(self.brain, "_task_registry", None)
                if _tr:
                    _tr.create_task(
                        _inner.on_security_event(),
                        name="inner_state_security",
                    )

            await self.brain.memory.set_last_notification_time(event_type)

            logger.warning(
                "INTERRUPT [%s/%s] (protocol: %s): %s",
                event_type,
                urgency,
                protocol,
                text,
            )
            return

        # Phase 6: Activity Engine + Silence Matrix
        activity_result = await self.brain.activity.should_deliver(urgency)
        if activity_result["suppress"]:
            logger.info(
                "Meldung unterdrückt [%s]: Aktivität=%s, Delivery=%s",
                event_type,
                activity_result["activity"],
                activity_result["delivery"],
            )
            return

        delivery_method = activity_result["delivery"]

        # Notification-ID generieren (für Feedback-Tracking)
        notification_id = f"notif_{uuid.uuid4().hex[:12]}"

        # #18: Semantische Duplikat-Erkennung vor LLM-Polish
        description = self.event_handlers.get(event_type, (MEDIUM, event_type))[1]
        _dedup_text = data.get("message", description)
        if urgency not in (CRITICAL, HIGH):
            try:
                if await self._is_semantically_duplicate(_dedup_text):
                    logger.info(
                        "Semantisches Duplikat unterdrückt: [%s] %s",
                        event_type,
                        _dedup_text[:60],
                    )
                    return
            except Exception as e:
                logger.debug("Semantische Duplikatpruefung fehlgeschlagen: %s", e)

        # Meldung generieren

        # Feature 3: Geräte-Persönlichkeit — narration statt LLM wenn moeglich
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
                # Person-aware Anrede für Device-Narration
                _narr_persons = await self._get_persons_at_home()
                _narr_person = _narr_persons[0] if len(_narr_persons) == 1 else ""
                narration_text = self.brain.personality.narrate_device_event(
                    entity_id,
                    narration_event_map[event_type],
                    detail=data.get("detail", ""),
                    person=_narr_person,
                )
            except Exception as e:
                logger.warning("Error in narration: %s", e)

        if narration_text:
            text = narration_text
            await self._deliver(
                text,
                event_type,
                urgency,
                notification_id,
                delivery_method=delivery_method,
                volume=activity_result.get("volume", 0.8),
            )
            await self.brain.memory.set_last_notification_time(event_type)
            await feedback.track_notification(notification_id, event_type)
            logger.info(
                "Proaktive Meldung [%s/%s] (narration, id: %s, delivery: %s): %s",
                event_type,
                urgency,
                notification_id,
                delivery_method,
                text,
            )
            return

        # D4: Eskalations-Intelligenz — graduelle Steigerung bei wiederholten Meldungen
        try:
            _esc_key = f"mha:notify_escalation:{event_type}"
            _redis = getattr(self.brain, "memory", None)
            _redis = _redis.redis if _redis else None
            if _redis:
                _esc_count = await _redis.incr(_esc_key)
                await _redis.expire(_esc_key, 6 * 3600)  # 6h Fenster
                if _esc_count == 1:
                    description = f"[ERSTE MELDUNG] {description}"
                elif _esc_count == 2:
                    description = f"[WIEDERHOLUNG #{_esc_count} — erhoehe Dringlichkeit natuerlich] {description}"
                elif _esc_count >= 3:
                    description = f"[WIEDERHOLUNG #{_esc_count} — sehr dringend, Butler wird bestimmter] {description}"
        except Exception as e:
            logger.debug("D4: Eskalations-Counter fehlgeschlagen: %s", e)

        prompt = self._build_notification_prompt(event_type, description, data, urgency)

        try:
            response = await self.brain.ollama.chat(
                messages=[
                    {
                        "role": "system",
                        "content": self._get_notification_system_prompt(
                            urgency, person=data.get("person", "")
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                model=settings.model_notify,
                think=False,
                max_tokens=300,
            )

            text = validate_notification(
                response.get("message", {}).get("content", description)
            )
            # Fallback auf Original wenn Reasoning-Leak komplett entfernt wurde
            if not text:
                text = description

            # Unified Delivery: WebSocket + TTS
            await self._deliver(
                text,
                event_type,
                urgency,
                notification_id,
                delivery_method=delivery_method,
                volume=activity_result.get("volume", 0.8),
            )

            # Cooldown setzen
            await self.brain.memory.set_last_notification_time(event_type)

            # Feedback-Tracker: Meldung registrieren (wartet auf Feedback)
            await feedback.track_notification(notification_id, event_type)

            logger.info(
                "Proaktive Meldung [%s/%s] (id: %s, delivery: %s, activity: %s): %s",
                event_type,
                urgency,
                notification_id,
                delivery_method,
                activity_result["activity"],
                text,
            )

        except Exception as e:
            logger.error(
                "Fehler bei proaktiver Meldung [%s/%s]: %s",
                event_type,
                urgency,
                e,
                exc_info=True,
            )

    async def _build_arrival_status(self, person_name: str) -> dict:
        """Baut einen Status-Bericht für eine ankommende Person."""
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
                    if (
                        s.get("state") == "home"
                        and pname.lower() != person_name.lower()
                    ):
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

            # Offene Fenster/Tueren — kategorisiert
            from .function_calling import is_window_or_door, get_opening_type

            open_items = []
            open_gates = []
            for s in states:
                eid = s.get("entity_id", "")
                if is_window_or_door(eid, s) and s.get("state") == "on":
                    name = s.get("attributes", {}).get("friendly_name", eid)
                    if get_opening_type(eid, s) == "gate":
                        open_gates.append(name)
                    else:
                        open_items.append(name)
            if open_items:
                status["open_items"] = open_items
            if open_gates:
                status["open_gates"] = open_gates

            # Aktive Lichter
            lights_on = sum(
                1
                for s in states
                if s.get("entity_id", "").startswith("light.")
                and s.get("state") == "on"
            )
            status["lights_on"] = lights_on

        except Exception as e:
            logger.debug("Fehler beim Status-Bericht: %s", e)

        return status

    # ------------------------------------------------------------------
    # MCU-JARVIS: Rückkehr-Briefing (Event-Akkumulator)
    # ------------------------------------------------------------------
    # Sammelt Events während eine Person weg ist und liefert ein
    # kompaktes Briefing bei Rückkehr. Wie JARVIS der Tony Stark
    # nach der Landung auf dem Laufenden haelt.

    _RETURN_BRIEFING_KEY = "mha:return_briefing:{person}"

    # Default Event-Typen (überschrieben durch settings.yaml return_briefing.event_types)
    _DEFAULT_BRIEFING_EVENT_TYPES = frozenset(
        [
            "doorbell",
            "person_arrived",
            "person_left",
            "washer_done",
            "dryer_done",
            "weather_warning",
            "low_battery",
            "entity_offline",
            "maintenance_due",
            "conditional_executed",
            "learning_suggestion",
            "threat_detected",
            "energy_price_high",
            "solar_surplus",
        ]
    )

    def _get_briefing_config(self) -> tuple:
        """Liest Return-Briefing Config: (ttl_seconds, max_events, event_types)."""
        rb_cfg = yaml_config.get("return_briefing", {})
        ttl = rb_cfg.get("ttl_hours", 24) * 3600
        max_events = rb_cfg.get("max_events", 20)
        # Event-Typen aus Config: nur aktivierte Typen
        cfg_types = rb_cfg.get("event_types", {})
        if cfg_types:
            active = {k for k, v in cfg_types.items() if v}
            event_types = active if active else self._DEFAULT_BRIEFING_EVENT_TYPES
        else:
            event_types = self._DEFAULT_BRIEFING_EVENT_TYPES
        return ttl, max_events, event_types

    async def _start_absence_accumulator(self, person_name: str):
        """Startet die Event-Sammlung für eine weggehende Person."""
        if not self.brain.memory.redis:
            return
        try:
            ttl, _, _ = self._get_briefing_config()
            key = self._RETURN_BRIEFING_KEY.format(person=person_name.lower())
            # Initialer Eintrag mit Abgangszeit
            initial = json.dumps(
                {
                    "departed": datetime.now(timezone.utc).isoformat(),
                    "events": [],
                }
            )
            await self.brain.memory.redis.setex(key, ttl, initial)
            logger.info("Rückkehr-Briefing Akkumulator gestartet für %s", person_name)
        except Exception as e:
            logger.debug("Akkumulator-Start fehlgeschlagen: %s", e)

    async def _accumulate_event(self, event_type: str, urgency: str, data: dict):
        """Fuegt ein Event zum Rückkehr-Briefing aller abwesender Personen hinzu.

        Wird aus _notify() aufgerufen — sammelt nur relevante Events.
        """
        _, max_events, event_types = self._get_briefing_config()
        if event_type not in event_types:
            return
        if not self.brain.memory.redis:
            return

        # Alle aktiven Akkumulatoren finden (person.* away)
        try:
            keys = []
            async for key in self.brain.memory.redis.scan_iter("mha:return_briefing:*"):
                keys.append(key)

            if not keys:
                return

            event_entry = {
                "type": event_type,
                "urgency": urgency,
                "summary": self.event_handlers.get(event_type, (MEDIUM, event_type))[1],
                "time": datetime.now(_LOCAL_TZ).strftime("%H:%M"),
                "detail": data.get("person", data.get("entity", "")),
            }

            for key in keys:
                raw = await self.brain.memory.redis.get(key)
                if raw is None:
                    continue
                try:
                    briefing_data = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    logger.debug("Ungültiges JSON in Key %s, überspringe", key)
                    continue
                events = briefing_data.get("events", [])
                # Max Events pro Abwesenheit (konfigurierbar)
                if len(events) < max_events:
                    events.append(event_entry)
                    briefing_data["events"] = events
                    ttl = await self.brain.memory.redis.ttl(key)
                    if ttl and ttl > 0:
                        await self.brain.memory.redis.setex(
                            key, ttl, json.dumps(briefing_data)
                        )
        except Exception as e:
            logger.debug("Event-Akkumulation fehlgeschlagen: %s", e)

    async def _build_return_briefing(self, person_name: str) -> str:
        """Baut ein kompaktes Rückkehr-Briefing aus gesammelten Events.

        Returns:
            Briefing-Text oder leerer String.
        """
        if not self.brain.memory.redis:
            return ""

        key = self._RETURN_BRIEFING_KEY.format(person=person_name.lower())
        try:
            raw = await self.brain.memory.redis.get(key)
            if not raw:
                return ""

            try:
                briefing_data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                logger.debug("Ungültiges JSON in Briefing-Key %s", key)
                return ""
            events = briefing_data.get("events", [])
            departed = briefing_data.get("departed", "")

            # Aufraeumen — Akkumulator entfernen
            await self.brain.memory.redis.delete(key)

            if not events:
                return ""

            # Kompaktes Briefing zusammenbauen
            # Gruppiere nach Typ, zaehle Mehrfach-Events
            from collections import Counter

            type_counts = Counter(e.get("type", "") for e in events)

            lines = []
            for evt_type, count in type_counts.most_common():
                summary = self.event_handlers.get(evt_type, (MEDIUM, evt_type))[1]
                # Details der letzten Instanz dieses Typs
                last_event = next(
                    (e for e in reversed(events) if e.get("type") == evt_type), {}
                )
                detail = last_event.get("detail", "")
                time_str = last_event.get("time", "")

                if count > 1:
                    lines.append(f"{summary} ({count}x)")
                elif detail:
                    lines.append(f"{summary}: {detail} ({time_str})")
                else:
                    lines.append(f"{summary} ({time_str})")

            if not lines:
                return ""

            # Abwesenheitsdauer berechnen
            duration_str = ""
            if departed:
                try:
                    dep_dt = datetime.fromisoformat(departed)
                    diff = datetime.now(timezone.utc) - dep_dt
                    hours = diff.total_seconds() / 3600
                    if hours >= 1:
                        duration_str = f" (Abwesend: {int(hours)}h {int(diff.total_seconds() % 3600 / 60)}min)"
                    else:
                        duration_str = (
                            f" (Abwesend: {int(diff.total_seconds() / 60)} Min)"
                        )
                except (ValueError, TypeError):
                    pass

            return (
                f"Während deiner Abwesenheit{duration_str}: " + ". ".join(lines) + "."
            )

        except Exception as e:
            logger.debug("Rückkehr-Briefing Aufbau fehlgeschlagen: %s", e)
            return ""

    async def generate_status_report(self, person_name: str = "") -> str:
        """Generiert einen Jarvis-artigen Status-Bericht (kann auch manuell aufgerufen werden)."""
        status = await self._build_arrival_status(person_name or "User")
        prompt = self._build_status_report_prompt(status)

        try:
            response = await self.brain.ollama.chat(
                messages=[
                    {
                        "role": "system",
                        "content": self._get_notification_system_prompt(
                            person=person_name
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                model=settings.model_notify,
                think=False,
                max_tokens=300,
            )
            return validate_notification(
                response.get("message", {}).get(
                    "content", f"Alles ruhig, {get_person_title(person_name)}."
                )
            )
        except Exception as e:
            logger.error("Fehler beim Status-Bericht: %s", e)
            return "Status-Abfrage fehlgeschlagen. Systeme prüfen."

    async def _get_persons_at_home(self) -> list[str]:
        """Gibt die Liste der aktuell anwesenden Personen zurück.

        Aktualisiert automatisch die active_person für get_person_title():
        - 1 Person zuhause: deren Name setzen
        - 0 Personen: leeren (verhindert veraltete Anrede)
        - Mehrere Personen: primary_user bevorzugen wenn anwesend
        - HA-Fehler: leeren (veraltete Daten sind schlimmer als Fallback)
        """
        try:
            states = await self.brain.ha.get_states()
            if not states:
                set_active_person("")
                return []
            persons = []
            for s in states:
                if s.get("entity_id", "").startswith("person."):
                    if s.get("state") == "home":
                        eid = s.get("entity_id", "")
                        # Entity-ID-Mapping hat Vorrang (zuverlaessiger als friendly_name)
                        pname = resolve_person_by_entity(eid)
                        if not pname:
                            pname = s.get("attributes", {}).get("friendly_name", "")
                        if pname:
                            persons.append(pname)
            # Active-Person aktualisieren
            if len(persons) == 1:
                set_active_person(persons[0])
            elif len(persons) == 0:
                set_active_person("")
            else:
                # Mehrere Personen: primary_user bevorzugen wenn anwesend
                primary = settings.user_name
                primary_found = ""
                for p in persons:
                    if p.lower() == primary.lower() or p.lower().startswith(
                        primary.lower()
                    ):
                        primary_found = p
                        break
                if primary_found:
                    set_active_person(primary_found)
                # Sonst: active_person nicht ändern (brain.py setzt bei Gespräch)
            return persons
        except Exception as e:
            # HA nicht erreichbar: active_person leeren statt veraltete Daten behalten
            logger.debug("HA-Status fuer active_person nicht erreichbar: %s", e)
            set_active_person("")
            return []

    async def _resolve_title_for_notification(self, data: dict) -> str:
        """Bestimmt die korrekte Anrede für eine Notification."""
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
        """Baut den Prompt für einen Status-Bericht (JARVIS-Butler-Stil)."""
        person = status.get("person", "User")
        title = self._get_person_title(person)
        parts = [
            f'{person} (Anrede: "{title}") ist gerade angekommen.',
            f"Erstelle einen knappen Butler-Status-Bericht. Wie JARVIS aus dem MCU.",
            f'WICHTIG: Sprich die Person mit "{title}" an, NICHT mit dem Vornamen.',
            "STIL: Sachlich, kompakt. Daten zuerst, dann Auffaelligkeiten. Kein 'Willkommen zuhause!'.",
            f"BEISPIEL: '21 Grad, {title}. Post war da. Küche-Fenster steht noch offen.'",
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
            parts.append(
                f"Wetter: {weather.get('temp', '?')}°C, {weather.get('condition', '?')}"
            )

        open_items = status.get("open_items", [])
        if open_items:
            parts.append(f"Offen: {', '.join(open_items)}")
        open_gates = status.get("open_gates", [])
        if open_gates:
            parts.append(f"Tore offen: {', '.join(open_gates)}")

        lights = status.get("lights_on", 0)
        parts.append(f"Lichter an: {lights}")

        parts.append("Maximal 3 Sätze. Deutsch.")
        return "\n".join(parts)

    def _get_notification_system_prompt(
        self, urgency: str = "low", person: str = ""
    ) -> str:
        """Holt den Notification-Prompt aus der PersonalityEngine.

        Nutzt den vollen Personality-Stack (Sarkasmus, Formality, Tageszeit,
        Mood) statt eines statischen Mini-Prompts.
        """
        try:
            return self.brain.personality.build_notification_prompt(
                urgency, person=person
            )
        except Exception as e:
            logger.debug("Personality-Notification-Prompt fehlgeschlagen: %s", e)
            # Fallback auf Minimal-Prompt
            _title = get_person_title(person) if person else get_person_title()
            return (
                f"Du bist {settings.assistant_name} — J.A.R.V.I.S. aus dem MCU. "
                "Proaktive Hausmeldung. 1-2 Sätze. Deutsch. Trocken-britisch. "
                f'Anrede = "{_title}". Nie alarmistisch, nie devot. '
                "VERBOTEN: Hallo, Achtung, Es tut mir leid, Guten Tag."
            )

    # ------------------------------------------------------------------
    # Alert-Personality: Meldungen im Jarvis-Stil reformulieren
    # ------------------------------------------------------------------

    async def format_with_personality(
        self, raw_message: str, urgency: str = "low", person: str = ""
    ) -> str:
        """Reformuliert eine nackte Alert-Meldung im Jarvis-Stil.

        Nutzt das Fast-Model für minimale Latenz.
        Faellt auf raw_message zurück bei Fehler.

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
                    {
                        "role": "system",
                        "content": self._get_notification_system_prompt(
                            urgency, person=person
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"[{urgency.upper()}] Reformuliere im JARVIS-Stil:\n{raw_message}"
                        ),
                    },
                ],
                model=settings.model_notify,
                think=False,
                max_tokens=300,
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
        logger.info("Diagnostics-Loop gestartet")

        while self._running:
            try:
                diag = self.brain.diagnostics
                result = await diag.check_all()

                # Entity-Probleme gruppiert melden (statt 150x einzeln _notify)
                issues_by_type: dict[str, list[dict]] = {}
                for issue in result.get("issues", []):
                    issue_type = issue.get("issue_type", "unknown")
                    event_type = {
                        "offline": "entity_offline",
                        "low_battery": "low_battery",
                        "stale": "stale_sensor",
                    }.get(issue_type, "entity_offline")
                    issues_by_type.setdefault(event_type, []).append(issue)

                for event_type, issues in issues_by_type.items():
                    # Hoechste Severity der Gruppe bestimmt Urgency
                    has_critical = any(i.get("severity") == "critical" for i in issues)
                    has_warning = any(i.get("severity") == "warning" for i in issues)
                    urgency = HIGH if has_critical else MEDIUM if has_warning else LOW

                    # Zusammenfassung: Anzahl + erste Entities als Detail
                    entity_ids = [
                        i.get("entity_id", "") for i in issues if i.get("entity_id")
                    ]
                    preview = ", ".join(entity_ids[:5])
                    if len(entity_ids) > 5:
                        preview += f" (+{len(entity_ids) - 5} weitere)"

                    # Einzelne Entity direkt benennen, bei mehreren Anzahl + Liste
                    if len(entity_ids) == 1:
                        entity_label = entity_ids[0]
                        message = f"Entity offline: {entity_ids[0]}"
                    else:
                        entity_label = f"{len(issues)} Entities"
                        message = f"{len(issues)} Entities: {preview}"

                    await self._notify(
                        event_type,
                        urgency,
                        {
                            "entity": entity_label,
                            "message": message,
                            "count": len(issues),
                            "entities": entity_ids,
                        },
                    )

                # Wartungs-Erinnerungen gruppiert (statt einzeln)
                maintenance_tasks = result.get("maintenance_due", [])
                if maintenance_tasks:
                    task_names = [
                        t.get("name", "") for t in maintenance_tasks if t.get("name")
                    ]
                    preview = ", ".join(task_names[:5])
                    if len(task_names) > 5:
                        preview += f" (+{len(task_names) - 5} weitere)"

                    await self._notify(
                        "maintenance_due",
                        LOW,
                        {
                            "entity": f"{len(maintenance_tasks)}x Wartung",
                            "message": f"{len(maintenance_tasks)} Aufgaben: {preview}",
                            "count": len(maintenance_tasks),
                            "tasks": maintenance_tasks,
                        },
                    )

                # Smart Shopping: Verbrauchsprognose-Check
                if (
                    hasattr(self.brain, "smart_shopping")
                    and self.brain.smart_shopping.enabled
                ):
                    try:
                        self.brain.smart_shopping.set_notify_callback(self._notify)
                        notified = await self.brain.smart_shopping.check_and_notify()
                        if notified:
                            logger.info("Smart Shopping Erinnerungen: %s", notified)
                    except Exception as _ss_err:
                        logger.debug("Smart Shopping Check: %s", _ss_err)

            except Exception as e:
                logger.error("Diagnostik-Check Fehler: %s", e)

            # Warte bis zum nächsten Check
            interval = self.brain.diagnostics.check_interval * 60
            await asyncio.sleep(interval)

    def _build_notification_prompt(
        self, event_type: str, description: str, data: dict, urgency: str
    ) -> str:
        parts = [f"[{urgency.upper()}] {description}"]
        # Person-aware Anrede für alle Templates
        _title = (
            get_person_title(data["person"])
            if data.get("person")
            else get_person_title()
        )

        if "person" in data:
            parts.append(f"Person: {data['person']}")
        if "entity" in data:
            parts.append(f"Entity: {data['entity']}")
        if "status_report" in data:
            status = data["status_report"]
            prompt = self._build_status_report_prompt(status)
            # Phase 7.8: Abwesenheits-Summary anhaengen
            if "absence_summary" in status:
                prompt += f"\n\nWährend der Abwesenheit: {status['absence_summary']}"
                prompt += "\nErwähne kurz was während der Abwesenheit passiert ist."
            return prompt

        # Phase 7.4: Abschied mit Sicherheits-Check (JARVIS-Butler-Stil)
        if data.get("departure_check"):
            person = data.get("person", "User")
            title = self._get_person_title(person)
            parts = [
                f'{person} (Anrede: "{title}") verlaesst gerade das Haus.',
                f"Sprich mit \"{title}\" an. KEIN 'Schoenen Tag!' oder 'Tschuess!'.",
                "Nur relevante Fakten: offene Fenster, unverriegelte Tueren, Alarm-Status.",
                f"Wenn alles gesichert ist: nur knapp bestätigen. 'Alles gesichert, {title}.'",
                "Wenn etwas offen ist: sachlich erwähnen. 'Fenster Küche steht noch offen.'",
            ]
            # Einkaufsliste anhaengen wenn Eintraege vorhanden
            shopping_items = data.get("shopping_items", [])
            if shopping_items:
                count = len(shopping_items)
                if count <= 3:
                    items_str = ", ".join(shopping_items)
                    parts.append(
                        f"Einkaufsliste hat {count} Eintraege: {items_str}. "
                        "Erwaehne beilaeufig. 'Uebrigens, [Artikel] steht noch auf der Liste.'"
                    )
                else:
                    parts.append(
                        f"Einkaufsliste hat {count} Eintraege. "
                        f"Erwaehne beilaeufig die Anzahl. 'Uebrigens, {count} Dinge auf der Einkaufsliste.'"
                    )
            parts.append(
                "Max 2-3 Sätze. Deutsch. Butler der dem Herrn den Mantel reicht, nicht winkt."
            )
            return "\n".join(parts)

        # Nacht-Motion Kamera: Bewegung + Kamera-Beschreibung
        if event_type == "night_motion_camera":
            cam_desc = data.get("camera_description", "")
            return (
                f"Naechtliche Bewegung erkannt ({data.get('entity', 'Aussen')}).\n"
                f"Kamera zeigt: {cam_desc}\n"
                f"Formuliere eine knappe Sicherheitsmeldung im JARVIS-Stil.\n"
                f"Max 2 Sätze. Deutsch. Sachlich. Keine Panik wenn harmlos (Tier, Wind)."
            )

        # Smart Shopping: Verbrauchsprognose-Erinnerung
        if event_type == "shopping_reminder":
            item_name = data.get("item", "")
            msg = data.get("message", "")
            return (
                f"Einkaufs-Erinnerung: {msg}\n"
                "Formuliere beilaeufig, wie eine nebensaechliche Bemerkung.\n"
                f"Beispiel: 'Uebrigens, {_title} — {item_name} koennte bald alle sein.'\n"
                "Max 1 Satz. Deutsch. Butler-Stil. Nicht dringend."
            )

        # Phase 10.1: Musik-Follow Vorschlag
        if event_type == "music_follow":
            from_room = data.get("from_room", "")
            to_room = data.get("to_room", "")
            return (
                f"Musik läuft gerade in {from_room}. Bewegung erkannt in {to_room}.\n"
                f"Frage kurz ob die Musik mitkommen soll.\n"
                f"Beispiel: 'Musik läuft noch in {from_room}. Soll sie mitkommen?'\n"
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
                parts.append(f"Überfaellig seit {days} Tagen.")
            if desc:
                parts.append(f"Info: {desc}")
            parts.append(
                "Formuliere eine sanfte, beiläufige Erinnerung. Nicht dringend."
            )
            parts.append(
                f"Beispiel: 'Nebenbei, {_title}: [Aufgabe] koennte mal erledigt werden.'"
            )
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
                    visitor_context = (
                        f" {rec}" if rec else " Tuer wurde automatisch geoeffnet."
                    )
                elif visitor_info.get("expected"):
                    rec = visitor_info.get("recommendation", "")
                    visitor_context = f" {rec}" if rec else " Erwarteter Besuch."

            if camera_desc:
                return (
                    f"Tuerklingel. Kamera zeigt: {camera_desc}{visitor_context}\n"
                    "Beschreibe kurz wer/was vor der Tuer ist. Max 1-2 Sätze. Butler-Stil.\n"
                    f"Beispiel: 'Paketbote an der Tuer, {_title}. Sieht nach DHL aus.'"
                )
            return (
                f"Tuerklingel.{visitor_context}\n"
                "Melde kurz dass jemand geklingelt hat. Max 1 Satz. Butler-Stil.\n"
                f"Beispiel: 'Jemand an der Tuer, {_title}.'"
            )

        # Phase 17: Sicherheitswarnung (Threat Assessment)
        # WICHTIG: Sachlich melden, NICHT dramatisieren
        if event_type == "threat_detected":
            threat_type = data.get("type", "unbekannt")
            message = data.get("message", "Sicherheitswarnung")
            return (
                f"Sicherheitsmeldung ({threat_type}): {message}\n"
                "Formuliere sachlich, NICHT dramatisch. Max 1-2 Sätze. Butler-Stil.\n"
                "VERBOTEN: 'eingenistet', 'eingeschlichen', 'Eindringling', 'Bedrohung'.\n"
                f"Beispiel: '{_title}, ein unbekanntes Gerät ist im Netzwerk aufgetaucht: [Name].'"
            )

        # Phase 17: Bedingte Aktion ausgeführt
        if event_type == "conditional_executed":
            label = data.get("label", "")
            action = data.get("action", "")
            return (
                f"Bedingte Aktion ausgeführt: {label} -> {action}\n"
                "Formuliere als kurze Info. Max 1 Satz. Butler-Stil.\n"
                "Beispiel: 'Die Rolladen wurden automatisch geschlossen — Regen erkannt.'"
            )

        # Phase 10: Diagnostik-Meldungen — NUR Fakten, KEINE erfundenen Ursachen
        if event_type in ("entity_offline", "low_battery", "stale_sensor"):
            entity = data.get("entity", "")
            message = data.get("message", description)
            return (
                f"Diagnostik: {message}\n"
                f"Entity: {entity}\n"
                "Formuliere EXAKT die Meldung oben um, NICHTS hinzufuegen.\n"
                "Erfinde KEINE Ursachen, Gruende oder Erklaerungen.\n"
                "VERBOTEN: 'aufgrund von', 'wegen', 'vermutlich', 'wahrscheinlich', 'moeglicherweise'.\n"
                f"Beispiel Batterie: '{_title}, Batterie von [Gerät] bei [X]%.'\n"
                f"Beispiel Offline: '{_title}, [Gerät] ist seit [X] Minuten offline.'\n"
                f"Beispiel Stale: '{_title}, [Sensor] hat sich seit [X] Minuten nicht gemeldet.'"
            )

        # Observation: Bereits polierter/generierter Text
        if event_type == "observation" and data.get("message"):
            msg = data["message"]
            return (
                f"Formuliere diese Beobachtung im JARVIS-Butler-Stil um.\n"
                f"Max 2 Saetze. Deutsch. Trocken-britisch.\n"
                f"Wenn ein [INSIDER-KONTEXT] angegeben ist, baue eine beilaeufige "
                f"Rueck-Referenz ein (z.B. 'wie letzten Dienstag', 'das hatten wir schon mal').\n\n"
                f"{msg}"
            )

        parts.append(f"Dringlichkeit: {urgency}")

        # data["message"] als Details einfuegen (generischer Fix)
        if "message" in data:
            parts.append(f"Details: {data['message']}")

        # Wer ist gerade zuhause?
        parts.append(
            "Formuliere eine kurze Meldung. Sprich die Bewohner mit Namen an wenn passend."
        )
        parts.append(
            "Erfinde KEINE Ursachen oder Erklaerungen. NUR die gegebenen Fakten."
        )

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
        logger.info("Batch-Loop gestartet (interval=%ds)", self.batch_interval)
        medium_check_interval = 10 * 60  # 10 Min für MEDIUM
        last_flush = time.monotonic()

        while self._running:
            loop_start = time.monotonic()
            try:
                elapsed = loop_start - last_flush
                # F-033: Lock für shared batch_queue Zugriff
                async with self._state_lock:
                    has_items = bool(self._batch_queue)
                    has_medium = (
                        any(b.get("urgency") == MEDIUM for b in self._batch_queue)
                        if has_items
                        else False
                    )

                if has_items:
                    # MEDIUM sofort flushen wenn Timer abgelaufen
                    if has_medium and elapsed >= medium_check_interval:
                        await self._flush_batch()
                        last_flush = time.monotonic()
                    # LOW flushen nach Standard-Intervall
                    elif elapsed >= self.batch_interval * 60:
                        await self._flush_batch()
                        last_flush = time.monotonic()
            except Exception as e:
                logger.error("Batch-Flush Fehler: %s", e)

            # Drift-kompensiertes Sleep: 60s abzüglich Verarbeitungszeit
            sleep_time = max(0, 60 - (time.monotonic() - loop_start))
            await asyncio.sleep(sleep_time)

    async def _flush_batch(self):
        """Sendet alle gesammelten LOW+MEDIUM-Meldungen als eine Zusammenfassung.

        MEDIUM-Events werden im Batch hoeher priorisiert und zuerst erwähnt.
        F-033: Lock für atomaren batch_queue Zugriff.
        Concurrent-Guard: Verhindert mehrere gleichzeitige Flushes.
        Dedup: Gleiche event_types werden zusammengefasst (letztes Vorkommen behalten).
        """
        # Guard: Nur ein Flush gleichzeitig (verhindert 2 TTS-Nachrichten in 1 Sekunde)
        async with self._batch_flush_lock:
            if self._batch_flushing:
                return
            self._batch_flushing = True
            try:
                await self._flush_batch_inner()
            finally:
                self._batch_flushing = False

    async def _flush_batch_inner(self):
        """Innerer Flush — nimmt ALLE Items aus der Queue (nicht nur max_items)."""
        async with self._state_lock:
            if not self._batch_queue:
                return

            # Quiet Hours VOR Entnahme prüfen (vermeidet unnötige Remove+Re-Insert)
            if self._is_quiet_hours():
                logger.info(
                    "Batch unterdrückt (Quiet Hours, %d Items in Queue)",
                    len(self._batch_queue),
                )
                return

            # Gesamte Queue leeren (atomar unter Lock)
            all_items = list(self._batch_queue)
            self._batch_queue.clear()

        # Dedup: Bei gleichen event_types nur das letzte Vorkommen behalten
        seen = {}
        for item in all_items:
            seen[item.get("event_type", id(item))] = item
        items = list(seen.values())

        # Sortieren: MEDIUM zuerst, dann LOW
        items.sort(key=lambda x: 0 if x.get("urgency") == MEDIUM else 1)

        # Activity-Check: Nicht bei Schlaf/Call (aber MEDIUM weniger streng)
        highest_urgency = (
            MEDIUM if any(b.get("urgency") == MEDIUM for b in items) else LOW
        )
        activity_result = await self.brain.activity.should_deliver(highest_urgency)
        if activity_result["suppress"]:
            trigger_info = activity_result.get("trigger", "")
            if trigger_info:
                logger.info(
                    "Batch unterdrückt: Aktivität=%s, Trigger=%s",
                    activity_result["activity"],
                    trigger_info,
                )
            else:
                logger.info(
                    "Batch unterdrückt: Aktivität=%s", activity_result["activity"]
                )
            # MEDIUM zurück in Queue (sollen nicht verloren gehen)
            # F-033: Lock für atomaren batch_queue Zugriff nach await
            medium_items = [i for i in items if i.get("urgency") == MEDIUM]
            if medium_items:
                async with self._state_lock:
                    self._batch_queue = medium_items + self._batch_queue
            return

        # Zusammenfassung generieren
        medium_parts = []
        low_parts = []
        for item in items:
            data = item.get("data", {})
            entity = data.get("entity", "")
            # Bei gruppierten Issues die Entity-IDs direkt anzeigen
            entities_list = data.get("entities", [])
            if entities_list:
                entity = ", ".join(entities_list[:5])
                if len(entities_list) > 5:
                    entity += f" (+{len(entities_list) - 5} weitere)"
            line = f"- {item['description']}"
            if entity:
                line += f" [{entity}]"
            if "message" in data:
                line += f" ({data['message']})"
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

        # Person-aware Anrede für Batch
        _batch_persons = await self._get_persons_at_home()
        _batch_person = _batch_persons[0] if len(_batch_persons) == 1 else ""
        _batch_title = (
            get_person_title(_batch_person) if _batch_person else get_person_title()
        )
        prompt = (
            f"Fasse diese {len(items)} Meldung(en) in 1-2 Sätzen zusammen. "
            "NUR die gegebenen Fakten nennen. Erfinde KEINE Ursachen oder Gruende. "
            "Keine Metaphern, keine Vergleiche, keine Vermutungen. Wichtiges zuerst.\n\n"
            + "\n".join(summary_parts)
            + f"\n\nBeispiel: '{_batch_title}, der iMac ist seit zwei Stunden offline. "
            f"Der Energie-Sensor meldet seit sieben Stunden keine neuen Werte.'"
        )

        try:
            response = await self.brain.ollama.chat(
                messages=[
                    {
                        "role": "system",
                        "content": self._get_notification_system_prompt(
                            person=_batch_person
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                model=settings.model_notify,
                think=False,
                max_tokens=500,
            )

            text = validate_notification(response.get("message", {}).get("content", ""))
            if text:
                notification_id = f"notif_{uuid.uuid4().hex[:12]}"
                await self._deliver(
                    text,
                    "batch_summary",
                    LOW,
                    notification_id,
                    delivery_method=activity_result.get("delivery", ""),
                    volume=activity_result.get("volume", 0.5),
                )
                await self.brain.feedback.track_notification(
                    notification_id, "batch_summary"
                )
                logger.info(
                    "Batch-Summary gesendet (%d Items, id: %s): %s",
                    len(items),
                    notification_id,
                    text,
                )
                try:
                    event_types = list({i.get("event_type", "") for i in items})
                    await self.brain.ha.log_activity(
                        "proactive",
                        "batch_summary",
                        f"Proaktive Meldung: {text[:150]}",
                        arguments={"items": len(items), "event_types": event_types[:5]},
                    )
                except Exception as e:
                    logger.debug("Aktivitaetslog Batch-Summary fehlgeschlagen: %s", e)

        except Exception as e:
            logger.error("Batch-Summary Fehler: %s", e)

    # ------------------------------------------------------------------
    # Phase 11: Cover-Automation (Sonnenstand, Wetter, Temperatur, Zeitplan)
    #
    # Bugs fixed: 1 (Vacation YAML), 2 (Sensors), 3 (User-Schedules),
    #   4 (Scene triggers), 5 (Night hours), 6 (Markise extend), 7+9 (Vacation dedup)
    # Features: 1 (Window-open), 2 (Manual override), 3 (sun_protection_position),
    #   4 (Cloud aware), 5 (Proportional elevation), 6 (Gradual morning),
    #   7 (Wave open), 8 (Heating), 9 (Room temp), 10 (Hysteresis),
    #   11 (Lux-based), 12 (CO2), 13 (Bed sensor), 14 (Seat sensor),
    #   15 (Presence), 16 (Privacy), 17 (Action log/Dashboard)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Phase 18: Unaufgeforderte Beobachtungen
    # ------------------------------------------------------------------

    async def _run_observation_loop(self):
        """Jarvis bemerkt Muster und teilt Beobachtungen mit.

        Prüft alle 4 Stunden:
        - Wiederholte Widersprueche (Heizung hoch → Fenster auf)
        - Vergessene Routinen (Alarm nicht aktiviert seit 3 Tagen)
        - Effizienz-Tipps (Heizung nachts auf 22 wenn erst um 23 Uhr schlafen)

        Max 1 Beobachtung pro Tag. Delivery via _notify_callback mit LOW Priority.
        """
        obs_cfg = yaml_config.get("observation_loop", {})
        interval_h = obs_cfg.get("interval_hours", 4)
        max_daily = obs_cfg.get("max_daily", 1)

        # Startup-Delay: 10 Minuten warten
        await asyncio.sleep(600)

        while self._running:
            try:
                # FIX-C1: Redis via brain.memory.redis (nicht self._redis)
                _redis = getattr(getattr(self.brain, "memory", None), "redis", None)

                # Cooldown prüfen: max 1 pro Tag
                if _redis:
                    today = datetime.now(_LOCAL_TZ).strftime("%Y-%m-%d")
                    cooldown_key = f"mha:proactive:observation:{today}"
                    count = await _redis.get(cooldown_key)
                    if count and int(count) >= max_daily:
                        await asyncio.sleep(interval_h * 3600)
                        continue

                observation = await self._generate_observation()

                # LLM-Polish: JARVIS-Stil statt Template-Text
                if observation:
                    observation = await self._polish_observation(observation)

                # FIX-C2: Nutze self._notify() statt self._notify_callback
                if observation:
                    await self._notify(
                        "observation",
                        "low",
                        {"message": observation},
                    )
                    # Cooldown setzen
                    if _redis:
                        today = datetime.now(_LOCAL_TZ).strftime("%Y-%m-%d")
                        cooldown_key = f"mha:proactive:observation:{today}"
                        await _redis.incr(cooldown_key)
                        await _redis.expire(cooldown_key, 86400)

            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning("Observation-Loop Fehler: %s", e)

            await asyncio.sleep(interval_h * 3600)

    async def _generate_observation(self) -> Optional[str]:
        """Generiert eine Beobachtung basierend auf Haus-Zustand.

        Returns:
            Beobachtungs-Text oder None
        """
        try:
            states = await self.brain.ha.get_states()
            if not states:
                return None

            title = get_person_title()

            # FIX-C1: Redis via brain.memory.redis
            _redis = getattr(getattr(self.brain, "memory", None), "redis", None)

            # Check 1: Alarm seit 3+ Tagen nicht aktiviert
            if _redis:
                last_alarm = await _redis.get("mha:proactive:last_alarm_armed")
                if last_alarm:
                    try:
                        last_ts = float(last_alarm)
                        days_since = (time.time() - last_ts) / 86400
                        if days_since >= 3:
                            return (
                                f"Mir ist aufgefallen, {title} — der Alarm wurde seit "
                                f"{int(days_since)} Tagen nicht aktiviert. Alles in Ordnung?"
                            )
                    except (ValueError, TypeError):
                        pass

            # Check 2: Heizung läuft nachts auf hoher Temperatur
            hour = datetime.now(_LOCAL_TZ).hour
            if 23 <= hour or hour < 5:
                for s in states:
                    eid = s.get("entity_id", "")
                    if "climate" in eid:
                        temp = s.get("attributes", {}).get("temperature")
                        hvac = s.get("attributes", {}).get("hvac_action", "")
                        if temp and hvac == "heating":
                            try:
                                if float(temp) >= 22:
                                    name = s.get("attributes", {}).get(
                                        "friendly_name", eid
                                    )
                                    return (
                                        f"Nebenbei bemerkt, {title} — die Heizung in {name} "
                                        f"läuft auf {temp}°C. Um diese Uhrzeit vielleicht etwas hoch?"
                                    )
                            except (ValueError, TypeError):
                                pass

            # Check 3: Licht brennt in leerem Raum (kein Motion seit 30+ Min)
            lights_on = {}
            motion_recent = set()
            for s in states:
                eid = s.get("entity_id", "")
                if eid.startswith("light.") and s.get("state") == "on":
                    # Raumnamen extrahieren
                    name = s.get("attributes", {}).get("friendly_name", eid)
                    lights_on[eid] = name
                if eid.startswith("binary_sensor.motion") or eid.startswith(
                    "binary_sensor.bewegung"
                ):
                    if s.get("state") == "on":
                        motion_recent.add(eid.lower())

            if lights_on and not motion_recent:
                # Alle Lichter an, nirgends Bewegung
                light_names = list(lights_on.values())[:3]
                if len(light_names) >= 2:
                    return (
                        f"Kleine Beobachtung, {title} — Licht brennt noch in "
                        f"{', '.join(light_names)}, aber es bewegt sich niemand."
                    )

            # Check 4: Fenster offen + Heizung an (Energie-Verschwendung)
            open_windows = []
            heating_active = False
            for s in states:
                eid = s.get("entity_id", "")
                if eid.startswith("binary_sensor.fenster") or eid.startswith(
                    "binary_sensor.window"
                ):
                    if s.get("state") == "on":
                        open_windows.append(
                            s.get("attributes", {}).get("friendly_name", eid)
                        )
                if "climate" in eid:
                    hvac = s.get("attributes", {}).get("hvac_action", "")
                    if hvac == "heating":
                        heating_active = True

            if open_windows and heating_active:
                windows_str = ", ".join(open_windows[:2])
                return (
                    f"Mir ist aufgefallen, {title} — {windows_str} "
                    f"{'ist' if len(open_windows) == 1 else 'sind'} offen "
                    f"während die Heizung läuft. Das kostet Energie."
                )

            # Check 5: PredictiveMaintenance — Batterie-Warnungen
            if hasattr(self.brain, "predictive_maintenance"):
                try:
                    suggestions = (
                        self.brain.predictive_maintenance.get_maintenance_suggestions()
                    )
                    high_urgency = [
                        s for s in suggestions if s.get("urgency") == "high"
                    ]
                    if high_urgency:
                        first = high_urgency[0]
                        return f"Wartungshinweis, {title} — {first['description']}"
                except Exception as e:
                    logger.warning("Unhandled: %s", e)
            return None
        except Exception as e:
            logger.warning("Observation-Generierung fehlgeschlagen: %s", e)
            return None

    async def _contextualize_threat(self, threat: dict) -> str:
        """Kontextualisiert Bedrohungsmeldungen mit LLM.

        Kombiniert Bedrohungstyp mit Wetter, Uhrzeit und Kontext
        fuer eine sinnvolle Einschaetzung statt generischer Warnung.
        """
        raw_msg = threat.get("message", "")
        if not raw_msg or not getattr(self.brain, "ollama", None):
            return raw_msg
        try:
            # Kontext sammeln: Uhrzeit, Wetter
            from datetime import datetime

            hour = datetime.now(_LOCAL_TZ).hour
            weather_info = ""
            try:
                states = await self.brain.ha.get_states()
                for s in states or []:
                    if s.get("entity_id", "").startswith("weather."):
                        attrs = s.get("attributes", {})
                        weather_info = (
                            f"Wetter: {s.get('state', '?')}, "
                            f"Wind: {attrs.get('wind_speed', '?')} km/h"
                        )
                        break
            except Exception as e:
                logger.debug("Wetterinfo-Abruf fehlgeschlagen: %s", e)

            response = await asyncio.wait_for(
                self.brain.ollama.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Du bist J.A.R.V.I.S., Sicherheits-KI. "
                                "Bewerte diese Bedrohung im Kontext und formuliere "
                                "eine praezise Meldung. Schaetze ein ob es ernst ist "
                                "oder harmlosen Ursprung haben koennte. Max 2 Saetze."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"Bedrohung: {raw_msg}\n"
                                f"Uhrzeit: {hour}:00 Uhr\n"
                                f"{weather_info}\n"
                                f"Typ: {threat.get('type', 'unbekannt')}"
                            ),
                        },
                    ],
                    model=settings.model_fast,
                    think=False,
                    max_tokens=300,
                    tier="fast",
                ),
                timeout=3.0,
            )
            polished = (response.get("message", {}).get("content", "") or "").strip()
            if polished and len(polished) > 15:
                return polished
        except Exception as e:
            logger.debug("Threat-Kontext LLM fehlgeschlagen: %s", e)
        return raw_msg

    async def _polish_auto_action(self, raw_text: str) -> str:
        """Poliert eine Auto-Aktions-Nachricht in JARVIS-Butler-Stil.

        Aus "Willkommen, Sir. Beleuchtung — erledigt." wird
        "Ich habe mir erlaubt, die Beleuchtung einzuschalten, Sir."
        """
        if not raw_text or not getattr(self.brain, "ollama", None):
            return raw_text
        try:
            response = await asyncio.wait_for(
                self.brain.ollama.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": self._get_notification_system_prompt(),
                        },
                        {
                            "role": "user",
                            "content": (
                                "Formuliere diese autonome Aktion um — JARVIS-Butler-Stil. "
                                "Verwende 'Ich habe mir erlaubt...' oder 'Ich habe bereits...'. "
                                "Max 2 Saetze. Behalte die Fakten exakt bei:\n\n"
                                + raw_text
                            ),
                        },
                    ],
                    model=settings.model_notify,
                    think=False,
                    max_tokens=300,
                ),
                timeout=5.0,
            )
            polished = (response.get("message", {}).get("content", "") or "").strip()
            if polished and len(polished) > 10:
                return polished
        except Exception as e:
            logger.debug("Auto-Action-LLM-Polish fehlgeschlagen: %s", e)
        return raw_text

    async def _polish_observation(self, raw_text: str) -> str:
        """Poliert eine Beobachtung mit LLM in JARVIS-Butler-Stil.

        Falls LLM nicht verfuegbar, wird der Rohtext zurueckgegeben.
        """
        if not raw_text or not getattr(self.brain, "ollama", None):
            return raw_text
        try:
            response = await asyncio.wait_for(
                self.brain.ollama.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": self._get_notification_system_prompt(),
                        },
                        {
                            "role": "user",
                            "content": (
                                "Formuliere diese Beobachtung um — kurz, trocken, JARVIS-Butler-Stil. "
                                "Max 2 Saetze. Behalte die Fakten exakt bei, "
                                "aendere nur den Ton (trockener Humor, britischer Butler). "
                                "Wenn ein [INSIDER-KONTEXT] vorhanden ist, baue eine beilaeufige "
                                "Referenz darauf ein — wie ein Butler der sich an fruehere Vorfaelle erinnert.\n\n"
                                + raw_text
                            ),
                        },
                    ],
                    model=settings.model_notify,
                    think=False,
                    max_tokens=300,
                ),
                timeout=5.0,
            )
            polished = (response.get("message", {}).get("content", "") or "").strip()
            if polished and len(polished) > 10:
                return polished
        except Exception as e:
            logger.warning("Observation-LLM-Polish fehlgeschlagen: %s", e)
        return raw_text

    async def _run_seasonal_loop(self):
        """Zentrale Cover-Automatik.

        Prüft alle 15 Minuten:
        1. Wetter-Schutz (hoechste Prio): Sturm → Rolllaeden hoch, Regen → Markisen ein
        2. Sonnenstand-Tracking: Azimut+Elevation → betroffene Fenster abdunkeln
        3. Temperatur-basiert: Hitze → Sonnenschutz, Kaelte nachts → Isolierung
        4. User-Zeitplaene: Aus cover_schedules.json
        5. Zeitplan + Anwesenheit: Morgens hoch, abends runter, Urlaubssimulation
        6. Markisen-Ausfahren bei Sonne
        7. Heizungs-Integration
        8. CO2-Lüftung
        9. Privacy-Modus
        10. Praesenz-basiert (niemand zuhause → zu)
        """
        await asyncio.sleep(PROACTIVE_SEASONAL_STARTUP_DELAY)

        # Redis-Keys für Dedup von automatischen Aktionen
        # Graceful Degradation: Bei Redis-Ausfall wird ohne Redis weitergearbeitet
        _redis = None
        _redis_available = False
        try:
            _redis = getattr(self.brain, "memory", None)
            _redis = getattr(_redis, "redis", None) if _redis else None
            if _redis:
                await _redis.ping()
                _redis_available = True
        except Exception as e:
            logger.warning(
                "Cover-Loop: Redis nicht erreichbar — Safe Mode aktiv (kein Dedup, kein Lock): %s",
                e,
            )
            _redis = None

        # Zeitplan-Dedup: aus Redis laden damit Restart kein Doppel-Trigger ausloest
        _SCHEDULE_KEY = "mha:cover:last_schedule_action"
        _SCHEDULE_DATE_KEY = "mha:cover:last_schedule_date"
        last_action_date = ""
        last_schedule_action = ""
        if _redis:
            try:
                saved_date = await _redis.get(_SCHEDULE_DATE_KEY)
                saved_action = await _redis.get(_SCHEDULE_KEY)
                if saved_date:
                    last_action_date = (
                        saved_date
                        if isinstance(saved_date, str)
                        else saved_date.decode()
                    )
                if saved_action:
                    last_schedule_action = (
                        saved_action
                        if isinstance(saved_action, str)
                        else saved_action.decode()
                    )
                logger.debug(
                    "Cover-Schedule State aus Redis: date=%s action=%s",
                    last_action_date,
                    last_schedule_action,
                )
            except Exception as e:
                logger.warning("Unhandled: %s", e)
        # Fallback bei Redis-Restart: Wenn kein gespeicherter State vorhanden
        # und es ist nach der typischen Morgens-Öffnungszeit, defensiv "open" annehmen
        # um doppelte Morgens-Öffnung zu vermeiden
        if not last_schedule_action and not last_action_date:
            _now = datetime.now(_LOCAL_TZ)
            if _now.hour >= 10:  # Nach 10 Uhr: Morgens-Öffnung war vermutlich schon
                last_schedule_action = "open"
                last_action_date = _now.strftime("%Y-%m-%d")
                logger.info(
                    "Cover-Schedule: Redis leer, nach 10 Uhr → defensiv 'open' angenommen"
                )

        # Startup-Reconciliation: Beim Start prüfen ob Covers im erwarteten Zustand sind
        await self._startup_reconciliation(_redis)

        while self._running:
            try:
                # Graceful Redis Re-Connect: Redis periodisch prüfen
                if not _redis or not _redis_available:
                    try:
                        _redis_candidate = getattr(self.brain, "memory", None)
                        _redis_candidate = (
                            getattr(_redis_candidate, "redis", None)
                            if _redis_candidate
                            else None
                        )
                        if _redis_candidate:
                            await _redis_candidate.ping()
                            _redis = _redis_candidate
                            _redis_available = True
                            logger.info(
                                "Cover-Loop: Redis wieder erreichbar — Safe Mode deaktiviert"
                            )
                    except Exception as e:
                        logger.debug("Redis-Verbindung fehlgeschlagen: %s", e)
                        _redis = None
                        _redis_available = False

                # Config bei jedem Zyklus frisch lesen (Hot-Reload aus UI)
                seasonal_cfg = yaml_config.get("seasonal_actions", {})
                check_interval = seasonal_cfg.get("check_interval_minutes", 15)
                auto_level = seasonal_cfg.get("auto_execute_level", 3)
                cover_cfg = seasonal_cfg.get("cover_automation", {})

                now = datetime.now(_LOCAL_TZ)
                today = now.strftime("%Y-%m-%d")

                if last_action_date != today:
                    last_schedule_action = ""
                    last_action_date = today

                # HA API Timeout-Handling
                try:
                    states = await asyncio.wait_for(
                        self.brain.ha.get_states(),
                        timeout=30.0,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "Cover-Loop: HA API Timeout bei get_states() — Zyklus übersprungen"
                    )
                    await asyncio.sleep(check_interval * 60)
                    continue
                if not states:
                    await asyncio.sleep(check_interval * 60)
                    continue

                sun = self._get_sun_data(states)
                weather = self._get_weather_data(states, cover_cfg)
                # Wetter-Condition in Redis cachen (für Anticipation-Engine)
                if _redis and weather.get("condition"):
                    try:
                        await _redis.set(
                            "mha:weather:current_condition",
                            weather["condition"],
                            ex=300,
                        )
                    except Exception as e:
                        logger.warning("Unhandled: %s", e)
                cover_profiles = self._load_cover_profiles()

                # ── PRIORITÄTSSYSTEM ──────────────────────────────────
                # Set trackt welche Entity-IDs im aktuellen Zyklus bereits
                # von einer höherprioren Regel gesteuert wurden.
                # Niedrigere Regeln überspringen diese Entities.
                _cycle_acted = set()

                # ── GLOBALER SCHLAF-GUARD ──────────────────────────────
                # Wenn Aktivität = sleeping → NUR Wetterschutz (Sturm)
                # ausführen, ALLES andere überspringen.
                # Prüft: 1) Activity-Modul 2) Bettsensor-Fallback
                _sleep_block = await self._is_sleeping(states)
                if _sleep_block:
                    logger.debug("Cover-Loop: Schlafmodus aktiv — nur Wetterschutz")

                # 1. WETTER-SCHUTZ (hoechste Priorität — auch bei Schlaf!)
                if cover_cfg.get("weather_protection", True):
                    await self._cover_weather_protection(
                        states,
                        weather,
                        cover_profiles,
                        cover_cfg,
                        auto_level,
                        _redis,
                        _cycle_acted,
                    )

                if _sleep_block:
                    await asyncio.sleep(check_interval * 60)
                    continue

                # 2. SONNENSTAND-TRACKING (inkl. Bewoelkung, Proportional, Blendschutz)
                if cover_cfg.get("sun_tracking", True) and sun:
                    await self._cover_sun_tracking(
                        states,
                        sun,
                        weather,
                        cover_profiles,
                        cover_cfg,
                        auto_level,
                        _redis,
                        _cycle_acted,
                    )

                # 3. TEMPERATUR-BASIERT (inkl. Hysterese, Raumtemp)
                if cover_cfg.get("temperature_based", True):
                    await self._cover_temperature_logic(
                        states,
                        weather,
                        cover_cfg,
                        cover_profiles,
                        auto_level,
                        _redis,
                        _cycle_acted,
                    )

                # 4. USER-ZEITPLAENE (aus cover_schedules.json)
                await self._cover_user_schedules(
                    states, auto_level, _redis, _cycle_acted
                )

                # 5. ZEITPLAN + ANWESENHEIT (Sonnenstand-basiert + Urlaubssimulation)
                timing = self.brain.context_builder.get_cover_timing(states)
                new_schedule_action = await self._cover_schedule_logic(
                    states,
                    timing,
                    cover_cfg,
                    auto_level,
                    last_schedule_action,
                    _redis,
                    cover_profiles,
                    _cycle_acted,
                )
                if new_schedule_action != last_schedule_action and _redis:
                    try:
                        await _redis.set(_SCHEDULE_KEY, new_schedule_action, ex=86400)
                        await _redis.set(_SCHEDULE_DATE_KEY, today, ex=86400)
                    except Exception as e:
                        logger.warning("Unhandled: %s", e)
                last_schedule_action = new_schedule_action

                # 6. MARKISEN-AUSFAHREN bei Sonne (Bug 6: Dead Config lebendig machen)
                await self._cover_markise_extend(
                    states, sun, weather, cover_cfg, auto_level, _redis, _cycle_acted
                )

                # 7. HEIZUNGS-INTEGRATION (Feature 8)
                if cover_cfg.get("heating_integration", False):
                    await self._cover_heating_integration(
                        states,
                        sun,
                        weather,
                        cover_profiles,
                        cover_cfg,
                        auto_level,
                        _redis,
                        _cycle_acted,
                    )

                # 7b. HEIZUNGS-WETTER-ANPASSUNG
                await self._heating_weather_adjustment(states, sun, weather)

                # 8. CO2-LUEFTUNG (Feature 12)
                if cover_cfg.get("co2_ventilation", False):
                    await self._cover_co2_ventilation(
                        states, weather, auto_level, _redis, _cycle_acted
                    )

                # 9. PRIVACY-MODUS (Feature 16)
                if cover_cfg.get("privacy_mode", False):
                    await self._cover_privacy_mode(
                        states, sun, cover_profiles, auto_level, _redis, _cycle_acted
                    )

                # 10. PRAESENZ-BASIERT (Feature 15)
                if cover_cfg.get("presence_aware", False):
                    await self._cover_presence_logic(
                        states, cover_cfg, auto_level, _redis, _cycle_acted
                    )

                # 11. PROAKTIVE VORSCHLÄGE (Schwellwerte optimieren)
                await self._check_threshold_suggestions(weather, cover_cfg, _redis)

            except Exception as e:
                logger.error("Cover-Automation Fehler: %s", e)

            await asyncio.sleep(check_interval * 60)

    # ── Cover-Automation Hilfsmethoden ──────────────────────

    @staticmethod
    def _get_sun_data(states: list) -> dict:
        """Extrahiert Sonnen-Daten (elevation, azimuth, rising) aus HA states."""
        for s in states or []:
            if s.get("entity_id") == "sun.sun":
                attrs = s.get("attributes", {})
                return {
                    "state": s.get("state", ""),
                    "elevation": attrs.get("elevation", 0),
                    "azimuth": attrs.get("azimuth", 180),
                    "rising": attrs.get("rising", True),
                }
        return {}

    @staticmethod
    def _get_weather_data(states: list, cover_cfg: dict = None) -> dict:
        """Extrahiert Wetter-Daten — nutzt konfigurierte Sensoren wenn vorhanden (Bug 2)."""
        from .cover_config import get_sensor_by_role

        # Defaults aus weather.* Entity (konfigurierbar, Fallback: weather.forecast_home)
        temp, wind, condition, lux, rain = 10.0, 0.0, "", 0.0, False
        forecast = []
        weather_entity = None
        # Konfigurierte Entity bevorzugen
        configured_we = (cover_cfg or {}).get("weather_entity", "") if cover_cfg else ""
        for s in states or []:
            eid = s.get("entity_id", "")
            if configured_we and eid == configured_we:
                weather_entity = s
                break
            if not configured_we and eid == "weather.forecast_home":
                weather_entity = s
                break
            if eid.startswith("weather.") and not weather_entity:
                weather_entity = s
        if weather_entity:
            attrs = weather_entity.get("attributes", {})
            try:
                temp = float(attrs.get("temperature", 10))
            except (ValueError, TypeError):
                pass
            try:
                wind = float(attrs.get("wind_speed", 0))
            except (ValueError, TypeError):
                pass
            condition = weather_entity.get("state", "")
            forecast = attrs.get("forecast", []) or []

        # Bug 2: Konfigurierte Sensoren überschreiben weather.*
        state_map = {s.get("entity_id"): s for s in (states or [])}

        temp_outdoor_eid = get_sensor_by_role("temp_outdoor")
        if temp_outdoor_eid and temp_outdoor_eid in state_map:
            try:
                temp = float(state_map[temp_outdoor_eid].get("state", temp))
            except (ValueError, TypeError):
                pass

        wind_eid = get_sensor_by_role("wind_sensor")
        if wind_eid and wind_eid in state_map:
            try:
                wind = float(state_map[wind_eid].get("state", wind))
            except (ValueError, TypeError):
                pass

        sun_eid = get_sensor_by_role("sun_sensor")
        if sun_eid and sun_eid in state_map:
            try:
                lux = float(state_map[sun_eid].get("state", 0))
            except (ValueError, TypeError):
                pass

        rain_eid = get_sensor_by_role("rain_sensor")
        if rain_eid and rain_eid in state_map:
            rain_state = state_map[rain_eid].get("state", "off")
            rain = rain_state in ("on", "True", "true")

        # Sensor-Plausibilitätsprüfung: unglaubwürdige Werte auf sichere Defaults setzen
        if not (-40 <= temp <= 55):
            logger.warning(
                "Sensor-Plausibilität: Temperatur %s°C außerhalb [-40,55] — ignoriert",
                temp,
            )
            temp = 10.0
        if not (0 <= wind <= 250):
            logger.warning(
                "Sensor-Plausibilität: Wind %s km/h außerhalb [0,250] — ignoriert", wind
            )
            wind = 0.0
        if not (0 <= lux <= 200000):
            logger.warning(
                "Sensor-Plausibilität: Lux %s außerhalb [0,200000] — ignoriert", lux
            )
            lux = 0.0

        # Sensor-Staleness: Warnung wenn Sensor seit >3h nicht aktualisiert
        for _eid, _label in [
            (get_sensor_by_role("wind_sensor"), "Wind"),
            (get_sensor_by_role("temp_outdoor"), "Temperatur"),
        ]:
            if _eid and _eid in state_map:
                _lc = state_map[_eid].get("last_changed", "")
                if _lc:
                    try:
                        from dateutil.parser import isoparse

                        _last = isoparse(_lc)
                        _age_h = (
                            datetime.now(timezone.utc) - _last
                        ).total_seconds() / 3600
                        if _age_h > 3:
                            logger.warning(
                                "Sensor-Staleness: %s (%s) seit %.1fh nicht aktualisiert",
                                _label,
                                _eid,
                                _age_h,
                            )
                    except Exception as e:
                        logger.debug("Sensor-Staleness-Pruefung fehlgeschlagen: %s", e)

        return {
            "temperature": temp,
            "wind_speed": wind,
            "condition": condition,
            "lux": lux,
            "rain": rain,
            "forecast": forecast,
        }

    @staticmethod
    def _get_indoor_temp(states: list, sensor_entity: str) -> float:
        """Liest die Innenraumtemperatur eines spezifischen Sensors (Feature 9)."""
        if not sensor_entity:
            return 0.0
        for s in states or []:
            if s.get("entity_id") == sensor_entity:
                try:
                    return float(s.get("state", 0))
                except (ValueError, TypeError):
                    return 0.0
        return 0.0

    @staticmethod
    def _load_cover_profiles() -> list:
        """Lädt Cover-Profile aus room_profiles.yaml (gecached)."""
        data = _get_room_profiles_cached()
        return data.get("cover_profiles", {}).get("covers", [])

    @staticmethod
    def _get_room_for_cover(entity_id: str) -> str:
        """Raum-Matching über Config: Prüft zuerst cover_profiles, dann Entity-ID Heuristik."""
        # 1. Explizites Mapping aus cover_profiles
        data = _get_room_profiles_cached()
        for cover in data.get("cover_profiles", {}).get("covers", []):
            if cover.get("entity_id") == entity_id:
                room = cover.get("room", "")
                if room:
                    return room.lower()
        # 2. Explizites room_mapping aus Config
        room_mapping = (
            yaml_config.get("seasonal_actions", {})
            .get(
                "cover_automation",
                {},
            )
            .get("room_mapping", {})
        )
        if entity_id in room_mapping:
            return room_mapping[entity_id].lower()
        # 3. Fallback: Heuristik aus Entity-ID
        return entity_id.lower().replace("cover.", "").split("_")[0]

    @staticmethod
    def _is_window_open(states: list, entity_id: str) -> bool:
        """Prüft ob ein zugeordneter Fenster-Sensor offen ist (Feature 1).

        Raum-Matching: Nutzt _get_room_for_cover für zuverlässigeres Matching.
        """
        opening_sensors = yaml_config.get("opening_sensors", {}).get("entities", {})
        cover_room = ProactiveManager._get_room_for_cover(entity_id)
        for sensor_eid, sensor_cfg in (opening_sensors or {}).items():
            sensor_lower = sensor_eid.lower()
            sensor_type = (
                sensor_cfg.get("type", "fenster")
                if isinstance(sensor_cfg, dict)
                else "fenster"
            )
            if sensor_type not in ("fenster", "tuer"):
                continue
            # Prüfe: Sensor enthält Raumnamen ODER explizites Cover-Mapping
            sensor_room = ""
            if isinstance(sensor_cfg, dict):
                sensor_room = sensor_cfg.get("room", "").lower()
            if (cover_room and cover_room in sensor_lower) or (
                sensor_room and sensor_room == cover_room
            ):
                for s in states or []:
                    if s.get("entity_id") == sensor_eid and s.get("state") == "on":
                        return True
        return False

    async def _startup_reconciliation(self, redis_client):
        """Startup-Reconciliation: Prüft ob Covers nach Neustart im erwarteten Zustand sind.

        Liest gespeicherte Reason-States aus Redis und vergleicht mit aktuellen
        Positionen. Loggt Abweichungen und setzt ggf. Covers auf erwartete Position.
        """
        if not redis_client:
            logger.info("Startup-Reconciliation: Übersprungen (kein Redis)")
            return
        try:
            import json as _json

            states = await self.brain.ha.get_states()
            if not states:
                return
            cover_states = [
                s for s in states if s.get("entity_id", "").startswith("cover.")
            ]
            reconciled = 0
            for cs in cover_states:
                eid = cs.get("entity_id")
                reason_raw = await redis_client.get(f"mha:cover:reason:{eid}")
                if not reason_raw:
                    continue
                try:
                    reason_data = _json.loads(
                        reason_raw
                        if isinstance(reason_raw, str)
                        else reason_raw.decode()
                    )
                except Exception as e:
                    logger.debug("Cover-Reason JSON-Parsing fehlgeschlagen: %s", e)
                    continue
                expected_pos = reason_data.get("position")
                if expected_pos is None:
                    continue
                current_pos = cs.get("attributes", {}).get("current_position")
                if current_pos is None:
                    continue
                try:
                    jarvis_pos = self.brain.executor._translate_cover_position_from_ha(
                        eid, int(current_pos)
                    )
                    if abs(jarvis_pos - expected_pos) > 15:
                        logger.info(
                            "Startup-Reconciliation: %s erwartet %d%%, ist %d%% (Grund: %s)",
                            eid,
                            expected_pos,
                            jarvis_pos,
                            reason_data.get("reason", "?"),
                        )
                        reconciled += 1
                except (ValueError, TypeError):
                    pass
            if reconciled > 0:
                logger.info(
                    "Startup-Reconciliation: %d Cover mit Abweichungen gefunden",
                    reconciled,
                )
            else:
                logger.info("Startup-Reconciliation: Alle Cover im erwarteten Zustand")
        except Exception as e:
            logger.warning("Startup-Reconciliation Fehler: %s", e)

    # Rate-Limiting: max Aktionen pro Cover pro Stunde
    _COVER_RATE_LIMIT_MAX = 6
    _COVER_RATE_LIMIT_WINDOW = 3600  # 1 Stunde

    async def _check_cover_rate_limit(self, entity_id: str, redis_client) -> bool:
        """Prüft ob Rate-Limit für dieses Cover erreicht ist (max 6x/h). Returns True wenn blockiert."""
        if not redis_client:
            return False
        try:
            rate_key = f"mha:cover:rate_limit:{entity_id}"
            count = await redis_client.get(rate_key)
            if count and int(count) >= self._COVER_RATE_LIMIT_MAX:
                logger.warning(
                    "Cover Rate-Limit: %s hat %s Aktionen/h erreicht — blockiert",
                    entity_id,
                    count,
                )
                return True
        except Exception as e:
            logger.warning("Unhandled: %s", e)
        return False

    async def _increment_cover_rate(self, entity_id: str, redis_client):
        """Zählt Cover-Aktion hoch für Rate-Limiting."""
        if not redis_client:
            return
        try:
            rate_key = f"mha:cover:rate_limit:{entity_id}"
            pipe = redis_client.pipeline()
            pipe.incr(rate_key)
            pipe.expire(rate_key, self._COVER_RATE_LIMIT_WINDOW)
            await pipe.execute()
        except Exception as e:
            logger.warning("Unhandled: %s", e)

    async def _set_cover_reason(
        self, entity_id: str, position: int, reason: str, redis_client
    ):
        """Speichert den Grund für die aktuelle Cover-Position in Redis."""
        if not redis_client:
            return
        try:
            import json as _json

            reason_data = _json.dumps(
                {
                    "position": position,
                    "reason": reason,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            await redis_client.set(
                f"mha:cover:reason:{entity_id}", reason_data, ex=86400
            )
        except Exception as e:
            logger.warning("Unhandled: %s", e)

    async def get_cover_reason(self, entity_id: str) -> dict:
        """Liest den Grund für die aktuelle Cover-Position (für Debug-Assistent)."""
        try:
            import json as _json

            _redis = (
                self.brain.memory.redis
                if self.brain.memory and hasattr(self.brain.memory, "redis")
                else None
            )
            if not _redis:
                return {}
            data = await _redis.get(f"mha:cover:reason:{entity_id}")
            if data:
                return _json.loads(data if isinstance(data, str) else data.decode())
        except Exception as e:
            logger.warning("Unhandled: %s", e)
        return {}

    async def _schedule_position_verify(
        self, entity_id: str, target_position: int, redis_client
    ):
        """Plant eine Positions-Rückmelde-Prüfung nach 60s."""

        async def _verify():
            await asyncio.sleep(60)
            try:
                states = await self.brain.ha.get_states()
                state = next(
                    (s for s in (states or []) if s.get("entity_id") == entity_id), {}
                )
                current_pos = state.get("attributes", {}).get("current_position")
                if current_pos is not None:
                    jarvis_pos = self.brain.executor._translate_cover_position_from_ha(
                        entity_id,
                        int(current_pos),
                    )
                    if abs(jarvis_pos - target_position) > 10:
                        logger.warning(
                            "Cover Positions-Check: %s sollte bei %d%% sein, ist aber bei %d%%",
                            entity_id,
                            target_position,
                            jarvis_pos,
                        )
                        # Anomalie tracken
                        await self._track_cover_anomaly(entity_id, redis_client)
            except Exception as e:
                logger.debug("Cover Positions-Check Fehler: %s", e)

        self.brain._task_registry.create_task(
            _verify(), name=f"cover_verify_{entity_id}"
        )

    async def _track_cover_anomaly(self, entity_id: str, redis_client):
        """Trackt Anomalien (Ping-Pong-Erkennung): Wenn >4 Anomalien in 2h → Warnung."""
        if not redis_client:
            return
        try:
            anomaly_key = f"mha:cover:anomaly:{entity_id}"
            count = await redis_client.incr(anomaly_key)
            if count == 1:
                await redis_client.expire(anomaly_key, 7200)  # 2h Fenster
            if count >= 4:
                logger.warning(
                    "Cover Anomalie: %s hat %d unerwartete Positionsänderungen in 2h (Ping-Pong?)",
                    entity_id,
                    count,
                )
                await self._notify(
                    "cover_anomaly",
                    MEDIUM,
                    {
                        "message": f"Rollladen {entity_id} zeigt ungewöhnliches Verhalten ({count} Anomalien in 2h) — möglicherweise Ping-Pong",
                        "entity": entity_id,
                    },
                )
                await redis_client.delete(anomaly_key)  # Reset nach Warnung
        except Exception as e:
            logger.warning("Unhandled: %s", e)

    async def _auto_cover_action(
        self,
        entity_id: str,
        position: int,
        reason: str,
        auto_level: int,
        redis_client=None,
        *,
        skip_power_lock: bool = False,
        dedup_ttl: int = 1800,
        dry_run: bool = False,
    ) -> bool:
        """Fuehrt eine automatische Cover-Aktion aus (oder schlaegt vor).

        Checks: Dedup, Manual Override, Power-Close-Lock, Fenster-offen-Schutz,
        Rate-Limiting, Reason-State, Positions-Rückmelde-Check.
        """
        # Dry-Run Modus: Nur loggen, nicht ausführen
        _dry_run = dry_run or yaml_config.get("seasonal_actions", {}).get(
            "cover_automation",
            {},
        ).get("dry_run", False)

        _autonomy = getattr(self.brain, "autonomy", None)
        level = _autonomy.level if _autonomy else 2

        # Rate-Limiting: max 6 Aktionen pro Cover pro Stunde
        if await self._check_cover_rate_limit(entity_id, redis_client):
            return False

        # Power-Close Lock: Wenn Strom-Automatik aktiv, andere Automatiken blockieren
        if not skip_power_lock and redis_client:
            power_lock_key = f"mha:cover:power_close:{entity_id}"
            try:
                power_locked = await redis_client.get(power_lock_key)
                if power_locked:
                    logger.debug(
                        "Cover-Auto: %s übersprungen — Power-Close Lock aktiv",
                        entity_id,
                    )
                    return False
            except Exception as e:
                logger.warning("Unhandled: %s", e)
        # Feature 2: Manual Override Schutz — wenn manuell bedient, nicht antasten
        if redis_client:
            override_key = f"mha:cover:manual_override:{entity_id}"
            override = await redis_client.get(override_key)
            if override:
                logger.info(
                    "Cover-Auto: %s uebersprungen — manueller Override aktiv", entity_id
                )
                return False

        # Dedup per Redis (30 Min Cooldown) — Power-Close überspringt Dedup
        if redis_client and not skip_power_lock:
            dedup_key = f"mha:cover:auto:{entity_id}:{position}"
            already = await redis_client.get(dedup_key)
            if already:
                return False
            await redis_client.set(dedup_key, "1", ex=dedup_ttl)

        if level >= auto_level:
            try:
                # HA API Timeout-Handling: get_states mit Timeout
                try:
                    states = await asyncio.wait_for(
                        self.brain.ha.get_states(),
                        timeout=15.0,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "Cover-Auto: HA API Timeout bei get_states() für %s", entity_id
                    )
                    return False
                state = next(
                    (s for s in (states or []) if s.get("entity_id") == entity_id), {}
                )
                if not await self.brain.executor._is_safe_cover(entity_id, state):
                    return False

                # Feature 1: Fenster-offen-Schutz (nur beim Schliessen)
                if position < 50 and self._is_window_open(states, entity_id):
                    logger.info(
                        "Cover-Auto: %s Schliessen übersprungen — Fenster offen",
                        entity_id,
                    )
                    # Fenster-offen-Benachrichtigung senden
                    await self._notify(
                        "window_open_cover_blocked",
                        LOW,
                        {
                            "message": f"Rollladen {entity_id} nicht geschlossen — Fenster ist offen",
                            "entity": entity_id,
                        },
                    )
                    return False

                # Idempotenz: Nicht bewegen wenn schon am Ziel (±5%)
                current_pos = state.get("attributes", {}).get("current_position")
                if current_pos is not None:
                    try:
                        jarvis_pos = (
                            self.brain.executor._translate_cover_position_from_ha(
                                entity_id,
                                int(current_pos),
                            )
                        )
                        if abs(jarvis_pos - position) <= 5:
                            logger.info(
                                "Cover-Auto: %s bereits bei %d%% (Ziel %d%%) — uebersprungen",
                                entity_id,
                                jarvis_pos,
                                position,
                            )
                            return False
                    except (ValueError, TypeError):
                        pass

                # Dry-Run: Nur loggen, nicht ausführen
                if _dry_run:
                    logger.info(
                        "Cover-Auto [DRY-RUN]: %s -> %d%% (%s)",
                        entity_id,
                        position,
                        reason,
                    )
                    return False

                ha_pos = self.brain.executor._translate_cover_position(
                    entity_id, position
                )
                # Feature 2: Markierung setzen BEVOR HA-Call, damit der State-Change als Jarvis-ausgeloest erkannt wird
                if redis_client:
                    acting_key = f"mha:cover:jarvis_acting:{entity_id}"
                    await redis_client.set(acting_key, "1", ex=300)
                await self.brain.ha.call_service(
                    "cover",
                    "set_cover_position",
                    {"entity_id": entity_id, "position": ha_pos},
                )
                logger.info(
                    "Cover-Auto: %s -> %d%% (HA: %d%%) (%s)",
                    entity_id,
                    position,
                    ha_pos,
                    reason,
                )

                # Rate-Limiting: Zähler erhöhen
                await self._increment_cover_rate(entity_id, redis_client)

                # Reason-State in Redis speichern
                await self._set_cover_reason(entity_id, position, reason, redis_client)

                # Positions-Rückmelde-Check nach 60s
                await self._schedule_position_verify(entity_id, position, redis_client)

                # State-Machine Transition
                cs = self._get_cover_state(entity_id)
                if "sturm" in reason.lower() or "storm" in reason.lower():
                    cs.transition(self.CoverState.STORM_SECURED, reason)
                elif (
                    "sonne" in reason.lower()
                    or "sonnenschutz" in reason.lower()
                    or "blendschutz" in reason.lower()
                ):
                    cs.transition(self.CoverState.SUN_PROTECTED, reason)
                elif "nacht" in reason.lower() or "isolier" in reason.lower():
                    cs.transition(self.CoverState.NIGHT_CLOSED, reason)
                elif "heizung" in reason.lower():
                    cs.transition(self.CoverState.HEATING_INSULATION, reason)
                elif "morgens" in reason.lower() or "oeffnen" in reason.lower():
                    cs.transition(self.CoverState.SCHEDULE_OPEN, reason)
                elif "abends" in reason.lower() or "schliessen" in reason.lower():
                    cs.transition(self.CoverState.SCHEDULE_CLOSED, reason)
                else:
                    new_state = (
                        self.CoverState.SCHEDULE_OPEN
                        if position > 50
                        else self.CoverState.SCHEDULE_CLOSED
                    )
                    cs.transition(new_state, reason)

                # Feature 17: Aktions-Log für Dashboard
                try:
                    from .cover_config import log_cover_action

                    log_cover_action(entity_id, position, reason)
                except Exception as e:
                    logger.warning("Unhandled: %s", e)
                # Activity-Log fuer UI
                try:
                    await self.brain.ha.log_activity(
                        "cover_auto",
                        "set_cover_position",
                        f"Cover {entity_id} -> {position}% ({reason})",
                        arguments={"entity_id": entity_id, "position": position},
                        result=reason,
                    )
                except Exception as e:
                    logger.debug(
                        "Cover-Aktivitaetsprotokollierung fehlgeschlagen: %s", e
                    )
                # Cover-Licht Koordination: LightEngine informieren
                try:
                    if hasattr(self.brain, "light_engine") and self.brain.light_engine:
                        await self.brain.light_engine.on_cover_position_change(
                            entity_id,
                            position,
                            reason,
                        )
                except Exception as le_err:
                    logger.debug("Cover→Licht Callback Fehler: %s", le_err)

                return True
            except Exception as e:
                logger.error("Cover-Auto Fehler für %s: %s", entity_id, e)
                return False
        else:
            desc = "oeffnen" if position > 50 else "schliessen"
            await self._notify(
                "seasonal_cover",
                LOW,
                {
                    "action": desc,
                    "message": f"Rollladen {desc}? ({reason})",
                    "suggestion": True,
                },
            )
            return False

    async def _cover_weather_protection(
        self,
        states,
        weather,
        profiles,
        cover_cfg,
        auto_level,
        redis_client,
        cycle_acted=None,
    ):
        """Sturm → Rolllaeden HOCH. Regen → Markisen EINFAHREN."""
        storm_speed = cover_cfg.get("storm_wind_speed", 50)
        # Feature 10: Hysterese — Storm erst beenden bei storm_speed - hysteresis_wind
        hysteresis_wind = cover_cfg.get("hysteresis_wind", 10)
        wind = weather.get("wind_speed", 0)
        condition = weather.get("condition", "")

        # Sturmschutz mit Hysterese: Aktivieren bei storm_speed, Entwarnung bei storm_speed - hysteresis_wind
        storm_active_key = "mha:cover:storm_active"
        storm_was_active = False
        if redis_client:
            try:
                storm_was_active = bool(await redis_client.get(storm_active_key))
            except Exception as e:
                logger.warning("Unhandled: %s", e)
        if wind >= storm_speed:
            # Sturm aktiv: Covers sichern
            if redis_client:
                try:
                    await redis_client.set(storm_active_key, "1", ex=7200)
                except Exception as e:
                    logger.warning("Unhandled: %s", e)
            notified = False
            for s in states or []:
                eid = s.get("entity_id", "")
                if not eid.startswith("cover."):
                    continue
                if not await self.brain.executor._is_safe_cover(eid, s):
                    continue
                if cycle_acted is not None and eid in cycle_acted:
                    continue
                if self.brain.executor._is_markise(eid, s):
                    storm_pos = 0
                    storm_reason = (
                        f"Sturmschutz: Markise eingefahren (Wind {wind} km/h)"
                    )
                elif s.get("attributes", {}).get("device_class") in (
                    "blind",
                    "shutter",
                ):
                    storm_pos = 0
                    storm_reason = (
                        f"Sturmschutz: Jalousie geschlossen (Wind {wind} km/h)"
                    )
                else:
                    storm_pos = 100
                    storm_reason = (
                        f"Sturmschutz: Rollladen hochgefahren (Wind {wind} km/h)"
                    )
                acted = await self._auto_cover_action(
                    eid,
                    storm_pos,
                    storm_reason,
                    auto_level,
                    redis_client,
                    dedup_ttl=300,
                )
                if acted:
                    if cycle_acted is not None:
                        cycle_acted.add(eid)
                if acted and not notified:
                    await self._notify(
                        "weather_cover_protection",
                        MEDIUM,
                        {
                            "message": f"Sturmwarnung: Covers zum Schutz gesichert (Wind {wind} km/h)",
                        },
                    )
                    notified = True
        elif storm_was_active and wind < (storm_speed - hysteresis_wind):
            # Sturm vorbei (mit Hysterese): Storm-Flag loeschen
            if redis_client:
                try:
                    await redis_client.delete(storm_active_key)
                except Exception as e:
                    logger.warning("Unhandled: %s", e)
            logger.info(
                "Cover-Wetter: Sturmwarnung aufgehoben (Wind %d km/h < %d km/h Schwelle)",
                wind,
                storm_speed - hysteresis_wind,
            )

        # Regen/Hagel: Nur Markisen einfahren
        rp_data = _get_room_profiles_cached()
        markise_cfg = rp_data.get("markisen", {})
        markise_wind = markise_cfg.get("wind_retract_speed", 40)
        rain_retract = markise_cfg.get("rain_retract", True)

        rain_conditions = {"rainy", "pouring", "hail", "lightning-rainy", "lightning"}
        is_raining = condition in rain_conditions or weather.get("rain", False)
        if (rain_retract and is_raining) or wind >= markise_wind:
            for s in states or []:
                eid = s.get("entity_id", "")
                if not eid.startswith("cover."):
                    continue
                if cycle_acted is not None and eid in cycle_acted:
                    continue
                if self.brain.executor._is_markise(eid, s):
                    acted = await self._auto_cover_action(
                        eid,
                        0,
                        f"Markise eingefahren ({condition}, Wind {wind} km/h)",
                        auto_level,
                        redis_client,
                        dedup_ttl=300,
                    )
                    if acted and cycle_acted is not None:
                        cycle_acted.add(eid)

        # Vorhersage-basierter Wetterschutz (weather.forecast_home)
        if cover_cfg.get("forecast_weather_protection", True):
            forecast = weather.get("forecast", [])
            lookahead = cover_cfg.get("forecast_lookahead_hours", 4)
            # Nur die nächsten N Einträge prüfen
            fc_slice = forecast[:lookahead] if forecast else []
            fc_storm = False
            fc_rain = False
            fc_wind_max = 0
            for fc in fc_slice:
                fc_wind = fc.get("wind_speed", 0) or 0
                fc_condition = (fc.get("condition") or "").lower()
                fc_precip = fc.get("precipitation", 0) or 0
                if fc_wind > fc_wind_max:
                    fc_wind_max = fc_wind
                if fc_wind >= storm_speed:
                    fc_storm = True
                if fc_condition in rain_conditions or fc_precip > 2:
                    fc_rain = True

            # Vorhersage: Sturm → Markisen praeventiv einfahren
            if fc_storm and not (wind >= storm_speed):
                notified_fc = False
                for s in states or []:
                    eid = s.get("entity_id", "")
                    if not eid.startswith("cover."):
                        continue
                    if cycle_acted is not None and eid in cycle_acted:
                        continue
                    if self.brain.executor._is_markise(eid, s):
                        acted = await self._auto_cover_action(
                            eid,
                            0,
                            f"Vorhersage: Markise eingefahren (Sturm erwartet, bis {fc_wind_max:.0f} km/h)",
                            auto_level,
                            redis_client,
                            dedup_ttl=300,
                        )
                        if acted and cycle_acted is not None:
                            cycle_acted.add(eid)
                        if acted and not notified_fc:
                            await self._notify(
                                "weather_cover_protection",
                                MEDIUM,
                                {
                                    "message": f"Vorhersage: Sturm erwartet ({fc_wind_max:.0f} km/h) — Markisen praeventiv eingefahren",
                                },
                            )
                            notified_fc = True

            # Vorhersage: Regen → Markisen praeventiv einfahren
            if fc_rain and not is_raining and rain_retract:
                for s in states or []:
                    eid = s.get("entity_id", "")
                    if not eid.startswith("cover."):
                        continue
                    if cycle_acted is not None and eid in cycle_acted:
                        continue
                    if self.brain.executor._is_markise(eid, s):
                        acted = await self._auto_cover_action(
                            eid,
                            0,
                            "Vorhersage: Markise eingefahren (Regen erwartet)",
                            auto_level,
                            redis_client,
                            dedup_ttl=300,
                        )
                        if acted and cycle_acted is not None:
                            cycle_acted.add(eid)

    async def _cover_sun_tracking(
        self,
        states,
        sun,
        weather,
        profiles,
        cover_cfg,
        auto_level,
        redis_client,
        cycle_acted=None,
    ):
        """Azimut-basiert: Betroffene Fenster abdunkeln bei Hitze + Sonne.

        Features: 3 (sun_protection_position), 4 (cloud aware), 5 (proportional),
                  9 (room temp), 13 (bed sensor), 14 (seat/glare protection).
        """
        elevation = sun.get("elevation", 0)
        if elevation <= 0:
            return

        azimuth = sun.get("azimuth", 180)
        temp = weather.get("temperature", 20)
        condition = weather.get("condition", "")
        lux = weather.get("lux", 0)
        heat_temp = cover_cfg.get("heat_protection_temp", 26)
        hysteresis_temp = cover_cfg.get("hysteresis_temp", 2)
        glare_protection = cover_cfg.get("glare_protection", False)

        # Feature 4: Bewoelkung — bei komplett bedeckt kein Sonnenschutz
        cloudy_conditions = {
            "cloudy",
            "fog",
            "rainy",
            "pouring",
            "hail",
            "lightning-rainy",
        }
        is_cloudy = condition in cloudy_conditions

        for cover in profiles:
            entity_id = cover.get("entity_id")
            if not entity_id or not cover.get("allow_auto"):
                continue
            if not cover.get("heat_protection"):
                continue

            start = cover.get("sun_exposure_start", 0)
            end = cover.get("sun_exposure_end", 360)

            # Wraparound für Nordfenster
            if start <= end:
                sun_hitting = start <= azimuth <= end
            else:
                sun_hitting = azimuth >= start or azimuth <= end

            # Feature 9: Raumtemperatur statt nur Aussentemperatur
            indoor_sensor = cover.get("temp_indoor_sensor", "")
            effective_temp = temp
            if indoor_sensor:
                indoor_temp = self._get_indoor_temp(states, indoor_sensor)
                if indoor_temp != 0.0 or any(
                    s.get("entity_id") == indoor_sensor for s in (states or [])
                ):
                    effective_temp = max(temp, indoor_temp)

            # Feature 14: Sitzsensor — Blendschutz unabhängig von Temperatur
            occupancy_sensor = cover.get("occupancy_sensor", "")
            occupied = False
            if occupancy_sensor and glare_protection:
                for s in states or []:
                    if (
                        s.get("entity_id") == occupancy_sensor
                        and s.get("state") == "on"
                    ):
                        occupied = True
                        break

            # Feature 13: Bettsensor — Schlafzimmer nicht oeffnen wenn Bett belegt
            # Zuerst per-cover bed_sensor, dann Fallback auf Raum-bed_sensors
            _bed_sensors = []
            _cover_bs = cover.get("bed_sensor", "")
            if _cover_bs:
                _bed_sensors = [_cover_bs]
            else:
                cover_room = cover.get("room", "")
                if cover_room:
                    _rp = _get_room_profiles_cached()
                    _room_cfg = (_rp.get("rooms") or {}).get(cover_room, {})
                    from .config import get_room_bed_sensors

                    _bed_sensors = get_room_bed_sensors(_room_cfg)
            bed_occupied = False
            for s in states or []:
                if s.get("entity_id") in _bed_sensors and s.get("state") == "on":
                    bed_occupied = True
                    break

            if sun_hitting and not is_cloudy:
                if cycle_acted is not None and entity_id in cycle_acted:
                    continue
                # Feature 11: Lux-basiert — hohe Helligkeit = extra Sonnenschutz-Anlass
                lux_override = lux > 50000

                # Temperatur-Check mit Hysterese (Feature 10)
                needs_sun_protection = (
                    effective_temp >= heat_temp
                    or lux_override
                    or (occupied and sun_hitting)  # Feature 14: Blendschutz
                )

                if needs_sun_protection:
                    # Feature 3+5: Position aus Profil oder proportional zur Elevation
                    base_pos = cover.get("sun_protection_position", 20)
                    # Feature 5: Proportionale Position basierend auf Elevation
                    proportional_pos = max(10, 100 - int(elevation * 1.5))
                    target_pos = min(base_pos, proportional_pos)

                    reason_parts = [f"Sonnenschutz ({effective_temp}°C"]
                    if indoor_sensor and effective_temp > temp:
                        reason_parts.append(f"Raum: {effective_temp}°C")
                    if occupied:
                        reason_parts.append("Blendschutz")
                    if lux_override:
                        reason_parts.append(f"{int(lux)} Lux")
                    reason = ", ".join(reason_parts) + f", Azimut {azimuth}°)"

                    acted = await self._auto_cover_action(
                        entity_id,
                        target_pos,
                        reason,
                        auto_level,
                        redis_client,
                    )
                    if acted:
                        if cycle_acted is not None:
                            cycle_acted.add(entity_id)
                        # Merken, dass wir dieses Cover wegen Sonne geschlossen haben
                        if redis_client:
                            try:
                                await redis_client.set(
                                    f"mha:cover:sun_closed:{entity_id}",
                                    "1",
                                    ex=7200,
                                )
                            except Exception as e:
                                logger.warning("Unhandled: %s", e)
            elif not sun_hitting:
                # Sonne nicht mehr auf Fenster — wieder oeffnen
                # ABER: Nicht oeffnen wenn geschlafen wird (Feature 13)
                if bed_occupied or await self._is_sleeping(states):
                    continue
                if cycle_acted is not None and entity_id in cycle_acted:
                    continue
                if redis_client:
                    sun_closed_key = f"mha:cover:sun_closed:{entity_id}"
                    was_sun_closed = await redis_client.get(sun_closed_key)
                    if was_sun_closed:
                        # Sonne ist weg von Fassade → Sonnenschutz aufheben
                        # (unabhängig von Temperatur — Hysterese nur solange Sonne drauf scheint)
                        acted = await self._auto_cover_action(
                            entity_id,
                            100,
                            f"Sonne vorbei — Rollladen wieder offen (Temp {effective_temp}°C)",
                            auto_level,
                            redis_client,
                        )
                        if acted:
                            if cycle_acted is not None:
                                cycle_acted.add(entity_id)
                            try:
                                await redis_client.delete(sun_closed_key)
                            except Exception as e:
                                logger.warning("Unhandled: %s", e)

    async def _cover_temperature_logic(
        self,
        states,
        weather,
        cover_cfg,
        cover_profiles,
        auto_level,
        redis_client,
        cycle_acted=None,
    ):
        """Kaelte nachts → runter (Isolierung). Mit konfigurierbaren Nacht-Zeiten (Bug 5)."""
        temp = weather.get("temperature", 10)
        hour = datetime.now(_LOCAL_TZ).hour
        frost_temp = cover_cfg.get("frost_protection_temp", 3)
        night_insulation = cover_cfg.get("night_insulation", True)
        # Bug 5: Konfigurierbare Nacht-Stunden
        night_start = cover_cfg.get("night_start_hour", 22)
        night_end = cover_cfg.get("night_end_hour", 6)

        # Nachts + kalt → alle Rolllaeden runter (Isolierung)
        is_night = (
            ((night_start <= hour) or (hour < night_end))
            if night_start > night_end
            else (night_start <= hour < night_end)
        )
        if night_insulation and is_night and temp <= frost_temp:
            for s in states or []:
                eid = s.get("entity_id", "")
                if not eid.startswith("cover."):
                    continue
                if cycle_acted is not None and eid in cycle_acted:
                    continue
                if not await self.brain.executor._is_safe_cover(eid, s):
                    continue
                if self.brain.executor._is_markise(eid, s):
                    continue
                acted = await self._auto_cover_action(
                    eid,
                    0,
                    f"Nacht-Isolierung ({temp}°C aussen)",
                    auto_level,
                    redis_client,
                )
                if acted and cycle_acted is not None:
                    cycle_acted.add(eid)

    async def _cover_user_schedules(
        self, states, auto_level, redis_client, cycle_acted=None
    ):
        """Bug 3: User-Zeitplaene aus cover_schedules.json ausführen."""
        from .cover_config import load_cover_schedules, load_cover_groups, _find_by_id

        schedules = load_cover_schedules()
        if not schedules:
            return

        now = datetime.now(_LOCAL_TZ)
        current_minutes = now.hour * 60 + now.minute
        weekday = now.weekday()  # 0=Mo, 6=So
        tolerance = 10  # +/- 10 Minuten Toleranz (> 15 Min Check-Intervall/2)

        for sched in schedules:
            if not sched.get("is_active", True):
                continue
            days = sched.get("days", [0, 1, 2, 3, 4, 5, 6])
            if weekday not in days:
                continue

            time_str = sched.get("time_str", "08:00")
            try:
                parts = time_str.split(":")
                sched_min = int(parts[0]) * 60 + int(parts[1])
            except (ValueError, IndexError):
                continue

            if abs(current_minutes - sched_min) > tolerance:
                continue

            position = sched.get("position", 100)
            target_entity = sched.get("entity_id")
            target_group = sched.get("group_id")

            # Nicht öffnen wenn Bett belegt (Schlafmodus)
            if position > 0 and await self._is_sleeping(states):
                logger.info(
                    "User-Zeitplan '%s' übersprungen — Schlafmodus aktiv", time_str
                )
                continue

            # Dedup per Redis
            dedup_key = (
                f"mha:cover:usched:{sched.get('id', 0)}:{now.strftime('%Y-%m-%d')}"
            )
            if redis_client:
                already = await redis_client.get(dedup_key)
                if already:
                    continue
                await redis_client.set(dedup_key, "1", ex=86400)

            if target_entity:
                # Einzelnes Cover
                if cycle_acted is not None and target_entity in cycle_acted:
                    continue
                acted = await self._auto_cover_action(
                    target_entity,
                    position,
                    f"Zeitplan '{time_str}' → {position}%",
                    auto_level,
                    redis_client,
                )
                if acted and cycle_acted is not None:
                    cycle_acted.add(target_entity)
            elif target_group:
                # Gruppe
                groups = load_cover_groups()
                group = _find_by_id(groups, target_group)
                if group:
                    for eid in group.get("entity_ids", []):
                        if cycle_acted is not None and eid in cycle_acted:
                            continue
                        acted = await self._auto_cover_action(
                            eid,
                            position,
                            f"Zeitplan '{time_str}' Gruppe '{group.get('name', '')}' → {position}%",
                            auto_level,
                            redis_client,
                        )
                        if acted and cycle_acted is not None:
                            cycle_acted.add(eid)
            else:
                # Alle Cover
                for s in states or []:
                    eid = s.get("entity_id", "")
                    if not eid.startswith("cover."):
                        continue
                    if cycle_acted is not None and eid in cycle_acted:
                        continue
                    if not await self.brain.executor._is_safe_cover(eid, s):
                        continue
                    if self.brain.executor._is_markise(eid, s):
                        continue
                    acted = await self._auto_cover_action(
                        eid,
                        position,
                        f"Zeitplan '{time_str}' → {position}%",
                        auto_level,
                        redis_client,
                    )
                    if acted and cycle_acted is not None:
                        cycle_acted.add(eid)

    async def _cover_schedule_logic(
        self,
        states,
        timing,
        cover_cfg,
        auto_level,
        last_schedule_action,
        redis_client,
        cover_profiles=None,
        cycle_acted=None,
    ) -> str:
        """Morgens hoch (mit Softstart + Welle), abends runter, Urlaubssimulation.

        Bug 1: Urlaubssimulation nutzt jetzt vacation_simulation.* Config.
        Feature 6: Graduelles Oeffnen am Morgen.
        Feature 7: Wellenfoermiges Oeffnen (Ost→Sued→West).
        Feature 13: Bettsensor respektieren.
        """
        now = datetime.now(_LOCAL_TZ)
        current_minutes = now.hour * 60 + now.minute
        open_time = timing.get("open_time", "07:30")
        close_time = timing.get("close_time", "19:00")
        reason = timing.get("reason", "")

        try:
            ot = open_time.split(":")
            open_min = max(0, min(1439, int(ot[0]) * 60 + int(ot[1])))
            ct = close_time.split(":")
            close_min = max(0, min(1439, int(ct[0]) * 60 + int(ct[1])))
        except (ValueError, IndexError):
            open_min, close_min = 450, 1140

        tolerance = (
            20  # Muss > check_interval sein damit kein Zyklus die Aktion verpasst
        )
        gradual = cover_cfg.get("gradual_morning", False)
        wave_open = cover_cfg.get("wave_open", False)

        # Morgens: oeffnen (nur wenn Bett frei + hell genug)
        # Feature 5: Erweitertes Zeitfenster — wenn Sonnencheck blockiert,
        # bleibt das Fenster 2h offen (statt nur 15 Min Toleranz)
        # Globaler Bettsensor-Check: Wenn IRGENDEIN Bettbelegungssensor aktiv ist,
        # Rolladen NICHT öffnen — unabhängig von Cover-Profil-Konfiguration.
        # Verhindert dass Rolladen hochfahren während jemand schläft.
        _is_sleep = await self._is_sleeping(states)
        if _is_sleep:
            logger.info("Cover-Zeitplan: Öffnung übersprungen — Schlafmodus aktiv")
            return last_schedule_action

        fallback_max_min = cover_cfg.get("wakeup_fallback_max_minutes", 120)
        in_open_window = (
            last_schedule_action != "open"
            and current_minutes >= (open_min - tolerance)
            and current_minutes <= (open_min + fallback_max_min)
        )
        if in_open_window:
            # Bedingungen prüfen: Sonnenstand (Bettbelegung wird per-Cover geprueft, Zeile 3302+)
            _skip_reason = None
            _is_fallback = current_minutes > (open_min + tolerance)
            if cover_cfg.get("wakeup_sun_check", True):
                _sun = self._get_sun_data(states)
                _min_elev = cover_cfg.get("wakeup_min_sun_elevation", -6)
                _cur_elev = _sun.get("elevation", 0)
                if _cur_elev < _min_elev:
                    _remaining = open_min + fallback_max_min - current_minutes
                    _skip_reason = (
                        f"zu dunkel (Sonnenhöhe {_cur_elev:.1f}° < {_min_elev}°"
                        f"{f', Fallback in {_remaining} Min' if _remaining > 0 else ', Fallback abgelaufen'})"
                    )
            if _skip_reason:
                logger.info("Cover-Zeitplan: Öffnung übersprungen — %s", _skip_reason)
            else:
                # Feature 7: Wellenfoermiges Oeffnen nach Himmelsrichtung
                covers_to_open = []
                for s in states or []:
                    eid = s.get("entity_id", "")
                    if not eid.startswith("cover."):
                        continue
                    if not await self.brain.executor._is_safe_cover(eid, s):
                        continue
                    if self.brain.executor._is_markise(eid, s):
                        continue
                    # Feature 13: Bettsensor — Schlafzimmer-Cover nicht oeffnen wenn besetzt
                    # Zuerst per-cover bed_sensor, dann Fallback auf Raum-bed_sensors
                    skip = False
                    if cover_profiles:
                        for cp in cover_profiles:
                            if cp.get("entity_id") == eid:
                                _bs_list = []
                                _cp_bs = cp.get("bed_sensor", "")
                                if _cp_bs:
                                    _bs_list = [_cp_bs]
                                elif cp.get("room"):
                                    _rp2 = _get_room_profiles_cached()
                                    _rc = (_rp2.get("rooms") or {}).get(cp["room"], {})
                                    from .config import get_room_bed_sensors

                                    _bs_list = get_room_bed_sensors(_rc)
                                for bs in states or []:
                                    if (
                                        bs.get("entity_id") in _bs_list
                                        and bs.get("state") == "on"
                                    ):
                                        skip = True
                                        break
                    if skip:
                        continue
                    # Azimut für Sortierung
                    azimut = 180
                    if cover_profiles:
                        for cp in cover_profiles:
                            if cp.get("entity_id") == eid:
                                azimut = cp.get("sun_exposure_start", 180)
                                break
                    covers_to_open.append((eid, azimut))

                # Prioritätssystem: Bereits gesteuerte Covers ausschliessen
                if cycle_acted:
                    covers_to_open = [
                        (e, a) for e, a in covers_to_open if e not in cycle_acted
                    ]

                # Feature 7: Nach Azimut sortieren (Ost zuerst)
                if wave_open:
                    covers_to_open.sort(key=lambda x: x[1])

                count = 0
                # Feature 6: Graduelles Oeffnen — als Background-Task damit
                # der Haupt-Loop nicht blockiert wird.  Während der 10 Min
                # graduellem Oeffnen MUSS der Loop weiterlaufen, damit
                # Wetter-Schutz (Sturm, Regen) sofort reagieren kann.
                if gradual and covers_to_open:

                    async def _gradual_open(covers, _reason, _auto_level, _redis):
                        _count = 0
                        for step_pos in (30, 70, 100):
                            for eid, _ in covers:
                                for _attempt in range(2):
                                    try:
                                        acted = await self._auto_cover_action(
                                            eid,
                                            step_pos,
                                            f"Morgens oeffnen Stufe {step_pos}% ({_reason})",
                                            _auto_level,
                                            _redis,
                                        )
                                        if acted:
                                            _count += 1
                                        break
                                    except Exception as e:
                                        logger.debug(
                                            "Benachrichtigungszustellung fehlgeschlagen (Versuch %d): %s",
                                            _attempt,
                                            e,
                                        )
                                        if _attempt == 0:
                                            await asyncio.sleep(60)
                            if step_pos < 100:
                                await asyncio.sleep(300)
                        # Fallback: Sicherstellen dass alle Covers auf 100% sind
                        for eid, _ in covers:
                            try:
                                await self._auto_cover_action(
                                    eid,
                                    100,
                                    f"Morgens oeffnen Fallback ({_reason})",
                                    _auto_level,
                                    _redis,
                                )
                            except Exception as e:
                                logger.warning("Unhandled: %s", e)
                        if _count > 0:
                            await self._notify(
                                "seasonal_cover",
                                LOW,
                                {
                                    "action": "open",
                                    "message": f"Rolllaeden geoeffnet ({_reason})",
                                    "count": _count,
                                },
                            )

                    self.brain._task_registry.create_task(
                        _gradual_open(
                            list(covers_to_open),
                            reason,
                            auto_level,
                            redis_client,
                        ),
                        name="gradual_cover_open",
                    )
                    return "open"
                else:
                    for eid, _ in covers_to_open:
                        acted = await self._auto_cover_action(
                            eid,
                            100,
                            f"Morgens oeffnen ({reason})",
                            auto_level,
                            redis_client,
                        )
                        if acted:
                            count += 1
                            if cycle_acted is not None:
                                cycle_acted.add(eid)
                        # Feature 7: 2 Min Delay zwischen Himmelsrichtungsgruppen
                        if wave_open and count > 0 and count % 3 == 0:
                            await asyncio.sleep(120)

                if count > 0:
                    # Sleep-Lock löschen — Rollläden offen = Person ist wach
                    try:
                        if redis_client:
                            await redis_client.delete(self._SLEEP_LOCK_KEY)
                    except Exception as e:
                        logger.warning("Unhandled: %s", e)
                    await self._notify(
                        "seasonal_cover",
                        LOW,
                        {
                            "action": "open",
                            "message": f"Rollläden geöffnet ({reason})",
                            "count": count,
                        },
                    )
                return "open"

        # Abends: schliessen — per Elevation (wenn konfiguriert) ODER per Zeitplan
        _close_elevation = cover_cfg.get("sunset_close_elevation", None)
        _close_triggered = False
        if _close_elevation is not None and last_schedule_action != "close":
            _sun = self._get_sun_data(states)
            _cur_elev = _sun.get("elevation", 10)
            _rising = _sun.get("rising", True)
            # Nur abends (Sonne sinkt) und Elevation unter Schwellwert
            if not _rising and _cur_elev <= float(_close_elevation):
                _close_triggered = True
                reason = f"Elevation {_cur_elev:.1f}° <= {_close_elevation}°"
        elif _close_elevation is None and last_schedule_action != "close":
            # Zeitplan-Fallback NUR wenn keine Elevation konfiguriert ist
            if abs(current_minutes - close_min) <= tolerance:
                _close_triggered = True

        if last_schedule_action != "close" and _close_triggered:
            count = 0
            for s in states or []:
                eid = s.get("entity_id", "")
                if not eid.startswith("cover."):
                    continue
                if cycle_acted is not None and eid in cycle_acted:
                    continue
                if not await self.brain.executor._is_safe_cover(eid, s):
                    continue
                if self.brain.executor._is_markise(eid, s):
                    continue
                acted = await self._auto_cover_action(
                    eid,
                    0,
                    f"Abends schliessen ({reason})",
                    auto_level,
                    redis_client,
                    dedup_ttl=900,
                )
                if acted:
                    count += 1
                    if cycle_acted is not None:
                        cycle_acted.add(eid)
            if count > 0:
                await self._notify(
                    "seasonal_cover",
                    LOW,
                    {
                        "action": "close",
                        "message": f"Rolllaeden geschlossen ({reason})",
                        "count": count,
                    },
                )
            return "close"

        # Bug 1: Urlaubssimulation nutzt jetzt vacation_simulation.* Config
        if cover_cfg.get("presence_simulation", True):
            vacation_entity = cover_cfg.get("vacation_mode_entity", "")
            if vacation_entity:
                vacation_active = False
                for s in states or []:
                    if s.get("entity_id") == vacation_entity and s.get("state") == "on":
                        vacation_active = True
                        break

                if vacation_active:
                    # Bug 1: Config aus vacation_simulation.* lesen (NICHT hardcoded!)
                    vac_cfg = yaml_config.get("vacation_simulation", {})
                    morning_hour = vac_cfg.get("morning_hour", 7)
                    evening_hour = vac_cfg.get("evening_hour", 18)
                    night_hour = vac_cfg.get("night_hour", 23)
                    variation = vac_cfg.get("variation_minutes", 30)

                    # Variation einmal pro Tag berechnen (in Redis speichern)
                    var_offset = 0
                    if variation > 0 and redis_client:
                        try:
                            stored = await redis_client.get("mha:cover:vac_var_offset")
                            if stored:
                                var_offset = int(
                                    stored
                                    if isinstance(stored, (str, int))
                                    else stored.decode()
                                )
                            else:
                                var_offset = random.randint(-variation, variation)
                                await redis_client.set(
                                    "mha:cover:vac_var_offset",
                                    str(var_offset),
                                    ex=86400,
                                )
                        except Exception as e:
                            logger.debug("Variations-Berechnung fehlgeschlagen: %s", e)
                            var_offset = random.randint(-variation, variation)
                    elif variation > 0:
                        var_offset = random.randint(-variation, variation)
                    morning_min = max(0, morning_hour * 60 + var_offset)
                    evening_min = max(0, evening_hour * 60 + var_offset)
                    night_min = max(0, night_hour * 60 + var_offset)

                    # Morgens oeffnen (mit Variation + Sonnencheck)
                    if abs(current_minutes - morning_min) <= tolerance:
                        _vac_skip = False
                        if cover_cfg.get("wakeup_sun_check", True):
                            _sun = self._get_sun_data(states)
                            _min_elev = cover_cfg.get("wakeup_min_sun_elevation", -6)
                            if _sun.get("elevation", 0) < _min_elev:
                                _vac_skip = True
                                logger.info(
                                    "Urlaubssimulation: Morgens übersprungen — Sonne zu tief (%.1f° < %s°)",
                                    _sun.get("elevation", 0),
                                    _min_elev,
                                )
                        if not _vac_skip:
                            for cs in states or []:
                                eid = cs.get("entity_id", "")
                                if eid.startswith(
                                    "cover."
                                ) and await self.brain.executor._is_safe_cover(eid, cs):
                                    if not self.brain.executor._is_markise(eid, cs):
                                        await self._auto_cover_action(
                                            eid,
                                            100,
                                            "Urlaubssimulation (morgens)",
                                            auto_level,
                                            redis_client,
                                        )
                            last_schedule_action = "open"

                    # Abends teilweise schliessen (mit Variation)
                    elif abs(current_minutes - evening_min) <= tolerance:
                        for cs in states or []:
                            eid = cs.get("entity_id", "")
                            if eid.startswith(
                                "cover."
                            ) and await self.brain.executor._is_safe_cover(eid, cs):
                                if not self.brain.executor._is_markise(eid, cs):
                                    await self._auto_cover_action(
                                        eid,
                                        30,
                                        "Urlaubssimulation (abends, Sichtschutz)",
                                        auto_level,
                                        redis_client,
                                    )
                        last_schedule_action = "close"

                    # Nachts komplett zu
                    elif abs(current_minutes - night_min) <= tolerance:
                        for cs in states or []:
                            eid = cs.get("entity_id", "")
                            if eid.startswith(
                                "cover."
                            ) and await self.brain.executor._is_safe_cover(eid, cs):
                                if not self.brain.executor._is_markise(eid, cs):
                                    await self._auto_cover_action(
                                        eid,
                                        0,
                                        "Urlaubssimulation (Nacht)",
                                        auto_level,
                                        redis_client,
                                    )
                        last_schedule_action = "close"

        return last_schedule_action

    # Bug 6: Markisen-Ausfahren bei Sonne (Dead Config lebendig machen)
    async def _cover_markise_extend(
        self,
        states,
        sun,
        weather,
        cover_cfg,
        auto_level,
        redis_client,
        cycle_acted=None,
    ):
        """Markisen automatisch ausfahren bei Sonne + Waerme + kein Wind/Regen."""
        rp_data = _get_room_profiles_cached()
        markise_cfg = rp_data.get("markisen", {})
        sun_extend_temp = markise_cfg.get("sun_extend_temp", 22)
        markise_wind = markise_cfg.get("wind_retract_speed", 40)

        temp = weather.get("temperature", 10)
        wind = weather.get("wind_speed", 0)
        condition = weather.get("condition", "")
        elevation = sun.get("elevation", 0) if sun else 0
        rain_conditions = {"rainy", "pouring", "hail", "lightning-rainy", "lightning"}
        is_raining = condition in rain_conditions or weather.get("rain", False)

        if (
            temp >= sun_extend_temp
            and elevation > 10
            and wind < markise_wind
            and not is_raining
        ):
            sunny_conditions = {"sunny", "partlycloudy", "windy"}
            if condition in sunny_conditions or condition == "":
                for s in states or []:
                    eid = s.get("entity_id", "")
                    if not eid.startswith("cover."):
                        continue
                    if self.brain.executor._is_markise(eid, s):
                        if cycle_acted is not None and eid in cycle_acted:
                            continue
                        acted = await self._auto_cover_action(
                            eid,
                            100,
                            f"Markise ausgefahren (Sonne, {temp}°C, Wind {wind} km/h)",
                            auto_level,
                            redis_client,
                        )
                        if acted and cycle_acted is not None:
                            cycle_acted.add(eid)

    # Feature 8: Heizungs-Integration
    async def _cover_heating_integration(
        self,
        states,
        sun,
        weather,
        cover_profiles,
        cover_cfg,
        auto_level,
        redis_client,
        cycle_acted=None,
    ):
        """Heizung läuft + kalt → Rolllaeden zu. Sonne scheint + Heizung aus → auf (Solar Gain)."""
        temp = weather.get("temperature", 10)
        condition = weather.get("condition", "")
        azimuth = sun.get("azimuth", 180) if sun else 180
        elevation = sun.get("elevation", 0) if sun else 0

        # Heizungs-Status ermitteln
        heating_active = False
        for s in states or []:
            if s.get("entity_id", "").startswith("climate."):
                hvac_action = s.get("attributes", {}).get("hvac_action", "")
                if hvac_action == "heating":
                    heating_active = True
                    break

        if heating_active and temp < 10:
            # Heizung läuft + kalt: Nicht-sonnenbeschienene Fenster schliessen
            for cover in cover_profiles or []:
                entity_id = cover.get("entity_id")
                if not entity_id or not cover.get("allow_auto"):
                    continue
                start = cover.get("sun_exposure_start", 0)
                end = cover.get("sun_exposure_end", 360)
                if start <= end:
                    sun_on_window = start <= azimuth <= end
                else:
                    sun_on_window = azimuth >= start or azimuth <= end
                # Nachts (elevation <= 0): ALLE Fenster schliessen fuer Waermedaemmung
                # Tags: nur nicht-sonnenbeschienene Fenster schliessen
                should_close = elevation <= 0 or not sun_on_window
                if should_close:
                    if cycle_acted is not None and entity_id in cycle_acted:
                        continue
                    reason = f"Heizungs-Isolierung ({temp}°C, Heizung läuft"
                    if elevation <= 0:
                        reason += ", Nacht"
                    reason += ")"
                    acted = await self._auto_cover_action(
                        entity_id,
                        0,
                        reason,
                        auto_level,
                        redis_client,
                    )
                    if acted and cycle_acted is not None:
                        cycle_acted.add(entity_id)

        elif not heating_active and elevation > 5 and temp < 20:
            # Heizung aus + Sonne: Sonnenbeschienene Fenster öffnen (passive Solarwärme)
            # ABER: Nicht öffnen wenn Bett belegt (jemand schläft)
            if await self._is_sleeping(states):
                logger.info("Passive Solarwärme übersprungen — Schlafmodus aktiv")
                return
            sunny_conditions = {"sunny", "partlycloudy"}
            if condition in sunny_conditions:
                for cover in cover_profiles or []:
                    entity_id = cover.get("entity_id")
                    if not entity_id or not cover.get("allow_auto"):
                        continue
                    start = cover.get("sun_exposure_start", 0)
                    end = cover.get("sun_exposure_end", 360)
                    if start <= end:
                        sun_on_window = start <= azimuth <= end
                    else:
                        sun_on_window = azimuth >= start or azimuth <= end
                    if sun_on_window:
                        if cycle_acted is not None and entity_id in cycle_acted:
                            continue
                        acted = await self._auto_cover_action(
                            entity_id,
                            100,
                            f"Passive Solarwärme ({temp}°C, Sonne auf Fenster)",
                            auto_level,
                            redis_client,
                        )
                        if acted and cycle_acted is not None:
                            cycle_acted.add(entity_id)

    # ── Heizungs-Wetter-Integration ──────────────────────────────
    async def _heating_weather_adjustment(self, states, sun, weather):
        """Passt Heizung an Wetter an: Vorhersage-Vorheizen, Solar-Gain, Wind-Kompensation.

        Nutzt climate.* Entities mit temperature-Attribut. Ändert nur wenn
        heating_weather_adjust in settings aktiviert ist.
        """
        heating_cfg = yaml_config.get("heating", {})
        hw_cfg = heating_cfg.get("weather_adjust", {})
        if not hw_cfg.get("enabled", False):
            return

        redis_client = getattr(getattr(self.brain, "memory", None), "redis", None)
        if not redis_client:
            return

        dedup_key = "mha:heating:weather_adjust"
        last = await redis_client.get(dedup_key)
        if last:
            return  # Nur alle 30 Min
        await redis_client.set(dedup_key, "1", ex=1800)

        temp = weather.get("temperature", 10)
        wind = weather.get("wind_speed", 0)
        condition = weather.get("condition", "")
        elevation = sun.get("elevation", 0) if sun else 0
        forecast = weather.get("forecast", [])

        offset = 0.0  # Temperatur-Offset, der empfohlen wird
        reasons = []

        # 1. Vorhersage-Vorheizen: Kaelteeinbruch in den nächsten Stunden
        lookahead = hw_cfg.get("forecast_lookahead_hours", 4)
        if forecast:
            future_temps = []
            for fc in forecast[:lookahead]:
                try:
                    future_temps.append(float(fc.get("temperature", temp)))
                except (ValueError, TypeError):
                    pass
            if future_temps:
                min_future = min(future_temps)
                drop = temp - min_future
                if drop >= hw_cfg.get("preheat_drop_threshold", 5):
                    # Starker Temperaturabfall vorhergesagt → vorheizen
                    offset += hw_cfg.get("preheat_offset", 1.0)
                    reasons.append(
                        f"Kaelteeinbruch vorhergesagt ({temp:.0f}→{min_future:.0f}°C)"
                    )

        # 2. Solar-Gain: Sonne scheint stark → Heizung reduzieren
        sunny_conditions = {"sunny", "partlycloudy"}
        if condition in sunny_conditions and elevation > 15:
            solar_reduction = hw_cfg.get("solar_gain_reduction", 0.5)
            offset -= solar_reduction
            reasons.append(f"Passive Solarwärme (Sonne {elevation:.0f}°)")

        # 3. Wind-Kompensation: Starker Wind → mehr Waermeverlust
        wind_threshold = hw_cfg.get("wind_compensation_threshold", 30)
        wind_offset = hw_cfg.get("wind_offset", 0.5)
        if wind > wind_threshold:
            offset += wind_offset
            reasons.append(f"Wind-Kompensation ({wind:.0f} km/h)")

        if abs(offset) < 0.3:
            return  # Zu kleiner Effekt

        # Offset anwenden: Heating-Curve-Modus oder Notification
        mode = heating_cfg.get("mode", "room_thermostat")
        if mode == "heating_curve":
            curve_entity = heating_cfg.get("curve_entity", "")
            if curve_entity:
                try:
                    current_offset = 0
                    for s in states or []:
                        if s.get("entity_id") == curve_entity:
                            current_offset = float(
                                s.get("attributes", {}).get("temperature", 0)
                            )
                            break
                    new_offset = round(current_offset + offset, 1)
                    min_off = heating_cfg.get("curve_offset_min", -5)
                    max_off = heating_cfg.get("curve_offset_max", 5)
                    new_offset = max(min_off, min(max_off, new_offset))
                    if abs(new_offset - current_offset) >= 0.3:
                        await self.brain.ha.call_service(
                            "climate",
                            "set_temperature",
                            {"entity_id": curve_entity, "temperature": new_offset},
                        )
                        logger.info(
                            "Heizung Wetter-Anpassung: Offset %+.1f → %+.1f (%s)",
                            current_offset,
                            new_offset,
                            ", ".join(reasons),
                        )
                        try:
                            await self.brain.ha.log_activity(
                                "proactive",
                                "heating_weather_adjust",
                                f"Heizung angepasst: {current_offset:+.1f} → {new_offset:+.1f} ({', '.join(reasons)})",
                                arguments={
                                    "entity_id": curve_entity,
                                    "old_offset": current_offset,
                                    "new_offset": new_offset,
                                },
                            )
                        except Exception as e:
                            logger.debug(
                                "Heizungs-Aktivitaetsprotokollierung fehlgeschlagen: %s",
                                e,
                            )
                except Exception as e:
                    logger.warning("Heizungs-Wetter-Anpassung fehlgeschlagen: %s", e)
        else:
            # Room thermostat: Nur informieren, nicht direkt ändern
            reason_text = ", ".join(reasons)
            logger.info(
                "Heizung Wetter-Hinweis: Offset %+.1f empfohlen (%s)",
                offset,
                reason_text,
            )
            await self._notify(
                "heating_weather_adjust",
                LOW,
                {
                    "message": f"Heizungs-Empfehlung ({reason_text}): Temperatur {'+' if offset > 0 else ''}{offset:.1f}°C anpassen.",
                },
            )

    # Feature 12: CO2-Lüftungsunterstuetzung
    async def _cover_co2_ventilation(
        self, states, weather, auto_level, redis_client, cycle_acted=None
    ):
        """Hoher CO2 + gutes Wetter → Rolllaeden auf + Benachrichtigung."""
        temp = weather.get("temperature", 10)
        condition = weather.get("condition", "")
        rain_conditions = {"rainy", "pouring", "hail", "lightning-rainy", "lightning"}
        is_raining = condition in rain_conditions or weather.get("rain", False)

        if is_raining or temp < 10 or temp > 25:
            return

        high_co2_rooms = []
        for s in states or []:
            eid = s.get("entity_id", "")
            if not eid.startswith("sensor."):
                continue
            dc = s.get("attributes", {}).get("device_class", "")
            if dc != "carbon_dioxide":
                continue
            try:
                co2 = float(s.get("state", 0))
            except (ValueError, TypeError):
                continue
            if co2 > 1000:
                # Raum aus Sensor-Entity extrahieren
                room = eid.replace("sensor.", "").split("_")[0]
                high_co2_rooms.append((room, co2))

        if high_co2_rooms:
            # Nicht öffnen wenn Bett belegt (Schlafmodus)
            if await self._is_sleeping(states):
                logger.info(
                    "CO2-Lüftung übersprungen — Schlafmodus aktiv (%s)",
                    ", ".join(f"{r}: {int(c)} ppm" for r, c in high_co2_rooms),
                )
                return
            # Covers in betroffenen Räumen öffnen
            for s in states or []:
                eid = s.get("entity_id", "")
                if not eid.startswith("cover."):
                    continue
                if not await self.brain.executor._is_safe_cover(eid, s):
                    continue
                if cycle_acted is not None and eid in cycle_acted:
                    continue
                cover_room = eid.replace("cover.", "").split("_")[0]
                for room, co2 in high_co2_rooms:
                    if room and room in cover_room:
                        acted = await self._auto_cover_action(
                            eid,
                            100,
                            f"CO2-Lüftung: {int(co2)} ppm im Raum",
                            auto_level,
                            redis_client,
                        )
                        if acted and cycle_acted is not None:
                            cycle_acted.add(eid)
                        break
            await self._notify(
                "co2_ventilation",
                LOW,
                {
                    "message": f"CO2 hoch ({int(high_co2_rooms[0][1])} ppm) — Rolllaeden geoeffnet + bitte lüften!",
                },
            )
            try:
                rooms_info = [(r, int(v)) for r, v in high_co2_rooms[:3]]
                await self.brain.ha.log_activity(
                    "proactive",
                    "co2_ventilation",
                    f"CO2-Lueftung: {int(high_co2_rooms[0][1])} ppm — Rolllaeden geoeffnet",
                    arguments={"rooms": rooms_info},
                )
            except Exception as e:
                logger.debug(
                    "CO2-Lueftungs-Aktivitaetsprotokollierung fehlgeschlagen: %s", e
                )

    # Feature 16: Privacy-Modus (Abendlicher Sichtschutz)
    async def _cover_privacy_mode(
        self, states, sun, cover_profiles, auto_level, redis_client, cycle_acted=None
    ):
        """Abends + Licht an → strassenseitige Rolllaeden schliessen.

        Berücksichtigt per-Cover privacy_close_hour (ab wann aktiviert wird)
        und globalen privacy_close_hour als Fallback.
        """
        from datetime import datetime as _dt

        elevation = sun.get("elevation", 0) if sun else 0
        if elevation > 0:
            return  # Nur nach Sonnenuntergang

        current_hour = _dt.now(timezone.utc).hour
        cover_cfg = yaml_config.get("seasonal_actions", {}).get("cover_automation", {})
        global_close_hour = cover_cfg.get("privacy_close_hour", None)

        for cover in cover_profiles or []:
            if not cover.get("privacy_mode"):
                continue
            entity_id = cover.get("entity_id")
            if not entity_id:
                continue

            # Per-Cover privacy_close_hour > globaler Wert
            close_hour = cover.get("privacy_close_hour") or global_close_hour
            if close_hour is not None:
                try:
                    close_hour = int(close_hour)
                    if current_hour < close_hour:
                        continue  # Noch nicht Zeit für Privacy
                except (ValueError, TypeError):
                    pass

            # Prüfen ob im Raum Licht an ist
            cover_room = entity_id.replace("cover.", "").split("_")[0]
            light_on = False
            for s in states or []:
                lid = s.get("entity_id", "")
                if (
                    lid.startswith("light.")
                    and cover_room in lid.lower()
                    and s.get("state") == "on"
                ):
                    light_on = True
                    break

            if light_on:
                if cycle_acted is not None and entity_id in cycle_acted:
                    continue
                acted = await self._auto_cover_action(
                    entity_id,
                    0,
                    "Privacy-Modus (Licht an + dunkel draussen)",
                    auto_level,
                    redis_client,
                )
                if acted and cycle_acted is not None:
                    cycle_acted.add(entity_id)

    # Feature 15: Praesenz-basierte Cover-Steuerung
    async def _cover_presence_logic(
        self, states, cover_cfg, auto_level, redis_client, cycle_acted=None
    ):
        """Niemand zuhause → alle zu. Person betritt Raum → auf."""
        # Nicht wenn Urlaubssimulation aktiv (die steuert Covers eigenstaendig)
        vacation_entity = cover_cfg.get("vacation_mode_entity", "")
        if vacation_entity:
            for s in states or []:
                if s.get("entity_id") == vacation_entity and s.get("state") == "on":
                    return

        anyone_home = False
        for s in states or []:
            if (
                s.get("entity_id", "").startswith("person.")
                and s.get("state") == "home"
            ):
                anyone_home = True
                break

        if not anyone_home:
            for s in states or []:
                eid = s.get("entity_id", "")
                if not eid.startswith("cover."):
                    continue
                if not await self.brain.executor._is_safe_cover(eid, s):
                    continue
                if self.brain.executor._is_markise(eid, s):
                    continue
                if cycle_acted is not None and eid in cycle_acted:
                    continue
                acted = await self._auto_cover_action(
                    eid,
                    0,
                    "Niemand zuhause — Einbruchschutz",
                    auto_level,
                    redis_client,
                )
                if acted and cycle_acted is not None:
                    cycle_acted.add(eid)

    async def _execute_seasonal_cover(
        self,
        action: str,
        position: int,
        season: str,
        reason: str,
        auto_level: int,
    ):
        """Kompatibilitaets-Wrapper für alte Aufrufe (z.B. aus routine_engine)."""
        _redis = getattr(getattr(self.brain, "memory", None), "redis", None)
        states = await self.brain.ha.get_states()
        for s in states or []:
            eid = s.get("entity_id", "")
            if eid.startswith("cover."):
                if not await self.brain.executor._is_safe_cover(eid, s):
                    continue
                await self._auto_cover_action(eid, position, reason, auto_level, _redis)

    # ── Phase 11: Saugroboter-Automatik ────────────────────

    async def _is_anyone_home(self) -> bool:
        """Prüft ob mindestens eine Person zuhause ist (person.* == 'home')."""
        states = await self.brain.ha.get_states()
        for s in states or []:
            if (
                s.get("entity_id", "").startswith("person.")
                and s.get("state") == "home"
            ):
                return True
        return False

    async def _vacuum_alarm_switch(self, mode: str) -> bool:
        """Schaltet die Alarmanlage für den Saugroboter um.

        Args:
            mode: 'arm_home' (Vacuum startet) oder 'arm_away' (Vacuum fertig)
        Returns:
            True wenn erfolgreich oder keine Alarmanlage konfiguriert
        """
        import assistant.config as cfg

        guard_cfg = cfg.yaml_config.get("vacuum", {}).get("presence_guard", {})
        if not guard_cfg.get("switch_alarm_for_cleaning"):
            return True

        alarm_entity = guard_cfg.get("alarm_entity", "")
        if not alarm_entity:
            # Automatisch erste Alarmanlage finden
            try:
                states = await self.brain.ha.get_states()
                for s in states or []:
                    if s.get("entity_id", "").startswith("alarm_control_panel."):
                        alarm_entity = s["entity_id"]
                        break
            except Exception as e:
                logger.error("Vacuum-Alarm: Alarmanlage suchen fehlgeschlagen: %s", e)
                return False
        if not alarm_entity:
            return True  # Keine Alarmanlage vorhanden

        # Aktuellen Alarm-Status prüfen
        try:
            state = await self.brain.ha.get_state(alarm_entity)
        except Exception as e:
            logger.error(
                "Vacuum-Alarm: Status von %s nicht abrufbar: %s", alarm_entity, e
            )
            return False
        current = state.get("state", "") if state else ""

        service_map = {
            "arm_home": "alarm_arm_home",
            "arm_away": "alarm_arm_away",
        }
        service = service_map.get(mode)
        if not service:
            return False

        # Redis-Client holen (einmal, statt doppelt)
        _memory = getattr(self.brain, "memory", None)
        _redis = getattr(_memory, "redis", None) if _memory else None

        # Nur umschalten wenn noetig
        # armed_away UND armed_night benoetigen Umschaltung auf arm_home
        if mode == "arm_home" and current in ("armed_away", "armed_night"):
            logger.info(
                "Vacuum-Alarm: %s (%s) → arm_home (Saugroboter startet)",
                alarm_entity,
                current,
            )
            try:
                success = await self.brain.ha.call_service(
                    "alarm_control_panel", service, {"entity_id": alarm_entity}
                )
            except Exception as e:
                logger.error(
                    "Vacuum-Alarm: arm_home Service-Aufruf fehlgeschlagen: %s", e
                )
                return False
            if success:
                # Merken dass wir den Alarm umgeschaltet haben + vorherigen Zustand
                if _redis:
                    try:
                        await _redis.set("mha:vacuum:alarm_switched", current, ex=7200)
                    except Exception as e:
                        logger.warning(
                            "Vacuum-Alarm: Redis-Flag setzen fehlgeschlagen: %s", e
                        )
            else:
                logger.error(
                    "Vacuum-Alarm: Umschalten auf arm_home fehlgeschlagen fuer %s",
                    alarm_entity,
                )
            return success
        elif mode == "arm_away" and current == "armed_home":
            # Nur zurueckschalten wenn WIR den Alarm umgeschaltet haben
            previous_state = None
            if _redis:
                try:
                    was_switched = await _redis.get("mha:vacuum:alarm_switched")
                    if not was_switched:
                        return True  # Wir haben nicht umgeschaltet → nichts tun
                    # Vorherigen Zustand auslesen (armed_away oder armed_night)
                    previous_state = (
                        was_switched
                        if isinstance(was_switched, str)
                        else was_switched.decode()
                    )
                    await _redis.delete("mha:vacuum:alarm_switched")
                except Exception as e:
                    logger.warning(
                        "Vacuum-Alarm: Redis-Flag lesen/loeschen fehlgeschlagen: %s — schalte trotzdem zurueck",
                        e,
                    )
            else:
                logger.warning(
                    "Vacuum-Alarm: Redis nicht verfuegbar — schalte trotzdem zurueck"
                )

            # Zum vorherigen Zustand zurueckschalten (armed_away oder armed_night)
            restore_service = "alarm_arm_away"
            if previous_state == "armed_night":
                restore_service = "alarm_arm_night"
            logger.info(
                "Vacuum-Alarm: %s → %s (Reinigung beendet)",
                alarm_entity,
                restore_service,
            )
            try:
                success = await self.brain.ha.call_service(
                    "alarm_control_panel", restore_service, {"entity_id": alarm_entity}
                )
                if not success:
                    logger.error(
                        "Vacuum-Alarm: Zurueckschalten auf %s fehlgeschlagen fuer %s",
                        restore_service,
                        alarm_entity,
                    )
                return success
            except Exception as e:
                logger.error(
                    "Vacuum-Alarm: Service-Aufruf %s fehlgeschlagen: %s",
                    restore_service,
                    e,
                )
                return False
        return True  # Kein Umschalten noetig

    async def _vacuum_can_start(self) -> tuple[bool, str]:
        """Prüft ob der Vacuum starten darf (Anwesenheits-Guard).

        Returns:
            (darf_starten: bool, grund: str)
        """
        import assistant.config as cfg

        guard_cfg = cfg.yaml_config.get("vacuum", {}).get("presence_guard", {})
        if not guard_cfg.get("enabled"):
            return True, ""

        if await self._is_anyone_home():
            return False, "Jemand ist zuhause"
        return True, ""

    _FAN_SPEED_MAP = {
        "quiet": "quiet",
        "standard": "standard",
        "strong": "strong",
        "turbo": "turbo",
    }
    _CLEAN_MODE_MAP = {
        "vacuum": "sweeping",
        "mop": "mopping",
        "vacuum_and_mop": "sweeping_and_mopping",
    }

    async def _prepare_vacuum(
        self, entity_id: str, fan_speed: str = "", mode: str = ""
    ) -> None:
        """Setzt Saugstaerke und Reinigungsmodus vor dem Start."""
        if fan_speed:
            resolved = self._FAN_SPEED_MAP.get(fan_speed, fan_speed)
            await self.brain.ha.call_service(
                "vacuum",
                "set_fan_speed",
                {
                    "entity_id": entity_id,
                    "fan_speed": resolved,
                },
            )
        if mode:
            resolved = self._CLEAN_MODE_MAP.get(mode, mode)
            base = entity_id.replace("vacuum.", "")
            await self.brain.ha.call_service(
                "select",
                "select_option",
                {
                    "entity_id": f"select.{base}_cleaning_mode",
                    "option": resolved,
                },
            )

    async def _vacuum_start_with_alarm(
        self,
        entity_id: str,
        nickname: str,
        reason: str,
        fan_speed: str = "",
        mode: str = "",
    ) -> bool:
        """Startet einen Vacuum mit Alarm-Management.

        1. Prüft Anwesenheit
        2. Schaltet Alarm von abwesend → anwesend
        3. Setzt Saugstaerke/Modus
        4. Startet den Vacuum
        """
        can_start, block_reason = await self._vacuum_can_start()
        if not can_start:
            logger.info("Vacuum-Guard: %s blockiert — %s", nickname, block_reason)
            return False

        # Alarm umschalten BEVOR Vacuum startet
        alarm_ok = await self._vacuum_alarm_switch("arm_home")
        if not alarm_ok:
            logger.error(
                "Vacuum: Alarm konnte nicht umgeschaltet werden — %s wird NICHT gestartet",
                nickname,
            )
            return False

        # Saugstaerke und Modus setzen
        if fan_speed or mode:
            await self._prepare_vacuum(entity_id, fan_speed, mode)

        success = await self.brain.ha.call_service(
            "vacuum", "start", {"entity_id": entity_id}
        )
        if success:
            logger.info(
                "Vacuum: %s gestartet (%s) — Alarm auf arm_home", nickname, reason
            )
            try:
                await self.brain.ha.log_activity(
                    "vacuum_auto",
                    "vacuum_start",
                    f"Staubsauger {nickname} gestartet ({reason})",
                    arguments={
                        "entity_id": entity_id,
                        "fan_speed": fan_speed,
                        "mode": mode,
                    },
                    result=reason,
                )
            except Exception as e:
                logger.debug(
                    "Staubsauger-Aktivitaetsprotokollierung fehlgeschlagen: %s", e
                )
        else:
            # Alarm zurückschalten wenn Start fehlgeschlagen
            await self._vacuum_alarm_switch("arm_away")
        return success

    async def _run_vacuum_presence_monitor(self):
        """Überwacht Anwesenheit während Vacuum-Reinigung.

        - Wenn jemand nachhause kommt → alle Vacuums pausieren + zur Ladestation
        - Wenn wieder alle weg sind → unterbrochene Reinigung fortsetzen
        - Alarm-Management: Zurückschalten wenn Reinigung beendet
        """
        await asyncio.sleep(PROACTIVE_SEASONAL_STARTUP_DELAY + 180)

        _redis = getattr(self.brain, "memory", None)
        _redis = getattr(_redis, "redis", None) if _redis else None

        _interrupted_local = None  # In-Memory Fallback wenn Redis nicht verfügbar

        logger.info("Vacuum-PresenceMonitor: Task gestartet")

        while self._running:
            try:
                import assistant.config as cfg

                vacuum_cfg = cfg.yaml_config.get("vacuum", {})
                guard_cfg = vacuum_cfg.get("presence_guard", {})
                robots = vacuum_cfg.get("robots", {})

                if not guard_cfg.get("enabled"):
                    await asyncio.sleep(60)
                    continue

                anyone_home = await self._is_anyone_home()
                states = await self.brain.ha.get_states()

                # Welche Vacuums saugen gerade?
                cleaning_robots = []
                all_docked = True
                for floor, robot in robots.items():
                    eid = robot.get("entity_id")
                    if not eid:
                        continue
                    entity_found = False
                    for s in states or []:
                        if s.get("entity_id") == eid:
                            entity_found = True
                            vac_state = s.get("state", "")
                            if vac_state == "cleaning":
                                cleaning_robots.append((floor, eid, robot))
                                all_docked = False
                            elif vac_state == "returning":
                                # Auf dem Weg zur Ladestation — noch nicht fertig
                                all_docked = False
                            elif vac_state == "paused":
                                # Pausiert (manuell oder automatisch) — nicht fertig
                                all_docked = False
                            elif vac_state == "unavailable":
                                # Offline — nicht als docked werten (Sicherheit)
                                all_docked = False
                                logger.warning(
                                    "Vacuum-PresenceMonitor: %s ist unavailable", eid
                                )
                            elif vac_state not in ("docked", "idle"):
                                # Unbekannter Zustand (error etc.) — nicht als docked werten
                                all_docked = False
                            break
                    if not entity_found:
                        # Entity nicht in HA-States — nicht als docked werten
                        all_docked = False
                        logger.warning(
                            "Vacuum-PresenceMonitor: %s nicht in HA-States gefunden",
                            eid,
                        )

                # Fall 1: Jemand kommt heim + Vacuum saugt → Pausieren + Dock
                # Guard: Nur wenn nicht schon pausiert (verhindert doppelte Befehle)
                if _redis:
                    already_interrupted = await _redis.get("mha:vacuum:interrupted")
                else:
                    already_interrupted = _interrupted_local
                if (
                    anyone_home
                    and cleaning_robots
                    and guard_cfg.get("pause_on_arrival")
                    and not already_interrupted
                ):
                    logger.info(
                        "Vacuum-PresenceMonitor: Jemand ist zuhause — %d Roboter pausieren",
                        len(cleaning_robots),
                    )
                    interrupted = []
                    for floor, eid, robot in cleaning_robots:
                        await self.brain.ha.call_service(
                            "vacuum", "pause", {"entity_id": eid}
                        )
                        await asyncio.sleep(2)
                        await self.brain.ha.call_service(
                            "vacuum", "return_to_base", {"entity_id": eid}
                        )
                        interrupted.append(floor)
                        nickname = robot.get("nickname", f"Saugroboter {floor.upper()}")
                        logger.info(
                            "Vacuum-PresenceMonitor: %s pausiert + zur Ladestation",
                            nickname,
                        )

                    # Unterbrochene Robots in Redis + lokal merken
                    if interrupted:
                        _interrupted_local = ",".join(interrupted)
                        if _redis:
                            await _redis.set(
                                "mha:vacuum:interrupted",
                                _interrupted_local,
                                ex=14400,  # 4 Stunden TTL
                            )
                    await self._notify(
                        "vacuum_paused_arrival",
                        LOW,
                        {
                            "message": "Saugroboter pausiert — jemand ist nachhause gekommen",
                        },
                    )
                    try:
                        await self.brain.ha.log_activity(
                            "vacuum_auto",
                            "vacuum_paused",
                            f"Staubsauger pausiert — Ankunft erkannt ({len(interrupted)} Roboter)",
                            arguments={"interrupted_floors": interrupted},
                        )
                    except Exception as e:
                        logger.debug(
                            "Staubsauger-Pause-Protokollierung fehlgeschlagen: %s", e
                        )

                # Fall 2: Niemand zuhause + unterbrochene Reinigung → Fortsetzen
                if not anyone_home and guard_cfg.get("resume_on_departure"):
                    interrupted_str = (
                        (await _redis.get("mha:vacuum:interrupted"))
                        if _redis
                        else _interrupted_local
                    )
                    if isinstance(interrupted_str, bytes):
                        interrupted_str = interrupted_str.decode()
                    if interrupted_str:
                        delay = guard_cfg.get("resume_delay_minutes", 5)
                        logger.info(
                            "Vacuum-PresenceMonitor: Alle weg — warte %d Min bevor Reinigung fortgesetzt wird",
                            delay,
                        )
                        await asyncio.sleep(delay * 60)

                        # Nochmal prüfen ob wirklich alle weg sind
                        if await self._is_anyone_home():
                            logger.info(
                                "Vacuum-PresenceMonitor: Doch noch jemand da — Fortsetzung abgebrochen"
                            )
                            await asyncio.sleep(30)
                            continue

                        floors = interrupted_str.split(",")

                        # Alarm umschalten
                        await self._vacuum_alarm_switch("arm_home")

                        # Erst alle Robots starten, DANN interrupted-State loeschen
                        resumed_floors = []
                        for floor in floors:
                            robot = robots.get(floor)
                            if not robot:
                                continue
                            eid = robot.get("entity_id")
                            if not eid:
                                continue
                            nickname = robot.get(
                                "nickname", f"Saugroboter {floor.upper()}"
                            )
                            success = await self.brain.ha.call_service(
                                "vacuum", "start", {"entity_id": eid}
                            )
                            if success:
                                resumed_floors.append(floor)
                                logger.info(
                                    "Vacuum-PresenceMonitor: %s Reinigung fortgesetzt",
                                    nickname,
                                )
                            else:
                                logger.warning(
                                    "Vacuum-PresenceMonitor: %s Fortsetzung fehlgeschlagen",
                                    nickname,
                                )

                        # Nur loeschen wenn mindestens ein Robot erfolgreich gestartet
                        if resumed_floors:
                            _interrupted_local = None
                            if _redis:
                                try:
                                    await _redis.delete("mha:vacuum:interrupted")
                                except Exception as e:
                                    logger.warning(
                                        "Vacuum-PresenceMonitor: Redis-Delete fehlgeschlagen: %s",
                                        e,
                                    )
                        else:
                            logger.warning(
                                "Vacuum-PresenceMonitor: Kein Robot konnte fortgesetzt werden — State behalten"
                            )

                        await self._notify(
                            "vacuum_resumed",
                            LOW,
                            {
                                "message": "Saugroboter setzt Reinigung fort — alle sind wieder weg",
                            },
                        )
                        try:
                            await self.brain.ha.log_activity(
                                "vacuum_auto",
                                "vacuum_resumed",
                                f"Staubsauger Reinigung fortgesetzt ({len(floors)} Roboter)",
                                arguments={"floors": floors},
                            )
                        except Exception as e:
                            logger.debug(
                                "Staubsauger-Fortsetzungs-Protokollierung fehlgeschlagen: %s",
                                e,
                            )

                # Fall 3: Alle Vacuums fertig (docked) → Alarm zurueckschalten
                if all_docked and not cleaning_robots:
                    should_restore = False
                    if _redis:
                        try:
                            was_switched = await _redis.get("mha:vacuum:alarm_switched")
                            if was_switched:
                                should_restore = True
                        except Exception as e:
                            logger.warning(
                                "Vacuum-PresenceMonitor: Redis-Check fehlgeschlagen: %s — pruefe Alarm-Status direkt",
                                e,
                            )
                            # Fallback: Alarm-Status direkt pruefen
                            try:
                                import assistant.config as _cfg3

                                _guard3 = _cfg3.yaml_config.get("vacuum", {}).get(
                                    "presence_guard", {}
                                )
                                if _guard3.get("switch_alarm_for_cleaning"):
                                    alarm_eid3 = _guard3.get("alarm_entity", "")
                                    if alarm_eid3:
                                        _astate3 = await self.brain.ha.get_state(
                                            alarm_eid3
                                        )
                                        if (
                                            _astate3
                                            and _astate3.get("state") == "armed_home"
                                        ):
                                            should_restore = True
                            except Exception as e2:
                                logger.warning(
                                    "Vacuum-PresenceMonitor: Alarm-Fallback-Check fehlgeschlagen: %s",
                                    e2,
                                )
                    else:
                        # Kein Redis: Alarm-Status direkt pruefen als Fallback
                        try:
                            import assistant.config as _cfg2

                            _guard = _cfg2.yaml_config.get("vacuum", {}).get(
                                "presence_guard", {}
                            )
                            if _guard.get("switch_alarm_for_cleaning"):
                                alarm_eid = _guard.get("alarm_entity", "")
                                if alarm_eid:
                                    _astate = await self.brain.ha.get_state(alarm_eid)
                                    if _astate and _astate.get("state") == "armed_home":
                                        should_restore = True
                        except Exception as e:
                            logger.warning(
                                "Vacuum-PresenceMonitor: Alarm-Fallback-Check fehlgeschlagen: %s",
                                e,
                            )
                    if should_restore:
                        await self._vacuum_alarm_switch("arm_away")

            except Exception as e:
                logger.error("Vacuum-PresenceMonitor Fehler: %s", e)

            await asyncio.sleep(30)  # 30 Sekunden Polling

    async def _run_vacuum_automation(self):
        """Saugroboter-Automatik: wenn niemand zuhause + keine Stoerung."""
        await asyncio.sleep(PROACTIVE_SEASONAL_STARTUP_DELAY + 120)  # Später starten

        _redis = getattr(self.brain, "memory", None)
        _redis = getattr(_redis, "redis", None) if _redis else None

        DAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

        while self._running:
            try:
                # Config bei jedem Durchlauf frisch lesen (Hot-Reload aus UI)
                import assistant.config as cfg

                vacuum_cfg = cfg.yaml_config.get("vacuum", {})
                auto_cfg = vacuum_cfg.get("auto_clean", {})
                robots = vacuum_cfg.get("robots", {})

                if not vacuum_cfg.get("enabled") or not auto_cfg.get("enabled"):
                    await asyncio.sleep(900)
                    continue

                mode = auto_cfg.get("mode", "smart")
                # Lokalzeit verwenden — schedule_time/preferred_time sind in Benutzer-Lokalzeit
                try:
                    from zoneinfo import ZoneInfo

                    _tz_name = vacuum_cfg.get("timezone") or cfg.yaml_config.get(
                        "timezone", "Europe/Berlin"
                    )
                    now = datetime.now(ZoneInfo(_tz_name))
                except Exception:
                    now = datetime.now(_LOCAL_TZ)
                hour = now.hour

                # ── Wochenplan-Trigger ──
                schedule_trigger = False
                if mode in ("schedule", "both"):
                    schedule_days = auto_cfg.get("schedule_days", [])
                    schedule_hour = auto_cfg.get("schedule_time", 10)
                    today_key = [k for k, v in DAY_MAP.items() if v == now.weekday()]
                    if (
                        today_key
                        and today_key[0] in schedule_days
                        and hour == schedule_hour
                    ):
                        schedule_trigger = True

                # ── Smart-Trigger (niemand zuhause) ──
                smart_trigger = False
                if mode in ("smart", "both"):
                    start_h = auto_cfg.get("preferred_time_start", 10)
                    end_h = auto_cfg.get("preferred_time_end", 16)
                    if start_h <= hour < end_h:
                        states = await self.brain.ha.get_states()
                        persons_home = [
                            s
                            for s in (states or [])
                            if s.get("entity_id", "").startswith("person.")
                            and s.get("state") == "home"
                        ]
                        nobody_home = auto_cfg.get("when_nobody_home", True)
                        if not nobody_home or not persons_home:
                            smart_trigger = True

                if not schedule_trigger and not smart_trigger:
                    await asyncio.sleep(900)
                    continue

                # Aktive Kalender-Events prüfen (z.B. "meeting" im Titel)
                not_during = auto_cfg.get("not_during", [])
                if not_during:
                    if not smart_trigger:
                        states = await self.brain.ha.get_states()
                    blocking = False
                    for s in states or []:
                        eid = s.get("entity_id", "")
                        if eid.startswith("calendar.") and s.get("state") == "on":
                            title = (
                                s.get("attributes", {}).get("message") or ""
                            ).lower()
                            if any(kw.lower() in title for kw in not_during):
                                blocking = True
                                break
                    if blocking:
                        await asyncio.sleep(900)
                        continue

                # Mindestabstand pro Roboter prüfen
                min_hours = auto_cfg.get("min_hours_between", 24)
                trigger_reason = "Wochenplan" if schedule_trigger else "niemand zuhause"
                for floor, robot in robots.items():
                    eid = robot.get("entity_id")
                    if not eid:
                        continue

                    if _redis:
                        try:
                            last_key = f"mha:vacuum:{floor}:last_auto_clean"
                            last = await _redis.get(last_key)
                            if last:
                                try:
                                    hours_since = (time.time() - float(last)) / 3600
                                    if hours_since < min_hours:
                                        continue
                                except (ValueError, TypeError):
                                    logger.warning(
                                        "Vacuum-Auto: Ungueltige Zeitangabe fuer %s: %s",
                                        last_key,
                                        last,
                                    )
                        except Exception as e:
                            logger.warning(
                                "Vacuum-Auto: Redis-Cooldown-Check fehlgeschlagen fuer %s: %s",
                                floor,
                                e,
                            )

                    # Saugstaerke + Modus für Auto-Clean
                    auto_fan = auto_cfg.get("auto_fan_speed", "") or vacuum_cfg.get(
                        "default_fan_speed", ""
                    )
                    auto_mode = auto_cfg.get("auto_mode", "") or vacuum_cfg.get(
                        "default_mode", ""
                    )

                    # Anwesenheits-Guard + Alarm-Management
                    nickname = robot.get("nickname", f"Saugroboter {floor.upper()}")
                    success = await self._vacuum_start_with_alarm(
                        eid,
                        nickname,
                        trigger_reason,
                        fan_speed=auto_fan,
                        mode=auto_mode,
                    )
                    if success:
                        if _redis:
                            try:
                                await _redis.set(
                                    f"mha:vacuum:{floor}:last_auto_clean",
                                    str(time.time()),
                                )
                            except Exception as e:
                                logger.warning(
                                    "Vacuum-Auto: Redis-Timestamp setzen fehlgeschlagen: %s",
                                    e,
                                )
                        await self._notify(
                            "vacuum_auto_start",
                            LOW,
                            {
                                "message": f"{nickname} startet automatisch ({trigger_reason})",
                            },
                        )
                        logger.info(
                            "Vacuum-Auto: %s gestartet (%s, %s)",
                            eid,
                            floor,
                            trigger_reason,
                        )
                    else:
                        logger.info(
                            "Vacuum-Auto: %s nicht gestartet (Guard blockiert)",
                            nickname,
                        )

                # Wartung prüfen (1x pro Durchlauf)
                await self._check_vacuum_maintenance(robots, _redis)

            except Exception as e:
                logger.error("Vacuum-Automation Fehler: %s", e)

            await asyncio.sleep(900)  # 15 Minuten

    def _find_robot_for_room(self, robots: dict, room: str):
        """Findet Roboter + Segment-ID für einen Raum (case-insensitive)."""
        room_lower = room.lower()
        for floor, r in robots.items():
            rooms_map = r.get("rooms", {})
            for rname, seg_id in rooms_map.items():
                if rname.lower() == room_lower:
                    return r, seg_id
        # Fallback: ersten Roboter ohne Segment
        if robots:
            return next(iter(robots.values())), None
        return None, None

    async def _start_vacuum_room(self, robot: dict, segment_id, room: str, reason: str):
        """Startet Vacuum für einen Raum mit Logging, Anwesenheits-Guard und Alarm."""
        eid = robot.get("entity_id", "")
        if not eid:
            logger.warning("Vacuum-Trigger: Kein entity_id für Roboter konfiguriert")
            return False

        # Anwesenheits-Guard: Nicht starten wenn jemand zuhause
        can_start, block_reason = await self._vacuum_can_start()
        if not can_start:
            logger.info(
                "Vacuum-Guard: %s fuer '%s' blockiert — %s | Trigger: %s",
                robot.get("nickname", "Saugroboter"),
                room,
                block_reason,
                reason,
            )
            return False

        # Alarm umschalten (abwesend → anwesend)
        alarm_ok = await self._vacuum_alarm_switch("arm_home")
        if not alarm_ok:
            logger.error(
                "Vacuum-Trigger: Alarm konnte nicht umgeschaltet werden — %s wird NICHT gestartet",
                robot.get("nickname", "Saugroboter"),
            )
            return False

        nickname = robot.get("nickname", "Saugroboter")
        success = False

        if segment_id is not None:
            # Segment-ID als int sicherstellen (Dreame erwartet int)
            try:
                seg = int(segment_id)
            except (ValueError, TypeError):
                seg = segment_id

            logger.info(
                "Vacuum-Trigger: Starte %s (%s) für Raum '%s' Segment=%s",
                nickname,
                eid,
                room,
                seg,
            )

            # Try Dreame-specific service first (Tasshack integration),
            # then fall back to generic vacuum.send_command (Roborock/Miio)
            success = await self.brain.ha.call_service(
                "dreame_vacuum",
                "vacuum_clean_segment",
                {
                    "entity_id": eid,
                    "segments": [seg],
                },
            )
            if not success:
                logger.info(
                    "Vacuum-Trigger: dreame_vacuum.vacuum_clean_segment nicht verfügbar, versuche vacuum.send_command"
                )
                success = await self.brain.ha.call_service(
                    "vacuum",
                    "send_command",
                    {
                        "entity_id": eid,
                        "command": "app_segment_clean",
                        "params": [seg],
                    },
                )
            if not success:
                logger.warning(
                    "Vacuum-Trigger: send_command fehlgeschlagen, versuche vacuum.start"
                )
                success = await self.brain.ha.call_service(
                    "vacuum", "start", {"entity_id": eid}
                )
        else:
            logger.info(
                "Vacuum-Trigger: Starte %s (%s) komplett (kein Segment für '%s')",
                nickname,
                eid,
                room,
            )
            success = await self.brain.ha.call_service(
                "vacuum", "start", {"entity_id": eid}
            )

        if success:
            logger.info(
                "Vacuum-Trigger: %s erfolgreich gestartet (%s)", nickname, reason
            )
        else:
            logger.error(
                "Vacuum-Trigger: %s Start FEHLGESCHLAGEN (%s)", nickname, reason
            )
            await self._vacuum_alarm_switch("arm_away")

        return success

    async def _run_vacuum_power_trigger(self):
        """Steckdosen-Trigger: Wenn Leistung unter Schwellwert → Raum saugen."""
        await asyncio.sleep(30)  # Kurzer Startup-Delay

        import assistant.config as cfg

        _redis = getattr(self.brain, "memory", None)
        _redis = getattr(_redis, "redis", None) if _redis else None

        # Zustand: war die Steckdose vorher "an" (über Schwellwert)?
        was_above: dict[str, bool] = {}

        logger.info("Vacuum-PowerTrigger: Task gestartet")

        while self._running:
            try:
                # Config bei jeder Iteration neu lesen (UI-Änderungen)
                vacuum_cfg = cfg.yaml_config.get("vacuum", {})
                pt_cfg = vacuum_cfg.get("power_trigger", {})
                robots = vacuum_cfg.get("robots", {})

                if not pt_cfg.get("enabled"):
                    await asyncio.sleep(60)
                    continue

                triggers = pt_cfg.get("triggers", [])
                delay_min = pt_cfg.get("delay_minutes", 5)
                cooldown_h = pt_cfg.get("cooldown_hours", 12)

                # Cleanup: Entfernte Entities aus Tracking-Dict loeschen
                active_entities = {
                    t.get("power_entity") for t in triggers if t.get("power_entity")
                }
                for old_key in list(was_above.keys()):
                    if old_key not in active_entities:
                        del was_above[old_key]

                if not triggers:
                    logger.debug("Vacuum-PowerTrigger: Keine Trigger konfiguriert")
                    await asyncio.sleep(60)
                    continue

                for trigger in triggers:
                    entity = trigger.get("entity", "")
                    threshold = trigger.get("threshold", 5)
                    room = trigger.get("room", "")
                    if not entity or not room:
                        continue

                    state = await self.brain.ha.get_state(entity)
                    if not state:
                        logger.debug(
                            "Vacuum-PowerTrigger: Entity %s nicht gefunden", entity
                        )
                        continue

                    try:
                        power = float(state.get("state", 0))
                    except (ValueError, TypeError):
                        logger.debug(
                            "Vacuum-PowerTrigger: %s hat keinen numerischen State: %s",
                            entity,
                            state.get("state"),
                        )
                        continue

                    above = power >= threshold
                    prev_above = was_above.get(entity)  # None beim 1. Durchlauf
                    was_above[entity] = above

                    if prev_above is None:
                        # Erster Durchlauf nach Start: nur Zustand merken, kein Edge
                        logger.debug(
                            "Vacuum-PowerTrigger: %s initialisiert (%.1fW, above=%s)",
                            entity,
                            power,
                            above,
                        )
                        continue

                    logger.debug(
                        "Vacuum-PowerTrigger: %s = %.1fW (Schwelle: %sW, vorher_drüber: %s, jetzt_drüber: %s)",
                        entity,
                        power,
                        threshold,
                        prev_above,
                        above,
                    )

                    # Fallende Flanke: war über Schwellwert, jetzt drunter
                    if prev_above and not above:
                        # Cooldown prüfen
                        if _redis:
                            try:
                                cd_key = f"mha:vacuum:pt:{entity}"
                                last = await _redis.get(cd_key)
                                if last:
                                    try:
                                        hours_since = (time.time() - float(last)) / 3600
                                        if hours_since < cooldown_h:
                                            logger.info(
                                                "Vacuum-PowerTrigger: %s Cooldown aktiv (%.1fh von %sh)",
                                                entity,
                                                hours_since,
                                                cooldown_h,
                                            )
                                            continue
                                    except (ValueError, TypeError):
                                        logger.warning(
                                            "Vacuum-PowerTrigger: Ungueltige Cooldown-Daten fuer %s",
                                            entity,
                                        )
                            except Exception as e:
                                logger.warning(
                                    "Vacuum-PowerTrigger: Redis-Cooldown-Check fehlgeschlagen: %s",
                                    e,
                                )

                        # Verzoegerung abwarten
                        logger.info(
                            "Vacuum-PowerTrigger: %s unter %sW — warte %d Min",
                            entity,
                            threshold,
                            delay_min,
                        )
                        await asyncio.sleep(delay_min * 60)

                        # Nochmal prüfen ob immer noch aus
                        recheck = await self.brain.ha.get_state(entity)
                        try:
                            recheck_power = (
                                float(recheck.get("state", 0)) if recheck else threshold
                            )
                        except (ValueError, TypeError):
                            recheck_power = threshold
                        if recheck_power >= threshold:
                            logger.info(
                                "Vacuum-PowerTrigger: %s wieder über Schwelle (%.1fW) — abgebrochen",
                                entity,
                                recheck_power,
                            )
                            was_above[entity] = True
                            continue

                        # Raum → Roboter + Segment finden
                        robot, segment_id = self._find_robot_for_room(robots, room)

                        if not robot:
                            logger.warning(
                                "Vacuum-PowerTrigger: Kein Roboter für Raum '%s' gefunden (robots: %s)",
                                room,
                                list(robots.keys()),
                            )
                            continue

                        reason = f"Steckdose {entity} abgeschaltet"
                        success = await self._start_vacuum_room(
                            robot, segment_id, room, reason
                        )

                        if success:
                            if _redis:
                                await _redis.set(
                                    f"mha:vacuum:pt:{entity}", str(time.time())
                                )
                            nickname = robot.get("nickname", "Saugroboter")
                            await self._notify(
                                "vacuum_power_trigger",
                                LOW,
                                {
                                    "message": f"{nickname} reinigt '{room}' — {reason}",
                                },
                            )

            except Exception as e:
                logger.error("Vacuum-PowerTrigger Fehler: %s", e, exc_info=True)

            await asyncio.sleep(60)  # 1 Minute Polling

    async def _run_vacuum_scene_trigger(self):
        """Szenen-Trigger: Wenn eine Szene aktiviert wird → Raum saugen."""
        await asyncio.sleep(30)  # Kurzer Startup-Delay

        import assistant.config as cfg

        _redis = getattr(self.brain, "memory", None)
        _redis = getattr(_redis, "redis", None) if _redis else None

        # Letzter bekannter last_changed-Zeitstempel pro Entity
        last_seen: dict[str, str] = {}

        logger.info("Vacuum-SceneTrigger: Task gestartet")

        while self._running:
            try:
                # Config bei jeder Iteration neu lesen (UI-Änderungen)
                vacuum_cfg = cfg.yaml_config.get("vacuum", {})
                st_cfg = vacuum_cfg.get("scene_trigger", {})
                robots = vacuum_cfg.get("robots", {})

                if not st_cfg.get("enabled"):
                    await asyncio.sleep(60)
                    continue

                triggers = st_cfg.get("triggers", [])
                delay_min = st_cfg.get("delay_minutes", 5)
                cooldown_h = st_cfg.get("cooldown_hours", 12)

                if not triggers:
                    logger.debug("Vacuum-SceneTrigger: Keine Trigger konfiguriert")
                    await asyncio.sleep(60)
                    continue

                # Cleanup: Entfernte Entities aus Tracking-Dict loeschen
                active_scene_entities = {
                    t.get("entity") for t in triggers if t.get("entity")
                }
                for old_key in list(last_seen.keys()):
                    if old_key not in active_scene_entities:
                        del last_seen[old_key]

                for trigger in triggers:
                    entity = trigger.get("entity", "")
                    room = trigger.get("room", "")
                    if not entity or not room:
                        continue

                    state = await self.brain.ha.get_state(entity)
                    if not state:
                        logger.debug(
                            "Vacuum-SceneTrigger: Entity %s nicht gefunden", entity
                        )
                        continue

                    # Szenen haben als last_changed den Zeitpunkt der letzten Aktivierung
                    changed = state.get("last_changed", "")
                    prev_changed = last_seen.get(entity)
                    last_seen[entity] = changed

                    # Erster Durchlauf: nur merken, nicht triggern
                    if prev_changed is None:
                        logger.debug(
                            "Vacuum-SceneTrigger: %s erster Check, merke last_changed=%s",
                            entity,
                            changed[:19] if changed else "?",
                        )
                        continue

                    # Szene wurde aktiviert (last_changed hat sich geändert)
                    if changed != prev_changed:
                        logger.info(
                            "Vacuum-SceneTrigger: %s aktiviert (changed: %s → %s)",
                            entity,
                            prev_changed[:19] if prev_changed else "?",
                            changed[:19] if changed else "?",
                        )

                        # Cooldown prüfen
                        if _redis:
                            try:
                                cd_key = f"mha:vacuum:st:{entity}"
                                last = await _redis.get(cd_key)
                                if last:
                                    try:
                                        hours_since = (time.time() - float(last)) / 3600
                                        if hours_since < cooldown_h:
                                            logger.info(
                                                "Vacuum-SceneTrigger: %s Cooldown aktiv (%.1fh von %sh)",
                                                entity,
                                                hours_since,
                                                cooldown_h,
                                            )
                                            continue
                                    except (ValueError, TypeError):
                                        logger.warning(
                                            "Vacuum-SceneTrigger: Ungueltige Cooldown-Daten fuer %s",
                                            entity,
                                        )
                            except Exception as e:
                                logger.warning(
                                    "Vacuum-SceneTrigger: Redis-Cooldown-Check fehlgeschlagen: %s",
                                    e,
                                )

                        # Verzoegerung
                        scene_name = (
                            entity.replace("scene.", "").replace("_", " ").title()
                        )
                        logger.info(
                            "Vacuum-SceneTrigger: %s — warte %d Min vor Start",
                            entity,
                            delay_min,
                        )
                        await asyncio.sleep(delay_min * 60)

                        # Raum → Roboter + Segment finden
                        robot, segment_id = self._find_robot_for_room(robots, room)

                        if not robot:
                            logger.warning(
                                "Vacuum-SceneTrigger: Kein Roboter für Raum '%s' gefunden (robots: %s)",
                                room,
                                list(robots.keys()),
                            )
                            continue

                        reason = f"Szene '{scene_name}' aktiviert"
                        success = await self._start_vacuum_room(
                            robot, segment_id, room, reason
                        )

                        if success:
                            if _redis:
                                await _redis.set(
                                    f"mha:vacuum:st:{entity}", str(time.time())
                                )
                            nickname = robot.get("nickname", "Saugroboter")
                            await self._notify(
                                "vacuum_scene_trigger",
                                LOW,
                                {
                                    "message": f"{nickname} reinigt '{room}' — {reason}",
                                },
                            )

            except Exception as e:
                logger.error("Vacuum-SceneTrigger Fehler: %s", e, exc_info=True)

            await asyncio.sleep(60)  # 1 Minute Polling

    async def _check_vacuum_maintenance(self, robots: dict, redis_client=None):
        """Prüft Filter/Buerste/Mopp Verschleiss und erinnert."""
        import assistant.config as cfg

        maint_cfg = cfg.yaml_config.get("vacuum", {}).get("maintenance", {})
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

            # Mehrere gängige Attribut-Namen prüfen (Dreame-Addon vs. Valetudo vs. Xiaomi Cloud)
            checks = {
                "Filter": attrs.get("filter_left") or attrs.get("filter_life_level"),
                "Hauptbuerste": attrs.get("main_brush_left")
                or attrs.get("brush_life_level")
                or attrs.get("main_brush_life_level"),
                "Seitenbuerste": attrs.get("side_brush_left")
                or attrs.get("side_brush_life_level"),
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
                    try:
                        dedup_key = f"mha:vacuum:maint:{floor}:{part}"
                        already = await redis_client.get(dedup_key)
                        if already:
                            continue
                        await redis_client.set(dedup_key, "1", ex=86400)
                    except Exception as e:
                        logger.warning(
                            "Vacuum-Wartung: Redis-Dedup fehlgeschlagen (%s): %s",
                            part,
                            e,
                        )

                await self._notify(
                    "vacuum_maintenance",
                    MEDIUM,
                    {
                        "message": f"{nickname}: {part} bei {remaining}% — Wechsel empfohlen",
                    },
                )
                logger.info("Vacuum-Wartung: %s %s bei %d%%", floor, part, remaining)

    # ------------------------------------------------------------------
    # Bettbelegung
    # ------------------------------------------------------------------

    async def _is_bed_occupied(self, states=None) -> bool:
        """Prüft ob ein Bettbelegungssensor aktiv ist (jemand schlaeft)."""
        try:
            if states is None:
                states = await self.brain.ha.get_states()
            bed_sensors = [
                s
                for s in (states or [])
                if s.get("entity_id", "").startswith("binary_sensor.")
                and s.get("attributes", {}).get("device_class") == "occupancy"
                and any(
                    kw in s.get("entity_id", "").lower()
                    for kw in ("bett", "bed", "matratze", "mattress")
                )
            ]
            if not bed_sensors:
                # Fallback: Occupancy-Sensoren in Schlafzimmern
                bed_sensors = [
                    s
                    for s in (states or [])
                    if s.get("entity_id", "").startswith("binary_sensor.")
                    and s.get("attributes", {}).get("device_class") == "occupancy"
                    and any(
                        kw in s.get("entity_id", "").lower()
                        for kw in ("schlafzimmer", "bedroom")
                    )
                ]
            if bed_sensors:
                return any(s.get("state") == "on" for s in bed_sensors)
        except Exception as e:
            logger.warning("Unhandled: %s", e)
        return False

    _SLEEP_LOCK_KEY = "mha:cover:sleep_lock"
    _SLEEP_LOCK_TTL_DEFAULT = 1800  # 30 Minuten Fallback

    @property
    def _sleep_lock_ttl(self) -> int:
        """Sleep-Lock TTL aus Config (Minuten → Sekunden), Fallback 30 Min."""
        try:
            cover_cfg = yaml_config.get("seasonal_actions", {}).get(
                "cover_automation", {}
            )
            minutes = cover_cfg.get("sleep_lock_minutes", 30)
            return max(60, int(minutes) * 60)  # Minimum 1 Minute
        except Exception as e:
            logger.debug("Sleep-Lock-TTL Berechnung fehlgeschlagen: %s", e)
            return self._SLEEP_LOCK_TTL_DEFAULT

    async def _is_sleeping(self, states=None) -> bool:
        """Prüft ob geschlafen wird — robust gegen Sensor-Flackern.

        Kombiniert vier Quellen:
        1. Activity-Modul (detect_activity → sleeping)
        2. Manueller Override (z.B. 'Gute Nacht' gesagt → sleeping)
        3. Bettsensor-Fallback (_is_bed_occupied)
        4. Redis Sleep-Lock (sticky: wenn sleeping erkannt, bleibt Lock
           für 30 Min aktiv — auch wenn Sensor kurz flackert)

        Returns True wenn EINE der Quellen Schlaf erkennt.
        """
        is_sleeping_now = False

        # 1. Activity-Modul (enthält manuellen Override + Sensor-Erkennung)
        try:
            detection = await self.brain.activity.detect_activity()
            activity = detection.get("activity", "")
            if activity == "sleeping":
                is_sleeping_now = True
                logger.debug(
                    "_is_sleeping: True (activity=%s, confidence=%.2f)",
                    activity,
                    detection.get("confidence", 0),
                )
        except Exception as e:
            logger.debug("_is_sleeping: Activity-Check fehlgeschlagen: %s", e)

        # 2. Bettsensor-Fallback
        if not is_sleeping_now and await self._is_bed_occupied(states):
            is_sleeping_now = True
            logger.debug("_is_sleeping: True (bed_occupied Fallback)")

        # 3. Sleep-Lock setzen/prüfen (sticky — gegen Sensor-Flackern)
        try:
            _redis = (
                self.brain.memory.redis
                if self.brain.memory and hasattr(self.brain.memory, "redis")
                else None
            )
            if not _redis:
                return is_sleeping_now

            if is_sleeping_now:
                # Lock setzen/erneuern (konfigurierbare Dauer)
                await _redis.setex(self._SLEEP_LOCK_KEY, self._sleep_lock_ttl, "1")
                return True

            # Nicht sleeping laut Sensoren — aber Lock noch aktiv?
            lock = await _redis.get(self._SLEEP_LOCK_KEY)
            if lock:
                ttl = await _redis.ttl(self._SLEEP_LOCK_KEY)
                logger.debug("_is_sleeping: True (Sleep-Lock aktiv, TTL=%ds)", ttl)
                return True
        except Exception as e:
            logger.debug("_is_sleeping: Redis Sleep-Lock Fehler: %s", e)

        return is_sleeping_now

    # ------------------------------------------------------------------
    # Notfall-Protokolle
    # ------------------------------------------------------------------

    # Erlaubte Notfall-Protokollnamen (Whitelist)
    _VALID_EMERGENCY_PROTOCOLS = frozenset(
        {"fire", "intrusion", "water_leak", "gas_leak", "co_alarm"}
    )

    async def _execute_emergency_protocol(self, protocol_name: str):
        """Fuehrt ein konfiguriertes Notfall-Protokoll aus.

        Sicherheits-Massnahmen:
        - Nur vordefinierte Protokollnamen erlaubt (Whitelist)
        - Erlaubte Domains/Services beschraenkt (keine beliebigen HA-Calls)
        - Vollstaendiges Audit-Logging jeder Aktion
        - Autonomie-Check: Bei Level 1 werden nur Notifications gesendet

        Protokolle werden in settings.yaml definiert unter emergency_protocols.
        Beispiel:
            emergency_protocols:
              fire:
                actions:
                  - {domain: light, service: turn_on, target: all}
                  - {domain: lock, service: unlock, target: all}
                  - {domain: notify, service: notify, data: {message: "FEUERALARM!"}}
        """
        # Whitelist-Check: Nur bekannte Protokollnamen erlaubt
        if protocol_name not in self._VALID_EMERGENCY_PROTOCOLS:
            logger.warning(
                "SECURITY: Unbekannter Notfall-Protokollname '%s' abgelehnt",
                protocol_name,
            )
            return

        protocol = self._emergency_protocols.get(protocol_name)
        if not protocol:
            logger.debug("Kein Notfall-Protokoll fuer '%s' konfiguriert", protocol_name)
            return

        actions = protocol.get("actions", [])
        if not actions:
            return

        # Autonomie-Check: Bei Level 1 nur benachrichtigen, nicht handeln
        _autonomy = getattr(self.brain, "autonomy", None)
        _auto_lvl = _autonomy.level if _autonomy is not None else 2
        if _auto_lvl < 2:
            logger.warning(
                "NOTFALL-PROTOKOLL '%s': Autonomie-Level %d — nur Notification, keine Aktionen",
                protocol_name,
                _auto_lvl,
            )
            await self._notify(
                f"emergency_{protocol_name}",
                CRITICAL,
                {
                    "protocol": protocol_name,
                    "message": f"Notfall '{protocol_name}' erkannt. Autonomie-Level zu niedrig fuer automatische Aktionen.",
                    "actions_blocked": len(actions),
                },
            )
            return

        # Erlaubte Domains/Services fuer Emergency (keine beliebigen Calls)
        _ALLOWED_EMERGENCY_DOMAINS = {
            "light",
            "lock",
            "switch",
            "cover",
            "notify",
            "alarm_control_panel",
            "siren",
            "fan",
        }

        logger.warning(
            "NOTFALL-PROTOKOLL '%s' wird ausgefuehrt (%d Protokoll-Aktionen, Autonomie: %d)",
            protocol_name,
            len(actions),
            _auto_lvl,
        )

        executed = []
        blocked = []
        for action in actions:
            domain = action.get("domain", "")
            service = action.get("service", "")
            target = action.get("target", "")
            data = action.get("data", {})

            if not domain or not service:
                continue

            # Domain-Whitelist pruefen
            if domain not in _ALLOWED_EMERGENCY_DOMAINS:
                logger.warning(
                    "SECURITY: Emergency-Aktion mit Domain '%s' blockiert (nicht erlaubt)",
                    domain,
                )
                blocked.append(f"{domain}.{service}")
                continue

            try:
                if target == "all":
                    states = await self.brain.ha.get_states()
                    for s in states or []:
                        eid = s.get("entity_id", "")
                        if eid.startswith(f"{domain}."):
                            await self.brain.ha.call_service(
                                domain,
                                service,
                                {"entity_id": eid, **data},
                            )
                            executed.append(eid)
                elif target:
                    await self.brain.ha.call_service(
                        domain,
                        service,
                        {"entity_id": target, **data},
                    )
                    executed.append(target)
                else:
                    await self.brain.ha.call_service(domain, service, data)
                    executed.append(f"{domain}.{service}")
            except Exception as e:
                logger.error(
                    "Notfall-Aktion fehlgeschlagen: %s.%s -> %s", domain, service, e
                )

        # Audit-Log
        logger.warning(
            "Notfall-Protokoll '%s': %d Aktionen ausgefuehrt, %d blockiert: %s",
            protocol_name,
            len(executed),
            len(blocked),
            [e for e in executed],
        )
        if blocked:
            logger.warning(
                "Notfall-Protokoll '%s': blockierte Aktionen: %s",
                protocol_name,
                blocked,
            )

        # Activity-Log fuer UI
        try:
            await self.brain.ha.log_activity(
                "emergency",
                f"emergency_{protocol_name}",
                f"Notfall-Protokoll '{protocol_name}': {len(executed)} Aktionen ausgefuehrt",
                arguments={"executed": executed[:20], "blocked": blocked[:10]},
                result=f"{len(executed)} ausgefuehrt, {len(blocked)} blockiert",
            )
        except Exception as e:
            logger.warning("Notfall-Protokoll-Protokollierung fehlgeschlagen: %s", e)

    # ------------------------------------------------------------------
    # Phase 17: Threat Assessment Loop
    # ------------------------------------------------------------------

    async def _run_threat_assessment_loop(self):
        """Periodischer Sicherheits- + Energie-Check."""
        await asyncio.sleep(PROACTIVE_THREAT_STARTUP_DELAY)
        logger.info("Threat-Assessment-Loop gestartet")

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
                    # LLM-Kontext: Bedrohung mit Wetter/Uhrzeit kontextualisieren
                    threat_msg = await self._contextualize_threat(threat)
                    await self._notify(
                        "threat_detected",
                        urgency,
                        {
                            "type": threat.get("type", "unknown"),
                            "message": threat_msg,
                            "entity": threat.get("entity", ""),
                        },
                    )

                    # Eskalation für kritische Bedrohungen
                    if threat.get("urgency") == "critical":
                        try:
                            actions = (
                                await self.brain.threat_assessment.escalate_threat(
                                    threat
                                )
                            )
                            if actions:
                                logger.info("Threat Eskalation: %s", ", ".join(actions))
                                # B6-ext: Erste Krise als Beziehungs-Milestone
                                try:
                                    _redis = (
                                        self.brain.memory.redis
                                        if self.brain.memory
                                        else None
                                    )
                                    if _redis:
                                        _first = await _redis.set(
                                            "mha:relationship:first_crisis",
                                            "1",
                                            ex=365 * 86400,
                                            nx=True,
                                        )
                                        if _first:
                                            await (
                                                self.brain.personality.record_milestone(
                                                    "system",
                                                    "Erste Krise gemeinsam gemeistert",
                                                )
                                            )
                                except Exception as e:
                                    logger.warning(
                                        "Threat-Eskalations-Benachrichtigung fehlgeschlagen: %s",
                                        e,
                                    )
                        except Exception as esc_err:
                            logger.warning(
                                "Threat Eskalation fehlgeschlagen: %s", esc_err
                            )
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
                    await self._notify(
                        pred.get("type", "foresight"),
                        urgency,
                        {
                            "message": pred.get("message", ""),
                        },
                    )
            except Exception as e:
                logger.debug("Foresight Fehler: %s", e)

            # Energy Events prüfen + taegliches Kostentracking
            try:
                if (
                    hasattr(self.brain, "energy_optimizer")
                    and self.brain.energy_optimizer.enabled
                ):
                    energy_alerts = (
                        await self.brain.energy_optimizer.check_energy_events()
                    )
                    for alert in energy_alerts:
                        urgency = LOW  # Energie-Alerts sind immer LOW
                        await self._notify(
                            alert.get("type", "energy_event"),
                            urgency,
                            {
                                "message": alert.get("message", ""),
                            },
                        )

                    # Taegliches Kostentracking (einmal pro Tag via Redis-Cooldown)
                    if self.brain.memory and self.brain.memory.redis:
                        tracked_key = "mha:energy:daily_tracked"
                        from datetime import datetime as _dt

                        today = _dt.now(timezone.utc).strftime("%Y-%m-%d")
                        last_tracked = await self.brain.memory.redis.get(tracked_key)
                        if isinstance(last_tracked, bytes):
                            last_tracked = last_tracked.decode("utf-8", errors="ignore")
                        if not last_tracked or last_tracked != today:
                            await self.brain.energy_optimizer.track_daily_cost()
                            await self.brain.memory.redis.setex(
                                tracked_key, 86400, today
                            )
            except Exception as e:
                logger.debug("Energy Check Fehler: %s", e)

            await asyncio.sleep(PROACTIVE_THREAT_CHECK_INTERVAL)

    # ------------------------------------------------------------------
    # Ambient Presence: Jarvis ist immer da
    # ------------------------------------------------------------------

    async def _run_ambient_presence_loop(self):
        """Periodisches Status-Flüstern — Jarvis ist eine Praesenz, kein totes System."""
        import random

        ambient_cfg = yaml_config.get("ambient_presence", {})
        interval = ambient_cfg.get("interval_minutes", 60) * 60
        quiet_start = ambient_cfg.get("quiet_start", 22)
        quiet_end = ambient_cfg.get("quiet_end", 7)
        report_weather = ambient_cfg.get("report_weather", True)
        report_energy = ambient_cfg.get("report_energy", True)
        all_quiet_prob = ambient_cfg.get("all_quiet_probability", 0.2)

        await asyncio.sleep(PROACTIVE_AMBIENT_CHECK_INTERVAL)
        logger.info("Ambient-Presence-Loop gestartet (interval=%ds)", interval)

        while self._running:
            try:
                hour = datetime.now(_LOCAL_TZ).hour

                # Quiet Hours respektieren
                if self._is_quiet_hours():
                    await asyncio.sleep(interval)
                    continue

                # Nur bei "relaxing" Activity sprechen
                try:
                    detection = await self.brain.activity.detect_activity()
                    activity = detection.get("activity", "")
                except Exception as e:
                    logger.debug("Aktivitaetserkennung fehlgeschlagen: %s", e)
                    activity = ""

                if activity != "relaxing":
                    await asyncio.sleep(interval)
                    continue

                # Autonomie-Level prüfen (mindestens Level 2)
                _autonomy = getattr(self.brain, "autonomy", None)
                if (_autonomy.level if _autonomy else 2) < 2:
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

                if (
                    states
                    and report_energy
                    and hasattr(self.brain, "energy_optimizer")
                    and self.brain.energy_optimizer.has_configured_entities
                ):
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
                    _quiet_person = (
                        _quiet_persons[0] if len(_quiet_persons) == 1 else ""
                    )
                    msg = f"Alles ruhig, {get_person_title(_quiet_person) if _quiet_person else get_person_title()}."
                else:
                    # Nichts zu berichten, nichts sagen
                    await asyncio.sleep(interval)
                    continue

                # Via Notification-System senden (nutzt Silence Matrix + Batching)
                await self._notify(
                    "ambient_status",
                    LOW,
                    {
                        "message": msg,
                    },
                )

            except Exception as e:
                logger.debug("Ambient Presence Fehler: %s", e)

            # MCU Sprint 3: Vacation Auto-Detection
            try:
                await self._check_vacation_auto_detect()
            except Exception as e:
                logger.debug("Vacation Auto-Detection Fehler: %s", e)

            await asyncio.sleep(interval)

    async def _check_vacation_auto_detect(self):
        """MCU Sprint 3: Suggests vacation mode after >48h of nobody home."""
        if not self.brain.memory.redis:
            return

        anyone_home = await self._is_anyone_home()
        _vac_key = "mha:proactive:nobody_home_since"
        _vac_notified_key = "mha:proactive:vacation_suggested"

        if anyone_home:
            # Someone's home — reset tracker
            await self.brain.memory.redis.delete(_vac_key)
            return

        # Nobody home — check/set timestamp
        stored = await self.brain.memory.redis.get(_vac_key)
        if not stored:
            await self.brain.memory.redis.set(
                _vac_key,
                datetime.now(timezone.utc).isoformat(),
                ex=604800,  # 7 days
            )
            return

        try:
            stored_str = stored.decode() if isinstance(stored, bytes) else stored
            since = datetime.fromisoformat(stored_str)
            hours_away = (datetime.now(timezone.utc) - since).total_seconds() / 3600

            if hours_away >= 48:
                # Check if already suggested in last 7 days
                already = await self.brain.memory.redis.get(_vac_notified_key)
                if already:
                    return

                await self.brain.memory.redis.set(_vac_notified_key, "1", ex=604800)
                title = get_person_title()
                msg = (
                    f"{title}, niemand ist seit {int(hours_away)} Stunden zuhause. "
                    f"Soll ich den Urlaubsmodus aktivieren?"
                )
                await self._deliver(
                    msg,
                    event_type="vacation_suggestion",
                    urgency=LOW,
                    volume=0.6,
                )
                logger.info(
                    "Vacation Auto-Detection: Vorschlag nach %dh", int(hours_away)
                )
        except (ValueError, TypeError):
            pass

    # ------------------------------------------------------------------
    # Event-basierte Wetter-Sensoren (WebSocket-Subscription)
    # ------------------------------------------------------------------

    async def _subscribe_weather_events(self, ws):
        """Subscribed auf Wetter-Sensor State-Changes via WebSocket.

        Statt alle 15 Min zu pollen, reagiert die Cover-Automation sofort
        auf kritische Wetter-Änderungen (Wind-Spitzen, Regeneinbruch).
        """
        from .cover_config import get_sensor_by_role

        weather_sensors = []
        for role in ("wind_sensor", "temp_outdoor", "rain_sensor", "sun_sensor"):
            eid = get_sensor_by_role(role)
            if eid:
                weather_sensors.append(eid)
        if not weather_sensors:
            return

        self._weather_event_cache = {}
        logger.info(
            "Wetter-Event-Subscription: %d Sensoren registriert", len(weather_sensors)
        )

    async def _on_entity_recovered(self, entity_id: str, new_val: str, new_state: dict):
        """Wird aufgerufen wenn eine Entity von unavailable → online wechselt.

        Raeumt Auto-Suppress in DiagnosticsEngine auf und benachrichtigt
        optional den Benutzer wenn die Entity lange offline war.
        """
        diag = getattr(self.brain, "diagnostics", None)
        if not diag:
            return

        result = diag.on_entity_recovered(entity_id)

        # Wenn Entity auto-suppressed war → Benutzer informieren
        if result:
            friendly = new_state.get("attributes", {}).get("friendly_name", entity_id)
            logger.info(
                "Entity recovered: %s (%s) — war auto-suppressed seit %s",
                entity_id,
                new_val,
                result.get("was_suppressed_since", "?"),
            )
            await self._notify(
                "entity_recovered",
                LOW,
                {
                    "entity": entity_id,
                    "message": f"{friendly} ist wieder online (Status: {new_val})",
                    "was_offline_since": result.get("was_suppressed_since", ""),
                },
            )
        else:
            logger.debug(
                "Entity recovered (nicht suppressed): %s → %s", entity_id, new_val
            )

    async def _handle_weather_event(
        self, entity_id: str, new_state: str, old_state: str
    ):
        """Reagiert auf kritische Wetter-Changes (Wind-Spike, Regen-Start)."""
        from .cover_config import get_sensor_by_role

        _redis = getattr(getattr(self.brain, "memory", None), "redis", None)

        # Wind-Spike: Sofortiger Sturmschutz wenn Wind plötzlich über Schwelle
        wind_eid = get_sensor_by_role("wind_sensor")
        if entity_id == wind_eid:
            try:
                wind = float(new_state)
                cover_cfg = yaml_config.get("seasonal_actions", {}).get(
                    "cover_automation", {}
                )
                storm_speed = cover_cfg.get("storm_wind_speed", 50)
                if wind >= storm_speed:
                    # Sofort-Dedup: Nicht doppelt auslösen wenn Loop auch gerade prüft
                    if _redis:
                        dedup = await _redis.get("mha:cover:weather_event_storm")
                        if dedup:
                            return
                        await _redis.set("mha:cover:weather_event_storm", "1", ex=300)
                    logger.warning(
                        "Wetter-Event: Wind-Spike %s km/h >= %s — Sofort-Sturmschutz",
                        wind,
                        storm_speed,
                    )
            except (ValueError, TypeError):
                pass

        # Regen-Start: Sofort Markisen einfahren
        rain_eid = get_sensor_by_role("rain_sensor")
        if (
            entity_id == rain_eid
            and new_state in ("on", "True", "true")
            and old_state in ("off", "False", "false")
        ):
            if _redis:
                dedup = await _redis.get("mha:cover:weather_event_rain")
                if dedup:
                    return
                await _redis.set("mha:cover:weather_event_rain", "1", ex=300)
            logger.info(
                "Wetter-Event: Regeneinbruch erkannt — Markisen sofort einfahren"
            )

    # ------------------------------------------------------------------
    # State-Machine pro Cover
    # ------------------------------------------------------------------

    class CoverState:
        """Einfache State-Machine pro Cover.

        States: idle, sun_protected, storm_secured, night_closed,
                manual_override, schedule_open, schedule_closed
        Transitions werden protokolliert für Debugging.
        """

        IDLE = "idle"
        SUN_PROTECTED = "sun_protected"
        STORM_SECURED = "storm_secured"
        NIGHT_CLOSED = "night_closed"
        MANUAL_OVERRIDE = "manual_override"
        SCHEDULE_OPEN = "schedule_open"
        SCHEDULE_CLOSED = "schedule_closed"
        HEATING_INSULATION = "heating_insulation"

        def __init__(self, entity_id: str):
            self.entity_id = entity_id
            self.state = self.IDLE
            self.since = datetime.now(timezone.utc)
            self.history: list[tuple[str, str, str]] = []  # (timestamp, from, to)

        def transition(self, new_state: str, reason: str = ""):
            if new_state != self.state:
                self.history.append(
                    (
                        datetime.now(timezone.utc).isoformat(),
                        self.state,
                        new_state,
                    )
                )
                # Max 20 History-Einträge behalten
                if len(self.history) > 20:
                    self.history = self.history[-20:]
                logger.debug(
                    "CoverState %s: %s → %s (%s)",
                    self.entity_id,
                    self.state,
                    new_state,
                    reason,
                )
                self.state = new_state
                self.since = datetime.now(timezone.utc)

        def to_dict(self) -> dict:
            return {
                "entity_id": self.entity_id,
                "state": self.state,
                "since": self.since.isoformat(),
                "history": self.history[-5:],
            }

    _cover_states: dict[str, "ProactiveManager.CoverState"] = {}

    def _get_cover_state(self, entity_id: str) -> "ProactiveManager.CoverState":
        """Holt oder erstellt die State-Machine für ein Cover."""
        if entity_id not in self._cover_states:
            self._cover_states[entity_id] = self.CoverState(entity_id)
        return self._cover_states[entity_id]

    def get_all_cover_states(self) -> list[dict]:
        """Gibt alle Cover-States zurück (für Debug/Dashboard)."""
        return [cs.to_dict() for cs in self._cover_states.values()]

    # ------------------------------------------------------------------
    # Morgen-Briefing: Cover-Zusammenfassung
    # ------------------------------------------------------------------

    async def get_cover_summary(self) -> str:
        """Erzeugt eine Zusammenfassung des Cover-Zustands für das Morgen-Briefing."""
        try:
            import json as _json

            states = await self.brain.ha.get_states()
            if not states:
                return ""
            covers = [s for s in states if s.get("entity_id", "").startswith("cover.")]
            if not covers:
                return ""

            open_covers = []
            closed_covers = []
            partial_covers = []
            for c in covers:
                eid = c.get("entity_id")
                pos = c.get("attributes", {}).get("current_position")
                if pos is None:
                    continue
                try:
                    jarvis_pos = self.brain.executor._translate_cover_position_from_ha(
                        eid, int(pos)
                    )
                except (ValueError, TypeError):
                    jarvis_pos = int(pos)
                name = c.get("attributes", {}).get(
                    "friendly_name", eid.replace("cover.", "")
                )
                if jarvis_pos >= 90:
                    open_covers.append(name)
                elif jarvis_pos <= 10:
                    closed_covers.append(name)
                else:
                    partial_covers.append(f"{name} ({jarvis_pos}%)")

            # Anomalien der letzten Nacht prüfen
            anomaly_count = 0
            _redis = getattr(getattr(self.brain, "memory", None), "redis", None)
            if _redis:
                for c in covers:
                    eid = c.get("entity_id")
                    anomaly_raw = await _redis.get(f"mha:cover:anomaly:{eid}")
                    if anomaly_raw:
                        try:
                            anomaly_count += int(anomaly_raw)
                        except (ValueError, TypeError):
                            pass

            parts = []
            if open_covers:
                parts.append(f"{len(open_covers)} offen")
            if closed_covers:
                parts.append(f"{len(closed_covers)} geschlossen")
            if partial_covers:
                parts.append(
                    f"{len(partial_covers)} teilweise ({', '.join(partial_covers[:3])})"
                )
            if anomaly_count > 0:
                parts.append(f"{anomaly_count} Anomalien letzte Nacht")

            if not parts:
                return ""
            return f"Rollläden: {', '.join(parts)}."
        except Exception as e:
            logger.debug("Cover-Summary Fehler: %s", e)
            return ""

    # ------------------------------------------------------------------
    # Proaktive Vorschläge (Schwellwerte anpassen)
    # ------------------------------------------------------------------

    async def _check_threshold_suggestions(
        self, weather: dict, cover_cfg: dict, redis_client
    ):
        """Analysiert ob Schwellwerte suboptimal sind und schlägt Anpassungen vor.

        Beispiel: Sonnenschutz triggert bei 26°C aber Nutzer öffnet manuell schon bei 24°C
        → Vorschlag: heat_protection_temp auf 24°C senken.
        """
        if not redis_client:
            return
        try:
            # Nur 1x pro Tag prüfen
            dedup_key = "mha:cover:threshold_suggestion"
            already = await redis_client.get(dedup_key)
            if already:
                return
            await redis_client.set(dedup_key, "1", ex=86400)

            suggestions = []
            temp = weather.get("temperature", 20)
            heat_temp = cover_cfg.get("heat_protection_temp", 26)

            # Prüfe: Wurden Cover manuell bei niedrigerer Temperatur geschlossen?
            import json as _json

            keys = []
            # Scan für manuelle Override-Keys
            cursor = 0
            while True:
                cursor, batch = await redis_client.scan(
                    cursor, match="mha:cover:manual_override:*", count=50
                )
                keys.extend(batch)
                if cursor == 0:
                    break

            if len(keys) >= 3 and temp < heat_temp - 2:
                suggestions.append(
                    f"Sonnenschutz-Schwelle liegt bei {heat_temp}°C, aber {len(keys)} Rollläden "
                    f"wurden manuell gesteuert bei {temp:.0f}°C. Vorschlag: heat_protection_temp "
                    f"auf {int(temp)}°C senken?"
                )

            # Wind-Schwelle: Sturmschutz zu oft/selten ausgelöst?
            storm_count_raw = await redis_client.get("mha:cover:storm_trigger_count")
            if storm_count_raw:
                storm_count = int(storm_count_raw)
                storm_speed = cover_cfg.get("storm_wind_speed", 50)
                if storm_count > 10:  # >10 Sturmauslösungen → Schwelle evtl. zu niedrig
                    suggestions.append(
                        f"Sturmschutz wurde {storm_count}x in letzter Zeit ausgelöst. "
                        f"Vorschlag: storm_wind_speed von {storm_speed} auf {storm_speed + 5} km/h erhöhen?"
                    )

            for suggestion in suggestions:
                await self._notify(
                    "learning_suggestion",
                    LOW,
                    {
                        "message": suggestion,
                        "suggestion": True,
                    },
                )
        except Exception as e:
            logger.debug("Threshold-Suggestion Fehler: %s", e)

    # ------------------------------------------------------------------
    # Routine-Abweichungserkennung
    # ------------------------------------------------------------------

    async def _run_routine_deviation_loop(self):
        """Prueft periodisch ob Personen ungewoehnlich spaet abwesend sind."""
        await asyncio.sleep(600)  # 10 Min Startup-Delay
        logger.info("Routine-Deviation-Loop gestartet")

        while self._running:
            try:
                hour = datetime.now(_LOCAL_TZ).hour
                if 17 <= hour <= 22:
                    # Abwesende Personen ermitteln
                    household = yaml_config.get("household", {}).get("members", [])
                    away_persons = []
                    for member in household:
                        name = member.get("name", "")
                        ha_entity = member.get("ha_entity", "")
                        if name and ha_entity:
                            try:
                                state = await self.brain.ha.get_state(ha_entity)
                                if state and state.get("state") == "not_home":
                                    away_persons.append(name)
                            except Exception as e:
                                logger.debug(
                                    "Personen-Status-Abfrage fehlgeschlagen fuer %s: %s",
                                    name,
                                    e,
                                )
                                continue

                    if away_persons:
                        anticipation = getattr(self.brain, "anticipation", None)
                        if anticipation:
                            deviations = await anticipation.check_routine_deviation(
                                away_persons
                            )
                            for dev in deviations:
                                person = dev["person"]
                                cooldown_key = f"mha:routine_deviation:{person}"
                                redis = getattr(self.brain.memory, "redis", None)
                                if redis:
                                    already = await redis.get(cooldown_key)
                                    if already:
                                        continue
                                    await redis.setex(cooldown_key, 86400, "1")

                                await self._notify(
                                    "routine_deviation",
                                    LOW,
                                    {
                                        "message": f"{person} ist normalerweise um {dev['expected_time']} Uhr zu Hause, "
                                        f"heute {dev['delay_minutes']} Minuten spaeter als ueblich.",
                                        "person": person,
                                    },
                                )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Routine-Deviation Fehler: %s", e)

            await asyncio.sleep(1800)  # Alle 30 Minuten pruefen

    # ------------------------------------------------------------------
    # Szenen-Scheduler: Cron-basierte Szenen-Aktivierung
    # ------------------------------------------------------------------

    @staticmethod
    def _cron_matches_now(cron_expr: str, now: datetime) -> bool:
        """Prueft ob ein Cron-Ausdruck auf die aktuelle Minute passt.

        Format: "minute hour day_of_month month day_of_week"
        Beispiel: "0 20 * * 5" = Freitag 20:00
        Unterstuetzt: Zahlen, *, Kommalisten (1,3,5), Bereiche (1-5)
        """
        try:
            parts = cron_expr.strip().split()
            if len(parts) != 5:
                return False

            def _matches(field: str, value: int) -> bool:
                if field == "*":
                    return True
                for part in field.split(","):
                    if "-" in part:
                        lo, hi = part.split("-", 1)
                        if int(lo) <= value <= int(hi):
                            return True
                    elif part.startswith("*/"):
                        step = int(part[2:])
                        if step > 0 and value % step == 0:
                            return True
                    elif int(part) == value:
                        return True
                return False

            minute, hour, dom, month, dow = parts
            return (
                _matches(minute, now.minute)
                and _matches(hour, now.hour)
                and _matches(dom, now.day)
                and _matches(month, now.month)
                and _matches(dow, now.isoweekday() % 7)  # 0=So, 1=Mo, ..., 6=Sa
            )
        except (ValueError, TypeError):
            return False

    async def _run_calendar_trigger_loop(self):
        """MCU Sprint 3: Prueft alle 15min auf anstehende Kalender-Events.

        Sendet Vorbereitungsvorschlaege 10-30min vor Events als MEDIUM-Priority.
        """
        await asyncio.sleep(180)  # 3 Min Startup-Delay
        logger.info("Calendar-Trigger-Loop gestartet")

        while self._running:
            try:
                if not self._is_quiet_hours():
                    await self._check_calendar_triggers()
            except Exception as e:
                logger.debug("Calendar-Trigger Check Fehler: %s", e)

            await asyncio.sleep(900)  # Alle 15 Minuten

    async def _check_calendar_triggers(self):
        """Prueft Kalender auf Events in 10-30 Minuten und schlaegt Vorbereitungen vor."""
        if not hasattr(self.brain, "calendar_intelligence"):
            return

        cal = self.brain.calendar_intelligence
        if not cal:
            return

        try:
            # Get upcoming events from HA calendar
            states = await self.brain.ha.get_states()
            if not states:
                return

            now = datetime.now(timezone.utc)
            upcoming = []

            for s in states:
                eid = s.get("entity_id", "")
                if not eid.startswith("calendar."):
                    continue
                attrs = s.get("attributes", {})
                start_time = attrs.get("start_time", "")
                summary = attrs.get("message", "") or attrs.get("friendly_name", "")
                if not start_time or not summary:
                    continue

                try:
                    event_start = datetime.fromisoformat(
                        start_time.replace("Z", "+00:00")
                    )
                    delta = (event_start - now).total_seconds() / 60
                    if 10 <= delta <= 30:
                        upcoming.append(
                            {
                                "summary": summary,
                                "minutes": int(delta),
                                "entity_id": eid,
                            }
                        )
                except (ValueError, TypeError):
                    continue

            if not upcoming:
                return

            # Deduplicate: Max 1 notification per event per day
            for event in upcoming[:2]:
                _dedup_key = f"mha:cal_trigger:{event['summary'][:30]}"
                if self.brain.memory.redis:
                    already = await self.brain.memory.redis.get(_dedup_key)
                    if already:
                        continue
                    await self.brain.memory.redis.set(_dedup_key, "1", ex=86400)

                title = get_person_title()
                msg = (
                    f"{title}, {event['summary']} in {event['minutes']} Minuten. "
                    f"Soll ich etwas vorbereiten?"
                )
                await self._deliver(
                    msg,
                    event_type="calendar_preparation",
                    urgency=MEDIUM,
                    delivery_method="tts_quiet",
                    volume=0.6,
                )
                logger.info(
                    "Calendar-Trigger: %s in %d min",
                    event["summary"][:50],
                    event["minutes"],
                )

        except Exception as e:
            logger.debug("Calendar-Trigger Fehler: %s", e)

    async def _run_scene_schedule_loop(self):
        """Prueft jede Minute ob geplante Szenen aktiviert werden muessen."""
        await asyncio.sleep(120)  # 2 Min Startup-Delay
        logger.info("Scene-Schedule-Loop gestartet")

        while self._running:
            try:
                # Szenen mit aktiviertem Schedule vom Add-on laden
                scenes = await self.brain.ha.mindhome_get("/api/scenes")
                if not isinstance(scenes, list):
                    await asyncio.sleep(60)
                    continue

                now = datetime.now(_LOCAL_TZ)
                for scene in scenes:
                    if not scene.get("schedule_enabled"):
                        continue
                    cron = scene.get("schedule_cron", "")
                    if not cron:
                        continue

                    scene_id = scene.get("id")
                    scene_name = scene.get("name_de", f"Szene {scene_id}")

                    if self._cron_matches_now(cron, now):
                        # Cooldown: Pro Szene maximal 1x pro Stunde (verhindert Doppel-Trigger)
                        cooldown_key = f"mha:scene_schedule:{scene_id}"
                        redis = getattr(self.brain.memory, "redis", None)
                        if redis:
                            already = await redis.get(cooldown_key)
                            if already:
                                continue
                            await redis.setex(cooldown_key, 3600, "1")

                        # Szene aktivieren via Add-on API
                        result = await self.brain.ha.mindhome_post(
                            f"/api/scenes/{scene_id}/activate", {}
                        )
                        success = isinstance(result, dict) and result.get("success")
                        if success:
                            logger.info(
                                "Szene '%s' (ID %s) per Schedule aktiviert [%s]",
                                scene_name,
                                scene_id,
                                cron,
                            )
                            await self._notify(
                                "scene_scheduled",
                                LOW,
                                {
                                    "entity": scene_name,
                                    "message": f"Geplante Szene '{scene_name}' aktiviert",
                                    "scene_id": scene_id,
                                },
                            )
                        else:
                            logger.warning(
                                "Szene '%s' (ID %s) Schedule-Aktivierung fehlgeschlagen",
                                scene_name,
                                scene_id,
                            )

                # Proaktive Szenen-Vorschlaege: Favoriten zur passenden Zeit vorschlagen
                # Nur alle 30 Min pruefen, und nur wenn Szene in letzten 7 Tagen
                # zur aehnlichen Uhrzeit (+/- 30 Min) aktiviert wurde
                if now.minute % 30 == 0:
                    await self._check_scene_suggestions(scenes, now)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Scene-Schedule Fehler: %s", e)

            await asyncio.sleep(60)  # Jede Minute pruefen

    async def _check_scene_suggestions(self, scenes: list, now: datetime):
        """Schlaegt Szenen vor die regelmaessig zur aktuellen Zeit aktiviert werden."""
        try:
            for scene in scenes:
                if not scene.get("is_favorite") and scene.get("frequency", 0) < 3:
                    continue  # Nur relevante Szenen (Favoriten oder haeufig genutzt)

                last_activated = scene.get("last_activated")
                if not last_activated:
                    continue

                scene_id = scene.get("id")
                scene_name = scene.get("name_de", f"Szene {scene_id}")

                # Zeitfenster-Check: Wurde die Szene regelmaessig um diese Uhrzeit genutzt?
                try:
                    if isinstance(last_activated, str):
                        last_dt = datetime.fromisoformat(
                            last_activated.replace("Z", "+00:00")
                        )
                    else:
                        continue
                    # Nur vorschlagen wenn letzte Aktivierung < 7 Tage her
                    # last_dt in lokale Zeitzone konvertieren (beide aware halten)
                    last_local = last_dt.astimezone(_LOCAL_TZ)
                    days_ago = (now - last_local).days
                    if days_ago > 7:
                        continue
                    # Uhrzeitvergleich: Aktivierungszeit +/- 30 Min zur aktuellen Zeit?
                    last_minutes = last_local.hour * 60 + last_local.minute
                    now_minutes = now.hour * 60 + now.minute
                    if abs(last_minutes - now_minutes) > 30:
                        continue
                except (ValueError, TypeError):
                    continue

                # Cooldown: Pro Szene 1x am Tag vorschlagen
                cooldown_key = f"mha:scene_suggest:{scene_id}"
                redis = getattr(self.brain.memory, "redis", None)
                if redis:
                    already = await redis.get(cooldown_key)
                    if already:
                        continue
                    await redis.setex(cooldown_key, 86400, "1")

                logger.info(
                    "Szenen-Vorschlag: '%s' (zuletzt %s)", scene_name, last_activated
                )
                await self._notify(
                    "scene_suggested",
                    LOW,
                    {
                        "entity": scene_name,
                        "message": f"Soll ich '{scene_name}' aktivieren? Du nutzt sie oft um diese Zeit.",
                        "scene_id": scene_id,
                    },
                )

        except Exception as e:
            logger.debug("Scene-Suggestion Fehler: %s", e)

    # ------------------------------------------------------------------
    # Konfigurations-Assistent
    # ------------------------------------------------------------------

    async def get_cover_config_help(self, question: str = "") -> str:
        """Konfigurations-Assistent: Beantwortet Fragen zur Cover-Konfiguration.

        Kann vom LLM aufgerufen werden wenn der Nutzer nach Cover-Einstellungen fragt.
        """
        try:
            cover_cfg = yaml_config.get("seasonal_actions", {}).get(
                "cover_automation", {}
            )
            profiles = self._load_cover_profiles()
            rp_data = _get_room_profiles_cached()
            markise_cfg = rp_data.get("markisen", {})

            config_summary = []
            config_summary.append("=== Cover-Automation Konfiguration ===")
            config_summary.append(
                f"Wetter-Schutz: {'aktiv' if cover_cfg.get('weather_protection', True) else 'inaktiv'}"
            )
            config_summary.append(
                f"Sonnenschutz-Temperatur: {cover_cfg.get('heat_protection_temp', 26)}°C"
            )
            config_summary.append(
                f"Sturm-Windgeschwindigkeit: {cover_cfg.get('storm_wind_speed', 50)} km/h"
            )
            config_summary.append(
                f"Hysterese Wind: {cover_cfg.get('hysteresis_wind', 10)} km/h"
            )
            config_summary.append(
                f"Hysterese Temperatur: {cover_cfg.get('hysteresis_temp', 2)}°C"
            )
            config_summary.append(
                f"Sun-Tracking: {'aktiv' if cover_cfg.get('sun_tracking', True) else 'inaktiv'}"
            )
            config_summary.append(
                f"Nacht-Isolierung: {'aktiv' if cover_cfg.get('night_insulation', True) else 'inaktiv'}"
            )
            config_summary.append(
                f"Frost-Schutz Temp: {cover_cfg.get('frost_protection_temp', 3)}°C"
            )
            config_summary.append(
                f"Morgen-Sonnencheck: {'aktiv' if cover_cfg.get('wakeup_sun_check', True) else 'inaktiv'}"
            )
            config_summary.append(
                f"Graduelles Öffnen: {'aktiv' if cover_cfg.get('gradual_morning', False) else 'inaktiv'}"
            )
            config_summary.append(
                f"Wellen-Öffnen: {'aktiv' if cover_cfg.get('wave_open', False) else 'inaktiv'}"
            )
            config_summary.append(
                f"Heizungs-Integration: {'aktiv' if cover_cfg.get('heating_integration', False) else 'inaktiv'}"
            )
            config_summary.append(
                f"Dry-Run: {'aktiv' if cover_cfg.get('dry_run', False) else 'inaktiv'}"
            )
            config_summary.append(
                f"Markisen Wind-Einfahrt: {markise_cfg.get('wind_retract_speed', 40)} km/h"
            )
            config_summary.append(
                f"Markisen Regen-Einfahrt: {'ja' if markise_cfg.get('rain_retract', True) else 'nein'}"
            )
            config_summary.append(f"\n{len(profiles)} Cover-Profile konfiguriert:")
            for p in profiles[:10]:
                config_summary.append(
                    f"  - {p.get('entity_id')}: Raum={p.get('room', '?')}, "
                    f"auto={'ja' if p.get('allow_auto') else 'nein'}, "
                    f"Azimut {p.get('sun_exposure_start', 0)}-{p.get('sun_exposure_end', 360)}°"
                )

            return "\n".join(config_summary)
        except Exception as e:
            return f"Konfigurations-Fehler: {e}"

    # ------------------------------------------------------------------
    # Debug-Assistent: "Warum ist mein Rollladen zu?"
    # ------------------------------------------------------------------

    async def debug_cover_state(self, entity_id: str = "") -> str:
        """Erklärt warum ein Cover in seinem aktuellen Zustand ist.

        Kombiniert: Reason-State aus Redis, State-Machine History,
        aktuelle Sensor-Werte, und Cover-Profil-Konfiguration.
        """
        try:
            import json as _json

            parts = []

            if not entity_id:
                # Wenn keine Entity angegeben: alle Cover mit Reason auflisten
                states = await self.brain.ha.get_states()
                covers = [
                    s
                    for s in (states or [])
                    if s.get("entity_id", "").startswith("cover.")
                ]
                for c in covers[:15]:
                    eid = c.get("entity_id")
                    name = c.get("attributes", {}).get("friendly_name", eid)
                    pos = c.get("attributes", {}).get("current_position", "?")
                    reason = await self.get_cover_reason(eid)
                    reason_text = (
                        reason.get("reason", "kein Grund gespeichert")
                        if reason
                        else "kein Grund gespeichert"
                    )
                    parts.append(f"- {name}: Position {pos}% — {reason_text}")
                return (
                    "Cover-Status:\n" + "\n".join(parts)
                    if parts
                    else "Keine Cover gefunden."
                )

            # Einzelnes Cover analysieren
            states = await self.brain.ha.get_states()
            state = next(
                (s for s in (states or []) if s.get("entity_id") == entity_id), None
            )
            if not state:
                return f"Cover {entity_id} nicht gefunden."

            name = state.get("attributes", {}).get("friendly_name", entity_id)
            pos = state.get("attributes", {}).get("current_position", "?")
            parts.append(f"=== {name} ({entity_id}) ===")
            parts.append(f"Position: {pos}%")

            # Reason-State
            reason = await self.get_cover_reason(entity_id)
            if reason:
                parts.append(f"Letzter Grund: {reason.get('reason', '?')}")
                parts.append(f"Zeitpunkt: {reason.get('timestamp', '?')}")
            else:
                parts.append(
                    "Kein Grund gespeichert (manuell oder vor Reason-Tracking)"
                )

            # State-Machine
            if entity_id in self._cover_states:
                cs = self._cover_states[entity_id]
                parts.append(
                    f"State-Machine: {cs.state} (seit {cs.since.strftime('%H:%M')})"
                )
                if cs.history:
                    parts.append("Letzte Übergänge:")
                    for ts, from_s, to_s in cs.history[-5:]:
                        parts.append(f"  {ts}: {from_s} → {to_s}")

            # Cover-Profil
            profiles = self._load_cover_profiles()
            profile = next(
                (p for p in profiles if p.get("entity_id") == entity_id), None
            )
            if profile:
                parts.append(
                    f"Profil: Raum={profile.get('room', '?')}, "
                    f"Azimut {profile.get('sun_exposure_start', 0)}-{profile.get('sun_exposure_end', 360)}°, "
                    f"auto={'ja' if profile.get('allow_auto') else 'nein'}"
                )

            # Aktuelle Checks
            _redis = getattr(getattr(self.brain, "memory", None), "redis", None)
            if _redis:
                manual = await _redis.get(f"mha:cover:manual_override:{entity_id}")
                if manual:
                    ttl = await _redis.ttl(f"mha:cover:manual_override:{entity_id}")
                    parts.append(f"⚠ Manueller Override aktiv (noch {ttl}s)")
                power_lock = await _redis.get(f"mha:cover:power_close:{entity_id}")
                if power_lock:
                    parts.append("⚠ Power-Close Lock aktiv")
                acting = await _redis.get(f"mha:cover:jarvis_acting:{entity_id}")
                if acting:
                    parts.append("ℹ Jarvis-Acting Flag aktiv")
                anomaly = await _redis.get(f"mha:cover:anomaly:{entity_id}")
                if anomaly:
                    parts.append(f"⚠ {anomaly} Anomalien in letzter Zeit")
                rate = await _redis.get(f"mha:cover:rate_limit:{entity_id}")
                if rate:
                    parts.append(
                        f"Rate-Limit: {rate}/{self._COVER_RATE_LIMIT_MAX} Aktionen/h"
                    )

            # Fenster-Status
            if self._is_window_open(states, entity_id):
                parts.append("⚠ Fenster ist offen — Schließen blockiert")

            return "\n".join(parts)
        except Exception as e:
            return f"Debug-Fehler: {e}"
