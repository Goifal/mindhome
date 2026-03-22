"""
Tests for assistant.situation_model -- _build_snapshot, _compare_snapshots,
take_snapshot, get_situation_delta, initialize, and config handling.
"""

import json
import sys
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

# Ensure the assistant package is importable regardless of cwd.
_assistant_dir = os.path.join(os.path.dirname(__file__), os.pardir)
if _assistant_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_assistant_dir))

with patch("assistant.situation_model.yaml_config", {}):
    from assistant.situation_model import (
        SituationModel,
        KEY_LAST_SNAPSHOT,
        KEY_LAST_INTERACTION,
        SNAPSHOT_TTL,
    )


@pytest.fixture
def sm():
    with patch("assistant.situation_model.yaml_config", {}):
        return SituationModel()


@pytest.fixture
def sm_with_redis(redis_mock):
    with patch("assistant.situation_model.yaml_config", {}):
        model = SituationModel()
        model.redis = redis_mock
        model.enabled = True
        return model


# --- helpers ----------------------------------------------------------------


def _state(entity_id, state="on", attrs=None):
    """Shortcut to build a HA state dict."""
    a = {"friendly_name": entity_id.split(".", 1)[1].replace("_", " ").title()}
    if attrs:
        a.update(attrs)
    return {"entity_id": entity_id, "state": state, "attributes": a}


# ============================================================================
# Initialization & Config
# ============================================================================


class TestInitialization:
    """Tests fuer SituationModel Initialisierung und Config."""

    def test_default_config(self):
        with patch("assistant.situation_model.yaml_config", {}):
            model = SituationModel()
            assert model.enabled is True
            assert model.min_pause_minutes == 5
            assert model.max_changes == 5
            assert model.temp_threshold == 2

    def test_custom_config(self):
        cfg = {
            "situation_model": {
                "enabled": False,
                "min_pause_minutes": 10,
                "max_changes": 3,
                "temp_threshold": 5,
            }
        }
        with patch("assistant.situation_model.yaml_config", cfg):
            model = SituationModel()
            assert model.enabled is False
            assert model.min_pause_minutes == 10
            assert model.max_changes == 3
            assert model.temp_threshold == 5

    @pytest.mark.asyncio
    async def test_initialize_sets_redis(self):
        with patch("assistant.situation_model.yaml_config", {}):
            model = SituationModel()
            redis = AsyncMock()
            await model.initialize(redis)
            assert model.redis is redis

    @pytest.mark.asyncio
    async def test_initialize_none_redis(self):
        with patch("assistant.situation_model.yaml_config", {}):
            model = SituationModel()
            await model.initialize(None)
            assert model.redis is None


# ============================================================================
# take_snapshot
# ============================================================================


class TestTakeSnapshot:
    """Tests fuer SituationModel.take_snapshot()."""

    @pytest.mark.asyncio
    async def test_take_snapshot_stores_in_redis(self, sm_with_redis, redis_mock):
        """Snapshot is stored in Redis with TTL."""
        states = [_state("light.bedroom", "on")]
        await sm_with_redis.take_snapshot(states)
        # setex called twice: once for snapshot, once for last_interaction
        assert redis_mock.setex.call_count == 2
        # First call is the snapshot
        first_call = redis_mock.setex.call_args_list[0]
        assert first_call[0][0] == KEY_LAST_SNAPSHOT
        assert first_call[0][1] == SNAPSHOT_TTL
        # Verify stored data is valid JSON
        stored = json.loads(first_call[0][2])
        assert "lights_on" in stored

    @pytest.mark.asyncio
    async def test_take_snapshot_stores_interaction_time(
        self, sm_with_redis, redis_mock
    ):
        """Last interaction time is stored."""
        await sm_with_redis.take_snapshot([_state("light.wz", "on")])
        second_call = redis_mock.setex.call_args_list[1]
        assert second_call[0][0] == KEY_LAST_INTERACTION
        # Stored value is a valid ISO timestamp
        datetime.fromisoformat(second_call[0][2])

    @pytest.mark.asyncio
    async def test_take_snapshot_disabled(self, sm_with_redis, redis_mock):
        """Disabled model does not store snapshot."""
        sm_with_redis.enabled = False
        await sm_with_redis.take_snapshot([_state("light.wz", "on")])
        redis_mock.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_take_snapshot_no_redis(self, sm):
        """No Redis does not crash."""
        sm.redis = None
        await sm.take_snapshot([_state("light.wz", "on")])  # Should not raise

    @pytest.mark.asyncio
    async def test_take_snapshot_empty_states(self, sm_with_redis, redis_mock):
        """Empty states list does not store anything."""
        await sm_with_redis.take_snapshot([])
        redis_mock.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_take_snapshot_redis_exception(self, sm_with_redis, redis_mock):
        """Redis exception is caught gracefully."""
        redis_mock.setex = AsyncMock(side_effect=Exception("connection lost"))
        # Should not raise
        await sm_with_redis.take_snapshot([_state("light.wz", "on")])


