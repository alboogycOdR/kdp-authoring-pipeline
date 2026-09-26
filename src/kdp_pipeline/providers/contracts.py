from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kdp_pipeline.core.hashing import sha256_text


class RenderedPrompt(BaseModel):
    """The exact versioned prompt content supplied to a provider."""

    model_config = ConfigDict(frozen=True)

    template_id: str
    template_version: str
    rendered_text: str
    rendered_sha256: str

    @model_validator(mode="after")
    def validate_hash(self) -> "RenderedPrompt":
        expected = sha256_text(self.rendered_text)
        if self.rendered_sha256 != expected:
            raise ValueError("rendered_sha256 does not match rendered_text")
        return self


class UsageMetadata(BaseModel):
    """Small provider-neutral usage record; unavailable values remain None."""

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    estimated_cost: float | None = Field(default=None, ge=0)
    reported_cost: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class GenerationRequest(BaseModel):
    task_type: str
    system_instructions: str
    rendered_prompt: RenderedPrompt
    context_manifest_ref: str | None = None
    max_output_tokens: int = Field(gt=0)
    temperature: float | None = Field(default=None, ge=0)
    structured_output_schema: dict[str, Any] | None = None
    structured_output_schema_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GenerationResult(BaseModel):
    provider: str
    model: str
    text: str
    structured_data: Any | None = None
    usage: UsageMetadata | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    provider_response_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
