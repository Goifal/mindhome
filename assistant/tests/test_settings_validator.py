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


# ============================================================
# Additional coverage: edge cases, all schema sections,
# multi-field validation, member role values
# ============================================================


class TestValidateSettingsFullConfig:
    """Tests with a complete, valid configuration."""

    def test_full_valid_config_no_warnings(self):
        config = {
            "assistant": {"name": "Jarvis"},
            "household": {
                "primary_user": "Max",
                "members": [
                    {"name": "Max", "role": "owner"},
                    {"name": "Anna", "role": "member"},
                ],
            },
            "ollama": {
                "num_ctx_fast": 2048,
                "num_ctx_smart": 4096,
                "num_ctx_deep": 8192,
            },
            "models": {"fast": "qwen3.5:4b", "smart": "qwen3.5:9b"},
            "personality": {"humor_level": 5, "sarcasm_level": 3},
            "security": {"confirm_dangerous_actions": True},
            "memory": {"max_conversations": 50},
            "routines": {"morning_briefing": {"enabled": True}},
            "energy": {"enabled": True},
        }
        warnings = validate_settings(config)
        assert len(warnings) == 0


class TestValidateSettingsSecuritySection:
    """Tests for the security section validation."""

    def test_valid_security(self):
        config = {"security": {"confirm_dangerous_actions": True}}
        warnings = validate_settings(config)
        assert len(warnings) == 0

    def test_wrong_type_security_field(self):
        config = {"security": {"confirm_dangerous_actions": "yes"}}
        warnings = validate_settings(config)
        assert any("confirm_dangerous_actions" in w for w in warnings)

    def test_security_not_dict(self):
        config = {"security": "enabled"}
        warnings = validate_settings(config)
        assert any("Erwartet dict" in w for w in warnings)


class TestValidateSettingsMemorySection:
    """Tests for the memory section validation."""

    def test_valid_memory(self):
        config = {"memory": {"max_conversations": 50}}
        warnings = validate_settings(config)
        assert len(warnings) == 0

    def test_memory_below_min(self):
        config = {"memory": {"max_conversations": 1}}
        warnings = validate_settings(config)
        assert any("Minimum" in w for w in warnings)

    def test_memory_above_max(self):
        config = {"memory": {"max_conversations": 5000}}
        warnings = validate_settings(config)
        assert any("Maximum" in w for w in warnings)

    def test_memory_wrong_type(self):
        config = {"memory": {"max_conversations": "fifty"}}
        warnings = validate_settings(config)
        assert any("max_conversations" in w for w in warnings)


class TestValidateSettingsRoutinesSection:
    """Tests for the routines section validation."""

    def test_valid_routines(self):
        config = {"routines": {"morning_briefing": {"enabled": True}}}
        warnings = validate_settings(config)
        assert len(warnings) == 0

    def test_morning_briefing_wrong_type(self):
        config = {"routines": {"morning_briefing": "yes"}}
        warnings = validate_settings(config)
        assert any("morning_briefing" in w for w in warnings)


class TestValidateSettingsEnergySection:
    """Tests for the energy section validation."""

    def test_valid_energy(self):
        config = {"energy": {"enabled": True}}
        warnings = validate_settings(config)
        assert len(warnings) == 0

    def test_energy_wrong_type(self):
        config = {"energy": {"enabled": "yes"}}
        warnings = validate_settings(config)
        assert any("enabled" in w for w in warnings)


class TestValidateSettingsPersonalitySection:
    """Tests for personality section — humor_level + sarcasm_level."""

    def test_humor_below_min(self):
        config = {"personality": {"humor_level": 0}}
        warnings = validate_settings(config)
        assert any("Minimum" in w and "humor_level" in w for w in warnings)

    def test_humor_above_max(self):
        config = {"personality": {"humor_level": 15}}
        warnings = validate_settings(config)
        assert any("Maximum" in w and "humor_level" in w for w in warnings)

    def test_humor_float_accepted(self):
        config = {"personality": {"humor_level": 5.5}}
        warnings = validate_settings(config)
        assert len(warnings) == 0

    def test_sarcasm_below_min(self):
        config = {"personality": {"sarcasm_level": 0}}
        warnings = validate_settings(config)
        assert any("Minimum" in w and "sarcasm_level" in w for w in warnings)

    def test_personality_wrong_type(self):
        config = {"personality": [1, 2, 3]}
        warnings = validate_settings(config)
        assert any("Erwartet dict" in w for w in warnings)


class TestValidateSettingsOllamaSection:
    """Tests for ollama section — all three num_ctx fields."""

    def test_all_ctx_valid(self):
        config = {"ollama": {"num_ctx_fast": 2048, "num_ctx_smart": 4096, "num_ctx_deep": 8192}}
        warnings = validate_settings(config)
        assert len(warnings) == 0

    def test_ctx_smart_below_min(self):
        config = {"ollama": {"num_ctx_smart": 100}}
        warnings = validate_settings(config)
        assert any("num_ctx_smart" in w and "Minimum" in w for w in warnings)

    def test_ctx_deep_above_max(self):
        config = {"ollama": {"num_ctx_deep": 200000}}
        warnings = validate_settings(config)
        assert any("num_ctx_deep" in w and "Maximum" in w for w in warnings)

    def test_ctx_deep_wrong_type(self):
        config = {"ollama": {"num_ctx_deep": "large"}}
        warnings = validate_settings(config)
        assert any("num_ctx_deep" in w for w in warnings)


