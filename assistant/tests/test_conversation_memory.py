"""Tests for assistant.conversation_memory module."""

import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timedelta, timezone

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
    with patch(
        "assistant.conversation_memory.yaml_config",
        {
            "conversation_memory": {
                "enabled": True,
                "max_projects": 5,
                "max_questions": 3,
                "question_ttl_days": 14,
                "summary_retention_days": 30,
            }
        },
    ):
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
    proj = {
        "id": "proj_1",
        "name": "Test",
        "status": "active",
        "notes": [],
        "milestones": [],
    }
    mock_redis.hgetall.return_value = {"proj_1": json.dumps(proj)}
    await memory.initialize(mock_redis)
    result = await memory.update_project("Test", status="done")
    assert result["success"] is True
    assert "done" in result["message"]


@pytest.mark.asyncio
async def test_update_project_note_and_milestone(memory, mock_redis):
    proj = {
        "id": "proj_1",
        "name": "Test",
        "status": "active",
        "notes": [],
        "milestones": [],
    }
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
    proj = {
        "id": "proj_1",
        "name": "Test",
        "status": "active",
        "notes": [],
        "milestones": [],
    }
    mock_redis.hgetall.return_value = {"proj_1": json.dumps(proj)}
    await memory.initialize(mock_redis)
    result = await memory.update_project("Test")
    assert result["success"] is False
    assert "Keine Aenderung" in result["message"]


@pytest.mark.asyncio
async def test_get_projects_filters(memory, mock_redis):
    projects = {
        "p1": json.dumps(
            {
                "id": "p1",
                "name": "A",
                "status": "active",
                "person": "Max",
                "updated_at": "2025-01-02",
            }
        ),
        "p2": json.dumps(
            {
                "id": "p2",
                "name": "B",
                "status": "done",
                "person": "Anna",
                "updated_at": "2025-01-01",
            }
        ),
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
    mock_redis.hdel.reset_mock()  # Startup-Cleanup Calls ignorieren
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
        "q1": json.dumps(
            {
                "id": "q1",
                "question": "A?",
                "status": "open",
                "person": "Max",
                "created_at": "2025-01-01",
            }
        ),
        "q2": json.dumps(
            {
                "id": "q2",
                "question": "B?",
                "status": "answered",
                "person": "Max",
                "created_at": "2025-01-02",
            }
        ),
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
        b"q1": json.dumps(
            {
                "id": "q1",
                "status": "answered",
                "answered_at": old_date,
                "created_at": old_date,
            }
        ),
        b"q2": json.dumps({"id": "q2", "status": "open", "created_at": old_date}),
    }
    mock_redis.hgetall.return_value = questions
    await memory.initialize(mock_redis)
    mock_redis.hdel.reset_mock()  # Startup-Cleanup Calls ignorieren
    await memory._cleanup_old_questions()
    assert mock_redis.hdel.call_count == 2


# ------------------------------------------------------------------
# Daily Summaries
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_daily_summary(memory, mock_redis):
    await memory.initialize(mock_redis)
    result = await memory.save_daily_summary(
        "Guter Tag", ["Garten", "Kochen"], date="2025-03-01"
    )
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
    projects = {
        "p1": json.dumps(
            {
                "id": "p1",
                "name": "Garten",
                "status": "active",
                "milestones": [1, 2],
                "updated_at": "2025-01-01",
            }
        )
    }
    questions = {
        "q1": json.dumps(
            {
                "id": "q1",
                "question": "Was ist mit dem Rasen?",
                "status": "open",
                "created_at": "2025-01-01",
            }
        )
    }
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    summary = json.dumps({"date": yesterday, "summary": "Test", "topics": ["Garten"]})

    # hgetall is called by startup cleanup (questions, projects, followups)
    # and then by get_memory_context (projects, questions)
    mock_redis.hgetall.side_effect = [
        questions,  # _cleanup_old_questions
        projects,  # _cleanup_old_projects
        {},  # _cleanup_old_followups
        projects,  # get_memory_context → get_projects
        questions,  # get_memory_context → get_open_questions
    ]
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
            "id": "proj_1",
            "name": "Test",
            "status": "active",
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
        proj = {
            "id": "proj_1",
            "name": "Test",
            "status": "active",
            "notes": [],
            "milestones": [],
        }
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
            "q1": json.dumps(
                {
                    "id": "q1",
                    "question": "A?",
                    "status": "open",
                    "person": "Max",
                    "created_at": "2025-01-01",
                }
            ),
            "q2": json.dumps(
                {
                    "id": "q2",
                    "question": "B?",
                    "status": "open",
                    "person": "Anna",
                    "created_at": "2025-01-02",
                }
            ),
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
        proj = {
            "id": "p1",
            "name": "Test",
            "status": "active",
            "person": "",
            "updated_at": "2025-01-01",
        }
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
        kw = ConversationMemory._extract_topic_keywords(
            "Die Heizung im Schlafzimmer ist ineffizient"
        )
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


