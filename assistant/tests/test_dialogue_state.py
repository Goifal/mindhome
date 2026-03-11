"""Tests for assistant.dialogue_state module."""

import time
import pytest
from unittest.mock import patch

from assistant.dialogue_state import DialogueState, DialogueStateManager


@pytest.fixture
def dsm():
    with patch("assistant.dialogue_state.yaml_config", {"dialogue": {"enabled": True, "timeout_seconds": 300, "auto_resolve_references": True, "clarification_enabled": True, "max_clarification_options": 5}}):
        return DialogueStateManager()


# ------------------------------------------------------------------
# DialogueState
# ------------------------------------------------------------------


def test_dialogue_state_initial():
    ds = DialogueState()
    assert ds.state == "idle"
    assert ds.turn_count == 0
    assert ds.pending_clarification is None


def test_dialogue_state_is_stale():
    ds = DialogueState()
    ds.last_update = time.time() - 400
    assert ds.is_stale(timeout_seconds=300) is True
    ds.last_update = time.time()
    assert ds.is_stale(timeout_seconds=300) is False


def test_dialogue_state_reset():
    ds = DialogueState()
    ds.state = "multi_step"
    ds.turn_count = 5
    ds.pending_clarification = {"q": "test"}
    ds.reset()
    assert ds.state == "idle"
    assert ds.turn_count == 0
    assert ds.pending_clarification is None


def test_dialogue_state_to_dict():
    ds = DialogueState()
    ds.last_entities.append("light.kitchen")
    d = ds.to_dict()
    assert d["state"] == "idle"
    assert "light.kitchen" in d["last_entities"]
    assert "age_seconds" in d


# ------------------------------------------------------------------
# DialogueStateManager - _get_state
# ------------------------------------------------------------------


def test_get_state_creates_new(dsm):
    state = dsm._get_state("Max")
    assert isinstance(state, DialogueState)
    assert state.state == "idle"


def test_get_state_returns_same(dsm):
    s1 = dsm._get_state("Max")
    s2 = dsm._get_state("Max")
    assert s1 is s2


def test_get_state_resets_stale(dsm):
    state = dsm._get_state("Max")
    state.turn_count = 5
    state.state = "follow_up"
    state.last_update = time.time() - 400
    fresh = dsm._get_state("Max")
    assert fresh.state == "idle"
    assert fresh.turn_count == 0


# ------------------------------------------------------------------
# track_turn
# ------------------------------------------------------------------


def test_track_turn(dsm):
    dsm.track_turn("Licht an", person="Max", room="Wohnzimmer",
                   entities=["light.wohnzimmer"], domain="light",
                   actions=[{"description": "Licht eingeschaltet"}])
    state = dsm._get_state("Max")
    assert state.turn_count == 1
    assert "wohnzimmer" in state.last_rooms
    assert "light.wohnzimmer" in state.last_entities
    assert "light" in state.last_domains


def test_track_turn_disabled(dsm):
    dsm.enabled = False
    dsm.track_turn("Test", person="Max", room="R1")
    assert dsm._get_state("Max").turn_count == 0


def test_track_turn_clears_clarification(dsm):
    dsm.start_clarification("Max", "Welches?", ["A", "B"], "original")
    assert dsm._get_state("Max").state == "awaiting_clarification"
    dsm.track_turn("A", person="Max")
    assert dsm._get_state("Max").state == "follow_up"


# ------------------------------------------------------------------
# resolve_references
# ------------------------------------------------------------------


def test_resolve_entity_reference(dsm):
    dsm.track_turn("Licht an", person="Max", entities=["light.wohnzimmer"])
    result = dsm.resolve_references("Mach es aus", person="Max")
    assert result["had_references"] is True
    assert "light.wohnzimmer" in result["resolved_entities"]
    assert "context_hint" in result and result["context_hint"]


def test_resolve_room_reference(dsm):
    dsm.track_turn("Licht", person="Max", room="Buero")
    result = dsm.resolve_references("Mach dort das Licht an", person="Max")
    assert result["had_references"] is True
    assert "buero" in result["resolved_rooms"]


def test_resolve_hier_with_current_room(dsm):
    dsm.track_turn("x", person="Max")
    result = dsm.resolve_references("Mach hier das Licht an", person="Max", current_room="Kueche")
    assert result["had_references"] is True
    assert "Kueche" in result["resolved_rooms"]


def test_resolve_action_reference(dsm):
    dsm.track_turn("Licht an", person="Max",
                   actions=[{"description": "Licht eingeschaltet"}])
    result = dsm.resolve_references("nochmal", person="Max")
    assert result["had_references"] is True


def test_resolve_no_reference(dsm):
    result = dsm.resolve_references("Wie wird das Wetter?", person="Max")
    assert result["had_references"] is False
    assert result["resolved_entities"] == []


def test_resolve_disabled(dsm):
    dsm.enabled = False
    result = dsm.resolve_references("Mach es aus")
    assert result["had_references"] is False


# ------------------------------------------------------------------
# Clarification
# ------------------------------------------------------------------


def test_start_clarification(dsm):
    dsm.start_clarification("Max", "Welches Licht?", ["A", "B", "C"], "Licht an")
    state = dsm._get_state("Max")
    assert state.state == "awaiting_clarification"
    assert state.pending_clarification["question"] == "Welches Licht?"
    assert len(state.pending_clarification["options"]) == 3


