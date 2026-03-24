# PLATFORM_SLICE_009_CONTROLLED_DISPATCH_CALLBACK_LOOP

This slice closes the controlled runner loop without turning the platform into a workflow engine.

Baseline contract after FBP-001:

- dispatch is always platform-initiated from an admitted job
- each dispatch attempt is stored in `workflow_dispatches`
- dispatch status is constrained to `pending`, `sent`, or `failed`
- the runner callback endpoint is
  `POST /v1/platform/workflows/jobs/{job_id}/callback`
- callback auth uses `X-FlowBiz-Callback-Token`
- the token is derived from
  `HMAC-SHA256(PLATFORM_WORKFLOW_CALLBACK_SHARED_SECRET, "{job_id}:{dispatch_id}")`
- only the token hash is stored in the dispatch record
- callback outcomes are explicit:
  - duplicate
  - stale
  - invalid transition
  - accepted
- only accepted callbacks append a new workflow event

Accepted callback status mapping:

- `in_progress` -> `running`
- `success` -> `succeeded`
- `failed` -> `failed`

The callback loop updates job projection through the event ledger, not by mutating a side-channel status field.

The implementation lives in
[platform_app/dispatch_records.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/dispatch_records.py)
and
[platform_app/routes/workflow_events.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/routes/workflow_events.py).

See
[PLATFORM_BASELINE_WORKFLOW_STATE_CONTRACT.md](/d:/FlowBiz/flowbiz-ai-platform/docs/platform/PLATFORM_BASELINE_WORKFLOW_STATE_CONTRACT.md)
for the merged baseline contract.
