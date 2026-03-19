"""Tests for assistant.situation_model -- _build_snapshot and _compare_snapshots."""

import sys
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

import pytest

# Ensure the assistant package is importable regardless of cwd.
_assistant_dir = os.path.join(os.path.dirname(__file__), os.pardir)
if _assistant_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_assistant_dir))

with patch("assistant.situation_model.yaml_config", {}):
    from assistant.situation_model import SituationModel


@pytest.fixture
def sm():
    with patch("assistant.situation_model.yaml_config", {}):
        return SituationModel()


# --- helpers ----------------------------------------------------------------

def _state(entity_id, state="on", attrs=None):
    """Shortcut to build a HA state dict."""
    a = {"friendly_name": entity_id.split(".", 1)[1].replace("_", " ").title()}
    if attrs:
        a.update(attrs)
    return {"entity_id": entity_id, "state": state, "attributes": a}


# ============================================================================
# _build_snapshot tests
# ============================================================================

class TestBuildSnapshot:
    def test_climate_temperature(self, sm):
        states = [_state("climate.living_room", "heat",
                         {"current_temperature": 21.6, "temperature": 22.0})]
        snap = sm._build_snapshot(states)
        assert snap["temperatures"]["Living Room"] == 21.6
        assert snap["climate_targets"]["Living Room"] == 22.0

    def test_climate_without_current_temp(self, sm):
        """Climate entity with no current_temperature should not add to temps."""
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
        """Battery detected via 'battery' attribute (not 'battery_level')."""
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
        """Multiple entity types in a single snapshot."""
        states = [
            _state("climate.living_room", "heat",
                   {"current_temperature": 21.0, "temperature": 22.0}),
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
        """Exactly at threshold (2 degrees) should be reported."""
        old = {"temperatures": {"Room": 20.0}}
        new = {"temperatures": {"Room": 22.0}}
        changes = sm._compare_snapshots(old, new)
        assert any("gestiegen" in c for c in changes)

    # --- Windows ---

    def test_window_opened(self, sm):
        old = {"open_windows": []}
        new = {"open_windows": ["Kueche"]}
        changes = sm._compare_snapshots(old, new)
        assert any("Kueche" in c and "geöffnet" in c for c in changes)

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
        assert any("Haustuer" in c and "geöffnet" in c for c in changes)

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
        """Person not in old snapshot but present in new as 'home'."""
        old = {"persons": {}}
        new = {"persons": {"Bob": "home"}}
        changes = sm._compare_snapshots(old, new)
        assert any("nach Hause gekommen" in c for c in changes)

    def test_person_disappears_from_home(self, sm):
        """Person in old as 'home' but absent from new snapshot."""
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
        # Individual names should NOT appear
        assert not any(c == "A wurde eingeschaltet" for c in changes)

    def test_lights_off_many_summarised(self, sm):
        old = {"lights_on": ["A", "B", "C"]}
        new = {"lights_on": []}
        changes = sm._compare_snapshots(old, new)
        assert any("3 Lichter" in c and "ausgeschaltet" in c for c in changes)

    def test_lights_off_few_not_reported(self, sm):
        """Fewer than 3 lights off are NOT individually reported (code only
        reports summary for >= 3 off)."""
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
        assert any("fährt zurück" in c for c in changes)

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
        """Unknown vacuum state should use the raw state string."""
        old = {"vacuum_states": {"Robo": "docked"}}
        new = {"vacuum_states": {"Robo": "custom_mode"}}
        changes = sm._compare_snapshots(old, new)
        assert any("custom_mode" in c for c in changes)

    def test_vacuum_new_appears(self, sm):
        """Vacuum not in old but in new should report its state."""
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
        # Regular drop should still be reported
        assert any("gesunken" in c for c in changes)

    def test_no_causal_if_temp_rose(self, sm):
        """Causal linking only applies to temp drops, not rises."""
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
        """Lock unlock (prio 1) should come before window opened (prio 2)
        and before light (prio 5)."""
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
        """Window opened (prio 2) should come before media started (prio 4)."""
        old = {"open_windows": [], "media_playing": []}
        new = {"open_windows": ["Balkon"], "media_playing": ["Speaker"]}
        changes = sm._compare_snapshots(old, new)
        win_idx = next(i for i, c in enumerate(changes) if "geöffnet" in c)
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
        """If the change >= temp_threshold it is a normal change, not drift."""
        ts_old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        old = {"timestamp": ts_old, "temperatures": {"Room": 20.0}}
        new = {"temperatures": {"Room": 23.0}}
        changes = sm._compare_snapshots(old, new)
        assert any("gestiegen" in c for c in changes)
        assert not any("langsam" in c for c in changes)

    # --- Config ---

    def test_custom_temp_threshold(self):
        with patch("assistant.situation_model.yaml_config",
                   {"situation_model": {"temp_threshold": 5}}):
            model = SituationModel()
        old = {"temperatures": {"Room": 22.0}}
        new = {"temperatures": {"Room": 19.0}}
        changes = model._compare_snapshots(old, new)
        # 3-degree drop is below custom threshold of 5
        assert changes == []

    # --- Empty / missing keys ---

    def test_compare_empty_snapshots(self, sm):
        assert sm._compare_snapshots({}, {}) == []

    def test_compare_missing_keys_in_old(self, sm):
        """New snapshot has data, old is empty -- should not crash."""
        old = {}
        new = {
            "temperatures": {"Room": 20.0},
            "open_windows": ["Kitchen"],
            "lights_on": ["Lamp"],
        }
        changes = sm._compare_snapshots(old, new)
        assert any("Kitchen" in c for c in changes)
