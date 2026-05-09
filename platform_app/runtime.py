"""Runtime configuration validation for production-safe platform startup."""

from __future__ import annotations

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

    if errors:
        raise RuntimeConfigurationError(
            "Runtime configuration failed hardening checks: " + "; ".join(errors)
        )
