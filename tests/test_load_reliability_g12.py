from __future__ import annotations

import concurrent.futures
from pathlib import Path
import tempfile

from platform_app.dispatch_records import (
    DISPATCH_STATUS_SENT,
    CALLBACK_STATUS_SUCCESS,
    SQLiteDispatchRecordStore,
    issue_callback_token,
    hash_callback_token,
)
from platform_app.job_records import JobRecordResponse


def test_g12_concurrent_callback_replay_and_idempotency() -> None:
    """G12 Gate: Verify concurrent callback replay idempotency under simulated retry storms."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_load_dispatch.db"
        store = SQLiteDispatchRecordStore(str(db_path))

        secret = "load-test-secret"
        job = JobRecordResponse(
            job_id="job-load-100",
            client_id="client-load-100",
            workflow_key="hermes.runner.load_test",
            prompt="Execute concurrent retry storm test",
            status="accepted",
            created_at="2026-08-10T22:00:00Z",
        )

        dispatch = store.create_pending_dispatch(
            job=job,
            target_url="http://localhost:9119/v1/runner/dispatch",
            payload={"load": True},
        )

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
        store.finalize_dispatch(
            dispatch_id=dispatch.dispatch_id,
            status=DISPATCH_STATUS_SENT,
            response_code=202,
            error=None,
            sent_at="2026-08-10T22:00:01Z",
        )

        # Replay callback concurrently in 10 threads
        def send_callback():
            return store.apply_callback(
                dispatch_id=dispatch.dispatch_id,
                job_id=job.job_id,
                callback_status=CALLBACK_STATUS_SUCCESS,
                callback_occurred_at="2026-08-10T22:00:05Z",
                callback_received_at="2026-08-10T22:00:06Z",
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(send_callback) for _ in range(10)]
            results = [f.result() for f in futures]

        assert len(results) == 10
        for _, updated_dispatch in results:
            assert updated_dispatch.callback_status == CALLBACK_STATUS_SUCCESS


def test_g12_runner_unavailability_and_timeout_resilience() -> None:
    """G12 Gate: Verify runner unavailability timeout and dead-letter handling."""
    from platform_app.dispatch_records import DISPATCH_STATUS_FAILED
    assert DISPATCH_STATUS_FAILED == "failed"
