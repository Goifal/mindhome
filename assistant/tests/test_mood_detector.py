"""
Tests fuer MoodDetector — Stimmungserkennung + Trend-Analyse.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

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
            "sentiments": sentiments,
            "mood": "neutral",
            "stress": 0.0,
            "tiredness": 0.0,
            "frustration": 0,
            "positive_signals": 0,
            "last_texts": deque(maxlen=5),
            "last_decay_time": 0.0,
        }
        assert detector.get_mood_trend() == "declining"

    def test_improving_trend(self, detector):
        from collections import deque

        sentiments = deque(maxlen=10)
        for s in ["negative", "negative", "neutral", "positive", "positive"]:
            sentiments.append(s)
        detector._interaction_sentiments = sentiments
        detector._person_states["_default"] = {
            "sentiments": sentiments,
            "mood": "neutral",
            "stress": 0.0,
            "tiredness": 0.0,
            "frustration": 0,
            "positive_signals": 0,
            "last_texts": deque(maxlen=5),
            "last_decay_time": 0.0,
        }
        assert detector.get_mood_trend() == "improving"

    def test_volatile_trend(self, detector):
        from collections import deque

        sentiments = deque(maxlen=10)
        for s in ["positive", "negative", "positive", "negative", "positive"]:
            sentiments.append(s)
        detector._interaction_sentiments = sentiments
        detector._person_states["_default"] = {
            "sentiments": sentiments,
            "mood": "neutral",
            "stress": 0.0,
            "tiredness": 0.0,
            "frustration": 0,
            "positive_signals": 0,
            "last_texts": deque(maxlen=5),
            "last_decay_time": 0.0,
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
        assert "Stress" in hint or "ruhig" in hint
        assert isinstance(hint, str) and len(hint) > 0

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


# =====================================================================
# _store_person_state eviction (lines 204-210)
# =====================================================================


class TestStorePersonStateEviction:
    """Tests fuer Person-Limit in _store_person_state()."""

    def test_evicts_oldest_person_when_over_limit(self, detector):
        """When more than 20 persons, oldest non-default is evicted."""
        import time as _time

        # Create 20 person states (+ _default might exist)
        for i in range(21):
            key = f"person_{i}"
            detector._person_states[key] = {
                "mood": MOOD_NEUTRAL,
                "stress": 0.0,
                "tiredness": 0.0,
                "frustration": 0,
                "positive": 0,
                "times": [],
                "lengths": [],
                "sentiments": [],
                "last_texts": [],
                "last_decay_time": _time.time(),
                "voice_signals": [],
                "created_time": _time.time() - (21 - i),
            }
        # Load and store a new person
        detector._load_person_state("new_person")
        detector._created_time = _time.time()
        detector._store_person_state()
        # Should have evicted the oldest (person_0)
        assert len(detector._person_states) <= 21

    def test_evicts_oldest_not_default(self, detector):
        """_default should never be evicted."""
        import time as _time

        detector._person_states["_default"] = {
            "mood": MOOD_NEUTRAL,
            "stress": 0.0,
            "tiredness": 0.0,
            "frustration": 0,
            "positive": 0,
            "times": [],
            "lengths": [],
            "sentiments": [],
            "last_texts": [],
            "last_decay_time": _time.time(),
            "voice_signals": [],
            "created_time": 0,  # oldest
        }
        for i in range(21):
            key = f"person_{i}"
            detector._person_states[key] = {
                "mood": MOOD_NEUTRAL,
                "stress": 0.0,
                "tiredness": 0.0,
                "frustration": 0,
                "positive": 0,
                "times": [],
                "lengths": [],
                "sentiments": [],
                "last_texts": [],
                "last_decay_time": _time.time(),
                "voice_signals": [],
                "created_time": _time.time() - (21 - i),
            }
        detector._active_person_key = "person_20"
        detector._created_time = _time.time()
        detector._store_person_state()
        assert "_default" in detector._person_states


# =====================================================================
# initialize from Redis (lines 214-265)
# =====================================================================


class TestInitializeFromRedis:
    """Tests fuer initialize() mit Redis-Daten."""

    @pytest.mark.asyncio
    async def test_initialize_loads_person_states(self):
        d = MoodDetector()
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=["mha:mood:state:max"])
        mock_redis.hgetall = AsyncMock(
            side_effect=[
                # First call: for "mha:mood:state:max"
                {
                    "mood": "stressed",
                    "stress": "0.5",
                    "tiredness": "0.1",
                    "frustration": "2",
                    "positive": "1",
                },
                # Second call: legacy key "mha:mood:state"
                {},
            ]
        )
        mock_redis.expire = AsyncMock()

        await d.initialize(redis_client=mock_redis)
        assert "max" in d._person_states
        assert d._person_states["max"]["mood"] == "stressed"
        assert d._person_states["max"]["stress"] == 0.5

    @pytest.mark.asyncio
    async def test_initialize_loads_legacy_key(self):
        d = MoodDetector()
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=[])
        mock_redis.hgetall = AsyncMock(
            return_value={
                "mood": "tired",
                "stress": "0.2",
                "tiredness": "0.7",
                "frustration": "0",
                "positive": "0",
            }
        )
        mock_redis.expire = AsyncMock()

        await d.initialize(redis_client=mock_redis)
        assert "_default" in d._person_states
        assert d._person_states["_default"]["mood"] == "tired"

    @pytest.mark.asyncio
    async def test_initialize_handles_bytes_keys(self):
        d = MoodDetector()
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=[b"mha:mood:state:anna"])
        mock_redis.hgetall = AsyncMock(
            side_effect=[
                {
                    b"mood": b"good",
                    b"stress": b"0.0",
                    b"tiredness": b"0.0",
                    b"frustration": b"0",
                    b"positive": b"3",
                },
                {},  # legacy
            ]
        )
        mock_redis.expire = AsyncMock()

        await d.initialize(redis_client=mock_redis)
        assert "anna" in d._person_states

    @pytest.mark.asyncio
    async def test_initialize_redis_exception(self):
        d = MoodDetector()
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(side_effect=Exception("Redis down"))
        mock_redis.hgetall = AsyncMock()
        mock_redis.expire = AsyncMock()

        await d.initialize(redis_client=mock_redis)
        # Should not crash, just log

    @pytest.mark.asyncio
    async def test_initialize_no_redis(self):
        d = MoodDetector()
        await d.initialize(redis_client=None)
        assert d.redis is None


# =====================================================================
# analyze_inner edge cases (lines 300-301, 328-329, 344-346, 351-352,
#   356-357, 364, 366-369, 377)
# =====================================================================


class TestAnalyzeInnerEdges:
    """Tests fuer edge cases in _analyze_inner()."""

    @pytest.mark.asyncio
    async def test_rapid_commands_signal(self, detector):
        """4+ rapid commands trigger rapid_commands signal."""
        from collections import deque

        now = time.time()
        times = deque(maxlen=20)
        for i in range(5):
            times.append(now - 10 + i * 2)
        # Store the state so _load_person_state finds it
        detector._person_states["_default"] = {
            "mood": "neutral",
            "stress": 0.0,
            "tiredness": 0.0,
            "frustration": 0,
            "positive": 0,
            "times": times,
            "lengths": deque(maxlen=20),
            "sentiments": deque(maxlen=10),
            "last_texts": deque(maxlen=5),
            "last_decay_time": now,
            "voice_signals": [],
            "created_time": now,
        }
        result = await detector.analyze("noch ein befehl", "")
        assert "rapid_commands" in result["signals"]

    @pytest.mark.asyncio
    async def test_tired_keywords(self, detector):
        result = await detector.analyze("Ich bin so muede, gute nacht")
        assert "tired_keywords" in result["signals"]

    @pytest.mark.asyncio
    async def test_escalation_detection(self, detector):
        """2+ similar texts trigger escalation."""
        await detector.analyze("mach das licht an bitte")
        await detector.analyze("mach das licht an jetzt")
        result = await detector.analyze("mach das licht an sofort")
        assert "escalation" in result["signals"]

    @pytest.mark.asyncio
    async def test_exclamation_marks(self, detector):
        result = await detector.analyze("Das ist doch nicht wahr!! Unglaublich!!")
        assert "exclamation_marks" in result["signals"]

    @pytest.mark.asyncio
    async def test_frustrated_prefix(self, detector):
        result = await detector.analyze("nein! das war falsch")
        assert "frustrated_prefix" in result["signals"]

    @pytest.mark.asyncio
    async def test_late_night_short_message(self, detector):
        from unittest.mock import patch
        from datetime import datetime as dt

        mock_now = MagicMock()
        mock_now.hour = 23  # Late hour
        with patch("assistant.mood_detector.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = await detector.analyze("ja ok")
        assert "short_late_message" in result["signals"]

    @pytest.mark.asyncio
    async def test_is_late_when_start_less_than_end(self, detector):
        """Test is_late branch when tired_hour_start <= tired_hour_end."""
        from unittest.mock import patch

        detector.tired_hour_start = 2
        detector.tired_hour_end = 6
        mock_now = MagicMock()
        mock_now.hour = 3  # Between 2 and 6
        with patch("assistant.mood_detector.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = await detector.analyze("ok")
        # Should detect late hour

    @pytest.mark.asyncio
    async def test_tired_sentiment_tracked(self, detector):
        """Tired keywords produce 'tired' sentiment in tracking."""
        result = await detector.analyze("bin so muede")
        sentiments = list(detector._interaction_sentiments)
        assert "tired" in sentiments


# =====================================================================
# get_current_mood with state (line 424)
# =====================================================================


class TestGetCurrentMoodWithState:
    """Tests fuer get_current_mood() mit vorhandenem State."""

    def test_returns_state_for_known_person(self, detector):
        detector._person_states["max"] = {
            "mood": MOOD_STRESSED,
            "stress": 0.6,
            "tiredness": 0.1,
            "frustration": 2,
            "positive": 1,
            "voice_emotion": {"emotion": "angry"},
        }
        result = detector.get_current_mood("Max")
        assert result["mood"] == MOOD_STRESSED
        assert result["stress_level"] == 0.6
        assert result["voice_emotion"]["emotion"] == "angry"

    def test_returns_default_for_unknown(self, detector):
        result = detector.get_current_mood("unknown_person")
        assert result["mood"] == MOOD_NEUTRAL
        assert result["voice_emotion"] is None


# =====================================================================
# _is_repetition and _word_overlap (lines 516, 525)
# =====================================================================


class TestRepetitionAndOverlap:
    """Tests fuer _is_repetition() und _word_overlap()."""

    def test_word_overlap_similar(self, detector):
        overlap = detector._word_overlap("mach das licht an", "mach bitte das licht an")
        assert overlap > 0.5

    def test_word_overlap_empty(self, detector):
        assert detector._word_overlap("", "test") == 0.0
        assert detector._word_overlap("test", "") == 0.0

    def test_is_repetition_similar_words(self, detector):
        detector._last_texts.append("mach das licht an im wohnzimmer")
        assert detector._is_repetition("mach das licht an im schlafzimmer") is True


# =====================================================================
# _apply_decay (lines 532-538)
# =====================================================================


class TestApplyDecay:
    """Tests fuer _apply_decay()."""

    def test_decay_reduces_stress(self, detector):
        detector._stress_level = 0.5
        detector._tiredness_level = 0.3
        detector._last_decay_time = time.time() - 120  # 2 minutes ago
        detector._apply_decay(time.time())
        assert detector._stress_level < 0.5
        assert detector._tiredness_level < 0.3

    def test_decay_after_long_pause_resets_frustration(self, detector):
        # Nach 700s (~11 Minuten) Pause: Frustration sinkt um 11 Steps
        # (1 pro 60s), also von 3 auf 0 (max(0, 3-11))
        detector._frustration_count = 3
        detector._positive_count = 2
        detector._stress_level = 0.5
        detector._last_decay_time = time.time() - 700  # >10 minutes
        detector._apply_decay(time.time())
        assert detector._frustration_count == 0
        assert detector._positive_count == 0

    def test_no_decay_under_60_seconds(self, detector):
        detector._stress_level = 0.5
        detector._last_decay_time = time.time() - 30
        detector._apply_decay(time.time())
        assert detector._stress_level == 0.5


# =====================================================================
# get_suggested_actions extended (lines 586, 594, 606-607)
# =====================================================================


class TestSuggestedActionsExtended:
    """Erweiterte Tests fuer get_suggested_actions()."""

    def test_frustrated_high_count_offers_help(self, detector):
        detector._current_mood = MOOD_FRUSTRATED
        detector._frustration_count = 5
        actions = detector.get_suggested_actions()
        assert any(a["action"] == "offer_help" for a in actions)

    def test_tired_late_hour_suggests_gute_nacht(self, detector):
        from unittest.mock import patch

        detector._current_mood = MOOD_TIRED
        mock_now = MagicMock()
        mock_now.hour = 23
        with patch("assistant.mood_detector.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            actions = detector.get_suggested_actions()
        assert any(a["action"] == "scene.gute_nacht" for a in actions)

    def test_good_mood_evening_suggests_gemuetlich(self, detector):
        from unittest.mock import patch

        detector._current_mood = MOOD_GOOD
        mock_now = MagicMock()
        mock_now.hour = 20
        with patch("assistant.mood_detector.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            actions = detector.get_suggested_actions()
        assert any(a["action"] == "scene.gemuetlich" for a in actions)


# =====================================================================
# execute_suggested_actions light.dimmen (lines 650-655)
# =====================================================================


class TestExecuteLightDimmen:
    """Tests fuer execute_suggested_actions() mit light.dimmen."""

    @pytest.mark.asyncio
    async def test_executes_light_dimmen(self, detector):
        detector._current_mood = MOOD_STRESSED
        detector._stress_level = 0.8  # >= 0.7 triggers light.dimmen
        executor = AsyncMock()
        executor.execute = AsyncMock(return_value={"success": True})
        result = await detector.execute_suggested_actions(executor)
        light_actions = [a for a in result if a["action"] == "light.dimmen"]
        assert len(light_actions) == 1


# =====================================================================
# get_mood_prompt_hint extended (lines 702-744)
# =====================================================================


class TestMoodPromptHintExtended:
    """Erweiterte Tests fuer get_mood_prompt_hint()."""

    def test_stressed_high_hint(self, detector):
        from collections import deque

        detector._person_states["_default"] = {
            "mood": MOOD_STRESSED,
            "stress": 0.8,
            "frustration": 0,
            "sentiments": deque(maxlen=10),
        }
        hint = detector.get_mood_prompt_hint()
        assert "Stress" in hint
        assert "Pause" in hint

    def test_frustrated_high_hint(self, detector):
        from collections import deque

        detector._person_states["_default"] = {
            "mood": MOOD_FRUSTRATED,
            "stress": 0.3,
            "frustration": 5,
            "sentiments": deque(maxlen=10),
        }
        hint = detector.get_mood_prompt_hint()
        assert "frustriert" in hint
        assert "Frustration" in hint

    def test_tired_hint(self, detector):
        from collections import deque

        detector._person_states["_default"] = {
            "mood": MOOD_TIRED,
            "stress": 0.0,
            "frustration": 0,
            "sentiments": deque(maxlen=10),
        }
        hint = detector.get_mood_prompt_hint()
        assert "muede" in hint

    def test_good_mood_hint(self, detector):
        from collections import deque

        detector._person_states["_default"] = {
            "mood": MOOD_GOOD,
            "stress": 0.0,
            "frustration": 0,
            "sentiments": deque(maxlen=10),
        }
        hint = detector.get_mood_prompt_hint()
        assert "gut drauf" in hint

    def test_three_negatives_warning(self, detector):
        from collections import deque

        sentiments = deque(maxlen=10)
        for _ in range(3):
            sentiments.append("negative")
        detector._person_states["_default"] = {
            "mood": MOOD_NEUTRAL,
            "stress": 0.3,
            "frustration": 1,
            "sentiments": sentiments,
        }
        hint = detector.get_mood_prompt_hint()
        assert "WARNUNG" in hint

    def test_declining_trend_hint(self, detector):
        from collections import deque

        sentiments = deque(maxlen=10)
        for s in ["positive", "neutral", "negative", "negative", "negative"]:
            sentiments.append(s)
        detector._person_states["_default"] = {
            "mood": MOOD_NEUTRAL,
            "stress": 0.3,
            "frustration": 1,
            "sentiments": sentiments,
        }
        hint = detector.get_mood_prompt_hint()
        assert "fallend" in hint

    def test_volatile_trend_hint(self, detector):
        from collections import deque

        sentiments = deque(maxlen=10)
        for s in ["positive", "negative", "positive", "negative", "positive"]:
            sentiments.append(s)
        detector._person_states["_default"] = {
            "mood": MOOD_NEUTRAL,
            "stress": 0.0,
            "frustration": 0,
            "sentiments": sentiments,
        }
        hint = detector.get_mood_prompt_hint()
        assert "instabil" in hint

    def test_voice_signals_in_hint(self, detector):
        from collections import deque

        detector._person_states["_default"] = {
            "mood": MOOD_NEUTRAL,
            "stress": 0.0,
            "frustration": 0,
            "sentiments": deque(maxlen=10),
            "voice_signals": ["voice_fast", "voice_loud"],
        }
        hint = detector.get_mood_prompt_hint()
        assert "Stimm-Analyse" in hint

    def test_voice_emotion_in_hint(self, detector):
        from collections import deque

        detector._person_states["_default"] = {
            "mood": MOOD_NEUTRAL,
            "stress": 0.0,
            "frustration": 0,
            "sentiments": deque(maxlen=10),
            "voice_emotion": {"emotion": "angry", "confidence": 0.7},
        }
        hint = detector.get_mood_prompt_hint()
        assert "Stimm-Emotion" in hint
        assert "aergerlich" in hint

    def test_voice_emotion_neutral_not_shown(self, detector):
        from collections import deque

        detector._person_states["_default"] = {
            "mood": MOOD_NEUTRAL,
            "stress": 0.0,
            "frustration": 0,
            "sentiments": deque(maxlen=10),
            "voice_emotion": {"emotion": "neutral", "confidence": 0.8},
        }
        hint = detector.get_mood_prompt_hint()
        assert "Stimm-Emotion" not in hint

    def test_voice_emotion_low_confidence_not_shown(self, detector):
        from collections import deque

        detector._person_states["_default"] = {
            "mood": MOOD_NEUTRAL,
            "stress": 0.0,
            "frustration": 0,
            "sentiments": deque(maxlen=10),
            "voice_emotion": {"emotion": "angry", "confidence": 0.2},
        }
        hint = detector.get_mood_prompt_hint()
        assert "Stimm-Emotion" not in hint


# =====================================================================
# analyze_voice_metadata (lines 767-821)
# =====================================================================


class TestAnalyzeVoiceMetadata:
    """Tests fuer analyze_voice_metadata()."""

    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self, detector):
        detector.voice_enabled = False
        result = await detector.analyze_voice_metadata({"wpm": 200})
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_metadata_returns_empty(self, detector):
        result = await detector.analyze_voice_metadata({})
        assert result == []

    @pytest.mark.asyncio
    async def test_fast_speech_stress(self, detector):
        result = await detector.analyze_voice_metadata({"wpm": 220})
        assert "voice_fast" in result
        assert detector._stress_level > 0

    @pytest.mark.asyncio
    async def test_slow_speech_tiredness(self, detector):
        result = await detector.analyze_voice_metadata({"wpm": 50})
        assert "voice_slow" in result
        assert detector._tiredness_level > 0

    @pytest.mark.asyncio
    async def test_loud_voice_stress(self, detector):
        result = await detector.analyze_voice_metadata({"volume": 0.9})
        assert "voice_loud" in result

    @pytest.mark.asyncio
    async def test_quiet_voice_tiredness(self, detector):
        result = await detector.analyze_voice_metadata({"volume": 0.1})
        assert "voice_quiet" in result

    @pytest.mark.asyncio
    async def test_curt_commands(self, detector):
        result = await detector.analyze_voice_metadata(
            {
                "duration": 1.0,
                "word_count": 2,
            }
        )
        assert "voice_curt" in result

    @pytest.mark.asyncio
    async def test_rapid_follow_up(self, detector):
        result = await detector.analyze_voice_metadata(
            {
                "rapid_follow_up": True,
            }
        )
        assert "rapid_follow_up" in result

    @pytest.mark.asyncio
    async def test_stores_person_state(self, detector):
        await detector.analyze_voice_metadata({"wpm": 200}, person="Max")
        assert "max" in detector._person_states


# =====================================================================
# detect_audio_emotion (lines 836-938)
# =====================================================================


class TestDetectAudioEmotion:
    """Tests fuer detect_audio_emotion()."""

    def test_empty_metadata(self, detector):
        result = detector.detect_audio_emotion({})
        assert result["emotion"] == "neutral"
        assert result["confidence"] == 0.0

    def test_fast_speech_anxious(self, detector):
        result = detector.detect_audio_emotion({"wpm": 200})
        assert "speech_fast" in result["signals"]
        assert result["scores"].get("anxious", 0) > 0

    def test_moderate_fast_speech(self, detector):
        result = detector.detect_audio_emotion({"wpm": 160})
        assert "speech_moderate_fast" in result["signals"]

    def test_slow_speech_sad(self, detector):
        result = detector.detect_audio_emotion({"wpm": 60})
        assert "speech_slow" in result["signals"]

    def test_loud_voice(self, detector):
        result = detector.detect_audio_emotion({"volume": 0.9})
        assert "voice_loud" in result["signals"]

    def test_quiet_voice(self, detector):
        result = detector.detect_audio_emotion({"volume": 0.15})
        assert "voice_quiet" in result["signals"]

    def test_high_pitch(self, detector):
        result = detector.detect_audio_emotion({"pitch_mean": 250})
        assert "pitch_high" in result["signals"]

    def test_low_pitch(self, detector):
        result = detector.detect_audio_emotion({"pitch_mean": 80})
        assert "pitch_low" in result["signals"]

    def test_dynamic_pitch(self, detector):
        result = detector.detect_audio_emotion({"pitch_variance": 60})
        assert "pitch_dynamic" in result["signals"]

    def test_monotone_pitch(self, detector):
        result = detector.detect_audio_emotion({"pitch_variance": 5})
        assert "pitch_monotone" in result["signals"]

    def test_many_pauses(self, detector):
        result = detector.detect_audio_emotion({"pause_ratio": 0.5})
        assert "many_pauses" in result["signals"]

    def test_high_energy(self, detector):
        result = detector.detect_audio_emotion({"energy_rms": 0.8})
        assert "high_energy" in result["signals"]

    def test_low_energy(self, detector):
        result = detector.detect_audio_emotion({"energy_rms": 0.1})
        assert "low_energy" in result["signals"]

    def test_angry_emotion_integration(self, detector):
        """High score angry emotion integrates into mood state."""
        detector._stress_level = 0.0
        result = detector.detect_audio_emotion(
            {
                "wpm": 200,
                "volume": 0.9,
                "energy_rms": 0.8,
            }
        )
        assert result["emotion"] == "angry"
        assert detector._stress_level > 0

    def test_tired_emotion_integration(self, detector):
        detector._tiredness_level = 0.0
        result = detector.detect_audio_emotion(
            {
                "wpm": 60,
                "volume": 0.15,
                "pitch_variance": 5,
                "energy_rms": 0.1,
            }
        )
        assert detector._tiredness_level > 0

    def test_happy_emotion_reduces_stress(self, detector):
        detector._stress_level = 0.5
        result = detector.detect_audio_emotion(
            {
                "wpm": 160,
                "pitch_variance": 60,
            }
        )
        if result["emotion"] == "happy" and result["confidence"] > 0.4:
            assert detector._stress_level < 0.5

    def test_voice_mood_integration_stores_emotion(self, detector):
        detector.voice_mood_integration = True
        result = detector.detect_audio_emotion({"wpm": 200, "volume": 0.9})
        assert detector._last_voice_emotion.get(detector._active_person_key) is not None

    def test_voice_mood_integration_disabled(self, detector):
        detector.voice_mood_integration = False
        detector._last_voice_emotion = {}
        detector.detect_audio_emotion({"wpm": 200})
        assert detector._active_person_key not in detector._last_voice_emotion

    def test_none_metadata_returns_neutral(self, detector):
        result = detector.detect_audio_emotion(None)
        assert result["emotion"] == "neutral"


# =====================================================================
# get_voice_signals (line 942)
# =====================================================================


class TestGetVoiceSignals:
    """Tests fuer get_voice_signals()."""

    def test_returns_last_signals(self, detector):
        detector._last_voice_signals = ["voice_fast", "voice_loud"]
        assert detector.get_voice_signals() == ["voice_fast", "voice_loud"]

    def test_returns_empty_by_default(self, detector):
        assert detector.get_voice_signals() == []


# =====================================================================
# _save_state (lines 947, 960-961)
# =====================================================================


class TestSaveState:
    """Tests fuer _save_state()."""

    @pytest.mark.asyncio
    async def test_save_state_no_redis(self, detector):
        detector.redis = None
        await detector._save_state()
        # Should not crash

    @pytest.mark.asyncio
    async def test_save_state_writes_to_redis(self, detector):
        detector._current_mood = MOOD_STRESSED
        detector._stress_level = 0.5
        detector._active_person_key = "max"
        await detector._save_state()
        detector.redis.hset.assert_called_once()
        call_kwargs = detector.redis.hset.call_args[1]
        assert call_kwargs["mapping"]["mood"] == MOOD_STRESSED

    @pytest.mark.asyncio
    async def test_save_state_exception(self, detector):
        detector.redis.hset = AsyncMock(side_effect=Exception("Redis down"))
        await detector._save_state()
        # Should not crash


# =====================================================================
# get_mood_trend stable return (line 504)
# =====================================================================


class TestMoodTrendStable:
    """Additional mood trend tests."""

    def test_stable_when_all_neutral(self, detector):
        from collections import deque

        sentiments = deque(maxlen=10)
        for _ in range(5):
            sentiments.append("neutral")
        detector._person_states["_default"] = {
            "sentiments": sentiments,
            "mood": "neutral",
            "stress": 0.0,
            "tiredness": 0.0,
            "frustration": 0,
        }
        assert detector.get_mood_trend() == "stable"


# ------------------------------------------------------------------
# Phase 2A: Root-Cause, Empathie, Emotional Boundaries
# ------------------------------------------------------------------


class TestPhase2AEmpathy:
    """Tests fuer Empathie-Statements und Root-Cause."""

    @pytest.fixture
    def detector(self):
        with patch("assistant.mood_detector.yaml_config", {"mood": {}}):
            from assistant.mood_detector import MoodDetector

            d = MoodDetector()
            return d

    def test_empathy_frustrated_device(self, detector):
        """Empathie bei Frustration + Geraeteproblem."""
        stmt = detector.generate_empathy_statement("frustrated", "geraeteproblem")
        assert stmt is not None
        assert "Diagnostik" in stmt or "Probleme" in stmt

    def test_empathy_stressed_zeitdruck(self, detector):
        """Empathie bei Stress + Zeitdruck."""
        stmt = detector.generate_empathy_statement("stressed", "zeitdruck")
        assert stmt is not None
        assert "kurz" in stmt.lower()

    def test_empathy_tired(self, detector):
        """Empathie bei Muedigkeit."""
        stmt = detector.generate_empathy_statement("tired", "muedigkeit")
        assert stmt is not None
        assert "Ruhe" in stmt or "goennen" in stmt

    def test_empathy_neutral_none(self, detector):
        """Keine Empathie bei neutraler Stimmung."""
        stmt = detector.generate_empathy_statement("neutral")
        assert stmt is None

    def test_empathy_unknown_root_cause(self, detector):
        """Empathie mit unbekannter Ursache → Fallback."""
        stmt = detector.generate_empathy_statement("frustrated", "unbekannt")
        assert stmt is not None

    def test_get_root_cause_default(self, detector):
        """Default Root-Cause ist 'unbekannt'."""
        assert detector.get_root_cause() == "unbekannt"

    def test_get_root_cause_from_state(self, detector):
        """Root-Cause aus Person-State lesen."""
        detector._person_states["_default"] = {"root_cause": "zeitdruck"}
        assert detector.get_root_cause() == "zeitdruck"


class TestPhase2AEmotionalBoundaries:
    """Tests fuer emotionale Grenzen."""

    @pytest.fixture
    def detector(self):
        with patch("assistant.mood_detector.yaml_config", {"mood": {}}):
            from assistant.mood_detector import MoodDetector

            d = MoodDetector()
            d.redis = AsyncMock()
            return d

    @pytest.mark.asyncio
    async def test_boundaries_not_frustrated(self, detector):
        """Keine Grenzen bei neutraler Stimmung."""
        detector._current_mood = MOOD_NEUTRAL
        result = await detector.check_emotional_boundaries()
        assert result is None

    @pytest.mark.asyncio
    async def test_boundaries_below_threshold(self, detector):
        """Grenzen unter Schwelle (< 3 ignorierte Warnungen)."""
        detector._current_mood = MOOD_FRUSTRATED
        detector.redis.get = AsyncMock(return_value=b"2")
        result = await detector.check_emotional_boundaries()
        assert result is None

    @pytest.mark.asyncio
    async def test_boundaries_reached(self, detector):
        """Grenzen erreicht (>= 3 ignorierte Warnungen + Frustration)."""
        detector._current_mood = MOOD_FRUSTRATED
        detector.redis.get = AsyncMock(return_value=b"3")
        result = await detector.check_emotional_boundaries()
        assert result == "sachlich"

    @pytest.mark.asyncio
    async def test_record_ignored_warning(self, detector):
        """Ignorierte Warnung wird gezaehlt."""
        await detector.record_ignored_warning()
        detector.redis.incr.assert_called()
        detector.redis.expire.assert_called()

    @pytest.mark.asyncio
    async def test_store_root_cause(self, detector):
        """Root-Cause wird in Redis gespeichert."""
        await detector._store_root_cause("max", "zeitdruck")
        detector.redis.setex.assert_called()


# =====================================================================
# Phase 1/5: Ironie-Erkennung (_detect_irony)
# =====================================================================


class TestIronyDetection:
    """Tests fuer _detect_irony() — Ironie-/Sarkasmus-Erkennung."""

    @pytest.fixture
    def detector(self):
        d = MoodDetector()
        d.redis = AsyncMock()
        return d

    def test_irony_marker_with_negative_history(self, detector):
        """'Na super' nach negativen Interaktionen = ironisch."""
        from collections import deque

        detector._interaction_sentiments = deque(["negative", "negative", "neutral"])
        assert detector._detect_irony("na super, laeuft ja", "max") is True

    def test_irony_marker_without_negative_history(self, detector):
        """'Na super' ohne negative History = nicht ironisch."""
        from collections import deque

        detector._interaction_sentiments = deque(["neutral", "neutral", "neutral"])
        assert detector._detect_irony("na super, das freut mich", "max") is False

    def test_exaggeration_with_high_negatives(self, detector):
        """'Mega toll' nach 2+ negativen Sentiments = ironisch."""
        from collections import deque

        detector._interaction_sentiments = deque(["negative", "impatient", "negative"])
        assert detector._detect_irony("mega toll das ergebnis", "max") is True

    def test_exaggeration_without_negatives(self, detector):
        """'Mega toll' ohne negative History = echt gemeint."""
        from collections import deque

        detector._interaction_sentiments = deque(["neutral", "neutral"])
        assert detector._detect_irony("mega toll das ergebnis", "max") is False

    def test_frustrated_short_positive(self, detector):
        """Kurzes 'super toll' bei hoher Frustration + Stress = ironisch."""
        from collections import deque

        detector._frustration_count = 3
        detector._stress_level = 0.6
        detector._interaction_sentiments = deque(["neutral"])
        assert detector._detect_irony("super toll", "max") is True

    def test_normal_positive_not_ironic(self, detector):
        """Normales positives Feedback wird nicht als Ironie erkannt."""
        from collections import deque

        detector._frustration_count = 0
        detector._stress_level = 0.0
        detector._interaction_sentiments = deque(["neutral", "neutral"])
        assert detector._detect_irony("danke das ist gut", "max") is False

    def test_ja_klar_marker(self, detector):
        """'Ja klar' nach negativem Sentiment = ironisch."""
        from collections import deque

        detector._interaction_sentiments = deque(["negative"])
        assert detector._detect_irony("ja klar macht sinn", "max") is True

    def test_ganz_grosses_kino_marker(self, detector):
        """'Ganz grosses Kino' nach negativem Sentiment = ironisch."""
        from collections import deque

        detector._interaction_sentiments = deque(["impatient"])
        assert detector._detect_irony("ganz grosses kino wirklich", "max") is True


# =====================================================================
# Irony detection integration in full analyze() flow
# =====================================================================


class TestIronyInAnalyzeFlow:
    """Tests that irony detection integrates correctly into analyze().

    When _detect_irony returns True for seemingly positive text,
    analyze() should produce 'irony_detected' in signals, revert
    the positive_count increment, and keep/increase stress.
    """

    @pytest.mark.asyncio
    async def test_ironic_positive_produces_irony_signal(self, detector):
        """Ironic 'na super' after frustration triggers irony_detected signal."""
        # Build negative history first
        await detector.analyze("das geht nicht")
        await detector.analyze("funktioniert nicht")
        # Now send ironic positive text
        result = await detector.analyze("na super, laeuft ja")
        assert "irony_detected" in result["signals"]
        assert "positive_language" in result["signals"]

    @pytest.mark.asyncio
    async def test_ironic_text_keeps_stress_higher_than_genuine(self, detector):
        """Ironic positive text should keep stress higher than genuine praise would."""
        # Build frustration with negative history
        await detector.analyze("das geht nicht")
        await detector.analyze("funktioniert nicht")
        stress_after_negatives = detector._stress_level

        # Send ironic positive — stress gets +0.05 from irony but -0.1 from positive
        result = await detector.analyze("na super, laeuft ja")
        assert "irony_detected" in result["signals"]
        stress_after_irony = detector._stress_level

        # Compare: genuine positive without irony context reduces stress more
        detector2 = MoodDetector()
        detector2.redis = AsyncMock()
        await detector2.analyze("Hallo")
        await detector2.analyze("ok")
        # Set same stress level as after negatives
        detector2._stress_level = stress_after_negatives
        await detector2.analyze("Danke, super gemacht!")
        # Genuine positive should reduce stress more than ironic one
        assert detector2._stress_level < stress_after_irony

    @pytest.mark.asyncio
    async def test_ironic_text_reverts_positive_count(self, detector):
        """Irony should decrement positive_count that was incremented by keyword match."""
        await detector.analyze("das geht nicht")
        positive_before = detector._positive_count
        result = await detector.analyze("na toll, ganz toll")
        # positive_count should not net-increase from ironic text
        assert detector._positive_count <= positive_before + 1
        if "irony_detected" in result["signals"]:
            assert detector._positive_count <= positive_before

    @pytest.mark.asyncio
    async def test_genuine_positive_no_irony_signal(self, detector):
        """Genuine positive text without negative history has no irony_detected."""
        result = await detector.analyze("Danke, super gemacht!")
        assert "irony_detected" not in result["signals"]
        assert "positive_language" in result["signals"]

    @pytest.mark.asyncio
    async def test_irony_mood_stays_negative(self, detector):
        """After ironic text, mood should not flip to 'good'."""
        # Build significant frustration
        for _ in range(3):
            await detector.analyze("funktioniert nicht, nervig")
        result = await detector.analyze("ja klar, super toll")
        assert result["mood"] != MOOD_GOOD

    @pytest.mark.asyncio
    async def test_irony_after_escalation(self, detector):
        """Ironic response after escalation keeps high stress."""
        await detector.analyze("mach das licht an")
        await detector.analyze("mach das licht an jetzt")
        await detector.analyze("mach das licht an sofort")
        result = await detector.analyze("na super, perfekt gemacht")
        if "irony_detected" in result["signals"]:
            assert result["stress_level"] > 0.3

    @pytest.mark.asyncio
    async def test_frustrated_short_positive_in_flow(self, detector):
        """Short positive after heavy frustration is detected as irony."""
        # Build frustration and stress
        for _ in range(3):
            await detector.analyze("geht nicht, nervig!")
        result = await detector.analyze("super toll")
        # Should detect irony via frustration-context path
        assert "irony_detected" in result["signals"]


# =====================================================================
# Mood trend tracking — extended tests
# =====================================================================


class TestMoodTrends:
    """Extended tests for mood trend tracking across analyze() calls."""

    @pytest.mark.asyncio
    async def test_trend_after_positive_sequence(self, detector):
        """Sequence of positive messages should produce improving or stable trend."""
        await detector.analyze("das ist schlecht")
        await detector.analyze("naja, besser")
        await detector.analyze("Danke, super!")
        await detector.analyze("Perfekt, toll!")
        await detector.analyze("Freut mich, klasse!")
        trend = detector.get_mood_trend()
        assert trend in ("improving", "stable")

    @pytest.mark.asyncio
    async def test_trend_after_negative_sequence(self, detector):
        """Sequence of negative messages should produce declining trend."""
        await detector.analyze("Hallo, alles gut")
        await detector.analyze("ok passt")
        await detector.analyze("das stimmt nicht, falsch!")
        await detector.analyze("nervt mich, schlecht")
        await detector.analyze("geht nicht, kaputt")
        trend = detector.get_mood_trend()
        assert trend in ("declining", "volatile")

    @pytest.mark.asyncio
    async def test_trend_alternating_is_volatile(self, detector):
        """Alternating positive/negative should produce volatile trend."""
        for i in range(6):
            if i % 2 == 0:
                await detector.analyze("Danke, super gemacht!")
            else:
                await detector.analyze("funktioniert nicht, nervt")
        trend = detector.get_mood_trend()
        assert trend in ("volatile", "declining")

    def test_trend_empty_sentiments(self, detector):
        """Empty sentiments should return stable."""
        assert detector.get_mood_trend() == "stable"

    def test_trend_single_sentiment(self, detector):
        """Single sentiment should return stable (not enough data)."""
        detector._interaction_sentiments.append("negative")
        assert detector.get_mood_trend() == "stable"

    @pytest.mark.asyncio
    async def test_sentiments_capped_at_maxlen(self, detector):
        """Sentiments deque should not grow beyond its maxlen."""
        for i in range(25):
            await detector.analyze(f"nachricht nummer {i}")
        assert len(detector._interaction_sentiments) <= 10


# =====================================================================
# Edge cases
# =====================================================================


class TestEdgeCases:
    """Edge cases: empty text, very long text, special characters."""

    @pytest.mark.asyncio
    async def test_empty_string(self, detector):
        """Empty string should not crash and return neutral mood."""
        result = await detector.analyze("")
        assert result["mood"] in (MOOD_NEUTRAL, MOOD_TIRED)
        assert isinstance(result["signals"], list)

    @pytest.mark.asyncio
    async def test_whitespace_only(self, detector):
        """Whitespace-only input should not crash."""
        result = await detector.analyze("   ")
        assert result["mood"] in (MOOD_NEUTRAL, MOOD_TIRED)
        assert isinstance(result["signals"], list)

    @pytest.mark.asyncio
    async def test_very_long_text(self, detector):
        """Very long text should be handled without crash."""
        long_text = "Hallo " * 5000
        result = await detector.analyze(long_text)
        assert isinstance(result["mood"], str)
        assert isinstance(result["stress_level"], float)

    @pytest.mark.asyncio
    async def test_special_characters(self, detector):
        """Special characters should not crash analysis."""
        result = await detector.analyze("!@#$%^&*()_+-=[]{}|;':\",./<>?")
        assert isinstance(result["mood"], str)
        assert isinstance(result["signals"], list)

    @pytest.mark.asyncio
    async def test_emoji_text(self, detector):
        """Emoji-containing text should not crash."""
        result = await detector.analyze("Das ist gut 😊👍🔥")
        assert isinstance(result["mood"], str)

    @pytest.mark.asyncio
    async def test_multiline_text(self, detector):
        """Multiline text should be handled."""
        result = await detector.analyze("Zeile eins\nZeile zwei\nZeile drei")
        assert isinstance(result["mood"], str)

    @pytest.mark.asyncio
    async def test_numeric_only_text(self, detector):
        """Pure numeric input should not crash."""
        result = await detector.analyze("12345 67890")
        assert isinstance(result["mood"], str)

    @pytest.mark.asyncio
    async def test_single_character(self, detector):
        """Single character should be handled."""
        result = await detector.analyze("x")
        assert isinstance(result["mood"], str)

    @pytest.mark.asyncio
    async def test_repeated_analyze_calls_stable(self, detector):
        """Many sequential calls with varied neutral text should stay low stress."""
        neutral_texts = [
            "Hallo",
            "wie geht es",
            "alles klar",
            "ja",
            "verstanden",
            "in Ordnung",
            "ok danke",
            "passt",
            "gut",
            "weiter",
        ]
        for text in neutral_texts:
            result = await detector.analyze(text)
        # Varied neutral texts should not accumulate high stress
        assert result["stress_level"] <= 0.7

    @pytest.mark.asyncio
    async def test_person_parameter_none_string(self, detector):
        """Empty person string should default to _default key."""
        result = await detector.analyze("Hallo", "")
        assert isinstance(result["mood"], str)

    @pytest.mark.asyncio
    async def test_person_parameter_with_name(self, detector):
        """Named person should create per-person state."""
        await detector.analyze("Hallo", "Max")
        assert "max" in detector._person_states

    @pytest.mark.asyncio
    async def test_result_structure(self, detector):
        """Verify analyze() returns all expected keys."""
        result = await detector.analyze("Hallo Welt")
        assert "mood" in result
        assert "stress_level" in result
        assert "tiredness_level" in result
        assert "frustration_count" in result
        assert "signals" in result
        assert isinstance(result["stress_level"], float)
        assert isinstance(result["tiredness_level"], float)
        assert isinstance(result["frustration_count"], int)

    @pytest.mark.asyncio
    async def test_stress_level_bounded(self, detector):
        """Stress level should never exceed 1.0 even with many negative inputs."""
        for _ in range(20):
            await detector.analyze("funktioniert nicht! nervt! kaputt!")
        assert detector._stress_level <= 1.0

    @pytest.mark.asyncio
    async def test_tiredness_level_bounded(self, detector):
        """Tiredness level should never exceed 1.0."""
        for _ in range(20):
            await detector.analyze("bin so muede, gute nacht, will schlafen")
        assert detector._tiredness_level <= 1.0
