"""
Comprehensive tests for brain_humanizers.py — Query-Result Humanizer methods.

Tests all humanizer methods:
- _humanize_query_result (dispatch)
- _humanize_weather
- _humanize_calendar
- _humanize_entity_state
- _humanize_room_climate
- _humanize_house_status (with detail levels: kompakt, normal, ausfuehrlich)
- _humanize_alarms
- _humanize_lights
- _humanize_switches
- _humanize_covers
- _humanize_media
- _humanize_climate_list
"""

import pytest
from unittest.mock import MagicMock, patch

from assistant.brain_humanizers import BrainHumanizersMixin


@pytest.fixture
def humanizer():
    """Mixin instance with mocked _current_person."""
    h = BrainHumanizersMixin()
    h._current_person = "Max"
    return h


# ── _humanize_query_result dispatch ──────────────────────────


class TestHumanizeQueryResultDispatch:
    def test_dispatches_to_weather(self, humanizer):
        with patch.object(humanizer, "_humanize_weather", return_value="Wetter OK") as mock:
            result = humanizer._humanize_query_result("get_weather", "raw")
            mock.assert_called_once_with("raw")
            assert result == "Wetter OK"

    def test_dispatches_to_calendar(self, humanizer):
        with patch.object(humanizer, "_humanize_calendar", return_value="Termine OK") as mock:
            result = humanizer._humanize_query_result("get_calendar_events", "raw")
            mock.assert_called_once()

    def test_dispatches_to_entity_state(self, humanizer):
        with patch.object(humanizer, "_humanize_entity_state", return_value="OK") as mock:
            result = humanizer._humanize_query_result("get_entity_state", "raw")
            mock.assert_called_once()

    def test_dispatches_to_room_climate(self, humanizer):
        with patch.object(humanizer, "_humanize_room_climate", return_value="OK") as mock:
            result = humanizer._humanize_query_result("get_room_climate", "raw")
            mock.assert_called_once()

    def test_dispatches_to_house_status(self, humanizer):
        with patch.object(humanizer, "_humanize_house_status", return_value="OK") as mock:
            result = humanizer._humanize_query_result("get_house_status", "raw")
            mock.assert_called_once()

    def test_dispatches_to_alarms(self, humanizer):
        for fn in ["get_alarms", "set_wakeup_alarm", "cancel_alarm"]:
            with patch.object(humanizer, "_humanize_alarms", return_value="OK") as mock:
                result = humanizer._humanize_query_result(fn, "raw")
                mock.assert_called_once()

    def test_dispatches_to_lights(self, humanizer):
        with patch.object(humanizer, "_humanize_lights", return_value="OK") as mock:
            humanizer._humanize_query_result("get_lights", "raw")
            mock.assert_called_once()

    def test_dispatches_to_switches(self, humanizer):
        with patch.object(humanizer, "_humanize_switches", return_value="OK") as mock:
            humanizer._humanize_query_result("get_switches", "raw")
            mock.assert_called_once()

    def test_dispatches_to_covers(self, humanizer):
        with patch.object(humanizer, "_humanize_covers", return_value="OK") as mock:
            humanizer._humanize_query_result("get_covers", "raw")
            mock.assert_called_once()

    def test_dispatches_to_media(self, humanizer):
        with patch.object(humanizer, "_humanize_media", return_value="OK") as mock:
            humanizer._humanize_query_result("get_media", "raw")
            mock.assert_called_once()

    def test_dispatches_to_climate_list(self, humanizer):
        with patch.object(humanizer, "_humanize_climate_list", return_value="OK") as mock:
            humanizer._humanize_query_result("get_climate", "raw")
            mock.assert_called_once()

    def test_unknown_function_returns_raw(self, humanizer):
        result = humanizer._humanize_query_result("unknown_function", "raw data")
        assert result == "raw data"

    def test_exception_returns_raw(self, humanizer):
        with patch.object(humanizer, "_humanize_weather", side_effect=ValueError("fail")):
            result = humanizer._humanize_query_result("get_weather", "raw data")
            assert result == "raw data"


# ── _humanize_weather ────────────────────────────────────────


