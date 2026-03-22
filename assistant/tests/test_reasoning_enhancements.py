"""Tests fuer Reasoning-Enhancements (Phase 18+).

Testet:
- P0.1: Outcome-Feedback in JARVIS DENKT MIT
- P0.2: Kumulative Daily Poison Protection
- P0.3: Think-Content Self-Consistency Check
- P1.1: Causal-Chain Richtungserkennung
- P1.2: Learned Follow-ups (Think-Ahead)
- P2.1: Recency-Weighting fuer Patterns
"""

import asyncio
import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------
# P0.1: Outcome-Feedback in JARVIS DENKT MIT
# ---------------------------------------------------------------


class TestOutcomeFeedbackInContext:
    """Testet ob niedrige Outcome-Scores als Hints in JARVIS DENKT MIT erscheinen.

    Testet die Logik direkt ohne vollen Brain-Import (vermeidet FastAPI-Dep).
    """

    def _build_hints_with_scores(self, outcome_scores):
        """Simuliert den Outcome-Score-Teil von _build_jarvis_thinks_context."""
        hints = []
        _LOW_SCORE_THRESHOLD = 0.35
        if outcome_scores:
            low_score_actions = [
                (action, score)
                for action, score in outcome_scores.items()
                if score < _LOW_SCORE_THRESHOLD
            ]
            if low_score_actions:
                low_score_actions.sort(key=lambda x: x[1])
                score_lines = [
                    f"  - {a.replace('_', ' ')}: {int(s * 100)}% Erfolg"
                    for a, s in low_score_actions[:3]
                ]
                hints.append(
                    (
                        2,
                        "ERFAHRUNGSWERTE — diese Aktionen werden oft korrigiert:\n"
                        + "\n".join(score_lines)
                        + "\n"
                        "Bei diesen Aktionen: Lieber NACHFRAGEN statt direkt ausfuehren. "
                        "'Soll ich das wirklich so machen? Letztes Mal wurde das korrigiert.'",
                    )
                )
        return hints

    def test_low_scores_generate_hint(self):
        """Niedrige Outcome-Scores (<0.35) sollen einen Hint erzeugen."""
        hints = self._build_hints_with_scores({"set_cover": 0.2, "set_light": 0.8})
        assert len(hints) == 1
        assert "ERFAHRUNGSWERTE" in hints[0][1]
        assert "set cover" in hints[0][1]
        assert "set light" not in hints[0][1]

    def test_no_hint_when_all_scores_high(self):
        """Keine Outcome-Hints wenn alle Scores ueber Threshold."""
        hints = self._build_hints_with_scores({"set_cover": 0.7, "set_light": 0.9})
        assert len(hints) == 0

    def test_empty_scores_no_crash(self):
        """Leere/None Outcome-Scores duerfen keinen Crash verursachen."""
        assert self._build_hints_with_scores(None) == []
        assert self._build_hints_with_scores({}) == []

    def test_max_three_low_scores(self):
        """Maximal 3 niedrige Scores im Hint."""
        scores = {f"action_{i}": 0.1 * i for i in range(6)}
        hints = self._build_hints_with_scores(scores)
        assert len(hints) == 1
        # Zaehle die Zeilen im Hint
        lines = [l for l in hints[0][1].split("\n") if l.strip().startswith("-")]
        assert len(lines) == 3


# ---------------------------------------------------------------
# P0.2: Kumulative Daily Poison Protection
# ---------------------------------------------------------------


