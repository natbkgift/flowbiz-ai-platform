"""API key authentication scaffolding for platform public endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from hmac import compare_digest
from hashlib import sha256
import json

from fastapi import Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from platform_app.api_key_store import APIKeyStore
from platform_app.config import PlatformSettings


@dataclass(frozen=True)
class APIPrincipal:
    key_id: str
    scopes: tuple[str, ...] = ()


class APIKeyRecord(BaseModel):
    """Bootstrap record representing a provisioned API key."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key_id: str = Field(min_length=1)
    secret_hash: str = Field(min_length=32)
    scopes: tuple[str, ...] = ()
    disabled: bool = False


def hash_api_key_secret(secret: str) -> str:
    return sha256(secret.encode("utf-8")).hexdigest()


def _parse_required_keys(raw: str) -> dict[str, APIKeyRecord]:
    """Parse `key_id:secret` pairs separated by commas into a lookup table.

    This is a bootstrap-only format. Real implementations should use a DB/secret store.
    """
    result: dict[str, APIKeyRecord] = {}
    for item in raw.split(","):
        token = item.strip()
        if not token or ":" not in token:
            continue
        key_id, secret = token.split(":", 1)
        key_id = key_id.strip()
        if not key_id:
            continue
        result[key_id] = APIKeyRecord(
            key_id=key_id,
            secret_hash=hash_api_key_secret(secret.strip()),
            scopes=("platform:chat",),
        )
    return result


def _parse_api_key_records_json(raw: str) -> dict[str, APIKeyRecord]:
    text = raw.strip() or "[]"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Invalid PLATFORM_AUTH_API_KEYS_JSON: {exc.msg}",
        ) from exc

    if not isinstance(parsed, list):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Invalid PLATFORM_AUTH_API_KEYS_JSON: expected a JSON array",
        )

    result: dict[str, APIKeyRecord] = {}
    try:
        for item in parsed:
            rec = APIKeyRecord.model_validate(item)
            result[rec.key_id] = rec
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Invalid API key record: {exc.errors()[0]['msg']}",
        ) from exc
    return result


def load_api_key_records(settings: PlatformSettings) -> dict[str, APIKeyRecord]:
    records = _parse_api_key_records_json(settings.auth_api_keys_json)
    if records:
        return records
    return _parse_required_keys(settings.required_api_keys)


def authenticate_api_key(
    settings: PlatformSettings,
    x_api_key: str | None,
    store: APIKeyStore | None = None,
) -> APIPrincipal:
    if settings.auth_mode == "disabled":
        return APIPrincipal(key_id="anonymous", scopes=("*", "public"))

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
    if store is not None:
        record = store.get_key(key_id)
    else:
        allowed = load_api_key_records(settings)
        record = allowed.get(key_id)
    given_hash = hash_api_key_secret(secret)
    if (
        record is None
        or record.disabled
        or not compare_digest(record.secret_hash, given_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    return APIPrincipal(key_id=record.key_id, scopes=record.scopes)


def require_scopes(principal: APIPrincipal, required_scopes: tuple[str, ...]) -> APIPrincipal:
    if not required_scopes:
        return principal
    principal_scopes = set(principal.scopes)
    if "*" in principal_scopes:
        return principal
    missing = [scope for scope in required_scopes if scope not in principal_scopes]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required scopes: {', '.join(missing)}",
        )
    return principal


def auth_dependency_factory(settings: PlatformSettings, store: APIKeyStore | None = None):
    async def _dep(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> APIPrincipal:
        return authenticate_api_key(settings, x_api_key, store=store)

    return _dep
