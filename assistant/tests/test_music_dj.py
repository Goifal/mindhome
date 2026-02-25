"""
Tests fuer Feature 11: Smart DJ (kontextbewusste Musikempfehlungen).
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from assistant.music_dj import MusicDJ, GENRE_QUERIES, GENRE_LABELS, _get_time_of_day


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def mood_mock():
    """MoodDetector Mock."""
    mock = MagicMock()
    mock.get_current_mood = MagicMock(return_value={
        "mood": "neutral",
        "stress_level": 0.0,
        "tiredness_level": 0.0,
        "frustration_count": 0,
        "positive_count": 0,
    })
    return mock


@pytest.fixture
def activity_mock():
    """ActivityEngine Mock."""
    mock = AsyncMock()
    mock.detect_activity = AsyncMock(return_value={
        "activity": "relaxing",
        "confidence": 0.8,
    })
    return mock


@pytest.fixture
def dj(mood_mock, activity_mock, redis_mock):
    """MusicDJ Instanz mit Mocks."""
    d = MusicDJ(mood_mock, activity_mock)
    d.redis = redis_mock
    d.enabled = True
    d._config = {
        "enabled": True,
        "default_volume": 40,
        "suppress_during": ["sleeping", "in_call"],
        "custom_queries": {},
    }
    return d


# ============================================================
# TestBuildMusicContext
# ============================================================

class TestBuildMusicContext:
    """Tests fuer _build_music_context()."""

    def test_returns_mood(self, dj, mood_mock):
        """Context enthaelt aktuelle Stimmung."""
        mood_mock.get_current_mood.return_value = {"mood": "good", "stress_level": 0.1, "tiredness_level": 0.0}
        ctx = dj._build_music_context()
        assert ctx["mood"] == "good"

    def test_returns_stress(self, dj, mood_mock):
        """Context enthaelt Stress-Level."""
        mood_mock.get_current_mood.return_value = {"mood": "stressed", "stress_level": 0.7, "tiredness_level": 0.0}
        ctx = dj._build_music_context()
        assert ctx["stress_level"] == 0.7

    def test_returns_time_of_day(self, dj):
        """Context enthaelt Tageszeit."""
        ctx = dj._build_music_context()
        assert ctx["time_of_day"] in ("morning", "afternoon", "evening", "night")

    def test_returns_tiredness(self, dj, mood_mock):
        """Context enthaelt Muedigkeits-Level."""
        mood_mock.get_current_mood.return_value = {"mood": "tired", "stress_level": 0.0, "tiredness_level": 0.8}
        ctx = dj._build_music_context()
        assert ctx["tiredness_level"] == 0.8


# ============================================================
# TestContextToGenre
# ============================================================

class TestContextToGenre:
    """Tests fuer _context_to_genre()."""

    def test_frustrated_returns_comfort(self, dj):
        """Frustration → comfort_classics."""
        ctx = {"mood": "frustrated", "stress_level": 0.0, "tiredness_level": 0.0, "time_of_day": "afternoon"}
        assert dj._context_to_genre(ctx, "relaxing") == "comfort_classics"

    def test_stressed_focused_returns_focus_calm(self, dj):
        """Stress + fokussiert → focus_calm."""
        ctx = {"mood": "stressed", "stress_level": 0.7, "tiredness_level": 0.0, "time_of_day": "afternoon"}
        assert dj._context_to_genre(ctx, "focused") == "focus_calm"

    def test_stressed_relaxing_returns_meditation(self, dj):
        """Stress + entspannt → meditation."""
        ctx = {"mood": "stressed", "stress_level": 0.7, "tiredness_level": 0.0, "time_of_day": "evening"}
        assert dj._context_to_genre(ctx, "relaxing") == "meditation"

    def test_good_evening_returns_chill(self, dj):
        """Gute Stimmung am Abend → chill_evening."""
        ctx = {"mood": "good", "stress_level": 0.0, "tiredness_level": 0.0, "time_of_day": "evening"}
        assert dj._context_to_genre(ctx, "relaxing") == "chill_evening"

    def test_good_guests_returns_party(self, dj):
        """Gute Stimmung + Gaeste → party_hits."""
        ctx = {"mood": "good", "stress_level": 0.0, "tiredness_level": 0.0, "time_of_day": "evening"}
        assert dj._context_to_genre(ctx, "guests") == "party_hits"

    def test_neutral_focused_returns_lofi(self, dj):
        """Neutral + fokussiert → focus_lofi."""
        ctx = {"mood": "neutral", "stress_level": 0.0, "tiredness_level": 0.0, "time_of_day": "afternoon"}
        assert dj._context_to_genre(ctx, "focused") == "focus_lofi"

    def test_tired_evening_returns_sleep(self, dj):
        """Muede am Abend → sleep_ambient."""
        ctx = {"mood": "tired", "stress_level": 0.0, "tiredness_level": 0.8, "time_of_day": "evening"}
        assert dj._context_to_genre(ctx, "relaxing") == "sleep_ambient"

    def test_tired_morning_returns_energize(self, dj):
        """Muede am Morgen → energize_morning."""
        ctx = {"mood": "tired", "stress_level": 0.0, "tiredness_level": 0.6, "time_of_day": "morning"}
        assert dj._context_to_genre(ctx, "relaxing") == "energize_morning"


# ============================================================
# TestSuppressConditions
# ============================================================

class TestSuppressConditions:
    """Tests fuer Situationen ohne Musikempfehlung."""

    def test_sleeping_suppressed(self, dj):
        """Sleeping → keine Empfehlung."""
        ctx = {"mood": "neutral", "stress_level": 0.0, "tiredness_level": 0.0, "time_of_day": "night"}
        assert dj._context_to_genre(ctx, "sleeping") is None

    def test_in_call_suppressed(self, dj):
        """Im Telefonat → keine Empfehlung."""
        ctx = {"mood": "neutral", "stress_level": 0.0, "tiredness_level": 0.0, "time_of_day": "afternoon"}
        assert dj._context_to_genre(ctx, "in_call") is None

    def test_watching_suppressed(self, dj):
        """Film schauen → keine Empfehlung."""
        ctx = {"mood": "good", "stress_level": 0.0, "tiredness_level": 0.0, "time_of_day": "evening"}
        assert dj._context_to_genre(ctx, "watching") is None

    def test_disabled_returns_error(self, dj):
        """DJ deaktiviert → Fehlermeldung."""
        dj.enabled = False
        # get_recommendation ist async, testen wir in der async-Klasse
        assert dj.enabled is False


# ============================================================
# TestGenreToQuery
# ============================================================

class TestGenreToQuery:
    """Tests fuer _genre_to_query()."""

    def test_known_genre(self, dj):
        """Bekanntes Genre → passender Query."""
        assert "lofi" in dj._genre_to_query("focus_lofi").lower()

    def test_unknown_genre_fallback(self, dj):
        """Unbekanntes Genre → Fallback-Query."""
        assert dj._genre_to_query("unknown_genre") == "chill music"

    def test_custom_query_override(self, dj):
        """Custom-Query aus Config hat Vorrang."""
        dj._config["custom_queries"] = {"party_hits": "meine party playlist"}
        assert dj._genre_to_query("party_hits") == "meine party playlist"


# ============================================================
# TestGetRecommendation
# ============================================================

class TestGetRecommendation:
    """Tests fuer get_recommendation()."""

    @pytest.mark.asyncio
    async def test_basic_recommendation(self, dj, mood_mock):
        """Grundlegende Empfehlung wird generiert."""
        mood_mock.get_current_mood.return_value = {"mood": "good", "stress_level": 0.0, "tiredness_level": 0.0}
        result = await dj.get_recommendation(person="Max")
        assert result["success"] is True
        assert result["genre"] is not None
        assert result["query"] is not None
        assert result["label"] is not None

    @pytest.mark.asyncio
    async def test_recommendation_has_reason(self, dj):
        """Empfehlung enthaelt Begruendung."""
        result = await dj.get_recommendation()
        assert result["success"] is True
        assert "reason" in result

    @pytest.mark.asyncio
    async def test_suppressed_activity(self, dj, activity_mock):
        """Bei sleeping: genre ist None."""
        activity_mock.detect_activity.return_value = {"activity": "sleeping", "confidence": 0.9}
        result = await dj.get_recommendation()
        assert result["success"] is True
        assert result["genre"] is None

    @pytest.mark.asyncio
    async def test_disabled_dj(self, dj):
        """Deaktivierter DJ gibt Fehlermeldung."""
        dj.enabled = False
        result = await dj.get_recommendation()
        assert result["success"] is False
        assert "deaktiviert" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_saves_to_redis(self, dj, redis_mock):
        """Empfehlung wird in Redis gespeichert."""
        result = await dj.get_recommendation(person="Max")
        assert result["success"] is True
        redis_mock.setex.assert_called()
        key = redis_mock.setex.call_args[0][0]
        assert "music_dj" in key


# ============================================================
# TestPlayRecommendation
# ============================================================

class TestPlayRecommendation:
    """Tests fuer play_recommendation()."""

    @pytest.fixture
    def dj_with_executor(self, dj):
        """DJ mit Executor-Mock."""
        executor = AsyncMock()
        executor.execute = AsyncMock(return_value={"success": True, "message": "OK"})
        dj.executor = executor
        return dj

    @pytest.mark.asyncio
    async def test_play_calls_executor(self, dj_with_executor, mood_mock):
        """Play ruft Executor mit play_media auf."""
        mood_mock.get_current_mood.return_value = {"mood": "good", "stress_level": 0.0, "tiredness_level": 0.0}
        result = await dj_with_executor.play_recommendation(person="Max")
        assert result["success"] is True
        dj_with_executor.executor.execute.assert_called()
        first_call = dj_with_executor.executor.execute.call_args_list[0]
        assert first_call[0][0] == "play_media"

    @pytest.mark.asyncio
    async def test_play_with_room(self, dj_with_executor, mood_mock):
        """Room wird an Executor uebergeben."""
        mood_mock.get_current_mood.return_value = {"mood": "neutral", "stress_level": 0.0, "tiredness_level": 0.0}
        result = await dj_with_executor.play_recommendation(person="Max", room="wohnzimmer")
        assert result["success"] is True
        first_call = dj_with_executor.executor.execute.call_args_list[0]
        assert first_call[0][1].get("room") == "wohnzimmer"

    @pytest.mark.asyncio
    async def test_play_genre_override(self, dj_with_executor):
        """Genre-Override wird benutzt."""
        result = await dj_with_executor.play_recommendation(person="Max", genre_override="jazz_dinner")
        assert result["success"] is True
        assert result["genre"] == "jazz_dinner"

    @pytest.mark.asyncio
    async def test_play_no_executor(self, dj):
        """Ohne Executor → Fehlermeldung."""
        dj.executor = None
        result = await dj.play_recommendation(person="Max")
        assert result["success"] is False
        assert "Executor" in result["message"]

    @pytest.mark.asyncio
    async def test_play_sets_volume(self, dj_with_executor, mood_mock):
        """Default-Volume wird gesetzt."""
        mood_mock.get_current_mood.return_value = {"mood": "neutral", "stress_level": 0.0, "tiredness_level": 0.0}
        dj_with_executor._config["default_volume"] = 40
        result = await dj_with_executor.play_recommendation(person="Max")
        assert result["success"] is True
        # Zwei Aufrufe: play + volume
        assert dj_with_executor.executor.execute.call_count == 2


# ============================================================
# TestRecordFeedback
# ============================================================

class TestRecordFeedback:
    """Tests fuer record_feedback()."""

    @pytest.mark.asyncio
    async def test_positive_feedback(self, dj, redis_mock):
        """Positives Feedback wird gespeichert."""
        redis_mock.get = AsyncMock(return_value=json.dumps({
            "genre": "focus_lofi", "query": "test", "label": "Lo-Fi", "person": "Max",
        }).encode())
        redis_mock.hincrby = AsyncMock(return_value=1)
        result = await dj.record_feedback(positive=True, person="Max")
        assert result["success"] is True
        assert "gefaellt" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_negative_feedback(self, dj, redis_mock):
        """Negatives Feedback wird gespeichert."""
        redis_mock.get = AsyncMock(return_value=json.dumps({
            "genre": "party_hits", "query": "test", "label": "Party", "person": "Max",
        }).encode())
        redis_mock.hincrby = AsyncMock(return_value=-1)
        result = await dj.record_feedback(positive=False, person="Max")
        assert result["success"] is True
        assert "nicht dein Ding" in result["message"]

    @pytest.mark.asyncio
    async def test_negative_blocks_at_threshold(self, dj, redis_mock):
        """Bei -3 wird Genre blockiert."""
        redis_mock.get = AsyncMock(return_value=json.dumps({
            "genre": "party_hits", "query": "test", "label": "Party", "person": "Max",
        }).encode())
        redis_mock.hincrby = AsyncMock(return_value=-3)
        result = await dj.record_feedback(positive=False, person="Max")
        assert "vermieden" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_no_last_recommendation(self, dj, redis_mock):
        """Ohne letzte Empfehlung → Fehlermeldung."""
        redis_mock.get = AsyncMock(return_value=None)
        result = await dj.record_feedback(positive=True, person="Max")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_no_redis(self, dj):
        """Ohne Redis → Fehlermeldung."""
        dj.redis = None
        result = await dj.record_feedback(positive=True)
        assert result["success"] is False


# ============================================================
# TestApplyPreferences
# ============================================================

class TestApplyPreferences:
    """Tests fuer _apply_preferences()."""

    @pytest.mark.asyncio
    async def test_no_preference_keeps_genre(self, dj, redis_mock):
        """Ohne Praeferenz bleibt Genre unveraendert."""
        redis_mock.hget = AsyncMock(return_value=None)
        result = await dj._apply_preferences("focus_lofi", "Max")
        assert result == "focus_lofi"

    @pytest.mark.asyncio
    async def test_blocked_genre_switches(self, dj, redis_mock):
        """Blockiertes Genre (-3) wechselt zu Fallback."""
        redis_mock.hget = AsyncMock(return_value=b"-3")
        result = await dj._apply_preferences("focus_lofi", "Max")
        assert result != "focus_lofi"

    @pytest.mark.asyncio
    async def test_no_person_skips_check(self, dj):
        """Ohne Person wird Praeferenz-Check uebersprungen."""
        result = await dj._apply_preferences("focus_lofi", "")
        assert result == "focus_lofi"


# ============================================================
# TestGetMusicStatus
# ============================================================

class TestGetMusicStatus:
    """Tests fuer get_music_status()."""

    @pytest.mark.asyncio
    async def test_status_structure(self, dj):
        """Status hat erwartete Felder."""
        result = await dj.get_music_status()
        assert result["success"] is True
        assert "enabled" in result
        assert "current_context" in result
        assert "suggested_genre" in result

    @pytest.mark.asyncio
    async def test_status_includes_activity(self, dj):
        """Status enthaelt Aktivitaet."""
        result = await dj.get_music_status()
        assert "activity" in result["current_context"]


# ============================================================
# TestGetTimeOfDay
# ============================================================

class TestGetTimeOfDay:
    """Tests fuer _get_time_of_day()."""

    def test_morning(self):
        with patch("assistant.music_dj.datetime") as mock_dt:
            mock_dt.now.return_value = MagicMock(hour=8)
            assert _get_time_of_day() == "morning"

    def test_afternoon(self):
        with patch("assistant.music_dj.datetime") as mock_dt:
            mock_dt.now.return_value = MagicMock(hour=14)
            assert _get_time_of_day() == "afternoon"

    def test_evening(self):
        with patch("assistant.music_dj.datetime") as mock_dt:
            mock_dt.now.return_value = MagicMock(hour=20)
            assert _get_time_of_day() == "evening"

    def test_night(self):
        with patch("assistant.music_dj.datetime") as mock_dt:
            mock_dt.now.return_value = MagicMock(hour=2)
            assert _get_time_of_day() == "night"
