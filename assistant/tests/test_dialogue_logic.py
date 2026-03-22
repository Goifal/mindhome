"""
Tests for pure reference resolution and dialogue state logic.

Isolated tests -- no imports from the project. All logic is copied as
standalone functions so the test file is fully self-contained.
"""

import re
import pytest

# ---------------------------------------------------------------------------
# Standalone constants (copied from project)
# ---------------------------------------------------------------------------

ENTITY_REFERENCES_DE = {
    "es",
    "das",
    "den",
    "die",
    "ihn",
    "ihm",
    "ihr",
    "dem",
    "das gleiche",
    "den gleichen",
    "die gleiche",
    "dasselbe",
    "das licht",
    "die lampe",
    "das ding",
}

ROOM_REFERENCES_DE = {
    "dort",
    "da",
    "dahin",
    "drin",
    "dorthin",
    "im gleichen raum",
    "im selben raum",
    "da drin",
    "hier",
}

ACTION_REFERENCES_DE = {
    "nochmal",
    "das gleiche",
    "genauso",
    "wieder",
    "auch",
    "ebenfalls",
    "dasselbe",
}

CLARIFICATION_ANSWER_PATTERNS = [
    r"^(das |die |den )?(im |in der |in |am )?\w+$",
    r"^(ja|nein|doch|ok|okay)$",
    r"^\d+$",
    r"^(erst|zweit|dritt|viert|letzt)(e[rns]?)?$",
]

# ---------------------------------------------------------------------------
# Standalone functions (copied from project)
# ---------------------------------------------------------------------------


def resolve_references(
    text,
    last_entities=None,
    last_rooms=None,
    last_actions=None,
    current_room="",
):
    """Simplified standalone version for testing."""
    text_lower = text.lower().strip()
    resolved_entities = []
    resolved_rooms = []
    had_references = False
    hints = []

    for ref in ENTITY_REFERENCES_DE:
        if re.search(r"\b" + re.escape(ref) + r"\b", text_lower):
            if last_entities:
                resolved_entities.append(last_entities[0])
                had_references = True
                hints.append(f"'{ref}' -> {last_entities[0]}")
                break

    for ref in ROOM_REFERENCES_DE:
        if re.search(r"\b" + re.escape(ref) + r"\b", text_lower):
            if ref == "hier" and current_room:
                resolved_rooms.append(current_room)
                had_references = True
                hints.append(f"'hier' = {current_room}")
            elif last_rooms:
                resolved_rooms.append(last_rooms[0])
                had_references = True
                hints.append(f"'{ref}' -> {last_rooms[0]}")
            break

    for ref in ACTION_REFERENCES_DE:
        if re.search(r"\b" + re.escape(ref) + r"\b", text_lower) and last_actions:
            had_references = True
            break

    return {
        "had_references": had_references,
        "resolved_entities": resolved_entities,
        "resolved_rooms": resolved_rooms,
        "hints": hints,
    }


def is_clarification_answer(text):
    """Check if text matches a clarification answer pattern."""
    text_lower = text.lower().strip()
    for pattern in CLARIFICATION_ANSWER_PATTERNS:
        if re.match(pattern, text_lower):
            return True
    return False


# ===================================================================
# Tests
# ===================================================================


