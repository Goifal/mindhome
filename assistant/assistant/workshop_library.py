"""
Workshop Library — RAG fuer technische Fachbuecher und Referenzen.

Eigene ChromaDB-Collection (workshop_library) fuer Werkstatt-Dokumente
wie Datenblaetter, Reparaturanleitungen und Referenzhandbuecher.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Pfade
WORKSHOP_DOCS_DIR = Path("/app/data/workshop/library")
SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md"}


class WorkshopLibrary:
    """Workshop-RAG: Eigene ChromaDB-Collection fuer technische Fachbuecher."""

    COLLECTION_NAME = "workshop_library"
    CHUNK_SIZE = 1500      # Zeichen pro Chunk
    CHUNK_OVERLAP = 200    # Ueberlappung

    def __init__(self):
        self.chroma_client = None
        self.collection = None
        self.embedding_fn = None

    async def initialize(self, chroma_client, embedding_fn) -> None:
        """Initialisiert mit ChromaDB Client + Embedding-Funktion.

        Nutzt die gleiche ChromaDB-Instanz wie knowledge_base.py,
        aber eine EIGENE Collection (workshop_library statt mha_knowledge_base).
        """
        self.chroma_client = chroma_client
        self.embedding_fn = embedding_fn
        WORKSHOP_DOCS_DIR.mkdir(parents=True, exist_ok=True)
        self.collection = self.chroma_client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"description": "Workshop technical reference library"},
        )
        logger.info(
            "WorkshopLibrary: Collection '%s' mit %d Dokumenten",
            self.COLLECTION_NAME,
            self.collection.count(),
        )

    async def ingest_document(self, filepath: str) -> dict:
        """Importiert ein Dokument in die Workshop-Library.

        Unterstuetzt PDF (via PyMuPDF), TXT, MD.
        """
        if not self.collection:
            return {"status": "error", "message": "Library nicht initialisiert"}

        path = Path(filepath)
        if not path.exists():
            return {"status": "error", "message": f"Datei nicht gefunden: {path}"}
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return {
                "status": "error",
                "message": f"Nicht unterstuetzt: {path.suffix}. Erlaubt: {SUPPORTED_EXTENSIONS}",
            }

        # Text extrahieren
        if path.suffix.lower() == ".pdf":
            text = await self._extract_pdf(path)
        else:
            text = path.read_text(encoding="utf-8", errors="replace")

        if not text.strip():
            return {"status": "error", "message": "Dokument ist leer"}

        # Chunken
        chunks = self._chunk_text(text)

        # In ChromaDB speichern
        ids = [f"{path.stem}_{i}" for i in range(len(chunks))]
        metadatas = [
            {"source": path.name, "chunk": i, "total_chunks": len(chunks)}
            for i in range(len(chunks))
        ]

        if self.embedding_fn:
            embeddings = [self.embedding_fn(chunk) for chunk in chunks]
            self.collection.upsert(
                ids=ids, documents=chunks, metadatas=metadatas, embeddings=embeddings,
            )
        else:
            self.collection.upsert(ids=ids, documents=chunks, metadatas=metadatas)

        return {
            "status": "ok",
            "document": path.name,
            "chunks": len(chunks),
            "total_docs": self.collection.count(),
        }

    async def search(self, query: str, n_results: int = 5) -> list:
        """Sucht in der Workshop-Library."""
        if not self.collection or self.collection.count() == 0:
            return []

        if self.embedding_fn:
            query_embedding = self.embedding_fn(query)
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=min(n_results, self.collection.count()),
            )
        else:
            results = self.collection.query(
                query_texts=[query],
                n_results=min(n_results, self.collection.count()),
            )

        formatted = []
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        dists = results.get("distances", [[]])[0]
        for i, doc in enumerate(docs):
            meta = metas[i] if i < len(metas) else {}
            dist = dists[i] if i < len(dists) else 0
            formatted.append({
                "content": doc,
                "source": meta.get("source", ""),
                "chunk": meta.get("chunk", 0),
                "relevance": round(1 - dist, 3),
            })
        return formatted

    async def list_documents(self) -> list:
        """Listet alle Dokumente in der Library."""
        files = []
        if not WORKSHOP_DOCS_DIR.exists():
            return files
        for f in WORKSHOP_DOCS_DIR.iterdir():
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS:
                files.append({
                    "name": f.name,
                    "size_mb": round(f.stat().st_size / 1024 / 1024, 2),
                })
        return files

    async def get_stats(self) -> dict:
        """Gibt Statistiken der Workshop-Library zurueck."""
        count = self.collection.count() if self.collection else 0
        docs = await self.list_documents()
        return {
            "total_chunks": count,
            "total_documents": len(docs),
            "total_size_mb": round(sum(d["size_mb"] for d in docs), 2),
        }

    def _chunk_text(self, text: str) -> list[str]:
        """Teilt Text in ueberlappende Chunks."""
        chunks = []
        start = 0
        while start < len(text):
            end = start + self.CHUNK_SIZE
            chunk = text[start:end]
            if chunk.strip():
                chunks.append(chunk)
            start = end - self.CHUNK_OVERLAP
        return chunks

    async def _extract_pdf(self, path: Path) -> str:
        """Extrahiert Text aus PDF (Pattern: knowledge_base.py)."""
        # 1. PyMuPDF (fitz)
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(str(path))
            pages = []
            for page in doc:
                pages.append(page.get_text())
            doc.close()
            text = "\n\n".join(pages)
            if text.strip():
                logger.info("PDF gelesen via PyMuPDF: %s (%d Seiten)", path.name, len(pages))
                return text
        except ImportError:
            pass
        except Exception as e:
            logger.debug("PyMuPDF Fehler bei %s: %s", path.name, e)

        # 2. pdfplumber
        try:
            import pdfplumber
            pages = []
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        pages.append(page_text)
            text = "\n\n".join(pages)
            if text.strip():
                logger.info("PDF gelesen via pdfplumber: %s (%d Seiten)", path.name, len(pages))
                return text
        except ImportError:
            pass
        except Exception as e:
            logger.debug("pdfplumber Fehler bei %s: %s", path.name, e)

        # 3. PyPDF2
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(str(path))
            pages = []
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    pages.append(page_text)
            text = "\n\n".join(pages)
            if text.strip():
                logger.info("PDF gelesen via PyPDF2: %s (%d Seiten)", path.name, len(pages))
                return text
        except ImportError:
            pass
        except Exception as e:
            logger.debug("PyPDF2 Fehler bei %s: %s", path.name, e)

        logger.warning(
            "PDF %s konnte nicht gelesen werden. "
            "Installiere: pip install PyMuPDF oder pdfplumber oder PyPDF2",
            path.name,
        )
        return ""
