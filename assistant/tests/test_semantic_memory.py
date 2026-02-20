"""
Tests fuer Semantic Memory — Fakten-Speicherung, Duplikat-Erkennung,
Widerspruchs-Erkennung, Decay und explizites Notizbuch.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.semantic_memory import (
    FACT_CATEGORIES,
    SemanticFact,
    SemanticMemory,
)


# =====================================================================
# SemanticFact Datenklasse
# =====================================================================


class TestSemanticFact:
    """Tests fuer die SemanticFact Datenklasse."""

    def test_create_fact_defaults(self):
        fact = SemanticFact(content="Max mag 21 Grad", category="preference")
        assert fact.content == "Max mag 21 Grad"
        assert fact.category == "preference"
        assert fact.person == "unknown"
        assert fact.confidence == 0.8
        assert fact.times_confirmed == 1
        assert fact.fact_id.startswith("fact_")

    def test_create_fact_custom_values(self):
        fact = SemanticFact(
            content="Lisa hat Laktose-Intoleranz",
            category="health",
            person="Lisa",
            confidence=0.95,
            fact_id="custom_123",
        )
        assert fact.person == "Lisa"
        assert fact.confidence == 0.95
        assert fact.fact_id == "custom_123"

    def test_invalid_category_falls_back_to_general(self):
        fact = SemanticFact(content="Test", category="nonexistent_category")
        assert fact.category == "general"

    def test_valid_categories(self):
        for cat in FACT_CATEGORIES:
            fact = SemanticFact(content="Test", category=cat)
            assert fact.category == cat

    def test_to_dict(self):
        fact = SemanticFact(
            content="Max arbeitet remote",
            category="work",
            person="Max",
            confidence=0.7,
            fact_id="fact_test",
        )
        d = fact.to_dict()
        assert d["fact_id"] == "fact_test"
        assert d["content"] == "Max arbeitet remote"
        assert d["category"] == "work"
        assert d["person"] == "Max"
        assert d["confidence"] == "0.7"  # Als String gespeichert
        assert d["times_confirmed"] == "1"
        assert "created_at" in d
        assert "updated_at" in d

    def test_from_dict(self):
        data = {
            "fact_id": "fact_123",
            "content": "Max hat eine Katze",
            "category": "person",
            "person": "Max",
            "confidence": "0.85",
            "times_confirmed": "3",
            "created_at": "2026-01-15T10:00:00",
            "updated_at": "2026-02-10T14:00:00",
        }
        fact = SemanticFact.from_dict(data)
        assert fact.fact_id == "fact_123"
        assert fact.content == "Max hat eine Katze"
        assert fact.confidence == 0.85
        assert fact.times_confirmed == 3
        assert fact.created_at == "2026-01-15T10:00:00"

    def test_from_dict_missing_fields(self):
        data = {"content": "Minimal"}
        fact = SemanticFact.from_dict(data)
        assert fact.content == "Minimal"
        assert fact.category == "general"
        assert fact.person == "unknown"
        assert fact.confidence == 0.8

    def test_roundtrip_dict(self):
        original = SemanticFact(
            content="Test Roundtrip",
            category="habit",
            person="Lisa",
            confidence=0.6,
        )
        restored = SemanticFact.from_dict(original.to_dict())
        assert restored.content == original.content
        assert restored.category == original.category
        assert restored.person == original.person
        assert restored.confidence == original.confidence


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def redis_mock():
    """Redis AsyncMock fuer SemanticMemory."""
    r = AsyncMock()
    r.hset = AsyncMock()
    r.hgetall = AsyncMock(return_value={})
    r.hget = AsyncMock(return_value=None)
    r.sadd = AsyncMock()
    r.srem = AsyncMock()
    r.smembers = AsyncMock(return_value=set())
    r.scard = AsyncMock(return_value=0)
    r.delete = AsyncMock()
    return r


@pytest.fixture
def chroma_mock():
    """ChromaDB Collection Mock."""
    coll = MagicMock()
    coll.add = MagicMock()
    coll.update = MagicMock()
    coll.delete = MagicMock()
    coll.query = MagicMock(return_value={
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]],
        "ids": [[]],
    })
    return coll


@pytest.fixture
def semantic(redis_mock, chroma_mock):
    """SemanticMemory mit gemockten Backends."""
    sm = SemanticMemory()
    sm.redis = redis_mock
    sm.chroma_collection = chroma_mock
    return sm


@pytest.fixture
def semantic_no_backends():
    """SemanticMemory ohne Backends (Graceful Degradation)."""
    sm = SemanticMemory()
    sm.redis = None
    sm.chroma_collection = None
    return sm


# =====================================================================
# store_fact
# =====================================================================


class TestStoreFact:
    """Tests fuer das Speichern von Fakten."""

    @pytest.mark.asyncio
    async def test_store_new_fact(self, semantic, redis_mock, chroma_mock):
        # Keine Widersprueche, keine Duplikate
        chroma_mock.query = MagicMock(return_value={
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
            "ids": [[]],
        })

        fact = SemanticFact(
            content="Max bevorzugt 21 Grad",
            category="preference",
            person="Max",
        )
        result = await semantic.store_fact(fact)

        assert result is True
        chroma_mock.add.assert_called_once()
        redis_mock.hset.assert_called()
        redis_mock.sadd.assert_any_call("mha:facts:person:Max", fact.fact_id)
        redis_mock.sadd.assert_any_call("mha:facts:category:preference", fact.fact_id)
        redis_mock.sadd.assert_any_call("mha:facts:all", fact.fact_id)

    @pytest.mark.asyncio
    async def test_store_fact_deduplication(self, semantic, chroma_mock, redis_mock):
        # find_similar_fact findet ein Duplikat (distance < 0.15)
        chroma_mock.query = MagicMock(return_value={
            "documents": [["Max bevorzugt 21 Grad"]],
            "metadatas": [[{
                "fact_id": "existing_123",
                "content": "Max bevorzugt 21 Grad",
                "confidence": "0.75",
                "times_confirmed": "2",
                "category": "preference",
                "person": "Max",
            }]],
            "distances": [[0.05]],  # Sehr aehnlich -> Duplikat
            "ids": [["existing_123"]],
        })

        fact = SemanticFact(
            content="Max bevorzugt 21 Grad im Buero",
            category="preference",
            person="Max",
        )
        result = await semantic.store_fact(fact)

        # Sollte Update statt Insert machen
        assert result is True
        chroma_mock.add.assert_not_called()
        chroma_mock.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_fact_chroma_error(self, semantic, chroma_mock):
        chroma_mock.query = MagicMock(return_value={
            "documents": [[]], "metadatas": [[]], "distances": [[]], "ids": [[]],
        })
        chroma_mock.add.side_effect = Exception("ChromaDB unreachable")

        fact = SemanticFact(content="Test", category="general")
        result = await semantic.store_fact(fact)
        assert result is False


# =====================================================================
# _update_existing_fact
# =====================================================================


class TestUpdateExistingFact:
    """Tests fuer das Aktualisieren bestehender Fakten."""

    @pytest.mark.asyncio
    async def test_update_increments_confirmation(self, semantic, redis_mock, chroma_mock):
        existing = {
            "fact_id": "fact_old",
            "content": "Max trinkt gern Kaffee",
            "confidence": "0.7",
            "times_confirmed": "2",
            "category": "preference",
            "person": "Max",
        }
        new_fact = SemanticFact(content="Max trinkt gern Kaffee", category="preference")

        result = await semantic._update_existing_fact(existing, new_fact)

        assert result is True
        # Confidence sollte um 0.05 gestiegen sein
        chroma_mock.update.assert_called_once()
        update_meta = chroma_mock.update.call_args[1]["metadatas"][0]
        assert update_meta["times_confirmed"] == "3"
        assert float(update_meta["confidence"]) == pytest.approx(0.75)

    @pytest.mark.asyncio
    async def test_update_confidence_capped_at_1(self, semantic, chroma_mock):
        existing = {
            "fact_id": "fact_max",
            "content": "Test",
            "confidence": "0.98",
            "times_confirmed": "10",
        }
        new_fact = SemanticFact(content="Test", category="general")

        await semantic._update_existing_fact(existing, new_fact)

        update_meta = chroma_mock.update.call_args[1]["metadatas"][0]
        assert float(update_meta["confidence"]) <= 1.0

    @pytest.mark.asyncio
    async def test_update_prefers_longer_content(self, semantic, chroma_mock):
        existing = {
            "fact_id": "fact_x",
            "content": "Max Kaffee",
            "confidence": "0.7",
            "times_confirmed": "1",
        }
        new_fact = SemanticFact(
            content="Max trinkt morgens immer einen starken Kaffee",
            category="habit",
        )

        await semantic._update_existing_fact(existing, new_fact)

        # Laengerer Content wird bevorzugt
        updated_doc = chroma_mock.update.call_args[1]["documents"][0]
        assert "morgens" in updated_doc

    @pytest.mark.asyncio
    async def test_update_no_fact_id_returns_false(self, semantic):
        result = await semantic._update_existing_fact({}, SemanticFact(content="X", category="general"))
        assert result is False


# =====================================================================
# _check_contradiction
# =====================================================================


class TestContradictionDetection:
    """Tests fuer Widerspruchs-Erkennung."""

    @pytest.mark.asyncio
    async def test_no_contradiction_empty_results(self, semantic, chroma_mock):
        chroma_mock.query = MagicMock(return_value={
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
            "ids": [[]],
        })
        fact = SemanticFact(content="Max mag 21 Grad", category="preference", person="Max")
        result = await semantic._check_contradiction(fact)
        assert result is None

    @pytest.mark.asyncio
    async def test_contradiction_detected_different_numbers(self, semantic, chroma_mock):
        # Alter Fakt: 21 Grad, neuer Fakt: 23 Grad
        chroma_mock.query = MagicMock(return_value={
            "documents": [["Max bevorzugt 21 Grad im Buero"]],
            "metadatas": [[{"category": "preference", "person": "Max"}]],
            "distances": [[0.3]],  # Zwischen 0.15 und 0.8 -> verwandt
            "ids": [["fact_old"]],
        })

        fact = SemanticFact(
            content="Max bevorzugt 23 Grad im Buero",
            category="preference",
            person="Max",
        )
        result = await semantic._check_contradiction(fact)

        assert result is not None
        assert result["fact_id"] == "fact_old"
        assert "21" in result["content"]

    @pytest.mark.asyncio
    async def test_no_contradiction_same_numbers(self, semantic, chroma_mock):
        # Gleiche Zahlen -> kein Widerspruch
        chroma_mock.query = MagicMock(return_value={
            "documents": [["Max bevorzugt 21 Grad"]],
            "metadatas": [[{"category": "preference", "person": "Max"}]],
            "distances": [[0.3]],
            "ids": [["fact_old"]],
        })

        fact = SemanticFact(
            content="Max mag 21 Grad im Buero",
            category="preference",
            person="Max",
        )
        result = await semantic._check_contradiction(fact)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_contradiction_too_distant(self, semantic, chroma_mock):
        # Distance > 0.8 -> nicht verwandt genug
        chroma_mock.query = MagicMock(return_value={
            "documents": [["Lisa isst gern Pizza"]],
            "metadatas": [[{"category": "preference", "person": "Lisa"}]],
            "distances": [[0.9]],
            "ids": [["fact_other"]],
        })

        fact = SemanticFact(
            content="Max mag 23 Grad",
            category="preference",
            person="Max",
        )
        result = await semantic._check_contradiction(fact)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_contradiction_too_similar(self, semantic, chroma_mock):
        # Distance < 0.15 -> identisch, kein Widerspruch (sondern Duplikat)
        chroma_mock.query = MagicMock(return_value={
            "documents": [["Max bevorzugt 21 Grad"]],
            "metadatas": [[{"category": "preference", "person": "Max"}]],
            "distances": [[0.05]],
            "ids": [["fact_old"]],
        })

        fact = SemanticFact(
            content="Max bevorzugt 21 Grad",
            category="preference",
            person="Max",
        )
        result = await semantic._check_contradiction(fact)
        assert result is None

    @pytest.mark.asyncio
    async def test_contradiction_no_chroma(self, semantic_no_backends):
        fact = SemanticFact(content="Test 42", category="general")
        result = await semantic_no_backends._check_contradiction(fact)
        assert result is None


# =====================================================================
# apply_decay
# =====================================================================


class TestFactDecay:
    """Tests fuer den Confidence-Abbau ueber Zeit."""

    @pytest.mark.asyncio
    async def test_decay_old_fact(self, semantic, redis_mock):
        old_date = (datetime.now() - timedelta(days=35)).isoformat()
        redis_mock.smembers = AsyncMock(return_value={"fact_1"})
        redis_mock.hgetall = AsyncMock(return_value={
            "fact_id": "fact_1",
            "confidence": "0.5",
            "updated_at": old_date,
            "source_conversation": "User: test",
            "times_confirmed": "1",
        })

        await semantic.apply_decay()

        # Confidence sollte um 0.05 reduziert worden sein
        redis_mock.hset.assert_called()
        call_args = redis_mock.hset.call_args_list
        # Finde den confidence-Update Call
        conf_update = [c for c in call_args if len(c[0]) >= 3 and c[0][1] == "confidence"]
        assert len(conf_update) == 1
        new_conf = float(conf_update[0][0][2])
        assert new_conf == pytest.approx(0.45, abs=0.01)

    @pytest.mark.asyncio
    async def test_decay_explicit_fact_slower(self, semantic, redis_mock):
        old_date = (datetime.now() - timedelta(days=35)).isoformat()
        redis_mock.smembers = AsyncMock(return_value={"fact_2"})
        redis_mock.hgetall = AsyncMock(return_value={
            "fact_id": "fact_2",
            "confidence": "1.0",
            "updated_at": old_date,
            "source_conversation": "explicit",
            "times_confirmed": "1",
        })

        await semantic.apply_decay()

        # Explizite Fakten: nur 1% Decay
        conf_update = [c for c in redis_mock.hset.call_args_list
                       if len(c[0]) >= 3 and c[0][1] == "confidence"]
        assert len(conf_update) == 1
        new_conf = float(conf_update[0][0][2])
        assert new_conf == pytest.approx(0.99, abs=0.01)

    @pytest.mark.asyncio
    async def test_decay_frequently_confirmed_slower(self, semantic, redis_mock):
        old_date = (datetime.now() - timedelta(days=35)).isoformat()
        redis_mock.smembers = AsyncMock(return_value={"fact_3"})
        redis_mock.hgetall = AsyncMock(return_value={
            "fact_id": "fact_3",
            "confidence": "0.5",
            "updated_at": old_date,
            "source_conversation": "User: test",
            "times_confirmed": "5",  # >= 5 -> 50% langsamer
        })

        await semantic.apply_decay()

        conf_update = [c for c in redis_mock.hset.call_args_list
                       if len(c[0]) >= 3 and c[0][1] == "confidence"]
        assert len(conf_update) == 1
        new_conf = float(conf_update[0][0][2])
        # 0.05 * 0.5 = 0.025 Decay -> 0.5 - 0.025 = 0.475
        assert new_conf == pytest.approx(0.475, abs=0.01)

    @pytest.mark.asyncio
    async def test_decay_deletes_below_threshold(self, semantic, redis_mock):
        old_date = (datetime.now() - timedelta(days=35)).isoformat()
        redis_mock.smembers = AsyncMock(return_value={"fact_weak"})
        redis_mock.hgetall = AsyncMock(return_value={
            "fact_id": "fact_weak",
            "content": "Unwichtiger Fakt",
            "confidence": "0.2",
            "updated_at": old_date,
            "source_conversation": "User: x",
            "times_confirmed": "1",
            "person": "unknown",
            "category": "general",
        })

        await semantic.apply_decay()

        # Fakt sollte geloescht werden (0.2 - 0.05 = 0.15 < 0.2)
        redis_mock.delete.assert_called()

    @pytest.mark.asyncio
    async def test_decay_skips_recent_facts(self, semantic, redis_mock):
        recent_date = (datetime.now() - timedelta(days=10)).isoformat()
        redis_mock.smembers = AsyncMock(return_value={"fact_new"})
        redis_mock.hgetall = AsyncMock(return_value={
            "fact_id": "fact_new",
            "confidence": "0.5",
            "updated_at": recent_date,
            "source_conversation": "User: x",
            "times_confirmed": "1",
        })

        await semantic.apply_decay()

        # Keine Aenderung bei frischen Fakten (< 30 Tage)
        # hset sollte nicht fuer confidence aufgerufen werden
        conf_updates = [c for c in redis_mock.hset.call_args_list
                        if len(c[0]) >= 3 and c[0][1] == "confidence"]
        assert len(conf_updates) == 0

    @pytest.mark.asyncio
    async def test_decay_no_redis(self, semantic_no_backends):
        await semantic_no_backends.apply_decay()


# =====================================================================
# find_similar_fact
# =====================================================================


class TestFindSimilarFact:
    """Tests fuer Duplikat-Suche."""

    @pytest.mark.asyncio
    async def test_find_similar_match(self, semantic, chroma_mock):
        chroma_mock.query = MagicMock(return_value={
            "documents": [["Max mag warmes Licht"]],
            "metadatas": [[{"fact_id": "f1", "category": "preference"}]],
            "distances": [[0.1]],
        })
        result = await semantic.find_similar_fact("Max bevorzugt warmes Licht")
        assert result is not None
        assert result["fact_id"] == "f1"

    @pytest.mark.asyncio
    async def test_find_similar_no_match(self, semantic, chroma_mock):
        chroma_mock.query = MagicMock(return_value={
            "documents": [["Etwas ganz anderes"]],
            "metadatas": [[{"fact_id": "f2"}]],
            "distances": [[0.9]],  # Zu weit weg
        })
        result = await semantic.find_similar_fact("Max mag Kaffee")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_similar_no_chroma(self, semantic_no_backends):
        result = await semantic_no_backends.find_similar_fact("Test")
        assert result is None


# =====================================================================
# search_facts
# =====================================================================


class TestSearchFacts:
    """Tests fuer die semantische Fakten-Suche."""

    @pytest.mark.asyncio
    async def test_search_returns_formatted_results(self, semantic, chroma_mock):
        chroma_mock.query = MagicMock(return_value={
            "documents": [["Max mag 21 Grad", "Max trinkt Kaffee"]],
            "metadatas": [[
                {"category": "preference", "person": "Max", "confidence": "0.8", "times_confirmed": "3"},
                {"category": "habit", "person": "Max", "confidence": "0.7", "times_confirmed": "1"},
            ]],
            "distances": [[0.1, 0.4]],
        })

        results = await semantic.search_facts("Max Vorlieben", limit=5)

        assert len(results) == 2
        assert results[0]["content"] == "Max mag 21 Grad"
        assert results[0]["category"] == "preference"
        assert results[0]["confidence"] == 0.8
        assert results[0]["relevance"] == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_search_with_person_filter(self, semantic, chroma_mock):
        await semantic.search_facts("Vorlieben", person="Lisa")
        call_kwargs = chroma_mock.query.call_args[1]
        assert call_kwargs["where"] == {"person": "Lisa"}

    @pytest.mark.asyncio
    async def test_search_no_chroma(self, semantic_no_backends):
        result = await semantic_no_backends.search_facts("Test")
        assert result == []


# =====================================================================
# get_facts_by_person / get_facts_by_category
# =====================================================================


class TestFactRetrieval:
    """Tests fuer Fakten-Abruf nach Person/Kategorie."""

    @pytest.mark.asyncio
    async def test_get_facts_by_person(self, semantic, redis_mock):
        redis_mock.smembers = AsyncMock(return_value={"f1", "f2"})

        async def hgetall_side_effect(key):
            data = {
                "mha:fact:f1": {
                    "content": "Max mag Kaffee",
                    "category": "preference",
                    "person": "Max",
                    "confidence": "0.9",
                    "times_confirmed": "5",
                },
                "mha:fact:f2": {
                    "content": "Max steht um 7 auf",
                    "category": "habit",
                    "person": "Max",
                    "confidence": "0.6",
                    "times_confirmed": "1",
                },
            }
            return data.get(key, {})

        redis_mock.hgetall = AsyncMock(side_effect=hgetall_side_effect)

        result = await semantic.get_facts_by_person("Max")
        assert len(result) == 2
        # Sortiert nach Confidence (hoch -> niedrig)
        assert result[0]["confidence"] >= result[1]["confidence"]

    @pytest.mark.asyncio
    async def test_get_facts_by_category(self, semantic, redis_mock):
        redis_mock.smembers = AsyncMock(return_value={"f1"})
        redis_mock.hgetall = AsyncMock(return_value={
            "content": "Haselnuss-Allergie",
            "category": "health",
            "person": "Max",
            "confidence": "0.95",
        })

        result = await semantic.get_facts_by_category("health")
        assert len(result) == 1
        assert result[0]["category"] == "health"

    @pytest.mark.asyncio
    async def test_get_all_facts(self, semantic, redis_mock):
        redis_mock.smembers = AsyncMock(return_value={"f1"})
        redis_mock.hgetall = AsyncMock(return_value={
            "fact_id": "f1",
            "content": "Test Fakt",
            "category": "general",
            "person": "Max",
            "confidence": "0.5",
            "times_confirmed": "1",
            "created_at": "2026-02-20T10:00:00",
            "updated_at": "2026-02-20T10:00:00",
        })

        result = await semantic.get_all_facts()
        assert len(result) == 1
        assert result[0]["fact_id"] == "f1"

    @pytest.mark.asyncio
    async def test_get_all_facts_no_redis(self, semantic_no_backends):
        result = await semantic_no_backends.get_all_facts()
        assert result == []


# =====================================================================
# delete_fact
# =====================================================================


class TestDeleteFact:
    """Tests fuer das Loeschen von Fakten."""

    @pytest.mark.asyncio
    async def test_delete_fact_cleanup(self, semantic, redis_mock, chroma_mock):
        redis_mock.hgetall = AsyncMock(return_value={
            "person": "Max",
            "category": "preference",
        })

        result = await semantic.delete_fact("fact_123")

        assert result is True
        chroma_mock.delete.assert_called_once_with(ids=["fact_123"])
        redis_mock.srem.assert_any_call("mha:facts:person:Max", "fact_123")
        redis_mock.srem.assert_any_call("mha:facts:category:preference", "fact_123")
        redis_mock.srem.assert_any_call("mha:facts:all", "fact_123")
        redis_mock.delete.assert_called_once_with("mha:fact:fact_123")

    @pytest.mark.asyncio
    async def test_delete_nonexistent_fact(self, semantic, redis_mock):
        redis_mock.hgetall = AsyncMock(return_value={})
        result = await semantic.delete_fact("nonexistent")
        assert result is False


# =====================================================================
# Explicit Notebook (Phase 8)
# =====================================================================


class TestExplicitNotebook:
    """Tests fuer 'Merk dir' Funktionalitaet."""

    @pytest.mark.asyncio
    async def test_store_explicit_fact(self, semantic, chroma_mock):
        # Keine Duplikate
        chroma_mock.query = MagicMock(return_value={
            "documents": [[]], "metadatas": [[]], "distances": [[]], "ids": [[]],
        })

        result = await semantic.store_explicit(
            content="Geburtstag am 15. Maerz",
            category="person",
            person="Max",
        )

        assert result is True
        # Confidence muss 1.0 sein
        call_kwargs = chroma_mock.add.call_args[1]
        assert float(call_kwargs["metadatas"][0]["confidence"]) == 1.0
        assert call_kwargs["metadatas"][0]["source_conversation"] == "explicit"

    @pytest.mark.asyncio
    async def test_store_explicit_invalid_category(self, semantic, chroma_mock):
        chroma_mock.query = MagicMock(return_value={
            "documents": [[]], "metadatas": [[]], "distances": [[]], "ids": [[]],
        })

        result = await semantic.store_explicit(
            content="Test",
            category="invalid_cat",
        )
        assert result is True
        # Sollte auf "general" zurueckfallen
        meta = chroma_mock.add.call_args[1]["metadatas"][0]
        assert meta["category"] == "general"


# =====================================================================
# search_by_topic
# =====================================================================


class TestSearchByTopic:
    """Tests fuer Themen-Suche (grosszuegigerer Filter)."""

    @pytest.mark.asyncio
    async def test_search_by_topic_returns_results(self, semantic, chroma_mock):
        chroma_mock.query = MagicMock(return_value={
            "documents": [["Max arbeitet an Projekt Aurora"]],
            "metadatas": [[{
                "category": "work",
                "person": "Max",
                "confidence": "0.7",
                "times_confirmed": "2",
                "source_conversation": "User: Was mache ich gerade?",
                "created_at": "2026-02-15T10:00:00",
            }]],
            "distances": [[0.5]],
        })

        results = await semantic.search_by_topic("Arbeit Projekt")
        assert len(results) == 1
        assert results[0]["relevance"] == pytest.approx(0.5)
        assert "source" in results[0]

    @pytest.mark.asyncio
    async def test_search_by_topic_filters_distant(self, semantic, chroma_mock):
        chroma_mock.query = MagicMock(return_value={
            "documents": [["Etwas voellig unverwandtes"]],
            "metadatas": [[{"category": "general", "person": "unknown",
                           "confidence": "0.3", "times_confirmed": "1",
                           "source_conversation": "", "created_at": ""}]],
            "distances": [[1.8]],  # > 1.5 -> wird gefiltert
        })

        results = await semantic.search_by_topic("Kaffee")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_by_topic_no_chroma(self, semantic_no_backends):
        result = await semantic_no_backends.search_by_topic("Test")
        assert result == []


# =====================================================================
# forget
# =====================================================================


class TestForget:
    """Tests fuer 'Vergiss' Funktionalitaet."""

    @pytest.mark.asyncio
    async def test_forget_deletes_matching_facts(self, semantic, chroma_mock, redis_mock):
        # search_by_topic findet Fakten
        chroma_mock.query = MagicMock(return_value={
            "documents": [["Max mag Pizza"]],
            "metadatas": [[{
                "category": "preference",
                "person": "Max",
                "confidence": "0.8",
                "times_confirmed": "1",
                "source_conversation": "",
                "created_at": "",
            }]],
            "distances": [[0.2]],  # Relevance = 0.8 -> > 0.4 Threshold
            "ids": [["fact_pizza"]],
        })

        redis_mock.hgetall = AsyncMock(return_value={
            "person": "Max",
            "category": "preference",
        })

        deleted = await semantic.forget("Pizza")
        assert deleted >= 1

    @pytest.mark.asyncio
    async def test_forget_skips_low_relevance(self, semantic, chroma_mock):
        chroma_mock.query = MagicMock(return_value={
            "documents": [["Etwas kaum verwandtes"]],
            "metadatas": [[{
                "category": "general", "person": "unknown",
                "confidence": "0.3", "times_confirmed": "1",
                "source_conversation": "", "created_at": "",
            }]],
            "distances": [[0.8]],  # Relevance = 0.2 -> < 0.4 Threshold
            "ids": [["fact_unrelated"]],
        })

        deleted = await semantic.forget("Kaffee")
        assert deleted == 0


# =====================================================================
# get_todays_learnings / get_stats / get_correction_history
# =====================================================================


class TestUtilities:
    """Tests fuer Hilfs-Methoden."""

    @pytest.mark.asyncio
    async def test_get_todays_learnings(self, semantic, redis_mock):
        today = datetime.now().strftime("%Y-%m-%d")
        redis_mock.smembers = AsyncMock(return_value={"f1", "f2"})

        async def hgetall_side(key):
            data = {
                "mha:fact:f1": {
                    "content": "Neuer Fakt heute",
                    "category": "general",
                    "person": "Max",
                    "confidence": "0.5",
                    "created_at": f"{today}T14:00:00",
                    "source_conversation": "User: test",
                },
                "mha:fact:f2": {
                    "content": "Alter Fakt",
                    "category": "general",
                    "person": "Max",
                    "confidence": "0.5",
                    "created_at": "2026-01-01T10:00:00",
                    "source_conversation": "User: old",
                },
            }
            return data.get(key, {})

        redis_mock.hgetall = AsyncMock(side_effect=hgetall_side)

        result = await semantic.get_todays_learnings()
        assert len(result) == 1
        assert result[0]["content"] == "Neuer Fakt heute"

    @pytest.mark.asyncio
    async def test_get_stats(self, semantic, redis_mock):
        redis_mock.scard = AsyncMock(side_effect=lambda key: {
            "mha:facts:all": 10,
            "mha:facts:category:preference": 4,
            "mha:facts:category:person": 3,
            "mha:facts:category:habit": 2,
            "mha:facts:category:health": 1,
        }.get(key, 0))
        redis_mock.smembers = AsyncMock(return_value={"f1"})
        redis_mock.hget = AsyncMock(return_value="Max")

        stats = await semantic.get_stats()
        assert stats["total_facts"] == 10
        assert "preference" in stats["categories"]
        assert "Max" in stats["persons"]

    @pytest.mark.asyncio
    async def test_get_stats_no_redis(self, semantic_no_backends):
        stats = await semantic_no_backends.get_stats()
        assert stats["total_facts"] == 0

    @pytest.mark.asyncio
    async def test_get_correction_history(self, semantic, redis_mock):
        redis_mock.smembers = AsyncMock(return_value={"f1"})
        redis_mock.hgetall = AsyncMock(return_value={
            "content": "Temperatur korrigiert auf 22",
            "category": "preference",
            "person": "Max",
            "confidence": "0.9",
            "source_conversation": "correction: Max sagte 22 nicht 21",
            "created_at": "2026-02-20T10:00:00",
        })

        result = await semantic.get_correction_history()
        assert len(result) == 1
        assert "korrigiert" in result[0]["content"]

    @pytest.mark.asyncio
    async def test_get_correction_history_no_redis(self, semantic_no_backends):
        result = await semantic_no_backends.get_correction_history()
        assert result == []
