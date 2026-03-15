"""
Dialogue State Manager - Echte Dialogfuehrung mit Referenz-Aufloesung.

Medium Effort Feature: Tracked den Gespraechszustand, loest Referenzen auf
("es", "das", "dort", "den gleichen") und verwaltet Klaerungsfragen.

Zustaende:
- idle: Kein aktiver Dialog
- awaiting_clarification: Wartet auf Antwort zu Klaerungsfrage
- follow_up: User bezieht sich auf vorherige Aktion
- multi_step: Mehrstufiger Dialog (z.B. Szene erstellen)

Konfigurierbar in der Jarvis Assistant UI unter "Intelligenz".
"""

import logging
import re
import time
from collections import deque
from typing import Optional

from .config import yaml_config

logger = logging.getLogger(__name__)

# Referenz-Woerter die auf vorherige Entitaeten/Raeume verweisen
ENTITY_REFERENCES_DE = {
    "es", "das", "den", "die", "ihn", "ihm", "ihr", "dem",
    "das gleiche", "den gleichen", "die gleiche", "dasselbe",
    "das licht", "die lampe", "das ding",
}

ROOM_REFERENCES_DE = {
    "dort", "da", "dahin", "drin", "dorthin",
    "im gleichen raum", "im selben raum", "da drin",
    "hier",  # bezieht sich auf aktuellen Raum
}

ACTION_REFERENCES_DE = {
    "nochmal", "das gleiche", "genauso", "wieder",
    "auch", "ebenfalls", "dasselbe",
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

    def __init__(self):
        self.state: str = "idle"  # idle, awaiting_clarification, follow_up, multi_step
        self.last_entities: deque[str] = deque(maxlen=5)
        self.last_rooms: deque[str] = deque(maxlen=3)
        self.last_actions: deque[dict] = deque(maxlen=5)
        self.last_domains: deque[str] = deque(maxlen=3)
        self.pending_clarification: Optional[dict] = None
        self.multi_step_context: Optional[dict] = None
        self.last_update: float = time.time()
        self.turn_count: int = 0

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

        # Per-Person Dialog-Zustaende
        self._states: dict[str, DialogueState] = {}

    def _get_state(self, person: str = "") -> DialogueState:
        """Gibt den Dialog-Zustand fuer eine Person zurueck."""
        key = (person or "_default").lower()
        if key not in self._states:
            # Evict oldest entries if dict grows too large
            if len(self._states) > 50:
                oldest = sorted(
                    self._states,
                    key=lambda k: self._states[k].last_update if hasattr(self._states[k], 'last_update') else 0,
                )[:25]
                for old_key in oldest:
                    del self._states[old_key]
            self._states[key] = DialogueState()
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

    def resolve_references(self, text: str, person: str = "", current_room: str = "") -> dict:
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
            if re.search(r'\b' + re.escape(ref) + r'\b', text_lower):
                if state.last_entities:
                    last_ent = state.last_entities[0]
                    resolved_entities.append(last_ent)
                    had_references = True
                    hints.append(f"'{ref}' bezieht sich vermutlich auf: {last_ent}")
                    break

        # Raum-Referenzen aufloesen ("mach dort das Licht an")
        for ref in ROOM_REFERENCES_DE:
            if re.search(r'\b' + re.escape(ref) + r'\b', text_lower):
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
            if re.search(r'\b' + re.escape(ref) + r'\b', text_lower) and state.last_actions:
                last_action = state.last_actions[0]
                had_references = True
                hints.append(f"'{ref}' bezieht sich auf letzte Aktion: {last_action.get('description', str(last_action))}")
                break

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
            "options": options[:self.max_clarification_options],
            "original_text": original_text,
            "domain": domain,
            "timestamp": time.time(),
        }
        state.last_update = time.time()
        logger.info("Klaerungsfrage gestartet: '%s' (Optionen: %s)", question, options[:3])

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

    def needs_clarification(self, text: str, entities: list[str], person: str = "") -> Optional[dict]:
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
            "alle", "alles", "komplett", "ueberall", "jede", "jeden",
            "zusammen", "gleichzeitig",
        ]
        if any(m in text_lower for m in specificity_markers):
            return None

        # Max. Optionen begrenzen
        options = entities[:self.max_clarification_options]

        return {
            "question": f"Welches meinst du? ({', '.join(options[:3])}{'...' if len(options) > 3 else ''})",
            "options": options,
        }
