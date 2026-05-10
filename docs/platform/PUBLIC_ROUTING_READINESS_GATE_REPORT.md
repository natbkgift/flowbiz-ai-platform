# FlowBiz AI Platform Public Routing Readiness Gate Report

## 1. Summary

This was a verification and planning gate only. No Nginx files were edited, Nginx
was not reloaded, no public DNS/subdomain was created, and no public traffic
tests were run.

Internal runtime is healthy and substantially ready from an infrastructure
perspective, but public exposure remains blocked. The two main blockers are
product/runtime readiness: LLM provider is still `stub`, and
`flowbiz-ai-core` is not installed. A metadata-only canary could be designed,
but it must be explicitly route-restricted and reviewed before any Nginx change.

## 2. Current Internal Runtime Verification

Verified on the VPS:

- container: `flowbiz-ai-platform-prod`
- image: `flowbiz-ai-platform:9595b66e6100`
- deployed commit label:
  `9595b66e61003c17a702f5d48c0233b85f95b8cc`
- Docker health: `healthy`
- restart policy: `unless-stopped`
- network: `flowbiz-platform-internal`
- binding: `8100/tcp -> 127.0.0.1:18100`

Internal endpoint verification:

- `GET /healthz`: `200`
- `GET /readyz`: `200`
- `GET /v1/meta`: `200`
- `GET /docs`: `404`
- `GET /openapi.json`: `404`
- `/v1/meta` does not expose `env`
- `/v1/meta` does not expose detailed `modes`
- `/v1/meta` exposes `core_dependency.installed=false`
- `/v1/meta` reports rate limiting enabled

Nginx verification:

- `flowbiz.cloud/api` still proxies to `http://127.0.0.1:8000`
- no Nginx config references `18100`
- no Nginx config references `flowbiz-ai-platform`
- no Nginx config references `api.flowbiz.cloud`

## 3. Protected Internal Smoke Results

An ephemeral `platform:ops:read` key was created inside the platform API key
store, used for GET-only internal smoke checks, and revoked immediately. The key
value was not printed.

Results:

- authenticated `GET /v1/platform/ops/metrics`: `200`
- authenticated `GET /v1/platform/ops/observability`: `200`
- ephemeral key revoked after smoke: yes

`POST /v1/platform/ops/llm/smoke` was not run because provider mode remains
`stub` and this gate did not approve LLM provider smoke as public-readiness
evidence.

## 4. LLM Provider Gate

Public canary with functional API routes is not allowed while the LLM provider
remains `stub`.

Public routing should remain blocked until a real provider is configured if the
canary exposes any route that can trigger model execution or user-facing AI
behavior.

Required env keys by name only for real provider readiness:

- `PLATFORM_LLM_PROVIDER`
- `PLATFORM_LLM_MODEL`
- `PLATFORM_SECRET_PROVIDER`
- `PLATFORM_OPENAI_API_KEY_SECRET_NAME`
- `PLATFORM_OPENAI_BASE_URL`
- provider secret key named by `PLATFORM_OPENAI_API_KEY_SECRET_NAME`

Stub is acceptable only for an intentionally metadata-only canary with strict
Nginx allowlist:

- allow `GET /healthz`
- allow `GET /readyz`
- allow `GET /v1/meta`
- deny `/v1/platform/*`
- deny all POST/PUT/PATCH/DELETE methods
- keep docs and OpenAPI disabled

That metadata-only canary is a separate explicit decision, not approved by this
gate.

## 5. Core Dependency Gate

`core_dependency.installed=false` is acceptable for the current internal
deployment and for a metadata-only external canary that exposes only safe status
routes.

It is not acceptable for a broad functional platform API canary if the public
contract implies `flowbiz-ai-core` backed behavior.

Observed code dependency:

- `platform_app.core_bridge.get_core_package_status()` is used by `/v1/meta`
  only.
- No current route imports core execution APIs directly.

Routes safe without core:

- `GET /healthz`
- `GET /readyz`
- `GET /v1/meta`
- authenticated `GET /v1/platform/ops/metrics`
- authenticated `GET /v1/platform/ops/observability`

Routes not approved for public exposure before core/provider decision:

- `/v1/platform/chat`
- `/v1/platform/workflows/*`
- `/v1/platform/api-keys*`
- `/v1/platform/ops/llm/smoke`

## 6. Public Route Shape Decision

### Option 1: `api.flowbiz.cloud`

Recommended first canary shape.

Pros:

- clean separation from the static/root site
- simplest rollback by disabling one server block
- avoids disrupting the existing `flowbiz.cloud/api` legacy upstream
- cleaner future boundary for Hermes/core/platform API routing
- easier to apply narrow route allowlists during canary

Cons:

- requires DNS and certificate work
- clients need a new hostname

### Option 2: `flowbiz.cloud/api`

Not recommended for first canary.

Pros:

- existing public hostname and path convention
- potentially less client-side hostname change

Cons:

