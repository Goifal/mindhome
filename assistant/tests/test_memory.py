"""
Tests fuer Memory-System — Working Memory (Redis), Episodic Memory (ChromaDB),
Conversation Continuity und Notification Tracking.
"""

import json
from datetime import datetime, timedelta, timezone
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
    collection.query = MagicMock(
        return_value={
            "documents": [["Test Erinnerung"]],
            "metadatas": [[{"timestamp": "2026-02-20T10:00:00"}]],
            "distances": [[0.3]],
            "ids": [["conv_20260220_100000"]],
        }
    )
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
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
            json.dumps(
                {
                    "role": "assistant",
                    "content": "Antwort",
                    "timestamp": "2026-02-20T10:01:00",
                }
            ),
            json.dumps(
                {"role": "user", "content": "Frage", "timestamp": "2026-02-20T10:00:00"}
            ),
        ]
        redis_mock.lrange = AsyncMock(return_value=entries)

        result = await memory.get_recent_conversations(limit=5)

        redis_mock.lrange.assert_called_once_with("mha:conversations", 0, 4)
        # Ergebnis wird umgekehrt: aelteste zuerst
        assert len(result) == 2
        assert result[0]["content"] == "Frage"
        assert result[1]["content"] == "Antwort"

    @pytest.mark.asyncio
    async def test_get_recent_conversations_handles_invalid_json(
        self, memory, redis_mock
    ):
        redis_mock.lrange = AsyncMock(
            return_value=[
                json.dumps({"role": "user", "content": "ok", "timestamp": "t"}),
                "<<<INVALID JSON>>>",
                json.dumps({"role": "assistant", "content": "ja", "timestamp": "t"}),
            ]
        )

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
            json.dumps(
                {
                    "role": "user",
                    "content": "Morgen",
                    "timestamp": "2026-02-20T08:00:00",
                }
            ),
            json.dumps(
                {
                    "role": "assistant",
                    "content": "Guten Morgen",
                    "timestamp": "2026-02-20T08:00:01",
                }
            ),
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
        long_text = (
            "User: " + "Dies ist ein langer Satz. " * 30 + " Assistant: Antwort hier."
        )
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
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
            }
        )
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
        now = datetime.now(timezone.utc)

        # Thema: 30 Min alt -> sollte zurueckgegeben werden
        valid_entry = json.dumps(
            {
                "topic": "Energieanalyse",
                "context": "",
                "person": "Max",
                "timestamp": (now - timedelta(minutes=30)).isoformat(),
            }
        )

        # Thema: 2 Min alt -> zu frisch, wird gefiltert
        too_fresh = json.dumps(
            {
                "topic": "Gerade gesagt",
                "context": "",
                "person": "Max",
                "timestamp": (now - timedelta(minutes=2)).isoformat(),
            }
        )

        # Thema: 25 Stunden alt -> zu alt, wird gefiltert
        too_old = json.dumps(
            {
                "topic": "Gestern",
                "context": "",
                "person": "Max",
                "timestamp": (now - timedelta(hours=25)).isoformat(),
            }
        )

        redis_mock.hgetall = AsyncMock(
            return_value={
                "Energieanalyse": valid_entry,
                "Gerade gesagt": too_fresh,
                "Gestern": too_old,
            }
        )

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
        redis_mock.mget = AsyncMock(return_value=[None, None])
        score = await memory.get_feedback_score("window_alert")
        assert score == 0.5

    @pytest.mark.asyncio
    async def test_get_feedback_score_from_new_key(self, memory, redis_mock):
        # mget liefert [neues_schema, altes_schema] — neues hat Wert
        redis_mock.mget = AsyncMock(return_value=["0.8", None])
        score = await memory.get_feedback_score("door_alert")
        assert score == 0.8
        redis_mock.mget.assert_called_once_with(
            "mha:feedback:score:door_alert", "mha:feedback:door_alert"
        )

    @pytest.mark.asyncio
    async def test_get_feedback_score_no_redis(self, memory_no_redis):
        score = await memory_no_redis.get_feedback_score("test")
        assert score == 0.5

    @pytest.mark.asyncio
    async def test_update_feedback_score(self, memory, redis_mock):
        redis_mock.mget = AsyncMock(return_value=["0.5", None])
        await memory.update_feedback_score("test_event", 0.1)
        redis_mock.setex.assert_called_with(
            "mha:feedback:score:test_event", 90 * 86400, "0.6"
        )

    @pytest.mark.asyncio
    async def test_update_feedback_score_clamped_max(self, memory, redis_mock):
        redis_mock.mget = AsyncMock(return_value=["0.95", None])
        await memory.update_feedback_score("test_event", 0.2)
        redis_mock.setex.assert_called_with(
            "mha:feedback:score:test_event", 90 * 86400, "1.0"
        )

    @pytest.mark.asyncio
    async def test_update_feedback_score_clamped_min(self, memory, redis_mock):
        redis_mock.mget = AsyncMock(return_value=["0.1", None])
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


