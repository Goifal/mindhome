"""
Tests fuer LearningObserver — Muster-Erkennung + Wochentag + Response-Handling.
"""

import json
from unittest.mock import AsyncMock, MagicMock

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
        pipe_mock = MagicMock()
        pipe_mock.execute = AsyncMock(return_value=[2, -2])  # count=2 (unter min_repetitions), ttl=-2
        observer.redis.pipeline = MagicMock(return_value=pipe_mock)
        callback = AsyncMock()
        observer._notify_callback = callback
        await observer._check_pattern("light.wz:on", "22:00", "light.wz", "on")
        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_suggestion_at_threshold(self, observer):
        pipe_mock = MagicMock()
        pipe_mock.execute = AsyncMock(return_value=[3, 2592000])  # count=3 (at threshold), ttl set
        observer.redis.pipeline = MagicMock(return_value=pipe_mock)
        observer.redis.get = AsyncMock(return_value=None)  # Noch nicht vorgeschlagen
        callback = AsyncMock()
        observer._notify_callback = callback
        await observer._check_pattern("light.wz:on", "22:00", "light.wz", "on")
        callback.assert_called_once()
        msg = callback.call_args[0][0]
        assert msg["type"] == "learning_suggestion"
        assert msg["time_slot"] == "22:00"

    @pytest.mark.asyncio
    async def test_no_duplicate_suggestion(self, observer):
        pipe_mock = MagicMock()
        pipe_mock.execute = AsyncMock(return_value=[5, 2592000])  # count=5, ttl set
        observer.redis.pipeline = MagicMock(return_value=pipe_mock)
        observer.redis.get = AsyncMock(return_value="1")  # Schon vorgeschlagen
        callback = AsyncMock()
        observer._notify_callback = callback
        await observer._check_pattern("light.wz:on", "22:00", "light.wz", "on")
        callback.assert_not_called()


class TestWeekdayPattern:
    """Tests fuer _check_weekday_pattern()."""

    @pytest.mark.asyncio
    async def test_weekday_suggestion(self, observer):
        observer.redis.incr.return_value = 3
        # Kein Automated-Marker, kein taeglicher Vorschlag, kein Wochentag-Vorschlag
        observer.redis.get.side_effect = [None, None, None]
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
        assert "Fehler" in result or "Redis" in result or "nicht ansprechbar" in result


class TestWeekdayNames:
    def test_all_days(self):
        assert len(WEEKDAY_NAMES_DE) == 7
        assert WEEKDAY_NAMES_DE[0] == "Montag"
        assert WEEKDAY_NAMES_DE[6] == "Sonntag"


# =====================================================================
# APPENDED TESTS — Additional coverage for uncovered branches
# =====================================================================


class TestParsePersonPrefix:
    def test_with_person(self):
        from assistant.learning_observer import _parse_person_prefix
        person, action = _parse_person_prefix("julia:light.wohnzimmer:on")
        assert person == "julia"
        assert action == "light.wohnzimmer:on"

    def test_without_person(self):
        from assistant.learning_observer import _parse_person_prefix
        person, action = _parse_person_prefix("light.wohnzimmer:on")
        assert person == ""
        assert action == "light.wohnzimmer:on"

    def test_entity_only(self):
        from assistant.learning_observer import _parse_person_prefix
        person, action = _parse_person_prefix("light.wz")
        assert person == ""
        assert action == "light.wz"


