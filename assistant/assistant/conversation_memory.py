"""
Konversations-Gedaechtnis++ - Projekt-Tracker, offene Fragen, Zusammenfassungen.

Erweitert das bestehende Memory-System um:
- Projekt-Tracking: Laufende Projekte mit Meilensteinen und Status
- Offene Fragen: Unbeantwortete Fragen die spaeter nachverfolgt werden
- Tages-Zusammenfassungen: Kompakte Zusammenfassung der Gespraechsthemen

Nutzt Redis fuer persistente Speicherung.
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config

logger = logging.getLogger(__name__)

# Redis Keys
_KEY_PROJECTS = "mha:memory:projects"               # Hash: project_id -> JSON
_KEY_OPEN_QUESTIONS = "mha:memory:open_questions"    # Hash: question_id -> JSON
_KEY_DAILY_SUMMARY = "mha:memory:summary:"           # + YYYY-MM-DD -> JSON
_KEY_FOLLOWUPS = "mha:memory:followups"              # Hash: followup_id -> JSON
# Phase 3B: Gesprächs-Threads
_KEY_THREADS = "mha:memory:threads"                  # Hash: thread_id -> JSON
_KEY_THREAD_INDEX = "mha:memory:thread_index"        # Hash: keyword -> thread_id

# Defaults
_DEFAULT_MAX_PROJECTS = 20
_DEFAULT_MAX_QUESTIONS = 30
_DEFAULT_SUMMARY_RETENTION_DAYS = 0  # 0 = unbegrenzt
_DEFAULT_QUESTION_TTL_DAYS = 14


class ConversationMemory:
    """Erweitertes Konversationsgedaechtnis mit Projekt- und Fragen-Tracking."""

    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        cfg = yaml_config.get("conversation_memory", {})
        self.enabled = cfg.get("enabled", True)
        self.max_projects = cfg.get("max_projects", _DEFAULT_MAX_PROJECTS)
        self.max_questions = cfg.get("max_questions", _DEFAULT_MAX_QUESTIONS)
        self.summary_retention_days = cfg.get("summary_retention_days", _DEFAULT_SUMMARY_RETENTION_DAYS)
        self.question_ttl_days = cfg.get("question_ttl_days", _DEFAULT_QUESTION_TTL_DAYS)
        self._project_lock = asyncio.Lock()

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis-Verbindung."""
        self.redis = redis_client
        # Startup-Cleanup: Abgelaufene Eintraege entfernen
        if self.redis and self.enabled:
            await self._cleanup_expired_entries()
        logger.info("ConversationMemory initialisiert (enabled: %s)", self.enabled)

    async def _cleanup_expired_entries(self):
        """Entfernt beim Start abgelaufene Fragen, abgeschlossene Projekte und erledigte Followups."""
        try:
            await self._cleanup_old_questions()
            await self._cleanup_old_projects()
            await self._cleanup_old_followups()
        except Exception as e:
            logger.debug("ConversationMemory Startup-Cleanup fehlgeschlagen: %s", e)

    async def _cleanup_old_projects(self):
        """Entfernt abgeschlossene/abgebrochene Projekte die aelter als 30 Tage sind."""
        if not self.redis:
            return
        try:
            raw = await self.redis.hgetall(_KEY_PROJECTS)
            cutoff = (datetime.now() - timedelta(days=30)).isoformat()
            removed = 0
            for key, val in raw.items():
                key_str = key.decode() if isinstance(key, bytes) else key
                val_str = val.decode() if isinstance(val, bytes) else val
                p = json.loads(val_str)
                if p.get("status") in ("completed", "cancelled", "archived"):
                    updated = p.get("updated_at", p.get("created_at", ""))
                    if updated and updated < cutoff:
                        await self.redis.hdel(_KEY_PROJECTS, key_str)
                        removed += 1
            if removed:
                logger.info("Projekt-Cleanup: %d abgeschlossene Projekte entfernt", removed)
        except Exception as e:
            logger.debug("Projekt-Cleanup fehlgeschlagen: %s", e)

    async def _cleanup_old_followups(self):
        """Entfernt erledigte/abgelaufene Followups die aelter als 14 Tage sind."""
        if not self.redis:
            return
        try:
            raw = await self.redis.hgetall(_KEY_FOLLOWUPS)
            cutoff = (datetime.now() - timedelta(days=self.question_ttl_days)).isoformat()
            removed = 0
            for key, val in raw.items():
                key_str = key.decode() if isinstance(key, bytes) else key
                val_str = val.decode() if isinstance(val, bytes) else val
                f = json.loads(val_str)
                if f.get("status") in ("completed", "cancelled"):
                    completed = f.get("completed_at", f.get("created_at", ""))
                    if completed and completed < cutoff:
                        await self.redis.hdel(_KEY_FOLLOWUPS, key_str)
                        removed += 1
                elif f.get("created_at", "") < cutoff:
                    await self.redis.hdel(_KEY_FOLLOWUPS, key_str)
                    removed += 1
            if removed:
                logger.info("Followup-Cleanup: %d abgelaufene Followups entfernt", removed)
        except Exception as e:
            logger.debug("Followup-Cleanup fehlgeschlagen: %s", e)

    # ------------------------------------------------------------------
    # Projekt-Tracking
    # ------------------------------------------------------------------

    async def create_project(self, name: str, description: str = "",
                             person: str = "") -> dict:
        """Erstellt ein neues Projekt zum Nachverfolgen.

        Args:
            name: Projektname (z.B. "Gartenhaus bauen")
            description: Kurzbeschreibung
            person: Zugeordnete Person
        """
        if not self.redis or not self.enabled:
            return {"success": False, "message": "Konversationsgedaechtnis nicht verfuegbar."}

        if not name or not name.strip():
            return {"success": False, "message": "Projektname darf nicht leer sein."}

        name = name.strip()

        # Duplikat-Check
        existing = await self._find_project(name)
        if existing and existing.get("name", "").lower() == name.lower():
            return {"success": False, "message": f"Projekt '{name}' existiert bereits (Status: {existing.get('status', '?')}). Nutze update_project um es zu aendern."}

        import secrets
        project_id = f"proj_{datetime.now().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(3)}_{name.lower().replace(' ', '_')[:20]}"
        project = {
            "id": project_id,
            "name": name,
            "description": description,
            "person": person,
            "status": "active",
            "milestones": [],
            "notes": [],
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }

        try:
            # Limit pruefen
            count = await self.redis.hlen(_KEY_PROJECTS)
            if count >= self.max_projects:
                return {"success": False, "message": f"Maximale Projektanzahl ({self.max_projects}) erreicht. Schliesse zuerst ein altes Projekt ab."}

            await self.redis.hset(_KEY_PROJECTS, project_id, json.dumps(project))
            logger.info("Projekt erstellt: %s", name)
            return {"success": True, "message": f"Projekt '{name}' angelegt.", "project_id": project_id}
        except Exception as e:
            logger.error("Projekt erstellen fehlgeschlagen: %s", e)
            return {"success": False, "message": str(e)}

    async def update_project(self, name: str, status: str = "",
                             note: str = "", milestone: str = "") -> dict:
        """Aktualisiert ein Projekt (Status, Notiz oder Meilenstein).

        Lock schuetzt den Read-Modify-Write-Zyklus gegen Race Conditions
        bei konkurrierenden Updates desselben Projekts.

        Args:
            name: Projektname (Suche per Teilstring)
            status: Neuer Status (active/paused/done)
            note: Neue Notiz hinzufuegen
            milestone: Neuen Meilenstein hinzufuegen
        """
        if not self.redis or not self.enabled:
            return {"success": False, "message": "Konversationsgedaechtnis nicht verfuegbar."}

        async with self._project_lock:
            project = await self._find_project(name)
            if not project:
                return {"success": False, "message": f"Projekt '{name}' nicht gefunden."}

            changes = []
            if status and status in ("active", "paused", "done"):
                project["status"] = status
                changes.append(f"Status → {status}")
            if note:
                project["notes"].append({
                    "text": note,
                    "date": datetime.now().isoformat(),
                })
                # Max 20 Notizen
                if len(project["notes"]) > 20:
                    project["notes"] = project["notes"][-20:]
                changes.append("Notiz hinzugefuegt")
            if milestone:
                project["milestones"].append({
                    "text": milestone,
                    "date": datetime.now().isoformat(),
                    "done": True,
                })
                changes.append(f"Meilenstein: {milestone}")

            if not changes:
                return {"success": False, "message": "Keine Aenderung angegeben (status, note oder milestone)."}

            project["updated_at"] = datetime.now().isoformat()

            try:
                await self.redis.hset(_KEY_PROJECTS, project["id"], json.dumps(project))
                return {"success": True, "message": f"Projekt '{project['name']}' aktualisiert: {', '.join(changes)}"}
            except Exception as e:
                return {"success": False, "message": str(e)}

    async def get_projects(self, status: str = "", person: str = "") -> list[dict]:
        """Gibt alle Projekte zurueck (optional gefiltert)."""
        if not self.redis or not self.enabled:
            return []

        try:
            raw = await self.redis.hgetall(_KEY_PROJECTS)
            projects = []
            for val in raw.values():
                val_str = val.decode() if isinstance(val, bytes) else val
                proj = json.loads(val_str)
                if status and proj.get("status") != status:
                    continue
                if person and proj.get("person", "").lower() != person.lower():
                    continue
                projects.append(proj)

            projects.sort(key=lambda p: p.get("updated_at", ""), reverse=True)
            return projects
        except Exception as e:
            logger.debug("Projekte laden fehlgeschlagen: %s", e)
            return []

    async def delete_project(self, name: str) -> dict:
        """Loescht ein Projekt.

        Lock schuetzt gegen gleichzeitige Updates auf dasselbe Projekt.
        """
        if not self.redis or not self.enabled:
            return {"success": False, "message": "Konversationsgedaechtnis nicht verfuegbar."}

        async with self._project_lock:
            project = await self._find_project(name)
            if not project:
                return {"success": False, "message": f"Projekt '{name}' nicht gefunden."}

            try:
                await self.redis.hdel(_KEY_PROJECTS, project["id"])
                return {"success": True, "message": f"Projekt '{project['name']}' geloescht."}
            except Exception as e:
                return {"success": False, "message": str(e)}

    async def _find_project(self, name: str) -> Optional[dict]:
        """Findet ein Projekt per Name (exakt oder Teilstring)."""
        if not self.redis:
            return None
        try:
            raw = await self.redis.hgetall(_KEY_PROJECTS)
            name_lower = name.lower()
            for val in raw.values():
                val_str = val.decode() if isinstance(val, bytes) else val
                proj = json.loads(val_str)
                if proj.get("name", "").lower() == name_lower:
                    return proj
            # Teilstring-Suche
            for val in raw.values():
                val_str = val.decode() if isinstance(val, bytes) else val
                proj = json.loads(val_str)
                if name_lower in proj.get("name", "").lower():
                    return proj
            return None
        except Exception as e:
            logger.debug("ConversationMemory Lesefehler: %s", e)
            return None

    # ------------------------------------------------------------------
    # Offene Fragen
    # ------------------------------------------------------------------

    async def add_question(self, question: str, context: str = "",
                           person: str = "") -> dict:
        """Speichert eine offene Frage zur spaeteren Nachverfolgung.

        Args:
            question: Die Frage selbst
            context: Kontext in dem die Frage gestellt wurde
            person: Wer hat gefragt
        """
        if not self.redis or not self.enabled:
            return {"success": False, "message": "Konversationsgedaechtnis nicht verfuegbar."}

        if not question or not question.strip():
            return {"success": False, "message": "Frage darf nicht leer sein."}

        question = question.strip()

        q_id = f"q_{datetime.now().strftime('%Y%m%d%H%M%S%f')[:20]}"
        entry = {
            "id": q_id,
            "question": question,
            "context": context,
            "person": person,
            "status": "open",
            "answer": "",
            "created_at": datetime.now().isoformat(),
        }

        try:
            count = await self.redis.hlen(_KEY_OPEN_QUESTIONS)
            if count >= self.max_questions:
                await self._cleanup_old_questions()

            await self.redis.hset(_KEY_OPEN_QUESTIONS, q_id, json.dumps(entry))
            logger.info("Offene Frage gespeichert: %s", question[:500])
            q_display = question[:60] + "..." if len(question) > 60 else question
            return {"success": True, "message": f"Frage gemerkt: '{q_display}'"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    async def answer_question(self, question_search: str, answer: str) -> dict:
        """Beantwortet/schliesst eine offene Frage.

        Args:
            question_search: Suchbegriff um die Frage zu finden
            answer: Die Antwort
        """
        if not self.redis or not self.enabled:
            return {"success": False, "message": "Konversationsgedaechtnis nicht verfuegbar."}

        q = await self._find_question(question_search)
        if not q:
            return {"success": False, "message": f"Frage zu '{question_search}' nicht gefunden."}

        q["status"] = "answered"
        q["answer"] = answer
        q["answered_at"] = datetime.now().isoformat()

        try:
            await self.redis.hset(_KEY_OPEN_QUESTIONS, q["id"], json.dumps(q))
            q_display = q['question'][:50] + "..." if len(q['question']) > 50 else q['question']
            return {"success": True, "message": f"Frage beantwortet: '{q_display}'"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    async def get_open_questions(self, person: str = "") -> list[dict]:
        """Gibt alle offenen Fragen zurueck."""
        if not self.redis or not self.enabled:
            return []

        try:
            raw = await self.redis.hgetall(_KEY_OPEN_QUESTIONS)
            questions = []
            for val in raw.values():
                val_str = val.decode() if isinstance(val, bytes) else val
                q = json.loads(val_str)
                if q.get("status") != "open":
                    continue
                if person and q.get("person", "").lower() != person.lower():
                    continue
                questions.append(q)

            questions.sort(key=lambda q: q.get("created_at", ""), reverse=True)
            return questions
        except Exception as e:
            logger.debug("Offene Fragen laden fehlgeschlagen: %s", e)
            return []

    async def _find_question(self, search: str) -> Optional[dict]:
        """Findet eine Frage per Teilstring-Suche."""
        if not self.redis:
            return None
        try:
            raw = await self.redis.hgetall(_KEY_OPEN_QUESTIONS)
            search_lower = search.lower()
            for val in raw.values():
                val_str = val.decode() if isinstance(val, bytes) else val
                q = json.loads(val_str)
                if search_lower in q.get("question", "").lower():
                    return q
            return None
        except Exception as e:
            logger.debug("ConversationMemory Lesefehler: %s", e)
            return None

    async def _cleanup_old_questions(self):
        """Entfernt beantwortete und abgelaufene Fragen."""
        if not self.redis:
            return
        try:
            raw = await self.redis.hgetall(_KEY_OPEN_QUESTIONS)
            cutoff = (datetime.now() - timedelta(days=self.question_ttl_days)).isoformat()
            for key, val in raw.items():
                key_str = key.decode() if isinstance(key, bytes) else key
                val_str = val.decode() if isinstance(val, bytes) else val
                q = json.loads(val_str)
                # Beantwortete Fragen ueber TTL entfernen
                if q.get("status") == "answered":
                    answered = q.get("answered_at", "")
                    if answered and answered < cutoff:
                        await self.redis.hdel(_KEY_OPEN_QUESTIONS, key_str)
                # Offene Fragen ueber TTL entfernen
                elif q.get("created_at", "") < cutoff:
                    await self.redis.hdel(_KEY_OPEN_QUESTIONS, key_str)
        except Exception as e:
            logger.debug("Fragen-Cleanup fehlgeschlagen: %s", e)

    # ------------------------------------------------------------------
    # Tages-Zusammenfassungen
    # ------------------------------------------------------------------

    async def save_daily_summary(self, summary: str, topics: list[str],
                                 date: str = "") -> dict:
        """Speichert eine Tages-Zusammenfassung.

        Args:
            summary: Zusammenfassung des Tages
            topics: Liste der Hauptthemen
            date: Datum (YYYY-MM-DD), default: heute
        """
        if not self.redis or not self.enabled:
            return {"success": False, "message": "Konversationsgedaechtnis nicht verfuegbar."}

        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        entry = {
            "date": date,
            "summary": summary,
            "topics": topics,
            "created_at": datetime.now().isoformat(),
        }

        try:
            key = _KEY_DAILY_SUMMARY + date
            await self.redis.set(key, json.dumps(entry))
            # TTL nur setzen wenn Retention konfiguriert (0 = unbegrenzt)
            if self.summary_retention_days > 0:
                await self.redis.expire(key, self.summary_retention_days * 86400)
            return {"success": True, "message": f"Zusammenfassung fuer {date} gespeichert."}
        except Exception as e:
            return {"success": False, "message": str(e)}

    async def get_daily_summary(self, date: str = "") -> Optional[dict]:
        """Gibt die Zusammenfassung eines Tages zurueck."""
        if not self.redis or not self.enabled:
            return None

        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        try:
            raw = await self.redis.get(_KEY_DAILY_SUMMARY + date)
            if not raw:
                return None
            raw_str = raw.decode() if isinstance(raw, bytes) else raw
            return json.loads(raw_str)
        except Exception as e:
            logger.debug("ConversationMemory Lesefehler: %s", e)
            return None

    async def get_recent_summaries(self, days: int = 7) -> list[dict]:
        """Gibt die Zusammenfassungen der letzten X Tage zurueck."""
        if not self.redis or not self.enabled:
            return []

        summaries = []
        today = datetime.now().date()
        for i in range(days):
            date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            s = await self.get_daily_summary(date)
            if s:
                summaries.append(s)
        return summaries

    # ------------------------------------------------------------------
    # Follow-Up Tracking (Neugier & Nachfragen)
    # ------------------------------------------------------------------

    # Trigger-Muster: Deutsche Phrasen die auf zukuenftige Ereignisse hindeuten
    _FOLLOWUP_PATTERNS = [
        # (regex_pattern, vorgeschlagenes_topic, ask_after_default)
        (r"(?i)\b(arzt|zahnarzt|facharzt)termin\b.*?\b(morgen|uebermorgen|naechste woche)\b",
         "Arzttermin", "tomorrow"),
        (r"(?i)\b(paket|lieferung|sendung)\b.*?\b(kommt|erwartet|unterwegs)\b",
         "Paket-Lieferung", "tomorrow"),
        (r"(?i)\b(bewerbungs?gespraech|vorstellungsgespraech|interview)\b",
         "Bewerbungsgespraech", "tomorrow"),
        (r"(?i)\b(pruefung|klausur|examen|test)\b.*?\b(morgen|naechste woche|bald)\b",
         "Pruefung", "tomorrow"),
        (r"(?i)\b(reparatur|handwerker|techniker)\b.*?\b(kommt|morgen|naechste woche)\b",
         "Reparatur/Handwerker", "tomorrow"),
        (r"(?i)\b(reise|urlaub|flug)\b.*?\b(morgen|naechste woche|bald)\b",
         "Reise/Urlaub", "tomorrow"),
        (r"(?i)\b(meeting|besprechung|termin)\b.*?\b(morgen|naechste woche)\b",
         "Termin/Meeting", "tomorrow"),
        (r"(?i)\b(geburtstag|jubilaeum|feier)\b.*?\b(morgen|naechste woche|bald)\b",
         "Geburtstag/Feier", "tomorrow"),
        (r"(?i)\bwarte\s+(auf|noch)\b",
         "Wartet auf etwas", "next_conversation"),
        (r"(?i)\b(muss|sollte|will)\b.*?\b(morgen|spaeter|nachher)\b.*?\b(erledigen|machen|kaufen|anrufen)\b",
         "Aufgabe geplant", "next_conversation"),
    ]

    async def add_followup(self, topic: str, context: str,
                           ask_after: str = "next_conversation") -> dict:
        """Speichert eine Follow-Up-Frage fuer spaetere Nachverfolgung.

        Args:
            topic: Thema der Nachfrage (z.B. "Arzttermin", "Paket")
            context: Kontext in dem das Thema aufkam
            ask_after: Wann nachfragen — "next_conversation", "tomorrow"
                       oder ISO-Datetime (z.B. "2025-01-15T10:00:00")
        """
        if not self.redis or not self.enabled:
            return {"success": False, "message": "Konversationsgedaechtnis nicht verfuegbar."}

        if not topic or not topic.strip():
            return {"success": False, "message": "Follow-Up Thema darf nicht leer sein."}

        topic = topic.strip()

        # ask_after in konkreten Zeitpunkt umrechnen
        due_at = self._resolve_ask_after(ask_after)

        import secrets
        followup_id = f"fu_{datetime.now().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(3)}"
        entry = {
            "id": followup_id,
            "topic": topic,
            "context": context,
            "ask_after": ask_after,
            "due_at": due_at,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
        }

        try:
            await self.redis.hset(_KEY_FOLLOWUPS, followup_id, json.dumps(entry))
            logger.info("Follow-Up gespeichert: %s (faellig: %s)", topic, due_at)
            return {"success": True, "message": f"Follow-Up gemerkt: '{topic}' (nachfragen: {ask_after})"}
        except Exception as e:
            logger.error("Follow-Up speichern fehlgeschlagen: %s", e)
            return {"success": False, "message": str(e)}

    async def get_pending_followups(self) -> list[dict]:
        """Gibt alle faelligen Follow-Ups zurueck (basierend auf ask_after Timing).

        Ein Follow-Up ist faellig wenn:
        - ask_after == "next_conversation" → immer faellig
        - ask_after == "tomorrow" → faellig ab dem naechsten Tag
        - ask_after ist ISO-Datetime → faellig ab diesem Zeitpunkt
        """
        if not self.redis or not self.enabled:
            return []

        try:
            raw = await self.redis.hgetall(_KEY_FOLLOWUPS)
            now = datetime.now()
            pending = []

            for val in raw.values():
                val_str = val.decode() if isinstance(val, bytes) else val
                entry = json.loads(val_str)

                if entry.get("status") != "pending":
                    continue

                due_at = entry.get("due_at", "")
                if not due_at:
                    # Kein Faelligkeitsdatum → sofort faellig
                    pending.append(entry)
                    continue

                try:
                    due_dt = datetime.fromisoformat(due_at)
                    if now >= due_dt:
                        pending.append(entry)
                except (ValueError, TypeError):
                    # Ungueltige Zeitangabe → sicherheitshalber anzeigen
                    pending.append(entry)

            # Aelteste zuerst
            pending.sort(key=lambda f: f.get("created_at", ""))
            return pending
        except Exception as e:
            logger.debug("Follow-Ups laden fehlgeschlagen: %s", e)
            return []

    async def complete_followup(self, topic: str) -> dict:
        """Markiert ein Follow-Up als erledigt.

        Args:
            topic: Thema (Suche per Teilstring, wie bei Projekten)
        """
        if not self.redis or not self.enabled:
            return {"success": False, "message": "Konversationsgedaechtnis nicht verfuegbar."}

        entry = await self._find_followup(topic)
        if not entry:
            return {"success": False, "message": f"Follow-Up zu '{topic}' nicht gefunden."}

        entry["status"] = "done"
        entry["completed_at"] = datetime.now().isoformat()

        try:
            await self.redis.hset(_KEY_FOLLOWUPS, entry["id"], json.dumps(entry))
            return {"success": True, "message": f"Follow-Up '{entry['topic']}' als erledigt markiert."}
        except Exception as e:
            return {"success": False, "message": str(e)}

    async def extract_followup_triggers(self, text: str) -> list[dict]:
        """Erkennt Phrasen im Text die auf zukuenftige Ereignisse hindeuten.

        Sucht nach Mustern wie "Arzttermin morgen", "Paket kommt",
        "Bewerbungsgespraech", "Pruefung naechste Woche" etc.

        Args:
            text: Der zu analysierende Text

        Returns:
            Liste von vorgeschlagenen Follow-Ups mit topic, context, ask_after
        """
        if not text or not text.strip():
            return []

        suggestions = []
        seen_topics = set()

        for pattern, topic, ask_after in self._FOLLOWUP_PATTERNS:
            match = re.search(pattern, text)
            if match and topic not in seen_topics:
                seen_topics.add(topic)
                # Kontext: den gematchten Satz extrahieren
                # Finde den Satz der den Match enthaelt
                start = max(0, match.start() - 40)
                end = min(len(text), match.end() + 40)
                context_snippet = text[start:end].strip()
                if start > 0:
                    context_snippet = "..." + context_snippet
                if end < len(text):
                    context_snippet = context_snippet + "..."

                suggestions.append({
                    "topic": topic,
                    "context": context_snippet,
                    "ask_after": ask_after,
                    "matched_text": match.group(0),
                })

        return suggestions

    def _resolve_ask_after(self, ask_after: str) -> str:
        """Wandelt ask_after in einen konkreten ISO-Zeitpunkt um."""
        now = datetime.now()

        if ask_after == "next_conversation":
            # Sofort faellig — beim naechsten Gespraech nachfragen
            return now.isoformat()

        if ask_after == "tomorrow":
            # Morgen frueh um 8:00 Uhr
            tomorrow = now + timedelta(days=1)
            due = tomorrow.replace(hour=8, minute=0, second=0, microsecond=0)
            return due.isoformat()

        # Versuche als ISO-Datetime zu parsen
        try:
            dt = datetime.fromisoformat(ask_after)
            return dt.isoformat()
        except (ValueError, TypeError):
            # Fallback: sofort faellig
            logger.warning("Ungueltiges ask_after Format: %s, verwende 'jetzt'", ask_after)
            return now.isoformat()

    async def _find_followup(self, topic: str) -> Optional[dict]:
        """Findet ein Follow-Up per Topic (exakt oder Teilstring)."""
        if not self.redis:
            return None
        try:
            raw = await self.redis.hgetall(_KEY_FOLLOWUPS)
            topic_lower = topic.lower()
            # Exakte Suche zuerst
            for val in raw.values():
                val_str = val.decode() if isinstance(val, bytes) else val
                entry = json.loads(val_str)
                if entry.get("status") != "pending":
                    continue
                if entry.get("topic", "").lower() == topic_lower:
                    return entry
            # Teilstring-Suche
            for val in raw.values():
                val_str = val.decode() if isinstance(val, bytes) else val
                entry = json.loads(val_str)
                if entry.get("status") != "pending":
                    continue
                if topic_lower in entry.get("topic", "").lower():
                    return entry
            return None
        except Exception as e:
            logger.debug("Follow-Up Suche fehlgeschlagen: %s", e)
            return None

    # ------------------------------------------------------------------
    # Kontext fuer LLM / Context Builder
    # ------------------------------------------------------------------

    async def get_memory_context(self) -> str:
        """Kompakte Zusammenfassung fuer den LLM-Kontext."""
        parts = []

        # Aktive Projekte
        projects = await self.get_projects(status="active")
        if projects:
            proj_strs = []
            for p in projects[:5]:
                ms = len(p.get("milestones", []))
                proj_strs.append(f"{p['name']} ({ms} Meilensteine)")
            parts.append(f"Aktive Projekte: {', '.join(proj_strs)}")

        # Offene Fragen
        questions = await self.get_open_questions()
        if questions:
            q_strs = [q["question"][:40] for q in questions[:3]]
            parts.append(f"Offene Fragen ({len(questions)}): {'; '.join(q_strs)}")

        # Gestrige Zusammenfassung
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        summary = await self.get_daily_summary(yesterday)
        if summary and summary.get("topics"):
            parts.append(f"Gestern: {', '.join(summary['topics'][:5])}")

        # Aktive Threads
        threads = await self.get_recent_threads(limit=3)
        if threads:
            t_strs = [t.get("topic", "?") for t in threads]
            parts.append(f"Aktive Themen: {', '.join(t_strs)}")

        return " | ".join(parts) if parts else ""

    # ------------------------------------------------------------------
    # Phase 3B: Gesprächs-Threads
    # ------------------------------------------------------------------

    async def create_thread(self, topic: str, session_id: str = "") -> dict:
        """Erstellt einen neuen Gespraechs-Thread.

        Threads verknuepfen mehrere Sessions zum gleichen Thema.

        Args:
            topic: Thema des Threads
            session_id: Aktuelle Session-ID

        Returns:
            Thread-Dict mit id, topic, session_ids, etc.
        """
        if not self.redis or not topic:
            return {}

        try:
            thread_id = f"thread_{datetime.now().strftime('%Y%m%d%H%M%S')}_{id(topic) % 10000}"
            thread = {
                "id": thread_id,
                "topic": topic,
                "session_ids": [session_id] if session_id else [],
                "messages_count": 0,
                "created_at": datetime.now().isoformat(),
                "last_active": datetime.now().isoformat(),
            }
            await self.redis.hset(_KEY_THREADS, thread_id, json.dumps(thread))

            # Keywords indexieren fuer spaeteres Matching
            keywords = self._extract_topic_keywords(topic)
            for kw in keywords:
                await self.redis.hset(_KEY_THREAD_INDEX, kw, thread_id)

            logger.info("Thread erstellt: '%s' (ID: %s)", topic, thread_id)
            return thread
        except Exception as e:
            logger.debug("Thread-Erstellung fehlgeschlagen: %s", e)
            return {}

    async def link_session_to_thread(
        self, session_id: str, topic_hint: str = ""
    ) -> str | None:
        """Verknuepft eine Session mit einem bestehenden Thread.

        Sucht nach Keyword-Overlap mit existierenden Threads.

        Args:
            session_id: Aktuelle Session-ID
            topic_hint: Themen-Hinweis aus der aktuellen Nachricht

        Returns:
            Thread-ID wenn verknuepft, None sonst
        """
        if not self.redis or not topic_hint:
            return None

        try:
            keywords = self._extract_topic_keywords(topic_hint)
            if not keywords:
                return None

            # Thread-Index durchsuchen
            best_thread_id = None
            best_overlap = 0

            for kw in keywords:
                tid = await self.redis.hget(_KEY_THREAD_INDEX, kw)
                if tid:
                    tid = tid.decode() if isinstance(tid, bytes) else tid
                    # Overlap zaehlen
                    thread_raw = await self.redis.hget(_KEY_THREADS, tid)
                    if thread_raw:
                        thread = json.loads(thread_raw)
                        thread_keywords = self._extract_topic_keywords(thread.get("topic", ""))
                        overlap = len(set(keywords) & set(thread_keywords))
                        if overlap > best_overlap:
                            best_overlap = overlap
                            best_thread_id = tid

            if best_thread_id and best_overlap >= 2:
                # Session zum Thread hinzufuegen
                thread_raw = await self.redis.hget(_KEY_THREADS, best_thread_id)
                if thread_raw:
                    thread = json.loads(thread_raw)
                    if session_id not in thread.get("session_ids", []):
                        thread.setdefault("session_ids", []).append(session_id)
                        thread["last_active"] = datetime.now().isoformat()
                        thread["messages_count"] = thread.get("messages_count", 0) + 1
                        await self.redis.hset(_KEY_THREADS, best_thread_id, json.dumps(thread))
                return best_thread_id

        except Exception as e:
            logger.debug("Thread-Linking fehlgeschlagen: %s", e)
        return None

    async def get_thread_context(self, topic: str, limit: int = 3) -> list[dict]:
        """Gibt vorherige Sessions zum gleichen Thema zurueck.

        Args:
            topic: Thema oder Keywords
            limit: Max. Anzahl Threads

        Returns:
            Liste von Thread-Dicts
        """
        if not self.redis or not topic:
            return []

        try:
            keywords = self._extract_topic_keywords(topic)
            thread_ids = set()

            for kw in keywords:
                tid = await self.redis.hget(_KEY_THREAD_INDEX, kw)
                if tid:
                    thread_ids.add(tid.decode() if isinstance(tid, bytes) else tid)

            threads = []
            for tid in list(thread_ids)[:limit]:
                raw = await self.redis.hget(_KEY_THREADS, tid)
                if raw:
                    threads.append(json.loads(raw))

            # Nach letzter Aktivitaet sortieren
            threads.sort(key=lambda t: t.get("last_active", ""), reverse=True)
            return threads[:limit]

        except Exception as e:
            logger.debug("Thread-Context Fehler: %s", e)
            return []

    async def get_recent_threads(self, limit: int = 5) -> list[dict]:
        """Gibt die zuletzt aktiven Threads zurueck."""
        if not self.redis:
            return []

        try:
            all_raw = await self.redis.hgetall(_KEY_THREADS)
            threads = []
            for _tid, raw in all_raw.items():
                try:
                    threads.append(json.loads(raw))
                except (json.JSONDecodeError, TypeError):
                    continue

            threads.sort(key=lambda t: t.get("last_active", ""), reverse=True)
            return threads[:limit]
        except Exception as e:
            logger.debug("Recent threads Fehler: %s", e)
            return []

    async def auto_detect_thread(self, text: str, session_id: str = ""):
        """Automatische Thread-Erkennung nach jedem Turn.

        Extrahiert Keywords, versucht zu verknuepfen, erstellt ggf. neuen Thread.
        """
        if not self.redis or not text or len(text.split()) < 5:
            return

        try:
            # Versuche bestehenden Thread zu verknuepfen
            linked = await self.link_session_to_thread(session_id, text)
            if linked:
                return

            # Kein passender Thread — ggf. neuen erstellen bei genuegend Kontext
            if len(text.split()) >= 10:
                topic = " ".join(text.split()[:8])  # Erste 8 Woerter als Topic
                await self.create_thread(topic, session_id)
        except Exception as e:
            logger.debug("Auto-Thread-Detection Fehler: %s", e)

    @staticmethod
    def _extract_topic_keywords(text: str) -> list[str]:
        """Extrahiert Schluesselwoerter aus einem Text fuer Thread-Matching.

        Filtert Stoppwoerter und gibt relevante Woerter zurueck.
        """
        if not text:
            return []
        _STOP_WORDS = {
            "der", "die", "das", "ein", "eine", "und", "oder", "aber", "ich",
            "du", "er", "sie", "es", "wir", "ihr", "mein", "dein", "sein",
            "ihr", "ist", "sind", "hat", "haben", "wird", "werden", "kann",
            "soll", "muss", "wie", "was", "wer", "wo", "wann", "warum",
            "mit", "von", "fuer", "bei", "nach", "vor", "ueber", "unter",
            "in", "an", "auf", "aus", "zu", "um", "nicht", "kein", "keine",
            "auch", "noch", "schon", "mal", "so", "ja", "nein", "bitte",
            "the", "is", "are", "was", "has", "have", "will", "can",
        }
        words = text.lower().split()
        return [w for w in words if len(w) >= 3 and w not in _STOP_WORDS][:10]
