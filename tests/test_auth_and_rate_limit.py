from __future__ import annotations

import pytest
from fastapi import HTTPException

from platform_app.auth import (
    APIPrincipal,
    authenticate_api_key,
    hash_api_key_secret,
    load_api_key_records,
    require_scopes,
)
from platform_app.config import PlatformSettings
from platform_app.rate_limit import (
    RedisFixedWindowRateLimiterSkeleton,
    build_rate_limiter,
    enforce_rate_limit,
)


def _settings(**overrides) -> PlatformSettings:
    base = {
        "auth_mode": "disabled",
        "required_api_keys": "",
        "auth_api_keys_json": "[]",
        "rate_limit_mode": "noop",
        "rate_limit_rpm": 2,
        "rate_limit_redis_url": "redis://localhost:6379/0",
        "rate_limit_redis_prefix": "flowbiz:rl",
    }
    base.update(overrides)
    return PlatformSettings(**base)


def test_hash_api_key_secret_deterministic() -> None:
    assert hash_api_key_secret("secret-123") == hash_api_key_secret("secret-123")
    assert hash_api_key_secret("secret-123") != hash_api_key_secret("secret-456")


def test_authenticate_api_key_from_json_records_with_scopes() -> None:
    secret = "supersecret"
    settings = _settings(
        auth_mode="api_key",
        auth_api_keys_json=(
            '[{"key_id":"client-a","secret_hash":"'
            + hash_api_key_secret(secret)
            + '","scopes":["platform:chat","platform:meta"]}]'
        ),
    )
    principal = authenticate_api_key(settings, "client-a:supersecret")
    assert principal.key_id == "client-a"
    assert "platform:chat" in principal.scopes


def test_authenticate_api_key_rejects_bad_scope_check() -> None:
    principal = APIPrincipal(key_id="client-a", scopes=("platform:meta",))
    with pytest.raises(HTTPException) as exc:
        require_scopes(principal, ("platform:chat",))
    assert exc.value.status_code == 403


def test_load_api_key_records_falls_back_to_legacy_format() -> None:
    settings = _settings(auth_api_keys_json="[]", required_api_keys="demo:abc")
    records = load_api_key_records(settings)
    assert "demo" in records
    assert records["demo"].scopes == ("platform:chat",)


def test_build_rate_limiter_redis_mode_returns_skeleton() -> None:
    settings = _settings(
        rate_limit_mode="redis",
        rate_limit_rpm=123,
        rate_limit_redis_prefix="fb:rl",
    )
    limiter = build_rate_limiter(settings)
    assert isinstance(limiter, RedisFixedWindowRateLimiterSkeleton)
    bucket = limiter.bucket_key(APIPrincipal("client-a"), "platform:chat", now=120)
    assert bucket == "fb:rl:platform:chat:client-a:2"


def test_enforce_rate_limit_redis_skeleton_returns_503_until_implemented() -> None:
    limiter = RedisFixedWindowRateLimiterSkeleton(
        redis_url="redis://localhost:6379/0",
        prefix="fb:rl",
        rpm=10,
    )
    with pytest.raises(HTTPException) as exc:
        enforce_rate_limit(limiter, APIPrincipal("client-a"), "platform:chat")
    assert exc.value.status_code == 503

