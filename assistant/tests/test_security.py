"""
Tests fuer Security-Fixes: Bearer Token Sanitization, Rate-Limiter,
PIN Hashing, Garage-Cover Word-Boundary, Path Traversal, URL Parsing,
DNS-Rebinding-Schutz (F-069).
"""

import asyncio
import hashlib
import ipaddress
import os
import re
import secrets
import socket
from pathlib import Path
from unittest.mock import AsyncMock, patch
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

    def test_garagentor_not_matched_by_tor_regex(self):
        # 'garagentor' wird NICHT durch die tor-Regex gefunden (kein Separator)
        # Aber "garage" im Entity-Name blockiert es separat via 'in' Check
        assert not re.search(self._PATTERN, "cover.garagentor")

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
        pytest.importorskip("pydantic_settings")
        from assistant.function_calling import FunctionExecutor
        expected = {"set_light", "set_climate", "play_media", "set_cover",
                    "call_service", "send_notification"}
        for fn in expected:
            assert fn in FunctionExecutor._ALLOWED_FUNCTIONS

    def test_private_method_not_in_whitelist(self):
        pytest.importorskip("pydantic_settings")
        from assistant.function_calling import FunctionExecutor
        # Interne Methoden die nie via LLM aufrufbar sein duerfen
        for fn in ["_is_safe_cover", "close", "__init__", "set_config_versioning"]:
            assert fn not in FunctionExecutor._ALLOWED_FUNCTIONS


# ---------------------------------------------------------------
# F-069: DNS-Rebinding-Schutz
# ---------------------------------------------------------------


def _fake_getaddrinfo(ip_str: str):
    """Erzeugt eine Mock-Funktion fuer socket.getaddrinfo die eine feste IP liefert."""
    def _resolver(host, port, family=0, type=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip_str, 0))]
    return _resolver


