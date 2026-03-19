from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.platform_api.main import create_app
from platform_app.admission_policy import SQLiteAdmissionPolicyStore
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
from platform_app.workflow_events import resolve_workflow_events_db_path


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


def _policy_store(tmp_path) -> SQLiteAdmissionPolicyStore:
    db_path = resolve_workflow_events_db_path(str(Path(tmp_path) / "workflow_events.db"))
    return SQLiteAdmissionPolicyStore(db_path=db_path)


def test_job_admission_allowed_when_policy_permits(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    _policy_store(tmp_path).upsert_policy(
        client_id="client-a",
        is_enabled=True,
        max_jobs_per_day=5,
        max_active_jobs=2,
    )

    response = client.post(
        "/v1/platform/workflows/jobs",
        json={"client_id": "client-a", "workflow_key": "lead-enrichment"},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "received"


def test_job_admission_denied_when_client_disabled(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    _policy_store(tmp_path).upsert_policy(
        client_id="client-a",
        is_enabled=False,
        max_jobs_per_day=None,
        max_active_jobs=None,
    )

    response = client.post(
        "/v1/platform/workflows/jobs",
        json={"client_id": "client-a", "workflow_key": "lead-enrichment"},
    )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "client_disabled"


def test_job_admission_denied_when_daily_quota_exceeded(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    _policy_store(tmp_path).upsert_policy(
        client_id="client-a",
        is_enabled=True,
        max_jobs_per_day=1,
        max_active_jobs=None,
    )

    first = client.post(
        "/v1/platform/workflows/jobs",
        json={"client_id": "client-a", "workflow_key": "lead-enrichment"},
    )
    second = client.post(
        "/v1/platform/workflows/jobs",
        json={"client_id": "client-a", "workflow_key": "lead-enrichment"},
    )

    assert first.status_code == 201
    assert second.status_code == 429
    detail = second.json()["detail"]
    assert detail["code"] == "daily_quota_exceeded"


def test_job_admission_denied_when_active_job_limit_exceeded(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    _policy_store(tmp_path).upsert_policy(
        client_id="client-a",
        is_enabled=True,
        max_jobs_per_day=None,
        max_active_jobs=1,
    )

    first = client.post(
        "/v1/platform/workflows/jobs",
        json={"client_id": "client-a", "workflow_key": "lead-enrichment"},
    )
    second = client.post(
        "/v1/platform/workflows/jobs",
        json={"client_id": "client-a", "workflow_key": "lead-enrichment"},
    )

    assert first.status_code == 201
    assert second.status_code == 429
    detail = second.json()["detail"]
    assert detail["code"] == "active_job_limit_exceeded"


def test_job_admission_auth_still_required(monkeypatch, tmp_path) -> None:
    auth_api_keys_json = (
        '[{"key_id":"workflow-client","secret_hash":"'
        + hash_api_key_secret("policy-secret")
        + '","scopes":[]}]'
    )
    client = _client(
        monkeypatch,
        tmp_path,
        auth_mode="api_key",
        auth_api_keys_json=auth_api_keys_json,
    )
    _policy_store(tmp_path).upsert_policy(
        client_id="client-a",
        is_enabled=True,
        max_jobs_per_day=5,
        max_active_jobs=2,
    )

    response = client.post(
        "/v1/platform/workflows/jobs",
        json={"client_id": "client-a", "workflow_key": "lead-enrichment"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing X-API-Key"


def test_job_admission_default_allow_when_no_policy_exists(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)

    response = client.post(
        "/v1/platform/workflows/jobs",
        json={"client_id": "client-without-policy", "workflow_key": "lead-enrichment"},
    )

    assert response.status_code == 201
    assert response.json()["client_id"] == "client-without-policy"
