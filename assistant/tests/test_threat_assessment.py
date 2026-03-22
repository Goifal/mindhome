"""
Tests fuer ThreatAssessment — Sicherheitsanalyse + Score + Eskalation.
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.threat_assessment import ThreatAssessment


@pytest.fixture
def threat():
    ha = AsyncMock()
    t = ThreatAssessment(ha)
    t.redis = AsyncMock()
    return t


@pytest.fixture
def threat_no_redis():
    """ThreatAssessment ohne Redis — fuer Graceful-Degradation-Tests."""
    ha = AsyncMock()
    t = ThreatAssessment(ha)
    t.redis = None
    return t


@pytest.fixture
def threat_with_cooldown():
    """ThreatAssessment mit aktivem Cooldown (wurde bereits benachrichtigt)."""
    ha = AsyncMock()
    t = ThreatAssessment(ha)
    t.redis = AsyncMock()
    # _was_notified returns True -> already notified, cooldown active
    t.redis.get.return_value = b"1"
    return t


class TestCheckSmokeFire:
    """Tests fuer _check_smoke_fire()."""

    def test_no_smoke(self, threat):
        states = [{"entity_id": "binary_sensor.motion_flur", "state": "on"}]
        result = threat._check_smoke_fire(states)
        assert result == []

    def test_smoke_detected(self, threat):
        states = [
            {
                "entity_id": "binary_sensor.rauchmelder_kueche",
                "state": "on",
                "attributes": {"friendly_name": "Rauchmelder Kueche"},
            },
        ]
        result = threat._check_smoke_fire(states)
        assert len(result) == 1
        assert result[0]["type"] == "smoke_fire"
        assert result[0]["urgency"] == "critical"
        assert "Rauchmelder Kueche" in result[0]["message"]

    def test_smoke_off_ignored(self, threat):
        states = [
            {"entity_id": "binary_sensor.smoke_detector", "state": "off"},
        ]
        assert threat._check_smoke_fire(states) == []

    def test_co2_sensor_excluded(self, threat):
        """CO2-Sensoren sind Luftqualitaet, kein Feueralarm — bewusst ausgeschlossen."""
        states = [
            {
                "entity_id": "binary_sensor.co2_sensor_keller",
                "state": "on",
                "attributes": {"friendly_name": "CO2 Keller"},
            },
        ]
        result = threat._check_smoke_fire(states)
        assert result == []

    def test_carbon_monoxide_device_class_detected(self, threat):
        """Echte CO-Melder (device_class: carbon_monoxide) werden erkannt."""
        states = [
            {
                "entity_id": "binary_sensor.co_melder_garage",
                "state": "on",
                "attributes": {
                    "friendly_name": "CO Melder",
                    "device_class": "carbon_monoxide",
                },
            },
        ]
        result = threat._check_smoke_fire(states)
        assert len(result) == 1
        assert result[0]["type"] == "smoke_fire"


class TestCheckWaterLeak:
    """Tests fuer _check_water_leak()."""

    def test_no_leak(self, threat):
        states = [{"entity_id": "binary_sensor.door_front", "state": "on"}]
        assert threat._check_water_leak(states) == []

    def test_water_leak_detected(self, threat):
        states = [
            {
                "entity_id": "binary_sensor.wasserleck_bad",
                "state": "on",
                "attributes": {"friendly_name": "Wassersensor Bad"},
            },
        ]
        result = threat._check_water_leak(states)
        assert len(result) == 1
        assert result[0]["type"] == "water_leak"
        assert result[0]["urgency"] == "critical"

    def test_moisture_sensor(self, threat):
        states = [
            {
                "entity_id": "binary_sensor.moisture_keller",
                "state": "on",
                "attributes": {"friendly_name": "Feuchtigkeit Keller"},
            },
        ]
        result = threat._check_water_leak(states)
        assert len(result) == 1


class TestSecurityScore:
    """Tests fuer get_security_score()."""

    @pytest.mark.asyncio
    async def test_excellent_score(self, threat):
        threat.ha.get_states.return_value = [
            {"entity_id": "binary_sensor.door_front", "state": "off"},
            {"entity_id": "lock.front", "state": "locked"},
            {"entity_id": "person.max", "state": "home"},
        ]
        result = await threat.get_security_score()
        assert result["score"] >= 90
        assert result["level"] == "excellent"
        assert "Alles in Ordnung" in result["details"]

    @pytest.mark.asyncio
    async def test_open_doors_reduce_score(self, threat):
        threat.ha.get_states.return_value = [
            {"entity_id": "binary_sensor.door_front", "state": "on"},
            {"entity_id": "binary_sensor.door_back", "state": "on"},
        ]
        result = await threat.get_security_score()
        assert result["score"] <= 70
        assert "2 Tür(en) offen" in result["details"]

    @pytest.mark.asyncio
    async def test_unlocked_locks_reduce_score(self, threat):
        threat.ha.get_states.return_value = [
            {"entity_id": "lock.front", "state": "unlocked"},
            {"entity_id": "person.max", "state": "home"},  # Verhindert Nacht-Abzug
        ]
        result = await threat.get_security_score()
        assert result["score"] == 80
        assert "1 Schloss/Schlösser entriegelt" in result["details"]

    @pytest.mark.asyncio
    async def test_smoke_critical_score(self, threat):
        threat.ha.get_states.return_value = [
            {"entity_id": "binary_sensor.rauchmelder", "state": "on"},
        ]
        result = await threat.get_security_score()
        assert result["score"] <= 50
        assert result["level"] == "critical"

    @pytest.mark.asyncio
    async def test_disabled_returns_minus_one(self, threat):
        threat.enabled = False
        result = await threat.get_security_score()
        assert result["score"] == -1
        assert result["level"] == "disabled"


class TestEscalation:
    """Tests fuer escalate_threat()."""

    @pytest.mark.asyncio
    async def test_non_critical_no_action(self, threat):
        result = await threat.escalate_threat(
            {"type": "unknown_device", "urgency": "medium"}
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_smoke_turns_on_lights(self, threat):
        threat.ha.get_states.return_value = [
            {"entity_id": "light.wohnzimmer", "state": "off"},
            {"entity_id": "light.flur", "state": "off"},
        ]
        threat.ha.call_service.return_value = True
        result = await threat.escalate_threat(
            {"type": "smoke_fire", "urgency": "critical"}
        )
        assert "Alle Lichter eingeschaltet" in result
        assert threat.ha.call_service.call_count == 2

    @pytest.mark.asyncio
    async def test_door_open_warns_but_no_auto_lock(self, threat):
        """F-009: Keine Auto-Verriegelung — nur Warnung (verhindert Aussperren)."""
        result = await threat.escalate_threat(
            {
                "type": "lock_open_empty",
                "urgency": "critical",
                "entity": "lock.front_door",
            }
        )
        assert any("WARNUNG" in a for a in result)
        assert any("manuell verriegeln" in a for a in result)
        # call_service darf NICHT aufgerufen werden (keine Auto-Verriegelung)
        threat.ha.call_service.assert_not_called()


class TestStormWindows:
    """Tests fuer _check_storm_windows()."""

    def test_no_storm(self, threat):
        states = [
            {
                "entity_id": "weather.home",
                "state": "sunny",
                "attributes": {"wind_speed": 20},
            },
            {"entity_id": "binary_sensor.window_wz", "state": "on"},
        ]
        assert threat._check_storm_windows(states) == []

    def test_storm_with_open_windows(self, threat):
        states = [
            {
                "entity_id": "weather.home",
                "state": "windy",
                "attributes": {"wind_speed": 70},
            },
            {
                "entity_id": "binary_sensor.fenster_kueche",
                "state": "on",
                "attributes": {"friendly_name": "Fenster Kueche"},
            },
        ]
        result = threat._check_storm_windows(states)
        assert len(result) == 1
        assert result[0]["type"] == "storm_windows"
        assert "70" in result[0]["message"]


class TestDoorsNobodyHome:
    """Tests fuer _check_doors_nobody_home()."""

    def test_doors_open_nobody_home(self, threat):
        states = [
            {"entity_id": "person.max", "state": "not_home"},
            {
                "entity_id": "binary_sensor.door_front",
                "state": "on",
                "attributes": {"friendly_name": "Haustuer"},
            },
        ]
        result = threat._check_doors_nobody_home(states)
        assert len(result) == 1
        assert result[0]["urgency"] == "critical"

    def test_doors_open_someone_home(self, threat):
        states = [
            {"entity_id": "person.max", "state": "home"},
            {"entity_id": "binary_sensor.door_front", "state": "on"},
        ]
        assert threat._check_doors_nobody_home(states) == []

    def test_system_monitor_not_detected_as_gate(self, threat):
        """System-Monitor-Prozesse duerfen NICHT als offene Tore erkannt werden.

        Regression-Test: HA System Monitor Entities mit 'monitor', 'motor',
        'actuator' im Namen loesten False-Positive 'Tor offen' Warnungen aus.
        """
        states = [
            {"entity_id": "person.max", "state": "not_home"},
            # System Monitor Prozess-Sensoren (binary_sensor mit "tor" als Substring)
            {
                "entity_id": "binary_sensor.system_monitor_process",
                "state": "on",
                "attributes": {"friendly_name": "System Monitor Prozess"},
            },
            {
                "entity_id": "binary_sensor.motor_status",
                "state": "on",
                "attributes": {"friendly_name": "Motor Status"},
            },
            {
                "entity_id": "binary_sensor.actuator_valve",
                "state": "on",
                "attributes": {"friendly_name": "Actuator Ventil"},
            },
        ]
        result = threat._check_doors_nobody_home(states)
        assert result == [], (
            f"System-Entities faelschlich als Tuer/Tor erkannt: {result}"
        )

    def test_system_monitor_with_device_class_running(self, threat):
        """System-Monitor Sensoren mit device_class='running' werden gefiltert.

        Auch wenn MindHome-Domain sie als 'door_window' einstuft.
        """
        states = [
            {"entity_id": "person.max", "state": "not_home"},
            {
                "entity_id": "binary_sensor.prozess_s6_svscan",
                "state": "on",
                "attributes": {
                    "friendly_name": "System Monitor Prozess s6-svscan",
                    "device_class": "running",
                },
            },
            {
                "entity_id": "binary_sensor.prozess_python3",
                "state": "on",
                "attributes": {
                    "friendly_name": "System Monitor Prozess python3",
                    "device_class": "running",
                },
            },
        ]
        result = threat._check_doors_nobody_home(states)
        assert result == [], (
            f"Prozess-Sensoren mit device_class=running faelschlich erkannt: {result}"
        )

    def test_real_gate_still_detected(self, threat):
        """Echte Tore (gartentor, tor_einfahrt) muessen weiterhin erkannt werden."""
        states = [
            {"entity_id": "person.max", "state": "not_home"},
            {
                "entity_id": "binary_sensor.gartentor",
                "state": "on",
                "attributes": {"friendly_name": "Gartentor"},
            },
        ]
        result = threat._check_doors_nobody_home(states)
        assert len(result) == 1
        assert result[0]["urgency"] == "critical"
        assert "Gartentor" in result[0]["message"]

    def test_tor_segment_in_entity_id(self, threat):
        """Entity-IDs mit 'tor' als Segment (z.B. _tor_, _tor) werden erkannt."""
        states = [
            {"entity_id": "person.max", "state": "not_home"},
            {
                "entity_id": "binary_sensor.einfahrt_tor_status",
                "state": "on",
                "attributes": {"friendly_name": "Einfahrtstor"},
            },
        ]
        result = threat._check_doors_nobody_home(states)
        assert len(result) == 1


# ------------------------------------------------------------------
# MCU Sprint 4: Extended Tests
# ------------------------------------------------------------------


class TestThreatPriority:
    """MCU Sprint 4: Multi-Krisen-Priorisierung."""

    def test_priority_ordering(self, threat):
        """Threats sorted by life-threat priority."""
        threats = [
            {"type": "water_leak", "urgency": "critical"},
            {"type": "smoke_fire", "urgency": "critical"},
            {"type": "break_in", "urgency": "critical"},
            {"type": "night_motion", "urgency": "high"},
        ]
        threats.sort(key=lambda t: threat._THREAT_PRIORITY.get(t.get("type", ""), 99))
        assert threats[0]["type"] == "smoke_fire"
        assert threats[1]["type"] == "break_in"
        assert threats[2]["type"] == "water_leak"
        assert threats[3]["type"] == "night_motion"

    def test_unknown_threat_type_last(self, threat):
        """Unknown threat types get lowest priority (99)."""
        prio = threat._THREAT_PRIORITY.get("unknown_type", 99)
        assert prio == 99

    def test_co_same_priority_as_fire(self, threat):
        """CO and fire share highest priority (0)."""
        assert threat._THREAT_PRIORITY["smoke_fire"] == 0
        assert threat._THREAT_PRIORITY["carbon_monoxide"] == 0


class TestPlaybookDuplicateGuard:
    """Tests for preventing parallel playbook execution."""

    def test_running_playbook_tracked(self, threat):
        """Playbook added to running set is properly tracked."""
        threat._running_playbooks.add("fire_smoke")
        assert "fire_smoke" in threat._running_playbooks

    def test_running_playbook_cleanup(self, threat):
        """Playbook is removed from running set after discard."""
        threat._running_playbooks.add("test_scenario")
        threat._running_playbooks.discard("test_scenario")
        assert "test_scenario" not in threat._running_playbooks


class TestConcurrentThreats:
    """Tests for handling multiple simultaneous threats."""

    def test_multiple_smoke_detectors(self, threat):
        """Multiple smoke detectors trigger multiple threat entries."""
        states = [
            {
                "entity_id": "binary_sensor.rauchmelder_kueche",
                "state": "on",
                "attributes": {"friendly_name": "Rauchmelder Kueche"},
            },
            {
                "entity_id": "binary_sensor.rauchmelder_flur",
                "state": "on",
                "attributes": {"friendly_name": "Rauchmelder Flur"},
            },
        ]
        result = threat._check_smoke_fire(states)
        assert len(result) >= 1
        assert all(r["urgency"] == "critical" for r in result)

    def test_smoke_and_water_simultaneous(self, threat):
        """Both smoke and water leak detected simultaneously."""
        states = [
            {
                "entity_id": "binary_sensor.rauchmelder",
                "state": "on",
                "attributes": {"friendly_name": "Rauchmelder"},
            },
            {
                "entity_id": "binary_sensor.wassersensor",
                "state": "on",
                "attributes": {"friendly_name": "Wassersensor Bad"},
            },
        ]
        smoke = threat._check_smoke_fire(states)
        water = threat._check_water_leak(states)
        combined = smoke + water
        combined.sort(key=lambda t: threat._THREAT_PRIORITY.get(t.get("type", ""), 99))
        if combined:
            assert combined[0]["type"] == "smoke_fire"


class TestNightMotionEdgeCases:
    """Edge cases for night motion detection."""

    def test_no_states_no_crash(self, threat):
        """Empty states list should not crash any checker."""
        assert threat._check_smoke_fire([]) == []
        assert threat._check_water_leak([]) == []
        assert threat._check_storm_windows([], {}) == []
        assert threat._check_doors_nobody_home([]) == []


class TestPostCrisisDebrief:
    """MCU Sprint 4: Post-crisis debrief notification."""

    def test_notify_callback_default_none(self, threat):
        """Default _notify_callback is None."""
        assert threat._notify_callback is None

    def test_set_notify_callback(self, threat):
        """Callback can be set via setter."""
        cb = AsyncMock()
        threat.set_notify_callback(cb)
        assert threat._notify_callback is cb


class TestSecurityHardeningReport:
    """MCU Sprint 4: Security hardening report generation."""

    @pytest.mark.asyncio
    async def test_report_with_low_battery(self, threat):
        """Report identifies low battery sensors."""
        threat.ha.get_states.return_value = [
            {
                "entity_id": "sensor.tuer_batterie",
                "state": "15",
                "attributes": {"friendly_name": "Türsensor", "battery_level": 15},
            },
        ]
        report = await threat.generate_security_hardening_report()
        assert "Niedrige Batterie" in report
        assert "Türsensor" in report

    @pytest.mark.asyncio
    async def test_report_with_unavailable_devices(self, threat):
        """Report identifies unavailable devices."""
        threat.ha.get_states.return_value = [
            {
                "entity_id": "light.wohnzimmer",
                "state": "unavailable",
                "attributes": {"friendly_name": "Wohnzimmer Licht"},
            },
        ]
        report = await threat.generate_security_hardening_report()
        assert "Nicht erreichbar" in report

    @pytest.mark.asyncio
    async def test_report_all_clean(self, threat):
        """Report shows all-clear when no issues found."""
        threat.ha.get_states.return_value = [
            {
                "entity_id": "light.wohnzimmer",
                "state": "on",
                "attributes": {"friendly_name": "Wohnzimmer"},
            },
        ]
        report = await threat.generate_security_hardening_report()
        assert "in Ordnung" in report

    @pytest.mark.asyncio
    async def test_report_empty_states(self, threat):
        """Report handles empty states gracefully."""
        threat.ha.get_states.return_value = []
        report = await threat.generate_security_hardening_report()
        assert report == ""

    @pytest.mark.asyncio
    async def test_report_timeout(self, threat):
        """Report handles HA timeout gracefully."""
        threat.ha.get_states.side_effect = asyncio.TimeoutError()
        report = await threat.generate_security_hardening_report()
        assert report == ""
