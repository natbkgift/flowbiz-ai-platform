# flowbiz-ai-platform

Platform service layer for FlowBiz AI products. This repository implements production-facing concerns on top of `flowbiz-ai-core`, including:

- public API auth and API key enforcement
- rate limiting
- LLM provider integrations
- secret handling
- observability and alerting integration

`flowbiz-ai-core` remains the reusable foundation (contracts/runtime primitives). This repo owns platform-specific implementation and operations.

## Status

The public bootstrap routes remain available for local development. The production
runner lane uses PostgreSQL as authority and the published `flowbiz-ai-core` v0.2.3
contract package.

## Prerequisites

- Docker Desktop or Docker Engine with Compose support for the one-command path
- Python 3.11 if you want to run the app directly on the host
- The verified `flowbiz_ai_core-0.2.3-py3-none-any.whl` artifact. Its required
  SHA-256 is documented in `docs/platform/PROD-08_CORE_V023_PIN_FOUNDATION.md`.

## Quick Start

1. Copy the local-only example environment. The Compose stack does not read the
   legacy `.env` file and never needs production credentials:

```powershell
Copy-Item .env.local.example .env.local
```

2. Place the verified Core wheel at
   `.artifacts/flowbiz_ai_core-0.2.3-py3-none-any.whl` (the directory is ignored by Git).

3. Start the local stack:

```powershell
docker compose up --build
```

Compose starts a disposable PostgreSQL 16 service, applies Alembic migrations,
and binds the Platform only to `http://127.0.0.1:8100`. The local configuration
uses the stub LLM provider, disables authentication for smoke tests, and keeps
the Hermes runner disabled. PostgreSQL is available to local integration tests
only at `127.0.0.1:15432`.

## Smoke Verification

Run these in a second terminal after the stack is up:

```powershell
curl.exe http://localhost:8100/healthz
curl.exe http://localhost:8100/v1/meta
curl.exe -X POST http://localhost:8100/v1/platform/workflows/jobs ^
  -H "Content-Type: application/json" ^
  -d "{\"client_id\":\"local-smoke\",\"workflow_key\":\"hello-world\"}"
curl.exe http://localhost:8100/v1/platform/workflows/jobs
```

Expected results:

- `/healthz` returns `200` with `status=ok`
- `/v1/meta` returns `200` and shows `core_dependency.installed` if available, otherwise `not-installed`
- the workflow job create route returns `201`
- the workflow job list route returns `200`

## Stop

```powershell
docker compose down
```

Use `docker compose down -v` only when you intentionally want to remove the
disposable local PostgreSQL and Platform data volumes. This command never
targets VPS resources.

## Native Host Run

If you want to run without Docker:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
pip install .artifacts\flowbiz_ai_core-0.2.3-py3-none-any.whl
copy .env.example .env
uvicorn apps.platform_api.main:app --host 0.0.0.0 --port 8100 --reload
```

## Local Caveats

- The default local path uses `PLATFORM_LLM_PROVIDER=stub`.
- `PLATFORM_AUTH_MODE=disabled` is intended only for local bootstrap and smoke testing.
- The PostgreSQL runner lane is disabled in the default local env. Production enables
  it with `PLATFORM_RUNNER_ENABLED=true` plus file-backed transport secrets.
- The legacy SQLite workflow endpoints remain for local compatibility; they are not
  the production authority for Core v1 runner jobs.
- `.env.local` is ignored by Git. Do not paste VPS, SMTP, Gemini, GitHub, or
  production database credentials into it.
- The local Compose project is named `flowbiz-platform-local`; it does not join
  production networks and does not start a Hermes service.

## Local PostgreSQL Backup/Restore Drill

After the stack is healthy, create a custom-format backup inside the local
PostgreSQL container and restore it to an isolated local database:

```powershell
docker compose exec -T postgres pg_dump -U flowbiz_local -d flowbiz_platform_local -Fc -f /tmp/platform-local.dump
docker compose exec -T postgres createdb -U flowbiz_local flowbiz_platform_restore
docker compose exec -T postgres pg_restore -U flowbiz_local -d flowbiz_platform_restore --exit-on-error --single-transaction /tmp/platform-local.dump
docker compose exec -T postgres psql -U flowbiz_local -d flowbiz_platform_restore -Atc "SELECT version_num FROM alembic_version;"
docker compose exec -T postgres dropdb -U flowbiz_local flowbiz_platform_restore
```

These commands use only disposable local data. Production backup and restore
remain governed by the VPS release runbook.

## Local CI Baseline

This release lane is verified manually and does not require GitHub Actions:

- install the verified Core v0.2.3 wheel into an isolated environment
- run `pytest -q`
- run PostgreSQL migration upgrade/downgrade/upgrade and integration tests
- build both immutable Docker images and run the real Platform→Hermes→callback recovery drill

## Production Ops

The VPS manifest is `deploy/docker-compose.vps.yml`. It consumes only file-backed
secrets under `/opt/flowbiz/secrets/platform`, runs Alembic before startup, and binds
the public upstream to loopback port 18100. The internal production auth lane is documented in
[docs/platform/PLATFORM_PRODUCTION_AUTH_LANE.md](/d:/FlowBiz/flowbiz-ai-platform/docs/platform/PLATFORM_PRODUCTION_AUTH_LANE.md).

The current internal hardening gate, deployment checklist, secret permission
policy, public routing gate, and runner connectivity plan are documented under
`docs/platform/`.

See `docs/PLATFORM_ROADMAP.md` for #2-#4 implementation plan.
