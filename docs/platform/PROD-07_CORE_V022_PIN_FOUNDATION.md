<!-- markdownlint-disable MD013 -->

# PROD-07 Platform Core v0.2.2 Constraints-Only Gate

## Status

`DRAFT_CONSTRAINTS_ONLY_GATE`

## Objective

PROD-07 records the approved Platform release constraint for `flowbiz-ai-core` v0.2.2 without installing the private Core repository in Platform CI.

This PR intentionally does not add a Core package dependency to `pyproject.toml`. Real installed Core pin validation is deferred until a separately authorized package registry or CI credential path exists.

## Source of Truth

- Core package: `flowbiz-ai-core`
- Core version constraint: `0.2.2`
- Core verified tag: `v0.2.2`
- Core verified commit: `1fb5fe899955968d4c190e3c085a2271e8cf455f`
- Gate type: `constraints-only`
- Private Core install in Platform CI: `DEFERRED`
- Package registry publication: `NOT_PERFORMED`
- Downstream runtime pin: `NOT_PERFORMED`
- Product contract direction remains: `Browser -> Next.js BFF -> Platform API`
- Platform remains the business persistence and enforcement owner.

## Scope

Included:

- Record the verified Core v0.2.2 release constraint for Platform.
- Assert that Platform CI does not install private Core through `pyproject.toml`.
- Assert that the PROD-07 evidence document carries the expected Core package, version and verified commit.
- Add evidence documentation for future release gates.

Excluded:

- Installing `flowbiz-ai-core` from the private Core repository in Platform CI.
- Adding secrets, credentials, GitHub App tokens or workflow bypasses.
- Publishing Core to any package registry.
- Product repository changes.
- Core repository changes.
- Business route wiring.
- Jobs, workers, agents or provider implementation.
- LLM provider setup, model selection or credentials.
- Database schema/data changes, SQLite inspection or demo-data migration.
- Deployment, package publication, tag creation or GitHub Release creation.
- Downstream runtime pinning.
- PROD-08/09/10/19 work.

## Constraint Pin

The active PROD-07 constraint is:

```text
flowbiz-ai-core==0.2.2 @ 1fb5fe899955968d4c190e3c085a2271e8cf455f
```

This is a release constraint only. It is not an installed Platform dependency and it is not a package source that Platform CI consumes.

## Non-Install CI Proof

`tests/test_core_v022_pin.py` verifies:

- `pyproject.toml` does not include `flowbiz-ai-core` as an install dependency.
- `pyproject.toml` does not include a direct reference to `natbkgift/flowbiz-ai-core`.
- This evidence document records the expected Core package, version and verified commit.
- Private Core install in Platform CI remains deferred.
- Package registry publication remains not performed.

These checks intentionally avoid importing `packages.core.*`. Platform install compatibility must be proven later after an Owner-authorized registry/access path exists.

## Security and Supply Chain Position

- No private Core repository access is required by Platform CI in this PR.
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

- Real installed Core pin requires a separately authorized package registry or CI credential path.
- PROD-08 job/worker foundation requires separate Owner authorization.
- Agent/provider wiring requires separate Owner authorization.
- Business `/v1` route implementation remains separate.
- Product BFF implementation remains separate.
- Deployment remains separate and is not authorized by this PR.
