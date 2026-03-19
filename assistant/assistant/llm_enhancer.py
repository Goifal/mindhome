"""
LLM Enhancer - Macht Jarvis intelligenter durch gezielte LLM-Nutzung.

Vier Kernbereiche:
1. Smart Intent Recognition: Versteht implizite Befehle ("Mir ist kalt" -> Heizung hoch)
2. Conversation Summarizer: LLM-basierte Zusammenfassung fuer besseres Langzeitgedaechtnis
3. Proactive Suggester: LLM analysiert Muster und macht smarte Vorschlaege
4. Response Rewriter: Natuerlichere, kontextbewusstere Antworten
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from .config import settings, yaml_config, get_person_title
from .ollama_client import OllamaClient

logger = logging.getLogger(__name__)
from zoneinfo import ZoneInfo
_LOCAL_TZ = ZoneInfo(yaml_config.get("timezone", "Europe/Berlin"))

# Injection-Schutz
_INJECTION_PATTERN = re.compile(
    r'\[(?:SYSTEM|INSTRUCTION|OVERRIDE|ADMIN|COMMAND|PROMPT|ROLE)\b'
    r'|IGNORE\s+(?:ALL\s+)?(?:PREVIOUS\s+)?INSTRUCTIONS'
    r'|SYSTEM\s*(?:MODE|OVERRIDE|INSTRUCTION)'
    r'|<\/?(?:system|instruction|admin|role|prompt)\b',
    re.IGNORECASE,
)


def _sanitize(text: str, max_len: int = 500) -> str:
    """Bereinigt Text gegen Prompt-Injection."""
    if not text or not isinstance(text, str):
        return ""
    text = text.replace('\n', ' ').replace('\r', ' ')
    text = re.sub(r'\s{2,}', ' ', text).strip()[:max_len]
    if _INJECTION_PATTERN.search(text):
        logger.warning("Prompt-Injection blockiert in LLM Enhancer: %.80s", text)
        return ""
    return text


# =====================================================================
# 1. Smart Intent Recognition
# =====================================================================

IMPLICIT_INTENT_PROMPT = """Du bist ein Intent-Analysator fuer ein Smart Home System.

Analysiere den User-Text und erkenne IMPLIZITE Absichten.
Der User sagt nicht direkt was er will, sondern beschreibt einen Zustand oder ein Gefuehl.

Beispiele:
- "Mir ist kalt" -> {{"action": "set_climate", "intent": "Heizung hochdrehen", "confidence": 0.85}}
- "Es ist so dunkel hier" -> {{"action": "set_light", "intent": "Licht anschalten", "confidence": 0.9}}
- "Ich kann nicht schlafen" -> {{"action": "set_light", "intent": "Licht dimmen oder ausschalten", "confidence": 0.7}}
- "Es zieht hier" -> {{"action": "set_cover", "intent": "Fenster oder Rollladen schliessen", "confidence": 0.75}}
- "Mir ist langweilig" -> {{"action": "play_media", "intent": "Musik oder TV vorschlagen", "confidence": 0.6}}
- "Es ist so laut draussen" -> {{"action": "set_cover", "intent": "Rollladen schliessen", "confidence": 0.8}}
- "Ich geh jetzt ins Bett" -> {{"action": "goodnight", "intent": "Gute-Nacht-Routine", "confidence": 0.85}}
- "Ich muss frueh raus" -> {{"action": "set_alarm", "intent": "Wecker vorschlagen", "confidence": 0.65}}
- "Mir wird schlecht von der Luft" -> {{"action": "set_climate", "intent": "Lueftung verbessern", "confidence": 0.8}}

Wenn der Text eine DIREKTE Anweisung ist (z.B. "Mach das Licht an"), antworte mit {{"action": "none"}}.
Wenn KEINE implizite Absicht erkennbar ist, antworte mit {{"action": "none"}}.

Antworte NUR mit einem JSON-Objekt. Kein Kommentar.

Raum: {room}
Tageszeit: {time_of_day}
{room_state}Text: {text}

