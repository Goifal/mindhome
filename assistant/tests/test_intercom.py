"""
Tests fuer das Intercom-System — Broadcast, Send Intercom, TTS Helper, Regex.
"""

import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# FastAPI ist in der Test-Umgebung nicht installiert — Mock-Modul registrieren
if "fastapi" not in sys.modules:
    _fastapi_mock = MagicMock()
    _fastapi_mock.WebSocket = MagicMock
    _fastapi_mock.WebSocketDisconnect = type("WebSocketDisconnect", (Exception,), {})
    sys.modules["fastapi"] = _fastapi_mock

pydantic_settings = pytest.importorskip("pydantic_settings")

from assistant.function_calling import FunctionExecutor


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def ha_mock():
    mock = AsyncMock()
    mock.get_states = AsyncMock(return_value=[])
    mock.get_state = AsyncMock(return_value={"state": "idle"})
    mock.call_service = AsyncMock(return_value=True)
    return mock


@pytest.fixture
def executor(ha_mock):
    with patch("assistant.function_calling.yaml_config", {
        "tts": {"entity": "tts.piper"},
        "sounds": {"alexa_speakers": ["media_player.echo_kueche"]},
        "multi_room": {
            "room_speakers": {
                "wohnzimmer": "media_player.echo_wohnzimmer",
                "kueche": "media_player.echo_kueche",
            },
        },
        "intercom": {"broadcast_cooldown_seconds": 30},
    }):
        ex = FunctionExecutor(ha_mock)
    return ex


# =====================================================================
# _send_tts_to_speaker
# =====================================================================


class TestSendTtsToSpeaker:
    """Tests fuer den TTS-Dispatch Helper."""

    @pytest.mark.asyncio
    async def test_piper_speaker(self, executor, ha_mock):
        """Standard-Speaker nutzt tts.speak."""
        with patch("assistant.function_calling.yaml_config", {
            "tts": {"entity": "tts.piper"},
            "sounds": {"alexa_speakers": []},
        }):
            ok = await executor._send_tts_to_speaker("media_player.echo_wz", "Hallo")
            assert ok is True
            ha_mock.call_service.assert_called_with("tts", "speak", {
                "entity_id": "tts.piper",
                "media_player_entity_id": "media_player.echo_wz",
                "message": "Hallo",
            })

    @pytest.mark.asyncio
    async def test_alexa_speaker(self, executor, ha_mock):
        """Alexa-Speaker nutzt notify.alexa_media_*."""
        with patch("assistant.function_calling.yaml_config", {
            "tts": {"entity": "tts.piper"},
            "sounds": {"alexa_speakers": ["media_player.echo_kueche"]},
        }):
            ok = await executor._send_tts_to_speaker("media_player.echo_kueche", "Test")
            assert ok is True
            ha_mock.call_service.assert_called_with(
                "notify", "alexa_media_echo_kueche",
                {"message": "Test", "data": {"type": "tts"}},
            )

    @pytest.mark.asyncio
    async def test_error_returns_false(self, executor, ha_mock):
        """Bei Fehler gibt _send_tts_to_speaker False zurueck."""
        ha_mock.call_service = AsyncMock(side_effect=Exception("Connection error"))
        with patch("assistant.function_calling.yaml_config", {
            "tts": {"entity": "tts.piper"},
            "sounds": {"alexa_speakers": []},
        }):
            ok = await executor._send_tts_to_speaker("media_player.x", "Test")
            assert ok is False

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self, executor, ha_mock):
        with patch("assistant.function_calling.yaml_config", {
            "tts": {"entity": "tts.piper"},
            "sounds": {"alexa_speakers": []},
        }):
            ok = await executor._send_tts_to_speaker("media_player.x", "OK")
            assert ok is True


# =====================================================================
# Broadcast Speaker Filtering
# =====================================================================


