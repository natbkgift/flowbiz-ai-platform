# PLATFORM_SLICE_001_WORKFLOW_EVENT_LEDGER

This slice established the append-only workflow event ledger in
[platform_app/workflow_events.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/workflow_events.py)
and the workflow routes in
[platform_app/routes/workflow_events.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/routes/workflow_events.py).

Baseline contract after FBP-001:

- `workflow_events` remains append-only platform history.
- `POST /v1/platform/workflows/events` only accepts events for an admitted platform job.
- Event intake must match the admitted `client_id` and `workflow_key` for that `job_id`.
- `GET /v1/platform/workflows/jobs/{job_id}/events` is a ledger read for admitted jobs.
- Projection reads may normalize raw event statuses, but the raw ledger payload remains stored.

The table shape remains:

- `id`
- `job_id`
- `client_id`
- `workflow_key`
- `execution_id`
- `status`
- `received_at`
- `raw_payload`
- `source`

The baseline does not add replay, retries, or orchestration ownership beyond append-only history.
See
[PLATFORM_BASELINE_WORKFLOW_STATE_CONTRACT.md](/d:/FlowBiz/flowbiz-ai-platform/docs/platform/PLATFORM_BASELINE_WORKFLOW_STATE_CONTRACT.md)
for the merge-ready contract that now governs admission, ledger, dispatch, callback, and read models together.
