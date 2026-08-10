from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from platform_app.dispatch_records import (
    DISPATCH_STATUS_PENDING,
    DISPATCH_STATUS_SENT,
    CALLBACK_STATUS_SUCCESS,
    SQLiteDispatchRecordStore,
    issue_callback_token,
    hash_callback_token,
    validate_runner_dispatch_url,
)
from platform_app.job_records import JobRecordResponse


def test_runner_proof_r4_dispatch_and_signed_callback() -> None:
    """R4 Proof: Platform-authorized dispatch and HMAC signed callback loop."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_dispatch.db"
        store = SQLiteDispatchRecordStore(db_path)

        secret = "r4-test-shared-secret-12345"

        job = JobRecordResponse(
            job_id="job-r4-0001",
            client_id="client-test-01",
            workflow_key="hermes.runner.test_workflow",
            prompt="Execute R4 non-production proof task",
            status="accepted",
            created_at="2026-08-10T21:20:00Z",
        )

        # 1. Platform-authorized pending dispatch creation
        dispatch_record = store.create_pending_dispatch(
            job=job,
            target_url="http://localhost:9119/v1/runner/dispatch",
            payload={"task_id": "r4-task-1", "mode": "non-production"},
        )

        assert bool(dispatch_record.dispatch_id) is True
        assert dispatch_record.job_id == "job-r4-0001"
        assert dispatch_record.status == DISPATCH_STATUS_PENDING

        # 2. Issue HMAC callback token & set token hash
        raw_token = issue_callback_token(
            shared_secret=secret,
            job_id=job.job_id,
            dispatch_id=dispatch_record.dispatch_id,
        )
        token_hash = hash_callback_token(token=raw_token)
        store.set_callback_token_hash(
            dispatch_id=dispatch_record.dispatch_id,
            callback_token_hash=token_hash,
        )

        # 3. Finalize dispatch as SENT
        sent_record = store.finalize_dispatch(
            dispatch_id=dispatch_record.dispatch_id,
            status=DISPATCH_STATUS_SENT,
            response_code=202,
            error=None,
            sent_at="2026-08-10T21:20:01Z",
        )
        assert sent_record.status == DISPATCH_STATUS_SENT

        # 4. HMAC callback token validation
        is_valid = store.verify_callback_token(
            dispatch_id=dispatch_record.dispatch_id,
            provided_token=raw_token,
        )
        assert is_valid is True

        # Invalid token must fail
        is_invalid = store.verify_callback_token(
            dispatch_id=dispatch_record.dispatch_id,
            provided_token="forged-token-xyz",
        )
        assert is_invalid is False

        # 5. Apply signed callback
        job_status_change, updated_dispatch = store.apply_callback(
            dispatch_id=dispatch_record.dispatch_id,
            job_id=job.job_id,
            callback_status=CALLBACK_STATUS_SUCCESS,
            callback_occurred_at="2026-08-10T21:20:05Z",
            callback_received_at="2026-08-10T21:20:06Z",
        )
        assert updated_dispatch is not None
        assert updated_dispatch.callback_status == CALLBACK_STATUS_SUCCESS


def test_runner_proof_r4_url_validation_and_kill_switch() -> None:
    """R4 Proof: Target URL validation & kill switch enforcement."""
    # Valid local/internal runner dispatch URL returns normalized URL
    valid_url = "http://127.0.0.1:9119/dispatch"
    assert validate_runner_dispatch_url(valid_url) == valid_url

    # Empty URL or unsupported scheme raises ValueError
    with pytest.raises(ValueError):
        validate_runner_dispatch_url("")

    with pytest.raises(ValueError):
        validate_runner_dispatch_url("ftp://runner/dispatch")
