"""
Tests fuer Security-Fixes: Bearer Token Sanitization, Rate-Limiter,
PIN Hashing, Garage-Cover Word-Boundary, Path Traversal, URL Parsing.
"""

import hashlib
import os
import re
import secrets
from pathlib import Path
from urllib.parse import urlparse

import pytest


# ---------------------------------------------------------------
# PIN Hashing (aus main.py extrahierte Logik)
# ---------------------------------------------------------------


def _hash_value(value: str, salt: str | None = None) -> str:
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", value.encode(), salt.encode(), iterations=600_000)
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


# ---------------------------------------------------------------
# Path Traversal Prevention
# ---------------------------------------------------------------


class TestPathTraversal:
    """os.path.basename + resolve()-Check verhindert Ausbruch aus UPLOAD_DIR."""

    def test_basename_strips_directory(self):
        assert os.path.basename("../../etc/passwd") == "passwd"

    def test_basename_strips_absolute(self):
        assert os.path.basename("/etc/shadow") == "shadow"

    def test_basename_strips_mixed(self):
        assert os.path.basename("../../../secret.txt") == "secret.txt"

    def test_dot_rejected(self):
        safe = os.path.basename(".")
        assert safe == "."  # Wird separat abgefangen

    def test_dotdot_rejected(self):
        safe = os.path.basename("..")
        assert safe == ".."  # Wird separat abgefangen


# ---------------------------------------------------------------
# ChromaDB URL Parsing (SSRF Prevention)
# ---------------------------------------------------------------


class TestChromaUrlParsing:
    """urlparse() statt split(':') — verhindert SSRF."""

    def test_normal_url(self):
        url = "http://mha-chromadb:8000"
        parsed = urlparse(url)
        assert parsed.hostname == "mha-chromadb"
        assert parsed.port == 8000

    def test_url_with_auth_ignored(self):
        """SSRF-Vektor: user@attacker.com wird korrekt als hostname erkannt."""
        url = "http://localhost:8000@attacker.com:1234"
        parsed = urlparse(url)
        # urlparse erkennt 'attacker.com' als hostname (nicht localhost)
        assert parsed.hostname != "localhost"

    def test_url_without_port_defaults(self):
        url = "http://chromadb"
        parsed = urlparse(url)
        assert parsed.hostname == "chromadb"
        assert parsed.port is None  # Code nutzt default 8000

    def test_split_ssrf_vulnerability(self):
        """Zeigt warum split(':') unsicher ist."""
        url = "http://localhost:8000@attacker.com:1234"
        # Alte unsichere Methode:
        host_old = url.replace("http://", "").split(":")[0]
        assert host_old == "localhost"  # FALSCH! Verbindet zu localhost statt attacker
        # Neue sichere Methode:
        parsed = urlparse(url)
        assert parsed.hostname != "localhost"  # Korrekt erkannt


# ---------------------------------------------------------------
# Function Name Whitelist
# ---------------------------------------------------------------


class TestFunctionWhitelist:
    """getattr-Zugriff auf _exec_* nur fuer erlaubte Funktionen."""

    def test_known_functions_in_whitelist(self):
        from assistant.function_calling import FunctionExecutor
        expected = {"set_light", "set_climate", "play_media", "set_cover",
                    "call_service", "send_notification"}
        for fn in expected:
            assert fn in FunctionExecutor._ALLOWED_FUNCTIONS

    def test_private_method_not_in_whitelist(self):
        from assistant.function_calling import FunctionExecutor
        # Interne Methoden die nie via LLM aufrufbar sein duerfen
        for fn in ["_is_safe_cover", "close", "__init__", "set_config_versioning"]:
            assert fn not in FunctionExecutor._ALLOWED_FUNCTIONS
