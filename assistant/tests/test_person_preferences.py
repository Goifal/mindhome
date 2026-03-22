"""
Tests fuer PersonPreferences — Per-Person Preference Store.

Testet:
- get/set einzelne Praeferenzen
- get_all
- Validierung (Typ, Wertebereich)
- learn_from_correction
- get_context_hint
"""

from unittest.mock import AsyncMock

import pytest

from assistant.person_preferences import (
    PersonPreferences,
    KNOWN_PREFERENCES,
    REDIS_KEY_PREFIX,
)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def prefs():
    redis = AsyncMock()
    redis.hget = AsyncMock(return_value=None)
    redis.hgetall = AsyncMock(return_value={})
    redis.hset = AsyncMock()
    redis.expire = AsyncMock()
    return PersonPreferences(redis)


# ============================================================
# get()
# ============================================================


class TestGet:
    @pytest.mark.asyncio
    async def test_get_returns_default_when_missing(self, prefs):
        result = await prefs.get("Max", "default_brightness", 50)
        assert result == 50

    @pytest.mark.asyncio
    async def test_get_returns_float_for_numeric(self, prefs):
        prefs.redis.hget = AsyncMock(return_value="75.0")
        result = await prefs.get("Max", "default_brightness")
        assert result == 75.0
        assert isinstance(result, float)

    @pytest.mark.asyncio
    async def test_get_returns_string_for_string_pref(self, prefs):
        prefs.redis.hget = AsyncMock(return_value="warm")
        result = await prefs.get("Max", "preferred_color_temp")
        assert result == "warm"

    @pytest.mark.asyncio
    async def test_get_no_person_returns_default(self, prefs):
        result = await prefs.get("", "default_brightness", 42)
        assert result == 42

    @pytest.mark.asyncio
    async def test_get_no_redis_returns_default(self):
        pp = PersonPreferences(None)
        result = await pp.get("Max", "default_brightness", 99)
        assert result == 99

    @pytest.mark.asyncio
    async def test_get_invalid_float_returns_default(self, prefs):
        prefs.redis.hget = AsyncMock(return_value="not_a_number")
        result = await prefs.get("Max", "default_brightness", 50)
        assert result == 50


# ============================================================
# set()
# ============================================================


class TestSet:
    @pytest.mark.asyncio
    async def test_set_basic(self, prefs):
        result = await prefs.set("Max", "default_brightness", 70)
        assert result is True
        prefs.redis.hset.assert_called_once()
        # expire wird 2x aufgerufen: 1x fuer Prefs-Key, 1x fuer History-Key
        assert prefs.redis.expire.call_count == 2

    @pytest.mark.asyncio
    async def test_set_clamps_to_min(self, prefs):
        result = await prefs.set("Max", "default_brightness", -10)
        assert result is True
        # Should clamp to 0
        call_args = prefs.redis.hset.call_args
        assert call_args[0][2] == "0"  # str(0)

    @pytest.mark.asyncio
    async def test_set_clamps_to_max(self, prefs):
        result = await prefs.set("Max", "default_brightness", 200)
        assert result is True
        call_args = prefs.redis.hset.call_args
        assert call_args[0][2] == "100"  # str(100)

    @pytest.mark.asyncio
    async def test_set_invalid_enum_value(self, prefs):
        result = await prefs.set("Max", "preferred_color_temp", "hot_pink")
        assert result is False

    @pytest.mark.asyncio
    async def test_set_valid_enum_value(self, prefs):
        result = await prefs.set("Max", "preferred_color_temp", "warm")
        assert result is True

    @pytest.mark.asyncio
    async def test_set_no_person(self, prefs):
        result = await prefs.set("", "default_brightness", 50)
        assert result is False

    @pytest.mark.asyncio
    async def test_set_no_redis(self):
        pp = PersonPreferences(None)
        result = await pp.set("Max", "default_brightness", 50)
        assert result is False

    @pytest.mark.asyncio
    async def test_set_invalid_float(self, prefs):
        result = await prefs.set("Max", "default_brightness", "abc")
        assert result is False