# =====================================================================
# Pipeline Error Handling
# =====================================================================


class TestAddConversationErrorHandling:
    """Tests fuer Fehlerbehandlung in add_conversation."""

    @pytest.mark.asyncio
    async def test_add_conversation_pipeline_exception(self, memory, redis_mock):
        """Pipeline-Fehler wird gefangen, kein Crash."""
        pipe = redis_mock._pipeline
        pipe.execute = AsyncMock(side_effect=Exception("Pipeline broken"))

        # Sollte keinen Fehler werfen
        await memory.add_conversation("user", "Test message")


class TestGetConversationsForDateEdgeCases:
    """Tests fuer get_conversations_for_date Randfaelle."""

    @pytest.mark.asyncio
    async def test_skips_empty_entries(self, memory, redis_mock):
        """Leere Eintraege werden uebersprungen."""
        entries = [
            "",
            json.dumps({"role": "user", "content": "Hallo", "timestamp": "t1"}),
            None,
        ]
        redis_mock.lrange = AsyncMock(return_value=entries)

        result = await memory.get_conversations_for_date("2026-03-20")
        # Only the valid JSON entry should appear
        assert len(result) == 1
        assert result[0]["content"] == "Hallo"

    @pytest.mark.asyncio
    async def test_handles_invalid_json_in_archive(self, memory, redis_mock):
        """Ungueltige JSON-Eintraege im Archiv werden uebersprungen."""
        entries = [
            "<<<BROKEN>>>",
            json.dumps({"role": "assistant", "content": "Ok", "timestamp": "t2"}),
        ]
        redis_mock.lrange = AsyncMock(return_value=entries)

        result = await memory.get_conversations_for_date("2026-03-20")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_redis_exception_returns_empty(self, memory, redis_mock):
        """Redis-Fehler wird gefangen, leere Liste zurueckgegeben."""
        redis_mock.lrange = AsyncMock(side_effect=Exception("Redis error"))

        result = await memory.get_conversations_for_date("2026-03-20")
        assert result == []


# =====================================================================
# Search Episodes by Time
# =====================================================================


class TestSearchEpisodesByTime:
    """Tests fuer search_episodes_by_time."""

    @pytest.mark.asyncio
    async def test_returns_episodes_in_range(self, memory, chroma_mock):
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [["Montag Dialog", "Dienstag Dialog"]],
                "metadatas": [
                    [
                        {"timestamp": "2026-03-01T10:00:00", "person": "Max"},
                        {"timestamp": "2026-03-02T10:00:00", "person": "Anna"},
                    ]
                ],
                "distances": [[0.2, 0.4]],
            }
        )

        result = await memory.search_episodes_by_time(
            query="Heizung",
            start_date="2026-03-01",
            end_date="2026-03-07",
            limit=5,
        )

        assert len(result) == 2
        assert result[0]["content"] == "Montag Dialog"
        assert result[0]["person"] == "Max"
        assert result[1]["timestamp"] == "2026-03-02T10:00:00"

    @pytest.mark.asyncio
    async def test_respects_limit(self, memory, chroma_mock):
        """Limit begrenzt die Ergebnisse."""
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [["A", "B", "C"]],
                "metadatas": [
                    [
                        {"timestamp": "t1"},
                        {"timestamp": "t2"},
                        {"timestamp": "t3"},
                    ]
                ],
                "distances": [[0.1, 0.2, 0.3]],
            }
        )

        result = await memory.search_episodes_by_time(
            query="test",
            start_date="2026-01-01",
            end_date="2026-12-31",
            limit=2,
        )

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_no_chroma_returns_empty(self, memory_no_redis):
        result = await memory_no_redis.search_episodes_by_time(
            "test",
            "2026-01-01",
            "2026-12-31",
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_chroma_error_falls_back_to_search_memories(
        self, memory, chroma_mock
    ):
        """Bei Fehler wird auf search_memories zurueckgegriffen."""
        # Erster Aufruf (search_episodes_by_time) wirft Fehler
        call_count = 0

        def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if "where" in kwargs:
                raise Exception("where filter not supported")
            # Fallback-Aufruf ohne where
            return {
                "documents": [["Fallback result"]],
                "metadatas": [[{"timestamp": "t1"}]],
                "distances": [[0.5]],
            }

        chroma_mock.query = MagicMock(side_effect=side_effect)

        result = await memory.search_episodes_by_time(
            "test",
            "2026-01-01",
            "2026-12-31",
            limit=3,
        )

        # Sollte Fallback-Ergebnis liefern
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_empty_results(self, memory, chroma_mock):
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
            }
        )

        result = await memory.search_episodes_by_time(
            "nothing",
            "2026-01-01",
            "2026-12-31",
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_missing_metadata_handled_gracefully(self, memory, chroma_mock):
        """Fehlende Metadaten fuehren nicht zum Absturz."""
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [["Some text"]],
                "metadatas": [[]],  # No metadata
                "distances": [[0.3]],
            }
        )

        result = await memory.search_episodes_by_time(
            "test",
            "2026-01-01",
            "2026-12-31",
        )
        assert len(result) == 1
        assert result[0]["content"] == "Some text"
        assert result[0]["timestamp"] == ""


