"""Rate limiting scaffolding for platform public API."""

from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Protocol

from fastapi import HTTPException, status

from platform_app.auth import APIPrincipal
from platform_app.config import PlatformSettings


@dataclass
class RateLimitDecision:
    allowed: bool
    key: str
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
            remaining=remaining,
            reset_epoch=(window + 1) * 60,
        )


class RedisFixedWindowRateLimiterSkeleton:
    """Redis-backed limiter skeleton (implementation pending).

    Intended shape for production:
    - key: {prefix}:{route}:{principal}:{window}
    - atomic increment with expiry via Lua or MULTI/EXEC
    """

    def __init__(self, redis_url: str, prefix: str, rpm: int) -> None:
        self.redis_url = redis_url
        self.prefix = prefix
        self.rpm = max(1, rpm)

    def bucket_key(self, principal: APIPrincipal, route_key: str, now: int | None = None) -> str:
        ts = int(time()) if now is None else now
        window = ts // 60
        return f"{self.prefix}:{route_key}:{principal.key_id}:{window}"

    def check(self, principal: APIPrincipal, route_key: str) -> RateLimitDecision:
        raise NotImplementedError(
            "Redis rate limiter skeleton selected but not implemented yet. "
            "Implement Redis client + atomic window increment before production enablement."
        )


def build_rate_limiter(settings: PlatformSettings):
    if settings.rate_limit_mode == "noop":
        return NoopRateLimiter()
    if settings.rate_limit_mode == "memory":
        return InMemoryFixedWindowRateLimiter(settings.rate_limit_rpm)
    if settings.rate_limit_mode == "redis":
        return RedisFixedWindowRateLimiterSkeleton(
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
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
        )
    return decision
