from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_linux_start_script_is_lf_only_and_image_normalizes_defensively() -> None:
    start_script = (PROJECT_ROOT / "deploy" / "start.sh").read_bytes()
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    attributes = (PROJECT_ROOT / ".gitattributes").read_text(encoding="utf-8")

    assert b"\r\n" not in start_script
    assert "sed -i 's/\\r$//' /usr/local/bin/flowbiz-platform-start" in dockerfile
    assert "*.sh text eol=lf" in attributes
