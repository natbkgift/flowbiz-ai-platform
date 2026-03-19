# PLATFORM_SLICE_002_JOB_STATUS_PROJECTION

## Task Framing

เป้าหมายของ slice นี้คือเพิ่ม platform-owned current job state read model โดยใช้ workflow event ledger จาก Slice 1 เป็น source of truth เดียว

สิ่งที่ทำในรอบนี้:

- projection logic จาก workflow event ledger
- read-only endpoint สำหรับ current job state by `job_id`
- normalization แบบขั้นต่ำ
- preserve raw status

สิ่งที่ไม่ทำ:

- ไม่สร้าง orchestration engine
- ไม่เพิ่ม billing, dashboard, admin UI
- ไม่ทำ replay / reconciliation loop
- ไม่ตัด over `flowbiz-infra-n8n`
- ไม่เปลี่ยน contract ของ workflow event ledger

## System Analysis

### Confirmed Facts

- ledger ปัจจุบันเก็บ append-only records ใน SQLite ผ่าน [platform_app/workflow_events.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/workflow_events.py)
- event lookup เดิมใช้ `list_by_job_id()` และ sort ตาม `received_at ASC, id ASC`
- route namespace ปัจจุบันอยู่ใต้ `/v1/platform/workflows/...` ใน [platform_app/routes/workflow_events.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/routes/workflow_events.py)
- auth pattern ปัจจุบันคือ `X-API-Key` ผ่าน dependency เดิมจาก [platform_app/deps.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/deps.py)
- repo นี้มี SQLite bootstrap pattern อยู่แล้ว แต่ยังไม่มี projection table pattern

### Inferred Assumptions

- safest design สำหรับรีโปนี้คือ deterministic projection on read เพราะไม่ต้องเพิ่ม second write path
- current job state ควรเป็น derivative only และต้องไม่กลายเป็น truth source ใหม่
- route ใหม่ควรอยู่ใน namespace เดิมเพื่อเลี่ยง route sprawl

### Unknowns

- ยังไม่มี canonical platform taxonomy ที่กว้างกว่านี้
- ยังไม่มี job admission model ให้ bind ความสัมพันธ์ระหว่าง projected state กับ upstream admission record
- ยังไม่มี evidence ว่าต้อง optimize read path ด้วย persistent projection table ในตอนนี้

## Files Changed

- [platform_app/workflow_events.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/workflow_events.py)
- [platform_app/routes/workflow_events.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/routes/workflow_events.py)
- [tests/test_workflow_events.py](/d:/FlowBiz/flowbiz-ai-platform/tests/test_workflow_events.py)
- [docs/platform/PLATFORM_SLICE_002_JOB_STATUS_PROJECTION.md](/d:/FlowBiz/flowbiz-ai-platform/docs/platform/PLATFORM_SLICE_002_JOB_STATUS_PROJECTION.md)

## Projection Design Summary

design ที่เลือกคือ `Option B: deterministic projection on read`

เหตุผล:

- ledger เป็น source of truth เดียวอยู่แล้ว
- รีโปยังไม่มี idiomatic projection-table write path
- การเพิ่ม persistent derived table ตอนนี้จะเพิ่ม projection drift risk โดยไม่จำเป็น

ordering rule:

- ดึง events ของ job จาก ledger
- sort ตาม `(received_at, id)` แบบ ascending
- event สุดท้ายเป็น latest event ที่ชนะการ projection
- ถ้า `execution_id` หรือ `source` ไม่มีใน latest event จะถอยหลังหา latest non-null value ที่มีอยู่

projected fields:

- `job_id`
- `current_status`
- `raw_status`
- `execution_id`
- `client_id`
- `workflow_key`
- `received_at`
- `source`
- `event_count`

## Normalization Rules

platform status set ที่ใช้:

- `received`
- `accepted`
- `running`
- `succeeded`
- `failed`
- `cancelled`
- `unknown`

mapping ขั้นต่ำ:

- `received`, `ingested` -> `received`
- `accepted`, `queued`, `pending` -> `accepted`
- `running`, `in_progress`, `processing`, `started` -> `running`
- `succeeded`, `success`, `completed`, `done` -> `succeeded`
- `failed`, `error`, `errored` -> `failed`
- `cancelled`, `canceled` -> `cancelled`
- raw status อื่น -> `unknown`

หลักการสำคัญ:

- `raw_status` ถูก preserve ตามที่บันทึกใน ledger
- unknown raw statuses ไม่ทำให้ระบบ fail
- normalization layer จงใจเล็กเพื่อเลี่ยง taxonomy lock-in เร็วเกินไป

## Endpoint Summary

### GET `/v1/platform/workflows/jobs/{job_id}`

วัตถุประสงค์:

- อ่าน projected current known state ของ job จาก ledger

auth:

- ใช้ auth dependency เดิมของแพลตฟอร์ม
- เมื่อ `PLATFORM_AUTH_MODE=api_key` จะ reject หาก missing/invalid
- ไม่เพิ่ม scope ใหม่ใน slice นี้

successful response shape:

```json
{
  "status": "ok",
  "job_id": "job-123",
  "current_status": "running",
  "raw_status": "running",
  "execution_id": "exec-001",
  "client_id": "client-a",
  "workflow_key": "lead-enrichment",
  "received_at": "2026-03-19T02:00:00.000+00:00",
  "source": "n8n",
  "event_count": 2
}
```

not-found behavior:

- `404`
- detail: `Job not found: {job_id}`

## Validation Evidence

คำสั่งที่รันจริง:

```powershell
ruff check platform_app apps tests
pytest tests/test_platform_smoke.py tests/test_auth_and_rate_limit.py tests/test_workflow_events.py
@'
from apps.platform_api.main import create_app
app = create_app()
print("ok", len(app.routes))
'@ | python -
```

ผลที่ยืนยันได้:

- `ruff check` ผ่าน
- pytest ผ่าน `22 passed`
- startup/import ผ่าน (`ok 11`)

behavior ที่พิสูจน์ด้วย test:

- first event สร้าง visible projected state ได้
- later events update projected state ตาม latest event
- unknown raw status project เป็น `unknown` โดยไม่พัง
- missing job ให้ `404` แบบ predictable
- auth behavior ของ projection route ตาม convention เดิม
- ordering deterministic: `(received_at, id)` และ latest non-null `execution_id`/`source` ถูก preserve
- workflow event tests เดิมยังผ่าน

สิ่งที่ไม่ได้ verify:

- ไม่มี load test สำหรับ read-heavy path
- ไม่มี integration กับ external runner จริง
- ไม่มี backfill path จาก external historical events เพราะ slice นี้คำนวณ projection on read เท่านั้น

## Regression Risk

ความเสี่ยงหลัก:

- taxonomy lock-in risk: ต่ำถึงปานกลาง เพราะ mapping จงใจเล็กและ preserve raw status
- projection drift risk: ต่ำ เพราะไม่มี persistent projection table และ derive จาก ledger โดยตรงทุกครั้ง
- ordering ambiguity risk: ลดลงด้วย ordering rule แบบ explicit `(received_at, id)`
- route sprawl risk: ต่ำ เพราะเพิ่ม endpoint ใน namespace เดิม

tradeoff ที่เลือก:

- เลือก compute-on-read แทน persistent projection table เพื่อไม่สร้าง second truth source
- map `queued/pending` ไป `accepted` แบบขั้นต่ำ เพื่อให้ platform current state อ่านง่ายขึ้นโดยไม่อ้าง orchestration semantics มากเกินไป

## Why This Slice Is Safe

- ledger ยังเป็น authoritative source เดิม
- projection เป็น derivative read model only
- ไม่มี background worker หรือ replay loop
- ไม่มีการเปลี่ยน Slice 1 endpoint semantics
- current job state สามารถอ่านได้จาก platform โดยไม่บังคับให้ platform รับ ownership orchestration เต็มตัว

## Out Of Scope

- job admission / dispatch ownership
- job list / search read model
- policy / quota hook
- cutover หรือ forwarding จาก `flowbiz-infra-n8n`
- workflow control decisions

## Next Recommended Slice

แนะนำ slice ถัดไปเพียงหนึ่งอย่าง:

- `Job Admission Record Before Runner Dispatch`

เหตุผล:

- หลัง Slice 2 platform มีทั้ง event truth และ current state read model แล้ว
- จุดที่ยังขาดคือ platform-owned start-of-job record ก่อน runner dispatch
- เมื่อมี admission record แล้ว platform จะเริ่มถือ ownership ของจุดเริ่มงาน, event truth, และ current state อย่างต่อเนื่อง โดยยังไม่ต้องกลายเป็น orchestration engine
