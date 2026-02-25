# FlowBiz AI Platform Roadmap (Bootstrap for #2-#4)

This repo implements platform-specific behavior that is intentionally out of scope for `flowbiz-ai-core`.

## Ownership Split

- `flowbiz-ai-core`: contracts, runtime primitives, reusable schemas, minimal core API
- `flowbiz-ai-platform` (this repo): public API security, provider integrations, secrets, rate limiting, observability backends, platform operations

## Current Bootstrap Scope (Done in Skeleton)

- FastAPI platform service skeleton (`apps/platform_api/`)
- Config and env layout (`platform_app/config.py`, `.env.example`)
- Pinned dependency on `flowbiz-ai-core==0.2.0`
- Scaffolding modules for:
  - API key auth
  - rate limiting
  - LLM adapters
  - secret providers
  - observability bundle
- Stub platform endpoint: `POST /v1/platform/chat`

## #2 Public API Auth + API Key + Rate Limit (Next)

### Goal

Secure public endpoints and control abuse before exposing platform APIs externally.

### Deliverables

- Persistent API key store (DB-backed, hashed keys)
- Key scopes/permissions model
- Key rotation/revoke flow
- Auth middleware/dependencies with audit fields
- Redis-backed distributed rate limiter
- Standard rate-limit response headers

### DoD

- Auth required for all public write endpoints
- 401/403/429 behavior covered by tests
- Per-key and per-route limits configurable
- Basic audit logs include `key_id`, `route`, `trace_id`, `decision`

## #3 LLM Adapter + Secret Handling (Next)

### Goal

Replace stub LLM adapter with real providers and production-safe secret management.

### Deliverables

- Provider adapters (start with one provider, e.g. OpenAI)
- Timeout/retry configuration
- Error mapping and provider failure handling
- Secret provider abstraction implementations (env -> vault/manager later)
- Startup validation for required secrets per provider

### DoD

- Successful real provider request path (integration test or controlled smoke)
- Secret lookup errors fail fast with clear messages
- Provider errors mapped to stable platform response schema

## #4 Observability / Alerting (Next)

### Goal

Instrument platform behavior for production operations.

### Deliverables

- Prometheus metrics endpoint
- OpenTelemetry tracing exporter
- Structured logs with request correlation
- Dashboards (Grafana) and alert rules (error rate/latency/availability)
- Post-deploy smoke hook integration

### DoD

- Metrics/traces/logs visible in target backend
- Alert rules documented and tested in staging
- Incident runbook references dashboard and alert names

## Suggested Build Order

1. Auth + API keys (minimum viable security)
2. Redis rate limiting
3. First real LLM provider + env secret provider
4. Metrics + tracing
5. Alerts and dashboards
6. Hardened deploy lane for platform repo (reusing core scripts/runbooks where appropriate)

