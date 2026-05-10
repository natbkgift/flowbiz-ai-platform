# FlowBiz AI Platform Controlled Internal Deployment Report

## 1. Summary

Controlled internal deployment completed for `flowbiz-ai-platform` on the VPS.
The deployment stayed internal-only and preserved the localhost binding
`127.0.0.1:18100 -> 8100`.

No Nginx files were modified or reloaded. `flowbiz.cloud/api` still points to
`127.0.0.1:8000`. No `api.flowbiz.cloud` route exists. No production POST
workflow requests were run.

## 2. Target Commit SHA

- Branch: `feat/platform-internal-hardening-gate`
- Target commit SHA: `9595b66e61003c17a702f5d48c0233b85f95b8cc`
- Deployed image tag: `flowbiz-ai-platform:9595b66e6100`
- Container label: `flowbiz.commit=9595b66e61003c17a702f5d48c0233b85f95b8cc`

## 3. Pre-deploy State

- Local branch was committed and pushed to
  `origin/feat/platform-internal-hardening-gate`.
- Local validation passed after commit:
  - `python -m ruff check .`
  - `pytest -q`: `80 passed, 1 skipped`
- Previous VPS deployed SHA:
  `47288ca36bd734717b09717ee5de5c3a4d32d534`
- Previous image ID:
  `sha256:901b02b6383654aefd50a2213fcbf0d8158b8a71d0f7db0eb9db9f7050b57a5f`
- Previous container:
  - name: `flowbiz-ai-platform-prod`
  - image: `flowbiz-ai-platform:prod`
  - port: `127.0.0.1:18100->8100/tcp`
  - restart policy: `unless-stopped`
  - volume: `/opt/flowbiz-ai-platform/platform_data:/app/platform_data`
- Nginx pre-check:
  - `/api/` on `flowbiz.cloud` still proxies to `127.0.0.1:8000`
  - no public route pointed to the platform

## 4. Runtime Changes Made

- Tagged the previous image for rollback:
  `flowbiz-ai-platform:rollback-20260509184818`
- Moved `.env.backup.*` out of `/opt/flowbiz-ai-platform` into a root-only
  backup directory.
- Updated production env keys without printing values.
- Fetched and checked out the pinned commit on the VPS.
- Built `flowbiz-ai-platform:9595b66e6100` from the pinned commit.
- Recreated only `flowbiz-ai-platform-prod`.
- Kept port binding localhost-only.
- Attached the platform container only to `flowbiz-platform-internal`.

## 5. Env / Secret Handling Summary

No `.env` values, API keys, provider secrets, database contents, private keys, or
certificates were printed.

Env key handling:

- Confirmed required env key names exist.
- Set or verified production mode.
- Set or verified API-key auth mode.
- Set rate limiting to Redis mode.
- Set Redis URL for the dedicated internal control network without credentials.
- Set docs disabled explicitly.
- Set CORS to no wildcard origin.
- Kept LLM provider as `stub` for internal-only deployment.

The LLM provider remains a public-routing blocker.

## 6. File Permission Remediation

Read-only preflight initially found:

- `.env`: too permissive
- `.env.backup.`: present in active path
- SQLite DB files: too permissive
- bootstrap admin key file: already restricted

Actions:

- moved `.env.backup.` out of active path
- set `.env` to `600`
- set SQLite DB files to `600`
- kept bootstrap admin key file restricted

Post-remediation preflight:

- `.env`: OK, `0o600`
- `platform_auth.db`: OK, `0o600`
- `workflow_events.db`: OK, `0o600`

## 7. Network / Redis / Runner Connectivity

Network used:

- `flowbiz-platform-internal`

Attached services:

- `flowbiz-ai-platform-prod`
- `flowbiz-redis`
- runner API container with the configured runner hostname as a network alias

The platform was not joined to `flowbiz-infra-n8n_default`.

Checks:

- Redis DNS from platform container: OK
- Redis ping from platform container: OK
- Runner DNS from platform container: OK

## 8. Image / Container Details

- Container ID:
  `fc4245be9010728815169f1a2a46efca522542c9311ff96a2d6724da5e30e53a`
