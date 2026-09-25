from __future__ import annotations

from typing import Protocol, runtime_checkable

from kdp_pipeline.providers.contracts import GenerationRequest, GenerationResult


@runtime_checkable
class ModelProvider(Protocol):
    @property
    def provider_name(self) -> str:
        """Stable provider identity declared before generation."""

    @property
    def model_name(self) -> str:
        """Stable model identity declared before generation."""

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        """Generate a result without performing persistence or workflow side effects."""
