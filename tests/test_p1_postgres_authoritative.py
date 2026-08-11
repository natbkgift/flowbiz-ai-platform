from __future__ import annotations

from platform_app.db.models import (
    Base,
    Tenant,
    UserIdentity,
    Role,
    Membership,
    Project,
    Job,
    JobAttempt,
    UsageRecord,
    ApprovalRequest,
    ApprovalDecision,
    AuditEvent,
)
from platform_app.db.repositories import TenantScopedRepository


def test_p1_postgresql_authoritative_tables_mapped() -> None:
    """P1 Gate: Verify PostgreSQL models for tenants, RBAC, jobs, dispatches, callbacks, audit."""
    tables = Base.metadata.tables
    required_tables = {
        "user_identities",
        "tenants",
        "roles",
        "memberships",
        "projects",
        "jobs",
        "job_attempts",
        "usage_records",
        "approval_requests",
        "approval_decisions",
        "audit_events",
    }
    assert required_tables <= set(tables.keys())


def test_p1_tenant_isolation_constraints() -> None:
    """P1 Gate: Verify tenant_id column constraints on PostgreSQL models."""
    for table_name in ["projects", "jobs", "approval_requests", "audit_events"]:
        table = Base.metadata.tables[table_name]
        assert "tenant_id" in table.columns
        assert table.columns["tenant_id"].nullable is False
