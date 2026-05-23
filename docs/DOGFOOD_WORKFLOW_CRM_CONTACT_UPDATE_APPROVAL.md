# Dogfood Workflow 1 - CRM Contact Update Approval

## Workflow Overview

Workflow name: `FlowBiz Gate - CRM Contact Update Approval`

Purpose: route a proposed CRM contact update through the FlowBiz Approval Gate
before any CRM mutation is allowed to run.

This is the first dogfood workflow because contact updates are common, bounded,
and business-relevant without requiring Phase 2 approval queue UI, callbacks, or
production deployment. The workflow validates the core loop:

```text
trigger -> proposal -> gate decision -> branch -> audit evidence
```

Safety principle: only `ALLOW` may execute the CRM mutation. `NEEDS_APPROVAL`,
`DENY`, timeout, non-200, malformed response, or unknown decision must stop the
workflow and log evidence. Do not put raw PII in `payload_summary`; hash the
intended mutation payload into `payload_hash`.

## Architecture

1. Trigger receives a contact update request from a manual test, webhook, or CRM
   automation trigger.
2. Workflow builds a proposal payload with a stable `proposal_id`, action class,
   target scope, mutation type, safe summary, and SHA-256 `payload_hash`.
3. Workflow sends the proposal to the Approval Gate:
   `POST http://127.0.0.1:8100/v1/gate/proposals`.
4. Workflow branches by `decision`.
5. `ALLOW` branch executes only the safe test CRM update or mock CRM update.
6. `NEEDS_APPROVAL`, `DENY`, and error branches do not mutate CRM. They record
   the stop reason and evidence fields.
7. Approval Gate DB remains the audit source of record for the proposal and
   decision.

## n8n Implementation

### Node 1 - Manual Trigger or Webhook Trigger

Use `Manual Trigger` for local dry runs. Use `Webhook Trigger` only after the
manual flow passes.

Recommended manual test input:

```json
{
  "event_id": "dogfood-contact-update-001",
  "contact_id": "test-contact-001",
  "action_class": "crm.contact.update",
  "target_system": "hubspot-prod",
  "target_scope": {
    "type": "single",
    "estimated_record_count": 1
  },
  "mutation_type": "update",
  "payload_summary": "Update one contact from validated workflow trigger",
  "mutation_payload": {
    "contact_id": "test-contact-001",
    "fields": {
      "phone": "+66000000000"
    }
  }
}
```

For a real trigger, keep raw PII inside the workflow context only. Do not copy
names, emails, phone numbers, or addresses into `payload_summary`.

### Node 2 - Code Node: Build Proposal Payload

Node type: `Code`

Node name: `Build Proposal Payload`

Mode: `Run Once for Each Item`

Code:

```javascript
const crypto = require('crypto');

const mutationPayload = $json.mutation_payload ?? {
  contact_id: $json.contact_id,
  fields: $json.fields ?? {},
};

const canonicalPayload = JSON.stringify(mutationPayload);
const payloadHash = crypto
  .createHash('sha256')
  .update(canonicalPayload)
  .digest('hex');

const executionId = $execution.id ?? Date.now();
const eventId = $json.event_id ?? `manual-${executionId}`;
const now = new Date().toISOString();
const actionClass = $json.action_class ?? 'crm.contact.update';
const targetScope = $json.target_scope ?? {
  type: 'single',
  estimated_record_count: 1,
};
const mutationType = $json.mutation_type ?? 'update';
const safeSummary =
  $json.payload_summary ?? 'Update one contact from validated workflow trigger';
const proposalPrefix = $json.proposal_prefix ?? 'n8n-dogfood';

return {
  json: {
    workflow_run_id: executionId,
    proposal: {
      proposal_id: `${proposalPrefix}-${executionId}`,
      connector_id: 'dogfood-n8n',
      action_class: actionClass,
      target_system: $json.target_system ?? 'hubspot-prod',
      target_scope: targetScope,
      mutation_type: mutationType,
      payload_summary: safeSummary,
      payload_hash: payloadHash,
      triggering_signal: {
        source: 'crm_webhook',
        signal_id: eventId,
        signal_timestamp: now,
      },
      submitted_at: now,
      requested_by: 'dogfood-n8n',
    },
    intended_mutation_payload: mutationPayload,
  },
};
```

Use the same workflow for all three decision fixtures by changing only input
fields:

