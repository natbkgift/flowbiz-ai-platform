# ADR: Safe Automation Approval Gate — Runtime Architecture

**ADR ID:** ADR-SAAG-001
**Status:** Accepted — Draft 2026-05-21
**Branch:** `feat/safe-automation-approval-layer-v0`
**Spec:** `docs/SAFE_AUTOMATION_APPROVAL_LAYER_V0_SPEC.md`

---

## 1. Context

FlowBiz platform already owns a deny-by-default admission gate at the workflow job layer (Slice 5, `PLATFORM_SLICE_005_POLICY_QUOTA_GATE.md`). That gate answers: *should this job be admitted to the FlowBiz runtime?*

The Safe Automation Approval Gate answers a different question: *should this business action — proposed by an external automation tool — be permitted to execute in an external system?*

The distinction matters. Slice 5 governs internal platform admission. The approval gate governs external business mutations. The pattern is the same (propose → evaluate → decide → audit); the domain is different (business automations, not platform jobs).

External automation tools (Make, n8n, Zapier, custom webhooks) integrate with the gate by submitting a structured Action Proposal before executing any risky action. The gate returns ALLOW, DENY, or NEEDS_APPROVAL. All mutations are performed by the connector after receiving a decision, never by FlowBiz.

Four architectural decisions must be locked before implementation begins. Each one, if left ambiguous, would cause scope creep or connector integration failures during build.

---

## 2. Decisions

### Decision 1 — Runtime boundary: decision-only, no execution

**Decided:** FlowBiz evaluates proposals and returns decisions. It never calls external business system APIs (CRM, SCM, email, automation platforms) to execute mutations, even when a decision is ALLOW.

**Rationale:** A gate that can also execute is not a gate. If FlowBiz executed mutations, it would be simultaneously the evaluator and the actor — making the audit model incoherent (FlowBiz cannot audit its own mutations without a conflict), undermining the deny-by-default invariant (an actor has no incentive to deny itself), and taking on mutation risk and rollback responsibility that belongs to the operator and their tooling.

This boundary is directly inherited from the `flowbiz-ai-core` governance pattern: every frozen contract in BATCH_21 through BATCH_27 treats the gate as a proposal evaluator that produces a decision artifact, never as an executor.

**Consequence:** FlowBiz's integration surface is inbound-only for mutations. Connectors own execution. This is non-negotiable and must be enforced in implementation: no outbound HTTP calls to CRM/SCM/automation APIs may be introduced in the gate codebase.

---

### Decision 2 — Deny-by-default

**Decided:** Any Action Proposal without a matching policy rule that explicitly produces ALLOW results in DENY. There is no implicit permission. Unknown connectors, unknown action classes, and proposals that satisfy no active rule all receive DENY.

**Rationale:** Inherited directly from the core governance deny-by-default invariant. In the Git governance lineage, a commit proposal with no matching eligibility rule is ineligible — it does not pass through. The same logic applies here. Defaulting to ALLOW would require every policy to enumerate what is forbidden, which is an unbounded problem. Defaulting to DENY requires policy to enumerate only what is permitted, which is bounded and auditable.

**Consequence:** Onboarding a new connector requires explicit policy setup. This is intentional friction. A connector that submits valid proposals but has no matching policy rule will receive DENY with code `NO_MATCHING_POLICY`, not a silent failure.

---

### Decision 3 — Synchronous audit write on the response path

**Decided:** The audit record is written to persistent storage synchronously before the decision response is returned to the caller. If the audit write fails, the gate returns 500 and no decision is issued to the connector.

**Rationale:** Inherited from the BATCH_12A Observability Audit Envelope: every gate decision must be captured in a structured, persistent audit record. Making the audit write async would create a window where a decision was issued but not recorded — an inconsistent state that breaks the audit guarantee and cannot be recovered cleanly. The cost is added latency on the response path; this is acceptable because gate decisions are not high-frequency and the audit write is a local DB append.

**Consequence:** The gate response time is bounded by audit write latency, not just evaluation latency. The implementation must not introduce async audit writes as a "performance optimization" — that would silently break the guarantee this decision establishes.

---

### Decision 4 — Async-resume is the required pattern for NEEDS_APPROVAL; blocking-poll is permitted only for synchronous decisions

**Decided:** When a gate evaluation returns NEEDS_APPROVAL, the connector must complete its current workflow step immediately (receiving the NEEDS_APPROVAL response) and use an async-resume pattern to continue execution after a human decision is made. Blocking-poll within a single workflow step is not a supported pattern for NEEDS_APPROVAL.

For ALLOW and DENY — which are returned synchronously within the same API call — the connector may use the response inline within its workflow step.

**Rationale:**

