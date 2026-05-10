from __future__ import annotations

import httpx

from platform_app.core_bridge import CoreClient, CoreClientConfig


def test_core_client_forwards_correlation_headers_and_retries(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get(self, url: str, *, headers: dict[str, str]) -> httpx.Response:
            calls.append({"url": url, "headers": headers, "timeout": self.timeout})
            if len(calls) == 1:
                raise httpx.ConnectError("connect failed")
            return httpx.Response(200)

    monkeypatch.setattr("platform_app.core_bridge.httpx.Client", FakeClient)
    monkeypatch.setattr("platform_app.core_bridge.time.sleep", lambda _: None)

    client = CoreClient(
        CoreClientConfig(
            base_url="http://flowbiz-ai-core-internal:8000",
            service_token="service-token",
            timeout_seconds=1.5,
            retry_attempts=2,
            retry_backoff_seconds=0,
        )
    )

    reachable = client.is_reachable(
        request_id="req-123",
        correlation_id="corr-123",
    )

    assert reachable is True
    assert len(calls) == 2
    assert calls[1]["url"] == "http://flowbiz-ai-core-internal:8000/healthz"
    assert calls[1]["timeout"] == 1.5
    assert calls[1]["headers"] == {
        "X-Request-ID": "req-123",
        "X-Correlation-ID": "corr-123",
        "Authorization": "Bearer service-token",
    }


def test_core_client_fails_closed_without_base_url() -> None:
    client = CoreClient(CoreClientConfig(base_url=""))
    assert client.is_reachable() is False
