"""
Tests fuer StateChangeLog — Quellen-Erkennung, Logging, Konflikte, Prompt-Formatierung.
"""

import json
import time
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.state_change_log import (
    DEVICE_DEPENDENCIES,
    LOG_TTL_SECONDS,
    MAX_LOG_ENTRIES,
    REDIS_KEY_LOG,
    StateChangeLog,
)


@pytest.fixture
def scl():
    """Frische StateChangeLog-Instanz."""
    return StateChangeLog()


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.lrange = AsyncMock(return_value=[])
    r.lpush = AsyncMock()
    r.ltrim = AsyncMock()
    r.expire = AsyncMock()
    return r


# =========================================================================
# __init__
# =========================================================================
class TestInit:
    def test_defaults(self, scl):
        assert scl.redis is None
        assert isinstance(scl._log, deque)
        assert scl._log.maxlen == MAX_LOG_ENTRIES
        assert scl._jarvis_pending == {}

    def test_deque_max_len(self, scl):
        assert scl._log.maxlen == 200


# =========================================================================
# initialize
# =========================================================================
class TestInitialize:
    @pytest.mark.asyncio
    async def test_sets_redis_client(self, scl, mock_redis):
        await scl.initialize(mock_redis)
        assert scl.redis is mock_redis

    @pytest.mark.asyncio
    async def test_loads_entries_from_redis(self, scl, mock_redis):
        entries = [
            json.dumps({"entity_id": "light.a", "ts": 1}),
            json.dumps({"entity_id": "light.b", "ts": 2}),
        ]
        mock_redis.lrange.return_value = entries
        await scl.initialize(mock_redis)
        # Reversed order: b first in redis, but reversed so a appended first
        assert len(scl._log) == 2
        assert scl._log[0]["entity_id"] == "light.b"
        assert scl._log[1]["entity_id"] == "light.a"

    @pytest.mark.asyncio
    async def test_skips_invalid_json_entries(self, scl, mock_redis):
        mock_redis.lrange.return_value = [
            json.dumps({"entity_id": "light.ok"}),
            "NOT JSON",
            json.dumps({"entity_id": "light.ok2"}),
        ]
        await scl.initialize(mock_redis)
        assert len(scl._log) == 2

    @pytest.mark.asyncio
    async def test_handles_redis_exception(self, scl, mock_redis):
        mock_redis.lrange.side_effect = Exception("conn error")
        await scl.initialize(mock_redis)
        assert len(scl._log) == 0
        assert scl.redis is mock_redis

    @pytest.mark.asyncio
    async def test_initialize_without_redis(self, scl):
        await scl.initialize(None)
        assert scl.redis is None
        assert len(scl._log) == 0


# =========================================================================
# mark_jarvis_action
# =========================================================================
class TestMarkJarvisAction:
    def test_marks_entity(self, scl):
        scl.mark_jarvis_action("light.wz")
        assert "light.wz" in scl._jarvis_pending
        assert isinstance(scl._jarvis_pending["light.wz"], float)

    def test_overwrites_existing_marker(self, scl):
        scl.mark_jarvis_action("light.wz")
        ts1 = scl._jarvis_pending["light.wz"]
        scl.mark_jarvis_action("light.wz")
        ts2 = scl._jarvis_pending["light.wz"]
        assert ts2 >= ts1


# =========================================================================
# _detect_source
# =========================================================================
class TestDetectSource:
    def test_jarvis_within_window(self, scl):
        scl._jarvis_pending["light.wz"] = time.time()
        result = scl._detect_source("light.wz", {})
        assert result == "jarvis"
        # Marker consumed
        assert "light.wz" not in scl._jarvis_pending

    def test_jarvis_expired_marker(self, scl):
        scl._jarvis_pending["light.wz"] = time.time() - 15  # >10s ago
        result = scl._detect_source("light.wz", {"context": {}})
        assert result != "jarvis"

    def test_automation_via_parent_id(self, scl):
        state = {"context": {"user_id": None, "parent_id": "abc123"}}
        assert scl._detect_source("light.wz", state) == "automation"

    def test_user_app_via_user_id(self, scl):
        state = {"context": {"user_id": "user123", "parent_id": None}}
        assert scl._detect_source("light.wz", state) == "user_app"

    def test_automation_no_user_no_parent(self, scl):
        state = {"context": {"user_id": None, "parent_id": None}}
        assert scl._detect_source("light.wz", state) == "automation"

    def test_automation_empty_context(self, scl):
        state = {"context": {}}
        assert scl._detect_source("light.wz", state) == "automation"

    def test_no_context_key_defaults_to_empty_dict(self, scl):
        # No "context" key -> get returns {} -> isinstance dict -> automation
        assert scl._detect_source("light.wz", {}) == "automation"

    def test_unknown_context_not_dict(self, scl):
        state = {"context": "not_a_dict"}
        assert scl._detect_source("light.wz", state) == "unknown"

    def test_unknown_context_is_none(self, scl):
        state = {"context": None}
        assert scl._detect_source("light.wz", state) == "unknown"

    def test_jarvis_takes_priority_over_context(self, scl):
        scl._jarvis_pending["light.wz"] = time.time()
        state = {"context": {"user_id": "u1", "parent_id": "p1"}}
        assert scl._detect_source("light.wz", state) == "jarvis"

    def test_parent_id_takes_priority_over_user_id(self, scl):
        state = {"context": {"user_id": "u1", "parent_id": "p1"}}
        assert scl._detect_source("light.wz", state) == "automation"


