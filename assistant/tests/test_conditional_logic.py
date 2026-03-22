"""
Isolated tests for ConditionalCommands trigger matching logic.

These tests copy the pure logic as standalone functions so they run
without any project imports.
"""

import pytest

# ---------------------------------------------------------------------------
# Standalone copies of the production logic under test
# ---------------------------------------------------------------------------

OWNER_ONLY_ACTIONS = frozenset(
    {
        "lock_door",
        "unlock_door",
        "arm_security_system",
        "arm_alarm",
        "disarm_alarm",
        "open_garage",
        "close_garage",
        "open_cover",
    }
)


def check_trigger_match(cond, entity_id, new_state, old_state, attributes):
    trigger_type = cond.get("trigger_type", "")
    trigger_value = cond.get("trigger_value", "")

    if trigger_type == "state_change":
        parts = trigger_value.split(":", 1)
        target_entity = parts[0]
        target_state = parts[1] if len(parts) > 1 else None
        if entity_id != target_entity and not entity_id.endswith(target_entity):
            return False
        if target_state and new_state != target_state:
            return False
        if not target_state and new_state == old_state:
            return False
        return True

    elif trigger_type == "person_arrives":
        if not entity_id.startswith("person."):
            return False
        person_name = trigger_value.lower()
        entity_name = entity_id.split(".", 1)[1].lower()
        if person_name not in entity_name:
            return False
        return new_state == "home" and old_state != "home"

    elif trigger_type == "person_leaves":
        if not entity_id.startswith("person."):
            return False
        person_name = trigger_value.lower()
        entity_name = entity_id.split(".", 1)[1].lower()
        if person_name not in entity_name:
            return False
        return old_state == "home" and new_state != "home"

    elif trigger_type == "state_attribute":
        delim = "|" if "|" in trigger_value else ":"
        parts = trigger_value.split(delim, 3)
        if len(parts) < 4:
            return False
        target_entity, attr_name, operator, target_val = parts
        if entity_id != target_entity:
            return False
        attr_val = attributes.get(attr_name)
        if attr_val is None:
            return False
        try:
            attr_num = float(attr_val)
            target_num = float(target_val)
            if operator == ">" and attr_num > target_num:
                return True
            if operator == "<" and attr_num < target_num:
                return True
            if operator == "=" and attr_num == target_num:
                return True
        except (ValueError, TypeError):
            if operator == "=" and str(attr_val) == target_val:
                return True

    return False


# ---------------------------------------------------------------------------
# 1. state_change trigger tests
# ---------------------------------------------------------------------------


class TestStateChange:
    """Tests for trigger_type == 'state_change'."""

    def test_exact_entity_with_target_state(self):
        cond = {"trigger_type": "state_change", "trigger_value": "light.kitchen:on"}
        assert check_trigger_match(cond, "light.kitchen", "on", "off", {}) is True

    def test_exact_entity_wrong_state(self):
        cond = {"trigger_type": "state_change", "trigger_value": "light.kitchen:on"}
        assert check_trigger_match(cond, "light.kitchen", "off", "on", {}) is False

    def test_any_change_no_target_state(self):
        cond = {"trigger_type": "state_change", "trigger_value": "light.kitchen"}
        assert check_trigger_match(cond, "light.kitchen", "on", "off", {}) is True

    def test_same_state_no_target_state(self):
        """When no target state is given, same old/new should NOT match."""
        cond = {"trigger_type": "state_change", "trigger_value": "light.kitchen"}
        assert check_trigger_match(cond, "light.kitchen", "on", "on", {}) is False

    def test_entity_suffix_match(self):
        cond = {"trigger_type": "state_change", "trigger_value": "kitchen:on"}
        assert check_trigger_match(cond, "light.kitchen", "on", "off", {}) is True

    def test_wrong_entity(self):
        cond = {"trigger_type": "state_change", "trigger_value": "light.bedroom:on"}
        assert check_trigger_match(cond, "light.kitchen", "on", "off", {}) is False

    @pytest.mark.parametrize(
        "new,old,expected",
        [
            ("on", "off", True),
            ("off", "on", True),
            ("unavailable", "on", True),
        ],
    )
    def test_any_change_various_transitions(self, new, old, expected):
        cond = {"trigger_type": "state_change", "trigger_value": "switch.fan"}
        assert check_trigger_match(cond, "switch.fan", new, old, {}) is expected


