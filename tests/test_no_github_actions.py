from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_release_process_contains_no_github_actions_workflows() -> None:
    workflows = PROJECT_ROOT / ".github" / "workflows"
    workflow_files = (
        list(workflows.glob("*.yml")) + list(workflows.glob("*.yaml"))
        if workflows.exists()
        else []
    )

    assert workflow_files == []


def test_readme_declares_manual_local_release_gate() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    assert "verified manually and does not require GitHub Actions" in readme
