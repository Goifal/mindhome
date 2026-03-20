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

    @pytest.mark.asyncio
    async def test_status_with_redis_multiple_pages(self, seasonal_with_redis):
        """get_status with multi-page scan loop."""
        seasonal_with_redis.redis.scan = AsyncMock(side_effect=[
            (5, [b"k1", b"k2"]),
            (0, [b"k3"]),
        ])
        status = await seasonal_with_redis.get_status()
        assert status["months_with_data"] == 3

    @pytest.mark.asyncio
    async def test_status_with_redis_scan_exception(self, seasonal_with_redis):
        """get_status when scan raises exception."""
        seasonal_with_redis.redis.scan = AsyncMock(side_effect=RuntimeError("scan failed"))
        status = await seasonal_with_redis.get_status()
        assert status["months_with_data"] == -1


# ============================================================
# _seasonal_loop Tests
# ============================================================

class TestSeasonalLoop:

    @pytest.mark.asyncio
    async def test_seasonal_loop_calls_check(self, seasonal_with_redis):
        """_seasonal_loop calls _check_seasonal_patterns and notifies."""
        call_count = 0

        async def mock_check():
            nonlocal call_count
            call_count += 1
            seasonal_with_redis._running = False  # stop after first iteration
            return "Seasonal insight message"

        callback = AsyncMock()
        seasonal_with_redis._notify_callback = callback
        seasonal_with_redis._running = True

        with patch.object(seasonal_with_redis, "_check_seasonal_patterns", side_effect=mock_check), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await seasonal_with_redis._seasonal_loop()

        assert call_count == 1
        callback.assert_called_once_with(
            "Seasonal insight message",
            urgency="low",
            event_type="seasonal_insight",
        )

    @pytest.mark.asyncio
    async def test_seasonal_loop_no_insight(self, seasonal_with_redis):
        """_seasonal_loop does not notify when no insight returned."""
        async def mock_check():
            seasonal_with_redis._running = False
            return None

        callback = AsyncMock()
        seasonal_with_redis._notify_callback = callback
        seasonal_with_redis._running = True

        with patch.object(seasonal_with_redis, "_check_seasonal_patterns", side_effect=mock_check), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await seasonal_with_redis._seasonal_loop()

        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_seasonal_loop_exception_continues(self, seasonal_with_redis):
        """_seasonal_loop catches exceptions and continues."""
        call_count = 0

        async def mock_check():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("boom")
            seasonal_with_redis._running = False
            return None

        seasonal_with_redis._running = True
        with patch.object(seasonal_with_redis, "_check_seasonal_patterns", side_effect=mock_check), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await seasonal_with_redis._seasonal_loop()

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_seasonal_loop_cancelled(self, seasonal_with_redis):
        """_seasonal_loop exits on CancelledError."""
        import asyncio

        async def mock_check():
            raise asyncio.CancelledError()

        seasonal_with_redis._running = True
        with patch.object(seasonal_with_redis, "_check_seasonal_patterns", side_effect=mock_check), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await seasonal_with_redis._seasonal_loop()
        # Should exit cleanly


# ============================================================
# _check_seasonal_patterns cooldown Tests
# ============================================================