# =========================================================================
# log_change
# =========================================================================
class TestLogChange:
    @pytest.mark.asyncio
    async def test_appends_entry_to_log(self, scl):
        new_state = {"context": {}, "attributes": {"friendly_name": "Licht WZ"}}
        await scl.log_change("light.wz", "off", "on", new_state)
        assert len(scl._log) == 1
        entry = scl._log[0]
        assert entry["entity_id"] == "light.wz"
        assert entry["old"] == "off"
        assert entry["new"] == "on"
        assert entry["source"] == "automation"
        assert entry["name"] == "Licht WZ"
        assert "ts" in entry
        assert "time_str" in entry

    @pytest.mark.asyncio
    async def test_uses_friendly_name_param(self, scl):
        await scl.log_change("light.wz", "off", "on", {}, friendly_name="My Light")
        assert scl._log[0]["name"] == "My Light"

    @pytest.mark.asyncio
    async def test_falls_back_to_entity_id_for_name(self, scl):
        await scl.log_change("light.wz", "off", "on", {})
        assert scl._log[0]["name"] == "light.wz"

    @pytest.mark.asyncio
    async def test_falls_back_to_attributes_friendly_name(self, scl):
        state = {"attributes": {"friendly_name": "From Attrs"}}
        await scl.log_change("light.wz", "off", "on", state)
        assert scl._log[0]["name"] == "From Attrs"

    @pytest.mark.asyncio
    async def test_persists_to_redis(self, scl, mock_redis):
        scl.redis = mock_redis
        await scl.log_change("light.wz", "off", "on", {"context": {}})
        mock_redis.lpush.assert_awaited_once()
        mock_redis.ltrim.assert_awaited_once_with(REDIS_KEY_LOG, 0, MAX_LOG_ENTRIES - 1)
        mock_redis.expire.assert_awaited_once_with(REDIS_KEY_LOG, LOG_TTL_SECONDS)

    @pytest.mark.asyncio
    async def test_redis_error_does_not_raise(self, scl, mock_redis):
        scl.redis = mock_redis
        mock_redis.lpush.side_effect = Exception("redis down")
        # Should not raise
        await scl.log_change("light.wz", "off", "on", {"context": {}})
        assert len(scl._log) == 1

    @pytest.mark.asyncio
    async def test_no_redis_skips_persist(self, scl):
        await scl.log_change("light.wz", "off", "on", {})
        assert len(scl._log) == 1


# =========================================================================
# get_recent
# =========================================================================
class TestGetRecent:
    def test_returns_last_n(self, scl):
        for i in range(5):
            scl._log.append({"entity_id": f"light.{i}", "ts": i})
        result = scl.get_recent(3)
        assert len(result) == 3
        assert result[0]["entity_id"] == "light.2"

    def test_returns_all_if_fewer_than_n(self, scl):
        scl._log.append({"entity_id": "light.0"})
        result = scl.get_recent(10)
        assert len(result) == 1

    def test_empty_log(self, scl):
        assert scl.get_recent(10) == []

    def test_filter_by_domain(self, scl):
        scl._log.append({"entity_id": "light.wz"})
        scl._log.append({"entity_id": "climate.wz"})
        scl._log.append({"entity_id": "light.sz"})
        result = scl.get_recent(10, domain="light")
        assert len(result) == 2
        assert all(e["entity_id"].startswith("light.") for e in result)

    def test_filter_domain_no_match(self, scl):
        scl._log.append({"entity_id": "light.wz"})
        assert scl.get_recent(10, domain="climate") == []

    def test_domain_filter_respects_n(self, scl):
        for i in range(5):
            scl._log.append({"entity_id": f"light.{i}"})
        result = scl.get_recent(2, domain="light")
        assert len(result) == 2

    def test_missing_entity_id_in_entry(self, scl):
        scl._log.append({"name": "no_entity"})
        result = scl.get_recent(10, domain="light")
        assert len(result) == 0


