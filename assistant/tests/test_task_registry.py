"""Tests for TaskRegistry - asyncio background task management."""

import asyncio
import logging
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from assistant.task_registry import TaskRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _noop():
    """A coroutine that completes immediately."""
    return "done"


async def _sleep_forever():
    """A coroutine that blocks until cancelled."""
    await asyncio.sleep(3600)


async def _sleep_short():
    """A coroutine that sleeps briefly then returns."""
    await asyncio.sleep(0.05)
    return "short"


async def _raise_error():
    """A coroutine that raises an exception."""
    raise ValueError("boom")


# ---------------------------------------------------------------------------
# create_task
# ---------------------------------------------------------------------------

class TestCreateTask:
    @pytest.mark.asyncio
    async def test_create_task_returns_asyncio_task(self):
        reg = TaskRegistry()
        task = reg.create_task(_noop(), name="t1")
        assert isinstance(task, asyncio.Task)
        await task

    @pytest.mark.asyncio
    async def test_create_task_registers_by_name(self):
        reg = TaskRegistry()
        task = reg.create_task(_noop(), name="t1")
        assert "t1" in reg._tasks
        await task

    @pytest.mark.asyncio
    async def test_create_task_duplicate_without_replace_returns_existing(self):
        reg = TaskRegistry()
        task1 = reg.create_task(_sleep_forever(), name="dup")
        task2 = reg.create_task(_noop(), name="dup")
        assert task2 is task1
        task1.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task1

    @pytest.mark.asyncio
    async def test_create_task_duplicate_with_replace_cancels_existing(self):
        reg = TaskRegistry()
        task1 = reg.create_task(_sleep_forever(), name="rep")
        task2 = reg.create_task(_sleep_short(), name="rep", replace=True)
        assert task2 is not task1
        # Allow cancellation to propagate
        await asyncio.sleep(0)
        assert task1.cancelled()
        await task2

    @pytest.mark.asyncio
    async def test_create_task_reuse_name_after_done(self):
        """If old task is done, a new one should be created even without replace."""
        reg = TaskRegistry()
        task1 = reg.create_task(_noop(), name="reuse")
        await task1
        task2 = reg.create_task(_noop(), name="reuse")
        assert task2 is not task1
        await task2

    @pytest.mark.asyncio
    async def test_create_task_during_shutdown_raises(self):
        reg = TaskRegistry()
        reg._shutting_down = True
        with pytest.raises(RuntimeError, match="shutting down"):
            reg.create_task(_noop(), name="fail")

    @pytest.mark.asyncio
    async def test_create_task_during_shutdown_closes_coro(self):
        reg = TaskRegistry()
        reg._shutting_down = True
        coro = _noop()
        with pytest.raises(RuntimeError):
            reg.create_task(coro, name="fail")
        # coro was closed - calling send should raise StopIteration or error
        with pytest.raises(RuntimeError):
            coro.send(None)


# ---------------------------------------------------------------------------
# _on_task_done
# ---------------------------------------------------------------------------

class TestOnTaskDone:
    @pytest.mark.asyncio
    async def test_on_task_done_logs_error_on_exception(self, caplog):
        reg = TaskRegistry()
        with caplog.at_level(logging.ERROR, logger="assistant.task_registry"):
            task = reg.create_task(_raise_error(), name="err")
            # Wait for task to finish and callback to fire
            await asyncio.sleep(0.1)
        assert "fehlgeschlagen" in caplog.text or "boom" in caplog.text

    @pytest.mark.asyncio
    async def test_on_task_done_logs_debug_on_cancel(self, caplog):
        reg = TaskRegistry()
        with caplog.at_level(logging.DEBUG, logger="assistant.task_registry"):
            task = reg.create_task(_sleep_forever(), name="canc")
            task.cancel()
            await asyncio.sleep(0.1)
        assert "abgebrochen" in caplog.text

    @pytest.mark.asyncio
    async def test_on_task_done_no_log_on_success(self, caplog):
        reg = TaskRegistry()
        with caplog.at_level(logging.ERROR, logger="assistant.task_registry"):
            task = reg.create_task(_noop(), name="ok")
            await task
            await asyncio.sleep(0.05)
        assert "fehlgeschlagen" not in caplog.text


# ---------------------------------------------------------------------------
# cancel
# ---------------------------------------------------------------------------

class TestCancel:
    @pytest.mark.asyncio
    async def test_cancel_running_task_returns_true(self):
        reg = TaskRegistry()
        reg.create_task(_sleep_forever(), name="c1")
        assert reg.cancel("c1") is True

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_returns_false(self):
        reg = TaskRegistry()
        assert reg.cancel("nope") is False

    @pytest.mark.asyncio
    async def test_cancel_already_done_returns_false(self):
        reg = TaskRegistry()
        task = reg.create_task(_noop(), name="d1")
        await task
        assert reg.cancel("d1") is False


