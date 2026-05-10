"""Internal proxy from platform to core for the AI Operator Console.

Browser clients never call core directly. Platform issues server-side
internal HTTP calls to core, then forwards a redacted payload to the UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx

from platform_app.config import PlatformSettings


class OperatorProxyError(Exception):
    """Raised when an internal call to core fails."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class OperatorProxyConfig:
    base_url: str
    service_token: str = ""
    timeout_seconds: float = 5.0


class OperatorProxy:
    """Minimal internal HTTP client to core operator endpoints."""

    def __init__(self, config: OperatorProxyConfig) -> None:
        self._config = config

    def _headers(
        self, *, request_id: str | None, correlation_id: str | None
    ) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if request_id:
            headers["X-Request-ID"] = request_id
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id
        if self._config.service_token:
            headers["Authorization"] = f"Bearer {self._config.service_token}"
        return headers

    def _url(self, path: str) -> str:
        if not self._config.base_url.strip():
            raise OperatorProxyError(503, "Core base URL is not configured")
        return urljoin(self._config.base_url.rstrip("/") + "/", path.lstrip("/"))

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> Any:
        url = self._url(path)
        headers = self._headers(
            request_id=request_id, correlation_id=correlation_id
        )
        try:
            with httpx.Client(timeout=self._config.timeout_seconds) as client:
                response = client.request(
                    method, url, params=params, json=json_body, headers=headers
                )
        except httpx.HTTPError as exc:
            raise OperatorProxyError(502, f"Core unreachable: {exc.__class__.__name__}") from exc

        if response.status_code >= 400:
            try:
                detail = response.json()
            except ValueError:
                detail = {"detail": response.text[:200]}
            message = "Core returned an error"
            if isinstance(detail, dict):
                if "detail" in detail and isinstance(detail["detail"], str):
                    message = detail["detail"]
                elif "error" in detail and isinstance(detail["error"], dict):
                    message = detail["error"].get("message", message)
            raise OperatorProxyError(response.status_code, message)

        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise OperatorProxyError(502, "Core returned non-JSON payload") from exc

    def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> Any:
        return self._request(
            "GET",
            path,
            params=params,
            request_id=request_id,
            correlation_id=correlation_id,
        )

    def post(
        self,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> Any:
        return self._request(
            "POST",
            path,
            json_body=json_body,
            request_id=request_id,
            correlation_id=correlation_id,
        )


def build_operator_proxy(settings: PlatformSettings) -> OperatorProxy:
    return OperatorProxy(
        OperatorProxyConfig(
            base_url=settings.core_base_url,
            service_token=settings.core_service_token_value,
            timeout_seconds=max(2.0, min(10.0, settings.core_timeout_seconds * 2)),
        )
    )
