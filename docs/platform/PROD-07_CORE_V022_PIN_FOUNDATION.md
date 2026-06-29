<!-- markdownlint-disable MD013 -->

# PROD-07 Platform Core v0.2.2 Exact Pin Foundation

## Status

`DRAFT_PIN_FOUNDATION`

## Objective

PROD-07 establishes the Platform dependency foundation for importing the verified `flowbiz-ai-core` library used by later job, agent, provider and runtime integration PRs.

This PR pins Core to the verified release target only. It does not wire jobs, agents, providers, business routes, Product BFF integration or runtime execution paths.

## Source of Truth

- Core verified tag: `v0.2.2`
- Core tag target: `1fb5fe899955968d4c190e3c085a2271e8cf455f`
- Platform dependency pin: exact Git commit reference in `pyproject.toml`
- Product contract direction remains: `Browser -> Next.js BFF -> Platform API`
- Platform remains the business persistence and enforcement owner.

## Scope

Included:

- Add `flowbiz-ai-core` as a Platform dependency pinned to the exact verified Core commit.
- Add smoke tests proving the installed Core distribution reports version `0.2.2`.
- Add smoke tests proving Platform can import representative Core runtime and contract primitives.
- Add evidence documentation for future release gates.

Excluded:

- Product repository changes.
- Core repository changes.
- Business route wiring.
- Jobs, workers, agents or provider implementation.
- LLM provider setup, model selection or credentials.
- Database schema/data changes, SQLite inspection or demo-data migration.
- Deployment, package publication, tag creation or GitHub Release creation.
- PROD-08/09/10/19 work.

## Dependency Pin

The active dependency is pinned as a PEP 508 direct reference:

```toml
"flowbiz-ai-core @ git+https://github.com/natbkgift/flowbiz-ai-core.git@1fb5fe899955968d4c190e3c085a2271e8cf455f"
```

This intentionally uses the verified commit target rather than a mutable branch name. The `v0.2.2` tag has already been verified to point to the same commit in the Core release lane.

## Compatibility Smoke

`tests/test_core_v022_pin.py` verifies:

- `importlib.metadata.version("flowbiz-ai-core") == "0.2.2"`.
- `packages.core.retry.RetryPolicy` imports and can be used with `run_with_retry`.
- `packages.core.contracts.devx.SDKGeneratorTarget` imports and carries the expected `0.2.2` default package version.

These imports are intentionally narrow. They prove the dependency is installable and compatible without starting agents, jobs, providers or runtime business execution.

## Security and Supply Chain Position

- The dependency is exact-commit pinned to reduce mutable supply-chain risk.
- No secrets, production credentials or model names are introduced.
- No Core HTTP API is introduced into the business execution path.
- No runtime permission, tenant or RBAC behavior changes are introduced.
- Unknown downstream job/agent behavior remains blocked until later Owner-authorized PRs.

## Validation Plan

Run before review or merge gate:

```powershell
ruff check .
pytest -q
pytest tests/test_core_v022_pin.py -q
alembic upgrade head
```

GitHub CI must also pass PostgreSQL migration, pytest, downgrade/upgrade rehearsal, pg_dump/pg_restore rehearsal and app-creation smoke check on the PR head.

## Remaining Gates

- PROD-08 job/worker foundation requires separate Owner authorization.
- Agent/provider wiring requires separate Owner authorization.
- Business `/v1` route implementation remains separate.
- Product BFF implementation remains separate.
- Deployment remains separate and is not authorized by this PR.
