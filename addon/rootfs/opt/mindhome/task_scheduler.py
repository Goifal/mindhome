# MindHome - task_scheduler.py | see version.py for version info
"""
Generic task scheduler for periodic and one-shot tasks.
Phase 4 ready: Energieoptimierung, Schlaf-Erkennung etc. können
eigene Tasks registrieren ohne eigene Thread-Loops zu brauchen.
"""

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional, Dict

logger = logging.getLogger("mindhome.task_scheduler")


class ScheduledTask:
    """A registered periodic or one-shot task."""

    def __init__(self, name: str, callback: Callable, interval_seconds: int,
                 run_immediately: bool = False, one_shot: bool = False,
                 enabled: bool = True):
        self.name = name
        self.callback = callback
        self.interval_seconds = interval_seconds
        self.run_immediately = run_immediately
        self.one_shot = one_shot
        self.enabled = enabled
        self.last_run: Optional[float] = None
        self.next_run: float = 0 if run_immediately else time.time() + interval_seconds
        self.run_count: int = 0
        self.error_count: int = 0
        self.last_error: Optional[str] = None
        self.last_duration: float = 0


class TaskScheduler:
    """Central scheduler that runs registered tasks in a single thread.
    
    Usage:
        scheduler = TaskScheduler()
        scheduler.register("cleanup", cleanup_func, interval_seconds=3600)
        scheduler.register("energy_calc", energy_func, interval_seconds=300)
        scheduler.start()
    """

    def __init__(self, tick_interval: float = 5.0):
        self._tasks: Dict[str, ScheduledTask] = {}
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()
        self._tick_interval = tick_interval  # How often to check for due tasks

    def register(self, name: str, callback: Callable, interval_seconds: int,
                 run_immediately: bool = False, one_shot: bool = False,
                 enabled: bool = True) -> bool:
        """Register a new periodic task.
        
        Args:
            name: Unique task name
            callback: Function to call (no arguments)
            interval_seconds: Run every N seconds
            run_immediately: Run once immediately on start
            one_shot: Run only once, then auto-disable
            enabled: Start enabled
            
        Returns:
            True if registered, False if name already exists
        """
        with self._lock:
            if name in self._tasks:
                logger.warning(f"Task '{name}' already registered, updating")
                self._tasks[name].callback = callback
                self._tasks[name].interval_seconds = interval_seconds
                self._tasks[name].enabled = enabled
                return True

            task = ScheduledTask(name, callback, interval_seconds,
                                 run_immediately, one_shot, enabled)
            self._tasks[name] = task
            logger.info(f"Task registered: '{name}' (every {interval_seconds}s)")
            return True

    def unregister(self, name: str) -> bool:
        """Remove a task."""
        with self._lock:
            if name in self._tasks:
                del self._tasks[name]
                logger.info(f"Task unregistered: '{name}'")
                return True
        return False

    def enable(self, name: str) -> bool:
        """Enable a disabled task."""
        if name in self._tasks:
            self._tasks[name].enabled = True
            return True
        return False

    def disable(self, name: str) -> bool:
        """Disable a task without removing it."""
        if name in self._tasks:
            self._tasks[name].enabled = False
            return True
        return False

    def trigger_now(self, name: str) -> bool:
        """Trigger a task to run on next tick."""
        if name in self._tasks:
            self._tasks[name].next_run = 0
            return True
        return False

    def start(self):
        """Start the scheduler thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, 
                                         name="MindHome-TaskScheduler")
        self._thread.start()
        logger.info(f"TaskScheduler started ({len(self._tasks)} tasks)")

    def stop(self):
        """Stop the scheduler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("TaskScheduler stopped")

    def _run_loop(self):
        """Main scheduler loop."""
        while self._running:
            now = time.time()
            tasks_to_run = []

            with self._lock:
                for task in self._tasks.values():
                    if task.enabled and now >= task.next_run:
                        tasks_to_run.append(task)

            for task in tasks_to_run:
                self._execute_task(task, now)

            time.sleep(self._tick_interval)

    def _execute_task(self, task: ScheduledTask, now: float):
        """Execute a single task safely."""
        start = time.time()
        try:
            task.callback()
            task.run_count += 1
            task.last_run = now
            task.last_duration = time.time() - start

            if task.one_shot:
                task.enabled = False
                logger.info(f"One-shot task '{task.name}' completed, disabled")
            else:
                task.next_run = now + task.interval_seconds

            logger.debug(f"Task '{task.name}' completed in {task.last_duration:.2f}s")

        except Exception as e:
            task.error_count += 1
            task.last_error = str(e)
            task.next_run = now + task.interval_seconds  # Retry next interval
            logger.error(f"Task '{task.name}' failed: {e}")

    def get_status(self) -> list:
        """Get status of all registered tasks."""
        result = []
        for name, task in self._tasks.items():
            result.append({
                "name": name,
                "enabled": task.enabled,
                "interval_seconds": task.interval_seconds,
                "run_count": task.run_count,
                "error_count": task.error_count,
                "last_run": datetime.fromtimestamp(task.last_run, tz=timezone.utc).isoformat() if task.last_run else None,
                "last_duration_ms": round(task.last_duration * 1000, 1),
                "last_error": task.last_error,
                "one_shot": task.one_shot,
            })
        return result

    @property
    def is_running(self) -> bool:
        return self._running


# Singleton instance
task_scheduler = TaskScheduler()
