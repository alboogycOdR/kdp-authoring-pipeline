from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from kdp_pipeline.build import build_manuscript
from kdp_pipeline.chapter import ChapterService, accept_chapter
from kdp_pipeline.context import ContextManifest
from kdp_pipeline.core.state_machine import TitleState
from kdp_pipeline.models.planning import PlanningArtifactKind
from kdp_pipeline.planning import PlanningService, accept_planning_artifact
from kdp_pipeline.providers import FakeProvider
from kdp_pipeline.providers.contracts import GenerationResult
from kdp_pipeline.release.service import (
    KDP_CHECKS,
    METADATA_CHECKS,
    create_release_candidate,
    record_candidate_check,
    review_release_candidate,
)
from kdp_pipeline.storage.db import AssetRow, AuditEventRow
from kdp_pipeline.storage.service import (
    advance_to_drafting,
    advance_to_planned,
    advance_to_validated,
    create_project,
    create_title,
    session_scope,
    transition_title,
)
from kdp_pipeline.verification import scan_scripture_placeholders


class _ChapterTextProvider(FakeProvider):
    def __init__(self, chapter_text: str):
        super().__init__()
        self.chapter_text = chapter_text

    async def generate(self, request):
        if request.task_type == "chapter.draft.1":
            return GenerationResult(provider=self.provider_name, model=self.model_name,
                text=self.chapter_text, latency_ms=0)
        return await super().generate(request)


def _accepted_chapter(root: Path, chapter_text: str):
    shutil.copytree(Path("prompts"), root / "prompts")
    project = create_project(root, "G2 workflow tests")
    title = create_title(root, project.project_id, "Workflow gates fixture")
    provider = _ChapterTextProvider(chapter_text)
    for kind, number in ((PlanningArtifactKind.POSITIONING, None),
        (PlanningArtifactKind.BOOK_BRIEF, None), (PlanningArtifactKind.OUTLINE, None),
        (PlanningArtifactKind.CHAPTER_CARD, 1)):
        result = asyncio.run(PlanningService.generate(root, title_id=title.title_id,
            artifact_kind=kind, context_manifest=ContextManifest(title_id=title.title_id,
            task_type=f"planning.{kind.value}", inputs=[]), provider=provider, chapter_number=number))
        accept_planning_artifact(root, result.asset.asset_id, reviewer="planner", chapter_number=number)
    advance_to_validated(root, title.title_id)
    advance_to_planned(root, title.title_id)
    advance_to_drafting(root, title.title_id)
    draft = asyncio.run(ChapterService.draft(root, title_id=title.title_id,
        chapter_number=1, provider=provider))
    accepted = accept_chapter(root, draft.asset.asset_id, chapter_number=1, reviewer="editor")
    return title, accepted.accepted_asset


def test_scripture_variants_are_shared_by_build_and_verification_scan(tmp_path: Path):
    variants = "[ SCRIPTURE NEEDED ]\n【SCRIPTURE NEEDED】\n［SCRIPTURE NEEDED］\n(SCRIPTURE\u00a0NEEDED)\n"
    title, _accepted = _accepted_chapter(tmp_path, f"# Chapter One\n\n{variants}")

    build = build_manuscript(tmp_path, title_id=title.title_id, builder="builder")
    found = scan_scripture_placeholders(tmp_path, title.title_id)

    assert build.build.status == "blocked"
    assert sum(item["type"] == "scripture_placeholder" for item in build.manifest["blockers"]) == 4
    assert found["created_count"] == 4
    assert not any(item["type"] == "unfinished_text" for item in build.manifest["blockers"])


def test_unfinished_text_markers_block_build(tmp_path: Path):
    title, _accepted = _accepted_chapter(tmp_path,
        "# Chapter One\n\nTODO: finish this.\nTBD\n[TK]\nlorem ipsum\n")
    result = build_manuscript(tmp_path, title_id=title.title_id, builder="builder")

    assert result.build.status == "blocked"
    assert sum(item["type"] == "unfinished_text" for item in result.manifest["blockers"]) == 4


