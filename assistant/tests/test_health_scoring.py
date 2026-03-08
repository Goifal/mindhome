"""
Tests fuer health_monitor.py — Scoring- und Threshold-Funktionen

Testet alle Schwellwert-Pruefungen und Scoring-Funktionen isoliert:
  - _score_co2: CO2-Scoring (ppm → 0-100)
  - _score_humidity: Feuchtigkeits-Scoring (% → 0-100)
  - _score_temperature: Temperatur-Scoring (°C → 0-100)
  - _check_co2: CO2-Alarm-Erkennung
  - _check_humidity: Feuchtigkeits-Alarm-Erkennung
  - _check_temperature: Temperatur-Alarm-Erkennung
  - _check_humidor: Humidor-spezifische Feuchtigkeitspruefung
"""

import pytest


# ============================================================
# Scoring-Funktionen (pure static methods, aus health_monitor.py)
# ============================================================

def score_co2(ppm: float) -> int:
    if ppm < 600:
        return 100
    elif ppm < 800:
        return 85
    elif ppm < 1000:
        return 65
    elif ppm < 1200:
        return 45
    elif ppm < 1500:
        return 25
    return 10


def score_humidity(percent: float) -> int:
    if 40 <= percent <= 60:
        return 100
    elif 30 <= percent < 40 or 60 < percent <= 70:
        return 70
    elif 20 <= percent < 30 or 70 < percent <= 80:
        return 40
    return 15


def score_temperature(temp: float) -> int:
    if 20 <= temp <= 23:
        return 100
    elif 18 <= temp < 20 or 23 < temp <= 25:
        return 75
    elif 16 <= temp < 18 or 25 < temp <= 27:
        return 50
    return 25


# ============================================================
# Threshold-Check-Funktionen (extrahiert)
# ============================================================

def check_co2(ppm: float, warn: int = 1000, critical: int = 1500) -> dict | None:
    if ppm >= critical:
        return {"type": "co2_critical", "urgency": "high", "value": ppm}
    elif ppm >= warn:
        return {"type": "co2_warn", "urgency": "medium", "value": ppm}
    return None


def check_humidity(percent: float, low: int = 30, high: int = 70) -> dict | None:
    if percent < low:
        return {"type": "humidity_low", "urgency": "medium", "value": percent}
    elif percent > high:
        return {"type": "humidity_high", "urgency": "medium", "value": percent}
    return None


def check_temperature(temp: float, low: int = 16, high: int = 27) -> dict | None:
    if temp < low:
        return {"type": "temp_low", "urgency": "low", "value": temp}
    elif temp > high:
        return {"type": "temp_high", "urgency": "low", "value": temp}
    return None


def check_humidor(percent: float, warn_below: int = 62, warn_above: int = 75, target: int = 69) -> dict | None:
    if percent < warn_below:
        return {"type": "humidor_low", "urgency": "medium", "value": percent}
    elif percent > warn_above:
        return {"type": "humidor_high", "urgency": "low", "value": percent}
    return None


# ============================================================
# CO2 Scoring Tests
# ============================================================

class TestCO2Scoring:
    """CO2-Score: ppm → 0-100."""

    @pytest.mark.parametrize("ppm,expected", [
        (400, 100),   # Frische Luft
        (599, 100),
        (600, 85),    # Grenzwert
        (700, 85),
        (800, 65),
        (900, 65),
        (1000, 45),
        (1100, 45),
        (1200, 25),
        (1400, 25),
        (1500, 10),   # Kritisch
        (2000, 10),
    ])
    def test_co2_score(self, ppm, expected):
        assert score_co2(ppm) == expected

    def test_co2_monotonic_decrease(self):
        """Score sinkt mit steigender ppm."""
        prev = 101
        for ppm in [400, 700, 900, 1100, 1300, 1600]:
            s = score_co2(ppm)
            assert s < prev, f"Score bei {ppm}ppm ({s}) sollte < vorheriger ({prev})"
            prev = s


# ============================================================
# Humidity Scoring Tests
# ============================================================

