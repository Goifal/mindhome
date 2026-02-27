"""
Recipe Store — Dedizierte Rezept-Datenbank fuer den Kochmodus.

Eigene ChromaDB-Collection (mha_recipes), getrennt von der
allgemeinen Wissensdatenbank. Nur der Kochmodus greift darauf zu.

- Rezept-Dateien aus config/recipes/ einlesen
- Text in Chunks aufteilen und in ChromaDB speichern
- Semantische Suche fuer Rezept-Lookup beim Kochen
"""

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .config import settings, yaml_config
from .knowledge_base import KnowledgeBase

logger = logging.getLogger(__name__)

# Upload-Limits
REC_UPLOAD_MAX_SIZE = 10 * 1024 * 1024  # 10 MB
REC_UPLOAD_ALLOWED = {".txt", ".md", ".pdf", ".csv"}

# Defaults
DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 100


class RecipeStore:
    """Rezept-Datenbank ueber eigene ChromaDB-Collection."""

    def __init__(self):
        self.chroma_collection = None
        self._chroma_client = None
        self._recipes_dir: Optional[Path] = None
        self._ingested_hashes: set[str] = set()

    async def initialize(self):
        """Initialisiert die ChromaDB Collection und laedt Rezepte."""
        rec_config = yaml_config.get("recipe_store", {})
        if not rec_config.get("enabled", True):
            logger.info("Recipe Store deaktiviert")
            return

        try:
            import chromadb

            _parsed = urlparse(settings.chroma_url)
            self._chroma_client = chromadb.HttpClient(
                host=_parsed.hostname or "localhost",
                port=_parsed.port or 8000,
            )
            from .embeddings import get_embedding_function
            ef = get_embedding_function()
            col_kwargs = {
                "name": "mha_recipes",
                "metadata": {"description": "MindHome Assistant - Rezeptdatenbank (Kochmodus)"},
            }
            if ef:
                col_kwargs["embedding_function"] = ef
            self.chroma_collection = self._chroma_client.get_or_create_collection(**col_kwargs)
            logger.info(
                "Recipe Store initialisiert (ChromaDB: mha_recipes, %d Eintraege)",
                self.chroma_collection.count(),
            )
        except Exception as e:
            logger.warning("Recipe Store ChromaDB nicht verfuegbar: %s", e)
            self.chroma_collection = None
            return

        # Rezept-Verzeichnis bestimmen
        config_dir = Path(__file__).parent.parent / "config"
        self._recipes_dir = config_dir / "recipes"
        self._recipes_dir.mkdir(exist_ok=True)

        # Bestehende Hashes laden
        self._load_ingested_hashes()

        # Auto-Ingestion beim Start
        if rec_config.get("auto_ingest", True):
            await self.ingest_all()

    def _load_ingested_hashes(self):
        """Laedt die Hashes bereits ingestierter Chunks."""
        if not self.chroma_collection:
            return
        try:
            existing = self.chroma_collection.get(include=["metadatas"])
            if existing and existing.get("metadatas"):
                for meta in existing["metadatas"]:
                    h = meta.get("content_hash", "")
                    if h:
                        self._ingested_hashes.add(h)
        except Exception as e:
            logger.debug("Fehler beim Laden bestehender Recipe-Hashes: %s", e)

    async def ingest_all(self) -> int:
        """Liest alle Dateien im Rezept-Verzeichnis ein."""
        if not self._recipes_dir or not self.chroma_collection:
            return 0

        total_chunks = 0
        for ext in REC_UPLOAD_ALLOWED:
            for filepath in self._recipes_dir.rglob(f"*{ext}"):
                chunks = await self.ingest_file(filepath)
                total_chunks += chunks

        if total_chunks > 0:
            logger.info("Recipe Store: %d neue Chunks ingestiert", total_chunks)
        return total_chunks

    async def ingest_file(self, filepath: Path) -> int:
        """Liest eine einzelne Rezept-Datei ein und speichert die Chunks."""
        if not self.chroma_collection:
            return 0

        if filepath.suffix.lower() == ".pdf":
            content = KnowledgeBase._extract_pdf_text(filepath)
        else:
            try:
                content = filepath.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                logger.warning("Fehler beim Lesen von %s: %s", filepath.name, e)
                return 0

        if not content.strip():
            return 0

        rec_config = yaml_config.get("recipe_store", {})
        chunk_size = rec_config.get("chunk_size", DEFAULT_CHUNK_SIZE)
        chunk_overlap = rec_config.get("chunk_overlap", DEFAULT_CHUNK_OVERLAP)

        chunks = KnowledgeBase._split_text(content, chunk_size, chunk_overlap)
        new_chunks = 0

        for i, chunk in enumerate(chunks):
            content_hash = hashlib.md5(chunk.encode()).hexdigest()

            if content_hash in self._ingested_hashes:
                continue

            chunk_id = f"rec_{filepath.stem}_{i}_{content_hash[:8]}"
            metadata = {
                "source_file": filepath.name,
                "chunk_index": str(i),
                "total_chunks": str(len(chunks)),
                "content_hash": content_hash,
                "ingested_at": datetime.now().isoformat(),
            }

            try:
                self.chroma_collection.add(
                    documents=[chunk],
                    metadatas=[metadata],
                    ids=[chunk_id],
                )
                self._ingested_hashes.add(content_hash)
                new_chunks += 1
            except Exception as e:
                logger.debug("Fehler beim Speichern von Rezept-Chunk %s: %s", chunk_id, e)

        if new_chunks > 0:
            logger.info(
                "Recipe Store: %s -> %d/%d Chunks gespeichert",
                filepath.name, new_chunks, len(chunks),
            )
        return new_chunks

    async def search(self, query: str, limit: int = 5) -> list[dict]:
        """Durchsucht die Rezeptdatenbank semantisch."""
        if not self.chroma_collection:
            return []

        rec_config = yaml_config.get("recipe_store", {})
        max_distance = rec_config.get("max_distance", 1.0)

        try:
            results = self.chroma_collection.query(
                query_texts=[query],
                n_results=limit,
            )

            hits = []
            if results and results.get("documents") and results["documents"][0]:
                for i, doc in enumerate(results["documents"][0]):
                    distance = (
                        results["distances"][0][i]
                        if results.get("distances") and results["distances"][0]
                        else 2.0
                    )
                    if distance > max_distance:
                        continue

                    meta = (
                        results["metadatas"][0][i]
                        if results.get("metadatas") and results["metadatas"][0]
                        else {}
                    )
                    hits.append({
                        "content": doc,
                        "source": meta.get("source_file", "unbekannt"),
                        "relevance": round(1.0 - min(distance, 1.0), 2),
                        "distance": round(distance, 3),
                    })

            return hits
        except Exception as e:
            logger.error("Fehler bei Rezept-Suche: %s", e)
            return []

    async def get_stats(self) -> dict:
        """Gibt Statistiken ueber die Rezeptdatenbank zurueck."""
        if not self.chroma_collection:
            return {"enabled": False, "total_chunks": 0, "sources": []}

        try:
            total = self.chroma_collection.count()
            existing = self.chroma_collection.get(include=["metadatas"])
            sources = set()
            if existing and existing.get("metadatas"):
                for meta in existing["metadatas"]:
                    src = meta.get("source_file", "")
                    if src:
                        sources.add(src)
            return {
                "enabled": True,
                "total_chunks": total,
                "sources": sorted(sources),
            }
        except Exception as e:
            logger.error("Fehler bei Recipe-Stats: %s", e)
            return {"enabled": True, "total_chunks": 0, "sources": []}

    async def get_chunks(self, source: str = "", offset: int = 0, limit: int = 50) -> list[dict]:
        """Gibt alle Rezept-Chunks zurueck (optional gefiltert nach Quelle)."""
        if not self.chroma_collection:
            return []

        try:
            where = {"source_file": source} if source else None
            results = self.chroma_collection.get(
                include=["documents", "metadatas"],
                where=where,
            )
            chunks = []
            if results and results.get("ids"):
                for i, chunk_id in enumerate(results["ids"]):
                    doc = results["documents"][i] if results.get("documents") else ""
                    meta = results["metadatas"][i] if results.get("metadatas") else {}
                    chunks.append({
                        "id": chunk_id,
                        "content": doc[:200] + ("..." if len(doc) > 200 else ""),
                        "content_full": doc,
                        "source": meta.get("source_file", "unbekannt"),
                        "chunk_index": meta.get("chunk_index", 0),
                    })
            chunks.sort(key=lambda c: (c["source"], c["chunk_index"]))
            return chunks[offset:offset + limit]
        except Exception as e:
            logger.error("Fehler beim Laden der Rezept-Chunks: %s", e)
            return []

    async def delete_chunks(self, chunk_ids: list[str]) -> int:
        """Loescht einzelne Chunks anhand ihrer IDs."""
        if not self.chroma_collection or not chunk_ids:
            return 0

        try:
            self.chroma_collection.delete(ids=chunk_ids)
            logger.info("Recipe Store: %d Chunks geloescht", len(chunk_ids))
            return len(chunk_ids)
        except Exception as e:
            logger.error("Fehler beim Loeschen von Rezept-Chunks: %s", e)
            return 0

    async def delete_source_chunks(self, source_file: str) -> int:
        """Loescht alle Chunks einer bestimmten Quelle."""
        if not self.chroma_collection or not source_file:
            return 0

        try:
            results = self.chroma_collection.get(
                where={"source_file": source_file},
                include=["metadatas"],
            )
            if not results or not results.get("ids"):
                return 0

            chunk_ids = results["ids"]
            for meta in (results.get("metadatas") or []):
                h = meta.get("content_hash", "")
                self._ingested_hashes.discard(h)

            self.chroma_collection.delete(ids=chunk_ids)
            logger.info("Recipe Store: %d Chunks von '%s' geloescht", len(chunk_ids), source_file)
            return len(chunk_ids)
        except Exception as e:
            logger.error("Fehler beim Loeschen von Rezept-Quelle '%s': %s", source_file, e)
            return 0

    async def reingest_file(self, filename: str) -> int:
        """Loescht alle Chunks einer Datei und liest sie neu ein."""
        if not self._recipes_dir:
            return 0

        filepath = None
        for f in self._recipes_dir.rglob(filename):
            if f.is_file():
                filepath = f
                break

        if not filepath or not filepath.exists():
            logger.warning("Recipe Store: Datei '%s' nicht gefunden", filename)
            return 0

        await self.delete_source_chunks(filename)
        return await self.ingest_file(filepath)

    async def clear(self) -> bool:
        """Loescht die gesamte Rezeptdatenbank."""
        if not self._chroma_client:
            return False

        try:
            self._chroma_client.delete_collection("mha_recipes")
            from .embeddings import get_embedding_function
            ef = get_embedding_function()
            col_kwargs = {
                "name": "mha_recipes",
                "metadata": {"description": "MindHome Assistant - Rezeptdatenbank (Kochmodus)"},
            }
            if ef:
                col_kwargs["embedding_function"] = ef
            self.chroma_collection = self._chroma_client.get_or_create_collection(**col_kwargs)
            self._ingested_hashes.clear()
            logger.info("Recipe Store geloescht")
            return True
        except Exception as e:
            logger.error("Fehler beim Loeschen des Recipe Store: %s", e)
            return False

    async def rebuild(self) -> dict:
        """Loescht die Collection und liest alle Rezepte mit dem aktuellen Embedding-Modell neu ein."""
        cleared = await self.clear()
        if not cleared:
            return {"success": False, "error": "Collection konnte nicht geloescht werden"}

        new_chunks = await self.ingest_all()
        from .embeddings import DEFAULT_MODEL
        rec_config = yaml_config.get("recipe_store", {})
        model = rec_config.get("embedding_model", DEFAULT_MODEL)
        return {
            "success": True,
            "new_chunks": new_chunks,
            "embedding_model": model,
        }
