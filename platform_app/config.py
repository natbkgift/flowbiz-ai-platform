"""Platform configuration for FlowBiz AI Platform."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PlatformSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="PLATFORM_",
        extra="ignore",
    )

    env: str = "development"
    name: str = "FlowBiz AI Platform"
    version: str = "0.1.0"
    log_level: str = "INFO"

    auth_mode: str = Field(default="disabled")
    required_api_keys: str = Field(default="")
    auth_api_keys_json: str = Field(default="[]")

    rate_limit_mode: str = "noop"
    rate_limit_rpm: int = 60
    rate_limit_redis_url: str = "redis://localhost:6379/0"
    rate_limit_redis_prefix: str = "flowbiz:rl"

    llm_provider: str = "stub"
    llm_model: str = "stub-echo"
    secret_provider: str = "env"

    metrics_mode: str = "log"
    tracing_mode: str = "disabled"
    alerts_mode: str = "disabled"


@lru_cache
def get_settings() -> PlatformSettings:
    return PlatformSettings()
