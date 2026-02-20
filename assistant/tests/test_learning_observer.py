"""
Tests fuer LearningObserver — Muster-Erkennung + Wochentag + Response-Handling.
"""

import json
from unittest.mock import AsyncMock

import pytest

from assistant.learning_observer import (
    KEY_MANUAL_ACTIONS,
    KEY_PATTERNS,
    KEY_RESPONSES,
    KEY_SUGGESTED,
    KEY_WEEKDAY_PATTERNS,
    WEEKDAY_NAMES_DE,
    LearningObserver,
)


@pytest.fixture
def observer():
    o = LearningObserver()
    o.redis = AsyncMock()
    o.enabled = True
    o.min_repetitions = 3
    return o


class TestObserveStateChange:
    """Tests fuer observe_state_change()."""

    @pytest.mark.asyncio
    async def test_records_manual_action(self, observer):
        observer.redis.get.return_value = None  # Kein Jarvis-Marker
        observer.redis.incr.return_value = 1
        await observer.observe_state_change("light.wohnzimmer", "on", "off")
        observer.redis.lpush.assert_called_once()
        observer.redis.ltrim.assert_called_once()

    @pytest.mark.asyncio
    async def test_ignores_jarvis_action(self, observer):
        observer.redis.get.return_value = "1"  # Jarvis-Marker gesetzt
        await observer.observe_state_change("light.wohnzimmer", "on", "off")
        observer.redis.lpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_irrelevant_domain(self, observer):
        observer.redis.get.return_value = None
        await observer.observe_state_change("sensor.temperature", "22", "21")
        observer.redis.lpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_unavailable(self, observer):
        observer.redis.get.return_value = None
        await observer.observe_state_change("light.flur", "unavailable", "on")
        observer.redis.lpush.assert_not_called()


class TestCheckPattern:
    """Tests fuer _check_pattern() und Vorschlags-Generierung."""

    @pytest.mark.asyncio
    async def test_no_suggestion_below_threshold(self, observer):
        observer.redis.incr.return_value = 2  # Unter min_repetitions
        callback = AsyncMock()
        observer._notify_callback = callback
        await observer._check_pattern("light.wz:on", "22:00", "light.wz", "on")
        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_suggestion_at_threshold(self, observer):
        observer.redis.incr.return_value = 3
        observer.redis.get.return_value = None  # Noch nicht vorgeschlagen
        callback = AsyncMock()
        observer._notify_callback = callback
        await observer._check_pattern("light.wz:on", "22:00", "light.wz", "on")
        callback.assert_called_once()
        msg = callback.call_args[0][0]
        assert msg["type"] == "learning_suggestion"
        assert msg["time_slot"] == "22:00"

    @pytest.mark.asyncio
    async def test_no_duplicate_suggestion(self, observer):
        observer.redis.incr.return_value = 5
        observer.redis.get.return_value = "1"  # Schon vorgeschlagen
        callback = AsyncMock()
        observer._notify_callback = callback
        await observer._check_pattern("light.wz:on", "22:00", "light.wz", "on")
        callback.assert_not_called()


class TestWeekdayPattern:
    """Tests fuer _check_weekday_pattern()."""

    @pytest.mark.asyncio
    async def test_weekday_suggestion(self, observer):
        observer.redis.incr.return_value = 3
        # Kein taeglicher Vorschlag, kein Wochentag-Vorschlag
        observer.redis.get.side_effect = [None, None]
        callback = AsyncMock()
        observer._notify_callback = callback

        await observer._check_weekday_pattern("light.wz:on", "22:00", 0, "light.wz", "on")

        callback.assert_called_once()
        msg = callback.call_args[0][0]
        assert msg["weekday"] == 0
        assert msg["weekday_name"] == "Montag"
        assert "Montag" in msg["message"]

    @pytest.mark.asyncio
    async def test_weekday_skipped_if_daily_exists(self, observer):
        observer.redis.incr.return_value = 3
        observer.redis.get.side_effect = ["1"]  # Taeglich schon vorgeschlagen
        callback = AsyncMock()
        observer._notify_callback = callback
        await observer._check_weekday_pattern("light.wz:on", "22:00", 2, "light.wz", "on")
        callback.assert_not_called()


class TestHandleResponse:
    """Tests fuer handle_response()."""

    @pytest.mark.asyncio
    async def test_accept_response(self, observer):
        result = await observer.handle_response("light.wohnzimmer", "22:00", accepted=True)
        assert "vorgemerkt" in result
        observer.redis.lpush.assert_called_once()

    @pytest.mark.asyncio
    async def test_reject_response(self, observer):
        result = await observer.handle_response("light.wohnzimmer", "22:00", accepted=False)
        assert "nicht automatisieren" in result

    @pytest.mark.asyncio
    async def test_no_redis_error(self, observer):
        observer.redis = None
        result = await observer.handle_response("light.wz", "22:00", accepted=True)
        assert "Fehler" in result


class TestWeekdayNames:
    def test_all_days(self):
        assert len(WEEKDAY_NAMES_DE) == 7
        assert WEEKDAY_NAMES_DE[0] == "Montag"
        assert WEEKDAY_NAMES_DE[6] == "Sonntag"
