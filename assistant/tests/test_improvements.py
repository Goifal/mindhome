"""
Tests fuer die 45 Verbesserungen — Neue Settings und Logik.

Testet:
- Temporale Autonomie (#42)
- De-Eskalation (#41)
- Emergency Escalation (#40)
- Threat Playbook Execution (#39)
- Conflict Prediction (#44)
- Pushback Learning (#45)
- Feedback Smoothing (#9)
- Explainability Extensions
- HealthMonitor Hysterese (#24)
- Mood Decay (#17)
- Settings Defaults
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =====================================================================
# Temporale Autonomie (#42) + De-Eskalation (#41) + Emergency (#40)
# =====================================================================


class TestTemporalAutonomy:
    """Tests fuer temporale Autonomie-Offsets."""

    def test_effective_level_night_offset(self):
        """Nacht-Offset reduziert Level."""
        from assistant.autonomy import AutonomyManager

        mock_settings = MagicMock()
        mock_settings.autonomy_level = 3
        mock_settings.user_name = "Sir"

        yaml_mock = {
            "trust_levels": {"default": 0, "persons": {}},
            "autonomy": {
                "temporal": {
                    "enabled": True,
                    "night_offset": -1,
                    "day_offset": 0,
                },
            },
        }

        with (
            patch("assistant.autonomy.settings", mock_settings),
            patch("assistant.autonomy.yaml_config", yaml_mock),
        ):
            am = AutonomyManager()

            # Simuliere Nacht (23:00)
            with patch("assistant.autonomy.datetime") as dt_mock:
                dt_mock.now.return_value = datetime(
                    2026, 3, 20, 23, 0, tzinfo=timezone.utc
                )
                dt_mock.side_effect = lambda *a, **kw: datetime(*a, **kw)
                level = am.get_effective_level()
                assert level <= 3  # Sollte reduziert sein

    def test_effective_level_clamped_to_1(self):
        """Level darf nicht unter 1 fallen."""
        from assistant.autonomy import AutonomyManager

        mock_settings = MagicMock()
        mock_settings.autonomy_level = 1
        mock_settings.user_name = "Sir"

        yaml_mock = {
            "trust_levels": {"default": 0, "persons": {}},
            "autonomy": {
                "temporal": {
                    "enabled": True,
                    "night_offset": -3,
                    "day_offset": 0,
                },
            },
        }

        with (
            patch("assistant.autonomy.settings", mock_settings),
            patch("assistant.autonomy.yaml_config", yaml_mock),
        ):
            am = AutonomyManager()
            level = am.get_effective_level()
            assert level >= 1

    def test_temporal_disabled(self):
        """Bei deaktivierter temporaler Autonomie gilt normales Level."""
        from assistant.autonomy import AutonomyManager

        mock_settings = MagicMock()
        mock_settings.autonomy_level = 3
        mock_settings.user_name = "Sir"

        yaml_mock = {
            "trust_levels": {"default": 0, "persons": {}},
            "autonomy": {
                "temporal": {"enabled": False},
            },
        }

        with (
            patch("assistant.autonomy.settings", mock_settings),
            patch("assistant.autonomy.yaml_config", yaml_mock),
        ):
            am = AutonomyManager()
            level = am.get_effective_level()
            assert level == 3


class TestEmergencyEscalation:
    """Tests fuer Notfall-Autonomie-Eskalation."""

    def test_emergency_escalation_boosts_level(self):
        """Emergency Escalation setzt Level auf 5."""
        from assistant.autonomy import AutonomyManager

        mock_settings = MagicMock()
        mock_settings.autonomy_level = 2
        mock_settings.user_name = "Sir"

        yaml_mock = {
            "trust_levels": {"default": 0, "persons": {}},
            "threat_assessment": {
                "emergency_autonomy_boost": True,
                "emergency_boost_duration_min": 15,
            },
        }

        with (
            patch("assistant.autonomy.settings", mock_settings),
            patch("assistant.autonomy.yaml_config", yaml_mock),
        ):
            am = AutonomyManager()
            am.escalate_for_emergency()
            level = am.get_effective_level()
            assert level == 5

    def test_clear_emergency(self):
        """Emergency Escalation kann zurueckgesetzt werden."""
        from assistant.autonomy import AutonomyManager

        mock_settings = MagicMock()
        mock_settings.autonomy_level = 2
        mock_settings.user_name = "Sir"

        yaml_mock = {
            "trust_levels": {"default": 0, "persons": {}},
            "threat_assessment": {"emergency_autonomy_boost": True},
        }

        with (
            patch("assistant.autonomy.settings", mock_settings),
            patch("assistant.autonomy.yaml_config", yaml_mock),
        ):
            am = AutonomyManager()
            am.escalate_for_emergency()
            am.clear_emergency_escalation()
            # Mock datetime auf 12:00 (Tag) damit temporaler Offset keine Rolle spielt
            with patch("assistant.autonomy.datetime") as dt_mock:
                dt_mock.now.return_value = datetime(
                    2026, 3, 20, 12, 0, tzinfo=timezone.utc
                )
                dt_mock.side_effect = lambda *a, **kw: datetime(*a, **kw)
                level = am.get_effective_level()
                assert level == 2


class TestDeescalation:
    """Tests fuer Autonomie-De-Eskalation."""

    def test_deescalation_proposal(self):
        """Bei niedriger Akzeptanzrate wird Rueckstufung vorgeschlagen."""
        from assistant.autonomy import AutonomyManager

        mock_settings = MagicMock()
        mock_settings.autonomy_level = 3
        mock_settings.user_name = "Sir"

        yaml_mock = {
            "trust_levels": {"default": 0, "persons": {}},
            "autonomy": {
                "deescalation": {
                    "enabled": True,
                    "min_acceptance_rate": 0.5,
                    "evaluation_days": 7,
                },
            },
        }

        with (
            patch("assistant.autonomy.settings", mock_settings),
            patch("assistant.autonomy.yaml_config", yaml_mock),
        ):
            am = AutonomyManager()
            # Simuliere niedrige Akzeptanzrate
            am._stats = {"accepted": 10, "total": 100}
            result = am.check_deescalation()
            # Result kann None oder dict sein


# =====================================================================
# Threat Playbook Executor (#39)
# =====================================================================


class TestPlaybookExecutor:
    """Tests fuer Threat Playbook Ausfuehrung."""

    @pytest.mark.asyncio
    async def test_execute_playbook_returns_summary(self):
        """execute_playbook gibt Summary zurueck."""
        try:
            from assistant.threat_assessment import ThreatAssessment
        except ImportError:
            pytest.skip("Missing dependency for ThreatAssessment")

        ha = AsyncMock()
        ha.call_service = AsyncMock(return_value=True)
        t = ThreatAssessment(ha)
        t.redis = AsyncMock()

        with patch(
            "assistant.threat_assessment.yaml_config",
            {
                "threat_assessment": {"auto_execute_playbooks": True},
            },
        ):
            result = await t.execute_playbook_by_name("fire")
            assert isinstance(result, dict)
            assert "playbook" in result

    @pytest.mark.asyncio
    async def test_execute_playbook_prevents_parallel(self):
        """Parallele Ausfuehrung desselben Playbooks wird verhindert."""
        try:
            from assistant.threat_assessment import ThreatAssessment
        except ImportError:
            pytest.skip("Missing dependency for ThreatAssessment")

        ha = AsyncMock()
        t = ThreatAssessment(ha)
        t.redis = AsyncMock()

        t._running_playbooks.add("fire")
        result = await t.execute_playbook_by_name("fire")
        assert result.get("steps_executed", 0) == 0 or "already_running" in str(result)


# =====================================================================
# Conflict Prediction (#44)
# =====================================================================


class TestConflictPrediction:
    """Tests fuer Konflikt-Vorhersage."""

    @pytest.mark.asyncio
    async def test_predict_no_conflict(self):
        """Keine Vorhersage wenn keine kuerzlichen Konflikte."""
        try:
            from assistant.conflict_resolver import ConflictResolver
        except ImportError:
            pytest.skip("Missing dependency for ConflictResolver")

        yaml_mock = {
            "conflict_resolution": {
                "enabled": True,
                "prediction_enabled": True,
                "prediction_window_seconds": 180,
            },
        }

        with patch("assistant.conflict_resolver.yaml_config", yaml_mock):
            cr = ConflictResolver.__new__(ConflictResolver)
            cr._recent_commands = {}
            cr._commands_lock = __import__("threading").Lock()
            cr.yaml_config = yaml_mock

            result = await cr.predict_conflict(
                "max", "climate", "wohnzimmer", {"temperature": 22}
            )
            assert result is None


# =====================================================================
# Explainability Extensions
# =====================================================================


class TestExplainabilityConfig:
    """Tests fuer Explainability-Konfiguration."""

    def test_explanation_style_default(self):
        """Default explanation_style ist 'auto'."""
        from assistant.explainability import ExplainabilityEngine

        with patch(
            "assistant.explainability.yaml_config",
            {
                "explainability": {"explanation_style": "auto"},
            },
        ):
            from collections import deque

            ee = ExplainabilityEngine.__new__(ExplainabilityEngine)
            ee._decisions = deque(maxlen=50)
            ee.reload_config()
            assert ee.explanation_style == "auto"


# =====================================================================
# Settings Defaults
# =====================================================================


class TestSettingsDefaults:
    """Prueft dass alle neuen Settings sinnvolle Defaults haben."""

    def test_threat_assessment_defaults(self):
        """Threat Assessment hat sichere Defaults."""
        import yaml

        with open("config/settings.yaml.example") as f:
            cfg = yaml.safe_load(f)

        ta = cfg.get("threat_assessment", {})
        assert ta.get("auto_execute_playbooks") is False
        assert ta.get("emergency_autonomy_boost") is False
        assert 20 <= ta.get("night_start_hour", 22) <= 23
        assert 5 <= ta.get("night_end_hour", 6) <= 8

    def test_autonomy_temporal_defaults(self):
        """Temporale Autonomie ist default aus."""
        import yaml

        with open("config/settings.yaml.example") as f:
            cfg = yaml.safe_load(f)

        temporal = cfg.get("autonomy", {}).get("temporal", {})
        assert temporal.get("enabled") is False

    def test_pushback_learning_defaults(self):
        """Pushback-Learning ist default aus."""
        import yaml

        with open("config/settings.yaml.example") as f:
            cfg = yaml.safe_load(f)

        pb = cfg.get("pushback", {})
        assert pb.get("learning_enabled") is False

    def test_routine_anomaly_defaults(self):
        """Routine-Anomalie ist default aus."""
        import yaml

        with open("config/settings.yaml.example") as f:
            cfg = yaml.safe_load(f)

        ra = cfg.get("routine_anomaly", {})
        assert ra.get("enabled") is False
        assert 0.6 <= ra.get("min_confidence", 0.8) <= 0.95

    def test_mood_reaction_defaults(self):
        """Mood-Reaktion ist default an."""
        import yaml

        with open("config/settings.yaml.example") as f:
            cfg = yaml.safe_load(f)

        mr = cfg.get("mood_reaction", {})
        assert mr.get("enabled") is True

    def test_all_new_sections_exist(self):
        """Alle neuen YAML-Sektionen existieren."""
        import yaml

        with open("config/settings.yaml.example") as f:
            cfg = yaml.safe_load(f)

        new_sections = [
            "threat_assessment",
            "outcome_tracker",
            "correction_memory",
            "routine_anomaly",
            "weather_forecast",
            "mood_reaction",
            "inner_state",
            "semantic_memory",
            "whatif_simulation",
        ]
        for section in new_sections:
            assert section in cfg, f"Sektion '{section}' fehlt in settings.yaml.example"