JSON:"""


class SmartIntentRecognizer:
    """Erkennt implizite Absichten aus natuerlicher Sprache via LLM."""

    def __init__(self, ollama: OllamaClient):
        self.ollama = ollama
        cfg = yaml_config.get("llm_enhancer", {}).get("smart_intent", {})
        self.enabled = cfg.get("enabled", True)
        self.min_confidence = cfg.get("min_confidence", 0.65)
        self._model = cfg.get("model", "")

    def _get_model(self) -> str:
        if self._model:
            from .config import resolve_model
            return resolve_model(self._model, fallback_tier="fast")
        return settings.model_fast

    def _is_implicit(self, text: str) -> bool:
        """Schnell-Check: Ist der Text ein impliziter Wunsch (kein direkter Befehl)?

        Gelockerter Filter: Neben expliziten Markern werden auch kurze Saetze
        ohne Device-Verben durchgelassen, da das LLM selbst 'action: none'
        zurueckgeben kann wenn kein impliziter Wunsch vorliegt.
        """
        text_lower = text.lower().strip()

        # Direkte Befehle ausschliessen
        direct_verbs = (
            "mach", "schalt", "stell", "setz", "dreh", "fahr",
            "oeffne", "schliess", "spiel", "stopp", "pause",
        )
        if any(text_lower.startswith(v) for v in direct_verbs):
            return False

        # Fragen sind keine impliziten Wuensche
        question_starts = (
            "was ", "wer ", "wie ", "wo ", "warum ", "wann ", "welch",
            "wie viel", "erklaer", "sag mir",
        )
        if any(text_lower.startswith(q) for q in question_starts):
            return False

        # Implizite Marker erkennen (hohe Konfidenz)
        implicit_markers = [
            "mir ist", "mir wird", "es ist so", "es ist zu",
            "ich kann nicht", "ich friere", "ich schwitze",
            "es zieht", "es stinkt", "es riecht",
            "so dunkel", "so hell", "so kalt", "so warm",
            "so laut", "so leise", "langweilig",
            "muede", "müde", "wach", "schlecht",
            "ich geh", "ich muss", "bin gleich",
            # Erweiterte Marker: Zustandsbeschreibungen und Emotionen
            "puh", "bah", "igitt", "boah", "uff",
            "hier ist", "hier riecht", "hier stinkt",
            "es nervt", "ich halt das nicht", "das haelt man nicht aus",
            "es ist viel zu", "total", "echt zu", "viel zu",
            "muffig", "stickig", "zugig",
            "ich brauche", "ich brauch", "ich will",
            "komme nicht zur ruhe", "kann mich nicht konzentrier",
        ]
        if any(m in text_lower for m in implicit_markers):
            return True

        # Gelockerter Filter: Kurze Saetze (3-8 Woerter) ohne Device-Verben
        # und ohne Fragewort — koennten implizite Wuensche sein.
        # Das LLM kann mit 'action: none' filtern.
        word_count = len(text_lower.split())
        if 3 <= word_count <= 8:
            # Kein Device-Verb, kein direkter Befehl → LLM entscheiden lassen
            device_verbs_in_text = (
                "einschalten", "ausschalten", "anschalten", "abschalten",
                "aktivier", "deaktivier", "hochfahren", "runterfahren",
            )
            if not any(v in text_lower for v in device_verbs_in_text):
                return True

        return False

    async def recognize(self, text: str, room: str = "",
                        time_of_day: str = "",
                        room_state: str = "") -> Optional[dict]:
        """Erkennt implizite Absichten im Text.

        Returns:
            Dict mit action, intent, confidence oder None
        """
        if not self.enabled:
            return None

        safe_text = _sanitize(text)
        if not safe_text:
            return None

        # Schnell-Filter: Nur bei potentiell impliziten Texten das LLM fragen
        if not self._is_implicit(safe_text):
            return None

        if not time_of_day:
            hour = datetime.now(_LOCAL_TZ).hour
            if 5 <= hour < 12:
                time_of_day = "Morgen"
            elif 12 <= hour < 17:
                time_of_day = "Nachmittag"
            elif 17 <= hour < 22:
                time_of_day = "Abend"
            else:
                time_of_day = "Nacht"

        # Raum-Status aufbereiten (Klima, Licht, Rollladen)
        _state_line = f"Aktueller Raum-Status: {room_state}\n" if room_state else ""

        prompt = IMPLICIT_INTENT_PROMPT.format(
            text=safe_text,
            room=room or "unbekannt",
            time_of_day=time_of_day,
            room_state=_state_line,
        )

        try:
            response = await self.ollama.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self._get_model(),
                temperature=0.1,
                max_tokens=200,
                think=False,
            )

            content = response.get("message", {}).get("content", "").strip()
            result = self._parse_result(content)

            if result and result.get("action") != "none":
                confidence = result.get("confidence", 0)
                if confidence >= self.min_confidence:
                    logger.info(
                        "Impliziter Intent erkannt: '%s' -> %s (%.0f%%)",
                        text[:50], result.get("intent", ""), confidence * 100,
                    )
                    return result

            return None

        except Exception as e:
            logger.debug("Smart Intent Recognition fehlgeschlagen: %s", e)
            return None

    @staticmethod
    def _parse_result(llm_output: str) -> Optional[dict]:
        """Parst LLM-JSON-Antwort."""
        text = llm_output.strip()

        # Think-Tags entfernen
        if "<think>" in text:
            think_end = text.find("</think>")
            if think_end != -1:
                text = text[think_end + 8:].strip()

        # JSON extrahieren
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        return None


# =====================================================================
# 2. Conversation Summarizer
# =====================================================================

SUMMARIZE_PROMPT = """Fasse das folgende Gespraech zwischen einem User und dem Smart-Home-Assistenten JARVIS zusammen.

