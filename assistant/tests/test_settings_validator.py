"""
Tests fuer SettingsValidator — settings.yaml Validierung.

Testet:
- Leere/ungueltige Config
- Pflichtfeld-Pruefung
- Typ-Pruefung
- Wertebereich-Pruefung
- Household-Members Validierung
"""

import pytest

from assistant.settings_validator import validate_settings


class TestValidateSettingsBasic:

    def test_empty_config_warns(self):
        warnings = validate_settings({})
        # Leeres dict wird als "leer" behandelt — eine Warnung
        assert len(warnings) == 1

    def test_none_config_warns(self):
        warnings = validate_settings(None)
        assert any("leer" in w or "kein Dict" in w for w in warnings)

    def test_non_dict_config_warns(self):
        warnings = validate_settings("not a dict")
        assert len(warnings) > 0

    def test_valid_minimal_config(self):
        config = {
            "assistant": {"name": "Jarvis"},
            "household": {"primary_user": "Max"},
            "models": {"fast": "qwen3.5:4b", "smart": "qwen3.5:9b"},
        }
        warnings = validate_settings(config)
        assert len(warnings) == 0


class TestValidateSettingsTypes:

    def test_wrong_section_type(self):
        config = {"assistant": "not a dict"}
        warnings = validate_settings(config)
        assert any("Erwartet dict" in w for w in warnings)

    def test_wrong_field_type(self):
        config = {
            "ollama": {"num_ctx_fast": "not_an_int"},
        }
        warnings = validate_settings(config)
        assert any("num_ctx_fast" in w for w in warnings)

    def test_missing_required_field(self):
        config = {"assistant": {}}
        warnings = validate_settings(config)
        assert any("name" in w and "Pflichtfeld" in w for w in warnings)


class TestValidateSettingsRanges:

    def test_value_below_min(self):
        config = {"ollama": {"num_ctx_fast": 100}}
        warnings = validate_settings(config)
        assert any("Minimum" in w for w in warnings)

    def test_value_above_max(self):
        config = {"ollama": {"num_ctx_fast": 999999}}
        warnings = validate_settings(config)
        assert any("Maximum" in w for w in warnings)

    def test_value_in_range_ok(self):
        config = {"ollama": {"num_ctx_fast": 4096}}
        warnings = validate_settings(config)
        assert len(warnings) == 0

    def test_personality_sarcasm_out_of_range(self):
        config = {"personality": {"sarcasm_level": 15}}
        warnings = validate_settings(config)
        assert any("Maximum" in w for w in warnings)


class TestValidateSettingsMembers:

    def test_valid_member(self):
        config = {
            "household": {
                "primary_user": "Max",
                "members": [{"name": "Max", "role": "owner"}],
            },
        }
        warnings = validate_settings(config)
        assert len(warnings) == 0

    def test_member_missing_name(self):
        config = {
            "household": {
                "primary_user": "Max",
                "members": [{"role": "owner"}],
            },
        }
        warnings = validate_settings(config)
        assert any("name" in w and "Pflichtfeld" in w for w in warnings)

    def test_member_invalid_role(self):
        config = {
            "household": {
                "primary_user": "Max",
                "members": [{"name": "Hacker", "role": "admin"}],
            },
        }
        warnings = validate_settings(config)
        assert any("admin" in w for w in warnings)

    def test_member_not_dict(self):
        config = {
            "household": {
                "primary_user": "Max",
                "members": ["Max"],
            },
        }
        warnings = validate_settings(config)
        assert any("Kein Dict" in w for w in warnings)