# =====================================================================
# Episode Management (get_all_episodes, delete_episodes)
# =====================================================================


class TestGetAllEpisodes:
    """Tests fuer get_all_episodes (UI-Paginierung)."""

    @pytest.mark.asyncio
    async def test_returns_paginated_episodes(self, memory, chroma_mock):
        chroma_mock.count = MagicMock(return_value=3)
        chroma_mock.get = MagicMock(
            side_effect=[
                # Erster Aufruf: Metadaten
                {
                    "ids": ["ep1", "ep2", "ep3"],
                    "metadatas": [
                        {"timestamp": "2026-03-01T10:00:00", "type": "conversation"},
                        {"timestamp": "2026-03-02T10:00:00", "type": "conversation"},
                        {"timestamp": "2026-03-03T10:00:00", "type": "conversation"},
                    ],
                },
                # Zweiter Aufruf: Documents fuer die Seite
                {
                    "ids": ["ep3", "ep2"],
                    "documents": ["Dialog 3", "Dialog 2"],
                },
            ]
        )

        result = await memory.get_all_episodes(offset=0, limit=2)

        assert len(result) == 2
        # Neueste zuerst (nach timestamp sortiert, absteigend)
        assert result[0]["id"] == "ep3"
        assert result[0]["content"] == "Dialog 3"

    @pytest.mark.asyncio
    async def test_no_chroma_returns_empty(self, memory_no_redis):
        result = await memory_no_redis.get_all_episodes()
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_collection(self, memory, chroma_mock):
        chroma_mock.count = MagicMock(return_value=0)
        result = await memory.get_all_episodes()
        assert result == []

    @pytest.mark.asyncio
    async def test_offset_beyond_range(self, memory, chroma_mock):
        chroma_mock.count = MagicMock(return_value=2)
        chroma_mock.get = MagicMock(
            return_value={
                "ids": ["ep1", "ep2"],
                "metadatas": [
                    {"timestamp": "2026-03-01T10:00:00", "type": "conversation"},
                    {"timestamp": "2026-03-02T10:00:00", "type": "conversation"},
                ],
            }
        )

        result = await memory.get_all_episodes(offset=10, limit=5)
        assert result == []

    @pytest.mark.asyncio
    async def test_chroma_exception_returns_empty(self, memory, chroma_mock):
        chroma_mock.count = MagicMock(side_effect=Exception("ChromaDB down"))
        result = await memory.get_all_episodes()
        assert result == []

    @pytest.mark.asyncio
    async def test_non_dict_metadata_handled(self, memory, chroma_mock):
        """Nicht-Dict Metadaten fuehren nicht zum Absturz."""
        chroma_mock.count = MagicMock(return_value=1)
        chroma_mock.get = MagicMock(
            side_effect=[
                {
                    "ids": ["ep1"],
                    "metadatas": [None],  # Kein Dict
                },
                {
                    "ids": ["ep1"],
                    "documents": ["Dialog text"],
                },
            ]
        )

        result = await memory.get_all_episodes(offset=0, limit=1)
        assert len(result) == 1
        assert result[0]["timestamp"] == ""


