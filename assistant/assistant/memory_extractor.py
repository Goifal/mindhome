"""
Memory Extractor - Extrahiert Fakten aus Gespraechen mittels LLM.
Laeuft nach jeder substantiellen Konversation und speichert
extrahierte Fakten im Semantic Memory.
"""

import json
import logging
import re
from typing import Optional

from .config import settings, yaml_config

# Injection-Schutz: Gleiches Pattern wie context_builder.py / correction_memory.py
_INJECTION_PATTERN = re.compile(
    r'\[(?:SYSTEM|INSTRUCTION|OVERRIDE|ADMIN|COMMAND|PROMPT|ROLE)\b'
    r'|IGNORE\s+(?:ALL\s+)?(?:PREVIOUS\s+)?INSTRUCTIONS'
    r'|SYSTEM\s*(?:MODE|OVERRIDE|INSTRUCTION)'
    r'|<\/?(?:system|instruction|admin|role|prompt)\b',
    re.IGNORECASE,
)
from .ollama_client import OllamaClient
from .semantic_memory import SemanticFact, SemanticMemory

logger = logging.getLogger(__name__)

# Prompt für Fakten-Extraktion (deutsch, knapp, strukturiert)
EXTRACTION_PROMPT = """Du bist ein Fakten-Extraktor. Analysiere das folgende Gespraech und extrahiere ALLE relevanten Fakten.

Kategorien:
- preference: Vorlieben und Abneigungen (Temperatur, Licht, Musik, Essen, etc.)
- person: Informationen über Personen (Namen, Beziehungen, Berufe)
- habit: Gewohnheiten und Routinen (Aufstehzeit, Joggen, Arbeitszeiten)
- health: Gesundheitsinformationen (Allergien, Unvertraeglichkeiten, Medikamente)
- work: Arbeit und Projekte (Job, Meetings, Deadlines)
- general: Sonstige wichtige Fakten

Regeln:
- Nur KONKRETE Fakten extrahieren, keine Vermutungen.
- Jeder Fakt als eigenstaendiger Satz.
- Person identifizieren (wer sagt/meint das?). NUR echte Bewohner/Menschen als Person.
- NIEMALS "Jarvis", "Assistant", "System", "Bot" oder "unknown" als Person verwenden.
  Wenn die Person der Bewohner ist, dessen Name bekannt ist, diesen verwenden.
  Wenn nicht klar ist wer spricht, Person aus dem Kontext oben uebernehmen.
- Keine Fakten über das Smart Home System selbst (Jarvis-Einstellungen, Systeme, Module).
- Keine trivialen Befehle ("Licht an") als Fakten speichern.
- NUR Fakten die langfristig relevant sind.
- UNTERSCHEIDE momentane Zustaende von dauerhaften Praeferenzen:
  - "Mir ist warm" = momentan, NICHT speichern.
  - "Ich mag es kuehl" = Praeferenz, speichern.
  - "Ich bin muede" = momentan, NICHT speichern.
  - "Ich stehe immer um 6 auf" = Gewohnheit, speichern.
- Keine Grüße, Danksagungen oder Smalltalk als Fakten.

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
{"content": "Eltern kommen nächstes Wochenende zu Besuch", "category": "intent", "person": "Max"}

Nur echte Plaene mit erkennbarer Zeitangabe. Keine Vermutungen."""

# Defaults — werden von yaml_config überschrieben
_DEFAULT_MIN_WORDS = 3
_DEFAULT_MAX_LENGTH = 2000


# Personen-Blocklist: Diese Namen sind KEINE echten Bewohner und duerfen
# nicht als fact_person gespeichert werden.
_INVALID_PERSONS = frozenset({
    "unknown", "unbekannt", "jarvis", "assistant", "assistent",
    "system", "bot", "ki", "ai", "smart home", "mindhome",
    "user", "nutzer", "benutzer", "niemand", "none",
})

