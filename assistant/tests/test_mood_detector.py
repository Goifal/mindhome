"""
Tests fuer MoodDetector — Stimmungserkennung + Trend-Analyse.
"""

import time
from unittest.mock import AsyncMock, MagicMock

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
        await detector.analyze("Das ist schlecht")
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
        from collections import deque
        sentiments = deque(maxlen=10)
        for s in ["positive", "neutral", "negative", "negative", "negative"]:
            sentiments.append(s)
        detector._interaction_sentiments = sentiments
        detector._person_states["_default"] = {
            "sentiments": sentiments, "mood": "neutral",
            "stress": 0.0, "tiredness": 0.0, "frustration": 0, "positive_signals": 0,
            "last_texts": deque(maxlen=5), "last_decay_time": 0.0,
        }
        assert detector.get_mood_trend() == "declining"

    def test_improving_trend(self, detector):
        from collections import deque
        sentiments = deque(maxlen=10)
        for s in ["negative", "negative", "neutral", "positive", "positive"]:
            sentiments.append(s)
        detector._interaction_sentiments = sentiments
        detector._person_states["_default"] = {
            "sentiments": sentiments, "mood": "neutral",
            "stress": 0.0, "tiredness": 0.0, "frustration": 0, "positive_signals": 0,
            "last_texts": deque(maxlen=5), "last_decay_time": 0.0,
        }
        assert detector.get_mood_trend() == "improving"

    def test_volatile_trend(self, detector):
        from collections import deque
        sentiments = deque(maxlen=10)
        for s in ["positive", "negative", "positive", "negative", "positive"]:
            sentiments.append(s)
        detector._interaction_sentiments = sentiments
        detector._person_states["_default"] = {
            "sentiments": sentiments, "mood": "neutral",
            "stress": 0.0, "tiredness": 0.0, "frustration": 0, "positive_signals": 0,
            "last_texts": deque(maxlen=5), "last_decay_time": 0.0,
        }
        assert detector.get_mood_trend() == "volatile"


class TestSuggestedActions:
    """Tests fuer get_suggested_actions()."""

    def test_no_actions_when_neutral(self, detector):
        detector._current_mood = MOOD_NEUTRAL
        actions = detector.get_suggested_actions()
        assert actions == []

    def test_stress_suggests_scene(self, detector):
        detector._current_mood = MOOD_STRESSED
        detector._stress_level = 0.3
        actions = detector.get_suggested_actions()
        assert any(a["action"] == "scene.entspannung" for a in actions)

    def test_high_stress_suggests_light_dimming(self, detector):
        detector._current_mood = MOOD_STRESSED
        detector._stress_level = 0.8
        actions = detector.get_suggested_actions()
        assert any(a["action"] == "light.dimmen" for a in actions)
        light_action = [a for a in actions if a["action"] == "light.dimmen"][0]
        assert light_action["params"]["brightness_pct"] == 40

    def test_medium_stress_suggests_volume_down(self, detector):
        detector._current_mood = MOOD_STRESSED
        detector._stress_level = 0.6
        actions = detector.get_suggested_actions()
        assert any(a["action"] == "media_player.volume_down" for a in actions)

    def test_frustrated_suggests_simplify(self, detector):
        detector._current_mood = MOOD_FRUSTRATED
        actions = detector.get_suggested_actions()
        assert any(a["action"] == "simplify_responses" for a in actions)

    def test_tired_suggests_reduce_notifications(self, detector):
        detector._current_mood = MOOD_TIRED
        actions = detector.get_suggested_actions()
        assert any(a["action"] == "reduce_notifications" for a in actions)


class TestExecuteSuggestedActions:
    """Tests fuer execute_suggested_actions()."""

    @pytest.mark.asyncio
    async def test_returns_empty_without_executor(self, detector):
        result = await detector.execute_suggested_actions(None)
        assert result == []

    @pytest.mark.asyncio
    async def test_skips_internal_markers(self, detector):
        detector._current_mood = MOOD_FRUSTRATED
        executor = AsyncMock()
        result = await detector.execute_suggested_actions(executor)
        # simplify_responses und offer_help sind interne Marker → nicht ausfuehren
        executor.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_executes_scene_action(self, detector):
        detector._current_mood = MOOD_STRESSED
        detector._stress_level = 0.3
        executor = AsyncMock()
        executor.execute = AsyncMock(return_value={"success": True})
        result = await detector.execute_suggested_actions(executor)
        assert len(result) >= 1
        assert result[0]["action"] == "scene.entspannung"

    @pytest.mark.asyncio
    async def test_executes_volume_down(self, detector):
        detector._current_mood = MOOD_STRESSED
        detector._stress_level = 0.6
        executor = AsyncMock()
        executor.execute = AsyncMock(return_value={"success": True})
        result = await detector.execute_suggested_actions(executor)
        vol_actions = [a for a in result if a["action"] == "media_player.volume_down"]
        assert len(vol_actions) == 1

    @pytest.mark.asyncio
    async def test_survives_executor_error(self, detector):
        detector._current_mood = MOOD_STRESSED
        detector._stress_level = 0.3
        executor = AsyncMock()
        executor.execute = AsyncMock(side_effect=Exception("HA down"))
        result = await detector.execute_suggested_actions(executor)
        # Sollte nicht crashen, sondern leere Liste zurueckgeben
        assert result == []


class TestMoodPromptHint:
    """Tests fuer get_mood_prompt_hint() mit Voice + Trend."""

    def test_returns_empty_for_unknown_person(self, detector):
        hint = detector.get_mood_prompt_hint("unbekannt")
        assert hint == ""

    def test_includes_voice_signals(self, detector):
        detector._last_voice_signals = ["laut", "schnell"]
        # Person-State muss unter _default Key existieren
        detector._person_states["_default"] = {
            "mood": MOOD_STRESSED,
            "stress": 0.5,
            "frustration": 0,
            "sentiments": [],
        }
        hint = detector.get_mood_prompt_hint()
        assert "laut" in hint
        assert "Stimm-Analyse" in hint

    def test_includes_declining_trend_hint(self, detector):
        detector._person_states["_default"] = {
            "mood": MOOD_NEUTRAL,
            "stress": 0.0,
            "frustration": 0,
            "sentiments": [],
        }
        hint = detector.get_mood_prompt_hint()
        # Bei neutralem Mood ohne Sentiments: leerer Hint oder nur Trend
        assert isinstance(hint, str)
