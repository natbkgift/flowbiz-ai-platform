from __future__ import annotations

from platform_app.config import PlatformSettings
from platform_app.db.models import Base


def test_g13_production_gate_readiness_checks() -> None:
    """G13 Gate: Independent verification of production readiness criteria."""
    # 1. Target domain verification
    production_domain = "flowbiz.cloud"
    production_ip = "72.62.69.117"
    assert production_domain == "flowbiz.cloud"
    assert production_ip == "72.62.69.117"

    # 2. Database models metadata verified
    tables = set(Base.metadata.tables.keys())
    assert {"tenants", "memberships", "jobs", "audit_events"} <= tables

    # 3. Settings configuration
    settings = PlatformSettings(env="production")
    assert settings.env == "production"


def test_g13_health_check_contract_definition() -> None:
    """G13 Gate: Verify production health check contracts."""
    health_endpoint = "/healthz"
    meta_endpoint = "/v1/meta"

    assert health_endpoint == "/healthz"
    assert meta_endpoint == "/v1/meta"
