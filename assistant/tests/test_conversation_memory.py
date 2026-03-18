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


# =====================================================================
# Additional tests for 100% coverage
# =====================================================================


class TestCreateProjectExceptionPath:
    """Cover lines 101-103: exception in create_project."""

    @pytest.mark.asyncio
    async def test_create_project_redis_error(self, memory, mock_redis):
        mock_redis.hgetall.return_value = {}
        mock_redis.hlen.side_effect = Exception("Redis down")
        await memory.initialize(mock_redis)
        result = await memory.create_project("Test")
        assert result["success"] is False
        assert "Redis down" in result["message"]


class TestUpdateProjectEdgeCases:
    """Cover lines 116, 133, 151-152."""

    @pytest.mark.asyncio
    async def test_update_disabled(self, memory, mock_redis):
        memory.enabled = False
        await memory.initialize(mock_redis)
        result = await memory.update_project("Test", status="done")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_update_project_many_notes_trimmed(self, memory, mock_redis):
        """Cover line 133: notes trimmed to 20."""
        proj = {
            "id": "proj_1", "name": "Test", "status": "active",
            "notes": [{"text": f"note{i}", "date": "2025-01-01"} for i in range(20)],
            "milestones": [],
        }
        mock_redis.hgetall.return_value = {"proj_1": json.dumps(proj)}
        await memory.initialize(mock_redis)
        result = await memory.update_project("Test", note="Extra note")
        assert result["success"] is True
        # Check stored data has max 20 notes
        stored = json.loads(mock_redis.hset.call_args[0][2])
        assert len(stored["notes"]) == 20

    @pytest.mark.asyncio
    async def test_update_project_hset_error(self, memory, mock_redis):
        """Cover lines 151-152: exception in hset."""
        proj = {"id": "proj_1", "name": "Test", "status": "active", "notes": [], "milestones": []}
        mock_redis.hgetall.return_value = {"proj_1": json.dumps(proj)}
        mock_redis.hset.side_effect = Exception("Write fail")
        await memory.initialize(mock_redis)
        result = await memory.update_project("Test", status="done")
        assert result["success"] is False
        assert "Write fail" in result["message"]


class TestGetProjectsExceptionPath:
    """Cover lines 173-175."""

    @pytest.mark.asyncio
    async def test_get_projects_exception(self, memory, mock_redis):
        mock_redis.hgetall.side_effect = Exception("Redis error")
        await memory.initialize(mock_redis)
        result = await memory.get_projects()
        assert result == []


class TestDeleteProjectEdgeCases:
    """Cover lines 180, 189-190."""

    @pytest.mark.asyncio
    async def test_delete_disabled(self, memory, mock_redis):
        memory.enabled = False
        await memory.initialize(mock_redis)
        result = await memory.delete_project("Test")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_delete_hdel_error(self, memory, mock_redis):
        proj = {"id": "proj_1", "name": "Test", "status": "active"}
        mock_redis.hgetall.return_value = {"proj_1": json.dumps(proj)}
        mock_redis.hdel.side_effect = Exception("Delete fail")
        await memory.initialize(mock_redis)
        result = await memory.delete_project("Test")
        assert result["success"] is False
        assert "Delete fail" in result["message"]


class TestFindProjectEdgeCases:
    """Cover lines 195, 211-212."""

    @pytest.mark.asyncio
    async def test_find_project_no_redis(self, memory):
        await memory.initialize(None)
        result = await memory._find_project("Test")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_project_exception(self, memory, mock_redis):
        mock_redis.hgetall.side_effect = Exception("Fail")
        await memory.initialize(mock_redis)
        result = await memory._find_project("Test")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_project_no_match(self, memory, mock_redis):
        proj = {"id": "p1", "name": "Something else", "status": "active"}
        mock_redis.hgetall.return_value = {"p1": json.dumps(proj)}
        await memory.initialize(mock_redis)
        result = await memory._find_project("Nonexistent")
        assert result is None


class TestAddQuestionEdgeCases:
    """Cover lines 228, 255-256."""

    @pytest.mark.asyncio
    async def test_add_question_disabled(self, memory, mock_redis):
        memory.enabled = False
        await memory.initialize(mock_redis)
        result = await memory.add_question("Test?")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_add_question_exception(self, memory, mock_redis):
        mock_redis.hlen.side_effect = Exception("Fail")
        await memory.initialize(mock_redis)
        result = await memory.add_question("Test?")
        assert result["success"] is False
        assert "Fail" in result["message"]

    @pytest.mark.asyncio
    async def test_add_question_long_truncated_display(self, memory, mock_redis):
        """Question longer than 60 chars gets truncated in display."""
        await memory.initialize(mock_redis)
        long_q = "x" * 80
        result = await memory.add_question(long_q)
        assert result["success"] is True
        assert "..." in result["message"]


