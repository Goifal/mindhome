"""
Tests fuer situation_model.py - Haus-Veraenderungs-Tracking zwischen Gespraechen.

Testet SituationModel: Snapshot-Bau, Snapshot-Vergleich, Prioritaetssortierung.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# _build_snapshot
# ---------------------------------------------------------------------------

@patch("assistant.situation_model.yaml_config", {})
class TestBuildSnapshot:
    """Tests fuer den kompakten Hausstatus-Snapshot."""

    def _model(self):
        from assistant.situation_model import SituationModel
        return SituationModel()

    def test_empty_states(self):
        snap = self._model()._build_snapshot([])
        assert snap["temperatures"] == {}
        assert snap["open_windows"] == []
        assert snap["lights_on"] == []

    def test_climate_temperature(self):
        states = [{
            "entity_id": "climate.wohnzimmer",
            "state": "heat",
            "attributes": {"friendly_name": "Wohnzimmer", "current_temperature": 22.3, "temperature": 23.0},
        }]
        snap = self._model()._build_snapshot(states)
        assert snap["temperatures"]["Wohnzimmer"] == 22.3
        assert snap["climate_targets"]["Wohnzimmer"] == 23.0

    def test_sensor_temperature(self):
        states = [{
            "entity_id": "sensor.aussen_temperature",
            "state": "15.5",
            "attributes": {"friendly_name": "Aussen"},
        }]
        snap = self._model()._build_snapshot(states)
        assert snap["temperatures"]["Aussen"] == 15.5

    def test_sensor_temperature_invalid_ignored(self):
        states = [{
            "entity_id": "sensor.broken_temperature",
            "state": "unavailable",
            "attributes": {"friendly_name": "Broken"},
        }]
        snap = self._model()._build_snapshot(states)
        assert "Broken" not in snap["temperatures"]

    def test_sensor_temperature_plausibility(self):
        states = [{
            "entity_id": "sensor.weird_temperature",
            "state": "999",
            "attributes": {"friendly_name": "Weird"},
        }]
        snap = self._model()._build_snapshot(states)
        assert "Weird" not in snap["temperatures"]

    def test_open_window(self):
        states = [{
            "entity_id": "binary_sensor.kuechen_window",
            "state": "on",
            "attributes": {"friendly_name": "Kuechen-Fenster"},
        }]
        snap = self._model()._build_snapshot(states)
        assert "Kuechen-Fenster" in snap["open_windows"]

    def test_closed_window_not_included(self):
        states = [{
            "entity_id": "binary_sensor.kuechen_window",
            "state": "off",
            "attributes": {"friendly_name": "Kuechen-Fenster"},
        }]
        snap = self._model()._build_snapshot(states)
        assert snap["open_windows"] == []

    def test_open_door(self):
        states = [{
            "entity_id": "binary_sensor.front_door",
            "state": "on",
            "attributes": {"friendly_name": "Haustuer"},
        }]
        snap = self._model()._build_snapshot(states)
        assert "Haustuer" in snap["open_doors"]

    def test_light_on(self):
        states = [{
            "entity_id": "light.wohnzimmer",
            "state": "on",
            "attributes": {"friendly_name": "Wohnzimmer Licht"},
        }]
        snap = self._model()._build_snapshot(states)
        assert "Wohnzimmer Licht" in snap["lights_on"]

    def test_lock_unlocked(self):
        states = [{
            "entity_id": "lock.front",
            "state": "unlocked",
            "attributes": {"friendly_name": "Haustuer-Schloss"},
        }]
        snap = self._model()._build_snapshot(states)
        assert "Haustuer-Schloss" in snap["locks_unlocked"]

    def test_lock_locked_not_included(self):
        states = [{
            "entity_id": "lock.front",
            "state": "locked",
            "attributes": {"friendly_name": "Haustuer-Schloss"},
        }]
        snap = self._model()._build_snapshot(states)
        assert snap["locks_unlocked"] == []

    def test_cover_open(self):
        states = [{
            "entity_id": "cover.wohnzimmer",
            "state": "open",
            "attributes": {"friendly_name": "Rollladen WZ"},
        }]
        snap = self._model()._build_snapshot(states)
        assert "Rollladen WZ" in snap["covers_open"]

    def test_person_tracking(self):
        states = [{
            "entity_id": "person.max",
            "state": "home",
            "attributes": {"friendly_name": "Max"},
        }]
        snap = self._model()._build_snapshot(states)
        assert snap["persons"]["Max"] == "home"

    def test_media_playing(self):
        states = [{
            "entity_id": "media_player.wohnzimmer",
            "state": "playing",
            "attributes": {"friendly_name": "Sonos WZ"},
        }]
        snap = self._model()._build_snapshot(states)
        assert "Sonos WZ" in snap["media_playing"]

    def test_low_battery(self):
        states = [{
            "entity_id": "sensor.motion",
            "state": "off",
            "attributes": {"friendly_name": "Bewegung", "battery_level": 15},
        }]
        snap = self._model()._build_snapshot(states)
        assert snap["low_batteries"]["Bewegung"] == 15

    def test_normal_battery_not_tracked(self):
        states = [{
            "entity_id": "sensor.motion",
            "state": "off",
            "attributes": {"friendly_name": "Bewegung", "battery_level": 80},
        }]
        snap = self._model()._build_snapshot(states)
        assert "low_batteries" not in snap or "Bewegung" not in snap.get("low_batteries", {})

    def test_vacuum_state(self):
        states = [{
            "entity_id": "vacuum.roborock",
            "state": "cleaning",
            "attributes": {"friendly_name": "Roborock"},
        }]
        snap = self._model()._build_snapshot(states)
        assert snap["vacuum_states"]["Roborock"] == "cleaning"


# ---------------------------------------------------------------------------
# _compare_snapshots
# ---------------------------------------------------------------------------

@patch("assistant.situation_model.yaml_config", {})
class TestCompareSnapshots:
    """Tests fuer Snapshot-Vergleich und Aenderungserkennung."""

    def _model(self):
        from assistant.situation_model import SituationModel
        return SituationModel()

    def _base_snapshot(self, **overrides):
        snap = {
            "timestamp": (datetime.now() - timedelta(minutes=30)).isoformat(),
            "temperatures": {},
            "open_windows": [],
            "open_doors": [],
            "lights_on": [],
            "locks_unlocked": [],
            "covers_open": [],
            "persons": {},
            "media_playing": [],
            "climate_targets": {},
        }
        snap.update(overrides)
        return snap

    def test_no_changes(self):
        old = self._base_snapshot()
        new = self._base_snapshot()
        changes = self._model()._compare_snapshots(old, new)
        assert changes == []

    # --- Temperature ---

    def test_temp_drop_above_threshold(self):
        old = self._base_snapshot(temperatures={"WZ": 22.0})
        new = self._base_snapshot(temperatures={"WZ": 19.0})
        changes = self._model()._compare_snapshots(old, new)
        assert any("gesunken" in c for c in changes)

    def test_temp_rise_above_threshold(self):
        old = self._base_snapshot(temperatures={"WZ": 18.0})
        new = self._base_snapshot(temperatures={"WZ": 21.0})
        changes = self._model()._compare_snapshots(old, new)
        assert any("gestiegen" in c for c in changes)

    def test_temp_change_below_threshold_ignored(self):
        old = self._base_snapshot(temperatures={"WZ": 22.0})
        new = self._base_snapshot(temperatures={"WZ": 21.5})
        changes = self._model()._compare_snapshots(old, new)
        assert not any("WZ" in c for c in changes)

    # --- Windows ---

    def test_window_opened(self):
        old = self._base_snapshot(open_windows=[])
        new = self._base_snapshot(open_windows=["Kuechen-Fenster"])
        changes = self._model()._compare_snapshots(old, new)
        assert any("Kuechen-Fenster" in c and "geöffnet" in c for c in changes)

    def test_window_closed(self):
        old = self._base_snapshot(open_windows=["Kuechen-Fenster"])
        new = self._base_snapshot(open_windows=[])
        changes = self._model()._compare_snapshots(old, new)
        assert any("Kuechen-Fenster" in c and "geschlossen" in c for c in changes)

    # --- Causal linking ---

    def test_causal_window_temp_drop(self):
        old = self._base_snapshot(
            open_windows=[],
            temperatures={"Kueche": 22.0},
        )
        new = self._base_snapshot(
            open_windows=["Kuechen-Fenster"],
            temperatures={"Kueche": 18.0},
        )
        changes = self._model()._compare_snapshots(old, new)
        assert any("vermutlich weil" in c for c in changes)

    # --- Doors ---

    def test_door_opened(self):
        old = self._base_snapshot(open_doors=[])
        new = self._base_snapshot(open_doors=["Haustuer"])
        changes = self._model()._compare_snapshots(old, new)
        assert any("Haustuer" in c and "geöffnet" in c for c in changes)

    def test_door_closed(self):
        old = self._base_snapshot(open_doors=["Haustuer"])
        new = self._base_snapshot(open_doors=[])
        changes = self._model()._compare_snapshots(old, new)
        assert any("Haustuer" in c and "geschlossen" in c for c in changes)

    # --- Locks ---

    def test_lock_unlocked(self):
        old = self._base_snapshot(locks_unlocked=[])
        new = self._base_snapshot(locks_unlocked=["Haustuer-Schloss"])
        changes = self._model()._compare_snapshots(old, new)
        assert any("entriegelt" in c for c in changes)

    def test_lock_locked(self):
        old = self._base_snapshot(locks_unlocked=["Haustuer-Schloss"])
        new = self._base_snapshot(locks_unlocked=[])
        changes = self._model()._compare_snapshots(old, new)
        assert any("verriegelt" in c for c in changes)

    # --- Persons ---

    def test_person_arrived(self):
        old = self._base_snapshot(persons={"Max": "not_home"})
        new = self._base_snapshot(persons={"Max": "home"})
        changes = self._model()._compare_snapshots(old, new)
        assert any("nach Hause gekommen" in c for c in changes)

    def test_person_left(self):
        old = self._base_snapshot(persons={"Max": "home"})
        new = self._base_snapshot(persons={"Max": "not_home"})
        changes = self._model()._compare_snapshots(old, new)
        assert any("Haus verlassen" in c for c in changes)

    def test_person_no_change(self):
        old = self._base_snapshot(persons={"Max": "home"})
        new = self._base_snapshot(persons={"Max": "home"})
        changes = self._model()._compare_snapshots(old, new)
        assert not any("Max" in c for c in changes)

    # --- Lights ---

    def test_single_light_on(self):
        old = self._base_snapshot(lights_on=[])
        new = self._base_snapshot(lights_on=["Kueche"])
        changes = self._model()._compare_snapshots(old, new)
        assert any("Kueche" in c and "eingeschaltet" in c for c in changes)

    def test_many_lights_on_summarized(self):
        old = self._base_snapshot(lights_on=[])
        new = self._base_snapshot(lights_on=["L1", "L2", "L3"])
        changes = self._model()._compare_snapshots(old, new)
        assert any("3 Lichter" in c for c in changes)

    def test_many_lights_off_summarized(self):
        old = self._base_snapshot(lights_on=["L1", "L2", "L3"])
        new = self._base_snapshot(lights_on=[])
        changes = self._model()._compare_snapshots(old, new)
        assert any("3 Lichter" in c and "ausgeschaltet" in c for c in changes)

    # --- Media ---

    def test_media_started(self):
        old = self._base_snapshot(media_playing=[])
        new = self._base_snapshot(media_playing=["Sonos WZ"])
        changes = self._model()._compare_snapshots(old, new)
        assert any("Musik" in c for c in changes)

    def test_media_stopped(self):
        old = self._base_snapshot(media_playing=["Sonos WZ"])
        new = self._base_snapshot(media_playing=[])
        changes = self._model()._compare_snapshots(old, new)
        assert any("gestoppt" in c for c in changes)

    # --- Batteries ---

    def test_new_low_battery(self):
        old = self._base_snapshot()
        new = self._base_snapshot()
        new["low_batteries"] = {"Sensor1": 10}
        changes = self._model()._compare_snapshots(old, new)
        assert any("Batterie" in c and "10%" in c for c in changes)

    def test_battery_dropped(self):
        old = self._base_snapshot()
        old["low_batteries"] = {"Sensor1": 18}
        new = self._base_snapshot()
        new["low_batteries"] = {"Sensor1": 12}
        changes = self._model()._compare_snapshots(old, new)
        assert any("18%" in c and "12%" in c for c in changes)

    def test_battery_small_drop_ignored(self):
        old = self._base_snapshot()
        old["low_batteries"] = {"Sensor1": 15}
        new = self._base_snapshot()
        new["low_batteries"] = {"Sensor1": 13}
        changes = self._model()._compare_snapshots(old, new)
        assert not any("Sensor1" in c for c in changes)

    # --- Vacuum ---

    def test_vacuum_state_change(self):
        old = self._base_snapshot()
        old["vacuum_states"] = {"Roborock": "docked"}
        new = self._base_snapshot()
        new["vacuum_states"] = {"Roborock": "cleaning"}
        changes = self._model()._compare_snapshots(old, new)
        assert any("saugt" in c for c in changes)

    def test_vacuum_error(self):
        old = self._base_snapshot()
        old["vacuum_states"] = {"Roborock": "cleaning"}
        new = self._base_snapshot()
        new["vacuum_states"] = {"Roborock": "error"}
        changes = self._model()._compare_snapshots(old, new)
        assert any("FEHLER" in c for c in changes)

    def test_vacuum_no_change(self):
        old = self._base_snapshot()
        old["vacuum_states"] = {"Roborock": "docked"}
        new = self._base_snapshot()
        new["vacuum_states"] = {"Roborock": "docked"}
        changes = self._model()._compare_snapshots(old, new)
        assert not any("Roborock" in c for c in changes)

    # --- Temperature Drift ---

    def test_temp_drift_over_1h(self):
        old = self._base_snapshot(
            temperatures={"WZ": 22.0},
            timestamp=(datetime.now() - timedelta(hours=2)).isoformat(),
        )
        new = self._base_snapshot(temperatures={"WZ": 21.0})
        model = self._model()
        model.temp_threshold = 2
        changes = model._compare_snapshots(old, new)
        assert any("langsam" in c for c in changes)

    def test_no_drift_under_1h(self):
        old = self._base_snapshot(
            temperatures={"WZ": 22.0},
            timestamp=(datetime.now() - timedelta(minutes=30)).isoformat(),
        )
        new = self._base_snapshot(temperatures={"WZ": 21.0})
        changes = self._model()._compare_snapshots(old, new)
        assert not any("langsam" in c for c in changes)

    # --- Priority ordering ---

    def test_priority_ordering(self):
        """Locks (prio 1) should come before lights (prio 5)."""
        old = self._base_snapshot(
            locks_unlocked=[],
            lights_on=[],
        )
        new = self._base_snapshot(
            locks_unlocked=["Schloss"],
            lights_on=["Lampe"],
        )
        changes = self._model()._compare_snapshots(old, new)
        lock_idx = next(i for i, c in enumerate(changes) if "entriegelt" in c)
        light_idx = next(i for i, c in enumerate(changes) if "eingeschaltet" in c)
        assert lock_idx < light_idx


# ---------------------------------------------------------------------------
# SituationModel init and async methods (lightweight)
# ---------------------------------------------------------------------------

@patch("assistant.situation_model.yaml_config", {})
class TestSituationModelInit:
    """Tests fuer Initialisierung und Konfiguration."""

    def test_defaults(self):
        from assistant.situation_model import SituationModel
        model = SituationModel()
        assert model.enabled is True
        assert model.min_pause_minutes == 5
        assert model.max_changes == 5
        assert model.temp_threshold == 2

    def test_custom_config(self):
        with patch("assistant.situation_model.yaml_config", {
            "situation_model": {"enabled": False, "min_pause_minutes": 10, "max_changes": 3, "temp_threshold": 1}
        }):
            from assistant.situation_model import SituationModel
            model = SituationModel()
            assert model.enabled is False
            assert model.min_pause_minutes == 10
            assert model.max_changes == 3
            assert model.temp_threshold == 1

    @pytest.mark.asyncio
    async def test_initialize_sets_redis(self, redis_mock):
        from assistant.situation_model import SituationModel
        model = SituationModel()
        await model.initialize(redis_mock)
        assert model.redis is redis_mock

    @pytest.mark.asyncio
    async def test_take_snapshot_disabled(self, redis_mock):
        from assistant.situation_model import SituationModel
        model = SituationModel()
        model.enabled = False
        model.redis = redis_mock
        await model.take_snapshot([{"entity_id": "light.x", "state": "on", "attributes": {}}])
        redis_mock.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_take_snapshot_stores_to_redis(self, redis_mock):
        from assistant.situation_model import SituationModel
        model = SituationModel()
        model.redis = redis_mock
        await model.take_snapshot([{"entity_id": "light.x", "state": "on", "attributes": {"friendly_name": "L"}}])
        assert redis_mock.setex.call_count == 2

    @pytest.mark.asyncio
    async def test_get_situation_delta_no_snapshot(self, redis_mock):
        from assistant.situation_model import SituationModel
        model = SituationModel()
        model.redis = redis_mock
        redis_mock.get = AsyncMock(return_value=None)
        result = await model.get_situation_delta([{"entity_id": "light.x", "state": "on", "attributes": {}}])
        assert result is None

    @pytest.mark.asyncio
    async def test_get_situation_delta_disabled(self, redis_mock):
        from assistant.situation_model import SituationModel
        model = SituationModel()
        model.enabled = False
        model.redis = redis_mock
        result = await model.get_situation_delta([])
        assert result is None
