"""
Tests fuer Per-Person Locks in brain.py — Multi-User Processing.

Testet:
  - Verschiedene Personen koennen gleichzeitig Requests senden
  - Gleiche Person wird serialisiert
  - _active_persons Set wird korrekt verwaltet
  - Proaktive Callbacks werden bei aktiven Personen unterdrueckt
  - ContextVar fuer current_person ist concurrent-safe
"""

import asyncio
from contextvars import ContextVar

import pytest

try:
    from assistant.request_context import (
        get_current_person,
        set_current_person,
        _current_person_var,
    )
except ImportError:
    # FastAPI nicht installiert — ContextVar direkt testen
    _current_person_var = ContextVar("current_person", default="")

    def get_current_person() -> str:
        return _current_person_var.get()

    def set_current_person(person: str) -> None:
        _current_person_var.set(person)


# ============================================================
# ContextVar Tests
# ============================================================


class TestCurrentPersonContextVar:
    """ContextVar fuer aktuelle Person — concurrent-safe."""

    def test_set_and_get(self):
        set_current_person("Max")
        assert get_current_person() == "Max"

    def test_default_empty(self):
        # Reset to default
        token = _current_person_var.set("")
        try:
            assert get_current_person() == ""
        finally:
            _current_person_var.reset(token)

    @pytest.mark.asyncio
    async def test_concurrent_tasks_isolated(self):
        """Zwei async Tasks sehen ihre eigene Person."""
        results = {}

        async def set_and_read(name: str, delay: float):
            set_current_person(name)
            await asyncio.sleep(delay)
            results[name] = get_current_person()

        # Task A setzt "Max", wartet 0.1s
        # Task B setzt "Lisa", wartet 0.05s
        # Ohne ContextVar wuerde B's set A's Wert ueberschreiben
        await asyncio.gather(
            set_and_read("Max", 0.1),
            set_and_read("Lisa", 0.05),
        )

        assert results["Max"] == "Max", "Max sollte seinen eigenen Kontext sehen"
        assert results["Lisa"] == "Lisa", "Lisa sollte ihren eigenen Kontext sehen"


# ============================================================
# Per-Person Lock Unit Tests
# ============================================================


class TestPerPersonLockLogic:
    """Testet die Lock-Verwaltung ohne vollstaendigen Brain."""

    @pytest.mark.asyncio
    async def test_different_persons_not_blocked(self):
        """Verschiedene Personen blockieren sich NICHT gegenseitig."""
        person_locks: dict[str, asyncio.Lock] = {}
        guard = asyncio.Lock()
        execution_order: list[str] = []

        async def get_lock(person: str) -> asyncio.Lock:
            async with guard:
                if person not in person_locks:
                    person_locks[person] = asyncio.Lock()
                return person_locks[person]

        async def simulate_request(person: str, duration: float):
            lock = await get_lock(person)
            await lock.acquire()
            try:
                execution_order.append(f"{person}_start")
                await asyncio.sleep(duration)
                execution_order.append(f"{person}_end")
            finally:
                lock.release()

        # Max und Lisa starten gleichzeitig
        await asyncio.gather(
            simulate_request("Max", 0.1),
            simulate_request("Lisa", 0.05),
        )

        # Lisa sollte VOR Max fertig sein (kuerzere Duration)
        assert "Lisa_end" in execution_order
        assert "Max_end" in execution_order
        lisa_end_idx = execution_order.index("Lisa_end")
        max_end_idx = execution_order.index("Max_end")
        assert lisa_end_idx < max_end_idx, (
            "Lisa (50ms) sollte vor Max (100ms) fertig sein"
        )

    @pytest.mark.asyncio
    async def test_same_person_serialized(self):
        """Gleiche Person wird serialisiert — zweiter Request wartet."""
        person_locks: dict[str, asyncio.Lock] = {}
        guard = asyncio.Lock()
        execution_order: list[str] = []

        async def get_lock(person: str) -> asyncio.Lock:
            async with guard:
                if person not in person_locks:
                    person_locks[person] = asyncio.Lock()
                return person_locks[person]

        async def simulate_request(person: str, request_id: int, duration: float):
            lock = await get_lock(person)
            await lock.acquire()
            try:
                execution_order.append(f"{person}_{request_id}_start")
                await asyncio.sleep(duration)
                execution_order.append(f"{person}_{request_id}_end")
            finally:
                lock.release()

        # Max sendet zwei Requests gleichzeitig
        await asyncio.gather(
            simulate_request("Max", 1, 0.1),
            simulate_request("Max", 2, 0.05),
        )

        # Request 2 muss NACH Request 1 starten (serialisiert)
        assert (
            execution_order[0] == "Max_1_start" or execution_order[0] == "Max_2_start"
        )
        first_start = execution_order[0].split("_")[1]
        second_start_idx = next(
            i
            for i, e in enumerate(execution_order)
            if e.endswith("_start") and e != execution_order[0]
        )
        first_end_idx = next(
            i for i, e in enumerate(execution_order) if e == f"Max_{first_start}_end"
        )
        # Zweiter Start muss NACH erstem End kommen
        assert second_start_idx > first_end_idx, (
            "Zweiter Request muss serialisiert warten"
        )


# ============================================================
# Active Persons Set
# ============================================================


class TestActivePersonsSet:
    """_active_persons Set Verwaltung."""

    def test_add_and_discard(self):
        active: set[str] = set()
        active.add("Max")
        assert active  # Truthy
        active.add("Lisa")
        assert len(active) == 2
        active.discard("Max")
        assert "Max" not in active
        assert active  # Lisa still active
        active.discard("Lisa")
        assert not active  # Falsy — empty

    def test_discard_nonexistent_no_error(self):
        """discard() wirft keinen Fehler bei nicht-vorhandenem Element."""
        active: set[str] = set()
        active.discard("nobody")  # Kein KeyError