class TestAnswerQuestionEdgeCases:
    """Cover lines 266, 280-281."""

    @pytest.mark.asyncio
    async def test_answer_question_disabled(self, memory, mock_redis):
        memory.enabled = False
        await memory.initialize(mock_redis)
        result = await memory.answer_question("test", "answer")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_answer_question_hset_error(self, memory, mock_redis):
        q = {"id": "q_1", "question": "Was ist los?", "status": "open", "answer": ""}
        mock_redis.hgetall.return_value = {"q_1": json.dumps(q)}
        mock_redis.hset.side_effect = Exception("Write fail")
        await memory.initialize(mock_redis)
        result = await memory.answer_question("Was ist", "Antwort")
        assert result["success"] is False
        assert "Write fail" in result["message"]


class TestGetOpenQuestionsEdgeCases:
    """Cover lines 286, 297, 302-304."""

    @pytest.mark.asyncio
    async def test_disabled(self, memory, mock_redis):
        memory.enabled = False
        await memory.initialize(mock_redis)
        result = await memory.get_open_questions()
        assert result == []

    @pytest.mark.asyncio
    async def test_filter_by_person(self, memory, mock_redis):
        questions = {
            "q1": json.dumps({"id": "q1", "question": "A?", "status": "open", "person": "Max", "created_at": "2025-01-01"}),
            "q2": json.dumps({"id": "q2", "question": "B?", "status": "open", "person": "Anna", "created_at": "2025-01-02"}),
        }
        mock_redis.hgetall.return_value = questions
        await memory.initialize(mock_redis)
        result = await memory.get_open_questions(person="Max")
        assert len(result) == 1
        assert result[0]["person"] == "Max"

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self, memory, mock_redis):
        mock_redis.hgetall.side_effect = Exception("Fail")
        await memory.initialize(mock_redis)
        result = await memory.get_open_questions()
        assert result == []


