import asyncio
import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from kdp_pipeline.chapter import ChapterService
from kdp_pipeline.context import ContextManifest
from kdp_pipeline.editorial import EditorialService
from kdp_pipeline.generation.service import GenerationServiceError
from kdp_pipeline.models.planning import PlanningArtifactKind
from kdp_pipeline.planning import PlanningService, accept_planning_artifact
from kdp_pipeline.providers import FakeProvider, GenerationResult, UsageMetadata
from kdp_pipeline.providers.configuration import add_provider_profile, select_provider_for_project
from kdp_pipeline.providers.settings import ProviderProfileSettings
from kdp_pipeline.storage.db import AuditEventRow, EditorialFindingRow, JobRow, UsageEventRow
from kdp_pipeline.storage.service import (advance_to_drafting, advance_to_planned, advance_to_validated,
                                          create_project, create_title, session_scope)
from kdp_pipeline.inspection import inspect_title


PROFILE_ID = "editorial-gpt5-low"


def setup_drafting_title(tmp_path):
    shutil.copytree(Path("prompts"), tmp_path / "prompts")
    project = create_project(tmp_path, "Sprint 6.5 editorial")
    title = create_title(tmp_path, project.project_id, "Provider default fixture")
    planner = FakeProvider()
    for kind, chapter_number in ((PlanningArtifactKind.POSITIONING, None), (PlanningArtifactKind.BOOK_BRIEF, None),
                                 (PlanningArtifactKind.OUTLINE, None), (PlanningArtifactKind.CHAPTER_CARD, 1)):
        result = asyncio.run(PlanningService.generate(
            tmp_path, title_id=title.title_id, artifact_kind=kind,
            context_manifest=ContextManifest(title_id=title.title_id, task_type="planning", inputs=[]),
            provider=planner, chapter_number=chapter_number,
        ))
        accept_planning_artifact(tmp_path, result.asset.asset_id, reviewer="test", chapter_number=chapter_number)
    advance_to_validated(tmp_path, title.title_id)
    advance_to_planned(tmp_path, title.title_id)
    advance_to_drafting(tmp_path, title.title_id)
    draft = asyncio.run(ChapterService.draft(tmp_path, title_id=title.title_id, chapter_number=1, provider=planner))
    add_provider_profile(tmp_path, ProviderProfileSettings(
        provider_id=PROFILE_ID, provider_type="openai-compatible", display_name="Test GPT-5 profile",
        model="gpt-5", base_url="https://api.openai.com/v1", api_key_env="UNUSED_TEST_KEY",
        default_max_output_tokens=4000, reasoning_effort="low", read_timeout_seconds=180,
    ))
    select_provider_for_project(tmp_path, project.project_id, PROFILE_ID)
    return title, draft


class RecordingProviderWrapper:
    """Offline wrapper with a selected profile and a deliberately stale local default."""
    provider_name = "openai-compatible"
    model_name = "gpt-5"
    profile_id = PROFILE_ID
    config_hash = "safe-test-config-hash"
    default_max_output_tokens = 1200

    def __init__(self, text="developmental findings"):
        self.text = text
        self.calls = 0
        self.request = None

    async def generate(self, request):
        self.calls += 1
        self.request = request
        return GenerationResult(provider=self.provider_name, model=self.model_name, text=self.text,
                                usage=UsageMetadata(input_tokens=10, output_tokens=5, total_tokens=15))


@pytest.mark.parametrize("override,expected", [(None, 4000), (777, 777)])
def test_developmental_editorial_uses_profile_default_or_explicit_override(tmp_path, override, expected):
    title, draft = setup_drafting_title(tmp_path)
    provider = RecordingProviderWrapper()
    result = asyncio.run(EditorialService.developmental(
        tmp_path, title_id=title.title_id, chapter_number=1, source_asset_id=draft.asset.asset_id,
        provider=provider, max_output_tokens=override,
    ))

    assert provider.calls == 1
    assert provider.request.max_output_tokens == expected
    with session_scope(tmp_path) as session:
        event = session.scalar(select(AuditEventRow).where(
            AuditEventRow.action == "generation.job.created", AuditEventRow.entity_id == result.generation.job.job_id,
        ))
        request = json.loads(event.metadata_json)["effective_request"]
    assert request == {
        "provider_profile_id": PROFILE_ID,
        "model": "gpt-5",
        "max_output_tokens": expected,
        "prompt_template_id": "editorial/developmental",
        "prompt_template_version": "1.0",
        "reasoning_effort": "low",
        "timeouts_seconds": {"connect": 60.0, "read": 180.0, "write": 60.0, "pool": 60.0},
    }
    inspected = inspect_title(tmp_path, title.title_id)
    job_view = next(job for job in inspected["jobs"] if job["job_id"] == result.generation.job.job_id)
    assert job_view["request_diagnostics"] == request


def test_developmental_empty_output_still_fails_without_finding_or_asset(tmp_path):
    title, draft = setup_drafting_title(tmp_path)
    provider = RecordingProviderWrapper(text=" \n")
    with pytest.raises(GenerationServiceError, match="empty or whitespace-only"):
        asyncio.run(EditorialService.developmental(
            tmp_path, title_id=title.title_id, chapter_number=1, source_asset_id=draft.asset.asset_id,
            provider=provider,
        ))
    assert provider.calls == 1
    with session_scope(tmp_path) as session:
        job = session.scalar(select(JobRow).where(JobRow.job_type == "generate:chapter.editorial.developmental.1"))
        assert job.status == "failed"
        assert job.result_asset_ids_json == "[]"
        assert session.scalar(select(UsageEventRow).where(UsageEventRow.job_id == job.job_id)) is not None
        assert session.scalar(select(EditorialFindingRow).where(EditorialFindingRow.pass_type == "developmental")) is None
