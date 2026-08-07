"""SQLite records for plans, audit events, executor approvals, and replay protection."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .security import make_operator_code, operator_code_hash, verify_operator_code


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds")


class SQLiteStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE,
                    target TEXT NOT NULL,
                    action TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    argv_json TEXT NOT NULL,
                    config_fingerprint TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    approval_mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    exit_code INTEGER,
                    stdout TEXT,
                    stderr TEXT,
                    duration_ms INTEGER,
                    error TEXT
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    operation_id TEXT,
                    actor TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS executor_records (
                    operation_id TEXT PRIMARY KEY,
                    digest TEXT NOT NULL,
                    target TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    exit_code INTEGER,
                    result_json TEXT
                );

                CREATE TABLE IF NOT EXISTS operator_approvals (
                    operation_id TEXT PRIMARY KEY,
                    digest TEXT NOT NULL,
                    code_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT
                );
                """
            )

    def create_operation(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if record.get("idempotency_key"):
                existing = connection.execute(
                    "SELECT * FROM operations WHERE idempotency_key = ?",
                    (record["idempotency_key"],),
                ).fetchone()
                if existing is not None:
                    existing_dict = self._operation_row(existing)
                    comparable_fields = (
                        "target",
                        "action",
                        "parameters",
                        "reason",
                        "argv",
                        "config_fingerprint",
                        "approval_mode",
                    )
                    if any(existing_dict[field] != record[field] for field in comparable_fields):
                        raise ValueError(
                            "idempotency_key was already used for a different operation"
                        )
                    return existing_dict

            connection.execute(
                """
                INSERT INTO operations (
                    operation_id, idempotency_key, target, action, parameters_json,
                    reason, argv_json, config_fingerprint, digest, approval_mode,
                    status, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'planned', ?, ?)
                """,
                (
                    record["operation_id"],
                    record.get("idempotency_key"),
                    record["target"],
                    record["action"],
                    json.dumps(record["parameters"], sort_keys=True),
                    record["reason"],
                    json.dumps(record["argv"]),
                    record["config_fingerprint"],
                    record["digest"],
                    record["approval_mode"],
                    record["created_at"],
                    record["expires_at"],
                ),
            )
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?", (record["operation_id"],)
            ).fetchone()
            assert row is not None
            return self._operation_row(row)

    def get_operation(self, operation_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
        return self._operation_row(row) if row is not None else None

    def mark_operation_running(self, operation_id: str, digest: str) -> dict[str, Any]:
        now = iso(utc_now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            if row is None:
                raise ValueError("Unknown operation_id")
            operation = self._operation_row(row)
            if operation["digest"] != digest:
                raise ValueError("Operation digest mismatch")
            if operation["status"] == "succeeded":
                return operation
            if operation["status"] != "planned":
                raise ValueError(f"Operation is not executable from status {operation['status']!r}")
            if datetime.fromisoformat(operation["expires_at"]) <= utc_now():
                connection.execute(
                    "UPDATE operations SET status = 'expired', completed_at = ? "
                    "WHERE operation_id = ?",
                    (now, operation_id),
                )
                raise ValueError("Operation plan has expired")
            connection.execute(
                "UPDATE operations SET status = 'running', started_at = ? WHERE operation_id = ?",
                (now, operation_id),
            )
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            assert row is not None
            return self._operation_row(row)

    def complete_operation(
        self,
        operation_id: str,
        *,
        status: str,
        exit_code: int | None,
        stdout: str,
        stderr: str,
        duration_ms: int | None,
        error: str | None = None,
    ) -> dict[str, Any]:
        completed_at = iso(utc_now())
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE operations
                SET status = ?, completed_at = ?, exit_code = ?, stdout = ?, stderr = ?,
                    duration_ms = ?, error = ?
                WHERE operation_id = ?
                """,
                (
                    status,
                    completed_at,
                    exit_code,
                    stdout,
                    stderr,
                    duration_ms,
                    error,
                    operation_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            if row is None:
                raise ValueError("Unknown operation_id")
            return self._operation_row(row)

    def cancel_operation(self, operation_id: str, reason: str) -> dict[str, Any]:
        now = iso(utc_now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            if row is None:
                raise ValueError("Unknown operation_id")
            operation = self._operation_row(row)
            if operation["status"] == "cancelled":
                return operation
            if operation["status"] != "planned":
                raise ValueError("Only planned operations can be cancelled")
            connection.execute(
                "UPDATE operations SET status = 'cancelled', completed_at = ?, error = ? "
                "WHERE operation_id = ?",
                (now, reason, operation_id),
            )
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            assert row is not None
            return self._operation_row(row)

    def add_audit(
        self,
        event_type: str,
        *,
        actor: str,
        operation_id: str | None,
        details: dict[str, Any],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO audit_events (event_type, operation_id, actor, details_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event_type,
                    operation_id,
                    actor,
                    json.dumps(details, sort_keys=True),
                    iso(utc_now()),
                ),
            )

    def recent_audit(self, limit: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_events ORDER BY event_id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "operation_id": row["operation_id"],
                "actor": row["actor"],
                "details": json.loads(row["details_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def begin_executor_record(
        self,
        *,
        operation_id: str,
        digest: str,
        target: str,
        action: str,
    ) -> dict[str, Any] | None:
        now = iso(utc_now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM executor_records WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            if existing is not None:
                if existing["digest"] != digest:
                    raise ValueError("Executor operation_id replayed with a different digest")
                if existing["status"] == "succeeded":
                    return self._executor_row(existing)
                raise ValueError(
                    f"Executor operation already exists with status {existing['status']!r}"
                )
            connection.execute(
                """
                INSERT INTO executor_records (
                    operation_id, digest, target, action, status, created_at, started_at
                ) VALUES (?, ?, ?, ?, 'running', ?, ?)
                """,
                (operation_id, digest, target, action, now, now),
            )
        return None

    def complete_executor_record(
        self,
        operation_id: str,
        *,
        status: str,
        exit_code: int,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE executor_records
                SET status = ?, completed_at = ?, exit_code = ?, result_json = ?
                WHERE operation_id = ?
                """,
                (status, iso(utc_now()), exit_code, json.dumps(result), operation_id),
            )
            row = connection.execute(
                "SELECT * FROM executor_records WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            if row is None:
                raise ValueError("Executor record disappeared")
            return self._executor_row(row)

    def issue_operator_code(
        self,
        operation_id: str,
        digest: str,
        ttl_seconds: int,
    ) -> tuple[str, str]:
        code = make_operator_code()
        expires_at = iso(utc_now() + timedelta(seconds=ttl_seconds))
        code_hash = operator_code_hash(operation_id, digest, code)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_id FROM operator_approvals WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                raise ValueError(
                    "An operator approval was already issued for this operation; "
                    "create a new operation plan"
                )
            connection.execute(
                """
                INSERT INTO operator_approvals (
                    operation_id, digest, code_hash, expires_at, consumed_at
                ) VALUES (?, ?, ?, ?, NULL)
                """,
                (operation_id, digest, code_hash, expires_at),
            )
        return code, expires_at

    def consume_operator_code(self, operation_id: str, digest: str, code: str) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM operator_approvals WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            if row is None:
                raise ValueError("No operator approval exists for this operation")
            if row["digest"] != digest:
                raise ValueError("Operator approval digest mismatch")
            if row["consumed_at"] is not None:
                raise ValueError("Operator approval code has already been consumed")
            if datetime.fromisoformat(row["expires_at"]) <= utc_now():
                raise ValueError("Operator approval code has expired")
            if not verify_operator_code(operation_id, digest, code, row["code_hash"]):
                raise ValueError("Invalid operator approval code")
            connection.execute(
                "UPDATE operator_approvals SET consumed_at = ? WHERE operation_id = ?",
                (iso(utc_now()), operation_id),
            )

    @staticmethod
    def _operation_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "operation_id": row["operation_id"],
            "idempotency_key": row["idempotency_key"],
            "target": row["target"],
            "action": row["action"],
            "parameters": json.loads(row["parameters_json"]),
            "reason": row["reason"],
            "argv": json.loads(row["argv_json"]),
            "config_fingerprint": row["config_fingerprint"],
            "digest": row["digest"],
            "approval_mode": row["approval_mode"],
            "status": row["status"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "exit_code": row["exit_code"],
            "stdout": row["stdout"],
            "stderr": row["stderr"],
            "duration_ms": row["duration_ms"],
            "error": row["error"],
        }

    @staticmethod
    def _executor_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "operation_id": row["operation_id"],
            "digest": row["digest"],
            "target": row["target"],
            "action": row["action"],
            "status": row["status"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "exit_code": row["exit_code"],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
        }
