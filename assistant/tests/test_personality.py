"""
Tests fuer PersonalityEngine — Persoenlichkeit und Antwort-Stil.

Testet:
- Initialisierung und Config
- Mood-Styles
- Humor-Templates
- Easter Eggs
- Opinion-Rules Matching
- Bestaetigungen (Success/Failed/Partial)
- Komplexitaets-Modi
- Formality-Stufen
- Person-Profile
- Reload Config
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from assistant.personality import (
    PersonalityEngine,
    MOOD_STYLES,
    HUMOR_TEMPLATES,
    COMPLEXITY_PROMPTS,
    FORMALITY_PROMPTS,
    CONFIRMATIONS_SUCCESS,
    CONFIRMATIONS_FAILED,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def personality():
    with patch("assistant.personality.yaml_config", {"personality": {
        "sarcasm_level": 3,
        "opinion_intensity": 2,
        "self_irony_enabled": True,
    }}):
        with patch("assistant.personality.settings") as mock_settings:
            mock_settings.user_name = "Max"
            mock_settings.assistant_name = "Jarvis"
            engine = PersonalityEngine()
    return engine


# ============================================================
# Initialisierung
# ============================================================

class TestPersonalityInit:

    def test_default_values(self, personality):
        assert personality.sarcasm_level == 3
        assert personality.opinion_intensity == 2
        assert personality.self_irony_enabled is True
        assert personality.user_name == "Max"
        assert personality.assistant_name == "Jarvis"

    def test_mood_detector_setter(self, personality):
        md = MagicMock()
        personality.set_mood_detector(md)
        assert personality._mood_detector is md

    def test_redis_setter(self, personality):
        r = MagicMock()
        personality.set_redis(r)
        assert personality._redis is r


# ============================================================
# Mood Styles
# ============================================================

class TestMoodStyles:

    def test_all_moods_defined(self):
        for mood in ["good", "neutral", "stressed", "frustrated", "tired"]:
            assert mood in MOOD_STYLES

    def test_stressed_short_responses(self):
        style = MOOD_STYLES["stressed"]
        assert style["max_sentences_mod"] < 0

    def test_good_more_humor(self):
        style = MOOD_STYLES["good"]
        assert style["max_sentences_mod"] >= 0


# ============================================================
# Humor Templates
# ============================================================

class TestHumorTemplates:

    def test_all_levels_defined(self):
        for level in range(1, 6):
            assert level in HUMOR_TEMPLATES

    def test_level_1_no_humor(self):
        assert "Kein Humor" in HUMOR_TEMPLATES[1]

    def test_level_5_sarcastic_humor(self):
        assert "sarkastisch" in HUMOR_TEMPLATES[5]


# ============================================================
# Complexity Prompts
# ============================================================

class TestComplexityPrompts:

    def test_all_modes_defined(self):
        assert "kurz" in COMPLEXITY_PROMPTS
        assert "normal" in COMPLEXITY_PROMPTS
        assert "ausführlich" in COMPLEXITY_PROMPTS

    def test_kurz_is_short(self):
        assert "1 Satz" in COMPLEXITY_PROMPTS["kurz"]


# ============================================================
# Formality Prompts
# ============================================================

class TestFormalityPrompts:

    def test_all_levels_defined(self):
        assert "formal" in FORMALITY_PROMPTS
        assert "butler" in FORMALITY_PROMPTS
        assert "locker" in FORMALITY_PROMPTS
        assert "freund" in FORMALITY_PROMPTS


# ============================================================
# Easter Eggs
# ============================================================

class TestEasterEggs:

    def test_no_easter_egg(self, personality):
        personality._easter_eggs = [
            {"triggers": ["test phrase"], "responses": ["Antwort"], "enabled": True},
        ]
        result = personality.check_easter_egg("Guten Morgen")
        assert result is None

    def test_easter_egg_triggered(self, personality):
        personality._easter_eggs = [
            {"triggers": ["jarvis bist du da"], "responses": ["Immer, Sir."], "enabled": True},
        ]
        result = personality.check_easter_egg("Jarvis bist du da?")
        assert result is not None

    def test_disabled_easter_egg(self, personality):
        personality._easter_eggs = [
            {"triggers": ["test"], "responses": ["Antwort"], "enabled": False},
        ]
        result = personality.check_easter_egg("test")
        assert result is None


# ============================================================
# Opinion Rule Matching
# ============================================================

class TestOpinionRules:

    def test_match_rule_basic(self, personality):
        rule = {
            "check_action": "set_climate",
            "check_field": "temperature",
            "check_operator": ">",
            "check_value": 25,
            "min_intensity": 1,
        }
        assert personality._match_rule(rule, "set_climate", {"temperature": 28}, hour=12) is True

    def test_no_match_wrong_action(self, personality):
        rule = {
            "check_action": "set_climate",
            "check_field": "temperature",
            "check_operator": ">",
            "check_value": 25,
            "min_intensity": 1,
        }
        assert personality._match_rule(rule, "set_light", {"temperature": 28}, hour=12) is False

    def test_no_match_value_below(self, personality):
        rule = {
            "check_action": "set_climate",
            "check_field": "temperature",
            "check_operator": ">",
            "check_value": 25,
            "min_intensity": 1,
        }
        assert personality._match_rule(rule, "set_climate", {"temperature": 20}, hour=12) is False

    def test_match_hour_check(self, personality):
        rule = {
            "check_action": "set_light",
            "check_field": "",
            "check_operator": "",
            "check_value": None,
            "min_intensity": 1,
            "check_hour_min": 22,
            "check_hour_max": 5,
        }
        # Mitternachts-Wraparound: 23 Uhr sollte matchen
        assert personality._match_rule(rule, "set_light", {}, hour=23) is True
        # 12 Uhr sollte nicht matchen
        assert personality._match_rule(rule, "set_light", {}, hour=12) is False

    def test_intensity_too_high(self, personality):
        personality.opinion_intensity = 1
        rule = {
            "check_action": "set_climate",
            "min_intensity": 3,
        }
        assert personality._match_rule(rule, "set_climate", {}, hour=12) is False


# ============================================================
# Bestaetigungen
# ============================================================

class TestConfirmations:

    def test_success_confirmations_exist(self):
        assert len(CONFIRMATIONS_SUCCESS) > 5

    def test_failed_confirmations_exist(self):
        assert len(CONFIRMATIONS_FAILED) > 2

    def test_no_duplicate_confirmations(self):
        assert len(set(CONFIRMATIONS_SUCCESS)) == len(CONFIRMATIONS_SUCCESS)


# ============================================================
# Person Profiles
# ============================================================

class TestPersonProfiles:

    def test_empty_profile_for_unknown(self):
        with patch("assistant.personality.yaml_config", {"person_profiles": {"enabled": True, "profiles": {}}}):
            profile = PersonalityEngine._get_person_profile("unknown")
        assert profile == {}

    def test_profile_disabled(self):
        with patch("assistant.personality.yaml_config", {"person_profiles": {"enabled": False}}):
            profile = PersonalityEngine._get_person_profile("Max")
        assert profile == {}

    def test_empty_person_name(self):
        with patch("assistant.personality.yaml_config", {"person_profiles": {"enabled": True, "profiles": {"max": {"humor": 4}}}}):
            profile = PersonalityEngine._get_person_profile("")
        assert profile == {}


# ============================================================
# Humor Templates Laden
# ============================================================

class TestLoadHumorTemplates:

    def test_default_templates(self):
        result = PersonalityEngine._load_humor_templates({})
        assert result == dict(HUMOR_TEMPLATES)

    def test_custom_templates_string_keys(self):
        result = PersonalityEngine._load_humor_templates({
            "humor_templates": {"1": "No humor", "3": "Some humor"},
        })
        assert 1 in result
        assert 3 in result
        assert result[1] == "No humor"

    def test_invalid_templates_fallback(self):
        result = PersonalityEngine._load_humor_templates({
            "humor_templates": {"invalid": None},
        })
        assert result == dict(HUMOR_TEMPLATES)


# ============================================================
# Reload Config
# ============================================================

class TestReloadConfig:

    def test_reload_updates_sarcasm(self, personality):
        with patch("assistant.personality.yaml_config", {"personality": {
            "sarcasm_level": 5,
            "opinion_intensity": 3,
            "self_irony_enabled": False,
        }}):
            personality.reload_config()
        assert personality.sarcasm_level == 5
        assert personality.opinion_intensity == 3
        assert personality.self_irony_enabled is False