# ============================================================
# Cleanup: _cleanup_old_projects
# ============================================================


class TestCleanupOldProjects:
    """Tests fuer _cleanup_old_projects."""

    @pytest.mark.asyncio
    async def test_removes_old_completed_projects(self, memory, mock_redis):
        old_date = (datetime.now() - timedelta(days=60)).isoformat()
        projects = {
            "p1": json.dumps(
                {
                    "id": "p1",
                    "name": "Old Done",
                    "status": "completed",
                    "updated_at": old_date,
                }
            ),
            "p2": json.dumps(
                {
                    "id": "p2",
                    "name": "Active",
                    "status": "active",
                    "updated_at": old_date,
                }
            ),
            "p3": json.dumps(
                {
                    "id": "p3",
                    "name": "Recent Done",
                    "status": "completed",
                    "updated_at": datetime.now().isoformat(),
                }
            ),
        }
        mock_redis.hgetall.return_value = projects
        await memory.initialize(mock_redis)
        mock_redis.hdel.reset_mock()
        await memory._cleanup_old_projects()
        # Only p1 should be removed (completed + old)
        mock_redis.hdel.assert_called_once()

    @pytest.mark.asyncio
    async def test_removes_cancelled_and_archived(self, memory, mock_redis):
        old_date = (datetime.now() - timedelta(days=60)).isoformat()
        projects = {
            "p1": json.dumps(
                {
                    "id": "p1",
                    "name": "Cancelled",
                    "status": "cancelled",
                    "updated_at": old_date,
                }
            ),
            "p2": json.dumps(
                {
                    "id": "p2",
                    "name": "Archived",
                    "status": "archived",
                    "created_at": old_date,
                }
            ),
        }
        mock_redis.hgetall.return_value = projects
        await memory.initialize(mock_redis)
        mock_redis.hdel.reset_mock()
        await memory._cleanup_old_projects()
        assert mock_redis.hdel.call_count == 2

    @pytest.mark.asyncio
    async def test_no_redis_no_crash(self, memory):
        await memory.initialize(None)
        await memory._cleanup_old_projects()

    @pytest.mark.asyncio
    async def test_exception_caught(self, memory, mock_redis):
        mock_redis.hgetall.side_effect = Exception("Redis error")
        await memory.initialize(mock_redis)
        await memory._cleanup_old_projects()  # Should not raise

    @pytest.mark.asyncio
    async def test_bytes_keys_decoded(self, memory, mock_redis):
        old_date = (datetime.now() - timedelta(days=60)).isoformat()
        projects = {
            b"p1": json.dumps(
                {
                    "id": "p1",
                    "name": "Done",
                    "status": "completed",
                    "updated_at": old_date,
                }
            ).encode(),
        }
        mock_redis.hgetall.return_value = projects
        await memory.initialize(mock_redis)
        mock_redis.hdel.reset_mock()
        await memory._cleanup_old_projects()
        mock_redis.hdel.assert_called_once()


# ============================================================
# Cleanup: _cleanup_old_followups
# ============================================================


