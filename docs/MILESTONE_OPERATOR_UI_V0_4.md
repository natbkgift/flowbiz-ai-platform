# FlowBiz Operator UI v0.4 Freeze

Date: 2026-05-10

Repository: `flowbiz-ai-platform`
Milestone tag: `flowbiz-platform-v0.4-operator-ui`
Branch: `feat/operator-ui-v1`
Companion core branch: `feat/operator-ui-api-v1`
Hermes baseline: `flowbiz-hermes-v0.3-runtime-stable`

## Architecture

Operator UI v0.4 adds an internal-only browser console on top of the frozen
Runtime v0.3 stack.

- Platform serves the console shell and static assets.
- Platform proxies internal operator API calls to core.
- Core remains the source of truth for projects, tasks, task events, audit
  records, approvals, and worker summaries.
- Hermes is unchanged and remains the v0.3 read-only worker.

The UI is intentionally a visibility and approval surface. It is not a write,
deploy, restart, shell, Docker, SSH, messaging, or PR-mode control plane.

## Platform Proxy Routes

Routes are mounted only when `PLATFORM_OPERATOR_UI_ENABLED=true`:

- `/internal/operator/`
- `/internal/operator/assets/style.css`
- `/internal/operator/assets/app.js`
- `/internal/operator/api/dashboard/summary`
- `/internal/operator/api/projects`
- `/internal/operator/api/tasks`
- `/internal/operator/api/tasks/{task_id}`
- `/internal/operator/api/tasks/{task_id}/approve`
- `/internal/operator/api/tasks/{task_id}/reject`
- `/internal/operator/api/events`
- `/internal/operator/api/audit`
- `/internal/operator/api/approvals`
- `/internal/operator/api/workers/summary`
- `/internal/operator/api/health`
- `/internal/operator/api/policy`

All routes remain under `/internal/operator/*`; no public route is introduced.

## Core Dashboard Endpoints

Platform proxies to the Batch 4 core operator endpoints under `/v1/operator/*`,
including:

- `/v1/operator/dashboard/summary`
- `/v1/operator/events`
- `/v1/operator/audit`
- `/v1/operator/approvals`
- `/v1/operator/workers/summary`
- Existing project, task, approval, and rejection endpoints.

## Auth And Token Gate

- The router is not registered unless `PLATFORM_OPERATOR_UI_ENABLED=true`.
- Every operator UI route requires the configured internal operator token.
- Missing or invalid tokens return unauthorized responses.
- The token is not logged, rendered, or forwarded to the browser.

## Redaction Policy

Every proxied payload is passed through server-side redaction before it can
reach the browser.

Redaction masks:

- Keys containing token, secret, password, api key, authorization, private key,
  credential, or client secret indicators.
- Denied task target paths such as `.env`, `.env.*`, `*.pem`, `*.key`,
  `id_rsa`, `id_ed25519`, `.secrets`, and `letsencrypt`.
- Inline bearer tokens and long hex-like secret values in text fields.

## Public Surface Verification

The public surface remains unchanged:

- `/healthz`, `/readyz`, and `/v1/meta` remain the allowed public metadata
  surface.
- `/v1/operator/*` is not publicly exposed by Platform.
- `/internal/operator/*` is not added to `api.flowbiz.cloud` or
  `flowbiz.cloud/api`.
- `/internal/worker/*`, `/docs`, and `/openapi.json` remain unavailable on
  the public surface.

## Blocked Capabilities

Operator UI v0.4 does not enable:

- Write mode.
- PR mode.
- Deploy, restart, package install, shell, terminal, Docker socket, SSH, cron,
  messaging, or secret rotation.
- Nginx changes.
- Public allowlist changes.
- Database schema changes.
- Hermes changes.

Approvals remain visible and auditable, but Hermes v0.3 still only claims
read-only tasks.

## Rollback Plan

Preferred rollback:

1. Set `PLATFORM_OPERATOR_UI_ENABLED=false`.
2. Confirm `/internal/operator/*` returns not found.
3. Keep core and Hermes running at their existing stable runtime baselines.

Commit or release rollback:

- Platform v0.4 tag: `flowbiz-platform-v0.4-operator-ui`
- Core v0.4 tag: `flowbiz-core-v0.4-operator-ui`
- Runtime v0.3 fallback tags:
  `flowbiz-platform-v0.3-runtime-stable`,
  `flowbiz-core-v0.3-runtime-stable`,
  `flowbiz-hermes-v0.3-runtime-stable`

Do not roll back by rewriting history.

## Next Phase Constraints

Batch 5 may proceed as design-only work. Implementation must not enable write
execution, PR mode, public operator routes, Nginx changes, or Hermes write
capabilities without a separate approval gate.
