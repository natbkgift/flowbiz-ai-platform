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
    auth_store_mode: str = Field(default="json")
    auth_sqlite_path: str = Field(default="platform_data/platform_auth.db")
    required_api_keys: str = Field(default="")
    auth_api_keys_json: str = Field(default="[]")

    rate_limit_mode: str = "noop"
    rate_limit_rpm: int = 60
    rate_limit_redis_url: str = "redis://localhost:6379/0"
    rate_limit_redis_prefix: str = "flowbiz:rl"

    llm_provider: str = "stub"
    llm_model: str = "stub-echo"
    secret_provider: str = "env"
    secret_file_path: str = "secrets.local.json"
    llm_timeout_seconds: float = 30.0
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key_secret_name: str = "OPENAI_API_KEY"

    metrics_mode: str = "log"
    tracing_mode: str = "disabled"
    alerts_mode: str = "disabled"


@lru_cache
def get_settings() -> PlatformSettings:
    return PlatformSettings()
