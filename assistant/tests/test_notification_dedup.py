"""Tests fuer Unified Notification Deduplication."""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.notification_dedup import NotificationDedup


@pytest.fixture
def redis_mock():
    """Async Redis-Mock mit lrange/lpush/ltrim/expire."""
    r = AsyncMock()
    r.lrange = AsyncMock(return_value=[])
    r.lpush = AsyncMock()
    r.ltrim = AsyncMock()
    r.expire = AsyncMock()
    r.delete = AsyncMock()
    return r


@pytest.fixture
def dedup(redis_mock):
    d = NotificationDedup(redis_client=redis_mock)
    return d


@pytest.mark.asyncio
async def test_critical_urgency_bypasses_dedup(dedup):
    """CRITICAL/HIGH Meldungen werden nie als Duplikat erkannt."""
    result = await dedup.is_duplicate("Feueralarm!", source="test", urgency="critical")
    assert result is False

    result = await dedup.is_duplicate("Wasseralarm!", source="test", urgency="high")
    assert result is False


@pytest.mark.asyncio
async def test_no_redis_returns_false(dedup):
    """Ohne Redis-Verbindung kein Dedup."""
    dedup._redis = None
    result = await dedup.is_duplicate("Test message", source="test")
    assert result is False


@pytest.mark.asyncio
async def test_short_messages_skipped(dedup):
    """Sehr kurze Nachrichten werden nicht geprueft."""
    result = await dedup.is_duplicate("Hi", source="test")
    assert result is False


@pytest.mark.asyncio
async def test_empty_buffer_no_duplicate(dedup, redis_mock):
    """Leerer Buffer = kein Duplikat, Eintrag wird gespeichert."""
    fake_emb = [0.1] * 384

    with patch(
        "assistant.notification_dedup.NotificationDedup.is_duplicate",
        wraps=dedup.is_duplicate,
    ):
        with patch("assistant.embeddings.get_embedding_function") as mock_ef:
            mock_ef.return_value = lambda texts: [fake_emb]
            result = await dedup.is_duplicate(
                "Das Licht im Flur ist seit 3 Stunden an.", source="insight"
            )

    assert result is False
    redis_mock.lpush.assert_called_once()


@pytest.mark.asyncio
async def test_duplicate_detected(dedup, redis_mock):
    """Semantisch aehnliche Nachrichten werden als Duplikat erkannt."""
    fake_emb = [0.5] * 384

    # Simuliere einen bestehenden Buffer-Eintrag mit gleichem Embedding
    existing_entry = json.dumps(
        {
            "ts": time.time(),
            "emb": fake_emb,
            "src": "insight/weather",
            "txt": "Regen erwartet, Fenster offen",
        }
    )
    redis_mock.lrange = AsyncMock(return_value=[existing_entry.encode()])

    with patch("assistant.embeddings.get_embedding_function") as mock_ef:
        # Gleiches Embedding = Cosinus-Aehnlichkeit 1.0
        mock_ef.return_value = lambda texts: [fake_emb]
        result = await dedup.is_duplicate(
            "Regen erwartet, Fenster offen",
            source="anticipation",
        )

    assert result is True


@pytest.mark.asyncio
async def test_expired_entries_ignored(dedup, redis_mock):
    """Alte Eintraege ausserhalb des Zeitfensters werden ignoriert."""
    fake_emb = [0.5] * 384

    old_entry = json.dumps(
        {
            "ts": time.time() - 3600,  # 1 Stunde alt
            "emb": fake_emb,
            "src": "insight",
            "txt": "Alte Nachricht",
        }
    )
    redis_mock.lrange = AsyncMock(return_value=[old_entry.encode()])

    with patch("assistant.embeddings.get_embedding_function") as mock_ef:
        mock_ef.return_value = lambda texts: [fake_emb]
        result = await dedup.is_duplicate("Alte Nachricht nochmal", source="test")

    assert result is False


@pytest.mark.asyncio
async def test_clear_buffer(dedup, redis_mock):
    """Buffer leeren funktioniert."""
    await dedup.clear_buffer()
    redis_mock.delete.assert_called_once_with("mha:unified_notification_buffer")
