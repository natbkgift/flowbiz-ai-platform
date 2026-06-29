"""PostgreSQL engine and session helpers.

These helpers are intentionally explicit. PROD-04 adds the foundation but does
not wire PostgreSQL into FastAPI routes or replace existing SQLite stores.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from platform_app.config import PlatformSettings, get_settings


class DatabaseUrlNotConfigured(RuntimeError):
    """Raised when a PostgreSQL operation is requested without a URL."""


def get_database_url(settings: PlatformSettings | None = None) -> str:
    """Return the configured PostgreSQL database URL or fail closed."""

    current = settings or get_settings()
    database_url = current.database_url_value.strip()
    if not database_url:
        raise DatabaseUrlNotConfigured("PLATFORM_DATABASE_URL is not configured")
    return database_url


def create_platform_engine(database_url: str | None = None) -> Engine:
    """Create a SQLAlchemy engine for PostgreSQL foundation tests or later wiring."""

    return create_engine(database_url or get_database_url(), pool_pre_ping=True, future=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a typed SQLAlchemy session factory."""

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Yield a transaction-bound session and roll back on errors."""

    with factory() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