# ============================================================================
# get_situation_delta
# ============================================================================


class TestGetSituationDelta:
    """Tests fuer SituationModel.get_situation_delta()."""

    @pytest.mark.asyncio
    async def test_delta_with_changes(self, sm_with_redis, redis_mock):
        """Returns delta text when there are changes."""
        old_snapshot = {
            "timestamp": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            "temperatures": {"Wohnzimmer": 22.0},
            "open_windows": [],
            "lights_on": [],
            "locks_unlocked": [],
        }
        redis_mock.get = AsyncMock(
            side_effect=[
                json.dumps(old_snapshot),  # snapshot
                (
                    datetime.now(timezone.utc) - timedelta(minutes=30)
                ).isoformat(),  # last interaction
            ]
        )
        current = [
            _state(
                "climate.living_room",
                "heat",
                {
                    "current_temperature": 19.0,
                    "temperature": 22.0,
                    "friendly_name": "Wohnzimmer",
                },
            ),
        ]
        result = await sm_with_redis.get_situation_delta(current)
        assert result is not None
        assert "SITUATIONS-DELTA" in result
        assert "gesunken" in result

    @pytest.mark.asyncio
    async def test_delta_no_previous_snapshot(self, sm_with_redis, redis_mock):
        """No previous snapshot returns None."""
        redis_mock.get = AsyncMock(return_value=None)
        result = await sm_with_redis.get_situation_delta([_state("light.wz", "on")])
        assert result is None

    @pytest.mark.asyncio
    async def test_delta_no_changes_returns_none(self, sm_with_redis, redis_mock):
        """When current state matches old snapshot, returns None."""
        old_snapshot = {"temperatures": {}, "open_windows": [], "lights_on": ["Wz"]}
        redis_mock.get = AsyncMock(
            side_effect=[
                json.dumps(old_snapshot),
                (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(),
            ]
        )
        # Current state has same light on
        result = await sm_with_redis.get_situation_delta(
            [_state("light.wz", "on", {"friendly_name": "Wz"})]
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_delta_no_changes(self, sm_with_redis, redis_mock):
        """Same state returns None."""
        old_snapshot = {"temperatures": {"Room": 20.0}, "open_windows": []}
        redis_mock.get = AsyncMock(
            side_effect=[
                json.dumps(old_snapshot),
                (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(),
            ]
        )
        current = [
            _state(
                "climate.room",
                "heat",
                {"current_temperature": 20.0, "friendly_name": "Room"},
            )
        ]
        result = await sm_with_redis.get_situation_delta(current)
        assert result is None

    @pytest.mark.asyncio
    async def test_delta_disabled(self, sm_with_redis):
        """Disabled model returns None."""
        sm_with_redis.enabled = False
        result = await sm_with_redis.get_situation_delta([_state("light.wz", "on")])
        assert result is None

    @pytest.mark.asyncio
    async def test_delta_empty_states(self, sm_with_redis):
        """Empty states list returns None."""
        result = await sm_with_redis.get_situation_delta([])
        assert result is None

    @pytest.mark.asyncio
    async def test_delta_redis_exception(self, sm_with_redis, redis_mock):
        """Redis exception returns None gracefully."""
        redis_mock.get = AsyncMock(side_effect=Exception("connection lost"))
        result = await sm_with_redis.get_situation_delta([_state("light.wz", "on")])
        assert result is None

    @pytest.mark.asyncio
    async def test_delta_invalid_snapshot_json(self, sm_with_redis, redis_mock):
        """Invalid JSON in stored snapshot returns None."""
        redis_mock.get = AsyncMock(
            side_effect=[
                "not valid json{{{",
                (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(),
            ]
        )
        result = await sm_with_redis.get_situation_delta([_state("light.wz", "on")])
        assert result is None

    @pytest.mark.asyncio
    async def test_delta_max_changes_limit(self, sm_with_redis, redis_mock):
        """Delta is limited to max_changes entries."""
        sm_with_redis.max_changes = 2
        old_snapshot = {
            "temperatures": {},
            "open_windows": [],
            "locks_unlocked": [],
            "lights_on": [],
            "open_doors": [],
        }
        redis_mock.get = AsyncMock(
            side_effect=[
                json.dumps(old_snapshot),
                (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(),
            ]
        )
        # Many changes: 5 lights turned on individually
        current = [
            _state("lock.front", "unlocked"),
            _state("binary_sensor.kitchen_window", "on"),
            _state("binary_sensor.balkon_fenster", "on"),
            _state("binary_sensor.front_door", "on"),
            _state("light.lamp_a", "on"),
            _state("light.lamp_b", "on"),
        ]
        result = await sm_with_redis.get_situation_delta(current)
        assert result is not None
        # Count the bullet points
        lines = [l for l in result.split("\n") if l.startswith("- ")]
        assert len(lines) <= 2

    @pytest.mark.asyncio
    async def test_delta_header_without_time(self, sm_with_redis, redis_mock):
        """When time parsing fails, header still present without time info."""
        old_snapshot = {
            "temperatures": {},
            "open_windows": [],
            "locks_unlocked": ["Front"],
        }
        redis_mock.get = AsyncMock(
            side_effect=[
                json.dumps(old_snapshot),
                (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat(),
            ]
        )
        current = [_state("lock.front", "locked")]
        result = await sm_with_redis.get_situation_delta(current)
        assert result is not None
        assert "Seit dem letzten Gespraech" in result
        assert "verriegelt" in result

    @pytest.mark.asyncio
    async def test_delta_with_no_interaction_time(self, sm_with_redis, redis_mock):
        """When no interaction time stored, header has no time prefix."""
        old_snapshot = {
            "temperatures": {},
            "open_windows": [],
            "locks_unlocked": ["Front"],
        }
        redis_mock.get = AsyncMock(
            side_effect=[
                json.dumps(old_snapshot),
                None,  # no last interaction time
            ]
        )
        current = [_state("lock.front", "locked")]
        result = await sm_with_redis.get_situation_delta(current)
        assert result is not None
        assert "Seit dem letzten Gespraech:" in result

    @pytest.mark.asyncio
    async def test_delta_with_invalid_time_string(self, sm_with_redis, redis_mock):
        """Invalid time string does not crash, header has no time."""
        old_snapshot = {
            "temperatures": {},
            "open_windows": [],
            "locks_unlocked": ["Front"],
        }
        redis_mock.get = AsyncMock(
            side_effect=[
                json.dumps(old_snapshot),
                "not a valid timestamp",
            ]
        )
        current = [_state("lock.front", "locked")]
        result = await sm_with_redis.get_situation_delta(current)
        assert result is not None
        assert "verriegelt" in result

    @pytest.mark.asyncio
    async def test_delta_bytes_snapshot(self, sm_with_redis, redis_mock):
        """Redis returning bytes is handled correctly."""
        old_snapshot = {
            "temperatures": {},
            "open_windows": [],
            "locks_unlocked": ["Front"],
        }
        redis_mock.get = AsyncMock(
            side_effect=[
                json.dumps(old_snapshot).encode(),
                (datetime.now(timezone.utc) - timedelta(minutes=30))
                .isoformat()
                .encode(),
            ]
        )
        current = [_state("lock.front", "locked")]
        result = await sm_with_redis.get_situation_delta(current)
        assert result is not None


# ============================================================================
# _build_snapshot tests
# ============================================================================


class TestBuildSnapshot:
    def test_climate_temperature(self, sm):
        states = [
            _state(
                "climate.living_room",
                "heat",
                {"current_temperature": 21.6, "temperature": 22.0},
            )
        ]
        snap = sm._build_snapshot(states)
        assert snap["temperatures"]["Living Room"] == 21.6
        assert snap["climate_targets"]["Living Room"] == 22.0

    def test_climate_without_current_temp(self, sm):
        states = [_state("climate.office", "heat", {"temperature": 22.0})]
        snap = sm._build_snapshot(states)
        assert "Office" not in snap["temperatures"]
        assert snap["climate_targets"]["Office"] == 22.0

    def test_sensor_temperature(self, sm):
        states = [_state("sensor.outdoor_temperature", "5.3")]
        snap = sm._build_snapshot(states)
        assert snap["temperatures"]["Outdoor Temperature"] == 5.3

    def test_sensor_temperature_out_of_range_high_ignored(self, sm):
        states = [_state("sensor.outdoor_temperature", "100")]
        snap = sm._build_snapshot(states)
        assert snap["temperatures"] == {}

    def test_sensor_temperature_out_of_range_low_ignored(self, sm):
        states = [_state("sensor.outdoor_temperature", "-50")]
        snap = sm._build_snapshot(states)
        assert snap["temperatures"] == {}

    def test_sensor_temperature_boundary_valid(self, sm):
        states = [_state("sensor.freezer_temperature", "-39.5")]
        snap = sm._build_snapshot(states)
        assert snap["temperatures"]["Freezer Temperature"] == -39.5

    def test_sensor_temperature_non_numeric_ignored(self, sm):
        states = [_state("sensor.outdoor_temperature", "unavailable")]
        snap = sm._build_snapshot(states)
        assert snap["temperatures"] == {}

    def test_open_window(self, sm):
        states = [_state("binary_sensor.kitchen_window", "on")]
        snap = sm._build_snapshot(states)
        assert "Kitchen Window" in snap["open_windows"]

    def test_closed_window_not_included(self, sm):
        states = [_state("binary_sensor.kitchen_window", "off")]
        snap = sm._build_snapshot(states)
        assert snap["open_windows"] == []

    def test_open_door(self, sm):
        states = [_state("binary_sensor.front_door", "on")]
        snap = sm._build_snapshot(states)
        assert "Front Door" in snap["open_doors"]

    def test_fenster_keyword_detected(self, sm):
        states = [_state("binary_sensor.kuechen_fenster", "on")]
        snap = sm._build_snapshot(states)
        assert len(snap["open_windows"]) == 1

    def test_tuer_keyword_detected(self, sm):
        states = [_state("binary_sensor.haus_tuer", "on")]
        snap = sm._build_snapshot(states)
        assert len(snap["open_doors"]) == 1

    def test_light_on(self, sm):
        states = [_state("light.bedroom", "on")]
        snap = sm._build_snapshot(states)
        assert "Bedroom" in snap["lights_on"]

    def test_light_off_not_included(self, sm):
        states = [_state("light.bedroom", "off")]
        snap = sm._build_snapshot(states)
        assert snap["lights_on"] == []

    def test_lock_unlocked(self, sm):
        states = [_state("lock.front", "unlocked")]
        snap = sm._build_snapshot(states)
        assert "Front" in snap["locks_unlocked"]

    def test_lock_locked_not_included(self, sm):
        states = [_state("lock.front", "locked")]
        snap = sm._build_snapshot(states)
        assert snap["locks_unlocked"] == []

    def test_cover_open(self, sm):
        states = [_state("cover.blinds", "open")]
        snap = sm._build_snapshot(states)
        assert "Blinds" in snap["covers_open"]

    def test_cover_closed_not_included(self, sm):
        states = [_state("cover.blinds", "closed")]
        snap = sm._build_snapshot(states)
        assert snap["covers_open"] == []

    def test_person_tracking(self, sm):
        states = [_state("person.alice", "home")]
        snap = sm._build_snapshot(states)
        assert snap["persons"]["Alice"] == "home"

    def test_media_playing(self, sm):
        states = [_state("media_player.speaker", "playing")]
        snap = sm._build_snapshot(states)
        assert "Speaker" in snap["media_playing"]

    def test_media_idle_not_included(self, sm):
        states = [_state("media_player.speaker", "idle")]
        snap = sm._build_snapshot(states)
        assert snap["media_playing"] == []

    def test_low_battery_tracked(self, sm):
        states = [_state("sensor.motion", "off", {"battery_level": 15})]
        snap = sm._build_snapshot(states)
        assert snap["low_batteries"]["Motion"] == 15

    def test_normal_battery_not_tracked(self, sm):
        states = [_state("sensor.motion", "off", {"battery_level": 80})]
        snap = sm._build_snapshot(states)
        assert "low_batteries" not in snap or snap.get("low_batteries", {}) == {}

    def test_battery_via_battery_attr(self, sm):
        states = [_state("sensor.door_sensor", "off", {"battery": 10})]
        snap = sm._build_snapshot(states)
        assert snap["low_batteries"]["Door Sensor"] == 10

    def test_vacuum_state(self, sm):
        states = [_state("vacuum.robo", "cleaning")]
        snap = sm._build_snapshot(states)
        assert snap["vacuum_states"]["Robo"] == "cleaning"

    def test_empty_states(self, sm):
        snap = sm._build_snapshot([])
        assert snap["temperatures"] == {}
        assert snap["open_windows"] == []

    def test_snapshot_has_timestamp(self, sm):
        snap = sm._build_snapshot([])
        assert "timestamp" in snap

    def test_multiple_entities_combined(self, sm):
        states = [
            _state(
                "climate.living_room",
                "heat",
                {"current_temperature": 21.0, "temperature": 22.0},
            ),
            _state("binary_sensor.kitchen_window", "on"),
            _state("light.bedroom", "on"),
            _state("person.bob", "not_home"),
            _state("vacuum.robo", "docked"),
        ]
        snap = sm._build_snapshot(states)
        assert snap["temperatures"]["Living Room"] == 21.0
        assert "Kitchen Window" in snap["open_windows"]
        assert "Bedroom" in snap["lights_on"]
        assert snap["persons"]["Bob"] == "not_home"
        assert snap["vacuum_states"]["Robo"] == "docked"

    def test_climate_invalid_temperature_value(self, sm):
        """Non-numeric current_temperature is handled gracefully."""
        states = [_state("climate.bad", "heat", {"current_temperature": "unavailable"})]
        snap = sm._build_snapshot(states)
        assert "Bad" not in snap["temperatures"]

    def test_battery_non_numeric_ignored(self, sm):
        """Non-numeric battery value is handled gracefully."""
        states = [_state("sensor.x", "off", {"battery_level": "unknown"})]
        snap = sm._build_snapshot(states)
        assert snap.get("low_batteries", {}) == {}


# ============================================================================
# _compare_snapshots tests
# ============================================================================


class TestCompareSnapshots:
    # --- Temperature ---

    def test_no_changes(self, sm):
        snap = {"temperatures": {"Room": 20.0}, "open_windows": []}
        assert sm._compare_snapshots(snap, snap) == []

    def test_temperature_drop_above_threshold(self, sm):
        old = {"temperatures": {"Room": 22.0}}
        new = {"temperatures": {"Room": 19.5}}
        changes = sm._compare_snapshots(old, new)
        assert any("gesunken" in c for c in changes)
        assert any("2.5" in c for c in changes)

    def test_temperature_rise_above_threshold(self, sm):
        old = {"temperatures": {"Room": 18.0}}
        new = {"temperatures": {"Room": 21.0}}
        changes = sm._compare_snapshots(old, new)
        assert any("gestiegen" in c for c in changes)

    def test_temperature_change_below_threshold_ignored(self, sm):
        old = {"temperatures": {"Room": 20.0}}
        new = {"temperatures": {"Room": 21.0}}
        changes = sm._compare_snapshots(old, new)
        assert not any("Temperatur" in c for c in changes)

    def test_temperature_exact_threshold(self, sm):
        old = {"temperatures": {"Room": 20.0}}
        new = {"temperatures": {"Room": 22.0}}
        changes = sm._compare_snapshots(old, new)
        assert any("gestiegen" in c for c in changes)

    # --- Windows ---

    def test_window_opened(self, sm):
        old = {"open_windows": []}
        new = {"open_windows": ["Kueche"]}
        changes = sm._compare_snapshots(old, new)
        assert any("Kueche" in c and "ge\u00f6ffnet" in c for c in changes)

    def test_window_closed(self, sm):
        old = {"open_windows": ["Kueche"]}
        new = {"open_windows": []}
        changes = sm._compare_snapshots(old, new)
        assert any("Kueche" in c and "geschlossen" in c for c in changes)

    # --- Doors ---

    def test_door_opened(self, sm):
        old = {"open_doors": []}
        new = {"open_doors": ["Haustuer"]}
        changes = sm._compare_snapshots(old, new)
        assert any("Haustuer" in c and "ge\u00f6ffnet" in c for c in changes)

    def test_door_closed(self, sm):
        old = {"open_doors": ["Haustuer"]}
        new = {"open_doors": []}
        changes = sm._compare_snapshots(old, new)
        assert any("Haustuer" in c and "geschlossen" in c for c in changes)

    # --- Locks ---

    def test_lock_unlocked(self, sm):
        old = {"locks_unlocked": []}
        new = {"locks_unlocked": ["Front"]}
        changes = sm._compare_snapshots(old, new)
        assert any("entriegelt" in c for c in changes)

    def test_lock_locked(self, sm):
        old = {"locks_unlocked": ["Front"]}
        new = {"locks_unlocked": []}
        changes = sm._compare_snapshots(old, new)
        assert any("verriegelt" in c for c in changes)

    # --- Persons ---

    def test_person_arrived(self, sm):
        old = {"persons": {"Alice": "not_home"}}
        new = {"persons": {"Alice": "home"}}
        changes = sm._compare_snapshots(old, new)
        assert any("nach Hause gekommen" in c for c in changes)

    def test_person_left(self, sm):
        old = {"persons": {"Alice": "home"}}
        new = {"persons": {"Alice": "not_home"}}
        changes = sm._compare_snapshots(old, new)
        assert any("Haus verlassen" in c for c in changes)

    def test_person_no_change(self, sm):
        old = {"persons": {"Alice": "home"}}
        new = {"persons": {"Alice": "home"}}
        assert sm._compare_snapshots(old, new) == []

    def test_person_new_appears_at_home(self, sm):
        old = {"persons": {}}
        new = {"persons": {"Bob": "home"}}
        changes = sm._compare_snapshots(old, new)
        assert any("nach Hause gekommen" in c for c in changes)

    def test_person_disappears_from_home(self, sm):
        old = {"persons": {"Bob": "home"}}
        new = {"persons": {}}
        changes = sm._compare_snapshots(old, new)
        assert any("Haus verlassen" in c for c in changes)

    # --- Lights ---

    def test_lights_on_few(self, sm):
        old = {"lights_on": []}
        new = {"lights_on": ["Lamp A", "Lamp B"]}
        changes = sm._compare_snapshots(old, new)
        assert any("Lamp A" in c and "eingeschaltet" in c for c in changes)
        assert any("Lamp B" in c and "eingeschaltet" in c for c in changes)

    def test_lights_on_many_summarised(self, sm):
        old = {"lights_on": []}
        new = {"lights_on": ["A", "B", "C"]}
        changes = sm._compare_snapshots(old, new)
        assert any("3 Lichter" in c and "eingeschaltet" in c for c in changes)
        assert not any(c == "A wurde eingeschaltet" for c in changes)

    def test_lights_off_many_summarised(self, sm):
        old = {"lights_on": ["A", "B", "C"]}
        new = {"lights_on": []}
        changes = sm._compare_snapshots(old, new)
        assert any("3 Lichter" in c and "ausgeschaltet" in c for c in changes)

    def test_lights_off_few_not_reported(self, sm):
        old = {"lights_on": ["Lamp A"]}
        new = {"lights_on": []}
        changes = sm._compare_snapshots(old, new)
        assert not any("Lamp A" in c for c in changes)

    # --- Media ---

    def test_media_started(self, sm):
        old = {"media_playing": []}
        new = {"media_playing": ["Wohnzimmer"]}
        changes = sm._compare_snapshots(old, new)
        assert any("Musik" in c for c in changes)

    def test_media_stopped(self, sm):
        old = {"media_playing": ["Wohnzimmer"]}
        new = {"media_playing": []}
        changes = sm._compare_snapshots(old, new)
        assert any("gestoppt" in c for c in changes)

    # --- Batteries ---

    def test_battery_new_low(self, sm):
        old = {}
        new = {"low_batteries": {"Sensor": 12}}
        changes = sm._compare_snapshots(old, new)
        assert any("Batterie" in c and "12%" in c for c in changes)

    def test_battery_drop(self, sm):
        old = {"low_batteries": {"Sensor": 18}}
        new = {"low_batteries": {"Sensor": 10}}
        changes = sm._compare_snapshots(old, new)
        assert any("18%" in c and "10%" in c for c in changes)

    def test_battery_small_drop_ignored(self, sm):
        old = {"low_batteries": {"Sensor": 18}}
        new = {"low_batteries": {"Sensor": 15}}
        changes = sm._compare_snapshots(old, new)
        assert not any("Sensor" in c for c in changes)

    # --- Vacuum ---

    def test_vacuum_state_change(self, sm):
        old = {"vacuum_states": {"Robo": "docked"}}
        new = {"vacuum_states": {"Robo": "cleaning"}}
        changes = sm._compare_snapshots(old, new)
        assert any("saugt" in c for c in changes)

    def test_vacuum_returning(self, sm):
        old = {"vacuum_states": {"Robo": "cleaning"}}
        new = {"vacuum_states": {"Robo": "returning"}}
        changes = sm._compare_snapshots(old, new)
        assert any("f\u00e4hrt zur\u00fcck" in c for c in changes)

    def test_vacuum_error(self, sm):
        old = {"vacuum_states": {"Robo": "cleaning"}}
        new = {"vacuum_states": {"Robo": "error"}}
        changes = sm._compare_snapshots(old, new)
        assert any("FEHLER" in c for c in changes)

    def test_vacuum_no_change(self, sm):
        old = {"vacuum_states": {"Robo": "docked"}}
        new = {"vacuum_states": {"Robo": "docked"}}
        assert sm._compare_snapshots(old, new) == []

    def test_vacuum_unknown_state_uses_raw(self, sm):
        old = {"vacuum_states": {"Robo": "docked"}}
        new = {"vacuum_states": {"Robo": "custom_mode"}}
        changes = sm._compare_snapshots(old, new)
        assert any("custom_mode" in c for c in changes)

    def test_vacuum_new_appears(self, sm):
        old = {"vacuum_states": {}}
        new = {"vacuum_states": {"Robo": "cleaning"}}
        changes = sm._compare_snapshots(old, new)
        assert any("saugt" in c for c in changes)

    # --- Causal linking ---

    def test_causal_window_temp_drop(self, sm):
        old = {"open_windows": [], "temperatures": {"Wohnzimmer": 22.0}}
        new = {"open_windows": ["Kueche"], "temperatures": {"Wohnzimmer": 19.0}}
        changes = sm._compare_snapshots(old, new)
        causal = [c for c in changes if "vermutlich" in c]
        assert len(causal) == 1
        assert "Kueche" in causal[0]

    def test_no_causal_if_no_window_opened(self, sm):
        old = {"open_windows": ["Kueche"], "temperatures": {"Wohnzimmer": 22.0}}
        new = {"open_windows": ["Kueche"], "temperatures": {"Wohnzimmer": 19.0}}
        changes = sm._compare_snapshots(old, new)
        assert not any("vermutlich" in c for c in changes)
        assert any("gesunken" in c for c in changes)

    def test_no_causal_if_temp_rose(self, sm):
        old = {"open_windows": [], "temperatures": {"Room": 18.0}}
        new = {"open_windows": ["Kitchen"], "temperatures": {"Room": 21.0}}
        changes = sm._compare_snapshots(old, new)
        assert not any("vermutlich" in c for c in changes)
        assert any("gestiegen" in c for c in changes)

    # --- Priority ordering ---

    def test_priority_ordering_lock_before_light(self, sm):
        old = {"locks_unlocked": [], "lights_on": []}
        new = {"locks_unlocked": ["Front"], "lights_on": ["Lamp"]}
        changes = sm._compare_snapshots(old, new)
        lock_idx = next(i for i, c in enumerate(changes) if "entriegelt" in c)
        light_idx = next(i for i, c in enumerate(changes) if "eingeschaltet" in c)
        assert lock_idx < light_idx

    def test_priority_ordering_security_first(self, sm):
        old = {
            "locks_unlocked": [],
            "open_windows": [],
            "lights_on": [],
            "media_playing": [],
        }
        new = {
            "locks_unlocked": ["Front"],
            "open_windows": ["Kueche"],
            "lights_on": ["Lamp"],
            "media_playing": ["Speaker"],
        }
        changes = sm._compare_snapshots(old, new)
        assert "entriegelt" in changes[0]

    def test_priority_window_before_media(self, sm):
        old = {"open_windows": [], "media_playing": []}
        new = {"open_windows": ["Balkon"], "media_playing": ["Speaker"]}
        changes = sm._compare_snapshots(old, new)
        win_idx = next(i for i, c in enumerate(changes) if "ge\u00f6ffnet" in c)
        media_idx = next(i for i, c in enumerate(changes) if "Musik" in c)
        assert win_idx < media_idx

    # --- Temperature drift ---

    def test_temperature_drift_after_1h(self, sm):
        ts_old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        old = {"timestamp": ts_old, "temperatures": {"Room": 20.0}}
        new = {"temperatures": {"Room": 21.0}}
        changes = sm._compare_snapshots(old, new)
        assert any("langsam" in c for c in changes)

    def test_temperature_drift_not_if_recent(self, sm):
        ts_old = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        old = {"timestamp": ts_old, "temperatures": {"Room": 20.0}}
        new = {"temperatures": {"Room": 21.0}}
        changes = sm._compare_snapshots(old, new)
        assert not any("langsam" in c for c in changes)

    def test_temperature_drift_not_if_too_small(self, sm):
        ts_old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        old = {"timestamp": ts_old, "temperatures": {"Room": 20.0}}
        new = {"temperatures": {"Room": 20.3}}
        changes = sm._compare_snapshots(old, new)
        assert not any("langsam" in c for c in changes)

    def test_temperature_drift_not_if_above_main_threshold(self, sm):
        ts_old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        old = {"timestamp": ts_old, "temperatures": {"Room": 20.0}}
        new = {"temperatures": {"Room": 23.0}}
        changes = sm._compare_snapshots(old, new)
        assert any("gestiegen" in c for c in changes)
        assert not any("langsam" in c for c in changes)

    # --- Config ---

    def test_custom_temp_threshold(self):
        with patch(
            "assistant.situation_model.yaml_config",
            {"situation_model": {"temp_threshold": 5}},
        ):
            model = SituationModel()
        old = {"temperatures": {"Room": 22.0}}
        new = {"temperatures": {"Room": 19.0}}
        changes = model._compare_snapshots(old, new)
        assert changes == []

    # --- Empty / missing keys ---

    def test_compare_empty_snapshots(self, sm):
        assert sm._compare_snapshots({}, {}) == []

    def test_compare_missing_keys_in_old(self, sm):
        old = {}
        new = {
            "temperatures": {"Room": 20.0},
            "open_windows": ["Kitchen"],
            "lights_on": ["Lamp"],
        }
        changes = sm._compare_snapshots(old, new)
        assert any("Kitchen" in c for c in changes)

    def test_compare_multiple_temp_changes(self, sm):
        """Multiple temperature changes are all reported."""
        old = {"temperatures": {"Room A": 22.0, "Room B": 18.0}}
        new = {"temperatures": {"Room A": 19.0, "Room B": 21.0}}
        changes = sm._compare_snapshots(old, new)
        assert any("Room A" in c and "gesunken" in c for c in changes)
        assert any("Room B" in c and "gestiegen" in c for c in changes)
