from __future__ import annotations

import os
import stat

from platform_app.api_key_store import SQLiteAPIKeyStore
from platform_app.auth import hash_api_key_secret
from platform_app.ops_auth import (
    DEFAULT_BOOTSTRAP_SCOPES,
    seed_or_rotate_bootstrap_admin_key,
)


def test_seed_or_rotate_bootstrap_admin_key_creates_key_and_file(tmp_path) -> None:
    db_path = tmp_path / "platform_auth.db"
    output_path = tmp_path / "bootstrap-admin-api-key.txt"

    result = seed_or_rotate_bootstrap_admin_key(
        db_path=str(db_path),
        output_path=str(output_path),
    )

    assert result.action == "created"
    assert output_path.exists()
    assert output_path.read_text(encoding="utf-8").startswith("bootstrap-admin:")

    store = SQLiteAPIKeyStore(str(db_path), hash_secret_fn=hash_api_key_secret)
    stored = store.get_key("bootstrap-admin")
    assert stored is not None
    assert stored.client_id == "platform-admin"
    assert stored.scopes == DEFAULT_BOOTSTRAP_SCOPES

    if os.name != "nt":
        mode = stat.S_IMODE(output_path.stat().st_mode)
        assert mode == 0o600


def test_seed_or_rotate_bootstrap_admin_key_rotates_existing_key(tmp_path) -> None:
    db_path = tmp_path / "platform_auth.db"
    output_path = tmp_path / "bootstrap-admin-api-key.txt"

    first = seed_or_rotate_bootstrap_admin_key(
        db_path=str(db_path),
        output_path=str(output_path),
    )
    first_value = output_path.read_text(encoding="utf-8")

    second = seed_or_rotate_bootstrap_admin_key(
        db_path=str(db_path),
        output_path=str(output_path),
    )
    second_value = output_path.read_text(encoding="utf-8")

    assert first.action == "created"
    assert second.action == "rotated"
    assert first_value != second_value
