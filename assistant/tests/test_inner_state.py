"""
Tests fuer InnerStateEngine — JARVIS innerer emotionaler Zustand.

Testet:
- Initialisierung (Defaults, Redis-Load, fehlerhafte Redis-Daten)
- Event-Handler (on_action_success, on_action_failure, on_warning_ignored,
  on_funny_interaction, on_complex_solve, on_security_event, on_house_optimal)
- Mood-Berechnung (_update_mood) und Prioritaeten
- Counter-Decay nach 10 Minuten
- Confidence/Satisfaction Clamping (0.0–1.0)
- Prompt-Generierung (get_prompt_section, Mood-Hints, Confidence-Hints)
- Persistenz (_save_state via Redis Pipeline)
- Properties und get_state()
- set_notify_callback, stop, reload_config
"""

import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from assistant.inner_state import (
    InnerStateEngine,
    MOOD_NEUTRAL,
    MOOD_CONTENT,
    MOOD_AMUSED,
    MOOD_CONCERNED,
    MOOD_PROUD,
    MOOD_CURIOUS,
    MOOD_IRRITATED,
    VALID_MOODS,
    MOOD_PROMPT_HINTS,
    MOOD_TRANSITIONS,
    CONFIDENCE_HINTS,
)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def engine():
    """Fresh InnerStateEngine with no Redis."""
    return InnerStateEngine()


@pytest.fixture
def redis_mock():
    """AsyncMock Redis client with pipeline support."""
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    pipe = AsyncMock()
    pipe.set = MagicMock()
    pipe.execute = AsyncMock()
    mock.pipeline = MagicMock(return_value=pipe)
    return mock


@pytest.fixture
def engine_with_redis(engine, redis_mock):
    """Engine with a mocked Redis client attached (no initialize call)."""
    engine.redis = redis_mock
    return engine


# ============================================================
# Initialization Tests
# ============================================================


class TestInitialization:
    """Tests fuer __init__ und initialize."""

    def test_default_values(self, engine):
        assert engine.mood == MOOD_NEUTRAL
        assert engine.confidence == 0.6
        assert engine.satisfaction == 0.5
        assert engine.redis is None
        assert engine._notify_callback is None
        assert engine._successful_actions == 0
        assert engine._failed_actions == 0
        assert engine._ignored_warnings == 0
        assert engine._funny_interactions == 0
        assert engine._complex_solves == 0

    @pytest.mark.asyncio
    async def test_initialize_without_redis(self, engine):
        await engine.initialize(None)
        assert engine.redis is None
        assert engine.mood == MOOD_NEUTRAL

    @pytest.mark.asyncio
    async def test_initialize_loads_mood_from_redis(self, redis_mock):
        redis_mock.get = AsyncMock(
            side_effect=[
                b"stolz",  # mood
                b"0.85",  # confidence
                b"0.72",  # satisfaction
            ]
        )
        engine = InnerStateEngine()
        await engine.initialize(redis_mock)
        assert engine.mood == MOOD_PROUD
        assert engine.confidence == 0.85
        assert engine.satisfaction == 0.72

    @pytest.mark.asyncio
    async def test_initialize_loads_string_mood(self, redis_mock):
        """Redis may return str instead of bytes."""
        redis_mock.get = AsyncMock(
            side_effect=[
                "amuesiert",
                "0.4",
                "0.3",
            ]
        )
        engine = InnerStateEngine()
        await engine.initialize(redis_mock)
        assert engine.mood == MOOD_AMUSED
        assert engine.confidence == 0.4
        assert engine.satisfaction == 0.3

    @pytest.mark.asyncio
    async def test_initialize_ignores_invalid_mood(self, redis_mock):
        redis_mock.get = AsyncMock(
            side_effect=[
                b"ungueltig_mood",
                None,
                None,
            ]
        )
        engine = InnerStateEngine()
        await engine.initialize(redis_mock)
        assert engine.mood == MOOD_NEUTRAL

    @pytest.mark.asyncio
    async def test_initialize_clamps_confidence(self, redis_mock):
        redis_mock.get = AsyncMock(
            side_effect=[
                None,
                b"5.0",  # over 1.0
                b"-2.0",  # will not be reached for satisfaction
            ]
        )
        engine = InnerStateEngine()
        await engine.initialize(redis_mock)
        assert engine.confidence == 1.0

    @pytest.mark.asyncio
    async def test_initialize_clamps_satisfaction_low(self, redis_mock):
        redis_mock.get = AsyncMock(
            side_effect=[
                None,
                None,
                b"-0.5",
            ]
        )
        engine = InnerStateEngine()
        await engine.initialize(redis_mock)
        assert engine.satisfaction == 0.0

    @pytest.mark.asyncio
    async def test_initialize_handles_redis_error(self, redis_mock):
        redis_mock.get = AsyncMock(side_effect=ConnectionError("down"))
        engine = InnerStateEngine()
        await engine.initialize(redis_mock)
        # Should fall back to defaults
        assert engine.mood == MOOD_NEUTRAL
        assert engine.confidence == 0.6


