# Dogfood Workflow 1 Dry Run Pack - CRM Contact Update Approval

## Purpose

This dry run proves Pattern A sync behavior before any real CRM mutation is
connected.

Use only a mock CRM update or mock logging node. The Approval Gate is exercised
through the real HTTP endpoint, but the workflow must not mutate a live CRM.

Core proof:

```text
trigger -> proposal -> Approval Gate decision -> branch -> mock mutation or stop -> evidence
```

Only `ALLOW` may reach the mock CRM update. `NEEDS_APPROVAL`, `DENY`, timeout,
non-200, malformed response, and unknown decision must stop the workflow and log
fail-closed evidence.

## Required Environment

- FlowBiz Approval Gate API running locally.
- Dogfood seed data loaded with:

  ```powershell
  python scripts\seed_approval_gate_dogfood.py
  ```

- Local API started with:

  ```powershell
  python -m uvicorn apps.platform_api.main:app --host 127.0.0.1 --port 8100
  ```

- n8n/Make secret or environment variable set:

  ```text
  FLOWBIZ_GATE_API_KEY=dogfood-gate-key-rotate-me-7f3a9c21b8
  ```

- Mock CRM endpoint or mock logging node configured.
- No live CRM credential in the dry-run workflow.
- No live CRM mutation.
- For Make SaaS, use a non-production public dev URL or tunnel to the local API.
  Do not point Make SaaS at production for this dry run.

## Test Cases

### A. ALLOW

Input fields:

```json
{
  "event_id": "dryrun-allow-001",
  "proposal_prefix": "dryrun-allow",
  "action_class": "crm.contact.update",
  "target_system": "hubspot-prod",
  "target_scope": {
    "type": "single",
    "estimated_record_count": 1
  },
  "mutation_type": "update",
  "payload_summary": "Update one contact from validated workflow trigger",
  "mutation_payload": {
    "contact_id": "mock-contact-001",
    "fields": {
      "phone": "+66000000000"
    }
  }
}
```

Expected:

- Approval Gate returns HTTP `200`.
- Decision is `ALLOW`.
- Mock CRM update runs exactly once.
- Evidence includes `proposal_id`, `decision_id`, `decision=ALLOW`, and
  `risk_level=LOW`.
- DB audit row exists for the tested `proposal_id`.

### B. NEEDS_APPROVAL

Input fields:

```json
{
  "event_id": "dryrun-needs-approval-001",
  "proposal_prefix": "dryrun-needs-approval",
  "action_class": "crm.campaign.send",
  "target_system": "hubspot-prod",
  "target_scope": {
    "type": "bulk",
    "estimated_record_count": 847
  },
  "mutation_type": "send",
  "payload_summary": "Send campaign to a bulk contact segment",
  "mutation_payload": {
    "campaign_id": "mock-campaign-001",
    "estimated_recipient_count": 847
  }
}
```

Expected:

- Approval Gate returns HTTP `200`.
- Decision is `NEEDS_APPROVAL`.
- Mock CRM update does not run.
- Pending evidence is logged with `approval_queue_id`,
  `approval_required_from`, and `reason_detail`.
- DB audit row exists for the tested `proposal_id`.

### C. DENY

Input fields:

```json
{
  "event_id": "dryrun-deny-001",
  "proposal_prefix": "dryrun-deny",
  "action_class": "crm.deal.status_change",
  "target_system": "hubspot-prod",
  "target_scope": {
    "type": "single",
    "estimated_record_count": 1
  },
  "mutation_type": "status_change",
  "payload_summary": "Change one deal status",
  "mutation_payload": {
    "deal_id": "mock-deal-001",
    "new_status": "closed_won"
  }
}
```

Expected:

- Approval Gate returns HTTP `200`.
- Decision is `DENY`.
- Mock CRM update does not run.
- Blocked evidence is logged with `reason_code`, `reason_detail`, and
  `risk_level`.
- DB audit row exists for the tested `proposal_id`.

### D. ERROR / Timeout / Non-200 / Malformed Response / Unknown Decision

Run at least one controlled error case before connecting any real CRM action.

Suggested safe fixtures:

- Timeout or transport error: point the HTTP node to an unused local port such
  as `http://127.0.0.1:8199/v1/gate/proposals`.
- Non-200: use an invalid `FLOWBIZ_GATE_API_KEY` and expect HTTP `401`.
- Malformed response: point the HTTP node to a mock endpoint returning non-JSON.
- Unknown decision: point the HTTP node to a mock endpoint returning HTTP `200`
  with `{"decision":"UNKNOWN"}`.

Expected:

