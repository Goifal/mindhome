"""Tests for assistant/web_search.py — WebSearch unit tests."""

import ipaddress
import time
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from assistant.web_search import (
    WebSearch,
    _is_ip_blocked,
    _is_safe_url,
    _resolve_and_check,
    _safe_read_json,
    _BLOCKED_NETWORKS,
    _BLOCKED_HOSTNAMES,
)


# ── _is_ip_blocked ───────────────────────────────────────────


def test_ip_blocked_loopback():
    assert _is_ip_blocked(ipaddress.ip_address("127.0.0.1")) is True


def test_ip_blocked_private_10():
    assert _is_ip_blocked(ipaddress.ip_address("10.0.0.1")) is True


def test_ip_blocked_private_192():
    assert _is_ip_blocked(ipaddress.ip_address("192.168.1.1")) is True


def test_ip_blocked_private_172():
    assert _is_ip_blocked(ipaddress.ip_address("172.16.0.1")) is True


def test_ip_blocked_link_local():
    assert _is_ip_blocked(ipaddress.ip_address("169.254.1.1")) is True


def test_ip_blocked_cgnat():
    assert _is_ip_blocked(ipaddress.ip_address("100.64.0.1")) is True


def test_ip_blocked_ipv6_loopback():
    assert _is_ip_blocked(ipaddress.ip_address("::1")) is True


def test_ip_blocked_ipv4_mapped_ipv6():
    addr = ipaddress.ip_address("::ffff:127.0.0.1")
    assert _is_ip_blocked(addr) is True


def test_ip_not_blocked_public():
    assert _is_ip_blocked(ipaddress.ip_address("8.8.8.8")) is False


def test_ip_not_blocked_public_ipv6():
    assert _is_ip_blocked(ipaddress.ip_address("2001:4860:4860::8888")) is False


# ── _is_safe_url ─────────────────────────────────────────────


def test_safe_url_https():
    assert _is_safe_url("https://example.com/search") is True


def test_safe_url_http():
    assert _is_safe_url("http://example.com/search") is True


def test_unsafe_url_ftp():
    assert _is_safe_url("ftp://example.com/file") is False


def test_unsafe_url_javascript():
    assert _is_safe_url("javascript:alert(1)") is False


def test_unsafe_url_localhost():
    assert _is_safe_url("http://localhost/api") is False


def test_unsafe_url_blocked_hostname():
    assert _is_safe_url("http://redis:6379/") is False
    assert _is_safe_url("http://metadata.google.internal/") is False


def test_unsafe_url_private_ip():
    assert _is_safe_url("http://192.168.1.1/admin") is False


def test_unsafe_url_loopback_ip():
    assert _is_safe_url("http://127.0.0.1:8080/") is False


def test_unsafe_url_userinfo():
    assert _is_safe_url("http://admin:pass@example.com/") is False


def test_unsafe_url_empty():
    assert _is_safe_url("") is False


def test_safe_url_no_hostname():
    assert _is_safe_url("http:///path") is False


# ── _resolve_and_check ────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_and_check_blocked_hostname():
    assert await _resolve_and_check("localhost") is False


@pytest.mark.asyncio
async def test_resolve_and_check_ip_literal_public():
    assert await _resolve_and_check("8.8.8.8") is True


@pytest.mark.asyncio
async def test_resolve_and_check_ip_literal_blocked():
    assert await _resolve_and_check("127.0.0.1") is False


@pytest.mark.asyncio
async def test_resolve_and_check_empty():
    assert await _resolve_and_check("") is False


# ── _safe_read_json ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_safe_read_json_valid():
    resp = AsyncMock()
    resp.headers = {"Content-Type": "application/json; charset=utf-8"}
    resp.content_length = 100
    resp.content.read = AsyncMock(return_value=b'{"results": []}')
    result = await _safe_read_json(resp)
    assert result == {"results": []}


@pytest.mark.asyncio
async def test_safe_read_json_wrong_content_type():
    resp = AsyncMock()
    resp.headers = {"Content-Type": "text/html"}
    resp.content_length = 100
    result = await _safe_read_json(resp)
    assert result is None


