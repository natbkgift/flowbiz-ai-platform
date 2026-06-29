"""Tenant-scoped PostgreSQL repository helpers.

The repository enforces tenant predicates for every read/write method. It is a
foundation for later route cutover and is not wired into runtime in PROD-04.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from platform_app.db.models import AuditEvent, Job, Project


class TenantScopedRepository:
    """Minimal tenant-scoped repository used by foundation tests."""

    def __init__(self, session: Session, tenant_id: str) -> None:
        if not tenant_id.strip():
            raise ValueError("tenant_id is required")
        self._session = session
        self._tenant_id = tenant_id

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    def create_project(
        self,
        *,
        project_id: str,
        name: str,
        created_by_user_id: str | None = None,
    ) -> Project:
        project = Project(
            project_id=project_id,
            tenant_id=self._tenant_id,
            name=name,
            created_by_user_id=created_by_user_id,
        )
        self._session.add(project)
        self._session.flush()
        return project

    def get_project(self, project_id: str) -> Project | None:
        statement = select(Project).where(
            Project.tenant_id == self._tenant_id,
            Project.project_id == project_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_projects(self) -> list[Project]:
        statement = select(Project).where(Project.tenant_id == self._tenant_id)
        return list(self._session.execute(statement).scalars())

    def create_job(
        self,
        *,
        job_id: str,
        project_id: str,
        kind: str,
        idempotency_key: str,
        payload: dict[str, object] | None = None,
    ) -> Job:
        job = Job(
            job_id=job_id,
            tenant_id=self._tenant_id,
            project_id=project_id,
            kind=kind,
            state="queued",
            idempotency_key=idempotency_key,
            payload=payload or {},
        )
        self._session.add(job)
        self._session.flush()
        return job

    def get_job_by_idempotency_key(self, idempotency_key: str) -> Job | None:
        statement = select(Job).where(
            Job.tenant_id == self._tenant_id,
            Job.idempotency_key == idempotency_key,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def append_audit_event(
        self,
        *,
        event_id: str,
        event_type: str,
        resource_type: str,
        resource_id: str,
        actor_user_id: str | None = None,
        request_id: str | None = None,
        safe_details: dict[str, object] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            event_id=event_id,
            tenant_id=self._tenant_id,
            actor_user_id=actor_user_id,
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=request_id,
            safe_details=safe_details or {},
        )
        self._session.add(event)
        self._session.flush()
        return event
