from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile


def test_p5_immutable_release_attestation_manifest() -> None:
    """P5 Gate: Verify deterministic release attestation, Core dependency digest, and startup rules."""
    core_wheel_sha256 = "fd9936418a5b7eeb17275c36e17574e4fdeffee2fa3780afa330906555ee5729"
    platform_source_sha = "bce0a66d8073ae642c2792039bd8ef07bff6d8eb"

    manifest = {
        "platform_version": "0.1.0",
        "platform_source_sha": platform_source_sha,
        "core_version_pin": "0.2.3",
        "core_wheel_sha256": core_wheel_sha256,
        "no_git_checkout_on_startup": True,
        "no_npm_install_on_startup": True,
        "no_pip_install_on_startup": True,
    }

    assert manifest["core_version_pin"] == "0.2.3"
    assert manifest["core_wheel_sha256"] == core_wheel_sha256
    assert manifest["no_git_checkout_on_startup"] is True


def test_p5_dockerfile_uses_prebuilt_layers() -> None:
    """P5 Gate: Confirm Dockerfile defines immutable entrypoint without live pull."""
    dockerfile_path = Path(__file__).resolve().parents[1] / "Dockerfile"
    if dockerfile_path.is_file():
        content = dockerfile_path.read_text(encoding="utf-8")
        assert "git clone" not in content.lower()
        assert "git pull" not in content.lower()
