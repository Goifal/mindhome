"""Tests for assistant.self_automation module."""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helper: build a SelfAutomation instance with mocks
# ---------------------------------------------------------------------------

def _make_sa(ha_mock, ollama_mock, yaml_cfg=None):
    """Create a SelfAutomation instance with mocked dependencies."""
    yaml_cfg = yaml_cfg or {}
    with patch("assistant.self_automation.yaml_config", yaml_cfg), \
         patch("assistant.self_automation._load_templates", return_value={}), \
         patch("assistant.self_automation.settings") as settings_mock:
        settings_mock.assistant_name = "Jarvis"
        settings_mock.user_name = "Max"
        settings_mock.model_deep = "test-model"
        from assistant.self_automation import SelfAutomation
        return SelfAutomation(ha_mock, ollama_mock)


# ---------------------------------------------------------------------------
# _extract_json
# ---------------------------------------------------------------------------

class TestExtractJson:
    def test_plain_json(self):
        from assistant.self_automation import SelfAutomation
        data = SelfAutomation._extract_json('{"alias": "test"}')
        assert data == {"alias": "test"}

    def test_json_in_markdown_block(self):
        from assistant.self_automation import SelfAutomation
        text = 'Here is the automation:\n```json\n{"alias": "test"}\n```\nDone.'
        data = SelfAutomation._extract_json(text)
        assert data == {"alias": "test"}

    def test_json_embedded_in_text(self):
        from assistant.self_automation import SelfAutomation
        text = 'Sure: {"alias": "x", "trigger": []} end'
        data = SelfAutomation._extract_json(text)
        assert data is not None
        assert data["alias"] == "x"

    def test_invalid_json_returns_none(self):
        from assistant.self_automation import SelfAutomation
        assert SelfAutomation._extract_json("no json here") is None

    def test_empty_string(self):
        from assistant.self_automation import SelfAutomation
        assert SelfAutomation._extract_json("") is None


# ---------------------------------------------------------------------------
# _extract_room_hint
# ---------------------------------------------------------------------------

class TestExtractRoomHint:
    def test_wohnzimmer(self):
        from assistant.self_automation import SelfAutomation
        assert SelfAutomation._extract_room_hint("Licht im Wohnzimmer an") == "wohnzimmer"

    def test_kueche_umlaut(self):
        from assistant.self_automation import SelfAutomation
        assert SelfAutomation._extract_room_hint("Küche beleuchten") == "kueche"

    def test_no_room(self):
        from assistant.self_automation import SelfAutomation
        assert SelfAutomation._extract_room_hint("etwas machen") == ""


# ---------------------------------------------------------------------------
# _humanize_entity
# ---------------------------------------------------------------------------

class TestHumanizeEntity:
    def test_light(self):
        from assistant.self_automation import SelfAutomation
        assert SelfAutomation._humanize_entity("light.wohnzimmer") == "Wohnzimmer-Licht"

    def test_person(self):
        from assistant.self_automation import SelfAutomation
        assert SelfAutomation._humanize_entity("person.max") == "Max"

    def test_empty(self):
        from assistant.self_automation import SelfAutomation
        assert SelfAutomation._humanize_entity("") == ""

    def test_unknown_domain(self):
        from assistant.self_automation import SelfAutomation
        result = SelfAutomation._humanize_entity("fan.bedroom")
        assert result == "Bedroom"


# ---------------------------------------------------------------------------
# _humanize_state_trigger
# ---------------------------------------------------------------------------

class TestHumanizeStateTrigger:
    def test_person_home(self):
        from assistant.self_automation import SelfAutomation
        result = SelfAutomation._humanize_state_trigger("person.max", "home")
        assert "nach Hause" in result

    def test_person_not_home(self):
        from assistant.self_automation import SelfAutomation
        result = SelfAutomation._humanize_state_trigger("person.max", "not_home")
        assert "verlaesst" in result

    def test_empty_entity(self):
        from assistant.self_automation import SelfAutomation
        result = SelfAutomation._humanize_state_trigger("", "on")
        assert "Zustandsaenderung" in result


# ---------------------------------------------------------------------------
# _humanize_action
# ---------------------------------------------------------------------------

class TestHumanizeAction:
    def test_light_turn_on(self):
        from assistant.self_automation import SelfAutomation
        action = {"service": "light.turn_on", "target": {"entity_id": "light.wohnzimmer"}, "data": {}}
        result = SelfAutomation._humanize_action(action)
        assert "Licht" in result and "einschalten" in result

    def test_with_temperature_data(self):
        from assistant.self_automation import SelfAutomation
        action = {"service": "climate.set_temperature", "target": {"entity_id": "climate.wz"}, "data": {"temperature": 21}}
        result = SelfAutomation._humanize_action(action)
        assert "21" in result


