"""Controlled dispatch records and runner handoff."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Any
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field

from platform_app.config import PlatformSettings
from platform_app.job_records import JobRecordResponse

DISPATCH_STATUS_PENDING = "pending"
DISPATCH_STATUS_SENT = "sent"
DISPATCH_STATUS_FAILED = "failed"


class DispatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: dict[str, Any] = Field(default_factory=dict)


class DispatchRecordResponse(BaseModel):
    dispatch_id: str
    job_id: str
    client_id: str
    workflow_key: str
    target_url: str
    payload: dict[str, Any]
    status: str
    response_code: int | None
    error: str | None
    created_at: str
    sent_at: str | None


class DispatchListResponse(BaseModel):
    status: str = "ok"
    job_id: str
    count: int
    dispatches: list[DispatchRecordResponse]


class DispatchResult(BaseModel):
    status: str = "ok"
    dispatch: DispatchRecordResponse


@dataclass(frozen=True)
class StoredDispatchRecord:
    dispatch_id: str
    job_id: str
    client_id: str
    workflow_key: str
    target_url: str
    payload: str
    status: str
    response_code: int | None
    error: str | None
    created_at: str
    sent_at: str | None

    def to_model(self) -> DispatchRecordResponse:
        return DispatchRecordResponse(
            dispatch_id=self.dispatch_id,
            job_id=self.job_id,
            client_id=self.client_id,
            workflow_key=self.workflow_key,
            target_url=self.target_url,
            payload=json.loads(self.payload),
            status=self.status,
            response_code=self.response_code,
            error=self.error,
            created_at=self.created_at,
            sent_at=self.sent_at,
        )


class SQLiteDispatchRecordStore:
    """SQLite-backed dispatch audit store."""

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
                CREATE TABLE IF NOT EXISTS workflow_dispatches (
                  dispatch_id TEXT PRIMARY KEY,
                  job_id TEXT NOT NULL,
                  client_id TEXT NOT NULL,
                  workflow_key TEXT NOT NULL,
                  target_url TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  status TEXT NOT NULL,
                  response_code INTEGER NULL,
                  error TEXT NULL,
                  created_at TEXT NOT NULL,
                  sent_at TEXT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_workflow_dispatches_job_id
                  ON workflow_dispatches(job_id, created_at, dispatch_id);
                """
            )

    def create_pending_dispatch(
        self,
        *,
        job: JobRecordResponse,
        target_url: str,
        payload: dict[str, Any],
    ) -> DispatchRecordResponse:
        dispatch_id = str(uuid4())
        created_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO workflow_dispatches (
                      dispatch_id,
                      job_id,
                      client_id,
                      workflow_key,
                      target_url,
                      payload,
                      status,
                      response_code,
                      error,
                      created_at,
                      sent_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        dispatch_id,
                        job.job_id,
                        job.client_id,
                        job.workflow_key,
                        target_url,
                        payload_json,
                        DISPATCH_STATUS_PENDING,
                        None,
                        None,
                        created_at,
                        None,
                    ),
                )

        return StoredDispatchRecord(
            dispatch_id=dispatch_id,
            job_id=job.job_id,
            client_id=job.client_id,
            workflow_key=job.workflow_key,
            target_url=target_url,
            payload=payload_json,
            status=DISPATCH_STATUS_PENDING,
            response_code=None,
            error=None,
            created_at=created_at,
            sent_at=None,
        ).to_model()

    def finalize_dispatch(
        self,
        *,
        dispatch_id: str,
        status: str,
        response_code: int | None,
        error: str | None,
        sent_at: str | None,
    ) -> DispatchRecordResponse:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE workflow_dispatches
                    SET status = ?, response_code = ?, error = ?, sent_at = ?
                    WHERE dispatch_id = ?
                    """,
                    (status, response_code, error, sent_at, dispatch_id),
                )
                row = conn.execute(
                    """
                    SELECT
                      dispatch_id,
                      job_id,
                      client_id,
                      workflow_key,
                      target_url,
                      payload,
                      status,
                      response_code,
                      error,
                      created_at,
                      sent_at
                    FROM workflow_dispatches
                    WHERE dispatch_id = ?
                    """,
                    (dispatch_id,),
                ).fetchone()

        if row is None:
            raise KeyError(f"Dispatch record not found: {dispatch_id}")

        return StoredDispatchRecord(
            dispatch_id=str(row["dispatch_id"]),
            job_id=str(row["job_id"]),
            client_id=str(row["client_id"]),
            workflow_key=str(row["workflow_key"]),
            target_url=str(row["target_url"]),
            payload=str(row["payload"]),
            status=str(row["status"]),
            response_code=int(row["response_code"]) if row["response_code"] is not None else None,
            error=str(row["error"]) if row["error"] else None,
            created_at=str(row["created_at"]),
            sent_at=str(row["sent_at"]) if row["sent_at"] else None,
        ).to_model()

    def list_by_job_id(self, job_id: str) -> list[DispatchRecordResponse]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  dispatch_id,
                  job_id,
                  client_id,
                  workflow_key,
                  target_url,
                  payload,
                  status,
                  response_code,
                  error,
                  created_at,
                  sent_at
                FROM workflow_dispatches
                WHERE job_id = ?
                ORDER BY created_at ASC, dispatch_id ASC
                """,
                (job_id,),
            ).fetchall()

        return [
            StoredDispatchRecord(
                dispatch_id=str(row["dispatch_id"]),
                job_id=str(row["job_id"]),
                client_id=str(row["client_id"]),
                workflow_key=str(row["workflow_key"]),
                target_url=str(row["target_url"]),
                payload=str(row["payload"]),
                status=str(row["status"]),
                response_code=int(row["response_code"]) if row["response_code"] is not None else None,
                error=str(row["error"]) if row["error"] else None,
                created_at=str(row["created_at"]),
                sent_at=str(row["sent_at"]) if row["sent_at"] else None,
            ).to_model()
            for row in rows
        ]


