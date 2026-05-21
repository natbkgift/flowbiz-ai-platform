# Safe Automation Approval Layer v0 — Product Spec

**Status:** Draft v0.1 — 2026-05-21
**Branch:** `feat/safe-automation-approval-layer-v0`
**Owner:** FlowBiz Platform

---

## 1. Purpose & Positioning

**Stop your business automations from doing expensive things you didn't mean to approve.**

You use automation tools — Make, n8n, Zapier, HubSpot Workflows, or your own webhooks — to move fast. That's good. But some of those automations touch things that can hurt: bulk-update a thousand CRM contacts, fire a campaign to the wrong segment, delete a deal pipeline stage, move a contract to a wrong status. When they go wrong, they go wrong at speed and at scale.

FlowBiz adds a **decision checkpoint** that sits between your automation tool and the action it wants to take. Before any risky action executes, FlowBiz evaluates it against your business rules, checks whether the evidence for the action is complete, and returns one of three answers:

- **ALLOW** — the action is within policy; the tool may proceed
- **DENY** — the action is outside policy; the tool must stop
- **NEEDS_APPROVAL** — the action requires a human decision before proceeding

FlowBiz does not execute the action. It evaluates the proposal and records the decision. The tool that asked retains execution authority — and responsibility — after receiving the answer.

Every decision is logged with the full context that produced it. That log is your proof, your audit trail, and your rollback reference.

---

## 2. Problem

### What goes wrong with automation today

Automation tools are designed to act, not to evaluate. They have no concept of:

- Whether an action affects 1 record or 10,000
- Whether the initiating signal is trustworthy or anomalous
- Whether the proposed change has been seen and approved by the responsible person
- Whether a rollback is even possible if the action turns out to be wrong

Teams respond to this by either (a) keeping automations conservative and underusing them, or (b) living with occasional large mistakes and cleaning them up manually. Neither is acceptable at scale.

### Specific failure modes this spec targets

| Failure mode | Example |
|---|---|
| Bulk mutation without scope confirmation | n8n updates 8,000 contacts based on a mis-tagged filter |
| Action from bad signal | Webhook fires because a test event leaked into production |
| Unreviewed high-risk action | Contract status moved to "Closed-Won" by automation, not sales rep |
| No record of who approved what | Compliance audit cannot reconstruct why a campaign fired |
| No rollback guidance | After bulk action, team doesn't know what to revert |

---

## 3. Scope — v0

v0 covers the decision gate and audit trail only. Specifically:

- **Action Proposal intake** — accept a structured proposal from an external connector
- **Policy evaluation** — evaluate the proposal against declared business rules (deny-by-default)
- **Risk scoring** — produce a risk signal based on scope, origin, and evidence quality
- **Decision response** — return ALLOW / DENY / NEEDS_APPROVAL with explanation
- **Approval queue** — hold NEEDS_APPROVAL proposals for human decision via FlowBiz Operator UI
- **Audit log** — record every proposal, evaluation, and decision with full payload and provenance
- **Rollback checklist generation** — for ALLOW decisions above a risk threshold, generate a structured rollback checklist bound to that decision record
- **Connector webhook pattern** — a defined contract for how Make/n8n/custom connectors call the gate and consume the decision

---

## 4. Non-goals — v0

The following are explicitly out of scope for v0:

- FlowBiz calling CRM, SCM, or any external business system API (see Section 14)
- Executing or scheduling any business action
- Building or managing business automation workflows
- Native integrations with HubSpot, Salesforce, Pipedrive, or any CRM
- Email sending, Slack notifications, or any communication action
- Billing, plan management, or usage metering
- Policy DSL editor or visual rule builder
- Multi-tenant isolation (v0 targets single operator context)
- Real-time streaming of approval decisions
- Mobile approval interface

---

## 5. Governance Lineage

The approval gate pattern generalizes directly from the frozen Git governance contracts in `flowbiz-ai-core`. The translation is exact:

