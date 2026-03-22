"""
Tests fuer KnowledgeBase — RAG-System, Chunks, Suche.
"""

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.knowledge_base import (
    KnowledgeBase,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_CHUNK_OVERLAP,
    SUPPORTED_EXTENSIONS,
    KB_UPLOAD_MAX_SIZE,
)


YAML_CFG = {
    "knowledge_base": {
        "enabled": True,
        "chunk_size": 500,
        "chunk_overlap": 50,
        "max_distance": 1.2,
        "auto_ingest": False,
        "watch_interval_seconds": 0,
    },
}


@pytest.fixture
def chroma():
    m = MagicMock()
    m.add = MagicMock()
    m.count = MagicMock(return_value=0)
    m.get = MagicMock(return_value={"ids": [], "metadatas": [], "documents": []})
    m.query = MagicMock(
        return_value={
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }
    )
    m.delete = MagicMock()
    return m


@pytest.fixture
def kb(chroma):
    with patch("assistant.knowledge_base.yaml_config", YAML_CFG):
        kb = KnowledgeBase()
    kb.chroma_collection = chroma
    kb._knowledge_dir = Path("/tmp/test_knowledge")
    return kb


# ── Text Splitting ───────────────────────────────────────


class TestSplitText:
    def test_short_text_single_chunk(self):
        result = KnowledgeBase._split_text("Hello world", 500, 50)
        assert len(result) == 1
        assert result[0] == "Hello world"

    def test_empty_text(self):
        result = KnowledgeBase._split_text("", 500, 50)
        assert result == []

    def test_whitespace_only(self):
        result = KnowledgeBase._split_text("   \n\n  ", 500, 50)
        assert result == []

    def test_splits_at_paragraphs(self):
        text = "Paragraph 1.\n\nParagraph 2.\n\nParagraph 3."
        result = KnowledgeBase._split_text(text, 30, 0)
        assert len(result) >= 2

    def test_overlap_added(self):
        # Generate text with paragraphs that exceed chunk size
        text = "A" * 100 + "\n\n" + "B" * 100 + "\n\n" + "C" * 100
        result = KnowledgeBase._split_text(text, 120, 20)
        assert len(result) >= 2
        # Check that overlap marker exists in subsequent chunks
        if len(result) > 1:
            assert (
                "..." in result[1]
                or result[1].startswith(result[0][-20:])
                or len(result[1]) > 100
            )

    def test_long_paragraph_splits_at_sentences(self):
        text = "This is sentence one. This is sentence two. This is sentence three. This is sentence four. And another very long sentence here."
        result = KnowledgeBase._split_text(text, 60, 0)
        assert len(result) >= 2


# ── Query Expansion ──────────────────────────────────────


class TestExpandQuery:
    def test_expand_simple(self):
        queries = KnowledgeBase._expand_query("wie funktioniert das")
        assert queries[0] == "wie funktioniert das"
        assert len(queries) >= 1

    def test_expand_with_keywords(self):
        queries = KnowledgeBase._expand_query("wie funktioniert der ESP32 Sensor")
        assert len(queries) >= 1
        # Should have keyword variant without stopwords
        if len(queries) > 1:
            assert "wie" not in queries[1]
            assert "der" not in queries[1]

    def test_expand_all_stopwords(self):
        queries = KnowledgeBase._expand_query("wie ist das")
        # All words are stopwords or short, so only original query
        assert len(queries) >= 1


# ── Keyword Overlap Bonus ────────────────────────────────


class TestKeywordOverlap:
    def test_full_overlap(self):
        bonus = KnowledgeBase._keyword_overlap_bonus(
            "ESP32 Sensor", "Der ESP32 Sensor misst Temperatur"
        )
        assert bonus > 0.5

    def test_no_overlap(self):
        bonus = KnowledgeBase._keyword_overlap_bonus(
            "Raspberry Pi", "Arduino Nano Board"
        )
        assert bonus == 0.0

    def test_partial_overlap(self):
        bonus = KnowledgeBase._keyword_overlap_bonus(
            "ESP32 Temperatur Sensor", "ESP32 misst Druck"
        )
        assert 0.0 < bonus < 1.0

    def test_short_words_ignored(self):
        bonus = KnowledgeBase._keyword_overlap_bonus("an", "an der Wand")
        assert bonus == 0.0


# ── Ingest Text ──────────────────────────────────────────


class TestIngestText:
    @pytest.mark.asyncio
    async def test_ingest_text_empty(self, kb):
        result = await kb.ingest_text("")
        assert result == 0

    @pytest.mark.asyncio
    async def test_ingest_text_no_collection(self):
        with patch("assistant.knowledge_base.yaml_config", YAML_CFG):
            kb = KnowledgeBase()
        kb.chroma_collection = None
        result = await kb.ingest_text("Some text")
        assert result == 0

    @pytest.mark.asyncio
    async def test_ingest_text_success(self, kb, chroma):
        result = await kb.ingest_text("This is a test document about ESP32 sensors.")
        assert result >= 1
        chroma.add.assert_called()

    @pytest.mark.asyncio
    async def test_ingest_text_dedup(self, kb, chroma):
        text = "Exact same text"
        h = hashlib.md5(text.encode()).hexdigest()
        kb._ingested_hashes.add(h)
        result = await kb.ingest_text(text)
        assert result == 0


