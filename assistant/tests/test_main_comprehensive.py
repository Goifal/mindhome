"""
Comprehensive tests for main.py — Handlers, buffers, boot, redaction, models.

Tests: _ErrorBufferHandler, _ActivityBufferHandler, _restore/_persist buffers,
_boot_announcement, _SENSITIVE_PATTERNS, _check_api_key, _init_api_key,
Pydantic models (ChatRequest, ChatResponse, TTSInfo, FeedbackRequest),
_periodic_token_cleanup, _API_KEY_EXEMPT_PATHS.
"""

import asyncio
import json
import logging
import re
from collections import deque
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ── Sensitive Pattern Redaction ──────────────────────────────────────


class TestSensitivePatterns:
    def _get_pattern(self):
        from assistant.main import _SENSITIVE_PATTERNS

        return _SENSITIVE_PATTERNS

    def test_redacts_api_key_equals(self):
        pat = self._get_pattern()
        text = "Failed with api_key=sk-1234abcd"
        result = pat.sub("[REDACTED]", text)
        assert "sk-1234abcd" not in result
        assert "[REDACTED]" in result

    def test_redacts_token_colon(self):
        pat = self._get_pattern()
        text = "token:Bearer_eyJhbGciOi"
        result = pat.sub("[REDACTED]", text)
        assert "Bearer_eyJhbGciOi" not in result

    def test_redacts_password_equals(self):
        pat = self._get_pattern()
        text = "password=supersecret123"
        result = pat.sub("[REDACTED]", text)
        assert "supersecret123" not in result

    def test_redacts_secret_colon(self):
        pat = self._get_pattern()
        text = "secret: my_secret_value"
        result = pat.sub("[REDACTED]", text)
        assert "my_secret_value" not in result

    def test_redacts_credential(self):
        pat = self._get_pattern()
        text = "credential=abc123"
        result = pat.sub("[REDACTED]", text)
        assert "abc123" not in result

    def test_redacts_auth(self):
        pat = self._get_pattern()
        text = "auth=token_xyz"
        result = pat.sub("[REDACTED]", text)
        assert "token_xyz" not in result

    def test_case_insensitive(self):
        pat = self._get_pattern()
        text = "API_KEY=secret123"
        result = pat.sub("[REDACTED]", text)
        assert "secret123" not in result

    def test_no_redaction_for_normal_text(self):
        pat = self._get_pattern()
        text = "The light in the kitchen is on"
        result = pat.sub("[REDACTED]", text)
        assert result == text

    def test_api_hyphen_key(self):
        pat = self._get_pattern()
        text = "api-key=test_value"
        result = pat.sub("[REDACTED]", text)
        assert "test_value" not in result


# ── _ErrorBufferHandler ─────────────────────────────────────────────


class TestErrorBufferHandler:
    def test_emit_appends_to_buffer(self):
        from assistant.main import _ErrorBufferHandler, _error_buffer

        handler = _ErrorBufferHandler(level=logging.WARNING)
        handler.setFormatter(logging.Formatter("%(message)s"))

        initial_len = len(_error_buffer)
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="Test warning",
            args=None,
            exc_info=None,
        )
        handler.emit(record)
        assert len(_error_buffer) > initial_len
        assert _error_buffer[-1]["level"] == "WARNING"
        assert "Test warning" in _error_buffer[-1]["message"]

    def test_emit_redacts_sensitive_data(self):
        from assistant.main import _ErrorBufferHandler, _error_buffer

        handler = _ErrorBufferHandler(level=logging.WARNING)
        handler.setFormatter(logging.Formatter("%(message)s"))

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="Failed with api_key=secret123",
            args=None,
            exc_info=None,
        )
        handler.emit(record)
        entry = _error_buffer[-1]
        assert "secret123" not in entry["message"]
        assert "[REDACTED]" in entry["message"]

    def test_emit_stores_timestamp(self):
        from assistant.main import _ErrorBufferHandler, _error_buffer

        handler = _ErrorBufferHandler(level=logging.WARNING)
        handler.setFormatter(logging.Formatter("%(message)s"))

        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="timestamp test",
            args=None,
            exc_info=None,
        )
        handler.emit(record)
        entry = _error_buffer[-1]
        assert "timestamp" in entry
        # Should be ISO format
        assert "T" in entry["timestamp"]

    def test_emit_stores_logger_name(self):
        from assistant.main import _ErrorBufferHandler, _error_buffer

        handler = _ErrorBufferHandler(level=logging.WARNING)
        handler.setFormatter(logging.Formatter("%(message)s"))

        record = logging.LogRecord(
            name="my.custom.logger",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="logger name test",
            args=None,
            exc_info=None,
        )
        handler.emit(record)
        assert _error_buffer[-1]["logger"] == "my.custom.logger"

    def test_emit_handles_format_error_gracefully(self):
        from assistant.main import _ErrorBufferHandler

        handler = _ErrorBufferHandler(level=logging.WARNING)
        # Set a formatter that will raise
        bad_formatter = MagicMock()
        bad_formatter.format = MagicMock(side_effect=ValueError("format boom"))
        handler.setFormatter(bad_formatter)

        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="will fail",
            args=None,
            exc_info=None,
        )
        # Should not raise
        handler.emit(record)


