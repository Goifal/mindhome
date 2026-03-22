"""
Tests fuer Semantic Memory — Fakten-Speicherung, Duplikat-Erkennung,
Widerspruchs-Erkennung, Decay und explizites Notizbuch.
"""

import json
from datetime import datetime, timedelta, timezone
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

    # Pipeline-Mock: delegiert Aufrufe an die entsprechenden Redis-Methoden
    def _make_pipe():
        pipe_ops = []
        pipe = MagicMock()

        def _track(method_name):
            def _side_effect(*args, **kwargs):
                pipe_ops.append((method_name, args, kwargs))

            return _side_effect

        pipe.hgetall = MagicMock(side_effect=_track("hgetall"))
        pipe.hget = MagicMock(side_effect=_track("hget"))
        pipe.hset = MagicMock(side_effect=_track("hset"))
        pipe.sadd = MagicMock(side_effect=_track("sadd"))
        pipe.srem = MagicMock(side_effect=_track("srem"))
        pipe.scard = MagicMock(side_effect=_track("scard"))
        pipe.delete = MagicMock(side_effect=_track("delete"))

        async def _execute():
            results = []
            for method_name, args, kwargs in pipe_ops:
                fn = getattr(r, method_name)
                results.append(await fn(*args, **kwargs))
            return results

        pipe.execute = AsyncMock(side_effect=_execute)
        return pipe

    r.pipeline = MagicMock(side_effect=_make_pipe)
    return r


@pytest.fixture
def chroma_mock():
    """ChromaDB Collection Mock."""
    coll = MagicMock()
    coll.add = MagicMock()
    coll.update = MagicMock()
    coll.delete = MagicMock()
    coll.query = MagicMock(
        return_value={
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
            "ids": [[]],
        }
    )
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
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
                "ids": [[]],
            }
        )

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
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [["Max bevorzugt 21 Grad"]],
                "metadatas": [
                    [
                        {
                            "fact_id": "existing_123",
                            "content": "Max bevorzugt 21 Grad",
                            "confidence": "0.75",
                            "times_confirmed": "2",
                            "category": "preference",
                            "person": "Max",
                        }
                    ]
                ],
                "distances": [[0.05]],  # Sehr aehnlich -> Duplikat
                "ids": [["existing_123"]],
            }
        )

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
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
                "ids": [[]],
            }
        )
        chroma_mock.add.side_effect = Exception("ChromaDB unreachable")

        fact = SemanticFact(content="Test", category="general")
        result = await semantic.store_fact(fact)
        assert result is True


# =====================================================================
# _update_existing_fact
# =====================================================================


class TestUpdateExistingFact:
    """Tests fuer das Aktualisieren bestehender Fakten."""

    @pytest.mark.asyncio
    async def test_update_increments_confirmation(
        self, semantic, redis_mock, chroma_mock
    ):
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
    async def test_update_uses_newer_content(self, semantic, chroma_mock):
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

        # Neuerer Content wird immer verwendet
        updated_doc = chroma_mock.update.call_args[1]["documents"][0]
        assert "morgens" in updated_doc

    @pytest.mark.asyncio
    async def test_update_newer_shorter_content_wins(self, semantic, chroma_mock):
        """Auch kuerzerer neuer Content gewinnt ueber laengeren alten."""
        existing = {
            "fact_id": "fact_y",
            "content": "Max trinkt morgens immer einen starken Kaffee mit Milch",
            "confidence": "0.7",
            "times_confirmed": "1",
        }
        new_fact = SemanticFact(
            content="Max trinkt keinen Kaffee mehr",
            category="habit",
        )

        await semantic._update_existing_fact(existing, new_fact)

        updated_doc = chroma_mock.update.call_args[1]["documents"][0]
        assert updated_doc == "Max trinkt keinen Kaffee mehr"

    @pytest.mark.asyncio
    async def test_update_no_fact_id_returns_false(self, semantic):
        result = await semantic._update_existing_fact(
            {}, SemanticFact(content="X", category="general")
        )
        assert result is False


# =====================================================================
# _check_contradiction
# =====================================================================


