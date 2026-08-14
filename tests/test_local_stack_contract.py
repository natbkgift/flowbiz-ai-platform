from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _parse_env_example() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in (PROJECT_ROOT / "env.local.example").read_text(
        encoding="utf-8"
    ).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def test_local_compose_isolated_from_vps_and_hermes() -> None:
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "name: flowbiz-platform-local" in compose
    assert "image: postgres:16-alpine" in compose
    assert "- .env.local" in compose
    assert '"127.0.0.1:8100:8100"' in compose
    assert '"127.0.0.1:15432:5432"' in compose
    assert "/opt/flowbiz" not in compose
    assert "/var/run/docker.sock" not in compose
    assert "privileged: true" not in compose
    assert "hermes" not in compose.lower()


def test_local_environment_is_stub_only_and_contains_no_provider_secret() -> None:
    env = _parse_env_example()
    raw = (PROJECT_ROOT / "env.local.example").read_text(encoding="utf-8")

    assert env["PLATFORM_ENV"] == "development"
    assert env["PLATFORM_AUTH_MODE"] == "disabled"
    assert env["PLATFORM_LLM_PROVIDER"] == "stub"
    assert env["PLATFORM_RUNNER_ENABLED"] == "false"
    assert "@postgres:5432/flowbiz_platform_local" in env["PLATFORM_DATABASE_URL"]
    assert env["PLATFORM_DATABASE_URL_FILE"] == ""
    assert env["PLATFORM_RUNNER_DISPATCH_TOKEN"] == ""
    assert env["PLATFORM_RUNNER_CALLBACK_SECRET"] == ""
    assert env["PLATFORM_JOB_ADMIN_TOKEN"] == ""
    assert not re.search(
        r"AIza[0-9A-Za-z_-]{20,}|ghp_[0-9A-Za-z]{20,}|github_pat_[0-9A-Za-z_]{20,}|sk-[0-9A-Za-z_-]{20,}",
        raw,
    )


def test_local_environment_file_is_not_committed() -> None:
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    dockerignore = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert ".env.local" in gitignore.splitlines()
    assert ".env.local" in dockerignore.splitlines()
