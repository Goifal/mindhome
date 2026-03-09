"""Tests for assistant.recipe_store — RecipeStore class."""

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

import pytest

from assistant.recipe_store import RecipeStore, REC_UPLOAD_MAX_SIZE, REC_UPLOAD_ALLOWED, DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def store():
    """RecipeStore with mocked chroma collection."""
    s = RecipeStore()
    s.chroma_collection = MagicMock()
    s._chroma_client = MagicMock()
    s._recipes_dir = Path("/tmp/test_recipes")
    return s


@pytest.fixture
def store_uninit():
    """RecipeStore without initialization (no collection)."""
    return RecipeStore()


# ── Constants ─────────────────────────────────────────────

def test_upload_max_size():
    assert REC_UPLOAD_MAX_SIZE == 10 * 1024 * 1024


def test_upload_allowed_extensions():
    assert REC_UPLOAD_ALLOWED == {".txt", ".md", ".pdf", ".csv"}


def test_default_chunk_size():
    assert DEFAULT_CHUNK_SIZE == 800


def test_default_chunk_overlap():
    assert DEFAULT_CHUNK_OVERLAP == 100


# ── __init__ ──────────────────────────────────────────────

def test_init_defaults():
    s = RecipeStore()
    assert s.chroma_collection is None
    assert s._chroma_client is None
    assert s._recipes_dir is None
    assert s._ingested_hashes == set()


# ── _load_ingested_hashes ─────────────────────────────────

def test_load_ingested_hashes_no_collection():
    s = RecipeStore()
    s._load_ingested_hashes()
    assert s._ingested_hashes == set()


def test_load_ingested_hashes_populates(store):
    store.chroma_collection.get.return_value = {
        "metadatas": [
            {"content_hash": "abc123"},
            {"content_hash": "def456"},
            {},
        ]
    }
    store._load_ingested_hashes()
    assert store._ingested_hashes == {"abc123", "def456"}


def test_load_ingested_hashes_exception(store):
    store.chroma_collection.get.side_effect = RuntimeError("fail")
    store._load_ingested_hashes()
    assert store._ingested_hashes == set()


# ── search ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_no_collection(store_uninit):
    result = await store_uninit.search("pasta")
    assert result == []


@pytest.mark.asyncio
@patch("assistant.recipe_store.yaml_config", {"recipe_store": {"max_distance": 1.0}})
async def test_search_returns_hits(store):
    store.chroma_collection.query.return_value = {
        "documents": [["Pasta mit Tomaten", "Pizza Margherita"]],
        "distances": [[0.3, 0.8]],
        "metadatas": [[{"source_file": "pasta.txt"}, {"source_file": "pizza.txt"}]],
    }
    hits = await store.search("pasta", limit=5)
    assert len(hits) == 2
    assert hits[0]["content"] == "Pasta mit Tomaten"
    assert hits[0]["source"] == "pasta.txt"
    assert hits[0]["relevance"] == 0.7
    assert hits[0]["distance"] == 0.3


@pytest.mark.asyncio
@patch("assistant.recipe_store.yaml_config", {"recipe_store": {"max_distance": 0.5}})
async def test_search_filters_by_max_distance(store):
    store.chroma_collection.query.return_value = {
        "documents": [["close hit", "far hit"]],
        "distances": [[0.3, 0.8]],
        "metadatas": [[{"source_file": "a.txt"}, {"source_file": "b.txt"}]],
    }
    hits = await store.search("test")
    assert len(hits) == 1
    assert hits[0]["content"] == "close hit"


@pytest.mark.asyncio
@patch("assistant.recipe_store.yaml_config", {"recipe_store": {"max_distance": 1.0}})
async def test_search_exception_returns_empty(store):
    store.chroma_collection.query.side_effect = RuntimeError("db down")
    result = await store.search("test")
    assert result == []


@pytest.mark.asyncio
@patch("assistant.recipe_store.yaml_config", {"recipe_store": {"max_distance": 1.0}})
async def test_search_empty_results(store):
    store.chroma_collection.query.return_value = {
        "documents": [[]],
        "distances": [[]],
        "metadatas": [[]],
    }
    hits = await store.search("nothing")
    assert hits == []


