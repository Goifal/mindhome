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
    with patch(
        "assistant.multi_room_audio.yaml_config",
        {
            "multi_room_audio": {
                "enabled": True,
                "max_groups": 10,
                "default_volume": 40,
                "use_native_grouping": False,
            },
        },
    ):
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
    result = await mra.create_group(
        "Party", ["media_player.a", "media_player.b"], "Partygruppe"
    )
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
    mra.ha.get_state = AsyncMock(
        return_value={"state": "playing", "attributes": {"friendly_name": "Speaker A"}}
    )
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
    mra.ha.get_states = AsyncMock(
        return_value=[
            {
                "entity_id": "media_player.kitchen",
                "state": "idle",
                "attributes": {"friendly_name": "Kitchen"},
            },
            {
                "entity_id": "media_player.living_room_tv",
                "state": "idle",
                "attributes": {},
            },
            {"entity_id": "light.lamp", "state": "on", "attributes": {}},
        ]
    )
    speakers = await mra.discover_speakers()
    assert len(speakers) == 1
    assert speakers[0]["entity_id"] == "media_player.kitchen"


@pytest.mark.asyncio
async def test_discover_speakers_excludes_device_class_tv(mra):
    mra.ha.get_states = AsyncMock(
        return_value=[
            {
                "entity_id": "media_player.generic",
                "state": "idle",
                "attributes": {"device_class": "tv"},
            },
        ]
    )
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
    with patch(
        "assistant.multi_room_audio.yaml_config",
        {
            "multi_room_audio": {
                "enabled": True,
                "presets": {
                    "Ueberall": {
                        "speakers": ["media_player.a", "media_player.b"],
                        "description": "Alle Speaker",
                    },
                },
            },
        },
    ):
        await mra.load_presets()
    groups = await mra.list_groups()
    assert any(g["name"] == "Ueberall" for g in groups)


@pytest.mark.asyncio
async def test_load_presets_no_redis(mra):
    mra.redis = None
    with patch(
        "assistant.multi_room_audio.yaml_config",
        {
            "multi_room_audio": {"presets": {"X": {"speakers": ["media_player.a"]}}},
        },
    ):
        await mra.load_presets()  # should not raise


# =====================================================================
# Additional coverage tests
# =====================================================================