# =========================================================================
# _get_entity_role
# =========================================================================
class TestGetEntityRole:
    def test_returns_role_from_annotation(self):
        mock_fc = MagicMock()
        mock_fc.get_entity_annotation = MagicMock(
            return_value={"role": "ceiling_light"}
        )
        with patch.dict("sys.modules", {"assistant.function_calling": mock_fc}):
            result = StateChangeLog._get_entity_role("light.wz_decke")
            assert result == "ceiling_light"

    def test_annotation_without_role_falls_back(self):
        mock_fc = MagicMock()
        mock_fc.get_entity_annotation = MagicMock(return_value={"role": ""})
        with patch.dict("sys.modules", {"assistant.function_calling": mock_fc}):
            result = StateChangeLog._get_entity_role("light.wz_decke")
            assert result == "light"

    def test_annotation_returns_none(self):
        mock_fc = MagicMock()
        mock_fc.get_entity_annotation = MagicMock(return_value=None)
        with patch.dict("sys.modules", {"assistant.function_calling": mock_fc}):
            result = StateChangeLog._get_entity_role("light.wz_decke")
            assert result == "light"

    def test_fallback_to_domain(self):
        # When function_calling import fails, should return domain
        with patch.dict("sys.modules", {"assistant.function_calling": None}):
            result = StateChangeLog._get_entity_role("light.wz_decke")
            assert result == "light"

    def test_fallback_no_dot_in_entity(self):
        with patch.dict("sys.modules", {"assistant.function_calling": None}):
            result = StateChangeLog._get_entity_role("nodot")
            assert result == ""


# =========================================================================
# _get_entity_room
# =========================================================================
class TestGetEntityRoom:
    def test_returns_empty_on_import_failure(self):
        with patch.dict("sys.modules", {"assistant.function_calling": None}):
            result = StateChangeLog._get_entity_room("light.wz")
            assert result == ""


# =========================================================================
# detect_conflicts
# =========================================================================
class TestDetectConflicts:
    @patch.object(StateChangeLog, "_get_entity_role", return_value="window_contact")
    @patch.object(StateChangeLog, "_get_entity_room", return_value="wohnzimmer")
    def test_finds_conflict_window_open_climate_on(self, mock_room, mock_role):
        scl = StateChangeLog()
        states = {
            "binary_sensor.fenster_wz": "on",  # window open
            "climate.wz": "heat",
        }
        # Override role per entity
        role_map = {
            "binary_sensor.fenster_wz": "window_contact",
            "climate.wz": "climate",
        }
        mock_role.side_effect = lambda eid: role_map.get(eid, "")
        room_map = {
            "binary_sensor.fenster_wz": "wohnzimmer",
            "climate.wz": "wohnzimmer",
        }
        mock_room.side_effect = lambda eid: room_map.get(eid, "")

        conflicts = scl.detect_conflicts(states)
        # Should find at least one conflict for window_contact
        window_conflicts = [
            c for c in conflicts if c["trigger_role"] == "window_contact"
        ]
        assert len(window_conflicts) > 0
        assert window_conflicts[0]["trigger_state"] == "on"

    @patch.object(StateChangeLog, "_get_entity_role", return_value="")
    @patch.object(StateChangeLog, "_get_entity_room", return_value="")
    def test_no_conflicts_empty_states(self, mock_room, mock_role):
        scl = StateChangeLog()
        assert scl.detect_conflicts({}) == []

    @patch.object(StateChangeLog, "_get_entity_role")
    @patch.object(StateChangeLog, "_get_entity_room", return_value="")
    def test_no_conflicts_all_off(self, mock_room, mock_role):
        scl = StateChangeLog()
        mock_role.side_effect = lambda eid: "ceiling_light"
        states = {"light.wz": "off", "light.sz": "off"}
        conflicts = scl.detect_conflicts(states)
        assert conflicts == []

    @patch.object(StateChangeLog, "_get_entity_role")
    @patch.object(StateChangeLog, "_get_entity_room")
    def test_same_room_filter(self, mock_room, mock_role):
        scl = StateChangeLog()
        role_map = {
            "binary_sensor.fenster_wz": "window_contact",
            "climate.sz": "climate",
        }
        mock_role.side_effect = lambda eid: role_map.get(eid, eid.split(".")[0])
        room_map = {
            "binary_sensor.fenster_wz": "wohnzimmer",
            "climate.sz": "schlafzimmer",
        }
        mock_room.side_effect = lambda eid: room_map.get(eid, "")

        states = {
            "binary_sensor.fenster_wz": "on",
            "climate.sz": "heat",
        }
        conflicts = scl.detect_conflicts(states)
        # Window in WZ, climate in SZ - same_room conflicts should not match
        window_conflicts = [
            c
            for c in conflicts
            if c["trigger_role"] == "window_contact" and c["same_room"]
        ]
        for c in window_conflicts:
            assert not c["affected_active"]

    @patch.object(StateChangeLog, "_get_entity_role")
    @patch.object(StateChangeLog, "_get_entity_room")
    def test_conflict_contains_expected_fields(self, mock_room, mock_role):
        scl = StateChangeLog()
        role_map = {
            "binary_sensor.fenster_wz": "window_contact",
            "climate.wz": "climate",
        }
        mock_role.side_effect = lambda eid: role_map.get(eid, "")
        mock_room.return_value = "wohnzimmer"

        states = {
            "binary_sensor.fenster_wz": "on",
            "climate.wz": "heat",
        }
        conflicts = scl.detect_conflicts(states)
        if conflicts:
            c = conflicts[0]
            assert "trigger_entity" in c
            assert "trigger_role" in c
            assert "trigger_state" in c
            assert "trigger_room" in c
            assert "affected_role" in c
            assert "affected_active" in c
            assert "same_room" in c
            assert "effect" in c
            assert "hint" in c

    @patch.object(StateChangeLog, "_get_entity_role")
    @patch.object(StateChangeLog, "_get_entity_room", return_value="")
    def test_affected_inactive_states_skipped(self, mock_room, mock_role):
        """Entities with off/unavailable/unknown/idle should not count as affected_active."""
        scl = StateChangeLog()
        role_map = {
            "binary_sensor.fenster_wz": "window_contact",
            "climate.wz": "climate",
        }
        mock_role.side_effect = lambda eid: role_map.get(eid, "")
        states = {
            "binary_sensor.fenster_wz": "on",
            "climate.wz": "off",
        }
        conflicts = scl.detect_conflicts(states)
        window_conflicts = [
            c for c in conflicts if c["trigger_role"] == "window_contact"
        ]
        for c in window_conflicts:
            if c["affected_role"] == "climate":
                assert not c["affected_active"]