@pytest.mark.asyncio
async def test_safe_read_json_too_large_header():
    resp = AsyncMock()
    resp.headers = {"Content-Type": "application/json"}
    resp.content_length = 10 * 1024 * 1024  # 10 MB
    result = await _safe_read_json(resp)
    assert result is None


@pytest.mark.asyncio
async def test_safe_read_json_too_large_body():
    resp = AsyncMock()
    resp.headers = {"Content-Type": "application/json"}
    resp.content_length = None
    resp.content.read = AsyncMock(return_value=b"x" * (5 * 1024 * 1024 + 2))
    result = await _safe_read_json(resp)
    assert result is None


@pytest.mark.asyncio
async def test_safe_read_json_invalid_json():
    resp = AsyncMock()
    resp.headers = {"Content-Type": "application/json"}
    resp.content_length = 10
    resp.content.read = AsyncMock(return_value=b"not json")
    result = await _safe_read_json(resp)
    assert result is None


# ── WebSearch.__init__ ────────────────────────────────────────


def test_websearch_init_disabled_by_default():
    with patch("assistant.web_search.yaml_config", {"web_search": {}}):
        ws = WebSearch()
    assert ws.enabled is False


def test_websearch_init_enabled():
    with patch(
        "assistant.web_search.yaml_config",
        {
            "web_search": {
                "enabled": True,
                "engine": "searxng",
                "searxng_url": "http://searxng:8888",
            },
        },
    ):
        ws = WebSearch()
    assert ws.enabled is True


def test_websearch_init_invalid_searxng_url():
    with patch(
        "assistant.web_search.yaml_config",
        {
            "web_search": {
                "enabled": True,
                "engine": "searxng",
                "searxng_url": "ftp://bad",
            },
        },
    ):
        ws = WebSearch()
    assert ws.enabled is False


# ── _sanitize_query ───────────────────────────────────────────


def test_sanitize_query_normal():
    with patch("assistant.web_search.yaml_config", {"web_search": {}}):
        ws = WebSearch()
    assert ws._sanitize_query("python tutorial") == "python tutorial"


def test_sanitize_query_too_short():
    with patch("assistant.web_search.yaml_config", {"web_search": {}}):
        ws = WebSearch()
    assert ws._sanitize_query("ab") is None


def test_sanitize_query_empty():
    with patch("assistant.web_search.yaml_config", {"web_search": {}}):
        ws = WebSearch()
    assert ws._sanitize_query("") is None
    assert ws._sanitize_query(None) is None


def test_sanitize_query_blacklisted_scheme():
    with patch("assistant.web_search.yaml_config", {"web_search": {}}):
        ws = WebSearch()
    assert ws._sanitize_query("file:///etc/passwd") is None
    assert ws._sanitize_query("<script>alert(1)") is None


def test_sanitize_query_null_bytes_removed():
    with patch("assistant.web_search.yaml_config", {"web_search": {}}):
        ws = WebSearch()
    # Null bytes are stripped first, then blacklist checks on the cleaned string
    result = ws._sanitize_query("test\x00query")
    assert result is not None
    assert "\x00" not in result


def test_sanitize_query_blacklisted_with_null():
    with patch("assistant.web_search.yaml_config", {"web_search": {}}):
        ws = WebSearch()
    # Null byte alone triggers blacklist because original string has \x00
    assert ws._sanitize_query("\x00\x00\x00") is None


def test_sanitize_query_truncates_long():
    with patch("assistant.web_search.yaml_config", {"web_search": {}}):
        ws = WebSearch()
    long_query = "a" * 500
    result = ws._sanitize_query(long_query)
    assert len(result) == ws._MAX_QUERY_LEN


def test_sanitize_query_removes_bangs():
    with patch("assistant.web_search.yaml_config", {"web_search": {}}):
        ws = WebSearch()
    result = ws._sanitize_query("!google test query")
    assert "!google" not in result
    assert "test query" in result


# ── _check_rate_limit ─────────────────────────────────────────


def test_rate_limit_allows_initially():
    with patch(
        "assistant.web_search.yaml_config",
        {"web_search": {"rate_limit_max": 3, "rate_limit_window": 60}},
    ):
        ws = WebSearch()
    assert ws._check_rate_limit() is True