class TestContradictionDetection:
    """Tests fuer Widerspruchs-Erkennung."""

    @pytest.mark.asyncio
    async def test_no_contradiction_empty_results(self, semantic, chroma_mock):
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
                "ids": [[]],
            }
        )
        fact = SemanticFact(
            content="Max mag 21 Grad", category="preference", person="Max"
        )
        result = await semantic._check_contradiction(fact)
        assert result is None

    @pytest.mark.asyncio
    async def test_contradiction_detected_different_numbers(
        self, semantic, chroma_mock
    ):
        # Alter Fakt: 21 Grad, neuer Fakt: 23 Grad
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [["Max bevorzugt 21 Grad im Buero"]],
                "metadatas": [[{"category": "preference", "person": "Max"}]],
                "distances": [[0.3]],  # Zwischen 0.15 und 0.8 -> verwandt
                "ids": [["fact_old"]],
            }
        )

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
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [["Max bevorzugt 21 Grad"]],
                "metadatas": [[{"category": "preference", "person": "Max"}]],
                "distances": [[0.3]],
                "ids": [["fact_old"]],
            }
        )

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
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [["Lisa isst gern Pizza"]],
                "metadatas": [[{"category": "preference", "person": "Lisa"}]],
                "distances": [[0.9]],
                "ids": [["fact_other"]],
            }
        )

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
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [["Max bevorzugt 21 Grad"]],
                "metadatas": [[{"category": "preference", "person": "Max"}]],
                "distances": [[0.05]],
                "ids": [["fact_old"]],
            }
        )

        fact = SemanticFact(
            content="Max bevorzugt 21 Grad",
            category="preference",
            person="Max",
        )
        result = await semantic._check_contradiction(fact)
        assert result is None

    @pytest.mark.asyncio
    async def test_contradiction_cross_category(self, semantic, chroma_mock):
        """Widerspruch ueber Kategorie-Grenzen: preference vs habit."""
        # Erster Aufruf (gleiche Kategorie) findet nichts
        # Zweiter Aufruf (nur Person) findet den Widerspruch
        call_count = [0]

        def _query_side_effect(**kwargs):
            call_count[0] += 1
            where = kwargs.get("where", {})
            # Erster Aufruf: category + person Filter -> nichts
            if isinstance(where, dict) and "$and" in where:
                return {
                    "documents": [[]],
                    "metadatas": [[]],
                    "distances": [[]],
                    "ids": [[]],
                }
            # Zweiter Aufruf: nur person Filter -> findet alten Fakt
            return {
                "documents": [["Max mag Kaffee"]],
                "metadatas": [[{"category": "preference", "person": "Max"}]],
                "distances": [[0.3]],
                "ids": [["fact_old"]],
            }

        chroma_mock.query = MagicMock(side_effect=_query_side_effect)

        fact = SemanticFact(
            content="Max hasst Kaffee",
            category="habit",
            person="Max",
        )
        result = await semantic._check_contradiction(fact)

        assert result is not None
        assert result["fact_id"] == "fact_old"
        assert "mag" in result["content"]

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
        old_date = (datetime.now(timezone.utc) - timedelta(days=35)).isoformat()
        redis_mock.smembers = AsyncMock(return_value={"fact_1"})
        redis_mock.hgetall = AsyncMock(
            return_value={
                "fact_id": "fact_1",
                "confidence": "0.5",
                "updated_at": old_date,
                "source_conversation": "User: test",
                "times_confirmed": "1",
            }
        )

        await semantic.apply_decay()

        # Confidence sollte um 0.05 reduziert worden sein
        redis_mock.hset.assert_called()
        call_args = redis_mock.hset.call_args_list
        # Finde den confidence-Update Call
        conf_update = [
            c for c in call_args if len(c[0]) >= 3 and c[0][1] == "confidence"
        ]
        assert len(conf_update) == 1
        new_conf = float(conf_update[0][0][2])
        # Decay-Rate: 0.02 pro 30 Tage → 0.5 - 0.02 = 0.48
        assert new_conf == pytest.approx(0.48, abs=0.01)

    @pytest.mark.asyncio
    async def test_decay_explicit_fact_slower(self, semantic, redis_mock):
        old_date = (datetime.now(timezone.utc) - timedelta(days=35)).isoformat()
        redis_mock.smembers = AsyncMock(return_value={"fact_2"})
        redis_mock.hgetall = AsyncMock(
            return_value={
                "fact_id": "fact_2",
                "confidence": "1.0",
                "updated_at": old_date,
                "source_conversation": "explicit",
                "times_confirmed": "1",
            }
        )

        await semantic.apply_decay()

        # Explizite Fakten: nur 1% Decay
        conf_update = [
            c
            for c in redis_mock.hset.call_args_list
            if len(c[0]) >= 3 and c[0][1] == "confidence"
        ]
        assert len(conf_update) == 1
        new_conf = float(conf_update[0][0][2])
        assert new_conf == pytest.approx(0.99, abs=0.01)

    @pytest.mark.asyncio
    async def test_decay_frequently_confirmed_slower(self, semantic, redis_mock):
        old_date = (datetime.now(timezone.utc) - timedelta(days=35)).isoformat()
        redis_mock.smembers = AsyncMock(return_value={"fact_3"})
        redis_mock.hgetall = AsyncMock(
            return_value={
                "fact_id": "fact_3",
                "confidence": "0.5",
                "updated_at": old_date,
                "source_conversation": "User: test",
                "times_confirmed": "5",  # >= 5 -> 50% langsamer
            }
        )

        await semantic.apply_decay()

        conf_update = [
            c
            for c in redis_mock.hset.call_args_list
            if len(c[0]) >= 3 and c[0][1] == "confidence"
        ]
        assert len(conf_update) == 1
        new_conf = float(conf_update[0][0][2])
        # 0.02 * 0.25 = 0.005 Decay -> 0.5 - 0.005 = 0.495
        assert new_conf == pytest.approx(0.495, abs=0.01)

    @pytest.mark.asyncio
    async def test_decay_deletes_below_threshold(self, semantic, redis_mock):
        old_date = (datetime.now(timezone.utc) - timedelta(days=35)).isoformat()
        redis_mock.smembers = AsyncMock(return_value={"fact_weak"})
        redis_mock.hgetall = AsyncMock(
            return_value={
                "fact_id": "fact_weak",
                "content": "Unwichtiger Fakt",
                "confidence": "0.2",
                "updated_at": old_date,
                "source_conversation": "User: x",
                "times_confirmed": "1",
                "person": "unknown",
                "category": "general",
            }
        )

        await semantic.apply_decay()

        # Fakt sollte geloescht werden (0.2 - 0.05 = 0.15 < 0.2)
        redis_mock.delete.assert_called()

    @pytest.mark.asyncio
    async def test_decay_skips_recent_facts(self, semantic, redis_mock):
        recent_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        redis_mock.smembers = AsyncMock(return_value={"fact_new"})
        redis_mock.hgetall = AsyncMock(
            return_value={
                "fact_id": "fact_new",
                "confidence": "0.5",
                "updated_at": recent_date,
                "source_conversation": "User: x",
                "times_confirmed": "1",
            }
        )

        await semantic.apply_decay()

        # Keine Aenderung bei frischen Fakten (< 30 Tage)
        # hset sollte nicht fuer confidence aufgerufen werden
        conf_updates = [
            c
            for c in redis_mock.hset.call_args_list
            if len(c[0]) >= 3 and c[0][1] == "confidence"
        ]
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
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [["Max mag warmes Licht"]],
                "metadatas": [[{"fact_id": "f1", "category": "preference"}]],
                "distances": [[0.1]],
            }
        )
        result = await semantic.find_similar_fact("Max bevorzugt warmes Licht")
        assert result is not None
        assert result["fact_id"] == "f1"

    @pytest.mark.asyncio
    async def test_find_similar_no_match(self, semantic, chroma_mock):
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [["Etwas ganz anderes"]],
                "metadatas": [[{"fact_id": "f2"}]],
                "distances": [[0.9]],  # Zu weit weg
            }
        )
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
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [["Max mag 21 Grad", "Max trinkt Kaffee"]],
                "metadatas": [
                    [
                        {
                            "category": "preference",
                            "person": "Max",
                            "confidence": "0.8",
                            "times_confirmed": "3",
                        },
                        {
                            "category": "habit",
                            "person": "Max",
                            "confidence": "0.7",
                            "times_confirmed": "1",
                        },
                    ]
                ],
                "distances": [[0.1, 0.4]],
            }
        )

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
        redis_mock.hgetall = AsyncMock(
            return_value={
                "content": "Haselnuss-Allergie",
                "category": "health",
                "person": "Max",
                "confidence": "0.95",
            }
        )

        result = await semantic.get_facts_by_category("health")
        assert len(result) == 1
        assert result[0]["category"] == "health"

    @pytest.mark.asyncio
    async def test_get_all_facts(self, semantic, redis_mock):
        redis_mock.smembers = AsyncMock(return_value={"f1"})
        redis_mock.hgetall = AsyncMock(
            return_value={
                "fact_id": "f1",
                "content": "Test Fakt",
                "category": "general",
                "person": "Max",
                "confidence": "0.5",
                "times_confirmed": "1",
                "created_at": "2026-02-20T10:00:00",
                "updated_at": "2026-02-20T10:00:00",
            }
        )

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
        redis_mock.hgetall = AsyncMock(
            return_value={
                "person": "Max",
                "category": "preference",
            }
        )
        # F-030: Lock-Acquire muss gelingen
        redis_mock.set = AsyncMock(return_value=True)

        result = await semantic.delete_fact("fact_123")

        assert result is True
        chroma_mock.delete.assert_called_once_with(ids=["fact_123"])
        redis_mock.srem.assert_any_call("mha:facts:person:Max", "fact_123")
        redis_mock.srem.assert_any_call("mha:facts:category:preference", "fact_123")
        redis_mock.srem.assert_any_call("mha:facts:all", "fact_123")
        # delete wird 2x aufgerufen: Fakt + Lock-Cleanup (F-030)
        redis_mock.delete.assert_any_call("mha:fact:fact_123")
        redis_mock.delete.assert_any_call("mha:fact_lock:del:fact_123")
        assert redis_mock.delete.call_count == 2

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
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
                "ids": [[]],
            }
        )

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
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
                "ids": [[]],
            }
        )

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
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [["Max arbeitet an Projekt Aurora"]],
                "metadatas": [
                    [
                        {
                            "category": "work",
                            "person": "Max",
                            "confidence": "0.7",
                            "times_confirmed": "2",
                            "source_conversation": "User: Was mache ich gerade?",
                            "created_at": "2026-02-15T10:00:00",
                        }
                    ]
                ],
                "distances": [[0.5]],
            }
        )

        results = await semantic.search_by_topic("Arbeit Projekt")
        assert len(results) == 1
        assert results[0]["relevance"] == pytest.approx(0.5)
        assert "source" in results[0]

    @pytest.mark.asyncio
    async def test_search_by_topic_filters_distant(self, semantic, chroma_mock):
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [["Etwas voellig unverwandtes"]],
                "metadatas": [
                    [
                        {
                            "category": "general",
                            "person": "unknown",
                            "confidence": "0.3",
                            "times_confirmed": "1",
                            "source_conversation": "",
                            "created_at": "",
                        }
                    ]
                ],
                "distances": [[1.8]],  # > 1.5 -> wird gefiltert
            }
        )

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
    async def test_forget_deletes_matching_facts(
        self, semantic, chroma_mock, redis_mock
    ):
        # search_by_topic findet Fakten
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [["Max mag Pizza"]],
                "metadatas": [
                    [
                        {
                            "category": "preference",
                            "person": "Max",
                            "confidence": "0.8",
                            "times_confirmed": "1",
                            "source_conversation": "",
                            "created_at": "",
                        }
                    ]
                ],
                "distances": [[0.2]],  # Relevance = 0.8 -> > 0.4 Threshold
                "ids": [["fact_pizza"]],
            }
        )

        redis_mock.hgetall = AsyncMock(
            return_value={
                "person": "Max",
                "category": "preference",
            }
        )

        deleted = await semantic.forget("Pizza")
        assert deleted >= 1

    @pytest.mark.asyncio
    async def test_forget_skips_low_relevance(self, semantic, chroma_mock):
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [["Etwas kaum verwandtes"]],
                "metadatas": [
                    [
                        {
                            "category": "general",
                            "person": "unknown",
                            "confidence": "0.3",
                            "times_confirmed": "1",
                            "source_conversation": "",
                            "created_at": "",
                        }
                    ]
                ],
                "distances": [[0.8]],  # Relevance = 0.2 -> < 0.4 Threshold
                "ids": [["fact_unrelated"]],
            }
        )

        deleted = await semantic.forget("Kaffee")
        assert deleted == 0


