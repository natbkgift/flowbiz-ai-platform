"""SQLite connection helpers shared by platform stores."""

from __future__ import annotations

import sqlite3

SQLITE_BUSY_TIMEOUT_MS = 30_000


class PlatformSQLiteConnection(sqlite3.Connection):
    """SQLite connection that closes when used as a context manager."""

    def __exit__(self, exc_type, exc, traceback) -> bool | None:
        try:
            return super().__exit__(exc_type, exc, traceback)
        finally:
            self.close()


def connect_sqlite(db_path: str) -> sqlite3.Connection:
    """Open SQLite with platform defaults that reduce transient write failures."""

    conn = sqlite3.connect(
        db_path,
        timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,
        factory=PlatformSQLiteConnection,
    )
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def prepare_sqlite_database(conn: sqlite3.Connection) -> None:
    """Apply persistent DB settings after opening a writable SQLite database."""

    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
