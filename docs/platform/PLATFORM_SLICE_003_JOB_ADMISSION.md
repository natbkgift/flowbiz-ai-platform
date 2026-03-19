# PLATFORM_SLICE_003_JOB_ADMISSION

## Task Framing

เป้าหมายของ slice นี้คือทำให้ platform เป็น owner ของการสร้าง job โดยเพิ่ม admission record ก่อน execution แต่ยังไม่แตะ dispatch/orchestration

## Schema

table: `workflow_jobs`

fields:

- `job_id` (platform-generated UUID, primary key)
- `client_id`
- `workflow_key`
- `status` (initial = `received`)
- `created_at`
- `input_payload` (optional JSON)
- `metadata` (optional JSON)

storage design:

- ใช้ SQLite file เดียวกับ workflow ledger เพื่อให้ workflow domain อยู่ใน persistence boundary เดียวกัน
- `workflow_jobs` เป็น source of truth สำหรับ job existence
- event ledger ยังคงเป็น source of truth สำหรับ workflow event truth

## Files Changed

- [platform_app/job_records.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/job_records.py)
- [platform_app/deps.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/deps.py)
- [platform_app/routes/workflow_events.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/routes/workflow_events.py)
- [tests/test_job_records.py](/d:/FlowBiz/flowbiz-ai-platform/tests/test_job_records.py)
- [docs/platform/PLATFORM_SLICE_003_JOB_ADMISSION.md](/d:/FlowBiz/flowbiz-ai-platform/docs/platform/PLATFORM_SLICE_003_JOB_ADMISSION.md)

## Endpoints

- `POST /v1/platform/workflows/jobs`
- `GET /v1/platform/workflows/jobs/{job_id}/record`

หมายเหตุ:

- route `GET /v1/platform/workflows/jobs/{job_id}` ถูกใช้ไปแล้วใน Slice 2 สำหรับ projected current state
- จึงใช้ `/record` เพื่อ preserve contract เดิมและเลี่ยง route conflict

## Validation Evidence

คำสั่งที่ต้องรันจริงสำหรับ slice นี้:

```powershell
ruff check platform_app apps tests
pytest tests/test_platform_smoke.py tests/test_auth_and_rate_limit.py tests/test_workflow_events.py tests/test_job_records.py
@'
from apps.platform_api.main import create_app
app = create_app()
print("ok", len(app.routes))
'@ | python -
```

ผลที่ยืนยันได้:

- `ruff check` ผ่าน
- pytest ผ่าน `28 passed`
- startup/import ผ่าน (`ok 13`)

behavior ที่พิสูจน์ด้วย test:

- create job สำเร็จและได้ platform-generated `job_id`
- invalid payload ถูก reject
- auth behavior ของ create endpoint ตาม convention เดิม
- lookup คืน base admission record ถูกต้อง
- `job_id` ซ้ำกันไม่เกิดขึ้นใน targeted tests
- job record กับ workflow event ledger อยู่ร่วมกันได้โดยไม่ชนกัน

## Regression Risk

- route conflict risk: แก้โดยคง projection route เดิมไว้ และใช้ `/jobs/{job_id}/record` สำหรับ base record
- DB collision risk: ต่ำ เพราะใช้คนละ table (`workflow_jobs` vs `workflow_events`) ใน SQLite file เดียวกัน
- contract expansion risk: ต่ำ เพราะยังไม่มี dispatch/status transition logic
- orchestration creep risk: ต่ำ เพราะยังไม่มี runner integration หรือ execution control

## Safety Summary

- platform เป็นคนสร้าง `job_id` เอง
- initial status ถูกตรึงเป็น `received`
- ไม่มี dispatch, scheduler, retry, หรือ runner integration
- job record และ projection route coexist กันโดยไม่ทับ contract

## Next Slice

แนะนำถัดไป:

- lightweight job list/read model from admission + projection state
