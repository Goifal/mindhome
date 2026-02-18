"""
Mood Detector - Phase 3: Stimmungs-, Stress- und Muedigkeitserkennung.
Phase 9: Erweitert um Sprach-Metadaten-Analyse (Voice Emotion Detection).

Analysiert User-Interaktionsmuster und erkennt:
- Stimmung (gut, neutral, gestresst, frustriert, muede)
- Stress (schnelle aufeinanderfolgende Befehle, ungeduldige Sprache)
- Muedigkeit (spaete Uhrzeit + kurze Nachrichten + muede Keywords)
- Frustration (Wiederholungen, negative Keywords, Ausrufezeichen)
- Phase 9: Sprechgeschwindigkeit (schnell = Stress, langsam = Muedigkeit)
- Phase 9: Lautstaerke-Level (laut = aufgeregt, leise = muede/unsicher)

Nutzt Redis fuer die Interaktions-History und Pattern-Erkennung.
"""

import logging
import time
from collections import deque
from datetime import datetime
from typing import Optional

import redis.asyncio as redis

from .config import yaml_config

logger = logging.getLogger(__name__)

# Stimmungs-Zustände
MOOD_GOOD = "good"
MOOD_NEUTRAL = "neutral"
MOOD_STRESSED = "stressed"
MOOD_FRUSTRATED = "frustrated"
MOOD_TIRED = "tired"

# Keywords fuer Stimmungserkennung (Defaults, ueberschrieben durch settings.yaml)
_mood_cfg = yaml_config.get("mood", {})

POSITIVE_KEYWORDS = _mood_cfg.get("positive_keywords", [
    "danke", "super", "perfekt", "toll", "geil", "nice", "cool", "genau",
    "klasse", "wunderbar", "prima", "top", "gut gemacht", "laeuft",
    "haha", "lol", "witzig", "lustig", "freut mich", "ja gerne",
])

NEGATIVE_KEYWORDS = _mood_cfg.get("negative_keywords", [
    "nein", "falsch", "nicht das", "stimmt nicht", "geht nicht",
    "funktioniert nicht", "kaputt", "nervig", "nervt", "schlecht",
    "mist", "verdammt", "scheisse", "bloed", "egal",
])

IMPATIENT_KEYWORDS = _mood_cfg.get("impatient_keywords", [
    "schnell", "sofort", "jetzt", "los", "mach schon", "beeil dich",
    "endlich", "nochmal", "schon wieder", "hab ich doch gesagt",
    "zum dritten mal", "wie oft noch", "kapierst du",
])

TIRED_KEYWORDS = _mood_cfg.get("tired_keywords", [
    "muede", "schlafen", "bett", "gute nacht", "nacht",
    "gaehn", "erschoepft", "fertig", "genug fuer heute",
    "schluss fuer heute", "feierabend", "ins bett",
])

FRUSTRATED_PREFIXES = [
    "nein ", "nein!", "nein,", "falsch!", "nicht!", "stopp!",
]