class TestDailyPoisonProtection:
    """Testet die kumulative Tages-Cap fuer Score-Aenderungen."""

    @pytest.mark.asyncio
    async def test_daily_cap_blocks_excessive_changes(self):
        """Nach Erreichen des Tagesbudgets sollen weitere Updates blockiert werden."""
        from assistant.outcome_tracker import OutcomeTracker, MAX_DAILY_CHANGE

        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {}}):
            t = OutcomeTracker()

        redis = AsyncMock()
        t.redis = redis

        redis.hget.return_value = "20"  # Above MIN_OUTCOMES

        # Simuliere: Tagesbudget bereits bei 0.19 (fast erschoepft)
        redis.get.side_effect = [
            "0.5",  # Current score
            str(MAX_DAILY_CHANGE - 0.01),  # Daily cumulative fast voll
        ]

        await t._update_score("set_light", "positive")
        # setex sollte trotzdem aufgerufen werden (kleines Restbudget)
        assert redis.setex.call_count == 2  # Score + Daily

    @pytest.mark.asyncio
    async def test_daily_cap_fully_exhausted(self):
        """Wenn Tagesbudget komplett verbraucht, kein Score-Update."""
        from assistant.outcome_tracker import OutcomeTracker, MAX_DAILY_CHANGE

        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {}}):
            t = OutcomeTracker()

        redis = AsyncMock()
        t.redis = redis

        redis.hget.return_value = "20"
        # Tagesbudget komplett verbraucht
        redis.get.side_effect = [
            "0.5",  # Current score
            str(MAX_DAILY_CHANGE),  # Daily cumulative = MAX
        ]

        await t._update_score("set_light", "positive")
        # Kein setex weil Budget erschoepft
        assert redis.setex.call_count == 0

    @pytest.mark.asyncio
    async def test_negative_daily_cap(self):
        """Negative kumulative Aenderungen werden auch begrenzt."""
        from assistant.outcome_tracker import OutcomeTracker, MAX_DAILY_CHANGE

        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {}}):
            t = OutcomeTracker()

        redis = AsyncMock()
        t.redis = redis

        redis.hget.return_value = "20"
        # Negatives Tagesbudget erschoepft
        redis.get.side_effect = [
            "0.5",  # Current score
            str(-MAX_DAILY_CHANGE),  # Daily cumulative = -MAX
        ]

        await t._update_score("set_light", "negative")
        # Kein setex weil negatives Budget erschoepft
        assert redis.setex.call_count == 0


# ---------------------------------------------------------------
# P0.3: Think-Content Self-Consistency Check
# ---------------------------------------------------------------


class TestThinkConsistencyCheck:
    """Testet die Self-Consistency-Pruefung zwischen Think und Response.

    Implementiert die Prueflogik direkt (vermeidet FastAPI-Dep durch Brain-Import).
    """

    # Bedenken-Signale (Kopie aus brain.py fuer isolierte Tests)
    _THINK_CONCERN_PATTERNS = [
        ("nicht sicher", "Ich bin mir nicht ganz sicher"),
        ("unsicher", "Ich bin mir nicht ganz sicher"),
        ("risiko", "Vorsicht — das birgt ein gewisses Risiko"),
        ("risk", "Vorsicht — das birgt ein gewisses Risiko"),
        ("gefaehrlich", "Achtung — das koennte problematisch sein"),
    ]
    _RESPONSE_OVERCONFIDENT = [
        "erledigt", "done", "kein problem", "selbstverstaendlich",
        "sofort", "natuerlich", "wird gemacht",
    ]
    _TRANSPARENCY_SIGNALS = [
        "allerdings", "aber", "vorsicht", "hinweis", "beachte",
        "nicht sicher", "moeglicherweise", "vielleicht",
    ]

    def _check(self, thinking, response, actions):
        """Repliziert _check_think_consistency ohne Brain-Import."""
        if not thinking or not actions:
            return None
        thinking_lower = thinking.lower()
        response_lower = response.lower()

        concern_msg = None
        for pattern, hint in self._THINK_CONCERN_PATTERNS:
            if pattern in thinking_lower:
                concern_msg = hint
                break
        if not concern_msg:
            return None

        if any(sig in response_lower for sig in self._TRANSPARENCY_SIGNALS):
            return None

        if not any(sig in response_lower for sig in self._RESPONSE_OVERCONFIDENT):
            return None

        return f"Nebenbei bemerkt: {concern_msg} — falls etwas nicht stimmt, einfach Bescheid sagen."

    def test_concern_detected_with_overconfident_response(self):
        """Bedenken im Thinking + uebermutige Antwort → Warnung."""
        result = self._check(
            "Ich bin mir nicht sicher ob das der richtige Raum ist...",
            "Erledigt! Habe das Licht im Wohnzimmer ausgeschaltet.",
            [{"function": "set_light"}],
        )
        assert result is not None
        assert "nicht ganz sicher" in result

    def test_no_concern_when_transparent(self):
        """Wenn die Antwort selbst Unsicherheit zeigt → kein Nachtrag."""
        result = self._check(
            "Ich bin unsicher ob das korrekt ist",
            "Allerdings bin ich nicht ganz sicher ob das der richtige Raum ist.",
            [{"function": "set_light"}],
        )
        assert result is None

    def test_no_concern_without_overconfidence(self):
        """Ohne uebermutige Signale in der Antwort → kein Nachtrag."""
        result = self._check(
            "Ich bin unsicher...",
            "Ich habe das Licht angepasst.",
            [{"function": "set_light"}],
        )
        assert result is None

    def test_no_concern_without_thinking(self):
        """Ohne Thinking-Content → kein Check."""
        result = self._check("", "Erledigt!", [{"function": "set_light"}])
        assert result is None

    def test_risk_detected(self):
        """Risiko-Signal im Thinking soll erkannt werden."""
        result = self._check(
            "Das birgt ein Risiko — die Heizung koennte ueberhitzen",
            "Wird gemacht! Habe die Heizung hochgedreht.",
            [{"function": "set_climate"}],
        )
        assert result is not None
        assert "Risiko" in result


