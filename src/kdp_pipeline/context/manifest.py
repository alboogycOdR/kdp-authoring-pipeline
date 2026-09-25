from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field, model_validator

from kdp_pipeline.core.hashing import canonical_json_bytes, sha256_bytes


class ContextInput(BaseModel):
    input_ref: str
    sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")
    context_tier: str | None = None
    role: str | None = None


class ContextManifest(BaseModel):
    title_id: str
    task_type: str
    inputs: list[ContextInput]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    manifest_hash: str | None = None

    @model_validator(mode="after")
    def set_or_validate_hash(self) -> "ContextManifest":
        expected = sha256_bytes(canonical_json_bytes(self.semantic_payload()))
        if self.manifest_hash is not None and self.manifest_hash != expected:
            raise ValueError("manifest_hash does not match the semantic manifest contents")
        self.manifest_hash = expected
        return self

    def semantic_payload(self) -> dict:
        """Return the hash payload; timestamp and manifest_hash are intentionally excluded."""
        return {
            "title_id": self.title_id,
            "task_type": self.task_type,
            "inputs": [item.model_dump(mode="json", exclude_none=True) for item in self.inputs],
        }