def test_rate_limit_blocks_when_exceeded():
    with patch(
        "assistant.web_search.yaml_config",
        {"web_search": {"rate_limit_max": 2, "rate_limit_window": 60}},
    ):
        ws = WebSearch()
    ws._check_rate_limit()
    ws._check_rate_limit()
    assert ws._check_rate_limit() is False


# ── Cache ─────────────────────────────────────────────────────


def test_cache_key_consistent():
    with patch("assistant.web_search.yaml_config", {"web_search": {}}):
        ws = WebSearch()
    k1 = ws._get_cache_key("Hello World")
    k2 = ws._get_cache_key("hello world")
    assert k1 == k2


def test_cache_set_and_get():
    with patch("assistant.web_search.yaml_config", {"web_search": {}}):
        ws = WebSearch()
    ws._set_cached("test query", {"success": True, "message": "result"})
    result = ws._get_cached("test query")
    assert result is not None
    assert result["success"] is True


def test_cache_expired():
    with patch(
        "assistant.web_search.yaml_config", {"web_search": {"cache_ttl_seconds": 0}}
    ):
        ws = WebSearch()
    ws._cache_ttl = 0
    ws._set_cached("test query", {"success": True})
    # Monotonic time has moved forward so TTL=0 means expired
    result = ws._get_cached("test query")
    # With TTL 0, cache check: (now - entry_ts) < 0 is False
    assert result is None


def test_cache_eviction():
    with patch("assistant.web_search.yaml_config", {"web_search": {}}):
        ws = WebSearch()
    for i in range(101):
        ws._set_cached(f"query {i}", {"i": i})
    assert len(ws._cache) <= 100


# ── search ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_disabled():
    with patch("assistant.web_search.yaml_config", {"web_search": {"enabled": False}}):
        ws = WebSearch()
    result = await ws.search("test")
    assert result["success"] is False
    assert "deaktiviert" in result["message"]


@pytest.mark.asyncio
async def test_search_invalid_query():
    with patch(
        "assistant.web_search.yaml_config",
        {"web_search": {"enabled": True, "engine": "duckduckgo"}},
    ):
        ws = WebSearch()
    result = await ws.search("ab")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_search_rate_limited():
    with patch(
        "assistant.web_search.yaml_config",
        {
            "web_search": {
                "enabled": True,
                "engine": "duckduckgo",
                "rate_limit_max": 0,
                "rate_limit_window": 60,
            },
        },
    ):
        ws = WebSearch()
    result = await ws.search("test query")
    assert result["success"] is False
    assert "viele Suchanfragen" in result["message"]


@pytest.mark.asyncio
async def test_search_returns_cached():
    with patch(
        "assistant.web_search.yaml_config",
        {
            "web_search": {"enabled": True, "engine": "duckduckgo"},
        },
    ):
        ws = WebSearch()
    cached_result = {"success": True, "message": "cached result"}
    ws._set_cached("test query", cached_result)
    result = await ws.search("test query")
    assert result["message"] == "cached result"


@pytest.mark.asyncio
async def test_search_exception_sanitized():
    with patch(
        "assistant.web_search.yaml_config",
        {
            "web_search": {
                "enabled": True,
                "engine": "searxng",
                "searxng_url": "http://searxng:8888",
            },
        },
    ):
        ws = WebSearch()
    ws._cache.clear()
    with patch.object(
        ws,
        "_search_searxng",
        new_callable=AsyncMock,
        side_effect=Exception("internal error details"),
    ):
        result = await ws.search("test query")
    assert result["success"] is False
    assert "internal error" not in result["message"]  # F-078: no internal details
    assert "nicht durchgefuehrt" in result["message"]


# ── NEW: _is_safe_url edge cases — Lines 115-116 ────────────


def test_safe_url_exception():
    """Exception in URL parsing returns False (lines 115-116)."""
    # Passing a non-string triggers exception
    assert _is_safe_url(None) is False


# ── NEW: _resolve_and_check DNS resolution — Lines 153, 165-166 ────


@pytest.mark.asyncio
async def test_resolve_and_check_dns_timeout():
    """DNS timeout returns False (lines 146-148)."""
    import asyncio

    with patch(
        "assistant.web_search.asyncio.wait_for", side_effect=asyncio.TimeoutError()
    ):
        result = await _resolve_and_check("example.com")
    assert result is False


