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
    CookingTimer,
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
    @pytest.mark.asyncio
    async def test_scale_up(self, assistant):
        assistant.session = _make_session()
        result = await assistant._adjust_portions(4)
        assert "4" in result
        assert assistant.session.portions == 4
        # 200g → 400g
        assert "400" in assistant.session.ingredients[0]

    @pytest.mark.asyncio
    async def test_scale_down(self, assistant):
        assistant.session = _make_session()
        result = await assistant._adjust_portions(1)
        assert "1" in result
        assert "100" in assistant.session.ingredients[0]

    @pytest.mark.asyncio
    async def test_scale_persists_to_redis(self, assistant, redis_mock):
        """Portionen-Aenderung muss in Redis gespeichert werden."""
        assistant.session = _make_session()
        await assistant._adjust_portions(4)
        redis_mock.setex.assert_called()


class TestRecipeParsing:
    def test_valid_json(self, assistant):
        content = json.dumps({
            "dish": "Testgericht",
            "portions": 2,
            "ingredients": ["100g Mehl", "2 Eier"],
            "steps": [
                {"number": 1, "instruction": "Mehl sieben", "timer_minutes": None},
                {"number": 2, "instruction": "Eier unterruehren", "timer_minutes": None},
            ],
        })
        session = assistant._parse_recipe(content, "Testgericht", 2, "max")
        assert session is not None
        assert session.dish == "Testgericht"
        assert len(session.steps) == 2
        assert len(session.ingredients) == 2

    def test_json_with_surrounding_text(self, assistant):
        """LLM antwortet manchmal mit Text vor/nach dem JSON."""
        content = 'Hier ist dein Rezept:\n{"dish":"Pasta","portions":2,"ingredients":["200g Pasta"],"steps":[{"number":1,"instruction":"Kochen","timer_minutes":8}]}\nGuten Appetit!'
        session = assistant._parse_recipe(content, "Pasta", 2, "max")
        assert session is not None
        assert session.dish == "Pasta"
        assert session.steps[0].timer_minutes == 8

    def test_invalid_json(self, assistant):
        session = assistant._parse_recipe("Das ist kein JSON", "Test", 2, "max")
        assert session is None

    def test_empty_steps(self, assistant):
        content = json.dumps({"dish": "Leer", "portions": 1, "ingredients": [], "steps": []})
        session = assistant._parse_recipe(content, "Leer", 1, "max")
        assert session is None

    def test_step_with_timer(self, assistant):
        content = json.dumps({
            "dish": "Nudeln",
            "portions": 2,
            "ingredients": ["500g Nudeln"],
            "steps": [
                {"number": 1, "instruction": "Nudeln kochen", "timer_minutes": 10},
            ],
        })
        session = assistant._parse_recipe(content, "Nudeln", 2, "max")
        assert session.steps[0].timer_minutes == 10


class TestTimerDataclass:
    def test_fresh_timer_remaining(self):
        timer = CookingTimer(label="Test", duration_seconds=300)
        assert timer.remaining_seconds == 0
        assert not timer.is_done

    def test_started_timer(self):
        import time
        timer = CookingTimer(label="Test", duration_seconds=300)
        timer.start()
        assert timer.remaining_seconds > 0
        assert timer.remaining_seconds <= 300

    def test_finished_timer(self):
        timer = CookingTimer(label="Test", duration_seconds=60, finished=True)
        assert timer.is_done
        assert timer.remaining_seconds == 0

    def test_format_remaining_minutes(self):
        import time
        timer = CookingTimer(label="Test", duration_seconds=125, started_at=time.time())
        fmt = timer.format_remaining()
        assert "Minuten" in fmt

    def test_format_abgelaufen(self):
        timer = CookingTimer(label="Test", duration_seconds=1, finished=True)
        assert timer.format_remaining() == "abgelaufen"


class TestExplicitPortions:
    def test_explicit_with_keyword(self, assistant):
        assert assistant._extract_explicit_portions("fuer 4 portionen") == 4
        assert assistant._extract_explicit_portions("für 6 personen") == 6

    def test_no_keyword_returns_zero(self, assistant):
        """Ohne explizites Portionen/Personen-Keyword: 0 zurueckgeben."""
        assert assistant._extract_explicit_portions("fuer was ist der timer") == 0
        assert assistant._extract_explicit_portions("danke fuer die hilfe") == 0

    def test_number_with_keyword(self, assistant):
        assert assistant._extract_explicit_portions("8 portionen bitte") == 8

    def test_max_20(self, assistant):
        assert assistant._extract_explicit_portions("fuer 50 portionen") == 20


class TestNavigationRouting:
    @pytest.mark.asyncio
    async def test_finish_all_steps(self, assistant):
        """Letzter Schritt -> Fertig-Meldung."""
        assistant.session = _make_session(steps=2, current_step=1)
        result = await assistant._next_step()
        assert "Fertig" in result or "abgeschlossen" in result

    def test_repeat_no_current_step(self, assistant):
        assistant.session = _make_session(current_step=-1)
        result = assistant._repeat_step()
        assert "keinen aktuellen Schritt" in result

    def test_status_shows_dish(self, assistant):
        assistant.session = _make_session(dish="Risotto")
        result = assistant._show_status()
        assert "Risotto" in result

    @pytest.mark.asyncio
    async def test_handle_navigation_stop(self, assistant):
        assistant.session = _make_session()
        result = await assistant.handle_navigation("stop kochen")
        assert "beendet" in result
        assert assistant.session is None

    def test_disabled_no_intent(self, assistant):
        """Deaktivierter Koch-Modus erkennt keine Intents."""
        assistant.enabled = False
        assert assistant.is_cooking_intent("Ich will Pasta kochen") is False
