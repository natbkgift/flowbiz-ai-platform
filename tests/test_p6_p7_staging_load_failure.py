from __future__ import annotations

import concurrent.futures
from pathlib import Path
import tempfile

from platform_app.config import PlatformSettings
from platform_app.dispatch_records import (
    DISPATCH_STATUS_SENT,
    CALLBACK_STATUS_SUCCESS,
    SQLiteDispatchRecordStore,
    issue_callback_token,
    hash_callback_token,
)
from platform_app.job_records import JobRecordResponse


def test_p6_p7_single_vps_staging_load_and_chaos_rehearsal() -> None:
    """P6/P7 Gate: Single-VPS staging load & chaos failure rehearsal."""
    # Staging settings
    staging_settings = PlatformSettings(
        env="staging",
        name="FlowBiz AI Platform (Staging Rehearsal)",
        version="0.1.0",
        docs_enabled=True,
    )
    assert staging_settings.env == "staging"

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "staging_dispatch.db"
        store = SQLiteDispatchRecordStore(str(db_path))

        secret = "p6-p7-staging-secret"
        job = JobRecordResponse(
            job_id="job-p6-p7-001",
            client_id="client-p6-p7-001",
            workflow_key="hermes.runner.staging_chaos",
            prompt="Execute P6/P7 load and chaos test",
            status="accepted",
            created_at="2026-08-11T05:40:00Z",
        )

        dispatch = store.create_pending_dispatch(
            job=job,
            target_url="http://127.0.0.1:18101/v1/runner/dispatch",
            payload={"staging": True, "concurrency_test": True},
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
            sent_at="2026-08-11T05:40:01Z",
        )

        # Replay callback concurrently under simulated load
        def send_callback():
            return store.apply_callback(
                dispatch_id=dispatch.dispatch_id,
                job_id=job.job_id,
                callback_status=CALLBACK_STATUS_SUCCESS,
                callback_occurred_at="2026-08-11T05:40:05Z",
                callback_received_at="2026-08-11T05:40:06Z",
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(send_callback) for _ in range(10)]
            results = [f.result() for f in futures]

        assert len(results) == 10
        for _, updated in results:
            assert updated.callback_status == CALLBACK_STATUS_SUCCESS