# ── _ActivityBufferHandler ──────────────────────────────────────────


class TestActivityBufferHandler:
    def test_emit_for_known_module(self):
        from assistant.main import _ActivityBufferHandler, _activity_buffer

        handler = _ActivityBufferHandler(level=logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))

        initial_len = len(_activity_buffer)
        record = logging.LogRecord(
            name="assistant.brain",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Brain activity",
            args=None,
            exc_info=None,
        )
        handler.emit(record)
        assert len(_activity_buffer) > initial_len
        assert _activity_buffer[-1]["module"] == "Brain"

    def test_emit_for_sub_module(self):
        from assistant.main import _ActivityBufferHandler, _activity_buffer

        handler = _ActivityBufferHandler(level=logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))

        initial_len = len(_activity_buffer)
        record = logging.LogRecord(
            name="assistant.proactive.seasonal",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Sub-module log",
            args=None,
            exc_info=None,
        )
        handler.emit(record)
        assert len(_activity_buffer) > initial_len

    def test_emit_ignores_unknown_module(self):
        from assistant.main import _ActivityBufferHandler, _activity_buffer

        handler = _ActivityBufferHandler(level=logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))

        initial_len = len(_activity_buffer)
        record = logging.LogRecord(
            name="some.other.module",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Should be ignored",
            args=None,
            exc_info=None,
        )
        handler.emit(record)
        assert len(_activity_buffer) == initial_len

    def test_emit_redacts_sensitive_data(self):
        from assistant.main import _ActivityBufferHandler, _activity_buffer

        handler = _ActivityBufferHandler(level=logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))

        record = logging.LogRecord(
            name="assistant.brain",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Using token=abc123",
            args=None,
            exc_info=None,
        )
        handler.emit(record)
        assert "abc123" not in _activity_buffer[-1]["message"]

    def test_emit_uses_module_label(self):
        from assistant.main import _ActivityBufferHandler, _activity_buffer

        handler = _ActivityBufferHandler(level=logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))

        record = logging.LogRecord(
            name="assistant.diagnostics",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Diagnostics",
            args=None,
            exc_info=None,
        )
        handler.emit(record)
        assert _activity_buffer[-1]["module"] == "Diagnostik"

    def test_emit_falls_back_to_last_part_of_name(self):
        from assistant.main import _ActivityBufferHandler, _activity_buffer

        handler = _ActivityBufferHandler(level=logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))

        # Sub-logger not in labels dict, should use last part
        record = logging.LogRecord(
            name="assistant.proactive.special_handler",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Special handler",
            args=None,
            exc_info=None,
        )
        handler.emit(record)
        # The parent "assistant.proactive" is in the set, but sub-logger uses
        # _ACTIVITY_MODULE_LABELS.get(record.name, record.name.split(".")[-1])
        # Since record.name is "assistant.proactive.special_handler", it won't be
        # directly in labels, so falls back to "special_handler"
        assert _activity_buffer[-1]["module"] == "special_handler"

    def test_emit_handles_format_error_gracefully(self):
        from assistant.main import _ActivityBufferHandler

        handler = _ActivityBufferHandler(level=logging.INFO)
        bad_formatter = MagicMock()
        bad_formatter.format = MagicMock(side_effect=ValueError("format boom"))
        handler.setFormatter(bad_formatter)

        record = logging.LogRecord(
            name="assistant.brain",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="will fail",
            args=None,
            exc_info=None,
        )
        # Should not raise
        handler.emit(record)


# ── _restore_error_buffer / _persist_error_buffer ───────────────────


