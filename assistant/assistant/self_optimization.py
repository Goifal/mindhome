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

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

import assistant.config as cfg_module
from .config import settings, yaml_config, load_yaml_config
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
        from .config import resolve_model

        self._model = resolve_model(self._cfg.get("model", ""), fallback_tier="deep")
        self._bounds = self._cfg.get("parameter_bounds", {})
        # SICHERHEIT: Mindestmenge an immutable Keys, die NICHT per Config ueberschrieben werden kann
        _HARDCODED_IMMUTABLE = {
            "trust_levels",
            "security",
            "autonomy",
            "dashboard",
            "models",
        }
        self._immutable = _HARDCODED_IMMUTABLE | set(
            self._cfg.get("immutable_keys", [])
        )

        self._redis = None
        self._pending_proposals: list[dict] = []
        self._proposals_lock = asyncio.Lock()
        self._notify_callback = None
        self._proactive_insights = self._cfg.get("proactive_insights", False)

    async def initialize(self, redis_client):
        """Initialisiert mit Redis-Client."""
        self._redis = redis_client
        logger.info(
            "SelfOptimization initialisiert (enabled=%s, mode=%s, interval=%s)",
            self._enabled,
            self._approval_mode,
            self._interval,
        )

    def set_notify_callback(self, callback):
        """Setzt Callback fuer proaktive Insights (wie spontaneous_observer Pattern)."""
        self._notify_callback = callback

    def is_enabled(self) -> bool:
        return self._enabled and self._approval_mode != "off"

    async def _generate_proactive_insight(self) -> Optional[str]:
        """Generiert proaktive Insights ueber Korrektur-Muster nach Domaene.

        Analysiert welche Bereiche (Licht, Klima, Medien) die meisten
        Korrekturen haben und teilt dies dem Benutzer mit.

        Returns:
            Insight-Text oder None
        """
        if not self._redis or not self._proactive_insights:
            return None

        try:
            # Domain-Corrections aus Redis laden
            corrections_raw = await self._redis.hgetall(
                "mha:self_opt:domain_corrections"
            )
            if not corrections_raw:
                return None

            domain_counts: dict[str, int] = {}
            total = 0
            for domain_bytes, count_bytes in corrections_raw.items():
                domain = (
                    domain_bytes.decode()
                    if isinstance(domain_bytes, bytes)
                    else domain_bytes
                )
                count = int(
                    count_bytes.decode()
                    if isinstance(count_bytes, bytes)
                    else count_bytes
                )
                domain_counts[domain] = count
                total += count

            if total < 5:  # Mindestens 5 Korrekturen noetig
                return None

            # Domain mit den meisten Korrekturen
            worst_domain = max(domain_counts, key=domain_counts.get)
            worst_count = domain_counts[worst_domain]
            worst_pct = round(worst_count / total * 100)

            if worst_pct < 30:  # Nur melden wenn > 30% in einer Domain
                return None

            _DOMAIN_DE = {
                "climate": "Klima",
                "light": "Licht",
                "media": "Medien",
                "cover": "Rolllaeden",
                "lock": "Schloesser",
                "security": "Sicherheit",
            }
            domain_name = _DOMAIN_DE.get(worst_domain, worst_domain.title())

            return (
                f"Mir ist aufgefallen, dass {worst_pct}% meiner Korrekturen "
                f"den Bereich '{domain_name}' betreffen ({worst_count} von {total}). "
                f"Ich passe meine Empfehlungen in diesem Bereich an."
            )

        except Exception as e:
            logger.debug("Proactive insight generation failed: %s", e)
            return None

    async def track_domain_correction(
        self, domain: str, failure_cause: str = ""
    ):
        """Trackt eine Korrektur fuer eine bestimmte Domaene.

        Wird von brain.py aufgerufen wenn der User eine Jarvis-Aktion korrigiert.

        Args:
            domain: Betroffene Domaene (climate, light, cover, etc.)
            failure_cause: Optionale Ursache (z.B. "window_open", "user_reverted").
        """
        if not self._redis or not domain:
            return
        try:
            await self._redis.hincrby("mha:self_opt:domain_corrections", domain, 1)
            await self._redis.expire("mha:self_opt:domain_corrections", 30 * 86400)

            # Ursachen-Korrelation tracken: domain + cause
            if failure_cause:
                for cause in failure_cause.split("|"):
                    cause = cause.strip()
                    if cause:
                        corr_key = f"mha:self_opt:cause_corr:{domain}:{cause}"
                        await self._redis.incr(corr_key)
                        await self._redis.expire(corr_key, 30 * 86400)
        except Exception as e:
            logger.debug("Domain correction tracking failed: %s", e)

    async def get_failure_correlations(self) -> list[dict]:
        """Analysiert welche Ursachen mit welchen Domains korrelieren.

        Ermoeglicht Root-Cause-Analyse: "80% der Klima-Korrekturen
        passieren wenn Fenster offen sind."

        Returns:
            Liste von {"domain": ..., "cause": ..., "count": ..., "insight": ...}
        """
        if not self._redis:
            return []

        correlations = []
        try:
            cursor = 0
            while True:
                cursor, keys = await self._redis.scan(
                    cursor, match="mha:self_opt:cause_corr:*", count=50
                )
                for key in keys:
                    key_str = key.decode() if isinstance(key, bytes) else key
                    parts = key_str.split(":")
                    if len(parts) < 5:
                        continue
                    domain = parts[3]
                    cause = parts[4]
                    val = await self._redis.get(key)
                    count = int(
                        val.decode() if isinstance(val, bytes) else val
                    ) if val else 0
                    if count >= 3:
                        _CAUSE_DE = {
                            "window_open": "offenes Fenster",
                            "user_reverted": "User-Korrektur",
                            "device_unavailable": "Geraet offline",
                            "parameters_adjusted": "Parameter-Anpassung",
                        }
                        cause_de = _CAUSE_DE.get(cause, cause)
                        correlations.append({
                            "domain": domain,
                            "cause": cause,
                            "count": count,
                            "insight": (
                                f"{count}x {domain}-Fehler durch {cause_de}"
                            ),
                        })
                if cursor == 0:
                    break
        except Exception as e:
            logger.debug("Failure correlations scan failed: %s", e)

        correlations.sort(key=lambda x: x["count"], reverse=True)
        return correlations[:10]

    async def run_analysis(
        self, outcome_tracker=None, response_quality=None, correction_memory=None
    ) -> list[dict]:
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

            if isinstance(last_run, bytes):
                last_run = last_run.decode()
            last_dt = datetime.fromisoformat(last_run)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            _INTERVAL_DAYS = {"weekly": 7, "3day": 3, "daily": 1}
            delta = timedelta(days=_INTERVAL_DAYS.get(self._interval, 7))
            if datetime.now(timezone.utc) - last_dt < delta:
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
            corrections,
            feedback_stats,
            outcome_stats=outcome_stats,
            quality_stats=quality_stats,
            correction_patterns=correction_patterns,
        )

        valid_proposals = []
        for p in proposals[: self._max_proposals]:
            if self._validate_proposal(p):
                valid_proposals.append(p)

        async with self._proposals_lock:
            self._pending_proposals = valid_proposals

        if valid_proposals:
            await self._redis.set(
                "mha:self_opt:pending",
                json.dumps(valid_proposals),
                ex=7 * 86400,
            )

        _INTERVAL_TTL = {"weekly": 8, "3day": 4, "daily": 2}
        ttl = _INTERVAL_TTL.get(self._interval, 8) * 86400
        await self._redis.setex(
            "mha:self_opt:last_run", ttl, datetime.now(timezone.utc).isoformat()
        )

        # Proaktive Insights generieren und ueber Callback melden
        if self._notify_callback and self._proactive_insights:
            insight = await self._generate_proactive_insight()
            if insight:
                try:
                    await self._notify_callback(
                        {
                            "message": insight,
                            "type": "self_optimization_insight",
                            "urgency": "low",
                        }
                    )
                except Exception as e:
                    logger.debug("Proactive insight callback failed: %s", e)

        logger.info(
            "Analyse abgeschlossen: %d Vorschlaege generiert", len(valid_proposals)
        )
        return valid_proposals

    async def get_pending_proposals(self) -> list[dict]:
        """Gibt aktuelle Vorschlaege zurueck (fuer Dashboard/Chat)."""
        if not self.is_enabled():
            return []

        async with self._proposals_lock:
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
            "settings",
            _SETTINGS_PATH,
            reason=f"self_opt:{param}={new_value}",
            changed_by="self_optimization",
        )

        result = await self._apply_parameter(param, new_value)

        if result["success"]:
            proposals.pop(index)
            async with self._proposals_lock:
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
                    json.dumps(
                        {
                            **proposal,
                            "applied_at": datetime.now(timezone.utc).isoformat(),
                            "snapshot_id": snapshot_id,
                        }
                    ),
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
        async with self._proposals_lock:
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
                "mha:self_opt:rejected",
                json.dumps(
                    {**rejected, "rejected_at": datetime.now(timezone.utc).isoformat()}
                ),
            )
            await self._redis.ltrim("mha:self_opt:rejected", 0, 29)
            await self._redis.expire("mha:self_opt:rejected", 90 * 86400)

        return {
            "success": True,
            "message": f"Vorschlag '{rejected['parameter']}' abgelehnt",
        }

    async def reject_all(self) -> dict:
        """User lehnt alle Vorschlaege ab."""
        if not self.is_enabled():
            return {"success": False, "message": "Selbstoptimierung ist deaktiviert"}
        proposals = await self.get_pending_proposals()
        count = len(proposals)
        async with self._proposals_lock:
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
            logger.warning(
                "SICHERHEIT: Vorschlag fuer unbekannten Parameter abgelehnt: %s", param
            )
            return False

        # 2. IMMUTABLE: Geschuetzte Bereiche
        for immutable_key in self._immutable:
            if param.startswith(immutable_key) or immutable_key.startswith(param):
                logger.warning(
                    "SICHERHEIT: Vorschlag fuer immutable Key abgelehnt: %s", param
                )
                return False

        # 3. TYP: Nur numerische Werte erlauben (alle Parameter sind numerisch)
        value = proposal.get("proposed")
        if not isinstance(value, (int, float)):
            logger.warning(
                "SICHERHEIT: Nicht-numerischer Wert abgelehnt: %s=%s (type=%s)",
                param,
                value,
                type(value).__name__,
            )
            return False

        # 4. BOUNDS: Grenzen pruefen
        bounds = self._bounds.get(param)
        if bounds:
            if value < bounds.get("min", float("-inf")):
                logger.warning(
                    "Vorschlag unter Minimum: %s=%s (min=%s)",
                    param,
                    value,
                    bounds["min"],
                )
                return False
            if value > bounds.get("max", float("inf")):
                logger.warning(
                    "Vorschlag ueber Maximum: %s=%s (max=%s)",
                    param,
                    value,
                    bounds["max"],
                )
                return False

        # 5. KONSISTENZ: Sarkasmus-Formalitaet Sync
        current = self._get_current_values()
        if param == "sarcasm_level":
            formality = current.get("formality_start", 80)
            if value >= 8 and formality > 75:
                logger.warning(
                    "KONSISTENZ: sarcasm_level=%s mit formality_start=%s widerspruechlich — abgelehnt",
                    value,
                    formality,
                )
                return False
            if value <= 1 and formality < 30:
                logger.warning(
                    "KONSISTENZ: sarcasm_level=%s mit formality_start=%s widerspruechlich — abgelehnt",
                    value,
                    formality,
                )
                return False

        return True

    async def _generate_proposals(
        self,
        corrections: list,
        feedback_stats: dict,
        outcome_stats: dict = None,
        quality_stats: dict = None,
        correction_patterns: list = None,
    ) -> list[dict]:
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
                return [
                    p for p in proposals if isinstance(p, dict) and "parameter" in p
                ]

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
            old_value = self._get_current_values().get(param)

            def _read_and_write():
                import tempfile

                with open(_SETTINGS_PATH) as f:
                    config = yaml.safe_load(f) or {}

                node = config
                for key in path[:-1]:
                    if key not in node:
                        node[key] = {}
                    node = node[key]
                node[path[-1]] = new_value

                tmp_fd, tmp_path = tempfile.mkstemp(
                    dir=_SETTINGS_PATH.parent,
                    suffix=".yaml.tmp",
                )
                try:
                    with open(tmp_fd, "w") as f:
                        yaml.safe_dump(
                            config,
                            f,
                            allow_unicode=True,
                            default_flow_style=False,
                            sort_keys=False,
                        )
                    Path(tmp_path).replace(_SETTINGS_PATH)
                except BaseException:
                    Path(tmp_path).unlink(missing_ok=True)
                    raise

            await asyncio.to_thread(_read_and_write)

            # Hot-Reload: yaml_config im Speicher aktualisieren
            _new = load_yaml_config()
            cfg_module.yaml_config.clear()
            cfg_module.yaml_config.update(_new)
            logger.info("yaml_config nach Parameter-Aenderung im Speicher aktualisiert")

            logger.info("Parameter angepasst: %s = %s", param, new_value)
            return {
                "success": True,
                "message": f"{param}: {old_value} -> {new_value}",
            }

        except Exception as e:
            logger.error("Parameter-Aenderung fehlgeschlagen: %s", e)
            return {"success": False, "message": "Parameter-Aenderung fehlgeschlagen."}

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
        except Exception as e:
            logger.warning("Self-optimization data retrieval failed: %s", e)
            return {}

    # Feature 9a: Neue Datenquellen
    async def _get_outcome_stats(self, outcome_tracker=None) -> dict:
        """Holt Outcome-Statistiken (Feature 9a)."""
        if not outcome_tracker:
            return {}
        try:
            return await outcome_tracker.get_stats()
        except Exception as e:
            logger.debug("Self-optimization data retrieval failed: %s", e)
            return {}

    async def _get_quality_stats(self, response_quality=None) -> dict:
        """Holt Response-Quality-Statistiken (Feature 9a)."""
        if not response_quality:
            return {}
        try:
            return await response_quality.get_stats()
        except Exception as e:
            logger.debug("Self-optimization data retrieval failed: %s", e)
            return {}

    async def _get_correction_patterns(self, correction_memory=None) -> list:
        """Holt Korrektur-Muster (Feature 9a)."""
        if not correction_memory:
            return []
        try:
            return await correction_memory.get_correction_patterns()
        except Exception as e:
            logger.debug("Self-optimization data retrieval failed: %s", e)
            return []

    # Feature 9b: Effectiveness Tracking
    async def save_baseline(
        self, param: str, outcome_tracker=None, response_quality=None
    ):
        """Speichert Baseline-Metriken vor einer Aenderung (Feature 9b)."""
        if not self._redis:
            return
        baseline = {"timestamp": datetime.now(timezone.utc).isoformat()}
        if outcome_tracker:
            try:
                baseline["outcome_stats"] = await outcome_tracker.get_stats()
            except Exception as e:
                logger.debug("Unhandled: %s", e)
        if response_quality:
            try:
                baseline["quality_stats"] = await response_quality.get_stats()
            except Exception as e:
                logger.debug("Unhandled: %s", e)
        await self._redis.setex(
            f"mha:self_opt:baseline:{param}",
            30 * 86400,
            json.dumps(baseline, ensure_ascii=False, default=str),
        )

    async def check_effectiveness(
        self, param: str, outcome_tracker=None, response_quality=None
    ) -> Optional[dict]:
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
            except Exception as e:
                logger.debug("Unhandled: %s", e)
        if response_quality:
            try:
                current_quality = await response_quality.get_stats()
            except Exception as e:
                logger.debug("Unhandled: %s", e)
        # Einfacher Vergleich: Outcome-Score-Differenz
        baseline_outcomes = baseline.get("outcome_stats", {})
        score_changes = {}
        for action, stats in current_outcomes.items():
            if isinstance(stats, dict) and action in baseline_outcomes:
                old_score = baseline_outcomes[action].get("score", 0.5)
                new_score = stats.get("score", 0.5)
                if isinstance(old_score, (int, float)) and isinstance(
                    new_score, (int, float)
                ):
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

        lines = ["Folgende Optimierungen bieten sich an:", ""]
        for i, p in enumerate(proposals):
            conf = int(p.get("confidence", 0) * 100)
            lines.append(
                f"  [{i + 1}] {p['parameter']}: {p['current']} -> {p['proposed']} "
                f"({conf}% Confidence)"
            )
            lines.append(f"      Grund: {p['reason']}")
            lines.append("")

        lines.append("Sage 'Vorschlag 1 annehmen', 'alle ablehnen', oder 'Rollback'.")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Phase 13.4b: Banned-Phrases Auto-Detection
    # ------------------------------------------------------------------

    async def track_filtered_phrase(self, phrase: str):
        """Trackt eine Phrase die vom Response-Filter entfernt wurde.

        Wird aus brain.py _filter_response() aufgerufen.
        Bei 5+ Entfernungen der gleichen Phrase: Vorschlag zur dauerhaften Aufnahme.
        """
        if not self._redis or not phrase:
            return
        try:
            clean = phrase.strip()[:100]
            key = "mha:self_opt:phrase_filter_counts"
            await self._redis.hincrby(key, clean, 1)
            await self._redis.expire(key, 30 * 86400)
        except Exception as e:
            logger.debug("Unhandled: %s", e)

    async def track_character_break(self, break_type: str, detail: str = ""):
        """Trackt einen erkannten Charakter-Bruch pro Session.

        break_type: Art des Bruchs (z.B. "llm_voice", "identity", "hallucination",
                    "formal_sie", "banned_starter", "sanity_check")
        detail: Optionales Detail (z.B. die erkannte Phrase, max 100 Zeichen)
        """
        if not self._redis:
            return
        try:
            from datetime import date

            day_key = f"mha:self_opt:character_breaks:{date.today().isoformat()}"
            await self._redis.hincrby(day_key, break_type, 1)
            await self._redis.expire(day_key, 30 * 86400)
            # Detail-Log fuer Analyse (letzte 50 Brueche)
            if detail:
                import json

                log_key = "mha:self_opt:character_break_log"
                entry = json.dumps(
                    {
                        "type": break_type,
                        "detail": detail[:100],
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }
                )
                await self._redis.lpush(log_key, entry)
                await self._redis.ltrim(log_key, 0, 49)
                await self._redis.expire(log_key, 30 * 86400)
        except Exception as e:
            logger.warning("Character break tracking failed: %s", e)

    async def get_character_break_stats(self, days: int = 7) -> dict:
        """Gibt Character-Break-Statistiken der letzten N Tage zurueck."""
        if not self._redis:
            return {}
        try:
            from datetime import date, timedelta

            stats = {}
            for d in range(days):
                day = (date.today() - timedelta(days=d)).isoformat()
                key = f"mha:self_opt:character_breaks:{day}"
                day_data = await self._redis.hgetall(key)
                if day_data:
                    stats[day] = {
                        (k.decode() if isinstance(k, bytes) else k): int(v)
                        for k, v in day_data.items()
                    }
            return stats
        except Exception as e:
            logger.debug("Self-optimization data retrieval failed: %s", e)
            return {}

    async def track_user_phrase_correction(self, original_phrase: str):
        """Trackt wenn User eine Phrase explizit korrigiert ('sag das nicht').

        Wird aus correction_memory aufgerufen.
        """
        if not self._redis or not original_phrase:
            return
        try:
            clean = original_phrase.strip()[:100]
            key = "mha:self_opt:phrase_corrections"
            await self._redis.hincrby(key, clean, 1)
            await self._redis.expire(key, 90 * 86400)
        except Exception as e:
            logger.debug("Unhandled: %s", e)

    async def detect_new_banned_phrases(self) -> list[dict]:
        """Erkennt Phrasen die haeufig gefiltert oder korrigiert werden.

        Returns:
            Liste von Vorschlaegen: [{"phrase": "...", "count": N, "source": "filter"|"correction"}]
        """
        if not self._redis:
            return []

        suggestions = []

        # 1. Phrasen die der Filter oft entfernt (5+ mal)
        try:
            raw_filter_counts = await self._redis.hgetall(
                "mha:self_opt:phrase_filter_counts"
            )
            filter_counts = {
                (k.decode() if isinstance(k, bytes) else k): (
                    v.decode() if isinstance(v, bytes) else v
                )
                for k, v in (raw_filter_counts or {}).items()
            }
            for phrase, count_str in filter_counts.items():
                count = int(count_str or 0)
                if count >= 5:
                    suggestions.append(
                        {
                            "phrase": phrase,
                            "count": count,
                            "source": "filter",
                            "reason": f"Wurde {count}x vom Filter entfernt — dauerhaft aufnehmen?",
                        }
                    )
        except Exception as e:
            logger.debug("Unhandled: %s", e)
        # 2. Phrasen die User explizit korrigiert hat (2+ mal)
        try:
            raw_corrections = await self._redis.hgetall(
                "mha:self_opt:phrase_corrections"
            )
            corrections = {
                (k.decode() if isinstance(k, bytes) else k): (
                    v.decode() if isinstance(v, bytes) else v
                )
                for k, v in (raw_corrections or {}).items()
            }
            for phrase, count_str in corrections.items():
                count = int(count_str or 0)
                if count >= 2:
                    suggestions.append(
                        {
                            "phrase": phrase,
                            "count": count,
                            "source": "correction",
                            "reason": f"User hat diese Formulierung {count}x korrigiert",
                        }
                    )
        except Exception as e:
            logger.debug("Unhandled: %s", e)
        # Sortieren nach Haeufigkeit
        suggestions.sort(key=lambda s: s["count"], reverse=True)
        return suggestions[:5]

    async def add_banned_phrase(self, phrase: str) -> dict:
        """Fuegt eine Phrase zur banned_phrases Liste hinzu (nach User-Bestaetigung).

        Returns: {"success": bool, "message": str}
        """
        if not phrase or len(phrase) < 3:
            return {"success": False, "message": "Phrase zu kurz"}

        try:

            def _read_config():
                with open(_SETTINGS_PATH) as f:
                    return yaml.safe_load(f) or {}

            config = await asyncio.to_thread(_read_config)

            # Snapshot vor Aenderung
            await self.versioning.create_snapshot(
                "settings",
                _SETTINGS_PATH,
                reason=f"add_banned_phrase:{phrase[:50]}",
                changed_by="self_optimization",
            )

            if "response_filter" not in config:
                config["response_filter"] = {}
            if "banned_phrases" not in config["response_filter"]:
                config["response_filter"]["banned_phrases"] = []

            if phrase in config["response_filter"]["banned_phrases"]:
                return {
                    "success": False,
                    "message": f"'{phrase}' ist bereits in der Liste",
                }

            config["response_filter"]["banned_phrases"].append(phrase)

            def _write_config():
                with open(_SETTINGS_PATH, "w") as f:
                    yaml.safe_dump(
                        config,
                        f,
                        allow_unicode=True,
                        default_flow_style=False,
                        sort_keys=False,
                    )

            await asyncio.to_thread(_write_config)

            # Hot-Reload
            _new = load_yaml_config()
            cfg_module.yaml_config.clear()
            cfg_module.yaml_config.update(_new)

            # Zaehler zuruecksetzen
            if self._redis:
                await self._redis.hdel("mha:self_opt:phrase_filter_counts", phrase)
                await self._redis.hdel("mha:self_opt:phrase_corrections", phrase)

            logger.info("Banned Phrase hinzugefuegt: '%s'", phrase)
            return {
                "success": True,
                "message": f"'{phrase}' zur Sperrliste hinzugefuegt",
            }

        except Exception as e:
            logger.error("Banned Phrase Fehler: %s", e)
            return {
                "success": False,
                "message": "Sperrlisten-Aenderung fehlgeschlagen.",
            }

    def format_phrase_suggestions(self, suggestions: list[dict]) -> str:
        """Formatiert Phrase-Vorschlaege fuer Chat-Ausgabe."""
        if not suggestions:
            return ""

        lines = ["Wiederkehrende Phrasen die ich sperren sollte:", ""]
        for i, s in enumerate(suggestions):
            source_de = (
                "oft vom Filter entfernt"
                if s["source"] == "filter"
                else "von dir korrigiert"
            )
            lines.append(f'  [{i + 1}] "{s["phrase"]}" ({s["count"]}x {source_de})')
        lines.append("")
        lines.append("Sage 'Phrase 1 sperren' oder 'alle Phrasen sperren'.")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Phase 13.4c: Weekly Summary Report
    # ------------------------------------------------------------------

    async def generate_weekly_summary(self, correction_memory=None) -> str:
        """Generiert eine kompakte Zusammenfassung der Optimierungs-Aktivitaeten.

        Returns:
            Formatierter Text fuer den Weekly-Report.
        """
        parts = []

        # 1. Optimierungs-Vorschlaege (Parameter)
        proposals = await self.get_pending_proposals()
        if proposals:
            parts.append(
                f"- {len(proposals)} Optimierungsvorschlag{'e' if len(proposals) > 1 else ''} wartend"
            )

        # 2. Angewandte Aenderungen (letzte Woche)
        if self._redis:
            history = await self._redis.lrange("mha:self_opt:history", 0, 4)
            recent = []
            for item in history or []:
                try:
                    entry = json.loads(item)
                    if entry.get("applied_at"):
                        recent.append(
                            f"{entry['parameter']}: {entry.get('current')} -> {entry.get('proposed')}"
                        )
                except (json.JSONDecodeError, KeyError):
                    pass
            if recent:
                parts.append(f"- Letzte Aenderungen: {', '.join(recent[:3])}")

        # 3. Phrase-Vorschlaege
        phrase_suggestions = await self.detect_new_banned_phrases()
        if phrase_suggestions:
            parts.append(
                f"- {len(phrase_suggestions)} neue Phrase{'n' if len(phrase_suggestions) > 1 else ''} zum Sperren erkannt"
            )

        # 4. Korrektur-Statistiken
        if correction_memory:
            stats = await correction_memory.get_stats()
            total = stats.get("total_corrections", 0)
            rules = stats.get("active_rules", 0)
            if total or rules:
                parts.append(f"- Korrekturen: {total} gesamt, {rules} aktive Regeln")

        if not parts:
            return ""

        return "Selbstoptimierung:\n" + "\n".join(parts)

    def health_status(self) -> dict:
        """Status fuer Diagnostik."""
        return {
            "enabled": self._enabled,
            "approval_mode": self._approval_mode,
            "interval": self._interval,
            "pending_proposals": len(self._pending_proposals),
            "max_proposals": self._max_proposals,
        }
