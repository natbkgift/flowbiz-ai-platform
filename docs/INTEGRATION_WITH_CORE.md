# Integrating with flowbiz-ai-core

## Pinning Policy

- Pin exact version in production: `flowbiz-ai-core==0.2.0`
- Upgrade intentionally after reviewing core release notes and smoke tests

## Recommended Upgrade Flow

1. Bump pinned version in `pyproject.toml`
2. Run platform tests
3. Run local smoke against platform API
4. Deploy candidate to staging/production by commit SHA
5. Run post-deploy smoke and compare key endpoints

## What to Import from Core

Use core for reusable contracts and runtime primitives. Keep platform-specific code in this repo.

Examples:
- request/response schemas
- runtime orchestration primitives
- shared error contracts
- observability schema contracts

## What NOT to Push Back into Core

- platform auth implementation
- billing and quota enforcement
- provider SDK integrations
- secrets manager integrations
- tenant routing and platform deployment logic

