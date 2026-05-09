from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from apps.platform_api.main import create_app
from platform_app.auth import hash_api_key_secret
from platform_app.config import PlatformSettings, get_settings
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
from platform_app.file_permissions import scan_platform_file_permissions
from platform_app.runtime import RuntimeConfigurationError, validate_runtime_configuration


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


def _ops_auth_json(secret: str = "ops-secret") -> str:
    return (
        '[{"key_id":"ops","secret_hash":"'
        + hash_api_key_secret(secret)
        + '","scopes":["platform:ops:read"]}]'
    )


def _client(monkeypatch: pytest.MonkeyPatch, tmp_path, *, env: str = "development"):
    monkeypatch.setenv("PLATFORM_ENV", env)
    monkeypatch.setenv("PLATFORM_AUTH_MODE", "api_key")
    monkeypatch.setenv("PLATFORM_AUTH_STORE_MODE", "json")
    monkeypatch.setenv("PLATFORM_AUTH_API_KEYS_JSON", _ops_auth_json())
    monkeypatch.setenv(
        "PLATFORM_WORKFLOW_EVENTS_SQLITE_PATH",
        str(tmp_path / "workflow_events.db"),
    )
    if env == "production":
        monkeypatch.setenv("PLATFORM_RATE_LIMIT_MODE", "redis")
        monkeypatch.setenv("PLATFORM_DOCS_ENABLED", "false")
    else:
        monkeypatch.setenv("PLATFORM_RATE_LIMIT_MODE", "noop")
        monkeypatch.delenv("PLATFORM_DOCS_ENABLED", raising=False)
    _clear_caches()
    return TestClient(create_app())


def test_production_docs_are_disabled(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path, env="production")
    response = client.get("/docs")
    assert response.status_code == 404


def test_production_runtime_rejects_docs_and_noop_rate_limit() -> None:
    settings = PlatformSettings(
        env="production",
        auth_mode="api_key",
        rate_limit_mode="noop",
        docs_enabled=True,
    )
    with pytest.raises(RuntimeConfigurationError) as exc:
        validate_runtime_configuration(settings)
    message = str(exc.value)
    assert "FastAPI docs must be disabled" in message
    assert "PLATFORM_RATE_LIMIT_MODE=redis" in message


def test_public_meta_is_safe_in_production(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path, env="production")
    response = client.get("/v1/meta")
    assert response.status_code == 200
    data = response.json()
    assert "env" not in data
    assert "modes" not in data
    assert set(data["core_dependency"].keys()) == {"installed"}
    assert "capabilities" in data


def test_readyz_and_request_id_header(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    response = client.get("/readyz", headers={"X-Request-ID": "req-test-123"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-test-123"
    data = response.json()
    assert data["status"] == "ready"
    assert data["checks"]["configuration_loaded"] is True


def test_ops_observability_and_metrics_require_api_key(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)

    missing = client.get("/v1/platform/ops/observability")
    assert missing.status_code == 401

    headers = {"X-API-Key": "ops:ops-secret"}
    observability = client.get("/v1/platform/ops/observability", headers=headers)
    metrics = client.get("/v1/platform/ops/metrics", headers=headers)
    assert observability.status_code == 200
    assert metrics.status_code == 200
    assert "recent_event_count" in metrics.json()["counters"]


def test_llm_smoke_is_protected_and_does_not_return_output(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    headers = {"X-API-Key": "ops:ops-secret"}
    response = client.post("/v1/platform/ops/llm/smoke", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["provider"] == "stub"
    assert "output" not in data
    assert "flowbiz-platform-smoke" not in response.text


def test_explicit_cors_policy_allows_configured_origin(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PLATFORM_CORS_ALLOWED_ORIGINS", "https://app.flowbiz.cloud")
    client = _client(monkeypatch, tmp_path)
    response = client.options(
        "/v1/meta",
        headers={
            "Origin": "https://app.flowbiz.cloud",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.flowbiz.cloud"


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode checks require chmod")
def test_permission_preflight_reports_bad_modes_without_file_contents(tmp_path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("SECRET_VALUE=do-not-print", encoding="utf-8")
    os.chmod(env_path, 0o644)

    backup = tmp_path / ".env.backup."
    backup.write_text("SECRET_VALUE=do-not-print", encoding="utf-8")
    os.chmod(backup, 0o600)

    data_dir = tmp_path / "platform_data"
    data_dir.mkdir()
    db_path = data_dir / "workflow_events.db"
    db_path.write_text("not-a-real-db", encoding="utf-8")
    os.chmod(db_path, 0o644)

    findings = scan_platform_file_permissions(tmp_path)
    rendered = "\n".join(item.message + " " + item.path for item in findings)
    assert "do-not-print" not in rendered
    bad_kinds = {item.kind for item in findings if item.status == "bad"}
    assert {".env", ".env.backup", "sqlite_db"} <= bad_kinds
