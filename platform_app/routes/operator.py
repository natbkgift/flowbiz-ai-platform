"""Internal-only AI Operator Console routes.

These routes are mounted under ``/internal/operator/*``. They are gated by:

1. ``PLATFORM_OPERATOR_UI_ENABLED=1`` — feature flag (defaults to disabled).
2. ``PLATFORM_OPERATOR_UI_TOKEN`` — bearer token shared with internal callers.

The console UI is delivered as static HTML/CSS/JS that calls the JSON proxy
endpoints in this module. All proxy responses pass through
``redact_payload`` so secrets and denied paths can never reach the browser.

The Hermes worker remains read-only. Approve/reject endpoints update task
state in the core control plane only; they do not perform writes, deploys,
restarts, shells, container actions, or messaging.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from platform_app.config import PlatformSettings, get_settings
from platform_app.operator_proxy import (
    OperatorProxy,
    OperatorProxyError,
    build_operator_proxy,
)
from platform_app.operator_redaction import redact_payload

router = APIRouter(prefix="/internal/operator", tags=["internal-operator"])

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static" / "operator"
_PING_CLIENT = httpx.Client(timeout=2.0)


def _ensure_enabled(settings: PlatformSettings) -> None:
    if not settings.operator_ui_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Operator UI is disabled",
        )


def require_operator_token(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_operator_token: Annotated[
        str | None, Header(alias="X-FlowBiz-Operator-Token")
    ] = None,
) -> None:
    """Require the configured internal operator bearer token."""

    settings = get_settings()
    _ensure_enabled(settings)

    expected = settings.operator_ui_token_value
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Operator UI token is not configured",
        )

    provided = x_operator_token
    if authorization and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()

    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Operator token required",
        )

    request.state.operator_authenticated = True


def _proxy() -> OperatorProxy:
    return build_operator_proxy(get_settings())


def _request_ids(request: Request) -> tuple[str | None, str | None]:
    return (
        getattr(request.state, "request_id", None),
        getattr(request.state, "correlation_id", None),
    )


def _proxy_get(
    request: Request,
    path: str,
    *,
    params: dict[str, Any] | None = None,
) -> Any:
    request_id, correlation_id = _request_ids(request)
    try:
        payload = _proxy().get(
            path,
            params=params,
            request_id=request_id,
            correlation_id=correlation_id,
        )
    except OperatorProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return redact_payload(payload)


def _proxy_post(
    request: Request,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
) -> Any:
    request_id, correlation_id = _request_ids(request)
    try:
        payload = _proxy().post(
            path,
            json_body=json_body,
            request_id=request_id,
            correlation_id=correlation_id,
        )
    except OperatorProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return redact_payload(payload)


class ApprovalDecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator_id: str = Field(min_length=1, max_length=120)
    reason: str | None = Field(default=None, max_length=500)


@router.get("/", include_in_schema=False)
def operator_index(_: None = Depends(require_operator_token)) -> FileResponse:
    """Serve the operator console shell."""

    index_file = _STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=500, detail="Operator UI assets are missing")
    return FileResponse(index_file, media_type="text/html")


@router.get("/assets/{filename}", include_in_schema=False)
def operator_asset(
    filename: str, _: None = Depends(require_operator_token)
) -> FileResponse:
    """Serve a single console asset file."""

    if Path(filename).name != filename or filename.startswith("."):
        raise HTTPException(status_code=404, detail="Asset not found")
    target = _STATIC_DIR / filename
    if not target.resolve().is_relative_to(_STATIC_DIR.resolve()):
        raise HTTPException(status_code=404, detail="Asset not found")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    media = "text/css" if filename.endswith(".css") else (
        "application/javascript" if filename.endswith(".js") else "text/plain"
    )
    return FileResponse(target, media_type=media)


@router.get("/api/health")
def operator_health(
    request: Request, _: None = Depends(require_operator_token)
) -> dict[str, Any]:
    """Aggregated health card data for the operator console."""

    settings = get_settings()
    request_id, correlation_id = _request_ids(request)

    core_health: dict[str, Any] = {"reachable": False, "status": "unreachable"}
    try:
        result = _proxy().get(
            "/healthz", request_id=request_id, correlation_id=correlation_id
        )
        if isinstance(result, dict):
            core_health = {"reachable": True, "status": "ok", "service": result.get("service")}
    except OperatorProxyError as exc:
        core_health["error_status"] = exc.status_code

    legacy_status = _ping(settings.operator_ui_legacy_upstream_health_url)
    canary_status = _ping(settings.operator_ui_public_canary_health_url)

    return redact_payload(
        {
            "platform": {"reachable": True, "status": "ok"},
            "core": core_health,
            "public_canary": canary_status,
            "legacy_upstream": legacy_status,
            "warnings": _build_warnings(legacy_status),
        }
    )


def _ping(url: str) -> dict[str, Any]:
    if not url.strip():
        return {"configured": False, "status": "not_configured"}
    try:
        response = _PING_CLIENT.get(url)
        return {
            "configured": True,
            "status": "ok" if response.status_code == 200 else f"http_{response.status_code}",
            "http_status": response.status_code,
        }
    except httpx.HTTPError as exc:
        return {
            "configured": True,
            "status": "unreachable",
            "error": exc.__class__.__name__,
        }


def _build_warnings(legacy_status: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if legacy_status.get("http_status") == 502:
        warnings.append(
            "flowbiz.cloud/api legacy upstream returned 502 — investigate before exposing new routes"
        )
    return warnings


@router.get("/api/dashboard/summary")
def dashboard_summary(
    request: Request, _: None = Depends(require_operator_token)
) -> Any:
    return _proxy_get(request, "/v1/operator/dashboard/summary")


@router.get("/api/projects")
def list_projects(
    request: Request, _: None = Depends(require_operator_token)
) -> Any:
    return _proxy_get(request, "/v1/operator/projects")


@router.get("/api/tasks")
def list_tasks(
    request: Request,
    _: None = Depends(require_operator_token),
    task_status: Annotated[str | None, Query(alias="status")] = None,
    project_id: str | None = None,
) -> Any:
    params: dict[str, Any] = {}
    if task_status:
        params["status"] = task_status
    if project_id:
        params["project_id"] = project_id
    return _proxy_get(request, "/v1/operator/tasks", params=params)


@router.get("/api/tasks/{task_id}")
def get_task(
    task_id: str,
    request: Request,
    _: None = Depends(require_operator_token),
) -> Any:
    return _proxy_get(request, f"/v1/operator/tasks/{task_id}")


@router.get("/api/events")
def list_events(
    request: Request,
    _: None = Depends(require_operator_token),
    task_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    params: dict[str, Any] = {"limit": limit}
    if task_id:
        params["task_id"] = task_id
    return _proxy_get(request, "/v1/operator/events", params=params)


@router.get("/api/audit")
def list_audit(
    request: Request,
    _: None = Depends(require_operator_token),
    task_id: str | None = None,
    project_id: str | None = None,
    event_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    params: dict[str, Any] = {"limit": limit}
    if task_id:
        params["task_id"] = task_id
    if project_id:
        params["project_id"] = project_id
    if event_type:
        params["event_type"] = event_type
    return _proxy_get(request, "/v1/operator/audit", params=params)


@router.get("/api/approvals")
def list_approvals(
    request: Request,
    _: None = Depends(require_operator_token),
    task_id: str | None = None,
    decision: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    params: dict[str, Any] = {"limit": limit}
    if task_id:
        params["task_id"] = task_id
    if decision:
        params["decision"] = decision
    return _proxy_get(request, "/v1/operator/approvals", params=params)


@router.get("/api/workers/summary")
def workers_summary(
    request: Request, _: None = Depends(require_operator_token)
) -> Any:
    return _proxy_get(request, "/v1/operator/workers/summary")


@router.post("/api/tasks/{task_id}/approve")
def approve_task(
    task_id: str,
    payload: ApprovalDecisionBody,
    request: Request,
    _: None = Depends(require_operator_token),
) -> Any:
    return _proxy_post(
        request,
        f"/v1/operator/tasks/{task_id}/approve",
        json_body=payload.model_dump(exclude_none=True),
    )


@router.post("/api/tasks/{task_id}/reject")
def reject_task(
    task_id: str,
    payload: ApprovalDecisionBody,
    request: Request,
    _: None = Depends(require_operator_token),
) -> Any:
    return _proxy_post(
        request,
        f"/v1/operator/tasks/{task_id}/reject",
        json_body=payload.model_dump(exclude_none=True),
    )


@router.get("/api/policy")
def policy_constraints(_: None = Depends(require_operator_token)) -> JSONResponse:
    """Static description of the read-only policy boundary, for the UI."""

    return JSONResponse(
        {
            "read_only_actions": ["read_only"],
            "approval_required_actions": [
                "write_file",
                "deploy",
                "restart_service",
                "send_external_message",
            ],
            "blocked_actions": ["delete_file", "docker_socket_access"],
            "allowed_runtime_modes": [
                "repo_inventory",
                "docs_summary",
                "dependency_summary",
                "architecture_report",
            ],
            "ui_capabilities": {
                "approve_required_action": True,
                "reject_required_action": True,
                "deploy_button": False,
                "restart_button": False,
                "shell_terminal": False,
                "docker_action": False,
                "ssh_action": False,
                "write_file": False,
                "rotate_secrets": False,
            },
            "warnings": [
                "Approving a write/deploy action does NOT cause execution under the current "
                "read-only Hermes worker. Approval changes task state only."
            ],
        }
    )
