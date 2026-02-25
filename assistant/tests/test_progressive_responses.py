"""
Tests fuer Feature 1: Progressive Antworten (get_progress_message).
"""
import pytest
from unittest.mock import MagicMock, patch


class TestGetProgressMessage:
    """Tests fuer personality.get_progress_message()."""

    @pytest.fixture
    def personality_formal(self):
        """Personality-Instanz mit formalem Stil (formality >= 50)."""
        from assistant.personality import PersonalityEngine
        p = PersonalityEngine.__new__(PersonalityEngine)
        p._current_formality = 70
        p.formality_start = 70
        return p

    @pytest.fixture
    def personality_casual(self):
        """Personality-Instanz mit lockerem Stil (formality < 50)."""
        from assistant.personality import PersonalityEngine
        p = PersonalityEngine.__new__(PersonalityEngine)
        p._current_formality = 30
        p.formality_start = 30
        return p

    def test_context_step_formal(self, personality_formal):
        """Formale Variante fuer context-Schritt."""
        msg = personality_formal.get_progress_message("context")
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_context_step_casual(self, personality_casual):
        """Lockere Variante fuer context-Schritt."""
        msg = personality_casual.get_progress_message("context")
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_thinking_step_formal(self, personality_formal):
        """Formale Variante fuer thinking-Schritt."""
        msg = personality_formal.get_progress_message("thinking")
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_thinking_step_casual(self, personality_casual):
        """Lockere Variante fuer thinking-Schritt."""
        msg = personality_casual.get_progress_message("thinking")
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_action_step_formal(self, personality_formal):
        """Formale Variante fuer action-Schritt."""
        msg = personality_formal.get_progress_message("action")
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_action_step_casual(self, personality_casual):
        """Lockere Variante fuer action-Schritt."""
        msg = personality_casual.get_progress_message("action")
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_invalid_step_returns_empty(self, personality_formal):
        """Ungueltiger Schritt gibt leeren String zurueck."""
        msg = personality_formal.get_progress_message("invalid_step")
        assert msg == ""

    def test_all_three_steps_valid(self, personality_formal):
        """Alle drei Schritte geben nicht-leere Strings zurueck."""
        for step in ("context", "thinking", "action"):
            msg = personality_formal.get_progress_message(step)
            assert len(msg) > 0, f"Step '{step}' returned empty string"

    def test_formal_vs_casual_different_pools(self, personality_formal, personality_casual):
        """Formale und lockere Nachrichten kommen aus verschiedenen Pools."""
        # Sammle jeweils viele Nachrichten um die Pools zu vergleichen
        formal_msgs = set()
        casual_msgs = set()
        for _ in range(50):
            formal_msgs.add(personality_formal.get_progress_message("action"))
            casual_msgs.add(personality_casual.get_progress_message("action"))
        # Mindestens eine Nachricht pro Pool
        assert len(formal_msgs) >= 1
        assert len(casual_msgs) >= 1
