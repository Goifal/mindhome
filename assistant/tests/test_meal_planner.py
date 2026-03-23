"""Tests fuer MealPlanner - Essensplanung."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from assistant.meal_planner import MealPlanner


@pytest.fixture
def ollama_mock():
    mock = AsyncMock()
    mock.generate = AsyncMock(
        return_value="1. Spaghetti Carbonara\n2. Gemuesesuppe\n3. Omelette"
    )
    return mock


@pytest.fixture
def redis_mock():
    mock = AsyncMock()
    mock.hset = AsyncMock()
    mock.zadd = AsyncMock()
    mock.zcard = AsyncMock(return_value=5)
    mock.zrangebyscore = AsyncMock(return_value=[])
    mock.hgetall = AsyncMock(return_value={})
    mock.expire = AsyncMock()
    mock.zrange = AsyncMock(return_value=[])
    mock.delete = AsyncMock()
    mock.zrem = AsyncMock()

    pipe = MagicMock()
    pipe.hget = MagicMock()
    pipe.hgetall = MagicMock()
    pipe.execute = AsyncMock(return_value=[])
    mock.pipeline = MagicMock(return_value=pipe)

    return mock


@pytest.fixture
def inventory_mock():
    mock = AsyncMock()
    mock.list_items = AsyncMock(
        return_value={
            "items": [
                {"name": "Spaghetti", "expiry_date": "2026-04-01"},
                {"name": "Eier", "expiry_date": "2026-03-25"},
                {"name": "Parmesan", "expiry_date": ""},
            ]
        }
    )
    return mock


@pytest.fixture
def meal_planner(ollama_mock, redis_mock, inventory_mock):
    mp = MealPlanner(ollama_mock)
    mp.redis = redis_mock
    mp.inventory = inventory_mock
    mp.ha = AsyncMock()
    mp.ha.call_service = AsyncMock(return_value=True)
    return mp


@pytest.mark.asyncio
async def test_suggest_from_inventory(meal_planner, ollama_mock):
    result = await meal_planner.suggest_from_inventory()
    assert result["success"] is True
    ollama_mock.generate.assert_called_once()


@pytest.mark.asyncio
async def test_suggest_no_inventory(ollama_mock, redis_mock):
    mp = MealPlanner(ollama_mock)
    mp.redis = redis_mock
    result = await mp.suggest_from_inventory()
    assert result["success"] is False


@pytest.mark.asyncio
async def test_suggest_empty_inventory(meal_planner, inventory_mock):
    inventory_mock.list_items = AsyncMock(return_value={"items": []})
    result = await meal_planner.suggest_from_inventory()
    assert result["success"] is True
    assert "Keine Vorraete" in result["message"]


@pytest.mark.asyncio
async def test_log_meal(meal_planner, redis_mock):
    result = await meal_planner.log_meal(
        meal="Spaghetti Carbonara",
        meal_type="abendessen",
        rating=4,
    )
    assert result["success"] is True
    assert "protokolliert" in result["message"]
    redis_mock.hset.assert_called()
    redis_mock.zadd.assert_called()


@pytest.mark.asyncio
async def test_log_meal_empty(meal_planner):
    result = await meal_planner.log_meal(meal="")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_log_meal_invalid_type(meal_planner, redis_mock):
    """Ungueltiger Mahlzeitentyp -> Fallback auf 'abendessen'."""
    result = await meal_planner.log_meal(
        meal="Pizza",
        meal_type="brunch",
    )
    assert result["success"] is True


@pytest.mark.asyncio
async def test_get_meal_history_empty(meal_planner, redis_mock):
    result = await meal_planner.get_meal_history()
    assert result["success"] is True
    assert "Keine Mahlzeiten" in result["message"]


@pytest.mark.asyncio
async def test_get_current_plan_empty(meal_planner, redis_mock):
    result = await meal_planner.get_current_plan()
    assert result["success"] is True
    assert "Kein Wochenplan" in result["message"]


@pytest.mark.asyncio
async def test_add_missing_to_shopping(meal_planner):
    result = await meal_planner.add_missing_to_shopping(
        recipe_ingredients=["Mehl", "Butter", "Spaghetti"]
    )
    assert result["success"] is True
    assert "2" in result["message"]


@pytest.mark.asyncio
async def test_add_missing_empty_list(meal_planner):
    result = await meal_planner.add_missing_to_shopping(recipe_ingredients=[])
    assert result["success"] is False


@pytest.mark.asyncio
async def test_create_weekly_plan(meal_planner, ollama_mock):
    result = await meal_planner.create_weekly_plan(preferences="viel Gemuese")
    assert result["success"] is True
    ollama_mock.generate.assert_called()


def test_context_hints():
    mp = MealPlanner(AsyncMock())
    hints = mp.get_context_hints()
    assert len(hints) > 0
    assert "MealPlanner" in hints[0]