# ── ingest_file ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_file_no_collection(store_uninit):
    result = await store_uninit.ingest_file(Path("/tmp/test.txt"))
    assert result == 0


@pytest.mark.asyncio
@patch("assistant.recipe_store.yaml_config", {"recipe_store": {"chunk_size": 800, "chunk_overlap": 100}})
@patch("assistant.recipe_store.KnowledgeBase")
async def test_ingest_file_txt(mock_kb, store, tmp_path):
    recipe_file = tmp_path / "test_recipe.txt"
    recipe_file.write_text("This is a test recipe content for ingestion.")

    mock_kb._split_text.return_value = ["chunk1", "chunk2"]
    store.chroma_collection.add = MagicMock()

    result = await store.ingest_file(recipe_file)
    assert result == 2
    assert store.chroma_collection.add.call_count == 2


@pytest.mark.asyncio
@patch("assistant.recipe_store.yaml_config", {"recipe_store": {"chunk_size": 800, "chunk_overlap": 100}})
@patch("assistant.recipe_store.KnowledgeBase")
async def test_ingest_file_skips_existing_hashes(mock_kb, store, tmp_path):
    recipe_file = tmp_path / "test.txt"
    recipe_file.write_text("existing content")

    mock_kb._split_text.return_value = ["chunk1"]
    content_hash = hashlib.md5("chunk1".encode()).hexdigest()
    store._ingested_hashes.add(content_hash)

    result = await store.ingest_file(recipe_file)
    assert result == 0


@pytest.mark.asyncio
@patch("assistant.recipe_store.yaml_config", {"recipe_store": {}})
@patch("assistant.recipe_store.KnowledgeBase")
async def test_ingest_file_empty_content(mock_kb, store, tmp_path):
    recipe_file = tmp_path / "empty.txt"
    recipe_file.write_text("   ")
    result = await store.ingest_file(recipe_file)
    assert result == 0


# ── ingest_all ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_all_no_dir(store_uninit):
    result = await store_uninit.ingest_all()
    assert result == 0


# ── get_stats ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_stats_no_collection(store_uninit):
    stats = await store_uninit.get_stats()
    assert stats == {"enabled": False, "total_chunks": 0, "sources": []}


@pytest.mark.asyncio
async def test_get_stats_with_data(store):
    store.chroma_collection.count.return_value = 10
    store.chroma_collection.get.return_value = {
        "metadatas": [
            {"source_file": "pasta.txt"},
            {"source_file": "pizza.txt"},
            {"source_file": "pasta.txt"},
        ]
    }
    stats = await store.get_stats()
    assert stats["enabled"] is True
    assert stats["total_chunks"] == 10
    assert stats["sources"] == ["pasta.txt", "pizza.txt"]


@pytest.mark.asyncio
async def test_get_stats_exception(store):
    store.chroma_collection.count.side_effect = RuntimeError("fail")
    stats = await store.get_stats()
    assert stats == {"enabled": True, "total_chunks": 0, "sources": []}


# ── get_chunks ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_chunks_no_collection(store_uninit):
    result = await store_uninit.get_chunks()
    assert result == []


@pytest.mark.asyncio
async def test_get_chunks_returns_sorted(store):
    store.chroma_collection.get.return_value = {
        "ids": ["id1", "id2"],
        "documents": ["short", "x" * 250],
        "metadatas": [
            {"source_file": "b.txt", "chunk_index": "0"},
            {"source_file": "a.txt", "chunk_index": "0"},
        ],
    }
    chunks = await store.get_chunks()
    assert len(chunks) == 2
    assert chunks[0]["source"] == "a.txt"
    assert chunks[1]["source"] == "b.txt"
    # Long content truncated
    assert chunks[0]["content"].endswith("...")


@pytest.mark.asyncio
async def test_get_chunks_with_offset_limit(store):
    store.chroma_collection.get.return_value = {
        "ids": [f"id{i}" for i in range(5)],
        "documents": [f"doc{i}" for i in range(5)],
        "metadatas": [{"source_file": "a.txt", "chunk_index": str(i)} for i in range(5)],
    }
    chunks = await store.get_chunks(offset=1, limit=2)
    assert len(chunks) == 2