class TestHumanizeWeather:
    def test_basic_weather(self, humanizer):
        raw = "AKTUELL: 22°C, sonnig, Wind aus West mit 5 km/h"
        result = humanizer._humanize_weather(raw)
        assert "22 Grad" in result

    def test_cold_weather_gloves(self, humanizer):
        with patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            raw = "AKTUELL: -2°C, bewölkt, Wind aus Nord mit 3 km/h"
            result = humanizer._humanize_weather(raw)
            assert "Handschuhe" in result

    def test_cool_weather_jacket(self, humanizer):
        raw = "AKTUELL: 3°C, bewoelkt, Wind aus Süd mit 2 km/h"
        result = humanizer._humanize_weather(raw)
        assert "Jacke" in result

    def test_hot_weather_drink(self, humanizer):
        with patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            raw = "AKTUELL: 35°C, sonnig, Wind aus Ost mit 2 km/h"
            result = humanizer._humanize_weather(raw)
            assert "trinken" in result

    def test_strong_wind(self, humanizer):
        raw = "AKTUELL: 15°C, bewoelkt, Wind aus Nord mit 25 km/h"
        result = humanizer._humanize_weather(raw)
        assert "Wind" in result

    def test_no_temp_returns_raw(self, humanizer):
        raw = "Keine Wetterdaten verfuegbar"
        result = humanizer._humanize_weather(raw)
        assert result == raw

    def test_with_forecast(self, humanizer):
        raw = (
            "AKTUELL: 15°C, bewoelkt, Wind aus Süd mit 5 km/h\n"
            "VORHERSAGE 2026-03-12: bewoelkt, Hoch 18, Tief 8, Niederschlag 2 mm"
        )
        result = humanizer._humanize_weather(raw)
        assert "18" in result

    def test_condition_mapping(self, humanizer):
        raw = "AKTUELL: 20°C, sonnig, Wind aus Ost mit 3 km/h"
        result = humanizer._humanize_weather(raw)
        assert "sonnig" in result

    def test_wind_reverse_format(self, humanizer):
        raw = "AKTUELL: 15°C, bewoelkt, Wind 20 km/h aus Nord"
        result = humanizer._humanize_weather(raw)
        assert "Wind" in result

    def test_no_wind(self, humanizer):
        raw = "AKTUELL: 15°C, bewoelkt"
        result = humanizer._humanize_weather(raw)
        assert "15 Grad" in result

    def test_forecast_multiple(self, humanizer):
        raw = (
            "AKTUELL: 10°C, bewoelkt, Wind aus Ost mit 5 km/h\n"
            "VORHERSAGE 2026-03-12: sonnig, Hoch 15, Tief 5\n"
            "VORHERSAGE 2026-03-13: regen, Hoch 12, Tief 3, Niederschlag 5 mm"
        )
        result = humanizer._humanize_weather(raw)
        assert "15" in result
        assert "12" in result


# ── _humanize_calendar ───────────────────────────────────────


class TestHumanizeCalendar:
    def test_empty(self, humanizer):
        assert humanizer._humanize_calendar("") == ""

    def test_keine_termine(self, humanizer):
        with patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            result = humanizer._humanize_calendar("TERMINE HEUTE: KEINE TERMINE")
            assert "nichts geplant" in result or "frei" in result

    def test_zero_count(self, humanizer):
        with patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            result = humanizer._humanize_calendar("TERMINE HEUTE (0)")
            assert "geplant" in result or "frei" in result

    def test_single_event(self, humanizer):
        with patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            raw = "TERMINE HEUTE:\n09:00 | Meeting"
            result = humanizer._humanize_calendar(raw)
            assert "Meeting" in result
            assert "9 Uhr" in result

    def test_multiple_events(self, humanizer):
        with patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            raw = "TERMINE HEUTE:\n09:00 | Meeting\n14:30 | Zahnarzt"
            result = humanizer._humanize_calendar(raw)
            assert "2 Termine" in result
            assert "Meeting" in result
            assert "Zahnarzt" in result

    def test_morgen_prefix(self, humanizer):
        with patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            raw = "TERMINE MORGEN:\n10:00 | Termin"
            result = humanizer._humanize_calendar(raw)
            assert "Morgen" in result

    def test_woche_prefix(self, humanizer):
        with patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            raw = "TERMINE DIESE WOCHE:\n10:00 | Termin"
            result = humanizer._humanize_calendar(raw)
            assert "Woche" in result

    def test_full_hour_formatting(self, humanizer):
        with patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            raw = "TERMINE HEUTE:\n08:00 | Fruehstueck"
            result = humanizer._humanize_calendar(raw)
            assert "8 Uhr" in result

    def test_non_full_hour(self, humanizer):
        with patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            raw = "TERMINE HEUTE:\n08:30 | Fruehstueck"
            result = humanizer._humanize_calendar(raw)
            assert "8 Uhr 30" in result

    def test_ganztaegig(self, humanizer):
        with patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            raw = "TERMINE HEUTE:\nganztaegig | Urlaub"
            result = humanizer._humanize_calendar(raw)
            assert "Urlaub" in result

    def test_no_matches_returns_raw(self, humanizer):
        raw = "Unstructured text without events"
        result = humanizer._humanize_calendar(raw)
        assert result == raw


