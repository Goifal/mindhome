"""
Timer Manager - Allgemeine Timer & Erinnerungen fuer den Jarvis-Assistenten.

Features:
- Software-Timer mit Label und optionaler Aktion bei Ablauf
- Mehrere Timer parallel
- Timer-Status abfragbar ("Wie lange noch?")
- Benachrichtigung via TTS im Raum + optional Push
- Optionale Aktion bei Ablauf (z.B. Licht ausschalten)

Basiert auf dem bewaehrten CookingTimer-Pattern aus cooking_assistant.py,
aber generalisiert fuer beliebige Anwendungsfaelle.
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Redis Keys
KEY_TIMERS = "mha:timers:active"


@dataclass
class GeneralTimer:
    """Ein allgemeiner Software-Timer."""
    id: str
    label: str
    duration_seconds: int
    room: str = ""
    person: str = ""
    started_at: float = 0.0
    finished: bool = False
    action_on_expire: Optional[dict] = None  # z.B. {"function": "set_light", "args": {"room": "kueche", "state": "off"}}

    def start(self):
        self.started_at = time.time()
        self.finished = False

    @property
    def remaining_seconds(self) -> int:
        if self.finished or self.started_at == 0:
            return 0
        elapsed = time.time() - self.started_at
        remaining = self.duration_seconds - elapsed
        return max(0, int(remaining))

    @property
    def is_done(self) -> bool:
        if self.finished:
            return True
        if self.started_at > 0 and self.remaining_seconds <= 0:
            self.finished = True
            return True
        return False

    def format_remaining(self) -> str:
        secs = self.remaining_seconds
        if secs <= 0:
            return "abgelaufen"
        hours = secs // 3600
        minutes = (secs % 3600) // 60
        seconds = secs % 60
        parts = []
        if hours > 0:
            parts.append(f"{hours} Stunde{'n' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} Minute{'n' if minutes > 1 else ''}")
        if seconds > 0 and hours == 0:
            parts.append(f"{seconds} Sekunde{'n' if seconds > 1 else ''}")
        return " und ".join(parts) if parts else "abgelaufen"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "duration_seconds": self.duration_seconds,
            "room": self.room,
            "person": self.person,
            "started_at": self.started_at,
            "finished": self.finished,
            "action_on_expire": self.action_on_expire,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GeneralTimer":
        return cls(
            id=data["id"],
            label=data["label"],
            duration_seconds=data["duration_seconds"],
            room=data.get("room", ""),
            person=data.get("person", ""),
            started_at=data.get("started_at", 0.0),
            finished=data.get("finished", False),
            action_on_expire=data.get("action_on_expire"),
        )


class TimerManager:
    """Verwaltet allgemeine Timer und Erinnerungen."""

    def __init__(self):
        self.timers: dict[str, GeneralTimer] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._notify_callback = None
        self._action_callback = None  # Fuer Aktionen bei Ablauf (FunctionExecutor)
        self.redis: Optional[aioredis.Redis] = None

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert den TimerManager."""
        self.redis = redis_client
        # Bestehende Timer aus Redis wiederherstellen
        if self.redis:
            await self._restore_timers()
        logger.info("TimerManager initialisiert (%d aktive Timer)", len(self.timers))

    def set_notify_callback(self, callback):
        """Setzt den Callback fuer Timer-Benachrichtigungen."""
        self._notify_callback = callback

    def set_action_callback(self, callback):
        """Setzt den Callback fuer Aktionen bei Timer-Ablauf."""
        self._action_callback = callback

    async def create_timer(
        self,
        duration_minutes: int,
        label: str = "",
        room: str = "",
        person: str = "",
        action_on_expire: Optional[dict] = None,
    ) -> dict:
        """Erstellt einen neuen Timer.

        Args:
            duration_minutes: Dauer in Minuten (1-1440)
            label: Bezeichnung (z.B. "Waesche", "Pizza")
            room: Raum fuer TTS-Benachrichtigung
            person: Person die den Timer erstellt hat
            action_on_expire: Optionale Aktion bei Ablauf

        Returns:
            Ergebnis-Dict mit success und message
        """
        if duration_minutes < 1 or duration_minutes > 1440:
            return {"success": False, "message": "Timer muss zwischen 1 und 1440 Minuten (24h) liegen."}

        timer_id = str(uuid.uuid4())[:8]
        if not label:
            label = f"Timer ({duration_minutes} Min)"

        timer = GeneralTimer(
            id=timer_id,
            label=label,
            duration_seconds=duration_minutes * 60,
            room=room,
            person=person,
            action_on_expire=action_on_expire,
        )
        timer.start()

        self.timers[timer_id] = timer
        await self._persist_timer(timer)

        # Hintergrund-Task fuer Benachrichtigung
        task = asyncio.create_task(self._timer_watcher(timer))
        self._tasks[timer_id] = task

        # Zeitformatierung
        if duration_minutes >= 60:
            hours = duration_minutes // 60
            mins = duration_minutes % 60
            time_str = f"{hours} Stunde{'n' if hours > 1 else ''}"
            if mins > 0:
                time_str += f" und {mins} Minute{'n' if mins > 1 else ''}"
        else:
            time_str = f"{duration_minutes} Minute{'n' if duration_minutes > 1 else ''}"

        action_hint = ""
        if action_on_expire:
            action_hint = " Ich fuehre die gewuenschte Aktion dann aus."

        return {
            "success": True,
            "message": f"Timer '{label}' gesetzt: {time_str}.{action_hint}",
            "timer_id": timer_id,
        }

    async def cancel_timer(self, timer_id: str = "", label: str = "") -> dict:
        """Bricht einen Timer ab.

        Kann per ID oder Label gesucht werden.
        """
        target = None

        if timer_id and timer_id in self.timers:
            target = self.timers[timer_id]
        elif label:
            label_lower = label.lower()
            for t in self.timers.values():
                if label_lower in t.label.lower() and not t.is_done:
                    target = t
                    break

        if not target:
            return {"success": False, "message": "Timer nicht gefunden."}

        # Task canceln
        task = self._tasks.pop(target.id, None)
        if task:
            task.cancel()

        target.finished = True
        del self.timers[target.id]
        await self._remove_timer(target.id)

        return {"success": True, "message": f"Timer '{target.label}' abgebrochen."}

    def get_status(self) -> dict:
        """Gibt den Status aller Timer zurueck."""
        active = []
        done = []

        for timer in self.timers.values():
            if timer.is_done:
                done.append(timer)
            else:
                active.append(timer)

        if not active and not done:
            return {"success": True, "message": "Keine Timer aktiv."}

        parts = []
        if active:
            parts.append("Aktive Timer:")
            for t in active:
                parts.append(f"  - {t.label}: noch {t.format_remaining()}")
        if done:
            parts.append("Abgelaufene Timer:")
            for t in done:
                parts.append(f"  - {t.label}: abgelaufen")

        return {"success": True, "message": "\n".join(parts), "active_count": len(active)}

    def get_context_hints(self) -> list[str]:
        """Liefert Timer-Hinweise fuer den System-Prompt Kontext."""
        hints = []
        for timer in self.timers.values():
            if not timer.is_done:
                hints.append(f"Timer '{timer.label}': noch {timer.format_remaining()}")
        return hints

    async def _timer_watcher(self, timer: GeneralTimer):
        """Ueberwacht einen Timer und benachrichtigt bei Ablauf."""
        try:
            remaining = timer.remaining_seconds
            if remaining > 0:
                await asyncio.sleep(remaining)

            timer.finished = True
            logger.info("Timer abgelaufen: %s (ID: %s)", timer.label, timer.id)

            # Benachrichtigung senden
            message = f"Sir, der Timer fuer '{timer.label}' ist abgelaufen!"
            if self._notify_callback:
                await self._notify_callback({
                    "message": message,
                    "type": "timer_expired",
                    "room": timer.room,
                    "timer_id": timer.id,
                })

            # Optionale Aktion ausfuehren
            if timer.action_on_expire and self._action_callback:
                action = timer.action_on_expire
                func_name = action.get("function", "")
                func_args = action.get("args", {})
                if func_name:
                    logger.info("Timer-Aktion ausfuehren: %s(%s)", func_name, func_args)
                    result = await self._action_callback(func_name, func_args)
                    action_msg = f"Timer-Aktion '{func_name}' ausgefuehrt."
                    if self._notify_callback:
                        await self._notify_callback({
                            "message": action_msg,
                            "type": "timer_action",
                            "room": timer.room,
                        })

            # Aufraumen
            self._tasks.pop(timer.id, None)
            await self._remove_timer(timer.id)
            # Timer im Dict behalten fuer Status-Abfrage, aber nach 5 Min entfernen
            asyncio.get_event_loop().call_later(300, lambda: self.timers.pop(timer.id, None))

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Timer-Watcher Fehler fuer '%s': %s", timer.label, e)

    async def _persist_timer(self, timer: GeneralTimer):
        """Speichert Timer in Redis fuer Persistenz."""
        if not self.redis:
            return
        try:
            await self.redis.hset(KEY_TIMERS, timer.id, json.dumps(timer.to_dict()))
        except Exception as e:
            logger.debug("Timer-Persistenz fehlgeschlagen: %s", e)

    async def _remove_timer(self, timer_id: str):
        """Entfernt Timer aus Redis."""
        if not self.redis:
            return
        try:
            await self.redis.hdel(KEY_TIMERS, timer_id)
        except Exception:
            pass

    async def _restore_timers(self):
        """Stellt Timer aus Redis nach Neustart wieder her."""
        if not self.redis:
            return
        try:
            raw = await self.redis.hgetall(KEY_TIMERS)
            if not raw:
                return

            for timer_id, data in raw.items():
                if isinstance(timer_id, bytes):
                    timer_id = timer_id.decode()
                if isinstance(data, bytes):
                    data = data.decode()

                timer = GeneralTimer.from_dict(json.loads(data))

                # Pruefen ob Timer noch laeuft
                if timer.remaining_seconds > 0 and not timer.finished:
                    self.timers[timer.id] = timer
                    task = asyncio.create_task(self._timer_watcher(timer))
                    self._tasks[timer.id] = task
                    logger.info("Timer wiederhergestellt: '%s' (noch %s)",
                                timer.label, timer.format_remaining())
                else:
                    # Abgelaufener Timer entfernen
                    await self._remove_timer(timer.id)
        except Exception as e:
            logger.warning("Timer-Wiederherstellung fehlgeschlagen: %s", e)
