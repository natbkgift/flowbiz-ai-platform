from __future__ import annotations

from platform_app.db.models import Base
from platform_app.tenant_rbac import PlatformRole, RbacAction, allowed_actions_for_role
from platform_app.admission_policy import AdmissionDecision, PLATFORM_STATUS_ACCEPTED
from platform_app.observability import RequestEvent


def test_postgresql_models_registered() -> None:
    """Verify authoritative PostgreSQL models are properly defined on Base metadata."""
    tables = Base.metadata.tables
    assert "user_identities" in tables
    assert "tenants" in tables
    assert "roles" in tables
    assert "memberships" in tables
    assert "projects" in tables
    assert "jobs" in tables
    assert "job_attempts" in tables
    assert "approval_requests" in tables
    assert "approval_decisions" in tables
    assert "audit_events" in tables


def test_tenant_rbac_roles_and_actions() -> None:
    """Verify RBAC role hierarchy and action mappings."""
    assert PlatformRole.OWNER == "owner"
    assert PlatformRole.ADMIN == "admin"
    assert PlatformRole.MARKETER == "marketer"
    assert PlatformRole.VIEWER == "viewer"

    owner_actions = allowed_actions_for_role(PlatformRole.OWNER)
    assert RbacAction.TENANT_READ in owner_actions
    assert RbacAction.PROJECT_WRITE in owner_actions
    assert RbacAction.TENANT_MANAGE in owner_actions


def test_admission_decision_and_status_constants() -> None:
    """Verify admission decision schema and status constants."""
    assert PLATFORM_STATUS_ACCEPTED == "accepted"
    decision = AdmissionDecision(allowed=True, code="ACCEPTED", message="Job accepted")
    assert decision.allowed is True
    assert decision.code == "ACCEPTED"


def test_observability_request_event() -> None:
    """Verify observability RequestEvent schema."""
    event = RequestEvent(
        route="/v1/platform/jobs",
        status_code=202,
        duration_ms=42.5,
    )
    assert event.route == "/v1/platform/jobs"
    assert event.status_code == 202
    assert event.duration_ms == 42.5
