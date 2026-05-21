"""Workflow event ledger endpoints."""

from __future__ import annotations

import time

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from platform_app.admission_policy import SQLiteAdmissionPolicyStore
from platform_app.auth import APIPrincipal
from platform_app.deps import (
    get_admission_policy_store,
    get_dispatch_record_store,
    get_job_record_store,
    get_request_principal,
    get_runner_dispatcher,
    get_workflow_event_store,
)
from platform_app.dispatch_records import (
    CALLBACK_STATUS_FAILED,
    CALLBACK_STATUS_IN_PROGRESS,
    CALLBACK_STATUS_SUCCESS,
    DISPATCH_STATUS_FAILED,
    DISPATCH_STATUS_SENT,
    DispatchListResponse,
    DispatchRequest,
    DispatchResult,
    RunnerDispatchError,
    RunnerDispatcher,
    SQLiteDispatchRecordStore,
    hash_callback_token,
)
from platform_app.job_records import (
    JobCreateRequest,
    JobListItemResponse,
    JobListResponse,
    JobRecordResponse,
    INITIAL_JOB_STATUS,
    SQLiteJobRecordStore,
)
from platform_app.workflow_events import (
    JobStateProjectionResponse,
    WorkflowEventIngestResponse,
    SQLiteWorkflowEventStore,
    WorkflowEventIngestRequest,
    WorkflowEventLookupResponse,
    project_job_state,
)

router = APIRouter(prefix="/v1/platform/workflows", tags=["internal"])

CALLBACK_SOURCE = "runner_callback"
CALLBACK_STATUS_TO_EVENT_STATUS = {
    CALLBACK_STATUS_IN_PROGRESS: "running",
    CALLBACK_STATUS_SUCCESS: "succeeded",
    CALLBACK_STATUS_FAILED: "failed",
}


class WorkflowDispatchCallbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    dispatch_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    occurred_at: datetime
    result_summary: dict[str, object] | None = None


class WorkflowDispatchCallbackResponse(BaseModel):
    status: str
    outcome: str
    job_id: str
    dispatch_id: str
    current_status: str
    raw_status: str
    occurred_at: str


def _projection_from_job_record(record: JobRecordResponse) -> JobStateProjectionResponse:
    return JobStateProjectionResponse(
        job_id=record.job_id,
        current_status=record.status,
        raw_status=record.status,
        execution_id=None,
        client_id=record.client_id,
        workflow_key=record.workflow_key,
        received_at=record.created_at,
        source="job_admission" if record.status == INITIAL_JOB_STATUS else None,
        event_count=0,
    )


def _record_observability(request: Request, route: str, status_code: int, start: float) -> None:
    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    obs = getattr(request.app.state, "observability", None)
    if obs is not None:
        obs.record(route=route, status_code=status_code, duration_ms=duration_ms)


@router.post(
    "/events",
    status_code=status.HTTP_201_CREATED,
    response_model=WorkflowEventIngestResponse,
)
def intake_workflow_event(
    body: WorkflowEventIngestRequest,
    request: Request,
    principal: APIPrincipal = Depends(get_request_principal),
    store: SQLiteWorkflowEventStore = Depends(get_workflow_event_store),
    job_store: SQLiteJobRecordStore = Depends(get_job_record_store),
) -> WorkflowEventIngestResponse:
    del principal
    start = time.perf_counter()
    job = job_store.get_job(body.job_id)
    if job is None:
        _record_observability(
            request,
            route="/v1/platform/workflows/events",
            status_code=status.HTTP_404_NOT_FOUND,
            start=start,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job record not found: {body.job_id}",
        )
    if job.client_id != body.client_id or job.workflow_key != body.workflow_key:
        _record_observability(
            request,
            route="/v1/platform/workflows/events",
            status_code=status.HTTP_409_CONFLICT,
            start=start,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Workflow event does not match admitted job contract for "
                f"{body.job_id}"
            ),
        )
    record = store.append_event(body)
    _record_observability(
        request,
        route="/v1/platform/workflows/events",
        status_code=status.HTTP_201_CREATED,
        start=start,
    )
    return WorkflowEventIngestResponse(record=record)


