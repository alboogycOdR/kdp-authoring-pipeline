import asyncio
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from kdp_pipeline.context import ContextManifest
from kdp_pipeline.core.state_machine import TitleState
from kdp_pipeline.models.planning import PlanningArtifactKind
from kdp_pipeline.planning import PlanningService, accept_planning_artifact, planning_requirements_met
from kdp_pipeline.providers import FakeProvider
from kdp_pipeline.storage.db import ApprovalRow, AssetRow, ProvenanceRow
from kdp_pipeline.storage.service import (
    advance_to_planned,
    advance_to_validated,
    create_project,
    create_title,
    get_title,
    session_scope,
    transition_title,
)


def _manifest(title_id: str) -> ContextManifest:
    return ContextManifest(title_id=title_id, task_type="planning", inputs=[])


def _setup(tmp_path: Path):
    shutil.copytree(Path("prompts"), tmp_path / "prompts")
    project = create_project(tmp_path, "Planning")
    title = create_title(tmp_path, project.project_id, "Planning Title")
    return project, title


def test_planning_generation_acceptance_and_explicit_planned_transition(tmp_path: Path):
    project, title = _setup(tmp_path)
    provider = FakeProvider()
    results = []
    for kind, chapter_number in (
        (PlanningArtifactKind.POSITIONING, None),
        (PlanningArtifactKind.BOOK_BRIEF, None),
        (PlanningArtifactKind.OUTLINE, None),
        (PlanningArtifactKind.CHAPTER_CARD, 1),
    ):
        results.append(asyncio.run(PlanningService.generate(
            tmp_path,
            title_id=title.title_id,
            artifact_kind=kind,
            context_manifest=_manifest(title.title_id),
            provider=provider,
            chapter_number=chapter_number,
        )))

    assert not planning_requirements_met(tmp_path, title.title_id)
    with pytest.raises(ValueError, match="required accepted planning"):
        transition_title(tmp_path, title.title_id, TitleState.VALIDATED)
        advance_to_planned(tmp_path, title.title_id)

    accepted = []
    for result, chapter_number in zip(results, (None, None, None, 1)):
        accepted.append(accept_planning_artifact(
            tmp_path, result.asset.asset_id, reviewer="reviewer-1", chapter_number=chapter_number,
        ))

    assert planning_requirements_met(tmp_path, title.title_id)
    assert title.status == TitleState.IDEA.value
    with session_scope(tmp_path) as session:
        for item in accepted:
            assert Path(item.source_asset.path).is_file()
            assert Path(item.destination_path).is_file()
            assert item.accepted_asset.sha256 == item.approval.candidate_hash
            assert item.accepted_asset.source_ref == item.source_asset.asset_id
            assert session.scalar(select(ApprovalRow).where(ApprovalRow.asset_id == item.accepted_asset.asset_id))
            assert session.scalar(select(ProvenanceRow).where(ProvenanceRow.asset_id == item.accepted_asset.asset_id))

    assert get_title(tmp_path, title.title_id).status == TitleState.VALIDATED.value
    assert advance_to_planned(tmp_path, title.title_id).status == TitleState.PLANNED.value


def test_planning_acceptance_does_not_advance_title(tmp_path: Path):
    project, title = _setup(tmp_path)
    result = asyncio.run(PlanningService.generate(
        tmp_path,
        title_id=title.title_id,
        artifact_kind=PlanningArtifactKind.POSITIONING,
        context_manifest=_manifest(title.title_id),
        provider=FakeProvider(),
    ))
    accept_planning_artifact(tmp_path, result.asset.asset_id, reviewer="human")
    with session_scope(tmp_path) as session:
        persisted = session.get(AssetRow, result.asset.asset_id)
        assert persisted.approval_status == "experimental"
    assert title.status == TitleState.IDEA.value