class RunnerDispatchError(RuntimeError):
    """Stable error for runner handoff failures."""

    def __init__(self, message: str, response_code: int | None = None) -> None:
        super().__init__(message)
        self.response_code = response_code


class RunnerDispatcher:
    def __init__(
        self,
        *,
        target_url: str,
        callback_url: str,
        timeout_seconds: float,
        client: httpx.Client | None = None,
    ) -> None:
        self._target_url = target_url
        self._callback_url = callback_url
        self._timeout_seconds = timeout_seconds
        self._client = client

    @property
    def target_url(self) -> str:
        return self._target_url

    @property
    def callback_url(self) -> str:
        return self._callback_url

    def dispatch(self, job: JobRecordResponse, payload: dict[str, Any]) -> int:
        body = {
            "job_id": job.job_id,
            "client_id": job.client_id,
            "workflow_key": job.workflow_key,
            "payload": payload,
            "callback_url": self._callback_url,
        }

        own_client = False
        client = self._client
        if client is None:
            client = httpx.Client(timeout=self._timeout_seconds)
            own_client = True

        try:
            response = client.post(self._target_url, json=body)
        except httpx.TimeoutException as exc:
            raise RunnerDispatchError("Runner dispatch timed out") from exc
        except httpx.HTTPError as exc:
            raise RunnerDispatchError(f"Runner dispatch failed: {exc}") from exc
        finally:
            if own_client:
                client.close()

        if response.status_code >= 400:
            raise RunnerDispatchError(
                f"Runner dispatch returned status {response.status_code}",
                response_code=response.status_code,
            )

        return int(response.status_code)


def build_runner_dispatcher(settings: PlatformSettings) -> RunnerDispatcher:
    target_url = settings.workflow_runner_dispatch_url.strip()
    if not target_url:
        raise ValueError("PLATFORM_WORKFLOW_RUNNER_DISPATCH_URL is not configured")
    callback_base = settings.platform_public_base_url.rstrip("/")
    callback_url = f"{callback_base}/v1/platform/workflows/events"
    return RunnerDispatcher(
        target_url=target_url,
        callback_url=callback_url,
        timeout_seconds=settings.llm_timeout_seconds,
    )
