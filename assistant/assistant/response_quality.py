"""
Response Quality Tracker - Misst wie effektiv Jarvis' Antworten sind.

Follow-Up-Frage innerhalb 60s = Antwort unklar.
User wiederholt/umformuliert = nicht verstanden.
Einzelner Austausch = Erfolg. "Danke" = klar positiv.
Scores pro Kategorie (device_command, knowledge, smalltalk, analysis).

Sicherheit: Rein beobachtend. Kein Schreibzugriff auf Config/HA. Bounded Scores 0-1.
"""

import json
import logging
import time
from datetime import datetime
from typing import Optional

from .config import yaml_config

logger = logging.getLogger(__name__)

DEFAULT_SCORE = 0.5
MIN_EXCHANGES_FOR_SCORE = 20

# EMA Alpha (neuere Daten zaehlen mehr)
EMA_ALPHA = 0.1


class ResponseQualityTracker:
    """Trackt Antwort-Qualitaet pro Kategorie."""

    def __init__(self):
        self.redis = None
        self.enabled = False
        self._cfg = yaml_config.get("response_quality", {})
        self._followup_window = self._cfg.get("followup_window_seconds", 60)
        self._rephrase_threshold = self._cfg.get("rephrase_similarity_threshold", 0.6)

        # State fuer Follow-Up-Erkennung
        self._last_user_text: str = ""
        self._last_response_time: float = 0.0
        self._last_response_category: str = ""

    async def initialize(self, redis_client):
        """Initialisiert mit Redis Client."""
        self.redis = redis_client
        self.enabled = self._cfg.get("enabled", True) and self.redis is not None
        logger.info("ResponseQualityTracker initialisiert (enabled=%s)", self.enabled)

    def check_followup(self, current_text: str) -> Optional[dict]:
        """Prueft ob aktueller Text ein Follow-Up/Rephrase der letzten Antwort ist.

        Wird am ANFANG von process() aufgerufen.
        Returns: Dict mit {is_followup, is_rephrase, previous_category} oder None.
        """
        if not self.enabled or not self._last_user_text:
            return None

        now = time.time()
        elapsed = now - self._last_response_time

        result = {
            "is_followup": False,
            "is_rephrase": False,
            "previous_category": self._last_response_category,
        }

        # Follow-Up: Neue Nachricht < N Sekunden nach letzter Antwort
        if elapsed < self._followup_window and self._last_response_category:
            result["is_followup"] = True

        # Rephrase: Aehnlicher Text wie vorher
        if self._detect_rephrase(current_text, self._last_user_text):
            result["is_rephrase"] = True

        if result["is_followup"] or result["is_rephrase"]:
            return result
        return None

    async def record_exchange(self, category: str, person: str = "",
                              had_followup: bool = False, was_rephrased: bool = False,
                              was_thanked: bool = False):
        """Bewertet einen Austausch und aktualisiert Scores."""
        if not self.enabled or not self.redis:
            return

        # Qualitaet bestimmen
        if was_thanked:
            quality = "clear"
            score_target = 1.0
        elif was_rephrased:
            quality = "rephrased"
            score_target = 0.0
        elif had_followup:
            quality = "unclear"
            score_target = 0.2
        else:
            quality = "clear"
            score_target = 0.8

        # Stats aktualisieren
        stats_key = f"mha:response_quality:stats:{category}"
        await self.redis.hincrby(stats_key, quality, 1)
        await self.redis.hincrby(stats_key, "total", 1)
        await self.redis.expire(stats_key, 90 * 86400)

        # Score aktualisieren (EMA)
        await self._update_score(category, score_target)

        # Per-Person Score (Feature 6)
        if person:
            await self._update_score(category, score_target, person=person)
            person_stats_key = f"mha:response_quality:stats:{category}:person:{person}"
            await self.redis.hincrby(person_stats_key, quality, 1)
            await self.redis.hincrby(person_stats_key, "total", 1)
            await self.redis.expire(person_stats_key, 90 * 86400)

        # History speichern
        entry = json.dumps({
            "category": category,
            "quality": quality,
            "person": person,
            "timestamp": datetime.now().isoformat(),
        }, ensure_ascii=False)
        await self.redis.lpush("mha:response_quality:history", entry)
        await self.redis.ltrim("mha:response_quality:history", 0, 299)
        await self.redis.expire("mha:response_quality:history", 90 * 86400)

        logger.debug("Response Quality [%s]: %s (Person: %s)", category, quality, person or "-")

    def update_last_exchange(self, text: str, category: str):
        """Speichert letzten Text + Kategorie fuer Follow-Up-Erkennung.

        Wird am ENDE von process() aufgerufen.
        """
        self._last_user_text = text
        self._last_response_time = time.time()
        self._last_response_category = category

    async def get_quality_score(self, category: str) -> float:
        """Score 0-1 pro Kategorie."""
        if not self.redis:
            return DEFAULT_SCORE

        score = await self.redis.get(f"mha:response_quality:score:{category}")
        if score is not None:
            return float(score)

        # Genug Daten?
        total = await self.redis.hget(f"mha:response_quality:stats:{category}", "total")
        if not total or int(total) < MIN_EXCHANGES_FOR_SCORE:
            return DEFAULT_SCORE

        return DEFAULT_SCORE

    async def get_person_score(self, category: str, person: str) -> float:
        """Per-Person Quality Score."""
        if not self.redis or not person:
            return DEFAULT_SCORE
        score = await self.redis.get(
            f"mha:response_quality:score:{category}:person:{person}"
        )
        return float(score) if score is not None else DEFAULT_SCORE

    async def get_stats(self) -> dict:
        """Statistiken fuer Self-Report."""
        if not self.redis:
            return {}

        stats = {}
        for category in ("device_command", "knowledge", "smalltalk", "analysis"):
            data = await self.redis.hgetall(f"mha:response_quality:stats:{category}")
            if data:
                score = await self.get_quality_score(category)
                stats[category] = {
                    k: int(v) for k, v in data.items()
                }
                stats[category]["score"] = score

        return stats

    # --- Private Methoden ---

    def _detect_rephrase(self, current_text: str, previous_text: str) -> bool:
        """Aehnlichkeitscheck: Keyword-Overlap > Threshold."""
        if not current_text or not previous_text:
            return False

        # Einfacher Keyword-Overlap
        current_words = set(current_text.lower().split())
        previous_words = set(previous_text.lower().split())

        # Stoppwoerter ignorieren
        stopwords = {"ich", "du", "das", "die", "der", "ein", "eine", "ist", "und",
                     "oder", "aber", "ja", "nein", "bitte", "mal", "noch", "auch",
                     "nicht", "mir", "mich", "es", "den", "dem", "was", "wie", "in",
                     "im", "am", "an", "auf", "fuer", "von", "zu", "mit"}
        current_words -= stopwords
        previous_words -= stopwords

        if not current_words or not previous_words:
            return False

        overlap = len(current_words & previous_words)
        total = len(current_words | previous_words)

        if total == 0:
            return False

        similarity = overlap / total
        return similarity >= self._rephrase_threshold

    async def _update_score(self, category: str, target: float, person: str = ""):
        """Aktualisiert Score via EMA."""
        if not self.redis:
            return

        if person:
            score_key = f"mha:response_quality:score:{category}:person:{person}"
            stats_key = f"mha:response_quality:stats:{category}:person:{person}"
        else:
            score_key = f"mha:response_quality:score:{category}"
            stats_key = f"mha:response_quality:stats:{category}"

        # Minimum-Datenmenge
        total = await self.redis.hget(stats_key, "total")
        if not total or int(total) < MIN_EXCHANGES_FOR_SCORE:
            return

        current = await self.redis.get(score_key)
        current_score = float(current) if current else DEFAULT_SCORE

        new_score = EMA_ALPHA * target + (1 - EMA_ALPHA) * current_score
        new_score = max(0.0, min(1.0, new_score))

        await self.redis.setex(score_key, 90 * 86400, str(round(new_score, 4)))
