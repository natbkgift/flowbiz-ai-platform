"""System and metadata endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from platform_app.config import get_settings
from platform_app.core_bridge import get_core_package_status

router = APIRouter(tags=["public"])


def _safe_capabilities() -> dict[str, object]:
    settings = get_settings()
    return {
        "auth_required": settings.auth_mode != "disabled",
        "rate_limited": settings.rate_limit_mode != "noop",
        "llm_configured": bool(settings.llm_provider),
    }


@router.get("/healthz")
def healthz() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.name,
        "version": settings.version,
    }


@router.get("/readyz")
def readyz() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ready",
        "service": settings.name,
        "version": settings.version,
        "checks": {
            "configuration_loaded": True,
            "auth_configured": settings.auth_mode in {"disabled", "api_key"},
            "rate_limit_configured": settings.rate_limit_mode
            in {"noop", "memory", "redis"},
            "cors_policy_loaded": True,
        },
    }


@router.get("/v1/meta")
def meta() -> dict[str, object]:
    settings = get_settings()
    core_status = get_core_package_status()
    payload: dict[str, object] = {
        "service": settings.name,
        "version": settings.version,
        "core_dependency": {"installed": bool(core_status["installed"])},
        "capabilities": _safe_capabilities(),
    }
    if not settings.is_production:
        payload["modes"] = {
            "auth": settings.auth_mode,
            "rate_limit": settings.rate_limit_mode,
            "llm": settings.llm_provider,
            "metrics": settings.metrics_mode,
            "tracing": settings.tracing_mode,
        }
    return payload
