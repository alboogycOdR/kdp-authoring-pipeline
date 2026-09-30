from __future__ import annotations

import asyncio
import json
import re
import shutil
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread
from urllib.parse import urlencode

import pytest

from kdp_pipeline.build.service import build_manuscript
from kdp_pipeline.chapter.service import ChapterService
from kdp_pipeline.context import ContextManifest
from kdp_pipeline.inspection import inspect_title
from kdp_pipeline.models.planning import PlanningArtifactKind
from kdp_pipeline.planning import PlanningService, accept_planning_artifact
from kdp_pipeline.providers import FakeProvider
from kdp_pipeline.providers.contracts import GenerationResult
from kdp_pipeline.release.service import KDP_CHECKS, METADATA_CHECKS, create_release_candidate
from kdp_pipeline.storage.db import CanonProposalRow, EditorialFindingRow, utcnow
from kdp_pipeline.storage.files import sha256_file
from kdp_pipeline.storage.service import (
    advance_to_drafting, advance_to_planned, advance_to_validated,
    create_project, create_title, session_scope,
)
from kdp_pipeline.verification.service import add_verification_flag, record_rights
from kdp_pipeline.workspace.actions import run_release_check, run_review_decision
from kdp_pipeline.workspace.render import render_review, render_workspace
from kdp_pipeline.workspace.inspection import inspect_workspace
from kdp_pipeline.workspace.review import inspect_review
from kdp_pipeline.workspace.server import create_workspace_server


class ReviewFixtureProvider(FakeProvider):
    def __init__(self, *, include_placeholder: bool = True):
        super().__init__()
        self.include_placeholder = include_placeholder

    async def generate(self, request):
        if request.task_type == "chapter.draft.1":
            placeholder = "\n\n[SCRIPTURE NEEDED]" if self.include_placeholder else ""
            return GenerationResult(provider=self.provider_name, model=self.model_name,
                text=f"# Chapter One\n\nReflection <script>alert(1)</script>{placeholder}\n",
                latency_ms=0)
        return await super().generate(request)


def _draft_title(root: Path, *, include_placeholder: bool = True) -> tuple[str, str]:
    shutil.copytree(Path("prompts"), root / "prompts")
    project = create_project(root, "Review fixture")
    title = create_title(root, project.project_id, "Review this book")
    provider = ReviewFixtureProvider(include_placeholder=include_placeholder)
    for kind, number in ((PlanningArtifactKind.POSITIONING, None),
                         (PlanningArtifactKind.BOOK_BRIEF, None),
                         (PlanningArtifactKind.OUTLINE, None),
                         (PlanningArtifactKind.CHAPTER_CARD, 1)):
        planned = asyncio.run(PlanningService.generate(root, title_id=title.title_id,
            artifact_kind=kind, context_manifest=ContextManifest(title_id=title.title_id,
            task_type=f"planning.{kind.value}", inputs=[]), provider=provider, chapter_number=number))
        accept_planning_artifact(root, planned.asset.asset_id, reviewer="planner", chapter_number=number)
    advance_to_validated(root, title.title_id)
    advance_to_planned(root, title.title_id)
    advance_to_drafting(root, title.title_id)
    draft = asyncio.run(ChapterService.draft(root, title_id=title.title_id,
        chapter_number=1, provider=provider))
    return title.title_id, draft.asset.asset_id


def _decision(dossier: dict, decision: str, **fields: str) -> dict[str, str]:
    return {"review_hash": dossier["review_hash"], "confirm_consequences": "yes",
            "reviewer": "human-reviewer", "decision": decision, **fields}