- ALLOW: `action_class=crm.contact.update`, `mutation_type=update`,
  `target_scope.type=single`, `target_scope.estimated_record_count=1`
- NEEDS_APPROVAL: `action_class=crm.campaign.send`, `mutation_type=send`,
  `target_scope.type=bulk`, `target_scope.estimated_record_count=847`
- DENY: `action_class=crm.deal.status_change`,
  `mutation_type=status_change`, `target_scope.type=single`,
  `target_scope.estimated_record_count=1`

If the n8n Code node cannot use the built-in `crypto` module in your runtime,
enable built-in modules for Code nodes in the self-hosted n8n environment or
compute `payload_hash` upstream before the proposal node.

### Node 3 - HTTP Request Node: Submit Proposal to Approval Gate

Node type: `HTTP Request`

Configuration:

- Method: `POST`
- URL: `http://127.0.0.1:8100/v1/gate/proposals`
- Authentication: none in node settings; use header below.
- Headers:
  - `Authorization`: `Bearer {{$env.FLOWBIZ_GATE_API_KEY}}`
  - `Content-Type`: `application/json`
- Body Content Type: `JSON`
- Body: `{{$json.proposal}}`
- Timeout: `10000` ms
- Response format: `JSON`
- Full response: enabled if supported by the installed n8n version.
- Continue On Fail: enabled only if the next node routes failures to the error
  branch. If unavailable, use n8n error workflow handling and fail closed.

Expected successful response shape:

```json
{
  "proposal_id": "n8n-contact-update-123",
  "decision": "ALLOW",
  "decision_id": "uuid",
  "decision_timestamp": "2026-05-23T03:01:09.881+00:00",
  "reason_code": "POLICY_ALLOWED",
  "reason_detail": "Policy pol-contact-update allows this proposal",
  "risk_level": "LOW",
  "approval_required_from": null,
  "approval_queue_id": null,
  "rollback_checklist_id": null
}
```

### Node 4 - Code Node: Normalize Gate Result

Node type: `Code`

Node name: `Normalize Gate Result`

Mode: `Run Once for Each Item`

Purpose: convert HTTP response and error variants into one branchable object.

Code:

```javascript
const proposal = $('Build Proposal Payload').item.json.proposal;
const response = $json.body ?? $json;
const statusCodeRaw = $json.statusCode ?? $json.status ?? null;
const statusCode = Number(statusCodeRaw);
const decision = response?.decision;

const allowedDecisions = ['ALLOW', 'NEEDS_APPROVAL', 'DENY'];
const successfulHttp = statusCode === 200;
const validDecision = successfulHttp && allowedDecisions.includes(decision);
const normalizedDecision = validDecision ? decision : 'ERROR';

let stopReason = null;
if (!successfulHttp) {
  stopReason = 'Approval Gate returned non-200 or missing HTTP status';
} else if (!allowedDecisions.includes(decision)) {
  stopReason = 'Malformed or unknown Approval Gate response';
}

return {
  json: {
    workflow_run_id: $('Build Proposal Payload').item.json.workflow_run_id,
    proposal_id: response?.proposal_id ?? proposal.proposal_id,
    decision_id: response?.decision_id ?? null,
    decision: normalizedDecision,
    http_status: statusCode,
    gate_timestamp: response?.decision_timestamp ?? null,
    reason_code: response?.reason_code ?? null,
    reason_detail: response?.reason_detail ?? null,
    risk_level: response?.risk_level ?? null,
    approval_required_from: response?.approval_required_from ?? null,
    approval_queue_id: response?.approval_queue_id ?? null,
    target_system: proposal.target_system,
    action_class: proposal.action_class,
    payload_hash: proposal.payload_hash,
    error_body: validDecision ? null : response,
    stop_reason: stopReason,
    intended_mutation_payload: $('Build Proposal Payload').item.json.intended_mutation_payload,
  },
};
```

If the HTTP node surfaces timeout or transport failure separately, map that item
to the same fail-closed evidence shape before the Switch node. Preserve proposal
metadata from `Build Proposal Payload` even when the gate response is missing:

