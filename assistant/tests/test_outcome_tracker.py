"""
Tests fuer OutcomeTracker — Wirkungstracker fuer Jarvis-Aktionen.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.outcome_tracker import (
    OutcomeTracker,
    OUTCOME_POSITIVE,
    OUTCOME_NEUTRAL,
    OUTCOME_PARTIAL,
    OUTCOME_NEGATIVE,
    DEFAULT_SCORE,
    MIN_OUTCOMES_FOR_SCORE,
    _extract_state_key,
)


@pytest.fixture
def tracker(redis_mock, ha_mock):
    t = OutcomeTracker()
    t.redis = redis_mock
    t.ha = ha_mock
    t.enabled = True
    t._task_registry = MagicMock()
    t._task_registry.create_task = MagicMock()
    t._observation_delay = 0  # Kein Delay fuer Tests
    return t


class TestTrackAction:
    """Tests fuer track_action()."""

    @pytest.mark.asyncio
    async def test_disabled_tracker_returns(self, tracker):
        tracker.enabled = False
        await tracker.track_action("set_light", {"room": "wohnzimmer"}, {"success": True})
        tracker.redis.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_entity_no_tracking(self, tracker):
        tracker.ha.get_state = AsyncMock(return_value=None)
        await tracker.track_action("get_weather", {}, {"success": True})
        tracker.redis.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_tracks_action_with_entity(self, tracker):
        tracker.ha.get_state = AsyncMock(return_value={
            "state": "on",
            "attributes": {"brightness": 100},
        })
        await tracker.track_action(
            "set_light", {"room": "wohnzimmer"}, {"success": True},
            person="Max", room="wohnzimmer",
        )
        tracker.redis.setex.assert_called()

    @pytest.mark.asyncio
    async def test_max_pending_limit(self, tracker):
        tracker._pending_count = 20
        tracker.ha.get_state = AsyncMock(return_value={"state": "on", "attributes": {}})
        await tracker.track_action("set_light", {"room": "wz"}, {"success": True})
        # Sollte nicht tracken da max_pending erreicht
        tracker.redis.setex.assert_not_called()


class TestRecordVerbalFeedback:
    """Tests fuer record_verbal_feedback()."""

    @pytest.mark.asyncio
    async def test_positive_feedback(self, tracker):
        tracker.redis.get.return_value = "set_light"
        await tracker.record_verbal_feedback("positive")
        tracker.redis.lpush.assert_called()

    @pytest.mark.asyncio
    async def test_negative_feedback(self, tracker):
        tracker.redis.get.return_value = "set_climate"
        await tracker.record_verbal_feedback("negative", action_type="set_climate")
        tracker.redis.lpush.assert_called()

    @pytest.mark.asyncio
    async def test_unknown_feedback_ignored(self, tracker):
        await tracker.record_verbal_feedback("unknown_type")
        tracker.redis.lpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_disabled_feedback_ignored(self, tracker):
        tracker.enabled = False
        await tracker.record_verbal_feedback("positive")
        tracker.redis.lpush.assert_not_called()


class TestClassifyOutcome:
    """Tests fuer _classify_outcome()."""

    def test_same_state_is_neutral(self, tracker):
        after = {"state": "on", "attributes": {"brightness": 100}}
        now = {"state": "on", "attributes": {"brightness": 100}}
        assert tracker._classify_outcome(after, now, "set_light") == OUTCOME_NEUTRAL

    def test_different_state_is_negative(self, tracker):
        after = {"state": "on", "attributes": {}}
        now = {"state": "off", "attributes": {}}
        assert tracker._classify_outcome(after, now, "set_light") == OUTCOME_NEGATIVE

    def test_changed_attributes_is_partial(self, tracker):
        # 1 of 3 non-volatile attrs changed = 33% < 50% = PARTIAL
        # Note: brightness/color_temp are volatile attrs and are skipped
        after = {"state": "on", "attributes": {"effect": "rainbow", "rgb_color": [255, 255, 255], "transition": 2}}
        now = {"state": "on", "attributes": {"effect": "none", "rgb_color": [255, 255, 255], "transition": 2}}
        assert tracker._classify_outcome(after, now, "set_light") == OUTCOME_PARTIAL

    def test_empty_states_neutral(self, tracker):
        assert tracker._classify_outcome({}, {}, "set_light") == OUTCOME_NEUTRAL
        assert tracker._classify_outcome(None, None, "set_light") == OUTCOME_NEUTRAL


class TestGetScores:
    """Tests fuer Score-Abfragen."""

    @pytest.mark.asyncio
    async def test_default_score_when_no_data(self, tracker):
        tracker.redis.get.return_value = None
        tracker.redis.hget.return_value = None
        score = await tracker.get_success_score("set_light")
        assert score == DEFAULT_SCORE

    @pytest.mark.asyncio
    async def test_returns_stored_score(self, tracker):
        tracker.redis.get.return_value = "0.85"
        score = await tracker.get_success_score("set_light")
        assert score == 0.85

    @pytest.mark.asyncio
    async def test_person_score_default(self, tracker):
        tracker.redis.get.return_value = None
        score = await tracker.get_person_score("set_light", "Max")
        assert score == DEFAULT_SCORE

    @pytest.mark.asyncio
    async def test_person_score_stored(self, tracker):
        tracker.redis.get.return_value = "0.72"
        score = await tracker.get_person_score("set_light", "Max")
        assert score == 0.72


class TestExtractStateKey:
    """Tests fuer _extract_state_key()."""

    def test_dict_state(self):
        state = {"state": "on", "attributes": {"brightness": 100, "friendly_name": "Licht"}}
        result = _extract_state_key(state)
        assert result["state"] == "on"
        assert "brightness" in result["attributes"]
        assert "friendly_name" not in result["attributes"]

    def test_none_state(self):
        assert _extract_state_key(None) == {}

    def test_empty_dict(self):
        # Empty dict is falsy in Python, so _extract_state_key returns {}
        result = _extract_state_key({})
        assert result == {}


class TestGetStats:
    """Tests fuer get_stats()."""

    @pytest.mark.asyncio
    async def test_empty_stats(self, tracker):
        tracker.redis.scan.return_value = (0, [])
        stats = await tracker.get_stats()
        assert stats == {}

    @pytest.mark.asyncio
    async def test_filters_room_and_person_keys(self, tracker):
        """Nur globale Stats (4-teilige Keys) sollen in get_stats() erscheinen."""
        tracker.redis.scan.return_value = (0, [
            "mha:outcome:stats:set_light",                      # Global ✓
            "mha:outcome:stats:set_light:wohnzimmer",           # Room ✗
            "mha:outcome:stats:set_light:person:Max",           # Person ✗
        ])
        tracker.redis.hgetall.return_value = {"positive": "5", "total": "10"}
        tracker.redis.get.return_value = "0.75"
        stats = await tracker.get_stats()
        # Nur der globale Key sollte durchkommen
        assert "set_light" in stats
        assert "set_light:wohnzimmer" not in stats
        assert "set_light:person:Max" not in stats


# ============================================================
# Additional Coverage Tests
# ============================================================

class TestInitialize:
    @pytest.mark.asyncio
    async def test_initialize_sets_enabled(self, redis_mock, ha_mock):
        from assistant.outcome_tracker import OutcomeTracker
        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {"enabled": True, "observation_delay_seconds": 60}}):
            t = OutcomeTracker()
        await t.initialize(redis_mock, ha_mock)
        assert t.enabled is True
        assert t.redis is redis_mock
        assert t.ha is ha_mock

    @pytest.mark.asyncio
    async def test_initialize_disabled_without_redis(self, ha_mock):
        from assistant.outcome_tracker import OutcomeTracker
        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {"enabled": True}}):
            t = OutcomeTracker()
        await t.initialize(None, ha_mock)
        assert t.enabled is False

    @pytest.mark.asyncio
    async def test_initialize_with_task_registry(self, redis_mock, ha_mock):
        from assistant.outcome_tracker import OutcomeTracker
        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {"enabled": True}}):
            t = OutcomeTracker()
        registry = MagicMock()
        await t.initialize(redis_mock, ha_mock, task_registry=registry)
        assert t._task_registry is registry


class TestGetWeeklyTrends:
    @pytest.mark.asyncio
    async def test_empty_trends_no_redis(self):
        from assistant.outcome_tracker import OutcomeTracker
        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {}}):
            t = OutcomeTracker()
        result = await t.get_weekly_trends()
        assert result == {}

    @pytest.mark.asyncio
    async def test_empty_trends_no_data(self, redis_mock):
        from assistant.outcome_tracker import OutcomeTracker
        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {}}):
            t = OutcomeTracker()
        t.redis = redis_mock
        t.enabled = True
        redis_mock.lrange.return_value = []
        result = await t.get_weekly_trends()
        assert result == {}

    @pytest.mark.asyncio
    async def test_weekly_trends_with_data(self, redis_mock):
        from assistant.outcome_tracker import OutcomeTracker
        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {}}):
            t = OutcomeTracker()
        t.redis = redis_mock
        t.enabled = True
        entries = [
            json.dumps({
                "action_type": "set_light",
                "outcome": "positive",
                "timestamp": "2025-06-01T10:00:00",
            }),
            json.dumps({
                "action_type": "set_light",
                "outcome": "negative",
                "timestamp": "2025-06-02T10:00:00",
            }),
        ]
        redis_mock.lrange.return_value = entries
        result = await t.get_weekly_trends()
        assert "set_light" in result
        assert len(result["set_light"]) > 0


class TestDelayedCheck:
    @pytest.mark.asyncio
    async def test_delayed_check_classifies_outcome(self, redis_mock, ha_mock):
        from assistant.outcome_tracker import OutcomeTracker
        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {"observation_delay_seconds": 0}}):
            t = OutcomeTracker()
        t.redis = redis_mock
        t.ha = ha_mock
        t.enabled = True
        t._pending_count = 1

        ha_mock.get_state.return_value = {"state": "on", "attributes": {}}
        pending = {
            "id": "test1",
            "action_type": "set_light",
            "entity_id": "light.wohnzimmer",
            "state_after": {"state": "on", "attributes": {}},
            "person": "Max",
            "room": "wohnzimmer",
            "timestamp": "2025-06-01T10:00:00",
            "args": {},
        }
        await t._delayed_check("test1", pending)
        # Should have stored outcome
        redis_mock.lpush.assert_called()

    @pytest.mark.asyncio
    async def test_delayed_check_no_current_state(self, redis_mock, ha_mock):
        from assistant.outcome_tracker import OutcomeTracker
        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {"observation_delay_seconds": 0}}):
            t = OutcomeTracker()
        t.redis = redis_mock
        t.ha = ha_mock
        t.enabled = True
        t._pending_count = 1

        ha_mock.get_state.return_value = None
        pending = {
            "id": "test2",
            "action_type": "set_light",
            "entity_id": "light.wohnzimmer",
            "state_after": {"state": "on", "attributes": {}},
            "person": "",
            "room": "",
            "timestamp": "2025-06-01T10:00:00",
            "args": {},
        }
        await t._delayed_check("test2", pending)
        assert t._pending_count == 0

    @pytest.mark.asyncio
    async def test_delayed_check_ha_exception(self, redis_mock, ha_mock):
        from assistant.outcome_tracker import OutcomeTracker
        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {"observation_delay_seconds": 0}}):
            t = OutcomeTracker()
        t.redis = redis_mock
        t.ha = ha_mock
        t.enabled = True
        t._pending_count = 1

        ha_mock.get_state.side_effect = Exception("HA down")
        pending = {
            "id": "test3",
            "action_type": "set_light",
            "entity_id": "light.wohnzimmer",
            "state_after": {"state": "on", "attributes": {}},
            "person": "",
            "room": "",
            "timestamp": "2025-06-01T10:00:00",
            "args": {},
        }
        await t._delayed_check("test3", pending)
        assert t._pending_count == 0


class TestStoreOutcomeWithContext:
    @pytest.mark.asyncio
    async def test_store_outcome_with_room(self, redis_mock):
        from assistant.outcome_tracker import OutcomeTracker
        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {}}):
            t = OutcomeTracker()
        t.redis = redis_mock
        t.enabled = True
        redis_mock.hget.return_value = None
        await t._store_outcome("set_light", "positive", room="wohnzimmer")
        # Should store room-specific stats
        hincrby_calls = [str(c) for c in redis_mock.hincrby.call_args_list]
        assert any("wohnzimmer" in c for c in hincrby_calls)

    @pytest.mark.asyncio
    async def test_store_outcome_with_person(self, redis_mock):
        from assistant.outcome_tracker import OutcomeTracker
        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {}}):
            t = OutcomeTracker()
        t.redis = redis_mock
        t.enabled = True
        redis_mock.hget.return_value = None
        await t._store_outcome("set_light", "positive", person="Max")
        hincrby_calls = [str(c) for c in redis_mock.hincrby.call_args_list]
        assert any("person:Max" in c for c in hincrby_calls)


class TestUpdateScore:
    @pytest.mark.asyncio
    async def test_update_score_not_enough_data(self, redis_mock):
        from assistant.outcome_tracker import OutcomeTracker
        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {}}):
            t = OutcomeTracker()
        t.redis = redis_mock
        redis_mock.hget.return_value = "5"  # Below MIN_OUTCOMES_FOR_SCORE (10)
        await t._update_score("set_light", "positive")
        redis_mock.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_score_ema_calculation(self, redis_mock):
        from assistant.outcome_tracker import OutcomeTracker
        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {}}):
            t = OutcomeTracker()
        t.redis = redis_mock
        redis_mock.hget.return_value = "20"  # Above MIN_OUTCOMES_FOR_SCORE
        redis_mock.get.return_value = "0.5"  # Current score
        await t._update_score("set_light", "positive")
        redis_mock.setex.assert_called_once()
        # Check score was written
        score_str = redis_mock.setex.call_args[0][2]
        score = float(score_str)
        assert 0.5 < score <= 1.0

    @pytest.mark.asyncio
    async def test_update_score_person_specific(self, redis_mock):
        from assistant.outcome_tracker import OutcomeTracker
        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {}}):
            t = OutcomeTracker()
        t.redis = redis_mock
        redis_mock.hget.return_value = "15"
        redis_mock.get.return_value = "0.5"
        await t._update_score("set_light", "negative", person="Max")
        call_args = redis_mock.setex.call_args[0]
        assert "person:Max" in call_args[0]

    @pytest.mark.asyncio
    async def test_update_score_no_redis(self):
        from assistant.outcome_tracker import OutcomeTracker
        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {}}):
            t = OutcomeTracker()
        t.redis = None
        await t._update_score("set_light", "positive")  # Should not raise


class TestTrackActionEntityConstruction:
    @pytest.mark.asyncio
    async def test_entity_id_from_room_and_action_type(self, redis_mock, ha_mock):
        from assistant.outcome_tracker import OutcomeTracker
        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {"enabled": True, "observation_delay_seconds": 0}}):
            t = OutcomeTracker()
        t.redis = redis_mock
        t.ha = ha_mock
        t.enabled = True

        ha_mock.get_state.return_value = {"state": "on", "attributes": {}}
        await t.track_action(
            "set_light",
            {"room": "Wohnzimmer"},
            {},
            room="Wohnzimmer",
        )
        # Should have constructed entity_id = light.wohnzimmer
        redis_mock.setex.assert_called()

    @pytest.mark.asyncio
    async def test_entity_id_from_result(self, redis_mock, ha_mock):
        from assistant.outcome_tracker import OutcomeTracker
        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {"enabled": True, "observation_delay_seconds": 0}}):
            t = OutcomeTracker()
        t.redis = redis_mock
        t.ha = ha_mock
        t.enabled = True

        ha_mock.get_state.return_value = {"state": "on", "attributes": {}}
        await t.track_action(
            "set_light",
            {},
            {"entity_id": "light.kueche"},
        )
        redis_mock.setex.assert_called()
