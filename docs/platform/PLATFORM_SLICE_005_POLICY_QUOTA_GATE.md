# PLATFORM_SLICE_005_POLICY_QUOTA_GATE

## Task Framing

เป้าหมายของ slice นี้คือเพิ่ม minimal policy / quota gate ที่จุด job admission เพื่อให้ `flowbiz-ai-platform` เริ่มเป็น owner ของ business control ที่ admission time โดยยังไม่ขยายเป็น billing platform หรือ policy engine ขนาดใหญ่

สิ่งที่ทำ:

- SQLite-backed client admission policy store
- allow/deny decision ก่อนสร้าง job record
- deterministic quota checks สำหรับ daily jobs และ active jobs
- clear rejection response เมื่อ policy block admission

สิ่งที่ไม่ทำ:

- billing integration
- plan catalog
- subscription UI
- dispatch changes
- retry/scheduler
- dashboard/admin UI
- policy DSL

## Schema

table: `client_admission_policies`

fields:

- `client_id`
- `is_enabled`
- `max_jobs_per_day`
- `max_active_jobs`
- `updated_at`

storage design:

- ใช้ SQLite file เดียวกับ workflow domain เดิม
- policy record เป็น platform-owned control state
- job records, dispatch records, และ event ledger ยังคงแยก responsibility ของตนเอง

## Policy Decision Rules

default behavior:

- ถ้าไม่มี policy record สำหรับ `client_id` จะ `allow` โดย bootstrap default
- เหตุผลคือ preserve existing job admission contract ของ Slice 3 และเลี่ยง breaking change ทันที

deny conditions:

- `is_enabled = false` -> deny
- จำนวน jobs ที่สร้างในวัน UTC ปัจจุบัน `>= max_jobs_per_day` -> deny
- จำนวน active jobs `>= max_active_jobs` -> deny

active job definition:

- ใช้ latest workflow event status ถ้ามี
- ถ้า job ยังไม่มี event ใช้ `workflow_jobs.status`
- normalize status ผ่าน platform status normalization เดิม
- นับ active เฉพาะ `received`, `accepted`, `running`

denial semantics:

- disabled client -> `403`
- quota/active-limit exceeded -> `429`
- response detail เป็น object `{code, message}`

## Endpoint Impacts

endpoint ที่ได้รับผล:

- `POST /v1/platform/workflows/jobs`

behavior change:

- ก่อน create job record จะ evaluate policy/quota ก่อน
- ถ้า allowed contract เดิมยังคงเป็น `201` + job record response
- ถ้า denied จะ return explicit rejection response

no new management endpoint:

- slice นี้ใช้ internal bootstrap storage + fixture seeding ใน tests
- ยังไม่เพิ่ม policy admin surface

## Files Changed

- [platform_app/admission_policy.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/admission_policy.py)
- [platform_app/deps.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/deps.py)
- [platform_app/routes/workflow_events.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/routes/workflow_events.py)
- [tests/test_workflow_events.py](/d:/FlowBiz/flowbiz-ai-platform/tests/test_workflow_events.py)
- [tests/test_job_records.py](/d:/FlowBiz/flowbiz-ai-platform/tests/test_job_records.py)
- [tests/test_dispatch_records.py](/d:/FlowBiz/flowbiz-ai-platform/tests/test_dispatch_records.py)
- [tests/test_admission_policy.py](/d:/FlowBiz/flowbiz-ai-platform/tests/test_admission_policy.py)
- [docs/platform/PLATFORM_SLICE_005_POLICY_QUOTA_GATE.md](/d:/FlowBiz/flowbiz-ai-platform/docs/platform/PLATFORM_SLICE_005_POLICY_QUOTA_GATE.md)

## Validation Evidence

คำสั่งที่รันจริง:

```powershell
ruff check platform_app apps tests
pytest tests/test_platform_smoke.py tests/test_auth_and_rate_limit.py tests/test_workflow_events.py tests/test_job_records.py tests/test_dispatch_records.py tests/test_admission_policy.py
@'
from apps.platform_api.main import create_app
app = create_app()
print("ok", len(app.routes))
'@ | python -
```

ผลที่ยืนยันได้:

- `ruff check` ผ่าน
- pytest ผ่าน `40 passed`
- startup/import ผ่าน (`ok 15`)

behavior ที่พิสูจน์ด้วย test:

- admission allowed เมื่อ policy อนุญาต
- admission denied เมื่อ client disabled
- admission denied เมื่อ daily quota exceeded
- admission denied เมื่อ active job limit exceeded
- auth requirement เดิมยังคงอยู่
- existing job admission success path ยังผ่านเมื่ออยู่ใน limit
- previous workflow/dispatch/projection tests ยังผ่าน

## Regression Risks

- contract stability risk: ต่ำ เพราะ `POST /v1/platform/workflows/jobs` ยังคืน contract เดิมเมื่อ allowed
- denial semantics risk: ลดลงด้วย explicit `code` และ `message`
- active job ambiguity risk: มีอยู่บ้าง แต่ถูกจำกัดด้วย rule ชัดเจนว่าใช้ latest event หรือ fallback ไป job status
- accidental truth mutation risk: ต่ำ เพราะ policy logic ไม่แก้ event truth หรือ projection truth
- n8n coupling risk: ไม่มี เพราะ gate ทำงานที่ admission layer เท่านั้น

## Why This Slice Is Safe

- control logic ถูกวางใน `flowbiz-ai-platform` ตาม ownership ที่ต้องการ
- ไม่มี billing complexity หรือ plan model
- ใช้ SQLite/bootstrap pattern เดิมของรีโป
- preserve route contracts เดิมทั้งหมดนอกจากเพิ่ม deny path ที่จำเป็นสำหรับ admission control

## Next Slice

แนะนำถัดไป:

- API Key Lifecycle + Audit Trail
