from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_production_image_pins_base_and_packaging_toolchain() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert (
        "FROM python:3.11-slim@sha256:"
        "a630a63cdb314e2d138a2fca3e375e319e8568346ffafac5b980f888630ac4f1"
    ) in dockerfile
    assert "pip==26.2.1" in dockerfile
    assert "setuptools==83.0.0" in dockerfile
    assert "pip install --upgrade pip" not in dockerfile
