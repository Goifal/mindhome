"""
Tests fuer Feature 8: Lern-Transparenz (learning_observer reports).
"""
import json
import pytest
from unittest.mock import AsyncMock

from assistant.learning_observer import LearningObserver


class TestGetLearningReport:
    """Tests fuer get_learning_report()."""

    @pytest.fixture
    def observer(self, redis_mock):
        """LearningObserver mit Redis-Mock."""
        obs = LearningObserver()
        obs.redis = redis_mock
        return obs

    @pytest.mark.asyncio
    async def test_empty_report(self, observer):
        """Leerer Report bei keinen Daten."""
        observer.redis.llen = AsyncMock(return_value=0)
        observer.redis.lrange = AsyncMock(return_value=[])
        observer.get_learned_patterns = AsyncMock(return_value=[])
        report = await observer.get_learning_report()
        assert report["total_observations"] == 0
        assert report["patterns"] == []
        assert report["suggestions_made"] == 0

    @pytest.mark.asyncio
    async def test_report_with_observations(self, observer):
        """Report mit Beobachtungen."""
        observer.redis.llen = AsyncMock(return_value=50)
        observer.redis.lrange = AsyncMock(return_value=[
            json.dumps({"accepted": True}).encode(),
            json.dumps({"accepted": False}).encode(),
            json.dumps({"accepted": True}).encode(),
        ])
        observer.get_learned_patterns = AsyncMock(return_value=[
            {"entity": "light.wz", "time_slot": "08", "count": 5, "weekday": -1, "action": "on"},
        ])
        report = await observer.get_learning_report()
        assert report["total_observations"] == 50
        assert report["suggestions_made"] == 3
        assert report["accepted"] == 2
        assert report["declined"] == 1
        assert len(report["patterns"]) == 1

    @pytest.mark.asyncio
    async def test_report_no_redis(self, observer):
        """Ohne Redis gibt Default-Report zurueck."""
        observer.redis = None
        report = await observer.get_learning_report()
        assert report["total_observations"] == 0
        assert report["patterns"] == []


class TestFormatLearningReport:
    """Tests fuer format_learning_report()."""

    @pytest.fixture
    def observer(self):
        return LearningObserver()

    def test_empty_report_message(self, observer):
        """Leerer Report gibt passende Meldung."""
        report = {
            "patterns": [],
            "total_observations": 0,
            "suggestions_made": 0,
            "accepted": 0,
            "declined": 0,
        }
        result = observer.format_learning_report(report)
        assert "keine" in result.lower() or "noch" in result.lower()

    def test_report_with_patterns(self, observer):
        """Report mit Mustern zeigt sie an."""
        report = {
            "patterns": [
                {"entity": "light.wohnzimmer", "time_slot": "08", "count": 5, "weekday": -1, "action": "on"},
                {"entity": "light.schlafzimmer", "time_slot": "22", "count": 3, "weekday": 0, "action": "off"},
            ],
            "total_observations": 100,
            "suggestions_made": 5,
            "accepted": 3,
            "declined": 2,
        }
        result = observer.format_learning_report(report)
        assert "100" in result
        assert "Wohnzimmer" in result or "wohnzimmer" in result.lower()
        assert "08" in result
        assert "taeglich" in result.lower() or "täglich" in result.lower()

    def test_report_weekday_pattern(self, observer):
        """Wochentags-Muster wird mit Tagesname angezeigt."""
        report = {
            "patterns": [
                {"entity": "light.wz", "time_slot": "08", "count": 3, "weekday": 0, "action": "on"},
            ],
            "total_observations": 10,
            "suggestions_made": 0,
            "accepted": 0,
            "declined": 0,
        }
        result = observer.format_learning_report(report)
        # Montag (weekday 0)
        assert "Montag" in result

    def test_report_entity_friendly_name(self, observer):
        """Entity-ID wird zu lesbarem Namen konvertiert."""
        report = {
            "patterns": [
                {"entity": "light.schlaf_zimmer_lampe", "time_slot": "22", "count": 4, "weekday": -1, "action": "off"},
            ],
            "total_observations": 20,
            "suggestions_made": 0,
            "accepted": 0,
            "declined": 0,
        }
        result = observer.format_learning_report(report)
        # Underscores werden zu Spaces, Title Case
        assert "Schlaf" in result or "schlaf" in result.lower()

    def test_suggestions_line_only_if_present(self, observer):
        """Vorschlaege-Zeile nur wenn Vorschlaege > 0."""
        report_no_suggestions = {
            "patterns": [{"entity": "light.wz", "time_slot": "08", "count": 3, "weekday": -1, "action": "on"}],
            "total_observations": 10,
            "suggestions_made": 0,
            "accepted": 0,
            "declined": 0,
        }
        result = observer.format_learning_report(report_no_suggestions)
        assert "akzeptiert" not in result.lower()

    def test_max_10_patterns(self, observer):
        """Maximal 10 Muster werden angezeigt."""
        patterns = [
            {"entity": f"light.room{i}", "time_slot": f"{8+i:02d}", "count": 10-i, "weekday": -1, "action": "on"}
            for i in range(15)
        ]
        report = {
            "patterns": patterns,
            "total_observations": 100,
            "suggestions_made": 0,
            "accepted": 0,
            "declined": 0,
        }
        result = observer.format_learning_report(report)
        # Zaehle Muster-Zeilen (beginnen mit "- ")
        pattern_lines = [l for l in result.split("\n") if l.strip().startswith("- ")]
        assert len(pattern_lines) <= 10