# ── Search ───────────────────────────────────────────────


class TestSearch:
    @pytest.mark.asyncio
    async def test_search_no_collection(self):
        with patch("assistant.knowledge_base.yaml_config", YAML_CFG):
            kb = KnowledgeBase()
        kb.chroma_collection = None
        result = await kb.search("test")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_no_results(self, kb, chroma):
        chroma.query.return_value = {
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }
        result = await kb.search("nonexistent")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_with_results(self, kb, chroma):
        chroma.query.return_value = {
            "documents": [["Doc about ESP32"]],
            "metadatas": [[{"source_file": "test.md", "content_hash": "abc"}]],
            "distances": [[0.3]],
        }
        result = await kb.search("ESP32")
        assert len(result) >= 1
        assert result[0]["source"] == "test.md"
        assert result[0]["relevance"] > 0

    @pytest.mark.asyncio
    async def test_search_filters_by_distance(self, kb, chroma):
        chroma.query.return_value = {
            "documents": [["Irrelevant doc"]],
            "metadatas": [[{"source_file": "x.md", "content_hash": "xyz"}]],
            "distances": [[2.0]],  # Beyond max_distance
        }
        result = await kb.search("something")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_respects_limit(self, kb, chroma):
        docs = [f"Doc {i}" for i in range(10)]
        metas = [
            {"source_file": f"f{i}.md", "content_hash": f"h{i}"} for i in range(10)
        ]
        dists = [0.1 + i * 0.05 for i in range(10)]
        chroma.query.return_value = {
            "documents": [docs],
            "metadatas": [metas],
            "distances": [dists],
        }
        result = await kb.search("test", limit=3)
        assert len(result) <= 3


# ── Stats ────────────────────────────────────────────────


class TestStats:
    @pytest.mark.asyncio
    async def test_get_stats_no_collection(self):
        with patch("assistant.knowledge_base.yaml_config", YAML_CFG):
            kb = KnowledgeBase()
        kb.chroma_collection = None
        stats = await kb.get_stats()
        assert stats["enabled"] is False

    @pytest.mark.asyncio
    async def test_get_stats_with_data(self, kb, chroma):
        chroma.count.return_value = 42
        chroma.get.return_value = {
            "metadatas": [
                {"source_file": "a.md"},
                {"source_file": "b.txt"},
                {"source_file": "a.md"},
            ]
        }
        stats = await kb.get_stats()
        assert stats["enabled"] is True
        assert stats["total_chunks"] == 42
        assert "a.md" in stats["sources"]
        assert "b.txt" in stats["sources"]


# ── Chunks CRUD ──────────────────────────────────────────


class TestChunksCRUD:
    @pytest.mark.asyncio
    async def test_get_chunks_empty(self, kb, chroma):
        chroma.get.return_value = {"ids": [], "documents": [], "metadatas": []}
        result = await kb.get_chunks()
        assert result == []

    @pytest.mark.asyncio
    async def test_delete_chunks(self, kb, chroma):
        result = await kb.delete_chunks(["id1", "id2"])
        assert result == 2
        chroma.delete.assert_called_once_with(ids=["id1", "id2"])

    @pytest.mark.asyncio
    async def test_delete_chunks_empty_list(self, kb):
        result = await kb.delete_chunks([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_delete_source_chunks(self, kb, chroma):
        chroma.get.return_value = {
            "ids": ["c1", "c2"],
            "metadatas": [{"content_hash": "h1"}, {"content_hash": "h2"}],
        }
        kb._ingested_hashes = {"h1", "h2", "h3"}
        result = await kb.delete_source_chunks("test.md")
        assert result == 2
        assert "h1" not in kb._ingested_hashes
        assert "h3" in kb._ingested_hashes

    @pytest.mark.asyncio
    async def test_delete_source_chunks_not_found(self, kb, chroma):
        chroma.get.return_value = {"ids": [], "metadatas": []}
        result = await kb.delete_source_chunks("nonexistent.md")
        assert result == 0


# ── Clear & Rebuild ──────────────────────────────────────


class TestClearRebuild:
    @pytest.mark.asyncio
    async def test_clear_no_client(self):
        with patch("assistant.knowledge_base.yaml_config", YAML_CFG):
            kb = KnowledgeBase()
        kb._chroma_client = None
        result = await kb.clear()
        assert result is False

    @pytest.mark.asyncio
    async def test_clear_success(self, kb):
        client = MagicMock()
        kb._chroma_client = client
        col = MagicMock()
        client.get_or_create_collection.return_value = col

        with patch("assistant.embeddings.get_embedding_function", return_value=None):
            result = await kb.clear()
        assert result is True
        assert kb._ingested_hashes == set()
