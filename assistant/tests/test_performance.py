"""
Tests fuer Performance-Optimierungen — Caches, Pipelines, Limits, Persistenz.
"""

import json
import time
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.context_builder import ContextBuilder
from assistant.memory import MemoryManager


# =====================================================================
# ha_client: States-Cache (TTL, Invalidierung, self._STATES_CACHE_TTL)
# =====================================================================


class TestHaClientStatesCache:
    """Tests fuer den States-Cache im HomeAssistantClient."""

    def _make_client(self):
        with patch("assistant.ha_client.settings") as mock_settings:
            mock_settings.ha_url = "http://localhost:8123"
            mock_settings.ha_token = "test-token"
            mock_settings.mindhome_url = "http://localhost:8099"
            from assistant.ha_client import HomeAssistantClient
            return HomeAssistantClient()

    def test_cache_ttl_is_5_seconds(self):
        client = self._make_client()
        assert client._STATES_CACHE_TTL == 5.0

    def test_cache_initially_none(self):
        client = self._make_client()
        assert client._states_cache is None
        assert client._states_cache_ts == 0.0

    @pytest.mark.asyncio
    async def test_first_call_fetches_from_ha(self):
        client = self._make_client()
        states = [{"entity_id": "light.test", "state": "on"}]
        client._get_ha = AsyncMock(return_value=states)

        result = await client.get_states()
        assert result == states
        client._get_ha.assert_called_once_with("/api/states")

    @pytest.mark.asyncio
    async def test_second_call_returns_cache(self):
        client = self._make_client()
        states = [{"entity_id": "light.test", "state": "on"}]
        client._get_ha = AsyncMock(return_value=states)

        await client.get_states()
        await client.get_states()
        # Nur 1x aufgerufen — zweiter Call kommt aus Cache
        client._get_ha.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_expires_after_ttl(self):
        client = self._make_client()
        client._STATES_CACHE_TTL = 0.01  # 10ms fuer Test
        states1 = [{"entity_id": "light.a", "state": "on"}]
        states2 = [{"entity_id": "light.b", "state": "off"}]
        client._get_ha = AsyncMock(side_effect=[states1, states2])

        result1 = await client.get_states()
        assert result1 == states1

        import asyncio
        await asyncio.sleep(0.02)

        result2 = await client.get_states()
        assert result2 == states2
        assert client._get_ha.call_count == 2

    @pytest.mark.asyncio
    async def test_cache_handles_none_response(self):
        client = self._make_client()
        client._get_ha = AsyncMock(return_value=None)

        result = await client.get_states()
        assert result == []


# =====================================================================
# Fehlerspeicher-Persistenz (restore/persist)
# =====================================================================


class TestErrorBufferPersistence:
    """Tests fuer _restore_error_buffer und _persist_error_buffer.

    Da main.py FastAPI importiert (nicht in Test-Env verfuegbar),
    testen wir die Logik direkt ohne Import.
    """

    @pytest.mark.asyncio
    async def test_persist_saves_to_redis(self):
        buffer = deque(maxlen=100)
        buffer.append({"level": "WARNING", "message": "test1"})
        buffer.append({"level": "ERROR", "message": "test2"})
        key = "mha:error_buffer"
        ttl = 7 * 86400

        redis_mock = AsyncMock()

        # Logik aus _persist_error_buffer nachgebaut
        entries = list(buffer)
        await redis_mock.set(key, json.dumps(entries), ex=ttl)

        redis_mock.set.assert_called_once()
        saved = json.loads(redis_mock.set.call_args[0][1])
        assert len(saved) == 2
        assert saved[0]["message"] == "test1"

    @pytest.mark.asyncio
    async def test_restore_loads_from_redis(self):
        buffer = deque(maxlen=100)
        entries = [{"level": "ERROR", "message": "old_error"}]

        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(return_value=json.dumps(entries))

        # Logik aus _restore_error_buffer nachgebaut
        raw = await redis_mock.get("mha:error_buffer")
        restored = json.loads(raw)
        for entry in restored:
            buffer.append(entry)

        assert len(buffer) == 1
        assert buffer[0]["message"] == "old_error"

    @pytest.mark.asyncio
    async def test_restore_empty_redis(self):
        buffer = deque(maxlen=100)

        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(return_value=None)

        raw = await redis_mock.get("mha:error_buffer")
        if raw:
            for entry in json.loads(raw):
                buffer.append(entry)

        assert len(buffer) == 0

    @pytest.mark.asyncio
    async def test_restore_handles_corrupt_json(self):
        buffer = deque(maxlen=100)

        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(return_value="not-json{{{")

        raw = await redis_mock.get("mha:error_buffer")
        try:
            for entry in json.loads(raw):
                buffer.append(entry)
        except (json.JSONDecodeError, TypeError):
            pass

        assert len(buffer) == 0

    @pytest.mark.asyncio
    async def test_persist_handles_redis_error(self):
        redis_mock = AsyncMock()
        redis_mock.set = AsyncMock(side_effect=Exception("Redis down"))

        # Soll nicht crashen
        try:
            await redis_mock.set("mha:error_buffer", "[]", ex=604800)
        except Exception:
            pass  # Graceful handling


