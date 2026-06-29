from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

from platform_app.db.models import Membership, Tenant, UserIdentity
from platform_app.db.session import create_session_factory, session_scope
from platform_app.supabase_auth import AuthenticatedPrincipal
from platform_app.tenant_rbac import (
    PlatformRole,
    RbacAction,
    RbacPolicy,
    TenantMembershipResolver,
    TenantRbacError,
    allowed_actions_for_role,
    assert_all_roles_have_actions,
    require_tenant_action,
)

REQUIRED_TABLES = {"user_identities", "tenants", "roles", "memberships"}
TABLES_TO_TRUNCATE = ("memberships", "tenants", "user_identities")


@pytest.fixture()
def postgres_engine() -> Engine:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required for tenant/RBAC foundation tests")

    engine = create_engine(database_url, future=True)
    if not _schema_exists(engine):
        engine.dispose()
        pytest.skip("PostgreSQL schema is not migrated; run alembic upgrade head")

    _truncate_test_tables(engine)
    try:
        yield engine
    finally:
        _truncate_test_tables(engine)
        engine.dispose()


def _schema_exists(engine: Engine) -> bool:
    return REQUIRED_TABLES <= set(inspect(engine).get_table_names())


def _truncate_test_tables(engine: Engine) -> None:
    table_list = ", ".join(f'"{table_name}"' for table_name in TABLES_TO_TRUNCATE)
    with engine.begin() as connection:
        connection.exec_driver_sql(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE")


def _principal(subject: str = "supabase-subject-a", tenant_id: str | None = "ten_a") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        subject=subject,
        issuer="https://supabase.example.invalid/auth/v1",
        audience=("authenticated",),
        expires_at=4_102_444_800,
        request_id="req_test",
        tenant_selector=tenant_id,
        tenant_authorized=False,
    )


def _seed_membership(
    engine: Engine,
    *,
    tenant_id: str = "ten_a",
    tenant_status: str = "active",
    membership_status: str = "active",
    role: str = "marketer",
    subject: str = "supabase-subject-a",
) -> None:
    factory = create_session_factory(engine)
    with session_scope(factory) as session:
        session.add(
            UserIdentity(
                user_id="usr_a",
                provider="supabase",
                external_subject=subject,
                email="user@example.invalid",
            )
        )
        session.add(Tenant(tenant_id=tenant_id, slug=tenant_id, name="Tenant A", status=tenant_status))
        session.flush()
        session.add(
            Membership(
                membership_id="mem_a",
                tenant_id=tenant_id,
                user_id="usr_a",
                role=role,
                status=membership_status,
            )
        )


def test_resolves_active_supabase_membership(postgres_engine: Engine) -> None:
    _seed_membership(postgres_engine)
    factory = create_session_factory(postgres_engine)

    with session_scope(factory) as session:
        tenant_principal = TenantMembershipResolver().resolve(session, _principal())

    assert tenant_principal.tenant_id == "ten_a"
    assert tenant_principal.user_id == "usr_a"
    assert tenant_principal.membership_id == "mem_a"
    assert tenant_principal.role is PlatformRole.MARKETER
    assert tenant_principal.tenant_authorized is True
    assert tenant_principal.request_id == "req_test"


def test_resolve_fails_closed_for_tenant_mismatch(postgres_engine: Engine) -> None:
    _seed_membership(postgres_engine)
    factory = create_session_factory(postgres_engine)

    with session_scope(factory) as session, pytest.raises(TenantRbacError) as exc_info:
        TenantMembershipResolver().resolve(session, _principal(tenant_id="ten_b"))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Tenant access denied"


def test_resolve_fails_closed_for_conflicting_tenant_selector(postgres_engine: Engine) -> None:
    _seed_membership(postgres_engine)
    factory = create_session_factory(postgres_engine)

    with session_scope(factory) as session, pytest.raises(TenantRbacError):
        TenantMembershipResolver().resolve(
            session,
            _principal(tenant_id="ten_a"),
            tenant_selector="ten_b",
        )


def test_resolve_fails_closed_for_inactive_membership_or_tenant(postgres_engine: Engine) -> None:
    _seed_membership(postgres_engine, membership_status="suspended")
    factory = create_session_factory(postgres_engine)
    with session_scope(factory) as session, pytest.raises(TenantRbacError):
        TenantMembershipResolver().resolve(session, _principal())

    _truncate_test_tables(postgres_engine)
    _seed_membership(postgres_engine, tenant_status="disabled")
    with session_scope(factory) as session, pytest.raises(TenantRbacError):
        TenantMembershipResolver().resolve(session, _principal())


def test_required_action_is_checked_after_membership_resolution(postgres_engine: Engine) -> None:
    _seed_membership(postgres_engine, role="viewer")
    factory = create_session_factory(postgres_engine)

    with session_scope(factory) as session, pytest.raises(TenantRbacError) as exc_info:
        TenantMembershipResolver().resolve(
            session,
            _principal(),
            required_action=RbacAction.GENERATION_SUBMIT,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Permission denied"


def test_rbac_policy_is_default_deny_for_unknown_values() -> None:
    policy = RbacPolicy()

    assert policy.allows("viewer", RbacAction.PROJECT_READ)
    assert not policy.allows("viewer", RbacAction.GENERATION_SUBMIT)
    assert not policy.allows("unknown", RbacAction.PROJECT_READ)
    assert not policy.allows("viewer", "unknown.action")

    with pytest.raises(TenantRbacError):
        policy.require("viewer", RbacAction.GENERATION_SUBMIT)


def test_role_action_matrix_is_explicit() -> None:
    assert_all_roles_have_actions(PlatformRole)
    assert RbacAction.MEMBERSHIP_MANAGE in allowed_actions_for_role(PlatformRole.OWNER)
    assert RbacAction.MEMBERSHIP_MANAGE not in allowed_actions_for_role(PlatformRole.ADMIN)
    assert RbacAction.GENERATION_SUBMIT in allowed_actions_for_role(PlatformRole.MARKETER)
    assert RbacAction.GENERATION_SUBMIT not in allowed_actions_for_role(PlatformRole.VIEWER)


def test_require_tenant_action_accepts_resolved_principal() -> None:
    tenant_principal = TenantMembershipResolver().policy
    assert tenant_principal.allows(PlatformRole.ADMIN, RbacAction.APPROVAL_DECIDE)

    resolved = TenantMembershipResolver().policy
    with pytest.raises(TenantRbacError):
        resolved.require(PlatformRole.VIEWER, RbacAction.APPROVAL_DECIDE)

    from platform_app.tenant_rbac import TenantPrincipal

    principal = TenantPrincipal(
        subject="sub",
        user_id="usr",
        tenant_id="ten",
        membership_id="mem",
        role=PlatformRole.ADMIN,
    )
    require_tenant_action(principal, RbacAction.APPROVAL_DECIDE)
