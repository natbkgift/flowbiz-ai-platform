"""HTTP middleware for request correlation and access logging."""

from __future__ import annotations

import logging
import re
from time import perf_counter
from typing import Any
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
CORRELATION_ID_HEADER = "X-Correlation-ID"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_ACCESS_LOGGER = logging.getLogger("platform_app.access")


def normalize_request_id(value: str | None) -> str:
    if value and _REQUEST_ID_RE.fullmatch(value):
        return value
    return uuid4().hex


class RequestContextMiddleware:
    """Attach a request ID and emit one structured access event per request.

    Implemented as a pure ASGI middleware to avoid BaseHTTPMiddleware's
    response-buffering overhead and context-propagation limitations.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        scope.setdefault("state", {})
        request = Request(scope)
        request_id = normalize_request_id(request.headers.get(REQUEST_ID_HEADER))
        correlation_id = normalize_request_id(
            request.headers.get(CORRELATION_ID_HEADER) or request_id
        )
        scope["state"]["request_id"] = request_id
        scope["state"]["correlation_id"] = correlation_id
        start = perf_counter()
        status_code = 500

        async def send_with_headers(message: Any) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers.append(REQUEST_ID_HEADER, request_id)
                headers.append(CORRELATION_ID_HEADER, correlation_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            duration_ms = round((perf_counter() - start) * 1000, 1)
            _ACCESS_LOGGER.info(
                "request_complete",
                extra={
                    "request_id": request_id,
                    "correlation_id": correlation_id,
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
