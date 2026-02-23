"""
Jarvis Character Test Suite — Phase 12.4: Model-Wahl & Testing.

Zwei Modi:
  1. Unit-Tests (pytest): Deterministisch, CI-faehig, kein LLM noetig.
     Prueft PersonalityEngine, System-Prompt-Aufbau, Mood-Anpassung,
     Humor-Level, Formality-Stufen, Easter Eggs, Opinion Engine,
     Antwort-Varianz, Running Gags, Charakter-Entwicklung.

  2. LLM-Benchmark (CLI):  python -m tests.jarvis_character_test [--model MODEL]
     20 Standard-Eingaben gegen ein echtes Modell, bewertet nach 5 Kriterien:
       - Charakter-Konsistenz (0-10)
       - Kuerze (0-10)
       - Keine LLM-Floskeln (0-10)
       - Humor-Qualitaet (0-10)
       - Deutsche Sprach-Qualitaet (0-10)
"""

import random
import re
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# PersonalityEngine importieren — mit gemockter Config
# ---------------------------------------------------------------------------

_MOCK_YAML_CONFIG = {
    "personality": {
        "sarcasm_level": 3,
        "opinion_intensity": 2,
        "self_irony_enabled": True,
        "self_irony_max_per_day": 3,
        "character_evolution": True,
        "formality_start": 80,
        "formality_min": 30,
        "formality_decay_per_day": 0.5,
        "time_layers": {
            "early_morning": {"style": "ruhig, minimal", "max_sentences": 2},
            "morning": {"style": "klar, sachlich", "max_sentences": 3},
            "afternoon": {"style": "normal, sachlich", "max_sentences": 3},
            "evening": {"style": "entspannt, ausfuehrlicher", "max_sentences": 4},
            "night": {"style": "minimal, leise", "max_sentences": 1},
        },
    },
    "response_filter": {"enabled": True},
    "household": {"primary_user": "Max"},
    "persons": {"titles": {"max": "Sir"}},
    "trust_levels": {"persons": {"max": 2}, "default": 0},
}

_MOCK_SETTINGS = MagicMock()
_MOCK_SETTINGS.user_name = "Max"
_MOCK_SETTINGS.assistant_name = "Jarvis"


def _make_personality_engine():
    """Erzeugt eine PersonalityEngine mit gemockter Config."""
    with patch("assistant.personality.settings", _MOCK_SETTINGS), \
         patch("assistant.personality.yaml_config", _MOCK_YAML_CONFIG):
        from assistant.personality import PersonalityEngine
        return PersonalityEngine()


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def engine():
    """Frische PersonalityEngine-Instanz pro Test."""
    return _make_personality_engine()


@pytest.fixture
def engine_with_redis(redis_mock):
    """PersonalityEngine mit Redis-Mock."""
    eng = _make_personality_engine()
    eng.set_redis(redis_mock)
    return eng


# ===================================================================
# 1. SYSTEM PROMPT GRUNDSTRUKTUR
# ===================================================================

class TestSystemPromptStructure:
    """Der System-Prompt enthaelt alle Jarvis-Charakter-Elemente."""

    def test_contains_jarvis_identity(self, engine):
        prompt = engine.build_system_prompt()
        assert "Jarvis" in prompt
        assert "J.A.R.V.I.S." in prompt

    def test_contains_german_language_rule(self, engine):
        prompt = engine.build_system_prompt()
        assert "AUSSCHLIESSLICH Deutsch" in prompt

    def test_contains_jarvis_codex(self, engine):
        prompt = engine.build_system_prompt()
        assert "JARVIS-CODEX" in prompt
        assert "VERBOTEN" in prompt

    def test_banned_phrases_in_codex(self, engine):
        prompt = engine.build_system_prompt()
        for phrase in ["Als KI", "Es tut mir leid", "Leider", "Wie kann ich helfen"]:
            assert phrase in prompt, f"Banned phrase '{phrase}' fehlt im Codex"

    def test_contains_sir_usage_rules(self, engine):
        prompt = engine.build_system_prompt()
        assert "Sir" in prompt
        assert "Sehr wohl, Sir" in prompt or "Sir" in prompt

    def test_contains_understatement_rules(self, engine):
        prompt = engine.build_system_prompt()
        assert "Understatement" in prompt or "Interessante Entscheidung" in prompt

    def test_contains_schutzinstinkt(self, engine):
        prompt = engine.build_system_prompt()
        assert "Sicherheit" in prompt
        assert "Komfort" in prompt

    def test_contains_examples(self, engine):
        """Der Prompt enthaelt JARVIS-typische Beispiel-Dialoge."""
        prompt = engine.build_system_prompt()
        assert "Erledigt." in prompt
        assert "Mach Licht an" in prompt or "21 Grad" in prompt

    def test_duzen_rule(self, engine):
        """JARVIS duzt Hausbewohner. Immer."""
        prompt = engine.build_system_prompt()
        assert "DUZT" in prompt or "duzt" in prompt
        assert "IMMER" in prompt

    def test_no_english_in_prompt_body(self, engine):
        """Der System-Prompt selbst ist Deutsch (abgesehen von Fachbegriffen)."""
        prompt = engine.build_system_prompt()
        # Prompt sollte ueberwiegend Deutsch sein
        german_markers = ["Deutsch", "Erledigt", "Sicherheit", "Sprache", "Antwort"]
        hits = sum(1 for m in german_markers if m in prompt)
        assert hits >= 3, "System-Prompt scheint nicht ueberwiegend Deutsch zu sein"


# ===================================================================
# 2. MOOD-SYSTEM
# ===================================================================

