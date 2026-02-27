"""
Adaptive Thresholds - Lernende Schwellwerte.

Analysiert Outcome-Daten + Feedback-Scores und passt Schwellwerte an.
Zwei Stufen: Auto-Adjust (enge Grenzen, ohne Genehmigung) und
Proposal-Based (weiter, mit Genehmigung ueber Self-Optimization).

Sicherheit:
- Auto-Adjust aendert NUR Laufzeit yaml_config dict, NICHT die Datei.
- Reset bei Restart. Bounds hardcoded (nicht aus Config lesbar).
- Alle Anpassungen geloggt mit Audit-Trail.
"""

import json
import logging
import time
from datetime import datetime
from typing import Optional

from .config import yaml_config

logger = logging.getLogger(__name__)

# Hardcoded Auto-Adjust Grenzen (eng, ohne Genehmigung)
_AUTO_BOUNDS = {
    "insights.cooldown_hours": {
        "path": ["insights", "cooldown_hours"],
        "min": 2, "max": 8, "default": 4, "step": 1,
    },
    "anticipation.min_confidence": {
        "path": ["anticipation", "min_confidence"],
        "min": 0.5, "max": 0.8, "default": 0.6, "step": 0.05,
    },
    "feedback.base_cooldown_seconds": {
        "path": ["feedback", "base_cooldown_seconds"],
        "min": 120, "max": 600, "default": 300, "step": 60,
    },
}

# Min Datenmenge bevor Schwellwerte geaendert werden
MIN_OUTCOMES_FOR_ADJUST = 50
MIN_WEEKS_FOR_ADJUST = 4

# Max Auto-Adjustments pro Woche
MAX_ADJUSTMENTS_PER_WEEK = 3


