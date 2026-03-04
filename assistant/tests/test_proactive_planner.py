"""
Tests fuer ProactiveSequencePlanner — Multi-Step-Planung.

Testet:
- Ankunfts-Sequenz (Licht + Klima)
- Wetter-Sequenz (Fenster-Warnung + Rollladen)
- Gaeste-Sequenz (Licht + Musik)
- Cooldown-Logik
- Safety: Security-Aktionen nie automatisch
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from assistant.proactive_planner import ProactiveSequencePlanner


@pytest.fixture
def ha_mock():
    return AsyncMock()


@pytest.fixture
def planner(ha_mock):
    with patch("assistant.proactive_planner.yaml_config", {"proactive_planner": {"enabled": True}}):
        p = ProactiveSequencePlanner(ha=ha_mock)
    return p


@pytest.fixture
def planner_with_redis(planner, redis_mock):
    planner.redis = redis_mock
    return planner


# ============================================================
# Initialisierung
# ============================================================

class TestPlannerInit:

    def test_default_config(self, planner):
        assert planner.enabled is True
        assert planner.min_autonomy_for_auto == 4

    @pytest.mark.asyncio
    async def test_initialize(self, planner, redis_mock):
        await planner.initialize(redis_client=redis_mock)
        assert planner.redis is redis_mock

    def test_disabled(self, ha_mock):
        with patch("assistant.proactive_planner.yaml_config", {"proactive_planner": {"enabled": False}}):
            p = ProactiveSequencePlanner(ha=ha_mock)
        assert p.enabled is False


# ============================================================
# Person Arrived
# ============================================================

class TestArrivalSequence:

    @pytest.mark.asyncio
    async def test_evening_arrival_with_eco(self, planner_with_redis):
        p = planner_with_redis
        p.redis.exists = AsyncMock(return_value=0)

        context = {
            "house": {
                "climate": [{"preset_mode": "eco", "hvac_mode": "heat"}],
            },
            "person": {"name": "Max"},
        }

        with patch("assistant.proactive_planner.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 19, 0)  # 19 Uhr
            result = await p.plan_from_context_change("person_arrived", context, autonomy_level=2)

        assert result is not None
        assert result["trigger"] == "person_arrived"
        # Abends: Licht + Klima
        action_types = [a["type"] for a in result["actions"]]
        assert "set_light" in action_types
        assert "set_climate" in action_types
        assert result["needs_confirmation"] is True  # Level 2 < 4

    @pytest.mark.asyncio
    async def test_daytime_arrival_no_eco(self, planner_with_redis):
        p = planner_with_redis
        p.redis.exists = AsyncMock(return_value=0)

        context = {
            "house": {"climate": [{"preset_mode": "home", "hvac_mode": "heat"}]},
            "person": {"name": "Max"},
        }

        with patch("assistant.proactive_planner.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 12, 0)  # Mittags
            result = await p.plan_from_context_change("person_arrived", context, autonomy_level=2)

        # Tagsüber kein Licht, kein Eco → keine Aktionen → None
        assert result is None

    @pytest.mark.asyncio
    async def test_auto_execute_at_high_autonomy(self, planner_with_redis):
        p = planner_with_redis
        p.redis.exists = AsyncMock(return_value=0)

        context = {
            "house": {"climate": [{"preset_mode": "eco"}]},
            "person": {"name": "Max"},
        }

        with patch("assistant.proactive_planner.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 20, 0)
            result = await p.plan_from_context_change("person_arrived", context, autonomy_level=5)

        assert result is not None
        assert result["needs_confirmation"] is False  # Level 5 >= 4


# ============================================================
# Weather Changed
# ============================================================

class TestWeatherSequence:

    @pytest.mark.asyncio
    async def test_rain_with_open_windows(self, planner_with_redis):
        p = planner_with_redis
        p.redis.exists = AsyncMock(return_value=0)

        context = {
            "weather": {"condition": "rainy"},
            "house": {"open_windows": ["Kueche", "Bad"]},
        }

        result = await p.plan_from_context_change("weather_changed", context)
        assert result is not None
        assert result["trigger"] == "weather_changed"
        assert any("Fenster" in a.get("description", "") for a in result["actions"])

    @pytest.mark.asyncio
    async def test_hail_triggers_cover(self, planner_with_redis):
        p = planner_with_redis
        p.redis.exists = AsyncMock(return_value=0)

        context = {
            "weather": {"condition": "hail"},
            "house": {"open_windows": []},
        }

        result = await p.plan_from_context_change("weather_changed", context)
        assert result is not None
        assert any(a["type"] == "set_cover" for a in result["actions"])

    @pytest.mark.asyncio
    async def test_sunny_no_action(self, planner_with_redis):
        p = planner_with_redis
        p.redis.exists = AsyncMock(return_value=0)

        context = {
            "weather": {"condition": "sunny"},
            "house": {"open_windows": []},
        }

        result = await p.plan_from_context_change("weather_changed", context)
        assert result is None


# ============================================================
# Guest Sequence
# ============================================================

class TestGuestSequence:

    @pytest.mark.asyncio
    async def test_evening_guest_event(self, planner_with_redis):
        p = planner_with_redis
        p.redis.exists = AsyncMock(return_value=0)

        with patch("assistant.proactive_planner.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 18, 0)
            result = await p.plan_from_context_change("calendar_event_soon", {})

        assert result is not None
        assert result["trigger"] == "calendar_event_soon"
        action_types = [a["type"] for a in result["actions"]]
        assert "set_light" in action_types
        assert "play_media" in action_types


# ============================================================
# Cooldown
# ============================================================

class TestCooldown:

    @pytest.mark.asyncio
    async def test_cooldown_blocks_repeat(self, planner_with_redis):
        p = planner_with_redis
        p.redis.exists = AsyncMock(return_value=1)  # Cooldown aktiv

        context = {
            "weather": {"condition": "hail"},
            "house": {"open_windows": ["Fenster"]},
        }

        result = await p.plan_from_context_change("weather_changed", context)
        assert result is None


# ============================================================
# Safety: Security-Aktionen
# ============================================================

class TestSecuritySafety:

    @pytest.mark.asyncio
    async def test_security_action_always_needs_confirmation(self, planner_with_redis):
        p = planner_with_redis
        p.redis.exists = AsyncMock(return_value=0)

        # Erzwinge einen Plan mit Security-Aktion
        async def fake_plan(*args, **kwargs):
            return {
                "trigger": "person_arrived",
                "actions": [{"type": "unlock_door", "args": {}, "description": "Tuer entriegeln"}],
                "message": "Test",
                "auto_message": "Test",
            }

        p._plan_arrival_sequence = fake_plan

        context = {"person": {"name": "Max"}}
        result = await p.plan_from_context_change("person_arrived", context, autonomy_level=5)

        assert result is not None
        assert result["needs_confirmation"] is True  # Trotz Level 5!


# ============================================================
# Disabled Planner
# ============================================================

class TestDisabledPlanner:

    @pytest.mark.asyncio
    async def test_disabled_returns_none(self, planner):
        planner.enabled = False
        result = await planner.plan_from_context_change("person_arrived", {})
        assert result is None


# ============================================================
# Status
# ============================================================

class TestPlannerStatus:

    @pytest.mark.asyncio
    async def test_status_without_redis(self, planner):
        status = await planner.get_status()
        assert status["enabled"] is True
        assert "active_cooldowns" not in status

    @pytest.mark.asyncio
    async def test_status_with_redis(self, planner_with_redis):
        planner_with_redis.redis.scan = AsyncMock(return_value=(0, [b"key1", b"key2"]))
        status = await planner_with_redis.get_status()
        assert status["active_cooldowns"] == 2