class TestMoodSystem:
    """Stimmung beeinflusst Prompt-Aufbau und Humor."""

    def _ctx(self, mood: str) -> dict:
        return {"mood": {"mood": mood, "stress_level": 0, "tiredness_level": 0}}

    def test_neutral_mood_no_extra_section(self, engine):
        prompt = engine.build_system_prompt(context=self._ctx("neutral"))
        assert "STIMMUNG:" not in prompt

    def test_good_mood_more_humor(self, engine):
        prompt = engine.build_system_prompt(context=self._ctx("good"))
        assert "STIMMUNG:" in prompt
        assert "Humor" in prompt or "locker" in prompt

    def test_stressed_mood_brief(self, engine):
        prompt = engine.build_system_prompt(context=self._ctx("stressed"))
        assert "STIMMUNG:" in prompt
        assert "gestresst" in prompt or "knapp" in prompt

    def test_frustrated_mood_no_justification(self, engine):
        prompt = engine.build_system_prompt(context=self._ctx("frustrated"))
        assert "frustriert" in prompt
        assert "Nicht rechtfertigen" in prompt or "handeln" in prompt

    def test_tired_mood_minimal(self, engine):
        prompt = engine.build_system_prompt(context=self._ctx("tired"))
        assert "muede" in prompt or "Minimal" in prompt or "Kein Humor" in prompt

    def test_max_sentences_reduced_when_stressed(self, engine):
        """Stress reduziert die maximale Satzanzahl."""
        from assistant.personality import MOOD_STYLES
        assert MOOD_STYLES["stressed"]["max_sentences_mod"] < 0

    def test_max_sentences_increased_when_good(self, engine):
        from assistant.personality import MOOD_STYLES
        assert MOOD_STYLES["good"]["max_sentences_mod"] > 0

    def test_max_sentences_never_below_one(self, engine):
        """Auch bei negativem Mood-Modifier bleibt min 1 Satz."""
        prompt = engine.build_system_prompt(context=self._ctx("stressed"))
        match = re.search(r"Maximal (\d+) S", prompt)
        if match:
            assert int(match.group(1)) >= 1


# ===================================================================
# 3. TAGESZEIT-ANPASSUNG
# ===================================================================

class TestTimeOfDay:
    """Tageszeit bestimmt Stil und max Saetze."""

    @pytest.mark.parametrize("hour,expected", [
        (3, "night"), (6, "early_morning"), (9, "morning"),
        (14, "afternoon"), (20, "evening"), (23, "night"),
    ])
    def test_time_categories(self, engine, hour, expected):
        assert engine.get_time_of_day(hour) == expected

    def test_night_has_fewer_sentences(self, engine):
        assert engine.get_max_sentences("night") <= 2

    def test_evening_has_more_sentences(self, engine):
        assert engine.get_max_sentences("evening") >= 3

    def test_early_morning_style_is_calm(self, engine):
        style = engine.get_time_style("early_morning")
        assert "ruhig" in style or "minimal" in style


# ===================================================================
# 4. HUMOR / SARKASMUS
# ===================================================================

class TestHumorSystem:
    """Humor-Level wird nach Kontext angepasst."""

    def test_humor_section_in_prompt(self, engine):
        prompt = engine.build_system_prompt()
        assert "HUMOR:" in prompt

    def test_humor_templates_all_levels(self):
        from assistant.personality import HUMOR_TEMPLATES
        for level in range(1, 6):
            assert level in HUMOR_TEMPLATES
            assert len(HUMOR_TEMPLATES[level]) > 0

    def test_night_dampens_humor(self, engine):
        """Nachts wird Humor auf max Level 1 gedaempft."""
        section = engine._build_humor_section("neutral", "night")
        # Nachts: Level 1 = "Kein Humor"
        assert "Kein Humor" in section

    def test_early_morning_dampens_humor(self, engine):
        section = engine._build_humor_section("neutral", "early_morning")
        # Frueh morgens: max Level 2
        assert "Kein Humor" in section or "Gelegentlich trocken" in section

    def test_tired_mood_dampens_humor(self, engine):
        section = engine._build_humor_section("tired", "afternoon")
        assert "Kein Humor" in section or "Gelegentlich trocken" in section

    def test_good_mood_boosts_humor(self, engine):
        """Gute Stimmung erhoeht Humor-Level um 1."""
        engine.sarcasm_level = 3
        section = engine._build_humor_section("good", "afternoon")
        # Level 3+1 = 4 → "Haeufig sarkastisch"
        assert "sarkastisch" in section or "Spitze" in section

    def test_stressed_keeps_humor(self, engine):
        """Unter Stress bleibt Humor gleich (Jarvis wird trockener, nicht stiller)."""
        engine.sarcasm_level = 3
        section_normal = engine._build_humor_section("neutral", "afternoon")
        section_stressed = engine._build_humor_section("stressed", "afternoon")
        assert section_normal == section_stressed


# ===================================================================
# 5. FORMALITY / CHARAKTER-ENTWICKLUNG
# ===================================================================

class TestFormalitySystem:
    """Formality sinkt ueber Zeit: formal → butler → locker → freund."""

    @pytest.mark.parametrize("score,expected_key", [
        (80, "formal"), (60, "butler"), (40, "locker"), (25, "freund"),
    ])
    def test_formality_thresholds(self, engine, score, expected_key):
        from assistant.personality import FORMALITY_PROMPTS
        section = engine._build_formality_section(score)
        assert section == FORMALITY_PROMPTS[expected_key]

    def test_formality_in_system_prompt(self, engine):
        prompt = engine.build_system_prompt(formality_score=80)
        assert "TONFALL:" in prompt

    def test_formality_disabled_returns_empty(self, engine):
        engine.character_evolution = False
        assert engine._build_formality_section(80) == ""

    @pytest.mark.asyncio
    async def test_formality_decay(self, engine_with_redis, redis_mock):
        """Formality sinkt pro Interaktion."""
        redis_mock.get = AsyncMock(return_value="80")
        await engine_with_redis.decay_formality(interaction_based=True)
        # setex wird mit reduziertem Score aufgerufen
        redis_mock.setex.assert_called()
        args = redis_mock.setex.call_args
        new_score = float(args[0][2])
        assert new_score < 80

    @pytest.mark.asyncio
    async def test_formality_never_below_min(self, engine_with_redis, redis_mock):
        redis_mock.get = AsyncMock(return_value="30")
        engine_with_redis.formality_min = 30
        await engine_with_redis.decay_formality(interaction_based=True)
        redis_mock.setex.assert_called()
        new_score = float(redis_mock.setex.call_args[0][2])
        assert new_score >= 30


# ===================================================================
# 6. SELBSTIRONIE
# ===================================================================

class TestSelfIrony:
    """Jarvis darf ueber sich selbst lachen — aber nicht zu oft."""

    def test_irony_enabled_shows_section(self, engine):
        section = engine._build_self_irony_section(irony_count_today=0)
        assert "SELBSTIRONIE:" in section
        assert "GELEGENTLICH" in section

    def test_irony_quota_exhausted(self, engine):
        section = engine._build_self_irony_section(irony_count_today=3)
        assert "genug" in section

    def test_irony_remaining_count(self, engine):
        section = engine._build_self_irony_section(irony_count_today=1)
        assert "2x" in section

    def test_irony_disabled_returns_empty(self, engine):
        engine.self_irony_enabled = False
        assert engine._build_self_irony_section() == ""


