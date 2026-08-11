"""Make PostgreSQL authoritative for Platform-runner dispatch and callback state.

Revision ID: 20260812_0002
Revises: 20260629_0001
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_0002"
down_revision: str | None = "20260629_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_jobs_job_kind_valid"), "jobs", type_="check")
    op.create_check_constraint(
        "job_kind_valid",
        "jobs",
        "kind IN ('strategy','creative_brief','campaign_plan','runner_task')",
    )

    op.create_table(
        "runner_dispatches",
        sa.Column("dispatch_id", sa.String(length=128), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(length=64),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.String(length=64),
            sa.ForeignKey("jobs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("runner_id", sa.String(length=128), nullable=False),
        sa.Column("workflow_key", sa.String(length=128), nullable=False),
        sa.Column("contract_version", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("trace_id", sa.String(length=128), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("callback_url", sa.String(length=512), nullable=False),
        sa.Column("response_code", sa.Integer(), nullable=True),
        sa.Column("safe_error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('pending','accepted','rejected','dispatch_failed','callback_received')",
            name="runner_dispatch_status_valid",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_runner_dispatches_tenant_idempotency",
        ),
    )
    op.create_index(
        "ix_runner_dispatches_tenant_job",
        "runner_dispatches",
        ["tenant_id", "job_id"],
    )
    op.create_index(
        "ix_runner_dispatches_tenant_status",
        "runner_dispatches",
        ["tenant_id", "status"],
    )

    op.create_table(
        "runner_callbacks",
        sa.Column("callback_id", sa.String(length=128), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(length=64),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dispatch_id",
            sa.String(length=128),
            sa.ForeignKey("runner_dispatches.dispatch_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.String(length=64),
            sa.ForeignKey("jobs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("runner_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("trace_id", sa.String(length=128), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('succeeded','failed','cancelled')",
            name="runner_callback_status_valid",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_runner_callbacks_tenant_idempotency",
        ),
    )
    op.create_index(
        "ix_runner_callbacks_tenant_job",
        "runner_callbacks",
        ["tenant_id", "job_id"],
    )
    op.create_index(
        "ix_runner_callbacks_dispatch",
        "runner_callbacks",
        ["dispatch_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_runner_callbacks_dispatch", table_name="runner_callbacks")
    op.drop_index("ix_runner_callbacks_tenant_job", table_name="runner_callbacks")
    op.drop_table("runner_callbacks")
    op.drop_index("ix_runner_dispatches_tenant_status", table_name="runner_dispatches")
    op.drop_index("ix_runner_dispatches_tenant_job", table_name="runner_dispatches")
    op.drop_table("runner_dispatches")
    op.drop_constraint(op.f("ck_jobs_job_kind_valid"), "jobs", type_="check")
    op.create_check_constraint(
        "job_kind_valid",
        "jobs",
        "kind IN ('strategy','creative_brief','campaign_plan')",
    )
