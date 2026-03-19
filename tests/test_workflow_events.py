from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from apps.platform_api.main import create_app
from platform_app.auth import hash_api_key_secret
from platform_app.config import get_settings
from platform_app.deps import (
    get_admission_policy_store,
    get_api_key_store,
    get_auth_dependency,
    get_llm_adapter,
    get_rate_limiter,
    get_secret_provider_bundle,
    get_workflow_event_store,
)
from platform_app.workflow_events import WorkflowEventRecord, project_job_state


def _clear_caches() -> None:
    get_settings.cache_clear()
    get_secret_provider_bundle.cache_clear()
    get_llm_adapter.cache_clear()
    get_rate_limiter.cache_clear()
    get_api_key_store.cache_clear()
    get_auth_dependency.cache_clear()
    get_workflow_event_store.cache_clear()
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


def test_workflow_event_intake_persists_and_lookup_by_job_id(monkeypatch, tmp_path) -> None:
    auth_api_keys_json = (
        '[{"key_id":"workflow-callback","secret_hash":"'
        + hash_api_key_secret("callback-secret")
        + '","scopes":[]}]'
    )
    client = _client(
        monkeypatch,
        tmp_path,
        auth_mode="api_key",
        auth_api_keys_json=auth_api_keys_json,
    )
    headers = {"X-API-Key": "workflow-callback:callback-secret"}
    payload = {
        "job_id": "job-123",
        "client_id": "client-a",
        "workflow_key": "lead-enrichment",
        "execution_id": "exec-001",
        "status": "completed",
        "source": "n8n",
        "callback_type": "workflow.finished",
        "output_ref": {"artifact_id": "art-123"},
    }

    intake = client.post("/v1/platform/workflows/events", json=payload, headers=headers)
    assert intake.status_code == 201
    intake_data = intake.json()
    assert intake_data["status"] == "accepted"
    assert intake_data["record"]["job_id"] == "job-123"
    assert intake_data["record"]["raw_payload"]["callback_type"] == "workflow.finished"
    assert intake_data["record"]["source"] == "n8n"

    db_path = tmp_path / "workflow_events.db"
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT job_id, client_id, workflow_key, execution_id, status, source FROM workflow_events"
        ).fetchone()
    assert row == (
        "job-123",
        "client-a",
        "lead-enrichment",
        "exec-001",
        "completed",
        "n8n",
    )

    lookup = client.get("/v1/platform/workflows/jobs/job-123/events", headers=headers)
    assert lookup.status_code == 200
    lookup_data = lookup.json()
    assert lookup_data["status"] == "ok"
    assert lookup_data["job_id"] == "job-123"
    assert lookup_data["count"] == 1
    assert lookup_data["records"][0]["raw_payload"]["output_ref"]["artifact_id"] == "art-123"


def test_workflow_event_intake_rejects_missing_and_invalid_auth(monkeypatch, tmp_path) -> None:
    auth_api_keys_json = (
        '[{"key_id":"workflow-callback","secret_hash":"'
        + hash_api_key_secret("callback-secret")
        + '","scopes":[]}]'
    )
    client = _client(
        monkeypatch,
        tmp_path,
        auth_mode="api_key",
        auth_api_keys_json=auth_api_keys_json,
    )
    payload = {
        "job_id": "job-123",
        "client_id": "client-a",
        "workflow_key": "lead-enrichment",
        "status": "completed",
    }

    missing = client.post("/v1/platform/workflows/events", json=payload)
    assert missing.status_code == 401
    assert missing.json()["detail"] == "Missing X-API-Key"

    invalid = client.post(
        "/v1/platform/workflows/events",
        json=payload,
        headers={"X-API-Key": "workflow-callback:wrong-secret"},
    )
    assert invalid.status_code == 401
    assert invalid.json()["detail"] == "Invalid API key"


def test_workflow_event_lookup_returns_multiple_records_for_job(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)

    first = {
        "job_id": "job-lookup",
        "client_id": "client-a",
        "workflow_key": "lead-enrichment",
        "status": "queued",
        "sequence": 1,
    }
    second = {
        "job_id": "job-lookup",
        "client_id": "client-a",
        "workflow_key": "lead-enrichment",
        "status": "running",
        "sequence": 2,
    }
    other = {
        "job_id": "job-other",
        "client_id": "client-a",
        "workflow_key": "lead-enrichment",
        "status": "completed",
    }

    assert client.post("/v1/platform/workflows/events", json=first).status_code == 201
    assert client.post("/v1/platform/workflows/events", json=second).status_code == 201
    assert client.post("/v1/platform/workflows/events", json=other).status_code == 201

    lookup = client.get("/v1/platform/workflows/jobs/job-lookup/events")
    assert lookup.status_code == 200
    data = lookup.json()
    assert data["count"] == 2
    assert [item["status"] for item in data["records"]] == ["queued", "running"]
    assert [item["raw_payload"]["sequence"] for item in data["records"]] == [1, 2]


