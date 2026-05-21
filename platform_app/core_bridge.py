"""Helpers for integrating with flowbiz-ai-core without hard-coding internals."""

from __future__ import annotations

import time
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from urllib.parse import urljoin

import httpx

from platform_app.config import PlatformSettings


@dataclass(frozen=True)
class CoreClientConfig:
    base_url: str
    service_token: str = ""
    timeout_seconds: float = 2.0
    retry_attempts: int = 2
    retry_backoff_seconds: float = 0.2


class CoreClient:
    """Minimal internal client for safe core metadata and health checks."""

    def __init__(self, config: CoreClientConfig) -> None:
        self._config = config

    def is_reachable(
        self,
        *,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> bool:
        if not self._config.base_url.strip():
            return False

        attempts = max(1, self._config.retry_attempts)
        headers = self._request_headers(
            request_id=request_id,
            correlation_id=correlation_id,
        )
        url = urljoin(self._config.base_url.rstrip("/") + "/", "healthz")

        with httpx.Client(timeout=self._config.timeout_seconds) as client:
            for attempt in range(attempts):
                try:
                    response = client.get(url, headers=headers)
                    return response.status_code == 200
                except httpx.HTTPError:
                    if attempt == attempts - 1:
                        return False
                    time.sleep(max(0.0, self._config.retry_backoff_seconds))
        return False

    def _request_headers(
        self,
        *,
        request_id: str | None,
        correlation_id: str | None,
    ) -> dict[str, str]:
        headers: dict[str, str] = {}
        if request_id:
            headers["X-Request-ID"] = request_id
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id
        if self._config.service_token:
            headers["Authorization"] = f"Bearer {self._config.service_token}"
        return headers


def get_core_package_status() -> dict[str, str | bool]:
    try:
        core_version = version("flowbiz-ai-core")
        return {"installed": True, "version": core_version}
    except PackageNotFoundError:
        return {"installed": False, "version": "not-installed"}


def build_core_client(settings: PlatformSettings) -> CoreClient:
    return CoreClient(
        CoreClientConfig(
            base_url=settings.core_base_url,
            service_token=settings.core_service_token_value,
            timeout_seconds=settings.core_timeout_seconds,
            retry_attempts=settings.core_retry_attempts,
            retry_backoff_seconds=settings.core_retry_backoff_seconds,
        )
    )


def get_core_runtime_status(
    settings: PlatformSettings,
    *,
    request_id: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, bool]:
    return {
        "reachable": build_core_client(settings).is_reachable(
            request_id=request_id,
            correlation_id=correlation_id,
        )
    }