class TestCheckSeasonalPatternsCooldown:

    @pytest.mark.asyncio
    async def test_returns_none_no_redis(self, seasonal):
        result = await seasonal._check_seasonal_patterns()
        assert result is None

    @pytest.mark.asyncio
    async def test_cooldown_active_returns_none(self, seasonal_with_redis):
        """When cooldown key exists, returns None."""
        seasonal_with_redis.redis.exists = AsyncMock(return_value=1)
        with patch("assistant.seasonal_insight.get_person_title", return_value="Sir"):
            result = await seasonal_with_redis._check_seasonal_patterns()
        assert result is None

    @pytest.mark.asyncio
    async def test_cooldown_exception_returns_none(self, seasonal_with_redis):
        """Exception checking cooldown returns None."""
        seasonal_with_redis.redis.exists = AsyncMock(side_effect=RuntimeError("redis down"))
        with patch("assistant.seasonal_insight.get_person_title", return_value="Sir"):
            result = await seasonal_with_redis._check_seasonal_patterns()
        assert result is None

    @pytest.mark.asyncio
    async def test_transition_insight_sets_cooldown(self, seasonal_with_redis):
        """When transition insight found, cooldown is set."""
        seasonal_with_redis.redis.exists = AsyncMock(return_value=0)
        with patch("assistant.seasonal_insight.get_person_title", return_value="Sir"), \
             patch.object(seasonal_with_redis, "_check_seasonal_transition",
                         new_callable=AsyncMock, return_value="Season change tip"):
            result = await seasonal_with_redis._check_seasonal_patterns()
        assert result == "Season change tip"
        seasonal_with_redis.redis.setex.assert_called()

    @pytest.mark.asyncio
    async def test_yoy_insight_sets_cooldown(self, seasonal_with_redis):
        """When YoY insight found (no transition), cooldown is set."""
        seasonal_with_redis.redis.exists = AsyncMock(return_value=0)
        with patch("assistant.seasonal_insight.get_person_title", return_value="Sir"), \
             patch.object(seasonal_with_redis, "_check_seasonal_transition",
                         new_callable=AsyncMock, return_value=None), \
             patch.object(seasonal_with_redis, "_check_year_over_year",
                         new_callable=AsyncMock, return_value="YoY insight"):
            result = await seasonal_with_redis._check_seasonal_patterns()
        assert result == "YoY insight"
        seasonal_with_redis.redis.setex.assert_called()

    @pytest.mark.asyncio
    async def test_no_insights_returns_none(self, seasonal_with_redis):
        """When no transition and no YoY insight, returns None."""
        seasonal_with_redis.redis.exists = AsyncMock(return_value=0)
        with patch("assistant.seasonal_insight.get_person_title", return_value="Sir"), \
             patch.object(seasonal_with_redis, "_check_seasonal_transition",
                         new_callable=AsyncMock, return_value=None), \
             patch.object(seasonal_with_redis, "_check_year_over_year",
                         new_callable=AsyncMock, return_value=None):
            result = await seasonal_with_redis._check_seasonal_patterns()
        assert result is None

    @pytest.mark.asyncio
    async def test_transition_cooldown_setex_exception(self, seasonal_with_redis):
        """When transition insight found but setex fails, insight is still returned."""
        seasonal_with_redis.redis.exists = AsyncMock(return_value=0)
        seasonal_with_redis.redis.setex = AsyncMock(side_effect=RuntimeError("redis down"))
        with patch("assistant.seasonal_insight.get_person_title", return_value="Sir"), \
             patch.object(seasonal_with_redis, "_check_seasonal_transition",
                         new_callable=AsyncMock, return_value="Season tip"):
            result = await seasonal_with_redis._check_seasonal_patterns()
        assert result == "Season tip"

    @pytest.mark.asyncio
    async def test_yoy_cooldown_setex_exception(self, seasonal_with_redis):
        """When YoY insight found but setex fails, insight is still returned."""
        seasonal_with_redis.redis.exists = AsyncMock(return_value=0)
        seasonal_with_redis.redis.setex = AsyncMock(side_effect=RuntimeError("redis down"))
        with patch("assistant.seasonal_insight.get_person_title", return_value="Sir"), \
             patch.object(seasonal_with_redis, "_check_seasonal_transition",
                         new_callable=AsyncMock, return_value=None), \
             patch.object(seasonal_with_redis, "_check_year_over_year",
                         new_callable=AsyncMock, return_value="YoY tip"):
            result = await seasonal_with_redis._check_seasonal_patterns()
        assert result == "YoY tip"


# ============================================================
# set_ollama / set_ha
# ============================================================

