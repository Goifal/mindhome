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


# ── Coverage: lines 56-58 (_resolve_embedding) ──────────────

@pytest.mark.asyncio
async def test_resolve_embedding_awaitable(lib):
    """_resolve_embedding awaits coroutines."""
    async def _coro():
        return [0.1, 0.2]
    result = await lib._resolve_embedding(_coro())
    assert result == [0.1, 0.2]


@pytest.mark.asyncio
async def test_resolve_embedding_non_awaitable(lib):
    """_resolve_embedding returns non-awaitable results directly."""
    result = await lib._resolve_embedding([0.1, 0.2])
    assert result == [0.1, 0.2]


# ── Coverage: lines 210-211 (extract_pdf fitz returns empty) ─

@pytest.mark.asyncio
async def test_extract_pdf_fitz_empty_then_pdfplumber(lib, tmp_path):
    """When fitz returns empty text, falls through to pdfplumber."""
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"fake")

    mock_fitz = MagicMock()
    mock_doc = MagicMock()
    mock_page = MagicMock()
    mock_page.get_text.return_value = ""  # empty text
    mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
    mock_fitz.open.return_value = mock_doc

    mock_pdfplumber = MagicMock()
    mock_pdf = MagicMock()
    mock_plumber_page = MagicMock()
    mock_plumber_page.extract_text.return_value = "pdfplumber text"
    mock_pdf.pages = [mock_plumber_page]
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdfplumber.open.return_value = mock_pdf

    with patch.dict("sys.modules", {"fitz": mock_fitz, "pdfplumber": mock_pdfplumber}):
        result = await lib._extract_pdf(pdf_path)
    assert "pdfplumber text" in result


# ── Coverage: lines 216-225 (pdfplumber success path) ────────

@pytest.mark.asyncio
async def test_extract_pdf_pdfplumber_success(lib, tmp_path):
    """pdfplumber extracts text when fitz is not available."""
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"fake")

    mock_pdfplumber = MagicMock()
    mock_pdf = MagicMock()
    mock_page1 = MagicMock()
    mock_page1.extract_text.return_value = "Page 1"
    mock_page2 = MagicMock()
    mock_page2.extract_text.return_value = "Page 2"
    mock_pdf.pages = [mock_page1, mock_page2]
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdfplumber.open.return_value = mock_pdf

    def selective_import(name, *args, **kwargs):
        if name == "fitz":
            raise ImportError("no fitz")
        if name == "pdfplumber":
            return mock_pdfplumber
        return original_import(name, *args, **kwargs)

    import builtins
    original_import = builtins.__import__
    with patch.dict("sys.modules", {"fitz": None}):
        with patch("builtins.__import__", side_effect=selective_import):
            result = await lib._extract_pdf(pdf_path)
    assert "Page 1" in result
    assert "Page 2" in result


# ── Coverage: lines 228-229 (pdfplumber exception) ──────────

@pytest.mark.asyncio
async def test_extract_pdf_pdfplumber_exception(lib, tmp_path):
    """When pdfplumber raises exception, falls through to PyPDF2."""
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"fake")

    mock_pdfplumber = MagicMock()
    mock_pdfplumber.open.side_effect = Exception("pdfplumber error")

    mock_pypdf2 = MagicMock()
    mock_reader = MagicMock()
    mock_reader_page = MagicMock()
    mock_reader_page.extract_text.return_value = "PyPDF2 text"
    mock_reader.pages = [mock_reader_page]
    mock_pypdf2.PdfReader.return_value = mock_reader

    def selective_import(name, *args, **kwargs):
        if name == "fitz":
            raise ImportError("no fitz")
        if name == "pdfplumber":
            return mock_pdfplumber
        if name == "PyPDF2":
            return mock_pypdf2
        return original_import(name, *args, **kwargs)

    import builtins
    original_import = builtins.__import__
    with patch.dict("sys.modules", {"fitz": None}):
        with patch("builtins.__import__", side_effect=selective_import):
            result = await lib._extract_pdf(pdf_path)
    assert "PyPDF2 text" in result


# ── Coverage: lines 234-243 (PyPDF2 success path) ───────────

@pytest.mark.asyncio
async def test_extract_pdf_pypdf2_success(lib, tmp_path):
    """PyPDF2 extracts text when fitz and pdfplumber unavailable."""
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"fake")

    mock_pypdf2 = MagicMock()
    mock_reader = MagicMock()
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "PyPDF2 content"
    mock_reader.pages = [mock_page]
    mock_pypdf2.PdfReader.return_value = mock_reader

    def selective_import(name, *args, **kwargs):
        if name == "fitz":
            raise ImportError("no fitz")
        if name == "pdfplumber":
            raise ImportError("no pdfplumber")
        if name == "PyPDF2":
            return mock_pypdf2
        return original_import(name, *args, **kwargs)

    import builtins
    original_import = builtins.__import__
    with patch.dict("sys.modules", {"fitz": None, "pdfplumber": None}):
        with patch("builtins.__import__", side_effect=selective_import):
            result = await lib._extract_pdf(pdf_path)
    assert "PyPDF2 content" in result


# ── Coverage: lines 246-247 (PyPDF2 exception) ──────────────

@pytest.mark.asyncio
async def test_extract_pdf_pypdf2_exception(lib, tmp_path):
    """When PyPDF2 raises exception, returns empty string."""
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"fake")

    mock_pypdf2 = MagicMock()
    mock_pypdf2.PdfReader.side_effect = Exception("PyPDF2 error")

    def selective_import(name, *args, **kwargs):
        if name == "fitz":
            raise ImportError("no fitz")
        if name == "pdfplumber":
            raise ImportError("no pdfplumber")
        if name == "PyPDF2":
            return mock_pypdf2
        return original_import(name, *args, **kwargs)

    import builtins
    original_import = builtins.__import__
    with patch.dict("sys.modules", {"fitz": None, "pdfplumber": None}):
        with patch("builtins.__import__", side_effect=selective_import):
            result = await lib._extract_pdf(pdf_path)
    assert result == ""


# ── Coverage: lines 216-225 pdfplumber with None page text ───

@pytest.mark.asyncio
async def test_extract_pdf_pdfplumber_none_page_text(lib, tmp_path):
    """pdfplumber skips pages with None text."""
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"fake")

    mock_pdfplumber = MagicMock()
    mock_pdf = MagicMock()
    page_with_text = MagicMock()
    page_with_text.extract_text.return_value = "Good page"
    page_without_text = MagicMock()
    page_without_text.extract_text.return_value = None
    mock_pdf.pages = [page_with_text, page_without_text]
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdfplumber.open.return_value = mock_pdf

    def selective_import(name, *args, **kwargs):
        if name == "fitz":
            raise ImportError("no fitz")
        if name == "pdfplumber":
            return mock_pdfplumber
        return original_import(name, *args, **kwargs)

    import builtins
    original_import = builtins.__import__
    with patch.dict("sys.modules", {"fitz": None}):
        with patch("builtins.__import__", side_effect=selective_import):
            result = await lib._extract_pdf(pdf_path)
    assert "Good page" in result
