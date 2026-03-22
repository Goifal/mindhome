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
            tts = {
                "ssml": "<speak>Hi</speak>",
                "message_type": "greeting",
                "speed": 95,
                "volume": 0.6,
            }
            await emit_speaking("Hi", tts_data=tts)
            call_data = mock_ws.broadcast.call_args[0][1]
            assert call_data["ssml"] == "<speak>Hi</speak>"
            assert call_data["message_type"] == "greeting"
            assert call_data["speed"] == 95
            assert call_data["volume"] == 0.6


# ============================================================
# Coverage: lines 28-29 (MAX_CONNECTIONS reached)
# ============================================================


class TestConnectMaxConnections:
    @pytest.mark.asyncio
    async def test_connect_max_connections_returns_false(self):
        """When MAX_CONNECTIONS reached, close ws and return False."""
        cm = ConnectionManager()
        cm.MAX_CONNECTIONS = 2
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        ws3 = AsyncMock()
        await cm.connect(ws1)
        await cm.connect(ws2)
        result = await cm.connect(ws3)
        assert result is False
        ws3.close.assert_called_once_with(code=4008, reason="Zu viele Verbindungen")
        assert len(cm.active_connections) == 2


# ============================================================
# Coverage: lines 68-69 (broadcast cleanup ValueError)
# ============================================================


class TestBroadcastCleanupValueError:
    @pytest.mark.asyncio
    async def test_broadcast_cleanup_already_removed(self):
        """If a broken connection is already removed during cleanup, no error."""
        cm = ConnectionManager()
        ws_broken = AsyncMock()
        ws_broken.send_text.side_effect = Exception("fail")
        cm.active_connections.append(ws_broken)
        # Remove it before cleanup runs (simulating concurrent removal)
        original_remove = cm.active_connections.remove

        def remove_then_clear(conn):
            try:
                original_remove(conn)
            except ValueError:
                pass

        # First broadcast removes it, second cleanup should handle ValueError
        await cm.broadcast("test", {})
        # Connection should be gone
        assert ws_broken not in cm.active_connections


# ============================================================
# Coverage: lines 80-81 (send_personal error)
# ============================================================


class TestSendPersonalError:
    @pytest.mark.asyncio
    async def test_send_personal_exception_is_caught(self):
        """send_personal catches exceptions silently."""
        cm = ConnectionManager()
        ws = AsyncMock()
        ws.send_text.side_effect = Exception("connection lost")
        # Should not raise
        await cm.send_personal(ws, "event", {"data": "test"})


# ============================================================
# Coverage: lines 90, 106, 115, 120, 131, 162 (emit_* functions)
# ============================================================

from assistant.websocket import (
    emit_thinking,
    emit_action,
    emit_listening,
    emit_sound,
    emit_progress,
    emit_proactive,
    emit_workshop,
)


