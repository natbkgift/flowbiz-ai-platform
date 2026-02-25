from __future__ import annotations

from fastapi.testclient import TestClient

from apps.platform_api.main import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_healthz() -> None:
    client = _client()
    r = client.get("/healthz")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_meta() -> None:
    client = _client()
    r = client.get("/v1/meta")
    assert r.status_code == 200
    data = r.json()
    assert "core_dependency" in data
    assert "modes" in data


def test_platform_chat_stub() -> None:
    client = _client()
    r = client.post("/v1/platform/chat", json={"prompt": "hello"})
    assert r.status_code == 200
    assert "X-RateLimit-Limit" in r.headers
    assert "X-RateLimit-Remaining" in r.headers
    assert "X-RateLimit-Reset" in r.headers
    data = r.json()
    assert data["status"] == "ok"
    assert data["data"]["provider"] == "stub"
