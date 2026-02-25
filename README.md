# flowbiz-ai-platform

Platform service layer for FlowBiz AI products. This repository implements production-facing concerns on top of `flowbiz-ai-core`, including:

- public API auth and API key enforcement
- rate limiting
- LLM provider integrations
- secret handling
- observability and alerting integration

`flowbiz-ai-core` remains the reusable foundation (contracts/runtime primitives). This repo owns platform-specific implementation and operations.

## Status

Initial skeleton repo (platform bootstrap). Core dependency is pinned and platform modules are scaffolded for staged implementation.

## Dependency Pinning

This repo pins `flowbiz-ai-core==0.2.0` in `pyproject.toml`.

For local development on the same machine (before publishing wheels), you can temporarily install from a local path:

```powershell
pip install -e ..\flowbiz-ai-core
pip install -e .[dev]
```

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
copy .env.example .env
uvicorn apps.platform_api.main:app --reload --host 0.0.0.0 --port 8100
```

## Endpoints (Skeleton)

- `GET /healthz`
- `GET /v1/meta`
- `POST /v1/platform/chat` (stub, guarded)

See `docs/PLATFORM_ROADMAP.md` for #2-#4 implementation plan.

