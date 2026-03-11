"""
Comprehensive tests for conditional_commands.py — ConditionalCommands class.

Tests alle Methoden: initialize(), create_conditional(), check_event(),
_check_trigger_match(), list_conditionals(), delete_conditional(),
Trust-Checks, Redis-Interaktion, Edge Cases.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.conditional_commands import (
    ConditionalCommands,
    KEY_INDEX,
    KEY_PREFIX,
    OWNER_ONLY_ACTIONS,
)


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def redis_mock():
    r = AsyncMock()
    r.scard = AsyncMock(return_value=0)
    r.smembers = AsyncMock(return_value=set())
    r.mget = AsyncMock(return_value=[])
    r.setex = AsyncMock()
    r.sadd = AsyncMock()
    r.srem = AsyncMock()
    r.delete = AsyncMock(return_value=1)
    r.get = AsyncMock(return_value=None)
    r.ttl = AsyncMock(return_value=3600)
    pipe = AsyncMock()
    pipe.ttl = MagicMock()
    pipe.execute = AsyncMock(return_value=[])
    r.pipeline = MagicMock(return_value=pipe)
    return r


@pytest.fixture
def cc():
    return ConditionalCommands()


@pytest.fixture
def cc_with_redis(cc, redis_mock):
    cc.redis = redis_mock
    return cc


# ── Initialize ────────────────────────────────────────────────────────

class TestInitialize:

    @pytest.mark.asyncio
    async def test_initialize_with_redis(self, cc, redis_mock):
        redis_mock.scard = AsyncMock(return_value=5)
        await cc.initialize(redis_mock)
        assert cc.redis is redis_mock
        redis_mock.scard.assert_called_once_with(KEY_INDEX)

    @pytest.mark.asyncio
    async def test_initialize_without_redis(self, cc):
        await cc.initialize(None)
        assert cc.redis is None

    def test_set_action_callback(self, cc):
        cb = AsyncMock()
        cc.set_action_callback(cb)
        assert cc._action_callback is cb


# ── Create Conditional ────────────────────────────────────────────────

class TestCreateConditional:

    @pytest.mark.asyncio
    async def test_no_redis(self, cc):
        result = await cc.create_conditional(
            "state_change", "light.kitchen:on", "set_light", {}
        )
        assert result["success"] is False
        assert "Redis" in result["message"]

    @pytest.mark.asyncio
    async def test_successful_creation(self, cc_with_redis, redis_mock):
        result = await cc_with_redis.create_conditional(
            "state_change", "sensor.regen:on", "set_cover",
            {"room": "all", "position": 0},
            label="Bei Regen Rolladen runter",
            ttl_hours=12,
        )
        assert result["success"] is True
        assert "conditional_id" in result
        assert "12 Stunden" in result["message"]
        assert "einmalig" in result["message"]
        redis_mock.setex.assert_called_once()
        redis_mock.sadd.assert_called_once()

    @pytest.mark.asyncio
    async def test_creation_dauerhaft(self, cc_with_redis):
        result = await cc_with_redis.create_conditional(
            "state_change", "light.test:on", "set_light", {},
            one_shot=False, ttl_hours=48,
        )
        assert result["success"] is True
        assert "dauerhaft" in result["message"]
        assert "48 Stunden" in result["message"]

    @pytest.mark.asyncio
    async def test_creation_singular_hour(self, cc_with_redis):
        result = await cc_with_redis.create_conditional(
            "state_change", "light.test:on", "set_light", {},
            ttl_hours=1,
        )
        assert result["success"] is True
        assert "1 Stunde" in result["message"]
        assert "Stunden" not in result["message"]

    @pytest.mark.asyncio
    async def test_auto_label(self, cc_with_redis):
        result = await cc_with_redis.create_conditional(
            "state_change", "sensor.x:on", "set_light", {},
        )
        assert result["success"] is True
        assert "sensor.x:on" in result["message"]

    @pytest.mark.asyncio
    async def test_ttl_clamped_min(self, cc_with_redis, redis_mock):
        result = await cc_with_redis.create_conditional(
            "state_change", "s:on", "set_light", {}, ttl_hours=0,
        )
        assert result["success"] is True
        # TTL should be clamped to 1h minimum
        call_args = redis_mock.setex.call_args
        assert call_args[0][1] == 3600  # 1 * 3600

    @pytest.mark.asyncio
    async def test_ttl_clamped_max(self, cc_with_redis, redis_mock):
        result = await cc_with_redis.create_conditional(
            "state_change", "s:on", "set_light", {}, ttl_hours=999,
        )
        assert result["success"] is True
        call_args = redis_mock.setex.call_args
        assert call_args[0][1] == 168 * 3600  # 168 * 3600

    @pytest.mark.asyncio
    async def test_owner_only_action_blocked_for_member(self, cc_with_redis):
        result = await cc_with_redis.create_conditional(
            "state_change", "s:on", "lock_door", {},
            trust_level="member",
        )
        assert result["success"] is False
        assert "Owner" in result["message"]

    @pytest.mark.asyncio
    async def test_owner_only_action_allowed_for_owner(self, cc_with_redis):
        result = await cc_with_redis.create_conditional(
            "state_change", "s:on", "unlock_door", {},
            trust_level="owner",
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_owner_only_action_blocked_for_guest(self, cc_with_redis):
        result = await cc_with_redis.create_conditional(
            "state_change", "s:on", "arm_alarm", {},
            trust_level="guest",
        )
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_redis_error_during_save(self, cc_with_redis, redis_mock):
        redis_mock.setex = AsyncMock(side_effect=ConnectionError("down"))
        result = await cc_with_redis.create_conditional(
            "state_change", "s:on", "set_light", {},
        )
        assert result["success"] is False
        assert "nicht gespeichert" in result["message"]


# ── Check Event ───────────────────────────────────────────────────────

class TestCheckEvent:

    @pytest.mark.asyncio
    async def test_no_redis_returns_empty(self, cc):
        result = await cc.check_event("light.kitchen", "on", "off")
        assert result == []

    @pytest.mark.asyncio
    async def test_no_conditionals(self, cc_with_redis, redis_mock):
        redis_mock.smembers = AsyncMock(return_value=set())
        result = await cc_with_redis.check_event("light.kitchen", "on", "off")
        assert result == []

    @pytest.mark.asyncio
    async def test_matching_state_change_one_shot(self, cc_with_redis, redis_mock):
        cond_id = "abc12345"
        cond = {
            "id": cond_id,
            "trigger_type": "state_change",
            "trigger_value": "light.kitchen:on",
            "action_function": "set_cover",
            "action_args": {"position": 0},
            "label": "Test",
            "one_shot": True,
            "trust_level": "owner",
            "executed_count": 0,
        }
        redis_mock.smembers = AsyncMock(return_value={cond_id})
        redis_mock.mget = AsyncMock(return_value=[json.dumps(cond)])

        callback = AsyncMock(return_value={"success": True})
        cc_with_redis.set_action_callback(callback)

        result = await cc_with_redis.check_event("light.kitchen", "on", "off")
        assert len(result) == 1
        assert result[0]["conditional_id"] == cond_id
        callback.assert_called_once_with("set_cover", {"position": 0})
        # One-shot: should be deleted
        redis_mock.delete.assert_called()
        redis_mock.srem.assert_called()

    @pytest.mark.asyncio
    async def test_matching_dauerhaft_updates_counter(self, cc_with_redis, redis_mock):
        cond_id = "dauer123"
        cond = {
            "id": cond_id,
            "trigger_type": "state_change",
            "trigger_value": "light.kitchen:on",
            "action_function": "set_light",
            "action_args": {},
            "label": "Dauerhaft",
            "one_shot": False,
            "trust_level": "owner",
            "executed_count": 0,
        }
        redis_mock.smembers = AsyncMock(return_value={cond_id})
        redis_mock.mget = AsyncMock(return_value=[json.dumps(cond)])
        redis_mock.ttl = AsyncMock(return_value=7200)

        callback = AsyncMock(return_value={"success": True})
        cc_with_redis.set_action_callback(callback)

        result = await cc_with_redis.check_event("light.kitchen", "on", "off")
        assert len(result) == 1
        # Should update count via setex (not delete)
        redis_mock.setex.assert_called()
        updated_data = json.loads(redis_mock.setex.call_args[0][2])
        assert updated_data["executed_count"] == 1

    @pytest.mark.asyncio
    async def test_no_match_does_not_execute(self, cc_with_redis, redis_mock):
        cond = {
            "id": "x",
            "trigger_type": "state_change",
            "trigger_value": "light.bedroom:on",
            "action_function": "set_light",
            "action_args": {},
            "label": "Test",
            "one_shot": True,
            "trust_level": "owner",
            "executed_count": 0,
        }
        redis_mock.smembers = AsyncMock(return_value={"x"})
        redis_mock.mget = AsyncMock(return_value=[json.dumps(cond)])

        callback = AsyncMock()
        cc_with_redis.set_action_callback(callback)

        result = await cc_with_redis.check_event("light.kitchen", "on", "off")
        assert result == []
        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_expired_entry_cleaned_up(self, cc_with_redis, redis_mock):
        redis_mock.smembers = AsyncMock(return_value={"expired1"})
        redis_mock.mget = AsyncMock(return_value=[None])

        result = await cc_with_redis.check_event("light.kitchen", "on", "off")
        assert result == []
        redis_mock.srem.assert_called_with(KEY_INDEX, "expired1")

    @pytest.mark.asyncio
    async def test_bytes_cond_ids_decoded(self, cc_with_redis, redis_mock):
        cond = {
            "id": "abc",
            "trigger_type": "state_change",
            "trigger_value": "light.kitchen:on",
            "action_function": "set_light",
            "action_args": {},
            "label": "Test",
            "one_shot": True,
            "trust_level": "owner",
            "executed_count": 0,
        }
        redis_mock.smembers = AsyncMock(return_value={b"abc"})
        redis_mock.mget = AsyncMock(return_value=[json.dumps(cond).encode()])

        callback = AsyncMock(return_value={"success": True})
        cc_with_redis.set_action_callback(callback)

        result = await cc_with_redis.check_event("light.kitchen", "on", "off")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_owner_only_blocked_at_execution(self, cc_with_redis, redis_mock):
        """Trust was member at creation, action is owner-only -> blocked at execution."""
        cond = {
            "id": "sec1",
            "trigger_type": "state_change",
            "trigger_value": "light.kitchen:on",
            "action_function": "lock_door",
            "action_args": {},
            "label": "Lock",
            "one_shot": True,
            "trust_level": "member",
            "person": "guest1",
            "executed_count": 0,
        }
        redis_mock.smembers = AsyncMock(return_value={"sec1"})
        redis_mock.mget = AsyncMock(return_value=[json.dumps(cond)])

        callback = AsyncMock()
        cc_with_redis.set_action_callback(callback)

        result = await cc_with_redis.check_event("light.kitchen", "on", "off")
        assert result == []
        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_callback_still_records(self, cc_with_redis, redis_mock):
        cond = {
            "id": "nocb",
            "trigger_type": "state_change",
            "trigger_value": "light.kitchen:on",
            "action_function": "set_light",
            "action_args": {},
            "label": "No CB",
            "one_shot": True,
            "trust_level": "owner",
            "executed_count": 0,
        }
        redis_mock.smembers = AsyncMock(return_value={"nocb"})
        redis_mock.mget = AsyncMock(return_value=[json.dumps(cond)])
        # No callback set
        cc_with_redis._action_callback = None

        result = await cc_with_redis.check_event("light.kitchen", "on", "off")
        # No callback → no execution record
        assert result == []

    @pytest.mark.asyncio
    async def test_callback_exception_handled(self, cc_with_redis, redis_mock):
        cond = {
            "id": "err1",
            "trigger_type": "state_change",
            "trigger_value": "light.kitchen:on",
            "action_function": "set_light",
            "action_args": {},
            "label": "Error",
            "one_shot": True,
            "trust_level": "owner",
            "executed_count": 0,
        }
        redis_mock.smembers = AsyncMock(return_value={"err1"})
        redis_mock.mget = AsyncMock(return_value=[json.dumps(cond)])

        callback = AsyncMock(side_effect=RuntimeError("boom"))
        cc_with_redis.set_action_callback(callback)

        result = await cc_with_redis.check_event("light.kitchen", "on", "off")
        # Error during callback → still no crash
        assert result == []

    @pytest.mark.asyncio
    async def test_smembers_exception_returns_empty(self, cc_with_redis, redis_mock):
        redis_mock.smembers = AsyncMock(side_effect=ConnectionError("down"))
        result = await cc_with_redis.check_event("light.kitchen", "on", "off")
        assert result == []

    @pytest.mark.asyncio
    async def test_dauerhaft_with_zero_ttl_not_updated(self, cc_with_redis, redis_mock):
        """When TTL is 0 or negative, don't update."""
        cond = {
            "id": "d1",
            "trigger_type": "state_change",
            "trigger_value": "light.kitchen:on",
            "action_function": "set_light",
            "action_args": {},
            "label": "D",
            "one_shot": False,
            "trust_level": "owner",
            "executed_count": 0,
        }
        redis_mock.smembers = AsyncMock(return_value={"d1"})
        redis_mock.mget = AsyncMock(return_value=[json.dumps(cond)])
        redis_mock.ttl = AsyncMock(return_value=-1)

        callback = AsyncMock(return_value={"success": True})
        cc_with_redis.set_action_callback(callback)

        await cc_with_redis.check_event("light.kitchen", "on", "off")
        # setex should NOT be called since TTL <= 0
        redis_mock.setex.assert_not_called()


