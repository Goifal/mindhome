"""Tests for predictive_maintenance - device failure prediction and maintenance."""

from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from assistant.predictive_maintenance import (
    DeviceLifecycleEntry,
    PredictiveMaintenance,
    DEFAULT_LIFESPANS,
    DRAIN_THRESHOLDS,
)


# ---------------------------------------------------------------------------
# DeviceLifecycleEntry
# ---------------------------------------------------------------------------

class TestDeviceLifecycleEntry:
    def test_defaults_with_no_data(self):
        entry = DeviceLifecycleEntry("sensor.test")
        assert entry.entity_id == "sensor.test"
        assert entry.device_type == "default"
        assert entry.installed_date is None
        assert entry.last_battery_level is None
        assert entry.battery_history == []
        assert entry.health_score == 100.0
        assert entry.failure_count == 0
        assert entry.total_offline_hours == 0.0
        assert entry.notes == ""

    def test_initializes_from_data_dict(self):
        data = {
            "device_type": "motion_sensor",
            "installed_date": "2024-01-15",
            "last_battery_level": 85.0,
            "battery_history": [{"level": 90, "date": "2024-06-01"}],
            "health_score": 75.5,
            "failure_count": 3,
            "total_offline_hours": 12.5,
            "notes": "Kitchen sensor",
        }
        entry = DeviceLifecycleEntry("sensor.kitchen", data)
        assert entry.device_type == "motion_sensor"
        assert entry.installed_date == "2024-01-15"
        assert entry.last_battery_level == 85.0
        assert len(entry.battery_history) == 1
        assert entry.health_score == 75.5
        assert entry.failure_count == 3
        assert entry.total_offline_hours == 12.5
        assert entry.notes == "Kitchen sensor"

    def test_to_dict_round_trip(self):
        data = {
            "device_type": "thermostat",
            "installed_date": "2023-01-01",
            "health_score": 88.888,
            "failure_count": 1,
            "total_offline_hours": 3.456,
        }
        entry = DeviceLifecycleEntry("climate.living", data)
        d = entry.to_dict()
        assert d["entity_id"] == "climate.living"
        assert d["device_type"] == "thermostat"
        assert d["health_score"] == 88.9  # rounded to 1 decimal
        assert d["total_offline_hours"] == 3.5  # rounded to 1 decimal

    def test_to_dict_truncates_battery_history_to_30(self):
        history = [{"level": 100 - i, "date": f"2024-01-{i+1:02d}"} for i in range(50)]
        entry = DeviceLifecycleEntry("sensor.x", {"battery_history": history})
        d = entry.to_dict()
        assert len(d["battery_history"]) == 30
        # Should keep last 30 entries
        assert d["battery_history"][0] == history[20]

    def test_to_dict_with_none_data(self):
        entry = DeviceLifecycleEntry("sensor.y", None)
        d = entry.to_dict()
        assert d["entity_id"] == "sensor.y"
        assert d["installed_date"] is None


# ---------------------------------------------------------------------------
# PredictiveMaintenance.__init__
# ---------------------------------------------------------------------------

@patch("assistant.predictive_maintenance.yaml_config", {})
class TestPredictiveMaintenanceInit:
    def test_defaults(self):
        pm = PredictiveMaintenance()
        assert pm.enabled is True
        assert pm.lookback_days == 90
        assert pm.failure_probability_threshold == 0.7
        assert pm.battery_drain_alert_pct == 5.0
        assert pm.redis is None

    def test_config_override(self):
        with patch("assistant.predictive_maintenance.yaml_config", {
            "predictive_maintenance": {"enabled": False, "lookback_days": 30}
        }):
            pm = PredictiveMaintenance()
            assert pm.enabled is False
            assert pm.lookback_days == 30

    def test_custom_lifespans_merged(self):
        with patch("assistant.predictive_maintenance.yaml_config", {
            "predictive_maintenance": {
                "typical_lifespans": {"light_bulb": 2000}
            }
        }):
            pm = PredictiveMaintenance()
            assert pm._lifespans["light_bulb"] == 2000
            # Default ones should still be present
            assert pm._lifespans["smoke_detector"] == DEFAULT_LIFESPANS["smoke_detector"]


# ---------------------------------------------------------------------------
# _get_or_create
# ---------------------------------------------------------------------------

