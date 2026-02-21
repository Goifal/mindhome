"""
Brain Callbacks - Ausgelagerte Callback-Handler fuer AssistantBrain.

Reduziert brain.py um ~200 LOC. Alle Methoden werden als Mixin
in AssistantBrain eingebunden.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class BrainCallbacksMixin:
    """Mixin mit allen proaktiven Callback-Handlern fuer AssistantBrain.

    Erwartet dass self._speak_and_emit, self.proactive, self.executor,
    self.sound_manager etc. existieren (wird via AssistantBrain bereitgestellt).
    """

    async def _handle_timer_notification(self, alert: dict) -> None:
        """Callback fuer allgemeine Timer — meldet wenn Timer abgelaufen ist."""
        message = alert.get("message", "")
        if message:
            formatted = await self.proactive.format_with_personality(message, "medium")
            await self._speak_and_emit(formatted)
            logger.info("Timer -> Meldung: %s", formatted)

    async def _handle_learning_suggestion(self, alert: dict) -> None:
        """Callback fuer Learning Observer — schlaegt Automatisierungen vor."""
        message = alert.get("message", "")
        if message:
            formatted = await self.proactive.format_with_personality(message, "low")
            await self._speak_and_emit(formatted)
            logger.info("Learning -> Vorschlag: %s", formatted)

    async def _handle_cooking_timer(self, alert: dict) -> None:
        """Callback fuer Koch-Timer — meldet wenn Timer abgelaufen ist."""
        message = alert.get("message", "")
        if message:
            formatted = await self.proactive.format_with_personality(message, "medium")
            await self._speak_and_emit(formatted)
            logger.info("Koch-Timer -> Meldung: %s", formatted)

    async def _handle_time_alert(self, alert: dict) -> None:
        """Callback fuer TimeAwareness-Alerts — leitet an proaktive Meldung weiter."""
        message = alert.get("message", "")
        if message:
            formatted = await self.proactive.format_with_personality(message, "medium")
            await self._speak_and_emit(formatted)
            logger.info("TimeAwareness -> Meldung: %s", formatted)

    async def _handle_health_alert(self, alert_type: str, urgency: str, message: str) -> None:
        """Callback fuer Health Monitor — leitet an proaktive Meldung weiter."""
        if message:
            formatted = await self.proactive.format_with_personality(message, urgency)
            await self._speak_and_emit(formatted)
            logger.info("Health Monitor [%s/%s]: %s", alert_type, urgency, formatted)

    async def _handle_device_health_alert(self, alert: dict) -> None:
        """Callback fuer DeviceHealthMonitor — meldet Geraete-Anomalien."""
        message = alert.get("message", "")
        if message:
            formatted = await self.proactive.format_with_personality(message, "medium")
            await self._speak_and_emit(formatted)
            logger.info(
                "DeviceHealth [%s]: %s",
                alert.get("alert_type", "?"), formatted,
            )

    async def _handle_wellness_nudge(self, nudge_type: str, message: str) -> None:
        """Callback fuer Wellness Advisor — kuemmert sich um den User."""
        if message:
            formatted = await self.proactive.format_with_personality(message, "low")
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
        """Callback fuer Ambient Audio Events — reagiert auf Umgebungsgeraeusche."""
        if not message:
            return

        logger.info(
            "Ambient Audio [%s/%s]: %s (Raum: %s)",
            event_type, severity, message, room or "?",
        )

        # Sound-Alarm abspielen (wenn konfiguriert)
        from .ambient_audio import DEFAULT_EVENT_REACTIONS
        reaction = DEFAULT_EVENT_REACTIONS.get(event_type, {})
        sound_event = reaction.get("sound_event")
        if sound_event and self.sound_manager.enabled:
            await self.sound_manager.play_event_sound(sound_event, room=room)

        # HA-Aktionen ausfuehren
        if actions:
            if "lights_on" in actions and room:
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
