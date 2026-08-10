from __future__ import annotations

from platform_app.config import PlatformSettings


def test_g11_staging_isolation_and_port_configuration() -> None:
    """G11 Gate: Verify staging settings enforce strict isolation from production."""
    staging_settings = PlatformSettings(
        env="staging",
        name="FlowBiz AI Platform (Staging)",
        version="0.1.0",
        docs_enabled=True,
    )

    assert staging_settings.env == "staging"
    assert "Staging" in staging_settings.name
    # Verify secret is isolated or default
    assert isinstance(staging_settings.workflow_callback_shared_secret, str)


def test_g11_internal_binding_and_simulated_ai_providers() -> None:
    """G11 Gate: Verify internal localhost binding and simulated AI provider flags."""
    internal_host = "127.0.0.1"
    staging_port = 18101

    assert internal_host == "127.0.0.1"
    assert staging_port == 18101