@patch("assistant.predictive_maintenance.yaml_config", {})
class TestGetOrCreate:
    def test_creates_new_entry(self):
        pm = PredictiveMaintenance()
        entry = pm._get_or_create("sensor.new")
        assert isinstance(entry, DeviceLifecycleEntry)
        assert entry.entity_id == "sensor.new"
        assert "sensor.new" in pm._devices

    def test_returns_existing_entry(self):
        pm = PredictiveMaintenance()
        entry1 = pm._get_or_create("sensor.exist")
        entry1.notes = "modified"
        entry2 = pm._get_or_create("sensor.exist")
        assert entry2 is entry1
        assert entry2.notes == "modified"


# ---------------------------------------------------------------------------
# calculate_battery_drain_rate
# ---------------------------------------------------------------------------

@patch("assistant.predictive_maintenance.yaml_config", {})
class TestCalculateBatteryDrainRate:
    def _make_pm_with_history(self, entity_id, history):
        pm = PredictiveMaintenance()
        entry = pm._get_or_create(entity_id)
        entry.battery_history = history
        return pm

    def test_returns_none_for_unknown_device(self):
        pm = PredictiveMaintenance()
        assert pm.calculate_battery_drain_rate("sensor.unknown") is None

    def test_returns_none_for_less_than_2_entries(self):
        pm = self._make_pm_with_history("sensor.x", [
            {"level": 100, "date": "2024-01-01T00:00:00"}
        ])
        assert pm.calculate_battery_drain_rate("sensor.x") is None

    def test_normal_drain_rate(self):
        """1% drop over 7 days = 1%/week => normal."""
        now = datetime.now()
        week_ago = now - timedelta(days=7)
        pm = self._make_pm_with_history("sensor.a", [
            {"level": 100, "date": week_ago.isoformat()},
            {"level": 99, "date": now.isoformat()},
        ])
        result = pm.calculate_battery_drain_rate("sensor.a")
        assert result is not None
        assert result["severity"] == "normal"
        assert result["pct_per_week"] == pytest.approx(1.0, abs=0.1)

    def test_concerning_drain_rate(self):
        """5% drop over 7 days = 5%/week => concerning."""
        now = datetime.now()
        week_ago = now - timedelta(days=7)
        pm = self._make_pm_with_history("sensor.b", [
            {"level": 100, "date": week_ago.isoformat()},
            {"level": 95, "date": now.isoformat()},
        ])
        result = pm.calculate_battery_drain_rate("sensor.b")
        assert result["severity"] == "concerning"

    def test_critical_drain_rate(self):
        """20% drop over 7 days = 20%/week => critical."""
        now = datetime.now()
        week_ago = now - timedelta(days=7)
        pm = self._make_pm_with_history("sensor.c", [
            {"level": 100, "date": week_ago.isoformat()},
            {"level": 80, "date": now.isoformat()},
        ])
        result = pm.calculate_battery_drain_rate("sensor.c")
        assert result["severity"] == "critical"
        assert result["pct_per_week"] == pytest.approx(20.0, abs=0.5)

    def test_no_drop_returns_normal_with_zero_rate(self):
        """No drain (battery went up or stayed same)."""
        now = datetime.now()
        week_ago = now - timedelta(days=7)
        pm = self._make_pm_with_history("sensor.d", [
            {"level": 80, "date": week_ago.isoformat()},
            {"level": 85, "date": now.isoformat()},
        ])
        result = pm.calculate_battery_drain_rate("sensor.d")
        assert result["pct_per_week"] == 0
        assert result["days_until_empty"] is None
        assert result["severity"] == "normal"

    def test_days_until_empty_calculation(self):
        """10% drop over 10 days = 1%/day => at 50% level, ~50 days left."""
        now = datetime.now()
        ten_days_ago = now - timedelta(days=10)
        pm = self._make_pm_with_history("sensor.e", [
            {"level": 60, "date": ten_days_ago.isoformat()},
            {"level": 50, "date": now.isoformat()},
        ])
        result = pm.calculate_battery_drain_rate("sensor.e")
        assert result["days_until_empty"] == 50
        assert result["current_level"] == 50

    def test_invalid_date_format_returns_none(self):
        pm = self._make_pm_with_history("sensor.f", [
            {"level": 100, "date": "not-a-date"},
            {"level": 90, "date": "also-not-a-date"},
        ])
        result = pm.calculate_battery_drain_rate("sensor.f")
        assert result is None

    @pytest.mark.parametrize("drop,expected_severity", [
        (1.0, "normal"),       # 1%/week < 2.0
        (1.9, "normal"),       # just under threshold
        (5.0, "concerning"),   # == concerning threshold
        (9.9, "concerning"),   # just under critical
        (10.0, "critical"),    # == critical threshold
        (20.0, "critical"),    # well above critical
    ])
    def test_severity_thresholds(self, drop, expected_severity):
        now = datetime.now()
        week_ago = now - timedelta(days=7)
        pm = self._make_pm_with_history("sensor.thresh", [
            {"level": 100, "date": week_ago.isoformat()},
            {"level": 100 - drop, "date": now.isoformat()},
        ])
        result = pm.calculate_battery_drain_rate("sensor.thresh")
        assert result["severity"] == expected_severity


