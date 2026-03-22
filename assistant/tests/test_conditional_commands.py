"""
Tests fuer ConditionalCommands — Temporaere Wenn-Dann-Befehle.

Testet:
- create_conditional() (Erstellung, TTL-Clamp, Owner-Only)
- check_event() (Trigger-Matching: state_change, person_arrives/leaves)
- _check_trigger_match() (state_change, person, compound)
- OWNER_ONLY_ACTIONS Sicherheit
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.conditional_commands import (
    ConditionalCommands,
    OWNER_ONLY_ACTIONS,
    KEY_PREFIX,
    KEY_INDEX,
)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def cond():
    cc = ConditionalCommands()
    cc.redis = AsyncMock()
    cc.redis.setex = AsyncMock()
    cc.redis.sadd = AsyncMock()
    cc.redis.scard = AsyncMock(return_value=0)
    cc.redis.smembers = AsyncMock(return_value=set())
    cc.redis.mget = AsyncMock(return_value=[])
    cc.redis.delete = AsyncMock()
    cc.redis.srem = AsyncMock()
    cc.redis.ttl = AsyncMock(return_value=3600)
    cc._action_callback = AsyncMock(return_value={"success": True})
    return cc


# ============================================================
# OWNER_ONLY_ACTIONS
# ============================================================


class TestOwnerOnlyActions:
    def test_lock_door_requires_owner(self):
        assert "lock_door" in OWNER_ONLY_ACTIONS

    def test_unlock_door_requires_owner(self):
        assert "unlock_door" in OWNER_ONLY_ACTIONS

    def test_arm_security_requires_owner(self):
        assert "arm_security_system" in OWNER_ONLY_ACTIONS

    def test_set_light_not_owner_only(self):
        assert "set_light" not in OWNER_ONLY_ACTIONS


# ============================================================
# create_conditional
# ============================================================


class TestCreateConditional:
    @pytest.mark.asyncio
    async def test_create_basic(self, cond):
        result = await cond.create_conditional(
            trigger_type="state_change",
            trigger_value="sensor.regen:on",
            action_function="set_cover",
            action_args={"room": "wohnzimmer", "position": 0},
            label="Regen Rollladen",
        )
        assert result["success"] is True
        assert "conditional_id" in result
        assert "Regen Rollladen" in result["message"]
        cond.redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_redis_fails(self):
        cc = ConditionalCommands()
        cc.redis = None
        result = await cc.create_conditional(
            trigger_type="state_change",
            trigger_value="x:on",
            action_function="set_light",
            action_args={},
        )
        assert result["success"] is False
        assert "Redis" in result["message"]

    @pytest.mark.asyncio
    async def test_ttl_clamped_max(self, cond):
        result = await cond.create_conditional(
            trigger_type="state_change",
            trigger_value="x:on",
            action_function="set_light",
            action_args={},
            ttl_hours=500,  # > 168
        )
        assert result["success"] is True
        # TTL should be clamped to 168h = 604800s
        call_args = cond.redis.setex.call_args
        ttl_used = call_args[0][1]
        assert ttl_used == 168 * 3600

    @pytest.mark.asyncio
    async def test_ttl_clamped_min(self, cond):
        result = await cond.create_conditional(
            trigger_type="state_change",
            trigger_value="x:on",
            action_function="set_light",
            action_args={},
            ttl_hours=0,  # < 1
        )
        assert result["success"] is True
        call_args = cond.redis.setex.call_args
        ttl_used = call_args[0][1]
        assert ttl_used == 1 * 3600

    @pytest.mark.asyncio
    async def test_owner_only_action_blocked_for_member(self, cond):
        result = await cond.create_conditional(
            trigger_type="state_change",
            trigger_value="x:on",
            action_function="lock_door",
            action_args={},
            trust_level="member",
        )
        assert result["success"] is False
        assert "Owner" in result["message"]

    @pytest.mark.asyncio
    async def test_owner_only_action_allowed_for_owner(self, cond):
        result = await cond.create_conditional(
            trigger_type="state_change",
            trigger_value="x:on",
            action_function="lock_door",
            action_args={},
            trust_level="owner",
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_one_shot_flag_stored(self, cond):
        await cond.create_conditional(
            trigger_type="state_change",
            trigger_value="x:on",
            action_function="set_light",
            action_args={},
            one_shot=True,
        )
        stored = json.loads(cond.redis.setex.call_args[0][2])
        assert stored["one_shot"] is True

    @pytest.mark.asyncio
    async def test_default_label_generated(self, cond):
        result = await cond.create_conditional(
            trigger_type="state_change",
            trigger_value="sensor.regen:on",
            action_function="set_cover",
            action_args={},
        )
        assert result["success"] is True
        stored = json.loads(cond.redis.setex.call_args[0][2])
        assert "sensor.regen:on" in stored["label"]

    @pytest.mark.asyncio
    async def test_compound_trigger_stored(self, cond):
        sub_triggers = [
            {"trigger_type": "state_change", "trigger_value": "sensor.regen:on"},
            {
                "trigger_type": "state_change",
                "trigger_value": "binary_sensor.fenster:on",
            },
        ]
        result = await cond.create_conditional(
            trigger_type="compound",
            trigger_value="",
            action_function="send_notification",
            action_args={"message": "Fenster offen bei Regen!"},
            sub_triggers=sub_triggers,
            logic_operator="and",
        )
        assert result["success"] is True
        stored = json.loads(cond.redis.setex.call_args[0][2])
        assert stored["trigger_type"] == "compound"
        assert len(stored["sub_triggers"]) == 2


# ============================================================
# _check_trigger_match
# ============================================================


class TestCheckTriggerMatch:
    def test_state_change_match(self, cond):
        conditional = {
            "trigger_type": "state_change",
            "trigger_value": "sensor.regen:on",
        }
        assert (
            cond._check_trigger_match(
                conditional,
                "sensor.regen",
                "on",
                "off",
                {},
            )
            is True
        )

    def test_state_change_no_match_wrong_state(self, cond):
        conditional = {
            "trigger_type": "state_change",
            "trigger_value": "sensor.regen:on",
        }
        assert (
            cond._check_trigger_match(
                conditional,
                "sensor.regen",
                "off",
                "on",
                {},
            )
            is False
        )

    def test_state_change_no_match_wrong_entity(self, cond):
        conditional = {
            "trigger_type": "state_change",
            "trigger_value": "sensor.regen:on",
        }
        assert (
            cond._check_trigger_match(
                conditional,
                "sensor.wind",
                "on",
                "off",
                {},
            )
            is False
        )

    def test_state_change_any_state(self, cond):
        """Ohne target_state matcht jeder Wechsel."""
        conditional = {
            "trigger_type": "state_change",
            "trigger_value": "sensor.regen",
        }
        assert (
            cond._check_trigger_match(
                conditional,
                "sensor.regen",
                "on",
                "off",
                {},
            )
            is True
        )

    def test_state_change_same_state_no_match(self, cond):
        """Kein Wechsel = kein Match bei target_state=None."""
        conditional = {
            "trigger_type": "state_change",
            "trigger_value": "sensor.regen",
        }
        assert (
            cond._check_trigger_match(
                conditional,
                "sensor.regen",
                "on",
                "on",
                {},
            )
            is False
        )

    def test_person_arrives_match(self, cond):
        conditional = {
            "trigger_type": "person_arrives",
            "trigger_value": "max",
        }
        assert (
            cond._check_trigger_match(
                conditional,
                "person.max",
                "home",
                "not_home",
                {},
            )
            is True
        )

    def test_person_arrives_already_home(self, cond):
        conditional = {
            "trigger_type": "person_arrives",
            "trigger_value": "max",
        }
        assert (
            cond._check_trigger_match(
                conditional,
                "person.max",
                "home",
                "home",
                {},
            )
            is False
        )

    def test_person_leaves_match(self, cond):
        conditional = {
            "trigger_type": "person_leaves",
            "trigger_value": "max",
        }
        assert (
            cond._check_trigger_match(
                conditional,
                "person.max",
                "not_home",
                "home",
                {},
            )
            is True
        )

    def test_person_leaves_wrong_entity(self, cond):
        conditional = {
            "trigger_type": "person_leaves",
            "trigger_value": "max",
        }
        assert (
            cond._check_trigger_match(
                conditional,
                "light.wohnzimmer",
                "off",
                "on",
                {},
            )
            is False
        )

    def test_compound_or_one_match(self, cond):
        conditional = {
            "trigger_type": "compound",
            "logic_operator": "or",
            "sub_triggers": [
                {"trigger_type": "state_change", "trigger_value": "sensor.a:on"},
                {"trigger_type": "state_change", "trigger_value": "sensor.b:on"},
            ],
        }
        assert (
            cond._check_trigger_match(
                conditional,
                "sensor.a",
                "on",
                "off",
                {},
            )
            is True
        )

    def test_compound_or_no_match(self, cond):
        conditional = {
            "trigger_type": "compound",
            "logic_operator": "or",
            "sub_triggers": [
                {"trigger_type": "state_change", "trigger_value": "sensor.a:on"},
                {"trigger_type": "state_change", "trigger_value": "sensor.b:on"},
            ],
        }
        assert (
            cond._check_trigger_match(
                conditional,
                "sensor.c",
                "on",
                "off",
                {},
            )
            is False
        )

    def test_compound_empty_sub_triggers(self, cond):
        conditional = {
            "trigger_type": "compound",
            "logic_operator": "and",
            "sub_triggers": [],
        }
        assert (
            cond._check_trigger_match(
                conditional,
                "sensor.a",
                "on",
                "off",
                {},
            )
            is False
        )


# ============================================================
# check_event
# ============================================================


class TestCheckEvent:
    @pytest.mark.asyncio
    async def test_no_redis(self):
        cc = ConditionalCommands()
        cc.redis = None
        result = await cc.check_event("sensor.x", "on")
        assert result == []

    @pytest.mark.asyncio
    async def test_no_conditionals(self, cond):
        cond.redis.smembers = AsyncMock(return_value=set())
        result = await cond.check_event("sensor.x", "on")
        assert result == []

    @pytest.mark.asyncio
    async def test_matching_conditional_executes(self, cond):
        cond_data = {
            "id": "abc",
            "trigger_type": "state_change",
            "trigger_value": "sensor.regen:on",
            "action_function": "set_cover",
            "action_args": {"room": "wz", "position": 0},
            "label": "Regen",
            "one_shot": True,
            "person": "Max",
            "trust_level": "owner",
            "executed_count": 0,
        }
        cond.redis.smembers = AsyncMock(return_value={"abc"})
        cond.redis.mget = AsyncMock(return_value=[json.dumps(cond_data)])

        result = await cond.check_event("sensor.regen", "on", "off")
        assert len(result) == 1
        assert result[0]["action"] == "set_cover"
        # One-shot: should be deleted
        cond.redis.delete.assert_called()

    @pytest.mark.asyncio
    async def test_owner_only_blocked_at_execution(self, cond):
        cond_data = {
            "id": "abc",
            "trigger_type": "state_change",
            "trigger_value": "sensor.x:on",
            "action_function": "lock_door",
            "action_args": {},
            "label": "Lock",
            "one_shot": True,
            "person": "Guest",
            "trust_level": "guest",
            "executed_count": 0,
        }
        cond.redis.smembers = AsyncMock(return_value={"abc"})
        cond.redis.mget = AsyncMock(return_value=[json.dumps(cond_data)])

        result = await cond.check_event("sensor.x", "on", "off")
        assert len(result) == 0  # Blocked