# ---------------------------------------------------------------------------
# _contains_template
# ---------------------------------------------------------------------------

class TestContainsTemplate:
    def test_jinja_curly(self):
        from assistant.self_automation import SelfAutomation
        assert SelfAutomation._contains_template("{{ states('sensor.x') }}") is True

    def test_jinja_block(self):
        from assistant.self_automation import SelfAutomation
        assert SelfAutomation._contains_template("{% if true %}yes{% endif %}") is True

    def test_plain_string(self):
        from assistant.self_automation import SelfAutomation
        assert SelfAutomation._contains_template("hello world") is False

    def test_nested_dict(self):
        from assistant.self_automation import SelfAutomation
        d = {"key": "{{ bad }}"}
        assert SelfAutomation._contains_template(d) is True

    def test_nested_list(self):
        from assistant.self_automation import SelfAutomation
        assert SelfAutomation._contains_template(["safe", "{{ bad }}"]) is True

    def test_clean_dict(self):
        from assistant.self_automation import SelfAutomation
        assert SelfAutomation._contains_template({"key": "safe"}) is False


# ---------------------------------------------------------------------------
# _validate_automation
# ---------------------------------------------------------------------------

class TestValidateAutomation:
    def _get_sa(self):
        ha = AsyncMock()
        ollama = AsyncMock()
        return _make_sa(ha, ollama)

    def test_valid_automation(self):
        sa = self._get_sa()
        auto = {
            "trigger": [{"platform": "state", "entity_id": "light.test"}],
            "action": [{"service": "light.turn_on", "target": {"entity_id": "light.test"}}],
        }
        result = sa._validate_automation(auto)
        assert result["valid"] is True

    def test_blocked_service(self):
        sa = self._get_sa()
        auto = {
            "trigger": [{"platform": "state"}],
            "action": [{"service": "shell_command.evil"}],
        }
        result = sa._validate_automation(auto)
        assert result["valid"] is False
        assert "gesperrt" in result["reason"]

    def test_template_in_action(self):
        sa = self._get_sa()
        auto = {
            "trigger": [{"platform": "state"}],
            "action": [{"service": "light.turn_on", "data": {"brightness": "{{ 255 }}"}}],
        }
        result = sa._validate_automation(auto)
        assert result["valid"] is False

    def test_invalid_trigger_platform(self):
        sa = self._get_sa()
        auto = {
            "trigger": [{"platform": "webhook"}],
            "action": [{"service": "light.turn_on"}],
        }
        result = sa._validate_automation(auto)
        assert result["valid"] is False
        assert "nicht erlaubt" in result["reason"]

    def test_no_actions(self):
        sa = self._get_sa()
        auto = {"trigger": [{"platform": "state"}], "action": []}
        result = sa._validate_automation(auto)
        assert result["valid"] is False

    def test_no_triggers(self):
        sa = self._get_sa()
        auto = {"trigger": [], "action": [{"service": "light.turn_on"}]}
        result = sa._validate_automation(auto)
        assert result["valid"] is False

    def test_service_not_in_whitelist(self):
        sa = self._get_sa()
        auto = {
            "trigger": [{"platform": "state"}],
            "action": [{"service": "lock.unlock"}],
        }
        result = sa._validate_automation(auto)
        assert result["valid"] is False


# ---------------------------------------------------------------------------
# _check_rate_limit
# ---------------------------------------------------------------------------

class TestCheckRateLimit:
    def test_under_limit(self):
        sa = _make_sa(AsyncMock(), AsyncMock())
        assert sa._check_rate_limit() is True

    def test_over_limit(self):
        sa = _make_sa(AsyncMock(), AsyncMock())
        sa._daily_count = sa._max_per_day
        sa._daily_reset = datetime.now()
        assert sa._check_rate_limit() is False

    def test_reset_on_new_day(self):
        sa = _make_sa(AsyncMock(), AsyncMock())
        sa._daily_count = sa._max_per_day
        sa._daily_reset = datetime.now() - timedelta(days=1)
        assert sa._check_rate_limit() is True
        assert sa._daily_count == 0


# ---------------------------------------------------------------------------
# _get_entity_examples
# ---------------------------------------------------------------------------

class TestGetEntityExamples:
    def test_empty_states(self):
        sa = _make_sa(AsyncMock(), AsyncMock())
        result = sa._get_entity_examples([])
        assert "keine Geraete" in result

    def test_with_entities(self):
        sa = _make_sa(AsyncMock(), AsyncMock())
        states = [
            {"entity_id": "light.wohnzimmer"},
            {"entity_id": "sensor.temp"},
        ]
        result = sa._get_entity_examples(states)
        assert "light" in result
        assert "sensor" in result