@pytest.mark.asyncio
async def test_resolve_and_check_dns_failure():
    """DNS failure returns False (lines 149-151)."""
    import socket

    with patch("assistant.web_search.asyncio.wait_for", side_effect=socket.gaierror()):
        result = await _resolve_and_check("nonexistent.invalid")
    assert result is False


@pytest.mark.asyncio
async def test_resolve_and_check_no_results():
    """No DNS results returns False (line 153)."""
    with patch("assistant.web_search.asyncio.wait_for", return_value=[]):
        result = await _resolve_and_check("example.com")
    assert result is False


@pytest.mark.asyncio
async def test_resolve_and_check_invalid_ip_in_result():
    """Invalid IP in DNS result returns False (lines 165-166)."""
    # sockaddr with unparseable IP
    infos = [(2, 1, 0, "", ("not-an-ip", 80))]
    with patch("assistant.web_search.asyncio.wait_for", return_value=infos):
        result = await _resolve_and_check("example.com")
    assert result is False


# ── NEW: _safe_read_json — Line 309 ─────────────────────────


@pytest.mark.asyncio
async def test_safe_read_json_no_content_length():
    """Content-Length is None, body within limits (line 185-186)."""
    resp = AsyncMock()
    resp.headers = {"Content-Type": "application/json"}
    resp.content_length = None
    resp.content.read = AsyncMock(return_value=b'{"key": "value"}')
    result = await _safe_read_json(resp)
    assert result == {"key": "value"}


# ── NEW: search with SearXNG — Lines 376-403 ────────────────


@pytest.mark.asyncio
async def test_search_searxng_success():
    """SearXNG search returns formatted results (lines 376-403)."""
    import aiohttp

    with patch(
        "assistant.web_search.yaml_config",
        {
            "web_search": {
                "enabled": True,
                "engine": "searxng",
                "searxng_url": "http://searxng:8888",
            },
        },
    ):
        ws = WebSearch()
    ws._cache.clear()

    mock_resp = AsyncMock()
    mock_resp.status = 200

    with (
        patch(
            "assistant.web_search._safe_read_json",
            new_callable=AsyncMock,
            return_value={
                "results": [
                    {
                        "title": "Result 1",
                        "content": "Snippet 1",
                        "url": "https://example.com/1",
                    },
                    {
                        "title": "Result 2",
                        "content": "Snippet 2",
                        "url": "https://example.com/2",
                    },
                ]
            },
        ),
        patch("aiohttp.ClientSession") as mock_session,
    ):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session_instance = AsyncMock()
        mock_session_instance.get = MagicMock(return_value=mock_ctx)
        mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
        mock_session_instance.__aexit__ = AsyncMock(return_value=False)
        mock_session.return_value = mock_session_instance

        with patch(
            "assistant.web_search._safe_read_json", new_callable=AsyncMock
        ) as mock_json:
            mock_json.return_value = {
                "results": [
                    {
                        "title": "Result 1",
                        "content": "Snippet 1",
                        "url": "https://example.com/1",
                    },
                ]
            }
            # Use direct method call to test _search_searxng
            results = await ws._search_searxng("test query")
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_search_searxng_non_200():
    """SearXNG returns empty on non-200 status (line 432)."""
    with patch(
        "assistant.web_search.yaml_config",
        {
            "web_search": {
                "enabled": True,
                "engine": "searxng",
                "searxng_url": "http://searxng:8888",
            },
        },
    ):
        ws = WebSearch()

    mock_resp = AsyncMock()
    mock_resp.status = 500

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_ctx)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        results = await ws._search_searxng("test")
    assert results == []


@pytest.mark.asyncio
async def test_search_no_results():
    """Empty results returns no-results message (line 379)."""
    with patch(
        "assistant.web_search.yaml_config",
        {
            "web_search": {
                "enabled": True,
                "engine": "searxng",
                "searxng_url": "http://searxng:8888",
            },
        },
    ):
        ws = WebSearch()
    ws._cache.clear()

    with patch.object(ws, "_search_searxng", new_callable=AsyncMock, return_value=[]):
        result = await ws.search("test query")
    assert result["success"] is True
    assert "Keine Ergebnisse" in result["message"]


