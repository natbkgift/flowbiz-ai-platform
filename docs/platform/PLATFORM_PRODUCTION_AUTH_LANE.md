# PLATFORM_PRODUCTION_AUTH_LANE

This runbook codifies the current internal production auth lane for `flowbiz-ai-platform`.

## Scope

- host: `flowbiz-vps`
- repo path: `/opt/flowbiz-ai-platform`
- service: `flowbiz-ai-platform-prod`
- binding: `127.0.0.1:18100 -> 8100`
- auth mode: `api_key`
- auth store: SQLite at `platform_data/platform_auth.db`

This lane is intentionally internal-only. It hardens access/control without exposing the platform publicly yet.

## Current Contract

- `GET /healthz` stays unauthenticated
- `GET /v1/meta` stays unauthenticated
- platform routes that depend on `get_request_principal` require `X-API-Key`
- bootstrap admin credentials live in a root-only file on the VPS

## Bootstrap Or Rotate The Admin Key

Run on the VPS after the repo is updated:

```bash
cd /opt/flowbiz-ai-platform
python3 scripts/seed_bootstrap_admin_key.py \
  --db-path /opt/flowbiz-ai-platform/platform_data/platform_auth.db \
  --output-path /opt/flowbiz-ai-platform/platform_data/bootstrap-admin-api-key.txt
```

Expected behavior:

- first run creates `bootstrap-admin`
- later runs rotate the same key id in place
- the plaintext key is written only to `bootstrap-admin-api-key.txt`

The script uses these default scopes:

- `platform:api_keys:manage`
- `platform:chat`

## VPS Config Requirements

The deployed `.env` must include:

```env
PLATFORM_AUTH_MODE=api_key
PLATFORM_AUTH_STORE_MODE=sqlite
PLATFORM_AUTH_SQLITE_PATH=platform_data/platform_auth.db
```

The current production lane still keeps:

- `PLATFORM_LLM_PROVIDER=stub`
- `PLATFORM_WORKFLOW_RUNNER_DISPATCH_URL=` unset
- `PLATFORM_WORKFLOW_CALLBACK_SHARED_SECRET=` unset

## Restart The Container

The current VPS lane uses a direct `docker run` deploy shape:

```bash
cd /opt/flowbiz-ai-platform
docker build -t flowbiz-ai-platform:prod .
docker rm -f flowbiz-ai-platform-prod || true
docker run -d \
  --name flowbiz-ai-platform-prod \
  --restart unless-stopped \
  --env-file .env \
  -p 127.0.0.1:18100:8100 \
  -v /opt/flowbiz-ai-platform/platform_data:/app/platform_data \
  flowbiz-ai-platform:prod
```

## Smoke Checks

Anonymous-safe checks:

```bash
curl -fsS http://127.0.0.1:18100/healthz
curl -fsS http://127.0.0.1:18100/v1/meta
```

Expected:

- `/healthz` returns `200`
- `/v1/meta` returns `200`
- `/v1/meta` reports `"auth": "api_key"`

Anonymous rejection check:

```bash
curl -i http://127.0.0.1:18100/v1/platform/workflows/jobs
```

Expected:

- `401`
- body contains `Missing X-API-Key`

Authenticated management check:

```bash
ADMIN_KEY="$(cat /opt/flowbiz-ai-platform/platform_data/bootstrap-admin-api-key.txt)"
curl -fsS \
  -H "X-API-Key: ${ADMIN_KEY}" \
  http://127.0.0.1:18100/v1/platform/api-keys/audit
```

## Operational Notes

- treat `bootstrap-admin-api-key.txt` as break-glass credential material
- keep the file root-readable only
- do not paste the plaintext key into chat, docs, or ticket comments
- prefer rotating the bootstrap key after any manual handling

## FBP-004B Discovery Notes

As of `2026-03-25`, the VPS topology shows:

- `flowbiz-ai-platform-prod` is internal-only on `127.0.0.1:18100`
- `flowbiz-ai-core-api-1` still runs separately on `127.0.0.1:8000`
- public edge currently belongs to `flowbiz-client-live-tiktok` deploy containers:
  - `flowbiz-gateway`
  - `flowbiz-dashboard`
- `flowbiz-client-amp` also runs as a separate product stack on `127.0.0.1:8001` and `127.0.0.1:8002`
- no deployed `n8n` or `flowbiz-infra-n8n` container was found on the VPS during this inspection

Implication:

- do not set `PLATFORM_WORKFLOW_RUNNER_DISPATCH_URL` yet until the actual runner endpoint is identified or deployed
- the next safe move after auth codification is runner endpoint discovery and explicit runner ownership