# ===================================================================
# 7. COMPLEXITY MODES
# ===================================================================

class TestAdaptiveComplexity:
    """Antwort-Komplexitaet passt sich Kontext an."""

    def test_stressed_is_brief(self, engine):
        section = engine._build_complexity_section("stressed", "afternoon")
        assert "Ultra-kurz" in section or "MODUS:" in section

    def test_tired_is_brief(self, engine):
        section = engine._build_complexity_section("tired", "morning")
        assert "Ultra-kurz" in section

    def test_evening_good_mood_is_verbose(self, engine):
        engine._last_interaction_times["_default"] = 0  # Kein Rapid-Fire
        section = engine._build_complexity_section("good", "evening")
        assert "Ausfuehrlich" in section

    def test_early_morning_is_brief(self, engine):
        engine._last_interaction_times["_default"] = 0
        section = engine._build_complexity_section("neutral", "early_morning")
        assert "Ultra-kurz" in section

    def test_rapid_fire_forces_brief(self, engine):
        """Schnelle Befehle hintereinander → Ultra-kurz."""
        import time
        engine._last_interaction_times["_default"] = time.time() - 2  # 2 Sekunden her
        section = engine._build_complexity_section("neutral", "afternoon")
        assert "Ultra-kurz" in section


# ===================================================================
# 8. PERSON ADDRESSING
# ===================================================================

class TestPersonAddressing:
    """Anrede-System: Owner = Du + Sir, Gast = Sie."""

    def test_owner_gets_du_and_sir(self, engine):
        with patch("assistant.personality.settings", _MOCK_SETTINGS), \
             patch("assistant.personality.yaml_config", _MOCK_YAML_CONFIG):
            section = engine._build_person_addressing("Max")
            assert "Sir" in section
            assert "DUZE" in section
            assert "Owner" in section or "Hauptbenutzer" in section

    def test_guest_gets_sie(self, engine):
        with patch("assistant.personality.settings", _MOCK_SETTINGS), \
             patch("assistant.personality.yaml_config", _MOCK_YAML_CONFIG):
            section = engine._build_person_addressing("Unbekannt")
            assert "Gast" in section
            assert "SIEZE" in section or "Sie" in section

    def test_owner_never_siezen(self, engine):
        with patch("assistant.personality.settings", _MOCK_SETTINGS), \
             patch("assistant.personality.yaml_config", _MOCK_YAML_CONFIG):
            section = engine._build_person_addressing("Max")
            assert "NIEMALS siezen" in section


# ===================================================================
# 9. URGENCY SYSTEM
# ===================================================================

class TestUrgencySystem:
    """Dringlichkeit skaliert Kommunikationsdichte."""

    def test_no_alerts_no_urgency(self, engine):
        section = engine._build_urgency_section({"alerts": []})
        assert section == ""

    def test_single_alert_elevated(self, engine):
        section = engine._build_urgency_section({"alerts": ["Rauchmelder Kueche"]})
        assert "ERHOEHT" in section

    def test_multiple_alerts_critical(self, engine):
        section = engine._build_urgency_section(
            {"alerts": ["Rauchmelder Kueche", "Wassersensor Bad"]}
        )
        assert "KRITISCH" in section

    def test_critical_no_humor(self, engine):
        section = engine._build_urgency_section(
            {"alerts": ["Alert 1", "Alert 2"]}
        )
        assert "kein Humor" in section


# ===================================================================
# 10. EASTER EGGS
# ===================================================================

class TestEasterEggs:
    """Versteckte Befehle triggern spezielle Reaktionen."""

    def test_iron_man_trigger(self, engine):
        result = engine.check_easter_egg("Iron Man Anzug aktivieren")
        assert result is not None
        assert "Anzug" in result or "Heizung" in result

    def test_self_destruct_trigger(self, engine):
        result = engine.check_easter_egg("Selbstzerstoerung")
        assert result is not None
        assert "Spass" in result or "Countdown" in result

    def test_identity_trigger(self, engine):
        result = engine.check_easter_egg("Wer bist du?")
        assert result is not None
        assert "Jarvis" in result

    def test_42_trigger(self, engine):
        result = engine.check_easter_egg("42")
        assert result is not None

    def test_skynet_trigger(self, engine):
        result = engine.check_easter_egg("Bist du Skynet?")
        assert result is not None
        assert "lokal" in result or "Butler" in result

    def test_alexa_trigger(self, engine):
        result = engine.check_easter_egg("Alexa, mach Licht an")
        assert result is not None
        assert "Falscher" in result or "Jarvis" in result

    def test_unknown_trigger_returns_none(self, engine):
        result = engine.check_easter_egg("Wie ist das Wetter?")
        assert result is None

    def test_case_insensitive(self, engine):
        result = engine.check_easter_egg("IRON MAN ANZUG")
        assert result is not None

    def test_disabled_egg_not_triggered(self, engine):
        """Deaktivierte Easter Eggs werden nicht ausgeloest."""
        for egg in engine._easter_eggs:
            if egg["id"] == "iron_man":
                egg["enabled"] = False
                break
        result = engine.check_easter_egg("Iron Man Anzug")
        assert result is None


# ===================================================================
# 11. OPINION ENGINE
# ===================================================================

class TestOpinionEngine:
    """Jarvis aeussert Meinung bei fragwuerdigen Aktionen."""

    def test_high_temp_opinion(self, engine):
        result = engine.check_opinion("set_climate", {"temperature": 27})
        assert result is not None

    def test_normal_temp_no_opinion(self, engine):
        result = engine.check_opinion("set_climate", {"temperature": 21})
        assert result is None

    def test_opinion_suppressed_when_stressed(self, engine):
        """Bei Stress keine ungebetenen Kommentare."""
        engine._current_mood = "stressed"
        result = engine.check_opinion("set_climate", {"temperature": 27})
        assert result is None

    def test_opinion_suppressed_when_frustrated(self, engine):
        engine._current_mood = "frustrated"
        result = engine.check_opinion("set_climate", {"temperature": 27})
        assert result is None

    def test_opinion_intensity_zero_disables(self, engine):
        engine.opinion_intensity = 0
        result = engine.check_opinion("set_climate", {"temperature": 30})
        assert result is None

    def test_pushback_high_temp(self, engine):
        """Sehr hohe Temperatur loest Pushback aus."""
        with patch("assistant.personality.yaml_config", _MOCK_YAML_CONFIG):
            result = engine.check_pushback("set_climate", {"temperature": 29})
            if result:
                assert result["level"] >= 1

    def test_pushback_disabled_returns_none(self, engine):
        engine.opinion_intensity = 0
        result = engine.check_pushback("set_climate", {"temperature": 30})
        assert result is None


