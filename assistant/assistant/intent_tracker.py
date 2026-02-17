"""
Intent Tracker - Erkennt und verfolgt Absichten aus Gespraechen.

Phase 8: Extrahiert Zeitangaben und Aktionen aus natuerlicher Sprache
und erinnert den User zum richtigen Zeitpunkt.

Beispiel: "Naechstes WE kommen meine Eltern"
  -> Intent: Besuch, Deadline: naechstes Wochenende
  -> Freitag: "Deine Eltern kommen morgen. Gaestemodus vorbereiten?"
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import redis.asyncio as redis

from .config import yaml_config
from .ollama_client import OllamaClient

logger = logging.getLogger(__name__)

# Prompt fuer Intent-Extraktion aus Gespraechen
INTENT_EXTRACTION_PROMPT = """Analysiere den folgenden Text und extrahiere ABSICHTEN und PLAENE.

Suche nach:
- Zeitangaben: "morgen", "naechste Woche", "am Freitag", "in 3 Tagen"
- Personen: Wer kommt, wer geht, wer wird erwartet
- Aktionen: Was soll passieren, was muss vorbereitet werden

Antworte NUR mit einem JSON-Array. Wenn keine Absichten erkennbar, antworte mit [].

Format:
[
  {
    "intent": "Besuch der Eltern",
    "deadline": "2026-02-21",
    "person": "Eltern",
    "suggested_actions": ["Gaestemodus vorbereiten", "Gaestezimmer heizen"],
    "reminder_text": "Deine Eltern kommen morgen. Soll ich den Gaestemodus vorbereiten?"
  }
]

Heutiges Datum: {today}
Aktueller Wochentag: {weekday}

Text:
{text}

