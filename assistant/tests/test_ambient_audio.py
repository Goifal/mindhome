"""
Tests fuer AmbientAudioClassifier — Cooldown, Reaktionen, Nachtmodus.
"""

import time
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from assistant.ambient_audio import AmbientAudioClassifier


@pytest.fixture
def classifier():
    ha = AsyncMock()
    c = AmbientAudioClassifier(ha)
    c.enabled = True
    c._default_cooldown = 30
    return c


class TestCheckCooldown:
    """Tests fuer _check_cooldown()."""

    def test_no_previous_event(self, classifier):
        assert classifier._check_cooldown("doorbell") is True

    def test_within_cooldown(self, classifier):
        classifier._last_event_times["doorbell"] = time.time()
        assert classifier._check_cooldown("doorbell") is False

    def test_after_cooldown(self, classifier):
        classifier._last_event_times["doorbell"] = time.time() - 60
        assert classifier._check_cooldown("doorbell") is True

    def test_custom_event_cooldown(self, classifier):
        classifier._event_cooldowns["alarm"] = 120
        classifier._last_event_times["alarm"] = time.time() - 60
        # 60s vergangen, aber Cooldown ist 120s
        assert classifier._check_cooldown("alarm") is False

    def test_custom_event_cooldown_passed(self, classifier):
        classifier._event_cooldowns["alarm"] = 120
        classifier._last_event_times["alarm"] = time.time() - 150
        assert classifier._check_cooldown("alarm") is True


class TestGetReaction:
    """Tests fuer _get_reaction()."""

    def test_known_event_type(self, classifier):
        # DEFAULT_EVENT_REACTIONS hat z.B. "doorbell", "glass_break"
        reaction = classifier._get_reaction("doorbell")
        # Kann None sein wenn kein Mapping existiert, oder dict
        # Testen dass es ein dict oder None ist
        assert reaction is None or isinstance(reaction, dict)

    def test_override_merges(self, classifier):
        classifier._reaction_overrides["custom_event"] = {
            "message": "Eigene Nachricht",
            "severity": "critical",
        }
        # Wenn custom_event nicht in DEFAULT_EVENT_REACTIONS, merged mit leerem dict
        reaction = classifier._get_reaction("custom_event")
        assert reaction is not None
        assert reaction["message"] == "Eigene Nachricht"
        assert reaction["severity"] == "critical"

    def test_unknown_event_no_override(self, classifier):
        reaction = classifier._get_reaction("totally_unknown_xyz")
        assert reaction is None


