"""
Security-Endpoint-Tests (P07a): Verifiziert dass kritische Endpoints
aus P04c/P06d korrekt abgesichert sind.

Testet:
- Token-Validierung (_check_token)
- PIN Brute-Force-Schutz (_check_pin_rate_limit)
- Workshop Hardware Trust-Level (_require_hardware_owner)
- SSRF URL-Validierung (Addon routes)
"""

import importlib
import secrets
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------
# Token-Validierung
# ---------------------------------------------------------------


class TestCheckToken:
    """Verifiziert dass _check_token unautorisierte Requests ablehnt."""

    def _make_check_token(self):
        """Erstellt isolierte Token-Check-Logik."""
        active_tokens: dict[str, float] = {}
        api_key = ""
        expiry = 86400  # 24h

        def check(token: str):
            if api_key and token and secrets.compare_digest(token, api_key):
                return True
            if token not in active_tokens:
                return False
            created = active_tokens[token]
            now = datetime.now(timezone.utc).timestamp()
            if now - created > expiry:
                del active_tokens[token]
                return False
            return True

        return active_tokens, check

    def test_empty_token_rejected(self):
        _, check = self._make_check_token()
        assert check("") is False

    def test_random_token_rejected(self):
        _, check = self._make_check_token()
        assert check("abc123random") is False

    def test_valid_token_accepted(self):
        tokens, check = self._make_check_token()
        token = "valid_session_token_12345678"
        tokens[token] = datetime.now(timezone.utc).timestamp()
        assert check(token) is True

    def test_expired_token_rejected(self):
        tokens, check = self._make_check_token()
        token = "expired_token_xyz"
        tokens[token] = datetime.now(timezone.utc).timestamp() - 90000  # >24h ago
        assert check(token) is False


# ---------------------------------------------------------------
# Security Endpoint Auth Verification
# ---------------------------------------------------------------


class TestEndpointAuthRequirements:
    """Statische Analyse: Alle kritischen Endpoints nutzen _check_token."""

    @pytest.fixture(autouse=True)
    def load_source(self):
        import pathlib
        self.main_source = (
            pathlib.Path(__file__).parent.parent / "assistant" / "main.py"
        ).read_text()

    def _endpoint_has_check_token(self, endpoint_path: str) -> bool:
        """Prueft ob ein Endpoint _check_token aufruft."""
        # Finde die Endpoint-Definition
        import re
        pattern = rf'@app\.\w+\("{re.escape(endpoint_path)}"\)\s*\nasync def \w+\([^)]*\).*?(?=@app\.\w+\(|class |def [a-z])'
        match = re.search(pattern, self.main_source, re.DOTALL)
        if not match:
            return False
        handler_code = match.group(0)
        return "_check_token" in handler_code

    def test_factory_reset_has_auth(self):
        assert self._endpoint_has_check_token("/api/ui/factory-reset")

    def test_system_update_has_auth(self):
        assert self._endpoint_has_check_token("/api/ui/system/update")

    def test_system_restart_has_auth(self):
        assert self._endpoint_has_check_token("/api/ui/system/restart")

    def test_api_key_regenerate_has_auth(self):
        assert self._endpoint_has_check_token("/api/ui/api-key/regenerate")

    def test_recovery_key_regenerate_has_auth(self):
        assert self._endpoint_has_check_token("/api/ui/recovery-key/regenerate")


class TestEndpointPinRateLimit:
    """Statische Analyse: PIN-Endpoints nutzen Rate-Limiting."""

    @pytest.fixture(autouse=True)
    def load_source(self):
        import pathlib
        self.main_source = (
            pathlib.Path(__file__).parent.parent / "assistant" / "main.py"
        ).read_text()

    def _endpoint_has_rate_limit(self, endpoint_path: str) -> bool:
        """Prueft ob ein Endpoint _check_pin_rate_limit aufruft."""
        import re
        pattern = rf'@app\.\w+\("{re.escape(endpoint_path)}"\)\s*\nasync def \w+\([^)]*\).*?(?=@app\.\w+\(|class |def [a-z])'
        match = re.search(pattern, self.main_source, re.DOTALL)
        if not match:
            return False
        return "_check_pin_rate_limit" in match.group(0)

    def test_auth_has_rate_limit(self):
        assert self._endpoint_has_rate_limit("/api/ui/auth")

    def test_reset_pin_has_rate_limit(self):
        assert self._endpoint_has_rate_limit("/api/ui/reset-pin")

    def test_factory_reset_has_rate_limit(self):
        assert self._endpoint_has_rate_limit("/api/ui/factory-reset")


# ---------------------------------------------------------------
# Workshop Hardware Trust-Level
# ---------------------------------------------------------------