class TestSetters:

    def test_set_ollama(self, seasonal):
        mock_ollama = MagicMock()
        seasonal.set_ollama(mock_ollama)
        assert seasonal._ollama is mock_ollama

    def test_set_ha(self, seasonal):
        mock_ha = MagicMock()
        seasonal.set_ha(mock_ha)
        assert seasonal._ha is mock_ha


# ============================================================
# Initialize edge cases
# ============================================================

class TestInitializeEdgeCases:

    @pytest.mark.asyncio
    async def test_initialize_disabled_no_task(self, seasonal, redis_mock):
        """When disabled, no background task is created."""
        seasonal.enabled = False
        await seasonal.initialize(redis_client=redis_mock)
        assert seasonal.redis is redis_mock
        assert seasonal._task is None
        assert seasonal._running is False

    @pytest.mark.asyncio
    async def test_initialize_no_redis_no_task(self, seasonal):
        """Without Redis, no background task is created."""
        await seasonal.initialize(redis_client=None)
        assert seasonal.redis is None
        assert seasonal._task is None
        assert seasonal._running is False

    @pytest.mark.asyncio
    async def test_initialize_stores_notify_callback(self, seasonal, redis_mock):
        """Notify callback is stored on initialize."""
        cb = AsyncMock()
        with patch.object(seasonal, "_seasonal_loop", new_callable=AsyncMock):
            await seasonal.initialize(redis_client=redis_mock, notify_callback=cb)
        assert seasonal._notify_callback is cb

    @pytest.mark.asyncio
    async def test_stop_with_running_task(self, seasonal):
        """Stop cancels a running task properly."""
        import asyncio

        async def long_sleep():
            await asyncio.sleep(3600)

        seasonal._running = True
        seasonal._task = asyncio.create_task(long_sleep())
        await seasonal.stop()
        assert seasonal._running is False
        assert seasonal._task.cancelled()


# ============================================================
# Action Logging edge cases
# ============================================================

class TestActionLoggingEdgeCases:

    @pytest.mark.asyncio
    async def test_log_action_redis_exception(self, seasonal_with_redis):
        """Redis exception in log_seasonal_action is handled gracefully."""
        seasonal_with_redis.redis.hincrby = AsyncMock(side_effect=RuntimeError("redis error"))
        # Should not raise
        await seasonal_with_redis.log_seasonal_action("set_light", {"room": "kueche"})


# ============================================================
# _llm_seasonal_tip Tests
# ============================================================