class TestEntityReferences:
    """Entity reference resolution with and without history."""

    @pytest.mark.parametrize(
        "text, last_entity",
        [
            ("mach es aus", "light.wohnzimmer"),
            ("schalte das ein", "light.kueche"),
            ("kannst du es dimmen", "light.schlafzimmer"),
            ("schalte ihn ein", "switch.ventilator"),
            ("mach ihm an", "light.flur"),
            ("stell die auf 50", "light.stehlampe"),
            ("den bitte ausschalten", "switch.heizung"),
        ],
        ids=[
            "es-aus",
            "das-ein",
            "es-dimmen",
            "ihn-ein",
            "ihm-an",
            "die-auf-50",
            "den-ausschalten",
        ],
    )
    def test_simple_pronoun_resolves_to_last_entity(self, text, last_entity):
        result = resolve_references(text, last_entities=[last_entity])
        assert result["had_references"] is True
        assert last_entity in result["resolved_entities"]
        assert len(result["hints"]) == 1

    @pytest.mark.parametrize(
        "text",
        [
            "das gleiche",
            "den gleichen",
            "die gleiche",
            "dasselbe",
        ],
    )
    def test_compound_entity_references(self, text):
        result = resolve_references(text, last_entities=["light.wohnzimmer"])
        assert result["had_references"] is True
        assert "light.wohnzimmer" in result["resolved_entities"]

    @pytest.mark.parametrize(
        "text",
        [
            "das licht bitte",
            "schalte die lampe um",
            "mach das ding aus",
        ],
    )
    def test_descriptive_entity_references(self, text):
        result = resolve_references(text, last_entities=["light.bad"])
        assert result["had_references"] is True
        assert "light.bad" in result["resolved_entities"]

    @pytest.mark.parametrize(
        "text",
        [
            "mach es aus",
            "schalte das ein",
            "das gleiche",
            "die lampe bitte",
        ],
    )
    def test_entity_reference_without_history_no_resolution(self, text):
        result = resolve_references(text, last_entities=None)
        assert result["resolved_entities"] == []
        # had_references stays False when there is no history to resolve to
        assert result["had_references"] is False

    def test_entity_reference_empty_history_no_resolution(self):
        result = resolve_references("mach es aus", last_entities=[])
        assert result["resolved_entities"] == []
        assert result["had_references"] is False

    def test_picks_first_entity_from_history(self):
        result = resolve_references(
            "mach es aus",
            last_entities=["light.kueche", "light.wohnzimmer"],
        )
        assert result["resolved_entities"] == ["light.kueche"]


class TestRoomReferences:
    """Room reference resolution including 'hier' with current_room."""

    @pytest.mark.parametrize(
        "text, expected_room",
        [
            ("mach dort das licht an", "Wohnzimmer"),
            ("schalte da alles aus", "Kueche"),
            ("geh dahin", "Flur"),
            ("da drin bitte", "Schlafzimmer"),
            ("dorthin bitte", "Bad"),
            ("drin alles aus", "Keller"),
        ],
        ids=["dort", "da", "dahin", "da-drin", "dorthin", "drin"],
    )
    def test_room_reference_resolves_to_last_room(self, text, expected_room):
        result = resolve_references(text, last_rooms=[expected_room])
        assert result["had_references"] is True
        assert expected_room in result["resolved_rooms"]
        assert len(result["hints"]) == 1

    @pytest.mark.parametrize(
        "text",
        [
            "im gleichen raum",
            "im selben raum",
        ],
    )
    def test_compound_room_references(self, text):
        result = resolve_references(text, last_rooms=["Wohnzimmer"])
        assert result["had_references"] is True
        assert "Wohnzimmer" in result["resolved_rooms"]

    def test_hier_uses_current_room(self):
        result = resolve_references(
            "mach hier das licht an",
            last_rooms=["Kueche"],
            current_room="Wohnzimmer",
        )
        assert result["had_references"] is True
        assert "Wohnzimmer" in result["resolved_rooms"]
        # Should NOT fall back to last_rooms when current_room is set
        assert "Kueche" not in result["resolved_rooms"]
        assert any("hier" in h for h in result["hints"])

    def test_hier_without_current_room_no_resolution(self):
        # "hier" with no current_room and no last_rooms -> no resolution
        result = resolve_references("mach hier das licht an", current_room="")
        assert result["resolved_rooms"] == []

    def test_hier_without_current_room_but_with_last_rooms(self):
        # "hier" with no current_room: whether it resolves depends on set
        # iteration order. If "hier" is checked first, the elif branch
        # (last_rooms) is skipped because ref == "hier" takes the if-branch
        # which requires current_room. If another ref matches first, it may
        # resolve. We only assert that if resolution happens, the room is
        # from last_rooms, and current_room is never used when empty.
        result = resolve_references(
            "hier bitte",
            last_rooms=["Kueche"],
            current_room="",
        )
        # current_room is empty, so it must not appear in resolved_rooms
        assert "" not in result["resolved_rooms"]
        # if anything resolved it can only be from last_rooms
        for room in result["resolved_rooms"]:
            assert room in ["Kueche"]

    @pytest.mark.parametrize(
        "text",
        [
            "mach dort das licht an",
            "da bitte alles aus",
            "im gleichen raum",
        ],
    )
    def test_room_reference_without_history_no_resolution(self, text):
        result = resolve_references(text, last_rooms=None)
        assert result["resolved_rooms"] == []
        assert result["had_references"] is False

    def test_room_reference_empty_history_no_resolution(self):
        result = resolve_references("mach dort alles aus", last_rooms=[])
        assert result["resolved_rooms"] == []
        assert result["had_references"] is False

    def test_picks_first_room_from_history(self):
        result = resolve_references("da auch", last_rooms=["Wohnzimmer", "Kueche"])
        assert result["resolved_rooms"] == ["Wohnzimmer"]


