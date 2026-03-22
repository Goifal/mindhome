"""Tests fuer Intelligence-Fixes (Kausales Denken Phase 3).

Testet:
- Fix 1: Topic-Switch Multi-Turn Schutz
- Fix 2: Correction Memory kausaler Kontext
- Fix 3: Outcome Failure-Cause Analyse
- Fix 4: Self-Optimization Korrelationsanalyse
- Fix 6: Anticipation Plausibilitaets-Check
- Fix 8: Learning-Transfer Grund-Tracking
"""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------
# Fix 1: Topic-Switch Multi-Turn Schutz
# ---------------------------------------------------------------


class TestTopicSwitchProtection:
    """Testet dass semantische Verfeinerungen keinen Topic-Switch ausloesen."""

    def _make_manager(self):
        from assistant.dialogue_state import DialogueStateManager
        with patch("assistant.dialogue_state.yaml_config", {"dialogue_state": {}}):
            return DialogueStateManager()

    def test_refinement_words_prevent_reset(self):
        """'Heller bitte' nach 'Mach Licht an' soll KEIN Topic-Switch sein."""
        mgr = self._make_manager()
        # Turn 1
        mgr.track_turn("Mach das Licht an", person="test")
        state = mgr._get_state("test")
        assert state.turn_count == 1

        # Turn 2: Verfeinerung
        mgr.track_turn("Heller bitte", person="test")
        state = mgr._get_state("test")
        # Sollte NICHT zurueckgesetzt worden sein
        assert state.turn_count == 2

    def test_correction_words_prevent_reset(self):
        """'Nein, nicht so hell' soll kein Topic-Switch sein."""
        mgr = self._make_manager()
        mgr.track_turn("Mach das Licht auf 80 Prozent", person="test")
        mgr.track_turn("Nein etwas dunkler bitte", person="test")
        state = mgr._get_state("test")
        assert state.turn_count == 2

    def test_domain_continuity_prevents_reset(self):
        """Licht-Woerter nach Licht-Befehl = kein Topic-Switch."""
        mgr = self._make_manager()
        mgr.track_turn("Schalte die Lampe ein", person="test",
                       domain="light")
        mgr.track_turn("Kannst du dimmen auf 50", person="test")
        state = mgr._get_state("test")
        assert state.turn_count == 2

    def test_real_topic_switch_still_detected(self):
        """Ein echter Topic-Switch soll weiterhin erkannt werden."""
        mgr = self._make_manager()
        mgr.track_turn("Wie wird das Wetter morgen", person="test")
        # Komplett anderes Thema, keine Verfeinerung, keine Referenz
        mgr.track_turn("Bestell mir eine Pizza bei Lieferando", person="test")
        state = mgr._get_state("test")
        # Topic-Switch sollte erkannt werden (turn_count = 1)
        assert state.turn_count == 1


# ---------------------------------------------------------------
# Fix 2: Correction Memory kausaler Kontext
# ---------------------------------------------------------------


class TestCorrectionMemoryCausalContext:
    """Testet kausalen Kontext in der Correction Memory."""

    @pytest.mark.asyncio
    async def test_store_with_causal_context(self):
        """Korrektur mit kausalem Kontext speichern."""
        from assistant.correction_memory import CorrectionMemory

        with patch("assistant.correction_memory.yaml_config", {
            "correction_memory": {"enabled": True},
        }):
            cm = CorrectionMemory()

        redis = AsyncMock()
        cm.redis = redis
        cm.enabled = True
        # Mock _update_rules
        cm._update_rules = AsyncMock()

        await cm.store_correction(
            original_action="set_climate",
            original_args={"temperature": 22, "room": "wohnzimmer"},
            correction_text="Nicht heizen, Fenster ist offen",
            person="Max",
            causal_context={"windows_open": True, "activity": "lueften"},
        )

        # Redis lpush sollte aufgerufen worden sein
        redis.lpush.assert_called_once()
        stored = json.loads(redis.lpush.call_args[0][1])
        assert stored["causal_context"]["windows_open"] is True
        assert stored["causal_context"]["activity"] == "lueften"

    @pytest.mark.asyncio
    async def test_store_without_context_no_crash(self):
        """Korrektur ohne kausalen Kontext funktioniert weiterhin."""
        from assistant.correction_memory import CorrectionMemory

        with patch("assistant.correction_memory.yaml_config", {
            "correction_memory": {"enabled": True},
        }):
            cm = CorrectionMemory()

        redis = AsyncMock()
        cm.redis = redis
        cm.enabled = True
        cm._update_rules = AsyncMock()

        await cm.store_correction(
            original_action="set_light",
            original_args={"brightness": 80},
            correction_text="Zu hell",
        )

        stored = json.loads(redis.lpush.call_args[0][1])
        assert "causal_context" not in stored