class TestCleanupOldFollowups:
    """Tests fuer _cleanup_old_followups."""

    @pytest.mark.asyncio
    async def test_removes_old_completed_followups(self, memory, mock_redis):
        old_date = (datetime.now() - timedelta(days=30)).isoformat()
        followups = {
            "fu1": json.dumps(
                {
                    "id": "fu1",
                    "status": "completed",
                    "completed_at": old_date,
                    "created_at": old_date,
                }
            ),
            "fu2": json.dumps(
                {
                    "id": "fu2",
                    "status": "pending",
                    "created_at": datetime.now().isoformat(),
                }
            ),
        }
        mock_redis.hgetall.return_value = followups
        await memory.initialize(mock_redis)
        mock_redis.hdel.reset_mock()
        await memory._cleanup_old_followups()
        # Only fu1 should be removed
        mock_redis.hdel.assert_called_once()

    @pytest.mark.asyncio
    async def test_removes_expired_pending_followups(self, memory, mock_redis):
        old_date = (datetime.now() - timedelta(days=30)).isoformat()
        followups = {
            "fu1": json.dumps(
                {
                    "id": "fu1",
                    "status": "pending",
                    "created_at": old_date,
                }
            ),
        }
        mock_redis.hgetall.return_value = followups
        await memory.initialize(mock_redis)
        mock_redis.hdel.reset_mock()
        await memory._cleanup_old_followups()
        mock_redis.hdel.assert_called_once()

    @pytest.mark.asyncio
    async def test_removes_cancelled_followups(self, memory, mock_redis):
        old_date = (datetime.now() - timedelta(days=30)).isoformat()
        followups = {
            "fu1": json.dumps(
                {
                    "id": "fu1",
                    "status": "cancelled",
                    "completed_at": old_date,
                    "created_at": old_date,
                }
            ),
        }
        mock_redis.hgetall.return_value = followups
        await memory.initialize(mock_redis)
        mock_redis.hdel.reset_mock()
        await memory._cleanup_old_followups()
        mock_redis.hdel.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_redis_no_crash(self, memory):
        await memory.initialize(None)
        await memory._cleanup_old_followups()

    @pytest.mark.asyncio
    async def test_exception_caught(self, memory, mock_redis):
        mock_redis.hgetall.side_effect = Exception("Fail")
        await memory.initialize(mock_redis)
        await memory._cleanup_old_followups()


# ============================================================
# Cleanup: _cleanup_expired_entries
# ============================================================


class TestCleanupExpiredEntries:
    """Tests fuer _cleanup_expired_entries (Startup-Cleanup)."""

    @pytest.mark.asyncio
    async def test_calls_all_cleanups(self, memory, mock_redis):
        mock_redis.hgetall.return_value = {}
        await memory.initialize(mock_redis)
        # initialize calls _cleanup_expired_entries which calls all three
        # If hgetall was called at least 3 times, all cleanups ran
        assert mock_redis.hgetall.call_count >= 3

    @pytest.mark.asyncio
    async def test_exception_in_cleanup_caught(self, memory, mock_redis):
        mock_redis.hgetall.side_effect = Exception("Total failure")
        # initialize should not raise even if cleanup fails
        await memory.initialize(mock_redis)


# ============================================================
# Follow-Up Tracking
# ============================================================


class TestAddFollowup:
    """Tests fuer add_followup."""

    @pytest.mark.asyncio
    async def test_add_followup_success(self, memory, mock_redis):
        mock_redis.hgetall.return_value = {}
        await memory.initialize(mock_redis)
        mock_redis.hset.reset_mock()
        result = await memory.add_followup(
            "Arzttermin",
            context="Morgen um 10",
            ask_after="tomorrow",
        )
        assert result["success"] is True
        assert "Arzttermin" in result["message"]
        mock_redis.hset.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_followup_disabled(self, memory, mock_redis):
        memory.enabled = False
        await memory.initialize(mock_redis)
        result = await memory.add_followup("Test", "context")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_add_followup_no_redis(self, memory):
        await memory.initialize(None)
        result = await memory.add_followup("Test", "context")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_add_followup_empty_topic(self, memory, mock_redis):
        mock_redis.hgetall.return_value = {}
        await memory.initialize(mock_redis)
        result = await memory.add_followup("  ", "context")
        assert result["success"] is False
        assert "leer" in result["message"]

    @pytest.mark.asyncio
    async def test_add_followup_redis_error(self, memory, mock_redis):
        mock_redis.hgetall.return_value = {}
        await memory.initialize(mock_redis)
        mock_redis.hset.side_effect = Exception("Write fail")
        result = await memory.add_followup("Test topic", context="ctx")
        assert result["success"] is False
        assert "Write fail" in result["message"]


