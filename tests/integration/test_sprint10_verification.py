from __future__ import annotations

import asyncio
import sqlite3
import shutil
from pathlib import Path

import pytest

from kdp_pipeline.chapter import ChapterService, accept_chapter
from kdp_pipeline.context import ContextManifest
from kdp_pipeline.inspection import inspect_title
from kdp_pipeline.models.planning import PlanningArtifactKind
from kdp_pipeline.planning import PlanningService, accept_planning_artifact
from kdp_pipeline.providers import FakeProvider
from kdp_pipeline.providers.contracts import GenerationResult
from kdp_pipeline.storage.files import sha256_file
from kdp_pipeline.storage.service import (advance_to_drafting, advance_to_planned,
    advance_to_validated, create_project, create_title)
from kdp_pipeline.verification import (add_verification_flag, decide_rights_record,
    decide_verification, record_rights, scan_scripture_placeholders)


class PlaceholderProvider(FakeProvider):
    async def generate(self, request):
        if request.task_type == "chapter.draft.1":
            return GenerationResult(provider=self.provider_name, model=self.model_name,
                text="# Chapter One\n\nReflection: [SCRIPTURE NEEDED]\n\nPractice: Keep the citation open for review.\n", latency_ms=0)
        return await super().generate(request)


def _setup_accepted_chapter(root: Path):
    shutil.copytree(Path("prompts"), root / "prompts")
    project = create_project(root, "Verification workflow")
    title = create_title(root, project.project_id, "Scripture placeholder test")
    provider = PlaceholderProvider()
    for kind, chapter_number in ((PlanningArtifactKind.POSITIONING, None),
        (PlanningArtifactKind.BOOK_BRIEF, None), (PlanningArtifactKind.OUTLINE, None),
        (PlanningArtifactKind.CHAPTER_CARD, 1)):
        planned = asyncio.run(PlanningService.generate(root, title_id=title.title_id,
            artifact_kind=kind, context_manifest=ContextManifest(title_id=title.title_id,
            task_type=f"planning.{kind.value}", inputs=[]), provider=provider,
            chapter_number=chapter_number))
        accept_planning_artifact(root, planned.asset.asset_id, reviewer="planner",
                                 chapter_number=chapter_number)
    advance_to_validated(root, title.title_id)
    advance_to_planned(root, title.title_id)
    advance_to_drafting(root, title.title_id)
    draft = asyncio.run(ChapterService.draft(root, title_id=title.title_id,
        chapter_number=1, provider=provider))
    accepted = accept_chapter(root, draft.asset.asset_id, chapter_number=1, reviewer="editor")
    return title, accepted.accepted_asset


def test_scripture_placeholders_are_queued_idempotently_and_remain_release_blockers(tmp_path):
    title, accepted = _setup_accepted_chapter(tmp_path)
    original_hash = sha256_file(Path(accepted.path))
    first = scan_scripture_placeholders(tmp_path, title.title_id)
    second = scan_scripture_placeholders(tmp_path, title.title_id)

    assert first["created_count"] == 1
    assert second["created_count"] == 0
    assert second["existing_count"] == 1
    report = inspect_title(tmp_path, title.title_id)
    item = report["verification"]["items"][0]
    assert item["kind"] == "scripture"
    assert item["exact_text"] == "[SCRIPTURE NEEDED]"
    assert item["status"] == "pending"
    assert item["locator"].startswith("chapter-001:line-")
    assert any(blocker["id"] == item["verification_id"]
               for blocker in report["verification"]["release_blockers"])
    assert "[SCRIPTURE NEEDED]" in Path(accepted.path).read_text(encoding="utf-8")
    assert sha256_file(Path(accepted.path)) == original_hash


def test_scripture_decision_requires_reference_policy_and_evidence(tmp_path):
    title, _ = _setup_accepted_chapter(tmp_path)
    item_id = scan_scripture_placeholders(tmp_path, title.title_id)["created"][0]
    with pytest.raises(ValueError, match="exact reference and translation/source policy"):
        decide_verification(tmp_path, item_id, decision="verified", reviewer="reviewer",
                            rationale="Checked.", evidence_reference="https://example.test/source")

    item = decide_verification(tmp_path, item_id, decision="verified", reviewer="reviewer",
        rationale="Reference and source policy checked by a human.",
        evidence_reference="https://example.test/source", proposed_reference="Psalm 90:17",
        source_policy="Use the approved translation and verify exact wording against its licensed source.")
    report = inspect_title(tmp_path, title.title_id)
    assert item.proposed_reference == "Psalm 90:17"
    assert item.status == "verified"
    assert "[SCRIPTURE NEEDED]" == report["verification"]["items"][0]["exact_text"]
    assert report["verification"]["release_blockers"] == []


def test_source_flags_and_rights_records_are_audited_and_inspected(tmp_path):
    title, accepted = _setup_accepted_chapter(tmp_path)
    flag = add_verification_flag(tmp_path, title_id=title.title_id, kind="source_claim",
        locator="chapter-001:paragraph-2", exact_text="A factual claim needing a source.",
        reviewer="editor", asset_id=accepted.asset_id)
    rights = record_rights(tmp_path, title_id=title.title_id, asset_id=accepted.asset_id,
        material_type="font", description="Interior heading font", reviewer="editor",
        source="Font vendor page", legal_basis="Commercial license", evidence_reference="license.pdf",
        territories=["worldwide"], term="perpetual")

    with pytest.raises(ValueError, match="legal basis and evidence"):
        from kdp_pipeline.verification import decide_rights_record
        # A second record demonstrates that an unsubstantiated clearance remains blocked.
        pending = record_rights(tmp_path, title_id=title.title_id, material_type="image",
            description="Cover reference image", reviewer="editor")
        decide_rights_record(tmp_path, pending.rights_record_id, decision="cleared",
            reviewer="reviewer", rationale="Insufficient evidence")

    decided = decide_rights_record(tmp_path, rights.rights_record_id, decision="cleared",
        reviewer="reviewer", rationale="License evidence reviewed.")
    report = inspect_title(tmp_path, title.title_id)
    assert flag.verification_id in [item["verification_id"] for item in report["verification"]["items"]]
    assert decided.status == "cleared"
    assert any(blocker["id"] == flag.verification_id for blocker in report["verification"]["release_blockers"])
    assert any(event["action"] == "rights.record.decided" for event in report["audit"])


def test_inspection_remains_compatible_with_legacy_database_without_verification_tables(tmp_path):
    title, _ = _setup_accepted_chapter(tmp_path)
    database = tmp_path / ".kdp" / "state.db"
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE rights_log")
        connection.execute("DROP TABLE verification_items")
    report = inspect_title(tmp_path, title.title_id)
    assert report["verification"]["items"] == []
    assert report["verification"]["rights_records"] == []