Make scenarios and n8n workflows impose step-level execution timeouts, typically in the range of 30 seconds to a few minutes depending on plan and configuration. Human approval decisions are not bounded by these timeouts — an approver may take minutes, hours, or days to act. A connector that submits a proposal and then polls within the same step will hit its timeout before a human has had a chance to approve, causing the automation to fail at the step level. This is not a connector implementation detail — it is a fundamental mismatch between human response latency and machine step timeout that cannot be resolved with a longer poll interval.

The async-resume pattern resolves this correctly:

```
Step A — Submit Proposal
  connector submits proposal to POST /v1/gate/proposals
  receives: { decision: "NEEDS_APPROVAL", approval_queue_id: "...", proposal_id: "..." }
  workflow step completes immediately with proposal_id stored in workflow state

[human reviews and acts in FlowBiz Operator UI — no connector step is waiting]

Step B — Resume on Decision (triggered by webhook callback OR second automation trigger)
  FlowBiz calls connector-registered callback URL with decision update, OR
  a second Make/n8n trigger fires when FlowBiz writes the final decision
  connector reads: { decision: "ALLOW" | "DENY", decision_id: "..." }
  workflow continues from stored proposal_id state
```

Blocking-poll (submit → poll in a loop → receive decision) works only when the decision is expected within the step timeout. For ALLOW and DENY this is guaranteed — they are synchronous. For NEEDS_APPROVAL it is not guaranteed and must not be used.

**Consequence for connector contract (Section 12 of spec):** The connector pattern defined in the spec must be updated to reflect this decision. Specifically:

- The "polls `GET /v1/gate/proposals/{proposal_id}/decision`" path described in the spec is valid only for ALLOW/DENY status checks (e.g., a connector verifying a decision it already received inline). It must NOT be used as the primary wait mechanism for NEEDS_APPROVAL.
- FlowBiz must provide a **callback/webhook registration** field in the Action Proposal or connector registration so that connectors can receive a push notification when a NEEDS_APPROVAL decision resolves.
- For connectors that cannot register webhook callbacks (some Make plans), the recommended pattern is: a second Make scenario or n8n workflow triggered by a FlowBiz-generated event when the approval is recorded.

**Consequence for Approval Queue design:** The Approval Queue expiry logic must account for the fact that the connector is not waiting — expiry affects the human window, not a waiting machine. The expiry notification must be pushed to the connector (via the registered callback) so the connector can handle the expired state cleanly.

**Open question deferred:** The exact webhook delivery guarantee (at-least-once vs exactly-once) and retry behavior are not decided here. This ADR decides the pattern (async-resume required); delivery semantics are a Phase 2 implementation decision.

---

## 3. Governance Justification

These decisions inherit directly from frozen `flowbiz-ai-core` contracts:

| Decision | Source contract |
|---|---|
| Decision 1 — decision-only boundary | BATCH_27 Merge Authority Contract: the gate evaluates eligibility and records the decision; execution is downstream of the gate, not part of it |
| Decision 2 — deny-by-default | BATCH_21 Commit Provenance Binding + BATCH_27 Merge Eligibility Contract: proposals without matching eligibility criteria are ineligible by default, not permitted by default |
| Decision 3 — synchronous audit write | BATCH_12A Observability Audit Envelope: every gate decision is captured in a structured persistent record before the response is issued |
| Decision 4 — async-resume | Not directly inherited; this decision resolves the connector integration constraint introduced by the approval gate's human-latency requirement. It is consistent with the gate-as-record-keeper pattern: the gate persists the proposal and decision; the connector resumes from that persisted state |

---

## 4. Scope Boundaries

### What this ADR covers

- The four decisions above and their consequences for the gate implementation
- The connector contract adjustment required by Decision 4

### What this ADR does not cover

- Policy rule authoring format (YAML/JSON schema — deferred to implementation)
- Webhook delivery guarantee and retry semantics (deferred to Phase 2)
- Multi-tenant isolation (out of scope for v0 per spec Section 4)
- Rollback execution (out of scope permanently per Decision 1)

### Relationship to Slice 5 (Policy Quota Gate)

Slice 5 owns the `client_admission_policies` store and the admit/deny decision at platform job admission time. The approval gate is a separate domain, separate store, and separate decision surface. They share the same architectural pattern (deny-by-default, synchronous audit write) but must not share implementation state. The approval gate is not an extension of Slice 5 — it is a parallel application of the same pattern to the business automation domain.

---

## 5. Consequences

### Positive

