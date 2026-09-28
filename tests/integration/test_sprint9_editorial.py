from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from kdp_pipeline.chapter import ChapterService
from kdp_pipeline.context import ContextManifest
from kdp_pipeline.editorial import StructuredEditorialService, create_revision_recommendation
from kdp_pipeline.inspection import inspect_title
from kdp_pipeline.models.planning import PlanningArtifactKind
from kdp_pipeline.planning import PlanningService, accept_planning_artifact
from kdp_pipeline.providers.contracts import GenerationResult
from kdp_pipeline.storage.db import AuditEventRow, EditorialFindingRow, JobRow, RevisionRecommendationRow
from kdp_pipeline.storage.files import sha256_file
from kdp_pipeline.storage.service import (advance_to_drafting, advance_to_planned,
    advance_to_validated, create_project, create_title, session_scope)


class EditorialFixtureProvider:
    provider_name = "fixture"
    model_name = "editorial-test"

    def __init__(self, response: str):
        self.response = response
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        response = self.response
        if request.task_type.startswith("planning."):
            kind = request.task_type.removeprefix("planning.").split(".", 1)[0].replace("_", " ").upper()
            response = f"ACCEPTED {kind} CONTEXT for sprint nine."
        return GenerationResult(provider=self.provider_name, model=self.model_name,
                                text=response, latency_ms=0)


def _valid_response(*, findings=None):
    return json.dumps({"status": "review", "supplied_context_confirmed": True,
        "summary": "The chapter is aligned overall, with one focused improvement.",
        "findings": findings if findings is not None else [{
            "severity": "minor", "location": "opening", "issue": "Clarify the opening transition.",
            "evidence": "The opening moves quickly from situation to reflection.",
            "recommended_action": "Add a brief transition.",
        }], "required_followups": []})


def _setup_title(root: Path):
    shutil.copytree(Path("prompts"), root / "prompts")
    project = create_project(root, "Sprint 9 editorial")
    title = create_title(root, project.project_id, "Structured editorial fixture")
    planner = EditorialFixtureProvider("Fixture planning content")
    for kind, number in ((PlanningArtifactKind.POSITIONING, None),
                         (PlanningArtifactKind.BOOK_BRIEF, None),
                         (PlanningArtifactKind.OUTLINE, None),
                         (PlanningArtifactKind.CHAPTER_CARD, 1)):
        planned = asyncio.run(PlanningService.generate(root, title_id=title.title_id,
            artifact_kind=kind, context_manifest=ContextManifest(title_id=title.title_id,
            task_type=f"planning.{kind.value}", inputs=[]), provider=planner, chapter_number=number))
        accept_planning_artifact(root, planned.asset.asset_id, reviewer="test", chapter_number=number)
    advance_to_validated(root, title.title_id)
    advance_to_planned(root, title.title_id)
    advance_to_drafting(root, title.title_id)
    draft_provider = EditorialFixtureProvider("Fixture draft chapter with a clear opening, reflection, practice, and prayer.")
    draft = asyncio.run(ChapterService.draft(root, title_id=title.title_id, chapter_number=1,
                                               provider=draft_provider))
    return title, draft, draft_provider


def test_structured_editorial_sends_chapter_and_accepted_context_and_creates_findings(tmp_path):
    title, draft, _ = _setup_title(tmp_path)
    provider = EditorialFixtureProvider(_valid_response())
    result = asyncio.run(StructuredEditorialService.analyze(tmp_path, title_id=title.title_id,
        chapter_number=1, source_asset_id=draft.asset.asset_id, pass_type="voice", provider=provider))

    assert len(provider.requests) == 1
    prompt = provider.requests[0].rendered_prompt.rendered_text
    assert "Fixture draft chapter with a clear opening" in prompt
    for kind in ("POSITIONING", "BOOK BRIEF", "OUTLINE", "CHAPTER CARD"):
        assert f"ACCEPTED {kind} CONTEXT" in prompt
    assert "supplied_context_confirmed" in prompt
    assert len(result.findings) == 1
    assert result.findings[0].pass_type == "voice"
    assert result.output.status == "review"


def test_missing_context_response_is_rejected_without_findings_or_recommendations(tmp_path):
    title, draft, _ = _setup_title(tmp_path)
    provider = EditorialFixtureProvider("Please provide the chapter text and accepted context.")
    with pytest.raises(ValueError, match="required context is missing"):
        asyncio.run(StructuredEditorialService.analyze(tmp_path, title_id=title.title_id,
            chapter_number=1, source_asset_id=draft.asset.asset_id, pass_type="line", provider=provider))

    with session_scope(tmp_path) as session:
        job = session.scalar(select(JobRow).where(JobRow.job_type == "generate:chapter.editorial.line.1"))
        assert job is not None and job.status == "failed"
        assert session.scalar(select(EditorialFindingRow).where(EditorialFindingRow.pass_type == "line")) is None
        assert session.scalar(select(RevisionRecommendationRow)) is None
        event = session.scalar(select(AuditEventRow).where(AuditEventRow.action == "editorial.output.rejected"))
        assert event is not None
        assert json.loads(event.metadata_json)["findings_created"] == 0
    inspected = inspect_title(tmp_path, title.title_id)
    assert inspected["editorial"]["rejected_outputs"][0]["job_id"] == job.job_id


def test_revision_recommendation_is_human_owned_and_does_not_change_source(tmp_path):
    title, draft, _ = _setup_title(tmp_path)
    provider = EditorialFixtureProvider(_valid_response())
    result = asyncio.run(StructuredEditorialService.analyze(tmp_path, title_id=title.title_id,
        chapter_number=1, source_asset_id=draft.asset.asset_id, pass_type="copy", provider=provider))
    source_hash = sha256_file(Path(draft.asset.path))
    recommendation = create_revision_recommendation(tmp_path, title_id=title.title_id,
        chapter_number=1, source_asset_id=draft.asset.asset_id,
        finding_ids=[result.findings[0].finding_id], owner="human-editor")

    assert recommendation.owner == "human-editor"
    assert recommendation.status == "open"
    assert sha256_file(Path(draft.asset.path)) == source_hash
    inspected = inspect_title(tmp_path, title.title_id)
    assert inspected["editorial"]["revision_recommendations"][0]["recommendation_id"] == recommendation.recommendation_id
    assert any(event["action"] == "editorial.revision_recommendation.created" for event in inspected["audit"])
