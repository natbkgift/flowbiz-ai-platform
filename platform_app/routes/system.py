"""System and metadata endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import text

from platform_app.config import get_settings
from platform_app.core_bridge import get_core_package_status, get_core_runtime_status
from platform_app.db.session import get_session_factory

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
    database_ready = not settings.runner_enabled
    migration_ready = not settings.runner_enabled
    if settings.runner_enabled:
        try:
            factory = get_session_factory()
            with factory() as session:
                session.execute(text("SELECT 1"))
                revision = session.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
            database_ready = True
            migration_ready = revision == "20260812_0002"
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="PostgreSQL authority is not ready",
            ) from exc
    core_installed = bool(get_core_package_status()["installed"])
    if settings.runner_enabled and (not core_installed or not migration_ready):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="runner contract or database migration is not ready",
        )
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
            "postgres_authority": database_ready,
            "runner_migration_current": migration_ready,
            "core_contract_installed": core_installed,
        },
    }


@router.get("/v1/meta")
def meta(request: Request) -> dict[str, object]:
    settings = get_settings()
    core_status = get_core_package_status()
    core_runtime = get_core_runtime_status(
        settings,
        request_id=getattr(request.state, "request_id", None),
        correlation_id=getattr(request.state, "correlation_id", None),
    )
    payload: dict[str, object] = {
        "service": settings.name,
        "version": settings.version,
        "core_dependency": {"installed": bool(core_status["installed"])},
        "core_runtime": {"reachable": bool(core_runtime["reachable"])},
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