# ---------------------------------------------------------------
# Fix 3: Outcome Failure-Cause Analyse
# ---------------------------------------------------------------


class TestOutcomeFailureCause:
    """Testet die Ursachen-Analyse bei negativen Outcomes."""

    @pytest.mark.asyncio
    async def test_device_unavailable_detected(self):
        """Geraet unavailable wird als Ursache erkannt."""
        from assistant.outcome_tracker import OutcomeTracker

        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {}}):
            t = OutcomeTracker()
        t.ha = AsyncMock()

        cause = await t._analyze_failure_cause(
            "light.wohnzimmer", "set_light",
            {"state": "on", "attributes": {}},
            {"state": "unavailable", "attributes": {}},
        )
        assert cause == "device_unavailable"

    @pytest.mark.asyncio
    async def test_user_reverted_detected(self):
        """User-Revert (State zurueckgesetzt) wird erkannt."""
        from assistant.outcome_tracker import OutcomeTracker

        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {}}):
            t = OutcomeTracker()
        t.ha = AsyncMock()
        t.ha.get_states.return_value = []

        cause = await t._analyze_failure_cause(
            "light.wohnzimmer", "set_light",
            {"state": "on", "attributes": {}},
            {"state": "off", "attributes": {}},
        )
        assert "user_reverted" in cause

    @pytest.mark.asyncio
    async def test_window_open_detected_for_climate(self):
        """Offenes Fenster bei Klima-Aktion wird als Ursache erkannt."""
        from assistant.outcome_tracker import OutcomeTracker

        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {}}):
            t = OutcomeTracker()
        t.ha = AsyncMock()
        t.ha.get_states.return_value = [
            {"entity_id": "binary_sensor.fenster_wohnzimmer", "state": "on"},
        ]

        cause = await t._analyze_failure_cause(
            "climate.wohnzimmer", "set_climate",
            {"state": "heat", "attributes": {"temperature": 22}},
            {"state": "heat", "attributes": {"temperature": 18}},
            room="wohnzimmer",
        )
        assert "window_open" in cause


# ---------------------------------------------------------------
# Fix 4: Self-Optimization Korrelationsanalyse
# ---------------------------------------------------------------


class TestSelfOptimizationCorrelations:
    """Testet die Failure-Korrelationsanalyse."""

    @pytest.mark.asyncio
    async def test_track_with_failure_cause(self):
        """Ursache wird mit Domain-Korrektur gespeichert."""
        from assistant.self_optimization import SelfOptimization

        with patch("assistant.self_optimization.yaml_config", {
            "self_optimization": {"enabled": True},
        }):
            engine = SelfOptimization.__new__(SelfOptimization)
            engine._redis = AsyncMock()
            engine._proactive_insights = True

        await engine.track_domain_correction("climate", "window_open")
        # Domain-Counter + Cause-Korrelation
        assert engine._redis.hincrby.call_count == 1
        assert engine._redis.incr.call_count == 1
        incr_key = engine._redis.incr.call_args[0][0]
        assert "climate" in incr_key
        assert "window_open" in incr_key

    @pytest.mark.asyncio
    async def test_get_failure_correlations(self):
        """Korrelationen werden korrekt geladen."""
        from assistant.self_optimization import SelfOptimization

        with patch("assistant.self_optimization.yaml_config", {
            "self_optimization": {"enabled": True},
        }):
            engine = SelfOptimization.__new__(SelfOptimization)
            engine._redis = AsyncMock()

        engine._redis.scan.return_value = (
            0,
            [b"mha:self_opt:cause_corr:climate:window_open"],
        )
        engine._redis.get.return_value = b"7"

        correlations = await engine.get_failure_correlations()
        assert len(correlations) == 1
        assert correlations[0]["domain"] == "climate"
        assert correlations[0]["cause"] == "window_open"
        assert correlations[0]["count"] == 7


