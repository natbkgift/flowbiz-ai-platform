"""Secret provider scaffolding for LLM and platform integrations."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from platform_app.config import PlatformSettings


class SecretNotFoundError(RuntimeError):
    pass


class SecretProvider:
    def get(self, key: str) -> str:
        raise NotImplementedError


class EnvSecretProvider(SecretProvider):
    def get(self, key: str) -> str:
        value = os.getenv(key)
        if not value:
            raise SecretNotFoundError(f"Missing secret: {key}")
        return value


class JsonFileSecretProvider(SecretProvider):
    """Loads secrets from a local JSON file (bootstrap/dev or simple VPS use)."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            raise SecretNotFoundError(f"Secret file not found: {self._path}")
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SecretNotFoundError(
                f"Invalid JSON secret file {self._path}: {exc.msg}"
            ) from exc
        if not isinstance(payload, dict):
            raise SecretNotFoundError(
                f"Invalid JSON secret file {self._path}: expected object"
            )
        return {str(k): str(v) for k, v in payload.items()}

    def get(self, key: str) -> str:
        payload = self._load()
        value = payload.get(key)
        if not value:
            raise SecretNotFoundError(f"Missing secret: {key}")
        return value


@dataclass(frozen=True)
class SecretProviderBundle:
    provider_name: str
    provider: SecretProvider


def build_secret_provider(settings: PlatformSettings) -> SecretProviderBundle:
    if settings.secret_provider == "env":
        return SecretProviderBundle(provider_name="env", provider=EnvSecretProvider())
    if settings.secret_provider == "file_json":
        return SecretProviderBundle(
            provider_name="file_json",
            provider=JsonFileSecretProvider(settings.secret_file_path),
        )
    raise ValueError(f"Unsupported secret provider: {settings.secret_provider}")
