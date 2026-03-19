"""Platform-owned job admission records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

INITIAL_JOB_STATUS = "received"


class JobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(min_length=1)
    workflow_key: str = Field(min_length=1)
    input_payload: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class JobRecordResponse(BaseModel):
    job_id: str
    client_id: str
    workflow_key: str
    status: str
    created_at: str
    input_payload: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class StoredJobRecord:
    job_id: str
    client_id: str
    workflow_key: str
    status: str
    created_at: str
    input_payload: str | None = None
    metadata: str | None = None

    def to_model(self) -> JobRecordResponse:
        return JobRecordResponse(
            job_id=self.job_id,
            client_id=self.client_id,
            workflow_key=self.workflow_key,
            status=self.status,
            created_at=self.created_at,
            input_payload=json.loads(self.input_payload) if self.input_payload else None,
            metadata=json.loads(self.metadata) if self.metadata else None,
        )


class SQLiteJobRecordStore:
    """SQLite-backed platform job admission store."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = Lock()
        self._ensure_parent_dir()
        self._init_schema()

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
                CREATE TABLE IF NOT EXISTS workflow_jobs (
                  job_id TEXT PRIMARY KEY,
                  client_id TEXT NOT NULL,
                  workflow_key TEXT NOT NULL,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  input_payload TEXT NULL,
                  metadata TEXT NULL
                );
                """
            )

    def create_job(self, payload: JobCreateRequest) -> JobRecordResponse:
        job_id = str(uuid4())
        created_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        input_payload = (
            json.dumps(payload.input_payload, ensure_ascii=False, separators=(",", ":"))
            if payload.input_payload is not None
            else None
        )
        metadata = (
            json.dumps(payload.metadata, ensure_ascii=False, separators=(",", ":"))
            if payload.metadata is not None
            else None
        )

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO workflow_jobs (
                      job_id,
                      client_id,
                      workflow_key,
                      status,
                      created_at,
                      input_payload,
                      metadata
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        payload.client_id,
                        payload.workflow_key,
                        INITIAL_JOB_STATUS,
                        created_at,
                        input_payload,
                        metadata,
                    ),
                )

        return StoredJobRecord(
            job_id=job_id,
            client_id=payload.client_id,
            workflow_key=payload.workflow_key,
            status=INITIAL_JOB_STATUS,
            created_at=created_at,
            input_payload=input_payload,
            metadata=metadata,
        ).to_model()

    def get_job(self, job_id: str) -> JobRecordResponse | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                  job_id,
                  client_id,
                  workflow_key,
                  status,
                  created_at,
                  input_payload,
                  metadata
                FROM workflow_jobs
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()

        if row is None:
            return None

        return StoredJobRecord(
            job_id=str(row["job_id"]),
            client_id=str(row["client_id"]),
            workflow_key=str(row["workflow_key"]),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            input_payload=str(row["input_payload"]) if row["input_payload"] else None,
            metadata=str(row["metadata"]) if row["metadata"] else None,
        ).to_model()
