from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from apps.platform_api.main import create_app
from platform_app.auth import hash_api_key_secret
from platform_app.config import get_settings
from platform_app.deps import (
    get_admission_policy_store,
    get_api_key_store,
    get_auth_dependency,
    get_dispatch_record_store,
    get_job_record_store,
    get_llm_adapter,
    get_rate_limiter,
    get_runner_dispatcher,
    get_secret_provider_bundle,
    get_workflow_event_store,
)
from platform_app.dispatch_records import RunnerDispatchError


def _clear_caches() -> None:
    get_settings.cache_clear()
    get_secret_provider_bundle.cache_clear()
    get_llm_adapter.cache_clear()
    get_rate_limiter.cache_clear()
    get_api_key_store.cache_clear()
    get_auth_dependency.cache_clear()
    get_workflow_event_store.cache_clear()
    get_job_record_store.cache_clear()
    get_dispatch_record_store.cache_clear()
    get_runner_dispatcher.cache_clear()
    get_admission_policy_store.cache_clear()


@pytest.fixture(autouse=True)
def _reset_platform_caches():
    _clear_caches()
    yield
    _clear_caches()


class _FakeRunnerDispatcher:
    def __init__(self, behavior: str = "success") -> None:
        self.target_url = "https://runner.example/dispatch"
        self.callback_shared_secret = "callback-secret"
        self.behavior = behavior
        self.calls: list[dict[str, object]] = []

    def callback_url_for(self, job_id: str) -> str:
        return f"https://platform.example/v1/platform/workflows/jobs/{job_id}/callback"

    def issue_callback_token(self, *, job_id: str, dispatch_id: str) -> str:
        return f"token:{job_id}:{dispatch_id}"

    def dispatch(
        self,
        job,
        payload: dict[str, object],
        *,
        dispatch_id: str,
        callback_token: str,
    ) -> int:
        self.calls.append(
            {
                "job_id": job.job_id,
                "payload": payload,
                "dispatch_id": dispatch_id,
                "callback_url": self.callback_url_for(job.job_id),
                "callback_token": callback_token,
            }
        )
        if self.behavior == "timeout":
            raise RunnerDispatchError("Runner dispatch timed out")
        if self.behavior == "500":
            raise RunnerDispatchError("Runner dispatch returned status 500", response_code=500)
        return 202


def _client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    *,
    auth_mode: str = "disabled",
    auth_api_keys_json: str = "[]",
    dispatcher: _FakeRunnerDispatcher | None = None,
) -> TestClient:
    monkeypatch.setenv("PLATFORM_AUTH_MODE", auth_mode)
    monkeypatch.setenv("PLATFORM_AUTH_STORE_MODE", "json")
    monkeypatch.setenv("PLATFORM_AUTH_API_KEYS_JSON", auth_api_keys_json)
    monkeypatch.setenv(
        "PLATFORM_WORKFLOW_EVENTS_SQLITE_PATH",
        str(tmp_path / "workflow_events.db"),
    )
    monkeypatch.setenv(
        "PLATFORM_WORKFLOW_RUNNER_DISPATCH_URL",
        "https://runner.example/dispatch",
    )
    monkeypatch.setenv(
        "PLATFORM_PLATFORM_PUBLIC_BASE_URL",
        "https://platform.example",
    )
    monkeypatch.setenv(
        "PLATFORM_WORKFLOW_CALLBACK_SHARED_SECRET",
        "callback-secret",
    )
    _clear_caches()
    app = create_app()
    if dispatcher is not None:
        app.dependency_overrides[get_runner_dispatcher] = lambda: dispatcher
    return TestClient(app)


def _create_job(client: TestClient) -> str:
    response = client.post(
        "/v1/platform/workflows/jobs",
        json={"client_id": "client-a", "workflow_key": "lead-enrichment"},
    )
    assert response.status_code == 201
    return response.json()["job_id"]


