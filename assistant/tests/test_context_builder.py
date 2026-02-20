"""
Tests fuer ContextBuilder — Haus-Status, Zeitkontext, Wetter-Warnungen.
"""

from unittest.mock import AsyncMock

import pytest

from assistant.context_builder import ContextBuilder


@pytest.fixture
def builder():
    ha = AsyncMock()
    return ContextBuilder(ha)


class TestTimeOfDay:
    """Tests fuer _get_time_of_day()."""

    def test_early_morning(self, builder):
        assert builder._get_time_of_day(6) == "early_morning"

    def test_morning(self, builder):
        assert builder._get_time_of_day(10) == "morning"

    def test_afternoon(self, builder):
        assert builder._get_time_of_day(15) == "afternoon"

    def test_evening(self, builder):
        assert builder._get_time_of_day(19) == "evening"

    def test_night(self, builder):
        assert builder._get_time_of_day(1) == "night"

    def test_boundary_morning(self, builder):
        assert builder._get_time_of_day(8) == "morning"

    def test_boundary_evening(self, builder):
        assert builder._get_time_of_day(18) == "evening"


class TestWeekdayGerman:
    """Tests fuer _weekday_german()."""

    def test_montag(self, builder):
        assert builder._weekday_german(0) == "Montag"

    def test_sonntag(self, builder):
        assert builder._weekday_german(6) == "Sonntag"

    def test_all_days(self, builder):
        days = [builder._weekday_german(i) for i in range(7)]
        assert len(days) == 7
        assert days[0] == "Montag"
        assert days[4] == "Freitag"


class TestExtractHouseStatus:
    """Tests fuer _extract_house_status()."""

    def test_temperatures(self, builder):
        states = [
            {"entity_id": "climate.wohnzimmer", "state": "heat",
             "attributes": {"friendly_name": "Wohnzimmer", "current_temperature": 21.5, "temperature": 22}},
        ]
        result = builder._extract_house_status(states)
        assert "Wohnzimmer" in result["temperatures"]
        assert result["temperatures"]["Wohnzimmer"]["current"] == 21.5
        assert result["temperatures"]["Wohnzimmer"]["target"] == 22

    def test_lights_on(self, builder):
        states = [
            {"entity_id": "light.flur", "state": "on",
             "attributes": {"friendly_name": "Flur", "brightness": 128}},
        ]
        result = builder._extract_house_status(states)
        assert len(result["lights"]) == 1
        assert "Flur" in result["lights"][0]
        assert "50%" in result["lights"][0]

    def test_lights_off_excluded(self, builder):
        states = [
            {"entity_id": "light.flur", "state": "off",
             "attributes": {"friendly_name": "Flur"}},
        ]
        result = builder._extract_house_status(states)
        assert len(result["lights"]) == 0

    def test_presence_home(self, builder):
        states = [
            {"entity_id": "person.max", "state": "home",
             "attributes": {"friendly_name": "Max"}},
            {"entity_id": "person.anna", "state": "not_home",
             "attributes": {"friendly_name": "Anna"}},
        ]
        result = builder._extract_house_status(states)
        assert "Max" in result["presence"]["home"]
        assert "Anna" in result["presence"]["away"]

    def test_weather(self, builder):
        states = [
            {"entity_id": "weather.home", "state": "sunny",
             "attributes": {"temperature": 25, "humidity": 45, "wind_speed": 15}},
        ]
        result = builder._extract_house_status(states)
        assert result["weather"]["temp"] == 25
        assert result["weather"]["condition"] == "sunny"

    def test_media_playing(self, builder):
        states = [
            {"entity_id": "media_player.wz", "state": "playing",
             "attributes": {"friendly_name": "Wohnzimmer", "media_title": "Jazz Mix"}},
        ]
        result = builder._extract_house_status(states)
        assert len(result["media"]) == 1
        assert "Jazz Mix" in result["media"][0]

    def test_media_paused_excluded(self, builder):
        states = [
            {"entity_id": "media_player.wz", "state": "paused",
             "attributes": {"friendly_name": "WZ"}},
        ]
        result = builder._extract_house_status(states)
        assert len(result["media"]) == 0

    def test_alarm_security(self, builder):
        states = [
            {"entity_id": "alarm_control_panel.home", "state": "armed_away",
             "attributes": {}},
        ]
        result = builder._extract_house_status(states)
        assert result["security"] == "armed_away"


class TestExtractPerson:
    """Tests fuer _extract_person()."""

    def test_person_home(self, builder):
        states = [
            {"entity_id": "person.max", "state": "home",
             "attributes": {"friendly_name": "Max"}},
        ]
        result = builder._extract_person(states)
        assert result["name"] == "Max"

    def test_nobody_home(self, builder):
        states = [
            {"entity_id": "person.max", "state": "not_home",
             "attributes": {"friendly_name": "Max"}},
        ]
        result = builder._extract_person(states)
        assert result["name"] == "User"

    def test_empty_states(self, builder):
        result = builder._extract_person([])
        assert result["name"] == "User"


class TestGuessRoom:
    """Tests fuer _guess_current_room()."""

    def test_motion_detected(self, builder):
        states = [
            {"entity_id": "binary_sensor.motion_kueche", "state": "on",
             "last_changed": "2026-02-20T10:00:00",
             "attributes": {"friendly_name": "Bewegung Kueche"}},
        ]
        result = builder._guess_current_room(states)
        assert "Kueche" in result

    def test_no_motion(self, builder):
        states = [
            {"entity_id": "binary_sensor.motion_flur", "state": "off",
             "last_changed": "2026-02-20T09:00:00",
             "attributes": {"friendly_name": "Bewegung Flur"}},
        ]
        result = builder._guess_current_room(states)
        assert result == "unbekannt"


class TestWeatherWarnings:
    """Tests fuer _check_weather_warnings()."""

    def test_no_warnings_normal(self, builder):
        states = [
            {"entity_id": "weather.home", "state": "sunny",
             "attributes": {"temperature": 22, "wind_speed": 10}},
        ]
        result = builder._check_weather_warnings(states)
        assert result == []

    def test_high_wind_warning(self, builder):
        states = [
            {"entity_id": "weather.home", "state": "windy",
             "attributes": {"temperature": 15, "wind_speed": 75}},
        ]
        result = builder._check_weather_warnings(states)
        assert len(result) >= 1
        assert any("Wind" in w or "wind" in w.lower() for w in result)

    def test_extreme_cold_warning(self, builder):
        states = [
            {"entity_id": "weather.home", "state": "clear-night",
             "attributes": {"temperature": -10, "wind_speed": 5}},
        ]
        result = builder._check_weather_warnings(states)
        assert len(result) >= 1


class TestBuild:
    """Tests fuer build() — Gesamter Kontextaufbau."""

    @pytest.mark.asyncio
    async def test_build_returns_time_context(self, builder):
        builder.ha.get_states.return_value = []
        result = await builder.build()
        assert "time" in result
        assert "weekday" in result["time"]
        assert "time_of_day" in result["time"]

    @pytest.mark.asyncio
    async def test_build_with_states(self, builder):
        builder.ha.get_states.return_value = [
            {"entity_id": "person.max", "state": "home",
             "attributes": {"friendly_name": "Max"}},
            {"entity_id": "weather.home", "state": "sunny",
             "attributes": {"temperature": 20}},
        ]
        result = await builder.build()
        assert "house" in result
        assert "person" in result

    @pytest.mark.asyncio
    async def test_build_without_states(self, builder):
        builder.ha.get_states.return_value = None
        result = await builder.build()
        assert "time" in result
        assert "house" not in result
