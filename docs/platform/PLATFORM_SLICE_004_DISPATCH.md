# PLATFORM_SLICE_004_DISPATCH

## Task Framing

เป้าหมายของ slice นี้คือเพิ่ม controlled dispatch / runner handoff แบบ platform-owned โดยไม่ขยายเป็น workflow engine

สิ่งที่เพิ่ม:

- dispatch audit record ของแพลตฟอร์ม
- explicit dispatch action ต่อ job ที่มีอยู่แล้ว
- outbound HTTP POST ไปยัง runner endpoint ที่ตั้งค่าผ่าน config
- correlation กับ `job_id` เดิม

สิ่งที่ไม่ทำ:

- retry engine
- scheduler / queue
- policy/quota
- billing
- background worker
- runner-specific adapter

## Schema

table: `workflow_dispatches`

fields:

- `dispatch_id` (UUID)
- `job_id`
- `client_id`
- `workflow_key`
- `target_url`
- `payload`
- `status` (`pending | sent | failed`)
- `response_code`
- `error`
- `created_at`
- `sent_at`

storage design:

- ใช้ SQLite file เดียวกับ workflow domain เดิม
- dispatch record เป็น audit trail ของ outbound handoff
- job record ยังเป็น source of truth สำหรับ job existence
- event ledger ยังเป็น source of truth สำหรับ event truth

## Endpoint Contracts

- `POST /v1/platform/workflows/jobs/{job_id}/dispatch`
- `GET /v1/platform/workflows/jobs/{job_id}/dispatches`

runner request payload ขั้นต่ำ:

- `job_id`
- `client_id`
- `workflow_key`
- `payload`
- `callback_url`

## Dispatch Flow

1. validate ว่า job มีอยู่จริง
2. create dispatch record ด้วยสถานะ `pending`
3. ส่ง HTTP POST ไปยัง runner endpoint
4. finalize dispatch record
5. success -> `sent`
6. failure -> `failed`

หมายเหตุ:

- dispatch failure ไม่แก้ job status
- ไม่มี retry/backoff ใน slice นี้
- ไม่มี background processing

## Files Changed

- [platform_app/config.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/config.py)
- [platform_app/deps.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/deps.py)
- [platform_app/dispatch_records.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/dispatch_records.py)
- [platform_app/routes/workflow_events.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/routes/workflow_events.py)
- [.env.example](/d:/FlowBiz/flowbiz-ai-platform/.env.example)
- [tests/test_dispatch_records.py](/d:/FlowBiz/flowbiz-ai-platform/tests/test_dispatch_records.py)
- [docs/platform/PLATFORM_SLICE_004_DISPATCH.md](/d:/FlowBiz/flowbiz-ai-platform/docs/platform/PLATFORM_SLICE_004_DISPATCH.md)

## Validation Evidence

คำสั่งที่รันจริง:

```powershell
ruff check platform_app apps tests
pytest tests/test_platform_smoke.py tests/test_auth_and_rate_limit.py tests/test_workflow_events.py tests/test_job_records.py tests/test_dispatch_records.py
@'
from apps.platform_api.main import create_app
app = create_app()
print("ok", len(app.routes))
'@ | python -
```

## Regression Risk

- route contract risk: ต่ำ เพราะเพิ่มเฉพาะ dispatch routes ใหม่
- job admission interference risk: ต่ำ เพราะ dispatch ต้องอ้าง job ที่มีอยู่แล้วเท่านั้น
- projection interference risk: ต่ำ เพราะ dispatch failure ไม่แก้ projected job state โดยตรง
- orchestration creep risk: ต่ำ เพราะยังไม่มี retry, queue, scheduler, หรือ policy engine

## Next Slice

แนะนำถัดไป:

- Policy / Quota Gate at Admission
