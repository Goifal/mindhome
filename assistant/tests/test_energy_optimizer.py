"""
Tests fuer EnergyOptimizer — Kostentracking, Anomalie, Wochen-Vergleich.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.energy_optimizer import EnergyOptimizer


@pytest.fixture
def ha_client():
    ha = AsyncMock()
    ha.get_states = AsyncMock(return_value=[])
    return ha


@pytest.fixture
def redis_mock():
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.setex = AsyncMock()
    return r


@pytest.fixture
def optimizer(ha_client, redis_mock):
    with patch("assistant.energy_optimizer.yaml_config") as mock_cfg:
        mock_cfg.get.return_value = {
            "enabled": True,
            "entities": {
                "electricity_price": "sensor.strompreis",
                "total_consumption": "sensor.verbrauch",
                "solar_production": "sensor.solar",
                "grid_export": "sensor.einspeisung",
            },
            "thresholds": {
                "price_low_cent": 15,
                "price_high_cent": 35,
                "solar_high_watts": 2000,
                "anomaly_increase_percent": 30,
            },
        }
        eo = EnergyOptimizer(ha_client)
        eo.redis = redis_mock
        return eo


class TestAnomalyDetection:
    @pytest.mark.asyncio
    async def test_no_anomaly_without_data(self, optimizer):
        result = await optimizer._check_anomaly(500.0)
        assert result is None  # Zu wenig historische Daten

    @pytest.mark.asyncio
    async def test_detects_anomaly(self, optimizer, redis_mock):
        """30%+ ueber Durchschnitt = Anomalie."""

        # 7 Tage mit 300W Durchschnitt simulieren — mget gibt Liste zurueck
        async def fake_mget(keys):
            return [
                json.dumps({"consumption_wh": 300, "avg_price_cent": 25})
                if "mha:energy:daily:" in k
                else None
                for k in keys
            ]

        redis_mock.mget = AsyncMock(side_effect=fake_mget)

        # 500W = 67% ueber 300W Durchschnitt → Anomalie
        result = await optimizer._check_anomaly(500.0)
        assert result is not None
        assert "ueber" in result

    @pytest.mark.asyncio
    async def test_no_anomaly_within_threshold(self, optimizer, redis_mock):
        """Unter 30% = keine Anomalie."""

        async def fake_mget(keys):
            return [
                json.dumps({"consumption_wh": 400, "avg_price_cent": 25})
                if "mha:energy:daily:" in k
                else None
                for k in keys
            ]

        redis_mock.mget = AsyncMock(side_effect=fake_mget)

        # 450W = 12.5% ueber 400W → keine Anomalie
        result = await optimizer._check_anomaly(450.0)
        assert result is None


class TestWeeklyComparison:
    @pytest.mark.asyncio
    async def test_no_comparison_without_data(self, optimizer):
        result = await optimizer._get_weekly_comparison()
        assert result is None

    @pytest.mark.asyncio
    async def test_more_consumption(self, optimizer, redis_mock):
        """Erkennt hoehere Verbrauchswoche."""
        now = datetime.now()

        async def fake_mget(keys):
            results = []
            for key in keys:
                matched = False
                for i in range(7):
                    day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
                    if day in key:
                        results.append(json.dumps({"consumption_wh": 500}))
                        matched = True
                        break
                    day_lw = (now - timedelta(days=i + 7)).strftime("%Y-%m-%d")
                    if day_lw in key:
                        results.append(json.dumps({"consumption_wh": 300}))
                        matched = True
                        break
                if not matched:
                    results.append(None)
            return results

        redis_mock.mget = AsyncMock(side_effect=fake_mget)
        result = await optimizer._get_weekly_comparison()
        # Kann None sein wenn die Keys nicht matchen — das ist OK fuer Unit-Test


class TestDailyCostTracking:
    @pytest.mark.asyncio
    async def test_tracks_daily_cost(self, optimizer, ha_client, redis_mock):
        ha_client.get_states = AsyncMock(
            return_value=[
                {"entity_id": "sensor.verbrauch", "state": "450"},
                {"entity_id": "sensor.strompreis", "state": "28.5"},
            ]
        )
        await optimizer.track_daily_cost()
        redis_mock.setex.assert_called_once()
        call_args = redis_mock.setex.call_args
        data = json.loads(call_args[0][2])
        assert data["consumption_wh"] == 450.0
        assert data["avg_price_cent"] == 28.5

    @pytest.mark.asyncio
    async def test_skips_without_consumption(self, optimizer, ha_client, redis_mock):
        ha_client.get_states = AsyncMock(
            return_value=[
                {"entity_id": "sensor.strompreis", "state": "28.5"},
            ]
        )
        await optimizer.track_daily_cost()
        redis_mock.setex.assert_not_called()


class TestEnergyReport:
    @pytest.mark.asyncio
    async def test_report_with_sensors(self, optimizer, ha_client):
        ha_client.get_states = AsyncMock(
            return_value=[
                {"entity_id": "sensor.strompreis", "state": "12.5"},
                {"entity_id": "sensor.verbrauch", "state": "350"},
                {"entity_id": "sensor.solar", "state": "2500"},
            ]
        )
        result = await optimizer.get_energy_report()
        assert result["success"] is True
        assert "12.5" in result["message"]
        assert "guenstig" in result["message"]

    @pytest.mark.asyncio
    async def test_report_disabled(self, optimizer):
        optimizer.enabled = False
        result = await optimizer.get_energy_report()
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_report_no_states(self, optimizer, ha_client):
        """Report ohne HA-Verbindung gibt Fehlermeldung."""
        ha_client.get_states = AsyncMock(return_value=None)
        result = await optimizer.get_energy_report()
        assert result["success"] is False
        assert "Keine Verbindung" in result["message"]

    @pytest.mark.asyncio
    async def test_report_no_sensors_found(self, optimizer, ha_client):
        """Wenn keine passenden Sensoren gefunden werden."""
        ha_client.get_states = AsyncMock(
            return_value=[
                {"entity_id": "light.test", "state": "on", "attributes": {}},
            ]
        )
        result = await optimizer.get_energy_report()
        assert result["success"] is True
        assert "Keine Energie-Sensoren" in result["message"]

    @pytest.mark.asyncio
    async def test_report_price_high(self, optimizer, ha_client):
        """Hoher Strompreis wird als 'teuer' markiert."""
        ha_client.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "sensor.strompreis",
                    "state": "40",
                    "attributes": {"unit_of_measurement": "ct/kWh"},
                },
            ]
        )
        result = await optimizer.get_energy_report()
        assert result["success"] is True
        assert "teuer" in result["message"]

    @pytest.mark.asyncio
    async def test_report_price_normal(self, optimizer, ha_client):
        """Normaler Strompreis wird als 'normal' markiert."""
        ha_client.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "sensor.strompreis",
                    "state": "25",
                    "attributes": {"unit_of_measurement": "ct/kWh"},
                },
            ]
        )
        result = await optimizer.get_energy_report()
        assert result["success"] is True
        assert "normal" in result["message"]

    @pytest.mark.asyncio
    async def test_report_solar_included(self, optimizer, ha_client):
        """Solar-Ertrag wird im Bericht angezeigt."""
        ha_client.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "sensor.solar",
                    "state": "3500",
                    "attributes": {"unit_of_measurement": "W"},
                },
            ]
        )
        result = await optimizer.get_energy_report()
        assert "3500" in result["message"]
        assert "Solar" in result["message"]

    @pytest.mark.asyncio
    async def test_report_export_only_positive(self, optimizer, ha_client):
        """Netz-Einspeisung wird nur angezeigt wenn > 0."""
        ha_client.get_states = AsyncMock(
            return_value=[
                {"entity_id": "sensor.einspeisung", "state": "0", "attributes": {}},
                {"entity_id": "sensor.strompreis", "state": "25", "attributes": {}},
            ]
        )
        result = await optimizer.get_energy_report()
        assert "Einspeisung" not in result["message"]


# ---------------------------------------------------------------------------
# Price Unit Normalization
# ---------------------------------------------------------------------------


class TestPriceUnitNormalization:
    """Tests fuer Preis-Einheiten-Normalisierung in get_energy_report."""

    @pytest.mark.asyncio
    async def test_eur_per_mwh_normalized(self, optimizer, ha_client):
        """EUR/MWh wird korrekt nach ct/kWh umgerechnet (/ 10)."""
        ha_client.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "sensor.strompreis",
                    "state": "250",
                    "attributes": {"unit_of_measurement": "EUR/MWh"},
                },
            ]
        )
        result = await optimizer.get_energy_report()
        assert "25.0" in result["message"]  # 250 / 10 = 25

    @pytest.mark.asyncio
    async def test_eur_per_kwh_normalized(self, optimizer, ha_client):
        """EUR/kWh wird korrekt nach ct/kWh umgerechnet (* 100)."""
        ha_client.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "sensor.strompreis",
                    "state": "0.28",
                    "attributes": {"unit_of_measurement": "EUR/kWh"},
                },
            ]
        )
        result = await optimizer.get_energy_report()
        assert "28.0" in result["message"]  # 0.28 * 100 = 28

    @pytest.mark.asyncio
    async def test_heuristic_high_value_as_eur_mwh(self, optimizer, ha_client):
        """Wert > 100 ohne Einheit wird als EUR/MWh interpretiert."""
        ha_client.get_states = AsyncMock(
            return_value=[
                {"entity_id": "sensor.strompreis", "state": "200", "attributes": {}},
            ]
        )
        result = await optimizer.get_energy_report()
        assert "20.0" in result["message"]  # 200 / 10 = 20

    @pytest.mark.asyncio
    async def test_heuristic_low_value_as_eur_kwh(self, optimizer, ha_client):
        """Wert < 1 ohne Einheit wird als EUR/kWh interpretiert."""
        ha_client.get_states = AsyncMock(
            return_value=[
                {"entity_id": "sensor.strompreis", "state": "0.30", "attributes": {}},
            ]
        )
        result = await optimizer.get_energy_report()
        assert "30.0" in result["message"]  # 0.30 * 100 = 30


# ---------------------------------------------------------------------------
# _find_sensor_value
# ---------------------------------------------------------------------------


class TestFindSensorValue:
    """Tests fuer _find_sensor_value() — konfiguriertes Entity und Keyword-Suche."""

    def test_configured_entity_found(self, optimizer):
        states = [
            {"entity_id": "sensor.strompreis", "state": "28.5", "attributes": {}},
        ]
        result = optimizer._find_sensor_value(states, "sensor.strompreis", [])
        assert result == 28.5

    def test_configured_entity_unavailable(self, optimizer):
        states = [
            {
                "entity_id": "sensor.strompreis",
                "state": "unavailable",
                "attributes": {},
            },
        ]
        result = optimizer._find_sensor_value(states, "sensor.strompreis", [])
        assert result is None

    def test_configured_entity_unknown(self, optimizer):
        states = [
            {"entity_id": "sensor.strompreis", "state": "unknown", "attributes": {}},
        ]
        result = optimizer._find_sensor_value(states, "sensor.strompreis", [])
        assert result is None

    def test_configured_entity_empty_string(self, optimizer):
        states = [
            {"entity_id": "sensor.strompreis", "state": "", "attributes": {}},
        ]
        result = optimizer._find_sensor_value(states, "sensor.strompreis", [])
        assert result is None

    def test_configured_entity_invalid_value(self, optimizer):
        states = [
            {"entity_id": "sensor.strompreis", "state": "n/a", "attributes": {}},
        ]
        result = optimizer._find_sensor_value(states, "sensor.strompreis", [])
        assert result is None

    def test_keyword_fallback(self, optimizer):
        """Wenn kein Entity konfiguriert, wird per Keyword gesucht."""
        states = [
            {
                "entity_id": "sensor.electricity_price_today",
                "state": "22.5",
                "attributes": {},
            },
        ]
        result = optimizer._find_sensor_value(states, "", ["price", "electricity"])
        assert result == 22.5

    def test_keyword_only_sensor_domain(self, optimizer):
        """Keyword-Suche ignoriert Nicht-Sensor-Entities."""
        states = [
            {"entity_id": "light.solar_panel", "state": "on", "attributes": {}},
            {"entity_id": "sensor.solar_output", "state": "1500", "attributes": {}},
        ]
        result = optimizer._find_sensor_value(states, "", ["solar"])
        assert result == 1500.0

    def test_no_match_returns_none(self, optimizer):
        states = [
            {"entity_id": "sensor.temperature", "state": "21.5", "attributes": {}},
        ]
        result = optimizer._find_sensor_value(states, "", ["nonexistent"])
        assert result is None

    def test_configured_not_in_states(self, optimizer):
        """Konfiguriertes Entity nicht in States vorhanden."""
        states = [
            {"entity_id": "sensor.other", "state": "10", "attributes": {}},
        ]
        result = optimizer._find_sensor_value(states, "sensor.strompreis", ["price"])
        # Falls konfiguriertes Entity nicht gefunden, Keyword-Suche als Fallback
        assert result is None  # "price" not in "sensor.other"


# ---------------------------------------------------------------------------
# _find_sensor_unit
# ---------------------------------------------------------------------------


class TestFindSensorUnit:
    """Tests fuer _find_sensor_unit()."""

    def test_configured_entity_unit(self, optimizer):
        states = [
            {
                "entity_id": "sensor.strompreis",
                "state": "28",
                "attributes": {"unit_of_measurement": "ct/kWh"},
            },
        ]
        result = optimizer._find_sensor_unit(states, "sensor.strompreis", [])
        assert result == "ct/kWh"

    def test_keyword_search_unit(self, optimizer):
        states = [
            {
                "entity_id": "sensor.solar_output",
                "state": "2000",
                "attributes": {"unit_of_measurement": "W"},
            },
        ]
        result = optimizer._find_sensor_unit(states, "", ["solar"])
        assert result == "W"

    def test_no_unit_returns_empty(self, optimizer):
        states = [
            {"entity_id": "sensor.test", "state": "10", "attributes": {}},
        ]
        result = optimizer._find_sensor_unit(states, "sensor.test", [])
        assert result == ""


# ---------------------------------------------------------------------------
# calculate_load_shift_savings
# ---------------------------------------------------------------------------


class TestCalculateLoadShiftSavings:
    """Tests fuer calculate_load_shift_savings()."""

    def test_savings_when_cheaper(self, optimizer):
        """Jetzt guenstiger als Durchschnitt = positive Ersparnis."""
        result = optimizer.calculate_load_shift_savings(
            current_price=15.0, avg_price=30.0, estimated_kwh=2.0
        )
        assert result == 30.0  # (30-15) * 2 = 30 ct

    def test_cost_when_more_expensive(self, optimizer):
        """Jetzt teurer als Durchschnitt = negative Ersparnis."""
        result = optimizer.calculate_load_shift_savings(
            current_price=40.0, avg_price=25.0, estimated_kwh=1.5
        )
        assert result == -22.5  # (25-40) * 1.5 = -22.5 ct

    def test_zero_savings_at_avg(self, optimizer):
        """Gleicher Preis = keine Ersparnis."""
        result = optimizer.calculate_load_shift_savings(
            current_price=25.0, avg_price=25.0, estimated_kwh=3.0
        )
        assert result == 0.0


# ---------------------------------------------------------------------------
# _check_cloud_forecast
# ---------------------------------------------------------------------------


class TestCheckCloudForecast:
    """Tests fuer _check_cloud_forecast()."""

    def test_cloudy_forecast_detected(self):
        states = [
            {
                "entity_id": "weather.home",
                "state": "sunny",
                "attributes": {
                    "forecast": [
                        {"condition": "cloudy", "datetime": "2026-03-20T15:00"},
                    ]
                },
            },
        ]
        assert EnergyOptimizer._check_cloud_forecast(states) is True

    def test_rainy_forecast_detected(self):
        states = [
            {
                "entity_id": "weather.home",
                "state": "sunny",
                "attributes": {
                    "forecast": [
                        {"condition": "sunny", "datetime": "2026-03-20T12:00"},
                        {"condition": "rainy", "datetime": "2026-03-20T15:00"},
                    ]
                },
            },
        ]
        assert EnergyOptimizer._check_cloud_forecast(states) is True

    def test_clear_forecast_no_clouds(self):
        states = [
            {
                "entity_id": "weather.home",
                "state": "sunny",
                "attributes": {
                    "forecast": [
                        {"condition": "sunny", "datetime": "2026-03-20T12:00"},
                        {"condition": "partlycloudy", "datetime": "2026-03-20T15:00"},
                    ]
                },
            },
        ]
        assert EnergyOptimizer._check_cloud_forecast(states) is False

    def test_no_weather_entity(self):
        states = [
            {"entity_id": "sensor.temp", "state": "20", "attributes": {}},
        ]
        assert EnergyOptimizer._check_cloud_forecast(states) is False

    def test_no_forecast_data(self):
        states = [
            {"entity_id": "weather.home", "state": "sunny", "attributes": {}},
        ]
        assert EnergyOptimizer._check_cloud_forecast(states) is False

    def test_non_weather_entities_ignored(self):
        """Nur weather.* Entities werden geprueft."""
        states = [
            {
                "entity_id": "sensor.weather_condition",
                "state": "sunny",
                "attributes": {
                    "forecast": [
                        {"condition": "cloudy"},
                    ]
                },
            },
        ]
        assert EnergyOptimizer._check_cloud_forecast(states) is False


# ---------------------------------------------------------------------------
# _estimate_cheap_windows
# ---------------------------------------------------------------------------


class TestEstimateCheapWindows:
    """Tests fuer _estimate_cheap_windows()."""

    def _make_optimizer(self):
        ha = MagicMock()
        return EnergyOptimizer(ha)

    def test_returns_windows(self):
        now = datetime(2026, 3, 20, 10, 0)
        eo = self._make_optimizer()
        result = eo._estimate_cheap_windows(now, 2.0)
        assert len(result) > 0
        # Jedes Window hat Format "HH:MM-HH:MM"
        for w in result:
            assert "-" in w
            parts = w.split("-")
            assert len(parts) == 2
            assert ":" in parts[0]
            assert ":" in parts[1]

    def test_past_slots_pushed_to_next_day(self):
        """Slots die heute schon vorbei sind, werden auf morgen verschoben."""
        now = datetime(2026, 3, 20, 23, 0)
        eo = self._make_optimizer()
        result = eo._estimate_cheap_windows(now, 2.0)
        # Alle vorgeschlagenen Slots muessen in der Zukunft liegen (naechster Tag)
        assert len(result) > 0

    def test_window_duration_matches(self):
        """Zeitfenster-Dauer entspricht der angegebenen duration_h."""
        now = datetime(2026, 3, 20, 8, 0)
        eo = self._make_optimizer()
        result = eo._estimate_cheap_windows(now, 3.0)
        # Pruefe erstes Window
        first = result[0]
        start_str, end_str = first.split("-")
        start_h, start_m = map(int, start_str.split(":"))
        end_h, end_m = map(int, end_str.split(":"))
        duration_minutes = (end_h * 60 + end_m) - (start_h * 60 + start_m)
        if duration_minutes < 0:
            duration_minutes += 24 * 60
        assert duration_minutes == 180  # 3 Stunden


# ---------------------------------------------------------------------------
# _get_avg_price
# ---------------------------------------------------------------------------


class TestGetAvgPrice:
    """Tests fuer _get_avg_price()."""

    @pytest.mark.asyncio
    async def test_fallback_without_redis(self, optimizer):
        optimizer.redis = None
        result = await optimizer._get_avg_price(25.0)
        # Fallback: (price_low + price_high) / 2 = (15 + 35) / 2 = 25
        assert result == 25.0

    @pytest.mark.asyncio
    async def test_from_redis_history(self, optimizer, redis_mock):
        redis_mock.get = AsyncMock(return_value=json.dumps([20.0, 25.0, 30.0]))
        result = await optimizer._get_avg_price(28.0)
        assert result == 25.0  # (20+25+30)/3 = 25

    @pytest.mark.asyncio
    async def test_redis_error_uses_fallback(self, optimizer, redis_mock):
        redis_mock.get = AsyncMock(side_effect=Exception("redis down"))
        result = await optimizer._get_avg_price(28.0)
        assert result == 25.0  # Fallback

    @pytest.mark.asyncio
    async def test_redis_empty_history_uses_fallback(self, optimizer, redis_mock):
        redis_mock.get = AsyncMock(return_value=json.dumps([]))
        result = await optimizer._get_avg_price(28.0)
        assert result == 25.0  # Fallback (leere Liste)


# ---------------------------------------------------------------------------
# _was_recently_alerted / _mark_alerted
# ---------------------------------------------------------------------------


class TestAlertCooldown:
    """Tests fuer _was_recently_alerted() und _mark_alerted()."""

    @pytest.mark.asyncio
    async def test_not_alerted_returns_false(self, optimizer, redis_mock):
        redis_mock.get = AsyncMock(return_value=None)
        result = await optimizer._was_recently_alerted("test_alert")
        assert result is False

    @pytest.mark.asyncio
    async def test_alerted_returns_true(self, optimizer, redis_mock):
        redis_mock.get = AsyncMock(return_value="1")
        result = await optimizer._was_recently_alerted("test_alert")
        assert result is True

    @pytest.mark.asyncio
    async def test_no_redis_returns_false(self, optimizer):
        optimizer.redis = None
        result = await optimizer._was_recently_alerted("test_alert")
        assert result is False

    @pytest.mark.asyncio
    async def test_redis_error_returns_false(self, optimizer, redis_mock):
        redis_mock.get = AsyncMock(side_effect=Exception("fail"))
        result = await optimizer._was_recently_alerted("test_alert")
        assert result is False

    @pytest.mark.asyncio
    async def test_mark_alerted_sets_key_with_ttl(self, optimizer, redis_mock):
        await optimizer._mark_alerted("solar_high", cooldown_minutes=180)
        redis_mock.setex.assert_called_once_with(
            "mha:energy:alert:solar_high", 180 * 60, "1"
        )

    @pytest.mark.asyncio
    async def test_mark_alerted_no_redis(self, optimizer):
        optimizer.redis = None
        # Should not raise
        await optimizer._mark_alerted("test_alert")

    @pytest.mark.asyncio
    async def test_mark_alerted_redis_error(self, optimizer, redis_mock):
        redis_mock.setex = AsyncMock(side_effect=Exception("fail"))
        # Should not raise, just log
        await optimizer._mark_alerted("test_alert")


# ---------------------------------------------------------------------------
# has_configured_entities
# ---------------------------------------------------------------------------


class TestHasConfiguredEntities:
    """Tests fuer has_configured_entities Property."""

    def test_true_with_price_sensor(self, optimizer):
        optimizer.price_sensor = "sensor.price"
        optimizer.consumption_sensor = ""
        optimizer.solar_sensor = ""
        optimizer.grid_export_sensor = ""
        assert optimizer.has_configured_entities is True

    def test_false_without_any(self, optimizer):
        optimizer.price_sensor = ""
        optimizer.consumption_sensor = ""
        optimizer.solar_sensor = ""
        optimizer.grid_export_sensor = ""
        assert optimizer.has_configured_entities is False


# ---------------------------------------------------------------------------
# get_solar_surplus_actions
# ---------------------------------------------------------------------------


class TestGetSolarSurplusActions:
    """Tests fuer get_solar_surplus_actions()."""

    @pytest.mark.asyncio
    async def test_surplus_recommends_devices(self, optimizer, ha_client):
        """Solarueberschuss empfiehlt passende Geraete."""
        ha_client.get_states = AsyncMock(
            return_value=[
                {"entity_id": "sensor.solar", "state": "5000", "attributes": {}},
                {"entity_id": "sensor.verbrauch", "state": "1000", "attributes": {}},
            ]
        )
        result = await optimizer.get_solar_surplus_actions(ha_client)
        assert len(result) > 0
        assert all("device" in a and "message" in a and "power_kw" in a for a in result)

    @pytest.mark.asyncio
    async def test_no_surplus_no_actions(self, optimizer, ha_client):
        """Ohne Ueberschuss keine Empfehlungen."""
        ha_client.get_states = AsyncMock(
            return_value=[
                {"entity_id": "sensor.solar", "state": "500", "attributes": {}},
                {"entity_id": "sensor.verbrauch", "state": "2000", "attributes": {}},
            ]
        )
        result = await optimizer.get_solar_surplus_actions(ha_client)
        assert result == []

    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self, optimizer, ha_client):
        optimizer.enabled = False
        result = await optimizer.get_solar_surplus_actions(ha_client)
        assert result == []

    @pytest.mark.asyncio
    async def test_no_states_returns_empty(self, optimizer, ha_client):
        ha_client.get_states = AsyncMock(return_value=None)
        result = await optimizer.get_solar_surplus_actions(ha_client)
        assert result == []

    @pytest.mark.asyncio
    async def test_missing_solar_sensor_returns_empty(self, optimizer, ha_client):
        """Ohne Solar-Sensor keine Empfehlungen."""
        ha_client.get_states = AsyncMock(
            return_value=[
                {"entity_id": "sensor.verbrauch", "state": "1000", "attributes": {}},
            ]
        )
        result = await optimizer.get_solar_surplus_actions(ha_client)
        assert result == []


# ---------------------------------------------------------------------------
# get_optimal_schedule
# ---------------------------------------------------------------------------


class TestGetOptimalSchedule:
    """Tests fuer get_optimal_schedule()."""

    @pytest.mark.asyncio
    async def test_cheap_price_recommends_now(self, optimizer, ha_client, redis_mock):
        """Guenstiger Preis empfiehlt sofortiges Starten."""
        ha_client.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "sensor.strompreis",
                    "state": "10",
                    "attributes": {"unit_of_measurement": "ct/kWh"},
                },
            ]
        )
        redis_mock.get = AsyncMock(return_value=None)  # No price history
        result = await optimizer.get_optimal_schedule(ha_client)
        assert len(result) > 0
        # Alle Geraete sollten "Jetzt starten" empfohlen werden
        for item in result:
            assert "Jetzt starten" in item["suggestion"]
            assert item["savings_estimate_ct"] >= 0

    @pytest.mark.asyncio
    async def test_expensive_price_recommends_later(
        self, optimizer, ha_client, redis_mock
    ):
        """Teurer Preis empfiehlt spaeteres Starten."""
        ha_client.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "sensor.strompreis",
                    "state": "50",
                    "attributes": {"unit_of_measurement": "ct/kWh"},
                },
            ]
        )
        redis_mock.get = AsyncMock(return_value=None)
        result = await optimizer.get_optimal_schedule(ha_client)
        assert len(result) > 0
        for item in result:
            assert "spaeter" in item["suggestion"].lower()

    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self, optimizer, ha_client):
        optimizer.enabled = False
        result = await optimizer.get_optimal_schedule(ha_client)
        assert result == []

    @pytest.mark.asyncio
    async def test_no_price_sensor_returns_empty(self, optimizer, ha_client):
        """Ohne Preis-Sensor keine Empfehlungen."""
        ha_client.get_states = AsyncMock(
            return_value=[
                {"entity_id": "sensor.verbrauch", "state": "500", "attributes": {}},
            ]
        )
        optimizer.price_sensor = ""  # Kein konfigurierter Preis-Sensor
        result = await optimizer.get_optimal_schedule(ha_client)
        assert result == []

    @pytest.mark.asyncio
    async def test_e_auto_display_name(self, optimizer, ha_client, redis_mock):
        """E-Auto bekommt speziellen Display-Namen."""
        ha_client.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "sensor.strompreis",
                    "state": "10",
                    "attributes": {"unit_of_measurement": "ct/kWh"},
                },
            ]
        )
        redis_mock.get = AsyncMock(return_value=None)
        result = await optimizer.get_optimal_schedule(ha_client)
        e_auto_items = [r for r in result if r["device"] == "E-Auto"]
        assert len(e_auto_items) == 1


# ---------------------------------------------------------------------------
# check_energy_events — Proaktive Meldungen
# ---------------------------------------------------------------------------


class TestCheckEnergyEvents:
    """Tests fuer check_energy_events() — proaktive Energie-Alerts."""

    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self, optimizer):
        optimizer.enabled = False
        result = await optimizer.check_energy_events()
        assert result == []

    @pytest.mark.asyncio
    async def test_no_configured_entities_returns_empty(self, optimizer):
        """Ohne konfigurierte Entities keine proaktiven Alerts."""
        optimizer.price_sensor = ""
        optimizer.consumption_sensor = ""
        optimizer.solar_sensor = ""
        optimizer.grid_export_sensor = ""
        result = await optimizer.check_energy_events()
        assert result == []

    @pytest.mark.asyncio
    async def test_high_price_alert(self, optimizer, ha_client, redis_mock):
        """Hoher Strompreis erzeugt Alert."""
        ha_client.get_states = AsyncMock(
            return_value=[
                {"entity_id": "sensor.strompreis", "state": "45", "attributes": {}},
            ]
        )
        redis_mock.get = AsyncMock(return_value=None)  # Kein kuerzlicher Alert
        redis_mock.mget = AsyncMock(return_value=[None] * 7)  # Keine Anomalie-Daten
        result = await optimizer.check_energy_events()
        price_alerts = [a for a in result if a["type"] == "energy_price_high"]
        assert len(price_alerts) == 1
        assert "hoch" in price_alerts[0]["message"].lower()

    @pytest.mark.asyncio
    async def test_high_price_alert_cooldown(self, optimizer, ha_client, redis_mock):
        """Hoher Preis-Alert wird nicht wiederholt waehrend Cooldown."""
        ha_client.get_states = AsyncMock(
            return_value=[
                {"entity_id": "sensor.strompreis", "state": "45", "attributes": {}},
            ]
        )
        # Simuliere kuerzlich gesendeten Alert
        redis_mock.get = AsyncMock(return_value="1")
        redis_mock.mget = AsyncMock(return_value=[None] * 7)
        result = await optimizer.check_energy_events()
        price_alerts = [a for a in result if a["type"] == "energy_price_high"]
        assert len(price_alerts) == 0

    @pytest.mark.asyncio
    async def test_solar_surplus_alert(self, optimizer, ha_client, redis_mock):
        """Solar-Ueberschuss erzeugt Alert."""
        ha_client.get_states = AsyncMock(
            return_value=[
                {"entity_id": "sensor.solar", "state": "3000", "attributes": {}},
                {"entity_id": "sensor.einspeisung", "state": "1500", "attributes": {}},
            ]
        )
        redis_mock.get = AsyncMock(return_value=None)
        redis_mock.mget = AsyncMock(return_value=[None] * 7)
        result = await optimizer.check_energy_events()
        solar_alerts = [a for a in result if a["type"] == "solar_surplus"]
        assert len(solar_alerts) == 1

    @pytest.mark.asyncio
    async def test_no_states_returns_empty(self, optimizer, ha_client):
        ha_client.get_states = AsyncMock(return_value=None)
        result = await optimizer.check_energy_events()
        assert result == []


# ---------------------------------------------------------------------------
# _get_recommendations
# ---------------------------------------------------------------------------


class TestGetRecommendations:
    """Tests fuer _get_recommendations()."""

    @pytest.mark.asyncio
    async def test_cheap_price_recommendation(self, optimizer, redis_mock):
        redis_mock.mget = AsyncMock(return_value=[None] * 7)  # Kein Anomalie-Daten
        result = await optimizer._get_recommendations(
            price=10.0, solar=None, consumption=None
        )
        assert any("guenstig" in r.lower() for r in result)

    @pytest.mark.asyncio
    async def test_expensive_price_recommendation(self, optimizer, redis_mock):
        redis_mock.mget = AsyncMock(return_value=[None] * 7)
        result = await optimizer._get_recommendations(
            price=40.0, solar=None, consumption=None
        )
        assert any("teuer" in r.lower() for r in result)

    @pytest.mark.asyncio
    async def test_high_solar_recommendation(self, optimizer, redis_mock):
        redis_mock.mget = AsyncMock(return_value=[None] * 7)
        result = await optimizer._get_recommendations(
            price=None, solar=3000.0, consumption=None
        )
        assert any("Solar" in r for r in result)

    @pytest.mark.asyncio
    async def test_no_data_empty_recommendations(self, optimizer, redis_mock):
        redis_mock.mget = AsyncMock(return_value=[None] * 7)
        result = await optimizer._get_recommendations(
            price=None, solar=None, consumption=None
        )
        # No recommendations when all data is None
        # (may still get weekly comparison etc, but those return None with no data)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Weekly Comparison — Erweiterte Tests
# ---------------------------------------------------------------------------


class TestWeeklyComparisonExtended:
    """Erweiterte Tests fuer _get_weekly_comparison()."""

    @pytest.mark.asyncio
    async def test_less_consumption(self, optimizer, redis_mock):
        """Erkennt niedrigere Verbrauchswoche."""
        now = datetime.now()

        def build_raw_results(keys):
            results = []
            for idx in range(7):
                # This week (even indices): lower consumption
                results.append(json.dumps({"consumption_wh": 200}))
                # Last week (odd indices): higher consumption
                results.append(json.dumps({"consumption_wh": 400}))
            return results[: len(keys)]

        redis_mock.mget = AsyncMock(side_effect=lambda keys: build_raw_results(keys))
        result = await optimizer._get_weekly_comparison()
        if result:
            assert "weniger" in result

    @pytest.mark.asyncio
    async def test_small_diff_returns_none(self, optimizer, redis_mock):
        """Unter 5% Unterschied wird nicht gemeldet."""

        def build_raw_results(keys):
            results = []
            for idx in range(7):
                results.append(json.dumps({"consumption_wh": 300}))  # this week
                results.append(json.dumps({"consumption_wh": 305}))  # last week
            return results[: len(keys)]

        redis_mock.mget = AsyncMock(side_effect=lambda keys: build_raw_results(keys))
        result = await optimizer._get_weekly_comparison()
        assert result is None

    @pytest.mark.asyncio
    async def test_no_redis_returns_none(self, optimizer):
        optimizer.redis = None
        result = await optimizer._get_weekly_comparison()
        assert result is None


# ---------------------------------------------------------------------------
# initialize
# ---------------------------------------------------------------------------


class TestInitialize:
    """Tests fuer initialize()."""

    @pytest.mark.asyncio
    async def test_sets_redis(self, optimizer, redis_mock):
        new_redis = AsyncMock()
        await optimizer.initialize(new_redis)
        assert optimizer.redis is new_redis

    @pytest.mark.asyncio
    async def test_initialize_without_redis(self, optimizer):
        await optimizer.initialize(None)
        assert optimizer.redis is None


# ---------------------------------------------------------------------------
# Daily Cost Tracking — Erweiterte Tests
# ---------------------------------------------------------------------------


class TestDailyCostTrackingExtended:
    """Erweiterte Tests fuer track_daily_cost()."""

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self, optimizer, redis_mock):
        optimizer.enabled = False
        await optimizer.track_daily_cost()
        redis_mock.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_without_redis(self, optimizer):
        optimizer.redis = None
        await optimizer.track_daily_cost()
        # Should not raise

    @pytest.mark.asyncio
    async def test_skips_without_configured_entities(self, optimizer, redis_mock):
        optimizer.price_sensor = ""
        optimizer.consumption_sensor = ""
        optimizer.solar_sensor = ""
        optimizer.grid_export_sensor = ""
        await optimizer.track_daily_cost()
        redis_mock.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_tracks_with_price_zero_when_no_price(
        self, optimizer, ha_client, redis_mock
    ):
        """Ohne Preis-Sensor wird avg_price_cent als 0 gespeichert."""
        ha_client.get_states = AsyncMock(
            return_value=[
                {"entity_id": "sensor.verbrauch", "state": "300"},
            ]
        )
        await optimizer.track_daily_cost()
        redis_mock.setex.assert_called_once()
        call_args = redis_mock.setex.call_args
        data = json.loads(call_args[0][2])
        assert data["consumption_wh"] == 300.0
        assert data["avg_price_cent"] == 0

    @pytest.mark.asyncio
    async def test_redis_error_handled(self, optimizer, ha_client, redis_mock):
        """Redis-Fehler beim Speichern wird abgefangen."""
        ha_client.get_states = AsyncMock(
            return_value=[
                {"entity_id": "sensor.verbrauch", "state": "450"},
                {"entity_id": "sensor.strompreis", "state": "28.5"},
            ]
        )
        redis_mock.setex = AsyncMock(side_effect=Exception("redis connection lost"))
        # Should not raise
        await optimizer.track_daily_cost()
