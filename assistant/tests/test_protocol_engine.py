"""
Tests fuer Feature 2: Benannte Protokolle (ProtocolEngine).
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from assistant.protocol_engine import ProtocolEngine


class TestNormalizeName:
    """Tests fuer ProtocolEngine._normalize_name()."""

    def test_simple_name(self):
        assert ProtocolEngine._normalize_name("Filmabend") == "filmabend"

    def test_name_with_spaces(self):
        assert ProtocolEngine._normalize_name("Film Abend") == "film_abend"

    def test_name_with_umlauts(self):
        result = ProtocolEngine._normalize_name("Bücher Rücken")
        assert "ue" in result
        assert "ü" not in result

    def test_name_with_special_chars(self):
        result = ProtocolEngine._normalize_name("Film!Abend?#")
        assert result == "film_abend"

    def test_collapse_multiple_underscores(self):
        result = ProtocolEngine._normalize_name("test___name")
        assert result == "test_name"

    def test_strip_leading_trailing_underscores(self):
        result = ProtocolEngine._normalize_name("___leading___")
        assert result == "leading"

    def test_max_length_50(self):
        long_name = "a" * 100
        result = ProtocolEngine._normalize_name(long_name)
        assert len(result) <= 50

    def test_lowercase(self):
        result = ProtocolEngine._normalize_name("FILMABEND")
        assert result == "filmabend"

    def test_umlaut_ae(self):
        result = ProtocolEngine._normalize_name("Tägliche Routine")
        assert "ae" in result

    def test_umlaut_oe(self):
        result = ProtocolEngine._normalize_name("Schöner Morgen")
        assert "oe" in result

    def test_sz(self):
        result = ProtocolEngine._normalize_name("Große Sache")
        assert "ss" in result


class TestGenerateUndoSteps:
    """Tests fuer ProtocolEngine._generate_undo_steps()."""

    def test_undo_light_off(self):
        """Licht aus → Undo = Licht an mit brightness 80."""
        steps = [{"tool": "set_light", "args": {"entity_id": "light.wz", "state": "off"}}]
        undo = ProtocolEngine._generate_undo_steps(steps)
        assert len(undo) == 1
        assert undo[0]["args"]["state"] == "on"
        assert undo[0]["args"]["brightness"] == 80

    def test_undo_light_on(self):
        """Licht an (brightness >= 50) → Undo = Licht aus."""
        steps = [{"tool": "set_light", "args": {"entity_id": "light.wz", "state": "on", "brightness": 80}}]
        undo = ProtocolEngine._generate_undo_steps(steps)
        assert len(undo) == 1
        assert undo[0]["args"]["state"] == "off"

    def test_undo_light_dim(self):
        """Licht gedimmt (brightness < 50) → Undo = Licht an mit brightness 80."""
        steps = [{"tool": "set_light", "args": {"entity_id": "light.wz", "state": "on", "brightness": 20}}]
        undo = ProtocolEngine._generate_undo_steps(steps)
        assert len(undo) == 1
        assert undo[0]["args"]["state"] == "on"
        assert undo[0]["args"]["brightness"] == 80

    def test_undo_cover_close(self):
        """Rolladen schliessen → Undo = oeffnen."""
        steps = [{"tool": "set_cover", "args": {"entity_id": "cover.wz", "action": "close"}}]
        undo = ProtocolEngine._generate_undo_steps(steps)
        assert len(undo) == 1
        assert undo[0]["args"]["action"] == "open"

    def test_undo_cover_open(self):
        """Rolladen oeffnen → Undo = schliessen."""
        steps = [{"tool": "set_cover", "args": {"entity_id": "cover.wz", "action": "open"}}]
        undo = ProtocolEngine._generate_undo_steps(steps)
        assert len(undo) == 1
        assert undo[0]["args"]["action"] == "close"

    def test_undo_climate(self):
        """Klima setzen → Undo = 21°C."""
        steps = [{"tool": "set_climate", "args": {"entity_id": "climate.wz", "temperature": 25}}]
        undo = ProtocolEngine._generate_undo_steps(steps)
        assert len(undo) == 1
        assert undo[0]["args"]["temperature"] == 21

    def test_undo_switch_on(self):
        """Switch ein → Undo = aus."""
        steps = [{"tool": "set_switch", "args": {"entity_id": "switch.tv", "state": "on"}}]
        undo = ProtocolEngine._generate_undo_steps(steps)
        assert len(undo) == 1
        assert undo[0]["args"]["state"] == "off"

    def test_undo_media_play(self):
        """Media play → Undo = stop."""
        steps = [{"tool": "play_media", "args": {"entity_id": "media.tv", "action": "play"}}]
        undo = ProtocolEngine._generate_undo_steps(steps)
        assert len(undo) == 1
        assert undo[0]["args"]["action"] == "stop"

    def test_unknown_tool_skipped(self):
        """Unbekanntes Tool wird uebersprungen."""
        steps = [{"tool": "unknown_tool", "args": {"foo": "bar"}}]
        undo = ProtocolEngine._generate_undo_steps(steps)
        assert len(undo) == 0

    def test_multiple_steps(self):
        """Mehrere Schritte werden korrekt reversed."""
        steps = [
            {"tool": "set_light", "args": {"entity_id": "light.wz", "state": "off"}},
            {"tool": "set_cover", "args": {"entity_id": "cover.wz", "action": "close"}},
        ]
        undo = ProtocolEngine._generate_undo_steps(steps)
        assert len(undo) == 2


class TestDetectProtocolIntent:
    """Tests fuer ProtocolEngine.detect_protocol_intent()."""

    @pytest.fixture
    def engine(self, redis_mock):
        """ProtocolEngine mit gemocktem Redis."""
        ollama = AsyncMock()
        e = ProtocolEngine(ollama)
        e.redis = redis_mock
        e.enabled = True
        return e

    @pytest.mark.asyncio
    async def test_detect_exact_match(self, engine):
        """Exakter Protokoll-Name wird erkannt."""
        engine.redis.smembers = AsyncMock(return_value={b"filmabend"})
        result = await engine.detect_protocol_intent("filmabend")
        assert result == "filmabend"

    @pytest.mark.asyncio
    async def test_detect_with_jarvis_prefix(self, engine):
        """'Jarvis filmabend' erkennt 'filmabend'."""
        engine.redis.smembers = AsyncMock(return_value={b"filmabend"})
        result = await engine.detect_protocol_intent("jarvis filmabend")
        assert result == "filmabend"

    @pytest.mark.asyncio
    async def test_detect_no_match(self, engine):
        """Kein Match gibt None zurueck."""
        engine.redis.smembers = AsyncMock(return_value={b"filmabend"})
        result = await engine.detect_protocol_intent("wie wird das wetter")
        assert result is None

    @pytest.mark.asyncio
    async def test_detect_disabled(self, engine):
        """Deaktiviertes Feature gibt None zurueck."""
        engine.enabled = False
        result = await engine.detect_protocol_intent("filmabend")
        assert result is None

    @pytest.mark.asyncio
    async def test_detect_no_redis(self, engine):
        """Ohne Redis gibt None zurueck."""
        engine.redis = None
        result = await engine.detect_protocol_intent("filmabend")
        assert result is None


class TestCreateProtocol:
    """Tests fuer ProtocolEngine.create_protocol()."""

    @pytest.fixture
    def engine(self, redis_mock, ollama_mock):
        """ProtocolEngine mit Mocks."""
        e = ProtocolEngine(ollama_mock)
        e.redis = redis_mock
        e.enabled = True
        return e

    @pytest.mark.asyncio
    async def test_create_success(self, engine):
        """Protokoll erfolgreich erstellen."""
        engine.redis.scard = AsyncMock(return_value=0)
        engine.redis.smembers = AsyncMock(return_value=set())
        # LLM gibt JSON-Steps zurueck
        engine._parse_steps = AsyncMock(return_value=[
            {"tool": "set_light", "args": {"entity_id": "light.wz", "state": "off", "brightness": 20}},
        ])
        result = await engine.create_protocol("Filmabend", "Licht dimmen")
        assert result["success"] is True
        assert "steps" in result

    @pytest.mark.asyncio
    async def test_create_stores_in_redis(self, engine):
        """Protokoll wird in Redis gespeichert."""
        engine.redis.scard = AsyncMock(return_value=0)
        engine.redis.smembers = AsyncMock(return_value=set())
        engine._parse_steps = AsyncMock(return_value=[
            {"tool": "set_light", "args": {"entity_id": "light.wz", "state": "off"}},
        ])
        await engine.create_protocol("Test", "Licht aus", person="Max")
        # Redis set und sadd muessen aufgerufen worden sein
        engine.redis.set.assert_called()
        engine.redis.sadd.assert_called()

    @pytest.mark.asyncio
    async def test_create_person_stored(self, engine):
        """Person wird im Protokoll gespeichert."""
        engine.redis.scard = AsyncMock(return_value=0)
        engine.redis.smembers = AsyncMock(return_value=set())
        engine._parse_steps = AsyncMock(return_value=[
            {"tool": "set_light", "args": {"entity_id": "light.wz", "state": "off"}},
        ])
        await engine.create_protocol("Test", "Licht aus", person="Max")
        # Pruefe den Redis set() call
        call_args = engine.redis.set.call_args
        stored_data = json.loads(call_args[0][1])
        assert stored_data["created_by"] == "Max"


class TestExecuteProtocol:
    """Tests fuer ProtocolEngine.execute_protocol()."""

    @pytest.fixture
    def engine(self, redis_mock):
        """ProtocolEngine mit Executor-Mock."""
        ollama = AsyncMock()
        e = ProtocolEngine(ollama)
        e.redis = redis_mock
        e.enabled = True
        e.executor = AsyncMock()
        e.executor.execute = AsyncMock(return_value={"success": True})
        return e

    @pytest.mark.asyncio
    async def test_execute_runs_steps(self, engine):
        """Alle Steps werden ausgefuehrt."""
        protocol = {
            "name": "filmabend",
            "name_normalized": "filmabend",
            "steps": [
                {"tool": "set_light", "args": {"entity_id": "light.wz", "state": "off"}},
                {"tool": "set_cover", "args": {"entity_id": "cover.wz", "action": "close"}},
            ],
            "undo_steps": [],
        }
        engine.redis.get = AsyncMock(return_value=json.dumps(protocol).encode())
        result = await engine.execute_protocol("filmabend")
        assert result["success"] is True
        assert engine.executor.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_execute_not_found(self, engine):
        """Nicht existierendes Protokoll gibt Fehler."""
        engine.redis.get = AsyncMock(return_value=None)
        result = await engine.execute_protocol("nichtvorhanden")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_execute_stores_last_executed(self, engine):
        """Last-executed Marker wird in Redis gespeichert."""
        protocol = {
            "name": "filmabend",
            "name_normalized": "filmabend",
            "steps": [
                {"tool": "set_light", "args": {"entity_id": "light.wz", "state": "off"}},
            ],
            "undo_steps": [],
        }
        engine.redis.get = AsyncMock(return_value=json.dumps(protocol).encode())
        await engine.execute_protocol("filmabend")
        # setex mit TTL von 3600 Sekunden
        engine.redis.setex.assert_called()
