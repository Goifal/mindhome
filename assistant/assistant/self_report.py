"""
Self Report - Woechentlicher Selbst-Bericht ueber alle Lernsysteme.

Aggregiert Daten aus Outcome Tracker, Correction Memory, Feedback Tracker,
Anticipation, Insight Engine, Learning Observer, Response Quality, Error Patterns.
Generiert via LLM einen natuerlichsprachlichen Bericht.

Sicherheit: Rein lesend + aggregierend. Keine Schreibzugriffe. User sieht alles.
"""

import json
import logging
from datetime import datetime
from typing import Optional

from .config import yaml_config

logger = logging.getLogger(__name__)


class SelfReport:
    """Generiert woechentliche Selbst-Berichte ueber Jarvis' Lernfortschritt."""

    def __init__(self):
        self.redis = None
        self.ollama = None
        self.enabled = False
        self._cfg = yaml_config.get("self_report", {})
        self._model = self._cfg.get("model", "qwen3:14b")
        self._last_report_day: str = ""

    async def initialize(self, redis_client, ollama_client):
        """Initialisiert mit Redis und Ollama."""
        self.redis = redis_client
        self.ollama = ollama_client
        self.enabled = self._cfg.get("enabled", True) and self.redis is not None
        logger.info("SelfReport initialisiert (enabled=%s)", self.enabled)

    async def generate_report(self, outcome_tracker=None, correction_memory=None,
                              feedback_tracker=None, anticipation=None,
                              insight_engine=None, learning_observer=None,
                              response_quality=None, error_patterns=None,
                              self_optimization=None) -> dict:
        """Sammelt Daten aus allen Subsystemen und generiert einen Bericht."""
        if not self.enabled or not self.redis:
            return {"error": "SelfReport nicht aktiv"}

        # Rate Limit: Max 1 Report pro Tag
        today = datetime.now().strftime("%Y-%m-%d")
        if self._last_report_day == today:
            cached = await self.get_latest_report()
            if cached:
                return cached

        # Daten sammeln
        data = {}

        if outcome_tracker:
            try:
                data["outcomes"] = await outcome_tracker.get_stats()
                data["outcome_trends"] = await outcome_tracker.get_weekly_trends()
            except Exception as e:
                logger.debug("SelfReport: Outcome-Daten Fehler: %s", e)

        if correction_memory:
            try:
                data["corrections"] = await correction_memory.get_stats()
                data["correction_patterns"] = await correction_memory.get_correction_patterns()
            except Exception as e:
                logger.debug("SelfReport: Korrektur-Daten Fehler: %s", e)

        if feedback_tracker:
            try:
                data["feedback"] = await feedback_tracker.get_all_scores()
            except Exception as e:
                logger.debug("SelfReport: Feedback-Daten Fehler: %s", e)

        if learning_observer:
            try:
                data["learning"] = await learning_observer.get_learning_report()
            except Exception as e:
                logger.debug("SelfReport: Learning-Daten Fehler: %s", e)

        if response_quality:
            try:
                data["response_quality"] = await response_quality.get_stats()
            except Exception as e:
                logger.debug("SelfReport: Quality-Daten Fehler: %s", e)

        if error_patterns:
            try:
                data["errors"] = await error_patterns.get_stats()
            except Exception as e:
                logger.debug("SelfReport: Error-Daten Fehler: %s", e)

        if self_optimization:
            try:
                opt_summary = await self_optimization.generate_weekly_summary(
                    correction_memory=correction_memory,
                )
                if opt_summary:
                    data["self_optimization"] = opt_summary
            except Exception as e:
                logger.debug("SelfReport: Self-Optimization Fehler: %s", e)

        # LLM-Summary generieren
        summary = await self._generate_summary(data)
        if not summary:
            summary = self._format_fallback(data)

        report = {
            "generated_at": datetime.now().isoformat(),
            "summary": summary,
            "data": data,
        }

        # In Redis speichern
        report_json = json.dumps(report, ensure_ascii=False, default=str)
        await self.redis.setex("mha:self_report:latest", 14 * 86400, report_json)
        await self.redis.lpush("mha:self_report:history", report_json)
        await self.redis.ltrim("mha:self_report:history", 0, 11)
        await self.redis.expire("mha:self_report:history", 365 * 86400)

        self._last_report_day = today
        logger.info("Self-Report generiert (%d Zeichen)", len(summary))

        return report

    async def get_latest_report(self) -> Optional[dict]:
        """Cached Report fuer Chat/Dashboard."""
        if not self.redis:
            return None
        raw = await self.redis.get("mha:self_report:latest")
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
        return None

    # --- Private Methoden ---

    async def _generate_summary(self, data: dict) -> str:
        """LLM generiert 5-8 Saetze im Jarvis-Tonfall."""
        if not self.ollama or not data:
            return ""

        # Daten-Zusammenfassung fuer Prompt
        data_text = []

        outcomes = data.get("outcomes", {})
        if outcomes:
            for action, stats in outcomes.items():
                score = stats.get("score", 0.5)
                total = stats.get("total", 0)
                data_text.append(f"- {action}: Score {score:.2f} ({total} Aktionen)")

        corrections = data.get("corrections", {})
        if corrections:
            total_corr = corrections.get("total_corrections", 0)
            rules = corrections.get("active_rules", 0)
            data_text.append(f"- Korrekturen: {total_corr} gesamt, {rules} aktive Regeln")

        quality = data.get("response_quality", {})
        if quality:
            for cat, stats in quality.items():
                score = stats.get("score", 0.5)
                data_text.append(f"- Antwortqualitaet '{cat}': {score:.2f}")

        errors = data.get("errors", {})
        if errors:
            last_24h = errors.get("last_24h", 0)
            data_text.append(f"- Fehler letzte 24h: {last_24h}")

        feedback = data.get("feedback", {})
        if feedback:
            high_scores = {k: v for k, v in feedback.items() if isinstance(v, (int, float)) and v > 0.7}
            low_scores = {k: v for k, v in feedback.items() if isinstance(v, (int, float)) and v < 0.3}
            if high_scores:
                data_text.append(f"- Gut angenommene Meldungen: {', '.join(high_scores.keys())}")
            if low_scores:
                data_text.append(f"- Schlecht angenommene Meldungen: {', '.join(low_scores.keys())}")

        if not data_text:
            return ""

        prompt = f"""Du bist Jarvis, ein intelligenter Hausassistent.
Schreibe einen kurzen Selbstbericht (5-8 Saetze) ueber deinen Lernfortschritt diese Woche.
Sei ehrlich, trocken-humorvoll und konkret. Erwaehne Zahlen.

DATEN:
{chr(10).join(data_text)}

Schreibe den Bericht in der Ich-Form. Nicht zu formell, aber respektvoll."""

        try:
            response = await self.ollama.generate(
                model=self._model,
                prompt=prompt,
                temperature=0.6,
                max_tokens=300,
            )
            text = response.strip()
            if text and len(text) > 20:
                return text
        except Exception as e:
            logger.debug("SelfReport LLM-Summary Fehler: %s", e)

        return ""

    def _format_fallback(self, data: dict) -> str:
        """Fallback-Formatierung ohne LLM."""
        lines = ["Woechentlicher Lern-Bericht:", ""]

        outcomes = data.get("outcomes", {})
        if outcomes:
            lines.append("Aktions-Ergebnisse:")
            for action, stats in outcomes.items():
                score = stats.get("score", 0.5)
                total = stats.get("total", 0)
                lines.append(f"  {action}: {score:.0%} Erfolg ({total} Aktionen)")

        corrections = data.get("corrections", {})
        if corrections:
            total = corrections.get("total_corrections", 0)
            rules = corrections.get("active_rules", 0)
            lines.append(f"\nKorrekturen: {total} gesamt, {rules} Regeln gelernt")

        quality = data.get("response_quality", {})
        if quality:
            lines.append("\nAntwort-Qualitaet:")
            for cat, stats in quality.items():
                score = stats.get("score", 0.5)
                lines.append(f"  {cat}: {score:.0%}")

        errors = data.get("errors", {})
        if errors:
            lines.append(f"\nFehler: {errors.get('last_24h', 0)} in den letzten 24h")

        if len(lines) <= 2:
            return "Noch nicht genug Daten fuer einen aussagekraeftigen Bericht."

        return "\n".join(lines)
