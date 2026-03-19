"""Workflow event ledger persistence and schemas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

PLATFORM_STATUS_RECEIVED = "received"
PLATFORM_STATUS_ACCEPTED = "accepted"
PLATFORM_STATUS_RUNNING = "running"
PLATFORM_STATUS_SUCCEEDED = "succeeded"
PLATFORM_STATUS_FAILED = "failed"
PLATFORM_STATUS_CANCELLED = "cancelled"
PLATFORM_STATUS_UNKNOWN = "unknown"

_PLATFORM_STATUS_MAP = {
    PLATFORM_STATUS_RECEIVED: {"received", "ingested"},
    PLATFORM_STATUS_ACCEPTED: {"accepted", "queued", "pending"},
    PLATFORM_STATUS_RUNNING: {"running", "in_progress", "processing", "started"},
    PLATFORM_STATUS_SUCCEEDED: {"succeeded", "success", "completed", "done"},
    PLATFORM_STATUS_FAILED: {"failed", "error", "errored"},
    PLATFORM_STATUS_CANCELLED: {"cancelled", "canceled"},
}


class WorkflowEventIngestRequest(BaseModel):
    """Append-friendly workflow event intake payload."""

    model_config = ConfigDict(extra="allow")

    job_id: str = Field(min_length=1)
    client_id: str = Field(min_length=1)
    workflow_key: str = Field(min_length=1)
    execution_id: str | None = None
    status: str = Field(min_length=1)
    source: str | None = None


class WorkflowEventRecord(BaseModel):
    id: int
    job_id: str
    client_id: str
    workflow_key: str
    execution_id: str | None
    status: str
    received_at: str
    raw_payload: dict[str, Any]
    source: str | None = None


class WorkflowEventLookupResponse(BaseModel):
    status: str = "ok"
    job_id: str
    count: int
    records: list[WorkflowEventRecord]


class WorkflowEventIngestResponse(BaseModel):
    status: str = "accepted"
    record: WorkflowEventRecord


class JobStateProjectionResponse(BaseModel):
    status: str = "ok"
    job_id: str
    current_status: str
    raw_status: str
    execution_id: str | None
    client_id: str
    workflow_key: str
    received_at: str
    source: str | None
    event_count: int


@dataclass(frozen=True)
class StoredWorkflowEvent:
    id: int
    job_id: str
    client_id: str
    workflow_key: str
    execution_id: str | None
    status: str
    received_at: str
    raw_payload: str
    source: str | None = None

    def to_model(self) -> WorkflowEventRecord:
        return WorkflowEventRecord(
            id=self.id,
            job_id=self.job_id,
            client_id=self.client_id,
            workflow_key=self.workflow_key,
            execution_id=self.execution_id,
            status=self.status,
            received_at=self.received_at,
            raw_payload=json.loads(self.raw_payload),
            source=self.source,
        )


class SQLiteWorkflowEventStore:
    """SQLite-backed workflow event ledger bootstrap implementation."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = Lock()
        self._ensure_parent_dir()
        self._init_schema()

    @property
    def db_path(self) -> str:
        return self._db_path

    def _ensure_parent_dir(self) -> None:
        parent = Path(self._db_path).expanduser().resolve().parent
        parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS workflow_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  job_id TEXT NOT NULL,
                  client_id TEXT NOT NULL,
                  workflow_key TEXT NOT NULL,
                  execution_id TEXT NULL,
                  status TEXT NOT NULL,
                  received_at TEXT NOT NULL,
                  raw_payload TEXT NOT NULL,
                  source TEXT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_workflow_events_job_id
                  ON workflow_events(job_id, received_at, id);
                """
            )

    def append_event(self, payload: WorkflowEventIngestRequest) -> WorkflowEventRecord:
        received_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        raw_payload = json.dumps(
            payload.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO workflow_events (
                      job_id,
                      client_id,
                      workflow_key,
                      execution_id,
                      status,
                      received_at,
                      raw_payload,
                      source
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload.job_id,
                        payload.client_id,
                        payload.workflow_key,
                        payload.execution_id,
                        payload.status,
                        received_at,
                        raw_payload,
                        payload.source,
                    ),
                )
                event_id = int(cur.lastrowid)

        return StoredWorkflowEvent(
            id=event_id,
            job_id=payload.job_id,
            client_id=payload.client_id,
            workflow_key=payload.workflow_key,
            execution_id=payload.execution_id,
            status=payload.status,
            received_at=received_at,
            raw_payload=raw_payload,
            source=payload.source,
        ).to_model()

    def list_by_job_id(self, job_id: str) -> list[WorkflowEventRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  id,
                  job_id,
                  client_id,
                  workflow_key,
                  execution_id,
                  status,
                  received_at,
                  raw_payload,
                  source
                FROM workflow_events
                WHERE job_id = ?
                ORDER BY received_at ASC, id ASC
                """,
                (job_id,),
            ).fetchall()

        return [
            StoredWorkflowEvent(
                id=int(row["id"]),
                job_id=str(row["job_id"]),
                client_id=str(row["client_id"]),
                workflow_key=str(row["workflow_key"]),
                execution_id=str(row["execution_id"]) if row["execution_id"] else None,
                status=str(row["status"]),
                received_at=str(row["received_at"]),
                raw_payload=str(row["raw_payload"]),
                source=str(row["source"]) if row["source"] else None,
            ).to_model()
            for row in rows
        ]


def resolve_workflow_events_db_path(path_value: str) -> str:
    path = Path(path_value)
    if path.is_absolute():
        return str(path)
    return str((Path.cwd() / path).resolve())


def normalize_workflow_status(raw_status: str) -> str:
    normalized = raw_status.strip().lower()
    for platform_status, raw_statuses in _PLATFORM_STATUS_MAP.items():
        if normalized in raw_statuses:
            return platform_status
    return PLATFORM_STATUS_UNKNOWN


def project_job_state(
    events: list[WorkflowEventRecord],
) -> JobStateProjectionResponse | None:
    if not events:
        return None

    ordered_events = sorted(events, key=lambda item: (item.received_at, item.id))
    latest = ordered_events[-1]

    latest_execution_id = next(
        (event.execution_id for event in reversed(ordered_events) if event.execution_id),
        None,
    )
    latest_source = next(
        (event.source for event in reversed(ordered_events) if event.source),
        None,
    )

    return JobStateProjectionResponse(
        job_id=latest.job_id,
        current_status=normalize_workflow_status(latest.status),
        raw_status=latest.status,
        execution_id=latest_execution_id,
        client_id=latest.client_id,
        workflow_key=latest.workflow_key,
        received_at=latest.received_at,
        source=latest_source,
        event_count=len(ordered_events),
    )
