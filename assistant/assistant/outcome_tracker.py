"""
Outcome Tracker - Wirkungstracker fuer Jarvis-Aktionen.

Beobachtet ob User-Aktionen nach Jarvis-Ausfuehrung rueckgaengig gemacht,
angepasst oder beibehalten werden. Verbales Feedback ("Danke") wird ebenfalls
erfasst. Ergebnis: Rolling Score 0-1 pro Aktionstyp.

Sicherheit: Rein lesend (nur get_state). Scores bounded 0-1. Redis TTL 90d.
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Optional

from .config import yaml_config

logger = logging.getLogger(__name__)

# Outcome-Klassifikationen
OUTCOME_POSITIVE = "positive"
OUTCOME_NEUTRAL = "neutral"
OUTCOME_PARTIAL = "partial"
OUTCOME_NEGATIVE = "negative"

# Score-Deltas pro Outcome
_SCORE_DELTAS = {
    OUTCOME_POSITIVE: 0.05,
    OUTCOME_NEUTRAL: 0.0,
    OUTCOME_PARTIAL: -0.02,
    OUTCOME_NEGATIVE: -0.05,
}

# Default-Score fuer neue Aktionstypen
DEFAULT_SCORE = 0.5

# Minimum Outcomes bevor Score berechnet wird
MIN_OUTCOMES_FOR_SCORE = 10

# Max daily score change (Data Poisoning Protection)
MAX_DAILY_CHANGE = 0.20

# Rolling Window fuer Score-Berechnung (neuere Daten wichtiger)
ROLLING_WINDOW = 200


class OutcomeTracker:
    """Trackt Wirkung von Jarvis-Aktionen durch Vorher/Nachher-Vergleich."""

    def __init__(self):
        self.redis = None
        self.ha = None
        self.enabled = False
        self._pending_count = 0
        self._max_pending = 20
        self._cfg = yaml_config.get("outcome_tracker", {})
        self._observation_delay = self._cfg.get("observation_delay_seconds", 180)
        self._max_results = self._cfg.get("max_results", 500)
        self._task_registry = None

    async def initialize(self, redis_client, ha_client, task_registry=None):
        """Initialisiert mit Redis und HA Client."""
        self.redis = redis_client
        self.ha = ha_client
        self._task_registry = task_registry
        self.enabled = self._cfg.get("enabled", True) and self.redis is not None
        logger.info("OutcomeTracker initialisiert (enabled=%s, delay=%ds)",
                     self.enabled, self._observation_delay)

    async def track_action(self, action_type: str, args: dict, result: dict,
                           person: str = "", room: str = ""):
        """Snapshot nach Aktion + Delayed Check starten."""
        if not self.enabled or not self.redis or not self.ha:
            return

        if self._pending_count >= self._max_pending:
            logger.debug("OutcomeTracker: Max pending erreicht (%d)", self._max_pending)
            return

        # Entity-ID bestimmen
        entity_id = args.get("entity_id", "")
        if not entity_id:
            r = args.get("room", room or "")
            if r and action_type in ("set_light", "set_cover", "set_climate", "set_switch"):
                domain = action_type.replace("set_", "")
                entity_id = f"{domain}.{r.lower().replace(' ', '_')}"

        if not entity_id:
            return

        # Aktuellen State snapshotten
        try:
            state = await self.ha.get_state(entity_id)
            if not state:
                return
        except Exception as e:
            logger.debug("OutcomeTracker snapshot Fehler: %s", e)
            return

        obs_id = str(uuid.uuid4())[:8]
        pending = {
            "id": obs_id,
            "action_type": action_type,
            "entity_id": entity_id,
            "args": args,
            "state_after": _extract_state_key(state),
            "person": person,
            "room": room,
            "timestamp": datetime.now().isoformat(),
        }

        # In Redis speichern mit TTL
        await self.redis.setex(
            f"mha:outcome:pending:{obs_id}",
            self._observation_delay + 120,  # Etwas mehr TTL als Delay
            json.dumps(pending, ensure_ascii=False),
        )
        self._pending_count += 1

        # Delayed Check als Background Task
        if self._task_registry:
            self._task_registry.create_task(
                self._delayed_check(obs_id, pending),
                name=f"outcome_check_{obs_id}",
            )
        else:
            asyncio.ensure_future(self._delayed_check(obs_id, pending))

    async def record_verbal_feedback(self, feedback_type: str, action_type: str = "",
                                     person: str = ""):
        """Manuelles Feedback: 'Danke' = POSITIVE, Korrektur = NEGATIVE."""
        if not self.enabled or not self.redis:
            return

        if feedback_type == "positive":
            outcome = OUTCOME_POSITIVE
        elif feedback_type == "negative":
            outcome = OUTCOME_NEGATIVE
        else:
            return

        # Verwende letzten Aktionstyp wenn keiner angegeben
        if not action_type:
            last = await self.redis.get("mha:outcome:last_action_type")
            action_type = last or "unknown"

        await self._store_outcome(action_type, outcome, person)

    async def get_success_score(self, action_type: str) -> float:
        """Rolling Score 0-1 fuer einen Aktionstyp."""
        if not self.redis:
            return DEFAULT_SCORE

        score = await self.redis.get(f"mha:outcome:score:{action_type}")
        if score is not None:
            return float(score)

        # Pruefen ob genug Daten fuer Score-Berechnung
        total = await self.redis.hget(f"mha:outcome:stats:{action_type}", "total")
        if not total or int(total) < MIN_OUTCOMES_FOR_SCORE:
            return DEFAULT_SCORE

        return DEFAULT_SCORE

    async def get_person_score(self, action_type: str, person: str) -> float:
        """Per-Person Score fuer einen Aktionstyp."""
        if not self.redis or not person:
            return DEFAULT_SCORE

        score = await self.redis.get(
            f"mha:outcome:score:{action_type}:person:{person}"
        )
        return float(score) if score is not None else DEFAULT_SCORE

    async def get_stats(self) -> dict:
        """Statistiken fuer Self-Report."""
        if not self.redis:
            return {}

        stats = {}
        cursor = 0
        while True:
            cursor, keys = await self.redis.scan(
                cursor, match="mha:outcome:stats:*", count=50
            )
            for key in keys:
                # Skip person-specific keys for global stats
                parts = key.split(":")
                if "person" in parts:
                    continue
                action_type = key.replace("mha:outcome:stats:", "")
                data = await self.redis.hgetall(f"mha:outcome:stats:{action_type}")
                score = await self.redis.get(f"mha:outcome:score:{action_type}")
                stats[action_type] = {
                    k: int(v) for k, v in data.items()
                }
                stats[action_type]["score"] = float(score) if score else DEFAULT_SCORE
            if cursor == 0:
                break

        return stats

    async def get_weekly_trends(self) -> dict:
        """Woechentliche Score-Trends fuer Self-Report / Self-Optimization."""
        if not self.redis:
            return {}

        trends = {}
        raw = await self.redis.lrange("mha:outcome:results", 0, self._max_results - 1)
        if not raw:
            return {}

        # Ergebnisse nach Woche und Aktionstyp gruppieren
        from collections import defaultdict
        weekly = defaultdict(lambda: defaultdict(list))
        for item in raw:
            try:
                entry = json.loads(item)
                ts = datetime.fromisoformat(entry["timestamp"])
                week_key = ts.strftime("%Y-W%W")
                action = entry.get("action_type", "unknown")
                outcome = entry.get("outcome", OUTCOME_NEUTRAL)
                score_val = _SCORE_DELTAS.get(outcome, 0.0)
                weekly[action][week_key].append(score_val)
            except (json.JSONDecodeError, KeyError, ValueError):
                continue

        # Woechentliche Durchschnitte berechnen
        for action, weeks in weekly.items():
            sorted_weeks = sorted(weeks.keys())[-4:]  # Letzte 4 Wochen
            trend = []
            for w in sorted_weeks:
                vals = weeks[w]
                avg = sum(vals) / len(vals) if vals else 0
                trend.append(round(DEFAULT_SCORE + avg, 2))
            trends[action] = trend

        return trends

    # --- Private Methoden ---

    async def _delayed_check(self, obs_id: str, pending: dict):
        """Nach Delay: Entity-State erneut pruefen und Outcome klassifizieren."""
        try:
            await asyncio.sleep(self._observation_delay)

            entity_id = pending["entity_id"]
            action_type = pending["action_type"]

            # Aktuellen State holen
            try:
                current_state = await self.ha.get_state(entity_id)
                if not current_state:
                    self._pending_count = max(0, self._pending_count - 1)
                    return
            except Exception:
                self._pending_count = max(0, self._pending_count - 1)
                return

            state_now = _extract_state_key(current_state)
            state_after = pending["state_after"]

            outcome = self._classify_outcome(state_after, state_now, action_type)
            person = pending.get("person", "")

            await self._store_outcome(action_type, outcome, person,
                                      room=pending.get("room", ""))

            logger.info("Outcome [%s]: %s (Entity: %s, Person: %s)",
                        outcome, action_type, entity_id, person or "unbekannt")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("OutcomeTracker delayed check Fehler: %s", e)
        finally:
            self._pending_count = max(0, self._pending_count - 1)
            if self.redis:
                await self.redis.delete(f"mha:outcome:pending:{obs_id}")

    def _classify_outcome(self, state_after: dict, state_now: dict,
                          action_type: str) -> str:
        """Vergleicht State: Rueckgaengig = NEGATIVE, angepasst = PARTIAL, gleich = NEUTRAL."""
        if not state_after or not state_now:
            return OUTCOME_NEUTRAL

        after_state = state_after.get("state", "")
        now_state = state_now.get("state", "")

        # State komplett rueckgaengig gemacht (z.B. Licht wieder aus)
        if after_state != now_state:
            return OUTCOME_NEGATIVE

        # Attribute vergleichen (z.B. Helligkeit geaendert)
        after_attrs = state_after.get("attributes", {})
        now_attrs = state_now.get("attributes", {})

        changed_attrs = 0
        total_attrs = 0
        for key in set(after_attrs.keys()) | set(now_attrs.keys()):
            if key in ("friendly_name", "icon", "supported_features"):
                continue
            total_attrs += 1
            if after_attrs.get(key) != now_attrs.get(key):
                changed_attrs += 1

        if total_attrs > 0 and changed_attrs > 0:
            ratio = changed_attrs / total_attrs
            if ratio > 0.5:
                return OUTCOME_NEGATIVE
            return OUTCOME_PARTIAL

        return OUTCOME_NEUTRAL

    async def _store_outcome(self, action_type: str, outcome: str,
                             person: str = "", room: str = ""):
        """Speichert Outcome in Redis und aktualisiert Scores."""
        if not self.redis:
            return

        entry = json.dumps({
            "action_type": action_type,
            "outcome": outcome,
            "person": person,
            "room": room,
            "timestamp": datetime.now().isoformat(),
        }, ensure_ascii=False)

        # Ergebnis-Liste (max N Eintraege)
        await self.redis.lpush("mha:outcome:results", entry)
        await self.redis.ltrim("mha:outcome:results", 0, self._max_results - 1)
        await self.redis.expire("mha:outcome:results", 90 * 86400)

        # Stats pro Aktionstyp
        stats_key = f"mha:outcome:stats:{action_type}"
        await self.redis.hincrby(stats_key, outcome, 1)
        await self.redis.hincrby(stats_key, "total", 1)
        await self.redis.expire(stats_key, 180 * 86400)

        # Stats pro Aktionstyp + Room
        if room:
            room_key = f"mha:outcome:stats:{action_type}:{room}"
            await self.redis.hincrby(room_key, outcome, 1)
            await self.redis.hincrby(room_key, "total", 1)
            await self.redis.expire(room_key, 90 * 86400)

        # Per-Person Stats (Feature 6)
        if person:
            person_key = f"mha:outcome:stats:{action_type}:person:{person}"
            await self.redis.hincrby(person_key, outcome, 1)
            await self.redis.hincrby(person_key, "total", 1)
            await self.redis.expire(person_key, 90 * 86400)

        # Score aktualisieren
        await self._update_score(action_type, outcome)

        # Per-Person Score
        if person:
            await self._update_score(action_type, outcome, person=person)

        # Letzten Aktionstyp merken (fuer verbal feedback ohne Kontext)
        await self.redis.setex("mha:outcome:last_action_type", 300, action_type)

    async def _update_score(self, action_type: str, outcome: str, person: str = ""):
        """Aktualisiert den Rolling Score (EMA, alpha=0.1)."""
        if not self.redis:
            return

        if person:
            score_key = f"mha:outcome:score:{action_type}:person:{person}"
            stats_key = f"mha:outcome:stats:{action_type}:person:{person}"
        else:
            score_key = f"mha:outcome:score:{action_type}"
            stats_key = f"mha:outcome:stats:{action_type}"

        # Minimum-Datenmenge pruefen
        total = await self.redis.hget(stats_key, "total")
        if not total or int(total) < MIN_OUTCOMES_FOR_SCORE:
            return

        current = await self.redis.get(score_key)
        current_score = float(current) if current else DEFAULT_SCORE

        # EMA: Score = alpha * new + (1-alpha) * old
        alpha = 0.1
        target = 1.0 if outcome == OUTCOME_POSITIVE else (
            0.5 if outcome == OUTCOME_NEUTRAL else (
                0.3 if outcome == OUTCOME_PARTIAL else 0.0
            )
        )
        new_score = alpha * target + (1 - alpha) * current_score

        # Data Poisoning Protection: Max daily change
        delta = new_score - current_score
        clamped_delta = max(-MAX_DAILY_CHANGE, min(MAX_DAILY_CHANGE, delta))
        final_score = max(0.0, min(1.0, current_score + clamped_delta))

        ttl = 180 * 86400
        await self.redis.setex(score_key, ttl, str(round(final_score, 4)))


def _extract_state_key(state) -> dict:
    """Extrahiert relevante State-Daten aus HA Entity State."""
    if not state:
        return {}
    if isinstance(state, dict):
        return {
            "state": state.get("state", ""),
            "attributes": {
                k: v for k, v in state.get("attributes", {}).items()
                if k not in ("friendly_name", "icon", "supported_features",
                             "entity_picture", "device_class")
            },
        }
    # State-Objekt mit .state und .attributes
    try:
        return {
            "state": str(getattr(state, "state", "")),
            "attributes": dict(getattr(state, "attributes", {})),
        }
    except Exception:
        return {}
