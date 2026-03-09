"""
Tests fuer Follow-Me Engine - Raum-Tracking und Transfer-Logik.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, AsyncMock

from assistant.follow_me import FollowMeEngine


# ============================================================
# Fixtures
# ============================================================

FOLLOW_ME_CONFIG = {
    "follow_me": {
        "enabled": True,
        "cooldown_seconds": 60,
        "transfer_music": True,
        "transfer_lights": True,
        "transfer_climate": False,
        "profiles": {
            "alice": {"light_brightness": 90, "comfort_temp": 23},
            "bob": {"light_brightness": 60, "comfort_temp": 20},
        },
    },
    "multi_room": {
        "room_motion_sensors": {
            "wohnzimmer": "binary_sensor.motion_wohnzimmer",
            "schlafzimmer": "binary_sensor.motion_schlafzimmer",
            "kueche": "binary_sensor.motion_kueche",
        },
        "room_speakers": {
            "wohnzimmer": "media_player.wohnzimmer_speaker",
            "Schlafzimmer": "media_player.schlafzimmer_speaker",
            "kueche": "media_player.kueche_speaker",
        },
    },
}

DISABLED_CONFIG = {
    "follow_me": {
        "enabled": False,
    },
}


@pytest.fixture
def engine(ha_mock):
    """FollowMeEngine with mocked config."""
    with patch("assistant.follow_me.yaml_config", FOLLOW_ME_CONFIG):
        eng = FollowMeEngine(ha_mock)
    return eng


@pytest.fixture
def disabled_engine(ha_mock):
    """FollowMeEngine with disabled config."""
    with patch("assistant.follow_me.yaml_config", DISABLED_CONFIG):
        eng = FollowMeEngine(ha_mock)
    return eng


# ============================================================
# get_profile Tests
# ============================================================

class TestGetProfile:
    def test_known_person(self, engine):
        profile = engine.get_profile("alice")
        assert profile["light_brightness"] == 90
        assert profile["comfort_temp"] == 23

    def test_unknown_person_returns_empty(self, engine):
        profile = engine.get_profile("unknown_person")
        assert profile == {}

    def test_case_fallback(self, engine):
        """get_profile tries exact key first, then lowered."""
        profile = engine.get_profile("Alice")
        # "Alice" not in profiles, but "Alice".lower() == "alice" is
        assert profile["light_brightness"] == 90


# ============================================================
# _find_speaker Tests
# ============================================================

class TestFindSpeaker:
    @pytest.mark.parametrize("room,expected", [
        ("wohnzimmer", "media_player.wohnzimmer_speaker"),
        ("Schlafzimmer", "media_player.schlafzimmer_speaker"),
        ("kueche", "media_player.kueche_speaker"),
    ])
    def test_find_existing_speaker(self, engine, room, expected):
        speakers = FOLLOW_ME_CONFIG["multi_room"]["room_speakers"]
        assert engine._find_speaker(room, speakers) == expected

    def test_case_insensitive_match(self, engine):
        speakers = FOLLOW_ME_CONFIG["multi_room"]["room_speakers"]
        result = engine._find_speaker("WOHNZIMMER", speakers)
        assert result == "media_player.wohnzimmer_speaker"

    def test_underscore_to_underscore_normalization(self, engine):
        """Room name with underscore matches config key with underscore."""
        speakers = {"wohn_zimmer": "media_player.wz"}
        result = engine._find_speaker("Wohn_Zimmer", speakers)
        assert result == "media_player.wz"

    def test_unknown_room_returns_none(self, engine):
        speakers = FOLLOW_ME_CONFIG["multi_room"]["room_speakers"]
        assert engine._find_speaker("garage", speakers) is None

    def test_empty_speakers_returns_none(self, engine):
        assert engine._find_speaker("wohnzimmer", {}) is None
        assert engine._find_speaker("wohnzimmer", None) is None


# ============================================================
# cleanup_stale_tracking Tests
# ============================================================

class TestCleanupStaleTracking:
    def test_removes_stale_entries(self, engine):
        engine._person_room["alice"] = "wohnzimmer"
        engine._last_transfer["alice"] = datetime.now() - timedelta(hours=10)
        engine._person_room["bob"] = "kueche"
        engine._last_transfer["bob"] = datetime.now() - timedelta(hours=10)

        engine.cleanup_stale_tracking(max_age_hours=8)

        assert "alice" not in engine._person_room
        assert "alice" not in engine._last_transfer
        assert "bob" not in engine._person_room

    def test_keeps_recent_entries(self, engine):
        engine._person_room["alice"] = "wohnzimmer"
        engine._last_transfer["alice"] = datetime.now() - timedelta(hours=2)

        engine.cleanup_stale_tracking(max_age_hours=8)

        assert "alice" in engine._person_room
        assert "alice" in engine._last_transfer

    def test_mixed_stale_and_recent(self, engine):
        engine._person_room["alice"] = "wohnzimmer"
        engine._last_transfer["alice"] = datetime.now() - timedelta(hours=10)
        engine._person_room["bob"] = "kueche"
        engine._last_transfer["bob"] = datetime.now() - timedelta(hours=1)

        engine.cleanup_stale_tracking(max_age_hours=8)

        assert "alice" not in engine._person_room
        assert "bob" in engine._person_room

    def test_no_entries_no_error(self, engine):
        engine.cleanup_stale_tracking(max_age_hours=8)
        assert engine._person_room == {}


# ============================================================
# health_status Tests
# ============================================================

class TestHealthStatus:
    def test_returns_correct_structure(self, engine):
        status = engine.health_status()
        assert status["enabled"] is True
        assert status["cooldown_seconds"] == 60
        assert status["transfer_music"] is True
        assert status["transfer_lights"] is True
        assert status["transfer_climate"] is False
        assert status["tracked_persons"] == 0
        assert set(status["profiles"]) == {"alice", "bob"}

    def test_tracked_persons_count(self, engine):
        engine._person_room["alice"] = "wohnzimmer"
        engine._person_room["bob"] = "kueche"
        assert engine.health_status()["tracked_persons"] == 2


# ============================================================
# handle_motion Tests
# ============================================================

class TestHandleMotion:
    @pytest.mark.asyncio
    async def test_returns_none_when_disabled(self, disabled_engine):
        result = await disabled_engine.handle_motion(
            "binary_sensor.motion_wohnzimmer", "alice"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_sensor(self, engine, ha_mock):
        with patch("assistant.follow_me.yaml_config", FOLLOW_ME_CONFIG):
            result = await engine.handle_motion(
                "binary_sensor.motion_garage", "alice"
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_first_room_no_transfer(self, engine, ha_mock):
        """First known location should register but not trigger transfer."""
        with patch("assistant.follow_me.yaml_config", FOLLOW_ME_CONFIG):
            result = await engine.handle_motion(
                "binary_sensor.motion_wohnzimmer", "alice"
            )
        assert result is None
        assert engine._person_room["alice"] == "wohnzimmer"

    @pytest.mark.asyncio
    async def test_same_room_no_transfer(self, engine, ha_mock):
        """Motion in same room should not trigger transfer."""
        engine._person_room["alice"] = "wohnzimmer"
        with patch("assistant.follow_me.yaml_config", FOLLOW_ME_CONFIG):
            result = await engine.handle_motion(
                "binary_sensor.motion_wohnzimmer", "alice"
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_cooldown_prevents_transfer(self, engine, ha_mock):
        """Transfer within cooldown should be blocked."""
        engine._person_room["alice"] = "wohnzimmer"
        engine._last_transfer["alice"] = datetime.now()  # just now

        with patch("assistant.follow_me.yaml_config", FOLLOW_ME_CONFIG):
            result = await engine.handle_motion(
                "binary_sensor.motion_schlafzimmer", "alice"
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_room_change_triggers_transfer(self, engine, ha_mock):
        """Room change after cooldown should trigger transfer with music."""
        engine._person_room["alice"] = "wohnzimmer"
        engine._last_transfer["alice"] = datetime.now() - timedelta(seconds=120)

        ha_mock.get_state = AsyncMock(return_value={"state": "playing"})

        with patch("assistant.follow_me.yaml_config", FOLLOW_ME_CONFIG), \
             patch("assistant.config.get_room_profiles", return_value={"rooms": {}}):
            result = await engine.handle_motion(
                "binary_sensor.motion_schlafzimmer", "alice"
            )

        assert result is not None
        assert result["person"] == "alice"
        assert result["from_room"] == "wohnzimmer"
        assert result["to_room"] == "schlafzimmer"
        assert len(result["actions"]) > 0

    @pytest.mark.asyncio
    async def test_default_person_key_when_empty(self, engine, ha_mock):
        """Empty person string should use 'default' as key."""
        with patch("assistant.follow_me.yaml_config", FOLLOW_ME_CONFIG):
            await engine.handle_motion(
                "binary_sensor.motion_wohnzimmer", ""
            )
        assert "default" in engine._person_room

    @pytest.mark.asyncio
    async def test_others_in_old_room_no_pause(self, engine, ha_mock):
        """When others remain in old room, old speaker should NOT be paused."""
        engine._person_room["alice"] = "wohnzimmer"
        engine._person_room["bob"] = "wohnzimmer"
        engine._last_transfer["alice"] = datetime.now() - timedelta(seconds=120)

        ha_mock.get_state = AsyncMock(return_value={"state": "playing"})

        with patch("assistant.follow_me.yaml_config", FOLLOW_ME_CONFIG), \
             patch("assistant.config.get_room_profiles", return_value={"rooms": {}}):
            result = await engine.handle_motion(
                "binary_sensor.motion_kueche", "alice"
            )

        assert result is not None
        # media_pause should NOT have been called (bob still in wohnzimmer)
        pause_calls = [
            c for c in ha_mock.call_service.call_args_list
            if c.args[1] == "media_pause"
        ]
        assert len(pause_calls) == 0

    @pytest.mark.asyncio
    async def test_no_motion_sensors_configured(self, engine, ha_mock):
        """No motion sensors in config should return None."""
        empty_config = {
            "follow_me": {"enabled": True, "cooldown_seconds": 60,
                          "transfer_music": True, "transfer_lights": True,
                          "transfer_climate": False, "profiles": {}},
            "multi_room": {},
        }
        with patch("assistant.follow_me.yaml_config", empty_config):
            result = await engine.handle_motion(
                "binary_sensor.motion_wohnzimmer", "alice"
            )
        assert result is None
