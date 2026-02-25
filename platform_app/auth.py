"""API key authentication scaffolding for platform public endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from fastapi import Header, HTTPException, status

from platform_app.config import PlatformSettings


@dataclass(frozen=True)
class APIPrincipal:
    key_id: str
    scopes: tuple[str, ...] = ()


def _parse_required_keys(raw: str) -> dict[str, str]:
    """Parse `key_id:secret` pairs separated by commas into a lookup table.

    This is a bootstrap-only format. Real implementations should use a DB/secret store.
    """
    result: dict[str, str] = {}
    for item in raw.split(","):
        token = item.strip()
        if not token or ":" not in token:
            continue
        key_id, secret = token.split(":", 1)
        result[key_id.strip()] = sha256(secret.strip().encode("utf-8")).hexdigest()
    return result


def authenticate_api_key(
    settings: PlatformSettings,
    x_api_key: str | None,
) -> APIPrincipal:
    if settings.auth_mode == "disabled":
        return APIPrincipal(key_id="anonymous", scopes=("public",))

    if settings.auth_mode != "api_key":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Unsupported auth mode: {settings.auth_mode}",
        )

    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key",
        )

    if ":" not in x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key format",
        )

    key_id, secret = x_api_key.split(":", 1)
    allowed = _parse_required_keys(settings.required_api_keys)
    expected_hash = allowed.get(key_id)
    given_hash = sha256(secret.encode("utf-8")).hexdigest()
    if not expected_hash or expected_hash != given_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    return APIPrincipal(key_id=key_id, scopes=("platform:chat",))


def auth_dependency_factory(settings: PlatformSettings):
    async def _dep(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> APIPrincipal:
        return authenticate_api_key(settings, x_api_key)

    return _dep

