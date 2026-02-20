"""
Tests fuer MoodDetector — Stimmungserkennung + Trend-Analyse.
"""

import time
from unittest.mock import AsyncMock

import pytest

from assistant.mood_detector import (
    MOOD_FRUSTRATED,
    MOOD_GOOD,
    MOOD_NEUTRAL,
    MOOD_STRESSED,
    MOOD_TIRED,
    MoodDetector,
)


@pytest.fixture
def detector():
    d = MoodDetector()
    d.redis = AsyncMock()
    return d


class TestDetermineMood:
    """Tests fuer _determine_mood()."""

    def test_neutral_by_default(self, detector):
        assert detector._determine_mood() == MOOD_NEUTRAL

    def test_tired_when_tiredness_high(self, detector):
        detector._tiredness_level = 0.7
        assert detector._determine_mood() == MOOD_TIRED

    def test_frustrated_after_threshold(self, detector):
        detector._frustration_count = 4
        assert detector._determine_mood() == MOOD_FRUSTRATED

    def test_stressed_when_stress_high(self, detector):
        detector._stress_level = 0.6
        assert detector._determine_mood() == MOOD_STRESSED

    def test_good_with_positive_signals(self, detector):
        detector._positive_count = 3
        detector._frustration_count = 0
        assert detector._determine_mood() == MOOD_GOOD

    def test_rapid_commands_trigger_stress(self, detector):
        """5 kurze Befehle in <60s = stressed."""
        now = time.time()
        for i in range(5):
            detector._interaction_times.append(now - 50 + i * 10)
            detector._interaction_lengths.append(2)  # Kurze Befehle
        assert detector._determine_mood() == MOOD_STRESSED


class TestAnalyze:
    """Tests fuer analyze()."""

    @pytest.mark.asyncio
    async def test_positive_language_reduces_stress(self, detector):
        detector._stress_level = 0.3
        result = await detector.analyze("Danke, super gemacht!")
        assert "positive_language" in result["signals"]
        assert detector._stress_level < 0.3

    @pytest.mark.asyncio
    async def test_negative_language_increases_frustration(self, detector):
        result = await detector.analyze("Das stimmt nicht, falsch!")
        assert "negative_language" in result["signals"]
        assert detector._frustration_count > 0

    @pytest.mark.asyncio
    async def test_impatient_keywords_boost_stress(self, detector):
        result = await detector.analyze("Mach schon, sofort!")
        assert "impatient_language" in result["signals"]
        assert detector._stress_level > 0

    @pytest.mark.asyncio
    async def test_repetition_detection(self, detector):
        await detector.analyze("Licht an")
        result = await detector.analyze("Licht an")
        assert "repetition" in result["signals"]

    @pytest.mark.asyncio
    async def test_sentiment_tracking(self, detector):
        """Sentiments werden in _interaction_sentiments aufgezeichnet."""
        await detector.analyze("Danke!")
        await detector.analyze("Hallo")
        await detector.analyze("Das nervt")
        sentiments = list(detector._interaction_sentiments)
        assert sentiments[0] == "positive"
        assert sentiments[1] == "neutral"
        assert sentiments[2] == "negative"


class TestMoodTrend:
    """Tests fuer get_mood_trend()."""

    def test_stable_with_few_sentiments(self, detector):
        detector._interaction_sentiments.append("neutral")
        assert detector.get_mood_trend() == "stable"

    def test_declining_trend(self, detector):
        for s in ["positive", "neutral", "negative", "negative", "negative"]:
            detector._interaction_sentiments.append(s)
        assert detector.get_mood_trend() == "declining"

    def test_improving_trend(self, detector):
        for s in ["negative", "negative", "neutral", "positive", "positive"]:
            detector._interaction_sentiments.append(s)
        assert detector.get_mood_trend() == "improving"

    def test_volatile_trend(self, detector):
        for s in ["positive", "negative", "positive", "negative", "positive"]:
            detector._interaction_sentiments.append(s)
        assert detector.get_mood_trend() == "volatile"
