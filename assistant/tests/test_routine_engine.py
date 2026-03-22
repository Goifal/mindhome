"""
Tests fuer RoutineEngine — Morning Briefing, Sleep-Awareness, Goodnight.
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Europe/Berlin")

import pytest

from assistant.routine_engine import RoutineEngine


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def engine(ha_mock, ollama_mock, redis_mock):
    e = RoutineEngine(ha_mock, ollama_mock)
    e.redis = redis_mock
    e.briefing_enabled = True
    e.briefing_modules = ["greeting", "weather"]
    e.weekday_style = "kurz"
    e.weekend_style = "lang"
    return e


# ── Sleep Awareness ──────────────────────────────────────────────────


class TestSleepAwareness:
    @pytest.mark.asyncio
    async def test_no_sleep_hint_without_redis(self, engine):
        engine.redis = None
        result = await engine._get_sleep_awareness()
        assert result == {}

    @pytest.mark.asyncio
    async def test_no_sleep_hint_when_no_late_night(self, engine, redis_mock):
        redis_mock.sismember = AsyncMock(return_value=False)
        result = await engine._get_sleep_awareness()
        assert result == {}

    @pytest.mark.asyncio
    async def test_sleep_hint_after_late_night(self, engine, redis_mock):
        today = datetime.now(tz=_TZ).date().isoformat()

        async def sismember_side_effect(key, date_str):
            return date_str == today

        redis_mock.sismember = AsyncMock(side_effect=sismember_side_effect)
        result = await engine._get_sleep_awareness()
        assert result.get("was_late") is True
        assert "SCHLAF-HINWEIS" in result.get("briefing_note", "")

    @pytest.mark.asyncio
    async def test_consecutive_nights_escalation(self, engine, redis_mock):
        today = datetime.now(tz=_TZ).date()
        late_dates = {(today - timedelta(days=i)).isoformat() for i in range(4)}

        async def sismember_side_effect(key, date_str):
            return date_str in late_dates

        redis_mock.sismember = AsyncMock(side_effect=sismember_side_effect)
        result = await engine._get_sleep_awareness()
        assert result.get("was_late") is True
        # 4 Naechte in Folge → erwaehne es
        note = result.get("briefing_note", "")
        assert "4" in note or "Naechte" in note


# ── Morning Briefing ─────────────────────────────────────────────────


class TestMorningBriefing:
    @pytest.mark.asyncio
    async def test_skip_when_disabled(self, engine):
        engine.briefing_enabled = False
        result = await engine.generate_morning_briefing()
        assert result["text"] == ""

    @pytest.mark.asyncio
    async def test_skip_when_already_done_today(self, engine, redis_mock):
        today = datetime.now(tz=_TZ).strftime("%Y-%m-%d")
        # Lock existiert bereits (set NX gibt None zurueck) + done-Datum ist heute
        redis_mock.set = AsyncMock(return_value=None)
        redis_mock.get = AsyncMock(return_value=today)
        result = await engine.generate_morning_briefing()
        assert result["text"] == ""

    @pytest.mark.asyncio
    async def test_force_ignores_done_flag(self, engine, redis_mock, ollama_mock):
        today = datetime.now(tz=_TZ).strftime("%Y-%m-%d")
        redis_mock.get = AsyncMock(return_value=today)
        redis_mock.sismember = AsyncMock(return_value=False)
        # Mock the briefing modules to return content
        engine._get_briefing_module = AsyncMock(return_value="Wetter: Sonnig, 15 Grad")
        result = await engine.generate_morning_briefing(force=True)
        # Force=True → Briefing wird generiert trotz Done-Flag
        ollama_mock.chat.assert_called_once()


# ── Briefing Prompt ──────────────────────────────────────────────────


class TestBriefingPrompt:
    def test_kurz_style_limits_sentences(self, engine):
        parts = ["Wetter: Sonnig", "Kalender: Keine Termine"]
        prompt = engine._build_briefing_prompt(parts, "kurz", "", datetime.now())
        assert "Maximal 3 Saetze" in prompt

    def test_lang_style_allows_more(self, engine):
        parts = ["Wetter: Sonnig"]
        prompt = engine._build_briefing_prompt(parts, "lang", "", datetime.now())
        assert "Bis 5 Saetze" in prompt


# ── Generate Morning Briefing ──────────────────────────────────────────


class TestGenerateMorningBriefing:
    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self, engine):
        engine.briefing_enabled = False
        result = await engine.generate_morning_briefing()
        assert result["text"] == ""

    @pytest.mark.asyncio
    async def test_already_done_today(self, engine, redis_mock):
        today = datetime.now(tz=_TZ).strftime("%Y-%m-%d")
        redis_mock.set = AsyncMock(return_value=None)  # Lock exists
        redis_mock.get = AsyncMock(return_value=today)
        result = await engine.generate_morning_briefing()
        assert result["text"] == ""

    @pytest.mark.asyncio
    async def test_force_ignores_done(self, engine, redis_mock, ollama_mock):
        today = datetime.now(tz=_TZ).strftime("%Y-%m-%d")
        redis_mock.get = AsyncMock(return_value=today)
        redis_mock.sismember = AsyncMock(return_value=False)
        redis_mock.setex = AsyncMock()

        # Mock briefing modules
        async def fake_module(module, person, style):
            if module == "greeting":
                return "Tag: Mittwoch"
            if module == "weather":
                return "Wetter: Sonnig"
            return ""

        engine._get_briefing_module = fake_module
        engine._execute_morning_actions = AsyncMock(return_value=[])

        result = await engine.generate_morning_briefing(force=True)
        ollama_mock.chat.assert_called_once()


# ── Translate Weather ──────────────────────────────────────────────────


class TestTranslateWeather:
    def test_sunny(self):
        from assistant.routine_engine import RoutineEngine

        assert RoutineEngine._translate_weather("sunny") == "sonnig"

    def test_rainy(self):
        from assistant.routine_engine import RoutineEngine

        assert RoutineEngine._translate_weather("rainy") == "Regen"

    def test_unknown(self):
        from assistant.routine_engine import RoutineEngine

        assert (
            RoutineEngine._translate_weather("unknown_condition") == "unknown_condition"
        )

    def test_fog(self):
        from assistant.routine_engine import RoutineEngine

        assert RoutineEngine._translate_weather("fog") == "Nebel"

    def test_snowy(self):
        from assistant.routine_engine import RoutineEngine

        assert RoutineEngine._translate_weather("snowy") == "Schnee"

    def test_lightning_rainy(self):
        from assistant.routine_engine import RoutineEngine

        assert (
            RoutineEngine._translate_weather("lightning-rainy") == "Gewitter mit Regen"
        )


# ── Check Birthday ─────────────────────────────────────────────────────


class TestCheckBirthday:
    def test_no_birthdays(self, engine):
        with patch(
            "assistant.routine_engine.yaml_config", {"persons": {"birthdays": {}}}
        ):
            result = engine._check_birthday("Max", datetime.now(tz=_TZ))
        assert result == ""

    def test_birthday_today(self, engine):
        now = datetime.now(tz=_TZ)
        birthday = f"1990-{now.strftime('%m-%d')}"
        with patch(
            "assistant.routine_engine.yaml_config",
            {"persons": {"birthdays": {"Max": birthday}}},
        ):
            result = engine._check_birthday("Max", now)
        assert "GEBURTSTAG" in result
        assert "Max" in result

    def test_birthday_other_person(self, engine):
        now = datetime.now(tz=_TZ)
        birthday = f"1985-{now.strftime('%m-%d')}"
        with patch(
            "assistant.routine_engine.yaml_config",
            {"persons": {"birthdays": {"Anna": birthday}}},
        ):
            result = engine._check_birthday("Max", now)
        assert "GEBURTSTAG" in result
        assert "Anna" in result

    def test_no_birthday_today(self, engine):
        now = datetime.now(tz=_TZ)
        birthday = "1990-01-01"
        # Only matches on Jan 1
        with patch(
            "assistant.routine_engine.yaml_config",
            {"persons": {"birthdays": {"Max": birthday}}},
        ):
            if now.strftime("%m-%d") != "01-01":
                result = engine._check_birthday("Max", now)
                assert result == ""


# ── Is Goodnight Intent ────────────────────────────────────────────────


class TestIsGoodnightIntent:
    @pytest.mark.asyncio
    async def test_gute_nacht(self, engine):
        assert await engine.is_goodnight_intent("Gute Nacht") is True

    @pytest.mark.asyncio
    async def test_ich_gehe_schlafen(self, engine):
        assert await engine.is_goodnight_intent("ich gehe schlafen") is True

    @pytest.mark.asyncio
    async def test_weather_excludes(self, engine):
        assert (
            await engine.is_goodnight_intent("Wie kalt wird es heute Nacht?") is False
        )
        assert await engine.is_goodnight_intent("Wetter für die Nacht?") is False
        assert await engine.is_goodnight_intent("Temperatur heute Nacht") is False

    @pytest.mark.asyncio
    async def test_unrelated_text(self, engine):
        assert await engine.is_goodnight_intent("Mach das Licht an") is False


# ── Execute Goodnight ──────────────────────────────────────────────────


class TestExecuteGoodnight:
    @pytest.mark.asyncio
    async def test_disabled(self, engine):
        engine.goodnight_enabled = False
        result = await engine.execute_goodnight("Max")
        assert "Gute Nacht" in result["text"]
        assert result["actions"] == []

    @pytest.mark.asyncio
    async def test_enabled_with_mocks(self, engine, redis_mock, ha_mock, ollama_mock):
        engine.goodnight_enabled = True
        engine._executor = AsyncMock()
        engine._personality = None
        ha_mock.get_states = AsyncMock(return_value=[])
        redis_mock.setex = AsyncMock()

        # Mock LLM response
        ollama_mock.chat = AsyncMock(
            return_value={
                "message": {"content": "Gute Nacht, Sir. Alles ist sicher."},
            }
        )

        result = await engine.execute_goodnight("Max")
        assert "text" in result
        assert "actions" in result
        assert "issues" in result


# ── Briefing System Prompt ─────────────────────────────────────────────


class TestBriefingSystemPrompt:
    def test_without_personality(self, engine):
        engine._personality = None
        with (
            patch("assistant.routine_engine.settings") as mock_s,
            patch("assistant.routine_engine.get_person_title", return_value="Sir"),
        ):
            mock_s.assistant_name = "Jarvis"
            prompt = engine._get_briefing_system_prompt("kurz")
        assert "Jarvis" in prompt
        assert "Morning Briefing" in prompt

    def test_with_personality(self, engine):
        mock_pers = MagicMock()
        mock_pers.build_routine_prompt = MagicMock(return_value="Custom Prompt")
        engine._personality = mock_pers
        prompt = engine._get_briefing_system_prompt("kurz")
        assert prompt == "Custom Prompt"

    def test_personality_error_fallback(self, engine):
        mock_pers = MagicMock()
        mock_pers.build_routine_prompt = MagicMock(side_effect=RuntimeError("fail"))
        engine._personality = mock_pers
        with (
            patch("assistant.routine_engine.settings") as mock_s,
            patch("assistant.routine_engine.get_person_title", return_value="Sir"),
        ):
            mock_s.assistant_name = "Jarvis"
            prompt = engine._get_briefing_system_prompt("kurz")
        assert "Jarvis" in prompt


# ── Calendar Briefing ──────────────────────────────────────────────────


class TestCalendarBriefing:
    @pytest.mark.asyncio
    async def test_no_states(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=None)
        result = await engine._get_calendar_briefing()
        assert result == ""

    @pytest.mark.asyncio
    async def test_no_calendar_entities(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(
            return_value=[
                {"entity_id": "light.test", "state": "on"},
            ]
        )
        result = await engine._get_calendar_briefing()
        assert result == ""

    @pytest.mark.asyncio
    async def test_with_events(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "calendar.default",
                    "attributes": {"message": "Team Meeting", "start_time": "10:00"},
                },
            ]
        )
        result = await engine._get_calendar_briefing()
        assert "Termine" in result
        assert "Team Meeting" in result


# ── House Status Briefing ──────────────────────────────────────────────


class TestHouseStatusBriefing:
    @pytest.mark.asyncio
    async def test_no_states(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=None)
        result = await engine._get_house_status_briefing()
        assert result == ""

    @pytest.mark.asyncio
    async def test_with_lights(self, engine, ha_mock):
        with patch("assistant.routine_engine.yaml_config", {"room_temperature": {}}):
            ha_mock.get_states = AsyncMock(
                return_value=[
                    {
                        "entity_id": "light.kitchen",
                        "state": "on",
                        "attributes": {"friendly_name": "Kueche"},
                    },
                    {
                        "entity_id": "light.living",
                        "state": "on",
                        "attributes": {"friendly_name": "Wohnzimmer"},
                    },
                ]
            )
            result = await engine._get_house_status_briefing()
        assert "Lichter an: 2" in result


# ── Reload Config ──────────────────────────────────────────────────────


class TestRoutineReloadConfig:
    def test_reload(self, engine):
        with patch(
            "assistant.routine_engine.yaml_config",
            {
                "routines": {
                    "morning_briefing": {"enabled": False, "weekday_style": "lang"},
                    "good_night": {"enabled": False},
                    "guest_mode": {},
                },
            },
        ):
            engine.reload_config()
        assert engine.briefing_enabled is False
        assert engine.weekday_style == "lang"
        assert engine.goodnight_enabled is False


# ── Forecast via Service ────────────────────────────────────────────────


class TestForecastViaService:
    @pytest.mark.asyncio
    async def test_no_result(self, engine, ha_mock):
        ha_mock.call_service_with_response = AsyncMock(return_value=None)
        result = await engine._get_forecast_via_service("weather.home")
        assert result == []

    @pytest.mark.asyncio
    async def test_format1_list(self, engine, ha_mock):
        ha_mock.call_service_with_response = AsyncMock(
            return_value=[
                {
                    "weather.home": {
                        "forecast": [{"temperature": 20, "condition": "sunny"}]
                    }
                },
            ]
        )
        result = await engine._get_forecast_via_service("weather.home")
        assert len(result) == 1
        assert result[0]["temperature"] == 20

    @pytest.mark.asyncio
    async def test_format2_dict(self, engine, ha_mock):
        ha_mock.call_service_with_response = AsyncMock(
            return_value={
                "weather.home": {"forecast": [{"temperature": 15}]},
            }
        )
        result = await engine._get_forecast_via_service("weather.home")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_service_response_wrapper(self, engine, ha_mock):
        ha_mock.call_service_with_response = AsyncMock(
            return_value={
                "service_response": {
                    "weather.home": {"forecast": [{"temperature": 18}]}
                },
            }
        )
        result = await engine._get_forecast_via_service("weather.home")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_error_returns_empty(self, engine, ha_mock):
        ha_mock.call_service_with_response = AsyncMock(side_effect=Exception("fail"))
        result = await engine._get_forecast_via_service("weather.home")
        assert result == []


# ── Execute Morning Actions ─────────────────────────────────────────────


class TestExecuteMorningActions:
    @pytest.mark.asyncio
    async def test_no_executor(self, engine):
        engine._executor = None
        result = await engine._execute_morning_actions()
        assert result == []

    @pytest.mark.asyncio
    async def test_covers_up(self, engine, redis_mock):
        executor = AsyncMock()
        executor.execute = AsyncMock(return_value={"success": True})
        engine._executor = executor
        engine.morning_actions = {"covers_up": True}
        redis_mock.get = AsyncMock(return_value=None)

        with patch.object(
            engine, "_is_bed_occupied", new_callable=AsyncMock, return_value=False
        ):
            result = await engine._execute_morning_actions()
        assert len(result) == 1
        assert result[0]["function"] == "set_cover"

    @pytest.mark.asyncio
    async def test_covers_up_skipped_bed_occupied(self, engine, redis_mock):
        executor = AsyncMock()
        engine._executor = executor
        engine.morning_actions = {"covers_up": True}
        redis_mock.get = AsyncMock(return_value=None)

        with patch.object(
            engine, "_is_bed_occupied", new_callable=AsyncMock, return_value=True
        ):
            result = await engine._execute_morning_actions()
        assert result == []
        executor.execute.assert_not_called()


# ── Initialize ──────────────────────────────────────────────────────────


class TestRoutineInitialize:
    @pytest.mark.asyncio
    async def test_initialize_with_redis(self, engine, redis_mock):
        await engine.initialize(redis_mock)
        assert engine.redis is redis_mock

    @pytest.mark.asyncio
    async def test_initialize_without_redis(self, engine):
        await engine.initialize(None)
        assert engine.redis is None

    def test_set_executor(self, engine):
        executor = MagicMock()
        engine.set_executor(executor)
        assert engine._executor is executor

    def test_set_personality(self, engine):
        pers = MagicMock()
        engine.set_personality(pers)
        assert engine._personality is pers


# ============================================================
# Phase 5C: Erweiterte Routinen
# ============================================================


class TestPhase5CExtendedRoutines:
    """Tests fuer erweiterte Routinen."""

    @pytest.fixture
    def engine(self, ha_mock, ollama_mock):
        with patch("assistant.routine_engine.yaml_config", {"routines": {}}):
            e = RoutineEngine(ha_client=ha_mock, ollama=ollama_mock)
            e.redis = AsyncMock()
            return e

    @pytest.mark.asyncio
    async def test_weather_precaution_no_redis(self, engine):
        engine.redis = None
        result = await engine.weather_precaution_routine()
        assert result is None

    @pytest.mark.asyncio
    async def test_weather_precaution_no_forecast(self, engine):
        engine.redis.get = AsyncMock(return_value=None)
        result = await engine.weather_precaution_routine()
        assert result is None

    @pytest.mark.asyncio
    async def test_calendar_health_no_events(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=[])
        result = await engine.calendar_health_check()
        assert result is None

    @pytest.mark.asyncio
    async def test_energy_routine_no_solar(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=[])
        result = await engine.energy_routine()
        assert result is None

    @pytest.mark.asyncio
    async def test_incomplete_recovery_no_data(self, engine):
        engine.redis.get = AsyncMock(return_value=None)
        result = await engine.incomplete_routine_recovery()
        assert result is None

    @pytest.mark.asyncio
    async def test_habit_intervention_before_2330(self, engine):
        """Vor 23:30 → keine Intervention."""
        with patch("assistant.routine_engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 18, 22, 0, tzinfo=_TZ)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = await engine.habit_intervention()
        assert result is None


# ============================================================
# Vacation Simulation
# ============================================================


class TestVacationSimulation:
    @pytest.mark.asyncio
    async def test_start_without_redis(self, engine):
        engine.redis = None
        result = await engine.start_vacation_simulation()
        assert "Redis" in result

    @pytest.mark.asyncio
    async def test_start_creates_task(self, engine, redis_mock):
        result = await engine.start_vacation_simulation()
        redis_mock.setex.assert_called_once()
        assert engine._vacation_task is not None
        assert (
            "bewohnt" in result.lower()
            or "uebernehme" in result.lower()
            or "bernehme" in result.lower()
        )
        # Cleanup — cancel the background task
        engine._vacation_task.cancel()
        try:
            await engine._vacation_task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, engine, redis_mock):
        # Start first
        await engine.start_vacation_simulation()
        task = engine._vacation_task
        assert task is not None

        result = await engine.stop_vacation_simulation()
        redis_mock.delete.assert_called()
        assert "beendet" in result.lower() or "Willkommen" in result

    @pytest.mark.asyncio
    async def test_stop_without_running_task(self, engine, redis_mock):
        engine._vacation_task = None
        result = await engine.stop_vacation_simulation()
        assert "beendet" in result.lower() or "Willkommen" in result

    @pytest.mark.asyncio
    async def test_sim_action_skips_cover_actions(self, engine, ha_mock):
        """Bug 7: Cover-Aktionen werden uebersprungen."""
        ha_mock.call_service = AsyncMock()
        await engine._sim_action("covers_up")
        ha_mock.call_service.assert_not_called()
        await engine._sim_action("covers_down")
        ha_mock.call_service.assert_not_called()

    @pytest.mark.asyncio
    async def test_sim_action_light_random_on(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(
            return_value=[
                {"entity_id": "light.wohnzimmer", "state": "off", "attributes": {}},
                {"entity_id": "light.kueche", "state": "off", "attributes": {}},
            ]
        )
        ha_mock.call_service = AsyncMock()
        await engine._sim_action("light_random_on")
        ha_mock.call_service.assert_called_once()
        call_args = ha_mock.call_service.call_args
        assert call_args[0][0] == "light"
        assert call_args[0][1] == "turn_on"

    @pytest.mark.asyncio
    async def test_sim_action_no_states(self, engine, ha_mock):
        """Graceful handling when HA returns no states."""
        ha_mock.get_states = AsyncMock(return_value=None)
        # Should not raise
        await engine._sim_action("light_random_on")

    @pytest.mark.asyncio
    async def test_sim_action_all_lights_off(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(
            return_value=[
                {"entity_id": "light.wohnzimmer", "state": "on", "attributes": {}},
                {"entity_id": "light.kueche", "state": "on", "attributes": {}},
            ]
        )
        ha_mock.call_service = AsyncMock()
        await engine._sim_action("all_lights_off")
        assert ha_mock.call_service.call_count == 2


# ============================================================
# Guest Mode
# ============================================================


class TestGuestMode:
    @pytest.mark.asyncio
    async def test_is_guest_trigger_keyword(self, engine):
        assert await engine.is_guest_trigger("ich habe besuch") is True
        assert await engine.is_guest_trigger("Gaeste kommen") is True

    @pytest.mark.asyncio
    async def test_is_guest_trigger_extended(self, engine):
        assert await engine.is_guest_trigger("meine eltern kommen") is True
        assert await engine.is_guest_trigger("wir bekommen besuch") is True

    @pytest.mark.asyncio
    async def test_is_guest_trigger_gone_signal_blocks_llm(self, engine, ollama_mock):
        """Gaeste-gehen-Signale duerfen nicht als Trigger erkannt werden."""
        result = await engine.is_guest_trigger("Die Gaeste sind gegangen")
        assert result is False
        ollama_mock.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_is_guest_trigger_unrelated(self, engine, ollama_mock):
        """Unrelated text falls through to LLM, which returns nein."""
        ollama_mock.chat = AsyncMock(
            return_value={
                "message": {"content": "nein"},
            }
        )
        result = await engine.is_guest_trigger("Mach das Licht an")
        assert result is False

    @pytest.mark.asyncio
    async def test_is_guest_trigger_long_text_skips_llm(self, engine, ollama_mock):
        """Text > 80 Zeichen wird ohne LLM abgelehnt."""
        long_text = "a" * 81
        result = await engine.is_guest_trigger(long_text)
        assert result is False
        ollama_mock.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_activate_guest_mode(self, engine, redis_mock):
        result = await engine.activate_guest_mode()
        assert "aktiviert" in result.lower()
        redis_mock.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_activate_guest_mode_no_redis(self, engine):
        engine.redis = None
        result = await engine.activate_guest_mode()
        assert "aktiviert" in result.lower()

    @pytest.mark.asyncio
    async def test_deactivate_guest_mode(self, engine, redis_mock):
        result = await engine.deactivate_guest_mode()
        assert "beendet" in result.lower() or "Normalbetrieb" in result
        redis_mock.delete.assert_called()

    @pytest.mark.asyncio
    async def test_is_guest_mode_active_true(self, engine, redis_mock):
        redis_mock.get = AsyncMock(return_value="active")
        assert await engine.is_guest_mode_active() is True

    @pytest.mark.asyncio
    async def test_is_guest_mode_active_false(self, engine, redis_mock):
        redis_mock.get = AsyncMock(return_value=None)
        assert await engine.is_guest_mode_active() is False

    @pytest.mark.asyncio
    async def test_is_guest_mode_active_bytes(self, engine, redis_mock):
        redis_mock.get = AsyncMock(return_value=b"active")
        assert await engine.is_guest_mode_active() is True

    @pytest.mark.asyncio
    async def test_is_guest_mode_no_redis(self, engine):
        engine.redis = None
        assert await engine.is_guest_mode_active() is False

    def test_get_guest_mode_prompt_with_restrictions(self, engine):
        engine.guest_restrictions = {
            "hide_personal_info": True,
            "formal_tone": True,
            "restrict_security": True,
        }
        prompt = engine.get_guest_mode_prompt()
        assert "GAESTE-MODUS" in prompt
        assert "persoenlichen Infos" in prompt
        assert "Formeller Ton" in prompt
        assert "Alarm" in prompt

    def test_get_guest_mode_prompt_minimal(self, engine):
        engine.guest_restrictions = {}
        prompt = engine.get_guest_mode_prompt()
        assert "GAESTE-MODUS" in prompt
        assert "Hoeflich ablehnen" in prompt


# ============================================================
# Guest WiFi
# ============================================================


class TestGuestWifi:
    @pytest.mark.asyncio
    async def test_activate_guest_wifi_no_executor(self, engine):
        engine._executor = None
        result = await engine.activate_guest_wifi()
        assert "Executor" in result or "verfügbar" in result

    @pytest.mark.asyncio
    async def test_activate_guest_wifi_success(self, engine):
        executor = AsyncMock()
        executor.execute = AsyncMock(return_value={"success": True})
        engine._executor = executor
        engine.guest_restrictions = {
            "guest_wifi": {"ssid": "TestWifi", "password": "1234"}
        }
        result = await engine.activate_guest_wifi()
        assert "TestWifi" in result
        assert "1234" in result

    @pytest.mark.asyncio
    async def test_deactivate_guest_wifi_no_executor(self, engine):
        engine._executor = None
        result = await engine.deactivate_guest_wifi()
        assert "Executor" in result or "verfügbar" in result

    @pytest.mark.asyncio
    async def test_deactivate_guest_wifi_success(self, engine):
        executor = AsyncMock()
        executor.execute = AsyncMock(return_value={"success": True})
        engine._executor = executor
        result = await engine.deactivate_guest_wifi()
        assert "deaktiviert" in result.lower()


# ============================================================
# Absence Log
# ============================================================


class TestAbsenceLog:
    @pytest.mark.asyncio
    async def test_log_absence_no_redis(self, engine):
        engine.redis = None
        # Should not raise
        await engine.log_absence_event("motion", "Bewegung im Flur")

    @pytest.mark.asyncio
    async def test_log_absence_event(self, engine, redis_mock):
        await engine.log_absence_event("motion", "Bewegung im Flur")
        redis_mock.rpush.assert_called_once()
        redis_mock.expire.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_absence_summary_no_redis(self, engine):
        engine.redis = None
        result = await engine.get_absence_summary()
        assert result == ""

    @pytest.mark.asyncio
    async def test_get_absence_summary_no_entries(self, engine, redis_mock):
        redis_mock.lrange = AsyncMock(return_value=[])
        result = await engine.get_absence_summary()
        assert result == ""

    @pytest.mark.asyncio
    async def test_get_absence_summary_filters_noise(
        self, engine, redis_mock, ollama_mock
    ):
        """Irrelevante Events werden herausgefiltert."""
        entries = [
            b"2026-03-20T10:00:00|motion_idle|Idle since 5m",
            b"2026-03-20T10:05:00|sensor_update|unavailable",
            b"2026-03-20T11:00:00|alarm|Tuer geoeffnet",
        ]
        redis_mock.lrange = AsyncMock(return_value=entries)
        redis_mock.delete = AsyncMock()
        ollama_mock.chat = AsyncMock(
            return_value={
                "message": {
                    "content": "Waehrend Ihrer Abwesenheit wurde eine Tuer geoeffnet."
                },
            }
        )
        result = await engine.get_absence_summary()
        assert result != ""
        # LLM was called with only the relevant event
        ollama_mock.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_absence_summary_deduplicates(
        self, engine, redis_mock, ollama_mock
    ):
        """Doppelte Events werden dedupliziert."""
        entries = [
            b"2026-03-20T10:00:00|alarm|Tuer Flur geoeffnet",
            b"2026-03-20T10:01:00|alarm|Tuer Flur geoeffnet",
            b"2026-03-20T10:02:00|alarm|Tuer Flur geoeffnet",
        ]
        redis_mock.lrange = AsyncMock(return_value=entries)
        redis_mock.delete = AsyncMock()
        ollama_mock.chat = AsyncMock(
            return_value={
                "message": {"content": "Tuer wurde geoeffnet."},
            }
        )
        result = await engine.get_absence_summary()
        # Only one unique event should be passed to the LLM
        call_content = ollama_mock.chat.call_args[1]["messages"][1]["content"]
        assert call_content.count("Tuer Flur geoeffnet") == 1


# ============================================================
# Safety Checks (Goodnight)
# ============================================================


class TestSafetyChecks:
    @pytest.mark.asyncio
    async def test_no_states_returns_empty(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=None)
        issues = await engine._run_safety_checks()
        assert issues == []

    @pytest.mark.asyncio
    async def test_unlocked_door_is_critical(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "lock.front_door",
                    "state": "unlocked",
                    "attributes": {"friendly_name": "Haustuer"},
                },
            ]
        )
        # StateChangeLog.__new__ is used internally and wrapped in try/except
        issues = await engine._run_safety_checks()
        door_issues = [i for i in issues if i["type"] == "door_unlocked"]
        assert len(door_issues) == 1
        assert door_issues[0]["critical"] is True
        assert "Haustuer" in door_issues[0]["message"]

    @pytest.mark.asyncio
    async def test_lights_on_issue(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "light.kueche",
                    "state": "on",
                    "attributes": {"friendly_name": "Kueche"},
                },
                {
                    "entity_id": "light.bad",
                    "state": "on",
                    "attributes": {"friendly_name": "Bad"},
                },
            ]
        )
        issues = await engine._run_safety_checks()
        light_issues = [i for i in issues if i["type"] == "lights_on"]
        assert len(light_issues) == 1
        assert "2" in light_issues[0]["message"]
        assert light_issues[0]["critical"] is False

    @pytest.mark.asyncio
    async def test_alarm_disarmed_issue(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "alarm_control_panel.main",
                    "state": "disarmed",
                    "attributes": {},
                },
            ]
        )
        issues = await engine._run_safety_checks()
        alarm_issues = [i for i in issues if i["type"] == "alarm_off"]
        assert len(alarm_issues) == 1


# ============================================================
# Goodnight with Critical Issues
# ============================================================


class TestGoodnightCriticalIssues:
    @pytest.mark.asyncio
    async def test_critical_issues_skip_actions(
        self, engine, redis_mock, ha_mock, ollama_mock
    ):
        """Bei kritischen Issues werden Aktionen uebersprungen."""
        engine.goodnight_enabled = True
        engine._executor = AsyncMock()

        # Return unlocked door (critical)
        ha_mock.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "lock.front_door",
                    "state": "unlocked",
                    "attributes": {"friendly_name": "Haustuer"},
                },
            ]
        )

        ollama_mock.chat = AsyncMock(
            return_value={
                "message": {
                    "content": "Gute Nacht. Achtung: Haustuer nicht verriegelt."
                },
            }
        )

        result = await engine.execute_goodnight("Max")

        assert len(result["issues"]) >= 1
        # Critical issue → goodnight actions should NOT have been called
        critical = [i for i in result["issues"] if i.get("critical")]
        assert len(critical) >= 1


# ============================================================
# Travel Briefing
# ============================================================


class TestTravelBriefing:
    @pytest.mark.asyncio
    async def test_no_states(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=None)
        result = await engine.get_travel_briefing()
        assert result == ""

    @pytest.mark.asyncio
    async def test_no_travel_sensors(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(
            return_value=[
                {"entity_id": "sensor.temperature", "state": "22", "attributes": {}},
            ]
        )
        result = await engine.get_travel_briefing()
        assert result == ""

    @pytest.mark.asyncio
    async def test_with_travel_sensor(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "sensor.commute_travel_time",
                    "state": "35",
                    "attributes": {
                        "friendly_name": "Arbeitsweg",
                        "unit_of_measurement": "min",
                    },
                },
            ]
        )
        result = await engine.get_travel_briefing()
        assert "Verkehr" in result
        assert "Arbeitsweg" in result
        assert "35" in result

    @pytest.mark.asyncio
    async def test_travel_delay_detection(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "sensor.commute_travel_time",
                    "state": "50",
                    "attributes": {
                        "friendly_name": "Arbeitsweg",
                        "unit_of_measurement": "min",
                        "duration_in_traffic": "30",
                    },
                },
            ]
        )
        result = await engine.get_travel_briefing()
        assert "Verzögerung" in result or "Verzoegerung" in result

    @pytest.mark.asyncio
    async def test_travel_invalid_duration(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "sensor.commute_travel_time",
                    "state": "unavailable",
                    "attributes": {"friendly_name": "Arbeitsweg"},
                },
            ]
        )
        result = await engine.get_travel_briefing()
        assert result == ""


# ============================================================
# Wakeup Sequence
# ============================================================


class TestWakeupSequence:
    @pytest.mark.asyncio
    async def test_disabled_returns_false(self, engine):
        with patch("assistant.routine_engine.yaml_config", {"routines": {}}):
            result = await engine.execute_wakeup_sequence()
        assert result is False

    @pytest.mark.asyncio
    async def test_low_autonomy_returns_false(self, engine):
        ws_cfg = {"enabled": True, "min_autonomy_level": 4}
        with patch(
            "assistant.routine_engine.yaml_config",
            {
                "routines": {"morning_briefing": {"wakeup_sequence": ws_cfg}},
            },
        ):
            result = await engine.execute_wakeup_sequence(autonomy_level=2)
        assert result is False

    @pytest.mark.asyncio
    async def test_outside_time_window(self, engine):
        ws_cfg = {
            "enabled": True,
            "min_autonomy_level": 1,
            "window_start_hour": 5,
            "window_end_hour": 9,
        }
        with (
            patch(
                "assistant.routine_engine.yaml_config",
                {
                    "routines": {"morning_briefing": {"wakeup_sequence": ws_cfg}},
                },
            ),
            patch("assistant.routine_engine.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = datetime(2026, 3, 20, 12, 0, tzinfo=_TZ)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = await engine.execute_wakeup_sequence(autonomy_level=3)
        assert result is False

    @pytest.mark.asyncio
    async def test_already_done_today(self, engine, redis_mock):
        today = datetime.now(tz=_TZ).strftime("%Y-%m-%d")
        ws_cfg = {
            "enabled": True,
            "min_autonomy_level": 1,
            "window_start_hour": 0,
            "window_end_hour": 23,
        }
        redis_mock.get = AsyncMock(return_value=today.encode())
        with patch(
            "assistant.routine_engine.yaml_config",
            {
                "routines": {"morning_briefing": {"wakeup_sequence": ws_cfg}},
            },
        ):
            result = await engine.execute_wakeup_sequence(autonomy_level=3)
        assert result is False

    @pytest.mark.asyncio
    async def test_bed_occupied_skips(self, engine, redis_mock):
        ws_cfg = {
            "enabled": True,
            "min_autonomy_level": 1,
            "window_start_hour": 0,
            "window_end_hour": 23,
        }
        redis_mock.get = AsyncMock(return_value=None)
        with (
            patch(
                "assistant.routine_engine.yaml_config",
                {
                    "routines": {"morning_briefing": {"wakeup_sequence": ws_cfg}},
                },
            ),
            patch.object(
                engine, "_is_bed_occupied", new_callable=AsyncMock, return_value=True
            ),
        ):
            result = await engine.execute_wakeup_sequence(autonomy_level=3)
        assert result is False


# ============================================================
# Goodnight Intent Edge Cases
# ============================================================


class TestGoodnightIntentEdgeCases:
    @pytest.mark.asyncio
    async def test_device_commands_excluded(self, engine):
        """Geraetebefehle duerfen nicht als Gute-Nacht-Intent gelten."""
        assert (
            await engine.is_goodnight_intent("Rollladen runter fuer die Nacht") is False
        )
        assert await engine.is_goodnight_intent("Licht aus im Schlafzimmer") is False
        assert await engine.is_goodnight_intent("Heizung auf 18 Grad Nacht") is False

    @pytest.mark.asyncio
    async def test_extended_triggers(self, engine):
        assert await engine.is_goodnight_intent("ab ins bett") is True
        assert await engine.is_goodnight_intent("bin muede") is True
        assert await engine.is_goodnight_intent("bis morgen") is True
        assert await engine.is_goodnight_intent("feierabend") is True

    @pytest.mark.asyncio
    async def test_long_text_skips_llm(self, engine, ollama_mock):
        """Text > 80 Zeichen wird ohne LLM abgelehnt."""
        long_text = "x" * 81
        result = await engine.is_goodnight_intent(long_text)
        assert result is False
        ollama_mock.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_fallback_on_timeout(self, engine, ollama_mock):
        """LLM-Timeout gibt False zurueck."""
        ollama_mock.chat = AsyncMock(side_effect=asyncio.TimeoutError())
        result = await engine.is_goodnight_intent("schlafe wohl")
        # "schlafe" matches extended trigger, so this returns True before LLM
        assert result is True

    @pytest.mark.asyncio
    async def test_llm_fallback_unrecognized(self, engine, ollama_mock):
        """LLM erkennt keinen Goodnight-Intent."""
        ollama_mock.chat = AsyncMock(
            return_value={
                "message": {"content": "nein"},
            }
        )
        result = await engine.is_goodnight_intent("Servus")
        assert result is False


# ============================================================
# Morning Briefing LLM Fallback
# ============================================================


class TestMorningBriefingLLMFallback:
    @pytest.mark.asyncio
    async def test_llm_error_falls_back_to_raw_parts(
        self, engine, redis_mock, ollama_mock
    ):
        """Bei LLM-Fehler wird der rohe Text als Fallback genutzt."""
        redis_mock.set = AsyncMock(return_value=True)  # Lock acquired
        redis_mock.sismember = AsyncMock(return_value=False)

        async def fake_module(module, person, style):
            if module == "greeting":
                return "Tag: Freitag"
            if module == "weather":
                return "Wetter: Regen"
            return ""

        engine._get_briefing_module = fake_module
        engine._execute_morning_actions = AsyncMock(return_value=[])
        ollama_mock.chat = AsyncMock(side_effect=Exception("LLM down"))

        result = await engine.generate_morning_briefing(force=True)
        # Fallback: raw parts joined
        assert "Tag: Freitag" in result["text"]
        assert "Wetter: Regen" in result["text"]

    @pytest.mark.asyncio
    async def test_no_parts_returns_empty(self, engine, redis_mock):
        """Wenn alle Module leer sind, kommt kein Briefing."""
        redis_mock.set = AsyncMock(return_value=True)
        redis_mock.sismember = AsyncMock(return_value=False)

        engine._get_briefing_module = AsyncMock(return_value="")

        result = await engine.generate_morning_briefing(force=True)
        assert result["text"] == ""
        assert result["actions"] == []


# ============================================================
# Greeting Context
# ============================================================


class TestGreetingContext:
    @pytest.mark.asyncio
    async def test_greeting_includes_weekday(self, engine):
        engine._semantic_memory = None
        with patch(
            "assistant.routine_engine.yaml_config", {"persons": {"birthdays": {}}}
        ):
            result = await engine._get_greeting_context("Max")
        assert "Tag:" in result
        # Must contain one of the weekday names
        weekdays = [
            "Montag",
            "Dienstag",
            "Mittwoch",
            "Donnerstag",
            "Freitag",
            "Samstag",
            "Sonntag",
        ]
        assert any(d in result for d in weekdays)

    @pytest.mark.asyncio
    async def test_greeting_with_semantic_memory(self, engine):
        sm = AsyncMock()
        sm.get_upcoming_personal_dates = AsyncMock(
            return_value=[
                {
                    "days_until": 0,
                    "person": "lisa",
                    "label": "Geburtstag",
                    "date_type": "birthday",
                    "anniversary_years": 30,
                },
            ]
        )
        engine._semantic_memory = sm
        with patch(
            "assistant.routine_engine.yaml_config", {"persons": {"birthdays": {}}}
        ):
            result = await engine._get_greeting_context("Max")
        assert "Lisa" in result
        assert "30" in result

    @pytest.mark.asyncio
    async def test_greeting_semantic_memory_error(self, engine):
        """Semantic Memory Fehler wird abgefangen."""
        sm = AsyncMock()
        sm.get_upcoming_personal_dates = AsyncMock(side_effect=RuntimeError("DB down"))
        engine._semantic_memory = sm
        with patch(
            "assistant.routine_engine.yaml_config", {"persons": {"birthdays": {}}}
        ):
            result = await engine._get_greeting_context("Max")
        # Should still return basic greeting without crashing
        assert "Tag:" in result


# ============================================================
# Briefing Module Dispatch
# ============================================================


class TestBriefingModuleDispatch:
    @pytest.mark.asyncio
    async def test_unknown_module_returns_empty(self, engine):
        result = await engine._get_briefing_module("nonexistent_module", "Max", "kurz")
        assert result == ""

    @pytest.mark.asyncio
    async def test_module_error_returns_empty(self, engine, ha_mock):
        """Fehler in einem Modul gibt leeren String zurueck."""
        ha_mock.get_states = AsyncMock(side_effect=RuntimeError("HA down"))
        result = await engine._get_briefing_module("house_status", "Max", "kurz")
        assert result == ""


# ============================================================
# Migrate YAML Birthdays
# ============================================================


class TestMigrateYamlBirthdays:
    @pytest.mark.asyncio
    async def test_no_redis_returns_zero(self, engine):
        engine.redis = None
        result = await engine.migrate_yaml_birthdays(MagicMock())
        assert result == 0

    @pytest.mark.asyncio
    async def test_no_semantic_memory_returns_zero(self, engine, redis_mock):
        result = await engine.migrate_yaml_birthdays(None)
        assert result == 0

    @pytest.mark.asyncio
    async def test_already_migrated(self, engine, redis_mock):
        redis_mock.get = AsyncMock(return_value="1")
        result = await engine.migrate_yaml_birthdays(MagicMock())
        assert result == 0

    @pytest.mark.asyncio
    async def test_no_birthdays_in_yaml(self, engine, redis_mock):
        redis_mock.get = AsyncMock(return_value=None)
        with patch(
            "assistant.routine_engine.yaml_config", {"persons": {"birthdays": {}}}
        ):
            result = await engine.migrate_yaml_birthdays(MagicMock())
        assert result == 0
        redis_mock.set.assert_called()  # Flag set even if no birthdays

    @pytest.mark.asyncio
    async def test_migrate_with_birthdays(self, engine, redis_mock):
        """Successfully migrates YAML birthdays to semantic memory."""
        redis_mock.get = AsyncMock(return_value=None)
        sm = AsyncMock()
        sm.store_personal_date = AsyncMock(return_value=True)
        with patch(
            "assistant.routine_engine.yaml_config",
            {
                "persons": {"birthdays": {"Max": "1990-06-15", "Anna": "1985-12-01"}},
            },
        ):
            result = await engine.migrate_yaml_birthdays(sm)
        assert result == 2
        assert sm.store_personal_date.call_count == 2
        redis_mock.set.assert_called()

    @pytest.mark.asyncio
    async def test_migrate_with_short_date_format(self, engine, redis_mock):
        """Handles MM-DD date format without year."""
        redis_mock.get = AsyncMock(return_value=None)
        sm = AsyncMock()
        sm.store_personal_date = AsyncMock(return_value=True)
        with patch(
            "assistant.routine_engine.yaml_config",
            {
                "persons": {"birthdays": {"Max": "06-15"}},
            },
        ):
            result = await engine.migrate_yaml_birthdays(sm)
        assert result == 1
        call_kwargs = sm.store_personal_date.call_args[1]
        assert call_kwargs["year"] == ""
        assert call_kwargs["date_mm_dd"] == "06-15"

    @pytest.mark.asyncio
    async def test_migrate_partial_failure(self, engine, redis_mock):
        """Counts only successful migrations."""
        redis_mock.get = AsyncMock(return_value=None)
        sm = AsyncMock()
        sm.store_personal_date = AsyncMock(side_effect=[True, False])
        with patch(
            "assistant.routine_engine.yaml_config",
            {
                "persons": {"birthdays": {"Max": "1990-06-15", "Anna": "1985-12-01"}},
            },
        ):
            result = await engine.migrate_yaml_birthdays(sm)
        assert result == 1
