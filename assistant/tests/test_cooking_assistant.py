"""
Tests fuer CookingAssistant — Koch-Session + Redis-Persistenz.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from assistant.cooking_assistant import (
    CookingAssistant,
    CookingSession,
    CookingStep,
)


@pytest.fixture
def ollama():
    return AsyncMock()


@pytest.fixture
def redis_mock():
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.setex = AsyncMock()
    r.delete = AsyncMock()
    return r


@pytest.fixture
def assistant(ollama, redis_mock):
    ca = CookingAssistant(ollama)
    ca.redis = redis_mock
    return ca


def _make_session(dish="Spaghetti", steps=3, current_step=0):
    return CookingSession(
        dish=dish,
        portions=2,
        ingredients=["200g Spaghetti", "100g Guanciale"],
        steps=[
            CookingStep(number=i + 1, instruction=f"Schritt {i + 1}", timer_minutes=None)
            for i in range(steps)
        ],
        current_step=current_step,
        started_at=1000.0,
        person="max",
    )


class TestCookingIntent:
    def test_recognizes_cooking_intent(self, assistant):
        assert assistant.is_cooking_intent("Ich will Spaghetti kochen") is True
        assert assistant.is_cooking_intent("Rezept fuer Lasagne") is True
        assert assistant.is_cooking_intent("Wie ist das Wetter?") is False

    def test_recognizes_wie_mache_ich(self, assistant):
        assert assistant.is_cooking_intent("Wie mache ich Pasta Carbonara?") is True
        assert assistant.is_cooking_intent("Wie macht man Risotto?") is True
        assert assistant.is_cooking_intent("Wie koche ich Reis?") is True
        assert assistant.is_cooking_intent("Wie bereite ich Sushi zu?") is True


class TestDishExtraction:
    def test_wie_mache_ich(self, assistant):
        assert assistant._extract_dish("Wie mache ich Pasta Carbonara?") == "pasta carbonara"

    def test_wie_macht_man(self, assistant):
        assert assistant._extract_dish("Wie macht man Risotto?") == "risotto"

    def test_rezept_fuer(self, assistant):
        assert assistant._extract_dish("Rezept fuer Lasagne") == "lasagne"

    def test_ich_will_kochen(self, assistant):
        assert assistant._extract_dish("Ich will Spaghetti kochen") == "spaghetti"

    def test_no_trailing_punctuation(self, assistant):
        assert assistant._extract_dish("Wie mache ich Gulasch?") == "gulasch"
        assert assistant._extract_dish("Wie koche ich Suppe!") == "suppe"

    def test_navigation_detection(self, assistant):
        # Ohne aktive Session
        assert assistant.is_cooking_navigation("weiter") is False
        # Mit aktiver Session
        assistant.session = _make_session()
        assert assistant.is_cooking_navigation("weiter") is True
        assert assistant.is_cooking_navigation("zutaten") is True
        assert assistant.is_cooking_navigation("Wie ist das Wetter?") is False


class TestNavigation:
    @pytest.mark.asyncio
    async def test_next_step(self, assistant):
        assistant.session = _make_session(current_step=-1)
        result = await assistant._next_step()
        assert "Schritt 1" in result
        assert assistant.session.current_step == 0

    @pytest.mark.asyncio
    async def test_prev_step(self, assistant):
        assistant.session = _make_session(current_step=1)
        result = await assistant._prev_step()
        assert "Zurueck" in result
        assert assistant.session.current_step == 0

    @pytest.mark.asyncio
    async def test_prev_step_at_start(self, assistant):
        assistant.session = _make_session(current_step=0)
        result = await assistant._prev_step()
        assert "ersten Schritt" in result

    @pytest.mark.asyncio
    async def test_stop_session(self, assistant):
        assistant.session = _make_session()
        result = await assistant._stop_session()
        assert "beendet" in result
        assert assistant.session is None

    def test_show_ingredients(self, assistant):
        assistant.session = _make_session()
        result = assistant._show_ingredients()
        assert "Spaghetti" in result
        assert "Guanciale" in result


class TestPersistence:
    @pytest.mark.asyncio
    async def test_persist_session(self, assistant, redis_mock):
        assistant.session = _make_session()
        await assistant._persist_session()
        redis_mock.setex.assert_called_once()
        call_args = redis_mock.setex.call_args
        assert call_args[0][0] == "mha:cooking:session"
        data = json.loads(call_args[0][2])
        assert data["dish"] == "Spaghetti"
        assert len(data["steps"]) == 3

    @pytest.mark.asyncio
    async def test_restore_session(self, assistant, redis_mock):
        session_data = {
            "dish": "Lasagne",
            "portions": 4,
            "ingredients": ["500g Hackfleisch"],
            "steps": [
                {"number": 1, "instruction": "Hack anbraten", "timer_minutes": 5},
            ],
            "current_step": 0,
            "started_at": 2000.0,
            "person": "lisa",
        }
        redis_mock.get = AsyncMock(return_value=json.dumps(session_data))
        await assistant._restore_session()
        assert assistant.session is not None
        assert assistant.session.dish == "Lasagne"
        assert assistant.session.portions == 4
        assert assistant.session.person == "lisa"

    @pytest.mark.asyncio
    async def test_clear_persisted_session(self, assistant, redis_mock):
        await assistant._clear_persisted_session()
        redis_mock.delete.assert_called_once_with("mha:cooking:session")

    @pytest.mark.asyncio
    async def test_initialize_restores_session(self, ollama, redis_mock):
        session_data = {
            "dish": "Pizza",
            "portions": 2,
            "ingredients": [],
            "steps": [{"number": 1, "instruction": "Teig", "timer_minutes": None}],
            "current_step": 0,
            "started_at": 3000.0,
            "person": "max",
        }
        redis_mock.get = AsyncMock(return_value=json.dumps(session_data))
        ca = CookingAssistant(ollama)
        await ca.initialize(redis_client=redis_mock)
        assert ca.session is not None
        assert ca.session.dish == "Pizza"


class TestPortionScaling:
    def test_scale_up(self, assistant):
        assistant.session = _make_session()
        result = assistant._adjust_portions(4)
        assert "4" in result
        assert assistant.session.portions == 4
        # 200g → 400g
        assert "400" in assistant.session.ingredients[0]

    def test_scale_down(self, assistant):
        assistant.session = _make_session()
        result = assistant._adjust_portions(1)
        assert "1" in result
        assert "100" in assistant.session.ingredients[0]
