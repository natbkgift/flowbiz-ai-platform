"""Secret provider scaffolding for LLM and platform integrations."""

from __future__ import annotations

import os
from dataclasses import dataclass

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


@dataclass(frozen=True)
class SecretProviderBundle:
    provider_name: str
    provider: SecretProvider


def build_secret_provider(settings: PlatformSettings) -> SecretProviderBundle:
    if settings.secret_provider == "env":
        return SecretProviderBundle(provider_name="env", provider=EnvSecretProvider())
    raise ValueError(f"Unsupported secret provider: {settings.secret_provider}")

