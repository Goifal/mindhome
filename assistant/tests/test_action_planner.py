"""
Tests fuer ActionPlanner — Komplexitaets-Erkennung, Narration, Rollback, Planning Dialoge.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.action_planner import (
    ActionPlanner,
    ActionPlan,
    PlanStep,
)


YAML_CFG = {
    "planner": {
        "max_iterations": 8,
        "model": "test-model",
        "max_tokens": 512,
    },
    "narration": {
        "enabled": True,
        "default_transition": 3,
        "scene_transitions": {"filmabend": 8, "romantik": 10},
        "step_delay": 0,  # No delay in tests
        "narrate_actions": True,
    },
}


@pytest.fixture
def ollama():
    m = AsyncMock()
    m.chat = AsyncMock(return_value={
        "message": {"role": "assistant", "content": "Fertig.", "tool_calls": []},
    })
    return m


@pytest.fixture
def executor():
    m = AsyncMock()
    m.execute = AsyncMock(return_value={"success": True, "message": "OK"})
    return m


@pytest.fixture
def validator():
    m = MagicMock()
    result = MagicMock()
    result.ok = True
    result.needs_confirmation = False
    result.reason = ""
    m.validate.return_value = result
    return m


@pytest.fixture
def planner(ollama, executor, validator):
    with patch("assistant.action_planner.yaml_config", YAML_CFG):
        with patch("assistant.action_planner._planner_cfg", YAML_CFG["planner"]):
            ap = ActionPlanner(ollama, executor, validator)
    return ap


# ── is_complex_request ───────────────────────────────────

class TestIsComplexRequest:
    def test_complex_with_keyword(self, planner):
        assert planner.is_complex_request("Mach alles fertig machen fuer morgen")

    def test_complex_routine(self, planner):
        assert planner.is_complex_request("Starte die Morgenroutine")

    def test_not_complex_simple(self, planner):
        assert not planner.is_complex_request("Licht an")

    def test_not_complex_question(self, planner):
        assert not planner.is_complex_request("Was ist die Temperatur?")

    def test_not_complex_question_start(self, planner):
        assert not planner.is_complex_request("Wie warm ist es ueberall?")

    def test_complex_with_party(self, planner):
        assert planner.is_complex_request("Bereite die Party vor")


# ── is_planning_request ──────────────────────────────────

class TestIsPlanningRequest:
    def test_planning_dinner(self, planner):
        assert planner.is_planning_request("Plane eine Dinner Party")

    def test_planning_organisiere(self, planner):
        assert planner.is_planning_request("Organisiere meinen Geburtstag")

    def test_not_planning(self, planner):
        assert not planner.is_planning_request("Licht an im Wohnzimmer")


# ── Narration Helpers ────────────────────────────────────

class TestNarration:
    def test_get_transition_default(self, planner):
        assert planner._get_transition("Licht an") == 3

    def test_get_transition_scene(self, planner):
        assert planner._get_transition("Filmabend starten") == 8
        assert planner._get_transition("Romantik Modus") == 10

    def test_narration_text_light_dim(self):
        text = ActionPlanner._get_narration_text("set_light", {
            "room": "wohnzimmer", "state": "on", "brightness": 30,
        })
        assert "dimmt" in text

    def test_narration_text_light_full(self):
        text = ActionPlanner._get_narration_text("set_light", {
            "room": "wohnzimmer", "state": "on", "brightness": 100,
        })
        assert text == ""

    def test_narration_text_cover(self):
        text = ActionPlanner._get_narration_text("set_cover", {
            "room": "wohnzimmer", "position": 0,
        })
        assert "faehrt" in text

    def test_narration_text_unknown_func(self):
        text = ActionPlanner._get_narration_text("unknown_func", {})
        assert text == ""


# ── Rollback Info ────────────────────────────────────────

class TestRollbackInfo:
    def test_rollback_light_on(self):
        fn, args = ActionPlanner._get_rollback_info("set_light", {"room": "wz", "state": "on"})
        assert fn == "set_light"
        assert args["state"] == "off"

    def test_rollback_light_off(self):
        fn, args = ActionPlanner._get_rollback_info("set_light", {"room": "wz", "state": "off"})
        assert fn == "set_light"
        assert args["state"] == "on"

    def test_rollback_cover(self):
        fn, args = ActionPlanner._get_rollback_info("set_cover", {"room": "wz", "position": 0})
        assert fn == "set_cover"
        assert args["position"] == 100

    def test_rollback_lock(self):
        fn, args = ActionPlanner._get_rollback_info("lock_door", {"door": "front", "action": "unlock"})
        assert fn == "lock_door"
        assert args["action"] == "lock"

    def test_rollback_scene_not_possible(self):
        fn, args = ActionPlanner._get_rollback_info("activate_scene", {"scene": "movie"})
        assert fn is None
        assert args is None

    def test_rollback_unknown_func(self):
        fn, args = ActionPlanner._get_rollback_info("play_media", {"url": "x"})
        assert fn is None
        assert args is None


# ── ActionPlan ───────────────────────────────────────────

class TestActionPlan:
    def test_to_dict(self):
        plan = ActionPlan(request="test request")
        plan.steps.append(PlanStep(function="set_light", args={"room": "wz"}, status="done"))
        plan.summary = "Fertig"
        plan.iterations = 1
        d = plan.to_dict()
        assert d["request"] == "test request"
        assert len(d["steps"]) == 1
        assert d["summary"] == "Fertig"
        assert d["rollback_performed"] is False

    def test_to_dict_empty(self):
        plan = ActionPlan(request="")
        d = plan.to_dict()
        assert d["steps"] == []
        assert d["needs_confirmation"] is False


# ── get_last_plan ────────────────────────────────────────

class TestGetLastPlan:
    def test_no_last_plan(self, planner):
        assert planner.get_last_plan() is None

    def test_with_last_plan(self, planner):
        planner._last_plan = ActionPlan(request="test")
        result = planner.get_last_plan()
        assert result is not None
        assert result["request"] == "test"


# ── plan_and_execute ─────────────────────────────────────

class TestPlanAndExecute:
    @pytest.mark.asyncio
    async def test_plan_simple_no_tools(self, planner, ollama):
        ollama.chat.return_value = {
            "message": {"role": "assistant", "content": "Alles erledigt.", "tool_calls": []},
        }
        with patch("assistant.action_planner.get_assistant_tools", return_value=[]):
            result = await planner.plan_and_execute(
                "Alles fertig machen", "System prompt", {}, [],
            )
        assert "response" in result
        assert result["response"] == "Alles erledigt."

    @pytest.mark.asyncio
    async def test_plan_with_tool_calls(self, planner, ollama, executor):
        # First call returns tool calls, second returns summary
        ollama.chat.side_effect = [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "set_light", "arguments": {"room": "wz", "state": "on"}}},
                    ],
                },
            },
            {
                "message": {"role": "assistant", "content": "Licht ist an.", "tool_calls": []},
            },
        ]
        with patch("assistant.action_planner.get_assistant_tools", return_value=[]):
            with patch("assistant.action_planner.emit_action", new_callable=AsyncMock):
                with patch("assistant.action_planner.emit_speaking", new_callable=AsyncMock):
                    result = await planner.plan_and_execute(
                        "Mach alles fertig", "System", {}, [],
                    )
        assert result["response"] == "Licht ist an."
        assert len(result["actions"]) == 1

    @pytest.mark.asyncio
    async def test_plan_llm_error(self, planner, ollama):
        ollama.chat.return_value = {"error": "Model not found"}
        with patch("assistant.action_planner.get_assistant_tools", return_value=[]):
            result = await planner.plan_and_execute("Test", "System", {}, [])
        assert "Fehler" in result["response"]


# ── Rollback Mechanism ───────────────────────────────────

class TestRollback:
    @pytest.mark.asyncio
    async def test_rollback_completed_steps(self, planner, executor):
        steps = [
            PlanStep(function="set_light", args={"room": "wz", "state": "on"},
                     status="done", rollback_function="set_light",
                     rollback_args={"room": "wz", "state": "off"}),
            PlanStep(function="set_cover", args={"room": "wz", "position": 0},
                     status="done", rollback_function="set_cover",
                     rollback_args={"room": "wz", "position": 100}),
        ]
        count = await planner._rollback_completed_steps(steps)
        assert count == 2
        assert executor.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_rollback_skips_non_done(self, planner, executor):
        steps = [
            PlanStep(function="set_light", args={}, status="failed"),
            PlanStep(function="set_light", args={}, status="blocked"),
        ]
        count = await planner._rollback_completed_steps(steps)
        assert count == 0

    @pytest.mark.asyncio
    async def test_rollback_skips_no_rollback_info(self, planner, executor):
        steps = [
            PlanStep(function="activate_scene", args={}, status="done",
                     rollback_function=None, rollback_args=None),
        ]
        count = await planner._rollback_completed_steps(steps)
        assert count == 0


# ── Planning Dialogs ─────────────────────────────────────

class TestPlanningDialogs:
    @pytest.mark.asyncio
    async def test_start_planning_dialog(self, planner, ollama):
        with patch("assistant.action_planner.settings") as mock_settings:
            mock_settings.assistant_name = "JARVIS"
            mock_settings.model_fast = "fast-model"
            with patch("assistant.action_planner.get_person_title", return_value="Sir"):
                result = await planner.start_planning_dialog("Plane eine Dinner Party")
        assert "plan_id" in result
        assert result["status"] == "waiting_for_details"

    def test_has_pending_plan_none(self, planner):
        assert planner.has_pending_plan() is None

    def test_has_pending_plan_exists(self, planner):
        planner._pending_plans["plan_abc"] = {
            "status": "waiting_for_details",
            "created_at": time.time(),
        }
        result = planner.has_pending_plan()
        assert result == "plan_abc"

    def test_has_pending_plan_expired(self, planner):
        planner._pending_plans["plan_old"] = {
            "status": "waiting_for_details",
            "created_at": time.time() - 700,  # >10 min
        }
        result = planner.has_pending_plan()
        assert result is None
        assert "plan_old" not in planner._pending_plans

    def test_clear_plan(self, planner):
        planner._pending_plans["plan_x"] = {"status": "waiting_for_details"}
        planner.clear_plan("plan_x")
        assert "plan_x" not in planner._pending_plans

    @pytest.mark.asyncio
    async def test_continue_planning_dialog_expired(self, planner):
        result = await planner.continue_planning_dialog("Details...", "nonexistent")
        assert result["status"] == "error"

    def test_cleanup_expired_plans(self, planner):
        planner._pending_plans["old"] = {"created_at": time.time() - 700}
        planner._pending_plans["new"] = {"created_at": time.time()}
        planner._cleanup_expired_plans()
        assert "old" not in planner._pending_plans
        assert "new" in planner._pending_plans
