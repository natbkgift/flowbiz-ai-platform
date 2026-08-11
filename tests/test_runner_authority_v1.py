from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from packages.core.contracts.platform_runner import (
    PlatformRunnerDispatch,
    RunnerCompletionCallback,
)
from platform_app.db.models import Base
from platform_app.runner_security import (
    RunnerSignatureError,
    sign_callback,
    verify_callback_signature,
)


def test_postgres_maps_authoritative_runner_tables() -> None:
    assert {"runner_dispatches", "runner_callbacks"} <= set(Base.metadata.tables)
    dispatch = Base.metadata.tables["runner_dispatches"]
    callback = Base.metadata.tables["runner_callbacks"]
    assert dispatch.c.tenant_id.nullable is False
    assert callback.c.tenant_id.nullable is False
    assert any(
        constraint.name == "uq_runner_dispatches_tenant_idempotency"
        for constraint in dispatch.constraints
    )
    assert any(
        constraint.name == "uq_runner_callbacks_tenant_idempotency"
        for constraint in callback.constraints
    )


def test_callback_signature_binds_timestamp_and_exact_body() -> None:
    secret = "test-only-callback-secret"
    timestamp = "1786480000"
    body = b'{"status":"succeeded"}'
    signature = sign_callback(secret, timestamp, body)
    verify_callback_signature(
        secret=secret,
        timestamp=timestamp,
        signature=signature,
        body=body,
        max_clock_skew_seconds=300,
        now=1786480000,
    )
    with pytest.raises(RunnerSignatureError, match="invalid callback signature"):
        verify_callback_signature(
            secret=secret,
            timestamp=timestamp,
            signature=signature,
            body=body + b" ",
            max_clock_skew_seconds=300,
            now=1786480000,
        )
    with pytest.raises(RunnerSignatureError, match="stale callback"):
        verify_callback_signature(
            secret=secret,
            timestamp=timestamp,
            signature=signature,
            body=body,
            max_clock_skew_seconds=300,
            now=1786481000,
        )


def test_core_v1_contract_round_trip_is_strict() -> None:
    now = datetime.now(UTC)
    dispatch = PlatformRunnerDispatch.model_validate_json(
        json.dumps(
            {
                "contract_version": "1.0",
                "dispatch_id": "dispatch-test-1",
                "job_id": "job-test-1",
                "workflow_key": "hermes.repo_inventory",
                "inputs": {"action": "read_only", "target_paths": []},
                "trace_id": "trace-test-1",
                "correlation_id": "corr-test-1",
                "idempotency_key": "dispatch:test-1",
                "callback_url": "http://platform:8100/internal/platform/v1/runner/callbacks",
                "dispatched_at": now.isoformat(),
                "deadline_at": None,
            }
        )
    )
    callback = RunnerCompletionCallback(
        contract_version="1.0",
        callback_id="callback-test-1",
        dispatch_id=dispatch.dispatch_id,
        job_id=dispatch.job_id,
        runner_id="hermes-readonly-1",
        status="succeeded",
        attempt=1,
        idempotency_key="callback:dispatch-test-1:1",
        result={"mode": "repo_inventory"},
        error=None,
        trace_id=dispatch.trace_id,
        correlation_id=dispatch.correlation_id,
        completed_at=now,
    )
    assert RunnerCompletionCallback.model_validate_json(callback.model_dump_json()) == callback
