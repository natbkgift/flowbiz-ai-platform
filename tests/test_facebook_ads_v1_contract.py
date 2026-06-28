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
    spec = json.loads(OPENAPI.read_text(encoding="utf-8"))
    assert isinstance(spec, dict), "OpenAPI document must be a JSON object"
    return spec


def require_mapping(value: object, context: str) -> dict:
    assert isinstance(value, dict), f"{context} must be an object"
    return value


def operations(spec: dict):
    paths = require_mapping(spec.get("paths"), "OpenAPI paths")
    for path, raw_path_item in paths.items():
        path_item = require_mapping(raw_path_item, f"Path item {path}")
        for method, operation in path_item.items():
            if method in {"get", "post", "put", "patch", "delete"}:
                yield path, method, require_mapping(operation, f"{method.upper()} {path}")


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
    version = spec.get("openapi")
    assert isinstance(version, str) and re.fullmatch(r"3\.1\.\d+", version), (
        "OpenAPI version must be a 3.1.x string"
    )
    paths = require_mapping(spec.get("paths"), "OpenAPI paths")
    for path, methods in REQUIRED_PATH_METHODS.items():
        assert path in paths, f"Missing required path {path}"
        path_item = require_mapping(paths.get(path), f"Path item {path}")
        missing_methods = methods - path_item.keys()
        assert not missing_methods, f"{path} is missing methods: {sorted(missing_methods)}"

    operation_ids = []
    for path, method, operation in operations(spec):
        operation_id = operation.get("operationId")
        assert isinstance(operation_id, str) and operation_id, (
            f"Missing operationId for {method.upper()} {path}"
        )
        operation_ids.append(operation_id)
    duplicates = sorted({item for item in operation_ids if operation_ids.count(item) > 1})
    assert not duplicates, f"Duplicate operationIds found: {duplicates}"


def test_references_and_required_schemas_resolve() -> None:
    spec = load_contract()
    components = require_mapping(spec.get("components"), "OpenAPI components")
    schemas = require_mapping(components.get("schemas"), "OpenAPI component schemas")
    missing_schemas = REQUIRED_SCHEMAS - schemas.keys()
    assert not missing_schemas, f"Missing required schemas: {sorted(missing_schemas)}"
    for node in walk(spec):
        ref = node.get("$ref")
        if ref is None:
            continue
        assert isinstance(ref, str) and ref.startswith("#/"), (
            f"External or malformed $ref is not allowed in this self-contained contract: {ref!r}"
        )
        target: object = spec
        for segment in ref.removeprefix("#/").split("/"):
            key = segment.replace("~1", "/").replace("~0", "~")
            target_mapping = require_mapping(target, f"$ref parent while resolving {ref}")
            assert key in target_mapping, f"Unresolved local $ref: {ref}"
            target = target_mapping[key]
        assert target is not None, f"Local $ref resolves to null: {ref}"


def test_operation_security_extensions_and_safe_errors() -> None:
    spec = load_contract()
    components = require_mapping(spec.get("components"), "OpenAPI components")
    security_schemes = require_mapping(
        components.get("securitySchemes"), "OpenAPI security schemes"
    )
    assert "SupabaseBearer" in security_schemes, "Missing SupabaseBearer security scheme"
    for path, method, operation in operations(spec):
        missing_extensions = EXTENSIONS - operation.keys()
        assert not missing_extensions, (
            f"{method.upper()} {path} is missing extensions: {sorted(missing_extensions)}"
        )
        caller = operation.get("x-flowbiz-caller")
        assert caller == "Next.js BFF", (
            f"{method.upper()} {path} must declare Next.js BFF as caller; got {caller!r}"
        )
        security = operation["security"] if "security" in operation else spec.get("security")
        assert security == [{"SupabaseBearer": []}], (
            f"{method.upper()} {path} must effectively require SupabaseBearer"
        )
        responses = require_mapping(operation.get("responses"), f"Responses for {method.upper()} {path}")
        required_errors = {"400", "401", "403", "404", "409", "422", "429", "503"}
        missing_errors = required_errors - responses.keys()
        assert not missing_errors, (
            f"{method.upper()} {path} is missing safe errors: {sorted(missing_errors)}"
        )
        idempotency = operation.get("x-flowbiz-idempotency")
        if method == "get":
            assert idempotency == "not-applicable", (
                f"GET {path} must declare idempotency as not-applicable"
            )
        else:
            assert isinstance(idempotency, str) and idempotency.startswith("required"), (
                f"{method.upper()} {path} must require idempotency"
            )
            parameters = operation.get("parameters", [])
            assert isinstance(parameters, list), (
                f"Parameters for {method.upper()} {path} must be an array"
            )
            refs = {
                require_mapping(item, f"Parameter for {method.upper()} {path}").get("$ref")
                for item in parameters
            }
            assert "#/components/parameters/IdempotencyKeyParameter" in refs, (
                f"{method.upper()} {path} must reference IdempotencyKeyParameter"
            )
        if path != "/v1/auth/me":
            tenant_enforcement = operation.get("x-flowbiz-tenant-enforcement")
            assert tenant_enforcement not in {None, "not-applicable"}, (
                f"{method.upper()} {path} must declare tenant enforcement"
            )


def test_job_states_are_closed_and_complete() -> None:
    spec = load_contract()
    components = require_mapping(spec.get("components"), "OpenAPI components")
    schemas = require_mapping(components.get("schemas"), "OpenAPI component schemas")
    job = require_mapping(schemas.get("Job"), "Job schema")
    properties = require_mapping(job.get("properties"), "Job schema properties")
    state = require_mapping(properties.get("state"), "Job.state schema")
    states = state.get("enum")
    assert states == ["queued", "running", "succeeded", "failed", "dead_letter", "cancelled"]


def test_no_password_or_direct_browser_contract() -> None:
    spec = load_contract()
    serialized = json.dumps(spec).lower()
    assert "password" not in serialized
    for path, method, operation in operations(spec):
        caller = operation.get("x-flowbiz-caller")
        assert isinstance(caller, str) and caller, (
            f"Missing x-flowbiz-caller for {method.upper()} {path}"
        )
        assert caller != "Browser", f"Browser caller is forbidden for {method.upper()} {path}"


def test_fixtures_are_synthetic_and_reference_known_schemas() -> None:
    spec = load_contract()
    components = require_mapping(spec.get("components"), "OpenAPI components")
    schemas = require_mapping(components.get("schemas"), "OpenAPI component schemas")
    files = sorted(FIXTURES.glob("*.json"))
    assert len(files) >= 9, "Expected at least nine synthetic fixture files"
    combined = ""
    for path in files:
        fixture = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(fixture, dict), f"Fixture {path.name} must be a JSON object"
        has_schema = "schema" in fixture
        has_schemas = "schemas" in fixture
        assert has_schema ^ has_schemas, (
            f"Fixture {path.name} must specify exactly one of 'schema' or 'schemas'"
        )
        if has_schemas:
            names = fixture.get("schemas")
            assert isinstance(names, list) and names, (
                f"Fixture {path.name} 'schemas' must be a non-empty array"
            )
        else:
            names = [fixture.get("schema")]
        assert all(isinstance(name, str) and name for name in names), (
            f"Fixture {path.name} schema names must be non-empty strings"
        )
        unknown = sorted(name for name in names if name not in schemas)
        assert not unknown, f"Fixture {path.name} references unknown schemas: {unknown}"
        assert "example" in fixture, f"Fixture {path.name} must contain an example"
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