class TestErrorBufferPersistence:
    @pytest.mark.asyncio
    async def test_restore_with_data(self):
        from assistant.main import _restore_error_buffer, _error_buffer

        entries = [
            {
                "timestamp": "2026-01-01T00:00:00",
                "level": "WARNING",
                "logger": "test",
                "message": "old error",
            },
            {
                "timestamp": "2026-01-01T00:01:00",
                "level": "ERROR",
                "logger": "test",
                "message": "old error 2",
            },
        ]
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=json.dumps(entries))

        initial_len = len(_error_buffer)
        count = await _restore_error_buffer(redis)
        assert count == 2
        assert len(_error_buffer) >= initial_len + 2

    @pytest.mark.asyncio
    async def test_restore_empty(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)

        from assistant.main import _restore_error_buffer

        count = await _restore_error_buffer(redis)
        assert count == 0

    @pytest.mark.asyncio
    async def test_restore_error_returns_zero(self):
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=Exception("Redis down"))

        from assistant.main import _restore_error_buffer

        count = await _restore_error_buffer(redis)
        assert count == 0

    @pytest.mark.asyncio
    async def test_persist_stores_to_redis(self):
        from assistant.main import (
            _persist_error_buffer,
            _error_buffer,
            _REDIS_ERROR_BUFFER_KEY,
            _REDIS_ERROR_BUFFER_TTL,
        )

        redis = AsyncMock()
        redis.set = AsyncMock()

        # Add something to the buffer
        _error_buffer.append(
            {"timestamp": "now", "level": "WARNING", "logger": "t", "message": "m"}
        )

        await _persist_error_buffer(redis)
        redis.set.assert_called_once()
        call_args = redis.set.call_args
        assert call_args[0][0] == _REDIS_ERROR_BUFFER_KEY
        assert call_args[1]["ex"] == _REDIS_ERROR_BUFFER_TTL

    @pytest.mark.asyncio
    async def test_persist_error_does_not_raise(self):
        redis = AsyncMock()
        redis.set = AsyncMock(side_effect=Exception("Redis down"))

        from assistant.main import _persist_error_buffer

        # Should not raise
        await _persist_error_buffer(redis)


# ── _restore_activity_buffer / _persist_activity_buffer ─────────────


class TestActivityBufferPersistence:
    @pytest.mark.asyncio
    async def test_restore_with_data(self):
        from assistant.main import _restore_activity_buffer, _activity_buffer

        entries = [
            {
                "timestamp": "2026-01-01T00:00:00",
                "level": "INFO",
                "module": "Brain",
                "logger": "assistant.brain",
                "message": "activity",
            },
        ]
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=json.dumps(entries))

        initial_len = len(_activity_buffer)
        count = await _restore_activity_buffer(redis)
        assert count == 1
        assert len(_activity_buffer) >= initial_len + 1

    @pytest.mark.asyncio
    async def test_restore_empty(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)

        from assistant.main import _restore_activity_buffer

        count = await _restore_activity_buffer(redis)
        assert count == 0

    @pytest.mark.asyncio
    async def test_restore_error_returns_zero(self):
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=Exception("Redis down"))

        from assistant.main import _restore_activity_buffer

        count = await _restore_activity_buffer(redis)
        assert count == 0

    @pytest.mark.asyncio
    async def test_persist_stores_to_redis(self):
        from assistant.main import (
            _persist_activity_buffer,
            _activity_buffer,
            _REDIS_ACTIVITY_BUFFER_KEY,
            _REDIS_ACTIVITY_BUFFER_TTL,
        )

        redis = AsyncMock()
        redis.set = AsyncMock()

        _activity_buffer.append(
            {
                "timestamp": "now",
                "level": "INFO",
                "module": "t",
                "logger": "t",
                "message": "m",
            }
        )

        await _persist_activity_buffer(redis)
        redis.set.assert_called_once()
        call_args = redis.set.call_args
        assert call_args[0][0] == _REDIS_ACTIVITY_BUFFER_KEY
        assert call_args[1]["ex"] == _REDIS_ACTIVITY_BUFFER_TTL

    @pytest.mark.asyncio
    async def test_persist_truncates_to_500(self):
        from assistant.main import _persist_activity_buffer, _activity_buffer

        redis = AsyncMock()
        redis.set = AsyncMock()

        # Add 600 entries
        for i in range(600):
            _activity_buffer.append(
                {
                    "timestamp": str(i),
                    "level": "INFO",
                    "module": "t",
                    "logger": "t",
                    "message": f"msg_{i}",
                }
            )

        await _persist_activity_buffer(redis)
        # Check that persisted data has at most 500 entries
        stored_data = json.loads(redis.set.call_args[0][1])
        assert len(stored_data) <= 500

    @pytest.mark.asyncio
    async def test_persist_error_does_not_raise(self):
        redis = AsyncMock()
        redis.set = AsyncMock(side_effect=Exception("Redis down"))

        from assistant.main import _persist_activity_buffer

        # Should not raise
        await _persist_activity_buffer(redis)


