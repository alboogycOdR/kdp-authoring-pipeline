from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from kdp_pipeline.build import build_manuscript
from kdp_pipeline.chapter import ChapterService, accept_chapter
from kdp_pipeline.chapters import record_chapter_summary
from kdp_pipeline.context import ContextManifest
from kdp_pipeline.inspection import inspect_title
from kdp_pipeline.models.planning import PlanningArtifactKind
from kdp_pipeline.planning import PlanningService, accept_planning_artifact
from kdp_pipeline.providers import FakeProvider
from kdp_pipeline.providers.contracts import GenerationResult
from kdp_pipeline.release import (create_release_candidate, export_release_packet,
    record_candidate_check, review_release_candidate)
from kdp_pipeline.storage.db import ApprovalRow
from kdp_pipeline.storage.service import (advance_to_drafting, advance_to_planned,
    advance_to_validated, create_project, create_title, session_scope)
from kdp_pipeline.verification import scan_scripture_placeholders


class ReleaseFixtureProvider(FakeProvider):
    def __init__(self, *, include_placeholder: bool):
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


def _setup_book(root: Path, *, include_placeholder: bool):
    shutil.copytree(Path("prompts"), root / "prompts")
    project = create_project(root, "Sprint 12 release")
    title = create_title(root, project.project_id, "Release candidate fixture")
    provider = ReleaseFixtureProvider(include_placeholder=include_placeholder)
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
    for number in (1, 2):
        draft = asyncio.run(ChapterService.draft(root, title_id=title.title_id,
            chapter_number=number, provider=provider))
        result = accept_chapter(root, draft.asset.asset_id, chapter_number=number, reviewer="editor")
        accepted.append(result.accepted_asset)
        if number == 1:
            record_chapter_summary(root, title.title_id, 1, result.accepted_asset.asset_id,
                "The first chapter introduces the reader and the book's purpose.", "editor")
    return title, accepted


def _complete_review_checks(root: Path, candidate_id: str):
    for key in ("title", "subtitle", "author", "description", "keywords", "categories",
                "language", "reader_age", "metadata_policy_current"):
        record_candidate_check(root, candidate_id, domain="metadata", key=key,
            decision="complete", reviewer="reviewer", rationale="Reviewed against approved metadata.",
            evidence_reference="metadata-review-record", value="Human reviewed")
    record_candidate_check(root, candidate_id, domain="ai_disclosure", key="ai_use_disclosure",
        decision="complete", reviewer="reviewer", rationale="Disclosure reviewed against current official guidance.",
        evidence_reference="https://kdp.amazon.com/help", statement="AI was used for assisted drafting and human-reviewed.")
    for key in ("current_format_requirements", "current_content_guidelines", "metadata_requirements",
                "rights_and_territories", "ai_content_disclosure", "final_upload_settings"):
        record_candidate_check(root, candidate_id, domain="kdp", key=key,
            decision="complete", reviewer="reviewer", rationale="Checked current official KDP documentation manually.",
            evidence_reference="https://kdp.amazon.com/help")


def test_release_candidate_freezes_inputs_and_requires_human_review_before_manual_kdp_action(tmp_path):
    title, _chapters = _setup_book(tmp_path, include_placeholder=False)
    build = build_manuscript(tmp_path, title_id=title.title_id, builder="builder")
    assert build.build.status == "built"
    candidate = create_release_candidate(tmp_path, title_id=title.title_id,
        build_id=build.build.build_id, creator="release-manager")
    assert candidate.candidate_sha256
    frozen_inputs = json.loads(candidate.frozen_inputs_json)
    assert len(frozen_inputs) == 2
    assert candidate.status == "blocked"
    _complete_review_checks(tmp_path, candidate.candidate_id)

    report = inspect_title(tmp_path, title.title_id)
    inspected = report["release"]["candidates"][0]
    assert inspected["status"] == "pending_human_review"
    assert inspected["current_blockers"] == []
    approved, approval = review_release_candidate(tmp_path, candidate.candidate_id,
        decision="approve", reviewer="release-reviewer", rationale="Packet checked and approved for manual KDP action.")
    assert approved.status == "approved_for_manual_kdp_action"
    assert approval is not None and approval.scope == "release_candidate"
    assert "remain manual" in json.loads(approval.conditions_json)[0]

    packet_row, packet_asset = export_release_packet(tmp_path, candidate.candidate_id, creator="operator")
    packet = json.loads(Path(packet_asset.path).read_text(encoding="utf-8"))
    assert packet["approval_id"] == approval.approval_id
    assert packet["final_kdp_action_manual"] is True
    assert packet["unresolved_blockers"] == []
    assert packet["kdp_human_checklist"]["source_policy"].startswith("Verify current requirements")
    assert packet_row.sha256 == packet_asset.sha256
    final_inspection = inspect_title(tmp_path, title.title_id)
    assert final_inspection["release"]["packets"][0]["packet_id"] == packet_row.packet_id
    assert final_inspection["inconsistencies"] == []


def test_unresolved_scripture_and_changed_verification_state_block_release_approval(tmp_path):
    title, _chapters = _setup_book(tmp_path, include_placeholder=True)
    build = build_manuscript(tmp_path, title_id=title.title_id, builder="builder")
    candidate = create_release_candidate(tmp_path, title_id=title.title_id,
        build_id=build.build.build_id, creator="release-manager")
    scan_scripture_placeholders(tmp_path, title.title_id)
    _complete_review_checks(tmp_path, candidate.candidate_id)
    approved, approval = review_release_candidate(tmp_path, candidate.candidate_id,
        decision="approve", reviewer="release-reviewer", rationale="Attempt should remain blocked.")
    assert approval is None
    assert approved.status == "blocked"
    report = inspect_title(tmp_path, title.title_id)
    types = {item["type"] for item in report["release"]["candidates"][0]["current_blockers"]}
    assert "scripture_placeholder" in types
    assert "verification_state_changed" in types
    with session_scope(tmp_path) as session:
        assert session.query(ApprovalRow).filter_by(scope="release_candidate", decision="accepted").count() == 0