# ── _humanize_entity_state ───────────────────────────────────


class TestHumanizeEntityState:
    def test_short_text_returns_raw(self, humanizer):
        raw = "on"
        assert humanizer._humanize_entity_state(raw) == raw

    def test_few_lines_returns_raw(self, humanizer):
        raw = "Line 1\nLine 2\nLine 3"
        assert humanizer._humanize_entity_state(raw) == raw

    def test_long_text_summarizes(self, humanizer):
        # Build raw with > 80 chars and > 3 lines
        raw = "\n".join([f"- Datenpunkt {i}: Wert {i}" for i in range(10)])
        result = humanizer._humanize_entity_state(raw)
        assert "weitere Datenpunkte" in result


# ── _humanize_room_climate ───────────────────────────────────


class TestHumanizeRoomClimate:
    def test_temp_and_humidity(self, humanizer):
        raw = "Temperatur: 21.5°C, Luftfeuchtigkeit: 55%"
        result = humanizer._humanize_room_climate(raw)
        assert "21.5 Grad" in result
        assert "55%" in result

    def test_only_temp(self, humanizer):
        raw = "22°C"
        result = humanizer._humanize_room_climate(raw)
        assert "22 Grad" in result

    def test_no_data(self, humanizer):
        raw = "Keine Daten"
        assert humanizer._humanize_room_climate(raw) == raw


# ── _humanize_house_status ───────────────────────────────────


class TestHumanizeHouseStatus:
    def test_empty_returns_ruhig(self, humanizer):
        with patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            result = humanizer._humanize_house_status("")
            assert "ruhig" in result

    def test_presence_normal(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "normal"}}
            raw = "Zuhause: Max"
            result = humanizer._humanize_house_status(raw)
            assert "Max ist zuhause" in result

    def test_presence_kompakt(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "kompakt"}}
            raw = "Zuhause: Max, Anna"
            result = humanizer._humanize_house_status(raw)
            assert "2 Personen" in result

    def test_temperatures_normal(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "normal"}}
            raw = "Temperaturen: Wohnzimmer 21°C (Soll 22°C)"
            result = humanizer._humanize_house_status(raw)
            assert "21°C" in result
            assert "Soll" not in result

    def test_temperatures_kompakt(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "kompakt"}}
            raw = "Temperaturen: Wohnzimmer 21°C"
            result = humanizer._humanize_house_status(raw)
            assert "21°C" in result

    def test_lights_normal(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "normal"}}
            raw = "Lichter an: Wohnzimmer, Kueche"
            result = humanizer._humanize_house_status(raw)
            assert "Lichter an" in result

    def test_lights_kompakt(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "kompakt"}}
            raw = "Lichter an: Wohnzimmer, Kueche"
            result = humanizer._humanize_house_status(raw)
            assert "2 Lichter" in result

    def test_lights_many_normal(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "normal"}}
            raw = "Lichter an: L1, L2, L3, L4, L5"
            result = humanizer._humanize_house_status(raw)
            assert "5 Lichter" in result

    def test_all_lights_off(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "normal"}}
            raw = "Alle Lichter aus"
            result = humanizer._humanize_house_status(raw)
            assert "Alle Lichter aus" in result

    def test_security(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "normal"}}
            raw = "Sicherheit: armed_home"
            result = humanizer._humanize_house_status(raw)
            assert "Alarmanlage aktiv" in result

    def test_weather(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "normal"}}
            raw = "Wetter: 20°C, sonnig"
            result = humanizer._humanize_house_status(raw)
            assert "Draussen" in result

    def test_weather_kompakt(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "kompakt"}}
            raw = "Wetter: 20°C, sonnig"
            result = humanizer._humanize_house_status(raw)
            assert "20°C" in result

    def test_media(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "normal"}}
            raw = "Medien aktiv: Spotify im Wohnzimmer"
            result = humanizer._humanize_house_status(raw)
            assert "Medien" in result

    def test_open_items(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "normal"}}
            raw = "Offen: Fenster Kueche"
            result = humanizer._humanize_house_status(raw)
            assert "Offen" in result

    def test_offline_kompakt(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "kompakt"}}
            raw = "Offline (3)"
            result = humanizer._humanize_house_status(raw)
            assert "3 Geraete offline" in result

    def test_unterwegs_not_in_kompakt(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "kompakt"}}
            raw = "Unterwegs: Anna"
            result = humanizer._humanize_house_status(raw)
            assert "Anna" not in result

    def test_ausfuehrlich(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "ausfuehrlich"}}
            raw = "Lichter an: Wohnzimmer: 80%, Kueche: 100%"
            result = humanizer._humanize_house_status(raw)
            assert "80%" in result


