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
        assert len(names) == len(set(names)), (
            f"Duplikate: {[n for n in names if names.count(n) > 1]}"
        )


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
        "mood": "gut",
        "stress_level": 0.2,
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
    brain.camera_manager.describe_doorbell = AsyncMock(
        return_value="Eine Person mit Paket vor der Tuer"
    )
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
        from datetime import datetime, timedelta, timezone

        start = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
        mock_brain.memory.redis.get = AsyncMock(
            side_effect=lambda k: start if "pc_start" in k else None
        )
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
        assert result["message"] == "Alle Geräte normal"
        assert result["alerts"] == []

    @pytest.mark.asyncio
    async def test_with_alerts(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        mock_brain.device_health.check_all = AsyncMock(
            return_value=[
                {"message": "Sensor Kueche inaktiv seit 2h"},
                {"message": "Heizung Buero ineffizient"},
            ]
        )
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
        mock_brain.device_health.get_status = AsyncMock(
            side_effect=ConnectionError("Redis down")
        )
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
        mock_brain.learning_observer.get_learned_patterns = AsyncMock(
            return_value=[
                {
                    "action": "light.wohnzimmer:off",
                    "time_slot": "22:00-23:00",
                    "count": 12,
                    "weekday": -1,
                },
                {
                    "action": "cover.buero:100",
                    "time_slot": "07:00-08:00",
                    "count": 8,
                    "weekday": 0,
                },
            ]
        )
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
        mock_brain.learning_observer.get_learned_patterns = AsyncMock(
            side_effect=Exception("fail")
        )
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
        assert "nicht verfügbar" in result["message"]

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
        mock_brain.camera_manager.describe_doorbell = AsyncMock(
            side_effect=TimeoutError("Camera timeout")
        )
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_describe_doorbell({})
        assert result["success"] is False
        assert "fehlgeschlagen" in result["message"]


@_needs_main
class TestExecRetrieveMemory:
    """Tests fuer _exec_retrieve_memory()."""

    @pytest.mark.asyncio
    async def test_returns_facts(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        mock_brain.semantic_memory = MagicMock()
        mock_brain.semantic_memory.search_facts = AsyncMock(
            return_value=[
                {
                    "content": "Lieblingsfarbe ist Blau",
                    "confidence": 0.9,
                    "category": "preferences",
                    "person": "Max",
                },
                {
                    "content": "Allergisch gegen Erdnuesse",
                    "confidence": 0.85,
                    "category": "health",
                    "person": "",
                },
            ]
        )
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_retrieve_memory({"query": "Vorlieben"})
        assert result["success"] is True
        assert "Lieblingsfarbe ist Blau" in result["message"]
        assert "[preferences]" in result["message"]
        assert "(Person: Max)" in result["message"]
        assert "90%" in result["message"]

    @pytest.mark.asyncio
    async def test_empty_results(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        mock_brain.semantic_memory = MagicMock()
        mock_brain.semantic_memory.search_facts = AsyncMock(return_value=[])
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_retrieve_memory({"query": "unbekannt"})
        assert result["success"] is True
        assert "Keine Fakten" in result["message"]

    @pytest.mark.asyncio
    async def test_missing_query_returns_false(self):
        executor = _make_executor()
        result = await executor._exec_retrieve_memory({})
        assert result["success"] is False
        assert "Suchbegriff" in result["message"]

    @pytest.mark.asyncio
    async def test_empty_query_returns_false(self):
        executor = _make_executor()
        result = await executor._exec_retrieve_memory({"query": ""})
        assert result["success"] is False
        assert "Suchbegriff" in result["message"]

    @pytest.mark.asyncio
    async def test_with_person_filter(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        mock_brain.semantic_memory = MagicMock()
        mock_brain.semantic_memory.search_facts = AsyncMock(
            return_value=[
                {
                    "content": "Trinkt gerne Kaffee",
                    "confidence": 0.95,
                    "category": "preferences",
                    "person": "Lisa",
                },
            ]
        )
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_retrieve_memory(
                {"query": "Kaffee", "person": "Lisa"}
            )
        assert result["success"] is True
        mock_brain.semantic_memory.search_facts.assert_awaited_once_with(
            "Kaffee",
            limit=5,
            person="Lisa",
        )

    @pytest.mark.asyncio
    async def test_error_returns_false(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        mock_brain.semantic_memory = MagicMock()
        mock_brain.semantic_memory.search_facts = AsyncMock(
            side_effect=RuntimeError("ChromaDB down")
        )
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_retrieve_memory({"query": "test"})
        assert result["success"] is False
        assert "fehlgeschlagen" in result["message"]

    @pytest.mark.asyncio
    async def test_no_semantic_memory_returns_false(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        if hasattr(mock_brain, "semantic_memory"):
            del mock_brain.semantic_memory
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_retrieve_memory({"query": "test"})
        assert result["success"] is False
        assert "nicht verfuegbar" in result["message"]


@_needs_main
class TestExecRetrieveHistory:
    """Tests fuer _exec_retrieve_history()."""

    @pytest.mark.asyncio
    async def test_returns_conversations(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        mock_brain.memory.get_recent_conversations = AsyncMock(
            return_value=[
                {
                    "role": "user",
                    "content": "Mach das Licht an",
                    "timestamp": "2026-03-20T14:30:00",
                },
                {
                    "role": "assistant",
                    "content": "Licht ist an.",
                    "timestamp": "2026-03-20T14:30:05",
                },
            ]
        )
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_retrieve_history({})
        assert result["success"] is True
        assert "2 Interaktionen" in result["message"]
        assert "[14:30]" in result["message"]
        assert "Mach das Licht an" in result["message"]

    @pytest.mark.asyncio
    async def test_empty_history(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        mock_brain.memory.get_recent_conversations = AsyncMock(return_value=[])
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_retrieve_history({})
        assert result["success"] is True
        assert "Keine aktuellen" in result["message"]

    @pytest.mark.asyncio
    async def test_limit_capped_at_20(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        mock_brain.memory.get_recent_conversations = AsyncMock(return_value=[])
        with patch("assistant.main.brain", mock_brain):
            await executor._exec_retrieve_history({"limit": 50})
        mock_brain.memory.get_recent_conversations.assert_awaited_once_with(limit=20)

    @pytest.mark.asyncio
    async def test_default_limit_is_5(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        mock_brain.memory.get_recent_conversations = AsyncMock(return_value=[])
        with patch("assistant.main.brain", mock_brain):
            await executor._exec_retrieve_history({})
        mock_brain.memory.get_recent_conversations.assert_awaited_once_with(limit=5)

    @pytest.mark.asyncio
    async def test_error_returns_false(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        mock_brain.memory.get_recent_conversations = AsyncMock(
            side_effect=Exception("Redis down")
        )
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_retrieve_history({})
        assert result["success"] is False
        assert "fehlgeschlagen" in result["message"]

    @pytest.mark.asyncio
    async def test_content_truncated_at_200(self):
        executor = _make_executor()
        mock_brain = _mock_brain()
        long_content = "A" * 300
        mock_brain.memory.get_recent_conversations = AsyncMock(
            return_value=[
                {
                    "role": "user",
                    "content": long_content,
                    "timestamp": "2026-03-20T10:00:00",
                },
            ]
        )
        with patch("assistant.main.brain", mock_brain):
            result = await executor._exec_retrieve_history({})
        assert result["success"] is True
        # Content should be truncated to 200 chars in the output
        assert "A" * 201 not in result["message"]


@_needs_main
class TestExecVerifyDeviceState:
    """Tests fuer _exec_verify_device_state()."""

    @pytest.mark.asyncio
    async def test_light_with_brightness(self):
        executor = _make_executor()
        executor.ha.get_state = AsyncMock(
            return_value={
                "state": "on",
                "attributes": {"brightness": 128},
            }
        )
        result = await executor._exec_verify_device_state(
            {"entity_id": "light.wohnzimmer"}
        )
        assert result["success"] is True
        assert result["state"] == "on"
        assert "Helligkeit: 50%" in result["message"]

    @pytest.mark.asyncio
    async def test_climate_with_temperatures(self):
        executor = _make_executor()
        executor.ha.get_state = AsyncMock(
            return_value={
                "state": "heat",
                "attributes": {"temperature": 22, "current_temperature": 20.5},
            }
        )
        result = await executor._exec_verify_device_state(
            {"entity_id": "climate.buero"}
        )
        assert result["success"] is True
        assert "Zieltemperatur: 22°C" in result["message"]
        assert "Aktuelle Temperatur: 20.5°C" in result["message"]

    @pytest.mark.asyncio
    async def test_cover_with_position(self):
        executor = _make_executor()
        executor.ha.get_state = AsyncMock(
            return_value={
                "state": "open",
                "attributes": {"current_position": 75},
            }
        )
        result = await executor._exec_verify_device_state(
            {"entity_id": "cover.rolladen"}
        )
        assert result["success"] is True
        assert "Position: 75%" in result["message"]

    @pytest.mark.asyncio
    async def test_missing_entity_id_returns_false(self):
        executor = _make_executor()
        result = await executor._exec_verify_device_state({})
        assert result["success"] is False
        assert "entity_id" in result["message"]

    @pytest.mark.asyncio
    async def test_entity_not_found(self):
        executor = _make_executor()
        executor.ha.get_state = AsyncMock(return_value=None)
        result = await executor._exec_verify_device_state(
            {"entity_id": "light.gibts_nicht"}
        )
        assert result["success"] is False
        assert "nicht gefunden" in result["message"]

    @pytest.mark.asyncio
    async def test_expected_state_verified(self):
        executor = _make_executor()
        executor.ha.get_state = AsyncMock(
            return_value={
                "state": "on",
                "attributes": {},
            }
        )
        result = await executor._exec_verify_device_state(
            {
                "entity_id": "light.flur",
                "expected_state": "on",
            }
        )
        assert result["success"] is True
        assert result["verified"] is True

    @pytest.mark.asyncio
    async def test_expected_state_mismatch(self):
        executor = _make_executor()
        executor.ha.get_state = AsyncMock(
            return_value={
                "state": "off",
                "attributes": {},
            }
        )
        result = await executor._exec_verify_device_state(
            {
                "entity_id": "light.flur",
                "expected_state": "on",
            }
        )
        assert result["success"] is True
        assert result["verified"] is False
        assert "tatsaechlich: off" in result["message"]

    @pytest.mark.asyncio
    async def test_error_returns_false(self):
        executor = _make_executor()
        executor.ha.get_state = AsyncMock(side_effect=ConnectionError("HA offline"))
        result = await executor._exec_verify_device_state({"entity_id": "light.test"})
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
            _json.dumps({"message": {"content": "Hallo"}, "done": False}).encode()
            + b"\n",
            _json.dumps({"message": {"content": " Welt"}, "done": False}).encode()
            + b"\n",
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
            _json.dumps({"message": {"content": "<think>"}, "done": False}).encode()
            + b"\n",
            _json.dumps({"message": {"content": "reasoning"}, "done": False}).encode()
            + b"\n",
            _json.dumps({"message": {"content": "</think>"}, "done": False}).encode()
            + b"\n",
            _json.dumps({"message": {"content": "Antwort"}, "done": False}).encode()
            + b"\n",
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
        """stream_chat() bei HTTP-Error gibt Error-Marker oder nichts zurueck."""
        client = self._make_stream_client([], status=500)
        tokens = []
        async for token in client.stream_chat(
            messages=[{"role": "user", "content": "test"}],
        ):
            tokens.append(token)

        assert tokens == [] or tokens == ["[STREAM_ERROR]"]