# ============================================================
# get_all()
# ============================================================


class TestGetAll:
    @pytest.mark.asyncio
    async def test_get_all_empty(self, prefs):
        result = await prefs.get_all("Max")
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_all_with_data(self, prefs):
        prefs.redis.hgetall = AsyncMock(
            return_value={
                "default_brightness": "70",
                "preferred_color_temp": "warm",
            }
        )
        result = await prefs.get_all("Max")
        assert result["default_brightness"] == 70.0
        assert result["preferred_color_temp"] == "warm"

    @pytest.mark.asyncio
    async def test_get_all_no_person(self, prefs):
        result = await prefs.get_all("")
        assert result == {}


# ============================================================
# set_many()
# ============================================================


class TestSetMany:
    @pytest.mark.asyncio
    async def test_set_many_all_valid(self, prefs):
        count = await prefs.set_many(
            "Max",
            {
                "default_brightness": 60,
                "default_temperature": 21,
            },
        )
        assert count == 2

    @pytest.mark.asyncio
    async def test_set_many_partial_valid(self, prefs):
        count = await prefs.set_many(
            "Max",
            {
                "default_brightness": 60,
                "preferred_color_temp": "invalid_value",
            },
        )
        assert count == 1


# ============================================================
# learn_from_correction()
# ============================================================


class TestLearnFromCorrection:
    @pytest.mark.asyncio
    async def test_learns_brightness(self, prefs):
        await prefs.learn_from_correction(
            "Max",
            "set_light",
            {"brightness": 50},
            {"brightness": 80},
        )
        prefs.redis.hset.assert_called()
        # Should have stored default_brightness=80
        call_args = prefs.redis.hset.call_args
        assert "default_brightness" in call_args[0]

    @pytest.mark.asyncio
    async def test_learns_temperature(self, prefs):
        await prefs.learn_from_correction(
            "Max",
            "set_climate",
            {"temperature": 20},
            {"temperature": 22},
        )
        prefs.redis.hset.assert_called()

    @pytest.mark.asyncio
    async def test_no_learn_same_value(self, prefs):
        await prefs.learn_from_correction(
            "Max",
            "set_light",
            {"brightness": 50},
            {"brightness": 50},
        )
        prefs.redis.hset.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_learn_unknown_action(self, prefs):
        await prefs.learn_from_correction(
            "Max",
            "unknown_action",
            {"x": 1},
            {"x": 2},
        )
        prefs.redis.hset.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_learn_empty_person(self, prefs):
        await prefs.learn_from_correction(
            "",
            "set_light",
            {"brightness": 50},
            {"brightness": 80},
        )
        prefs.redis.hset.assert_not_called()


# ============================================================
# get_context_hint()
# ============================================================


class TestGetContextHint:
    @pytest.mark.asyncio
    async def test_hint_empty_when_no_prefs(self, prefs):
        result = await prefs.get_context_hint("Max")
        assert result == ""

    @pytest.mark.asyncio
    async def test_hint_includes_values(self, prefs):
        prefs.redis.hgetall = AsyncMock(
            return_value={
                "default_brightness": "70",
            }
        )
        result = await prefs.get_context_hint("Max")
        assert "Max" in result
        assert "70" in result


# ============================================================
# KNOWN_PREFERENCES Schema
# ============================================================


class TestKnownPreferences:
    def test_brightness_range(self):
        spec = KNOWN_PREFERENCES["default_brightness"]
        assert spec["min"] == 0
        assert spec["max"] == 100

    def test_temperature_range(self):
        spec = KNOWN_PREFERENCES["default_temperature"]
        assert spec["min"] == 15
        assert spec["max"] == 28

    def test_color_temp_values(self):
        spec = KNOWN_PREFERENCES["preferred_color_temp"]
        assert "warm" in spec["values"]
        assert "cool" in spec["values"]
