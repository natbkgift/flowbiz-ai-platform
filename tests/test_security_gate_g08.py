from __future__ import annotations

from platform_app.operator_redaction import redact_payload
from platform_app.tenant_rbac import PlatformRole, RbacAction, allowed_actions_for_role
from platform_app.dispatch_records import hash_callback_token, issue_callback_token
from platform_app.rate_limit import APIPrincipal, InMemoryFixedWindowRateLimiter


def test_secret_scan_and_env_redaction() -> None:
    """G08 Gate: Verify sensitive secret redaction function."""
    sensitive_data = {
        "api_key": "secret-flowbiz-token-9999",
        "password": "super-secret-pass",
        "normal_field": "public-data",
    }
    redacted = redact_payload(sensitive_data)
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["password"] == "[REDACTED]"
    assert redacted["normal_field"] == "public-data"


def test_callback_forgery_prevention() -> None:
    """G08 Gate: Verify HMAC callback token forgery resistance."""
    secret = "production-hardening-secret-key"
    job_id = "job-sec-100"
    dispatch_id = "dsp-sec-100"

    real_token = issue_callback_token(
        shared_secret=secret,
        job_id=job_id,
        dispatch_id=dispatch_id,
    )
    forged_token = issue_callback_token(
        shared_secret="wrong-secret",
        job_id=job_id,
        dispatch_id=dispatch_id,
    )

    real_hash = hash_callback_token(real_token)
    forged_hash = hash_callback_token(forged_token)

    assert real_hash != forged_hash


def test_tenant_isolation_and_permission_boundaries() -> None:
    """G08 Gate: Verify viewer role cannot perform administrative write actions."""
    viewer_actions = allowed_actions_for_role(PlatformRole.VIEWER)
    assert RbacAction.TENANT_MANAGE not in viewer_actions
    assert RbacAction.PROJECT_DELETE not in viewer_actions
    assert RbacAction.MEMBERSHIP_MANAGE not in viewer_actions


def test_rate_limiter_abuse_case() -> None:
    """G08 Gate: Verify rate limiter enforces burst limits."""
    limiter = InMemoryFixedWindowRateLimiter(rpm=2)
    p = APIPrincipal(key_id="tenant-abuse-1")

    # First 2 requests within limit 2 pass
    assert limiter.check(p, "route-1").allowed is True
    assert limiter.check(p, "route-1").allowed is True
    # 3rd request exceeds limit
    assert limiter.check(p, "route-1").allowed is False