- Image:
  `flowbiz-ai-platform:9595b66e6100`
- Restart policy:
  `unless-stopped`
- Docker health:
  `healthy`
- Port:
  `8100/tcp -> 127.0.0.1:18100`
- Network:
  `flowbiz-platform-internal`

## 9. Internal Smoke Results

GET-only localhost checks:

- `GET /healthz`: `200`
- `GET /readyz`: `200`
- `GET /v1/meta`: `200`
- `GET /docs`: `404`
- `GET /openapi.json`: `404`
- `GET /v1/platform/ops/observability` without auth: `401`
- `GET /v1/platform/ops/metrics` without auth: `401`

Additional checks:

- request ID header present: OK
- correlation ID header present: OK
- production `/v1/meta` omits `env`: OK
- production `/v1/meta` omits detailed `modes`: OK
- `core_dependency` exposes only `installed`: OK
- rate limit mode is not `noop`: OK
- docs disabled in runtime config: OK
- CORS is not wildcard: OK
- Docker healthcheck: healthy

Optional protected internal smoke:

- Not run. No test-safe API key was used or printed.

## 10. Security Checks

- Platform remains internal-only on `127.0.0.1:18100`.
- No public `0.0.0.0` host port binding.
- Nginx was not edited.
- Nginx was not reloaded.
- `flowbiz.cloud/api` was not pointed to the platform.
- `api.flowbiz.cloud` was not created.
- Protected ops endpoints are not accessible without auth.
- Docs and OpenAPI are disabled in production.
- No secret values were printed.

## 11. Stop Conditions Encountered

No deployment stop condition remained open.

Non-blocking command issues resolved during execution:

- A local PowerShell quoting issue occurred before rollback tagging succeeded;
  no runtime change was made by the failed command.
- A remote `git status --short --branch` option parsing issue occurred after
  checkout; pinned checkout had already succeeded and was verified with
  `git status -sb`.
- One smoke script had an extra heredoc tail after all GET checks passed; the
  smoke checks were rerun cleanly and passed.
- A Docker inspect template command had quoting issues; container details were
  rerun cleanly and verified.

## 12. Rollback Plan

Rollback image:

- `flowbiz-ai-platform:rollback-20260509184818`

Rollback commands:

```bash
docker rm -f flowbiz-ai-platform-prod
docker run -d \
  --name flowbiz-ai-platform-prod \
  --env-file /opt/flowbiz-ai-platform/.env \
  --restart unless-stopped \
  --network bridge \
  -p 127.0.0.1:18100:8100 \
  -v /opt/flowbiz-ai-platform/platform_data:/app/platform_data \
  flowbiz-ai-platform:rollback-20260509184818
```

Rollback notes:

- Do not touch Nginx for rollback.
- If rolling back config as well, restore the root-only `.env` backup created
  before deployment without printing contents.
- Re-run GET-only localhost smoke checks after rollback.

## 13. Remaining Blockers

- Public routing readiness gate has not passed.
- LLM provider remains `stub`; real provider readiness is still blocked.
- `core_dependency.installed=false` remains visible in safe metadata.
- Authenticated protected internal smoke was not run because no test-safe API key
  was available without exposing it.
- `flowbiz.cloud/api` still points to the legacy `127.0.0.1:8000` upstream.

## 14. Public Routing Decision

- Safe to expose publicly now: No.
- Safe to point `flowbiz.cloud/api` to the platform now: No.
- Safe to create `api.flowbiz.cloud` canary now: No.

Reason:

- The internal deployment succeeded, but public routing still requires the public
  readiness gate, real LLM/provider decision, final auth/ops smoke with a
  test-safe key, and an explicit Nginx/canary plan.

## 15. Next Recommended Phase

Run `FlowBiz AI Platform Public Routing Readiness Gate`:

1. Provision a test-safe ops API key path that can be used without exposing the
   key.
2. Decide whether public canary requires real LLM provider or remains blocked.
3. Validate authenticated ops metrics and LLM smoke internally.
4. Decide the public route shape separately: `flowbiz.cloud/api` vs
   `api.flowbiz.cloud`.
5. Prepare Nginx change as a reviewed, reversible canary plan.
