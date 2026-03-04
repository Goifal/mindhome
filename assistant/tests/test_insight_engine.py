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
            "climate": [{"name": "WZ", "current_temp": 21}],
            "open_doors": [],
            "states": [
                {"entity_id": "alarm_control_panel.home", "state": "disarmed", "attributes": {}},
                {"entity_id": "light.wohnzimmer", "state": "on", "attributes": {"friendly_name": "WZ"}},
            ],
        }
        result = await insight_engine._check_guest_preparation(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_guest_event_too_cold(self, insight_engine):
        """Gaeste kommen, aber Raum ist zu kalt."""
        now = datetime.now()
        event_time = now + timedelta(hours=2)
        data = {
            "calendar_events": [{"summary": "Besuch kommt", "start": event_time.isoformat()}],
            "climate": [{"name": "Wohnzimmer", "current_temp": 16}],
            "open_doors": [],
            "states": [
                {"entity_id": "alarm_control_panel.home", "state": "disarmed", "attributes": {}},
                {"entity_id": "light.wz", "state": "on", "attributes": {"friendly_name": "WZ"}},
            ],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_guest_preparation(data)
        assert result is not None
        assert "Temperatur" in result["message"]

    @pytest.mark.asyncio
    async def test_guest_event_open_doors(self, insight_engine):
        """Gaeste kommen, aber Tueren stehen offen."""
        now = datetime.now()
        event_time = now + timedelta(hours=1)
        data = {
            "calendar_events": [{"summary": "Einladung Abendessen", "start": event_time.isoformat()}],
            "climate": [],
            "open_doors": ["Haustuer"],
            "states": [
                {"entity_id": "alarm_control_panel.home", "state": "disarmed", "attributes": {}},
                {"entity_id": "light.wz", "state": "on", "attributes": {"friendly_name": "WZ"}},
            ],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_guest_preparation(data)
        assert result is not None
        assert "Tueren" in result["message"]


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
        """Braucht mindestens 2 Probleme (ohne offene Tueren)."""
        data = {
            "open_windows": [],
            "open_doors": [],
            "states": [
                {"entity_id": "person.max", "state": "not_home", "attributes": {"friendly_name": "Max"}},
                {"entity_id": "alarm_control_panel.home", "state": "disarmed", "attributes": {}},
            ],
        }
        result = await insight_engine._check_away_security_full(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_open_door_alone_triggers(self, insight_engine):
        """Offene Tuer allein reicht fuer einen Hinweis (kritischer als Fenster)."""
        data = {
            "open_windows": [],
            "open_doors": ["Haustuer"],
            "states": [
                {"entity_id": "person.max", "state": "not_home", "attributes": {"friendly_name": "Max"}},
                {"entity_id": "alarm_control_panel.home", "state": "armed_away", "attributes": {}},
            ],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_away_security_full(data)
        assert result is not None
        assert "Tueren" in result["message"]

    @pytest.mark.asyncio
    async def test_open_door_plus_alarm_off(self, insight_engine):
        data = {
            "open_windows": [],
            "open_doors": ["Haustuer"],
            "states": [
                {"entity_id": "person.max", "state": "not_home", "attributes": {"friendly_name": "Max"}},
                {"entity_id": "alarm_control_panel.home", "state": "disarmed", "attributes": {}},
            ],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_away_security_full(data)
        assert result is not None
        assert "Tueren" in result["message"]
        assert "Alarm" in result["message"]

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
        assert result["urgency"] == "low"

    @pytest.mark.asyncio
    async def test_working_with_bad_climate_medium_urgency(self, insight_engine):
        """Arbeitszeit + warmer Raum → urgency steigt auf medium."""
        activity_mock = MagicMock()
        activity_mock.current_activity = "working"
        activity_mock.current_duration_hours = 9
        insight_engine.activity = activity_mock

        data = {
            "climate": [{"name": "Buero", "current_temp": 27}],
            "weather": {"humidity": 70},
        }

        with patch("assistant.insight_engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 21, 0)
            with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
                result = await insight_engine._check_health_work_pattern(data)

        assert result is not None
        assert result["urgency"] == "medium"
        assert "27" in result["message"]
        assert "70%" in result["message"]

    @pytest.mark.asyncio
    async def test_working_normal_climate_low_urgency(self, insight_engine):
        """Arbeitszeit + angenehmes Klima → bleibt low."""
        activity_mock = MagicMock()
        activity_mock.current_activity = "working"
        activity_mock.current_duration_hours = 9
        insight_engine.activity = activity_mock

        data = {
            "climate": [{"name": "Buero", "current_temp": 22}],
            "weather": {"humidity": 45},
        }

        with patch("assistant.insight_engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 21, 0)
            with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
                result = await insight_engine._check_health_work_pattern(data)

        assert result is not None
        assert result["urgency"] == "low"
        assert "Dazu" not in result["message"]

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
    async def test_high_outdoor_humidity_triggers(self, insight_engine):
        """Kein Regen, aber >80% Luftfeuchtigkeit draussen → trotzdem Widerspruch."""
        data = {
            "open_windows": ["Fenster"],
            "forecast": [{"condition": "cloudy"}],
            "weather": {"humidity": 85},
            "states": [
                {"entity_id": "switch.entfeuchter", "state": "on", "attributes": {}},
            ],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_humidity_contradiction(data)
        assert result is not None
        assert "85%" in result["message"]

    @pytest.mark.asyncio
    async def test_indoor_humidity_shown(self, insight_engine):
        """Indoor-Sensor >60% → wird in Meldung erwaehnt."""
        data = {
            "open_windows": ["Fenster"],
            "forecast": [{"condition": "rainy"}],
            "states": [
                {"entity_id": "switch.entfeuchter", "state": "on", "attributes": {}},
                {"entity_id": "sensor.bad_humidity", "state": "72", "attributes": {}},
            ],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_humidity_contradiction(data)
        assert result is not None
        assert "72%" in result["message"]
        assert result["data"]["indoor_humidity"] == 72.0

    @pytest.mark.asyncio
    async def test_no_rain_no_alert(self, insight_engine):
        data = {
            "open_windows": ["Fenster"],
            "forecast": [{"condition": "sunny"}],
            "weather": {"humidity": 50},
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


# ============================================================
# Night Security Check
# ============================================================

class TestNightSecurity:

    @pytest.mark.asyncio
    async def test_late_night_windows_open(self, insight_engine):
        """Nach 23 Uhr + Fenster offen + Person zuhause → Hinweis."""
        data = {
            "open_windows": ["Kueche Fenster"],
            "open_doors": [],
            "persons_home": ["Max"],
            "persons_away": [],
            "alarm_state": "disarmed",
            "weather": {"temperature": 5},
            "states": [],
        }
        with patch("assistant.insight_engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 23, 30)
            with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
                result = await insight_engine._check_night_security(data)
        assert result is not None
        assert result["check"] == "night_security"
        assert "Fenster" in result["message"]
        assert "23 Uhr" in result["message"]
        assert "5°C" in result["message"]

    @pytest.mark.asyncio
    async def test_late_night_doors_open_high_urgency(self, insight_engine):
        """Offene Tueren nachts → high urgency."""
        data = {
            "open_windows": [],
            "open_doors": ["Haustuer"],
            "persons_home": ["Max"],
            "persons_away": [],
            "alarm_state": "disarmed",
            "weather": {},
            "states": [],
        }
        with patch("assistant.insight_engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 0, 15)
            with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
                result = await insight_engine._check_night_security(data)
        assert result is not None
        assert result["urgency"] == "high"
        assert "Tueren" in result["message"]

    @pytest.mark.asyncio
    async def test_before_23_no_alert(self, insight_engine):
        """Vor 23 Uhr → kein Hinweis."""
        data = {
            "open_windows": ["Fenster"],
            "open_doors": [],
            "persons_home": ["Max"],
            "persons_away": [],
            "alarm_state": "disarmed",
            "states": [],
        }
        with patch("assistant.insight_engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 22, 0)
            result = await insight_engine._check_night_security(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_nobody_home_no_alert(self, insight_engine):
        """Niemand zuhause → kein Hinweis."""
        data = {
            "open_windows": ["Fenster"],
            "open_doors": [],
            "persons_home": [],
            "persons_away": ["Max"],
            "alarm_state": "disarmed",
            "states": [],
        }
        with patch("assistant.insight_engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 23, 30)
            result = await insight_engine._check_night_security(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_alarm_armed_no_alert(self, insight_engine):
        """Alarm scharf → alles ok, kein Hinweis."""
        data = {
            "open_windows": ["Fenster"],
            "open_doors": [],
            "persons_home": ["Max"],
            "persons_away": [],
            "alarm_state": "armed_home",
            "states": [],
        }
        with patch("assistant.insight_engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 23, 30)
            result = await insight_engine._check_night_security(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_nothing_open_no_alert(self, insight_engine):
        """Alles zu → kein Hinweis."""
        data = {
            "open_windows": [],
            "open_doors": [],
            "persons_home": ["Max"],
            "persons_away": [],
            "alarm_state": "disarmed",
            "states": [],
        }
        with patch("assistant.insight_engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 23, 30)
            result = await insight_engine._check_night_security(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_early_morning_triggers(self, insight_engine):
        """Frueh morgens (0-5 Uhr) zaehlt auch als Nacht."""
        data = {
            "open_windows": ["Fenster"],
            "open_doors": [],
            "persons_home": ["Max"],
            "persons_away": [],
            "alarm_state": "disarmed",
            "weather": {},
            "states": [],
        }
        with patch("assistant.insight_engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 3, 0)
            with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
                result = await insight_engine._check_night_security(data)
        assert result is not None

    @pytest.mark.asyncio
    async def test_windows_and_doors_combined(self, insight_engine):
        """Fenster + Tueren offen → beides in Meldung."""
        data = {
            "open_windows": ["Kueche"],
            "open_doors": ["Haustuer"],
            "persons_home": ["Max"],
            "persons_away": [],
            "alarm_state": "disarmed",
            "weather": {},
            "states": [],
        }
        with patch("assistant.insight_engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 23, 45)
            with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
                result = await insight_engine._check_night_security(data)
        assert result is not None
        assert "Fenster" in result["message"]
        assert "Tueren" in result["message"]
        assert result["urgency"] == "high"


# ============================================================
# Heating vs Sun Check
# ============================================================

class TestHeatingVsSun:

    @pytest.mark.asyncio
    async def test_heating_plus_sunny_warm(self, insight_engine):
        """Heizung laeuft + sonnig + warm → Hinweis."""
        data = {
            "weather": {"condition": "sunny", "temperature": 22},
            "climate": [{"name": "Wohnzimmer", "hvac_action": "heating", "state": "heat"}],
            "states": [],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_heating_vs_sun(data)
        assert result is not None
        assert result["check"] == "heating_vs_sun"
        assert "Wohnzimmer" in result["message"]
        assert "22°C" in result["message"]
        assert "Sonnenschein" in result["message"]

    @pytest.mark.asyncio
    async def test_heating_with_covers_closed(self, insight_engine):
        """Heizung + Sonne + Rollladen zu → erwaehnt Rollladen."""
        data = {
            "weather": {"condition": "sunny", "temperature": 20},
            "climate": [{"name": "WZ", "hvac_action": "heating", "state": "heat"}],
            "states": [
                {"entity_id": "cover.wohnzimmer", "state": "closed",
                 "attributes": {"friendly_name": "WZ Rollladen", "current_position": 0}},
            ],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_heating_vs_sun(data)
        assert result is not None
        assert "Rollladen" in result["message"]

    @pytest.mark.asyncio
    async def test_no_heating_no_alert(self, insight_engine):
        """Keine Heizung aktiv → kein Hinweis."""
        data = {
            "weather": {"condition": "sunny", "temperature": 22},
            "climate": [{"name": "WZ", "hvac_action": "idle", "state": "heat"}],
            "states": [],
        }
        result = await insight_engine._check_heating_vs_sun(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_rainy_no_alert(self, insight_engine):
        """Regen → kein Hinweis."""
        data = {
            "weather": {"condition": "rainy", "temperature": 22},
            "climate": [{"name": "WZ", "hvac_action": "heating", "state": "heat"}],
            "states": [],
        }
        result = await insight_engine._check_heating_vs_sun(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_too_cold_outside_no_alert(self, insight_engine):
        """Sonnig aber zu kalt (<18°C) → kein Hinweis."""
        data = {
            "weather": {"condition": "sunny", "temperature": 12},
            "climate": [{"name": "WZ", "hvac_action": "heating", "state": "heat"}],
            "states": [],
        }
        result = await insight_engine._check_heating_vs_sun(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_partlycloudy_triggers(self, insight_engine):
        """Teilweise bewoelkt + warm → zaehlt auch."""
        data = {
            "weather": {"condition": "partlycloudy", "temperature": 20},
            "climate": [{"name": "Buero", "hvac_action": "heating", "state": "heat"}],
            "states": [],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_heating_vs_sun(data)
        assert result is not None
        assert "Buero" in result["message"]

    @pytest.mark.asyncio
    async def test_multiple_heating_rooms(self, insight_engine):
        """Mehrere Raeume heizen → alle erwaehnt."""
        data = {
            "weather": {"condition": "sunny", "temperature": 21},
            "climate": [
                {"name": "WZ", "hvac_action": "heating", "state": "heat"},
                {"name": "Schlafzimmer", "hvac_action": "heating", "state": "heat"},
            ],
            "states": [],
        }
        with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
            result = await insight_engine._check_heating_vs_sun(data)
        assert result is not None
        assert "WZ" in result["message"]
        assert "Schlafzimmer" in result["message"]

    @pytest.mark.asyncio
    async def test_no_weather_data(self, insight_engine):
        """Keine Wetterdaten → kein Hinweis."""
        data = {
            "weather": None,
            "climate": [{"name": "WZ", "hvac_action": "heating", "state": "heat"}],
            "states": [],
        }
        result = await insight_engine._check_heating_vs_sun(data)
        assert result is None


# ============================================================
# Forgotten Devices Check
# ============================================================

class TestForgottenDevices:

    @pytest.mark.asyncio
    async def test_media_playing_all_away(self, insight_engine):
        """Media Player laeuft + alle weg → Hinweis."""
        data = {
            "persons_home": [],
            "persons_away": ["Max"],
            "states": [
                {"entity_id": "media_player.tv_wz", "state": "playing",
                 "attributes": {"friendly_name": "Fernseher WZ", "media_title": "Netflix"}},
            ],
        }
        with patch("assistant.insight_engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 14, 0)
            with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
                result = await insight_engine._check_forgotten_devices(data)
        assert result is not None
        assert result["check"] == "forgotten_devices"
        assert "Fernseher WZ" in result["message"]
        assert "Netflix" in result["message"]
        assert "niemand zuhause" in result["message"]
        assert result["urgency"] == "medium"

    @pytest.mark.asyncio
    async def test_media_paused_all_away(self, insight_engine):
        """Paused zaehlt auch als aktiv."""
        data = {
            "persons_home": [],
            "persons_away": ["Max"],
            "states": [
                {"entity_id": "media_player.tv", "state": "paused",
                 "attributes": {"friendly_name": "TV"}},
            ],
        }
        with patch("assistant.insight_engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 14, 0)
            with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
                result = await insight_engine._check_forgotten_devices(data)
        assert result is not None

    @pytest.mark.asyncio
    async def test_late_night_media_on(self, insight_engine):
        """Nach Mitternacht + Media Player an → Hinweis (auch wenn jemand da)."""
        data = {
            "persons_home": ["Max"],
            "persons_away": [],
            "states": [
                {"entity_id": "media_player.tv", "state": "playing",
                 "attributes": {"friendly_name": "Fernseher"}},
            ],
        }
        with patch("assistant.insight_engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 2, 30)
            with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
                result = await insight_engine._check_forgotten_devices(data)
        assert result is not None
        assert result["urgency"] == "low"
        assert "2 Uhr" in result["message"]

    @pytest.mark.asyncio
    async def test_someone_home_daytime_no_alert(self, insight_engine):
        """Jemand zuhause + Tageszeit → kein Hinweis."""
        data = {
            "persons_home": ["Max"],
            "persons_away": [],
            "states": [
                {"entity_id": "media_player.tv", "state": "playing",
                 "attributes": {"friendly_name": "TV"}},
            ],
        }
        with patch("assistant.insight_engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 20, 0)
            result = await insight_engine._check_forgotten_devices(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_media_playing(self, insight_engine):
        """Kein Media Player aktiv → kein Hinweis."""
        data = {
            "persons_home": [],
            "persons_away": ["Max"],
            "states": [
                {"entity_id": "media_player.tv", "state": "off", "attributes": {}},
            ],
        }
        with patch("assistant.insight_engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 14, 0)
            result = await insight_engine._check_forgotten_devices(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_nobody_away_nobody_home(self, insight_engine):
        """Keine Personen-Daten → kein Hinweis."""
        data = {
            "persons_home": [],
            "persons_away": [],
            "states": [
                {"entity_id": "media_player.tv", "state": "playing",
                 "attributes": {"friendly_name": "TV"}},
            ],
        }
        with patch("assistant.insight_engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 14, 0)
            result = await insight_engine._check_forgotten_devices(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_multiple_media_players(self, insight_engine):
        """Mehrere aktive Media Player → alle erwaehnt."""
        data = {
            "persons_home": [],
            "persons_away": ["Max"],
            "states": [
                {"entity_id": "media_player.tv_wz", "state": "playing",
                 "attributes": {"friendly_name": "Fernseher WZ"}},
                {"entity_id": "media_player.sonos", "state": "playing",
                 "attributes": {"friendly_name": "Sonos", "media_title": "Spotify"}},
            ],
        }
        with patch("assistant.insight_engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 14, 0)
            with patch.object(insight_engine, "_get_title_for_home", return_value="Sir"):
                result = await insight_engine._check_forgotten_devices(data)
        assert result is not None
        assert "Fernseher WZ" in result["message"]
        assert "Sonos" in result["message"]