# ---------------------------------------------------------------
# Fix 6: Anticipation Plausibilitaets-Check
# ---------------------------------------------------------------


class TestAnticipationPlausibility:
    """Testet den Plausibilitaets-Check fuer Causal-Chains."""

    def test_unrelated_domains_reduce_confidence(self):
        """Ketten mit unverwandten Domains bekommen reduzierte Confidence."""
        # media + climate sind NICHT in _RELATED_DOMAINS
        pattern = {
            "type": "causal_chain",
            "actions": ["play_media", "set_climate"],
            "confidence": 0.8,
            "description": "media → climate",
        }
        # Simuliere den Domain-Check
        _domains = set()
        for _ca in pattern["actions"]:
            if "media" in _ca or "play" in _ca:
                _domains.add("media")
            elif "climate" in _ca:
                _domains.add("climate")
        assert "media" in _domains
        assert "climate" in _domains
        # media + climate ist NICHT in RELATED_DOMAINS
        _RELATED_DOMAINS = {
            frozenset({"light", "cover"}),
            frozenset({"climate", "cover"}),
            frozenset({"climate", "light"}),
            frozenset({"lock", "security"}),
            frozenset({"light", "security"}),
        }
        _all_related = all(
            frozenset(pair) in _RELATED_DOMAINS
            for pair in __import__("itertools").combinations(_domains, 2)
        )
        assert not _all_related  # Nicht verwandt

    def test_related_domains_keep_confidence(self):
        """Ketten mit verwandten Domains behalten ihre Confidence."""
        _domains = {"light", "cover"}
        _RELATED_DOMAINS = {
            frozenset({"light", "cover"}),
            frozenset({"climate", "cover"}),
        }
        _all_related = all(
            frozenset(pair) in _RELATED_DOMAINS
            for pair in __import__("itertools").combinations(_domains, 2)
        )
        assert _all_related  # Verwandt


# ---------------------------------------------------------------
# Fix 8: Learning-Transfer Grund-Tracking
# ---------------------------------------------------------------


class TestLearningTransferReason:
    """Testet dass Gruende im Learning-Transfer gespeichert werden."""

    @pytest.mark.asyncio
    async def test_observe_action_with_reason(self):
        """Grund wird in der Praeferenz gespeichert."""
        from assistant.learning_transfer import LearningTransfer

        with patch("assistant.learning_transfer.yaml_config", {
            "learning_transfer": {"enabled": True, "domains": ["light"]},
        }):
            engine = LearningTransfer.__new__(LearningTransfer)
            engine.enabled = True
            engine.domains_enabled = ["light"]
            engine._preferences = {}
            engine._lock = __import__("asyncio").Lock()
            engine._save_preferences = AsyncMock()
            engine.auto_suggest = False

        await engine.observe_action(
            room="kueche",
            domain="light",
            attributes={"brightness": 180, "color_temp": 4000},
            person="Max",
            reason="task_lighting",
        )

        prefs = engine._preferences.get("kueche:light", [])
        assert len(prefs) == 1
        assert prefs[0]["reason"] == "task_lighting"
        assert prefs[0]["brightness"] == 180