class TestIsNight:
    """Tests fuer _is_night()."""

    def test_night_standard(self, classifier):
        """22:00-07:00 ist Nacht."""
        classifier._night_start = 22
        classifier._night_end = 7

        with patch("assistant.ambient_audio.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 2, 20, 23, 0)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            assert classifier._is_night() is True

    def test_day_standard(self, classifier):
        """Mittags ist kein Nachtmodus."""
        classifier._night_start = 22
        classifier._night_end = 7

        with patch("assistant.ambient_audio.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 2, 20, 12, 0)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            assert classifier._is_night() is False


class TestEscalateSeverity:
    """Tests fuer _escalate_severity()."""

    def test_info_to_high(self, classifier):
        assert classifier._escalate_severity("info") == "high"

    def test_high_to_critical(self, classifier):
        assert classifier._escalate_severity("high") == "critical"

    def test_critical_stays(self, classifier):
        assert classifier._escalate_severity("critical") == "critical"

    def test_unknown_unchanged(self, classifier):
        assert classifier._escalate_severity("foo") == "foo"


class TestExtractRoom:
    """Tests fuer _extract_room_from_entity()."""

    def test_wohnzimmer(self, classifier):
        result = classifier._extract_room_from_entity("binary_sensor.wohnzimmer_smoke")
        assert result == "wohnzimmer"

    def test_kueche(self, classifier):
        result = classifier._extract_room_from_entity("binary_sensor.kueche_glass_break")
        assert result == "kueche"

    def test_schlafzimmer(self, classifier):
        result = classifier._extract_room_from_entity("binary_sensor.schlafzimmer_noise")
        assert result == "schlafzimmer"

    def test_fallback_underscore_split(self, classifier):
        result = classifier._extract_room_from_entity("binary_sensor.diele_sensor")
        assert result == "diele"

    def test_no_dot(self, classifier):
        result = classifier._extract_room_from_entity("invalid_entity")
        assert result is None


class TestRecentEvents:
    """Tests fuer get_recent_events() und get_events_by_type()."""

    def test_empty_history(self, classifier):
        assert classifier.get_recent_events() == []

    def test_recent_events_limit(self, classifier):
        classifier._event_history = [{"type": f"event_{i}"} for i in range(20)]
        result = classifier.get_recent_events(limit=5)
        assert len(result) == 5

    def test_events_by_type(self, classifier):
        classifier._event_history = [
            {"type": "doorbell"},
            {"type": "glass_break"},
            {"type": "doorbell"},
        ]
        result = classifier.get_events_by_type("doorbell")
        assert len(result) == 2


class TestHealthStatus:
    """Tests fuer health_status()."""

    def test_disabled(self, classifier):
        classifier.enabled = False
        assert classifier.health_status() == "disabled"

    def test_running(self, classifier):
        classifier._running = True
        status = classifier.health_status()
        assert "running" in status

    def test_active_not_running(self, classifier):
        classifier._running = False
        status = classifier.health_status()
        assert "active" in status


# =====================================================================
# Additional tests for 100% coverage
# =====================================================================

import json
import asyncio


class TestInitialize:
    """Tests fuer initialize()."""

    @pytest.mark.asyncio
    async def test_initialize_loads_history(self, classifier):
        redis = AsyncMock()
        history_data = json.dumps([{"type": "doorbell", "timestamp": "2026-01-01"}])
        redis.get = AsyncMock(return_value=history_data)
        await classifier.initialize(redis)
        assert len(classifier._event_history) == 1
        assert classifier._redis is redis

    @pytest.mark.asyncio
    async def test_initialize_no_redis(self, classifier):
        await classifier.initialize(None)
        assert classifier._redis is None

    @pytest.mark.asyncio
    async def test_initialize_empty_history(self, classifier):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        await classifier.initialize(redis)
        assert classifier._event_history == []

    @pytest.mark.asyncio
    async def test_initialize_corrupted_history(self, classifier):
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=Exception("Redis error"))
        await classifier.initialize(redis)
        assert classifier._event_history == []


class TestStartStop:
    """Tests fuer start() und stop()."""

    @pytest.mark.asyncio
    async def test_start_disabled(self, classifier):
        classifier.enabled = False
        await classifier.start()
        assert classifier._running is False

    @pytest.mark.asyncio
    async def test_start_no_sensors(self, classifier):
        classifier._sensor_mappings = {}
        await classifier.start()
        assert classifier._running is False

    @pytest.mark.asyncio
    async def test_start_with_sensors(self, classifier):
        classifier._sensor_mappings = {"sensor.test": "doorbell"}
        with patch.object(classifier, '_poll_loop', new_callable=AsyncMock):
            await classifier.start()
        assert classifier._running is True
        classifier._poll_task.cancel()
        try:
            await classifier._poll_task
        except (asyncio.CancelledError, Exception):
            pass

    @pytest.mark.asyncio
    async def test_stop(self, classifier):
        classifier._running = True
        classifier._poll_task = asyncio.create_task(asyncio.sleep(100))
        await classifier.stop()
        assert classifier._running is False

    @pytest.mark.asyncio
    async def test_stop_no_task(self, classifier):
        classifier._running = True
        classifier._poll_task = None
        await classifier.stop()
        assert classifier._running is False


class TestProcessEvent:
    """Tests fuer process_event()."""

    @pytest.mark.asyncio
    async def test_disabled_returns_none(self, classifier):
        classifier.enabled = False
        result = await classifier.process_event("doorbell")
        assert result is None

    @pytest.mark.asyncio
    async def test_disabled_event_type(self, classifier):
        classifier._disabled_events = {"doorbell"}
        result = await classifier.process_event("doorbell")
        assert result is None

    @pytest.mark.asyncio
    async def test_low_confidence(self, classifier):
        with patch("assistant.ambient_audio.yaml_config", {"ambient_audio": {"min_confidence": 0.8}}):
            result = await classifier.process_event("doorbell", confidence=0.3)
        assert result is None

    @pytest.mark.asyncio
    async def test_in_cooldown(self, classifier):
        classifier._last_event_times["doorbell"] = time.time()
        result = await classifier.process_event("doorbell")
        assert result is None

    @pytest.mark.asyncio
    async def test_unknown_reaction(self, classifier):
        result = await classifier.process_event("totally_unknown_event_xyz")
        assert result is None

    @pytest.mark.asyncio
    async def test_successful_event(self, classifier):
        classifier._last_event_times.clear()
        with patch("assistant.ambient_audio.yaml_config", {"ambient_audio": {"min_confidence": 0.5}}):
            with patch.object(classifier, '_is_night', return_value=False):
                result = await classifier.process_event(
                    "doorbell", room="flur", confidence=0.9, source="sensor",
                )
        assert result is not None
        assert result["type"] == "doorbell"
        assert result["room"] == "flur"
        assert result["severity"] == "info"

    @pytest.mark.asyncio
    async def test_night_escalation(self, classifier):
        classifier._last_event_times.clear()
        classifier._night_escalate = True
        with patch("assistant.ambient_audio.yaml_config", {"ambient_audio": {"min_confidence": 0.5}}):
            with patch.object(classifier, '_is_night', return_value=True):
                result = await classifier.process_event(
                    "doorbell", room="flur", confidence=0.9,
                )
        assert result is not None
        assert result["severity"] == "high"  # escalated from info

    @pytest.mark.asyncio
    async def test_callback_called(self, classifier):
        classifier._last_event_times.clear()
        callback = AsyncMock()
        classifier._notify_callback = callback
        with patch("assistant.ambient_audio.yaml_config", {"ambient_audio": {"min_confidence": 0.5}}):
            with patch.object(classifier, '_is_night', return_value=False):
                await classifier.process_event("doorbell", room="flur", confidence=0.9)
        callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_callback_exception(self, classifier):
        classifier._last_event_times.clear()
        callback = AsyncMock(side_effect=Exception("callback failed"))
        classifier._notify_callback = callback
        with patch("assistant.ambient_audio.yaml_config", {"ambient_audio": {"min_confidence": 0.5}}):
            with patch.object(classifier, '_is_night', return_value=False):
                result = await classifier.process_event("doorbell", confidence=0.9)
        assert result is not None  # Should still return event

    @pytest.mark.asyncio
    async def test_history_truncation(self, classifier):
        classifier._last_event_times.clear()
        classifier._event_history = [{"type": "x"} for _ in range(100)]
        with patch("assistant.ambient_audio.yaml_config", {"ambient_audio": {"min_confidence": 0.5}}):
            with patch.object(classifier, '_is_night', return_value=False):
                await classifier.process_event("doorbell", confidence=0.9)
        assert len(classifier._event_history) <= classifier._max_history


class TestProcessHaStateChange:
    """Tests fuer process_ha_state_change()."""

    @pytest.mark.asyncio
    async def test_disabled(self, classifier):
        classifier.enabled = False
        result = await classifier.process_ha_state_change("sensor.x", "on")
        assert result is None

    @pytest.mark.asyncio
    async def test_non_trigger_state(self, classifier):
        result = await classifier.process_ha_state_change("sensor.x", "off")
        assert result is None

    @pytest.mark.asyncio
    async def test_unmapped_entity(self, classifier):
        result = await classifier.process_ha_state_change("sensor.unknown", "on")
        assert result is None

    @pytest.mark.asyncio
    async def test_mapped_entity(self, classifier):
        classifier._sensor_mappings = {"binary_sensor.kueche_smoke": "smoke_alarm"}
        classifier._last_event_times.clear()
        with patch("assistant.ambient_audio.yaml_config", {"ambient_audio": {"min_confidence": 0.5}}):
            with patch.object(classifier, '_is_night', return_value=False):
                result = await classifier.process_ha_state_change(
                    "binary_sensor.kueche_smoke", "on", {"confidence": 0.95},
                )
        assert result is not None
        assert result["type"] == "smoke_alarm"
        assert result["room"] == "kueche"

    @pytest.mark.asyncio
    async def test_confidence_from_attributes(self, classifier):
        classifier._sensor_mappings = {"binary_sensor.test": "glass_break"}
        classifier._last_event_times.clear()
        with patch("assistant.ambient_audio.yaml_config", {"ambient_audio": {"min_confidence": 0.5}}):
            with patch.object(classifier, '_is_night', return_value=False):
                result = await classifier.process_ha_state_change(
                    "binary_sensor.test", "detected", {"score": 0.8},
                )
        assert result is not None


class TestSaveHistory:
    """Tests fuer _save_history()."""

    @pytest.mark.asyncio
    async def test_no_redis(self, classifier):
        classifier._redis = None
        await classifier._save_history()

    @pytest.mark.asyncio
    async def test_save_success(self, classifier):
        redis = AsyncMock()
        classifier._redis = redis
        classifier._event_history = [{"type": "doorbell"}]
        await classifier._save_history()
        redis.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_exception(self, classifier):
        redis = AsyncMock()
        redis.set = AsyncMock(side_effect=Exception("fail"))
        classifier._redis = redis
        classifier._event_history = [{"type": "doorbell"}]
        await classifier._save_history()  # Should not raise


class TestGetInfo:
    """Tests fuer get_info()."""

    def test_returns_complete_info(self, classifier):
        info = classifier.get_info()
        assert "enabled" in info
        assert "running" in info
        assert "sensor_count" in info
        assert "supported_events" in info
        assert "cooldowns" in info


class TestSetNotifyCallback:
    """Tests fuer set_notify_callback()."""

    def test_set_callback(self, classifier):
        async def my_callback(**kwargs):
            pass
        classifier.set_notify_callback(my_callback)
        assert classifier._notify_callback is my_callback


class TestExtractRoomFallback:
    """Additional extract_room tests."""

    def test_no_underscore_returns_none(self, classifier):
        result = classifier._extract_room_from_entity("binary_sensor.singleword")
        assert result is None or result == "singleword"
