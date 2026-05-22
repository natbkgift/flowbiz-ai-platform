"""Append-only approval gate audit log."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from threading import Lock

from platform_app.approval_models import AuditRecord
from platform_app.sqlite_utils import connect_sqlite, prepare_sqlite_database


class SQLiteApprovalAuditStore:
    """SQLite-backed append-only audit log for gate decisions."""

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
                CREATE TABLE IF NOT EXISTS approval_audit_events (
                  audit_id TEXT PRIMARY KEY,
                  event_type TEXT NOT NULL,
                  proposal_id TEXT NOT NULL,
                  decision_id TEXT NULL,
                  timestamp TEXT NOT NULL,
                  actor TEXT NOT NULL,
                  action_class TEXT NOT NULL,
                  target_system TEXT NOT NULL,
                  target_scope TEXT NOT NULL,
                  risk_level TEXT NOT NULL,
                  decision TEXT NULL,
                  reason_code TEXT NULL,
                  payload_hash TEXT NOT NULL,
                  full_proposal_snapshot TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_approval_audit_proposal_id
                  ON approval_audit_events(proposal_id, timestamp, audit_id);

                CREATE INDEX IF NOT EXISTS idx_approval_audit_decision
                  ON approval_audit_events(decision, timestamp);
                """
            )

    def append_record(self, record: AuditRecord) -> AuditRecord:
        target_scope = json.dumps(
            record.target_scope,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        full_proposal_snapshot = json.dumps(
            record.full_proposal_snapshot,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO approval_audit_events (
                      audit_id,
                      event_type,
                      proposal_id,
                      decision_id,
                      timestamp,
                      actor,
                      action_class,
                      target_system,
                      target_scope,
                      risk_level,
                      decision,
                      reason_code,
                      payload_hash,
                      full_proposal_snapshot
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.audit_id,
                        record.event_type,
                        record.proposal_id,
                        record.decision_id,
                        record.timestamp,
                        record.actor,
                        record.action_class,
                        record.target_system,
                        target_scope,
                        record.risk_level,
                        record.decision,
                        record.reason_code,
                        record.payload_hash,
                        full_proposal_snapshot,
                    ),
                )
        return record

    def list_by_proposal_id(self, proposal_id: str) -> list[AuditRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  audit_id,
                  event_type,
                  proposal_id,
                  decision_id,
                  timestamp,
                  actor,
                  action_class,
                  target_system,
                  target_scope,
                  risk_level,
                  decision,
                  reason_code,
                  payload_hash,
                  full_proposal_snapshot
                FROM approval_audit_events
                WHERE proposal_id = ?
                ORDER BY timestamp ASC, audit_id ASC
                """,
                (proposal_id,),
            ).fetchall()
        return [_row_to_audit_record(row) for row in rows]

    def count_by_proposal_id(self, proposal_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM approval_audit_events
                WHERE proposal_id = ?
                """,
                (proposal_id,),
            ).fetchone()
        return int(row["count"]) if row is not None else 0


def _row_to_audit_record(row: sqlite3.Row) -> AuditRecord:
    return AuditRecord(
        audit_id=str(row["audit_id"]),
        event_type=str(row["event_type"]),
        proposal_id=str(row["proposal_id"]),
        decision_id=str(row["decision_id"]) if row["decision_id"] else None,
        timestamp=str(row["timestamp"]),
        actor=str(row["actor"]),
        action_class=str(row["action_class"]),
        target_system=str(row["target_system"]),
        target_scope=json.loads(str(row["target_scope"])),
        risk_level=str(row["risk_level"]),
        decision=str(row["decision"]) if row["decision"] else None,
        reason_code=str(row["reason_code"]) if row["reason_code"] else None,
        payload_hash=str(row["payload_hash"]),
        full_proposal_snapshot=json.loads(str(row["full_proposal_snapshot"])),
    )
