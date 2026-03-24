# PLATFORM_SLICE_008_JOB_LIST_OPERATOR_READ_MODEL

This slice defines the operator-facing read model served by
`GET /v1/platform/workflows/jobs`.

Baseline contract after FBP-001:

- ordering is deterministic: `created_at DESC, job_id DESC`
- `limit` is the only list control and is bounded to `1..100`
- each item exposes only summary fields:
  - `job_id`
  - `client_id`
  - `workflow_key`
  - `admission_status`
  - `current_status`
  - `raw_status`
  - `created_at`
  - `latest_received_at`
- `current_status` is projected from the ledger when events exist
- `current_status` falls back to the admission record when no events exist
- `input_payload` and `metadata` are intentionally excluded

The implementation lives in
[platform_app/job_records.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/job_records.py)
and
[platform_app/routes/workflow_events.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/routes/workflow_events.py).

This is a safe operator summary surface, not a dashboard API and not a raw ledger dump.
See
[PLATFORM_BASELINE_WORKFLOW_STATE_CONTRACT.md](/d:/FlowBiz/flowbiz-ai-platform/docs/platform/PLATFORM_BASELINE_WORKFLOW_STATE_CONTRACT.md)
for the full baseline.
