"""Platform FastAPI entrypoint for FlowBiz AI Platform."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from platform_app.config import get_settings
from platform_app.deps import get_secret_provider_bundle
from platform_app.middleware import RequestContextMiddleware
from platform_app.observability import (
    configure_structured_logging,
    init_observability,
)
from platform_app.routes.platform import router as platform_router
from platform_app.routes.system import router as system_router
from platform_app.routes.workflow_events import router as workflow_events_router
from platform_app.runtime import validate_runtime_configuration


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_structured_logging(settings)
    validate_runtime_configuration(settings, get_secret_provider_bundle())
    app.state.observability = init_observability(settings)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    docs_url = "/docs" if settings.docs_enabled_effective else None
    redoc_url = "/redoc" if settings.docs_enabled_effective else None
    openapi_url = "/openapi.json" if settings.docs_enabled_effective else None
    app = FastAPI(
        title=settings.name,
        version=settings.version,
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )
    app.add_middleware(RequestContextMiddleware)
    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=settings.cors_allow_credentials,
            allow_methods=settings.cors_method_list,
            allow_headers=settings.cors_header_list,
            expose_headers=settings.cors_expose_header_list,
        )
    app.include_router(system_router)
    app.include_router(platform_router)
    app.include_router(workflow_events_router)
    return app


app = create_app()