REGELN:
- Maximal 3-4 Saetze
- Behalte: Wichtige Fakten, Entscheidungen, Praeferenzen, offene Themen
- Ignoriere: Begruessungen, Bestaetigungen ("Erledigt"), reine Geraetebefehle
- Schreibe in der dritten Person ("Der User hat...", "JARVIS hat...")
- Wenn der User persoenliche Informationen geteilt hat, diese IMMER erwaehnen

Gespraech:
{conversation}

Zusammenfassung:"""


class ConversationSummarizer:
    """LLM-basierte Gespraechs-Zusammenfassung fuer besseres Langzeitgedaechtnis."""

    def __init__(self, ollama: OllamaClient):
        self.ollama = ollama
        cfg = yaml_config.get("llm_enhancer", {}).get("conversation_summary", {})
        self.enabled = cfg.get("enabled", True)
        self.min_messages = cfg.get("min_messages", 4)
        self._model = cfg.get("model", "")

    def _get_model(self) -> str:
        if self._model:
            from .config import resolve_model
            return resolve_model(self._model, fallback_tier="fast")
        return settings.model_fast

    async def summarize(self, messages: list[dict],
                        person: str = "") -> Optional[str]:
        """Fasst eine Liste von Gespraechs-Nachrichten zusammen.

        Args:
            messages: Liste von {role: "user"|"assistant", content: str}
            person: Name der Person

        Returns:
            Zusammenfassung als String oder None
        """
        if not self.enabled or len(messages) < self.min_messages:
            return None

        # Gespraech formatieren
        lines = []
        for m in messages:
            role = person or "User" if m.get("role") == "user" else "Jarvis"
            content = _sanitize(m.get("content", ""), max_len=200)
            if content:
                lines.append(f"{role}: {content}")

        if not lines:
            return None

        conversation = "\n".join(lines)
        prompt = SUMMARIZE_PROMPT.format(conversation=conversation)

        try:
            response = await self.ollama.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self._get_model(),
                temperature=0.2,
                max_tokens=500,
                think=False,
            )

            content = response.get("message", {}).get("content", "").strip()

            # Think-Tags entfernen
            if "<think>" in content:
                think_end = content.find("</think>")
                if think_end != -1:
                    content = content[think_end + 8:].strip()

            if content and len(content) > 10:
                logger.info("Gespraech zusammengefasst (%d msgs -> %d chars)",
                            len(messages), len(content))
                return content

            return None

        except Exception as e:
            logger.debug("Conversation Summary fehlgeschlagen: %s", e)
            return None

    async def summarize_for_context(self, messages: list[dict],
                                    person: str = "") -> Optional[str]:
        """Erstellt eine kompakte Zusammenfassung fuer den LLM-Kontext.

        Kuerzer als summarize() — nur Fakten und offene Themen.
        """
        if not self.enabled or len(messages) < self.min_messages:
            return None

        lines = []
        for m in messages:
            role = person or "User" if m.get("role") == "user" else "Jarvis"
            content = _sanitize(m.get("content", ""), max_len=150)
            if content:
                lines.append(f"{role}: {content}")

        if not lines:
            return None

        prompt = (
            "Extrahiere die KERN-INFORMATIONEN aus diesem Gespraech in 1-2 Saetzen. "
            "Nur Fakten, Entscheidungen und offene Fragen. Kein Smalltalk.\n\n"
            + "\n".join(lines)
            + "\n\nKern-Info:"
        )

        try:
            response = await self.ollama.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self._get_model(),
                temperature=0.1,
                max_tokens=500,
                think=False,
            )

            content = response.get("message", {}).get("content", "").strip()
            if "<think>" in content:
                think_end = content.find("</think>")
                if think_end != -1:
                    content = content[think_end + 8:].strip()

            return content if content and len(content) > 5 else None

        except Exception as e:
            logger.debug("Context Summary fehlgeschlagen: %s", e)
            return None


# =====================================================================
# 3. Proactive Suggester
# =====================================================================

PROACTIVE_ANALYSIS_PROMPT = """Du bist ein Smart-Home-Analyst. Analysiere die folgenden Muster und den aktuellen Kontext.

