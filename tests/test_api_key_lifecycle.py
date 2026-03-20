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
        json={
            "client_id": "client-a",
            "scopes": ["platform:chat"],
            "reason": "initial bootstrap issuance",
        },
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

    audit = client.get("/v1/platform/api-keys/audit", headers=manager_headers)
    assert audit.status_code == 200
    issued_event = next(
        item for item in audit.json()["events"] if item["action"] == "issued" and item["key_id"] == issue_data["key_id"]
    )
    assert issued_event["event_type"] == "issued"
    assert issued_event["actor"] == "admin_api"
    assert issued_event["actor_type"] == "api_key"
    assert issued_event["actor_id"] == "manager"
    assert issued_event["reason"] == "initial bootstrap issuance"

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
        json={"reason": "manual revoke after test"},
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
    events = [item for item in audit.json()["events"] if item["key_id"] == key_data["key_id"]]
    actions = [item["action"] for item in events]
    assert actions == ["issued", "revoked"]
    revoked_event = events[-1]
    assert revoked_event["event_type"] == "revoked"
    assert revoked_event["actor_type"] == "api_key"
    assert revoked_event["actor_id"] == "manager"
    assert revoked_event["reason"] == "manual revoke after test"


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


def test_api_key_rotate_success_old_key_rejected_new_key_accepted(monkeypatch, tmp_path) -> None:
    _, manager = _seed_manager_key(tmp_path)
    client = _client(monkeypatch, tmp_path)
    manager_headers = {"X-API-Key": f"{manager.key_id}:{manager.secret_plaintext}"}

    issue = client.post(
        "/v1/platform/api-keys",
        json={"client_id": "client-a", "scopes": ["platform:chat"]},
        headers=manager_headers,
    )
    assert issue.status_code == 201
    old_key_data = issue.json()

    rotate = client.post(
        f"/v1/platform/api-keys/{old_key_data['key_id']}/rotate",
        json={"reason": "routine credential rotation"},
        headers=manager_headers,
    )
    assert rotate.status_code == 200
    rotate_data = rotate.json()
    assert rotate_data["status"] == "rotated"
    assert rotate_data["key_id"] == old_key_data["key_id"]
    assert rotate_data["client_id"] == "client-a"
    assert rotate_data["scopes"] == ["platform:chat"]
    assert rotate_data["api_key"].startswith(old_key_data["key_id"] + ":")
    assert rotate_data["api_key"] != old_key_data["api_key"]
    assert old_key_data["api_key"].split(":", 1)[1] not in rotate.text

    old_chat = client.post(
        "/v1/platform/chat",
        json={"prompt": "hello"},
        headers={"X-API-Key": old_key_data["api_key"]},
    )
    assert old_chat.status_code == 401
    assert old_chat.json()["detail"] == "Invalid API key"

    new_chat = client.post(
        "/v1/platform/chat",
        json={"prompt": "hello"},
        headers={"X-API-Key": rotate_data["api_key"]},
    )
    assert new_chat.status_code == 200
    assert new_chat.json()["status"] == "ok"


def test_api_key_rotate_audit_contains_actor_reason_and_no_secret_leak(monkeypatch, tmp_path) -> None:
    _, manager = _seed_manager_key(tmp_path)
    client = _client(monkeypatch, tmp_path)
    manager_headers = {"X-API-Key": f"{manager.key_id}:{manager.secret_plaintext}"}

    issue = client.post(
        "/v1/platform/api-keys",
        json={"client_id": "client-a", "scopes": ["platform:chat"]},
        headers=manager_headers,
    )
    key_data = issue.json()
    old_secret = key_data["api_key"].split(":", 1)[1]

    rotate = client.post(
        f"/v1/platform/api-keys/{key_data['key_id']}/rotate",
        json={"reason": "suspected compromise"},
        headers=manager_headers,
    )
    assert rotate.status_code == 200
    new_secret = rotate.json()["api_key"].split(":", 1)[1]

    audit = client.get("/v1/platform/api-keys/audit", headers=manager_headers)
    assert audit.status_code == 200
    audit_data = audit.json()
    events = [item for item in audit_data["events"] if item["key_id"] == key_data["key_id"]]
    assert [item["event_type"] for item in events] == ["issued", "rotated", "revoked_by_rotation"]
    assert events[1]["actor"] == "admin_api"
    assert events[1]["actor_type"] == "api_key"
    assert events[1]["actor_id"] == "manager"
    assert events[1]["reason"] == "suspected compromise"
    assert events[2]["reason"] == "suspected compromise"
    assert old_secret not in audit.text
    assert new_secret not in audit.text
