from __future__ import annotations

import json
import ipaddress
import os
import re
import time
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field, field_validator

from kdp_pipeline.providers.contracts import GenerationRequest, GenerationResult, UsageMetadata


class OpenAICompatibleProviderError(RuntimeError):
    """Base error for the isolated OpenAI-compatible adapter."""


class ProviderConfigurationError(OpenAICompatibleProviderError):
    pass


class ProviderTransportError(OpenAICompatibleProviderError):
    pass


class ProviderHTTPError(OpenAICompatibleProviderError):
    def __init__(self, status_code: int, error_type: str | None = None, error_code: str | None = None):
        self.status_code = status_code
        self.error_type = error_type
        self.error_code = error_code
        details = [f"HTTP {status_code}"]
        if error_type:
            details.append(f"type={error_type}")
        if error_code:
            details.append(f"code={error_code}")
        super().__init__("OpenAI-compatible provider error (" + ", ".join(details) + ")")


class ProviderResponseError(OpenAICompatibleProviderError):
    pass


class OpenAICompatibleConfig(BaseModel):
    base_url: str = "https://api.openai.com/v1"
    model: str = Field(min_length=1)
    api_key_env: str | None = Field(default="OPENAI_API_KEY", min_length=1)
    timeout_seconds: float = Field(default=60.0, gt=0)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an absolute http(s) URL")
        if parsed.query or parsed.fragment:
            raise ValueError("base_url must not contain a query string or fragment")
        return value.rstrip("/")

    @classmethod
    def from_env(cls) -> "OpenAICompatibleConfig":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ProviderConfigurationError("Missing API key in environment variable OPENAI_API_KEY")
        model = os.getenv("OPENAI_MODEL")
        if not model:
            raise ProviderConfigurationError("Missing model in environment variable OPENAI_MODEL")
        return cls(
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            model=model,
        )


def _safe_error_identity(value: object, secret: str | None = None) -> str | None:
    if not isinstance(value, str):
        return None
    # Error type/code are deliberately constrained to short identifier-like values.
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", value):
        return None
    if secret and secret.casefold() in value.casefold():
        return None
    return value


class OpenAICompatibleProvider:
    def __init__(self, config: OpenAICompatibleConfig, client: httpx.AsyncClient | None = None):
        self.config = config
        self._client = client

    @property
    def provider_name(self) -> str:
        return "openai-compatible"

    @property
    def model_name(self) -> str:
        return self.config.model

    def _payload(self, request: GenerationRequest) -> dict:
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": request.system_instructions},
                {"role": "user", "content": request.rendered_prompt.rendered_text},
            ],
            "max_tokens": request.max_output_tokens,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.structured_output_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_output",
                    "strict": True,
                    "schema": request.structured_output_schema,
                },
            }
        elif request.structured_output_schema_ref is not None:
            raise ProviderConfigurationError(
                "structured_output_schema_ref requires an inline structured_output_schema; "
                "no schema resolver exists for this adapter"
            )
        return payload

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        api_key = os.getenv(self.config.api_key_env) if self.config.api_key_env else None
        parsed_url = urlparse(self.config.base_url)
        host = parsed_url.hostname or ""
        loopback = host == "localhost"
        try:
            loopback = loopback or ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass
        if not api_key and not loopback:
            raise ProviderConfigurationError(
                f"Missing API key in environment variable {self.config.api_key_env or 'OPENAI_API_KEY'}"
            )

        payload = self._payload(request)
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        owned_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.config.timeout_seconds)
        started = time.perf_counter()
        try:
            try:
                response = await client.post(
                    f"{self.config.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
            except httpx.HTTPError as exc:
                raise ProviderTransportError(
                    f"OpenAI-compatible provider transport failure: {type(exc).__name__}"
                ) from exc

            if response.status_code >= 400:
                error_type = None
                error_code = None
                try:
                    error_body = response.json()
                    error = error_body.get("error", {}) if isinstance(error_body, dict) else {}
                    if isinstance(error, dict):
                        error_type = _safe_error_identity(error.get("type"), api_key)
                        error_code = _safe_error_identity(error.get("code"), api_key)
                except (ValueError, json.JSONDecodeError):
                    pass
                raise ProviderHTTPError(response.status_code, error_type, error_code)

            try:
                body = response.json()
            except (ValueError, json.JSONDecodeError) as exc:
                raise ProviderResponseError("Provider returned a non-JSON response") from exc

            try:
                choice = body["choices"][0]
                message = choice["message"]
                text = message["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise ProviderResponseError("Provider response is missing choices[0].message.content") from exc
            if not isinstance(text, str):
                raise ProviderResponseError("Provider response content is not text")

            structured_data = None
            if request.structured_output_schema is not None:
                try:
                    structured_data = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise ProviderResponseError(
                        "Provider returned invalid JSON for the requested structured output"
                    ) from exc

            usage = body.get("usage")
            usage_metadata = UsageMetadata(
                input_tokens=usage.get("prompt_tokens") if isinstance(usage, dict) else None,
                output_tokens=usage.get("completion_tokens") if isinstance(usage, dict) else None,
                total_tokens=usage.get("total_tokens") if isinstance(usage, dict) else None,
                cached_input_tokens=(usage.get("prompt_tokens_details", {}).get("cached_tokens")
                                     if isinstance(usage, dict) and isinstance(usage.get("prompt_tokens_details"), dict)
                                     else None),
                reported_cost=(usage.get("cost") if isinstance(usage, dict)
                               and isinstance(usage.get("cost"), (int, float)) else None),
                currency="USD" if isinstance(usage, dict) and isinstance(usage.get("cost"), (int, float)) else None,
            ) if isinstance(usage, dict) else None

            response_id = body.get("id") if isinstance(body, dict) else None
            return GenerationResult(
                provider=self.provider_name,
                model=self.model_name,
                text=text,
                structured_data=structured_data,
                usage=usage_metadata,
                latency_ms=(time.perf_counter() - started) * 1000,
                provider_response_ref=response_id if isinstance(response_id, str) else None,
            )
        finally:
            if owned_client:
                await client.aclose()