Erkannte Muster aus der Action-History:
{patterns}

Aktueller Kontext:
- Tageszeit: {time_of_day}
- Wochentag: {weekday}
- Person: {person}
- Raum: {room}
- Wetter: {weather}

Generiere EINEN smarten Vorschlag basierend auf den Mustern und dem Kontext.
Der Vorschlag soll natuerlich klingen und dem User einen Mehrwert bieten.

REGELN:
- NUR vorschlagen wenn die Muster KLAR auf eine Aktion hindeuten
- Vorschlag als kurzer deutscher Satz (JARVIS-Ton: trocken, britisch-elegant)
- Wenn kein sinnvoller Vorschlag moeglich, antworte mit: KEINE

Beispiele guter Vorschlaege:
- "Du gehst freitags immer um 18 Uhr joggen. Soll ich die Heizung schon mal vorwaermen?"
- "Dein Filmabend-Muster: Rollladen runter, gedimmtes Licht. Soll ich vorbereiten?"
- "Letzte 3 Samstage: Musik im Wohnzimmer ab 10 Uhr. Heute auch?"

Vorschlag:"""


class ProactiveSuggester:
    """LLM-basierte proaktive Vorschlaege basierend auf erkannten Mustern."""

    def __init__(self, ollama: OllamaClient):
        self.ollama = ollama
        cfg = yaml_config.get("llm_enhancer", {}).get("proactive_suggestions", {})
        self.enabled = cfg.get("enabled", True)
        self.min_patterns = cfg.get("min_patterns", 1)
        self.max_suggestions_per_day = cfg.get("max_per_day", 5)
        self._model = cfg.get("model", "")
        self._suggestions_today = 0
        self._last_reset_day = datetime.now(timezone.utc).date()

    def _get_model(self) -> str:
        if self._model:
            from .config import resolve_model
            return resolve_model(self._model, fallback_tier="smart")
        return settings.model_smart

    def _check_daily_limit(self) -> bool:
        """Prueft ob das Tageslimit noch nicht erreicht ist."""
        today = datetime.now(timezone.utc).date()
        if today != self._last_reset_day:
            self._suggestions_today = 0
            self._last_reset_day = today
        return self._suggestions_today < self.max_suggestions_per_day

    async def generate_suggestion(
        self,
        patterns: list[dict],
        person: str = "",
        room: str = "",
        weather: str = "",
    ) -> Optional[dict]:
        """Generiert einen proaktiven Vorschlag basierend auf Mustern.

        Args:
            patterns: Erkannte Muster aus AnticipationEngine
            person: Aktuelle Person
            room: Aktueller Raum
            weather: Aktuelle Wetterlage

        Returns:
            Dict mit suggestion, action, confidence oder None
        """
        if not self.enabled or not patterns:
            return None

        if len(patterns) < self.min_patterns:
            return None

        if not self._check_daily_limit():
            return None

        now = datetime.now(_LOCAL_TZ)
        weekdays = ["Montag", "Dienstag", "Mittwoch", "Donnerstag",
                     "Freitag", "Samstag", "Sonntag"]

        hour = now.hour
        if 5 <= hour < 12:
            time_of_day = f"Morgen ({hour}:00)"
        elif 12 <= hour < 17:
            time_of_day = f"Nachmittag ({hour}:00)"
        elif 17 <= hour < 22:
            time_of_day = f"Abend ({hour}:00)"
        else:
            time_of_day = f"Nacht ({hour}:00)"

        # Top-Patterns formatieren (max 5 relevanteste)
        sorted_patterns = sorted(patterns, key=lambda p: p.get("confidence", 0), reverse=True)[:5]
        patterns_text = "\n".join(
            f"- {p.get('description', p.get('action', '?'))} "
            f"(Confidence: {p.get('confidence', 0):.0%}, {p.get('occurrences', 0)}x)"
            for p in sorted_patterns
        )

        prompt = PROACTIVE_ANALYSIS_PROMPT.format(
            patterns=patterns_text,
            time_of_day=time_of_day,
            weekday=weekdays[now.weekday()],
            person=person or "unbekannt",
            room=room or "unbekannt",
            weather=weather or "unbekannt",
        )

        try:
            response = await self.ollama.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self._get_model(),
                temperature=0.5,
                max_tokens=500,
                think=False,
            )

            content = response.get("message", {}).get("content", "").strip()

            # Think-Tags entfernen
            if "<think>" in content:
                think_end = content.find("</think>")
                if think_end != -1:
                    content = content[think_end + 8:].strip()

            if not content or "KEINE" in content.upper() or len(content) < 10:
                return None

            self._suggestions_today += 1

            # Aktion aus dem relevantesten Pattern
            top_pattern = sorted_patterns[0] if sorted_patterns else {}

            logger.info("Proaktiver Vorschlag generiert: '%s'", content[:500])
            return {
                "suggestion": content,
                "action": top_pattern.get("action", ""),
                "args": top_pattern.get("args", {}),
                "confidence": top_pattern.get("confidence", 0.6),
                "pattern_type": top_pattern.get("type", "unknown"),
            }

        except Exception as e:
            logger.debug("Proactive Suggestion fehlgeschlagen: %s", e)
            return None


# =====================================================================
# 4. Response Rewriter
# =====================================================================

REWRITE_PROMPT = """Du bist der Schreibstil-Filter von J.A.R.V.I.S., dem Smart-Home-Butler.