| Git governance contract | Business automation equivalent |
|---|---|
| `BATCH_21` — Commit Provenance Binding: every proposed change must carry verified provenance before evaluation begins | Action Proposal must carry: source connector identity, triggering signal, payload hash, and timestamp before FlowBiz evaluates |
| `BATCH_24` — Override Audit Requirements: any bypass of a control requires a full audit record with authority reference | Any human override of a DENY decision requires: approver identity, reason, and timestamp bound to the original decision record |
| `BATCH_27` — Merge Authority Contract: only authorized actors can approve changes within defined scope boundaries | Approval authority is scoped: each policy rule names who may approve it, for what action class, and at what risk level |
| `BATCH_27` — Merge Eligibility Contract: a proposal is ineligible if evidence requirements are not met | An action proposal is ineligible for ALLOW if required evidence fields are absent or fail validation |
| `BATCH_13A` — Repo Eligibility Revision: defined which repo classes are subject to which gate controls | Action eligibility defines which action classes (by target system and mutation type) are subject to which policy rules in v0 |
| `BATCH_12A` — Observability Audit Envelope: every gate decision must be captured in a structured, persistent audit record | Every FlowBiz gate decision (including DENY and no-op evaluations) is written to the audit log before the response is returned |

The core invariant inherited from all of the above: **the gate is deny-by-default**. An action without a matching policy that explicitly permits it receives DENY, not ALLOW.

---

## 6. Action Schema

An **Action Proposal** is the unit of evaluation. External connectors submit proposals; FlowBiz evaluates them.

### Required fields

```json
{
  "proposal_id": "string — idempotency key, set by caller",
  "connector_id": "string — registered connector identity",
  "action_class": "string — category of action (see below)",
  "target_system": "string — which system would execute the mutation",
  "target_scope": {
    "type": "string — 'single' | 'bulk' | 'global'",
    "estimated_record_count": "integer — 0 if unknown"
  },
  "mutation_type": "string — 'create' | 'update' | 'delete' | 'status_change' | 'send' | 'other'",
  "payload_summary": "string — human-readable description of what the action would do",
  "payload_hash": "string — SHA-256 of the full action payload",
  "triggering_signal": {
    "source": "string — what caused this action to be proposed",
    "signal_id": "string — identifier of the triggering event",
    "signal_timestamp": "ISO8601"
  },
  "submitted_at": "ISO8601",
  "requested_by": "string — connector or user identity"
}
```

### Action class vocabulary (v0)

| Class | Examples |
|---|---|
| `crm.contact.update` | Update contact fields, merge contacts |
| `crm.contact.delete` | Archive or delete contacts |
| `crm.deal.status_change` | Move deal stage, close deal |
| `crm.campaign.send` | Enroll contacts in campaign, trigger email sequence |
| `workflow.trigger` | Start a downstream automation workflow |
| `data.export` | Export data to external destination |
| `config.change` | Modify automation configuration or business rules |

---

## 7. Policy Evaluation Contract

### Evaluation sequence

1. **Schema validation** — reject malformed proposals immediately (400)
2. **Connector authentication** — reject unregistered connectors (401)
3. **Action eligibility check** — if the action class is not in the active policy set, return DENY with code `NO_MATCHING_POLICY`
4. **Evidence validation** — check that required evidence fields for this action class are present and non-empty
5. **Risk scoring** — compute a risk signal (Section 8)
6. **Policy rule evaluation** — evaluate all applicable rules against the proposal and risk signal
7. **Decision** — resolve to ALLOW, DENY, or NEEDS_APPROVAL
8. **Audit write** — write the full decision record before returning the response
9. **Response** — return the decision to the caller

### Decision response schema

```json
{
  "proposal_id": "string — echoed from request",
  "decision": "ALLOW | DENY | NEEDS_APPROVAL",
  "decision_id": "string — FlowBiz-generated, stable reference for this decision",
  "decision_timestamp": "ISO8601",
  "reason_code": "string",
  "reason_detail": "string — human-readable explanation",
  "risk_level": "LOW | MEDIUM | HIGH | CRITICAL",
  "approval_required_from": "string | null — role or identity required if NEEDS_APPROVAL",
  "approval_queue_id": "string | null — populated if NEEDS_APPROVAL",
  "rollback_checklist_id": "string | null — populated if ALLOW and risk_level >= MEDIUM"
}
```

