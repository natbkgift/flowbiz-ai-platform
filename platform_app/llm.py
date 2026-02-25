"""LLM adapter implementations for platform runtime (stub + provider hooks)."""

from __future__ import annotations

import httpx
from pydantic import BaseModel, Field

from platform_app.config import PlatformSettings
from platform_app.secrets import SecretNotFoundError, SecretProviderBundle


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1)
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    output: str
    model: str
    provider: str
    finish_reason: str = "stop"


class LLMProviderError(RuntimeError):
    """Stable platform-layer error for provider failures."""


class LLMAdapter:
    def chat(self, req: ChatRequest) -> ChatResponse:
        raise NotImplementedError


class StubLLMAdapter(LLMAdapter):
    def __init__(self, model: str) -> None:
        self._model = model

    def chat(self, req: ChatRequest) -> ChatResponse:
        return ChatResponse(
            output=f"[stub:{self._model}] {req.prompt}",
            model=self._model,
            provider="stub",
        )


class OpenAIChatCompletionsAdapter(LLMAdapter):
    """Minimal OpenAI Chat Completions adapter using REST API."""

    def __init__(
        self,
        model: str,
        base_url: str,
        timeout_seconds: float,
        api_key_secret_name: str,
        secrets: SecretProviderBundle,
        client: httpx.Client | None = None,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._api_key_secret_name = api_key_secret_name
        self._secrets = secrets
        self._client = client

    def chat(self, req: ChatRequest) -> ChatResponse:
        try:
            api_key = self._secrets.provider.get(self._api_key_secret_name)
        except SecretNotFoundError as exc:
            raise LLMProviderError(str(exc)) from exc

        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": req.prompt}],
        }
        url = f"{self._base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}"}

        own_client = False
        client = self._client
        if client is None:
            client = httpx.Client(timeout=self._timeout_seconds)
            own_client = True

        try:
            response = client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"OpenAI request failed: {exc}") from exc
        finally:
            if own_client:
                client.close()

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMProviderError(
                f"OpenAI response was not valid JSON (status {response.status_code})"
            ) from exc

        if response.status_code >= 400:
            message = (
                data.get("error", {}).get("message")
                if isinstance(data, dict)
                else None
            ) or f"OpenAI API error status {response.status_code}"
            raise LLMProviderError(message)

        try:
            choice0 = data["choices"][0]
            content = choice0["message"]["content"]
            finish_reason = choice0.get("finish_reason") or "stop"
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("OpenAI response missing expected fields") from exc

        return ChatResponse(
            output=str(content),
            model=self._model,
            provider="openai",
            finish_reason=str(finish_reason),
        )


def build_llm_adapter(settings: PlatformSettings, secrets: SecretProviderBundle) -> LLMAdapter:
    if settings.llm_provider == "stub":
        return StubLLMAdapter(settings.llm_model)
    if settings.llm_provider == "openai":
        return OpenAIChatCompletionsAdapter(
            model=settings.llm_model,
            base_url=settings.openai_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
            api_key_secret_name=settings.openai_api_key_secret_name,
            secrets=secrets,
        )
    raise ValueError(f"Unsupported llm provider: {settings.llm_provider}")