# Confidence pro Kategorie: Gesundheit/Sicherheit höher, Smalltalk niedriger
CATEGORY_CONFIDENCE = {
    "health": 0.9,      # Allergien, Medikamente -> sehr wichtig
    "person": 0.85,     # Beziehungen, Namen -> wichtig
    "preference": 0.75, # Vorlieben -> mittel-hoch
    "habit": 0.7,       # Gewohnheiten -> mittel
    "work": 0.7,        # Arbeit/Projekte -> mittel
    "intent": 0.6,      # Absichten/Plaene -> kann sich ändern
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
        from .config import resolve_model
        self._extraction_model = resolve_model(mem_cfg.get("extraction_model", ""), fallback_tier="fast")
        self._extraction_temperature = float(mem_cfg.get("extraction_temperature", 0.1))
        self._extraction_max_tokens = int(mem_cfg.get("extraction_max_tokens", 512))
        self._min_words = int(mem_cfg.get("extraction_min_words", _DEFAULT_MIN_WORDS))
        self._default_confidence = float(mem_cfg.get("default_confidence", 0.7))
        self._duplicate_threshold = float(mem_cfg.get("duplicate_threshold", 0.15))

        # Konfigurierbare Category-Confidence (Fallback: hardcoded CATEGORY_CONFIDENCE)
        self._category_confidence = mem_cfg.get("category_confidence") or dict(CATEGORY_CONFIDENCE)

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
        # Prüfen ob Extraktion sinnvoll / aktiviert ist
        if not self.enabled or not self._should_extract(user_text, assistant_response):
            return []

        # Embedding-basierte Duplikat-Pruefung: Wenn der User-Text semantisch
        # sehr aehnlich zu kuerzlich extrahierten Fakten ist, LLM-Call sparen.
        if await self._is_duplicate_input(user_text, person):
            logger.debug("Memory-Extraktion uebersprungen: Input zu aehnlich zu kuerzlichen Fakten")
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
            content = (raw.get("content") or "").strip()
            category = (raw.get("category") or "general").strip()
            fact_person = (raw.get("person") or person or "unknown").strip()

            if not content:
                continue

            # Invalide Personen filtern: Jarvis/Assistant/System sind keine Bewohner
            _is_system_person = fact_person.lower() in _INVALID_PERSONS
            # "unknown" ist OK als Fallback — nur echte System-Namen blocken
            _is_only_unknown = fact_person.lower() in ("unknown", "unbekannt")
            if _is_system_person and not _is_only_unknown:
                # Echte System-Person (jarvis, assistant, bot) → auf Bewohner zurueckfallen
                if person and person.lower() not in _INVALID_PERSONS:
                    fact_person = person
                else:
                    logger.debug("Fakt uebersprungen (System-Person '%s'): %s",
                                 fact_person, content[:80])
                    continue
            elif _is_only_unknown and person and person.lower() not in _INVALID_PERSONS:
                # LLM hat keine Person erkannt, aber wir wissen wer spricht
                fact_person = person

            # Confidence basierend auf Kategorie (Gesundheit > Smalltalk)
            initial_confidence = self._category_confidence.get(category, 0.5)

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

    async def _is_duplicate_input(self, user_text: str, person: str) -> bool:
        """Prueft ob der User-Text semantisch zu aehnlich zu kuerzlich gespeicherten Fakten ist.

        Nutzt Sentence-Transformer Embeddings fuer schnellen Vergleich.
        Spart unnoetige LLM-Calls wenn der User wiederholt Aehnliches sagt.
        """
        try:
            from .embeddings import get_embedding, cosine_similarity

            # Letzte Fakten fuer diese Person aus Semantic Memory holen
            if not self.semantic:
                return False
            recent_facts = await self.semantic.search(user_text, person=person, limit=3)
            if not recent_facts:
                return False

            user_emb = get_embedding(user_text.lower().strip())
            if user_emb is None:
                return False

            for fact in recent_facts:
                fact_text = fact.get("content", "") if isinstance(fact, dict) else getattr(fact, "content", "")
                if not fact_text:
                    continue
                fact_emb = get_embedding(fact_text.lower().strip())
                if fact_emb is not None:
                    similarity = cosine_similarity(user_emb, fact_emb)
                    if similarity >= 0.92:  # Sehr hohe Aehnlichkeit = Duplikat
                        return True
        except Exception as e:
            logger.debug("Duplikat-Pruefung fehlgeschlagen: %s", e)

        return False

    def _should_extract(self, user_text: str, assistant_response: str) -> bool:
        """Prueeft ob eine Extraktion sinnvoll ist.

        Filtert Grüße, Bestaetigungen, Einzelwort-Antworten und reine
        Befehle heraus — diese enthalten keine speichernswerten Fakten.
        """
        text_lower = user_text.lower().strip().rstrip("!?.")

        # WHITELIST: Diese Patterns IMMER extrahieren, egal wie kurz
        force_extract_patterns = [
            "merk dir", "merkt euch", "merke dir",
            "vergiss nicht", "vergiss das nicht",
            "ab sofort", "von jetzt an", "ab heute",
            "ich heisse", "ich heiße", "mein name ist",
            "meine frau", "mein mann", "mein partner", "meine freundin", "mein freund",
            "mein geburtstag", "ich bin geboren",
            "ich mag", "ich hasse", "ich bevorzuge", "ich liebe", "ich finde",
            "ich bin allergisch", "ich vertrage kein",
            "ich arbeite", "ich bin von beruf", "mein beruf",
            "wir haben", "wir bekommen", "wir erwarten",
            "meine kinder", "mein sohn", "meine tochter", "mein hund", "meine katze",
            "meine mutter", "mein vater", "meine eltern", "meine schwester", "mein bruder",
            "ich esse kein", "ich trinke kein", "vegetarisch", "vegan",
            "ich brauche", "ich moechte gerne", "ich möchte gerne",
            "immer um", "jeden tag", "jeden morgen", "jeden abend", "jede woche",
            "am liebsten", "am besten", "normalerweise",
        ]
        if any(p in text_lower for p in force_extract_patterns):
            return True  # Erzwungene Extraktion!

        # Zu kurze Texte überspringen (erhöhtes Minimum)
        if len(user_text.split()) < max(self._min_words, 3):
            return False

        # Reine Befehle überspringen (kein Fakten-Potenzial)
        command_only = {
            "licht an", "licht aus", "stopp", "stop", "pause",
            "weiter", "lauter", "leiser", "gute nacht", "guten morgen",
            "mach an", "mach aus", "schalte an", "schalte aus",
            "rollladen hoch", "rollladen runter", "jalousie hoch", "jalousie runter",
        }
        if text_lower in command_only:
            return False

        # Grüße und Smalltalk überspringen
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

        # Proaktive Meldungs-Marker überspringen
        if user_text.startswith("[proaktiv"):
            return False

        return True

    @staticmethod
    def _sanitize_for_extraction(text: str, max_len: int = 1000) -> str:
        """Bereinigt User-Text gegen Prompt-Injection in der Fakten-Extraktion."""
        if not text or not isinstance(text, str):
            return ""
        text = text.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
        text = re.sub(r'\s{2,}', ' ', text).strip()
        text = text[:max_len]
        if _INJECTION_PATTERN.search(text):
            logger.warning("Prompt-Injection in Memory-Extraktion blockiert: %.80s", text)
            return "[BLOCKIERT — verdaechtiger Input]"
        return text

    def _format_conversation(
        self,
        user_text: str,
        assistant_response: str,
        person: str,
        context: Optional[dict] = None,
    ) -> str:
        """Formatiert die Konversation für den Extraction-Prompt."""
        parts = []

        if person and person != "unknown":
            parts.append(f"Person: {self._sanitize_for_extraction(person, 50)}")

        if context:
            room = context.get("room", "")
            time_info = context.get("time", {})
            if room:
                parts.append(f"Raum: {self._sanitize_for_extraction(room, 50)}")
            if time_info:
                parts.append(f"Zeit: {self._sanitize_for_extraction(str(time_info.get('datetime', '')), 50)}")

        # Sanitize user input against prompt injection
        safe_user = self._sanitize_for_extraction(user_text)
        safe_assistant = self._sanitize_for_extraction(assistant_response)
        # Sprecherlabel: Echten Namen verwenden, sonst "Bewohner" (nicht "unknown")
        speaker = person if (person and person.lower() not in ("unknown", "unbekannt")) else "Bewohner"
        parts.append(f"{speaker}: {safe_user}")
        parts.append(f"Jarvis: {safe_assistant}")

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
                think=False,  # Kein Thinking — nur JSON-Output
            )

            if "error" in response:
                logger.error("LLM Fehler bei Extraktion: %s", response["error"])
                return []

            content = response.get("message", {}).get("content", "").strip()
            return self._parse_facts(content)

        except Exception as e:
            logger.error("Fehler bei Fakten-Extraktion: %s (model=%s, text_len=%d)",
                         e, self._extraction_model, len(conversation))
            return []

    def _parse_facts(self, llm_output: str) -> list[dict]:
        """Parst die LLM-Antwort in eine Liste von Fakten."""
        # JSON-Array aus der Antwort extrahieren
        text = llm_output.strip()

        # Think-Tags entfernen (Qwen3.5 denkt manchmal vor der Antwort)
        if "<think>" in text:
            think_end = text.find("</think>")
            if think_end != -1:
                text = text[think_end + 8:].strip()

        # Markdown Code-Block entfernen (```json ... ```)
        if text.startswith("```"):
            lines = text.split("\n")
            # Erste Zeile (```json) und letzte (```) entfernen
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

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

        # Leere Antwort oder nur Whitespace → keine Fakten (kein Warning noetig)
        if not text or text in ("[]", "null", "None", "keine", "Keine"):
            return []

        logger.warning("Fakten-JSON-Parse fehlgeschlagen (LLM-Output war kein valides JSON): %s", text[:300])
        return []

    # ------------------------------------------------------------------
    # Feature 5: Emotionales Gedaechtnis (Relationship Memory)
    # ------------------------------------------------------------------

    _NEGATIVE_REACTION_PATTERNS = frozenset([
        "nein", "lass das", "hör auf", "nicht", "stop", "stopp",
        "will ich nicht", "nervt", "falsch", "schlecht", "weg damit",
        "mach das rueckgaengig", "zurück", "undo", "abbrechen",
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
            action_performed: Welche Aktion ausgeführt wurde (z.B. "set_climate")
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

            # Bei negativer Reaktion: Korrektur als Praeferenz extrahieren
            # z.B. "Nein, 21 Grad!" nach set_climate(23) → Praeferenz speichern
            if not accepted and self.semantic and action_performed.startswith("set_"):
                try:
                    await self._extract_correction_preference(
                        user_text, action_performed, person,
                    )
                except Exception as pref_err:
                    logger.debug("Korrektur-Praeferenz-Extraktion fehlgeschlagen: %s", pref_err)

        except Exception as e:
            logger.debug("Emotionale Reaktion speichern fehlgeschlagen: %s", e)

    async def _extract_correction_preference(
        self, user_text: str, action: str, person: str,
    ) -> None:
        """Extrahiert eine Praeferenz aus einer Korrektur-Aussage.

        Wenn der User eine Aktion korrigiert (z.B. 'Nein, 21 Grad!'),
        wird daraus ein Praeferenz-Fakt abgeleitet und gespeichert.
        """
        from .semantic_memory import SemanticFact

        prompt = (
            "Der User hat eine Smart-Home-Aktion korrigiert.\n"
            f"Aktion: {action}\n"
            f"User-Korrektur: {user_text}\n\n"
            "Extrahiere die PRAEFERENZ des Users als kurzen Fakt (1 Satz, Deutsch).\n"
            "Beispiele:\n"
            "- 'Nein, 21 Grad!' → 'bevorzugt 21 Grad'\n"
            "- 'Zu hell, mach dunkler' → 'bevorzugt gedimmtes Licht'\n"
            "- 'Das Licht soll warm sein' → 'bevorzugt warmes Licht'\n\n"
            "Wenn KEINE klare Praeferenz erkennbar ist, antworte mit: KEINE\n"
            "Antwort (NUR den Fakt oder KEINE):"
        )

        try:
            result = await self.ollama.generate(
                prompt=prompt,
                temperature=0.1,
                max_tokens=60,
            )
            result = (result or "").strip()

            if not result or "KEINE" in result.upper() or len(result) < 5:
                return

            fact = SemanticFact(
                content=f"{person} {result}" if person else result,
                category="preference",
                person=person,
                confidence=0.85,
                source_conversation=f"Korrektur: {user_text[:100]}",
            )
            await self.semantic.store_fact(fact)
            logger.info("Korrektur-Praeferenz gespeichert: %s", result[:500])
        except Exception as e:
            logger.debug("Korrektur-LLM fehlgeschlagen: %s", e)

    @staticmethod
    async def get_emotional_context(
        action_type: str, person: str, redis_client=None,
    ) -> Optional[str]:
        """Gibt emotionalen Kontext für eine Aktion zurück.

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
                    f"Frage lieber nach bevor du diese Aktion ausführst."
                )
            return None
        except Exception as e:
            logger.debug("Emotionaler Kontext Fehler: %s", e)
            return None

    def detect_negative_reaction(self, text: str) -> bool:
        """Erkennt ob ein Text eine negative Reaktion auf eine Aktion ist."""
        text_lower = text.lower().strip()
        return any(p in text_lower for p in self._NEGATIVE_REACTION_PATTERNS)
