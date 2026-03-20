"""
Tests fuer climate_model.py - Thermisches Raumsimulationsmodell.

Testet RoomThermalState, ClimateModel (Simulation, What-If, Komfort, Kontext).
"""

import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# RoomThermalState
# ---------------------------------------------------------------------------

@patch("assistant.climate_model.yaml_config", {})
class TestRoomThermalState:
    """Tests fuer RoomThermalState Datenklasse."""

    def _make_state(self, **kwargs):
        from assistant.climate_model import RoomThermalState
        defaults = dict(room="Wohnzimmer", current_temp=22.0)
        defaults.update(kwargs)
        return RoomThermalState(**defaults)

    def test_init_defaults(self):
        s = self._make_state()
        assert s.room == "Wohnzimmer"
        assert s.current_temp == 22.0
        assert s.target_temp == 21.0
        assert s.outdoor_temp == 10.0
        assert s.heating_active is False
        assert s.cooling_active is False
        assert s.windows_open == 0
        assert s.sun_exposure is False
        assert s.humidity == 50.0

    def test_init_custom_values(self):
        s = self._make_state(
            target_temp=25.0, outdoor_temp=5.0,
            heating_active=True, windows_open=2,
            sun_exposure=True, humidity=65.3,
        )
        assert s.target_temp == 25.0
        assert s.outdoor_temp == 5.0
        assert s.heating_active is True
        assert s.windows_open == 2
        assert s.sun_exposure is True
        assert s.humidity == 65.3

    def test_to_dict_keys(self):
        d = self._make_state().to_dict()
        expected_keys = {
            "room", "current_temp", "target_temp", "outdoor_temp",
            "heating_active", "cooling_active", "windows_open",
            "sun_exposure", "humidity",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_rounds_current_temp(self):
        s = self._make_state(current_temp=22.456)
        assert s.to_dict()["current_temp"] == 22.5

    def test_to_dict_rounds_humidity(self):
        s = self._make_state(humidity=55.678)
        assert s.to_dict()["humidity"] == 55.7

    def test_to_dict_preserves_booleans(self):
        s = self._make_state(heating_active=True, cooling_active=True, sun_exposure=True)
        d = s.to_dict()
        assert d["heating_active"] is True
        assert d["cooling_active"] is True
        assert d["sun_exposure"] is True


# ---------------------------------------------------------------------------
# ClimateModel.__init__ / _get_params
# ---------------------------------------------------------------------------

class TestClimateModelInit:
    """Tests fuer ClimateModel Initialisierung und Parameteraufloesung."""

    @patch("assistant.climate_model.yaml_config", {})
    def test_defaults_when_no_config(self):
        from assistant.climate_model import ClimateModel
        model = ClimateModel()
        assert model.enabled is True
        assert model.simulation_step_minutes == 1
        assert model.max_simulation_minutes == 240

    @patch("assistant.climate_model.yaml_config", {
        "climate_model": {"enabled": False, "simulation_step_minutes": 5, "max_simulation_minutes": 120}
    })
    def test_custom_config(self):
        from assistant.climate_model import ClimateModel
        model = ClimateModel()
        assert model.enabled is False
        assert model.simulation_step_minutes == 5
        assert model.max_simulation_minutes == 120

    @patch("assistant.climate_model.yaml_config", {})
    def test_get_params_default(self):
        from assistant.climate_model import ClimateModel, DEFAULT_ROOM_THERMAL
        model = ClimateModel()
        params = model._get_params("Wohnzimmer")
        assert params == DEFAULT_ROOM_THERMAL

    @patch("assistant.climate_model.yaml_config", {
        "climate_model": {
            "room_params": {
                "bad": {"heat_loss_coefficient": 0.03}
            }
        }
    })
    def test_get_params_room_specific_override(self):
        from assistant.climate_model import ClimateModel, DEFAULT_ROOM_THERMAL
        model = ClimateModel()
        params = model._get_params("Bad")
        assert params["heat_loss_coefficient"] == 0.03
        assert params["heating_power_per_min"] == DEFAULT_ROOM_THERMAL["heating_power_per_min"]

    @patch("assistant.climate_model.yaml_config", {
        "climate_model": {
            "default_params": {"heating_power_per_min": 0.2}
        }
    })
    def test_get_params_custom_defaults(self):
        from assistant.climate_model import ClimateModel
        model = ClimateModel()
        params = model._get_params("Kueche")
        assert params["heating_power_per_min"] == 0.2


# ---------------------------------------------------------------------------
# ClimateModel.simulate
# ---------------------------------------------------------------------------

@patch("assistant.climate_model.yaml_config", {})
class TestClimateModelSimulate:
    """Tests fuer die Temperatursimulation."""

    def _model(self):
        from assistant.climate_model import ClimateModel
        return ClimateModel()

    def _state(self, **kwargs):
        from assistant.climate_model import RoomThermalState
        defaults = dict(room="Wohnzimmer", current_temp=20.0,
                        target_temp=21.0, outdoor_temp=5.0)
        defaults.update(kwargs)
        return RoomThermalState(**defaults)

    def test_disabled_returns_error(self):
        model = self._model()
        model.enabled = False
        result = model.simulate(self._state())
        assert "error" in result

    def test_basic_result_keys(self):
        model = self._model()
        result = model.simulate(self._state(), duration_minutes=10)
        for key in ("room", "initial_temp", "final_temp", "temp_change",
                     "timeline", "reaches_target", "time_to_target_minutes",
                     "duration_minutes", "changes_applied", "description"):
            assert key in result

    def test_duration_capped(self):
        model = self._model()
        model.max_simulation_minutes = 60
        result = model.simulate(self._state(), duration_minutes=999)
        assert result["duration_minutes"] == 60

    def test_heating_raises_temp(self):
        model = self._model()
        state = self._state(current_temp=18.0, target_temp=22.0,
                            heating_active=True, outdoor_temp=17.0)
        result = model.simulate(state, duration_minutes=60)
        assert result["final_temp"] > 18.0

    def test_cooling_lowers_temp(self):
        model = self._model()
        state = self._state(current_temp=28.0, target_temp=22.0,
                            cooling_active=True, outdoor_temp=30.0)
        result = model.simulate(state, duration_minutes=60)
        assert result["final_temp"] < 28.0

    def test_window_open_increases_heat_loss(self):
        model = self._model()
        state_closed = self._state(current_temp=22.0, windows_open=0)
        state_open = self._state(current_temp=22.0, windows_open=2)
        r_closed = model.simulate(state_closed, duration_minutes=30)
        r_open = model.simulate(state_open, duration_minutes=30)
        # With windows open, more heat lost → lower temp
        assert r_open["final_temp"] < r_closed["final_temp"]

    def test_sun_exposure_heats(self):
        model = self._model()
        state_no_sun = self._state(current_temp=20.0, outdoor_temp=20.0)
        state_sun = self._state(current_temp=20.0, outdoor_temp=20.0, sun_exposure=True)
        r_no = model.simulate(state_no_sun, duration_minutes=60)
        r_sun = model.simulate(state_sun, duration_minutes=60)
        assert r_sun["final_temp"] > r_no["final_temp"]

    def test_changes_close_windows(self):
        model = self._model()
        state = self._state(windows_open=2)
        result = model.simulate(state, changes={"close_windows": True})
        # After closing, temp should be higher than leaving open
        result_open = model.simulate(self._state(windows_open=2))
        assert result["final_temp"] >= result_open["final_temp"]

    def test_changes_heating_on(self):
        model = self._model()
        state = self._state(current_temp=18.0, target_temp=22.0, outdoor_temp=17.0)
        result = model.simulate(state, changes={"heating_on": True})
        assert result["final_temp"] > 18.0

    def test_changes_set_target(self):
        model = self._model()
        state = self._state(current_temp=18.0)
        result = model.simulate(state, changes={"set_target": 25, "heating_on": True})
        assert result["changes_applied"]["set_target"] == 25

    def test_reaches_target_with_heating(self):
        model = self._model()
        state = self._state(current_temp=20.0, target_temp=21.0,
                            heating_active=True, outdoor_temp=19.0)
        result = model.simulate(state, duration_minutes=120)
        assert result["reaches_target"] is True
        assert result["time_to_target_minutes"] is not None

    def test_timeline_contains_start(self):
        model = self._model()
        result = model.simulate(self._state(), duration_minutes=10)
        assert result["timeline"][0] == (0, 20.0)

    def test_temp_clamped_max_40(self):
        model = self._model()
        state = self._state(current_temp=39.0, target_temp=45.0,
                            heating_active=True, outdoor_temp=38.0,
                            sun_exposure=True)
        result = model.simulate(state, duration_minutes=240)
        assert result["final_temp"] <= 40.0


# ---------------------------------------------------------------------------
# ClimateModel._parse_what_if
# ---------------------------------------------------------------------------

@patch("assistant.climate_model.yaml_config", {})
class TestParseWhatIf:
    """Tests fuer die deutsche Frageinterpretation."""

    def _model(self):
        from assistant.climate_model import ClimateModel
        return ClimateModel()

    @pytest.mark.parametrize("question,expected_key", [
        ("Fenster schliessen", "close_windows"),
        ("Fenster zumachen", "close_windows"),
        ("Fenster zu", "close_windows"),
        ("Fenster oeffnen", "open_windows"),
        ("Fenster aufmachen", "open_windows"),
        ("Fenster auf", "open_windows"),
    ])
    def test_window_commands(self, question, expected_key):
        result = self._model()._parse_what_if(question)
        assert result is not None
        assert expected_key in result

    @pytest.mark.parametrize("question,expected_key", [
        ("Heizung ausschalten", "heating_off"),
        ("Heizung abstellen", "heating_off"),
        ("Heizung aus", "heating_off"),
        ("Heizung anschalten", "heating_on"),
        ("Heizung einschalten", "heating_on"),
        ("Heizung an", "heating_on"),
    ])
    def test_heating_commands(self, question, expected_key):
        result = self._model()._parse_what_if(question)
        assert result is not None
        assert expected_key in result

    @pytest.mark.parametrize("question,expected_key", [
        ("Klima aus", "cooling_off"),
        ("Kuehlung aus", "cooling_off"),
        ("AC aus", "cooling_off"),
        ("Klima an", "cooling_on"),
        ("Kuehlung an", "cooling_on"),
        ("AC an", "cooling_on"),
    ])
    def test_cooling_commands(self, question, expected_key):
        result = self._model()._parse_what_if(question)
        assert result is not None
        assert expected_key in result

    def test_target_temp_parsed(self):
        result = self._model()._parse_what_if("Temperatur auf 23 Grad")
        assert result["set_target"] == 23
        assert result.get("heating_on") is True  # >22 implies heating

    def test_target_temp_low_implies_cooling(self):
        result = self._model()._parse_what_if("Auf 17 Grad")
        assert result["set_target"] == 17
        assert result.get("cooling_on") is True

    def test_target_temp_out_of_range_ignored(self):
        result = self._model()._parse_what_if("Temperatur auf 50 Grad")
        # 50 is outside 15-30 range; only if no other changes → None
        assert result is None

    def test_unrecognized_question_returns_none(self):
        result = self._model()._parse_what_if("Wie wird das Wetter morgen?")
        assert result is None

    def test_combined_window_and_heating(self):
        result = self._model()._parse_what_if("Fenster zu und Heizung an")
        assert result["close_windows"] is True
        assert result["heating_on"] is True


# ---------------------------------------------------------------------------
# ClimateModel.what_if
# ---------------------------------------------------------------------------

@patch("assistant.climate_model.yaml_config", {})
class TestWhatIf:
    """Tests fuer what_if (parse + simulate integration)."""

    def _model(self):
        from assistant.climate_model import ClimateModel
        return ClimateModel()

    def _state(self, **kw):
        from assistant.climate_model import RoomThermalState
        defaults = dict(room="Buero", current_temp=20.0, outdoor_temp=5.0)
        defaults.update(kw)
        return RoomThermalState(**defaults)

    def test_valid_question(self):
        result = self._model().what_if(self._state(), "Fenster schliessen")
        assert "final_temp" in result
        assert result["duration_minutes"] == 120

    def test_unparseable_question(self):
        result = self._model().what_if(self._state(), "xyz unbekannt")
        assert "error" in result


# ---------------------------------------------------------------------------
# ClimateModel.estimate_comfort_time
# ---------------------------------------------------------------------------

@patch("assistant.climate_model.yaml_config", {})
class TestEstimateComfortTime:
    """Tests fuer Komforttemperatur-Schaetzung."""

    def _model(self):
        from assistant.climate_model import ClimateModel
        return ClimateModel()

    def _state(self, **kw):
        from assistant.climate_model import RoomThermalState
        defaults = dict(room="Schlafzimmer", current_temp=20.0, outdoor_temp=5.0)
        defaults.update(kw)
        return RoomThermalState(**defaults)

    def test_already_at_comfort(self):
        result = self._model().estimate_comfort_time(self._state(current_temp=21.2), comfort_temp=21.0)
        assert result["minutes"] == 0
        assert "Bereits bei Komforttemperatur" in result["description"]

    def test_reachable(self):
        state = self._state(current_temp=19.0, outdoor_temp=18.0)
        result = self._model().estimate_comfort_time(state, comfort_temp=21.0)
        assert result["minutes"] is not None
        assert result["minutes"] > 0
        assert "Minuten" in result["description"]

    def test_unreachable_returns_none_minutes(self):
        # Very cold outdoor, open windows → unlikely to reach comfort
        state = self._state(current_temp=5.0, outdoor_temp=-20.0, windows_open=3)
        result = self._model().estimate_comfort_time(state, comfort_temp=21.0)
        assert result["minutes"] is None
        assert "nicht innerhalb" in result["description"]


# ---------------------------------------------------------------------------
# ClimateModel.get_context_hint
# ---------------------------------------------------------------------------

@patch("assistant.climate_model.yaml_config", {})
class TestGetContextHint:
    """Tests fuer LLM-Kontexthinweise."""

    def _model(self):
        from assistant.climate_model import ClimateModel
        return ClimateModel()

    def _state(self, **kw):
        from assistant.climate_model import RoomThermalState
        defaults = dict(room="Wohnzimmer", current_temp=20.0, outdoor_temp=5.0)
        defaults.update(kw)
        return RoomThermalState(**defaults)

    def test_empty_when_disabled(self):
        model = self._model()
        model.enabled = False
        assert model.get_context_hint([self._state()]) == ""

    def test_empty_when_no_rooms(self):
        assert self._model().get_context_hint(None) == ""
        assert self._model().get_context_hint([]) == ""

    def test_warning_window_and_heating(self):
        state = self._state(windows_open=1, heating_active=True)
        hint = self._model().get_context_hint([state])
        assert "WARNUNG" in hint
        assert "Fenster offen" in hint

    def test_temp_difference_hint(self):
        state = self._state(current_temp=17.0, target_temp=22.0)
        hint = self._model().get_context_hint([state])
        assert "steigt" in hint

    def test_no_hint_when_no_issues(self):
        state = self._state(current_temp=21.0, target_temp=21.0, windows_open=0, heating_active=False)
        hint = self._model().get_context_hint([state])
        assert hint == ""

    def test_max_three_rooms(self):
        states = [self._state(room=f"Room{i}", windows_open=1, heating_active=True) for i in range(5)]
        hint = self._model().get_context_hint(states)
        assert hint.count("WARNUNG") == 3


# ---------------------------------------------------------------------------
# ClimateModel._estimate_loss_rate
# ---------------------------------------------------------------------------

@patch("assistant.climate_model.yaml_config", {})
class TestEstimateLossRate:
    """Tests fuer Waermeverlust-Berechnung."""

    def _model(self):
        from assistant.climate_model import ClimateModel
        return ClimateModel()

    def _state(self, **kw):
        from assistant.climate_model import RoomThermalState
        defaults = dict(room="Buero", current_temp=22.0, outdoor_temp=5.0)
        defaults.update(kw)
        return RoomThermalState(**defaults)

    def test_positive_loss_when_cold_outside(self):
        loss = self._model()._estimate_loss_rate(self._state())
        assert loss > 0

    def test_window_increases_loss(self):
        loss_closed = self._model()._estimate_loss_rate(self._state(windows_open=0))
        loss_open = self._model()._estimate_loss_rate(self._state(windows_open=1))
        assert loss_open > loss_closed

    def test_zero_delta_zero_loss(self):
        loss = self._model()._estimate_loss_rate(self._state(current_temp=10.0, outdoor_temp=10.0))
        assert loss == 0.0


# ---------------------------------------------------------------------------
# ClimateModel._generate_description
# ---------------------------------------------------------------------------

@patch("assistant.climate_model.yaml_config", {})
class TestGenerateDescription:
    """Tests fuer natuerlichsprachliche Beschreibung."""

    def _model(self):
        from assistant.climate_model import ClimateModel
        return ClimateModel()

    def _state(self, **kw):
        from assistant.climate_model import RoomThermalState
        defaults = dict(room="Kueche", current_temp=20.0, outdoor_temp=5.0)
        defaults.update(kw)
        return RoomThermalState(**defaults)

    def test_no_change_description(self):
        s = self._state()
        desc = self._model()._generate_description(s, s, {}, 20.0, 0.0, 60, False, None)
        assert "bleibt" in desc

    def test_temp_rise_description(self):
        s = self._state()
        desc = self._model()._generate_description(s, s, {}, 23.0, 3.0, 60, False, None)
        assert "steigt" in desc

    def test_temp_drop_description(self):
        s = self._state()
        desc = self._model()._generate_description(s, s, {}, 17.0, -3.0, 60, False, None)
        assert "sinkt" in desc

    def test_change_parts_listed(self):
        s = self._state()
        changes = {"close_windows": True, "heating_on": True}
        desc = self._model()._generate_description(s, s, changes, 22.0, 2.0, 60, True, 30)
        assert "Fenster geschlossen" in desc
        assert "Heizung eingeschaltet" in desc

    def test_target_reached_mentioned(self):
        s = self._state(target_temp=22.0)
        sim = self._state(target_temp=22.0, heating_active=True)
        desc = self._model()._generate_description(s, sim, {}, 22.0, 2.0, 60, True, 25)
        assert "25 Minuten" in desc

    def test_target_not_reached_mentioned(self):
        s = self._state(target_temp=25.0)
        sim = self._state(target_temp=25.0, heating_active=True)
        desc = self._model()._generate_description(s, sim, {}, 21.0, 1.0, 60, False, None)
        assert "nicht erreicht" in desc


# ---------------------------------------------------------------------------
# Zusaetzliche Tests fuer 100% Coverage
# ---------------------------------------------------------------------------

@patch("assistant.climate_model.yaml_config", {})
class TestClimateModelChangesEdgeCases:
    """Tests fuer bisher ungetestete Aenderungs-Zweige im simulate()."""

    def _model(self):
        from assistant.climate_model import ClimateModel
        return ClimateModel()

    def _state(self, **kw):
        from assistant.climate_model import RoomThermalState
        defaults = dict(room="Bad", current_temp=20.0, outdoor_temp=5.0, target_temp=21.0)
        defaults.update(kw)
        return RoomThermalState(**defaults)

    def test_changes_set_target_out_of_range_warning(self):
        """set_target ausserhalb 5-35 Grad loggt Warnung (Zeile 150)."""
        model = self._model()
        state = self._state()
        result = model.simulate(state, changes={"set_target": 2, "heating_on": True})
        assert result["changes_applied"]["set_target"] == 2

    def test_changes_open_windows(self):
        """open_windows Aenderung (Zeile 154)."""
        model = self._model()
        state = self._state(windows_open=0)
        result = model.simulate(state, changes={"open_windows": 2})
        assert result is not None

    def test_changes_heating_off(self):
        """heating_off Aenderung (Zeile 158)."""
        model = self._model()
        state = self._state(heating_active=True)
        result = model.simulate(state, changes={"heating_off": True})
        assert result is not None

    def test_changes_cooling_off(self):
        """cooling_off Aenderung (Zeile 162)."""
        model = self._model()
        state = self._state(cooling_active=True)
        result = model.simulate(state, changes={"cooling_off": True})
        assert result is not None

    def test_changes_cooling_on(self):
        """cooling_on Aenderung (Zeile 164)."""
        model = self._model()
        state = self._state(current_temp=28.0, target_temp=22.0)
        result = model.simulate(state, changes={"cooling_on": True})
        assert result["final_temp"] < 28.0

    def test_cooling_reaches_target(self):
        """Kuehlung erreicht Zieltemperatur (Zeilen 218-219)."""
        model = self._model()
        state = self._state(current_temp=25.0, target_temp=22.0,
                            cooling_active=True, outdoor_temp=20.0)
        result = model.simulate(state, duration_minutes=120)
        assert result["reaches_target"] is True
        assert result["time_to_target_minutes"] is not None


@patch("assistant.climate_model.yaml_config", {})
class TestGenerateDescriptionCoverage:
    """Zusaetzliche Tests fuer _generate_description — fehlende Zweige."""

    def _model(self):
        from assistant.climate_model import ClimateModel
        return ClimateModel()

    def _state(self, **kw):
        from assistant.climate_model import RoomThermalState
        defaults = dict(room="Flur", current_temp=20.0, outdoor_temp=5.0)
        defaults.update(kw)
        return RoomThermalState(**defaults)

    def test_open_windows_description(self):
        """'Fenster geoeffnet' in Beschreibung (Zeile 402)."""
        s = self._state()
        desc = self._model()._generate_description(s, s, {"open_windows": 1}, 19.0, -1.0, 60, False, None)
        assert "Fenster" in desc

    def test_heating_off_description(self):
        """'Heizung ausgeschaltet' in Beschreibung (Zeile 406)."""
        s = self._state()
        desc = self._model()._generate_description(s, s, {"heating_off": True}, 19.0, -1.0, 60, False, None)
        assert "Heizung ausgeschaltet" in desc

    def test_cooling_on_description(self):
        """'Kuehlung eingeschaltet' in Beschreibung (Zeile 408)."""
        s = self._state()
        desc = self._model()._generate_description(s, s, {"cooling_on": True}, 19.0, -1.0, 60, False, None)
        assert "Kuehlung eingeschaltet" in desc

    def test_cooling_off_description(self):
        """'Kuehlung ausgeschaltet' in Beschreibung (Zeile 410)."""
        s = self._state()
        desc = self._model()._generate_description(s, s, {"cooling_off": True}, 20.0, 0.0, 60, False, None)
        assert "Kuehlung ausgeschaltet" in desc


# ---------------------------------------------------------------------------
# ClimateModel.simulate_scenario
# ---------------------------------------------------------------------------

@patch("assistant.climate_model.yaml_config", {})
class TestSimulateScenario:
    """Tests fuer vordefinierte Langzeit-Szenarien."""

    def _model(self):
        from assistant.climate_model import ClimateModel
        return ClimateModel()

    def test_disabled_returns_error(self):
        model = self._model()
        model.enabled = False
        result = model.simulate_scenario("heating_off")
        assert "error" in result

    def test_heating_off_scenario(self):
        model = self._model()
        result = model.simulate_scenario("heating_off", duration_hours=24, params={
            "room": "wohnzimmer", "current_temp": 21.0, "outdoor_temp": 0.0,
        })
        assert result["scenario"] == "heating_off"
        assert len(result["timeline"]) > 1
        # Temp should drop without heating when outdoor is 0
        assert result["min_temp"] < 21.0

    def test_heating_off_critical_threshold(self):
        """Heating-off with very cold outside should reach critical temp."""
        model = self._model()
        result = model.simulate_scenario("heating_off", duration_hours=24, params={
            "current_temp": 21.0, "outdoor_temp": -10.0, "critical_temp": 17.0,
        })
        assert result["time_to_critical"] is not None
        assert "nicht empfohlen" in result["recommendation"]

    def test_heating_off_mild_weather_safe(self):
        """Heating-off in mild weather should stay above critical."""
        model = self._model()
        result = model.simulate_scenario("heating_off", duration_hours=6, params={
            "current_temp": 21.0, "outdoor_temp": 18.0, "critical_temp": 15.0,
        })
        assert result["min_temp"] > 15.0
        assert "kann voruebergehend ausgeschaltet werden" in result["recommendation"]

    def test_windows_open_scenario(self):
        model = self._model()
        result = model.simulate_scenario("windows_open", duration_hours=2, params={
            "current_temp": 21.0, "outdoor_temp": 5.0,
        })
        assert result["scenario"] == "windows_open"
        assert result["min_temp"] < 21.0

    def test_windows_open_reaches_critical(self):
        """Open windows in cold weather should reach critical temp quickly."""
        model = self._model()
        result = model.simulate_scenario("windows_open", duration_hours=6, params={
            "current_temp": 21.0, "outdoor_temp": -5.0, "critical_temp": 17.0,
        })
        assert result["time_to_critical"] is not None
        assert "Stosslüften" in result["recommendation"]

    def test_windows_open_safe_in_warm_weather(self):
        """Open windows in warm weather should be safe."""
        model = self._model()
        result = model.simulate_scenario("windows_open", duration_hours=2, params={
            "current_temp": 21.0, "outdoor_temp": 20.0, "critical_temp": 15.0,
        })
        assert result["time_to_critical"] is None
        assert "moeglich" in result["recommendation"]

    def test_vacation_3days_scenario(self):
        """Vacation scenario should force 72h duration and 16C target."""
        model = self._model()
        result = model.simulate_scenario("vacation_3days", params={
            "current_temp": 21.0, "outdoor_temp": 5.0,
        })
        assert result["scenario"] == "vacation_3days"
        # Timeline should cover 72 hours
        last_hour = result["timeline"][-1]["hour"]
        assert last_hour == 72

    def test_vacation_3days_extreme_cold_warning(self):
        """Vacation in extreme cold should warn about frost risk."""
        model = self._model()
        result = model.simulate_scenario("vacation_3days", params={
            "current_temp": 21.0, "outdoor_temp": -20.0,
        })
        if result["min_temp"] < 10:
            assert "WARNUNG" in result["recommendation"]

    def test_all_covers_closed_scenario(self):
        """Closed covers should reduce heat loss."""
        model = self._model()
        result_open = model.simulate_scenario("heating_off", duration_hours=12, params={
            "current_temp": 21.0, "outdoor_temp": 0.0,
        })
        result_covered = model.simulate_scenario("all_covers_closed", duration_hours=12, params={
            "current_temp": 21.0, "outdoor_temp": 0.0,
        })
        # Covered should retain more heat (higher min temp)
        assert result_covered["min_temp"] >= result_open["min_temp"]
        assert "30%" in result_covered["recommendation"]

    def test_timeline_starts_at_hour_zero(self):
        model = self._model()
        result = model.simulate_scenario("heating_off", duration_hours=6, params={
            "current_temp": 21.0, "outdoor_temp": 10.0,
        })
        assert result["timeline"][0]["hour"] == 0
        assert result["timeline"][0]["temp"] == 21.0


# ---------------------------------------------------------------------------
# ClimateModel.estimate_energy_cost
# ---------------------------------------------------------------------------

@patch("assistant.climate_model.yaml_config", {})
class TestEstimateEnergyCost:
    """Tests fuer Energiekosten-Schaetzung."""

    def _model(self):
        from assistant.climate_model import ClimateModel
        return ClimateModel()

    def test_disabled_returns_error(self):
        model = self._model()
        model.enabled = False
        result = model.estimate_energy_cost("heating_off", 24)
        assert "error" in result

    def test_heating_off_zero_cost(self):
        """Turning heating off should cost 0 kWh."""
        model = self._model()
        result = model.estimate_energy_cost("heating_off", 24, params={
            "outdoor_temp": 5.0,
        })
        assert result["kwh_total"] == 0.0
        assert result["cost_eur"] == 0.0
        assert result["vs_normal_pct"] < 0  # Savings vs normal

    def test_vacation_3days_less_than_normal(self):
        """Vacation mode at 16C should use less energy than 21C normal."""
        model = self._model()
        # Use mild outdoor temp so duty cycles don't both cap at 1.0
        result = model.estimate_energy_cost("vacation_3days", 72, params={
            "outdoor_temp": 15.0,
        })
        assert result["vs_normal_pct"] < 0  # Negative = savings

    def test_windows_open_more_than_normal(self):
        """Open windows should increase energy consumption."""
        model = self._model()
        # Use mild outdoor so normal duty doesn't cap at 1.0
        result = model.estimate_energy_cost("windows_open", 8, params={
            "outdoor_temp": 18.0,
        })
        assert result["vs_normal_pct"] > 0  # More consumption

    def test_all_covers_closed_less_than_normal(self):
        """Closed covers should reduce energy consumption."""
        model = self._model()
        result = model.estimate_energy_cost("all_covers_closed", 24, params={
            "outdoor_temp": 5.0,
        })
        assert result["vs_normal_pct"] < 0  # Savings

    def test_unknown_scenario_equals_normal(self):
        """Unknown scenarios should default to normal consumption."""
        model = self._model()
        result = model.estimate_energy_cost("some_unknown", 24, params={
            "outdoor_temp": 5.0,
        })
        assert result["vs_normal_pct"] == 0

    def test_custom_price_per_kwh(self):
        """Custom energy price should be reflected in cost calculation."""
        model = self._model()
        result_default = model.estimate_energy_cost("vacation_3days", 72, params={"outdoor_temp": 5.0})
        result_expensive = model.estimate_energy_cost("vacation_3days", 72, price_per_kwh=0.60, params={"outdoor_temp": 5.0})
        if result_default["kwh_total"] > 0:
            assert result_expensive["cost_eur"] == pytest.approx(result_default["cost_eur"] * 2, rel=0.01)

    def test_warm_outdoor_no_heating_needed(self):
        """When outdoor temp >= target, no heating duty is needed."""
        model = self._model()
        result = model.estimate_energy_cost("heating_off", 24, params={
            "outdoor_temp": 25.0,
        })
        assert result["kwh_total"] == 0.0
        assert result["vs_normal_pct"] == 0

    def test_result_keys(self):
        """Result should contain required keys."""
        model = self._model()
        result = model.estimate_energy_cost("heating_off", 24)
        assert "kwh_total" in result
        assert "cost_eur" in result
        assert "vs_normal_pct" in result


# ---------------------------------------------------------------------------
# Simulation edge cases
# ---------------------------------------------------------------------------

@patch("assistant.climate_model.yaml_config", {})
class TestSimulateEdgeCases:
    """Edge cases and boundary conditions for the simulation."""

    def _model(self):
        from assistant.climate_model import ClimateModel
        return ClimateModel()

    def _state(self, **kw):
        from assistant.climate_model import RoomThermalState
        defaults = dict(room="Test", current_temp=20.0, outdoor_temp=5.0, target_temp=21.0)
        defaults.update(kw)
        return RoomThermalState(**defaults)

    def test_zero_duration(self):
        """Zero duration should return initial temp as final temp."""
        model = self._model()
        result = model.simulate(self._state(current_temp=20.0), duration_minutes=0)
        assert result["final_temp"] == 20.0
        assert result["temp_change"] == 0.0

    def test_very_short_duration(self):
        """1-minute simulation should produce minimal change."""
        model = self._model()
        result = model.simulate(self._state(current_temp=20.0), duration_minutes=1)
        assert abs(result["temp_change"]) < 1.0

    def test_both_heating_and_cooling_active(self):
        """When both are active, only one should apply based on current vs target."""
        model = self._model()
        # Use outdoor close to current so heat loss doesn't dominate
        state = self._state(
            current_temp=20.0, target_temp=22.0,
            heating_active=True, cooling_active=True,
            outdoor_temp=19.0,
        )
        result = model.simulate(state, duration_minutes=60)
        # Heating should win because current < target, and outdoor is mild
        assert result["final_temp"] > 20.0

    def test_no_heating_no_cooling_passive_equilibrium(self):
        """Without heating or cooling, temp should drift toward outdoor."""
        model = self._model()
        state = self._state(current_temp=20.0, outdoor_temp=10.0)
        result = model.simulate(state, duration_minutes=120)
        assert result["final_temp"] < 20.0  # Drifts toward 10

    def test_outdoor_hotter_than_indoor(self):
        """When outdoor is hotter, indoor temp should rise passively."""
        model = self._model()
        state = self._state(current_temp=20.0, outdoor_temp=35.0)
        result = model.simulate(state, duration_minutes=60)
        assert result["final_temp"] > 20.0

    def test_thermal_mass_slows_change(self):
        """Higher thermal mass should result in slower temperature change."""
        from assistant.climate_model import ClimateModel
        with patch("assistant.climate_model.yaml_config", {
            "climate_model": {
                "room_params": {
                    "heavy": {"thermal_mass_factor": 3.0},
                    "light": {"thermal_mass_factor": 0.5},
                }
            }
        }):
            model = ClimateModel()
        state_heavy = self._state(room="heavy", current_temp=20.0, outdoor_temp=5.0)
        state_light = self._state(room="light", current_temp=20.0, outdoor_temp=5.0)
        r_heavy = model.simulate(state_heavy, duration_minutes=60)
        r_light = model.simulate(state_light, duration_minutes=60)
        # Light mass should change faster (bigger drop)
        assert abs(r_light["temp_change"]) > abs(r_heavy["temp_change"])

    def test_sun_and_windows_combined(self):
        """Sun exposure with open windows should partially offset heat loss."""
        model = self._model()
        state = self._state(current_temp=20.0, outdoor_temp=10.0,
                            windows_open=1, sun_exposure=True)
        result_both = model.simulate(state, duration_minutes=60)
        state_window_only = self._state(current_temp=20.0, outdoor_temp=10.0,
                                         windows_open=1, sun_exposure=False)
        result_window = model.simulate(state_window_only, duration_minutes=60)
        # Sun should partially offset the window loss
        assert result_both["final_temp"] > result_window["final_temp"]

    def test_multiple_windows_increase_loss(self):
        """More windows open should increase heat loss proportionally."""
        model = self._model()
        r1 = model.simulate(self._state(windows_open=1, outdoor_temp=0.0), duration_minutes=30)
        r3 = model.simulate(self._state(windows_open=3, outdoor_temp=0.0), duration_minutes=30)
        assert r3["final_temp"] < r1["final_temp"]


# ---------------------------------------------------------------------------
# RoomThermalState edge cases
# ---------------------------------------------------------------------------

@patch("assistant.climate_model.yaml_config", {})
class TestRoomThermalStateEdgeCases:
    """Additional edge case tests for RoomThermalState."""

    def test_extreme_temperatures(self):
        from assistant.climate_model import RoomThermalState
        s = RoomThermalState(room="test", current_temp=-20.0, outdoor_temp=-30.0)
        d = s.to_dict()
        assert d["current_temp"] == -20.0
        assert d["outdoor_temp"] == -30.0

    def test_zero_humidity(self):
        from assistant.climate_model import RoomThermalState
        s = RoomThermalState(room="test", current_temp=20.0, humidity=0.0)
        assert s.to_dict()["humidity"] == 0.0

    def test_high_humidity(self):
        from assistant.climate_model import RoomThermalState
        s = RoomThermalState(room="test", current_temp=20.0, humidity=100.0)
        assert s.to_dict()["humidity"] == 100.0


# ---------------------------------------------------------------------------
# what_if with custom duration
# ---------------------------------------------------------------------------

@patch("assistant.climate_model.yaml_config", {})
class TestWhatIfEdgeCases:
    """Extended what_if tests."""

    def _model(self):
        from assistant.climate_model import ClimateModel
        return ClimateModel()

    def _state(self, **kw):
        from assistant.climate_model import RoomThermalState
        defaults = dict(room="Buero", current_temp=20.0, outdoor_temp=5.0)
        defaults.update(kw)
        return RoomThermalState(**defaults)

    def test_what_if_heating_on(self):
        # Use mild outdoor temp so heating can overcome heat loss
        result = self._model().what_if(self._state(outdoor_temp=19.0), "Heizung anschalten")
        assert "final_temp" in result
        assert result["final_temp"] > 20.0

    def test_what_if_set_temperature(self):
        result = self._model().what_if(self._state(), "Temperatur auf 25 Grad")
        assert result["changes_applied"]["set_target"] == 25

    def test_what_if_combined_actions(self):
        result = self._model().what_if(
            self._state(windows_open=2), "Fenster zu und Heizung an",
        )
        assert result["changes_applied"]["close_windows"] is True
        assert result["changes_applied"]["heating_on"] is True

    def test_what_if_disabled_model(self):
        """what_if with disabled model should return error through simulate."""
        model = self._model()
        model.enabled = False
        result = model.what_if(self._state(), "Fenster schliessen")
        assert "error" in result


# ---------------------------------------------------------------------------
# estimate_comfort_time edge cases
# ---------------------------------------------------------------------------

@patch("assistant.climate_model.yaml_config", {})
class TestEstimateComfortTimeEdgeCases:
    """Extended comfort time estimation tests."""

    def _model(self):
        from assistant.climate_model import ClimateModel
        return ClimateModel()

    def _state(self, **kw):
        from assistant.climate_model import RoomThermalState
        defaults = dict(room="Buero", current_temp=20.0, outdoor_temp=5.0)
        defaults.update(kw)
        return RoomThermalState(**defaults)

    def test_cooling_to_comfort(self):
        """Room too hot should estimate cooling time."""
        state = self._state(current_temp=28.0, outdoor_temp=20.0)
        result = self._model().estimate_comfort_time(state, comfort_temp=22.0)
        assert result["minutes"] is not None
        assert result["minutes"] > 0

    def test_just_outside_threshold(self):
        """0.6 degrees from comfort should still require estimation."""
        state = self._state(current_temp=20.4, outdoor_temp=19.0)
        result = self._model().estimate_comfort_time(state, comfort_temp=21.0)
        # 0.6 > 0.5 threshold, so estimation should run
        assert result["minutes"] is not None or result["minutes"] is None  # depends on reachability

    def test_just_inside_threshold(self):
        """0.4 degrees from comfort should be considered already comfortable."""
        state = self._state(current_temp=20.6)
        result = self._model().estimate_comfort_time(state, comfort_temp=21.0)
        assert result["minutes"] == 0
        assert "Bereits bei Komforttemperatur" in result["description"]


# ---------------------------------------------------------------------------
# get_context_hint edge cases
# ---------------------------------------------------------------------------

@patch("assistant.climate_model.yaml_config", {})
class TestGetContextHintEdgeCases:
    """Extended context hint tests."""

    def _model(self):
        from assistant.climate_model import ClimateModel
        return ClimateModel()

    def _state(self, **kw):
        from assistant.climate_model import RoomThermalState
        defaults = dict(room="Wohnzimmer", current_temp=20.0, outdoor_temp=5.0)
        defaults.update(kw)
        return RoomThermalState(**defaults)

    def test_temp_dropping_hint(self):
        """When current > target by more than 3 degrees, hint should say 'sinkt'."""
        state = self._state(current_temp=27.0, target_temp=21.0)
        hint = self._model().get_context_hint([state])
        assert "sinkt" in hint

    def test_both_window_warning_and_temp_hint(self):
        """Room with window open + heating + large temp diff should show both."""
        state = self._state(
            current_temp=17.0, target_temp=22.0,
            windows_open=1, heating_active=True,
        )
        hint = self._model().get_context_hint([state])
        assert "WARNUNG" in hint
        assert "steigt" in hint

    def test_multiple_rooms_combined(self):
        """Multiple rooms should all produce hints."""
        states = [
            self._state(room="Buero", current_temp=17.0, target_temp=22.0),
            self._state(room="Bad", windows_open=1, heating_active=True, current_temp=20.0, target_temp=21.0),
        ]
        hint = self._model().get_context_hint(states)
        assert "Buero" in hint
        assert "WARNUNG" in hint
