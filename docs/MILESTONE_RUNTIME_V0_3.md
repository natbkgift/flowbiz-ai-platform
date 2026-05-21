# FlowBiz Runtime v0.3 Freeze

Date: 2026-05-10

Repository: `flowbiz-ai-platform`
Milestone tag: `flowbiz-platform-v0.3-runtime-stable`

## Architecture Overview

The v0.3 runtime milestone freezes the stable internal runtime stack before
Batch 4, the AI Operator UI phase.

- `flowbiz-ai-platform` owns platform-facing API behavior, authentication,
  rate limiting, provider integration, observability, and the platform-to-core
  bridge.
- `flowbiz-ai-core` owns durable control-plane contracts, task policy,
  internal worker task APIs, and shared runtime primitives.
- `flowbiz-hermes-agent` owns the internal-only, read-only Hermes worker
  wrapper that claims approved tasks from core.

Platform remains the outer runtime integration layer. Core and Hermes remain
internal dependencies.

## Active Internal Services

- Platform FastAPI service.
- Core FastAPI control-plane service.
- Core durable persistence layer.
- Internal Hermes read-only worker, when enabled by the core worker token and
  internal network.

## Docker Networks

- Local platform compose remains unchanged.
- Core/Hermes worker communication uses an internal Docker network such as
  `flowbiz-internal`.
- VPS validation used the internal `flowbiz-platform-core-control` network.
- No host port or public route is added for Hermes.

## Security Boundaries

- Platform public routes are unchanged.
- Core worker routes remain internal-only.
- Hermes has no public ingress and no published host port.
- Worker authentication uses the existing internal worker-token boundary.
- Secrets, environment files, SSH material, private keys, certificates, and
  ACME material are excluded from this freeze.

## Blocked Capabilities

The frozen runtime does not add or enable:

- Public Hermes routes.
- Nginx changes.
- `api.flowbiz.cloud` changes.
- `flowbiz.cloud/api` changes.
- Client repository changes.
- DB schema changes.
- Secret rotation.
- Deploy, restart, shell, SSH, Docker socket, cron, messaging, or write
  capabilities for Hermes.

## Current Public Surface

The public surface is unchanged from the pre-freeze platform runtime. This
freeze does not expose Batch 4 UI routes and does not publish Hermes or core
worker endpoints.

## Hermes Upstream Pin

Hermes upstream repository: `https://github.com/NousResearch/hermes-agent`

Pinned upstream SHA:
`ce374bc1baf3138d59a7761686d91b042015db59`

## Runtime Modes

The frozen Hermes integration accepts only read-only runtime modes:

- `repo_inventory`
- `docs_summary`
- `dependency_summary`
- `architecture_report`

Unknown modes, non-read-only actions, denied paths, writable mounts, shell
execution, Docker access, SSH access, and messaging actions fail closed.

## Known Limitations

- AI Operator UI is not part of v0.3.
- Hermes is read-only and deterministic-only when public egress is unavailable.
- Public routing remains intentionally unchanged.
- Any future upstream Hermes SHA bump requires re-audit.

## Rollback Notes

Rollback should use the milestone tag
`flowbiz-platform-v0.3-runtime-stable` after it is pushed. If tag rollback is
not available, use the latest pushed freeze commit recorded in the release
gate report.

Do not roll back by rewriting history. Use normal revert or deployment pinning.

## Next Planned Phase

Batch 4: AI Operator UI, built on top of this frozen runtime milestone without
changing the internal runtime security boundary by default.