# ---------------------------------------------------------------------------
# 2. person_arrives trigger tests
# ---------------------------------------------------------------------------


class TestPersonArrives:
    """Tests for trigger_type == 'person_arrives'."""

    def test_person_arrives_home(self):
        cond = {"trigger_type": "person_arrives", "trigger_value": "alice"}
        assert check_trigger_match(cond, "person.alice", "home", "away", {}) is True

    def test_non_person_entity(self):
        cond = {"trigger_type": "person_arrives", "trigger_value": "alice"}
        assert (
            check_trigger_match(cond, "device_tracker.alice", "home", "away", {})
            is False
        )

    def test_wrong_person(self):
        cond = {"trigger_type": "person_arrives", "trigger_value": "bob"}
        assert check_trigger_match(cond, "person.alice", "home", "away", {}) is False

    def test_already_home(self):
        """old_state is already 'home' so this is not an arrival."""
        cond = {"trigger_type": "person_arrives", "trigger_value": "alice"}
        assert check_trigger_match(cond, "person.alice", "home", "home", {}) is False

    def test_case_insensitive_name(self):
        cond = {"trigger_type": "person_arrives", "trigger_value": "Alice"}
        assert check_trigger_match(cond, "person.alice", "home", "not_home", {}) is True

    def test_person_leaves_does_not_match_arrives(self):
        cond = {"trigger_type": "person_arrives", "trigger_value": "alice"}
        assert check_trigger_match(cond, "person.alice", "away", "home", {}) is False


# ---------------------------------------------------------------------------
# 3. person_leaves trigger tests
# ---------------------------------------------------------------------------


class TestPersonLeaves:
    """Tests for trigger_type == 'person_leaves'."""

    def test_person_leaves_home(self):
        cond = {"trigger_type": "person_leaves", "trigger_value": "alice"}
        assert check_trigger_match(cond, "person.alice", "away", "home", {}) is True

    def test_non_person_entity(self):
        cond = {"trigger_type": "person_leaves", "trigger_value": "alice"}
        assert check_trigger_match(cond, "sensor.alice", "away", "home", {}) is False

    def test_wrong_person(self):
        cond = {"trigger_type": "person_leaves", "trigger_value": "bob"}
        assert check_trigger_match(cond, "person.alice", "away", "home", {}) is False

    def test_not_previously_home(self):
        """old_state is not 'home' so this is not a departure."""
        cond = {"trigger_type": "person_leaves", "trigger_value": "alice"}
        assert check_trigger_match(cond, "person.alice", "away", "away", {}) is False

    def test_arrives_does_not_match_leaves(self):
        cond = {"trigger_type": "person_leaves", "trigger_value": "alice"}
        assert check_trigger_match(cond, "person.alice", "home", "away", {}) is False


# ---------------------------------------------------------------------------
# 4. state_attribute trigger tests
# ---------------------------------------------------------------------------


