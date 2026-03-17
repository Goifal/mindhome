"""
Tests fuer RoutineEngine — Morning Briefing, Sleep-Awareness, Goodnight.
"""

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
        assert RoutineEngine._translate_weather("unknown_condition") == "unknown_condition"

    def test_fog(self):
        from assistant.routine_engine import RoutineEngine
        assert RoutineEngine._translate_weather("fog") == "Nebel"

    def test_snowy(self):
        from assistant.routine_engine import RoutineEngine
        assert RoutineEngine._translate_weather("snowy") == "Schnee"

    def test_lightning_rainy(self):
        from assistant.routine_engine import RoutineEngine
        assert RoutineEngine._translate_weather("lightning-rainy") == "Gewitter mit Regen"


# ── Check Birthday ─────────────────────────────────────────────────────

class TestCheckBirthday:

    def test_no_birthdays(self, engine):
        with patch("assistant.routine_engine.yaml_config", {"persons": {"birthdays": {}}}):
            result = engine._check_birthday("Max", datetime.now(tz=_TZ))
        assert result == ""

    def test_birthday_today(self, engine):
        now = datetime.now(tz=_TZ)
        birthday = f"1990-{now.strftime('%m-%d')}"
        with patch("assistant.routine_engine.yaml_config", {"persons": {"birthdays": {"Max": birthday}}}):
            result = engine._check_birthday("Max", now)
        assert "GEBURTSTAG" in result
        assert "Max" in result

    def test_birthday_other_person(self, engine):
        now = datetime.now(tz=_TZ)
        birthday = f"1985-{now.strftime('%m-%d')}"
        with patch("assistant.routine_engine.yaml_config", {"persons": {"birthdays": {"Anna": birthday}}}):
            result = engine._check_birthday("Max", now)
        assert "GEBURTSTAG" in result
        assert "Anna" in result

    def test_no_birthday_today(self, engine):
        now = datetime.now(tz=_TZ)
        birthday = "1990-01-01"
        # Only matches on Jan 1
        with patch("assistant.routine_engine.yaml_config", {"persons": {"birthdays": {"Max": birthday}}}):
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
        assert await engine.is_goodnight_intent("Wie kalt wird es heute Nacht?") is False
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
        ollama_mock.chat = AsyncMock(return_value={
            "message": {"content": "Gute Nacht, Sir. Alles ist sicher."},
        })

        result = await engine.execute_goodnight("Max")
        assert "text" in result
        assert "actions" in result
        assert "issues" in result


# ── Briefing System Prompt ─────────────────────────────────────────────

class TestBriefingSystemPrompt:

    def test_without_personality(self, engine):
        engine._personality = None
        with patch("assistant.routine_engine.settings") as mock_s, \
             patch("assistant.routine_engine.get_person_title", return_value="Sir"):
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
        with patch("assistant.routine_engine.settings") as mock_s, \
             patch("assistant.routine_engine.get_person_title", return_value="Sir"):
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
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "light.test", "state": "on"},
        ])
        result = await engine._get_calendar_briefing()
        assert result == ""

    @pytest.mark.asyncio
    async def test_with_events(self, engine, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "calendar.default", "attributes": {"message": "Team Meeting", "start_time": "10:00"}},
        ])
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
            ha_mock.get_states = AsyncMock(return_value=[
                {"entity_id": "light.kitchen", "state": "on", "attributes": {"friendly_name": "Kueche"}},
                {"entity_id": "light.living", "state": "on", "attributes": {"friendly_name": "Wohnzimmer"}},
            ])
            result = await engine._get_house_status_briefing()
        assert "Lichter an: 2" in result


# ── Reload Config ──────────────────────────────────────────────────────

class TestRoutineReloadConfig:

    def test_reload(self, engine):
        with patch("assistant.routine_engine.yaml_config", {
            "routines": {
                "morning_briefing": {"enabled": False, "weekday_style": "lang"},
                "good_night": {"enabled": False},
                "guest_mode": {},
            },
        }):
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
        ha_mock.call_service_with_response = AsyncMock(return_value=[
            {"weather.home": {"forecast": [{"temperature": 20, "condition": "sunny"}]}},
        ])
        result = await engine._get_forecast_via_service("weather.home")
        assert len(result) == 1
        assert result[0]["temperature"] == 20

    @pytest.mark.asyncio
    async def test_format2_dict(self, engine, ha_mock):
        ha_mock.call_service_with_response = AsyncMock(return_value={
            "weather.home": {"forecast": [{"temperature": 15}]},
        })
        result = await engine._get_forecast_via_service("weather.home")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_service_response_wrapper(self, engine, ha_mock):
        ha_mock.call_service_with_response = AsyncMock(return_value={
            "service_response": {"weather.home": {"forecast": [{"temperature": 18}]}},
        })
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

        with patch.object(engine, "_is_bed_occupied", new_callable=AsyncMock, return_value=False):
            result = await engine._execute_morning_actions()
        assert len(result) == 1
        assert result[0]["function"] == "set_cover"

    @pytest.mark.asyncio
    async def test_covers_up_skipped_bed_occupied(self, engine, redis_mock):
        executor = AsyncMock()
        engine._executor = executor
        engine.morning_actions = {"covers_up": True}
        redis_mock.get = AsyncMock(return_value=None)

        with patch.object(engine, "_is_bed_occupied", new_callable=AsyncMock, return_value=True):
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
