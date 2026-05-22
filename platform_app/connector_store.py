"""SQLite-backed connector registration store for the approval gate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hmac import compare_digest
import json
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Protocol

from platform_app.auth import hash_api_key_secret
from platform_app.approval_models import ConnectorRegistration, ConnectorRegistrationRecord


@dataclass(frozen=True)
class StoredConnector:
    connector_id: str
    connector_name: str
    allowed_action_classes: tuple[str, ...]
    api_key_hash: str
    callback_url: str | None
    disabled: bool
    created_at: str
    updated_at: str

    def to_model(self) -> ConnectorRegistrationRecord:
        return ConnectorRegistrationRecord(
            connector_id=self.connector_id,
            connector_name=self.connector_name,
            allowed_action_classes=self.allowed_action_classes,
            callback_url=self.callback_url,
            disabled=self.disabled,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class ConnectorStore(Protocol):
    def get_connector(self, connector_id: str) -> StoredConnector | None: ...

    def authenticate_api_key(self, api_key: str) -> StoredConnector | None: ...


def _serialize_action_classes(action_classes: tuple[str, ...]) -> str:
    return json.dumps(list(action_classes), ensure_ascii=False, separators=(",", ":"))


def _deserialize_action_classes(raw: str) -> tuple[str, ...]:
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        return ()
    return tuple(str(item) for item in parsed if str(item).strip())


class SQLiteConnectorStore:
    """SQLite store for connector identity and scoped proposal authority."""

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
                CREATE TABLE IF NOT EXISTS approval_connectors (
                  connector_id TEXT PRIMARY KEY,
                  connector_name TEXT NOT NULL,
                  allowed_action_classes TEXT NOT NULL,
                  api_key_hash TEXT NOT NULL UNIQUE,
                  callback_url TEXT NULL,
                  disabled INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_approval_connectors_api_key_hash
                  ON approval_connectors(api_key_hash);
                """
            )

    def upsert_connector(
        self,
        registration: ConnectorRegistration,
    ) -> ConnectorRegistrationRecord:
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        api_key_hash = hash_api_key_secret(registration.api_key)
        allowed_action_classes = _serialize_action_classes(
            registration.allowed_action_classes
        )

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO approval_connectors (
                      connector_id,
                      connector_name,
                      allowed_action_classes,
                      api_key_hash,
                      callback_url,
                      disabled,
                      created_at,
                      updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(connector_id) DO UPDATE SET
                      connector_name = excluded.connector_name,
                      allowed_action_classes = excluded.allowed_action_classes,
                      api_key_hash = excluded.api_key_hash,
                      callback_url = excluded.callback_url,
                      disabled = excluded.disabled,
                      updated_at = excluded.updated_at
                    """,
                    (
                        registration.connector_id,
                        registration.connector_name,
                        allowed_action_classes,
                        api_key_hash,
                        registration.callback_url,
                        int(registration.disabled),
                        now,
                        now,
                    ),
                )

        stored = self.get_connector(registration.connector_id)
        if stored is None:
            raise RuntimeError(f"Connector registration failed: {registration.connector_id}")
        return stored.to_model()

    def get_connector(self, connector_id: str) -> StoredConnector | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                  connector_id,
                  connector_name,
                  allowed_action_classes,
                  api_key_hash,
                  callback_url,
                  disabled,
                  created_at,
                  updated_at
                FROM approval_connectors
                WHERE connector_id = ?
                """,
                (connector_id,),
            ).fetchone()
        return _row_to_connector(row)

    def authenticate_api_key(self, api_key: str) -> StoredConnector | None:
        api_key_hash = hash_api_key_secret(api_key)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                  connector_id,
                  connector_name,
                  allowed_action_classes,
                  api_key_hash,
                  callback_url,
                  disabled,
                  created_at,
                  updated_at
                FROM approval_connectors
                WHERE api_key_hash = ?
                """,
                (api_key_hash,),
            ).fetchone()

        connector = _row_to_connector(row)
        if connector is None or connector.disabled:
            return None
        if not compare_digest(connector.api_key_hash, api_key_hash):
            return None
        return connector


def _row_to_connector(row: sqlite3.Row | None) -> StoredConnector | None:
    if row is None:
        return None
    return StoredConnector(
        connector_id=str(row["connector_id"]),
        connector_name=str(row["connector_name"]),
        allowed_action_classes=_deserialize_action_classes(
            str(row["allowed_action_classes"])
        ),
        api_key_hash=str(row["api_key_hash"]),
        callback_url=str(row["callback_url"]) if row["callback_url"] else None,
        disabled=bool(row["disabled"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )
