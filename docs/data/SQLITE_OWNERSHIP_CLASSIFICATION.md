<!-- markdownlint-disable MD013 -->

# SQLite Ownership Classification Packet

## 1. Document Control

| Field | Value |
| --- | --- |
| Status | `OWNER_CLASSIFICATION_COMPLETE` |
| Date | 2026-06-28 |
| Repository | `natbkgift/flowbiz-ai-platform` |
| Branch | `docs/sqlite-owner-classification` |
| Product Blueprint | `OWNER_APPROVED` |
| Core gate | `BLOCKED_FOR_PROD_01` |
| Scope | Read-only evidence packet for 17 reported SQLite records |

## 2. Safety Declaration

This packet was prepared with Python standard-library `sqlite3` connections using URI
`mode=ro`. `PRAGMA query_only=ON` was enabled and confirmed as `1` on every
connection before table data was read. Only schemas, counts, timestamp bounds,
non-sensitive status/type values, and relationship coverage were inspected. Complete
rows, payloads, prompts, raw identifiers, PII, API keys, tokens, callback secrets,
credentials, and the raw primary-key-to-alias mapping are not included.

Agent evidence is not an ownership decision. Unknown or ambiguous rows remain
`UNKNOWN_OWNERSHIP`. No record may be deleted or assigned to a tenant by inference.
Classification does not authorize migration or disposal. No database mutation,
migration, import, export, compaction, schema change, service startup, deployment,
tag, release, PROD-01 work, or PROD-04 work was performed.

## 3. Database File Inventory

Paths below are repository-relative aliases, not absolute machine paths. Timestamps
are UTC.

| Path alias | Bytes | Modified | Permissions | SHA-256 | Associated files |
| --- | ---: | --- | --- | --- | --- |
| `platform_data/approval_gate.db` | 94,208 | 2026-05-23T03:01:28.873Z | Archive attribute; ACL inheritance enabled; 4 inherited and 0 explicit access rules | `9481aa43f396500348207d3141d7a049b3183a0ff54043b9ef9ff4f4e16f85da` | Empty `-wal` (0 bytes) and `-shm` (32,768 bytes) present after the read-only connection; no journal |
| `platform_data/workflow_events.db` | 36,864 | 2026-05-22T10:27:42.869Z | Archive attribute; ACL inheritance enabled; 4 inherited and 0 explicit access rules | `4d4b00f24d4d4ba4bf88722361004a7fa0e75a3946b0ac23cc596138d2acc832` | No `-wal`, `-shm`, or journal |

Configuration defines three SQLite path settings:

- `auth_sqlite_path` -> `platform_data/platform_auth.db`; the configured auth store
  mode is JSON and no file exists at this path alias, so there was no auth SQLite file
  to inspect.
- `approval_gate_sqlite_path` -> `platform_data/approval_gate.db`.
- `workflow_events_sqlite_path` -> `platform_data/workflow_events.db`.

The two source databases, the empty WAL, and the SHM were stable across repeated
size, timestamp, and SHA-256 checks. Runtime database and sidecar files are ignored
and must remain unstaged.

## 4. Schema and Table Inventory

SQLite library version: `3.45.1`.

The table inventory was recomputed from each inspected database with the following
query after confirming `PRAGMA query_only=ON`:

```sql
SELECT name, sql FROM sqlite_master
WHERE type='table' AND name NOT LIKE 'sqlite_%'
ORDER BY name;
```

| Database path alias | Actual user tables |
| --- | ---: |
| `platform_data/approval_gate.db` | 6 |
| `platform_data/workflow_events.db` | 3 |
| **Actual total** | **9** |

### `platform_data/approval_gate.db`

| Table | Rows | Schema summary | Foreign keys |
| --- | ---: | --- | --- |
| `approval_audit_events` | 4 | `audit_id TEXT PK`; event, proposal/decision reference, timestamp, actor, action, target, risk, decision, reason, hash, and snapshot fields | None declared; all 4 proposal references and all 4 populated decision references matched |
| `approval_connectors` | 1 | `connector_id TEXT PK`; name, allowed-action, key-hash, callback, disabled, and timestamp fields | None declared; the connector is referenced by all 4 proposals |
| `approval_decisions` | 4 | `decision_id TEXT PK`; proposal reference, decision, timestamp, reason, risk, approval, queue, and rollback fields | `proposal_id` -> `approval_proposals.proposal_id` |
| `approval_outcomes` | 0 | `proposal_id TEXT PK`; outcome and timestamp fields | `proposal_id` -> `approval_proposals.proposal_id` |
| `approval_policies` | 2 | `policy_id TEXT PK`; action, target, mutation, risk, approval, enabled, and timestamp fields | None declared |
| `approval_proposals` | 4 | `proposal_id TEXT PK`; connector, action, target, mutation, summaries/hashes, signal, requester, timestamps, and payload fields | None declared; all 4 connector references matched |

### `platform_data/workflow_events.db`

