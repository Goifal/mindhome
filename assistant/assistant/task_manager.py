"""
Task Manager - Aufgabenverwaltung fuer die ganze Familie.

Nutzt Home Assistants todo-Domain fuer persistente Aufgabenlisten.
Unterstuetzt:
- Persoenliche und geteilte Aufgabenlisten
- Wiederkehrende Aufgaben (taeglich, woechentlich, monatlich)
- Aufgaben pro Person zuweisen
- Faelligkeitsdaten und Prioritaeten
- Proaktive Erinnerungen bei faelligen Aufgaben

Redis Keys:
- mha:tasks:recurring:{task_id}  - Wiederkehrende Aufgaben-Definitionen
- mha:tasks:assigned:{person}    - Aufgaben pro Person (Referenzen)
- mha:tasks:meta:{item_uid}      - Metadaten (Prioritaet, Faelligkeit, Person)
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config

logger = logging.getLogger(__name__)

# Konfiguration
_cfg = yaml_config.get("task_manager", {})
_DEFAULT_LIST = _cfg.get("default_list", "todo.einkaufsliste")
_FAMILY_LIST = _cfg.get("family_list", "todo.familie")
_RECURRING_CHECK_INTERVAL = _cfg.get("recurring_check_minutes", 60)

_RECURRENCE_TYPES = frozenset({"daily", "weekly", "monthly", "weekday"})
_PRIORITIES = frozenset({"low", "medium", "high", "urgent"})
_WEEKDAY_MAP = {
    "montag": 0,
    "dienstag": 1,
    "mittwoch": 2,
    "donnerstag": 3,
    "freitag": 4,
    "samstag": 5,
    "sonntag": 6,
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
    "mo": 0,
    "di": 1,
    "mi": 2,
    "do": 3,
    "fr": 4,
    "sa": 5,
    "so": 6,
}


class TaskManager:
    """Aufgabenverwaltung ueber Home Assistant todo-Domain + Redis-Metadaten."""

    def __init__(self, ha_client):
        self.ha = ha_client
        self.redis: Optional[aioredis.Redis] = None
        self._notify_callback = None
        self._recurring_task: Optional[asyncio.Task] = None

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis-Verbindung."""
        self.redis = redis_client
        # Starte recurring-Check Loop
        if self.redis:
            self._recurring_task = asyncio.create_task(self._recurring_loop())
            self._recurring_task.add_done_callback(
                lambda t: t.exception() if not t.cancelled() else None
            )
        logger.info("TaskManager initialisiert")

    def set_notify_callback(self, callback):
        """Setzt Callback fuer Aufgaben-Erinnerungen."""
        self._notify_callback = callback

    # ------------------------------------------------------------------
    # Oeffentliche API
    # ------------------------------------------------------------------

    async def add_task(
        self,
        title: str,
        person: str = "",
        due_date: str = "",
        priority: str = "medium",
        list_entity: str = "",
        description: str = "",
    ) -> dict:
        """Fuegt eine neue Aufgabe hinzu."""
        if not title or not title.strip():
            return {"success": False, "message": "Kein Aufgabentext angegeben."}

        title = title.strip()
        priority = priority.lower() if priority.lower() in _PRIORITIES else "medium"
        target_list = list_entity or (_FAMILY_LIST if not person else _DEFAULT_LIST)

        # HA todo.add_item Service aufrufen
        service_data = {"item": title}
        if due_date:
            service_data["due_date"] = due_date
        if description:
            service_data["description"] = description

        success = await self.ha.call_service(
            "todo",
            "add_item",
            service_data,
            target={"entity_id": target_list},
        )

        if not success:
            return {
                "success": False,
                "message": f"Konnte Aufgabe nicht hinzufuegen. Ist '{target_list}' verfuegbar?",
            }

        # Metadaten in Redis speichern
        if self.redis:
            meta_id = f"task_{uuid.uuid4().hex[:8]}"
            meta = {
                "title": title,
                "person": person.lower() if person else "",
                "priority": priority,
                "due_date": due_date,
                "list_entity": target_list,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            await self.redis.hset(f"mha:tasks:meta:{meta_id}", mapping=meta)
            await self.redis.expire(f"mha:tasks:meta:{meta_id}", 90 * 86400)  # 90 Tage

            if person:
                await self.redis.sadd(f"mha:tasks:assigned:{person.lower()}", meta_id)

        person_hint = f" (fuer {person})" if person else ""
        due_hint = f", faellig am {due_date}" if due_date else ""
        return {
            "success": True,
            "message": f"Aufgabe '{title}'{person_hint}{due_hint} hinzugefuegt.",
        }

    async def list_tasks(
        self,
        person: str = "",
        list_entity: str = "",
        status: str = "needs_action",
    ) -> dict:
        """Listet Aufgaben auf."""
        target_list = list_entity or _FAMILY_LIST

        # HA todo.get_items aufrufen
        items = await self._get_todo_items(target_list, status)
        if items is None:
            return {
                "success": False,
                "message": f"Todo-Liste '{target_list}' nicht verfuegbar.",
            }

        # Optional nach Person filtern (via Redis-Metadaten)
        if person and self.redis:
            assigned_ids = await self.redis.smembers(
                f"mha:tasks:assigned:{person.lower()}"
            )
            if assigned_ids:
                assigned_titles = set()
                pipe = self.redis.pipeline()
                for aid in assigned_ids:
                    aid_str = aid if isinstance(aid, str) else aid.decode()
                    pipe.hget(f"mha:tasks:meta:{aid_str}", "title")
                titles = await pipe.execute()
                for t in titles:
                    if t:
                        assigned_titles.add(t if isinstance(t, str) else t.decode())
                items = [i for i in items if i.get("summary", "") in assigned_titles]

        if not items:
            hint = f" fuer {person}" if person else ""
            return {
                "success": True,
                "message": f"Keine offenen Aufgaben{hint}. Alles erledigt!",
            }

        lines = []
        for i, item in enumerate(items, 1):
            summary = item.get("summary", "?")
            due = item.get("due", "")
            due_str = f" (faellig: {due})" if due else ""
            status_icon = "[ ]" if item.get("status") == "needs_action" else "[x]"
            lines.append(f"{i}. {status_icon} {summary}{due_str}")

        person_hint = f" fuer {person}" if person else ""
        return {
            "success": True,
            "message": f"Aufgaben{person_hint}:\n" + "\n".join(lines),
        }

    async def complete_task(self, title: str, list_entity: str = "") -> dict:
        """Markiert eine Aufgabe als erledigt."""
        if not title:
            return {"success": False, "message": "Kein Aufgabentext angegeben."}

        target_list = list_entity or _FAMILY_LIST

        success = await self.ha.call_service(
            "todo",
            "update_item",
            {"item": title, "status": "completed"},
            target={"entity_id": target_list},
        )

        if not success:
            return {
                "success": False,
                "message": f"Aufgabe '{title}' nicht gefunden oder nicht abschliessbar.",
            }

        return {"success": True, "message": f"Aufgabe '{title}' erledigt. Gut gemacht!"}

    async def remove_task(self, title: str, list_entity: str = "") -> dict:
        """Entfernt eine Aufgabe komplett."""
        if not title:
            return {"success": False, "message": "Kein Aufgabentext angegeben."}

        target_list = list_entity or _FAMILY_LIST

        success = await self.ha.call_service(
            "todo",
            "remove_item",
            {"item": title},
            target={"entity_id": target_list},
        )

        if not success:
            return {
                "success": False,
                "message": f"Aufgabe '{title}' nicht gefunden.",
            }

        return {"success": True, "message": f"Aufgabe '{title}' entfernt."}

    async def add_recurring_task(
        self,
        title: str,
        recurrence: str,
        weekday: str = "",
        person: str = "",
        list_entity: str = "",
    ) -> dict:
        """Erstellt eine wiederkehrende Aufgabe.

        Args:
            recurrence: daily, weekly, monthly, weekday
            weekday: Fuer weekly - z.B. 'montag', 'dienstag'
        """
        if not title:
            return {"success": False, "message": "Kein Aufgabentext angegeben."}

        recurrence = recurrence.lower()
        if recurrence not in _RECURRENCE_TYPES:
            return {
                "success": False,
                "message": f"Unbekannter Wiederholungstyp: {recurrence}. "
                f"Moeglich: {', '.join(sorted(_RECURRENCE_TYPES))}",
            }

        weekday_num = None
        if recurrence == "weekly":
            if not weekday:
                return {
                    "success": False,
                    "message": "Fuer woechentliche Aufgaben muss ein Wochentag angegeben werden.",
                }
            weekday_num = _WEEKDAY_MAP.get(weekday.lower())
            if weekday_num is None:
                return {
                    "success": False,
                    "message": f"Unbekannter Wochentag: {weekday}",
                }

        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar."}

        task_id = f"rec_{uuid.uuid4().hex[:8]}"
        rec_data = {
            "title": title,
            "recurrence": recurrence,
            "weekday": str(weekday_num) if weekday_num is not None else "",
            "person": person.lower() if person else "",
            "list_entity": list_entity or _FAMILY_LIST,
            "last_created": "",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        await self.redis.hset(f"mha:tasks:recurring:{task_id}", mapping=rec_data)
        await self.redis.sadd("mha:tasks:recurring:all", task_id)

        schedule_hint = {
            "daily": "jeden Tag",
            "weekly": f"jeden {weekday}" if weekday else "woechentlich",
            "monthly": "monatlich (am 1.)",
            "weekday": "Montag bis Freitag",
        }.get(recurrence, recurrence)

        return {
            "success": True,
            "message": f"Wiederkehrende Aufgabe '{title}' ({schedule_hint}) erstellt.",
        }

    async def list_recurring_tasks(self) -> dict:
        """Listet alle wiederkehrenden Aufgaben."""
        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar."}

        task_ids = await self.redis.smembers("mha:tasks:recurring:all")
        if not task_ids:
            return {
                "success": True,
                "message": "Keine wiederkehrenden Aufgaben konfiguriert.",
            }

        lines = []
        pipe = self.redis.pipeline()
        ids_list = []
        for tid in task_ids:
            tid_str = tid if isinstance(tid, str) else tid.decode()
            ids_list.append(tid_str)
            pipe.hgetall(f"mha:tasks:recurring:{tid_str}")
        results = await pipe.execute()

        for tid, data in zip(ids_list, results):
            if not data:
                continue
            title = (data.get("title") or data.get(b"title", b"")).strip()
            if isinstance(title, bytes):
                title = title.decode()
            recurrence = (
                data.get("recurrence") or data.get(b"recurrence", b"")
            ).strip()
            if isinstance(recurrence, bytes):
                recurrence = recurrence.decode()
            person = (data.get("person") or data.get(b"person", b"")).strip()
            if isinstance(person, bytes):
                person = person.decode()

            person_hint = f" [{person}]" if person else ""
            lines.append(f"- {title} ({recurrence}){person_hint}")

        if not lines:
            return {"success": True, "message": "Keine wiederkehrenden Aufgaben."}

        return {
            "success": True,
            "message": "Wiederkehrende Aufgaben:\n" + "\n".join(lines),
        }

    async def delete_recurring_task(self, title: str) -> dict:
        """Loescht eine wiederkehrende Aufgabe nach Titel."""
        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar."}

        task_ids = await self.redis.smembers("mha:tasks:recurring:all")
        for tid in task_ids:
            tid_str = tid if isinstance(tid, str) else tid.decode()
            stored_title = await self.redis.hget(
                f"mha:tasks:recurring:{tid_str}", "title"
            )
            if stored_title:
                if isinstance(stored_title, bytes):
                    stored_title = stored_title.decode()
                if stored_title.lower().strip() == title.lower().strip():
                    await self.redis.delete(f"mha:tasks:recurring:{tid_str}")
                    await self.redis.srem("mha:tasks:recurring:all", tid_str)
                    return {
                        "success": True,
                        "message": f"Wiederkehrende Aufgabe '{title}' geloescht.",
                    }

        return {
            "success": False,
            "message": f"Wiederkehrende Aufgabe '{title}' nicht gefunden.",
        }

    def get_context_hints(self) -> list[str]:
        """Gibt Kontext-Hints fuer den Context Builder zurueck."""
        return ["TaskManager aktiv: Aufgabenverwaltung ueber HA todo-Domain verfuegbar"]

    # ------------------------------------------------------------------
    # Interne Helfer
    # ------------------------------------------------------------------

    async def _get_todo_items(
        self, entity_id: str, status: str = "needs_action"
    ) -> Optional[list]:
        """Ruft Todo-Items von Home Assistant ab."""
        try:
            state = await self.ha.get_state(entity_id)
            if state is None:
                return None

            # HA todo entities haben Items als Attribute
            attrs = state.get("attributes", {})
            items = attrs.get("items", [])

            if status == "all":
                return items
            return [i for i in items if i.get("status") == status]
        except Exception as e:
            logger.warning(
                "Fehler beim Abrufen von todo-Items fuer %s: %s", entity_id, e
            )
            return None

    async def _recurring_loop(self):
        """Prueft periodisch ob wiederkehrende Aufgaben erstellt werden muessen."""
        while True:
            try:
                await asyncio.sleep(_RECURRING_CHECK_INTERVAL * 60)
                await self._process_recurring_tasks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Fehler in recurring task loop: %s", e)
                await asyncio.sleep(300)  # 5 Min Pause bei Fehler

    async def _process_recurring_tasks(self):
        """Erstellt faellige wiederkehrende Aufgaben."""
        if not self.redis:
            return

        task_ids = await self.redis.smembers("mha:tasks:recurring:all")
        if not task_ids:
            return

        now = datetime.now(timezone.utc)
        today_str = now.strftime("%Y-%m-%d")

        for tid in task_ids:
            tid_str = tid if isinstance(tid, str) else tid.decode()
            data = await self.redis.hgetall(f"mha:tasks:recurring:{tid_str}")
            if not data:
                continue

            # Decode Redis bytes
            decoded = {}
            for k, v in data.items():
                key = k if isinstance(k, str) else k.decode()
                val = v if isinstance(v, str) else v.decode()
                decoded[key] = val

            last_created = decoded.get("last_created", "")
            if last_created == today_str:
                continue  # Heute schon erstellt

            recurrence = decoded.get("recurrence", "")
            should_create = False

            if recurrence == "daily":
                should_create = True
            elif recurrence == "weekday":
                should_create = now.weekday() < 5  # Mo-Fr
            elif recurrence == "weekly":
                target_day = int(decoded.get("weekday", "-1"))
                should_create = now.weekday() == target_day
            elif recurrence == "monthly":
                should_create = now.day == 1

            if should_create:
                title = decoded.get("title", "")
                list_entity = decoded.get("list_entity", _FAMILY_LIST)

                service_data = {"item": title}
                success = await self.ha.call_service(
                    "todo",
                    "add_item",
                    service_data,
                    target={"entity_id": list_entity},
                )

                if success:
                    await self.redis.hset(
                        f"mha:tasks:recurring:{tid_str}",
                        "last_created",
                        today_str,
                    )
                    logger.info(
                        "Wiederkehrende Aufgabe erstellt: %s (%s)",
                        title,
                        recurrence,
                    )

    async def shutdown(self):
        """Beendet den recurring loop."""
        if self._recurring_task and not self._recurring_task.done():
            self._recurring_task.cancel()
            try:
                await self._recurring_task
            except asyncio.CancelledError:
                pass
