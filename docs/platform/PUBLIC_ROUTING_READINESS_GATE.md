# Platform Public Routing Readiness Gate

## Decision

The platform is not ready for public routing.

Do not point `flowbiz.cloud/api` to the platform yet. Do not add or reload Nginx
configuration for this service until every blocker below is closed.

## Required Before Public Routing

- VPS deployed commit matches an approved release commit SHA.
- `PLATFORM_ENV=production`.
- FastAPI docs, ReDoc, and OpenAPI are disabled in production.
- `PLATFORM_AUTH_MODE=api_key`.
- Admin/internal routes require scoped API keys.
- `PLATFORM_RATE_LIMIT_MODE=redis`.
- Redis backend is reachable from the platform container.
- Redis unavailable behavior is accepted as fail-closed.
- CORS is explicitly configured for approved origins only.
- `/healthz`, `/readyz`, and `/v1/meta` expose only public-safe metadata.
- Metrics and observability routes are internal/protected.
- `.env`, SQLite DBs, and bootstrap admin key file permissions pass preflight.
- No `.env.backup.*` files exist in the active runtime path.
- Runner dispatch hostname resolves from the platform container on an approved
  internal network.
- No production POST smoke tests are required for routing readiness.

## Explicit Non-Goals For This Gate

- Do not expose the platform publicly.
- Do not deploy Hermes.
- Do not change client application repos.
- Do not reload Nginx.
- Do not run production workflow dispatches.

## Routing Decision Checklist

Before Nginx is changed, attach this evidence to the release record:

- Approved commit SHA.
- Read-only permission preflight result.
- Internal GET smoke result for `/healthz`, `/readyz`, and `/v1/meta`.
- Authenticated internal GET result for `/v1/platform/ops/observability`.
- Redis connectivity evidence from inside the platform container.
- Runner DNS evidence from inside the platform container.
- Confirmation that docs routes return `404` in production.

## Current Blockers

- Deployed copy is behind local `main`.
- Current runtime rate limiting is `noop`.
- Current runtime LLM provider is `stub`.
- Runner hostnames do not resolve from the platform container.
- Active runtime path has an `.env.backup.` file.
- Secret and SQLite file permissions still need manual remediation.
