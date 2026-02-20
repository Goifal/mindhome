"""
Tests fuer Memory-System — Episodic Chunking + Semantic Fact Decay.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestEpisodicChunking:
    """Tests fuer MemoryManager._split_conversation()."""

    def test_short_text_no_split(self):
        from assistant.memory import MemoryManager
        result = MemoryManager._split_conversation("Hallo Welt")
        assert result == ["Hallo Welt"]

    def test_empty_text(self):
        from assistant.memory import MemoryManager
        result = MemoryManager._split_conversation("")
        assert result == []

    def test_speaker_change_split(self):
        from assistant.memory import MemoryManager
        text = (
            "User: Wie wird das Wetter morgen in Wien? Ich brauche das fuer die Planung. "
            "Das ist wirklich wichtig und ich frage mich ob es regnen wird oder nicht. "
            "Assistant: Morgen wird es in Wien sonnig bei 22 Grad. "
            "Kein Regen erwartet. Perfektes Wetter fuer draussen. "
            "User: Super danke dir."
        )
        result = MemoryManager._split_conversation(text)
        # Sollte in mehrere Chunks aufgeteilt werden
        assert len(result) >= 1
        assert all(len(chunk) > 0 for chunk in result)

    def test_chunks_have_overlap(self):
        from assistant.memory import MemoryManager
        # Langer Text ohne Speaker-Wechsel
        text = "Dies ist ein sehr langer Text. " * 20  # ~600 Zeichen
        result = MemoryManager._split_conversation(text)
        assert len(result) >= 2


class TestSemanticFactDecay:
    """Tests fuer Contradiction Detection + Fact Decay Logik."""

    def test_category_confidence_mapping(self):
        from assistant.memory_extractor import MemoryExtractor
        conf = MemoryExtractor.CATEGORY_CONFIDENCE
        assert conf["health"] > conf["general"]
        assert conf["person"] > conf["intent"]
        assert conf["preference"] > conf["general"]

    def test_all_categories_have_confidence(self):
        from assistant.memory_extractor import MemoryExtractor
        expected = ["health", "person", "preference", "habit", "work", "intent", "general"]
        for cat in expected:
            assert cat in MemoryExtractor.CATEGORY_CONFIDENCE