# ── _boot_announcement ──────────────────────────────────────────────


class TestBootAnnouncement:
    @pytest.mark.asyncio
    async def test_basic_boot_message(self):
        from assistant.main import _boot_announcement

        brain_mock = MagicMock()
        brain_mock.ha = AsyncMock()
        brain_mock.ha.get_states = AsyncMock(return_value=[])
        brain_mock.sound_manager = MagicMock()
        brain_mock.sound_manager.play_event_sound = AsyncMock()
        brain_mock.sound_manager.speak_response = AsyncMock()

        health = {"components": {}}
        cfg = {"delay_seconds": 0}

        with (
            patch("assistant.main.yaml_config", {"room_temperature": {}}),
            patch("assistant.main.emit_speaking", new_callable=AsyncMock) as mock_emit,
            patch("assistant.main.get_person_title", return_value="Sir"),
        ):
            await _boot_announcement(brain_mock, health, cfg)
            mock_emit.assert_called_once()
            msg = mock_emit.call_args[0][0]
            assert "Sir" in msg
            assert "Keine Auffaelligkeiten" in msg

    @pytest.mark.asyncio
    async def test_boot_with_temperature_sensors(self):
        from assistant.main import _boot_announcement

        brain_mock = MagicMock()
        brain_mock.ha = AsyncMock()
        brain_mock.ha.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "sensor.temp_wohnzimmer",
                    "state": "21.5",
                    "attributes": {},
                },
                {
                    "entity_id": "sensor.temp_schlafzimmer",
                    "state": "20.5",
                    "attributes": {},
                },
            ]
        )
        brain_mock.sound_manager = MagicMock()
        brain_mock.sound_manager.play_event_sound = AsyncMock()
        brain_mock.sound_manager.speak_response = AsyncMock()

        health = {"components": {}}
        cfg = {"delay_seconds": 0}

        with (
            patch(
                "assistant.main.yaml_config",
                {
                    "room_temperature": {
                        "sensors": [
                            "sensor.temp_wohnzimmer",
                            "sensor.temp_schlafzimmer",
                        ]
                    },
                },
            ),
            patch("assistant.main.emit_speaking", new_callable=AsyncMock) as mock_emit,
            patch("assistant.main.get_person_title", return_value="Sir"),
        ):
            await _boot_announcement(brain_mock, health, cfg)
            msg = mock_emit.call_args[0][0]
            assert "21" in msg  # Average of 21.5 and 20.5 = 21.0
            assert "Grad" in msg

    @pytest.mark.asyncio
    async def test_boot_with_climate_fallback(self):
        from assistant.main import _boot_announcement

        brain_mock = MagicMock()
        brain_mock.ha = AsyncMock()
        brain_mock.ha.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "climate.wohnzimmer",
                    "state": "heat",
                    "attributes": {"current_temperature": 22.0},
                },
            ]
        )
        brain_mock.sound_manager = MagicMock()
        brain_mock.sound_manager.play_event_sound = AsyncMock()
        brain_mock.sound_manager.speak_response = AsyncMock()

        health = {"components": {}}
        cfg = {"delay_seconds": 0}

        with (
            patch("assistant.main.yaml_config", {"room_temperature": {"sensors": []}}),
            patch("assistant.main.emit_speaking", new_callable=AsyncMock) as mock_emit,
            patch("assistant.main.get_person_title", return_value="Sir"),
            patch("assistant.function_calling.is_window_or_door", return_value=False),
        ):
            await _boot_announcement(brain_mock, health, cfg)
            msg = mock_emit.call_args[0][0]
            assert "22" in msg
            assert "Grad" in msg

    @pytest.mark.asyncio
    async def test_boot_with_open_windows(self):
        from assistant.main import _boot_announcement

        brain_mock = MagicMock()
        brain_mock.ha = AsyncMock()
        brain_mock.ha.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "binary_sensor.fenster_kueche",
                    "state": "on",
                    "attributes": {"friendly_name": "Fenster Kueche"},
                },
            ]
        )
        brain_mock.sound_manager = MagicMock()
        brain_mock.sound_manager.play_event_sound = AsyncMock()
        brain_mock.sound_manager.speak_response = AsyncMock()

        health = {"components": {}}
        cfg = {"delay_seconds": 0}

        with (
            patch("assistant.main.yaml_config", {"room_temperature": {}}),
            patch("assistant.main.emit_speaking", new_callable=AsyncMock) as mock_emit,
            patch("assistant.main.get_person_title", return_value="Sir"),
            patch("assistant.function_calling.is_window_or_door", return_value=True),
            patch("assistant.function_calling.get_opening_type", return_value="window"),
        ):
            await _boot_announcement(brain_mock, health, cfg)
            msg = mock_emit.call_args[0][0]
            assert "Offen" in msg
            assert "Fenster Kueche" in msg

    @pytest.mark.asyncio
    async def test_boot_skips_gates(self):
        from assistant.main import _boot_announcement

        brain_mock = MagicMock()
        brain_mock.ha = AsyncMock()
        brain_mock.ha.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "binary_sensor.gartentor",
                    "state": "on",
                    "attributes": {"friendly_name": "Gartentor"},
                },
            ]
        )
        brain_mock.sound_manager = MagicMock()
        brain_mock.sound_manager.play_event_sound = AsyncMock()
        brain_mock.sound_manager.speak_response = AsyncMock()

        health = {"components": {}}
        cfg = {"delay_seconds": 0}

        with (
            patch("assistant.main.yaml_config", {"room_temperature": {}}),
            patch("assistant.main.emit_speaking", new_callable=AsyncMock) as mock_emit,
            patch("assistant.main.get_person_title", return_value="Sir"),
            patch("assistant.function_calling.is_window_or_door", return_value=True),
            patch("assistant.function_calling.get_opening_type", return_value="gate"),
        ):
            await _boot_announcement(brain_mock, health, cfg)
            msg = mock_emit.call_args[0][0]
            assert "Gartentor" not in msg

    @pytest.mark.asyncio
    async def test_boot_with_many_open_items(self):
        from assistant.main import _boot_announcement

        brain_mock = MagicMock()
        states = [
            {
                "entity_id": f"binary_sensor.window_{i}",
                "state": "on",
                "attributes": {"friendly_name": f"Window {i}"},
            }
            for i in range(5)
        ]
        brain_mock.ha = AsyncMock()
        brain_mock.ha.get_states = AsyncMock(return_value=states)
        brain_mock.sound_manager = MagicMock()
        brain_mock.sound_manager.play_event_sound = AsyncMock()
        brain_mock.sound_manager.speak_response = AsyncMock()

        health = {"components": {}}
        cfg = {"delay_seconds": 0}

        with (
            patch("assistant.main.yaml_config", {"room_temperature": {}}),
            patch("assistant.main.emit_speaking", new_callable=AsyncMock) as mock_emit,
            patch("assistant.main.get_person_title", return_value="Sir"),
            patch("assistant.function_calling.is_window_or_door", return_value=True),
            patch("assistant.function_calling.get_opening_type", return_value="window"),
        ):
            await _boot_announcement(brain_mock, health, cfg)
            msg = mock_emit.call_args[0][0]
            assert "5 Fenster oder Tueren sind offen" in msg

    @pytest.mark.asyncio
    async def test_boot_with_failed_components(self):
        from assistant.main import _boot_announcement

        brain_mock = MagicMock()
        brain_mock.ha = AsyncMock()
        brain_mock.ha.get_states = AsyncMock(return_value=[])
        brain_mock.sound_manager = MagicMock()
        brain_mock.sound_manager.play_event_sound = AsyncMock()
        brain_mock.sound_manager.speak_response = AsyncMock()

        health = {
            "components": {
                "redis": "connected",
                "ollama": "error: timeout",
                "ha": "disconnected",
            }
        }
        cfg = {"delay_seconds": 0}

        with (
            patch("assistant.main.yaml_config", {"room_temperature": {}}),
            patch("assistant.main.emit_speaking", new_callable=AsyncMock) as mock_emit,
            patch("assistant.main.get_person_title", return_value="Sir"),
        ):
            await _boot_announcement(brain_mock, health, cfg)
            msg = mock_emit.call_args[0][0]
            assert "2 Systeme eingeschränkt" in msg

    @pytest.mark.asyncio
    async def test_boot_single_failed_component(self):
        from assistant.main import _boot_announcement

        brain_mock = MagicMock()
        brain_mock.ha = AsyncMock()
        brain_mock.ha.get_states = AsyncMock(return_value=[])
        brain_mock.sound_manager = MagicMock()
        brain_mock.sound_manager.play_event_sound = AsyncMock()
        brain_mock.sound_manager.speak_response = AsyncMock()

        health = {"components": {"ollama": "error: timeout"}}
        cfg = {"delay_seconds": 0}

        with (
            patch("assistant.main.yaml_config", {"room_temperature": {}}),
            patch("assistant.main.emit_speaking", new_callable=AsyncMock) as mock_emit,
            patch("assistant.main.get_person_title", return_value="Sir"),
        ):
            await _boot_announcement(brain_mock, health, cfg)
            msg = mock_emit.call_args[0][0]
            assert "1 System eingeschränkt" in msg

    @pytest.mark.asyncio
    async def test_boot_custom_messages(self):
        from assistant.main import _boot_announcement

        brain_mock = MagicMock()
        brain_mock.ha = AsyncMock()
        brain_mock.ha.get_states = AsyncMock(return_value=[])
        brain_mock.sound_manager = MagicMock()
        brain_mock.sound_manager.play_event_sound = AsyncMock()
        brain_mock.sound_manager.speak_response = AsyncMock()

        health = {"components": {}}
        cfg = {"delay_seconds": 0, "messages": ["Custom boot message, Sir."]}

        with (
            patch("assistant.main.yaml_config", {"room_temperature": {}}),
            patch("assistant.main.emit_speaking", new_callable=AsyncMock) as mock_emit,
            patch("assistant.main.get_person_title", return_value="Sir"),
        ):
            await _boot_announcement(brain_mock, health, cfg)
            msg = mock_emit.call_args[0][0]
            assert msg.startswith("Custom boot message")

    @pytest.mark.asyncio
    async def test_boot_exception_fallback(self):
        from assistant.main import _boot_announcement

        brain_mock = MagicMock()
        brain_mock.ha = AsyncMock()
        brain_mock.ha.get_states = AsyncMock(side_effect=Exception("HA down"))

        health = {"components": {}}
        cfg = {"delay_seconds": 0}

        with (
            patch("assistant.main.yaml_config", {"room_temperature": {}}),
            patch("assistant.main.emit_speaking", new_callable=AsyncMock) as mock_emit,
            patch("assistant.main.get_person_title", return_value="Sir"),
        ):
            await _boot_announcement(brain_mock, health, cfg)
            mock_emit.assert_called_once()
            msg = mock_emit.call_args[0][0]
            assert "Sir" in msg

    @pytest.mark.asyncio
    async def test_boot_without_sound_manager(self):
        from assistant.main import _boot_announcement

        brain_mock = MagicMock(spec=[])  # No attributes
        brain_mock.ha = AsyncMock()
        brain_mock.ha.get_states = AsyncMock(return_value=[])

        health = {"components": {}}
        cfg = {"delay_seconds": 0}

        with (
            patch("assistant.main.yaml_config", {"room_temperature": {}}),
            patch("assistant.main.emit_speaking", new_callable=AsyncMock) as mock_emit,
            patch("assistant.main.get_person_title", return_value="Sir"),
        ):
            await _boot_announcement(brain_mock, health, cfg)
            mock_emit.assert_called_once()