class TestObserveStateChangeExtended:
    @pytest.mark.asyncio
    async def test_disabled_observer(self, observer):
        observer.enabled = False
        await observer.observe_state_change("light.wz", "on", "off")
        observer.redis.lpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_redis(self, observer):
        observer.redis = None
        await observer.observe_state_change("light.wz", "on", "off")

    @pytest.mark.asyncio
    async def test_cover_domain(self, observer):
        observer.redis.get.return_value = None
        observer.redis.incr.return_value = 1
        pipe_mock = MagicMock()
        pipe_mock.execute = AsyncMock(return_value=[1, -2])
        observer.redis.pipeline = MagicMock(return_value=pipe_mock)
        await observer.observe_state_change("cover.wz", "open", "closed")
        observer.redis.lpush.assert_called_once()

    @pytest.mark.asyncio
    async def test_media_player_domain(self, observer):
        observer.redis.get.return_value = None
        observer.redis.incr.return_value = 1
        pipe_mock = MagicMock()
        pipe_mock.execute = AsyncMock(return_value=[1, -2])
        observer.redis.pipeline = MagicMock(return_value=pipe_mock)
        await observer.observe_state_change("media_player.wz", "playing", "idle")
        observer.redis.lpush.assert_called_once()

    @pytest.mark.asyncio
    async def test_with_person(self, observer):
        observer.redis.get.return_value = None
        observer.redis.incr.return_value = 1
        pipe_mock = MagicMock()
        pipe_mock.execute = AsyncMock(return_value=[1, -2])
        observer.redis.pipeline = MagicMock(return_value=pipe_mock)
        await observer.observe_state_change("light.wz", "on", "off", person="julia")
        observer.redis.lpush.assert_called_once()

    @pytest.mark.asyncio
    async def test_automated_entity_skipped(self, observer):
        """F-053: Cycle detection — automated entities are skipped."""
        async def fake_get(key):
            if "automated" in key:
                return "1"
            return None
        observer.redis.get = AsyncMock(side_effect=fake_get)
        await observer.observe_state_change("light.wz", "on", "off")
        observer.redis.lpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_exception_handling(self, observer):
        observer.redis.get.return_value = None
        observer.redis.lpush.side_effect = Exception("Redis error")
        # Should not raise
        await observer.observe_state_change("light.wz", "on", "off")


class TestCheckPatternExtended:
    @pytest.mark.asyncio
    async def test_pattern_with_person(self, observer):
        pipe_mock = MagicMock()
        pipe_mock.execute = AsyncMock(return_value=[3, 2592000])
        observer.redis.pipeline = MagicMock(return_value=pipe_mock)
        observer.redis.get = AsyncMock(return_value=None)
        callback = AsyncMock()
        observer._notify_callback = callback
        await observer._check_pattern("light.wz:on", "22:00", "light.wz", "on", person="julia")
        callback.assert_called_once()
        msg = callback.call_args[0][0]
        assert "julia" in msg.get("person", "")

    @pytest.mark.asyncio
    async def test_expire_set_on_first_incr(self, observer):
        pipe_mock = MagicMock()
        pipe_mock.execute = AsyncMock(return_value=[1, -2])
        observer.redis.pipeline = MagicMock(return_value=pipe_mock)
        await observer._check_pattern("light.wz:on", "22:00", "light.wz", "on")
        observer.redis.expire.assert_called()

    @pytest.mark.asyncio
    async def test_off_state_message(self, observer):
        pipe_mock = MagicMock()
        pipe_mock.execute = AsyncMock(return_value=[3, 2592000])
        observer.redis.pipeline = MagicMock(return_value=pipe_mock)
        observer.redis.get = AsyncMock(return_value=None)
        callback = AsyncMock()
        observer._notify_callback = callback
        await observer._check_pattern("light.wz:off", "22:00", "light.wz", "off")
        msg = callback.call_args[0][0]
        assert msg["new_state"] == "off"

    @pytest.mark.asyncio
    async def test_no_callback_set(self, observer):
        pipe_mock = MagicMock()
        pipe_mock.execute = AsyncMock(return_value=[3, 2592000])
        observer.redis.pipeline = MagicMock(return_value=pipe_mock)
        observer.redis.get = AsyncMock(return_value=None)
        observer._notify_callback = None
        await observer._check_pattern("light.wz:on", "22:00", "light.wz", "on")
        # Should not raise


class TestCheckWeekdayPatternExtended:
    @pytest.mark.asyncio
    async def test_weekday_automated_skipped(self, observer):
        """F-053: Automated weekday patterns are skipped."""
        async def fake_get(key):
            if "automated" in key:
                return "1"
            return None
        observer.redis.get = AsyncMock(side_effect=fake_get)
        callback = AsyncMock()
        observer._notify_callback = callback
        await observer._check_weekday_pattern("light.wz:on", "22:00", 0, "light.wz", "on")
        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_weekday_already_suggested(self, observer):
        observer.redis.incr.return_value = 3
        observer.redis.get.side_effect = [None, None, "1"]  # automated=None, daily=None, weekday=already
        callback = AsyncMock()
        observer._notify_callback = callback
        await observer._check_weekday_pattern("light.wz:on", "22:00", 2, "light.wz", "on")
        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_weekday_no_callback(self, observer):
        observer.redis.incr.return_value = 3
        observer.redis.get.side_effect = [None, None, None]
        observer._notify_callback = None
        await observer._check_weekday_pattern("light.wz:on", "22:00", 0, "light.wz", "on")

    @pytest.mark.asyncio
    async def test_weekday_with_person(self, observer):
        observer.redis.incr.return_value = 3
        observer.redis.get.side_effect = [None, None, None]
        callback = AsyncMock()
        observer._notify_callback = callback
        await observer._check_weekday_pattern("light.wz:on", "22:00", 0, "light.wz", "on", person="max")
        callback.assert_called_once()
        msg = callback.call_args[0][0]
        assert msg["person"] == "max"


