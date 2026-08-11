from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_linux_start_script_is_lf_only_and_image_normalizes_defensively() -> None:
    start_script = (PROJECT_ROOT / "deploy" / "start.sh").read_bytes()
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    attributes = (PROJECT_ROOT / ".gitattributes").read_text(encoding="utf-8")

    assert b"\r\n" not in start_script
    assert "sed -i 's/\\r$//' /usr/local/bin/flowbiz-platform-start" in dockerfile
    assert "*.sh text eol=lf" in attributes


def test_vps_compose_separates_internal_control_and_loopback_edge_networks() -> None:
    compose_path = PROJECT_ROOT / "deploy" / "docker-compose.vps.yml"
    compose_text = compose_path.read_text(encoding="utf-8")
    compose = yaml.safe_load(compose_text)
    platform = compose["services"]["platform"]

    assert set(platform["networks"]) == {
        "flowbiz-platform-core-control",
        "flowbiz-platform-edge",
    }
    assert platform["ports"] == ["127.0.0.1:18100:8100"]
    assert compose["networks"]["flowbiz-platform-core-control"]["external"] is True
    assert compose["networks"]["flowbiz-platform-edge"] == {
        "name": "flowbiz-platform-edge",
        "driver": "bridge",
    }
