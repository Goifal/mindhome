"""Tests fuer NoteManager - Notiz-System."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from assistant.note_manager import NoteManager


@pytest.fixture
def redis_mock():
    mock = AsyncMock()
    mock.hset = AsyncMock()
    mock.zadd = AsyncMock()
    mock.sadd = AsyncMock()
    mock.zcard = AsyncMock(return_value=5)
    mock.zrevrange = AsyncMock(return_value=[])
    mock.zrangebyscore = AsyncMock(return_value=[])
    mock.smembers = AsyncMock(return_value=set())
    mock.scard = AsyncMock(return_value=0)
    mock.hgetall = AsyncMock(return_value={})
    mock.zrem = AsyncMock()
    mock.srem = AsyncMock()
    mock.delete = AsyncMock()

    pipe = MagicMock()
    pipe.hgetall = MagicMock()
    pipe.hget = MagicMock()
    pipe.execute = AsyncMock(return_value=[])
    mock.pipeline = MagicMock(return_value=pipe)

    return mock


@pytest.fixture
def note_mgr(redis_mock):
    nm = NoteManager()
    nm.redis = redis_mock
    return nm


@pytest.mark.asyncio
async def test_add_note_success(note_mgr, redis_mock):
    result = await note_mgr.add_note(
        content="Schluesseldienst: 0800-123456",
        category="haushalt",
    )
    assert result["success"] is True
    assert "note_id" in result
    redis_mock.hset.assert_called()
    redis_mock.zadd.assert_called()
    redis_mock.sadd.assert_called()


@pytest.mark.asyncio
async def test_add_note_empty_content(note_mgr):
    result = await note_mgr.add_note(content="")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_add_note_with_person(note_mgr, redis_mock):
    result = await note_mgr.add_note(
        content="Zahnarzt am Dienstag",
        category="gesundheit",
        person="lisa",
    )
    assert result["success"] is True
    assert redis_mock.sadd.call_count == 2


@pytest.mark.asyncio
async def test_add_note_invalid_category(note_mgr, redis_mock):
    """Ungueltige Kategorie -> Fallback auf 'sonstiges'."""
    result = await note_mgr.add_note(
        content="Test",
        category="invalid_cat",
    )
    assert result["success"] is True
    calls = redis_mock.sadd.call_args_list
    assert any("sonstiges" in str(c) for c in calls)


@pytest.mark.asyncio
async def test_list_notes_empty(note_mgr, redis_mock):
    result = await note_mgr.list_notes()
    assert result["success"] is True
    assert "Keine" in result["message"]


@pytest.mark.asyncio
async def test_search_notes_empty(note_mgr, redis_mock):
    result = await note_mgr.search_notes(query="test")
    assert result["success"] is True


@pytest.mark.asyncio
async def test_search_notes_no_query(note_mgr):
    result = await note_mgr.search_notes(query="")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_delete_note_not_found(note_mgr, redis_mock):
    result = await note_mgr.delete_note("nonexistent_id")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_delete_note_success(note_mgr, redis_mock):
    redis_mock.hgetall = AsyncMock(
        return_value={
            "id": "note_abc123",
            "content": "Test",
            "category": "haushalt",
            "person": "max",
        }
    )
    result = await note_mgr.delete_note("note_abc123")
    assert result["success"] is True
    redis_mock.delete.assert_called()
    redis_mock.zrem.assert_called()


@pytest.mark.asyncio
async def test_get_categories_empty(note_mgr, redis_mock):
    result = await note_mgr.get_note_categories()
    assert result["success"] is True
    assert "Noch keine" in result["message"]


def test_context_hints():
    nm = NoteManager()
    hints = nm.get_context_hints()
    assert len(hints) > 0
    assert "NoteManager" in hints[0]
