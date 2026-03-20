"""Unified Notification Deduplication — Cross-Module semantische Duplikaterkennung.

Stellt einen zentralen Dedup-Service bereit, den alle Notification-Handler
(Proactive, Insight, Anticipation, Spontaneous, Learning, Wellness, Music)
nutzen koennen. Verhindert, dass Module A und Module B semantisch identische
Nachrichten an den User senden.

Buffer: Redis-Liste ``mha:unified_notification_buffer`` (max 20 Eintraege, 30 Min).
Schwelle: Cosinus-Aehnlichkeit > 0.85 gilt als Duplikat.
CRITICAL/HIGH Urgency wird NICHT gefiltert.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

_BUFFER_KEY = "mha:unified_notification_buffer"
_MAX_BUFFER_SIZE = 20
_DEFAULT_WINDOW_MINUTES = 30
_SIMILARITY_THRESHOLD = 0.85


class NotificationDedup:
    """Zentraler Dedup-Service fuer alle Notification-Quellen."""

    def __init__(self, redis_client=None):
        self._redis = redis_client

    def set_redis(self, redis_client) -> None:
        self._redis = redis_client

    async def is_duplicate(
        self,
        message: str,
        source: str = "",
        urgency: str = "low",
        window_minutes: int = _DEFAULT_WINDOW_MINUTES,
    ) -> bool:
        """Prueft ob eine semantisch aehnliche Notification kuerzlich gesendet wurde.

        Args:
            message: Der Notification-Text.
            source: Quelle (z.B. ``insight/weather_windows``, ``anticipation``,
                    ``spontaneous``, ``learning``).
            urgency: Dringlichkeit. ``critical``/``high`` werden nie gefiltert.
            window_minutes: Zeitfenster fuer Duplikat-Erkennung.

        Returns:
            ``True`` wenn ein semantisches Duplikat im Buffer liegt.
        """
        if urgency in ("critical", "high"):
            return False

        if not self._redis:
            return False

        if not message or len(message.strip()) < 10:
            return False

        try:
            from .embeddings import get_embedding_function, compute_cosine_similarity

            ef = get_embedding_function()
            if not ef:
                return False

            now = time.time()
            new_emb = ef([message])[0]

            raw_items = await self._redis.lrange(_BUFFER_KEY, 0, _MAX_BUFFER_SIZE - 1)
            for raw in raw_items:
                try:
                    item = json.loads(raw)
                    ts = item.get("ts", 0)
                    if (now - ts) > window_minutes * 60:
                        continue
                    old_emb = item.get("emb", [])
                    if not old_emb:
                        continue
                    similarity = compute_cosine_similarity(new_emb, old_emb)
                    if similarity > _SIMILARITY_THRESHOLD:
                        old_source = item.get("src", "?")
                        logger.info(
                            "Unified Dedup: Duplikat erkannt (%.2f) — "
                            "neu=[%s] %.50s vs alt=[%s] %.50s",
                            similarity,
                            source,
                            message,
                            old_source,
                            item.get("txt", "")[:50],
                        )
                        return True
                except (json.JSONDecodeError, TypeError):
                    continue

            # Neuen Eintrag in Buffer speichern
            entry = json.dumps(
                {"ts": now, "emb": new_emb, "src": source, "txt": message[:100]},
                ensure_ascii=False,
            )
            await self._redis.lpush(_BUFFER_KEY, entry)
            await self._redis.ltrim(_BUFFER_KEY, 0, _MAX_BUFFER_SIZE - 1)
            await self._redis.expire(_BUFFER_KEY, window_minutes * 60)

        except Exception as e:
            logger.debug("Unified Dedup Fehler: %s", e)

        return False

    async def clear_buffer(self) -> None:
        """Buffer leeren (z.B. beim Neustart)."""
        if self._redis:
            try:
                await self._redis.delete(_BUFFER_KEY)
            except Exception:
                pass