# ── _check_api_key ──────────────────────────────────────────────────


class TestCheckApiKey:
    def test_valid_header_key(self):
        from assistant.main import _check_api_key, _assistant_api_key

        request = MagicMock()
        request.headers = {"x-api-key": _assistant_api_key}
        request.query_params = {}

        assert _check_api_key(request) is True

    def test_valid_query_key(self):
        from assistant.main import _check_api_key, _assistant_api_key

        request = MagicMock()
        request.headers = {}
        request.query_params = {"api_key": _assistant_api_key}

        assert _check_api_key(request) is True

    def test_invalid_key(self):
        from assistant.main import _check_api_key

        request = MagicMock()
        request.headers = {"x-api-key": "wrong_key"}
        request.query_params = {}

        assert _check_api_key(request) is False

    def test_no_key_provided(self):
        from assistant.main import _check_api_key

        request = MagicMock()
        request.headers = {}
        request.query_params = {}

        assert _check_api_key(request) is False

    def test_header_takes_precedence_over_query(self):
        from assistant.main import _check_api_key, _assistant_api_key

        request = MagicMock()
        request.headers = {"x-api-key": _assistant_api_key}
        request.query_params = {"api_key": "wrong"}

        assert _check_api_key(request) is True


# ── API Key Exempt Paths ────────────────────────────────────────────