class TestStateAttribute:
    """Tests for trigger_type == 'state_attribute'."""

    # --- numeric comparisons ---

    @pytest.mark.parametrize(
        "operator,attr_val,target_val,expected",
        [
            (">", "75", "50", True),
            (">", "50", "50", False),
            (">", "25", "50", False),
            ("<", "25", "50", True),
            ("<", "50", "50", False),
            ("<", "75", "50", False),
            ("=", "50", "50", True),
            ("=", "50.0", "50", True),
            ("=", "49", "50", False),
        ],
    )
    def test_numeric_comparisons_colon_delim(
        self, operator, attr_val, target_val, expected
    ):
        cond = {
            "trigger_type": "state_attribute",
            "trigger_value": f"sensor.temp:temperature:{operator}:{target_val}",
        }
        attrs = {"temperature": attr_val}
        assert check_trigger_match(cond, "sensor.temp", "on", "off", attrs) is expected

    @pytest.mark.parametrize(
        "operator,attr_val,target_val,expected",
        [
            (">", "80", "70", True),
            ("<", "60", "70", True),
            ("=", "70", "70", True),
        ],
    )
    def test_numeric_comparisons_pipe_delim(
        self, operator, attr_val, target_val, expected
    ):
        cond = {
            "trigger_type": "state_attribute",
            "trigger_value": f"sensor.humidity|humidity|{operator}|{target_val}",
        }
        attrs = {"humidity": attr_val}
        assert (
            check_trigger_match(cond, "sensor.humidity", "on", "off", attrs) is expected
        )

    # --- string comparison ---

    def test_string_equality(self):
        cond = {
            "trigger_type": "state_attribute",
            "trigger_value": "media_player.tv:source:=:HDMI 1",
        }
        attrs = {"source": "HDMI 1"}
        assert check_trigger_match(cond, "media_player.tv", "on", "off", attrs) is True

    def test_string_equality_mismatch(self):
        cond = {
            "trigger_type": "state_attribute",
            "trigger_value": "media_player.tv:source:=:HDMI 1",
        }
        attrs = {"source": "HDMI 2"}
        assert check_trigger_match(cond, "media_player.tv", "on", "off", attrs) is False

    # --- missing attribute ---

    def test_missing_attribute(self):
        cond = {
            "trigger_type": "state_attribute",
            "trigger_value": "sensor.temp:temperature:>:50",
        }
        assert check_trigger_match(cond, "sensor.temp", "on", "off", {}) is False

    # --- wrong entity ---

    def test_wrong_entity(self):
        cond = {
            "trigger_type": "state_attribute",
            "trigger_value": "sensor.temp:temperature:>:50",
        }
        attrs = {"temperature": "75"}
        assert check_trigger_match(cond, "sensor.other", "on", "off", attrs) is False

    # --- insufficient parts ---

    @pytest.mark.parametrize(
        "trigger_value",
        [
            "sensor.temp:temperature",
            "sensor.temp:temperature:>",
            "sensor.temp",
        ],
    )
    def test_insufficient_parts(self, trigger_value):
        cond = {"trigger_type": "state_attribute", "trigger_value": trigger_value}
        assert (
            check_trigger_match(cond, "sensor.temp", "on", "off", {"temperature": "75"})
            is False
        )


# ---------------------------------------------------------------------------
# 5. Unknown trigger type
# ---------------------------------------------------------------------------


class TestUnknownTrigger:
    """Unknown or empty trigger types must return False."""

    @pytest.mark.parametrize("trigger_type", ["", "unknown", "magic", "time_based"])
    def test_unknown_trigger_returns_false(self, trigger_type):
        cond = {"trigger_type": trigger_type, "trigger_value": "anything"}
        assert check_trigger_match(cond, "sensor.x", "on", "off", {}) is False

    def test_missing_trigger_type_key(self):
        cond = {"trigger_value": "something"}
        assert check_trigger_match(cond, "sensor.x", "on", "off", {}) is False


# ---------------------------------------------------------------------------
# 6. OWNER_ONLY_ACTIONS
# ---------------------------------------------------------------------------


class TestOwnerOnlyActions:
    """Verify the OWNER_ONLY_ACTIONS set contains expected security actions."""

    @pytest.mark.parametrize(
        "action",
        [
            "lock_door",
            "unlock_door",
            "arm_security_system",
            "arm_alarm",
            "disarm_alarm",
            "open_garage",
            "close_garage",
            "open_cover",
        ],
    )
    def test_expected_action_present(self, action):
        assert action in OWNER_ONLY_ACTIONS

    def test_is_frozenset(self):
        assert isinstance(OWNER_ONLY_ACTIONS, frozenset)

    def test_exact_size(self):
        assert len(OWNER_ONLY_ACTIONS) == 8

    @pytest.mark.parametrize(
        "action",
        [
            "turn_on",
            "turn_off",
            "toggle",
            "set_temperature",
        ],
    )
    def test_non_security_action_absent(self, action):
        assert action not in OWNER_ONLY_ACTIONS
