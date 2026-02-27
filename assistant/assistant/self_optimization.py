"""
Self Optimization - Jarvis analysiert Interaktionen und schlaegt Anpassungen vor.

Phase 13.4: Kontrollierte Prompt-Selbstoptimierung.
- Woechentliche/taegliche Analyse der Interaktions-Qualitaet
- Vorschlaege fuer Personality-Parameter (sarcasm_level, max_sentences, etc.)
- NIEMALS Auto-Apply: User muss bestaetigen (approval_mode: manual)
- Parameter-Grenzen verhindern extreme Werte
- Immutable Keys schuetzen Kern-Identitaet
- Snapshot vor jeder Aenderung via ConfigVersioning
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from .config import settings, yaml_config
from .config_versioning import ConfigVersioning
from .ollama_client import OllamaClient

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).parent.parent / "config"
_SETTINGS_PATH = _CONFIG_DIR / "settings.yaml"

# Mapping: Parameter-Name -> YAML-Pfad in settings.yaml
_PARAMETER_PATHS = {
    "sarcasm_level": ["personality", "sarcasm_level"],
    "opinion_intensity": ["personality", "opinion_intensity"],
    "max_response_sentences": ["response_filter", "max_response_sentences"],
    "formality_min": ["personality", "formality_min"],
    "formality_start": ["personality", "formality_start"],
    # Feature 9d: Erweiterte optimierbare Parameter
    "insight_cooldown_hours": ["insights", "cooldown_hours"],
    "anticipation_min_confidence": ["anticipation", "min_confidence"],
    "feedback_base_cooldown": ["feedback", "base_cooldown_seconds"],
    "spontaneous_max_per_day": ["spontaneous", "max_per_day"],
}


class SelfOptimization:
    """Analysiert Interaktionen und generiert Parameter-Vorschlaege."""

    def __init__(self, ollama: OllamaClient, config_versioning: ConfigVersioning):
        self.ollama = ollama
        self.versioning = config_versioning

        self._cfg = yaml_config.get("self_optimization", {})
        self._enabled = self._cfg.get("enabled", False)
        self._approval_mode = self._cfg.get("approval_mode", "manual")
        self._interval = self._cfg.get("analysis_interval", "weekly")
        self._max_proposals = self._cfg.get("max_proposals_per_cycle", 3)
        self._model = self._cfg.get("model", "qwen3:14b")
        self._bounds = self._cfg.get("parameter_bounds", {})
        # SICHERHEIT: Mindestmenge an immutable Keys, die NICHT per Config ueberschrieben werden kann
        _HARDCODED_IMMUTABLE = {"trust_levels", "security", "autonomy", "dashboard", "models"}
        self._immutable = _HARDCODED_IMMUTABLE | set(self._cfg.get("immutable_keys", []))

        self._redis = None
        self._pending_proposals: list[dict] = []

    async def initialize(self, redis_client):
        """Initialisiert mit Redis-Client."""
        self._redis = redis_client
        logger.info(
            "SelfOptimization initialisiert (enabled=%s, mode=%s, interval=%s)",
            self._enabled, self._approval_mode, self._interval,
        )

    def is_enabled(self) -> bool:
        return self._enabled and self._approval_mode != "off"

    async def run_analysis(self, outcome_tracker=None, response_quality=None,
                           correction_memory=None) -> list[dict]:
        """Fuehrt eine Analyse der letzten Interaktionen durch.

        Args:
            outcome_tracker: OutcomeTracker-Instanz (Feature 9a)
            response_quality: ResponseQualityTracker-Instanz (Feature 9a)
            correction_memory: CorrectionMemory-Instanz (Feature 9a)

        Returns: Liste von Vorschlaegen [{parameter, current, proposed, reason, confidence}]
        """
        if not self.is_enabled() or not self._redis:
            return []

        last_run = await self._redis.get("mha:self_opt:last_run")
        if last_run:
            from datetime import timedelta
            last_dt = datetime.fromisoformat(last_run)
            delta = timedelta(days=7) if self._interval == "weekly" else timedelta(days=1)
            if datetime.now() - last_dt < delta:
                logger.debug("Analyse noch nicht faellig (letzte: %s)", last_run)
                return []

        corrections = await self._get_recent_corrections()
        feedback_stats = await self._get_feedback_stats()

        # Feature 9a: Mehr Datenquellen
        outcome_stats = await self._get_outcome_stats(outcome_tracker)
        quality_stats = await self._get_quality_stats(response_quality)
        correction_patterns = await self._get_correction_patterns(correction_memory)

        if not corrections and not feedback_stats and not outcome_stats:
            logger.info("Keine Daten fuer Analyse vorhanden")
            return []

        proposals = await self._generate_proposals(
            corrections, feedback_stats,
            outcome_stats=outcome_stats, quality_stats=quality_stats,
            correction_patterns=correction_patterns,
        )

        valid_proposals = []
        for p in proposals[:self._max_proposals]:
            if self._validate_proposal(p):
                valid_proposals.append(p)

        self._pending_proposals = valid_proposals

        if valid_proposals:
            await self._redis.set(
                "mha:self_opt:pending",
                json.dumps(valid_proposals),
                ex=7 * 86400,
            )

        ttl = 8 * 86400 if self._interval == "weekly" else 2 * 86400
        await self._redis.setex("mha:self_opt:last_run", ttl, datetime.now().isoformat())

        logger.info("Analyse abgeschlossen: %d Vorschlaege generiert", len(valid_proposals))
        return valid_proposals

    async def get_pending_proposals(self) -> list[dict]:
        """Gibt aktuelle Vorschlaege zurueck (fuer Dashboard/Chat)."""
        if not self.is_enabled():
            return []

        if self._pending_proposals:
            return self._pending_proposals

        if self._redis:
            raw = await self._redis.get("mha:self_opt:pending")
            if raw:
                self._pending_proposals = json.loads(raw)
        return self._pending_proposals

    async def approve_proposal(self, index: int) -> dict:
        """User genehmigt einen Vorschlag. Wendet die Aenderung an.

        Returns: {"success": bool, "message": str}
        """
        if not self.is_enabled():
            return {"success": False, "message": "Selbstoptimierung ist deaktiviert"}

        proposals = await self.get_pending_proposals()
        if index < 0 or index >= len(proposals):
            return {"success": False, "message": f"Vorschlag #{index} existiert nicht"}

        proposal = proposals[index]
        param = proposal["parameter"]
        new_value = proposal["proposed"]

        if not self._validate_proposal(proposal):
            return {"success": False, "message": "Vorschlag verletzt Parameter-Grenzen"}

        snapshot_id = await self.versioning.create_snapshot(
            "settings", _SETTINGS_PATH,
            reason=f"self_opt:{param}={new_value}",
            changed_by="self_optimization",
        )

        result = await self._apply_parameter(param, new_value)

        if result["success"]:
            proposals.pop(index)
            self._pending_proposals = proposals
            if self._redis:
                if proposals:
                    await self._redis.set(
                        "mha:self_opt:pending",
                        json.dumps(proposals),
                        ex=7 * 86400,
                    )
                else:
                    await self._redis.delete("mha:self_opt:pending")

                await self._redis.lpush(
                    "mha:self_opt:history",
                    json.dumps({
                        **proposal,
                        "applied_at": datetime.now().isoformat(),
                        "snapshot_id": snapshot_id,
                    }),
                )
                await self._redis.ltrim("mha:self_opt:history", 0, 49)
                await self._redis.expire("mha:self_opt:history", 90 * 86400)

        return result

    async def reject_proposal(self, index: int) -> dict:
        """User lehnt einen Vorschlag ab."""
        if not self.is_enabled():
            return {"success": False, "message": "Selbstoptimierung ist deaktiviert"}

        proposals = await self.get_pending_proposals()
        if index < 0 or index >= len(proposals):
            return {"success": False, "message": f"Vorschlag #{index} existiert nicht"}

        rejected = proposals.pop(index)
        self._pending_proposals = proposals

        if self._redis:
            if proposals:
                await self._redis.set(
                    "mha:self_opt:pending", json.dumps(proposals), ex=7 * 86400,
                )
            else:
                await self._redis.delete("mha:self_opt:pending")

            await self._redis.lpush(
                "mha:self_opt:rejected",
                json.dumps({**rejected, "rejected_at": datetime.now().isoformat()}),
            )
            await self._redis.ltrim("mha:self_opt:rejected", 0, 29)
            await self._redis.expire("mha:self_opt:rejected", 90 * 86400)

        return {"success": True, "message": f"Vorschlag '{rejected['parameter']}' abgelehnt"}

    async def reject_all(self) -> dict:
        """User lehnt alle Vorschlaege ab."""
        if not self.is_enabled():
            return {"success": False, "message": "Selbstoptimierung ist deaktiviert"}
        proposals = await self.get_pending_proposals()
        count = len(proposals)
        self._pending_proposals = []
        if self._redis:
            await self._redis.delete("mha:self_opt:pending")
        return {"success": True, "message": f"{count} Vorschlaege abgelehnt"}

    def _validate_proposal(self, proposal: dict) -> bool:
        """Prueft ob ein Vorschlag gueltig ist. SICHERHEITSKRITISCH.

        Pruefungen (alle muessen bestehen):
        1. Parameter muss in _PARAMETER_PATHS Whitelist sein
        2. Parameter darf nicht in immutable_keys sein
        3. Wert muss numerisch sein (alle erlaubten Parameter sind numerisch)
        4. Wert muss innerhalb der Bounds liegen
        """
        param = proposal.get("parameter", "")

        # 1. WHITELIST: Nur bekannte Parameter erlauben
        if param not in _PARAMETER_PATHS:
            logger.warning("SICHERHEIT: Vorschlag fuer unbekannten Parameter abgelehnt: %s", param)
            return False

        # 2. IMMUTABLE: Geschuetzte Bereiche
        for immutable_key in self._immutable:
            if param.startswith(immutable_key) or immutable_key.startswith(param):
                logger.warning("SICHERHEIT: Vorschlag fuer immutable Key abgelehnt: %s", param)
                return False

        # 3. TYP: Nur numerische Werte erlauben (alle Parameter sind numerisch)
        value = proposal.get("proposed")
        if not isinstance(value, (int, float)):
            logger.warning("SICHERHEIT: Nicht-numerischer Wert abgelehnt: %s=%s (type=%s)", param, value, type(value).__name__)
            return False

        # 4. BOUNDS: Grenzen pruefen
        bounds = self._bounds.get(param)
        if bounds:
            if value < bounds.get("min", float("-inf")):
                logger.warning("Vorschlag unter Minimum: %s=%s (min=%s)", param, value, bounds["min"])
                return False
            if value > bounds.get("max", float("inf")):
                logger.warning("Vorschlag ueber Maximum: %s=%s (max=%s)", param, value, bounds["max"])
                return False

        return True

    async def _generate_proposals(self, corrections: list, feedback_stats: dict,
                                   outcome_stats: dict = None, quality_stats: dict = None,
                                   correction_patterns: list = None) -> list[dict]:
        """Generiert Vorschlaege via LLM-Analyse."""
        current_values = self._get_current_values()

        # Feature 9e: Trend-Metriken im Prompt
        extra_data = ""
        if outcome_stats:
            extra_data += f"\nOUTCOME-STATISTIKEN:\n{json.dumps(outcome_stats, indent=2, ensure_ascii=False)}\n"
        if quality_stats:
            extra_data += f"\nANTWORT-QUALITAET:\n{json.dumps(quality_stats, indent=2, ensure_ascii=False)}\n"
        if correction_patterns:
            extra_data += f"\nKORREKTUR-MUSTER (Top 5):\n{json.dumps(correction_patterns[:5], indent=2, ensure_ascii=False)}\n"

        prompt = f"""Du bist Jarvis' Selbstoptimierungs-Modul.