# ============================================================
# Event Handler Tests
# ============================================================


class TestEventHandlers:
    """Tests fuer alle Event-Tracking-Methoden."""

    @pytest.mark.asyncio
    async def test_on_action_success_increments(self, engine):
        await engine.on_action_success("lights.on")
        assert engine._successful_actions == 1
        assert engine.confidence == pytest.approx(0.62)
        assert engine.satisfaction == pytest.approx(0.53)

    @pytest.mark.asyncio
    async def test_on_action_success_multiple(self, engine):
        for _ in range(5):
            await engine.on_action_success()
        assert engine._successful_actions == 5
        assert engine.confidence == pytest.approx(0.7)
        assert engine.satisfaction == pytest.approx(0.65)

    @pytest.mark.asyncio
    async def test_on_action_failure_decrements(self, engine):
        await engine.on_action_failure("lights.on", "timeout")
        assert engine._failed_actions == 1
        assert engine.confidence == pytest.approx(0.55)
        assert engine.satisfaction == pytest.approx(0.47)

    @pytest.mark.asyncio
    async def test_on_action_failure_multiple(self, engine):
        for _ in range(3):
            await engine.on_action_failure()
        assert engine._failed_actions == 3
        assert engine.confidence == pytest.approx(0.45)
        assert engine.satisfaction == pytest.approx(0.41)

    @pytest.mark.asyncio
    async def test_on_warning_ignored(self, engine):
        await engine.on_warning_ignored()
        assert engine._ignored_warnings == 1

    @pytest.mark.asyncio
    async def test_on_funny_interaction(self, engine):
        await engine.on_funny_interaction()
        assert engine._funny_interactions == 1

    @pytest.mark.asyncio
    async def test_on_complex_solve(self, engine):
        initial_conf = engine.confidence
        await engine.on_complex_solve()
        assert engine._complex_solves == 1
        assert engine.confidence == pytest.approx(initial_conf + 0.05)

    @pytest.mark.asyncio
    async def test_on_security_event(self, engine):
        await engine.on_security_event()
        assert engine.mood == MOOD_CONCERNED
        assert engine.satisfaction == pytest.approx(0.4)

    @pytest.mark.asyncio
    async def test_on_security_event_saves_state(self, engine_with_redis):
        await engine_with_redis.on_security_event()
        pipe = engine_with_redis.redis.pipeline()
        pipe.execute.assert_awaited()

    @pytest.mark.asyncio
    async def test_on_house_optimal_increases_satisfaction(self, engine):
        await engine.on_house_optimal()
        assert engine.satisfaction == pytest.approx(0.52)

    @pytest.mark.asyncio
    async def test_on_house_optimal_triggers_content_mood(self, engine):
        """When neutral and satisfaction > 0.7, mood becomes CONTENT."""
        engine._satisfaction = 0.69
        await engine.on_house_optimal()
        # 0.69 + 0.02 = 0.71 > 0.7 and mood is neutral
        assert engine.mood == MOOD_CONTENT

    @pytest.mark.asyncio
    async def test_on_house_optimal_no_mood_change_if_not_neutral(self, engine):
        engine._mood = MOOD_AMUSED
        engine._satisfaction = 0.75
        await engine.on_house_optimal()
        assert engine.mood == MOOD_AMUSED  # unchanged


# ============================================================
# Confidence / Satisfaction Clamping
# ============================================================


class TestValueClamping:
    """Confidence und Satisfaction bleiben im Bereich 0.0–1.0."""

    @pytest.mark.asyncio
    async def test_confidence_cannot_exceed_1(self, engine):
        engine._confidence = 0.99
        await engine.on_action_success()
        assert engine.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_confidence_cannot_go_below_0(self, engine):
        engine._confidence = 0.02
        await engine.on_action_failure()
        assert engine.confidence >= 0.0

    @pytest.mark.asyncio
    async def test_satisfaction_cannot_exceed_1(self, engine):
        engine._satisfaction = 0.99
        await engine.on_action_success()
        assert engine.satisfaction <= 1.0

    @pytest.mark.asyncio
    async def test_satisfaction_cannot_go_below_0(self, engine):
        engine._satisfaction = 0.01
        await engine.on_action_failure()
        assert engine.satisfaction >= 0.0

    @pytest.mark.asyncio
    async def test_satisfaction_floor_on_security_event(self, engine):
        engine._satisfaction = 0.05
        await engine.on_security_event()
        assert engine.satisfaction == 0.0


# ============================================================
# Mood Calculation (_update_mood)
# ============================================================