class TestDeleteEpisodes:
    """Tests fuer delete_episodes."""

    @pytest.mark.asyncio
    async def test_deletes_episodes(self, memory, chroma_mock):
        result = await memory.delete_episodes(["ep1", "ep2"])
        assert result == 2
        chroma_mock.delete.assert_called_once_with(ids=["ep1", "ep2"])

    @pytest.mark.asyncio
    async def test_no_chroma_returns_zero(self, memory_no_redis):
        result = await memory_no_redis.delete_episodes(["ep1"])
        assert result == 0

    @pytest.mark.asyncio
    async def test_empty_list_returns_zero(self, memory, chroma_mock):
        result = await memory.delete_episodes([])
        assert result == 0
        chroma_mock.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_chroma_error_returns_zero(self, memory, chroma_mock):
        chroma_mock.delete.side_effect = Exception("Delete failed")
        result = await memory.delete_episodes(["ep1"])
        assert result == 0


# =====================================================================
# Clear All Memory
# =====================================================================


class TestClearAllMemory:
    """Tests fuer clear_all_memory (vollstaendiges Loeschen)."""

    @pytest.mark.asyncio
    async def test_clears_all_three_layers(self, memory, redis_mock, chroma_mock):
        """Loescht Episoden, Fakten und Working Memory."""
        # ChromaDB Client mock
        chroma_client = MagicMock()
        chroma_client.delete_collection = MagicMock()
        chroma_client.get_or_create_collection = MagicMock(return_value=chroma_mock)
        memory._chroma_client = chroma_client

        # Semantic Memory mock
        memory.semantic = AsyncMock()
        memory.semantic.clear_all = AsyncMock(return_value=5)

        # Redis scan_iter mock
        async def scan_iter_mock(match=""):
            if "archive" in match:
                yield "mha:archive:2026-03-19"
            elif "context" in match:
                yield "mha:context:room"
            elif "emotional_memory" in match:
                yield "mha:emotional_memory:angry"
            elif "pending_topics" in match:
                yield "mha:pending_topics"

        redis_mock.scan_iter = scan_iter_mock
        redis_mock.delete = AsyncMock()

        with patch("assistant.embeddings.get_embedding_function", return_value=None):
            result = await memory.clear_all_memory()

        assert result["episodes_deleted"] == -1  # -1 = alle
        assert result["facts_deleted"] == 5
        assert result["working_cleared"] is True
        chroma_client.delete_collection.assert_called_once_with("mha_conversations")
        redis_mock.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_chroma_error(self, memory, redis_mock, chroma_mock):
        """ChromaDB-Fehler wird gefangen."""
        chroma_client = MagicMock()
        chroma_client.delete_collection = MagicMock(
            side_effect=Exception("ChromaDB error")
        )
        memory._chroma_client = chroma_client
        memory.semantic = AsyncMock()
        memory.semantic.clear_all = AsyncMock(return_value=0)

        async def scan_iter_mock(match=""):
            return
            yield  # noqa: F821 — make it an async generator

        redis_mock.scan_iter = scan_iter_mock
        redis_mock.delete = AsyncMock()

        result = await memory.clear_all_memory()
        assert result["episodes_deleted"] == 0  # Nicht geloescht wegen Fehler

    @pytest.mark.asyncio
    async def test_handles_semantic_error(self, memory, redis_mock, chroma_mock):
        """Semantic Memory Fehler wird gefangen."""
        memory._chroma_client = None
        memory.semantic = AsyncMock()
        memory.semantic.clear_all = AsyncMock(side_effect=Exception("Semantic error"))

        async def scan_iter_mock(match=""):
            return
            yield  # noqa: F821

        redis_mock.scan_iter = scan_iter_mock
        redis_mock.delete = AsyncMock()

        result = await memory.clear_all_memory()
        assert result["facts_deleted"] == 0

    @pytest.mark.asyncio
    async def test_handles_redis_error(self, memory, redis_mock, chroma_mock):
        """Redis-Fehler wird gefangen."""
        memory._chroma_client = None
        memory.semantic = None

        async def scan_iter_mock(match=""):
            raise Exception("Redis scan error")
            yield  # noqa: F821

        redis_mock.scan_iter = scan_iter_mock

        result = await memory.clear_all_memory()
        assert result["working_cleared"] is False

    @pytest.mark.asyncio
    async def test_no_backends_available(self, memory_no_redis):
        """Kein Backend verfuegbar — kein Crash."""
        memory_no_redis.semantic = None
        result = await memory_no_redis.clear_all_memory()
        assert result["episodes_deleted"] == 0
        assert result["facts_deleted"] == 0
        assert result["working_cleared"] is False


