"""Rate limiting scaffolding for platform public API."""

from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Protocol

from fastapi import HTTPException, Response, status

from platform_app.auth import APIPrincipal
from platform_app.config import PlatformSettings


@dataclass
class RateLimitDecision:
    allowed: bool
    key: str
    limit: int
    count: int
    remaining: int
    reset_epoch: int


class RateLimiter(Protocol):
    def check(self, principal: APIPrincipal, route_key: str) -> RateLimitDecision: ...


class NoopRateLimiter:
    def check(self, principal: APIPrincipal, route_key: str) -> RateLimitDecision:
        now = int(time())
        return RateLimitDecision(
            allowed=True,
            key=f"{principal.key_id}:{route_key}",
            limit=999999,
            count=0,
            remaining=999999,
            reset_epoch=now + 60,
        )


class InMemoryFixedWindowRateLimiter:
    """Bootstrap-only limiter for local/dev. Replace with Redis in production."""

    def __init__(self, rpm: int) -> None:
        self._rpm = max(1, rpm)
        self._buckets: dict[str, tuple[int, int]] = {}

    def check(self, principal: APIPrincipal, route_key: str) -> RateLimitDecision:
        now = int(time())
        window = now // 60
        key = f"{principal.key_id}:{route_key}"
        current_window, count = self._buckets.get(key, (window, 0))
        if current_window != window:
            current_window, count = window, 0
        count += 1
        self._buckets[key] = (current_window, count)
        remaining = max(0, self._rpm - count)
        return RateLimitDecision(
            allowed=count <= self._rpm,
            key=key,
            limit=self._rpm,
            count=count,
            remaining=remaining,
            reset_epoch=(window + 1) * 60,
        )


class RedisFixedWindowRateLimiter:
    """Redis-backed fixed-window limiter using Lua for atomic increment+expire."""

    _WINDOW_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('PEXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('PTTL', KEYS[1])
if ttl < 0 then
  ttl = ARGV[1]
  redis.call('PEXPIRE', KEYS[1], ttl)
end
return {current, ttl}
"""

    def __init__(self, redis_url: str, prefix: str, rpm: int, client=None) -> None:
        self.redis_url = redis_url
        self.prefix = prefix
        self.rpm = max(1, rpm)
        self._client = client
        self._script_sha: str | None = None

    def bucket_key(self, principal: APIPrincipal, route_key: str, now: int | None = None) -> str:
        ts = int(time()) if now is None else now
        window = ts // 60
        return f"{self.prefix}:{route_key}:{principal.key_id}:{window}"

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import redis  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "redis package is required for PLATFORM_RATE_LIMIT_MODE=redis"
            ) from exc
        self._client = redis.Redis.from_url(self.redis_url, decode_responses=False)
        return self._client

    def _eval_window(self, bucket_key: str) -> tuple[int, int]:
        client = self._get_client()
        ttl_ms = 60_000
        try:
            if self._script_sha is None:
                self._script_sha = client.script_load(self._WINDOW_SCRIPT)
            raw = client.evalsha(self._script_sha, 1, bucket_key, ttl_ms)
        except Exception as exc:
            # Retry on NOSCRIPT or client reset by reloading script once.
            if self._script_sha is not None and ("NOSCRIPT" in str(exc).upper()):
                self._script_sha = client.script_load(self._WINDOW_SCRIPT)
                raw = client.evalsha(self._script_sha, 1, bucket_key, ttl_ms)
            else:
                raise

        if not isinstance(raw, (list, tuple)) or len(raw) < 2:
            raise RuntimeError("Unexpected Redis Lua response for rate limit script")

        count = int(raw[0])
        pttl = int(raw[1])
        if pttl < 0:
            pttl = ttl_ms
        return count, pttl

    def check(self, principal: APIPrincipal, route_key: str) -> RateLimitDecision:
        now = time()
        key = self.bucket_key(principal, route_key, now=int(now))
        count, ttl_ms = self._eval_window(key)
        remaining = max(0, self.rpm - count)
        reset_epoch = int(now + max(1, ttl_ms) / 1000.0)
        return RateLimitDecision(
            allowed=count <= self.rpm,
            key=key,
            limit=self.rpm,
            count=count,
            remaining=remaining,
            reset_epoch=reset_epoch,
        )


def build_rate_limiter(settings: PlatformSettings):
    if settings.rate_limit_mode == "noop":
        return NoopRateLimiter()
    if settings.rate_limit_mode == "memory":
        return InMemoryFixedWindowRateLimiter(settings.rate_limit_rpm)
    if settings.rate_limit_mode == "redis":
        return RedisFixedWindowRateLimiter(
            redis_url=settings.rate_limit_redis_url,
            prefix=settings.rate_limit_redis_prefix,
            rpm=settings.rate_limit_rpm,
        )
    raise ValueError(f"Unsupported rate limit mode: {settings.rate_limit_mode}")


def enforce_rate_limit(limiter: RateLimiter, principal: APIPrincipal, route_key: str) -> RateLimitDecision:
    try:
        decision = limiter.check(principal, route_key)
    except NotImplementedError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    if not decision.allowed:
        headers = build_rate_limit_headers(decision)
        retry_after = max(0, decision.reset_epoch - int(time()))
        headers["Retry-After"] = str(retry_after)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers=headers,
        )
    return decision


def build_rate_limit_headers(decision: RateLimitDecision) -> dict[str, str]:
    return {
        "X-RateLimit-Limit": str(decision.limit),
        "X-RateLimit-Remaining": str(decision.remaining),
        "X-RateLimit-Reset": str(decision.reset_epoch),
    }


def apply_rate_limit_headers(response: Response, decision: RateLimitDecision) -> None:
    for key, value in build_rate_limit_headers(decision).items():
        response.headers[key] = value
