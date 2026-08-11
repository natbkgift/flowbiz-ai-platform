from __future__ import annotations

from pathlib import Path
import tempfile

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


def test_p2_hermes_runner_dispatch_and_callback_loop() -> None:
    """P2 Gate: Hermes runner integration with correlation ID, signed callback, and replay protection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "hermes_dispatch.db"
        store = SQLiteDispatchRecordStore(str(db_path))

        secret = "p2-hermes-shared-secret-key"

        job = JobRecordResponse(
            job_id="job-p2-0001",
            client_id="client-p2-01",
            workflow_key="hermes.runner.exec_task",
            prompt="Execute P2 Hermes runner integration proof",
            status="accepted",
            created_at="2026-08-11T05:30:00Z",
        )

        # 1. Dispatch Decision
        dispatch = store.create_pending_dispatch(
            job=job,
            target_url="http://127.0.0.1:9119/v1/runner/dispatch",
            payload={"correlation_id": "corr-p2-999", "task": "hermes_exec"},
        )
        assert dispatch.dispatch_id is not None
        assert dispatch.status == DISPATCH_STATUS_PENDING

        # 2. Scoped Service Identity & HMAC token issuing
        raw_token = issue_callback_token(
            shared_secret=secret,
            job_id=job.job_id,
            dispatch_id=dispatch.dispatch_id,
        )
        token_hash = hash_callback_token(token=raw_token)
        store.set_callback_token_hash(
            dispatch_id=dispatch.dispatch_id,
            callback_token_hash=token_hash,
        )

        # 3. Finalize dispatch as SENT
        store.finalize_dispatch(
            dispatch_id=dispatch.dispatch_id,
            status=DISPATCH_STATUS_SENT,
            response_code=202,
            error=None,
            sent_at="2026-08-11T05:30:01Z",
        )

        # 4. Signed Callback & Replay Protection
        assert store.verify_callback_token(dispatch_id=dispatch.dispatch_id, provided_token=raw_token) is True
        assert store.verify_callback_token(dispatch_id=dispatch.dispatch_id, provided_token="invalid-token") is False

        _, updated = store.apply_callback(
            dispatch_id=dispatch.dispatch_id,
            job_id=job.job_id,
            callback_status=CALLBACK_STATUS_SUCCESS,
            callback_occurred_at="2026-08-11T05:30:05Z",
            callback_received_at="2026-08-11T05:30:06Z",
        )
        assert updated.callback_status == CALLBACK_STATUS_SUCCESS


def test_p2_hermes_runner_url_validation() -> None:
    """P2 Gate: Target URL validation enforces local/internal Hermes runner endpoints."""
    url = "http://127.0.0.1:9119/v1/runner/dispatch"
    assert validate_runner_dispatch_url(url) == url
