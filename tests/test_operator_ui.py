from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.platform_api.main import create_app
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
from platform_app.operator_redaction import redact_payload
from platform_app.operator_proxy import OperatorProxy


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


def _enable_operator_ui(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("PLATFORM_ENV", "development")
    monkeypatch.setenv("PLATFORM_AUTH_MODE", "disabled")
    monkeypatch.setenv("PLATFORM_RATE_LIMIT_MODE", "noop")
    monkeypatch.setenv(
        "PLATFORM_WORKFLOW_EVENTS_SQLITE_PATH",
        str(tmp_path / "workflow_events.db"),
    )
    monkeypatch.setenv("PLATFORM_OPERATOR_UI_ENABLED", "true")
    monkeypatch.setenv("PLATFORM_OPERATOR_UI_TOKEN", "ops-test-token")
    monkeypatch.setenv("PLATFORM_CORE_BASE_URL", "http://core.test")
    _clear_caches()


def test_operator_ui_disabled_by_default(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PLATFORM_ENV", "development")
    monkeypatch.setenv("PLATFORM_AUTH_MODE", "disabled")
    monkeypatch.setenv("PLATFORM_RATE_LIMIT_MODE", "noop")
    monkeypatch.setenv(
        "PLATFORM_WORKFLOW_EVENTS_SQLITE_PATH",
        str(tmp_path / "workflow_events.db"),
    )
    monkeypatch.delenv("PLATFORM_OPERATOR_UI_ENABLED", raising=False)
    _clear_caches()
    client = TestClient(create_app())
    response = client.get("/internal/operator/")
    assert response.status_code == 404


def test_operator_index_requires_token(monkeypatch, tmp_path) -> None:
    _enable_operator_ui(monkeypatch, tmp_path)
    client = TestClient(create_app())
    no_token = client.get("/internal/operator/")
    assert no_token.status_code == 401
    bad_token = client.get(
        "/internal/operator/",
        headers={"Authorization": "Bearer wrong"},
    )
    assert bad_token.status_code == 401
    good = client.get(
        "/internal/operator/",
        headers={"Authorization": "Bearer ops-test-token"},
    )
    assert good.status_code == 200
    assert "FlowBiz AI Operator Console" in good.text


def test_operator_assets_served_only_with_token(monkeypatch, tmp_path) -> None:
    _enable_operator_ui(monkeypatch, tmp_path)
    client = TestClient(create_app())
    no_token = client.get("/internal/operator/assets/app.js")
    assert no_token.status_code == 401
    css = client.get(
        "/internal/operator/assets/style.css",
        headers={"Authorization": "Bearer ops-test-token"},
    )
    assert css.status_code == 200
    assert "color" in css.text


def test_operator_asset_path_traversal_blocked(monkeypatch, tmp_path) -> None:
    _enable_operator_ui(monkeypatch, tmp_path)
    client = TestClient(create_app())
    response = client.get(
        "/internal/operator/assets/..%2Fconfig.py",
        headers={"Authorization": "Bearer ops-test-token"},
    )
    assert response.status_code in {400, 404}


def test_operator_dashboard_proxy_redacts(
    monkeypatch, tmp_path
) -> None:
    _enable_operator_ui(monkeypatch, tmp_path)

    def fake_get(self, path, *, params=None, request_id=None, correlation_id=None):
        return {
            "project_count": 1,
            "task_count": 2,
            "queued": 1,
            "claimed": 0,
            "running": 0,
            "requires_approval": 1,
            "approved": 0,
            "rejected": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "recent_policy_denials": 0,
            "healthy_workers": 1,
            "stale_workers": 0,
            "service_token": "abcdef0123456789abcdef0123456789",
            "extra": {
                "OPENAI_API_KEY": "sk-secret-value",
                "Authorization": "Bearer 0123456789abcdefABCDEF",
            },
        }

    monkeypatch.setattr(OperatorProxy, "get", fake_get)
    client = TestClient(create_app())
    response = client.get(
        "/internal/operator/api/dashboard/summary",
        headers={"Authorization": "Bearer ops-test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["task_count"] == 2
    assert body["service_token"] == "[REDACTED]"
    assert body["extra"]["OPENAI_API_KEY"] == "[REDACTED]"
    assert body["extra"]["Authorization"] == "[REDACTED]"


def test_operator_task_paths_redacted(monkeypatch, tmp_path) -> None:
    _enable_operator_ui(monkeypatch, tmp_path)

    sample_task = {
        "id": "task_1",
        "project_id": "proj_1",
        "title": "Inspect repo",
        "action": "read_only",
        "status": "queued",
        "approval_required": False,
        "policy_decision": {
            "effect": "allowed",
            "reason": "Read-only task allowed by default",
            "action": "read_only",
        },
        "target_paths": ["README.md", ".env", "deploy/cert.pem", "src/main.py"],
        "created_at": "2026-05-10T12:00:00Z",
        "updated_at": "2026-05-10T12:00:00Z",
    }

    def fake_get(self, path, *, params=None, request_id=None, correlation_id=None):
        return sample_task

    monkeypatch.setattr(OperatorProxy, "get", fake_get)
    client = TestClient(create_app())
    response = client.get(
        "/internal/operator/api/tasks/task_1",
        headers={"Authorization": "Bearer ops-test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["target_paths"][0] == "README.md"
    assert body["target_paths"][1] == "[REDACTED]"
    assert body["target_paths"][2] == "[REDACTED]"
    assert body["target_paths"][3] == "src/main.py"


def test_operator_approval_proxied(monkeypatch, tmp_path) -> None:
    _enable_operator_ui(monkeypatch, tmp_path)

    captured: dict[str, Any] = {}

    def fake_post(self, path, *, json_body=None, request_id=None, correlation_id=None):
        captured["path"] = path
        captured["body"] = json_body
        return {
            "id": "task_1",
            "status": "approved",
            "policy_decision": {"effect": "requires_approval", "reason": "ok", "action": "deploy"},
            "approval_required": True,
            "project_id": "proj_1",
            "title": "Deploy x",
            "action": "deploy",
            "target_paths": [],
            "created_at": "2026-05-10T12:00:00Z",
            "updated_at": "2026-05-10T12:00:00Z",
        }

    monkeypatch.setattr(OperatorProxy, "post", fake_post)
    client = TestClient(create_app())
    response = client.post(
        "/internal/operator/api/tasks/task_1/approve",
        headers={"Authorization": "Bearer ops-test-token"},
        json={"operator_id": "ops-1", "reason": "verified"},
    )
    assert response.status_code == 200
    assert captured["path"].endswith("/v1/operator/tasks/task_1/approve")
    assert captured["body"]["operator_id"] == "ops-1"
    assert captured["body"]["reason"] == "verified"
    assert response.json()["status"] == "approved"


def test_redact_payload_pure() -> None:
    payload = {
        "instructions": "use Authorization: Bearer 0123456789abcdef0123456789abcdef please",
        "metadata": {
            "client_secret": "very-secret",
            "credentials": {"db_password": "pw1234"},
            "ok_field": "fine",
        },
        "target_paths": ["./.env", "ok.txt"],
        "long_hex": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
    }
    out = redact_payload(payload)
    assert out["metadata"]["client_secret"] == "[REDACTED]"
    assert out["metadata"]["credentials"] == "[REDACTED]"
    assert out["metadata"]["ok_field"] == "fine"
    assert out["target_paths"] == ["[REDACTED]", "ok.txt"]
    assert "[REDACTED]" in out["instructions"]
    assert out["long_hex"] == "[REDACTED]"


def test_operator_policy_endpoint_blocks_dangerous_capabilities(
    monkeypatch, tmp_path
) -> None:
    _enable_operator_ui(monkeypatch, tmp_path)
    client = TestClient(create_app())
    response = client.get(
        "/internal/operator/api/policy",
        headers={"Authorization": "Bearer ops-test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    cap = body["ui_capabilities"]
    assert cap["deploy_button"] is False
    assert cap["restart_button"] is False
    assert cap["shell_terminal"] is False
    assert cap["docker_action"] is False
    assert cap["ssh_action"] is False
    assert cap["write_file"] is False
    assert cap["rotate_secrets"] is False


def test_public_surface_unchanged_when_operator_ui_enabled(
    monkeypatch, tmp_path
) -> None:
    _enable_operator_ui(monkeypatch, tmp_path)
    client = TestClient(create_app())
    healthz = client.get("/healthz")
    readyz = client.get("/readyz")
    meta = client.get("/v1/meta")
    assert healthz.status_code == 200
    assert readyz.status_code == 200
    assert meta.status_code == 200
    operator_public = client.get("/v1/operator/tasks")
    assert operator_public.status_code == 404
    internal_worker = client.get("/internal/worker/tasks/claim")
    assert internal_worker.status_code == 404