### Deny-by-default invariant

If no policy rule produces an explicit ALLOW, the decision is DENY. There is no implicit permission. A connector receiving DENY must stop; it must not retry the same proposal without modification.

---

## 8. Risk Signals

Risk scoring produces a single `risk_level` that informs both the policy decision and the rollback checklist generation.

### Inputs to risk scoring

| Signal | Weight driver |
|---|---|
| `target_scope.type = 'bulk'` | Elevated — bulk mutations are hard to reverse |
| `target_scope.estimated_record_count > 100` | Elevated — scale threshold |
| `target_scope.estimated_record_count > 1000` | Critical threshold |
| `mutation_type = 'delete'` | Elevated — destructive mutation |
| `mutation_type = 'send'` | Elevated — communications are irreversible |
| `triggering_signal.source` is test/staging connector in production context | Critical — signal origin mismatch |
| `payload_hash` matches a recently denied proposal | Elevated — retry of denied action |
| Action class is `config.change` | Elevated — configuration mutations have broad downstream effect |
| `requested_by` is an automated connector (not a human user) | Baseline elevation for all automated proposals |

### Risk levels

| Level | Default disposition |
|---|---|
| LOW | ALLOW if policy matches |
| MEDIUM | ALLOW with rollback checklist generated |
| HIGH | NEEDS_APPROVAL unless policy explicitly permits auto-allow |
| CRITICAL | DENY unless policy explicitly permits and approval is obtained |

---

## 9. Approval Queue

### Purpose

When FlowBiz returns NEEDS_APPROVAL, the proposal enters the Approval Queue. A human operator reviews the proposal in the FlowBiz Operator UI, sees the full context and risk signal, and makes one of two decisions: **Approve** or **Reject**.

### Queue record fields

- `approval_queue_id`
- `proposal_id` + `decision_id` (linked)
- `action_summary` (human-readable)
- `risk_level`
- `approval_required_from`
- `submitted_at`
- `expires_at` (proposals expire if not acted on within the configured window)
- `status`: `pending` | `approved` | `rejected` | `expired`

### After human decision

- **Approved**: FlowBiz creates a new decision record with `decision = ALLOW`, bound to the original `proposal_id` and the approver identity. The external connector must poll or receive a callback to retrieve the updated decision and then execute the action.
- **Rejected**: FlowBiz creates a new decision record with `decision = DENY`. The connector must not proceed.
- **Expired**: Treated as DENY.

### Override audit requirement (from BATCH_24 lineage)

Any approval of a proposal that was initially DENY (not just NEEDS_APPROVAL) must record:
- approver identity
- reason text (required, not optional)
- timestamp
- reference to the original DENY decision record

This override record is permanent and cannot be deleted.

---

## 10. Audit Log / Change Timeline

Every FlowBiz gate action produces a persistent audit record. No action is taken, no decision is returned, before the audit record is written.

### Audit record fields

```json
{
  "audit_id": "string",
  "event_type": "PROPOSAL_RECEIVED | DECISION_MADE | APPROVAL_REQUESTED | APPROVAL_GIVEN | APPROVAL_REJECTED | OVERRIDE_RECORDED | ROLLBACK_CHECKLIST_GENERATED",
  "proposal_id": "string",
  "decision_id": "string | null",
  "timestamp": "ISO8601",
  "actor": "string — connector_id or operator user_id",
  "action_class": "string",
  "target_system": "string",
  "target_scope": "object",
  "risk_level": "string",
  "decision": "string | null",
  "reason_code": "string | null",
  "payload_hash": "string",
  "full_proposal_snapshot": "object — full proposal at evaluation time"
}
```

### Audit guarantees (from BATCH_12A lineage)

- Audit records are append-only; existing records cannot be modified or deleted
- The audit write is synchronous with the gate response; a failure to write the audit record returns a 500 — the decision is not returned to the caller
- Audit records are queryable by `proposal_id`, `connector_id`, `action_class`, `target_system`, `decision`, and time range
- The Change Timeline view in the Operator UI surfaces the audit log as a readable timeline of what was proposed, decided, and by whom

---

## 11. Rollback Checklist Generator

