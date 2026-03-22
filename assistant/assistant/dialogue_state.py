"""
Dialogue State Manager - Echte Dialogfuehrung mit Referenz-Aufloesung.

Medium Effort Feature: Tracked den Gespraechszustand, loest Referenzen auf
("es", "das", "dort", "den gleichen") und verwaltet Klaerungsfragen.

C5: Cross-Session Intent-Referenzierung — "wie gestern", "wie letzte Woche"
durchsucht das Action-Log in Redis.

Zustaende:
- idle: Kein aktiver Dialog
- awaiting_clarification: Wartet auf Antwort zu Klaerungsfrage
- follow_up: User bezieht sich auf vorherige Aktion
- multi_step: Mehrstufiger Dialog (z.B. Szene erstellen)

Konfigurierbar in der Jarvis Assistant UI unter "Intelligenz".
"""

import asyncio
import json
import logging
import re
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional

from .config import yaml_config

logger = logging.getLogger(__name__)

# Referenz-Woerter die auf vorherige Entitaeten/Raeume verweisen
ENTITY_REFERENCES_DE = {
    "es",
    "das",
    "den",
    "die",
    "ihn",
    "ihm",
    "ihr",
    "dem",
    "das gleiche",
    "den gleichen",
    "die gleiche",
    "dasselbe",
    "das licht",
    "die lampe",
    "das ding",
}

ROOM_REFERENCES_DE = {
    "dort",
    "da",
    "dahin",
    "drin",
    "dorthin",
    "im gleichen raum",
    "im selben raum",
    "da drin",
    "hier",  # bezieht sich auf aktuellen Raum
}

ACTION_REFERENCES_DE = {
    "nochmal",
    "das gleiche",
    "genauso",
    "wieder",
    "auch",
    "ebenfalls",
    "dasselbe",
}

# C5: Temporale Referenzen fuer cross-session Aktionen
TEMPORAL_REFERENCES_DE = {
    "wie gestern": timedelta(days=1),
    "wie vorgestern": timedelta(days=2),
    "wie letzte woche": timedelta(days=7),
    "wie letzten freitag": timedelta(days=7),  # Approximation
    "wie letztes mal": timedelta(days=3),
    "wie vorher": timedelta(hours=4),
    "wie vorhin": timedelta(hours=2),
    "wie heute morgen": timedelta(hours=8),
    "wie heute nacht": timedelta(hours=12),
    "wie eben": timedelta(minutes=30),
    "wie gerade": timedelta(minutes=15),
    "wie am montag": timedelta(days=7),
    "wie am dienstag": timedelta(days=7),
    "wie am mittwoch": timedelta(days=7),
    "wie am donnerstag": timedelta(days=7),
    "wie am freitag": timedelta(days=7),
    "wie am samstag": timedelta(days=7),
    "wie am sonntag": timedelta(days=7),
    "wie am wochenende": timedelta(days=7),
    "wie immer": timedelta(days=7),  # Sucht in den letzten 7 Tagen
}

# Klaerungsmuster: "Welches X?" Antworten die eine Auswahl treffen
CLARIFICATION_ANSWER_PATTERNS = [
    r"^(das |die |den )?(im |in der |in |am )?\w+$",  # "im Buero", "Wohnzimmer"
    r"^(ja|nein|doch|ok|okay)$",
    r"^\d+$",  # Nummerische Antwort
    r"^(erst|zweit|dritt|viert|letzt)(e[rns]?)?$",  # "das erste", "den zweiten"
]


class DialogueState:
    """Speichert den Zustand eines laufenden Dialogs."""

    def __init__(self, max_references: int = 20):
        self.state: str = "idle"  # idle, awaiting_clarification, follow_up, multi_step
        self.last_entities: deque[str] = deque(maxlen=max_references)
        self.last_rooms: deque[str] = deque(maxlen=3)
        self.last_actions: deque[dict] = deque(maxlen=5)
        self.last_domains: deque[str] = deque(maxlen=3)
        self.pending_clarification: Optional[dict] = None
        self.multi_step_context: Optional[dict] = None
        self.last_update: float = time.time()
        self.turn_count: int = 0
        self._last_turn_words: set[str] = set()  # MCU Sprint 2: Topic-Switch-Detection

    def is_stale(self, timeout_seconds: int = 300) -> bool:
        """Prueft ob der Dialog-Zustand veraltet ist."""
        return (time.time() - self.last_update) > timeout_seconds

    def reset(self):
        """Setzt den Zustand zurueck.

        Behält last_entities und last_rooms fuer Kontext-Kontinuitaet,
        da diese auch nach Pausen relevant sein koennen ('das Licht'
        bezieht sich oft auf den zuletzt besprochenen Raum).
        """
        self.state = "idle"
        self.pending_clarification = None
        self.multi_step_context = None
        self.turn_count = 0
        # last_entities, last_rooms, last_actions, last_domains bleiben erhalten

    def to_dict(self) -> dict:
        """Serialisiert den Zustand fuer Debug/API."""
        return {
            "state": self.state,
            "last_entities": list(self.last_entities),
            "last_rooms": list(self.last_rooms),
            "last_actions": list(self.last_actions),
            "last_domains": list(self.last_domains),
            "turn_count": self.turn_count,
            "pending_clarification": self.pending_clarification,
            "age_seconds": round(time.time() - self.last_update),
        }


