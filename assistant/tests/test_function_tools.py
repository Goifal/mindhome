"""
Tests fuer Batch-8 Function-Calling Tools und Stream-Callback.

Testet: get_wellness_status, get_device_health, get_learned_patterns,
describe_doorbell, sowie die Tool-Definitionen in _ASSISTANT_TOOLS_STATIC.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.function_calling import FunctionExecutor, get_assistant_tools

try:
    import assistant.main  # noqa: F401
    _HAS_MAIN = True
except Exception:
    _HAS_MAIN = False

_needs_main = pytest.mark.skipif(
    not _HAS_MAIN, reason="assistant.main nicht importierbar (FastAPI fehlt)"
)


# ---------------------------------------------------------------
# Tool-Definitionen
# ---------------------------------------------------------------


class TestToolDefinitions:
    """Prueft dass alle neuen Tools in der Tool-Liste vorhanden sind."""

    def _tool_names(self):
        tools = get_assistant_tools()
        return [t["function"]["name"] for t in tools]

    def test_get_wellness_status_defined(self):
        assert "get_wellness_status" in self._tool_names()

    def test_get_device_health_defined(self):
        assert "get_device_health" in self._tool_names()

    def test_get_learned_patterns_defined(self):
        assert "get_learned_patterns" in self._tool_names()

    def test_describe_doorbell_defined(self):
        assert "describe_doorbell" in self._tool_names()

    def test_all_tools_have_parameters(self):
        for tool in get_assistant_tools():
            func = tool["function"]
            assert "parameters" in func, f"{func['name']} hat keine parameters"
            assert func["parameters"]["type"] == "object"

    def test_no_duplicate_tool_names(self):
        names = self._tool_names()
        assert len(names) == len(set(names)), f"Duplikate: {[n for n in names if names.count(n) > 1]}"


# ---------------------------------------------------------------
# Executor-Methoden
# ---------------------------------------------------------------


def _make_executor():
    """Erstellt FunctionExecutor mit gemocktem HA-Client."""
    ha = AsyncMock()
    return FunctionExecutor(ha)


def _mock_brain():
    """Erstellt ein Mock-Brain-Objekt fuer die Executor-Tests."""
    brain = MagicMock()
    # Mood
    brain.mood.get_current_mood.return_value = {
        "mood": "gut", "stress_level": 0.2,
    }
    # Memory + Redis
    brain.memory.redis = AsyncMock()
    brain.memory.redis.get = AsyncMock(return_value=None)
    # Activity
    brain.activity.detect_activity = AsyncMock(return_value={"activity": "working"})
    # Device Health
    brain.device_health.get_status = AsyncMock(return_value={"monitored_devices": 15})
    brain.device_health.check_all = AsyncMock(return_value=[])
    # Learning Observer
    brain.learning_observer.get_learned_patterns = AsyncMock(return_value=[])
    # Camera
    brain.camera_manager.describe_doorbell = AsyncMock(return_value="Eine Person mit Paket vor der Tuer")
    return brain


@_needs_main
class TestExecWellnessStatus:
    """Tests fuer _exec_get_wellness_status()."""

    @pytest.mark.asyncio
    async def test_returns_mood(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_get_wellness_status({})
        assert result["success"] is True
        assert result["mood"] == "gut"
        assert result["stress_level"] == 0.2

    @pytest.mark.asyncio
    async def test_includes_activity(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_get_wellness_status({})
        assert result["activity"] == "working"

    @pytest.mark.asyncio
    async def test_no_redis_still_works(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        mock_brain.memory.redis = None
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_get_wellness_status({})
        assert result["success"] is True
        assert result["mood"] == "gut"

    @pytest.mark.asyncio
    async def test_pc_minutes_from_redis(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        from datetime import datetime, timedelta
        start = (datetime.now() - timedelta(minutes=45)).isoformat()
        mock_brain.memory.redis.get = AsyncMock(side_effect=lambda k: start if "pc_start" in k else None)
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_get_wellness_status({})
        assert result["success"] is True
        assert "pc_minutes" in result
        assert 44 <= result["pc_minutes"] <= 46

    @pytest.mark.asyncio
    async def test_error_returns_false(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        mock_brain.mood.get_current_mood.side_effect = RuntimeError("Mood kaputt")
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_get_wellness_status({})
        assert result["success"] is False
        assert "fehlgeschlagen" in result["message"]


@_needs_main
class TestExecDeviceHealth:
    """Tests fuer _exec_get_device_health()."""

    @pytest.mark.asyncio
    async def test_no_alerts(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_get_device_health({})
        assert result["success"] is True
        assert result["message"] == "Alle Geraete normal"
        assert result["alerts"] == []

    @pytest.mark.asyncio
    async def test_with_alerts(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        mock_brain.device_health.check_all = AsyncMock(return_value=[
            {"message": "Sensor Kueche inaktiv seit 2h"},
            {"message": "Heizung Buero ineffizient"},
        ])
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_get_device_health({})
        assert result["success"] is True
        assert "2 Anomalie(n)" in result["message"]
        assert len(result["alerts"]) == 2

    @pytest.mark.asyncio
    async def test_includes_status(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_get_device_health({})
        assert result["monitored_devices"] == 15

    @pytest.mark.asyncio
    async def test_error_returns_false(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        mock_brain.device_health.get_status = AsyncMock(side_effect=ConnectionError("Redis down"))
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_get_device_health({})
        assert result["success"] is False


@_needs_main
class TestExecLearnedPatterns:
    """Tests fuer _exec_get_learned_patterns()."""

    @pytest.mark.asyncio
    async def test_no_patterns(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_get_learned_patterns({})
        assert result["success"] is True
        assert "keine Muster" in result["message"].lower() or result["patterns"] == []

    @pytest.mark.asyncio
    async def test_with_patterns(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        mock_brain.learning_observer.get_learned_patterns = AsyncMock(return_value=[
            {"action": "light.wohnzimmer:off", "time_slot": "22:00-23:00", "count": 12, "weekday": -1},
            {"action": "cover.buero:100", "time_slot": "07:00-08:00", "count": 8, "weekday": 0},
        ])
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_get_learned_patterns({})
        assert result["success"] is True
        assert result["count"] == 2
        assert result["patterns"][0]["action"] == "light.wohnzimmer:off"
        assert result["patterns"][1]["weekday"] == 0

    @pytest.mark.asyncio
    async def test_error_returns_false(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        mock_brain.learning_observer.get_learned_patterns = AsyncMock(side_effect=Exception("fail"))
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_get_learned_patterns({})
        assert result["success"] is False


@_needs_main
class TestExecDescribeDoorbell:
    """Tests fuer _exec_describe_doorbell()."""

    @pytest.mark.asyncio
    async def test_returns_description(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_describe_doorbell({})
        assert result["success"] is True
        assert "Paket" in result["message"]

    @pytest.mark.asyncio
    async def test_no_image_returns_false(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        mock_brain.camera_manager.describe_doorbell = AsyncMock(return_value=None)
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_describe_doorbell({})
        assert result["success"] is False
        assert "nicht verfuegbar" in result["message"]

    @pytest.mark.asyncio
    async def test_empty_string_returns_false(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        mock_brain.camera_manager.describe_doorbell = AsyncMock(return_value="")
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_describe_doorbell({})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_camera_error_returns_false(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        mock_brain.camera_manager.describe_doorbell = AsyncMock(side_effect=TimeoutError("Camera timeout"))
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_describe_doorbell({})
        assert result["success"] is False
        assert "fehlgeschlagen" in result["message"]


# ---------------------------------------------------------------
# Stream-Callback in OllamaClient.stream_chat()
# ---------------------------------------------------------------


class TestStreamChat:
    """Tests fuer stream_chat() async generator."""

    @staticmethod
    def _make_stream_client(chunks, status=200):
        """Erstellt OllamaClient mit gemockter Session fuer Stream-Tests."""
        from assistant.ollama_client import OllamaClient
        client = OllamaClient()

        async def fake_content_iter():
            for chunk in chunks:
                yield chunk

        mock_resp = MagicMock()
        mock_resp.status = status
        mock_resp.content = fake_content_iter()
        mock_resp.text = AsyncMock(return_value="Error")

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_resp)
        cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=cm)

        # _get_session() soll unsere Mock-Session zurueckgeben
        client._get_session = AsyncMock(return_value=mock_session)
        return client

    @pytest.mark.asyncio
    async def test_yields_content_tokens(self):
        """stream_chat() gibt Content-Tokens zurueck."""
        import json as _json

        chunks = [
            _json.dumps({"message": {"content": "Hallo"}, "done": False}).encode() + b"\n",
            _json.dumps({"message": {"content": " Welt"}, "done": False}).encode() + b"\n",
            _json.dumps({"message": {"content": ""}, "done": True}).encode() + b"\n",
        ]

        client = self._make_stream_client(chunks)
        tokens = []
        async for token in client.stream_chat(
            messages=[{"role": "user", "content": "Hi"}],
        ):
            tokens.append(token)

        assert tokens == ["Hallo", " Welt"]

    @pytest.mark.asyncio
    async def test_filters_think_tags(self):
        """stream_chat() filtert <think>-Bloecke."""
        import json as _json

        chunks = [
            _json.dumps({"message": {"content": "<think>"}, "done": False}).encode() + b"\n",
            _json.dumps({"message": {"content": "reasoning"}, "done": False}).encode() + b"\n",
            _json.dumps({"message": {"content": "</think>"}, "done": False}).encode() + b"\n",
            _json.dumps({"message": {"content": "Antwort"}, "done": False}).encode() + b"\n",
            _json.dumps({"message": {"content": ""}, "done": True}).encode() + b"\n",
        ]

        client = self._make_stream_client(chunks)
        tokens = []
        async for token in client.stream_chat(
            messages=[{"role": "user", "content": "test"}],
        ):
            tokens.append(token)

        assert tokens == ["Antwort"]

    @pytest.mark.asyncio
    async def test_error_yields_nothing(self):
        """stream_chat() bei HTTP-Error gibt nichts zurueck."""
        client = self._make_stream_client([], status=500)
        tokens = []
        async for token in client.stream_chat(
            messages=[{"role": "user", "content": "test"}],
        ):
            tokens.append(token)

        assert tokens == []