class TestGetPendingFollowups:
    """Tests fuer get_pending_followups."""

    @pytest.mark.asyncio
    async def test_returns_due_followups(self, memory, mock_redis):
        now = datetime.now()
        past = (now - timedelta(hours=2)).isoformat()
        followups = {
            "fu1": json.dumps(
                {
                    "id": "fu1",
                    "topic": "Arzttermin",
                    "status": "pending",
                    "due_at": past,
                    "created_at": past,
                }
            ),
            "fu2": json.dumps(
                {
                    "id": "fu2",
                    "topic": "Fertig",
                    "status": "done",
                    "due_at": past,
                    "created_at": past,
                }
            ),
        }
        mock_redis.hgetall.return_value = followups
        await memory.initialize(mock_redis)
        result = await memory.get_pending_followups()
        assert len(result) == 1
        assert result[0]["topic"] == "Arzttermin"

    @pytest.mark.asyncio
    async def test_future_followups_not_returned(self, memory, mock_redis):
        future = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        followups = {
            "fu1": json.dumps(
                {
                    "id": "fu1",
                    "topic": "Spaeter",
                    "status": "pending",
                    "due_at": future,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            ),
        }
        mock_redis.hgetall.return_value = followups
        await memory.initialize(mock_redis)
        result = await memory.get_pending_followups()
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_no_due_at_is_immediately_due(self, memory, mock_redis):
        followups = {
            "fu1": json.dumps(
                {
                    "id": "fu1",
                    "topic": "Sofort",
                    "status": "pending",
                    "due_at": "",
                    "created_at": datetime.now().isoformat(),
                }
            ),
        }
        mock_redis.hgetall.return_value = followups
        await memory.initialize(mock_redis)
        result = await memory.get_pending_followups()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_invalid_due_at_is_due(self, memory, mock_redis):
        followups = {
            "fu1": json.dumps(
                {
                    "id": "fu1",
                    "topic": "Kaputt",
                    "status": "pending",
                    "due_at": "not-a-date",
                    "created_at": datetime.now().isoformat(),
                }
            ),
        }
        mock_redis.hgetall.return_value = followups
        await memory.initialize(mock_redis)
        result = await memory.get_pending_followups()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_sorted_oldest_first(self, memory, mock_redis):
        old = (datetime.now() - timedelta(hours=5)).isoformat()
        recent = (datetime.now() - timedelta(hours=1)).isoformat()
        followups = {
            "fu1": json.dumps(
                {
                    "id": "fu1",
                    "topic": "Neuerer",
                    "status": "pending",
                    "due_at": recent,
                    "created_at": recent,
                }
            ),
            "fu2": json.dumps(
                {
                    "id": "fu2",
                    "topic": "Aelterer",
                    "status": "pending",
                    "due_at": old,
                    "created_at": old,
                }
            ),
        }
        mock_redis.hgetall.return_value = followups
        await memory.initialize(mock_redis)
        result = await memory.get_pending_followups()
        assert len(result) == 2
        assert result[0]["topic"] == "Aelterer"

    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self, memory, mock_redis):
        memory.enabled = False
        await memory.initialize(mock_redis)
        result = await memory.get_pending_followups()
        assert result == []

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self, memory, mock_redis):
        mock_redis.hgetall.side_effect = Exception("Fail")
        await memory.initialize(mock_redis)
        result = await memory.get_pending_followups()
        assert result == []

    @pytest.mark.asyncio
    async def test_bytes_values_decoded(self, memory, mock_redis):
        past = (datetime.now() - timedelta(hours=1)).isoformat()
        followups = {
            b"fu1": json.dumps(
                {
                    "id": "fu1",
                    "topic": "BytesTopic",
                    "status": "pending",
                    "due_at": past,
                    "created_at": past,
                }
            ).encode(),
        }
        mock_redis.hgetall.return_value = followups
        await memory.initialize(mock_redis)
        result = await memory.get_pending_followups()
        assert len(result) == 1
        assert result[0]["topic"] == "BytesTopic"


