import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from kdp_pipeline.context import ContextInput, ContextManifest
from kdp_pipeline.core.hashing import canonical_json_bytes, sha256_text
from kdp_pipeline.providers import GenerationRequest, GenerationResult, ModelProvider, RenderedPrompt
from kdp_pipeline.prompts import MissingPromptVariableError, PromptNotFoundError, PromptRegistry


class TinyProvider:
    provider_name = "tiny-test"
    model_name = "tiny-test-v1"

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(provider="fake", model="tiny", text=request.rendered_prompt.rendered_text)


def make_prompt() -> RenderedPrompt:
    text = "Hello Ada"
    return RenderedPrompt(
        template_id="planning/greeting",
        template_version="1.0",
        rendered_text=text,
        rendered_sha256=sha256_text(text),
    )


def test_provider_protocol_compatibility():
    assert isinstance(TinyProvider(), ModelProvider)


def test_generation_request_requires_typed_prompt_identity():
    request = GenerationRequest(
        task_type="classification",
        system_instructions="Be precise.",
        rendered_prompt=make_prompt(),
        context_manifest_ref="manifest-1",
        max_output_tokens=128,
        structured_output_schema={"type": "object"},
        structured_output_schema_ref="schemas/classification.json",
    )
    assert request.rendered_prompt.template_id == "planning/greeting"
    assert request.rendered_prompt.rendered_sha256 == sha256_text("Hello Ada")

    with pytest.raises(ValidationError):
        GenerationRequest(
            task_type="classification",
            system_instructions="Be precise.",
            rendered_prompt={"template_id": "x", "template_version": "1.0", "rendered_text": "x"},
            max_output_tokens=128,
        )


def test_generation_result_validation():
    result = GenerationResult(
        provider="fake",
        model="tiny",
        text="result",
        structured_data={"ok": True},
        usage={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
        latency_ms=1.5,
        provider_response_ref="fake://response/1",
    )
    assert result.usage.total_tokens == 5
    with pytest.raises(ValidationError):
        GenerationResult(provider="fake", model="tiny", text="result", latency_ms=-1)


def test_prompt_lookup_rendering_version_and_hash(tmp_path: Path):
    prompt_path = tmp_path / "planning" / "greeting-v1.0.md"
    prompt_path.parent.mkdir()
    prompt_path.write_text("Hello {{ name }}\n", encoding="utf-8")
    registry = PromptRegistry(tmp_path)

    template = registry.load("planning/greeting")
    assert template.template_version == "1.0"
    rendered = registry.render("planning/greeting", {"name": "Ada"})
    assert rendered.rendered_text == "Hello Ada\n"
    assert rendered.rendered_sha256 == hashlib.sha256(b"Hello Ada\n").hexdigest()


def test_prompt_failures_are_clear(tmp_path: Path):
    prompt_path = tmp_path / "drafting" / "chapter-v1.0.md"
    prompt_path.parent.mkdir()
    prompt_path.write_text("Draft {{ chapter }}", encoding="utf-8")
    registry = PromptRegistry(tmp_path)

    with pytest.raises(PromptNotFoundError):
        registry.load("missing/template")
    with pytest.raises(MissingPromptVariableError, match="chapter"):
        registry.render("drafting/chapter", {})


def test_context_manifest_hash_is_deterministic_and_order_sensitive():
    digest_a = "a" * 64
    digest_b = "b" * 64
    created_a = datetime(2026, 1, 1, tzinfo=timezone.utc)
    created_b = created_a + timedelta(days=1)
    inputs = [
        ContextInput(input_ref="asset-a", sha256=digest_a, context_tier="A", role="brief"),
        ContextInput(input_ref="asset-b", sha256=digest_b, context_tier="B", role="character"),
    ]
    first = ContextManifest(title_id="BK-1", task_type="draft", inputs=inputs, created_at=created_a)
    second = ContextManifest(title_id="BK-1", task_type="draft", inputs=inputs, created_at=created_b)
    reordered = ContextManifest(title_id="BK-1", task_type="draft", inputs=list(reversed(inputs)), created_at=created_a)

    assert first.manifest_hash == second.manifest_hash
    assert first.manifest_hash != reordered.manifest_hash
    assert first.manifest_hash == hashlib.sha256(canonical_json_bytes(first.semantic_payload())).hexdigest()


def test_changed_context_input_changes_manifest_hash():
    base = ContextManifest(
        title_id="BK-1",
        task_type="draft",
        inputs=[ContextInput(input_ref="asset-a", sha256="a" * 64)],
    )
    changed = ContextManifest(
        title_id="BK-1",
        task_type="draft",
        inputs=[ContextInput(input_ref="asset-a", sha256="b" * 64)],
    )
    assert base.manifest_hash != changed.manifest_hash