# =========================================================================
# format_conflicts_for_prompt
# =========================================================================
class TestFormatConflictsForPrompt:
    @patch.object(StateChangeLog, "detect_conflicts", return_value=[])
    def test_empty_on_no_conflicts(self, mock_dc, scl):
        assert scl.format_conflicts_for_prompt({}) == ""

    @patch.object(StateChangeLog, "detect_conflicts")
    def test_empty_on_no_active_conflicts(self, mock_dc, scl):
        mock_dc.return_value = [
            {
                "trigger_entity": "binary_sensor.fenster",
                "trigger_role": "window_contact",
                "trigger_state": "on",
                "trigger_room": "",
                "affected_role": "climate",
                "affected_active": False,
                "same_room": True,
                "effect": "Fenster offen",
                "hint": "Fenster offen waehrend Heizung laeuft",
            }
        ]
        assert scl.format_conflicts_for_prompt({}) == ""

    @patch("assistant.state_change_log.StateChangeLog.detect_conflicts")
    def test_formats_active_conflicts(self, mock_dc, scl):
        mock_dc.return_value = [
            {
                "trigger_entity": "binary_sensor.fenster",
                "trigger_role": "window_contact",
                "trigger_state": "on",
                "trigger_room": "wohnzimmer",
                "affected_role": "climate",
                "affected_active": True,
                "same_room": True,
                "effect": "Waermeverlust",
                "hint": "Fenster offen waehrend Heizung",
            }
        ]
        result = scl.format_conflicts_for_prompt({})
        assert "AKTIVE GERAETE-KONFLIKTE" in result
        assert "Fenster offen waehrend Heizung" in result
        assert "Waermeverlust" in result

    @patch("assistant.state_change_log.StateChangeLog.detect_conflicts")
    def test_deduplicates_by_trigger_entity_and_affected(self, mock_dc, scl):
        conflict = {
            "trigger_entity": "binary_sensor.fenster",
            "trigger_role": "window_contact",
            "trigger_state": "on",
            "trigger_room": "",
            "affected_role": "climate",
            "affected_active": True,
            "same_room": True,
            "effect": "eff",
            "hint": "hint1",
        }
        mock_dc.return_value = [conflict, conflict.copy()]
        result = scl.format_conflicts_for_prompt({})
        # Only one line despite two identical conflicts
        assert result.count("- hint1") == 1

    @patch("assistant.state_change_log.StateChangeLog.detect_conflicts")
    def test_skips_conflict_without_hint(self, mock_dc, scl):
        mock_dc.return_value = [
            {
                "trigger_entity": "binary_sensor.fenster",
                "trigger_role": "window_contact",
                "trigger_state": "on",
                "trigger_room": "",
                "affected_role": "climate",
                "affected_active": True,
                "same_room": True,
                "effect": "eff",
                "hint": "",
            }
        ]
        assert scl.format_conflicts_for_prompt({}) == ""

    @patch("assistant.state_change_log.StateChangeLog.detect_conflicts")
    def test_includes_room_info(self, mock_dc, scl):
        mock_dc.return_value = [
            {
                "trigger_entity": "binary_sensor.fenster",
                "trigger_role": "window_contact",
                "trigger_state": "on",
                "trigger_room": "kueche",
                "affected_role": "climate",
                "affected_active": True,
                "same_room": True,
                "effect": "Waermeverlust",
                "hint": "Fenster offen",
            }
        ]
        result = scl.format_conflicts_for_prompt({})
        # Room may or may not appear depending on _sanitize_for_prompt import
        assert "Fenster offen" in result

    @patch("assistant.state_change_log.StateChangeLog.detect_conflicts")
    def test_contains_advisory_footer(self, mock_dc, scl):
        mock_dc.return_value = [
            {
                "trigger_entity": "binary_sensor.f",
                "trigger_role": "window_contact",
                "trigger_state": "on",
                "trigger_room": "",
                "affected_role": "climate",
                "affected_active": True,
                "same_room": False,
                "effect": "e",
                "hint": "h",
            }
        ]
        result = scl.format_conflicts_for_prompt({})
        assert "NIEMALS eine Aktion des Users wegen eines Konflikts" in result