# ── Trigger Match (via real class method) ──────────────────────────────

class TestCheckTriggerMatchReal:

    def test_state_change_exact_match(self, cc):
        cond = {"trigger_type": "state_change", "trigger_value": "light.kitchen:on"}
        assert cc._check_trigger_match(cond, "light.kitchen", "on", "off", {}) is True

    def test_state_change_wrong_state(self, cc):
        cond = {"trigger_type": "state_change", "trigger_value": "light.kitchen:on"}
        assert cc._check_trigger_match(cond, "light.kitchen", "off", "on", {}) is False

    def test_state_change_any_change(self, cc):
        cond = {"trigger_type": "state_change", "trigger_value": "light.kitchen"}
        assert cc._check_trigger_match(cond, "light.kitchen", "on", "off", {}) is True

    def test_state_change_same_state_no_match(self, cc):
        cond = {"trigger_type": "state_change", "trigger_value": "light.kitchen"}
        assert cc._check_trigger_match(cond, "light.kitchen", "on", "on", {}) is False

    def test_state_change_suffix_match(self, cc):
        cond = {"trigger_type": "state_change", "trigger_value": "kitchen:on"}
        assert cc._check_trigger_match(cond, "light.kitchen", "on", "off", {}) is True

    def test_person_arrives(self, cc):
        cond = {"trigger_type": "person_arrives", "trigger_value": "alice"}
        assert cc._check_trigger_match(cond, "person.alice", "home", "away", {}) is True

    def test_person_arrives_not_person_entity(self, cc):
        cond = {"trigger_type": "person_arrives", "trigger_value": "alice"}
        assert cc._check_trigger_match(cond, "device_tracker.alice", "home", "away", {}) is False

    def test_person_arrives_already_home(self, cc):
        cond = {"trigger_type": "person_arrives", "trigger_value": "alice"}
        assert cc._check_trigger_match(cond, "person.alice", "home", "home", {}) is False

    def test_person_arrives_wrong_person(self, cc):
        cond = {"trigger_type": "person_arrives", "trigger_value": "bob"}
        assert cc._check_trigger_match(cond, "person.alice", "home", "away", {}) is False

    def test_person_leaves(self, cc):
        cond = {"trigger_type": "person_leaves", "trigger_value": "alice"}
        assert cc._check_trigger_match(cond, "person.alice", "away", "home", {}) is True

    def test_person_leaves_not_home(self, cc):
        cond = {"trigger_type": "person_leaves", "trigger_value": "alice"}
        assert cc._check_trigger_match(cond, "person.alice", "away", "away", {}) is False

    def test_state_attribute_gt_pipe_delim(self, cc):
        cond = {
            "trigger_type": "state_attribute",
            "trigger_value": "sensor.temp|temperature|>|25",
        }
        assert cc._check_trigger_match(cond, "sensor.temp", "on", "off", {"temperature": "30"}) is True

    def test_state_attribute_lt_colon_delim(self, cc):
        cond = {
            "trigger_type": "state_attribute",
            "trigger_value": "sensor.temp:temperature:<:25",
        }
        assert cc._check_trigger_match(cond, "sensor.temp", "on", "off", {"temperature": "20"}) is True

    def test_state_attribute_eq_numeric(self, cc):
        cond = {
            "trigger_type": "state_attribute",
            "trigger_value": "sensor.temp:temperature:=:25",
        }
        assert cc._check_trigger_match(cond, "sensor.temp", "on", "off", {"temperature": "25"}) is True

    def test_state_attribute_eq_string_fallback(self, cc):
        cond = {
            "trigger_type": "state_attribute",
            "trigger_value": "media_player.tv:source:=:HDMI 1",
        }
        assert cc._check_trigger_match(cond, "media_player.tv", "on", "off", {"source": "HDMI 1"}) is True

    def test_state_attribute_missing_attr(self, cc):
        cond = {
            "trigger_type": "state_attribute",
            "trigger_value": "sensor.temp:temperature:>:25",
        }
        assert cc._check_trigger_match(cond, "sensor.temp", "on", "off", {}) is False

    def test_state_attribute_insufficient_parts(self, cc):
        cond = {"trigger_type": "state_attribute", "trigger_value": "sensor.temp:temp"}
        assert cc._check_trigger_match(cond, "sensor.temp", "on", "off", {"temp": "30"}) is False

    def test_state_attribute_wrong_entity(self, cc):
        cond = {
            "trigger_type": "state_attribute",
            "trigger_value": "sensor.other:temperature:>:25",
        }
        assert cc._check_trigger_match(cond, "sensor.temp", "on", "off", {"temperature": "30"}) is False

    def test_unknown_trigger_type(self, cc):
        cond = {"trigger_type": "unknown", "trigger_value": "anything"}
        assert cc._check_trigger_match(cond, "sensor.x", "on", "off", {}) is False


