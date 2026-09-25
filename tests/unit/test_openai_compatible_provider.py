import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from kdp_pipeline.core.hashing import sha256_text
from kdp_pipeline.providers import (
    GenerationRequest,
    OpenAICompatibleConfig,
    OpenAICompatibleProvider,
    ProviderConfigurationError,
    ProviderHTTPError,
    ProviderResponseError,
    ProviderTransportError,
    RenderedPrompt,
)


def make_request(*, structured_schema=None, structured_schema_ref=None):
    text = "Rendered prompt"
    return GenerationRequest(
        task_type="test-task",
        system_instructions="System instructions",
        rendered_prompt=RenderedPrompt(
            template_id="tests/provider",
            template_version="1.0",
            rendered_text=text,
            rendered_sha256=sha256_text(text),
        ),
        max_output_tokens=64,
        temperature=0.25,
        structured_output_schema=structured_schema,
        structured_output_schema_ref=structured_schema_ref,
    )


def run(coro):
    return asyncio.run(coro)


def test_config_defaults_and_from_env(monkeypatch):
    config = OpenAICompatibleConfig(model="test-model")
    assert config.base_url == "https://api.openai.com/v1"

    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://local.example/v1/")
    monkeypatch.setenv("OPENAI_MODEL", "local-model")
    from_env = OpenAICompatibleConfig.from_env()
    assert from_env.base_url == "https://local.example/v1"
    assert from_env.model == "local-model"
    assert not hasattr(from_env, "api_key")

    monkeypatch.delenv("OPENAI_API_KEY")
    with pytest.raises(ProviderConfigurationError, match="OPENAI_API_KEY"):
        OpenAICompatibleConfig.from_env()

    with pytest.raises(ValidationError):
        OpenAICompatibleConfig(model="test-model", base_url="not-a-url")


def test_successful_request_and_response_mapping(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    seen = {}

    async def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers["authorization"]
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "model": "server-alias",
                "choices": [{"message": {"content": "provider output"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        OpenAICompatibleConfig(model="test-model"),
        client=client,
    )
    try:
        result = run(provider.generate(make_request()))
    finally:
        run(client.aclose())

    assert provider.provider_name == "openai-compatible"
    assert provider.model_name == "test-model"
    assert seen["url"] == "https://api.openai.com/v1/chat/completions"
    assert seen["authorization"] == "Bearer test-secret"
    assert seen["payload"] == {
        "model": "test-model",
        "messages": [
            {"role": "system", "content": "System instructions"},
            {"role": "user", "content": "Rendered prompt"},
        ],
        "max_tokens": 64,
        "temperature": 0.25,
    }
    assert result.provider == "openai-compatible"
    assert result.model == "test-model"
    assert result.text == "provider output"
    assert result.provider_response_ref == "chatcmpl-test"
    assert result.usage.input_tokens == 11
    assert result.usage.output_tokens == 7
    assert result.usage.total_tokens == 18
    assert result.latency_ms >= 0


def test_inline_structured_schema_maps_and_parses(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    seen = {}

    async def handler(request: httpx.Request):
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"ok": true}'}}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(OpenAICompatibleConfig(model="test-model"), client=client)
    try:
        result = run(provider.generate(make_request(structured_schema=schema)))
    finally:
        run(client.aclose())

    assert seen["payload"]["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "structured_output", "strict": True, "schema": schema},
    }
    assert result.structured_data == {"ok": True}


def test_schema_reference_without_inline_schema_fails_without_request(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    calls = 0

    async def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(OpenAICompatibleConfig(model="test-model"), client=client)
    try:
        with pytest.raises(ProviderConfigurationError, match="schema resolver"):
            run(provider.generate(make_request(structured_schema_ref="schemas/test.json")))
    finally:
        run(client.aclose())
    assert calls == 0


def test_endpoint_structured_output_error_is_not_retried(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    calls = 0

    async def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"error": {"type": "invalid_request_error", "code": "unsupported_format"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(OpenAICompatibleConfig(model="test-model"), client=client)
    try:
        with pytest.raises(ProviderHTTPError, match="unsupported_format"):
            run(provider.generate(make_request(structured_schema={"type": "object"})))
    finally:
        run(client.aclose())
    assert calls == 1


def test_errors_do_not_leak_key_prompt_or_large_response(monkeypatch):
    secret = "super-secret-api-key"
    monkeypatch.setenv("OPENAI_API_KEY", secret)

    async def handler(request: httpx.Request):
        return httpx.Response(
            500,
            json={
                "error": {
                    "type": "server_error",
                    "code": "internal",
                    "message": f"{secret} Rendered prompt and sensitive body " + "x" * 10000,
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(OpenAICompatibleConfig(model="test-model"), client=client)
    try:
        with pytest.raises(ProviderHTTPError) as caught:
            run(provider.generate(make_request()))
    finally:
        run(client.aclose())
    message = str(caught.value)
    assert secret not in message
    assert "Rendered prompt" not in message
    assert len(message) < 300


def test_transport_and_malformed_response_errors(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")

    def transport_failure(request: httpx.Request):
        raise httpx.ConnectError("network unavailable", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(transport_failure))
    provider = OpenAICompatibleProvider(OpenAICompatibleConfig(model="test-model"), client=client)
    try:
        with pytest.raises(ProviderTransportError, match="ConnectError"):
            run(provider.generate(make_request()))
    finally:
        run(client.aclose())

    async def malformed(request: httpx.Request):
        return httpx.Response(200, json={"choices": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(malformed))
    provider = OpenAICompatibleProvider(OpenAICompatibleConfig(model="test-model"), client=client)
    try:
        with pytest.raises(ProviderResponseError, match="choices"):
            run(provider.generate(make_request()))
    finally:
        run(client.aclose())
