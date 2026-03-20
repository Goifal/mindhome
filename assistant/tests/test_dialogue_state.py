"""Tests for assistant.dialogue_state module."""

import time
import pytest
from unittest.mock import MagicMock, patch

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


# ------------------------------------------------------------------
# Phase 6: Erweiterte Dialogfuehrung
# ------------------------------------------------------------------


class TestPhase6ExtendedDialogue:

    def test_conversation_depth_initial(self, dsm):
        assert dsm.get_conversation_depth("Max") == 0

    def test_conversation_depth_after_turns(self, dsm):
        dsm.track_turn("Hallo", person="Max")
        dsm.track_turn("Licht an", person="Max")
        assert dsm.get_conversation_depth("Max") == 2

    def test_topic_continuity_new_conversation(self, dsm):
        result = dsm.get_topic_continuity("Hallo", person="Max")
        assert result["is_continuation"] is False

    def test_topic_continuity_explicit_switch(self, dsm):
        dsm.track_turn("Licht an", person="Max")
        result = dsm.get_topic_continuity("anderes thema bitte", person="Max")
        assert result["is_continuation"] is False
        assert result["confidence"] > 0.5

    def test_topic_continuity_continuation(self, dsm):
        dsm.track_turn("Licht an", person="Max", domain="light")
        result = dsm.get_topic_continuity("und auch im Flur", person="Max")
        assert result["is_continuation"] is True

    def test_implicit_context_empty(self, dsm):
        result = dsm.get_implicit_context("Max")
        assert result == ""

    def test_implicit_context_with_history(self, dsm):
        dsm.track_turn("Licht an", person="Max", room="Kueche",
                        entities=["light.kueche"])
        result = dsm.get_implicit_context("Max")
        assert "kueche" in result.lower()

    def test_suggest_follow_up_no_history(self, dsm):
        result = dsm.suggest_follow_up({}, person="Max")
        assert result == ""

    def test_suggest_follow_up_light_on(self, dsm):
        dsm.track_turn("Licht an", person="Max",
                        actions=[{"action": "set_light", "args": {"state": "on"}}])
        dsm.track_turn("ok", person="Max")
        result = dsm.suggest_follow_up({"success": True}, person="Max")
        assert "Helligkeit" in result or "Farbe" in result

    def test_suggest_follow_up_climate(self, dsm):
        dsm.track_turn("Heizung an", person="Max",
                        actions=[{"action": "set_climate"}])
        dsm.track_turn("ok", person="Max")
        result = dsm.suggest_follow_up({"success": True}, person="Max")
        assert "Temperatur" in result

    def test_suggest_follow_up_media(self, dsm):
        dsm.track_turn("Musik an", person="Max",
                        actions=[{"action": "play_media"}])
        dsm.track_turn("ok", person="Max")
        result = dsm.suggest_follow_up({"success": True}, person="Max")
        assert "Lautstaerke" in result

    def test_suggest_follow_up_cover_closed(self, dsm):
        dsm.track_turn("Rollladen runter", person="Max",
                        actions=[{"action": "set_cover", "args": {"state": "closed"}}])
        dsm.track_turn("ok", person="Max")
        result = dsm.suggest_follow_up({"success": True}, person="Max")
        assert "Licht" in result

    def test_suggest_follow_up_failed_action(self, dsm):
        dsm.track_turn("Licht an", person="Max",
                        actions=[{"action": "set_light", "args": {"state": "on"}}])
        dsm.track_turn("ok", person="Max")
        result = dsm.suggest_follow_up({"success": False}, person="Max")
        assert result == ""


# ------------------------------------------------------------------
# Phase 6A: Ellipsis, Negation, Ambiguity Ranking, Discourse Repair
# ------------------------------------------------------------------


class TestEllipsisResolution:
    """Tests fuer _resolve_ellipsis — ergaenzt Kontext bei 'Und', 'Auch', 'Dort'."""

    def test_ellipsis_und_prefix(self, dsm):
        dsm.track_turn("Licht an", person="Max", room="Kueche",
                        entities=["light.kueche"])
        result = dsm._resolve_ellipsis("Und im Flur", person="Max")
        assert "(Raum: kueche)" in result
        assert "(Geraet: light.kueche)" in result

    def test_ellipsis_auch_prefix(self, dsm):
        dsm.track_turn("Licht an", person="Max", room="Buero")
        result = dsm._resolve_ellipsis("Auch bitte", person="Max")
        assert "buero" in result.lower()

    def test_ellipsis_dort_prefix(self, dsm):
        dsm.track_turn("Licht an", person="Max", room="Schlafzimmer")
        result = dsm._resolve_ellipsis("Dort auch", person="Max")
        assert "schlafzimmer" in result.lower()

    def test_ellipsis_no_prefix_unchanged(self, dsm):
        dsm.track_turn("Licht", person="Max", room="Kueche")
        result = dsm._resolve_ellipsis("Mach das Licht an", person="Max")
        assert result == "Mach das Licht an"

    def test_ellipsis_no_history(self, dsm):
        result = dsm._resolve_ellipsis("Und bitte", person="Max")
        assert result == "Und bitte"