class TestValidateSettingsModelsSection:
    """Tests for models section — required fields."""

    def test_missing_fast(self):
        config = {"models": {"smart": "qwen:9b"}}
        warnings = validate_settings(config)
        assert any("fast" in w and "Pflichtfeld" in w for w in warnings)

    def test_missing_smart(self):
        config = {"models": {"fast": "qwen:4b"}}
        warnings = validate_settings(config)
        assert any("smart" in w and "Pflichtfeld" in w for w in warnings)

    def test_both_missing(self):
        config = {"models": {}}
        warnings = validate_settings(config)
        assert any("fast" in w for w in warnings)
        assert any("smart" in w for w in warnings)

    def test_wrong_type_fast(self):
        config = {"models": {"fast": 123, "smart": "qwen:9b"}}
        warnings = validate_settings(config)
        assert any("fast" in w for w in warnings)


class TestValidateSettingsHouseholdSection:
    """Tests for household section — primary_user and members."""

    def test_missing_primary_user(self):
        config = {"household": {}}
        warnings = validate_settings(config)
        assert any("primary_user" in w and "Pflichtfeld" in w for w in warnings)

    def test_primary_user_wrong_type(self):
        config = {"household": {"primary_user": 123}}
        warnings = validate_settings(config)
        assert any("primary_user" in w for w in warnings)

    def test_members_not_list(self):
        """Members is not a list — should not crash, just skip member validation."""
        config = {"household": {"primary_user": "Max", "members": "invalid"}}
        warnings = validate_settings(config)
        # members has wrong type
        assert any("members" in w for w in warnings)


class TestValidateSettingsMemberRoles:
    """Tests for all valid and invalid member roles."""

    def test_all_valid_roles(self):
        for role in ["owner", "member", "child", "guest"]:
            config = {
                "household": {
                    "primary_user": "Max",
                    "members": [{"name": "Test", "role": role}],
                },
            }
            warnings = validate_settings(config)
            role_warnings = [w for w in warnings if "role" in w and "nicht in" in w]
            assert len(role_warnings) == 0, f"Role '{role}' should be valid"

    def test_invalid_role(self):
        config = {
            "household": {
                "primary_user": "Max",
                "members": [{"name": "Hacker", "role": "superadmin"}],
            },
        }
        warnings = validate_settings(config)
        assert any("superadmin" in w for w in warnings)

    def test_member_missing_role(self):
        config = {
            "household": {
                "primary_user": "Max",
                "members": [{"name": "Test"}],
            },
        }
        warnings = validate_settings(config)
        assert any("role" in w and "Pflichtfeld" in w for w in warnings)


class TestValidateSettingsMultipleMembers:
    """Tests with multiple members, some valid, some not."""

    def test_mixed_valid_invalid_members(self):
        config = {
            "household": {
                "primary_user": "Max",
                "members": [
                    {"name": "Max", "role": "owner"},
                    {"name": "Bad", "role": "hacker"},
                    "not_a_dict",
                ],
            },
        }
        warnings = validate_settings(config)
        # Should have warnings for invalid role and non-dict member
        assert any("hacker" in w for w in warnings)
        assert any("Kein Dict" in w for w in warnings)
        # But no warnings for the valid member


class TestValidateSettingsOptionalSections:
    """Tests that optional/unknown sections don't cause warnings."""

    def test_unknown_section_ignored(self):
        config = {
            "custom_section": {"anything": "goes"},
            "assistant": {"name": "Jarvis"},
        }
        warnings = validate_settings(config)
        assert len(warnings) == 0

    def test_missing_optional_sections_no_warnings(self):
        """Config with only unknown keys should produce no warnings."""
        config = {"unknown_key": "value"}
        warnings = validate_settings(config)
        assert len(warnings) == 0

    def test_optional_field_none_no_warning(self):
        """Optional field that is None should not produce a warning."""
        config = {"household": {"primary_user": "Max", "members": None}}
        warnings = validate_settings(config)
        # members is optional, None should not crash
        assert not any("Kein Dict" in w for w in warnings)


class TestValidateSettingsEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_dict_warns(self):
        """Empty dict is treated as 'empty config'."""
        warnings = validate_settings({})
        assert len(warnings) == 1
        assert "leer" in warnings[0]

    def test_integer_config(self):
        """Non-dict config produces warning."""
        warnings = validate_settings(42)
        assert len(warnings) > 0

    def test_list_config(self):
        """List config produces warning."""
        warnings = validate_settings([1, 2, 3])
        assert len(warnings) > 0

    def test_boundary_values_accepted(self):
        """Exact min/max boundary values are accepted."""
        config = {
            "ollama": {"num_ctx_fast": 512, "num_ctx_deep": 131072},
            "personality": {"humor_level": 1, "sarcasm_level": 10},
            "memory": {"max_conversations": 5},
        }
        warnings = validate_settings(config)
        assert len(warnings) == 0

    def test_multiple_warnings_accumulated(self):
        """Multiple problems produce multiple warnings."""
        config = {
            "assistant": {},  # missing name
            "models": {},  # missing fast and smart
            "personality": {"sarcasm_level": 99},  # above max
        }
        warnings = validate_settings(config)
        assert len(warnings) >= 3