class TestMoodCalculation:
    """Tests fuer die prioritaetsbasierte Mood-Berechnung."""

    @pytest.mark.asyncio
    async def test_irritated_on_3_ignored_warnings(self, engine):
        for _ in range(3):
            await engine.on_warning_ignored()
        assert engine.mood == MOOD_IRRITATED

    @pytest.mark.asyncio
    async def test_proud_on_complex_solve_no_failures(self, engine):
        await engine.on_complex_solve()
        assert engine.mood == MOOD_PROUD

    @pytest.mark.asyncio
    async def test_proud_overridden_by_irritated(self, engine):
        """Irritated has higher priority than proud."""
        await engine.on_complex_solve()
        for _ in range(3):
            await engine.on_warning_ignored()
        assert engine.mood == MOOD_IRRITATED

    @pytest.mark.asyncio
    async def test_amused_on_2_funny_interactions(self, engine):
        await engine.on_funny_interaction()
        await engine.on_funny_interaction()
        assert engine.mood == MOOD_AMUSED

    @pytest.mark.asyncio
    async def test_content_on_high_satisfaction_no_failures(self, engine):
        engine._satisfaction = 0.68
        await engine.on_action_success()  # +0.03 -> 0.71, +0.02 conf
        assert engine.mood == MOOD_CONTENT

    @pytest.mark.asyncio
    async def test_concerned_on_multiple_failures(self, engine):
        await engine.on_action_failure()
        await engine.on_action_failure()
        assert engine.mood == MOOD_CONCERNED

    @pytest.mark.asyncio
    async def test_neutral_default(self, engine):
        await engine.on_action_success()
        # 1 success, sat=0.53 < 0.7, no complex solves, no funny, no warnings
        assert engine.mood == MOOD_NEUTRAL

    @pytest.mark.asyncio
    async def test_proud_not_set_with_failures(self, engine):
        """Complex solve + failure should NOT yield PROUD."""
        await engine.on_action_failure()
        await engine.on_complex_solve()
        # _failed_actions=1 so proud condition fails, but also not >= 2 for concerned
        assert engine.mood != MOOD_PROUD

    @pytest.mark.asyncio
    async def test_amused_overridden_by_proud(self, engine):
        """Proud has higher priority than amused."""
        await engine.on_funny_interaction()
        await engine.on_funny_interaction()
        assert engine.mood == MOOD_AMUSED
        await engine.on_complex_solve()
        assert engine.mood == MOOD_PROUD


# ============================================================
# Counter Decay
# ============================================================


class TestCounterDecay:
    """Counter werden nach 10 Minuten dekrementiert."""

    @pytest.mark.asyncio
    async def test_decay_after_10_minutes(self, engine):
        engine._successful_actions = 3
        engine._failed_actions = 2
        engine._ignored_warnings = 1
        engine._funny_interactions = 4
        engine._complex_solves = 2
        engine._last_update = time.time() - 700  # >600s ago

        await engine._update_mood()

        assert engine._successful_actions == 2
        assert engine._failed_actions == 1
        assert engine._ignored_warnings == 0
        assert engine._funny_interactions == 3
        assert engine._complex_solves == 1

    @pytest.mark.asyncio
    async def test_no_decay_before_10_minutes(self, engine):
        engine._successful_actions = 3
        engine._last_update = time.time() - 100  # <600s

        await engine._update_mood()

        assert engine._successful_actions == 3

    @pytest.mark.asyncio
    async def test_decay_does_not_go_below_zero(self, engine):
        engine._successful_actions = 0
        engine._last_update = time.time() - 700

        await engine._update_mood()

        assert engine._successful_actions == 0


# ============================================================
# Prompt Generation
# ============================================================


class TestPromptGeneration:
    """Tests fuer get_prompt_section()."""

    @patch("assistant.inner_state.yaml_config", {"inner_state": {"enabled": True}})
    def test_neutral_no_hint(self, engine):
        engine._mood = MOOD_NEUTRAL
        engine._confidence = 0.5  # range (0.3, 0.6) -> no hint
        result = engine.get_prompt_section()
        assert result == ""

    @patch("assistant.inner_state.yaml_config", {"inner_state": {"enabled": True}})
    def test_content_mood_hint(self, engine):
        engine._mood = MOOD_CONTENT
        engine._confidence = 0.5
        result = engine.get_prompt_section()
        assert "Zufrieden" in result

    @patch("assistant.inner_state.yaml_config", {"inner_state": {"enabled": True}})
    def test_irritated_mood_hint(self, engine):
        engine._mood = MOOD_IRRITATED
        engine._confidence = 0.5
        result = engine.get_prompt_section()
        assert "irritiert" in result

    @patch("assistant.inner_state.yaml_config", {"inner_state": {"enabled": True}})
    def test_high_confidence_hint(self, engine):
        engine._mood = MOOD_NEUTRAL
        engine._confidence = 0.7
        result = engine.get_prompt_section()
        assert "Hoch" in result

    @patch("assistant.inner_state.yaml_config", {"inner_state": {"enabled": True}})
    def test_very_high_confidence_hint(self, engine):
        engine._mood = MOOD_NEUTRAL
        engine._confidence = 0.9
        result = engine.get_prompt_section()
        assert "Sehr hoch" in result

    @patch("assistant.inner_state.yaml_config", {"inner_state": {"enabled": True}})
    def test_low_confidence_hint(self, engine):
        engine._mood = MOOD_NEUTRAL
        engine._confidence = 0.2
        result = engine.get_prompt_section()
        assert "Niedrig" in result

    @patch("assistant.inner_state.yaml_config", {"inner_state": {"enabled": True}})
    def test_mood_and_confidence_combined(self, engine):
        engine._mood = MOOD_PROUD
        engine._confidence = 0.9
        result = engine.get_prompt_section()
        assert "Stolz" in result
        assert "Sehr hoch" in result

    @patch("assistant.inner_state.yaml_config", {"inner_state": {"enabled": False}})
    def test_disabled_returns_empty(self, engine):
        engine._mood = MOOD_PROUD
        engine._confidence = 0.9
        result = engine.get_prompt_section()
        assert result == ""

    @patch("assistant.inner_state.yaml_config", {})
    def test_missing_config_defaults_enabled(self, engine):
        engine._mood = MOOD_AMUSED
        engine._confidence = 0.5
        result = engine.get_prompt_section()
        assert "Amuesiert" in result

    @patch("assistant.inner_state.yaml_config", {"inner_state": {"enabled": True}})
    def test_prompt_ends_with_newline(self, engine):
        engine._mood = MOOD_CONCERNED
        engine._confidence = 0.5
        result = engine.get_prompt_section()
        assert result.endswith("\n")