```json
{
  "workflow_run_id": "{{$('Build Proposal Payload').item.json.workflow_run_id}}",
  "proposal_id": "{{$('Build Proposal Payload').item.json.proposal.proposal_id}}",
  "decision_id": null,
  "decision": "ERROR",
  "http_status": null,
  "gate_timestamp": null,
  "reason_code": null,
  "reason_detail": null,
  "risk_level": null,
  "approval_required_from": null,
  "approval_queue_id": null,
  "target_system": "{{$('Build Proposal Payload').item.json.proposal.target_system}}",
  "action_class": "{{$('Build Proposal Payload').item.json.proposal.action_class}}",
  "payload_hash": "{{$('Build Proposal Payload').item.json.proposal.payload_hash}}",
  "error_body": "{{$json}}",
  "stop_reason": "Approval Gate timeout or transport error",
  "intended_mutation_payload": "{{$('Build Proposal Payload').item.json.intended_mutation_payload}}"
}
```

### Node 5 - Switch Node: Branch by Decision

Node type: `Switch`

Value to check: `{{$json.decision}}`

Rules:

- Equals `ALLOW` -> ALLOW branch
- Equals `NEEDS_APPROVAL` -> NEEDS_APPROVAL branch
- Equals `DENY` -> DENY branch
- Fallback/default -> ERROR branch

### Node 6A - ALLOW Branch: Execute Safe CRM Update

For local dogfood, use a mock CRM update first. A safe mock can be a Set node,
local webhook, or a test-only CRM endpoint.

Required behavior:

- Execute the CRM mutation only in this branch.
- Use `{{$json.intended_mutation_payload}}` as the mutation source.
- Log the complete evidence record below with `workflow_status=executed`.

Evidence record:

```json
{
  "workflow_status": "executed",
  "workflow_run_id": "{{$json.workflow_run_id}}",
  "proposal_id": "{{$json.proposal_id}}",
  "decision_id": "{{$json.decision_id}}",
  "decision": "{{$json.decision}}",
  "reason_code": "{{$json.reason_code}}",
  "reason_detail": "{{$json.reason_detail}}",
  "risk_level": "{{$json.risk_level}}",
  "approval_required_from": "{{$json.approval_required_from}}",
  "approval_queue_id": "{{$json.approval_queue_id}}",
  "target_system": "{{$json.target_system}}",
  "action_class": "{{$json.action_class}}",
  "payload_hash": "{{$json.payload_hash}}",
  "http_status": "{{$json.http_status}}",
  "gate_timestamp": "{{$json.gate_timestamp}}"
}
```

Optional outcome call after the safe mutation succeeds:

- Method: `POST`
- URL:
  `http://127.0.0.1:8100/v1/gate/proposals/{{$json.proposal_id}}/outcome`
- Headers:
  - `Authorization`: `Bearer {{$env.FLOWBIZ_GATE_API_KEY}}`
  - `Content-Type`: `application/json`
- Body:

```json
{
  "outcome": "executed",
  "execution_timestamp": "{{$now}}"
}
```

### Node 6B - NEEDS_APPROVAL Branch: Mark Pending

Do not call CRM.

Write evidence to the selected workflow log store:

```json
{
  "workflow_status": "pending_approval",
  "workflow_run_id": "{{$json.workflow_run_id}}",
  "proposal_id": "{{$json.proposal_id}}",
  "decision_id": "{{$json.decision_id}}",
  "decision": "{{$json.decision}}",
  "reason_code": "{{$json.reason_code}}",
  "reason_detail": "{{$json.reason_detail}}",
  "risk_level": "{{$json.risk_level}}",
  "approval_queue_id": "{{$json.approval_queue_id}}",
  "approval_required_from": "{{$json.approval_required_from}}",
  "target_system": "{{$json.target_system}}",
  "action_class": "{{$json.action_class}}",
  "payload_hash": "{{$json.payload_hash}}",
  "http_status": "{{$json.http_status}}",
  "gate_timestamp": "{{$json.gate_timestamp}}"
}
```

### Node 6C - DENY Branch: Mark Blocked

Do not call CRM.

Write evidence to the selected workflow log store:

```json
{
  "workflow_status": "blocked",
  "workflow_run_id": "{{$json.workflow_run_id}}",
  "proposal_id": "{{$json.proposal_id}}",
  "decision_id": "{{$json.decision_id}}",
  "decision": "{{$json.decision}}",
  "reason_code": "{{$json.reason_code}}",
  "reason_detail": "{{$json.reason_detail}}",
  "risk_level": "{{$json.risk_level}}",
  "approval_queue_id": "{{$json.approval_queue_id}}",
  "approval_required_from": "{{$json.approval_required_from}}",
  "target_system": "{{$json.target_system}}",
  "action_class": "{{$json.action_class}}",
  "payload_hash": "{{$json.payload_hash}}",
  "http_status": "{{$json.http_status}}",
  "gate_timestamp": "{{$json.gate_timestamp}}"
}
```