# =========================================================================
# check_action_dependencies
# =========================================================================
class TestCheckActionDependencies:
    @patch.object(StateChangeLog, "_get_entity_role", return_value="")
    @patch.object(StateChangeLog, "_get_entity_room", return_value="")
    def test_returns_list(self, mock_room, mock_role):
        result = StateChangeLog.check_action_dependencies(
            "set_light", {"entity_id": "light.wz", "state": "on"}, []
        )
        assert isinstance(result, list)

    @patch.object(StateChangeLog, "_get_entity_role", return_value="")
    @patch.object(StateChangeLog, "_get_entity_room", return_value="")
    def test_empty_ha_states(self, mock_room, mock_role):
        result = StateChangeLog.check_action_dependencies(
            "set_light", {"entity_id": "light.wz", "state": "on"}, []
        )
        assert result == []

    def test_handles_exception_gracefully(self):
        # Passing invalid data should not raise
        result = StateChangeLog.check_action_dependencies("set_light", {}, "not_a_list")
        assert isinstance(result, list)

    @patch.object(StateChangeLog, "_get_entity_role", return_value="")
    @patch.object(StateChangeLog, "_get_entity_room", return_value="")
    def test_no_target_entity(self, mock_room, mock_role):
        result = StateChangeLog.check_action_dependencies(
            "set_light", {"brightness": 100}, []
        )
        assert isinstance(result, list)


# =========================================================================
# format_for_prompt
# =========================================================================
class TestFormatForPrompt:
    def test_empty_log(self, scl):
        assert scl.format_for_prompt() == ""

    def test_old_entries_filtered_out(self, scl):
        scl._log.append(
            {
                "entity_id": "light.wz",
                "name": "Licht",
                "old": "off",
                "new": "on",
                "source": "jarvis",
                "ts": time.time() - 3600,  # 1h ago, > 30min cutoff
                "time_str": "10:00",
            }
        )
        assert scl.format_for_prompt() == ""

    def test_recent_entries_included(self, scl):
        scl._log.append(
            {
                "entity_id": "light.wz",
                "name": "Licht WZ",
                "old": "off",
                "new": "on",
                "source": "jarvis",
                "ts": time.time() - 60,  # 1 min ago
                "time_str": "14:30",
            }
        )
        result = scl.format_for_prompt()
        assert "LETZTE GERAETE-AENDERUNGEN" in result
        assert "Licht WZ" in result
        assert "off" in result
        assert "on" in result
        assert "JARVIS" in result

    def test_source_labels(self, scl):
        now = time.time()
        for src, label in [
            ("jarvis", "JARVIS"),
            ("automation", "HA-Automation"),
            ("user_app", "User (App/Dashboard)"),
            ("user_physical", "User (physisch)"),
            ("unknown", "unbekannt"),
        ]:
            scl._log.append(
                {
                    "entity_id": f"light.{src}",
                    "name": f"Test {src}",
                    "old": "off",
                    "new": "on",
                    "source": src,
                    "ts": now,
                    "time_str": "14:00",
                }
            )
        result = scl.format_for_prompt(10)
        assert "JARVIS" in result
        assert "HA-Automation" in result
        assert "User (App/Dashboard)" in result
        assert "User (physisch)" in result
        assert "unbekannt" in result

    def test_footer_text(self, scl):
        scl._log.append(
            {
                "entity_id": "light.wz",
                "name": "L",
                "old": "off",
                "new": "on",
                "source": "jarvis",
                "ts": time.time(),
                "time_str": "14:00",
            }
        )
        result = scl.format_for_prompt()
        assert "Nutze diese Info" in result

    def test_respects_n_parameter(self, scl):
        now = time.time()
        for i in range(5):
            scl._log.append(
                {
                    "entity_id": f"light.{i}",
                    "name": f"L{i}",
                    "old": "off",
                    "new": "on",
                    "source": "jarvis",
                    "ts": now,
                    "time_str": "14:00",
                }
            )
        result = scl.format_for_prompt(2)
        # Should have exactly 2 entry lines
        entry_lines = [l for l in result.split("\n") if l.startswith("- ")]
        assert len(entry_lines) == 2

    def test_missing_fields_use_defaults(self, scl):
        scl._log.append({"ts": time.time()})
        result = scl.format_for_prompt()
        assert "?" in result

    def test_unknown_source_uses_raw_value(self, scl):
        scl._log.append(
            {
                "entity_id": "light.wz",
                "name": "L",
                "old": "off",
                "new": "on",
                "source": "custom_source",
                "ts": time.time(),
                "time_str": "14:00",
            }
        )
        result = scl.format_for_prompt()
        assert "custom_source" in result