# ── _humanize_alarms ─────────────────────────────────────────


class TestHumanizeAlarms:
    def test_no_alarms(self, humanizer):
        result = humanizer._humanize_alarms("keine wecker")
        assert "Kein Wecker" in result

    def test_empty(self, humanizer):
        result = humanizer._humanize_alarms("")
        assert "Kein Wecker" in result

    def test_set_alarm(self, humanizer):
        raw = "Wecker gestellt: morgen um 08:15 Uhr."
        result = humanizer._humanize_alarms(raw)
        assert "steht auf" in result

    def test_single_active_alarm(self, humanizer):
        raw = "Aktive Wecker:\n  - Wecker: 08:15 Uhr (einmalig)"
        result = humanizer._humanize_alarms(raw)
        assert "08:15 Uhr" in result

    def test_multiple_alarms(self, humanizer):
        raw = "Aktive Wecker:\n  - Morgen: 07:00 Uhr (einmalig)\n  - Sport: 06:30 Uhr (Mo-Fr)"
        result = humanizer._humanize_alarms(raw)
        assert "2 Wecker aktiv" in result

    def test_repeating_alarm(self, humanizer):
        raw = "Aktive Wecker:\n  - Arbeit: 06:00 Uhr (Mo-Fr)"
        result = humanizer._humanize_alarms(raw)
        assert "Mo-Fr" in result

    def test_unmatched_returns_raw(self, humanizer):
        raw = "Some unusual alarm format"
        result = humanizer._humanize_alarms(raw)
        assert result == raw


# ── _humanize_lights ─────────────────────────────────────────


class TestHumanizeLights:
    def test_all_off(self, humanizer):
        raw = "- Wohnzimmer Licht [light.wohnzimmer]: off"
        result = humanizer._humanize_lights(raw)
        assert "dunkel" in result.lower()

    def test_single_light_on(self, humanizer):
        raw = "- Wohnzimmer Licht [light.wohnzimmer]: on (80%)"
        result = humanizer._humanize_lights(raw)
        assert "Wohnzimmer Licht" in result
        assert "80%" in result

    def test_multiple_lights(self, humanizer):
        raw = "- Licht 1 [light.l1]: on\n- Licht 2 [light.l2]: on"
        result = humanizer._humanize_lights(raw)
        assert "2 Lichter aktiv" in result

    def test_without_brightness(self, humanizer):
        raw = "- Licht Test [light.test]: on"
        result = humanizer._humanize_lights(raw)
        assert "Licht Test" in result


# ── _humanize_switches ───────────────────────────────────────