# =====================================================================
# Factory Reset
# =====================================================================


class TestFactoryReset:
    """Tests fuer factory_reset."""

    @pytest.mark.asyncio
    async def test_factory_reset_clears_all_keys(self, memory, redis_mock, chroma_mock):
        """Factory Reset loescht alle mha:* Keys."""
        memory._chroma_client = None
        memory.semantic = AsyncMock()
        memory.semantic.clear_all = AsyncMock(return_value=0)

        async def scan_iter_mock(match=""):
            if match == "mha:*":
                yield "mha:feedback:score:test"
                yield "mha:corrections:data"
            else:
                return

        redis_mock.scan_iter = scan_iter_mock
        redis_mock.delete = AsyncMock()

        result = await memory.factory_reset()
        assert result["redis_keys_deleted"] == 2

    @pytest.mark.asyncio
    async def test_factory_reset_with_uploads(self, memory, redis_mock, chroma_mock):
        """Factory Reset mit Uploads-Loeschung."""
        memory._chroma_client = None
        memory.semantic = AsyncMock()
        memory.semantic.clear_all = AsyncMock(return_value=0)

        async def scan_iter_mock(match=""):
            return
            yield  # noqa: F821

        redis_mock.scan_iter = scan_iter_mock
        redis_mock.delete = AsyncMock()

        mock_upload_dir = MagicMock()
        mock_upload_dir.exists.return_value = True
        mock_upload_dir.iterdir.return_value = [MagicMock(), MagicMock()]  # 2 Dateien

        with (
            patch("assistant.embeddings.get_embedding_function", return_value=None),
            patch.dict(
                "sys.modules",
                {"assistant.file_handler": MagicMock(UPLOAD_DIR=mock_upload_dir)},
            ),
            patch("shutil.rmtree"),
        ):
            result = await memory.factory_reset(include_uploads=True)

        assert result.get("uploads_deleted") == 2

    @pytest.mark.asyncio
    async def test_factory_reset_redis_error(self, memory, redis_mock, chroma_mock):
        """Redis-Fehler bei Factory Reset wird gefangen."""
        memory._chroma_client = None
        memory.semantic = AsyncMock()
        memory.semantic.clear_all = AsyncMock(return_value=0)

        async def scan_iter_mock(match=""):
            raise Exception("Redis scan error")
            yield  # noqa: F821

        redis_mock.scan_iter = scan_iter_mock

        result = await memory.factory_reset()
        assert result.get("redis_keys_deleted") == 0

    @pytest.mark.asyncio
    async def test_factory_reset_no_redis(self, memory_no_redis):
        """Factory Reset ohne Redis — kein Crash."""
        memory_no_redis.semantic = AsyncMock()
        memory_no_redis.semantic.clear_all = AsyncMock(return_value=0)
        result = await memory_no_redis.factory_reset()
        assert "redis_keys_deleted" not in result


# =====================================================================
# Store Episode — Dedup and Timeout Handling
# =====================================================================


