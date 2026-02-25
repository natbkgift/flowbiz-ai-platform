"""System and metadata endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from platform_app.config import get_settings
from platform_app.core_bridge import get_core_package_status

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.name,
        "version": settings.version,
        "env": settings.env,
    }


@router.get("/v1/meta")
def meta() -> dict[str, object]:
    settings = get_settings()
    return {
        "service": settings.name,
        "env": settings.env,
        "version": settings.version,
        "core_dependency": get_core_package_status(),
        "modes": {
            "auth": settings.auth_mode,
            "rate_limit": settings.rate_limit_mode,
            "llm": settings.llm_provider,
            "metrics": settings.metrics_mode,
            "tracing": settings.tracing_mode,
        },
    }

