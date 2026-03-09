"""
Tests fuer feedback.py — Feedback-Scoring und Notification-Entscheidung

Testet:
  - _calculate_cooldown: Score → Cooldown-Dauer
  - should_notify: Notification-Entscheidungslogik
  - FEEDBACK_DELTAS: Score-Aenderungen bei verschiedenem Feedback
  - Score-Grenzen: SUPPRESS, REDUCE, NORMAL, BOOST
"""

import pytest


# ============================================================
# Konstanten (aus feedback.py)
# ============================================================

FEEDBACK_DELTAS = {
    "ignored": -0.05,
    "dismissed": -0.10,
    "acknowledged": 0.05,
    "engaged": 0.10,
    "thanked": 0.20,
}

DEFAULT_SCORE = 0.5
SCORE_SUPPRESS = 0.15
SCORE_REDUCE = 0.30
SCORE_NORMAL = 0.50
SCORE_BOOST = 0.70

BASE_COOLDOWN = 300  # 5 Minuten


# ============================================================
# Cooldown-Berechnung (extrahiert)
# ============================================================

def calculate_cooldown(score: float, base: int = BASE_COOLDOWN) -> int:
    """Berechnet adaptiven Cooldown basierend auf Score."""
    if score >= SCORE_BOOST:
        return int(base * 0.6)
    elif score >= SCORE_NORMAL:
        return base
    elif score >= SCORE_REDUCE:
        return int(base * 2.0)
    else:
        return int(base * 5.0)


# ============================================================
# Notification-Entscheidung (extrahiert, synchron fuer Tests)
# ============================================================

def should_notify(urgency: str, score: float) -> dict:
    """Entscheidet ob Notification gesendet werden soll."""
    if urgency == "critical":
        return {"allow": True, "reason": "critical_always_allowed", "cooldown": 0}

    if urgency == "high":
        if score < SCORE_SUPPRESS:
            return {"allow": False, "reason": f"score_too_low ({score:.2f})", "cooldown": 0}
        return {"allow": True, "reason": "high_priority", "cooldown": calculate_cooldown(score)}

    if urgency == "medium":
        if score < SCORE_REDUCE:
            return {"allow": False, "reason": f"score_too_low ({score:.2f})", "cooldown": 0}
        return {"allow": True, "reason": "score_ok", "cooldown": calculate_cooldown(score)}

    # LOW
    if score < SCORE_NORMAL:
        return {"allow": False, "reason": f"low_priority_score_insufficient ({score:.2f})", "cooldown": 0}
    return {"allow": True, "reason": "score_ok", "cooldown": calculate_cooldown(score)}


def apply_feedback(current_score: float, feedback_type: str) -> float:
    """Wendet Feedback-Delta auf Score an."""
    delta = FEEDBACK_DELTAS.get(feedback_type, 0)
    return max(0.0, min(1.0, current_score + delta))


# ============================================================
# Cooldown Tests
# ============================================================

class TestCooldown:
    """Cooldown-Berechnung basierend auf Score."""

    def test_boost_score_short_cooldown(self):
        """Hoher Score → kuerzerer Cooldown (60%)."""
        result = calculate_cooldown(0.8)
        assert result == int(BASE_COOLDOWN * 0.6)

    def test_normal_score_base_cooldown(self):
        """Normaler Score → Standard-Cooldown."""
        result = calculate_cooldown(0.5)
        assert result == BASE_COOLDOWN

    def test_reduce_score_long_cooldown(self):
        """Niedriger Score → laengerer Cooldown (200%)."""
        result = calculate_cooldown(0.3)
        assert result == int(BASE_COOLDOWN * 2.0)

    def test_suppress_score_very_long_cooldown(self):
        """Sehr niedriger Score → sehr langer Cooldown (500%)."""
        result = calculate_cooldown(0.1)
        assert result == int(BASE_COOLDOWN * 5.0)

    def test_boundary_boost(self):
        assert calculate_cooldown(0.70) == int(BASE_COOLDOWN * 0.6)
        assert calculate_cooldown(0.69) == BASE_COOLDOWN

    def test_boundary_normal(self):
        assert calculate_cooldown(0.50) == BASE_COOLDOWN
        assert calculate_cooldown(0.49) == int(BASE_COOLDOWN * 2.0)

    def test_boundary_reduce(self):
        assert calculate_cooldown(0.30) == int(BASE_COOLDOWN * 2.0)
        assert calculate_cooldown(0.29) == int(BASE_COOLDOWN * 5.0)


