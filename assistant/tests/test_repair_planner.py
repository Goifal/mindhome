"""
Tests fuer RepairPlanner — Projekt-CRUD, Session, Navigation, Inventar,
Diagnose, Simulation, Troubleshooting, 3D-Drucker, Roboterarm, Timer,
Journal, Snippets, Scanner, Geraete-Management und mehr.
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.repair_planner import (
    RepairPlanner,
    RepairSession,
    RepairStep,
    TEMPLATES,
    REPAIR_KEYWORDS,
    ACTIVATION_ON,
    ACTIVATION_OFF,
    NAV_NEXT,
    NAV_PREV,
)


YAML_CFG = {
    "workshop": {
        "enabled": True,
        "workshop_room": "werkstatt",
        "auto_safety_check": True,
        "proactive_suggestions": True,
    },
}


@pytest.fixture
def ollama():
    m = AsyncMock()
    m.chat = AsyncMock(return_value={
        "message": {"role": "assistant", "content": "Test-Antwort"},
    })
    return m


@pytest.fixture
def ha():
    m = AsyncMock()
    m.get_states = AsyncMock(return_value=[])
    m.call_service = AsyncMock(return_value={"success": True})
    return m


@pytest.fixture
def redis_m():
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.setex = AsyncMock()
    r.set = AsyncMock()
    r.delete = AsyncMock()
    r.hset = AsyncMock()
    r.hget = AsyncMock(return_value=None)
    r.hgetall = AsyncMock(return_value={})
    r.sadd = AsyncMock()
    r.srem = AsyncMock()
    r.smembers = AsyncMock(return_value=set())
    return r


@pytest.fixture
def planner(ollama, ha, redis_m):
    with patch("assistant.repair_planner.yaml_config", YAML_CFG):
        rp = RepairPlanner(ollama, ha)
        rp.redis = redis_m
        return rp


def _make_session(steps=3, current_step=0):
    return RepairSession(
        project_id="p123",
        title="Test-Projekt",
        category="maker",
        steps=[
            RepairStep(number=i + 1, title=f"Schritt {i + 1}",
                       description=f"Beschreibung {i + 1}",
                       tools=["Loetkolben"] if i == 0 else [],
                       parts=["ESP32"] if i == 0 else [])
            for i in range(steps)
        ],
        current_step=current_step,
        started_at="2025-01-01T00:00:00",
    )


# ── Dataclass Tests ──────────────────────────────────────

class TestRepairSession:
    def test_total_steps(self):
        s = _make_session(steps=5)
        assert s.total_steps == 5

    def test_is_finished_false(self):
        s = _make_session(steps=3, current_step=1)
        assert not s.is_finished

    def test_is_finished_true(self):
        s = _make_session(steps=3, current_step=3)
        assert s.is_finished

    def test_get_current_step(self):
        s = _make_session(steps=3, current_step=1)
        step = s.get_current_step()
        assert step is not None
        assert step.number == 2

    def test_get_current_step_out_of_range(self):
        s = _make_session(steps=2, current_step=5)
        assert s.get_current_step() is None


# ── Projekt-CRUD ─────────────────────────────────────────

class TestProjectCRUD:
    @pytest.mark.asyncio
    async def test_create_project(self, planner, redis_m):
        result = await planner.create_project("Test Titel", description="Desc")
        assert result["title"] == "Test Titel"
        assert "id" in result
        redis_m.hset.assert_called()
        redis_m.sadd.assert_called()

    @pytest.mark.asyncio
    async def test_create_project_no_redis(self, ollama, ha):
        with patch("assistant.repair_planner.yaml_config", YAML_CFG):
            rp = RepairPlanner(ollama, ha)
            rp.redis = None
            result = await rp.create_project("X")
            assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_project(self, planner, redis_m):
        redis_m.hgetall.return_value = {
            "id": "p1", "title": "Proj", "parts": "[]", "tools": "[]",
            "notes": "[]", "expenses": "[]",
        }
        proj = await planner.get_project("p1")
        assert proj["title"] == "Proj"
        assert isinstance(proj["parts"], list)

    @pytest.mark.asyncio
    async def test_get_project_not_found(self, planner, redis_m):
        redis_m.hgetall.return_value = {}
        assert await planner.get_project("xxx") is None

    @pytest.mark.asyncio
    async def test_list_projects_empty(self, planner, redis_m):
        redis_m.smembers.return_value = set()
        result = await planner.list_projects()
        assert result == []

    @pytest.mark.asyncio
    async def test_add_project_note(self, planner, redis_m):
        redis_m.hgetall.return_value = {
            "id": "p1", "title": "P", "notes": "[]",
            "parts": "[]", "tools": "[]", "expenses": "[]",
        }
        result = await planner.add_project_note("p1", "Test-Notiz")
        assert result["status"] == "ok"
        assert result["note_count"] == 1

    @pytest.mark.asyncio
    async def test_add_project_note_not_found(self, planner, redis_m):
        redis_m.hgetall.return_value = {}
        result = await planner.add_project_note("xxx", "Notiz")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_add_part(self, planner, redis_m):
        redis_m.hgetall.return_value = {
            "id": "p1", "title": "P", "parts": "[]",
            "tools": "[]", "notes": "[]", "expenses": "[]",
        }
        result = await planner.add_part("p1", "Widerstand", quantity=10)
        assert result["status"] == "ok"
        assert result["part"] == "Widerstand"

    @pytest.mark.asyncio
    async def test_add_missing_to_shopping_all_available(self, planner, redis_m):
        redis_m.hgetall.return_value = {
            "id": "p1", "title": "P",
            "parts": json.dumps([{"name": "X", "available": True}]),
            "tools": "[]", "notes": "[]", "expenses": "[]",
        }
        result = await planner.add_missing_to_shopping("p1")
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_add_missing_to_shopping_missing(self, planner, redis_m):
        redis_m.hgetall.return_value = {
            "id": "p1", "title": "P",
            "parts": json.dumps([{"name": "X", "available": False}]),
            "tools": "[]", "notes": "[]", "expenses": "[]",
        }
        result = await planner.add_missing_to_shopping("p1")
        assert result["status"] == "confirm_needed"
        assert len(result["missing_parts"]) == 1


# ── Navigation ───────────────────────────────────────────

class TestNavigation:
    def test_is_repair_navigation_no_session(self, planner):
        assert not planner.is_repair_navigation("weiter")

    def test_is_repair_navigation_with_session(self, planner):
        planner._session = _make_session()
        assert planner.is_repair_navigation("weiter")
        assert planner.is_repair_navigation("status")
        assert not planner.is_repair_navigation("irgendwas unbekanntes")

    @pytest.mark.asyncio
    async def test_next_step(self, planner, redis_m):
        planner._session = _make_session(steps=3, current_step=0)
        with patch("assistant.repair_planner.emit_workshop", new_callable=AsyncMock, create=True):
            result = await planner.handle_navigation("weiter")
        assert "Schritt 2" in result

    @pytest.mark.asyncio
    async def test_prev_step_at_start(self, planner):
        planner._session = _make_session(steps=3, current_step=0)
        result = await planner.handle_navigation("zurück")
        assert "ersten Schritt" in result

    @pytest.mark.asyncio
    async def test_repeat_step(self, planner):
        planner._session = _make_session(steps=3, current_step=1)
        result = await planner.handle_navigation("nochmal")
        assert "Schritt 2" in result

    @pytest.mark.asyncio
    async def test_status(self, planner):
        planner._session = _make_session(steps=3, current_step=1)
        result = await planner.handle_navigation("status")
        assert "Test-Projekt" in result

    @pytest.mark.asyncio
    async def test_get_parts(self, planner):
        planner._session = _make_session(steps=3, current_step=0)
        result = await planner.handle_navigation("teile")
        assert "ESP32" in result

    @pytest.mark.asyncio
    async def test_get_tools(self, planner):
        planner._session = _make_session(steps=3, current_step=0)
        result = await planner.handle_navigation("werkzeugliste")
        assert "Loetkolben" in result


# ── Inventar / Budget / Templates ────────────────────────

class TestInventarAndBudget:
    @pytest.mark.asyncio
    async def test_add_workshop_item(self, planner, redis_m):
        result = await planner.add_workshop_item("Loetkolben", category="werkzeug")
        assert result["status"] == "ok"
        redis_m.hset.assert_called()

    @pytest.mark.asyncio
    async def test_list_workshop_empty(self, planner, redis_m):
        redis_m.smembers.return_value = set()
        result = await planner.list_workshop()
        assert result == []

    @pytest.mark.asyncio
    async def test_set_project_budget(self, planner, redis_m):
        result = await planner.set_project_budget("p1", 100)
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_add_expense(self, planner, redis_m):
        redis_m.hgetall.return_value = {
            "id": "p1", "title": "P", "expenses": "[]",
            "parts": "[]", "tools": "[]", "notes": "[]",
        }
        result = await planner.add_expense("p1", "Draht", 3.50)
        assert result["status"] == "ok"
        assert result["total"] == 3.50

    @pytest.mark.asyncio
    async def test_create_from_template_valid(self, planner, redis_m):
        result = await planner.create_from_template("esp_sensor")
        assert "id" in result

    @pytest.mark.asyncio
    async def test_create_from_template_invalid(self, planner):
        result = await planner.create_from_template("nonexistent")
        assert result["status"] == "error"


# ── Workshop Environment ─────────────────────────────────

class TestWorkshopEnvironment:
    @pytest.mark.asyncio
    async def test_get_workshop_environment(self, planner, ha):
        ha.get_states.return_value = [
            {"entity_id": "sensor.werkstatt_temperature", "state": "22.5"},
            {"entity_id": "sensor.werkstatt_humidity", "state": "55"},
            {"entity_id": "sensor.wohnzimmer_temperature", "state": "21"},
        ]
        env = await planner.get_workshop_environment()
        assert env.get("temperatur") == "22.5"
        assert env.get("feuchtigkeit") == "55"

    @pytest.mark.asyncio
    async def test_get_workshop_environment_ha_error(self, planner, ha):
        ha.get_states.side_effect = Exception("HA down")
        env = await planner.get_workshop_environment()
        assert env == {}


# ── Safety Checklist ─────────────────────────────────────

class TestSafetyChecklist:
    @pytest.mark.asyncio
    async def test_safety_checklist_loeten(self, planner, redis_m):
        redis_m.hgetall.return_value = {
            "id": "p1", "title": "P", "category": "maker",
            "tools": json.dumps(["loetkolben"]),
            "parts": "[]", "notes": "[]", "expenses": "[]",
        }
        result = await planner.generate_safety_checklist("p1")
        assert "Loetkolben-Ablage" in result

    @pytest.mark.asyncio
    async def test_safety_checklist_reparatur(self, planner, redis_m):
        redis_m.hgetall.return_value = {
            "id": "p1", "title": "P", "category": "reparatur",
            "tools": "[]", "parts": "[]", "notes": "[]", "expenses": "[]",
        }
        result = await planner.generate_safety_checklist("p1")
        assert "Strom" in result

    @pytest.mark.asyncio
    async def test_safety_checklist_not_found(self, planner, redis_m):
        redis_m.hgetall.return_value = {}
        result = await planner.generate_safety_checklist("xxx")
        assert "nicht gefunden" in result


# ── Tool Lending ─────────────────────────────────────────

class TestToolLending:
    @pytest.mark.asyncio
    async def test_lend_tool(self, planner, redis_m):
        result = await planner.lend_tool("Bohrmaschine", "Max")
        assert result["status"] == "ok"
        assert "Max" in result["message"]

    @pytest.mark.asyncio
    async def test_return_tool(self, planner, redis_m):
        result = await planner.return_tool("Bohrmaschine")
        assert result["status"] == "ok"
        redis_m.delete.assert_called()

    @pytest.mark.asyncio
    async def test_record_skill(self, planner, redis_m):
        result = await planner.record_skill("max", "loeten", "advanced")
        assert result["status"] == "ok"
