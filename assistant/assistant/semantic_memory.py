"""
Semantic Memory - Langzeit-Fakten des MindHome Assistants.
Speichert extrahierte Fakten aus Gespraechen (Praeferenzen, Personen, Gewohnheiten).
Nutzt ChromaDB fuer Vektor-Suche und Redis fuer schnellen Zugriff.
"""

import json
import logging
from datetime import datetime
from typing import Optional

import redis.asyncio as redis

from .config import settings

logger = logging.getLogger(__name__)

# Fakten-Kategorien
FACT_CATEGORIES = [
    "preference",   # "Max mag 21 Grad im Buero"
    "person",       # "Lisa ist die Freundin von Max"
    "habit",        # "Max steht um 7 Uhr auf"
    "health",       # "Max hat eine Haselnuss-Allergie"
    "work",         # "Max arbeitet an Projekt Aurora"
    "intent",       # Phase 8: "Eltern kommen naechstes WE"
    "general",      # Sonstige Fakten
]


class SemanticFact:
    """Ein einzelner semantischer Fakt."""

    def __init__(
        self,
        content: str,
        category: str,
        person: str = "unknown",
        confidence: float = 0.8,
        source_conversation: str = "",
        fact_id: Optional[str] = None,
    ):
        self.fact_id = fact_id or f"fact_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        self.content = content
        self.category = category if category in FACT_CATEGORIES else "general"
        self.person = person
        self.confidence = confidence
        self.source_conversation = source_conversation
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at
        self.times_confirmed = 1

    def to_dict(self) -> dict:
        return {
            "fact_id": self.fact_id,
            "content": self.content,
            "category": self.category,
            "person": self.person,
            "confidence": str(self.confidence),
            "source_conversation": self.source_conversation,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "times_confirmed": str(self.times_confirmed),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SemanticFact":
        fact = cls(
            content=data.get("content", ""),
            category=data.get("category", "general"),
            person=data.get("person", "unknown"),
            confidence=float(data.get("confidence", 0.8)),
            source_conversation=data.get("source_conversation", ""),
            fact_id=data.get("fact_id"),
        )
        fact.created_at = data.get("created_at", fact.created_at)
        fact.updated_at = data.get("updated_at", fact.updated_at)
        fact.times_confirmed = int(data.get("times_confirmed", 1))
        return fact


class SemanticMemory:
    """Verwaltet semantische Fakten ueber ChromaDB + Redis."""

    def __init__(self):
        self.redis: Optional[redis.Redis] = None
        self.chroma_collection = None
        self._chroma_client = None

    async def initialize(self, redis_client: Optional[redis.Redis] = None):
        """Initialisiert die Verbindungen."""
        self.redis = redis_client

        try:
            import chromadb

            self._chroma_client = chromadb.HttpClient(
                host=settings.chroma_url.replace("http://", "").split(":")[0],
                port=int(settings.chroma_url.split(":")[-1]),
            )
            self.chroma_collection = self._chroma_client.get_or_create_collection(
                name="mha_semantic_facts",
                metadata={"description": "MindHome Assistant - Extrahierte Fakten"},
            )
            logger.info("Semantic Memory initialisiert (ChromaDB: mha_semantic_facts)")
        except Exception as e:
            logger.warning("Semantic Memory ChromaDB nicht verfuegbar: %s", e)
            self.chroma_collection = None

    async def store_fact(self, fact: SemanticFact) -> bool:
        # Widerspruchserkennung: Pruefen ob ein widersprechender Fakt existiert
        contradiction = await self._check_contradiction(fact)
        if contradiction:
            logger.info(
                "Widerspruch erkannt: '%s' vs '%s' -> Alter Fakt wird aktualisiert",
                fact.content, contradiction.get("content", ""),
            )
            # Alten Fakt loeschen und neuen speichern (neuere Info gewinnt)
            old_id = contradiction.get("fact_id", "")
            if old_id:
                await self.delete_fact(old_id)

        existing = await self.find_similar_fact(fact.content, threshold=0.15)
        if existing:
            return await self._update_existing_fact(existing, fact)

        if self.chroma_collection:
            try:
                self.chroma_collection.add(
                    documents=[fact.content],
                    metadatas=[fact.to_dict()],
                    ids=[fact.fact_id],
                )
            except Exception as e:
                logger.error("Fehler beim Speichern in ChromaDB: %s", e)
                return False

        if self.redis:
            try:
                await self.redis.hset(
                    f"mha:fact:{fact.fact_id}",
                    mapping=fact.to_dict(),
                )
                await self.redis.sadd(
                    f"mha:facts:person:{fact.person}",
                    fact.fact_id,
                )
                await self.redis.sadd(
                    f"mha:facts:category:{fact.category}",
                    fact.fact_id,
                )
                await self.redis.sadd("mha:facts:all", fact.fact_id)
            except Exception as e:
                logger.error("Fehler beim Redis-Index: %s", e)

        logger.info(
            "Neuer Fakt gespeichert: [%s] %s (Person: %s)",
            fact.category, fact.content, fact.person,
        )
        return True

    async def _update_existing_fact(
        self, existing: dict, new_fact: SemanticFact
    ) -> bool:
        fact_id = existing.get("fact_id", "")
        if not fact_id:
            return False

        now = datetime.now().isoformat()
        times_confirmed = int(existing.get("times_confirmed", 1)) + 1
        new_confidence = min(1.0, float(existing.get("confidence", 0.8)) + 0.05)

        if self.chroma_collection:
            try:
                updated_meta = existing.copy()
                updated_meta["updated_at"] = now
                updated_meta["times_confirmed"] = str(times_confirmed)
                updated_meta["confidence"] = str(new_confidence)
                new_content = new_fact.content if len(new_fact.content) > len(existing.get("content", "")) else existing.get("content", "")
                self.chroma_collection.update(
                    ids=[fact_id],
                    documents=[new_content],
                    metadatas=[updated_meta],
                )
            except Exception as e:
                logger.error("Fehler beim Update in ChromaDB: %s", e)

        if self.redis:
            try:
                await self.redis.hset(f"mha:fact:{fact_id}", "updated_at", now)
                await self.redis.hset(
                    f"mha:fact:{fact_id}", "times_confirmed", str(times_confirmed)
                )
                await self.redis.hset(
                    f"mha:fact:{fact_id}", "confidence", str(new_confidence)
                )
            except Exception as e:
                logger.error("Fehler beim Redis-Update: %s", e)

        logger.debug(
            "Fakt bestaetigt: %s (x%d, Confidence: %.2f)",
            fact_id, times_confirmed, new_confidence,
        )
        return True

    async def _check_contradiction(self, new_fact: SemanticFact) -> Optional[dict]:
        """Prueft ob ein neuer Fakt einem bestehenden widerspricht.

        Sucht nach Fakten der gleichen Person + Kategorie die semantisch
        aehnlich aber inhaltlich anders sind (z.B. unterschiedliche Zahlen
        fuer die gleiche Praeferenz).
        """
        if not self.chroma_collection:
            return None

        try:
            # Suche nach aehnlichen Fakten der gleichen Person+Kategorie
            where_filter = {
                "$and": [
                    {"person": new_fact.person},
                    {"category": new_fact.category},
                ]
            }
            results = self.chroma_collection.query(
                query_texts=[new_fact.content],
                n_results=3,
                where=where_filter,
            )

            if not results or not results.get("documents") or not results["documents"][0]:
                return None

            for i, doc in enumerate(results["documents"][0]):
                distance = results["distances"][0][i] if results.get("distances") else 1.0
                meta = results["metadatas"][0][i] if results.get("metadatas") else {}

                # Aehnlich genug um verwandt zu sein (< 0.8) aber
                # verschieden genug um ein Widerspruch zu sein (> 0.15)
                if 0.15 < distance < 0.8:
                    # Pruefen ob es numerische Werte gibt die sich unterscheiden
                    import re
                    old_nums = set(re.findall(r'\d+(?:\.\d+)?', doc))
                    new_nums = set(re.findall(r'\d+(?:\.\d+)?', new_fact.content))
                    if old_nums and new_nums and old_nums != new_nums:
                        fact_id = results["ids"][0][i] if results.get("ids") else ""
                        return {
                            "fact_id": fact_id,
                            "content": doc,
                            "category": meta.get("category", ""),
                            "person": meta.get("person", ""),
                        }

        except Exception as e:
            logger.debug("Widerspruch-Check fehlgeschlagen: %s", e)

        return None

    async def apply_decay(self):
        """Reduziert die Confidence alter Fakten ueber Zeit.

        Fakten die laenger als 30 Tage nicht bestaetigt wurden verlieren
        an Confidence. Explizite Fakten (confidence=1.0) werden langsamer
        abgebaut. Fakten unter 0.2 Confidence werden geloescht.
        """
        if not self.redis:
            return

        try:
            fact_ids = await self.redis.smembers("mha:facts:all")
            now = datetime.now()
            decayed = 0
            deleted = 0

            for fact_id in fact_ids:
                data = await self.redis.hgetall(f"mha:fact:{fact_id}")
                if not data:
                    continue

                updated_at = data.get("updated_at", "")
                if not updated_at:
                    continue

                try:
                    last_update = datetime.fromisoformat(updated_at)
                except (ValueError, TypeError):
                    continue

                days_since = (now - last_update).days
                if days_since < 30:
                    continue

                confidence = float(data.get("confidence", 0.5))
                source = data.get("source_conversation", "")

                # Explizite Fakten ("merk dir") langsamer abbauen
                if source == "explicit":
                    decay_rate = 0.01  # 1% pro 30-Tage-Zyklus
                else:
                    decay_rate = 0.05  # 5% pro 30-Tage-Zyklus

                # Haeufig bestaetigte Fakten langsamer abbauen
                times_confirmed = int(data.get("times_confirmed", 1))
                if times_confirmed >= 5:
                    decay_rate *= 0.5
                elif times_confirmed >= 3:
                    decay_rate *= 0.75

                new_confidence = max(0.0, confidence - decay_rate)

                if new_confidence < 0.2:
                    # Fakt zu unsicher -> loeschen
                    await self.delete_fact(fact_id)
                    deleted += 1
                elif new_confidence != confidence:
                    await self.redis.hset(
                        f"mha:fact:{fact_id}", "confidence", str(round(new_confidence, 3))
                    )
                    if self.chroma_collection:
                        try:
                            self.chroma_collection.update(
                                ids=[fact_id],
                                metadatas=[{**data, "confidence": str(round(new_confidence, 3))}],
                            )
                        except Exception:
                            pass
                    decayed += 1

            if decayed or deleted:
                logger.info(
                    "Fact Decay: %d Fakten reduziert, %d geloescht",
                    decayed, deleted,
                )

        except Exception as e:
            logger.error("Fehler bei Fact Decay: %s", e)

    async def find_similar_fact(
        self, query: str, threshold: float = 0.15
    ) -> Optional[dict]:
        if not self.chroma_collection:
            return None

        try:
            results = self.chroma_collection.query(
                query_texts=[query],
                n_results=1,
            )
            if (
                results
                and results.get("documents")
                and results["documents"][0]
                and results.get("distances")
                and results["distances"][0]
            ):
                distance = results["distances"][0][0]
                if distance <= threshold:
                    meta = results["metadatas"][0][0] if results.get("metadatas") else {}
                    return meta
        except Exception as e:
            logger.error("Fehler bei Duplikat-Suche: %s", e)

        return None

    async def search_facts(
        self, query: str, limit: int = 5, person: Optional[str] = None
    ) -> list[dict]:
        if not self.chroma_collection:
            return []

        try:
            where_filter = None
            if person:
                where_filter = {"person": person}

            results = self.chroma_collection.query(
                query_texts=[query],
                n_results=limit,
                where=where_filter,
            )

            facts = []
            if results and results.get("documents"):
                for i, doc in enumerate(results["documents"][0]):
                    meta = results["metadatas"][0][i] if results.get("metadatas") else {}
                    distance = (
                        results["distances"][0][i] if results.get("distances") else 1.0
                    )
                    facts.append({
                        "content": doc,
                        "category": meta.get("category", "general"),
                        "person": meta.get("person", "unknown"),
                        "confidence": float(meta.get("confidence", 0.5)),
                        "times_confirmed": int(meta.get("times_confirmed", 1)),
                        "relevance": 1.0 - min(distance, 1.0),
                    })
            return facts
        except Exception as e:
            logger.error("Fehler bei Fakten-Suche: %s", e)
            return []

    async def get_facts_by_person(self, person: str) -> list[dict]:
        if not self.redis:
            return await self.search_facts(person, limit=20, person=person)

        try:
            fact_ids = await self.redis.smembers(f"mha:facts:person:{person}")
            facts = []
            for fact_id in fact_ids:
                data = await self.redis.hgetall(f"mha:fact:{fact_id}")
                if data:
                    facts.append({
                        "content": data.get("content", ""),
                        "category": data.get("category", "general"),
                        "person": data.get("person", person),
                        "confidence": float(data.get("confidence", 0.5)),
                        "times_confirmed": int(data.get("times_confirmed", 1)),
                    })
            facts.sort(key=lambda f: f["confidence"], reverse=True)
            return facts
        except Exception as e:
            logger.error("Fehler bei Person-Fakten: %s", e)
            return []

    async def get_facts_by_category(self, category: str) -> list[dict]:
        if not self.redis:
            return await self.search_facts(category, limit=20)

        try:
            fact_ids = await self.redis.smembers(f"mha:facts:category:{category}")
            facts = []
            for fact_id in fact_ids:
                data = await self.redis.hgetall(f"mha:fact:{fact_id}")
                if data:
                    facts.append({
                        "content": data.get("content", ""),
                        "category": category,
                        "person": data.get("person", "unknown"),
                        "confidence": float(data.get("confidence", 0.5)),
                    })
            return facts
        except Exception as e:
            logger.error("Fehler bei Kategorie-Fakten: %s", e)
            return []

    async def get_all_facts(self) -> list[dict]:
        if not self.redis:
            return []

        try:
            fact_ids = await self.redis.smembers("mha:facts:all")
            facts = []
            for fact_id in fact_ids:
                data = await self.redis.hgetall(f"mha:fact:{fact_id}")
                if data:
                    facts.append({
                        "fact_id": data.get("fact_id", fact_id),
                        "content": data.get("content", ""),
                        "category": data.get("category", "general"),
                        "person": data.get("person", "unknown"),
                        "confidence": float(data.get("confidence", 0.5)),
                        "times_confirmed": int(data.get("times_confirmed", 1)),
                        "created_at": data.get("created_at", ""),
                        "updated_at": data.get("updated_at", ""),
                    })
            facts.sort(key=lambda f: f["confidence"], reverse=True)
            return facts
        except Exception as e:
            logger.error("Fehler beim Laden aller Fakten: %s", e)
            return []

    async def delete_fact(self, fact_id: str) -> bool:
        if self.chroma_collection:
            try:
                self.chroma_collection.delete(ids=[fact_id])
            except Exception as e:
                logger.error("Fehler beim Loeschen aus ChromaDB: %s", e)

        if self.redis:
            try:
                data = await self.redis.hgetall(f"mha:fact:{fact_id}")
                if data:
                    person = data.get("person", "unknown")
                    category = data.get("category", "general")
                    await self.redis.srem(f"mha:facts:person:{person}", fact_id)
                    await self.redis.srem(f"mha:facts:category:{category}", fact_id)
                    await self.redis.srem("mha:facts:all", fact_id)
                    await self.redis.delete(f"mha:fact:{fact_id}")
                    logger.info("Fakt geloescht: %s", fact_id)
                    return True
            except Exception as e:
                logger.error("Fehler beim Loeschen aus Redis: %s", e)

        return False

    # ------------------------------------------------------------------
    # Phase 8: Explizites Wissens-Notizbuch
    # ------------------------------------------------------------------

    async def store_explicit(
        self, content: str, category: str = "general", person: str = "unknown"
    ) -> bool:
        """
        Speichert einen explizit genannten Fakt ('Merk dir: ...').
        Confidence ist 1.0 da der User es direkt gesagt hat.
        """
        fact = SemanticFact(
            content=content,
            category=category if category in FACT_CATEGORIES else "general",
            person=person,
            confidence=1.0,
            source_conversation="explicit",
        )
        success = await self.store_fact(fact)
        if success:
            logger.info("Expliziter Fakt gespeichert: %s", content)
        return success

    async def search_by_topic(
        self, topic: str, limit: int = 10
    ) -> list[dict]:
        """
        Sucht alle Fakten zu einem Thema (semantisch).
        Gibt auch niedrig-relevante Treffer zurueck.
        """
        if not self.chroma_collection:
            return []

        try:
            results = self.chroma_collection.query(
                query_texts=[topic],
                n_results=limit,
            )

            facts = []
            if results and results.get("documents"):
                for i, doc in enumerate(results["documents"][0]):
                    meta = results["metadatas"][0][i] if results.get("metadatas") else {}
                    distance = (
                        results["distances"][0][i] if results.get("distances") else 1.0
                    )
                    # Grosszuegigerer Filter als search_facts
                    if distance < 1.5:
                        facts.append({
                            "content": doc,
                            "category": meta.get("category", "general"),
                            "person": meta.get("person", "unknown"),
                            "confidence": float(meta.get("confidence", 0.5)),
                            "times_confirmed": int(meta.get("times_confirmed", 1)),
                            "relevance": 1.0 - min(distance, 1.0),
                            "source": meta.get("source_conversation", ""),
                            "created_at": meta.get("created_at", ""),
                        })
            return facts
        except Exception as e:
            logger.error("Fehler bei Themen-Suche: %s", e)
            return []

    async def forget(self, topic: str) -> int:
        """
        Loescht alle Fakten die zu einem Thema passen.
        Gibt die Anzahl geloeschter Fakten zurueck.
        """
        # Erst suchen, dann loeschen
        matching = await self.search_by_topic(topic, limit=20)
        deleted = 0

        for fact in matching:
            if fact.get("relevance", 0) < 0.4:
                continue  # Nur hoch-relevante loeschen

            # Fakt-ID finden
            fact_id = None
            if self.chroma_collection:
                try:
                    results = self.chroma_collection.query(
                        query_texts=[fact["content"]],
                        n_results=1,
                    )
                    if results and results.get("ids") and results["ids"][0]:
                        fact_id = results["ids"][0][0]
                except Exception:
                    pass

            if fact_id:
                success = await self.delete_fact(fact_id)
                if success:
                    deleted += 1

        if deleted:
            logger.info("'%s' vergessen: %d Fakt(en) geloescht", topic, deleted)
        return deleted

    async def get_correction_history(self, person: str = "") -> list[dict]:
        """Gibt alle durch Korrekturen gelernten Fakten zurueck."""
        if not self.redis:
            return []

        try:
            if person:
                fact_ids = await self.redis.smembers(f"mha:facts:person:{person}")
            else:
                fact_ids = await self.redis.smembers("mha:facts:all")

            corrections = []
            for fact_id in fact_ids:
                data = await self.redis.hgetall(f"mha:fact:{fact_id}")
                if data:
                    source = data.get("source_conversation", "")
                    if source.startswith("correction:"):
                        corrections.append({
                            "content": data.get("content", ""),
                            "category": data.get("category", "general"),
                            "person": data.get("person", "unknown"),
                            "confidence": float(data.get("confidence", 0.5)),
                            "source": source.replace("correction: ", "", 1),
                            "created_at": data.get("created_at", ""),
                        })
            corrections.sort(key=lambda f: f.get("created_at", ""), reverse=True)
            return corrections
        except Exception as e:
            logger.error("Fehler bei Korrektur-History: %s", e)
            return []

    async def get_todays_learnings(self) -> list[dict]:
        """Gibt alle heute gelernten Fakten zurueck."""
        today = datetime.now().strftime("%Y-%m-%d")

        if not self.redis:
            return []

        try:
            fact_ids = await self.redis.smembers("mha:facts:all")
            todays = []
            for fact_id in fact_ids:
                data = await self.redis.hgetall(f"mha:fact:{fact_id}")
                if data:
                    created = data.get("created_at", "")
                    if created.startswith(today):
                        todays.append({
                            "content": data.get("content", ""),
                            "category": data.get("category", "general"),
                            "person": data.get("person", "unknown"),
                            "confidence": float(data.get("confidence", 0.5)),
                            "source": data.get("source_conversation", ""),
                        })
            return todays
        except Exception as e:
            logger.error("Fehler bei heutigen Learnings: %s", e)
            return []

    async def get_stats(self) -> dict:
        if not self.redis:
            return {"total_facts": 0, "categories": {}, "persons": []}

        try:
            total = await self.redis.scard("mha:facts:all")
            categories = {}
            for cat in FACT_CATEGORIES:
                count = await self.redis.scard(f"mha:facts:category:{cat}")
                if count > 0:
                    categories[cat] = count

            persons = set()
            fact_ids = await self.redis.smembers("mha:facts:all")
            for fact_id in fact_ids:
                person = await self.redis.hget(f"mha:fact:{fact_id}", "person")
                if person:
                    persons.add(person)

            return {
                "total_facts": total,
                "categories": categories,
                "persons": list(persons),
            }
        except Exception as e:
            logger.error("Fehler bei Stats: %s", e)
            return {"total_facts": 0, "categories": {}, "persons": []}