class TestLlmSeasonalTip:

    @pytest.mark.asyncio
    async def test_llm_tip_disabled_in_config(self, seasonal_with_redis):
        """When llm_tips is False in config, returns None."""
        seasonal_with_redis._ollama = MagicMock()
        with patch("assistant.seasonal_insight.yaml_config", {
            "seasonal_insights": {"enabled": True, "llm_tips": False},
        }):
            result = await seasonal_with_redis._llm_seasonal_tip("sommer", "Sommer", "Sir")
        assert result is None

    @pytest.mark.asyncio
    async def test_llm_tip_no_ollama(self, seasonal_with_redis):
        """Without ollama client, returns None."""
        seasonal_with_redis._ollama = None
        with patch("assistant.seasonal_insight.yaml_config", {
            "seasonal_insights": {"enabled": True, "llm_tips": True},
        }):
            result = await seasonal_with_redis._llm_seasonal_tip("sommer", "Sommer", "Sir")
        assert result is None

    @pytest.mark.asyncio
    async def test_llm_tip_success(self, seasonal_with_redis):
        """LLM returns a valid tip string."""
        ollama = AsyncMock()
        ollama.chat = AsyncMock(return_value={
            "message": {"content": "Sir, der Sommer naht. Soll ich die Klimaanlage vorbereiten und Rollos anpassen?"},
        })
        seasonal_with_redis._ollama = ollama

        with patch("assistant.seasonal_insight.yaml_config", {
            "seasonal_insights": {"enabled": True, "llm_tips": True},
        }), patch("assistant.seasonal_insight.SeasonalInsightEngine._llm_seasonal_tip.__module__", create=True), \
             patch("assistant.config.settings") as mock_settings:
            mock_settings.model_smart = "test-model"
            result = await seasonal_with_redis._llm_seasonal_tip("sommer", "Sommer", "Sir")

        assert result is not None
        assert len(result) > 20

    @pytest.mark.asyncio
    async def test_llm_tip_strips_think_tags(self, seasonal_with_redis):
        """LLM response with <think> tags has them removed."""
        ollama = AsyncMock()
        ollama.chat = AsyncMock(return_value={
            "message": {"content": "<think>internal reasoning</think>Sir, der Winter kommt. Soll ich die Heizung hochfahren?"},
        })
        seasonal_with_redis._ollama = ollama

        with patch("assistant.seasonal_insight.yaml_config", {
            "seasonal_insights": {"enabled": True, "llm_tips": True},
        }), patch("assistant.config.settings") as mock_settings:
            mock_settings.model_smart = "test-model"
            result = await seasonal_with_redis._llm_seasonal_tip("winter", "Winter", "Sir")

        assert result is not None
        assert "<think>" not in result
        assert "Sir" in result

    @pytest.mark.asyncio
    async def test_llm_tip_too_short_response(self, seasonal_with_redis):
        """LLM response shorter than 20 chars returns None."""
        ollama = AsyncMock()
        ollama.chat = AsyncMock(return_value={
            "message": {"content": "Kurz."},
        })
        seasonal_with_redis._ollama = ollama

        with patch("assistant.seasonal_insight.yaml_config", {
            "seasonal_insights": {"enabled": True, "llm_tips": True},
        }), patch("assistant.config.settings") as mock_settings:
            mock_settings.model_smart = "test-model"
            result = await seasonal_with_redis._llm_seasonal_tip("sommer", "Sommer", "Sir")

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_tip_empty_response(self, seasonal_with_redis):
        """LLM response with empty content returns None."""
        ollama = AsyncMock()
        ollama.chat = AsyncMock(return_value={
            "message": {"content": ""},
        })
        seasonal_with_redis._ollama = ollama

        with patch("assistant.seasonal_insight.yaml_config", {
            "seasonal_insights": {"enabled": True, "llm_tips": True},
        }), patch("assistant.config.settings") as mock_settings:
            mock_settings.model_smart = "test-model"
            result = await seasonal_with_redis._llm_seasonal_tip("sommer", "Sommer", "Sir")

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_tip_timeout(self, seasonal_with_redis):
        """LLM timeout returns None."""
        import asyncio

        ollama = AsyncMock()
        ollama.chat = AsyncMock(side_effect=asyncio.TimeoutError())
        seasonal_with_redis._ollama = ollama

        with patch("assistant.seasonal_insight.yaml_config", {
            "seasonal_insights": {"enabled": True, "llm_tips": True},
        }), patch("assistant.config.settings") as mock_settings:
            mock_settings.model_smart = "test-model"
            result = await seasonal_with_redis._llm_seasonal_tip("sommer", "Sommer", "Sir")

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_tip_exception(self, seasonal_with_redis):
        """LLM exception returns None."""
        ollama = AsyncMock()
        ollama.chat = AsyncMock(side_effect=RuntimeError("LLM crashed"))
        seasonal_with_redis._ollama = ollama

        with patch("assistant.seasonal_insight.yaml_config", {
            "seasonal_insights": {"enabled": True, "llm_tips": True},
        }), patch("assistant.config.settings") as mock_settings:
            mock_settings.model_smart = "test-model"
            result = await seasonal_with_redis._llm_seasonal_tip("sommer", "Sommer", "Sir")

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_tip_with_ha_context(self, seasonal_with_redis):
        """LLM tip includes house context from HA states."""
        ollama = AsyncMock()
        ollama.chat = AsyncMock(return_value={
            "message": {"content": "Sir, die Heizung laeuft noch auf Wintermodus. Soll ich auf Fruehling umstellen?"},
        })
        seasonal_with_redis._ollama = ollama

        ha_mock = AsyncMock()
        ha_mock.get_states = AsyncMock(return_value=[
            {
                "entity_id": "climate.wohnzimmer",
                "state": "heat",
                "attributes": {"friendly_name": "Wohnzimmer Heizung", "temperature": 22},
            },
            {
                "entity_id": "cover.wohnzimmer",
                "state": "open",
                "attributes": {"friendly_name": "Wohnzimmer Rollladen", "current_position": 80},
            },
        ])
        seasonal_with_redis._ha = ha_mock

        with patch("assistant.seasonal_insight.yaml_config", {
            "seasonal_insights": {"enabled": True, "llm_tips": True},
        }), patch("assistant.config.settings") as mock_settings:
            mock_settings.model_smart = "test-model"
            result = await seasonal_with_redis._llm_seasonal_tip("fruehling", "Fruehling", "Sir")

        assert result is not None
        # Verify HA states were fetched
        ha_mock.get_states.assert_called_once()
        # Verify chat was called with house context in the user message
        call_args = ollama.chat.call_args
        user_msg = call_args[1]["messages"][1]["content"] if "messages" in call_args[1] else call_args[0][0][1]["content"]
        assert "Wohnzimmer Heizung" in user_msg or "Heizung" in user_msg

    @pytest.mark.asyncio
    async def test_llm_tip_ha_states_exception(self, seasonal_with_redis):
        """HA state fetch exception is handled gracefully, LLM still called."""
        ollama = AsyncMock()
        ollama.chat = AsyncMock(return_value={
            "message": {"content": "Sir, der Herbst naht. Heizprogramme sollten vorbereitet werden."},
        })
        seasonal_with_redis._ollama = ollama

        ha_mock = AsyncMock()
        ha_mock.get_states = AsyncMock(side_effect=RuntimeError("HA unavailable"))
        seasonal_with_redis._ha = ha_mock

        with patch("assistant.seasonal_insight.yaml_config", {
            "seasonal_insights": {"enabled": True, "llm_tips": True},
        }), patch("assistant.config.settings") as mock_settings:
            mock_settings.model_smart = "test-model"
            result = await seasonal_with_redis._llm_seasonal_tip("herbst", "Herbst", "Sir")

        # LLM is still called despite HA failure
        assert result is not None
        ollama.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_tip_ha_no_relevant_entities(self, seasonal_with_redis):
        """HA returns states but none are climate or cover entities."""
        ollama = AsyncMock()
        ollama.chat = AsyncMock(return_value={
            "message": {"content": "Sir, der Winter kommt bald. Soll ich vorsorglich die Heizung pruefen?"},
        })
        seasonal_with_redis._ollama = ollama

        ha_mock = AsyncMock()
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "light.wohnzimmer", "state": "on", "attributes": {"friendly_name": "Licht"}},
            {"entity_id": "sensor.temp", "state": "22", "attributes": {}},
        ])
        seasonal_with_redis._ha = ha_mock

        with patch("assistant.seasonal_insight.yaml_config", {
            "seasonal_insights": {"enabled": True, "llm_tips": True},
        }), patch("assistant.config.settings") as mock_settings:
            mock_settings.model_smart = "test-model"
            result = await seasonal_with_redis._llm_seasonal_tip("winter", "Winter", "Sir")

        assert result is not None

    @pytest.mark.asyncio
    async def test_llm_tip_none_content_in_response(self, seasonal_with_redis):
        """LLM response with None content returns None."""
        ollama = AsyncMock()
        ollama.chat = AsyncMock(return_value={
            "message": {"content": None},
        })
        seasonal_with_redis._ollama = ollama

        with patch("assistant.seasonal_insight.yaml_config", {
            "seasonal_insights": {"enabled": True, "llm_tips": True},
        }), patch("assistant.config.settings") as mock_settings:
            mock_settings.model_smart = "test-model"
            result = await seasonal_with_redis._llm_seasonal_tip("sommer", "Sommer", "Sir")

        assert result is None


