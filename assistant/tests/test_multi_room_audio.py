"""Tests for assistant/multi_room_audio.py — MultiRoomAudio unit tests."""

import json
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from assistant.multi_room_audio import MultiRoomAudio, _KEY_GROUPS, _KEY_ACTIVE_GROUP


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
def ha_client():
    ha = AsyncMock()
    ha.get_states = AsyncMock(return_value=[])
    ha.get_state = AsyncMock(return_value=None)
    ha.call_service = AsyncMock(return_value=True)
    return ha


@pytest.fixture
def redis_client():
    """Redis mock with basic hash operations using an in-memory store."""
    r = AsyncMock()
    _store = {}

    async def mock_hset(key, field, value):
        _store.setdefault(key, {})[field] = value

    async def mock_hget(key, field):
        return _store.get(key, {}).get(field)

    async def mock_hdel(key, field):
        if key in _store and field in _store[key]:
            del _store[key][field]
            return 1
        return 0

    async def mock_hlen(key):
        return len(_store.get(key, {}))

    async def mock_hgetall(key):
        return _store.get(key, {})

    r.hset = AsyncMock(side_effect=mock_hset)
    r.hget = AsyncMock(side_effect=mock_hget)
    r.hdel = AsyncMock(side_effect=mock_hdel)
    r.hlen = AsyncMock(side_effect=mock_hlen)
    r.hgetall = AsyncMock(side_effect=mock_hgetall)
    r.get = AsyncMock(return_value=None)
    r.set = AsyncMock(return_value=True)
    r.delete = AsyncMock(return_value=True)
    return r


@pytest.fixture
def mra(ha_client):
    with patch("assistant.multi_room_audio.yaml_config", {
        "multi_room_audio": {"enabled": True, "max_groups": 10, "default_volume": 40, "use_native_grouping": False},
    }):
        audio = MultiRoomAudio(ha_client)
    return audio


async def _make_ready(mra, redis_client):
    """Helper to initialize mra with redis."""
    await mra.initialize(redis_client)
    return mra


# ── initialize ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_initialize(mra, redis_client):
    await mra.initialize(redis_client)
    assert mra.redis is redis_client


# ── create_group ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_group_success(mra, redis_client):
    await _make_ready(mra, redis_client)
    result = await mra.create_group("Party", ["media_player.a", "media_player.b"], "Partygruppe")
    assert result["success"] is True
    assert "Party" in result["message"]


@pytest.mark.asyncio
async def test_create_group_empty_name(mra, redis_client):
    await _make_ready(mra, redis_client)
    result = await mra.create_group("", ["media_player.a"])
    assert result["success"] is False
    assert "leer" in result["message"]


@pytest.mark.asyncio
async def test_create_group_no_speakers(mra, redis_client):
    await _make_ready(mra, redis_client)
    result = await mra.create_group("Test", [])
    assert result["success"] is False


@pytest.mark.asyncio
async def test_create_group_duplicate(mra, redis_client):
    await _make_ready(mra, redis_client)
    await mra.create_group("Party", ["media_player.a"])
    result = await mra.create_group("Party", ["media_player.b"])
    assert result["success"] is False
    assert "existiert bereits" in result["message"]


@pytest.mark.asyncio
async def test_create_group_no_redis(mra):
    mra.redis = None
    result = await mra.create_group("Party", ["media_player.a"])
    assert result["success"] is False


@pytest.mark.asyncio
async def test_create_group_max_reached(mra, redis_client):
    await _make_ready(mra, redis_client)
    mra.max_groups = 1
    await mra.create_group("First", ["media_player.a"])
    result = await mra.create_group("Second", ["media_player.b"])
    assert result["success"] is False
    assert "Maximale" in result["message"]


# ── delete_group ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_group_success(mra, redis_client):
    await _make_ready(mra, redis_client)
    await mra.create_group("ToDelete", ["media_player.a"])
    result = await mra.delete_group("ToDelete")
    assert result["success"] is True