class AdaptiveThresholds:
    """Analysiert Lern-Daten und passt Schwellwerte an."""

    def __init__(self):
        self.redis = None
        self.enabled = False
        self._cfg = yaml_config.get("adaptive_thresholds", {})
        self._adjustments_this_week = 0
        self._last_adjustment_week: str = ""

    async def initialize(self, redis_client):
        """Initialisiert mit Redis Client."""
        self.redis = redis_client
        self.enabled = self._cfg.get("enabled", False) and self.redis is not None
        auto_adjust = self._cfg.get("auto_adjust", True)
        if not auto_adjust:
            self.enabled = False
        logger.info("AdaptiveThresholds initialisiert (enabled=%s)", self.enabled)

    async def run_analysis(self, outcome_tracker=None, correction_memory=None,
                           feedback_tracker=None) -> dict:
        """Analyse + automatische Anpassung innerhalb enger Grenzen."""
        if not self.enabled or not self.redis:
            return {"adjusted": [], "skipped": []}

        # Rate Limit
        current_week = datetime.now().strftime("%Y-W%W")
        if self._last_adjustment_week != current_week:
            self._adjustments_this_week = 0
            self._last_adjustment_week = current_week

        if self._adjustments_this_week >= MAX_ADJUSTMENTS_PER_WEEK:
            return {"adjusted": [], "skipped": ["rate_limit_reached"]}

        # Daten-Menge pruefen
        if not await self._has_sufficient_data(outcome_tracker):
            return {"adjusted": [], "skipped": ["insufficient_data"]}

        adjusted = []
        skipped = []

        for param_name, bounds in _AUTO_BOUNDS.items():
            try:
                result = await self._analyze_parameter(
                    param_name, bounds, outcome_tracker, feedback_tracker
                )
                if result:
                    if result.get("adjusted"):
                        adjusted.append(result)
                        self._adjustments_this_week += 1
                    else:
                        skipped.append(result.get("reason", "no_change"))
            except Exception as e:
                logger.debug("AdaptiveThresholds Fehler bei %s: %s", param_name, e)
                skipped.append(f"{param_name}: {e}")

            if self._adjustments_this_week >= MAX_ADJUSTMENTS_PER_WEEK:
                break

        # Ergebnisse loggen
        if adjusted:
            await self._log_adjustments(adjusted)

        return {"adjusted": adjusted, "skipped": skipped}

    async def get_adjustment_history(self) -> list[dict]:
        """Gibt Anpassungs-Historie zurueck."""
        if not self.redis:
            return []

        raw = await self.redis.lrange("mha:adaptive:history", 0, 49)
        history = []
        for item in raw:
            try:
                history.append(json.loads(item))
            except json.JSONDecodeError:
                continue
        return history

    # --- Private Methoden ---

    async def _has_sufficient_data(self, outcome_tracker) -> bool:
        """Prueft ob genuegend Daten fuer Analyse vorhanden sind."""
        if not outcome_tracker or not self.redis:
            return False

        stats = await outcome_tracker.get_stats()
        total_outcomes = sum(
            s.get("total", 0) for s in stats.values()
            if isinstance(s, dict)
        )

        return total_outcomes >= MIN_OUTCOMES_FOR_ADJUST

    async def _analyze_parameter(self, param_name: str, bounds: dict,
                                 outcome_tracker, feedback_tracker) -> Optional[dict]:
        """Analysiert einen Parameter und entscheidet ob Anpassung noetig."""
        # Aktuellen Wert lesen
        current = self._get_runtime_value(bounds["path"])
        if current is None:
            current = bounds["default"]

        # Pruefen ob Self-Optimization einen Vorschlag fuer diesen Parameter hat
        if self.redis:
            pending = await self.redis.get(f"mha:self_opt:pending_param:{param_name}")
            if pending:
                return {"adjusted": False, "reason": f"self_opt_pending:{param_name}"}

        # Daten-basierte Entscheidung
        direction = await self._determine_direction(param_name, outcome_tracker, feedback_tracker)

        if direction == 0:
            return None  # Keine Aenderung noetig

        step = bounds["step"]
        new_value = current + (step * direction)

        # Bounds pruefen
        new_value = max(bounds["min"], min(bounds["max"], new_value))

        if new_value == current:
            return {"adjusted": False, "reason": "at_bound"}

        # Anomalie-Check: Wenn > 80% negative Outcomes, NICHT auto-adjusten
        if outcome_tracker:
            stats = await outcome_tracker.get_stats()
            for action_stats in stats.values():
                if isinstance(action_stats, dict):
                    total = action_stats.get("total", 0)
                    negative = action_stats.get("negative", 0)
                    if total > 20 and negative / total > 0.8:
                        logger.warning("ANOMALIE: >80%% negative Outcomes — skip auto-adjust")
                        return {"adjusted": False, "reason": "anomaly_detected"}

        # Auto-Apply (nur Laufzeit, nicht persistent!)
        self._set_runtime_value(bounds["path"], new_value)

        reason = f"Score-basiert: {'erhoehen' if direction > 0 else 'senken'}"
        logger.info("Auto-Adjust: %s %.2f -> %.2f (%s)", param_name, current, new_value, reason)

        return {
            "adjusted": True,
            "parameter": param_name,
            "old_value": current,
            "new_value": new_value,
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
        }

    async def _determine_direction(self, param_name: str,
                                   outcome_tracker, feedback_tracker) -> int:
        """Bestimmt Anpassungs-Richtung: +1 (erhoehen), -1 (senken), 0 (keine Aenderung)."""
        # Insights Cooldown: Score niedrig = Cooldown erhoehen (weniger Insights)
        if param_name == "insights.cooldown_hours":
            if feedback_tracker:
                insight_score = await feedback_tracker.get_score("insight")
                if insight_score < 0.3:
                    return 1  # Cooldown erhoehen (weniger Insights)
                elif insight_score > 0.7:
                    return -1  # Cooldown senken (mehr Insights)

        # Anticipation Confidence: Viele falsche Vorhersagen = Confidence erhoehen
        elif param_name == "anticipation.min_confidence":
            if outcome_tracker:
                score = await outcome_tracker.get_success_score("anticipation")
                if score < 0.3:
                    return 1  # Confidence erhoehen (weniger, aber bessere Vorhersagen)
                elif score > 0.7:
                    return -1  # Confidence senken (mehr Vorhersagen)

        # Feedback Cooldown: Viele ignored = Cooldown erhoehen
        elif param_name == "feedback.base_cooldown_seconds":
            if feedback_tracker:
                scores = await feedback_tracker.get_all_scores()
                avg_score = sum(
                    v for v in scores.values() if isinstance(v, (int, float))
                ) / max(1, len(scores)) if scores else 0.5
                if avg_score < 0.3:
                    return 1  # Cooldown erhoehen (weniger Meldungen)
                elif avg_score > 0.7:
                    return -1  # Cooldown senken (mehr Meldungen ok)

        return 0

    def _get_runtime_value(self, path: list[str]):
        """Liest Wert aus Laufzeit-Config."""
        cfg = yaml_config
        for key in path:
            if isinstance(cfg, dict):
                cfg = cfg.get(key)
            else:
                return None
        return cfg

    def _set_runtime_value(self, path: list[str], value):
        """Schreibt Wert in Laufzeit-Config (NICHT in Datei!)."""
        cfg = yaml_config
        for key in path[:-1]:
            if isinstance(cfg, dict):
                if key not in cfg:
                    cfg[key] = {}
                cfg = cfg[key]
            else:
                return
        if isinstance(cfg, dict):
            cfg[path[-1]] = value

    async def _log_adjustments(self, adjusted: list[dict]):
        """Speichert Anpassungen in Redis Audit-Trail."""
        if not self.redis:
            return

        for adj in adjusted:
            entry = json.dumps(adj, ensure_ascii=False)
            await self.redis.lpush("mha:adaptive:history", entry)

        await self.redis.ltrim("mha:adaptive:history", 0, 99)
        await self.redis.expire("mha:adaptive:history", 180 * 86400)