# =====================================================================
# get_todays_learnings / get_stats / get_correction_history
# =====================================================================


class TestUtilities:
    """Tests fuer Hilfs-Methoden."""

    @pytest.mark.asyncio
    async def test_get_todays_learnings(self, semantic, redis_mock):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
        redis_mock.scard = AsyncMock(
            side_effect=lambda key: {
                "mha:facts:all": 10,
                "mha:facts:category:preference": 4,
                "mha:facts:category:person": 3,
                "mha:facts:category:habit": 2,
                "mha:facts:category:health": 1,
            }.get(key, 0)
        )
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
        redis_mock.hgetall = AsyncMock(
            return_value={
                "content": "Temperatur korrigiert auf 22",
                "category": "preference",
                "person": "Max",
                "confidence": "0.9",
                "source_conversation": "correction: Max sagte 22 nicht 21",
                "created_at": "2026-02-20T10:00:00",
            }
        )

        result = await semantic.get_correction_history()
        assert len(result) == 1
        assert "korrigiert" in result[0]["content"]

    @pytest.mark.asyncio
    async def test_get_correction_history_no_redis(self, semantic_no_backends):
        result = await semantic_no_backends.get_correction_history()
        assert result == []


# =====================================================================
# FACT_CATEGORIES Completeness
# =====================================================================


class TestFactCategories:
    """Tests fuer die Definition und Vollstaendigkeit der Fakten-Kategorien."""

    def test_all_9_categories_defined(self):
        """Alle 10 Kategorien sind definiert (9 Original + scene_preference)."""
        expected = [
            "preference",
            "person",
            "habit",
            "health",
            "work",
            "personal_date",
            "intent",
            "conversation_topic",
            "general",
            "scene_preference",
        ]
        for cat in expected:
            assert cat in FACT_CATEGORIES, f"Kategorie '{cat}' fehlt in FACT_CATEGORIES"

    def test_no_duplicate_categories(self):
        assert len(FACT_CATEGORIES) == len(set(FACT_CATEGORIES))


# =====================================================================
# SemanticFact date_meta
# =====================================================================


class TestSemanticFactDateMeta:
    """Tests fuer date_meta Felder in SemanticFact."""

    def test_to_dict_with_date_meta(self):
        fact = SemanticFact(
            content="Lisas Geburtstag ist am 15. Maerz",
            category="personal_date",
            person="Lisa",
            date_meta={
                "date_type": "birthday",
                "date_mm_dd": "03-15",
                "year": "1992",
                "label": "Geburtstag",
            },
        )
        d = fact.to_dict()
        assert d["date_type"] == "birthday"
        assert d["date_mm_dd"] == "03-15"
        assert d["date_year"] == "1992"
        assert d["date_label"] == "Geburtstag"

    def test_to_dict_without_date_meta(self):
        fact = SemanticFact(content="Normaler Fakt", category="general")
        d = fact.to_dict()
        assert "date_type" not in d
        assert "date_mm_dd" not in d

    def test_from_dict_restores_date_meta(self):
        data = {
            "content": "Geburtstag",
            "category": "personal_date",
            "date_type": "birthday",
            "date_mm_dd": "03-15",
            "date_year": "1992",
            "date_label": "Geburtstag",
        }
        fact = SemanticFact.from_dict(data)
        assert fact.date_meta is not None
        assert fact.date_meta["date_type"] == "birthday"
        assert fact.date_meta["date_mm_dd"] == "03-15"

    def test_from_dict_no_date_meta_when_missing(self):
        data = {"content": "Normal", "category": "general"}
        fact = SemanticFact.from_dict(data)
        assert fact.date_meta is None


# =====================================================================
# store_fact — Backend Failure Scenarios
# =====================================================================


class TestStoreFactEdgeCases:
    """Tests fuer store_fact bei verschiedenen Fehlerzustaenden."""

    @pytest.mark.asyncio
    async def test_store_fact_no_backends_returns_false(self, semantic_no_backends):
        """Ohne Redis und ChromaDB wird False zurueckgegeben."""
        fact = SemanticFact(content="Test Fakt", category="general")
        # find_similar_fact returns None (no chroma), no contradiction check
        result = await semantic_no_backends.store_fact(fact)
        assert result is False

    @pytest.mark.asyncio
    async def test_store_fact_redis_error_returns_false(
        self, semantic, redis_mock, chroma_mock
    ):
        """Redis-Fehler beim Schreiben fuehrt zu False."""
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
                "ids": [[]],
            }
        )

        # Pipeline execute wirft Exception
        def _make_failing_pipe():
            pipe = MagicMock()
            pipe.hset = MagicMock()
            pipe.sadd = MagicMock()
            pipe.execute = AsyncMock(side_effect=Exception("Redis pipeline error"))
            return pipe

        redis_mock.pipeline = MagicMock(side_effect=_make_failing_pipe)

        fact = SemanticFact(content="Test", category="general")
        result = await semantic.store_fact(fact)
        assert result is False

    @pytest.mark.asyncio
    async def test_store_fact_lock_retry_success(
        self, semantic, redis_mock, chroma_mock
    ):
        """Lock wird beim Retry erhalten."""
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
                "ids": [[]],
            }
        )

        # Erster Lock-Versuch schlaegt fehl, zweiter gelingt
        redis_mock.set = AsyncMock(side_effect=[False, True])

        fact = SemanticFact(content="Lock Retry Test", category="general")
        result = await semantic.store_fact(fact)
        assert result is True

    @pytest.mark.asyncio
    async def test_store_fact_lock_both_retries_fail(
        self, semantic, redis_mock, chroma_mock
    ):
        """Lock kann auch nach Retry nicht erhalten werden."""
        redis_mock.set = AsyncMock(return_value=False)

        fact = SemanticFact(content="Lock Fail Test", category="general")
        result = await semantic.store_fact(fact)
        assert result is False

    @pytest.mark.asyncio
    async def test_store_person_fact_refreshes_cache(
        self, semantic, redis_mock, chroma_mock
    ):
        """Person-Fakten triggern einen Relationship-Cache-Refresh."""
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
                "ids": [[]],
            }
        )

        fact = SemanticFact(
            content="Lisa ist Max' Freundin", category="person", person="Max"
        )
        with patch.object(
            semantic, "refresh_relationship_cache", new_callable=AsyncMock
        ) as mock_refresh:
            await semantic.store_fact(fact)
            mock_refresh.assert_called_once()


