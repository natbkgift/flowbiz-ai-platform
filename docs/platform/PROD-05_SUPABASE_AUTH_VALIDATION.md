<!-- markdownlint-disable MD013 -->

# PROD-05 Supabase Auth Validation Foundation

## Status

`DRAFT_FOUNDATION`

## Objective

PROD-05 adds a fail-closed Supabase JWT validation foundation for Platform APIs. It validates caller identity for the Platform boundary defined in PROD-02:

`Browser -> Next.js BFF -> Platform API`

The browser must not call Platform directly. The BFF forwards a Supabase bearer token to Platform. Platform validates signature, issuer, audience, and expiry before producing an identity-only principal.

## Scope

Included:

- Supabase JWT validation settings.
- JWKS fetch and TTL cache primitives.
- RS256 JWT signature, issuer, audience, and expiry validation.
- FastAPI dependency factory for future `/v1` route implementations.
- Identity-only `AuthenticatedPrincipal` model.
- Unit and dependency tests using generated test keys only.

Excluded:

- Product BFF authentication implementation.
- Tenant membership lookup or RBAC enforcement.
- PostgreSQL user/tenant writes.
- SQLite mutation or demo data migration.
- Production Supabase credentials or project URLs.
- Core dependency pinning.
- Deployment, tags, releases, or package publication.

## Configuration

Local bootstrap remains disabled by default:

```env
PLATFORM_AUTH_MODE=disabled
```

Supabase mode requires these values at runtime. They are intentionally blank in documentation and must be provided through an approved secret/config channel later:

```env
PLATFORM_AUTH_MODE=supabase
PLATFORM_SUPABASE_JWT_ISSUER=
PLATFORM_SUPABASE_JWT_AUDIENCE=
PLATFORM_SUPABASE_JWKS_URL=
PLATFORM_SUPABASE_JWKS_CACHE_SECONDS=300
PLATFORM_SUPABASE_JWKS_TIMEOUT_SECONDS=2
PLATFORM_SUPABASE_JWT_CLOCK_SKEW_SECONDS=30
```

Do not commit production values, access tokens, service-role keys, anon keys, JWTs, private keys, or project-specific URLs.

## Security Properties

- Missing or malformed bearer tokens return `401`.
- Invalid signature, issuer, audience, expiry, algorithm, or `kid` returns `401`.
- Missing or unavailable JWKS returns `503` and fails closed.
- Only `RS256` is accepted.
- Raw bearer tokens are never returned by the principal model.
- `X-Tenant-ID` is preserved only as an untrusted selector.
- `tenant_authorized` remains `false` until a later tenant/RBAC gate performs authoritative membership checks.

## Failure Modes

| Condition | Safe response |
| --- | --- |
| Missing bearer token | `401 Missing bearer token` |
| Malformed Authorization header | `401 Malformed Authorization header` |
| Invalid JWT or claims | `401 Invalid bearer token` |
| Unknown `kid` | `401 Invalid bearer token` |
| JWKS timeout/fetch/parse failure | `503 Supabase JWKS unavailable` |
| Supabase mode missing config | `503 Supabase auth is not configured` |
| Unsupported auth mode for Supabase dependency | `503` |

## Test Evidence Required

Run before review or merge gate:

```powershell
python -m ruff format --check .
python -m ruff check .
python -m pytest -q
python -m pytest tests/test_supabase_auth_validation.py -q
```

## Remaining Gates

- PROD-06: tenant membership and RBAC enforcement.
- Product BFF auth/session implementation remains separate.
- Platform route wiring for the Facebook Ads `/v1` contract remains separate.
- Production Supabase configuration remains blocked until explicit owner approval.