class TestHumanizeSwitches:
    def test_all_off(self, humanizer):
        raw = "- Steckdose [switch.test]: off"
        result = humanizer._humanize_switches(raw)
        assert "Alle Schalter aus" in result

    def test_single_on(self, humanizer):
        raw = "- Kaffeemaschine [switch.kaffee]: on"
        result = humanizer._humanize_switches(raw)
        assert "Kaffeemaschine" in result
        assert "laeuft" in result

    def test_multiple_on(self, humanizer):
        raw = "- G1 [switch.g1]: on\n- G2 [switch.g2]: on"
        result = humanizer._humanize_switches(raw)
        assert "2 Geraete aktiv" in result


# ── _humanize_covers ─────────────────────────────────────────


class TestHumanizeCovers:
    def test_all_closed(self, humanizer):
        raw = "- Wohnzimmer [cover.wz]: closed"
        result = humanizer._humanize_covers(raw)
        assert "unten" in result.lower()

    def test_single_open(self, humanizer):
        raw = "- Wohnzimmer [cover.wz]: open (80%)"
        result = humanizer._humanize_covers(raw)
        assert "offen" in result.lower()
        assert "80%" in result

    def test_multiple_open(self, humanizer):
        raw = "- R1 [cover.r1]: open\n- R2 [cover.r2]: open"
        result = humanizer._humanize_covers(raw)
        assert "2 Rolllaeden" in result

    def test_german_offen(self, humanizer):
        raw = "- Test [cover.test]: offen (50%)"
        result = humanizer._humanize_covers(raw)
        assert "offen" in result.lower()


# ── _humanize_media ──────────────────────────────────────────


class TestHumanizeMedia:
    def test_silence(self, humanizer):
        raw = "- Wohnzimmer [media_player.wz]: idle"
        result = humanizer._humanize_media(raw)
        assert "Stille" in result

    def test_single_playing(self, humanizer):
        raw = "- Wohnzimmer [media_player.wz]: playing"
        result = humanizer._humanize_media(raw)
        assert "laeuft" in result

    def test_multiple_playing(self, humanizer):
        raw = "- P1 [mp.1]: playing\n- P2 [mp.2]: playing"
        result = humanizer._humanize_media(raw)
        assert "Medien aktiv" in result


# ── _humanize_climate_list ───────────────────────────────────


class TestHumanizeClimateList:
    def test_with_temps(self, humanizer):
        raw = "- Wohnzimmer [climate.wz]: 21.5°C\n- Schlafzimmer [climate.sz]: 19°C"
        result = humanizer._humanize_climate_list(raw)
        assert "21.5°C" in result
        assert "19°C" in result

    def test_no_temps_short(self, humanizer):
        raw = "Keine Klima-Geraete"
        result = humanizer._humanize_climate_list(raw)
        assert result == raw

    def test_no_temps_long(self, humanizer):
        raw = "\n".join([f"Line {i}" for i in range(10)])
        result = humanizer._humanize_climate_list(raw)
        # Should process without error
        assert isinstance(result, str)


# ── format_comparison ───────────────────────────────────────


class TestFormatComparison:
    def test_unchanged(self, humanizer):
        result = humanizer.format_comparison(20.0, 20.0, "°C")
        assert "unveraendert" in result
        assert "20.0°C" in result

    def test_increase_integer(self, humanizer):
        result = humanizer.format_comparison(22.0, 18.0, "°C")
        assert "↑" in result
        assert "22°C" in result
        assert "18°C" in result
        assert "4°C" in result

    def test_decrease_integer(self, humanizer):
        result = humanizer.format_comparison(15.0, 20.0, "°C")
        assert "↓" in result
        assert "15°C" in result
        assert "20°C" in result
        assert "5°C" in result

    def test_float_formatting(self, humanizer):
        result = humanizer.format_comparison(21.5, 20.3, "°C")
        assert "↑" in result
        assert "21.5°C" in result
        assert "20.3°C" in result

    def test_no_unit(self, humanizer):
        result = humanizer.format_comparison(10.0, 8.0)
        assert "↑" in result
        assert "vorher" in result

    def test_negative_values(self, humanizer):
        result = humanizer.format_comparison(-5.0, -2.0, "°C")
        assert "↓" in result
        assert "3°C" in result