@pytest.mark.asyncio
async def test_delete_group_not_found(mra, redis_client):
    await _make_ready(mra, redis_client)
    result = await mra.delete_group("nonexistent")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_delete_group_empty_name(mra, redis_client):
    await _make_ready(mra, redis_client)
    result = await mra.delete_group("")
    assert result["success"] is False


# ── modify_group ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_modify_group_add_speaker(mra, redis_client):
    await _make_ready(mra, redis_client)
    await mra.create_group("Mod", ["media_player.a"])
    result = await mra.modify_group("Mod", add_speakers=["media_player.b"])
    assert result["success"] is True
    assert "+media_player.b" in result["message"]


@pytest.mark.asyncio
async def test_modify_group_remove_speaker(mra, redis_client):
    await _make_ready(mra, redis_client)
    await mra.create_group("Mod", ["media_player.a", "media_player.b"])
    result = await mra.modify_group("Mod", remove_speakers=["media_player.b"])
    assert result["success"] is True
    assert "-media_player.b" in result["message"]


@pytest.mark.asyncio
async def test_modify_group_no_changes(mra, redis_client):
    await _make_ready(mra, redis_client)
    await mra.create_group("Mod", ["media_player.a"])
    result = await mra.modify_group("Mod", add_speakers=["media_player.a"])
    assert result["success"] is False
    assert "Keine Aenderungen" in result["message"]


@pytest.mark.asyncio
async def test_modify_group_not_found(mra, redis_client):
    await _make_ready(mra, redis_client)
    result = await mra.modify_group("nonexistent", add_speakers=["media_player.a"])
    assert result["success"] is False


# ── list_groups ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_groups_empty(mra, redis_client):
    await _make_ready(mra, redis_client)
    result = await mra.list_groups()
    assert result == []


@pytest.mark.asyncio
async def test_list_groups_returns_all(mra, redis_client):
    await _make_ready(mra, redis_client)
    await mra.create_group("Alpha", ["media_player.a"])
    await mra.create_group("Beta", ["media_player.b"])
    result = await mra.list_groups()
    assert len(result) == 2
    names = [g["name"] for g in result]
    assert "Alpha" in names
    assert "Beta" in names


@pytest.mark.asyncio
async def test_list_groups_no_redis(mra):
    mra.redis = None
    result = await mra.list_groups()
    assert result == []


# ── play_to_group ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_play_to_group_success(mra, redis_client):
    await _make_ready(mra, redis_client)
    await mra.create_group("Music", ["media_player.a", "media_player.b"])
    result = await mra.play_to_group("Music", query="Jazz")
    assert result["success"] is True


@pytest.mark.asyncio
async def test_play_to_group_not_found(mra, redis_client):
    await _make_ready(mra, redis_client)
    result = await mra.play_to_group("nonexistent", query="test")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_play_to_group_no_content(mra, redis_client):
    await _make_ready(mra, redis_client)
    await mra.create_group("Music", ["media_player.a"])
    result = await mra.play_to_group("Music")
    assert result["success"] is False
    assert "Kein Inhalt" in result["message"]


# ── stop_group / pause_group ──────────────────────────────────

@pytest.mark.asyncio
async def test_stop_group_success(mra, redis_client):
    await _make_ready(mra, redis_client)
    await mra.create_group("Music", ["media_player.a"])
    result = await mra.stop_group("Music")
    assert result["success"] is True
    assert "gestoppt" in result["message"]


@pytest.mark.asyncio
async def test_stop_group_not_found(mra, redis_client):
    await _make_ready(mra, redis_client)
    result = await mra.stop_group("nonexistent")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_pause_group_success(mra, redis_client):
    await _make_ready(mra, redis_client)
    await mra.create_group("Music", ["media_player.a"])
    result = await mra.pause_group("Music")
    assert result["success"] is True
    assert "pausiert" in result["message"]


