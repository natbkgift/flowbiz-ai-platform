from __future__ import annotations

from importlib.metadata import version

from packages.core.contracts.devx import SDKGeneratorTarget
from packages.core.retry import RetryPolicy, run_with_retry


CORE_DISTRIBUTION = "flowbiz-ai-core"
EXPECTED_CORE_VERSION = "0.2.2"


def test_core_distribution_version_is_pinned_to_v022() -> None:
    assert version(CORE_DISTRIBUTION) == EXPECTED_CORE_VERSION


def test_core_runtime_and_contract_imports_are_platform_compatible() -> None:
    policy = RetryPolicy(max_retries=1, timeout_seconds=0.0, backoff_seconds=0.0)
    result = run_with_retry(lambda: "platform-compatible", policy)

    assert result.success is True
    assert result.attempts == 1
    assert result.result == "platform-compatible"
    assert result.error is None

    sdk_target = SDKGeneratorTarget(
        language="python",
        package_name="flowbiz-ai-platform",
    )
    assert sdk_target.package_version == EXPECTED_CORE_VERSION
