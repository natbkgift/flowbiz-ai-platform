"""Workflow event ledger endpoints."""

from __future__ import annotations

import time

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status

from platform_app.auth import APIPrincipal
from platform_app.deps import (
    get_dispatch_record_store,
    get_job_record_store,
    get_request_principal,
    get_runner_dispatcher,
    get_workflow_event_store,
)
from platform_app.dispatch_records import (
    DISPATCH_STATUS_FAILED,
    DISPATCH_STATUS_SENT,
    DispatchListResponse,
    DispatchRequest,
    DispatchResult,
    RunnerDispatchError,
    RunnerDispatcher,
    SQLiteDispatchRecordStore,
)
from platform_app.job_records import JobCreateRequest, JobRecordResponse, SQLiteJobRecordStore
from platform_app.workflow_events import (
    JobStateProjectionResponse,
    WorkflowEventIngestResponse,
    SQLiteWorkflowEventStore,
    WorkflowEventIngestRequest,
    WorkflowEventLookupResponse,
    project_job_state,
)

router = APIRouter(prefix="/v1/platform/workflows")


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
) -> WorkflowEventIngestResponse:
    del principal
    start = time.perf_counter()
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
    store: SQLiteWorkflowEventStore = Depends(get_workflow_event_store),
) -> WorkflowEventLookupResponse:
    del principal
    start = time.perf_counter()
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
    store: SQLiteWorkflowEventStore = Depends(get_workflow_event_store),
) -> JobStateProjectionResponse:
    del principal
    start = time.perf_counter()
    projection = project_job_state(store.list_by_job_id(job_id))
    if projection is None:
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

    _record_observability(
        request,
        route="/v1/platform/workflows/jobs/{job_id}",
        status_code=status.HTTP_200_OK,
        start=start,
    )
    return projection


@router.post("/jobs", status_code=status.HTTP_201_CREATED, response_model=JobRecordResponse)
def create_job_record(
    body: JobCreateRequest,
    request: Request,
    principal: APIPrincipal = Depends(get_request_principal),
    store: SQLiteJobRecordStore = Depends(get_job_record_store),
) -> JobRecordResponse:
    del principal
    start = time.perf_counter()
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
        response_code = dispatcher.dispatch(job, body.payload)
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
