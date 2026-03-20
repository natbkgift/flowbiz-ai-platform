"""Persistent API key store (SQLite bootstrap implementation)."""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
import json
from pathlib import Path
from threading import Lock
from typing import Protocol


@dataclass(frozen=True)
class StoredAPIKey:
    key_id: str
    secret_hash: str
    scopes: tuple[str, ...]
    client_id: str | None = None
    disabled: bool = False


@dataclass(frozen=True)
class IssuedAPIKey:
    key_id: str
    secret_plaintext: str
    secret_hash: str
    scopes: tuple[str, ...]
    client_id: str | None = None


@dataclass(frozen=True)
class APIKeyAuditEvent:
    id: int
    client_id: str | None
    action: str
    event_type: str
    key_id: str
    actor: str
    actor_type: str | None
    actor_id: str | None
    reason: str | None
    created_at: str
    metadata: dict[str, object] | None = None


class APIKeyStore(Protocol):
    def get_key(self, key_id: str) -> StoredAPIKey | None: ...

    def create_key(
        self,
        key_id: str,
        scopes: tuple[str, ...],
        client_id: str | None = None,
        actor: str = "system",
        actor_type: str | None = None,
        actor_id: str | None = None,
        reason: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> IssuedAPIKey: ...

    def rotate_key(
        self,
        key_id: str,
        actor: str = "system",
        actor_type: str | None = None,
        actor_id: str | None = None,
        reason: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> IssuedAPIKey: ...

    def revoke_key(
        self,
        key_id: str,
        actor: str = "system",
        actor_type: str | None = None,
        actor_id: str | None = None,
        reason: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None: ...


def _normalize_scopes(scopes: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for scope in scopes:
        value = str(scope).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return tuple(ordered)


class SQLiteAPIKeyStore:
    """SQLite-based persistent key store for bootstrap/platform MVP.

    Uses two tables:
    - `api_keys` (key metadata + hash + disabled flag)
    - `api_key_scopes` (1:N scopes per key)
    """

    def __init__(self, db_path: str, hash_secret_fn) -> None:
        self._db_path = db_path
        self._hash_secret_fn = hash_secret_fn
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
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS api_keys (
                  key_id TEXT PRIMARY KEY,
                  client_id TEXT NULL,
                  secret_hash TEXT NOT NULL,
                  disabled INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS api_key_scopes (
                  key_id TEXT NOT NULL,
                  scope TEXT NOT NULL,
                  PRIMARY KEY (key_id, scope),
                  FOREIGN KEY (key_id) REFERENCES api_keys(key_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS api_key_audit_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  client_id TEXT NULL,
                  action TEXT NOT NULL,
                  key_id TEXT NOT NULL,
                  actor TEXT NOT NULL,
                  actor_type TEXT NULL,
                  actor_id TEXT NULL,
                  reason TEXT NULL,
                  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  metadata TEXT NULL
                );
                """
            )
            cols = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(api_keys)").fetchall()
            }
            if "client_id" not in cols:
                conn.execute("ALTER TABLE api_keys ADD COLUMN client_id TEXT NULL")
            audit_cols = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(api_key_audit_events)").fetchall()
            }
            if "actor_type" not in audit_cols:
                conn.execute("ALTER TABLE api_key_audit_events ADD COLUMN actor_type TEXT NULL")
            if "actor_id" not in audit_cols:
                conn.execute("ALTER TABLE api_key_audit_events ADD COLUMN actor_id TEXT NULL")
            if "reason" not in audit_cols:
                conn.execute("ALTER TABLE api_key_audit_events ADD COLUMN reason TEXT NULL")

    def get_key(self, key_id: str) -> StoredAPIKey | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT key_id, client_id, secret_hash, disabled
                FROM api_keys
                WHERE key_id = ?
                """,
                (key_id,),
            ).fetchone()
            if row is None:
                return None
            scope_rows = conn.execute(
                "SELECT scope FROM api_key_scopes WHERE key_id = ? ORDER BY scope",
                (key_id,),
            ).fetchall()
        scopes = tuple(str(r["scope"]) for r in scope_rows)
        return StoredAPIKey(
            key_id=str(row["key_id"]),
            client_id=str(row["client_id"]) if row["client_id"] else None,
            secret_hash=str(row["secret_hash"]),
            disabled=bool(row["disabled"]),
            scopes=scopes,
        )

    def _issue_secret(self) -> str:
        return secrets.token_urlsafe(24)

    def _upsert_key_with_secret(
        self,
        key_id: str,
        secret_plaintext: str,
        scopes: tuple[str, ...],
        client_id: str | None = None,
        disabled: bool = False,
        audit_action: str | None = None,
        actor: str = "system",
        actor_type: str | None = None,
        actor_id: str | None = None,
        reason: str | None = None,
        additional_audit_actions: tuple[str, ...] = (),
        metadata: dict[str, object] | None = None,
    ) -> IssuedAPIKey:
        scopes = _normalize_scopes(scopes)
        secret_hash = self._hash_secret_fn(secret_plaintext)
        metadata_json = (
            json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
            if metadata is not None
            else None
        )
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO api_keys (key_id, client_id, secret_hash, disabled)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(key_id) DO UPDATE SET
                      client_id = excluded.client_id,
                      secret_hash = excluded.secret_hash,
                      disabled = excluded.disabled,
                      updated_at = CURRENT_TIMESTAMP
                    """,
                    (key_id, client_id, secret_hash, int(disabled)),
                )
                conn.execute(
                    "DELETE FROM api_key_scopes WHERE key_id = ?",
                    (key_id,),
                )
                conn.executemany(
                    "INSERT INTO api_key_scopes (key_id, scope) VALUES (?, ?)",
                    [(key_id, scope) for scope in scopes],
                )
                if audit_action is not None:
                    self._insert_audit_event(
                        conn=conn,
                        client_id=client_id,
                        action=audit_action,
                        key_id=key_id,
                        actor=actor,
                        actor_type=actor_type,
                        actor_id=actor_id,
                        reason=reason,
                        metadata_json=metadata_json,
                    )
                for extra_action in additional_audit_actions:
                    self._insert_audit_event(
                        conn=conn,
                        client_id=client_id,
                        action=extra_action,
                        key_id=key_id,
                        actor=actor,
                        actor_type=actor_type,
                        actor_id=actor_id,
                        reason=reason,
                        metadata_json=metadata_json,
                    )
        return IssuedAPIKey(
            key_id=key_id,
            secret_plaintext=secret_plaintext,
            secret_hash=secret_hash,
            scopes=scopes,
            client_id=client_id,
        )

    def create_key(
        self,
        key_id: str,
        scopes: tuple[str, ...],
        client_id: str | None = None,
        actor: str = "system",
        actor_type: str | None = None,
        actor_id: str | None = None,
        reason: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> IssuedAPIKey:
        existing = self.get_key(key_id)
        if existing is not None:
            raise ValueError(f"API key already exists: {key_id}")
        return self._upsert_key_with_secret(
            key_id=key_id,
            secret_plaintext=self._issue_secret(),
            scopes=scopes,
            client_id=client_id,
            disabled=False,
            audit_action="issued",
            actor=actor,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason or "issued_via_api",
            metadata=metadata,
        )

    def revoke_key(
        self,
        key_id: str,
        actor: str = "system",
        actor_type: str | None = None,
        actor_id: str | None = None,
        reason: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        existing = self.get_key(key_id)
        if existing is None:
            raise KeyError(f"API key not found: {key_id}")
        metadata_json = (
            json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
            if metadata is not None
            else None
        )
        with self._lock:
            with self._connect() as conn:
                updated = conn.execute(
                    """
                    UPDATE api_keys
                    SET disabled = 1, updated_at = CURRENT_TIMESTAMP
                    WHERE key_id = ?
                    """,
                    (key_id,),
                )
                if updated.rowcount == 0:
                    raise KeyError(f"API key not found: {key_id}")
                self._insert_audit_event(
                    conn=conn,
                    client_id=existing.client_id,
                    action="revoked",
                    key_id=key_id,
                    actor=actor,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    reason=reason or "revoked_via_api",
                    metadata_json=metadata_json,
                )

    def rotate_key(
        self,
        key_id: str,
        actor: str = "system",
        actor_type: str | None = None,
        actor_id: str | None = None,
        reason: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> IssuedAPIKey:
        existing = self.get_key(key_id)
        if existing is None:
            raise KeyError(f"API key not found: {key_id}")
        return self._upsert_key_with_secret(
            key_id=key_id,
            secret_plaintext=self._issue_secret(),
            scopes=existing.scopes,
            client_id=existing.client_id,
            disabled=False,
            audit_action="rotated",
            actor=actor,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason or "rotated_via_api",
            additional_audit_actions=("revoked_by_rotation",),
            metadata=metadata,
        )

    def list_audit_events(self, client_id: str | None = None) -> list[APIKeyAuditEvent]:
        query = """
            SELECT
              id,
              client_id,
              action,
              key_id,
              actor,
              actor_type,
              actor_id,
              reason,
              created_at,
              metadata
            FROM api_key_audit_events
        """
        params: tuple[object, ...] = ()
        if client_id is not None:
            query += " WHERE client_id = ?"
            params = (client_id,)
        query += " ORDER BY id ASC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            APIKeyAuditEvent(
                id=int(row["id"]),
                client_id=str(row["client_id"]) if row["client_id"] else None,
                action=str(row["action"]),
                event_type=str(row["action"]),
                key_id=str(row["key_id"]),
                actor=str(row["actor"]),
                actor_type=str(row["actor_type"]) if row["actor_type"] else None,
                actor_id=str(row["actor_id"]) if row["actor_id"] else None,
                reason=str(row["reason"]) if row["reason"] else None,
                created_at=str(row["created_at"]),
                metadata=json.loads(row["metadata"]) if row["metadata"] else None,
            )
            for row in rows
        ]

    def _insert_audit_event(
        self,
        *,
        conn: sqlite3.Connection,
        client_id: str | None,
        action: str,
        key_id: str,
        actor: str,
        actor_type: str | None,
        actor_id: str | None,
        reason: str | None,
        metadata_json: str | None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO api_key_audit_events (
              client_id,
              action,
              key_id,
              actor,
              actor_type,
              actor_id,
              reason,
              metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                client_id,
                action,
                key_id,
                actor,
                actor_type,
                actor_id,
                reason,
                metadata_json,
            ),
        )


def resolve_auth_db_path(path_value: str) -> str:
    path = Path(path_value)
    if path.is_absolute():
        return str(path)
    return str((Path.cwd() / path).resolve())
