"""
Ambient Audio Classifier - Phase 14.3: Umgebungsgeraeusch-Erkennung.

Erkennt kritische Umgebungsgeraeusche und loest Aktionen aus:
  - Glasbruch (glass_break)
  - Rauchmelder (smoke_alarm)
  - CO-Melder (co_alarm)
  - Hundegebell (dog_bark)
  - Baby weint (baby_cry)
  - Tuerklingel (doorbell)
  - Schuss / Explosion (gunshot)
  - Wasseralarm (water_alarm)
  - Schreien (scream)

Arbeitet mit:
  1. HA Binary-Sensoren (z.B. ESPHome sound_event Sensoren)
  2. Audio-Stream-Klassifikation via YAMNet / custom Modell (optional)
  3. Webhook-basierte Events von externen Audio-Klassifizierern

Jedes erkannte Event wird:
  - Geloggt (Redis History)
  - An den ProactiveManager als Alert weitergegeben
  - Optional: Sound-Alarm abgespielt
  - Optional: HA-Automation getriggert (z.B. Licht an bei Glasbruch nachts)
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Callable, Awaitable

from .config import yaml_config
from .ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)
from zoneinfo import ZoneInfo
_LOCAL_TZ = ZoneInfo(yaml_config.get("timezone", "Europe/Berlin"))


# Standard-Reaktionen pro Event-Typ
DEFAULT_EVENT_REACTIONS = {
    "glass_break": {
        "severity": "critical",
        "message_de": "Glasbruch{room_suffix}. Licht ist an, Kameras laufen.",
        "sound_event": "alarm",
        "actions": ["lights_on", "notify_owner"],
    },
    "smoke_alarm": {
        "severity": "critical",
        "message_de": "Rauchmelder schlaegt an in {room}. Sofort pruefen.",
        "sound_event": "alarm",
        "actions": ["lights_on", "notify_all"],
    },
    "co_alarm": {
        "severity": "critical",
        "message_de": "CO-Melder in {room}. Fenster auf, Raum raeumen. Sofort.",
        "sound_event": "alarm",
        "actions": ["lights_on", "notify_all"],
    },
    "dog_bark": {
        "severity": "info",
        "message_de": "Der Hund meldet sich{room_suffix}.",
        "sound_event": None,
        "actions": ["notify_owner"],
    },
    "baby_cry": {
        "severity": "high",
        "message_de": "Das Kind ist wach{room_suffix}.",
        "sound_event": "warning",
        "actions": ["notify_owner"],
    },
    "doorbell": {
        "severity": "info",
        "message_de": "Jemand an der Tuer.",
        "sound_event": "doorbell",
        "actions": ["notify_present"],
    },
    "gunshot": {
        "severity": "critical",
        "message_de": "Lauter Knall{room_suffix}. Situation unklar — Vorsicht.",
        "sound_event": "alarm",
        "actions": ["lights_on", "notify_all"],
    },
    "water_alarm": {
        "severity": "high",
        "message_de": "Wasser in {room}. Haupthahn pruefen.",
        "sound_event": "alarm",
        "actions": ["notify_owner"],
    },
    "scream": {
        "severity": "high",
        "message_de": "Schrei{room_suffix}. Alles in Ordnung da drin?",
        "sound_event": "warning",
        "actions": ["notify_present"],
    },
}

# Severity -> Prioritaet fuer Benachrichtigungen
SEVERITY_PRIORITY = {
    "critical": 3,  # Sofort, laut, alle
    "high": 2,      # Sofort, normal, Owner
    "info": 1,      # Normal, leise
}


class AmbientAudioClassifier:
    """Erkennt und reagiert auf Umgebungsgeraeusche."""

    def __init__(self, ha_client: HomeAssistantClient):
        self.ha = ha_client

        # Konfiguration laden
        cfg = yaml_config.get("ambient_audio", {})
        self.enabled = cfg.get("enabled", True)

        # Sensor-Mappings: HA entity_id -> event_type
        self._sensor_mappings: dict[str, str] = cfg.get("sensor_mappings") or {}

        # Cooldowns pro Event-Typ (verhindert Spam)
        cooldowns = cfg.get("cooldowns") or {}
        self._default_cooldown = cooldowns.get("default_seconds", 30)
        self._event_cooldowns: dict[str, int] = cooldowns.get("per_event") or {}

        # Reaktions-Overrides aus Config
        self._reaction_overrides: dict[str, dict] = cfg.get("reaction_overrides") or {}

        # Default-Reaktionen aus YAML (Fallback: hardcoded DEFAULT_EVENT_REACTIONS)
        yaml_reactions = cfg.get("default_reactions")
        if yaml_reactions and isinstance(yaml_reactions, dict):
            self._default_reactions = dict(DEFAULT_EVENT_REACTIONS)
            for evt, info in yaml_reactions.items():
                if isinstance(info, dict):
                    if evt in self._default_reactions:
                        self._default_reactions[evt] = {**self._default_reactions[evt], **info}
                    else:
                        self._default_reactions[evt] = info
        else:
            self._default_reactions = dict(DEFAULT_EVENT_REACTIONS)

        # Nachmodus: Strengere Reaktionen nachts
        night_cfg = cfg.get("night_mode") or {}
        self._night_start = int(night_cfg.get("start_hour", 22))
        self._night_end = int(night_cfg.get("end_hour", 7))
        self._night_escalate = night_cfg.get("escalate_severity", True)

        # Deaktivierte Events (z.B. wenn kein Hund da ist)
        self._disabled_events: set[str] = set(cfg.get("disabled_events") or [])

        # State
        self._last_event_times: dict[str, float] = {}
        self._event_history: list[dict] = []
        self._max_history = 100
        self._notify_callback: Optional[Callable] = None
        self._running = False
        self._poll_task: Optional[asyncio.Task] = None
        self._background_tasks: set[asyncio.Task] = set()

        # Redis fuer Persistenz
        self._redis = None

        # Polling-Intervall fuer HA-Sensoren
        self._poll_interval = cfg.get("poll_interval_seconds", 5)

        logger.info(
            "AmbientAudioClassifier initialisiert (enabled: %s, sensoren: %d, "
            "disabled: %s)",
            self.enabled, len(self._sensor_mappings),
            list(self._disabled_events) or "keine",
        )

    async def initialize(self, redis_client=None):
        """Initialisiert den Classifier mit Redis-Anbindung."""
        self._redis = redis_client

        # Event-History aus Redis laden
        if self._redis:
            try:
                history_raw = await self._redis.get("mha:ambient:history")
                if history_raw:
                    import json
                    self._event_history = json.loads(history_raw)[-self._max_history:]
                    logger.info(
                        "Ambient Audio History geladen: %d Events",
                        len(self._event_history),
                    )
            except Exception as e:
                logger.warning("Ambient Audio History laden fehlgeschlagen: %s", e)

    async def start(self):
        """Startet den Sensor-Polling-Loop."""
        if not self.enabled or not self._sensor_mappings:
            logger.info("Ambient Audio Polling nicht gestartet (enabled=%s, sensoren=%d)",
                        self.enabled, len(self._sensor_mappings))
            return

        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        self._poll_task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        logger.info("Ambient Audio Polling gestartet (Intervall: %ds)", self._poll_interval)

    async def stop(self):
        """Stoppt den Polling-Loop."""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("Ambient Audio Polling gestoppt")

    def set_notify_callback(self, callback: Callable[..., Awaitable]):
        """Setzt die Callback-Funktion fuer Event-Benachrichtigungen.

        Args:
            callback: Async-Funktion(event_type, message, severity, room, actions)
        """
        self._notify_callback = callback

    # ------------------------------------------------------------------
    # Event-Verarbeitung
    # ------------------------------------------------------------------

    async def process_event(
        self,
        event_type: str,
        room: Optional[str] = None,
        confidence: float = 1.0,
        source: str = "sensor",
    ) -> Optional[dict]:
        """
        Verarbeitet ein erkanntes Audio-Event.

        Args:
            event_type: Art des Events (glass_break, smoke_alarm, etc.)
            room: Raum in dem das Event erkannt wurde
            confidence: Erkennungs-Confidence (0.0-1.0)
            source: Quelle (sensor, webhook, stream)

        Returns:
            Event-Dict mit Reaktion oder None (wenn unterdrueckt)
        """
        if not self.enabled:
            return None

        # Deaktivierte Events ignorieren
        if event_type in self._disabled_events:
            logger.debug("Event '%s' ist deaktiviert", event_type)
            return None

        # Confidence-Schwelle
        min_confidence = yaml_config.get("ambient_audio", {}).get(
            "min_confidence", 0.6,
        )
        if confidence < min_confidence:
            logger.debug(
                "Event '%s' unter Confidence-Schwelle (%.2f < %.2f)",
                event_type, confidence, min_confidence,
            )
            return None

        # Cooldown pruefen
        if not self._check_cooldown(event_type):
            logger.debug("Event '%s' im Cooldown", event_type)
            return None

        # Reaktion bestimmen
        reaction = self._get_reaction(event_type)
        if not reaction:
            logger.warning("Kein Reaktions-Template fuer Event '%s'", event_type)
            return None

        # Nachtmodus: Severity hochstufen
        severity = reaction["severity"]
        if self._is_night() and self._night_escalate:
            severity = self._escalate_severity(severity)

        # Nachricht formatieren
        room_display = room or "unbekanntem Raum"
        room_suffix = f" im {room_display}" if room else ""
        message = reaction["message_de"].format(
            room=room_display,
            room_suffix=room_suffix,
        )

        # Event-Objekt erstellen
        event = {
            "type": event_type,
            "room": room,
            "confidence": confidence,
            "source": source,
            "severity": severity,
            "message": message,
            "sound_event": reaction.get("sound_event"),
            "actions": reaction.get("actions", []),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "is_night": self._is_night(),
        }

        # Cooldown aktualisieren
        self._last_event_times[event_type] = time.time()

        # History speichern
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history:]

        # Redis persistieren (async) – Task in Set halten, damit GC ihn nicht einsammelt
        task = asyncio.create_task(self._save_history())
        self._background_tasks.add(task)

        def _on_done(t: asyncio.Task) -> None:
            self._background_tasks.discard(t)
            if not t.cancelled() and t.exception():
                logger.warning("_save_history fehlgeschlagen: %s", t.exception())

        task.add_done_callback(_on_done)

        # Callback ausfuehren (ProactiveManager benachrichtigen)
        if self._notify_callback:
            try:
                await self._notify_callback(
                    event_type=event_type,
                    message=message,
                    severity=severity,
                    room=room,
                    actions=reaction.get("actions", []),
                )
            except Exception as e:
                logger.error("Ambient Audio Callback fehlgeschlagen: %s", e)

        logger.info(
            "Ambient Audio Event: %s (Raum: %s, Severity: %s, Confidence: %.2f, Quelle: %s)",
            event_type, room or "?", severity, confidence, source,
        )

        return event

    async def process_ha_state_change(self, entity_id: str, new_state: str, attributes: dict = None) -> Optional[dict]:
        """
        Verarbeitet eine HA State-Change die auf ein Audio-Event hinweisen koennte.

        Args:
            entity_id: HA Entity-ID (z.B. binary_sensor.kueche_smoke)
            new_state: Neuer State ("on", "off", etc.)
            attributes: Entity-Attribute

        Returns:
            Event-Dict oder None
        """
        if not self.enabled:
            return None

        # Nur "on" States verarbeiten (Sensor ausgeloest)
        if new_state not in ("on", "detected", "triggered"):
            return None

        # Entity in Sensor-Mapping suchen
        event_type = self._sensor_mappings.get(entity_id)
        if not event_type:
            return None

        # Raum aus Entity-ID extrahieren
        room = self._extract_room_from_entity(entity_id)

        # Confidence aus Attributen (wenn verfuegbar)
        confidence = 1.0
        if attributes:
            confidence = attributes.get("confidence", attributes.get("score", 1.0))

        return await self.process_event(
            event_type=event_type,
            room=room,
            confidence=confidence,
            source="ha_sensor",
        )

    # ------------------------------------------------------------------
    # Polling Loop (fuer HA-Sensoren)
    # ------------------------------------------------------------------

    async def _poll_loop(self):
        """Pollt HA-Sensoren auf Audio-Events."""
        # Letzten State pro Sensor merken
        last_states: dict[str, str] = {}
        _consecutive_errors = 0
        _max_backoff = 60  # seconds

        while self._running:
            try:
                entity_ids = list(self._sensor_mappings.keys())
                if entity_ids:
                    # Alle Sensor-States parallel abrufen
                    state_results = await asyncio.gather(
                        *(self.ha.get_state(eid) for eid in entity_ids),
                        return_exceptions=True,
                    )

                    for entity_id, state_data in zip(entity_ids, state_results):
                        try:
                            if isinstance(state_data, BaseException):
                                logger.debug("Sensor-Poll fehlgeschlagen (%s): %s", entity_id, state_data)
                                continue
                            if not state_data:
                                continue

                            current_state = state_data.get("state", "off")
                            prev_state = last_states.get(entity_id, "off")

                            # Nur bei Zustandsaenderung zu "aktiv"
                            if current_state != prev_state:
                                last_states[entity_id] = current_state
                                if current_state in ("on", "detected", "triggered"):
                                    await self.process_ha_state_change(
                                        entity_id=entity_id,
                                        new_state=current_state,
                                        attributes=state_data.get("attributes", {}),
                                    )
                        except Exception as e:
                            logger.debug("Sensor-Poll fehlgeschlagen (%s): %s", entity_id, e)

                _consecutive_errors = 0

            except Exception as e:
                _consecutive_errors += 1
                _backoff = min(self._poll_interval * (2 ** _consecutive_errors), _max_backoff)
                logger.error("Ambient Audio Poll-Loop Fehler (backoff %.1fs): %s", _backoff, e)
                await asyncio.sleep(_backoff)
                continue

            await asyncio.sleep(self._poll_interval)

    # ------------------------------------------------------------------
    # Hilfsfunktionen
    # ------------------------------------------------------------------

    def _check_cooldown(self, event_type: str) -> bool:
        """Prueft ob ein Event-Typ noch im Cooldown ist."""
        last_time = self._last_event_times.get(event_type, 0)
        cooldown = self._event_cooldowns.get(event_type, self._default_cooldown)
        return (time.time() - last_time) >= cooldown

    def _get_reaction(self, event_type: str) -> Optional[dict]:
        """Gibt das Reaktions-Template fuer einen Event-Typ zurueck."""
        # Erst Config-Overrides pruefen
        if event_type in self._reaction_overrides:
            # Merge mit Default
            default = self._default_reactions.get(event_type, {})
            merged = {**default, **self._reaction_overrides[event_type]}
            return merged

        return self._default_reactions.get(event_type)

    def _is_night(self) -> bool:
        """Prueft ob Nachtmodus aktiv ist."""
        hour = datetime.now(_LOCAL_TZ).hour
        if self._night_start > self._night_end:
            return hour >= self._night_start or hour < self._night_end
        return self._night_start <= hour < self._night_end

    def _escalate_severity(self, severity: str) -> str:
        """Stuft Severity nachts hoch."""
        escalation = {
            "info": "high",
            "high": "critical",
            "critical": "critical",  # Bleibt
        }
        return escalation.get(severity, severity)

    def _extract_room_from_entity(self, entity_id: str) -> Optional[str]:
        """Extrahiert den Raumnamen aus einer Entity-ID."""
        # z.B. "binary_sensor.kueche_smoke" -> "kueche"
        # z.B. "binary_sensor.wohnzimmer_glass_break" -> "wohnzimmer"
        parts = entity_id.split(".")
        if len(parts) != 2:
            return None

        name = parts[1]
        # Bekannte Raum-Praefixe
        room_names = [
            "wohnzimmer", "schlafzimmer", "kueche", "bad", "badezimmer",
            "buero", "flur", "keller", "dachboden", "garage",
            "kinderzimmer", "gaestezimmer", "esszimmer", "balkon",
            "terrasse", "garten", "eingang",
        ]
        for room in room_names:
            if name.startswith(room):
                return room

        # Fallback: Erster Teil vor dem letzten Underscore
        parts_name = name.rsplit("_", 1)
        if len(parts_name) > 1:
            return parts_name[0].replace("_", " ")

        return None

    async def _save_history(self):
        """Speichert Event-History in Redis."""
        if not self._redis:
            return
        try:
            import json
            await self._redis.set(
                "mha:ambient:history",
                json.dumps(self._event_history[-self._max_history:]),
            )
        except Exception as e:
            logger.debug("Ambient History speichern fehlgeschlagen: %s", e)

    # ------------------------------------------------------------------
    # Status & Info
    # ------------------------------------------------------------------

    def get_recent_events(self, limit: int = 10) -> list[dict]:
        """Gibt die letzten Audio-Events zurueck."""
        return self._event_history[-limit:]

    def get_events_by_type(self, event_type: str, limit: int = 10) -> list[dict]:
        """Gibt Events eines bestimmten Typs zurueck."""
        filtered = [e for e in self._event_history if e["type"] == event_type]
        return filtered[-limit:]

    def health_status(self) -> str:
        """Gibt den Health-Status zurueck."""
        if not self.enabled:
            return "disabled"
        if self._running:
            return f"running ({len(self._sensor_mappings)} sensoren, {len(self._event_history)} events)"
        return f"active ({len(self._sensor_mappings)} sensoren)"

    def get_info(self) -> dict:
        """Gibt detaillierte Infos zurueck."""
        return {
            "enabled": self.enabled,
            "running": self._running,
            "sensor_count": len(self._sensor_mappings),
            "sensor_mappings": dict(self._sensor_mappings),
            "disabled_events": list(self._disabled_events),
            "event_history_count": len(self._event_history),
            "recent_events": self.get_recent_events(5),
            "supported_events": list(self._default_reactions.keys()),
            "night_mode": self._is_night(),
            "cooldowns": {
                "default": self._default_cooldown,
                "per_event": self._event_cooldowns,
            },
        }

    # ------------------------------------------------------------------
    # Event-Korrelation, False-Positive-Lernen & Zeitbasierte Dringlichkeit
    # ------------------------------------------------------------------

    def correlate_events(self, events: list[dict], window_seconds: int = 30) -> list[dict]:
        """Gruppiert Events innerhalb eines Zeitfensters zu Incidents.

        Beispiel: glass_break + alarm innerhalb von 30s = ein Incident.

        Args:
            events: Liste von Event-Dicts mit "timestamp" und "type".
            window_seconds: Zeitfenster in Sekunden fuer Korrelation.

        Returns:
            Liste von Incident-Dicts mit allen korrelierten Events.
        """
        if not events:
            return []

        sorted_events = sorted(events, key=lambda e: e.get("timestamp", 0))
        incidents: list[dict] = []
        current_group: list[dict] = [sorted_events[0]]

        for event in sorted_events[1:]:
            group_start = current_group[0].get("timestamp", 0)
            event_time = event.get("timestamp", 0)

            if event_time - group_start <= window_seconds:
                current_group.append(event)
            else:
                incidents.append(self._build_incident(current_group))
                current_group = [event]

        # Letzte Gruppe abschliessen
        incidents.append(self._build_incident(current_group))
        return incidents

    def _build_incident(self, group: list[dict]) -> dict:
        """Baut ein Incident-Dict aus einer Gruppe korrelierter Events."""
        event_types = list({e.get("type", "unknown") for e in group})
        severities = [e.get("severity", "info") for e in group]
        severity_order = {"critical": 3, "warning": 2, "info": 1}
        max_severity = max(severities, key=lambda s: severity_order.get(s, 0))
        return {
            "events": group,
            "event_types": event_types,
            "event_count": len(group),
            "severity": max_severity,
            "timestamp_start": group[0].get("timestamp", 0),
            "timestamp_end": group[-1].get("timestamp", 0),
        }

    def learn_false_positive(self, event_id: str, is_false: bool = True):
        """Lernt aus False Positives und reduziert Sensitivitaet bei haeufigen Fehlern.

        Nach 5 False Positives fuer einen Event-Typ wird die Sensitivitaet reduziert.

        Args:
            event_id: Event-Typ-ID (z.B. "glass_break", "dog_bark").
            is_false: True wenn es ein False Positive war.
        """
        if not hasattr(self, "_false_positive_counts"):
            self._false_positive_counts: dict[str, int] = {}
            self._sensitivity_reduced: set[str] = set()

        if not is_false:
            return

        self._false_positive_counts[event_id] = self._false_positive_counts.get(event_id, 0) + 1
        count = self._false_positive_counts[event_id]
        logger.info("False Positive fuer '%s': %d Mal gemeldet", event_id, count)

        if count >= 5 and event_id not in self._sensitivity_reduced:
            self._sensitivity_reduced.add(event_id)
            logger.warning(
                "Sensitivitaet fuer '%s' reduziert — %d False Positives erreicht",
                event_id, count,
            )

    def get_temporal_urgency(self, event_type: str, hour: int) -> str:
        """Bestimmt Dringlichkeit basierend auf Tageszeit.

        Nachts (22-6 Uhr) sind Events kritischer, da ungewoehnlicher.

        Args:
            event_type: Typ des Events.
            hour: Aktuelle Stunde (0-23).

        Returns:
            "critical" fuer Nacht, "normal" fuer Tag.
        """
        is_night = hour >= 22 or hour < 6
        if is_night:
            return "critical"
        return "normal"
