<!-- markdownlint-disable MD013 -->

# PROD-04 — PostgreSQL Foundation

## Status

`DRAFT_PR_FOR_REVIEW`

## Objective

PROD-04 establishes PostgreSQL persistence foundations for the FlowBiz Facebook Ads Platform API contract. It adds models, Alembic migrations, tenant-scoped repository helpers, read-only SQLite inventory support, synthetic tests, and PostgreSQL CI evidence.

This PR does not cut runtime over from existing SQLite stores and does not implement auth, RBAC, API routes, jobs, agents, providers, Core pinning, deployment, or later PROD phases.

## Scope

Included:

- SQLAlchemy 2.x / Alembic / psycopg dependency foundation.
- `PLATFORM_DATABASE_URL` setting without default production value.
- PostgreSQL models for Blueprint entities.
- Initial Alembic migration with `upgrade` and `downgrade`.
- Tenant-scoped repository helpers for future route wiring.
- Read-only SQLite inventory exporter code tested only with synthetic SQLite.
- GitHub Actions PostgreSQL 17 service, migration checks, tests, downgrade/upgrade rehearsal, and `pg_dump`/`pg_restore` rehearsal.

Excluded:

- Runtime cutover from SQLite to PostgreSQL.
- Real SQLite export, import, migration, deletion, copying, or tenant assignment.
- Supabase JWT validation, tenant/RBAC policy implementation, jobs/workers, agents, LLM providers, billing, Meta integration, Product changes, Core pinning, deployment, tags, or releases.

## Data Model Inventory

| Area | Tables |
| --- | --- |
| Identity | `user_identities`, `tenants`, `roles`, `memberships` |
| Product | `projects`, `business_profiles`, `product_services`, `campaign_goals` |
| AI outputs | `strategies`, `creative_briefs`, `campaign_plans` |
| Execution | `jobs`, `job_attempts`, `usage_records` |
| Governance | `approval_requests`, `approval_decisions`, `audit_events` |

Tenant-owned tables carry non-null `tenant_id` and tenant-leading indexes. Generated output tables have tenant/project/version uniqueness. Jobs have tenant-scoped idempotency uniqueness. Job states are constrained to `queued`, `running`, `succeeded`, `failed`, `dead_letter`, and `cancelled`.

## SQLite Demo Data Position

The SQLite ownership packet classifies R001-R017 as `demo` with disposal prohibited. PROD-04 does not inspect, export, import, assign tenants to, delete, or mutate those records.

The read-only exporter is intentionally limited to non-sensitive inventory and hash-stability checks. Tests use synthetic temporary SQLite files only.

## Rollback and Fallback

Rollback before merge is branch deletion. Rollback after merge is a revert of this PR because the runtime remains on existing SQLite stores.

If PostgreSQL migration validation fails, no production traffic is affected because routes are not wired to PostgreSQL in this PR.

## Validation Plan

Required PR-head evidence:

- `ruff check .`
- `pytest -q`
- `alembic upgrade head`
- `alembic downgrade base && alembic upgrade head`
- PostgreSQL 17 health check
- `pg_dump` and `pg_restore` rehearsal against the CI database
- Existing FastAPI app creation smoke check
- Secret/forbidden-scope review

## Remaining Gates

- PROD-05/06 must implement Supabase auth, tenant membership and RBAC separately.
- Runtime cutover from SQLite to PostgreSQL requires a separate Owner-authorized PR.
- Real SQLite demo-data export/import requires a separate Owner-authorized PR with private evidence handling.
- Core pinning, deployment, and later Product integration phases remain out of scope.
