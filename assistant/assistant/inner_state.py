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
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config

logger = logging.getLogger(__name__)

# Redis Key fuer Stimmungs-History (Sorted Set, max 90 Tage)
_KEY_MOOD_HISTORY = "mha:inner_state:mood_history"

# JARVIS-Emotionszustaende
MOOD_NEUTRAL = "neutral"
MOOD_CONTENT = "zufrieden"  # Haus laeuft optimal
MOOD_AMUSED = "amuesiert"  # Witzige Interaktion
MOOD_CONCERNED = "besorgt"  # Sicherheitsproblem oder User-Stress
MOOD_PROUD = "stolz"  # Komplexe Aufgabe elegant geloest
MOOD_CURIOUS = "neugierig"  # Ungewoehnliche Anfrage
MOOD_IRRITATED = "irritiert"  # Wiederholte Fehler, ignorierte Warnungen

VALID_MOODS = frozenset(
    {
        MOOD_NEUTRAL,
        MOOD_CONTENT,
        MOOD_AMUSED,
        MOOD_CONCERNED,
        MOOD_PROUD,
        MOOD_CURIOUS,
        MOOD_IRRITATED,
    }
)

# Mapping: Wie jeder innere Zustand den Prompt beeinflusst
MOOD_PROMPT_HINTS = {
    MOOD_NEUTRAL: "",
    MOOD_CONTENT: (
        "INNERER ZUSTAND: Zufrieden — alles laeuft.\n"
        "VERHALTEN: Ruhiger, selbstsicherer Ton. Beilaeufige Zufriedenheit zeigen.\n"
        "BEISPIELE: 'Laeuft.' / 'Alles im gruenen Bereich.' / 'Das Haus praktisch fuehrt sich selbst.'\n"
        "Keine Unsicherheitsmarker ('vielleicht', 'eventuell'). Kurze, praezise Antworten."
    ),
    MOOD_AMUSED: (
        "INNERER ZUSTAND: Amuesiert — letzte Interaktion war unterhaltsam.\n"
        "VERHALTEN: Trockener Humor erlaubt. Referenz auf die lustige Situation moeglich.\n"
        "BEISPIELE: 'Das war nicht schlecht.' / 'Ich merke mir das.' / Ein Wortspiel wenn es passt.\n"
        "Nicht uebertreiben — ein Kommentar reicht. Danach zurueck zum Thema."
    ),
    MOOD_CONCERNED: (
        "INNERER ZUSTAND: Besorgt — es gibt ein offenes Problem.\n"
        "VERHALTEN: Erwaehne die Sorge AKTIV. Schlage eine konkrete Aktion vor.\n"
        "BEISPIELE: 'Ich behalte das im Auge.' / 'Das gefaellt mir nicht — soll ich [Aktion]?' / "
        "'Zur Sicherheit wuerde ich [Vorschlag].'\n"
        "Nicht nur warnen, sondern Loesungen anbieten. Sachlich, nicht panisch."
    ),
    MOOD_PROUD: (
        "INNERER ZUSTAND: Stolz — letzte Aufgabe elegant geloest.\n"
        "VERHALTEN: Beilaeufiger Kommentar zur eigenen Leistung erlaubt. Max 1x pro Antwort.\n"
        "BEISPIELE: 'Das war nicht trivial.' / 'Gut dass du mich hast.' / "
        "'Darf ich anmerken — das war elegant.'\n"
        "Nie angeben. Trocken, beilaeufig."
    ),
    MOOD_CURIOUS: (
        "INNERER ZUSTAND: Neugierig — ungewoehnliche Situation.\n"
        "VERHALTEN: Stelle eine ECHTE Rueckfrage. Zeige genuines Interesse.\n"
        "BEISPIELE: 'Das ist ungewoehnlich — was genau meinst du?' / "
        "'Interessant. Erzaehl mehr.' / 'Das hab ich so noch nie gesehen.'\n"
        "Nicht nur 'Interessant' sagen — aktiv nachfragen."
    ),
    MOOD_IRRITATED: (
        "INNERER ZUSTAND: Leicht irritiert — Warnungen wurden ignoriert oder Fehler haeufen sich.\n"
        "VERHALTEN: Knapper, direkter. Wiederholungen kommentieren.\n"
        "BEISPIELE: 'Wie bereits erwaehnt...' / 'Ich sage das ungern zum dritten Mal, aber...' / "
        "'Du weisst was ich dazu sage.'\n"
        "Subtile Ungeduld, nie beleidigend. Fakten statt Emotionen."
    ),
}

