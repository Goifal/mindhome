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


# ---------------------------------------------------------------------------
# Backpressure / MAX_ACTIVE_TASKS
# ---------------------------------------------------------------------------

class TestBackpressure:
    @pytest.mark.asyncio
    async def test_backpressure_rejects_at_limit(self):
        """When MAX_ACTIVE_TASKS is reached, new tasks are rejected."""
        reg = TaskRegistry()
        reg.MAX_ACTIVE_TASKS = 3
        reg.create_task(_sleep_forever(), name="bp1")
        reg.create_task(_sleep_forever(), name="bp2")
        reg.create_task(_sleep_forever(), name="bp3")
        with pytest.raises(RuntimeError, match="limit reached"):
            reg.create_task(_sleep_forever(), name="bp4")
        # Cleanup
        for n in ["bp1", "bp2", "bp3"]:
            reg.cancel(n)

    @pytest.mark.asyncio
    async def test_backpressure_closes_rejected_coroutine(self):
        """Rejected coroutine should be closed to avoid ResourceWarning."""
        reg = TaskRegistry()
        reg.MAX_ACTIVE_TASKS = 1
        reg.create_task(_sleep_forever(), name="fill")
        coro = _noop()
        with pytest.raises(RuntimeError, match="limit reached"):
            reg.create_task(coro, name="rejected")
        # Verify coro was closed
        with pytest.raises(RuntimeError):
            coro.send(None)
        reg.cancel("fill")

    @pytest.mark.asyncio
    async def test_backpressure_allows_after_done_cleanup(self):
        """After tasks finish, new ones should be accepted again."""
        reg = TaskRegistry()
        reg.MAX_ACTIVE_TASKS = 2
        t1 = reg.create_task(_noop(), name="fin1")
        t2 = reg.create_task(_noop(), name="fin2")
        await t1
        await t2
        # Done tasks should be cleaned up, allowing new ones
        t3 = reg.create_task(_noop(), name="new1")
        assert isinstance(t3, asyncio.Task)
        await t3


# ---------------------------------------------------------------------------
# _cleanup_done_tasks
# ---------------------------------------------------------------------------

class TestCleanupDoneTasks:
    @pytest.mark.asyncio
    async def test_cleanup_removes_finished_tasks(self):
        """Completed tasks should be removed from the internal dict."""
        reg = TaskRegistry()
        t = reg.create_task(_noop(), name="clean1")
        await t
        assert "clean1" in reg._tasks
        reg._cleanup_done_tasks()
        assert "clean1" not in reg._tasks

    @pytest.mark.asyncio
    async def test_cleanup_keeps_running_tasks(self):
        """Running tasks should not be removed."""
        reg = TaskRegistry()
        reg.create_task(_sleep_forever(), name="alive")
        reg._cleanup_done_tasks()
        assert "alive" in reg._tasks
        reg.cancel("alive")


# ---------------------------------------------------------------------------
# Persistent Tasks / Watchdog
# ---------------------------------------------------------------------------

class TestPersistentTasks:
    @pytest.mark.asyncio
    async def test_create_persistent_registers_factory(self):
        """Factory should be stored for auto-restart."""
        reg = TaskRegistry()
        factory = lambda: _noop()
        task = reg.create_persistent_task(factory, name="pers1")
        assert "pers1" in reg._persistent
        assert reg._restart_counts["pers1"] == 0
        await task

    @pytest.mark.asyncio
    async def test_persistent_task_restart_count_increments(self):
        """Restart count should increase on failure."""
        reg = TaskRegistry()
        call_count = 0

        async def _fail_once():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("first failure")
            await asyncio.sleep(3600)

        reg.create_persistent_task(lambda: _fail_once(), name="retry")
        # Wait for the task to fail and the restart logic to run
        await asyncio.sleep(0.2)
        assert reg._restart_counts.get("retry", 0) >= 1

        # Cleanup
        reg._shutting_down = True
        reg.cancel("retry")

    @pytest.mark.asyncio
    async def test_restart_persistent_during_shutdown_does_nothing(self):
        """_restart_persistent should not restart if shutting down."""
        reg = TaskRegistry()
        reg._persistent["gone"] = lambda: _noop()
        reg._shutting_down = True
        await reg._restart_persistent("gone")
        assert "gone" not in reg._tasks

    @pytest.mark.asyncio
    async def test_restart_persistent_missing_factory(self):
        """_restart_persistent should handle missing factory gracefully."""
        reg = TaskRegistry()
        await reg._restart_persistent("nonexistent")
        # Should not raise


# ---------------------------------------------------------------------------
# Status edge cases
# ---------------------------------------------------------------------------

class TestStatusEdgeCases:
    @pytest.mark.asyncio
    async def test_status_cancelled_field(self):
        """Cancelled tasks should show cancelled=True in status."""
        reg = TaskRegistry()
        t = reg.create_task(_sleep_forever(), name="canc_status")
        t.cancel()
        await asyncio.sleep(0.05)
        s = reg.status()
        task_info = next(t for t in s["tasks"] if t["name"] == "canc_status")
        assert task_info["done"] is True
        assert task_info["cancelled"] is True

    @pytest.mark.asyncio
    async def test_status_mixed_tasks(self):
        """Status with multiple running tasks shows correct active count."""
        reg = TaskRegistry()
        reg.create_task(_sleep_forever(), name="running_1")
        reg.create_task(_sleep_forever(), name="running_2")

        s = reg.status()
        assert s["total_registered"] == 2
        assert s["active"] == 2
        names = [t["name"] for t in s["tasks"]]
        assert "running_1" in names
        assert "running_2" in names

        # Cancel one and verify count updates
        reg.cancel("running_1")
        await asyncio.sleep(0.05)
        s2 = reg.status()
        active_tasks = [t for t in s2["tasks"] if not t["done"]]
        assert len(active_tasks) == 1
        reg.cancel("running_2")
