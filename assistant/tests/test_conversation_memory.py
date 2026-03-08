"""Tests for assistant.conversation_memory module."""

import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timedelta

from assistant.conversation_memory import ConversationMemory


@pytest.fixture
def mock_redis():
    """Create a mock async Redis client."""
    r = AsyncMock()
    r.hlen = AsyncMock(return_value=0)
    r.hset = AsyncMock()
    r.hdel = AsyncMock()
    r.hgetall = AsyncMock(return_value={})
    r.get = AsyncMock(return_value=None)
    r.set = AsyncMock()
    r.expire = AsyncMock()
    return r


@pytest.fixture
def memory():
    with patch("assistant.conversation_memory.yaml_config", {"conversation_memory": {"enabled": True, "max_projects": 5, "max_questions": 3, "question_ttl_days": 14, "summary_retention_days": 30}}):
        return ConversationMemory()


# ------------------------------------------------------------------
# Project Tracking
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_project_success(memory, mock_redis):
    await memory.initialize(mock_redis)
    result = await memory.create_project("Gartenhaus", description="Holz", person="Max")
    assert result["success"] is True
    assert "project_id" in result
    mock_redis.hset.assert_called_once()


@pytest.mark.asyncio
async def test_create_project_disabled(memory, mock_redis):
    memory.enabled = False
    await memory.initialize(mock_redis)
    result = await memory.create_project("Test")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_create_project_no_redis(memory):
    await memory.initialize(None)
    result = await memory.create_project("Test")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_create_project_empty_name(memory, mock_redis):
    await memory.initialize(mock_redis)
    result = await memory.create_project("  ")
    assert result["success"] is False
    assert "leer" in result["message"]


@pytest.mark.asyncio
async def test_create_project_duplicate(memory, mock_redis):
    existing = {"name": "Gartenhaus", "status": "active", "id": "proj_1"}
    mock_redis.hgetall.return_value = {"proj_1": json.dumps(existing)}
    await memory.initialize(mock_redis)
    result = await memory.create_project("Gartenhaus")
    assert result["success"] is False
    assert "existiert bereits" in result["message"]


@pytest.mark.asyncio
async def test_create_project_max_limit(memory, mock_redis):
    mock_redis.hlen.return_value = 5  # max_projects=5
    mock_redis.hgetall.return_value = {}
    await memory.initialize(mock_redis)
    result = await memory.create_project("Neues Projekt")
    assert result["success"] is False
    assert "Maximale" in result["message"]


@pytest.mark.asyncio
async def test_update_project_status(memory, mock_redis):
    proj = {"id": "proj_1", "name": "Test", "status": "active", "notes": [], "milestones": []}
    mock_redis.hgetall.return_value = {"proj_1": json.dumps(proj)}
    await memory.initialize(mock_redis)
    result = await memory.update_project("Test", status="done")
    assert result["success"] is True
    assert "done" in result["message"]


@pytest.mark.asyncio
async def test_update_project_note_and_milestone(memory, mock_redis):
    proj = {"id": "proj_1", "name": "Test", "status": "active", "notes": [], "milestones": []}
    mock_redis.hgetall.return_value = {"proj_1": json.dumps(proj)}
    await memory.initialize(mock_redis)
    result = await memory.update_project("Test", note="Progress", milestone="Phase 1")
    assert result["success"] is True
    assert "Notiz" in result["message"]
    assert "Meilenstein" in result["message"]


@pytest.mark.asyncio
async def test_update_project_not_found(memory, mock_redis):
    mock_redis.hgetall.return_value = {}
    await memory.initialize(mock_redis)
    result = await memory.update_project("NonExistent")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_update_project_no_changes(memory, mock_redis):
    proj = {"id": "proj_1", "name": "Test", "status": "active", "notes": [], "milestones": []}
    mock_redis.hgetall.return_value = {"proj_1": json.dumps(proj)}
    await memory.initialize(mock_redis)
    result = await memory.update_project("Test")
    assert result["success"] is False
    assert "Keine Aenderung" in result["message"]


@pytest.mark.asyncio
async def test_get_projects_filters(memory, mock_redis):
    projects = {
        "p1": json.dumps({"id": "p1", "name": "A", "status": "active", "person": "Max", "updated_at": "2025-01-02"}),
        "p2": json.dumps({"id": "p2", "name": "B", "status": "done", "person": "Anna", "updated_at": "2025-01-01"}),
    }
    mock_redis.hgetall.return_value = projects
    await memory.initialize(mock_redis)

    all_projects = await memory.get_projects()
    assert len(all_projects) == 2

    active = await memory.get_projects(status="active")
    assert len(active) == 1
    assert active[0]["name"] == "A"

    by_person = await memory.get_projects(person="Anna")
    assert len(by_person) == 1
    assert by_person[0]["name"] == "B"


@pytest.mark.asyncio
async def test_get_projects_disabled(memory, mock_redis):
    memory.enabled = False
    await memory.initialize(mock_redis)
    assert await memory.get_projects() == []


@pytest.mark.asyncio
async def test_delete_project(memory, mock_redis):
    proj = {"id": "proj_1", "name": "Test", "status": "active"}
    mock_redis.hgetall.return_value = {"proj_1": json.dumps(proj)}
    await memory.initialize(mock_redis)
    result = await memory.delete_project("Test")
    assert result["success"] is True
    mock_redis.hdel.assert_called_once()


