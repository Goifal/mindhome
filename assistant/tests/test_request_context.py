"""Tests for request_context - Request-ID tracing and structured logging."""

import logging
import uuid
from contextvars import ContextVar
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from assistant.request_context import (
    _request_id_var,
    get_request_id,
    RequestContextMiddleware,
    StructuredFormatter,
    setup_structured_logging,
)


# ---------------------------------------------------------------------------
# ContextVar / get_request_id
# ---------------------------------------------------------------------------

class TestGetRequestId:
    def test_default_is_empty_string(self):
        token = _request_id_var.set("")
        try:
            assert get_request_id() == ""
        finally:
            _request_id_var.reset(token)

    def test_returns_set_value(self):
        token = _request_id_var.set("abc123")
        try:
            assert get_request_id() == "abc123"
        finally:
            _request_id_var.reset(token)

    def test_reset_restores_previous(self):
        original = _request_id_var.get()
        token = _request_id_var.set("temp")
        assert get_request_id() == "temp"
        _request_id_var.reset(token)
        assert get_request_id() == original

    def test_set_and_get_unicode_value(self):
        token = _request_id_var.set("req-\u00fc\u00e4\u00f6")
        try:
            assert get_request_id() == "req-\u00fc\u00e4\u00f6"
        finally:
            _request_id_var.reset(token)

    def test_set_long_value(self):
        long_id = "x" * 200
        token = _request_id_var.set(long_id)
        try:
            assert get_request_id() == long_id
        finally:
            _request_id_var.reset(token)


# ---------------------------------------------------------------------------
# StructuredFormatter
# ---------------------------------------------------------------------------

class TestStructuredFormatter:
    def _make_record(self, msg="test message"):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg=msg,
            args=(),
            exc_info=None,
        )
        return record

    def test_format_includes_request_id_when_set(self):
        fmt = "%(request_id)s%(message)s"
        formatter = StructuredFormatter(fmt=fmt)
        token = _request_id_var.set("xyz789")
        try:
            record = self._make_record("hello")
            output = formatter.format(record)
            assert "[req-xyz789]" in output
            assert "hello" in output
        finally:
            _request_id_var.reset(token)

    def test_format_no_request_id_when_empty(self):
        fmt = "%(request_id)s%(message)s"
        formatter = StructuredFormatter(fmt=fmt)
        token = _request_id_var.set("")
        try:
            record = self._make_record("hello")
            output = formatter.format(record)
            assert "[req-" not in output
            assert "hello" in output
        finally:
            _request_id_var.reset(token)

    def test_format_with_full_format_string(self):
        fmt = "%(asctime)s [%(name)s] %(levelname)s: %(request_id)s%(message)s"
        formatter = StructuredFormatter(fmt=fmt, datefmt="%H:%M:%S")
        token = _request_id_var.set("aaa")
        try:
            record = self._make_record("msg")
            output = formatter.format(record)
            assert "[test]" in output
            assert "INFO" in output
            assert "[req-aaa]" in output
        finally:
            _request_id_var.reset(token)

    def test_format_sets_request_id_attr_on_record(self):
        fmt = "%(request_id)s%(message)s"
        formatter = StructuredFormatter(fmt=fmt)
        token = _request_id_var.set("r1")
        try:
            record = self._make_record("x")
            formatter.format(record)
            assert record.request_id == "[req-r1] "
        finally:
            _request_id_var.reset(token)

    def test_format_sets_empty_request_id_attr_when_no_id(self):
        fmt = "%(request_id)s%(message)s"
        formatter = StructuredFormatter(fmt=fmt)
        token = _request_id_var.set("")
        try:
            record = self._make_record("x")
            formatter.format(record)
            assert record.request_id == ""
        finally:
            _request_id_var.reset(token)

    def test_format_request_id_has_trailing_space(self):
        """The request_id field should have a trailing space for readability."""
        fmt = "%(request_id)s%(message)s"
        formatter = StructuredFormatter(fmt=fmt)
        token = _request_id_var.set("test123")
        try:
            record = self._make_record("msg")
            formatter.format(record)
            assert record.request_id.endswith(" ")
        finally:
            _request_id_var.reset(token)

    def test_formatter_inherits_from_logging_formatter(self):
        formatter = StructuredFormatter(fmt="%(message)s")
        assert isinstance(formatter, logging.Formatter)


