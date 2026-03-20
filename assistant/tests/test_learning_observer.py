"""
Tests fuer LearningObserver — Muster-Erkennung + Wochentag + Response-Handling.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

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

    @pytest.mark.asyncio
    async def test_cluster_callback_at_min_repetitions(self, observer):
        """Callback wird exakt bei min_repetitions (3) ausgeloest."""
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)

        recent1 = json.dumps({
            "entity_id": "light.wohnzimmer",
            "new_state": "on",
            "domain": "light",
            "timestamp": (now - timedelta(seconds=60)).isoformat(),
        })
        recent2 = json.dumps({
            "entity_id": "cover.wohnzimmer",
            "new_state": "closed",
            "domain": "cover",
            "timestamp": (now - timedelta(seconds=120)).isoformat(),
        })
        observer.redis.lrange = AsyncMock(return_value=[recent1, recent2])
        # count == min_repetitions (3) → trigger callback
        observer.redis.incr = AsyncMock(return_value=3)

        action = {
            "entity_id": "switch.wohnzimmer",
            "new_state": "on",
            "domain": "switch",
            "timestamp": now.isoformat(),
            "time_slot": "22:00",
        }
        await observer._check_temporal_cluster(action, person="max")

        observer._notify_callback.assert_called_once()
        msg = observer._notify_callback.call_args[0][0]
        assert msg["type"] == "temporal_cluster"
        assert msg["count"] == 3
        assert msg["person"] == "max"
        assert msg["time_slot"] == "22:00"
        assert "cluster_name" in msg
        assert len(msg["actions"]) >= 2

    @pytest.mark.asyncio
    async def test_cluster_no_callback_below_min_repetitions(self, observer):
        """Callback wird NICHT ausgeloest wenn count < min_repetitions."""
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)

        recent1 = json.dumps({
            "entity_id": "light.wohnzimmer",
            "new_state": "on",
            "domain": "light",
            "timestamp": (now - timedelta(seconds=60)).isoformat(),
        })
        recent2 = json.dumps({
            "entity_id": "cover.wohnzimmer",
            "new_state": "closed",
            "domain": "cover",
            "timestamp": (now - timedelta(seconds=120)).isoformat(),
        })
        observer.redis.lrange = AsyncMock(return_value=[recent1, recent2])
        observer.redis.incr = AsyncMock(return_value=2)  # Below threshold

        action = {
            "entity_id": "switch.wohnzimmer",
            "new_state": "on",
            "domain": "switch",
            "timestamp": now.isoformat(),
        }
        await observer._check_temporal_cluster(action)
        observer._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_cluster_no_callback_above_min_repetitions(self, observer):
        """Callback wird NICHT erneut ausgeloest wenn count > min_repetitions."""
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)

        recent1 = json.dumps({
            "entity_id": "light.wohnzimmer",
            "new_state": "on",
            "domain": "light",
            "timestamp": (now - timedelta(seconds=60)).isoformat(),
        })
        recent2 = json.dumps({
            "entity_id": "cover.wohnzimmer",
            "new_state": "closed",
            "domain": "cover",
            "timestamp": (now - timedelta(seconds=120)).isoformat(),
        })
        observer.redis.lrange = AsyncMock(return_value=[recent1, recent2])
        observer.redis.incr = AsyncMock(return_value=5)  # Above threshold

        action = {
            "entity_id": "switch.wohnzimmer",
            "new_state": "on",
            "domain": "switch",
            "timestamp": now.isoformat(),
        }
        await observer._check_temporal_cluster(action)
        observer._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_cluster_first_observation_sets_expire_and_details(self, observer):
        """Erste Beobachtung (count=1) setzt TTL und speichert Cluster-Details."""
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)

        recent1 = json.dumps({
            "entity_id": "light.flur",
            "new_state": "on",
            "domain": "light",
            "timestamp": (now - timedelta(seconds=30)).isoformat(),
        })
        recent2 = json.dumps({
            "entity_id": "light.kueche",
            "new_state": "on",
            "domain": "light",
            "timestamp": (now - timedelta(seconds=90)).isoformat(),
        })
        observer.redis.lrange = AsyncMock(return_value=[recent1, recent2])
        observer.redis.incr = AsyncMock(return_value=1)

        action = {
            "entity_id": "light.bad",
            "new_state": "on",
            "domain": "light",
            "timestamp": now.isoformat(),
            "time_slot": "07:30",
        }
        await observer._check_temporal_cluster(action)

        # expire should be called for count_key AND details key
        assert observer.redis.expire.call_count == 2
        observer.redis.hset.assert_called_once()

    @pytest.mark.asyncio
    async def test_cluster_old_actions_excluded(self, observer):
        """Aktionen aelter als 5 Minuten werden nicht in den Cluster aufgenommen."""
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)

        old_action = json.dumps({
            "entity_id": "light.wohnzimmer",
            "new_state": "on",
            "domain": "light",
            "timestamp": (now - timedelta(seconds=600)).isoformat(),  # 10 min ago
        })
        recent_action = json.dumps({
            "entity_id": "cover.wohnzimmer",
            "new_state": "closed",
            "domain": "cover",
            "timestamp": (now - timedelta(seconds=60)).isoformat(),
        })
        observer.redis.lrange = AsyncMock(return_value=[old_action, recent_action])

        action = {
            "entity_id": "switch.wohnzimmer",
            "new_state": "on",
            "domain": "switch",
            "timestamp": now.isoformat(),
        }
        await observer._check_temporal_cluster(action)
        # Only 1 recent action within 5 min → not enough for cluster
        observer.redis.incr.assert_not_called()

    @pytest.mark.asyncio
    async def test_cluster_no_callback_when_none(self, observer):
        """Kein Fehler wenn _notify_callback None ist bei min_repetitions."""
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)

        recent1 = json.dumps({
            "entity_id": "light.wohnzimmer",
            "new_state": "on",
            "domain": "light",
            "timestamp": (now - timedelta(seconds=60)).isoformat(),
        })
        recent2 = json.dumps({
            "entity_id": "cover.wohnzimmer",
            "new_state": "closed",
            "domain": "cover",
            "timestamp": (now - timedelta(seconds=120)).isoformat(),
        })
        observer.redis.lrange = AsyncMock(return_value=[recent1, recent2])
        observer.redis.incr = AsyncMock(return_value=3)
        observer._notify_callback = None

        action = {
            "entity_id": "switch.wohnzimmer",
            "new_state": "on",
            "domain": "switch",
            "timestamp": now.isoformat(),
        }
        # Should not raise
        await observer._check_temporal_cluster(action)

    @pytest.mark.asyncio
    async def test_cluster_exception_is_caught(self, observer):
        """Exception in _check_temporal_cluster wird abgefangen."""
        observer.redis.lrange = AsyncMock(side_effect=Exception("Redis down"))

        action = {
            "entity_id": "light.wohnzimmer",
            "new_state": "on",
            "domain": "light",
            "timestamp": "2026-03-20T10:00:00+00:00",
        }
        # Should not raise
        await observer._check_temporal_cluster(action)

    @pytest.mark.asyncio
    async def test_cluster_global_key_when_no_person(self, observer):
        """Ohne Person wird 'global' im Cluster-Key verwendet."""
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)

        recent1 = json.dumps({
            "entity_id": "light.wohnzimmer",
            "new_state": "on",
            "domain": "light",
            "timestamp": (now - timedelta(seconds=60)).isoformat(),
        })
        recent2 = json.dumps({
            "entity_id": "cover.wohnzimmer",
            "new_state": "closed",
            "domain": "cover",
            "timestamp": (now - timedelta(seconds=120)).isoformat(),
        })
        observer.redis.lrange = AsyncMock(return_value=[recent1, recent2])
        observer.redis.incr = AsyncMock(return_value=1)

        action = {
            "entity_id": "switch.wohnzimmer",
            "new_state": "on",
            "domain": "switch",
            "timestamp": now.isoformat(),
        }
        await observer._check_temporal_cluster(action, person="")

        incr_key = observer.redis.incr.call_args[0][0]
        assert "global" in incr_key

    @pytest.mark.asyncio
    async def test_cluster_deduplicates_actions(self, observer):
        """Doppelte entity:state Paare werden im Cluster dedupliziert — kein Cluster bei <2 unique."""
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)

        # Gleiche Aktion zweimal → nur 1 unique in cluster_actions
        dup1 = json.dumps({
            "entity_id": "light.wohnzimmer",
            "new_state": "on",
            "domain": "light",
            "timestamp": (now - timedelta(seconds=60)).isoformat(),
        })
        dup2 = json.dumps({
            "entity_id": "light.wohnzimmer",
            "new_state": "on",
            "domain": "light",
            "timestamp": (now - timedelta(seconds=120)).isoformat(),
        })
        observer.redis.lrange = AsyncMock(return_value=[dup1, dup2])

        action = {
            "entity_id": "switch.wohnzimmer",
            "new_state": "on",
            "domain": "switch",
            "timestamp": now.isoformat(),
        }
        await observer._check_temporal_cluster(action)
        # Only 1 unique recent action after dedup → below threshold of 2 → no cluster
        observer.redis.incr.assert_not_called()

    @pytest.mark.asyncio
    async def test_cluster_auto_name_contains_domains(self, observer):
        """Auto-Name enthaelt die beteiligten Domains."""
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)

        recent1 = json.dumps({
            "entity_id": "light.wohnzimmer",
            "new_state": "on",
            "domain": "light",
            "timestamp": (now - timedelta(seconds=60)).isoformat(),
        })
        recent2 = json.dumps({
            "entity_id": "cover.wohnzimmer",
            "new_state": "closed",
            "domain": "cover",
            "timestamp": (now - timedelta(seconds=120)).isoformat(),
        })
        observer.redis.lrange = AsyncMock(return_value=[recent1, recent2])
        observer.redis.incr = AsyncMock(return_value=3)

        action = {
            "entity_id": "switch.wohnzimmer",
            "new_state": "on",
            "domain": "switch",
            "timestamp": now.isoformat(),
            "time_slot": "08:00",
        }
        await observer._check_temporal_cluster(action)

        msg = observer._notify_callback.call_args[0][0]
        # Auto-name is built from recent (cluster_actions) domains, not current action
        assert "cover" in msg["cluster_name"]
        assert "light" in msg["cluster_name"]
        assert "0800" in msg["cluster_name"]


# =====================================================================
# B8: Dynamic Skill Acquisition — Abstract Concepts
# =====================================================================


class TestExtractConceptName:
    """Tests fuer _extract_concept_name() — abstrakte Konzepte aus User-Text."""

    @pytest.fixture
    def observer(self):
        o = LearningObserver()
        o.redis = AsyncMock()
        o.enabled = True
        o.min_repetitions = 3
        return o

    def test_known_concepts(self, observer):
        """Bekannte Trigger werden korrekt extrahiert."""
        assert observer._extract_concept_name("Feierabend!") == "feierabend"
        assert observer._extract_concept_name("Gute Nacht, Jarvis") == "gute_nacht"
        assert observer._extract_concept_name("Starte den Filmabend") == "filmabend"
        assert observer._extract_concept_name("Guten Morgen") == "guten_morgen"
        assert observer._extract_concept_name("Ich will chillen") == "entspannung"
        assert observer._extract_concept_name("Party machen") == "party"
        assert observer._extract_concept_name("Partymodus aktivieren") == "party"
        assert observer._extract_concept_name("Schlafenszeit") == "gute_nacht"
        assert observer._extract_concept_name("Die Gaeste kommen gleich") == "gaeste"
        assert observer._extract_concept_name("Besuch kommt") == "gaeste"
        assert observer._extract_concept_name("Gaming-Session starten") == "gaming"

    def test_unknown_text_returns_empty(self, observer):
        assert observer._extract_concept_name("Wie ist das Wetter?") == ""
        assert observer._extract_concept_name("Mach das Licht an") == ""
        assert observer._extract_concept_name("") == ""

    def test_case_insensitive(self, observer):
        assert observer._extract_concept_name("FEIERABEND") == "feierabend"
        assert observer._extract_concept_name("Morgenroutine") == "morgenroutine"

    def test_synonyms_map_to_same_concept(self, observer):
        """Synonyme wie 'chillen' und 'entspannung' ergeben das gleiche Konzept."""
        assert observer._extract_concept_name("Entspannung bitte") == "entspannung"
        assert observer._extract_concept_name("Ich will chillen") == "entspannung"
        assert observer._extract_concept_name("Kochen wir was") == "kochmodus"
        assert observer._extract_concept_name("Kochmodus an") == "kochmodus"


class TestObserveAbstractAction:
    """Tests fuer observe_abstract_action() — B8 Beobachtung."""

    @pytest.fixture
    def observer(self):
        o = LearningObserver()
        o.redis = AsyncMock()
        o.enabled = True
        o.min_repetitions = 3
        o._notify_callback = AsyncMock()
        return o

    @pytest.mark.asyncio
    async def test_disabled_observer_skips(self, observer):
        observer.enabled = False
        await observer.observe_abstract_action(
            [{"entity_id": "light.wz", "new_state": "on"},
             {"entity_id": "cover.wz", "new_state": "closed"}],
            "Feierabend",
        )
        observer.redis.lpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_redis_skips(self, observer):
        observer.redis = None
        await observer.observe_abstract_action(
            [{"entity_id": "light.wz", "new_state": "on"},
             {"entity_id": "cover.wz", "new_state": "closed"}],
            "Feierabend",
        )

    @pytest.mark.asyncio
    async def test_less_than_2_actions_skips(self, observer):
        await observer.observe_abstract_action(
            [{"entity_id": "light.wz", "new_state": "on"}],
            "Feierabend",
        )
        observer.redis.lpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_concept_text_skips(self, observer):
        await observer.observe_abstract_action(
            [{"entity_id": "light.wz", "new_state": "on"},
             {"entity_id": "cover.wz", "new_state": "closed"}],
            "Mach das Licht an",
        )
        observer.redis.lpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_records_observation_below_threshold(self, observer):
        """Observation wird gespeichert, aber Konzept noch nicht erstellt."""
        observer.redis.llen = AsyncMock(return_value=2)  # below min_observations
        await observer.observe_abstract_action(
            [{"entity_id": "light.wz", "new_state": "on"},
             {"entity_id": "cover.wz", "new_state": "closed"}],
            "Feierabend",
        )
        observer.redis.lpush.assert_called_once()
        observer.redis.ltrim.assert_called_once()
        observer.redis.expire.assert_called()

    @pytest.mark.asyncio
    async def test_triggers_concept_creation_at_threshold(self, observer):
        """Ab min_observations wird _maybe_create_concept aufgerufen."""
        observer.redis.llen = AsyncMock(return_value=3)
        # _maybe_create_concept will try to lrange; return empty to short-circuit
        observer.redis.lrange = AsyncMock(return_value=[])
        await observer.observe_abstract_action(
            [{"entity_id": "light.wz", "new_state": "on"},
             {"entity_id": "cover.wz", "new_state": "closed"}],
            "Feierabend",
            person="julia",
        )
        observer.redis.lpush.assert_called_once()

    @pytest.mark.asyncio
    async def test_exception_is_caught(self, observer):
        """Exception in observe_abstract_action wird abgefangen."""
        observer.redis.lpush = AsyncMock(side_effect=Exception("Redis error"))
        # Should not raise
        await observer.observe_abstract_action(
            [{"entity_id": "light.wz", "new_state": "on"},
             {"entity_id": "cover.wz", "new_state": "closed"}],
            "Feierabend",
        )

    @pytest.mark.asyncio
    async def test_dynamic_skills_disabled_skips(self, observer):
        """Wenn dynamic_skills.enabled=False, wird nicht beobachtet."""
        with patch("assistant.learning_observer.yaml_config", {"timezone": "Europe/Berlin", "dynamic_skills": {"enabled": False}, "learning": {}}):
            await observer.observe_abstract_action(
                [{"entity_id": "light.wz", "new_state": "on"},
                 {"entity_id": "cover.wz", "new_state": "closed"}],
                "Feierabend",
            )
            observer.redis.lpush.assert_not_called()


class TestMaybeCreateConcept:
    """Tests fuer _maybe_create_concept() — B8 Konzept-Erstellung."""

    @pytest.fixture
    def observer(self):
        o = LearningObserver()
        o.redis = AsyncMock()
        o.enabled = True
        o.min_repetitions = 3
        o._notify_callback = AsyncMock()
        return o

    @pytest.mark.asyncio
    async def test_no_observations_returns(self, observer):
        observer.redis.lrange = AsyncMock(return_value=[])
        await observer._maybe_create_concept("feierabend", "key", "", {"min_observations": 3})
        observer.redis.hset.assert_not_called()

    @pytest.mark.asyncio
    async def test_too_few_observations_returns(self, observer):
        observer.redis.lrange = AsyncMock(return_value=[
            json.dumps({"actions": ["light.wz:on"], "hour": 18, "weekday": 0}),
        ])
        await observer._maybe_create_concept("feierabend", "key", "", {"min_observations": 3})
        observer.redis.hset.assert_not_called()

    @pytest.mark.asyncio
    async def test_already_existing_concept_skips(self, observer):
        obs_data = json.dumps({"actions": ["light.wz:on", "cover.wz:closed"], "hour": 18, "weekday": 0})
        observer.redis.lrange = AsyncMock(return_value=[obs_data, obs_data, obs_data])
        observer.redis.hget = AsyncMock(return_value='{"name": "feierabend"}')  # Already exists
        await observer._maybe_create_concept("feierabend", "key", "", {"min_observations": 3})
        # hset should NOT be called because concept already exists
        observer.redis.hset.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_concept_with_core_actions(self, observer):
        """Konzept wird erstellt wenn genug gemeinsame Aktionen vorhanden."""
        obs = json.dumps({
            "actions": ["light.wz:on", "cover.wz:closed", "climate.wz:heat"],
            "hour": 18,
            "weekday": 0,
        })
        observer.redis.lrange = AsyncMock(return_value=[obs, obs, obs])
        observer.redis.hget = AsyncMock(return_value=None)  # Not existing yet
        await observer._maybe_create_concept("feierabend", "key", "julia", {"min_observations": 3})
        observer.redis.hset.assert_called_once()
        # Verify the concept data
        call_args = observer.redis.hset.call_args
        concept_data = json.loads(call_args[0][2])
        assert concept_data["name"] == "feierabend"
        assert len(concept_data["core_actions"]) >= 2
        assert concept_data["person"] == "julia"
        assert concept_data["typical_hour"] == 18
        # Callback should be called
        observer._notify_callback.assert_called_once()
        msg = observer._notify_callback.call_args[0][0]
        assert msg["type"] == "concept_learned"
        assert msg["concept"] == "feierabend"

    @pytest.mark.asyncio
    async def test_too_few_core_actions_skips(self, observer):
        """Weniger als 2 gemeinsame Kern-Aktionen → kein Konzept."""
        # Each observation has different actions → no action reaches 50% threshold
        obs1 = json.dumps({"actions": ["light.wz:on", "cover.wz:closed"], "hour": 18, "weekday": 0})
        obs2 = json.dumps({"actions": ["light.flur:on", "switch.wz:on"], "hour": 19, "weekday": 1})
        obs3 = json.dumps({"actions": ["climate.wz:heat", "media_player.wz:playing"], "hour": 20, "weekday": 2})
        observer.redis.lrange = AsyncMock(return_value=[obs1, obs2, obs3])
        observer.redis.hget = AsyncMock(return_value=None)
        await observer._maybe_create_concept("feierabend", "key", "", {"min_observations": 3})
        observer.redis.hset.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_callback_when_none(self, observer):
        """Kein Fehler wenn _notify_callback None ist."""
        obs = json.dumps({
            "actions": ["light.wz:on", "cover.wz:closed"],
            "hour": 18,
            "weekday": 0,
        })
        observer.redis.lrange = AsyncMock(return_value=[obs, obs, obs])
        observer.redis.hget = AsyncMock(return_value=None)
        observer._notify_callback = None
        # Should not raise
        await observer._maybe_create_concept("feierabend", "key", "", {"min_observations": 3})
        observer.redis.hset.assert_called_once()

    @pytest.mark.asyncio
    async def test_exception_is_caught(self, observer):
        observer.redis.lrange = AsyncMock(side_effect=Exception("Redis down"))
        # Should not raise
        await observer._maybe_create_concept("feierabend", "key", "", {"min_observations": 3})


class TestGetConcept:
    """Tests fuer get_concept() — B8 Konzept-Laden."""

    @pytest.fixture
    def observer(self):
        o = LearningObserver()
        o.redis = AsyncMock()
        o.enabled = True
        return o

    @pytest.mark.asyncio
    async def test_no_redis_returns_none(self, observer):
        observer.redis = None
        result = await observer.get_concept("feierabend")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_concept(self, observer):
        concept = {"name": "feierabend", "core_actions": ["light.wz:on"]}
        observer.redis.hget = AsyncMock(return_value=json.dumps(concept))
        result = await observer.get_concept("feierabend")
        assert result["name"] == "feierabend"

    @pytest.mark.asyncio
    async def test_person_fallback_to_global(self, observer):
        """Wenn kein person-spezifisches Konzept existiert, Fallback auf global."""
        global_concept = {"name": "feierabend", "core_actions": ["light.wz:on"]}
        observer.redis.hget = AsyncMock(side_effect=[None, json.dumps(global_concept)])
        result = await observer.get_concept("feierabend", person="julia")
        assert result is not None
        assert result["name"] == "feierabend"
        # Should have been called twice: once for julia-specific, once for global
        assert observer.redis.hget.call_count == 2

    @pytest.mark.asyncio
    async def test_not_found_returns_none(self, observer):
        observer.redis.hget = AsyncMock(return_value=None)
        result = await observer.get_concept("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_exception_returns_none(self, observer):
        observer.redis.hget = AsyncMock(side_effect=Exception("fail"))
        result = await observer.get_concept("feierabend")
        assert result is None

    @pytest.mark.asyncio
    async def test_bytes_response(self, observer):
        """Redis kann bytes zurueckgeben statt str."""
        concept = {"name": "feierabend"}
        observer.redis.hget = AsyncMock(return_value=json.dumps(concept).encode())
        result = await observer.get_concept("feierabend")
        assert result["name"] == "feierabend"


class TestGetAllConcepts:
    """Tests fuer get_all_concepts() — B8 alle Konzepte auflisten."""

    @pytest.fixture
    def observer(self):
        o = LearningObserver()
        o.redis = AsyncMock()
        o.enabled = True
        return o

    @pytest.mark.asyncio
    async def test_no_redis(self, observer):
        observer.redis = None
        result = await observer.get_all_concepts()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_all_concepts(self, observer):
        observer.redis.hgetall = AsyncMock(return_value={
            "feierabend": json.dumps({"name": "feierabend"}),
            "julia:filmabend": json.dumps({"name": "filmabend", "person": "julia"}),
        })
        result = await observer.get_all_concepts()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_filter_by_person(self, observer):
        observer.redis.hgetall = AsyncMock(return_value={
            "feierabend": json.dumps({"name": "feierabend"}),
            "julia:filmabend": json.dumps({"name": "filmabend"}),
            "max:gaming": json.dumps({"name": "gaming"}),
        })
        result = await observer.get_all_concepts(person="julia")
        # Should include "julia:filmabend" and "feierabend" (no person prefix → global)
        names = [c["name"] for c in result]
        assert "filmabend" in names
        assert "feierabend" in names
        assert "gaming" not in names

    @pytest.mark.asyncio
    async def test_invalid_json_skipped(self, observer):
        observer.redis.hgetall = AsyncMock(return_value={
            "feierabend": "invalid json{{{",
            "filmabend": json.dumps({"name": "filmabend"}),
        })
        result = await observer.get_all_concepts()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self, observer):
        observer.redis.hgetall = AsyncMock(side_effect=Exception("fail"))
        result = await observer.get_all_concepts()
        assert result == []

    @pytest.mark.asyncio
    async def test_bytes_keys_and_values(self, observer):
        observer.redis.hgetall = AsyncMock(return_value={
            b"feierabend": json.dumps({"name": "feierabend"}).encode(),
        })
        result = await observer.get_all_concepts()
        assert len(result) == 1
        assert result[0]["name"] == "feierabend"


# =====================================================================
# B12: Proaktives Selbst-Lernen — Wissenslücken
# =====================================================================


class TestObserveKnowledgeGap:
    """Tests fuer observe_knowledge_gap() — B12 proaktives Lernen."""

    @pytest.fixture
    def observer(self):
        o = LearningObserver()
        o.redis = AsyncMock()
        o.enabled = True
        o._notify_callback = AsyncMock()
        return o

    @pytest.mark.asyncio
    async def test_disabled_skips(self, observer):
        observer.enabled = False
        await observer.observe_knowledge_gap("Was ist X?", tool_failed=True)
        observer._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_redis_skips(self, observer):
        observer.redis = None
        await observer.observe_knowledge_gap("Was ist X?", tool_failed=True)
        observer._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_callback_skips(self, observer):
        observer._notify_callback = None
        await observer.observe_knowledge_gap("Was ist X?", tool_failed=True)

    @pytest.mark.asyncio
    async def test_tool_failed_sends_notification(self, observer):
        observer.redis.get = AsyncMock(return_value=None)  # No cooldown
        await observer.observe_knowledge_gap("Schalte Lampe ein", tool_failed=True)
        observer._notify_callback.assert_called_once()
        msg = observer._notify_callback.call_args[0][0]
        assert msg["type"] == "knowledge_gap"
        assert "nicht funktioniert" in msg["message"]

    @pytest.mark.asyncio
    async def test_no_tool_match_long_text_sends(self, observer):
        observer.redis.get = AsyncMock(return_value=None)
        await observer.observe_knowledge_gap(
            "Kannst du bitte das Ding im Keller einschalten",
            no_tool_match=True,
        )
        observer._notify_callback.assert_called_once()
        msg = observer._notify_callback.call_args[0][0]
        assert "nicht sicher" in msg["message"]

    @pytest.mark.asyncio
    async def test_no_tool_match_short_text_skips(self, observer):
        """Kurze Texte (< 4 Woerter) werden bei no_tool_match ignoriert."""
        observer.redis.get = AsyncMock(return_value=None)
        await observer.observe_knowledge_gap("Hallo Jarvis", no_tool_match=True)
        observer._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_cooldown_prevents_repeat(self, observer):
        """Innerhalb des Cooldowns wird keine Frage gesendet."""
        from datetime import datetime, timezone
        recent = datetime.now(timezone.utc).isoformat()
        observer.redis.get = AsyncMock(return_value=recent)
        await observer.observe_knowledge_gap("Fehler passiert", tool_failed=True)
        observer._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_cooldown_expired_allows_question(self, observer):
        """Nach Cooldown-Ablauf wird wieder gefragt."""
        from datetime import datetime, timedelta, timezone
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        observer.redis.get = AsyncMock(return_value=old)
        await observer.observe_knowledge_gap("Fehler passiert", tool_failed=True)
        observer._notify_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_sets_cooldown_after_sending(self, observer):
        observer.redis.get = AsyncMock(return_value=None)
        await observer.observe_knowledge_gap("Fehler X", tool_failed=True)
        observer.redis.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_neither_failed_nor_no_match_no_message(self, observer):
        """Ohne tool_failed oder no_tool_match wird keine Nachricht gesendet."""
        observer.redis.get = AsyncMock(return_value=None)
        await observer.observe_knowledge_gap("Normaler Text")
        observer._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_self_learning_disabled_skips(self, observer):
        with patch("assistant.learning_observer.yaml_config", {"timezone": "Europe/Berlin", "self_learning": {"enabled": False}, "learning": {}}):
            await observer.observe_knowledge_gap("Fehler", tool_failed=True)
            observer._notify_callback.assert_not_called()


# =====================================================================
# [16] Auto-Learning: Device→Scene Trigger
# =====================================================================


class TestObserveSceneActivation:
    """Tests fuer observe_scene_activation() — [16] Szenen-Trigger."""

    @pytest.fixture
    def observer(self):
        o = LearningObserver()
        o.redis = AsyncMock()
        o.enabled = True
        o.min_repetitions = 3
        o._notify_callback = AsyncMock()
        return o

    @pytest.mark.asyncio
    async def test_disabled_skips(self, observer):
        observer.enabled = False
        await observer.observe_scene_activation("filmabend")
        observer.redis.lrange.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_redis_skips(self, observer):
        observer.redis = None
        await observer.observe_scene_activation("filmabend")

    @pytest.mark.asyncio
    async def test_no_recent_actions_skips(self, observer):
        observer.redis.lrange = AsyncMock(return_value=[])
        await observer.observe_scene_activation("filmabend")
        observer._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_relevant_trigger_domain_skips(self, observer):
        """Nur relevante Trigger-Domains (media_player, switch, etc.) werden beruecksichtigt."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        action = json.dumps({
            "entity_id": "light.wohnzimmer",  # light is NOT a trigger domain
            "new_state": "on",
            "timestamp": now.isoformat(),
        })
        observer.redis.lrange = AsyncMock(return_value=[action])
        await observer.observe_scene_activation("filmabend")
        observer._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_suggestion_at_threshold(self, observer):
        """Vorschlag wird bei min_repetitions generiert."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        action = json.dumps({
            "entity_id": "media_player.tv_wohnzimmer",
            "new_state": "on",
            "timestamp": now.isoformat(),
        })
        observer.redis.lrange = AsyncMock(return_value=[action])
        pipe_mock = MagicMock()
        pipe_mock.execute = AsyncMock(return_value=[3, -2])  # count=3, no TTL
        observer.redis.pipeline = MagicMock(return_value=pipe_mock)
        observer.redis.get = AsyncMock(return_value=None)  # Not suggested yet
        await observer.observe_scene_activation("filmabend", person="max")
        observer._notify_callback.assert_called_once()
        msg = observer._notify_callback.call_args[0][0]
        assert msg["type"] == "scene_device_suggestion"
        assert msg["trigger_entity"] == "media_player.tv_wohnzimmer"
        assert msg["scene_name"] == "filmabend"
        assert msg["count"] == 3

    @pytest.mark.asyncio
    async def test_already_suggested_skips(self, observer):
        """Bereits vorgeschlagene Patterns werden nicht erneut vorgeschlagen."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        action = json.dumps({
            "entity_id": "media_player.tv",
            "new_state": "on",
            "timestamp": now.isoformat(),
        })
        observer.redis.lrange = AsyncMock(return_value=[action])
        pipe_mock = MagicMock()
        pipe_mock.execute = AsyncMock(return_value=[3, 86400])
        observer.redis.pipeline = MagicMock(return_value=pipe_mock)
        observer.redis.get = AsyncMock(return_value="1")  # Already suggested
        await observer.observe_scene_activation("filmabend")
        observer._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_below_threshold_skips(self, observer):
        """Unter min_repetitions wird kein Vorschlag gemacht."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        action = json.dumps({
            "entity_id": "switch.tv_power",
            "new_state": "on",
            "timestamp": now.isoformat(),
        })
        observer.redis.lrange = AsyncMock(return_value=[action])
        pipe_mock = MagicMock()
        pipe_mock.execute = AsyncMock(return_value=[2, 86400])  # count=2 < 3
        observer.redis.pipeline = MagicMock(return_value=pipe_mock)
        await observer.observe_scene_activation("filmabend")
        observer._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_old_action_ignored(self, observer):
        """Aktionen aelter als 5 Minuten werden ignoriert."""
        from datetime import datetime, timedelta, timezone
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        action = json.dumps({
            "entity_id": "media_player.tv",
            "new_state": "on",
            "timestamp": old_time.isoformat(),
        })
        observer.redis.lrange = AsyncMock(return_value=[action])
        await observer.observe_scene_activation("filmabend")
        observer._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_exception_is_caught(self, observer):
        observer.redis.lrange = AsyncMock(side_effect=Exception("Redis down"))
        # Should not raise
        await observer.observe_scene_activation("filmabend")


# =====================================================================
# LLM-basierter Lern-Report
# =====================================================================


class TestFormatLearningReportLlm:
    """Tests fuer format_learning_report_llm() — LLM-Rewrite des Reports."""

    @pytest.fixture
    def observer(self):
        o = LearningObserver()
        o.redis = AsyncMock()
        o.enabled = True
        return o

    @pytest.mark.asyncio
    async def test_no_ollama_returns_fallback(self, observer):
        """Ohne Ollama wird der Template-Fallback verwendet."""
        report = {"patterns": [], "total_observations": 0, "suggestions_made": 0, "accepted": 0, "declined": 0}
        result = await observer.format_learning_report_llm(report)
        assert "Noch keine" in result

    @pytest.mark.asyncio
    async def test_llm_report_disabled_returns_fallback(self, observer):
        """Wenn llm_report=False, wird der Template-Fallback verwendet."""
        observer._ollama = AsyncMock()
        with patch("assistant.learning_observer.yaml_config", {"timezone": "Europe/Berlin", "learning": {"llm_report": False}}):
            report = {"patterns": [], "total_observations": 5, "suggestions_made": 0, "accepted": 0, "declined": 0}
            result = await observer.format_learning_report_llm(report)
            assert "5 manuelle Aktionen" in result

    @pytest.mark.asyncio
    async def test_llm_success_returns_generated_text(self, observer):
        """LLM-generierter Text wird zurueckgegeben wenn lang genug."""
        observer._ollama = AsyncMock()
        observer._ollama.generate = AsyncMock(return_value="Ich habe 50 Aktionen beobachtet und dabei 3 Muster erkannt.")
        with patch("assistant.learning_observer.yaml_config", {"timezone": "Europe/Berlin", "learning": {"llm_report": True}}), \
             patch("assistant.config.settings") as mock_settings:
            mock_settings.model_fast = "test-model"
            report = {"patterns": [], "total_observations": 50, "suggestions_made": 0, "accepted": 0, "declined": 0}
            result = await observer.format_learning_report_llm(report)
            assert "50 Aktionen" in result

    @pytest.mark.asyncio
    async def test_llm_short_response_falls_back(self, observer):
        """Zu kurze LLM-Antwort (<=20 Zeichen) → Fallback."""
        observer._ollama = AsyncMock()
        observer._ollama.generate = AsyncMock(return_value="Kurz.")
        with patch("assistant.learning_observer.yaml_config", {"timezone": "Europe/Berlin", "learning": {"llm_report": True}}), \
             patch("assistant.config.settings") as mock_settings:
            mock_settings.model_fast = "test-model"
            report = {"patterns": [], "total_observations": 10, "suggestions_made": 0, "accepted": 0, "declined": 0}
            result = await observer.format_learning_report_llm(report)
            assert "10 manuelle Aktionen" in result

    @pytest.mark.asyncio
    async def test_llm_exception_falls_back(self, observer):
        """LLM-Exception → Fallback."""
        observer._ollama = AsyncMock()
        observer._ollama.generate = AsyncMock(side_effect=Exception("LLM down"))
        with patch("assistant.learning_observer.yaml_config", {"timezone": "Europe/Berlin", "learning": {"llm_report": True}}), \
             patch("assistant.config.settings") as mock_settings:
            mock_settings.model_fast = "test-model"
            report = {"patterns": [], "total_observations": 10, "suggestions_made": 0, "accepted": 0, "declined": 0}
            result = await observer.format_learning_report_llm(report)
            assert "10 manuelle Aktionen" in result


# =====================================================================
# set_ollama
# =====================================================================


class TestSetOllama:
    def test_set_ollama(self):
        o = LearningObserver()
        mock_ollama = MagicMock()
        o.set_ollama(mock_ollama)
        assert o._ollama == mock_ollama


# =====================================================================
# Weekday patterns in get_learned_patterns
# =====================================================================


class TestGetLearnedPatternsWeekday:
    """Additional coverage for weekday pattern scanning in get_learned_patterns."""

    @pytest.fixture
    def observer(self):
        o = LearningObserver()
        o.redis = AsyncMock()
        o.enabled = True
        o.min_repetitions = 3
        return o

    @pytest.mark.asyncio
    async def test_weekday_patterns_included(self, observer):
        """Weekday patterns are scanned and included in results."""
        # First scan (daily patterns) returns empty
        # Second scan (weekday patterns) returns a match
        scan_calls = [0]

        async def fake_scan(cursor, match="", count=200):
            scan_calls[0] += 1
            if KEY_WEEKDAY_PATTERNS in match:
                if cursor == 0:
                    return (0, ["mha:learning:weekday_patterns:light.wz:on:22:00:0"])
                return (0, [])
            else:
                return (0, [])

        observer.redis.scan = AsyncMock(side_effect=fake_scan)
        observer.redis.mget = AsyncMock(return_value=["5"])
        result = await observer.get_learned_patterns()
        assert len(result) == 1
        assert result[0]["weekday"] == 0
        assert result[0]["count"] == 5

    @pytest.mark.asyncio
    async def test_weekday_patterns_with_person(self, observer):
        """Weekday patterns with person prefix are parsed correctly."""
        async def fake_scan(cursor, match="", count=200):
            if KEY_WEEKDAY_PATTERNS in match:
                if cursor == 0:
                    return (0, ["mha:learning:weekday_patterns:julia:light.wz:on:22:00:2"])
                return (0, [])
            return (0, [])

        observer.redis.scan = AsyncMock(side_effect=fake_scan)
        observer.redis.mget = AsyncMock(return_value=["4"])
        result = await observer.get_learned_patterns(person="julia")
        assert len(result) == 1
        assert result[0]["person"] == "julia"
        assert result[0]["weekday"] == 2

    @pytest.mark.asyncio
    async def test_weekday_scan_exception(self, observer):
        """Exception in weekday SCAN does not break the whole method."""
        # Daily scan works fine
        async def fake_scan(cursor, match="", count=200):
            if KEY_WEEKDAY_PATTERNS in match:
                raise Exception("weekday scan failed")
            return (0, [])

        observer.redis.scan = AsyncMock(side_effect=fake_scan)
        result = await observer.get_learned_patterns()
        assert result == []

    @pytest.mark.asyncio
    async def test_max_20_results(self, observer):
        """Results are capped at 20."""
        keys = [f"mha:learning:patterns:light.room{i}:on:22:0{i % 6}" for i in range(25)]
        async def fake_scan(cursor, match="", count=200):
            if KEY_PATTERNS in match and KEY_WEEKDAY_PATTERNS not in match:
                return (0, keys)
            return (0, [])
        observer.redis.scan = AsyncMock(side_effect=fake_scan)
        observer.redis.mget = AsyncMock(return_value=["5"] * 25)
        result = await observer.get_learned_patterns()
        assert len(result) <= 20

    @pytest.mark.asyncio
    async def test_results_sorted_by_count_desc(self, observer):
        """Results are sorted by count descending."""
        async def fake_scan(cursor, match="", count=200):
            if KEY_PATTERNS in match and KEY_WEEKDAY_PATTERNS not in match:
                return (0, [
                    "mha:learning:patterns:light.wz:on:22:00",
                    "mha:learning:patterns:light.flur:on:21:00",
                ])
            return (0, [])
        observer.redis.scan = AsyncMock(side_effect=fake_scan)
        observer.redis.mget = AsyncMock(return_value=["3", "7"])
        result = await observer.get_learned_patterns()
        assert len(result) == 2
        assert result[0]["count"] == 7  # Highest first
        assert result[1]["count"] == 3


# =====================================================================
# observe_scene_activation — Additional Edge Cases
# =====================================================================


class TestObserveSceneActivationEdgeCases:
    """Additional edge cases for observe_scene_activation."""

    @pytest.fixture
    def observer(self):
        o = LearningObserver()
        o.redis = AsyncMock()
        o.enabled = True
        o.min_repetitions = 3
        o._notify_callback = AsyncMock()
        return o

    @pytest.mark.asyncio
    async def test_auto_learning_disabled_in_config(self, observer):
        """Skips when auto_learning.enabled is False in scenes config."""
        with patch("assistant.learning_observer.yaml_config", {
            "timezone": "Europe/Berlin",
            "scenes": {"auto_learning": {"enabled": False}},
        }):
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            action = json.dumps({
                "entity_id": "media_player.tv",
                "new_state": "on",
                "timestamp": now.isoformat(),
            })
            observer.redis.lrange = AsyncMock(return_value=[action])
            await observer.observe_scene_activation("filmabend")
            observer._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_already_in_device_trigger_map(self, observer):
        """Skips when trigger_entity→scene is already configured in device_trigger_map."""
        with patch("assistant.learning_observer.yaml_config", {
            "timezone": "Europe/Berlin",
            "scenes": {
                "auto_learning": {"enabled": True},
                "device_trigger_map": {"media_player.tv": ["filmabend"]},
            },
        }):
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            action = json.dumps({
                "entity_id": "media_player.tv",
                "new_state": "on",
                "timestamp": now.isoformat(),
            })
            observer.redis.lrange = AsyncMock(return_value=[action])
            pipe_mock = MagicMock()
            pipe_mock.execute = AsyncMock(return_value=[5, 86400])  # count=5
            observer.redis.pipeline = MagicMock(return_value=pipe_mock)
            observer.redis.get = AsyncMock(return_value=None)  # Not suggested
            await observer.observe_scene_activation("filmabend")
            observer._notify_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_callback_still_completes(self, observer):
        """Runs without error even when no _notify_callback is set."""
        observer._notify_callback = None
        with patch("assistant.learning_observer.yaml_config", {
            "timezone": "Europe/Berlin",
            "scenes": {"auto_learning": {"enabled": True}},
        }):
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            action = json.dumps({
                "entity_id": "switch.tv_power",
                "new_state": "on",
                "timestamp": now.isoformat(),
            })
            observer.redis.lrange = AsyncMock(return_value=[action])
            pipe_mock = MagicMock()
            pipe_mock.execute = AsyncMock(return_value=[3, -2])
            observer.redis.pipeline = MagicMock(return_value=pipe_mock)
            observer.redis.get = AsyncMock(return_value=None)
            await observer.observe_scene_activation("filmabend")  # No exception

    @pytest.mark.asyncio
    async def test_sets_ttl_when_missing(self, observer):
        """Sets 60-day TTL when pattern key has no TTL."""
        with patch("assistant.learning_observer.yaml_config", {
            "timezone": "Europe/Berlin",
            "scenes": {"auto_learning": {"enabled": True}},
        }):
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            action = json.dumps({
                "entity_id": "switch.tv",
                "new_state": "on",
                "timestamp": now.isoformat(),
            })
            observer.redis.lrange = AsyncMock(return_value=[action])
            pipe_mock = MagicMock()
            pipe_mock.execute = AsyncMock(return_value=[1, -2])  # count=1, no TTL
            observer.redis.pipeline = MagicMock(return_value=pipe_mock)
            await observer.observe_scene_activation("filmabend")
            observer.redis.expire.assert_called_once()

    @pytest.mark.asyncio
    async def test_bytes_action_decoded(self, observer):
        """Bytes actions from Redis are decoded correctly."""
        with patch("assistant.learning_observer.yaml_config", {
            "timezone": "Europe/Berlin",
            "scenes": {"auto_learning": {"enabled": True}},
        }):
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            action = json.dumps({
                "entity_id": "switch.tv",
                "new_state": "on",
                "timestamp": now.isoformat(),
            }).encode()
            observer.redis.lrange = AsyncMock(return_value=[action])
            pipe_mock = MagicMock()
            pipe_mock.execute = AsyncMock(return_value=[1, 86400])
            observer.redis.pipeline = MagicMock(return_value=pipe_mock)
            await observer.observe_scene_activation("filmabend")  # No exception


# =====================================================================
# observe_abstract_action Edge Cases
# =====================================================================


class TestObserveAbstractActionEdgeCases:
    """Edge cases for observe_abstract_action."""

    @pytest.fixture
    def observer(self):
        o = LearningObserver()
        o.redis = AsyncMock()
        o.enabled = True
        return o

    @pytest.mark.asyncio
    async def test_disabled_skips(self, observer):
        observer.enabled = False
        await observer.observe_abstract_action([{"entity_id": "a", "new_state": "on"}], "Feierabend")
        observer.redis.lpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_redis_skips(self, observer):
        observer.redis = None
        await observer.observe_abstract_action([{"entity_id": "a", "new_state": "on"}], "Feierabend")

    @pytest.mark.asyncio
    async def test_less_than_two_actions_skips(self, observer):
        """Needs at least 2 actions for abstract concept."""
        with patch("assistant.learning_observer.yaml_config", {
            "timezone": "Europe/Berlin",
            "dynamic_skills": {"enabled": True},
        }):
            await observer.observe_abstract_action(
                [{"entity_id": "a", "new_state": "on"}],
                "Feierabend",
            )
            observer.redis.lpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_concept_name_extracted_skips(self, observer):
        """If no concept name extracted, skips."""
        with patch("assistant.learning_observer.yaml_config", {
            "timezone": "Europe/Berlin",
            "dynamic_skills": {"enabled": True},
        }):
            await observer.observe_abstract_action(
                [{"entity_id": "a", "new_state": "on"}, {"entity_id": "b", "new_state": "off"}],
                "Mach mal das Licht an und die Heizung aus",  # No abstract concept
            )
            observer.redis.lpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_stores_observation(self, observer):
        """Stores observation in Redis when concept name is found."""
        with patch("assistant.learning_observer.yaml_config", {
            "timezone": "Europe/Berlin",
            "dynamic_skills": {"enabled": True, "min_observations": 5},
        }):
            observer.redis.llen = AsyncMock(return_value=1)  # Not enough for concept
            await observer.observe_abstract_action(
                [{"entity_id": "light.wz", "new_state": "on"}, {"entity_id": "switch.tv", "new_state": "on"}],
                "Feierabend",
            )
            observer.redis.lpush.assert_called_once()
            observer.redis.ltrim.assert_called_once()

    @pytest.mark.asyncio
    async def test_dynamic_skills_disabled(self, observer):
        """Skips when dynamic_skills.enabled is False."""
        with patch("assistant.learning_observer.yaml_config", {
            "timezone": "Europe/Berlin",
            "dynamic_skills": {"enabled": False},
        }):
            await observer.observe_abstract_action(
                [{"entity_id": "a", "new_state": "on"}, {"entity_id": "b", "new_state": "off"}],
                "Feierabend",
            )
            observer.redis.lpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_exception_caught(self, observer):
        """Exceptions are caught gracefully."""
        with patch("assistant.learning_observer.yaml_config", {
            "timezone": "Europe/Berlin",
            "dynamic_skills": {"enabled": True},
        }):
            observer.redis.lpush = AsyncMock(side_effect=Exception("Redis error"))
            await observer.observe_abstract_action(
                [{"entity_id": "a", "new_state": "on"}, {"entity_id": "b", "new_state": "off"}],
                "Feierabend",
            )  # No exception raised


# =====================================================================
# format_learning_report edge cases
# =====================================================================


class TestFormatLearningReportEdgeCases:
    """Additional edge cases for format_learning_report."""

    def test_with_patterns(self):
        o = LearningObserver()
        report = {
            "patterns": [
                {"entity": "light.wz", "state": "on", "time": "22:00", "count": 5},
                {"entity": "cover.sz", "state": "close", "time": "23:00", "count": 3},
            ],
            "total_observations": 100,
            "suggestions_made": 2,
            "accepted": 1,
            "declined": 1,
        }
        result = o.format_learning_report(report)
        assert "100 manuelle Aktionen" in result
        assert "2 erkannte Muster" in result
        assert "1 akzeptiert" in result

    def test_zero_observations(self):
        o = LearningObserver()
        report = {
            "patterns": [],
            "total_observations": 0,
            "suggestions_made": 0,
            "accepted": 0,
            "declined": 0,
        }
        result = o.format_learning_report(report)
        assert "Noch keine" in result
