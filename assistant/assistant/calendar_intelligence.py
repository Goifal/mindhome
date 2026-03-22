"""
Calendar Intelligence - Erkennt Gewohnheiten und Konflikte aus Kalender-Daten.

Quick Win: Extrahiert Muster aus wiederkehrenden Terminen,
erkennt Konflikte (z.B. Pendelzeit vs. Meeting-Beginn),
und leitet Gewohnheiten ab (z.B. Mittagspause immer 12-13 Uhr).

Konfigurierbar in der Jarvis Assistant UI unter dem Tab "Kalender-Intelligenz".
"""

import hashlib
import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import redis.asyncio as aioredis

from .config import yaml_config

_LOCAL_TZ = ZoneInfo(yaml_config.get("timezone", "Europe/Berlin"))

logger = logging.getLogger(__name__)

REDIS_KEY_HABITS = "mha:calendar:habits"
REDIS_KEY_CONFLICTS = "mha:calendar:conflicts"
REDIS_KEY_EVENT_HISTORY = "mha:calendar:event_history"
REDIS_KEY_COMMUTE_PREFIX = "mha:calendar:commute:"


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
        self.per_route_commute_enabled = cfg.get("per_route_commute", False)

        # Erkannte Gewohnheiten (Cache)
        self._habits: list[dict] = []
        self._conflicts: list[dict] = []
        # Per-route commute times: destination_hash -> learned minutes
        self._route_commute_cache: dict[str, float] = {}

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis."""
        self.redis = redis_client
        if self.redis and self.enabled:
            await self._load_habits()
            if self.per_route_commute_enabled:
                await self._load_route_commute_cache()
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

    @staticmethod
    def _location_hash(location: str) -> str:
        """Erzeugt einen stabilen Hash fuer eine Location (normalisiert)."""
        normalized = location.strip().lower()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

    async def _load_route_commute_cache(self):
        """Laedt alle gespeicherten per-route Pendelzeiten aus Redis in den Cache."""
        if not self.redis:
            return
        try:
            # Scan fuer alle commute keys
            cursor = 0
            prefix = REDIS_KEY_COMMUTE_PREFIX
            while True:
                cursor, keys = await self.redis.scan(
                    cursor=cursor, match=f"{prefix}*", count=100
                )
                for key in keys:
                    raw = await self.redis.get(key)
                    if raw:
                        loc_hash = (
                            key.decode("utf-8").removeprefix(prefix)
                            if isinstance(key, bytes)
                            else str(key).removeprefix(prefix)
                        )
                        try:
                            self._route_commute_cache[loc_hash] = float(raw)
                        except (ValueError, TypeError):
                            logger.warning(
                                "Ungueltige Pendelzeit in Redis fuer Key %s: %s",
                                key,
                                raw,
                            )
                if cursor == 0:
                    break
            if self._route_commute_cache:
                logger.info(
                    "Per-Route Pendelzeiten geladen: %d Routen",
                    len(self._route_commute_cache),
                )
        except Exception as e:
            logger.warning("Route-Commute-Cache laden fehlgeschlagen: %s", e)

    async def store_commute_time(self, location: str, minutes: float):
        """Speichert eine gelernte Pendelzeit fuer eine bestimmte Location.

        Wird aufgerufen wenn ein Benutzer eine tatsaechliche Pendelzeit fuer
        eine bestimmte Location meldet oder wenn aus Kalender-Daten abgeleitet.

        Args:
            location: Zielort-String (z.B. "Buero", "Arztpraxis Dr. Mueller")
            minutes: Tatsaechliche Pendelzeit in Minuten
        """
        if not self.per_route_commute_enabled:
            return
        if not location or minutes <= 0:
            return

        loc_hash = self._location_hash(location)
        self._route_commute_cache[loc_hash] = minutes

        if self.redis:
            try:
                key = f"{REDIS_KEY_COMMUTE_PREFIX}{loc_hash}"
                # 90 Tage TTL — Pendelzeiten koennen sich aendern
                await self.redis.setex(key, 90 * 86400, str(minutes))
                logger.info(
                    "Pendelzeit gespeichert: '%s' -> %.0f Min. (hash=%s)",
                    location,
                    minutes,
                    loc_hash,
                )
            except Exception as e:
                logger.warning("Pendelzeit speichern fehlgeschlagen: %s", e)

    def _get_commute_for_event(self, event: dict) -> float:
        """Ermittelt Pendelzeit fuer ein Event — per-route oder global default.

        Args:
            event: Kalender-Event dict (muss 'location' Feld haben)

        Returns:
            Pendelzeit in Minuten
        """
        if not self.per_route_commute_enabled:
            return self.commute_minutes

        location = event.get("location", "")
        if location:
            loc_hash = self._location_hash(location)
            learned = self._route_commute_cache.get(loc_hash)
            if learned is not None:
                return learned

        return self.commute_minutes

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
                    habits.append(
                        {
                            "type": "recurring_event",
                            "title": title,
                            "day": day,
                            "hour": int(hour),
                            "count": count,
                            "description": f"{title} findet regelmaessig {day}s um {hour} Uhr statt ({count}x erkannt).",
                        }
                    )

        # Zeitblock-Gewohnheiten (z.B. immer frei zwischen 12-13)
        hour_activity = Counter()
        for ev in events:
            start = self._parse_dt(ev.get("start", ""))
            end = self._parse_dt(ev.get("end", ""))
            if start and end and not ev.get("all_day"):
                if end.hour >= start.hour:
                    for h in range(start.hour, min(end.hour, 24)):
                        hour_activity[h] += 1
                else:
                    # Midnight-crossing event
                    for h in range(start.hour, 24):
                        hour_activity[h] += 1
                    for h in range(0, end.hour):
                        hour_activity[h] += 1

        return habits

    def _detect_conflicts(self, events: list[dict]) -> list[dict]:
        """Erkennt Zeitkonflikte und Pendelzeit-Probleme.

        Z.B. 'Meeting um 9 Uhr, aber Pendelzeit 30 Min = muss um 8:30 los'.
        Nutzt per-route Pendelzeiten wenn per_route_commute aktiviert ist.
        """
        conflicts = []

        # Sortierte Events nach Startzeit
        timed_events = []
        for ev in events:
            start = self._parse_dt(ev.get("start", ""))
            end = self._parse_dt(ev.get("end", ""))
            if start and end and not ev.get("all_day"):
                timed_events.append(
                    {
                        "start": start,
                        "end": end,
                        "summary": ev.get("summary", ""),
                        "location": ev.get("location", ""),
                        "_orig": ev,
                    }
                )

        timed_events.sort(key=lambda e: e["start"])

        # Ueberlappungen erkennen
        for i in range(len(timed_events) - 1):
            curr = timed_events[i]
            nxt = timed_events[i + 1]
            gap = (nxt["start"] - curr["end"]).total_seconds() / 60

            if gap < 0:
                # Direkte Ueberlappung
                conflicts.append(
                    {
                        "type": "overlap",
                        "event_a": curr["summary"],
                        "event_b": nxt["summary"],
                        "gap_minutes": round(gap),
                        "description": f"'{curr['summary']}' und '{nxt['summary']}' ueberlappen sich um {abs(round(gap))} Minuten.",
                    }
                )
            else:
                # Pendelzeit fuer das naechste Event ermitteln (per-route oder global)
                commute = self._get_commute_for_event(nxt["_orig"])
                if 0 < gap < commute:
                    # Pendelzeit-Warnung
                    conflicts.append(
                        {
                            "type": "tight_schedule",
                            "event_a": curr["summary"],
                            "event_b": nxt["summary"],
                            "gap_minutes": round(gap),
                            "commute_minutes": round(commute),
                            "description": f"Nur {round(gap)} Min. zwischen '{curr['summary']}' und '{nxt['summary']}' (Pendelzeit: {round(commute)} Min.).",
                        }
                    )

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
                breaks.append(
                    {
                        "start": curr_end.strftime("%H:%M"),
                        "end": next_start.strftime("%H:%M"),
                        "duration_minutes": round(gap),
                        "description": f"Freies Zeitfenster: {curr_end.strftime('%H:%M')} - {next_start.strftime('%H:%M')} ({round(gap)} Min.)",
                    }
                )

        return breaks

    async def is_in_event(self) -> Optional[dict]:
        """Prueft ob gerade ein Kalender-Event stattfindet.

        Returns:
            Dict mit in_event, summary, ends_at oder None wenn kein Event.
        """
        if not self.redis or not self.enabled:
            return None
        try:
            raw = await self.redis.get(REDIS_KEY_EVENT_HISTORY)
            if not raw:
                return None
            events = json.loads(raw)
            now = datetime.now(_LOCAL_TZ)
            for ev in events:
                start = self._parse_dt(ev.get("start", ""))
                end = self._parse_dt(ev.get("end", ""))
                if not start or not end or ev.get("all_day"):
                    continue
                # Vergleich in Lokalzeit
                start_local = (
                    start.astimezone(_LOCAL_TZ)
                    if start.tzinfo
                    else start.replace(tzinfo=_LOCAL_TZ)
                )
                end_local = (
                    end.astimezone(_LOCAL_TZ)
                    if end.tzinfo
                    else end.replace(tzinfo=_LOCAL_TZ)
                )
                if start_local <= now <= end_local:
                    return {
                        "in_event": True,
                        "summary": ev.get("summary", "Termin"),
                        "ends_at": end_local.strftime("%H:%M"),
                    }
        except Exception as e:
            logger.debug("is_in_event Fehler: %s", e)
        return None

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
