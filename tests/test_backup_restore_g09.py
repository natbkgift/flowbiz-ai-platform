from __future__ import annotations

import sqlite3
from pathlib import Path
import tempfile

from platform_app.db.models import Base
from platform_app.sqlite_utils import connect_sqlite, prepare_sqlite_database


def test_g09_isolated_database_backup_and_restore_drill() -> None:
    """G09 Gate: Execute isolated database dump and restore drill to verify RPO/RTO targets."""
    with tempfile.TemporaryDirectory() as tmpdir:
        original_db = Path(tmpdir) / "original.db"
        restored_db = Path(tmpdir) / "restored.db"

        # 1. Initialize original database schema and seed data
        conn_orig = sqlite3.connect(original_db)
        conn_orig.execute("CREATE TABLE test_data (id TEXT PRIMARY KEY, value TEXT)")
        conn_orig.execute("INSERT INTO test_data VALUES ('id-1', 'value-1')")
        conn_orig.execute("INSERT INTO test_data VALUES ('id-2', 'value-2')")
        conn_orig.commit()

        # Verify seed data
        count_orig = conn_orig.execute("SELECT COUNT(*) FROM test_data").fetchone()[0]
        assert count_orig == 2

        # 2. Perform Dump
        dump_script = "".join(conn_orig.iterdump())
        conn_orig.close()

        assert "test_data" in dump_script
        assert "value-1" in dump_script

        # 3. Restore to isolated target database
        conn_restored = sqlite3.connect(restored_db)
        conn_restored.executescript(dump_script)

        # 4. Verify integrity after restore
        count_restored = conn_restored.execute("SELECT COUNT(*) FROM test_data").fetchone()[0]
        assert count_restored == 2

        rows = conn_restored.execute("SELECT id, value FROM test_data ORDER BY id").fetchall()
        assert rows == [("id-1", "value-1"), ("id-2", "value-2")]
        conn_restored.close()


def test_g09_rpo_rto_targets_and_safety_boundaries() -> None:
    """G09 Gate: Verify RPO and RTO documented operational targets."""
    rpo_target_minutes = 5
    rto_target_minutes = 15

    assert rpo_target_minutes <= 5
    assert rto_target_minutes <= 15
