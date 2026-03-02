"""
Memory Extractor - Extrahiert Fakten aus Gespraechen mittels LLM.
Laeuft nach jeder substantiellen Konversation und speichert
extrahierte Fakten im Semantic Memory.
"""

import json
import logging
from typing import Optional

from .config import yaml_config
from .ollama_client import OllamaClient
from .semantic_memory import SemanticFact, SemanticMemory

logger = logging.getLogger(__name__)

# Prompt fuer Fakten-Extraktion (deutsch, knapp, strukturiert)
EXTRACTION_PROMPT = """Du bist ein Fakten-Extraktor. Analysiere das folgende Gespraech und extrahiere ALLE relevanten Fakten.

Kategorien:
- preference: Vorlieben und Abneigungen (Temperatur, Licht, Musik, Essen, etc.)
- person: Informationen ueber Personen (Namen, Beziehungen, Berufe)
- habit: Gewohnheiten und Routinen (Aufstehzeit, Joggen, Arbeitszeiten)
- health: Gesundheitsinformationen (Allergien, Unvertraeglichkeiten, Medikamente)
- work: Arbeit und Projekte (Job, Meetings, Deadlines)
- general: Sonstige wichtige Fakten

Regeln:
- Nur KONKRETE Fakten extrahieren, keine Vermutungen.
- Jeder Fakt als eigenstaendiger Satz.
- Person identifizieren (wer sagt/meint das?).
- Keine Fakten ueber das Smart Home System selbst.
- Keine trivialen Befehle ("Licht an") als Fakten speichern.
- NUR Fakten die langfristig relevant sind.
- UNTERSCHEIDE momentane Zustaende von dauerhaften Praeferenzen:
  - "Mir ist warm" = momentan, NICHT speichern.
  - "Ich mag es kuehl" = Praeferenz, speichern.
  - "Ich bin muede" = momentan, NICHT speichern.
  - "Ich stehe immer um 6 auf" = Gewohnheit, speichern.
- Keine Gruesse, Danksagungen oder Smalltalk als Fakten.

Antworte NUR mit einem JSON-Array. Wenn keine Fakten vorhanden, antworte mit [].

Format:
[
  {"content": "Max bevorzugt 21 Grad im Buero", "category": "preference", "person": "Max"},
  {"content": "Lisa ist die Freundin von Max", "category": "person", "person": "Max"}
]

Gespraech:
{conversation}

Fakten (JSON-Array):"""

# Phase 8: Erweiterter Prompt mit Intent-Erkennung
INTENT_EXTRACTION_HINT = """
Zusaetzlich zu Fakten: Suche nach ABSICHTEN und PLAENEN mit Zeitangaben.
Wenn der User etwas plant (Besuch, Reise, Termin, Vorhaben), extrahiere das als:
{"content": "Eltern kommen naechstes Wochenende zu Besuch", "category": "intent", "person": "Max"}

Nur echte Plaene mit erkennbarer Zeitangabe. Keine Vermutungen."""

# Defaults — werden von yaml_config ueberschrieben
_DEFAULT_MIN_WORDS = 5
_DEFAULT_MAX_LENGTH = 2000


# Confidence pro Kategorie: Gesundheit/Sicherheit hoeher, Smalltalk niedriger
CATEGORY_CONFIDENCE = {
    "health": 0.9,      # Allergien, Medikamente -> sehr wichtig
    "person": 0.85,     # Beziehungen, Namen -> wichtig
    "preference": 0.75, # Vorlieben -> mittel-hoch
    "habit": 0.7,       # Gewohnheiten -> mittel
    "work": 0.7,        # Arbeit/Projekte -> mittel
    "intent": 0.6,      # Absichten/Plaene -> kann sich aendern
    "general": 0.5,     # Sonstiges -> niedrig
}


