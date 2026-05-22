from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from apps.platform_api.main import create_app
from platform_app.approval_models import ConnectorRegistration
from platform_app.approval_policy import SQLiteApprovalPolicyStore
from platform_app.approval_records import SQLiteApprovalRecordStore, resolve_approval_gate_db_path
from platform_app.config import get_settings
from platform_app.connector_store import SQLiteConnectorStore
from platform_app.deps import (
    get_admission_policy_store,
    get_api_key_store,
    get_approval_audit_store,
    get_approval_connector_store,
    get_approval_policy_store,
    get_approval_record_store,
    get_auth_dependency,
    get_dispatch_record_store,
    get_job_record_store,
    get_llm_adapter,
    get_rate_limiter,
    get_runner_dispatcher,
    get_secret_provider_bundle,
    get_workflow_event_store,
)


def _clear_caches() -> None:
    get_settings.cache_clear()
    get_secret_provider_bundle.cache_clear()
    get_llm_adapter.cache_clear()
    get_rate_limiter.cache_clear()
    get_api_key_store.cache_clear()
    get_auth_dependency.cache_clear()
    get_workflow_event_store.cache_clear()
    get_job_record_store.cache_clear()
    get_dispatch_record_store.cache_clear()
    get_runner_dispatcher.cache_clear()
    get_admission_policy_store.cache_clear()
    get_approval_connector_store.cache_clear()
    get_approval_policy_store.cache_clear()
    get_approval_record_store.cache_clear()
    get_approval_audit_store.cache_clear()


@pytest.fixture(autouse=True)
def _reset_platform_caches():
    _clear_caches()
    yield
    _clear_caches()


def _client(monkeypatch: pytest.MonkeyPatch, tmp_path) -> TestClient:
    monkeypatch.setenv(
        "PLATFORM_APPROVAL_GATE_SQLITE_PATH",
        str(tmp_path / "approval_gate.db"),
    )
    _clear_caches()
    return TestClient(create_app())


def _db_path(tmp_path) -> str:
    return resolve_approval_gate_db_path(str(tmp_path / "approval_gate.db"))


def _connector_store(tmp_path) -> SQLiteConnectorStore:
    return SQLiteConnectorStore(db_path=_db_path(tmp_path))


def _policy_store(tmp_path) -> SQLiteApprovalPolicyStore:
    return SQLiteApprovalPolicyStore(db_path=_db_path(tmp_path))


def _record_store(tmp_path) -> SQLiteApprovalRecordStore:
    return SQLiteApprovalRecordStore(db_path=_db_path(tmp_path))


def _headers(api_key: str = "connector-secret") -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _register_connector(
    tmp_path,
    *,
    connector_id: str = "n8n-main",
    api_key: str = "connector-secret",
    action_classes: tuple[str, ...] = ("crm.contact.update", "crm.campaign.send"),
) -> None:
    _connector_store(tmp_path).upsert_connector(
        ConnectorRegistration(
            connector_id=connector_id,
            connector_name="n8n Main",
            allowed_action_classes=action_classes,
            api_key=api_key,
            callback_url=None,
        )
    )


def _seed_policy(
    tmp_path,
    *,
    policy_id: str = "policy-contact-update",
    action_class: str = "crm.contact.update",
    allowed_mutation_types: tuple[str, ...] = ("update",),
    auto_allow_risk_levels: tuple[str, ...] = ("LOW", "MEDIUM"),
    approval_required_from: str | None = None,
) -> None:
    _policy_store(tmp_path).upsert_policy(
        policy_id=policy_id,
        action_class=action_class,
        allowed_mutation_types=allowed_mutation_types,
        auto_allow_risk_levels=auto_allow_risk_levels,
        approval_required_from=approval_required_from,
    )


def _proposal(
    *,
    proposal_id: str = "proposal-001",
    connector_id: str = "n8n-main",
    action_class: str = "crm.contact.update",
    target_system: str = "hubspot-prod",
    scope_type: str = "single",
    record_count: int = 1,
    mutation_type: str = "update",
    requested_by: str = "sales-ops-user",
) -> dict[str, object]:
    return {
        "proposal_id": proposal_id,
        "connector_id": connector_id,
        "action_class": action_class,
        "target_system": target_system,
        "target_scope": {
            "type": scope_type,
            "estimated_record_count": record_count,
        },
        "mutation_type": mutation_type,
        "payload_summary": "Update contact lifecycle stage",
        "payload_hash": "a" * 64,
        "triggering_signal": {
            "source": "hubspot-prod-webhook",
            "signal_id": f"signal-{proposal_id}",
            "signal_timestamp": "2026-05-21T12:00:00Z",
        },
        "submitted_at": "2026-05-21T12:00:01Z",
        "requested_by": requested_by,
    }