class TestHandleResponseExtended:
    @pytest.mark.asyncio
    async def test_accept_with_weekday(self, observer):
        result = await observer.handle_response("light.wz", "22:00", accepted=True, weekday=2, person="max")
        assert "vorgemerkt" in result
        # Should set automated markers for weekday
        observer.redis.setex.assert_called()

    @pytest.mark.asyncio
    async def test_accept_without_weekday(self, observer):
        result = await observer.handle_response("light.wz", "22:00", accepted=True, weekday=-1)
        assert "vorgemerkt" in result

    @pytest.mark.asyncio
    async def test_reject_with_person(self, observer):
        result = await observer.handle_response("light.wz", "22:00", accepted=False, person="max")
        assert "nicht automatisieren" in result


class TestGetLearnedPatterns:
    @pytest.mark.asyncio
    async def test_no_redis(self, observer):
        observer.redis = None
        result = await observer.get_learned_patterns()
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_patterns(self, observer):
        observer.redis.scan = AsyncMock(return_value=(0, []))
        result = await observer.get_learned_patterns()
        assert result == []

    @pytest.mark.asyncio
    async def test_with_patterns(self, observer):
        observer.redis.scan = AsyncMock(side_effect=[
            (0, ["mha:learning:patterns:light.wz:on:22:00"]),
            (0, []),
        ])
        observer.redis.mget = AsyncMock(return_value=["5"])
        result = await observer.get_learned_patterns()
        assert len(result) >= 1
        assert result[0]["count"] == 5

    @pytest.mark.asyncio
    async def test_filter_by_person(self, observer):
        observer.redis.scan = AsyncMock(side_effect=[
            (0, ["mha:learning:patterns:julia:light.wz:on:22:00",
                 "mha:learning:patterns:light.flur:on:21:00"]),
            (0, []),
        ])
        observer.redis.mget = AsyncMock(return_value=["5", "3"])
        result = await observer.get_learned_patterns(person="julia")
        # Only julia patterns should appear
        for p in result:
            assert p["person"] == "julia"

    @pytest.mark.asyncio
    async def test_skip_low_count(self, observer):
        observer.redis.scan = AsyncMock(side_effect=[
            (0, ["mha:learning:patterns:light.wz:on:22:00"]),
            (0, []),
        ])
        observer.redis.mget = AsyncMock(return_value=["1"])
        result = await observer.get_learned_patterns()
        assert result == []

    @pytest.mark.asyncio
    async def test_exception_handling(self, observer):
        observer.redis.scan = AsyncMock(side_effect=Exception("scan failed"))
        result = await observer.get_learned_patterns()
        assert result == []


class TestGetLearningReport:
    @pytest.mark.asyncio
    async def test_no_redis(self, observer):
        observer.redis = None
        result = await observer.get_learning_report()
        assert result["total_observations"] == 0
        assert result["patterns"] == []

    @pytest.mark.asyncio
    async def test_with_data(self, observer):
        observer.redis.scan = AsyncMock(return_value=(0, []))
        observer.redis.llen = AsyncMock(return_value=50)
        observer.redis.lrange = AsyncMock(return_value=[
            json.dumps({"accepted": True}),
            json.dumps({"accepted": False}),
        ])
        result = await observer.get_learning_report()
        assert result["total_observations"] == 50
        assert result["accepted"] == 1
        assert result["declined"] == 1

    @pytest.mark.asyncio
    async def test_with_invalid_response_data(self, observer):
        observer.redis.scan = AsyncMock(return_value=(0, []))
        observer.redis.llen = AsyncMock(return_value=10)
        observer.redis.lrange = AsyncMock(return_value=[
            "invalid json",
            json.dumps({"accepted": True}),
        ])
        result = await observer.get_learning_report()
        assert result["accepted"] == 1


