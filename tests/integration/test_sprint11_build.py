from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from kdp_pipeline.build import accept_matter, build_manuscript, register_matter
from kdp_pipeline.chapter import ChapterService, accept_chapter
from kdp_pipeline.chapters import record_chapter_summary
from kdp_pipeline.context import ContextManifest
from kdp_pipeline.inspection import inspect_title
from kdp_pipeline.models.planning import PlanningArtifactKind
from kdp_pipeline.planning import PlanningService, accept_planning_artifact
from kdp_pipeline.providers import FakeProvider
from kdp_pipeline.providers.contracts import GenerationResult
from kdp_pipeline.storage.files import sha256_file
from kdp_pipeline.storage.service import (advance_to_drafting, advance_to_planned,
    advance_to_validated, create_project, create_title)


class BookFixtureProvider(FakeProvider):
    def __init__(self, *, include_placeholder: bool = True):
        super().__init__()
        self.include_placeholder = include_placeholder

    async def generate(self, request):
        if request.task_type == "chapter.draft.1":
            text = "# First Chapter\n\nOpening for the first chapter.\n"
        elif request.task_type == "chapter.draft.2":
            placeholder = "[SCRIPTURE NEEDED]\n" if self.include_placeholder else ""
            text = f"# Second Chapter\n\n{placeholder}Second chapter text.\n"
        else:
            return await super().generate(request)
        return GenerationResult(provider=self.provider_name, model=self.model_name, text=text, latency_ms=0)


def _setup_book(root: Path, *, accept_chapters: bool = True, include_placeholder: bool = True):
    shutil.copytree(Path("prompts"), root / "prompts")
    project = create_project(root, "Sprint 11 build")
    title = create_title(root, project.project_id, "Book build fixture")
    provider = BookFixtureProvider(include_placeholder=include_placeholder)
    for kind, number in ((PlanningArtifactKind.POSITIONING, None),
        (PlanningArtifactKind.BOOK_BRIEF, None), (PlanningArtifactKind.OUTLINE, None),
        (PlanningArtifactKind.CHAPTER_CARD, 1), (PlanningArtifactKind.CHAPTER_CARD, 2)):
        planned = asyncio.run(PlanningService.generate(root, title_id=title.title_id,
            artifact_kind=kind, context_manifest=ContextManifest(title_id=title.title_id,
            task_type=f"planning.{kind.value}", inputs=[]), provider=provider, chapter_number=number))
        accept_planning_artifact(root, planned.asset.asset_id, reviewer="planner", chapter_number=number)
    advance_to_validated(root, title.title_id)
    advance_to_planned(root, title.title_id)
    advance_to_drafting(root, title.title_id)
    accepted = []
    if not accept_chapters:
        return title, accepted
    for number in (1, 2):
        draft = asyncio.run(ChapterService.draft(root, title_id=title.title_id,
            chapter_number=number, provider=provider))
        accepted_result = accept_chapter(root, draft.asset.asset_id,
            chapter_number=number, reviewer="editor")
        accepted.append(accepted_result.accepted_asset)
        if number == 1:
            record_chapter_summary(root, title.title_id, 1, accepted_result.accepted_asset.asset_id,
                "First chapter introduces the reader and establishes the book's purpose.", "editor")
    return title, accepted


def test_markdown_build_assembles_accepted_chapters_matter_and_toc_and_exposes_blockers(tmp_path):
    title, chapters = _setup_book(tmp_path)
    front_source = tmp_path / "front.md"
    front_source.write_text("## A Note to Readers\n\nWelcome.\n", encoding="utf-8")
    back_source = tmp_path / "back.md"
    back_source.write_text("## About the Author\n\nAuthor biography.\n", encoding="utf-8")
    front = register_matter(tmp_path, title_id=title.title_id, section="front",
        source_path=front_source, creator="human-author")
    back = register_matter(tmp_path, title_id=title.title_id, section="back",
        source_path=back_source, creator="human-author")
    front_accepted, _ = accept_matter(tmp_path, front.asset_id, reviewer="editor")
    back_accepted, _ = accept_matter(tmp_path, back.asset_id, reviewer="editor")

    result = build_manuscript(tmp_path, title_id=title.title_id, builder="operator")
    output = Path(result.asset.path).read_text(encoding="utf-8")
    assert output.index("A Note to Readers") < output.index("## Contents") < output.index("First Chapter")
    assert output.index("First Chapter") < output.index("Second Chapter") < output.index("About the Author")
    assert "[First Chapter](#chapter-001)" in output
    assert "[Second Chapter](#chapter-002)" in output
    assert "[SCRIPTURE NEEDED]" in output
    assert result.build.status == "blocked"
    assert result.manifest["release_eligible"] is False
    assert result.manifest["release_review_required"] is True
    assert any(item["type"] == "scripture_placeholder" for item in result.manifest["blockers"])
    included = {item["asset_id"] for item in result.manifest["included_assets"]}
    assert included == {chapter.asset_id for chapter in chapters} | {front_accepted.asset_id, back_accepted.asset_id}
    assert result.build.output_sha256 == sha256_file(Path(result.asset.path))
    assert result.build.manifest_sha256 == sha256_file(Path(result.build.manifest_path))
    report = inspect_title(tmp_path, title.title_id)
    assert report["builds"]["records"][0]["status"] == "blocked"
    assert report["builds"]["records"][0]["output_exists"] is True
    assert report["inconsistencies"] == []


def test_build_requires_an_accepted_chapter(tmp_path):
    title, _ = _setup_book(tmp_path, accept_chapters=False)
    with pytest.raises(ValueError, match="without accepted chapter assets"):
        build_manuscript(tmp_path, title_id=title.title_id)
