"""Minimal admission policy and quota checks for job creation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from threading import Lock

from pydantic import BaseModel

from platform_app.workflow_events import (
    PLATFORM_STATUS_ACCEPTED,
    PLATFORM_STATUS_RECEIVED,
    PLATFORM_STATUS_RUNNING,
    normalize_workflow_status,
)

ACTIVE_PLATFORM_STATUSES = {
    PLATFORM_STATUS_RECEIVED,
    PLATFORM_STATUS_ACCEPTED,
    PLATFORM_STATUS_RUNNING,
}


class AdmissionPolicyRecord(BaseModel):
    client_id: str
    is_enabled: bool
    max_jobs_per_day: int | None
    max_active_jobs: int | None
    updated_at: str


@dataclass(frozen=True)
class AdmissionDecision:
    allowed: bool
    code: str
    message: str


class SQLiteAdmissionPolicyStore:
    """SQLite-backed minimal policy/quota store."""

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
                CREATE TABLE IF NOT EXISTS client_admission_policies (
                  client_id TEXT PRIMARY KEY,
                  is_enabled INTEGER NOT NULL,
                  max_jobs_per_day INTEGER NULL,
                  max_active_jobs INTEGER NULL,
                  updated_at TEXT NOT NULL
                );
                """
            )

    def upsert_policy(
        self,
        *,
        client_id: str,
        is_enabled: bool,
        max_jobs_per_day: int | None,
        max_active_jobs: int | None,
    ) -> AdmissionPolicyRecord:
        updated_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO client_admission_policies (
                      client_id,
                      is_enabled,
                      max_jobs_per_day,
                      max_active_jobs,
                      updated_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(client_id) DO UPDATE SET
                      is_enabled = excluded.is_enabled,
                      max_jobs_per_day = excluded.max_jobs_per_day,
                      max_active_jobs = excluded.max_active_jobs,
                      updated_at = excluded.updated_at
                    """,
                    (
                        client_id,
                        int(is_enabled),
                        max_jobs_per_day,
                        max_active_jobs,
                        updated_at,
                    ),
                )
        return AdmissionPolicyRecord(
            client_id=client_id,
            is_enabled=is_enabled,
            max_jobs_per_day=max_jobs_per_day,
            max_active_jobs=max_active_jobs,
            updated_at=updated_at,
        )

    def get_policy(self, client_id: str) -> AdmissionPolicyRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                  client_id,
                  is_enabled,
                  max_jobs_per_day,
                  max_active_jobs,
                  updated_at
                FROM client_admission_policies
                WHERE client_id = ?
                """,
                (client_id,),
            ).fetchone()

        if row is None:
            return None

        return AdmissionPolicyRecord(
            client_id=str(row["client_id"]),
            is_enabled=bool(row["is_enabled"]),
            max_jobs_per_day=int(row["max_jobs_per_day"])
            if row["max_jobs_per_day"] is not None
            else None,
            max_active_jobs=int(row["max_active_jobs"])
            if row["max_active_jobs"] is not None
            else None,
            updated_at=str(row["updated_at"]),
        )

    def evaluate_admission(self, client_id: str) -> AdmissionDecision:
        policy = self.get_policy(client_id)
        if policy is None:
            return AdmissionDecision(
                allowed=True,
                code="default_allow",
                message="No client policy record found; allowing admission by bootstrap default",
            )

        if not policy.is_enabled:
            return AdmissionDecision(
                allowed=False,
                code="client_disabled",
                message=f"Client {client_id} is disabled for job admission",
            )

        jobs_today = self._count_jobs_created_today(client_id)
        if (
            policy.max_jobs_per_day is not None
            and jobs_today >= policy.max_jobs_per_day
        ):
            return AdmissionDecision(
                allowed=False,
                code="daily_quota_exceeded",
                message=(
                    f"Client {client_id} exceeded daily job quota "
                    f"({jobs_today}/{policy.max_jobs_per_day})"
                ),
            )

        active_jobs = self._count_active_jobs(client_id)
        if (
            policy.max_active_jobs is not None
            and active_jobs >= policy.max_active_jobs
        ):
            return AdmissionDecision(
                allowed=False,
                code="active_job_limit_exceeded",
                message=(
                    f"Client {client_id} exceeded active job limit "
                    f"({active_jobs}/{policy.max_active_jobs})"
                ),
            )

        return AdmissionDecision(
            allowed=True,
            code="allowed",
            message=f"Client {client_id} is allowed to create a job",
        )

    def _count_jobs_created_today(self, client_id: str) -> int:
        start_of_day = datetime.now(timezone.utc).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        ).isoformat(timespec="milliseconds")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM workflow_jobs
                WHERE client_id = ?
                  AND created_at >= ?
                """,
                (client_id, start_of_day),
            ).fetchone()
        return int(row["count"]) if row is not None else 0

    def _count_active_jobs(self, client_id: str) -> int:
        with self._connect() as conn:
            has_events_table = conn.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table' AND name = 'workflow_events'
                """
            ).fetchone()
            if has_events_table is None:
                rows = conn.execute(
                    """
                    SELECT j.job_id, j.status AS effective_status
                    FROM workflow_jobs j
                    WHERE j.client_id = ?
                    """,
                    (client_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT
                      j.job_id,
                      COALESCE(
                        (
                          SELECT e.status
                          FROM workflow_events e
                          WHERE e.job_id = j.job_id
                          ORDER BY e.received_at DESC, e.id DESC
                          LIMIT 1
                        ),
                        j.status
                      ) AS effective_status
                    FROM workflow_jobs j
                    WHERE j.client_id = ?
                    """,
                    (client_id,),
                ).fetchall()

        count = 0
        for row in rows:
            if normalize_workflow_status(str(row["effective_status"])) in ACTIVE_PLATFORM_STATUSES:
                count += 1
        return count
