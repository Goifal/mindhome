"""
Task Registry - Zentrales Tracking aller asyncio Background-Tasks.

Verhindert Fire-and-Forget Leaks: Alle Tasks werden registriert,
ueberwacht und beim Shutdown sauber beendet.
"""

import asyncio
import logging
import time
from typing import Callable, Coroutine, Optional

logger = logging.getLogger(__name__)


class TaskRegistry:
    """Verwaltet alle Background-Tasks des Assistants."""

    # Maximale Anzahl gleichzeitig aktiver Tasks — verhindert Resource-Exhaustion
    MAX_ACTIVE_TASKS = 200

    # Watchdog: Max Restarts bevor aufgegeben wird
    _MAX_RESTARTS = 5
    _RESTART_BACKOFF_BASE = 2.0  # Sekunden

    def __init__(self):
        self._tasks: dict[str, asyncio.Task] = {}
        self._shutting_down = False
        # Watchdog: Factories fuer persistente Tasks (auto-restart bei Crash)
        self._persistent: dict[str, Callable[[], Coroutine]] = {}
        self._restart_counts: dict[str, int] = {}
        self._last_restart: dict[str, float] = {}

    def create_task(
        self,
        coro: Coroutine,
        *,
        name: str,
        replace: bool = False,
    ) -> asyncio.Task:
        """Erstellt und registriert einen neuen Task mit Error-Logging.

        Args:
            coro: Die auszufuehrende Coroutine
            name: Eindeutiger Name fuer den Task
            replace: Wenn True, wird ein bestehender Task mit gleichem Namen gecancelt
        """
        if self._shutting_down:
            logger.warning("Task '%s' abgelehnt — Shutdown laeuft", name)
            coro.close()
            raise RuntimeError("TaskRegistry is shutting down")

        # Bestehenden Task ersetzen?
        if name in self._tasks:
            existing = self._tasks[name]
            if not existing.done():
                if replace:
                    existing.cancel()
                    logger.debug("Task '%s' ersetzt", name)
                else:
                    logger.debug("Task '%s' laeuft bereits — uebersprungen", name)
                    coro.close()
                    return existing

        # Backpressure: abgeschlossene Tasks aufraeumen und Limit pruefen
        self._cleanup_done_tasks()
        active_count = sum(1 for t in self._tasks.values() if not t.done())
        if active_count >= self.MAX_ACTIVE_TASKS:
            logger.warning(
                "TaskRegistry Backpressure: %d aktive Tasks (Limit %d) — "
                "Task '%s' abgelehnt",
                active_count,
                self.MAX_ACTIVE_TASKS,
                name,
            )
            coro.close()
            raise RuntimeError(
                f"TaskRegistry limit reached ({active_count}/{self.MAX_ACTIVE_TASKS})"
            )

        task = asyncio.create_task(coro, name=name)
        self._tasks[name] = task
        task.add_done_callback(lambda t: self._on_task_done(t, name))
        return task

    def create_persistent_task(
        self,
        factory: Callable[[], Coroutine],
        *,
        name: str,
    ) -> asyncio.Task:
        """Erstellt einen persistenten Task der bei Crash automatisch neustartet.

        Anders als create_task: Erhaelt eine Factory-Funktion (keine Coroutine),
        damit bei jedem Restart eine frische Coroutine erzeugt werden kann.

        Args:
            factory: Parameterlose Funktion die eine Coroutine zurueckgibt
            name: Eindeutiger Task-Name
        """
        self._persistent[name] = factory
        self._restart_counts[name] = 0
        return self.create_task(factory(), name=name, replace=True)

    def _on_task_done(self, task: asyncio.Task, name: str) -> None:
        """Callback wenn ein Task endet — loggt Fehler, restartet persistente Tasks."""
        if task.cancelled():
            logger.debug("Task '%s' wurde abgebrochen", name)
            return

        exc = task.exception()
        if exc:
            logger.error(
                "Background-Task '%s' fehlgeschlagen: %s",
                name,
                exc,
                exc_info=exc,
            )
            # Watchdog: Persistente Tasks automatisch neustarten
            if name in self._persistent and not self._shutting_down:
                self._restart_counts[name] = self._restart_counts.get(name, 0) + 1
                count = self._restart_counts[name]
                if count <= self._MAX_RESTARTS:
                    backoff = self._RESTART_BACKOFF_BASE ** min(count, 5)
                    logger.warning(
                        "Watchdog: Task '%s' wird in %.0fs neugestartet "
                        "(Versuch %d/%d)",
                        name,
                        backoff,
                        count,
                        self._MAX_RESTARTS,
                    )
                    # Reset Zaehler wenn letzter Restart >5min her (transient error)
                    last = self._last_restart.get(name, 0)
                    if time.monotonic() - last > 300:
                        self._restart_counts[name] = 1
                        count = 1
                        backoff = self._RESTART_BACKOFF_BASE
                    self._last_restart[name] = time.monotonic()
                    asyncio.get_event_loop().call_later(
                        backoff,
                        lambda n=name: asyncio.ensure_future(
                            self._restart_persistent(n)
                        ),
                    )
                else:
                    logger.error(
                        "Watchdog: Task '%s' hat %d Restarts erreicht — aufgegeben",
                        name,
                        self._MAX_RESTARTS,
                    )

    async def _restart_persistent(self, name: str) -> None:
        """Restartet einen persistenten Task."""
        factory = self._persistent.get(name)
        if not factory or self._shutting_down:
            return
        try:
            self.create_task(factory(), name=name, replace=True)
            logger.info("Watchdog: Task '%s' erfolgreich neugestartet", name)
        except Exception as e:
            logger.error("Watchdog: Restart von '%s' fehlgeschlagen: %s", name, e)

    def _cleanup_done_tasks(self) -> None:
        """Entfernt abgeschlossene Tasks aus dem Registry."""
        done_names = [n for n, t in self._tasks.items() if t.done()]
        for n in done_names:
            del self._tasks[n]

    def cancel(self, name: str) -> bool:
        """Bricht einen einzelnen Task ab."""
        task = self._tasks.get(name)
        if task and not task.done():
            task.cancel()
            return True
        return False

    def is_running(self, name: str) -> bool:
        """Prueft ob ein Task laeuft."""
        task = self._tasks.get(name)
        return task is not None and not task.done()

    @property
    def active_tasks(self) -> list[str]:
        """Liste aller aktiven Task-Namen."""
        return [name for name, task in self._tasks.items() if not task.done()]

    @property
    def task_count(self) -> int:
        """Anzahl aktiver Tasks."""
        return len(self.active_tasks)

    async def shutdown(self, timeout: float = 10.0) -> None:
        """Beendet alle Tasks graceful.

        Args:
            timeout: Maximale Wartezeit in Sekunden
        """
        self._shutting_down = True
        active = [task for task in self._tasks.values() if not task.done()]

        if not active:
            logger.info("TaskRegistry: Keine aktiven Tasks zum Beenden")
            return

        logger.info("TaskRegistry: Beende %d aktive Tasks...", len(active))

        # Alle Tasks canceln
        for task in active:
            task.cancel()

        # Auf Beendigung warten (mit Timeout)
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*active, return_exceptions=True),
                timeout=timeout,  # T2: Shutdown-Timeout
            )
        except asyncio.TimeoutError:
            logger.warning(
                "T2: TaskRegistry shutdown timeout (%.0fs) — %d Tasks liefen noch",
                timeout,
                len(active),
            )
            results = [asyncio.TimeoutError()] * len(active)

        cancelled = sum(1 for r in results if isinstance(r, asyncio.CancelledError))
        errors = sum(
            1
            for r in results
            if isinstance(r, Exception) and not isinstance(r, asyncio.CancelledError)
        )

        logger.info(
            "TaskRegistry: %d Tasks beendet (%d cancelled, %d Fehler)",
            len(active),
            cancelled,
            errors,
        )

        self._tasks.clear()

    def status(self) -> dict:
        """Status fuer Diagnostik/Metrics."""
        active = []
        for name, task in self._tasks.items():
            active.append(
                {
                    "name": name,
                    "done": task.done(),
                    "cancelled": task.cancelled() if task.done() else False,
                }
            )
        return {
            "total_registered": len(self._tasks),
            "active": len([t for t in active if not t["done"]]),
            "tasks": active,
        }
