"""
Knowledge Base - RAG-System fuer den MindHome Assistant.
Speichert und durchsucht Wissensdokumente lokal via ChromaDB.

Phase 11.1: Wissensdatenbank
- Dokumente aus /config/knowledge/ Verzeichnis einlesen
- Text in Chunks aufteilen und in ChromaDB speichern
- Semantische Suche fuer RAG-Queries
- Alles lokal, kein Internet noetig
"""

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import settings, yaml_config

logger = logging.getLogger(__name__)

# Unterstuetzte Dateitypen
SUPPORTED_EXTENSIONS = {".txt", ".md", ".yaml", ".yml", ".csv", ".log"}

# Chunk-Einstellungen
DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50


class KnowledgeBase:
    """RAG-Wissensdatenbank ueber ChromaDB."""

    def __init__(self):
        self.chroma_collection = None
        self._chroma_client = None
        self._knowledge_dir: Optional[Path] = None
        self._ingested_hashes: set[str] = set()

    async def initialize(self):
        """Initialisiert die ChromaDB Collection und laedt Dokumente."""
        kb_config = yaml_config.get("knowledge_base", {})
        if not kb_config.get("enabled", True):
            logger.info("Knowledge Base deaktiviert")
            return

        try:
            import chromadb

            self._chroma_client = chromadb.HttpClient(
                host=settings.chroma_url.replace("http://", "").split(":")[0],
                port=int(settings.chroma_url.split(":")[-1]),
            )
            self.chroma_collection = self._chroma_client.get_or_create_collection(
                name="mha_knowledge_base",
                metadata={"description": "MindHome Assistant - Wissensdatenbank (RAG)"},
            )
            logger.info(
                "Knowledge Base initialisiert (ChromaDB: mha_knowledge_base, %d Eintraege)",
                self.chroma_collection.count(),
            )
        except Exception as e:
            logger.warning("Knowledge Base ChromaDB nicht verfuegbar: %s", e)
            self.chroma_collection = None
            return

        # Wissens-Verzeichnis bestimmen
        config_dir = Path(__file__).parent.parent / "config"
        self._knowledge_dir = config_dir / "knowledge"

        # Verzeichnis erstellen falls nicht vorhanden
        self._knowledge_dir.mkdir(exist_ok=True)

        # Bestehende Hashes laden (um Duplikat-Ingestion zu vermeiden)
        self._load_ingested_hashes()

        # Auto-Ingestion beim Start
        if kb_config.get("auto_ingest", True):
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
            logger.debug("Fehler beim Laden bestehender Hashes: %s", e)

    async def ingest_all(self) -> int:
        """Liest alle Dateien im Wissens-Verzeichnis ein und speichert sie."""
        if not self._knowledge_dir or not self.chroma_collection:
            return 0

        total_chunks = 0
        for ext in SUPPORTED_EXTENSIONS:
            for filepath in self._knowledge_dir.glob(f"*{ext}"):
                chunks = await self.ingest_file(filepath)
                total_chunks += chunks

        if total_chunks > 0:
            logger.info("Knowledge Base: %d neue Chunks ingestiert", total_chunks)
        return total_chunks

    async def ingest_file(self, filepath: Path) -> int:
        """Liest eine einzelne Datei ein und speichert die Chunks."""
        if not self.chroma_collection:
            return 0

        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            logger.warning("Fehler beim Lesen von %s: %s", filepath.name, e)
            return 0

        if not content.strip():
            return 0

        kb_config = yaml_config.get("knowledge_base", {})
        chunk_size = kb_config.get("chunk_size", DEFAULT_CHUNK_SIZE)
        chunk_overlap = kb_config.get("chunk_overlap", DEFAULT_CHUNK_OVERLAP)

        chunks = self._split_text(content, chunk_size, chunk_overlap)
        new_chunks = 0

        for i, chunk in enumerate(chunks):
            content_hash = hashlib.md5(chunk.encode()).hexdigest()

            # Duplikat-Check
            if content_hash in self._ingested_hashes:
                continue

            chunk_id = f"kb_{filepath.stem}_{i}_{content_hash[:8]}"
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
                logger.debug("Fehler beim Speichern von Chunk %s: %s", chunk_id, e)

        if new_chunks > 0:
            logger.info(
                "Knowledge Base: %s -> %d/%d Chunks gespeichert",
                filepath.name, new_chunks, len(chunks),
            )
        return new_chunks

    async def ingest_text(self, text: str, source: str = "voice") -> int:
        """Speichert einen Text direkt in die Wissensdatenbank (z.B. via Sprache)."""
        if not self.chroma_collection or not text.strip():
            return 0

        kb_config = yaml_config.get("knowledge_base", {})
        chunk_size = kb_config.get("chunk_size", DEFAULT_CHUNK_SIZE)
        chunk_overlap = kb_config.get("chunk_overlap", DEFAULT_CHUNK_OVERLAP)

        chunks = self._split_text(text, chunk_size, chunk_overlap)
        new_chunks = 0

        for i, chunk in enumerate(chunks):
            content_hash = hashlib.md5(chunk.encode()).hexdigest()
            if content_hash in self._ingested_hashes:
                continue

            chunk_id = f"kb_{source}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{i}"
            metadata = {
                "source_file": source,
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
                logger.debug("Fehler beim Speichern: %s", e)

        return new_chunks

    async def search(self, query: str, limit: int = 3) -> list[dict]:
        """Durchsucht die Wissensdatenbank semantisch."""
        if not self.chroma_collection:
            return []

        kb_config = yaml_config.get("knowledge_base", {})
        max_distance = kb_config.get("max_distance", 1.2)

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
                    # Nur relevante Treffer
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
            logger.error("Fehler bei Knowledge-Suche: %s", e)
            return []

    async def get_stats(self) -> dict:
        """Gibt Statistiken ueber die Wissensdatenbank zurueck."""
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
            logger.error("Fehler bei Knowledge-Stats: %s", e)
            return {"enabled": True, "total_chunks": 0, "sources": []}

    async def clear(self) -> bool:
        """Loescht die gesamte Wissensdatenbank."""
        if not self._chroma_client:
            return False

        try:
            self._chroma_client.delete_collection("mha_knowledge_base")
            self.chroma_collection = self._chroma_client.get_or_create_collection(
                name="mha_knowledge_base",
                metadata={"description": "MindHome Assistant - Wissensdatenbank (RAG)"},
            )
            self._ingested_hashes.clear()
            logger.info("Knowledge Base geloescht")
            return True
        except Exception as e:
            logger.error("Fehler beim Loeschen der Knowledge Base: %s", e)
            return False

    @staticmethod
    def _split_text(
        text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP
    ) -> list[str]:
        """Teilt Text in Chunks auf. Versucht an Absaetzen/Saetzen zu trennen."""
        if len(text) <= chunk_size:
            return [text.strip()] if text.strip() else []

        chunks = []
        # Zuerst an Doppel-Newlines (Absaetzen) splitten
        paragraphs = text.split("\n\n")
        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # Passt der Absatz noch in den aktuellen Chunk?
            if len(current_chunk) + len(para) + 2 <= chunk_size:
                current_chunk = f"{current_chunk}\n\n{para}" if current_chunk else para
            else:
                # Aktuellen Chunk speichern
                if current_chunk:
                    chunks.append(current_chunk.strip())

                # Ist der Absatz selbst zu lang? Dann an Saetzen splitten
                if len(para) > chunk_size:
                    sentences = para.replace(". ", ".\n").split("\n")
                    current_chunk = ""
                    for sent in sentences:
                        sent = sent.strip()
                        if not sent:
                            continue
                        if len(current_chunk) + len(sent) + 1 <= chunk_size:
                            current_chunk = f"{current_chunk} {sent}" if current_chunk else sent
                        else:
                            if current_chunk:
                                chunks.append(current_chunk.strip())
                            current_chunk = sent
                else:
                    current_chunk = para

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        # Overlap hinzufuegen (letzte N Zeichen vom vorherigen Chunk voranstellen)
        if overlap > 0 and len(chunks) > 1:
            overlapped = [chunks[0]]
            for i in range(1, len(chunks)):
                prev_tail = chunks[i - 1][-overlap:]
                # Nur wenn der Overlap nicht schon am Anfang ist
                if not chunks[i].startswith(prev_tail):
                    overlapped.append(f"...{prev_tail} {chunks[i]}")
                else:
                    overlapped.append(chunks[i])
            chunks = overlapped

        return [c for c in chunks if c.strip()]
