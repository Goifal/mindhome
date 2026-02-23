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
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import redis.asyncio as aioredis

# F-051: Timezone-aware datetimes fuer korrekte Wecker/Erinnerungen bei DST-Wechsel
_TZ = ZoneInfo("Europe/Berlin")


def _now() -> datetime:
    """Timezone-aware datetime.now() fuer Europe/Berlin."""
    return datetime.now(_TZ)

logger = logging.getLogger(__name__)

# F-003: Whitelist fuer erlaubte Timer-Aktionen bei Ablauf
# Sicherheitsrelevante Aktionen (lock_door, arm_security_system, etc.) sind NICHT erlaubt
TIMER_ACTION_WHITELIST = frozenset({
    "set_light", "set_climate", "set_cover",
    "play_media", "pause_media", "stop_media",
    "send_message", "send_message_to_person",
    "set_volume",
})

# Redis Keys
KEY_TIMERS = "mha:timers:active"
KEY_REMINDERS = "mha:reminders:active"
KEY_ALARMS = "mha:alarms:active"


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
    def remaining_seconds(self) -> float:
        """Verbleibende Sekunden als Float (Praezision fuer Sleep)."""
        if self.finished or self.started_at == 0:
            return 0.0
        elapsed = time.time() - self.started_at
        remaining = self.duration_seconds - elapsed
        return max(0.0, remaining)

    @property
    def remaining_seconds_display(self) -> int:
        """Gerundete verbleibende Sekunden fuer Anzeige."""
        return int(self.remaining_seconds + 0.5)

    @property
    def is_done(self) -> bool:
        if self.finished:
            return True
        return self.started_at > 0 and self.remaining_seconds <= 0

    def format_remaining(self) -> str:
        secs = self.remaining_seconds_display
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
        """Initialisiert den TimerManager (Timer, Erinnerungen, Wecker)."""
        self.redis = redis_client
        # Bestehende Timer, Erinnerungen und Wecker aus Redis wiederherstellen
        if self.redis:
            await self._restore_timers()
            await self._restore_reminders()
            await self._restore_alarms()
        logger.info("TimerManager initialisiert (%d aktive Timer/Erinnerungen/Wecker)", len(self.timers))

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

        # Task canceln und auf Abschluss warten
        task = self._tasks.pop(target.id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        target.finished = True
        self.timers.pop(target.id, None)
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
                # F-003: Nur Whitelist-Aktionen erlauben
                if func_name and func_name not in TIMER_ACTION_WHITELIST:
                    logger.warning(
                        "Timer-Aktion blockiert (nicht in Whitelist): %s(%s) — Timer: %s",
                        func_name, func_args, timer.label,
                    )
                    if self._notify_callback:
                        await self._notify_callback({
                            "message": f"Timer-Aktion '{func_name}' blockiert (nicht erlaubt).",
                            "type": "timer_action_blocked",
                            "room": timer.room,
                        })
                elif func_name:
                    logger.info("Timer-Aktion ausfuehren: %s(%s)", func_name, func_args)
                    try:
                        result = await self._action_callback(func_name, func_args)
                    except Exception as action_err:
                        logger.error("Timer-Aktion fehlgeschlagen: %s", action_err)
                        result = None
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
            asyncio.get_running_loop().call_later(
                300, lambda tid=timer.id: self.timers.pop(tid, None)
            )

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
        except Exception as e:
            logger.debug("Timer Redis-Cleanup fehlgeschlagen: %s", e)

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

                # Pruefen ob Timer noch laeuft (remaining_seconds ist jetzt float)
                if timer.remaining_seconds > 0.0 and not timer.finished:
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

    # ==================================================================
    # Erinnerungen (absolute Uhrzeit)
    # ==================================================================

    async def create_reminder(
        self,
        time_str: str,
        label: str,
        date_str: str = "",
        room: str = "",
        person: str = "",
    ) -> dict:
        """Erstellt eine Erinnerung fuer einen absoluten Zeitpunkt.

        Args:
            time_str: Uhrzeit im Format "HH:MM" (z.B. "15:00")
            label: Woran erinnert werden soll
            date_str: Datum im Format "YYYY-MM-DD" (leer = heute/morgen automatisch)
            room: Raum fuer TTS-Benachrichtigung
            person: Person die die Erinnerung erstellt hat

        Returns:
            Ergebnis-Dict mit success und message
        """
        try:
            now = _now()

            # Zielzeit parsen
            target_time = datetime.strptime(time_str, "%H:%M")
            if date_str:
                target_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=_TZ)
            else:
                target_date = now

            target = target_date.replace(
                hour=target_time.hour,
                minute=target_time.minute,
                second=0,
                microsecond=0,
            )

            # Wenn Zeitpunkt heute schon vorbei ist → morgen
            if target <= now and not date_str:
                target += timedelta(days=1)

            seconds_until = (target - now).total_seconds()
            if seconds_until <= 0:
                return {"success": False, "message": "Der Zeitpunkt liegt in der Vergangenheit."}
            if seconds_until > 7 * 86400:
                return {"success": False, "message": "Erinnerungen koennen maximal 7 Tage in der Zukunft liegen."}

        except ValueError:
            return {"success": False, "message": f"Ungueltige Uhrzeit: {time_str}. Format: HH:MM"}

        reminder_id = str(uuid.uuid4())[:8]
        timer = GeneralTimer(
            id=reminder_id,
            label=label,
            duration_seconds=int(seconds_until),
            room=room,
            person=person,
            started_at=time.time(),
        )

        self.timers[reminder_id] = timer
        await self._persist_reminder(reminder_id, timer, target)

        # Watcher-Task starten
        task = asyncio.create_task(self._reminder_watcher(timer, target))
        self._tasks[reminder_id] = task

        # Menschenlesbare Zeitangabe
        day_str = ""
        if target.date() == now.date():
            day_str = "heute"
        elif target.date() == (now + timedelta(days=1)).date():
            day_str = "morgen"
        else:
            day_str = target.strftime("%d.%m.%Y")

        return {
            "success": True,
            "message": f"Erinnerung gesetzt: '{label}' {day_str} um {time_str} Uhr.",
            "reminder_id": reminder_id,
        }

    async def _reminder_watcher(self, timer: GeneralTimer, target: datetime):
        """Wartet bis zum Erinnerungs-Zeitpunkt und benachrichtigt."""
        try:
            seconds_until = (target - _now()).total_seconds()
            if seconds_until > 0:
                await asyncio.sleep(seconds_until)

            timer.finished = True
            logger.info("Erinnerung ausgeloest: %s (ID: %s)", timer.label, timer.id)

            if self._notify_callback:
                await self._notify_callback({
                    "message": f"Sir, Erinnerung: {timer.label}",
                    "type": "reminder",
                    "room": timer.room,
                    "timer_id": timer.id,
                })

            # Aufraumen
            self._tasks.pop(timer.id, None)
            await self._remove_reminder(timer.id)
            asyncio.get_running_loop().call_later(
                300, lambda tid=timer.id: self.timers.pop(tid, None)
            )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Reminder-Watcher Fehler fuer '%s': %s", timer.label, e)

    async def _persist_reminder(self, reminder_id: str, timer: GeneralTimer, target: datetime):
        """Speichert Erinnerung in Redis."""
        if not self.redis:
            return
        try:
            data = timer.to_dict()
            data["target_iso"] = target.isoformat()
            await self.redis.hset(KEY_REMINDERS, reminder_id, json.dumps(data))
        except Exception as e:
            logger.debug("Reminder-Persistenz fehlgeschlagen: %s", e)

    async def _remove_reminder(self, reminder_id: str):
        """Entfernt Erinnerung aus Redis."""
        if not self.redis:
            return
        try:
            await self.redis.hdel(KEY_REMINDERS, reminder_id)
        except Exception as e:
            logger.debug("Reminder Redis-Cleanup fehlgeschlagen: %s", e)

    async def _restore_reminders(self):
        """Stellt Erinnerungen aus Redis nach Neustart wieder her."""
        if not self.redis:
            return
        try:
            raw = await self.redis.hgetall(KEY_REMINDERS)
            if not raw:
                return
            for rid, data in raw.items():
                if isinstance(rid, bytes):
                    rid = rid.decode()
                if isinstance(data, bytes):
                    data = data.decode()

                info = json.loads(data)
                target = datetime.fromisoformat(info["target_iso"])
                if target.tzinfo is None:
                    target = target.replace(tzinfo=_TZ)

                if target > _now():
                    timer = GeneralTimer.from_dict(info)
                    self.timers[timer.id] = timer
                    task = asyncio.create_task(self._reminder_watcher(timer, target))
                    self._tasks[timer.id] = task
                    logger.info("Erinnerung wiederhergestellt: '%s' um %s",
                                timer.label, target.strftime("%H:%M"))
                else:
                    await self._remove_reminder(rid)
        except Exception as e:
            logger.warning("Reminder-Wiederherstellung fehlgeschlagen: %s", e)

    def get_reminders_status(self) -> dict:
        """Gibt den Status aller Erinnerungen zurueck (nur aktive Reminder)."""
        # Erinnerungen sind auch in self.timers, aber wir filtern per Redis-Key
        active = [t for t in self.timers.values() if not t.is_done]
        if not active:
            return {"success": True, "message": "Keine aktiven Erinnerungen."}
        parts = ["Aktive Erinnerungen:"]
        for t in active:
            parts.append(f"  - {t.label}: in {t.format_remaining()}")
        return {"success": True, "message": "\n".join(parts)}

    # ==================================================================
    # Wecker (Wake-Up Alarm)
    # ==================================================================

    async def set_wakeup_alarm(
        self,
        time_str: str,
        label: str = "Wecker",
        room: str = "",
        repeat: str = "",
    ) -> dict:
        """Setzt einen Wecker fuer eine bestimmte Uhrzeit.

        Args:
            time_str: Uhrzeit im Format "HH:MM" (z.B. "06:30")
            label: Bezeichnung (Standard: "Wecker")
            room: Raum fuer TTS/Licht-Wecken
            repeat: Wiederholungs-Modus: "" (einmalig), "daily", "weekdays", "weekends"

        Returns:
            Ergebnis-Dict mit success und message
        """
        try:
            now = _now()
            target_time = datetime.strptime(time_str, "%H:%M")
            target = now.replace(
                hour=target_time.hour,
                minute=target_time.minute,
                second=0,
                microsecond=0,
            )

            # Wenn heute schon vorbei → morgen
            if target <= now:
                target += timedelta(days=1)

            # Bei weekdays/weekends ggf. weiter springen
            if repeat == "weekdays":
                while target.weekday() >= 5:  # Sa=5, So=6
                    target += timedelta(days=1)
            elif repeat == "weekends":
                while target.weekday() < 5:
                    target += timedelta(days=1)

            seconds_until = (target - now).total_seconds()
            if seconds_until <= 0:
                return {"success": False, "message": "Zeitpunkt liegt in der Vergangenheit."}

        except ValueError:
            return {"success": False, "message": f"Ungueltige Uhrzeit: {time_str}. Format: HH:MM"}

        alarm_id = str(uuid.uuid4())[:8]
        alarm_data = {
            "id": alarm_id,
            "time": time_str,
            "label": label,
            "room": room,
            "repeat": repeat,
            "active": True,
            "created_at": now.isoformat(),
            "next_trigger": target.isoformat(),
        }

        # Alarm in Redis speichern
        if self.redis:
            try:
                await self.redis.hset(KEY_ALARMS, alarm_id, json.dumps(alarm_data))
            except Exception as e:
                logger.debug("Wecker-Persistenz fehlgeschlagen: %s", e)

        # Timer erstellen fuer naechstes Klingeln
        timer = GeneralTimer(
            id=alarm_id,
            label=label,
            duration_seconds=int(seconds_until),
            room=room,
            started_at=time.time(),
        )
        self.timers[alarm_id] = timer
        task = asyncio.create_task(self._alarm_watcher(alarm_id, alarm_data))
        self._tasks[alarm_id] = task

        repeat_text = {
            "daily": " (taeglich)",
            "weekdays": " (Mo-Fr)",
            "weekends": " (Sa-So)",
        }.get(repeat, "")

        day_str = "morgen" if target.date() > now.date() else "heute"
        return {
            "success": True,
            "message": f"Wecker gestellt: {day_str} um {time_str} Uhr{repeat_text}.",
            "alarm_id": alarm_id,
        }

    async def cancel_alarm(self, alarm_id: str = "", label: str = "") -> dict:
        """Loescht einen Wecker.

        Wenn weder alarm_id noch label angegeben und nur ein Wecker aktiv ist,
        wird dieser geloescht.
        """
        target_id = alarm_id

        if not target_id and label:
            # Per Label in Redis suchen
            if self.redis:
                try:
                    raw = await self.redis.hgetall(KEY_ALARMS)
                    for aid, data in (raw or {}).items():
                        if isinstance(aid, bytes):
                            aid = aid.decode()
                        if isinstance(data, bytes):
                            data = data.decode()
                        info = json.loads(data)
                        if label.lower() in info.get("label", "").lower() and info.get("active"):
                            target_id = aid
                            break
                except Exception:
                    pass

            # Fallback: In-Memory suchen (falls Redis unavailable)
            if not target_id:
                label_lower = label.lower()
                for tid, timer in self.timers.items():
                    if label_lower in timer.label.lower() and not timer.is_done:
                        target_id = tid
                        break

        # Kein Label/ID angegeben: Wenn nur ein aktiver Wecker existiert, diesen loeschen
        if not target_id and not label:
            active_alarms = []
            if self.redis:
                try:
                    raw = await self.redis.hgetall(KEY_ALARMS)
                    for aid, data in (raw or {}).items():
                        if isinstance(aid, bytes):
                            aid = aid.decode()
                        if isinstance(data, bytes):
                            data = data.decode()
                        info = json.loads(data)
                        if info.get("active"):
                            active_alarms.append(aid)
                except Exception:
                    pass
            if len(active_alarms) == 1:
                target_id = active_alarms[0]
            elif len(active_alarms) > 1:
                return {"success": False, "message": "Mehrere Wecker aktiv. Bitte angeben welcher geloescht werden soll."}

        if not target_id:
            return {"success": False, "message": "Wecker nicht gefunden."}

        # Task canceln
        task = self._tasks.pop(target_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self.timers.pop(target_id, None)

        # Aus Redis entfernen
        if self.redis:
            try:
                await self.redis.hdel(KEY_ALARMS, target_id)
            except Exception:
                pass

        return {"success": True, "message": "Wecker geloescht."}

    async def get_alarms(self) -> dict:
        """Gibt alle aktiven Wecker zurueck."""
        if not self.redis:
            return {"success": True, "message": "Keine Wecker gesetzt."}

        try:
            raw = await self.redis.hgetall(KEY_ALARMS)
            if not raw:
                return {"success": True, "message": "Keine Wecker gesetzt."}

            alarms = []
            for aid, data in raw.items():
                if isinstance(data, bytes):
                    data = data.decode()
                info = json.loads(data)
                if info.get("active"):
                    repeat_text = {
                        "daily": "taeglich",
                        "weekdays": "Mo-Fr",
                        "weekends": "Sa-So",
                    }.get(info.get("repeat", ""), "einmalig")
                    alarms.append(f"  - {info['label']}: {info['time']} Uhr ({repeat_text})")

            if not alarms:
                return {"success": True, "message": "Keine Wecker gesetzt."}

            return {"success": True, "message": "Aktive Wecker:\n" + "\n".join(alarms)}
        except Exception as e:
            logger.debug("Wecker-Status Fehler: %s", e)
            return {"success": True, "message": "Keine Wecker gesetzt."}

    async def _alarm_watcher(self, alarm_id: str, alarm_data: dict):
        """Wartet bis zur Weckzeit, benachrichtigt, und plant ggf. Wiederholung."""
        try:
            target = datetime.fromisoformat(alarm_data["next_trigger"])
            if target.tzinfo is None:
                target = target.replace(tzinfo=_TZ)
            seconds_until = (target - _now()).total_seconds()
            if seconds_until > 0:
                await asyncio.sleep(seconds_until)

            logger.info("Wecker klingelt: %s um %s", alarm_data["label"], alarm_data["time"])

            # Benachrichtigung senden
            if self._notify_callback:
                await self._notify_callback({
                    "message": f"Guten Morgen Sir! Wecker: {alarm_data['label']} — es ist {alarm_data['time']} Uhr.",
                    "type": "wakeup_alarm",
                    "room": alarm_data.get("room", ""),
                    "alarm_id": alarm_id,
                })

            self._tasks.pop(alarm_id, None)
            self.timers.pop(alarm_id, None)

            # Wiederholung planen
            repeat = alarm_data.get("repeat", "")
            if repeat:
                await self._schedule_next_alarm(alarm_id, alarm_data)
            else:
                # Einmaliger Wecker — aus Redis entfernen
                if self.redis:
                    await self.redis.hdel(KEY_ALARMS, alarm_id)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Wecker-Watcher Fehler: %s", e)

    async def _schedule_next_alarm(self, alarm_id: str, alarm_data: dict):
        """Plant den naechsten Wecker-Termin fuer wiederkehrende Wecker."""
        try:
            now = _now()
            target_time = datetime.strptime(alarm_data["time"], "%H:%M")
            next_target = now.replace(
                hour=target_time.hour,
                minute=target_time.minute,
                second=0,
                microsecond=0,
            ) + timedelta(days=1)

            repeat = alarm_data.get("repeat", "daily")
            if repeat == "weekdays":
                while next_target.weekday() >= 5:
                    next_target += timedelta(days=1)
            elif repeat == "weekends":
                while next_target.weekday() < 5:
                    next_target += timedelta(days=1)

            alarm_data["next_trigger"] = next_target.isoformat()

            # Redis aktualisieren
            if self.redis:
                await self.redis.hset(KEY_ALARMS, alarm_id, json.dumps(alarm_data))

            # Neuen Timer + Task erstellen
            seconds_until = (next_target - now).total_seconds()
            timer = GeneralTimer(
                id=alarm_id,
                label=alarm_data["label"],
                duration_seconds=int(seconds_until),
                room=alarm_data.get("room", ""),
                started_at=time.time(),
            )
            self.timers[alarm_id] = timer
            task = asyncio.create_task(self._alarm_watcher(alarm_id, alarm_data))
            self._tasks[alarm_id] = task

            logger.info("Naechster Wecker: %s um %s", alarm_data["label"],
                        next_target.strftime("%d.%m. %H:%M"))
        except Exception as e:
            logger.error("Wecker-Wiederholung fehlgeschlagen: %s", e)

    async def _restore_alarms(self):
        """Stellt Wecker aus Redis nach Neustart wieder her."""
        if not self.redis:
            return
        try:
            raw = await self.redis.hgetall(KEY_ALARMS)
            if not raw:
                return
            for aid, data in raw.items():
                if isinstance(aid, bytes):
                    aid = aid.decode()
                if isinstance(data, bytes):
                    data = data.decode()

                alarm_data = json.loads(data)
                if not alarm_data.get("active", True):
                    continue

                target = datetime.fromisoformat(alarm_data["next_trigger"])
            if target.tzinfo is None:
                target = target.replace(tzinfo=_TZ)

                if target > _now():
                    # Noch in der Zukunft → Task starten
                    seconds_until = (target - _now()).total_seconds()
                    timer = GeneralTimer(
                        id=aid,
                        label=alarm_data["label"],
                        duration_seconds=int(seconds_until),
                        room=alarm_data.get("room", ""),
                        started_at=time.time(),
                    )
                    self.timers[aid] = timer
                    task = asyncio.create_task(self._alarm_watcher(aid, alarm_data))
                    self._tasks[aid] = task
                    logger.info("Wecker wiederhergestellt: '%s' um %s",
                                alarm_data["label"], alarm_data["time"])
                elif alarm_data.get("repeat"):
                    # Vergangener wiederkehrender Wecker → naechsten planen
                    await self._schedule_next_alarm(aid, alarm_data)
                else:
                    # Vergangener einmaliger Wecker → entfernen
                    await self.redis.hdel(KEY_ALARMS, aid)
        except Exception as e:
            logger.warning("Wecker-Wiederherstellung fehlgeschlagen: %s", e)