# ============================================================
# Properties and get_state
# ============================================================


class TestPropertiesAndState:
    """Tests fuer Properties und get_state()."""

    def test_get_state_returns_dict(self, engine):
        state = engine.get_state()
        assert isinstance(state, dict)
        assert "mood" in state
        assert "confidence" in state
        assert "satisfaction" in state

    def test_get_state_values(self, engine):
        state = engine.get_state()
        assert state["mood"] == MOOD_NEUTRAL
        assert state["confidence"] == 0.6
        assert state["satisfaction"] == 0.5

    def test_get_state_rounds_values(self, engine):
        engine._confidence = 0.12345
        engine._satisfaction = 0.67891
        state = engine.get_state()
        assert state["confidence"] == 0.12
        assert state["satisfaction"] == 0.68

    def test_mood_property(self, engine):
        engine._mood = MOOD_CURIOUS
        assert engine.mood == MOOD_CURIOUS

    def test_confidence_property(self, engine):
        engine._confidence = 0.42
        assert engine.confidence == 0.42

    def test_satisfaction_property(self, engine):
        engine._satisfaction = 0.77
        assert engine.satisfaction == 0.77


# ============================================================
# Persistence (_save_state)
# ============================================================


class TestPersistence:
    """Tests fuer Redis-Persistenz."""

    @pytest.mark.asyncio
    async def test_save_state_uses_pipeline(self, engine_with_redis):
        await engine_with_redis._save_state()
        engine_with_redis.redis.pipeline.assert_called()
        pipe = engine_with_redis.redis.pipeline()
        pipe.execute.assert_awaited()

    @pytest.mark.asyncio
    async def test_save_state_sets_correct_keys(self, engine_with_redis):
        await engine_with_redis._save_state()
        pipe = engine_with_redis.redis.pipeline()
        calls = [str(c) for c in pipe.set.call_args_list]
        combined = " ".join(calls)
        assert "mha:inner_state:mood" in combined
        assert "mha:inner_state:confidence" in combined
        assert "mha:inner_state:satisfaction" in combined
        assert "mha:inner_state:last_update" in combined

    @pytest.mark.asyncio
    async def test_save_state_noop_without_redis(self, engine):
        # Should not raise
        await engine._save_state()

    @pytest.mark.asyncio
    async def test_save_state_handles_redis_error(self, engine_with_redis):
        engine_with_redis.redis.pipeline.side_effect = ConnectionError("fail")
        # Should not raise
        await engine_with_redis._save_state()

    @pytest.mark.asyncio
    async def test_save_state_sets_expiry(self, engine_with_redis):
        await engine_with_redis._save_state()
        pipe = engine_with_redis.redis.pipeline()
        for call in pipe.set.call_args_list:
            args, kwargs = call
            assert kwargs.get("ex") == 86400 or (len(args) >= 3 and 86400 in args)


# ============================================================
# Callback and No-ops
# ============================================================


class TestCallbackAndNoops:
    """Tests fuer set_notify_callback, stop, reload_config."""

    def test_set_notify_callback(self, engine):
        cb = MagicMock()
        engine.set_notify_callback(cb)
        assert engine._notify_callback is cb

    def test_stop_is_noop(self, engine):
        engine.stop()  # Should not raise

    def test_reload_config_is_noop(self, engine):
        engine.reload_config()  # Should not raise


# ============================================================
# Constants
# ============================================================


class TestConstants:
    """Tests fuer Modul-Konstanten."""

    def test_valid_moods_contains_all(self):
        expected = {
            MOOD_NEUTRAL,
            MOOD_CONTENT,
            MOOD_AMUSED,
            MOOD_CONCERNED,
            MOOD_PROUD,
            MOOD_CURIOUS,
            MOOD_IRRITATED,
        }
        assert VALID_MOODS == expected

    def test_valid_moods_is_frozenset(self):
        assert isinstance(VALID_MOODS, frozenset)

    def test_mood_prompt_hints_keys_match_valid_moods(self):
        assert set(MOOD_PROMPT_HINTS.keys()) == VALID_MOODS

    def test_confidence_hints_cover_full_range(self):
        ranges = sorted(CONFIDENCE_HINTS.keys())
        assert ranges[0][0] == 0.0
        assert ranges[-1][1] > 1.0  # 1.01