def test_planning_review_records_conditions_without_advancing_title(tmp_path: Path):
    shutil.copytree(Path("prompts"), tmp_path / "prompts")
    project = create_project(tmp_path, "Planning review")
    title = create_title(tmp_path, project.project_id, "Planning title")
    proposed = asyncio.run(PlanningService.generate(tmp_path, title_id=title.title_id,
        artifact_kind=PlanningArtifactKind.POSITIONING,
        context_manifest=ContextManifest(title_id=title.title_id,
            task_type="planning.positioning", inputs=[]), provider=FakeProvider()))
    dossier = inspect_review(tmp_path, "asset", proposed.asset.asset_id)
    assert dossier["can_decide"] is True
    assert dossier["artefact"]["type"] == "planning.positioning"
    _, message = run_review_decision(tmp_path, "asset", proposed.asset.asset_id,
        _decision(dossier, "accept", conditions="Verify target reader description."))
    report = inspect_title(tmp_path, title.title_id)
    assert "approval" in message
    assert report["title"]["status"] == "IDEA"
    assert report["planning"]["positioning"]["complete"] is True
    assert any("Verify target reader description." in entry["conditions"]
               for entry in report["chapter_workflow"]["verification_conditions"])


def test_attention_flags_findings_from_invalid_continuity_as_suspect(tmp_path: Path):
    title_id, draft_id = _draft_title(tmp_path)
    snapshot = inspect_workspace(tmp_path)
    report = snapshot["titles"][title_id]
    report["findings"].append({"finding_id": "FND-OLD", "asset_id": draft_id,
                                "pass_type": "continuity", "status": "open"})
    report["continuity"]["findings_from_invalid_analysis"] = ["FND-OLD"]
    page = render_workspace(snapshot)
    assert "FND-OLD is open. From an invalid or unverified continuity attempt" in page
    assert "do not use as guidance" in page


def test_review_dossier_requires_fresh_context_and_records_chapter_conditions(tmp_path: Path):
    title_id, draft_id = _draft_title(tmp_path)
    with session_scope(tmp_path) as session:
        session.add(EditorialFindingRow(finding_id="FND-REVIEW-1", title_id=title_id,
            asset_id=draft_id, pass_type="developmental", severity="minor",
            location="chapter-001", description="Check the devotional flow.",
            status="open", created_at=utcnow()))
        session.commit()
    dossier = inspect_review(tmp_path, "asset", draft_id)
    page = render_review(dossier, "sample-token")
    positions = [page.index(label) for label in ("1. Artefact", "2. Provenance", "3. Findings",
                                                 "4. Blockers", "5. Conditions", "6. Consequences",
                                                 "7. Human decision")]
    assert positions == sorted(positions)
    assert "Check the devotional flow" in page
    assert "[SCRIPTURE NEEDED] remains unresolved" in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<script>alert(1)</script>" not in page
    assert dossier["provenance"][0]["provider"] == "fake"

    with session_scope(tmp_path) as session:
        session.get(EditorialFindingRow, "FND-REVIEW-1").description = "Updated finding after page load."
        session.commit()
    with pytest.raises(ValueError, match="Review context changed"):
        run_review_decision(tmp_path, "asset", draft_id, _decision(dossier, "accept"))

    current = inspect_review(tmp_path, "asset", draft_id)
    title, message = run_review_decision(tmp_path, "asset", draft_id,
        _decision(current, "accept", conditions="Check final layout."))
    assert title == title_id and "approval" in message
    report = inspect_title(tmp_path, title_id)
    accepted_id = report["chapter_lifecycle"]["accepted_chapter_assets"][0]
    accepted = next(item for item in report["assets"] if item["asset_id"] == accepted_id)
    assert sha256_file(Path(accepted["path"])) == accepted["sha256"]
    recorded = next(item for item in report["chapter_workflow"]["verification_conditions"]
                    if item["asset_id"] == accepted_id)
    assert "Check final layout." in recorded["conditions"]
    assert any("[SCRIPTURE NEEDED]" in condition for condition in recorded["conditions"])
    assert inspect_review(tmp_path, "asset", draft_id)["can_decide"] is False
    assert report["inconsistencies"] == []
    workspace = render_workspace(inspect_workspace(tmp_path))
    assert "[SCRIPTURE NEEDED] remains unresolved" in workspace
    assert "No titles currently meet the ready-for-next-step conditions." in workspace


