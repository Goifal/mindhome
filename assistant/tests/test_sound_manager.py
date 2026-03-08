"""Tests for assistant/sound_manager.py — SoundManager unit tests."""

import time
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from assistant.sound_manager import SoundManager, TTS_CHIME_TEXTS, DEFAULT_SOUND_DESCRIPTIONS


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
def ha_client():
    ha = AsyncMock()
    ha.get_states = AsyncMock(return_value=[])
    ha.get_state = AsyncMock(return_value=None)
    ha.call_service = AsyncMock(return_value=True)
    return ha


@pytest.fixture
def sm(ha_client):
    with patch("assistant.sound_manager.yaml_config", {
        "sounds": {
            "enabled": True,
            "events": {"doorbell": "/local/sounds/doorbell.mp3"},
            "night_volume_factor": 0.4,
            "sound_base_url": "/local/sounds",
            "tts_entity": "",
            "default_speaker": "",
            "alexa_speakers": ["media_player.echo_kueche"],
        },
        "volume": {"evening_start": 22, "morning_start": 7},
        "multi_room": {"room_speakers": {"wohnzimmer": "media_player.wz_speaker"}},
    }):
        manager = SoundManager(ha_client)
    return manager


# ── __init__ ──────────────────────────────────────────────────

def test_init_defaults(sm):
    assert sm.enabled is True
    assert sm.night_volume_factor == 0.4
    assert sm.sound_base_url == "/local/sounds"
    assert sm.evening_start == 22
    assert sm.morning_start == 7


def test_init_disabled():
    ha = AsyncMock()
    with patch("assistant.sound_manager.yaml_config", {
        "sounds": {"enabled": False, "events": {}},
        "volume": {},
        "multi_room": {},
    }):
        mgr = SoundManager(ha)
    assert mgr.enabled is False


# ── _is_alexa_speaker / _alexa_notify_service ─────────────────

def test_is_alexa_speaker_true(sm):
    assert sm._is_alexa_speaker("media_player.echo_kueche") is True


def test_is_alexa_speaker_false(sm):
    assert sm._is_alexa_speaker("media_player.wz_speaker") is False


def test_alexa_notify_service(sm):
    result = sm._alexa_notify_service("media_player.echo_wohnzimmer")
    assert result == "alexa_media_echo_wohnzimmer"


# ── _is_tts_speaker ──────────────────────────────────────────

def test_is_tts_speaker_valid(sm):
    assert sm._is_tts_speaker("media_player.kitchen_speaker") is True


def test_is_tts_speaker_tv_excluded(sm):
    assert sm._is_tts_speaker("media_player.living_room_tv") is False


def test_is_tts_speaker_fire_tv_excluded(sm):
    assert sm._is_tts_speaker("media_player.fire_tv_stick") is False


def test_is_tts_speaker_receiver_excluded(sm):
    assert sm._is_tts_speaker("media_player.denon_avr") is False


def test_is_tts_speaker_non_media_player(sm):
    assert sm._is_tts_speaker("light.kitchen") is False


def test_is_tts_speaker_device_class_tv(sm):
    assert sm._is_tts_speaker("media_player.generic", {"device_class": "tv"}) is False


# ── _get_auto_volume ──────────────────────────────────────────

def test_get_auto_volume_alarm_always_full(sm):
    vol = sm._get_auto_volume("alarm")
    assert vol == 1.0