@router.get("/jobs/{job_id}/events")
def lookup_workflow_events(
    job_id: str,
    request: Request,
    principal: APIPrincipal = Depends(get_request_principal),
    job_store: SQLiteJobRecordStore = Depends(get_job_record_store),
    store: SQLiteWorkflowEventStore = Depends(get_workflow_event_store),
) -> WorkflowEventLookupResponse:
    del principal
    start = time.perf_counter()
    if job_store.get_job(job_id) is None:
        _record_observability(
            request,
            route="/v1/platform/workflows/jobs/{job_id}/events",
            status_code=status.HTTP_404_NOT_FOUND,
            start=start,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job record not found: {job_id}",
        )
    records = store.list_by_job_id(job_id)
    _record_observability(
        request,
        route="/v1/platform/workflows/jobs/{job_id}/events",
        status_code=status.HTTP_200_OK,
        start=start,
    )
    return WorkflowEventLookupResponse(job_id=job_id, count=len(records), records=records)


@router.get("/jobs/{job_id}", response_model=JobStateProjectionResponse)
def lookup_projected_job_state(
    job_id: str,
    request: Request,
    principal: APIPrincipal = Depends(get_request_principal),
    job_store: SQLiteJobRecordStore = Depends(get_job_record_store),
    store: SQLiteWorkflowEventStore = Depends(get_workflow_event_store),
) -> JobStateProjectionResponse:
    del principal
    start = time.perf_counter()
    job = job_store.get_job(job_id)
    if job is None:
        _record_observability(
            request,
            route="/v1/platform/workflows/jobs/{job_id}",
            status_code=status.HTTP_404_NOT_FOUND,
            start=start,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job not found: {job_id}",
        )
    projection = project_job_state(store.list_by_job_id(job_id))
    if projection is None:
        projection = _projection_from_job_record(job)

    _record_observability(
        request,
        route="/v1/platform/workflows/jobs/{job_id}",
        status_code=status.HTTP_200_OK,
        start=start,
    )
    return projection


@router.get("/jobs", response_model=JobListResponse)
def list_jobs(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    principal: APIPrincipal = Depends(get_request_principal),
    job_store: SQLiteJobRecordStore = Depends(get_job_record_store),
    event_store: SQLiteWorkflowEventStore = Depends(get_workflow_event_store),
) -> JobListResponse:
    del principal
    start = time.perf_counter()
    records = job_store.list_jobs(limit=limit)
    jobs: list[JobListItemResponse] = []
    for record in records:
        projection = project_job_state(event_store.list_by_job_id(record.job_id))
        jobs.append(
            JobListItemResponse(
                job_id=record.job_id,
                client_id=record.client_id,
                workflow_key=record.workflow_key,
                admission_status=record.status,
                current_status=projection.current_status if projection is not None else record.status,
                raw_status=projection.raw_status if projection is not None else None,
                created_at=record.created_at,
                latest_received_at=projection.received_at if projection is not None else None,
            )
        )
    _record_observability(
        request,
        route="/v1/platform/workflows/jobs",
        status_code=status.HTTP_200_OK,
        start=start,
    )
    return JobListResponse(count=len(jobs), jobs=jobs)


@router.post("/jobs", status_code=status.HTTP_201_CREATED, response_model=JobRecordResponse)
def create_job_record(
    body: JobCreateRequest,
    request: Request,
    principal: APIPrincipal = Depends(get_request_principal),
    store: SQLiteJobRecordStore = Depends(get_job_record_store),
    policy_store: SQLiteAdmissionPolicyStore = Depends(get_admission_policy_store),
) -> JobRecordResponse:
    del principal
    start = time.perf_counter()
    decision = policy_store.evaluate_admission(body.client_id)
    if not decision.allowed:
        status_code = (
            status.HTTP_403_FORBIDDEN
            if decision.code == "client_disabled"
            else status.HTTP_429_TOO_MANY_REQUESTS
        )
        _record_observability(
            request,
            route="/v1/platform/workflows/jobs",
            status_code=status_code,
            start=start,
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": decision.code, "message": decision.message},
        )
    record = store.create_job(body)
    _record_observability(
        request,
        route="/v1/platform/workflows/jobs",
        status_code=status.HTTP_201_CREATED,
        start=start,
    )
    return record


