"""Dependency factories for platform routes."""

from __future__ import annotations

from functools import lru_cache

from fastapi import Header

from platform_app.auth import auth_dependency_factory
from platform_app.api_key_store import SQLiteAPIKeyStore, resolve_auth_db_path
from platform_app.config import get_settings
from platform_app.llm import build_llm_adapter
from platform_app.rate_limit import build_rate_limiter
from platform_app.secrets import build_secret_provider
from platform_app.auth import hash_api_key_secret
from platform_app.workflow_events import (
    SQLiteWorkflowEventStore,
    resolve_workflow_events_db_path,
)


@lru_cache
def get_secret_provider_bundle():
    return build_secret_provider(get_settings())


@lru_cache
def get_llm_adapter():
    return build_llm_adapter(get_settings(), get_secret_provider_bundle())


@lru_cache
def get_rate_limiter():
    return build_rate_limiter(get_settings())


@lru_cache
def get_api_key_store():
    settings = get_settings()
    if settings.auth_store_mode == "json":
        return None
    if settings.auth_store_mode == "sqlite":
        return SQLiteAPIKeyStore(
            db_path=resolve_auth_db_path(settings.auth_sqlite_path),
            hash_secret_fn=hash_api_key_secret,
        )
    raise ValueError(f"Unsupported auth_store_mode: {settings.auth_store_mode}")


@lru_cache
def get_auth_dependency():
    return auth_dependency_factory(get_settings(), store=get_api_key_store())


async def get_request_principal(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    auth_dep = auth_dependency_factory(get_settings(), store=get_api_key_store())
    return await auth_dep(x_api_key)


@lru_cache
def get_workflow_event_store() -> SQLiteWorkflowEventStore:
    settings = get_settings()
    return SQLiteWorkflowEventStore(
        db_path=resolve_workflow_events_db_path(settings.workflow_events_sqlite_path)
    )