# ============================================================
# Integration: Event Sequences
# ============================================================


class TestEventSequences:
    """Integrationstests mit Event-Ketten."""

    @pytest.mark.asyncio
    async def test_success_then_failure_mood_stays_neutral(self, engine):
        await engine.on_action_success()
        await engine.on_action_failure()
        # 1 success, 1 failure, sat ~0.5, no complex, no funny, no warnings
        assert engine.mood == MOOD_NEUTRAL

    @pytest.mark.asyncio
    async def test_security_event_overrides_proud(self, engine):
        await engine.on_complex_solve()
        assert engine.mood == MOOD_PROUD
        await engine.on_security_event()
        assert engine.mood == MOOD_CONCERNED

    @pytest.mark.asyncio
    async def test_full_scenario(self, engine):
        """Realistic sequence of events."""
        await engine.on_action_success("heizung.an")
        await engine.on_action_success("licht.an")
        await engine.on_house_optimal()
        # sat = 0.5 + 0.03 + 0.03 + 0.02 = 0.58, mood neutral
        assert engine.mood == MOOD_NEUTRAL

        await engine.on_complex_solve()
        assert engine.mood == MOOD_PROUD

        await engine.on_action_failure("door.lock", "timeout")
        # Now failed_actions=1, complex_solves=1 but failed>0 -> not proud
        assert engine.mood != MOOD_PROUD


# ============================================================
# User Mood Change
# ============================================================


class TestUserMoodChange:
    """Tests fuer on_user_mood_change — empathische Reaktion auf User-Stimmung."""

    @pytest.mark.asyncio
    async def test_frustrated_user_triggers_concerned(self, engine):
        await engine.on_user_mood_change("frustrated", "Max")
        assert engine.mood == MOOD_CONCERNED

    @pytest.mark.asyncio
    async def test_stressed_user_triggers_concerned(self, engine):
        await engine.on_user_mood_change("stressed", "Lisa")
        assert engine.mood == MOOD_CONCERNED

    @pytest.mark.asyncio
    async def test_good_user_mood_increases_satisfaction(self, engine):
        initial_sat = engine.satisfaction
        await engine.on_user_mood_change("good", "Max")
        assert engine.satisfaction == pytest.approx(initial_sat + 0.1)
        # Mood should not change directly
        assert engine.mood == MOOD_NEUTRAL

    @pytest.mark.asyncio
    async def test_good_user_mood_clamps_satisfaction(self, engine):
        engine._satisfaction = 0.95
        await engine.on_user_mood_change("good")
        assert engine.satisfaction <= 1.0

    @pytest.mark.asyncio
    async def test_unknown_user_mood_no_change(self, engine):
        initial_mood = engine.mood
        initial_sat = engine.satisfaction
        await engine.on_user_mood_change("bored")
        assert engine.mood == initial_mood
        assert engine.satisfaction == initial_sat

    @pytest.mark.asyncio
    async def test_frustrated_saves_previous_mood(self, engine):
        engine._mood = MOOD_AMUSED
        await engine.on_user_mood_change("frustrated")
        assert engine._previous_mood == MOOD_AMUSED
        assert engine.mood == MOOD_CONCERNED

    @pytest.mark.asyncio
    async def test_user_mood_without_person(self, engine):
        """Person parameter is optional."""
        await engine.on_user_mood_change("frustrated")
        assert engine.mood == MOOD_CONCERNED


# ============================================================
# Scene Activation
# ============================================================


class TestSceneActivation:
    """Tests fuer on_scene_activated — Szene beeinflusst Stimmung."""

    @pytest.mark.asyncio
    async def test_party_scene_sets_amused(self, engine):
        await engine.on_scene_activated("party")
        assert engine.mood == MOOD_AMUSED

    @pytest.mark.asyncio
    async def test_gemuetlich_scene_sets_content(self, engine):
        await engine.on_scene_activated("gemuetlich")
        assert engine.mood == MOOD_CONTENT

    @pytest.mark.asyncio
    async def test_filmabend_scene_sets_content(self, engine):
        await engine.on_scene_activated("filmabend")
        assert engine.mood == MOOD_CONTENT

    @pytest.mark.asyncio
    async def test_schlafen_scene_keeps_neutral(self, engine):
        """If mood is already neutral, scene 'schlafen' should not change it."""
        assert engine.mood == MOOD_NEUTRAL
        await engine.on_scene_activated("schlafen")
        assert engine.mood == MOOD_NEUTRAL

    @pytest.mark.asyncio
    async def test_scene_changes_previous_mood(self, engine):
        engine._mood = MOOD_IRRITATED
        await engine.on_scene_activated("party")
        assert engine._previous_mood == MOOD_IRRITATED
        assert engine.mood == MOOD_AMUSED

    @pytest.mark.asyncio
    async def test_unknown_scene_no_change(self, engine):
        engine._mood = MOOD_PROUD
        await engine.on_scene_activated("unknown_scene")
        assert engine.mood == MOOD_PROUD

    @pytest.mark.asyncio
    async def test_scene_no_change_if_same_mood(self, engine):
        """If target mood equals current mood, no transition should happen."""
        engine._mood = MOOD_CONTENT
        engine._previous_mood = MOOD_NEUTRAL
        await engine.on_scene_activated("filmabend")  # also CONTENT
        assert engine.mood == MOOD_CONTENT
        # _previous_mood should NOT be updated since no transition occurred
        assert engine._previous_mood == MOOD_NEUTRAL

    @pytest.mark.asyncio
    async def test_scene_saves_state_with_redis(self, engine_with_redis):
        await engine_with_redis.on_scene_activated("party")
        pipe = engine_with_redis.redis.pipeline()
        pipe.execute.assert_awaited()

    @pytest.mark.asyncio
    async def test_all_scene_mood_map_entries_are_valid(self):
        """All scene mood targets must be valid moods."""
        engine = InnerStateEngine()
        for scene_name, target_mood in engine._SCENE_MOOD_MAP.items():
            assert target_mood in VALID_MOODS, (
                f"Scene '{scene_name}' maps to invalid mood '{target_mood}'"
            )


