"""Platform FastAPI entrypoint for FlowBiz AI Platform."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from platform_app.config import get_settings
from platform_app.observability import init_observability
from platform_app.routes.platform import router as platform_router
from platform_app.routes.system import router as system_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.observability = init_observability(settings)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.name,
        version=settings.version,
        lifespan=lifespan,
    )
    app.include_router(system_router)
    app.include_router(platform_router)
    return app


app = create_app()