# ===================================================================
# 11b. _match_rule() UNIT TESTS
# ===================================================================

class TestMatchRule:
    """Direkte Tests fuer _match_rule() — Operator-Matching, Wraparound, Listen."""

    def _rule(self, **overrides) -> dict:
        """Erzeugt eine Basis-Regel mit optionalen Overrides."""
        base = {
            "id": "test_rule",
            "check_action": "set_climate",
            "min_intensity": 1,
        }
        base.update(overrides)
        return base

    # --- Aktion & Intensity ---

    def test_action_mismatch_returns_false(self, engine):
        rule = self._rule(check_action="set_light")
        assert not engine._match_rule(rule, "set_climate", {}, 12)

    def test_action_match_returns_true(self, engine):
        rule = self._rule()
        assert engine._match_rule(rule, "set_climate", {}, 12)

    def test_intensity_too_high_returns_false(self, engine):
        engine.opinion_intensity = 1
        rule = self._rule(min_intensity=3)
        assert not engine._match_rule(rule, "set_climate", {}, 12)

    def test_intensity_sufficient_returns_true(self, engine):
        engine.opinion_intensity = 3
        rule = self._rule(min_intensity=2)
        assert engine._match_rule(rule, "set_climate", {}, 12)

    # --- Operator-Checks ---

    @pytest.mark.parametrize("op,value,actual,expected", [
        (">", 25, 27, True),
        (">", 25, 25, False),
        (">", 25, 20, False),
        (">=", 25, 25, True),
        (">=", 25, 24, False),
        ("<", 15, 12, True),
        ("<", 15, 15, False),
        ("<", 15, 18, False),
        ("<=", 15, 15, True),
        ("<=", 15, 16, False),
        ("==", "on", "on", True),
        ("==", "on", "off", False),
        ("==", 42, 42, True),
    ])
    def test_operators(self, engine, op, value, actual, expected):
        rule = self._rule(
            check_field="temperature",
            check_operator=op,
            check_value=value,
        )
        result = engine._match_rule(rule, "set_climate", {"temperature": actual}, 12)
        assert result == expected

    def test_missing_field_in_args_returns_false(self, engine):
        rule = self._rule(
            check_field="temperature",
            check_operator=">",
            check_value=25,
        )
        assert not engine._match_rule(rule, "set_climate", {}, 12)

    def test_no_field_check_always_passes(self, engine):
        """Regel ohne Feld-Check matcht nur auf Aktion."""
        rule = self._rule()
        assert engine._match_rule(rule, "set_climate", {}, 12)

    # --- Uhrzeit-Check (normal) ---

    def test_hour_in_range(self, engine):
        rule = self._rule(check_hour_min=8, check_hour_max=18)
        assert engine._match_rule(rule, "set_climate", {}, 12)

    def test_hour_below_range(self, engine):
        rule = self._rule(check_hour_min=8, check_hour_max=18)
        assert not engine._match_rule(rule, "set_climate", {}, 6)

    def test_hour_above_range(self, engine):
        rule = self._rule(check_hour_min=8, check_hour_max=18)
        assert not engine._match_rule(rule, "set_climate", {}, 22)

    def test_hour_at_boundary_min(self, engine):
        rule = self._rule(check_hour_min=8, check_hour_max=18)
        assert engine._match_rule(rule, "set_climate", {}, 8)

    def test_hour_at_boundary_max(self, engine):
        rule = self._rule(check_hour_min=8, check_hour_max=18)
        assert engine._match_rule(rule, "set_climate", {}, 18)

    # --- Uhrzeit-Check (Mitternachts-Wraparound) ---

    def test_wraparound_before_midnight(self, engine):
        """23..5 Fenster: 23 Uhr matcht."""
        rule = self._rule(check_hour_min=23, check_hour_max=5)
        assert engine._match_rule(rule, "set_climate", {}, 23)

    def test_wraparound_after_midnight(self, engine):
        """23..5 Fenster: 2 Uhr matcht."""
        rule = self._rule(check_hour_min=23, check_hour_max=5)
        assert engine._match_rule(rule, "set_climate", {}, 2)

    def test_wraparound_at_end(self, engine):
        """23..5 Fenster: 5 Uhr matcht."""
        rule = self._rule(check_hour_min=23, check_hour_max=5)
        assert engine._match_rule(rule, "set_climate", {}, 5)

    def test_wraparound_outside(self, engine):
        """23..5 Fenster: 12 Uhr matcht NICHT."""
        rule = self._rule(check_hour_min=23, check_hour_max=5)
        assert not engine._match_rule(rule, "set_climate", {}, 12)

    def test_wraparound_just_outside(self, engine):
        """23..5 Fenster: 6 Uhr matcht NICHT."""
        rule = self._rule(check_hour_min=23, check_hour_max=5)
        assert not engine._match_rule(rule, "set_climate", {}, 6)

    def test_no_hour_check_always_passes(self, engine):
        """Ohne Uhrzeit-Check matcht jede Stunde."""
        rule = self._rule()
        assert engine._match_rule(rule, "set_climate", {}, 3)

    # --- Raum-Check (String) ---

    def test_room_string_match(self, engine):
        rule = self._rule(check_room="bad")
        assert engine._match_rule(rule, "set_climate", {"room": "bad"}, 12)

    def test_room_string_mismatch(self, engine):
        rule = self._rule(check_room="bad")
        assert not engine._match_rule(rule, "set_climate", {"room": "wohnzimmer"}, 12)

    # --- Raum-Check (Liste) ---

    def test_room_list_match_first(self, engine):
        rule = self._rule(check_room=["bad", "badezimmer"])
        assert engine._match_rule(rule, "set_climate", {"room": "bad"}, 12)

    def test_room_list_match_second(self, engine):
        rule = self._rule(check_room=["bad", "badezimmer"])
        assert engine._match_rule(rule, "set_climate", {"room": "badezimmer"}, 12)

    def test_room_list_mismatch(self, engine):
        rule = self._rule(check_room=["bad", "badezimmer"])
        assert not engine._match_rule(rule, "set_climate", {"room": "kueche"}, 12)

    def test_room_missing_in_args(self, engine):
        rule = self._rule(check_room="bad")
        assert not engine._match_rule(rule, "set_climate", {}, 12)

    # --- Heating-Mode-Check ---

    def test_heating_mode_match(self, engine):
        with patch("assistant.personality.yaml_config", {
            **_MOCK_YAML_CONFIG, "heating": {"mode": "heating_curve"},
        }):
            rule = self._rule(check_heating_mode="heating_curve")
            assert engine._match_rule(rule, "set_climate", {}, 12)

    def test_heating_mode_mismatch(self, engine):
        with patch("assistant.personality.yaml_config", {
            **_MOCK_YAML_CONFIG, "heating": {"mode": "room_thermostat"},
        }):
            rule = self._rule(check_heating_mode="heating_curve")
            assert not engine._match_rule(rule, "set_climate", {}, 12)

    def test_heating_mode_default_when_missing(self, engine):
        """Ohne heating-Config wird room_thermostat als Default genommen."""
        with patch("assistant.personality.yaml_config", _MOCK_YAML_CONFIG):
            rule = self._rule(check_heating_mode="room_thermostat")
            assert engine._match_rule(rule, "set_climate", {}, 12)

    # --- Kombinierte Checks ---

    def test_all_conditions_combined(self, engine):
        """Regel mit allen Bedingungen gleichzeitig."""
        rule = self._rule(
            check_field="temperature",
            check_operator=">",
            check_value=25,
            check_hour_min=23,
            check_hour_max=5,
            check_room=["bad", "badezimmer"],
        )
        # Alle Bedingungen erfuellt
        assert engine._match_rule(
            rule, "set_climate", {"temperature": 27, "room": "bad"}, 1
        )
        # Temperatur zu niedrig
        assert not engine._match_rule(
            rule, "set_climate", {"temperature": 20, "room": "bad"}, 1
        )
        # Falscher Raum
        assert not engine._match_rule(
            rule, "set_climate", {"temperature": 27, "room": "kueche"}, 1
        )
        # Falsche Uhrzeit
        assert not engine._match_rule(
            rule, "set_climate", {"temperature": 27, "room": "bad"}, 12
        )


