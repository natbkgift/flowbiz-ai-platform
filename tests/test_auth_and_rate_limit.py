from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi import Response

from platform_app.api_key_store import SQLiteAPIKeyStore
from platform_app.auth import (
    APIPrincipal,
    authenticate_api_key,
    hash_api_key_secret,
    load_api_key_records,
    require_scopes,
)
from platform_app.config import PlatformSettings
from platform_app.rate_limit import (
    RedisFixedWindowRateLimiter,
    apply_rate_limit_headers,
    build_rate_limiter,
    build_rate_limit_headers,
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


def test_sqlite_api_key_store_create_get_rotate_revoke(tmp_path) -> None:
    db_path = tmp_path / "auth.db"
    store = SQLiteAPIKeyStore(str(db_path), hash_secret_fn=hash_api_key_secret)
    issued = store.create_key("client-a", ("platform:chat", "platform:meta"))
    loaded = store.get_key("client-a")
    assert loaded is not None
    assert loaded.key_id == "client-a"
    assert loaded.disabled is False
    assert "platform:chat" in loaded.scopes
    assert loaded.secret_hash == issued.secret_hash

    rotated = store.rotate_key("client-a")
    assert rotated.key_id == "client-a"
    assert rotated.secret_hash != issued.secret_hash
    assert rotated.secret_plaintext != issued.secret_plaintext

    store.revoke_key("client-a")
    revoked = store.get_key("client-a")
    assert revoked is not None
    assert revoked.disabled is True


def test_authenticate_api_key_against_sqlite_store(tmp_path) -> None:
    db_path = tmp_path / "auth.db"
    store = SQLiteAPIKeyStore(str(db_path), hash_secret_fn=hash_api_key_secret)
    issued = store.create_key("client-a", ("platform:chat",))
    settings = _settings(auth_mode="api_key", auth_store_mode="sqlite")
    principal = authenticate_api_key(settings, f"client-a:{issued.secret_plaintext}", store=store)
    assert principal.key_id == "client-a"
    assert principal.scopes == ("platform:chat",)


def test_build_rate_limiter_redis_mode_returns_impl() -> None:
    settings = _settings(
        rate_limit_mode="redis",
        rate_limit_rpm=123,
        rate_limit_redis_prefix="fb:rl",
    )
    limiter = build_rate_limiter(settings)
    assert isinstance(limiter, RedisFixedWindowRateLimiter)
    bucket = limiter.bucket_key(APIPrincipal("client-a"), "platform:chat", now=120)
    assert bucket == "fb:rl:platform:chat:client-a:2"


class _FakeRedisClient:
    def __init__(self) -> None:
        self._sha = "sha1"
        self._counts: dict[str, int] = {}
        self._ttl_ms: int = 60_000
        self._loaded = False

    def script_load(self, script: str) -> str:
        assert "INCR" in script
        self._loaded = True
        return self._sha

    def evalsha(self, sha: str, numkeys: int, key: str, ttl_ms: int):
        assert self._loaded is True
        assert sha == self._sha
        assert numkeys == 1
        self._ttl_ms = int(ttl_ms)
        self._counts[key] = self._counts.get(key, 0) + 1
        return [self._counts[key], self._ttl_ms]


def test_redis_rate_limiter_check_and_headers() -> None:
    limiter = RedisFixedWindowRateLimiter(
        redis_url="redis://example",
        prefix="fb:rl",
        rpm=2,
        client=_FakeRedisClient(),
    )
    principal = APIPrincipal("client-a")
    first = enforce_rate_limit(limiter, principal, "platform:chat")
    second = enforce_rate_limit(limiter, principal, "platform:chat")
    assert first.allowed is True
    assert first.remaining == 1
    assert second.remaining == 0
    headers = build_rate_limit_headers(second)
    assert headers["X-RateLimit-Limit"] == "2"
    assert headers["X-RateLimit-Remaining"] == "0"
    resp = Response()
    apply_rate_limit_headers(resp, second)
    assert resp.headers["X-RateLimit-Limit"] == "2"


def test_redis_rate_limiter_raises_429_with_headers() -> None:
    limiter = RedisFixedWindowRateLimiter(
        redis_url="redis://example",
        prefix="fb:rl",
        rpm=1,
        client=_FakeRedisClient(),
    )
    principal = APIPrincipal("client-a")
    enforce_rate_limit(limiter, principal, "platform:chat")
    with pytest.raises(HTTPException) as exc:
        enforce_rate_limit(limiter, principal, "platform:chat")
    assert exc.value.status_code == 429
    assert exc.value.headers is not None
    assert "X-RateLimit-Limit" in exc.value.headers