### Node 6D - ERROR Branch: Fail Closed

Do not call CRM.

Write evidence to the selected workflow log store:

```json
{
  "workflow_status": "gate_error_fail_closed",
  "workflow_run_id": "{{$json.workflow_run_id}}",
  "proposal_id": "{{$json.proposal_id}}",
  "decision_id": "{{$json.decision_id}}",
  "decision": "{{$json.decision}}",
  "reason_code": "{{$json.reason_code}}",
  "reason_detail": "{{$json.reason_detail}}",
  "risk_level": "{{$json.risk_level}}",
  "approval_queue_id": "{{$json.approval_queue_id}}",
  "approval_required_from": "{{$json.approval_required_from}}",
  "target_system": "{{$json.target_system}}",
  "action_class": "{{$json.action_class}}",
  "payload_hash": "{{$json.payload_hash}}",
  "http_status": "{{$json.http_status}}",
  "gate_timestamp": "{{$json.gate_timestamp}}",
  "stop_reason": "{{$json.stop_reason}}",
  "error_body": "{{$json.error_body}}"
}
```

### Evidence/Logging Node

Use one logging node per branch or one shared logging sub-workflow. The minimum
fields are:

- `workflow_run_id`
- `proposal_id`
- `decision_id`
- `decision`
- `reason_code`
- `reason_detail`
- `risk_level`
- `approval_required_from`
- `approval_queue_id`
- `target_system`
- `action_class`
- `payload_hash`
- `http_status`
- `gate_timestamp`
- `workflow_status`

Do not log raw contact PII.

## Make.com Implementation

### Module 1 - Trigger

Use `Webhooks > Custom webhook` for integration tests or `Tools > Run once` with
sample JSON for manual dry runs.

Expected input fields:

- `event_id`
- `contact_id`
- `action_class`
- `target_system`
- `target_scope`
- `mutation_type`
- `payload_summary`
- `mutation_payload`

### Module 2 - Build JSON Body

Use `JSON > Create JSON` or a mapping module.

Map:

- `proposal_id`: `make-contact-update-{{executionId}}`
- `connector_id`: `dogfood-n8n`
- `action_class`: trigger `action_class`, default `crm.contact.update`
- `target_system`: trigger `target_system`, default `hubspot-prod`
- `target_scope.type`: trigger `target_scope.type`, default `single`
- `target_scope.estimated_record_count`: trigger
  `target_scope.estimated_record_count`, default `1`
- `mutation_type`: trigger `mutation_type`, default `update`
- `payload_summary`: trigger `payload_summary`, default
  `Update one contact from validated workflow trigger`
- `payload_hash`: SHA-256 hex of the intended mutation payload
- `triggering_signal.source`: `crm_webhook`
- `triggering_signal.signal_id`: trigger `event_id`
- `triggering_signal.signal_timestamp`: current timestamp
- `submitted_at`: current timestamp
- `requested_by`: `dogfood-n8n`

If SHA-256 is not available as a native Make function in the scenario, compute
the hash in a small code/helper module or precompute it upstream before this
workflow. Do not replace the hash with raw payload details.

Use the same Make scenario for all three decision fixtures by changing only the
trigger input:

- ALLOW: `action_class=crm.contact.update`, `mutation_type=update`,
  `target_scope.type=single`, `target_scope.estimated_record_count=1`
- NEEDS_APPROVAL: `action_class=crm.campaign.send`, `mutation_type=send`,
  `target_scope.type=bulk`, `target_scope.estimated_record_count=847`
- DENY: `action_class=crm.deal.status_change`,
  `mutation_type=status_change`, `target_scope.type=single`,
  `target_scope.estimated_record_count=1`

### Module 3 - HTTP: Make a Request

Module: `HTTP > Make a request`

Configuration:

- Method: `POST`
- URL for local/self-hosted Make runner:
  `http://127.0.0.1:8100/v1/gate/proposals`
- URL for Make SaaS: use a non-production public dev URL or tunnel that reaches
  the local Approval Gate. Do not use production for this dogfood dry run.
- Headers:
  - `Authorization`: `Bearer {{FLOWBIZ_GATE_API_KEY}}`
  - `Content-Type`: `application/json`
