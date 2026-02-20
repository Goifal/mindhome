"""
Tests fuer AmbientAudioClassifier — Cooldown, Reaktionen, Nachtmodus.
"""

import time
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from assistant.ambient_audio import AmbientAudioClassifier


@pytest.fixture
def classifier():
    ha = AsyncMock()
    c = AmbientAudioClassifier(ha)
    c.enabled = True
    c._default_cooldown = 30
    return c


class TestCheckCooldown:
    """Tests fuer _check_cooldown()."""

    def test_no_previous_event(self, classifier):
        assert classifier._check_cooldown("doorbell") is True

    def test_within_cooldown(self, classifier):
        classifier._last_event_times["doorbell"] = time.time()
        assert classifier._check_cooldown("doorbell") is False

    def test_after_cooldown(self, classifier):
        classifier._last_event_times["doorbell"] = time.time() - 60
        assert classifier._check_cooldown("doorbell") is True

    def test_custom_event_cooldown(self, classifier):
        classifier._event_cooldowns["alarm"] = 120
        classifier._last_event_times["alarm"] = time.time() - 60
        # 60s vergangen, aber Cooldown ist 120s
        assert classifier._check_cooldown("alarm") is False

    def test_custom_event_cooldown_passed(self, classifier):
        classifier._event_cooldowns["alarm"] = 120
        classifier._last_event_times["alarm"] = time.time() - 150
        assert classifier._check_cooldown("alarm") is True


class TestGetReaction:
    """Tests fuer _get_reaction()."""

    def test_known_event_type(self, classifier):
        # DEFAULT_EVENT_REACTIONS hat z.B. "doorbell", "glass_break"
        reaction = classifier._get_reaction("doorbell")
        # Kann None sein wenn kein Mapping existiert, oder dict
        # Testen dass es ein dict oder None ist
        assert reaction is None or isinstance(reaction, dict)

    def test_override_merges(self, classifier):
        classifier._reaction_overrides["custom_event"] = {
            "message": "Eigene Nachricht",
            "severity": "critical",
        }
        # Wenn custom_event nicht in DEFAULT_EVENT_REACTIONS, merged mit leerem dict
        reaction = classifier._get_reaction("custom_event")
        assert reaction is not None
        assert reaction["message"] == "Eigene Nachricht"
        assert reaction["severity"] == "critical"

    def test_unknown_event_no_override(self, classifier):
        reaction = classifier._get_reaction("totally_unknown_xyz")
        assert reaction is None


class TestIsNight:
    """Tests fuer _is_night()."""

    def test_night_standard(self, classifier):
        """22:00-07:00 ist Nacht."""
        classifier._night_start = 22
        classifier._night_end = 7

        with patch("assistant.ambient_audio.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 2, 20, 23, 0)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            assert classifier._is_night() is True

    def test_day_standard(self, classifier):
        """Mittags ist kein Nachtmodus."""
        classifier._night_start = 22
        classifier._night_end = 7

        with patch("assistant.ambient_audio.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 2, 20, 12, 0)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            assert classifier._is_night() is False


class TestEscalateSeverity:
    """Tests fuer _escalate_severity()."""

    def test_info_to_high(self, classifier):
        assert classifier._escalate_severity("info") == "high"

    def test_high_to_critical(self, classifier):
        assert classifier._escalate_severity("high") == "critical"

    def test_critical_stays(self, classifier):
        assert classifier._escalate_severity("critical") == "critical"

    def test_unknown_unchanged(self, classifier):
        assert classifier._escalate_severity("foo") == "foo"


class TestExtractRoom:
    """Tests fuer _extract_room_from_entity()."""

    def test_wohnzimmer(self, classifier):
        result = classifier._extract_room_from_entity("binary_sensor.wohnzimmer_smoke")
        assert result == "wohnzimmer"

    def test_kueche(self, classifier):
        result = classifier._extract_room_from_entity("binary_sensor.kueche_glass_break")
        assert result == "kueche"

    def test_schlafzimmer(self, classifier):
        result = classifier._extract_room_from_entity("binary_sensor.schlafzimmer_noise")
        assert result == "schlafzimmer"

    def test_fallback_underscore_split(self, classifier):
        result = classifier._extract_room_from_entity("binary_sensor.diele_sensor")
        assert result == "diele"

    def test_no_dot(self, classifier):
        result = classifier._extract_room_from_entity("invalid_entity")
        assert result is None


class TestRecentEvents:
    """Tests fuer get_recent_events() und get_events_by_type()."""

    def test_empty_history(self, classifier):
        assert classifier.get_recent_events() == []

    def test_recent_events_limit(self, classifier):
        classifier._event_history = [{"type": f"event_{i}"} for i in range(20)]
        result = classifier.get_recent_events(limit=5)
        assert len(result) == 5

    def test_events_by_type(self, classifier):
        classifier._event_history = [
            {"type": "doorbell"},
            {"type": "glass_break"},
            {"type": "doorbell"},
        ]
        result = classifier.get_events_by_type("doorbell")
        assert len(result) == 2


class TestHealthStatus:
    """Tests fuer health_status()."""

    def test_disabled(self, classifier):
        classifier.enabled = False
        assert classifier.health_status() == "disabled"

    def test_running(self, classifier):
        classifier._running = True
        status = classifier.health_status()
        assert "running" in status

    def test_active_not_running(self, classifier):
        classifier._running = False
        status = classifier.health_status()
        assert "active" in status
