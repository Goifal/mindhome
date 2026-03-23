"""Tests fuer TaskManager - Aufgabenverwaltung."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from assistant.task_manager import TaskManager


@pytest.fixture
def ha_mock():
    mock = AsyncMock()
    mock.call_service = AsyncMock(return_value=True)
    mock.get_state = AsyncMock(
        return_value={
            "state": "2",
            "attributes": {
                "items": [
                    {"summary": "Milch kaufen", "status": "needs_action"},
                    {
                        "summary": "Zahnarzt anrufen",
                        "status": "needs_action",
                        "due": "2026-03-25",
                    },
                ]
            },
        }
    )
    return mock


@pytest.fixture
def redis_mock():
    mock = AsyncMock()
    mock.hset = AsyncMock()
    mock.expire = AsyncMock()
    mock.sadd = AsyncMock()
    mock.smembers = AsyncMock(return_value=set())
    mock.hgetall = AsyncMock(return_value={})
    mock.hget = AsyncMock(return_value=None)
    mock.srem = AsyncMock()
    mock.delete = AsyncMock()
    return mock


@pytest.fixture
def task_mgr(ha_mock, redis_mock):
    tm = TaskManager(ha_mock)
    tm.redis = redis_mock
    return tm


@pytest.mark.asyncio
async def test_add_task_success(task_mgr, ha_mock, redis_mock):
    task_mgr.redis = redis_mock
    await task_mgr.initialize(redis_client=redis_mock)
    if task_mgr._recurring_task:
        task_mgr._recurring_task.cancel()
    result = await task_mgr.add_task(title="Milch kaufen", person="max")
    assert result["success"] is True
    assert "Milch kaufen" in result["message"]
    ha_mock.call_service.assert_called_once()


@pytest.mark.asyncio
async def test_add_task_empty_title(task_mgr):
    result = await task_mgr.add_task(title="")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_add_task_with_due_date(task_mgr, ha_mock, redis_mock):
    task_mgr.redis = redis_mock
    result = await task_mgr.add_task(
        title="Steuer abgeben",
        due_date="2026-04-15",
        priority="high",
    )
    assert result["success"] is True
    assert "faellig" in result["message"]


@pytest.mark.asyncio
async def test_list_tasks(task_mgr):
    result = await task_mgr.list_tasks()
    assert result["success"] is True
    assert "Milch kaufen" in result["message"]
    assert "Zahnarzt anrufen" in result["message"]


@pytest.mark.asyncio
async def test_complete_task(task_mgr, ha_mock):
    result = await task_mgr.complete_task(title="Milch kaufen")
    assert result["success"] is True
    assert "erledigt" in result["message"]


@pytest.mark.asyncio
async def test_complete_task_empty(task_mgr):
    result = await task_mgr.complete_task(title="")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_remove_task(task_mgr, ha_mock):
    result = await task_mgr.remove_task(title="Milch kaufen")
    assert result["success"] is True


@pytest.mark.asyncio
async def test_add_recurring_task(task_mgr, redis_mock):
    result = await task_mgr.add_recurring_task(
        title="Papiertonne raus",
        recurrence="weekly",
        weekday="montag",
    )
    assert result["success"] is True
    assert "montag" in result["message"].lower()
    redis_mock.hset.assert_called()
    redis_mock.sadd.assert_called()


@pytest.mark.asyncio
async def test_add_recurring_invalid_type(task_mgr):
    result = await task_mgr.add_recurring_task(
        title="Test",
        recurrence="hourly",
    )
    assert result["success"] is False


@pytest.mark.asyncio
async def test_add_recurring_weekly_no_weekday(task_mgr):
    result = await task_mgr.add_recurring_task(
        title="Test",
        recurrence="weekly",
    )
    assert result["success"] is False


@pytest.mark.asyncio
async def test_list_recurring_empty(task_mgr, redis_mock):
    redis_mock.smembers = AsyncMock(return_value=set())
    result = await task_mgr.list_recurring_tasks()
    assert result["success"] is True
    assert "Keine" in result["message"]


def test_context_hints():
    tm = TaskManager(AsyncMock())
    hints = tm.get_context_hints()
    assert len(hints) > 0
    assert "TaskManager" in hints[0]
