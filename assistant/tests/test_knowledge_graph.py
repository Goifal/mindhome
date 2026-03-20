"""
Tests fuer KnowledgeGraph — Redis-basierter Wissensgraph.

Testet:
- Node-Operationen (add, get, max_nodes guard)
- Edge-Operationen (add, increment, TTL)
- Query-Operationen (get_related, neighbors, 2-hop, context)
- Pruning (schwache Kanten entfernen)
- Stats und Disabled-Zustand
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.knowledge_graph import KnowledgeGraph


@pytest.fixture
def kg(redis_mock):
    """KnowledgeGraph mit Redis-Mock."""
    with patch("assistant.knowledge_graph.yaml_config", {}):
        graph = KnowledgeGraph()
    graph.redis = redis_mock
    graph.enabled = True
    return graph


# ============================================================
# Initialisierung
# ============================================================

class TestKnowledgeGraphInit:

    def test_default_config(self):
        with patch("assistant.knowledge_graph.yaml_config", {}):
            kg = KnowledgeGraph()
        assert kg.enabled is True
        assert kg.max_nodes == 1000
        assert kg.redis is None

    def test_custom_config(self):
        with patch("assistant.knowledge_graph.yaml_config", {
            "knowledge_graph": {"enabled": False, "max_nodes": 500},
        }):
            kg = KnowledgeGraph()
        assert kg.enabled is False
        assert kg.max_nodes == 500

    @pytest.mark.asyncio
    async def test_initialize(self, redis_mock):
        with patch("assistant.knowledge_graph.yaml_config", {}):
            kg = KnowledgeGraph()
        await kg.initialize(redis_client=redis_mock)
        assert kg.redis is redis_mock


# ============================================================
# Node Operations
# ============================================================

class TestNodes:

    @pytest.mark.asyncio
    async def test_add_node(self, kg, redis_mock):
        redis_mock.scard = AsyncMock(return_value=5)
        await kg.add_node("person:max", "person", {"name": "Max"})
        pipe = redis_mock._pipeline
        pipe.hset.assert_called()
        pipe.sadd.assert_called()
        pipe.execute.assert_called()

    @pytest.mark.asyncio
    async def test_add_node_max_reached(self, kg, redis_mock):
        redis_mock.scard = AsyncMock(return_value=1000)
        pipe = redis_mock._pipeline
        pipe.execute.reset_mock()
        await kg.add_node("person:max", "person")
        pipe.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_node_with_type(self, kg, redis_mock):
        node_data = json.dumps({"type": "person", "name": "Max"})
        redis_mock.hget = AsyncMock(return_value=node_data)
        result = await kg.get_node("person:max", "person")
        assert result["name"] == "Max"

    @pytest.mark.asyncio
    async def test_get_node_not_found(self, kg, redis_mock):
        redis_mock.hget = AsyncMock(return_value=None)
        result = await kg.get_node("person:unknown", "person")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_node_search_all_types(self, kg, redis_mock):
        """Ohne Typ werden alle Typen durchsucht."""
        call_count = 0
        async def fake_hget(key, node_id):
            nonlocal call_count
            call_count += 1
            if "nodes:device" in key:
                return json.dumps({"type": "device", "name": "Licht"})
            return None
        redis_mock.hget = fake_hget
        result = await kg.get_node("device:licht")
        assert result is not None
        assert result["type"] == "device"

    @pytest.mark.asyncio
    async def test_disabled_skips(self, redis_mock):
        with patch("assistant.knowledge_graph.yaml_config", {}):
            kg = KnowledgeGraph()
        kg.redis = redis_mock
        kg.enabled = False
        await kg.add_node("person:max", "person")
        redis_mock.pipeline.assert_not_called()


# ============================================================
# Edge Operations
# ============================================================

class TestEdges:

    @pytest.mark.asyncio
    async def test_add_edge(self, kg, redis_mock):
        await kg.add_edge("person:max", "prefers", "device:licht_wz", weight=0.8)
        pipe = redis_mock._pipeline
        pipe.sadd.assert_called()
        pipe.hset.assert_called()
        pipe.expire.assert_called()
        pipe.execute.assert_called()

    @pytest.mark.asyncio
    async def test_increment_existing_edge(self, kg, redis_mock):
        existing = json.dumps({"weight": 0.5, "relation": "prefers", "updated": 0})
        redis_mock.hget = AsyncMock(return_value=existing)
        await kg.increment_edge("person:max", "prefers", "device:licht", delta=0.1)
        redis_mock.hset.assert_called()
        stored = json.loads(redis_mock.hset.call_args[0][2])
        assert abs(stored["weight"] - 0.6) < 0.01

    @pytest.mark.asyncio
    async def test_increment_caps_at_1(self, kg, redis_mock):
        existing = json.dumps({"weight": 0.95, "relation": "prefers", "updated": 0})
        redis_mock.hget = AsyncMock(return_value=existing)
        await kg.increment_edge("person:max", "prefers", "device:licht", delta=0.2)
        stored = json.loads(redis_mock.hset.call_args[0][2])
        assert stored["weight"] == 1.0

    @pytest.mark.asyncio
    async def test_increment_nonexistent_creates(self, kg, redis_mock):
        redis_mock.hget = AsyncMock(return_value=None)
        await kg.increment_edge("person:max", "prefers", "device:licht", delta=0.1)
        pipe = redis_mock._pipeline
        pipe.execute.assert_called()


# ============================================================
# Query Operations
# ============================================================

class TestQueries:

    @pytest.mark.asyncio
    async def test_get_related_out(self, kg, redis_mock):
        redis_mock.smembers = AsyncMock(return_value={"device:licht", "device:heizung"})
        result = await kg.get_related("person:max", "prefers", direction="out")
        assert len(result) == 2
        assert "device:licht" in result

    @pytest.mark.asyncio
    async def test_get_related_in(self, kg, redis_mock):
        redis_mock.smembers = AsyncMock(return_value={"person:max"})
        result = await kg.get_related("device:licht", "prefers", direction="in")
        assert "person:max" in result

    @pytest.mark.asyncio
    async def test_get_neighbors(self, kg, redis_mock):
        redis_mock.smembers = AsyncMock(return_value={"device:a", "room:b"})
        result = await kg.get_neighbors("person:max")
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_query_2hop(self, kg, redis_mock):
        async def mock_smembers(key):
            if "out:located_in:person:max" in key:
                return {"room:wz"}
            if "out:has_preference:room:wz" in key:
                return {"pref:warm"}
            return set()
        redis_mock.smembers = mock_smembers
        result = await kg.query_2hop("person:max", "located_in", "has_preference")
        assert "pref:warm" in result

    @pytest.mark.asyncio
    async def test_query_2hop_deduplicates(self, kg, redis_mock):
        """Gleiche Ergebnisse ueber verschiedene Pfade werden dedupliziert."""
        async def mock_smembers(key):
            if "out:rel1:start" in key:
                return {"mid1", "mid2"}
            if "out:rel2:" in key:
                return {"target"}
            return set()
        redis_mock.smembers = mock_smembers
        result = await kg.query_2hop("start", "rel1", "rel2")
        assert result == ["target"]

    @pytest.mark.asyncio
    async def test_no_redis_returns_empty(self):
        with patch("assistant.knowledge_graph.yaml_config", {}):
            kg = KnowledgeGraph()
        assert await kg.get_related("x", "y") == []
        assert await kg.get_neighbors("x") == []
        assert await kg.query_2hop("x", "y", "z") == []
        assert await kg.query_context("x") == []


# ============================================================
# Pruning
# ============================================================

class TestPruning:

    @pytest.mark.asyncio
    async def test_prune_weak_edges(self, kg, redis_mock):
        weak = json.dumps({"weight": 0.05, "relation": "prefers"})
        # hgetall wird fuer 4 Relationen aufgerufen — nur bei "prefers" Daten liefern
        call_count = 0
        async def mock_hgetall(key):
            nonlocal call_count
            call_count += 1
            if "prefers" in key:
                return {"person:max>device:licht": weak}
            return {}
        redis_mock.hgetall = mock_hgetall
        removed = await kg.prune_weak_edges(min_weight=0.1)
        assert removed == 1

    @pytest.mark.asyncio
    async def test_prune_keeps_strong(self, kg, redis_mock):
        strong = json.dumps({"weight": 0.9, "relation": "prefers"})
        async def mock_hgetall(key):
            if "prefers" in key:
                return {"person:max>device:licht": strong}
            return {}
        redis_mock.hgetall = mock_hgetall
        removed = await kg.prune_weak_edges(min_weight=0.1)
        assert removed == 0

    @pytest.mark.asyncio
    async def test_prune_no_redis(self):
        with patch("assistant.knowledge_graph.yaml_config", {}):
            kg = KnowledgeGraph()
        assert await kg.prune_weak_edges() == 0


# ============================================================
# Stats
# ============================================================

class TestStats:

    @pytest.mark.asyncio
    async def test_stats_with_redis(self, kg, redis_mock):
        redis_mock.scard = AsyncMock(return_value=10)
        stats = await kg.get_stats()
        assert stats["enabled"] is True
        assert stats["connected"] is True
        assert stats["nodes"] == 10

    @pytest.mark.asyncio
    async def test_stats_no_redis(self):
        with patch("assistant.knowledge_graph.yaml_config", {}):
            kg = KnowledgeGraph()
        stats = await kg.get_stats()
        assert stats["connected"] is False


# ============================================================
# Query Context
# ============================================================

class TestQueryContext:
    """Tests fuer query_context() — Multi-Attribut-Kontextabfrage."""

    @pytest.mark.asyncio
    async def test_query_context_basic(self, kg, redis_mock):
        """Grundlegende query_context liefert Praeferenzen und Geraete-Nutzung."""
        async def mock_smembers(key):
            if "out:prefers:person:max" in key:
                return {"pref:warm"}
            if "out:uses_often:person:max" in key:
                return {"device:licht"}
            return set()

        redis_mock.smembers = mock_smembers
        redis_mock.hget = AsyncMock(return_value=json.dumps({
            "weight": 0.8, "relation": "prefers",
        }))

        results = await kg.query_context("max")
        assert len(results) >= 2
        types = {r["type"] for r in results}
        assert "preference" in types
        assert "device_usage" in types

    @pytest.mark.asyncio
    async def test_query_context_room_filter(self, kg, redis_mock):
        """Ergebnisse mit anderem Raum werden herausgefiltert."""
        async def mock_smembers(key):
            if "out:prefers:person:max" in key:
                return {"pref:warm"}
            return set()

        redis_mock.smembers = mock_smembers
        redis_mock.hget = AsyncMock(return_value=json.dumps({
            "weight": 0.8, "relation": "prefers", "room": "kueche",
        }))

        results = await kg.query_context("max", room="wohnzimmer")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_query_context_time_filter(self, kg, redis_mock):
        """Ergebnisse mit anderem time_slot werden herausgefiltert."""
        async def mock_smembers(key):
            if "out:prefers:person:max" in key:
                return {"pref:warm"}
            return set()

        redis_mock.smembers = mock_smembers
        redis_mock.hget = AsyncMock(return_value=json.dumps({
            "weight": 0.8, "relation": "prefers", "time_slot": "morning",
        }))

        results = await kg.query_context("max", time_slot="evening")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_query_context_no_redis(self):
        """Ohne Redis liefert query_context eine leere Liste."""
        with patch("assistant.knowledge_graph.yaml_config", {}):
            kg = KnowledgeGraph()
        results = await kg.query_context("max")
        assert results == []

    @pytest.mark.asyncio
    async def test_query_context_sorted_by_weight(self, kg, redis_mock):
        """Ergebnisse sind nach Gewicht absteigend sortiert."""
        async def mock_smembers(key):
            if "out:prefers:person:max" in key:
                return {"pref:a", "pref:b", "pref:c"}
            return set()

        weights = {"person:max>pref:a": 0.3, "person:max>pref:b": 0.9, "person:max>pref:c": 0.5}

        async def mock_hget(key, edge_key):
            w = weights.get(edge_key, 0.5)
            return json.dumps({"weight": w, "relation": "prefers"})

        redis_mock.smembers = mock_smembers
        redis_mock.hget = mock_hget

        results = await kg.query_context("max")
        result_weights = [r["weight"] for r in results]
        assert result_weights == sorted(result_weights, reverse=True)
        assert result_weights[0] == 0.9

    @pytest.mark.asyncio
    async def test_query_context_max_20_results(self, kg, redis_mock):
        """query_context gibt maximal 20 Ergebnisse zurueck."""
        # 15 Praeferenzen + 10 Geraete = 25, soll auf 20 begrenzt werden
        prefs = {f"pref:{i}" for i in range(15)}
        devices = {f"device:{i}" for i in range(10)}

        async def mock_smembers(key):
            if "out:prefers:person:max" in key:
                return prefs
            if "out:uses_often:person:max" in key:
                return devices
            return set()

        redis_mock.smembers = mock_smembers
        redis_mock.hget = AsyncMock(return_value=json.dumps({
            "weight": 0.5, "relation": "prefers",
        }))

        results = await kg.query_context("max")
        assert len(results) <= 20


# ============================================================
# Knowledge Graph Edge Cases
# ============================================================

class TestKnowledgeGraphEdgeCases:
    """Edge-Case-Tests fuer KnowledgeGraph."""

    @pytest.mark.asyncio
    async def test_add_node_without_properties(self, kg, redis_mock):
        """add_node ohne properties Dict funktioniert fehlerfrei."""
        redis_mock.scard = AsyncMock(return_value=5)
        await kg.add_node("person:anna", "person")
        pipe = redis_mock._pipeline
        pipe.hset.assert_called()
        pipe.execute.assert_called()

    @pytest.mark.asyncio
    async def test_add_edge_with_metadata(self, kg, redis_mock):
        """add_edge mit metadata Dict — Metadaten werden gespeichert."""
        await kg.add_edge(
            "person:max", "prefers", "device:licht",
            weight=0.7, metadata={"room": "wohnzimmer", "time_slot": "evening"},
        )
        pipe = redis_mock._pipeline
        pipe.hset.assert_called()
        # Pruefe dass Metadaten im gespeicherten JSON enthalten sind
        hset_calls = pipe.hset.call_args_list
        found_meta = False
        for call in hset_calls:
            args = call[0] if call[0] else []
            for arg in args:
                if isinstance(arg, str) and "wohnzimmer" in arg:
                    stored = json.loads(arg)
                    assert stored["room"] == "wohnzimmer"
                    assert stored["time_slot"] == "evening"
                    assert abs(stored["weight"] - 0.7) < 0.01
                    found_meta = True
        assert found_meta, "Metadaten nicht in hset-Aufrufen gefunden"

    @pytest.mark.asyncio
    async def test_get_related_no_redis(self):
        """get_related ohne Redis liefert leere Liste."""
        with patch("assistant.knowledge_graph.yaml_config", {}):
            kg = KnowledgeGraph()
        result = await kg.get_related("person:max", "prefers")
        assert result == []

    @pytest.mark.asyncio
    async def test_bytes_handling_in_smembers(self, kg, redis_mock):
        """smembers mit Bytes werden korrekt zu Strings decodiert."""
        redis_mock.smembers = AsyncMock(return_value={b"node1", b"node2"})
        result = await kg.get_related("person:max", "prefers")
        assert len(result) == 2
        assert "node1" in result
        assert "node2" in result
        # Sicherstellen dass keine Bytes zurueckgegeben werden
        for item in result:
            assert isinstance(item, str)
