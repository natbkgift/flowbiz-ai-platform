# PLATFORM_SLICE_001_WORKFLOW_EVENT_LEDGER

## Task Framing

เป้าหมายของ slice นี้คือสร้าง foothold แรกของ orchestration truth ภายใน `flowbiz-ai-platform` โดยเพิ่มเพียง 3 อย่าง:

- persistent workflow event ledger
- authenticated callback/event intake endpoint
- read-only lookup endpoint by `job_id`

สิ่งที่ตั้งใจไม่ทำใน slice นี้:

- ไม่สร้าง orchestration engine
- ไม่เพิ่ม billing, dashboard, admin UI
- ไม่ทำ event replay
- ไม่เปลี่ยน responsibility ของ `flowbiz-infra-n8n` ในรอบนี้
- ไม่เปลี่ยน route เดิมของระบบ

## Repository Analysis

### Confirmed Facts

- app entrypoint ปัจจุบันคือ [apps/platform_api/main.py](/d:/FlowBiz/flowbiz-ai-platform/apps/platform_api/main.py)
- แอปใช้ FastAPI เดียวและ include router หลักจาก [platform_app/routes/system.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/routes/system.py) และ [platform_app/routes/platform.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/routes/platform.py)
- route namespace ที่มีอยู่แล้วใช้รูปแบบ `/v1/platform/...`
- config ใช้ `pydantic-settings` ผ่าน [platform_app/config.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/config.py) และ env prefix `PLATFORM_`
- auth ปัจจุบันใช้ `X-API-Key` ผ่าน [platform_app/auth.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/auth.py)
- persistent bootstrap pattern ที่มีอยู่แล้วคือ SQLite store ใน [platform_app/api_key_store.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/api_key_store.py)
- observability ที่มีอยู่ตอนนี้เป็น in-memory bundle และ route-level `obs.record(...)` ใน [platform_app/observability.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/observability.py)
- tests ปัจจุบันอยู่ใต้ `tests/` และใช้ `fastapi.testclient.TestClient`

### Inferred Assumptions

- เนื่องจากรีโปยังเป็น platform bootstrap, การเพิ่ม SQLite-backed ledger แยกไฟล์ DB จาก auth store เป็น pattern ที่สอดคล้องที่สุดและเสี่ยงต่ำ
- เนื่องจาก auth contract เดิมยังไม่ประกาศ scope สำหรับ workflow callback, slice นี้ใช้กลไก auth เดิมโดยไม่บังคับ scope ใหม่ เพื่อเลี่ยงการ cement contract เร็วเกินไป
- namespace `/v1/platform/workflows/...` เป็นทางเลือกที่ future-safe ที่สุดจาก route pattern ที่มีอยู่จริง

### Unknowns

- ยังไม่มี source-of-truth job admission model ในรีโปนี้ จึงยังไม่สามารถ enforce foreign key ระหว่าง event กับ job ได้อย่างปลอดภัย
- ยังไม่พบ contract กลางสำหรับ workflow status taxonomy จึงเก็บ `status` เป็น string แบบ append-friendly
- ยังไม่มี structured logging backend จริงนอกจาก in-memory observability bundle

## Files Changed

- [apps/platform_api/main.py](/d:/FlowBiz/flowbiz-ai-platform/apps/platform_api/main.py)
- [platform_app/config.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/config.py)
- [platform_app/deps.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/deps.py)
- [platform_app/routes/platform.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/routes/platform.py)
- [platform_app/routes/workflow_events.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/routes/workflow_events.py)
- [platform_app/workflow_events.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/workflow_events.py)
- [.env.example](/d:/FlowBiz/flowbiz-ai-platform/.env.example)
- [tests/test_workflow_events.py](/d:/FlowBiz/flowbiz-ai-platform/tests/test_workflow_events.py)
- [docs/platform/PLATFORM_SLICE_001_WORKFLOW_EVENT_LEDGER.md](/d:/FlowBiz/flowbiz-ai-platform/docs/platform/PLATFORM_SLICE_001_WORKFLOW_EVENT_LEDGER.md)

## Schema / Storage Summary

เพิ่ม SQLite store ใหม่ใน [platform_app/workflow_events.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/workflow_events.py) โดย bootstrap schema อัตโนมัติเมื่อ store ถูกสร้าง:

- table: `workflow_events`
- primary key: `id INTEGER PRIMARY KEY AUTOINCREMENT`
- columns:
  - `job_id TEXT NOT NULL`
  - `client_id TEXT NOT NULL`
  - `workflow_key TEXT NOT NULL`
  - `execution_id TEXT NULL`
  - `status TEXT NOT NULL`
  - `received_at TEXT NOT NULL`
  - `raw_payload TEXT NOT NULL`
  - `source TEXT NULL`
- index:
  - `idx_workflow_events_job_id` on `(job_id, received_at, id)`

