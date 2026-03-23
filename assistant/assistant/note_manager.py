"""
Note Manager - Persistentes Notiz-System mit semantischer Suche.

Speichert Notizen in Redis (persistent) und ChromaDB (semantische Suche).
Bietet schnellen Zugriff auf Notizen per Kategorie, Datum und Freitext.

Features:
- Schnelle Notiz-Erfassung ("Jarvis, merke dir...")
- Kategorisierte Notizen (haushalt, arbeit, ideen, einkauf, gesundheit, etc.)
- Semantische Suche via ChromaDB
- Per-Person Notizen
- Notiz-Archivierung nach 90 Tagen (statt Loeschung)

Redis Keys:
- mha:notes:{note_id}           - Notiz-Daten (Hash)
- mha:notes:all                  - Alle Notiz-IDs (Sorted Set by timestamp)
- mha:notes:category:{cat}       - Notiz-IDs pro Kategorie (Set)
- mha:notes:person:{person}      - Notiz-IDs pro Person (Set)

ChromaDB Collection: jarvis_notes
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config

logger = logging.getLogger(__name__)

_cfg = yaml_config.get("notes", {})
_ENABLED = _cfg.get("enabled", True)
_MAX_NOTES = _cfg.get("max_notes", 500)
_ARCHIVE_AFTER_DAYS = _cfg.get("archive_after_days", 90)
_CHROMA_COLLECTION = "jarvis_notes"

_CATEGORIES = frozenset(
    {
        "haushalt",
        "arbeit",
        "ideen",
        "einkauf",
        "gesundheit",
        "technik",
        "finanzen",
        "familie",
        "rezept",
        "sonstiges",
    }
)


class NoteManager:
    """Persistentes Notiz-System mit semantischer Suche."""

    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        self.chroma_collection = None

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis-Verbindung."""
        self.redis = redis_client
        logger.info("NoteManager initialisiert")

    def set_chroma_collection(self, collection):
        """Setzt die ChromaDB Collection fuer semantische Suche."""
        self.chroma_collection = collection

    # ------------------------------------------------------------------
    # Oeffentliche API
    # ------------------------------------------------------------------

    async def add_note(
        self,
        content: str,
        category: str = "sonstiges",
        person: str = "",
        tags: str = "",
    ) -> dict:
        """Speichert eine neue Notiz."""
        if not content or not content.strip():
            return {"success": False, "message": "Kein Notiztext angegeben."}

        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar."}

        content = content.strip()
        category = category.lower() if category.lower() in _CATEGORIES else "sonstiges"

        note_id = f"note_{uuid.uuid4().hex[:10]}"
        now = datetime.now(timezone.utc)
        timestamp = now.timestamp()

        note = {
            "id": note_id,
            "content": content,
            "category": category,
            "person": person.lower() if person else "",
            "tags": tags,
            "created_at": now.isoformat(),
            "archived": "false",
        }

        # Redis: Notiz speichern
        await self.redis.hset(f"mha:notes:{note_id}", mapping=note)
        await self.redis.zadd("mha:notes:all", {note_id: timestamp})
        await self.redis.sadd(f"mha:notes:category:{category}", note_id)
        if person:
            await self.redis.sadd(f"mha:notes:person:{person.lower()}", note_id)

        # ChromaDB: Fuer semantische Suche indexieren
        if self.chroma_collection:
            try:
                self.chroma_collection.add(
                    ids=[note_id],
                    documents=[content],
                    metadatas=[
                        {
                            "category": category,
                            "person": person.lower() if person else "",
                            "created_at": now.isoformat(),
                        }
                    ],
                )
            except Exception as e:
                logger.warning("ChromaDB Indexierung fehlgeschlagen: %s", e)

        # Limit pruefen
        total = await self.redis.zcard("mha:notes:all")
        if total > _MAX_NOTES:
            await self._archive_oldest()

        return {
            "success": True,
            "message": f"Notiz gespeichert ({category}).",
            "note_id": note_id,
        }

    async def list_notes(
        self,
        category: str = "",
        person: str = "",
        limit: int = 10,
        include_archived: bool = False,
    ) -> dict:
        """Listet Notizen auf."""
        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar."}

        # IDs ermitteln
        if category and person:
            cat_ids = await self.redis.smembers(
                f"mha:notes:category:{category.lower()}"
            )
            person_ids = await self.redis.smembers(f"mha:notes:person:{person.lower()}")
            note_ids = cat_ids & person_ids
        elif category:
            note_ids = await self.redis.smembers(
                f"mha:notes:category:{category.lower()}"
            )
        elif person:
            note_ids = await self.redis.smembers(f"mha:notes:person:{person.lower()}")
        else:
            # Neueste N Notizen (Sorted Set, absteigend)
            raw = await self.redis.zrevrange("mha:notes:all", 0, limit - 1)
            note_ids = set(raw) if raw else set()

        if not note_ids:
            hint = ""
            if category:
                hint += f" in '{category}'"
            if person:
                hint += f" von {person}"
            return {"success": True, "message": f"Keine Notizen{hint} gefunden."}

        # Notizen laden
        notes = await self._fetch_notes(note_ids, include_archived)

        # Sortieren nach Erstellungsdatum (neueste zuerst)
        notes.sort(key=lambda n: n.get("created_at", ""), reverse=True)
        notes = notes[:limit]

        if not notes:
            return {"success": True, "message": "Keine Notizen gefunden."}

        lines = []
        for n in notes:
            date_str = n.get("created_at", "")[:10]
            cat = n.get("category", "")
            content = n.get("content", "")
            # Kuerzen wenn zu lang
            if len(content) > 100:
                content = content[:97] + "..."
            person_hint = f" [{n['person']}]" if n.get("person") else ""
            lines.append(f"- [{date_str}] ({cat}){person_hint} {content}")

        return {
            "success": True,
            "message": f"{len(notes)} Notizen:\n" + "\n".join(lines),
        }

    async def search_notes(self, query: str, limit: int = 5) -> dict:
        """Durchsucht Notizen semantisch via ChromaDB."""
        if not query:
            return {"success": False, "message": "Kein Suchbegriff angegeben."}

        # Erst ChromaDB (semantisch)
        if self.chroma_collection:
            try:
                results = self.chroma_collection.query(
                    query_texts=[query],
                    n_results=limit,
                )
                if results and results.get("ids") and results["ids"][0]:
                    note_ids = set(results["ids"][0])
                    notes = await self._fetch_notes(note_ids)

                    if notes:
                        lines = []
                        for n in notes:
                            date_str = n.get("created_at", "")[:10]
                            content = n.get("content", "")
                            if len(content) > 120:
                                content = content[:117] + "..."
                            lines.append(f"- [{date_str}] {content}")

                        return {
                            "success": True,
                            "message": f"Gefunden ({len(notes)} Treffer):\n"
                            + "\n".join(lines),
                        }
            except Exception as e:
                logger.warning("ChromaDB Suche fehlgeschlagen: %s", e)

        # Fallback: Einfache Redis-Suche (Substring-Match)
        return await self._redis_text_search(query, limit)

    async def delete_note(self, note_id: str) -> dict:
        """Loescht eine Notiz."""
        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar."}

        data = await self.redis.hgetall(f"mha:notes:{note_id}")
        if not data:
            return {"success": False, "message": f"Notiz '{note_id}' nicht gefunden."}

        decoded = _decode_hash(data)
        category = decoded.get("category", "")
        person = decoded.get("person", "")

        # Aus allen Indices entfernen
        await self.redis.delete(f"mha:notes:{note_id}")
        await self.redis.zrem("mha:notes:all", note_id)
        if category:
            await self.redis.srem(f"mha:notes:category:{category}", note_id)
        if person:
            await self.redis.srem(f"mha:notes:person:{person}", note_id)

        # ChromaDB
        if self.chroma_collection:
            try:
                self.chroma_collection.delete(ids=[note_id])
            except Exception as e:
                logger.debug("ChromaDB Delete: %s", e)

        return {"success": True, "message": "Notiz geloescht."}

    async def get_note_categories(self) -> dict:
        """Listet verfuegbare Kategorien mit Anzahl."""
        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar."}

        counts = {}
        for cat in _CATEGORIES:
            count = await self.redis.scard(f"mha:notes:category:{cat}")
            if count > 0:
                counts[cat] = count

        if not counts:
            return {"success": True, "message": "Noch keine Notizen vorhanden."}

        lines = [f"- {cat}: {count} Notizen" for cat, count in sorted(counts.items())]
        return {
            "success": True,
            "message": "Notiz-Kategorien:\n" + "\n".join(lines),
        }

    def get_context_hints(self) -> list[str]:
        """Kontext-Hints fuer Context Builder."""
        return ["NoteManager aktiv: Notizen erstellen, suchen und verwalten"]

    # ------------------------------------------------------------------
    # Interne Helfer
    # ------------------------------------------------------------------

    async def _fetch_notes(
        self, note_ids: set, include_archived: bool = False
    ) -> list[dict]:
        """Laedt Notizen per Pipeline."""
        if not self.redis or not note_ids:
            return []

        pipe = self.redis.pipeline()
        ids_list = []
        for nid in note_ids:
            nid_str = nid if isinstance(nid, str) else nid.decode()
            ids_list.append(nid_str)
            pipe.hgetall(f"mha:notes:{nid_str}")
        results = await pipe.execute()

        notes = []
        for nid, data in zip(ids_list, results):
            if not data:
                continue
            decoded = _decode_hash(data)
            if not include_archived and decoded.get("archived") == "true":
                continue
            notes.append(decoded)

        return notes

    async def _archive_oldest(self):
        """Archiviert die aeltesten Notizen wenn Limit ueberschritten."""
        if not self.redis:
            return

        total = await self.redis.zcard("mha:notes:all")
        if total <= _MAX_NOTES:
            return

        # Aelteste Eintraege archivieren
        excess = total - _MAX_NOTES
        oldest = await self.redis.zrange("mha:notes:all", 0, excess - 1)
        for nid in oldest:
            nid_str = nid if isinstance(nid, str) else nid.decode()
            await self.redis.hset(f"mha:notes:{nid_str}", "archived", "true")

    async def _redis_text_search(self, query: str, limit: int) -> dict:
        """Einfache Textsuche ueber Redis (Fallback wenn kein ChromaDB)."""
        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar."}

        query_lower = query.lower()
        # Neueste 100 Notizen durchsuchen
        recent_ids = await self.redis.zrevrange("mha:notes:all", 0, 99)
        if not recent_ids:
            return {"success": True, "message": "Keine Notizen gefunden."}

        matches = []
        pipe = self.redis.pipeline()
        ids_list = []
        for nid in recent_ids:
            nid_str = nid if isinstance(nid, str) else nid.decode()
            ids_list.append(nid_str)
            pipe.hget(f"mha:notes:{nid_str}", "content")
        contents = await pipe.execute()

        for nid, content in zip(ids_list, contents):
            if content:
                content_str = content if isinstance(content, str) else content.decode()
                if query_lower in content_str.lower():
                    matches.append(nid)
                    if len(matches) >= limit:
                        break

        if not matches:
            return {"success": True, "message": f"Keine Notizen zu '{query}' gefunden."}

        notes = await self._fetch_notes(set(matches))
        lines = []
        for n in notes:
            date_str = n.get("created_at", "")[:10]
            content = n.get("content", "")
            if len(content) > 120:
                content = content[:117] + "..."
            lines.append(f"- [{date_str}] {content}")

        return {
            "success": True,
            "message": f"{len(notes)} Treffer:\n" + "\n".join(lines),
        }

    async def shutdown(self):
        """Cleanup."""
        pass

    async def stop(self):
        """Alias fuer shutdown (Brain-Kompatibilitaet)."""
        await self.shutdown()


def _decode_hash(data: dict) -> dict:
    """Dekodiert Redis-Hash bytes zu strings."""
    decoded = {}
    for k, v in data.items():
        key = k if isinstance(k, str) else k.decode()
        val = v if isinstance(v, str) else v.decode()
        decoded[key] = val
    return decoded
