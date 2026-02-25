"""Persistent API key store (SQLite bootstrap implementation)."""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Protocol


@dataclass(frozen=True)
class StoredAPIKey:
    key_id: str
    secret_hash: str
    scopes: tuple[str, ...]
    disabled: bool = False


@dataclass(frozen=True)
class IssuedAPIKey:
    key_id: str
    secret_plaintext: str
    secret_hash: str
    scopes: tuple[str, ...]


class APIKeyStore(Protocol):
    def get_key(self, key_id: str) -> StoredAPIKey | None: ...

    def create_key(self, key_id: str, scopes: tuple[str, ...]) -> IssuedAPIKey: ...

    def rotate_key(self, key_id: str) -> IssuedAPIKey: ...

    def revoke_key(self, key_id: str) -> None: ...


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
                """
            )

    def get_key(self, key_id: str) -> StoredAPIKey | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT key_id, secret_hash, disabled FROM api_keys WHERE key_id = ?",
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
        disabled: bool = False,
    ) -> IssuedAPIKey:
        scopes = _normalize_scopes(scopes)
        secret_hash = self._hash_secret_fn(secret_plaintext)
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO api_keys (key_id, secret_hash, disabled)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key_id) DO UPDATE SET
                      secret_hash = excluded.secret_hash,
                      disabled = excluded.disabled,
                      updated_at = CURRENT_TIMESTAMP
                    """,
                    (key_id, secret_hash, int(disabled)),
                )
                conn.execute(
                    "DELETE FROM api_key_scopes WHERE key_id = ?",
                    (key_id,),
                )
                conn.executemany(
                    "INSERT INTO api_key_scopes (key_id, scope) VALUES (?, ?)",
                    [(key_id, scope) for scope in scopes],
                )
        return IssuedAPIKey(
            key_id=key_id,
            secret_plaintext=secret_plaintext,
            secret_hash=secret_hash,
            scopes=scopes,
        )

    def create_key(self, key_id: str, scopes: tuple[str, ...]) -> IssuedAPIKey:
        existing = self.get_key(key_id)
        if existing is not None:
            raise ValueError(f"API key already exists: {key_id}")
        return self._upsert_key_with_secret(
            key_id=key_id,
            secret_plaintext=self._issue_secret(),
            scopes=scopes,
            disabled=False,
        )

    def rotate_key(self, key_id: str) -> IssuedAPIKey:
        existing = self.get_key(key_id)
        if existing is None:
            raise KeyError(f"API key not found: {key_id}")
        return self._upsert_key_with_secret(
            key_id=key_id,
            secret_plaintext=self._issue_secret(),
            scopes=existing.scopes,
            disabled=False,
        )

    def revoke_key(self, key_id: str) -> None:
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


def resolve_auth_db_path(path_value: str) -> str:
    path = Path(path_value)
    if path.is_absolute():
        return str(path)
    return str((Path.cwd() / path).resolve())
