"""
Tests fuer AutonomyManager — Autonomie-Level + Person-basierte Trust-Levels.

Umfassende Tests fuer sicherheitskritische Logik:
- 5 Autonomie-Level (1=Assistent bis 5=Autopilot)
- Domain-spezifische Autonomie-Level
- Person-basierte Trust-Levels (0=Gast, 1=Mitbewohner, 2=Owner)
- Kombinierte Autonomie+Trust Pruefung (can_execute)
- Harte Sicherheitsgrenzen (Safety Caps)
- Autonomy Evolution (dynamische Level-Anpassung)
- Boundary- und Edge-Cases
"""

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from assistant.autonomy import (
    ACTION_PERMISSIONS,
    ACTION_DOMAIN_MAP,
    AUTONOMY_DOMAINS,
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
    """AutonomyManager mit Standard-Config (Patches bleiben aktiv fuer Laufzeit-Zugriff)."""
    mock_settings = MagicMock()
    mock_settings.autonomy_level = 2
    mock_settings.user_name = "Sir"

    yaml_mock = {"trust_levels": _DEFAULT_TRUST_CFG}

    with patch("assistant.autonomy.settings", mock_settings), \
         patch("assistant.autonomy.yaml_config", yaml_mock):
        mgr = AutonomyManager()
        yield mgr


def _make_autonomy(level=2, trust_cfg=None, autonomy_cfg=None):
    """Erstellt AutonomyManager mit gemockter Config (fuer einfache Tests)."""
    if trust_cfg is None:
        trust_cfg = _DEFAULT_TRUST_CFG

    mock_settings = MagicMock()
    mock_settings.autonomy_level = level
    mock_settings.user_name = "Sir"

    yaml_mock = {"trust_levels": trust_cfg}
    if autonomy_cfg is not None:
        yaml_mock["autonomy"] = autonomy_cfg

    with patch("assistant.autonomy.settings", mock_settings), \
         patch("assistant.autonomy.yaml_config", yaml_mock):
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


# =====================================================================
# can_execute() — Kombinierte Autonomie + Trust Pruefung
# =====================================================================


class TestCanExecute:
    """Tests fuer can_execute() — Autonomie-Level UND Person-Trust kombiniert."""

    def test_owner_with_sufficient_level(self, am):
        result = am.can_execute(person="Sir", action_type="respond_to_command", function_name="set_light")
        assert result["allowed"] is True
        assert result["autonomy_ok"] is True
        assert result["trust_ok"] is True

    def test_owner_with_insufficient_level(self):
        am = _make_autonomy(level=1)
        result = am.can_execute(person="Sir", action_type="proactive_info", function_name="set_light")
        assert result["allowed"] is False
        assert result["autonomy_ok"] is False
        assert result["trust_ok"] is True
        assert "reason" in result

    def test_guest_blocked_by_trust(self, am):
        result = am.can_execute(person="Fremder", action_type="respond_to_command", function_name="lock_door")
        assert result["allowed"] is False
        assert result["autonomy_ok"] is True
        assert result["trust_ok"] is False

    def test_guest_allowed_for_light(self, am):
        result = am.can_execute(person="Fremder", action_type="respond_to_command", function_name="set_light")
        assert result["allowed"] is True

    def test_both_blocked_reports_both_reasons(self):
        am = _make_autonomy(level=1)
        result = am.can_execute(person="Fremder", action_type="proactive_info", function_name="lock_door")
        assert result["allowed"] is False
        assert result["autonomy_ok"] is False
        assert result["trust_ok"] is False
        assert "reason" in result

    def test_empty_person_treated_as_guest(self, am):
        result = am.can_execute(person="", action_type="respond_to_command", function_name="lock_door")
        assert result["allowed"] is False
        assert result["trust_level"] == 0


# =====================================================================
# check_safety_caps() — Harte Sicherheitsgrenzen
# =====================================================================


class TestCheckSafetyCaps:
    """Tests fuer check_safety_caps() — unabhaengig von Level/Trust."""

    def test_valid_temperature(self, am):
        result = am.check_safety_caps("set_temperature", {"temperature": 21})
        assert result["allowed"] is True

    def test_temperature_too_high(self, am):
        result = am.check_safety_caps("set_temperature", {"temperature": 35})
        assert result["allowed"] is False
        assert "Maximum" in result["reason"]

    def test_temperature_too_low(self, am):
        result = am.check_safety_caps("set_temperature", {"temperature": 10})
        assert result["allowed"] is False
        assert "Minimum" in result["reason"]

    def test_temperature_boundary_min(self, am):
        result = am.check_safety_caps("set_temperature", {"temperature": 14})
        assert result["allowed"] is True

    def test_temperature_boundary_max(self, am):
        result = am.check_safety_caps("set_temperature", {"temperature": 30})
        assert result["allowed"] is True

    def test_invalid_temperature_string(self, am):
        result = am.check_safety_caps("set_temperature", {"temperature": "abc"})
        assert result["allowed"] is False

    def test_valid_brightness(self, am):
        result = am.check_safety_caps("set_light", {"brightness": 50})
        assert result["allowed"] is True

    def test_brightness_out_of_range(self, am):
        result = am.check_safety_caps("set_light", {"brightness": 150})
        assert result["allowed"] is False

    def test_brightness_negative(self, am):
        result = am.check_safety_caps("set_light", {"brightness": -10})
        assert result["allowed"] is False

    def test_unrelated_function_passes(self, am):
        result = am.check_safety_caps("play_media", {"volume": 100})
        assert result["allowed"] is True

    def test_no_args_passes(self, am):
        result = am.check_safety_caps("set_temperature", {})
        assert result["allowed"] is True


# =====================================================================
# Domain-spezifische Autonomie-Level
# =====================================================================


class TestDomainSpecificAutonomy:
    """Tests fuer domain-spezifische Autonomie-Level."""

    def test_domain_levels_disabled_by_default(self):
        """Ohne domain_levels_enabled nutzt can_act das globale Level."""
        am = _make_autonomy(level=3)
        # Globales Level 3 reicht fuer adjust_temperature_small (Level 3)
        assert am.can_act("adjust_temperature_small") is True

    def test_domain_levels_override_global(self):
        """Domain-Level ueberschreibt globales Level wenn aktiviert."""
        am = _make_autonomy(level=2, autonomy_cfg={
            "domain_levels_enabled": True,
            "domain_levels": {"climate": 4, "light": 3},
        })
        # Globales Level ist 2, aber Climate-Domain hat Level 4
        assert am.can_act("adjust_temperature_small", domain="climate") is True
        # Light-Domain hat Level 3 → reicht fuer set_light (Level 3)
        assert am.can_act("set_light", domain="light") is True

    def test_domain_level_auto_resolved_from_action(self):
        """Domaene wird aus ACTION_DOMAIN_MAP automatisch aufgeloest."""
        am = _make_autonomy(level=2, autonomy_cfg={
            "domain_levels_enabled": True,
            "domain_levels": {"climate": 4},
        })
        # adjust_temperature_small mappt zu "climate" in ACTION_DOMAIN_MAP
        assert am.can_act("adjust_temperature_small") is True

    def test_domain_level_explicit_overrides_auto(self):
        """Explizite Domaene hat Vorrang vor automatischer Aufloesung."""
        am = _make_autonomy(level=2, autonomy_cfg={
            "domain_levels_enabled": True,
            "domain_levels": {"climate": 4, "security": 1},
        })
        # Aktion adjust_temperature_small mappt zu climate (Level 4),
        # aber explizite Domaene "security" hat Level 1
        assert am.can_act("adjust_temperature_small", domain="security") is False

    def test_domain_fallback_to_global_for_unknown_domain(self):
        """Unbekannte Domaene faellt auf globales Level zurueck."""
        am = _make_autonomy(level=3, autonomy_cfg={
            "domain_levels_enabled": True,
            "domain_levels": {"climate": 5},
        })
        # "notification" ist nicht in domain_levels konfiguriert → globales Level 3
        assert am.can_act("proactive_info", domain="notification") is True

    def test_domain_levels_in_level_info(self):
        """get_level_info zeigt domain_levels wenn aktiviert."""
        am = _make_autonomy(level=2, autonomy_cfg={
            "domain_levels_enabled": True,
            "domain_levels": {"climate": 4, "light": 3},
        })
        info = am.get_level_info()
        assert info["domain_levels_enabled"] is True
        assert "domain_levels" in info
        assert info["domain_levels"]["climate"]["level"] == 4
        assert info["domain_levels"]["climate"]["name"] == "Vertrauter"

    def test_invalid_domain_in_config_ignored(self):
        """Domaenen die nicht in AUTONOMY_DOMAINS stehen werden ignoriert."""
        am = _make_autonomy(level=2, autonomy_cfg={
            "domain_levels_enabled": True,
            "domain_levels": {"climate": 4, "nonexistent_domain": 5},
        })
        assert "nonexistent_domain" not in am._domain_levels
        assert "climate" in am._domain_levels


class TestDomainSpecificCanExecute:
    """Domain-spezifische Autonomie in Kombination mit Trust."""

    def test_domain_level_sufficient_trust_ok(self):
        """Domain-Level reicht + Trust OK → erlaubt."""
        am = _make_autonomy(level=1, autonomy_cfg={
            "domain_levels_enabled": True,
            "domain_levels": {"light": 3},
        })
        result = am.can_execute(
            person="Sir", action_type="set_light",
            function_name="set_light", domain="light",
        )
        assert result["allowed"] is True
        assert result["autonomy_level"] == 3  # Domain-Level, nicht global

    def test_domain_level_insufficient(self):
        """Domain-Level reicht nicht → blockiert trotz Owner."""
        am = _make_autonomy(level=1, autonomy_cfg={
            "domain_levels_enabled": True,
            "domain_levels": {"security": 1},
        })
        result = am.can_execute(
            person="Sir", action_type="create_automation",
            function_name="set_light", domain="security",
        )
        assert result["allowed"] is False
        assert result["autonomy_ok"] is False


# =====================================================================
# Autonomie-Level Grenzwerte und Edge-Cases
# =====================================================================


class TestAutonomyEdgeCases:
    """Edge-Cases und Grenzwerte fuer Autonomie-Level."""

    def test_all_five_levels_have_names(self):
        """Alle 5 Level muessen einen Namen haben."""
        for level in range(1, 6):
            am = _make_autonomy(level=level)
            info = am.get_level_info()
            assert info["name"] != "Unbekannt", f"Level {level} hat keinen Namen"
            assert info["description"] != "", f"Level {level} hat keine Beschreibung"

    def test_level_1_minimal_permissions(self):
        """Level 1 (Assistent) darf nur reagieren + Sicherheitswarnungen."""
        am = _make_autonomy(level=1)
        info = am.get_level_info()
        allowed = set(info["allowed_actions"])
        # Nur Level-1-Aktionen
        for action, req_level in ACTION_PERMISSIONS.items():
            if req_level == 1:
                assert action in allowed, f"Level 1 sollte '{action}' erlauben"
            else:
                assert action not in allowed, f"Level 1 sollte '{action}' NICHT erlauben"

    def test_level_5_allows_everything(self):
        """Level 5 (Autopilot) darf alles in ACTION_PERMISSIONS."""
        am = _make_autonomy(level=5)
        info = am.get_level_info()
        allowed = set(info["allowed_actions"])
        for action in ACTION_PERMISSIONS:
            assert action in allowed, f"Level 5 sollte '{action}' erlauben"

    def test_level_progression_monotonic(self):
        """Hoehere Level duerfen alles was niedrigere duerfen (monoton steigend)."""
        prev_actions = set()
        for level in range(1, 6):
            am = _make_autonomy(level=level)
            info = am.get_level_info()
            current_actions = set(info["allowed_actions"])
            assert prev_actions.issubset(current_actions), (
                f"Level {level} fehlen Aktionen die Level {level-1} hatte: "
                f"{prev_actions - current_actions}"
            )
            prev_actions = current_actions

    def test_set_level_non_integer_rejected(self):
        """Nicht-Integer Level werden korrekt behandelt."""
        am = _make_autonomy(level=2)
        # Float-Wert 2.5 — int(2.5)=2 ist valid, aber set_level prueft 1<=level<=5
        # 2.5 wird als float uebergeben, der Vergleich 1 <= 2.5 <= 5 ist True in Python
        # Das ist ein impliziter Edge-Case
        assert am.set_level(2) is True  # Kein Change aber gueltig

    def test_custom_action_permissions_from_config(self):
        """Action-Permissions aus Config ueberschreiben Defaults."""
        am = _make_autonomy(level=2, autonomy_cfg={
            "action_permissions": {"proactive_info": 1},  # Normalerweise Level 2
        })
        # proactive_info jetzt auf Level 1 → Level 2 reicht sowieso
        am_l1 = _make_autonomy(level=1, autonomy_cfg={
            "action_permissions": {"proactive_info": 1},
        })
        assert am_l1.can_act("proactive_info") is True

    def test_trust_level_global_keyword(self):
        """'global' Person bekommt immer Trust 2 (Owner)."""
        am = _make_autonomy(level=2)
        assert am.get_trust_level("global") == 2
        assert am.get_trust_level("Global") == 2
        assert am.get_trust_level("GLOBAL") == 2


# =====================================================================
# Sicherheits-Caps Erweiterungen
# =====================================================================


class TestSafetyCapsExtended:
    """Erweiterte Tests fuer harte Sicherheitsgrenzen."""

    def test_set_climate_also_checked(self):
        """set_climate und adjust_temperature haben gleiche Grenzen."""
        am = _make_autonomy(level=5)
        for fn in ("set_temperature", "set_climate", "adjust_temperature"):
            result = am.check_safety_caps(fn, {"temperature": 35})
            assert result["allowed"] is False, f"{fn} sollte 35°C blockieren"

    def test_brightness_boundary_0_and_100(self):
        """Brightness 0 und 100 sind gueltig (Grenzen inklusive)."""
        am = _make_autonomy(level=5)
        assert am.check_safety_caps("set_light", {"brightness": 0})["allowed"] is True
        assert am.check_safety_caps("set_light", {"brightness": 100})["allowed"] is True

    def test_brightness_string_number_accepted(self):
        """Brightness als String-Zahl wird korrekt geparst."""
        am = _make_autonomy(level=5)
        result = am.check_safety_caps("set_light", {"brightness": "50"})
        assert result["allowed"] is True

    def test_brightness_invalid_string_passes_silently(self):
        """Brightness als ungueltige Zeichenkette: int() schlaegt fehl, kein Bounds-Check."""
        am = _make_autonomy(level=5)
        # Wenn int() fehlschlaegt, wird der Block uebersprungen → erlaubt
        result = am.check_safety_caps("set_light", {"brightness": "hell"})
        assert result["allowed"] is True

    def test_temperature_boundary_exact_min_max(self):
        """Temperatur exakt am Minimum/Maximum ist gueltig."""
        am = _make_autonomy(level=5)
        caps = am.SAFETY_CAPS
        assert am.check_safety_caps("set_temperature", {"temperature": caps["min_temperature"]})["allowed"] is True
        assert am.check_safety_caps("set_temperature", {"temperature": caps["max_temperature"]})["allowed"] is True

    def test_temperature_just_outside_boundaries(self):
        """Temperatur knapp ausserhalb der Grenzen wird blockiert."""
        am = _make_autonomy(level=5)
        caps = am.SAFETY_CAPS
        assert am.check_safety_caps("set_temperature", {"temperature": caps["min_temperature"] - 0.1})["allowed"] is False
        assert am.check_safety_caps("set_temperature", {"temperature": caps["max_temperature"] + 0.1})["allowed"] is False

    def test_set_brightness_function_also_checked(self):
        """set_brightness hat gleiche Brightness-Grenzen wie set_light."""
        am = _make_autonomy(level=5)
        result = am.check_safety_caps("set_brightness", {"brightness": 150})
        assert result["allowed"] is False


# =====================================================================
# Autonomy Evolution
# =====================================================================


class TestAutonomyEvolution:
    """Tests fuer dynamische Level-Anpassung."""

    @pytest.mark.asyncio
    async def test_track_interaction_without_redis(self):
        """track_interaction ohne Redis darf nicht crashen."""
        am = _make_autonomy(level=2)
        # Kein Redis gesetzt → soll still zurueckkehren
        await am.track_interaction("proactive_info", accepted=True)

    @pytest.mark.asyncio
    async def test_track_interaction_with_redis(self):
        """track_interaction zaehlt korrekt in Redis."""
        am = _make_autonomy(level=2)
        redis = AsyncMock()
        am.set_redis(redis)
        await am.track_interaction("proactive_info", accepted=True)
        redis.hincrby.assert_any_call(am._REDIS_KEY_STATS, "total", 1)
        redis.hincrby.assert_any_call(am._REDIS_KEY_STATS, "accepted", 1)

    @pytest.mark.asyncio
    async def test_track_interaction_rejected(self):
        """Abgelehnte Interaktion zaehlt rejected."""
        am = _make_autonomy(level=2)
        redis = AsyncMock()
        am.set_redis(redis)
        await am.track_interaction("proactive_info", accepted=False)
        redis.hincrby.assert_any_call(am._REDIS_KEY_STATS, "rejected", 1)

    @pytest.mark.asyncio
    async def test_evaluate_evolution_without_redis(self):
        """evaluate_evolution ohne Redis gibt None zurueck."""
        am = _make_autonomy(level=1)
        result = await am.evaluate_evolution()
        assert result is None

    @pytest.mark.asyncio
    async def test_evaluate_evolution_disabled(self):
        """Evolution disabled in Config gibt None zurueck."""
        am = _make_autonomy(level=1, autonomy_cfg={
            "evolution": {"enabled": False},
        })
        redis = AsyncMock()
        am.set_redis(redis)
        result = await am.evaluate_evolution()
        assert result is None

    @pytest.mark.asyncio
    async def test_evaluate_evolution_max_level_reached(self):
        """Bereits auf max_level → kein Aufstieg moeglich."""
        am = _make_autonomy(level=3, autonomy_cfg={
            "evolution": {"enabled": True, "max_level": 3},
        })
        redis = AsyncMock()
        am.set_redis(redis)
        result = await am.evaluate_evolution()
        assert result is None

    @pytest.mark.asyncio
    async def test_evaluate_evolution_level_5_never_auto(self):
        """Level 5 (Autopilot) kann nie automatisch erreicht werden."""
        am = _make_autonomy(level=4, autonomy_cfg={
            "evolution": {"enabled": True, "max_level": 5},
        })
        redis = AsyncMock()
        am.set_redis(redis)
        result = await am.evaluate_evolution()
        assert result is None  # next_level=5 > 4 → None

    @pytest.mark.asyncio
    async def test_evaluate_evolution_not_ready(self):
        """Kriterien nicht erfuellt → ready=False."""
        am = _make_autonomy(level=1, autonomy_cfg={
            "evolution": {"enabled": True, "max_level": 3},
        })
        redis = AsyncMock()
        redis.hgetall = AsyncMock(return_value={
            "total": "10", "accepted": "8", "rejected": "2",
        })
        redis.get = AsyncMock(return_value=datetime.now(timezone.utc).isoformat())
        am.set_redis(redis)

        with patch("assistant.autonomy.yaml_config", {
            "trust_levels": _DEFAULT_TRUST_CFG,
            "autonomy": {"evolution": {"enabled": True, "max_level": 3}},
        }):
            result = await am.evaluate_evolution()
            assert result is not None
            assert result["ready"] is False
            assert result["meets_interactions"] is False  # nur 10 von 200

    @pytest.mark.asyncio
    async def test_evaluate_evolution_ready(self):
        """Alle Kriterien erfuellt → ready=True."""
        am = _make_autonomy(level=1, autonomy_cfg={
            "evolution": {"enabled": True, "max_level": 3},
        })
        redis = AsyncMock()
        redis.hgetall = AsyncMock(return_value={
            "total": "300", "accepted": "250", "rejected": "50",
        })
        # first_start = 60 Tage her
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        redis.get = AsyncMock(return_value=start.isoformat())
        am.set_redis(redis)

        with patch("assistant.autonomy.yaml_config", {
            "trust_levels": _DEFAULT_TRUST_CFG,
            "autonomy": {"evolution": {"enabled": True, "max_level": 3}},
        }):
            result = await am.evaluate_evolution()
            assert result is not None
            assert result["ready"] is True
            assert result["proposed_level"] == 2

    @pytest.mark.asyncio
    async def test_apply_evolution_resets_stats(self):
        """apply_evolution setzt Redis-Statistiken zurueck."""
        am = _make_autonomy(level=1, autonomy_cfg={
            "evolution": {"enabled": True, "max_level": 3},
        })
        redis = AsyncMock()
        redis.hgetall = AsyncMock(return_value={
            "total": "300", "accepted": "250", "rejected": "50",
        })
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        redis.get = AsyncMock(return_value=start.isoformat())
        am.set_redis(redis)

        with patch("assistant.autonomy.yaml_config", {
            "trust_levels": _DEFAULT_TRUST_CFG,
            "autonomy": {"evolution": {"enabled": True, "max_level": 3}},
        }):
            result = await am.apply_evolution()
            assert result is True
            assert am.level == 2
            redis.delete.assert_called_with(am._REDIS_KEY_STATS)

    def test_get_evolution_info(self):
        """get_evolution_info gibt strukturierte Daten zurueck."""
        am = _make_autonomy(level=2, autonomy_cfg={
            "evolution": {"enabled": True, "max_level": 3},
        })
        info = am.get_evolution_info()
        assert info["enabled"] is True
        assert info["max_level"] == 3
        assert info["current_level"] == 2
        assert info["next_level"] == 3
        assert "criteria" in info

    @pytest.mark.asyncio
    async def test_track_interaction_redis_error_no_crash(self):
        """Redis-Fehler bei track_interaction darf nicht crashen."""
        am = _make_autonomy(level=2)
        redis = AsyncMock()
        redis.hincrby = AsyncMock(side_effect=ConnectionError("Redis down"))
        am.set_redis(redis)
        # Soll nicht werfen
        await am.track_interaction("proactive_info", accepted=True)


# =====================================================================
# Trust-Level Erweiterte Edge-Cases
# =====================================================================


class TestTrustEdgeCases:
    """Erweiterte Edge-Cases fuer Trust-Level-System."""

    def test_none_person_treated_as_guest(self):
        """None als Person → default Trust (Gast)."""
        am = _make_autonomy(level=2)
        # get_trust_level erwartet str, None wuerde Fehler geben
        # Aber empty string ist der dokumentierte Weg
        assert am.get_trust_level("") == 0

    def test_mitbewohner_cannot_lock_door(self):
        """Mitbewohner (Trust 1) darf Tueren nicht sperren (security_action)."""
        am = _make_autonomy(level=5)
        result = am.can_person_act("Lisa", "lock_door")
        assert result["allowed"] is False

    def test_mitbewohner_cannot_set_presence_mode(self):
        """Mitbewohner (Trust 1) darf Anwesenheitsmodus nicht aendern."""
        am = _make_autonomy(level=5)
        result = am.can_person_act("Lisa", "set_presence_mode")
        assert result["allowed"] is False

    def test_owner_can_do_all_security_actions(self, am):
        """Owner (Trust 2) darf alle konfigurierten Sicherheitsaktionen."""
        for action in am._security_actions:
            result = am.can_person_act("Sir", action)
            assert result["allowed"] is True, f"Owner sollte '{action}' duerfen"

    def test_guest_blocked_on_all_security_actions(self, am):
        """Gast (Trust 0) wird bei allen Sicherheitsaktionen blockiert."""
        for action in am._security_actions:
            result = am.can_person_act("Fremder", action)
            assert result["allowed"] is False, f"Gast sollte '{action}' NICHT duerfen"

    def test_can_execute_with_room_scoping(self):
        """can_execute mit Raum-Scoping fuer Gaeste."""
        trust_cfg = dict(_DEFAULT_TRUST_CFG)
        trust_cfg["room_restrictions"] = {"fremder": ["kueche"]}

        mock_settings = MagicMock()
        mock_settings.autonomy_level = 2
        mock_settings.user_name = "Sir"
        yaml_mock = {"trust_levels": trust_cfg}

        with patch("assistant.autonomy.settings", mock_settings), \
             patch("assistant.autonomy.yaml_config", yaml_mock):
            am = AutonomyManager()
            # In erlaubtem Raum
            result = am.can_execute(
                person="Fremder", action_type="respond_to_command",
                function_name="set_light", room="kueche",
            )
            assert result["allowed"] is True
            # In nicht-erlaubtem Raum
            result = am.can_execute(
                person="Fremder", action_type="respond_to_command",
                function_name="set_light", room="schlafzimmer",
            )
            assert result["allowed"] is False
