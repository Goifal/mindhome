"""
TTS Enhancer - Phase 9: Natürlichere Sprachausgabe mit SSML.

Generiert SSML-Tags basierend auf Nachrichtentyp und Kontext:
- Pausen vor wichtigen Informationen
- Sprechgeschwindigkeit variiert mit Inhalt
- Betonung bei Warnungen und Fragen
- Flüstermodus bei Nacht oder auf Befehl

Nachrichtentypen:
  confirmation - Kurze Bestätigung ("Erledigt.")
  warning      - Warnung oder Alarm
  briefing     - Morgen-Briefing, Status-Report
  greeting     - Begrüßung
  question     - Rückfrage an den User
  casual       - Normale Antwort
"""

import logging
import re
from datetime import datetime
from typing import Optional
from xml.sax.saxutils import escape as xml_escape  # P-2: Modul-Ebene statt pro Aufruf

from .config import yaml_config

logger = logging.getLogger(__name__)

# P-3: Vorcompilierte Regex-Patterns für Warn-Wörter (statt re.compile pro Aufruf)
_EMPHASIS_WORDS = [
    "warnung", "achtung", "vorsicht", "offen", "alarm",
    "notfall", "gefahr", "sofort",
]
_EMPHASIS_PATTERNS = {
    word: re.compile(re.escape(word), re.IGNORECASE)
    for word in _EMPHASIS_WORDS
}

# Englische Titel/Anreden die vom deutschen TTS falsch ausgesprochen werden.
# Diese werden im SSML mit <lang xml:lang="en-US"> gewrappt damit die
# TTS-Engine auf englische Phonetik wechselt.
_ENGLISH_TITLES = ["Sir", "Ma'am", "Ma'am", "Madam"]
_ENGLISH_TITLE_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in _ENGLISH_TITLES) + r")\b",
    re.IGNORECASE,
)


# Nachrichtentyp-Erkennung via Keywords
MESSAGE_TYPE_PATTERNS = {
    "warning": [
        "warnung", "achtung", "vorsicht", "alarm", "notfall", "gefahr",
        "offen", "läuft seit", "vergessen", "offline", "fehler",
    ],
    "greeting": [
        "guten morgen", "guten abend", "guten tag", "willkommen",
        "hallo", "gute nacht", "moin",
    ],
    "briefing": [
        "briefing", "zusammenfassung", "status", "bericht",
        "heute steht an", "wetter", "termine", "überblick",
    ],
    "confirmation": [
        "erledigt", "gemacht", "ist passiert", "wie gewünscht",
        "selbstverständlich", "kein problem",
        "geht klar", "sofort",
    ],
    "question": [
        "soll ich", "möchtest du", "welchen raum", "noch relevant",
        "darf ich", "meinst du",
    ],
}


