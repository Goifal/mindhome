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
from datetime import datetime, timezone
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
                              was_thanked: bool = False, response_text: str = ""):
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
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False)
        await self.redis.lpush("mha:response_quality:history", entry)
        await self.redis.ltrim("mha:response_quality:history", 0, 299)
        await self.redis.expire("mha:response_quality:history", 90 * 86400)

        # D6: Gute Antworten als Few-Shot-Beispiele speichern
        if score_target >= 0.8 and self._last_user_text:
            await self._store_few_shot_example(
                category, self._last_user_text, response_text, person
            )

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
            raw_data = await self.redis.hgetall(f"mha:response_quality:stats:{category}")
            if raw_data:
                score = await self.get_quality_score(category)
                data = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in raw_data.items()}
                stats[category] = {
                    k: float(v) for k, v in data.items()
                }
                stats[category]["score"] = score

        return stats

    # --- Private Methoden ---

    def _detect_rephrase(self, current_text: str, previous_text: str) -> bool:
        """Aehnlichkeitscheck: Embedding-basierte Semantik + Keyword-Overlap Fallback.

        Nutzt Sentence-Transformer Embeddings fuer semantische Aehnlichkeit.
        Erkennt auch Rephrasings wie 'Mach das Licht an' vs 'Beleuchtung einschalten'.
        Fallback auf Keyword-Overlap wenn Embeddings nicht verfuegbar.
        """
        if not current_text or not previous_text:
            return False

        # Primaer: Embedding-basierte Aehnlichkeit (semantisch)
        try:
            from .embeddings import get_embedding, cosine_similarity
            emb_current = get_embedding(current_text.lower().strip())
            emb_previous = get_embedding(previous_text.lower().strip())
            if emb_current is not None and emb_previous is not None:
                similarity = cosine_similarity(emb_current, emb_previous)
                return similarity >= self._rephrase_threshold
        except Exception as e:
            logger.debug("Embedding-Vergleich fehlgeschlagen, Fallback auf Keyword-Overlap: %s", e)

        # Fallback: Keyword-Overlap (wenn Embeddings nicht verfuegbar)
        current_words = set(current_text.lower().split())
        previous_words = set(previous_text.lower().split())

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

    async def get_weak_categories(self, threshold: float = 0.3) -> list[dict]:
        """D5: Gibt Kategorien mit schlechtem Quality-Score zurueck.

        Wird von personality.py genutzt um VERMEIDE-Hints zu generieren.

        Args:
            threshold: Score-Schwelle unter der eine Kategorie als schlecht gilt.

        Returns:
            Liste von {category, score, rephrase_count, total} Dicts.
        """
        if not self.redis:
            return []

        weak = []
        for category in ("device_command", "knowledge", "smalltalk", "analysis"):
            score = await self.get_quality_score(category)
            if score < threshold:
                stats = await self.redis.hgetall(f"mha:response_quality:stats:{category}")
                total = int(stats.get("total", stats.get(b"total", 0)))
                rephrased = int(stats.get("rephrased", stats.get(b"rephrased", 0)))
                if total >= MIN_EXCHANGES_FOR_SCORE:
                    weak.append({
                        "category": category,
                        "score": round(score, 2),
                        "rephrase_count": rephrased,
                        "total": total,
                    })
        return weak

    # ── D6: Dynamic Few-Shot Examples ──────────────────────────

    async def _store_few_shot_example(self, category: str, user_text: str,
                                      response_text: str, person: str):
        """D6: Speichert einen guten Austausch als Few-Shot-Beispiel.

        Wird nur aufgerufen wenn score_target >= 0.8 (gute Qualitaet).
        Speichert User+Response-Text als Beispiel-Paar.
        """
        if not self.redis or not user_text:
            return

        # Ohne Response-Text kein sinnvolles Few-Shot-Beispiel
        if not response_text:
            return

        try:
            _cfg = yaml_config.get("dynamic_few_shot", {})
            if not _cfg.get("enabled", True):
                return

            _max_examples = _cfg.get("max_per_category", 10)
            _key = f"mha:few_shot:{category}"

            entry = json.dumps({
                "user_text": user_text[:200],
                "response_text": response_text[:300],
                "category": category,
                "person": person,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }, ensure_ascii=False)

            await self.redis.lpush(_key, entry)
            await self.redis.ltrim(_key, 0, _max_examples - 1)
            await self.redis.expire(_key, 60 * 86400)  # 60 Tage TTL

        except Exception as e:
            logger.debug("D6 Few-Shot Store Fehler: %s", e)

    async def get_few_shot_examples(self, category: str, limit: int = 3) -> list[dict]:
        """D6: Laedt die besten Few-Shot-Beispiele fuer eine Kategorie.

        Args:
            category: Antwort-Kategorie (device_command, knowledge, smalltalk, analysis)
            limit: Max. Anzahl Beispiele

        Returns:
            Liste von {user_text, category, person, timestamp} Dicts
        """
        if not self.redis:
            return []

        try:
            _cfg = yaml_config.get("dynamic_few_shot", {})
            if not _cfg.get("enabled", True):
                return []

            _key = f"mha:few_shot:{category}"
            raw = await self.redis.lrange(_key, 0, limit - 1)
            examples = []
            for r in raw:
                try:
                    entry = json.loads(r) if isinstance(r, str) else json.loads(r.decode())
                    examples.append(entry)
                except (json.JSONDecodeError, TypeError):
                    continue
            return examples

        except Exception as e:
            logger.debug("D6 Few-Shot Load Fehler: %s", e)
            return []
