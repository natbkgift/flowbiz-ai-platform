from __future__ import annotations

import json

import httpx
import pytest

from platform_app.llm import (
    ChatRequest,
    LLMProviderError,
    OpenAIChatCompletionsAdapter,
)
from platform_app.secrets import JsonFileSecretProvider, SecretNotFoundError, SecretProviderBundle


class _FakeResponse:
    def __init__(self, status_code: int, payload) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeHTTPClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.calls: list[dict[str, object]] = []
        self.closed = False

    def post(self, url: str, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self._response

    def close(self) -> None:
        self.closed = True


def test_json_file_secret_provider_reads_values(tmp_path) -> None:
    path = tmp_path / "secrets.json"
    path.write_text(json.dumps({"OPENAI_API_KEY": "sk-test"}), encoding="utf-8")
    provider = JsonFileSecretProvider(str(path))
    assert provider.get("OPENAI_API_KEY") == "sk-test"


def test_json_file_secret_provider_missing_key_raises(tmp_path) -> None:
    path = tmp_path / "secrets.json"
    path.write_text("{}", encoding="utf-8")
    provider = JsonFileSecretProvider(str(path))
    with pytest.raises(SecretNotFoundError):
        provider.get("OPENAI_API_KEY")


def test_openai_adapter_success_uses_secret_and_parses_response(tmp_path) -> None:
    secret_file = tmp_path / "secrets.json"
    secret_file.write_text(json.dumps({"OPENAI_API_KEY": "sk-test"}), encoding="utf-8")
    secrets_bundle = SecretProviderBundle(
        provider_name="file_json",
        provider=JsonFileSecretProvider(str(secret_file)),
    )
    fake_client = _FakeHTTPClient(
        _FakeResponse(
            200,
            {
                "choices": [
                    {
                        "message": {"content": "Hello from OpenAI"},
                        "finish_reason": "stop",
                    }
                ]
            },
        )
    )
    adapter = OpenAIChatCompletionsAdapter(
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        timeout_seconds=30,
        api_key_secret_name="OPENAI_API_KEY",
        secrets=secrets_bundle,
        client=fake_client,
    )
    resp = adapter.chat(ChatRequest(prompt="hi"))
    assert resp.provider == "openai"
    assert resp.output == "Hello from OpenAI"
    assert fake_client.calls[0]["url"] == "https://api.openai.com/v1/chat/completions"
    auth = fake_client.calls[0]["headers"]["Authorization"]  # type: ignore[index]
    assert auth == "Bearer sk-test"


def test_openai_adapter_maps_api_error_to_platform_error(tmp_path) -> None:
    secret_file = tmp_path / "secrets.json"
    secret_file.write_text(json.dumps({"OPENAI_API_KEY": "sk-test"}), encoding="utf-8")
    secrets_bundle = SecretProviderBundle(
        provider_name="file_json",
        provider=JsonFileSecretProvider(str(secret_file)),
    )
    fake_client = _FakeHTTPClient(
        _FakeResponse(401, {"error": {"message": "Invalid API key"}})
    )
    adapter = OpenAIChatCompletionsAdapter(
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        timeout_seconds=30,
        api_key_secret_name="OPENAI_API_KEY",
        secrets=secrets_bundle,
        client=fake_client,
    )
    with pytest.raises(LLMProviderError) as exc:
        adapter.chat(ChatRequest(prompt="hi"))
    assert "Invalid API key" in str(exc.value)


def test_openai_adapter_maps_transport_error(tmp_path) -> None:
    secret_file = tmp_path / "secrets.json"
    secret_file.write_text(json.dumps({"OPENAI_API_KEY": "sk-test"}), encoding="utf-8")
    secrets_bundle = SecretProviderBundle(
        provider_name="file_json",
        provider=JsonFileSecretProvider(str(secret_file)),
    )

    class _ErrClient:
        def post(self, *args, **kwargs):
            raise httpx.ConnectError("boom")

        def close(self) -> None:
            return None

    adapter = OpenAIChatCompletionsAdapter(
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        timeout_seconds=30,
        api_key_secret_name="OPENAI_API_KEY",
        secrets=secrets_bundle,
        client=_ErrClient(),
    )
    with pytest.raises(LLMProviderError):
        adapter.chat(ChatRequest(prompt="hi"))

