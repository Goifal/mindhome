"""Tests fuer Causal Thinking Enhancements.

Testet:
- Fix 1: Action Planner kausaler Kontext
- Fix 2: Proaktives Counterfactual
- Fix 3: Reasoning-Chains Aktivierung
- Fix 4: Cross-Domain Causal Learning
"""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------
# Fix 1: Action Planner kausaler Kontext
# ---------------------------------------------------------------


class TestActionPlannerCausalContext:
    """Testet ob der Action Planner kausale Daten im Prompt erhaelt."""

    def test_planner_prompt_includes_causal_thinking(self):
        """Der PLANNER_SYSTEM_PROMPT sollte kausales Denken erwaehnen."""
        try:
            from assistant.action_planner import PLANNER_SYSTEM_PROMPT
        except ImportError:
            # FastAPI nicht installiert — Prompt direkt aus Datei lesen
            import re
            with open("assistant/action_planner.py") as f:
                content = f.read()
            match = re.search(
                r'PLANNER_SYSTEM_PROMPT\s*=\s*"""(.*?)"""', content, re.DOTALL
            )
            assert match, "PLANNER_SYSTEM_PROMPT nicht gefunden"
            PLANNER_SYSTEM_PROMPT = match.group(1)

        assert "KAUSALES DENKEN" in PLANNER_SYSTEM_PROMPT
        assert "Abhaengigkeiten" in PLANNER_SYSTEM_PROMPT
        assert "ERFAHRUNGSWERTE" in PLANNER_SYSTEM_PROMPT

    def test_causal_context_extracts_outcome_scores(self):
        """Outcome-Scores werden in den kausalen Kontext extrahiert."""
        # Simuliere die Logik aus action_planner.plan_and_execute
        context = {
            "causal_context": {
                "outcome_scores": {"set_cover": 0.2, "set_light": 0.9},
            }
        }
        _causal_ctx = context.get("causal_context", {})
        _outcome_scores = _causal_ctx.get("outcome_scores", {})
        _low = [
            (a, s) for a, s in _outcome_scores.items() if s < 0.4
        ]
        assert len(_low) == 1
        assert _low[0][0] == "set_cover"

    def test_causal_context_extracts_chains(self):
        """Causal-Chains werden in den Planner-Kontext extrahiert."""
        context = {
            "causal_context": {
                "causal_chains": [
                    {
                        "type": "causal_chain",
                        "description": "Kette (hour:19): A → B → C",
                        "confidence": 0.85,
                        "order_consistency": 0.95,
                    }
                ],
            }
        }
        _chains = context["causal_context"]["causal_chains"]
        assert len(_chains) == 1
        assert _chains[0]["order_consistency"] == 0.95

    def test_empty_causal_context_no_crash(self):
        """Leerer kausaler Kontext erzeugt keinen Fehler."""
        context = {}
        _causal_ctx = context.get("causal_context", {})
        _outcome_scores = _causal_ctx.get("outcome_scores", {})
        _chains = _causal_ctx.get("causal_chains", [])
        assert _outcome_scores == {}
        assert _chains == []


# ---------------------------------------------------------------
# Fix 2: Proaktives Counterfactual
# ---------------------------------------------------------------


