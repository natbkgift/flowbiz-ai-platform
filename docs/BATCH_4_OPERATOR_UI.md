# Batch 4 — FlowBiz AI Operator Console (UI v1)

Date: 2026-05-10

Branch: `feat/operator-ui-v1`
Companion core branch: `feat/operator-ui-api-v1`

## Purpose

Internal-only console for visibility, auditability, task review, worker
status, and approval workflow on top of the frozen Runtime v0.3 stack.

This is **not** an AI command center. It does not enable write, deploy,
restart, shell, container, SSH, cron, messaging, or PR mode.

## Mounted at

- `/internal/operator/` — console shell (HTML)
- `/internal/operator/assets/style.css`, `app.js` — static console assets
- `/internal/operator/api/dashboard/summary`
- `/internal/operator/api/projects`
- `/internal/operator/api/tasks` (with optional `status`, `project_id`)
- `/internal/operator/api/tasks/{task_id}`
- `/internal/operator/api/tasks/{task_id}/approve`
- `/internal/operator/api/tasks/{task_id}/reject`
- `/internal/operator/api/events`
- `/internal/operator/api/audit`
- `/internal/operator/api/approvals`
- `/internal/operator/api/workers/summary`
- `/internal/operator/api/health`
- `/internal/operator/api/policy`

All routes are mounted only when `PLATFORM_OPERATOR_UI_ENABLED=true` and
require the operator bearer token from `PLATFORM_OPERATOR_UI_TOKEN`. The path
prefix `/internal/*` is excluded from the public allowlist on
`api.flowbiz.cloud` and is not served via `flowbiz.cloud/api`.

## Read-only safety

The console is a thin proxy onto the existing core control-plane operator
endpoints. Every payload returned to the browser passes through
`platform_app.operator_redaction.redact_payload`, which masks:

- keys whose names contain `password`, `secret`, `token`, `api_key`,
  `authorization`, `private_key`, `credential`, `client_secret`
- task `target_paths` matching the secret-path patterns enforced by core
  (`.env`, `*.pem`, `*.key`, `id_rsa`, `id_ed25519`, `.secrets`,
  `letsencrypt`)
- inline bearer tokens and 32+ character hex strings inside any text field

The UI explicitly does not render deploy, restart, terminal, docker, SSH,
write-file, secret-rotation, or PR controls. The capability matrix is
served from `/internal/operator/api/policy` and is consumed by the UI for
guard-rails.

## Approvals are advisory under v0.3

Approving a write/deploy/restart task changes its status in core
(`requires_approval` → `approved`). The current Hermes worker only claims
`read_only` actions, so approval does not cause execution. The UI surfaces
this as a banner on the Approvals tab and the task-detail approval card.

## Rollback

Rollback to Runtime v0.3 is unaffected. Rollback options:

1. Set `PLATFORM_OPERATOR_UI_ENABLED=false` — the operator router is not
   registered and `/internal/operator/*` returns 404.
2. Roll back to the milestone tags: `flowbiz-platform-v0.3-runtime-stable`
   and `flowbiz-core-v0.3-runtime-stable`. Hermes is unchanged
   (`flowbiz-hermes-v0.3-runtime-stable`).
3. Revert the merge commits for `feat/operator-ui-v1` and
   `feat/operator-ui-api-v1` if Batch 4 is shipped via merge.

## Public surface verification (production smoke)

| Path | Expected | Actual |
|---|---|---|
| `/healthz` | 200 | 200 |
| `/readyz` | 200 | 200 |
| `/v1/meta` | 200 | 200 |
| `/v1/operator/tasks` | 404 | 404 |
| `/internal/worker/tasks/claim` | 404 | 404 |
| `/docs` | 404 | 404 |
| `/openapi.json` | 404 | 404 |
| `/internal/operator/` (no token) | 401 | 401 |
| `/internal/operator/` (with token) | 200 | 200 |

## Out of scope (Batch 5 candidate)

- Write/deploy/restart execution under operator approval gating.
- Outbound notifications.
- Multi-operator approval quorum.
- Full PR-mode (read-write Hermes).