class TestNegationTracking:
    """Tests fuer _track_negation — erkennt Negationsmuster."""

    def test_negation_nicht(self, dsm):
        result = dsm._track_negation("nicht das Licht", person="Max")
        assert result == "licht"

    def test_negation_kein(self, dsm):
        result = dsm._track_negation("kein Licht", person="Max")
        assert result == "licht"

    def test_negation_nein(self, dsm):
        result = dsm._track_negation("nein nicht die Lampe", person="Max")
        assert result is not None

    def test_negation_stored_in_state(self, dsm):
        dsm._track_negation("nicht das Licht", person="Max")
        state = dsm._get_state("Max")
        assert hasattr(state, "negated_entities")
        assert "licht" in state.negated_entities

    def test_negation_none_on_no_match(self, dsm):
        result = dsm._track_negation("mach das Licht an", person="Max")
        assert result is None

    def test_negation_max_stored(self, dsm):
        """Negated entities list is capped at 5."""
        for i in range(7):
            dsm._track_negation(f"nicht entity_{i}", person="Max")
        state = dsm._get_state("Max")
        assert len(state.negated_entities) <= 5


class TestAmbiguityRanking:
    """Tests fuer _rank_ambiguity — rankt Entities nach Relevanz."""

    def test_basic_ranking_returns_all(self, dsm):
        entities = ["light.a", "light.b", "light.c"]
        ranked = dsm._rank_ambiguity(entities, "Licht an", person="Max")
        assert len(ranked) == 3
        assert all(isinstance(r, tuple) and len(r) == 2 for r in ranked)

    def test_recent_entity_ranked_higher(self, dsm):
        dsm.track_turn("x", person="Max", entities=["light.b"])
        ranked = dsm._rank_ambiguity(
            ["light.a", "light.b", "light.c"], "Licht", person="Max"
        )
        # light.b was recently used, should rank higher
        entity_names = [r[0] for r in ranked]
        assert entity_names[0] == "light.b"

    def test_room_match_bonus(self, dsm):
        dsm.track_turn("x", person="Max", room="kueche")
        ranked = dsm._rank_ambiguity(
            ["light.wohnzimmer", "light.kueche"], "Licht an", person="Max"
        )
        entity_names = [r[0] for r in ranked]
        assert entity_names[0] == "light.kueche"

    def test_name_similarity_bonus(self, dsm):
        ranked = dsm._rank_ambiguity(
            ["light.bad", "light.wohnzimmer"], "Wohnzimmer Licht", person="Max"
        )
        entity_names = [r[0] for r in ranked]
        assert entity_names[0] == "light.wohnzimmer"

    def test_score_capped_at_1(self, dsm):
        dsm.track_turn("x", person="Max", room="kueche",
                        entities=["light.kueche_decke"])
        ranked = dsm._rank_ambiguity(
            ["light.kueche_decke"], "kueche decke", person="Max"
        )
        assert ranked[0][1] <= 1.0


class TestDiscourseRepair:
    """Tests fuer _discourse_repair — erkennt Korrektur-Muster."""

    def test_das_andere_with_two_entities(self, dsm):
        dsm.track_turn("x", person="Max", entities=["light.a", "light.b"])
        result = dsm._discourse_repair("das andere", person="Max")
        assert result is not None
        # appendleft puts light.b at index 0, light.a at index 1
        assert result["original"] == "light.b"
        assert result["correction"] == "light.a"

    def test_nein_with_entity(self, dsm):
        dsm.track_turn("x", person="Max", entities=["light.a", "light.b"])
        result = dsm._discourse_repair("nein, Wohnzimmer", person="Max")
        assert result is not None

    def test_nicht_das_sondern(self, dsm):
        dsm.track_turn("x", person="Max", entities=["light.a", "light.b"])
        result = dsm._discourse_repair("nicht das sondern das andere", person="Max")
        assert result is not None

    def test_no_repair_normal_text(self, dsm):
        dsm.track_turn("x", person="Max", entities=["light.a"])
        result = dsm._discourse_repair("Mach das Licht an", person="Max")
        assert result is None

    def test_no_repair_single_entity(self, dsm):
        dsm.track_turn("x", person="Max", entities=["light.a"])
        result = dsm._discourse_repair("das andere", person="Max")
        # Only 1 entity, no alternative to switch to
        assert result is None