# ── NEW: _search_duckduckgo — Lines 454-510 ─────────────────


@pytest.mark.asyncio
async def test_search_duckduckgo_dns_blocked():
    """DuckDuckGo blocked by DNS check (lines 464-466)."""
    with patch(
        "assistant.web_search.yaml_config",
        {
            "web_search": {"enabled": True, "engine": "duckduckgo"},
        },
    ):
        ws = WebSearch()

    # F-093: _resolve_and_pin statt _resolve_and_check (TOCTOU-Fix)
    with patch(
        "assistant.web_search._resolve_and_pin", new_callable=AsyncMock, return_value=[]
    ):
        results = await ws._search_duckduckgo("test")
    assert results == []


@pytest.mark.asyncio
async def test_search_duckduckgo_with_results():
    """DuckDuckGo returns abstract and related topics (lines 485-510)."""
    with patch(
        "assistant.web_search.yaml_config",
        {
            "web_search": {"enabled": True, "engine": "duckduckgo"},
        },
    ):
        ws = WebSearch()

    mock_data = {
        "AbstractText": "Python is a language",
        "AbstractURL": "https://python.org",
        "Heading": "Python",
        "RelatedTopics": [
            {"Text": "Related topic 1", "FirstURL": "https://example.com/1"},
            {"Text": "Related topic 2", "FirstURL": "https://example.com/2"},
        ],
    }

    mock_resp = AsyncMock()
    mock_resp.status = 200

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_ctx)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    # F-093: _resolve_and_pin statt _resolve_and_check mocken (TOCTOU-Fix)
    fake_resolved = [
        {
            "hostname": "api.duckduckgo.com",
            "host": "52.142.124.215",
            "port": 0,
            "family": 2,
            "proto": 0,
            "flags": 0,
        }
    ]
    with (
        patch(
            "assistant.web_search._resolve_and_pin",
            new_callable=AsyncMock,
            return_value=fake_resolved,
        ),
        patch("aiohttp.ClientSession", return_value=mock_session),
        patch(
            "assistant.web_search._safe_read_json",
            new_callable=AsyncMock,
            return_value=mock_data,
        ),
    ):
        results = await ws._search_duckduckgo("python")

    assert len(results) >= 1
    assert results[0]["title"] == "Python"


@pytest.mark.asyncio
async def test_search_duckduckgo_unsafe_url():
    """DuckDuckGo filters unsafe URLs (lines 489-490, 502-503)."""
    with patch(
        "assistant.web_search.yaml_config",
        {
            "web_search": {"enabled": True, "engine": "duckduckgo"},
        },
    ):
        ws = WebSearch()

    mock_data = {
        "AbstractText": "Test",
        "AbstractURL": "http://192.168.1.1/admin",  # Blocked
        "Heading": "Test",
        "RelatedTopics": [
            {"Text": "Topic", "FirstURL": "http://127.0.0.1/internal"},  # Blocked
        ],
    }

    mock_resp = AsyncMock()
    mock_resp.status = 200

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_ctx)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    # F-093: _resolve_and_pin statt _resolve_and_check (TOCTOU-Fix)
    fake_resolved = [
        {
            "hostname": "api.duckduckgo.com",
            "host": "52.142.124.215",
            "port": 0,
            "family": 2,
            "proto": 0,
            "flags": 0,
        }
    ]
    with (
        patch(
            "assistant.web_search._resolve_and_pin",
            new_callable=AsyncMock,
            return_value=fake_resolved,
        ),
        patch("aiohttp.ClientSession", return_value=mock_session),
        patch(
            "assistant.web_search._safe_read_json",
            new_callable=AsyncMock,
            return_value=mock_data,
        ),
    ):
        results = await ws._search_duckduckgo("test")

    # URLs should be cleared
    for r in results:
        assert r["url"] == ""


# ── NEW: SearXNG invalid URL at init — Line 252 ─────────────


def test_searxng_url_with_path():
    """SearXNG URL with query/fragment is disabled."""
    with patch(
        "assistant.web_search.yaml_config",
        {
            "web_search": {
                "enabled": True,
                "engine": "searxng",
                "searxng_url": "http://searxng:8888?foo=bar",
            },
        },
    ):
        ws = WebSearch()
    assert ws.enabled is False