# ── List Conditionals ─────────────────────────────────────────────────

class TestListConditionals:

    @pytest.mark.asyncio
    async def test_no_redis(self, cc):
        result = await cc.list_conditionals()
        assert result["success"] is True
        assert "Keine" in result["message"]

    @pytest.mark.asyncio
    async def test_empty_list(self, cc_with_redis, redis_mock):
        redis_mock.smembers = AsyncMock(return_value=set())
        result = await cc_with_redis.list_conditionals()
        assert result["success"] is True
        assert "Keine" in result["message"]

    @pytest.mark.asyncio
    async def test_with_conditionals(self, cc_with_redis, redis_mock):
        cond = {
            "label": "Regen-Schutz",
            "one_shot": True,
        }
        redis_mock.smembers = AsyncMock(return_value={"id1"})
        redis_mock.mget = AsyncMock(return_value=[json.dumps(cond)])
        pipe = AsyncMock()
        pipe.ttl = MagicMock()
        pipe.execute = AsyncMock(return_value=[7200])  # 2h
        redis_mock.pipeline = MagicMock(return_value=pipe)

        result = await cc_with_redis.list_conditionals()
        assert result["success"] is True
        assert "Regen-Schutz" in result["message"]
        assert "einmalig" in result["message"]

    @pytest.mark.asyncio
    async def test_expired_entry_cleaned(self, cc_with_redis, redis_mock):
        redis_mock.smembers = AsyncMock(return_value={"exp1"})
        redis_mock.mget = AsyncMock(return_value=[None])
        pipe = AsyncMock()
        pipe.ttl = MagicMock()
        pipe.execute = AsyncMock(return_value=[0])
        redis_mock.pipeline = MagicMock(return_value=pipe)

        result = await cc_with_redis.list_conditionals()
        redis_mock.srem.assert_called_with(KEY_INDEX, "exp1")

    @pytest.mark.asyncio
    async def test_bytes_handling(self, cc_with_redis, redis_mock):
        cond = {"label": "Test", "one_shot": False}
        redis_mock.smembers = AsyncMock(return_value={b"id1"})
        redis_mock.mget = AsyncMock(return_value=[json.dumps(cond).encode()])
        pipe = AsyncMock()
        pipe.ttl = MagicMock()
        pipe.execute = AsyncMock(return_value=[3600])
        redis_mock.pipeline = MagicMock(return_value=pipe)

        result = await cc_with_redis.list_conditionals()
        assert result["success"] is True
        assert "dauerhaft" in result["message"]


# ── Delete Conditional ────────────────────────────────────────────────

class TestDeleteConditional:

    @pytest.mark.asyncio
    async def test_no_redis(self, cc):
        result = await cc.delete_conditional("abc")
        assert result["success"] is False
        assert "Redis" in result["message"]

    @pytest.mark.asyncio
    async def test_successful_delete(self, cc_with_redis, redis_mock):
        redis_mock.delete = AsyncMock(return_value=1)
        result = await cc_with_redis.delete_conditional("abc123")
        assert result["success"] is True
        assert "abc123" in result["message"]

    @pytest.mark.asyncio
    async def test_not_found(self, cc_with_redis, redis_mock):
        redis_mock.delete = AsyncMock(return_value=0)
        result = await cc_with_redis.delete_conditional("missing")
        assert result["success"] is False
        assert "nicht gefunden" in result["message"]