# ---------------------------------------------------------------------------
# calculate_health_score
# ---------------------------------------------------------------------------

@patch("assistant.predictive_maintenance.yaml_config", {})
class TestCalculateHealthScore:
    def test_unknown_device_returns_100(self):
        pm = PredictiveMaintenance()
        result = pm.calculate_health_score("sensor.nope")
        assert result["score"] == 100
        assert result["risk"] == "low"
        assert result["factors"] == {}

    def test_new_device_full_health(self):
        pm = PredictiveMaintenance()
        entry = pm._get_or_create("sensor.new")
        entry.device_type = "motion_sensor"
        entry.installed_date = datetime.now().isoformat()
        result = pm.calculate_health_score("sensor.new")
        assert result["score"] >= 95
        assert result["risk"] == "low"

    def test_old_device_age_penalty(self):
        pm = PredictiveMaintenance()
        entry = pm._get_or_create("sensor.old")
        entry.device_type = "motion_sensor"
        # Installed 5 years ago (full lifespan)
        entry.installed_date = (datetime.now() - timedelta(days=1825)).isoformat()
        result = pm.calculate_health_score("sensor.old")
        assert "age" in result["factors"]
        assert result["factors"]["age"]["penalty"] == pytest.approx(40, abs=2)

    def test_device_with_failures_penalty(self):
        pm = PredictiveMaintenance()
        entry = pm._get_or_create("sensor.fail")
        entry.failure_count = 4
        entry.total_offline_hours = 10
        result = pm.calculate_health_score("sensor.fail")
        assert "offline_events" in result["factors"]
        assert result["factors"]["offline_events"]["penalty"] == 20  # 4*5=20

    def test_failure_penalty_capped_at_20(self):
        pm = PredictiveMaintenance()
        entry = pm._get_or_create("sensor.many_fail")
        entry.failure_count = 100
        result = pm.calculate_health_score("sensor.many_fail")
        assert result["factors"]["offline_events"]["penalty"] == 20

    @pytest.mark.parametrize("score,expected_risk", [
        (100, "low"),
        (70, "low"),
        (69, "medium"),
        (50, "medium"),
        (49, "high"),
        (30, "high"),
        (29, "critical"),
        (0, "critical"),
    ])
    def test_risk_levels(self, score, expected_risk):
        pm = PredictiveMaintenance()
        entry = pm._get_or_create("sensor.risk")
        # Manipulate to get target score via failure_count
        # score = 100 - min(20, failure_count*5), so we set failure_count
        # to get near target. For precise control, set health_score won't work
        # since calculate_health_score recalculates. Instead test risk mapping directly.
        # We test by setting factors that yield the desired score range.
        entry.failure_count = 0  # reset

        if score <= 29:
            # Need large penalties: age=40 + drain=30 + offline=20 = 90 penalty -> score=10
            entry.device_type = "motion_sensor"
            entry.installed_date = (datetime.now() - timedelta(days=3650)).isoformat()
            entry.failure_count = 4
            # Add critical drain
            now = datetime.now()
            week_ago = now - timedelta(days=7)
            entry.battery_history = [
                {"level": 100, "date": week_ago.isoformat()},
                {"level": 80, "date": now.isoformat()},
            ]
        elif score <= 49:
            entry.device_type = "motion_sensor"
            entry.installed_date = (datetime.now() - timedelta(days=1825)).isoformat()
            entry.failure_count = 3  # 15 penalty
        elif score <= 69:
            entry.failure_count = 4  # 20 penalty + some age
            entry.device_type = "motion_sensor"
            entry.installed_date = (datetime.now() - timedelta(days=900)).isoformat()
        # else: no penalties, score ~ 100

        result = pm.calculate_health_score("sensor.risk")
        assert result["risk"] == expected_risk

    def test_score_never_below_zero(self):
        pm = PredictiveMaintenance()
        entry = pm._get_or_create("sensor.floor")
        entry.device_type = "light_bulb"
        entry.installed_date = (datetime.now() - timedelta(days=10000)).isoformat()
        entry.failure_count = 100
        now = datetime.now()
        week_ago = now - timedelta(days=7)
        entry.battery_history = [
            {"level": 100, "date": week_ago.isoformat()},
            {"level": 30, "date": now.isoformat()},
        ]
        result = pm.calculate_health_score("sensor.floor")
        assert result["score"] >= 0