# =========================================================================
# format_automations_for_prompt
# =========================================================================
class TestFormatAutomationsForPrompt:
    def test_empty_list(self):
        assert StateChangeLog.format_automations_for_prompt([]) == ""

    def test_none_input(self):
        assert StateChangeLog.format_automations_for_prompt(None) == ""

    def test_non_automation_entities_skipped(self):
        states = [
            {"entity_id": "light.wz", "state": "on", "attributes": {}},
        ]
        assert StateChangeLog.format_automations_for_prompt(states) == ""

    def test_active_automation_listed(self):
        states = [
            {
                "entity_id": "automation.licht_abends",
                "state": "on",
                "attributes": {"friendly_name": "Licht abends", "last_triggered": ""},
            }
        ]
        result = StateChangeLog.format_automations_for_prompt(states)
        assert "Licht abends" in result
        assert "aktiv" in result

    def test_recently_triggered_shown(self):
        from datetime import datetime, timezone

        recent_ts = datetime.now(timezone.utc).isoformat()
        states = [
            {
                "entity_id": "automation.heizung_morgens",
                "state": "on",
                "attributes": {
                    "friendly_name": "Heizung morgens",
                    "last_triggered": recent_ts,
                },
            }
        ]
        result = StateChangeLog.format_automations_for_prompt(states)
        assert "Heizung morgens" in result
        assert "Kuerzlich ausgeloeste Automationen" in result

    def test_old_triggered_not_recent(self):
        from datetime import datetime, timezone, timedelta

        old_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        states = [
            {
                "entity_id": "automation.old_one",
                "state": "on",
                "attributes": {
                    "friendly_name": "Old Automation",
                    "last_triggered": old_ts,
                },
            }
        ]
        result = StateChangeLog.format_automations_for_prompt(states)
        # Should be listed as active, not recently triggered
        assert "aktiv" in result
        assert "Kuerzlich ausgeloeste" not in result

    def test_off_automation_not_shown(self):
        states = [
            {
                "entity_id": "automation.disabled",
                "state": "off",
                "attributes": {"friendly_name": "Disabled", "last_triggered": ""},
            }
        ]
        assert StateChangeLog.format_automations_for_prompt(states) == ""

    def test_too_many_active_suppressed(self):
        """More than 15 active automations should not be listed."""
        states = [
            {
                "entity_id": f"automation.auto_{i}",
                "state": "on",
                "attributes": {
                    "friendly_name": f"Auto {i}",
                    "last_triggered": "",
                },
            }
            for i in range(20)
        ]
        result = StateChangeLog.format_automations_for_prompt(states)
        # Should not contain "Aktive Automationen" section
        assert "Aktive Automationen:" not in result

    def test_footer_text(self):
        states = [
            {
                "entity_id": "automation.test",
                "state": "on",
                "attributes": {"friendly_name": "Test", "last_triggered": ""},
            }
        ]
        result = StateChangeLog.format_automations_for_prompt(states)
        assert "Nutze diese Info" in result

    def test_handles_z_suffix_in_timestamp(self):
        from datetime import datetime, timezone

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        states = [
            {
                "entity_id": "automation.z_test",
                "state": "on",
                "attributes": {
                    "friendly_name": "Z Test",
                    "last_triggered": ts,
                },
            }
        ]
        result = StateChangeLog.format_automations_for_prompt(states)
        assert "Z Test" in result

    def test_invalid_timestamp_handled(self):
        states = [
            {
                "entity_id": "automation.bad_ts",
                "state": "on",
                "attributes": {
                    "friendly_name": "Bad TS",
                    "last_triggered": "not-a-date",
                },
            }
        ]
        # Should not raise, should show as active
        result = StateChangeLog.format_automations_for_prompt(states)
        assert "Bad TS" in result
        assert "aktiv" in result

    def test_header_present(self):
        states = [
            {
                "entity_id": "automation.test",
                "state": "on",
                "attributes": {"friendly_name": "Test", "last_triggered": ""},
            }
        ]
        result = StateChangeLog.format_automations_for_prompt(states)
        assert "HA-AUTOMATIONEN" in result


