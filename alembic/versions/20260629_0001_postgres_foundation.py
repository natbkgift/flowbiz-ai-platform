"""Initial PostgreSQL persistence foundation.

Revision ID: 20260629_0001
Revises:
Create Date: 2026-06-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260629_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_VALUES = "'owner','admin','marketer','viewer','service_identity'"
JOB_STATE_VALUES = "'queued','running','succeeded','failed','dead_letter','cancelled'"
JOB_KIND_VALUES = "'strategy','creative_brief','campaign_plan'"
APPROVAL_STATUS_VALUES = "'pending','approved','rejected','cancelled'"
APPROVAL_DECISION_VALUES = "'approve','reject'"


def tenant_id_column() -> sa.Column[str]:
    return sa.Column(
        "tenant_id",
        sa.String(length=64),
        sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
    )


def timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        )
    ]


def upgrade() -> None:
    op.create_table(
        "user_identities",
        sa.Column("user_id", sa.String(length=64), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_subject", sa.String(length=256), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=160), nullable=True),
        *timestamps(),
        sa.UniqueConstraint(
            "provider",
            "external_subject",
            name="uq_user_identities_provider_subject",
        ),
    )

    op.create_table(
        "tenants",
        sa.Column("tenant_id", sa.String(length=64), primary_key=True),
        sa.Column("slug", sa.String(length=120), nullable=False, unique=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        *timestamps(),
    )

    op.create_table(
        "roles",
        sa.Column("role", sa.String(length=32), primary_key=True),
        sa.Column("description", sa.Text(), nullable=False),
    )
    roles_table = sa.table(
        "roles",
        sa.column("role", sa.String(length=32)),
        sa.column("description", sa.Text()),
    )
    op.bulk_insert(
        roles_table,
        [
            {"role": "owner", "description": "Tenant owner"},
            {"role": "admin", "description": "Tenant administrator"},
            {"role": "marketer", "description": "Marketing operator"},
            {"role": "viewer", "description": "Read-only viewer"},
            {"role": "service_identity", "description": "Service identity"},
        ],
    )

    op.create_table(
        "memberships",
        sa.Column("membership_id", sa.String(length=64), primary_key=True),
        tenant_id_column(),
        sa.Column(
            "user_id",
            sa.String(length=64),
            sa.ForeignKey("user_identities.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.String(length=32),
            sa.ForeignKey("roles.role", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        *timestamps(),
        sa.CheckConstraint(f"role IN ({ROLE_VALUES})", name="membership_role_valid"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_user"),
    )
    op.create_index("ix_memberships_tenant_role", "memberships", ["tenant_id", "role"])

    op.create_table(
        "projects",
        sa.Column("project_id", sa.String(length=64), primary_key=True),
        tenant_id_column(),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column(
            "created_by_user_id",
            sa.String(length=64),
            sa.ForeignKey("user_identities.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_projects_tenant_project", "projects", ["tenant_id", "project_id"])

    op.create_table(
        "business_profiles",
        sa.Column("business_profile_id", sa.String(length=64), primary_key=True),
        tenant_id_column(),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.project_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *timestamps(),
        sa.UniqueConstraint("tenant_id", "project_id", name="uq_business_profiles_project"),
    )
    op.create_index(
        "ix_business_profiles_tenant_project",
        "business_profiles",
        ["tenant_id", "project_id"],
    )

    op.create_table(
        "product_services",
        sa.Column("product_service_id", sa.String(length=64), primary_key=True),
        tenant_id_column(),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.project_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "ix_product_services_tenant_project",
        "product_services",
        ["tenant_id", "project_id"],
    )

    op.create_table(
        "campaign_goals",
        sa.Column("campaign_goal_id", sa.String(length=64), primary_key=True),
        tenant_id_column(),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.project_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("goal_type", sa.String(length=80), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index("ix_campaign_goals_tenant_project", "campaign_goals", ["tenant_id", "project_id"])

    for table_name, pk_name, uq_name in (
        ("strategies", "strategy_id", "uq_strategies_version"),
        ("creative_briefs", "creative_brief_id", "uq_creative_briefs_version"),
        ("campaign_plans", "campaign_plan_id", "uq_campaign_plans_version"),
    ):
        op.create_table(
            table_name,
            sa.Column(pk_name, sa.String(length=64), primary_key=True),
            tenant_id_column(),
            sa.Column(
                "project_id",
                sa.String(length=64),
                sa.ForeignKey("projects.project_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("job_id", sa.String(length=64), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            *timestamps(),
            sa.UniqueConstraint("tenant_id", "project_id", "version", name=uq_name),
        )
        op.create_index(f"ix_{table_name}_tenant_project", table_name, ["tenant_id", "project_id"])

    op.create_table(
        "jobs",
        sa.Column("job_id", sa.String(length=64), primary_key=True),
        tenant_id_column(),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.project_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("result_ref", sa.String(length=64), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(f"kind IN ({JOB_KIND_VALUES})", name="job_kind_valid"),
        sa.CheckConstraint(f"state IN ({JOB_STATE_VALUES})", name="job_state_valid"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_jobs_tenant_idempotency"),
    )
    op.create_index("ix_jobs_tenant_state", "jobs", ["tenant_id", "state"])
    op.create_index("ix_jobs_tenant_project", "jobs", ["tenant_id", "project_id"])

    op.create_table(
        "job_attempts",
        sa.Column("job_attempt_id", sa.String(length=64), primary_key=True),
        tenant_id_column(),
        sa.Column(
            "job_id",
            sa.String(length=64),
            sa.ForeignKey("jobs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"state IN ({JOB_STATE_VALUES})", name="job_attempt_state_valid"),
        sa.UniqueConstraint("job_id", "attempt_number", name="uq_job_attempts_job_attempt"),
    )
    op.create_index("ix_job_attempts_tenant_job", "job_attempts", ["tenant_id", "job_id"])

    op.create_table(
        "usage_records",
        sa.Column("usage_record_id", sa.String(length=64), primary_key=True),
        tenant_id_column(),
        sa.Column(
            "job_id",
            sa.String(length=64),
            sa.ForeignKey("jobs.job_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("usage_type", sa.String(length=80), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *timestamps(),
    )
    op.create_index("ix_usage_records_tenant_created", "usage_records", ["tenant_id", "created_at"])

    op.create_table(
        "approval_requests",
        sa.Column("approval_id", sa.String(length=64), primary_key=True),
        tenant_id_column(),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.project_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "requested_by_user_id",
            sa.String(length=64),
            sa.ForeignKey("user_identities.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *timestamps(),
        sa.CheckConstraint(
            f"status IN ({APPROVAL_STATUS_VALUES})",
            name="approval_request_status_valid",
        ),
    )
    op.create_index("ix_approval_requests_tenant_status", "approval_requests", ["tenant_id", "status"])

    op.create_table(
        "approval_decisions",
        sa.Column("decision_id", sa.String(length=64), primary_key=True),
        tenant_id_column(),
        sa.Column(
            "approval_id",
            sa.String(length=64),
            sa.ForeignKey("approval_requests.approval_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column(
            "decided_by_user_id",
            sa.String(length=64),
            sa.ForeignKey("user_identities.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            f"decision IN ({APPROVAL_DECISION_VALUES})",
            name="approval_decision_valid",
        ),
    )
    op.create_index(
        "ix_approval_decisions_tenant_approval",
        "approval_decisions",
        ["tenant_id", "approval_id"],
    )

    op.create_table(
        "audit_events",
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        tenant_id_column(),
        sa.Column(
            "actor_user_id",
            sa.String(length=64),
            sa.ForeignKey("user_identities.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(length=160), nullable=False),
        sa.Column("resource_type", sa.String(length=120), nullable=False),
        sa.Column("resource_id", sa.String(length=120), nullable=False),
        sa.Column("request_id", sa.String(length=120), nullable=True),
        sa.Column(
            "safe_details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *timestamps(),
    )
    op.create_index("ix_audit_events_tenant_created", "audit_events", ["tenant_id", "created_at"])


def downgrade() -> None:
    for index_name, table_name in (
        ("ix_audit_events_tenant_created", "audit_events"),
        ("ix_approval_decisions_tenant_approval", "approval_decisions"),
        ("ix_approval_requests_tenant_status", "approval_requests"),
        ("ix_usage_records_tenant_created", "usage_records"),
        ("ix_job_attempts_tenant_job", "job_attempts"),
        ("ix_jobs_tenant_project", "jobs"),
        ("ix_jobs_tenant_state", "jobs"),
        ("ix_campaign_plans_tenant_project", "campaign_plans"),
        ("ix_creative_briefs_tenant_project", "creative_briefs"),
        ("ix_strategies_tenant_project", "strategies"),
        ("ix_campaign_goals_tenant_project", "campaign_goals"),
        ("ix_product_services_tenant_project", "product_services"),
        ("ix_business_profiles_tenant_project", "business_profiles"),
        ("ix_projects_tenant_project", "projects"),
        ("ix_memberships_tenant_role", "memberships"),
    ):
        op.drop_index(index_name, table_name=table_name)

    for table_name in (
        "audit_events",
        "approval_decisions",
        "approval_requests",
        "usage_records",
        "job_attempts",
        "jobs",
        "campaign_plans",
        "creative_briefs",
        "strategies",
        "campaign_goals",
        "product_services",
        "business_profiles",
        "projects",
        "memberships",
        "roles",
        "tenants",
        "user_identities",
    ):
        op.drop_table(table_name)
