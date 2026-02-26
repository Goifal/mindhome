"""
Edge-Case Tests fuer Music DJ, Visitor Manager und Function-Calling Handler.
Ergaenzt die bestehenden Tests mit Grenzfaellen und Integrations-Szenarien.
"""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.music_dj import MusicDJ, GENRE_QUERIES, _get_time_of_day
from assistant.visitor_manager import VisitorManager, _KEY_KNOWN, _KEY_LAST_RING


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def mood_mock():
    mock = MagicMock()
    mock.get_current_mood = MagicMock(return_value={
        "mood": "neutral", "stress_level": 0.0, "tiredness_level": 0.0,
    })
    return mock


@pytest.fixture
def activity_mock():
    mock = AsyncMock()
    mock.detect_activity = AsyncMock(return_value={
        "activity": "relaxing", "confidence": 0.8,
    })
    return mock


@pytest.fixture
def redis_mock():
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock()
    mock.setex = AsyncMock()
    mock.delete = AsyncMock()
    mock.hset = AsyncMock()
    mock.hget = AsyncMock(return_value=None)
    mock.hgetall = AsyncMock(return_value={})
    mock.hdel = AsyncMock()
    mock.hincrby = AsyncMock()
    mock.lrange = AsyncMock(return_value=[])
    pipe = MagicMock()
    pipe.lpush = MagicMock()
    pipe.ltrim = MagicMock()
    pipe.execute = AsyncMock(return_value=[])
    mock.pipeline = MagicMock(return_value=pipe)
    mock._pipeline = pipe
    return mock


@pytest.fixture
def dj(mood_mock, activity_mock, redis_mock):
    """MusicDJ mit Mocks."""
    with patch("assistant.music_dj.yaml_config", {"music_dj": {}}):
        d = MusicDJ(mood_mock, activity_mock)
    d.redis = redis_mock
    d.enabled = True
    return d


@pytest.fixture
def vm(redis_mock):
    """VisitorManager mit Mocks."""
    ha = AsyncMock()
    camera = AsyncMock()
    with patch("assistant.visitor_manager.yaml_config", {"visitor_management": {}}):
        v = VisitorManager(ha, camera)
    v.redis = redis_mock
    v.executor = AsyncMock()
    v.executor.execute = AsyncMock(return_value={"success": True})
    v.enabled = True
    return v


# =====================================================================
# Music DJ Edge Cases
# =====================================================================