class TestApiKeyExemptPaths:
    def test_health_exempt(self):
        from assistant.main import _API_KEY_EXEMPT_PATHS

        assert "/api/assistant/health" in _API_KEY_EXEMPT_PATHS

    def test_ws_exempt(self):
        from assistant.main import _API_KEY_EXEMPT_PATHS

        assert "/api/assistant/ws" in _API_KEY_EXEMPT_PATHS

    def test_root_exempt(self):
        from assistant.main import _API_KEY_EXEMPT_PATHS

        assert "/" in _API_KEY_EXEMPT_PATHS

    def test_docs_exempt(self):
        from assistant.main import _API_KEY_EXEMPT_PATHS

        assert "/docs" in _API_KEY_EXEMPT_PATHS

    def test_chat_not_exempt(self):
        from assistant.main import _API_KEY_EXEMPT_PATHS

        assert "/api/assistant/chat" not in _API_KEY_EXEMPT_PATHS


# ── Pydantic Models ─────────────────────────────────────────────────


class TestPydanticModels:
    def test_chat_request_minimal(self):
        from assistant.main import ChatRequest

        req = ChatRequest(text="Hallo")
        assert req.text == "Hallo"
        assert req.person is None
        assert req.room is None

    def test_chat_request_full(self):
        from assistant.main import ChatRequest

        req = ChatRequest(
            text="Licht an",
            person="Max",
            room="wohnzimmer",
            speaker_confidence=0.95,
            voice_metadata={"pitch": 120},
            device_id="sat_1",
        )
        assert req.person == "Max"
        assert req.room == "wohnzimmer"
        assert req.speaker_confidence == 0.95
        assert req.voice_metadata == {"pitch": 120}
        assert req.device_id == "sat_1"

    def test_tts_info_defaults(self):
        from assistant.main import TTSInfo

        tts = TTSInfo()
        assert tts.text == ""
        assert tts.ssml == ""
        assert tts.message_type == "casual"
        assert tts.speed == 100
        assert tts.volume == 0.8
        assert tts.target_speaker is None

    def test_tts_info_custom(self):
        from assistant.main import TTSInfo

        tts = TTSInfo(text="Hallo", speed=120, volume=1.0, target_speaker="wohnzimmer")
        assert tts.text == "Hallo"
        assert tts.speed == 120
        assert tts.target_speaker == "wohnzimmer"

    def test_chat_response_minimal(self):
        from assistant.main import ChatResponse

        resp = ChatResponse(response="Alles klar")
        assert resp.response == "Alles klar"
        assert resp.actions == []
        assert resp.model_used == ""
        assert resp.tts is None

    def test_chat_response_full(self):
        from assistant.main import ChatResponse, TTSInfo

        tts = TTSInfo(text="spoken text")
        resp = ChatResponse(
            response="Done",
            actions=[{"type": "set_light"}],
            model_used="llama3",
            context_room="kueche",
            tts=tts,
        )
        assert len(resp.actions) == 1
        assert resp.model_used == "llama3"
        assert resp.tts.text == "spoken text"

    def test_feedback_request(self):
        from assistant.main import FeedbackRequest

        req = FeedbackRequest(feedback_type="acknowledged", event_type="smoke")
        assert req.feedback_type == "acknowledged"
        assert req.event_type == "smoke"

    def test_settings_update_defaults(self):
        from assistant.main import SettingsUpdate

        update = SettingsUpdate()
        assert update.autonomy_level is None

    def test_settings_update_with_level(self):
        from assistant.main import SettingsUpdate

        update = SettingsUpdate(autonomy_level=3)
        assert update.autonomy_level == 3