class TTSEnhancer:
    """Verbessert TTS-Ausgabe mit SSML und adaptiver Lautstärke."""

    def __init__(self):
        # TTS Konfiguration
        tts_cfg = yaml_config.get("tts", {})
        self.ssml_enabled = tts_cfg.get("ssml_enabled", False)
        self.prosody_variation = tts_cfg.get("prosody_variation", False)

        # Sprechgeschwindigkeit pro Typ
        speed_cfg = tts_cfg.get("speed", {})
        self.speed_map = {
            "confirmation": speed_cfg.get("confirmation", 105),
            "warning": speed_cfg.get("warning", 85),
            "briefing": speed_cfg.get("briefing", 95),
            "status": speed_cfg.get("status", 95),
            "greeting": speed_cfg.get("greeting", 100),
            "question": speed_cfg.get("question", 100),
            "casual": speed_cfg.get("casual", 100),
        }

        # Pitch pro Typ (Phase 9.1)
        pitch_cfg = tts_cfg.get("pitch", {})
        self.pitch_map = {
            "confirmation": pitch_cfg.get("confirmation", "+5%"),
            "warning": pitch_cfg.get("warning", "-10%"),
            "briefing": pitch_cfg.get("briefing", "0%"),
            "status": pitch_cfg.get("status", "0%"),
            "greeting": pitch_cfg.get("greeting", "+5%"),
            "question": pitch_cfg.get("question", "+10%"),
            "casual": pitch_cfg.get("casual", "0%"),
        }

        # Pausen
        pause_cfg = tts_cfg.get("pauses", {})
        self.pause_important = pause_cfg.get("before_important", 300)
        self.pause_sentence = pause_cfg.get("between_sentences", 200)
        self.pause_greeting = pause_cfg.get("after_greeting", 400)

        # Flüstermodus-Trigger
        self.whisper_triggers = tts_cfg.get("whisper_triggers", [
            "psst", "leise", "flüster", "whisper"
        ])
        self.whisper_cancel = tts_cfg.get("whisper_cancel_triggers", [
            "normal", "laut", "normale lautstärke"
        ])

        # Volume Konfiguration
        vol_cfg = yaml_config.get("volume", {})

        def _safe_float(val, default: float) -> float:
            try:
                return float(val)
            except (ValueError, TypeError):
                return default

        def _safe_int(val, default: int) -> int:
            try:
                return int(val)
            except (ValueError, TypeError):
                return default

        self.vol_day = _safe_float(vol_cfg.get("day", 0.8), 0.8)
        self.vol_evening = _safe_float(vol_cfg.get("evening", 0.5), 0.5)
        self.vol_night = _safe_float(vol_cfg.get("night", 0.3), 0.3)
        self.vol_sleeping = _safe_float(vol_cfg.get("sleeping", 0.2), 0.2)
        self.vol_emergency = _safe_float(vol_cfg.get("emergency", 1.0), 1.0)
        self.vol_whisper = _safe_float(vol_cfg.get("whisper", 0.15), 0.15)
        self.evening_start = _safe_int(vol_cfg.get("evening_start", 22), 22)
        self.night_start = _safe_int(vol_cfg.get("night_start", 0), 0)
        self.morning_start = _safe_int(vol_cfg.get("morning_start", 7), 7)

        # Auto-Nacht-Whisper: Automatisch Flüstern zwischen bestimmten Uhrzeiten
        self.auto_night_whisper = tts_cfg.get("auto_night_whisper", True)
        self.auto_whisper_start = _safe_int(vol_cfg.get("auto_whisper_start", 23), 23)
        self.auto_whisper_end = _safe_int(vol_cfg.get("auto_whisper_end", 6), 6)

        # Zustand
        self._whisper_mode = False

        logger.info(
            "TTSEnhancer initialisiert (SSML: %s, Prosody-Variation: %s, Whisper-Triggers: %d)",
            self.ssml_enabled, self.prosody_variation, len(self.whisper_triggers),
        )

    # Negations-Muster: Wenn ein Warning-Keyword in negiertem Kontext steht,
    # ist es keine echte Warnung (z.B. "keine Alarme", "kein Fehler").
    _NEGATION_PREFIXES = re.compile(
        r"\b(?:kein|keine|keinen|keinem|keiner|ohne|nichts|nie|niemals|nicht)\s+",
        re.IGNORECASE,
    )

    def classify_message(self, text: str) -> str:
        """
        Klassifiziert den Nachrichtentyp.

        Returns:
            Einer von: confirmation, warning, briefing, greeting, question, casual
        """
        text_lower = text.lower()

        for msg_type, patterns in MESSAGE_TYPE_PATTERNS.items():
            if any(p in text_lower for p in patterns):
                # Warning-Guard: Pruefen ob Keywords in negiertem Kontext stehen
                # z.B. "keine Alarme" → kein Warning, "Alarm ausgeloest" → Warning
                if msg_type == "warning":
                    matched_patterns = [p for p in patterns if p in text_lower]
                    all_negated = all(
                        bool(self._NEGATION_PREFIXES.search(
                            text_lower[:text_lower.index(p)][-30:] if text_lower.index(p) > 0 else ""
                        ))
                        for p in matched_patterns
                    )
                    if all_negated:
                        continue  # Alle Warning-Keywords sind negiert → kein Warning
                return msg_type

        # Frage erkennen
        if text.rstrip().endswith("?"):
            return "question"

        return "casual"

    def enhance(self, text: str, message_type: Optional[str] = None,
                urgency: str = "medium", activity: str = "") -> dict:
        """
        Verbessert einen Text für TTS-Ausgabe.

        Args:
            text: Originaltext
            message_type: Optional manueller Typ (sonst auto-detect)
            urgency: Dringlichkeit (critical, high, medium, low)
            activity: Aktuelle Aktivität des Users (sleeping, focused, etc.)

        Returns:
            Dict mit:
                text: Original-Text
                ssml: SSML-erweiterter Text (oder Original wenn SSML aus)
                message_type: Erkannter Nachrichtentyp
                speed: Sprechgeschwindigkeit (%)
                volume: Empfohlene Lautstärke (0.0-1.0)
        """
        if not message_type:
            message_type = self.classify_message(text)

        if self.prosody_variation:
            speed = self.speed_map.get(message_type, 100)
            pitch = self.pitch_map.get(message_type, "0%")
        else:
            speed = 100
            pitch = "0%"
        volume = self.get_volume(activity=activity, message_type=message_type, urgency=urgency)

        if self.ssml_enabled:
            ssml = self._generate_ssml(text, message_type, speed, pitch)
        else:
            ssml = text

        return {
            "text": text,
            "ssml": ssml,
            "message_type": message_type,
            "speed": speed,
            "pitch": pitch,
            "volume": volume,
        }

    def get_volume(self, activity: str = "", message_type: str = "casual",
                   urgency: str = "medium") -> float:
        """
        Bestimmt die optimale Lautstärke.

        Priorität: Notfall > Flüstermodus > Aktivität > Tageszeit
        """
        # Notfall immer laut
        if urgency == "critical":
            return self.vol_emergency

        # Flüstermodus (manuell oder Auto-Nacht)
        if self._whisper_mode or self._is_auto_night_whisper():
            return self.vol_whisper

        # Aktivitätsbasiert
        if activity == "sleeping":
            return self.vol_sleeping

        # Tageszeit-basiert
        hour = datetime.now().hour
        if self.night_start > self.morning_start:
            # Über Mitternacht: z.B. 22-6
            if hour >= self.night_start or hour < self.morning_start:
                return self.vol_night
        elif self.night_start <= hour < self.morning_start:
            return self.vol_night
        elif hour >= self.evening_start:
            return self.vol_evening

        return self.vol_day

    def check_whisper_command(self, text: str) -> Optional[str]:
        """
        Prüft ob der Text einen Flüstermodus-Befehl enthaelt.

        Nutzt Wortgrenzen-Matching um Fehlerkennungen zu vermeiden
        (z.B. Substring-Treffer in Gerätebefehlen).

        Returns:
            "activate" wenn Flüstern aktiviert werden soll
            "deactivate" wenn deaktiviert
            None wenn kein Befehl
        """
        text_lower = text.lower().strip()

        if any(re.search(rf"\b{re.escape(t)}\b", text_lower) for t in self.whisper_cancel):
            if self._whisper_mode:
                self._whisper_mode = False
                logger.info("Flüstermodus deaktiviert")
                return "deactivate"

        if any(re.search(rf"\b{re.escape(t)}\b", text_lower) for t in self.whisper_triggers):
            self._whisper_mode = True
            logger.info("Flüstermodus aktiviert")
            return "activate"

        return None

    @property
    def is_whisper_mode(self) -> bool:
        """Gibt zurück ob Flüstermodus aktiv ist (manuell oder Auto-Nacht)."""
        return self._whisper_mode or self._is_auto_night_whisper()

    def _is_auto_night_whisper(self) -> bool:
        """Prüft ob Auto-Nacht-Whisper aktiv sein sollte."""
        if not self.auto_night_whisper:
            return False
        hour = datetime.now().hour
        if self.auto_whisper_start > self.auto_whisper_end:
            # Über Mitternacht: z.B. 23-6
            return hour >= self.auto_whisper_start or hour < self.auto_whisper_end
        return self.auto_whisper_start <= hour < self.auto_whisper_end

    def _generate_ssml(self, text: str, message_type: str, speed: int,
                        pitch: str = "0%") -> str:
        """
        Generiert SSML aus Text und Nachrichtentyp.

        Piper TTS unterstützt einen Teil von SSML:
        - <break> für Pausen
        - <prosody rate="..." pitch="..."> für Geschwindigkeit + Tonhöhe
        - <emphasis> für Betonung
        """
        parts = []

        # Sprechgeschwindigkeit + Pitch
        prosody_attrs = ""
        if speed != 100:
            prosody_attrs += f' rate="{speed}%"'
        if pitch and pitch != "0%":
            prosody_attrs += f' pitch="{pitch}"'

        if prosody_attrs:
            parts.append(f'<speak><prosody{prosody_attrs}>')
        else:
            parts.append('<speak>')

        # F-059: User-Text XML-escapen um SSML-Injection zu verhindern
        # P-2: xml_escape jetzt auf Modul-Ebene importiert
        text = xml_escape(text)

        # Englische Titel (Sir, Ma'am) mit <lang> wrappen damit TTS
        # sie nicht mit deutscher Phonetik ausspricht.
        text = _ENGLISH_TITLE_PATTERN.sub(
            r'<lang xml:lang="en-US">\1</lang>', text
        )

        # Text in Sätze aufteilen
        sentences = self._split_sentences(text)

        for i, sentence in enumerate(sentences):
            sentence = sentence.strip()
            if not sentence:
                continue

            # Erster Satz bei Begrüßung: Pause danach
            if i == 0 and message_type == "greeting":
                parts.append(sentence)
                parts.append(f'<break time="{self.pause_greeting}ms"/>')
                continue

            # Warnungen: Pause vor wichtigen Wörtern + Emphasis
            if message_type == "warning":
                sentence = self._add_warning_emphasis(sentence)
                if i == 0:
                    parts.append(f'<break time="{self.pause_important}ms"/>')

            # Briefing: Pause zwischen Bausteinen
            if message_type == "briefing" and i > 0:
                parts.append(f'<break time="{self.pause_important}ms"/>')

            parts.append(sentence)

            # Pause zwischen Sätzen
            if i < len(sentences) - 1:
                parts.append(f'<break time="{self.pause_sentence}ms"/>')

        if prosody_attrs:
            parts.append('</prosody></speak>')
        else:
            parts.append('</speak>')

        return "".join(parts)

    def _add_warning_emphasis(self, sentence: str) -> str:
        """Fuegt Betonung bei Warn-Wörtern hinzu."""
        # P-3: Vorcompilierte Patterns aus Modul-Ebene verwenden
        for word, pattern in _EMPHASIS_PATTERNS.items():
            if pattern.search(sentence):
                sentence = pattern.sub(
                    f'<emphasis level="strong">{word.capitalize()}</emphasis>',
                    sentence,
                )
        return sentence

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Teilt Text in Sätze auf."""
        # Einfaches Splitting an Satzzeichen
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s for s in sentences if s.strip()]

    # ------------------------------------------------------------------
    # Phase 9.4: Narration Delays + Fade
    # ------------------------------------------------------------------

    def enhance_narration(self, segments: list[dict]) -> dict:
        """Erzeugt eine SSML-Narration mit Delays und Fade-Effekten.

        Args:
            segments: Liste von Segmenten mit:
                text: str - Sprechtext
                pause_before_ms: int - Pause vor dem Segment (optional)
                pause_after_ms: int - Pause nach dem Segment (optional)
                speed: int - Geschwindigkeit % (optional)
                pitch: str - Tonhöhe (optional)
                volume: str - Lautstärke soft/medium/loud/x-loud (optional)
                emphasis: str - Betonungslevel moderate/strong (optional)

        Returns:
            Dict mit ssml, total_estimated_duration_ms
        """
        parts = ['<speak>']
        total_duration = 0

        for seg in segments:
            text = seg.get("text", "")
            if not text:
                continue
            text = xml_escape(text)

            # Pause vor dem Segment (Delay)
            pause_before = seg.get("pause_before_ms", 0)
            if pause_before > 0:
                parts.append(f'<break time="{pause_before}ms"/>')
                total_duration += pause_before

            # Prosody-Attribute
            prosody_attrs = ""
            seg_speed = seg.get("speed")
            seg_pitch = seg.get("pitch")
            seg_volume = seg.get("volume")
            if seg_speed and seg_speed != 100:
                prosody_attrs += f' rate="{seg_speed}%"'
            if seg_pitch:
                prosody_attrs += f' pitch="{seg_pitch}"'
            if seg_volume:
                prosody_attrs += f' volume="{seg_volume}"'

            # Emphasis
            emphasis = seg.get("emphasis")
            inner_text = text
            if emphasis:
                inner_text = f'<emphasis level="{emphasis}">{text}</emphasis>'

            if prosody_attrs:
                parts.append(f'<prosody{prosody_attrs}>{inner_text}</prosody>')
            else:
                parts.append(inner_text)

            # Geschaetzte Sprechdauer: ~150 WPM = 2.5 Wörter/Sek
            word_count = len(text.split())
            effective_speed = (seg_speed or 100) / 100.0
            speak_ms = int(word_count / (2.5 * effective_speed) * 1000)
            total_duration += speak_ms

            # Pause nach dem Segment (Fade-Effekt simulieren)
            pause_after = seg.get("pause_after_ms", 0)
            if pause_after > 0:
                parts.append(f'<break time="{pause_after}ms"/>')
                total_duration += pause_after

        parts.append('</speak>')
        return {
            "ssml": "".join(parts),
            "total_estimated_duration_ms": total_duration,
        }
