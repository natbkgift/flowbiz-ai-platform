# PLATFORM_SLICE_006_API_KEY_LIFECYCLE_AUDIT

## Task Framing

เป้าหมายของ slice นี้คือเพิ่ม minimal API key lifecycle + durable audit trail ใน `flowbiz-ai-platform` โดย reuse auth SQLite store เดิมและไม่ขยายเป็น full admin/IAM system

สิ่งที่เพิ่ม:

- issue API key
- revoke API key
- durable audit trail สำหรับ lifecycle actions
- protected lifecycle endpoints ที่ reuse auth/scopes เดิม

สิ่งที่ไม่ทำ:

- full admin UI
- RBAC
- tenant redesign
- billing hooks
- policy/admin workflow system

## Schema / Storage Changes

auth store เดิมใน [api_key_store.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/api_key_store.py) ถูกขยายให้รองรับ:

- `api_keys.client_id`
- table `api_key_audit_events`

audit fields:

- `id`
- `client_id`
- `action`
- `key_id`
- `actor`
- `created_at`
- `metadata`

storage behavior:

- ใช้ SQLite auth DB เดิม (`PLATFORM_AUTH_SQLITE_PATH`)
- issuance และ revoke จะ append audit record แบบ deterministic
- plaintext secret ไม่ถูกเก็บใน audit

## Endpoint Contracts

เพิ่ม endpoint ใต้ namespace เดิม `/v1/platform`:

- `POST /v1/platform/api-keys`
- `POST /v1/platform/api-keys/{key_id}/revoke`
- `GET /v1/platform/api-keys/audit`

contract rules:

- issue endpoint return plaintext API key ครั้งเดียวในรูป `key_id:secret`
- revoke endpoint ไม่ return secret
- audit endpoint return audit events เท่านั้น
- lifecycle endpoints require scope `platform:api_keys:manage` เมื่อ auth เปิดใช้งาน
- existing `X-API-Key` request contract ไม่เปลี่ยน

## Secret Handling Rules

- raw secret ถูกสร้างและ return เฉพาะตอน issue
- audit response ไม่ expose plaintext secret
- revoke/audit/list path ไม่ expose plaintext secret
- stored auth path ยังตรวจด้วย hash เหมือนเดิม

## Files Changed

- [platform_app/api_key_store.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/api_key_store.py)
- [platform_app/deps.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/deps.py)
- [platform_app/routes/platform.py](/d:/FlowBiz/flowbiz-ai-platform/platform_app/routes/platform.py)
- [tests/test_api_key_lifecycle.py](/d:/FlowBiz/flowbiz-ai-platform/tests/test_api_key_lifecycle.py)
- [docs/platform/PLATFORM_SLICE_006_API_KEY_LIFECYCLE_AUDIT.md](/d:/FlowBiz/flowbiz-ai-platform/docs/platform/PLATFORM_SLICE_006_API_KEY_LIFECYCLE_AUDIT.md)

## Validation Evidence

คำสั่งที่รันจริง:

```powershell
ruff check platform_app apps tests
pytest tests/test_platform_smoke.py tests/test_auth_and_rate_limit.py tests/test_workflow_events.py tests/test_job_records.py tests/test_dispatch_records.py tests/test_admission_policy.py tests/test_api_key_lifecycle.py
@'
from apps.platform_api.main import create_app
app = create_app()
print("ok", len(app.routes))
'@ | python - 2>&1
```

ผลที่ยืนยันได้:

- `ruff check` ผ่าน
- pytest ผ่าน `44 passed`
- startup/import ผ่าน (`ok 18`)

behavior ที่พิสูจน์ด้วย test:

- key issuance สำเร็จ
- newly issued key ใช้งาน auth path จริงได้
- revoked key ถูก reject deterministically
- audit record ถูกสร้างทั้งตอน issue และ revoke
- audit response ไม่ leak raw secret
- prior slice tests ยังผ่านทั้งหมด

## Regression Risks

- auth compatibility risk: ต่ำ เพราะ `authenticate_api_key()` path เดิมยังใช้ hash + disabled flag เดิม
- secret leakage risk: ลดลงด้วยการ return secret เฉพาะตอน issue
- lifecycle route hardening risk: จำกัดด้วย manage scope เดิม ไม่เพิ่ม auth model ใหม่
- coupling risk: ต่ำ เพราะ route ใหม่ไม่แตะ job/dispatch/event logic

## Why This Slice Is Safe

- reuse SQLite auth store pattern เดิม
- ขยายเฉพาะ lifecycle surface ขั้นต่ำ
- preserve existing request auth semantics
- durable audit trail อยู่ใน platform repo ตาม ownership ที่ต้องการ

## Next Slice

แนะนำถัดไป:

- Job List / Operator Read Model
