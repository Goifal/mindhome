"""Tests for assistant/light_engine.py — LightEngine unit tests."""

import asyncio
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from assistant.light_engine import LightEngine, _safe_redis, _R_OVERRIDE, _R_SLEEP, _R_DUSK, _R_AWAY_OFF, _R_NIGHT_DIM, _R_PATHLIGHT, _R_WEATHER_BOOST


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
def ha_client():
    ha = AsyncMock()
    ha.get_states = AsyncMock(return_value=[])
    ha.get_state = AsyncMock(return_value=None)
    ha.call_service = AsyncMock(return_value=True)
    return ha


@pytest.fixture
def redis_client():
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.set = AsyncMock(return_value=True)
    r.delete = AsyncMock(return_value=True)
    r.keys = AsyncMock(return_value=[])
    r.ttl = AsyncMock(return_value=-1)
    return r


@pytest.fixture
def engine(ha_client):
    with patch("assistant.light_engine.yaml_config", {
        "lighting": {"enabled": True, "presence_control": {"enabled": True, "auto_on_motion": True}},
    }):
        eng = LightEngine(ha_client)
    return eng


@pytest.fixture
async def engine_with_redis(engine, redis_client):
    await engine.initialize(redis_client)
    return engine


# ── _safe_redis ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_safe_redis_success(redis_client):
    redis_client.get = AsyncMock(return_value=b"1")
    result = await _safe_redis(redis_client, "get", "key")
    assert result == b"1"


@pytest.mark.asyncio
async def test_safe_redis_exception_returns_none(redis_client):
    redis_client.get = AsyncMock(side_effect=ConnectionError("fail"))
    result = await _safe_redis(redis_client, "get", "key")
    assert result is None


# ── initialize / start / stop ─────────────────────────────────

@pytest.mark.asyncio
async def test_initialize(engine, redis_client):
    await engine.initialize(redis_client)
    assert engine.redis is redis_client


@pytest.mark.asyncio
async def test_start_stop(engine):
    with patch.object(engine, '_check_loop', new_callable=AsyncMock):
        await engine.start()
        assert engine._running is True
        await engine.stop()
        assert engine._running is False


@pytest.mark.asyncio
async def test_start_idempotent(engine):
    with patch.object(engine, '_check_loop', new_callable=AsyncMock):
        await engine.start()
        task1 = engine._task
        await engine.start()  # should not create new task
        assert engine._task is task1
        await engine.stop()


# ── on_motion ─────────────────────────────────────────────────

@pytest.mark.asyncio
@patch("assistant.light_engine.get_room_profiles", return_value={"rooms": {"wohnzimmer": {"light_entities": ["light.wz"], "presence_auto_on": True}}})
@patch("assistant.light_engine.FunctionExecutor")
@patch("assistant.light_engine.yaml_config", {
    "lighting": {"enabled": True, "presence_control": {"enabled": True, "auto_on_motion": True}},
})
async def test_on_motion_turns_on_light(mock_fe, mock_profiles, engine):
    mock_fe._get_adaptive_brightness = MagicMock(return_value=70)
    engine.ha.get_state = AsyncMock(return_value={"state": "off"})
    engine.redis = None

    await engine.on_motion("binary_sensor.motion", "wohnzimmer")

    engine.ha.call_service.assert_called_once()
    call_args = engine.ha.call_service.call_args
    assert call_args[0][0] == "light"
    assert call_args[0][1] == "turn_on"
    assert call_args[0][2]["entity_id"] == "light.wz"


@pytest.mark.asyncio
@patch("assistant.light_engine.yaml_config", {"lighting": {"enabled": False}})
async def test_on_motion_disabled(engine):
    await engine.on_motion("binary_sensor.motion", "wohnzimmer")
    engine.ha.call_service.assert_not_called()


@pytest.mark.asyncio
@patch("assistant.light_engine.get_room_profiles", return_value={"rooms": {"wohnzimmer": {"light_entities": ["light.wz"], "presence_auto_on": True}}})
@patch("assistant.light_engine.FunctionExecutor")
@patch("assistant.light_engine.yaml_config", {
    "lighting": {"enabled": True, "presence_control": {"enabled": True, "auto_on_motion": True}},
})
async def test_on_motion_skips_already_on(mock_fe, mock_profiles, engine):
    mock_fe._get_adaptive_brightness = MagicMock(return_value=70)
    engine.ha.get_state = AsyncMock(return_value={"state": "on"})
    engine.redis = None

    await engine.on_motion("binary_sensor.motion", "wohnzimmer")
    engine.ha.call_service.assert_not_called()


