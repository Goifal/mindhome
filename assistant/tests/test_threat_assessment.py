"""
Tests fuer ThreatAssessment — Sicherheitsanalyse + Score + Eskalation.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from assistant.threat_assessment import ThreatAssessment


@pytest.fixture
def threat():
    ha = AsyncMock()
    t = ThreatAssessment(ha)
    t.redis = AsyncMock()
    return t


class TestCheckSmokeFire:
    """Tests fuer _check_smoke_fire()."""

    def test_no_smoke(self, threat):
        states = [{"entity_id": "binary_sensor.motion_flur", "state": "on"}]
        result = threat._check_smoke_fire(states)
        assert result == []

    def test_smoke_detected(self, threat):
        states = [
            {"entity_id": "binary_sensor.rauchmelder_kueche", "state": "on",
             "attributes": {"friendly_name": "Rauchmelder Kueche"}},
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
            {"entity_id": "binary_sensor.co2_sensor_keller", "state": "on",
             "attributes": {"friendly_name": "CO2 Keller"}},
        ]
        result = threat._check_smoke_fire(states)
        assert result == []

    def test_carbon_monoxide_device_class_detected(self, threat):
        """Echte CO-Melder (device_class: carbon_monoxide) werden erkannt."""
        states = [
            {"entity_id": "binary_sensor.co_melder_garage", "state": "on",
             "attributes": {"friendly_name": "CO Melder", "device_class": "carbon_monoxide"}},
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
            {"entity_id": "binary_sensor.wasserleck_bad", "state": "on",
             "attributes": {"friendly_name": "Wassersensor Bad"}},
        ]
        result = threat._check_water_leak(states)
        assert len(result) == 1
        assert result[0]["type"] == "water_leak"
        assert result[0]["urgency"] == "critical"

    def test_moisture_sensor(self, threat):
        states = [
            {"entity_id": "binary_sensor.moisture_keller", "state": "on",
             "attributes": {"friendly_name": "Feuchtigkeit Keller"}},
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
            {"entity_id": "binary_sensor.door_garage", "state": "on"},
        ]
        result = await threat.get_security_score()
        assert result["score"] <= 70
        assert "2 Tuer(en) offen" in result["details"]

    @pytest.mark.asyncio
    async def test_unlocked_locks_reduce_score(self, threat):
        threat.ha.get_states.return_value = [
            {"entity_id": "lock.front", "state": "unlocked"},
        ]
        result = await threat.get_security_score()
        assert result["score"] == 80
        assert "1 Schloss/Schloesser entriegelt" in result["details"]

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
        result = await threat.escalate_threat({"type": "unknown_device", "urgency": "medium"})
        assert result == []

    @pytest.mark.asyncio
    async def test_smoke_turns_on_lights(self, threat):
        threat.ha.get_states.return_value = [
            {"entity_id": "light.wohnzimmer", "state": "off"},
            {"entity_id": "light.flur", "state": "off"},
        ]
        threat.ha.call_service.return_value = True
        result = await threat.escalate_threat({"type": "smoke_fire", "urgency": "critical"})
        assert "Alle Lichter eingeschaltet" in result
        assert threat.ha.call_service.call_count == 2

    @pytest.mark.asyncio
    async def test_door_open_warns_but_no_auto_lock(self, threat):
        """F-009: Keine Auto-Verriegelung — nur Warnung (verhindert Aussperren)."""
        result = await threat.escalate_threat({
            "type": "lock_open_empty",
            "urgency": "critical",
            "entity": "lock.front_door",
        })
        assert any("WARNUNG" in a for a in result)
        assert any("manuell verriegeln" in a for a in result)
        # call_service darf NICHT aufgerufen werden (keine Auto-Verriegelung)
        threat.ha.call_service.assert_not_called()


class TestStormWindows:
    """Tests fuer _check_storm_windows()."""

    def test_no_storm(self, threat):
        states = [
            {"entity_id": "weather.home", "state": "sunny", "attributes": {"wind_speed": 20}},
            {"entity_id": "binary_sensor.window_wz", "state": "on"},
        ]
        assert threat._check_storm_windows(states) == []

    def test_storm_with_open_windows(self, threat):
        states = [
            {"entity_id": "weather.home", "state": "windy", "attributes": {"wind_speed": 70}},
            {"entity_id": "binary_sensor.fenster_kueche", "state": "on",
             "attributes": {"friendly_name": "Fenster Kueche"}},
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
            {"entity_id": "binary_sensor.door_front", "state": "on",
             "attributes": {"friendly_name": "Haustuer"}},
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
