"""Read-only SQLite inventory helpers for demo-record migration planning.

This module does not run against the real platform SQLite files by default and
never writes to SQLite or PostgreSQL. Real export/import remains a later,
separately authorized owner action.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import sqlite3


@dataclass(frozen=True)
class SQLiteTableInventory:
    database_alias: str
    table_name: str
    row_count: int


@dataclass(frozen=True)
class SQLiteDatabaseInventory:
    database_alias: str
    sha256: str
    tables: tuple[SQLiteTableInventory, ...]


class ReadOnlySQLiteInventoryExporter:
    """Collect non-sensitive SQLite inventory through read-only connections."""

    def __init__(self, database_paths: dict[str, Path]) -> None:
        self._database_paths = dict(database_paths)

    def inspect(self) -> tuple[SQLiteDatabaseInventory, ...]:
        inventories: list[SQLiteDatabaseInventory] = []
        for alias, path in sorted(self._database_paths.items()):
            before_hash = _sha256(path)
            tables = _inspect_tables(alias, path)
            after_hash = _sha256(path)
            if before_hash != after_hash:
                raise RuntimeError(f"SQLite snapshot changed during read-only inspection: {alias}")
            inventories.append(
                SQLiteDatabaseInventory(
                    database_alias=alias,
                    sha256=after_hash,
                    tables=tuple(tables),
                )
            )
        return tuple(inventories)


def _inspect_tables(database_alias: str, path: Path) -> list[SQLiteTableInventory]:
    uri = f"file:{path.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        query_only = conn.execute("PRAGMA query_only").fetchone()
        if query_only is None or query_only[0] != 1:
            raise RuntimeError("SQLite connection is not query-only")
        table_names = [
            row[0]
            for row in conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            )
        ]
        return [
            SQLiteTableInventory(
                database_alias=database_alias,
                table_name=table_name,
                row_count=int(conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]),
            )
            for table_name in table_names
        ]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
