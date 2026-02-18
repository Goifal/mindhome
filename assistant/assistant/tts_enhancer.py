"""
TTS Enhancer - Phase 9: Natuerlichere Sprachausgabe mit SSML.

Generiert SSML-Tags basierend auf Nachrichtentyp und Kontext:
- Pausen vor wichtigen Informationen
- Sprechgeschwindigkeit variiert mit Inhalt
- Betonung bei Warnungen und Fragen
- Fluestermodus bei Nacht oder auf Befehl

Nachrichtentypen:
  confirmation - Kurze Bestaetigung ("Erledigt.")
  warning      - Warnung oder Alarm
  briefing     - Morgen-Briefing, Status-Report
  greeting     - Begruessung
  question     - Rueckfrage an den User
  casual       - Normale Antwort
"""

import logging
import re
from datetime import datetime
from typing import Optional

from .config import yaml_config

logger = logging.getLogger(__name__)


# Nachrichtentyp-Erkennung via Keywords
MESSAGE_TYPE_PATTERNS = {
    "warning": [
        "warnung", "achtung", "vorsicht", "alarm", "notfall", "gefahr",
        "offen", "laeuft seit", "vergessen", "offline", "fehler",
    ],
    "greeting": [
        "guten morgen", "guten abend", "guten tag", "willkommen",
        "hallo", "gute nacht", "moin",
    ],
    "briefing": [
        "briefing", "zusammenfassung", "status", "bericht",
        "heute steht an", "wetter", "termine", "ueberblick",
    ],
    "confirmation": [
        "erledigt", "gemacht", "ist passiert", "wie gewuenscht",
        "aber natuerlich", "selbstverstaendlich", "kein problem",
        "geht klar", "sofort",
    ],
    "question": [
        "soll ich", "moechtest du", "welchen raum", "noch relevant",
        "darf ich", "meinst du",
    ],
}