# ── NEW: search result URL filtering — Lines 412-450 ────────


@pytest.mark.asyncio
async def test_search_searxng_filters_unsafe_result_urls():
    """SearXNG filters unsafe URLs in results (lines 442-444)."""
    with patch(
        "assistant.web_search.yaml_config",
        {
            "web_search": {
                "enabled": True,
                "engine": "searxng",
                "searxng_url": "http://searxng:8888",
            },
        },
    ):
        ws = WebSearch()

    mock_resp = AsyncMock()
    mock_resp.status = 200

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_ctx)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("aiohttp.ClientSession", return_value=mock_session),
        patch(
            "assistant.web_search._safe_read_json",
            new_callable=AsyncMock,
            return_value={
                "results": [
                    {"title": "Safe", "content": "OK", "url": "https://example.com"},
                    {
                        "title": "Unsafe",
                        "content": "Bad",
                        "url": "http://192.168.1.1/admin",
                    },
                ]
            },
        ),
    ):
        results = await ws._search_searxng("test")

    # Unsafe URL should be cleared
    unsafe = [r for r in results if r["url"] == "" and r["title"] == "Unsafe"]
    assert len(unsafe) == 1


# ============================================================
# F-093: Security Hardening Tests
# ============================================================


class TestF093ContentTypeHardening:
    """F-093: Content-Type-Validierung verschaerft — nur application/json."""

    @pytest.mark.asyncio
    async def test_rejects_text_html_with_json_substring(self):
        """'text/html; json' darf nicht als JSON akzeptiert werden."""
        resp = AsyncMock()
        resp.headers = {"Content-Type": "text/html; json"}
        resp.content_length = 10
        assert await _safe_read_json(resp) is None

    @pytest.mark.asyncio
    async def test_rejects_application_not_json(self):
        """'application/not-json-really' wird abgelehnt."""
        resp = AsyncMock()
        resp.headers = {"Content-Type": "application/not-json-really"}
        resp.content_length = 10
        assert await _safe_read_json(resp) is None

    @pytest.mark.asyncio
    async def test_accepts_application_json_with_charset(self):
        """'application/json; charset=utf-8' wird akzeptiert."""
        resp = AsyncMock()
        resp.headers = {"Content-Type": "application/json; charset=utf-8"}
        resp.content_length = 10
        resp.content.read = AsyncMock(return_value=b'{"ok": true}')
        result = await _safe_read_json(resp)
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_accepts_text_json(self):
        """'text/json' wird als Legacy-MIME akzeptiert."""
        resp = AsyncMock()
        resp.headers = {"Content-Type": "text/json"}
        resp.content_length = 10
        resp.content.read = AsyncMock(return_value=b'{"ok": true}')
        result = await _safe_read_json(resp)
        assert result == {"ok": True}


class TestF093UnicodeQueryBypass:
    """F-093: Unicode-Normalisierung verhindert Fullwidth-Bypasses."""

    def _make_ws(self):
        with patch("assistant.web_search.yaml_config", {"web_search": {}}):
            return WebSearch()

    def test_fullwidth_file_scheme_blocked(self):
        """Fullwidth 'ｆｉｌｅ://' wird nach NFKC zu 'file://' → blockiert."""
        ws = self._make_ws()
        assert ws._sanitize_query("\uff46\uff49\uff4c\uff45://etc/passwd") is None

    def test_fullwidth_script_tag_blocked(self):
        """Fullwidth '<script' wird nach NFKC normalisiert → blockiert."""
        ws = self._make_ws()
        assert ws._sanitize_query("\uff1cscript\uff1e") is None

    def test_normal_unicode_passes(self):
        """Normaler Unicode (Umlaute etc.) passiert unbeschaedigt."""
        ws = self._make_ws()
        result = ws._sanitize_query("Wetter in München heute")
        assert result is not None
        assert "München" in result