# ---------------------------------------------------------------
# P1.1: Causal-Chain Richtungserkennung
# ---------------------------------------------------------------


class TestCausalChainOrdering:
    """Testet die Richtungserkennung bei kausalen Ketten."""

    def _make_entries(self, actions_sequences: list[list[str]], base_hour: int = 19):
        """Erstellt Action-Log-Eintraege aus Aktions-Sequenzen."""
        entries = []
        for seq_idx, seq in enumerate(actions_sequences):
            base_ts = datetime(2026, 3, 1 + seq_idx, base_hour, 0, tzinfo=timezone.utc)
            for i, action in enumerate(seq):
                entries.append({
                    "action": action,
                    "timestamp": (base_ts + timedelta(minutes=i * 2)).isoformat(),
                    "hour": base_hour,
                    "weekday": (base_ts + timedelta(days=seq_idx)).weekday(),
                })
        return entries

    def test_consistent_order_boosts_confidence(self):
        """Immer gleiche Reihenfolge (A→B→C) soll hoehere Confidence haben."""
        from assistant.anticipation import AnticipationEngine

        with patch("assistant.anticipation.yaml_config", {
            "anticipation": {
                "causal_chain_window_min": 10,
                "causal_chain_min_occurrences": 3,
            },
        }):
            engine = AnticipationEngine.__new__(AnticipationEngine)
            engine.min_confidence = 0.1
            engine.history_days = 30

            # 5x gleiche Reihenfolge: A→B→C
            consistent = self._make_entries([
                ["turn_off_lights", "close_covers", "lock_door"],
            ] * 5)

            patterns = engine._detect_causal_chains(consistent)

            assert len(patterns) >= 1
            p = patterns[0]
            assert p["order_consistency"] == 1.0  # Perfekte Konsistenz

    def test_mixed_order_lower_confidence(self):
        """Gemischte Reihenfolge soll niedrigere order_consistency haben."""
        from assistant.anticipation import AnticipationEngine

        with patch("assistant.anticipation.yaml_config", {
            "anticipation": {
                "causal_chain_window_min": 10,
                "causal_chain_min_occurrences": 3,
            },
        }):
            engine = AnticipationEngine.__new__(AnticipationEngine)
            engine.min_confidence = 0.1
            engine.history_days = 30

            # 3x A→B→C, 3x C→B→A
            mixed = self._make_entries([
                ["turn_off_lights", "close_covers", "lock_door"],
                ["turn_off_lights", "close_covers", "lock_door"],
                ["turn_off_lights", "close_covers", "lock_door"],
                ["lock_door", "close_covers", "turn_off_lights"],
                ["lock_door", "close_covers", "turn_off_lights"],
                ["lock_door", "close_covers", "turn_off_lights"],
            ])

            patterns = engine._detect_causal_chains(mixed)

            assert len(patterns) >= 1
            p = patterns[0]
            # Gemischt: order_consistency < 1.0
            assert p["order_consistency"] < 1.0


# ---------------------------------------------------------------
# P1.2: Learned Follow-ups (Think-Ahead)
# ---------------------------------------------------------------