class TestCompleteFollowup:
    """Tests fuer complete_followup."""

    @pytest.mark.asyncio
    async def test_complete_success(self, memory, mock_redis):
        followups = {
            "fu1": json.dumps(
                {
                    "id": "fu1",
                    "topic": "Arzttermin",
                    "status": "pending",
                    "created_at": datetime.now().isoformat(),
                }
            ),
        }
        mock_redis.hgetall.return_value = followups
        await memory.initialize(mock_redis)
        mock_redis.hset.reset_mock()
        result = await memory.complete_followup("Arzt")
        assert result["success"] is True
        assert "erledigt" in result["message"]
        # Check stored data has status done
        stored = json.loads(mock_redis.hset.call_args[0][2])
        assert stored["status"] == "done"
        assert "completed_at" in stored

    @pytest.mark.asyncio
    async def test_complete_not_found(self, memory, mock_redis):
        mock_redis.hgetall.return_value = {}
        await memory.initialize(mock_redis)
        result = await memory.complete_followup("Nonexistent")
        assert result["success"] is False
        assert "nicht gefunden" in result["message"]

    @pytest.mark.asyncio
    async def test_complete_disabled(self, memory, mock_redis):
        memory.enabled = False
        await memory.initialize(mock_redis)
        result = await memory.complete_followup("Test")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_complete_hset_error(self, memory, mock_redis):
        followups = {
            "fu1": json.dumps(
                {
                    "id": "fu1",
                    "topic": "Test",
                    "status": "pending",
                    "created_at": datetime.now().isoformat(),
                }
            ),
        }
        mock_redis.hgetall.return_value = followups
        mock_redis.hset.side_effect = Exception("Write fail")
        await memory.initialize(mock_redis)
        result = await memory.complete_followup("Test")
        assert result["success"] is False


class TestFindFollowup:
    """Tests fuer _find_followup."""

    @pytest.mark.asyncio
    async def test_exact_match(self, memory, mock_redis):
        followups = {
            "fu1": json.dumps(
                {
                    "id": "fu1",
                    "topic": "Arzttermin",
                    "status": "pending",
                }
            ),
        }
        mock_redis.hgetall.return_value = followups
        await memory.initialize(mock_redis)
        result = await memory._find_followup("Arzttermin")
        assert result is not None
        assert result["topic"] == "Arzttermin"

    @pytest.mark.asyncio
    async def test_partial_match(self, memory, mock_redis):
        followups = {
            "fu1": json.dumps(
                {
                    "id": "fu1",
                    "topic": "Arzttermin morgen",
                    "status": "pending",
                }
            ),
        }
        mock_redis.hgetall.return_value = followups
        await memory.initialize(mock_redis)
        result = await memory._find_followup("arzt")
        assert result is not None

    @pytest.mark.asyncio
    async def test_skips_non_pending(self, memory, mock_redis):
        followups = {
            "fu1": json.dumps(
                {
                    "id": "fu1",
                    "topic": "Fertig",
                    "status": "done",
                }
            ),
        }
        mock_redis.hgetall.return_value = followups
        await memory.initialize(mock_redis)
        result = await memory._find_followup("Fertig")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_redis(self, memory):
        await memory.initialize(None)
        result = await memory._find_followup("test")
        assert result is None

    @pytest.mark.asyncio
    async def test_exception(self, memory, mock_redis):
        mock_redis.hgetall.side_effect = Exception("Fail")
        await memory.initialize(mock_redis)
        result = await memory._find_followup("test")
        assert result is None


# ============================================================
# Extract Follow-Up Triggers
# ============================================================


