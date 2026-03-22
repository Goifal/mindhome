"""
RedisKnowledgeGraph — Leichtgewichtiger Wissensgraph ueber Redis.

Speichert Relationen zwischen Personen, Raeumen, Geraeten und Praeferenzen
als Redis-Sets/Hashes. Ermoeglicht 2-Hop-Queries wie:
"Was mag Max abends im Wohnzimmer?"

Keine externe Dependency (kein NetworkX) — nutzt Redis-Primitiven fuer
Graph-Traversal. Nodes und Edges werden ueber Pipelines atomar geschrieben.
"""

import json
import logging
import time
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config

logger = logging.getLogger(__name__)

_PREFIX = "mha:kg"
_MAX_NODES = 1000
_EDGE_TTL = 180 * 86400  # 180 Tage


class KnowledgeGraph:
    """Redis-basierter Wissensgraph fuer Relationen zwischen Entitaeten."""

    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        cfg = yaml_config.get("knowledge_graph", {})
        self.enabled = cfg.get("enabled", True)
        self.max_nodes = cfg.get("max_nodes", _MAX_NODES)

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert den Graphen mit Redis-Verbindung."""
        self.redis = redis_client
        if self.enabled and self.redis:
            logger.info("KnowledgeGraph initialisiert")

    # ------------------------------------------------------------------
    # Node Operations
    # ------------------------------------------------------------------

    async def add_node(
        self, node_id: str, node_type: str, properties: Optional[dict] = None
    ):
        """Fuegt einen Knoten hinzu oder aktualisiert ihn.

        Args:
            node_id: Eindeutige ID (z.B. "person:max", "room:wohnzimmer")
            node_type: Typ (person, room, device, preference, time)
            properties: Optionale Eigenschaften als Dict
        """
        if not self.redis or not self.enabled:
            return

        # Node-Count-Guard
        count = await self.redis.scard(f"{_PREFIX}:all_nodes")
        if count >= self.max_nodes:
            logger.warning(
                "KG: Max Nodes erreicht (%d), ueberspringe %s", count, node_id
            )
            return

        pipe = self.redis.pipeline()
        node_data = json.dumps(
            {
                "type": node_type,
                "updated": time.time(),
                **(properties or {}),
            }
        )
        pipe.hset(f"{_PREFIX}:nodes:{node_type}", node_id, node_data)
        pipe.sadd(f"{_PREFIX}:all_nodes", node_id)
        pipe.sadd(f"{_PREFIX}:type_index:{node_type}", node_id)
        await pipe.execute()

    async def get_node(self, node_id: str, node_type: str = "") -> Optional[dict]:
        """Holt Node-Daten. Wenn node_type unbekannt, alle Typen durchsuchen."""
        if not self.redis:
            return None

        if node_type:
            raw = await self.redis.hget(f"{_PREFIX}:nodes:{node_type}", node_id)
            if raw:
                return json.loads(raw)
            return None

        # Typ unbekannt — alle durchsuchen
        for nt in ("person", "room", "device", "preference", "time"):
            raw = await self.redis.hget(f"{_PREFIX}:nodes:{nt}", node_id)
            if raw:
                return json.loads(raw)
        return None

    # ------------------------------------------------------------------
    # Edge Operations
    # ------------------------------------------------------------------

    async def add_edge(
        self,
        from_id: str,
        relation: str,
        to_id: str,
        weight: float = 1.0,
        metadata: Optional[dict] = None,
    ):
        """Fuegt eine gerichtete Kante hinzu.

        Args:
            from_id: Quell-Knoten ID
            relation: Relationstyp (z.B. "prefers", "uses_often", "located_in")
            to_id: Ziel-Knoten ID
            weight: Gewicht 0.0-1.0 (hoeher = staerker)
            metadata: Optionale Metadaten (time_slot, room, etc.)
        """
        if not self.redis or not self.enabled:
            return

        edge_key = f"{from_id}>{to_id}"
        meta = json.dumps(
            {
                "weight": weight,
                "relation": relation,
                "updated": time.time(),
                **(metadata or {}),
            }
        )

        pipe = self.redis.pipeline()
        # Forward-Index: Alle Kanten eines Typs
        pipe.sadd(f"{_PREFIX}:edges:{relation}", edge_key)
        pipe.expire(f"{_PREFIX}:edges:{relation}", _EDGE_TTL)
        # Edge-Metadaten
        pipe.hset(f"{_PREFIX}:edge_meta:{relation}", edge_key, meta)
        pipe.expire(f"{_PREFIX}:edge_meta:{relation}", _EDGE_TTL)
        # Reverse-Index: Eingehende Kanten zum Ziel
        pipe.sadd(f"{_PREFIX}:in:{relation}:{to_id}", from_id)
        pipe.expire(f"{_PREFIX}:in:{relation}:{to_id}", _EDGE_TTL)
        # Outgoing-Index: Ausgehende Kanten von Quelle
        pipe.sadd(f"{_PREFIX}:out:{relation}:{from_id}", to_id)
        pipe.expire(f"{_PREFIX}:out:{relation}:{from_id}", _EDGE_TTL)
        # Nachbar-Set (unabhaengig von Relation)
        pipe.sadd(f"{_PREFIX}:neighbors:{from_id}", to_id)
        pipe.expire(f"{_PREFIX}:neighbors:{from_id}", _EDGE_TTL)
        await pipe.execute()

    async def increment_edge(
        self, from_id: str, relation: str, to_id: str, delta: float = 0.05
    ):
        """Erhoeht das Gewicht einer bestehenden Kante (z.B. bei Wiederholung)."""
        if not self.redis:
            return

        edge_key = f"{from_id}>{to_id}"
        raw = await self.redis.hget(f"{_PREFIX}:edge_meta:{relation}", edge_key)
        if raw:
            data = json.loads(raw)
            data["weight"] = min(1.0, data.get("weight", 0.5) + delta)
            data["updated"] = time.time()
            await self.redis.hset(
                f"{_PREFIX}:edge_meta:{relation}",
                edge_key,
                json.dumps(data),
            )
        else:
            await self.add_edge(from_id, relation, to_id, weight=0.5 + delta)

    # ------------------------------------------------------------------
    # Query Operations
    # ------------------------------------------------------------------

    async def get_related(
        self, node_id: str, relation: str, direction: str = "out"
    ) -> list[str]:
        """Alle ueber eine Relation verbundenen Knoten.

        Args:
            node_id: Ausgangsknoten
            relation: Relationstyp
            direction: "out" (ausgehend) oder "in" (eingehend)

        Returns:
            Liste von Knoten-IDs
        """
        if not self.redis:
            return []

        if direction == "out":
            key = f"{_PREFIX}:out:{relation}:{node_id}"
        else:
            key = f"{_PREFIX}:in:{relation}:{node_id}"

        members = await self.redis.smembers(key)
        return [m.decode() if isinstance(m, bytes) else m for m in members]

    async def get_neighbors(self, node_id: str) -> list[str]:
        """Alle direkt verbundenen Knoten (unabhaengig von Relation)."""
        if not self.redis:
            return []
        members = await self.redis.smembers(f"{_PREFIX}:neighbors:{node_id}")
        return [m.decode() if isinstance(m, bytes) else m for m in members]

    async def query_2hop(self, start: str, rel1: str, rel2: str) -> list[str]:
        """2-Hop-Query: start -[rel1]-> intermediate -[rel2]-> results.

        Beispiel: query_2hop("person:max", "located_in", "has_preference")
        → Alle Praeferenzen von Max ueber seine Raeume.
        """
        if not self.redis:
            return []

        intermediates = await self.get_related(start, rel1, direction="out")
        results = []
        for mid in intermediates:
            targets = await self.get_related(mid, rel2, direction="out")
            results.extend(targets)
        return list(set(results))  # Deduplizieren

    async def query_context(
        self, person: str, room: str = "", time_slot: str = ""
    ) -> list[dict]:
        """Multi-Attribut-Query: Was ist fuer Person X relevant im Kontext?

        Kombiniert Person-Praeferenzen, Raum-Geraete und Zeitmuster.

        Returns:
            Liste von relevanten Fakten/Relationen als Dicts
        """
        if not self.redis:
            return []

        results = []
        person_id = f"person:{person}"

        # 1. Direkte Praeferenzen der Person
        prefs = await self.get_related(person_id, "prefers")
        for pref in prefs:
            meta_raw = await self.redis.hget(
                f"{_PREFIX}:edge_meta:prefers",
                f"{person_id}>{pref}",
            )
            meta = json.loads(meta_raw) if meta_raw else {}
            # Raum-Filter
            if room and meta.get("room") and meta["room"] != room:
                continue
            # Zeit-Filter
            if time_slot and meta.get("time_slot") and meta["time_slot"] != time_slot:
                continue
            results.append(
                {
                    "type": "preference",
                    "person": person,
                    "target": pref,
                    "weight": meta.get("weight", 0.5),
                    "room": meta.get("room", ""),
                    "time_slot": meta.get("time_slot", ""),
                }
            )

        # 2. Geraete die Person oft nutzt
        devices = await self.get_related(person_id, "uses_often")
        for dev in devices:
            meta_raw = await self.redis.hget(
                f"{_PREFIX}:edge_meta:uses_often",
                f"{person_id}>{dev}",
            )
            meta = json.loads(meta_raw) if meta_raw else {}
            if room and meta.get("room") and meta["room"] != room:
                continue
            results.append(
                {
                    "type": "device_usage",
                    "person": person,
                    "device": dev,
                    "weight": meta.get("weight", 0.5),
                    "room": meta.get("room", ""),
                }
            )

        # Nach Gewicht sortieren
        results.sort(key=lambda x: x.get("weight", 0), reverse=True)
        return results[:20]

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    async def prune_weak_edges(self, min_weight: float = 0.1):
        """Entfernt Kanten mit zu niedrigem Gewicht (Pruning)."""
        if not self.redis:
            return 0

        removed = 0
        for relation in ("prefers", "uses_often", "located_in", "together_with"):
            meta_key = f"{_PREFIX}:edge_meta:{relation}"
            all_edges = await self.redis.hgetall(meta_key)
            for edge_key, meta_raw in all_edges.items():
                meta = json.loads(meta_raw)
                if meta.get("weight", 0) < min_weight:
                    edge_str = (
                        edge_key.decode() if isinstance(edge_key, bytes) else edge_key
                    )
                    pipe = self.redis.pipeline()
                    pipe.hdel(meta_key, edge_str)
                    pipe.srem(f"{_PREFIX}:edges:{relation}", edge_str)
                    # from>to aufsplitten
                    parts = edge_str.split(">", 1)
                    if len(parts) == 2:
                        pipe.srem(f"{_PREFIX}:out:{relation}:{parts[0]}", parts[1])
                        pipe.srem(f"{_PREFIX}:in:{relation}:{parts[1]}", parts[0])
                    await pipe.execute()
                    removed += 1

        if removed:
            logger.info(
                "KG: %d schwache Kanten entfernt (min_weight=%.2f)", removed, min_weight
            )
        return removed

    async def get_stats(self) -> dict:
        """Gibt Graph-Statistiken zurueck."""
        if not self.redis:
            return {"enabled": self.enabled, "connected": False}

        node_count = await self.redis.scard(f"{_PREFIX}:all_nodes")
        edge_counts = {}
        for relation in ("prefers", "uses_often", "located_in", "together_with"):
            count = await self.redis.scard(f"{_PREFIX}:edges:{relation}")
            if count:
                edge_counts[relation] = count

        return {
            "enabled": self.enabled,
            "connected": True,
            "nodes": node_count,
            "edges": edge_counts,
            "max_nodes": self.max_nodes,
        }