# ============================================================
# Mood Transitions
# ============================================================


class TestMoodTransitions:
    """Tests fuer get_transition_comment und MOOD_TRANSITIONS."""

    def test_transition_comment_irritated_to_content(self, engine):
        engine._mood = MOOD_CONTENT
        engine._previous_mood = MOOD_IRRITATED
        comment = engine.get_transition_comment()
        assert comment == "Deutlich besser als vorhin."

    def test_transition_comment_concerned_to_neutral(self, engine):
        engine._mood = MOOD_NEUTRAL
        engine._previous_mood = MOOD_CONCERNED
        comment = engine.get_transition_comment()
        assert comment == "Problem scheint geloest."

    def test_transition_comment_neutral_to_proud(self, engine):
        engine._mood = MOOD_PROUD
        engine._previous_mood = MOOD_NEUTRAL
        comment = engine.get_transition_comment()
        assert comment == "Darf ich anmerken — das lief gut."

    def test_no_transition_comment_same_mood(self, engine):
        engine._mood = MOOD_NEUTRAL
        engine._previous_mood = MOOD_NEUTRAL
        comment = engine.get_transition_comment()
        assert comment is None

    def test_no_transition_comment_unmapped_pair(self, engine):
        engine._mood = MOOD_CURIOUS
        engine._previous_mood = MOOD_AMUSED
        comment = engine.get_transition_comment()
        assert comment is None

    def test_transition_comment_consumed_once(self, engine):
        """Transition comment should only be returned once."""
        engine._mood = MOOD_CONTENT
        engine._previous_mood = MOOD_IRRITATED
        comment1 = engine.get_transition_comment()
        assert comment1 is not None
        comment2 = engine.get_transition_comment()
        assert comment2 is None

    def test_all_transition_keys_are_valid_moods(self):
        """All moods in MOOD_TRANSITIONS keys must be valid."""
        for (from_mood, to_mood), comment in MOOD_TRANSITIONS.items():
            assert from_mood in VALID_MOODS, f"Invalid from_mood: {from_mood}"
            assert to_mood in VALID_MOODS, f"Invalid to_mood: {to_mood}"
            assert isinstance(comment, str) and len(comment) > 0

    @patch("assistant.inner_state.yaml_config", {"inner_state": {"enabled": True}})
    def test_transition_comment_included_in_prompt(self, engine):
        """Transition comment should appear in get_prompt_section output."""
        engine._mood = MOOD_NEUTRAL
        engine._previous_mood = MOOD_CONCERNED
        engine._confidence = 0.5
        result = engine.get_prompt_section()
        assert "STIMMUNGSWECHSEL" in result
        assert "Problem scheint geloest." in result


# ============================================================
# Mood History
# ============================================================