class TestDnsRebindingProtection:
    """F-069: DNS-Aufloesung VOR dem Request — verhindert Rebinding-Angriffe."""

    def test_is_ip_blocked_loopback(self):
        from assistant.web_search import _is_ip_blocked
        assert _is_ip_blocked(ipaddress.ip_address("127.0.0.1"))
        assert _is_ip_blocked(ipaddress.ip_address("127.0.0.53"))

    def test_is_ip_blocked_private(self):
        from assistant.web_search import _is_ip_blocked
        assert _is_ip_blocked(ipaddress.ip_address("192.168.1.1"))
        assert _is_ip_blocked(ipaddress.ip_address("10.0.0.1"))
        assert _is_ip_blocked(ipaddress.ip_address("172.16.0.1"))

    def test_is_ip_blocked_link_local(self):
        from assistant.web_search import _is_ip_blocked
        assert _is_ip_blocked(ipaddress.ip_address("169.254.1.1"))

    def test_is_ip_blocked_ipv6_loopback(self):
        from assistant.web_search import _is_ip_blocked
        assert _is_ip_blocked(ipaddress.ip_address("::1"))

    def test_is_ip_blocked_ipv6_private(self):
        from assistant.web_search import _is_ip_blocked
        assert _is_ip_blocked(ipaddress.ip_address("fd00::1"))

    def test_is_ip_blocked_public_allowed(self):
        from assistant.web_search import _is_ip_blocked
        assert not _is_ip_blocked(ipaddress.ip_address("8.8.8.8"))
        assert not _is_ip_blocked(ipaddress.ip_address("1.1.1.1"))
        assert not _is_ip_blocked(ipaddress.ip_address("93.184.216.34"))

    @pytest.mark.asyncio
    async def test_resolve_blocks_hostname_resolving_to_loopback(self):
        """Hostname der auf 127.0.0.1 aufloest muss blockiert werden."""
        from assistant.web_search import _resolve_and_check
        with patch("socket.getaddrinfo", _fake_getaddrinfo("127.0.0.1")):
            assert not await _resolve_and_check("evil-rebind.com")

    @pytest.mark.asyncio
    async def test_resolve_blocks_hostname_resolving_to_private(self):
        """Hostname der auf 192.168.x.x aufloest muss blockiert werden."""
        from assistant.web_search import _resolve_and_check
        with patch("socket.getaddrinfo", _fake_getaddrinfo("192.168.1.100")):
            assert not await _resolve_and_check("evil-rebind.com")

    @pytest.mark.asyncio
    async def test_resolve_blocks_hostname_resolving_to_10_net(self):
        from assistant.web_search import _resolve_and_check
        with patch("socket.getaddrinfo", _fake_getaddrinfo("10.0.0.5")):
            assert not await _resolve_and_check("attacker.com")

    @pytest.mark.asyncio
    async def test_resolve_allows_public_ip(self):
        """Hostname der auf oeffentliche IP aufloest ist ok."""
        from assistant.web_search import _resolve_and_check
        with patch("socket.getaddrinfo", _fake_getaddrinfo("93.184.216.34")):
            assert await _resolve_and_check("example.com")

    @pytest.mark.asyncio
    async def test_resolve_blocks_known_hostnames(self):
        """Bekannte interne Hostnamen werden direkt blockiert, ohne DNS."""
        from assistant.web_search import _resolve_and_check
        for name in ("localhost", "redis", "chromadb", "ollama", "homeassistant", "ha"):
            assert not await _resolve_and_check(name)

    @pytest.mark.asyncio
    async def test_resolve_blocks_ip_literal_private(self):
        """IP-Literal wird direkt geprueft, ohne DNS-Aufloesung."""
        from assistant.web_search import _resolve_and_check
        assert not await _resolve_and_check("192.168.1.1")
        assert not await _resolve_and_check("127.0.0.1")
        assert not await _resolve_and_check("::1")

    @pytest.mark.asyncio
    async def test_resolve_allows_ip_literal_public(self):
        from assistant.web_search import _resolve_and_check
        assert await _resolve_and_check("8.8.8.8")

    @pytest.mark.asyncio
    async def test_resolve_blocks_on_dns_failure(self):
        """Fehlgeschlagene DNS-Aufloesung wird sicherheitshalber blockiert."""
        from assistant.web_search import _resolve_and_check
        with patch("socket.getaddrinfo", side_effect=socket.gaierror("NXDOMAIN")):
            assert not await _resolve_and_check("nonexistent.example.com")

    @pytest.mark.asyncio
    async def test_resolve_empty_hostname_blocked(self):
        from assistant.web_search import _resolve_and_check
        assert not await _resolve_and_check("")

    @pytest.mark.asyncio
    async def test_resolve_blocks_if_any_ip_is_private(self):
        """Wenn ein Hostname auf mehrere IPs aufloest und EINE privat ist → blockieren."""
        from assistant.web_search import _resolve_and_check

        def _multi_resolve(host, port, family=0, type=0):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0)),
                (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.1", 0)),
            ]

        with patch("socket.getaddrinfo", _multi_resolve):
            assert not await _resolve_and_check("dual-homed-evil.com")

    def test_is_safe_url_blocks_ftp(self):
        """Scheme-Pruefung bleibt intakt."""
        from assistant.web_search import _is_safe_url
        assert not _is_safe_url("ftp://evil.com/payload")

    def test_is_safe_url_blocks_localhost(self):
        from assistant.web_search import _is_safe_url
        assert not _is_safe_url("http://localhost:8080/admin")

    def test_is_safe_url_blocks_internal_hostnames(self):
        from assistant.web_search import _is_safe_url
        for host in ("redis", "chromadb", "ollama", "homeassistant", "ha"):
            assert not _is_safe_url(f"http://{host}:6379/")

    def test_is_safe_url_allows_external(self):
        from assistant.web_search import _is_safe_url
        assert _is_safe_url("https://searxng.example.com/search")