@pytest.mark.asyncio
async def test_delete_project_not_found(memory, mock_redis):
    mock_redis.hgetall.return_value = {}
    await memory.initialize(mock_redis)
    result = await memory.delete_project("Ghost")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_find_project_partial_match(memory, mock_redis):
    proj = {"id": "p1", "name": "Gartenhaus bauen", "status": "active"}
    mock_redis.hgetall.return_value = {"p1": json.dumps(proj)}
    await memory.initialize(mock_redis)
    found = await memory._find_project("Garten")
    assert found is not None
    assert found["name"] == "Gartenhaus bauen"


# ------------------------------------------------------------------
# Open Questions
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_question_success(memory, mock_redis):
    await memory.initialize(mock_redis)
    result = await memory.add_question("Was ist los?", context="Test", person="Max")
    assert result["success"] is True
    mock_redis.hset.assert_called_once()


@pytest.mark.asyncio
async def test_add_question_empty(memory, mock_redis):
    await memory.initialize(mock_redis)
    result = await memory.add_question("  ")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_add_question_triggers_cleanup(memory, mock_redis):
    mock_redis.hlen.return_value = 3  # max_questions=3
    mock_redis.hgetall.return_value = {}
    await memory.initialize(mock_redis)
    result = await memory.add_question("New question")
    assert result["success"] is True


@pytest.mark.asyncio
async def test_answer_question(memory, mock_redis):
    q = {"id": "q_1", "question": "Was ist los?", "status": "open", "answer": ""}
    mock_redis.hgetall.return_value = {"q_1": json.dumps(q)}
    await memory.initialize(mock_redis)
    result = await memory.answer_question("Was ist", "Alles gut")
    assert result["success"] is True


@pytest.mark.asyncio
async def test_answer_question_not_found(memory, mock_redis):
    mock_redis.hgetall.return_value = {}
    await memory.initialize(mock_redis)
    result = await memory.answer_question("nope", "answer")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_get_open_questions(memory, mock_redis):
    questions = {
        "q1": json.dumps({"id": "q1", "question": "A?", "status": "open", "person": "Max", "created_at": "2025-01-01"}),
        "q2": json.dumps({"id": "q2", "question": "B?", "status": "answered", "person": "Max", "created_at": "2025-01-02"}),
    }
    mock_redis.hgetall.return_value = questions
    await memory.initialize(mock_redis)
    open_q = await memory.get_open_questions()
    assert len(open_q) == 1
    assert open_q[0]["question"] == "A?"


@pytest.mark.asyncio
async def test_cleanup_old_questions(memory, mock_redis):
    old_date = (datetime.now() - timedelta(days=30)).isoformat()
    questions = {
        b"q1": json.dumps({"id": "q1", "status": "answered", "answered_at": old_date, "created_at": old_date}),
        b"q2": json.dumps({"id": "q2", "status": "open", "created_at": old_date}),
    }
    mock_redis.hgetall.return_value = questions
    await memory.initialize(mock_redis)
    await memory._cleanup_old_questions()
    assert mock_redis.hdel.call_count == 2


# ------------------------------------------------------------------
# Daily Summaries
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_daily_summary(memory, mock_redis):
    await memory.initialize(mock_redis)
    result = await memory.save_daily_summary("Guter Tag", ["Garten", "Kochen"], date="2025-03-01")
    assert result["success"] is True
    mock_redis.set.assert_called_once()
    mock_redis.expire.assert_called_once()


@pytest.mark.asyncio
async def test_get_daily_summary(memory, mock_redis):
    entry = json.dumps({"date": "2025-03-01", "summary": "Test", "topics": ["A"]})
    mock_redis.get.return_value = entry
    await memory.initialize(mock_redis)
    result = await memory.get_daily_summary("2025-03-01")
    assert result is not None
    assert result["summary"] == "Test"


@pytest.mark.asyncio
async def test_get_daily_summary_none(memory, mock_redis):
    mock_redis.get.return_value = None
    await memory.initialize(mock_redis)
    result = await memory.get_daily_summary("2025-03-01")
    assert result is None


@pytest.mark.asyncio
async def test_get_recent_summaries(memory, mock_redis):
    entry = json.dumps({"date": "2025-03-01", "summary": "Test", "topics": []})
    # Return data only for the first call, None for the rest
    mock_redis.get.side_effect = [entry] + [None] * 6
    await memory.initialize(mock_redis)
    results = await memory.get_recent_summaries(days=7)
    assert len(results) == 1


# ------------------------------------------------------------------
# Memory Context
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_memory_context_empty(memory, mock_redis):
    mock_redis.hgetall.return_value = {}
    mock_redis.get.return_value = None
    await memory.initialize(mock_redis)
    ctx = await memory.get_memory_context()
    assert ctx == ""


@pytest.mark.asyncio
async def test_get_memory_context_with_data(memory, mock_redis):
    projects = {"p1": json.dumps({"id": "p1", "name": "Garten", "status": "active", "milestones": [1, 2], "updated_at": "2025-01-01"})}
    questions = {"q1": json.dumps({"id": "q1", "question": "Was ist mit dem Rasen?", "status": "open", "created_at": "2025-01-01"})}
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    summary = json.dumps({"date": yesterday, "summary": "Test", "topics": ["Garten"]})

    # hgetall is called for both projects and questions
    mock_redis.hgetall.side_effect = [projects, questions]
    mock_redis.get.return_value = summary
    await memory.initialize(mock_redis)
    ctx = await memory.get_memory_context()
    assert "Garten" in ctx
    assert "Offene Fragen" in ctx
    assert "Gestern" in ctx
