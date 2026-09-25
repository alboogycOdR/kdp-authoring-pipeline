import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from kdp_pipeline.context import ContextInput, ContextManifest
from kdp_pipeline.core.hashing import sha256_text
from kdp_pipeline.generation import GenerationService
from kdp_pipeline.providers import FakeProvider, GenerationRequest, GenerationResult, RenderedPrompt
from kdp_pipeline.storage.db import AssetRow, JobRow, ProvenanceRow
from kdp_pipeline.storage.service import create_project, create_title, list_audit, session_scope


def make_prompt(text: str = "Generate a deterministic output.") -> RenderedPrompt:
    return RenderedPrompt(
        template_id="tests/generation",
        template_version="1.0",
        rendered_text=text,
        rendered_sha256=sha256_text(text),
    )


def make_manifest(title_id: str, input_hash: str = "a" * 64) -> ContextManifest:
    return ContextManifest(
        title_id=title_id,
        task_type="fake-generation",
        inputs=[ContextInput(input_ref="brief-1", sha256=input_hash, context_tier="A", role="brief")],
    )


class CountingFakeProvider(FakeProvider):
    def __init__(self, provider_name="fake", model_name="fake-v1"):
        super().__init__(provider_name, model_name)
        self.calls = 0

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.calls += 1
        return await super().generate(request)


def run_generation(root: Path, title_id: str, provider, prompt=None, manifest=None):
    return asyncio.run(
        GenerationService.generate(
            root,
            title_id=title_id,
            task_type="draft/test output",
            rendered_prompt=prompt or make_prompt(),
            context_manifest=manifest or make_manifest(title_id),
            provider=provider,
            system_instructions="Return only the generated test text.",
            max_output_tokens=128,
            temperature=0,
        )
    )


def setup_title(tmp_path: Path):
    project = create_project(tmp_path, "Generation Project")
    title = create_title(tmp_path, project.project_id, "Generation Title")
    return project, title


def test_generation_service_persists_experimental_asset_provenance_and_audit(tmp_path: Path):
    _, title = setup_title(tmp_path)
    result = run_generation(tmp_path, title.title_id, CountingFakeProvider())

    assert result.reused is False
    assert result.output_path.parent.name == "experimental"
    assert result.output_path.name == f"draft-test-output-{result.job.job_id}.md"
    assert result.output_path.is_file()
    assert result.asset.approval_status == "experimental"
    assert result.asset.sha256 == __import__("hashlib").sha256(result.output_path.read_bytes()).hexdigest()
    assert result.provenance.job_id == result.job.job_id
    assert result.provenance.asset_id == result.asset.asset_id
    assert result.provenance.provider == "fake"
    assert result.provenance.model == "fake-v1"
    assert result.provenance.prompt_template_id == "tests/generation"
    assert result.provenance.prompt_template_version == "1.0"
    assert result.provenance.rendered_prompt_sha256 == make_prompt().rendered_sha256
    assert result.provenance.input_references == ["brief-1"]
    assert result.provenance.input_hashes == ["a" * 64]
    assert result.provenance.context_manifest_hash == make_manifest(title.title_id).manifest_hash
    assert result.provenance.output_hash == result.asset.sha256

    actions = [event.action for event in list_audit(tmp_path, result.job.job_id)]
    assert actions == [
        "generation.job.created",
        "generation.started",
        "generation.succeeded",
    ]
    assert "asset.register" in [event.action for event in list_audit(tmp_path, result.asset.asset_id)]
    assert "provenance.create" in [event.action for event in list_audit(tmp_path, result.provenance.provenance_id)]


def test_idempotent_rerun_reuses_everything_without_provider_or_file_rewrite(tmp_path: Path):
    _, title = setup_title(tmp_path)
    provider = CountingFakeProvider()
    first = run_generation(tmp_path, title.title_id, provider)
    first_text = first.output_path.read_text(encoding="utf-8")
    first_mtime = first.output_path.stat().st_mtime_ns

    second = run_generation(tmp_path, title.title_id, provider)

    assert provider.calls == 1
    assert second.reused is True
    assert second.job.job_id == first.job.job_id
    assert second.asset.asset_id == first.asset.asset_id
    assert second.provenance.provenance_id == first.provenance.provenance_id
    assert second.output_path == first.output_path
    assert second.output_path.read_text(encoding="utf-8") == first_text
    assert second.output_path.stat().st_mtime_ns == first_mtime
    with session_scope(tmp_path) as session:
        assert session.scalar(select(func.count(AssetRow.asset_id))) == 1
        assert session.scalar(select(func.count(ProvenanceRow.provenance_id))) == 1
    assert "generation.reused" in [event.action for event in list_audit(tmp_path, first.job.job_id)]


def test_prompt_or_context_change_creates_new_idempotency_boundary(tmp_path: Path):
    _, title = setup_title(tmp_path)
    provider = CountingFakeProvider()
    first = run_generation(tmp_path, title.title_id, provider)
    changed_prompt = run_generation(tmp_path, title.title_id, provider, prompt=make_prompt("Changed prompt."))
    changed_context = run_generation(
        tmp_path,
        title.title_id,
        provider,
        manifest=make_manifest(title.title_id, "b" * 64),
    )

    assert len({first.job.job_id, changed_prompt.job.job_id, changed_context.job.job_id}) == 3
    assert len({first.job.input_manifest_hash, changed_prompt.job.input_manifest_hash, changed_context.job.input_manifest_hash}) == 3
    assert provider.calls == 3


def test_provider_failure_marks_job_failed_without_asset_or_provenance(tmp_path: Path):
    _, title = setup_title(tmp_path)

    class FailingProvider:
        provider_name = "fake-failing"
        model_name = "fake-failing-v1"

        async def generate(self, request):
            raise RuntimeError("deliberate provider failure")

    with pytest.raises(RuntimeError, match="deliberate provider failure"):
        run_generation(tmp_path, title.title_id, FailingProvider())

    with session_scope(tmp_path) as session:
        job = session.scalar(select(JobRow).where(JobRow.title_id == title.title_id))
        assert job.status == "failed"
        assert "deliberate provider failure" in job.error
        assert session.scalar(select(func.count(AssetRow.asset_id))) == 0
        assert session.scalar(select(func.count(ProvenanceRow.provenance_id))) == 0
    assert not list((tmp_path / "projects" / next(iter([p.name for p in (tmp_path / "projects").iterdir()])) / "titles" / title.title_id / "05_drafts" / "experimental").glob("*.md"))
    assert "generation.failed" in [event.action for event in list_audit(tmp_path, job.job_id)]
