"""Tenant membership and RBAC foundation for Platform APIs.

This module verifies that a previously authenticated Supabase identity belongs
to the selected tenant before future route handlers trust ``X-Tenant-ID``.
It is intentionally not wired into FastAPI routes in PROD-06.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from http import HTTPStatus

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from platform_app.db.models import Membership, Tenant, UserIdentity
from platform_app.supabase_auth import AuthenticatedPrincipal


class PlatformRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MARKETER = "marketer"
    VIEWER = "viewer"
    SERVICE_IDENTITY = "service_identity"


class RbacAction(StrEnum):
    AUTH_ME_READ = "auth.me.read"
    TENANT_READ = "tenant.read"
    TENANT_MANAGE = "tenant.manage"
    MEMBERSHIP_READ = "membership.read"
    MEMBERSHIP_MANAGE = "membership.manage"
    PROJECT_READ = "project.read"
    PROJECT_WRITE = "project.write"
    PROJECT_DELETE = "project.delete"
    ONBOARDING_READ = "onboarding.read"
    ONBOARDING_WRITE = "onboarding.write"
    GENERATION_SUBMIT = "generation.submit"
    JOB_READ = "job.read"
    JOB_RETRY = "job.retry"
    JOB_CANCEL = "job.cancel"
    OUTPUT_READ = "output.read"
    DASHBOARD_READ = "dashboard.read"
    APPROVAL_READ = "approval.read"
    APPROVAL_DECIDE = "approval.decide"
    AUDIT_READ = "audit.read"
    USAGE_READ = "usage.read"


ACTIVE_STATUS = "active"
SUPABASE_PROVIDER = "supabase"

READ_ROLES = frozenset(
    {
        PlatformRole.OWNER,
        PlatformRole.ADMIN,
        PlatformRole.MARKETER,
        PlatformRole.VIEWER,
        PlatformRole.SERVICE_IDENTITY,
    }
)
OPERATOR_ROLES = frozenset({PlatformRole.OWNER, PlatformRole.ADMIN, PlatformRole.MARKETER})
ADMIN_ROLES = frozenset({PlatformRole.OWNER, PlatformRole.ADMIN})
OWNER_ROLES = frozenset({PlatformRole.OWNER})

ACTION_ALLOWED_ROLES: dict[RbacAction, frozenset[PlatformRole]] = {
    RbacAction.AUTH_ME_READ: READ_ROLES,
    RbacAction.TENANT_READ: READ_ROLES,
    RbacAction.TENANT_MANAGE: OWNER_ROLES,
    RbacAction.MEMBERSHIP_READ: ADMIN_ROLES,
    RbacAction.MEMBERSHIP_MANAGE: OWNER_ROLES,
    RbacAction.PROJECT_READ: READ_ROLES,
    RbacAction.PROJECT_WRITE: OPERATOR_ROLES,
    RbacAction.PROJECT_DELETE: ADMIN_ROLES,
    RbacAction.ONBOARDING_READ: READ_ROLES,
    RbacAction.ONBOARDING_WRITE: OPERATOR_ROLES,
    RbacAction.GENERATION_SUBMIT: OPERATOR_ROLES,
    RbacAction.JOB_READ: READ_ROLES,
    RbacAction.JOB_RETRY: OPERATOR_ROLES,
    RbacAction.JOB_CANCEL: OPERATOR_ROLES,
    RbacAction.OUTPUT_READ: READ_ROLES,
    RbacAction.DASHBOARD_READ: READ_ROLES,
    RbacAction.APPROVAL_READ: READ_ROLES,
    RbacAction.APPROVAL_DECIDE: ADMIN_ROLES,
    RbacAction.AUDIT_READ: ADMIN_ROLES,
    RbacAction.USAGE_READ: ADMIN_ROLES,
}


class TenantRbacError(Exception):
    """Safe tenant/RBAC error for future route adapters."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class TenantPrincipal(BaseModel):
    """Authenticated principal after authoritative tenant membership lookup."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    membership_id: str = Field(min_length=1)
    role: PlatformRole
    request_id: str | None = None
    tenant_authorized: bool = True


class RbacPolicy(BaseModel):
    """Fail-closed RBAC policy with explicit action-to-role mappings."""

    model_config = ConfigDict(frozen=True)

    allowed_roles: dict[RbacAction, frozenset[PlatformRole]] = Field(
        default_factory=lambda: dict(ACTION_ALLOWED_ROLES)
    )

    def allows(self, role: str | PlatformRole, action: str | RbacAction) -> bool:
        normalized_role = _parse_role(role)
        normalized_action = _parse_action(action)
        if normalized_role is None or normalized_action is None:
            return False
        return normalized_role in self.allowed_roles.get(normalized_action, frozenset())

    def require(self, role: str | PlatformRole, action: str | RbacAction) -> None:
        if not self.allows(role, action):
            raise TenantRbacError(HTTPStatus.FORBIDDEN, "Permission denied")


DEFAULT_POLICY = RbacPolicy()


class TenantMembershipResolver:
    """Resolve Supabase identity + tenant selector into a tenant principal."""

    def __init__(self, policy: RbacPolicy | None = None) -> None:
        self._policy = policy or DEFAULT_POLICY

    @property
    def policy(self) -> RbacPolicy:
        return self._policy

    def resolve(
        self,
        session: Session,
        principal: AuthenticatedPrincipal,
        *,
        tenant_selector: str | None = None,
        required_action: str | RbacAction | None = None,
    ) -> TenantPrincipal:
        tenant_id = _select_tenant_id(tenant_selector, principal.tenant_selector)
        if tenant_id is None:
            raise TenantRbacError(HTTPStatus.FORBIDDEN, "Tenant access denied")

        statement = (
            select(UserIdentity, Membership, Tenant)
            .join(Membership, Membership.user_id == UserIdentity.user_id)
            .join(Tenant, Tenant.tenant_id == Membership.tenant_id)
            .where(
                UserIdentity.provider == SUPABASE_PROVIDER,
                UserIdentity.external_subject == principal.subject,
                Membership.tenant_id == tenant_id,
                Membership.status == ACTIVE_STATUS,
                Tenant.status == ACTIVE_STATUS,
            )
        )
        row = session.execute(statement).one_or_none()
        if row is None:
            raise TenantRbacError(HTTPStatus.FORBIDDEN, "Tenant access denied")

        user_identity, membership, _tenant = row
        role = _parse_role(membership.role)
        if role is None:
            raise TenantRbacError(HTTPStatus.FORBIDDEN, "Tenant access denied")

        tenant_principal = TenantPrincipal(
            subject=principal.subject,
            user_id=user_identity.user_id,
            tenant_id=membership.tenant_id,
            membership_id=membership.membership_id,
            role=role,
            request_id=principal.request_id,
            tenant_authorized=True,
        )
        if required_action is not None:
            self._policy.require(tenant_principal.role, required_action)
        return tenant_principal


def require_tenant_action(
    tenant_principal: TenantPrincipal,
    action: str | RbacAction,
    *,
    policy: RbacPolicy | None = None,
) -> None:
    """Require an action for an already resolved tenant principal."""

    active_policy = policy or DEFAULT_POLICY
    active_policy.require(tenant_principal.role, action)


def allowed_actions_for_role(role: str | PlatformRole) -> tuple[RbacAction, ...]:
    """Return explicit allowed actions for documentation/tests."""

    normalized_role = _parse_role(role)
    if normalized_role is None:
        return ()
    return tuple(
        action
        for action, allowed_roles in ACTION_ALLOWED_ROLES.items()
        if normalized_role in allowed_roles
    )


def _parse_role(role: str | PlatformRole) -> PlatformRole | None:
    if isinstance(role, PlatformRole):
        return role
    try:
        return PlatformRole(role)
    except ValueError:
        return None


def _parse_action(action: str | RbacAction) -> RbacAction | None:
    if isinstance(action, RbacAction):
        return action
    try:
        return RbacAction(action)
    except ValueError:
        return None


def _select_tenant_id(*selectors: str | None) -> str | None:
    selected = [selector.strip() for selector in selectors if selector and selector.strip()]
    if not selected:
        return None
    first, *rest = selected
    if any(selector != first for selector in rest):
        return None
    return first


def assert_all_roles_have_actions(roles: Iterable[PlatformRole]) -> None:
    """Test helper that fails closed if a role has no explicit action mapping."""

    for role in roles:
        if not allowed_actions_for_role(role):
            raise AssertionError(f"role has no actions: {role.value}")
