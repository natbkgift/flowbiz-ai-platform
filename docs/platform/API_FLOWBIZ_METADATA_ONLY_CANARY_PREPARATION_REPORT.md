# api.flowbiz.cloud Metadata-only Canary Preparation Report

Verified on 2026-05-10 from the VPS alias `flowbiz-vps`.

## 1. Summary

The `api.flowbiz.cloud` metadata-only canary is prepared as a plan and reviewed
configuration draft only. No DNS record was created, no certificate was issued,
no Nginx canary file was written on the VPS, and Nginx was not reloaded.

Current internal platform checks passed:

- container: `flowbiz-ai-platform-prod`
- image: `flowbiz-ai-platform:9595b66e6100`
- Docker health: `healthy`
- binding: `127.0.0.1:18100 -> 8100`
- internal metadata endpoints: healthy
- docs and OpenAPI: still disabled internally

Current public routing remains unchanged:

- no Nginx reference to `api.flowbiz.cloud`
- no Nginx reference to platform port `18100`
- `flowbiz.cloud/api` still proxies to legacy `127.0.0.1:8000`
- functional public API exposure remains blocked

## 2. Preflight Verification

Docker runtime:

| Check | Result |
| --- | --- |
| Container exists | Pass |
| Container status | `Up 7 hours (healthy)` |
| Container image | `flowbiz-ai-platform:9595b66e6100` |
| Docker health | `healthy` |
| Docker port map | `127.0.0.1:18100->8100/tcp` |
| Host listener | `127.0.0.1:18100` only |

Internal endpoint status checks against `http://127.0.0.1:18100`:

| Request | Result |
| --- | --- |
| `GET /healthz` | `200` |
| `GET /readyz` | `200` |
| `GET /v1/meta` | `200` |
| `GET /docs` | `404` |
| `GET /openapi.json` | `404` |

Nginx state:

| Check | Result |
| --- | --- |
| `api.flowbiz.cloud` in `/etc/nginx` | Not found |
| Platform port `18100` in `/etc/nginx` | Not found |
| Platform app name in `/etc/nginx` | Not found |
| Current `nginx -t` | Pass |
| Nginx reload | Not run |

Current `flowbiz.cloud/api` active config remains:

```nginx
location /api/ {
  rewrite ^/api/(.*)$ /$1 break;
  proxy_pass http://127.0.0.1:8000;
  proxy_set_header Host $host;
  proxy_set_header X-Real-IP $remote_addr;
  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  proxy_set_header X-Forwarded-Proto $scheme;
}
```

## 3. Canary Scope

Allowed public canary surface:

- `GET /healthz`
- `GET /readyz`
- `GET /v1/meta`

Denied public canary surface:

- `/docs`
- `/openapi.json`
- `/v1/platform/*`
- all non-GET methods
- all other paths

Functional platform API exposure remains blocked because:

- LLM provider remains `stub`
- `flowbiz-ai-core` is not installed
- public routing has not been enabled
- protected platform routes are outside this canary scope

## 4. DNS/TLS Status

DNS status:

| Name | Result |
| --- | --- |
| `flowbiz.cloud` A | `72.62.69.117` |
| VPS public IPv4 | `72.62.69.117` |
| `api.flowbiz.cloud` A | Not present |
| `api.flowbiz.cloud` AAAA | Not present |
| `flowbiz.cloud` AAAA | Not present |
| VPS public IPv6 | `2a02:4780:5e:c382::1` |

Required DNS record before enablement:

```dns
api.flowbiz.cloud. 300 IN A 72.62.69.117
```

Do not add an AAAA record unless IPv6 serving is explicitly approved and tested.
The VPS has an IPv6 address, but the current apex hostname has no AAAA record.

TLS status:

- Certbot is installed: `certbot 2.9.0`
- `/etc/letsencrypt/live/api.flowbiz.cloud` is absent
- no certificate was issued for `api.flowbiz.cloud`
- existing `flowbiz.cloud` certificate was not modified
- cert private key contents were not read or printed

TLS issuance plan after DNS approval:

1. Add the `api.flowbiz.cloud` A record and wait for resolution.
2. Create only an approved HTTP-01 challenge/server block for
   `api.flowbiz.cloud`, or use the approved full canary config below after the
   certificate paths exist.
3. Run `nginx -t`.
4. Reload Nginx only after explicit approval and a passing syntax test.
5. Issue a separate certificate:

```bash
certbot certonly \
  --webroot -w /var/www/certbot \
  --cert-name api.flowbiz.cloud \
  -d api.flowbiz.cloud
```

Do not use a command that expands or replaces the existing `flowbiz.cloud`
certificate.

## 5. Nginx Config Draft

No Nginx config file was created in this phase because explicit approval to
write the canary file was not given.

Reviewed future file path:

```text
/etc/nginx/conf.d/api.flowbiz.cloud.metadata-canary.conf
```

Draft content for the future approved step:

