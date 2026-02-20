"""
Tests fuer ConflictResolver — Konflikterkennung, Recording, Labels.
"""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from assistant.conflict_resolver import ConflictResolver


@pytest.fixture
def resolver():
    autonomy = AsyncMock()
    ollama = AsyncMock()
    r = ConflictResolver(autonomy, ollama)
    r.enabled = True
    return r


class TestRecordCommand:
    """Tests fuer record_command()."""

    def test_records_command(self, resolver):
        resolver.record_command("Max", "set_light", {"brightness": 100}, "wohnzimmer")
        assert len(resolver._recent_commands["max"]) == 1
        cmd = resolver._recent_commands["max"][0]
        assert cmd["person"] == "max"
        assert cmd["function"] == "set_light"
        assert cmd["args"]["brightness"] == 100
        assert cmd["room"] == "wohnzimmer"

    def test_multiple_commands_same_person(self, resolver):
        resolver.record_command("Max", "set_light", {"brightness": 50})
        resolver.record_command("Max", "set_light", {"brightness": 100})
        assert len(resolver._recent_commands["max"]) == 2

    def test_different_persons(self, resolver):
        resolver.record_command("Max", "set_light", {"brightness": 50})
        resolver.record_command("Anna", "set_light", {"brightness": 100})
        assert len(resolver._recent_commands["max"]) == 1
        assert len(resolver._recent_commands["anna"]) == 1

    def test_disabled_no_record(self, resolver):
        resolver.enabled = False
        resolver.record_command("Max", "set_light", {"brightness": 50})
        assert len(resolver._recent_commands) == 0

    def test_empty_person_no_record(self, resolver):
        resolver.record_command("", "set_light", {"brightness": 50})
        assert len(resolver._recent_commands) == 0

    def test_ring_buffer_limit(self, resolver):
        resolver._max_commands = 3
        for i in range(5):
            resolver.record_command("Max", "set_light", {"brightness": i * 10})
        assert len(resolver._recent_commands["max"]) == 3


class TestDetectConflict:
    """Tests fuer _detect_conflict()."""

    def test_numeric_conflict(self, resolver):
        result = resolver._detect_conflict(
            "climate",
            {"temperature": 25},
            {"temperature": 19},
            {"threshold": 3},
        )
        assert result is not None
        assert result["type"] == "numeric"
        assert result["difference"] == 6

    def test_numeric_no_conflict_within_threshold(self, resolver):
        result = resolver._detect_conflict(
            "climate",
            {"temperature": 21},
            {"temperature": 22},
            {"threshold": 3},
        )
        assert result is None

    def test_categorical_conflict(self, resolver):
        result = resolver._detect_conflict(
            "light",
            {"state": "on"},
            {"state": "off"},
            {},
        )
        assert result is not None
        assert result["type"] == "categorical"

    def test_categorical_no_conflict_same(self, resolver):
        result = resolver._detect_conflict(
            "light",
            {"state": "on"},
            {"state": "on"},
            {},
        )
        assert result is None


class TestCheckConflict:
    """Tests fuer check_conflict()."""

    @pytest.mark.asyncio
    async def test_no_conflict_same_person(self, resolver):
        resolver.record_command("Max", "set_light", {"state": "on"})
        result = await resolver.check_conflict("Max", "set_light", {"state": "off"})
        assert result is None

    @pytest.mark.asyncio
    async def test_no_conflict_disabled(self, resolver):
        resolver.enabled = False
        result = await resolver.check_conflict("Max", "set_light", {"state": "on"})
        assert result is None

    @pytest.mark.asyncio
    async def test_no_conflict_unknown_function(self, resolver):
        resolver.record_command("Anna", "play_sound", {"sound": "chime"})
        result = await resolver.check_conflict("Max", "play_sound", {"sound": "ding"})
        # play_sound ist keine ueberwachte Domain
        assert result is None


class TestDomainLabel:
    """Tests fuer _domain_label()."""

    def test_light(self, resolver):
        assert resolver._domain_label("light") == "das Licht"

    def test_media(self, resolver):
        assert resolver._domain_label("media") == "die Musik"

    def test_cover(self, resolver):
        assert resolver._domain_label("cover") == "die Rolladen"

    def test_unknown(self, resolver):
        assert resolver._domain_label("xyz") == "xyz"


class TestDescribeAction:
    """Tests fuer _describe_action()."""

    def test_climate_temperature(self, resolver):
        result = resolver._describe_action("climate", {"temperature": 22})
        assert "22" in result
        assert "°C" in result

    def test_light_state(self, resolver):
        result = resolver._describe_action("light", {"state": "on"})
        assert "on" in result

    def test_light_brightness(self, resolver):
        result = resolver._describe_action("light", {"brightness": 80})
        assert "80" in result

    def test_cover_position(self, resolver):
        result = resolver._describe_action("cover", {"position": 50})
        assert "50" in result

    def test_unknown_domain(self, resolver):
        result = resolver._describe_action("xyz", {})
        assert "entsprechend" in result


class TestHealthStatus:
    """Tests fuer health_status()."""

    def test_enabled_status(self, resolver):
        status = resolver.health_status()
        assert isinstance(status, str)

    def test_disabled_status(self, resolver):
        resolver.enabled = False
        status = resolver.health_status()
        assert "disabled" in status.lower()