- Body type: `Raw`
- Content type: `JSON (application/json)`
- Request content: JSON from Module 2
- Parse response: `Yes`
- Timeout: `10s`

### Module 4 - HTTP Error Handler: Fail-Closed Evidence

Attach an error handler route to Module 3, or the equivalent Make configuration
for module failure handling. This is required because timeout, transport, and
parse failures may stop the scenario before the normal Router receives a bundle.

The error handler must not call CRM. It must convert the module failure into the
same evidence shape used by the ERROR route:

- `workflow_status=gate_error_fail_closed`
- `workflow_run_id`
- `proposal_id`
- `decision_id=null`
- `decision=ERROR`
- `reason_code=null`
- `reason_detail=null`
- `risk_level=null`
- `approval_required_from=null`
- `approval_queue_id=null`
- `target_system`
- `action_class`
- `payload_hash`
- `http_status=null`
- `gate_timestamp=null`
- `error_body`
- `timeout` or transport failure detail
- `malformed_response` if response parsing failed
- `stop_reason=Approval Gate timeout, transport error, or parse failure`

After writing this evidence record, stop the route. Do not reconnect it to the
ALLOW/NEEDS_APPROVAL/DENY Router.

### Module 5 - Router

Create four routes with filters:

- ALLOW route: HTTP status is `200` and `body.decision` equals `ALLOW`
- NEEDS_APPROVAL route: HTTP status is `200` and `body.decision` equals
  `NEEDS_APPROVAL`
- DENY route: HTTP status is `200` and `body.decision` equals `DENY`
- ERROR route: HTTP status is not `200`, timeout, parse error, missing
  `body.decision`, or decision is not one of `ALLOW`, `NEEDS_APPROVAL`, `DENY`

### ALLOW Route

Execute only the safe test CRM update or mock CRM update.

Then write evidence:

- `workflow_run_id`
- `proposal_id`
- `decision_id`
- `decision`
- `reason_code`
- `reason_detail`
- `risk_level`
- `approval_required_from`
- `approval_queue_id`
- `target_system`
- `action_class`
- `payload_hash`
- `http_status`
- `gate_timestamp`
- `workflow_status=executed`

Optional: call the outcome endpoint with `outcome=executed` after the mutation
succeeds.

### NEEDS_APPROVAL Route

Do not update CRM.

Write evidence:

- `workflow_status=pending_approval`
- `workflow_run_id`
- `proposal_id`
- `decision_id`
- `decision`
- `reason_code`
- `reason_detail`
- `risk_level`
- `approval_queue_id`
- `approval_required_from`
- `target_system`
- `action_class`
- `payload_hash`
- `http_status`
- `gate_timestamp`

### DENY Route

Do not update CRM.

Write evidence:

- `workflow_status=blocked`
- `workflow_run_id`
- `proposal_id`
- `decision_id`
- `decision`
- `reason_code`
- `reason_detail`
- `risk_level`
- `approval_required_from`
- `approval_queue_id`
- `target_system`
- `action_class`
- `payload_hash`
- `http_status`
- `gate_timestamp`

### ERROR Route

Do not update CRM.

Write evidence:

- `workflow_status=gate_error_fail_closed`
- `workflow_run_id`
- `proposal_id`
- `decision_id`
- `decision`
- `reason_code`
- `reason_detail`
- `risk_level`
- `approval_required_from`
- `approval_queue_id`
- `target_system`
- `action_class`
- `payload_hash`
- `http_status`
- `gate_timestamp`
- `error_body`
- `timeout`
- `malformed_response`
- `stop_reason`

## Sample Proposal Payload

```json
{
  "proposal_id": "n8n-contact-update-{{$execution.id}}",
  "connector_id": "dogfood-n8n",
  "action_class": "crm.contact.update",
  "target_system": "hubspot-prod",
  "target_scope": {
    "type": "single",
    "estimated_record_count": 1
  },
  "mutation_type": "update",
  "payload_summary": "Update one contact from validated workflow trigger",
  "payload_hash": "<sha256 hex of intended CRM update payload>",
  "triggering_signal": {
    "source": "crm_webhook",
    "signal_id": "{{$json.event_id}}",
    "signal_timestamp": "{{$now}}"
  },
  "submitted_at": "{{$now}}",
  "requested_by": "dogfood-n8n"
}
```

## Decision Handling Contract