Deine Aufgabe: Schreibe die folgende Antwort um, damit sie NATUERLICHER und
PERSOENLICHER klingt — wie ein erfahrener Butler, nicht wie ein Chatbot.

CHARAKTER:
- Trocken-britischer Humor (Sarkasmus-Level: {sarcasm_level}/5)
- Souveraen, knapp, praezise
- Anrede: "{title}" (sparsam verwenden, nicht in jedem Satz)
- NIEMALS: "Natürlich!", "Gerne!", "Selbstverständlich!", "Klar!", "Super!"
- NIEMALS: Aufzaehlungen mit Spiegelstrichen oder Nummern
- Stimmlage anpassen: {mood_hint}

REGELN:
- Maximal 1-2 Saetze (bei einfachen Aktionen: 1 Satz)
- Fakten und Zahlen EXAKT uebernehmen (Temperaturen, Zeiten, Entity-IDs)
- Keine neuen Informationen hinzufuegen
- Wenn die Antwort bereits gut ist, minimal aendern
- Bei Geraetebefehlen: Nur "Erledigt." oder eine kurze Bestaetigung

User-Frage: {user_text}
Stimmung des Users: {mood}
Original-Antwort: {response}

Umgeschriebene Antwort:"""


class ResponseRewriter:
    """LLM-basiertes Response-Rewriting fuer natuerlichere Antworten."""

    def __init__(self, ollama: OllamaClient):
        self.ollama = ollama
        cfg = yaml_config.get("llm_enhancer", {}).get("response_rewriter", {})
        self.enabled = cfg.get("enabled", True)
        self.min_length = cfg.get("min_response_length", 15)
        self.max_length = cfg.get("max_response_length", 500)
        self._model = cfg.get("model", "")
        self._skip_patterns = cfg.get("skip_patterns", [
            "Erledigt", "Verstanden", "Wird gemacht",
        ])

    def _get_model(self) -> str:
        if self._model:
            from .config import resolve_model
            return resolve_model(self._model, fallback_tier="fast")
        return settings.model_fast

    def _should_rewrite(self, response: str, category: str = "") -> bool:
        """Prueft ob ein Rewriting sinnvoll ist."""
        if not self.enabled:
            return False

        response = response.strip()

        # Zu kurz oder zu lang
        if len(response) < self.min_length or len(response) > self.max_length:
            return False

        # Bereits gute Kurzantworten nicht umschreiben
        if response.rstrip(".!") in self._skip_patterns:
            return False

        # Reine Geraetebefehle brauchen kein Rewriting
        if category == "device_command" and len(response) < 30:
            return False

        return True

    async def rewrite(
        self,
        response: str,
        user_text: str = "",
        person: str = "",
        mood: str = "neutral",
        sarcasm_level: int = 3,
        category: str = "",
    ) -> str:
        """Schreibt eine Antwort um fuer natuerlicheren Ton.

        Args:
            response: Original-Antwort
            user_text: User-Frage (fuer Kontext)
            person: Name der Person
            mood: Stimmung des Users
            sarcasm_level: Sarkasmus-Level 1-5
            category: Request-Kategorie (device_command, knowledge, etc.)

        Returns:
            Umgeschriebene Antwort (oder Original bei Fehler/Skip)
        """
        if not self._should_rewrite(response, category):
            return response

        safe_response = _sanitize(response, max_len=500)
        safe_user = _sanitize(user_text, max_len=200)
        if not safe_response:
            return response

        title = get_person_title(person) if person else "Sir"

        mood_hints = {
            "good": "User ist gut drauf — etwas lockerer, ein Hauch Humor erlaubt.",
            "neutral": "Sachlich, ausgeglichen.",
            "stressed": "User ist gestresst — extrem kurz, keine Rueckfragen.",
            "frustrated": "User ist frustriert — sofort handeln, nicht rechtfertigen.",
            "tired": "User ist muede — minimal, ruhig, kein Humor.",
        }
        mood_hint = mood_hints.get(mood, mood_hints["neutral"])

        prompt = REWRITE_PROMPT.format(
            user_text=safe_user,
            response=safe_response,
            title=title,
            mood=mood,
            mood_hint=mood_hint,
            sarcasm_level=sarcasm_level,
        )

        try:
            result = await self.ollama.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self._get_model(),
                temperature=0.4,
                max_tokens=500,
                think=False,
            )

            content = result.get("message", {}).get("content", "").strip()

            # Think-Tags entfernen
            if "<think>" in content:
                think_end = content.find("</think>")
                if think_end != -1:
                    content = content[think_end + 8:].strip()

            # Validierung: Rewrite muss sinnvoll sein
            if not content or len(content) < 3:
                return response

            # Zu lang? Original behalten
            if len(content) > len(response) * 2.5:
                logger.debug("Rewrite zu lang (%d vs %d), behalte Original",
                             len(content), len(response))
                return response

            # Fakten-Check: Zahlen aus Original muessen im Rewrite vorkommen
            # Normalisiert Dezimalzahlen (21.5 == 21,5) fuer robusten Vergleich
            original_numbers = re.findall(r'\d+[.,]?\d*', response)
            if original_numbers:
                # Normalisiere: Komma→Punkt, dann als Float-Set vergleichen
                def _normalize_nums(nums: list[str]) -> set[str]:
                    result = set()
                    for n in nums:
                        normalized = n.replace(",", ".")
                        try:
                            result.add(str(float(normalized)))
                        except ValueError:
                            result.add(n)
                    return result

                orig_set = _normalize_nums(original_numbers)
                rewrite_numbers = re.findall(r'\d+[.,]?\d*', content)
                rewrite_set = _normalize_nums(rewrite_numbers)
                missing = orig_set - rewrite_set
                if missing:
                    logger.debug("Rewrite hat Zahlen verloren: %s, behalte Original", missing)
                    return response

            logger.debug("Response rewritten: '%s' -> '%s'",
                         response[:50], content[:50])
            return content

        except Exception as e:
            logger.debug("Response Rewriting fehlgeschlagen: %s", e)
            return response


# =====================================================================
# Unified Interface
# =====================================================================

class LLMEnhancer:
    """Zentrale Klasse die alle LLM-Enhancements buendelt."""

    def __init__(self, ollama: OllamaClient):
        self.ollama = ollama
        self.smart_intent = SmartIntentRecognizer(ollama)
        self.summarizer = ConversationSummarizer(ollama)
        self.proactive = ProactiveSuggester(ollama)
        self.rewriter = ResponseRewriter(ollama)

        cfg = yaml_config.get("llm_enhancer", {})
        self.enabled = cfg.get("enabled", True)

        logger.info(
            "LLM Enhancer initialisiert (intent=%s, summary=%s, proactive=%s, rewrite=%s)",
            self.smart_intent.enabled, self.summarizer.enabled,
            self.proactive.enabled, self.rewriter.enabled,
        )