@pytest.mark.asyncio
async def test_get_chunks_filter_by_source(store):
    store.chroma_collection.get.return_value = {
        "ids": ["id1"],
        "documents": ["content"],
        "metadatas": [{"source_file": "target.txt", "chunk_index": "0"}],
    }
    await store.get_chunks(source="target.txt")
    call_kwargs = store.chroma_collection.get.call_args
    assert call_kwargs.kwargs.get("where") == {"source_file": "target.txt"}


# ── delete_chunks ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_chunks_no_collection(store_uninit):
    result = await store_uninit.delete_chunks(["id1"])
    assert result == 0


@pytest.mark.asyncio
async def test_delete_chunks_empty_list(store):
    result = await store.delete_chunks([])
    assert result == 0


@pytest.mark.asyncio
async def test_delete_chunks_success(store):
    result = await store.delete_chunks(["id1", "id2"])
    assert result == 2
    store.chroma_collection.delete.assert_called_once_with(ids=["id1", "id2"])


@pytest.mark.asyncio
async def test_delete_chunks_exception(store):
    store.chroma_collection.delete.side_effect = RuntimeError("fail")
    result = await store.delete_chunks(["id1"])
    assert result == 0


# ── delete_source_chunks ──────────────────────────────────

@pytest.mark.asyncio
async def test_delete_source_chunks_no_collection(store_uninit):
    result = await store_uninit.delete_source_chunks("a.txt")
    assert result == 0


@pytest.mark.asyncio
async def test_delete_source_chunks_empty_source(store):
    result = await store.delete_source_chunks("")
    assert result == 0


@pytest.mark.asyncio
async def test_delete_source_chunks_success(store):
    store.chroma_collection.get.return_value = {
        "ids": ["id1", "id2"],
        "metadatas": [{"content_hash": "h1"}, {"content_hash": "h2"}],
    }
    store._ingested_hashes = {"h1", "h2", "h3"}
    result = await store.delete_source_chunks("recipe.txt")
    assert result == 2
    assert "h1" not in store._ingested_hashes
    assert "h2" not in store._ingested_hashes
    assert "h3" in store._ingested_hashes


# ── clear ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_clear_no_client(store_uninit):
    result = await store_uninit.clear()
    assert result is False


@pytest.mark.asyncio
@patch("assistant.embeddings.get_embedding_function", return_value=None)
async def test_clear_success(mock_ef, store):
    store._ingested_hashes = {"a", "b"}
    store._chroma_client.get_or_create_collection.return_value = MagicMock()
    result = await store.clear()
    assert result is True
    assert store._ingested_hashes == set()
    store._chroma_client.delete_collection.assert_called_once_with("mha_recipes")


@pytest.mark.asyncio
async def test_clear_exception(store):
    store._chroma_client.delete_collection.side_effect = RuntimeError("fail")
    result = await store.clear()
    assert result is False


# ── rebuild ───────────────────────────────────────────────

@pytest.mark.asyncio
@patch("assistant.recipe_store.yaml_config", {"recipe_store": {}})
async def test_rebuild_clear_fails(store):
    store._chroma_client.delete_collection.side_effect = RuntimeError("fail")
    result = await store.rebuild()
    assert result["success"] is False


@pytest.mark.asyncio
@patch("assistant.recipe_store.yaml_config", {"recipe_store": {}})
@patch("assistant.embeddings.get_embedding_function", return_value=None)
@patch("assistant.embeddings.DEFAULT_MODEL", "test-model")
async def test_rebuild_success(mock_ef, store):
    store._chroma_client.get_or_create_collection.return_value = MagicMock()
    store._recipes_dir = None  # ingest_all returns 0
    result = await store.rebuild()
    assert result["success"] is True
    assert result["new_chunks"] == 0
    assert result["embedding_model"] == "test-model"


# ── reingest_file ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_reingest_file_no_recipes_dir(store_uninit):
    result = await store_uninit.reingest_file("test.txt")
    assert result == 0
