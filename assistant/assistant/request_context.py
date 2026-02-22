"""
Request Context - Request-ID Tracing + Structured Logging Middleware.

Jeder Request bekommt eine eindeutige Request-ID die durch alle
Log-Eintraege propagiert wird. Ermoeglicht Korrelation von Logs
ueber mehrere Komponenten hinweg.
"""

import logging
import time
import uuid
from contextvars import ContextVar
from typing import Optional

from fastapi import Request

# ContextVar fuer Request-ID (thread-safe, asyncio-kompatibel)
_request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    """Gibt die aktuelle Request-ID zurueck."""
    return _request_id_var.get()


class RequestContextMiddleware:
    """FastAPI Middleware die jedem Request eine ID zuweist und Logging anreichert."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # Request-ID aus Header oder neu generieren
        headers = dict(scope.get("headers", []))
        request_id = ""
        for key, value in headers.items():
            if key == b"x-request-id":
                request_id = value.decode("utf-8", errors="replace")
                break

        if not request_id:
            request_id = uuid.uuid4().hex[:12]

        # In ContextVar setzen
        token = _request_id_var.set(request_id)

        # Request-ID als Response-Header mitsenden
        original_send = send

        async def send_with_request_id(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append([b"x-request-id", request_id.encode()])
                message["headers"] = headers
            await original_send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            _request_id_var.reset(token)


class StructuredFormatter(logging.Formatter):
    """Log-Formatter der Request-ID und strukturierte Felder hinzufuegt.

    Output-Format (human-readable mit Request-ID):
        12:34:56 [module] INFO [req-abc123] Message here
    """

    def format(self, record: logging.LogRecord) -> str:
        request_id = _request_id_var.get()
        if request_id:
            record.request_id = f"[req-{request_id}] "
        else:
            record.request_id = ""

        return super().format(record)


def setup_structured_logging() -> None:
    """Konfiguriert Structured Logging fuer die gesamte Anwendung."""
    fmt = "%(asctime)s [%(name)s] %(levelname)s: %(request_id)s%(message)s"
    formatter = StructuredFormatter(fmt=fmt, datefmt="%H:%M:%S")

    # Root-Logger konfigurieren
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Bestehende Handler aktualisieren
    for handler in root.handlers:
        handler.setFormatter(formatter)

    # Falls keine Handler existieren, einen hinzufuegen
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        root.addHandler(handler)
