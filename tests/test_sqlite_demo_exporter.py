from __future__ import annotations

import sqlite3

import pytest

from platform_app.data_export.sqlite_demo_exporter import ReadOnlySQLiteInventoryExporter


def test_read_only_sqlite_exporter_collects_synthetic_inventory(tmp_path) -> None:
    db_path = tmp_path / "synthetic_demo.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE demo_records (id TEXT PRIMARY KEY, status TEXT NOT NULL)")
        conn.execute("INSERT INTO demo_records (id, status) VALUES ('R001', 'demo')")
        conn.commit()

    before_bytes = db_path.read_bytes()
    exporter = ReadOnlySQLiteInventoryExporter({"synthetic_demo": db_path})

    inventory = exporter.inspect()

    assert db_path.read_bytes() == before_bytes
    assert len(inventory) == 1
    assert inventory[0].database_alias == "synthetic_demo"
    assert len(inventory[0].sha256) == 64
    assert [(table.table_name, table.row_count) for table in inventory[0].tables] == [
        ("demo_records", 1)
    ]


def test_read_only_sqlite_exporter_rejects_missing_database(tmp_path) -> None:
    exporter = ReadOnlySQLiteInventoryExporter({"missing": tmp_path / "missing.db"})

    with pytest.raises(FileNotFoundError):
        exporter.inspect()