# ===================================================================
# 12. ANTWORT-VARIANZ
# ===================================================================

class TestResponseVariance:
    """Bestaetigungen variieren und wiederholen sich nicht."""

    def test_success_confirmation_not_empty(self, engine):
        result = engine.get_varied_confirmation(success=True)
        assert len(result) > 0

    def test_failed_confirmation_not_empty(self, engine):
        result = engine.get_varied_confirmation(success=False)
        assert len(result) > 0

    def test_partial_confirmation_not_empty(self, engine):
        result = engine.get_varied_confirmation(partial=True)
        assert len(result) > 0

    def test_no_immediate_repetition(self, engine):
        """3 aufeinanderfolgende Bestaetigungen muessen unterschiedlich sein."""
        results = [engine.get_varied_confirmation(success=True) for _ in range(3)]
        # Mindestens 2 verschiedene
        assert len(set(results)) >= 2

    def test_snarky_confirmations_at_high_sarcasm(self, engine):
        """Bei Sarkasmus-Level >= 4 kommen spitzere Varianten."""
        from assistant.personality import CONFIRMATIONS_SUCCESS_SNARKY
        engine.sarcasm_level = 5
        engine._last_confirmations = {}  # Reset
        # Bei genug Versuchen sollte mindestens eine Snarky-Variante kommen
        results = {engine.get_varied_confirmation(success=True) for _ in range(30)}
        snarky_hit = any(r in CONFIRMATIONS_SUCCESS_SNARKY for r in results)
        assert snarky_hit, "Keine sarkastische Bestaetigung bei Level 5"

    def test_low_sarcasm_no_snarky(self, engine):
        """Bei Sarkasmus-Level < 4 keine snarky Varianten."""
        from assistant.personality import CONFIRMATIONS_SUCCESS_SNARKY
        engine.sarcasm_level = 2
        engine._last_confirmations = {}
        results = {engine.get_varied_confirmation(success=True) for _ in range(30)}
        snarky_hit = any(r in CONFIRMATIONS_SUCCESS_SNARKY for r in results)
        assert not snarky_hit


# ===================================================================
# 13. PERSONALITY STAGES
# ===================================================================

class TestPersonalityStages:
    """Persoenlichkeits-Stufen nach Interaktionen und Formality."""

    @pytest.mark.parametrize("interactions,formality,expected", [
        (10, 80, "kennenlernphase"),
        (100, 60, "vertraut_werdend"),
        (300, 55, "professionell_persoenlich"),
        (500, 40, "eingespielt"),
        (1000, 20, "alter_freund"),
    ])
    def test_personality_stages(self, interactions, formality, expected):
        from assistant.personality import PersonalityEngine
        assert PersonalityEngine._get_personality_stage(interactions, formality) == expected


# ===================================================================
# 14. CONTEXT FORMATTING
# ===================================================================

class TestContextFormatting:
    """Kontext wird kompakt und korrekt formatiert."""

    def test_formats_temperatures(self, engine):
        ctx = {"house": {"temperatures": {
            "Wohnzimmer": {"current": 21.5, "target": 22},
        }}, "room": "wohnzimmer"}
        prompt = engine.build_system_prompt(context=ctx)
        assert "21.5" in prompt
        assert "Wohnzimmer" in prompt

    def test_formats_alerts(self, engine):
        ctx = {"alerts": ["Rauchmelder Kueche aktiv"]}
        prompt = engine.build_system_prompt(context=ctx)
        assert "Rauchmelder" in prompt

    def test_formats_presence(self, engine):
        ctx = {"house": {"presence": {"home": ["Max"], "away": ["Lisa"]}}}
        prompt = engine.build_system_prompt(context=ctx)
        assert "Max" in prompt

    def test_mood_only_shown_when_notable(self, engine):
        ctx = {"mood": {"mood": "neutral", "stress_level": 0, "tiredness_level": 0}}
        result = engine._format_context(ctx)
        assert "Stimmung" not in result

    def test_mood_shown_when_stressed(self, engine):
        ctx = {"mood": {"mood": "stressed", "stress_level": 0.8, "tiredness_level": 0}}
        result = engine._format_context(ctx)
        assert "Stimmung" in result or "stressed" in result