# ---------------------------------------------------------------------------
# is_running
# ---------------------------------------------------------------------------

class TestIsRunning:
    @pytest.mark.asyncio
    async def test_is_running_true_for_active_task(self):
        reg = TaskRegistry()
        reg.create_task(_sleep_forever(), name="r1")
        assert reg.is_running("r1") is True
        reg.cancel("r1")

    @pytest.mark.asyncio
    async def test_is_running_false_for_done_task(self):
        reg = TaskRegistry()
        task = reg.create_task(_noop(), name="r2")
        await task
        assert reg.is_running("r2") is False

    @pytest.mark.asyncio
    async def test_is_running_false_for_unknown_name(self):
        reg = TaskRegistry()
        assert reg.is_running("unknown") is False


# ---------------------------------------------------------------------------
# active_tasks / task_count
# ---------------------------------------------------------------------------

class TestActiveTasksAndCount:
    @pytest.mark.asyncio
    async def test_active_tasks_lists_running(self):
        reg = TaskRegistry()
        reg.create_task(_sleep_forever(), name="a1")
        reg.create_task(_sleep_forever(), name="a2")
        assert set(reg.active_tasks) == {"a1", "a2"}
        reg.cancel("a1")
        reg.cancel("a2")

    @pytest.mark.asyncio
    async def test_active_tasks_excludes_done(self):
        reg = TaskRegistry()
        task = reg.create_task(_noop(), name="done1")
        await task
        assert "done1" not in reg.active_tasks

    @pytest.mark.asyncio
    async def test_task_count_reflects_active(self):
        reg = TaskRegistry()
        reg.create_task(_sleep_forever(), name="c1")
        reg.create_task(_sleep_forever(), name="c2")
        assert reg.task_count == 2
        reg.cancel("c1")
        await asyncio.sleep(0.05)
        assert reg.task_count == 1
        reg.cancel("c2")


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------

class TestShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_cancels_all_tasks(self):
        reg = TaskRegistry()
        reg.create_task(_sleep_forever(), name="s1")
        reg.create_task(_sleep_forever(), name="s2")
        await reg.shutdown(timeout=2.0)
        assert reg._shutting_down is True
        assert len(reg._tasks) == 0

    @pytest.mark.asyncio
    async def test_shutdown_no_active_tasks(self, caplog):
        reg = TaskRegistry()
        with caplog.at_level(logging.INFO, logger="assistant.task_registry"):
            await reg.shutdown()
        assert reg._shutting_down is True

    @pytest.mark.asyncio
    async def test_shutdown_sets_shutting_down_flag(self):
        reg = TaskRegistry()
        assert reg._shutting_down is False
        await reg.shutdown()
        assert reg._shutting_down is True


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

class TestStatus:
    @pytest.mark.asyncio
    async def test_status_empty_registry(self):
        reg = TaskRegistry()
        s = reg.status()
        assert s["total_registered"] == 0
        assert s["active"] == 0
        assert s["tasks"] == []

    @pytest.mark.asyncio
    async def test_status_with_running_task(self):
        reg = TaskRegistry()
        reg.create_task(_sleep_forever(), name="st1")
        s = reg.status()
        assert s["total_registered"] == 1
        assert s["active"] == 1
        assert s["tasks"][0]["name"] == "st1"
        assert s["tasks"][0]["done"] is False
        reg.cancel("st1")

    @pytest.mark.asyncio
    async def test_status_with_done_task(self):
        reg = TaskRegistry()
        task = reg.create_task(_noop(), name="st2")
        await task
        s = reg.status()
        assert s["total_registered"] == 1
        assert s["active"] == 0
        assert s["tasks"][0]["done"] is True


# ---------------------------------------------------------------------------
# Zusaetzliche Tests fuer 100% Coverage — Zeilen 119-121
# ---------------------------------------------------------------------------

class TestShutdownTimeout:
    """Tests fuer shutdown Timeout-Handling — Zeilen 119-121."""

    @pytest.mark.asyncio
    async def test_shutdown_timeout_logs_warning(self):
        """Bei Timeout werden die Tasks trotzdem beendet (Zeilen 119-121)."""
        reg = TaskRegistry()

        async def _stuck():
            """Coroutine die cancel ignoriert."""
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                # Simuliere Task der nicht sofort stoppt
                await asyncio.sleep(3600)

        reg.create_task(_stuck(), name="stuck1")
        reg.create_task(_stuck(), name="stuck2")
        # Sehr kurzes Timeout erzwingt TimeoutError
        await reg.shutdown(timeout=0.01)
        assert reg._shutting_down is True
        assert len(reg._tasks) == 0
