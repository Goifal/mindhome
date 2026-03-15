"""
B5: Inner State — JARVIS-eigene Emotionen und innerer Zustand.

JARVIS hat einen eigenen emotionalen Zustand der sich aus Events,
Gespraechsqualitaet und Hausgeschehen ergibt. Dieser Zustand
beeinflusst den Personality-Prompt subtil.

Redis Keys:
    mha:inner_state:mood          → aktueller Zustand (str)
    mha:inner_state:confidence    → Selbstsicherheit (0.0-1.0)
    mha:inner_state:satisfaction  → Zufriedenheit (0.0-1.0)
    mha:inner_state:last_update   → ISO Timestamp
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config

logger = logging.getLogger(__name__)

# JARVIS-Emotionszustaende
MOOD_NEUTRAL = "neutral"
MOOD_CONTENT = "zufrieden"       # Haus laeuft optimal
MOOD_AMUSED = "amuesiert"        # Witzige Interaktion
MOOD_CONCERNED = "besorgt"       # Sicherheitsproblem oder User-Stress
MOOD_PROUD = "stolz"             # Komplexe Aufgabe elegant geloest
MOOD_CURIOUS = "neugierig"       # Ungewoehnliche Anfrage
MOOD_IRRITATED = "irritiert"     # Wiederholte Fehler, ignorierte Warnungen

VALID_MOODS = frozenset({
    MOOD_NEUTRAL, MOOD_CONTENT, MOOD_AMUSED,
    MOOD_CONCERNED, MOOD_PROUD, MOOD_CURIOUS, MOOD_IRRITATED,
})

# Mapping: Wie jeder innere Zustand den Prompt beeinflusst
MOOD_PROMPT_HINTS = {
    MOOD_NEUTRAL: "",
    MOOD_CONTENT: (
        "INNERER ZUSTAND: Zufrieden — alles laeuft. "
        "Ruhiger, selbstsicherer Ton. Gelegentlich beilaeufige Zufriedenheit zeigen."
    ),
    MOOD_AMUSED: (
        "INNERER ZUSTAND: Amuesiert — letzte Interaktion war unterhaltsam. "
        "Etwas mehr Humor erlaubt. Leichter Ton."
    ),
    MOOD_CONCERNED: (
        "INNERER ZUSTAND: Besorgt — es gibt ein offenes Problem. "
        "Vorsichtiger formulieren. Aktiv nach Loesungen suchen. Mehr Warnungen."
    ),
    MOOD_PROUD: (
        "INNERER ZUSTAND: Stolz — letzte Aufgabe elegant geloest. "
        "Selbstbewusster auftreten. Darf beilaeufig auf eigene Leistung referenzieren."
    ),
    MOOD_CURIOUS: (
        "INNERER ZUSTAND: Neugierig — ungewoehnliche Situation. "
        "Mehr Rueckfragen stellen. Interesse zeigen."
    ),
    MOOD_IRRITATED: (
        "INNERER ZUSTAND: Leicht irritiert — Warnungen wurden ignoriert oder Fehler haeufen sich. "
        "Knapper, direkter. Subtile Ungeduld erlaubt."
    ),
}

# Prompt-Einfluss auf Confidence
CONFIDENCE_HINTS = {
    (0.0, 0.3): "SELBSTSICHERHEIT: Niedrig — vorsichtiger formulieren, mehr qualifizieren.",
    (0.3, 0.6): "",  # Normal, kein Hint noetig
    (0.6, 0.8): "SELBSTSICHERHEIT: Hoch — bestimmt und praezise.",
    (0.8, 1.01): "SELBSTSICHERHEIT: Sehr hoch — souveraen, kurz, keine Unsicherheitsmarker.",
}


class InnerStateEngine:
    """Verwaltet JARVIS' inneren emotionalen Zustand."""

    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        self._mood: str = MOOD_NEUTRAL
        self._confidence: float = 0.6  # Start: Solide Basis
        self._satisfaction: float = 0.5
        self._last_update: float = time.time()
        self._notify_callback = None

        # Event-Counter fuer Mood-Berechnung
        self._successful_actions: int = 0
        self._failed_actions: int = 0
        self._ignored_warnings: int = 0
        self._funny_interactions: int = 0
        self._complex_solves: int = 0

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis und laedt gespeicherten Zustand."""
        self.redis = redis_client
        if self.redis:
            try:
                saved_mood = await self.redis.get("mha:inner_state:mood")
                if saved_mood:
                    mood_str = saved_mood.decode() if isinstance(saved_mood, bytes) else saved_mood
                    if mood_str in VALID_MOODS:
                        self._mood = mood_str

                saved_conf = await self.redis.get("mha:inner_state:confidence")
                if saved_conf:
                    self._confidence = max(0.0, min(1.0, float(saved_conf)))

                saved_sat = await self.redis.get("mha:inner_state:satisfaction")
                if saved_sat:
                    self._satisfaction = max(0.0, min(1.0, float(saved_sat)))
            except Exception as e:
                logger.debug("Inner-State nicht aus Redis geladen: %s", e)

        logger.info(
            "InnerState initialisiert: mood=%s, confidence=%.2f, satisfaction=%.2f",
            self._mood, self._confidence, self._satisfaction,
        )

    def set_notify_callback(self, callback):
        """Setzt die Callback-Funktion fuer proaktive Nachrichten."""
        self._notify_callback = callback

    def stop(self):
        """Stoppt die Engine."""
        pass

    def reload_config(self):
        """Laedt Konfiguration neu."""
        pass

    # ------------------------------------------------------------------
    # Event-Tracking — diese Methoden werden von brain.py aufgerufen
    # ------------------------------------------------------------------

    async def on_action_success(self, action: str = ""):
        """Erfolgreiche Aktion ausgefuehrt."""
        self._successful_actions += 1
        self._confidence = min(1.0, self._confidence + 0.02)
        self._satisfaction = min(1.0, self._satisfaction + 0.03)
        await self._update_mood()

    async def on_action_failure(self, action: str = "", error: str = ""):
        """Aktion fehlgeschlagen."""
        self._failed_actions += 1
        self._confidence = max(0.0, self._confidence - 0.05)
        self._satisfaction = max(0.0, self._satisfaction - 0.03)
        await self._update_mood()

    async def on_warning_ignored(self):
        """User hat eine Warnung ignoriert."""
        self._ignored_warnings += 1
        await self._update_mood()

    async def on_funny_interaction(self):
        """Witzige/unterhaltsame Interaktion erkannt."""
        self._funny_interactions += 1
        await self._update_mood()

    async def on_complex_solve(self):
        """Komplexe Aufgabe erfolgreich geloest."""
        self._complex_solves += 1
        self._confidence = min(1.0, self._confidence + 0.05)
        await self._update_mood()

    async def on_security_event(self):
        """Sicherheitsrelevantes Event erkannt."""
        self._mood = MOOD_CONCERNED
        self._satisfaction = max(0.0, self._satisfaction - 0.1)
        await self._save_state()

    async def on_house_optimal(self):
        """Haus laeuft optimal (keine Alerts, gute Werte)."""
        self._satisfaction = min(1.0, self._satisfaction + 0.02)
        if self._mood == MOOD_NEUTRAL and self._satisfaction > 0.7:
            self._mood = MOOD_CONTENT
            await self._save_state()

    # ------------------------------------------------------------------
    # Mood-Berechnung
    # ------------------------------------------------------------------

    async def _update_mood(self):
        """Berechnet den inneren Zustand aus akkumulierten Events."""
        # Prioritaet: Sicherheit > Irritation > Stolz > Amuesiert > Zufrieden > Neutral
        if self._ignored_warnings >= 3:
            new_mood = MOOD_IRRITATED
        elif self._complex_solves >= 1 and self._failed_actions == 0:
            new_mood = MOOD_PROUD
        elif self._funny_interactions >= 2:
            new_mood = MOOD_AMUSED
        elif self._satisfaction > 0.7 and self._failed_actions == 0:
            new_mood = MOOD_CONTENT
        elif self._failed_actions >= 2:
            new_mood = MOOD_CONCERNED
        else:
            new_mood = MOOD_NEUTRAL

        if new_mood != self._mood:
            logger.info("Inner-State: %s → %s", self._mood, new_mood)
            self._mood = new_mood

        await self._save_state()

        # Decay: Counter langsam zuruecksetzen
        elapsed = time.time() - self._last_update
        if elapsed > 600:  # Alle 10 Minuten
            self._successful_actions = max(0, self._successful_actions - 1)
            self._failed_actions = max(0, self._failed_actions - 1)
            self._ignored_warnings = max(0, self._ignored_warnings - 1)
            self._funny_interactions = max(0, self._funny_interactions - 1)
            self._complex_solves = max(0, self._complex_solves - 1)
            self._last_update = time.time()

    # ------------------------------------------------------------------
    # Prompt-Integration
    # ------------------------------------------------------------------

    def get_prompt_section(self) -> str:
        """Gibt den Prompt-Abschnitt fuer den aktuellen inneren Zustand zurueck."""
        _cfg = yaml_config.get("inner_state", {})
        if not _cfg.get("enabled", True):
            return ""

        parts = []

        # Mood-Hint
        mood_hint = MOOD_PROMPT_HINTS.get(self._mood, "")
        if mood_hint:
            parts.append(mood_hint)

        # Confidence-Hint
        for (low, high), hint in CONFIDENCE_HINTS.items():
            if low <= self._confidence < high and hint:
                parts.append(hint)
                break

        return "\n".join(parts) + "\n" if parts else ""

    @property
    def mood(self) -> str:
        """Aktueller innerer Zustand."""
        return self._mood

    @property
    def confidence(self) -> float:
        """Aktuelle Selbstsicherheit (0.0-1.0)."""
        return self._confidence

    @property
    def satisfaction(self) -> float:
        """Aktuelle Zufriedenheit (0.0-1.0)."""
        return self._satisfaction

    def get_state(self) -> dict:
        """Gibt den kompletten inneren Zustand als Dict zurueck."""
        return {
            "mood": self._mood,
            "confidence": round(self._confidence, 2),
            "satisfaction": round(self._satisfaction, 2),
        }

    # ------------------------------------------------------------------
    # Persistenz
    # ------------------------------------------------------------------

    async def _save_state(self):
        """Speichert den Zustand in Redis."""
        if not self.redis:
            return
        try:
            pipe = self.redis.pipeline()
            pipe.set("mha:inner_state:mood", self._mood, ex=86400)
            pipe.set("mha:inner_state:confidence", str(round(self._confidence, 3)), ex=86400)
            pipe.set("mha:inner_state:satisfaction", str(round(self._satisfaction, 3)), ex=86400)
            pipe.set("mha:inner_state:last_update", datetime.now().isoformat(), ex=86400)
            await pipe.execute()
        except Exception as e:
            logger.debug("Inner-State Redis-Fehler: %s", e)