class TTSEnhancer:
    """Verbessert TTS-Ausgabe mit SSML und adaptiver Lautstaerke."""

    def __init__(self):
        # TTS Konfiguration
        tts_cfg = yaml_config.get("tts", {})
        self.ssml_enabled = tts_cfg.get("ssml_enabled", True)

        # Sprechgeschwindigkeit pro Typ
        speed_cfg = tts_cfg.get("speed", {})
        self.speed_map = {
            "confirmation": speed_cfg.get("confirmation", 105),
            "warning": speed_cfg.get("warning", 85),
            "briefing": speed_cfg.get("briefing", 95),
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
            "greeting": pitch_cfg.get("greeting", "+5%"),
            "question": pitch_cfg.get("question", "+10%"),
            "casual": pitch_cfg.get("casual", "0%"),
        }

        # Pausen
        pause_cfg = tts_cfg.get("pauses", {})
        self.pause_important = pause_cfg.get("before_important", 300)
        self.pause_sentence = pause_cfg.get("between_sentences", 200)
        self.pause_greeting = pause_cfg.get("after_greeting", 400)

        # Fluestermodus-Trigger
        self.whisper_triggers = tts_cfg.get("whisper_triggers", [
            "psst", "leise", "fluester", "whisper"
        ])
        self.whisper_cancel = tts_cfg.get("whisper_cancel_triggers", [
            "normal", "laut", "normale lautstaerke"
        ])

        # Volume Konfiguration
        vol_cfg = yaml_config.get("volume", {})
        self.vol_day = vol_cfg.get("day", 0.8)
        self.vol_evening = vol_cfg.get("evening", 0.5)
        self.vol_night = vol_cfg.get("night", 0.3)
        self.vol_sleeping = vol_cfg.get("sleeping", 0.2)
        self.vol_emergency = vol_cfg.get("emergency", 1.0)
        self.vol_whisper = vol_cfg.get("whisper", 0.15)
        self.evening_start = vol_cfg.get("evening_start", 22)
        self.night_start = vol_cfg.get("night_start", 0)
        self.morning_start = vol_cfg.get("morning_start", 7)

        # Auto-Nacht-Whisper: Automatisch Fluestern zwischen bestimmten Uhrzeiten
        self.auto_night_whisper = tts_cfg.get("auto_night_whisper", True)
        self.auto_whisper_start = vol_cfg.get("auto_whisper_start", 23)
        self.auto_whisper_end = vol_cfg.get("auto_whisper_end", 6)

        # Zustand
        self._whisper_mode = False

        logger.info(
            "TTSEnhancer initialisiert (SSML: %s, Whisper-Triggers: %d)",
            self.ssml_enabled, len(self.whisper_triggers),
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
                return msg_type

        # Frage erkennen
        if text.rstrip().endswith("?"):
            return "question"

        return "casual"

    def enhance(self, text: str, message_type: Optional[str] = None,
                urgency: str = "medium", activity: str = "") -> dict:
        """
        Verbessert einen Text fuer TTS-Ausgabe.

        Args:
            text: Originaltext
            message_type: Optional manueller Typ (sonst auto-detect)
            urgency: Dringlichkeit (critical, high, medium, low)
            activity: Aktuelle Aktivitaet des Users (sleeping, focused, etc.)

        Returns:
            Dict mit:
                text: Original-Text
                ssml: SSML-erweiterter Text (oder Original wenn SSML aus)
                message_type: Erkannter Nachrichtentyp
                speed: Sprechgeschwindigkeit (%)
                volume: Empfohlene Lautstaerke (0.0-1.0)
        """
        if not message_type:
            message_type = self.classify_message(text)

        speed = self.speed_map.get(message_type, 100)
        pitch = self.pitch_map.get(message_type, "0%")
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
        Bestimmt die optimale Lautstaerke.

        Prioritaet: Notfall > Fluestermodus > Aktivitaet > Tageszeit
        """
        # Notfall immer laut
        if urgency == "critical":
            return self.vol_emergency

        # Fluestermodus (manuell oder Auto-Nacht)
        if self._whisper_mode or self._is_auto_night_whisper():
            return self.vol_whisper

        # Aktivitaetsbasiert
        if activity == "sleeping":
            return self.vol_sleeping

        # Tageszeit-basiert
        hour = datetime.now().hour
        if self.night_start <= hour < self.morning_start:
            return self.vol_night
        elif hour >= self.evening_start:
            return self.vol_evening

        return self.vol_day

    def check_whisper_command(self, text: str) -> Optional[str]:
        """
        Prueft ob der Text einen Fluestermodus-Befehl enthaelt.

        Returns:
            "activate" wenn Fluestern aktiviert werden soll
            "deactivate" wenn deaktiviert
            None wenn kein Befehl
        """
        text_lower = text.lower().strip()

        if any(t in text_lower for t in self.whisper_cancel):
            if self._whisper_mode:
                self._whisper_mode = False
                logger.info("Fluestermodus deaktiviert")
                return "deactivate"

        if any(t in text_lower for t in self.whisper_triggers):
            self._whisper_mode = True
            logger.info("Fluestermodus aktiviert")
            return "activate"

        return None

    @property
    def is_whisper_mode(self) -> bool:
        """Gibt zurueck ob Fluestermodus aktiv ist (manuell oder Auto-Nacht)."""
        return self._whisper_mode or self._is_auto_night_whisper()

    def _is_auto_night_whisper(self) -> bool:
        """Prueft ob Auto-Nacht-Whisper aktiv sein sollte."""
        if not self.auto_night_whisper:
            return False
        hour = datetime.now().hour
        if self.auto_whisper_start > self.auto_whisper_end:
            # Ueber Mitternacht: z.B. 23-6
            return hour >= self.auto_whisper_start or hour < self.auto_whisper_end
        return self.auto_whisper_start <= hour < self.auto_whisper_end

    def _generate_ssml(self, text: str, message_type: str, speed: int,
                        pitch: str = "0%") -> str:
        """
        Generiert SSML aus Text und Nachrichtentyp.

        Piper TTS unterstuetzt einen Teil von SSML:
        - <break> fuer Pausen
        - <prosody rate="..." pitch="..."> fuer Geschwindigkeit + Tonhoehe
        - <emphasis> fuer Betonung
        """
        parts = []

        # Sprechgeschwindigkeit + Pitch
        prosody_attrs = ""
        if speed != 100:
            prosody_attrs += f' rate="{speed}%"'
        if pitch and pitch != "0%":
            prosody_attrs += f' pitch="{pitch}"'

        parts.append(f'<speak><prosody{prosody_attrs}>')

        # Text in Saetze aufteilen
        sentences = self._split_sentences(text)

        for i, sentence in enumerate(sentences):
            sentence = sentence.strip()
            if not sentence:
                continue

            # Erster Satz bei Begruessung: Pause danach
            if i == 0 and message_type == "greeting":
                parts.append(sentence)
                parts.append(f'<break time="{self.pause_greeting}ms"/>')
                continue

            # Warnungen: Pause vor wichtigen Woertern + Emphasis
            if message_type == "warning":
                sentence = self._add_warning_emphasis(sentence)
                if i == 0:
                    parts.append(f'<break time="{self.pause_important}ms"/>')

            # Briefing: Pause zwischen Bausteinen
            if message_type == "briefing" and i > 0:
                parts.append(f'<break time="{self.pause_important}ms"/>')

            parts.append(sentence)

            # Pause zwischen Saetzen
            if i < len(sentences) - 1:
                parts.append(f'<break time="{self.pause_sentence}ms"/>')

        parts.append('</prosody></speak>')

        return "".join(parts)

    def _add_warning_emphasis(self, sentence: str) -> str:
        """Fuegt Betonung bei Warn-Woertern hinzu."""
        emphasis_words = [
            "warnung", "achtung", "vorsicht", "offen", "alarm",
            "notfall", "gefahr", "sofort",
        ]
        for word in emphasis_words:
            # Case-insensitive ersetzen mit Emphasis-Tag
            pattern = re.compile(re.escape(word), re.IGNORECASE)
            if pattern.search(sentence):
                sentence = pattern.sub(
                    f'<emphasis level="strong">{word.capitalize()}</emphasis>',
                    sentence,
                    count=1,
                )
                break  # Nur ein Wort pro Satz betonen
        return sentence

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Teilt Text in Saetze auf."""
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
                pitch: str - Tonhoehe (optional)
                volume: str - Lautstaerke soft/medium/loud/x-loud (optional)
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

            # Geschaetzte Sprechdauer: ~150 WPM = 2.5 Woerter/Sek
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
