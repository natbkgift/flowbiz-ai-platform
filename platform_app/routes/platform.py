"""Platform-facing endpoints that wrap platform concerns around LLM execution."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from platform_app.auth import APIPrincipal, require_scopes
from platform_app.deps import (
    get_auth_dependency,
    get_llm_adapter,
    get_rate_limiter,
)
from platform_app.llm import ChatRequest, LLMProviderError
from platform_app.rate_limit import apply_rate_limit_headers, enforce_rate_limit

router = APIRouter(prefix="/v1/platform")


@router.post("/chat")
def platform_chat(
    body: ChatRequest,
    request: Request,
    response: Response,
    principal: APIPrincipal = Depends(get_auth_dependency()),
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
