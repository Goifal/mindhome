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
from datetime import datetime, timezone
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
        self._pending_lock = asyncio.Lock()
        self._max_pending = 20
        self._cfg = yaml_config.get("outcome_tracker", {})
        self._observation_delay = self._cfg.get("observation_delay_seconds", 180)
        self._max_results = self._cfg.get("max_results", 500)
        self._calibration_min = self._cfg.get("calibration_min", 0.5)
        self._calibration_max = self._cfg.get("calibration_max", 1.5)
        self._task_registry = None
        self._background_tasks: set[asyncio.Task] = set()
        self._learning_observer = None
        self._lo_feedback_enabled = self._cfg.get("learning_observer_feedback", True)
        self._lo_learning_boost = float(self._cfg.get("learning_boost", 0.1))
        self._anticipation = None
        self._anticipation_feedback_enabled = self._cfg.get(
            "anticipation_feedback", True
        )
        self._anticipation_success_boost = float(
            self._cfg.get("success_confidence_boost", 0.1)
        )
        self._anticipation_failure_penalty = float(
            self._cfg.get("failure_confidence_penalty", 0.15)
        )
        # Konfigurierbare Werte fuer Follow-up-Learning und Poison Protection
        self._max_daily_change = float(
            self._cfg.get("max_daily_score_change", MAX_DAILY_CHANGE)
        )
        self._followup_window = int(
            self._cfg.get("followup_window_seconds", 120)
        )
        self._followup_min = int(
            self._cfg.get("followup_min_count", 3)
        )
        self._followup_ttl = int(
            self._cfg.get("followup_ttl_days", 90)
        ) * 86400
        self._low_score_threshold = float(
            self._cfg.get("low_score_threshold", 0.35)
        )

    async def initialize(self, redis_client, ha_client, task_registry=None):
        """Initialisiert mit Redis und HA Client."""
        self.redis = redis_client
        self.ha = ha_client
        self._task_registry = task_registry
        self.enabled = self._cfg.get("enabled", True) and self.redis is not None
        logger.info(
            "OutcomeTracker initialisiert (enabled=%s, delay=%ds)",
            self.enabled,
            self._observation_delay,
        )

    async def track_action(
        self,
        action_type: str,
        args: dict,
        result: dict,
        person: str = "",
        room: str = "",
    ):
        """Snapshot nach Aktion + Delayed Check starten."""
        if not self.enabled or not self.redis or not self.ha:
            return

        if self._pending_count >= self._max_pending:
            logger.debug("OutcomeTracker: Max pending erreicht (%d)", self._max_pending)
            return

        # Entity-ID bestimmen: bevorzuge aufgeloeste ID aus result (von _find_entity),
        # dann args, dann konstruierte ID als Fallback
        entity_id = ""
        if isinstance(result, dict) and result.get("entity_id"):
            entity_id = result["entity_id"]
        if not entity_id:
            entity_id = args.get("entity_id", "")
        if not entity_id:
            r = args.get("room", room or "")
            if r and action_type in (
                "set_light",
                "set_cover",
                "set_climate",
                "set_switch",
            ):
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
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # In Redis speichern mit TTL
        await self.redis.setex(
            f"mha:outcome:pending:{obs_id}",
            self._observation_delay + 120,  # Etwas mehr TTL als Delay
            json.dumps(pending, ensure_ascii=False),
        )
        async with self._pending_lock:
            self._pending_count += 1

        # Delayed Check als Background Task
        if self._task_registry:
            self._task_registry.create_task(
                self._delayed_check(obs_id, pending),
                name=f"outcome_check_{obs_id}",
            )
        else:
            task = asyncio.ensure_future(self._delayed_check(obs_id, pending))
            self._background_tasks.add(task)

            def _on_task_done(t):
                self._background_tasks.discard(t)
                if not t.cancelled():
                    exc = t.exception()
                    if exc:
                        logger.warning("OutcomeTracker delayed check fehlgeschlagen: %s", exc)

            task.add_done_callback(_on_task_done)

    async def record_verbal_feedback(
        self, feedback_type: str, action_type: str = "", person: str = ""
    ):
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
            last = last.decode() if isinstance(last, bytes) else last
            action_type = last or "unknown"

        await self._store_outcome(action_type, outcome, person)

    async def get_success_score(self, action_type: str, person: str = "") -> float:
        """Rolling Score 0-1 fuer einen Aktionstyp.

        Wenn person angegeben: Per-Person Score bevorzugen, Fallback auf global.
        """
        if not self.redis:
            return DEFAULT_SCORE

        # Per-Person Score bevorzugen
        if person:
            person_score = await self.get_person_score(action_type, person)
            if person_score != DEFAULT_SCORE:
                return person_score

        score = await self.redis.get(f"mha:outcome:score:{action_type}")
        if score is not None:
            score = score.decode() if isinstance(score, bytes) else score
            return float(score)

        # Pruefen ob genug Daten fuer Score-Berechnung
        total = await self.redis.hget(f"mha:outcome:stats:{action_type}", "total")
        if total is not None:
            total = total.decode() if isinstance(total, bytes) else total
        if not total or int(total) < MIN_OUTCOMES_FOR_SCORE:
            return DEFAULT_SCORE

        # Score aus positiv/negativ Verhaeltnis berechnen
        positive = await self.redis.hget(f"mha:outcome:stats:{action_type}", "positive")
        if positive is not None:
            positive = positive.decode() if isinstance(positive, bytes) else positive
        positive = int(positive) if positive else 0
        total_int = int(total)
        computed_score = positive / total_int if total_int > 0 else DEFAULT_SCORE
        # Score cachen fuer schnelleren Zugriff
        await self.redis.set(
            f"mha:outcome:score:{action_type}", str(round(computed_score, 4))
        )
        return computed_score

    async def get_person_score(self, action_type: str, person: str) -> float:
        """Per-Person Score fuer einen Aktionstyp."""
        if not self.redis or not person:
            return DEFAULT_SCORE

        score = await self.redis.get(f"mha:outcome:score:{action_type}:person:{person}")
        if score is not None:
            score = score.decode() if isinstance(score, bytes) else score
        return float(score) if score is not None else DEFAULT_SCORE

    async def get_stats(self) -> dict:
        """Statistiken fuer Self-Report."""
        if not self.redis:
            return {}

        stats = {}
        cursor = 0
        try:
            while True:
                cursor, keys = await self.redis.scan(
                    cursor, match="mha:outcome:stats:*", count=50
                )
                for key in keys:
                    # Nur globale Stats: mha:outcome:stats:{action_type} (4 Teile)
                    # Skip room-specific (5 Teile) und person-specific (6 Teile) Keys
                    key_str = key.decode() if isinstance(key, bytes) else key
                    parts = key_str.split(":")
                    if len(parts) != 4:
                        continue
                    action_type = parts[3]
                    raw = await self.redis.hgetall(f"mha:outcome:stats:{action_type}")
                    data = {
                        (k.decode() if isinstance(k, bytes) else k): (
                            v.decode() if isinstance(v, bytes) else v
                        )
                        for k, v in raw.items()
                    }
                    score = await self.redis.get(f"mha:outcome:score:{action_type}")
                    score = score.decode() if isinstance(score, bytes) else score
                    stats[action_type] = {k: int(v) for k, v in data.items()}
                    stats[action_type]["score"] = (
                        float(score) if score else DEFAULT_SCORE
                    )
                if cursor == 0:
                    break
        except Exception as e:
            logger.warning("L6: Outcome stats SCAN failed: %s", e)

        return stats

    async def get_all_scores(self) -> dict[str, float]:
        """Gibt alle globalen Outcome-Scores zurueck.

        Returns:
            Dict mit action_type -> score (0.0-1.0)
        """
        if not self.redis:
            return {}

        scores = {}
        cursor = 0
        try:
            while True:
                cursor, keys = await self.redis.scan(
                    cursor, match="mha:outcome:score:*", count=50
                )
                for key in keys:
                    key_str = key.decode() if isinstance(key, bytes) else key
                    parts = key_str.split(":")
                    # Nur globale Scores (4 Teile), nicht per-person (6 Teile)
                    if len(parts) != 4:
                        continue
                    action_type = parts[3]
                    val = await self.redis.get(key)
                    if val is not None:
                        val = val.decode() if isinstance(val, bytes) else val
                        scores[action_type] = float(val)
                if cursor == 0:
                    break
        except Exception as e:
            logger.warning("get_all_scores SCAN failed: %s", e)

        return scores

    async def get_recent_failures(self, limit: int = 3) -> list[dict]:
        """Gibt die letzten fehlgeschlagenen Aktionen zurueck (fuer LLM-Context).

        Returns:
            Liste mit {"action_type": ..., "reason": ...} Dicts
        """
        if not self.redis:
            return []
        try:
            raw = await self.redis.lrange("mha:outcome:results", 0, 49)
            failures = []
            for entry in raw:
                data = json.loads(entry)
                if data.get("outcome") == OUTCOME_NEGATIVE:
                    _failure = {
                        "action_type": data.get("action_type", "unbekannt"),
                        "reason": data.get("room", ""),
                        "timestamp": data.get("timestamp", ""),
                    }
                    # Ursache einschliessen wenn vorhanden
                    _cause = data.get("failure_cause")
                    if _cause:
                        _failure["cause"] = _cause
                    failures.append(_failure)
                    if len(failures) >= limit:
                        break
            return failures
        except Exception as e:
            logger.debug("get_recent_failures: %s", e)
            return []

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

    # ------------------------------------------------------------------
    # Per-Domain Confidence Calibration
    # ------------------------------------------------------------------

    async def get_domain_calibration(self) -> dict[str, dict]:
        """Berechnet Kalibrierungsdaten pro Domain.

        Aggregiert alle Outcome-Scores nach Domain (climate, light, cover,
        media, security, etc.) und gibt fuer jede Domain:
        - ``avg_score``: Durchschnittlicher Erfolgs-Score
        - ``total_actions``: Gesamtzahl der Aktionen
        - ``calibration_factor``: Faktor fuer Confidence-Anpassung
          (>1.0 = Domain uebertrifft, <1.0 = Domain unterperformt)

        Returns:
            Dict[domain_name, {avg_score, total_actions, calibration_factor}]
        """
        if not self.redis:
            return {}

        try:
            domain_data: dict[str, list[float]] = {}

            cursor = 0
            while True:
                cursor, keys = await self.redis.scan(
                    cursor,
                    match="mha:outcome:score:*",
                    count=50,
                )
                for key in keys:
                    key_str = key.decode() if isinstance(key, bytes) else key
                    parts = key_str.split(":")
                    if len(parts) != 4:
                        continue
                    action_type = parts[3]

                    # Domain aus action_type extrahieren
                    domain = self._extract_domain(action_type)
                    if not domain:
                        continue

                    val = await self.redis.get(key)
                    if val is not None:
                        val_str = val.decode() if isinstance(val, bytes) else val
                        domain_data.setdefault(domain, []).append(float(val_str))
                if cursor == 0:
                    break

            # Kalibrierung berechnen
            calibration = {}
            global_avg = DEFAULT_SCORE
            all_scores = [s for scores in domain_data.values() for s in scores]
            if all_scores:
                global_avg = sum(all_scores) / len(all_scores)

            for domain, scores in domain_data.items():
                avg = sum(scores) / len(scores) if scores else DEFAULT_SCORE
                # Calibration Factor: relative Performance vs. Durchschnitt
                # 1.0 = durchschnittlich, >1.0 = besser, <1.0 = schlechter
                factor = avg / global_avg if global_avg > 0 else 1.0
                calibration[domain] = {
                    "avg_score": round(avg, 3),
                    "total_actions": len(scores),
                    "calibration_factor": round(
                        max(self._calibration_min, min(self._calibration_max, factor)),
                        3,
                    ),
                }

            return calibration

        except Exception as e:
            logger.debug("Domain calibration Fehler: %s", e)
            return {}

    async def get_calibrated_score(
        self,
        action_type: str,
        person: str = "",
    ) -> tuple[float, float]:
        """Gibt den kalibrierten Outcome-Score zurueck.

        Kombiniert den Roh-Score mit dem Domain-spezifischen
        Kalibrierungsfaktor.

        Returns:
            Tuple (raw_score, calibrated_score)
        """
        raw_score = await self.get_success_score(action_type, person)
        domain = self._extract_domain(action_type)

        if not domain:
            return raw_score, raw_score

        calibration = await self.get_domain_calibration()
        domain_cal = calibration.get(domain, {})
        factor = domain_cal.get("calibration_factor", 1.0)

        calibrated = max(0.0, min(1.0, raw_score * factor))
        return raw_score, round(calibrated, 4)

    @staticmethod
    def _extract_domain(action_type: str) -> str:
        """Extrahiert die Domain aus einem Aktionstyp.

        Beispiele:
            ``anticipation:set_climate`` -> ``climate``
            ``set_light_brightness`` -> ``light``
            ``turn_on_cover`` -> ``cover``
        """
        # Anticipation-Prefix entfernen
        at = action_type
        if at.startswith("anticipation:"):
            at = at[len("anticipation:") :]

        # Bekannte Domain-Patterns
        domain_keywords = {
            "climate": "climate",
            "light": "light",
            "cover": "cover",
            "media": "media",
            "lock": "security",
            "alarm": "security",
            "security": "security",
            "switch": "switch",
            "fan": "fan",
            "scene": "scene",
        }
        at_lower = at.lower()
        for keyword, domain in domain_keywords.items():
            if keyword in at_lower:
                return domain
        return ""

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
                    # Kein Decrement hier — finally-Block uebernimmt das
                    return
            except Exception as e:
                logger.debug("Geraetestatus-Abfrage fehlgeschlagen: %s", e)
                # Kein Decrement hier — finally-Block uebernimmt das
                return

            state_now = _extract_state_key(current_state)
            state_after = pending["state_after"]

            outcome = self._classify_outcome(state_after, state_now, action_type)
            person = pending.get("person", "")

            # Ursachen-Analyse bei negativem Outcome: WARUM wurde es korrigiert?
            failure_cause = None
            if outcome in (OUTCOME_NEGATIVE, OUTCOME_PARTIAL) and self.ha:
                failure_cause = await self._analyze_failure_cause(
                    entity_id, action_type, state_after, state_now,
                    room=pending.get("room", ""),
                )

            await self._store_outcome(
                action_type, outcome, person,
                room=pending.get("room", ""),
                failure_cause=failure_cause,
            )

            logger.info(
                "Outcome [%s]: %s (Entity: %s, Person: %s%s)",
                outcome,
                action_type,
                entity_id,
                person or "unbekannt",
                f", Ursache: {failure_cause}" if failure_cause else "",
            )

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("OutcomeTracker delayed check Fehler: %s", e)
        finally:
            async with self._pending_lock:
                self._pending_count = max(0, self._pending_count - 1)
            if self.redis:
                await self.redis.delete(f"mha:outcome:pending:{obs_id}")

    # Aktionstypen bei denen State-Aenderungen nach dem Delay normal sind
    # (Timer laufen aus, Klima-Schedules, circadiane Beleuchtung etc.)
    _EXPECTED_CHANGE_ACTIONS = frozenset(
        {
            "set_temperature",
            "set_hvac_mode",
            "climate_set",
            "timer_start",
            "timer_set",
            "set_sleep_timer",
            "set_brightness",
            "set_color_temp",  # circadian dimming
            "cover_set_position",  # auto-schedules
        }
    )

    # Attribute die sich durch Automatisierungen/Schedules normal aendern
    _VOLATILE_ATTRS = frozenset(
        {
            "current_temperature",
            "temperature",
            "hvac_action",
            "color_temp",
            "brightness",
            "position",
            "current_position",
        }
    )

    def _classify_outcome(
        self, state_after: dict, state_now: dict, action_type: str
    ) -> str:
        """Vergleicht State: Rueckgaengig = NEGATIVE, angepasst = PARTIAL, gleich = NEUTRAL.

        Beruecksichtigt erwartete Aenderungen (Timer, Schedules, circadiane Beleuchtung)
        und volatile Attribute um False-Negatives zu vermeiden.
        """
        if not state_after or not state_now:
            return OUTCOME_NEUTRAL

        after_state = state_after.get("state", "")
        now_state = state_now.get("state", "")

        # State komplett rueckgaengig gemacht (z.B. Licht wieder aus)
        if after_state != now_state:
            # Bei Aktionen mit erwartetem State-Wechsel (Timer, Klima) ist das normal
            if action_type in self._EXPECTED_CHANGE_ACTIONS:
                return OUTCOME_NEUTRAL
            return OUTCOME_NEGATIVE

        # Attribute vergleichen (z.B. Helligkeit geaendert)
        after_attrs = state_after.get("attributes", {})
        now_attrs = state_now.get("attributes", {})

        changed_attrs = 0
        total_attrs = 0
        for key in set(after_attrs.keys()) | set(now_attrs.keys()):
            if key in ("friendly_name", "icon", "supported_features"):
                continue
            # Volatile Attribute (Temperatur, Position) aendern sich natuerlich
            if key in self._VOLATILE_ATTRS:
                continue
            total_attrs += 1
            if after_attrs.get(key) != now_attrs.get(key):
                changed_attrs += 1

        if total_attrs == 0:
            return OUTCOME_NEUTRAL
        if changed_attrs > 0:
            ratio = changed_attrs / total_attrs
            if ratio > 0.5:
                return OUTCOME_NEGATIVE
            return OUTCOME_PARTIAL

        return OUTCOME_NEUTRAL

    async def _analyze_failure_cause(
        self,
        entity_id: str,
        action_type: str,
        state_after: dict,
        state_now: dict,
        room: str = "",
    ) -> Optional[str]:
        """Analysiert die Ursache eines negativen Outcomes (regelbasiert).

        Prueft haeufige Fehlerursachen:
        - Fenster offen bei Klima-Aktionen
        - Geraet unavailable/offline
        - Konfliktierende Automation
        - User-Revert (bewusste Korrektur)

        Returns:
            Ursachen-String oder None.
        """
        try:
            causes = []

            # 1. Geraet unavailable?
            now_state_val = state_now.get("state", "")
            if now_state_val == "unavailable":
                return "device_unavailable"

            # 2. Bei Klima: Fenster offen?
            if "climate" in action_type or "temperature" in action_type:
                states = await self.ha.get_states() if self.ha else []
                room_lower = room.lower().replace(" ", "_") if room else ""
                for s in states:
                    eid = s.get("entity_id", "")
                    if (
                        eid.startswith("binary_sensor.")
                        and ("window" in eid or "fenster" in eid)
                        and s.get("state") == "on"
                        and (not room_lower or room_lower in eid.lower())
                    ):
                        causes.append("window_open")
                        break

            # 3. State wurde komplett zurueckgesetzt (User-Revert)
            after_state = state_after.get("state", "")
            if after_state != now_state_val:
                causes.append("user_reverted")

            # 4. Attribute stark veraendert (partielle Korrektur)
            after_attrs = state_after.get("attributes", {})
            now_attrs = state_now.get("attributes", {})
            _changed = sum(
                1 for k in set(after_attrs) | set(now_attrs)
                if k not in ("friendly_name", "icon", "supported_features")
                and after_attrs.get(k) != now_attrs.get(k)
            )
            if _changed > 0 and after_state == now_state_val:
                causes.append("parameters_adjusted")

            return "|".join(causes) if causes else None

        except Exception as e:
            logger.debug("Failure cause analysis Fehler: %s", e)
            return None

    async def _store_outcome(
        self,
        action_type: str,
        outcome: str,
        person: str = "",
        room: str = "",
        failure_cause: Optional[str] = None,
    ):
        """Speichert Outcome in Redis und aktualisiert Scores."""
        if not self.redis:
            return

        # Device-Dependency-Kontext: War ein Konflikt aktiv bei dieser Aktion?
        _dep_influenced = False
        try:
            from .state_change_log import StateChangeLog
            import assistant.main as main_module

            if hasattr(main_module, "brain"):
                _states = await main_module.brain.ha.get_states() or []
                _hints = StateChangeLog.check_action_dependencies(
                    action_type, {}, _states
                )
                if _hints:
                    _dep_influenced = True
        except Exception as e:
            logger.debug("Abhaengigkeitspruefung fuer Outcome fehlgeschlagen: %s", e)

        _entry_data = {
            "action_type": action_type,
            "outcome": outcome,
            "person": person,
            "room": room,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if _dep_influenced:
            _entry_data["dependency_influenced"] = True
        if failure_cause:
            _entry_data["failure_cause"] = failure_cause
        entry = json.dumps(_entry_data, ensure_ascii=False)

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

        # LearningObserver feedback: boost pattern confidence on success
        if outcome == OUTCOME_POSITIVE and self._lo_feedback_enabled:
            await self._notify_learning_observer(action_type, person, room)

        # AnticipationEngine feedback: adjust pattern confidence based on outcome
        if self._anticipation_feedback_enabled and outcome in (
            OUTCOME_POSITIVE,
            OUTCOME_NEGATIVE,
        ):
            await self._notify_anticipation_engine(action_type, outcome)

        # MCU Sprint 6: Auto-Opinion-Learning — Meinungen aus Geraete-Feedback bilden
        if outcome in (OUTCOME_POSITIVE, OUTCOME_NEGATIVE):
            await self._update_auto_opinion(action_type, outcome, room)

        # Letzten Aktionstyp merken (fuer verbal feedback ohne Kontext)
        await self.redis.setex("mha:outcome:last_action_type", 300, action_type)

    async def _update_score(self, action_type: str, outcome: str, person: str = ""):
        """Aktualisiert den Rolling Score (EMA, alpha=0.1).

        Data Poisoning Protection:
        - Per-Update: Einzelner Delta auf ±MAX_DAILY_CHANGE begrenzt.
        - Kumulativ: Tages-Gesamtaenderung auf ±MAX_DAILY_CHANGE begrenzt.
          Tracking via Redis-Key mit 24h-TTL pro action_type(+person).
        """
        if not self.redis:
            return

        if person:
            score_key = f"mha:outcome:score:{action_type}:person:{person}"
            stats_key = f"mha:outcome:stats:{action_type}:person:{person}"
            daily_key = f"mha:outcome:daily_delta:{action_type}:person:{person}"
        else:
            score_key = f"mha:outcome:score:{action_type}"
            stats_key = f"mha:outcome:stats:{action_type}"
            daily_key = f"mha:outcome:daily_delta:{action_type}"

        # Minimum-Datenmenge pruefen
        total = await self.redis.hget(stats_key, "total")
        if total is not None:
            total = total.decode() if isinstance(total, bytes) else total
        if not total or int(total) < MIN_OUTCOMES_FOR_SCORE:
            return

        current = await self.redis.get(score_key)
        if current is not None:
            current = current.decode() if isinstance(current, bytes) else current
        current_score = float(current) if current else DEFAULT_SCORE

        # EMA: Score = alpha * new + (1-alpha) * old
        alpha = 0.1
        target = (
            1.0
            if outcome == OUTCOME_POSITIVE
            else (
                0.5
                if outcome == OUTCOME_NEUTRAL
                else (0.3 if outcome == OUTCOME_PARTIAL else 0.0)
            )
        )
        new_score = alpha * target + (1 - alpha) * current_score

        # Data Poisoning Protection: Per-Update Cap
        delta = new_score - current_score
        clamped_delta = max(-self._max_daily_change, min(self._max_daily_change, delta))

        # Data Poisoning Protection: Kumulative Tages-Cap
        # Trackt die Gesamtaenderung pro Tag via Redis (24h-TTL).
        # Wenn das Tagesbudget erschoepft ist, wird das Update uebersprungen.
        try:
            daily_raw = await self.redis.get(daily_key)
            daily_cumulative = (
                float(daily_raw.decode() if isinstance(daily_raw, bytes) else daily_raw)
                if daily_raw is not None
                else 0.0
            )
        except (ValueError, TypeError):
            daily_cumulative = 0.0

        # Verbleibendes Budget in Richtung des Deltas pruefen
        if clamped_delta > 0:
            remaining = self._max_daily_change - daily_cumulative
            if remaining <= 0:
                logger.debug(
                    "Poison Protection: Tages-Cap erreicht fuer %s (kumulativ: %.4f)",
                    action_type,
                    daily_cumulative,
                )
                return
            clamped_delta = min(clamped_delta, remaining)
        elif clamped_delta < 0:
            remaining = -self._max_daily_change - daily_cumulative
            if remaining >= 0:
                logger.debug(
                    "Poison Protection: Tages-Cap erreicht fuer %s (kumulativ: %.4f)",
                    action_type,
                    daily_cumulative,
                )
                return
            clamped_delta = max(clamped_delta, remaining)

        final_score = max(0.0, min(1.0, current_score + clamped_delta))

        ttl = 180 * 86400
        await self.redis.setex(score_key, ttl, str(round(final_score, 4)))

        # Kumulativen Tages-Delta aktualisieren (24h-TTL)
        new_cumulative = daily_cumulative + clamped_delta
        await self.redis.setex(daily_key, 86400, str(round(new_cumulative, 4)))

    async def _notify_learning_observer(
        self, action_type: str, person: str = "", room: str = ""
    ):
        """Boosts pattern confidence in LearningObserver on successful outcome."""
        try:
            if not self._learning_observer:
                import assistant.main as main_module

                if hasattr(main_module, "brain"):
                    self._learning_observer = getattr(
                        main_module.brain, "learning_observer", None
                    )
            if not self._learning_observer:
                return

            boost_redis_key = f"mha:outcome:lo_boost:{action_type}"
            if self.redis:
                already = await self.redis.get(boost_redis_key)
                if already:
                    return
                await self.redis.setex(boost_redis_key, 3600, "1")

            if hasattr(self._learning_observer, "boost_pattern_confidence"):
                await self._learning_observer.boost_pattern_confidence(
                    action_type,
                    self._lo_learning_boost,
                    person=person,
                    room=room,
                )
                logger.debug(
                    "LearningObserver boosted: %s +%.2f",
                    action_type,
                    self._lo_learning_boost,
                )
        except Exception as e:
            logger.debug("LearningObserver notification failed: %s", e)

    async def _notify_anticipation_engine(self, action_type: str, outcome: str):
        """Adjusts anticipation pattern confidence based on outcome result.

        On success: boosts confidence by configurable amount (default +0.1).
        On failure: reduces confidence by configurable amount (default -0.15).
        """
        try:
            if self._anticipation is None:
                import assistant.main as main_module

                if hasattr(main_module, "brain"):
                    self._anticipation = getattr(
                        main_module.brain, "anticipation", None
                    )
            if self._anticipation is None:
                return

            # Use record_feedback which already handles confidence + cooldown logic
            accepted = outcome == OUTCOME_POSITIVE
            # Build pattern description from action_type for feedback tracking
            pattern_desc = f"outcome:{action_type}"

            await self._anticipation.record_feedback(pattern_desc, accepted)

            # Additionally adjust adaptive threshold if available
            if hasattr(self._anticipation, "update_adaptive_threshold"):
                import hashlib

                pattern_hash = hashlib.md5(
                    action_type.encode(), usedforsecurity=False
                ).hexdigest()[:12]
                await self._anticipation.update_adaptive_threshold(
                    pattern_hash, accepted
                )

            delta = (
                self._anticipation_success_boost
                if accepted
                else -self._anticipation_failure_penalty
            )
            logger.debug(
                "Anticipation feedback: %s %s (delta=%+.2f)",
                action_type,
                outcome,
                delta,
            )
        except Exception as e:
            logger.debug("Anticipation feedback failed: %s", e)

    # ------------------------------------------------------------------
    # MCU Sprint 6: Auto-Opinion-Learning aus Geraete-Feedback
    # ------------------------------------------------------------------

    _AUTO_OPINION_FAILURE_THRESHOLD = 5
    _AUTO_OPINION_SUCCESS_THRESHOLD = 20
    _AUTO_OPINION_WINDOW_DAYS = 30

    async def _update_auto_opinion(
        self, action_type: str, outcome: str, room: str
    ) -> None:
        """Zaehlt Erfolge/Fehler pro Geraetetyp+Raum und bildet automatisch Meinungen.

        Bei >=5 Fehlern in 30 Tagen: negative Meinung.
        Bei >=20 Erfolgen ohne Fehler: positive Meinung.
        """
        if not self.redis:
            return

        device_key = f"{action_type}:{room}" if room else action_type
        redis_key = f"mha:auto_opinion:{device_key}"

        try:
            # Zaehler atomar inkrementieren
            if outcome == OUTCOME_NEGATIVE:
                await self.redis.hincrby(redis_key, "failures", 1)
            elif outcome == OUTCOME_POSITIVE:
                await self.redis.hincrby(redis_key, "successes", 1)
                # Bei Erfolg: failure streak unterbrechen
                await self.redis.hset(redis_key, "last_success", "1")

            # TTL setzen (30 Tage Fenster)
            await self.redis.expire(redis_key, self._AUTO_OPINION_WINDOW_DAYS * 86400)

            # Zaehler lesen
            raw_failures = await self.redis.hget(redis_key, "failures")
            raw_successes = await self.redis.hget(redis_key, "successes")
            failures = int(raw_failures or 0)
            successes = int(raw_successes or 0)

            # Cooldown: Meinung nur einmal pro Gerät bilden
            opinion_key = f"mha:auto_opinion:formed:{device_key}"
            already_formed = await self.redis.get(opinion_key)
            if already_formed:
                return

            personality = getattr(self, "_personality", None)
            if not personality:
                return

            # Negative Meinung bei vielen Fehlern
            if failures >= self._AUTO_OPINION_FAILURE_THRESHOLD:
                room_nice = room.replace("_", " ").capitalize() if room else ""
                device_nice = (
                    action_type.replace("set_", "").replace("_", " ").capitalize()
                )
                topic = f"{device_nice} {room_nice}".strip()
                opinion = (
                    f"Das {device_nice.lower()} "
                    f"{'im ' + room_nice if room_nice else ''} "
                    f"macht oefter Probleme — {failures} Fehler in letzter Zeit."
                ).strip()
                await personality.store_learned_opinion(topic, opinion)
                await self.redis.set(opinion_key, "negative", ex=30 * 86400)
                logger.info("Auto-Opinion (negativ): %s — %d Fehler", topic, failures)

            # Positive Meinung bei vielen Erfolgen ohne Fehler
            elif successes >= self._AUTO_OPINION_SUCCESS_THRESHOLD and failures == 0:
                room_nice = room.replace("_", " ").capitalize() if room else ""
                device_nice = (
                    action_type.replace("set_", "").replace("_", " ").capitalize()
                )
                topic = f"{device_nice} {room_nice}".strip()
                opinion = (
                    f"Das {device_nice.lower()} "
                    f"{'im ' + room_nice if room_nice else ''} "
                    f"funktioniert zuverlaessig."
                ).strip()
                await personality.store_learned_opinion(topic, opinion)
                await self.redis.set(opinion_key, "positive", ex=30 * 86400)
                logger.info("Auto-Opinion (positiv): %s — %d Erfolge", topic, successes)

        except Exception as e:
            logger.debug("Auto-Opinion Update fehlgeschlagen: %s", e)

    # ------------------------------------------------------------------
    # Learned Follow-ups: Trackt Aktions-Sequenzen fuer Think-Ahead
    # ------------------------------------------------------------------

    # Defaults — werden von __init__ aus Config ueberschrieben
    _FOLLOWUP_WINDOW_SECONDS = 120
    _FOLLOWUP_MIN_COUNT = 3
    _FOLLOWUP_TTL = 90 * 86400

    async def track_followup_sequence(self, action_type: str, room: str = ""):
        """Trackt Aktions-Sequenzen: Wenn nach Aktion A regelmaessig B folgt, lernen.

        Wird bei jeder Tool-Execution aufgerufen. Prueft ob kurz vorher
        eine andere Aktion im selben Raum ausgefuehrt wurde und zaehlt das Paar.

        Args:
            action_type: Die gerade ausgefuehrte Aktion (z.B. "set_cover").
            room: Der Raum (fuer raumspezifische Sequenzen).
        """
        if not self.redis or not self.enabled:
            return

        try:
            # Vorherige Aktion und Zeitpunkt aus Redis holen
            prev_key = f"mha:followup:last_action:{room}" if room else "mha:followup:last_action:global"
            prev_raw = await self.redis.get(prev_key)
            if prev_raw:
                prev_data = json.loads(
                    prev_raw.decode() if isinstance(prev_raw, bytes) else prev_raw
                )
                prev_action = prev_data.get("action", "")
                prev_ts = prev_data.get("ts", 0)

                # Nur zaehlen wenn anderer Aktionstyp und innerhalb des Zeitfensters
                if (
                    prev_action
                    and prev_action != action_type
                    and (time.time() - prev_ts) <= self._followup_window
                ):
                    pair_key = f"mha:followup:pair:{prev_action}:{action_type}"
                    if room:
                        pair_key = f"{pair_key}:{room}"
                    await self.redis.incr(pair_key)
                    await self.redis.expire(pair_key, self._followup_ttl)

            # Aktuelle Aktion als "letzte" speichern
            await self.redis.setex(
                prev_key,
                self._followup_window + 10,
                json.dumps({"action": action_type, "ts": time.time()}),
            )
        except Exception as e:
            logger.debug("Follow-up Sequenz-Tracking fehlgeschlagen: %s", e)

    async def get_learned_followups(self, action_type: str, room: str = "") -> list[dict]:
        """Gibt gelernte Follow-up-Aktionen fuer eine ausgefuehrte Aktion zurueck.

        Returns:
            Liste von {"action": "set_cover", "count": 7, "room": "schlafzimmer"} Dicts,
            sortiert nach Haeufigkeit. Nur Paare mit >= _FOLLOWUP_MIN_COUNT.
        """
        if not self.redis or not self.enabled:
            return []

        followups = []
        try:
            # Raumspezifische und globale Patterns scannen
            patterns = [f"mha:followup:pair:{action_type}:*"]
            for pattern in patterns:
                cursor = 0
                while True:
                    cursor, keys = await self.redis.scan(
                        cursor, match=pattern, count=50
                    )
                    for key in keys:
                        key_str = key.decode() if isinstance(key, bytes) else key
                        parts = key_str.split(":")
                        # Format: mha:followup:pair:{prev}:{next} oder ..:{next}:{room}
                        if len(parts) < 5:
                            continue
                        follow_action = parts[4]
                        follow_room = parts[5] if len(parts) > 5 else ""
                        val = await self.redis.get(key)
                        count = int(val.decode() if isinstance(val, bytes) else val) if val else 0
                        if count >= self._followup_min:
                            followups.append({
                                "action": follow_action,
                                "count": count,
                                "room": follow_room,
                            })
                    if cursor == 0:
                        break
        except Exception as e:
            logger.debug("Learned Follow-ups laden fehlgeschlagen: %s", e)

        followups.sort(key=lambda x: x["count"], reverse=True)
        return followups[:5]  # Max 5 Follow-ups

    def set_personality(self, personality) -> None:
        """Setzt die PersonalityEngine-Referenz fuer Auto-Opinion-Learning."""
        self._personality = personality


def _extract_state_key(state) -> dict:
    """Extrahiert relevante State-Daten aus HA Entity State."""
    if not state:
        return {}
    if isinstance(state, dict):
        return {
            "state": state.get("state", ""),
            "attributes": {
                k: v
                for k, v in state.get("attributes", {}).items()
                if k
                not in (
                    "friendly_name",
                    "icon",
                    "supported_features",
                    "entity_picture",
                    "device_class",
                )
            },
        }
    # State-Objekt mit .state und .attributes
    try:
        return {
            "state": str(getattr(state, "state", "")),
            "attributes": dict(getattr(state, "attributes", {})),
        }
    except Exception as e:
        logger.debug("State object conversion failed: %s", e)
        return {}
