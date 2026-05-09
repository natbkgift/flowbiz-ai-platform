# FlowBiz AI Platform Internal Hardening Gate Report

## 1. Summary

This phase hardens the platform as an internal-only service before any public
routing is allowed. The branch is `feat/platform-internal-hardening-gate`.

Current repo/runtime parity finding:

- Local `main` and `origin/main`: `c0353a4fbb1fa051b0c72f2df9ee4d79cab7e933`
- VPS deployed copy at `/opt/flowbiz-ai-platform`: `47288ca36bd734717b09717ee5de5c3a4d32d534`
- Missing on VPS: `c0353a4 Codify production auth lane`
- VPS working tree shows an untracked `.env.backup.` file. Its contents were
  not read.

The deployed container was not restarted, Nginx was not reloaded, Docker
networks were not changed, and no production POST requests were made.

## 2. Files Changed

- `apps/platform_api/main.py`
- `Dockerfile`
- `README.md`
- `platform_app/config.py`
- `platform_app/dispatch_records.py`
- `platform_app/file_permissions.py`
- `platform_app/middleware.py`
- `platform_app/observability.py`
- `platform_app/rate_limit.py`
- `platform_app/routes/platform.py`
- `platform_app/routes/system.py`
- `platform_app/routes/workflow_events.py`
- `platform_app/runtime.py`
- `scripts/check_platform_file_permissions.py`
- `scripts/remediate_platform_file_permissions.sh`
- `tests/test_auth_and_rate_limit.py`
- `tests/test_dispatch_records.py`
- `tests/test_internal_hardening_gate.py`
- `tests/test_llm_and_secrets.py`
- `tests/test_platform_smoke.py`
- `docs/platform/DEPLOYMENT_CHECKLIST.md`
- `docs/platform/PUBLIC_ROUTING_READINESS_GATE.md`
- `docs/platform/RUNNER_CONNECTIVITY.md`
- `docs/platform/SECRET_PERMISSION_POLICY.md`

## 3. Public Surface Hardening

- FastAPI docs, ReDoc, and OpenAPI are disabled automatically when
  `PLATFORM_ENV=production`, unless explicitly overridden. Production validation
  rejects an override that enables them.
- `/healthz` no longer returns environment name.
- `/v1/meta` returns a public-safe shape in production: service, version,
  `core_dependency.installed`, and coarse capabilities only.
- `/readyz` was added as a safe readiness endpoint.
- CORS is explicit and environment-driven. Empty CORS config means no CORS
  middleware. Wildcard CORS is rejected in production.
- Routers are tagged as `public` or `internal` to make public-safe vs internal
  routes visible in route registration and OpenAPI during development.

## 4. Auth / API Key Changes

- `/v1/platform/ops/observability` now requires API key auth when auth mode is
  enabled.
- New internal ops scope: `platform:ops:read`.
- New protected internal endpoints:
  - `GET /v1/platform/ops/metrics`
  - `POST /v1/platform/ops/llm/smoke`
- `/healthz`, `/readyz`, and `/v1/meta` remain unauthenticated and are kept
  intentionally low-information.

## 5. Rate Limit Changes

- Production validation now requires `PLATFORM_RATE_LIMIT_MODE=redis`.
- Redis-backed rate limiting fails closed with `503` and `Retry-After: 5` if the
  backend is unavailable.
- Allowed requests still receive `X-RateLimit-Limit`,
  `X-RateLimit-Remaining`, and `X-RateLimit-Reset`.
- Exceeded requests return `429` with rate limit headers and `Retry-After`.
- `noop` remains available for local development only.

## 6. LLM Provider Readiness

- `stub` remains available for local and development.
- Non-stub provider validation now checks required provider secret availability
  without printing secret values.
- OpenAI configuration requires a non-stub model and a resolvable configured
  secret name.
- `POST /v1/platform/ops/llm/smoke` exercises the configured adapter with a
  fixed non-sensitive smoke prompt and does not return prompt text or model
  output.

## 7. Secret Permission Policy

- Required policy documented in `SECRET_PERMISSION_POLICY.md`:
  - `.env`: `600`
  - `.env.backup.*`: must not exist in active runtime repo path
  - SQLite DB files: `600` or restricted owner/group equivalent
  - bootstrap admin key file: `600`
- `scripts/check_platform_file_permissions.py` is read-only and reports path,
  kind, status, and mode only.
- `scripts/remediate_platform_file_permissions.sh` is manual-only and gated by
  `CONFIRM_PLATFORM_PERMISSION_REMEDIATION=apply`; it was not run.

## 8. Workflow Runner Connectivity Plan

Observed read-only VPS topology:

- `flowbiz-ai-platform-prod` is attached only to Docker `bridge`.
- `flowbiz-infra-n8n-api-1`, `flowbiz-infra-n8n-n8n-1`, Postgres, and Redis are
  on `flowbiz-infra-n8n_default`.
- `flowbiz-platform-internal` exists but has no containers attached.
- Hostname lookups for n8n/api/redis names from the platform container return no
  records because the platform is not on those networks.

Recommendation:

- Use a dedicated shared internal control network, preferably the existing
  `flowbiz-platform-internal`, and attach only the platform plus the specific
  runner/API service that should receive dispatches.
- Avoid joining the platform directly to `flowbiz-infra-n8n_default` as the
  long-term design because that grants broad network access to n8n Postgres,
  Redis, and n8n internals.
- Do not change Docker networks until the runner boundary and service alias are
  approved.