For every ALLOW decision where `risk_level >= MEDIUM`, FlowBiz generates a structured rollback checklist bound to that decision.

### What the checklist contains

- `decision_id` — the ALLOW decision this checklist belongs to
- `action_summary` — what was approved
- `target_scope` — how many records, which system
- `estimated_reversal_steps` — ordered list of steps to undo the action, derived from the action class and mutation type
- `reversal_window` — estimated time window within which reversal is practical (action-class specific)
- `data_export_required` — boolean, true if a pre-action export is recommended
- `approver_contact` — who approved, for follow-up

### Checklist is advisory

The checklist is a reference document, not an execution plan. FlowBiz does not execute rollback operations. The operator uses the checklist to guide manual or tool-assisted reversal in the target system.

---

## 12. Connector Pattern

> **ADR reference:** The patterns in this section implement ADR Decision 4 (async-resume required for NEEDS_APPROVAL). See `docs/adr/ADR_SAFE_AUTOMATION_APPROVAL_GATE_RUNTIME.md` Section 2, Decision 4 for full rationale and alternatives considered.

### Pattern A — ALLOW and DENY (synchronous, inline)

ALLOW and DENY are returned synchronously within the same API call. The connector handles them inline in a single workflow step.

```
Step 1 — Submit and act
  Tool submits Action Proposal:
    POST /v1/gate/proposals
    Authorization: Bearer <connector_api_key>
    Body: Action Proposal (Section 6)

  FlowBiz responds synchronously:
    - ALLOW  → tool executes the action against the target system in this step
               then posts outcome:
               POST /v1/gate/proposals/{proposal_id}/outcome
               Body: { "outcome": "executed", "execution_timestamp": ISO8601 }
    - DENY   → tool stops; does not proceed
               POST /v1/gate/proposals/{proposal_id}/outcome
               Body: { "outcome": "aborted", "execution_timestamp": ISO8601 }
```

### Pattern B — NEEDS_APPROVAL (async-resume, two-step)

NEEDS_APPROVAL decisions require human action before the connector can proceed. Human response latency is unbounded relative to automation step timeouts (Make and n8n step timeouts range from 30 seconds to a few minutes depending on plan). A connector that blocks-polls within a single step will hit the step timeout before a human acts. **Blocking-poll is not a supported pattern for NEEDS_APPROVAL.**

The required pattern is async-resume:

```
Step A — Submit and complete immediately
  Tool submits Action Proposal:
    POST /v1/gate/proposals
    Authorization: Bearer <connector_api_key>
    Body: Action Proposal (Section 6)

  FlowBiz responds:
    { "decision": "NEEDS_APPROVAL", "proposal_id": "...", "approval_queue_id": "..." }

  Tool stores proposal_id in workflow state.
  Workflow step A completes immediately. No waiting.

[Human reviews proposal in FlowBiz Operator UI and approves or rejects.
 FlowBiz writes the final decision and notifies the connector.]

Step B — Resume on decision (triggered by callback or second automation trigger)
  Option 1 — Callback (preferred):
    FlowBiz calls the connector-registered callback_url with:
    { "proposal_id": "...", "decision": "ALLOW" | "DENY", "decision_id": "..." }
    The callback triggers Step B of the automation.

  Option 2 — Second trigger (for connectors without callback support):
    A separate Make scenario / n8n workflow is configured to fire when
    FlowBiz records a final decision. It reads the stored proposal_id
    from the first workflow's state and continues from there.

  In Step B, tool reads decision:
    - ALLOW  → tool executes the mutation in the target system
               then posts outcome to /v1/gate/proposals/{proposal_id}/outcome
    - DENY   → tool stops (proposal was rejected or expired)
               then posts outcome to /v1/gate/proposals/{proposal_id}/outcome
```

### Polling — status verification only

`GET /v1/gate/proposals/{proposal_id}/decision` is available for status verification (e.g., confirming the current state of a known proposal_id). It is **not** the primary wait mechanism for NEEDS_APPROVAL. Do not build a poll loop inside a single automation step expecting a human to respond within the step timeout.

### Connector registration