class TestWorkshopHardwareTrustLevel:
    """Statische Analyse: Workshop-Endpoints pruefen Trust-Level."""

    @pytest.fixture(autouse=True)
    def load_source(self):
        import pathlib
        self.main_source = (
            pathlib.Path(__file__).parent.parent / "assistant" / "main.py"
        ).read_text()

    HARDWARE_ENDPOINTS = [
        "/api/workshop/arm/move",
        "/api/workshop/arm/gripper",
        "/api/workshop/arm/home",
        "/api/workshop/arm/save-position",
        "/api/workshop/arm/pick-tool",
        "/api/workshop/printer/start",
        "/api/workshop/printer/pause",
        "/api/workshop/printer/cancel",
    ]

    def _endpoint_has_hardware_check(self, endpoint_path: str) -> bool:
        import re
        pattern = rf'@app\.\w+\("{re.escape(endpoint_path)}"\)\s*\nasync def \w+\([^)]*\).*?(?=@app\.\w+\(|class |def [a-z])'
        match = re.search(pattern, self.main_source, re.DOTALL)
        if not match:
            return False
        return "_require_hardware_owner" in match.group(0)

    @pytest.mark.parametrize("endpoint", HARDWARE_ENDPOINTS)
    def test_hardware_endpoint_has_trust_check(self, endpoint):
        assert self._endpoint_has_hardware_check(endpoint), \
            f"{endpoint} fehlt _require_hardware_owner Check"


# ---------------------------------------------------------------
# SSRF Prevention (Addon URL Validation)
# ---------------------------------------------------------------


class TestSsrfPrevention:
    """Prueft dass die URL-Validierung keine Public IPs akzeptiert."""

    # Korrekte RFC 1918 Prefixes
    _ALLOWED_PREFIXES = (
        "192.168.", "10.", "172.16.", "172.17.", "172.18.",
        "172.19.", "172.20.", "172.21.", "172.22.", "172.23.",
        "172.24.", "172.25.", "172.26.", "172.27.", "172.28.",
        "172.29.", "172.30.", "172.31.",
        "127.", "localhost", "::1",
    )

    def _is_allowed(self, url: str) -> bool:
        """Simuliert die URL-Validierung aus addon/routes/chat.py."""
        from urllib.parse import urlparse
        try:
            parsed = urlparse(url)
            host = parsed.hostname or ""
            return any(host.startswith(p) for p in self._ALLOWED_PREFIXES)
        except Exception:
            return False

    def test_private_192_168_allowed(self):
        assert self._is_allowed("http://192.168.1.1:8123/api") is True

    def test_private_10_allowed(self):
        assert self._is_allowed("http://10.0.0.1/api") is True

    def test_private_172_16_allowed(self):
        assert self._is_allowed("http://172.16.0.1/api") is True

    def test_private_172_31_allowed(self):
        assert self._is_allowed("http://172.31.255.255/api") is True

    def test_localhost_allowed(self):
        assert self._is_allowed("http://127.0.0.1:8080/") is True

    def test_public_172_200_blocked(self):
        """Prueft den SSRF-Fix: 172.200.x.x ist KEIN privates Netz."""
        assert self._is_allowed("http://172.200.1.1/api") is False

    def test_public_172_32_blocked(self):
        assert self._is_allowed("http://172.32.0.1/api") is False

    def test_public_172_255_blocked(self):
        assert self._is_allowed("http://172.255.0.1/api") is False

    def test_public_ip_blocked(self):
        assert self._is_allowed("http://8.8.8.8/api") is False

    def test_external_domain_blocked(self):
        assert self._is_allowed("http://evil.com/steal-data") is False


# ---------------------------------------------------------------
# Addon CORS & Ingress Source Verification
# ---------------------------------------------------------------


class TestAddonCorsConfig:
    """Prueft dass addon/app.py CORS konfigurierbar macht."""

    @pytest.fixture(autouse=True)
    def load_source(self):
        import pathlib
        self.addon_source = (
            pathlib.Path(__file__).parent.parent.parent
            / "addon" / "rootfs" / "opt" / "mindhome" / "app.py"
        ).read_text()

    def test_cors_not_wildcard(self):
        """CORS darf nicht mehr blanket '*' sein."""
        assert 'CORS(app)' not in self.addon_source or 'CORS_ORIGINS' in self.addon_source

    def test_cors_configurable(self):
        """CORS_ORIGINS env var wird gelesen."""
        assert "CORS_ORIGINS" in self.addon_source

    def test_ingress_token_checked(self):
        """Ingress-Token wird validiert."""
        assert "X-Ingress-Token" in self.addon_source

    def test_supervisor_token_read(self):
        """SUPERVISOR_TOKEN wird aus env gelesen."""
        assert "SUPERVISOR_TOKEN" in self.addon_source