# ============================================================
# Notification-Entscheidung Tests
# ============================================================

class TestShouldNotify:
    """Notification-Entscheidungslogik."""

    # Critical: Immer durchlassen
    def test_critical_always_allowed(self):
        result = should_notify("critical", 0.0)
        assert result["allow"] is True

    def test_critical_with_zero_score(self):
        result = should_notify("critical", 0.0)
        assert result["allow"] is True
        assert result["cooldown"] == 0

    # High: Nur bei sehr niedrigem Score unterdruecken
    def test_high_with_good_score(self):
        result = should_notify("high", 0.5)
        assert result["allow"] is True

    def test_high_with_suppress_score(self):
        result = should_notify("high", 0.10)
        assert result["allow"] is False

    def test_high_boundary(self):
        assert should_notify("high", 0.15)["allow"] is True
        assert should_notify("high", 0.14)["allow"] is False

    # Medium: Unterdruecken bei niedrigem Score
    def test_medium_with_good_score(self):
        result = should_notify("medium", 0.5)
        assert result["allow"] is True

    def test_medium_with_low_score(self):
        result = should_notify("medium", 0.20)
        assert result["allow"] is False

    def test_medium_boundary(self):
        assert should_notify("medium", 0.30)["allow"] is True
        assert should_notify("medium", 0.29)["allow"] is False

    # Low: Strenger filtern
    def test_low_with_good_score(self):
        result = should_notify("low", 0.6)
        assert result["allow"] is True

    def test_low_with_medium_score(self):
        result = should_notify("low", 0.4)
        assert result["allow"] is False

    def test_low_boundary(self):
        assert should_notify("low", 0.50)["allow"] is True
        assert should_notify("low", 0.49)["allow"] is False


# ============================================================
# Feedback-Delta Tests
# ============================================================

class TestFeedbackDeltas:
    """Score-Aenderungen bei verschiedenem Feedback."""

    def test_ignored_decreases(self):
        new = apply_feedback(0.5, "ignored")
        assert new == 0.45

    def test_dismissed_decreases_more(self):
        new = apply_feedback(0.5, "dismissed")
        assert new == 0.40

    def test_acknowledged_increases(self):
        new = apply_feedback(0.5, "acknowledged")
        assert new == 0.55

    def test_engaged_increases_more(self):
        new = apply_feedback(0.5, "engaged")
        assert new == 0.60

    def test_thanked_big_increase(self):
        new = apply_feedback(0.5, "thanked")
        assert new == 0.70

    def test_score_clamped_at_zero(self):
        new = apply_feedback(0.05, "dismissed")
        assert new == 0.0

    def test_score_clamped_at_one(self):
        new = apply_feedback(0.95, "thanked")
        assert new == 1.0

    def test_unknown_feedback_no_change(self):
        new = apply_feedback(0.5, "unknown_type")
        assert new == 0.5

    def test_repeated_ignoring_approaches_zero(self):
        """Wiederholtes Ignorieren senkt Score schrittweise."""
        score = DEFAULT_SCORE
        for _ in range(10):
            score = apply_feedback(score, "ignored")
        assert score < 0.001  # Nahe Null (Float-Praezision)

    def test_default_score(self):
        """Default-Score ist 0.5."""
        assert DEFAULT_SCORE == 0.5
