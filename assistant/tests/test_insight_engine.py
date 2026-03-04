"""
Tests fuer InsightEngine — Proaktive Hinweis-Generierung.

Testet die regel-basierten Checks:
- Wetter + offene Fenster
- Frost + Heizung aus/away
- Kalender-Reise + Alarm deaktiviert
- Energie-Anomalie
- Abwesenheit + Geraete an
- Temperatur-Drop
- Fenster offen + Temperatur faellt
- Kalender x Wetter Cross-Reference
- Komfort-Widersprueche
- Phase 18 3D+: Gaeste-Vorbereitung, Away-Security, Health-Work, Humidity
"""

import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from assistant.insight_engine import InsightEngine, _RAIN_CONDITIONS, _STORM_CONDITIONS


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def ha_mock():
    mock = AsyncMock()
    mock.get_states = AsyncMock(return_value=[])
    mock.call_service_with_response = AsyncMock(return_value={})
    return mock


@pytest.fixture
def insight_engine(ha_mock):
    with patch("assistant.insight_engine.yaml_config", {"insights": {"enabled": True}, "insight_checks": {}}):
        engine = InsightEngine(ha=ha_mock)
    engine.redis = None
    return engine


@pytest.fixture
def insight_with_redis(insight_engine, redis_mock):
    insight_engine.redis = redis_mock
    return insight_engine


# ============================================================
# Initialisierung
# ============================================================

class TestInsightEngineInit:

    def test_default_config(self, insight_engine):
        assert insight_engine.enabled is True
        assert insight_engine.check_weather_windows is True
        assert insight_engine.check_frost_heating is True

    def test_disabled_config(self, ha_mock):
        with patch("assistant.insight_engine.yaml_config", {"insights": {"enabled": False}, "insight_checks": {}}):
            engine = InsightEngine(ha=ha_mock)
        assert engine.enabled is False

    @pytest.mark.asyncio
    async def test_set_notify_callback(self, insight_engine):
        cb = AsyncMock()
        insight_engine.set_notify_callback(cb)
        assert insight_engine._notify_callback is cb

    @pytest.mark.asyncio
    async def test_stop(self, insight_engine):
        import asyncio
        insight_engine._running = True
        # Erstelle einen echten abgeschlossenen Task
        async def noop(): pass
        task = asyncio.ensure_future(noop())
        await task
        insight_engine._task = task
        await insight_engine.stop()
        assert insight_engine._running is False


# ============================================================
# Weather + Windows Check
# ============================================================

