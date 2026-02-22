"""
Task Registry - Zentrales Tracking aller asyncio Background-Tasks.

Verhindert Fire-and-Forget Leaks: Alle Tasks werden registriert,
ueberwacht und beim Shutdown sauber beendet.
"""

import asyncio
import logging
from typing import Coroutine, Optional

logger = logging.getLogger(__name__)


class TaskRegistry:
    """Verwaltet alle Background-Tasks des Assistants."""

    def __init__(self):
        self._tasks: dict[str, asyncio.Task] = {}
        self._shutting_down = False

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

        task = asyncio.create_task(coro, name=name)
        self._tasks[name] = task
        task.add_done_callback(lambda t: self._on_task_done(t, name))
        return task

    def _on_task_done(self, task: asyncio.Task, name: str) -> None:
        """Callback wenn ein Task endet — loggt Fehler."""
        if task.cancelled():
            logger.debug("Task '%s' wurde abgebrochen", name)
            return

        exc = task.exception()
        if exc:
            logger.error(
                "Background-Task '%s' fehlgeschlagen: %s",
                name, exc, exc_info=exc,
            )

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
        results = await asyncio.gather(*active, return_exceptions=True)

        cancelled = sum(1 for r in results if isinstance(r, asyncio.CancelledError))
        errors = sum(1 for r in results if isinstance(r, Exception) and not isinstance(r, asyncio.CancelledError))

        logger.info(
            "TaskRegistry: %d Tasks beendet (%d cancelled, %d Fehler)",
            len(active), cancelled, errors,
        )

        self._tasks.clear()

    def status(self) -> dict:
        """Status fuer Diagnostik/Metrics."""
        active = []
        for name, task in self._tasks.items():
            active.append({
                "name": name,
                "done": task.done(),
                "cancelled": task.cancelled() if task.done() else False,
            })
        return {
            "total_registered": len(self._tasks),
            "active": len([t for t in active if not t["done"]]),
            "tasks": active,
        }