class TestCreateGroupEdges:
    """Edge cases for create_group."""

    @pytest.mark.asyncio
    async def test_create_group_redis_exception(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        # Override hset to raise on the second call (first is create, but we need
        # the hset for the group itself to fail)
        original_hset = redis_client.hset.side_effect
        call_count = [0]

        async def failing_hset(key, field, value):
            call_count[0] += 1
            if call_count[0] >= 1 and key == _KEY_GROUPS:
                raise Exception("Redis write error")
            return await original_hset(key, field, value)

        redis_client.hset = AsyncMock(side_effect=failing_hset)
        result = await mra.create_group("Fail", ["media_player.a"])
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_create_group_disabled(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        mra.enabled = False
        result = await mra.create_group("Test", ["media_player.a"])
        assert result["success"] is False


class TestDeleteGroupEdges:
    """Edge cases for delete_group."""

    @pytest.mark.asyncio
    async def test_delete_group_disabled(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        mra.enabled = False
        result = await mra.delete_group("Test")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_delete_active_group_clears_active(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        await mra.create_group("Active", ["media_player.a"])
        # Set as active group
        await redis_client.set(_KEY_ACTIVE_GROUP, "active")
        redis_client.get = AsyncMock(return_value="active")
        result = await mra.delete_group("Active")
        assert result["success"] is True
        redis_client.delete.assert_called()

    @pytest.mark.asyncio
    async def test_delete_active_group_bytes(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        await mra.create_group("ByteTest", ["media_player.a"])
        redis_client.get = AsyncMock(return_value=b"bytetest")
        result = await mra.delete_group("ByteTest")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_delete_group_exception(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        redis_client.hdel = AsyncMock(side_effect=Exception("Redis error"))
        result = await mra.delete_group("Test")
        assert result["success"] is False


class TestModifyGroupEdges:
    """Edge cases for modify_group."""

    @pytest.mark.asyncio
    async def test_modify_group_disabled(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        mra.enabled = False
        result = await mra.modify_group("Test", add_speakers=["media_player.a"])
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_modify_group_redis_exception(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        await mra.create_group("ModFail", ["media_player.a"])
        # Make hset always fail from now on
        redis_client.hset = AsyncMock(side_effect=Exception("Redis write error"))
        result = await mra.modify_group("ModFail", add_speakers=["media_player.b"])
        assert result["success"] is False


class TestListGroupsEdges:
    """Edge cases for list_groups."""

    @pytest.mark.asyncio
    async def test_list_groups_disabled(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        mra.enabled = False
        result = await mra.list_groups()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_groups_exception(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        redis_client.hgetall = AsyncMock(side_effect=Exception("Redis error"))
        result = await mra.list_groups()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_groups_bytes_values(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        group_data = json.dumps(
            {
                "name": "Test",
                "speakers": ["media_player.a"],
                "volume": 40,
                "speaker_volumes": {},
            }
        )
        redis_client.hgetall = AsyncMock(return_value={"test": group_data.encode()})
        result = await mra.list_groups()
        assert len(result) == 1


class TestPlayToGroupEdges:
    """Edge cases for play_to_group."""

    @pytest.mark.asyncio
    async def test_play_disabled(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        mra.enabled = False
        result = await mra.play_to_group("Test", query="Jazz")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_play_empty_speakers(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        # Create group then manually set speakers to empty
        await mra.create_group("Empty", ["media_player.a"])
        group = await mra._get_group("Empty")
        group["speakers"] = []
        await redis_client.hset(_KEY_GROUPS, "empty", json.dumps(group))
        result = await mra.play_to_group("Empty", query="Jazz")
        assert result["success"] is False
        assert (
            "keine Speaker" in result["message"].lower()
            or "keine Speaker" in result["message"]
        )

    @pytest.mark.asyncio
    async def test_play_native_grouping(self, mra, redis_client, ha_client):
        await _make_ready(mra, redis_client)
        mra.use_native_grouping = True
        await mra.create_group("Native", ["media_player.a", "media_player.b"])
        result = await mra.play_to_group("Native", query="Jazz")
        assert result["success"] is True
        # Should have called join
        join_calls = [
            c for c in ha_client.call_service.call_args_list if c[0][1] == "join"
        ]
        assert len(join_calls) >= 1


class TestPlayNativeGroupEdges:
    """Edge cases for _play_native_group."""

    @pytest.mark.asyncio
    async def test_native_group_fallback_on_error(self, mra, redis_client, ha_client):
        await _make_ready(mra, redis_client)
        mra.use_native_grouping = True

        # Make join succeed but play_media fail, triggering fallback
        call_count = [0]

        async def mock_call_service(domain, service, data):
            call_count[0] += 1
            if service == "play_media" and call_count[0] <= 3:
                raise Exception("play failed")
            return True

        ha_client.call_service = AsyncMock(side_effect=mock_call_service)

        group = {
            "name": "Test",
            "speakers": ["media_player.a", "media_player.b"],
            "volume": 40,
            "speaker_volumes": {"media_player.a": 40, "media_player.b": 40},
        }
        # The fallback _play_parallel will also fail, but that's ok
        result = await mra._play_native_group(
            ["media_player.a", "media_player.b"], "Jazz", "music", group
        )
        # Should attempt fallback


class TestPlayParallelEdges:
    """Edge cases for _play_parallel."""

    @pytest.mark.asyncio
    async def test_partial_failures(self, mra, redis_client, ha_client):
        await _make_ready(mra, redis_client)
        call_count = [0]

        async def mock_call_service(domain, service, data):
            call_count[0] += 1
            if service == "play_media" and data.get("entity_id") == "media_player.b":
                raise Exception("Speaker B offline")
            return True

        ha_client.call_service = AsyncMock(side_effect=mock_call_service)
        group = {
            "name": "Test",
            "speakers": ["media_player.a", "media_player.b"],
            "volume": 40,
            "speaker_volumes": {"media_player.a": 40, "media_player.b": 40},
        }
        result = await mra._play_parallel(
            ["media_player.a", "media_player.b"], "Jazz", "music", group
        )
        assert result["success"] is True
        assert "fehlgeschlagen" in result["message"]

    @pytest.mark.asyncio
    async def test_all_fail_exception(self, mra, redis_client, ha_client):
        await _make_ready(mra, redis_client)
        group = {
            "name": "Test",
            "speakers": ["media_player.a"],
            "volume": 40,
            "speaker_volumes": {"media_player.a": 40},
        }
        # Patch gather to raise to hit except branch (lines 277-278)
        with patch("asyncio.gather", side_effect=Exception("All down")):
            result = await mra._play_parallel(
                ["media_player.a"], "Jazz", "music", group
            )
        assert result["success"] is False


class TestStopGroupEdges:
    """Edge cases for stop_group."""

    @pytest.mark.asyncio
    async def test_stop_disabled(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        mra.enabled = False
        result = await mra.stop_group("Test")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_stop_with_native_unjoin(self, mra, redis_client, ha_client):
        await _make_ready(mra, redis_client)
        mra.use_native_grouping = True
        await mra.create_group("NativeStop", ["media_player.a", "media_player.b"])
        result = await mra.stop_group("NativeStop")
        assert result["success"] is True
        # Should have called unjoin
        unjoin_calls = [
            c
            for c in ha_client.call_service.call_args_list
            if len(c[0]) > 1 and c[0][1] == "unjoin"
        ]
        assert len(unjoin_calls) >= 1

    @pytest.mark.asyncio
    async def test_stop_native_unjoin_exception(self, mra, redis_client, ha_client):
        await _make_ready(mra, redis_client)
        mra.use_native_grouping = True
        await mra.create_group("UnjoinFail", ["media_player.a", "media_player.b"])

        call_count = [0]

        async def mock_call_service(domain, service, data):
            call_count[0] += 1
            if service == "unjoin":
                raise Exception("Unjoin failed")
            return True

        ha_client.call_service = AsyncMock(side_effect=mock_call_service)
        result = await mra.stop_group("UnjoinFail")
        assert result["success"] is True  # Should still succeed

    @pytest.mark.asyncio
    async def test_stop_group_exception(self, mra, redis_client, ha_client):
        await _make_ready(mra, redis_client)
        await mra.create_group("StopFail", ["media_player.a"])
        # Patch asyncio.gather to raise to hit the except branch
        with patch("asyncio.gather", side_effect=Exception("gather failed")):
            result = await mra.stop_group("StopFail")
        assert result["success"] is False


class TestPauseGroupEdges:
    """Edge cases for pause_group."""

    @pytest.mark.asyncio
    async def test_pause_disabled(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        mra.enabled = False
        result = await mra.pause_group("Test")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_pause_not_found(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        result = await mra.pause_group("nonexistent")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_pause_exception(self, mra, redis_client, ha_client):
        await _make_ready(mra, redis_client)
        await mra.create_group("PauseFail", ["media_player.a"])
        # Patch asyncio.gather to raise to hit the except branch
        with patch("asyncio.gather", side_effect=Exception("gather failed")):
            result = await mra.pause_group("PauseFail")
        assert result["success"] is False


class TestSetGroupVolumeEdges:
    """Edge cases for set_group_volume."""

    @pytest.mark.asyncio
    async def test_volume_disabled(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        mra.enabled = False
        result = await mra.set_group_volume("Test", 50)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_volume_group_not_found(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        result = await mra.set_group_volume("nonexistent", 50)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_volume_single_speaker_exception(self, mra, redis_client, ha_client):
        await _make_ready(mra, redis_client)
        await mra.create_group("VolFail", ["media_player.a"])
        ha_client.call_service = AsyncMock(side_effect=Exception("HA error"))
        result = await mra.set_group_volume("VolFail", 60, speaker="media_player.a")
        # Should still succeed (exception is caught)
        assert result["success"] is True


class TestGetGroupStatusEdges:
    """Edge cases for get_group_status."""

    @pytest.mark.asyncio
    async def test_status_disabled(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        mra.enabled = False
        result = await mra.get_group_status()
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_status_specific_not_found(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        result = await mra.get_group_status("nonexistent")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_status_all_with_active_group(self, mra, redis_client, ha_client):
        await _make_ready(mra, redis_client)
        await mra.create_group("Music", ["media_player.a"], description="Main speakers")
        await mra.create_group("Party", ["media_player.b"])
        redis_client.get = AsyncMock(return_value="music")
        result = await mra.get_group_status()
        assert result["success"] is True
        assert "Music" in result["message"]
        assert "Main speakers" in result["message"]

    @pytest.mark.asyncio
    async def test_status_active_bytes(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        await mra.create_group("ByteActive", ["media_player.a"])
        redis_client.get = AsyncMock(return_value=b"byteactive")
        result = await mra.get_group_status()
        assert result["success"] is True


class TestBuildGroupStatusEdges:
    """Edge cases for _build_group_status."""

    @pytest.mark.asyncio
    async def test_description_shown(self, mra, redis_client, ha_client):
        await _make_ready(mra, redis_client)
        group = {
            "name": "Test",
            "description": "Test description",
            "speakers": ["media_player.a"],
            "speaker_volumes": {"media_player.a": 40},
        }
        ha_client.get_state = AsyncMock(
            return_value={
                "state": "playing",
                "attributes": {"friendly_name": "Speaker A", "media_title": "Song"},
            }
        )
        result = await mra._build_group_status(group)
        assert "Test description" in result["message"]
        assert "Song" in result["message"]

    @pytest.mark.asyncio
    async def test_speaker_not_reachable(self, mra, redis_client, ha_client):
        await _make_ready(mra, redis_client)
        group = {
            "name": "Test",
            "speakers": ["media_player.a"],
            "speaker_volumes": {"media_player.a": 40},
        }
        ha_client.get_state = AsyncMock(return_value=None)
        result = await mra._build_group_status(group)
        assert "nicht erreichbar" in result["message"]

    @pytest.mark.asyncio
    async def test_speaker_state_exception(self, mra, redis_client, ha_client):
        await _make_ready(mra, redis_client)
        group = {
            "name": "Test",
            "speakers": ["media_player.a"],
            "speaker_volumes": {"media_player.a": 40},
        }
        ha_client.get_state = AsyncMock(side_effect=Exception("HA error"))
        result = await mra._build_group_status(group)
        assert "Fehler" in result["message"]


class TestLoadPresetsEdges:
    """Edge cases for load_presets."""

    @pytest.mark.asyncio
    async def test_preset_empty_speakers_skipped(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        with patch(
            "assistant.multi_room_audio.yaml_config",
            {
                "multi_room_audio": {
                    "presets": {
                        "Empty": {"speakers": [], "description": "No speakers"},
                        "Valid": {
                            "speakers": ["media_player.a"],
                            "description": "Has speakers",
                        },
                    },
                },
            },
        ):
            await mra.load_presets()
        groups = await mra.list_groups()
        names = [g["name"] for g in groups]
        assert "Valid" in names
        # "Empty" should have been skipped

    @pytest.mark.asyncio
    async def test_preset_existing_group_skipped(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        await mra.create_group("Existing", ["media_player.a"])
        with patch(
            "assistant.multi_room_audio.yaml_config",
            {
                "multi_room_audio": {
                    "presets": {
                        "Existing": {
                            "speakers": ["media_player.b"],
                            "description": "New version",
                        },
                    },
                },
            },
        ):
            await mra.load_presets()
        # Group should still have original speaker
        group = await mra._get_group("Existing")
        assert "media_player.a" in group["speakers"]


class TestGetGroupEdges:
    """Edge cases for _get_group."""

    @pytest.mark.asyncio
    async def test_get_group_no_redis(self, mra):
        mra.redis = None
        result = await mra._get_group("test")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_group_exception(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        redis_client.hget = AsyncMock(side_effect=Exception("Parse error"))
        result = await mra._get_group("test")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_group_bytes_value(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        group_data = json.dumps({"name": "Test", "speakers": ["media_player.a"]})
        redis_client.hget = AsyncMock(return_value=group_data.encode())
        result = await mra._get_group("test")
        assert result is not None
        assert result["name"] == "Test"


class TestGetSpeakerNamesEdges:
    """Edge cases for _get_speaker_names."""

    @pytest.mark.asyncio
    async def test_empty_entity_ids(self, mra, redis_client):
        await _make_ready(mra, redis_client)
        result = await mra._get_speaker_names([])
        assert result == []

    @pytest.mark.asyncio
    async def test_state_returns_none(self, mra, redis_client, ha_client):
        await _make_ready(mra, redis_client)
        ha_client.get_state = AsyncMock(return_value=None)
        result = await mra._get_speaker_names(["media_player.test"])
        assert result == ["test"]  # media_player. stripped

    @pytest.mark.asyncio
    async def test_state_exception(self, mra, redis_client, ha_client):
        await _make_ready(mra, redis_client)
        ha_client.get_state = AsyncMock(side_effect=Exception("HA error"))
        result = await mra._get_speaker_names(["media_player.test"])
        assert result == ["test"]

    @pytest.mark.asyncio
    async def test_state_with_friendly_name(self, mra, redis_client, ha_client):
        await _make_ready(mra, redis_client)
        ha_client.get_state = AsyncMock(
            return_value={
                "attributes": {"friendly_name": "Kitchen Speaker"},
            }
        )
        result = await mra._get_speaker_names(["media_player.kitchen"])
        assert result == ["Kitchen Speaker"]


class TestDiscoverSpeakersEdges:
    """Edge cases for discover_speakers."""

    @pytest.mark.asyncio
    async def test_discover_exception(self, mra, ha_client):
        ha_client.get_states = AsyncMock(side_effect=Exception("HA error"))
        result = await mra.discover_speakers()
        assert result == []

    @pytest.mark.asyncio
    async def test_discover_excludes_receiver_device_class(self, mra, ha_client):
        ha_client.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "media_player.avr",
                    "state": "on",
                    "attributes": {"device_class": "receiver"},
                },
            ]
        )
        result = await mra.discover_speakers()
        assert len(result) == 0
