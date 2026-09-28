import asyncio
import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select, func

from kdp_pipeline.chapter import ChapterService
from kdp_pipeline.continuity import ContinuityOutputInvalid, ContinuityService
from kdp_pipeline.inspection import inspect_title
from kdp_pipeline.models.planning import PlanningArtifactKind
from kdp_pipeline.planning import PlanningService, accept_planning_artifact
from kdp_pipeline.providers import FakeProvider
from kdp_pipeline.providers.contracts import GenerationResult, UsageMetadata
from kdp_pipeline.storage.db import AssetRow, CanonProposalRow, EditorialFindingRow, UsageEventRow
from kdp_pipeline.storage.service import (advance_to_drafting, advance_to_planned, advance_to_validated,
                                          create_project, create_title, session_scope)


def structured_result():
    return {
        "status": "review", "supplied_context_confirmed": True,
        "alignment_with_positioning": "Reviewed positioning.", "alignment_with_book_brief": "Reviewed brief.",
        "alignment_with_outline": "Reviewed outline.", "alignment_with_chapter_card": "Reviewed card.",
        "canon_baseline_assessment": "Empty starting baseline.", "scripture_and_claims_check": "Placeholder retained.",
        "prosperity_or_outcome_promise_check": "No promise found.", "audience_consistency_check": "Audience aligns.",
        "continuity_findings": [], "canon_proposal_recommendation": "No specific proposal.", "required_followups": [],
    }


class LocalResponseProvider:
    provider_name = "local-test"
    model_name = "fixture"

    def __init__(self, text):
        self.text = text
        self.request = None

    async def generate(self, request):
        self.request = request
        return GenerationResult(provider=self.provider_name, model=self.model_name, text=self.text,
                               usage=UsageMetadata(input_tokens=15, output_tokens=20, total_tokens=35))


def ready_title(tmp_path):
    shutil.copytree(Path("prompts"), tmp_path / "prompts")
    project = create_project(tmp_path, "Sprint 6.4")
    title = create_title(tmp_path, project.project_id, "Continuity Fixture")
    for kind, number in ((PlanningArtifactKind.POSITIONING, None), (PlanningArtifactKind.BOOK_BRIEF, None),
                         (PlanningArtifactKind.OUTLINE, None), (PlanningArtifactKind.CHAPTER_CARD, 1)):
        from kdp_pipeline.context import ContextManifest
        result = asyncio.run(PlanningService.generate(tmp_path, title_id=title.title_id, artifact_kind=kind,
            context_manifest=ContextManifest(title_id=title.title_id, task_type="planning", inputs=[]),
            provider=FakeProvider(), chapter_number=number))
        accept_planning_artifact(tmp_path, result.asset.asset_id, reviewer="test", chapter_number=number)
    advance_to_validated(tmp_path, title.title_id); advance_to_planned(tmp_path, title.title_id); advance_to_drafting(tmp_path, title.title_id)
    draft = asyncio.run(ChapterService.draft(tmp_path, title_id=title.title_id, chapter_number=1, provider=FakeProvider()))
    return title, draft


def test_continuity_request_contains_manifest_sources_and_empty_baseline(tmp_path):
    title, draft = ready_title(tmp_path)
    provider = LocalResponseProvider(json.dumps(structured_result()))
    result = asyncio.run(ContinuityService.analyze(tmp_path, title_id=title.title_id, chapter_number=1,
        source_asset_id=draft.asset.asset_id, provider=provider))
    prompt = provider.request.rendered_prompt.rendered_text
    assert draft.output_path.read_text(encoding="utf-8") in prompt
    with session_scope(tmp_path) as session:
        asset_ids = result.generation.provenance.input_references
        assets = [session.get(AssetRow, asset_id) for asset_id in asset_ids]
        assert {asset.asset_type for asset in assets if asset is not None} >= {
            "chapter.draft", "planning.positioning", "planning.book-brief", "planning.outline", "planning.chapter-card",
        }
        for asset in assets:
            if asset is not None and asset.asset_type.startswith("planning."):
                assert Path(asset.path).read_text(encoding="utf-8") in prompt
                assert asset.sha256 in result.generation.provenance.input_hashes
    assert "No established canon/continuity baseline exists yet" in prompt
    assert set(result.generation.provenance.input_references) >= {draft.asset.asset_id}
    assert result.finding is not None and result.proposal is not None


def test_unusable_response_is_recorded_but_creates_no_finding_or_proposal(tmp_path):
    title, draft = ready_title(tmp_path)
    provider = LocalResponseProvider("I don't have the chapter text. Please provide the full chapter.")
    with pytest.raises(ContinuityOutputInvalid):
        asyncio.run(ContinuityService.analyze(tmp_path, title_id=title.title_id, chapter_number=1,
            source_asset_id=draft.asset.asset_id, provider=provider))
    with session_scope(tmp_path) as session:
        assert session.scalar(select(func.count(EditorialFindingRow.finding_id)).where(EditorialFindingRow.pass_type == "continuity")) == 0
        assert session.scalar(select(func.count(CanonProposalRow.proposal_id)) ) == 0
        usage = session.scalar(select(UsageEventRow).where(UsageEventRow.provider == "local-test"))
        assert usage is not None and usage.total_tokens == 35
    report = inspect_title(tmp_path, title.title_id)
    assert report["continuity"]["runs"][0]["output_valid"] is False


def test_inspection_flags_pre_hardening_pilot_output(tmp_path):
    root = Path.cwd()
    if not (root / ".kdp" / "state.db").is_file():
        pytest.skip("repository pilot database unavailable")
    report = inspect_title(root, "BK-20260927-5D879BDB")
    prior = next(run for run in report["continuity"]["runs"] if run["job_id"] == "JOB-20260928-57D97700")
    assert prior["output_valid"] is False
    assert "FND-20260928-94DA4F65" in report["continuity"]["findings_from_invalid_analysis"]
    assert "CAN-20260928-171B0F3E" in report["continuity"]["proposals_from_invalid_analysis"]