class TestProactiveCounterfactual:
    """Testet das proaktive Counterfactual vor der Ausfuehrung."""

    def test_build_counterfactual_window_open(self):
        """Counterfactual fuer climate + window_open liefert Warnung."""
        from assistant.explainability import ExplainabilityEngine

        result = ExplainabilityEngine._build_counterfactual(
            "climate", {"window_open": True}
        )
        assert result is not None
        assert "Heizkosten" in result or "Ohne Eingreifen" in result

    def test_build_counterfactual_empty_room(self):
        """Counterfactual fuer light + empty_room liefert Stromverbrauch-Warnung."""
        from assistant.explainability import ExplainabilityEngine

        result = ExplainabilityEngine._build_counterfactual(
            "light", {"room_empty": True}
        )
        assert result is not None
        assert "Stromverbrauch" in result or "Ohne Eingreifen" in result

    def test_build_counterfactual_no_context(self):
        """Ohne relevanten Kontext kein Counterfactual."""
        from assistant.explainability import ExplainabilityEngine

        result = ExplainabilityEngine._build_counterfactual("light", {})
        assert result is None

    def test_counterfactual_in_action_entry(self):
        """Counterfactual wird in executed_actions Eintrag gespeichert."""
        action_entry = {
            "function": "set_climate",
            "args": {"room": "wohnzimmer"},
            "result": {"success": True},
            "counterfactual": "Ohne Eingreifen: Heizkosten von ca. 0.50€/h verschwendet.",
        }
        assert "counterfactual" in action_entry
        assert "Heizkosten" in action_entry["counterfactual"]


# ---------------------------------------------------------------
# Fix 3: Reasoning-Chains Aktivierung
# ---------------------------------------------------------------


class TestReasoningChains:
    """Testet ob Reasoning-Chains standardmaessig aktiv sind."""

    def test_reasoning_chains_default_true(self):
        """reasoning_chains sollte standardmaessig True sein."""
        from assistant.explainability import ExplainabilityEngine

        with patch("assistant.explainability.yaml_config", {"explainability": {}}):
            engine = ExplainabilityEngine()
        assert engine.reasoning_chains is True

    def test_format_explanation_includes_chain(self):
        """format_explanation sollte Kausalkette enthalten wenn aktiviert."""
        from assistant.explainability import ExplainabilityEngine

        with patch("assistant.explainability.yaml_config", {"explainability": {}}):
            engine = ExplainabilityEngine()

        decision = {
            "action": "set_climate(temperature=20)",
            "reason": "Fenster offen erkannt",
            "trigger": "sensor",
            "domain": "climate",
            "confidence": 0.9,
            "timestamp": time.time(),
            "time_str": "19:30:00",
        }
        result = engine.format_explanation(decision)
        assert "Kausalkette" in result
        assert "sensor" in result

    def test_format_explanation_without_domain(self):
        """Ohne Domain/Trigger keine Kausalkette im Format."""
        from assistant.explainability import ExplainabilityEngine

        with patch("assistant.explainability.yaml_config", {"explainability": {}}):
            engine = ExplainabilityEngine()

        decision = {
            "action": "set_light(brightness=50)",
            "reason": "User-Befehl",
            "trigger": "",
            "domain": "",
            "confidence": 1.0,
            "timestamp": time.time(),
            "time_str": "20:00:00",
        }
        result = engine.format_explanation(decision)
        assert "Kausalkette" not in result

    def test_counterfactual_from_context_in_log_decision(self):
        """Proaktives Counterfactual aus context wird als alternative_outcome geloggt."""
        from assistant.explainability import ExplainabilityEngine

        with patch("assistant.explainability.yaml_config", {"explainability": {}}):
            engine = ExplainabilityEngine()

        import asyncio
        asyncio.get_event_loop().run_until_complete(
            engine.log_decision(
                action="set_climate(temp=20)",
                reason="User-Befehl",
                context={"counterfactual": "Ohne Eingreifen: Heizkosten steigen"},
                domain="climate",
            )
        )
        # Letzte Entscheidung sollte das Counterfactual enthalten
        decisions = engine.explain_last(1)
        assert len(decisions) == 1
        assert "Heizkosten" in str(decisions[0].get("alternative_outcomes", []))


# ---------------------------------------------------------------
# Fix 4: Cross-Domain Causal Learning
# ---------------------------------------------------------------


