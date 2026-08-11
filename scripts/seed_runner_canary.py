"""Idempotently seed the internal production canary tenant and project."""

from __future__ import annotations

import os

from platform_app.db.models import Project, Tenant
from platform_app.db.session import get_session_factory


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def main() -> None:
    tenant_id = _required("PLATFORM_CANARY_TENANT_ID")
    project_id = _required("PLATFORM_CANARY_PROJECT_ID")
    factory = get_session_factory()
    with factory() as session:
        tenant = session.get(Tenant, tenant_id)
        if tenant is None:
            tenant = Tenant(
                tenant_id=tenant_id,
                slug="internal-production-canary",
                name="Internal Production Canary",
                status="active",
            )
            session.add(tenant)
            session.flush()
        if session.get(Project, project_id) is None:
            session.add(
                Project(
                    project_id=project_id,
                    tenant_id=tenant_id,
                    name="Hermes Read-only Production Canary",
                    status="active",
                )
            )
        session.commit()
    print("runner canary authority seeded")


if __name__ == "__main__":
    main()
