"""
Semantic Response Cache — Cached LLM-Antworten fuer wiederkehrende Anfragen.

Fuer Status-Queries ("Wie warm ist es im Wohnzimmer?") und Device-Queries
die innerhalb eines kurzen Zeitfensters wiederholt gestellt werden.

Cache-Key: Hash aus (intent_type, profile_category, normalisierter Text).
TTL: Konfigurierbar, Default 45s fuer Status-Queries, 24h fuer Knowledge.

Unterstuetzte Kategorien:
- device_query: Status-Abfragen (TTL 45s)
- knowledge: Faktische Antworten (TTL 24h)

Device-Commands (set_*) werden NIEMALS gecacht.

Features:
- Pre-Caching: Morgen-Briefing und haeufige Abfragen vorberechnen
- Room-Invalidation: Cache wird bei State-Aenderung im Raum invalidiert
"""

import hashlib
import json
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Kategorien die gecacht werden duerfen
_CACHEABLE_CATEGORIES = frozenset({"device_query", "knowledge"})

# Default TTL pro Kategorie (Sekunden)
_DEFAULT_TTL = {
    "device_query": 45,
    "knowledge": 86400,  # 24 Stunden
}


class ResponseCache:
    """Redis-basierter Cache fuer LLM-Antworten."""

    def __init__(self):
        self._redis = None
        self._enabled = True
        self._ttl_overrides: dict[str, int] = {}
        self._hits = 0
        self._misses = 0
        self._pre_cache_count = 0
        self._category_hits: dict[str, int] = {}
        self._invalidation_count = 0

    def configure(self, *, enabled: bool = True, ttl_overrides: Optional[dict] = None):
        """Konfiguriert den Cache (aus settings.yaml)."""
        self._enabled = enabled
        if ttl_overrides:
            self._ttl_overrides = ttl_overrides

    def set_redis(self, redis_client) -> None:
        """Setzt den Redis-Client."""
        self._redis = redis_client

    def _make_key(self, text: str, category: str, room: Optional[str] = None) -> str:
        """Erzeugt einen Cache-Key aus normalisiertem Text + Kategorie."""
        # Normalisierung: lowercase, Whitespace komprimieren, Satzzeichen entfernen
        normalized = " ".join(text.lower().split())
        for ch in ".,!?;:":
            normalized = normalized.replace(ch, "")
        parts = [category, normalized]
        if room:
            parts.append(room.lower())
        raw = "|".join(parts)
        h = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return f"mha:rcache:{h}"

    def _get_ttl(self, category: str) -> int:
        """Gibt TTL fuer eine Kategorie zurueck."""
        if category in self._ttl_overrides:
            return self._ttl_overrides[category]
        return _DEFAULT_TTL.get(category, 0)

    async def get(
        self, text: str, category: str, room: Optional[str] = None,
    ) -> Optional[dict]:
        """Sucht eine gecachte Antwort.

        Returns: Dict mit 'response', 'model', 'tts' oder None bei Cache-Miss.
        """
        if not self._enabled or not self._redis:
            return None
        if category not in _CACHEABLE_CATEGORIES:
            return None

        ttl = self._get_ttl(category)
        if ttl <= 0:
            return None

        key = self._make_key(text, category, room)
        try:
            raw = await self._redis.get(key)
            if raw:
                self._hits += 1
                self._category_hits[category] = self._category_hits.get(category, 0) + 1
                data = json.loads(raw)
                age_ms = round((time.time() - data.get("_ts", 0)) * 1000)
                logger.info(
                    "ResponseCache HIT [%s] age=%dms key=%s",
                    category, age_ms, key[-8:],
                )
                return data
        except Exception as e:
            logger.debug("ResponseCache get Fehler: %s", e)

        self._misses += 1
        return None

    async def put(
        self,
        text: str,
        category: str,
        response: str,
        model: str,
        room: Optional[str] = None,
        tts: Optional[dict] = None,
    ) -> None:
        """Speichert eine Antwort im Cache."""
        if not self._enabled or not self._redis:
            return
        if category not in _CACHEABLE_CATEGORIES:
            return

        ttl = self._get_ttl(category)
        if ttl <= 0:
            return

        key = self._make_key(text, category, room)
        data = {
            "response": response,
            "model": model,
            "_ts": time.time(),
        }
        if tts:
            data["tts"] = tts
        try:
            await self._redis.set(key, json.dumps(data), ex=ttl)
            logger.debug("ResponseCache PUT [%s] ttl=%ds key=%s", category, ttl, key[-8:])
        except Exception as e:
            logger.debug("ResponseCache put Fehler: %s", e)

    async def pre_cache(
        self,
        text: str,
        category: str,
        response: str,
        model: str,
        room: Optional[str] = None,
        tts: Optional[dict] = None,
    ) -> bool:
        """Speichert eine Antwort explizit im Cache (Pre-Caching).

        Wird verwendet fuer vorberechnete Antworten wie Morgen-Briefing,
        haeufige Status-Abfragen etc.

        Returns: True wenn erfolgreich gecacht.
        """
        if not self._enabled or not self._redis:
            return False
        if category not in _CACHEABLE_CATEGORIES:
            return False

        ttl = self._get_ttl(category)
        if ttl <= 0:
            return False

        key = self._make_key(text, category, room)
        data = {
            "response": response,
            "model": model,
            "_ts": time.time(),
            "_pre_cached": True,
        }
        if tts:
            data["tts"] = tts
        try:
            await self._redis.set(key, json.dumps(data), ex=ttl)
            self._pre_cache_count += 1
            logger.debug("ResponseCache PRE-CACHE [%s] ttl=%ds key=%s", category, ttl, key[-8:])
            return True
        except Exception as e:
            logger.debug("ResponseCache pre_cache Fehler: %s", e)
            return False

    async def invalidate_by_room(self, room: str) -> int:
        """Invalidiert device_query-Cache fuer einen bestimmten Raum.

        Wird aufgerufen wenn sich ein State im Raum aendert,
        damit gecachte Antworten nicht veraltet sind.

        Returns: Anzahl geloeschter Keys.
        """
        if not self._redis or not room:
            return 0

        try:
            # Scan nach Cache-Keys die diesen Raum betreffen
            pattern = "mha:rcache:*"
            deleted = 0
            async for key in self._redis.scan_iter(match=pattern, count=100):
                try:
                    raw = await self._redis.get(key)
                    if not raw:
                        continue
                    # Key-Struktur: category|text|room -> SHA256
                    # Wir koennen den Raum nicht aus dem Hash rekonstruieren,
                    # daher loeschen wir alle device_query-Caches (kurzer TTL, schnell rebuilt)
                    data = json.loads(raw)
                    if not data.get("_pre_cached"):
                        await self._redis.delete(key)
                        deleted += 1
                except Exception:
                    continue

            if deleted:
                self._invalidation_count += deleted
                logger.debug("ResponseCache invalidated %d entries for room '%s'", deleted, room)
            return deleted
        except Exception as e:
            logger.debug("ResponseCache invalidate Fehler: %s", e)
            return 0

    def get_hit_rate(self) -> dict:
        """Gibt Cache-Statistiken zurueck."""
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "total": total,
            "hit_rate": round(self._hits / total * 100, 1) if total else 0.0,
            "pre_cached": self._pre_cache_count,
            "invalidations": self._invalidation_count,
            "category_hits": dict(self._category_hits),
        }