class DialogueStateManager:
    """Verwaltet Dialog-Zustaende pro Person und loest Referenzen auf."""

    def __init__(self):
        cfg = yaml_config.get("dialogue", {})
        self.enabled = cfg.get("enabled", True)
        self.timeout_seconds = cfg.get("timeout_seconds", 600)
        self.auto_resolve_references = cfg.get("auto_resolve_references", True)
        self.clarification_enabled = cfg.get("clarification_enabled", True)
        self.max_clarification_options = cfg.get("max_clarification_options", 5)
        self.max_references = cfg.get("max_references", 20)
        self.clarification_timeout = cfg.get("clarification_timeout_seconds", 300)

        # Per-Person Dialog-Zustaende
        self._states: dict[str, DialogueState] = {}

        # C5: Redis-Client fuer cross-session Referenzierung
        self._redis = None

    def set_redis(self, redis_client):
        """C5: Setzt Redis-Client fuer Action-Log Zugriff."""
        self._redis = redis_client

    def _get_state(self, person: str = "") -> DialogueState:
        """Gibt den Dialog-Zustand fuer eine Person zurueck."""
        key = (person or "_default").lower()
        if key not in self._states:
            # Evict oldest entries if dict grows too large
            if len(self._states) > 50:
                oldest = sorted(
                    self._states,
                    key=lambda k: (
                        self._states[k].last_update
                        if hasattr(self._states[k], "last_update")
                        else 0
                    ),
                )[:25]
                for old_key in oldest:
                    del self._states[old_key]
            self._states[key] = DialogueState(max_references=self.max_references)
        state = self._states[key]
        # Stale-Check: Zustand zuruecksetzen wenn zu alt
        if state.is_stale(self.timeout_seconds):
            state.reset()
        return state

    def track_turn(
        self,
        text: str,
        person: str = "",
        room: str = "",
        entities: list[str] = None,
        actions: list[dict] = None,
        domain: str = "",
    ):
        """Trackt einen Dialog-Turn (nach LLM-Antwort).

        Args:
            text: User-Text
            person: Person
            room: Raum
            entities: Betroffene Entities (z.B. ["light.wohnzimmer"])
            actions: Ausgefuehrte Aktionen
            domain: Domaene (light, climate, etc.)
        """
        if not self.enabled:
            return

        state = self._get_state(person)
        state.last_update = time.time()
        state.turn_count += 1

        # MCU Sprint 2: Topic-Switch-Detection via Jaccard word overlap
        # Erweitert: Semantische Verfeinerungen und Domain-Kontinuitaet
        # verhindern falsche Topic-Switch-Erkennung bei Multi-Turn-Reasoning.
        if text and state.turn_count > 1 and state._last_turn_words:
            _reference_words = {
                "es",
                "das",
                "die",
                "der",
                "den",
                "dem",
                "dort",
                "da",
                "hier",
                "nochmal",
                "auch",
                "wieder",
                "genau",
                "gleich",
                "selbe",
            }
            # Semantische Verfeinerungs-Signale: Wenn der User den vorherigen
            # Befehl verfeinert/korrigiert, ist es KEIN Topic-Switch.
            _refinement_words = {
                # Komparative (deutsch)
                "heller", "dunkler", "waermer", "kaelter", "lauter", "leiser",
                "schneller", "langsamer", "mehr", "weniger", "staerker",
                "schwaecher", "hoeher", "niedriger", "groesser", "kleiner",
                # Korrekturen
                "nein", "nicht", "falsch", "anders", "doch", "stattdessen",
                "lieber", "eigentlich", "besser", "richtig",
                # Verfeinerungen
                "bisschen", "etwas", "viel", "ganz", "komplett", "halb",
                "nur", "noch", "aber", "bitte", "dazu", "ausserdem",
                "zusaetzlich", "trotzdem", "weil",
            }
            _acknowledgments = {
                "ok",
                "okay",
                "ja",
                "nein",
                "gut",
                "danke",
                "alles klar",
                "passt",
                "mhm",
                "jep",
                "nö",
                "klar",
            }
            current_words = set(text.lower().split()) - _reference_words
            prev_words = state._last_turn_words
            # Skip topic-switch for short utterances (acknowledgments, greetings, 1-word turns)
            _is_ack = (
                text.lower().strip() in _acknowledgments or len(current_words) <= 1
            )
            _prev_too_short = len(prev_words) <= 1
            if current_words and prev_words and not _is_ack and not _prev_too_short:
                intersection = current_words & prev_words
                union = current_words | prev_words
                jaccard = len(intersection) / len(union) if union else 0
                has_reference = bool(set(text.lower().split()) & _reference_words)

                # Verfeinerungs-Check: Enthaelt der Turn Verfeinerungs-Signale?
                has_refinement = bool(
                    set(text.lower().split()) & _refinement_words
                )

                # Domain-Kontinuitaet: Wenn der User Woerter aus derselben Domain
                # verwendet wie im letzten Turn, ist es wahrscheinlich kein Switch.
                _domain_continuity = False
                if state.last_domains:
                    _last_domain = state.last_domains[0] if state.last_domains else ""
                    _domain_keywords = {
                        "light": {"licht", "lampe", "hell", "dunkel", "dimm", "leucht", "bright"},
                        "climate": {"heiz", "temp", "warm", "kalt", "grad", "klima", "thermostat"},
                        "cover": {"rollladen", "rolladen", "rollo", "jalousie", "hoch", "runter"},
                        "media": {"musik", "laut", "leise", "song", "play", "pause", "stopp"},
                    }
                    _kws = _domain_keywords.get(_last_domain, set())
                    if _kws and any(
                        kw in text.lower() for kw in _kws
                    ):
                        _domain_continuity = True

                if jaccard < 0.1 and not has_reference and not has_refinement and not _domain_continuity:
                    logger.info(
                        "Topic-Switch erkannt (Jaccard=%.2f): '%s'",
                        jaccard,
                        text[:60],
                    )
                    state.reset()
                    state.last_update = time.time()
                    state.turn_count = 1  # Restart count after reset

        # Update last turn words for next comparison
        if text:
            _stop = {
                "ich",
                "du",
                "ein",
                "eine",
                "einer",
                "und",
                "oder",
                "ist",
                "sind",
                "hat",
                "habe",
                "der",
                "die",
                "das",
                "den",
                "dem",
                "in",
                "im",
                "am",
                "an",
                "auf",
                "zu",
                "für",
                "fuer",
                "mit",
                "von",
                "nicht",
                "kein",
                "keine",
                "ja",
                "nein",
                "bitte",
                "danke",
                "mal",
                "noch",
                "schon",
            }
            state._last_turn_words = set(text.lower().split()) - _stop

        if room:
            # Duplikate vermeiden, neueste zuerst
            if room.lower() not in state.last_rooms:
                state.last_rooms.appendleft(room.lower())

        if entities:
            for ent in entities:
                if ent not in state.last_entities:
                    state.last_entities.appendleft(ent)

        if actions:
            for act in actions:
                state.last_actions.appendleft(act)

        if domain:
            if domain not in state.last_domains:
                state.last_domains.appendleft(domain)

        # Klaerungsfrage aufloesen wenn beantwortet
        if state.state == "awaiting_clarification":
            state.state = "follow_up"
            state.pending_clarification = None

        # Cross-Session Referenzen in Redis speichern (fire-and-forget)
        if self._redis:
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(self._save_important_references(person))
                task.add_done_callback(
                    lambda t: (
                        logger.warning(
                            "save_important_references failed: %s", t.exception()
                        )
                        if not t.cancelled() and t.exception()
                        else None
                    )
                )
            except RuntimeError:
                pass  # Kein laufender Event-Loop

    def resolve_references(
        self, text: str, person: str = "", current_room: str = ""
    ) -> dict:
        """Loest Referenzen im User-Text auf.

        Erkennt Pronomen/Referenzen und ersetzt sie durch konkrete Entities/Raeume.

        Args:
            text: User-Text (z.B. "Mach es aus")
            person: Person
            current_room: Aktueller Raum (fuer "hier")

        Returns:
            Dict mit:
                resolved_text: Text mit aufgeloesten Referenzen
                had_references: bool
                resolved_entities: list
                resolved_rooms: list
                context_hint: str (fuer LLM-Prompt)
        """
        if not self.enabled or not self.auto_resolve_references:
            return {
                "resolved_text": text,
                "had_references": False,
                "resolved_entities": [],
                "resolved_rooms": [],
                "context_hint": "",
            }

        state = self._get_state(person)
        text_lower = text.lower().strip()
        resolved_entities = []
        resolved_rooms = []
        had_references = False
        hints = []

        # Entity-Referenzen aufloesen ("mach es aus", "schalte das ein")
        for ref in ENTITY_REFERENCES_DE:
            if re.search(r"\b" + re.escape(ref) + r"\b", text_lower):
                if state.last_entities:
                    last_ent = state.last_entities[0]
                    resolved_entities.append(last_ent)
                    had_references = True
                    hints.append(f"'{ref}' bezieht sich vermutlich auf: {last_ent}")
                    break

        # Raum-Referenzen aufloesen ("mach dort das Licht an")
        for ref in ROOM_REFERENCES_DE:
            if re.search(r"\b" + re.escape(ref) + r"\b", text_lower):
                if ref == "hier" and current_room:
                    resolved_rooms.append(current_room)
                    had_references = True
                    hints.append(f"'hier' = {current_room}")
                elif state.last_rooms:
                    last_room = state.last_rooms[0]
                    resolved_rooms.append(last_room)
                    had_references = True
                    hints.append(f"'{ref}' bezieht sich auf: {last_room}")
                break

        # Aktions-Referenzen ("nochmal", "das gleiche", "auch im Buero")
        for ref in ACTION_REFERENCES_DE:
            if (
                re.search(r"\b" + re.escape(ref) + r"\b", text_lower)
                and state.last_actions
            ):
                last_action = state.last_actions[0]
                had_references = True
                hints.append(
                    f"'{ref}' bezieht sich auf letzte Aktion: {last_action.get('description', str(last_action))}"
                )
                break

        # C5: Temporale Referenzen ("wie gestern", "wie letzte Woche")
        _cross_cfg = yaml_config.get("cross_session_references", {})
        if _cross_cfg.get("enabled", True):
            temporal_hint = self._resolve_temporal_reference(text_lower, person)
            if temporal_hint:
                had_references = True
                hints.append(temporal_hint)

        context_hint = ""
        if hints:
            context_hint = "Referenz-Aufloesung: " + ". ".join(hints) + "."

        return {
            "resolved_text": text,  # Original-Text bleibt, Kontext geht ans LLM
            "had_references": had_references,
            "resolved_entities": resolved_entities,
            "resolved_rooms": resolved_rooms,
            "context_hint": context_hint,
        }

    # ------------------------------------------------------------------
    # C5: Cross-Session Temporale Referenzierung
    # ------------------------------------------------------------------

    def _resolve_temporal_reference(self, text_lower: str, person: str = "") -> str:
        """Loest temporale Referenzen wie 'wie gestern' ueber das Action-Log auf.

        Durchsucht mha:action_outcomes in Redis nach Aktionen die zum
        Zeitfenster passen und gibt einen Kontext-Hint zurueck.
        """
        if not self._redis:
            return ""

        matched_ref = ""
        matched_delta = None

        for ref_text, delta in TEMPORAL_REFERENCES_DE.items():
            if ref_text in text_lower:
                matched_ref = ref_text
                matched_delta = delta
                break

        # Wochentag-spezifische Referenzen ("wie am Montag")
        if not matched_ref:
            weekday_map = {
                "montag": 0,
                "dienstag": 1,
                "mittwoch": 2,
                "donnerstag": 3,
                "freitag": 4,
                "samstag": 5,
                "sonntag": 6,
            }
            for day_name, day_num in weekday_map.items():
                pattern = f"wie am {day_name}"
                if pattern in text_lower or f"wie letzten {day_name}" in text_lower:
                    today = datetime.now(timezone.utc).weekday()
                    days_ago = (today - day_num) % 7
                    if days_ago == 0:
                        days_ago = 7
                    matched_ref = pattern
                    matched_delta = timedelta(days=days_ago)
                    break

        if not matched_ref or not matched_delta:
            return ""

        # Synchroner Redis-Zugriff ist hier nicht moeglich (resolve_references ist sync).
        # Stattdessen: Cached Action-Log nutzen falls vorhanden.
        try:
            cached = self._get_cached_action_log()
            if not cached:
                return ""

            now = datetime.now(timezone.utc)
            target_time = now - matched_delta
            # Zeitfenster: +/- 2 Stunden um den Zielzeitpunkt
            window_start = target_time - timedelta(hours=2)
            window_end = target_time + timedelta(hours=2)
            # Fuer "wie immer": Breites Fenster (letzte 7 Tage)
            if matched_ref == "wie immer":
                window_start = now - timedelta(days=7)
                window_end = now

            matching_actions = []
            for entry in cached:
                try:
                    ts_str = entry.get("timestamp", "")
                    if not ts_str:
                        continue
                    ts = datetime.fromisoformat(ts_str)
                    if window_start <= ts <= window_end:
                        action = entry.get("action", entry.get("function", ""))
                        desc = entry.get("description", action)
                        if action and entry.get("success", True):
                            matching_actions.append(desc)
                except (ValueError, TypeError):
                    continue

            if matching_actions:
                # Deduplizieren und max 3 Aktionen zeigen
                unique = list(dict.fromkeys(matching_actions))[:3]
                actions_str = ", ".join(unique)
                return f"'{matched_ref}' referenziert fruehere Aktionen: {actions_str}"

        except Exception as e:
            logger.debug("C5 Temporal Reference Fehler: %s", e)

        return ""

    def _get_cached_action_log(self) -> list[dict]:
        """Laedt das Action-Log aus dem internen Cache.

        Da resolve_references() synchron ist, kann kein async Redis-Call
        gemacht werden. Stattdessen wird der Cache von set_action_log_cache()
        genutzt, der von brain.py periodisch befuellt wird.
        """
        return getattr(self, "_action_log_cache", [])

    def set_action_log_cache(self, entries: list[dict]):
        """C5: Setzt den Action-Log Cache (von brain.py aufgerufen)."""
        self._action_log_cache = entries

    async def resolve_temporal_reference_async(
        self, text_lower: str, person: str = ""
    ) -> str:
        """Async Version: Loest temporale Referenzen per direktem Redis-Zugriff auf.

        Faellt auf die cached Version zurueck wenn Redis nicht verfuegbar ist.
        """
        if not self._redis:
            return self._resolve_temporal_reference(text_lower, person)

        matched_ref = ""
        matched_delta = None

        for ref_text, delta in TEMPORAL_REFERENCES_DE.items():
            if ref_text in text_lower:
                matched_ref = ref_text
                matched_delta = delta
                break

        if not matched_ref or not matched_delta:
            return ""

        try:
            now = datetime.now(timezone.utc)
            target_time = now - matched_delta
            window_start = target_time - timedelta(hours=2)
            window_end = target_time + timedelta(hours=2)
            if matched_ref == "wie immer":
                window_start = now - timedelta(days=7)
                window_end = now

            # Redis Action-Outcomes direkt abfragen
            raw = await self._redis.lrange("mha:action_outcomes", 0, 199)
            matching_actions = []
            for entry_raw in raw:
                try:
                    entry_str = (
                        entry_raw.decode()
                        if isinstance(entry_raw, bytes)
                        else entry_raw
                    )
                    entry = json.loads(entry_str)
                    ts_str = entry.get("timestamp", "")
                    if not ts_str:
                        continue
                    ts = datetime.fromisoformat(ts_str)
                    if window_start <= ts <= window_end:
                        # Person-Filter wenn angegeben
                        if (
                            person
                            and entry.get("person", "")
                            and entry.get("person", "").lower() != person.lower()
                        ):
                            continue
                        action = entry.get("action", entry.get("function", ""))
                        desc = entry.get("description", action)
                        if action and entry.get("success", True):
                            matching_actions.append(desc)
                except (ValueError, TypeError, json.JSONDecodeError):
                    continue

            if matching_actions:
                unique = list(dict.fromkeys(matching_actions))[:3]
                actions_str = ", ".join(unique)
                return f"'{matched_ref}' referenziert fruehere Aktionen: {actions_str}"

        except Exception as e:
            logger.debug("C5 Async Temporal Reference Fehler: %s", e)
            # Fall back to cached version
            return self._resolve_temporal_reference(text_lower, person)

        return ""

    # ------------------------------------------------------------------
    # Cross-Session Reference Speicherung
    # ------------------------------------------------------------------

    _XREF_KEY = "mha:dialogue:references"  # Hash: person -> JSON

    async def _save_important_references(self, person: str = "") -> None:
        """Speichert wichtige Referenzen in Redis fuer Cross-Session Zugriff.

        Wird nach jedem track_turn aufgerufen, damit Entitaeten und
        Raeume ueber Session-Grenzen hinweg verfuegbar bleiben.
        """
        if not self._redis:
            return

        state = self._get_state(person)
        key = (person or "_default").lower()

        try:
            ref_data = json.dumps(
                {
                    "entities": list(state.last_entities)[:10],
                    "rooms": list(state.last_rooms),
                    "actions": [
                        {
                            "action": a.get("action", a.get("function", "")),
                            "description": a.get("description", "")[:100],
                        }
                        for a in list(state.last_actions)[:3]
                    ],
                    "domains": list(state.last_domains),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
            )

            await self._redis.hset(self._XREF_KEY, key, ref_data)
            await self._redis.expire(self._XREF_KEY, 14 * 86400)  # 14 Tage TTL
        except Exception as e:
            logger.debug("Cross-Session Referenz-Save Fehler: %s", e)

    async def _resolve_cross_session(self, text_lower: str, person: str = "") -> str:
        """Loest Referenzen aus frueheren Sessions auf.

        Wenn der aktuelle In-Memory State leer ist (neue Session),
        werden gespeicherte Referenzen aus Redis geladen.

        Returns:
            Context-Hint fuer das LLM oder leerer String.
        """
        if not self._redis:
            return ""

        state = self._get_state(person)

        # Nur laden wenn In-Memory State leer ist (neue Session)
        if state.last_entities or state.last_rooms:
            return ""

        # Pronomen/Referenz-Check
        has_reference = False
        for ref in ENTITY_REFERENCES_DE:
            if ref in text_lower:
                has_reference = True
                break
        if not has_reference:
            for ref in ROOM_REFERENCES_DE:
                if ref in text_lower:
                    has_reference = True
                    break
        if not has_reference:
            for ref in ACTION_REFERENCES_DE:
                if ref in text_lower:
                    has_reference = True
                    break

        if not has_reference:
            return ""

        try:
            key = (person or "_default").lower()
            raw = await self._redis.hget(self._XREF_KEY, key)
            if not raw:
                return ""

            data_str = raw.decode() if isinstance(raw, bytes) else raw
            data = json.loads(data_str)

            entities = data.get("entities", [])
            rooms = data.get("rooms", [])

            # In-Memory State wiederherstellen
            for ent in reversed(entities):
                if ent not in state.last_entities:
                    state.last_entities.appendleft(ent)
            for room in reversed(rooms):
                if room not in state.last_rooms:
                    state.last_rooms.appendleft(room)
            for domain in reversed(data.get("domains", [])):
                if domain not in state.last_domains:
                    state.last_domains.appendleft(domain)

            hints = []
            if entities:
                hints.append(
                    f"Letzte Entitaeten (Cross-Session): {', '.join(entities[:3])}"
                )
            if rooms:
                hints.append(f"Letzte Raeume: {', '.join(rooms[:3])}")

            if hints:
                return " | ".join(hints)
        except Exception as e:
            logger.debug("Cross-Session Referenz-Resolve Fehler: %s", e)

        return ""

    def start_clarification(
        self,
        person: str,
        question: str,
        options: list[str],
        original_text: str,
        domain: str = "",
    ):
        """Startet eine Klaerungsfrage ("Welches Licht?").

        Args:
            person: Person
            question: Klaerungsfrage
            options: Moegliche Antworten
            original_text: Urspruenglicher User-Text
            domain: Domaene
        """
        if not self.enabled or not self.clarification_enabled:
            return

        state = self._get_state(person)
        state.state = "awaiting_clarification"
        state.pending_clarification = {
            "question": question,
            "options": options[: self.max_clarification_options],
            "original_text": original_text,
            "domain": domain,
            "timestamp": time.time(),
        }
        state.last_update = time.time()
        logger.info(
            "Klaerungsfrage gestartet: '%s' (Optionen: %s)", question, options[:3]
        )

    def check_clarification_answer(self, text: str, person: str = "") -> Optional[dict]:
        """Prueft ob der Text eine Antwort auf eine Klaerungsfrage ist.

        Args:
            text: User-Text
            person: Person

        Returns:
            Dict mit original_text, selected_option, domain wenn Klaerung aufgeloest,
            None wenn keine Klaerung pending oder Text keine Antwort ist.
        """
        if not self.enabled:
            return None

        state = self._get_state(person)
        if state.state != "awaiting_clarification" or not state.pending_clarification:
            return None

        clarification = state.pending_clarification

        # Timeout check
        age = time.time() - clarification.get("timestamp", 0)
        if age > self.clarification_timeout:
            logger.debug("Klaerungsfrage timeout nach %.0fs", age)
            state.pending_clarification = None
            state.state = "idle"
            return None

        text_lower = text.lower().strip()

        # Direkte Option-Auswahl (z.B. "Wohnzimmer" wenn Optionen [Wohnzimmer, Buero, ...])
        for opt in clarification["options"]:
            if opt.lower() in text_lower or text_lower in opt.lower():
                state.state = "follow_up"
                result = {
                    "original_text": clarification["original_text"],
                    "selected_option": opt,
                    "domain": clarification.get("domain", ""),
                    "clarification_question": clarification["question"],
                }
                state.pending_clarification = None
                return result

        # Kurze Antwort die auf eine Klaerung hindeuten koennte
        for pattern in CLARIFICATION_ANSWER_PATTERNS:
            if re.match(pattern, text_lower):
                state.state = "follow_up"
                result = {
                    "original_text": clarification["original_text"],
                    "selected_option": text,
                    "domain": clarification.get("domain", ""),
                    "clarification_question": clarification["question"],
                    "was_pattern_match": True,
                }
                state.pending_clarification = None
                return result

        # Kein Match — Klaerung aufgeben, Text normal verarbeiten
        state.pending_clarification = None
        state.state = "idle"
        return None

    def get_context_prompt(self, person: str = "", current_room: str = "") -> str:
        """Gibt den Dialog-Kontext als Prompt-Hinweis zurueck.

        Wird in den System-Prompt eingebaut fuer kontextbewusste Antworten.
        """
        if not self.enabled:
            return ""

        state = self._get_state(person)
        if state.turn_count == 0:
            return ""

        hints = []

        if state.last_entities:
            ents = ", ".join(list(state.last_entities)[:3])
            hints.append(f"Zuletzt besprochene Geraete: {ents}")

        if state.last_rooms:
            rooms = ", ".join(list(state.last_rooms)[:2])
            hints.append(f"Zuletzt besprochene Raeume: {rooms}")

        if state.last_actions:
            last = state.last_actions[0]
            desc = last.get("description", str(last))
            hints.append(f"Letzte Aktion: {desc}")

        if state.state == "awaiting_clarification" and state.pending_clarification:
            q = state.pending_clarification["question"]
            hints.append(f"OFFENE KLAERUNGSFRAGE: {q}")

        return " | ".join(hints) if hints else ""

    def get_state_info(self, person: str = "") -> dict:
        """Gibt den aktuellen Dialog-Zustand zurueck (fuer API/Debug)."""
        state = self._get_state(person)
        return state.to_dict()

    def needs_clarification(
        self, text: str, entities: list[str], person: str = ""
    ) -> Optional[dict]:
        """Prueft ob eine Klaerungsfrage noetig ist.

        Z.B. wenn "Mach das Licht an" in einem Raum mit 5 Lichtern gesagt wird.

        Args:
            text: User-Text
            entities: Gefundene Entities die passen koennten
            person: Person

        Returns:
            Dict mit question, options wenn Klaerung noetig, None sonst.
        """
        if not self.enabled or not self.clarification_enabled:
            return None

        # Klaerung nur wenn mehrere Entities matchen und der Text vage ist
        if len(entities) <= 1:
            return None

        # Wenn der Text schon spezifisch genug ist, keine Klaerung
        text_lower = text.lower()
        specificity_markers = [
            "alle",
            "alles",
            "komplett",
            "ueberall",
            "jede",
            "jeden",
            "zusammen",
            "gleichzeitig",
        ]
        if any(m in text_lower for m in specificity_markers):
            return None

        # Max. Optionen begrenzen
        options = entities[: self.max_clarification_options]

        return {
            "question": f"Welches meinst du? ({', '.join(options[:3])}{'...' if len(options) > 3 else ''})",
            "options": options,
        }

    # ------------------------------------------------------------------
    # Phase 6: Erweiterte Dialogfuehrung
    # ------------------------------------------------------------------

    def get_conversation_depth(self, person: str = "") -> int:
        """Gibt die Gespraechstiefe (Anzahl Turns) fuer eine Person zurueck."""
        state = self._get_state(person)
        return state.turn_count

    def get_topic_continuity(self, text: str, person: str = "") -> dict:
        """Prueft ob der aktuelle Text thematisch zum bisherigen Gespraech passt.

        Returns:
            Dict mit is_continuation, confidence, suggested_context
        """
        state = self._get_state(person)

        if state.turn_count == 0:
            return {
                "is_continuation": False,
                "confidence": 0.0,
                "suggested_context": "",
            }

        text_lower = text.lower()

        # Explizite Topic-Wechsel-Marker
        topic_switch_markers = [
            "anderes thema",
            "etwas anderes",
            "uebrigens",
            "ach ja",
            "mal was anderes",
            "andere frage",
            "neues thema",
        ]
        if any(m in text_lower for m in topic_switch_markers):
            return {
                "is_continuation": False,
                "confidence": 0.9,
                "suggested_context": "",
            }

        # Continuation-Marker
        continuation_markers = [
            "und",
            "ausserdem",
            "noch",
            "auch",
            "dazu",
            "was ist mit",
            "wie waere es mit",
            "kannst du auch",
            "und was",
            "und wie",
            "noch eine",
        ]

        is_cont = any(text_lower.startswith(m) for m in continuation_markers)
        # Wenn Domain gleich bleibt → wahrscheinlich Continuation
        if state.last_domains:
            last_domain = state.last_domains[-1] if state.last_domains else ""
            if last_domain:
                is_cont = True

        context = ""
        if is_cont and state.last_entities:
            context = f"Bezieht sich auf: {', '.join(list(state.last_entities)[-2:])}"
        if is_cont and state.last_rooms:
            room = state.last_rooms[-1]
            context += f" (Raum: {room})" if context else f"Raum: {room}"

        return {
            "is_continuation": is_cont,
            "confidence": 0.7 if is_cont else 0.3,
            "suggested_context": context,
        }

    def get_implicit_context(self, person: str = "") -> str:
        """Gibt impliziten Kontext zurueck fuer bessere Antwortgenerierung.

        Z.B. wenn User nacheinander "Mach Licht an" → "Auch im Flur" sagt,
        wird der Raum-Kontext aus der vorherigen Interaktion uebernommen.
        """
        state = self._get_state(person)
        if state.is_stale(self.timeout_seconds) or state.turn_count == 0:
            return ""

        parts = []
        if state.last_rooms:
            rooms = list(state.last_rooms)
            parts.append(f"Letzte Raeume: {', '.join(rooms)}")
        if state.last_entities:
            ents = list(state.last_entities)[-3:]
            parts.append(f"Letzte Geraete: {', '.join(ents)}")
        if state.last_actions:
            last = state.last_actions[-1]
            action_name = last.get("action", "unbekannt")
            parts.append(f"Letzte Aktion: {action_name}")
        if state.state == "awaiting_clarification" and state.pending_clarification:
            parts.append(
                f"Offene Frage: {state.pending_clarification.get('question', '')}"
            )

        return " | ".join(parts) if parts else ""

    def suggest_follow_up(self, action_result: dict, person: str = "") -> str:
        """Schlaegt eine Follow-Up-Frage basierend auf der letzten Aktion vor.

        Args:
            action_result: Ergebnis der letzten Aktion
            person: Person

        Returns:
            Vorgeschlagene Follow-Up-Frage oder leerer String
        """
        state = self._get_state(person)
        if state.turn_count < 2:
            return ""

        # Nur bei erfolgreichen Aktionen
        if not action_result.get("success", False):
            return ""

        last_actions = list(state.last_actions)
        if not last_actions:
            return ""

        last = last_actions[-1]
        action = last.get("action", "")

        # Pattern-basierte Vorschlaege
        if action == "set_light" and last.get("args", {}).get("state") == "on":
            return "Soll ich die Helligkeit oder Farbe anpassen?"
        if action == "set_climate":
            return "Soll ich die Temperatur in anderen Raeumen auch anpassen?"
        if action == "play_media":
            return "Soll ich die Lautstaerke anpassen?"
        if action == "set_cover" and last.get("args", {}).get("state") == "closed":
            return "Soll ich auch das Licht anmachen?"

        return ""

    # ------------------------------------------------------------------
    # Phase 6A: Ellipsis, Negation, Ambiguity Ranking, Discourse Repair
    # ------------------------------------------------------------------

    def _resolve_ellipsis(self, text: str, person: str = "") -> str:
        """Loest elliptische Ausdruecke auf indem Kontext aus vorherigen Turns uebernommen wird.

        Wenn der Text mit 'Und ', 'Auch ' oder 'Dort ' beginnt, wird der zuletzt
        besprochene Raum bzw. die letzte Entity als Kontext ergaenzt.

        Returns:
            Angereicherter Text mit Kontext-Informationen.
        """
        text_stripped = text.strip()
        text_lower = text_stripped.lower()
        state = self._get_state(person)

        prefixes = {"und ": True, "auch ": True, "dort ": True}
        matched_prefix = None
        for prefix in prefixes:
            if text_lower.startswith(prefix):
                matched_prefix = prefix
                break

        if not matched_prefix:
            return text

        context_parts = []
        if state.last_rooms:
            context_parts.append(f"(Raum: {state.last_rooms[0]})")
        if state.last_entities:
            context_parts.append(f"(Geraet: {state.last_entities[0]})")

        if context_parts:
            return f"{text_stripped} {' '.join(context_parts)}"
        return text

    def _track_negation(self, text: str, person: str = "") -> Optional[str]:
        """Erkennt Negationsmuster und speichert die negierte Entity im State.

        Erkennt Muster wie 'nicht das Licht', 'kein Licht', 'nein, nicht die Lampe'.

        Returns:
            Die negierte Entity oder None wenn keine Negation erkannt wurde.
        """
        text_lower = text.lower().strip()
        state = self._get_state(person)

        negation_patterns = [
            r"(?:nicht|kein(?:e[rns]?)?|nein)\s+(?:das |die |den |der )?(\w+)",
        ]

        for pattern in negation_patterns:
            match = re.search(pattern, text_lower)
            if match:
                negated_entity = match.group(1).strip()
                if not hasattr(state, "negated_entities"):
                    state.negated_entities = []
                state.negated_entities = [negated_entity] + getattr(
                    state, "negated_entities", []
                )
                state.negated_entities = state.negated_entities[:5]
                logger.debug("Negation erkannt: '%s'", negated_entity)
                return negated_entity

        return None

    def _rank_ambiguity(
        self, entities: list[str], text: str, person: str = ""
    ) -> list[tuple[str, float]]:
        """Rankt mehrdeutige Entities nach Relevanz.

        Bewertet anhand von:
        - Kuerzliche Nutzung (zuletzt besprochene Entities bevorzugt)
        - Raum-Match (Entity im aktuellen Raum bevorzugt)
        - Namens-Aehnlichkeit zum User-Text

        Returns:
            Liste von (entity, confidence_score) Tupeln, absteigend nach Score.
        """
        state = self._get_state(person)
        text_lower = text.lower()
        scored: list[tuple[str, float]] = []

        recent_entities = list(state.last_entities)
        recent_rooms = list(state.last_rooms)

        for entity in entities:
            score = 0.5  # Basis-Score
            entity_lower = entity.lower()

            # Bonus fuer kuerzliche Nutzung (absteigend nach Aktualitaet)
            for idx, recent in enumerate(recent_entities):
                if recent.lower() == entity_lower:
                    score += max(0.3 - idx * 0.05, 0.05)
                    break

            # Bonus fuer Raum-Match
            if recent_rooms:
                current_room = recent_rooms[0]
                if current_room in entity_lower:
                    score += 0.2

            # Bonus fuer Namens-Aehnlichkeit zum Text
            entity_words = entity_lower.replace(".", " ").replace("_", " ").split()
            for word in entity_words:
                if word in text_lower and len(word) > 2:
                    score += 0.1

            scored.append((entity, min(score, 1.0)))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def _discourse_repair(self, text: str, person: str = "") -> Optional[dict]:
        """Erkennt Korrektur-Muster wenn der User die vorherige Referenz korrigiert.

        Erkennt Muster wie 'das ANDERE', 'nein das', 'nicht das' und gibt
        die korrigierte Entity zurueck.

        Returns:
            Dict mit 'correction' und 'original' Keys oder None.
        """
        text_lower = text.lower().strip()
        state = self._get_state(person)

        repair_patterns = [
            r"(?:das |die |den )?andere(?:s|n|r)?",
            r"nein[\s,]+(?:das |die |den )?(\w+)",
            r"nicht das[\s,]+(?:sondern\s+)?(?:das |die |den )?(\w+)",
        ]

        for pattern in repair_patterns:
            if re.search(pattern, text_lower):
                # "das andere" → naechste Entity in der Liste (nicht die letzte)
                if len(state.last_entities) >= 2:
                    original = state.last_entities[0]
                    correction = state.last_entities[1]
                    logger.debug("Discourse Repair: '%s' -> '%s'", original, correction)
                    return {"correction": correction, "original": original}
                break

        return None
