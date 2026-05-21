# Platform Runner Connectivity

## Observed VPS Topology

Read-only inspection showed:

- `flowbiz-ai-platform-prod` is attached only to Docker `bridge`.
- `flowbiz-infra-n8n-api-1` is attached to `flowbiz-infra-n8n_default`.
- `flowbiz-infra-n8n-n8n-1`, n8n Postgres, and n8n Redis are also attached to
  `flowbiz-infra-n8n_default`.
- `flowbiz-platform-internal` exists but currently has no containers attached.
- Hostname lookups from the platform container for n8n/API/Redis names return no
  records because the platform is not attached to the relevant networks.

## Dispatch URL Validation

The platform validates `PLATFORM_WORKFLOW_RUNNER_DISPATCH_URL` before building
the runner dispatcher:

- must be `http` or `https`
- must include a hostname
- must not embed username/password credentials
- must not use URL fragments
- must not use localhost addresses in production

This validation does not replace Docker DNS testing. It only prevents obvious
misconfiguration and secret-in-URL patterns.

## Recommended Production Topology

Use a dedicated internal control network:

- Network: `flowbiz-platform-internal`
- Members:
  - `flowbiz-ai-platform-prod`
  - the specific runner/API service that receives dispatch requests
  - Redis only if it is the approved platform rate-limit Redis
- Service alias:
  - assign a stable alias such as `flowbiz-runner-dispatch`

Example target shape:

```text
flowbiz-ai-platform-prod
  -> http://flowbiz-runner-dispatch:<port>/<dispatch-path>
```

## Alternatives

### Join `flowbiz-infra-n8n_default`

This is the fastest short-term path, but it gives the platform broad network
reachability to n8n, n8n Postgres, and n8n Redis. Use only for a tightly scoped
internal test and document the temporary exception.

### New Shared Internal Network

Create a new network if `flowbiz-platform-internal` is not acceptable. This is
equivalent to the recommended model, but it adds another network to operate.

### Dedicated Platform-Control Network

This is the recommended long-term model. It keeps dispatch and rate-limit
dependencies scoped to platform control traffic and avoids coupling the platform
to n8n's full internal network.

## Required Evidence Before Enabling Dispatch

- Docker network membership for platform and runner/API service.
- `getent hosts <runner-alias>` succeeds inside the platform container.
- Internal GET health check for the runner/API service succeeds if available.
- No production workflow dispatch POST is run until explicitly approved.