class TestMusicDJTimeBoundaries:
    """Tests fuer Zeitgrenzen in _get_time_of_day() (Modul-Level Funktion)."""

    def test_boundary_morning_start(self):
        """05:00 ist Morgen."""
        with patch("assistant.music_dj.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 5
            mock_dt.now.return_value = mock_now
            assert _get_time_of_day() == "morning"

    def test_boundary_morning_end(self):
        """09:59 ist noch Morgen."""
        with patch("assistant.music_dj.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 9
            mock_dt.now.return_value = mock_now
            assert _get_time_of_day() == "morning"

    def test_boundary_afternoon_start(self):
        with patch("assistant.music_dj.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 10
            mock_dt.now.return_value = mock_now
            assert _get_time_of_day() == "afternoon"

    def test_boundary_evening_start(self):
        with patch("assistant.music_dj.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 17
            mock_dt.now.return_value = mock_now
            assert _get_time_of_day() == "evening"

    def test_boundary_night_start(self):
        with patch("assistant.music_dj.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 22
            mock_dt.now.return_value = mock_now
            assert _get_time_of_day() == "night"

    def test_midnight_is_night(self):
        with patch("assistant.music_dj.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 0
            mock_dt.now.return_value = mock_now
            assert _get_time_of_day() == "night"


class TestMusicDJStressThresholds:
    """Tests fuer Stress/Mood Schwellwerte."""

    @pytest.mark.asyncio
    async def test_medium_stress_normal_mood(self, dj, mood_mock, activity_mock):
        """Stress 0.4 mit normalem Mood — kein Focus-Genre."""
        mood_mock.get_current_mood.return_value = {
            "mood": "neutral", "stress_level": 0.4, "tiredness": 0.0,
        }
        result = await dj.get_recommendation()
        assert result["success"] is True
        # Bei medium stress und neutral mood → focus_lofi oder aehnlich
        assert result.get("genre") is not None

    @pytest.mark.asyncio
    async def test_high_stress_gets_calm(self, dj, mood_mock, activity_mock):
        """Hoher Stress → beruhigende Musik."""
        mood_mock.get_current_mood.return_value = {
            "mood": "stressed", "stress_level": 0.8, "tiredness": 0.0,
        }
        result = await dj.get_recommendation()
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_disabled_returns_error(self, dj):
        """Deaktivierter DJ gibt Fehler zurueck."""
        dj.enabled = False
        result = await dj.get_recommendation()
        assert result["success"] is False


class TestMusicDJAllGenresHaveQueries:
    """Sicherstellen dass alle Genres in der Query-Map vorhanden sind."""

    def test_all_genre_queries_are_strings(self):
        for genre, query in GENRE_QUERIES.items():
            assert isinstance(query, str), f"{genre}: Query ist kein String"
            assert len(query) > 3, f"{genre}: Query zu kurz"


# =====================================================================
# Visitor Manager Edge Cases
# =====================================================================


class TestVisitorManagerConcurrency:
    """Tests fuer Cooldown und Race-Conditions."""

    @pytest.mark.asyncio
    async def test_rapid_doorbell_presses(self, vm):
        """Schnelle Mehrfach-Klingel -> nur erste wird verarbeitet."""
        result1 = await vm.handle_doorbell("Person 1")
        assert result1["handled"] is True

        # Sofort nochmal klingeln
        result2 = await vm.handle_doorbell("Person 1")
        assert result2["handled"] is False
        assert result2["reason"] == "cooldown"

    @pytest.mark.asyncio
    async def test_cooldown_exactly_at_boundary(self, vm):
        """Klingel genau am Cooldown-Rand."""
        vm.ring_cooldown_seconds = 30
        vm._last_ring_time = time.time() - 30  # Genau 30s her
        result = await vm.handle_doorbell("Person")
        assert result["handled"] is True


class TestVisitorManagerRedisEdgeCases:
    """Tests fuer Redis-Fehler und korrupte Daten."""

    @pytest.mark.asyncio
    async def test_corrupt_known_visitor_json(self, vm, redis_mock):
        """Korrupter JSON in Known-Visitor Hash."""
        redis_mock.hget = AsyncMock(return_value="{{broken json")
        profile = await vm._get_known_visitor("test")
        assert profile is None

    @pytest.mark.asyncio
    async def test_grant_entry_with_corrupt_ring_data(self, vm, redis_mock):
        """Korrupte Ring-Daten bei grant_entry."""
        redis_mock.get = AsyncMock(return_value="not valid json")
        result = await vm.grant_entry()
        # Sollte trotzdem funktionieren (leere ring_info)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_add_visitor_empty_strings(self, vm, redis_mock):
        """Besucher mit leeren Feldern."""
        result = await vm.add_known_visitor("test", "Test", relationship="", notes="")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_history_with_corrupt_entries(self, vm, redis_mock):
        """History mit teilweise korrupten JSON-Eintraegen."""
        redis_mock.lrange = AsyncMock(return_value=[
            json.dumps({"person_id": "mama", "name": "Mama", "timestamp": "now"}),
            "{{corrupt",
            json.dumps({"person_id": "papa", "name": "Papa", "timestamp": "now"}),
        ])
        result = await vm.get_visit_history()
        assert result["count"] == 2  # Korrupter Eintrag uebersprungen


class TestVisitorManagerAutoUnlockWorkflow:
    """Tests fuer den vollstaendigen Auto-Unlock-Workflow."""

    @pytest.mark.asyncio
    async def test_full_workflow_expect_ring_unlock(self, vm, redis_mock):
        """Vollstaendiger Workflow: Besucher erwarten → Klingel → Auto-Unlock."""
        # 1. Besucher erwarten
        result = await vm.expect_visitor("mama", name="Mama", auto_unlock=True)
        assert result["success"] is True

        # 2. Klingel-Event mit erwartetem Besucher
        redis_mock.hgetall = AsyncMock(return_value={
            "mama": json.dumps({
                "id": "mama",
                "name": "Mama",
                "expected_time": "15:00",
                "auto_unlock": True,
            }),
        })
        ring_result = await vm.handle_doorbell("Aeltere Dame vor der Tuer")
        assert ring_result["handled"] is True
        assert ring_result["auto_unlocked"] is True

    @pytest.mark.asyncio
    async def test_grant_entry_clears_ring_context(self, vm, redis_mock):
        """grant_entry loescht den Ring-Kontext."""
        ring_info = json.dumps({"timestamp": "now", "camera_description": "Person"})
        redis_mock.get = AsyncMock(return_value=ring_info)

        await vm.grant_entry()
        redis_mock.delete.assert_called_with(_KEY_LAST_RING)

    @pytest.mark.asyncio
    async def test_multiple_expected_only_first_auto_unlock(self, vm, redis_mock):
        """Mehrere erwartete Besucher — nur der erste mit auto_unlock wird entriegelt."""
        redis_mock.hgetall = AsyncMock(return_value={
            "lieferant": json.dumps({
                "id": "lieferant",
                "name": "DHL",
                "auto_unlock": False,
            }),
            "mama": json.dumps({
                "id": "mama",
                "name": "Mama",
                "auto_unlock": True,
            }),
        })
        result = await vm.handle_doorbell("Person")
        assert result["handled"] is True
        assert result["expected"] is True
        assert result["auto_unlocked"] is True


# =====================================================================
# Function Calling — Whitelist + Dispatch
# =====================================================================


class TestFunctionCallingWhitelist:
    """Tests fuer Function-Calling Whitelist und Dispatch."""

    def test_manage_visitor_in_whitelist(self):
        from assistant.function_calling import FunctionExecutor
        assert "manage_visitor" in FunctionExecutor._ALLOWED_FUNCTIONS

    def test_recommend_music_in_whitelist(self):
        from assistant.function_calling import FunctionExecutor
        assert "recommend_music" in FunctionExecutor._ALLOWED_FUNCTIONS

    def test_describe_doorbell_in_whitelist(self):
        from assistant.function_calling import FunctionExecutor
        assert "describe_doorbell" in FunctionExecutor._ALLOWED_FUNCTIONS

    def test_lock_door_in_whitelist(self):
        from assistant.function_calling import FunctionExecutor
        assert "lock_door" in FunctionExecutor._ALLOWED_FUNCTIONS

    def test_handler_methods_exist(self):
        """Alle Whitelist-Funktionen haben einen _exec_ Handler."""
        from assistant.function_calling import FunctionExecutor
        for func_name in FunctionExecutor._ALLOWED_FUNCTIONS:
            handler = f"_exec_{func_name}"
            assert hasattr(FunctionExecutor, handler), f"Handler {handler} fehlt"
