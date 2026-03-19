"""
Memory Manager - Gedaechtnis des MindHome Assistants.
Working Memory (Redis) + Episodic Memory (ChromaDB) + Semantic Memory (Fakten).
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import redis.asyncio as redis

from .circuit_breaker import redis_breaker, chromadb_breaker
from .config import settings
from .semantic_memory import SemanticMemory

logger = logging.getLogger(__name__)


class MemoryManager:
    """Verwaltet das Kurz-, Langzeit- und semantische Gedaechtnis."""

    def __init__(self):
        self.redis: Optional[redis.Redis] = None
        self.chroma_collection = None
        self._chroma_client = None
        self.semantic = SemanticMemory()

    async def initialize(self):
        """Initialisiert Redis, ChromaDB und Semantic Memory."""
        # Redis (Working Memory)
        try:
            self.redis = redis.from_url(
                settings.redis_url, decode_responses=True
            )
            await self.redis.ping()
            redis_breaker.record_success()
            logger.info("Redis verbunden")
        except Exception as e:
            redis_breaker.record_failure()
            logger.warning("Redis nicht verfuegbar: %s", e)
            if self.redis:
                await self.redis.close()
            self.redis = None

        # ChromaDB (Episodic Memory)
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
                "name": "mha_conversations",
                "metadata": {"description": "MindHome Assistant Gespraeche und Erinnerungen"},
            }
            if ef:
                col_kwargs["embedding_function"] = ef
            self.chroma_collection = self._chroma_client.get_or_create_collection(**col_kwargs)
            chromadb_breaker.record_success()
            logger.info("ChromaDB verbunden, Collection: mha_conversations")
        except Exception as e:
            chromadb_breaker.record_failure()
            logger.warning("ChromaDB nicht verfuegbar: %s", e)
            self.chroma_collection = None

        # Semantic Memory (Fakten-Gedaechtnis)
        await self.semantic.initialize(redis_client=self.redis)
        logger.info("Memory Manager initialisiert (Working + Episodic + Semantic)")

    # ----- Working Memory (Redis) -----

    async def add_conversation(self, role: str, content: str):
        """Speichert eine Nachricht im Working Memory + Tages-Archiv."""
        if not self.redis:
            return

        entry = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        entry_json = json.dumps(entry)

        # P-5: Redis Pipeline — 5 Roundtrips auf 1 reduziert (~80-150ms gespart)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        archive_key = f"mha:archive:{today}"
        try:
            pipe = self.redis.pipeline()
            # Working Memory (letzte 50, mit 7-Tage-TTL als Sicherheitsnetz)
            pipe.lpush("mha:conversations", entry_json)
            pipe.ltrim("mha:conversations", 0, 49)
            pipe.expire("mha:conversations", 7 * 86400)
            # Tages-Archiv (Phase 7: fuer DailySummarizer)
            pipe.rpush(archive_key, entry_json)
            pipe.expire(archive_key, 30 * 86400)
            await pipe.execute()
        except Exception as e:
            logger.warning("add_conversation pipeline failed (lpush+ltrim+archive): %s", e)

    async def get_recent_conversations(self, limit: int = 5) -> list[dict]:
        """Holt die letzten Gespraeche aus dem Working Memory."""
        if not self.redis:
            return []

        entries = await self.redis.lrange("mha:conversations", 0, limit - 1)
        _loads = json.loads  # Lokale Referenz fuer Hot Loop
        result = []
        for e in entries:
            try:
                result.append(_loads(e))
            except (json.JSONDecodeError, TypeError):
                continue
        result.reverse()  # In-place statt [::-1] Kopie
        return result

    async def set_context(self, key: str, value: str, ttl: int = 3600):
        """Speichert einen Kontext-Wert mit TTL."""
        if not self.redis:
            return
        await self.redis.setex(f"mha:context:{key}", ttl, value)

    async def get_context(self, key: str) -> Optional[str]:
        """Holt einen Kontext-Wert."""
        if not self.redis:
            return None
        return await self.redis.get(f"mha:context:{key}")

    async def get_conversations_for_date(self, date: str) -> list[dict]:
        """Holt alle Konversationen eines Tages aus dem Archiv (Phase 7)."""
        if not self.redis:
            return []

        try:
            archive_key = f"mha:archive:{date}"
            entries = await self.redis.lrange(archive_key, 0, -1)
            _loads = json.loads
            result = []
            for e in entries:
                if not e:
                    continue
                try:
                    result.append(_loads(e))
                except (json.JSONDecodeError, TypeError):
                    continue
            return result
        except Exception as e:
            logger.error("Fehler beim Laden des Archivs fuer %s: %s", date, e)
            return []

    # ----- Episodic Memory (ChromaDB) -----

    # Chunk-Einstellungen fuer Episodic Memory
    EPISODE_CHUNK_SIZE = 200
    EPISODE_CHUNK_OVERLAP = 50

    async def store_episode(self, conversation: str, metadata: Optional[dict] = None):
        """Speichert ein Gespraech im Langzeitgedaechtnis.

        Teilt lange Konversationen in kleinere Chunks auf fuer bessere
        semantische Suche. Jeder Chunk erhaelt den vollen Metadaten-Kontext.
        Deduplizierung: Prüft ob aehnliche Episode bereits existiert.
        """
        if not self.chroma_collection:
            logger.warning("Episode nicht gespeichert — ChromaDB nicht verfuegbar")
            return

        try:
            # S4: Deduplizierung — pruefen ob sehr aehnliche Episode existiert
            try:
                preview = conversation[:500]
                results = await asyncio.to_thread(
                    self.chroma_collection.query,
                    query_texts=[preview],
                    n_results=1,
                )
                if (results and results.get("distances")
                        and results["distances"][0]
                        and results["distances"][0][0] < 0.1):
                    logger.debug("Episode-Duplikat erkannt, uebersprungen")
                    return
            except Exception as e:
                logger.debug("Dedup-Check fehlgeschlagen: %s", e)

            meta = dict(metadata) if metadata else {}
            meta["timestamp"] = datetime.now(timezone.utc).isoformat()
            meta["type"] = "conversation"
            base_id = f"conv_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}"

            chunks = self._split_conversation(conversation)

            for i, chunk in enumerate(chunks):
                chunk_meta = meta.copy()
                chunk_meta["chunk_index"] = str(i)
                chunk_meta["total_chunks"] = str(len(chunks))
                doc_id = f"{base_id}_{i}" if len(chunks) > 1 else base_id

                # P3: Timeout auf ChromaDB-Operationen mit 1x Retry
                stored = False
                for _attempt in range(2):
                    try:
                        await asyncio.wait_for(
                            asyncio.to_thread(
                                self.chroma_collection.add,
                                documents=[chunk],
                                metadatas=[chunk_meta],
                                ids=[doc_id],
                            ),
                            timeout=5.0 * (_attempt + 1),
                        )
                        stored = True
                        break
                    except asyncio.TimeoutError:
                        if _attempt == 0:
                            logger.warning("ChromaDB Timeout bei Chunk %s, Retry...", doc_id)
                            await asyncio.sleep(0.5)
                        else:
                            logger.error("ChromaDB Timeout beim Speichern von Chunk %s nach Retry", doc_id)
                if not stored:
                    continue

            logger.debug(
                "Episode gespeichert: %s (%d Chunk(s))", base_id, len(chunks)
            )
        except Exception as e:
            logger.error("Fehler beim Speichern der Episode: %s", e)

    @staticmethod
    def _split_conversation(text: str) -> list[str]:
        """Teilt eine Konversation in semantisch sinnvolle Chunks.

        Strategie:
        1. An Sprecherwechseln (User:/Assistant:) trennen
        2. Zu lange Bloecke an Satzgrenzen splitten
        3. Overlap fuer Kontext-Erhalt
        """
        chunk_size = MemoryManager.EPISODE_CHUNK_SIZE
        overlap = MemoryManager.EPISODE_CHUNK_OVERLAP

        if len(text) <= chunk_size:
            return [text.strip()] if text.strip() else []

        # An Sprecherwechseln splitten
        import re
        segments = re.split(r'(?=(?:User|Assistant|Sir|Jarvis):)', text)
        segments = [s.strip() for s in segments if s.strip()]

        # Segmente in Chunks zusammenfassen
        chunks = []
        current = ""

        for segment in segments:
            if len(current) + len(segment) + 1 <= chunk_size:
                current = f"{current} {segment}".strip() if current else segment
            else:
                if current:
                    chunks.append(current)
                # Segment selbst zu lang? An Saetzen splitten
                if len(segment) > chunk_size:
                    sentences = re.split(r'(?<=[.!?])\s+', segment)
                    current = ""
                    for sent in sentences:
                        if len(current) + len(sent) + 1 <= chunk_size:
                            current = f"{current} {sent}".strip() if current else sent
                        else:
                            if current:
                                chunks.append(current)
                            current = sent
                else:
                    current = segment

        if current.strip():
            chunks.append(current.strip())

        # Overlap hinzufuegen
        if overlap > 0 and len(chunks) > 1:
            overlapped = [chunks[0]]
            for i in range(1, len(chunks)):
                prev_tail = chunks[i - 1][-overlap:]
                if not chunks[i].startswith(prev_tail):
                    overlapped.append(f"...{prev_tail} {chunks[i]}")
                else:
                    overlapped.append(chunks[i])
            chunks = overlapped

        return [c for c in chunks if c.strip()]

    async def search_memories(self, query: str, limit: int = 3) -> list[dict]:
        """Sucht relevante Erinnerungen per Vektor-Suche."""
        if not self.chroma_collection:
            return []

        try:
            results = await asyncio.to_thread(
                self.chroma_collection.query,
                query_texts=[query],
                n_results=limit,
            )

            memories = []
            if results and results.get("documents"):
                docs = results["documents"][0] if results["documents"] else []
                metas = results["metadatas"][0] if results.get("metadatas") and results["metadatas"] else []
                dists = results["distances"][0] if results.get("distances") and results["distances"] else []
                for i, doc in enumerate(docs):
                    meta = metas[i] if i < len(metas) else {}
                    memories.append({
                        "content": doc,
                        "timestamp": meta.get("timestamp", "") if isinstance(meta, dict) else "",
                        "relevance": dists[i] if i < len(dists) else 0,
                    })
            return memories
        except Exception as e:
            logger.error("Fehler bei Memory-Suche: %s", e)
            return []

    async def search_episodes_by_time(
        self, query: str, start_date: str, end_date: str, limit: int = 5,
    ) -> list[dict]:
        """Sucht Episoden in einem bestimmten Zeitraum.

        Args:
            query: Suchtext fuer Vektor-Aehnlichkeit
            start_date: Start-Datum (ISO-Format, z.B. '2025-03-01')
            end_date: End-Datum (ISO-Format, z.B. '2025-03-07')
            limit: Max Ergebnisse
        """
        if not self.chroma_collection:
            return []

        try:
            results = await asyncio.to_thread(
                self.chroma_collection.query,
                query_texts=[query],
                n_results=limit * 3,  # Mehr holen, dann filtern
                where={
                    "$and": [
                        {"timestamp": {"$gte": start_date}},
                        {"timestamp": {"$lte": end_date + "T23:59:59"}},
                    ]
                },
            )

            episodes = []
            if results and results.get("documents"):
                docs = results["documents"][0] if results["documents"] else []
                metas = results["metadatas"][0] if results.get("metadatas") and results["metadatas"] else []
                for i, doc in enumerate(docs):
                    if i >= limit:
                        break
                    meta = metas[i] if i < len(metas) else {}
                    episodes.append({
                        "content": doc,
                        "timestamp": meta.get("timestamp", "") if isinstance(meta, dict) else "",
                        "person": meta.get("person", "") if isinstance(meta, dict) else "",
                    })
            return episodes
        except Exception as e:
            logger.debug("Temporale Episoden-Suche fehlgeschlagen: %s", e)
            # Fallback: Normale Suche ohne Zeitfilter
            return await self.search_memories(query, limit=limit)

    # ----- Phase 8: Konversations-Kontinuitaet -----

    async def mark_conversation_pending(
        self, topic: str, context: str = "", person: str = ""
    ):
        """Markiert ein offenes Gespraechsthema das spaeter fortgesetzt werden soll."""
        if not self.redis:
            return

        try:
            entry = json.dumps({
                "topic": topic,
                "context": context,
                "person": person,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            await self.redis.hset("mha:pending_topics", topic, entry)
            # 24h TTL auf das gesamte Hash
            await self.redis.expire("mha:pending_topics", 86400)
            logger.info("Offenes Thema markiert: %s", topic)
        except Exception as e:
            logger.error("Fehler beim Markieren des Themas: %s", e)

    async def get_pending_conversations(self) -> list[dict]:
        """Holt alle offenen Gespraechsthemen."""
        if not self.redis:
            return []

        try:
            all_topics = await self.redis.hgetall("mha:pending_topics")
            pending = []
            now = datetime.now(timezone.utc)

            for topic_key, entry_json in all_topics.items():
                try:
                    entry = json.loads(entry_json)
                    ts_str = entry.get("timestamp", "")
                    if not ts_str:
                        continue
                    ts = datetime.fromisoformat(ts_str)
                    age_minutes = (now - ts).total_seconds() / 60

                    # Nur Themen die aelter als 10 Min sind (User war weg)
                    # und juenger als 24h
                    if 10 <= age_minutes <= 1440:
                        entry["age_minutes"] = round(age_minutes)
                        pending.append(entry)
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue

            return pending
        except Exception as e:
            logger.error("Fehler beim Laden offener Themen: %s", e)
            return []

    async def resolve_conversation(self, topic: str):
        """Markiert ein offenes Thema als erledigt."""
        if not self.redis:
            return
        try:
            await self.redis.hdel("mha:pending_topics", topic)
            logger.info("Thema erledigt: %s", topic)
        except Exception as e:
            logger.error("Fehler beim Erledigen des Themas: %s", e)

    # ----- Proaktive Meldungen -----

    async def get_last_notification_time(self, event_type: str) -> Optional[str]:
        """Wann wurde dieser Event-Typ zuletzt gemeldet?"""
        if not self.redis:
            return None
        return await self.redis.get(f"mha:notify:{event_type}")

    async def set_last_notification_time(self, event_type: str):
        """Markiert wann dieser Event-Typ gemeldet wurde."""
        if not self.redis:
            return
        await self.redis.setex(
            f"mha:notify:{event_type}",
            3600,  # 1 Stunde TTL
            datetime.now(timezone.utc).isoformat(),
        )

    # ----- Feedback Scores -----
    # HINWEIS: Feedback-Logik ist seit Phase 5 im FeedbackTracker (feedback.py).
    # Diese Methoden bleiben als Kompatibilitaets-Brücke erhalten.

    async def get_feedback_score(self, event_type: str) -> float:
        """Holt den Feedback-Score fuer einen Event-Typ."""
        if not self.redis:
            return 0.5
        # Beide Key-Schemata in einem Roundtrip pruefen (mget statt 2x get)
        new_key = f"mha:feedback:score:{event_type}"
        old_key = f"mha:feedback:{event_type}"
        results = await self.redis.mget(new_key, old_key)
        score = results[0] or results[1]
        return float(score) if score else 0.5

    async def update_feedback_score(self, event_type: str, delta: float):
        """Aktualisiert den Feedback-Score (Legacy-Kompatibilitaet)."""
        if not self.redis:
            return
        current = await self.get_feedback_score(event_type)
        new_score = max(0.0, min(1.0, current + delta))
        # 90 Tage TTL auf Feedback-Scores
        await self.redis.setex(
            f"mha:feedback:score:{event_type}",
            90 * 86400,
            str(new_score),
        )

    # ----- Episoden-Verwaltung (UI) -----

    async def get_all_episodes(self, offset: int = 0, limit: int = 50) -> list[dict]:
        """Gibt alle Episoden aus ChromaDB zurueck (paginiert)."""
        if not self.chroma_collection:
            return []
        try:
            total = await asyncio.to_thread(self.chroma_collection.count)
            if total == 0:
                return []
            # Nur die IDs + Metadaten holen um nach Timestamp zu sortieren,
            # dann nur die benoetigte Seite mit Documents laden.
            meta_result = await asyncio.to_thread(
                self.chroma_collection.get,
                include=["metadatas"],
                limit=total,
            )
            meta_ids = meta_result.get("ids", [])
            meta_list = meta_result.get("metadatas", [])

            # Index-Liste mit Timestamps aufbauen und sortieren
            indexed = []
            for i, doc_id in enumerate(meta_ids):
                meta = meta_list[i] if i < len(meta_list) else {}
                ts = meta.get("timestamp", "") if isinstance(meta, dict) else ""
                indexed.append((ts, doc_id, meta))
            indexed.sort(key=lambda x: x[0], reverse=True)

            # Nur die benoetigte Seite extrahieren
            page = indexed[offset:offset + limit]
            if not page:
                return []

            # Documents nur fuer die Seite nachladen
            page_ids = [item[1] for item in page]
            doc_result = await asyncio.to_thread(
                self.chroma_collection.get,
                ids=page_ids,
                include=["documents"],
            )
            doc_map = {}
            for i, did in enumerate(doc_result.get("ids", [])):
                docs = doc_result.get("documents", [])
                doc_map[did] = docs[i] if i < len(docs) else ""

            episodes = []
            for ts, doc_id, meta in page:
                if not isinstance(meta, dict):
                    meta = {}
                episodes.append({
                    "id": doc_id,
                    "content": doc_map.get(doc_id, ""),
                    "timestamp": meta.get("timestamp", ""),
                    "type": meta.get("type", ""),
                    "chunk_index": meta.get("chunk_index", "0"),
                    "total_chunks": meta.get("total_chunks", "1"),
                })
            return episodes
        except Exception as e:
            logger.error("Fehler beim Laden der Episoden: %s", e)
            return []

    async def delete_episodes(self, episode_ids: list[str]) -> int:
        """Loescht einzelne Episoden aus ChromaDB."""
        if not self.chroma_collection or not episode_ids:
            return 0
        try:
            await asyncio.to_thread(self.chroma_collection.delete, ids=episode_ids)
            deleted_count = len(episode_ids)
            logger.info("Episoden geloescht: %d", deleted_count)
            return deleted_count
        except Exception as e:
            logger.error("Fehler beim Loeschen der Episoden: %s", e)
            return 0

    async def clear_all_memory(self) -> dict:
        """Loescht das gesamte Gedaechtnis (Episoden + Fakten + Working Memory).

        ACHTUNG: Unwiderruflich! Nur ueber PIN-geschuetzten Endpoint aufrufen.
        """
        result = {"episodes_deleted": 0, "facts_deleted": 0, "working_cleared": False}

        # 1. Episoden (ChromaDB Collection neu erstellen)
        if self._chroma_client and self.chroma_collection:
            try:
                self._chroma_client.delete_collection("mha_conversations")
                from .embeddings import get_embedding_function
                ef = get_embedding_function()
                col_kwargs = {
                    "name": "mha_conversations",
                    "metadata": {"description": "MindHome Assistant Gespraeche und Erinnerungen"},
                }
                if ef:
                    col_kwargs["embedding_function"] = ef
                self.chroma_collection = self._chroma_client.get_or_create_collection(**col_kwargs)
                result["episodes_deleted"] = -1  # -1 = alle
                logger.info("Episodisches Gedaechtnis geloescht")
            except Exception as e:
                logger.error("Fehler beim Loeschen der Episoden: %s", e)

        # 2. Fakten (Semantic Memory)
        if self.semantic:
            try:
                deleted = await self.semantic.clear_all()
                result["facts_deleted"] = deleted
            except Exception as e:
                logger.error("Fehler beim Loeschen der Fakten: %s", e)

        # 3. Working Memory (Redis-Konversationen + Archive)
        if self.redis:
            try:
                keys = []
                async for key in self.redis.scan_iter(match="mha:archive:*"):
                    keys.append(key)
                async for key in self.redis.scan_iter(match="mha:context:*"):
                    keys.append(key)
                async for key in self.redis.scan_iter(match="mha:emotional_memory:*"):
                    keys.append(key)
                async for key in self.redis.scan_iter(match="mha:pending_topics"):
                    keys.append(key)
                keys.append("mha:conversations")
                if keys:
                    await self.redis.delete(*keys)
                result["working_cleared"] = True
                logger.info("Working Memory geloescht")
            except Exception as e:
                logger.error("Fehler beim Loeschen des Working Memory: %s", e)

        logger.warning("GESAMTES GEDAECHTNIS ZURUECKGESETZT")
        return result

    async def factory_reset(self, include_uploads: bool = False) -> dict:
        """Vollstaendiger Reset auf Grundeinstellung.

        Loescht ALLEN gelernten State (Redis mha:* + ChromaDB),
        behaelt Config-Dateien (settings.yaml, .env).
        """
        # 1. Bestehenden Memory-Reset ausfuehren (Episoden + Fakten + Working Memory)
        result = await self.clear_all_memory()

        # 2. Alle verbleibenden mha:* Keys aus Redis loeschen
        #    (Korrekturen, Feedback, Learning, Mood, Besucher, Speaker, etc.)
        if self.redis:
            try:
                all_keys = []
                async for key in self.redis.scan_iter(match="mha:*"):
                    all_keys.append(key)
                if all_keys:
                    await self.redis.delete(*all_keys)
                result["redis_keys_deleted"] = len(all_keys)
                logger.info("Redis Factory-Reset: %d Keys geloescht", len(all_keys))
            except Exception as e:
                logger.error("Fehler beim Redis Factory-Reset: %s", e)
                result["redis_keys_deleted"] = 0

        # 3. Uploads loeschen (optional)
        if include_uploads:
            try:
                from .file_handler import UPLOAD_DIR
                import shutil
                if UPLOAD_DIR.exists():
                    count = sum(1 for _ in UPLOAD_DIR.iterdir())
                    shutil.rmtree(UPLOAD_DIR)
                    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                    result["uploads_deleted"] = count
                    logger.info("Uploads geloescht: %d Dateien", count)
            except Exception as e:
                logger.error("Fehler beim Loeschen der Uploads: %s", e)

        logger.warning("FACTORY RESET DURCHGEFUEHRT")
        return result

    async def close(self):
        """Schliesst Verbindungen."""
        if self.redis:
            await self.redis.close()
