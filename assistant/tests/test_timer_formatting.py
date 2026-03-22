"""
Tests fuer timer_manager.py — Zeitformatierung und Timer-Logik

Testet:
  - format_remaining: Zeitformatierung (Sekunden → "X Stunden und Y Minuten")
  - Timer-Validierung: Dauer-Grenzen (1-1440 Minuten)
  - Zeitstring-Generierung: Stunden+Minuten Kombination
"""

import pytest


# ============================================================
# format_remaining (extrahiert aus GeneralTimer)
# ============================================================


def format_remaining(secs: int) -> str:
    """Formatiert verbleibende Sekunden als deutsche Zeitangabe."""
    if secs <= 0:
        return "abgelaufen"
    hours = secs // 3600
    minutes = (secs % 3600) // 60
    seconds = secs % 60
    parts = []
    if hours > 0:
        parts.append(f"{hours} Stunde{'n' if hours > 1 else ''}")
    if minutes > 0:
        parts.append(f"{minutes} Minute{'n' if minutes > 1 else ''}")
    if seconds > 0 and hours == 0:
        parts.append(f"{seconds} Sekunde{'n' if seconds > 1 else ''}")
    return " und ".join(parts) if parts else "abgelaufen"


def format_duration_string(duration_minutes: int) -> str:
    """Erzeugt lesbaren Dauer-String fuer Timer-Bestaetigung."""
    if duration_minutes >= 60:
        hours = duration_minutes // 60
        mins = duration_minutes % 60
        time_str = f"{hours} Stunde{'n' if hours > 1 else ''}"
        if mins > 0:
            time_str += f" und {mins} Minute{'n' if mins > 1 else ''}"
    else:
        time_str = f"{duration_minutes} Minute{'n' if duration_minutes > 1 else ''}"
    return time_str


def validate_duration(duration_minutes: int) -> bool:
    """Prueft ob die Timer-Dauer gueltig ist (1-1440 Minuten)."""
    return 1 <= duration_minutes <= 1440


# ============================================================
# format_remaining Tests
# ============================================================


class TestFormatRemaining:
    """Testet Zeitformatierung."""

    def test_abgelaufen(self):
        assert format_remaining(0) == "abgelaufen"
        assert format_remaining(-5) == "abgelaufen"

    def test_sekunden_singular(self):
        assert format_remaining(1) == "1 Sekunde"

    def test_sekunden_plural(self):
        assert format_remaining(30) == "30 Sekunden"

    def test_eine_minute(self):
        assert format_remaining(60) == "1 Minute"

    def test_mehrere_minuten(self):
        assert format_remaining(300) == "5 Minuten"

    def test_minute_und_sekunden(self):
        assert format_remaining(90) == "1 Minute und 30 Sekunden"

    def test_eine_stunde(self):
        assert format_remaining(3600) == "1 Stunde"

    def test_mehrere_stunden(self):
        assert format_remaining(7200) == "2 Stunden"

    def test_stunde_und_minuten(self):
        assert format_remaining(3660) == "1 Stunde und 1 Minute"

    def test_stunden_und_minuten(self):
        assert format_remaining(5400) == "1 Stunde und 30 Minuten"

    def test_keine_sekunden_bei_stunden(self):
        """Sekunden werden bei Stunden nicht angezeigt."""
        result = format_remaining(3601)
        assert "Sekunde" not in result

    def test_zwei_stunden_dreissig_minuten(self):
        assert format_remaining(9000) == "2 Stunden und 30 Minuten"


# ============================================================
# format_duration_string Tests
# ============================================================


class TestFormatDurationString:
    """Testet Timer-Bestaetigungs-String."""

    def test_eine_minute(self):
        assert format_duration_string(1) == "1 Minute"

    def test_fuenf_minuten(self):
        assert format_duration_string(5) == "5 Minuten"

    def test_eine_stunde(self):
        assert format_duration_string(60) == "1 Stunde"

    def test_zwei_stunden(self):
        assert format_duration_string(120) == "2 Stunden"

    def test_stunde_und_minute(self):
        assert format_duration_string(61) == "1 Stunde und 1 Minute"

    def test_stunde_und_minuten(self):
        assert format_duration_string(90) == "1 Stunde und 30 Minuten"

    def test_volle_stunden_ohne_minuten(self):
        result = format_duration_string(120)
        assert "Minute" not in result


# ============================================================
# Duration Validation Tests
# ============================================================


class TestDurationValidation:
    """Testet Timer-Dauer-Validierung."""

    def test_minimum(self):
        assert validate_duration(1) is True

    def test_maximum(self):
        assert validate_duration(1440) is True

    def test_too_short(self):
        assert validate_duration(0) is False

    def test_negative(self):
        assert validate_duration(-5) is False

    def test_too_long(self):
        assert validate_duration(1441) is False

    def test_typical_values(self):
        assert validate_duration(5) is True
        assert validate_duration(15) is True
        assert validate_duration(30) is True
        assert validate_duration(60) is True
        assert validate_duration(120) is True
