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


def test_openai_gpt5_uses_reasoning_compatible_chat_parameters(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    seen = {}

    async def handler(request: httpx.Request):
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "positioning"}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        OpenAICompatibleConfig(model="gpt-5", base_url="https://api.openai.com/v1"),
        client=client,
    )
    try:
        result = run(provider.generate(make_request()))
    finally:
        run(client.aclose())

    payload = seen["payload"]
    assert payload["max_completion_tokens"] == 64
    assert "max_tokens" not in payload
    assert "temperature" not in payload
    assert "reasoning_effort" not in payload
    assert result.text == "positioning"


@pytest.mark.parametrize("model", ["gpt-5", "o3"])
def test_configured_official_reasoning_effort_is_sent_for_reasoning_models(monkeypatch, model):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    seen = {}

    async def handler(request: httpx.Request):
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "useful output"}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(OpenAICompatibleConfig(
        model=model, base_url="https://api.openai.com/v1", reasoning_effort="low",
    ), client=client)
    try:
        result = run(provider.generate(make_request()))
    finally:
        run(client.aclose())
    assert seen["payload"]["reasoning_effort"] == "low"
    assert seen["payload"]["max_completion_tokens"] == 64
    assert "temperature" not in seen["payload"]
    assert result.text == "useful output"


def test_reasoning_effort_is_omitted_for_non_reasoning_or_compatible_endpoint(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    payloads = []

    async def handler(request: httpx.Request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "output"}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    providers = [
        OpenAICompatibleProvider(OpenAICompatibleConfig(model="gpt-4.1", reasoning_effort="low"), client),
        OpenAICompatibleProvider(OpenAICompatibleConfig(
            model="gpt-5", base_url="https://compatible.example/v1", reasoning_effort="low",
        ), client),
    ]
    try:
        for provider in providers:
            run(provider.generate(make_request()))
    finally:
        run(client.aclose())
    assert all("reasoning_effort" not in payload for payload in payloads)


def test_openai_compatible_config_rejects_unknown_reasoning_effort():
    with pytest.raises(ValidationError):
        OpenAICompatibleConfig(model="gpt-5", reasoning_effort="xhigh")


def test_response_diagnostics_capture_safe_finish_refusal_and_token_details(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")

    async def handler(request: httpx.Request):
        return httpx.Response(200, json={
            "id": "chatcmpl-diagnostics", "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "choices": [{"finish_reason": "length", "message": {
                "content": "   ", "refusal": "private refusal details must not be retained",
            }}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 64, "total_tokens": 67,
                      "completion_tokens_details": {"reasoning_tokens": 60,
                          "accepted_prediction_tokens": 2}},
        })

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(OpenAICompatibleConfig(model="test-model"), client=client)
    try:
        result = run(provider.generate(make_request()))
    finally:
        run(client.aclose())

    assert result.text == "   "
    assert result.metadata["response_diagnostics"] == {
        "finish_reason": "length", "refusal_present": True, "reasoning_tokens": 60,
        "output_token_details": {"reasoning_tokens": 60, "accepted_prediction_tokens": 2},
        "content_empty": True, "provider_status": "incomplete",
        "incomplete_reason": "max_output_tokens",
    }
    assert "private refusal details" not in json.dumps(result.metadata)


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
                    "param": "max_tokens",
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
    assert "parameter=max_tokens" in message
    assert len(message) < 300


def test_provider_error_parameter_is_sanitized_against_secret(monkeypatch):
    secret = "sk-secret-value"
    monkeypatch.setenv("OPENAI_API_KEY", secret)

    async def handler(request: httpx.Request):
        return httpx.Response(400, json={"error": {"param": secret}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(OpenAICompatibleConfig(model="test-model"), client=client)
    try:
        with pytest.raises(ProviderHTTPError) as caught:
            run(provider.generate(make_request()))
    finally:
        run(client.aclose())
    assert secret not in str(caught.value)
    assert caught.value.parameter is None


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
