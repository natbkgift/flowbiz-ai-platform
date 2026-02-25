"""LLM adapter implementations for platform runtime (stub + provider hooks)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from platform_app.config import PlatformSettings
from platform_app.secrets import SecretProviderBundle


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1)
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    output: str
    model: str
    provider: str
    finish_reason: str = "stop"


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


class OpenAIAdapterStub(LLMAdapter):
    """Provider placeholder. Real implementation lands in subsequent platform PRs."""

    def __init__(self, model: str, _secrets: SecretProviderBundle) -> None:
        self._model = model

    def chat(self, req: ChatRequest) -> ChatResponse:
        raise NotImplementedError("OpenAI adapter not implemented yet")


def build_llm_adapter(settings: PlatformSettings, secrets: SecretProviderBundle) -> LLMAdapter:
    if settings.llm_provider == "stub":
        return StubLLMAdapter(settings.llm_model)
    if settings.llm_provider == "openai":
        return OpenAIAdapterStub(settings.llm_model, secrets)
    raise ValueError(f"Unsupported llm provider: {settings.llm_provider}")