# =====================================================================
# search_facts — Redis Fallback
# =====================================================================


class TestSearchFactsRedisFallback:
    """Tests fuer die Redis-Fallback-Suche wenn ChromaDB nicht verfuegbar ist."""

    @pytest.mark.asyncio
    async def test_redis_fallback_keyword_matching(self, redis_mock):
        """Redis-Fallback findet Fakten per Keyword-Matching."""
        sm = SemanticMemory()
        sm.redis = redis_mock
        sm.chroma_collection = None  # Kein ChromaDB -> Fallback

        redis_mock.smembers = AsyncMock(return_value={"f1", "f2"})

        async def hgetall_side(key):
            data = {
                "mha:fact:f1": {
                    "fact_id": "f1",
                    "content": "Max bevorzugt Kaffee am Morgen",
                    "category": "preference",
                    "person": "Max",
                    "confidence": "0.8",
                    "times_confirmed": "1",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                "mha:fact:f2": {
                    "fact_id": "f2",
                    "content": "Lisa mag Tee am Abend",
                    "category": "preference",
                    "person": "Lisa",
                    "confidence": "0.7",
                    "times_confirmed": "1",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            }
            return data.get(key, {})

        redis_mock.hgetall = AsyncMock(side_effect=hgetall_side)

        results = await sm.search_facts("Kaffee Morgen", limit=5)
        assert len(results) >= 1
        # Der Kaffee-Fakt sollte gefunden werden
        assert any("Kaffee" in r["content"] for r in results)

    @pytest.mark.asyncio
    async def test_redis_fallback_person_filter(self, redis_mock):
        """Redis-Fallback filtert nach Person."""
        sm = SemanticMemory()
        sm.redis = redis_mock
        sm.chroma_collection = None

        redis_mock.smembers = AsyncMock(return_value={"f1"})
        redis_mock.hgetall = AsyncMock(
            return_value={
                "fact_id": "f1",
                "content": "Max mag Kaffee",
                "category": "preference",
                "person": "Max",
                "confidence": "0.8",
                "times_confirmed": "1",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

        results = await sm.search_facts("Kaffee", person="Max")
        redis_mock.smembers.assert_called_with("mha:facts:person:Max")

    @pytest.mark.asyncio
    async def test_redis_fallback_filters_low_confidence(self, redis_mock):
        """Redis-Fallback filtert Fakten mit zu niedriger Confidence."""
        sm = SemanticMemory()
        sm.redis = redis_mock
        sm.chroma_collection = None

        redis_mock.smembers = AsyncMock(return_value={"f1"})
        redis_mock.hgetall = AsyncMock(
            return_value={
                "fact_id": "f1",
                "content": "Alter verfallener Fakt ueber Kaffee",
                "category": "general",
                "person": "Max",
                "confidence": "0.1",  # Unter min_confidence (0.4)
                "times_confirmed": "1",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

        results = await sm.search_facts("Kaffee")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_chroma_failure_falls_back_to_redis(
        self, semantic, chroma_mock, redis_mock
    ):
        """Bei ChromaDB-Fehler wird automatisch Redis-Fallback genutzt."""
        chroma_mock.query = MagicMock(side_effect=Exception("ChromaDB down"))
        redis_mock.smembers = AsyncMock(return_value=set())

        results = await semantic.search_facts("Test")
        assert results == []
        # Redis-Fallback wurde aufgerufen
        redis_mock.smembers.assert_called()

    @pytest.mark.asyncio
    async def test_search_no_backends_returns_empty(self, semantic_no_backends):
        results = await semantic_no_backends.search_facts("Test")
        assert results == []


# =====================================================================
# search_facts — Confidence Filtering
# =====================================================================


class TestSearchFactsConfidenceFilter:
    """Tests fuer Confidence-basierte Filterung bei ChromaDB-Suche."""

    @pytest.mark.asyncio
    async def test_search_filters_low_confidence_facts(self, semantic, chroma_mock):
        """Fakten unter min_confidence werden nicht zurueckgegeben."""
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [["Fakt mit hoher Conf", "Fakt mit niedriger Conf"]],
                "metadatas": [
                    [
                        {
                            "category": "preference",
                            "person": "Max",
                            "confidence": "0.8",
                            "times_confirmed": "3",
                        },
                        {
                            "category": "general",
                            "person": "Max",
                            "confidence": "0.1",
                            "times_confirmed": "1",
                        },
                    ]
                ],
                "distances": [[0.2, 0.3]],
            }
        )

        results = await semantic.search_facts("Max", limit=5)
        # Nur der Fakt mit confidence >= 0.4 sollte zurueckgegeben werden
        assert len(results) == 1
        assert results[0]["confidence"] == 0.8


# =====================================================================
# parse_date_from_text
# =====================================================================


class TestParseDateFromText:
    """Tests fuer das Datums-Parsing aus deutschem Text."""

    def test_parse_day_month_name(self):
        result = SemanticMemory.parse_date_from_text("am 15. Maerz")
        assert result == "03-15"

    def test_parse_day_month_name_umlaut(self):
        result = SemanticMemory.parse_date_from_text("am 15. März")
        assert result == "03-15"

    def test_parse_numeric_format(self):
        result = SemanticMemory.parse_date_from_text("am 7.6.")
        assert result == "06-07"

    def test_parse_numeric_with_year(self):
        result = SemanticMemory.parse_date_from_text("am 15.3.1992")
        assert result == "03-15"

    def test_parse_no_date_returns_none(self):
        result = SemanticMemory.parse_date_from_text("Kein Datum hier")
        assert result is None

    def test_parse_invalid_month_returns_none(self):
        result = SemanticMemory.parse_date_from_text("am 15.13.")
        assert result is None

    def test_parse_januar(self):
        result = SemanticMemory.parse_date_from_text("am 1. Januar")
        assert result == "01-01"

    def test_parse_dezember(self):
        result = SemanticMemory.parse_date_from_text("am 24. Dezember")
        assert result == "12-24"


# =====================================================================
# parse_year_from_text
# =====================================================================


class TestParseYearFromText:
    """Tests fuer die Jahreszahl-Extraktion."""

    def test_parse_valid_year(self):
        assert SemanticMemory.parse_year_from_text("geboren 1992 in Berlin") == "1992"

    def test_parse_2000s_year(self):
        assert SemanticMemory.parse_year_from_text("seit 2020 verheiratet") == "2020"

    def test_parse_no_year(self):
        assert SemanticMemory.parse_year_from_text("kein Jahr hier") == ""


# =====================================================================
# store_personal_date
# =====================================================================


class TestStorePersonalDate:
    """Tests fuer das Speichern persoenlicher Daten."""

    @pytest.mark.asyncio
    async def test_store_birthday(self, semantic, chroma_mock):
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
                "ids": [[]],
            }
        )

        result = await semantic.store_personal_date(
            date_type="birthday",
            person_name="Lisa",
            date_mm_dd="03-15",
            year="1992",
        )

        assert result is True
        meta = chroma_mock.add.call_args[1]["metadatas"][0]
        assert meta["category"] == "personal_date"
        assert float(meta["confidence"]) == 1.0
        assert meta["date_type"] == "birthday"
        assert meta["date_mm_dd"] == "03-15"
        content = chroma_mock.add.call_args[1]["documents"][0]
        assert "Lisa" in content
        assert "Geburtstag" in content

    @pytest.mark.asyncio
    async def test_store_anniversary(self, semantic, chroma_mock):
        chroma_mock.query = MagicMock(
            return_value={
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
                "ids": [[]],
            }
        )

        result = await semantic.store_personal_date(
            date_type="anniversary",
            person_name="Max",
            date_mm_dd="06-20",
            year="2018",
            label="Hochzeitstag",
        )

        assert result is True
        content = chroma_mock.add.call_args[1]["documents"][0]
        assert "Hochzeitstag" in content
        assert "2018" in content


# =====================================================================
# delete_fact Edge Cases
# =====================================================================


class TestDeleteFactEdgeCases:
    """Zusaetzliche Tests fuer Fakt-Loeschung."""

    @pytest.mark.asyncio
    async def test_delete_fact_no_redis(self, semantic_no_backends, chroma_mock):
        """Ohne Redis gibt delete_fact False zurueck."""
        semantic_no_backends.chroma_collection = chroma_mock
        result = await semantic_no_backends.delete_fact("fact_123")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_fact_chroma_error_continues(
        self, semantic, redis_mock, chroma_mock
    ):
        """ChromaDB-Fehler beim Loeschen verhindert nicht die Redis-Bereinigung."""
        chroma_mock.delete.side_effect = Exception("ChromaDB error")
        redis_mock.set = AsyncMock(return_value=True)
        redis_mock.hgetall = AsyncMock(
            return_value={
                "person": "Max",
                "category": "preference",
            }
        )

        result = await semantic.delete_fact("fact_456")
        assert result is True
        # Redis-Bereinigung wurde trotzdem ausgefuehrt
        redis_mock.srem.assert_called()

    @pytest.mark.asyncio
    async def test_delete_lock_not_acquired(self, semantic, redis_mock):
        """Wenn der Delete-Lock nicht erhalten wird, gibt delete_fact False zurueck."""
        redis_mock.set = AsyncMock(return_value=False)

        result = await semantic.delete_fact("fact_locked")
        assert result is False


# =====================================================================
# get_facts_by_person / get_facts_by_category Edge Cases
# =====================================================================


class TestFactRetrievalEdgeCases:
    """Edge Cases fuer Fakten-Abruf."""

    @pytest.mark.asyncio
    async def test_get_facts_by_person_empty_set(self, semantic, redis_mock):
        redis_mock.smembers = AsyncMock(return_value=set())
        result = await semantic.get_facts_by_person("Unbekannt")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_facts_by_category_empty_set(self, semantic, redis_mock):
        redis_mock.smembers = AsyncMock(return_value=set())
        result = await semantic.get_facts_by_category("nonexistent")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_facts_by_person_no_redis_uses_search(self, semantic_no_backends):
        """Ohne Redis faellt get_facts_by_person auf search_facts zurueck."""
        result = await semantic_no_backends.get_facts_by_person("Max")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_facts_by_category_no_redis_uses_search(
        self, semantic_no_backends
    ):
        """Ohne Redis faellt get_facts_by_category auf search_facts zurueck."""
        result = await semantic_no_backends.get_facts_by_category("health")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_all_facts_sorted_by_confidence(self, semantic, redis_mock):
        """get_all_facts sortiert nach Confidence (hoch -> niedrig)."""
        redis_mock.smembers = AsyncMock(return_value={"f1", "f2"})

        call_count = [0]

        async def hgetall_side(key):
            call_count[0] += 1
            data = {
                "mha:fact:f1": {
                    "fact_id": "f1",
                    "content": "Niedrig",
                    "category": "general",
                    "person": "Max",
                    "confidence": "0.3",
                    "times_confirmed": "1",
                    "created_at": "",
                    "updated_at": "",
                },
                "mha:fact:f2": {
                    "fact_id": "f2",
                    "content": "Hoch",
                    "category": "preference",
                    "person": "Max",
                    "confidence": "0.9",
                    "times_confirmed": "5",
                    "created_at": "",
                    "updated_at": "",
                },
            }
            return data.get(key, {})

        redis_mock.hgetall = AsyncMock(side_effect=hgetall_side)

        result = await semantic.get_all_facts()
        assert len(result) == 2
        assert result[0]["confidence"] > result[1]["confidence"]

    @pytest.mark.asyncio
    async def test_get_all_facts_handles_exception(self, semantic, redis_mock):
        """get_all_facts faengt Exceptions ab und gibt leere Liste zurueck."""
        redis_mock.smembers = AsyncMock(side_effect=Exception("Redis down"))
        result = await semantic.get_all_facts()
        assert result == []


# =====================================================================
# verify_consistency Tests
# =====================================================================


class TestVerifyConsistency:
    """Tests fuer verify_consistency — Redis/ChromaDB Konsistenz-Pruefung."""

    @pytest.fixture
    def semantic(self, redis_mock, chroma_mock):
        with (
            patch("assistant.semantic_memory.yaml_config", {"timezone": "UTC"}),
            patch("assistant.semantic_memory.settings"),
        ):
            sm = SemanticMemory()
            sm.redis = redis_mock
            sm.chroma_collection = chroma_mock
            return sm

    @pytest.mark.asyncio
    async def test_no_redis_returns_early(self, chroma_mock):
        with (
            patch("assistant.semantic_memory.yaml_config", {"timezone": "UTC"}),
            patch("assistant.semantic_memory.settings"),
        ):
            sm = SemanticMemory()
        sm.chroma_collection = chroma_mock
        await sm.verify_consistency()  # No exception

    @pytest.mark.asyncio
    async def test_no_chroma_returns_early(self, redis_mock):
        with (
            patch("assistant.semantic_memory.yaml_config", {"timezone": "UTC"}),
            patch("assistant.semantic_memory.settings"),
        ):
            sm = SemanticMemory()
        sm.redis = redis_mock
        await sm.verify_consistency()  # No exception

    @pytest.mark.asyncio
    async def test_empty_redis_returns_early(self, semantic, redis_mock):
        redis_mock.smembers = AsyncMock(return_value=set())
        await semantic.verify_consistency()  # No exception

    @pytest.mark.asyncio
    async def test_reindexes_missing_chroma_facts(
        self, semantic, redis_mock, chroma_mock
    ):
        """Facts in Redis but not in ChromaDB are re-indexed."""
        redis_mock.smembers = AsyncMock(return_value={"fact_1"})
        chroma_mock.get.return_value = {"ids": []}  # Not in ChromaDB
        redis_mock.hgetall = AsyncMock(
            return_value={
                "content": "Test fact",
                "category": "preference",
                "person": "Max",
                "confidence": "0.8",
            }
        )

        await semantic.verify_consistency()
        chroma_mock.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleans_orphaned_redis_ids(self, semantic, redis_mock, chroma_mock):
        """IDs in Redis index with no data are cleaned up."""
        redis_mock.smembers = AsyncMock(return_value={"orphan_id"})
        chroma_mock.get.return_value = {"ids": []}  # Not in ChromaDB
        redis_mock.hgetall = AsyncMock(return_value={})  # No data either

        await semantic.verify_consistency()
        redis_mock.srem.assert_called_with("mha:facts:all", "orphan_id")

    @pytest.mark.asyncio
    async def test_skips_facts_already_in_chroma(
        self, semantic, redis_mock, chroma_mock
    ):
        """Facts found in both Redis and ChromaDB are left alone."""
        redis_mock.smembers = AsyncMock(return_value={"fact_ok"})
        chroma_mock.get.return_value = {"ids": ["fact_ok"]}

        await semantic.verify_consistency()
        chroma_mock.add.assert_not_called()
        redis_mock.srem.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_bytes_fact_ids(self, semantic, redis_mock, chroma_mock):
        """Bytes fact IDs from Redis are decoded correctly."""
        redis_mock.smembers = AsyncMock(return_value={b"fact_bytes"})
        chroma_mock.get.return_value = {"ids": ["fact_bytes"]}

        await semantic.verify_consistency()  # No exception

    @pytest.mark.asyncio
    async def test_chroma_get_error_skips_fact(self, semantic, redis_mock, chroma_mock):
        """ChromaDB get error for a fact skips it without crashing."""
        redis_mock.smembers = AsyncMock(return_value={"fact_err"})
        chroma_mock.get.side_effect = Exception("ChromaDB error")

        await semantic.verify_consistency()  # No exception

    @pytest.mark.asyncio
    async def test_outer_exception_caught(self, semantic, redis_mock):
        """Top-level exception is caught."""
        redis_mock.smembers = AsyncMock(side_effect=Exception("Redis broken"))
        await semantic.verify_consistency()  # No exception


# =====================================================================
# get_upcoming_personal_dates Tests
# =====================================================================


class TestGetUpcomingPersonalDates:
    """Tests fuer get_upcoming_personal_dates."""

    @pytest.fixture
    def semantic(self, redis_mock, chroma_mock):
        with (
            patch("assistant.semantic_memory.yaml_config", {"timezone": "UTC"}),
            patch("assistant.semantic_memory.settings"),
        ):
            sm = SemanticMemory()
            sm.redis = redis_mock
            sm.chroma_collection = chroma_mock
            return sm

    @pytest.mark.asyncio
    async def test_no_redis_returns_empty(self):
        with (
            patch("assistant.semantic_memory.yaml_config", {"timezone": "UTC"}),
            patch("assistant.semantic_memory.settings"),
        ):
            sm = SemanticMemory()
        result = await sm.get_upcoming_personal_dates()
        assert result == []

    @pytest.mark.asyncio
    async def test_no_personal_date_facts(self, semantic, redis_mock):
        redis_mock.smembers = AsyncMock(return_value=set())
        result = await semantic.get_upcoming_personal_dates()
        assert result == []

    @pytest.mark.asyncio
    async def test_finds_upcoming_date(self, semantic, redis_mock):
        """Finds a personal date within the upcoming days."""
        redis_mock.smembers = AsyncMock(return_value={"pd_1"})

        # Set date to tomorrow
        from datetime import datetime, timedelta, timezone

        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%m-%d")

        pipe_mock = MagicMock()
        pipe_mock.hgetall = MagicMock()
        pipe_mock.execute = AsyncMock(
            return_value=[
                {
                    "fact_id": "pd_1",
                    "person": "Lisa",
                    "date_type": "birthday",
                    "date_mm_dd": tomorrow,
                    "date_year": "1990",
                    "date_label": "Geburtstag",
                    "content": f"Lisas Geburtstag ist am {tomorrow}",
                }
            ]
        )
        redis_mock.pipeline = MagicMock(return_value=pipe_mock)

        result = await semantic.get_upcoming_personal_dates(days_ahead=7)
        assert len(result) == 1
        assert result[0]["person"] == "Lisa"
        assert result[0]["days_until"] == 1

    @pytest.mark.asyncio
    async def test_excludes_dates_beyond_range(self, semantic, redis_mock):
        """Dates beyond days_ahead are excluded."""
        redis_mock.smembers = AsyncMock(return_value={"pd_1"})

        from datetime import datetime, timedelta, timezone

        far_future = (datetime.now(timezone.utc) + timedelta(days=60)).strftime("%m-%d")

        pipe_mock = MagicMock()
        pipe_mock.hgetall = MagicMock()
        pipe_mock.execute = AsyncMock(
            return_value=[
                {
                    "fact_id": "pd_1",
                    "person": "Max",
                    "date_type": "birthday",
                    "date_mm_dd": far_future,
                    "content": "Max birthday",
                }
            ]
        )
        redis_mock.pipeline = MagicMock(return_value=pipe_mock)

        result = await semantic.get_upcoming_personal_dates(days_ahead=30)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_calculates_anniversary_years(self, semantic, redis_mock):
        """Calculates anniversary years correctly."""
        redis_mock.smembers = AsyncMock(return_value={"pd_1"})

        from datetime import datetime, timedelta, timezone

        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%m-%d")

        pipe_mock = MagicMock()
        pipe_mock.hgetall = MagicMock()
        pipe_mock.execute = AsyncMock(
            return_value=[
                {
                    "fact_id": "pd_1",
                    "person": "Lisa",
                    "date_type": "birthday",
                    "date_mm_dd": tomorrow,
                    "date_year": "1990",
                    "content": "Birthday",
                }
            ]
        )
        redis_mock.pipeline = MagicMock(return_value=pipe_mock)

        result = await semantic.get_upcoming_personal_dates(days_ahead=7)
        assert len(result) == 1
        assert result[0]["anniversary_years"] > 30

    @pytest.mark.asyncio
    async def test_skips_entries_without_date_mm_dd(self, semantic, redis_mock):
        """Entries without date_mm_dd are skipped."""
        redis_mock.smembers = AsyncMock(return_value={"pd_1"})

        pipe_mock = MagicMock()
        pipe_mock.hgetall = MagicMock()
        pipe_mock.execute = AsyncMock(
            return_value=[
                {
                    "fact_id": "pd_1",
                    "person": "Max",
                    "date_type": "birthday",
                    "content": "No date_mm_dd field",
                }
            ]
        )
        redis_mock.pipeline = MagicMock(return_value=pipe_mock)

        result = await semantic.get_upcoming_personal_dates()
        assert result == []

    @pytest.mark.asyncio
    async def test_handles_invalid_date_format(self, semantic, redis_mock):
        """Invalid date_mm_dd is skipped gracefully."""
        redis_mock.smembers = AsyncMock(return_value={"pd_1"})

        pipe_mock = MagicMock()
        pipe_mock.hgetall = MagicMock()
        pipe_mock.execute = AsyncMock(
            return_value=[
                {
                    "fact_id": "pd_1",
                    "person": "Max",
                    "date_type": "birthday",
                    "date_mm_dd": "invalid",
                    "content": "Bad date",
                }
            ]
        )
        redis_mock.pipeline = MagicMock(return_value=pipe_mock)

        result = await semantic.get_upcoming_personal_dates()
        assert result == []

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self, semantic, redis_mock):
        redis_mock.smembers = AsyncMock(side_effect=Exception("Redis down"))
        result = await semantic.get_upcoming_personal_dates()
        assert result == []

    @pytest.mark.asyncio
    async def test_sorted_by_days_until(self, semantic, redis_mock):
        """Results are sorted by days_until ascending."""
        redis_mock.smembers = AsyncMock(return_value={"pd_1", "pd_2"})

        from datetime import datetime, timedelta, timezone

        d1 = (datetime.now(timezone.utc) + timedelta(days=5)).strftime("%m-%d")
        d2 = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%m-%d")

        pipe_mock = MagicMock()
        pipe_mock.hgetall = MagicMock()
        pipe_mock.execute = AsyncMock(
            return_value=[
                {
                    "fact_id": "pd_1",
                    "person": "A",
                    "date_type": "birthday",
                    "date_mm_dd": d1,
                    "content": "A",
                },
                {
                    "fact_id": "pd_2",
                    "person": "B",
                    "date_type": "birthday",
                    "date_mm_dd": d2,
                    "content": "B",
                },
            ]
        )
        redis_mock.pipeline = MagicMock(return_value=pipe_mock)

        result = await semantic.get_upcoming_personal_dates(days_ahead=30)
        assert len(result) == 2
        assert result[0]["days_until"] <= result[1]["days_until"]


# =====================================================================
# get_relevant_conversations Tests
# =====================================================================


class TestGetRelevantConversations:
    """Tests fuer get_relevant_conversations."""

    @pytest.fixture
    def semantic(self, redis_mock, chroma_mock):
        with (
            patch("assistant.semantic_memory.yaml_config", {"timezone": "UTC"}),
            patch("assistant.semantic_memory.settings"),
        ):
            sm = SemanticMemory()
            sm.redis = redis_mock
            sm.chroma_collection = chroma_mock
            return sm

    @pytest.mark.asyncio
    async def test_returns_only_conversation_topic_facts(self, semantic, chroma_mock):
        """Only returns facts with category conversation_topic."""
        chroma_mock.query.return_value = {
            "documents": [["topic fact", "preference fact"]],
            "metadatas": [
                [
                    {"category": "conversation_topic", "confidence": "0.9"},
                    {"category": "preference", "confidence": "0.9"},
                ]
            ],
            "distances": [[0.2, 0.3]],
            "ids": [["id1", "id2"]],
        }

        result = await semantic.get_relevant_conversations("smart home")
        assert all(r.get("category") == "conversation_topic" for r in result)

    @pytest.mark.asyncio
    async def test_filters_low_relevance(self, semantic, chroma_mock):
        """Filters out results with relevance <= 0.3."""
        chroma_mock.query.return_value = {
            "documents": [["low relevance topic"]],
            "metadatas": [
                [
                    {"category": "conversation_topic", "confidence": "0.9"},
                ]
            ],
            "distances": [[0.9]],  # distance 0.9 → relevance 0.1
            "ids": [["id1"]],
        }

        result = await semantic.get_relevant_conversations("something")
        assert result == []

    @pytest.mark.asyncio
    async def test_limits_results(self, semantic, chroma_mock):
        """Respects the limit parameter."""
        docs = [f"topic {i}" for i in range(10)]
        metas = [
            {"category": "conversation_topic", "confidence": "0.9"} for _ in range(10)
        ]
        dists = [0.1 + i * 0.02 for i in range(10)]
        ids = [f"id_{i}" for i in range(10)]

        chroma_mock.query.return_value = {
            "documents": [docs],
            "metadatas": [metas],
            "distances": [dists],
            "ids": [ids],
        }

        result = await semantic.get_relevant_conversations("test", limit=3)
        assert len(result) <= 3

    @pytest.mark.asyncio
    async def test_age_bonus_for_recent(self, semantic, chroma_mock):
        """Recent conversations get higher scores."""
        now_iso = datetime.now(timezone.utc).isoformat()
        old_iso = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        chroma_mock.query.return_value = {
            "documents": [["recent topic", "old topic"]],
            "metadatas": [
                [
                    {
                        "category": "conversation_topic",
                        "confidence": "0.9",
                        "created_at": now_iso,
                    },
                    {
                        "category": "conversation_topic",
                        "confidence": "0.9",
                        "created_at": old_iso,
                    },
                ]
            ],
            "distances": [[0.2, 0.2]],
            "ids": [["id1", "id2"]],
        }

        result = await semantic.get_relevant_conversations("test", limit=5)
        # Recent should be ranked first
        if len(result) >= 2:
            assert result[0]["_score"] >= result[1]["_score"]


# =====================================================================
# clear_all Tests
# =====================================================================


class TestClearAll:
    """Tests fuer clear_all — loescht alle Fakten."""

    @pytest.mark.asyncio
    async def test_no_redis_no_chroma(self):
        """Handles no backends gracefully."""
        with (
            patch("assistant.semantic_memory.yaml_config", {"timezone": "UTC"}),
            patch("assistant.semantic_memory.settings"),
        ):
            sm = SemanticMemory()
        result = await sm.clear_all()
        assert result == 0


# =====================================================================
# refresh_relationship_cache Tests
# =====================================================================


class TestRefreshRelationshipCache:
    """Tests fuer refresh_relationship_cache."""

    @pytest.fixture
    def semantic(self, redis_mock, chroma_mock):
        with (
            patch(
                "assistant.semantic_memory.yaml_config",
                {
                    "timezone": "UTC",
                    "household": {
                        "primary_user": "Max",
                        "members": [{"name": "Max"}, {"name": "Lisa"}],
                    },
                    "persons": {"titles": {"Max": "Sir"}},
                },
            ),
            patch("assistant.semantic_memory.settings"),
        ):
            sm = SemanticMemory()
            sm.redis = redis_mock
            sm.chroma_collection = chroma_mock
            return sm

    @pytest.mark.asyncio
    async def test_no_redis_returns_early(self):
        with (
            patch("assistant.semantic_memory.yaml_config", {"timezone": "UTC"}),
            patch("assistant.semantic_memory.settings"),
        ):
            sm = SemanticMemory()
        await sm.refresh_relationship_cache()  # No exception

    @pytest.mark.asyncio
    async def test_builds_relationship_cache(self, semantic, redis_mock):
        """Builds cache from person facts and known names."""
        redis_mock.smembers = AsyncMock(return_value={"f1"})
        pipe_mock = MagicMock()
        pipe_mock.hgetall = MagicMock()
        pipe_mock.execute = AsyncMock(
            return_value=[
                {
                    "content": "Lisa ist die Frau von Max",
                    "category": "person",
                    "person": "Lisa",
                    "confidence": "0.9",
                }
            ]
        )
        redis_mock.pipeline = MagicMock(return_value=pipe_mock)

        await semantic.refresh_relationship_cache()

        assert hasattr(semantic, "_relationship_cache")
        assert hasattr(semantic, "_relationship_cache_ts")

    @pytest.mark.asyncio
    async def test_empty_person_facts(self, semantic, redis_mock):
        """Empty person facts result in empty cache."""
        redis_mock.smembers = AsyncMock(return_value=set())

        await semantic.refresh_relationship_cache()
        assert semantic._relationship_cache == {}

    @pytest.mark.asyncio
    async def test_exception_caught(self, semantic, redis_mock):
        """Exceptions are caught and logged."""
        redis_mock.smembers = AsyncMock(side_effect=Exception("Redis down"))
        await semantic.refresh_relationship_cache()  # No exception


# =====================================================================
# _get_cached_relationship Tests
# =====================================================================


class TestGetCachedRelationship:
    """Tests fuer _get_cached_relationship."""

    def test_returns_cached_value(self):
        with (
            patch("assistant.semantic_memory.yaml_config", {"timezone": "UTC"}),
            patch("assistant.semantic_memory.settings"),
        ):
            sm = SemanticMemory()
        import time

        sm._relationship_cache = {"meine frau": "lisa"}
        sm._relationship_cache_ts = time.monotonic()

        result = sm._get_cached_relationship("meine frau", [], set())
        assert result == "lisa"

    def test_returns_empty_for_unknown_pattern(self):
        with (
            patch("assistant.semantic_memory.yaml_config", {"timezone": "UTC"}),
            patch("assistant.semantic_memory.settings"),
        ):
            sm = SemanticMemory()
        import time

        sm._relationship_cache = {"meine frau": "lisa"}
        sm._relationship_cache_ts = time.monotonic()

        result = sm._get_cached_relationship("mein bruder", [], set())
        assert result == ""

    def test_returns_empty_when_cache_stale(self):
        with (
            patch("assistant.semantic_memory.yaml_config", {"timezone": "UTC"}),
            patch("assistant.semantic_memory.settings"),
        ):
            sm = SemanticMemory()
        import time

        sm._relationship_cache = {"meine frau": "lisa"}
        sm._relationship_cache_ts = time.monotonic() - 400  # Past TTL of 300s

        result = sm._get_cached_relationship("meine frau", [], set())
        assert result == ""

    def test_returns_empty_when_no_cache(self):
        with (
            patch("assistant.semantic_memory.yaml_config", {"timezone": "UTC"}),
            patch("assistant.semantic_memory.settings"),
        ):
            sm = SemanticMemory()
        result = sm._get_cached_relationship("meine frau", [], set())
        assert result == ""


# =====================================================================
# search_by_topic Redis fallback Tests
# =====================================================================


class TestSearchByTopicFallback:
    """Tests fuer search_by_topic Redis-Fallback."""

    @pytest.fixture
    def semantic(self, redis_mock):
        with (
            patch(
                "assistant.semantic_memory.yaml_config",
                {
                    "timezone": "UTC",
                    "memory": {"min_confidence_for_context": 0.4},
                },
            ),
            patch("assistant.semantic_memory.settings"),
        ):
            sm = SemanticMemory()
            sm.redis = redis_mock
            sm.chroma_collection = None  # Force Redis fallback
            return sm

    @pytest.mark.asyncio
    async def test_uses_redis_fallback(self, semantic, redis_mock):
        """When ChromaDB is None, falls back to Redis."""
        redis_mock.smembers = AsyncMock(return_value={"f1"})
        pipe_mock = MagicMock()
        pipe_mock.hgetall = MagicMock()
        pipe_mock.execute = AsyncMock(
            return_value=[
                {
                    "content": "Max mag Kaffee",
                    "fact_id": "f1",
                    "category": "preference",
                    "person": "Max",
                    "confidence": "0.9",
                    "times_confirmed": "2",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            ]
        )
        redis_mock.pipeline = MagicMock(return_value=pipe_mock)

        result = await semantic.search_by_topic("Kaffee")
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_no_backends_returns_empty(self):
        """No ChromaDB and no Redis returns empty list."""
        with (
            patch("assistant.semantic_memory.yaml_config", {"timezone": "UTC"}),
            patch("assistant.semantic_memory.settings"),
        ):
            sm = SemanticMemory()
        result = await sm.search_by_topic("test")
        assert result == []


# =====================================================================
# forget Redis fallback Tests
# =====================================================================


class TestForgetRedisFallback:
    """Tests fuer forget() mit Redis fact_id Lookup."""

    @pytest.fixture
    def semantic(self, redis_mock, chroma_mock):
        with (
            patch(
                "assistant.semantic_memory.yaml_config",
                {
                    "timezone": "UTC",
                    "memory": {"min_confidence_for_context": 0.4},
                },
            ),
            patch("assistant.semantic_memory.settings"),
        ):
            sm = SemanticMemory()
            sm.redis = redis_mock
            sm.chroma_collection = chroma_mock
            return sm

    @pytest.mark.asyncio
    async def test_forget_with_fact_id_from_search(
        self, semantic, chroma_mock, redis_mock
    ):
        """forget() uses fact_id from search_by_topic when available."""
        chroma_mock.query.return_value = {
            "documents": [["Max mag Kaffee"]],
            "metadatas": [[{"category": "preference", "confidence": "0.9"}]],
            "distances": [[0.1]],
            "ids": [["fact_coffee"]],
        }
        # delete_fact needs lock
        redis_mock.set = AsyncMock(return_value=True)
        redis_mock.hgetall = AsyncMock(
            return_value={
                "person": "Max",
                "category": "preference",
            }
        )

        result = await semantic.forget("Kaffee")
        assert result >= 1

    @pytest.mark.asyncio
    async def test_forget_no_matching_facts(self, semantic, chroma_mock):
        """forget() returns 0 when no facts match."""
        chroma_mock.query.return_value = {
            "documents": [["irrelevant"]],
            "metadatas": [[{"category": "general", "confidence": "0.5"}]],
            "distances": [[1.2]],  # Low relevance
            "ids": [["id1"]],
        }

        result = await semantic.forget("nonexistent")
        assert result == 0


# =====================================================================
# _search_facts_chromadb recency boost Tests
# =====================================================================


class TestSearchFactsChromaDBRecencyBoost:
    """Tests fuer Recency-Boost in _search_facts_chromadb."""

    @pytest.fixture
    def semantic(self, redis_mock, chroma_mock):
        with (
            patch(
                "assistant.semantic_memory.yaml_config",
                {
                    "timezone": "UTC",
                    "memory": {"min_confidence_for_context": 0.4},
                },
            ),
            patch("assistant.semantic_memory.settings"),
        ):
            sm = SemanticMemory()
            sm.redis = redis_mock
            sm.chroma_collection = chroma_mock
            return sm

    @pytest.mark.asyncio
    async def test_recent_facts_get_boosted(self, semantic, chroma_mock):
        """Facts updated recently get a recency boost."""
        now_iso = datetime.now(timezone.utc).isoformat()

        chroma_mock.query.return_value = {
            "documents": [["recent fact"]],
            "metadatas": [
                [
                    {
                        "category": "preference",
                        "person": "Max",
                        "confidence": "0.8",
                        "times_confirmed": "1",
                        "updated_at": now_iso,
                    }
                ]
            ],
            "distances": [[0.3]],
        }

        result = await semantic.search_facts("test")
        assert len(result) == 1
        # Relevance should be > base (1.0 - 0.3 = 0.7) due to recency boost
        assert result[0]["relevance"] > 0.7

    @pytest.mark.asyncio
    async def test_old_facts_no_boost(self, semantic, chroma_mock):
        """Facts older than 60 days get no recency boost."""
        old_iso = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()

        chroma_mock.query.return_value = {
            "documents": [["old fact"]],
            "metadatas": [
                [
                    {
                        "category": "preference",
                        "person": "Max",
                        "confidence": "0.8",
                        "times_confirmed": "1",
                        "updated_at": old_iso,
                    }
                ]
            ],
            "distances": [[0.3]],
        }

        result = await semantic.search_facts("test")
        assert len(result) == 1
        # Relevance should be exactly base (1.0 - 0.3 = 0.7)
        assert abs(result[0]["relevance"] - 0.7) < 0.01

    @pytest.mark.asyncio
    async def test_filters_low_confidence(self, semantic, chroma_mock):
        """Facts below min_confidence_for_context are filtered out."""
        chroma_mock.query.return_value = {
            "documents": [["low confidence"]],
            "metadatas": [
                [
                    {
                        "category": "general",
                        "person": "Max",
                        "confidence": "0.2",
                        "times_confirmed": "1",
                    }
                ]
            ],
            "distances": [[0.1]],
        }

        result = await semantic.search_facts("test")
        assert result == []

    @pytest.mark.asyncio
    async def test_invalid_updated_at_no_crash(self, semantic, chroma_mock):
        """Invalid updated_at does not crash."""
        chroma_mock.query.return_value = {
            "documents": [["fact"]],
            "metadatas": [
                [
                    {
                        "category": "general",
                        "person": "Max",
                        "confidence": "0.8",
                        "times_confirmed": "1",
                        "updated_at": "not-a-date",
                    }
                ]
            ],
            "distances": [[0.3]],
        }

        result = await semantic.search_facts("test")
        assert len(result) == 1