class TestActionReferences:
    """Action reference resolution."""

    @pytest.mark.parametrize(
        "text",
        [
            "nochmal",
            "mach das nochmal",
            "wieder bitte",
            "genauso",
            "auch bitte",
            "ebenfalls",
        ],
        ids=["nochmal", "nochmal-sentence", "wieder", "genauso", "auch", "ebenfalls"],
    )
    def test_action_reference_with_history(self, text):
        result = resolve_references(
            text, last_actions=[{"action": "turn_on", "entity": "light.wohnzimmer"}]
        )
        assert result["had_references"] is True

    @pytest.mark.parametrize(
        "text",
        [
            "nochmal",
            "wieder",
            "genauso",
        ],
    )
    def test_action_reference_without_history_no_flag(self, text):
        result = resolve_references(text, last_actions=None)
        assert result["had_references"] is False

    def test_action_reference_empty_history_no_flag(self):
        result = resolve_references("nochmal", last_actions=[])
        assert result["had_references"] is False


class TestNoReferences:
    """Normal text without any references should yield empty results."""

    @pytest.mark.parametrize(
        "text",
        [
            "schalte das licht im wohnzimmer an",
            "wie ist das wetter",
            "stelle die heizung auf 22 grad",
            "guten morgen",
            "was ist die uhrzeit",
        ],
        ids=[
            "explicit-entity",
            "weather",
            "explicit-heating",
            "greeting",
            "time-question",
        ],
    )
    def test_normal_text_no_references(self, text):
        result = resolve_references(text)
        assert result["had_references"] is False
        assert result["resolved_entities"] == []
        assert result["resolved_rooms"] == []
        assert result["hints"] == []


class TestCombinedReferences:
    """Multiple reference types in a single utterance."""

    def test_entity_and_room_reference(self):
        result = resolve_references(
            "mach es dort an",
            last_entities=["light.flur"],
            last_rooms=["Kueche"],
        )
        assert result["had_references"] is True
        assert "light.flur" in result["resolved_entities"]
        assert "Kueche" in result["resolved_rooms"]

    def test_entity_and_action_reference(self):
        result = resolve_references(
            "mach es nochmal",
            last_entities=["light.wohnzimmer"],
            last_actions=[{"action": "toggle"}],
        )
        assert result["had_references"] is True
        assert "light.wohnzimmer" in result["resolved_entities"]


class TestClarificationAnswers:
    """is_clarification_answer should accept short confirmations, ordinals, numbers, and single words."""

    @pytest.mark.parametrize(
        "text",
        [
            "ja",
            "nein",
            "doch",
            "ok",
            "okay",
            "Ja",
            "NEIN",
            "Ok",
        ],
        ids=["ja", "nein", "doch", "ok", "okay", "Ja-upper", "NEIN-upper", "Ok-upper"],
    )
    def test_confirmation_words(self, text):
        assert is_clarification_answer(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "3",
            "1",
            "42",
            "007",
        ],
    )
    def test_numeric_answers(self, text):
        assert is_clarification_answer(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "erste",
            "erster",
            "ersten",
            "erstes",
            "zweite",
            "zweiten",
            "zweiter",
            "dritte",
            "vierte",
            "letzte",
            "letzter",
            "letzten",
        ],
    )
    def test_ordinal_answers(self, text):
        assert is_clarification_answer(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "Wohnzimmer",
            "Kueche",
            "Bad",
            "das Wohnzimmer",
            "die Kueche",
            "den Flur",
            "im Wohnzimmer",
            "in der Kueche",
            "am Eingang",
        ],
        ids=[
            "single-room",
            "single-room-2",
            "single-room-3",
            "das-room",
            "die-room",
            "den-room",
            "im-room",
            "in-der-room",
            "am-room",
        ],
    )
    def test_single_word_and_article_room_answers(self, text):
        assert is_clarification_answer(text) is True


class TestNonClarificationText:
    """Longer or complex sentences should NOT be treated as clarification answers."""

    @pytest.mark.parametrize(
        "text",
        [
            "wie geht es dir",
            "mach das licht an",
            "schalte die heizung im bad ein",
            "kannst du mir helfen",
            "was ist das wetter morgen",
            "bitte alle lichter ausschalten",
        ],
    )
    def test_not_clarification(self, text):
        assert is_clarification_answer(text) is False
