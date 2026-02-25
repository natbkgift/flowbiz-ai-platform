"""Helpers for integrating with flowbiz-ai-core without hard-coding internals."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


def get_core_package_status() -> dict[str, str | bool]:
    try:
        core_version = version("flowbiz-ai-core")
        return {"installed": True, "version": core_version}
    except PackageNotFoundError:
        return {"installed": False, "version": "not-installed"}

