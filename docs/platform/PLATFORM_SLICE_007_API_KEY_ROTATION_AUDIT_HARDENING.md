# PLATFORM_SLICE_007_API_KEY_ROTATION_AUDIT_HARDENING

## Task Framing

เป้าหมายของ slice นี้คือขยาย API key lifecycle เฉพาะจุดที่ยังขาดอยู่:

- rotate API key แบบ deterministic
- harden audit trail ด้วย `event_type`, `actor_type`, `actor_id`, และ `reason`

สิ่งที่จงใจไม่ทำ:

- admin UI
- RBAC redesign
- billing/policy changes
- job/dispatch/workflow coupling
- speculative lifecycle surface อื่นนอกเหนือจาก rotate

## System Analysis

ข้อเท็จจริงที่ยืนยันจากรีโป:

- auth path ปัจจุบันยังใช้ `X-API-Key: key_id:secret`
- Slice 6 ใช้ SQLite auth store เดิมใน [api_key_store.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/api_key_store.py)
- lifecycle routes อยู่ใต้ [platform.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/routes/platform.py)
- audit trail มีอยู่แล้ว แต่ actor/reason ยังไม่พอสำหรับ incident review

ข้อสันนิษฐานที่ใช้:

- narrow actor abstraction ที่ปลอดภัยสุดตอนนี้คือ `actor_type=api_key` และ `actor_id=<principal.key_id>`
- rotate ที่ปลอดภัยสุดคือ re-issue secret ให้ `key_id` เดิม แล้ว append audit chain แยกชัดเจน

สิ่งที่ยังไม่ทำ:

- full identity model
- human admin directory
- role inheritance

## Selected Safe Slice

เพิ่มเฉพาะ:

- `POST /v1/platform/api-keys/{key_id}/rotate`
- audit fields ใหม่:
  - `event_type`
  - `actor_type`
  - `actor_id`
  - `reason`

rotate behavior:

- return plaintext secret ใหม่ครั้งเดียว
- old secret ใช้งานไม่ได้หลัง rotate
- new secret ใช้ auth path เดิมได้ทันที
- audit append แบบ distinct event chain:
  - `issued`
  - `rotated`
  - `revoked_by_rotation`

## Implementation Plan

- ขยาย SQLite auth schema แบบ additive
- migrate audit table แบบ deterministic ด้วย `ALTER TABLE` เมื่อ field ใหม่ยังไม่มี
- wire reason/actor จาก route layer ลง store
- preserve `action` และ `actor` ใน audit response เพื่อ backward compatibility
- เพิ่ม test เฉพาะ rotate + audit hardening

## Code Changes

ไฟล์ที่แก้:

- [platform_app/api_key_store.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/api_key_store.py)
- [platform_app/routes/platform.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/routes/platform.py)
- [tests/test_api_key_lifecycle.py](/d:/FlowBiz/flowbiz-ai-platform/tests/test_api_key_lifecycle.py)
- [docs/platform/PLATFORM_SLICE_007_API_KEY_ROTATION_AUDIT_HARDENING.md](/d:/FlowBiz/flowbiz-ai-platform/docs/platform/PLATFORM_SLICE_007_API_KEY_ROTATION_AUDIT_HARDENING.md)

storage change summary:

- table `api_key_audit_events` รองรับ `actor_type`, `actor_id`, `reason`
- audit rows ยังเก็บ `action` เดิมเพื่อ compatibility
- `event_type` ถูก expose ใน response โดย mirror จาก `action`

endpoint summary:

- `POST /v1/platform/api-keys/{key_id}/rotate`
  - require scope `platform:api_keys:manage`
  - body รองรับ `reason` แบบ optional
  - return plaintext key ใหม่ครั้งเดียว
- `POST /v1/platform/api-keys/{key_id}/revoke`
  - รองรับ `reason` แบบ optional โดยไม่เปลี่ยน revoke contract หลัก
- `GET /v1/platform/api-keys/audit`
  - return both legacy fields (`action`, `actor`) and hardened fields (`event_type`, `actor_type`, `actor_id`, `reason`)

## Security Guarantees

- plaintext secret return เฉพาะตอน issue หรือ rotate response ครั้งเดียว
- audit/read path ไม่ leak raw secret เก่า/ใหม่
- old secret ถูก reject deterministically หลัง rotate
- new secret authenticate ผ่าน path เดิมโดยไม่เปลี่ยน `X-API-Key` contract
- actor context เพียงพอสำหรับ future incident review โดยไม่ต้อง introduce full identity model

## Explicit Non-Goals

- rotate batch operations
- key search/list admin console
- RBAC / tenant admin workflows
- coupling ไปยัง job admission หรือ dispatch
- broader IAM redesign

## Validation Evidence

คำสั่งที่ต้องยืนยันใน slice นี้:

```powershell
ruff check platform_app apps tests
pytest tests/test_platform_smoke.py tests/test_auth_and_rate_limit.py tests/test_workflow_events.py tests/test_job_records.py tests/test_dispatch_records.py tests/test_admission_policy.py tests/test_api_key_lifecycle.py
@'
from apps.platform_api.main import create_app
app = create_app()
print("ok", len(app.routes))
'@ | python - 2>&1
```

behavior ที่ต้องพิสูจน์:

- rotate success path ทำงานจริง
- old key ถูก reject หลัง rotate
- new key authenticate ได้
- audit rows มี actor/reason
- audit ไม่ leak plaintext secret
- prior auth/lifecycle behavior ยังผ่าน

## Regression Risks

- backward compatibility risk: ต่ำ เพราะ `action`/`actor` ยังถูก preserve
- identity overdesign risk: จำกัดด้วย actor abstraction แคบเพียง `actor_type` + `actor_id`
- secret leakage risk: ลดด้วย test ที่ assert ว่า audit ไม่เผย plaintext
- auth contract risk: ต่ำ เพราะ `authenticate_api_key()` ไม่ถูก redesign

## Next Recommended Slice

- Job List / Operator Read Model
