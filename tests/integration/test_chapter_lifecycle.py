import asyncio
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from kdp_pipeline.chapter import ChapterService, accept_chapter
from kdp_pipeline.continuity import ContinuityService, approve_canon_proposal
from kdp_pipeline.core.state_machine import TitleState
from kdp_pipeline.editorial import EditorialService
from kdp_pipeline.models.planning import PlanningArtifactKind
from kdp_pipeline.planning import PlanningService, accept_planning_artifact
from kdp_pipeline.providers import FakeProvider
from kdp_pipeline.storage.db import AuditEventRow, AssetRow, CanonProposalRow, EditorialFindingRow, ProvenanceRow
from kdp_pipeline.storage.service import (
    advance_to_drafting,
    advance_to_planned,
    advance_to_validated,
    create_project,
    create_title,
    get_title,
    session_scope,
)
from kdp_pipeline.context import ContextManifest


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


def test_draft_analysis_revision_and_acceptance_preserve_lineage(tmp_path: Path):
    project, title, provider = setup_drafting_title(tmp_path)
    draft = asyncio.run(ChapterService.draft(tmp_path, title_id=title.title_id, chapter_number=1, provider=provider))
    assert draft.asset.asset_type == "chapter.draft"
    assert draft.asset.approval_status == "experimental"
    assert draft.output_path.parent.name == "experimental"

    continuity = asyncio.run(ContinuityService.analyze(
        tmp_path, title_id=title.title_id, chapter_number=1, source_asset_id=draft.asset.asset_id, provider=provider,
    ))
    editorial = asyncio.run(EditorialService.developmental(
        tmp_path, title_id=title.title_id, chapter_number=1, source_asset_id=draft.asset.asset_id, provider=provider,
    ))
    assert continuity.finding.pass_type == "continuity"
    assert editorial.finding.pass_type == "developmental"
    assert Path(continuity.finding.snapshot_path).is_file()
    assert Path(editorial.finding.snapshot_path).is_file()
    assert Path(continuity.proposal.snapshot_path).is_file()
    assert continuity.proposal.status == "proposed"

    revision = asyncio.run(ChapterService.revise(
        tmp_path, title_id=title.title_id, chapter_number=1, source_asset_id=draft.asset.asset_id,
        finding_ids=[continuity.finding.finding_id, editorial.finding.finding_id], provider=provider,
    ))
    assert revision.asset.asset_type == "chapter.revision"
    assert revision.asset.source_ref == draft.asset.asset_id
    assert revision.asset.asset_id != draft.asset.asset_id
    assert revision.output_path != draft.output_path

    accepted = accept_chapter(
        tmp_path, revision.asset.asset_id, chapter_number=1, reviewer="human", 
        finding_ids=[continuity.finding.finding_id, editorial.finding.finding_id],
        proposal_ids=[continuity.proposal.proposal_id],
    )
    expected = tmp_path / "projects" / project.project_id / "titles" / title.title_id / "05_drafts" / "accepted" / "chapter-001.md"
    assert accepted.destination_path == expected
    assert expected.is_file()
    assert accepted.accepted_asset.approval_status == "accepted"
    assert accepted.accepted_asset.source_ref == revision.asset.asset_id
    assert accepted.accepted_asset.sha256 == hashlib.sha256(expected.read_bytes()).hexdigest()
    assert get_title(tmp_path, title.title_id).status == TitleState.DRAFTING.value

    with session_scope(tmp_path) as session:
        assert session.scalar(select(ProvenanceRow).where(ProvenanceRow.asset_id == accepted.accepted_asset.asset_id))
        event = session.scalar(select(AuditEventRow).where(
            AuditEventRow.entity_id == accepted.accepted_asset.asset_id,
            AuditEventRow.action == "chapter.accepted",
        ))
        assert json.loads(event.metadata_json)["source_asset_id"] == revision.asset.asset_id

    approved = approve_canon_proposal(tmp_path, continuity.proposal.proposal_id, reviewer="canon-reviewer", decision="accepted")
    assert approved.status == "accepted"
    assert not (tmp_path / "projects" / project.project_id / "titles" / title.title_id / "06_canon" / "entities.json").read_text().find("review") >= 0


def test_drafting_requires_explicit_state_transition(tmp_path: Path):
    shutil.copytree(Path("prompts"), tmp_path / "prompts")
    project = create_project(tmp_path, "Chapter Project")
    title = create_title(tmp_path, project.project_id, "Chapter Title")
    with pytest.raises(ValueError, match="explicit PLANNED to DRAFTING"):
        asyncio.run(ChapterService.draft(tmp_path, title_id=title.title_id, chapter_number=1, provider=FakeProvider()))
