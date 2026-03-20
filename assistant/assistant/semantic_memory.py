"""
Semantic Memory - Langzeit-Fakten des MindHome Assistants.
Speichert extrahierte Fakten aus Gespraechen (Praeferenzen, Personen, Gewohnheiten).
Nutzt ChromaDB fuer Vektor-Suche und Redis fuer schnellen Zugriff.
"""

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import redis.asyncio as redis

from .config import settings, yaml_config

logger = logging.getLogger(__name__)

_LOCAL_TZ = ZoneInfo(yaml_config.get("timezone", "Europe/Berlin"))

# Monats-Namen und Lookup fuer Datums-Parsing
_MONTH_NAMES = {
    1: "Januar", 2: "Februar", 3: "März", 4: "April",
    5: "Mai", 6: "Juni", 7: "Juli", 8: "August",
    9: "September", 10: "Oktober", 11: "November", 12: "Dezember",
}
_MONTH_LOOKUP = {
    "januar": 1, "februar": 2, "maerz": 3, "marz": 3, "märz": 3, "april": 4,
    "mai": 5, "juni": 6, "juli": 7, "august": 8,
    "september": 9, "oktober": 10, "november": 11, "dezember": 12,
}

# Fakten-Kategorien
FACT_CATEGORIES = [
    "preference",           # "Max mag 21 Grad im Buero"
    "person",               # "Lisa ist die Freundin von Max"
    "habit",                # "Max steht um 7 Uhr auf"
    "health",               # "Max hat eine Haselnuss-Allergie"
    "work",                 # "Max arbeitet an Projekt Aurora"
    "personal_date",        # Geburtstage, Jahrestage, persoenliche Daten
    "intent",               # Phase 8: "Eltern kommen naechstes WE"
    "conversation_topic",   # Gespraechs-Themen fuer Kontext-Kette
    "general",              # Sonstige Fakten
    "scene_preference",     # "Max mag Filmabend mit 15% statt 10%"
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
        date_meta: Optional[dict] = None,
    ):
        self.fact_id = fact_id or f"fact_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}"
        self.content = content
        self.category = category if category in FACT_CATEGORIES else "general"
        self.person = person
        self.confidence = confidence
        self.source_conversation = source_conversation
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.updated_at = self.created_at
        self.times_confirmed = 1
        # Optionale Metadaten fuer personal_date Fakten
        self.date_meta = date_meta  # {date_type, date_mm_dd, year, label}

    def to_dict(self) -> dict:
        d = {
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
        if self.date_meta:
            d["date_type"] = self.date_meta.get("date_type", "")
            d["date_mm_dd"] = self.date_meta.get("date_mm_dd", "")
            d["date_year"] = self.date_meta.get("year", "")
            d["date_label"] = self.date_meta.get("label", "")
        return d

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
        # date_meta wiederherstellen falls vorhanden
        if data.get("date_type") or data.get("date_mm_dd"):
            fact.date_meta = {
                "date_type": data.get("date_type", ""),
                "date_mm_dd": data.get("date_mm_dd", ""),
                "year": data.get("date_year", ""),
                "label": data.get("date_label", ""),
            }
        return fact


class SemanticMemory:
    """Verwaltet semantische Fakten ueber ChromaDB + Redis."""

    def __init__(self):
        self.redis: Optional[redis.Redis] = None
        self.chroma_collection = None
        self._chroma_client = None
        self._relationship_cache: dict[str, str] = {}
        self._relationship_cache_ts: float = 0.0
        self._relationship_lock = asyncio.Lock()
        self._last_contradiction: Optional[dict] = None

    async def initialize(self, redis_client: Optional[redis.Redis] = None):
        """Initialisiert die Verbindungen."""
        self.redis = redis_client

        try:
            import chromadb

            from urllib.parse import urlparse
            _parsed = urlparse(settings.chroma_url)
            self._chroma_client = chromadb.HttpClient(
                host=_parsed.hostname or "localhost",
                port=_parsed.port or 8000,
            )
            from .embeddings import get_embedding_function
            ef = get_embedding_function()
            col_kwargs = {
                "name": "mha_semantic_facts",
                "metadata": {"description": "MindHome Assistant - Extrahierte Fakten"},
            }
            if ef:
                col_kwargs["embedding_function"] = ef
            self.chroma_collection = self._chroma_client.get_or_create_collection(**col_kwargs)
            logger.info("Semantic Memory initialisiert (ChromaDB: mha_semantic_facts)")
        except Exception as e:
            logger.warning("Semantic Memory ChromaDB nicht verfuegbar: %s", e)
            self.chroma_collection = None


    async def store_fact(self, fact: SemanticFact) -> bool | dict:
        """Speichert einen Fakt. Gibt True/False zurueck oder ein dict mit
        Widerspruchsinformationen wenn ``contradiction_query`` aktiviert ist."""
        # F-007: Lock um den gesamten Read-Write-Zyklus gegen TOCTOU
        self._last_contradiction = None
        lock_key = f"mha:fact_lock:{hashlib.sha256(fact.content.encode()).hexdigest()[:12]}"
        lock_acquired = False
        if self.redis:
            try:
                lock_acquired = await self.redis.set(lock_key, "1", ex=10, nx=True)
                if not lock_acquired:
                    # Retry einmal nach kurzem Warten statt sofort aufgeben
                    await asyncio.sleep(0.2)
                    lock_acquired = await self.redis.set(lock_key, "1", ex=10, nx=True)
                    if not lock_acquired:
                        logger.debug("Fakt-Lock nicht erhalten nach Retry: %s", fact.content[:50])
                        return False
            except Exception as e:
                logger.debug("Redis Lock nicht verfuegbar, fahre ohne Lock fort: %s", e)

        try:
            result = await self._store_fact_inner(fact)
            if result and self._last_contradiction:
                return self._last_contradiction
            return result
        finally:
            if lock_acquired and self.redis:
                try:
                    await self.redis.delete(lock_key)
                except Exception as e:
                    logger.debug("Unhandled: %s", e)

    async def _store_fact_inner(self, fact: SemanticFact) -> bool | dict:
        contradiction_query_enabled = yaml_config.get("semantic_memory", {}).get(
            "contradiction_query", True
        )
        fact_versioning_enabled = yaml_config.get("semantic_memory", {}).get(
            "fact_versioning", False
        )

        # Widerspruchserkennung: Pruefen ob ein widersprechender Fakt existiert
        contradiction = await self._check_contradiction(fact)
        if contradiction:
            logger.info(
                "Widerspruch erkannt: '%s' vs '%s' -> Alter Fakt wird aktualisiert",
                fact.content, contradiction.get("content", ""),
            )
            old_content = contradiction.get("content", "")
            old_id = contradiction.get("fact_id", "")

            if fact_versioning_enabled and old_id:
                await self._store_fact_version(old_id, contradiction)

            # Alten Fakt loeschen und neuen speichern (neuere Info gewinnt)
            if old_id:
                await self.delete_fact(old_id)
                # Relationship-Cache invalidieren damit stale Beziehungsdaten
                # nicht weiter verwendet werden (z.B. Name geaendert)
                if fact.category == "person":
                    try:
                        await self.refresh_relationship_cache()
                    except Exception as e:
                        logger.debug("Relationship-Cache Refresh fehlgeschlagen: %s", e)

            if contradiction_query_enabled:
                self._last_contradiction = {
                    "contradiction_detected": True,
                    "old_value": old_content,
                    "old_fact_id": old_id,
                    "new_value": fact.content,
                    "category": fact.category,
                    "person": fact.person,
                }

        dup_threshold = float(yaml_config.get("memory", {}).get("duplicate_threshold", 0.15))
        existing = await self.find_similar_fact(fact.content, threshold=dup_threshold)
        if existing:
            return await self._update_existing_fact(existing, fact)

        # Wenn BEIDE Backends fehlen → sofort False (DL3-ME2 Fix)
        if not self.chroma_collection and not self.redis:
            logger.error("store_fact: Weder ChromaDB noch Redis verfuegbar — Fakt verworfen")
            return False

        # Redis zuerst schreiben (atomic Pipeline, billiger) — dann ChromaDB.
        # Bei Redis-Fehler: kein ChromaDB-Write → keine verwaisten Eintraege.
        # Bei ChromaDB-Fehler: Fakt ist trotzdem via Redis-Fallback querybar.
        redis_ok = True
        if self.redis:
            try:
                pipe = self.redis.pipeline()
                pipe.hset(
                    f"mha:fact:{fact.fact_id}",
                    mapping=fact.to_dict(),
                )
                pipe.sadd(
                    f"mha:facts:person:{fact.person}",
                    fact.fact_id,
                )
                pipe.sadd(
                    f"mha:facts:category:{fact.category}",
                    fact.fact_id,
                )
                pipe.sadd("mha:facts:all", fact.fact_id)
                await pipe.execute()
            except Exception as e:
                logger.error("Fehler beim Redis-Index: %s — ChromaDB-Write uebersprungen", e)
                redis_ok = False

        chroma_ok = True
        if self.chroma_collection and redis_ok:
            try:
                await asyncio.to_thread(
                    self.chroma_collection.add,
                    documents=[fact.content],
                    metadatas=[fact.to_dict()],
                    ids=[fact.fact_id],
                )
            except Exception as e:
                chroma_ok = False
                logger.error("Fehler beim Speichern in ChromaDB: %s (Fakt via Redis weiterhin verfuegbar)", e)

        # Bei person-Fakten Relationship Cache aktualisieren
        if redis_ok and fact.category == "person":
            try:
                await self.refresh_relationship_cache()
            except Exception as e:
                logger.debug("Relationship-Cache Refresh fehlgeschlagen: %s", e)

        if redis_ok:
            logger.info(
                "Neuer Fakt gespeichert: [%s] (Person: %s)",
                fact.category, fact.person,
            )
        else:
            logger.warning(
                "Fakt nur in ChromaDB gespeichert (Redis-Index fehlt): [%s] (Person: %s)",
                fact.category, fact.person,
            )
            return False
        if not chroma_ok:
            logger.warning(
                "Fakt nur in Redis gespeichert (ChromaDB fehlt, Redis-Fallback-Suche aktiv): "
                "[%s] (Person: %s) — Vektor-Suche nicht verfuegbar, Keyword-Suche als Fallback",
                fact.category, fact.person,
            )
        return True

    async def _update_existing_fact(
        self, existing: dict, new_fact: SemanticFact
    ) -> bool:
        fact_id = existing.get("fact_id", "")
        if not fact_id:
            return False

        old_content = existing.get("content", "")
        if old_content != new_fact.content:
            if yaml_config.get("semantic_memory", {}).get("fact_versioning", False):
                await self._store_fact_version(fact_id, existing)

        now = datetime.now(timezone.utc).isoformat()
        times_confirmed = int(existing.get("times_confirmed", 1)) + 1
        new_confidence = min(1.0, float(existing.get("confidence", 0.8)) + 0.05)

        if self.chroma_collection:
            try:
                updated_meta = existing.copy()
                updated_meta.pop("content", None)
                updated_meta["updated_at"] = now
                updated_meta["times_confirmed"] = str(times_confirmed)
                updated_meta["confidence"] = str(new_confidence)
                # Neuerer Fakt gewinnt immer (aktuellere Information)
                new_content = new_fact.content
                await asyncio.to_thread(
                    self.chroma_collection.update,
                    ids=[fact_id],
                    documents=[new_content],
                    metadatas=[updated_meta],
                )
            except Exception as e:
                logger.error("Fehler beim Update in ChromaDB: %s", e)

        if self.redis:
            try:
                pipe = self.redis.pipeline()
                pipe.hset(f"mha:fact:{fact_id}", "updated_at", now)
                pipe.hset(f"mha:fact:{fact_id}", "times_confirmed", str(times_confirmed))
                pipe.hset(f"mha:fact:{fact_id}", "confidence", str(new_confidence))
                pipe.hset(f"mha:fact:{fact_id}", "content", new_fact.content)
                await pipe.execute()
            except Exception as e:
                logger.error("Fehler beim Redis-Update: %s", e)

        logger.debug(
            "Fakt bestaetigt: %s (x%d, Confidence: %.2f)",
            fact_id, times_confirmed, new_confidence,
        )
        return True

    async def _store_fact_version(self, fact_id: str, old_fact: dict) -> None:
        """Speichert eine vorherige Version eines Fakts in Redis."""
        if not self.redis:
            return
        try:
            version_entry = json.dumps({
                "content": old_fact.get("content", ""),
                "category": old_fact.get("category", ""),
                "person": old_fact.get("person", ""),
                "confidence": old_fact.get("confidence", ""),
                "changed_at": datetime.now(timezone.utc).isoformat(),
            })
            key = f"mha:fact_history:{fact_id}"
            await self.redis.lpush(key, version_entry)
            await self.redis.ltrim(key, 0, 19)
            await self.redis.expire(key, 90 * 86400)
        except Exception as e:
            logger.warning("Fakt-Version konnte nicht gespeichert werden: %s", e)

    async def get_fact_history(self, fact_id: str) -> list:
        """Gibt die Versionshistorie eines Fakts zurueck.

        Liefert eine chronologische Liste frueherer Werte (neueste zuerst),
        sofern ``fact_versioning`` in der Konfiguration aktiviert ist.
        """
        if not self.redis:
            return []
        if not yaml_config.get("semantic_memory", {}).get("fact_versioning", False):
            return []
        try:
            raw = await self.redis.lrange(f"mha:fact_history:{fact_id}", 0, -1)
            return [json.loads(entry) for entry in raw]
        except Exception as e:
            logger.warning("Fakt-Historie konnte nicht geladen werden: %s", e)
            return []

    async def _check_contradiction(self, new_fact: SemanticFact) -> Optional[dict]:
        """Prueft ob ein neuer Fakt einem bestehenden widerspricht.

        Sucht nach Fakten der gleichen Person die semantisch aehnlich aber
        inhaltlich anders sind (z.B. unterschiedliche Zahlen, Gegensaetze).
        Prueft zuerst innerhalb der gleichen Kategorie, dann ueber alle
        Kategorien der Person hinweg (z.B. preference vs habit).
        """
        if not self.chroma_collection:
            return None

        # Zwei Durchlaeufe: 1) gleiche Kategorie, 2) nur gleiche Person
        _filters = [
            {"$and": [{"person": new_fact.person}, {"category": new_fact.category}]},
            {"person": new_fact.person},
        ]

        for where_filter in _filters:
            result = await self._check_contradiction_with_filter(new_fact, where_filter)
            if result:
                return result

        return None

    async def _check_contradiction_with_filter(
        self, new_fact: SemanticFact, where_filter: dict
    ) -> Optional[dict]:
        """Prueft Widersprueche mit einem bestimmten Filter."""
        try:
            results = await asyncio.to_thread(
                self.chroma_collection.query,
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
                    import re
                    is_contradiction = False

                    # 1. Numerische Widersprueche (z.B. "21 Grad" vs "22 Grad")
                    old_nums = set(re.findall(r'\d+(?:\.\d+)?', doc))
                    new_nums = set(re.findall(r'\d+(?:\.\d+)?', new_fact.content))
                    if old_nums and new_nums and old_nums != new_nums:
                        is_contradiction = True

                    # 2. Gegensatz-Paare (z.B. "mag Kaffee" vs "hasst Kaffee")
                    if not is_contradiction:
                        _opposites = [
                            (r'\bmag\b', r'\b(?:hasst|hasse|mag nicht|mag kein)\b'),
                            (r'\bliebt\b', r'\b(?:hasst|hasse)\b'),
                            (r'\bkein(?:e|en|er)?\b', r'\b(?:hat|ist|mag|liebt)\b'),
                            (r'\bnicht\b', r'\b(?:immer|gerne|gern)\b'),
                            (r'\bmorgens\b', r'\babends\b'),
                            (r'\bwarm\b', r'\bkalt\b'),
                            (r'\bkuehl\b', r'\bwarm\b'),
                        ]
                        doc_lower = doc.lower()
                        new_lower = new_fact.content.lower()
                        for pat_a, pat_b in _opposites:
                            a_in_old = bool(re.search(pat_a, doc_lower))
                            b_in_old = bool(re.search(pat_b, doc_lower))
                            a_in_new = bool(re.search(pat_a, new_lower))
                            b_in_new = bool(re.search(pat_b, new_lower))
                            # Gegensatz: ein Pattern im alten, das andere im neuen
                            if (a_in_old and b_in_new) or (b_in_old and a_in_new):
                                is_contradiction = True
                                break

                    if is_contradiction:
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
            now = datetime.now(timezone.utc)
            decayed = 0
            deleted = 0

            # Batch-fetch all fact data via pipeline to avoid N+1
            fact_ids_list = list(fact_ids)
            pipe = self.redis.pipeline()
            for fact_id in fact_ids_list:
                pipe.hgetall(f"mha:fact:{fact_id}")
            all_data = await pipe.execute()

            for fact_id, data in zip(fact_ids_list, all_data):
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

                # Decay-Rate: Langsam genug damit Fakten monatelang nutzbar bleiben.
                # Bei Confidence 0.8 und Rate 0.02 → nach 6 Monaten: ~0.68 → noch sichtbar.
                # Erst nach ~20 Monaten (0.4) wird der Fakt unsichtbar im Kontext.
                # Explizite Fakten ("merk dir") noch langsamer.
                if source == "explicit":
                    decay_rate = 0.005  # 0.5% pro 30-Tage-Zyklus — praktisch permanent
                else:
                    decay_rate = 0.02   # 2% pro 30-Tage-Zyklus — ~20 Monate bis unsichtbar

                # Haeufig bestaetigte Fakten langsamer abbauen
                times_confirmed = int(data.get("times_confirmed", 1))
                if times_confirmed >= 5:
                    decay_rate *= 0.25  # 4x langsamer — praktisch permanent
                elif times_confirmed >= 3:
                    decay_rate *= 0.5   # 2x langsamer

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
                            # Metadata-Keys bereinigen: bytes dekodieren, nur
                            # erlaubte String-Felder an ChromaDB weitergeben
                            clean_meta = {}
                            for k, v in data.items():
                                key = k.decode() if isinstance(k, bytes) else k
                                val = v.decode() if isinstance(v, bytes) else v
                                if isinstance(val, str):
                                    clean_meta[key] = val
                            clean_meta["confidence"] = str(round(new_confidence, 3))
                            await asyncio.to_thread(
                                self.chroma_collection.update,
                                ids=[fact_id],
                                metadatas=[clean_meta],
                            )
                        except Exception as e:
                            logger.debug("ChromaDB update in decay failed: %s", e)
                    decayed += 1

            if decayed or deleted:
                logger.info(
                    "Fact Decay: %d Fakten reduziert, %d geloescht",
                    decayed, deleted,
                )

        except Exception as e:
            logger.error("Fehler bei Fact Decay: %s", e)

    async def verify_consistency(self):
        """Prueft Konsistenz zwischen Redis und ChromaDB.

        Erkennt verwaiste Fakten (in einem System aber nicht im anderen)
        und re-indexiert sie. Wird taeglich nach dem Decay ausgefuehrt.
        """
        if not self.redis or not self.chroma_collection:
            return

        try:
            redis_ids = await self.redis.smembers("mha:facts:all")
            redis_ids_set = {
                (fid if isinstance(fid, str) else fid.decode())
                for fid in redis_ids
            }

            if not redis_ids_set:
                return

            # Stichprobe: Maximal 100 Fakten pruefen (Performance)
            # random.sample statt [:100] — deckt ueber mehrere Runs ALLE Fakten ab
            import random
            _all_ids = list(redis_ids_set)
            check_ids = random.sample(_all_ids, min(100, len(_all_ids)))
            orphaned_redis = 0
            reindexed = 0

            for fact_id in check_ids:
                # Pruefen ob der Fakt in ChromaDB existiert
                try:
                    result = await asyncio.to_thread(
                        self.chroma_collection.get,
                        ids=[fact_id],
                    )
                    if not result or not result.get("ids") or not result["ids"]:
                        # Fakt in Redis aber nicht in ChromaDB → re-indexieren
                        data = await self.redis.hgetall(f"mha:fact:{fact_id}")
                        if data:
                            content = data.get("content", "")
                            if isinstance(content, bytes):
                                content = content.decode()
                            if content:
                                meta = {}
                                for k, v in data.items():
                                    key = k if isinstance(k, str) else k.decode()
                                    val = v if isinstance(v, str) else v.decode()
                                    meta[key] = val
                                try:
                                    await asyncio.to_thread(
                                        self.chroma_collection.add,
                                        documents=[content],
                                        metadatas=[meta],
                                        ids=[fact_id],
                                    )
                                    reindexed += 1
                                except Exception as e:
                                    logger.debug("Re-Index fehlgeschlagen fuer %s: %s", fact_id, e)
                                    orphaned_redis += 1
                        else:
                            # Fakt-ID in Index aber keine Daten → Index bereinigen
                            await self.redis.srem("mha:facts:all", fact_id)
                            orphaned_redis += 1
                except Exception as e:
                    logger.debug("Konsistenz-Check fuer %s uebersprungen: %s", fact_id, e)

            if reindexed or orphaned_redis:
                logger.info(
                    "Konsistenz-Check: %d re-indexiert, %d verwaist bereinigt (von %d geprueft)",
                    reindexed, orphaned_redis, len(check_ids),
                )

        except Exception as e:
            logger.error("Konsistenz-Check fehlgeschlagen: %s", e)

    async def find_similar_fact(
        self, query: str, threshold: float = 0.15
    ) -> Optional[dict]:
        if not self.chroma_collection:
            return None

        try:
            results = await asyncio.to_thread(
                self.chroma_collection.query,
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
                    meta = dict(results["metadatas"][0][0]) if results.get("metadatas") else {}
                    # fact_id und content aus ChromaDB-Ergebnis sicherstellen
                    if not meta.get("fact_id") and results.get("ids") and results["ids"][0]:
                        meta["fact_id"] = results["ids"][0][0]
                    if not meta.get("content") and results["documents"][0]:
                        meta["content"] = results["documents"][0][0]
                    return meta
        except Exception as e:
            logger.error("Fehler bei Duplikat-Suche: %s", e)

        return None

    async def search_facts(
        self, query: str, limit: int = 5, person: Optional[str] = None
    ) -> list[dict]:
        # ChromaDB-Suche versuchen, bei Fehler Redis-Fallback
        if self.chroma_collection:
            try:
                return await self._search_facts_chromadb(query, limit, person)
            except Exception as e:
                logger.warning("ChromaDB search_facts fehlgeschlagen, versuche Redis-Fallback: %s", e)

        # Fallback: Alle Fakten aus Redis laden und nach Query-Keywords filtern
        if self.redis:
            return await self._search_facts_redis_fallback(query, limit, person)

        return []

    async def _search_facts_chromadb(
        self, query: str, limit: int, person: Optional[str] = None
    ) -> list[dict]:
        """Semantische Suche via ChromaDB Vektor-Aehnlichkeit."""
        where_filter = None
        if person:
            where_filter = {"person": person}

        results = await asyncio.to_thread(
            self.chroma_collection.query,
            query_texts=[query],
            n_results=limit,
            where=where_filter,
        )

        min_confidence = float(yaml_config.get("memory", {}).get(
            "min_confidence_for_context", 0.4
        ))
        now = datetime.now(timezone.utc)
        facts = []
        if results and results.get("documents"):
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i] if results.get("metadatas") else {}
                distance = (
                    results["distances"][0][i] if results.get("distances") else 1.0
                )
                confidence = float(meta.get("confidence", 0.5))
                # Fakten mit zu niedriger Confidence herausfiltern
                if confidence < min_confidence:
                    continue
                base_relevance = 1.0 - min(distance, 1.0)
                # Aktualitaets-Boost: Kuerzlich bestaetigte Fakten bevorzugen
                recency_boost = 0.0
                updated_at = meta.get("updated_at", "")
                if updated_at:
                    try:
                        days_old = (now - datetime.fromisoformat(updated_at)).days
                        # Staerkerer Recency-Boost: 25% fuer aktuelle Fakten,
                        # linear abfallend ueber 60 Tage
                        if days_old < 60:
                            recency_boost = 0.25 * max(0.0, 1.0 - days_old / 60.0)
                    except (ValueError, TypeError):
                        pass
                facts.append({
                    "content": doc,
                    "category": meta.get("category", "general"),
                    "person": meta.get("person", "unknown"),
                    "confidence": confidence,
                    "times_confirmed": int(meta.get("times_confirmed", 1)),
                    "relevance": min(1.0, base_relevance + recency_boost),
                })
        # Nach Relevanz sortieren damit aktuellere Fakten oben stehen
        facts.sort(key=lambda f: f["relevance"], reverse=True)
        return facts

    # Stoppwoerter fuer Redis-Fallback (haeufige dt. Woerter ohne Bedeutung)
    _STOPWORDS = frozenset({
        "der", "die", "das", "den", "dem", "des", "ein", "eine", "einer",
        "einem", "einen", "und", "oder", "aber", "ist", "sind", "war",
        "hat", "haben", "wird", "kann", "ich", "du", "er", "sie", "es",
        "wir", "ihr", "was", "wie", "wo", "wer", "von", "zu", "in",
        "mit", "auf", "an", "fuer", "für", "ueber", "über", "bei",
        "nach", "vor", "aus", "um", "nicht", "auch", "noch", "schon",
        "sehr", "ja", "nein", "mal", "so", "da", "dann", "wenn",
    })

    async def _search_facts_redis_fallback(
        self, query: str, limit: int, person: Optional[str] = None
    ) -> list[dict]:
        """Keyword-basierte Suche ueber Redis wenn ChromaDB nicht verfuegbar.

        Nutzt Stoppwort-Filterung, Teilwort-Matching und Confidence-Gewichtung
        fuer bessere Ergebnisse als einfaches Keyword-Matching.
        """
        try:
            if person:
                fact_ids = await self.redis.smembers(f"mha:facts:person:{person}")
            else:
                fact_ids = await self.redis.smembers("mha:facts:all")

            if not fact_ids:
                return []

            fact_ids_list = list(fact_ids)
            pipe = self.redis.pipeline()
            for fid in fact_ids_list:
                pipe.hgetall(f"mha:fact:{fid}")
            all_data = await pipe.execute()

            now = datetime.now(timezone.utc)
            min_confidence = float(yaml_config.get("memory", {}).get(
                "min_confidence_for_context", 0.4
            ))
            # Stoppwoerter entfernen, Wortstamm-Prefixe fuer Teilwort-Match
            query_words = {
                w for w in query.lower().split()
                if w not in self._STOPWORDS and len(w) > 2
            }
            if not query_words:
                # Nur Stoppwoerter → alle Woerter behalten
                query_words = set(query.lower().split())

            # Wortstamm-Prefixe (erste 4 Zeichen) fuer unscharfes Matching
            query_stems = {w[:4] for w in query_words if len(w) >= 4}

            facts = []
            for data in all_data:
                if not data:
                    continue
                content = data.get("content", "")
                if isinstance(content, bytes):
                    content = content.decode()
                confidence = float(data.get("confidence", 0.5))
                if confidence < min_confidence:
                    continue

                content_lower = content.lower()
                content_words = content_lower.split()

                # Exakte Wort-Matches
                exact_matches = sum(1 for w in query_words if w in content_lower)
                # Stamm-Matches (unscharfes Matching)
                stem_matches = 0
                if query_stems:
                    content_stems = {w[:4] for w in content_words if len(w) >= 4}
                    stem_matches = len(query_stems & content_stems)

                # Kombinierter Score: exakte Matches zaehlen doppelt
                total_score = (exact_matches * 2 + stem_matches) / max(len(query_words) * 2 + len(query_stems), 1)

                if total_score > 0:
                    # Confidence als Boost-Faktor (0.5-1.0 → 0.75-1.0)
                    conf_boost = 0.5 + confidence * 0.5
                    # Temporal-Boost: Neuere Fakten bevorzugen (analog zu ChromaDB)
                    _updated_at = data.get("updated_at", "")
                    if isinstance(_updated_at, bytes):
                        _updated_at = _updated_at.decode()
                    if _updated_at:
                        try:
                            _days_old = (now - datetime.fromisoformat(_updated_at)).days
                            if _days_old < 60:
                                total_score += 0.25 * max(0.0, 1.0 - _days_old / 60.0)
                        except (ValueError, TypeError):
                            pass
                    fact_id = data.get("fact_id", "")
                    if isinstance(fact_id, bytes):
                        fact_id = fact_id.decode()
                    facts.append({
                        "content": content,
                        "fact_id": fact_id,
                        "category": data.get("category", b"general").decode() if isinstance(data.get("category", b"general"), bytes) else (data.get("category") or "general"),
                        "person": data.get("person", b"unknown").decode() if isinstance(data.get("person", b"unknown"), bytes) else (data.get("person") or "unknown"),
                        "confidence": confidence,
                        "times_confirmed": int(data.get("times_confirmed", 1)),
                        "relevance": min(1.0, total_score * conf_boost),
                    })

            facts.sort(key=lambda f: f["relevance"], reverse=True)
            return facts[:limit]
        except Exception as e:
            logger.error("Redis-Fallback search_facts fehlgeschlagen: %s", e)
            return []

    async def get_facts_by_person(self, person: str) -> list[dict]:
        """Return all stored facts for a specific person."""
        if not self.redis:
            return await self.search_facts(person, limit=20, person=person)

        try:
            fact_ids = await self.redis.smembers(f"mha:facts:person:{person}")
            fact_ids_list = list(fact_ids)
            if not fact_ids_list:
                return []

            pipe = self.redis.pipeline()
            for fact_id in fact_ids_list:
                pipe.hgetall(f"mha:fact:{fact_id}")
            results = await pipe.execute()

            facts = []
            for data in results:
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

    _RELATIONSHIP_CACHE_TTL = 300.0  # 5 Minuten

    def _get_cached_relationship(
        self, pattern: str, keywords: list[str], known_names: set[str]
    ) -> str:
        """Loest Beziehungsbegriffe auf (synchron, aus Cache).

        Prueft den internen Relationship-Cache (befuellt durch
        ``_refresh_relationship_cache``) ob fuer einen Beziehungsbegriff
        ein Name bekannt ist.  Cache wird nach 5 Minuten als stale betrachtet.
        """
        import time as _time
        cache = getattr(self, "_relationship_cache", None)
        cache_ts = getattr(self, "_relationship_cache_ts", 0.0)
        if cache and (_time.monotonic() - cache_ts) < self._RELATIONSHIP_CACHE_TTL:
            if pattern in cache:
                return cache[pattern]
        return ""

    async def refresh_relationship_cache(self):
        """Laedt Beziehungs-Fakten aus dem Gedaechtnis und baut Lookup auf.

        Wird periodisch aufgerufen, damit ``_get_cached_relationship``
        synchron antworten kann.
        """
        if not self.redis:
            return

        async with self._relationship_lock:
            await self._refresh_relationship_cache_inner()

    async def _refresh_relationship_cache_inner(self):
        """Innere Implementierung von refresh_relationship_cache (unter Lock)."""
        try:
            person_facts = await self.get_facts_by_category("person")
            cache: dict[str, str] = {}

            # Bekannte Namen aus Config
            household = yaml_config.get("household") or {}
            known_names = set()
            for m in household.get("members") or []:
                name = (m.get("name") or "").strip()
                if name:
                    known_names.add(name)
            primary = (household.get("primary_user") or "").strip()
            if primary:
                known_names.add(primary)
            titles = (yaml_config.get("persons") or {}).get("titles") or {}
            for name in titles:
                known_names.add(name)

            _RELATION_KEYWORDS = {
                "meine frau": ["frau", "ehefrau", "partnerin", "wife"],
                "mein mann": ["mann", "ehemann", "partner", "husband"],
                "mein sohn": ["sohn", "son"],
                "meine tochter": ["tochter", "daughter"],
                "mein bruder": ["bruder", "brother"],
                "meine schwester": ["schwester", "sister"],
                "meine mutter": ["mutter", "mama", "mother"],
                "mein vater": ["vater", "papa", "father"],
                "mein partner": ["partner", "partnerin"],
            }

            for fact in person_facts:
                content_lower = (fact.get("content") or "").lower()
                for rel_pattern, kws in _RELATION_KEYWORDS.items():
                    if rel_pattern in cache:
                        continue
                    if any(kw in content_lower for kw in kws):
                        # Name aus dem Fakt extrahieren: pruefe welcher
                        # bekannte Name im Content vorkommt
                        for name in known_names:
                            if name.lower() in content_lower:
                                cache[rel_pattern] = name.lower()
                                break

            import time as _time
            self._relationship_cache = cache
            self._relationship_cache_ts = _time.monotonic()
            if cache:
                logger.debug("Relationship Cache aktualisiert: %s", cache)
        except Exception as e:
            logger.debug("Relationship Cache Fehler: %s", e)

    async def get_facts_by_category(self, category: str) -> list[dict]:
        """Return all stored facts for a specific category."""
        if not self.redis:
            return await self.search_facts(category, limit=20)

        try:
            fact_ids = await self.redis.smembers(f"mha:facts:category:{category}")
            fact_ids_list = list(fact_ids)
            if not fact_ids_list:
                return []

            pipe = self.redis.pipeline()
            for fact_id in fact_ids_list:
                pipe.hgetall(f"mha:fact:{fact_id}")
            results = await pipe.execute()

            facts = []
            for data in results:
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
        """Return all stored semantic facts."""
        if not self.redis:
            return []

        try:
            fact_ids = await self.redis.smembers("mha:facts:all")
            fact_ids_list = list(fact_ids)
            if not fact_ids_list:
                return []

            pipe = self.redis.pipeline()
            for fact_id in fact_ids_list:
                pipe.hgetall(f"mha:fact:{fact_id}")
            results = await pipe.execute()

            facts = []
            for fact_id, data in zip(fact_ids_list, results):
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
        """Loescht einen Fakt aus ChromaDB und Redis.

        F-030: Lock um den gesamten Delete-Zyklus gegen TOCTOU Race Condition.
        """
        lock_key = f"mha:fact_lock:del:{fact_id}"
        lock_acquired = False
        if self.redis:
            try:
                lock_acquired = await self.redis.set(lock_key, "1", ex=10, nx=True)
                if not lock_acquired:
                    logger.debug("Delete-Lock nicht erhalten: %s", fact_id)
                    return False
            except Exception as e:
                logger.debug("Redis Delete-Lock nicht verfuegbar: %s", e)
        try:
            return await self._delete_fact_inner(fact_id)
        finally:
            if lock_acquired and self.redis:
                try:
                    await self.redis.delete(lock_key)
                except Exception as e:
                    logger.debug("Delete-Lock Freigabe fehlgeschlagen: %s", e)

    async def _delete_fact_inner(self, fact_id: str) -> bool:
        """Interne Loesch-Logik (unter Lock)."""
        if self.chroma_collection:
            try:
                await asyncio.to_thread(self.chroma_collection.delete, ids=[fact_id])
            except Exception as e:
                logger.error("Fehler beim Loeschen aus ChromaDB: %s", e)

        if not self.redis:
            return False

        try:
            data = await self.redis.hgetall(f"mha:fact:{fact_id}")
            if data:
                person = data.get("person", "unknown")
                category = data.get("category", "general")
                pipe = self.redis.pipeline()
                pipe.srem(f"mha:facts:person:{person}", fact_id)
                pipe.srem(f"mha:facts:category:{category}", fact_id)
                pipe.srem("mha:facts:all", fact_id)
                pipe.delete(f"mha:fact:{fact_id}")
                await pipe.execute()
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
        # ChromaDB versuchen
        if self.chroma_collection:
            try:
                results = await asyncio.to_thread(
                    self.chroma_collection.query,
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
                        fact_id = results["ids"][0][i] if results.get("ids") and results["ids"][0] else ""
                        confidence = float(meta.get("confidence", 0.5))
                        # Grosszuegigerer Filter als search_facts, aber
                        # Confidence-Filter um veraltete Fakten auszuschliessen
                        if distance < 1.5 and confidence >= 0.3:
                            facts.append({
                                "content": doc,
                                "fact_id": fact_id,
                                "category": meta.get("category", "general"),
                                "person": meta.get("person", "unknown"),
                                "confidence": confidence,
                                "times_confirmed": int(meta.get("times_confirmed", 1)),
                                "relevance": 1.0 - min(distance, 1.0),
                                "source": meta.get("source_conversation", ""),
                                "created_at": meta.get("created_at", ""),
                            })
                return facts
            except Exception as e:
                logger.warning("ChromaDB search_by_topic fehlgeschlagen, versuche Redis-Fallback: %s", e)

        # Redis-Fallback: Keyword-basierte Suche
        if self.redis:
            return await self._search_facts_redis_fallback(topic, limit)

        return []

    async def get_relevant_conversations(
        self, topic: str, limit: int = 3
    ) -> list[dict]:
        """Sucht relevante vergangene Gespraeche/Themen fuer Kontext-Kette.

        Filtert nur conversation_topic Fakten und bevorzugt juengere.

        Returns:
            Liste von {content, person, relevance, created_at}
        """
        results = await self.search_by_topic(topic, limit=limit * 3)
        # Nur conversation_topic Fakten
        convos = [
            r for r in results
            if r.get("category") == "conversation_topic" and r.get("relevance", 0) > 0.3
        ]
        # Sortieren: Relevanz * Aktualitaets-Bonus
        for c in convos:
            created = c.get("created_at", "")
            age_bonus = 1.0
            if created:
                try:
                    from datetime import datetime
                    age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(created)).days
                    # Juengere Gespraeche bevorzugen (Bonus bis 1.5x fuer heute)
                    age_bonus = max(0.5, 1.5 - age_days * 0.1)
                except (ValueError, TypeError):
                    pass
            c["_score"] = c.get("relevance", 0) * age_bonus
        convos.sort(key=lambda c: c["_score"], reverse=True)
        return convos[:limit]

    async def forget(self, topic: str) -> int:
        """
        Loescht alle Fakten die zu einem Thema passen.
        Gibt die Anzahl geloeschter Fakten zurueck.

        Nutzt eine niedrige Relevanz-Schwelle (0.2), damit der User auch
        indirekt passende Fakten loeschen kann. Bei explizitem 'Vergiss'
        soll nichts uebrig bleiben.
        """
        matching = await self.search_by_topic(topic, limit=20)
        deleted = 0

        for fact in matching:
            if fact.get("relevance", 0) < 0.2:
                continue  # Nur komplett irrelevante ignorieren

            # fact_id direkt aus search_by_topic (wenn vorhanden)
            fact_id = fact.get("fact_id", "")

            # Fallback: Ueber Redis nach fact_id suchen (Pipeline statt N+1)
            if not fact_id and self.redis:
                try:
                    all_ids = list(await self.redis.smembers("mha:facts:all"))
                    if all_ids:
                        pipe = self.redis.pipeline()
                        for fid in all_ids:
                            pipe.hget(f"mha:fact:{fid}", "content")
                        contents = await pipe.execute()
                        target = fact.get("content", "")
                        for fid, fdata in zip(all_ids, contents):
                            if fdata:
                                fdata_str = fdata if isinstance(fdata, str) else fdata.decode()
                                if fdata_str == target:
                                    fact_id = fid if isinstance(fid, str) else fid.decode()
                                    break
                except Exception as e:
                    logger.debug("Redis fact_id Lookup fehlgeschlagen: %s", e)

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
            fact_ids_list = list(fact_ids)
            if not fact_ids_list:
                return []
            pipe = self.redis.pipeline()
            for fact_id in fact_ids_list:
                pipe.hgetall(f"mha:fact:{fact_id}")
            all_data = await pipe.execute()
            for data in all_data:
                if data:
                    source = data.get("source_conversation", "")
                    if source.startswith("correction:"):
                        corrections.append({
                            "content": data.get("content", ""),
                            "category": data.get("category", "general"),
                            "person": data.get("person", "unknown"),
                            "confidence": float(data.get("confidence", 0.5)),
                            "source": source.replace("correction:", "", 1),
                            "created_at": data.get("created_at", ""),
                        })
            corrections.sort(key=lambda f: f.get("created_at", ""), reverse=True)
            return corrections
        except Exception as e:
            logger.error("Fehler bei Korrektur-History: %s", e)
            return []

    async def get_todays_learnings(self) -> list[dict]:
        """Gibt alle heute gelernten Fakten zurueck."""
        today = datetime.now(_LOCAL_TZ).strftime("%Y-%m-%d")

        if not self.redis:
            return []

        try:
            fact_ids = await self.redis.smembers("mha:facts:all")
            fact_ids_list = list(fact_ids)
            if not fact_ids_list:
                return []
            pipe = self.redis.pipeline()
            for fact_id in fact_ids_list:
                pipe.hgetall(f"mha:fact:{fact_id}")
            all_data = await pipe.execute()
            todays = []
            for data in all_data:
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

    # ------------------------------------------------------------------
    # Persoenliche Daten (Geburtstage, Jahrestage)
    # ------------------------------------------------------------------

    async def store_personal_date(
        self,
        date_type: str,
        person_name: str,
        date_mm_dd: str,
        year: str = "",
        label: str = "",
    ) -> bool:
        """Speichert ein persoenliches Datum (Geburtstag, Jahrestag, etc.).

        Args:
            date_type: "birthday", "anniversary", "memorial" etc.
            person_name: Name der Person ("Lisa", "Mama")
            date_mm_dd: Datum als MM-DD ("03-15" fuer 15. Maerz)
            year: Optionales Geburtsjahr ("1992")
            label: Optionales Label ("Hochzeitstag", "Todestag Opa")
        """
        type_labels = {
            "birthday": "Geburtstag",
            "anniversary": "Jahrestag",
            "memorial": "Gedenktag",
        }
        type_label = label or type_labels.get(date_type, date_type)

        # Lesbaren Content erzeugen
        try:
            from datetime import datetime as _dt
            parsed = _dt.strptime(date_mm_dd, "%m-%d")
            date_readable = f"{parsed.day}. {_MONTH_NAMES.get(parsed.month, str(parsed.month))}"
        except (ValueError, TypeError):
            date_readable = date_mm_dd

        if date_type == "birthday":
            content = f"{person_name}s Geburtstag ist am {date_readable}"
            if year:
                content += f" ({year})"
        elif date_type == "anniversary":
            content = f"{type_label} ist am {date_readable}"
            if year:
                content += f" (seit {year})"
        else:
            content = f"{type_label} von {person_name} ist am {date_readable}"
            if year:
                content += f" ({year})"

        date_meta = {
            "date_type": date_type,
            "date_mm_dd": date_mm_dd,
            "year": year,
            "label": type_label,
        }

        fact = SemanticFact(
            content=content,
            category="personal_date",
            person=person_name.lower(),
            confidence=1.0,
            source_conversation="explicit",
            date_meta=date_meta,
        )
        return await self.store_fact(fact)

    async def get_upcoming_personal_dates(self, days_ahead: int = 30) -> list[dict]:
        """Findet persoenliche Daten die in den naechsten X Tagen anstehen.

        Returns:
            Liste von {person, date_type, date_mm_dd, year, label,
                       content, days_until, anniversary_years}
        """
        if not self.redis:
            return []

        try:
            fact_ids = await self.redis.smembers("mha:facts:category:personal_date")
            if not fact_ids:
                return []

            now = datetime.now(timezone.utc)
            today_mm_dd = now.strftime("%m-%d")
            current_year = now.year
            results = []

            # Pipeline fuer Batch-Fetch
            fact_ids_list = list(fact_ids)
            pipe = self.redis.pipeline()
            for fact_id in fact_ids_list:
                pipe.hgetall(f"mha:fact:{fact_id}")
            all_data = await pipe.execute()

            for fact_id, data in zip(fact_ids_list, all_data):
                if not data:
                    continue

                date_mm_dd = data.get("date_mm_dd", "")
                if not date_mm_dd:
                    continue

                # Tage bis zum Datum berechnen
                try:
                    target = datetime.strptime(
                        f"{current_year}-{date_mm_dd}", "%Y-%m-%d"
                    )
                    if target.date() < now.date():
                        # Dieses Jahr schon vorbei -> naechstes Jahr
                        target = datetime.strptime(
                            f"{current_year + 1}-{date_mm_dd}", "%Y-%m-%d"
                        )
                    days_until = (target.date() - now.date()).days
                except (ValueError, TypeError):
                    continue

                if days_until > days_ahead:
                    continue

                # Jubilaeums-Jahre berechnen
                anniversary_years = 0
                stored_year = data.get("date_year", "")
                if stored_year:
                    try:
                        target_year = target.year
                        anniversary_years = target_year - int(stored_year)
                    except (ValueError, TypeError):
                        pass

                results.append({
                    "fact_id": data.get("fact_id", fact_id),
                    "person": data.get("person", "unknown"),
                    "date_type": data.get("date_type", ""),
                    "date_mm_dd": date_mm_dd,
                    "year": stored_year,
                    "label": data.get("date_label", ""),
                    "content": data.get("content", ""),
                    "days_until": days_until,
                    "anniversary_years": anniversary_years,
                })

            results.sort(key=lambda r: r["days_until"])
            return results

        except Exception as e:
            logger.error("Fehler bei upcoming personal dates: %s", e)
            return []

    @staticmethod
    def parse_date_from_text(text: str) -> Optional[str]:
        """Parst ein Datum aus deutschem Text und gibt MM-DD zurueck.

        Erkennt Formate wie:
        - "am 15. Maerz" / "am 15. März" -> "03-15"
        - "am 7.6." / "am 07.06." -> "06-07"
        - "am 15.3.1992" -> "03-15"
        """
        import re

        # Format: "15. Maerz" / "15. März"
        month_pattern = (
            r"(\d{1,2})\.\s*"
            r"(Januar|Februar|Maerz|März|April|Mai|Juni|Juli|August|"
            r"September|Oktober|November|Dezember)"
        )
        m = re.search(month_pattern, text, re.IGNORECASE)
        if m:
            day = int(m.group(1))
            month_name = m.group(2).lower().replace("ä", "ae")
            month_num = _MONTH_LOOKUP.get(month_name, 0)
            if month_num:
                return f"{month_num:02d}-{day:02d}"

        # Format: "15.3." oder "15.03." oder "15.3.1992"
        numeric_pattern = r"(\d{1,2})\.(\d{1,2})\.(?:\d{2,4})?"
        m = re.search(numeric_pattern, text)
        if m:
            day = int(m.group(1))
            month = int(m.group(2))
            if 1 <= month <= 12 and 1 <= day <= 31:
                return f"{month:02d}-{day:02d}"

        return None

    @staticmethod
    def parse_year_from_text(text: str) -> str:
        """Extrahiert ein Jahreszahl aus Text (1900-2099)."""
        import re
        m = re.search(r"\b(19\d{2}|20\d{2})\b", text)
        return m.group(1) if m else ""

    async def get_stats(self) -> dict:
        if not self.redis:
            return {"total_facts": 0, "categories": {}, "persons": []}

        try:
            # Pipeline fuer total + alle Kategorie-Counts
            pipe = self.redis.pipeline()
            pipe.scard("mha:facts:all")
            for cat in FACT_CATEGORIES:
                pipe.scard(f"mha:facts:category:{cat}")
            stats_results = await pipe.execute()
            total = stats_results[0]
            categories = {}
            for idx, cat in enumerate(FACT_CATEGORIES):
                count = stats_results[idx + 1]
                if count > 0:
                    categories[cat] = count

            # Pipeline fuer Person-Lookup
            fact_ids = await self.redis.smembers("mha:facts:all")
            fact_ids_list = list(fact_ids)
            persons = set()
            if fact_ids_list:
                pipe = self.redis.pipeline()
                for fact_id in fact_ids_list:
                    pipe.hget(f"mha:fact:{fact_id}", "person")
                person_results = await pipe.execute()
                for person in person_results:
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

    async def clear_all(self) -> int:
        """Loescht alle Fakten aus ChromaDB und Redis. Gibt Anzahl geloeschter Fakten zurueck."""
        deleted = 0

        # Redis-Fakten aufraumen
        if self.redis:
            try:
                fact_ids = await self.redis.smembers("mha:facts:all")
                for fact_id in fact_ids:
                    data = await self.redis.hgetall(f"mha:fact:{fact_id}")
                    if data:
                        person = data.get("person", "unknown")
                        category = data.get("category", "general")
                        await self.redis.srem(f"mha:facts:person:{person}", fact_id)
                        await self.redis.srem(f"mha:facts:category:{category}", fact_id)
                    await self.redis.delete(f"mha:fact:{fact_id}")
                    deleted += 1
                await self.redis.delete("mha:facts:all")
                # Person- und Category-Sets aufraeumen
                async for key in self.redis.scan_iter(match="mha:facts:person:*"):
                    await self.redis.delete(key)
                async for key in self.redis.scan_iter(match="mha:facts:category:*"):
                    await self.redis.delete(key)
            except Exception as e:
                logger.error("Fehler beim Loeschen der Redis-Fakten: %s", e)

        # ChromaDB Collection neu erstellen
        if self._chroma_client and self.chroma_collection:
            try:
                self._chroma_client.delete_collection("mha_semantic_facts")
                from .embeddings import get_embedding_function
                ef = get_embedding_function()
                col_kwargs = {
                    "name": "mha_semantic_facts",
                    "metadata": {"description": "MindHome Assistant - Extrahierte Fakten"},
                }
                if ef:
                    col_kwargs["embedding_function"] = ef
                self.chroma_collection = self._chroma_client.get_or_create_collection(**col_kwargs)
                logger.info("Semantisches Gedaechtnis geloescht (%d Fakten)", deleted)
            except Exception as e:
                logger.error("Fehler beim Neuerstellen der ChromaDB-Collection: %s", e)

        return deleted

    async def expire_stale_facts(self, max_age_days: int = 90) -> int:
        """Entfernt Fakten die seit max_age_days nicht bestaetigt/aktualisiert wurden.

        ChromaDB hat kein natives TTL, daher iteriert diese Methode ueber
        alle Redis-Fakt-Metadaten und loescht veraltete Eintraege aus
        beiden Speichern (Redis + ChromaDB).
        """
        if not self.redis or not self.chroma_collection:
            return 0

        deleted = 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

        try:
            # Alle Fakt-IDs aus Redis scannen
            stale_ids = []
            async for key in self.redis.scan_iter(match="mha:fact:*", count=200):
                key_str = key.decode() if isinstance(key, bytes) else key
                # Nur Top-Level-Hashes (keine Sub-Keys)
                if key_str.count(":") != 2:
                    continue
                try:
                    updated_at = await self.redis.hget(key_str, "updated_at")
                    if isinstance(updated_at, bytes):
                        updated_at = updated_at.decode()
                    if not updated_at:
                        continue
                    last_update = datetime.fromisoformat(updated_at)
                    if last_update.tzinfo is None:
                        last_update = last_update.replace(tzinfo=timezone.utc)
                    if last_update < cutoff:
                        fact_id = key_str.split(":")[-1]
                        stale_ids.append(fact_id)
                except (ValueError, TypeError):
                    continue

            # Batch-Loeschung
            for fact_id in stale_ids:
                try:
                    await asyncio.to_thread(self.chroma_collection.delete, ids=[fact_id])
                    await self.redis.delete(f"mha:fact:{fact_id}")
                    deleted += 1
                except Exception as e:
                    logger.debug("Stale fact %s Loeschung fehlgeschlagen: %s", fact_id, e)

            if deleted:
                logger.info("expire_stale_facts: %d Fakten aelter als %d Tage entfernt",
                            deleted, max_age_days)
        except Exception as e:
            logger.warning("expire_stale_facts Fehler: %s", e)

        return deleted