class TestMoodHistory:
    """Tests fuer get_mood_history."""

    @pytest.mark.asyncio
    async def test_no_history_without_redis(self, engine):
        result = await engine.get_mood_history()
        assert result == []

    @pytest.mark.asyncio
    async def test_history_returns_parsed_entries(self, engine_with_redis):
        import json
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        entry = json.dumps(
            {
                "mood": "zufrieden",
                "confidence": 0.8,
                "satisfaction": 0.7,
                "hour": now.strftime("%Y-%m-%d-%H"),
            }
        )
        engine_with_redis.redis.zrangebyscore = AsyncMock(
            return_value=[(entry.encode(), now.timestamp())]
        )
        result = await engine_with_redis.get_mood_history(days=7)
        assert len(result) == 1
        assert result[0]["mood"] == "zufrieden"
        assert result[0]["confidence"] == 0.8
        assert "timestamp" in result[0]

    @pytest.mark.asyncio
    async def test_history_handles_string_entries(self, engine_with_redis):
        """Redis may return strings instead of bytes."""
        import json
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        entry = json.dumps(
            {
                "mood": "neutral",
                "confidence": 0.5,
                "satisfaction": 0.5,
                "hour": "2026-03-20-14",
            }
        )
        engine_with_redis.redis.zrangebyscore = AsyncMock(
            return_value=[(entry, now.timestamp())]  # str, not bytes
        )
        result = await engine_with_redis.get_mood_history(days=7)
        assert len(result) == 1
        assert result[0]["mood"] == "neutral"

    @pytest.mark.asyncio
    async def test_history_empty_on_redis_error(self, engine_with_redis):
        engine_with_redis.redis.zrangebyscore = AsyncMock(
            side_effect=ConnectionError("down")
        )
        result = await engine_with_redis.get_mood_history()
        assert result == []

    @pytest.mark.asyncio
    async def test_history_custom_days(self, engine_with_redis):
        engine_with_redis.redis.zrangebyscore = AsyncMock(return_value=[])
        await engine_with_redis.get_mood_history(days=30)
        call_args = engine_with_redis.redis.zrangebyscore.call_args
        # min_score should be 30 days ago
        min_score = call_args[0][1]
        import time

        expected_min = time.time() - (30 * 86400)
        assert abs(min_score - expected_min) < 5  # within 5 seconds


# ============================================================
# Mood Summary
# ============================================================


class TestMoodSummary:
    """Tests fuer get_mood_summary — kompakte Stimmungs-Zusammenfassung."""

    @pytest.mark.asyncio
    async def test_empty_summary_without_history(self, engine):
        result = await engine.get_mood_summary()
        assert result == ""

    @pytest.mark.asyncio
    async def test_summary_with_single_mood(self, engine_with_redis):
        import json
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        entries = []
        for i in range(5):
            entry = json.dumps(
                {
                    "mood": "zufrieden",
                    "confidence": 0.8,
                    "satisfaction": 0.7,
                    "hour": f"2026-03-20-{10 + i:02d}",
                }
            )
            entries.append((entry.encode(), now.timestamp() + i * 3600))
        engine_with_redis.redis.zrangebyscore = AsyncMock(return_value=entries)
        result = await engine_with_redis.get_mood_summary(days=7)
        assert "zufrieden 100%" in result
        assert "Stimmung letzte 7 Tage" in result

    @pytest.mark.asyncio
    async def test_summary_with_mixed_moods(self, engine_with_redis):
        import json
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        moods = [
            "zufrieden",
            "zufrieden",
            "neutral",
            "besorgt",
            "zufrieden",
            "neutral",
            "zufrieden",
            "neutral",
            "zufrieden",
            "neutral",
        ]
        entries = []
        for i, mood in enumerate(moods):
            entry = json.dumps(
                {
                    "mood": mood,
                    "confidence": 0.5,
                    "satisfaction": 0.5,
                    "hour": f"2026-03-{15 + i // 4:02d}-{10 + i % 4:02d}",
                }
            )
            entries.append((entry.encode(), now.timestamp() + i * 3600))
        engine_with_redis.redis.zrangebyscore = AsyncMock(return_value=entries)
        result = await engine_with_redis.get_mood_summary(days=7)
        assert "zufrieden" in result
        assert "neutral" in result
        assert "besorgt" in result
        assert "%" in result

    @pytest.mark.asyncio
    async def test_summary_trend_positive(self, engine_with_redis):
        """When second half has more positive moods, trend should be 'positiver'."""
        import json
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        # First half: mostly neutral; second half: mostly content/amused
        moods = [
            "neutral",
            "neutral",
            "neutral",
            "besorgt",
            "zufrieden",
            "zufrieden",
            "amuesiert",
            "stolz",
        ]
        entries = []
        for i, mood in enumerate(moods):
            entry = json.dumps(
                {
                    "mood": mood,
                    "confidence": 0.5,
                    "satisfaction": 0.5,
                    "hour": f"2026-03-{16 + i // 4:02d}-{10 + i % 4:02d}",
                }
            )
            entries.append((entry.encode(), now.timestamp() + i * 3600))
        engine_with_redis.redis.zrangebyscore = AsyncMock(return_value=entries)
        result = await engine_with_redis.get_mood_summary(days=7)
        assert "positiver" in result

    @pytest.mark.asyncio
    async def test_summary_trend_angespannt(self, engine_with_redis):
        """When first half has more positive moods, trend should be 'angespannter'."""
        import json
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        # First half: positive; second half: negative
        moods = [
            "zufrieden",
            "amuesiert",
            "stolz",
            "zufrieden",
            "neutral",
            "neutral",
            "besorgt",
            "irritiert",
        ]
        entries = []
        for i, mood in enumerate(moods):
            entry = json.dumps(
                {
                    "mood": mood,
                    "confidence": 0.5,
                    "satisfaction": 0.5,
                    "hour": f"2026-03-{16 + i // 4:02d}-{10 + i % 4:02d}",
                }
            )
            entries.append((entry.encode(), now.timestamp() + i * 3600))
        engine_with_redis.redis.zrangebyscore = AsyncMock(return_value=entries)
        result = await engine_with_redis.get_mood_summary(days=7)
        assert "angespannter" in result

    @pytest.mark.asyncio
    async def test_summary_trend_stable(self, engine_with_redis):
        """When both halves are similar, trend should be 'stabil'."""
        import json
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        moods = [
            "zufrieden",
            "neutral",
            "zufrieden",
            "neutral",
            "zufrieden",
            "neutral",
            "zufrieden",
            "neutral",
        ]
        entries = []
        for i, mood in enumerate(moods):
            entry = json.dumps(
                {
                    "mood": mood,
                    "confidence": 0.5,
                    "satisfaction": 0.5,
                    "hour": f"2026-03-{16 + i // 4:02d}-{10 + i % 4:02d}",
                }
            )
            entries.append((entry.encode(), now.timestamp() + i * 3600))
        engine_with_redis.redis.zrangebyscore = AsyncMock(return_value=entries)
        result = await engine_with_redis.get_mood_summary(days=7)
        assert "stabil" in result

    @pytest.mark.asyncio
    async def test_summary_no_trend_with_few_entries(self, engine_with_redis):
        """With <= 4 entries (mid <= 2), no trend should be calculated."""
        import json
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        moods = ["zufrieden", "neutral"]
        entries = []
        for i, mood in enumerate(moods):
            entry = json.dumps(
                {
                    "mood": mood,
                    "confidence": 0.5,
                    "satisfaction": 0.5,
                    "hour": f"2026-03-20-{10 + i:02d}",
                }
            )
            entries.append((entry.encode(), now.timestamp() + i * 3600))
        engine_with_redis.redis.zrangebyscore = AsyncMock(return_value=entries)
        result = await engine_with_redis.get_mood_summary(days=7)
        assert "Tendenz" not in result


