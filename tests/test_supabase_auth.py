from __future__ import annotations

import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from platform_app.config import PlatformSettings
from platform_app.supabase_auth import (
    AuthenticatedPrincipal,
    CachedJwksProvider,
    StaticJwksProvider,
    SupabaseAuthError,
    SupabaseJwtValidator,
    extract_bearer_token,
    supabase_auth_dependency_factory,
)

ISSUER = "https://issuer.example.test/auth/v1"
AUDIENCE = "authenticated"
KID = "test-key-1"


@pytest.fixture()
def signing_material():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    return private_key, {"keys": [public_jwk]}


def settings(auth_mode: str = "supabase") -> PlatformSettings:
    return PlatformSettings(
        auth_mode=auth_mode,
        supabase_jwt_issuer=ISSUER,
        supabase_jwt_audience=AUDIENCE,
        supabase_jwks_url="https://jwks.example.test",
    )


def mint_token(private_key, **overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "user_test_123",
        "email": "owner@example.test",
        "iat": now,
        "nbf": now,
        "exp": now + 300,
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": KID})


def validator_for(jwks: dict) -> SupabaseJwtValidator:
    return SupabaseJwtValidator(settings(), StaticJwksProvider(jwks))


def test_valid_token_returns_identity_only_principal(signing_material) -> None:
    private_key, jwks = signing_material
    token = mint_token(private_key)

    principal = validator_for(jwks).validate(
        token,
        request_id="req_test",
        tenant_selector="tenant_untrusted",
    )

    assert isinstance(principal, AuthenticatedPrincipal)
    assert principal.subject == "user_test_123"
    assert principal.email == "owner@example.test"
    assert principal.issuer == ISSUER
    assert principal.audience == (AUDIENCE,)
    assert principal.request_id == "req_test"
    assert principal.tenant_selector == "tenant_untrusted"
    assert principal.tenant_authorized is False
    assert "token" not in principal.model_dump()


def test_missing_and_malformed_bearer_are_rejected() -> None:
    with pytest.raises(SupabaseAuthError, match="Missing bearer token"):
        extract_bearer_token(None)
    with pytest.raises(SupabaseAuthError, match="Malformed Authorization header"):
        extract_bearer_token("Basic abc")
    with pytest.raises(SupabaseAuthError, match="Malformed Authorization header"):
        extract_bearer_token("Bearer ")


def test_invalid_signature_is_rejected(signing_material) -> None:
    private_key, jwks = signing_material
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = mint_token(other_key)

    with pytest.raises(SupabaseAuthError, match="Invalid bearer token"):
        validator_for(jwks).validate(token)


def test_expired_token_is_rejected(signing_material) -> None:
    private_key, jwks = signing_material
    token = mint_token(private_key, exp=int(time.time()) - 120)

    with pytest.raises(SupabaseAuthError, match="Invalid bearer token"):
        validator_for(jwks).validate(token)


def test_wrong_issuer_and_audience_are_rejected(signing_material) -> None:
    private_key, jwks = signing_material

    with pytest.raises(SupabaseAuthError, match="Invalid bearer token"):
        validator_for(jwks).validate(mint_token(private_key, iss="https://wrong.example.test"))

    with pytest.raises(SupabaseAuthError, match="Invalid bearer token"):
        validator_for(jwks).validate(mint_token(private_key, aud="wrong-audience"))


def test_unknown_kid_is_rejected(signing_material) -> None:
    private_key, jwks = signing_material
    token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "user_test_123",
            "exp": int(time.time()) + 300,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "unknown"},
    )

    with pytest.raises(SupabaseAuthError, match="Invalid bearer token"):
        validator_for(jwks).validate(token)


def test_jwks_fetch_failure_fails_closed() -> None:
    provider = CachedJwksProvider(
        lambda: (_ for _ in ()).throw(TimeoutError("jwks timeout")),
        cache_seconds=300,
    )
    validator = SupabaseJwtValidator(settings(), provider)

    with pytest.raises(SupabaseAuthError, match="Supabase JWKS unavailable"):
        validator.validate("not-a-token")


def test_jwks_cache_reuses_first_fetch(signing_material) -> None:
    _private_key, jwks = signing_material
    calls = 0

    def fetcher() -> dict:
        nonlocal calls
        calls += 1
        return jwks

    provider = CachedJwksProvider(fetcher, cache_seconds=300, clock=lambda: 100.0)
    assert provider.get_jwks() == jwks
    assert provider.get_jwks() == jwks
    assert calls == 1


def test_dependency_accepts_valid_token_and_does_not_authorize_tenant(signing_material) -> None:
    private_key, jwks = signing_material
    dependency = supabase_auth_dependency_factory(settings(), validator_for(jwks))
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(principal: AuthenticatedPrincipal = Depends(dependency)):
        return principal.model_dump()

    client = TestClient(app)
    response = client.get(
        "/whoami",
        headers={
            "Authorization": f"Bearer {mint_token(private_key)}",
            "X-Tenant-ID": "tenant_untrusted",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["subject"] == "user_test_123"
    assert body["tenant_selector"] == "tenant_untrusted"
    assert body["tenant_authorized"] is False
    assert "token" not in body


def test_dependency_rejects_missing_token(signing_material) -> None:
    _private_key, jwks = signing_material
    dependency = supabase_auth_dependency_factory(settings(), validator_for(jwks))
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(principal: AuthenticatedPrincipal = Depends(dependency)):
        return principal.model_dump()

    response = TestClient(app).get("/whoami")
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing bearer token"


def test_disabled_auth_mode_remains_local_bootstrap_compatible() -> None:
    dependency = supabase_auth_dependency_factory(settings(auth_mode="disabled"))
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(principal: AuthenticatedPrincipal = Depends(dependency)):
        return principal.model_dump()

    response = TestClient(app).get("/whoami", headers={"X-Tenant-ID": "tenant_untrusted"})
    assert response.status_code == 200
    body = response.json()
    assert body["subject"] == "local-disabled"
    assert body["tenant_selector"] == "tenant_untrusted"
    assert body["tenant_authorized"] is False
