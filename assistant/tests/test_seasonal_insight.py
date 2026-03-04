"""
Tests fuer SeasonalInsightEngine — Saisonale Muster-Erkennung.

Testet:
- Saisonale Zuordnung
- Saisonwechsel-Erkennung
- Vorjahres-Vergleich
- Action-Logging
- Cooldown-Logik
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from assistant.seasonal_insight import SeasonalInsightEngine, _SEASONS, _SEASON_LABELS


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def seasonal():
    with patch("assistant.seasonal_insight.yaml_config", {"seasonal_insights": {"enabled": True}}):
        engine = SeasonalInsightEngine()
    return engine


@pytest.fixture
def seasonal_with_redis(seasonal, redis_mock):
    seasonal.redis = redis_mock
    return seasonal


# ============================================================
# Saisonale Zuordnung
# ============================================================

class TestSeasonMapping:

    def test_winter_months(self):
        assert _SEASONS[12] == "winter"
        assert _SEASONS[1] == "winter"
        assert _SEASONS[2] == "winter"

    def test_spring_months(self):
        assert _SEASONS[3] == "fruehling"
        assert _SEASONS[4] == "fruehling"
        assert _SEASONS[5] == "fruehling"

    def test_summer_months(self):
        assert _SEASONS[6] == "sommer"
        assert _SEASONS[7] == "sommer"
        assert _SEASONS[8] == "sommer"

    def test_autumn_months(self):
        assert _SEASONS[9] == "herbst"
        assert _SEASONS[10] == "herbst"
        assert _SEASONS[11] == "herbst"

    def test_season_labels(self):
        assert _SEASON_LABELS["winter"] == "Winter"
        assert _SEASON_LABELS["sommer"] == "Sommer"


# ============================================================
# Initialisierung
# ============================================================

class TestSeasonalInit:

    def test_default_config(self, seasonal):
        assert seasonal.enabled is True
        assert seasonal.check_interval == 24 * 3600

    @pytest.mark.asyncio
    async def test_initialize_starts_loop(self, seasonal, redis_mock):
        """initialize mit Redis startet den Loop-Task."""
        with patch.object(seasonal, "_seasonal_loop", new_callable=AsyncMock):
            await seasonal.initialize(redis_client=redis_mock)
        assert seasonal.redis is redis_mock
        assert seasonal._running is True

    @pytest.mark.asyncio
    async def test_stop(self, seasonal):
        import asyncio
        seasonal._running = True
        async def noop(): pass
        task = asyncio.ensure_future(noop())
        await task
        seasonal._task = task
        await seasonal.stop()
        assert seasonal._running is False


# ============================================================
# Action Logging
# ============================================================

class TestActionLogging:

    @pytest.mark.asyncio
    async def test_log_action(self, seasonal_with_redis):
        await seasonal_with_redis.log_seasonal_action("set_climate", {"temp": 22})
        seasonal_with_redis.redis.hincrby.assert_called_once()
        seasonal_with_redis.redis.expire.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_action_no_redis(self, seasonal):
        # Sollte nicht crashen
        await seasonal.log_seasonal_action("set_light", {})

    @pytest.mark.asyncio
    async def test_log_action_disabled(self, seasonal_with_redis):
        seasonal_with_redis.enabled = False
        await seasonal_with_redis.log_seasonal_action("set_light", {})
        seasonal_with_redis.redis.hincrby.assert_not_called()


# ============================================================
# Seasonal Transition
# ============================================================

class TestSeasonalTransition:

    @pytest.mark.asyncio
    async def test_transition_detected(self, seasonal_with_redis):
        seasonal_with_redis.redis.exists = AsyncMock(return_value=0)  # Noch nicht gemeldet

        with patch("assistant.seasonal_insight.get_person_title", return_value="Sir"):
            result = await seasonal_with_redis._check_seasonal_transition("sommer", "Sir")

        assert result is not None
        assert "Sommer" in result
        seasonal_with_redis.redis.setex.assert_called()

    @pytest.mark.asyncio
    async def test_transition_already_notified(self, seasonal_with_redis):
        seasonal_with_redis.redis.exists = AsyncMock(return_value=1)  # Schon gemeldet

        result = await seasonal_with_redis._check_seasonal_transition("sommer", "Sir")
        assert result is None

    @pytest.mark.asyncio
    async def test_all_seasons_have_tips(self, seasonal_with_redis):
        seasonal_with_redis.redis.exists = AsyncMock(return_value=0)

        for season in ["fruehling", "sommer", "herbst", "winter"]:
            result = await seasonal_with_redis._check_seasonal_transition(season, "Sir")
            assert result is not None, f"Kein Tipp fuer {season}"


# ============================================================
# Year-over-Year Vergleich
# ============================================================

class TestYearOverYear:

    @pytest.mark.asyncio
    async def test_much_less_heating_than_last_year(self, seasonal_with_redis):
        seasonal_with_redis.redis.hgetall = AsyncMock(side_effect=[
            {b"set_climate": b"2"},   # Dieses Jahr: wenig
            {b"set_climate": b"30"},  # Letztes Jahr: viel
        ])

        with patch("assistant.seasonal_insight.get_person_title", return_value="Sir"):
            result = await seasonal_with_redis._check_year_over_year(6, "Sir")

        assert result is not None
        assert "haeufiger" in result

    @pytest.mark.asyncio
    async def test_much_more_heating_than_last_year(self, seasonal_with_redis):
        seasonal_with_redis.redis.hgetall = AsyncMock(side_effect=[
            {b"set_climate": b"50"},  # Dieses Jahr: viel
            {b"set_climate": b"10"},  # Letztes Jahr: wenig
        ])

        with patch("assistant.seasonal_insight.get_person_title", return_value="Sir"):
            result = await seasonal_with_redis._check_year_over_year(6, "Sir")

        assert result is not None
        assert "doppelt" in result

    @pytest.mark.asyncio
    async def test_no_last_year_data(self, seasonal_with_redis):
        seasonal_with_redis.redis.hgetall = AsyncMock(side_effect=[
            {b"set_climate": b"20"},
            {},  # Keine Vorjahres-Daten
        ])

        result = await seasonal_with_redis._check_year_over_year(6, "Sir")
        assert result is None

    @pytest.mark.asyncio
    async def test_similar_heating(self, seasonal_with_redis):
        seasonal_with_redis.redis.hgetall = AsyncMock(side_effect=[
            {b"set_climate": b"15"},
            {b"set_climate": b"18"},
        ])

        result = await seasonal_with_redis._check_year_over_year(6, "Sir")
        assert result is None


# ============================================================
# Status
# ============================================================

class TestSeasonalStatus:

    @pytest.mark.asyncio
    async def test_status_without_redis(self, seasonal):
        status = await seasonal.get_status()
        assert status["enabled"] is True
        assert status["running"] is False

    @pytest.mark.asyncio
    async def test_status_with_redis(self, seasonal_with_redis):
        seasonal_with_redis.redis.scan = AsyncMock(return_value=(0, [b"k1", b"k2", b"k3"]))
        status = await seasonal_with_redis.get_status()
        assert status["months_with_data"] == 3
