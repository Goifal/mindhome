"""
Knowledge Base - RAG-System fuer den MindHome Assistant.
Speichert und durchsucht Wissensdokumente lokal via ChromaDB.

Phase 11.1: Wissensdatenbank
- Dokumente aus /config/knowledge/ Verzeichnis einlesen
- Text in Chunks aufteilen und in ChromaDB speichern
- Semantische Suche fuer RAG-Queries
- Alles lokal, kein Internet noetig
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .config import settings, yaml_config

logger = logging.getLogger(__name__)

# Unterstuetzte Dateitypen
SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".csv"}

# Upload-Limits
KB_UPLOAD_MAX_SIZE = 10 * 1024 * 1024  # 10 MB
KB_UPLOAD_ALLOWED = {".txt", ".md", ".pdf", ".csv"}

# Chunk-Einstellungen (Defaults passend zu settings.yaml)
DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50


class KnowledgeBase:
    """RAG-Wissensdatenbank ueber ChromaDB."""

    def __init__(self):
        self.chroma_collection = None
        self._chroma_client = None
        self._knowledge_dir: Optional[Path] = None
        self._ingested_hashes: set[str] = set()
        self._file_mtimes: dict[str, float] = {}  # filepath -> last mtime
        self._watch_task: Optional[asyncio.Task] = None
        self._watch_running = False

    async def initialize(self):
        """Initialisiert die ChromaDB Collection und laedt Dokumente."""
        kb_config = yaml_config.get("knowledge_base", {})
        if not kb_config.get("enabled", True):
            logger.info("Knowledge Base deaktiviert")
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
                "name": "mha_knowledge_base",
                "metadata": {"description": "MindHome Assistant - Wissensdatenbank (RAG)"},
            }
            if ef:
                col_kwargs["embedding_function"] = ef
            self.chroma_collection = await asyncio.to_thread(
                self._chroma_client.get_or_create_collection, **col_kwargs
            )
            _count = await asyncio.to_thread(self.chroma_collection.count)
            logger.info(
                "Knowledge Base initialisiert (ChromaDB: mha_knowledge_base, %d Eintraege)",
                _count,
            )
        except Exception as e:
            logger.warning("Knowledge Base ChromaDB nicht verfuegbar: %s", e)
            self.chroma_collection = None
            return

        # Wissens-Verzeichnis bestimmen
        config_dir = Path(__file__).parent.parent / "config"
        self._knowledge_dir = config_dir / "knowledge"

        # Verzeichnis erstellen falls nicht vorhanden
        await asyncio.to_thread(self._knowledge_dir.mkdir, exist_ok=True)

        # Bestehende Hashes laden (sync Methode in Thread ausfuehren)
        await asyncio.to_thread(self._load_ingested_hashes)

        # Auto-Ingestion beim Start
        if kb_config.get("auto_ingest", True):
            await self.ingest_all()

        # Aktuelle Datei-Zeitstempel merken fuer Watch
        await asyncio.to_thread(self._snapshot_file_mtimes)

        # Auto-Watch starten: Prueeft regelmaessig auf neue/geaenderte Dateien
        watch_interval = kb_config.get("watch_interval_seconds", 120)
        if watch_interval > 0:
            self._watch_running = True
            self._watch_task = asyncio.create_task(
                self._watch_loop(watch_interval)
            )
            self._watch_task.add_done_callback(
                lambda t: t.exception() if not t.cancelled() else None
            )
            logger.info(
                "Knowledge Base Auto-Watch aktiv (alle %ds)", watch_interval
            )

    async def stop(self):
        """Stoppt den Auto-Watch Task."""
        self._watch_running = False
        if self._watch_task:
            self._watch_task.cancel()
            try:
                await self._watch_task
            except asyncio.CancelledError:
                pass

    def _snapshot_file_mtimes(self):
        """Speichert aktuelle mtime aller Dateien im Wissens-Verzeichnis."""
        if not self._knowledge_dir:
            return
        self._file_mtimes.clear()
        for ext in SUPPORTED_EXTENSIONS:
            for filepath in self._knowledge_dir.rglob(f"*{ext}"):
                try:
                    self._file_mtimes[str(filepath)] = filepath.stat().st_mtime
                except OSError:
                    pass

    async def _watch_loop(self, interval: int):
        """Prueft regelmaessig auf neue oder geaenderte Dateien und ingestiert sie."""
        while self._watch_running:
            try:
                await asyncio.sleep(interval)
                if not self._knowledge_dir or not self.chroma_collection:
                    continue

                new_or_changed = []
                current_files: dict[str, float] = {}

                def _scan_files():
                    _new = []
                    _current: dict[str, float] = {}
                    for ext in SUPPORTED_EXTENSIONS:
                        for fp in self._knowledge_dir.rglob(f"*{ext}"):
                            try:
                                mt = fp.stat().st_mtime
                            except OSError:
                                continue
                            fp_str = str(fp)
                            _current[fp_str] = mt
                            old_mt = self._file_mtimes.get(fp_str)
                            if old_mt is None or mt > old_mt:
                                _new.append(fp)
                    return _new, _current

                new_or_changed, current_files = await asyncio.to_thread(_scan_files)

                if new_or_changed:
                    total = 0
                    for filepath in new_or_changed:
                        # Bei geaenderten Dateien: alte Chunks loeschen, neu einlesen
                        if str(filepath) in self._file_mtimes:
                            await self.delete_source_chunks(filepath.name)
                        chunks = await self.ingest_file(filepath)
                        total += chunks

                    if total > 0:
                        logger.info(
                            "Knowledge Base Auto-Watch: %d Datei(en) -> %d neue Chunks",
                            len(new_or_changed), total,
                        )

                self._file_mtimes = current_files

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Fehler im Knowledge-Watch-Loop: %s", e)
                await asyncio.sleep(30)

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
        """Liest alle Dateien im Wissens-Verzeichnis ein und speichert sie.

        Scannt auch Unterverzeichnisse rekursiv. Max 5 parallel.
        """
        if not self._knowledge_dir or not self.chroma_collection:
            return 0

        def _collect_filepaths():
            result = []
            for ext in SUPPORTED_EXTENSIONS:
                # Rekursiv suchen (** statt nur direkte Dateien)
                result.extend(self._knowledge_dir.rglob(f"*{ext}"))
            return result

        filepaths = await asyncio.to_thread(_collect_filepaths)

        if not filepaths:
            return 0

        sem = asyncio.Semaphore(5)

        async def _ingest_limited(fp: Path) -> int:
            async with sem:
                return await self.ingest_file(fp)

        results = await asyncio.gather(
            *[_ingest_limited(fp) for fp in filepaths],
            return_exceptions=True,
        )
        total_chunks = sum(r for r in results if isinstance(r, int))

        if total_chunks > 0:
            logger.info("Knowledge Base: %d neue Chunks ingestiert", total_chunks)
        return total_chunks

    async def ingest_file(self, filepath: Path) -> int:
        """Liest eine einzelne Datei ein und speichert die Chunks."""
        if not self.chroma_collection:
            return 0

        # Phase 11.1: PDF-Support
        if filepath.suffix.lower() == ".pdf":
            content = await asyncio.to_thread(self._extract_pdf_text, filepath)
        else:
            try:
                content = await asyncio.to_thread(filepath.read_text, encoding="utf-8", errors="ignore")
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
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            }

            try:
                await asyncio.to_thread(
                    self.chroma_collection.add,
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

            chunk_id = f"kb_{source}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{i}"
            metadata = {
                "source_file": source,
                "chunk_index": str(i),
                "total_chunks": str(len(chunks)),
                "content_hash": content_hash,
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            }

            try:
                await asyncio.to_thread(
                    self.chroma_collection.add,
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
        """Durchsucht die Wissensdatenbank semantisch mit Multi-Query und Reranking.

        1. Erzeugt zusaetzliche Query-Varianten (Keyword-Extraktion + Umformulierung)
        2. Fuehrt parallele Suchen durch
        3. Merged und rerankt die Ergebnisse (dedupliziert, bestes Score gewinnt)
        """
        if not self.chroma_collection:
            return []

        kb_config = yaml_config.get("knowledge_base", {})
        max_distance = kb_config.get("max_distance", 1.2)

        try:
            # Multi-Query: Original + Keyword-Variante fuer breitere Abdeckung
            queries = self._expand_query(query)
            # Mehr Kandidaten holen, spaeter auf limit kuerzen
            fetch_per_query = max(limit * 2, 6)

            all_hits: dict[str, dict] = {}  # content_hash -> best hit

            # Parallele Suche ueber alle Query-Varianten
            async def _run_query(q):
                return await asyncio.to_thread(
                    self.chroma_collection.query,
                    query_texts=[q],
                    n_results=fetch_per_query,
                )

            all_results = await asyncio.gather(
                *[_run_query(q) for q in queries],
                return_exceptions=True,
            )

            for results in all_results:
                if isinstance(results, Exception):
                    logger.debug("Query-Fehler: %s", results)
                    continue

                if not results or not results.get("documents") or not results["documents"][0]:
                    continue

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
                    content_hash = meta.get("content_hash", doc[:50])

                    # Keyword-Boost: Wenn Query-Woerter im Dokument vorkommen
                    keyword_bonus = self._keyword_overlap_bonus(query, doc)
                    adjusted_distance = distance * (1.0 - keyword_bonus * 0.3)

                    relevance = round(1.0 - min(adjusted_distance, 1.0), 2)

                    # Bestes Ergebnis pro Chunk behalten
                    if content_hash not in all_hits or all_hits[content_hash]["relevance"] < relevance:
                        all_hits[content_hash] = {
                            "content": doc,
                            "source": meta.get("source_file", "unbekannt"),
                            "relevance": relevance,
                            "distance": round(adjusted_distance, 3),
                        }

            # Nach Relevanz sortieren, Top-N zurueckgeben
            ranked = sorted(all_hits.values(), key=lambda h: h["relevance"], reverse=True)
            return ranked[:limit]
        except Exception as e:
            logger.error("Fehler bei Knowledge-Suche: %s", e)
            return []

    @staticmethod
    def _expand_query(query: str) -> list[str]:
        """Erzeugt Query-Varianten fuer breitere Suche.

        - Original-Query
        - Nur Schluesselwoerter (Stoppwoerter entfernt)
        """
        queries = [query]

        # Stoppwoerter entfernen fuer Keyword-Query
        stopwords = {
            "ich", "du", "er", "sie", "es", "wir", "ihr", "mein", "dein",
            "das", "die", "der", "den", "dem", "des", "ein", "eine", "einen",
            "ist", "sind", "war", "hat", "haben", "wird", "kann", "soll",
            "und", "oder", "aber", "doch", "wenn", "weil", "dass", "ob",
            "nicht", "kein", "keine", "mir", "mich", "dir", "dich",
            "was", "wie", "wo", "wer", "wann", "warum",
            "bitte", "mal", "noch", "auch", "schon", "ja", "nein",
            "in", "im", "am", "an", "auf", "fuer", "von", "zu", "mit",
            "ueber", "unter", "nach", "vor", "bei", "aus", "um",
        }
        words = query.lower().split()
        keywords = [w for w in words if w not in stopwords and len(w) > 2]

        if keywords and len(keywords) < len(words):
            keyword_query = " ".join(keywords)
            if keyword_query != query.lower():
                queries.append(keyword_query)

        return queries

    @staticmethod
    def _keyword_overlap_bonus(query: str, document: str) -> float:
        """Berechnet Bonus basierend auf exaktem Keyword-Match im Dokument.

        Returns 0.0-1.0 (Anteil der Query-Woerter die im Dokument vorkommen).
        """
        query_words = set(query.lower().split())
        # Nur substantielle Woerter
        query_words = {w for w in query_words if len(w) > 2}
        if not query_words:
            return 0.0

        doc_lower = document.lower()
        matches = sum(1 for w in query_words if w in doc_lower)
        return matches / len(query_words)

    async def get_stats(self) -> dict:
        """Gibt Statistiken ueber die Wissensdatenbank zurueck."""
        if not self.chroma_collection:
            return {"enabled": False, "total_chunks": 0, "sources": []}

        try:
            total = await asyncio.to_thread(self.chroma_collection.count)
            existing = await asyncio.to_thread(
                self.chroma_collection.get, include=["metadatas"],
            )
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

    async def get_chunks(self, source: str = "", offset: int = 0, limit: int = 50) -> list[dict]:
        """Gibt alle Chunks zurueck (optional gefiltert nach Quelle)."""
        if not self.chroma_collection:
            return []

        try:
            where = {"source_file": source} if source else None
            results = await asyncio.to_thread(
                self.chroma_collection.get,
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
            # Sortieren nach Quelle + Index
            chunks.sort(key=lambda c: (c["source"], int(c["chunk_index"])))
            return chunks[offset:offset + limit]
        except Exception as e:
            logger.error("Fehler beim Laden der Chunks: %s", e)
            return []

    async def delete_chunks(self, chunk_ids: list[str]) -> int:
        """Loescht einzelne Chunks anhand ihrer IDs."""
        if not self.chroma_collection or not chunk_ids:
            return 0

        try:
            await asyncio.to_thread(self.chroma_collection.delete, ids=chunk_ids)
            logger.info("Knowledge Base: %d Chunks geloescht", len(chunk_ids))
            return len(chunk_ids)
        except Exception as e:
            logger.error("Fehler beim Loeschen von Chunks: %s", e)
            return 0

    async def delete_source_chunks(self, source_file: str) -> int:
        """Loescht alle Chunks einer bestimmten Quelle."""
        if not self.chroma_collection or not source_file:
            return 0

        try:
            results = await asyncio.to_thread(
                self.chroma_collection.get,
                where={"source_file": source_file},
                include=["metadatas"],
            )
            if not results or not results.get("ids"):
                return 0

            chunk_ids = results["ids"]
            # Hashes aus dem Cache entfernen
            for meta in (results.get("metadatas") or []):
                h = meta.get("content_hash", "")
                self._ingested_hashes.discard(h)

            await asyncio.to_thread(self.chroma_collection.delete, ids=chunk_ids)
            logger.info("Knowledge Base: %d Chunks von '%s' geloescht", len(chunk_ids), source_file)
            return len(chunk_ids)
        except Exception as e:
            logger.error("Fehler beim Loeschen von Quelle '%s': %s", source_file, e)
            return 0

    async def reingest_file(self, filename: str) -> int:
        """Loescht alle Chunks einer Datei und liest sie neu ein."""
        if not self._knowledge_dir:
            return 0

        # Datei finden (auch in Unterordnern)
        def _find_file():
            for f in self._knowledge_dir.rglob(filename):
                if f.is_file():
                    return f
            return None

        filepath = await asyncio.to_thread(_find_file)

        if not filepath:
            logger.warning("Knowledge Base: Datei '%s' nicht gefunden", filename)
            return 0

        await self.delete_source_chunks(filename)
        return await self.ingest_file(filepath)

    async def clear(self) -> bool:
        """Loescht die gesamte Wissensdatenbank."""
        if not self._chroma_client:
            return False

        try:
            await asyncio.to_thread(
                self._chroma_client.delete_collection, "mha_knowledge_base"
            )
            from .embeddings import get_embedding_function
            ef = get_embedding_function()
            col_kwargs = {
                "name": "mha_knowledge_base",
                "metadata": {"description": "MindHome Assistant - Wissensdatenbank (RAG)"},
            }
            if ef:
                col_kwargs["embedding_function"] = ef
            self.chroma_collection = await asyncio.to_thread(
                self._chroma_client.get_or_create_collection, **col_kwargs
            )
            self._ingested_hashes.clear()
            logger.info("Knowledge Base geloescht")
            return True
        except Exception as e:
            logger.error("Fehler beim Loeschen der Knowledge Base: %s", e)
            return False

    async def rebuild(self) -> dict:
        """Loescht die Collection und liest alle Dateien mit dem aktuellen Embedding-Modell neu ein."""
        cleared = await self.clear()
        if not cleared:
            return {"success": False, "error": "Collection konnte nicht geloescht werden"}

        new_chunks = await self.ingest_all()
        from .embeddings import DEFAULT_MODEL
        kb_config = yaml_config.get("knowledge_base", {})
        model = kb_config.get("embedding_model", DEFAULT_MODEL)
        return {
            "success": True,
            "new_chunks": new_chunks,
            "embedding_model": model,
        }

    @staticmethod
    def _extract_pdf_text(filepath: Path) -> str:
        """Phase 11.1: Extrahiert Text aus einer PDF-Datei.

        Versucht mehrere Bibliotheken in Reihenfolge:
        1. PyMuPDF (fitz) - schnell, gute Extraktion
        2. pdfplumber - gut fuer Tabellen
        3. PyPDF2 - weit verbreitet, Fallback
        """
        # 1. PyMuPDF (fitz)
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(str(filepath))
            pages = []
            for page in doc:
                pages.append(page.get_text())
            doc.close()
            text = "\n\n".join(pages)
            if text.strip():
                logger.info("PDF gelesen via PyMuPDF: %s (%d Seiten)", filepath.name, len(pages))
                return text
        except ImportError:
            pass
        except Exception as e:
            logger.debug("PyMuPDF Fehler bei %s: %s", filepath.name, e)

        # 2. pdfplumber
        try:
            import pdfplumber
            pages = []
            with pdfplumber.open(filepath) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        pages.append(page_text)
            text = "\n\n".join(pages)
            if text.strip():
                logger.info("PDF gelesen via pdfplumber: %s (%d Seiten)", filepath.name, len(pages))
                return text
        except ImportError:
            pass
        except Exception as e:
            logger.debug("pdfplumber Fehler bei %s: %s", filepath.name, e)

        # 3. PyPDF2
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(str(filepath))
            pages = []
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    pages.append(page_text)
            text = "\n\n".join(pages)
            if text.strip():
                logger.info("PDF gelesen via PyPDF2: %s (%d Seiten)", filepath.name, len(pages))
                return text
        except ImportError:
            pass
        except Exception as e:
            logger.debug("PyPDF2 Fehler bei %s: %s", filepath.name, e)

        logger.warning(
            "PDF %s konnte nicht gelesen werden. "
            "Installiere: pip install PyMuPDF oder pdfplumber oder PyPDF2",
            filepath.name,
        )
        return ""

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
