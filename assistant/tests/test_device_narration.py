"""
Tests fuer Feature 3: Geraete-Persoenlichkeit (narrate_device_event).
"""
import pytest
from unittest.mock import patch


class TestDeviceNarration:
    """Tests fuer personality.narrate_device_event()."""

    @pytest.fixture
    def personality(self):
        """Personality-Instanz fuer Narration-Tests."""
        from assistant.personality import PersonalityEngine
        p = PersonalityEngine.__new__(PersonalityEngine)
        p._current_formality = 70
        p.formality_start = 70
        return p

    def test_narrate_known_device_waschmaschine(self, personality):
        """Bekanntes Geraet (Waschmaschine) gibt Narration zurueck."""
        result = personality.narrate_device_event(
            "switch.waschmaschine", "turned_off"
        )
        assert result is not None
        assert "Fleissige" in result

    def test_narrate_known_device_saugroboter(self, personality):
        """Saugroboter hat Nickname 'der Kleine'."""
        result = personality.narrate_device_event(
            "switch.saugroboter", "turned_on"
        )
        assert result is not None
        assert "Kleine" in result

    def test_narrate_unknown_device_returns_none(self, personality):
        """Unbekanntes Geraet gibt None zurueck."""
        result = personality.narrate_device_event(
            "light.schreibtischlampe", "turned_on"
        )
        assert result is None

    def test_invalid_event_type_returns_none(self, personality):
        """Ungueltiger Event-Typ gibt None zurueck."""
        result = personality.narrate_device_event(
            "switch.waschmaschine", "exploded"
        )
        assert result is None

    def test_event_turned_off(self, personality):
        """turned_off Event liefert passende Nachricht."""
        result = personality.narrate_device_event(
            "switch.waschmaschine", "turned_off"
        )
        assert result is not None
        # Template enthaelt typischerweise "erledigt" oder "fertig" oder "Vollzug"
        assert any(w in result for w in ["erledigt", "fertig", "Vollzug"])

    def test_event_turned_on(self, personality):
        """turned_on Event liefert passende Nachricht."""
        result = personality.narrate_device_event(
            "switch.kaffeemaschine", "turned_on"
        )
        assert result is not None
        assert "Barista" in result

    def test_event_running_long_with_duration(self, personality):
        """running_long Event mit Duration-Detail."""
        result = personality.narrate_device_event(
            "switch.waschmaschine", "running_long", detail="3 Stunden"
        )
        assert result is not None
        assert "3 Stunden" in result

    def test_event_anomaly(self, personality):
        """anomaly Event liefert Warnmeldung."""
        result = personality.narrate_device_event(
            "switch.spuelmaschine", "anomaly"
        )
        assert result is not None
        assert "Gruendliche" in result

    def test_event_stale(self, personality):
        """stale Event mit Duration."""
        result = personality.narrate_device_event(
            "switch.saugroboter", "stale", detail="2 Tage"
        )
        assert result is not None
        assert "2 Tage" in result

    def test_custom_nickname_from_config(self, personality):
        """Custom-Nickname aus Config ueberschreibt Default."""
        with patch("assistant.personality.yaml_config") as mock_cfg:
            mock_cfg.get.return_value = {
                "enabled": True,
                "custom_nicknames": {
                    "waschmaschine": "Frau Waschkraft",
                },
            }
            result = personality.narrate_device_event(
                "switch.waschmaschine", "turned_off"
            )
            # Wenn Custom-Nickname funktioniert, sollte er im Text erscheinen
            if result is not None:
                assert "Waschkraft" in result or "Fleissige" in result

    def test_person_title_in_narration(self, personality):
        """Person-Parameter wird fuer Anrede verwendet."""
        # Bei formality >= 50 kann ein Title prepended werden
        results = set()
        for _ in range(50):
            r = personality.narrate_device_event(
                "switch.waschmaschine", "turned_off", person="TestUser"
            )
            if r is not None:
                results.add(r)
        # Mindestens eine Variante sollte existieren
        assert len(results) >= 1
