"""SQLAlchemy models for the PostgreSQL foundation.

The models mirror the PROD-02 contract entities but are not wired into
runtime routes in this PR. Tenant-owned business tables carry a non-null
``tenant_id`` and tenant-leading indexes to support later authorization.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from platform_app.db.base import Base

Timestamp = DateTime(timezone=True)
JsonDict = dict[str, Any]
EMPTY_JSONB = text("'{}'::jsonb")

ROLE_VALUES = "'owner','admin','marketer','viewer','service_identity'"
JOB_STATE_VALUES = "'queued','running','succeeded','failed','dead_letter','cancelled'"
JOB_KIND_VALUES = "'strategy','creative_brief','campaign_plan','runner_task'"
RUNNER_DISPATCH_STATUS_VALUES = (
    "'pending','accepted','rejected','dispatch_failed','callback_received'"
)
RUNNER_CALLBACK_STATUS_VALUES = "'succeeded','failed','cancelled'"
APPROVAL_STATUS_VALUES = "'pending','approved','rejected','cancelled'"
APPROVAL_DECISION_VALUES = "'approve','reject'"


class UserIdentity(Base):
    __tablename__ = "user_identities"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_subject: Mapped[str] = mapped_column(String(256), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(
        Timestamp,
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "external_subject",
            name="uq_user_identities_provider_subject",
        ),
    )


class Tenant(Base):
    __tablename__ = "tenants"

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default="active",
    )
    created_at: Mapped[datetime] = mapped_column(
        Timestamp,
        nullable=False,
        server_default=func.now(),
    )


class Role(Base):
    __tablename__ = "roles"

    role: Mapped[str] = mapped_column(String(32), primary_key=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)


class Membership(Base):
    __tablename__ = "memberships"

    membership_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_identities.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        ForeignKey("roles.role", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default="active",
    )
    created_at: Mapped[datetime] = mapped_column(
        Timestamp,
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(f"role IN ({ROLE_VALUES})", name="membership_role_valid"),
        UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_user"),
        Index("ix_memberships_tenant_role", "tenant_id", "role"),
    )


class Project(Base):
    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default="active",
    )
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("user_identities.user_id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        Timestamp,
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        Timestamp,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (Index("ix_projects_tenant_project", "tenant_id", "project_id"),)


class BusinessProfile(Base):
    __tablename__ = "business_profiles"

    business_profile_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    attributes: Mapped[JsonDict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=EMPTY_JSONB,
    )
    created_at: Mapped[datetime] = mapped_column(
        Timestamp,
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", name="uq_business_profiles_project"),
        Index("ix_business_profiles_tenant_project", "tenant_id", "project_id"),
    )


class ProductService(Base):
    __tablename__ = "product_services"

    product_service_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[JsonDict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=EMPTY_JSONB,
    )

    __table_args__ = (
        Index("ix_product_services_tenant_project", "tenant_id", "project_id"),
    )


class CampaignGoal(Base):
    __tablename__ = "campaign_goals"

    campaign_goal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    goal_type: Mapped[str] = mapped_column(String(80), nullable=False)
    details: Mapped[JsonDict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=EMPTY_JSONB,
    )

    __table_args__ = (Index("ix_campaign_goals_tenant_project", "tenant_id", "project_id"),)


class Strategy(Base):
    __tablename__ = "strategies"

    strategy_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[JsonDict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        Timestamp,
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "version", name="uq_strategies_version"),
        Index("ix_strategies_tenant_project", "tenant_id", "project_id"),
    )


class CreativeBrief(Base):
    __tablename__ = "creative_briefs"

    creative_brief_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[JsonDict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        Timestamp,
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "project_id",
            "version",
            name="uq_creative_briefs_version",
        ),
        Index("ix_creative_briefs_tenant_project", "tenant_id", "project_id"),
    )


class CampaignPlan(Base):
    __tablename__ = "campaign_plans"

    campaign_plan_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[JsonDict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        Timestamp,
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "project_id",
            "version",
            name="uq_campaign_plans_version",
        ),
        Index("ix_campaign_plans_tenant_project", "tenant_id", "project_id"),
    )


class Job(Base):
    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(160))
    payload: Mapped[JsonDict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=EMPTY_JSONB,
    )
    result_ref: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[JsonDict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        Timestamp,
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        Timestamp,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(f"kind IN ({JOB_KIND_VALUES})", name="job_kind_valid"),
        CheckConstraint(f"state IN ({JOB_STATE_VALUES})", name="job_state_valid"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_jobs_tenant_idempotency"),
        Index("ix_jobs_tenant_state", "tenant_id", "state"),
        Index("ix_jobs_tenant_project", "tenant_id", "project_id"),
    )


class JobAttempt(Base):
    __tablename__ = "job_attempts"

    job_attempt_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    error: Mapped[JsonDict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(Timestamp)

    __table_args__ = (
        CheckConstraint(f"state IN ({JOB_STATE_VALUES})", name="job_attempt_state_valid"),
        UniqueConstraint("job_id", "attempt_number", name="uq_job_attempts_job_attempt"),
        Index("ix_job_attempts_tenant_job", "tenant_id", "job_id"),
    )


class RunnerDispatch(Base):
    __tablename__ = "runner_dispatches"

    dispatch_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
        nullable=False,
    )
    runner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    workflow_key: Mapped[str] = mapped_column(String(128), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    inputs: Mapped[JsonDict] = mapped_column(JSONB, nullable=False)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    callback_url: Mapped[str] = mapped_column(String(512), nullable=False)
    response_code: Mapped[int | None] = mapped_column(Integer)
    safe_error: Mapped[JsonDict | None] = mapped_column(JSONB)
    dispatched_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(Timestamp)
    created_at: Mapped[datetime] = mapped_column(
        Timestamp,
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            f"status IN ({RUNNER_DISPATCH_STATUS_VALUES})",
            name="runner_dispatch_status_valid",
        ),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_runner_dispatches_tenant_idempotency",
        ),
        Index("ix_runner_dispatches_tenant_job", "tenant_id", "job_id"),
        Index("ix_runner_dispatches_tenant_status", "tenant_id", "status"),
    )


class RunnerCallback(Base):
    __tablename__ = "runner_callbacks"

    callback_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
    )
    dispatch_id: Mapped[str] = mapped_column(
        ForeignKey("runner_dispatches.dispatch_id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
        nullable=False,
    )
    runner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    result: Mapped[JsonDict | None] = mapped_column(JSONB)
    error: Mapped[JsonDict | None] = mapped_column(JSONB)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        Timestamp,
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            f"status IN ({RUNNER_CALLBACK_STATUS_VALUES})",
            name="runner_callback_status_valid",
        ),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_runner_callbacks_tenant_idempotency",
        ),
        Index("ix_runner_callbacks_tenant_job", "tenant_id", "job_id"),
        Index("ix_runner_callbacks_dispatch", "dispatch_id"),
    )


class UsageRecord(Base):
    __tablename__ = "usage_records"

    usage_record_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.job_id", ondelete="SET NULL"))
    usage_type: Mapped[str] = mapped_column(String(80), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[JsonDict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=EMPTY_JSONB,
    )
    created_at: Mapped[datetime] = mapped_column(
        Timestamp,
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (Index("ix_usage_records_tenant_created", "tenant_id", "created_at"),)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    approval_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.project_id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("user_identities.user_id", ondelete="SET NULL")
    )
    payload: Mapped[JsonDict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=EMPTY_JSONB,
    )
    created_at: Mapped[datetime] = mapped_column(
        Timestamp,
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            f"status IN ({APPROVAL_STATUS_VALUES})",
            name="approval_request_status_valid",
        ),
        Index("ix_approval_requests_tenant_status", "tenant_id", "status"),
    )


class ApprovalDecision(Base):
    __tablename__ = "approval_decisions"

    decision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
    )
    approval_id: Mapped[str] = mapped_column(
        ForeignKey("approval_requests.approval_id", ondelete="CASCADE"),
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    decided_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("user_identities.user_id", ondelete="SET NULL")
    )
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        Timestamp,
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            f"decision IN ({APPROVAL_DECISION_VALUES})",
            name="approval_decision_valid",
        ),
        Index("ix_approval_decisions_tenant_approval", "tenant_id", "approval_id"),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("user_identities.user_id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(String(160), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(120), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(120))
    safe_details: Mapped[JsonDict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=EMPTY_JSONB,
    )
    created_at: Mapped[datetime] = mapped_column(
        Timestamp,
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (Index("ix_audit_events_tenant_created", "tenant_id", "created_at"),)
