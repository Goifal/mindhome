"""
Tests fuer Memory-System — Working Memory (Redis), Episodic Memory (ChromaDB),
Conversation Continuity und Notification Tracking.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.memory import MemoryManager


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def redis_mock():
    """Erstellt einen vollstaendigen Redis AsyncMock."""
    r = AsyncMock()
    r.ping = AsyncMock(return_value=True)
    r.lpush = AsyncMock()
    r.ltrim = AsyncMock()
    r.rpush = AsyncMock()
    r.expire = AsyncMock()
    r.lrange = AsyncMock(return_value=[])
    r.setex = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.set = AsyncMock()
    r.hset = AsyncMock()
    r.hgetall = AsyncMock(return_value={})
    r.hdel = AsyncMock()
    r.close = AsyncMock()
    return r


@pytest.fixture
def chroma_mock():
    """Erstellt einen ChromaDB Collection Mock."""
    collection = MagicMock()
    collection.add = MagicMock()
    collection.query = MagicMock(return_value={
        "documents": [["Test Erinnerung"]],
        "metadatas": [[{"timestamp": "2026-02-20T10:00:00"}]],
        "distances": [[0.3]],
        "ids": [["conv_20260220_100000"]],
    })
    collection.update = MagicMock()
    collection.delete = MagicMock()
    return collection


@pytest.fixture
def memory(redis_mock, chroma_mock):
    """Erstellt einen MemoryManager mit gemockten Backends."""
    mm = MemoryManager()
    mm.redis = redis_mock
    mm.chroma_collection = chroma_mock
    mm.semantic = AsyncMock()

    # Pipeline-Mock: redis.pipeline() ist synchron, gibt Pipeline-Objekt zurueck
    pipe_mock = MagicMock()
    pipe_mock.lpush = MagicMock()
    pipe_mock.rpush = MagicMock()
    pipe_mock.ltrim = MagicMock()
    pipe_mock.expire = MagicMock()
    pipe_mock.execute = AsyncMock(return_value=[])
    redis_mock.pipeline = MagicMock(return_value=pipe_mock)
    redis_mock._pipeline = pipe_mock

    return mm


@pytest.fixture
def memory_no_redis():
    """MemoryManager ohne Redis (Graceful Degradation)."""
    mm = MemoryManager()
    mm.redis = None
    mm.chroma_collection = None
    mm.semantic = AsyncMock()
    return mm


# =====================================================================
# Working Memory (Redis)
# =====================================================================


class TestWorkingMemory:
    """Tests fuer add_conversation, get_recent_conversations, context."""

    @pytest.mark.asyncio
    async def test_add_conversation_stores_in_redis(self, memory, redis_mock):
        await memory.add_conversation("user", "Hallo Jarvis")

        # Code nutzt Pipeline: redis.pipeline() → pipe.lpush/ltrim → pipe.execute()
        pipe = redis_mock._pipeline
        pipe.lpush.assert_called()
        args = pipe.lpush.call_args
        assert args[0][0] == "mha:conversations"
        entry = json.loads(args[0][1])
        assert entry["role"] == "user"
        assert entry["content"] == "Hallo Jarvis"
        assert "timestamp" in entry

        pipe.ltrim.assert_called_once_with("mha:conversations", 0, 49)

    @pytest.mark.asyncio
    async def test_add_conversation_archives_daily(self, memory, redis_mock):
        await memory.add_conversation("assistant", "Guten Morgen, Sir.")

        # Code nutzt Pipeline fuer Tages-Archiv
        pipe = redis_mock._pipeline
        today = datetime.now().strftime("%Y-%m-%d")
        archive_key = f"mha:archive:{today}"
        pipe.rpush.assert_called_once()
        assert pipe.rpush.call_args[0][0] == archive_key
        # expire wird 2x aufgerufen: conversations (7d) + archive (30d)
        pipe.expire.assert_any_call(archive_key, 30 * 86400)
        assert pipe.expire.call_count == 2

    @pytest.mark.asyncio
    async def test_add_conversation_no_redis_no_error(self, memory_no_redis):
        # Sollte keinen Fehler werfen wenn Redis nicht da ist
        await memory_no_redis.add_conversation("user", "Test")

    @pytest.mark.asyncio
    async def test_get_recent_conversations_returns_ordered(self, memory, redis_mock):
        entries = [
            json.dumps({"role": "assistant", "content": "Antwort", "timestamp": "2026-02-20T10:01:00"}),
            json.dumps({"role": "user", "content": "Frage", "timestamp": "2026-02-20T10:00:00"}),
        ]
        redis_mock.lrange = AsyncMock(return_value=entries)

        result = await memory.get_recent_conversations(limit=5)

        redis_mock.lrange.assert_called_once_with("mha:conversations", 0, 4)
        # Ergebnis wird umgekehrt: aelteste zuerst
        assert len(result) == 2
        assert result[0]["content"] == "Frage"
        assert result[1]["content"] == "Antwort"

    @pytest.mark.asyncio
    async def test_get_recent_conversations_handles_invalid_json(self, memory, redis_mock):
        redis_mock.lrange = AsyncMock(return_value=[
            json.dumps({"role": "user", "content": "ok", "timestamp": "t"}),
            "<<<INVALID JSON>>>",
            json.dumps({"role": "assistant", "content": "ja", "timestamp": "t"}),
        ])

        result = await memory.get_recent_conversations(limit=5)
        # Invalider Eintrag wird uebersprungen
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_recent_conversations_no_redis(self, memory_no_redis):
        result = await memory_no_redis.get_recent_conversations()
        assert result == []

    @pytest.mark.asyncio
    async def test_set_context(self, memory, redis_mock):
        await memory.set_context("current_room", "Wohnzimmer", ttl=1800)
        redis_mock.setex.assert_called_once_with(
            "mha:context:current_room", 1800, "Wohnzimmer"
        )

    @pytest.mark.asyncio
    async def test_set_context_default_ttl(self, memory, redis_mock):
        await memory.set_context("mood", "gut")
        redis_mock.setex.assert_called_once_with("mha:context:mood", 3600, "gut")

    @pytest.mark.asyncio
    async def test_get_context(self, memory, redis_mock):
        redis_mock.get = AsyncMock(return_value="Buero")
        result = await memory.get_context("current_room")
        assert result == "Buero"
        redis_mock.get.assert_called_once_with("mha:context:current_room")

    @pytest.mark.asyncio
    async def test_get_context_no_redis(self, memory_no_redis):
        result = await memory_no_redis.get_context("anything")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_context_no_redis(self, memory_no_redis):
        # Kein Fehler wenn Redis fehlt
        await memory_no_redis.set_context("key", "val")

    @pytest.mark.asyncio
    async def test_get_conversations_for_date(self, memory, redis_mock):
        entries = [
            json.dumps({"role": "user", "content": "Morgen", "timestamp": "2026-02-20T08:00:00"}),
            json.dumps({"role": "assistant", "content": "Guten Morgen", "timestamp": "2026-02-20T08:00:01"}),
        ]
        redis_mock.lrange = AsyncMock(return_value=entries)

        result = await memory.get_conversations_for_date("2026-02-20")
        assert len(result) == 2
        redis_mock.lrange.assert_called_once_with("mha:archive:2026-02-20", 0, -1)

    @pytest.mark.asyncio
    async def test_get_conversations_for_date_no_redis(self, memory_no_redis):
        result = await memory_no_redis.get_conversations_for_date("2026-02-20")
        assert result == []


# =====================================================================
# Episodic Memory (ChromaDB)
# =====================================================================


class TestEpisodicMemory:
    """Tests fuer store_episode und search_memories."""

    @pytest.mark.asyncio
    async def test_store_episode_short_text(self, memory, chroma_mock):
        await memory.store_episode("Kurzer Dialog", {"topic": "Test"})

        chroma_mock.add.assert_called_once()
        call_kwargs = chroma_mock.add.call_args[1]
        assert call_kwargs["documents"] == ["Kurzer Dialog"]
        assert call_kwargs["metadatas"][0]["topic"] == "Test"
        assert call_kwargs["metadatas"][0]["type"] == "conversation"
        assert "timestamp" in call_kwargs["metadatas"][0]

    @pytest.mark.asyncio
    async def test_store_episode_long_text_creates_chunks(self, memory, chroma_mock):
        long_text = "User: " + "Dies ist ein langer Satz. " * 30 + " Assistant: Antwort hier."
        await memory.store_episode(long_text)

        # Sollte mehrere Chunks speichern
        assert chroma_mock.add.call_count >= 2

    @pytest.mark.asyncio
    async def test_store_episode_metadata_has_chunk_info(self, memory, chroma_mock):
        long_text = "User: " + "Langer Text hier. " * 30 + " Assistant: Antwort."
        await memory.store_episode(long_text)

        # Jeder Chunk hat chunk_index und total_chunks
        for call in chroma_mock.add.call_args_list:
            meta = call[1]["metadatas"][0]
            assert "chunk_index" in meta
            assert "total_chunks" in meta

    @pytest.mark.asyncio
    async def test_store_episode_no_chroma_no_error(self, memory_no_redis):
        await memory_no_redis.store_episode("Test Dialog")

    @pytest.mark.asyncio
    async def test_store_episode_chroma_error_caught(self, memory, chroma_mock):
        chroma_mock.add.side_effect = Exception("ChromaDB down")
        # Sollte keinen Fehler werfen
        await memory.store_episode("Test")

    @pytest.mark.asyncio
    async def test_search_memories(self, memory, chroma_mock):
        result = await memory.search_memories("Wetter Wien", limit=3)

        chroma_mock.query.assert_called_once_with(
            query_texts=["Wetter Wien"],
            n_results=3,
        )
        assert len(result) == 1
        assert result[0]["content"] == "Test Erinnerung"
        assert result[0]["timestamp"] == "2026-02-20T10:00:00"
        assert result[0]["relevance"] == 0.3

    @pytest.mark.asyncio
    async def test_search_memories_no_results(self, memory, chroma_mock):
        chroma_mock.query = MagicMock(return_value={
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        })
        result = await memory.search_memories("Gibt es nicht")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_memories_no_chroma(self, memory_no_redis):
        result = await memory_no_redis.search_memories("Test")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_memories_chroma_error_caught(self, memory, chroma_mock):
        chroma_mock.query.side_effect = Exception("Connection lost")
        result = await memory.search_memories("Test")
        assert result == []


# =====================================================================
# Episodic Chunking (statische Methode)
# =====================================================================


class TestEpisodicChunking:
    """Tests fuer MemoryManager._split_conversation()."""

    def test_short_text_no_split(self):
        result = MemoryManager._split_conversation("Hallo Welt")
        assert result == ["Hallo Welt"]

    def test_empty_text(self):
        result = MemoryManager._split_conversation("")
        assert result == []

    def test_whitespace_only(self):
        result = MemoryManager._split_conversation("   \n\t  ")
        assert result == []

    def test_speaker_change_split(self):
        text = (
            "User: Wie wird das Wetter morgen in Wien? Ich brauche das fuer die Planung. "
            "Das ist wirklich wichtig und ich frage mich ob es regnen wird oder nicht. "
            "Assistant: Morgen wird es in Wien sonnig bei 22 Grad. "
            "Kein Regen erwartet. Perfektes Wetter fuer draussen. "
            "User: Super danke dir."
        )
        result = MemoryManager._split_conversation(text)
        assert len(result) >= 1
        assert all(len(chunk) > 0 for chunk in result)

    def test_chunks_have_overlap(self):
        text = "Dies ist ein sehr langer Text. " * 20
        result = MemoryManager._split_conversation(text)
        assert len(result) >= 2

    def test_text_at_chunk_boundary(self):
        # Exakt chunk_size Zeichen
        text = "X" * MemoryManager.EPISODE_CHUNK_SIZE
        result = MemoryManager._split_conversation(text)
        assert len(result) == 1

    def test_text_just_over_chunk_boundary(self):
        text = "X" * (MemoryManager.EPISODE_CHUNK_SIZE + 1)
        result = MemoryManager._split_conversation(text)
        assert len(result) >= 1

    def test_jarvis_speaker_prefix_recognized(self):
        text = (
            "Sir: Mach bitte das Licht an im Wohnzimmer und stelle die Temperatur etwas waermer ein. "
            "Jarvis: Selbstverstaendlich. Licht ist an und Temperatur auf 22 Grad eingestellt. "
            "Sir: Danke Jarvis, das ist perfekt."
        )
        result = MemoryManager._split_conversation(text)
        assert len(result) >= 1
        # Inhalt sollte erhalten bleiben
        combined = " ".join(result)
        assert "Licht" in combined

    def test_no_empty_chunks_returned(self):
        text = "User:  \n\nAssistant:  \n\nUser: Hallo"
        result = MemoryManager._split_conversation(text)
        assert all(c.strip() for c in result)


# =====================================================================
# Conversation Continuity (Pending Topics)
# =====================================================================


class TestConversationContinuity:
    """Tests fuer offene Gespraechsthemen (Phase 8)."""

    @pytest.mark.asyncio
    async def test_mark_conversation_pending(self, memory, redis_mock):
        await memory.mark_conversation_pending(
            topic="Heizung optimieren",
            context="Wohnzimmer zu kalt",
            person="Max",
        )

        redis_mock.hset.assert_called_once()
        args = redis_mock.hset.call_args
        assert args[0][0] == "mha:pending_topics"
        assert args[0][1] == "Heizung optimieren"
        entry = json.loads(args[0][2])
        assert entry["topic"] == "Heizung optimieren"
        assert entry["context"] == "Wohnzimmer zu kalt"
        assert entry["person"] == "Max"

        redis_mock.expire.assert_called_once_with("mha:pending_topics", 86400)

    @pytest.mark.asyncio
    async def test_mark_pending_no_redis(self, memory_no_redis):
        await memory_no_redis.mark_conversation_pending("topic")

    @pytest.mark.asyncio
    async def test_get_pending_conversations_filters_by_age(self, memory, redis_mock):
        now = datetime.now()

        # Thema: 30 Min alt -> sollte zurueckgegeben werden
        valid_entry = json.dumps({
            "topic": "Energieanalyse",
            "context": "",
            "person": "Max",
            "timestamp": (now - timedelta(minutes=30)).isoformat(),
        })

        # Thema: 2 Min alt -> zu frisch, wird gefiltert
        too_fresh = json.dumps({
            "topic": "Gerade gesagt",
            "context": "",
            "person": "Max",
            "timestamp": (now - timedelta(minutes=2)).isoformat(),
        })

        # Thema: 25 Stunden alt -> zu alt, wird gefiltert
        too_old = json.dumps({
            "topic": "Gestern",
            "context": "",
            "person": "Max",
            "timestamp": (now - timedelta(hours=25)).isoformat(),
        })

        redis_mock.hgetall = AsyncMock(return_value={
            "Energieanalyse": valid_entry,
            "Gerade gesagt": too_fresh,
            "Gestern": too_old,
        })

        result = await memory.get_pending_conversations()
        assert len(result) == 1
        assert result[0]["topic"] == "Energieanalyse"
        assert "age_minutes" in result[0]

    @pytest.mark.asyncio
    async def test_get_pending_no_redis(self, memory_no_redis):
        result = await memory_no_redis.get_pending_conversations()
        assert result == []

    @pytest.mark.asyncio
    async def test_resolve_conversation(self, memory, redis_mock):
        await memory.resolve_conversation("Heizung optimieren")
        redis_mock.hdel.assert_called_once_with(
            "mha:pending_topics", "Heizung optimieren"
        )

    @pytest.mark.asyncio
    async def test_resolve_conversation_no_redis(self, memory_no_redis):
        await memory_no_redis.resolve_conversation("topic")


# =====================================================================
# Notification Tracking
# =====================================================================


class TestNotificationTracking:
    """Tests fuer Notification-Cooldown Verwaltung."""

    @pytest.mark.asyncio
    async def test_get_last_notification_time(self, memory, redis_mock):
        redis_mock.get = AsyncMock(return_value="2026-02-20T10:30:00")
        result = await memory.get_last_notification_time("window_open")
        assert result == "2026-02-20T10:30:00"
        redis_mock.get.assert_called_once_with("mha:notify:window_open")

    @pytest.mark.asyncio
    async def test_get_last_notification_time_none(self, memory, redis_mock):
        redis_mock.get = AsyncMock(return_value=None)
        result = await memory.get_last_notification_time("unknown_event")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_last_notification_no_redis(self, memory_no_redis):
        result = await memory_no_redis.get_last_notification_time("test")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_last_notification_time(self, memory, redis_mock):
        await memory.set_last_notification_time("door_open")
        redis_mock.setex.assert_called_once()
        args = redis_mock.setex.call_args[0]
        assert args[0] == "mha:notify:door_open"
        assert args[1] == 3600  # 1h TTL

    @pytest.mark.asyncio
    async def test_set_last_notification_no_redis(self, memory_no_redis):
        await memory_no_redis.set_last_notification_time("test")


# =====================================================================
# Feedback Scores
# =====================================================================


class TestFeedbackScores:
    """Tests fuer Legacy-Feedback-Score Verwaltung."""

    @pytest.mark.asyncio
    async def test_get_feedback_score_default(self, memory, redis_mock):
        redis_mock.get = AsyncMock(return_value=None)
        score = await memory.get_feedback_score("window_alert")
        assert score == 0.5

    @pytest.mark.asyncio
    async def test_get_feedback_score_from_new_key(self, memory, redis_mock):
        # Erstes get (neues Schema) liefert Wert
        redis_mock.get = AsyncMock(return_value="0.8")
        score = await memory.get_feedback_score("door_alert")
        assert score == 0.8
        redis_mock.get.assert_called_once_with("mha:feedback:score:door_alert")

    @pytest.mark.asyncio
    async def test_get_feedback_score_no_redis(self, memory_no_redis):
        score = await memory_no_redis.get_feedback_score("test")
        assert score == 0.5

    @pytest.mark.asyncio
    async def test_update_feedback_score(self, memory, redis_mock):
        redis_mock.get = AsyncMock(return_value="0.5")
        await memory.update_feedback_score("test_event", 0.1)
        redis_mock.setex.assert_called_with(
            "mha:feedback:score:test_event", 90 * 86400, "0.6"
        )

    @pytest.mark.asyncio
    async def test_update_feedback_score_clamped_max(self, memory, redis_mock):
        redis_mock.get = AsyncMock(return_value="0.95")
        await memory.update_feedback_score("test_event", 0.2)
        redis_mock.setex.assert_called_with(
            "mha:feedback:score:test_event", 90 * 86400, "1.0"
        )

    @pytest.mark.asyncio
    async def test_update_feedback_score_clamped_min(self, memory, redis_mock):
        redis_mock.get = AsyncMock(return_value="0.1")
        await memory.update_feedback_score("test_event", -0.5)
        redis_mock.setex.assert_called_with(
            "mha:feedback:score:test_event", 90 * 86400, "0.0"
        )

    @pytest.mark.asyncio
    async def test_update_feedback_no_redis(self, memory_no_redis):
        await memory_no_redis.update_feedback_score("test", 0.1)


# =====================================================================
# Close / Cleanup
# =====================================================================


class TestMemoryCleanup:
    """Tests fuer close() Methode."""

    @pytest.mark.asyncio
    async def test_close_with_redis(self, memory, redis_mock):
        await memory.close()
        redis_mock.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_without_redis(self, memory_no_redis):
        await memory_no_redis.close()