# ── Activity Loggers Set ────────────────────────────────────────────


class TestActivityLoggers:
    def test_contains_brain(self):
        from assistant.main import _ACTIVITY_LOGGERS

        assert "assistant.brain" in _ACTIVITY_LOGGERS

    def test_contains_proactive(self):
        from assistant.main import _ACTIVITY_LOGGERS

        assert "assistant.proactive" in _ACTIVITY_LOGGERS

    def test_contains_personality(self):
        from assistant.main import _ACTIVITY_LOGGERS

        assert "assistant.personality" in _ACTIVITY_LOGGERS

    def test_contains_mindhome_assistant(self):
        from assistant.main import _ACTIVITY_LOGGERS

        assert "mindhome-assistant" in _ACTIVITY_LOGGERS


# ── Activity Module Labels ──────────────────────────────────────────


class TestActivityModuleLabels:
    def test_brain_label(self):
        from assistant.main import _ACTIVITY_MODULE_LABELS

        assert _ACTIVITY_MODULE_LABELS["assistant.brain"] == "Brain"

    def test_proactive_label(self):
        from assistant.main import _ACTIVITY_MODULE_LABELS

        assert _ACTIVITY_MODULE_LABELS["assistant.proactive"] == "Proaktiv"

    def test_system_label(self):
        from assistant.main import _ACTIVITY_MODULE_LABELS

        assert _ACTIVITY_MODULE_LABELS["mindhome-assistant"] == "System"

    def test_all_loggers_have_labels(self):
        from assistant.main import _ACTIVITY_LOGGERS, _ACTIVITY_MODULE_LABELS

        for logger_name in _ACTIVITY_LOGGERS:
            assert logger_name in _ACTIVITY_MODULE_LABELS, (
                f"{logger_name} missing label"
            )