class TestBroadcastSpeakerFiltering:
    """Tests dass broadcast() nur TTS-faehige Speaker nutzt."""

    @pytest.mark.asyncio
    async def test_excludes_tvs(self, executor, ha_mock):
        """TVs werden nicht angesprochen."""
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "media_player.tv_wohnzimmer", "state": "on",
             "attributes": {"device_class": "tv"}},
            {"entity_id": "media_player.lautsprecher", "state": "idle",
             "attributes": {}},
        ])
        with patch("assistant.function_calling.yaml_config", {
            "tts": {"entity": "tts.piper"}, "sounds": {"alexa_speakers": []},
            "multi_room": {"room_speakers": {}}, "intercom": {},
        }):
            result = await executor._exec_broadcast({"message": "Test"})
        assert result["success"] is True
        assert result["delivered"] == 1

    @pytest.mark.asyncio
    async def test_excludes_firetv(self, executor, ha_mock):
        """Fire TV wird nicht angesprochen."""
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "media_player.fire_tv_stick", "state": "idle", "attributes": {}},
        ])
        with patch("assistant.function_calling.yaml_config", {
            "tts": {"entity": "tts.piper"}, "sounds": {"alexa_speakers": []},
            "multi_room": {"room_speakers": {}}, "intercom": {},
        }):
            result = await executor._exec_broadcast({"message": "Test"})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_uses_configured_room_speakers(self, executor, ha_mock):
        """Konfigurierte room_speakers werden bevorzugt."""
        ha_mock.get_states = AsyncMock(return_value=[])
        with patch("assistant.function_calling.yaml_config", {
            "tts": {"entity": "tts.piper"}, "sounds": {"alexa_speakers": []},
            "multi_room": {"room_speakers": {
                "wz": "media_player.echo_wz",
                "ku": "media_player.echo_ku",
            }}, "intercom": {},
        }):
            result = await executor._exec_broadcast({"message": "Test"})
        assert result["success"] is True
        assert result["delivered"] == 2

    @pytest.mark.asyncio
    async def test_deduplication(self, executor, ha_mock):
        """Speaker erscheint in Config UND HA States — nur einmal TTS."""
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "media_player.echo_wz", "state": "idle", "attributes": {}},
        ])
        with patch("assistant.function_calling.yaml_config", {
            "tts": {"entity": "tts.piper"}, "sounds": {"alexa_speakers": []},
            "multi_room": {"room_speakers": {"wz": "media_player.echo_wz"}},
            "intercom": {},
        }):
            result = await executor._exec_broadcast({"message": "Test"})
        assert result["delivered"] == 1

    @pytest.mark.asyncio
    async def test_no_speakers_returns_failure(self, executor, ha_mock):
        """Kein Speaker gefunden → Fehler."""
        ha_mock.get_states = AsyncMock(return_value=[])
        with patch("assistant.function_calling.yaml_config", {
            "tts": {"entity": "tts.piper"}, "sounds": {"alexa_speakers": []},
            "multi_room": {"room_speakers": {}}, "intercom": {},
        }):
            result = await executor._exec_broadcast({"message": "Test"})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_excludes_kodi(self, executor, ha_mock):
        """Kodi wird nicht angesprochen."""
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "media_player.kodi_wohnzimmer", "state": "idle", "attributes": {}},
        ])
        with patch("assistant.function_calling.yaml_config", {
            "tts": {"entity": "tts.piper"}, "sounds": {"alexa_speakers": []},
            "multi_room": {"room_speakers": {}}, "intercom": {},
        }):
            result = await executor._exec_broadcast({"message": "Test"})
        assert result["success"] is False


# =====================================================================
# Broadcast Rate Limiting
# =====================================================================


