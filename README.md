# flowbiz-ai-platform

Platform service layer for FlowBiz AI products. This repository implements production-facing concerns on top of `flowbiz-ai-core`, including:

- public API auth and API key enforcement
- rate limiting
- LLM provider integrations
- secret handling
- observability and alerting integration

`flowbiz-ai-core` remains the reusable foundation (contracts/runtime primitives). This repo owns platform-specific implementation and operations.

## Status

Platform bootstrap with a local self-run baseline. The default local path uses the stub LLM provider and does not require a sibling repo or extra services.

## Prerequisites

- Docker Desktop or Docker Engine with Compose support for the one-command path
- Python 3.11 if you want to run the app directly on the host

## Quick Start

1. Copy the example environment:

```powershell
copy .env.example .env
```

2. Start the local stack:

```powershell
docker compose up --build
```

The platform listens on `http://localhost:8100`.

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

## Native Host Run

If you want to run without Docker:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
copy .env.example .env
uvicorn apps.platform_api.main:app --host 0.0.0.0 --port 8100 --reload
```

## Local Caveats

- The default local path uses `PLATFORM_LLM_PROVIDER=stub`.
- `PLATFORM_AUTH_MODE=disabled` is intended only for local bootstrap and smoke testing.
- Dispatch and callback routes are present, but the default local env leaves runner dispatch disabled until you explicitly set `PLATFORM_WORKFLOW_RUNNER_DISPATCH_URL` and `PLATFORM_WORKFLOW_CALLBACK_SHARED_SECRET`.
- If you are developing cross-repo integrations, you can still install `flowbiz-ai-core` manually from a local path, but it is not required for local platform boot.

## CI Baseline

GitHub Actions runs the repo-local regression gate on pushes to `main` and on pull requests:

- `ruff check .`
- `pytest -q`
- a smoke command that imports `apps.platform_api.main`, creates the FastAPI app, and verifies workflow routes are registered

See `docs/PLATFORM_ROADMAP.md` for #2-#4 implementation plan.