@pytest.mark.asyncio
@patch("assistant.light_engine.get_room_profiles", return_value={"rooms": {"wohnzimmer": {"light_entities": ["light.wz"], "presence_auto_on": True, "night_path_light": True}}})
@patch("assistant.light_engine.yaml_config", {
    "lighting": {"enabled": True, "presence_control": {"enabled": True, "auto_on_motion": True, "night_path_light": True}},
})
async def test_on_motion_sleep_mode_uses_pathlight(mock_profiles, engine, redis_client):
    await engine.initialize(redis_client)
    redis_client.get = AsyncMock(return_value=b"1")  # sleep active

    await engine.on_motion("binary_sensor.motion", "wohnzimmer")
    # Should have called turn_on for pathlight
    engine.ha.call_service.assert_called()


@pytest.mark.asyncio
@patch("assistant.light_engine.get_room_profiles", return_value={"rooms": {"wohnzimmer": {"light_entities": ["light.wz"], "presence_auto_on": True}}})
@patch("assistant.light_engine.FunctionExecutor")
@patch("assistant.light_engine.yaml_config", {
    "lighting": {"enabled": True, "presence_control": {"enabled": True, "auto_on_motion": True}},
})
async def test_on_motion_with_mood_stressed(mock_fe, mock_profiles, engine):
    mock_fe._get_adaptive_brightness = MagicMock(return_value=70)
    engine.ha.get_state = AsyncMock(return_value={"state": "off"})
    engine.redis = None
    engine.mood = MagicMock()
    engine.mood.get_current_mood.return_value = {"mood": "stressed"}

    await engine.on_motion("binary_sensor.motion", "wohnzimmer")
    call_args = engine.ha.call_service.call_args[0][2]
    assert call_args["brightness_pct"] <= 50


# ── on_motion_clear ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_on_motion_clear_does_nothing(engine):
    await engine.on_motion_clear("binary_sensor.motion", "wohnzimmer")
    engine.ha.call_service.assert_not_called()


# ── on_bed_occupied ───────────────────────────────────────────