### ALLOW

- Continue to CRM mutation.
- Log `proposal_id`, `decision_id`, `decision`, and `risk_level`.
- Also log the minimum evidence fields listed in the Evidence/Logging Node
  section.
- Optional: record outcome if the existing endpoint is available:
  `POST /v1/gate/proposals/{proposal_id}/outcome`.

### NEEDS_APPROVAL

- Do not update CRM.
- Log `proposal_id`, `decision_id`, `approval_queue_id`,
  `approval_required_from`, and `reason_detail`.
- Also log the minimum evidence fields listed in the Evidence/Logging Node
  section.
- Mark workflow item pending.

### DENY

- Do not update CRM.
- Log `proposal_id`, `decision_id`, `reason_code`, `reason_detail`, and
  `risk_level`.
- Also log the minimum evidence fields listed in the Evidence/Logging Node
  section.
- Mark workflow item blocked.

### ERROR

- Do not update CRM.
- Log HTTP status, error body, timeout, or malformed response.
- Also log the minimum evidence fields listed in the Evidence/Logging Node
  section where available.
- Fail closed.

## Test Checklist

- [ ] Gate health returns `200`.
- [ ] ALLOW fixture continues to mock CRM update.
- [ ] NEEDS_APPROVAL fixture does not call CRM update.
- [ ] DENY fixture does not call CRM update.
- [ ] Timeout does not call CRM update.
- [ ] Non-200 does not call CRM update.
- [ ] Unknown decision does not call CRM update.
- [ ] DB audit row exists per proposal.
- [ ] Workflow run stores `proposal_id` and `decision_id`.

## Local Dry Run Plan

1. Seed dogfood connector and policies:

   ```powershell
   python scripts\seed_approval_gate_dogfood.py
   ```

2. Start the API locally:

   ```powershell
   python -m uvicorn apps.platform_api.main:app --host 127.0.0.1 --port 8100
   ```

3. Confirm health:

   ```powershell
   curl.exe -sS -w "`nHTTP_STATUS:%{http_code}`n" http://127.0.0.1:8100/healthz
   ```

4. Set the workflow secret:

   ```powershell
   $env:FLOWBIZ_GATE_API_KEY="dogfood-gate-key-rotate-me-7f3a9c21b8"
   ```

5. Run n8n/Make test with an ALLOW payload:
   `action_class=crm.contact.update`, `mutation_type=update`,
   `target_scope.type=single`, `target_scope.estimated_record_count=1`.

6. Run n8n/Make test with a NEEDS_APPROVAL payload:
   `action_class=crm.campaign.send`, `mutation_type=send`,
   `target_scope.type=bulk`, `target_scope.estimated_record_count=847`.

7. Run n8n/Make test with a DENY payload:
   `action_class=crm.deal.status_change`, `mutation_type=status_change`,
   `target_scope.type=single`, `target_scope.estimated_record_count=1`.

8. Query DB for audit evidence:

   ```powershell
   @'
   import sqlite3

   ids = [
       "n8n-dogfood-<allow-run-id>",
       "n8n-dogfood-<needs-approval-run-id>",
       "n8n-dogfood-<deny-run-id>",
   ]
   conn = sqlite3.connect("platform_data/approval_gate.db")
   conn.row_factory = sqlite3.Row
   for proposal_id in ids:
       row = conn.execute(
           """
           SELECT p.proposal_id, d.decision_id, d.decision, d.reason_code,
                  d.risk_level, a.audit_id, a.decision AS audit_decision
           FROM approval_proposals p
           JOIN approval_decisions d ON d.proposal_id = p.proposal_id
           JOIN approval_audit_events a ON a.proposal_id = p.proposal_id
           WHERE p.proposal_id = ?
           """,
           (proposal_id,),
       ).fetchone()
       print(dict(row) if row else {"missing": proposal_id})
   '@ | python -
   ```

9. Confirm no mutation happened except the ALLOW branch. For local dogfood, this
   should mean exactly one mock CRM update record or one safe test endpoint call.

## Go/No-Go Criteria

GO only if:

- ALLOW executes the expected safe mutation or mock mutation.
- NEEDS_APPROVAL, DENY, and ERROR never execute mutation.
- Evidence is logged.
- DB audit rows exist.

NO-GO if:

- Any unsafe branch mutates CRM.
- Any error path continues.
- Decision is missing but workflow continues.
- Evidence is incomplete.