- The runtime boundary (Decision 1) eliminates an entire class of implementation risk: no external API credentials, no mutation side-effects, no rollback ownership for FlowBiz.
- Deny-by-default (Decision 2) makes the permission model auditable by enumeration: what is permitted is listed; everything else is denied.
- Synchronous audit write (Decision 3) makes the audit log a reliable source of truth with no eventual-consistency gap.
- Async-resume (Decision 4) makes the approval gate compatible with real Make and n8n deployment constraints, enabling v0 to be useful in production rather than a demo-only feature.

### Negative / accepted tradeoffs

- Decision 1 pushes execution complexity to the connector. Connectors must handle the resume logic, credential management for the target system, and mutation error handling. This is the correct owner for those concerns, but it increases connector implementation effort.
- Decision 3 adds latency to every gate response. Accepted — gate calls are low-frequency relative to platform job throughput.
- Decision 4 increases connector integration complexity for NEEDS_APPROVAL cases. Connectors need two-step automation patterns (submit step + resume step) rather than a single synchronous flow. This is the correct tradeoff: the alternative (blocking-poll) is worse because it fails silently in production under real approval latency.

---

## 6. Alternatives Considered

### Alternative to Decision 1: FlowBiz executes "safe read-only" calls to CRM for evidence enrichment

Considered: allow FlowBiz to call CRM APIs in read-only mode to enrich a proposal's evidence (e.g., fetch the current state of a deal before evaluating a status-change proposal).

**Rejected:** Even read-only CRM calls introduce credential requirements, network dependency, and CRM API rate limits into the gate path. More importantly, it blurs the boundary — once FlowBiz has CRM credentials for reads, the incremental cost of adding writes feels small. The boundary must be strict. Evidence enrichment is the connector's job; the connector knows the target system and can include enriched context in the proposal payload.

### Alternative to Decision 2: Allowlist-plus-denylist (some actions permitted by default)

Considered: allow a subset of low-risk action classes (e.g., `crm.contact.update` on single records) by default without requiring explicit policy.

**Rejected:** "Low risk" is context-dependent (a single-record update to a billing field is not low risk). Default permits create invisible surface area. The friction of explicit policy setup is intentional and healthy. Operators who find it excessive can configure broad permits explicitly — they cannot un-permit things they didn't know were permitted by default.

### Alternative to Decision 3: Async audit write with a dead-letter queue for failures

Considered: write the audit record asynchronously, with failures sent to a dead-letter queue for retry, so that audit write latency does not block the response path.

**Rejected:** Async writes create a window of inconsistency. During that window, a decision has been issued to a connector that could act on it, but no audit record exists. If the write ultimately fails and the dead-letter queue is not processed, the decision is permanently unaudited. The audit guarantee must be synchronous. The latency cost is accepted.

### Alternative to Decision 4: Long-poll with extended step timeout negotiation

Considered: document a long-poll pattern with guidance for connectors to configure extended step timeouts, targeting a 15–30 minute poll window.

**Rejected:** Step timeout configuration is plan- and tool-dependent. Make's maximum step timeout varies by plan (some plans cap at 40 seconds, others at 5 minutes). n8n self-hosted has configurable timeouts but cloud has stricter limits. Relying on timeout configuration as a solution produces a gate that works only on certain plans at certain configurations — not a reliable integration. Async-resume works regardless of step timeout constraints.

---

## 7. Non-Goals of This ADR

- This ADR does not define the policy rule schema or the rule evaluation DSL.
- This ADR does not decide webhook delivery guarantees or retry semantics.
- This ADR does not govern how connectors authenticate to their target systems after receiving ALLOW.
- This ADR does not address the Operator UI design for the Approval Queue beyond confirming it must exist.
- This ADR does not set retention policy for the audit log.

---

## 8. Review Requirements

This ADR must be reviewed and accepted before implementation of any approval gate code begins.

**Required review confirmation:**

1. Decision 1 (decision-only boundary) is accepted and understood to be non-negotiable — no exceptions for "helper" outbound calls
2. Decision 2 (deny-by-default) is accepted — policy setup is required for every connector before it can receive ALLOW
3. Decision 3 (synchronous audit write) is accepted — latency tradeoff is acceptable for gate use patterns
4. Decision 4 (async-resume required for NEEDS_APPROVAL) is accepted — and the connector contract in `SAFE_AUTOMATION_APPROVAL_LAYER_V0_SPEC.md` Section 12 will be updated before implementation to reflect the two-step (submit + resume) connector pattern, callback registration requirement, and prohibition on blocking-poll for NEEDS_APPROVAL

**Spec update required before Phase 1 build starts:**
- Section 12 (Connector Pattern) of the spec must be revised to:
  - Make async-resume the primary documented pattern for NEEDS_APPROVAL
  - Add callback URL registration to the connector registration schema
  - Deprecate the polling path as the primary wait mechanism for NEEDS_APPROVAL (polling remains valid for status verification only)