# ── highlight_anomaly ───────────────────────────────────────


class TestHighlightAnomaly:
    def test_empty_values(self, humanizer):
        assert humanizer.highlight_anomaly({}) is None

    def test_single_item(self, humanizer):
        assert humanizer.highlight_anomaly({"door1": "open"}) is None

    def test_no_anomaly_all_closed(self, humanizer):
        values = {"door1": "closed", "door2": "closed", "door3": "open"}
        result = humanizer.highlight_anomaly(values, "Tueren")
        # 1/3 active = not anomaly
        assert result is None

    def test_anomaly_majority_open(self, humanizer):
        values = {"door1": "open", "door2": "open", "door3": "closed"}
        result = humanizer.highlight_anomaly(values, "Tueren")
        assert result is not None
        assert "2/3" in result
        assert "Tueren" in result
        assert "ungewoehnlich" in result

    def test_anomaly_all_on(self, humanizer):
        values = {"sw1": "on", "sw2": "on", "sw3": "on", "sw4": "on"}
        result = humanizer.highlight_anomaly(values, "Schalter")
        assert result is not None
        assert "4/4" in result

    def test_anomaly_boolean_true(self, humanizer):
        values = {"a": True, "b": True, "c": False}
        result = humanizer.highlight_anomaly(values)
        assert result is not None
        assert "Geraete" in result  # default label

    def test_anomaly_offen_state(self, humanizer):
        values = {"w1": "offen", "w2": "offen", "w3": "geschlossen"}
        result = humanizer.highlight_anomaly(values, "Fenster")
        assert result is not None
        assert "2/3" in result

    def test_exactly_half_not_anomaly(self, humanizer):
        values = {"a": "on", "b": "off"}
        result = humanizer.highlight_anomaly(values)
        # 1/2 = not > half
        assert result is None


# ── format_delta_context ────────────────────────────────────


class TestFormatDeltaContext:
    def test_empty_changes(self, humanizer):
        assert humanizer.format_delta_context([]) == ""

    def test_single_change(self, humanizer):
        changes = [{"entity": "Licht", "old_state": "off", "new_state": "on"}]
        result = humanizer.format_delta_context(changes)
        assert "Seit letzter Interaktion" in result
        assert "Licht" in result
        assert "off → on" in result

    def test_change_with_room(self, humanizer):
        changes = [{"entity": "Licht", "old_state": "off", "new_state": "on", "room": "Kueche"}]
        result = humanizer.format_delta_context(changes)
        assert "(Kueche)" in result

    def test_multiple_changes(self, humanizer):
        changes = [
            {"entity": "Licht", "old_state": "off", "new_state": "on"},
            {"entity": "Heizung", "old_state": "22", "new_state": "20"},
        ]
        result = humanizer.format_delta_context(changes)
        assert "Licht" in result
        assert "Heizung" in result

    def test_more_than_five_truncated(self, humanizer):
        changes = [
            {"entity": f"Device{i}", "old_state": "off", "new_state": "on"}
            for i in range(8)
        ]
        result = humanizer.format_delta_context(changes)
        assert "3 weitere" in result
        # Only first 5 devices should be mentioned
        assert "Device0" in result
        assert "Device4" in result
        assert "Device5" not in result

    def test_missing_fields_use_defaults(self, humanizer):
        changes = [{}]  # no entity, old_state, new_state
        result = humanizer.format_delta_context(changes)
        assert "Unbekannt" in result
        assert "? → ?" in result


# ── _humanize_device_command ────────────────────────────────