class TestStoreEpisodeAdvanced:
    """Tests fuer Deduplizierung und Timeout-Handling in store_episode."""

    @pytest.mark.asyncio
    async def test_dedup_skips_near_duplicate(self, memory, chroma_mock):
        """Sehr aehnliche Episode wird uebersprungen (distance < 0.1)."""
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [["Fast identischer Dialog"]],
                "metadatas": [[{"timestamp": "2026-03-20T10:00:00"}]],
                "distances": [[0.05]],  # Sehr nah = Duplikat
            }
        )

        await memory.store_episode("Fast identischer Dialog")
        # add sollte NICHT aufgerufen werden wegen Duplikat
        chroma_mock.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_dedup_check_fails_gracefully(self, memory, chroma_mock):
        """Fehlgeschlagener Dedup-Check verhindert nicht das Speichern."""
        chroma_mock.query = MagicMock(side_effect=Exception("Query failed"))
        chroma_mock.add = MagicMock()

        await memory.store_episode("Neuer Dialog")
        # Trotz Dedup-Fehler sollte add aufgerufen werden
        chroma_mock.add.assert_called()

    @pytest.mark.asyncio
    async def test_dedup_passes_for_different_content(self, memory, chroma_mock):
        """Unterschiedliche Episode (distance >= 0.1) wird gespeichert."""
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [["Anderer Dialog"]],
                "metadatas": [[{"timestamp": "t"}]],
                "distances": [[0.8]],  # Weit entfernt = kein Duplikat
            }
        )

        await memory.store_episode("Komplett neuer Dialog")
        chroma_mock.add.assert_called()

    @pytest.mark.asyncio
    async def test_store_with_no_dedup_results(self, memory, chroma_mock):
        """Leere Dedup-Ergebnisse verhindern nicht das Speichern."""
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
            }
        )

        await memory.store_episode("Dialog ohne Duplikat")
        chroma_mock.add.assert_called()

    @pytest.mark.asyncio
    async def test_custom_metadata_preserved(self, memory, chroma_mock):
        """Benutzerdefinierte Metadaten bleiben in gespeicherten Chunks erhalten."""
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [[]],
                "distances": [[]],
                "metadatas": [[]],
            }
        )

        await memory.store_episode("Kurzer Dialog", {"person": "Max", "room": "Buero"})

        call_kwargs = chroma_mock.add.call_args[1]
        meta = call_kwargs["metadatas"][0]
        assert meta["person"] == "Max"
        assert meta["room"] == "Buero"
        assert meta["type"] == "conversation"
        assert "timestamp" in meta


# =====================================================================
# Conversation Continuity — Error Paths
# =====================================================================


class TestConversationContinuityErrors:
    """Tests fuer Fehlerbehandlung in Pending-Topics-Methoden."""

    @pytest.mark.asyncio
    async def test_mark_pending_redis_error(self, memory, redis_mock):
        """Redis-Fehler bei mark_conversation_pending wird gefangen."""
        redis_mock.hset = AsyncMock(side_effect=Exception("Redis write error"))
        await memory.mark_conversation_pending("Topic", "Context")
        # Kein Crash — Fehler wird geloggt

    @pytest.mark.asyncio
    async def test_get_pending_redis_error(self, memory, redis_mock):
        """Redis-Fehler bei get_pending_conversations wird gefangen."""
        redis_mock.hgetall = AsyncMock(side_effect=Exception("Redis read error"))
        result = await memory.get_pending_conversations()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_pending_invalid_json_skipped(self, memory, redis_mock):
        """Ungueltige JSON-Eintraege in pending topics werden uebersprungen."""
        redis_mock.hgetall = AsyncMock(
            return_value={
                "valid": json.dumps(
                    {
                        "topic": "Valid",
                        "timestamp": (
                            datetime.now(timezone.utc) - timedelta(minutes=30)
                        ).isoformat(),
                    }
                ),
                "invalid": "<<<NOT JSON>>>",
            }
        )

        result = await memory.get_pending_conversations()
        assert len(result) == 1
        assert result[0]["topic"] == "Valid"

    @pytest.mark.asyncio
    async def test_get_pending_no_timestamp_skipped(self, memory, redis_mock):
        """Eintraege ohne Timestamp werden uebersprungen."""
        redis_mock.hgetall = AsyncMock(
            return_value={
                "no_ts": json.dumps({"topic": "NoTimestamp"}),
            }
        )

        result = await memory.get_pending_conversations()
        assert result == []

    @pytest.mark.asyncio
    async def test_resolve_conversation_redis_error(self, memory, redis_mock):
        """Redis-Fehler bei resolve_conversation wird gefangen."""
        redis_mock.hdel = AsyncMock(side_effect=Exception("Redis delete error"))
        # Kein Crash
        await memory.resolve_conversation("Topic")


# =====================================================================
# store_episode — Retry Logic and Edge Cases
# =====================================================================


