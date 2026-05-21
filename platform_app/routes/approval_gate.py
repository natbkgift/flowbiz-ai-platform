"""Safe automation approval gate endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from platform_app.approval_audit import SQLiteApprovalAuditStore
from platform_app.approval_models import (
    AUDIT_EVENT_DECISION_MADE,
    DECISION_DENY,
    DECISION_NEEDS_APPROVAL,
    ActionProposal,
    AuditRecord,
    DecisionResponse,
)
from platform_app.approval_policy import SQLiteApprovalPolicyStore
from platform_app.approval_records import (
    OUTCOME_ABORTED,
    OUTCOME_EXECUTED,
    ProposalOutcomeRecord,
    SQLiteApprovalRecordStore,
)
from platform_app.connector_store import SQLiteConnectorStore, StoredConnector
from platform_app.deps import (
    get_approval_audit_store,
    get_approval_connector_store,
    get_approval_policy_store,
    get_approval_record_store,
)
from platform_app.risk_scoring import score_risk

router = APIRouter(prefix="/v1/gate", tags=["approval-gate"])


class ProposalOutcomeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["executed", "aborted"]
    execution_timestamp: datetime


class ProposalOutcomeResponse(BaseModel):
    status: str = "ok"
    outcome: ProposalOutcomeRecord


def _record_observability(request: Request, route: str, status_code: int, start: float) -> None:
    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    obs = getattr(request.app.state, "observability", None)
    if obs is not None:
        obs.record(route=route, status_code=status_code, duration_ms=duration_ms)


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization bearer token",
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization bearer token",
        )
    return token.strip()


def _authenticate_connector(
    authorization: str | None = Header(default=None, alias="Authorization"),
    store: SQLiteConnectorStore = Depends(get_approval_connector_store),
) -> StoredConnector:
    connector = store.authenticate_api_key(_extract_bearer_token(authorization))
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid connector API key",
        )
    return connector


def _build_decision(
    *,
    proposal: ActionProposal,
    connector: StoredConnector,
    policy_store: SQLiteApprovalPolicyStore,
) -> DecisionResponse:
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    decision_id = str(uuid4())
    if proposal.connector_id != connector.connector_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Connector API key does not match proposal connector_id",
        )

    risk = score_risk(proposal)
    if proposal.action_class not in connector.allowed_action_classes:
        return DecisionResponse(
            proposal_id=proposal.proposal_id,
            decision=DECISION_DENY,
            decision_id=decision_id,
            decision_timestamp=now,
            reason_code="CONNECTOR_ACTION_CLASS_NOT_PERMITTED",
            reason_detail=(
                f"Connector {connector.connector_id} is not permitted to propose "
                f"{proposal.action_class}"
            ),
            risk_level=risk.risk_level,  # type: ignore[arg-type]
        )

    policy_decision = policy_store.evaluate_policy(
        proposal=proposal,
        risk_level=risk.risk_level,
    )
    approval_queue_id = (
        f"approval-{proposal.proposal_id}"
        if policy_decision.decision == DECISION_NEEDS_APPROVAL
        else None
    )
    return DecisionResponse(
        proposal_id=proposal.proposal_id,
        decision=policy_decision.decision,  # type: ignore[arg-type]
        decision_id=decision_id,
        decision_timestamp=now,
        reason_code=policy_decision.reason_code,
        reason_detail=policy_decision.reason_detail,
        risk_level=risk.risk_level,  # type: ignore[arg-type]
        approval_required_from=policy_decision.approval_required_from,
        approval_queue_id=approval_queue_id,
        rollback_checklist_id=None,
    )


def _audit_record_for_decision(
    *,
    proposal: ActionProposal,
    decision: DecisionResponse,
) -> AuditRecord:
    proposal_snapshot = proposal.model_dump(mode="json")
    return AuditRecord(
        audit_id=str(uuid4()),
        event_type=AUDIT_EVENT_DECISION_MADE,
        proposal_id=proposal.proposal_id,
        decision_id=decision.decision_id,
        timestamp=decision.decision_timestamp,
        actor=proposal.connector_id,
        action_class=proposal.action_class,
        target_system=proposal.target_system,
        target_scope=proposal_snapshot["target_scope"],
        risk_level=decision.risk_level,
        decision=decision.decision,
        reason_code=decision.reason_code,
        payload_hash=proposal.payload_hash,
        full_proposal_snapshot=proposal_snapshot,
    )


@router.post("/proposals", response_model=DecisionResponse)
def submit_proposal(
    body: ActionProposal,
    request: Request,
    connector: StoredConnector = Depends(_authenticate_connector),
    policy_store: SQLiteApprovalPolicyStore = Depends(get_approval_policy_store),
    record_store: SQLiteApprovalRecordStore = Depends(get_approval_record_store),
    audit_store: SQLiteApprovalAuditStore = Depends(get_approval_audit_store),
) -> DecisionResponse:
    start = time.perf_counter()
    existing = record_store.get_decision_by_proposal_id(body.proposal_id)
    if existing is not None:
        _record_observability(
            request,
            route="/v1/gate/proposals",
            status_code=status.HTTP_200_OK,
            start=start,
        )
        return existing

    decision = _build_decision(
        proposal=body,
        connector=connector,
        policy_store=policy_store,
    )
    try:
        audit_store.append_record(_audit_record_for_decision(proposal=body, decision=decision))
    except Exception as exc:
        _record_observability(
            request,
            route="/v1/gate/proposals",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            start=start,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Approval gate audit write failed",
        ) from exc

    stored = record_store.create_decision(proposal=body, decision=decision)
    _record_observability(
        request,
        route="/v1/gate/proposals",
        status_code=status.HTTP_200_OK,
        start=start,
    )
    return stored


@router.get("/proposals/{proposal_id}/decision", response_model=DecisionResponse)
def get_proposal_decision(
    proposal_id: str,
    request: Request,
    connector: StoredConnector = Depends(_authenticate_connector),
    record_store: SQLiteApprovalRecordStore = Depends(get_approval_record_store),
) -> DecisionResponse:
    del connector
    start = time.perf_counter()
    decision = record_store.get_decision_by_proposal_id(proposal_id)
    if decision is None:
        _record_observability(
            request,
            route="/v1/gate/proposals/{proposal_id}/decision",
            status_code=status.HTTP_404_NOT_FOUND,
            start=start,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Decision record not found: {proposal_id}",
        )
    _record_observability(
        request,
        route="/v1/gate/proposals/{proposal_id}/decision",
        status_code=status.HTTP_200_OK,
        start=start,
    )
    return decision


@router.post(
    "/proposals/{proposal_id}/outcome",
    response_model=ProposalOutcomeResponse,
)
def record_proposal_outcome(
    proposal_id: str,
    body: ProposalOutcomeRequest,
    request: Request,
    connector: StoredConnector = Depends(_authenticate_connector),
    record_store: SQLiteApprovalRecordStore = Depends(get_approval_record_store),
) -> ProposalOutcomeResponse:
    del connector
    start = time.perf_counter()
    if body.outcome not in {OUTCOME_EXECUTED, OUTCOME_ABORTED}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported proposal outcome",
        )
    try:
        outcome = record_store.record_outcome(
            proposal_id=proposal_id,
            outcome=body.outcome,
            execution_timestamp=body.execution_timestamp.astimezone(timezone.utc).isoformat(
                timespec="milliseconds"
            ),
        )
    except KeyError as exc:
        _record_observability(
            request,
            route="/v1/gate/proposals/{proposal_id}/outcome",
            status_code=status.HTTP_404_NOT_FOUND,
            start=start,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    _record_observability(
        request,
        route="/v1/gate/proposals/{proposal_id}/outcome",
        status_code=status.HTTP_200_OK,
        start=start,
    )
    return ProposalOutcomeResponse(outcome=outcome)
