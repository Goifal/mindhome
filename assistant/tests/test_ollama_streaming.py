"""
Tests fuer OllamaClient — Streaming + Think-Tag-Handling.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.ollama_client import strip_think_tags


class TestStripThinkTags:
    def test_no_think_tags(self):
        assert strip_think_tags("Hallo Welt") == "Hallo Welt"

    def test_strips_think_block(self):
        text = "<think>Ich denke nach...</think>Die Antwort ist 42."
        assert strip_think_tags(text) == "Die Antwort ist 42."

    def test_multiline_think_block(self):
        text = "<think>\nSchritt 1\nSchritt 2\n</think>\nErgebnis."
        assert strip_think_tags(text) == "Ergebnis."

    def test_empty_text(self):
        assert strip_think_tags("") == ""

    def test_none_text(self):
        assert strip_think_tags(None) is None

    def test_only_think_block(self):
        text = "<think>Nur Gedanken</think>"
        result = strip_think_tags(text)
        # Soll den Originaltext behalten wenn nichts uebrig bleibt
        assert result == text