class TestHumanizeDeviceCommand:
    def test_empty_executed_list(self, humanizer):
        with patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            result = humanizer._humanize_device_command("Mach das Licht an", [])
        assert "Erledigt" in result

    def test_single_light_on(self, humanizer):
        with patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            executed = [{"function": "set_light", "args": {"room": "wohnzimmer", "action": "on"}}]
            result = humanizer._humanize_device_command("Licht an", executed)
        assert "licht" in result.lower()
        assert "eingeschaltet" in result.lower()
        assert "wohnzimmer" in result.lower()

    def test_multiple_actions(self, humanizer):
        with patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            executed = [
                {"function": "set_light", "args": {"room": "wohnzimmer", "action": "off"}},
                {"function": "set_cover", "args": {"room": "schlafzimmer", "action": "close"}},
            ]
            result = humanizer._humanize_device_command("Gute Nacht", executed)
        assert "ausgeschaltet" in result
        assert "heruntergefahren" in result

    def test_three_actions_uses_comma(self, humanizer):
        with patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            executed = [
                {"function": "set_light", "args": {"room": "wohnzimmer", "action": "off"}},
                {"function": "set_cover", "args": {"room": "all", "action": "close"}},
                {"function": "set_switch", "args": {"room": "kueche", "action": "off"}},
            ]
            result = humanizer._humanize_device_command("Alles aus", executed)
        assert " und " in result

    def test_unknown_function_skipped(self, humanizer):
        with patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            executed = [{"function": "unknown_func", "args": {"room": "", "action": ""}}]
            result = humanizer._humanize_device_command("Test", executed)
        assert "Erledigt" in result

    def test_climate_action(self, humanizer):
        with patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            executed = [{"function": "set_climate", "args": {"room": "wohnzimmer"}}]
            result = humanizer._humanize_device_command("Heizung", executed)
        assert "Heizung" in result
        assert "angepasst" in result


# ── _describe_action ────────────────────────────────────────


class TestDescribeAction:
    def test_cover_close(self):
        result = BrainHumanizersMixin._describe_action("set_cover", "close", "wohnzimmer")
        assert "heruntergefahren" in result
        assert "Wohnzimmer" in result

    def test_cover_open(self):
        result = BrainHumanizersMixin._describe_action("set_cover", "open", "")
        assert "hochgefahren" in result

    def test_cover_stop(self):
        result = BrainHumanizersMixin._describe_action("set_cover", "stop", "buero")
        assert "gestoppt" in result

    def test_light_on(self):
        result = BrainHumanizersMixin._describe_action("set_light", "on", "bad")
        assert "eingeschaltet" in result
        assert "Bad" in result

    def test_light_off_no_room(self):
        result = BrainHumanizersMixin._describe_action("set_light", "off", "")
        assert "ausgeschaltet" in result

    def test_switch_on(self):
        result = BrainHumanizersMixin._describe_action("set_switch", "on", "garage")
        assert "eingeschaltet" in result
        assert "Garage" in result

    def test_feminine_room_uses_in_der(self):
        result = BrainHumanizersMixin._describe_action("set_light", "on", "kueche")
        assert "in der Kueche" in result

    def test_room_all_uses_ueberall(self):
        result = BrainHumanizersMixin._describe_action("set_light", "off", "all")
        assert "überall" in result

    def test_climate_special_case(self):
        result = BrainHumanizersMixin._describe_action("set_climate", "heat", "wohnzimmer")
        assert "Heizung" in result
        assert "angepasst" in result

    def test_unknown_function(self):
        result = BrainHumanizersMixin._describe_action("unknown", "action", "room")
        assert result is None

    def test_unknown_action_in_known_function(self):
        result = BrainHumanizersMixin._describe_action("set_light", "toggle", "room")
        assert result is None


# ── _humanize_house_status extended ─────────────────────────


