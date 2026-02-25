"""
Tests fuer Feature 5: Emotionales Gedaechtnis (memory_extractor reactions).
"""
import json
import pytest
from unittest.mock import AsyncMock, patch

from assistant.memory_extractor import MemoryExtractor


class TestDetectNegativeReaction:
    """Tests fuer detect_negative_reaction()."""

    @pytest.fixture
    def extractor(self, ollama_mock):
        """MemoryExtractor-Instanz."""
        semantic = AsyncMock()
        return MemoryExtractor(ollama=ollama_mock, semantic_memory=semantic)

    def test_nein_detected(self, extractor):
        assert extractor.detect_negative_reaction("Nein") is True

    def test_lass_das_detected(self, extractor):
        assert extractor.detect_negative_reaction("Lass das!") is True

    def test_hoer_auf_detected(self, extractor):
        assert extractor.detect_negative_reaction("Hoer auf damit") is True

    def test_stop_detected(self, extractor):
        assert extractor.detect_negative_reaction("Stop!") is True

    def test_stopp_detected(self, extractor):
        assert extractor.detect_negative_reaction("Stopp sofort") is True

    def test_nicht_detected(self, extractor):
        assert extractor.detect_negative_reaction("Das will ich nicht") is True

    def test_undo_detected(self, extractor):
        assert extractor.detect_negative_reaction("undo") is True

    def test_abbrechen_detected(self, extractor):
        assert extractor.detect_negative_reaction("Abbrechen bitte") is True

    def test_case_insensitive(self, extractor):
        assert extractor.detect_negative_reaction("NEIN DANKE") is True

    def test_positive_text_not_detected(self, extractor):
        assert extractor.detect_negative_reaction("Ja, mach das") is False

    def test_neutral_text_not_detected(self, extractor):
        assert extractor.detect_negative_reaction("Wie wird das Wetter?") is False

    def test_empty_text(self, extractor):
        assert extractor.detect_negative_reaction("") is False


class TestExtractReaction:
    """Tests fuer extract_reaction()."""

    @pytest.fixture
    def extractor(self, ollama_mock):
        semantic = AsyncMock()
        return MemoryExtractor(ollama=ollama_mock, semantic_memory=semantic)

    @pytest.mark.asyncio
    async def test_negative_reaction_stored(self, extractor, redis_mock):
        """Negative Reaktion wird in Redis gespeichert."""
        await extractor.extract_reaction(
            user_text="Lass das!",
            action_performed="set_cover",
            accepted=False,
            person="Max",
            redis_client=redis_mock,
        )
        redis_mock.lpush.assert_called_once()
        key = redis_mock.lpush.call_args[0][0]
        assert "emotional_memory" in key
        assert "set_cover" in key
        assert "max" in key

    @pytest.mark.asyncio
    async def test_positive_reaction_stored(self, extractor, redis_mock):
        """Positive Reaktion wird mit 'positive' Sentiment gespeichert."""
        await extractor.extract_reaction(
            user_text="Ja, danke",
            action_performed="set_light",
            accepted=True,
            person="Max",
            redis_client=redis_mock,
        )
        redis_mock.lpush.assert_called_once()
        stored_json = redis_mock.lpush.call_args[0][1]
        data = json.loads(stored_json)
        assert data["sentiment"] == "positive"

    @pytest.mark.asyncio
    async def test_negative_sentiment_stored(self, extractor, redis_mock):
        """Negative Reaktion hat 'negative' Sentiment."""
        await extractor.extract_reaction(
            user_text="Nein!",
            action_performed="set_cover",
            accepted=False,
            person="Max",
            redis_client=redis_mock,
        )
        stored_json = redis_mock.lpush.call_args[0][1]
        data = json.loads(stored_json)
        assert data["sentiment"] == "negative"

    @pytest.mark.asyncio
    async def test_ltrim_limits_entries(self, extractor, redis_mock):
        """LTRIM begrenzt auf 20 Eintraege."""
        await extractor.extract_reaction(
            user_text="Nein",
            action_performed="set_light",
            accepted=False,
            person="Max",
            redis_client=redis_mock,
        )
        redis_mock.ltrim.assert_called_once()
        # LTRIM 0 19 = max 20 entries
        args = redis_mock.ltrim.call_args[0]
        assert args[1] == 0
        assert args[2] == 19

    @pytest.mark.asyncio
    async def test_text_truncated(self, extractor, redis_mock):
        """User-Text wird auf 100 Zeichen begrenzt."""
        long_text = "A" * 200
        await extractor.extract_reaction(
            user_text=long_text,
            action_performed="set_light",
            accepted=False,
            person="Max",
            redis_client=redis_mock,
        )
        stored_json = redis_mock.lpush.call_args[0][1]
        data = json.loads(stored_json)
        assert len(data["user_text"]) <= 100


class TestGetEmotionalContext:
    """Tests fuer get_emotional_context()."""

    @pytest.fixture
    def extractor(self, ollama_mock):
        semantic = AsyncMock()
        return MemoryExtractor(ollama=ollama_mock, semantic_memory=semantic)

    @pytest.mark.asyncio
    async def test_no_history_returns_none(self, extractor, redis_mock):
        """Keine History gibt None zurueck."""
        redis_mock.lrange = AsyncMock(return_value=[])
        result = await extractor.get_emotional_context(
            action_type="set_light",
            person="Max",
            redis_client=redis_mock,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_below_threshold_returns_none(self, extractor, redis_mock):
        """Unter Threshold (default 2) gibt None zurueck."""
        entries = [
            json.dumps({"sentiment": "negative", "user_text": "Nein", "timestamp": "2026-01-01"}).encode(),
        ]
        redis_mock.lrange = AsyncMock(return_value=entries)
        result = await extractor.get_emotional_context(
            action_type="set_light",
            person="Max",
            redis_client=redis_mock,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_above_threshold_returns_warning(self, extractor, redis_mock):
        """Ueber Threshold gibt Warn-String zurueck."""
        entries = [
            json.dumps({"sentiment": "negative", "user_text": "Nein", "timestamp": "2026-01-01"}).encode(),
            json.dumps({"sentiment": "negative", "user_text": "Lass das", "timestamp": "2026-01-02"}).encode(),
        ]
        redis_mock.lrange = AsyncMock(return_value=entries)
        result = await extractor.get_emotional_context(
            action_type="set_cover",
            person="Max",
            redis_client=redis_mock,
        )
        assert result is not None
        assert "negativ" in result.lower() or "EMOTIONALES" in result
        assert "set_cover" in result

    @pytest.mark.asyncio
    async def test_mixed_reactions_only_counts_negative(self, extractor, redis_mock):
        """Nur negative Reaktionen werden gezaehlt."""
        entries = [
            json.dumps({"sentiment": "positive", "user_text": "Ja", "timestamp": "2026-01-01"}).encode(),
            json.dumps({"sentiment": "negative", "user_text": "Nein", "timestamp": "2026-01-02"}).encode(),
            json.dumps({"sentiment": "positive", "user_text": "OK", "timestamp": "2026-01-03"}).encode(),
        ]
        redis_mock.lrange = AsyncMock(return_value=entries)
        result = await extractor.get_emotional_context(
            action_type="set_light",
            person="Max",
            redis_client=redis_mock,
        )
        # Nur 1 negative → unter Threshold
        assert result is None