- Mock CRM update does not run.
- Fail-closed evidence is logged.
- `decision` is normalized to `ERROR` when the workflow reaches its error
  branch.
- `http_status` is captured for non-200 responses.
- `http_status=null` and `gate_timestamp=null` are captured for timeout or
  transport failure.
- DB audit row exists only for valid Approval Gate calls that reached
  `/v1/gate/proposals`; timeout to an unused port or mock malformed endpoints
  will not create a gate audit row.

## Evidence Checklist

Capture this for every run:

- [ ] n8n/Make execution ID
- [ ] `proposal_id`
- [ ] HTTP status
- [ ] `decision`
- [ ] `decision_id`
- [ ] `reason_code`
- [ ] `reason_detail`
- [ ] `risk_level`
- [ ] Whether mock CRM update ran
- [ ] DB audit row evidence
- [ ] Screenshot path or note placeholder

Recommended evidence table:

| Case | Execution ID | Proposal ID | HTTP status | Decision | Decision ID | Mock CRM update ran | DB audit row | Screenshot / note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ALLOW |  |  |  |  |  |  |  |  |
| NEEDS_APPROVAL |  |  |  |  |  |  |  |  |
| DENY |  |  |  |  |  |  |  |  |
| ERROR |  |  |  |  |  |  |  |  |

## DB Verification Commands

Set the tested proposal IDs in the command before running it.

```powershell
$env:FLOWBIZ_DRYRUN_PROPOSAL_IDS = "dryrun-allow-<execution-id>,dryrun-needs-approval-<execution-id>,dryrun-deny-<execution-id>"
```

Query `approval_proposals`, `approval_decisions`, and
`approval_audit_events`:

```powershell
@'
import os
import sqlite3

raw_ids = os.environ.get("FLOWBIZ_DRYRUN_PROPOSAL_IDS", "")
proposal_ids = [item.strip() for item in raw_ids.split(",") if item.strip()]
if not proposal_ids:
    raise SystemExit("Set FLOWBIZ_DRYRUN_PROPOSAL_IDS first")

conn = sqlite3.connect("platform_data/approval_gate.db")
conn.row_factory = sqlite3.Row

for proposal_id in proposal_ids:
    print(f"proposal_id={proposal_id}")

    proposal = conn.execute(
        """
        SELECT proposal_id, connector_id, action_class, target_system,
               mutation_type, submitted_at, received_at
        FROM approval_proposals
        WHERE proposal_id = ?
        """,
        (proposal_id,),
    ).fetchone()
    print("  approval_proposals:", dict(proposal) if proposal else None)

    decision = conn.execute(
        """
        SELECT decision_id, proposal_id, decision, reason_code, reason_detail,
               risk_level, approval_required_from, approval_queue_id,
               decision_timestamp
        FROM approval_decisions
        WHERE proposal_id = ?
        """,
        (proposal_id,),
    ).fetchone()
    print("  approval_decisions:", dict(decision) if decision else None)

    audits = conn.execute(
        """
        SELECT audit_id, event_type, proposal_id, decision_id, timestamp,
               action_class, decision, reason_code, risk_level
        FROM approval_audit_events
        WHERE proposal_id = ?
        ORDER BY timestamp ASC, audit_id ASC
        """,
        (proposal_id,),
    ).fetchall()
    print("  approval_audit_events:", [dict(row) for row in audits])
    print()
'@ | python -
```

Quick count check:

```powershell
@'
import os
import sqlite3

raw_ids = os.environ.get("FLOWBIZ_DRYRUN_PROPOSAL_IDS", "")
proposal_ids = [item.strip() for item in raw_ids.split(",") if item.strip()]
conn = sqlite3.connect("platform_data/approval_gate.db")

for proposal_id in proposal_ids:
    counts = {}
    for table in [
        "approval_proposals",
        "approval_decisions",
        "approval_audit_events",
    ]:
        counts[table] = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()[0]
    print(proposal_id, counts)
'@ | python -
```

Expected for valid gate calls:

- `approval_proposals=1`
- `approval_decisions=1`
- `approval_audit_events=1`

Expected for timeout to unused port or mock malformed endpoint:

- No Approval Gate DB row, because the real gate was not reached.
- Workflow evidence must still show fail-closed behavior.

## Pass/Fail Criteria

PASS only if:

- ALLOW is the only path that reaches mock CRM update.
- NEEDS_APPROVAL never mutates.
- DENY never mutates.
- ERROR never mutates.
- DB audit exists for valid gate calls.
- Workflow logs enough evidence for each branch.

FAIL if:

- Any unsafe branch reaches mutation.
- Any error path continues.
- Missing decision continues.
- Evidence is incomplete.

