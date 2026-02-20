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


async def emit_thinking():
    """Signalisiert: Assistant denkt nach."""
    await ws_manager.broadcast("assistant.thinking", {"status": "processing"})


async def emit_speaking(text: str, tts_data: dict = None):
    """Signalisiert: Assistant spricht. Phase 9: Optional mit TTS-Metadaten."""
    data = {"text": text}
    if tts_data:
        data["ssml"] = tts_data.get("ssml", text)
        data["message_type"] = tts_data.get("message_type", "casual")
        data["speed"] = tts_data.get("speed", 100)
        data["volume"] = tts_data.get("volume", 0.8)
    await ws_manager.broadcast("assistant.speaking", data)


async def emit_action(function_name: str, args: dict, result: dict):
    """Signalisiert: Assistant fuehrt Aktion aus."""
    await ws_manager.broadcast("assistant.action", {
        "function": function_name,
        "args": args,
        "result": result,
    })


async def emit_listening():
    """Signalisiert: Assistant hoert zu."""
    await ws_manager.broadcast("assistant.listening", {"status": "active"})


async def emit_sound(sound_event: str, volume: float = 0.5):
    """Phase 9: Signalisiert einen Sound-Event."""
    await ws_manager.broadcast("assistant.sound", {
        "sound": sound_event,
        "volume": volume,
    })


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
