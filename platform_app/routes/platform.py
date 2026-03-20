"""Platform-facing endpoints that wrap platform concerns around LLM execution."""

from __future__ import annotations

import time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from platform_app.auth import APIPrincipal, require_scopes
from platform_app.api_key_store import APIKeyAuditEvent, SQLiteAPIKeyStore
from platform_app.deps import (
    get_llm_adapter,
    get_required_api_key_store,
    get_request_principal,
    get_rate_limiter,
)
from platform_app.llm import ChatRequest, LLMProviderError
from platform_app.rate_limit import apply_rate_limit_headers, enforce_rate_limit

router = APIRouter(prefix="/v1/platform")

API_KEY_MANAGE_SCOPE = "platform:api_keys:manage"


class APIKeyIssueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(min_length=1)
    scopes: tuple[str, ...] = ("platform:chat",)


class APIKeyIssueResponse(BaseModel):
    status: str = "issued"
    client_id: str
    key_id: str
    api_key: str
    scopes: tuple[str, ...]


class APIKeyRevokeResponse(BaseModel):
    status: str = "revoked"
    key_id: str


class APIKeyAuditEventResponse(BaseModel):
    id: int
    client_id: str | None
    action: str
    key_id: str
    actor: str
    created_at: str
    metadata: dict[str, object] | None = None


class APIKeyAuditResponse(BaseModel):
    status: str = "ok"
    count: int
    events: list[APIKeyAuditEventResponse]


def _audit_to_response(event: APIKeyAuditEvent) -> APIKeyAuditEventResponse:
    return APIKeyAuditEventResponse(
        id=event.id,
        client_id=event.client_id,
        action=event.action,
        key_id=event.key_id,
        actor=event.actor,
        created_at=event.created_at,
        metadata=event.metadata,
    )


@router.post("/chat")
def platform_chat(
    body: ChatRequest,
    request: Request,
    response: Response,
    principal: APIPrincipal = Depends(get_request_principal),
):
    start = time.perf_counter()
    require_scopes(principal, ("platform:chat",))
    limiter = get_rate_limiter()
    decision = enforce_rate_limit(limiter, principal, "platform:chat")
    apply_rate_limit_headers(response, decision)
    adapter = get_llm_adapter()

    try:
        resp = adapter.chat(body)
    except NotImplementedError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(exc),
        ) from exc
    except LLMProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    obs = getattr(request.app.state, "observability", None)
    if obs is not None:
        obs.record(route="/v1/platform/chat", status_code=200, duration_ms=duration_ms)

    return {
        "status": "ok",
        "principal": principal.key_id,
        "rate_limit_remaining": decision.remaining,
        "data": resp.model_dump(),
        "duration_ms": duration_ms,
    }


@router.get("/ops/observability")
def observability_snapshot(request: Request) -> dict[str, object]:
    obs = getattr(request.app.state, "observability", None)
    if obs is None:
        return {"status": "disabled"}
    return {
        "status": "ok",
        "metrics_mode": obs.metrics_mode,
        "tracing_mode": obs.tracing_mode,
        "alerts_mode": obs.alerts_mode,
        "recent_event_count": len(obs.recent_events),
    }


@router.post("/api-keys", response_model=APIKeyIssueResponse, status_code=status.HTTP_201_CREATED)
def issue_api_key(
    body: APIKeyIssueRequest,
    request: Request,
    principal: APIPrincipal = Depends(get_request_principal),
    store: SQLiteAPIKeyStore = Depends(get_required_api_key_store),
) -> APIKeyIssueResponse:
    start = time.perf_counter()
    require_scopes(principal, (API_KEY_MANAGE_SCOPE,))
    key_id = f"{body.client_id}.{uuid4().hex[:12]}"
    issued = store.create_key(
        key_id=key_id,
        scopes=body.scopes,
        client_id=body.client_id,
        actor="admin_api",
        metadata={"issued_by": principal.key_id},
    )
    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    obs = getattr(request.app.state, "observability", None)
    if obs is not None:
        obs.record(route="/v1/platform/api-keys", status_code=201, duration_ms=duration_ms)

    return APIKeyIssueResponse(
        client_id=body.client_id,
        key_id=issued.key_id,
        api_key=f"{issued.key_id}:{issued.secret_plaintext}",
        scopes=issued.scopes,
    )


@router.post("/api-keys/{key_id}/revoke", response_model=APIKeyRevokeResponse)
def revoke_api_key(
    key_id: str,
    request: Request,
    principal: APIPrincipal = Depends(get_request_principal),
    store: SQLiteAPIKeyStore = Depends(get_required_api_key_store),
) -> APIKeyRevokeResponse:
    start = time.perf_counter()
    require_scopes(principal, (API_KEY_MANAGE_SCOPE,))
    try:
        store.revoke_key(
            key_id=key_id,
            actor="admin_api",
            metadata={"revoked_by": principal.key_id},
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    obs = getattr(request.app.state, "observability", None)
    if obs is not None:
        obs.record(
            route="/v1/platform/api-keys/{key_id}/revoke",
            status_code=200,
            duration_ms=duration_ms,
        )
    return APIKeyRevokeResponse(key_id=key_id)


@router.get("/api-keys/audit", response_model=APIKeyAuditResponse)
def list_api_key_audit(
    request: Request,
    client_id: str | None = None,
    principal: APIPrincipal = Depends(get_request_principal),
    store: SQLiteAPIKeyStore = Depends(get_required_api_key_store),
) -> APIKeyAuditResponse:
    start = time.perf_counter()
    require_scopes(principal, (API_KEY_MANAGE_SCOPE,))
    events = [_audit_to_response(event) for event in store.list_audit_events(client_id=client_id)]
    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    obs = getattr(request.app.state, "observability", None)
    if obs is not None:
        obs.record(route="/v1/platform/api-keys/audit", status_code=200, duration_ms=duration_ms)
    return APIKeyAuditResponse(count=len(events), events=events)