def test_workflow_event_intake_validation_failure_is_predictable(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    response = client.post(
        "/v1/platform/workflows/events",
        json={
            "client_id": "client-a",
            "workflow_key": "lead-enrichment",
            "status": "completed",
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(item["loc"][-1] == "job_id" for item in detail)


def test_projected_job_state_visible_after_first_event(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    payload = {
        "job_id": "job-projection-1",
        "client_id": "client-a",
        "workflow_key": "lead-enrichment",
        "status": "queued",
        "source": "n8n",
    }

    assert client.post("/v1/platform/workflows/events", json=payload).status_code == 201

    response = client.get("/v1/platform/workflows/jobs/job-projection-1")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["job_id"] == "job-projection-1"
    assert data["current_status"] == "accepted"
    assert data["raw_status"] == "queued"
    assert data["client_id"] == "client-a"
    assert data["workflow_key"] == "lead-enrichment"
    assert data["source"] == "n8n"
    assert data["event_count"] == 1


def test_projected_job_state_updates_with_later_events(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)

    first = {
        "job_id": "job-projection-2",
        "client_id": "client-a",
        "workflow_key": "lead-enrichment",
        "execution_id": "exec-001",
        "status": "queued",
        "source": "n8n",
    }
    second = {
        "job_id": "job-projection-2",
        "client_id": "client-a",
        "workflow_key": "lead-enrichment",
        "status": "running",
    }
    third = {
        "job_id": "job-projection-2",
        "client_id": "client-a",
        "workflow_key": "lead-enrichment",
        "status": "completed",
        "source": "worker-sync",
    }

    assert client.post("/v1/platform/workflows/events", json=first).status_code == 201
    assert client.post("/v1/platform/workflows/events", json=second).status_code == 201
    assert client.post("/v1/platform/workflows/events", json=third).status_code == 201

    response = client.get("/v1/platform/workflows/jobs/job-projection-2")
    assert response.status_code == 200
    data = response.json()
    assert data["current_status"] == "succeeded"
    assert data["raw_status"] == "completed"
    assert data["execution_id"] == "exec-001"
    assert data["source"] == "worker-sync"
    assert data["event_count"] == 3


def test_projected_job_state_unknown_status_is_safe(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    payload = {
        "job_id": "job-projection-3",
        "client_id": "client-a",
        "workflow_key": "lead-enrichment",
        "status": "paused_by_runner",
    }

    assert client.post("/v1/platform/workflows/events", json=payload).status_code == 201

    response = client.get("/v1/platform/workflows/jobs/job-projection-3")
    assert response.status_code == 200
    data = response.json()
    assert data["current_status"] == "unknown"
    assert data["raw_status"] == "paused_by_runner"


def test_projected_job_state_returns_404_for_unknown_job(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    response = client.get("/v1/platform/workflows/jobs/job-missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found: job-missing"


def test_projected_job_state_rejects_missing_auth_when_enabled(monkeypatch, tmp_path) -> None:
    auth_api_keys_json = (
        '[{"key_id":"workflow-callback","secret_hash":"'
        + hash_api_key_secret("callback-secret")
        + '","scopes":[]}]'
    )
    client = _client(
        monkeypatch,
        tmp_path,
        auth_mode="api_key",
        auth_api_keys_json=auth_api_keys_json,
    )

    response = client.get("/v1/platform/workflows/jobs/job-projection-auth")
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing X-API-Key"


def test_project_job_state_uses_received_at_then_id_for_latest_event() -> None:
    events = [
        WorkflowEventRecord(
            id=10,
            job_id="job-ordering",
            client_id="client-a",
            workflow_key="lead-enrichment",
            execution_id="exec-001",
            status="running",
            received_at="2026-03-19T10:00:00.000+00:00",
            raw_payload={"status": "running"},
            source="source-a",
        ),
        WorkflowEventRecord(
            id=11,
            job_id="job-ordering",
            client_id="client-a",
            workflow_key="lead-enrichment",
            execution_id=None,
            status="completed",
            received_at="2026-03-19T10:00:00.000+00:00",
            raw_payload={"status": "completed"},
            source=None,
        ),
    ]

    projection = project_job_state(events)
    assert projection is not None
    assert projection.raw_status == "completed"
    assert projection.current_status == "succeeded"
    assert projection.execution_id == "exec-001"
    assert projection.source == "source-a"
