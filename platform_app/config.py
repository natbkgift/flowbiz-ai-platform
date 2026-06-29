"""Platform configuration for FlowBiz AI Platform."""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, SecretStr
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
    docs_enabled: bool | None = None

    cors_allowed_origins: str = ""
    cors_allow_credentials: bool = False
    cors_allowed_methods: str = "GET,POST,OPTIONS"
    cors_allowed_headers: str = (
        "Authorization,Content-Type,X-API-Key,X-FlowBiz-Callback-Token,"
        "X-Request-ID,X-Correlation-ID"
    )
    cors_expose_headers: str = (
        "X-Request-ID,X-RateLimit-Limit,X-RateLimit-Remaining,"
        "X-RateLimit-Reset,Retry-After"
    )

    auth_mode: str = Field(default="disabled")
    auth_store_mode: str = Field(default="json")
    auth_sqlite_path: str = Field(default="platform_data/platform_auth.db")
    required_api_keys: str = Field(default="")
    auth_api_keys_json: str = Field(default="[]")

    supabase_jwt_issuer: str = Field(default="")
    supabase_jwt_audience: str = Field(default="")
    supabase_jwks_url: str = Field(default="")
    supabase_jwks_cache_seconds: int = Field(default=300)
    supabase_jwks_timeout_seconds: float = Field(default=2.0)
    supabase_jwt_clock_skew_seconds: int = Field(default=30)

    workflow_events_sqlite_path: str = Field(
        default="platform_data/workflow_events.db"
    )
    approval_gate_sqlite_path: str = Field(default="platform_data/approval_gate.db")
    workflow_runner_dispatch_url: str = Field(default="")
    workflow_callback_shared_secret: str = Field(default="")
    platform_public_base_url: str = Field(default="http://localhost:8100")

    database_url: SecretStr | None = Field(default=None)

    core_base_url: str = Field(default="")
    core_service_token: SecretStr | None = Field(default=None)
    core_timeout_seconds: float = Field(default=2.0)
    core_retry_attempts: int = Field(default=2)
    core_retry_backoff_seconds: float = Field(default=0.2)
    core_internal_allowed_hosts: str = Field(
        default="flowbiz-ai-core-internal,localhost,127.0.0.1"
    )

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

    operator_ui_enabled: bool = Field(default=False)
    operator_ui_token: SecretStr | None = Field(default=None)
    operator_ui_legacy_upstream_health_url: str = Field(default="")
    operator_ui_public_canary_health_url: str = Field(default="")

    @property
    def operator_ui_token_value(self) -> str:
        if self.operator_ui_token is None:
            return ""
        return self.operator_ui_token.get_secret_value()

    @property
    def database_url_value(self) -> str:
        if self.database_url is None:
            return ""
        return self.database_url.get_secret_value()

    @property
    def is_production(self) -> bool:
        return self.env.strip().lower() == "production"

    @property
    def docs_enabled_effective(self) -> bool:
        if self.docs_enabled is not None:
            return self.docs_enabled
        return not self.is_production

    @property
    def supabase_auth_configured(self) -> bool:
        return bool(
            self.supabase_jwt_issuer.strip()
            and self.supabase_jwt_audience.strip()
            and self.supabase_jwks_url.strip()
        )

    @property
    def auth_mode_supported(self) -> bool:
        if self.auth_mode in {"disabled", "api_key"}:
            return True
        if self.auth_mode == "supabase":
            return self.supabase_auth_configured
        return False

    def csv(self, raw: str) -> list[str]:
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return self.csv(self.cors_allowed_origins)

    @property
    def cors_method_list(self) -> list[str]:
        return self.csv(self.cors_allowed_methods)

    @property
    def cors_header_list(self) -> list[str]:
        return self.csv(self.cors_allowed_headers)

    @property
    def cors_expose_header_list(self) -> list[str]:
        return self.csv(self.cors_expose_headers)

    @property
    def core_internal_allowed_host_list(self) -> list[str]:
        return self.csv(self.core_internal_allowed_hosts)

    @property
    def core_base_hostname(self) -> str:
        if not self.core_base_url.strip():
            return ""
        return urlparse(self.core_base_url).hostname or ""

    @property
    def core_service_token_value(self) -> str:
        if self.core_service_token is None:
            return ""
        return self.core_service_token.get_secret_value()


@lru_cache
def get_settings() -> PlatformSettings:
    return PlatformSettings()