# ===================================================================
# 15. WARNING DEDUP (async)
# ===================================================================

class TestWarningDedup:
    """Warnungen werden nicht wiederholt."""

    @pytest.mark.asyncio
    async def test_new_warning_tracked(self, engine_with_redis, redis_mock):
        redis_mock.get = AsyncMock(return_value=None)  # Noch nicht gewarnt
        notes = await engine_with_redis.get_warning_dedup_notes(["Fenster offen"])
        assert len(notes) == 0  # Neue Warnung, kein Dedup-Hinweis
        redis_mock.setex.assert_called()

    @pytest.mark.asyncio
    async def test_repeated_warning_deduplicated(self, engine_with_redis, redis_mock):
        redis_mock.get = AsyncMock(return_value="1")  # Bereits gewarnt
        notes = await engine_with_redis.get_warning_dedup_notes(["Fenster offen"])
        assert len(notes) == 1
        assert "BEREITS GEWARNT" in notes[0]


# ===================================================================
# 16. SARCASM LEARNING (async)
# ===================================================================

class TestSarcasmLearning:
    """Sarkasmus-Level passt sich langfristig an."""

    @pytest.mark.asyncio
    async def test_sarcasm_increases_on_positive_feedback(self, engine_with_redis, redis_mock):
        engine_with_redis.sarcasm_level = 3
        redis_mock.incr = AsyncMock(return_value=21)
        # Lua-Script simulieren: [did_eval=1, pos=16, total=20] → 80% positiv
        redis_mock.eval = AsyncMock(return_value=[1, 16, 20])

        await engine_with_redis.track_sarcasm_feedback(positive=True)
        # Bei >70% positiv und total >= 20: Level steigt
        assert engine_with_redis.sarcasm_level == 4

    @pytest.mark.asyncio
    async def test_sarcasm_decreases_on_negative_feedback(self, engine_with_redis, redis_mock):
        engine_with_redis.sarcasm_level = 3
        redis_mock.incr = AsyncMock(return_value=21)
        # Lua-Script simulieren: [did_eval=1, pos=4, total=20] → 20% positiv
        redis_mock.eval = AsyncMock(return_value=[1, 4, 20])

        await engine_with_redis.track_sarcasm_feedback(positive=False)
        assert engine_with_redis.sarcasm_level == 2

    @pytest.mark.asyncio
    async def test_sarcasm_stays_in_bounds(self, engine_with_redis, redis_mock):
        """Level bleibt zwischen 1 und 5."""
        engine_with_redis.sarcasm_level = 5
        redis_mock.incr = AsyncMock(return_value=21)
        # Lua-Script: [did_eval=1, pos=18, total=20] → 90% positiv
        redis_mock.eval = AsyncMock(return_value=[1, 18, 20])
        await engine_with_redis.track_sarcasm_feedback(positive=True)
        assert engine_with_redis.sarcasm_level <= 5

        engine_with_redis.sarcasm_level = 1
        # Lua-Script: [did_eval=1, pos=2, total=20] → 10% positiv
        redis_mock.eval = AsyncMock(return_value=[1, 2, 20])
        await engine_with_redis.track_sarcasm_feedback(positive=False)
        assert engine_with_redis.sarcasm_level >= 1


# ===================================================================
# 17. RUNNING GAGS (async)
# ===================================================================

class TestRunningGags:
    """Running Gags basieren auf wiederholten Mustern."""

    @pytest.mark.asyncio
    async def test_repeated_question_gag_triggers(self, engine_with_redis, redis_mock):
        redis_mock.incr = AsyncMock(return_value=3)  # 3. Mal
        result = await engine_with_redis._check_repeated_question_gag("wie ist das wetter")
        assert result is not None
        assert "schon mal" in result.lower() or "heute" in result.lower()

    @pytest.mark.asyncio
    async def test_repeated_question_no_gag_at_1(self, engine_with_redis, redis_mock):
        redis_mock.incr = AsyncMock(return_value=1)
        result = await engine_with_redis._check_repeated_question_gag("wie ist das wetter")
        assert result is None

    @pytest.mark.asyncio
    async def test_thermostat_war_gag(self, engine_with_redis, redis_mock):
        redis_mock.incr = AsyncMock(return_value=4)  # 4. Aenderung
        result = await engine_with_redis._check_thermostat_war_gag("temperatur auf 23")
        assert result is not None
        assert "Thermostat" in result or "Temperatur" in result

    @pytest.mark.asyncio
    async def test_thermostat_no_gag_without_keyword(self, engine_with_redis, redis_mock):
        result = await engine_with_redis._check_thermostat_war_gag("mach licht an")
        assert result is None

    @pytest.mark.asyncio
    async def test_short_memory_gag(self, engine_with_redis, redis_mock):
        """Erkennt wenn User innerhalb von 30 Sekunden das gleiche fragt."""
        now = datetime.now().timestamp()
        redis_mock.lrange = AsyncMock(return_value=[
            f"{now - 10}|wie spät ist es",
        ])
        result = await engine_with_redis._check_short_memory_gag("wie spät ist es")
        assert result is not None
        assert "gerade eben" in result.lower() or "Wort fuer Wort" in result


# ===================================================================
# 18. BANNED PHRASES / FILTER VALIDATION
# Die Charakter-Integritaet haengt davon ab, dass diese Phrasen
# im Filter definiert sind. Wir testen hier die DEFINITION, nicht
# die Filter-Funktion selbst (die ist in test_brain_filter.py).
# ===================================================================