# ---------------------------------------------------------------------------
# predict_failures
# ---------------------------------------------------------------------------

@patch("assistant.predictive_maintenance.yaml_config", {})
class TestPredictFailures:
    def test_empty_devices_returns_empty(self):
        pm = PredictiveMaintenance()
        assert pm.predict_failures() == []

    def test_healthy_devices_not_included(self):
        pm = PredictiveMaintenance()
        entry = pm._get_or_create("sensor.healthy")
        entry.device_type = "motion_sensor"
        entry.installed_date = datetime.now().isoformat()
        result = pm.predict_failures()
        assert len(result) == 0

    def test_at_risk_device_included(self):
        pm = PredictiveMaintenance()
        entry = pm._get_or_create("sensor.risky")
        entry.device_type = "motion_sensor"
        # Very old device with failures
        entry.installed_date = (datetime.now() - timedelta(days=1825)).isoformat()
        entry.failure_count = 4
        result = pm.predict_failures()
        assert len(result) >= 1
        assert result[0]["entity_id"] == "sensor.risky"

    def test_predictions_sorted_critical_first(self):
        pm = PredictiveMaintenance()
        # High risk device
        e1 = pm._get_or_create("sensor.high")
        e1.device_type = "motion_sensor"
        e1.installed_date = (datetime.now() - timedelta(days=1825)).isoformat()
        e1.failure_count = 3

        # Critical risk device
        e2 = pm._get_or_create("sensor.critical")
        e2.device_type = "light_bulb"
        e2.installed_date = (datetime.now() - timedelta(days=5000)).isoformat()
        e2.failure_count = 4
        now = datetime.now()
        week_ago = now - timedelta(days=7)
        e2.battery_history = [
            {"level": 100, "date": week_ago.isoformat()},
            {"level": 50, "date": now.isoformat()},
        ]

        result = pm.predict_failures()
        if len(result) >= 2:
            assert result[0]["risk"] == "critical"


# ---------------------------------------------------------------------------
# get_maintenance_suggestions
# ---------------------------------------------------------------------------