storage strategy:

- ใช้ไฟล์ SQLite แยกจาก auth store ที่ `PLATFORM_WORKFLOW_EVENTS_SQLITE_PATH`
- เก็บ `raw_payload` เป็น JSON string ของ request body ทั้งก้อนหลัง validation
- ledger เป็น append-only insert + read by `job_id`
- ไม่มี projection table, replay queue, หรือ state machine ownership

## Endpoint Summary

### POST `/v1/platform/workflows/events`

วัตถุประสงค์:

- รับ workflow callback/event เข้าสู่ platform ledger

auth:

- ใช้กลไก `X-API-Key` เดิมของแพลตฟอร์ม
- เมื่อ `PLATFORM_AUTH_MODE=api_key` จะ reject หาก missing/invalid
- ไม่เพิ่ม scope ใหม่ใน slice นี้

request fields ขั้นต่ำ:

- `job_id`
- `client_id`
- `workflow_key`
- `status`

request fields รองรับ:

- `execution_id`
- `source`
- extra fields อื่น ๆ จะถูกเก็บใน `raw_payload`

response shape:

```json
{
  "status": "accepted",
  "record": {
    "id": 1,
    "job_id": "job-123",
    "client_id": "client-a",
    "workflow_key": "lead-enrichment",
    "execution_id": "exec-001",
    "status": "completed",
    "received_at": "2026-03-19T02:00:00.000+00:00",
    "raw_payload": {
      "job_id": "job-123",
      "client_id": "client-a"
    },
    "source": "n8n"
  }
}
```

### GET `/v1/platform/workflows/jobs/{job_id}/events`

วัตถุประสงค์:

- อ่าน event ledger ของ `job_id` แบบ read-only

response shape:

```json
{
  "status": "ok",
  "job_id": "job-123",
  "count": 1,
  "records": []
}
```

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
- pytest ผ่าน `16 passed`
- app import/startup path ใช้งานได้ และสร้าง app ได้สำเร็จ (`ok 10`)

behavior ที่พิสูจน์ด้วย test:

- valid authenticated intake persist ข้อมูลลง SQLite จริง
- missing auth ถูก reject ด้วย `401 Missing X-API-Key`
- invalid auth ถูก reject ด้วย `401 Invalid API key`
- lookup by `job_id` คืนเฉพาะ records ที่เกี่ยวข้อง
- validation failure จาก field ที่ขาด return `422`

สิ่งที่ไม่ได้ verify:

- ไม่มี integration กับ external callback source จริง
- ไม่มี load/performance test
- ไม่มี migration framework หรือ rollback automation เพราะ slice นี้ใช้ deterministic bootstrap schema แบบ SQLite

## Regression Risk

ความเสี่ยงหลัก:

- route compatibility: ต่ำ เพราะเพิ่ม route ใหม่และไม่เปลี่ยน path เดิม
- storage side effects: ต่ำ เพราะใช้ SQLite file แยกจาก auth store
- overlap กับ orchestration engine อนาคต: ปานกลาง หากอนาคตต้อง normalize status หรือ bind กับ job admission model
- bad contract cementing: ลดลงด้วยการเก็บ ledger แบบ append-friendly และเก็บ `raw_payload` เต็มก้อนโดยไม่บังคับ state machine ตอนนี้

tradeoff ที่เลือก:

- ไม่บังคับ scope ใหม่สำหรับ workflow route ใน slice นี้ เพื่อลด contract surface และ reuse auth mechanism เดิมให้แคบที่สุด
- ไม่สร้าง projection/current-state table เพราะจะทำให้ slice นี้ขยายเกิน ledger foothold

## Why This Slice Is Safe

- ใช้ pattern เดิมของรีโป: FastAPI router + settings + dependency cache + SQLite bootstrap
- เพิ่มเฉพาะ backend primitives ที่จำเป็นต่อ orchestration truth foothold
- ไม่มี broad refactor และไม่แตะ billing/dashboard/cutover
- ledger เก็บทั้ง normalized minimum fields และ `raw_payload` จึงรองรับ evolution รอบต่อไปได้โดยไม่ต้อง hard-code orchestration model เร็วเกินไป

## Out Of Scope

- job admission / creation record
- event-to-job status projection
- n8n cutover/forwarding control
- billing or entitlements
- admin/operator UI
- replay, dedupe, retries, reconciliation engine

## Next Recommended Slice

แนะนำ slice ถัดไปเพียงหนึ่งอย่าง:

- `event-to-job status projection model`

เหตุผล:

- ตอนนี้ platform มี append-only truth foothold แล้ว
- step ถัดไปที่ปลอดภัยที่สุดคือสร้าง read model/projection จาก ledger ไปสู่ current job status โดยยังไม่บังคับ cutover จาก runner และยังไม่ต้องรับ ownership เต็มของ orchestration engine