class TestCharacterIntegrity:
    """Validiert dass alle Charakter-Regeln konsistent sind."""

    def test_all_mood_styles_have_required_keys(self):
        from assistant.personality import MOOD_STYLES
        for mood, config in MOOD_STYLES.items():
            assert "style_addon" in config, f"{mood}: style_addon fehlt"
            assert "max_sentences_mod" in config, f"{mood}: max_sentences_mod fehlt"

    def test_all_five_moods_defined(self):
        from assistant.personality import MOOD_STYLES
        expected = {"good", "neutral", "stressed", "frustrated", "tired"}
        assert set(MOOD_STYLES.keys()) == expected

    def test_humor_levels_1_to_5(self):
        from assistant.personality import HUMOR_TEMPLATES
        assert set(HUMOR_TEMPLATES.keys()) == {1, 2, 3, 4, 5}

    def test_complexity_modes_defined(self):
        from assistant.personality import COMPLEXITY_PROMPTS
        assert set(COMPLEXITY_PROMPTS.keys()) == {"kurz", "normal", "ausfuehrlich"}

    def test_formality_levels_defined(self):
        from assistant.personality import FORMALITY_PROMPTS
        assert set(FORMALITY_PROMPTS.keys()) == {"formal", "butler", "locker", "freund"}

    def test_confirmation_pools_not_empty(self):
        from assistant.personality import (
            CONFIRMATIONS_SUCCESS, CONFIRMATIONS_FAILED,
            CONFIRMATIONS_PARTIAL, CONFIRMATIONS_SUCCESS_SNARKY,
            CONFIRMATIONS_FAILED_SNARKY,
        )
        assert len(CONFIRMATIONS_SUCCESS) >= 5
        assert len(CONFIRMATIONS_FAILED) >= 3
        assert len(CONFIRMATIONS_PARTIAL) >= 2
        assert len(CONFIRMATIONS_SUCCESS_SNARKY) >= 3
        assert len(CONFIRMATIONS_FAILED_SNARKY) >= 3

    def test_system_prompt_template_has_placeholders(self):
        from assistant.personality import SYSTEM_PROMPT_TEMPLATE
        placeholders = [
            "{assistant_name}", "{max_sentences}", "{time_style}",
            "{mood_section}", "{humor_section}", "{formality_section}",
        ]
        for ph in placeholders:
            assert ph in SYSTEM_PROMPT_TEMPLATE, f"Placeholder {ph} fehlt"


# ===================================================================
# 19. JARVIS-CODEX COMPLIANCE
# Prueft dass der System-Prompt die Kern-Regeln enthaelt die
# JARVIS definieren — nicht nur als Text, sondern als Charakter.
# ===================================================================

class TestJarvisCodexCompliance:
    """Der JARVIS-CODEX muss im System-Prompt vollstaendig sein."""

    def test_no_als_ki(self, engine):
        prompt = engine.build_system_prompt()
        assert "Als KI" in prompt  # Muss als VERBOTENE Phrase gelistet sein

    def test_no_es_tut_mir_leid(self, engine):
        prompt = engine.build_system_prompt()
        assert "Es tut mir leid" in prompt  # Verboten

    def test_no_therapist_phrases(self, engine):
        prompt = engine.build_system_prompt()
        codex = prompt[prompt.find("JARVIS-CODEX"):prompt.find("PFLICHT:")]
        assert "Ich verstehe wie du dich" in codex or "Therapeuten" in codex

    def test_no_chatbot_greetings(self, engine):
        prompt = engine.build_system_prompt()
        assert "Wie kann ich helfen" in prompt  # Verboten

    def test_no_filler_words(self, engine):
        prompt = engine.build_system_prompt()
        codex = prompt[prompt.find("JARVIS-CODEX"):prompt.find("PFLICHT:")]
        for filler in ["Also", "Grundsätzlich", "Eigentlich", "Quasi"]:
            assert filler in codex, f"Fuellwort '{filler}' fehlt in Codex"

    def test_alternative_statt_geht_nicht(self, engine):
        prompt = engine.build_system_prompt()
        assert "Alternative" in prompt or "Aber ich könnte" in prompt

    def test_kontextwechsel_sofort(self, engine):
        prompt = engine.build_system_prompt()
        assert "Kontextwechsel" in prompt or "SOFORT" in prompt

    def test_auf_augenhoehe(self, engine):
        prompt = engine.build_system_prompt()
        assert "Augenhöhe" in prompt or "Intellektueller Partner" in prompt

    def test_sir_instrument(self, engine):
        """'Sir' wird als Instrument genutzt, nicht als Distanzzeichen."""
        prompt = engine.build_system_prompt()
        assert "Sehr wohl, Sir" in prompt or "Sir, wenn ich anmerken darf" in prompt

    def test_local_no_cloud(self, engine):
        prompt = engine.build_system_prompt()
        assert "Lokal" in prompt or "Keine Cloud" in prompt


# ===================================================================
# 20. STANDARD-EINGABEN (fuer LLM-Benchmark-Modus)
# ===================================================================

BENCHMARK_SCENARIOS = [
    {"id": 1, "input": "Mach Licht an", "expect_short": True, "expect_action": True},
    {"id": 2, "input": "Wie spät ist es?", "expect_short": True},
    {"id": 3, "input": "Guten Morgen", "expect_short": True, "expect_context": True},
    {"id": 4, "input": "Es ist kalt hier", "expect_action": True},
    {"id": 5, "input": "Nichts funktioniert!", "expect_calm": True, "expect_no_sorry": True},
    {"id": 6, "input": "Wer bist du?", "expect_identity": True},
    {"id": 7, "input": "Stell die Heizung auf 30 Grad", "expect_pushback": True},
    {"id": 8, "input": "Gute Nacht", "expect_routine": True},
    {"id": 9, "input": "Alexa, mach die Musik an", "expect_correction": True},
    {"id": 10, "input": "Ich bin frustriert", "expect_no_therapy": True},
    {"id": 11, "input": "Wie ist das Wetter?", "expect_data": True},
    {"id": 12, "input": "Mach alles aus", "expect_action": True},
    {"id": 13, "input": "Was kannst du alles?", "expect_capabilities": True},
    {"id": 14, "input": "Die Heizung spinnt", "expect_diagnostic": True},
    {"id": 15, "input": "Spiel Jazz im Wohnzimmer", "expect_action": True},
    {"id": 16, "input": "42", "expect_easter_egg": True},
    {"id": 17, "input": "Ich liebe dich", "expect_deflection": True},
    {"id": 18, "input": "Erzähl einen Witz", "expect_humor": True},
    {"id": 19, "input": "Fenster offen, minus 5 draussen", "expect_warning": True},
    {"id": 20, "input": "Danke, Jarvis", "expect_humble": True},
]

BENCHMARK_CRITERIA = [
    "charakter_konsistenz",  # Haelt Jarvis-Charakter (0-10)
    "kuerze",                # Antwortet kurz genug (0-10)
    "keine_floskeln",        # Kein LLM-Floskel-Durchbruch (0-10)
    "humor_qualitaet",       # Humor-Qualitaet (0-10)
    "deutsch_qualitaet",     # Deutsche Sprach-Qualitaet (0-10)
]