# ---------------------------------------------------------------------------
# RequestContextMiddleware
# ---------------------------------------------------------------------------

class TestRequestContextMiddleware:
    @pytest.mark.asyncio
    async def test_non_http_scope_passes_through(self):
        """Non-http/websocket scopes should be passed directly to app."""
        app = AsyncMock()
        middleware = RequestContextMiddleware(app)
        scope = {"type": "lifespan"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)
        app.assert_awaited_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_http_scope_sets_request_id(self):
        """HTTP requests should get a request ID set in the context var."""
        captured_id = None

        async def app(scope, receive, send):
            nonlocal captured_id
            captured_id = get_request_id()

        middleware = RequestContextMiddleware(app)
        scope = {"type": "http", "headers": []}
        await middleware(scope, AsyncMock(), AsyncMock())

        assert captured_id is not None
        assert len(captured_id) == 12  # uuid hex[:12]

    @pytest.mark.asyncio
    async def test_http_scope_uses_provided_request_id(self):
        """If x-request-id header is present, use it."""
        captured_id = None

        async def app(scope, receive, send):
            nonlocal captured_id
            captured_id = get_request_id()

        middleware = RequestContextMiddleware(app)
        scope = {
            "type": "http",
            "headers": [(b"x-request-id", b"custom-id-123")],
        }
        await middleware(scope, AsyncMock(), AsyncMock())
        assert captured_id == "custom-id-123"

    @pytest.mark.asyncio
    async def test_websocket_scope_sets_request_id(self):
        captured_id = None

        async def app(scope, receive, send):
            nonlocal captured_id
            captured_id = get_request_id()

        middleware = RequestContextMiddleware(app)
        scope = {"type": "websocket", "headers": []}
        await middleware(scope, AsyncMock(), AsyncMock())
        assert captured_id is not None
        assert len(captured_id) == 12

    @pytest.mark.asyncio
    async def test_response_header_added(self):
        """x-request-id should be added to response headers."""
        sent_messages = []

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        middleware = RequestContextMiddleware(app)
        scope = {
            "type": "http",
            "headers": [(b"x-request-id", b"resp-test")],
        }

        async def capture_send(msg):
            sent_messages.append(msg)

        await middleware(scope, AsyncMock(), capture_send)
        start_msg = sent_messages[0]
        header_keys = [h[0] for h in start_msg["headers"]]
        assert b"x-request-id" in header_keys

    @pytest.mark.asyncio
    async def test_response_header_value_matches_request_id(self):
        """The response x-request-id value should match the one used."""
        sent_messages = []

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "headers": []})

        middleware = RequestContextMiddleware(app)
        scope = {
            "type": "http",
            "headers": [(b"x-request-id", b"match-me")],
        }

        async def capture_send(msg):
            sent_messages.append(msg)

        await middleware(scope, AsyncMock(), capture_send)
        start_msg = sent_messages[0]
        header_dict = {h[0]: h[1] for h in start_msg["headers"]}
        assert header_dict[b"x-request-id"] == b"match-me"

    @pytest.mark.asyncio
    async def test_context_var_reset_after_request(self):
        """ContextVar should be restored after the middleware finishes."""
        token = _request_id_var.set("before")
        try:
            async def app(scope, receive, send):
                pass

            middleware = RequestContextMiddleware(app)
            scope = {"type": "http", "headers": []}
            await middleware(scope, AsyncMock(), AsyncMock())
            assert _request_id_var.get() == "before"
        finally:
            _request_id_var.reset(token)

    @pytest.mark.asyncio
    async def test_context_var_reset_on_app_error(self):
        """ContextVar should be restored even if app raises."""
        token = _request_id_var.set("safe")
        try:
            async def app(scope, receive, send):
                raise ValueError("app error")

            middleware = RequestContextMiddleware(app)
            scope = {"type": "http", "headers": []}
            with pytest.raises(ValueError, match="app error"):
                await middleware(scope, AsyncMock(), AsyncMock())
            assert _request_id_var.get() == "safe"
        finally:
            _request_id_var.reset(token)

    @pytest.mark.asyncio
    async def test_non_start_messages_not_modified(self):
        """Only http.response.start messages should get the header."""
        sent_messages = []

        async def app(scope, receive, send):
            await send({"type": "http.response.body", "body": b"data"})

        middleware = RequestContextMiddleware(app)
        scope = {"type": "http", "headers": []}

        async def capture_send(msg):
            sent_messages.append(msg)

        await middleware(scope, AsyncMock(), capture_send)
        body_msg = sent_messages[0]
        assert "headers" not in body_msg

    @pytest.mark.asyncio
    async def test_scope_without_headers_key_uses_empty(self):
        """If scope has no 'headers' key, should default to empty and generate ID."""
        captured_id = None

        async def app(scope, receive, send):
            nonlocal captured_id
            captured_id = get_request_id()

        middleware = RequestContextMiddleware(app)
        scope = {"type": "http"}  # no "headers" key
        await middleware(scope, AsyncMock(), AsyncMock())
        assert captured_id is not None
        assert len(captured_id) == 12

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scope_type", ["lifespan", "startup", "shutdown"])
    async def test_non_http_scope_types_pass_through(self, scope_type):
        """Various non-http scope types should all pass through."""
        app = AsyncMock()
        middleware = RequestContextMiddleware(app)
        scope = {"type": scope_type}
        await middleware(scope, AsyncMock(), AsyncMock())
        app.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_middleware_stores_app(self):
        app = AsyncMock()
        middleware = RequestContextMiddleware(app)
        assert middleware.app is app