class TestHumanizeHouseStatusExtended:
    def test_security_triggered(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "normal"}}
            raw = "Sicherheit: triggered"
            result = humanizer._humanize_house_status(raw)
            assert "ALARM AUSGELOEST" in result

    def test_security_disarmed(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "normal"}}
            raw = "Sicherheit: disarmed"
            result = humanizer._humanize_house_status(raw)
            assert "Alarmanlage aus" in result

    def test_security_unknown_is_empty(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "normal"}}
            raw = "Sicherheit: unknown"
            result = humanizer._humanize_house_status(raw)
            # "unknown" maps to "" which is falsy, so nothing appended
            assert "ruhig" in result

    def test_multiple_persons_zuhause(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "normal"}}
            raw = "Zuhause: Max, Anna, Tom"
            result = humanizer._humanize_house_status(raw)
            assert "sind zuhause" in result

    def test_unterwegs_normal_shown(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "normal"}}
            raw = "Unterwegs: Anna"
            result = humanizer._humanize_house_status(raw)
            assert "Anna unterwegs" in result

    def test_open_items_kompakt(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "kompakt"}}
            raw = "Offen: Fenster Kueche, Tuer Flur"
            result = humanizer._humanize_house_status(raw)
            assert "2 offen" in result

    def test_media_kompakt(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "kompakt"}}
            raw = "Medien aktiv: Spotify im Wohnzimmer"
            result = humanizer._humanize_house_status(raw)
            assert "Medien aktiv" in result
            # kompakt should not have details
            assert "Spotify" not in result

    def test_offline_normal(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "normal"}}
            raw = "Offline (3)"
            result = humanizer._humanize_house_status(raw)
            assert "Offline (3)" in result

    def test_combined_status(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "normal"}}
            raw = "Zuhause: Max\nLichter an: Wohnzimmer\nWetter: 18°C, sonnig"
            result = humanizer._humanize_house_status(raw)
            assert "Max ist zuhause" in result
            assert "Lichter an" in result
            assert "Draussen" in result

    def test_temperatures_ausfuehrlich(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "ausfuehrlich"}}
            raw = "Temperaturen: Wohnzimmer 21°C (Soll 22°C)"
            result = humanizer._humanize_house_status(raw)
            # ausfuehrlich keeps all detail including Soll
            assert "Soll 22°C" in result

    def test_weather_normal_format(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "normal"}}
            raw = "Wetter: 15°C, bewoelkt"
            result = humanizer._humanize_house_status(raw)
            assert "Draussen: 15°C, bewoelkt" in result

    def test_weather_kompakt_no_temp_match(self, humanizer):
        with patch("assistant.brain_humanizers.cfg") as mock_cfg, \
             patch("assistant.brain_humanizers.get_person_title", return_value="Sir"):
            mock_cfg.yaml_config = {"house_status": {"detail_level": "kompakt"}}
            raw = "Wetter: bewoelkt"
            result = humanizer._humanize_house_status(raw)
            assert "Draussen: bewoelkt" in result


# ── _humanize_media extended ────────────────────────────────


class TestHumanizeMediaExtended:
    def test_spielt_keyword(self, humanizer):
        raw = "- Wohnzimmer [media_player.wz]: spielt Musik"
        result = humanizer._humanize_media(raw)
        assert "laeuft" in result
        assert "Wohnzimmer" in result


# ── _humanize_weather extended ──────────────────────────────


class TestHumanizeWeatherExtended:
    def test_no_condition_match(self, humanizer):
        raw = "AKTUELL: 18°C, unbekannt, Wind aus West mit 5 km/h"
        result = humanizer._humanize_weather(raw)
        assert "18 Grad draussen" in result

    def test_forecast_with_precipitation(self, humanizer):
        raw = (
            "AKTUELL: 15°C, bewoelkt, Wind aus Süd mit 5 km/h\n"
            "VORHERSAGE 2026-03-12: regen, Hoch 12, Tief 5, Niederschlag 8 mm"
        )
        result = humanizer._humanize_weather(raw)
        assert "8 mm Regen" in result

    def test_forecast_zero_precipitation(self, humanizer):
        raw = (
            "AKTUELL: 15°C, bewoelkt, Wind aus Süd mit 5 km/h\n"
            "VORHERSAGE 2026-03-12: sonnig, Hoch 20, Tief 10, Niederschlag 0 mm"
        )
        result = humanizer._humanize_weather(raw)
        # Zero precipitation should NOT be mentioned
        assert "mm Regen" not in result

    def test_forecast_with_condition_mapping(self, humanizer):
        raw = (
            "AKTUELL: 15°C, sonnig, Wind aus Ost mit 3 km/h\n"
            "VORHERSAGE 2026-03-12: nebel, Hoch 10, Tief 2"
        )
        result = humanizer._humanize_weather(raw)
        assert "neblig" in result

    def test_moderate_temp_no_comment(self, humanizer):
        raw = "AKTUELL: 18°C, sonnig, Wind aus West mit 5 km/h"
        result = humanizer._humanize_weather(raw)
        # 18 degrees: not cold, not hot - no comment
        assert "Handschuhe" not in result
        assert "Jacke" not in result
        assert "trinken" not in result