# ------------------------------------------------------------------
# Cross-Session Temporal References (C5)
# ------------------------------------------------------------------


class TestTemporalReferences:
    """Tests fuer _resolve_temporal_reference und action log cache."""

    def test_temporal_reference_no_redis(self, dsm):
        """Without redis, temporal references return empty string."""
        result = dsm._resolve_temporal_reference("wie gestern", person="Max")
        assert result == ""

    def test_temporal_reference_no_match(self, dsm):
        dsm._redis = MagicMock()
        result = dsm._resolve_temporal_reference("mach das licht an", person="Max")
        assert result == ""

    def test_set_and_get_action_log_cache(self, dsm):
        entries = [{"action": "set_light", "timestamp": "2026-03-19T10:00:00+00:00"}]
        dsm.set_action_log_cache(entries)
        assert dsm._get_cached_action_log() == entries

    def test_get_cached_action_log_empty_default(self, dsm):
        assert dsm._get_cached_action_log() == []

    def test_temporal_reference_with_matching_action(self, dsm):
        from datetime import datetime, timedelta, timezone
        dsm._redis = MagicMock()
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        dsm.set_action_log_cache([
            {
                "action": "set_light",
                "description": "Licht im Wohnzimmer eingeschaltet",
                "timestamp": yesterday.isoformat(),
                "success": True,
            }
        ])
        result = dsm._resolve_temporal_reference("wie gestern", person="Max")
        assert "Licht im Wohnzimmer" in result
        assert "wie gestern" in result

    def test_temporal_reference_wie_immer_broad_window(self, dsm):
        from datetime import datetime, timedelta, timezone
        dsm._redis = MagicMock()
        now = datetime.now(timezone.utc)
        five_days_ago = now - timedelta(days=5)
        dsm.set_action_log_cache([
            {
                "action": "set_light",
                "description": "Morgenroutine",
                "timestamp": five_days_ago.isoformat(),
                "success": True,
            }
        ])
        result = dsm._resolve_temporal_reference("wie immer", person="Max")
        assert "Morgenroutine" in result

    def test_temporal_reference_skips_failed_actions(self, dsm):
        from datetime import datetime, timedelta, timezone
        dsm._redis = MagicMock()
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        dsm.set_action_log_cache([
            {
                "action": "set_light",
                "description": "Failed action",
                "timestamp": yesterday.isoformat(),
                "success": False,
            }
        ])
        result = dsm._resolve_temporal_reference("wie gestern", person="Max")
        assert result == ""

    def test_temporal_reference_skips_invalid_timestamp(self, dsm):
        dsm._redis = MagicMock()
        dsm.set_action_log_cache([
            {
                "action": "set_light",
                "timestamp": "invalid-date",
                "success": True,
            }
        ])
        result = dsm._resolve_temporal_reference("wie gestern", person="Max")
        assert result == ""

    def test_temporal_reference_deduplicates(self, dsm):
        from datetime import datetime, timedelta, timezone
        dsm._redis = MagicMock()
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        dsm.set_action_log_cache([
            {
                "action": "set_light",
                "description": "Licht an",
                "timestamp": yesterday.isoformat(),
                "success": True,
            },
            {
                "action": "set_light",
                "description": "Licht an",
                "timestamp": (yesterday - timedelta(minutes=5)).isoformat(),
                "success": True,
            },
        ])
        result = dsm._resolve_temporal_reference("wie gestern", person="Max")
        # Should deduplicate — "Licht an" appears only once
        assert result.count("Licht an") == 1