class MemoryExtractor:
    """Extrahiert Fakten aus Gespraechen mittels LLM."""

    def __init__(self, ollama: OllamaClient, semantic_memory: SemanticMemory):
        self.ollama = ollama
        self.semantic = semantic_memory

        # Config aus settings.yaml lesen
        mem_cfg = yaml_config.get("memory", {})
        self.enabled = mem_cfg.get("extraction_enabled", True)
        self._extraction_model = mem_cfg.get("extraction_model", "qwen3:14b")
        self._extraction_temperature = float(mem_cfg.get("extraction_temperature", 0.1))
        self._extraction_max_tokens = int(mem_cfg.get("extraction_max_tokens", 512))
        self._min_words = int(mem_cfg.get("extraction_min_words", _DEFAULT_MIN_WORDS))
        self._default_confidence = float(mem_cfg.get("default_confidence", 0.7))
        self._duplicate_threshold = float(mem_cfg.get("duplicate_threshold", 0.15))

    async def extract_and_store(
        self,
        user_text: str,
        assistant_response: str,
        person: str = "unknown",
        context: Optional[dict] = None,
    ) -> list[SemanticFact]:
        """
        Extrahiert Fakten aus einem Gespraech und speichert sie.

        Args:
            user_text: Was der User gesagt hat
            assistant_response: Was der Assistant geantwortet hat
            person: Name der Person
            context: Optionaler Kontext (Raum, Zeit, etc.)

        Returns:
            Liste der extrahierten und gespeicherten Fakten
        """
        # Pruefen ob Extraktion sinnvoll / aktiviert ist
        if not self.enabled or not self._should_extract(user_text, assistant_response):
            return []

        # Konversation formatieren
        conversation = self._format_conversation(
            user_text, assistant_response, person, context
        )

        # LLM um Fakten-Extraktion bitten
        raw_facts = await self._call_llm(conversation)
        if not raw_facts:
            return []

        # Fakten parsen und speichern
        stored_facts = []
        for raw in raw_facts:
            content = raw.get("content", "").strip()
            category = raw.get("category", "general").strip()
            fact_person = raw.get("person", person).strip()

            if not content:
                continue

            # Confidence basierend auf Kategorie (Gesundheit > Smalltalk)
            initial_confidence = CATEGORY_CONFIDENCE.get(category, 0.5)

            fact = SemanticFact(
                content=content,
                category=category,
                person=fact_person,
                confidence=initial_confidence,
                source_conversation=f"User: {user_text[:100]}",
            )

            success = await self.semantic.store_fact(fact)
            if success:
                stored_facts.append(fact)

        if stored_facts:
            logger.info(
                "%d Fakt(en) extrahiert aus Gespraech mit %s",
                len(stored_facts), person,
            )

        return stored_facts

    def _should_extract(self, user_text: str, assistant_response: str) -> bool:
        """Prueeft ob eine Extraktion sinnvoll ist.

        Filtert Gruesse, Bestaetigungen, Einzelwort-Antworten und reine
        Befehle heraus — diese enthalten keine speichernswerten Fakten.
        """
        text_lower = user_text.lower().strip().rstrip("!?.")

        # Zu kurze Texte ueberspringen (erhoehtes Minimum)
        if len(user_text.split()) < max(self._min_words, 5):
            return False

        # Reine Befehle ueberspringen (kein Fakten-Potenzial)
        command_only = {
            "licht an", "licht aus", "stopp", "stop", "pause",
            "weiter", "lauter", "leiser", "gute nacht", "guten morgen",
            "mach an", "mach aus", "schalte an", "schalte aus",
            "rollladen hoch", "rollladen runter", "jalousie hoch", "jalousie runter",
        }
        if text_lower in command_only:
            return False

        # Gruesse und Smalltalk ueberspringen
        greetings = {
            "hallo", "hi", "hey", "moin", "morgen", "abend", "tag",
            "guten tag", "guten abend", "guten morgen", "servus",
            "wie gehts", "wie geht es dir", "alles klar", "was geht",
        }
        if text_lower in greetings:
            return False

        # Einzelwort-Bestaetigungen und Antworten
        confirmations = {
            "ja", "nein", "ok", "okay", "danke", "bitte", "genau",
            "richtig", "falsch", "stimmt", "passt", "klar", "alles klar",
            "gut", "super", "perfekt", "toll", "prima", "noe",
            "hmm", "aha", "achso", "verstehe", "logo",
        }
        if text_lower in confirmations:
            return False

        # Proaktive Meldungs-Marker ueberspringen
        if user_text.startswith("[proaktiv"):
            return False

        return True

    def _format_conversation(
        self,
        user_text: str,
        assistant_response: str,
        person: str,
        context: Optional[dict] = None,
    ) -> str:
        """Formatiert die Konversation fuer den Extraction-Prompt."""
        parts = []

        if person and person != "unknown":
            parts.append(f"Person: {person}")

        if context:
            room = context.get("room", "")
            time_info = context.get("time", {})
            if room:
                parts.append(f"Raum: {room}")
            if time_info:
                parts.append(f"Zeit: {time_info.get('datetime', '')}")

        parts.append(f"{person or 'User'}: {user_text}")
        parts.append(f"Assistant: {assistant_response}")

        conversation = "\n".join(parts)
        # Auf maximale Laenge begrenzen
        return conversation[:_DEFAULT_MAX_LENGTH]

    async def _call_llm(self, conversation: str) -> list[dict]:
        """Ruft das LLM auf um Fakten zu extrahieren."""
        # Phase 8: Intent-Erkennung anhaengen
        prompt = EXTRACTION_PROMPT.replace("{conversation}", conversation)
        prompt = prompt.rstrip() + "\n" + INTENT_EXTRACTION_HINT

        try:
            response = await self.ollama.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self._extraction_model,
                temperature=self._extraction_temperature,
                max_tokens=self._extraction_max_tokens,
            )

            if "error" in response:
                logger.error("LLM Fehler bei Extraktion: %s", response["error"])
                return []

            content = response.get("message", {}).get("content", "").strip()
            return self._parse_facts(content)

        except Exception as e:
            logger.error("Fehler bei Fakten-Extraktion: %s", e)
            return []

    def _parse_facts(self, llm_output: str) -> list[dict]:
        """Parst die LLM-Antwort in eine Liste von Fakten."""
        # JSON-Array aus der Antwort extrahieren
        text = llm_output.strip()

        # Versuche direktes JSON-Parsing
        try:
            result = json.loads(text)
            if isinstance(result, list):
                return [f for f in result if isinstance(f, dict) and f.get("content")]
            return []
        except json.JSONDecodeError:
            pass

        # Fallback: JSON-Array in der Antwort suchen
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                result = json.loads(text[start:end + 1])
                if isinstance(result, list):
                    return [f for f in result if isinstance(f, dict) and f.get("content")]
            except json.JSONDecodeError:
                pass

        logger.debug("Konnte LLM-Antwort nicht parsen: %s", text[:200])
        return []

    # ------------------------------------------------------------------
    # Feature 5: Emotionales Gedaechtnis (Relationship Memory)
    # ------------------------------------------------------------------

    _NEGATIVE_REACTION_PATTERNS = frozenset([
        "nein", "lass das", "hoer auf", "nicht", "stop", "stopp",
        "will ich nicht", "nervt", "falsch", "schlecht", "weg damit",
        "mach das rueckgaengig", "zurueck", "undo", "abbrechen",
    ])

    async def extract_reaction(
        self,
        user_text: str,
        action_performed: str,
        accepted: bool,
        person: str = "unknown",
        redis_client=None,
    ) -> None:
        """Speichert eine emotionale Reaktion auf eine Aktion.

        Args:
            user_text: Was der User gesagt hat
            action_performed: Welche Aktion ausgefuehrt wurde (z.B. "set_climate")
            accepted: Ob die Reaktion positiv war
            person: Betroffene Person
            redis_client: Redis-Client (optional, wird intern gesetzt)
        """
        emo_cfg = yaml_config.get("emotional_memory", {})
        if not emo_cfg.get("enabled", True):
            return

        redis = redis_client
        if not redis:
            return

        key = f"mha:emotional_memory:{action_performed}:{person.lower()}"
        sentiment = "positive" if accepted else "negative"

        try:
            import json as _json
            from datetime import datetime as _dt

            entry = _json.dumps({
                "sentiment": sentiment,
                "action": action_performed,
                "user_text": user_text[:100],
                "timestamp": _dt.now().isoformat(),
            })

            await redis.lpush(key, entry)
            await redis.ltrim(key, 0, 19)  # Max 20 Eintraege
            decay_days = emo_cfg.get("decay_days", 90)
            await redis.expire(key, decay_days * 86400)

            logger.info(
                "Emotionale Reaktion gespeichert: %s auf %s von %s",
                sentiment, action_performed, person,
            )
        except Exception as e:
            logger.debug("Emotionale Reaktion speichern fehlgeschlagen: %s", e)

    @staticmethod
    async def get_emotional_context(
        action_type: str, person: str, redis_client=None,
    ) -> Optional[str]:
        """Gibt emotionalen Kontext fuer eine Aktion zurueck.

        Args:
            action_type: Typ der geplanten Aktion (z.B. "set_climate")
            person: Betroffene Person
            redis_client: Redis-Client

        Returns:
            Warntext wenn negative History vorhanden, sonst None
        """
        emo_cfg = yaml_config.get("emotional_memory", {})
        if not emo_cfg.get("enabled", True) or not redis_client:
            return None

        key = f"mha:emotional_memory:{action_type}:{person.lower()}"
        threshold = emo_cfg.get("negative_threshold", 2)

        try:
            import json as _json

            entries_raw = await redis_client.lrange(key, 0, 9)
            if not entries_raw:
                return None

            negative_count = 0
            last_negative_text = ""
            for raw in entries_raw:
                entry = _json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                if entry.get("sentiment") == "negative":
                    negative_count += 1
                    if not last_negative_text:
                        last_negative_text = entry.get("user_text", "")

            if negative_count >= threshold:
                return (
                    f"EMOTIONALES GEDAECHTNIS: Der Benutzer hat bereits {negative_count}x "
                    f"negativ auf '{action_type}' reagiert "
                    f"(zuletzt: \"{last_negative_text}\"). "
                    f"Frage lieber nach bevor du diese Aktion ausfuehrst."
                )
            return None
        except Exception as e:
            logger.debug("Emotionaler Kontext Fehler: %s", e)
            return None

    def detect_negative_reaction(self, text: str) -> bool:
        """Erkennt ob ein Text eine negative Reaktion auf eine Aktion ist."""
        text_lower = text.lower().strip()
        return any(p in text_lower for p in self._NEGATIVE_REACTION_PATTERNS)