class TestHumidityScoring:
    """Feuchtigkeits-Score: % → 0-100."""

    @pytest.mark.parametrize("percent,expected", [
        (50, 100),    # Optimal
        (40, 100),
        (60, 100),
        (35, 70),     # Akzeptabel
        (65, 70),
        (25, 40),     # Marginal
        (75, 40),
        (15, 15),     # Schlecht
        (85, 15),
    ])
    def test_humidity_score(self, percent, expected):
        assert score_humidity(percent) == expected

    def test_optimal_range(self):
        """40-60% ist der optimale Bereich."""
        for p in range(40, 61):
            assert score_humidity(p) == 100


# ============================================================
# Temperature Scoring Tests
# ============================================================

class TestTemperatureScoring:
    """Temperatur-Score: °C → 0-100."""

    @pytest.mark.parametrize("temp,expected", [
        (21, 100),    # Optimal
        (20, 100),
        (23, 100),
        (19, 75),     # Akzeptabel
        (24, 75),
        (17, 50),     # Marginal
        (26, 50),
        (15, 25),     # Schlecht
        (28, 25),
    ])
    def test_temp_score(self, temp, expected):
        assert score_temperature(temp) == expected


# ============================================================
# CO2 Threshold Tests
# ============================================================

class TestCO2Check:
    """CO2-Schwellwert-Pruefung."""

    def test_normal_co2_no_alert(self):
        assert check_co2(800) is None

    def test_warn_threshold(self):
        result = check_co2(1000)
        assert result is not None
        assert result["type"] == "co2_warn"
        assert result["urgency"] == "medium"

    def test_critical_threshold(self):
        result = check_co2(1500)
        assert result is not None
        assert result["type"] == "co2_critical"
        assert result["urgency"] == "high"

    def test_just_below_warn(self):
        assert check_co2(999) is None

    def test_between_warn_and_critical(self):
        result = check_co2(1200)
        assert result["type"] == "co2_warn"

    def test_custom_thresholds(self):
        result = check_co2(800, warn=700, critical=1200)
        assert result["type"] == "co2_warn"


# ============================================================
# Humidity Threshold Tests
# ============================================================

class TestHumidityCheck:
    """Feuchtigkeits-Schwellwert-Pruefung."""

    def test_normal_humidity_no_alert(self):
        assert check_humidity(50) is None

    def test_too_dry(self):
        result = check_humidity(25)
        assert result["type"] == "humidity_low"

    def test_too_wet(self):
        result = check_humidity(80)
        assert result["type"] == "humidity_high"

    def test_boundary_low(self):
        assert check_humidity(30) is None  # 30 ist OK
        assert check_humidity(29) is not None

    def test_boundary_high(self):
        assert check_humidity(70) is None  # 70 ist OK
        assert check_humidity(71) is not None


# ============================================================
# Temperature Threshold Tests
# ============================================================

class TestTemperatureCheck:
    """Temperatur-Schwellwert-Pruefung."""

    def test_normal_temp_no_alert(self):
        assert check_temperature(22) is None

    def test_too_cold(self):
        result = check_temperature(14)
        assert result["type"] == "temp_low"
        assert result["urgency"] == "low"

    def test_too_hot(self):
        result = check_temperature(30)
        assert result["type"] == "temp_high"

    def test_boundary_low(self):
        assert check_temperature(16) is None
        assert check_temperature(15.9) is not None

    def test_boundary_high(self):
        assert check_temperature(27) is None
        assert check_temperature(27.1) is not None


# ============================================================
# Humidor Tests
# ============================================================

class TestHumidorCheck:
    """Humidor-spezifische Feuchtigkeitspruefung."""

    def test_normal_humidor(self):
        assert check_humidor(68) is None

    def test_humidor_too_dry(self):
        result = check_humidor(55)
        assert result["type"] == "humidor_low"
        assert result["urgency"] == "medium"

    def test_humidor_too_wet(self):
        result = check_humidor(80)
        assert result["type"] == "humidor_high"
        assert result["urgency"] == "low"

    def test_humidor_boundary(self):
        assert check_humidor(62) is None
        assert check_humidor(61) is not None
        assert check_humidor(75) is None
        assert check_humidor(76) is not None