@pytest.mark.asyncio
@patch("assistant.light_engine.yaml_config", {
    "lighting": {"enabled": True, "bed_sensors": {"enabled": True, "sleep_start_hour": 21, "sleep_mode": True, "sleep_dim_transition": 300}},
})
async def test_on_bed_occupied_activates_sleep_mode(engine, redis_client):
    await engine.initialize(redis_client)
    engine.ha.get_states = AsyncMock(return_value=[
        {"entity_id": "light.bedroom", "state": "on"},
    ])

    with patch("assistant.light_engine.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2025, 1, 1, 22, 30)
        await engine.on_bed_occupied("binary_sensor.bed", "schlafzimmer")

    redis_client.set.assert_called()
    engine.ha.call_service.assert_called()


@pytest.mark.asyncio
@patch("assistant.light_engine.yaml_config", {
    "lighting": {"enabled": True, "bed_sensors": {"enabled": True, "sleep_start_hour": 21}},
})
async def test_on_bed_occupied_ignored_during_day(engine, redis_client):
    await engine.initialize(redis_client)
    with patch("assistant.light_engine.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2025, 1, 1, 14, 0)
        await engine.on_bed_occupied("binary_sensor.bed", "schlafzimmer")

    engine.ha.call_service.assert_not_called()


# ── on_bed_clear ──────────────────────────────────────────────

@pytest.mark.asyncio
@patch("assistant.light_engine.get_room_profiles", return_value={"rooms": {"schlafzimmer": {"light_entities": ["light.bed"]}}})
@patch("assistant.light_engine.yaml_config", {
    "lighting": {
        "enabled": True,
        "bed_sensors": {"enabled": True, "wakeup_light": True, "wakeup_window_start": 5, "wakeup_window_end": 9, "wakeup_brightness": 40, "wakeup_transition": 120},
        "presence_control": {"night_start_hour": 22, "night_end_hour": 6},
    },
})
async def test_on_bed_clear_wakeup_light(mock_profiles, engine, redis_client):
    await engine.initialize(redis_client)
    with patch("assistant.light_engine.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2025, 1, 1, 7, 0)
        await engine.on_bed_clear("binary_sensor.bed", "schlafzimmer")

    engine.ha.call_service.assert_called()


# ── on_lux_change ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_on_lux_change_stores_value(engine):
    await engine.on_lux_change("sensor.lux", "wohnzimmer", 350.0)
    assert engine._room_lux["wohnzimmer"] == 350.0


# ── Manual Override ───────────────────────────────────────────

@pytest.mark.asyncio
@patch("assistant.light_engine.yaml_config", {
    "lighting": {"presence_control": {"manual_override_minutes": 30}},
    "seasonal_actions": {},
})
async def test_record_manual_override(engine, redis_client):
    await engine.initialize(redis_client)
    await engine.record_manual_override("light.wz")
    redis_client.set.assert_called_once()
    args = redis_client.set.call_args
    assert _R_OVERRIDE in args[0][0]


@pytest.mark.asyncio
async def test_record_manual_override_no_redis(engine):
    engine.redis = None
    await engine.record_manual_override("light.wz")  # should not raise


@pytest.mark.asyncio
async def test_is_manual_override_active_true(engine, redis_client):
    await engine.initialize(redis_client)
    redis_client.get = AsyncMock(return_value=b"1")
    assert await engine.is_manual_override_active("light.wz") is True


@pytest.mark.asyncio
async def test_is_manual_override_active_false(engine, redis_client):
    await engine.initialize(redis_client)
    redis_client.get = AsyncMock(return_value=None)
    assert await engine.is_manual_override_active("light.wz") is False


@pytest.mark.asyncio
async def test_is_manual_override_no_redis(engine):
    engine.redis = None
    assert await engine.is_manual_override_active("light.wz") is False


# ── Helper methods ────────────────────────────────────────────

@patch("assistant.light_engine.get_room_profiles", return_value={"rooms": {"wohnzimmer": {"light_entities": ["light.wz", "light.wz2"]}}})
def test_get_room_lights(mock_profiles, engine):
    lights = engine._get_room_lights("wohnzimmer", {"light_entities": ["light.wz", "light.wz2"]})
    assert lights == ["light.wz", "light.wz2"]


def test_get_room_lights_empty(engine):
    assert engine._get_room_lights("unknown", {}) == []


def test_get_room_lights_non_list(engine):
    assert engine._get_room_lights("room", {"light_entities": "not_a_list"}) == []


@patch("assistant.light_engine.yaml_config", {"lighting": {"presence_control": {"night_start_hour": 22, "night_end_hour": 6}}})
def test_is_night_at_midnight(engine):
    with patch("assistant.light_engine.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2025, 1, 1, 0, 30)
        assert engine._is_night({"night_start_hour": 22, "night_end_hour": 6}) is True


@patch("assistant.light_engine.yaml_config", {"lighting": {"presence_control": {"night_start_hour": 22, "night_end_hour": 6}}})
def test_is_night_at_noon(engine):
    with patch("assistant.light_engine.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2025, 1, 1, 12, 0)
        assert engine._is_night({"night_start_hour": 22, "night_end_hour": 6}) is False


def test_anyone_home_true():
    states = [{"entity_id": "person.alice", "state": "home"}]
    assert LightEngine._anyone_home(states) is True


def test_anyone_home_false():
    states = [{"entity_id": "person.alice", "state": "away"}]
    assert LightEngine._anyone_home(states) is False


def test_anyone_home_no_persons():
    states = [{"entity_id": "light.wz", "state": "on"}]
    assert LightEngine._anyone_home(states) is False


def test_find_room_for_light(engine):
    rooms = {"wohnzimmer": {"light_entities": ["light.wz"]}, "kueche": {"light_entities": ["light.ku"]}}
    assert engine._find_room_for_light("light.wz", rooms) == "wohnzimmer"
    assert engine._find_room_for_light("light.unknown", rooms) is None


# ── _check_away_auto_off ──────────────────────────────────────

@pytest.mark.asyncio
@patch("assistant.light_engine.yaml_config", {"lighting": {"enabled": True, "default_transition": 2}})
async def test_check_away_auto_off_turns_off_lights(engine, redis_client):
    await engine.initialize(redis_client)
    states = [
        {"entity_id": "person.alice", "state": "away"},
        {"entity_id": "light.wz", "state": "on"},
    ]
    await engine._check_away_auto_off({"default_transition": 2}, states)
    engine.ha.call_service.assert_called()
    assert engine.ha.call_service.call_args[0][1] == "turn_off"


@pytest.mark.asyncio
@patch("assistant.light_engine.yaml_config", {"lighting": {"enabled": True}})
async def test_check_away_auto_off_skips_when_home(engine, redis_client):
    await engine.initialize(redis_client)
    states = [{"entity_id": "person.alice", "state": "home"}]
    await engine._check_away_auto_off({}, states)
    engine.ha.call_service.assert_not_called()


# ── _get_weather_condition ────────────────────────────────────

def test_get_weather_condition_configured():
    states = [{"entity_id": "weather.custom", "state": "rainy"}]
    result = LightEngine._get_weather_condition(states, {"weather_entity": "weather.custom"})
    assert result == "rainy"


def test_get_weather_condition_default():
    states = [{"entity_id": "weather.forecast_home", "state": "cloudy"}]
    result = LightEngine._get_weather_condition(states, {})
    assert result == "cloudy"


def test_get_weather_condition_none():
    result = LightEngine._get_weather_condition([], {})
    assert result == ""
