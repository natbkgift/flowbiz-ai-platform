from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs" / "contracts" / "facebook_ads" / "v1"
OPENAPI = CONTRACT / "openapi.json"
FIXTURES = CONTRACT / "fixtures"

REQUIRED_PATH_METHODS = {
    "/v1/auth/me": {"get"},
    "/v1/tenants": {"get", "post"},
    "/v1/tenants/{tenant_id}/memberships": {"get", "post"},
    "/v1/tenants/{tenant_id}/memberships/{membership_id}": {"patch"},
    "/v1/projects": {"get", "post"},
    "/v1/projects/{project_id}": {"get", "patch", "delete"},
    "/v1/projects/{project_id}/onboarding": {"get", "put"},
    "/v1/projects/{project_id}/strategy-jobs": {"post"},
    "/v1/projects/{project_id}/creative-brief-jobs": {"post"},
    "/v1/projects/{project_id}/campaign-plan-jobs": {"post"},
    "/v1/jobs/{job_id}": {"get"},
    "/v1/jobs/{job_id}/retry": {"post"},
    "/v1/jobs/{job_id}/cancel": {"post"},
    "/v1/projects/{project_id}/strategies": {"get"},
    "/v1/projects/{project_id}/creative-briefs": {"get"},
    "/v1/projects/{project_id}/campaign-plans": {"get"},
    "/v1/dashboard/summary": {"get"},
    "/v1/approvals": {"get"},
    "/v1/approvals/{approval_id}/decisions": {"post"},
    "/v1/audit-events": {"get"},
    "/v1/usage/summary": {"get"},
}
EXTENSIONS = {
    "x-flowbiz-caller",
    "x-flowbiz-tenant-enforcement",
    "x-flowbiz-rbac",
    "x-flowbiz-idempotency",
    "x-flowbiz-rate-limit-class",
    "x-flowbiz-audit-event",
}
REQUIRED_SCHEMAS = {
    "Error", "PageInfo", "UserIdentity", "Tenant", "Membership", "Project",
    "BusinessProfile", "ProductService", "CampaignGoal", "OnboardingAggregate",
    "GenerationRequest", "Strategy", "CreativeBrief", "CampaignPlan", "Job",
    "JobAttemptSummary", "UsageSummary", "ApprovalRequest", "ApprovalDecision",
    "AuditEvent", "DashboardSummary",
}


def load_contract() -> dict:
    return json.loads(OPENAPI.read_text(encoding="utf-8"))


def operations(spec: dict):
    for path, path_item in spec["paths"].items():
        for method, operation in path_item.items():
            if method in {"get", "post", "put", "patch", "delete"}:
                yield path, method, operation


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def test_openapi_version_paths_and_operations() -> None:
    spec = load_contract()
    assert re.fullmatch(r"3\.1\.\d+", spec["openapi"])
    for path, methods in REQUIRED_PATH_METHODS.items():
        assert path in spec["paths"]
        assert methods <= spec["paths"][path].keys()
    operation_ids = [item[2]["operationId"] for item in operations(spec)]
    assert len(operation_ids) == len(set(operation_ids))


def test_references_and_required_schemas_resolve() -> None:
    spec = load_contract()
    schemas = spec["components"]["schemas"]
    assert REQUIRED_SCHEMAS <= schemas.keys()
    for node in walk(spec):
        ref = node.get("$ref")
        if ref:
            target = spec
            for segment in ref.removeprefix("#/").split("/"):
                target = target[segment.replace("~1", "/").replace("~0", "~")]
            assert target


def test_operation_security_extensions_and_safe_errors() -> None:
    spec = load_contract()
    for path, method, operation in operations(spec):
        assert EXTENSIONS <= operation.keys()
        assert operation["x-flowbiz-caller"] == "Next.js BFF"
        assert operation["security"] == [{"SupabaseBearer": []}]
        assert {"400", "401", "403", "404", "409", "422", "429", "503"} <= operation["responses"].keys()
        if method == "get":
            assert operation["x-flowbiz-idempotency"] == "not-applicable"
        else:
            assert operation["x-flowbiz-idempotency"].startswith("required")
            refs = {item.get("$ref") for item in operation.get("parameters", [])}
            assert "#/components/parameters/IdempotencyKeyParameter" in refs
        if path != "/v1/auth/me":
            assert operation["x-flowbiz-tenant-enforcement"] != "not-applicable"


def test_job_states_are_closed_and_complete() -> None:
    states = load_contract()["components"]["schemas"]["Job"]["properties"]["state"]["enum"]
    assert states == ["queued", "running", "succeeded", "failed", "dead_letter", "cancelled"]


def test_no_password_or_direct_browser_contract() -> None:
    spec = load_contract()
    serialized = json.dumps(spec).lower()
    assert "password" not in serialized
    assert all(operation["x-flowbiz-caller"] != "Browser" for _, _, operation in operations(spec))


def test_fixtures_are_synthetic_and_reference_known_schemas() -> None:
    schemas = load_contract()["components"]["schemas"]
    files = sorted(FIXTURES.glob("*.json"))
    assert len(files) >= 9
    combined = ""
    for path in files:
        fixture = json.loads(path.read_text(encoding="utf-8"))
        names = fixture.get("schemas", [fixture.get("schema")])
        assert names and all(name in schemas for name in names)
        combined += json.dumps(fixture)
    lowered = combined.lower()
    assert "demo" in lowered
    assert "localhost" not in lowered
    assert not re.search(r"(api[_-]?key|secret|bearer)\s*[:=]", lowered)


def test_no_unresolved_placeholders_or_unapproved_claims() -> None:
    text = OPENAPI.read_text(encoding="utf-8").lower()
    assert not re.search(r"\b(todo|tbd|fixme|changeme)\b", text)
    assert "guaranteed roas" not in text
    assert "guaranteed leads" not in text
