"""Tests for assistant.workshop_library — WorkshopLibrary class."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.workshop_library import WorkshopLibrary, WORKSHOP_DOCS_DIR, SUPPORTED_EXTENSIONS


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def lib():
    """WorkshopLibrary with mocked collection."""
    wl = WorkshopLibrary()
    wl.chroma_client = MagicMock()
    wl.collection = MagicMock()
    wl.collection.count.return_value = 10
    wl.embedding_fn = None
    return wl


@pytest.fixture
def lib_uninit():
    """WorkshopLibrary without initialization."""
    return WorkshopLibrary()


# ── Constants ─────────────────────────────────────────────

def test_supported_extensions():
    assert SUPPORTED_EXTENSIONS == {".pdf", ".txt", ".md"}


def test_collection_name():
    assert WorkshopLibrary.COLLECTION_NAME == "workshop_library"


def test_chunk_size():
    assert WorkshopLibrary.CHUNK_SIZE == 1500


def test_chunk_overlap():
    assert WorkshopLibrary.CHUNK_OVERLAP == 200


# ── __init__ ──────────────────────────────────────────────

def test_init_defaults():
    wl = WorkshopLibrary()
    assert wl.chroma_client is None
    assert wl.collection is None
    assert wl.embedding_fn is None


# ── initialize ────────────────────────────────────────────

@pytest.mark.asyncio
@patch.object(Path, "mkdir")
async def test_initialize(mock_mkdir):
    wl = WorkshopLibrary()
    client = MagicMock()
    collection = MagicMock()
    collection.count.return_value = 5
    client.get_or_create_collection.return_value = collection
    ef = MagicMock()

    await wl.initialize(client, ef)

    assert wl.chroma_client is client
    assert wl.embedding_fn is ef
    assert wl.collection is collection
    client.get_or_create_collection.assert_called_once()


# ── _chunk_text ───────────────────────────────────────────

def test_chunk_text_short():
    wl = WorkshopLibrary()
    text = "Hello world"
    chunks = wl._chunk_text(text)
    assert len(chunks) == 1
    assert chunks[0] == "Hello world"


def test_chunk_text_long():
    wl = WorkshopLibrary()
    text = "a" * 3000
    chunks = wl._chunk_text(text)
    assert len(chunks) >= 2
    # First chunk should be CHUNK_SIZE chars
    assert len(chunks[0]) == WorkshopLibrary.CHUNK_SIZE


def test_chunk_text_overlap():
    wl = WorkshopLibrary()
    text = "a" * 2000
    chunks = wl._chunk_text(text)
    # With overlap, second chunk starts at CHUNK_SIZE - CHUNK_OVERLAP
    assert len(chunks) >= 2


def test_chunk_text_empty():
    wl = WorkshopLibrary()
    chunks = wl._chunk_text("")
    assert chunks == []


def test_chunk_text_whitespace_only_chunks_skipped():
    wl = WorkshopLibrary()
    # Create text where one chunk would be whitespace
    text = "a" * 1500 + " " * 1500
    chunks = wl._chunk_text(text)
    # The whitespace chunk should be skipped
    for chunk in chunks:
        assert chunk.strip() != ""


# ── ingest_document ───────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_document_no_collection(lib_uninit):
    result = await lib_uninit.ingest_document("/tmp/test.txt")
    assert result["status"] == "error"
    assert "nicht initialisiert" in result["message"]


@pytest.mark.asyncio
async def test_ingest_document_file_not_found(lib):
    result = await lib.ingest_document("/nonexistent/file.txt")
    assert result["status"] == "error"
    assert "nicht gefunden" in result["message"]


@pytest.mark.asyncio
async def test_ingest_document_unsupported_extension(lib, tmp_path):
    f = tmp_path / "test.docx"
    f.write_text("content")
    result = await lib.ingest_document(str(f))
    assert result["status"] == "error"
    assert "Nicht unterstuetzt" in result["message"]


@pytest.mark.asyncio
async def test_ingest_document_empty_file(lib, tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("   ")
    result = await lib.ingest_document(str(f))
    assert result["status"] == "error"
    assert "leer" in result["message"]


@pytest.mark.asyncio
async def test_ingest_document_txt_success(lib, tmp_path):
    f = tmp_path / "manual.txt"
    f.write_text("This is a technical manual with useful content.")
    result = await lib.ingest_document(str(f))
    assert result["status"] == "ok"
    assert result["document"] == "manual.txt"
    assert result["chunks"] >= 1
    lib.collection.upsert.assert_called_once()


@pytest.mark.asyncio
async def test_ingest_document_with_embedding_fn(lib, tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("Some content for embedding.")
    lib.embedding_fn = MagicMock(return_value=[0.1] * 384)
    result = await lib.ingest_document(str(f))
    assert result["status"] == "ok"
    # Should call upsert with embeddings
    call_kwargs = lib.collection.upsert.call_args
    assert "embeddings" in call_kwargs.kwargs or len(call_kwargs.args) > 3


@pytest.mark.asyncio
async def test_ingest_document_md_success(lib, tmp_path):
    f = tmp_path / "guide.md"
    f.write_text("# Guide\n\nStep 1: Do something.")
    result = await lib.ingest_document(str(f))
    assert result["status"] == "ok"
    assert result["document"] == "guide.md"


@pytest.mark.asyncio
async def test_ingest_document_pdf(lib, tmp_path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4 fake pdf content")
    with patch.object(lib, "_extract_pdf", new_callable=AsyncMock, return_value="PDF extracted text"):
        result = await lib.ingest_document(str(f))
        assert result["status"] == "ok"


# ── search ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_no_collection(lib_uninit):
    result = await lib_uninit.search("test")
    assert result == []


@pytest.mark.asyncio
async def test_search_empty_collection(lib):
    lib.collection.count.return_value = 0
    result = await lib.search("test")
    assert result == []


@pytest.mark.asyncio
async def test_search_without_embedding_fn(lib):
    lib.collection.query.return_value = {
        "documents": [["Result doc"]],
        "metadatas": [[{"source": "manual.txt", "chunk": 0}]],
        "distances": [[0.2]],
    }
    results = await lib.search("query", n_results=3)
    assert len(results) == 1
    assert results[0]["content"] == "Result doc"
    assert results[0]["source"] == "manual.txt"
    assert results[0]["relevance"] == 0.8
    lib.collection.query.assert_called_once()


@pytest.mark.asyncio
async def test_search_with_embedding_fn(lib):
    lib.embedding_fn = MagicMock(return_value=[0.1] * 384)
    lib.collection.query.return_value = {
        "documents": [["Doc1", "Doc2"]],
        "metadatas": [[{"source": "a.txt", "chunk": 0}, {"source": "b.txt", "chunk": 1}]],
        "distances": [[0.1, 0.5]],
    }
    results = await lib.search("query")
    assert len(results) == 2
    lib.embedding_fn.assert_called_once_with("query")


@pytest.mark.asyncio
async def test_search_respects_n_results(lib):
    lib.collection.count.return_value = 3
    lib.collection.query.return_value = {
        "documents": [["A"]],
        "metadatas": [[{"source": "a.txt"}]],
        "distances": [[0.1]],
    }
    await lib.search("test", n_results=2)
    call_kwargs = lib.collection.query.call_args
    # n_results should be min(n_results, count) = min(2, 3) = 2
    assert call_kwargs.kwargs.get("n_results") == 2 or call_kwargs[1].get("n_results") == 2


# ── list_documents ────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_documents_dir_not_exists(lib):
    with patch.object(Path, "exists", return_value=False):
        result = await lib.list_documents()
        assert result == []


@pytest.mark.asyncio
async def test_list_documents_with_files(lib, tmp_path):
    (tmp_path / "a.txt").write_text("content")
    (tmp_path / "b.pdf").write_bytes(b"pdf")
    (tmp_path / "c.docx").write_text("ignored")

    with patch("assistant.workshop_library.WORKSHOP_DOCS_DIR", tmp_path):
        result = await lib.list_documents()
        names = [r["name"] for r in result]
        assert "a.txt" in names
        assert "b.pdf" in names
        assert "c.docx" not in names


# ── get_stats ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_stats_no_collection(lib_uninit):
    with patch.object(WorkshopLibrary, "list_documents", new_callable=AsyncMock, return_value=[]):
        stats = await lib_uninit.get_stats()
        assert stats["total_chunks"] == 0


@pytest.mark.asyncio
async def test_get_stats_with_data(lib):
    lib.collection.count.return_value = 25
    with patch.object(lib, "list_documents", new_callable=AsyncMock, return_value=[
        {"name": "a.txt", "size_mb": 1.5},
        {"name": "b.pdf", "size_mb": 2.5},
    ]):
        stats = await lib.get_stats()
        assert stats["total_chunks"] == 25
        assert stats["total_documents"] == 2
        assert stats["total_size_mb"] == 4.0


# ── _extract_pdf ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_pdf_fitz(lib, tmp_path):
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"fake")

    mock_fitz = MagicMock()
    mock_doc = MagicMock()
    mock_page = MagicMock()
    mock_page.get_text.return_value = "Page 1 text"
    mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
    mock_fitz.open.return_value = mock_doc

    with patch.dict("sys.modules", {"fitz": mock_fitz}):
        result = await lib._extract_pdf(pdf_path)
        assert "Page 1 text" in result


@pytest.mark.asyncio
async def test_extract_pdf_all_fail(lib, tmp_path):
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"fake")

    with patch.dict("sys.modules", {"fitz": None, "pdfplumber": None, "PyPDF2": None}):
        with patch("builtins.__import__", side_effect=ImportError("no module")):
            result = await lib._extract_pdf(pdf_path)
            assert result == ""
