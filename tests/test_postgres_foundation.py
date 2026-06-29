from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from platform_app.db.models import AuditEvent, Job, Tenant, UserIdentity
from platform_app.db.repositories import TenantScopedRepository
from platform_app.db.session import create_session_factory, session_scope

EXPECTED_TABLES = {
    "user_identities",
    "tenants",
    "roles",
    "memberships",
    "projects",
    "business_profiles",
    "product_services",
    "campaign_goals",
    "strategies",
    "creative_briefs",
    "campaign_plans",
    "jobs",
    "job_attempts",
    "usage_records",
    "approval_requests",
    "approval_decisions",
    "audit_events",
}

TENANT_TABLES = EXPECTED_TABLES - {"user_identities", "tenants", "roles"}
TABLES_TO_TRUNCATE = tuple(sorted(EXPECTED_TABLES - {"roles"}))
REQUIRED_JOB_STATES = {"queued", "running", "succeeded", "failed", "dead_letter", "cancelled"}
REQUIRED_JOB_KINDS = {"strategy", "creative_brief", "campaign_plan"}
OUTPUT_TABLES = {"strategies", "creative_briefs", "campaign_plans"}


@pytest.fixture()
def postgres_engine() -> Engine:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL foundation tests")

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
    return EXPECTED_TABLES <= set(inspect(engine).get_table_names())


def _truncate_test_tables(engine: Engine) -> None:
    table_list = ", ".join(f'"{table_name}"' for table_name in TABLES_TO_TRUNCATE)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE"))


def test_alembic_upgrade_creates_expected_tenant_scoped_schema(postgres_engine: Engine) -> None:
    inspector = inspect(postgres_engine)
    table_names = set(inspector.get_table_names())

    assert EXPECTED_TABLES <= table_names

    for table_name in TENANT_TABLES:
        columns = {column["name"]: column for column in inspector.get_columns(table_name)}
        assert "tenant_id" in columns, table_name
        assert columns["tenant_id"]["nullable"] is False, table_name
        index_columns = [
            tuple(index["column_names"])
            for index in inspector.get_indexes(table_name)
            if index["column_names"]
        ]
        assert any(columns[0] == "tenant_id" for columns in index_columns), table_name

    job_constraints = " ".join(
        check.get("sqltext", "") for check in inspector.get_check_constraints("jobs")
    )
    for expected_state in REQUIRED_JOB_STATES:
        assert expected_state in job_constraints
    for expected_kind in REQUIRED_JOB_KINDS:
        assert expected_kind in job_constraints

    for table_name in OUTPUT_TABLES:
        foreign_keys = inspector.get_foreign_keys(table_name)
        assert any(
            fk["referred_table"] == "jobs" and fk["constrained_columns"] == ["job_id"]
            for fk in foreign_keys
        ), table_name


def test_tenant_scoped_repository_isolates_projects(postgres_engine: Engine) -> None:
    factory = create_session_factory(postgres_engine)

    with session_scope(factory) as session:
        session.add_all(
            [
                Tenant(tenant_id="ten_a", slug="tenant-a", name="Tenant A"),
                Tenant(tenant_id="ten_b", slug="tenant-b", name="Tenant B"),
                UserIdentity(
                    user_id="usr_a",
                    provider="supabase",
                    external_subject="subject-a",
                    email="a@example.invalid",
                ),
            ]
        )
        session.flush()
        TenantScopedRepository(session, "ten_a").create_project(
            project_id="prj_a",
            name="Tenant A Project",
            created_by_user_id="usr_a",
        )

    with session_scope(factory) as session:
        assert TenantScopedRepository(session, "ten_a").get_project("prj_a") is not None
        assert TenantScopedRepository(session, "ten_b").get_project("prj_a") is None


def test_job_idempotency_is_tenant_scoped(postgres_engine: Engine) -> None:
    factory = create_session_factory(postgres_engine)

    with session_scope(factory) as session:
        session.add_all(
            [
                Tenant(tenant_id="ten_a", slug="tenant-a", name="Tenant A"),
                Tenant(tenant_id="ten_b", slug="tenant-b", name="Tenant B"),
            ]
        )
        session.flush()
        TenantScopedRepository(session, "ten_a").create_project(
            project_id="prj_a",
            name="Tenant A Project",
        )
        TenantScopedRepository(session, "ten_b").create_project(
            project_id="prj_b",
            name="Tenant B Project",
        )

    with session_scope(factory) as session:
        TenantScopedRepository(session, "ten_a").create_job(
            job_id="job_a_1",
            project_id="prj_a",
            kind="strategy",
            idempotency_key="idem-1",
        )
        TenantScopedRepository(session, "ten_b").create_job(
            job_id="job_b_1",
            project_id="prj_b",
            kind="strategy",
            idempotency_key="idem-1",
        )

    with pytest.raises(IntegrityError):
        with session_scope(factory) as session:
            TenantScopedRepository(session, "ten_a").create_job(
                job_id="job_a_2",
                project_id="prj_a",
                kind="strategy",
                idempotency_key="idem-1",
            )

    with session_scope(factory) as session:
        existing = TenantScopedRepository(session, "ten_a").get_job_by_idempotency_key("idem-1")
        assert existing is not None
        assert existing.job_id == "job_a_1"
        jobs = session.execute(select(Job).where(Job.tenant_id == "ten_a")).scalars().all()
        assert [job.job_id for job in jobs] == ["job_a_1"]


def test_audit_records_are_append_only_events(postgres_engine: Engine) -> None:
    factory = create_session_factory(postgres_engine)

    with session_scope(factory) as session:
        session.add(Tenant(tenant_id="ten_a", slug="tenant-a", name="Tenant A"))
        session.flush()
        repo = TenantScopedRepository(session, "ten_a")
        repo.append_audit_event(
            event_id="evt_1",
            event_type="project.created",
            resource_type="project",
            resource_id="prj_a",
            request_id="req_1",
        )
        repo.append_audit_event(
            event_id="evt_2",
            event_type="job.queued",
            resource_type="job",
            resource_id="job_a",
            request_id="req_2",
        )

    with session_scope(factory) as session:
        events = session.execute(
            select(AuditEvent)
            .where(AuditEvent.tenant_id == "ten_a")
            .order_by(AuditEvent.event_id)
        ).scalars().all()
        assert [event.event_id for event in events] == ["evt_1", "evt_2"]