Each connector must be registered in FlowBiz before use:
- `connector_id` — stable identifier
- `connector_name` — human-readable
- `allowed_action_classes` — which action classes this connector may propose
- `api_key` — rotatable credential
- `callback_url` — optional; HTTPS endpoint FlowBiz will POST to when a NEEDS_APPROVAL decision resolves (approved, rejected, or expired). Required for Pattern B Option 1. If absent, the connector must use a second-trigger approach (Pattern B Option 2).

Unregistered connectors receive 401. Registered connectors proposing disallowed action classes receive DENY with code `CONNECTOR_ACTION_CLASS_NOT_PERMITTED`.

---

## 13. Demo Scenario

**Scenario:** An n8n workflow is triggered when a deal reaches "Proposal Sent" in HubSpot. The workflow automatically enrolls the contact in a 3-email follow-up sequence. The contact list for this trigger is broad — it matches 847 contacts.

### Without FlowBiz

n8n fires the campaign enrollment immediately. 847 contacts receive the first email within minutes. If the trigger condition was misconfigured (e.g., wrong pipeline filter), there is no checkpoint and no rollback path.

### With FlowBiz

1. n8n reaches the "enroll in campaign" step and submits an Action Proposal:
   - `action_class: crm.campaign.send`
   - `target_scope: { type: "bulk", estimated_record_count: 847 }`
   - `mutation_type: send`
   - `triggering_signal: { source: "hubspot_deal_stage_webhook", signal_id: "hs_evt_92847" }`

2. FlowBiz evaluates:
   - Risk scoring: `bulk` scope + `send` mutation type + >100 records → **HIGH**
   - Policy rule: `crm.campaign.send` at HIGH risk requires approval
   - Decision: **NEEDS_APPROVAL**

3. FlowBiz places the proposal in the Approval Queue and returns NEEDS_APPROVAL. The n8n Step A completes immediately, storing the `proposal_id` in workflow state. n8n does not poll or wait — a second n8n workflow (or a callback trigger) resumes execution when FlowBiz records the human decision.

4. The FlowBiz Operator UI shows the pending approval with full context: 847 contacts, follow-up sequence name, triggering deal stage, risk level HIGH.

5. The responsible operator reviews and either:
   - **Approves**: n8n receives ALLOW, executes the campaign enrollment, FlowBiz records the ALLOW with approver identity and generates a rollback checklist.
   - **Rejects**: n8n receives DENY, does not enroll contacts, FlowBiz records the rejection.

6. The audit log has a complete record: proposal submitted at T+0, NEEDS_APPROVAL at T+0, human decision at T+12min, outcome recorded at T+13min.

---

## 14. Runtime Boundary Statement

**This section defines the hard boundary of FlowBiz's runtime behavior. It is not aspirational — it is a constraint that the v0 implementation must enforce and must never cross.**

### What FlowBiz does

- Receives Action Proposals from external connectors
- Evaluates proposals against policy rules
- Scores risk based on proposal content
- Returns a decision: ALLOW, DENY, or NEEDS_APPROVAL
- Writes a complete audit record for every decision
- Holds NEEDS_APPROVAL proposals in the Approval Queue for human decision
- Generates rollback checklists (documents, not execution plans)
- Exposes decision status for connector polling

### What FlowBiz does not do — ever, in v0

- **FlowBiz does not call CRM APIs.** It does not read, create, update, or delete records in HubSpot, Salesforce, Pipedrive, or any other CRM system.
- **FlowBiz does not execute automation workflows.** It does not trigger Make scenarios, n8n workflows, Zapier zaps, or any external automation.
- **FlowBiz does not send emails, SMS, or any communication** on behalf of a business.
- **FlowBiz does not write to any SCM system.** It does not push code, create branches, update repositories, or interact with GitHub, GitLab, or Bitbucket.
- **FlowBiz does not execute rollback operations.** It generates a rollback checklist and stops. Execution is the operator's responsibility.
- **FlowBiz does not modify configuration in external systems.** It may evaluate a proposed config change and return DENY, but it never makes the change.

### The line between FlowBiz and the connector

```
External connector → [submits proposal] → FlowBiz gate
FlowBiz gate → [returns decision] → External connector
External connector → [executes mutation IN TARGET SYSTEM] → Target system
```