## 9. Health / Readiness / Observability

- `/healthz` remains liveness-only.
- `/readyz` was added for readiness checks.
- Dockerfile now includes a liveness `HEALTHCHECK` against `/healthz`.
- Request/correlation ID middleware adds `X-Request-ID` and
  `X-Correlation-ID`.
- Structured JSON access logging was added without request bodies or secrets.
- Metrics design is internal/protected at `/v1/platform/ops/metrics`.

## 10. Tests Added

- Production docs disabled.
- Production validation rejects docs-enabled and noop rate limit.
- Production `/v1/meta` hides `env` and detailed `modes`.
- `/readyz` and request ID response header.
- Ops observability/metrics auth.
- LLM smoke path protection and no prompt/output leak.
- Explicit CORS allowed-origin behavior.
- Redis backend unavailable fail-closed behavior.
- Non-stub LLM provider secret validation.
- Dispatch URL validation.
- File permission preflight does not include file contents in findings.

## 11. Validation Commands Run

- `git rev-parse HEAD`
- `git rev-parse origin/main`
- `ssh flowbiz-vps "cd /opt/flowbiz-ai-platform && git rev-parse HEAD && git status --short --branch"`
- `git log --oneline 47288ca36bd734717b09717ee5de5c3a4d32d534..c0353a4fbb1fa051b0c72f2df9ee4d79cab7e933`
- `git diff --stat 47288ca36bd734717b09717ee5de5c3a4d32d534..c0353a4fbb1fa051b0c72f2df9ee4d79cab7e933`
- `ssh flowbiz-vps "docker ps --format '{{.Names}} {{.Networks}} {{.Ports}}'"`
- `ssh flowbiz-vps "docker inspect flowbiz-ai-platform-prod --format '{{json .NetworkSettings.Networks}}'"`
- `ssh flowbiz-vps "docker network ls --format '{{.Name}} {{.Driver}} {{.Scope}}'"`
- `ssh flowbiz-vps "docker network inspect flowbiz-platform-internal --format '{{json .Containers}}'"`
- `ssh flowbiz-vps "docker network inspect flowbiz-infra-n8n_default --format '{{json .Containers}}'"`
- `ssh flowbiz-vps "docker exec flowbiz-ai-platform-prod getent hosts flowbiz-infra-n8n-api-1 || true"`
- `ssh flowbiz-vps "docker exec flowbiz-ai-platform-prod getent hosts flowbiz-infra-n8n-n8n-1 || true"`
- `ssh flowbiz-vps "docker exec flowbiz-ai-platform-prod getent hosts flowbiz-redis || true"`
- `python -m ruff check .`
- `pytest -q`
- `python -c "from apps.platform_api.main import create_app; app = create_app(); print('app_import_ok routes=' + str(len(app.routes)))"`
- `python -c "from apps.platform_api.main import create_app; app=create_app(); paths=sorted(getattr(route, 'path', '') for route in app.routes); required={'/healthz','/readyz','/v1/meta','/v1/platform/ops/observability','/v1/platform/ops/metrics','/v1/platform/ops/llm/smoke'}; missing=required-set(paths); print('route_registration_ok' if not missing else 'missing=' + ','.join(sorted(missing)))"`
- `python scripts\check_platform_file_permissions.py --root .`

Final local validation results:

- `ruff check .`: passed
- `pytest -q`: `80 passed, 1 skipped`
- app import smoke: `app_import_ok routes=24`
- route registration smoke: `route_registration_ok`
- local permission preflight on Windows: `MANUAL_REVIEW` for `.env` and
  `platform_data/workflow_events.db` because POSIX mode checks are not available;
  no secret values were printed.

## 12. Remaining Risks

- The VPS deployed copy remains behind current `main` and behind this branch.
- Production `.env` likely still has `PLATFORM_RATE_LIMIT_MODE=noop` until
  manually changed in a future deployment window.
- LLM provider remains `stub` in the current deployed runtime.
- `flowbiz-ai-core` is still not installed in the deployed runtime.
- The platform container cannot resolve the runner hostname until Docker network
  topology is changed.
- Nginx public routing is still not configured for this platform and must remain
  blocked until the public routing readiness gate passes.

## 13. Deployment Blockers

- Select and configure Redis reachability for platform rate limiting.
- Select and configure the internal runner network and dispatch hostname.
- Remove or move `.env.backup.*` files out of the active runtime path.
- Restrict `.env`, SQLite DBs, and bootstrap key file permissions.
- Configure a real LLM provider and secret source if public behavior depends on
  real model execution.
- Install or otherwise satisfy `flowbiz-ai-core` only when the integration lane
  requires it and with the core repo boundary respected.

## 14. Public Routing Readiness Decision

- Safe to expose publicly now: No.
- Safe to point `flowbiz.cloud/api` to the platform now: No.
- Blocked by: repo/runtime drift, Redis rate limit not active in deployed
  runtime, LLM still stub, runner DNS/network unresolved, secret file permission
  findings, and pending deployment verification.

## 15. Next Recommended Phase

Run a controlled internal deployment phase:

1. Review and approve this branch.
2. Prepare production env changes without printing secrets.
3. Attach platform to the approved internal control network.
4. Configure Redis rate limiting.
5. Run read-only permission preflight on the VPS.
6. Deploy by pinned commit SHA and run internal localhost-only GET smoke checks.
7. Re-run the public routing readiness gate before touching Nginx.
