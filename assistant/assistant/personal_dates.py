"""
Personal Dates - Geburtstags- und Jahrestags-Automatik.

Prueft taeglich (und beim Morgen-Briefing) ob persoenliche Termine
anstehen. Nutzt die bestehende semantic_memory personal_date Kategorie.

Features:
- Taeglicher Check auf anstehende Geburtstage/Jahrestage
- Integration ins Morgen-Briefing
- Proaktive Erinnerungen 3 Tage, 1 Tag und am Tag selbst
- Altersberechnung wenn Geburtsjahr bekannt
- Geschenkvorschlaege basierend auf gespeicherten Vorlieben

Redis Keys:
- mha:personal_dates:reminded:{date_key}  - Bereits erinnerte Daten (TTL 2 Tage)
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config

logger = logging.getLogger(__name__)

_cfg = yaml_config.get("personal_dates", {})
_ENABLED = _cfg.get("enabled", True)
_REMIND_DAYS_BEFORE = _cfg.get("remind_days_before", [3, 1, 0])
_CHECK_INTERVAL_HOURS = _cfg.get("check_interval_hours", 6)
_BRIEFING_LOOKAHEAD_DAYS = _cfg.get("briefing_lookahead_days", 7)


class PersonalDatesManager:
    """Geburtstags- und Jahrestags-Erinnerungen."""

    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        self.semantic_memory = None
        self._notify_callback = None
        self._check_task: Optional[asyncio.Task] = None

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis-Verbindung."""
        self.redis = redis_client
        if _ENABLED and self.redis:
            self._check_task = asyncio.create_task(self._check_loop())
            self._check_task.add_done_callback(
                lambda t: t.exception() if not t.cancelled() else None
            )
        logger.info("PersonalDatesManager initialisiert")

    def set_notify_callback(self, callback):
        """Setzt Callback fuer proaktive Erinnerungen."""
        self._notify_callback = callback

    def set_semantic_memory(self, semantic_memory):
        """Verbindet mit dem SemanticMemory fuer Fakten-Zugriff."""
        self.semantic_memory = semantic_memory

    # ------------------------------------------------------------------
    # Morgen-Briefing Integration
    # ------------------------------------------------------------------

    async def get_briefing_section(self, days_ahead: int = 0) -> str:
        """Liefert den persoenliche-Termine-Abschnitt fuers Morgen-Briefing.

        Args:
            days_ahead: Wie viele Tage vorausschauen (0 = Config-Default)
        """
        if not _ENABLED:
            return ""

        lookahead = days_ahead or _BRIEFING_LOOKAHEAD_DAYS
        upcoming = await self.get_upcoming_dates(lookahead)

        if not upcoming:
            return ""

        lines = []
        for entry in upcoming:
            days_until = entry["days_until"]
            person = entry.get("person", "Unbekannt")
            date_type = entry.get("date_type", "")
            label = entry.get("label", "")
            year = entry.get("year", "")

            # Typ-spezifische Bezeichnung
            type_text = _format_date_type(date_type, label)

            # Altersberechnung
            age_text = ""
            if year and date_type == "birthday":
                try:
                    birth_year = int(year)
                    now = datetime.now(timezone.utc)
                    age = now.year - birth_year
                    age_text = f" (wird {age})"
                except (ValueError, TypeError):
                    pass

            # Zeitangabe
            if days_until == 0:
                time_text = "HEUTE"
            elif days_until == 1:
                time_text = "morgen"
            else:
                time_text = f"in {days_until} Tagen"

            person_title = person.title() if person else "Unbekannt"
            lines.append(f"- {person_title}: {type_text}{age_text} {time_text}")

        return "Persoenliche Termine:\n" + "\n".join(lines)

    # ------------------------------------------------------------------
    # Daten-Abfrage
    # ------------------------------------------------------------------

    async def get_upcoming_dates(self, days_ahead: int = 7) -> list[dict]:
        """Findet anstehende persoenliche Termine.

        Returns:
            Liste von Dicts mit: person, date_type, date_mm_dd, year, label,
            content, days_until, fact_id
        """
        if not self.redis:
            return []

        # Alle personal_date Facts aus Redis laden
        fact_ids = await self.redis.smembers("mha:facts:category:personal_date")
        if not fact_ids:
            return []

        ids_list = []
        pipe = self.redis.pipeline()
        for fid in fact_ids:
            fid_str = fid if isinstance(fid, str) else fid.decode()
            ids_list.append(fid_str)
            pipe.hgetall(f"mha:fact:{fid_str}")
        all_data = await pipe.execute()

        now = datetime.now(timezone.utc)
        current_year = now.year
        results = []

        for fid, data in zip(ids_list, all_data):
            if not data:
                continue

            # Decode bytes
            decoded = {}
            for k, v in data.items():
                key = k if isinstance(k, str) else k.decode()
                val = v if isinstance(v, str) else v.decode()
                decoded[key] = val

            date_mm_dd = decoded.get("date_mm_dd", "")
            if not date_mm_dd:
                continue

            try:
                # Parse Datum (Format: MM-DD oder MM/DD)
                date_mm_dd_clean = date_mm_dd.replace("/", "-")
                target = datetime.strptime(
                    f"{current_year}-{date_mm_dd_clean}", "%Y-%m-%d"
                ).replace(tzinfo=timezone.utc)

                # Wenn Datum schon vorbei, naechstes Jahr nehmen
                if target.date() < now.date():
                    target = target.replace(year=current_year + 1)

                days_until = (target.date() - now.date()).days

                if days_until <= days_ahead:
                    results.append(
                        {
                            "fact_id": fid,
                            "person": decoded.get("person", ""),
                            "date_type": decoded.get("date_type", ""),
                            "date_mm_dd": date_mm_dd,
                            "year": decoded.get("date_year", decoded.get("year", "")),
                            "label": decoded.get(
                                "date_label", decoded.get("label", "")
                            ),
                            "content": decoded.get("content", ""),
                            "days_until": days_until,
                        }
                    )
            except (ValueError, TypeError) as e:
                logger.debug("Ungültiges Datum '%s': %s", date_mm_dd, e)
                continue

        return sorted(results, key=lambda r: r["days_until"])

    async def get_person_dates(self, person: str) -> list[dict]:
        """Findet alle gespeicherten Termine fuer eine Person."""
        if not self.redis:
            return []

        # Suche in person-Index
        fact_ids = await self.redis.smembers(f"mha:facts:person:{person.lower()}")
        if not fact_ids:
            return []

        results = []
        pipe = self.redis.pipeline()
        ids_list = []
        for fid in fact_ids:
            fid_str = fid if isinstance(fid, str) else fid.decode()
            ids_list.append(fid_str)
            pipe.hgetall(f"mha:fact:{fid_str}")
        all_data = await pipe.execute()

        for fid, data in zip(ids_list, all_data):
            if not data:
                continue
            decoded = {}
            for k, v in data.items():
                key = k if isinstance(k, str) else k.decode()
                val = v if isinstance(v, str) else v.decode()
                decoded[key] = val

            if decoded.get("category") == "personal_date":
                results.append(
                    {
                        "fact_id": fid,
                        "person": decoded.get("person", ""),
                        "date_type": decoded.get("date_type", ""),
                        "date_mm_dd": decoded.get("date_mm_dd", ""),
                        "year": decoded.get("date_year", decoded.get("year", "")),
                        "label": decoded.get("date_label", decoded.get("label", "")),
                        "content": decoded.get("content", ""),
                    }
                )

        return results

    # ------------------------------------------------------------------
    # Proaktive Erinnerungen
    # ------------------------------------------------------------------

    async def check_and_notify(self):
        """Prueft auf anstehende Termine und sendet Erinnerungen."""
        if not _ENABLED or not self._notify_callback:
            return

        max_days = max(_REMIND_DAYS_BEFORE) if _REMIND_DAYS_BEFORE else 3
        upcoming = await self.get_upcoming_dates(max_days)

        for entry in upcoming:
            days_until = entry["days_until"]
            if days_until not in _REMIND_DAYS_BEFORE:
                continue

            # Pruefen ob schon erinnert
            date_key = f"{entry['person']}:{entry['date_mm_dd']}:{days_until}"
            reminded_key = f"mha:personal_dates:reminded:{date_key}"

            if self.redis:
                already_reminded = await self.redis.exists(reminded_key)
                if already_reminded:
                    continue

            # Erinnerung senden
            message = self._format_reminder(entry)
            priority = "high" if days_until == 0 else "medium"

            try:
                await self._notify_callback(
                    message=message,
                    priority=priority,
                )
            except Exception as e:
                logger.warning("Fehler bei Geburtstags-Benachrichtigung: %s", e)
                continue

            # Als erinnert markieren (2 Tage TTL)
            if self.redis:
                await self.redis.set(reminded_key, "1", ex=172800)

    def _format_reminder(self, entry: dict) -> str:
        """Formatiert eine Erinnerungsnachricht."""
        days_until = entry["days_until"]
        person = entry.get("person", "").title()
        date_type = entry.get("date_type", "")
        label = entry.get("label", "")
        year = entry.get("year", "")

        type_text = _format_date_type(date_type, label)

        if days_until == 0:
            age_text = ""
            if year and date_type == "birthday":
                try:
                    age = datetime.now(timezone.utc).year - int(year)
                    age_text = f" {person} wird heute {age}!"
                except (ValueError, TypeError):
                    pass
            return f"Heute ist {person}s {type_text}!{age_text}"
        elif days_until == 1:
            return f"Erinnerung: Morgen ist {person}s {type_text}."
        else:
            return f"In {days_until} Tagen ist {person}s {type_text}."

    # ------------------------------------------------------------------
    # Background Loop
    # ------------------------------------------------------------------

    async def _check_loop(self):
        """Periodischer Check auf anstehende Termine."""
        # Erster Check nach 2 Minuten (System muss erst hochfahren)
        await asyncio.sleep(120)
        while True:
            try:
                await self.check_and_notify()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Fehler im PersonalDates Check: %s", e)
            await asyncio.sleep(_CHECK_INTERVAL_HOURS * 3600)

    async def shutdown(self):
        """Beendet den Check-Loop."""
        if self._check_task and not self._check_task.done():
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass

    async def stop(self):
        """Alias fuer shutdown (Brain-Kompatibilitaet)."""
        await self.shutdown()


# ------------------------------------------------------------------
# Hilfsfunktionen
# ------------------------------------------------------------------


def _format_date_type(date_type: str, label: str = "") -> str:
    """Formatiert den Typ eines persoenlichen Datums leserlich."""
    if label:
        return label
    type_map = {
        "birthday": "Geburtstag",
        "anniversary": "Jahrestag",
        "wedding": "Hochzeitstag",
        "memorial": "Gedenktag",
        "nameday": "Namenstag",
    }
    return type_map.get(date_type, date_type or "besonderer Tag")