# ============================================================
# Seasonal Transition with LLM integration
# ============================================================

class TestSeasonalTransitionWithLlm:

    @pytest.mark.asyncio
    async def test_transition_uses_llm_tip_when_available(self, seasonal_with_redis):
        """When LLM returns a tip, static fallback is skipped."""
        seasonal_with_redis.redis.exists = AsyncMock(return_value=0)

        with patch.object(seasonal_with_redis, "_llm_seasonal_tip",
                         new_callable=AsyncMock, return_value="LLM-generated tip for the season change."):
            result = await seasonal_with_redis._check_seasonal_transition("sommer", "Sir")

        assert result == "LLM-generated tip for the season change."
        seasonal_with_redis.redis.setex.assert_called()

    @pytest.mark.asyncio
    async def test_transition_falls_back_to_static_when_llm_fails(self, seasonal_with_redis):
        """When LLM returns None, static tip is used."""
        seasonal_with_redis.redis.exists = AsyncMock(return_value=0)

        with patch.object(seasonal_with_redis, "_llm_seasonal_tip",
                         new_callable=AsyncMock, return_value=None):
            result = await seasonal_with_redis._check_seasonal_transition("sommer", "Sir")

        assert result is not None
        assert "Sommer" in result

    @pytest.mark.asyncio
    async def test_transition_no_redis(self, seasonal):
        """Without Redis, returns None."""
        result = await seasonal._check_seasonal_transition("sommer", "Sir")
        assert result is None

    @pytest.mark.asyncio
    async def test_transition_flag_check_exception(self, seasonal_with_redis):
        """Exception checking transition flag returns None."""
        seasonal_with_redis.redis.exists = AsyncMock(side_effect=RuntimeError("redis error"))
        result = await seasonal_with_redis._check_seasonal_transition("sommer", "Sir")
        assert result is None

    @pytest.mark.asyncio
    async def test_transition_setex_exception_on_static_tip(self, seasonal_with_redis):
        """Setex exception after static tip doesn't prevent tip from being returned."""
        seasonal_with_redis.redis.exists = AsyncMock(return_value=0)
        seasonal_with_redis.redis.setex = AsyncMock(side_effect=RuntimeError("redis down"))

        with patch.object(seasonal_with_redis, "_llm_seasonal_tip",
                         new_callable=AsyncMock, return_value=None):
            result = await seasonal_with_redis._check_seasonal_transition("herbst", "Sir")

        assert result is not None
        assert "Herbst" in result

    @pytest.mark.asyncio
    async def test_transition_setex_exception_on_llm_tip(self, seasonal_with_redis):
        """Setex exception after LLM tip doesn't prevent tip from being returned."""
        seasonal_with_redis.redis.exists = AsyncMock(return_value=0)
        seasonal_with_redis.redis.setex = AsyncMock(side_effect=RuntimeError("redis down"))

        with patch.object(seasonal_with_redis, "_llm_seasonal_tip",
                         new_callable=AsyncMock, return_value="LLM tip about the upcoming season."):
            result = await seasonal_with_redis._check_seasonal_transition("winter", "Sir")

        assert result == "LLM tip about the upcoming season."