class TestWeatherWindowsCheck:

    @pytest.mark.asyncio
    async def test_rain_forecast_with_open_windows(self, insight_engine):
        data = {
            "open_windows": ["Kueche Fenster"],
            "forecast": [{"condition": "rainy", "datetime": (datetime.now() + timedelta(hours=1)).isoformat()}],
            "states": [{"entity_id": "person.test", "state": "home", "attributes": {"friendly_name": "Test"}}],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_weather_windows(data)
        assert result is not None
        assert result["check"] == "weather_windows"
        assert "Kueche Fenster" in result["message"]
        assert result["urgency"] == "medium"

    @pytest.mark.asyncio
    async def test_storm_is_high_urgency(self, insight_engine):
        data = {
            "open_windows": ["Fenster 1"],
            "forecast": [{"condition": "lightning-rainy", "datetime": datetime.now().isoformat()}],
            "states": [],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_weather_windows(data)
        assert result is not None
        assert result["urgency"] == "high"

    @pytest.mark.asyncio
    async def test_no_windows_open(self, insight_engine):
        data = {"open_windows": [], "forecast": [{"condition": "rainy"}], "states": []}
        result = await insight_engine._check_weather_windows(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_rain_forecast(self, insight_engine):
        data = {"open_windows": ["Fenster"], "forecast": [{"condition": "sunny"}], "states": []}
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_weather_windows(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_high_precipitation_triggers(self, insight_engine):
        data = {
            "open_windows": ["Fenster"],
            "forecast": [{"condition": "cloudy", "precipitation": 5, "datetime": ""}],
            "states": [],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_weather_windows(data)
        assert result is not None

    @pytest.mark.asyncio
    async def test_multiple_windows_truncated(self, insight_engine):
        data = {
            "open_windows": ["F1", "F2", "F3", "F4", "F5"],
            "forecast": [{"condition": "rainy", "datetime": ""}],
            "states": [],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_weather_windows(data)
        assert result is not None
        assert "weitere" in result["message"]


# ============================================================
# Frost + Heating Check
# ============================================================

class TestFrostHeatingCheck:

    @pytest.mark.asyncio
    async def test_frost_with_heating_off(self, insight_engine):
        data = {
            "forecast": [{"temperature": 0, "templow": -2}],
            "climate": [{"name": "Wohnzimmer", "state": "off", "preset_mode": ""}],
            "states": [],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_frost_heating(data)
        assert result is not None
        assert result["check"] == "frost_heating"
        assert "Wohnzimmer ist aus" in result["message"]

    @pytest.mark.asyncio
    async def test_frost_with_heating_eco(self, insight_engine):
        data = {
            "forecast": [{"temperature": 1, "templow": -1}],
            "climate": [{"name": "Flur", "state": "heat", "preset_mode": "eco"}],
            "states": [],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_frost_heating(data)
        assert result is not None
        assert "Flur ist auf eco" in result["message"]

    @pytest.mark.asyncio
    async def test_no_frost_no_alert(self, insight_engine):
        data = {
            "forecast": [{"temperature": 10, "templow": 5}],
            "climate": [{"name": "Wohnzimmer", "state": "heat", "preset_mode": "home"}],
            "states": [],
        }
        result = await insight_engine._check_frost_heating(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_frost_but_heating_on(self, insight_engine):
        data = {
            "forecast": [{"temperature": -3}],
            "climate": [{"name": "Wohnzimmer", "state": "heat", "preset_mode": "home"}],
            "states": [],
        }
        result = await insight_engine._check_frost_heating(data)
        assert result is None


# ============================================================
# Calendar Travel Check
# ============================================================

class TestCalendarTravelCheck:

    @pytest.mark.asyncio
    async def test_travel_event_alarm_off(self, insight_engine):
        data = {
            "calendar_events": [{"summary": "Flug nach Berlin", "start": "2025-06-01T08:00:00"}],
            "alarm_state": "disarmed",
            "open_windows": [],
            "climate": [],
            "states": [],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_calendar_travel(data)
        assert result is not None
        assert result["check"] == "calendar_travel"
        assert "Alarmanlage" in result["message"]

    @pytest.mark.asyncio
    async def test_no_travel_keywords(self, insight_engine):
        data = {
            "calendar_events": [{"summary": "Meeting mit Team"}],
            "alarm_state": "disarmed",
            "open_windows": [],
            "climate": [],
            "states": [],
        }
        result = await insight_engine._check_calendar_travel(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_travel_with_open_windows(self, insight_engine):
        data = {
            "calendar_events": [{"summary": "Urlaub Mallorca", "start": "2025-07-01"}],
            "alarm_state": "armed_away",
            "open_windows": ["Kueche", "Bad"],
            "climate": [],
            "states": [],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_calendar_travel(data)
        assert result is not None
        assert "Fenster" in result["message"]

    @pytest.mark.asyncio
    async def test_travel_all_ok(self, insight_engine):
        """Reise-Event aber alles in Ordnung → kein Hinweis."""
        data = {
            "calendar_events": [{"summary": "Flug London", "start": "2025-06-01"}],
            "alarm_state": "armed_away",
            "open_windows": [],
            "climate": [{"name": "WZ", "state": "heat", "preset_mode": "away"}],
            "states": [],
        }
        result = await insight_engine._check_calendar_travel(data)
        assert result is None


# ============================================================
# Energy Anomaly Check
# ============================================================

class TestEnergyAnomalyCheck:

    @pytest.mark.asyncio
    async def test_high_consumption(self, insight_with_redis):
        engine = insight_with_redis

        # 7-Tage-Durchschnitt: 5000 Wh
        async def fake_get(key):
            if "daily:" in key and datetime.now().strftime("%Y-%m-%d") in key:
                return json.dumps({"consumption_wh": 8000})
            if "daily:" in key:
                return json.dumps({"consumption_wh": 5000})
            return None

        engine.redis.get = AsyncMock(side_effect=fake_get)

        with patch.object(engine, "_get_title_for_home", return_value="Sir"):
            with patch("assistant.insight_engine.datetime") as mock_dt:
                mock_dt.now.return_value = datetime(2025, 6, 15, 12, 0)
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                result = await engine._check_energy_anomaly({})
        # Result depends on the projected vs avg calculation
        # At noon, projected = 8000/12*24 = 16000, avg = 5000, increase = 220%
        assert result is not None
        assert result["check"] == "energy_anomaly"

    @pytest.mark.asyncio
    async def test_normal_consumption(self, insight_with_redis):
        engine = insight_with_redis

        async def fake_get(key):
            if "2025-06-15" in key:
                return json.dumps({"consumption_wh": 2000})
            if "daily:" in key:
                return json.dumps({"consumption_wh": 5000})
            return None

        engine.redis.get = AsyncMock(side_effect=fake_get)

        with patch("assistant.insight_engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 12, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = await engine._check_energy_anomaly({})
        # Projected: 2000/12*24 = 4000, avg: 5000 → -20% → no anomaly
        assert result is None

    @pytest.mark.asyncio
    async def test_no_redis(self, insight_engine):
        result = await insight_engine._check_energy_anomaly({})
        assert result is None


# ============================================================
# Away Devices Check
# ============================================================

class TestAwayDevicesCheck:

    @pytest.mark.asyncio
    async def test_away_with_lights_on(self, insight_with_redis):
        engine = insight_with_redis
        engine.redis.get = AsyncMock(return_value=(datetime.now() - timedelta(hours=3)).isoformat())
        engine.redis.exists = AsyncMock(return_value=0)

        data = {
            "persons_home": [],
            "persons_away": ["Max"],
            "lights_on": ["Wohnzimmer Licht", "Flur Licht"],
            "open_windows": [],
            "states": [],
        }
        with patch.object(engine, "_get_title_for_home", return_value="Sir"):
            result = await engine._check_away_devices(data)
        assert result is not None
        assert result["check"] == "away_devices"

    @pytest.mark.asyncio
    async def test_persons_home_no_alert(self, insight_with_redis):
        data = {
            "persons_home": ["Max"],
            "persons_away": [],
            "lights_on": ["Licht"],
            "open_windows": [],
            "states": [],
        }
        result = await insight_with_redis._check_away_devices(data)
        assert result is None


# ============================================================
# Run All Checks Integration
# ============================================================

class TestRunAllChecks:

    @pytest.mark.asyncio
    async def test_no_states_returns_empty(self, insight_engine):
        insight_engine.ha.get_states = AsyncMock(return_value=[])
        result = await insight_engine._run_all_checks()
        assert result == []

    @pytest.mark.asyncio
    async def test_cooldown_prevents_duplicate(self, insight_with_redis):
        engine = insight_with_redis
        # Simuliere dass ein Check auf Cooldown ist
        engine.redis.exists = AsyncMock(return_value=1)

        engine.ha.get_states = AsyncMock(return_value=[
            {"entity_id": "weather.home", "state": "rainy", "attributes": {"forecast": [{"condition": "rainy"}]}},
        ])

        result = await engine._run_all_checks()
        # Alle auf Cooldown → leer
        assert result == []


# ============================================================
# Reload Config
# ============================================================

class TestReloadConfig:

    def test_reload_updates_values(self, insight_engine):
        with patch("assistant.insight_engine.yaml_config", {
            "insights": {
                "enabled": False,
                "check_interval_minutes": 60,
                "cooldown_hours": 8,
                "checks": {"weather_windows": False},
                "thresholds": {"frost_temp_c": -5},
            },
            "insight_checks": {},
        }):
            insight_engine.reload_config()
        assert insight_engine.enabled is False
        assert insight_engine.check_interval == 3600
        assert insight_engine.cooldown_hours == 8
        assert insight_engine.check_weather_windows is False
        assert insight_engine.frost_temp == -5


# ============================================================
# Calendar x Weather Cross-Reference
# ============================================================

class TestCalendarWeatherCross:

    @pytest.mark.asyncio
    async def test_event_plus_rain(self, insight_engine):
        now = datetime.now()
        event_time = now + timedelta(hours=3)
        data = {
            "calendar_events": [{"summary": "Meeting", "start": event_time.isoformat()}],
            "forecast": [{"condition": "rainy"}],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_calendar_weather_cross(data)
        assert result is not None
        assert result["check"] == "calendar_weather_cross"
        assert "Regen" in result["message"]
        assert "Schirm" in result["message"]

    @pytest.mark.asyncio
    async def test_event_plus_storm(self, insight_engine):
        now = datetime.now()
        event_time = now + timedelta(hours=2)
        data = {
            "calendar_events": [{"summary": "Termin", "start": event_time.isoformat()}],
            "forecast": [{"condition": "lightning-rainy"}],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_calendar_weather_cross(data)
        assert result is not None
        assert "Regenkleidung" in result["message"]

    @pytest.mark.asyncio
    async def test_event_sunny_no_alert(self, insight_engine):
        now = datetime.now()
        event_time = now + timedelta(hours=3)
        data = {
            "calendar_events": [{"summary": "Termin", "start": event_time.isoformat()}],
            "forecast": [{"condition": "sunny"}],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_calendar_weather_cross(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_event_too_far_away(self, insight_engine):
        now = datetime.now()
        event_time = now + timedelta(hours=20)
        data = {
            "calendar_events": [{"summary": "Termin", "start": event_time.isoformat()}],
            "forecast": [{"condition": "rainy"}],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_calendar_weather_cross(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_events(self, insight_engine):
        data = {"calendar_events": [], "forecast": [{"condition": "rainy"}]}
        result = await insight_engine._check_calendar_weather_cross(data)
        assert result is None


# ============================================================
# Comfort Contradiction
# ============================================================

class TestComfortContradiction:

    @pytest.mark.asyncio
    async def test_heating_plus_open_window(self, insight_engine):
        data = {
            "open_windows": ["Wohnzimmer Fenster"],
            "climate": [{"name": "Wohnzimmer", "hvac_action": "heating"}],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_comfort_contradiction(data)
        assert result is not None
        assert result["check"] == "comfort_contradiction"
        assert "Heizung" in result["message"]
        assert "offen" in result["message"]

    @pytest.mark.asyncio
    async def test_no_windows_open(self, insight_engine):
        data = {
            "open_windows": [],
            "climate": [{"name": "Wohnzimmer", "hvac_action": "heating"}],
        }
        result = await insight_engine._check_comfort_contradiction(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_heating_idle_ok(self, insight_engine):
        data = {
            "open_windows": ["Fenster"],
            "climate": [{"name": "WZ", "hvac_action": "idle"}],
        }
        result = await insight_engine._check_comfort_contradiction(data)
        assert result is None


# ============================================================
# Phase 18: Guest Preparation (3D+)
# ============================================================

class TestGuestPreparation:

    @pytest.mark.asyncio
    async def test_guest_event_alarm_armed(self, insight_engine):
        now = datetime.now()
        event_time = now + timedelta(hours=2)
        data = {
            "calendar_events": [{"summary": "Dinner Party", "start": event_time.isoformat()}],
            "states": [
                {"entity_id": "alarm_control_panel.home", "state": "armed_away", "attributes": {}},
            ],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_guest_preparation(data)
        assert result is not None
        assert result["check"] == "guest_preparation"
        assert "Alarm" in result["message"]
        assert result["urgency"] == "medium"

    @pytest.mark.asyncio
    async def test_guest_event_lights_off(self, insight_engine):
        now = datetime.now()
        event_time = now + timedelta(hours=1)
        data = {
            "calendar_events": [{"summary": "Gaeste zum Brunch", "start": event_time.isoformat()}],
            "states": [
                {"entity_id": "alarm_control_panel.home", "state": "disarmed", "attributes": {}},
                # Keine Lichter an
            ],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_guest_preparation(data)
        assert result is not None
        assert "Lichter" in result["message"]

    @pytest.mark.asyncio
    async def test_no_guest_keywords(self, insight_engine):
        now = datetime.now()
        event_time = now + timedelta(hours=2)
        data = {
            "calendar_events": [{"summary": "Arzttermin", "start": event_time.isoformat()}],
            "states": [],
        }
        result = await insight_engine._check_guest_preparation(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_guest_event_too_far(self, insight_engine):
        now = datetime.now()
        event_time = now + timedelta(hours=6)
        data = {
            "calendar_events": [{"summary": "Dinner", "start": event_time.isoformat()}],
            "states": [{"entity_id": "alarm_control_panel.home", "state": "armed_away", "attributes": {}}],
        }
        result = await insight_engine._check_guest_preparation(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_guest_event_all_ok(self, insight_engine):
        now = datetime.now()
        event_time = now + timedelta(hours=2)
        data = {
            "calendar_events": [{"summary": "Party", "start": event_time.isoformat()}],
            "states": [
                {"entity_id": "alarm_control_panel.home", "state": "disarmed", "attributes": {}},
                {"entity_id": "light.wohnzimmer", "state": "on", "attributes": {"friendly_name": "WZ"}},
            ],
        }
        result = await insight_engine._check_guest_preparation(data)
        assert result is None


# ============================================================
# Phase 18: Away Security Full (3D+)
# ============================================================

class TestAwaySecurityFull:

    @pytest.mark.asyncio
    async def test_away_alarm_off_windows_open(self, insight_engine):
        data = {
            "open_windows": ["Kueche Fenster"],
            "states": [
                {"entity_id": "person.max", "state": "not_home", "attributes": {"friendly_name": "Max"}},
                {"entity_id": "alarm_control_panel.home", "state": "disarmed", "attributes": {}},
                {"entity_id": "binary_sensor.fenster", "state": "on", "attributes": {}},
            ],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_away_security_full(data)
        assert result is not None
        assert result["check"] == "away_security_full"
        assert result["urgency"] == "high"
        assert "Fenster" in result["message"]
        assert "Alarm" in result["message"]

    @pytest.mark.asyncio
    async def test_away_alarm_off_lights_on(self, insight_engine):
        data = {
            "open_windows": [],
            "states": [
                {"entity_id": "person.max", "state": "not_home", "attributes": {"friendly_name": "Max"}},
                {"entity_id": "alarm_control_panel.home", "state": "disarmed", "attributes": {}},
                {"entity_id": "light.wz", "state": "on", "attributes": {"friendly_name": "Wohnzimmer"}},
            ],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_away_security_full(data)
        assert result is not None
        assert "Lichter" in result["message"]

    @pytest.mark.asyncio
    async def test_someone_home(self, insight_engine):
        data = {
            "open_windows": ["Fenster"],
            "states": [
                {"entity_id": "person.max", "state": "home", "attributes": {"friendly_name": "Max"}},
                {"entity_id": "alarm_control_panel.home", "state": "disarmed", "attributes": {}},
            ],
        }
        result = await insight_engine._check_away_security_full(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_only_one_issue_not_enough(self, insight_engine):
        """Braucht mindestens 2 Probleme."""
        data = {
            "open_windows": [],
            "states": [
                {"entity_id": "person.max", "state": "not_home", "attributes": {"friendly_name": "Max"}},
                {"entity_id": "alarm_control_panel.home", "state": "disarmed", "attributes": {}},
            ],
        }
        result = await insight_engine._check_away_security_full(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_person_entities(self, insight_engine):
        data = {"open_windows": [], "states": []}
        result = await insight_engine._check_away_security_full(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_away_all_secure(self, insight_engine):
        """Alle weg, aber Alarm scharf + keine Fenster + keine Lichter."""
        data = {
            "open_windows": [],
            "states": [
                {"entity_id": "person.max", "state": "not_home", "attributes": {"friendly_name": "Max"}},
                {"entity_id": "alarm_control_panel.home", "state": "armed_away", "attributes": {}},
            ],
        }
        result = await insight_engine._check_away_security_full(data)
        assert result is None


# ============================================================
# Phase 18: Health Work Pattern (3D+)
# ============================================================

class TestHealthWorkPattern:

    @pytest.mark.asyncio
    async def test_working_too_long(self, insight_engine):
        activity_mock = MagicMock()
        activity_mock.current_activity = "working"
        activity_mock.current_duration_hours = 10
        insight_engine.activity = activity_mock

        with patch("assistant.insight_engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 20, 0)  # 20 Uhr
            with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
                result = await insight_engine._check_health_work_pattern({})

        assert result is not None
        assert result["check"] == "health_work_pattern"
        assert "Pause" in result["message"]
        assert "10" in result["message"]

    @pytest.mark.asyncio
    async def test_working_but_before_18(self, insight_engine):
        activity_mock = MagicMock()
        activity_mock.current_activity = "working"
        activity_mock.current_duration_hours = 10
        insight_engine.activity = activity_mock

        with patch("assistant.insight_engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 14, 0)  # 14 Uhr
            result = await insight_engine._check_health_work_pattern({})

        assert result is None

    @pytest.mark.asyncio
    async def test_not_working(self, insight_engine):
        activity_mock = MagicMock()
        activity_mock.current_activity = "idle"
        activity_mock.current_duration_hours = 10
        insight_engine.activity = activity_mock

        with patch("assistant.insight_engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 20, 0)
            result = await insight_engine._check_health_work_pattern({})

        assert result is None

    @pytest.mark.asyncio
    async def test_short_work_ok(self, insight_engine):
        activity_mock = MagicMock()
        activity_mock.current_activity = "working"
        activity_mock.current_duration_hours = 4
        insight_engine.activity = activity_mock

        with patch("assistant.insight_engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 20, 0)
            result = await insight_engine._check_health_work_pattern({})

        assert result is None

    @pytest.mark.asyncio
    async def test_no_activity_engine(self, insight_engine):
        insight_engine.activity = None
        result = await insight_engine._check_health_work_pattern({})
        assert result is None


# ============================================================
# Phase 18: Humidity Contradiction (3D+)
# ============================================================

class TestHumidityContradiction:

    @pytest.mark.asyncio
    async def test_dehumidifier_plus_rain_plus_windows(self, insight_engine):
        data = {
            "open_windows": ["Bad Fenster"],
            "forecast": [{"condition": "rainy"}],
            "states": [
                {"entity_id": "switch.entfeuchter", "state": "on", "attributes": {}},
            ],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_humidity_contradiction(data)
        assert result is not None
        assert result["check"] == "humidity_contradiction"
        assert "Entfeuchter" in result["message"]
        assert "Regen" in result["message"]

    @pytest.mark.asyncio
    async def test_climate_dry_mode_plus_rain(self, insight_engine):
        data = {
            "open_windows": ["Fenster"],
            "forecast": [{"condition": "pouring"}],
            "states": [
                {"entity_id": "climate.wz", "state": "dry", "attributes": {"hvac_mode": "dry"}},
            ],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_humidity_contradiction(data)
        assert result is not None

    @pytest.mark.asyncio
    async def test_no_rain_no_alert(self, insight_engine):
        data = {
            "open_windows": ["Fenster"],
            "forecast": [{"condition": "sunny"}],
            "states": [
                {"entity_id": "switch.entfeuchter", "state": "on", "attributes": {}},
            ],
        }
        result = await insight_engine._check_humidity_contradiction(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_windows_open(self, insight_engine):
        data = {
            "open_windows": [],
            "forecast": [{"condition": "rainy"}],
            "states": [{"entity_id": "switch.entfeuchter", "state": "on", "attributes": {}}],
        }
        result = await insight_engine._check_humidity_contradiction(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_dehumidifier(self, insight_engine):
        data = {
            "open_windows": ["Fenster"],
            "forecast": [{"condition": "rainy"}],
            "states": [],
        }
        result = await insight_engine._check_humidity_contradiction(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_high_precipitation_triggers(self, insight_engine):
        data = {
            "open_windows": ["Fenster"],
            "forecast": [{"condition": "cloudy", "precipitation": 5}],
            "states": [{"entity_id": "switch.dehumidifier", "state": "on", "attributes": {}}],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_humidity_contradiction(data)
        assert result is not None
