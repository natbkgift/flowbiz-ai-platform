"""SQLite-backed proposal, decision, and outcome records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Any, Literal

from pydantic import BaseModel

from platform_app.approval_models import ActionProposal, DecisionResponse
from platform_app.sqlite_utils import connect_sqlite, prepare_sqlite_database

OUTCOME_EXECUTED = "executed"
OUTCOME_ABORTED = "aborted"


class ProposalOutcomeRecord(BaseModel):
    proposal_id: str
    outcome: Literal["executed", "aborted"]
    execution_timestamp: str
    recorded_at: str


@dataclass(frozen=True)
class StoredDecisionRecord:
    decision_id: str
    proposal_id: str
    decision: str
    decision_timestamp: str
    reason_code: str
    reason_detail: str
    risk_level: str
    approval_required_from: str | None
    approval_queue_id: str | None
    rollback_checklist_id: str | None

    def to_model(self) -> DecisionResponse:
        return DecisionResponse(
            proposal_id=self.proposal_id,
            decision=self.decision,  # type: ignore[arg-type]
            decision_id=self.decision_id,
            decision_timestamp=self.decision_timestamp,
            reason_code=self.reason_code,
            reason_detail=self.reason_detail,
            risk_level=self.risk_level,  # type: ignore[arg-type]
            approval_required_from=self.approval_required_from,
            approval_queue_id=self.approval_queue_id,
            rollback_checklist_id=self.rollback_checklist_id,
        )


class SQLiteApprovalRecordStore:
    """SQLite-backed store for approval proposals and decisions."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = Lock()
        self._ensure_parent_dir()
        self._init_schema()

    def _ensure_parent_dir(self) -> None:
        parent = Path(self._db_path).expanduser().resolve().parent
        parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self._db_path)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            prepare_sqlite_database(conn)
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS approval_proposals (
                  proposal_id TEXT PRIMARY KEY,
                  connector_id TEXT NOT NULL,
                  action_class TEXT NOT NULL,
                  target_system TEXT NOT NULL,
                  target_scope TEXT NOT NULL,
                  mutation_type TEXT NOT NULL,
                  payload_summary TEXT NOT NULL,
                  payload_hash TEXT NOT NULL,
                  triggering_signal TEXT NOT NULL,
                  submitted_at TEXT NOT NULL,
                  requested_by TEXT NOT NULL,
                  received_at TEXT NOT NULL,
                  full_payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS approval_decisions (
                  decision_id TEXT PRIMARY KEY,
                  proposal_id TEXT NOT NULL UNIQUE,
                  decision TEXT NOT NULL,
                  decision_timestamp TEXT NOT NULL,
                  reason_code TEXT NOT NULL,
                  reason_detail TEXT NOT NULL,
                  risk_level TEXT NOT NULL,
                  approval_required_from TEXT NULL,
                  approval_queue_id TEXT NULL,
                  rollback_checklist_id TEXT NULL,
                  FOREIGN KEY (proposal_id)
                    REFERENCES approval_proposals(proposal_id)
                    ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS approval_outcomes (
                  proposal_id TEXT PRIMARY KEY,
                  outcome TEXT NOT NULL,
                  execution_timestamp TEXT NOT NULL,
                  recorded_at TEXT NOT NULL,
                  FOREIGN KEY (proposal_id)
                    REFERENCES approval_proposals(proposal_id)
                    ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_approval_proposals_connector_id
                  ON approval_proposals(connector_id, received_at DESC);

                CREATE INDEX IF NOT EXISTS idx_approval_decisions_proposal_id
                  ON approval_decisions(proposal_id);
                """
            )

    def get_decision_by_proposal_id(self, proposal_id: str) -> DecisionResponse | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                  decision_id,
                  proposal_id,
                  decision,
                  decision_timestamp,
                  reason_code,
                  reason_detail,
                  risk_level,
                  approval_required_from,
                  approval_queue_id,
                  rollback_checklist_id
                FROM approval_decisions
                WHERE proposal_id = ?
                """,
                (proposal_id,),
            ).fetchone()
        stored = _row_to_decision(row)
        return stored.to_model() if stored is not None else None

    def create_decision(
        self,
        *,
        proposal: ActionProposal,
        decision: DecisionResponse,
    ) -> DecisionResponse:
        proposal_payload = proposal.model_dump(mode="json")
        target_scope = json.dumps(
            proposal_payload["target_scope"],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        triggering_signal = json.dumps(
            proposal_payload["triggering_signal"],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        full_payload = json.dumps(
            proposal_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        received_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")

        with self._lock:
            with self._connect() as conn:
                existing = conn.execute(
                    """
                    SELECT
                      decision_id,
                      proposal_id,
                      decision,
                      decision_timestamp,
                      reason_code,
                      reason_detail,
                      risk_level,
                      approval_required_from,
                      approval_queue_id,
                      rollback_checklist_id
                    FROM approval_decisions
                    WHERE proposal_id = ?
                    """,
                    (proposal.proposal_id,),
                ).fetchone()
                if existing is not None:
                    return _row_to_decision(existing).to_model()  # type: ignore[union-attr]

                conn.execute(
                    """
                    INSERT OR IGNORE INTO approval_proposals (
                      proposal_id,
                      connector_id,
                      action_class,
                      target_system,
                      target_scope,
                      mutation_type,
                      payload_summary,
                      payload_hash,
                      triggering_signal,
                      submitted_at,
                      requested_by,
                      received_at,
                      full_payload
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        proposal.proposal_id,
                        proposal.connector_id,
                        proposal.action_class,
                        proposal.target_system,
                        target_scope,
                        proposal.mutation_type,
                        proposal.payload_summary,
                        proposal.payload_hash,
                        triggering_signal,
                        _to_utc_isoformat(proposal.submitted_at),
                        proposal.requested_by,
                        received_at,
                        full_payload,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO approval_decisions (
                      decision_id,
                      proposal_id,
                      decision,
                      decision_timestamp,
                      reason_code,
                      reason_detail,
                      risk_level,
                      approval_required_from,
                      approval_queue_id,
                      rollback_checklist_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision.decision_id,
                        decision.proposal_id,
                        decision.decision,
                        decision.decision_timestamp,
                        decision.reason_code,
                        decision.reason_detail,
                        decision.risk_level,
                        decision.approval_required_from,
                        decision.approval_queue_id,
                        decision.rollback_checklist_id,
                    ),
                )
        return decision

    def record_outcome(
        self,
        *,
        proposal_id: str,
        outcome: Literal["executed", "aborted"],
        execution_timestamp: str,
    ) -> ProposalOutcomeRecord:
        recorded_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        with self._lock:
            with self._connect() as conn:
                proposal = conn.execute(
                    "SELECT 1 FROM approval_proposals WHERE proposal_id = ?",
                    (proposal_id,),
                ).fetchone()
                if proposal is None:
                    raise KeyError(f"Proposal record not found: {proposal_id}")
                conn.execute(
                    """
                    INSERT INTO approval_outcomes (
                      proposal_id,
                      outcome,
                      execution_timestamp,
                      recorded_at
                    )
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(proposal_id) DO UPDATE SET
                      outcome = excluded.outcome,
                      execution_timestamp = excluded.execution_timestamp,
                      recorded_at = excluded.recorded_at
                    """,
                    (proposal_id, outcome, execution_timestamp, recorded_at),
                )

        return ProposalOutcomeRecord(
            proposal_id=proposal_id,
            outcome=outcome,
            execution_timestamp=execution_timestamp,
            recorded_at=recorded_at,
        )

    def get_proposal_snapshot(self, proposal_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT full_payload FROM approval_proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(str(row["full_payload"]))


def resolve_approval_gate_db_path(path_value: str) -> str:
    path = Path(path_value)
    if path.is_absolute():
        return str(path)
    return str((Path.cwd() / path).resolve())


def _to_utc_isoformat(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def _row_to_decision(row: sqlite3.Row | None) -> StoredDecisionRecord | None:
    if row is None:
        return None
    return StoredDecisionRecord(
        decision_id=str(row["decision_id"]),
        proposal_id=str(row["proposal_id"]),
        decision=str(row["decision"]),
        decision_timestamp=str(row["decision_timestamp"]),
        reason_code=str(row["reason_code"]),
        reason_detail=str(row["reason_detail"]),
        risk_level=str(row["risk_level"]),
        approval_required_from=(
            str(row["approval_required_from"]) if row["approval_required_from"] else None
        ),
        approval_queue_id=str(row["approval_queue_id"]) if row["approval_queue_id"] else None,
        rollback_checklist_id=(
            str(row["rollback_checklist_id"])
            if row["rollback_checklist_id"]
            else None
        ),
    )