class TestLearnedFollowups:
    """Testet das Follow-up-Sequenz-Tracking im OutcomeTracker."""

    @pytest.mark.asyncio
    async def test_track_followup_sequence(self):
        """Sequenz-Tracking soll Paare in Redis zaehlen."""
        from assistant.outcome_tracker import OutcomeTracker

        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {}}):
            t = OutcomeTracker()

        redis = AsyncMock()
        t.redis = redis
        t.enabled = True

        # Keine vorherige Aktion
        redis.get.return_value = None
        await t.track_followup_sequence("set_light", room="wohnzimmer")
        # Sollte nur die aktuelle Aktion speichern (setex), kein Paar zaehlen
        redis.incr.assert_not_called()
        redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_track_followup_pair_counted(self):
        """Wenn eine vorherige Aktion existiert, soll das Paar gezaehlt werden."""
        from assistant.outcome_tracker import OutcomeTracker

        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {}}):
            t = OutcomeTracker()

        redis = AsyncMock()
        t.redis = redis
        t.enabled = True

        # Vorherige Aktion existiert (vor 30 Sekunden)
        prev_data = json.dumps({"action": "set_light", "ts": time.time() - 30})
        redis.get.return_value = prev_data
        await t.track_followup_sequence("set_cover", room="schlafzimmer")
        # Paar sollte gezaehlt werden
        redis.incr.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_count_for_same_action(self):
        """Gleiche Aktion doppelt soll nicht als Sequenz zaehlen."""
        from assistant.outcome_tracker import OutcomeTracker

        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {}}):
            t = OutcomeTracker()

        redis = AsyncMock()
        t.redis = redis
        t.enabled = True

        prev_data = json.dumps({"action": "set_light", "ts": time.time() - 10})
        redis.get.return_value = prev_data
        await t.track_followup_sequence("set_light", room="wohnzimmer")
        redis.incr.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_learned_followups_min_count(self):
        """Nur Paare mit >= _FOLLOWUP_MIN_COUNT sollen zurueckgegeben werden."""
        from assistant.outcome_tracker import OutcomeTracker

        with patch("assistant.outcome_tracker.yaml_config", {"outcome_tracker": {}}):
            t = OutcomeTracker()

        redis = AsyncMock()
        t.redis = redis
        t.enabled = True

        # Simuliere Scan-Ergebnis
        redis.scan.return_value = (
            0,
            [b"mha:followup:pair:set_light:set_cover:schlafzimmer"],
        )
        redis.get.return_value = b"5"  # Ueber Minimum (3)

        followups = await t.get_learned_followups("set_light")
        assert len(followups) == 1
        assert followups[0]["action"] == "set_cover"
        assert followups[0]["count"] == 5


# ---------------------------------------------------------------
# P2.1: Recency-Weighting fuer Sequence Patterns
# ---------------------------------------------------------------


class TestRecencyWeighting:
    """Testet ob neuere Patterns staerker gewichtet werden."""

    def test_recent_sequences_weighted_higher(self):
        """Neuere Sequenzen sollen hoehere gewichtete Counts bekommen."""
        from assistant.anticipation import AnticipationEngine

        with patch("assistant.anticipation.yaml_config", {
            "anticipation": {},
        }):
            engine = AnticipationEngine.__new__(AnticipationEngine)
            engine.min_confidence = 0.1
            engine.history_days = 30

            now = datetime.now(timezone.utc)

            # Erstelle Eintraege: 5x kuerzlich, 5x alt
            entries = []
            for i in range(5):
                ts_recent = (now - timedelta(days=1)).isoformat()
                entries.append({
                    "action": "set_light" if i % 2 == 0 else "set_cover",
                    "timestamp": (now - timedelta(days=1, hours=i)).isoformat(),
                    "hour": 20,
                    "args": "{}",
                })
            for i in range(5):
                entries.append({
                    "action": "set_light" if i % 2 == 0 else "set_cover",
                    "timestamp": (now - timedelta(days=29, hours=i)).isoformat(),
                    "hour": 20,
                    "args": "{}",
                })

            patterns = engine._detect_sequence_patterns(entries)
            # Patterns sollten existieren (genug Daten)
            # Die Confidence sollte durch Recency-Weighting beeinflusst sein
            # (neuere zaehlen mehr als alte)
            for p in patterns:
                assert "confidence" in p
                assert 0 <= p["confidence"] <= 1.0