# ---------------------------------------------------------------------------
# Async: generate_automation (rate-limit path)
# ---------------------------------------------------------------------------

class TestGenerateAutomation:
    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(self):
        sa = _make_sa(AsyncMock(), AsyncMock())
        sa._daily_count = sa._max_per_day
        sa._daily_reset = datetime.now()
        result = await sa.generate_automation("Turn light on at sunset")
        assert result["success"] is False
        assert "Tageslimit" in result["message"]


# ---------------------------------------------------------------------------
# Async: confirm_automation
# ---------------------------------------------------------------------------

class TestConfirmAutomation:
    @pytest.mark.asyncio
    async def test_expired_pending(self):
        sa = _make_sa(AsyncMock(), AsyncMock())
        result = await sa.confirm_automation("nonexistent")
        assert result["success"] is False
        assert "abgelaufen" in result["message"]

    @pytest.mark.asyncio
    async def test_confirm_success(self):
        ha = AsyncMock()
        ha.put_config = AsyncMock(return_value=True)
        sa = _make_sa(ha, AsyncMock())
        sa._pending["abc123"] = {
            "automation": {
                "alias": "Test",
                "trigger": [{"platform": "time"}],
                "action": [{"service": "light.turn_on"}],
            },
            "description": "test",
            "person": "Max",
            "created": datetime.now().isoformat(),
            "method": "template",
        }
        result = await sa.confirm_automation("abc123")
        assert result["success"] is True
        assert result["automation_id"].startswith("jarvis_abc123")


# ---------------------------------------------------------------------------
# Async: delete_jarvis_automation
# ---------------------------------------------------------------------------

class TestDeleteJarvisAutomation:
    @pytest.mark.asyncio
    async def test_refuse_non_jarvis(self):
        sa = _make_sa(AsyncMock(), AsyncMock())
        result = await sa.delete_jarvis_automation("my_manual_auto")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_delete_success(self):
        ha = AsyncMock()
        ha.delete_config = AsyncMock(return_value=True)
        sa = _make_sa(ha, AsyncMock())
        result = await sa.delete_jarvis_automation("jarvis_abc_20260101")
        assert result["success"] is True


# ---------------------------------------------------------------------------
# get_pending_count / cleanup
# ---------------------------------------------------------------------------

class TestPendingCleanup:
    def test_pending_count_zero(self):
        sa = _make_sa(AsyncMock(), AsyncMock())
        assert sa.get_pending_count() == 0

    def test_cleanup_expired(self):
        sa = _make_sa(AsyncMock(), AsyncMock())
        past = (datetime.now() - timedelta(seconds=600)).isoformat()
        sa._pending["old"] = {"created": past, "description": "old"}
        sa._cleanup_expired_pending()
        assert "old" not in sa._pending


# ---------------------------------------------------------------------------
# health_status
# ---------------------------------------------------------------------------

class TestHealthStatus:
    def test_health_status_string(self):
        sa = _make_sa(AsyncMock(), AsyncMock())
        status = sa.health_status()
        assert "active" in status
        assert "daily" in status


# ---------------------------------------------------------------------------
# get_audit_log / _audit
# ---------------------------------------------------------------------------

class TestAuditLog:
    def test_audit_log_empty(self):
        sa = _make_sa(AsyncMock(), AsyncMock())
        assert sa.get_audit_log() == []

    def test_audit_adds_entry(self):
        sa = _make_sa(AsyncMock(), AsyncMock())
        sa._audit("test", "desc", "Max", {"alias": "Test"})
        log = sa.get_audit_log()
        assert len(log) == 1
        assert log[0]["action"] == "test"

    def test_audit_log_limit(self):
        sa = _make_sa(AsyncMock(), AsyncMock())
        for i in range(5):
            sa._audit("test", f"desc{i}", "Max", {})
        assert len(sa.get_audit_log(limit=3)) == 3


# ---------------------------------------------------------------------------
# _build_preview
# ---------------------------------------------------------------------------

class TestBuildPreview:
    def test_time_trigger_preview(self):
        sa = _make_sa(AsyncMock(), AsyncMock())
        auto = {
            "trigger": [{"platform": "time", "at": "07:00:00"}],
            "action": [{"service": "light.turn_on", "target": {"entity_id": "light.wz"}, "data": {}}],
        }
        preview = sa._build_preview(auto, "Licht morgens an")
        assert "07:00" in preview
        assert "Licht" in preview
