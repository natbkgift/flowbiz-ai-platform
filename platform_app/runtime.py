"""Runtime configuration validation for production-safe platform startup."""

from __future__ import annotations

import json
from urllib.parse import urlparse

from platform_app.config import PlatformSettings
from platform_app.secrets import SecretNotFoundError, SecretProviderBundle


class RuntimeConfigurationError(RuntimeError):
    """Raised when runtime settings are unsafe or incomplete."""


def validate_runtime_configuration(
    settings: PlatformSettings,
    secrets: SecretProviderBundle | None = None,
    *,
    validate_provider_secrets: bool = True,
) -> None:
    """Validate configuration without returning or logging secret values."""

    errors: list[str] = []
    cors_origins = settings.cors_origin_list

    if "*" in cors_origins and settings.cors_allow_credentials:
        errors.append("wildcard CORS origins cannot be used with credentials")

    if settings.is_production:
        if settings.docs_enabled_effective:
            errors.append("FastAPI docs must be disabled in production")
        if settings.auth_mode != "api_key":
            errors.append("PLATFORM_AUTH_MODE=api_key is required in production")
        else:
            try:
                api_key_records = json.loads(settings.auth_api_keys_json_value or "[]")
            except json.JSONDecodeError:
                api_key_records = None
            if not isinstance(api_key_records, list):
                errors.append("production API key records must be a JSON array")
            elif not api_key_records and not settings.required_api_keys.strip():
                errors.append("at least one production API key record is required")
        if settings.rate_limit_mode != "redis":
            errors.append("PLATFORM_RATE_LIMIT_MODE=redis is required in production")
        if "*" in cors_origins:
            errors.append("wildcard CORS origins are not allowed in production")

    if settings.rate_limit_mode == "redis":
        if not settings.rate_limit_redis_url.strip():
            errors.append("PLATFORM_RATE_LIMIT_REDIS_URL is required for redis mode")
    elif settings.rate_limit_mode not in {"noop", "memory"}:
        errors.append(f"unsupported rate limit mode: {settings.rate_limit_mode}")

    if settings.llm_provider == "stub":
        pass
    elif settings.llm_provider == "openai":
        if not settings.llm_model.strip() or settings.llm_model.startswith("stub"):
            errors.append("a real PLATFORM_LLM_MODEL is required for OpenAI")
        if not settings.openai_api_key_secret_name.strip():
            errors.append("PLATFORM_OPENAI_API_KEY_SECRET_NAME is required")
        elif validate_provider_secrets and secrets is not None:
            try:
                secrets.provider.get(settings.openai_api_key_secret_name)
            except SecretNotFoundError:
                errors.append(
                    "required OpenAI provider secret is unavailable from "
                    "PLATFORM_SECRET_PROVIDER"
                )
    else:
        errors.append(f"unsupported LLM provider: {settings.llm_provider}")

    if settings.core_base_url.strip():
        parsed_core_url = urlparse(settings.core_base_url)
        if parsed_core_url.scheme not in {"http", "https"} or not parsed_core_url.netloc:
            errors.append("PLATFORM_CORE_BASE_URL must be an http(s) URL")
        if settings.core_timeout_seconds <= 0 or settings.core_timeout_seconds > 10:
            errors.append("PLATFORM_CORE_TIMEOUT_SECONDS must be > 0 and <= 10")
        if settings.core_retry_attempts < 1 or settings.core_retry_attempts > 3:
            errors.append("PLATFORM_CORE_RETRY_ATTEMPTS must be between 1 and 3")
        if (
            settings.core_retry_backoff_seconds < 0
            or settings.core_retry_backoff_seconds > 2
        ):
            errors.append("PLATFORM_CORE_RETRY_BACKOFF_SECONDS must be between 0 and 2")
        if settings.is_production:
            allowed_hosts = set(settings.core_internal_allowed_host_list)
            if not parsed_core_url.hostname or parsed_core_url.hostname not in allowed_hosts:
                errors.append(
                    "PLATFORM_CORE_BASE_URL host must be an approved internal host "
                    "in production"
                )

    if settings.runner_enabled:
        if not settings.database_url_value:
            errors.append("PLATFORM_DATABASE_URL or PLATFORM_DATABASE_URL_FILE is required")
        if not settings.runner_dispatch_url.strip():
            errors.append("PLATFORM_RUNNER_DISPATCH_URL is required")
        else:
            runner_url = urlparse(settings.runner_dispatch_url)
            if runner_url.scheme not in {"http", "https"} or not runner_url.hostname:
                errors.append("PLATFORM_RUNNER_DISPATCH_URL must be an http(s) URL")
            if settings.is_production and runner_url.hostname in {
                "localhost",
                "127.0.0.1",
                "0.0.0.0",
                "::1",
            }:
                errors.append("production runner dispatch must use an internal service host")
        internal_base = urlparse(settings.platform_internal_base_url)
        if internal_base.scheme not in {"http", "https"} or not internal_base.hostname:
            errors.append("PLATFORM_PLATFORM_INTERNAL_BASE_URL must be an http(s) URL")
        if not settings.runner_dispatch_token_value:
            errors.append("runner dispatch token is required")
        if not settings.runner_callback_secret_value:
            errors.append("runner callback secret is required")
        if not settings.job_admin_token_value:
            errors.append("runner job administration token is required")
        if not 30 <= settings.runner_callback_max_clock_skew_seconds <= 600:
            errors.append("runner callback clock skew must be between 30 and 600 seconds")

    if errors:
        raise RuntimeConfigurationError(
            "Runtime configuration failed hardening checks: " + "; ".join(errors)
        )
