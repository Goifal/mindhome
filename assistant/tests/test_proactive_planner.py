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


# ============================================================
# Zusaetzliche Tests fuer 100% Coverage
# ============================================================

class TestCooldownExceptions:
    """Tests fuer Cooldown-Exception-Handling — Zeilen 74-75, 94-95."""

    @pytest.mark.asyncio
    async def test_cooldown_check_exception(self, ha_mock):
        """Cooldown-Check Exception wird abgefangen (Zeilen 74-75)."""
        with patch("assistant.proactive_planner.yaml_config", {"proactive_planner": {"enabled": True}}):
            p = ProactiveSequencePlanner(ha=ha_mock)
        redis = AsyncMock()
        redis.exists = AsyncMock(side_effect=Exception("Redis down"))
        redis.setex = AsyncMock()
        p.redis = redis

        context = {
            "weather": {"condition": "hail"},
            "house": {"open_windows": []},
        }
        # Trotz Redis-Fehler beim Cooldown-Check sollte der Plan erstellt werden
        result = await p.plan_from_context_change("weather_changed", context)
        assert result is not None

    @pytest.mark.asyncio
    async def test_cooldown_set_exception(self, ha_mock):
        """Cooldown-Set Exception wird abgefangen (Zeilen 94-95)."""
        with patch("assistant.proactive_planner.yaml_config", {"proactive_planner": {"enabled": True}}):
            p = ProactiveSequencePlanner(ha=ha_mock)
        redis = AsyncMock()
        redis.exists = AsyncMock(return_value=0)
        redis.setex = AsyncMock(side_effect=Exception("Redis write error"))
        p.redis = redis

        context = {
            "weather": {"condition": "pouring"},
            "house": {"open_windows": ["Fenster1"]},
        }
        result = await p.plan_from_context_change("weather_changed", context)
        # Plan wird trotzdem zurueckgegeben
        assert result is not None


class TestGuestSequenceNoActions:
    """Tests fuer _plan_guest_sequence — Zeile 212 (immer Musik, daher nie leer)."""

    @pytest.mark.asyncio
    async def test_daytime_guest_has_music(self, planner_with_redis):
        """Tagsueher hat nur Musik, aber nie leer (implizites Zeile 212)."""
        p = planner_with_redis
        p.redis.exists = AsyncMock(return_value=0)
        with patch("assistant.proactive_planner.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 15, 12, 0)
            result = await p.plan_from_context_change("calendar_event_soon", {})
        assert result is not None
        action_types = [a["type"] for a in result["actions"]]
        assert "play_media" in action_types


class TestStatusExceptions:
    """Tests fuer get_status — Zeilen 241-243."""

    @pytest.mark.asyncio
    async def test_status_redis_scan_exception(self, ha_mock):
        """get_status faengt Scan-Fehler ab (Zeilen 241-243)."""
        with patch("assistant.proactive_planner.yaml_config", {"proactive_planner": {"enabled": True}}):
            p = ProactiveSequencePlanner(ha=ha_mock)
        redis = AsyncMock()
        redis.scan = AsyncMock(side_effect=Exception("Scan failed"))
        p.redis = redis
        status = await p.get_status()
        assert status["active_cooldowns"] == -1


# ============================================================
# Anticipation→Planner Bridge (_enrich_plan_from_patterns)
# ============================================================

class TestAnticipationBridge:
    """Tests fuer _enrich_plan_from_patterns() — Gelernte Muster in Plaene integrieren."""

    @pytest.fixture
    def planner_with_anticipation(self, ha_mock, redis_mock):
        anticipation = AsyncMock()
        with patch("assistant.proactive_planner.yaml_config", {"proactive_planner": {"enabled": True}}):
            p = ProactiveSequencePlanner(ha=ha_mock, anticipation=anticipation)
        p.redis = redis_mock
        return p

    @pytest.mark.asyncio
    async def test_enrich_adds_learned_actions(self, planner_with_anticipation):
        """Gelernte Causal Chains mit hoher Confidence werden hinzugefuegt."""
        p = planner_with_anticipation
        p.anticipation.detect_patterns = AsyncMock(return_value=[
            {
                "type": "causal_chain",
                "confidence": 0.9,
                "chain_actions": [
                    {"action": "turn_on_radio", "args": {"room": "kueche"}},
                ],
            },
        ])
        plan = {
            "trigger": "person_arrived",
            "actions": [{"type": "set_light", "args": {"state": "on"}}],
            "message": "Test",
        }
        learned = await p._enrich_plan_from_patterns(plan, "person_arrived", {"person": {"name": "max"}})
        assert len(learned) == 1
        assert learned[0]["function"] == "turn_on_radio"
        assert learned[0]["type"] == "learned_pattern"

    @pytest.mark.asyncio
    async def test_enrich_skips_low_confidence(self, planner_with_anticipation):
        """Patterns mit niedriger Confidence werden ignoriert."""
        p = planner_with_anticipation
        p.anticipation.detect_patterns = AsyncMock(return_value=[
            {"type": "causal_chain", "confidence": 0.5, "chain_actions": [{"action": "play_music"}]},
        ])
        learned = await p._enrich_plan_from_patterns({"actions": [], "message": ""}, "test", {})
        assert len(learned) == 0

    @pytest.mark.asyncio
    async def test_enrich_max_5_actions(self, planner_with_anticipation):
        """Maximal 5 zusaetzliche Aktionen."""
        p = planner_with_anticipation
        p.anticipation.detect_patterns = AsyncMock(return_value=[
            {
                "type": "causal_chain",
                "confidence": 0.9,
                "chain_actions": [{"action": f"action_{i}"} for i in range(10)],
            },
        ])
        learned = await p._enrich_plan_from_patterns({"actions": [], "message": ""}, "test", {})
        assert len(learned) <= 5

    @pytest.mark.asyncio
    async def test_enrich_without_anticipation(self, ha_mock):
        """Ohne Anticipation-Engine werden keine Aktionen hinzugefuegt."""
        with patch("assistant.proactive_planner.yaml_config", {"proactive_planner": {"enabled": True}}):
            p = ProactiveSequencePlanner(ha=ha_mock, anticipation=None)
        learned = await p._enrich_plan_from_patterns({"actions": [], "message": ""}, "test", {})
        assert len(learned) == 0

    @pytest.mark.asyncio
    async def test_enrich_skips_non_causal_chain(self, planner_with_anticipation):
        """Nur causal_chain Patterns werden verwendet."""
        p = planner_with_anticipation
        p.anticipation.detect_patterns = AsyncMock(return_value=[
            {"type": "time_pattern", "confidence": 0.95, "chain_actions": [{"action": "test"}]},
        ])
        learned = await p._enrich_plan_from_patterns({"actions": [], "message": ""}, "test", {})
        assert len(learned) == 0
