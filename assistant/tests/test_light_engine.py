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
    mock_fe.get_adaptive_brightness = MagicMock(return_value=70)
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
    mock_fe.get_adaptive_brightness = MagicMock(return_value=70)
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
    mock_fe.get_adaptive_brightness = MagicMock(return_value=70)
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


# ── Night Dimming ────────────────────────────────────────────

@pytest.mark.asyncio
@patch("assistant.light_engine.get_room_profiles", return_value={
    "rooms": {"wohnzimmer": {"light_entities": ["light.wz"], "night_brightness": 20}}
})
@patch("assistant.light_engine.yaml_config", {
    "lighting": {"enabled": True, "night_dimming": True, "night_dimming_start_hour": 21, "night_dimming_transition": 300},
})
async def test_night_dimming_dims_bright_lights(mock_profiles, engine, redis_client):
    """Night dimming should reduce lights above night_brightness threshold."""
    await engine.initialize(redis_client)
    states = [
        {"entity_id": "light.wz", "state": "on", "attributes": {"brightness": 200}},
    ]
    with patch("assistant.light_engine.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2025, 1, 1, 22, 0)
        await engine._check_night_dimming(
            {"night_dimming_start_hour": 21, "night_dimming_transition": 300}, states,
        )
    engine.ha.call_service.assert_called()
    call_data = engine.ha.call_service.call_args[0][2]
    assert call_data["brightness_pct"] == 20
    assert call_data["transition"] == 300


@pytest.mark.asyncio
@patch("assistant.light_engine.get_room_profiles", return_value={
    "rooms": {"wohnzimmer": {"light_entities": ["light.wz"], "night_brightness": 20}}
})
@patch("assistant.light_engine.yaml_config", {
    "lighting": {"enabled": True, "night_dimming": True},
})
async def test_night_dimming_skips_already_dim_lights(mock_profiles, engine, redis_client):
    """Lights already at or below night_brightness should not be dimmed again."""
    await engine.initialize(redis_client)
    states = [
        {"entity_id": "light.wz", "state": "on", "attributes": {"brightness": 51}},  # ~20%
    ]
    with patch("assistant.light_engine.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2025, 1, 1, 22, 0)
        await engine._check_night_dimming(
            {"night_dimming_start_hour": 21, "night_dimming_transition": 300}, states,
        )
    engine.ha.call_service.assert_not_called()


@pytest.mark.asyncio
@patch("assistant.light_engine.yaml_config", {"lighting": {"enabled": True}})
async def test_night_dimming_skips_during_day(engine, redis_client):
    """Night dimming should not run during daytime hours."""
    await engine.initialize(redis_client)
    states = [{"entity_id": "light.wz", "state": "on", "attributes": {"brightness": 200}}]
    with patch("assistant.light_engine.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2025, 1, 1, 14, 0)
        await engine._check_night_dimming(
            {"night_dimming_start_hour": 21, "night_dimming_transition": 300}, states,
        )
    engine.ha.call_service.assert_not_called()


@pytest.mark.asyncio
@patch("assistant.light_engine.get_room_profiles", return_value={
    "rooms": {"wohnzimmer": {"light_entities": ["light.wz"], "night_brightness": 20}}
})
@patch("assistant.light_engine.yaml_config", {"lighting": {"enabled": True}})
async def test_night_dimming_skips_manual_override(mock_profiles, engine, redis_client):
    """Night dimming should respect manual override."""
    await engine.initialize(redis_client)
    redis_client.get = AsyncMock(side_effect=lambda key: b"1" if "override" in key else None)
    states = [{"entity_id": "light.wz", "state": "on", "attributes": {"brightness": 200}}]
    with patch("assistant.light_engine.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2025, 1, 1, 22, 0)
        await engine._check_night_dimming(
            {"night_dimming_start_hour": 21, "night_dimming_transition": 300}, states,
        )
    # Only the override check calls happened, no turn_on service calls
    for call in engine.ha.call_service.call_args_list:
        assert call[0][1] != "turn_on"


# ── Sleep Mode ───────────────────────────────────────────────

@pytest.mark.asyncio
@patch("assistant.light_engine.yaml_config", {
    "lighting": {"enabled": True, "bed_sensors": {"enabled": True, "sleep_dim_transition": 300}},
})
async def test_apply_sleep_mode_turns_off_all_lights(engine, redis_client):
    """Sleep mode should turn off all lights in the house with transition."""
    await engine.initialize(redis_client)
    engine.ha.get_states = AsyncMock(return_value=[
        {"entity_id": "light.wz", "state": "on"},
        {"entity_id": "light.kueche", "state": "on"},
        {"entity_id": "light.bad", "state": "off"},
        {"entity_id": "sensor.temp", "state": "22.5"},
    ])
    await engine._apply_sleep_mode({}, {"sleep_dim_transition": 300})
    # Should turn off 2 lights (the ones that are on)
    assert engine.ha.call_service.call_count == 2
    for call in engine.ha.call_service.call_args_list:
        assert call[0][1] == "turn_off"
        assert call[0][2]["transition"] == 300


@pytest.mark.asyncio
async def test_apply_sleep_mode_no_states(engine, redis_client):
    """Sleep mode should handle empty states gracefully."""
    await engine.initialize(redis_client)
    engine.ha.get_states = AsyncMock(return_value=None)
    await engine._apply_sleep_mode({}, {"sleep_dim_transition": 300})
    engine.ha.call_service.assert_not_called()


# ── Night Path Light ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_apply_night_path_light(engine, redis_client):
    """Night path light should set very low brightness and TTL."""
    await engine.initialize(redis_client)
    lights = ["light.flur", "light.bad"]
    pc = {"night_path_brightness": 5, "night_path_timeout_minutes": 5}
    await engine._apply_night_path_light("flur", lights, pc)
    assert engine.ha.call_service.call_count == 2
    for call in engine.ha.call_service.call_args_list:
        assert call[0][2]["brightness_pct"] == 5
        assert call[0][2]["transition"] == 2
    # Redis TTL should be set (5 min = 300s)
    assert redis_client.set.call_count >= 2


@pytest.mark.asyncio
async def test_apply_night_path_light_no_redis(engine):
    """Night path light should work without Redis (no TTL tracking)."""
    engine.redis = None
    await engine._apply_night_path_light("flur", ["light.flur"], {"night_path_brightness": 3, "night_path_timeout_minutes": 5})
    engine.ha.call_service.assert_called_once()


# ── Wakeup Light ─────────────────────────────────────────────

@pytest.mark.asyncio
@patch("assistant.light_engine.get_room_profiles", return_value={
    "rooms": {"schlafzimmer": {"light_entities": ["light.bed1", "light.bed2"]}}
})
@patch("assistant.light_engine.yaml_config", {"lighting": {"enabled": True}})
async def test_apply_wakeup_light_gradual(mock_profiles, engine):
    """Wakeup light should turn on lights with gradual transition."""
    bed_cfg = {"wakeup_brightness": 40, "wakeup_transition": 120}
    await engine._apply_wakeup_light("schlafzimmer", {}, bed_cfg)
    assert engine.ha.call_service.call_count == 2
    for call in engine.ha.call_service.call_args_list:
        assert call[0][2]["brightness_pct"] == 40
        assert call[0][2]["transition"] == 120


@pytest.mark.asyncio
@patch("assistant.light_engine.get_room_profiles", return_value={"rooms": {"schlafzimmer": {}}})
@patch("assistant.light_engine.yaml_config", {"lighting": {"enabled": True}})
async def test_apply_wakeup_light_no_lights_in_room(mock_profiles, engine):
    """Wakeup light should do nothing if room has no lights."""
    await engine._apply_wakeup_light("schlafzimmer", {}, {"wakeup_brightness": 40, "wakeup_transition": 120})
    engine.ha.call_service.assert_not_called()


# ── Dusk Auto-On ─────────────────────────────────────────────

@pytest.mark.asyncio
@patch("assistant.light_engine.get_room_profiles", return_value={
    "rooms": {"wohnzimmer": {"light_entities": ["light.wz"]}}
})
@patch("assistant.light_engine.FunctionExecutor")
@patch("assistant.light_engine.yaml_config", {
    "lighting": {"enabled": True, "dusk_sun_elevation": -2, "default_transition": 2, "dusk_only_occupied_rooms": False},
})
async def test_dusk_auto_on_triggers_at_sunset(mock_fe, mock_profiles, engine, redis_client):
    """Dusk auto-on should turn on lights when sun drops below threshold."""
    await engine.initialize(redis_client)
    mock_fe.get_adaptive_brightness = MagicMock(return_value=80)
    engine.ha.get_state = AsyncMock(return_value={"state": "off"})
    states = [
        {"entity_id": "sun.sun", "state": "below_horizon", "attributes": {"elevation": -3.0}},
        {"entity_id": "person.alice", "state": "home"},
    ]
    await engine._check_dusk_auto_on(
        {"dusk_sun_elevation": -2, "default_transition": 2, "dusk_only_occupied_rooms": False}, states,
    )
    engine.ha.call_service.assert_called()


@pytest.mark.asyncio
@patch("assistant.light_engine.yaml_config", {"lighting": {"enabled": True}})
async def test_dusk_auto_on_skips_when_nobody_home(engine, redis_client):
    """Dusk auto-on should not trigger if nobody is home."""
    await engine.initialize(redis_client)
    states = [
        {"entity_id": "sun.sun", "state": "below_horizon", "attributes": {"elevation": -3.0}},
        {"entity_id": "person.alice", "state": "away"},
    ]
    await engine._check_dusk_auto_on({"dusk_sun_elevation": -2}, states)
    engine.ha.call_service.assert_not_called()


@pytest.mark.asyncio
@patch("assistant.light_engine.yaml_config", {"lighting": {"enabled": True}})
async def test_dusk_auto_on_skips_above_threshold(engine, redis_client):
    """Dusk auto-on should not trigger when sun is above threshold."""
    await engine.initialize(redis_client)
    states = [
        {"entity_id": "sun.sun", "state": "above_horizon", "attributes": {"elevation": 10.0}},
        {"entity_id": "person.alice", "state": "home"},
    ]
    await engine._check_dusk_auto_on({"dusk_sun_elevation": -2}, states)
    engine.ha.call_service.assert_not_called()


# ── Weather Boost ────────────────────────────────────────────

@pytest.mark.asyncio
@patch("assistant.light_engine.get_room_profiles", return_value={
    "rooms": {"wohnzimmer": {"light_entities": ["light.wz"]}}
})
@patch("assistant.light_engine.yaml_config", {"lighting": {"enabled": True, "night_dimming_start_hour": 21, "presence_control": {"night_end_hour": 6}}})
async def test_weather_boost_increases_brightness_on_rain(mock_profiles, engine, redis_client):
    """Weather boost should increase brightness during rainy conditions."""
    await engine.initialize(redis_client)
    redis_client.get = AsyncMock(return_value=None)  # No prior boost
    engine.ha.get_state = AsyncMock(return_value={
        "state": "on", "attributes": {"brightness": 128},  # ~50%
    })
    states = [{"entity_id": "weather.forecast_home", "state": "rainy"}]
    wb_cfg = {"enabled": True, "rain_boost_pct": 25}
    with patch("assistant.light_engine.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2025, 1, 1, 14, 0)  # Daytime
        await engine._check_weather_boost(
            {"weather_boost": wb_cfg, "night_dimming_start_hour": 21, "presence_control": {"night_end_hour": 6}},
            states,
        )
    engine.ha.call_service.assert_called()
    call_data = engine.ha.call_service.call_args[0][2]
    assert call_data["brightness_pct"] == 75  # 50 + 25


@pytest.mark.asyncio
@patch("assistant.light_engine.yaml_config", {"lighting": {"enabled": True, "night_dimming_start_hour": 21, "presence_control": {"night_end_hour": 6}}})
async def test_weather_boost_skips_at_night(engine, redis_client):
    """Weather boost should not activate during nighttime."""
    await engine.initialize(redis_client)
    states = [{"entity_id": "weather.forecast_home", "state": "rainy"}]
    with patch("assistant.light_engine.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2025, 1, 1, 22, 0)  # Night
        await engine._check_weather_boost(
            {"weather_boost": {"enabled": True}, "night_dimming_start_hour": 21, "presence_control": {"night_end_hour": 6}},
            states,
        )
    engine.ha.call_service.assert_not_called()


# ── is_weather_boost_active ──────────────────────────────────

@pytest.mark.asyncio
async def test_is_weather_boost_active_true(engine, redis_client):
    """Should return True when weather boost Redis key exists."""
    await engine.initialize(redis_client)
    redis_client.get = AsyncMock(return_value=b"rainy")
    assert await engine._is_weather_boost_active() is True


@pytest.mark.asyncio
async def test_is_weather_boost_active_false_no_redis(engine):
    """Should return False when Redis is not available."""
    engine.redis = None
    assert await engine._is_weather_boost_active() is False


# ── Lux Adaptive ─────────────────────────────────────────────

@pytest.mark.asyncio
@patch("assistant.light_engine.get_room_profiles", return_value={
    "rooms": {"wohnzimmer": {"light_entities": ["light.wz"], "lux_sensor": "sensor.lux_wz"}}
})
@patch("assistant.light_engine.yaml_config", {"lighting": {"enabled": True, "lux_adaptive": {"enabled": True, "target_lux": 400, "min_brightness_pct": 10, "max_brightness_pct": 100}}})
async def test_lux_adaptive_adjusts_brightness(mock_profiles, engine, redis_client):
    """Lux adaptive should lower brightness when daylight is sufficient."""
    await engine.initialize(redis_client)
    redis_client.get = AsyncMock(return_value=None)  # No override, no weather boost
    engine._room_lux["wohnzimmer"] = 200  # Half of target 400
    engine.ha.get_state = AsyncMock(return_value={
        "state": "on", "attributes": {"brightness": 255},  # Currently 100%
    })
    states = []
    await engine._check_lux_adaptive(
        {"lux_adaptive": {"enabled": True, "target_lux": 400, "min_brightness_pct": 10, "max_brightness_pct": 100}},
        states,
    )
    engine.ha.call_service.assert_called()
    call_data = engine.ha.call_service.call_args[0][2]
    assert call_data["brightness_pct"] == 50  # 100% * (1 - 200/400)


@pytest.mark.asyncio
@patch("assistant.light_engine.get_room_profiles", return_value={
    "rooms": {"wohnzimmer": {"light_entities": ["light.wz"], "lux_sensor": "sensor.lux_wz"}}
})
@patch("assistant.light_engine.yaml_config", {"lighting": {"enabled": True, "lux_adaptive": {"enabled": True}}})
async def test_lux_adaptive_skips_when_weather_boost_active(mock_profiles, engine, redis_client):
    """Lux adaptive should skip when weather boost is active to avoid conflict."""
    await engine.initialize(redis_client)
    redis_client.get = AsyncMock(return_value=b"rainy")  # Weather boost active
    engine._room_lux["wohnzimmer"] = 200
    await engine._check_lux_adaptive(
        {"lux_adaptive": {"enabled": True}}, [],
    )
    engine.ha.call_service.assert_not_called()


# ── Cover Position Change ────────────────────────────────────

@pytest.mark.asyncio
@patch("assistant.light_engine.get_room_profiles", return_value={
    "rooms": {"wohnzimmer": {"light_entities": ["light.wz"], "cover_entities": ["cover.wz"]}}
})
@patch("assistant.light_engine.FunctionExecutor")
@patch("assistant.light_engine.yaml_config", {"lighting": {"enabled": True}})
async def test_on_cover_position_change_brightens_light(mock_fe, mock_profiles, engine, redis_client):
    """When cover closes, lights should be brightened to compensate."""
    await engine.initialize(redis_client)
    mock_fe.get_adaptive_brightness = MagicMock(return_value=80)
    redis_client.get = AsyncMock(return_value=None)  # No override
    engine.ha.get_state = AsyncMock(return_value={
        "state": "on", "attributes": {"brightness": 102},  # ~40%
    })
    await engine.on_cover_position_change("cover.wz", position=20)
    engine.ha.call_service.assert_called()
    call_data = engine.ha.call_service.call_args[0][2]
    assert call_data["brightness_pct"] == 80


@pytest.mark.asyncio
@patch("assistant.light_engine.yaml_config", {"lighting": {"enabled": False}})
async def test_on_cover_position_change_disabled(engine):
    """Cover-light coordination should not run when lighting disabled."""
    await engine.on_cover_position_change("cover.wz", position=20)
    engine.ha.call_service.assert_not_called()


@pytest.mark.asyncio
@patch("assistant.light_engine.yaml_config", {"lighting": {"enabled": True, "lux_adaptive": {"enabled": True}}})
async def test_on_cover_position_change_skips_when_lux_adaptive(engine):
    """Cover-light should not run when lux-adaptive is enabled (sensor is more accurate)."""
    await engine.on_cover_position_change("cover.wz", position=20)
    engine.ha.call_service.assert_not_called()


# ── Restore Adaptive Brightness ──────────────────────────────

@pytest.mark.asyncio
@patch("assistant.light_engine.get_room_profiles", return_value={
    "rooms": {"wohnzimmer": {"light_entities": ["light.wz"]}}
})
@patch("assistant.light_engine.FunctionExecutor")
@patch("assistant.light_engine.yaml_config", {"lighting": {"enabled": True}})
async def test_restore_adaptive_brightness(mock_fe, mock_profiles, engine, redis_client):
    """After weather boost ends, lights should be restored to adaptive brightness."""
    await engine.initialize(redis_client)
    mock_fe.get_adaptive_brightness = MagicMock(return_value=60)
    redis_client.get = AsyncMock(return_value=None)  # No override
    engine.ha.get_state = AsyncMock(return_value={
        "state": "on", "attributes": {"brightness": 204},  # ~80%
    })
    await engine._restore_adaptive_brightness({})
    engine.ha.call_service.assert_called()
    call_data = engine.ha.call_service.call_args[0][2]
    assert call_data["brightness_pct"] == 60


# ── _is_morning_window ───────────────────────────────────────

@patch("assistant.light_engine.yaml_config", {"lighting": {"bed_sensors": {"wakeup_window_start": 5, "wakeup_window_end": 9}}})
def test_is_morning_window_during_morning(engine):
    with patch("assistant.light_engine.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2025, 1, 1, 7, 0)
        assert engine._is_morning_window() is True


@patch("assistant.light_engine.yaml_config", {"lighting": {"bed_sensors": {"wakeup_window_start": 5, "wakeup_window_end": 9}}})
def test_is_morning_window_outside_window(engine):
    with patch("assistant.light_engine.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2025, 1, 1, 10, 0)
        assert engine._is_morning_window() is False


# ── _is_night edge cases ─────────────────────────────────────

@patch("assistant.light_engine.yaml_config", {"lighting": {"presence_control": {"night_start_hour": 22, "night_end_hour": 6}}})
def test_is_night_at_boundary_start(engine):
    """Exactly at night_start_hour should be night."""
    with patch("assistant.light_engine.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2025, 1, 1, 22, 0)
        assert engine._is_night({"night_start_hour": 22, "night_end_hour": 6}) is True


@patch("assistant.light_engine.yaml_config", {"lighting": {"presence_control": {"night_start_hour": 22, "night_end_hour": 6}}})
def test_is_night_at_boundary_end(engine):
    """Exactly at night_end_hour should NOT be night."""
    with patch("assistant.light_engine.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2025, 1, 1, 6, 0)
        assert engine._is_night({"night_start_hour": 22, "night_end_hour": 6}) is False


def test_is_night_no_config_uses_defaults(engine):
    """When no config provided, should use defaults from yaml_config."""
    with patch("assistant.light_engine.yaml_config", {"lighting": {"presence_control": {"night_start_hour": 23, "night_end_hour": 5}}}):
        with patch("assistant.light_engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 1, 23, 30)
            assert engine._is_night() is True


# ── Mood-based brightness adjustments ────────────────────────

@pytest.mark.asyncio
@patch("assistant.light_engine.get_room_profiles", return_value={"rooms": {"wohnzimmer": {"light_entities": ["light.wz"], "presence_auto_on": True}}})
@patch("assistant.light_engine.FunctionExecutor")
@patch("assistant.light_engine.yaml_config", {
    "lighting": {"enabled": True, "presence_control": {"enabled": True, "auto_on_motion": True}},
})
async def test_on_motion_with_mood_tired(mock_fe, mock_profiles, engine):
    """Tired mood should cap brightness at 30%."""
    mock_fe.get_adaptive_brightness = MagicMock(return_value=70)
    engine.ha.get_state = AsyncMock(return_value={"state": "off"})
    engine.redis = None
    engine.mood = MagicMock()
    engine.mood.get_current_mood.return_value = {"mood": "tired"}

    await engine.on_motion("binary_sensor.motion", "wohnzimmer")
    call_args = engine.ha.call_service.call_args[0][2]
    assert call_args["brightness_pct"] <= 30


@pytest.mark.asyncio
@patch("assistant.light_engine.get_room_profiles", return_value={"rooms": {"wohnzimmer": {"light_entities": ["light.wz"], "presence_auto_on": True}}})
@patch("assistant.light_engine.FunctionExecutor")
@patch("assistant.light_engine.yaml_config", {
    "lighting": {"enabled": True, "presence_control": {"enabled": True, "auto_on_motion": True}},
})
async def test_on_motion_with_mood_exception(mock_fe, mock_profiles, engine):
    """Mood exception should be handled gracefully."""
    mock_fe.get_adaptive_brightness = MagicMock(return_value=70)
    engine.ha.get_state = AsyncMock(return_value={"state": "off"})
    engine.redis = None
    engine.mood = MagicMock()
    engine.mood.get_current_mood.side_effect = RuntimeError("mood service down")

    await engine.on_motion("binary_sensor.motion", "wohnzimmer")
    # Should still turn on with non-mood-adjusted brightness
    engine.ha.call_service.assert_called_once()
    call_args = engine.ha.call_service.call_args[0][2]
    assert call_args["brightness_pct"] == 70


# ── Weather condition edge cases ─────────────────────────────

def test_get_weather_condition_fallback_to_first_weather():
    """Should fall back to first weather entity if no specific one configured."""
    states = [
        {"entity_id": "light.test", "state": "on"},
        {"entity_id": "weather.garden", "state": "Sunny"},
    ]
    result = LightEngine._get_weather_condition(states, {})
    assert result == "sunny"


def test_get_weather_condition_case_insensitive():
    """Weather condition should be lowercased."""
    states = [{"entity_id": "weather.forecast_home", "state": "RAINY"}]
    result = LightEngine._get_weather_condition(states, {})
    assert result == "rainy"


# ── _find_room_for_light edge cases ──────────────────────────

def test_find_room_for_light_non_list_entities(engine):
    """Should handle non-list light_entities gracefully."""
    rooms = {"wohnzimmer": {"light_entities": "not_a_list"}}
    assert engine._find_room_for_light("light.wz", rooms) is None


# ── Pathlight timeout ────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_pathlight_timeout_no_redis(engine):
    """Pathlight timeout check should do nothing without Redis."""
    engine.redis = None
    await engine._check_pathlight_timeout({})
    engine.ha.call_service.assert_not_called()


@pytest.mark.asyncio
async def test_check_pathlight_timeout_turns_off_expired(engine, redis_client):
    """Should turn off lights whose pathlight TTL has expired."""
    await engine.initialize(redis_client)
    redis_client.scan = AsyncMock(return_value=(b"0", [b"mha:light:pathlight:light.flur"]))
    redis_client.ttl = AsyncMock(return_value=-2)  # Key expired
    await engine._check_pathlight_timeout({"default_transition": 2})
    engine.ha.call_service.assert_called()
    assert engine.ha.call_service.call_args[0][1] == "turn_off"