def test_review_http_requires_token_and_shows_exact_result(tmp_path: Path):
    title_id, draft_id = _draft_title(tmp_path)
    server = create_workspace_server(tmp_path, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    try:
        connection.request("GET", f"/reviews/asset/{draft_id}")
        response = connection.getresponse()
        page = response.read().decode("utf-8")
        assert response.status == 200
        token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
        review_hash = re.search(r'name="review_hash" value="([^"]+)"', page).group(1)
        form = {"review_hash": review_hash, "confirm_consequences": "yes",
                "reviewer": "web-reviewer", "decision": "accept"}
        connection.request("POST", f"/reviews/asset/{draft_id}/decide", body=urlencode(form),
                           headers={"Content-Type": "application/x-www-form-urlencoded",
                                    "Sec-Fetch-Site": "same-origin"})
        response = connection.getresponse()
        assert response.status == 403
        response.read()
        form["csrf_token"] = token
        connection.request("POST", f"/reviews/asset/{draft_id}/decide", body=urlencode(form),
                           headers={"Content-Type": "application/x-www-form-urlencoded",
                                    "Sec-Fetch-Site": "same-origin"})
        response = connection.getresponse()
        assert response.status == 303
        redirect = response.headers["Location"]
        response.read()
        connection.request("GET", redirect)
        response = connection.getresponse()
        result_page = response.read().decode("utf-8")
        assert response.status == 200
        accepted_id = inspect_title(tmp_path, title_id)["chapter_lifecycle"]["accepted_chapter_assets"][0]
        assert f"Accepted asset {accepted_id}" in result_page
        assert "already accepted" in result_page
        assert "This record is no longer available" in result_page
    finally:
        connection.close()
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def test_release_review_keeps_blockers_and_records_human_check_and_hold(tmp_path: Path):
    title_id, draft_id = _draft_title(tmp_path)
    draft = inspect_review(tmp_path, "asset", draft_id)
    run_review_decision(tmp_path, "asset", draft_id, _decision(draft, "accept"))
    build = build_manuscript(tmp_path, title_id=title_id, builder="builder")
    candidate = create_release_candidate(tmp_path, title_id=title_id,
        build_id=build.build.build_id, creator="operator")
    dossier = inspect_review(tmp_path, "release", candidate.candidate_id)
    page = render_review(dossier, "sample-token")
    assert "Release checklist" in page
    assert "Complete manuscript build" in page
    assert "Reflection &lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "scripture_placeholder" in page
    assert 'value="approve" disabled' in page
    assert "Final KDP upload and publication remain manual" in page
    with pytest.raises(ValueError, match="approval is blocked"):
        run_review_decision(tmp_path, "release", candidate.candidate_id,
            _decision(dossier, "approve", rationale="Attempt to approve."))

    check_form = {"review_hash": dossier["review_hash"], "confirm_consequences": "yes",
                  "domain": "metadata", "key": "title", "decision": "complete",
                  "reviewer": "human-reviewer", "rationale": "Title checked.",
                  "evidence_reference": "title-review-record", "value": "Review this book"}
    _title, check_message = run_release_check(tmp_path, candidate.candidate_id, check_form)
    assert "metadata check title" in check_message
    with pytest.raises(ValueError, match="Review context changed"):
        run_review_decision(tmp_path, "release", candidate.candidate_id,
            _decision(dossier, "hold", rationale="Need more review."))
    current = inspect_review(tmp_path, "release", candidate.candidate_id)
    _title, message = run_review_decision(tmp_path, "release", candidate.candidate_id,
        _decision(current, "hold", rationale="Need Scripture and checklist review."))
    assert "held" in message
    recorded_review = inspect_review(tmp_path, "release", candidate.candidate_id)["artefact"]["human_review"]
    assert recorded_review["decision"] == "held"
    assert recorded_review["reviewer"] == "human-reviewer"
    assert recorded_review["rationale"] == "Need Scripture and checklist review."
    report = inspect_title(tmp_path, title_id)
    assert report["release"]["candidates"][0]["status"] == "held"
    assert report["release"]["candidates"][0]["current_blockers"]
    review_id = report["release"]["candidates"][0]["approval_id"]
    assert any(item["approval_id"] == review_id and item["decision"] == "held"
               for item in report["approvals"])
    assert not any(item["scope"] == "release_candidate" and item["decision"] == "accepted"
                   for item in report["approvals"])


def test_release_approval_requires_every_human_check_and_keeps_manual_publication(tmp_path: Path):
    title_id, draft_id = _draft_title(tmp_path, include_placeholder=False)
    run_review_decision(tmp_path, "asset", draft_id,
        _decision(inspect_review(tmp_path, "asset", draft_id), "accept"))
    build = build_manuscript(tmp_path, title_id=title_id, builder="builder")
    candidate = create_release_candidate(tmp_path, title_id=title_id,
        build_id=build.build.build_id, creator="operator")
    assert build.build.status == "built"
    for domain, keys in (("metadata", METADATA_CHECKS), ("kdp", KDP_CHECKS),
                         ("ai_disclosure", ("ai_use_disclosure",))):
        for key in keys:
            current = inspect_review(tmp_path, "release", candidate.candidate_id)
            run_release_check(tmp_path, candidate.candidate_id, {
                "review_hash": current["review_hash"], "confirm_consequences": "yes",
                "domain": domain, "key": key, "decision": "complete",
                "reviewer": "checklist-reviewer", "rationale": "Checked against current evidence.",
                "evidence_reference": "human-review-record",
                "statement": "Human-reviewed AI use disclosure." if domain == "ai_disclosure" else "",
            })
    ready = inspect_review(tmp_path, "release", candidate.candidate_id)
    assert ready["blockers"] == []
    assert 'value="approve" disabled' not in render_review(ready, "sample-token")
    _, result = run_review_decision(tmp_path, "release", candidate.candidate_id,
        _decision(ready, "approve", rationale="All checks reviewed by a human."))
    report = inspect_title(tmp_path, title_id)
    assert "approved_for_manual_kdp_action" in result
    assert report["release"]["candidates"][0]["status"] == "approved_for_manual_kdp_action"
    assert any(item["scope"] == "release_candidate" and item["decision"] == "accepted"
               for item in report["approvals"])
    assert report["inconsistencies"] == []


def test_canon_and_verification_decisions_remain_explicit_human_actions(tmp_path: Path):
    title_id, draft_id = _draft_title(tmp_path)
    with session_scope(tmp_path) as session:
        session.add(CanonProposalRow(proposal_id="CAN-REVIEW-1", title_id=title_id,
            entity_id="chapter-001", field="theme", current_value="service",
            proposed_value="stewardship", reason="Human review requested",
            evidence_asset_ids_json=json.dumps([draft_id]), affected_assets_json=json.dumps([draft_id]),
            status="proposed", created_at=utcnow()))
        session.commit()
    canon = inspect_review(tmp_path, "canon", "CAN-REVIEW-1")
    assert "stewardship" in render_review(canon, "sample-token")
    _, message = run_review_decision(tmp_path, "canon", "CAN-REVIEW-1",
                                     _decision(canon, "rejected"))
    assert "rejected" in message and "ledger was not changed" in message

    flag = add_verification_flag(tmp_path, title_id=title_id, kind="research",
        locator="chapter-001:paragraph-1", exact_text="Research claim", reviewer="editor")
    verification = inspect_review(tmp_path, "verification", flag.verification_id)
    assert "Research claim" in render_review(verification, "sample-token")
    _, message = run_review_decision(tmp_path, "verification", flag.verification_id,
        _decision(verification, "not_verified", rationale="No reliable source found."))
    assert "not_verified" in message

    rights = record_rights(tmp_path, title_id=title_id, material_type="image",
        description="Reference image", reviewer="editor")
    rights_dossier = inspect_review(tmp_path, "rights", rights.rights_record_id)
    assert 'value="cleared" disabled' in render_review(rights_dossier, "sample-token")
    _, message = run_review_decision(tmp_path, "rights", rights.rights_record_id,
        _decision(rights_dossier, "restricted", rationale="License unavailable."))
    assert "restricted" in message
    report = inspect_title(tmp_path, title_id)
    assert report["verification"]["items"][0]["status"] == "not_verified"
    assert report["verification"]["rights_records"][0]["status"] == "restricted"