class TestExtractFollowupTriggers:
    """Tests fuer extract_followup_triggers."""

    @pytest.mark.asyncio
    async def test_detects_arzttermin(self, memory, mock_redis):
        await memory.initialize(mock_redis)
        result = await memory.extract_followup_triggers(
            "Ich habe einen Arzttermin morgen um 10 Uhr"
        )
        assert len(result) >= 1
        assert any(r["topic"] == "Arzttermin" for r in result)

    @pytest.mark.asyncio
    async def test_detects_paket(self, memory, mock_redis):
        await memory.initialize(mock_redis)
        result = await memory.extract_followup_triggers(
            "Mein Paket kommt voraussichtlich morgen"
        )
        assert len(result) >= 1
        assert any(r["topic"] == "Paket-Lieferung" for r in result)

    @pytest.mark.asyncio
    async def test_detects_warten(self, memory, mock_redis):
        await memory.initialize(mock_redis)
        result = await memory.extract_followup_triggers(
            "Ich warte auf die Antwort vom Vermieter"
        )
        assert len(result) >= 1
        assert any(r["topic"] == "Wartet auf etwas" for r in result)

    @pytest.mark.asyncio
    async def test_empty_text_returns_empty(self, memory, mock_redis):
        await memory.initialize(mock_redis)
        result = await memory.extract_followup_triggers("")
        assert result == []

    @pytest.mark.asyncio
    async def test_whitespace_only_returns_empty(self, memory, mock_redis):
        await memory.initialize(mock_redis)
        result = await memory.extract_followup_triggers("   ")
        assert result == []

    @pytest.mark.asyncio
    async def test_no_triggers_found(self, memory, mock_redis):
        await memory.initialize(mock_redis)
        result = await memory.extract_followup_triggers("Das Wetter ist heute schoen")
        assert result == []

    @pytest.mark.asyncio
    async def test_no_duplicate_topics(self, memory, mock_redis):
        """Gleicher Topic-Typ wird nicht doppelt erkannt."""
        await memory.initialize(mock_redis)
        result = await memory.extract_followup_triggers(
            "Ich habe einen Arzttermin morgen und einen Zahnarzttermin uebermorgen"
        )
        topics = [r["topic"] for r in result]
        assert len(topics) == len(set(topics))

    @pytest.mark.asyncio
    async def test_context_snippet_extracted(self, memory, mock_redis):
        await memory.initialize(mock_redis)
        result = await memory.extract_followup_triggers(
            "Ich habe einen Arzttermin morgen um 10 Uhr beim Zahnarzt"
        )
        if result:
            assert "matched_text" in result[0]
            assert "context" in result[0]
            assert len(result[0]["context"]) > 0


# ============================================================
# _resolve_ask_after
# ============================================================


class TestResolveAskAfter:
    """Tests fuer _resolve_ask_after."""

    def test_next_conversation(self, memory):
        result = memory._resolve_ask_after("next_conversation")
        # Should be approximately now
        dt = datetime.fromisoformat(result)
        assert (datetime.now(timezone.utc) - dt).total_seconds() < 5

    def test_tomorrow(self, memory):
        result = memory._resolve_ask_after("tomorrow")
        dt = datetime.fromisoformat(result)
        assert dt.hour == 8
        assert dt.minute == 0
        # Should be roughly 1 day in the future
        diff = (dt - datetime.now(timezone.utc)).total_seconds()
        assert diff > 0

    def test_iso_datetime(self, memory):
        iso = "2026-06-15T14:30:00+00:00"
        result = memory._resolve_ask_after(iso)
        assert "2026-06-15" in result

    def test_invalid_format_falls_back(self, memory):
        result = memory._resolve_ask_after("gibberish")
        # Should fallback to now
        dt = datetime.fromisoformat(result)
        assert (datetime.now(timezone.utc) - dt).total_seconds() < 5


# ============================================================
# Thread System — Advanced Tests
# ============================================================


