"""
Tests fuer WebSocket-Events — Streaming, Broadcast, ConnectionManager.
"""

import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# FastAPI ist in der Test-Umgebung nicht installiert — Mock-Modul registrieren
if "fastapi" not in sys.modules:
    _fastapi_mock = MagicMock()
    _fastapi_mock.WebSocket = MagicMock
    _fastapi_mock.WebSocketDisconnect = type("WebSocketDisconnect", (Exception,), {})
    sys.modules["fastapi"] = _fastapi_mock

from assistant.websocket import (
    ConnectionManager,
    emit_speaking,
    emit_stream_end,
    emit_stream_start,
    emit_stream_token,
)


class TestConnectionManager:
    """Tests fuer ConnectionManager."""

    def test_initial_empty(self):
        cm = ConnectionManager()
        assert cm.active_connections == []

    @pytest.mark.asyncio
    async def test_connect(self):
        cm = ConnectionManager()
        ws = AsyncMock()
        await cm.connect(ws)
        assert len(cm.active_connections) == 1
        ws.accept.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect(self):
        cm = ConnectionManager()
        ws = AsyncMock()
        await cm.connect(ws)
        cm.disconnect(ws)
        assert len(cm.active_connections) == 0

    @pytest.mark.asyncio
    async def test_disconnect_unknown(self):
        """Disconnect von unbekanntem WS loest keinen Fehler aus."""
        cm = ConnectionManager()
        ws = AsyncMock()
        cm.disconnect(ws)  # Kein Fehler
        assert len(cm.active_connections) == 0

    @pytest.mark.asyncio
    async def test_broadcast_no_connections(self):
        """Broadcast ohne Verbindungen funktioniert lautlos."""
        cm = ConnectionManager()
        await cm.broadcast("test.event", {"key": "value"})
        # Kein Fehler

    @pytest.mark.asyncio
    async def test_broadcast_sends_json(self):
        cm = ConnectionManager()
        ws = AsyncMock()
        await cm.connect(ws)
        await cm.broadcast("test.event", {"key": "value"})

        ws.send_text.assert_called_once()
        sent = json.loads(ws.send_text.call_args[0][0])
        assert sent["event"] == "test.event"
        assert sent["data"]["key"] == "value"
        assert "timestamp" in sent

    @pytest.mark.asyncio
    async def test_broadcast_multiple_clients(self):
        cm = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await cm.connect(ws1)
        await cm.connect(ws2)
        await cm.broadcast("event", {"x": 1})

        assert ws1.send_text.call_count == 1
        assert ws2.send_text.call_count == 1

    @pytest.mark.asyncio
    async def test_broadcast_removes_disconnected(self):
        """Fehlgeschlagener Send entfernt den Client."""
        cm = ConnectionManager()
        ws_ok = AsyncMock()
        ws_broken = AsyncMock()
        ws_broken.send_text.side_effect = Exception("Disconnected")

        await cm.connect(ws_ok)
        await cm.connect(ws_broken)
        assert len(cm.active_connections) == 2

        await cm.broadcast("event", {})
        assert len(cm.active_connections) == 1
        assert ws_ok in cm.active_connections

    @pytest.mark.asyncio
    async def test_send_personal(self):
        cm = ConnectionManager()
        ws = AsyncMock()
        await cm.send_personal(ws, "personal.event", {"msg": "hi"})

        ws.send_text.assert_called_once()
        sent = json.loads(ws.send_text.call_args[0][0])
        assert sent["event"] == "personal.event"
        assert sent["data"]["msg"] == "hi"


class TestStreamEvents:
    """Tests fuer Streaming-Events."""

    @pytest.mark.asyncio
    async def test_emit_stream_start(self):
        with patch("assistant.websocket.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            await emit_stream_start()
            mock_ws.broadcast.assert_called_once_with(
                "assistant.stream_start", {"status": "streaming"}
            )

    @pytest.mark.asyncio
    async def test_emit_stream_token(self):
        with patch("assistant.websocket.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            await emit_stream_token("Hello")
            mock_ws.broadcast.assert_called_once_with(
                "assistant.stream_token", {"token": "Hello"}
            )

    @pytest.mark.asyncio
    async def test_emit_stream_token_empty(self):
        with patch("assistant.websocket.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            await emit_stream_token("")
            mock_ws.broadcast.assert_called_once_with(
                "assistant.stream_token", {"token": ""}
            )

    @pytest.mark.asyncio
    async def test_emit_stream_end_without_tts(self):
        with patch("assistant.websocket.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            await emit_stream_end("Vollstaendiger Text")
            mock_ws.broadcast.assert_called_once_with(
                "assistant.stream_end", {"text": "Vollstaendiger Text"}
            )

    @pytest.mark.asyncio
    async def test_emit_stream_end_with_tts(self):
        with patch("assistant.websocket.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            tts = {"ssml": "<speak>Hallo</speak>", "speed": 110}
            await emit_stream_end("Hallo", tts_data=tts)
            call_data = mock_ws.broadcast.call_args[0][1]
            assert call_data["text"] == "Hallo"
            assert call_data["tts"] == tts


class TestEmitSpeaking:
    """Tests fuer emit_speaking()."""

    @pytest.mark.asyncio
    async def test_emit_speaking_basic(self):
        with patch("assistant.websocket.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            await emit_speaking("Hallo Sir")
            call_data = mock_ws.broadcast.call_args[0][1]
            assert call_data["text"] == "Hallo Sir"
            assert "ssml" not in call_data

    @pytest.mark.asyncio
    async def test_emit_speaking_with_tts(self):
        with patch("assistant.websocket.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            tts = {"ssml": "<speak>Hi</speak>", "message_type": "greeting", "speed": 95, "volume": 0.6}
            await emit_speaking("Hi", tts_data=tts)
            call_data = mock_ws.broadcast.call_args[0][1]
            assert call_data["ssml"] == "<speak>Hi</speak>"
            assert call_data["message_type"] == "greeting"
            assert call_data["speed"] == 95
            assert call_data["volume"] == 0.6
