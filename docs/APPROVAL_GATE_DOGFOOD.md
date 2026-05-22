# Approval Gate — Dogfood Runbook

Exercise the Safe Automation Approval Gate (Phase 1) end-to-end on your own
machine, before wiring it to a real n8n/Make workflow. Single-operator use.

This runbook covers three decisions: **ALLOW**, **NEEDS_APPROVAL**, and **DENY**
(deny-by-default), plus reading the audit log.

> Phase 1 has no UI and no callback delivery. NEEDS_APPROVAL is returned and
> stored, but there is no human approve/reject flow yet (that is Phase 2). The
> dogfood goal is to confirm the gate evaluates, decides, and audits correctly
> against your own automation traffic.

---

## 1. Seed a connector + policies

From the repo root:

```bash
python scripts/seed_approval_gate_dogfood.py
```

This creates (idempotent):
- connector `dogfood-n8n` with api key `dogfood-gate-key-rotate-me-7f3a9c21b8`
  (override with `DOGFOOD_GATE_API_KEY`)
- policy `pol-contact-update` — `crm.contact.update`, auto-allow LOW/MEDIUM
- policy `pol-campaign-send` — `crm.campaign.send`, approval at HIGH/CRITICAL
- `crm.deal.status_change` is allowed for the connector but has **no policy**
  (used for the deny-by-default demo)

The script prints the resolved DB path (default `platform_data/approval_gate.db`).

---

## 2. Start the platform locally

```bash
uvicorn apps.platform_api.main:app --host 0.0.0.0 --port 8100 --reload
```

Gate listens at `http://localhost:8100`. Health check:

```bash
curl.exe http://localhost:8100/healthz
```

---

## 3. Scenario A — ALLOW (low-risk single contact update)

Save as `proposal_allow.json`:

```json
{
  "proposal_id": "demo-allow-001",
  "connector_id": "dogfood-n8n",
  "action_class": "crm.contact.update",
  "target_system": "hubspot-prod",
  "target_scope": { "type": "single", "estimated_record_count": 1 },
  "mutation_type": "update",
  "payload_summary": "Update phone number for one contact",
  "payload_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "triggering_signal": {
    "source": "hubspot_contact_form",
    "signal_id": "evt-allow-1",
    "signal_timestamp": "2026-05-22T03:00:00Z"
  },
  "submitted_at": "2026-05-22T03:00:01Z",
  "requested_by": "ops-bot"
}
```

```bash
curl.exe -s -X POST http://localhost:8100/v1/gate/proposals ^
  -H "Authorization: Bearer dogfood-gate-key-rotate-me-7f3a9c21b8" ^
  -H "Content-Type: application/json" ^
  -d "@proposal_allow.json"
```

Expected: `"decision": "ALLOW"`, `"risk_level": "LOW"`, `reason_code` `POLICY_ALLOWED`.

---

## 4. Scenario B — NEEDS_APPROVAL (bulk campaign send)

Save as `proposal_needs_approval.json`:

```json
{
  "proposal_id": "demo-approval-001",
  "connector_id": "dogfood-n8n",
  "action_class": "crm.campaign.send",
  "target_system": "hubspot-prod",
  "target_scope": { "type": "bulk", "estimated_record_count": 847 },
  "mutation_type": "send",
  "payload_summary": "Enroll 847 contacts in a 3-email follow-up sequence",
  "payload_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "triggering_signal": {
    "source": "hubspot_deal_stage_webhook",
    "signal_id": "hs_evt_92847",
    "signal_timestamp": "2026-05-22T03:05:00Z"
  },
  "submitted_at": "2026-05-22T03:05:01Z",
  "requested_by": "dogfood-n8n"
}
```

```bash
curl.exe -s -X POST http://localhost:8100/v1/gate/proposals ^
  -H "Authorization: Bearer dogfood-gate-key-rotate-me-7f3a9c21b8" ^
  -H "Content-Type: application/json" ^
  -d "@proposal_needs_approval.json"
```

Expected: `"decision": "NEEDS_APPROVAL"`, `"risk_level": "HIGH"`,
`approval_required_from` `founder`. Risk = bulk(+2) + send(+2) + >100 records(+2)
+ automated requester(+1) = 7 → HIGH.

---

## 5. Scenario C — DENY (deny-by-default, no policy)

Save as `proposal_deny.json`:

```json
{
  "proposal_id": "demo-deny-001",
  "connector_id": "dogfood-n8n",
  "action_class": "crm.deal.status_change",
  "target_system": "hubspot-prod",
  "target_scope": { "type": "single", "estimated_record_count": 1 },
  "mutation_type": "status_change",
  "payload_summary": "Move deal to Closed-Won",
  "payload_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "triggering_signal": {
    "source": "hubspot_deal_webhook",
    "signal_id": "evt-deny-1",
    "signal_timestamp": "2026-05-22T03:10:00Z"
  },
  "submitted_at": "2026-05-22T03:10:01Z",
  "requested_by": "dogfood-n8n"
}
```

```bash
curl.exe -s -X POST http://localhost:8100/v1/gate/proposals ^
  -H "Authorization: Bearer dogfood-gate-key-rotate-me-7f3a9c21b8" ^
  -H "Content-Type: application/json" ^
  -d "@proposal_deny.json"
```

Expected: `"decision": "DENY"`, `reason_code` `NO_MATCHING_POLICY`. The action
class is permitted for the connector but no policy explicitly allows it — so the
deny-by-default invariant returns DENY.

---

## 6. Read a stored decision

```bash
curl.exe -s http://localhost:8100/v1/gate/proposals/demo-approval-001/decision ^
  -H "Authorization: Bearer dogfood-gate-key-rotate-me-7f3a9c21b8"
```

---

## 7. Read the audit log

Phase 1 has no audit query API (that is Phase 3). Read the audit table directly:

```bash
sqlite3 platform_data/approval_gate.db ^
  "SELECT timestamp, action_class, decision, reason_code, risk_level FROM approval_audit_events ORDER BY timestamp;"
```

Every decision — including DENY — must have exactly one audit row. That row,
plus the proposal snapshot stored with it, is your proof and rollback reference.

---

## 8. Notes

- `payload_hash` must be a 64-character hex string (SHA-256 digest). The
  placeholders above are valid hex; in real use, hash your actual action payload.
- The gate never executes the mutation. ALLOW means "your tool may proceed" —
  the connector performs the action in the target system after reading the decision.
- This is single-operator dogfood. Any registered connector can read any
  decision in Phase 1 (no per-connector authorization yet) — fine for one
  operator, must be hardened before multi-tenant use.
- Rotate `DOGFOOD_GATE_API_KEY` before sharing this environment.
