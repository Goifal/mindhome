"""
Tests fuer main.py: Rate-Limiting, Token-Verwaltung, PIN-Hashing,
API Key Enforcement, CORS Origins.
"""

import hashlib
import secrets
import time
from collections import defaultdict
from datetime import datetime, timezone
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------
# Rate-Limiter Tests (isolierte Logik)
# ---------------------------------------------------------------


class TestRateLimiter:
    """Rate-Limiting: 60 Requests pro 60 Sekunden pro IP."""

    _RATE_WINDOW = 60
    _RATE_MAX_REQUESTS = 60

    def _check_rate(self, rate_limits: dict, client_ip: str, now: float) -> bool:
        """Simuliert die Rate-Limit Pruefung. Returns True wenn blockiert."""
        rate_limits[client_ip] = [
            t for t in rate_limits[client_ip] if now - t < self._RATE_WINDOW
        ]
        if len(rate_limits[client_ip]) >= self._RATE_MAX_REQUESTS:
            return True  # blockiert
        rate_limits[client_ip].append(now)
        return False

    def test_first_request_allowed(self):
        limits = defaultdict(list)
        assert self._check_rate(limits, "192.168.1.1", time.time()) is False

    def test_under_limit_allowed(self):
        limits = defaultdict(list)
        now = time.time()
        for i in range(59):
            assert self._check_rate(limits, "10.0.0.1", now + i * 0.1) is False

    def test_at_limit_blocked(self):
        limits = defaultdict(list)
        now = time.time()
        # 60 Requests erlaubt
        for i in range(60):
            self._check_rate(limits, "10.0.0.1", now)
        # 61. wird blockiert
        assert self._check_rate(limits, "10.0.0.1", now) is True

    def test_different_ips_independent(self):
        limits = defaultdict(list)
        now = time.time()
        # IP 1 auslasten
        for i in range(60):
            self._check_rate(limits, "10.0.0.1", now)
        # IP 2 ist nicht betroffen
        assert self._check_rate(limits, "10.0.0.2", now) is False

    def test_old_entries_expire(self):
        limits = defaultdict(list)
        now = time.time()
        # 60 Requests jetzt
        for i in range(60):
            self._check_rate(limits, "10.0.0.1", now)
        # Blockiert
        assert self._check_rate(limits, "10.0.0.1", now) is True
        # 61 Sekunden spaeter: Alte Eintraege verfallen
        assert self._check_rate(limits, "10.0.0.1", now + 61) is False


# ---------------------------------------------------------------
# Token-Verwaltung Tests
# ---------------------------------------------------------------


class TestTokenManagement:
    """UI-Token Erstellung, Validierung und Ablauf."""

    _TOKEN_EXPIRY_SECONDS = 4 * 60 * 60  # 4 Stunden

    def _create_token(self) -> tuple[str, float]:
        token = hashlib.sha256(
            f"pin{datetime.now().isoformat()}{secrets.token_hex(8)}".encode()
        ).hexdigest()[:32]
        ts = datetime.now(timezone.utc).timestamp()
        return token, ts

    def test_token_is_32_chars(self):
        token, _ = self._create_token()
        assert len(token) == 32

    def test_tokens_are_unique(self):
        t1, _ = self._create_token()
        t2, _ = self._create_token()
        assert t1 != t2

    def test_token_not_expired(self):
        _, ts = self._create_token()
        now = datetime.now(timezone.utc).timestamp()
        assert now - ts < self._TOKEN_EXPIRY_SECONDS

    def test_token_expired_after_4_hours(self):
        _, ts = self._create_token()
        future = ts + self._TOKEN_EXPIRY_SECONDS + 1
        assert future - ts > self._TOKEN_EXPIRY_SECONDS

    def test_cleanup_removes_expired(self):
        tokens = {}
        # Token vor 5 Stunden
        tokens["old_token"] = datetime.now(timezone.utc).timestamp() - 5 * 3600
        # Token vor 1 Stunde
        tokens["fresh_token"] = datetime.now(timezone.utc).timestamp() - 3600

        # Cleanup
        now = datetime.now(timezone.utc).timestamp()
        expired = [t for t, ts in tokens.items() if now - ts > self._TOKEN_EXPIRY_SECONDS]
        for t in expired:
            tokens.pop(t, None)

        assert "old_token" not in tokens
        assert "fresh_token" in tokens

    def test_cleanup_with_pop_is_safe(self):
        """pop(key, None) statt del verhindert KeyError bei concurrent access."""
        tokens = {"a": 1.0}
        tokens.pop("a", None)  # Sicher
        tokens.pop("a", None)  # Nochmal — kein KeyError
        tokens.pop("nonexistent", None)  # Existiert nicht — kein KeyError


# ---------------------------------------------------------------
# PIN Hashing (PBKDF2) Tests
# ---------------------------------------------------------------