@patch("assistant.predictive_maintenance.yaml_config", {})
class TestGetMaintenanceSuggestions:
    def test_empty_devices_returns_empty(self):
        pm = PredictiveMaintenance()
        assert pm.get_maintenance_suggestions() == []

    def test_battery_replacement_suggestion(self):
        pm = PredictiveMaintenance()
        entry = pm._get_or_create("sensor.low_batt")
        now = datetime.now()
        # 10% drop over 7 days at 20% level => ~14 days remaining
        week_ago = now - timedelta(days=7)
        entry.battery_history = [
            {"level": 30, "date": week_ago.isoformat()},
            {"level": 20, "date": now.isoformat()},
        ]
        suggestions = pm.get_maintenance_suggestions()
        batt = [s for s in suggestions if s["type"] == "battery_replacement"]
        assert len(batt) >= 1
        assert batt[0]["entity_id"] == "sensor.low_batt"

    def test_battery_high_urgency_when_7_days_or_less(self):
        pm = PredictiveMaintenance()
        entry = pm._get_or_create("sensor.urgent")
        now = datetime.now()
        # 10% drop over 7 days at 5% level => ~3.5 days remaining
        week_ago = now - timedelta(days=7)
        entry.battery_history = [
            {"level": 15, "date": week_ago.isoformat()},
            {"level": 5, "date": now.isoformat()},
        ]
        suggestions = pm.get_maintenance_suggestions()
        batt = [s for s in suggestions if s["type"] == "battery_replacement"]
        assert len(batt) >= 1
        assert batt[0]["urgency"] == "high"

    def test_end_of_life_suggestion(self):
        pm = PredictiveMaintenance()
        entry = pm._get_or_create("sensor.old")
        entry.device_type = "motion_sensor"
        # Installed 4.6 years ago (>= 90% of 5-year lifespan)
        entry.installed_date = (datetime.now() - timedelta(days=1680)).isoformat()
        suggestions = pm.get_maintenance_suggestions()
        eol = [s for s in suggestions if s["type"] == "end_of_life"]
        assert len(eol) >= 1
        assert eol[0]["urgency"] == "medium"

    def test_no_end_of_life_for_young_device(self):
        pm = PredictiveMaintenance()
        entry = pm._get_or_create("sensor.young")
        entry.device_type = "motion_sensor"
        entry.installed_date = datetime.now().isoformat()
        suggestions = pm.get_maintenance_suggestions()
        eol = [s for s in suggestions if s["type"] == "end_of_life"]
        assert len(eol) == 0

    def test_suggestions_sorted_high_urgency_first(self):
        pm = PredictiveMaintenance()
        # Medium urgency (end of life)
        e1 = pm._get_or_create("sensor.eol")
        e1.device_type = "motion_sensor"
        e1.installed_date = (datetime.now() - timedelta(days=1700)).isoformat()

        # High urgency (battery about to die)
        e2 = pm._get_or_create("sensor.batt_dying")
        now = datetime.now()
        week_ago = now - timedelta(days=7)
        e2.battery_history = [
            {"level": 15, "date": week_ago.isoformat()},
            {"level": 5, "date": now.isoformat()},
        ]

        suggestions = pm.get_maintenance_suggestions()
        if len(suggestions) >= 2:
            assert suggestions[0]["urgency"] == "high"

    def test_no_suggestion_for_battery_above_30_days(self):
        """Device with >30 days remaining should not trigger suggestion."""
        pm = PredictiveMaintenance()
        entry = pm._get_or_create("sensor.ok_batt")
        now = datetime.now()
        month_ago = now - timedelta(days=30)
        # 1% drop over 30 days at 90% level => ~2700 days remaining
        entry.battery_history = [
            {"level": 91, "date": month_ago.isoformat()},
            {"level": 90, "date": now.isoformat()},
        ]
        suggestions = pm.get_maintenance_suggestions()
        batt = [s for s in suggestions if s["type"] == "battery_replacement"]
        assert len(batt) == 0


# ---------------------------------------------------------------------------
# get_context_hint
# ---------------------------------------------------------------------------

@patch("assistant.predictive_maintenance.yaml_config", {})
class TestGetContextHint:
    def test_disabled_returns_empty(self):
        pm = PredictiveMaintenance()
        pm.enabled = False
        assert pm.get_context_hint() == ""

    def test_no_suggestions_returns_empty(self):
        pm = PredictiveMaintenance()
        assert pm.get_context_hint() == ""

    def test_returns_hint_for_high_urgency(self):
        pm = PredictiveMaintenance()
        entry = pm._get_or_create("sensor.critical_batt")
        now = datetime.now()
        week_ago = now - timedelta(days=7)
        entry.battery_history = [
            {"level": 15, "date": week_ago.isoformat()},
            {"level": 5, "date": now.isoformat()},
        ]
        hint = pm.get_context_hint()
        assert "WARTUNGSHINWEIS" in hint

    def test_no_hint_for_only_medium_urgency(self):
        pm = PredictiveMaintenance()
        entry = pm._get_or_create("sensor.eol_only")
        entry.device_type = "motion_sensor"
        entry.installed_date = (datetime.now() - timedelta(days=1700)).isoformat()
        hint = pm.get_context_hint()
        assert hint == ""


# ---------------------------------------------------------------------------
# DEFAULT_LIFESPANS and DRAIN_THRESHOLDS constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_default_lifespans_has_default_key(self):
        assert "default" in DEFAULT_LIFESPANS

    def test_drain_thresholds_ordering(self):
        assert DRAIN_THRESHOLDS["normal"] < DRAIN_THRESHOLDS["concerning"]
        assert DRAIN_THRESHOLDS["concerning"] < DRAIN_THRESHOLDS["critical"]

    @pytest.mark.parametrize("device_type", [
        "motion_sensor", "temperature_sensor", "smoke_detector",
        "smart_plug", "light_bulb", "thermostat", "lock", "camera",
    ])
    def test_default_lifespans_positive(self, device_type):
        assert DEFAULT_LIFESPANS[device_type] > 0