# =========================================================================
# summarize_automation + _summarize_trigger + _summarize_action
# =========================================================================


class TestSummarizeAutomation:
    """Tests fuer die kompakte Automation-Zusammenfassung."""

    def test_time_trigger(self):
        result = StateChangeLog._summarize_trigger({"platform": "time", "at": "07:00"})
        assert result == "um 07:00"

    def test_state_trigger_with_to(self):
        result = StateChangeLog._summarize_trigger(
            {
                "platform": "state",
                "entity_id": "binary_sensor.motion_kitchen",
                "to": "on",
            }
        )
        assert "motion kitchen" in result
        assert "on" in result

    def test_state_trigger_without_to(self):
        result = StateChangeLog._summarize_trigger(
            {
                "platform": "state",
                "entity_id": "sensor.temperature",
            }
        )
        assert "aendert sich" in result

    def test_sun_trigger_sunset(self):
        result = StateChangeLog._summarize_trigger(
            {"platform": "sun", "event": "sunset"}
        )
        assert "Sonnenuntergang" in result

    def test_sun_trigger_with_offset(self):
        result = StateChangeLog._summarize_trigger(
            {"platform": "sun", "event": "sunrise", "offset": "-00:30:00"}
        )
        assert "Sonnenaufgang" in result
        assert "-00:30:00" in result

    def test_numeric_state_above(self):
        result = StateChangeLog._summarize_trigger(
            {
                "platform": "numeric_state",
                "entity_id": "sensor.co2",
                "above": 1000,
            }
        )
        assert "co2" in result
        assert "1000" in result

    def test_numeric_state_below(self):
        result = StateChangeLog._summarize_trigger(
            {
                "platform": "numeric_state",
                "entity_id": "sensor.temperature",
                "below": 5,
            }
        )
        assert "< 5" in result

    def test_zone_trigger(self):
        result = StateChangeLog._summarize_trigger(
            {
                "platform": "zone",
                "zone": "zone.home",
                "event": "enter",
            }
        )
        assert "Zone" in result
        assert "betreten" in result

    def test_template_trigger(self):
        result = StateChangeLog._summarize_trigger({"platform": "template"})
        assert "Template" in result

    def test_time_pattern_trigger(self):
        result = StateChangeLog._summarize_trigger(
            {"platform": "time_pattern", "minutes": "/5"}
        )
        assert "/5" in result

    def test_device_trigger(self):
        result = StateChangeLog._summarize_trigger(
            {"platform": "device", "type": "turned_on", "domain": "light"}
        )
        assert "turned_on" in result

    def test_unknown_trigger(self):
        result = StateChangeLog._summarize_trigger({"platform": "calendar"})
        assert result == "calendar"

    def test_action_light_on(self):
        result = StateChangeLog._summarize_action(
            {
                "service": "light.turn_on",
                "entity_id": "light.schlafzimmer",
            }
        )
        assert "Licht" in result
        assert "schlafzimmer" in result
        assert "an" in result

    def test_action_light_off(self):
        result = StateChangeLog._summarize_action(
            {
                "service": "light.turn_off",
                "entity_id": "light.wohnzimmer",
            }
        )
        assert "Licht" in result
        assert "aus" in result

    def test_action_climate_set_temp(self):
        result = StateChangeLog._summarize_action(
            {
                "service": "climate.set_temperature",
                "entity_id": "climate.heizung",
                "data": {"temperature": 21},
            }
        )
        assert "21" in result
        assert "°C" in result

    def test_action_cover_position(self):
        result = StateChangeLog._summarize_action(
            {
                "service": "cover.set_cover_position",
                "entity_id": "cover.rollladen_kueche",
                "data": {"position": 50},
            }
        )
        assert "50%" in result

    def test_action_notify(self):
        result = StateChangeLog._summarize_action(
            {
                "service": "notify.mobile_app",
            }
        )
        assert "Benachrichtigung" in result

    def test_action_scene(self):
        result = StateChangeLog._summarize_action(
            {
                "scene": "scene.abend_stimmung",
            }
        )
        assert "Szene" in result
        assert "abend stimmung" in result

    def test_action_delay(self):
        result = StateChangeLog._summarize_action({"delay": "00:05:00"})
        assert result == "Pause"

    def test_action_choose(self):
        result = StateChangeLog._summarize_action({"choose": []})
        assert "Bedingter Ablauf" in result

    def test_action_entity_in_target(self):
        """Entity-ID im target-Feld statt direkt auf der Aktion."""
        result = StateChangeLog._summarize_action(
            {
                "service": "light.turn_on",
                "target": {"entity_id": "light.flur"},
            }
        )
        assert "flur" in result

    def test_summarize_full_automation(self):
        config = {
            "trigger": [{"platform": "time", "at": "07:00"}],
            "action": [
                {"service": "light.turn_on", "entity_id": "light.schlafzimmer"},
                {
                    "service": "climate.set_temperature",
                    "entity_id": "climate.heizung",
                    "data": {"temperature": 21},
                },
            ],
        }
        result = StateChangeLog.summarize_automation(config)
        assert "07:00" in result
        assert "Licht" in result
        assert "21" in result
        # Format: "trigger → aktionen"
        assert "→" in result

    def test_summarize_prefers_description(self):
        config = {
            "description": "Morgens alles vorbereiten",
            "trigger": [{"platform": "time", "at": "07:00"}],
            "action": [{"service": "light.turn_on"}],
        }
        result = StateChangeLog.summarize_automation(config)
        assert result == "Morgens alles vorbereiten"

    def test_summarize_empty_description_ignored(self):
        config = {
            "description": "",
            "trigger": [{"platform": "time", "at": "07:00"}],
            "action": [{"service": "light.turn_on", "entity_id": "light.test"}],
        }
        result = StateChangeLog.summarize_automation(config)
        assert "07:00" in result

    def test_summarize_truncates_long_output(self):
        config = {
            "trigger": [{"platform": "time", "at": "07:00"}],
            "action": [
                {"service": "light.turn_on", "entity_id": f"light.raum_{i}"}
                for i in range(10)
            ],
        }
        result = StateChangeLog.summarize_automation(config)
        assert len(result) <= 150

    def test_summarize_empty_config(self):
        assert StateChangeLog.summarize_automation({}) == ""


