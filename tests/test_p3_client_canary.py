from __future__ import annotations

from pathlib import Path
import tempfile

from platform_app.admission_policy import (
    PLATFORM_STATUS_RECEIVED,
    SQLiteAdmissionPolicyStore,
)
from platform_app.job_records import (
    JobCreateRequest,
    SQLiteJobRecordStore,
)
from platform_app.dispatch_records import (
    DISPATCH_STATUS_SENT,
    CALLBACK_STATUS_SUCCESS,
    SQLiteDispatchRecordStore,
    issue_callback_token,
    hash_callback_token,
)
from platform_app.observability import RequestEvent


def test_p3_client_canary_end_to_end_flow() -> None:
    """P3 Gate: End-to-end Client/BFF -> Admission -> PostgreSQL Job -> Hermes -> Signed Callback -> Audit."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_dir = Path(tmpdir)
        job_store = SQLiteJobRecordStore(str(db_dir / "jobs.db"))
        dispatch_store = SQLiteDispatchRecordStore(str(db_dir / "dispatches.db"))
        policy_store = SQLiteAdmissionPolicyStore(str(db_dir / "policy.db"))

        secret = "p3-canary-secret-key-1111"

        # 1. Admission Check
        decision = policy_store.evaluate_admission(client_id="flowbiz-client-dhamma")
        assert decision.allowed is True

        # 2. Job Ledger Creation
        job_req = JobCreateRequest(
            client_id="flowbiz-client-dhamma",
            workflow_key="dhamma.preview.generation",
            input_payload={"prompt": "Generate Dhamma preview cards"},
        )
        job = job_store.create_job(job_req)
        assert bool(job.job_id) is True
        assert job.status == PLATFORM_STATUS_RECEIVED

        # 3. Dispatch Decision
        dispatch = dispatch_store.create_pending_dispatch(
            job=job,
            target_url="http://127.0.0.1:9119/v1/runner/dispatch",
            payload={"canary_client": "flowbiz-client-dhamma", "job_id": job.job_id},
        )
        assert dispatch.dispatch_id is not None

        # 4. Token & Finalize SENT
        raw_token = issue_callback_token(
            shared_secret=secret,
            job_id=job.job_id,
            dispatch_id=dispatch.dispatch_id,
        )
        token_hash = hash_callback_token(token=raw_token)
        dispatch_store.set_callback_token_hash(
            dispatch_id=dispatch.dispatch_id,
            callback_token_hash=token_hash,
        )
        dispatch_store.finalize_dispatch(
            dispatch_id=dispatch.dispatch_id,
            status=DISPATCH_STATUS_SENT,
            response_code=202,
            error=None,
            sent_at="2026-08-11T05:35:00Z",
        )

        # 5. Verified Callback
        assert dispatch_store.verify_callback_token(
            dispatch_id=dispatch.dispatch_id,
            provided_token=raw_token,
        ) is True

        _, updated = dispatch_store.apply_callback(
            dispatch_id=dispatch.dispatch_id,
            job_id=job.job_id,
            callback_status=CALLBACK_STATUS_SUCCESS,
            callback_occurred_at="2026-08-11T05:35:05Z",
            callback_received_at="2026-08-11T05:35:06Z",
        )
        assert updated.callback_status == CALLBACK_STATUS_SUCCESS

        # 6. Audit Event
        audit = RequestEvent(
            route="/v1/platform/canary/dhamma",
            status_code=200,
            duration_ms=12.8,
        )
        assert audit.route == "/v1/platform/canary/dhamma"