# ============================================================
# Year-over-Year edge cases
# ============================================================

class TestYearOverYearEdgeCases:

    @pytest.mark.asyncio
    async def test_yoy_no_redis(self, seasonal):
        """Without Redis, returns None."""
        result = await seasonal._check_year_over_year(6, "Sir")
        assert result is None

    @pytest.mark.asyncio
    async def test_yoy_redis_exception(self, seasonal_with_redis):
        """Redis exception in hgetall is handled gracefully."""
        seasonal_with_redis.redis.hgetall = AsyncMock(side_effect=RuntimeError("redis down"))
        result = await seasonal_with_redis._check_year_over_year(6, "Sir")
        assert result is None

    @pytest.mark.asyncio
    async def test_yoy_no_set_climate_key(self, seasonal_with_redis):
        """When both years have data but no set_climate key, returns None."""
        seasonal_with_redis.redis.hgetall = AsyncMock(side_effect=[
            {b"set_light": b"15"},
            {b"set_light": b"10"},
        ])
        result = await seasonal_with_redis._check_year_over_year(6, "Sir")
        assert result is None

    @pytest.mark.asyncio
    async def test_yoy_current_empty_last_year_has_data(self, seasonal_with_redis):
        """When current month has no data but last year does."""
        seasonal_with_redis.redis.hgetall = AsyncMock(side_effect=[
            {},  # Current month - no data
            {b"set_climate": b"25"},  # Last year - had activity
        ])
        result = await seasonal_with_redis._check_year_over_year(6, "Sir")
        # heat_current=0 < heat_last(25)*0.3=7.5 and heat_last>10
        assert result is not None
        assert "haeufiger" in result

    @pytest.mark.asyncio
    async def test_yoy_low_last_year_not_significant(self, seasonal_with_redis):
        """When last year had few climate actions (<=10), no insight about less usage."""
        seasonal_with_redis.redis.hgetall = AsyncMock(side_effect=[
            {b"set_climate": b"1"},
            {b"set_climate": b"8"},  # <=10, threshold not met
        ])
        result = await seasonal_with_redis._check_year_over_year(6, "Sir")
        assert result is None

    @pytest.mark.asyncio
    async def test_yoy_more_heating_low_baseline(self, seasonal_with_redis):
        """When current is more than double but last year had <=5, no insight."""
        seasonal_with_redis.redis.hgetall = AsyncMock(side_effect=[
            {b"set_climate": b"12"},
            {b"set_climate": b"4"},  # <=5, threshold not met for 'double' check
        ])
        result = await seasonal_with_redis._check_year_over_year(6, "Sir")
        assert result is None

    @pytest.mark.asyncio
    async def test_yoy_string_data_from_redis(self, seasonal_with_redis):
        """Redis returns string (not bytes) data - should still work."""
        seasonal_with_redis.redis.hgetall = AsyncMock(side_effect=[
            {"set_climate": "2"},
            {"set_climate": "30"},
        ])
        result = await seasonal_with_redis._check_year_over_year(6, "Sir")
        assert result is not None
        assert "haeufiger" in result


# ============================================================
# Config edge cases
# ============================================================

class TestConfigEdgeCases:

    def test_custom_check_interval(self):
        with patch("assistant.seasonal_insight.yaml_config", {
            "seasonal_insights": {"enabled": True, "check_interval_hours": 12},
        }):
            engine = SeasonalInsightEngine()
        assert engine.check_interval == 12 * 3600

    def test_custom_min_history_months(self):
        with patch("assistant.seasonal_insight.yaml_config", {
            "seasonal_insights": {"enabled": True, "min_history_months": 6},
        }):
            engine = SeasonalInsightEngine()
        assert engine.min_history_months == 6

    def test_disabled_engine(self):
        with patch("assistant.seasonal_insight.yaml_config", {
            "seasonal_insights": {"enabled": False},
        }):
            engine = SeasonalInsightEngine()
        assert engine.enabled is False

    def test_missing_config_uses_defaults(self):
        with patch("assistant.seasonal_insight.yaml_config", {}):
            engine = SeasonalInsightEngine()
        assert engine.enabled is True
        assert engine.check_interval == 24 * 3600
        assert engine.min_history_months == 2
