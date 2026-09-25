from __future__ import annotations

from kdp_pipeline.core.hashing import canonical_json_bytes, sha256_bytes
from kdp_pipeline.providers.contracts import GenerationRequest, GenerationResult


class FakeProvider:
    """Deterministic provider for tests and local dry-runs only."""

    def __init__(self, provider_name: str = "fake", model_name: str = "fake-v1"):
        self._provider_name = provider_name
        self._model_name = model_name

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        identity = {
            "provider": self.provider_name,
            "model": self.model_name,
            "task_type": request.task_type,
            "system_instructions": request.system_instructions,
            "rendered_prompt": request.rendered_prompt.model_dump(mode="json"),
            "context_manifest_ref": request.context_manifest_ref,
            "max_output_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "structured_output_schema": request.structured_output_schema,
            "structured_output_schema_ref": request.structured_output_schema_ref,
        }
        digest = sha256_bytes(canonical_json_bytes(identity))
        text = (
            f"[fake:{self.provider_name}/{self.model_name}] {request.task_type}\n"
            f"{request.rendered_prompt.rendered_text}\n"
            f"generation-digest:{digest}\n"
        )
        return GenerationResult(
            provider=self.provider_name,
            model=self.model_name,
            text=text,
            latency_ms=0,
            metadata={"deterministic": True},
        )
