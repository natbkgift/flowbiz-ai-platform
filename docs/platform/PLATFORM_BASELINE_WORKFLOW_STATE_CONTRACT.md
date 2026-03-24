# PLATFORM_BASELINE_WORKFLOW_STATE_CONTRACT

This document is the merge-ready baseline contract for workflow state in `flowbiz-ai-platform`.

## Scope

- admission record: `workflow_jobs`
- append-only event ledger: `workflow_events`
- dispatch audit trail: `workflow_dispatches`
- controlled runner callback loop
- operator read surfaces for job detail and job list

## Authoritative Start

- `POST /v1/platform/workflows/jobs` is the authoritative workflow start.
- The platform generates `job_id`.
- The admission record is persisted before any runner dispatch or event projection exists.
- `GET /v1/platform/workflows/jobs/{job_id}/record` returns the admission record.

## Ledger Contract

- `POST /v1/platform/workflows/events` appends workflow events.
- Event intake only accepts admitted jobs.
- Event intake must match the admitted `client_id` and `workflow_key`.
- The ledger remains append-only and stores the normalized fields plus `raw_payload`.

## Projection Contract

- `GET /v1/platform/workflows/jobs/{job_id}` returns the current platform projection.
- If ledger events exist, projection is derived from the latest event.
- If no ledger events exist, projection falls back to the admission record.
- Unknown jobs return `404`.

## Dispatch Contract

- `POST /v1/platform/workflows/jobs/{job_id}/dispatch` creates a persisted dispatch attempt.
- `GET /v1/platform/workflows/jobs/{job_id}/dispatches` returns dispatch attempts in stable order.
- Dispatch status is limited to `pending`, `sent`, and `failed`.

## Callback Contract

- `POST /v1/platform/workflows/jobs/{job_id}/callback` is the only runner completion path in this baseline.
- Callback auth is deterministic and fail-closed.
- Duplicate callbacks are idempotent.
- Stale callbacks are rejected.
- Conflicting terminal callbacks are rejected.
- Accepted callbacks append to the ledger and therefore update projection and job list state.

## Operator Read Model

- `GET /v1/platform/workflows/jobs` is a safe summary list.
- Ordering is deterministic: `created_at DESC, job_id DESC`.
- The list exposes summary fields only and does not return `input_payload` or `metadata`.

## Out Of Scope

- billing, pricing, or plan logic
- dashboard UI
- queue or worker system
- multi-runner orchestration
- retries or reconciliation engine
