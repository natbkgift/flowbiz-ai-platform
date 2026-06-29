"""Supabase JWT validation foundation for FlowBiz Platform APIs.

This module validates identity only. Tenant authorization and RBAC remain separate
future gates; an X-Tenant-ID header is treated as an untrusted selector only.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx
import jwt
from fastapi import Header, HTTPException, Request, status
from jwt import InvalidTokenError
from jwt.algorithms import RSAAlgorithm
from pydantic import BaseModel, ConfigDict, Field

from platform_app.config import PlatformSettings

JWKS = Mapping[str, Any]
JwksFetcher = Callable[[], JWKS]


class AuthenticatedPrincipal(BaseModel):
    """Validated Supabase identity without tenant authorization."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: str = Field(min_length=1)
    issuer: str = Field(min_length=1)
    audience: tuple[str, ...] = Field(min_length=1)
    expires_at: int
    email: str | None = None
    request_id: str | None = None
    tenant_selector: str | None = None
    tenant_authorized: bool = False


class SupabaseAuthError(Exception):
    """Safe auth error mapped by the FastAPI dependency."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _safe_unauthorized(detail: str) -> SupabaseAuthError:
    return SupabaseAuthError(status.HTTP_401_UNAUTHORIZED, detail)


def _safe_unavailable(detail: str) -> SupabaseAuthError:
    return SupabaseAuthError(status.HTTP_503_SERVICE_UNAVAILABLE, detail)


def extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise _safe_unauthorized("Missing bearer token")
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token.strip():
        raise _safe_unauthorized("Malformed Authorization header")
    return token.strip()


def _validate_jwks(raw: JWKS) -> dict[str, Any]:
    keys = raw.get("keys")
    if not isinstance(keys, list):
        raise _safe_unavailable("Supabase JWKS unavailable")
    normalized_keys: list[dict[str, Any]] = []
    for item in keys:
        if isinstance(item, dict):
            normalized_keys.append(dict(item))
    if not normalized_keys:
        raise _safe_unavailable("Supabase JWKS unavailable")
    return {"keys": normalized_keys}


class StaticJwksProvider:
    """In-memory provider for tests and local non-network validation."""

    def __init__(self, jwks: JWKS) -> None:
        self._jwks = _validate_jwks(jwks)

    def get_jwks(self) -> dict[str, Any]:
        return self._jwks


class CachedJwksProvider:
    """Small TTL cache around a JWKS fetch function."""

    def __init__(
        self,
        fetcher: JwksFetcher,
        cache_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetcher = fetcher
        self._cache_seconds = max(cache_seconds, 0)
        self._clock = clock
        self._cached: dict[str, Any] | None = None
        self._cached_at = 0.0

    def get_jwks(self) -> dict[str, Any]:
        now = self._clock()
        if (
            self._cached is not None
            and self._cache_seconds > 0
            and now - self._cached_at < self._cache_seconds
        ):
            return self._cached
        try:
            jwks = _validate_jwks(self._fetcher())
        except SupabaseAuthError:
            raise
        except Exception as exc:
            raise _safe_unavailable("Supabase JWKS unavailable") from exc
        self._cached = jwks
        self._cached_at = now
        return jwks


class HttpJwksProvider(CachedJwksProvider):
    """Fetch JWKS over HTTPS with timeout and TTL caching."""

    def __init__(self, url: str, timeout_seconds: float, cache_seconds: int) -> None:
        self._url = url
        self._timeout_seconds = timeout_seconds
        super().__init__(self._fetch, cache_seconds=cache_seconds)

    def _fetch(self) -> JWKS:
        if not self._url.strip():
            raise _safe_unavailable("Supabase JWKS URL is not configured")
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.get(self._url)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            raise _safe_unavailable("Supabase JWKS unavailable") from exc
        if not isinstance(payload, dict):
            raise _safe_unavailable("Supabase JWKS unavailable")
        return payload


class SupabaseJwtValidator:
    """Validate Supabase JWTs and return an identity-only principal."""

    def __init__(
        self,
        settings: PlatformSettings,
        jwks_provider: StaticJwksProvider | CachedJwksProvider | HttpJwksProvider,
    ) -> None:
        self._settings = settings
        self._jwks_provider = jwks_provider

    def validate(
        self,
        token: str,
        *,
        request_id: str | None = None,
        tenant_selector: str | None = None,
    ) -> AuthenticatedPrincipal:
        if self._settings.auth_mode != "supabase":
            raise _safe_unavailable("Supabase auth mode is not enabled")
        if not self._settings.supabase_auth_configured:
            raise _safe_unavailable("Supabase auth is not configured")
        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as exc:
            raise _safe_unauthorized("Invalid bearer token") from exc
        key = self._select_key(header)
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=("RS256",),
                audience=self._settings.supabase_jwt_audience,
                issuer=self._settings.supabase_jwt_issuer,
                leeway=self._settings.supabase_jwt_clock_skew_seconds,
                options={"require": ["aud", "exp", "iss", "sub"]},
            )
        except InvalidTokenError as exc:
            raise _safe_unauthorized("Invalid bearer token") from exc
        return self._claims_to_principal(
            claims,
            request_id=request_id,
            tenant_selector=tenant_selector,
        )

    def _select_key(self, header: Mapping[str, Any]) -> object:
        kid = header.get("kid")
        alg = header.get("alg")
        if not isinstance(kid, str) or not kid:
            raise _safe_unauthorized("Invalid bearer token")
        if alg != "RS256":
            raise _safe_unauthorized("Invalid bearer token")
        jwks = self._jwks_provider.get_jwks()
        for key_data in jwks["keys"]:
            if key_data.get("kid") == kid:
                try:
                    return RSAAlgorithm.from_jwk(key_data)
                except Exception as exc:
                    raise _safe_unavailable("Supabase JWKS unavailable") from exc
        raise _safe_unauthorized("Invalid bearer token")

    def _claims_to_principal(
        self,
        claims: Mapping[str, Any],
        *,
        request_id: str | None,
        tenant_selector: str | None,
    ) -> AuthenticatedPrincipal:
        subject = claims.get("sub")
        issuer = claims.get("iss")
        audience = claims.get("aud")
        expires_at = claims.get("exp")
        if not isinstance(subject, str) or not subject:
            raise _safe_unauthorized("Invalid bearer token")
        if not isinstance(issuer, str) or not issuer:
            raise _safe_unauthorized("Invalid bearer token")
        if isinstance(audience, str):
            audience_tuple = (audience,)
        elif isinstance(audience, list) and all(isinstance(item, str) for item in audience):
            audience_tuple = tuple(audience)
        else:
            raise _safe_unauthorized("Invalid bearer token")
        if not isinstance(expires_at, int):
            raise _safe_unauthorized("Invalid bearer token")
        email = claims.get("email")
        return AuthenticatedPrincipal(
            subject=subject,
            issuer=issuer,
            audience=audience_tuple,
            expires_at=expires_at,
            email=email if isinstance(email, str) else None,
            request_id=request_id,
            tenant_selector=tenant_selector if tenant_selector else None,
            tenant_authorized=False,
        )


def build_supabase_jwks_provider(settings: PlatformSettings) -> HttpJwksProvider:
    return HttpJwksProvider(
        url=settings.supabase_jwks_url,
        timeout_seconds=settings.supabase_jwks_timeout_seconds,
        cache_seconds=settings.supabase_jwks_cache_seconds,
    )


def supabase_auth_dependency_factory(
    settings: PlatformSettings,
    validator: SupabaseJwtValidator | None = None,
):
    active_validator = validator or SupabaseJwtValidator(
        settings,
        build_supabase_jwks_provider(settings),
    )

    def _dep(
        request: Request,
        authorization: str | None = Header(default=None, alias="Authorization"),
        x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    ) -> AuthenticatedPrincipal:
        request_id = getattr(request.state, "request_id", None)
        if settings.auth_mode == "disabled":
            return AuthenticatedPrincipal(
                subject="local-disabled",
                issuer="local-bootstrap",
                audience=("local",),
                expires_at=0,
                request_id=request_id,
                tenant_selector=x_tenant_id if x_tenant_id else None,
                tenant_authorized=False,
            )
        if settings.auth_mode != "supabase":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Unsupported Supabase auth mode: {settings.auth_mode}",
            )
        try:
            token = extract_bearer_token(authorization)
            return active_validator.validate(
                token,
                request_id=request_id,
                tenant_selector=x_tenant_id,
            )
        except SupabaseAuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return _dep
