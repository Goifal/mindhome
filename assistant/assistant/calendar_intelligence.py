"""
Calendar Intelligence - Erkennt Gewohnheiten und Konflikte aus Kalender-Daten.

Quick Win: Extrahiert Muster aus wiederkehrenden Terminen,
erkennt Konflikte (z.B. Pendelzeit vs. Meeting-Beginn),
und leitet Gewohnheiten ab (z.B. Mittagspause immer 12-13 Uhr).

Konfigurierbar in der Jarvis Assistant UI unter dem Tab "Kalender-Intelligenz".
"""

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config

logger = logging.getLogger(__name__)

REDIS_KEY_HABITS = "mha:calendar:habits"
REDIS_KEY_CONFLICTS = "mha:calendar:conflicts"
REDIS_KEY_EVENT_HISTORY = "mha:calendar:event_history"


class CalendarIntelligence:
    """Erkennt Gewohnheiten und Konflikte aus Kalender-Daten."""

    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None

        cfg = yaml_config.get("calendar_intelligence", {})
        self.enabled = cfg.get("enabled", True)
        self.commute_minutes = cfg.get("commute_minutes", 30)
        self.habit_min_occurrences = cfg.get("habit_min_occurrences", 3)
        self.conflict_lookahead_hours = cfg.get("conflict_lookahead_hours", 24)
        self.habit_detection_enabled = cfg.get("habit_detection", True)
        self.conflict_detection_enabled = cfg.get("conflict_detection", True)
        self.break_detection_enabled = cfg.get("break_detection", True)

        # Erkannte Gewohnheiten (Cache)
        self._habits: list[dict] = []
        self._conflicts: list[dict] = []

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis."""
        self.redis = redis_client
        if self.redis and self.enabled:
            await self._load_habits()
        logger.info("CalendarIntelligence initialisiert (enabled: %s)", self.enabled)

    async def _load_habits(self):
        """Laedt gespeicherte Gewohnheiten aus Redis."""
        if not self.redis:
            return
        try:
            raw = await self.redis.get(REDIS_KEY_HABITS)
            if raw:
                self._habits = json.loads(raw)
        except Exception as e:
            logger.debug("Habits laden fehlgeschlagen: %s", e)

    async def analyze_events(self, events: list[dict]) -> dict:
        """Analysiert Kalender-Events und extrahiert Muster.

        Args:
            events: Liste von Kalender-Events mit Feldern:
                summary: str, start: str (ISO), end: str (ISO), all_day: bool

        Returns:
            Dict mit habits, conflicts, breaks
        """
        if not self.enabled:
            return {"habits": [], "conflicts": [], "breaks": []}

        result = {
            "habits": [],
            "conflicts": [],
            "breaks": [],
        }

        if self.habit_detection_enabled:
            result["habits"] = self._detect_habits(events)

        if self.conflict_detection_enabled:
            result["conflicts"] = self._detect_conflicts(events)

        if self.break_detection_enabled:
            result["breaks"] = self._detect_breaks(events)

        # In Redis speichern
        if self.redis:
            try:
                await self.redis.set(
                    REDIS_KEY_HABITS,
                    json.dumps(result["habits"], ensure_ascii=False),
                    ex=86400 * 7,  # 7 Tage
                )
                await self.redis.set(
                    REDIS_KEY_CONFLICTS,
                    json.dumps(result["conflicts"], ensure_ascii=False),
                    ex=86400,  # 1 Tag
                )
            except Exception as e:
                logger.debug("Calendar Intelligence Redis-Fehler: %s", e)

        self._habits = result["habits"]
        self._conflicts = result["conflicts"]
        return result

    def _detect_habits(self, events: list[dict]) -> list[dict]:
        """Erkennt wiederkehrende Muster in Events.

        Z.B. 'Mittagspause immer 12-13 Uhr' oder 'Montags Team-Meeting um 10'.
        """
        habits = []

        # Nach Wochentag + Zeitfenster gruppieren
        time_slots: dict[str, list] = defaultdict(list)
        for ev in events:
            start = self._parse_dt(ev.get("start", ""))
            if not start or ev.get("all_day"):
                continue
            slot_key = f"{start.strftime('%A')}_{start.hour:02d}"
            time_slots[slot_key].append(ev.get("summary", ""))

        # Wiederkehrende Titel pro Slot
        for slot_key, summaries in time_slots.items():
            counts = Counter(summaries)
            for title, count in counts.items():
                if count >= self.habit_min_occurrences and title:
                    day, hour = slot_key.split("_")
                    habits.append({
                        "type": "recurring_event",
                        "title": title,
                        "day": day,
                        "hour": int(hour),
                        "count": count,
                        "description": f"{title} findet regelmaessig {day}s um {hour} Uhr statt ({count}x erkannt).",
                    })

        # Zeitblock-Gewohnheiten (z.B. immer frei zwischen 12-13)
        hour_activity = Counter()
        for ev in events:
            start = self._parse_dt(ev.get("start", ""))
            end = self._parse_dt(ev.get("end", ""))
            if start and end and not ev.get("all_day"):
                for h in range(start.hour, min(end.hour + 1, 24)):
                    hour_activity[h] += 1

        return habits

    def _detect_conflicts(self, events: list[dict]) -> list[dict]:
        """Erkennt Zeitkonflikte und Pendelzeit-Probleme.

        Z.B. 'Meeting um 9 Uhr, aber Pendelzeit 30 Min = muss um 8:30 los'.
        """
        conflicts = []
        commute_delta = timedelta(minutes=self.commute_minutes)

        # Sortierte Events nach Startzeit
        timed_events = []
        for ev in events:
            start = self._parse_dt(ev.get("start", ""))
            end = self._parse_dt(ev.get("end", ""))
            if start and end and not ev.get("all_day"):
                timed_events.append({"start": start, "end": end, "summary": ev.get("summary", "")})

        timed_events.sort(key=lambda e: e["start"])

        # Ueberlappungen erkennen
        for i in range(len(timed_events) - 1):
            curr = timed_events[i]
            nxt = timed_events[i + 1]
            gap = (nxt["start"] - curr["end"]).total_seconds() / 60

            if gap < 0:
                # Direkte Ueberlappung
                conflicts.append({
                    "type": "overlap",
                    "event_a": curr["summary"],
                    "event_b": nxt["summary"],
                    "gap_minutes": round(gap),
                    "description": f"'{curr['summary']}' und '{nxt['summary']}' ueberlappen sich um {abs(round(gap))} Minuten.",
                })
            elif 0 < gap < self.commute_minutes:
                # Pendelzeit-Warnung
                conflicts.append({
                    "type": "tight_schedule",
                    "event_a": curr["summary"],
                    "event_b": nxt["summary"],
                    "gap_minutes": round(gap),
                    "description": f"Nur {round(gap)} Min. zwischen '{curr['summary']}' und '{nxt['summary']}' (Pendelzeit: {self.commute_minutes} Min.).",
                })

        return conflicts

    def _detect_breaks(self, events: list[dict]) -> list[dict]:
        """Erkennt natuerliche Pausen und freie Zeitfenster."""
        breaks = []
        timed_events = []

        for ev in events:
            start = self._parse_dt(ev.get("start", ""))
            end = self._parse_dt(ev.get("end", ""))
            if start and end and not ev.get("all_day"):
                timed_events.append({"start": start, "end": end})

        timed_events.sort(key=lambda e: e["start"])

        for i in range(len(timed_events) - 1):
            curr_end = timed_events[i]["end"]
            next_start = timed_events[i + 1]["start"]
            gap = (next_start - curr_end).total_seconds() / 60

            if 30 <= gap <= 180:
                breaks.append({
                    "start": curr_end.strftime("%H:%M"),
                    "end": next_start.strftime("%H:%M"),
                    "duration_minutes": round(gap),
                    "description": f"Freies Zeitfenster: {curr_end.strftime('%H:%M')} - {next_start.strftime('%H:%M')} ({round(gap)} Min.)",
                })

        return breaks

    def get_habits(self) -> list[dict]:
        """Gibt erkannte Gewohnheiten zurueck."""
        return self._habits

    def get_conflicts(self) -> list[dict]:
        """Gibt erkannte Konflikte zurueck."""
        return self._conflicts

    def get_context_hint(self, events: list[dict] = None) -> str:
        """Gibt einen Kontext-Hinweis fuer den LLM-Prompt zurueck.

        Beinhaltet erkannte Konflikte und relevante Gewohnheiten.
        """
        hints = []

        if self._conflicts:
            for c in self._conflicts[:3]:
                hints.append(f"Kalender-Konflikt: {c['description']}")

        if self._habits:
            for h in self._habits[:2]:
                hints.append(f"Kalender-Gewohnheit: {h['description']}")

        return " ".join(hints)

    @staticmethod
    def _parse_dt(dt_str: str) -> Optional[datetime]:
        """Parst verschiedene Datums-Formate."""
        if not dt_str:
            return None
        try:
            # ISO-Format mit Timezone
            if "T" in dt_str:
                return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            # Nur Datum
            return datetime.fromisoformat(dt_str)
        except (ValueError, TypeError):
            return None