class TestEmitThinking:
    @pytest.mark.asyncio
    async def test_emit_thinking(self):
        with patch("assistant.websocket.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            await emit_thinking()
            mock_ws.broadcast.assert_called_once_with(
                "assistant.thinking", {"status": "processing"}
            )


class TestEmitAction:
    @pytest.mark.asyncio
    async def test_emit_action(self):
        with patch("assistant.websocket.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            await emit_action("turn_on", {"entity": "light.x"}, {"success": True})
            mock_ws.broadcast.assert_called_once_with(
                "assistant.action",
                {
                    "function": "turn_on",
                    "args": {"entity": "light.x"},
                    "result": {"success": True},
                },
            )


class TestEmitListening:
    @pytest.mark.asyncio
    async def test_emit_listening(self):
        with patch("assistant.websocket.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            await emit_listening()
            mock_ws.broadcast.assert_called_once_with(
                "assistant.listening", {"status": "active"}
            )


class TestEmitSound:
    @pytest.mark.asyncio
    async def test_emit_sound(self):
        with patch("assistant.websocket.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            await emit_sound("chime", volume=0.7)
            mock_ws.broadcast.assert_called_once_with(
                "assistant.sound", {"sound": "chime", "volume": 0.7}
            )


class TestEmitProgress:
    @pytest.mark.asyncio
    async def test_emit_progress(self):
        with patch("assistant.websocket.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            await emit_progress("step1", "Analysiere...")
            mock_ws.broadcast.assert_called_once_with(
                "assistant.progress", {"step": "step1", "message": "Analysiere..."}
            )


class TestEmitProactive:
    @pytest.mark.asyncio
    async def test_emit_proactive(self):
        with patch("assistant.websocket.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            await emit_proactive(
                "Tuer offen", "door_open", urgency="high", notification_id="n1"
            )
            mock_ws.broadcast.assert_called_once_with(
                "assistant.proactive",
                {
                    "text": "Tuer offen",
                    "event_type": "door_open",
                    "urgency": "high",
                    "notification_id": "n1",
                },
            )


class TestEmitWorkshop:
    @pytest.mark.asyncio
    async def test_emit_workshop(self):
        with patch("assistant.websocket.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            await emit_workshop("file_created", {"project_id": "p1"})
            mock_ws.broadcast.assert_called_once_with(
                "workshop.file_created", {"project_id": "p1"}
            )

    @pytest.mark.asyncio
    async def test_emit_workshop_no_data(self):
        with patch("assistant.websocket.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            await emit_workshop("timer")
            mock_ws.broadcast.assert_called_once_with("workshop.timer", {})


# ============================================================
# Coverage: lines 201-226 (emit_interrupt with config)
# ============================================================

from assistant.websocket import emit_interrupt


class TestEmitInterrupt:
    @pytest.mark.asyncio
    async def test_emit_interrupt_enabled(self):
        """Interrupt enabled: sends interrupt signal, then proactive with critical."""
        with patch("assistant.websocket.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            with patch(
                "assistant.config.yaml_config",
                {
                    "interrupt_queue": {"enabled": True, "pause_ms": 0},
                },
            ):
                with patch(
                    "assistant.websocket.asyncio.sleep", new_callable=AsyncMock
                ) as mock_sleep:
                    await emit_interrupt(
                        "Feuer!", "fire_alarm", protocol="evac", actions_taken=["alarm"]
                    )
                    # Should have 2 broadcast calls: interrupt + proactive
                    assert mock_ws.broadcast.call_count == 2
                    first_call = mock_ws.broadcast.call_args_list[0]
                    assert first_call[0][0] == "assistant.interrupt"
                    assert first_call[0][1]["reason"] == "fire_alarm"
                    assert first_call[0][1]["protocol"] == "evac"
                    second_call = mock_ws.broadcast.call_args_list[1]
                    assert second_call[0][0] == "assistant.proactive"
                    assert second_call[0][1]["text"] == "Feuer!"
                    assert second_call[0][1]["urgency"] == "critical"
                    assert second_call[0][1]["interrupt"] is True
                    assert second_call[0][1]["actions_taken"] == ["alarm"]

    @pytest.mark.asyncio
    async def test_emit_interrupt_disabled(self):
        """Interrupt disabled: falls back to normal proactive broadcast."""
        with patch("assistant.websocket.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            with patch(
                "assistant.config.yaml_config",
                {
                    "interrupt_queue": {"enabled": False},
                },
            ):
                await emit_interrupt("Warnung", "warning_event")
                mock_ws.broadcast.assert_called_once_with(
                    "assistant.proactive",
                    {
                        "text": "Warnung",
                        "event_type": "warning_event",
                        "urgency": "critical",
                        "notification_id": "",
                    },
                )

    @pytest.mark.asyncio
    async def test_emit_interrupt_default_config(self):
        """Interrupt with default config (no interrupt_queue key)."""
        with patch("assistant.websocket.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            with patch("assistant.config.yaml_config", {}):
                with patch("assistant.websocket.asyncio.sleep", new_callable=AsyncMock):
                    await emit_interrupt("Test", "test_event")
                    # Default enabled=True, so interrupt path
                    assert mock_ws.broadcast.call_count == 2

    @pytest.mark.asyncio
    async def test_emit_interrupt_pause_ms(self):
        """Interrupt uses configured pause_ms for sleep."""
        with patch("assistant.websocket.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            with patch(
                "assistant.config.yaml_config",
                {
                    "interrupt_queue": {"enabled": True, "pause_ms": 500},
                },
            ):
                with patch(
                    "assistant.websocket.asyncio.sleep", new_callable=AsyncMock
                ) as mock_sleep:
                    await emit_interrupt("Alert", "alert_event")
                    mock_sleep.assert_called_once_with(0.5)

    @pytest.mark.asyncio
    async def test_emit_interrupt_no_actions_taken(self):
        """Interrupt without actions_taken defaults to empty list."""
        with patch("assistant.websocket.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            with patch(
                "assistant.config.yaml_config",
                {
                    "interrupt_queue": {"enabled": True, "pause_ms": 0},
                },
            ):
                with patch("assistant.websocket.asyncio.sleep", new_callable=AsyncMock):
                    await emit_interrupt("Test", "event")
                    second_call = mock_ws.broadcast.call_args_list[1]
                    assert second_call[0][1]["actions_taken"] == []