Absichten (JSON-Array):"""


class IntentTracker:
    """Verfolgt erkannte Absichten mit Deadline."""

    def __init__(self, ollama: OllamaClient):
        self.ollama = ollama
        self.redis: Optional[redis.Redis] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._notify_callback = None

        # Konfiguration
        cfg = yaml_config.get("intent_tracking", {})
        self.enabled = cfg.get("enabled", True)
        self.check_interval = cfg.get("check_interval_minutes", 60) * 60
        self.remind_hours_before = cfg.get("remind_hours_before", 12)

    async def initialize(self, redis_client: Optional[redis.Redis] = None):
        """Initialisiert den Tracker."""
        self.redis = redis_client
        if self.enabled and self.redis:
            self._running = True
            self._task = asyncio.create_task(self._reminder_loop())
            logger.info("IntentTracker initialisiert")

    def set_notify_callback(self, callback):
        """Setzt den Callback fuer Erinnerungen."""
        self._notify_callback = callback

    async def stop(self):
        """Stoppt den Tracker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # ------------------------------------------------------------------
    # Intent-Extraktion via LLM
    # ------------------------------------------------------------------

    async def extract_intents(self, text: str, person: str = "") -> list[dict]:
        """Extrahiert Absichten aus einem Text via LLM."""
        # Nur bei substantiellen Texten
        if len(text.split()) < 5:
            return []

        # Schnell-Filter: Enthaelt der Text Zeitangaben?
        time_keywords = [
            "morgen", "uebermorgen", "naechste", "naechstes", "naechsten",
            "am montag", "am dienstag", "am mittwoch", "am donnerstag",
            "am freitag", "am samstag", "am sonntag", "in ", "spaeter",
            "wochenende", "nacht", "abend", "heute", "bald",
            "kommt", "kommen", "besucht", "besuch", "termin", "meeting",
            "arzt", "urlaub", "verreise", "fahre weg", "fliege",
        ]
        text_lower = text.lower()
        if not any(kw in text_lower for kw in time_keywords):
            return []

        now = datetime.now()
        weekdays = ["Montag", "Dienstag", "Mittwoch", "Donnerstag",
                     "Freitag", "Samstag", "Sonntag"]

        prompt = INTENT_EXTRACTION_PROMPT.format(
            today=now.strftime("%Y-%m-%d"),
            weekday=weekdays[now.weekday()],
            text=text,
        )

        try:
            response = await self.ollama.chat(
                messages=[{"role": "user", "content": prompt}],
                model="qwen3:4b",
                temperature=0.1,
                max_tokens=512,
            )

            content = response.get("message", {}).get("content", "").strip()
            return self._parse_intents(content, person)

        except Exception as e:
            logger.error("Fehler bei Intent-Extraktion: %s", e)
            return []

    def _parse_intents(self, llm_output: str, person: str) -> list[dict]:
        """Parst die LLM-Antwort in Intents."""
        text = llm_output.strip()

        # Direktes JSON-Parsing
        try:
            result = json.loads(text)
            if isinstance(result, list):
                for item in result:
                    item["person"] = item.get("person", person)
                return [i for i in result if isinstance(i, dict) and i.get("intent")]
            return []
        except json.JSONDecodeError:
            pass

        # Fallback: JSON-Array suchen
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                result = json.loads(text[start:end + 1])
                if isinstance(result, list):
                    for item in result:
                        item["person"] = item.get("person", person)
                    return [i for i in result if isinstance(i, dict) and i.get("intent")]
            except json.JSONDecodeError:
                pass

        return []

    # ------------------------------------------------------------------
    # Intent-Speicherung
    # ------------------------------------------------------------------

    async def track_intent(self, intent: dict) -> bool:
        """Speichert einen erkannten Intent."""
        if not self.redis:
            return False

        try:
            intent_id = f"intent_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
            intent["intent_id"] = intent_id
            intent["created_at"] = datetime.now().isoformat()
            intent["status"] = "active"

            await self.redis.hset(
                f"mha:intent:{intent_id}",
                mapping={k: json.dumps(v) if isinstance(v, (list, dict)) else str(v)
                         for k, v in intent.items()},
            )
            await self.redis.sadd("mha:intents:active", intent_id)

            # TTL: 30 Tage
            await self.redis.expire(f"mha:intent:{intent_id}", 30 * 86400)

            logger.info("Intent gespeichert: %s (Deadline: %s)",
                        intent.get("intent", ""), intent.get("deadline", ""))
            return True
        except Exception as e:
            logger.error("Fehler beim Intent-Speichern: %s", e)
            return False

    async def get_active_intents(self) -> list[dict]:
        """Holt alle aktiven Intents."""
        if not self.redis:
            return []

        try:
            intent_ids = await self.redis.smembers("mha:intents:active")
            intents = []

            for intent_id in intent_ids:
                data = await self.redis.hgetall(f"mha:intent:{intent_id}")
                if data:
                    # JSON-Felder dekodieren
                    intent = {}
                    for k, v in data.items():
                        try:
                            intent[k] = json.loads(v)
                        except (json.JSONDecodeError, TypeError):
                            intent[k] = v
                    intents.append(intent)
                else:
                    # Intent expired, aus Set entfernen
                    await self.redis.srem("mha:intents:active", intent_id)

            return intents
        except Exception as e:
            logger.error("Fehler beim Laden aktiver Intents: %s", e)
            return []

    async def dismiss_intent(self, intent_id: str) -> bool:
        """Markiert einen Intent als erledigt."""
        if not self.redis:
            return False

        try:
            await self.redis.hset(f"mha:intent:{intent_id}", "status", "dismissed")
            await self.redis.srem("mha:intents:active", intent_id)
            logger.info("Intent erledigt: %s", intent_id)
            return True
        except Exception as e:
            logger.error("Fehler beim Erledigen des Intents: %s", e)
            return False

    # ------------------------------------------------------------------
    # Faellige Intents pruefen
    # ------------------------------------------------------------------

    async def get_due_intents(self) -> list[dict]:
        """Gibt Intents zurueck die bald faellig sind."""
        intents = await self.get_active_intents()
        if not intents:
            return []

        now = datetime.now()
        remind_before = timedelta(hours=self.remind_hours_before)
        due = []

        for intent in intents:
            deadline_str = intent.get("deadline", "")
            if not deadline_str:
                continue

            try:
                # Versuche verschiedene Formate
                deadline = None
                for fmt in ["%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"]:
                    try:
                        deadline = datetime.strptime(deadline_str, fmt)
                        break
                    except ValueError:
                        continue

                if not deadline:
                    continue

                # Ist die Deadline innerhalb des Erinnerungs-Fensters?
                time_until = deadline - now
                if timedelta(0) < time_until <= remind_before:
                    # Wurde fuer diesen Intent schon erinnert?
                    reminded_key = f"mha:intent:reminded:{intent.get('intent_id', '')}"
                    already = await self.redis.get(reminded_key) if self.redis else None
                    if not already:
                        intent["time_until_hours"] = round(time_until.total_seconds() / 3600, 1)
                        due.append(intent)

                        # Merken dass erinnert wurde
                        if self.redis:
                            await self.redis.setex(reminded_key, 86400, "1")

                # Ist die Deadline abgelaufen?
                elif time_until < timedelta(0):
                    # Auto-dismiss nach 2 Tagen
                    if abs(time_until.days) > 2:
                        await self.dismiss_intent(intent.get("intent_id", ""))

            except Exception as e:
                logger.debug("Fehler bei Deadline-Check: %s", e)

        return due

    # ------------------------------------------------------------------
    # Hintergrund-Loop
    # ------------------------------------------------------------------

    async def _reminder_loop(self):
        """Prueft stuendlich auf faellige Intents."""
        while self._running:
            try:
                await asyncio.sleep(self.check_interval)

                due_intents = await self.get_due_intents()
                for intent in due_intents:
                    reminder = intent.get("reminder_text", "")
                    if not reminder:
                        reminder = (
                            f"Erinnerung: {intent.get('intent', '')} "
                            f"(in {intent.get('time_until_hours', '?')} Stunden)"
                        )

                    if self._notify_callback:
                        await self._notify_callback({
                            "type": "intent_reminder",
                            "intent": intent,
                            "text": reminder,
                        })

                    logger.info("Intent-Erinnerung: %s", intent.get("intent", ""))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Fehler im Intent-Reminder-Loop: %s", e)
                await asyncio.sleep(60)
