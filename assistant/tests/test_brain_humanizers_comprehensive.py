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