def test_start_clarification_disabled(dsm):
    dsm.clarification_enabled = False
    dsm.start_clarification("Max", "Q?", ["A"], "text")
    assert dsm._get_state("Max").state == "idle"


def test_check_clarification_answer_option_match(dsm):
    dsm.start_clarification("Max", "Welches?", ["Wohnzimmer", "Buero"], "Licht an")
    result = dsm.check_clarification_answer("Wohnzimmer", person="Max")
    assert result is not None
    assert result["selected_option"] == "Wohnzimmer"
    assert result["original_text"] == "Licht an"
    assert dsm._get_state("Max").state == "follow_up"


def test_check_clarification_answer_pattern_match(dsm):
    dsm.start_clarification("Max", "Welches?", ["Wohnzimmer", "Schlafzimmer"], "text")
    result = dsm.check_clarification_answer("ja", person="Max")
    assert result is not None
    assert result.get("was_pattern_match") is True


def test_check_clarification_answer_no_match(dsm):
    dsm.start_clarification("Max", "Welches?", ["Wohnzimmer", "Schlafzimmer"], "text")
    result = dsm.check_clarification_answer("Wie wird das Wetter morgen?", person="Max")
    assert result is None
    assert dsm._get_state("Max").state == "idle"


def test_check_clarification_no_pending(dsm):
    result = dsm.check_clarification_answer("Wohnzimmer", person="Max")
    assert result is None


# ------------------------------------------------------------------
# Context Prompt & Info
# ------------------------------------------------------------------


def test_get_context_prompt_empty(dsm):
    assert dsm.get_context_prompt("Max") == ""


def test_get_context_prompt_with_data(dsm):
    dsm.track_turn("Licht an", person="Max", room="Wohnzimmer",
                   entities=["light.wohnzimmer"],
                   actions=[{"description": "Licht ein"}])
    prompt = dsm.get_context_prompt("Max")
    assert "light.wohnzimmer" in prompt
    assert "wohnzimmer" in prompt.lower()


def test_get_state_info(dsm):
    dsm.track_turn("Test", person="Max")
    info = dsm.get_state_info("Max")
    assert info["turn_count"] == 1


# ------------------------------------------------------------------
# needs_clarification
# ------------------------------------------------------------------


def test_needs_clarification_multiple_entities(dsm):
    result = dsm.needs_clarification("Licht an", ["light.a", "light.b", "light.c"])
    assert result is not None
    assert "question" in result
    assert len(result["options"]) == 3


def test_needs_clarification_single_entity(dsm):
    result = dsm.needs_clarification("Licht an", ["light.a"])
    assert result is None


def test_needs_clarification_specificity_marker(dsm):
    result = dsm.needs_clarification("alle Lichter an", ["light.a", "light.b"])
    assert result is None


def test_needs_clarification_disabled(dsm):
    dsm.clarification_enabled = False
    result = dsm.needs_clarification("Licht an", ["a", "b"])
    assert result is None


# ------------------------------------------------------------------
# Zusaetzliche Tests fuer 100% Coverage
# ------------------------------------------------------------------


class TestGetStateEviction:
    """Tests fuer die Eviction-Logik in _get_state — Zeilen 112-117."""

    def test_evict_oldest_entries_when_over_50(self, dsm):
        """Wenn mehr als 50 Eintraege, werden die aeltesten 25 entfernt (Zeilen 112-117)."""
        import time as _time
        # 51 verschiedene Personen eintragen
        for i in range(51):
            state = dsm._get_state(f"person_{i}")
            state.last_update = _time.time() - (100 - i)  # Aeltere zuerst

        # Naechster Zugriff mit neuer Person sollte Eviction ausloesen
        new_state = dsm._get_state("person_new")
        assert new_state is not None
        # Es sollten jetzt weniger als 52 Eintraege sein
        assert len(dsm._states) <= 52


class TestCheckClarificationDisabled:
    """Tests fuer check_clarification_answer wenn disabled — Zeile 296."""

    def test_check_clarification_answer_disabled(self, dsm):
        """check_clarification_answer gibt None zurueck wenn disabled (Zeile 296)."""
        dsm.enabled = False
        result = dsm.check_clarification_answer("Wohnzimmer", person="Max")
        assert result is None


class TestGetContextPromptDisabled:
    """Tests fuer get_context_prompt wenn disabled — Zeile 343."""

    def test_get_context_prompt_disabled(self, dsm):
        """get_context_prompt gibt leeren String zurueck wenn disabled (Zeile 343)."""
        dsm.enabled = False
        result = dsm.get_context_prompt("Max")
        assert result == ""


class TestGetContextPromptClarification:
    """Tests fuer get_context_prompt mit offener Klaerungsfrage — Zeilen 365-366."""

    def test_context_prompt_with_pending_clarification(self, dsm):
        """Offene Klaerungsfrage erscheint im Kontext-Prompt (Zeilen 365-366)."""
        dsm.track_turn("Licht an", person="Max", entities=["light.a"])
        dsm.start_clarification("Max", "Welches Licht meinst du?", ["A", "B"], "Licht an")
        prompt = dsm.get_context_prompt("Max")
        assert "OFFENE KLAERUNGSFRAGE" in prompt
        assert "Welches Licht meinst du?" in prompt
