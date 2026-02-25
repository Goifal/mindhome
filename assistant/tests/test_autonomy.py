"""
Tests fuer AutonomyManager — Autonomie-Level + Person-basierte Trust-Levels.
"""

from unittest.mock import patch, MagicMock

import pytest

from assistant.autonomy import (
    ACTION_PERMISSIONS,
    TRUST_LEVEL_NAMES,
    AutonomyManager,
)


# =====================================================================
# Fixtures
# =====================================================================

_DEFAULT_TRUST_CFG = {
    "default": 0,
    "persons": {"lisa": 1, "max": 2},
    "guest_allowed_actions": ["set_light", "set_climate", "play_media", "get_entity_state"],
    "security_actions": ["lock_door", "arm_security_system", "set_presence_mode"],
    "room_restrictions": {"gast": ["kueche", "wohnzimmer"]},
}


@pytest.fixture
def am():
    """AutonomyManager mit Standard-Config."""
    mock_settings = MagicMock()
    mock_settings.autonomy_level = 2
    mock_settings.user_name = "Sir"

    yaml_mock = {"trust_levels": _DEFAULT_TRUST_CFG}

    with patch("assistant.autonomy.settings", mock_settings), \
         patch("assistant.autonomy.yaml_config", yaml_mock):
        mgr = AutonomyManager()

    # Patches bleiben aktiv fuer Methoden die settings/yaml_config zur Laufzeit lesen
    p1 = patch("assistant.autonomy.settings", mock_settings)
    p2 = patch("assistant.autonomy.yaml_config", yaml_mock)
    p1.start()
    p2.start()
    yield mgr
    p2.stop()
    p1.stop()


def _make_autonomy(level=2, trust_cfg=None):
    """Erstellt AutonomyManager mit gemockter Config (fuer einfache Tests)."""
    if trust_cfg is None:
        trust_cfg = _DEFAULT_TRUST_CFG

    mock_settings = MagicMock()
    mock_settings.autonomy_level = level
    mock_settings.user_name = "Sir"

    with patch("assistant.autonomy.settings", mock_settings), \
         patch("assistant.autonomy.yaml_config", {"trust_levels": trust_cfg}):
        return AutonomyManager()


# =====================================================================
# Autonomie-Level
# =====================================================================


class TestCanAct:
    """Tests fuer Autonomie-Level Berechtigung."""

    def test_level_2_can_proactive(self):
        am = _make_autonomy(level=2)
        assert am.can_act("proactive_info") is True

    def test_level_1_cannot_proactive(self):
        am = _make_autonomy(level=1)
        assert am.can_act("proactive_info") is False

    def test_level_1_can_respond(self):
        am = _make_autonomy(level=1)
        assert am.can_act("respond_to_command") is True

    def test_level_3_can_adjust_temp(self):
        am = _make_autonomy(level=3)
        assert am.can_act("adjust_temperature_small") is True

    def test_level_2_cannot_adjust_temp(self):
        am = _make_autonomy(level=2)
        assert am.can_act("adjust_temperature_small") is False

    def test_security_alert_always_allowed(self):
        """Sicherheitswarnungen muessen auf Level 1 moeglich sein."""
        am = _make_autonomy(level=1)
        assert am.can_act("security_alert") is True

    def test_unknown_action_requires_level_5(self):
        am = _make_autonomy(level=4)
        assert am.can_act("unknown_action_xyz") is False
        am5 = _make_autonomy(level=5)
        assert am5.can_act("unknown_action_xyz") is True

    def test_level_5_can_create_automation(self):
        am = _make_autonomy(level=5)
        assert am.can_act("create_automation") is True


class TestSetLevel:
    """Tests fuer Level-Aenderung."""

    def test_set_valid_level(self):
        am = _make_autonomy(level=2)
        assert am.set_level(3) is True
        assert am.level == 3

    def test_set_invalid_level_too_low(self):
        am = _make_autonomy(level=2)
        assert am.set_level(0) is False
        assert am.level == 2

    def test_set_invalid_level_too_high(self):
        am = _make_autonomy(level=2)
        assert am.set_level(6) is False
        assert am.level == 2

    def test_set_boundary_levels(self):
        am = _make_autonomy(level=2)
        assert am.set_level(1) is True
        assert am.set_level(5) is True


