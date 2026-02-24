"""
WebSocket Manager - Echtzeit-Kommunikation mit Clients.
Sendet Events wie assistant.speaking, assistant.thinking, etc.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Verwaltet aktive WebSocket-Verbindungen."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Neue Verbindung akzeptieren."""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("WebSocket verbunden (%d aktiv)", len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        """Verbindung entfernen."""
        try:
            self.active_connections.remove(websocket)
        except ValueError:
            pass
        logger.info("WebSocket getrennt (%d aktiv)", len(self.active_connections))

    async def broadcast(self, event: str, data: Optional[dict] = None):
        """Event an alle verbundenen Clients senden."""
        if not self.active_connections:
            return

        message = json.dumps({
            "event": event,
            "data": data or {},
            "timestamp": datetime.now().isoformat(),
        })

        disconnected = []
        # Snapshot-Kopie um concurrent modification zu vermeiden
        connections = list(self.active_connections)
        for connection in connections:
            try:
                await connection.send_text(message)
            except Exception:
                disconnected.append(connection)

        for conn in disconnected:
            try:
                self.active_connections.remove(conn)
            except ValueError:
                pass

    async def send_personal(self, websocket: WebSocket, event: str, data: Optional[dict] = None):
        """Event an einen bestimmten Client senden."""
        message = json.dumps({
            "event": event,
            "data": data or {},
            "timestamp": datetime.now().isoformat(),
        })
        try:
            await websocket.send_text(message)
        except Exception as e:
            logger.debug("send_personal fehlgeschlagen: %s", e)


# Globale Instanz
ws_manager = ConnectionManager()


async def emit_thinking() -> None:
    """Signalisiert: Assistant denkt nach."""
    await ws_manager.broadcast("assistant.thinking", {"status": "processing"})


async def emit_speaking(text: str, tts_data: Optional[dict] = None) -> None:
    """Signalisiert: Assistant spricht. Phase 9: Optional mit TTS-Metadaten."""
    data = {"text": text}
    if tts_data:
        data["ssml"] = tts_data.get("ssml", text)
        data["message_type"] = tts_data.get("message_type", "casual")
        data["speed"] = tts_data.get("speed", 100)
        data["volume"] = tts_data.get("volume", 0.8)
    await ws_manager.broadcast("assistant.speaking", data)


async def emit_action(function_name: str, args: dict, result: dict) -> None:
    """Signalisiert: Assistant fuehrt Aktion aus."""
    await ws_manager.broadcast("assistant.action", {
        "function": function_name,
        "args": args,
        "result": result,
    })


async def emit_listening() -> None:
    """Signalisiert: Assistant hoert zu."""
    await ws_manager.broadcast("assistant.listening", {"status": "active"})


async def emit_sound(sound_event: str, volume: float = 0.5) -> None:
    """Phase 9: Signalisiert einen Sound-Event."""
    await ws_manager.broadcast("assistant.sound", {
        "sound": sound_event,
        "volume": volume,
    })


async def emit_stream_start() -> None:
    """Signalisiert: Streaming-Antwort beginnt."""
    await ws_manager.broadcast("assistant.stream_start", {"status": "streaming"})


async def emit_stream_token(token: str) -> None:
    """Sendet ein einzelnes Token der Streaming-Antwort."""
    await ws_manager.broadcast("assistant.stream_token", {"token": token})


async def emit_stream_end(full_text: str, tts_data: Optional[dict] = None) -> None:
    """Signalisiert: Streaming-Antwort komplett."""
    data = {"text": full_text}
    if tts_data:
        data["tts"] = tts_data
    await ws_manager.broadcast("assistant.stream_end", data)


async def emit_proactive(
    text: str,
    event_type: str,
    urgency: str = "medium",
    notification_id: str = "",
):
    """Signalisiert: Proaktive Meldung (mit ID fuer Feedback-Tracking)."""
    await ws_manager.broadcast("assistant.proactive", {
        "text": text,
        "event_type": event_type,
        "urgency": urgency,
        "notification_id": notification_id,
    })


async def emit_interrupt(
    text: str,
    event_type: str,
    protocol: str = "",
    actions_taken: list[str] | None = None,
):
    """CRITICAL Interrupt — unterbricht laufende Aktionen sofort.

    Sendet zuerst ein interrupt-Signal (Client soll TTS stoppen),
    dann die eigentliche Notfall-Meldung.
    Konfigurierbar via interrupt_queue.* in settings.yaml.
    """
    from .config import yaml_config
    iq_cfg = yaml_config.get("interrupt_queue", {})

    if not iq_cfg.get("enabled", True):
        # Interrupt deaktiviert — normalen Weg nehmen
        await ws_manager.broadcast("assistant.proactive", {
            "text": text,
            "event_type": event_type,
            "urgency": "critical",
            "notification_id": "",
        })
        return

    pause_ms = iq_cfg.get("pause_ms", 300)

    # 1. Interrupt-Signal: Client soll sofort alles stoppen
    await ws_manager.broadcast("assistant.interrupt", {
        "reason": event_type,
        "protocol": protocol,
    })

    # 2. Kurze Pause damit der Client reagieren kann
    await asyncio.sleep(pause_ms / 1000.0)

    # 3. Notfall-Meldung senden (als proactive mit urgency=critical)
    await ws_manager.broadcast("assistant.proactive", {
        "text": text,
        "event_type": event_type,
        "urgency": "critical",
        "notification_id": "",
        "interrupt": True,
        "protocol": protocol,
        "actions_taken": actions_taken or [],
    })