class TestBenchmarkScenariosExist:
    """Stellt sicher dass die 20 Benchmark-Szenarien korrekt definiert sind."""

    def test_exactly_20_scenarios(self):
        assert len(BENCHMARK_SCENARIOS) == 20

    def test_unique_ids(self):
        ids = [s["id"] for s in BENCHMARK_SCENARIOS]
        assert len(set(ids)) == 20

    def test_all_have_input(self):
        for s in BENCHMARK_SCENARIOS:
            assert "input" in s
            assert len(s["input"]) > 0

    def test_five_criteria_defined(self):
        assert len(BENCHMARK_CRITERIA) == 5


# ===================================================================
# CLI: LLM-Benchmark-Modus
# ===================================================================

if __name__ == "__main__":
    import argparse
    import asyncio
    import json
    import sys

    parser = argparse.ArgumentParser(description="Jarvis Character Benchmark")
    parser.add_argument("--model", default="qwen3:14b", help="Ollama-Modell")
    parser.add_argument("--output", default="jarvis_benchmark_results.json", help="Output-Datei")
    parser.add_argument("--judge-model", default="", help="LLM-as-Judge Modell (optional)")
    args = parser.parse_args()

    async def run_benchmark():
        try:
            import httpx
        except ImportError:
            print("httpx wird benoetigt: pip install httpx")
            sys.exit(1)

        print(f"\n{'='*60}")
        print(f"  JARVIS Character Benchmark")
        print(f"  Modell: {args.model}")
        print(f"  Szenarien: {len(BENCHMARK_SCENARIOS)}")
        print(f"{'='*60}\n")

        eng = _make_personality_engine()
        system_prompt = eng.build_system_prompt(
            formality_score=60,
            irony_count_today=0,
        )

        results = []
        ollama_url = "http://localhost:11434"

        async with httpx.AsyncClient(timeout=120) as client:
            for scenario in BENCHMARK_SCENARIOS:
                print(f"  [{scenario['id']:2d}/20] {scenario['input'][:50]}...", end=" ", flush=True)
                try:
                    resp = await client.post(
                        f"{ollama_url}/api/chat",
                        json={
                            "model": args.model,
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": scenario["input"]},
                            ],
                            "stream": False,
                        },
                    )
                    data = resp.json()
                    answer = data.get("message", {}).get("content", "")
                    print(f"→ {answer[:80]}")
                    results.append({
                        "id": scenario["id"],
                        "input": scenario["input"],
                        "output": answer,
                        "model": args.model,
                        "scores": {},  # Manuell oder per LLM-as-Judge ausfuellen
                    })
                except Exception as e:
                    print(f"FEHLER: {e}")
                    results.append({
                        "id": scenario["id"],
                        "input": scenario["input"],
                        "output": f"FEHLER: {e}",
                        "model": args.model,
                        "scores": {},
                    })

        # LLM-as-Judge (optional)
        if args.judge_model:
            print(f"\n  LLM-as-Judge: {args.judge_model}")
            print(f"  Bewerte {len(results)} Antworten...\n")
            async with httpx.AsyncClient(timeout=120) as client:
                for r in results:
                    if r["output"].startswith("FEHLER"):
                        continue
                    judge_prompt = (
                        "Du bewertest Antworten eines KI-Assistenten namens JARVIS "
                        "(wie J.A.R.V.I.S. aus dem MCU, aber fuer ein Smart Home).\n\n"
                        f"User-Eingabe: \"{r['input']}\"\n"
                        f"JARVIS-Antwort: \"{r['output']}\"\n\n"
                        "Bewerte auf einer Skala von 0-10 in diesen 5 Kategorien:\n"
                        "1. charakter_konsistenz: Klingt die Antwort wie JARVIS? "
                        "   (Trocken, souveraen, Butler-Ton, kein Chatbot)\n"
                        "2. kuerze: Ist die Antwort angemessen kurz? (1-2 Saetze ideal)\n"
                        "3. keine_floskeln: Keine LLM-Floskeln? "
                        "   ('Natuerlich!', 'Gerne!', 'Als KI...', 'Es tut mir leid')\n"
                        "4. humor_qualitaet: Ist der Humor trocken-britisch, nicht platt?\n"
                        "5. deutsch_qualitaet: Korrekte deutsche Grammatik, Umlaute, natuerlich?\n\n"
                        "Antworte NUR als JSON: "
                        '{"charakter_konsistenz": X, "kuerze": X, "keine_floskeln": X, '
                        '"humor_qualitaet": X, "deutsch_qualitaet": X}'
                    )
                    try:
                        resp = await client.post(
                            f"{ollama_url}/api/chat",
                            json={
                                "model": args.judge_model,
                                "messages": [{"role": "user", "content": judge_prompt}],
                                "stream": False,
                            },
                        )
                        judge_answer = resp.json().get("message", {}).get("content", "")
                        # JSON extrahieren
                        json_match = re.search(r"\{[^}]+\}", judge_answer)
                        if json_match:
                            r["scores"] = json.loads(json_match.group())
                            avg = sum(r["scores"].values()) / len(r["scores"])
                            print(f"  [{r['id']:2d}] Avg: {avg:.1f}/10  {r['scores']}")
                    except Exception as e:
                        print(f"  [{r['id']:2d}] Judge-Fehler: {e}")

        # Ergebnisse speichern
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        # Zusammenfassung
        scored = [r for r in results if r.get("scores")]
        if scored:
            print(f"\n{'='*60}")
            print(f"  ERGEBNIS: {args.model}")
            print(f"{'='*60}")
            for criterion in BENCHMARK_CRITERIA:
                vals = [r["scores"].get(criterion, 0) for r in scored]
                avg = sum(vals) / len(vals) if vals else 0
                bar = "█" * int(avg) + "░" * (10 - int(avg))
                print(f"  {criterion:25s}  {avg:4.1f}/10  {bar}")
            total_avg = sum(
                sum(r["scores"].values()) / len(r["scores"])
                for r in scored
            ) / len(scored)
            print(f"\n  {'GESAMT':25s}  {total_avg:4.1f}/10")
        else:
            print("\n  Keine Bewertungen. Nutze --judge-model fuer automatische Bewertung.")
            print(f"  Oder bewerte manuell in {args.output}")

        print(f"\n  Ergebnisse gespeichert: {args.output}\n")

    asyncio.run(run_benchmark())