# ── set_group_volume ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_group_volume_all(mra, redis_client):
    await _make_ready(mra, redis_client)
    await mra.create_group("Vol", ["media_player.a", "media_player.b"])
    result = await mra.set_group_volume("Vol", 80)
    assert result["success"] is True
    assert "80%" in result["message"]


@pytest.mark.asyncio
async def test_set_group_volume_single_speaker(mra, redis_client):
    await _make_ready(mra, redis_client)
    await mra.create_group("Vol", ["media_player.a", "media_player.b"])
    result = await mra.set_group_volume("Vol", 60, speaker="media_player.a")
    assert result["success"] is True


@pytest.mark.asyncio
async def test_set_group_volume_speaker_not_in_group(mra, redis_client):
    await _make_ready(mra, redis_client)
    await mra.create_group("Vol", ["media_player.a"])
    result = await mra.set_group_volume("Vol", 60, speaker="media_player.z")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_set_group_volume_clamp(mra, redis_client):
    await _make_ready(mra, redis_client)
    await mra.create_group("Vol", ["media_player.a"])
    result = await mra.set_group_volume("Vol", 150)
    assert result["success"] is True
    assert "100%" in result["message"]


# ── get_group_status ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_group_status_specific(mra, redis_client):
    await _make_ready(mra, redis_client)
    await mra.create_group("Status", ["media_player.a"])
    mra.ha.get_state = AsyncMock(return_value={"state": "playing", "attributes": {"friendly_name": "Speaker A"}})
    result = await mra.get_group_status("Status")
    assert result["success"] is True
    assert "Speaker A" in result["message"]


@pytest.mark.asyncio
async def test_get_group_status_all_empty(mra, redis_client):
    await _make_ready(mra, redis_client)
    result = await mra.get_group_status()
    assert result["success"] is True
    assert "Keine Audio-Gruppen" in result["message"]


# ── discover_speakers ────────────────────────────────────────

@pytest.mark.asyncio
async def test_discover_speakers(mra):
    mra.ha.get_states = AsyncMock(return_value=[
        {"entity_id": "media_player.kitchen", "state": "idle", "attributes": {"friendly_name": "Kitchen"}},
        {"entity_id": "media_player.living_room_tv", "state": "idle", "attributes": {}},
        {"entity_id": "light.lamp", "state": "on", "attributes": {}},
    ])
    speakers = await mra.discover_speakers()
    assert len(speakers) == 1
    assert speakers[0]["entity_id"] == "media_player.kitchen"


@pytest.mark.asyncio
async def test_discover_speakers_excludes_device_class_tv(mra):
    mra.ha.get_states = AsyncMock(return_value=[
        {"entity_id": "media_player.generic", "state": "idle", "attributes": {"device_class": "tv"}},
    ])
    speakers = await mra.discover_speakers()
    assert len(speakers) == 0


# ── health_status ─────────────────────────────────────────────

def test_health_status(mra):
    status = mra.health_status()
    assert status["enabled"] is True
    assert status["native_grouping"] is False
    assert status["max_groups"] == 10
    assert status["default_volume"] == 40


# ── load_presets ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_load_presets(mra, redis_client):
    await _make_ready(mra, redis_client)
    with patch("assistant.multi_room_audio.yaml_config", {
        "multi_room_audio": {
            "enabled": True,
            "presets": {
                "Ueberall": {"speakers": ["media_player.a", "media_player.b"], "description": "Alle Speaker"},
            },
        },
    }):
        await mra.load_presets()
    groups = await mra.list_groups()
    assert any(g["name"] == "Ueberall" for g in groups)


@pytest.mark.asyncio
async def test_load_presets_no_redis(mra):
    mra.redis = None
    with patch("assistant.multi_room_audio.yaml_config", {
        "multi_room_audio": {"presets": {"X": {"speakers": ["media_player.a"]}}},
    }):
        await mra.load_presets()  # should not raise
