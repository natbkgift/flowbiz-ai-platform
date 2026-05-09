"""HTTP middleware for request correlation and access logging."""

from __future__ import annotations

import logging
import re
from time import perf_counter
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"
CORRELATION_ID_HEADER = "X-Correlation-ID"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_ACCESS_LOGGER = logging.getLogger("platform_app.access")


def normalize_request_id(value: str | None) -> str:
    if value and _REQUEST_ID_RE.fullmatch(value):
        return value
    return uuid4().hex


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request ID and emit one structured access event per request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = normalize_request_id(request.headers.get(REQUEST_ID_HEADER))
        correlation_id = normalize_request_id(
            request.headers.get(CORRELATION_ID_HEADER) or request_id
        )
        request.state.request_id = request_id
        request.state.correlation_id = correlation_id
        start = perf_counter()
        status_code = 500
        response: Response | None = None

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
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
            if response is not None:
                response.headers[REQUEST_ID_HEADER] = request_id
                response.headers[CORRELATION_ID_HEADER] = correlation_id
