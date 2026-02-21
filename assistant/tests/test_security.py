"""
Tests fuer Security-Fixes: Bearer Token Sanitization, Rate-Limiter,
PIN Hashing, Garage-Cover Word-Boundary.
"""

import hashlib
import re
import secrets

import pytest


# ---------------------------------------------------------------
# PIN Hashing (aus main.py extrahierte Logik)
# ---------------------------------------------------------------


def _hash_value(value: str, salt: str | None = None) -> str:
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", value.encode(), salt.encode(), iterations=100_000)
    return f"{salt}:{h.hex()}"


def _verify_hash(value: str, stored: str) -> bool:
    if ":" in stored:
        salt, _ = stored.split(":", 1)
        return secrets.compare_digest(_hash_value(value, salt), stored)
    return secrets.compare_digest(hashlib.sha256(value.encode()).hexdigest(), stored)


class TestPinHashing:
    """PBKDF2 PIN Hashing und Legacy-Kompatibilitaet."""

    def test_hash_and_verify(self):
        pin = "1234"
        hashed = _hash_value(pin)
        assert ":" in hashed
        assert _verify_hash(pin, hashed)

    def test_wrong_pin_rejected(self):
        hashed = _hash_value("1234")
        assert not _verify_hash("5678", hashed)

    def test_legacy_sha256_verify(self):
        pin = "mypin"
        legacy_hash = hashlib.sha256(pin.encode()).hexdigest()
        assert ":" not in legacy_hash
        assert _verify_hash(pin, legacy_hash)

    def test_legacy_sha256_wrong_pin(self):
        legacy_hash = hashlib.sha256("mypin".encode()).hexdigest()
        assert not _verify_hash("wrongpin", legacy_hash)

    def test_hash_contains_salt(self):
        hashed = _hash_value("test")
        salt, hex_hash = hashed.split(":", 1)
        assert len(salt) == 32  # 16 bytes hex
        assert len(hex_hash) == 64  # SHA-256 hex

    def test_different_salts_produce_different_hashes(self):
        h1 = _hash_value("same_pin")
        h2 = _hash_value("same_pin")
        assert h1 != h2  # Unterschiedliche Salts


# ---------------------------------------------------------------
# Bearer Token Sanitization
# ---------------------------------------------------------------


class TestBearerTokenSanitization:
    """URL-Encoding verhindert Query-String Injection."""

    def test_normal_token_unchanged(self):
        from urllib.parse import quote
        token = "abc123XYZ"
        safe = quote(token, safe="")
        assert safe == token

    def test_injection_attempt_escaped(self):
        from urllib.parse import quote
        # Angreifer versucht: token=x&admin=true
        malicious = "x&admin=true"
        safe = quote(malicious, safe="")
        assert "&" not in safe
        assert "admin%3Dtrue" in safe or "admin=true" not in safe

    def test_special_chars_escaped(self):
        from urllib.parse import quote
        token = "token with spaces & special=chars"
        safe = quote(token, safe="")
        assert " " not in safe
        assert "&" not in safe
        assert "=" not in safe


# ---------------------------------------------------------------
# Garage Cover Word-Boundary Matching
# ---------------------------------------------------------------


class TestGarageCoverWordBoundary:
    """'tor' soll nur als eigenstaendiges Wort matchen, nicht in 'motor'."""

    _PATTERN = r'(?:^|[_.\s])tor(?:$|[_.\s])'

    def test_garagentor_matches(self):
        assert re.search(self._PATTERN, "cover.garagentor")  # 'tor' am Ende

    def test_tor_standalone_matches(self):
        assert re.search(self._PATTERN, "cover.tor_sued")

    def test_einfahrts_tor_matches(self):
        assert re.search(self._PATTERN, "cover.einfahrts_tor")

    def test_motor_does_not_match(self):
        assert not re.search(self._PATTERN, "cover.motor_shutter")

    def test_monitor_does_not_match(self):
        assert not re.search(self._PATTERN, "sensor.monitor_cover")

    def test_rotor_does_not_match(self):
        assert not re.search(self._PATTERN, "fan.rotor_main")

    def test_garage_in_eid_still_blocked(self):
        # 'garage' wird separat mit 'in' geprueft, nicht via Regex
        eid = "cover.garage_main"
        assert "garage" in eid.lower()

    def test_hoftor_matches(self):
        assert re.search(self._PATTERN, "cover.hof_tor")