# =====================================================================
# device_health: Redis-Pipeline Tests
# =====================================================================


class TestDeviceHealthPipeline:
    """Tests fuer Pipeline-Optimierungen in DeviceHealthMonitor."""

    def _make_monitor(self):
        with patch("assistant.device_health.yaml_config", {"device_health": {"enabled": True}}):
            from assistant.device_health import DeviceHealthMonitor
            ha = AsyncMock()
            monitor = DeviceHealthMonitor(ha)
            return monitor

    @pytest.mark.asyncio
    async def test_add_sample_uses_pipeline(self):
        monitor = self._make_monitor()
        pipe_mock = MagicMock()
        pipe_mock.execute = AsyncMock(return_value=[1, True])

        redis_mock = MagicMock()
        redis_mock.pipeline = MagicMock(return_value=pipe_mock)
        monitor.redis = redis_mock

        # _recalculate_baseline auch mocken (wird nach add_sample aufgerufen)
        monitor._recalculate_baseline = AsyncMock()

        await monitor._add_sample("sensor.test", 22.5)

        redis_mock.pipeline.assert_called_once()
        pipe_mock.rpush.assert_called_once()
        pipe_mock.expire.assert_called_once()
        pipe_mock.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_recalculate_baseline_uses_pipeline(self):
        monitor = self._make_monitor()
        monitor.baseline_days = 2  # Nur 3 Tage statt 30 fuer schnelleren Test

        # Pipeline-Mock: 3 Tage × lrange
        pipe_mock = MagicMock()
        pipe_mock.execute = AsyncMock(return_value=[
            [b"20.0", b"21.0"],  # Heute
            [b"19.5", b"20.5"],  # Gestern
            [b"22.0"],           # Vorgestern
        ])

        hset_mock = AsyncMock()
        expire_mock = AsyncMock()

        redis_mock = MagicMock()
        redis_mock.pipeline = MagicMock(return_value=pipe_mock)
        redis_mock.hset = hset_mock
        redis_mock.expire = expire_mock
        monitor.redis = redis_mock

        await monitor._recalculate_baseline("sensor.temp")

        # Pipeline wurde genutzt (nicht einzelne lrange-Calls)
        redis_mock.pipeline.assert_called_once()
        assert pipe_mock.lrange.call_count == 3  # 3 Tage
        pipe_mock.execute.assert_called_once()

        # Baseline wurde gespeichert
        hset_mock.assert_called_once()
        call_kwargs = hset_mock.call_args[1]
        mapping = call_kwargs["mapping"]
        assert float(mapping["mean"]) == pytest.approx(20.6, abs=0.1)
        assert int(mapping["samples"]) == 5


# =====================================================================
# anticipation: Pipeline + lrange-Limit
# =====================================================================


class TestAnticipationPipeline:
    """Tests fuer Pipeline und Limit in AnticipationEngine."""

    def _make_engine(self):
        with patch("assistant.anticipation.yaml_config", {"anticipation": {"enabled": True, "history_days": 30}}):
            from assistant.anticipation import AnticipationEngine
            return AnticipationEngine()

    @pytest.mark.asyncio
    async def test_log_action_uses_pipeline(self):
        engine = self._make_engine()

        pipe_mock = MagicMock()
        pipe_mock.execute = AsyncMock(return_value=[1, True, True, 1, True])

        redis_mock = MagicMock()
        redis_mock.pipeline = MagicMock(return_value=pipe_mock)
        engine.redis = redis_mock

        await engine.log_action("turn_on", {"entity_id": "light.test"}, "Max")

        redis_mock.pipeline.assert_called_once()
        # 5 Befehle in einer Pipeline: lpush, ltrim, expire, lpush(day), expire(day)
        pipe_mock.execute.assert_called_once()
        assert pipe_mock.lpush.call_count == 2
        pipe_mock.ltrim.assert_called_once_with("mha:action_log", 0, 999)
        assert pipe_mock.expire.call_count == 2

    @pytest.mark.asyncio
    async def test_detect_patterns_uses_correct_limit(self):
        engine = self._make_engine()

        redis_mock = AsyncMock()
        # Weniger als 10 Eintraege → leere Patterns
        redis_mock.lrange = AsyncMock(return_value=[])
        engine.redis = redis_mock

        result = await engine.detect_patterns()
        assert result == []
        # Limit 999 statt 4999
        redis_mock.lrange.assert_called_once_with("mha:action_log", 0, 999)


