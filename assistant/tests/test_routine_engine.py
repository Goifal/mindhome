"""
Tests fuer RoutineEngine — Morning Briefing, Sleep-Awareness, Goodnight.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

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
        today = datetime.now().date().isoformat()

        async def sismember_side_effect(key, date_str):
            return date_str == today

        redis_mock.sismember = AsyncMock(side_effect=sismember_side_effect)
        result = await engine._get_sleep_awareness()
        assert result.get("was_late") is True
        assert "SCHLAF-HINWEIS" in result.get("briefing_note", "")

    @pytest.mark.asyncio
    async def test_consecutive_nights_escalation(self, engine, redis_mock):
        today = datetime.now().date()
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
        today = datetime.now().strftime("%Y-%m-%d")
        # Lock existiert bereits (set NX gibt None zurueck) + done-Datum ist heute
        redis_mock.set = AsyncMock(return_value=None)
        redis_mock.get = AsyncMock(return_value=today)
        result = await engine.generate_morning_briefing()
        assert result["text"] == ""

    @pytest.mark.asyncio
    async def test_force_ignores_done_flag(self, engine, redis_mock, ollama_mock):
        today = datetime.now().strftime("%Y-%m-%d")
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
