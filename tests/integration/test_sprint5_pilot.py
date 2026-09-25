import asyncio
import shutil
from pathlib import Path

import pytest
from sqlalchemy import func, select

from kdp_pipeline.chapter import ChapterService, accept_chapter
from kdp_pipeline.continuity import ContinuityService
from kdp_pipeline.editorial import EditorialService
from kdp_pipeline.inspection import doctor, inspect_title
from kdp_pipeline.context import ContextManifest
from kdp_pipeline.models.planning import PlanningArtifactKind
from kdp_pipeline.planning import PlanningService, accept_planning_artifact
from kdp_pipeline.storage.db import ApprovalRow, AssetRow, CanonProposalRow, EditorialFindingRow
from kdp_pipeline.providers import FakeProvider
from kdp_pipeline.storage.service import (
    advance_to_drafting,
    advance_to_planned,
    advance_to_validated,
    create_project,
    create_title,
    session_scope,
)


def setup_drafting_title(tmp_path: Path):
    shutil.copytree(Path("prompts"), tmp_path / "prompts")
    project = create_project(tmp_path, "Chapter Project")
    title = create_title(tmp_path, project.project_id, "Chapter Title")
    provider = FakeProvider()
    for kind, chapter_number in ((PlanningArtifactKind.POSITIONING, None), (PlanningArtifactKind.BOOK_BRIEF, None),
                                 (PlanningArtifactKind.OUTLINE, None), (PlanningArtifactKind.CHAPTER_CARD, 1)):
        result = asyncio.run(PlanningService.generate(
            tmp_path, title_id=title.title_id, artifact_kind=kind,
            context_manifest=ContextManifest(title_id=title.title_id, task_type="planning", inputs=[]),
            provider=provider, chapter_number=chapter_number,
        ))
        accept_planning_artifact(tmp_path, result.asset.asset_id, reviewer="planner", chapter_number=chapter_number)
    advance_to_validated(tmp_path, title.title_id)
    advance_to_planned(tmp_path, title.title_id)
    advance_to_drafting(tmp_path, title.title_id)
    return project, title, provider


def test_repeated_chapter_acceptance_and_analysis_are_idempotent(tmp_path: Path):
    _, title, provider = setup_drafting_title(tmp_path)
    draft = asyncio.run(ChapterService.draft(tmp_path, title_id=title.title_id, chapter_number=1, provider=provider))
    first_continuity = asyncio.run(ContinuityService.analyze(
        tmp_path, title_id=title.title_id, chapter_number=1, source_asset_id=draft.asset.asset_id, provider=provider,
    ))
    second_continuity = asyncio.run(ContinuityService.analyze(
        tmp_path, title_id=title.title_id, chapter_number=1, source_asset_id=draft.asset.asset_id, provider=provider,
    ))
    first_editorial = asyncio.run(EditorialService.developmental(
        tmp_path, title_id=title.title_id, chapter_number=1, source_asset_id=draft.asset.asset_id, provider=provider,
    ))
    second_editorial = asyncio.run(EditorialService.developmental(
        tmp_path, title_id=title.title_id, chapter_number=1, source_asset_id=draft.asset.asset_id, provider=provider,
    ))
    assert first_continuity.finding.finding_id == second_continuity.finding.finding_id
    assert first_continuity.proposal.proposal_id == second_continuity.proposal.proposal_id
    assert first_editorial.finding.finding_id == second_editorial.finding.finding_id

    first = accept_chapter(tmp_path, draft.asset.asset_id, chapter_number=1, reviewer="pilot")
    second = accept_chapter(tmp_path, draft.asset.asset_id, chapter_number=1, reviewer="pilot")
    assert first.accepted_asset.asset_id == second.accepted_asset.asset_id
    assert first.approval.approval_id == second.approval.approval_id
    with session_scope(tmp_path) as session:
        assert session.scalar(select(func.count(AssetRow.asset_id)).where(
            AssetRow.source_ref == draft.asset.asset_id, AssetRow.asset_type == "chapter.accepted"
        )) == 1
        assert session.scalar(select(func.count(ApprovalRow.approval_id)).where(ApprovalRow.asset_id == first.accepted_asset.asset_id)) == 1
        assert session.scalar(select(func.count(EditorialFindingRow.finding_id)).where(EditorialFindingRow.pass_type == "continuity")) == 1
        assert session.scalar(select(func.count(CanonProposalRow.proposal_id))) == 1


def test_repeated_planning_acceptance_is_idempotent(tmp_path: Path):
    shutil.copytree(Path("prompts"), tmp_path / "prompts")
    project = create_project(tmp_path, "Planning")
    title = create_title(tmp_path, project.project_id, "Planning Title")
    result = asyncio.run(PlanningService.generate(
        tmp_path, title_id=title.title_id, artifact_kind=PlanningArtifactKind.POSITIONING,
        context_manifest=ContextManifest(title_id=title.title_id, task_type="planning", inputs=[]), provider=FakeProvider(),
    ))
    first = accept_planning_artifact(tmp_path, result.asset.asset_id, reviewer="pilot")
    second = accept_planning_artifact(tmp_path, result.asset.asset_id, reviewer="pilot")
    assert first.accepted_asset.asset_id == second.accepted_asset.asset_id
    with session_scope(tmp_path) as session:
        assert session.scalar(select(func.count(AssetRow.asset_id)).where(AssetRow.source_ref == result.asset.asset_id)) == 1
        assert session.scalar(select(func.count(ApprovalRow.approval_id)).where(ApprovalRow.asset_id == first.accepted_asset.asset_id)) == 1


def test_conflicting_accepted_content_is_not_overwritten(tmp_path: Path):
    _, title, provider = setup_drafting_title(tmp_path)
    draft = asyncio.run(ChapterService.draft(tmp_path, title_id=title.title_id, chapter_number=1, provider=provider))
    accepted = accept_chapter(tmp_path, draft.asset.asset_id, chapter_number=1, reviewer="pilot")
    accepted.destination_path.write_text("human conflict\n", encoding="utf-8")
    with pytest.raises(ValueError, match="conflicting"):
        accept_chapter(tmp_path, draft.asset.asset_id, chapter_number=1, reviewer="pilot")
    assert accepted.destination_path.read_text(encoding="utf-8") == "human conflict\n"


def test_inspection_and_doctor_are_read_only(tmp_path: Path):
    project, title, _ = setup_drafting_title(tmp_path)
    db_path = tmp_path / ".kdp" / "state.db"
    before_bytes = db_path.read_bytes()
    report = inspect_title(tmp_path, title.title_id)
    checks = doctor(tmp_path)
    assert report["title"]["title_id"] == title.title_id
    assert "planning" in report and "chapter_lifecycle" in report
    assert any(check["check"] == f"workspace:{title.title_id}" and check["status"] == "OK" for check in checks)
    assert db_path.read_bytes() == before_bytes


def test_doctor_missing_database_does_not_create_state(tmp_path: Path):
    checks = doctor(tmp_path)
    assert any(check["status"] == "FAIL" and check["check"] == "sqlite" for check in checks)
    assert not (tmp_path / ".kdp").exists()