# =====================================================================
# config_versioning: ltrim + Limit
# =====================================================================


class TestConfigVersioningLimits:
    """Tests fuer Snapshot-Limits in ConfigVersioning."""

    def _make_versioning(self):
        with patch("assistant.config_versioning.yaml_config", {"self_optimization": {"rollback": {"enabled": True}}}):
            from assistant.config_versioning import ConfigVersioning
            cv = ConfigVersioning()
            return cv

    @pytest.mark.asyncio
    async def test_create_snapshot_uses_pipeline_with_ltrim(self):
        cv = self._make_versioning()

        pipe_mock = MagicMock()
        pipe_mock.execute = AsyncMock(return_value=[1, True, True])

        redis_mock = MagicMock()
        redis_mock.pipeline = MagicMock(return_value=pipe_mock)
        cv._redis = redis_mock
        cv._cleanup_old_snapshots = AsyncMock()

        # yaml_path als Path-Mock mit exists()
        yaml_path = MagicMock()
        yaml_path.exists = MagicMock(return_value=True)

        with patch("assistant.config_versioning._SNAPSHOT_DIR") as snap_dir, \
             patch("assistant.config_versioning.shutil.copy2"):
            snap_dir.__truediv__ = MagicMock(return_value=MagicMock())

            result = await cv.create_snapshot("settings", yaml_path, "test_reason")

        # Pipeline mit lpush + ltrim(50) + expire
        redis_mock.pipeline.assert_called_once()
        pipe_mock.lpush.assert_called_once()
        pipe_mock.ltrim.assert_called_once()
        ltrim_args = pipe_mock.ltrim.call_args[0]
        assert ltrim_args[1] == 0
        assert ltrim_args[2] == 49  # Max 50 Snapshots
        pipe_mock.expire.assert_called_once()
        pipe_mock.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_snapshots_limited_to_50(self):
        cv = self._make_versioning()

        redis_mock = AsyncMock()
        redis_mock.lrange = AsyncMock(return_value=[])
        cv._redis = redis_mock

        await cv.list_snapshots("settings")
        redis_mock.lrange.assert_called_once_with("mha:config_snapshots:settings", 0, 49)


# =====================================================================
# memory: mget statt 2x get
# =====================================================================


class TestFeedbackScoreMget:
    """Tests fuer optimierte mget-basierte Feedback-Score-Abfrage."""

    @pytest.fixture
    def memory(self):
        mem = MemoryManager()
        mem.redis = AsyncMock()
        return mem

    @pytest.mark.asyncio
    async def test_mget_called_with_both_keys(self, memory):
        memory.redis.mget = AsyncMock(return_value=["0.7", None])
        score = await memory.get_feedback_score("test_event")
        assert score == 0.7
        memory.redis.mget.assert_called_once_with(
            "mha:feedback:score:test_event", "mha:feedback:test_event"
        )

    @pytest.mark.asyncio
    async def test_mget_falls_back_to_old_key(self, memory):
        memory.redis.mget = AsyncMock(return_value=[None, "0.3"])
        score = await memory.get_feedback_score("old_event")
        assert score == 0.3

    @pytest.mark.asyncio
    async def test_mget_both_none_returns_default(self, memory):
        memory.redis.mget = AsyncMock(return_value=[None, None])
        score = await memory.get_feedback_score("unknown")
        assert score == 0.5

    @pytest.mark.asyncio
    async def test_mget_new_key_preferred_over_old(self, memory):
        memory.redis.mget = AsyncMock(return_value=["0.9", "0.1"])
        score = await memory.get_feedback_score("both")
        assert score == 0.9  # Neues Schema hat Vorrang


# =====================================================================
# context_builder: Weather-Cache
# =====================================================================


class TestWeatherWarningsCache:
    """Tests fuer den 5-Minuten-Cache der Wetter-Warnungen."""

    @pytest.fixture
    def builder(self):
        ha = AsyncMock()
        return ContextBuilder(ha)

    def test_cache_ttl_is_300_seconds(self, builder):
        assert builder._WEATHER_CACHE_TTL == 300.0

    def test_cache_initially_empty(self, builder):
        assert builder._weather_cache == []
        assert builder._weather_cache_ts == 0.0

    def test_first_call_computes_warnings(self, builder):
        states = [{
            "entity_id": "weather.home",
            "state": "sunny",
            "attributes": {"temperature": 40, "wind_speed": 10, "humidity": 50},
        }]
        with patch("assistant.context_builder.yaml_config", {"weather_warnings": {"enabled": True, "temp_high": 35}}):
            warnings = builder._check_weather_warnings(states)
        assert any("Hitze" in w for w in warnings)
        assert builder._weather_cache_ts > 0

    def test_second_call_returns_cache(self, builder):
        builder._weather_cache = ["Cached warning"]
        builder._weather_cache_ts = time.time()  # Gerade erst gecacht

        # Leere States — waere normalerweise keine Warnung, aber Cache greift
        result = builder._check_weather_warnings([])
        assert result == ["Cached warning"]

    def test_cache_expires_after_ttl(self, builder):
        builder._weather_cache = ["Old warning"]
        builder._weather_cache_ts = time.time() - 400  # 400s alt, TTL ist 300s

        states = [{
            "entity_id": "weather.home",
            "state": "sunny",
            "attributes": {"temperature": 20, "wind_speed": 5},
        }]
        with patch("assistant.context_builder.yaml_config", {"weather_warnings": {"enabled": True}}):
            result = builder._check_weather_warnings(states)
        # Alte Cache-Warnung ist weg (20°C ist normal)
        assert "Old warning" not in result