class TestBroadcastRateLimiting:
    """Tests fuer Broadcast-Cooldown."""

    @pytest.mark.asyncio
    async def test_first_broadcast_succeeds(self, executor, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "media_player.speaker", "state": "idle", "attributes": {}},
        ])
        with patch("assistant.function_calling.yaml_config", {
            "tts": {"entity": "tts.piper"}, "sounds": {"alexa_speakers": []},
            "multi_room": {"room_speakers": {}}, "intercom": {},
        }):
            result = await executor._exec_broadcast({"message": "Erste Durchsage"})
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_rapid_second_broadcast_blocked(self, executor, ha_mock):
        """Zweite Durchsage innerhalb Cooldown wird blockiert."""
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "media_player.speaker", "state": "idle", "attributes": {}},
        ])
        with patch("assistant.function_calling.yaml_config", {
            "tts": {"entity": "tts.piper"}, "sounds": {"alexa_speakers": []},
            "multi_room": {"room_speakers": {}}, "intercom": {"broadcast_cooldown_seconds": 30},
        }):
            await executor._exec_broadcast({"message": "Erste"})
            result = await executor._exec_broadcast({"message": "Zweite"})
        assert result["success"] is False
        assert "Cooldown" in result["message"]

    @pytest.mark.asyncio
    async def test_broadcast_after_cooldown_succeeds(self, executor, ha_mock):
        """Nach Ablauf des Cooldowns geht die naechste Durchsage durch."""
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "media_player.speaker", "state": "idle", "attributes": {}},
        ])
        with patch("assistant.function_calling.yaml_config", {
            "tts": {"entity": "tts.piper"}, "sounds": {"alexa_speakers": []},
            "multi_room": {"room_speakers": {}}, "intercom": {"broadcast_cooldown_seconds": 30},
        }):
            await executor._exec_broadcast({"message": "Erste"})
            executor._last_broadcast_time = time.time() - 31  # Cooldown abgelaufen
            result = await executor._exec_broadcast({"message": "Zweite"})
        assert result["success"] is True


# =====================================================================
# Send Intercom
# =====================================================================


class TestSendIntercom:
    """Tests fuer gezielte Intercom-Durchsage."""

    @pytest.mark.asyncio
    async def test_direct_room_target(self, executor, ha_mock):
        """Raum direkt angegeben → Speaker im Raum finden."""
        with patch.object(executor, "_find_speaker_in_room",
                          return_value="media_player.echo_wz"):
            with patch("assistant.function_calling.yaml_config", {
                "tts": {"entity": "tts.piper"}, "sounds": {"alexa_speakers": []},
            }):
                result = await executor._exec_send_intercom({
                    "message": "Essen ist fertig",
                    "target_room": "wohnzimmer",
                })
        assert result["success"] is True
        assert "wohnzimmer" in result["message"]

    @pytest.mark.asyncio
    async def test_no_speaker_in_room_returns_error(self, executor, ha_mock):
        """Kein Speaker im Raum → Fehler."""
        with patch.object(executor, "_find_speaker_in_room", return_value=None):
            result = await executor._exec_send_intercom({
                "message": "Test",
                "target_room": "keller",
            })
        assert result["success"] is False
        assert "Kein Lautsprecher" in result["message"]

    @pytest.mark.asyncio
    async def test_person_prefix_in_message(self, executor, ha_mock):
        """Bei target_person wird Name als Prefix an TTS angehaengt."""
        with patch.object(executor, "_find_speaker_in_room",
                          return_value="media_player.echo_wz"):
            with patch("assistant.function_calling.yaml_config", {
                "tts": {"entity": "tts.piper"}, "sounds": {"alexa_speakers": []},
            }):
                await executor._exec_send_intercom({
                    "message": "Essen ist fertig",
                    "target_room": "wohnzimmer",
                    "target_person": "Julia",
                })
        # Pruefen dass TTS mit "Julia, Essen ist fertig" aufgerufen wurde
        ha_mock.call_service.assert_called()
        call_args = ha_mock.call_service.call_args
        assert "Julia, Essen ist fertig" in str(call_args)

    @pytest.mark.asyncio
    async def test_speaker_unavailable_returns_error(self, executor, ha_mock):
        """Speaker unavailable → Fehler."""
        ha_mock.get_state = AsyncMock(return_value={"state": "unavailable"})
        with patch.object(executor, "_find_speaker_in_room",
                          return_value="media_player.echo_wz"):
            result = await executor._exec_send_intercom({
                "message": "Test",
                "target_room": "wohnzimmer",
            })
        assert result["success"] is False
        assert "nicht erreichbar" in result["message"]

    @pytest.mark.asyncio
    async def test_empty_message_returns_error(self, executor, ha_mock):
        """Leere Nachricht → Fehler."""
        result = await executor._exec_send_intercom({"message": ""})
        assert result["success"] is False