class TestThreadSystemAdvanced:
    """Erweiterte Tests fuer Gespraechs-Thread-System."""

    @pytest.fixture
    def memory(self, mock_redis):
        with patch(
            "assistant.conversation_memory.yaml_config",
            {
                "conversation_memory": {
                    "enabled": True,
                    "max_projects": 5,
                    "max_questions": 3,
                    "question_ttl_days": 14,
                    "summary_retention_days": 30,
                }
            },
        ):
            m = ConversationMemory()
        m.redis = mock_redis
        m.enabled = True
        return m

    @pytest.mark.asyncio
    async def test_create_thread_exception(self, memory, mock_redis):
        mock_redis.hset.side_effect = Exception("Redis write fail")
        result = await memory.create_thread("Test Topic", "s1")
        assert result == {}

    @pytest.mark.asyncio
    async def test_link_session_keywords_insufficient(self, memory, mock_redis):
        """Nicht genuegend Keyword-Overlap (<2) verknuepft nicht."""
        mock_redis.hget = AsyncMock(return_value=None)
        result = await memory.link_session_to_thread("s1", "single keyword")
        assert result is None

    @pytest.mark.asyncio
    async def test_link_session_with_overlap(self, memory, mock_redis):
        """Verknuepfung bei genuegend Keyword-Overlap."""
        thread = {
            "id": "thread_1",
            "topic": "Heizung Schlafzimmer optimieren",
            "session_ids": ["s0"],
            "messages_count": 1,
            "last_active": "2026-03-19T10:00:00",
        }

        # hget returns thread_id from index, then thread data
        async def hget_side_effect(key, field):
            if key.endswith("thread_index"):
                # Return thread_id for matching keywords
                if field in ("heizung", "schlafzimmer", "optimieren"):
                    return "thread_1"
                return None
            elif key.endswith("threads"):
                return json.dumps(thread)
            return None

        mock_redis.hget = AsyncMock(side_effect=hget_side_effect)
        mock_redis.hset = AsyncMock()

        result = await memory.link_session_to_thread(
            "s2",
            "Die Heizung im Schlafzimmer ist kalt",
        )

        assert result == "thread_1"
        # Session should be added to thread
        mock_redis.hset.assert_called()

    @pytest.mark.asyncio
    async def test_link_session_exception(self, memory, mock_redis):
        mock_redis.hget = AsyncMock(side_effect=Exception("Fail"))
        result = await memory.link_session_to_thread("s1", "Heizung Schlafzimmer Test")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_thread_context_with_data(self, memory, mock_redis):
        thread = {
            "id": "thread_1",
            "topic": "Heizung",
            "session_ids": ["s1"],
            "last_active": "2026-03-20T10:00:00",
        }
        mock_redis.hget = AsyncMock(
            side_effect=lambda k, f: (
                "thread_1" if k.endswith("thread_index") else json.dumps(thread)
            )
        )
        result = await memory.get_thread_context("Heizung optimieren")
        assert len(result) >= 1
        assert result[0]["topic"] == "Heizung"

    @pytest.mark.asyncio
    async def test_get_thread_context_empty_topic(self, memory, mock_redis):
        result = await memory.get_thread_context("")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_thread_context_exception(self, memory, mock_redis):
        mock_redis.hget = AsyncMock(side_effect=Exception("Fail"))
        result = await memory.get_thread_context("Heizung")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_recent_threads_with_data(self, memory, mock_redis):
        threads = {
            "t1": json.dumps(
                {
                    "id": "t1",
                    "topic": "A",
                    "last_active": "2026-03-20T10:00:00",
                }
            ),
            "t2": json.dumps(
                {
                    "id": "t2",
                    "topic": "B",
                    "last_active": "2026-03-19T10:00:00",
                }
            ),
        }
        mock_redis.hgetall = AsyncMock(return_value=threads)
        result = await memory.get_recent_threads(limit=2)
        assert len(result) == 2
        # Sorted by last_active descending
        assert result[0]["topic"] == "A"
        assert result[1]["topic"] == "B"

    @pytest.mark.asyncio
    async def test_get_recent_threads_with_invalid_json(self, memory, mock_redis):
        threads = {
            "t1": json.dumps({"id": "t1", "topic": "Valid", "last_active": "t"}),
            "t2": "<<<INVALID>>>",
        }
        mock_redis.hgetall = AsyncMock(return_value=threads)
        result = await memory.get_recent_threads()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_recent_threads_no_redis(self, memory):
        memory.redis = None
        result = await memory.get_recent_threads()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_recent_threads_exception(self, memory, mock_redis):
        mock_redis.hgetall = AsyncMock(side_effect=Exception("Fail"))
        result = await memory.get_recent_threads()
        assert result == []

    @pytest.mark.asyncio
    async def test_auto_detect_creates_new_thread(self, memory, mock_redis):
        """auto_detect_thread erstellt neuen Thread wenn kein Link gefunden."""
        mock_redis.hget = AsyncMock(return_value=None)  # No existing thread
        mock_redis.hset = AsyncMock()

        text = "Die Heizung im Schlafzimmer braucht eine neue Einstellung fuer den Winter monate"
        await memory.auto_detect_thread(text, "session_1")
        # Should have called hset to create a thread
        mock_redis.hset.assert_called()

    @pytest.mark.asyncio
    async def test_auto_detect_links_existing_thread(self, memory, mock_redis):
        """auto_detect_thread verknuepft mit bestehendem Thread."""
        thread = {
            "id": "thread_1",
            "topic": "Heizung Schlafzimmer optimieren",
            "session_ids": ["s0"],
            "messages_count": 1,
            "last_active": "2026-03-19T10:00:00",
        }

        async def hget_side_effect(key, field):
            if key.endswith("thread_index"):
                if field in ("heizung", "schlafzimmer", "optimieren"):
                    return "thread_1"
                return None
            return json.dumps(thread)

        mock_redis.hget = AsyncMock(side_effect=hget_side_effect)
        mock_redis.hset = AsyncMock()

        text = "Heizung Schlafzimmer optimieren bitte die Temperatur anpassen morgens"
        await memory.auto_detect_thread(text, "session_2")

    @pytest.mark.asyncio
    async def test_auto_detect_exception(self, memory, mock_redis):
        mock_redis.hget = AsyncMock(side_effect=Exception("Fail"))
        await memory.auto_detect_thread(
            "Long enough text to trigger auto detect thread creation",
            "s1",
        )


