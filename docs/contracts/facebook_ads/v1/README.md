<!-- markdownlint-disable MD013 -->

# FlowBiz Facebook Ads Platform API v1

## Status

`CONTRACT_ONLY_DRAFT`

This directory is the Product/Platform integration contract for PROD-02. It defines the intended JSON boundary from the Next.js BFF to Platform. It does not implement routes, authentication, authorization, persistence, jobs, agents, providers, billing, Meta access, deployment, or a Core dependency pin.

## Trust Boundary

`Browser -> Next.js BFF -> Platform API`

- The browser uses Secure, HttpOnly session cookies with the BFF and never calls Platform directly.
- The BFF forwards a Supabase bearer token to Platform; Platform will validate signature, issuer, audience, and expiry before resolving identity.
- `X-Tenant-ID` is an untrusted selector. Platform membership and resource tenant keys are authoritative.
- Authorization defaults to deny. Unknown roles, job states, malformed outputs, and indeterminate dependency results fail closed.
- Mutations require `Idempotency-Key`; every response carries `X-Request-ID` for correlation.

## Contract Inventory

- OpenAPI: [`openapi.json`](openapi.json)
- Synthetic fixtures: [`fixtures/`](fixtures/)
- Contract validation: [`../../../../tests/test_facebook_ads_v1_contract.py`](../../../../tests/test_facebook_ads_v1_contract.py)

The contract contains 21 paths, 27 operations, and 29 component schemas. Required operations cover identity, tenant provisioning and membership, project CRUD, onboarding, three asynchronous generation lanes, job status/retry/cancel, persisted outputs, dashboard, approvals, audit, and usage.

## Roles

`owner`, `admin`, `marketer`, `viewer`, and `service_identity` are recognized roles. Each operation declares its minimum role in `x-flowbiz-rbac`; the later implementation must perform authoritative tenant membership lookup and may impose stricter policy.

## Safe Failure

Standard safe errors cover `400`, `401`, `403`, `404`, `409`, `422`, `429`, and `503`. Error details must be non-sensitive. A timeout, unknown state, malformed provider output, tenant mismatch, or dependency failure never implies a successful mutation.

## Explicit Deferrals

This version excludes Meta write actions, autonomous budget changes, campaign creation, production Meta OAuth, billing/payment, agency white-label, multi-platform ads, and automated execution. No pricing, trial length, model identifier, Meta permission, credential, outcome guarantee, or partner claim is defined.