FlowBiz is the decision layer. The connector is the execution layer. These are two separate systems with a clean interface between them. FlowBiz's decision response is a read-only artifact for the connector to act on. The connector retains full execution authority and full execution responsibility after receiving a decision.

### Why this boundary matters

If FlowBiz crossed this line — even once, even for a "helper" feature — it would:
- Take on mutation risk that belongs to the operator and their tooling
- Undermine the audit model (FlowBiz could not audit its own mutations without conflict)
- Violate the deny-by-default invariant (an actor that can execute cannot be the gate for its own execution)
- Make the v0 trust model incoherent

This boundary is inherited directly from the deny-only, decision-layer pattern established in `flowbiz-ai-core` governance: a gate that also executes is not a gate.

---

## 15. Rough Build Plan

### Phase 1 — Core gate (no UI, connector integration only)

1. Action Proposal schema validation and connector auth endpoint (`POST /v1/gate/proposals`)
2. Connector registration store (SQLite, consistent with platform patterns)
3. Policy store and deny-by-default evaluator
4. Risk scoring engine (deterministic, no ML)
5. Decision response with `decision_id`
6. Audit log write (append-only, synchronous with response)
7. Decision status endpoint (`GET /v1/gate/proposals/{proposal_id}/decision`) for connector polling
8. Outcome recording endpoint (`POST /v1/gate/proposals/{proposal_id}/outcome`)
9. Integration tests: ALLOW path, DENY path, NEEDS_APPROVAL path, connector auth failure, audit write verification

### Phase 2 — Approval Queue and Operator UI surface

10. Approval Queue store and expiry logic
11. Operator UI: Approval Queue list view
12. Operator UI: Proposal detail + approve/reject action
13. Approval outcome propagated to decision record and polling endpoint
14. Override audit record for any DENY override

### Phase 3 — Rollback and audit visibility

15. Rollback checklist generator (rule-based, action-class specific)
16. Audit log query API
17. Operator UI: Change Timeline view (audit log as timeline)

### Not in this plan

- Policy rule editor UI
- Connector management UI
- Webhook/push notification for decision updates (polling is sufficient for v0)

---

## 16. Open Questions & Risks

| Question / Risk | Priority | Notes |
|---|---|---|
| Polling latency for NEEDS_APPROVAL decisions — Make and n8n have timeout limits on step waits; what is the max approval window before the automation step times out? | HIGH | Must establish maximum approval wait time compatible with connector timeout behavior |
| Connector timeout handling — if a connector never polls for a decision update after NEEDS_APPROVAL, does the approval queue record expire silently or does it alert? | HIGH | Expiry behavior must be clearly defined and surfaced in Operator UI |
| `estimated_record_count` is caller-reported and unverified — a malicious or buggy connector could underreport to lower the risk score | MEDIUM | v0 accepts this; future versions should bind risk score to verified scope evidence |
| Policy rule authoring — who writes the policy rules in v0, and what is the interface? | MEDIUM | v0 target: operator-authored rules via a simple YAML/JSON format, loaded at startup |
| Proposal idempotency — if a connector submits the same `proposal_id` twice, what happens? | MEDIUM | Must define: return existing decision if proposal_id already evaluated |
| Audit log storage growth — append-only log with full payload snapshots grows quickly | LOW | v0 accepts SQLite; future versions need retention policy and archival |
| Multi-operator context — v0 targets single operator; if a second operator onboards, is there isolation? | LOW | Out of scope for v0; flag before multi-tenant use |

---

## 17. Recommended Next Step

**Write the ADR** (`docs/adr/ADR_SAFE_AUTOMATION_APPROVAL_GATE_RUNTIME.md`) to lock the key architectural decisions before implementation begins, specifically:

- The decision-only / no-execution runtime boundary (Section 14)
- Deny-by-default as a non-negotiable invariant
- Synchronous audit write as a gate on the response path
- The scope of v0 relative to what the platform already owns (policy gate pattern from Slice 5)

The ADR is the reviewable artifact that prevents scope creep during implementation. Write and review it before writing a single line of gate code.
