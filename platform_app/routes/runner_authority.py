"""PostgreSQL-authoritative Platform-to-runner lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from packages.core.contracts.platform_runner import (
    PLATFORM_RUNNER_CONTRACT_VERSION,
    PlatformRunnerDispatch,
    RunnerCompletionCallback,
    RunnerDispatchAcknowledgment,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from platform_app.config import PlatformSettings, get_settings
from platform_app.db.models import (
    AuditEvent,
    Job,
    Project,
    RunnerCallback,
    RunnerDispatch,
    Tenant,
)
from platform_app.db.session import get_database_session
from platform_app.runner_security import (
    RunnerSignatureError,
    bearer_token,
    token_matches,
    verify_callback_signature,
)

router = APIRouter(prefix="/internal/platform/v1/runner", tags=["internal-runner"])

WorkflowKey = Literal[
    "hermes.repo_inventory",
    "hermes.docs_summary",
    "hermes.dependency_summary",
    "hermes.architecture_report",
]


class RunnerJobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    project_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    workflow_key: WorkflowKey
    idempotency_key: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$",
    )
    inputs: dict[str, object] = Field(default_factory=dict)
    deadline_seconds: int = Field(default=300, ge=15, le=1800)


class RunnerJobResponse(BaseModel):
    job_id: str
    tenant_id: str
    project_id: str
    state: str
    workflow_key: str
    dispatch_id: str
    dispatch_status: str
    result: dict[str, object] | None = None
    error: dict[str, object] | None = None
    duplicate: bool = False


class CallbackReceipt(BaseModel):
    status: str = "ok"
    outcome: Literal["accepted", "duplicate"]
    callback_id: str
    job_id: str
    dispatch_id: str
    job_state: str


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _require_admin(
    authorization: str | None,
    settings: PlatformSettings,
) -> None:
    expected = settings.job_admin_token_value
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="runner administration is not configured",
        )
    if not token_matches(bearer_token(authorization), expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid service identity",
        )


def _response_for(
    session: Session,
    *,
    job: Job,
    dispatch: RunnerDispatch,
    duplicate: bool = False,
) -> RunnerJobResponse:
    callback = session.execute(
        select(RunnerCallback)
        .where(RunnerCallback.dispatch_id == dispatch.dispatch_id)
        .order_by(RunnerCallback.received_at.desc())
    ).scalars().first()
    workflow_key = str(job.payload.get("workflow_key", dispatch.workflow_key))
    return RunnerJobResponse(
        job_id=job.job_id,
        tenant_id=job.tenant_id,
        project_id=job.project_id,
        state=job.state,
        workflow_key=workflow_key,
        dispatch_id=dispatch.dispatch_id,
        dispatch_status=dispatch.status,
        result=callback.result if callback is not None else None,
        error=(callback.error if callback is not None else dispatch.safe_error),
        duplicate=duplicate,
    )


def _existing_job_response(
    session: Session,
    tenant_id: str,
    idempotency_key: str,
) -> RunnerJobResponse | None:
    job = session.execute(
        select(Job).where(
            Job.tenant_id == tenant_id,
            Job.idempotency_key == idempotency_key,
        )
    ).scalar_one_or_none()
    if job is None:
        return None
    dispatch = session.execute(
        select(RunnerDispatch).where(RunnerDispatch.job_id == job.job_id)
    ).scalar_one()
    return _response_for(session, job=job, dispatch=dispatch, duplicate=True)


@router.post("/jobs", response_model=RunnerJobResponse, status_code=status.HTTP_202_ACCEPTED)
def create_and_dispatch_runner_job(
    body: RunnerJobCreateRequest,
    session: Annotated[Session, Depends(get_database_session)],
    authorization: Annotated[
        str | None,
        Header(alias="Authorization"),
    ] = None,
) -> RunnerJobResponse:
    settings = get_settings()
    _require_admin(authorization, settings)
    if not settings.runner_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="runner integration is disabled",
        )

    existing = _existing_job_response(session, body.tenant_id, body.idempotency_key)
    if existing is not None:
        return existing

    tenant = session.get(Tenant, body.tenant_id)
    project = session.execute(
        select(Project).where(
            Project.tenant_id == body.tenant_id,
            Project.project_id == body.project_id,
        )
    ).scalar_one_or_none()
    if tenant is None or tenant.status != "active" or project is None or project.status != "active":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="active tenant/project authority record not found",
        )

    now = _utcnow()
    job_id = f"job-{uuid4().hex}"
    dispatch_id = f"dispatch-{uuid4().hex}"
    trace_id = f"trace-{uuid4().hex}"
    correlation_id = f"corr-{uuid4().hex}"
    callback_url = (
        settings.platform_internal_base_url.rstrip("/")
        + "/internal/platform/v1/runner/callbacks"
    )
    dispatch_contract = PlatformRunnerDispatch(
        contract_version=PLATFORM_RUNNER_CONTRACT_VERSION,
        dispatch_id=dispatch_id,
        job_id=job_id,
        workflow_key=body.workflow_key,
        inputs=body.inputs,
        trace_id=trace_id,
        correlation_id=correlation_id,
        idempotency_key=f"dispatch:{body.idempotency_key}",
        callback_url=callback_url,
        dispatched_at=now,
        deadline_at=now + timedelta(seconds=body.deadline_seconds),
    )
    job = Job(
        job_id=job_id,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        kind="runner_task",
        state="queued",
        idempotency_key=body.idempotency_key,
        payload={"workflow_key": body.workflow_key, "inputs": body.inputs},
    )
    dispatch = RunnerDispatch(
        dispatch_id=dispatch_id,
        tenant_id=body.tenant_id,
        job_id=job_id,
        runner_id=settings.runner_id,
        workflow_key=body.workflow_key,
        contract_version=PLATFORM_RUNNER_CONTRACT_VERSION,
        status="pending",
        inputs=body.inputs,
        trace_id=trace_id,
        correlation_id=correlation_id,
        idempotency_key=dispatch_contract.idempotency_key,
        callback_url=callback_url,
        dispatched_at=now,
    )
    session.add_all([job, dispatch])
    session.add(
        AuditEvent(
            event_id=f"audit-{uuid4().hex}",
            tenant_id=body.tenant_id,
            event_type="runner.dispatch.created",
            resource_type="job",
            resource_id=job_id,
            safe_details={"dispatch_id": dispatch_id, "workflow_key": body.workflow_key},
        )
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raced = _existing_job_response(session, body.tenant_id, body.idempotency_key)
        if raced is not None:
            return raced
        raise

    token = settings.runner_dispatch_token_value
    if not token or not settings.runner_dispatch_url.strip():
        dispatch.status = "dispatch_failed"
        dispatch.safe_error = {"code": "runner_transport_not_configured"}
        job.state = "failed"
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="runner transport is not configured",
        )

    try:
        response = httpx.post(
            settings.runner_dispatch_url,
            content=dispatch_contract.model_dump_json().encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=settings.runner_dispatch_timeout_seconds,
        )
        response.raise_for_status()
        acknowledgment = RunnerDispatchAcknowledgment.model_validate_json(response.content)
        if (
            acknowledgment.dispatch_id != dispatch_id
            or acknowledgment.job_id != job_id
            or acknowledgment.runner_id != settings.runner_id
        ):
            raise ValueError("runner acknowledgment does not match authoritative dispatch")
    except (httpx.HTTPError, ValueError) as exc:
        dispatch.status = "dispatch_failed"
        dispatch.response_code = getattr(getattr(exc, "response", None), "status_code", None)
        dispatch.safe_error = {"code": "runner_dispatch_failed"}
        job.state = "failed"
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="runner dispatch failed",
        ) from exc

    dispatch.response_code = response.status_code
    dispatch.acknowledged_at = acknowledgment.received_at
    if acknowledgment.status == "accepted":
        dispatch.status = "accepted"
        job.state = "running"
    else:
        dispatch.status = "rejected"
        dispatch.safe_error = acknowledgment.error.model_dump(mode="json")
        job.state = "failed"
    session.commit()
    return _response_for(session, job=job, dispatch=dispatch)


@router.get("/jobs/{job_id}", response_model=RunnerJobResponse)
def get_runner_job(
    job_id: str,
    tenant_id: str,
    session: Annotated[Session, Depends(get_database_session)],
    authorization: Annotated[
        str | None,
        Header(alias="Authorization"),
    ] = None,
) -> RunnerJobResponse:
    _require_admin(authorization, get_settings())
    job = session.execute(
        select(Job).where(Job.job_id == job_id, Job.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    dispatch = session.execute(
        select(RunnerDispatch).where(
            RunnerDispatch.job_id == job_id,
            RunnerDispatch.tenant_id == tenant_id,
        )
    ).scalar_one()
    return _response_for(session, job=job, dispatch=dispatch)


@router.post("/callbacks", response_model=CallbackReceipt)
async def receive_runner_callback(
    request: Request,
    x_flowbiz_timestamp: Annotated[str, Header(alias="X-FlowBiz-Timestamp")],
    x_flowbiz_signature: Annotated[str, Header(alias="X-FlowBiz-Signature")],
    session: Annotated[Session, Depends(get_database_session)],
) -> CallbackReceipt:
    settings = get_settings()
    raw_body = await request.body()
    try:
        verify_callback_signature(
            secret=settings.runner_callback_secret_value,
            timestamp=x_flowbiz_timestamp,
            signature=x_flowbiz_signature,
            body=raw_body,
            max_clock_skew_seconds=settings.runner_callback_max_clock_skew_seconds,
        )
        callback = RunnerCompletionCallback.model_validate_json(raw_body)
    except (RunnerSignatureError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid callback authentication or contract",
        ) from exc

    dispatch = session.get(RunnerDispatch, callback.dispatch_id)
    job = session.get(Job, callback.job_id)
    if dispatch is None or job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="dispatch not found")
    if (
        dispatch.job_id != callback.job_id
        or dispatch.runner_id != callback.runner_id
        or dispatch.trace_id != callback.trace_id
        or dispatch.correlation_id != callback.correlation_id
        or dispatch.status not in {"accepted", "callback_received"}
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="callback does not match authoritative dispatch",
        )

    existing = session.execute(
        select(RunnerCallback).where(
            RunnerCallback.tenant_id == dispatch.tenant_id,
            RunnerCallback.idempotency_key == callback.idempotency_key,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.callback_id != callback.callback_id
            or existing.dispatch_id != callback.dispatch_id
            or existing.status != callback.status
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="callback idempotency conflict",
            )
        return CallbackReceipt(
            outcome="duplicate",
            callback_id=existing.callback_id,
            job_id=existing.job_id,
            dispatch_id=existing.dispatch_id,
            job_state=job.state,
        )

    stored = RunnerCallback(
        callback_id=callback.callback_id,
        tenant_id=dispatch.tenant_id,
        dispatch_id=callback.dispatch_id,
        job_id=callback.job_id,
        runner_id=callback.runner_id,
        status=callback.status,
        attempt=callback.attempt,
        idempotency_key=callback.idempotency_key,
        result=callback.result,
        error=callback.error.model_dump(mode="json") if callback.error else None,
        trace_id=callback.trace_id,
        correlation_id=callback.correlation_id,
        completed_at=callback.completed_at,
    )
    session.add(stored)
    dispatch.status = "callback_received"
    job.state = callback.status
    job.error = stored.error
    if callback.status == "succeeded":
        job.result_ref = callback.callback_id
    session.add(
        AuditEvent(
            event_id=f"audit-{uuid4().hex}",
            tenant_id=dispatch.tenant_id,
            event_type="runner.callback.accepted",
            resource_type="job",
            resource_id=job.job_id,
            safe_details={
                "dispatch_id": dispatch.dispatch_id,
                "callback_id": callback.callback_id,
                "status": callback.status,
            },
        )
    )
    session.commit()
    return CallbackReceipt(
        outcome="accepted",
        callback_id=callback.callback_id,
        job_id=job.job_id,
        dispatch_id=dispatch.dispatch_id,
        job_state=job.state,
    )