- currently points to legacy `127.0.0.1:8000`
- higher rollback risk because it changes an existing path
- more path rewrite complexity
- easier to accidentally affect static/admin routes
- harder to keep platform, Hermes, and core boundaries clean

Decision:

- Prefer `api.flowbiz.cloud` for the first reviewed canary.
- Do not replace `flowbiz.cloud/api` until the subdomain canary passes.

## 7. Proposed Nginx Canary Plan

Do not apply this plan yet.

Proposed metadata-only canary server block:

```nginx
upstream flowbiz_ai_platform_internal {
    server 127.0.0.1:18100;
    keepalive 16;
}

server {
    listen 80;
    server_name api.flowbiz.cloud;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl http2;
    server_name api.flowbiz.cloud;

    ssl_certificate /etc/letsencrypt/live/api.flowbiz.cloud/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.flowbiz.cloud/privkey.pem;

    client_max_body_size 256k;
    proxy_connect_timeout 3s;
    proxy_send_timeout 10s;
    proxy_read_timeout 10s;

    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy no-referrer always;

    location = /healthz {
        proxy_pass http://flowbiz_ai_platform_internal;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Request-ID $request_id;
    }

    location = /readyz {
        proxy_pass http://flowbiz_ai_platform_internal;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Request-ID $request_id;
    }

    location = /v1/meta {
        proxy_pass http://flowbiz_ai_platform_internal;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Request-ID $request_id;
    }

    location / {
        return 404;
    }
}
```

TLS/certbot considerations:

- create DNS for `api.flowbiz.cloud` only after explicit approval
- issue certificate before enabling the 443 server block
- use `nginx -t` before any reload
- do not reuse or alter the existing `flowbiz.cloud` server block for this
  canary

Validation commands for a future approved change:

```bash
nginx -t
curl -fsS https://api.flowbiz.cloud/healthz
curl -fsS https://api.flowbiz.cloud/readyz
curl -fsS https://api.flowbiz.cloud/v1/meta
curl -sS -o /dev/null -w '%{http_code}\n' https://api.flowbiz.cloud/docs
curl -sS -o /dev/null -w '%{http_code}\n' https://api.flowbiz.cloud/openapi.json
curl -sS -o /dev/null -w '%{http_code}\n' https://api.flowbiz.cloud/v1/platform/ops/metrics
```

Expected future validation:

- health/meta routes return `200`
- docs and OpenAPI return `404`
- non-allowlisted routes return `404`
- protected ops routes are not publicly reachable
- no secrets appear in access/error logs

Stop conditions for future canary:

- `nginx -t` fails
- certificate issuance fails
- any non-allowlisted route is reachable
- docs/OpenAPI become reachable
- platform binds to a public host port
- protected route responds without auth
- `/v1/meta` exposes `env`, detailed modes, or sensitive config
- existing `flowbiz.cloud/api` behavior changes unexpectedly

## 8. Rollback Plan

For the proposed canary:

1. Remove or disable only the `api.flowbiz.cloud` server block.
2. Run `nginx -t`.
3. Reload Nginx only after syntax passes.
4. Confirm `flowbiz.cloud/api` remains unchanged.
5. Keep `flowbiz-ai-platform-prod` running internally; canary rollback should
   not require platform container rollback.

If platform rollback is also needed, use the previously captured rollback image:

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

## 9. Public Readiness Score

Scores are 0-5.

- internal runtime: 5
- auth enforcement: 4
- rate limiting: 5
- docs exposure: 5
- metadata safety: 5
- protected ops smoke: 5
- LLM readiness: 1
- core integration readiness: 2
- Nginx canary readiness: 3
- rollback readiness: 4

Overall readiness: 3.9/5 for a metadata-only canary plan, not for public
functional API exposure.

## 10. Blockers

- LLM provider remains `stub`.
- `flowbiz-ai-core` is not installed.
- No approved public Nginx canary change exists yet.
- No DNS/certificate work for `api.flowbiz.cloud` has been approved.
- Functional API route exposure has not been scoped or approved.
- `flowbiz.cloud/api` still points to the legacy upstream and must not be
  replaced until a subdomain canary passes.

## 11. Final Routing Decision

- Public exposure allowed now: No.
- `api.flowbiz.cloud` canary allowed now: No.
- `flowbiz.cloud/api` cutover allowed now: No.

Required before actual Nginx change:

- explicit approval of metadata-only vs functional canary scope
- explicit approval to create DNS/certificate for `api.flowbiz.cloud`
- reviewed Nginx config with route allowlist and rollback steps
- `nginx -t` plan and validation checklist
- decision on real LLM provider readiness
- decision on whether core integration is required before functional exposure

## 12. Next Recommended Phase

Run an `api.flowbiz.cloud` metadata-only canary preparation phase:

1. Decide whether metadata-only canary is acceptable while LLM remains `stub`.
2. Approve DNS and certbot work for `api.flowbiz.cloud`.
3. Prepare Nginx config in a reviewed file without enabling it.
4. Run `nginx -t` only after explicit approval.
5. Enable canary with strict allowlist only after the gate owner approves.
