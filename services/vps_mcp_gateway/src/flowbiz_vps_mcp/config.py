"""Configuration loading and deterministic fingerprints."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import yaml

from .models import GatewayConfig

DEFAULT_CONFIG_PATH = Path("/etc/flowbiz-vps-mcp/config.yaml")
CONFIG_ENV = "FLOWBIZ_VPS_MCP_CONFIG"


def resolve_config_path(explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    return Path(os.environ.get(CONFIG_ENV, str(DEFAULT_CONFIG_PATH)))


def load_config(explicit: str | Path | None = None) -> GatewayConfig:
    path = resolve_config_path(explicit)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Gateway config not found at {path}. Set {CONFIG_ENV} or install config.yaml."
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"Cannot read gateway config at {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise RuntimeError(f"Invalid YAML in gateway config at {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise RuntimeError("Gateway config must be a YAML object")
    return GatewayConfig.model_validate(raw)


def config_fingerprint(config: GatewayConfig) -> str:
    payload: Any = config.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