@router.post(
    "/jobs/{job_id}/dispatch",
    response_model=DispatchResult,
)
def dispatch_job_to_runner(
    job_id: str,
    body: DispatchRequest,
    request: Request,
    principal: APIPrincipal = Depends(get_request_principal),
    job_store: SQLiteJobRecordStore = Depends(get_job_record_store),
    dispatch_store: SQLiteDispatchRecordStore = Depends(get_dispatch_record_store),
    dispatcher: RunnerDispatcher = Depends(get_runner_dispatcher),
) -> DispatchResult:
    del principal
    start = time.perf_counter()
    job = job_store.get_job(job_id)
    if job is None:
        _record_observability(
            request,
            route="/v1/platform/workflows/jobs/{job_id}/dispatch",
            status_code=status.HTTP_404_NOT_FOUND,
            start=start,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job record not found: {job_id}",
        )

    pending = dispatch_store.create_pending_dispatch(
        job=job,
        target_url=dispatcher.target_url,
        payload=body.payload,
    )

    try:
        callback_token = dispatcher.issue_callback_token(
            job_id=job.job_id,
            dispatch_id=pending.dispatch_id,
        )
        dispatch_store.set_callback_token_hash(
            dispatch_id=pending.dispatch_id,
            callback_token_hash=hash_callback_token(callback_token),
        )
        response_code = dispatcher.dispatch(
            job,
            body.payload,
            dispatch_id=pending.dispatch_id,
            callback_token=callback_token,
        )
    except RunnerDispatchError as exc:
        finalized = dispatch_store.finalize_dispatch(
            dispatch_id=pending.dispatch_id,
            status=DISPATCH_STATUS_FAILED,
            response_code=exc.response_code,
            error=str(exc),
            sent_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        )
        _record_observability(
            request,
            route="/v1/platform/workflows/jobs/{job_id}/dispatch",
            status_code=status.HTTP_502_BAD_GATEWAY,
            start=start,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(exc), "dispatch": finalized.model_dump()},
        ) from exc
    except ValueError as exc:
        finalized = dispatch_store.finalize_dispatch(
            dispatch_id=pending.dispatch_id,
            status=DISPATCH_STATUS_FAILED,
            response_code=None,
            error=str(exc),
            sent_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        )
        _record_observability(
            request,
            route="/v1/platform/workflows/jobs/{job_id}/dispatch",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            start=start,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": str(exc), "dispatch": finalized.model_dump()},
        ) from exc

    finalized = dispatch_store.finalize_dispatch(
        dispatch_id=pending.dispatch_id,
        status=DISPATCH_STATUS_SENT,
        response_code=response_code,
        error=None,
        sent_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    )
    _record_observability(
        request,
        route="/v1/platform/workflows/jobs/{job_id}/dispatch",
        status_code=status.HTTP_200_OK,
        start=start,
    )
    return DispatchResult(dispatch=finalized)