```nginx
upstream flowbiz_ai_platform_metadata_canary {
    server 127.0.0.1:18100 max_fails=3 fail_timeout=10s;
    keepalive 16;
}

server {
    listen 80;
    listen [::]:80;
    server_name api.flowbiz.cloud;
    server_tokens off;

    client_max_body_size 16k;
    client_body_timeout 5s;
    client_header_timeout 5s;

    add_header Allow "GET" always;

    if ($request_method != GET) {
        return 405;
    }

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name api.flowbiz.cloud;
    server_tokens off;

    ssl_certificate /etc/letsencrypt/live/api.flowbiz.cloud/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.flowbiz.cloud/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    client_max_body_size 16k;
    client_body_timeout 5s;
    client_header_timeout 5s;
    keepalive_timeout 10s;

    proxy_http_version 1.1;
    proxy_connect_timeout 3s;
    proxy_send_timeout 10s;
    proxy_read_timeout 10s;
    proxy_buffering off;

    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy no-referrer always;
    add_header X-Frame-Options DENY always;
    add_header Content-Security-Policy "default-src 'none'; frame-ancestors 'none'; base-uri 'none'" always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
    add_header Cache-Control "no-store" always;
    add_header Allow "GET" always;

    location = /healthz {
        if ($request_method != GET) {
            return 405;
        }

        proxy_pass http://flowbiz_ai_platform_metadata_canary;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Request-ID $request_id;
    }

    location = /readyz {
        if ($request_method != GET) {
            return 405;
        }

        proxy_pass http://flowbiz_ai_platform_metadata_canary;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Request-ID $request_id;
    }

    location = /v1/meta {
        if ($request_method != GET) {
            return 405;
        }

        proxy_pass http://flowbiz_ai_platform_metadata_canary;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Request-ID $request_id;
    }

    location = /docs {
        return 404;
    }

    location = /openapi.json {
        return 404;
    }

    location ^~ /v1/platform/ {
        return 404;
    }

    location / {
        return 404;
    }
}
```

This draft does not rewrite to `flowbiz.cloud/api` and does not expose
`/v1/platform/*`.

## 6. Validation Matrix

Current internal preflight validation:

| Check | Expected | Actual | Status |
| --- | --- | --- | --- |
| Platform Docker health | `healthy` | `healthy` | Pass |
| Platform binding | `127.0.0.1:18100` only | `127.0.0.1:18100` only | Pass |
| Internal `GET /healthz` | `200` | `200` | Pass |
| Internal `GET /readyz` | `200` | `200` | Pass |
| Internal `GET /v1/meta` | `200` | `200` | Pass |
| Internal `GET /docs` | `404` | `404` | Pass |
| Internal `GET /openapi.json` | `404` | `404` | Pass |
| Current Nginx syntax | pass | pass | Pass |
| Current `api.flowbiz.cloud` config | absent | absent | Pass |
| Current `flowbiz.cloud/api` upstream | `127.0.0.1:8000` | `127.0.0.1:8000` | Pass |

Future validation commands after approved config write:

```bash
nginx -t
curl -sS -o /dev/null -w '%{http_code}\n' -H 'Host: api.flowbiz.cloud' http://127.0.0.1/healthz
curl -sS -o /dev/null -w '%{http_code}\n' -H 'Host: api.flowbiz.cloud' http://127.0.0.1/readyz
curl -sS -o /dev/null -w '%{http_code}\n' -H 'Host: api.flowbiz.cloud' http://127.0.0.1/v1/meta
curl -sS -o /dev/null -w '%{http_code}\n' -H 'Host: api.flowbiz.cloud' http://127.0.0.1/docs
curl -sS -o /dev/null -w '%{http_code}\n' -H 'Host: api.flowbiz.cloud' http://127.0.0.1/openapi.json
curl -sS -o /dev/null -w '%{http_code}\n' -H 'Host: api.flowbiz.cloud' http://127.0.0.1/v1/platform/ops/metrics
curl -sS -o /dev/null -w '%{http_code}\n' -X POST -H 'Host: api.flowbiz.cloud' http://127.0.0.1/v1/platform/chat
```

Future HTTPS host-header validation after certificate issuance but before DNS
cutover:

```bash
curl --resolve api.flowbiz.cloud:443:127.0.0.1 -sS -o /dev/null -w '%{http_code}\n' https://api.flowbiz.cloud/healthz
curl --resolve api.flowbiz.cloud:443:127.0.0.1 -sS -o /dev/null -w '%{http_code}\n' https://api.flowbiz.cloud/readyz
curl --resolve api.flowbiz.cloud:443:127.0.0.1 -sS -o /dev/null -w '%{http_code}\n' https://api.flowbiz.cloud/v1/meta
curl --resolve api.flowbiz.cloud:443:127.0.0.1 -sS -o /dev/null -w '%{http_code}\n' https://api.flowbiz.cloud/docs
curl --resolve api.flowbiz.cloud:443:127.0.0.1 -sS -o /dev/null -w '%{http_code}\n' https://api.flowbiz.cloud/openapi.json
curl --resolve api.flowbiz.cloud:443:127.0.0.1 -sS -o /dev/null -w '%{http_code}\n' https://api.flowbiz.cloud/v1/platform/ops/metrics
curl --resolve api.flowbiz.cloud:443:127.0.0.1 -sS -o /dev/null -w '%{http_code}\n' -X POST https://api.flowbiz.cloud/v1/platform/chat
```