Analysiere die folgenden Interaktionsdaten und schlage Parameter-Aenderungen vor.

AKTUELLE WERTE:
{json.dumps(current_values, indent=2, ensure_ascii=False)}

PARAMETER-GRENZEN:
{json.dumps(self._bounds, indent=2, ensure_ascii=False)}

KORREKTUREN VOM USER (letzte Woche):
{json.dumps(corrections[:10], indent=2, ensure_ascii=False)}

FEEDBACK-STATISTIK:
{json.dumps(feedback_stats, indent=2, ensure_ascii=False)}
{extra_data}
REGELN:
- Nur Parameter aendern die EINDEUTIG verbesserbar sind
- Kleine Schritte: max 1 Stufe pro Parameter pro Woche
- Bei wenig Daten: KEINE Vorschlaege machen
- Jeder Vorschlag braucht eine klare Begruendung

Antworte NUR mit einem JSON-Array (keine Erklaerung):
[{{"parameter": "...", "current": ..., "proposed": ..., "reason": "...", "confidence": 0.0-1.0}}]

Wenn keine Aenderung noetig: []"""

        try:
            response = await self.ollama.generate(
                model=self._model,
                prompt=prompt,
                temperature=0.3,
                max_tokens=512,
            )

            text = response.strip()
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                proposals = json.loads(text[start:end])
                return [p for p in proposals if isinstance(p, dict) and "parameter" in p]

        except Exception as e:
            logger.error("Proposal-Generierung fehlgeschlagen: %s", e)

        return []

    def _get_current_values(self) -> dict:
        """Liest aktuelle Parameter-Werte aus settings.yaml."""
        values = {}
        for param, path in _PARAMETER_PATHS.items():
            cfg = yaml_config
            for key in path:
                cfg = cfg.get(key, {}) if isinstance(cfg, dict) else {}
            if cfg != {}:
                values[param] = cfg
        return values

    async def _apply_parameter(self, param: str, new_value) -> dict:
        """Schreibt einen Parameter in settings.yaml."""
        path = _PARAMETER_PATHS.get(param)
        if not path:
            return {"success": False, "message": f"Unbekannter Parameter: {param}"}

        try:
            with open(_SETTINGS_PATH) as f:
                config = yaml.safe_load(f) or {}

            node = config
            for key in path[:-1]:
                if key not in node:
                    node[key] = {}
                node = node[key]
            node[path[-1]] = new_value

            with open(_SETTINGS_PATH, "w") as f:
                yaml.safe_dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

            logger.info("Parameter angepasst: %s = %s", param, new_value)
            return {
                "success": True,
                "message": f"{param}: {self._get_current_values().get(param)} -> {new_value}",
            }

        except Exception as e:
            logger.error("Parameter-Aenderung fehlgeschlagen: %s", e)
            return {"success": False, "message": f"Fehler: {e}"}

    async def _get_recent_corrections(self) -> list:
        """Holt User-Korrekturen aus Redis (letzte 7 Tage)."""
        if not self._redis:
            return []
        raw = await self._redis.lrange("mha:corrections", 0, 49)
        corrections = []
        for item in raw:
            try:
                corrections.append(json.loads(item))
            except json.JSONDecodeError:
                continue
        return corrections

    async def _get_feedback_stats(self) -> dict:
        """Holt Feedback-Statistiken aus Redis."""
        if not self._redis:
            return {}
        try:
            stats = {}
            for key_suffix in ["positive", "negative", "ignored", "corrections"]:
                val = await self._redis.get(f"mha:feedback:count:{key_suffix}")
                stats[key_suffix] = int(val) if val else 0
            return stats
        except Exception:
            return {}

    # Feature 9a: Neue Datenquellen
    async def _get_outcome_stats(self, outcome_tracker=None) -> dict:
        """Holt Outcome-Statistiken (Feature 9a)."""
        if not outcome_tracker:
            return {}
        try:
            return await outcome_tracker.get_stats()
        except Exception:
            return {}

    async def _get_quality_stats(self, response_quality=None) -> dict:
        """Holt Response-Quality-Statistiken (Feature 9a)."""
        if not response_quality:
            return {}
        try:
            return await response_quality.get_stats()
        except Exception:
            return {}

    async def _get_correction_patterns(self, correction_memory=None) -> list:
        """Holt Korrektur-Muster (Feature 9a)."""
        if not correction_memory:
            return []
        try:
            return await correction_memory.get_correction_patterns()
        except Exception:
            return []

    # Feature 9b: Effectiveness Tracking
    async def save_baseline(self, param: str, outcome_tracker=None, response_quality=None):
        """Speichert Baseline-Metriken vor einer Aenderung (Feature 9b)."""
        if not self._redis:
            return
        baseline = {"timestamp": datetime.now().isoformat()}
        if outcome_tracker:
            try:
                baseline["outcome_stats"] = await outcome_tracker.get_stats()
            except Exception:
                pass
        if response_quality:
            try:
                baseline["quality_stats"] = await response_quality.get_stats()
            except Exception:
                pass
        await self._redis.setex(
            f"mha:self_opt:baseline:{param}", 30 * 86400,
            json.dumps(baseline, ensure_ascii=False, default=str),
        )

    async def check_effectiveness(self, param: str, outcome_tracker=None,
                                  response_quality=None) -> Optional[dict]:
        """Vergleicht aktuelle Metriken mit Baseline (Feature 9b/9c)."""
        if not self._redis:
            return None
        raw = await self._redis.get(f"mha:self_opt:baseline:{param}")
        if not raw:
            return None
        try:
            baseline = json.loads(raw)
        except json.JSONDecodeError:
            return None

        current_outcomes = {}
        current_quality = {}
        if outcome_tracker:
            try:
                current_outcomes = await outcome_tracker.get_stats()
            except Exception:
                pass
        if response_quality:
            try:
                current_quality = await response_quality.get_stats()
            except Exception:
                pass

        # Einfacher Vergleich: Outcome-Score-Differenz
        baseline_outcomes = baseline.get("outcome_stats", {})
        score_changes = {}
        for action, stats in current_outcomes.items():
            if isinstance(stats, dict) and action in baseline_outcomes:
                old_score = baseline_outcomes[action].get("score", 0.5)
                new_score = stats.get("score", 0.5)
                if isinstance(old_score, (int, float)) and isinstance(new_score, (int, float)):
                    score_changes[action] = round(new_score - old_score, 3)

        return {
            "parameter": param,
            "score_changes": score_changes,
            "baseline_timestamp": baseline.get("timestamp", ""),
        }

    def format_proposals_for_chat(self, proposals: list[dict]) -> str:
        """Formatiert Vorschlaege fuer die Chat-Ausgabe."""
        if not proposals:
            return "Keine Optimierungsvorschlaege vorhanden."

        lines = ["Ich habe folgende Optimierungsvorschlaege:", ""]
        for i, p in enumerate(proposals):
            conf = int(p.get("confidence", 0) * 100)
            lines.append(
                f"  [{i+1}] {p['parameter']}: {p['current']} -> {p['proposed']} "
                f"({conf}% Confidence)"
            )
            lines.append(f"      Grund: {p['reason']}")
            lines.append("")

        lines.append("Sage 'Vorschlag 1 annehmen', 'alle ablehnen', oder 'Rollback'.")
        return "\n".join(lines)

    def health_status(self) -> dict:
        """Status fuer Diagnostik."""
        return {
            "enabled": self._enabled,
            "approval_mode": self._approval_mode,
            "interval": self._interval,
            "pending_proposals": len(self._pending_proposals),
            "max_proposals": self._max_proposals,
        }
