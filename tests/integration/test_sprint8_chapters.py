from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from kdp_pipeline.chapter import ChapterService, accept_chapter
from kdp_pipeline.chapters import chapter_status, queue_chapters, record_chapter_summary, resume_queue, stop_queue
from kdp_pipeline.context import ContextManifest
from kdp_pipeline.inspection import inspect_title
from kdp_pipeline.core.state_machine import TitleState
from kdp_pipeline.models.planning import PlanningArtifactKind
from kdp_pipeline.planning import PlanningService, accept_planning_artifact
from kdp_pipeline.providers import FakeProvider
from kdp_pipeline.providers.contracts import GenerationResult
from kdp_pipeline.storage.service import (advance_to_drafting, advance_to_planned,
                                          advance_to_validated, create_project, create_title)


class CapturingProvider:
    provider_name = "fixture"
    model_name = "chapter-test"

    def __init__(self): self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        return GenerationResult(provider=self.provider_name, model=self.model_name,
            text=f"Draft for chapter {request.task_type}", latency_ms=0)


def setup_title(root: Path):
    shutil.copytree(Path("prompts"), root / "prompts")
    project = create_project(root, "Chapter orchestration")
    title = create_title(root, project.project_id, "Bounded chapter test")
    fake = FakeProvider()
    for kind in (PlanningArtifactKind.POSITIONING, PlanningArtifactKind.BOOK_BRIEF, PlanningArtifactKind.OUTLINE):
        result = asyncio.run(PlanningService.generate(root, title_id=title.title_id, artifact_kind=kind,
            context_manifest=ContextManifest(title_id=title.title_id, task_type=f"planning.{kind.value}", inputs=[]), provider=fake))
        accept_planning_artifact(root, result.asset.asset_id, reviewer="human")
    for number in (1, 2):
        result = asyncio.run(PlanningService.generate(root, title_id=title.title_id,
            artifact_kind=PlanningArtifactKind.CHAPTER_CARD,
            context_manifest=ContextManifest(title_id=title.title_id, task_type="planning.chapter_card", inputs=[]),
            provider=fake, chapter_number=number))
        accept_planning_artifact(root, result.asset.asset_id, reviewer="human", chapter_number=number)
    advance_to_validated(root, title.title_id); advance_to_planned(root, title.title_id); advance_to_drafting(root, title.title_id)
    return project, title


def test_bounded_queue_pause_resume_and_missing_card_status(tmp_path: Path):
    _, title = setup_title(tmp_path)
    queued = queue_chapters(tmp_path, title.title_id, 1, 3)
    assert [row.status for row in queued] == ["queued", "queued", "waiting_for_card"]
    report = chapter_status(tmp_path, title.title_id)
    assert report["missing_cards"] == [3]
    assert stop_queue(tmp_path, title.title_id) == 2
    assert resume_queue(tmp_path, title.title_id) == 2
    with pytest.raises(ValueError, match="bounded"):
        queue_chapters(tmp_path, title.title_id, 1, 11)


def test_prior_summary_is_hashed_context_for_one_chapter_at_a_time(tmp_path: Path):
    _, title = setup_title(tmp_path)
    queue_chapters(tmp_path, title.title_id, 1, 2)
    provider = CapturingProvider()
    first = asyncio.run(ChapterService.draft(tmp_path, title_id=title.title_id, chapter_number=1, provider=provider))
    accepted = accept_chapter(tmp_path, first.asset.asset_id, chapter_number=1, reviewer="human")
    inspected = inspect_title(tmp_path, title.title_id)
    chapter_two = next(item for item in inspected["chapter_workflow"]["chapters"] if item["chapter_number"] == 2)
    assert chapter_two["status"] == "awaiting_prior_summary"
    assert inspected["chapter_workflow"]["missing_prior_summary_chapters"] == [2]
    with pytest.raises(ValueError, match="requires a reviewed context summary"):
        asyncio.run(ChapterService.draft(tmp_path, title_id=title.title_id, chapter_number=2, provider=provider))
    summary = record_chapter_summary(tmp_path, title.title_id, 1, accepted.accepted_asset.asset_id,
        "Chapter 1 establishes service, stewardship, and integrity as the reader's decision filter.", "human")
    second = asyncio.run(ChapterService.draft(tmp_path, title_id=title.title_id, chapter_number=2, provider=provider))
    request = provider.requests[-1]
    assert "Chapter 1 establishes service, stewardship, and integrity" in request.rendered_prompt.rendered_text
    assert summary.asset_id in second.provenance.input_references
    assert chapter_status(tmp_path, title.title_id)["accepted_chapter_count"] == 1
