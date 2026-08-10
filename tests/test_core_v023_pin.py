from __future__ import annotations

import tomllib
from pathlib import Path

CORE_PACKAGE = "flowbiz-ai-core"
EXPECTED_CORE_VERSION = "0.2.3"
VERIFIED_CORE_COMMIT = "9576229ce600caab54b9d4590dee3f86fc9145f0"
PRIVATE_CORE_REPO = "natbkgift/flowbiz-ai-core"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"
EVIDENCE_DOC_PATH = PROJECT_ROOT / "docs" / "platform" / "PROD-08_CORE_V023_PIN_FOUNDATION.md"


def _project_dependencies() -> list[str]:
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    return list(pyproject["project"].get("dependencies", []))


def _evidence_doc() -> str:
    return EVIDENCE_DOC_PATH.read_text(encoding="utf-8")


def test_platform_ci_does_not_install_private_core_dependency() -> None:
    dependencies = _project_dependencies()

    assert all(CORE_PACKAGE not in dependency for dependency in dependencies)
    assert all(PRIVATE_CORE_REPO not in dependency for dependency in dependencies)


def test_prod_08_records_core_release_constraint_without_installing_core() -> None:
    evidence = _evidence_doc()

    assert "constraints-only" in evidence
    assert f"Core package: `{CORE_PACKAGE}`" in evidence
    assert f"Core version constraint: `{EXPECTED_CORE_VERSION}`" in evidence
    assert f"Core verified commit: `{VERIFIED_CORE_COMMIT}`" in evidence
    assert "Private Core install in Platform CI: `DEFERRED`" in evidence
    assert "Package registry publication: `NOT_PERFORMED`" in evidence