def _create_job_with_headers(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        "/v1/platform/workflows/jobs",
        json={"client_id": "client-a", "workflow_key": "lead-enrichment"},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()["job_id"]


def test_dispatch_success_persists_sent_record(monkeypatch, tmp_path) -> None:
    dispatcher = _FakeRunnerDispatcher()
    client = _client(monkeypatch, tmp_path, dispatcher=dispatcher)
    job_id = _create_job(client)

    response = client.post(
        f"/v1/platform/workflows/jobs/{job_id}/dispatch",
        json={"payload": {"contact_id": "c-123"}},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["dispatch"]["job_id"] == job_id
    assert data["dispatch"]["status"] == "sent"
    assert data["dispatch"]["response_code"] == 202
    assert data["dispatch"]["target_url"] == "https://runner.example/dispatch"
    assert dispatcher.calls[0]["job_id"] == job_id
    assert dispatcher.calls[0]["dispatch_id"] == data["dispatch"]["dispatch_id"]
    assert dispatcher.calls[0]["callback_url"] == f"https://platform.example/v1/platform/workflows/jobs/{job_id}/callback"
    assert dispatcher.calls[0]["callback_token"] == f"token:{job_id}:{data['dispatch']['dispatch_id']}"

    listed = client.get(f"/v1/platform/workflows/jobs/{job_id}/dispatches")
    assert listed.status_code == 200
    listed_data = listed.json()
    assert listed_data["count"] == 1
    assert listed_data["dispatches"][0]["status"] == "sent"


def test_dispatch_failure_timeout_persists_failed_record(monkeypatch, tmp_path) -> None:
    dispatcher = _FakeRunnerDispatcher(behavior="timeout")
    client = _client(monkeypatch, tmp_path, dispatcher=dispatcher)
    job_id = _create_job(client)

    response = client.post(
        f"/v1/platform/workflows/jobs/{job_id}/dispatch",
        json={"payload": {"contact_id": "c-123"}},
    )

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["message"] == "Runner dispatch timed out"
    assert detail["dispatch"]["status"] == "failed"
    assert detail["dispatch"]["response_code"] is None


def test_dispatch_failure_http_500_persists_failed_record(monkeypatch, tmp_path) -> None:
    dispatcher = _FakeRunnerDispatcher(behavior="500")
    client = _client(monkeypatch, tmp_path, dispatcher=dispatcher)
    job_id = _create_job(client)

    response = client.post(
        f"/v1/platform/workflows/jobs/{job_id}/dispatch",
        json={"payload": {"contact_id": "c-123"}},
    )

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["dispatch"]["status"] == "failed"
    assert detail["dispatch"]["response_code"] == 500


def test_dispatch_rejects_missing_job(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path, dispatcher=_FakeRunnerDispatcher())
    response = client.post(
        "/v1/platform/workflows/jobs/job-missing/dispatch",
        json={"payload": {}},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Job record not found: job-missing"


def test_dispatch_requires_auth_when_enabled(monkeypatch, tmp_path) -> None:
    auth_api_keys_json = (
        '[{"key_id":"workflow-client","secret_hash":"'
        + hash_api_key_secret("dispatch-secret")
        + '","scopes":[]}]'
    )
    client = _client(
        monkeypatch,
        tmp_path,
        auth_mode="api_key",
        auth_api_keys_json=auth_api_keys_json,
        dispatcher=_FakeRunnerDispatcher(),
    )
    auth_headers = {"X-API-Key": "workflow-client:dispatch-secret"}
    job_id = _create_job_with_headers(client, auth_headers)

    response = client.post(
        f"/v1/platform/workflows/jobs/{job_id}/dispatch",
        json={"payload": {}},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing X-API-Key"


def test_multiple_dispatch_attempts_are_listed_for_job(monkeypatch, tmp_path) -> None:
    dispatcher = _FakeRunnerDispatcher()
    client = _client(monkeypatch, tmp_path, dispatcher=dispatcher)
    job_id = _create_job(client)

    first = client.post(
        f"/v1/platform/workflows/jobs/{job_id}/dispatch",
        json={"payload": {"attempt": 1}},
    )
    second = client.post(
        f"/v1/platform/workflows/jobs/{job_id}/dispatch",
        json={"payload": {"attempt": 2}},
    )

    assert first.status_code == 200
    assert second.status_code == 200

    listed = client.get(f"/v1/platform/workflows/jobs/{job_id}/dispatches")
    assert listed.status_code == 200
    data = listed.json()
    assert data["count"] == 2
    assert [item["payload"]["attempt"] for item in data["dispatches"]] == [1, 2]
    assert all(item["job_id"] == job_id for item in data["dispatches"])


def test_callback_accepts_valid_token_updates_projection_and_job_list(monkeypatch, tmp_path) -> None:
    dispatcher = _FakeRunnerDispatcher()
    client = _client(monkeypatch, tmp_path, dispatcher=dispatcher)
    job_id = _create_job(client)

    dispatch = client.post(
        f"/v1/platform/workflows/jobs/{job_id}/dispatch",
        json={"payload": {"contact_id": "c-123"}},
    )
    assert dispatch.status_code == 200
    dispatch_data = dispatch.json()["dispatch"]
    dispatch_id = dispatch_data["dispatch_id"]
    callback_token = dispatcher.calls[0]["callback_token"]
    occurred_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")

    callback = client.post(
        f"/v1/platform/workflows/jobs/{job_id}/callback",
        json={
            "job_id": job_id,
            "dispatch_id": dispatch_id,
            "status": "success",
            "occurred_at": occurred_at,
            "result_summary": {"records_processed": 12},
        },
        headers={"X-FlowBiz-Callback-Token": str(callback_token)},
    )
    assert callback.status_code == 200
    callback_data = callback.json()
    assert callback_data["outcome"] == "accepted"
    assert callback_data["current_status"] == "succeeded"
    assert callback_data["raw_status"] == "succeeded"

    projection = client.get(f"/v1/platform/workflows/jobs/{job_id}")
    assert projection.status_code == 200
    assert projection.json()["current_status"] == "succeeded"
    assert projection.json()["source"] == "runner_callback"

    listing = client.get("/v1/platform/workflows/jobs")
    assert listing.status_code == 200
    jobs = {item["job_id"]: item for item in listing.json()["jobs"]}
    assert jobs[job_id]["current_status"] == "succeeded"
    assert jobs[job_id]["raw_status"] == "succeeded"


def test_duplicate_callback_is_idempotent(monkeypatch, tmp_path) -> None:
    dispatcher = _FakeRunnerDispatcher()
    client = _client(monkeypatch, tmp_path, dispatcher=dispatcher)
    job_id = _create_job(client)

    dispatch = client.post(
        f"/v1/platform/workflows/jobs/{job_id}/dispatch",
        json={"payload": {"contact_id": "c-123"}},
    )
    dispatch_id = dispatch.json()["dispatch"]["dispatch_id"]
    callback_token = str(dispatcher.calls[0]["callback_token"])
    occurred_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    body = {
        "job_id": job_id,
        "dispatch_id": dispatch_id,
        "status": "in_progress",
        "occurred_at": occurred_at,
    }

    first = client.post(
        f"/v1/platform/workflows/jobs/{job_id}/callback",
        json=body,
        headers={"X-FlowBiz-Callback-Token": callback_token},
    )
    second = client.post(
        f"/v1/platform/workflows/jobs/{job_id}/callback",
        json=body,
        headers={"X-FlowBiz-Callback-Token": callback_token},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["outcome"] == "duplicate"

    events = client.get(f"/v1/platform/workflows/jobs/{job_id}/events")
    assert events.status_code == 200
    assert events.json()["count"] == 1


def test_callback_rejects_invalid_token(monkeypatch, tmp_path) -> None:
    dispatcher = _FakeRunnerDispatcher()
    client = _client(monkeypatch, tmp_path, dispatcher=dispatcher)
    job_id = _create_job(client)
    dispatch = client.post(
        f"/v1/platform/workflows/jobs/{job_id}/dispatch",
        json={"payload": {}},
    )
    dispatch_id = dispatch.json()["dispatch"]["dispatch_id"]

    callback = client.post(
        f"/v1/platform/workflows/jobs/{job_id}/callback",
        json={
            "job_id": job_id,
            "dispatch_id": dispatch_id,
            "status": "success",
            "occurred_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        },
        headers={"X-FlowBiz-Callback-Token": "wrong-token"},
    )
    assert callback.status_code == 401
    assert callback.json()["detail"] == "Invalid callback token"


def test_callback_rejects_stale_update(monkeypatch, tmp_path) -> None:
    dispatcher = _FakeRunnerDispatcher()
    client = _client(monkeypatch, tmp_path, dispatcher=dispatcher)
    job_id = _create_job(client)
    dispatch = client.post(
        f"/v1/platform/workflows/jobs/{job_id}/dispatch",
        json={"payload": {}},
    )
    dispatch_id = dispatch.json()["dispatch"]["dispatch_id"]
    callback_token = str(dispatcher.calls[0]["callback_token"])
    newer = datetime.now(timezone.utc)
    older = newer - timedelta(minutes=5)

    accepted = client.post(
        f"/v1/platform/workflows/jobs/{job_id}/callback",
        json={
            "job_id": job_id,
            "dispatch_id": dispatch_id,
            "status": "in_progress",
            "occurred_at": newer.isoformat(timespec="milliseconds"),
        },
        headers={"X-FlowBiz-Callback-Token": callback_token},
    )
    stale = client.post(
        f"/v1/platform/workflows/jobs/{job_id}/callback",
        json={
            "job_id": job_id,
            "dispatch_id": dispatch_id,
            "status": "in_progress",
            "occurred_at": older.isoformat(timespec="milliseconds"),
        },
        headers={"X-FlowBiz-Callback-Token": callback_token},
    )

    assert accepted.status_code == 200
    assert stale.status_code == 409
    assert stale.json()["detail"] == "Stale callback rejected"


def test_callback_rejects_malformed_payload(monkeypatch, tmp_path) -> None:
    dispatcher = _FakeRunnerDispatcher()
    client = _client(monkeypatch, tmp_path, dispatcher=dispatcher)
    job_id = _create_job(client)
    dispatch = client.post(
        f"/v1/platform/workflows/jobs/{job_id}/dispatch",
        json={"payload": {}},
    )
    dispatch_id = dispatch.json()["dispatch"]["dispatch_id"]
    callback_token = str(dispatcher.calls[0]["callback_token"])

    response = client.post(
        f"/v1/platform/workflows/jobs/{job_id}/callback",
        json={
            "job_id": job_id,
            "dispatch_id": dispatch_id,
            "status": "unsupported",
        },
        headers={"X-FlowBiz-Callback-Token": callback_token},
    )
    assert response.status_code == 422