# ============================================================
# Additional Edge Cases
# ============================================================


class TestEdgeCases:
    """Zusaetzliche Randfaelle und Grenzwert-Tests."""

    @pytest.mark.asyncio
    async def test_confidence_capped_on_many_successes(self, engine):
        """Confidence should never exceed 1.0 even after many successes."""
        for _ in range(50):
            await engine.on_action_success()
        assert engine.confidence == 1.0

    @pytest.mark.asyncio
    async def test_confidence_floored_on_many_failures(self, engine):
        """Confidence should never go below 0.0 even after many failures."""
        for _ in range(50):
            await engine.on_action_failure()
        assert engine.confidence == 0.0

    @pytest.mark.asyncio
    async def test_satisfaction_capped_on_many_user_good_moods(self, engine):
        for _ in range(20):
            await engine.on_user_mood_change("good")
        assert engine.satisfaction <= 1.0

    @pytest.mark.asyncio
    async def test_concurrent_events_do_not_corrupt_state(self, engine):
        """Multiple events in quick succession should leave valid state."""
        await engine.on_action_success()
        await engine.on_action_failure()
        await engine.on_funny_interaction()
        await engine.on_warning_ignored()
        await engine.on_complex_solve()
        assert engine.mood in VALID_MOODS
        assert 0.0 <= engine.confidence <= 1.0
        assert 0.0 <= engine.satisfaction <= 1.0

    @pytest.mark.asyncio
    async def test_mood_update_stores_previous_mood(self, engine):
        """When _update_mood changes mood, _previous_mood is updated."""
        await engine.on_complex_solve()  # Should set PROUD
        assert engine._previous_mood == MOOD_NEUTRAL
        assert engine.mood == MOOD_PROUD

    @pytest.mark.asyncio
    async def test_decay_resets_last_update(self, engine):
        """After decay, _last_update should be refreshed."""
        old_time = time.time() - 700
        engine._last_update = old_time
        engine._successful_actions = 1
        await engine._update_mood()
        assert engine._last_update > old_time

    def test_get_state_reflects_mutations(self, engine):
        """get_state should always reflect current internal values."""
        engine._mood = MOOD_IRRITATED
        engine._confidence = 0.1
        engine._satisfaction = 0.9
        state = engine.get_state()
        assert state["mood"] == MOOD_IRRITATED
        assert state["confidence"] == 0.1
        assert state["satisfaction"] == 0.9

    @pytest.mark.asyncio
    async def test_security_event_overrides_any_mood(self, engine):
        """on_security_event should override any current mood."""
        for mood in [
            MOOD_CONTENT,
            MOOD_AMUSED,
            MOOD_PROUD,
            MOOD_CURIOUS,
            MOOD_IRRITATED,
        ]:
            engine._mood = mood
            await engine.on_security_event()
            assert engine.mood == MOOD_CONCERNED

    @pytest.mark.asyncio
    async def test_scene_arbeiten_sets_neutral(self, engine):
        engine._mood = MOOD_AMUSED
        await engine.on_scene_activated("arbeiten")
        assert engine.mood == MOOD_NEUTRAL

    @pytest.mark.asyncio
    async def test_scene_spielen_sets_amused(self, engine):
        await engine.on_scene_activated("spielen")
        assert engine.mood == MOOD_AMUSED