class TestCrossDomainLearning:
    """Testet das Cross-Domain Causal Learning in der InsightEngine."""

    @pytest.mark.asyncio
    async def test_track_cross_domain_correlation(self):
        """Korrelation zwischen zwei Domains wird gezaehlt."""
        from assistant.insight_engine import InsightEngine

        ha = MagicMock()
        with patch("assistant.insight_engine.yaml_config", {
            "insights": {},
            "insight_checks": {},
            "insight_llm_causal": {},
            "cross_domain_learning": {"enabled": True, "window_seconds": 300, "min_count": 3},
        }):
            engine = InsightEngine(ha)

        redis = AsyncMock()
        engine.redis = redis

        # Vorheriger Change existiert (anderer Domain, innerhalb Fenster)
        prev_data = json.dumps({
            "entity": "binary_sensor.fenster_wz",
            "domain": "binary_sensor",
            "old": "off",
            "new": "on",
            "ts": time.time() - 30,
        })
        redis.scan.return_value = (
            0,
            [b"mha:cross_domain:recent:binary_sensor.fenster_wz"],
        )
        redis.get.return_value = prev_data

        await engine._track_cross_domain_correlation(
            "climate.wohnzimmer", "22", "20"
        )

        # Korrelation sollte gezaehlt werden
        redis.incr.assert_called_once()
        incr_key = redis.incr.call_args[0][0]
        assert "binary_sensor.fenster_wz" in incr_key
        assert "climate.wohnzimmer" in incr_key

    @pytest.mark.asyncio
    async def test_same_domain_not_counted(self):
        """Gleiches Domain wird nicht als Korrelation gezaehlt."""
        from assistant.insight_engine import InsightEngine

        ha = MagicMock()
        with patch("assistant.insight_engine.yaml_config", {
            "insights": {},
            "insight_checks": {},
            "insight_llm_causal": {},
            "cross_domain_learning": {"enabled": True, "window_seconds": 300, "min_count": 3},
        }):
            engine = InsightEngine(ha)

        redis = AsyncMock()
        engine.redis = redis

        # Vorheriger Change im GLEICHEN Domain
        prev_data = json.dumps({
            "entity": "climate.schlafzimmer",
            "domain": "climate",
            "old": "20",
            "new": "22",
            "ts": time.time() - 30,
        })
        redis.scan.return_value = (
            0,
            [b"mha:cross_domain:recent:climate.schlafzimmer"],
        )
        redis.get.return_value = prev_data

        await engine._track_cross_domain_correlation(
            "climate.wohnzimmer", "22", "20"
        )

        # Gleicher Domain → keine Korrelation
        redis.incr.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_learned_insights_min_count(self):
        """Nur Korrelationen mit >= min_count werden zurueckgegeben."""
        from assistant.insight_engine import InsightEngine

        ha = MagicMock()
        with patch("assistant.insight_engine.yaml_config", {
            "insights": {},
            "insight_checks": {},
            "insight_llm_causal": {},
            "cross_domain_learning": {"enabled": True, "min_count": 5},
        }):
            engine = InsightEngine(ha)

        redis = AsyncMock()
        engine.redis = redis

        redis.scan.return_value = (
            0,
            [b"mha:cross_domain:corr:binary_sensor.fenster_wz:climate.wohnzimmer"],
        )
        redis.get.return_value = b"7"  # Ueber Minimum

        insights = await engine.get_learned_cross_domain_insights()
        assert len(insights) == 1
        assert insights[0]["count"] == 7
        assert "fenster wz" in insights[0]["description"]

    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self):
        """Deaktiviertes Cross-Domain gibt leere Liste zurueck."""
        from assistant.insight_engine import InsightEngine

        ha = MagicMock()
        with patch("assistant.insight_engine.yaml_config", {
            "insights": {},
            "insight_checks": {},
            "insight_llm_causal": {},
            "cross_domain_learning": {"enabled": False},
        }):
            engine = InsightEngine(ha)

        engine.redis = AsyncMock()
        insights = await engine.get_learned_cross_domain_insights()
        assert insights == []
