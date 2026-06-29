<!-- markdownlint-disable MD013 -->

# PROD-06 Tenant Membership and RBAC Foundation

## Status

`DRAFT_FOUNDATION`

## Objective

PROD-06 establishes the Platform foundation for authoritative tenant membership lookup and fail-closed RBAC decisions after PROD-05 validates Supabase identity.

The security boundary remains:

`Browser -> Next.js BFF -> Platform API`

`X-Tenant-ID` is a tenant selector only. It is never authorization proof. Platform must verify the selector against PostgreSQL `user_identities`, `tenants`, `memberships`, and `roles` before a future route handler trusts tenant scope.

## Scope

Included:

- Tenant membership resolver backed by existing PROD-04 PostgreSQL models.
- Fail-closed RBAC policy with explicit action-to-role mappings.
- Tenant-authorized principal model for future dependencies and route adapters.
- Tests for active membership resolution, tenant mismatch denial, inactive tenant/member denial, conflicting selector denial, action denial, and default-deny behavior.

Excluded:

- Product BFF authentication/session implementation.
- Route wiring or business endpoint implementation.
- New tables, migrations, or schema changes.
- SQLite inspection, mutation, migration, export, import, deletion, or tenant inference.
- Supabase production configuration or credentials.
- Core dependency pinning.
- Jobs, workers, agents, provider integrations, billing, Meta integration, deployment, tags, releases, or package publication.

## Security Properties

- Supabase identity remains identity-only until PostgreSQL membership lookup succeeds.
- Missing, conflicting, inactive, or unknown tenant membership returns a safe `403` decision.
- Unknown role values fail closed.
- Unknown action values fail closed.
- `service_identity` is explicit and does not receive implicit administrative rights.
- Tenant context is created only after an active tenant and active membership match the Supabase subject.
- No route uses this foundation until a later Owner-authorized PR wires dependencies into `/v1` handlers.

## Role Matrix

| Role | Baseline purpose | Representative allowed actions |
| --- | --- | --- |
| `owner` | Tenant owner | tenant manage, membership manage, project write/delete, generation, approvals, audit, usage |
| `admin` | Tenant administrator | project write/delete, generation, approvals, audit, usage |
| `marketer` | Marketing operator | project write, onboarding write, generation submit, job retry/cancel |
| `viewer` | Read-only viewer | project/dashboard/output read only |
| `service_identity` | Service principal | explicit read/service-safe actions only; no implicit admin |

The executable source of truth is `platform_app/tenant_rbac.py`. The policy is intentionally explicit rather than role-order derived so unknown actions do not inherit access by accident.

## Data Position

The SQLite packet classified R001-R017 as `demo` with disposal prohibited. PROD-06 does not inspect, export, import, assign tenant ownership to, delete, or mutate those records.

Tenant/RBAC tests create synthetic PostgreSQL rows only in the CI test database.

## Failure Modes

| Condition | Safe result |
| --- | --- |
| Missing tenant selector | `403 Tenant access denied` |
| Conflicting selectors | `403 Tenant access denied` |
| No matching user identity | `403 Tenant access denied` |
| No active membership | `403 Tenant access denied` |
| Inactive tenant | `403 Tenant access denied` |
| Unknown role | `403 Tenant access denied` |
| Known role but disallowed action | `403 Permission denied` |
| Unknown action | `403 Permission denied` |

## Validation Plan

Run before review or merge gate:

```powershell
ruff check .
pytest -q
pytest tests/test_tenant_rbac.py -q
alembic upgrade head
```

GitHub CI must also pass PostgreSQL migration, pytest, downgrade/upgrade rehearsal, pg_dump/pg_restore rehearsal, and app-creation smoke check.

## Remaining Gates

- Product BFF auth/session implementation remains separate.
- Platform `/v1` route wiring remains separate.
- Business project/onboarding/job APIs remain separate.
- Runtime cutover from SQLite to PostgreSQL requires a separate Owner-authorized PR.
- Core pinning, deployment, and later Product integration phases remain out of scope.