class TestF093BangPatternHardening:
    """F-093: Erweiterte Bang-Pattern-Erkennung."""

    def _make_ws(self):
        with patch("assistant.web_search.yaml_config", {"web_search": {}}):
            return WebSearch()

    def test_numeric_bang_removed(self):
        """Numerische Bangs wie !123 werden entfernt."""
        ws = self._make_ws()
        result = ws._sanitize_query("!123 python tutorial")
        assert "!123" not in result
        assert "python tutorial" in result

    def test_double_bang_removed(self):
        """Doppel-Bangs wie !!g werden entfernt."""
        ws = self._make_ws()
        result = ws._sanitize_query("!!google test query")
        assert "!!google" not in result
        assert "test query" in result

    def test_searxng_engine_operator_removed(self):
        """SearXNG engines: Operator wird entfernt."""
        ws = self._make_ws()
        result = ws._sanitize_query("python tutorial engines:google")
        assert "engines:" not in result
        assert "python tutorial" in result

    def test_searxng_categories_operator_removed(self):
        """SearXNG categories: Operator wird entfernt."""
        ws = self._make_ws()
        result = ws._sanitize_query("categories:science python")
        assert "categories:" not in result

    def test_no_double_spaces_after_removal(self):
        """Nach Operator-Entfernung bleiben keine Doppel-Leerzeichen."""
        ws = self._make_ws()
        result = ws._sanitize_query("test !bing more engines:foo words")
        assert "  " not in result


class TestF093ResolveAndPin:
    """F-093: TOCTOU-sicheres DNS-Pinning."""

    @pytest.mark.asyncio
    async def test_blocked_hostname_returns_empty(self):
        """Geblockte Hostnames geben leere Liste zurueck."""
        from assistant.web_search import _resolve_and_pin

        result = await _resolve_and_pin("localhost")
        assert result == []

    @pytest.mark.asyncio
    async def test_blocked_ip_literal_returns_empty(self):
        """Geblockte IP-Literals geben leere Liste zurueck."""
        from assistant.web_search import _resolve_and_pin

        result = await _resolve_and_pin("127.0.0.1")
        assert result == []

    @pytest.mark.asyncio
    async def test_public_ip_literal_returns_resolved(self):
        """Oeffentliche IP-Literals werden direkt zurueckgegeben."""
        from assistant.web_search import _resolve_and_pin

        result = await _resolve_and_pin("8.8.8.8")
        assert len(result) == 1
        assert result[0]["host"] == "8.8.8.8"

    @pytest.mark.asyncio
    async def test_dns_resolves_to_blocked_returns_empty(self):
        """DNS der auf blockierte IP aufloest → leere Liste."""
        from assistant.web_search import _resolve_and_pin

        infos = [(2, 1, 6, "", ("127.0.0.1", 0))]
        with patch("assistant.web_search.asyncio.wait_for", return_value=infos):
            result = await _resolve_and_pin("evil.example.com")
        assert result == []

    @pytest.mark.asyncio
    async def test_dns_resolves_to_safe_returns_ips(self):
        """DNS der auf sichere IP aufloest → IP-Liste."""
        from assistant.web_search import _resolve_and_pin

        infos = [(2, 1, 6, "", ("93.184.216.34", 0))]
        with patch("assistant.web_search.asyncio.wait_for", return_value=infos):
            result = await _resolve_and_pin("example.com")
        assert len(result) == 1
        assert result[0]["host"] == "93.184.216.34"


class TestF093PinnedResolver:
    """F-093: PinnedResolver liefert nur vorgepinnte IPs."""

    @pytest.mark.asyncio
    async def test_resolves_pinned_hostname(self):
        """Gepinnter Hostname gibt vorgepinnte IPs zurueck."""
        from assistant.web_search import _PinnedResolver

        resolver = _PinnedResolver(
            "example.com",
            [
                {
                    "hostname": "example.com",
                    "host": "93.184.216.34",
                    "port": 0,
                    "family": 2,
                    "proto": 0,
                    "flags": 0,
                },
            ],
        )
        result = await resolver.resolve("example.com", 443)
        assert len(result) == 1
        assert result[0]["host"] == "93.184.216.34"
        assert result[0]["port"] == 443

    @pytest.mark.asyncio
    async def test_rejects_unknown_hostname(self):
        """Unbekannter Hostname wirft OSError."""
        from assistant.web_search import _PinnedResolver

        resolver = _PinnedResolver("example.com", [])
        with pytest.raises(OSError, match="DNS blockiert"):
            await resolver.resolve("evil.com", 443)