| Table | Rows | Schema summary | Foreign keys |
| --- | ---: | --- | --- |
| `client_admission_policies` | 0 | `client_id TEXT PK`; enabled, quota, active-job, and timestamp fields | None declared |
| `workflow_events` | 0 | `id INTEGER PK`; job/client/workflow/execution, status, timestamp, payload, and source fields | None declared |
| `workflow_jobs` | 2 | `job_id TEXT PK`; client/workflow, status, timestamp, input, and metadata fields | None declared |

`workflow_dispatches` is a runtime-defined table absent from the inspected snapshot.
The code-defined source is `platform_app.dispatch_records.SQLiteDispatchRecordStore`,
which creates the table when that store is initialized. Because the table is absent,
no row count is assigned or inferred, and it is not represented as a zero-row table.

Non-sensitive distributions observed:

- Approval audit events: 4 `DECISION_MADE`; decisions 2 `ALLOW`, 1 `DENY`, and
  1 `NEEDS_APPROVAL`; risk 3 `LOW` and 1 `HIGH`.
- Approval proposals: action types 2 contact updates, 1 campaign send, and 1 deal
  status change; mutation types 2 updates, 1 send, and 1 status change.
- Approval policies: 2 enabled. Connector: 1 enabled. Outcomes: 0.
- Workflow jobs: 2 `received`. Workflow events and client admission policies: 0.

## 5. Count Reconciliation

| Database | Table group | Source rows |
| --- | --- | ---: |
| Approval | Connector and policies | 3 |
| Approval | Proposals | 4 |
| Approval | Decision children | 4 |
| Approval | Audit children | 4 |
| Workflow | Jobs | 2 |
| **Observed total** | - | **17** |
| **Reported total** | - | **17** |
| **Difference** | - | **0** |

The observed total includes rows from the 9 tables actually returned by
`sqlite_master`. The absent runtime-defined `workflow_dispatches` table contributes
no inspected table or row count to this reconciliation. No zero-row claim is made for
that absent table.

An ownership unit is one persisted source row because ownership classification and
disposal authority must be explicit at row level. Supported relationships do not
authorize copying a classification from one row to another: audit and control rows
may have independent retention obligations. The 4 decision rows and 4 audit rows are
therefore grouped with their 4 proposal parents as record families while retaining
their own aliases and Owner decision fields. This yields 17 reconciled ownership
units. The raw primary-key-to-alias mapping remains outside Git.

## 6. Ownership Units

- `R001`: connector configuration record; related to 4 proposal families.
- `R002`-`R003`: enabled policy records; one relates by action/target criteria to 2
  proposals and one relates to 1 proposal.
- `R004`-`R006`: proposal family 1 (proposal, decision, audit).
- `R007`-`R009`: proposal family 2 (proposal, decision, audit).
- `R010`-`R012`: proposal family 3 (proposal, decision, audit).
- `R013`-`R015`: proposal family 4 (proposal, decision, audit).
- `R016`-`R017`: workflow job records; no child workflow events observed.

Aliases are neutral labels only. They do not encode identifiers, ownership,
classification, tenant, or disposal status.

## 7. Owner Decision Matrix

