from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.platform_api.main import create_app
from platform_app.auth import hash_api_key_secret
from platform_app.config import get_settings
from platform_app.deps import (
    get_admission_policy_store,
    get_api_key_store,
    get_auth_dependency,
    get_job_record_store,
    get_llm_adapter,
    get_rate_limiter,
    get_secret_provider_bundle,
    get_workflow_event_store,
)


def _clear_caches() -> None:
    get_settings.cache_clear()
    get_secret_provider_bundle.cache_clear()
    get_llm_adapter.cache_clear()
    get_rate_limiter.cache_clear()
    get_api_key_store.cache_clear()
    get_auth_dependency.cache_clear()
    get_workflow_event_store.cache_clear()
    get_job_record_store.cache_clear()
    get_admission_policy_store.cache_clear()


@pytest.fixture(autouse=True)
def _reset_platform_caches():
    _clear_caches()
    yield
    _clear_caches()


def _client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    *,
    auth_mode: str = "disabled",
    auth_api_keys_json: str = "[]",
) -> TestClient:
    monkeypatch.setenv("PLATFORM_AUTH_MODE", auth_mode)
    monkeypatch.setenv("PLATFORM_AUTH_STORE_MODE", "json")
    monkeypatch.setenv("PLATFORM_AUTH_API_KEYS_JSON", auth_api_keys_json)
    monkeypatch.setenv(
        "PLATFORM_WORKFLOW_EVENTS_SQLITE_PATH",
        str(tmp_path / "workflow_events.db"),
    )
    _clear_caches()
    return TestClient(create_app())


def test_job_creation_success(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    response = client.post(
        "/v1/platform/workflows/jobs",
        json={
            "client_id": "client-a",
            "workflow_key": "lead-enrichment",
            "input_payload": {"contact_id": "c-123"},
            "metadata": {"priority": "normal"},
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["job_id"]
    assert data["status"] == "received"
    assert data["client_id"] == "client-a"
    assert data["workflow_key"] == "lead-enrichment"
    assert data["input_payload"]["contact_id"] == "c-123"
    assert data["metadata"]["priority"] == "normal"


def test_job_creation_rejects_invalid_payload(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    response = client.post(
        "/v1/platform/workflows/jobs",
        json={"workflow_key": "lead-enrichment"},
    )

    assert response.status_code == 422
    assert any(item["loc"][-1] == "client_id" for item in response.json()["detail"])


def test_job_creation_requires_auth_when_enabled(monkeypatch, tmp_path) -> None:
    auth_api_keys_json = (
        '[{"key_id":"workflow-client","secret_hash":"'
        + hash_api_key_secret("job-secret")
        + '","scopes":[]}]'
    )
    client = _client(
        monkeypatch,
        tmp_path,
        auth_mode="api_key",
        auth_api_keys_json=auth_api_keys_json,
    )

    response = client.post(
        "/v1/platform/workflows/jobs",
        json={"client_id": "client-a", "workflow_key": "lead-enrichment"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing X-API-Key"


def test_job_lookup_returns_created_record(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    created = client.post(
        "/v1/platform/workflows/jobs",
        json={"client_id": "client-a", "workflow_key": "lead-enrichment"},
    )
    job_id = created.json()["job_id"]

    response = client.get(f"/v1/platform/workflows/jobs/{job_id}/record")
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == job_id
    assert data["status"] == "received"


def test_job_id_is_platform_generated_and_unique(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    first = client.post(
        "/v1/platform/workflows/jobs",
        json={"client_id": "client-a", "workflow_key": "lead-enrichment"},
    )
    second = client.post(
        "/v1/platform/workflows/jobs",
        json={"client_id": "client-a", "workflow_key": "lead-enrichment"},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["job_id"] != second.json()["job_id"]


def test_job_record_and_event_ledger_coexist_safely(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    created = client.post(
        "/v1/platform/workflows/jobs",
        json={"client_id": "client-a", "workflow_key": "lead-enrichment"},
    )
    job_id = created.json()["job_id"]

    event = client.post(
        "/v1/platform/workflows/events",
        json={
            "job_id": job_id,
            "client_id": "client-a",
            "workflow_key": "lead-enrichment",
            "status": "running",
            "execution_id": "exec-001",
        },
    )
    assert event.status_code == 201

    record = client.get(f"/v1/platform/workflows/jobs/{job_id}/record")
    projection = client.get(f"/v1/platform/workflows/jobs/{job_id}")

    assert record.status_code == 200
    assert record.json()["status"] == "received"
    assert projection.status_code == 200
    assert projection.json()["current_status"] == "running"
