# api.flowbiz.cloud Metadata-only Canary Enablement Report

Run date: 2026-05-10

## 1. Summary

`api.flowbiz.cloud` metadata-only canary is enabled.

Only these public routes are exposed:

- `GET /healthz`
- `GET /readyz`
- `GET /v1/meta`

All tested non-allowlisted paths and methods are blocked at Nginx. Functional
API exposure remains blocked.

`flowbiz.cloud/api` was not modified and still points to the legacy upstream
`127.0.0.1:8000`.

## 2. DNS

| Check | Result |
| --- | --- |
| `api.flowbiz.cloud` A record | `72.62.69.117` |
| VPS public IPv4 | `72.62.69.117` |
| DNS propagation gate | Pass |

No DNS changes were made from this environment during the resumed phase; the
record already resolved when enablement resumed.

## 3. TLS

A dedicated certificate was issued for `api.flowbiz.cloud` only.

| Check | Result |
| --- | --- |
| Certificate directory | present |
| Subject | `CN = api.flowbiz.cloud` |
| Issuer | Let's Encrypt |
| Expiry | 2026-08-08 08:17:42 UTC |

The existing `flowbiz.cloud` certificate was not modified. Certificate private
key contents were not read or printed.

## 4. Nginx

Remote enabled config:

```text
/etc/nginx/conf.d/api.flowbiz.cloud.metadata-canary.conf
```

Local reviewed config artifacts:

```text
docs/platform/nginx/api.flowbiz.cloud.acme-bootstrap.conf
docs/platform/nginx/api.flowbiz.cloud.metadata-canary.conf
```

Enablement sequence:

1. Installed a temporary ACME bootstrap config at the approved remote path.
2. Ran `nginx -t`; syntax passed.
3. Reloaded Nginx for HTTP-01 certificate issuance.
4. Issued a dedicated `api.flowbiz.cloud` certificate with Certbot webroot.
5. Replaced the bootstrap config with the full metadata-only canary config.
6. Ran `nginx -t`; syntax passed.
7. Reloaded Nginx after syntax passed.

The final config proxies only:

- `GET /healthz`
- `GET /readyz`
- `GET /v1/meta`

The final config returns `404` for docs, OpenAPI, `/v1/platform/*`, and all
other unmatched paths. Non-GET methods return `405`.

## 5. Validation Matrix

Public HTTPS validation:

| Request | Expected | Actual | Status |
| --- | --- | --- | --- |
| `GET https://api.flowbiz.cloud/healthz` | `200` | `200` | Pass |
| `GET https://api.flowbiz.cloud/readyz` | `200` | `200` | Pass |
| `GET https://api.flowbiz.cloud/v1/meta` | `200` | `200` | Pass |
| `GET https://api.flowbiz.cloud/docs` | `404` | `404` | Pass |
| `GET https://api.flowbiz.cloud/openapi.json` | `404` | `404` | Pass |
| `GET https://api.flowbiz.cloud/v1/platform/ops/metrics` | `404` | `404` | Pass |
| `POST https://api.flowbiz.cloud/v1/platform/chat` | `404` or `405` | `405` | Pass |

Additional blocklist checks:

| Request | Actual | Status |
| --- | --- | --- |
| `HEAD /healthz` | `405` | Pass |
| `POST /healthz` | `405` | Pass |
| `PUT /v1/meta` | `405` | Pass |
| `DELETE /readyz` | `405` | Pass |
| `GET /` | `404` | Pass |
| `GET /v1/meta/extra` | `404` | Pass |
| `GET /v1/platform/workflows/jobs` | `404` | Pass |
| `POST /v1/platform/ops/llm/smoke` | `405` | Pass |

Metadata safety spot-check:

| Check | Result |
| --- | --- |
| `/v1/meta` exposes `env` | No |
| `/v1/meta` exposes detailed `modes` | No |
| `/v1/meta` exposes `core_dependency` status | Yes |

## 6. Invariants Confirmed

| Check | Result |
| --- | --- |
| Platform container | `flowbiz-ai-platform-prod` |
| Platform image | `flowbiz-ai-platform:9595b66e6100` |
| Docker state | running |
| Docker health | healthy |
| Platform binding | `127.0.0.1:18100 -> 8100` only |
| Current `nginx -t` | Pass |
| `flowbiz.cloud.conf` hash | unchanged from pre-enable check |
| `flowbiz.cloud/api` upstream | `127.0.0.1:8000` |
| Nginx references to `18100` | only in `api.flowbiz.cloud.metadata-canary.conf` |
| Public protected route access | blocked at Nginx |
| Functional API exposure | blocked |

## 7. Actions Taken

- Verified DNS resolution for `api.flowbiz.cloud`.
- Verified platform health and localhost-only binding before enablement.
- Verified `flowbiz.cloud/api` before enablement.
- Installed the ACME bootstrap config at the approved canary config path.
- Ran `nginx -t` before reloading.
- Reloaded Nginx only after syntax passed.
- Issued a dedicated TLS certificate for `api.flowbiz.cloud`.
- Installed the final metadata-only canary config.
- Ran `nginx -t` before final reload.
- Reloaded Nginx only after syntax passed.
- Validated the public HTTPS allowlist and blocklist.
- Confirmed `flowbiz.cloud/api` remains unchanged.

## 8. Actions Not Taken

- Did not touch `flowbiz.cloud/api`.
- Did not deploy Hermes.
- Did not expose LLM endpoints.
- Did not expose workflow routes.
- Did not expose `/v1/platform/*`.
- Did not expose POST, PUT, PATCH, DELETE, or HEAD methods.
- Did not modify the existing `flowbiz.cloud` certificate.
- Did not print secrets, API keys, tokens, `.env` values, certificate private
  keys, private keys, or database contents.
- Did not restart or rollback the platform container.

## 9. Rollback Plan

Rollback scope is only `api.flowbiz.cloud`.

Commands:

```bash
mv /etc/nginx/conf.d/api.flowbiz.cloud.metadata-canary.conf \
  /etc/nginx/conf.d/api.flowbiz.cloud.metadata-canary.conf.disabled
nginx -t
systemctl reload nginx
grep -nE "location[[:space:]]+/api/|proxy_pass[[:space:]]+http://127\\.0\\.0\\.1:8000" \
  /etc/nginx/conf.d/flowbiz.cloud.conf
docker inspect flowbiz-ai-platform-prod \
  --format '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}|{{json .NetworkSettings.Ports}}'
```

Reload Nginx only after `nginx -t` passes. Do not rollback the platform
container unless internal platform health fails.

## 10. Final Decision

| Question | Decision |
| --- | --- |
| Is metadata-only canary enabled? | Yes |
| Was DNS available? | Yes |
| Was TLS issued? | Yes, dedicated to `api.flowbiz.cloud` |
| Was Nginx enabled? | Yes |
| Did validation pass? | Yes |
| Is functional API exposure still blocked? | Yes |
| Is `flowbiz.cloud/api` still untouched? | Yes |

Final status: `api.flowbiz.cloud` is enabled as a metadata-only canary. All
functional public API routes remain blocked.