class TestFormatLearningReport:
    def test_empty_report(self, observer):
        report = {"patterns": [], "total_observations": 0, "suggestions_made": 0, "accepted": 0, "declined": 0}
        result = observer.format_learning_report(report)
        assert "Noch keine" in result

    def test_with_patterns(self, observer):
        report = {
            "patterns": [
                {"entity": "light.wz", "time_slot": "22:00", "count": 5, "weekday": -1, "action": "light.wz:on"},
                {"entity": "light.flur", "time_slot": "21:00", "count": 3, "weekday": 0, "action": "light.flur:off"},
            ],
            "total_observations": 50,
            "suggestions_made": 2,
            "accepted": 1,
            "declined": 1,
        }
        result = observer.format_learning_report(report)
        assert "50 manuelle Aktionen" in result
        assert "taeglich" in result
        assert "Montag" in result
        assert "2 Vorschläge" in result

    def test_only_observations_no_patterns(self, observer):
        report = {"patterns": [], "total_observations": 10, "suggestions_made": 0, "accepted": 0, "declined": 0}
        result = observer.format_learning_report(report)
        assert "10 manuelle Aktionen" in result

    def test_weekday_out_of_range(self, observer):
        report = {
            "patterns": [
                {"entity": "light.wz", "time_slot": "22:00", "count": 5, "weekday": 10, "action": "light.wz:on"},
            ],
            "total_observations": 5,
            "suggestions_made": 0,
            "accepted": 0,
            "declined": 0,
        }
        result = observer.format_learning_report(report)
        assert "taeglich" in result  # Invalid weekday → treated as daily


class TestMarkJarvisAction:
    @pytest.mark.asyncio
    async def test_mark_jarvis_action(self, observer):
        await observer.mark_jarvis_action("light.wz")
        observer.redis.setex.assert_called()

    @pytest.mark.asyncio
    async def test_mark_jarvis_no_redis(self, observer):
        observer.redis = None
        await observer.mark_jarvis_action("light.wz")


class TestSetNotifyCallback:
    def test_set_callback(self, observer):
        cb = AsyncMock()
        observer.set_notify_callback(cb)
        assert observer._notify_callback == cb


class TestInitialize:
    @pytest.mark.asyncio
    async def test_initialize(self, observer):
        redis = AsyncMock()
        await observer.initialize(redis)
        assert observer.redis == redis


# =====================================================================
# Phase 4.2: Temporal Auto-Clustering
# =====================================================================


class TestTemporalClustering:
    """Tests fuer _check_temporal_cluster() — automatische Cluster-Erkennung."""

    @pytest.fixture
    def observer(self):
        o = LearningObserver()
        o.redis = AsyncMock()
        o.enabled = True
        o.min_repetitions = 3
        o._notify_callback = AsyncMock()
        return o

    @pytest.mark.asyncio
    async def test_cluster_with_recent_actions(self, observer):
        """Mehrere manuelle Aktionen in 5 Min werden als Cluster erkannt."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        two_min_ago = (now - __import__("datetime").timedelta(seconds=120)).isoformat()
        three_min_ago = (now - __import__("datetime").timedelta(seconds=180)).isoformat()
        now_iso = now.isoformat()

        recent1 = json.dumps({
            "entity_id": "light.wohnzimmer",
            "new_state": "on",
            "domain": "light",
            "timestamp": two_min_ago,
        })
        recent2 = json.dumps({
            "entity_id": "cover.kueche",
            "new_state": "closed",
            "domain": "cover",
            "timestamp": three_min_ago,
        })
        observer.redis.lrange = AsyncMock(return_value=[recent1, recent2])
        observer.redis.incr = AsyncMock(return_value=1)

        action = {
            "entity_id": "cover.wohnzimmer",
            "new_state": "closed",
            "domain": "cover",
            "timestamp": now_iso,
        }
        await observer._check_temporal_cluster(action, person="max")
        observer.redis.incr.assert_called()

    @pytest.mark.asyncio
    async def test_no_cluster_with_single_action(self, observer):
        """Nur 1 kuerzliche Aktion reicht nicht fuer einen Cluster."""
        observer.redis.lrange = AsyncMock(return_value=["invalid_json"])

        action = {
            "entity_id": "light.wohnzimmer",
            "new_state": "on",
            "domain": "light",
            "timestamp": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc,
            ).isoformat(),
        }
        await observer._check_temporal_cluster(action)
        observer.redis.incr.assert_not_called()