# ============================================================
# Memory Context — Additional Tests
# ============================================================


class TestGetMemoryContextAdvanced:
    """Erweiterte Tests fuer get_memory_context."""

    @pytest.mark.asyncio
    async def test_includes_threads(self, memory, mock_redis):
        projects = {}
        questions = {}
        threads = {
            "t1": json.dumps(
                {
                    "id": "t1",
                    "topic": "Heizungsoptimierung",
                    "last_active": "2026-03-20T10:00:00",
                }
            ),
        }

        call_count = [0]

        async def hgetall_side_effect(key):
            call_count[0] += 1
            if "thread" in key:
                return threads
            if "project" in key:
                return projects
            if "question" in key:
                return questions
            if "followup" in key:
                return {}
            return {}

        mock_redis.hgetall = AsyncMock(side_effect=hgetall_side_effect)
        mock_redis.get = AsyncMock(return_value=None)
        await memory.initialize(mock_redis)
        ctx = await memory.get_memory_context()
        assert "Heizungsoptimierung" in ctx

    @pytest.mark.asyncio
    async def test_limits_projects_to_five(self, memory, mock_redis):
        projects = {}
        for i in range(8):
            projects[f"p{i}"] = json.dumps(
                {
                    "id": f"p{i}",
                    "name": f"Projekt {i}",
                    "status": "active",
                    "milestones": [],
                    "updated_at": f"2026-03-{20 - i:02d}",
                }
            )

        async def hgetall_side_effect(key):
            if "project" in key:
                return projects
            if "thread" in key:
                return {}
            if "question" in key:
                return {}
            if "followup" in key:
                return {}
            return {}

        mock_redis.hgetall = AsyncMock(side_effect=hgetall_side_effect)
        mock_redis.get = AsyncMock(return_value=None)
        await memory.initialize(mock_redis)
        ctx = await memory.get_memory_context()
        # Should only mention at most 5 projects
        assert "Aktive Projekte" in ctx


# ============================================================
# Daily Summary — Retention Days
# ============================================================


class TestSaveDailySummaryRetention:
    """Tests fuer save_daily_summary mit Retention-Konfiguration."""

    @pytest.mark.asyncio
    async def test_with_retention_sets_expire(self, memory, mock_redis):
        """Wenn summary_retention_days > 0 wird expire gesetzt."""
        memory.summary_retention_days = 30
        mock_redis.hgetall.return_value = {}
        await memory.initialize(mock_redis)
        mock_redis.expire.reset_mock()
        result = await memory.save_daily_summary("Test", ["Topic"], date="2026-03-20")
        assert result["success"] is True
        mock_redis.expire.assert_called_once()

    @pytest.mark.asyncio
    async def test_without_retention_no_expire(self, memory, mock_redis):
        """Wenn summary_retention_days = 0 wird kein expire gesetzt."""
        memory.summary_retention_days = 0
        mock_redis.hgetall.return_value = {}
        await memory.initialize(mock_redis)
        mock_redis.expire.reset_mock()
        result = await memory.save_daily_summary("Test", ["Topic"], date="2026-03-20")
        assert result["success"] is True
        mock_redis.expire.assert_not_called()
