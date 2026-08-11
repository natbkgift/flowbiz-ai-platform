from __future__ import annotations

import tomllib
from importlib import metadata
from pathlib import Path

from packages.core.contracts.platform_runner import PLATFORM_RUNNER_CONTRACT_VERSION

CORE_PACKAGE = "flowbiz-ai-core"
EXPECTED_CORE_VERSION = "0.2.3"
VERIFIED_CORE_COMMIT = "a62027e435197f604dca22913c2a8a33705e1492"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"
EVIDENCE_DOC_PATH = PROJECT_ROOT / "docs" / "platform" / "PROD-08_CORE_V023_PIN_FOUNDATION.md"


def _core_runtime_dependencies() -> list[str]:
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    return list(pyproject["project"]["optional-dependencies"]["core-runtime"])


def _evidence_doc() -> str:
    return EVIDENCE_DOC_PATH.read_text(encoding="utf-8")


def test_platform_runtime_exactly_pins_published_core_package() -> None:
    assert _core_runtime_dependencies() == [f"{CORE_PACKAGE}=={EXPECTED_CORE_VERSION}"]
    assert metadata.version(CORE_PACKAGE) == EXPECTED_CORE_VERSION
    assert PLATFORM_RUNNER_CONTRACT_VERSION == "1.0"


def test_prod_08_records_published_core_release() -> None:
    evidence = _evidence_doc()

    assert "runtime-installed" in evidence
    assert f"Core package: `{CORE_PACKAGE}`" in evidence
    assert f"Core version constraint: `{EXPECTED_CORE_VERSION}`" in evidence
    assert f"Core verified commit: `{VERIFIED_CORE_COMMIT}`" in evidence
    assert "Manual release publication: `COMPLETE`" in evidence
    assert "GitHub Actions required: `NO`" in evidence