# ---------------------------------------------------------------------------
# setup_structured_logging
# ---------------------------------------------------------------------------

class TestSetupStructuredLogging:
    def test_configures_root_logger(self):
        root = logging.getLogger()
        original_handlers = root.handlers[:]
        original_level = root.level
        try:
            setup_structured_logging()
            assert root.level == logging.INFO
            # At least one handler should exist
            assert len(root.handlers) > 0
            # Handler should use StructuredFormatter
            handler = root.handlers[-1]
            assert isinstance(handler.formatter, StructuredFormatter)
        finally:
            root.handlers = original_handlers
            root.level = original_level

    def test_adds_handler_when_none_exist(self):
        root = logging.getLogger()
        original_handlers = root.handlers[:]
        try:
            root.handlers = []
            setup_structured_logging()
            assert len(root.handlers) == 1
            assert isinstance(root.handlers[0], logging.StreamHandler)
            assert isinstance(root.handlers[0].formatter, StructuredFormatter)
        finally:
            root.handlers = original_handlers

    def test_updates_existing_handlers(self):
        root = logging.getLogger()
        original_handlers = root.handlers[:]
        try:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(message)s"))
            root.handlers = [handler]
            setup_structured_logging()
            assert isinstance(handler.formatter, StructuredFormatter)
        finally:
            root.handlers = original_handlers

    def test_does_not_duplicate_handlers(self):
        """Calling setup twice with existing handler should not add another."""
        root = logging.getLogger()
        original_handlers = root.handlers[:]
        try:
            handler = logging.StreamHandler()
            root.handlers = [handler]
            setup_structured_logging()
            count_after_first = len(root.handlers)
            setup_structured_logging()
            assert len(root.handlers) == count_after_first
        finally:
            root.handlers = original_handlers
