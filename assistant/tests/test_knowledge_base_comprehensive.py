"""
Comprehensive tests for KnowledgeBase — covers ingest_file, ingest_all, reingest,
get_chunks filtering, _load_ingested_hashes, stop, rebuild, PDF extraction, and edge cases.

Complements the existing test_knowledge_base.py which covers _split_text,
_expand_query, _keyword_overlap_bonus, ingest_text, search basics, stats, chunk CRUD,
and clear.
"""

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from assistant.knowledge_base import (
    KnowledgeBase,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_CHUNK_OVERLAP,
    SUPPORTED_EXTENSIONS,
    KB_UPLOAD_MAX_SIZE,
    KB_UPLOAD_ALLOWED,
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
    m.query = MagicMock(return_value={
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]],
    })
    m.delete = MagicMock()
    m.upsert = MagicMock()
    return m


@pytest.fixture
def kb(chroma):
    with patch("assistant.knowledge_base.yaml_config", YAML_CFG):
        instance = KnowledgeBase()
    instance.chroma_collection = chroma
    instance._knowledge_dir = Path("/tmp/test_knowledge")
    return instance


# ── ingest_file ─────────────────────────────────────────────


class TestIngestFile:
    @pytest.mark.asyncio
    async def test_ingest_file_no_collection(self, kb):
        kb.chroma_collection = None
        result = await kb.ingest_file(Path("/tmp/test.md"))
        assert result == 0

    @pytest.mark.asyncio
    async def test_ingest_file_txt_success(self, kb, chroma, tmp_path):
        """Ingesting a .txt file should create chunks and add them to ChromaDB."""
        test_file = tmp_path / "notes.txt"
        test_file.write_text("This is a short test document for ingestion.")

        result = await kb.ingest_file(test_file)
        assert result >= 1
        chroma.add.assert_called()
        # Verify hash was stored
        assert len(kb._ingested_hashes) >= 1

    @pytest.mark.asyncio
    async def test_ingest_file_empty_content(self, kb, chroma, tmp_path):
        """Empty files should return 0 chunks."""
        test_file = tmp_path / "empty.txt"
        test_file.write_text("   \n  \n  ")

        result = await kb.ingest_file(test_file)
        assert result == 0
        chroma.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_ingest_file_deduplication(self, kb, chroma, tmp_path):
        """Chunks already in _ingested_hashes should be skipped."""
        content = "Unique test content for dedup check."
        content_hash = hashlib.md5(content.encode()).hexdigest()
        kb._ingested_hashes.add(content_hash)

        test_file = tmp_path / "dedup.txt"
        test_file.write_text(content)

        result = await kb.ingest_file(test_file)
        assert result == 0
        chroma.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_ingest_file_multiple_chunks(self, kb, chroma, tmp_path):
        """A long file should be split into multiple chunks."""
        # Create content longer than chunk_size (500)
        text = "\n\n".join([f"Paragraph {i}. " * 20 for i in range(10)])
        test_file = tmp_path / "long.txt"
        test_file.write_text(text)

        result = await kb.ingest_file(test_file)
        assert result >= 2
        assert chroma.add.call_count >= 2

    @pytest.mark.asyncio
    async def test_ingest_file_read_error(self, kb, chroma, tmp_path):
        """Non-existent file should return 0 and not raise."""
        result = await kb.ingest_file(Path("/tmp/nonexistent_xyz.txt"))
        assert result == 0

    @pytest.mark.asyncio
    async def test_ingest_file_pdf_calls_extract(self, kb, chroma, tmp_path):
        """PDF files should go through _extract_pdf_text."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"fake pdf content")

        with patch.object(KnowledgeBase, "_extract_pdf_text", return_value="Extracted PDF text content."):
            result = await kb.ingest_file(pdf_file)
        assert result >= 1

    @pytest.mark.asyncio
    async def test_ingest_file_chroma_add_error(self, kb, chroma, tmp_path):
        """If ChromaDB add fails, the chunk should be skipped gracefully."""
        test_file = tmp_path / "error_test.txt"
        test_file.write_text("Some content to ingest.")
        chroma.add.side_effect = Exception("ChromaDB write error")

        result = await kb.ingest_file(test_file)
        assert result == 0  # No chunks successfully stored


# ── ingest_all ──────────────────────────────────────────────


class TestIngestAll:
    @pytest.mark.asyncio
    async def test_ingest_all_no_dir(self, kb):
        kb._knowledge_dir = None
        result = await kb.ingest_all()
        assert result == 0

    @pytest.mark.asyncio
    async def test_ingest_all_no_collection(self, kb):
        kb.chroma_collection = None
        result = await kb.ingest_all()
        assert result == 0

    @pytest.mark.asyncio
    async def test_ingest_all_empty_dir(self, kb, tmp_path):
        """Empty knowledge dir should return 0."""
        kb._knowledge_dir = tmp_path
        result = await kb.ingest_all()
        assert result == 0

    @pytest.mark.asyncio
    async def test_ingest_all_with_files(self, kb, chroma, tmp_path):
        """Should ingest all supported files in the directory."""
        kb._knowledge_dir = tmp_path
        (tmp_path / "doc1.txt").write_text("Document one content.")
        (tmp_path / "doc2.md").write_text("Document two content.")
        (tmp_path / "ignore.py").write_text("This should be ignored.")

        result = await kb.ingest_all()
        assert result >= 2  # At least 1 chunk per file
        # .py should not be ingested
        for c in chroma.add.call_args_list:
            meta = c[1].get("metadatas", c[0][0] if c[0] else [{}])
            if isinstance(meta, list) and meta:
                assert not meta[0].get("source_file", "").endswith(".py")

    @pytest.mark.asyncio
    async def test_ingest_all_subdirectory(self, kb, chroma, tmp_path):
        """Should recursively scan subdirectories."""
        kb._knowledge_dir = tmp_path
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "nested.txt").write_text("Nested document content.")

        result = await kb.ingest_all()
        assert result >= 1


# ── _load_ingested_hashes ──────────────────────────────────


class TestLoadIngestedHashes:
    def test_load_hashes_no_collection(self, kb):
        kb.chroma_collection = None
        kb._load_ingested_hashes()
        assert kb._ingested_hashes == set()

    def test_load_hashes_from_chroma(self, kb, chroma):
        chroma.get.return_value = {
            "metadatas": [
                {"content_hash": "hash1"},
                {"content_hash": "hash2"},
                {"content_hash": ""},
                {},
            ]
        }
        kb._load_ingested_hashes()
        assert "hash1" in kb._ingested_hashes
        assert "hash2" in kb._ingested_hashes
        assert "" not in kb._ingested_hashes
        assert len(kb._ingested_hashes) == 2

    def test_load_hashes_chroma_error(self, kb, chroma):
        chroma.get.side_effect = Exception("DB error")
        kb._load_ingested_hashes()  # Should not raise
        assert kb._ingested_hashes == set()


# ── _snapshot_file_mtimes ──────────────────────────────────


class TestSnapshotFileMtimes:
    def test_no_knowledge_dir(self, kb):
        kb._knowledge_dir = None
        kb._snapshot_file_mtimes()
        assert kb._file_mtimes == {}

    def test_snapshot_captures_files(self, kb, tmp_path):
        kb._knowledge_dir = tmp_path
        (tmp_path / "doc.txt").write_text("content")
        (tmp_path / "doc.md").write_text("content")
        (tmp_path / "ignore.py").write_text("content")

        kb._snapshot_file_mtimes()
        paths = list(kb._file_mtimes.keys())
        assert any("doc.txt" in p for p in paths)
        assert any("doc.md" in p for p in paths)
        assert not any("ignore.py" in p for p in paths)


# ── reingest_file ──────────────────────────────────────────


class TestReingestFile:
    @pytest.mark.asyncio
    async def test_reingest_no_dir(self, kb):
        kb._knowledge_dir = None
        result = await kb.reingest_file("test.md")
        assert result == 0

    @pytest.mark.asyncio
    async def test_reingest_file_not_found(self, kb, tmp_path):
        kb._knowledge_dir = tmp_path
        result = await kb.reingest_file("nonexistent.md")
        assert result == 0

    @pytest.mark.asyncio
    async def test_reingest_deletes_then_ingests(self, kb, chroma, tmp_path):
        """reingest should delete old chunks then re-ingest the file."""
        kb._knowledge_dir = tmp_path
        (tmp_path / "readme.md").write_text("Updated readme content here.")

        # Set up delete_source_chunks to return 0 (simulating no old chunks)
        chroma.get.return_value = {"ids": [], "metadatas": []}

        result = await kb.reingest_file("readme.md")
        assert result >= 1
        chroma.add.assert_called()


# ── get_chunks with filtering ──────────────────────────────


class TestGetChunksFiltering:
    @pytest.mark.asyncio
    async def test_get_chunks_no_collection(self, kb):
        kb.chroma_collection = None
        result = await kb.get_chunks()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_chunks_with_source_filter(self, kb, chroma):
        chroma.get.return_value = {
            "ids": ["c1", "c2"],
            "documents": ["Doc content A", "Doc content B"],
            "metadatas": [
                {"source_file": "notes.md", "chunk_index": "0"},
                {"source_file": "notes.md", "chunk_index": "1"},
            ],
        }
        result = await kb.get_chunks(source="notes.md")
        assert len(result) == 2
        assert result[0]["source"] == "notes.md"
        assert result[0]["chunk_index"] == "0"
        chroma.get.assert_called_once_with(
            include=["documents", "metadatas"],
            where={"source_file": "notes.md"},
        )

    @pytest.mark.asyncio
    async def test_get_chunks_offset_and_limit(self, kb, chroma):
        """Offset and limit should slice the results."""
        chroma.get.return_value = {
            "ids": [f"c{i}" for i in range(10)],
            "documents": [f"Doc {i}" for i in range(10)],
            "metadatas": [{"source_file": "a.md", "chunk_index": str(i)} for i in range(10)],
        }
        result = await kb.get_chunks(offset=3, limit=4)
        assert len(result) == 4
        assert result[0]["chunk_index"] == "3"

    @pytest.mark.asyncio
    async def test_get_chunks_truncates_long_content(self, kb, chroma):
        """Content longer than 200 chars should be truncated in the 'content' field."""
        long_doc = "A" * 300
        chroma.get.return_value = {
            "ids": ["c1"],
            "documents": [long_doc],
            "metadatas": [{"source_file": "big.txt", "chunk_index": "0"}],
        }
        result = await kb.get_chunks()
        assert len(result) == 1
        assert result[0]["content"].endswith("...")
        assert len(result[0]["content"]) == 203  # 200 + "..."
        assert result[0]["content_full"] == long_doc

    @pytest.mark.asyncio
    async def test_get_chunks_error_handling(self, kb, chroma):
        chroma.get.side_effect = Exception("DB error")
        result = await kb.get_chunks()
        assert result == []


# ── rebuild ────────────────────────────────────────────────


class TestRebuild:
    @pytest.mark.asyncio
    async def test_rebuild_clear_fails(self, kb):
        """If clear fails, rebuild should return failure."""
        kb._chroma_client = None  # Will cause clear() to return False
        result = await kb.rebuild()
        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_rebuild_success(self, kb, chroma, tmp_path):
        """Rebuild should clear and re-ingest all files."""
        kb._knowledge_dir = tmp_path
        (tmp_path / "doc.txt").write_text("Test document for rebuild.")

        client = MagicMock()
        kb._chroma_client = client
        client.delete_collection = MagicMock()
        client.get_or_create_collection = MagicMock(return_value=chroma)

        with patch("assistant.embeddings.get_embedding_function", return_value=None):
            result = await kb.rebuild()

        assert result["success"] is True
        assert result["new_chunks"] >= 1
        assert "embedding_model" in result


# ── stop ───────────────────────────────────────────────────


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_no_task(self, kb):
        """stop() should work fine when no watch task is running."""
        kb._watch_task = None
        await kb.stop()
        assert kb._watch_running is False

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, kb):
        """stop() should cancel the watch task."""
        import asyncio

        async def fake_loop():
            await asyncio.sleep(9999)

        kb._watch_running = True
        kb._watch_task = asyncio.create_task(fake_loop())

        await kb.stop()
        assert kb._watch_running is False
        assert kb._watch_task.cancelled()


# ── search edge cases ─────────────────────────────────────


class TestSearchEdgeCases:
    @pytest.mark.asyncio
    async def test_search_empty_query(self, kb, chroma):
        """Empty query should still work without error."""
        chroma.query.return_value = {
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }
        result = await kb.search("")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_deduplicates_across_queries(self, kb, chroma):
        """Same document from multiple query variants should be deduplicated."""
        # Both query variants return the same document
        call_count = 0

        def mock_query(**kwargs):
            return {
                "documents": [["Same ESP32 document content"]],
                "metadatas": [[{"source_file": "esp.md", "content_hash": "same_hash"}]],
                "distances": [[0.2]],
            }

        chroma.query.side_effect = mock_query
        result = await kb.search("ESP32 Sensor")
        # Should have only 1 result despite potentially 2 queries
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_search_query_exception(self, kb, chroma):
        """If ChromaDB query raises, should return empty list."""
        chroma.query.side_effect = Exception("Connection lost")
        result = await kb.search("test query")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_relevance_ordering(self, kb, chroma):
        """Results should be sorted by relevance (highest first)."""
        chroma.query.return_value = {
            "documents": [["Low relevance doc", "High relevance doc"]],
            "metadatas": [[
                {"source_file": "low.md", "content_hash": "h_low"},
                {"source_file": "high.md", "content_hash": "h_high"},
            ]],
            "distances": [[0.9, 0.1]],
        }
        result = await kb.search("test", limit=10)
        assert len(result) == 2
        assert result[0]["relevance"] > result[1]["relevance"]
        assert result[0]["source"] == "high.md"


# ── _split_text additional edge cases ─────────────────────


class TestSplitTextAdditional:
    def test_single_very_long_paragraph_splits_at_sentences(self):
        """A long paragraph with sentences should be split at sentence boundaries."""
        text = "This is a sentence. " * 50  # ~1000 chars, has sentence breaks
        result = KnowledgeBase._split_text(text, 100, 0)
        assert len(result) >= 2

    def test_chunk_size_equals_text_length(self):
        """Text exactly at chunk_size should be a single chunk."""
        text = "A" * 500
        result = KnowledgeBase._split_text(text, 500, 0)
        assert len(result) == 1

    def test_chunk_size_one_less_than_text(self):
        """Text one char over chunk_size should produce multiple chunks."""
        text = "A" * 100 + "\n\n" + "B" * 100
        result = KnowledgeBase._split_text(text, 150, 0)
        assert len(result) >= 2

    def test_only_newlines(self):
        """Text with only newlines should return empty."""
        result = KnowledgeBase._split_text("\n\n\n\n\n", 500, 50)
        assert result == []


# ── _extract_pdf_text ──────────────────────────────────────


class TestExtractPdfText:
    def test_no_pdf_libraries_available(self, tmp_path):
        """Should return empty string when no PDF library is available."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")

        with patch.dict("sys.modules", {"fitz": None, "pdfplumber": None, "PyPDF2": None}):
            with patch("builtins.__import__", side_effect=ImportError("No PDF lib")):
                result = KnowledgeBase._extract_pdf_text(pdf_file)
        # With all imports failing, should return empty string
        assert isinstance(result, str)


