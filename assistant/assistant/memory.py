"""
Memory Manager - Gedaechtnis des MindHome Assistants.
Working Memory (Redis) + Episodic Memory (ChromaDB) + Semantic Memory (Fakten).
"""

import json
import logging
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import redis.asyncio as redis

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
            logger.info("Redis verbunden")
        except Exception as e:
            logger.warning("Redis nicht verfuegbar: %s", e)
            self.redis = None

        # ChromaDB (Episodic Memory)
        try:
            import chromadb

            _parsed = urlparse(settings.chroma_url)
            self._chroma_client = chromadb.HttpClient(
                host=_parsed.hostname or "localhost",
                port=_parsed.port or 8000,
            )
            self.chroma_collection = self._chroma_client.get_or_create_collection(
                name="mha_conversations",
                metadata={"description": "MindHome Assistant Gespraeche und Erinnerungen"},
            )
            logger.info("ChromaDB verbunden, Collection: mha_conversations")
        except Exception as e:
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
            "timestamp": datetime.now().isoformat(),
        }
        entry_json = json.dumps(entry)

        # Working Memory (letzte 50)
        await self.redis.lpush("mha:conversations", entry_json)
        await self.redis.ltrim("mha:conversations", 0, 49)

        # Tages-Archiv (Phase 7: fuer DailySummarizer)
        today = datetime.now().strftime("%Y-%m-%d")
        archive_key = f"mha:archive:{today}"
        await self.redis.rpush(archive_key, entry_json)
        # Archiv 30 Tage behalten
        await self.redis.expire(archive_key, 30 * 86400)

    async def get_recent_conversations(self, limit: int = 5) -> list[dict]:
        """Holt die letzten Gespraeche aus dem Working Memory."""
        if not self.redis:
            return []

        entries = await self.redis.lrange("mha:conversations", 0, limit - 1)
        result = []
        for e in entries:
            try:
                result.append(json.loads(e))
            except (json.JSONDecodeError, TypeError):
                continue
        return result[::-1]  # Aelteste zuerst

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
            return [json.loads(e) for e in entries]
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
        """
        if not self.chroma_collection:
            return

        try:
            meta = metadata or {}
            meta["timestamp"] = datetime.now().isoformat()
            meta["type"] = "conversation"
            base_id = f"conv_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

            chunks = self._split_conversation(conversation)

            for i, chunk in enumerate(chunks):
                chunk_meta = meta.copy()
                chunk_meta["chunk_index"] = str(i)
                chunk_meta["total_chunks"] = str(len(chunks))
                doc_id = f"{base_id}_{i}" if len(chunks) > 1 else base_id

                self.chroma_collection.add(
                    documents=[chunk],
                    metadatas=[chunk_meta],
                    ids=[doc_id],
                )

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
            results = self.chroma_collection.query(
                query_texts=[query],
                n_results=limit,
            )

            memories = []
            if results and results.get("documents"):
                for i, doc in enumerate(results["documents"][0]):
                    meta = results["metadatas"][0][i] if results.get("metadatas") else {}
                    memories.append({
                        "content": doc,
                        "timestamp": meta.get("timestamp", ""),
                        "relevance": results["distances"][0][i]
                        if results.get("distances")
                        else 0,
                    })
            return memories
        except Exception as e:
            logger.error("Fehler bei Memory-Suche: %s", e)
            return []

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
                "timestamp": datetime.now().isoformat(),
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
            now = datetime.now()

            for topic_key, entry_json in all_topics.items():
                entry = json.loads(entry_json)
                ts = datetime.fromisoformat(entry.get("timestamp", ""))
                age_minutes = (now - ts).total_seconds() / 60

                # Nur Themen die aelter als 10 Min sind (User war weg)
                # und juenger als 24h
                if 10 <= age_minutes <= 1440:
                    entry["age_minutes"] = round(age_minutes)
                    pending.append(entry)

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
            datetime.now().isoformat(),
        )

    # ----- Feedback Scores -----
    # HINWEIS: Feedback-Logik ist seit Phase 5 im FeedbackTracker (feedback.py).
    # Diese Methoden bleiben als Kompatibilitaets-Brücke erhalten.

    async def get_feedback_score(self, event_type: str) -> float:
        """Holt den Feedback-Score fuer einen Event-Typ."""
        if not self.redis:
            return 0.5
        # Phase 5: Neues Key-Schema
        score = await self.redis.get(f"mha:feedback:score:{event_type}")
        if score is None:
            # Fallback: altes Key-Schema
            score = await self.redis.get(f"mha:feedback:{event_type}")
        return float(score) if score else 0.5

    async def update_feedback_score(self, event_type: str, delta: float):
        """Aktualisiert den Feedback-Score (Legacy-Kompatibilitaet)."""
        if not self.redis:
            return
        current = await self.get_feedback_score(event_type)
        new_score = max(0.0, min(1.0, current + delta))
        await self.redis.set(f"mha:feedback:score:{event_type}", str(new_score))

    async def close(self):
        """Schliesst Verbindungen."""
        if self.redis:
            await self.redis.close()
