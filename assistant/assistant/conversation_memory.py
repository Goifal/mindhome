"""
Konversations-Gedaechtnis++ - Projekt-Tracker, offene Fragen, Zusammenfassungen.

Erweitert das bestehende Memory-System um:
- Projekt-Tracking: Laufende Projekte mit Meilensteinen und Status
- Offene Fragen: Unbeantwortete Fragen die spaeter nachverfolgt werden
- Tages-Zusammenfassungen: Kompakte Zusammenfassung der Gespraechsthemen

Nutzt Redis fuer persistente Speicherung.
"""

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

# Defaults
_DEFAULT_MAX_PROJECTS = 20
_DEFAULT_MAX_QUESTIONS = 30
_DEFAULT_SUMMARY_RETENTION_DAYS = 30
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

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis-Verbindung."""
        self.redis = redis_client
        logger.info("ConversationMemory initialisiert (enabled: %s)", self.enabled)

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

        Args:
            name: Projektname (Suche per Teilstring)
            status: Neuer Status (active/paused/done)
            note: Neue Notiz hinzufuegen
            milestone: Neuen Meilenstein hinzufuegen
        """
        if not self.redis or not self.enabled:
            return {"success": False, "message": "Konversationsgedaechtnis nicht verfuegbar."}

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
        """Loescht ein Projekt."""
        if not self.redis or not self.enabled:
            return {"success": False, "message": "Konversationsgedaechtnis nicht verfuegbar."}

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

        return " | ".join(parts) if parts else ""