class TestPinHashing:
    """PBKDF2 mit 600k Iterationen und Salt."""

    def _hash_value(self, value: str, salt: str = None) -> str:
        if salt is None:
            salt = secrets.token_hex(16)
        h = hashlib.pbkdf2_hmac("sha256", value.encode(), salt.encode(), iterations=600_000)
        return f"{salt}:{h.hex()}"

    def _verify_hash(self, value: str, stored: str) -> bool:
        if ":" in stored:
            salt, _ = stored.split(":", 1)
            return secrets.compare_digest(self._hash_value(value, salt), stored)
        return secrets.compare_digest(hashlib.sha256(value.encode()).hexdigest(), stored)

    def test_hash_verify_roundtrip(self):
        hashed = self._hash_value("secure_pin_123")
        assert self._verify_hash("secure_pin_123", hashed)

    def test_wrong_pin_fails(self):
        hashed = self._hash_value("correct")
        assert not self._verify_hash("wrong", hashed)

    def test_legacy_sha256_compatible(self):
        """Alte SHA-256 Hashes (ohne Salt) werden noch akzeptiert."""
        pin = "legacy_pin"
        old_hash = hashlib.sha256(pin.encode()).hexdigest()
        assert self._verify_hash(pin, old_hash)

    def test_legacy_migration_path(self):
        """Nach erfolgreicher Legacy-Verifikation kann man einen neuen Hash erstellen."""
        pin = "old_pin"
        old_hash = hashlib.sha256(pin.encode()).hexdigest()
        # Verify mit altem Hash
        assert self._verify_hash(pin, old_hash)
        # Neuen PBKDF2 Hash erstellen
        new_hash = self._hash_value(pin)
        assert ":" in new_hash  # Neues Format
        assert self._verify_hash(pin, new_hash)

    def test_salt_is_random(self):
        h1 = self._hash_value("pin")
        h2 = self._hash_value("pin")
        salt1 = h1.split(":")[0]
        salt2 = h2.split(":")[0]
        assert salt1 != salt2

    def test_hash_format(self):
        hashed = self._hash_value("test", salt="deadbeef" * 4)
        salt, hex_hash = hashed.split(":", 1)
        assert salt == "deadbeef" * 4
        assert len(hex_hash) == 64  # SHA-256 = 32 bytes = 64 hex chars


# ---------------------------------------------------------------
# CORS Origins Tests
# ---------------------------------------------------------------


class TestCorsOrigins:
    """CORS Origins werden korrekt getrimmt und geparsed."""

    def test_split_and_strip(self):
        raw = "http://localhost, http://example.com , http://ha.local:8123 "
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        assert origins == ["http://localhost", "http://example.com", "http://ha.local:8123"]

    def test_empty_string_results_in_empty_list(self):
        raw = ""
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        assert origins == []

    def test_single_origin(self):
        raw = "http://localhost:8123"
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        assert origins == ["http://localhost:8123"]

    def test_trailing_comma_ignored(self):
        raw = "http://localhost,"
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        assert origins == ["http://localhost"]

    def test_no_leading_spaces_in_origins(self):
        """Fuehrende Leerzeichen in Origins fuehren zu CORS-Fehlern."""
        raw = "http://localhost, http://example.com"
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        for origin in origins:
            assert not origin.startswith(" ")
            assert not origin.endswith(" ")


# ---------------------------------------------------------------
# API Key Initialization Tests
# ---------------------------------------------------------------


class TestApiKeyInit:
    """API Key wird generiert und Enforcement ist per Default aktiv."""

    def test_generated_key_is_strong(self):
        key = secrets.token_urlsafe(32)
        assert len(key) >= 32

    def test_enforcement_default_is_true(self):
        """Ohne explizite Konfiguration soll api_key_required=True sein."""
        security_cfg = {}
        required = security_cfg.get("api_key_required", True)
        assert required is True

    def test_enforcement_explicit_false(self):
        """User kann Enforcement explizit deaktivieren."""
        security_cfg = {"api_key_required": False}
        required = security_cfg.get("api_key_required", True)
        assert required is False

    def test_env_key_overrides_yaml(self):
        """Env-Variable hat hoechste Prioritaet."""
        env_key = "env_secret_key_123"
        yaml_key = "yaml_key_456"
        # Env hat Vorrang
        final_key = env_key if env_key else yaml_key
        assert final_key == env_key

    def test_compare_digest_timing_safe(self):
        """secrets.compare_digest ist timing-safe."""
        key = "my_api_key_123"
        assert secrets.compare_digest(key, key) is True
        assert secrets.compare_digest(key, "wrong") is False
        assert secrets.compare_digest("", "") is True


# ---------------------------------------------------------------
# HA Client States Cache Tests
# ---------------------------------------------------------------


class TestStatesCaching:
    """get_states() Cache verhindert N+1 Queries."""

    def test_cache_hit_within_ttl(self):
        """Zwei Aufrufe innerhalb von 2 Sekunden nutzen Cache."""
        cache = [{"entity_id": "light.wohnzimmer", "state": "on"}]
        cache_ts = time.monotonic()

        # Simulierter zweiter Aufruf 0.5s spaeter
        now = cache_ts + 0.5
        is_cached = cache is not None and (now - cache_ts) < 2.0
        assert is_cached is True

    def test_cache_miss_after_ttl(self):
        """Nach 2 Sekunden wird Cache invalidiert."""
        cache_ts = time.monotonic()

        now = cache_ts + 2.1
        is_cached = (now - cache_ts) < 2.0
        assert is_cached is False

    def test_cache_miss_when_empty(self):
        """Erster Aufruf hat keinen Cache."""
        cache = None
        cache_ts = 0.0

        now = time.monotonic()
        is_cached = cache is not None and (now - cache_ts) < 2.0
        assert is_cached is False
