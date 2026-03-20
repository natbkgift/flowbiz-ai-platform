from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.platform_api.main import create_app
from platform_app.api_key_store import SQLiteAPIKeyStore
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
from platform_app.routes.platform import API_KEY_MANAGE_SCOPE


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


def _seed_manager_key(tmp_path):
    db_path = tmp_path / "auth.db"
    store = SQLiteAPIKeyStore(str(db_path), hash_secret_fn=hash_api_key_secret)
    issued = store.create_key(
        "manager",
        (API_KEY_MANAGE_SCOPE,),
        client_id="platform-admin",
        actor="bootstrap",
    )
    return store, issued


def _client(monkeypatch: pytest.MonkeyPatch, tmp_path) -> TestClient:
    monkeypatch.setenv("PLATFORM_AUTH_MODE", "api_key")
    monkeypatch.setenv("PLATFORM_AUTH_STORE_MODE", "sqlite")
    monkeypatch.setenv("PLATFORM_AUTH_SQLITE_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("PLATFORM_WORKFLOW_EVENTS_SQLITE_PATH", str(tmp_path / "workflow.db"))
    _clear_caches()
    return TestClient(create_app())


def test_api_key_issue_success_and_new_key_authenticates(monkeypatch, tmp_path) -> None:
    _, manager = _seed_manager_key(tmp_path)
    client = _client(monkeypatch, tmp_path)
    manager_headers = {"X-API-Key": f"{manager.key_id}:{manager.secret_plaintext}"}

    issue = client.post(
        "/v1/platform/api-keys",
        json={"client_id": "client-a", "scopes": ["platform:chat"]},
        headers=manager_headers,
    )

    assert issue.status_code == 201
    issue_data = issue.json()
    assert issue_data["status"] == "issued"
    assert issue_data["client_id"] == "client-a"
    assert issue_data["key_id"].startswith("client-a.")
    assert issue_data["api_key"].startswith(issue_data["key_id"] + ":")

    chat = client.post(
        "/v1/platform/chat",
        json={"prompt": "hello"},
        headers={"X-API-Key": issue_data["api_key"]},
    )
    assert chat.status_code == 200
    assert chat.json()["status"] == "ok"

def test_revoked_key_is_rejected_and_audited(monkeypatch, tmp_path) -> None:
    _, manager = _seed_manager_key(tmp_path)
    client = _client(monkeypatch, tmp_path)
    manager_headers = {"X-API-Key": f"{manager.key_id}:{manager.secret_plaintext}"}

    issue = client.post(
        "/v1/platform/api-keys",
        json={"client_id": "client-a", "scopes": ["platform:chat"]},
        headers=manager_headers,
    )
    key_data = issue.json()

    revoke = client.post(
        f"/v1/platform/api-keys/{key_data['key_id']}/revoke",
        headers=manager_headers,
    )
    assert revoke.status_code == 200
    assert revoke.json()["status"] == "revoked"

    chat = client.post(
        "/v1/platform/chat",
        json={"prompt": "hello"},
        headers={"X-API-Key": key_data["api_key"]},
    )
    assert chat.status_code == 401
    assert chat.json()["detail"] == "Invalid API key"

    audit = client.get("/v1/platform/api-keys/audit", headers=manager_headers)
    assert audit.status_code == 200
    actions = [item["action"] for item in audit.json()["events"] if item["key_id"] == key_data["key_id"]]
    assert actions == ["issued", "revoked"]


def test_api_key_audit_never_leaks_raw_secret(monkeypatch, tmp_path) -> None:
    _, manager = _seed_manager_key(tmp_path)
    client = _client(monkeypatch, tmp_path)
    manager_headers = {"X-API-Key": f"{manager.key_id}:{manager.secret_plaintext}"}

    issue = client.post(
        "/v1/platform/api-keys",
        json={"client_id": "client-a", "scopes": ["platform:chat"]},
        headers=manager_headers,
    )
    key_data = issue.json()
    secret_plaintext = key_data["api_key"].split(":", 1)[1]

    audit = client.get("/v1/platform/api-keys/audit", headers=manager_headers)
    assert audit.status_code == 200
    audit_data = audit.json()
    assert secret_plaintext not in audit.text
    assert all("metadata" in item for item in audit_data["events"])


def test_api_key_issue_requires_manage_scope(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "auth.db"
    store = SQLiteAPIKeyStore(str(db_path), hash_secret_fn=hash_api_key_secret)
    limited = store.create_key(
        "limited",
        ("platform:chat",),
        client_id="client-limited",
        actor="bootstrap",
    )
    client = _client(monkeypatch, tmp_path)

    issue = client.post(
        "/v1/platform/api-keys",
        json={"client_id": "client-a", "scopes": ["platform:chat"]},
        headers={"X-API-Key": f"{limited.key_id}:{limited.secret_plaintext}"},
    )
    assert issue.status_code == 403
    assert "platform:api_keys:manage" in issue.json()["detail"]