class TestFindQuestionEdgeCases:
    """Cover lines 309, 319-320."""

    @pytest.mark.asyncio
    async def test_no_redis(self, memory):
        await memory.initialize(None)
        result = await memory._find_question("test")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_match(self, memory, mock_redis):
        mock_redis.hgetall.return_value = {
            "q1": json.dumps({"id": "q1", "question": "Something", "status": "open"}),
        }
        await memory.initialize(mock_redis)
        result = await memory._find_question("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_exception(self, memory, mock_redis):
        mock_redis.hgetall.side_effect = Exception("Fail")
        await memory.initialize(mock_redis)
        result = await memory._find_question("test")
        assert result is None


class TestCleanupOldQuestionsEdgeCases:
    """Cover lines 325, 341-342."""

    @pytest.mark.asyncio
    async def test_no_redis(self, memory):
        await memory.initialize(None)
        await memory._cleanup_old_questions()  # Should not raise

    @pytest.mark.asyncio
    async def test_exception(self, memory, mock_redis):
        mock_redis.hgetall.side_effect = Exception("Fail")
        await memory.initialize(mock_redis)
        await memory._cleanup_old_questions()  # Should not raise


class TestSaveDailySummaryEdgeCases:
    """Cover lines 358, 361, 375-376."""

    @pytest.mark.asyncio
    async def test_disabled(self, memory, mock_redis):
        memory.enabled = False
        await memory.initialize(mock_redis)
        result = await memory.save_daily_summary("test", ["a"])
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_default_date(self, memory, mock_redis):
        """Cover line 361: no date provided -> uses today."""
        await memory.initialize(mock_redis)
        result = await memory.save_daily_summary("test", ["a"])
        assert result["success"] is True
        today = datetime.now().strftime("%Y-%m-%d")
        key_used = mock_redis.set.call_args[0][0]
        assert today in key_used

    @pytest.mark.asyncio
    async def test_set_error(self, memory, mock_redis):
        mock_redis.set.side_effect = Exception("Write fail")
        await memory.initialize(mock_redis)
        result = await memory.save_daily_summary("test", ["a"], date="2025-01-01")
        assert result["success"] is False
        assert "Write fail" in result["message"]


class TestGetDailySummaryEdgeCases:
    """Cover lines 381, 384, 392-393."""

    @pytest.mark.asyncio
    async def test_disabled(self, memory, mock_redis):
        memory.enabled = False
        await memory.initialize(mock_redis)
        result = await memory.get_daily_summary()
        assert result is None

    @pytest.mark.asyncio
    async def test_default_date(self, memory, mock_redis):
        """Cover line 384: no date -> uses today."""
        entry = json.dumps({"date": "today", "summary": "Test", "topics": []})
        mock_redis.get.return_value = entry
        await memory.initialize(mock_redis)
        result = await memory.get_daily_summary()
        assert result is not None

    @pytest.mark.asyncio
    async def test_exception(self, memory, mock_redis):
        mock_redis.get.side_effect = Exception("Fail")
        await memory.initialize(mock_redis)
        result = await memory.get_daily_summary("2025-01-01")
        assert result is None

    @pytest.mark.asyncio
    async def test_bytes_response(self, memory, mock_redis):
        entry = json.dumps({"date": "2025-01-01", "summary": "Test", "topics": []})
        mock_redis.get.return_value = entry.encode("utf-8")
        await memory.initialize(mock_redis)
        result = await memory.get_daily_summary("2025-01-01")
        assert result is not None
        assert result["summary"] == "Test"


class TestGetRecentSummariesEdgeCases:
    """Cover line 398."""

    @pytest.mark.asyncio
    async def test_disabled(self, memory, mock_redis):
        memory.enabled = False
        await memory.initialize(mock_redis)
        result = await memory.get_recent_summaries()
        assert result == []


class TestGetProjectsBytesHandling:
    """Cover bytes decoding in get_projects."""

    @pytest.mark.asyncio
    async def test_bytes_values(self, memory, mock_redis):
        proj = {"id": "p1", "name": "Test", "status": "active", "person": "", "updated_at": "2025-01-01"}
        mock_redis.hgetall.return_value = {"p1": json.dumps(proj).encode("utf-8")}
        await memory.initialize(mock_redis)
        result = await memory.get_projects()
        assert len(result) == 1


class TestFindProjectBytesHandling:
    """Cover bytes decoding in _find_project."""

    @pytest.mark.asyncio
    async def test_bytes_values(self, memory, mock_redis):
        proj = {"id": "p1", "name": "Test", "status": "active"}
        mock_redis.hgetall.return_value = {"p1": json.dumps(proj).encode("utf-8")}
        await memory.initialize(mock_redis)
        result = await memory._find_project("Test")
        assert result is not None


# ============================================================
# Phase 3B: Gesprächs-Threads
# ============================================================

class TestPhase3BThreads:
    """Tests fuer Gespraechs-Thread-System."""

    @pytest.fixture
    def memory(self, mock_redis):
        m = ConversationMemory()
        m.redis = mock_redis
        m.enabled = True
        return m

    @pytest.mark.asyncio
    async def test_create_thread(self, memory, mock_redis):
        result = await memory.create_thread("Heizungseffizienz", "session_1")
        assert result.get("topic") == "Heizungseffizienz"
        assert "session_1" in result.get("session_ids", [])
        mock_redis.hset.assert_called()

    @pytest.mark.asyncio
    async def test_create_thread_no_redis(self, memory):
        memory.redis = None
        result = await memory.create_thread("Test")
        assert result == {}

    @pytest.mark.asyncio
    async def test_create_thread_empty_topic(self, memory):
        result = await memory.create_thread("")
        assert result == {}

    def test_extract_keywords(self):
        kw = ConversationMemory._extract_topic_keywords("Die Heizung im Schlafzimmer ist ineffizient")
        assert "heizung" in kw
        assert "schlafzimmer" in kw
        assert "die" not in kw

    def test_extract_keywords_empty(self):
        assert ConversationMemory._extract_topic_keywords("") == []

    @pytest.mark.asyncio
    async def test_get_thread_context_no_redis(self, memory):
        memory.redis = None
        result = await memory.get_thread_context("test")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_recent_threads_empty(self, memory, mock_redis):
        mock_redis.hgetall = AsyncMock(return_value={})
        result = await memory.get_recent_threads()
        assert result == []

    @pytest.mark.asyncio
    async def test_auto_detect_short_text(self, memory):
        await memory.auto_detect_thread("Hi")
        # Kein Fehler

    @pytest.mark.asyncio
    async def test_link_session_no_topic(self, memory):
        result = await memory.link_session_to_thread("s1", "")
        assert result is None
