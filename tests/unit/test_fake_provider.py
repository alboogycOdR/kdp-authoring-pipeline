import asyncio

from kdp_pipeline.core.hashing import sha256_text
from kdp_pipeline.providers import FakeProvider, GenerationRequest, RenderedPrompt


def request():
    text = "Prompt text"
    return GenerationRequest(
        task_type="test-task",
        system_instructions="Test instructions",
        rendered_prompt=RenderedPrompt(
            template_id="tests/example",
            template_version="1.0",
            rendered_text=text,
            rendered_sha256=sha256_text(text),
        ),
        context_manifest_ref="manifest-hash",
        max_output_tokens=64,
    )


def test_fake_provider_is_deterministic_and_declares_identity():
    provider = FakeProvider()
    first = asyncio.run(provider.generate(request()))
    second = asyncio.run(provider.generate(request()))

    assert provider.provider_name == "fake"
    assert provider.model_name == "fake-v1"
    assert first == second
    assert first.provider == provider.provider_name
    assert first.model == provider.model_name
