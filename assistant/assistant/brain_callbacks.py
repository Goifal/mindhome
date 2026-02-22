"""
Brain Callbacks - Ausgelagerte Callback-Handler fuer AssistantBrain.

Reduziert brain.py um ~200 LOC. Alle Methoden werden als Mixin
in AssistantBrain eingebunden.

F-036: Jeder Callback hat Error-Handling mit Fallback auf unformatierten Text.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# F-026: Sichere Aktionen die ohne Trust-Check ausfuehrbar sind
_SAFE_AMBIENT_ACTIONS = frozenset({"lights_on", "play_sound"})

# F-026: Aktionen die Owner-Trust benoetigen
_RESTRICTED_AMBIENT_ACTIONS = frozenset({
    "lock_door", "unlock_door", "set_alarm", "disarm_alarm",
    "open_garage", "close_garage",
})


class BrainCallbacksMixin:
    """Mixin mit allen proaktiven Callback-Handlern fuer AssistantBrain.

    Erwartet dass self._speak_and_emit, self.proactive, self.executor,
    self.sound_manager etc. existieren (wird via AssistantBrain bereitgestellt).
    """

    async def _handle_timer_notification(self, alert: dict) -> None:
        """Callback fuer allgemeine Timer/Wecker — meldet wenn Timer abgelaufen ist."""
        message = alert.get("message", "")
        room = alert.get("room") or None
        if message:
            # F-036: Error-Handling mit Fallback
            try:
                formatted = await self.proactive.format_with_personality(message, "medium")
            except Exception as e:
                logger.warning("Timer-Personality Fehler (Fallback): %s", e)
                formatted = message
            await self._speak_and_emit(formatted, room=room)
            logger.info("Timer -> Meldung: %s (Raum: %s)", formatted, room or "auto")

    async def _handle_learning_suggestion(self, alert: dict) -> None:
        """Callback fuer Learning Observer — schlaegt Automatisierungen vor."""
        message = alert.get("message", "")
        if message:
            try:
                formatted = await self.proactive.format_with_personality(message, "low")
            except Exception as e:
                logger.warning("Learning-Personality Fehler (Fallback): %s", e)
                formatted = message
            await self._speak_and_emit(formatted)
            logger.info("Learning -> Vorschlag: %s", formatted)

    async def _handle_cooking_timer(self, alert: dict) -> None:
        """Callback fuer Koch-Timer — meldet wenn Timer abgelaufen ist."""
        message = alert.get("message", "")
        if message:
            try:
                formatted = await self.proactive.format_with_personality(message, "medium")
            except Exception as e:
                logger.warning("Cooking-Personality Fehler (Fallback): %s", e)
                formatted = message
            await self._speak_and_emit(formatted)
            logger.info("Koch-Timer -> Meldung: %s", formatted)

    async def _handle_time_alert(self, alert: dict) -> None:
        """Callback fuer TimeAwareness-Alerts — leitet an proaktive Meldung weiter."""
        message = alert.get("message", "")
        if message:
            try:
                formatted = await self.proactive.format_with_personality(message, "medium")
            except Exception as e:
                logger.warning("TimeAwareness-Personality Fehler (Fallback): %s", e)
                formatted = message
            await self._speak_and_emit(formatted)
            logger.info("TimeAwareness -> Meldung: %s", formatted)

    async def _handle_health_alert(self, alert_type: str, urgency: str, message: str) -> None:
        """Callback fuer Health Monitor — leitet an proaktive Meldung weiter."""
        if message:
            try:
                formatted = await self.proactive.format_with_personality(message, urgency)
            except Exception as e:
                logger.warning("Health-Personality Fehler (Fallback): %s", e)
                formatted = message
            await self._speak_and_emit(formatted)
            logger.info("Health Monitor [%s/%s]: %s", alert_type, urgency, formatted)

    async def _handle_device_health_alert(self, alert: dict) -> None:
        """Callback fuer DeviceHealthMonitor — meldet Geraete-Anomalien."""
        message = alert.get("message", "")
        if message:
            try:
                formatted = await self.proactive.format_with_personality(message, "medium")
            except Exception as e:
                logger.warning("DeviceHealth-Personality Fehler (Fallback): %s", e)
                formatted = message
            await self._speak_and_emit(formatted)
            logger.info(
                "DeviceHealth [%s]: %s",
                alert.get("alert_type", "?"), formatted,
            )

    async def _handle_wellness_nudge(self, nudge_type: str, message: str) -> None:
        """Callback fuer Wellness Advisor — kuemmert sich um den User."""
        if message:
            try:
                formatted = await self.proactive.format_with_personality(message, "low")
            except Exception as e:
                logger.warning("Wellness-Personality Fehler (Fallback): %s", e)
                formatted = message
            await self._speak_and_emit(formatted)
            logger.info("Wellness [%s]: %s", nudge_type, formatted)

    async def _handle_ambient_audio_event(
        self,
        event_type: str,
        message: str,
        severity: str,
        room: Optional[str] = None,
        actions: Optional[list] = None,
    ) -> None:
        """Callback fuer Ambient Audio Events — reagiert auf Umgebungsgeraeusche.

        F-026: Nur sichere Aktionen (Licht, Sound) werden ohne Trust-Check
        ausgefuehrt. Sicherheitsrelevante Aktionen (Tueren, Alarm) werden
        blockiert und nur als Warnung gemeldet.
        """
        if not message:
            return

        logger.info(
            "Ambient Audio [%s/%s]: %s (Raum: %s)",
            event_type, severity, message, room or "?",
        )

        # Sound-Alarm abspielen (wenn konfiguriert)
        try:
            from .ambient_audio import DEFAULT_EVENT_REACTIONS
            reaction = DEFAULT_EVENT_REACTIONS.get(event_type, {})
            sound_event = reaction.get("sound_event")
            if sound_event and self.sound_manager.enabled:
                await self.sound_manager.play_event_sound(sound_event, room=room)
        except Exception as e:
            logger.warning("Ambient Audio Sound fehlgeschlagen: %s", e)

        # F-026: HA-Aktionen nur ausfuehren wenn sicher (kein Trust-Bypass)
        if actions:
            for action in actions:
                if action in _RESTRICTED_AMBIENT_ACTIONS:
                    logger.warning(
                        "F-026: Ambient Audio Aktion '%s' blockiert — benoetigt Owner-Trust",
                        action,
                    )
                    continue
                if action == "lights_on" and room:
                    try:
                        await self.executor.execute("set_light", {
                            "room": room,
                            "state": "on",
                            "brightness": 100,
                        })
                    except Exception as e:
                        logger.debug("Ambient Audio lights_on fehlgeschlagen: %s", e)

        # Nachricht via WebSocket + Speaker senden
        await self._speak_and_emit(message)