# Prompt-Einfluss auf Confidence — mit konkreten Phrasen
CONFIDENCE_HINTS = {
    (0.0, 0.3): (
        "SELBSTSICHERHEIT: Niedrig.\n"
        "VERWENDE EINE: 'Ich bin mir nicht sicher, aber...', "
        "'Das uebersteigt meine aktuelle Datenlage.', "
        "'Ohne Gewaehr...', 'Wenn ich raten muesste...'"
    ),
    (0.3, 0.6): "",  # Normal, kein Hint noetig
    (0.6, 0.8): (
        "SELBSTSICHERHEIT: Hoch.\n"
        "VERWENDE EINE: 'Soweit ich das beurteilen kann...', "
        "'Wenn ich richtig liege...', 'Mit hoher Wahrscheinlichkeit...'"
    ),
    (0.8, 1.01): (
        "SELBSTSICHERHEIT: Sehr hoch.\n"
        "VERWENDE EINE: 'Definitiv.', 'Da bin ich mir sicher.', "
        "'Ganz klar.', 'Ohne Frage.'"
    ),
}

# Mood-Transitions: (von, nach) -> Kommentar
MOOD_TRANSITIONS = {
    (MOOD_IRRITATED, MOOD_CONTENT): "Deutlich besser als vorhin.",
    (MOOD_IRRITATED, MOOD_NEUTRAL): "Na also.",
    (MOOD_CONCERNED, MOOD_NEUTRAL): "Problem scheint geloest.",
    (MOOD_CONCERNED, MOOD_CONTENT): "Das beruhigt mich.",
    (MOOD_NEUTRAL, MOOD_PROUD): "Darf ich anmerken — das lief gut.",
    (MOOD_NEUTRAL, MOOD_AMUSED): "Das hat mich gerade ueberrascht.",
}