def test_get_auto_volume_night_reduces(sm):
    with patch("assistant.sound_manager.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2025, 1, 1, 23, 0)
        vol = sm._get_auto_volume("confirmed")
    assert vol < 0.4  # Night factor applied


def test_get_auto_volume_daytime(sm):
    with patch("assistant.sound_manager.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2025, 1, 1, 12, 0)
        vol = sm._get_auto_volume("confirmed")
    assert vol == 0.4


def test_get_auto_volume_sleeping_activity(sm):
    with patch("assistant.sound_manager.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2025, 1, 1, 12, 0)
        vol = sm._get_auto_volume("confirmed", activity="sleeping")
    assert vol < 0.2


def test_get_auto_volume_weather_boost(sm):
    with patch("assistant.sound_manager.yaml_config", {
        "sounds": {"weather_volume_boost": 0.15},
        "volume": {},
        "multi_room": {},
    }):
        with patch("assistant.sound_manager.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 1, 12, 0)
            vol_normal = sm._get_auto_volume("confirmed", weather_condition="")
            vol_rainy = sm._get_auto_volume("confirmed", weather_condition="rainy")
    assert vol_rainy > vol_normal


def test_get_auto_volume_alarm_ignores_activity(sm):
    with patch("assistant.sound_manager.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2025, 1, 1, 12, 0)
        vol = sm._get_auto_volume("alarm", activity="sleeping")
    assert vol == 1.0


# ── play_event_sound ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_play_event_sound_disabled(sm):
    sm.enabled = False
    result = await sm.play_event_sound("doorbell")
    assert result is False


@pytest.mark.asyncio
async def test_play_event_sound_anti_spam(sm):
    sm._last_sound_time["doorbell"] = time.time()  # just played
    result = await sm.play_event_sound("doorbell")
    assert result is False


@pytest.mark.asyncio
async def test_play_event_sound_success(sm):
    sm._last_sound_time.clear()
    with patch.object(sm, '_resolve_speaker', new_callable=AsyncMock, return_value="media_player.wz_speaker"):
        with patch.object(sm, '_play_sound_file', new_callable=AsyncMock, return_value=True):
            with patch.object(sm, '_get_current_weather_condition', new_callable=AsyncMock, return_value=""):
                result = await sm.play_event_sound("doorbell", volume=0.5)
    assert result is True


@pytest.mark.asyncio
async def test_play_event_sound_fallback_tts(sm):
    sm._last_sound_time.clear()
    with patch.object(sm, '_resolve_speaker', new_callable=AsyncMock, return_value="media_player.wz_speaker"):
        with patch.object(sm, '_play_sound_file', new_callable=AsyncMock, return_value=False):
            with patch.object(sm, '_play_tts_chime', new_callable=AsyncMock, return_value=True):
                with patch.object(sm, '_get_current_weather_condition', new_callable=AsyncMock, return_value=""):
                    result = await sm.play_event_sound("warning", volume=0.5)
    assert result is True


@pytest.mark.asyncio
async def test_play_event_sound_no_speaker(sm):
    sm._last_sound_time.clear()
    with patch.object(sm, '_resolve_speaker', new_callable=AsyncMock, return_value=None):
        with patch.object(sm, '_get_current_weather_condition', new_callable=AsyncMock, return_value=""):
            result = await sm.play_event_sound("doorbell", volume=0.5)
    assert result is False


# ── _play_sound_file ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_play_sound_file_alexa_skipped(sm):
    result = await sm._play_sound_file("doorbell", "media_player.echo_kueche")
    assert result is False


@pytest.mark.asyncio
async def test_play_sound_file_custom_url(sm):
    result = await sm._play_sound_file("doorbell", "media_player.wz_speaker")
    assert result is True
    sm.ha.call_service.assert_called()


# ── _play_tts_chime ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_play_tts_chime_unknown_event(sm):
    result = await sm._play_tts_chime("unknown_event", "media_player.wz_speaker")
    assert result is False


@pytest.mark.asyncio
async def test_play_tts_chime_alexa(sm):
    with patch.object(sm, '_speak_via_alexa', new_callable=AsyncMock, return_value=True):
        result = await sm._play_tts_chime("warning", "media_player.echo_kueche")
    assert result is True


# ── _resolve_speaker ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_speaker_room_config(sm):
    with patch("assistant.sound_manager.yaml_config", {
        "multi_room": {"room_speakers": {"wohnzimmer": "media_player.wz_speaker"}},
        "sounds": {},
        "volume": {},
    }):
        result = await sm._resolve_speaker("wohnzimmer")
    assert result == "media_player.wz_speaker"


@pytest.mark.asyncio
async def test_resolve_speaker_default(sm):
    sm._configured_default_speaker = "media_player.default"
    result = await sm._resolve_speaker()
    assert result == "media_player.default"


# ── _find_tts_entity ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_find_tts_entity_configured(sm):
    sm._configured_tts_entity = "tts.piper"
    sm._cached_tts_entity = None
    result = await sm._find_tts_entity()
    assert result == "tts.piper"


@pytest.mark.asyncio
async def test_find_tts_entity_auto_piper(sm):
    sm._cached_tts_entity = None
    sm._configured_tts_entity = ""
    sm.ha.get_states = AsyncMock(return_value=[
        {"entity_id": "tts.piper_de", "state": "idle"},
        {"entity_id": "tts.other", "state": "idle"},
    ])
    sm._states_cache = None
    result = await sm._find_tts_entity()
    assert result == "tts.piper_de"


@pytest.mark.asyncio
async def test_find_tts_entity_fallback(sm):
    sm._cached_tts_entity = None
    sm._configured_tts_entity = ""
    sm.ha.get_states = AsyncMock(return_value=[
        {"entity_id": "tts.google_say", "state": "idle"},
    ])
    sm._states_cache = None
    result = await sm._find_tts_entity()
    assert result == "tts.google_say"


# ── get_sound_info ────────────────────────────────────────────

def test_get_sound_info(sm):
    info = sm.get_sound_info()
    assert "enabled" in info
    assert "events" in info
    assert "descriptions" in info
    assert info["descriptions"] == DEFAULT_SOUND_DESCRIPTIONS


# ── States cache ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_states_cache_hit(sm):
    sm._states_cache = [{"entity_id": "light.wz"}]
    sm._states_cache_time = time.monotonic()  # fresh
    result = await sm._get_states_cached()
    assert result == [{"entity_id": "light.wz"}]
    sm.ha.get_states.assert_not_called()


@pytest.mark.asyncio
async def test_states_cache_expired(sm):
    sm._states_cache = [{"entity_id": "light.old"}]
    sm._states_cache_time = time.monotonic() - 120  # old
    sm.ha.get_states = AsyncMock(return_value=[{"entity_id": "light.new"}])
    result = await sm._get_states_cached()
    assert result == [{"entity_id": "light.new"}]


# ── Constants ─────────────────────────────────────────────────

def test_tts_chime_texts_coverage():
    expected = {"listening", "confirmed", "warning", "alarm", "doorbell", "greeting", "error", "goodnight"}
    assert set(TTS_CHIME_TEXTS.keys()) == expected


def test_sound_descriptions_coverage():
    assert set(DEFAULT_SOUND_DESCRIPTIONS.keys()) == set(TTS_CHIME_TEXTS.keys())