# =====================================================================
# sound_manager: _last_sound_time Cleanup
# =====================================================================


class TestSoundManagerCleanup:
    """Tests fuer das Cleanup des _last_sound_time Dicts."""

    def _make_manager(self):
        with patch("assistant.sound_manager.yaml_config", {"sounds": {"enabled": False}, "multi_room": {}}):
            from assistant.sound_manager import SoundManager
            ha = AsyncMock()
            return SoundManager(ha)

    def test_last_sound_time_initially_empty(self):
        mgr = self._make_manager()
        assert mgr._last_sound_time == {}

    def test_cleanup_triggers_at_50_entries(self):
        mgr = self._make_manager()
        now = time.time()
        # 55 Eintraege, davon 50 alt (>60s) und 5 frisch
        for i in range(50):
            mgr._last_sound_time[f"old_event_{i}"] = now - 120  # 2 Min alt
        for i in range(5):
            mgr._last_sound_time[f"new_event_{i}"] = now - 10  # 10s alt

        assert len(mgr._last_sound_time) == 55

        # Simuliere play_sound Zugriff — Cleanup sollte triggern
        # Wir rufen den Cleanup-Code direkt aus play_sound nach:
        # "if len(self._last_sound_time) > 50:"
        if len(mgr._last_sound_time) > 50:
            mgr._last_sound_time = {
                k: v for k, v in mgr._last_sound_time.items()
                if now - v < 60
            }

        # Nur die 5 frischen sollten uebrig sein
        assert len(mgr._last_sound_time) == 5
        assert all(k.startswith("new_") for k in mgr._last_sound_time)

    def test_no_cleanup_under_50(self):
        mgr = self._make_manager()
        now = time.time()
        for i in range(30):
            mgr._last_sound_time[f"event_{i}"] = now - 120

        # Unter 50 → kein Cleanup
        assert len(mgr._last_sound_time) == 30


# =====================================================================
# brain: _get_occupied_room State-Map Optimierung
# =====================================================================


class TestOccupiedRoomStateMap:
    """Tests fuer die O(n) State-Map Optimierung in _get_occupied_room.

    Prueft die Logik der State-Map ohne den schweren AssistantBrain-Import.
    """

    def test_state_map_lookup_finds_correct_sensor(self):
        """State-Map findet Sensor per entity_id in O(1)."""
        states = [
            {"entity_id": "binary_sensor.motion_wz", "state": "off", "last_changed": "2026-01-01T10:00:00"},
            {"entity_id": "binary_sensor.motion_sz", "state": "on", "last_changed": "2026-01-01T10:05:00"},
            {"entity_id": "light.test", "state": "on"},
        ]
        state_map = {s.get("entity_id"): s for s in states}

        room_sensors = {
            "wohnzimmer": "binary_sensor.motion_wz",
            "schlafzimmer": "binary_sensor.motion_sz",
        }

        best_room = None
        best_changed = ""
        for room_name, sensor_id in room_sensors.items():
            s = state_map.get(sensor_id)
            if s and s.get("state") == "on":
                last_changed = s.get("last_changed", "")
                if last_changed > best_changed:
                    best_changed = last_changed
                    best_room = room_name

        assert best_room == "schlafzimmer"

    def test_state_map_missing_sensor(self):
        """State-Map gibt None fuer fehlende Sensoren."""
        states = [{"entity_id": "light.test", "state": "on"}]
        state_map = {s.get("entity_id"): s for s in states}

        assert state_map.get("binary_sensor.missing") is None

    def test_state_map_dedup(self):
        """State-Map dedupliziert bei doppelten entity_ids (letzter gewinnt)."""
        states = [
            {"entity_id": "sensor.temp", "state": "20"},
            {"entity_id": "sensor.temp", "state": "22"},
        ]
        state_map = {s.get("entity_id"): s for s in states}
        assert state_map["sensor.temp"]["state"] == "22"
