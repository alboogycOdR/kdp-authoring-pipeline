from __future__ import annotations

from typing import Protocol, runtime_checkable

from kdp_pipeline.providers.contracts import GenerationRequest, GenerationResult


@runtime_checkable
class ModelProvider(Protocol):
    async def generate(self, request: GenerationRequest) -> GenerationResult:
        """Generate a result without performing persistence or workflow side effects."""