class MoodDetector:
    """Erkennt Stimmung, Stress und Muedigkeit aus User-Interaktionen."""

    def __init__(self):
        self.redis: Optional[redis.Redis] = None

        # In-Memory Ring-Buffer fuer schnelle Pattern-Erkennung
        self._interaction_times: deque[float] = deque(maxlen=20)
        self._interaction_lengths: deque[int] = deque(maxlen=20)
        self._interaction_sentiments: deque[str] = deque(maxlen=10)
        self._last_texts: deque[str] = deque(maxlen=5)

        # Aktueller Zustand
        self._current_mood: str = MOOD_NEUTRAL
        self._stress_level: float = 0.0  # 0.0 = entspannt, 1.0 = maximal gestresst
        self._tiredness_level: float = 0.0  # 0.0 = wach, 1.0 = sehr muede
        self._frustration_count: int = 0
        self._positive_count: int = 0

        # Konfiguration
        mood_cfg = yaml_config.get("mood", {})
        self.rapid_command_threshold = mood_cfg.get("rapid_command_seconds", 5)
        self.stress_decay_seconds = mood_cfg.get("stress_decay_seconds", 300)
        self.frustration_threshold = mood_cfg.get("frustration_threshold", 3)
        self.tired_hour_start = mood_cfg.get("tired_hour_start", 23)
        self.tired_hour_end = mood_cfg.get("tired_hour_end", 5)

        # Stress-Boost Werte (konfigurierbar via settings.yaml)
        self.rapid_command_stress_boost = mood_cfg.get("rapid_command_stress_boost", 0.15)
        self.positive_stress_reduction = mood_cfg.get("positive_stress_reduction", 0.1)
        self.negative_stress_boost = mood_cfg.get("negative_stress_boost", 0.1)
        self.impatient_stress_boost = mood_cfg.get("impatient_stress_boost", 0.2)
        self.tired_boost = mood_cfg.get("tired_boost", 0.3)
        self.repetition_stress_boost = mood_cfg.get("repetition_stress_boost", 0.15)

        self._last_decay_time = time.time()

        # Phase 9: Voice Analysis Konfiguration
        voice_cfg = yaml_config.get("voice_analysis", {})
        self.voice_enabled = voice_cfg.get("enabled", True)
        self.wpm_fast = voice_cfg.get("wpm_fast", 180)
        self.wpm_slow = voice_cfg.get("wpm_slow", 80)
        self.wpm_normal = voice_cfg.get("wpm_normal", 130)
        self.voice_weight = voice_cfg.get("voice_weight", 0.3)
        self._last_voice_signals: list[str] = []

    async def initialize(self, redis_client: Optional[redis.Redis] = None):
        """Initialisiert mit Redis."""
        self.redis = redis_client

        # Vorherigen Zustand aus Redis laden
        if self.redis:
            try:
                saved = await self.redis.hgetall("mha:mood:state")
                if saved:
                    self._current_mood = saved.get("mood", MOOD_NEUTRAL)
                    self._stress_level = float(saved.get("stress", 0.0))
                    self._tiredness_level = float(saved.get("tiredness", 0.0))
            except Exception as e:
                logger.debug("Mood-State nicht geladen: %s", e)

        logger.info("MoodDetector initialisiert (Stimmung: %s)", self._current_mood)

    async def analyze(self, text: str, person: str = "") -> dict:
        """
        Analysiert eine User-Eingabe und aktualisiert die Stimmung.

        Args:
            text: User-Text
            person: Name der Person

        Returns:
            Dict mit mood, stress_level, tiredness_level, signals
        """
        now = time.time()
        self._apply_decay(now)

        signals = []

        # 1. Zeitliches Muster: Schnelle aufeinanderfolgende Befehle = Stress
        if self._interaction_times:
            time_since_last = now - self._interaction_times[-1]
            if time_since_last < self.rapid_command_threshold:
                self._stress_level = min(1.0, self._stress_level + self.rapid_command_stress_boost)
                signals.append("rapid_commands")

        # 2. Text-Analyse
        text_lower = text.lower().strip()
        text_len = len(text.split())

        # Positive Signale
        if any(kw in text_lower for kw in POSITIVE_KEYWORDS):
            self._positive_count += 1
            self._stress_level = max(0.0, self._stress_level - self.positive_stress_reduction)
            self._frustration_count = max(0, self._frustration_count - 1)
            signals.append("positive_language")

        # Negative/frustrierte Signale
        if any(kw in text_lower for kw in NEGATIVE_KEYWORDS):
            self._frustration_count += 1
            self._stress_level = min(1.0, self._stress_level + self.negative_stress_boost)
            signals.append("negative_language")

        # Ungeduldige Signale
        if any(kw in text_lower for kw in IMPATIENT_KEYWORDS):
            self._stress_level = min(1.0, self._stress_level + self.impatient_stress_boost)
            self._frustration_count += 1
            signals.append("impatient_language")

        # Muedigkeits-Keywords
        if any(kw in text_lower for kw in TIRED_KEYWORDS):
            self._tiredness_level = min(1.0, self._tiredness_level + self.tired_boost)
            signals.append("tired_keywords")

        # Frustrierte Wiederholung (gleicher/aehnlicher Text wie vorher)
        if self._last_texts and self._is_repetition(text_lower):
            self._frustration_count += 2
            self._stress_level = min(1.0, self._stress_level + self.repetition_stress_boost)
            signals.append("repetition")

        # Ausrufezeichen = Ungeduld/Frustration
        exclamation_count = text.count("!")
        if exclamation_count >= 2:
            self._stress_level = min(1.0, self._stress_level + 0.1)
            signals.append("exclamation_marks")

        # Frustrierter Anfang
        if any(text_lower.startswith(p) for p in FRUSTRATED_PREFIXES):
            self._frustration_count += 1
            signals.append("frustrated_prefix")

        # Sehr kurze Nachrichten spaet abends = muede
        hour = datetime.now().hour
        is_late = hour >= self.tired_hour_start or hour < self.tired_hour_end
        if is_late:
            self._tiredness_level = min(1.0, self._tiredness_level + 0.05)
            if text_len <= 3:
                self._tiredness_level = min(1.0, self._tiredness_level + 0.1)
                signals.append("short_late_message")

        # Interaktion aufzeichnen
        self._interaction_times.append(now)
        self._interaction_lengths.append(text_len)
        self._last_texts.append(text_lower)

        # 3. Gesamt-Stimmung bestimmen
        self._current_mood = self._determine_mood()

        # 4. In Redis speichern
        await self._save_state()

        result = {
            "mood": self._current_mood,
            "stress_level": round(self._stress_level, 2),
            "tiredness_level": round(self._tiredness_level, 2),
            "frustration_count": self._frustration_count,
            "signals": signals,
        }

        if signals:
            logger.info(
                "Mood: %s (Stress: %.2f, Muede: %.2f, Signale: %s)",
                self._current_mood, self._stress_level,
                self._tiredness_level, ", ".join(signals),
            )

        return result

    def get_current_mood(self) -> dict:
        """Gibt den aktuellen Stimmungszustand zurueck."""
        return {
            "mood": self._current_mood,
            "stress_level": round(self._stress_level, 2),
            "tiredness_level": round(self._tiredness_level, 2),
            "frustration_count": self._frustration_count,
            "positive_count": self._positive_count,
        }

    def _determine_mood(self) -> str:
        """Bestimmt die Gesamt-Stimmung aus allen Signalen."""
        # Muedigkeit hat Vorrang wenn sehr hoch
        if self._tiredness_level >= 0.6:
            return MOOD_TIRED

        # Frustration wenn mehrfach hintereinander negativ
        if self._frustration_count >= self.frustration_threshold:
            return MOOD_FRUSTRATED

        # Stress wenn Stresslevel hoch
        if self._stress_level >= 0.5:
            return MOOD_STRESSED

        # Gute Stimmung wenn positive Signale ueberwiegen
        if self._positive_count >= 2 and self._frustration_count == 0:
            return MOOD_GOOD

        return MOOD_NEUTRAL

    def _is_repetition(self, text: str) -> bool:
        """Prueft ob der Text eine Wiederholung ist."""
        for prev in self._last_texts:
            # Exakte Wiederholung
            if text == prev:
                return True
            # Aehnliche Wiederholung (gleiche Woerter)
            words = set(text.split())
            prev_words = set(prev.split())
            if len(words) > 1 and len(words & prev_words) / max(len(words), 1) > 0.7:
                return True
        return False

    def _apply_decay(self, now: float):
        """Laesst Stress und Frustration ueber Zeit abklingen."""
        elapsed = now - self._last_decay_time
        if elapsed > 60:  # Alle 60 Sekunden Decay
            decay_factor = elapsed / self.stress_decay_seconds
            self._stress_level = max(0.0, self._stress_level - decay_factor * 0.3)
            self._tiredness_level = max(0.0, self._tiredness_level - decay_factor * 0.1)
            if elapsed > 600:  # Nach 10 Minuten Pause: Frustration reset
                self._frustration_count = max(0, self._frustration_count - 1)
                self._positive_count = max(0, self._positive_count - 1)
            self._last_decay_time = now

    # ------------------------------------------------------------------
    # Emotionale Intelligenz (Phase 6.7)
    # ------------------------------------------------------------------

    def get_suggested_actions(self) -> list[dict]:
        """
        Gibt kontextbezogene Aktions-Vorschlaege basierend auf Stimmung zurueck.

        Returns:
            Liste von Aktions-Vorschlaegen mit:
                action: str - HA-Service oder Szene
                reason: str - Warum diese Aktion vorgeschlagen wird
                priority: str - low/medium/high
        """
        suggestions = []
        hour = datetime.now().hour

        if self._current_mood == MOOD_STRESSED:
            suggestions.append({
                "action": "scene.entspannung",
                "reason": "User wirkt gestresst - Entspannungs-Szene koennte helfen",
                "priority": "medium",
            })
            if self._stress_level >= 0.7:
                suggestions.append({
                    "action": "light.dimmen",
                    "reason": "Hoher Stress - gedimmtes Licht wirkt beruhigend",
                    "priority": "medium",
                    "params": {"brightness_pct": 40},
                })

        elif self._current_mood == MOOD_FRUSTRATED:
            suggestions.append({
                "action": "simplify_responses",
                "reason": "User ist frustriert - kuerzere Antworten, direkt handeln",
                "priority": "high",
            })
            if self._frustration_count >= 4:
                suggestions.append({
                    "action": "offer_help",
                    "reason": "Anhaltende Frustration - proaktiv Hilfe anbieten",
                    "priority": "high",
                })

        elif self._current_mood == MOOD_TIRED:
            if hour >= 22 or hour < 5:
                suggestions.append({
                    "action": "scene.gute_nacht",
                    "reason": "User ist muede und es ist spaet - Gute-Nacht-Routine vorschlagen",
                    "priority": "medium",
                })
            suggestions.append({
                "action": "reduce_notifications",
                "reason": "User ist muede - weniger proaktive Meldungen",
                "priority": "medium",
            })

        elif self._current_mood == MOOD_GOOD:
            if 18 <= hour <= 21:
                suggestions.append({
                    "action": "scene.gemuetlich",
                    "reason": "Gute Stimmung am Abend - Gemuetlichkeit verstaerken",
                    "priority": "low",
                })

        return suggestions

    async def execute_suggested_actions(self, executor) -> list[dict]:
        """
        Fuehrt die vorgeschlagenen Stimmungs-Aktionen tatsaechlich aus.

        Args:
            executor: FunctionExecutor-Instanz

        Returns:
            Liste der ausgefuehrten Aktionen mit Ergebnis
        """
        if not executor:
            return []

        suggestions = self.get_suggested_actions()
        executed = []

        for suggestion in suggestions:
            action = suggestion.get("action", "")
            priority = suggestion.get("priority", "low")

            # Nur interne Marker (kein HA-Service)
            if action in ("simplify_responses", "reduce_notifications", "offer_help"):
                continue

            # Szenen und Licht-Aktionen ausfuehren
            try:
                if action.startswith("scene."):
                    scene_name = action.split(".", 1)[1]
                    result = await executor.execute("activate_scene", {"scene": scene_name})
                    executed.append({
                        "action": action,
                        "reason": suggestion["reason"],
                        "result": result,
                    })
                elif action == "light.dimmen":
                    params = suggestion.get("params", {})
                    result = await executor.execute("set_light", {
                        "room": "wohnzimmer",
                        "brightness": params.get("brightness_pct", 40),
                    })
                    executed.append({
                        "action": action,
                        "reason": suggestion["reason"],
                        "result": result,
                    })
            except Exception as e:
                logger.warning("Mood-Aktion '%s' fehlgeschlagen: %s", action, e)

        if executed:
            logger.info("Mood-Aktionen ausgefuehrt: %d", len(executed))
        return executed

    def get_mood_prompt_hint(self) -> str:
        """
        Gibt einen Prompt-Hinweis basierend auf emotionalem Kontext zurueck.
        Wird in den System Prompt eingebaut fuer kontextsensitive Antworten.
        """
        hints = []

        if self._current_mood == MOOD_STRESSED:
            hints.append("User ist unter Stress. Antworte ruhig und effizient.")
            if self._stress_level >= 0.7:
                hints.append("Stress-Level sehr hoch. Schlage bei Gelegenheit eine Pause vor.")

        elif self._current_mood == MOOD_FRUSTRATED:
            hints.append("User ist frustriert. Nicht rechtfertigen, sondern loesen.")
            if self._frustration_count >= 4:
                hints.append("Anhaltende Frustration. Frage ob du anders helfen kannst.")

        elif self._current_mood == MOOD_TIRED:
            hints.append("User ist muede. Minimal antworten. Kein Humor.")

        elif self._current_mood == MOOD_GOOD:
            hints.append("User ist gut drauf. Etwas mehr Persoenlichkeit zeigen.")

        # Stress-Trend
        if len(self._interaction_sentiments) >= 3:
            recent = list(self._interaction_sentiments)[-3:]
            if all(s == "negative" for s in recent):
                hints.append("WARNUNG: 3x negativ hintereinander. Eskalation vermeiden.")

        return " ".join(hints)

    # ------------------------------------------------------------------
    # Phase 9: Voice Emotion Detection
    # ------------------------------------------------------------------

    def analyze_voice_metadata(self, metadata: dict) -> list[str]:
        """
        Phase 9: Analysiert Sprach-Metadaten fuer Stimmungserkennung.

        Args:
            metadata: Dict mit optionalen Feldern:
                wpm: float - Woerter pro Minute (Sprechgeschwindigkeit)
                volume: float - Lautstaerke (0.0-1.0)
                duration: float - Dauer der Aufnahme in Sekunden
                word_count: int - Anzahl erkannter Woerter

        Returns:
            Liste erkannter Voice-Signale
        """
        if not self.voice_enabled or not metadata:
            return []

        signals = []

        # Sprechgeschwindigkeit
        wpm = metadata.get("wpm")
        if wpm is not None:
            if wpm > self.wpm_fast:
                # Schnelles Sprechen = Stress/Aufregung
                stress_boost = (wpm - self.wpm_fast) / 100.0 * self.voice_weight
                self._stress_level = min(1.0, self._stress_level + stress_boost)
                signals.append("voice_fast")
                logger.debug("Voice: schnell (%.0f WPM) -> Stress +%.2f", wpm, stress_boost)
            elif wpm < self.wpm_slow:
                # Langsames Sprechen = Muedigkeit
                tired_boost = (self.wpm_slow - wpm) / 100.0 * self.voice_weight
                self._tiredness_level = min(1.0, self._tiredness_level + tired_boost)
                signals.append("voice_slow")
                logger.debug("Voice: langsam (%.0f WPM) -> Muedigkeit +%.2f", wpm, tired_boost)

        # Lautstaerke
        volume = metadata.get("volume")
        if volume is not None:
            if volume > 0.8:
                # Lautes Sprechen = aufgeregt/frustriert
                self._stress_level = min(1.0, self._stress_level + 0.1 * self.voice_weight)
                signals.append("voice_loud")
            elif volume < 0.2:
                # Leises Sprechen = muede/unsicher
                self._tiredness_level = min(1.0, self._tiredness_level + 0.1 * self.voice_weight)
                signals.append("voice_quiet")

        # Sehr kurze Aufnahme mit wenig Woertern = knappe Befehle
        duration = metadata.get("duration", 0)
        word_count = metadata.get("word_count", 0)
        if duration > 0 and word_count > 0:
            if duration < 1.5 and word_count <= 3:
                # Extrem knappe Befehle = ungeduldig
                self._stress_level = min(1.0, self._stress_level + 0.05 * self.voice_weight)
                signals.append("voice_curt")

        # Schnelle Nachfrage (<5s nach letztem Befehl) = Ungeduld/Stress
        if metadata.get("rapid_follow_up"):
            self._stress_level = min(1.0, self._stress_level + 0.1 * self.voice_weight)
            signals.append("rapid_follow_up")
            logger.debug("Voice: schnelle Nachfrage -> Stress +%.2f", 0.1 * self.voice_weight)

        self._last_voice_signals = signals
        return signals

    def detect_audio_emotion(self, metadata: dict) -> dict:
        """Phase 9.5: Erkennt Emotionen aus Audio-Metadaten.

        Kombiniert WPM, Lautstaerke, Pause-Muster und Tonhoehe zu einer
        Emotions-Einschaetzung.

        Args:
            metadata: Dict mit wpm, volume, duration, pitch_mean, pitch_variance,
                      pause_ratio, energy_rms

        Returns:
            Dict mit emotion, confidence, signals, scores
        """
        if not metadata:
            return {"emotion": "neutral", "confidence": 0.0, "signals": []}

        signals = []
        scores = {"happy": 0.0, "sad": 0.0, "angry": 0.0, "anxious": 0.0,
                  "tired": 0.0, "neutral": 0.3}

        wpm = metadata.get("wpm", 0)
        volume = metadata.get("volume", 0.5)
        pitch_mean = metadata.get("pitch_mean")
        pitch_variance = metadata.get("pitch_variance")
        pause_ratio = metadata.get("pause_ratio", 0)
        energy_rms = metadata.get("energy_rms")

        # Sprechgeschwindigkeit
        if wpm > 0:
            if wpm > 180:
                scores["anxious"] += 0.3
                scores["angry"] += 0.2
                signals.append("speech_fast")
            elif wpm > 150:
                scores["happy"] += 0.2
                signals.append("speech_moderate_fast")
            elif wpm < 80:
                scores["sad"] += 0.3
                scores["tired"] += 0.3
                signals.append("speech_slow")

        # Lautstaerke
        if volume > 0.8:
            scores["angry"] += 0.3
            scores["happy"] += 0.15
            signals.append("voice_loud")
        elif volume < 0.2:
            scores["sad"] += 0.2
            scores["tired"] += 0.2
            signals.append("voice_quiet")

        # Tonhoehe
        if pitch_mean is not None:
            if pitch_mean > 200:
                scores["anxious"] += 0.2
                scores["happy"] += 0.15
                signals.append("pitch_high")
            elif pitch_mean < 100:
                scores["sad"] += 0.15
                scores["tired"] += 0.1
                signals.append("pitch_low")

        if pitch_variance is not None:
            if pitch_variance > 50:
                scores["happy"] += 0.2
                scores["angry"] += 0.1
                signals.append("pitch_dynamic")
            elif pitch_variance < 10:
                scores["sad"] += 0.2
                scores["tired"] += 0.15
                signals.append("pitch_monotone")

        # Pausen-Muster
        if pause_ratio > 0.4:
            scores["tired"] += 0.2
            scores["sad"] += 0.1
            signals.append("many_pauses")

        # Energie
        if energy_rms is not None:
            if energy_rms > 0.7:
                scores["angry"] += 0.15
                signals.append("high_energy")
            elif energy_rms < 0.2:
                scores["tired"] += 0.15
                signals.append("low_energy")

        # Hoechste Emotion
        best_emotion = max(scores, key=scores.get)
        confidence = min(1.0, scores[best_emotion])

        # In Mood-State uebernehmen
        emotion_mood_map = {
            "happy": (-0.1, 0.0),
            "sad": (0.0, 0.1),
            "angry": (0.2, 0.0),
            "anxious": (0.15, 0.0),
            "tired": (0.0, 0.2),
        }
        if best_emotion in emotion_mood_map and confidence > 0.4:
            stress_d, tired_d = emotion_mood_map[best_emotion]
            self._stress_level = min(1.0, max(0.0,
                self._stress_level + stress_d * self.voice_weight))
            self._tiredness_level = min(1.0, max(0.0,
                self._tiredness_level + tired_d * self.voice_weight))

        return {
            "emotion": best_emotion,
            "confidence": round(confidence, 2),
            "signals": signals,
            "scores": {k: round(v, 2) for k, v in scores.items() if v > 0},
        }

    def get_voice_signals(self) -> list[str]:
        """Gibt die letzten Voice-Signale zurueck."""
        return self._last_voice_signals

    async def _save_state(self):
        """Speichert den aktuellen Zustand in Redis."""
        if not self.redis:
            return
        try:
            await self.redis.hset("mha:mood:state", mapping={
                "mood": self._current_mood,
                "stress": str(self._stress_level),
                "tiredness": str(self._tiredness_level),
                "frustration": str(self._frustration_count),
                "positive": str(self._positive_count),
                "updated": datetime.now().isoformat(),
            })
            # 1h TTL - Reset nach laengerer Inaktivitaet
            await self.redis.expire("mha:mood:state", 3600)
        except Exception as e:
            logger.debug("Mood-State nicht gespeichert: %s", e)
