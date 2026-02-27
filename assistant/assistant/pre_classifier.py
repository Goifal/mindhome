"""
Pre-Classifier — Leichtgewichtige Anfrage-Klassifikation VOR Context Build.

Bestimmt anhand von Regex/Keywords welche Subsysteme fuer eine Anfrage
tatsaechlich gebraucht werden. Spart bei einfachen Geraete-Befehlen
mehrere hundert Millisekunden Latenz, weil unnoetige async-Calls
(Mood, RAG, Security, Tutorial, ...) uebersprungen werden.

Das GENERAL-Profil aktiviert alle Subsysteme → identisch zum bisherigen
Verhalten. Wenn kein Profil uebergeben wird, aendert sich nichts.
"""

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RequestProfile:
    """Bestimmt welche Subsysteme fuer eine Anfrage aktiviert werden."""

    category: str  # "device_command", "knowledge", "memory", "general"

    # Context Builder Flags
    need_house_status: bool = True
    need_mindhome_data: bool = True
    need_activity: bool = True
    need_room_profile: bool = True
    need_memories: bool = True

    # Parallel Subsystem Flags (asyncio.gather in brain.py)
    need_mood: bool = True
    need_formality: bool = True
    need_irony: bool = True
    need_time_hints: bool = True
    need_security: bool = True
    need_cross_room: bool = True
    need_guest_mode: bool = True
    need_tutorial: bool = True
    need_summary: bool = True
    need_rag: bool = True


# -----------------------------------------------------------------
# Vordefinierte Profile
# -----------------------------------------------------------------

PROFILE_DEVICE_FAST = RequestProfile(
    category="device_command",
    need_house_status=True,       # Brauchen wir fuer Geraete-Zustand
    need_mindhome_data=False,
    need_activity=False,
    need_room_profile=True,       # Raum-Kontext fuer Geraete-Zuordnung
    need_memories=False,
    need_mood=False,
    need_formality=False,
    need_irony=False,
    need_time_hints=True,         # Zeitkontext ist wichtig (z.B. "Licht aus" um 3 Uhr)
    need_security=True,           # Sicherheit IMMER pruefen (auch bei Device-Commands)
    need_cross_room=False,
    need_guest_mode=True,         # Guest-Mode beeinflusst Berechtigung
    need_tutorial=False,
    need_summary=False,
    need_rag=False,
)

PROFILE_KNOWLEDGE = RequestProfile(
    category="knowledge",
    need_house_status=False,
    need_mindhome_data=False,
    need_activity=False,
    need_room_profile=False,
    need_memories=True,           # Persoenliches Wissen kann relevant sein
    need_mood=True,               # Tonalitaet der Antwort
    need_formality=True,
    need_irony=True,
    need_time_hints=False,
    need_security=False,
    need_cross_room=False,
    need_guest_mode=True,         # Guest-Mode: keine persoenlichen Fakten
    need_tutorial=False,
    need_summary=False,
    need_rag=True,                # RAG fuer Wissensbasis
)

PROFILE_MEMORY = RequestProfile(
    category="memory",
    need_house_status=False,
    need_mindhome_data=False,
    need_activity=False,
    need_room_profile=False,
    need_memories=True,           # Kern-Feature
    need_mood=True,
    need_formality=True,
    need_irony=True,
    need_time_hints=False,
    need_security=False,
    need_cross_room=False,
    need_guest_mode=True,
    need_tutorial=False,
    need_summary=False,
    need_rag=False,
)

PROFILE_GENERAL = RequestProfile(
    category="general",
    # Alles aktiv — identisch zum bisherigen Verhalten
)


# -----------------------------------------------------------------
# Klassifikations-Patterns (vorkompiliert)
# -----------------------------------------------------------------

_DEVICE_VERBS = re.compile(
    r"^(mach|schalte|stell|setz|dreh|oeffne|schliess|aktivier|deaktivier"
    r"|spiel|stopp|pause|lauter|leiser)\b",
)

_DEVICE_NOUNS = [
    "rollladen", "rolladen", "rollo", "jalousie",
    "licht", "lampe", "leuchte",
    "heizung", "thermostat",
    "steckdose", "schalter",
]

_DEVICE_ACTIONS = [
    "auf", "zu", "an", "aus", "hoch", "runter",
    "offen", "ein", "ab", "halb", "stopp",
]

_MEMORY_KEYWORDS = [
    "erinnerst du dich", "weisst du noch", "was weisst du",
    "habe ich dir", "hab ich gesagt", "was war",
]

_KNOWLEDGE_PATTERNS = [
    "wie lange", "wie viel", "wie viele", "was ist",
    "was sind", "was bedeutet", "erklaer mir", "erklaere",
    "warum ist", "wer ist", "wer war", "was passiert wenn",
    "wie funktioniert", "wie macht man", "wie kocht man",
    "rezept fuer", "rezept für", "definition von", "unterschied zwischen",
]

_SMART_HOME_KEYWORDS = [
    "licht", "lampe", "heizung", "temperatur", "rollladen",
    "jalousie", "szene", "alarm", "tuer", "fenster",
    "musik", "tv", "fernseher", "kamera", "sensor",
    "steckdose", "schalter", "thermostat",
    "status", "hausstatus", "haus-status", "ueberblick",
]


class PreClassifier:
    """Klassifiziert Anfragen fuer selektive Subsystem-Aktivierung."""

    def classify(self, text: str) -> RequestProfile:
        """
        Bestimmt das RequestProfile fuer einen User-Text.

        Reihenfolge:
          1. Geraete-Befehle (kurz + Device-Keyword) → DEVICE_FAST
          2. Memory-Fragen → MEMORY
          3. Wissensfragen (ohne Smart-Home) → KNOWLEDGE
          4. Alles andere → GENERAL
        """
        text_lower = text.lower().strip()
        word_count = len(text_lower.split())

        # 1. Geraete-Befehle: Verb-Start oder Nomen+Aktion, max 8 Woerter
        if word_count <= 8:
            if _DEVICE_VERBS.search(text_lower):
                logger.debug("PreClassifier: DEVICE_FAST (verb: %s)", text)
                return PROFILE_DEVICE_FAST

            has_noun = any(n in text_lower for n in _DEVICE_NOUNS)
            has_action = (
                any(f" {a}" in f" {text_lower}" for a in _DEVICE_ACTIONS)
                or "%" in text_lower
            )
            if has_noun and has_action:
                logger.debug("PreClassifier: DEVICE_FAST (noun+action: %s)", text)
                return PROFILE_DEVICE_FAST

        # 2. Memory-Fragen
        if any(kw in text_lower for kw in _MEMORY_KEYWORDS):
            logger.debug("PreClassifier: MEMORY (%s)", text)
            return PROFILE_MEMORY

        # 3. Wissensfragen ohne Smart-Home-Bezug
        is_knowledge = any(
            text_lower.startswith(kw) or f" {kw}" in text_lower
            for kw in _KNOWLEDGE_PATTERNS
        )
        has_smart_home = any(kw in text_lower for kw in _SMART_HOME_KEYWORDS)

        if is_knowledge and not has_smart_home:
            logger.debug("PreClassifier: KNOWLEDGE (%s)", text)
            return PROFILE_KNOWLEDGE

        # 4. Default: Alles aktiv
        logger.debug("PreClassifier: GENERAL (%s)", text)
        return PROFILE_GENERAL