def test_allow_path_writes_audit(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    _register_connector(tmp_path)
    _seed_policy(tmp_path)

    response = client.post(
        "/v1/gate/proposals",
        headers=_headers(),
        json=_proposal(),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "ALLOW"
    assert data["reason_code"] == "POLICY_ALLOWED"
    assert data["decision_id"]
    audits = get_approval_audit_store().list_by_proposal_id("proposal-001")
    assert len(audits) == 1
    assert audits[0].decision_id == data["decision_id"]


def test_deny_no_matching_policy_for_unknown_action_class(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    _register_connector(tmp_path, action_classes=("workflow.trigger",))

    response = client.post(
        "/v1/gate/proposals",
        headers=_headers(),
        json=_proposal(
            proposal_id="proposal-no-policy",
            action_class="workflow.trigger",
            mutation_type="other",
        ),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "DENY"
    assert data["reason_code"] == "NO_MATCHING_POLICY"
    assert get_approval_audit_store().count_by_proposal_id("proposal-no-policy") == 1


def test_deny_by_default_when_no_allow_rule_matches(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    _register_connector(tmp_path)
    _seed_policy(
        tmp_path,
        action_class="crm.contact.update",
        allowed_mutation_types=("create",),
    )

    response = client.post(
        "/v1/gate/proposals",
        headers=_headers(),
        json=_proposal(proposal_id="proposal-deny-default"),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "DENY"
    assert data["reason_code"] == "NO_MATCHING_POLICY"
    assert get_approval_audit_store().count_by_proposal_id("proposal-deny-default") == 1


def test_needs_approval_for_high_risk_bulk_send(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    _register_connector(tmp_path)
    _seed_policy(
        tmp_path,
        policy_id="policy-campaign-send",
        action_class="crm.campaign.send",
        allowed_mutation_types=("send",),
        auto_allow_risk_levels=("LOW", "MEDIUM"),
        approval_required_from="sales-ops-manager",
    )

    response = client.post(
        "/v1/gate/proposals",
        headers=_headers(),
        json=_proposal(
            proposal_id="proposal-needs-approval",
            action_class="crm.campaign.send",
            scope_type="bulk",
            record_count=847,
            mutation_type="send",
            requested_by="n8n connector",
        ),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "NEEDS_APPROVAL"
    assert data["risk_level"] == "HIGH"
    assert data["reason_code"] == "APPROVAL_REQUIRED"
    assert data["approval_required_from"] == "sales-ops-manager"
    assert data["approval_queue_id"] == "approval-proposal-needs-approval"
    assert get_approval_audit_store().count_by_proposal_id("proposal-needs-approval") == 1


def test_needs_approval_for_medium_risk_when_policy_has_approver(
    monkeypatch,
    tmp_path,
) -> None:
    client = _client(monkeypatch, tmp_path)
    _register_connector(tmp_path)
    _seed_policy(
        tmp_path,
        allowed_mutation_types=("delete",),
        auto_allow_risk_levels=("LOW",),
        approval_required_from="sales-ops-manager",
    )

    response = client.post(
        "/v1/gate/proposals",
        headers=_headers(),
        json=_proposal(
            proposal_id="proposal-medium-approval",
            scope_type="bulk",
            mutation_type="delete",
        ),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "NEEDS_APPROVAL"
    assert data["risk_level"] == "MEDIUM"
    assert data["reason_code"] == "APPROVAL_REQUIRED"
    assert data["approval_required_from"] == "sales-ops-manager"


def test_deny_when_matching_policy_does_not_permit_risk_level(
    monkeypatch,
    tmp_path,
) -> None:
    client = _client(monkeypatch, tmp_path)
    _register_connector(tmp_path)
    _seed_policy(
        tmp_path,
        allowed_mutation_types=("delete",),
        auto_allow_risk_levels=("LOW",),
    )

    response = client.post(
        "/v1/gate/proposals",
        headers=_headers(),
        json=_proposal(
            proposal_id="proposal-risk-denied",
            scope_type="bulk",
            mutation_type="delete",
        ),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "DENY"
    assert data["risk_level"] == "MEDIUM"
    assert data["reason_code"] == "RISK_LEVEL_NOT_PERMITTED"


def test_connector_auth_failure_for_unregistered_connector(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)

    response = client.post(
        "/v1/gate/proposals",
        headers=_headers("unknown-secret"),
        json=_proposal(),
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid connector API key"


def test_connector_action_class_not_permitted(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    _register_connector(tmp_path, action_classes=("crm.contact.update",))
    _seed_policy(
        tmp_path,
        policy_id="policy-campaign-send",
        action_class="crm.campaign.send",
        allowed_mutation_types=("send",),
    )

    response = client.post(
        "/v1/gate/proposals",
        headers=_headers(),
        json=_proposal(
            proposal_id="proposal-disallowed-class",
            action_class="crm.campaign.send",
            mutation_type="send",
        ),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "DENY"
    assert data["reason_code"] == "CONNECTOR_ACTION_CLASS_NOT_PERMITTED"
    assert get_approval_audit_store().count_by_proposal_id("proposal-disallowed-class") == 1


def test_audit_fail_closed_returns_500_without_decision(monkeypatch, tmp_path) -> None:
    class FailingAuditStore:
        def append_record(self, _record):
            raise RuntimeError("forced audit failure")

    monkeypatch.setenv(
        "PLATFORM_APPROVAL_GATE_SQLITE_PATH",
        str(tmp_path / "approval_gate.db"),
    )
    _clear_caches()
    app = create_app()
    app.dependency_overrides[get_approval_audit_store] = lambda: FailingAuditStore()
    client = TestClient(app)
    _register_connector(tmp_path)
    _seed_policy(tmp_path)

    response = client.post(
        "/v1/gate/proposals",
        headers=_headers(),
        json=_proposal(proposal_id="proposal-audit-fail"),
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Approval gate audit write failed"
    assert _record_store(tmp_path).get_decision_by_proposal_id("proposal-audit-fail") is None


def test_decision_status_endpoint_returns_stored_decision(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    _register_connector(tmp_path)
    _seed_policy(tmp_path)

    submitted = client.post(
        "/v1/gate/proposals",
        headers=_headers(),
        json=_proposal(proposal_id="proposal-status"),
    )
    response = client.get(
        "/v1/gate/proposals/proposal-status/decision",
        headers=_headers(),
    )

    assert submitted.status_code == 200
    assert response.status_code == 200
    assert response.json() == submitted.json()


def test_retry_after_partial_proposal_insert_creates_decision(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    _register_connector(tmp_path)
    _seed_policy(tmp_path)
    _record_store(tmp_path)
    payload = _proposal(proposal_id="proposal-partial-retry")

    with sqlite3.connect(_db_path(tmp_path)) as conn:
        conn.execute(
            """
            INSERT INTO approval_proposals (
              proposal_id,
              connector_id,
              action_class,
              target_system,
              target_scope,
              mutation_type,
              payload_summary,
              payload_hash,
              triggering_signal,
              submitted_at,
              requested_by,
              received_at,
              full_payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["proposal_id"],
                payload["connector_id"],
                payload["action_class"],
                payload["target_system"],
                "{}",
                payload["mutation_type"],
                payload["payload_summary"],
                payload["payload_hash"],
                "{}",
                payload["submitted_at"],
                payload["requested_by"],
                "2026-05-21T12:00:02.000+00:00",
                "{}",
            ),
        )

    response = client.post("/v1/gate/proposals", headers=_headers(), json=payload)

    assert response.status_code == 200
    assert response.json()["decision"] == "ALLOW"
    assert _record_store(tmp_path).get_decision_by_proposal_id("proposal-partial-retry")


def test_submitted_at_is_stored_in_utc(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    _register_connector(tmp_path)
    _seed_policy(tmp_path)
    payload = _proposal(proposal_id="proposal-utc")
    payload["submitted_at"] = "2026-05-21T19:00:01+07:00"

    response = client.post("/v1/gate/proposals", headers=_headers(), json=payload)

    assert response.status_code == 200
    with sqlite3.connect(_db_path(tmp_path)) as conn:
        stored = conn.execute(
            "SELECT submitted_at FROM approval_proposals WHERE proposal_id = ?",
            ("proposal-utc",),
        ).fetchone()
    assert stored[0] == "2026-05-21T12:00:01.000+00:00"


def test_outcome_endpoint_records_executed_and_aborted(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    _register_connector(tmp_path)
    _seed_policy(tmp_path)
    submitted = client.post(
        "/v1/gate/proposals",
        headers=_headers(),
        json=_proposal(proposal_id="proposal-outcome"),
    )
    assert submitted.status_code == 200

    executed = client.post(
        "/v1/gate/proposals/proposal-outcome/outcome",
        headers=_headers(),
        json={
            "outcome": "executed",
            "execution_timestamp": "2026-05-21T12:02:00Z",
        },
    )
    aborted = client.post(
        "/v1/gate/proposals/proposal-outcome/outcome",
        headers=_headers(),
        json={
            "outcome": "aborted",
            "execution_timestamp": "2026-05-21T12:03:00Z",
        },
    )

    assert executed.status_code == 200
    assert executed.json()["outcome"]["outcome"] == "executed"
    assert aborted.status_code == 200
    assert aborted.json()["outcome"]["outcome"] == "aborted"


def test_same_proposal_id_returns_existing_decision_idempotently(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    _register_connector(tmp_path)
    _seed_policy(tmp_path)
    payload = _proposal(proposal_id="proposal-idempotent")

    first = client.post("/v1/gate/proposals", headers=_headers(), json=payload)
    second = client.post("/v1/gate/proposals", headers=_headers(), json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    assert get_approval_audit_store().count_by_proposal_id("proposal-idempotent") == 1