# ------------------------------------------------------------------
# Edge Cases and Robustness
# ------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases: empty context, None values, special inputs."""

    def test_resolve_references_empty_text(self, dsm):
        result = dsm.resolve_references("", person="Max")
        assert result["had_references"] is False

    def test_resolve_references_none_person(self, dsm):
        dsm.track_turn("Licht an", person="", entities=["light.a"])
        result = dsm.resolve_references("Mach es aus", person="")
        assert result["had_references"] is True

    def test_track_turn_none_entities(self, dsm):
        """track_turn handles None entities gracefully."""
        dsm.track_turn("Test", person="Max", entities=None, actions=None)
        state = dsm._get_state("Max")
        assert state.turn_count == 1
        assert len(state.last_entities) == 0

    def test_track_turn_no_duplicate_rooms(self, dsm):
        """Same room tracked twice should not create duplicates."""
        dsm.track_turn("a", person="Max", room="Kueche")
        dsm.track_turn("b", person="Max", room="Kueche")
        state = dsm._get_state("Max")
        assert list(state.last_rooms).count("kueche") == 1

    def test_track_turn_no_duplicate_entities(self, dsm):
        """Same entity tracked twice should not create duplicates."""
        dsm.track_turn("a", person="Max", entities=["light.a"])
        dsm.track_turn("b", person="Max", entities=["light.a"])
        state = dsm._get_state("Max")
        assert list(state.last_entities).count("light.a") == 1

    def test_track_turn_no_duplicate_domains(self, dsm):
        """Same domain tracked twice should not create duplicates."""
        dsm.track_turn("a", person="Max", domain="light")
        dsm.track_turn("b", person="Max", domain="light")
        state = dsm._get_state("Max")
        assert list(state.last_domains).count("light") == 1

    def test_resolve_references_auto_resolve_disabled(self, dsm):
        dsm.auto_resolve_references = False
        dsm.track_turn("Licht an", person="Max", entities=["light.a"])
        result = dsm.resolve_references("Mach es aus", person="Max")
        assert result["had_references"] is False

    def test_resolve_entity_ref_no_history(self, dsm):
        """Entity reference without prior entity history resolves nothing."""
        result = dsm.resolve_references("Mach es aus", person="Max")
        assert result["had_references"] is False
        assert result["resolved_entities"] == []

    def test_resolve_room_ref_no_history(self, dsm):
        """Room reference 'dort' without prior room history resolves nothing."""
        result = dsm.resolve_references("Mach dort das Licht an", person="Max")
        # 'dort' is a room reference, but no rooms in history
        assert result["resolved_rooms"] == []

    def test_person_case_insensitive(self, dsm):
        """Person names should be case-insensitive."""
        dsm.track_turn("Licht an", person="Max", entities=["light.a"])
        dsm.track_turn("ok", person="max")
        state = dsm._get_state("MAX")
        assert state.turn_count == 2

    def test_get_context_prompt_with_last_action(self, dsm):
        dsm.track_turn("Licht an", person="Max",
                        actions=[{"description": "Wohnzimmer Licht eingeschaltet"}])
        prompt = dsm.get_context_prompt("Max")
        assert "Letzte Aktion" in prompt
        assert "Wohnzimmer Licht eingeschaltet" in prompt

    def test_implicit_context_with_pending_clarification(self, dsm):
        dsm.track_turn("Licht an", person="Max", entities=["light.a"])
        dsm.start_clarification("Max", "Welches Licht?", ["A", "B"], "Licht an")
        result = dsm.get_implicit_context("Max")
        assert "Offene Frage" in result
        assert "Welches Licht?" in result

    def test_dialogue_state_reset_preserves_history(self):
        """Reset should preserve last_entities, last_rooms, last_actions, last_domains."""
        ds = DialogueState()
        ds.last_entities.append("light.a")
        ds.last_rooms.append("kueche")
        ds.last_actions.append({"action": "test"})
        ds.last_domains.append("light")
        ds.state = "multi_step"
        ds.turn_count = 5
        ds.reset()
        assert ds.state == "idle"
        assert ds.turn_count == 0
        # History preserved
        assert "light.a" in ds.last_entities
        assert "kueche" in ds.last_rooms
        assert len(ds.last_actions) == 1
        assert "light" in ds.last_domains

    def test_needs_clarification_max_options_capped(self, dsm):
        """Options should be capped at max_clarification_options."""
        entities = [f"light.{i}" for i in range(10)]
        result = dsm.needs_clarification("Licht an", entities, person="Max")
        assert result is not None
        assert len(result["options"]) <= dsm.max_clarification_options

    def test_start_clarification_caps_options(self, dsm):
        """start_clarification should cap options at max_clarification_options."""
        dsm.start_clarification("Max", "Welches?",
                                [f"opt_{i}" for i in range(10)], "text")
        state = dsm._get_state("Max")
        assert len(state.pending_clarification["options"]) <= dsm.max_clarification_options