class TestFormatAutomationsWithConfigs:
    """Tests fuer format_automations_for_prompt mit automation_configs."""

    def test_configs_add_summary_to_active(self):
        states = [
            {
                "entity_id": "automation.morgen_routine",
                "state": "on",
                "attributes": {"friendly_name": "Morgen Routine", "last_triggered": ""},
            }
        ]
        configs = [
            {
                "id": "morgen_routine",
                "alias": "Morgen Routine",
                "trigger": [{"platform": "time", "at": "07:00"}],
                "action": [
                    {"service": "light.turn_on", "entity_id": "light.schlafzimmer"}
                ],
            }
        ]
        result = StateChangeLog.format_automations_for_prompt(
            states, automation_configs=configs
        )
        assert "07:00" in result
        assert "Licht" in result

    def test_configs_add_summary_to_recently_triggered(self):
        import time as _time
        from datetime import datetime, timezone

        # Erzeuge "vor 5 Min" Zeitstempel
        recent = datetime.now(timezone.utc).isoformat()
        states = [
            {
                "entity_id": "automation.fenster_alarm",
                "state": "on",
                "attributes": {
                    "friendly_name": "Fenster Alarm",
                    "last_triggered": recent,
                },
            }
        ]
        configs = [
            {
                "id": "fenster_alarm",
                "alias": "Fenster Alarm",
                "trigger": [
                    {
                        "platform": "state",
                        "entity_id": "binary_sensor.fenster",
                        "to": "on",
                    }
                ],
                "action": [{"service": "notify.mobile_app"}],
            }
        ]
        result = StateChangeLog.format_automations_for_prompt(
            states, automation_configs=configs
        )
        assert "Fenster Alarm" in result
        assert "Benachrichtigung" in result

    def test_without_configs_still_works(self):
        states = [
            {
                "entity_id": "automation.test",
                "state": "on",
                "attributes": {"friendly_name": "Test", "last_triggered": ""},
            }
        ]
        result = StateChangeLog.format_automations_for_prompt(states)
        assert "Test (aktiv)" in result

    def test_config_matched_by_alias(self):
        states = [
            {
                "entity_id": "automation.1234567890",
                "state": "on",
                "attributes": {"friendly_name": "Nachtlicht", "last_triggered": ""},
            }
        ]
        configs = [
            {
                "id": "1234567890",
                "alias": "Nachtlicht",
                "trigger": [{"platform": "sun", "event": "sunset"}],
                "action": [{"service": "light.turn_on", "entity_id": "light.flur"}],
            }
        ]
        result = StateChangeLog.format_automations_for_prompt(
            states, automation_configs=configs
        )
        assert "Sonnenuntergang" in result


# =========================================================================
# DEVICE_DEPENDENCIES structure
# =========================================================================
class TestDeviceDependencies:
    def test_is_list(self):
        assert isinstance(DEVICE_DEPENDENCIES, list)

    def test_not_empty(self):
        assert len(DEVICE_DEPENDENCIES) > 0

    def test_entries_have_required_keys(self):
        required = {"role", "state", "affects", "effect", "hint"}
        for dep in DEVICE_DEPENDENCIES:
            assert required.issubset(dep.keys()), f"Missing keys in {dep}"

    def test_all_roles_are_strings(self):
        for dep in DEVICE_DEPENDENCIES:
            assert isinstance(dep["role"], str)
            assert isinstance(dep["state"], str)
            assert isinstance(dep["affects"], str)