# =====================================================================
# Intercom Regex (_detect_intercom_command)
# =====================================================================


class TestDetectIntercomCommand:
    """Tests fuer die NLP Intercom-Pattern-Erkennung."""

    def _detect(self, text: str):
        from assistant.brain import AssistantBrain
        return AssistantBrain._detect_intercom_command(text)

    # -- Positive Matches --

    def test_sag_person_dass(self):
        result = self._detect("sag Julia dass das Essen fertig ist")
        assert result is not None
        assert result["function"] == "send_intercom"
        assert result["args"]["target_person"] == "Julia"
        assert "Essen fertig ist" in result["args"]["message"]

    def test_sage_der_person(self):
        result = self._detect("sage der Lisa im Wohnzimmer das Essen ist fertig")
        assert result is not None
        assert result["args"]["target_person"] == "Lisa"
        assert result["args"]["target_room"] == "Wohnzimmer"

    def test_lowercase_mama(self):
        """Kleingeschriebene Namen wie 'mama', 'papa' muessen funktionieren."""
        result = self._detect("sag mama dass ich komme")
        assert result is not None
        assert result["args"]["target_person"].lower() == "mama"

    def test_hyphenated_name(self):
        """Bindestrich-Namen wie Leon-Marie."""
        result = self._detect("sag Leon-Marie das Essen ist fertig")
        assert result is not None
        assert "Leon-Marie" in result["args"]["target_person"]

    def test_durchsage_room(self):
        result = self._detect("durchsage im Wohnzimmer: bitte kommen")
        assert result is not None
        assert result["function"] == "send_intercom"
        assert result["args"]["target_room"] == "Wohnzimmer"

    def test_durchsage_broadcast(self):
        result = self._detect("durchsage Essen ist fertig")
        assert result is not None
        assert result["function"] == "broadcast"

    def test_ruf_alle(self):
        result = self._detect("ruf alle zum Mittagessen")
        assert result is not None
        assert result["function"] == "broadcast"

    # -- False Positive Prevention --

    def test_sag_bescheid_not_intercom(self):
        assert self._detect("sag bescheid wenn du da bist") is None

    def test_sag_nochmal_not_intercom(self):
        assert self._detect("sag nochmal den Namen") is None

    def test_sag_halt_not_intercom(self):
        assert self._detect("sag halt was du denkst") is None

    def test_sag_einfach_not_intercom(self):
        assert self._detect("sag einfach ja dazu") is None

    def test_sag_mir_not_intercom(self):
        assert self._detect("sag mir was das Wetter ist") is None

    def test_sag_bitte_not_intercom(self):
        assert self._detect("sag bitte den Timer ab") is None

    # -- Edge Cases --

    def test_question_excluded(self):
        assert self._detect("sag Julia was?") is None

    def test_short_text_excluded(self):
        assert self._detect("sag ja") is None


# =====================================================================
# _is_tts_speaker
# =====================================================================


class TestIsTtsSpeaker:
    """Tests fuer die Speaker-Typ-Erkennung."""

    def _make_executor(self):
        ha = AsyncMock()
        with patch("assistant.function_calling.yaml_config", {}):
            return FunctionExecutor(ha)

    def test_normal_speaker_is_tts(self):
        ex = self._make_executor()
        assert ex._is_tts_speaker("media_player.echo_kueche", {}) is True

    def test_tv_excluded(self):
        ex = self._make_executor()
        assert ex._is_tts_speaker("media_player.tv_wohnzimmer", {}) is False

    def test_firetv_excluded(self):
        ex = self._make_executor()
        assert ex._is_tts_speaker("media_player.fire_tv_stick", {}) is False

    def test_receiver_excluded(self):
        ex = self._make_executor()
        assert ex._is_tts_speaker("media_player.denon_avr", {}) is False

    def test_device_class_tv_excluded(self):
        ex = self._make_executor()
        assert ex._is_tts_speaker("media_player.samsung", {"device_class": "tv"}) is False

    def test_non_media_player_excluded(self):
        ex = self._make_executor()
        assert ex._is_tts_speaker("light.wohnzimmer", {}) is False