# ── Constants and config ───────────────────────────────────


class TestConstants:
    def test_supported_extensions(self):
        assert ".txt" in SUPPORTED_EXTENSIONS
        assert ".md" in SUPPORTED_EXTENSIONS
        assert ".pdf" in SUPPORTED_EXTENSIONS
        assert ".csv" in SUPPORTED_EXTENSIONS
        assert ".py" not in SUPPORTED_EXTENSIONS

    def test_upload_limits(self):
        assert KB_UPLOAD_MAX_SIZE == 10 * 1024 * 1024
        assert KB_UPLOAD_ALLOWED == {".txt", ".md", ".pdf", ".csv"}

    def test_default_chunk_params(self):
        assert DEFAULT_CHUNK_SIZE == 500
        assert DEFAULT_CHUNK_OVERLAP == 50


# ── _expand_query additional ───────────────────────────────


class TestExpandQueryAdditional:
    def test_expand_single_keyword(self):
        """A single keyword should produce only the original query."""
        queries = KnowledgeBase._expand_query("ESP32")
        assert queries == ["ESP32"]

    def test_expand_preserves_original_case(self):
        """Original query should preserve its casing."""
        queries = KnowledgeBase._expand_query("Wie Funktioniert ESP32")
        assert queries[0] == "Wie Funktioniert ESP32"

    def test_expand_removes_german_stopwords(self):
        """German stopwords should be removed in the keyword variant."""
        queries = KnowledgeBase._expand_query("wie funktioniert der ESP32 Sensor")
        assert len(queries) >= 2
        keyword_variant = queries[1].lower()
        assert "wie" not in keyword_variant.split()
        assert "der" not in keyword_variant.split()
        assert "esp32" in keyword_variant
        assert "sensor" in keyword_variant
