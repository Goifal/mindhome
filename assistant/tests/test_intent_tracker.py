"""
Tests fuer IntentTracker — Datum-Parsing, Intent-Parsing, Speicherung.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from assistant.intent_tracker import IntentTracker, parse_relative_date


class TestParseRelativeDate:
    """Tests fuer parse_relative_date()."""

    def _ref(self):
        """Fester Referenz-Zeitpunkt: Mittwoch 2026-02-18."""
        return datetime(2026, 2, 18, 10, 0, 0)  # Mittwoch

    def test_heute(self):
        ref = self._ref()
        assert parse_relative_date("heute", ref) == "2026-02-18"

    def test_morgen(self):
        ref = self._ref()
        assert parse_relative_date("morgen", ref) == "2026-02-19"

    def test_uebermorgen(self):
        ref = self._ref()
        assert parse_relative_date("uebermorgen", ref) == "2026-02-20"

    def test_in_3_tagen(self):
        ref = self._ref()
        assert parse_relative_date("in 3 Tagen", ref) == "2026-02-21"

    def test_in_2_wochen(self):
        ref = self._ref()
        assert parse_relative_date("in 2 Wochen", ref) == "2026-03-04"

    def test_naechsten_freitag(self):
        ref = self._ref()  # Mittwoch
        result = parse_relative_date("am Freitag", ref)
        assert result == "2026-02-20"  # 2 Tage spaeter

    def test_naechsten_montag_springt_woche(self):
        ref = self._ref()  # Mittwoch
        result = parse_relative_date("am Montag", ref)
        assert result == "2026-02-23"  # Naechster Montag

    def test_naechstes_wochenende(self):
        ref = self._ref()  # Mittwoch
        result = parse_relative_date("naechstes Wochenende", ref)
        assert result == "2026-02-21"  # Samstag

    def test_naechste_woche(self):
        ref = self._ref()
        result = parse_relative_date("naechste Woche", ref)
        assert result == "2026-02-25"  # +7 Tage

    def test_ende_der_woche(self):
        ref = self._ref()  # Mittwoch
        result = parse_relative_date("Ende der Woche", ref)
        assert result == "2026-02-20"  # Freitag

    def test_unknown_returns_none(self):
        assert parse_relative_date("irgendwann") is None

    def test_empty_string(self):
        assert parse_relative_date("") is None


class TestParseIntents:
    """Tests fuer _parse_intents()."""

    @pytest.fixture
    def tracker(self):
        ollama = AsyncMock()
        t = IntentTracker(ollama)
        return t

    def test_valid_json_array(self, tracker):
        llm_output = json.dumps([{"intent": "Besuch", "deadline": "2026-03-01"}])
        result = tracker._parse_intents(llm_output, "Max")
        assert len(result) == 1
        assert result[0]["intent"] == "Besuch"
        assert result[0]["person"] == "Max"

    def test_empty_array(self, tracker):
        result = tracker._parse_intents("[]", "Max")
        assert result == []

    def test_json_with_surrounding_text(self, tracker):
        llm_output = 'Hier sind die Intents:\n[{"intent": "Arzt", "deadline": "2026-03-05"}]\nFertig.'
        result = tracker._parse_intents(llm_output, "Anna")
        assert len(result) == 1
        assert result[0]["intent"] == "Arzt"

    def test_invalid_json(self, tracker):
        result = tracker._parse_intents("Das ist kein JSON", "Max")
        assert result == []

    def test_filters_empty_intents(self, tracker):
        llm_output = json.dumps([{"intent": "", "deadline": "2026-03-01"}, {"intent": "Urlaub"}])
        result = tracker._parse_intents(llm_output, "Max")
        assert len(result) == 1
        assert result[0]["intent"] == "Urlaub"


class TestExtractIntents:
    """Tests fuer extract_intents() — Schnell-Filter."""

    @pytest.fixture
    def tracker(self):
        ollama = AsyncMock()
        t = IntentTracker(ollama)
        return t

    @pytest.mark.asyncio
    async def test_short_text_skipped(self, tracker):
        result = await tracker.extract_intents("Hallo du")
        assert result == []

    @pytest.mark.asyncio
    async def test_no_time_keywords_skipped(self, tracker):
        """Text ohne Zeitangaben wird uebersprungen."""
        result = await tracker.extract_intents("Wie wird das Wetter in Berlin sein dieses Jahr?")
        assert result == []

    @pytest.mark.asyncio
    async def test_text_with_time_keyword_calls_llm(self, tracker):
        """Text mit Zeitangabe geht an das LLM."""
        tracker.ollama.chat.return_value = {
            "message": {"content": "[]"},
        }
        result = await tracker.extract_intents(
            "Meine Eltern kommen morgen zu Besuch und bleiben eine Woche"
        )
        tracker.ollama.chat.assert_called_once()
        assert result == []


class TestTrackIntent:
    """Tests fuer track_intent() — Redis-Speicherung."""

    @pytest.fixture
    def tracker(self):
        ollama = AsyncMock()
        t = IntentTracker(ollama)
        t.redis = AsyncMock()
        return t

    @pytest.mark.asyncio
    async def test_stores_intent(self, tracker):
        intent = {"intent": "Besuch", "deadline": "2026-03-01"}
        result = await tracker.track_intent(intent)
        assert result is True
        tracker.redis.hset.assert_called_once()
        tracker.redis.sadd.assert_called_once()
        tracker.redis.expire.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_redis_returns_false(self, tracker):
        tracker.redis = None
        result = await tracker.track_intent({"intent": "Test"})
        assert result is False


class TestDismissIntent:
    """Tests fuer dismiss_intent()."""

    @pytest.fixture
    def tracker(self):
        ollama = AsyncMock()
        t = IntentTracker(ollama)
        t.redis = AsyncMock()
        return t

    @pytest.mark.asyncio
    async def test_dismiss_marks_and_removes(self, tracker):
        result = await tracker.dismiss_intent("intent_123")
        assert result is True
        tracker.redis.hset.assert_called_once()
        tracker.redis.srem.assert_called_once()

    @pytest.mark.asyncio
    async def test_dismiss_no_redis(self, tracker):
        tracker.redis = None
        result = await tracker.dismiss_intent("intent_123")
        assert result is False
