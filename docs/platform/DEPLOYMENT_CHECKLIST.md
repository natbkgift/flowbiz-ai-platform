# Platform Deployment Checklist

This checklist keeps future platform deploys traceable by commit SHA and avoids
accidental public exposure.

## Release Record

Record these before deployment:

- Branch:
- Commit SHA:
- Reviewer:
- Deployment operator:
- Date/time:
- Target host:
- Container image tag or digest:
- Rollback commit/image:

## Pre-Deploy Checks

Run from the local repo:

```powershell
git status --short --branch
git rev-parse HEAD
python -m ruff check .
pytest -q
python -c "from apps.platform_api.main import create_app; app = create_app(); print(len(app.routes))"
```

Run read-only checks on the VPS:

```bash
cd /opt/flowbiz-ai-platform
git rev-parse HEAD
git status --short --branch
python scripts/check_platform_file_permissions.py --root /opt/flowbiz-ai-platform
```

Do not print `.env`, API keys, tokens, database contents, private keys, or
certificates.

## Runtime Configuration Checks

Confirm without printing secret values:

- `PLATFORM_ENV=production`
- `PLATFORM_AUTH_MODE=api_key`
- `PLATFORM_AUTH_STORE_MODE=sqlite` or approved equivalent
- `PLATFORM_RATE_LIMIT_MODE=redis`
- Redis URL is configured and reachable from the platform container
- `PLATFORM_LLM_PROVIDER` is either `stub` for internal-only testing or an
  approved real provider with its secret available
- FastAPI docs are disabled
- CORS origin list contains only approved origins

## Internal Smoke Checks

Only run internal/local GET checks unless a separate deploy plan explicitly
approves POST tests:

```bash
curl -fsS http://127.0.0.1:18100/healthz
curl -fsS http://127.0.0.1:18100/readyz
curl -fsS http://127.0.0.1:18100/v1/meta
```

Authenticated ops checks may be run only with an operator-held key and must not
print the key:

```bash
curl -fsS -H "X-API-Key: ${PLATFORM_OPS_API_KEY}" \
  http://127.0.0.1:18100/v1/platform/ops/observability
```

## Deployment Guardrails

- Do not reload Nginx during the internal hardening gate.
- Do not point `flowbiz.cloud/api` to the platform during the internal gate.
- Do not run `docker compose up/down` against production unless an approved
  deployment window explicitly calls for it.
- Do not run production workflow dispatch POST requests as smoke tests.
- Do not deploy Hermes as part of this platform gate.

## Post-Deploy Evidence

Attach:

- Deployed commit SHA.
- Container ID/image digest.
- Read-only permission preflight output.
- Internal smoke command exit status.
- Docs route `404` evidence.
- Redis and runner DNS evidence from inside the platform container.