class TestGetLevelInfo:
    """Tests fuer Level-Info."""

    def test_info_contains_name(self):
        am = _make_autonomy(level=2)
        info = am.get_level_info()
        assert info["level"] == 2
        assert info["name"] == "Butler"

    def test_info_contains_allowed_actions(self):
        am = _make_autonomy(level=3)
        info = am.get_level_info()
        assert "respond_to_command" in info["allowed_actions"]
        assert "proactive_info" in info["allowed_actions"]
        assert "adjust_temperature_small" in info["allowed_actions"]
        assert "create_automation" not in info["allowed_actions"]


# =====================================================================
# Trust-Levels
# =====================================================================


class TestGetTrustLevel:
    """Tests fuer Person-basierte Trust-Levels."""

    def test_owner_is_always_2(self, am):
        """Hauptbenutzer (settings.user_name) bekommt immer Trust 2."""
        assert am.get_trust_level("Sir") == 2

    def test_owner_case_insensitive(self, am):
        assert am.get_trust_level("sir") == 2
        assert am.get_trust_level("SIR") == 2

    def test_configured_person(self, am):
        assert am.get_trust_level("Lisa") == 1

    def test_configured_person_case_insensitive(self, am):
        assert am.get_trust_level("lisa") == 1
        assert am.get_trust_level("LISA") == 1

    def test_unknown_person_gets_default(self, am):
        assert am.get_trust_level("Fremder") == 0

    def test_empty_person_gets_default(self, am):
        assert am.get_trust_level("") == 0


class TestCanPersonAct:
    """Tests fuer can_person_act() — Trust-basierte Aktionspruefung."""

    def test_owner_can_do_everything(self, am):
        result = am.can_person_act("Sir", "lock_door")
        assert result["allowed"] is True
        assert result["trust_level"] == 2

    def test_guest_blocked_on_security(self, am):
        result = am.can_person_act("Fremder", "lock_door")
        assert result["allowed"] is False
        assert "hoehere Autorisierung" in result["reason"]

    def test_guest_allowed_light(self, am):
        result = am.can_person_act("Fremder", "set_light")
        assert result["allowed"] is True
        assert result["trust_level"] == 0
        assert result["trust_name"] == "Gast"

    def test_guest_blocked_on_unknown_function(self, am):
        result = am.can_person_act("Fremder", "edit_config")
        assert result["allowed"] is False

    def test_mitbewohner_can_do_most(self, am):
        result = am.can_person_act("Lisa", "set_light")
        assert result["allowed"] is True
        result = am.can_person_act("Lisa", "play_media")
        assert result["allowed"] is True

    def test_mitbewohner_blocked_on_security(self, am):
        result = am.can_person_act("Lisa", "arm_security_system")
        assert result["allowed"] is False

    def test_room_scoping_for_guest(self, am):
        """Gast darf nur in zugewiesenen Raeumen handeln."""
        # Gast "gast" hat room_restrictions: ["kueche", "wohnzimmer"]
        with patch("assistant.autonomy.yaml_config", {"trust_levels": {
            "room_restrictions": {"gast": ["kueche", "wohnzimmer"]}
        }}):
            result = am.can_person_act("Gast", "set_light", room="kueche")
            assert result["allowed"] is True
            result = am.can_person_act("Gast", "set_light", room="schlafzimmer")
            assert result["allowed"] is False

    def test_room_scoping_without_restrictions(self, am):
        """Gast ohne room_restrictions darf ueberall (Guest-Aktionen)."""
        result = am.can_person_act("Fremder", "set_light", room="schlafzimmer")
        assert result["allowed"] is True


class TestTrustInfo:
    """Tests fuer get_trust_info()."""

    def test_info_contains_all_fields(self):
        am = _make_autonomy()
        info = am.get_trust_info()
        assert "default_trust" in info
        assert "persons" in info
        assert "guest_actions" in info
        assert "security_actions" in info

    def test_info_persons_correct(self):
        am = _make_autonomy()
        info = am.get_trust_info()
        assert "lisa" in info["persons"]
        assert info["persons"]["lisa"]["level"] == 1


# =====================================================================
# Konstanten
# =====================================================================


class TestConstants:
    """Tests fuer Action Permissions und Trust Level Names."""

    def test_all_permissions_have_levels(self):
        for action, level in ACTION_PERMISSIONS.items():
            assert 1 <= level <= 5, f"{action}: Level {level} ausserhalb [1, 5]"

    def test_trust_level_names_complete(self):
        for level in (0, 1, 2):
            assert level in TRUST_LEVEL_NAMES

    def test_security_alert_is_level_1(self):
        """Sicherheitswarnungen muessen auf niedrigstem Level ausfuehrbar sein."""
        assert ACTION_PERMISSIONS["security_alert"] == 1
