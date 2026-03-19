"""Workflow event ledger endpoints."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request, status

from platform_app.auth import APIPrincipal
from platform_app.deps import get_request_principal, get_workflow_event_store
from platform_app.workflow_events import (
    WorkflowEventIngestResponse,
    SQLiteWorkflowEventStore,
    WorkflowEventIngestRequest,
    WorkflowEventLookupResponse,
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