@router.post(
    "/jobs/{job_id}/callback",
    response_model=WorkflowDispatchCallbackResponse,
)
def receive_job_callback(
    job_id: str,
    body: WorkflowDispatchCallbackRequest,
    request: Request,
    x_flowbiz_callback_token: str | None = Header(default=None, alias="X-FlowBiz-Callback-Token"),
    job_store: SQLiteJobRecordStore = Depends(get_job_record_store),
    dispatch_store: SQLiteDispatchRecordStore = Depends(get_dispatch_record_store),
    event_store: SQLiteWorkflowEventStore = Depends(get_workflow_event_store),
) -> WorkflowDispatchCallbackResponse:
    start = time.perf_counter()
    if x_flowbiz_callback_token is None:
        _record_observability(
            request,
            route="/v1/platform/workflows/jobs/{job_id}/callback",
            status_code=status.HTTP_401_UNAUTHORIZED,
            start=start,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-FlowBiz-Callback-Token",
        )
    if body.job_id != job_id:
        _record_observability(
            request,
            route="/v1/platform/workflows/jobs/{job_id}/callback",
            status_code=status.HTTP_409_CONFLICT,
            start=start,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Callback job_id does not match route job_id",
        )

    if body.status not in CALLBACK_STATUS_TO_EVENT_STATUS:
        _record_observability(
            request,
            route="/v1/platform/workflows/jobs/{job_id}/callback",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            start=start,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported callback status",
        )

    job = job_store.get_job(job_id)
    if job is None:
        _record_observability(
            request,
            route="/v1/platform/workflows/jobs/{job_id}/callback",
            status_code=status.HTTP_404_NOT_FOUND,
            start=start,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job record not found: {job_id}",
        )

    if not dispatch_store.verify_callback_token(
        dispatch_id=body.dispatch_id,
        provided_token=x_flowbiz_callback_token,
    ):
        _record_observability(
            request,
            route="/v1/platform/workflows/jobs/{job_id}/callback",
            status_code=status.HTTP_401_UNAUTHORIZED,
            start=start,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid callback token",
        )

    callback_received_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    callback_occurred_at = body.occurred_at.astimezone(timezone.utc).isoformat(timespec="milliseconds")

    try:
        outcome, dispatch = dispatch_store.apply_callback(
            dispatch_id=body.dispatch_id,
            job_id=job_id,
            callback_status=body.status,
            callback_occurred_at=callback_occurred_at,
            callback_received_at=callback_received_at,
        )
    except KeyError as exc:
        _record_observability(
            request,
            route="/v1/platform/workflows/jobs/{job_id}/callback",
            status_code=status.HTTP_404_NOT_FOUND,
            start=start,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        _record_observability(
            request,
            route="/v1/platform/workflows/jobs/{job_id}/callback",
            status_code=status.HTTP_409_CONFLICT,
            start=start,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    if outcome == "stale":
        _record_observability(
            request,
            route="/v1/platform/workflows/jobs/{job_id}/callback",
            status_code=status.HTTP_409_CONFLICT,
            start=start,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Stale callback rejected",
        )
    if outcome == "invalid_transition":
        _record_observability(
            request,
            route="/v1/platform/workflows/jobs/{job_id}/callback",
            status_code=status.HTTP_409_CONFLICT,
            start=start,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invalid callback transition rejected",
        )

    event_status = CALLBACK_STATUS_TO_EVENT_STATUS[body.status]
    if outcome == "accepted":
        event_store.append_event(
            WorkflowEventIngestRequest.model_validate(
                {
                    "job_id": job_id,
                    "client_id": job.client_id,
                    "workflow_key": job.workflow_key,
                    "status": event_status,
                    "source": CALLBACK_SOURCE,
                    "dispatch_id": body.dispatch_id,
                    "callback_status": body.status,
                    "occurred_at": callback_occurred_at,
                    "result_summary": body.result_summary,
                }
            )
        )

    projection = project_job_state(event_store.list_by_job_id(job_id))
    current_status = projection.current_status if projection is not None else job.status
    raw_status = projection.raw_status if projection is not None else event_status
    _record_observability(
        request,
        route="/v1/platform/workflows/jobs/{job_id}/callback",
        status_code=status.HTTP_200_OK,
        start=start,
    )
    return WorkflowDispatchCallbackResponse(
        status="ok",
        outcome=outcome,
        job_id=job_id,
        dispatch_id=dispatch.dispatch_id,
        current_status=current_status,
        raw_status=raw_status,
        occurred_at=callback_occurred_at,
    )


@router.get(
    "/jobs/{job_id}/dispatches",
    response_model=DispatchListResponse,
)
def list_job_dispatches(
    job_id: str,
    request: Request,
    principal: APIPrincipal = Depends(get_request_principal),
    job_store: SQLiteJobRecordStore = Depends(get_job_record_store),
    dispatch_store: SQLiteDispatchRecordStore = Depends(get_dispatch_record_store),
) -> DispatchListResponse:
    del principal
    start = time.perf_counter()
    job = job_store.get_job(job_id)
    if job is None:
        _record_observability(
            request,
            route="/v1/platform/workflows/jobs/{job_id}/dispatches",
            status_code=status.HTTP_404_NOT_FOUND,
            start=start,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job record not found: {job_id}",
        )

    dispatches = dispatch_store.list_by_job_id(job_id)
    _record_observability(
        request,
        route="/v1/platform/workflows/jobs/{job_id}/dispatches",
        status_code=status.HTTP_200_OK,
        start=start,
    )
    return DispatchListResponse(job_id=job_id, count=len(dispatches), dispatches=dispatches)


@router.get("/jobs/{job_id}/record", response_model=JobRecordResponse)
def lookup_job_record(
    job_id: str,
    request: Request,
    principal: APIPrincipal = Depends(get_request_principal),
    store: SQLiteJobRecordStore = Depends(get_job_record_store),
) -> JobRecordResponse:
    del principal
    start = time.perf_counter()
    record = store.get_job(job_id)
    if record is None:
        _record_observability(
            request,
            route="/v1/platform/workflows/jobs/{job_id}/record",
            status_code=status.HTTP_404_NOT_FOUND,
            start=start,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job record not found: {job_id}",
        )

    _record_observability(
        request,
        route="/v1/platform/workflows/jobs/{job_id}/record",
        status_code=status.HTTP_200_OK,
        start=start,
    )
    return record
