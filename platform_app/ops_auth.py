"""Operational helpers for production auth bootstrap."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from platform_app.api_key_store import SQLiteAPIKeyStore
from platform_app.auth import hash_api_key_secret
from platform_app.routes.platform import API_KEY_MANAGE_SCOPE

DEFAULT_BOOTSTRAP_KEY_ID = "bootstrap-admin"
DEFAULT_BOOTSTRAP_CLIENT_ID = "platform-admin"
DEFAULT_BOOTSTRAP_SCOPES = (API_KEY_MANAGE_SCOPE, "platform:chat")


@dataclass(frozen=True)
class BootstrapKeyResult:
    action: str
    key_id: str
    client_id: str
    scopes: tuple[str, ...]
    output_path: str


def seed_or_rotate_bootstrap_admin_key(
    *,
    db_path: str,
    output_path: str,
    key_id: str = DEFAULT_BOOTSTRAP_KEY_ID,
    client_id: str = DEFAULT_BOOTSTRAP_CLIENT_ID,
    scopes: tuple[str, ...] = DEFAULT_BOOTSTRAP_SCOPES,
    reason: str = "vps_auth_hardening",
) -> BootstrapKeyResult:
    """Create or rotate the bootstrap admin key and write it to a file.

    The plaintext key is written only to ``output_path``. Callers should
    treat that file as sensitive operational state.
    """

    store = SQLiteAPIKeyStore(db_path, hash_secret_fn=hash_api_key_secret)
    existing = store.get_key(key_id)
    if existing is None:
        issued = store.create_key(
            key_id=key_id,
            scopes=scopes,
            client_id=client_id,
            actor="bootstrap",
            actor_type="system",
            reason=reason,
        )
        action = "created"
    else:
        issued = store.rotate_key(
            key_id=key_id,
            actor="bootstrap",
            actor_type="system",
            reason=f"{reason}_rotate",
        )
        action = "rotated"

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        f"{issued.key_id}:{issued.secret_plaintext}\n",
        encoding="utf-8",
    )
    if os.name != "nt":
        os.chmod(destination, 0o600)

    return BootstrapKeyResult(
        action=action,
        key_id=issued.key_id,
        client_id=issued.client_id or client_id,
        scopes=issued.scopes,
        output_path=str(destination),
    )
