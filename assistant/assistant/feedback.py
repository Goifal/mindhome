"""
Feedback Tracker - Phase 5: Der MindHome Assistant lernt aus Reaktionen.

Verfolgt wie der Benutzer auf proaktive Meldungen reagiert und passt
das Verhalten entsprechend an:
- Oft ignorierte Meldungen -> seltener senden
- Geschaetzte Meldungen -> haeufiger senden
- Adaptiver Cooldown pro Event-Typ
- Auto-Timeout: Keine Reaktion = "ignored"
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as redis

from .config import yaml_config
from .constants import REDIS_FEEDBACK_SCORE_TTL

logger = logging.getLogger(__name__)

# Feedback-Typen und ihre Score-Deltas
FEEDBACK_DELTAS = {
    "ignored": -0.05,    # Keine Reaktion (Auto-Timeout)
    "dismissed": -0.10,  # Aktiv weggeklickt
    "acknowledged": 0.05,  # Zur Kenntnis genommen
    "engaged": 0.10,     # Drauf eingegangen
    "praised": 0.15,     # Allgemeines Lob ("super", "toll", "perfekt")
    "thanked": 0.20,     # Expliziter Dank ("danke", "vielen dank")
}

# Woerter zur Auto-Erkennung von positivem Feedback
_THANK_WORDS = frozenset({
    "danke", "dankeschön", "dankeschoen", "vielen dank", "thanks", "thank you",
})
_PRAISE_WORDS = frozenset({
    "super", "toll", "genau richtig", "perfekt", "gut gemacht",
    "klasse", "prima", "sehr gut", "top", "wunderbar", "großartig",
    "grossartig", "spitze", "ausgezeichnet", "hervorragend",
})

# Standard-Score fuer neue Event-Typen
DEFAULT_SCORE = 0.5

# Score-Grenzen fuer Entscheidungen
SCORE_SUPPRESS = 0.15     # Unter diesem Wert: nicht mehr senden
SCORE_REDUCE = 0.30       # Unter diesem Wert: laengerer Cooldown
SCORE_NORMAL = 0.50       # Normaler Cooldown
SCORE_BOOST = 0.70        # Ueber diesem Wert: kuerzerer Cooldown


class FeedbackTracker:
    """Verfolgt und lernt aus Benutzer-Feedback auf proaktive Meldungen."""

    def __init__(self):
        self.redis: Optional[redis.Redis] = None

        # Pending notifications: warten auf Feedback
        # {notification_id: {"event_type": str, "sent_at": datetime}}
        self._pending: dict[str, dict] = {}
        self._pending_lock = asyncio.Lock()

        # Auto-Timeout Task
        self._timeout_task: Optional[asyncio.Task] = None
        self._running = False

        # Konfiguration aus YAML laden
        feedback_cfg = yaml_config.get("feedback", {})
        self.auto_timeout_seconds = feedback_cfg.get("auto_timeout_seconds", 120)
        self.base_cooldown_seconds = feedback_cfg.get("base_cooldown_seconds", 300)

    async def initialize(self, redis_client: Optional[redis.Redis] = None):
        """Initialisiert den Tracker mit Redis-Verbindung."""
        self.redis = redis_client
        self._running = True
        self._timeout_task = asyncio.create_task(self._auto_timeout_loop())
        self._timeout_task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        logger.info("FeedbackTracker initialisiert")

    async def stop(self):
        """Stoppt den Auto-Timeout Loop."""
        self._running = False
        if self._timeout_task:
            self._timeout_task.cancel()
            try:
                await self._timeout_task
            except asyncio.CancelledError:
                pass

    # ----- Notification Tracking -----

    async def track_notification(self, notification_id: str, event_type: str):
        """Registriert eine gesendete proaktive Meldung (wartet auf Feedback)."""
        async with self._pending_lock:
            self._pending[notification_id] = {
                "event_type": event_type,
                "sent_at": datetime.now(timezone.utc),
            }

        # Gesamt-Zaehler erhoehen
        await self._increment_counter(event_type, "total_sent")

        logger.debug(
            "Notification tracked: %s (type: %s)", notification_id, event_type
        )

    @staticmethod
    def detect_positive_feedback(text: str) -> Optional[str]:
        """Erkennt positives Feedback in User-Text automatisch.

        Returns:
            'thanked' bei explizitem Dank, 'praised' bei Lob, None sonst.
        """
        if not text:
            return None
        _lower = text.lower()
        if any(w in _lower for w in _THANK_WORDS):
            return "thanked"
        if any(w in _lower for w in _PRAISE_WORDS):
            return "praised"
        return None

    async def record_feedback(
        self, notification_id: str, feedback_type: str
    ) -> Optional[dict]:
        """
        Verarbeitet Feedback auf eine proaktive Meldung.

        Args:
            notification_id: ID der Meldung (oder event_type als Fallback)
            feedback_type: ignored, dismissed, acknowledged, engaged, thanked

        Returns:
            Dict mit neuem Score und event_type, oder None bei Fehler.
        """
        if feedback_type not in FEEDBACK_DELTAS:
            logger.warning("Unbekannter Feedback-Typ: %s", feedback_type)
            return None

        # Event-Typ ermitteln
        event_type = None
        async with self._pending_lock:
            pending_entry = self._pending.get(notification_id)
        if pending_entry is not None:
            event_type = pending_entry.get("event_type")
        else:
            # Fallback: notification_id ist der event_type
            event_type = notification_id

        if not event_type:
            return None

        delta = FEEDBACK_DELTAS[feedback_type]

        # Score aktualisieren
        new_score = await self._update_score(event_type, delta)

        # Feedback-History speichern
        await self._store_feedback_entry(event_type, feedback_type, delta)

        # Zaehler aktualisieren
        await self._increment_counter(event_type, feedback_type)

        # Pending erst nach erfolgreichem Score-Update entfernen
        async with self._pending_lock:
            self._pending.pop(notification_id, None)

        logger.info(
            "Feedback [%s] fuer '%s': %+.2f -> Score: %.2f",
            feedback_type, event_type, delta, new_score,
        )

        return {
            "event_type": event_type,
            "feedback_type": feedback_type,
            "delta": delta,
            "new_score": new_score,
        }

    # ----- Score & Entscheidungen -----

    async def get_score(self, event_type: str) -> float:
        """Holt den aktuellen Feedback-Score fuer einen Event-Typ."""
        if not self.redis:
            return DEFAULT_SCORE
        score = await self.redis.get(f"mha:feedback:score:{event_type}")
        if score:
            score = score.decode() if isinstance(score, bytes) else score
            return float(score)
        return DEFAULT_SCORE

    async def should_notify(self, event_type: str, urgency: str,
                            person: str = "") -> dict:
        """
        Entscheidet ob eine proaktive Meldung gesendet werden soll.

        Verwendet Per-Person-Score wenn Person bekannt ist, sonst globalen Score.

        Returns:
            Dict mit:
                allow: bool - Meldung senden?
                reason: str - Begruendung
                cooldown: int - Empfohlener Cooldown in Sekunden
        """
        # Critical immer durchlassen
        if urgency == "critical":
            return {
                "allow": True,
                "reason": "critical_always_allowed",
                "cooldown": 0,
            }

        # Per-Person Score hat Vorrang wenn verfuegbar
        if person:
            score = await self.get_person_score(event_type, person)
        else:
            score = await self.get_score(event_type)

        # HIGH: nur unterdruecken wenn Score sehr niedrig
        if urgency == "high":
            if score < SCORE_SUPPRESS:
                return {
                    "allow": False,
                    "reason": f"score_too_low ({score:.2f})",
                    "cooldown": 0,
                }
            return {
                "allow": True,
                "reason": "high_priority",
                "cooldown": self._calculate_cooldown(score),
            }

        # MEDIUM: unterdruecken wenn Score niedrig
        if urgency == "medium":
            if score < SCORE_REDUCE:
                return {
                    "allow": False,
                    "reason": f"score_too_low ({score:.2f})",
                    "cooldown": 0,
                }
            return {
                "allow": True,
                "reason": "score_ok",
                "cooldown": self._calculate_cooldown(score),
            }

        # LOW: strenger filtern
        if score < SCORE_NORMAL:
            return {
                "allow": False,
                "reason": f"low_priority_score_insufficient ({score:.2f})",
                "cooldown": 0,
            }

        return {
            "allow": True,
            "reason": "score_ok",
            "cooldown": self._calculate_cooldown(score),
        }

    def _calculate_cooldown(self, score: float) -> int:
        """Berechnet den adaptiven Cooldown basierend auf dem Score."""
        if score >= SCORE_BOOST:
            # Guter Score -> kuerzerer Cooldown (60% der Basis)
            return int(self.base_cooldown_seconds * 0.6)
        elif score >= SCORE_NORMAL:
            # Normaler Score -> Standard-Cooldown
            return self.base_cooldown_seconds
        elif score >= SCORE_REDUCE:
            # Niedriger Score -> laengerer Cooldown (200% der Basis)
            return int(self.base_cooldown_seconds * 2.0)
        else:
            # Sehr niedrig -> sehr langer Cooldown (500% der Basis)
            return int(self.base_cooldown_seconds * 5.0)

    # ----- Statistiken -----

    async def get_stats(self, event_type: Optional[str] = None) -> dict:
        """Holt Feedback-Statistiken (gesamt oder pro Event-Typ)."""
        if not self.redis:
            return {"error": "redis_unavailable"}

        if event_type:
            return await self._get_event_stats(event_type)

        # Alle Event-Typen sammeln
        keys = []
        cursor = 0
        try:
            while True:
                cursor, batch = await self.redis.scan(
                    cursor, match="mha:feedback:score:*", count=100
                )
                keys.extend(batch)
                if cursor == 0:
                    break
        except Exception as e:
            logger.warning("L1: Feedback score SCAN failed: %s", e)

        # Collect event types from keys
        event_types = []
        for key in keys:
            key = key.decode() if isinstance(key, bytes) else key
            et = key.replace("mha:feedback:score:", "")
            event_types.append(et)

        # Batch-fetch all scores via mget
        if event_types:
            score_keys = [f"mha:feedback:score:{et}" for et in event_types]
            raw_scores = await self.redis.mget(score_keys)
        else:
            raw_scores = []

        stats = {}
        for et, raw_score in zip(event_types, raw_scores):
            if isinstance(raw_score, bytes):
                raw_score = raw_score.decode()
            score = float(raw_score) if raw_score else DEFAULT_SCORE
            counters = await self._get_counters(et)
            recent = await self._get_recent_feedback(et, limit=5)
            cooldown = self._calculate_cooldown(score)
            stats[et] = {
                "score": score,
                "cooldown_seconds": cooldown,
                "counters": counters,
                "recent_feedback": recent,
            }

        return {
            "event_types": stats,
            "total_types": len(stats),
            "pending_notifications": len(self._pending),
        }

    async def _get_event_stats(self, event_type: str) -> dict:
        """Holt detaillierte Statistiken fuer einen Event-Typ."""
        score = await self.get_score(event_type)
        counters = await self._get_counters(event_type)
        recent = await self._get_recent_feedback(event_type, limit=5)
        cooldown = self._calculate_cooldown(score)

        return {
            "score": score,
            "cooldown_seconds": cooldown,
            "counters": counters,
            "recent_feedback": recent,
        }

    async def get_all_scores(self) -> dict[str, float]:
        """Holt alle Feedback-Scores."""
        if not self.redis:
            return {}

        scores = {}
        all_keys = []
        cursor = 0
        try:
            while True:
                cursor, keys = await self.redis.scan(
                    cursor, match="mha:feedback:score:*", count=100
                )
                for key in keys:
                    key = key.decode() if isinstance(key, bytes) else key
                    all_keys.append(key)
                if cursor == 0:
                    break
        except Exception as e:
            logger.warning("L2: Feedback all_scores SCAN failed: %s", e)
            return scores

        if all_keys:
            raw_values = await self.redis.mget(all_keys)
            for key, val in zip(all_keys, raw_values):
                et = key.replace("mha:feedback:score:", "")
                if isinstance(val, bytes):
                    val = val.decode()
                scores[et] = float(val) if val else DEFAULT_SCORE

        return scores

    # ----- Private Hilfsmethoden -----

    def _apply_smoothing(self, old_score: float, raw_new_score: float) -> float:
        """Wendet Exponential Moving Average auf den Score an (Feature 9)."""
        feedback_cfg = yaml_config.get("feedback", {})
        if not feedback_cfg.get("smoothing_enabled", True):
            return raw_new_score
        factor = feedback_cfg.get("smoothing_factor", 0.3)
        factor = max(0.0, min(1.0, factor))
        return (1.0 - factor) * old_score + factor * raw_new_score

    async def _update_score(self, event_type: str, delta: float,
                           person: str = "") -> float:
        """Aktualisiert den Score und gibt den neuen Wert zurueck."""
        if not self.redis:
            return DEFAULT_SCORE

        current = await self.get_score(event_type)
        raw_new = max(0.0, min(1.0, current + delta))
        new_score = max(0.0, min(1.0, self._apply_smoothing(current, raw_new)))
        await self.redis.setex(f"mha:feedback:score:{event_type}", REDIS_FEEDBACK_SCORE_TTL, str(new_score))

        # Per-Person Score (Feature 6: Per-Person Learning)
        if person:
            person_key = f"mha:feedback:score:{event_type}:person:{person}"
            person_current = await self.redis.get(person_key)
            if isinstance(person_current, bytes):
                person_current = person_current.decode()
            person_score = float(person_current) if person_current else DEFAULT_SCORE
            person_raw = max(0.0, min(1.0, person_score + delta))
            person_new = max(0.0, min(1.0, self._apply_smoothing(person_score, person_raw)))
            await self.redis.setex(person_key, REDIS_FEEDBACK_SCORE_TTL, str(person_new))

        return new_score

    async def get_person_score(self, event_type: str, person: str) -> float:
        """Per-Person Feedback-Score (Feature 6)."""
        if not self.redis or not person:
            return DEFAULT_SCORE
        score = await self.redis.get(f"mha:feedback:score:{event_type}:person:{person}")
        if isinstance(score, bytes):
            score = score.decode()
        if score:
            return float(score)
        return DEFAULT_SCORE

    async def _increment_counter(self, event_type: str, counter_name: str):
        """Erhoeht einen Zaehler fuer einen Event-Typ."""
        if not self.redis:
            return
        try:
            await self.redis.hincrby(
                f"mha:feedback:counters:{event_type}", counter_name, 1
            )
        except Exception as e:
            logger.warning("Counter increment failed for %s/%s: %s", event_type, counter_name, e)

    async def _get_counters(self, event_type: str) -> dict:
        """Holt alle Zaehler fuer einen Event-Typ."""
        if not self.redis:
            return {}
        data = await self.redis.hgetall(f"mha:feedback:counters:{event_type}")
        return {
            (k.decode() if isinstance(k, bytes) else k): int(v)
            for k, v in data.items()
        }

    async def _store_feedback_entry(
        self, event_type: str, feedback_type: str, delta: float
    ):
        """Speichert einen Feedback-Eintrag in der History."""
        if not self.redis:
            return

        entry = json.dumps({
            "type": feedback_type,
            "delta": delta,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        key = f"mha:feedback:history:{event_type}"
        await self.redis.lpush(key, entry)
        # Nur die letzten 500 Eintraege behalten
        await self.redis.ltrim(key, 0, 499)
        await self.redis.expire(key, REDIS_FEEDBACK_SCORE_TTL)

    async def _get_recent_feedback(
        self, event_type: str, limit: int = 5
    ) -> list[dict]:
        """Holt die letzten Feedback-Eintraege fuer einen Event-Typ."""
        if not self.redis:
            return []

        key = f"mha:feedback:history:{event_type}"
        entries = await self.redis.lrange(key, 0, limit - 1)
        result = []
        for e in entries:
            try:
                result.append(json.loads(e))
            except (json.JSONDecodeError, TypeError):
                continue
        return result

    async def _auto_timeout_loop(self):
        """Prueft periodisch auf Meldungen ohne Feedback (Auto-Timeout)."""
        while self._running:
            try:
                await asyncio.sleep(30)  # Alle 30 Sekunden pruefen
                await self._check_timeouts()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Fehler im Auto-Timeout Loop: %s", e)

    async def _check_timeouts(self):
        """Markiert alte Meldungen ohne Feedback als 'ignored'."""
        now = datetime.now(timezone.utc)
        timeout = timedelta(seconds=self.auto_timeout_seconds)

        expired = []
        async with self._pending_lock:
            for nid, info in list(self._pending.items()):
                if now - info["sent_at"] > timeout:
                    expired.append(nid)

        # Event-Typen die keinen Auto-Timeout-Abzug bekommen
        # (TTS-only Meldungen: User kann nicht "acknowledgen")
        _NO_AUTO_TIMEOUT_EVENTS = {"observation", "batch_summary", "ambient_status"}

        for nid in expired:
            async with self._pending_lock:
                info = self._pending.pop(nid, None)
            if info is None:
                continue
            # TTS-only Meldungen: kein Score-Abzug bei Timeout
            if info.get("event_type") in _NO_AUTO_TIMEOUT_EVENTS:
                logger.debug(
                    "Auto-Timeout uebersprungen (TTS-only): '%s'", info["event_type"]
                )
                continue
            await self._update_score(info["event_type"], FEEDBACK_DELTAS["ignored"])
            await self._store_feedback_entry(
                info["event_type"], "ignored", FEEDBACK_DELTAS["ignored"]
            )
            await self._increment_counter(info["event_type"], "ignored")
            logger.debug(
                "Auto-Timeout: '%s' als ignored markiert", info["event_type"]
            )

    def get_feedback_intensity(self, event_type: str, count: int) -> str:
        """Gibt die Feedback-Intensitaet basierend auf Wiederholungen zurueck.

        1x: "info", 2-3x: "reminder", 4-5x: "warning", 6+: "urgent"
        """
        if count <= 1:
            return "info"
        if count <= 3:
            return "reminder"
        if count <= 5:
            return "warning"
        return "urgent"

    _EVENT_COOLDOWNS: dict[str, int] = {
        "anticipation_suggestion": 1800,  # 30 min
        "wellness_nudge": 3600,           # 1h
        "spontaneous_observation": 5400,  # 90 min
        "learning_suggestion": 7200,      # 2h
        "insight": 3600,                  # 1h
    }

    def get_event_cooldown(self, event_type: str) -> int:
        """Gibt den spezifischen Cooldown fuer einen Event-Typ zurueck."""
        return self._EVENT_COOLDOWNS.get(event_type, 1800)  # Default 30min