# ── Buffer Constants ────────────────────────────────────────────────


class TestBufferConstants:
    def test_error_buffer_is_deque(self):
        from assistant.main import _error_buffer

        assert isinstance(_error_buffer, deque)

    def test_activity_buffer_is_deque(self):
        from assistant.main import _activity_buffer

        assert isinstance(_activity_buffer, deque)

    def test_redis_error_key(self):
        from assistant.main import _REDIS_ERROR_BUFFER_KEY

        assert _REDIS_ERROR_BUFFER_KEY == "mha:error_buffer"

    def test_redis_activity_key(self):
        from assistant.main import _REDIS_ACTIVITY_BUFFER_KEY

        assert _REDIS_ACTIVITY_BUFFER_KEY == "mha:activity_buffer"

    def test_error_buffer_ttl_7_days(self):
        from assistant.main import _REDIS_ERROR_BUFFER_TTL

        assert _REDIS_ERROR_BUFFER_TTL == 7 * 86400

    def test_activity_buffer_ttl_3_days(self):
        from assistant.main import _REDIS_ACTIVITY_BUFFER_TTL

        assert _REDIS_ACTIVITY_BUFFER_TTL == 3 * 86400


# ── _periodic_token_cleanup ─────────────────────────────────────────


class TestPeriodicTokenCleanup:
    @pytest.mark.asyncio
    async def test_runs_cleanup_loop(self):
        from assistant.main import _periodic_token_cleanup

        with (
            patch(
                "assistant.main.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=[None, asyncio.CancelledError()],
            ),
            patch(
                "assistant.main._cleanup_expired_tokens", new_callable=AsyncMock
            ) as mock_cleanup,
        ):
            with pytest.raises(asyncio.CancelledError):
                await _periodic_token_cleanup()
            mock_cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_error_does_not_crash(self):
        from assistant.main import _periodic_token_cleanup

        call_count = 0

        async def sleep_side_effect(_):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        with (
            patch("assistant.main.TOKEN_CLEANUP_INTERVAL", 0),
            patch(
                "asyncio.sleep", new_callable=AsyncMock, side_effect=sleep_side_effect
            ),
            patch(
                "assistant.main._cleanup_expired_tokens",
                new_callable=AsyncMock,
                side_effect=Exception("boom"),
            ),
        ):
            with pytest.raises(asyncio.CancelledError):
                await _periodic_token_cleanup()


# ── Error Buffer maxlen ─────────────────────────────────────────────


class TestErrorBufferMaxlen:
    def test_error_buffer_has_maxlen(self):
        from assistant.main import _error_buffer
        from assistant.constants import ERROR_BUFFER_MAX_SIZE

        assert _error_buffer.maxlen == ERROR_BUFFER_MAX_SIZE

    def test_activity_buffer_has_maxlen(self):
        from assistant.main import _activity_buffer
        from assistant.constants import ACTIVITY_BUFFER_MAX_SIZE

        assert _activity_buffer.maxlen == ACTIVITY_BUFFER_MAX_SIZE
