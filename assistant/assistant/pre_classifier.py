"""
Pre-Classifier — Leichtgewichtige Anfrage-Klassifikation VOR Context Build.

Bestimmt anhand von Regex/Keywords welche Subsysteme fuer eine Anfrage
tatsaechlich gebraucht werden. Spart bei einfachen Geraete-Befehlen
mehrere hundert Millisekunden Latenz, weil unnoetige async-Calls
(Mood, RAG, Security, Tutorial, ...) uebersprungen werden.

Das GENERAL-Profil aktiviert alle Subsysteme → identisch zum bisherigen
Verhalten. Wenn kein Profil uebergeben wird, aendert sich nichts.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

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
    need_mood=True,               # Mood auch bei Device-Commands — Frustration muss erkannt werden
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

PROFILE_DEVICE_QUERY = RequestProfile(
    category="device_query",
    need_house_status=True,       # Sensordaten/Zustaende abfragen
    need_mindhome_data=False,
    need_activity=True,           # Aktivitaet kann Antwort beeinflussen
    need_room_profile=True,       # Raum-Kontext fuer Zuordnung
    need_memories=False,          # Keine persoenlichen Erinnerungen noetig
    need_mood=False,              # Einfache Status-Antwort
    need_formality=False,
    need_irony=False,
    need_time_hints=True,         # Zeitkontext relevant (z.B. Nacht-Temperatur)
    need_security=False,
    need_cross_room=False,
    need_guest_mode=True,         # Guest-Mode beeinflusst sichtbare Daten
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
    r"^(mach|schalte?|schalt|stell|setz|dreh|fahr|oeffne|öffne|schliess|aktivier|deaktivier"
    r"|spiel|stopp|pause|pausier|lauter|leiser)e?\b",
)

# Eingebettete Verben: "ich will dass du X ausschaltest", "kannst du X einschalten"
_DEVICE_VERBS_EMBEDDED = re.compile(
    r"\b((?:ein|aus|an|ab|um)schalten?|(?:ein|aus|an|ab|um)schalt\w*"
    r"|(?:ein|aus|an|ab|um)machen?\w*|(?:ein|aus)stellen?\w*"
    r"|aktivieren?\w*|deaktivieren?\w*|abdunkeln?\w*|aufdrehen?\w*|zudrehen?\w*"
    r"|hochfahren?\w*|runterfahren?\w*|oeffnen?\w*|öffnen?\w*|schliessen?\w*"
    r"|abspielen?\w*|stoppen?\w*|pausieren?\w*)\b",
)

# Trennbare Verben: "schalte die Maschine aus", "mach das Licht an"
# Deutsche Trennverben haben den Praefix am Satzende
_DEVICE_VERBS_SEPARATED = re.compile(
    r"\b(mach\w*|schalt\w*|stell\w*|dreh\w*|fahr\w*)\b.+\b(ein|aus|an|ab|auf|zu|um|hoch|runter)\b"
)

_DEVICE_NOUNS = [
    "rollladen", "rolladen", "rollo", "jalousie",
    "rollläden", "rolläden", "rolllaeden", "rollos", "jalousien",
    "licht", "lampe", "leuchte", "beleuchtung",
    "heizung", "thermostat", "temperatur", "klima",
    "steckdose", "schalter",
    # Haushaltsgeraete (Switches)
    "maschine", "kaffeemaschine", "siebtraeger",
    "ventilator", "luefter", "pumpe", "boiler",
]

_DEVICE_ACTIONS = [
    "auf", "zu", "an", "aus", "hoch", "runter",
    "offen", "ein", "ab", "halb", "stopp", "stop",
    "dicht", "starten",
    # Klima-Aktionswoerter
    "wärmer", "waermer", "kälter", "kaelter",
    "kühler", "kuehler", "höher", "hoeher",
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
    "rollläden", "rolläden", "jalousie",
    "szene", "alarm", "tuer", "tür", "fenster",
    "musik", "tv", "fernseher", "kamera", "sensor",
    "steckdose", "schalter", "thermostat",
    "status", "hausstatus", "haus-status", "ueberblick", "überblick",
    "watt", "strom", "verbrauch", "energie", "kwh",
    "eingeschalten", "eingeschaltet", "ausgeschaltet",
    "smart plug", "smartplug",
]

# Status-Abfragen: Fragen nach aktuellem Zustand von Smart-Home-Geraeten
_STATUS_QUERY_PATTERNS = re.compile(
    r"(?:wie (?:warm|kalt|hell|dunkel|laut)|wie ist|was ist|ist (?:das|die|der) "
    r"|was zeigt|welche temperatur|wieviel grad|wie viel grad|wie hoch ist"
    r"|sind (?:die |das |der |alle )?|ist (?:das |die |der )?"
    r"|laeuft |status|hausstatus|haus-status|ueberblick"
    r"|was laeuft|was spielt"
    r")",
)

_STATUS_NOUNS = [
    "temperatur", "grad", "warm", "kalt", "heizung", "klima",
    "licht", "lichter", "lampe", "lampen", "hell", "dunkel", "helligkeit",
    "rollladen", "rolladen", "rolllaeden", "rollläden", "rolläden",
    "jalousie", "jalousien", "rollo", "rollos",
    "fenster", "tuer", "tür", "türen",
    "wetter", "aussen", "draussen",
    "strom", "verbrauch", "watt", "energie",
    "steckdose", "steckdosen", "schalter",
    "status", "hausstatus", "ueberblick", "überblick",
    "musik", "spielt", "laeuft", "läuft",
    "offen", "geschlossen", "verriegelt",
    "eingeschaltet", "ausgeschaltet",
    "alarm",
]

# Kurze Woerter die als eigenes Wort matchen muessen (nicht als Substring)
# "an" wuerde sonst "Anfang", "Antwort" etc. matchen
_STATUS_SHORT_WORDS = re.compile(r'\b(?:an|aus)\b')

# Implizite Befehle: Zustandsbeschreibungen die eine Geraete-Aktion implizieren.
# "Mir ist kalt" → Heizung hoch, "Es ist dunkel" → Licht an, etc.
# Werden als DEVICE_FAST klassifiziert damit das LLM die passende Aktion waehlt.
_IMPLICIT_COMMAND_PATTERNS = re.compile(
    r"(?:mir ist (?:kalt|warm|heiss)|ich (?:friere|schwitz|schwitze|frier)"
    r"|(?:es |hier |das )ist (?:(?:zu |so |viel zu |echt |total |ziemlich |sehr )?"
    r"(?:kalt|warm|heiss|dunkel|hell|laut|leise|stickig))"
    r"|(?:es |hier )(?:zieht|stinkt|riecht)"
    r"|(?:ich (?:seh|sehe|kann) (?:nichts|nix|kaum (?:was|etwas)))"
    r"|(?:(?:zu |so |viel zu |echt |total |ziemlich |sehr )"
    r"(?:kalt|warm|heiss|dunkel|hell|laut|leise|stickig) hier)"
    r")"
)


class PreClassifier:
    """Klassifiziert Anfragen fuer selektive Subsystem-Aktivierung.

    Primaer: Regex/Keyword-basiert (schnell, deterministisch).
    Fallback: LLM-Klassifikation fuer laengere Texte die im GENERAL landen.
    """

    def __init__(self):
        self._ollama = None
        self._last_category: str = ""  # Letzte Klassifikation fuer Kontext

    def set_ollama(self, ollama_client):
        """Setzt den OllamaClient fuer LLM-basierte Klassifikation."""
        self._ollama = ollama_client
        logger.info("PreClassifier: LLM-Fallback aktiviert")

    async def classify_async(self, text: str) -> RequestProfile:
        """Async-Version von classify() mit optionalem LLM-Fallback.

        Versucht zuerst Regex/Keyword-Klassifikation. Falls GENERAL und
        Text > 10 Woerter: LLM-Fallback fuer praezisere Klassifikation.
        """
        profile = self.classify(text)

        # LLM-Fallback nur bei GENERAL und laengeren Texten
        if (
            profile.category == "general"
            and self._ollama
            and len(text.split()) > 10
        ):
            from .config import yaml_config
            cfg = yaml_config.get("pre_classifier", {})
            if cfg.get("llm_fallback", True):
                llm_profile = await self._llm_classify(text)
                if llm_profile:
                    self._last_category = llm_profile.category
                    return llm_profile

        self._last_category = profile.category
        return profile

    async def _llm_classify(self, text: str) -> Optional[RequestProfile]:
        """LLM-basierte Klassifikation als Fallback fuer unklare Texte.

        Nutzt das Fast-Modell mit hartem Timeout. Bei Fehler → None (= GENERAL bleibt).
        """
        try:
            from .config import settings
            response = await asyncio.wait_for(
                self._ollama.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Klassifiziere den Text in GENAU eine Kategorie. "
                                "Antworte NUR mit dem Kategorie-Namen, kein anderer Text.\n"
                                "Kategorien:\n"
                                "- device_command: Geraetebefehl (Licht, Heizung, Rollladen, Steckdose steuern)\n"
                                "- device_query: Geraetestatus abfragen (Temperatur, ob etwas an/aus ist)\n"
                                "- knowledge: Wissensfrage (Erklaerung, Rezept, Info ohne Smart-Home-Bezug)\n"
                                "- memory: Erinnerungsfrage (was weisst du, erinnerst du dich)\n"
                                "- general: Alles andere (Smalltalk, komplexe Anfragen)\n"
                                + (f"Vorherige Anfrage war: {self._last_category}. "
                                   "Beruecksichtige das bei mehrdeutigen Folge-Anfragen.\n"
                                   if self._last_category else "")
                            ),
                        },
                        {"role": "user", "content": text[:300]},
                    ],
                    model=settings.model_fast,
                    temperature=0.0,
                    max_tokens=20,
                    think=False,
                    tier="fast",
                ),
                timeout=2.0,  # Hartes Timeout — darf Pre-Classification nicht verlangsamen
            )
            content = (response.get("message", {}).get("content", "") or "").strip().lower()
            # Think-Tags entfernen
            if "<think>" in content:
                think_end = content.find("</think>")
                if think_end != -1:
                    content = content[think_end + 8:].strip()

            profile_map = {
                "device_command": PROFILE_DEVICE_FAST,
                "device_query": PROFILE_DEVICE_QUERY,
                "knowledge": PROFILE_KNOWLEDGE,
                "memory": PROFILE_MEMORY,
                "general": PROFILE_GENERAL,
            }
            matched = profile_map.get(content)
            if matched:
                logger.debug("PreClassifier LLM-Fallback: %s -> %s", text[:50], content)
                return matched
        except asyncio.TimeoutError:
            logger.debug("PreClassifier LLM-Fallback Timeout")
        except Exception as e:
            logger.debug("PreClassifier LLM-Fallback Fehler: %s", e)
        return None

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
        # Normalize ß → ss so regex patterns (e.g. "schliess") match
        # both "schließe" and "schliesse" uniformly
        text_lower = text_lower.replace("ß", "ss")
        word_count = len(text_lower.split())

        # 1. Geraete-Befehle: Verb-Start oder Nomen+Aktion, max 12 Woerter
        #    (12 statt 8: Multi-Raum-Befehle wie "Mache die Rolllaeden im
        #    Wohnzimmer und der Kueche runter" haben 10 Woerter)
        #    ABER: Fragen ("ist ... an?", "sind ... offen?") sind Status-Queries, keine Commands
        #    FIX DL3-AI2/AI3: ? allein reicht NICHT — Fragewort muss dabei sein
        _question_starts = text_lower.startswith(("ist ", "sind ", "wie ", "was ", "wer ", "wo ", "wann ", "welch"))
        _has_question_mark = text_lower.rstrip().endswith("?")
        _is_question = _question_starts and (_has_question_mark or word_count <= 6)
        if word_count <= 12 and not _is_question:
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
            # "alles aus/zu/an" ohne spezifisches Geraete-Nomen
            _has_alle = any(f" {w}" in f" {text_lower}" for w in ("alle", "alles", "überall", "ueberall"))
            if _has_alle and has_action:
                logger.debug("PreClassifier: DEVICE_FAST (alles+action: %s)", text)
                return PROFILE_DEVICE_FAST

        # 1b. Eingebettete Device-Verben: "Ich will dass du X ausschaltest"
        #     Erkennt konjugierte Formen wie "ausschaltest", "einschalten", "anmachen"
        if word_count <= 16 and not _is_question:
            if _DEVICE_VERBS_EMBEDDED.search(text_lower):
                logger.debug("PreClassifier: DEVICE_FAST (embedded verb: %s)", text)
                return PROFILE_DEVICE_FAST

        # 1c. Trennbare Verben: "schalte die Maschine aus", "mach das Licht an"
        #     Deutsche Trennverben: Verb am Anfang/Mitte, Praefix am Satzende
        if word_count <= 16 and not _is_question:
            if _DEVICE_VERBS_SEPARATED.search(text_lower):
                _has_device_context = (
                    any(n in text_lower for n in _DEVICE_NOUNS)
                    or any(w in text_lower for w in ("maschine", "geraet", "gerät", "dose"))
                )
                if _has_device_context:
                    logger.debug("PreClassifier: DEVICE_FAST (separated verb: %s)", text)
                    return PROFILE_DEVICE_FAST

        # 2. Status-Abfragen: "Wie warm ist es?", "Sind die Rolllaeden offen?"
        if word_count <= 10:
            has_status_pattern = _STATUS_QUERY_PATTERNS.search(text_lower)
            has_status_noun = (
                any(n in text_lower for n in _STATUS_NOUNS)
                or _STATUS_SHORT_WORDS.search(text_lower)
            )
            if has_status_pattern and has_status_noun:
                logger.debug("PreClassifier: DEVICE_QUERY (%s)", text)
                return PROFILE_DEVICE_QUERY
            # Kurz-Queries: "Lichter?", "Rolllaeden?", "Steckdosen?" (1-2 Woerter + ?)
            if word_count <= 2 and text_lower.rstrip().endswith("?") and has_status_noun:
                logger.debug("PreClassifier: DEVICE_QUERY (short: %s)", text)
                return PROFILE_DEVICE_QUERY

        # 2b. Implizite Befehle: "Mir ist kalt", "Es ist dunkel hier"
        #     Zustandsbeschreibungen die eine Geraete-Aktion implizieren.
        if word_count <= 10 and _IMPLICIT_COMMAND_PATTERNS.search(text_lower):
            logger.debug("PreClassifier: DEVICE_FAST (implicit: %s)", text)
            return PROFILE_DEVICE_FAST

        # 3. Memory-Fragen
        if any(kw in text_lower for kw in _MEMORY_KEYWORDS):
            logger.debug("PreClassifier: MEMORY (%s)", text)
            return PROFILE_MEMORY

        # 5. Wissensfragen ohne Smart-Home-Bezug
        is_knowledge = any(
            text_lower.startswith(kw) or f" {kw}" in text_lower
            for kw in _KNOWLEDGE_PATTERNS
        )
        has_smart_home = any(kw in text_lower for kw in _SMART_HOME_KEYWORDS)

        if is_knowledge and not has_smart_home:
            logger.debug("PreClassifier: KNOWLEDGE (%s)", text)
            return PROFILE_KNOWLEDGE

        # 6. Default: Alles aktiv
        logger.debug("PreClassifier: GENERAL (%s)", text)
        return PROFILE_GENERAL