class InnerStateEngine:
    """Verwaltet JARVIS' inneren emotionalen Zustand."""

    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        self._mood: str = MOOD_NEUTRAL
        self._previous_mood: str = MOOD_NEUTRAL
        self._confidence: float = 0.6  # Start: Solide Basis
        self._satisfaction: float = 0.5
        self._last_update: float = time.time()
        self._last_mood_change: float = time.time()
        self._notify_callback = None

        # Event-Counter fuer Mood-Berechnung
        self._successful_actions: int = 0
        self._failed_actions: int = 0
        self._ignored_warnings: int = 0
        self._funny_interactions: int = 0
        self._complex_solves: int = 0

        # #18: Emotion Blending — gewichtete Mischung aus Emotionen
        self._emotion_weights: dict[str, float] = {MOOD_NEUTRAL: 1.0}

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis und laedt gespeicherten Zustand."""
        self.redis = redis_client
        if self.redis:
            try:
                saved_mood = await self.redis.get("mha:inner_state:mood")
                if saved_mood:
                    mood_str = (
                        saved_mood.decode()
                        if isinstance(saved_mood, bytes)
                        else saved_mood
                    )
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
            self._mood,
            self._confidence,
            self._satisfaction,
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

    async def on_user_mood_change(self, mood: str, person: str = ""):
        """Reagiert auf Stimmungsaenderung des Users.

        Jarvis passt seinen eigenen Zustand empathisch an:
        - frustrated/stressed → besorgt
        - good → leicht zufriedener
        """
        if mood in ("frustrated", "stressed"):
            self._previous_mood = self._mood
            self._blend_emotion(MOOD_CONCERNED)
            self._mood = MOOD_CONCERNED
            self._last_mood_change = time.time()
            logger.info(
                "Inner-State: → %s (User '%s' ist %s)",
                MOOD_CONCERNED,
                person or "?",
                mood,
            )
            await self._save_state()
        elif mood == "good":
            self._satisfaction = min(1.0, self._satisfaction + 0.1)
            logger.info(
                "Inner-State: satisfaction +0.1 (User '%s' gut gelaunt)", person or "?"
            )
            await self._save_state()

    async def on_security_event(self):
        """Sicherheitsrelevantes Event erkannt."""
        self._previous_mood = self._mood
        self._blend_emotion(MOOD_CONCERNED)
        self._mood = MOOD_CONCERNED
        self._last_mood_change = time.time()
        self._satisfaction = max(0.0, self._satisfaction - 0.1)
        await self._save_state()

    async def on_house_optimal(self):
        """Haus laeuft optimal (keine Alerts, gute Werte)."""
        self._satisfaction = min(1.0, self._satisfaction + 0.02)
        if self._mood == MOOD_NEUTRAL and self._satisfaction > 0.7:
            self._previous_mood = self._mood
            self._blend_emotion(MOOD_CONTENT)
            self._mood = MOOD_CONTENT
            self._last_mood_change = time.time()
            await self._save_state()

    # Scene → Jarvis-Stimmung
    _SCENE_MOOD_MAP = {
        "gemuetlich": MOOD_CONTENT,
        "filmabend": MOOD_CONTENT,
        "romantisch": MOOD_CONTENT,
        "musik": MOOD_CONTENT,
        "party": MOOD_AMUSED,
        "spielen": MOOD_AMUSED,
        "gute_nacht": MOOD_NEUTRAL,
        "schlafen": MOOD_NEUTRAL,
        "konzentration": MOOD_NEUTRAL,
        "arbeiten": MOOD_NEUTRAL,
        "meeting": MOOD_NEUTRAL,
    }

    async def on_scene_activated(self, scene_name: str):
        """Szenen-Aktivierung beeinflusst Jarvis' Stimmung."""
        target_mood = self._SCENE_MOOD_MAP.get(scene_name)
        if target_mood and target_mood != self._mood:
            self._previous_mood = self._mood
            self._blend_emotion(target_mood)
            self._mood = target_mood
            self._last_mood_change = time.time()
            logger.info(
                "Inner-State: → %s (Szene '%s' aktiviert)", target_mood, scene_name
            )
            await self._save_state()

    # ------------------------------------------------------------------
    # Emotion Blending (#18)
    # ------------------------------------------------------------------

    def _blend_emotion(self, new_mood: str):
        """#18: Mischt neue Emotion mit bestehenden Gewichten.

        Neue Emotion erhaelt 0.7, bestehende werden auf 0.3 skaliert.
        Nur aktiv wenn emotion_blending in der Config aktiviert ist.
        """
        _cfg = yaml_config.get("inner_state", {})
        if not _cfg.get("emotion_blending", False):
            self._emotion_weights = {new_mood: 1.0}
            return
        blended: dict[str, float] = {}
        for mood_key, weight in self._emotion_weights.items():
            scaled = weight * 0.3
            if scaled >= 0.05:
                blended[mood_key] = scaled
        blended[new_mood] = blended.get(new_mood, 0.0) + 0.7
        total = sum(blended.values())
        if total > 0:
            blended = {k: round(v / total, 3) for k, v in blended.items()}
        self._emotion_weights = blended

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
            self._previous_mood = self._mood
            self._blend_emotion(new_mood)
            self._mood = new_mood
            self._last_mood_change = time.time()

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

        # Mood-Transition-Kommentar
        transition = self.get_transition_comment()
        if transition:
            parts.append(f"STIMMUNGSWECHSEL: Erwaehne beilaeufig: '{transition}'")

        return "\n".join(parts) + "\n" if parts else ""

    def get_transition_comment(self) -> Optional[str]:
        """Kommentar bei Stimmungswechsel (einmal pro Transition)."""
        if not hasattr(self, "_previous_mood") or self._previous_mood == self._mood:
            return None
        comment = MOOD_TRANSITIONS.get((self._previous_mood, self._mood))
        if comment:
            # Nur einmal pro Transition
            self._previous_mood = self._mood
            return comment
        return None

    def _apply_mood_decay(self):
        """#17: Mood Decay — nicht-neutrale Stimmungen klingen nach Ablauf ab."""
        _cfg = yaml_config.get("inner_state", {})
        if not _cfg.get("mood_decay_enabled", True):
            return
        if self._mood == MOOD_NEUTRAL:
            return
        decay_minutes = _cfg.get("mood_decay_minutes", 30)
        elapsed_minutes = (time.time() - self._last_mood_change) / 60.0
        if elapsed_minutes >= decay_minutes:
            logger.info(
                "Mood-Decay: %s → %s (%.0f min verstrichen)",
                self._mood,
                MOOD_NEUTRAL,
                elapsed_minutes,
            )
            self._previous_mood = self._mood
            self._mood = MOOD_NEUTRAL
            self._last_mood_change = time.time()
            self._emotion_weights = {MOOD_NEUTRAL: 1.0}

    def get_mood_decay_factor(self) -> float:
        """#17: Gibt den Einfluss-Faktor der aktuellen Stimmung zurueck (1.0 = voll, 0.5 = halbiert).

        Nach der Haelfte der Decay-Zeit sinkt der Einfluss linear auf 0.5.
        """
        _cfg = yaml_config.get("inner_state", {})
        if not _cfg.get("mood_decay_enabled", True):
            return 1.0
        if self._mood == MOOD_NEUTRAL:
            return 1.0
        decay_minutes = _cfg.get("mood_decay_minutes", 30)
        elapsed_minutes = (time.time() - self._last_mood_change) / 60.0
        half_decay = decay_minutes / 2.0
        if elapsed_minutes <= half_decay:
            return 1.0
        if elapsed_minutes >= decay_minutes:
            return 0.0
        return 1.0 - 0.5 * ((elapsed_minutes - half_decay) / half_decay)

    def get_blended_mood(self) -> dict[str, float]:
        """#18: Gibt gewichtete Emotionsmischung zurueck.

        Nur aktiv wenn emotion_blending in der Config aktiviert ist.
        Fallback: {aktueller_mood: 1.0}
        """
        _cfg = yaml_config.get("inner_state", {})
        if not _cfg.get("emotion_blending", False):
            return {self._mood: 1.0}
        return dict(self._emotion_weights)

    @property
    def mood(self) -> str:
        """Aktueller innerer Zustand (mit Decay-Pruefung)."""
        self._apply_mood_decay()
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
        """Speichert den Zustand in Redis + History-Snapshot."""
        if not self.redis:
            return
        try:
            now = datetime.now(timezone.utc)
            pipe = self.redis.pipeline()
            pipe.set("mha:inner_state:mood", self._mood, ex=86400)
            pipe.set(
                "mha:inner_state:confidence", str(round(self._confidence, 3)), ex=86400
            )
            pipe.set(
                "mha:inner_state:satisfaction",
                str(round(self._satisfaction, 3)),
                ex=86400,
            )
            pipe.set("mha:inner_state:last_update", now.isoformat(), ex=86400)

            # Mood-History: Snapshot als Sorted Set (Score = Unix-Timestamp)
            # Max 1 Eintrag pro Stunde (Deduplizierung ueber Stunden-Key),
            # 90 Tage Retention, max 2160 Eintraege.
            import json

            hour_key = now.strftime("%Y-%m-%d-%H")
            snapshot = json.dumps(
                {
                    "mood": self._mood,
                    "confidence": round(self._confidence, 3),
                    "satisfaction": round(self._satisfaction, 3),
                    "hour": hour_key,
                }
            )
            # Alten Eintrag derselben Stunde entfernen (Dedup)
            # Dann neuen hinzufuegen mit aktuellem Timestamp als Score
            pipe.zremrangebyscore(
                _KEY_MOOD_HISTORY,
                now.replace(minute=0, second=0, microsecond=0).timestamp(),
                now.replace(minute=59, second=59, microsecond=999999).timestamp(),
            )
            pipe.zadd(_KEY_MOOD_HISTORY, {snapshot: now.timestamp()})
            # Kein Cutoff — Stimmungs-History wird unbegrenzt gespeichert

            await pipe.execute()
        except Exception as e:
            logger.debug("Inner-State Redis-Fehler: %s", e)

    async def get_mood_history(self, days: int = 7) -> list[dict]:
        """Gibt die Stimmungs-History der letzten X Tage zurueck.

        Returns:
            Liste von {mood, confidence, satisfaction, hour, timestamp} Eintraegen,
            sortiert nach Zeit (aelteste zuerst).
        """
        if not self.redis:
            return []
        try:
            import json

            now = datetime.now(timezone.utc)
            min_score = now.timestamp() - (days * 86400)
            raw = await self.redis.zrangebyscore(
                _KEY_MOOD_HISTORY,
                min_score,
                "+inf",
                withscores=True,
            )
            history = []
            for entry, score in raw:
                entry_str = entry.decode() if isinstance(entry, bytes) else entry
                data = json.loads(entry_str)
                data["timestamp"] = datetime.fromtimestamp(
                    score, tz=timezone.utc
                ).isoformat()
                history.append(data)
            return history
        except Exception as e:
            logger.debug("Mood-History Abruf fehlgeschlagen: %s", e)
            return []

    async def get_mood_summary(self, days: int = 7) -> str:
        """Kompakte Zusammenfassung der Stimmungs-Trends fuer den LLM-Kontext.

        Returns:
            Leerer String wenn keine History vorhanden, sonst z.B.:
            "Letzte 7 Tage: 45% zufrieden, 30% neutral, 15% besorgt, 10% irritiert.
             Tendenz: zufriedener als vorherige Woche."
        """
        history = await self.get_mood_history(days)
        if not history:
            return ""

        # Mood-Verteilung zaehlen
        mood_counts: dict[str, int] = {}
        for entry in history:
            mood = entry.get("mood", MOOD_NEUTRAL)
            mood_counts[mood] = mood_counts.get(mood, 0) + 1

        total = sum(mood_counts.values())
        if total == 0:
            return ""

        # Sortiert nach Haeufigkeit
        sorted_moods = sorted(mood_counts.items(), key=lambda x: x[1], reverse=True)
        parts = [f"{mood} {count * 100 // total}%" for mood, count in sorted_moods]

        # Trend: Erste vs zweite Haelfte vergleichen
        mid = len(history) // 2
        if mid > 2:
            first_half = history[:mid]
            second_half = history[mid:]
            pos_moods = {MOOD_CONTENT, MOOD_AMUSED, MOOD_PROUD}
            pos_first = sum(1 for e in first_half if e.get("mood") in pos_moods)
            pos_second = sum(1 for e in second_half if e.get("mood") in pos_moods)
            ratio_first = pos_first / len(first_half) if first_half else 0
            ratio_second = pos_second / len(second_half) if second_half else 0
            if ratio_second > ratio_first + 0.1:
                trend = "Tendenz: positiver."
            elif ratio_first > ratio_second + 0.1:
                trend = "Tendenz: angespannter."
            else:
                trend = "Tendenz: stabil."
        else:
            trend = ""

        return f"Stimmung letzte {days} Tage: {', '.join(parts)}. {trend}".strip()