Expected public canary results after DNS/TLS enablement:

| Request | Expected |
| --- | --- |
| `GET https://api.flowbiz.cloud/healthz` | `200` |
| `GET https://api.flowbiz.cloud/readyz` | `200` |
| `GET https://api.flowbiz.cloud/v1/meta` | `200` |
| `GET https://api.flowbiz.cloud/docs` | `404` |
| `GET https://api.flowbiz.cloud/openapi.json` | `404` |
| `GET https://api.flowbiz.cloud/v1/platform/ops/metrics` | `404` |
| `POST https://api.flowbiz.cloud/v1/platform/chat` | `404` or `405` |
| `flowbiz.cloud/api` | unchanged legacy upstream |

Stop immediately if any non-allowlisted route reaches the platform app, docs or
OpenAPI become reachable, `flowbiz.cloud/api` changes, `nginx -t` fails, or the
platform listener becomes public.

## 7. Rollback Plan

Rollback scope is only `api.flowbiz.cloud`.

1. Disable only `/etc/nginx/conf.d/api.flowbiz.cloud.metadata-canary.conf`.
2. Run `nginx -t`.
3. Reload Nginx only after syntax passes.
4. Confirm no `/etc/nginx` reference to `api.flowbiz.cloud` or `18100` remains.
5. Confirm `flowbiz.cloud/api` still proxies to `127.0.0.1:8000`.
6. Confirm internal platform health on `127.0.0.1:18100`.

Do not rollback the platform container unless internal platform health fails.

Suggested rollback verification:

```bash
nginx -t
grep -RIn "api\\.flowbiz\\.cloud" /etc/nginx 2>/dev/null || true
grep -RInE "127\\.0\\.0\\.1:18100|18100" /etc/nginx 2>/dev/null || true
grep -RInE "location[[:space:]].*/api|proxy_pass[[:space:]]+http://127\\.0\\.0\\.1:8000" /etc/nginx/conf.d/flowbiz.cloud.conf
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18100/healthz
```

## 8. Actions Taken

- Used read-only SSH checks against `flowbiz-vps`.
- Confirmed Docker runtime state, image, health, and localhost-only binding.
- Confirmed internal status codes for allowed and denied metadata routes.
- Confirmed there is no Nginx config for `api.flowbiz.cloud`.
- Confirmed Nginx has no reference to platform port `18100`.
- Confirmed the active `flowbiz.cloud/api` route still targets
  `127.0.0.1:8000`.
- Checked DNS for `api.flowbiz.cloud`.
- Checked Certbot availability and the absence of an `api.flowbiz.cloud`
  certificate directory.
- Ran current `nginx -t`; it passed.
- Created this local Markdown preparation report.

## 9. Actions Not Taken

- Did not create DNS.
- Did not issue TLS.
- Did not write an Nginx canary config file on the VPS.
- Did not enable an Nginx site or reload Nginx.
- Did not touch `flowbiz.cloud/api`.
- Did not deploy Hermes.
- Did not expose `/v1/platform/*`.
- Did not expose POST, PUT, PATCH, or DELETE methods.
- Did not print secrets, API keys, tokens, `.env` contents, private keys, cert
  private key contents, or database contents.
- Did not restart or rollback the platform container.

## 10. Remaining Blockers

- `api.flowbiz.cloud` DNS does not exist.
- `api.flowbiz.cloud` TLS certificate has not been issued.
- Explicit approval to create the Nginx canary file has not been given.
- Explicit approval to reload Nginx for enablement has not been given.
- External public validation cannot run until DNS/TLS/Nginx enablement occurs.
- LLM provider remains `stub`.
- `flowbiz-ai-core` is not installed.
- Functional public API exposure remains blocked.

## 11. Final Decision

| Question | Decision |
| --- | --- |
| Is metadata-only canary prepared? | Yes, as a preparation report and reviewed config draft only |
| Was DNS created? | No |
| Was TLS issued? | No |
| Was Nginx enabled? | No |
| Did validation pass? | Internal preflight and current `nginx -t` passed; public canary validation was not run |
| Is functional API exposure still blocked? | Yes |
| Is `flowbiz.cloud/api` still untouched? | Yes |

Final routing decision:

- Safe to expose functional APIs now: No.
- Safe to touch `flowbiz.cloud/api` now: No.
- Safe to proceed to the next canary enable step: only after explicit approval
  for DNS, TLS, Nginx config creation, `nginx -t`, and controlled reload.