class TestStoreEpisodeRetry:
    """Tests fuer store_episode Timeout/Retry-Logik."""

    @pytest.fixture
    def memory(self, redis_mock, chroma_mock):
        with (
            patch("assistant.memory.yaml_config", {"timezone": "UTC"}),
            patch("assistant.memory.settings"),
        ):
            m = MemoryManager()
            m.redis = redis_mock
            m.chroma_collection = chroma_mock
            return m

    @pytest.mark.asyncio
    async def test_dedup_check_skips_similar_episode(self, memory, chroma_mock):
        """Skips storing when very similar episode already exists."""
        chroma_mock.query.return_value = {
            "documents": [["Similar episode"]],
            "distances": [[0.05]],  # Very close = duplicate
            "metadatas": [[]],
        }

        await memory.store_episode("Similar episode content")
        chroma_mock.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_dedup_check_failure_continues(self, memory, chroma_mock):
        """Dedup check failure doesn't prevent storage."""
        chroma_mock.query.side_effect = Exception("Dedup error")
        chroma_mock.add = MagicMock()

        await memory.store_episode("New episode")
        chroma_mock.add.assert_called()

    @pytest.mark.asyncio
    async def test_no_chroma_logs_warning(self, memory):
        """Without ChromaDB, logs a warning."""
        memory.chroma_collection = None
        await memory.store_episode("Test")  # No exception

    @pytest.mark.asyncio
    async def test_stores_with_metadata(self, memory, chroma_mock):
        """Stores episode with custom metadata."""
        chroma_mock.query.return_value = {
            "documents": [[]],
            "distances": [[]],
            "metadatas": [[]],
        }

        await memory.store_episode("Content", {"person": "Max", "room": "Office"})
        call_kwargs = chroma_mock.add.call_args[1]
        assert call_kwargs["metadatas"][0]["person"] == "Max"
        assert call_kwargs["metadatas"][0]["room"] == "Office"
        assert call_kwargs["metadatas"][0]["type"] == "conversation"


# =====================================================================
# _split_conversation Tests
# =====================================================================


class TestSplitConversation:
    """Tests fuer _split_conversation."""

    def test_short_text_returns_single_chunk(self):
        result = MemoryManager._split_conversation("Short text")
        assert result == ["Short text"]

    def test_empty_text_returns_empty(self):
        result = MemoryManager._split_conversation("")
        assert result == []

    def test_whitespace_only_returns_empty(self):
        result = MemoryManager._split_conversation("   ")
        assert result == []

    def test_long_text_splits_into_chunks(self):
        # Create text longer than chunk size (200 chars)
        long_text = "User: " + "a " * 150 + "Assistant: " + "b " * 150
        result = MemoryManager._split_conversation(long_text)
        assert len(result) > 1

    def test_speaker_boundaries(self):
        """Text is split at speaker change boundaries."""
        text = "User: Hallo! " + "a " * 100 + "Assistant: Hi! " + "b " * 100
        result = MemoryManager._split_conversation(text)
        assert len(result) >= 2


# =====================================================================
# close Tests
# =====================================================================


class TestClose:
    """Tests fuer close()."""

    @pytest.mark.asyncio
    async def test_closes_redis(self, memory, redis_mock):
        result = await memory.close()
        redis_mock.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_redis_no_error(self):
        with (
            patch("assistant.memory.yaml_config", {"timezone": "UTC"}),
            patch("assistant.memory.settings"),
        ):
            m = MemoryManager()
        await m.close()  # No exception


# =====================================================================
# clear_all_memory Tests
# =====================================================================


class TestClearAllMemory:
    """Tests fuer clear_all_memory."""

    @pytest.fixture
    def memory(self, redis_mock, chroma_mock):
        with (
            patch("assistant.memory.yaml_config", {"timezone": "UTC"}),
            patch("assistant.memory.settings"),
        ):
            m = MemoryManager()
            m.redis = redis_mock
            m.chroma_collection = chroma_mock
            m._chroma_client = MagicMock()
            m.semantic = MagicMock()
            m.semantic.clear_all = AsyncMock(return_value=5)
            return m

    @pytest.mark.asyncio
    async def test_no_redis(self):
        """Works when no Redis."""
        with (
            patch("assistant.memory.yaml_config", {"timezone": "UTC"}),
            patch("assistant.memory.settings"),
        ):
            m = MemoryManager()
        m.semantic = MagicMock()
        m.semantic.clear_all = AsyncMock(return_value=0)

        result = await m.clear_all_memory()
        assert result["working_cleared"] is False


# =====================================================================
# factory_reset Tests
# =====================================================================


class TestFactoryReset:
    """Tests fuer factory_reset."""

    @pytest.mark.asyncio
    async def test_no_redis_handles_gracefully(self):
        """Factory reset works without Redis."""
        with (
            patch("assistant.memory.yaml_config", {"timezone": "UTC"}),
            patch("assistant.memory.settings"),
        ):
            m = MemoryManager()
        m.semantic = MagicMock()
        m.semantic.clear_all = AsyncMock(return_value=0)

        result = await m.factory_reset()
        assert (
            "redis_keys_deleted" not in result
            or result.get("redis_keys_deleted", 0) == 0
        )