def test_chapter_acceptance_requires_drafting_state_and_matching_filename_number(tmp_path: Path):
    shutil.copytree(Path("prompts"), tmp_path / "prompts")
    project = create_project(tmp_path, "G2 acceptance test")
    title = create_title(tmp_path, project.project_id, "Acceptance fixture")
    provider = _ChapterTextProvider("# Chapter One\n\nText.\n")
    for kind, number in ((PlanningArtifactKind.POSITIONING, None),
        (PlanningArtifactKind.BOOK_BRIEF, None), (PlanningArtifactKind.OUTLINE, None),
        (PlanningArtifactKind.CHAPTER_CARD, 1)):
        result = asyncio.run(PlanningService.generate(tmp_path, title_id=title.title_id,
            artifact_kind=kind, context_manifest=ContextManifest(title_id=title.title_id,
            task_type=f"planning.{kind.value}", inputs=[]), provider=provider, chapter_number=number))
        accept_planning_artifact(tmp_path, result.asset.asset_id, reviewer="planner", chapter_number=number)
    advance_to_validated(tmp_path, title.title_id)
    advance_to_planned(tmp_path, title.title_id)
    advance_to_drafting(tmp_path, title.title_id)
    draft = asyncio.run(ChapterService.draft(tmp_path, title_id=title.title_id,
        chapter_number=1, provider=provider))

    with pytest.raises(ValueError, match="Chapter number does not match"):
        accept_chapter(tmp_path, draft.asset.asset_id, chapter_number=2, reviewer="editor")

    transition_title(tmp_path, title.title_id, TitleState.POLICY_HOLD, actor_id="operator")
    with pytest.raises(ValueError, match="requires the title to be in DRAFTING"):
        accept_chapter(tmp_path, draft.asset.asset_id, chapter_number=1, reviewer="editor")


def test_create_snapshot_failure_keeps_append_only_audit_and_records_compensation(tmp_path: Path, monkeypatch):
    def fail_snapshot(*_args, **_kwargs):
        raise OSError("simulated snapshot write failure")

    monkeypatch.setattr("kdp_pipeline.storage.service.write_json", fail_snapshot)
    with pytest.raises(OSError, match="simulated snapshot write failure"):
        create_project(tmp_path, "Compensation fixture", actor_id="operator")

    with session_scope(tmp_path) as session:
        events = list(session.scalars(select(AuditEventRow).where(
            AuditEventRow.action.in_(["project.create", "project.create.rolled_back"]))))
        assert {event.action for event in events} == {"project.create", "project.create.rolled_back"}
        assert session.scalars(select(AssetRow)).all() == []
        assert len(events) == 2
        assert json.loads(next(event.metadata_json for event in events
                               if event.action == "project.create.rolled_back"))["reason"] == "snapshot write failed"


def test_release_state_edges_accept_only_complete_current_evidence(tmp_path: Path):
    title, _accepted = _accepted_chapter(tmp_path, "# Chapter One\n\nComplete text.\n")
    build = build_manuscript(tmp_path, title_id=title.title_id, builder="builder")
    assert build.build.status == "built"
    candidate = create_release_candidate(tmp_path, title_id=title.title_id,
        build_id=build.build.build_id, creator="release-creator")
    for key in METADATA_CHECKS:
        record_candidate_check(tmp_path, candidate.candidate_id, domain="metadata", key=key,
            decision="complete", reviewer="checklist-reviewer", rationale="Reviewed.",
            evidence_reference="metadata-review")
    record_candidate_check(tmp_path, candidate.candidate_id, domain="ai_disclosure", key="ai_use_disclosure",
        decision="complete", reviewer="checklist-reviewer", rationale="Reviewed.",
        evidence_reference="ai-disclosure-review", statement="Human-reviewed disclosure.")
    for key in KDP_CHECKS:
        record_candidate_check(tmp_path, candidate.candidate_id, domain="kdp", key=key,
            decision="complete", reviewer="checklist-reviewer", rationale="Reviewed.",
            evidence_reference="kdp-review")

    from kdp_pipeline.storage.service import transition_title
    transition_title(tmp_path, title.title_id, TitleState.EDITING, actor_id="editor")
    transition_title(tmp_path, title.title_id, TitleState.ASSET_READY, actor_id="editor")
    transition_title(tmp_path, title.title_id, TitleState.PREFLIGHT_PASSED, actor_id="reviewer")
    transition_title(tmp_path, title.title_id, TitleState.HUMAN_RELEASE_REVIEW, actor_id="reviewer")
    approved, approval = review_release_candidate(tmp_path, candidate.candidate_id,
        decision="approve", reviewer="independent-approver", rationale="Evidence reviewed.")
    assert approved.status == "approved_for_manual_kdp_action"
    assert approval is not None
    transition_title(tmp_path, title.title_id, TitleState.KDP_DRAFT_READY, actor_id="independent-approver")


def test_title_snapshot_failure_keeps_creation_event_and_records_compensation(tmp_path: Path, monkeypatch):
    project = create_project(tmp_path, "Title compensation parent")

    def fail_snapshot(*_args, **_kwargs):
        raise OSError("simulated snapshot write failure")

    monkeypatch.setattr("kdp_pipeline.storage.service.write_json", fail_snapshot)
    with pytest.raises(OSError, match="simulated snapshot write failure"):
        create_title(tmp_path, project.project_id, "Compensation fixture", actor_id="operator")

    with session_scope(tmp_path) as session:
        events = list(session.scalars(select(AuditEventRow).where(
            AuditEventRow.action.in_(["title.create", "title.create.rolled_back"]))))
        assert {event.action for event in events} == {"title.create", "title.create.rolled_back"}
        assert len(events) == 2