| Alias | Table/group | Non-sensitive evidence | Timestamp range (UTC) | Relationship summary | Owner classification | Owner rationale | Disposal permitted |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R001 | `approval_connectors` | Enabled connector configuration | 2026-05-22T03:20:28.998Z to 2026-05-23T02:59:55.975Z | Referenced by all 4 proposal families | `test` | Owner confirms FlowBiz has no real customers; internal development/test record | `NO` |
| R002 | `approval_policies` | Enabled contact-update policy | 2026-05-23T02:59:56.071Z | Criteria relate to 2 proposals | `test` | Owner confirms FlowBiz has no real customers; internal development/test record | `NO` |
| R003 | `approval_policies` | Enabled campaign-send policy | 2026-05-23T02:59:56.150Z | Criteria relate to 1 proposal | `test` | Owner confirms FlowBiz has no real customers; internal development/test record | `NO` |
| R004 | Proposal family 1 / `approval_proposals` | Contact update; update mutation | 2026-05-22T03:00:01.000Z to 2026-05-22T09:51:18.049Z | Parent of R005 and R006 | `test` | Owner confirms FlowBiz has no real customers; internal development/test record | `NO` |
| R005 | Proposal family 1 / `approval_decisions` | `ALLOW`; `LOW` risk | 2026-05-22T09:51:17.942Z | Decision child of R004; paired with R006 | `test` | Owner confirms FlowBiz has no real customers; internal development/test record | `NO` |
| R006 | Proposal family 1 / `approval_audit_events` | `DECISION_MADE` audit event | 2026-05-22T09:51:17.942Z | Audit child of R004; references R005 | `test` | Owner confirms FlowBiz has no real customers; internal development/test record | `NO` |
| R007 | Proposal family 2 / `approval_proposals` | Contact update; update mutation | 2026-05-23T03:01:01.000Z to 2026-05-23T03:01:09.988Z | Parent of R008 and R009 | `test` | Owner confirms FlowBiz has no real customers; internal development/test record | `NO` |
| R008 | Proposal family 2 / `approval_decisions` | `ALLOW`; `LOW` risk | 2026-05-23T03:01:09.881Z | Decision child of R007; paired with R009 | `test` | Owner confirms FlowBiz has no real customers; internal development/test record | `NO` |
| R009 | Proposal family 2 / `approval_audit_events` | `DECISION_MADE` audit event | 2026-05-23T03:01:09.881Z | Audit child of R007; references R008 | `test` | Owner confirms FlowBiz has no real customers; internal development/test record | `NO` |
| R010 | Proposal family 3 / `approval_proposals` | Campaign send; send mutation | 2026-05-23T03:01:19.006Z to 2026-05-23T03:02:01.000Z | Parent of R011 and R012 | `test` | Owner confirms FlowBiz has no real customers; internal development/test record | `NO` |
| R011 | Proposal family 3 / `approval_decisions` | `NEEDS_APPROVAL`; `HIGH` risk | 2026-05-23T03:01:18.882Z | Decision child of R010; paired with R012 | `test` | Owner confirms FlowBiz has no real customers; internal development/test record | `NO` |
| R012 | Proposal family 3 / `approval_audit_events` | `DECISION_MADE` audit event | 2026-05-23T03:01:18.882Z | Audit child of R010; references R011 | `test` | Owner confirms FlowBiz has no real customers; internal development/test record | `NO` |
| R013 | Proposal family 4 / `approval_proposals` | Deal status change; status-change mutation | 2026-05-23T03:01:28.787Z to 2026-05-23T03:03:01.000Z | Parent of R014 and R015 | `test` | Owner confirms FlowBiz has no real customers; internal development/test record | `NO` |
| R014 | Proposal family 4 / `approval_decisions` | `DENY`; `LOW` risk | 2026-05-23T03:01:28.696Z | Decision child of R013; paired with R015 | `test` | Owner confirms FlowBiz has no real customers; internal development/test record | `NO` |
| R015 | Proposal family 4 / `approval_audit_events` | `DECISION_MADE` audit event | 2026-05-23T03:01:28.696Z | Audit child of R013; references R014 | `test` | Owner confirms FlowBiz has no real customers; internal development/test record | `NO` |
| R016 | `workflow_jobs` | `received` status | 2026-03-24T14:24:29.789Z | No child workflow events observed | `test` | Owner confirms FlowBiz has no real customers; internal development/test record | `NO` |
| R017 | `workflow_jobs` | `received` status | 2026-05-22T10:27:42.773Z | No child workflow events observed | `test` | Owner confirms FlowBiz has no real customers; internal development/test record | `NO` |

## 8. Classification Definitions

- `customer/production`: Owner confirms the unit represents real customer or
  production activity. This classification alone does not assign a tenant.
- `test`: Owner confirms the unit was created for verification, automated testing,
  development testing, or an equivalent non-production purpose.
- `demo`: Owner confirms the unit was created for demonstration, training, sales,
  or showcase use and is not customer production data.
- `duplicate`: Owner confirms the unit duplicates another identified unit. The Owner
  rationale must identify the authoritative unit without placing raw identifiers in Git.
- `unknown`: Owner cannot establish a supported classification. The unit remains
  quarantined as `UNKNOWN_OWNERSHIP`.

## 9. Quarantine Rules

1. Every pending, unknown, ambiguous, or unsupported unit remains
   `UNKNOWN_OWNERSHIP` and quarantined.
2. No unit may be assigned to a tenant by inference, timestamp, relationship,
   status, action type, or similarity.
3. A parent classification does not automatically classify child decision, audit,
   event, policy, connector, or outcome rows.
4. No classification authorizes deletion, migration, disposal, export, replacement,
   or modification of a database or sidecar.
5. `Disposal permitted` remains `NO` unless a separate explicit Owner instruction
   and all applicable retention, relationship, and migration gates are satisfied.
6. Raw identifiers and private evidence must be reviewed outside Git through an
   access-controlled process.

## 10. Owner Approval Record

| Field | Owner entry |
| --- | --- |
| Owner name/role | `Nat / FlowBiz Owner` |
| Decision instruction/reference | `Owner instruction: FlowBiz has no real customers; complete the classification without returning manual record-entry work` |
| Decision date | `2026-06-28` |
| Aliases reviewed | `R001-R017` |
| Exceptions or unresolved aliases | `NONE` |
| Approval signature/record | `OWNER_CONFIRMED_NO_REAL_CUSTOMERS` |

All 17 ownership units are classified as `test` because the Owner confirms that
FlowBiz has no real customers and the inspected records are internal
development/testing records. Disposal remains prohibited. This classification does
not authorize deletion, migration, tenant assignment, release, or PROD-01.

## 11. Remaining Migration Gates

- Owner classification is complete for R001-R017: all units are `test`.
- Keep all classified test units isolated from production migration and tenant assignment; disposal remains prohibited.
- Revalidate source hashes, row counts, relationships, and query-only controls before
  any later approved work.
- Obtain separate explicit authority for tenant assignment, migration, retention, or
  disposal; classification is evidence only.
- Keep Core `BLOCKED_FOR_PROD_01` until its independent prerequisites are satisfied.
- PROD-01 requires a separate explicit Owner instruction and must not begin from this
  packet or its approval.