# =====================================================================
# delete_episodes Tests
# =====================================================================


class TestDeleteEpisodes:
    """Tests fuer delete_episodes."""

    @pytest.fixture
    def memory(self, redis_mock, chroma_mock):
        with (
            patch("assistant.memory.yaml_config", {"timezone": "UTC"}),
            patch("assistant.memory.settings"),
        ):
            m = MemoryManager()
            m.redis = redis_mock
            m.chroma_collection = chroma_mock
            return m

    @pytest.mark.asyncio
    async def test_deletes_episodes(self, memory, chroma_mock):
        result = await memory.delete_episodes(["ep_1", "ep_2"])
        assert result == 2
        chroma_mock.delete.assert_called_once_with(ids=["ep_1", "ep_2"])

    @pytest.mark.asyncio
    async def test_empty_list_returns_zero(self, memory, chroma_mock):
        result = await memory.delete_episodes([])
        assert result == 0
        chroma_mock.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_chroma_returns_zero(self, memory):
        memory.chroma_collection = None
        result = await memory.delete_episodes(["ep_1"])
        assert result == 0

    @pytest.mark.asyncio
    async def test_chroma_error_returns_zero(self, memory, chroma_mock):
        chroma_mock.delete.side_effect = Exception("ChromaDB error")
        result = await memory.delete_episodes(["ep_1"])
        assert result == 0


# =====================================================================
# get_conversations_for_date Tests
# =====================================================================


class TestGetConversationsForDate:
    """Tests fuer get_conversations_for_date."""

    @pytest.fixture
    def memory(self, redis_mock):
        with (
            patch("assistant.memory.yaml_config", {"timezone": "UTC"}),
            patch("assistant.memory.settings"),
        ):
            m = MemoryManager()
            m.redis = redis_mock
            return m

    @pytest.mark.asyncio
    async def test_returns_archived_conversations(self, memory, redis_mock):
        entries = [
            json.dumps(
                {"role": "user", "content": "Hello", "timestamp": "2025-06-15T10:00:00"}
            ),
            json.dumps(
                {
                    "role": "assistant",
                    "content": "Hi!",
                    "timestamp": "2025-06-15T10:01:00",
                }
            ),
        ]
        redis_mock.lrange = AsyncMock(return_value=entries)

        result = await memory.get_conversations_for_date("2025-06-15")
        assert len(result) == 2
        assert result[0]["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_no_redis_returns_empty(self):
        with (
            patch("assistant.memory.yaml_config", {"timezone": "UTC"}),
            patch("assistant.memory.settings"),
        ):
            m = MemoryManager()
        result = await m.get_conversations_for_date("2025-06-15")
        assert result == []

    @pytest.mark.asyncio
    async def test_invalid_json_skipped(self, memory, redis_mock):
        entries = ["not json", json.dumps({"role": "user", "content": "Valid"})]
        redis_mock.lrange = AsyncMock(return_value=entries)

        result = await memory.get_conversations_for_date("2025-06-15")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_empty_entries_skipped(self, memory, redis_mock):
        entries = ["", None, json.dumps({"role": "user", "content": "Valid"})]
        redis_mock.lrange = AsyncMock(return_value=entries)

        result = await memory.get_conversations_for_date("2025-06-15")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_redis_error_returns_empty(self, memory, redis_mock):
        redis_mock.lrange = AsyncMock(side_effect=Exception("Redis error"))
        result = await memory.get_conversations_for_date("2025-06-15")
        assert result == []


# =====================================================================
# search_episodes_by_time Tests
# =====================================================================


class TestSearchEpisodesByTime:
    """Tests fuer search_episodes_by_time."""

    @pytest.fixture
    def memory(self, redis_mock, chroma_mock):
        with (
            patch("assistant.memory.yaml_config", {"timezone": "UTC"}),
            patch("assistant.memory.settings"),
        ):
            m = MemoryManager()
            m.redis = redis_mock
            m.chroma_collection = chroma_mock
            return m

    @pytest.mark.asyncio
    async def test_no_chroma_returns_empty(self, memory):
        memory.chroma_collection = None
        result = await memory.search_episodes_by_time(
            "test", "2025-01-01", "2025-01-31"
        )
        assert result == []
