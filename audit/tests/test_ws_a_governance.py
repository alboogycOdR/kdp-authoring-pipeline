"""WS-A — governance invariants and state machine."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from lab.kdplab import CaptureProvider, draft_and_accept, plan_title, rows
from kdp_pipeline.build.service import build_manuscript
from kdp_pipeline.chapter import ChapterService, accept_chapter
from kdp_pipeline.core.state_machine import TitleState
from kdp_pipeline.inspection import doctor
from kdp_pipeline.release.service import (KDP_CHECKS, METADATA_CHECKS, create_release_candidate,
                                          record_candidate_check, review_release_candidate)
from kdp_pipeline.storage.service import transition_title


def _complete_checklist(root: Path, candidate_id: str, who: str) -> None:
    for key in METADATA_CHECKS:
        record_candidate_check(root, candidate_id, domain="metadata", key=key, decision="complete",
                               reviewer=who, rationale="ok", evidence_reference="x")
    for key in KDP_CHECKS:
        record_candidate_check(root, candidate_id, domain="kdp", key=key, decision="complete",
                               reviewer=who, rationale="ok", evidence_reference="x")
    record_candidate_check(root, candidate_id, domain="ai_disclosure", key="ai_use_disclosure",
                           decision="complete", reviewer=who, rationale="ok", evidence_reference="x",
                           statement="None")


def test_KDP_AUD_003_cli_transition_reaches_kdp_draft_ready_without_preflight_or_release_approval(root, evidence):
    """`kdp transition` (transition_title) only gates PLANNED. PREFLIGHT_PASSED and KDP_DRAFT_READY
    must require a passed preflight / approved release candidate."""
    book = plan_title(root)
    draft_and_accept(book)
    walked = []
    try:
        for target in (TitleState.EDITING, TitleState.ASSET_READY, TitleState.PREFLIGHT_PASSED,
                       TitleState.HUMAN_RELEASE_REVIEW, TitleState.KDP_DRAFT_READY):
            try:
                transition_title(root, book.title_id, target)
            except ValueError as exc:
                walked.append(f"refused {target.value}: {exc}")
                break
            walked.append(target.value)
    finally:
        candidates = rows(root, "select count(*) n from release_candidate_records")[0]["n"]
        builds = rows(root, "select count(*) n from manuscript_builds")[0]["n"]
        (evidence / "walk.json").write_text(json.dumps(
            {"reached": walked, "builds": builds, "release_candidates": candidates}, indent=2))
    assert "PREFLIGHT_PASSED" not in walked and "KDP_DRAFT_READY" not in walked, \
        f"Reached {walked[-1]} with {builds} builds and {candidates} release candidates"



def test_KDP_AUD_004_accepted_chapter_cannot_be_superseded_so_conditions_block_release_forever(root, evidence):
    """A chapter accepted with a condition (the Workspace adds one automatically for
    [SCRIPTURE NEEDED]) is a permanent build blocker; a corrected revision must be acceptable."""
    provider = CaptureProvider({"chapter.draft.1": "# Chapter One\n\nReflection: [SCRIPTURE NEEDED]\n"})
    book = plan_title(root, provider)
    draft_and_accept(book, provider, conditions=["[SCRIPTURE NEEDED] remains unresolved"])
    first = build_manuscript(root, title_id=book.title_id, builder="b")
    fixed = asyncio.run(ChapterService.revise(root, title_id=book.title_id, chapter_number=1,
                                              source_asset_id=book.ids["draft1"],
                                              provider=CaptureProvider({"chapter.revise.1": "# Chapter One\n\nReflection: Psalm 23:1 (KJV).\n"})))
    try:
        # The fix must be an explicit, audited supersede — never a silent overwrite.
        accept_chapter(root, fixed.asset.asset_id, chapter_number=1, reviewer="editor",
                       supersede=True, supersede_reason="Scripture reference supplied and verified")
        second = build_manuscript(root, title_id=book.title_id, builder="b")
        error = None if second.build.status == "built" else f"rebuild still blocked: {second.manifest['blockers']}"
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    (evidence / "result.json").write_text(json.dumps({"first_build_blockers": first.manifest["blockers"],
                                                      "accept_corrected_revision_error": error}, indent=2))
    assert error is None, f"Corrected chapter cannot replace the accepted one: {error}"


def test_KDP_AUD_015_release_approved_while_title_in_policy_hold_by_one_self_declared_person(root, evidence):
    book = plan_title(root)
    draft_and_accept(book)
    build = build_manuscript(root, title_id=book.title_id, builder="same-person")
    transition_title(root, book.title_id, TitleState.POLICY_HOLD)
    candidate = create_release_candidate(root, title_id=book.title_id, build_id=build.build.build_id, creator="same-person")
    _complete_checklist(root, candidate.candidate_id, "same-person")
    row, approval = review_release_candidate(root, candidate.candidate_id, decision="approve",
                                             reviewer="same-person", rationale="lgtm")
    state = rows(root, "select status from titles where title_id=?", book.title_id)[0]["status"]
    (evidence / "result.json").write_text(json.dumps({"title_state": state, "candidate_status": row.status,
        "approval_id": approval.approval_id if approval else None,
        "distinct_actors": sorted({r["actor_id"] for r in rows(root, "select actor_id from audit_events where entity_id=?", candidate.candidate_id)})}, indent=2))
    assert row.status != "approved_for_manual_kdp_action", \
        "Release approved while title is in POLICY_HOLD, by the same person who built, froze and checked it"


def test_KDP_AUD_016_chapter_acceptance_ignores_title_state_and_chapter_number(root, evidence):
    provider = CaptureProvider()
    book = plan_title(root, provider, chapters=2)
    draft2 = asyncio.run(ChapterService.draft(root, title_id=book.title_id, chapter_number=2, provider=provider))
    transition_title(root, book.title_id, TitleState.POLICY_HOLD)
    try:
        result = accept_chapter(root, draft2.asset.asset_id, chapter_number=1, reviewer="x")
        outcome = {"accepted_as": Path(result.destination_path).name, "title_state": "POLICY_HOLD"}
    except Exception as exc:  # noqa: BLE001
        outcome = {"error": str(exc)}
    (evidence / "result.json").write_text(json.dumps(outcome, indent=2))
    assert "error" in outcome, f"A chapter-2 draft was accepted as chapter 1 while the title is in POLICY_HOLD: {outcome}"


def test_KDP_AUD_021_audit_log_rewrite_is_undetectable(root, evidence):
    book = plan_title(root)
    try:
        with sqlite3.connect(root / ".kdp" / "state.db") as conn:
            conn.execute("update audit_events set actor_id='someone-else' where action='planning.accepted'")
            conn.execute("delete from audit_events where action='title.transition'")
    except sqlite3.DatabaseError as exc:  # append-only enforced in the database: the defence we want
        (evidence / "doctor.json").write_text(json.dumps({"rewrite_refused": str(exc)}))
        return
    checks = doctor(root)
    flagged = [c for c in checks if c["status"] != "OK" and "audit" in c["check"]]
    (evidence / "doctor.json").write_text(json.dumps(checks, indent=2))
    assert flagged, "Rewriting and deleting audit events is not detected by doctor (no hash chain / triggers)"


def test_KDP_AUD_012_canon_files_edited_on_disk_are_fed_to_the_model_undetected(root, evidence):
    from kdp_pipeline.continuity import ContinuityService
    provider = CaptureProvider()
    book = plan_title(root, provider)
    draft = asyncio.run(ChapterService.draft(root, title_id=book.title_id, chapter_number=1, provider=provider))
    canon = root / "projects" / book.project_id / "titles" / book.title_id / "06_canon" / "entities.json"
    canon.write_text(json.dumps({"entities": [{"name": "INJECTED-CANON: the hero is secretly a villain"}]}))
    asyncio.run(ContinuityService.analyze(root, title_id=book.title_id, chapter_number=1,
                                          source_asset_id=draft.asset.asset_id, provider=provider))
    sent = provider.requests[-1].rendered_prompt.rendered_text
    checks = doctor(root)
    (evidence / "result.json").write_text(json.dumps({
        "injected_text_sent_to_model": "INJECTED-CANON" in sent,
        "canon_proposals_decided": rows(root, "select count(*) n from canon_proposals where status!='proposed'")[0]["n"],
        "doctor_non_ok": [c for c in checks if c["status"] != "OK"]}, indent=2))
    assert "INJECTED-CANON" not in sent or any("canon" in c["check"] for c in checks if c["status"] != "OK"), \
        "Canon baseline was changed without any CanonProposal and consumed by the model; nothing detected it"


def test_KDP_AUD_031_manual_edit_of_ai_chapter_is_counted_as_non_ai_in_release_disclosure(root, evidence):
    from kdp_pipeline.workspace.authoring import create_manual_revision, read_edit_source
    provider = CaptureProvider({"chapter.draft.1": "# Chapter One\n\nAI written body.\n"})
    book = plan_title(root, provider)
    draft = asyncio.run(ChapterService.draft(root, title_id=book.title_id, chapter_number=1, provider=provider))
    text, digest, _ = read_edit_source(root, book.title_id, draft.asset.asset_id)
    create_manual_revision(root, book.title_id, draft.asset.asset_id, {
        "operator": "editor", "reason": "typo", "content": text.replace("body", "body!"), "source_sha256": digest})
    manual = rows(root, "select asset_id from assets where asset_type='chapter.revision'")[0]["asset_id"]
    accept_chapter(root, manual, chapter_number=1, reviewer="editor")
    build = build_manuscript(root, title_id=book.title_id, builder="b")
    candidate = create_release_candidate(root, title_id=book.title_id, build_id=build.build.build_id, creator="c")
    summary = json.loads(candidate.ai_use_summary_json)
    (evidence / "ai_use_summary.json").write_text(json.dumps(summary, indent=2))
    assert summary["ai_asset_count"] >= 1, \
        "A chapter that is 99.9% AI-generated text is reported as ai_asset_count=0 after a one-character manual edit"


def test_KDP_AUD_044_ai_revision_cannot_be_accepted_in_the_workspace(root, evidence):
    """AI revisions are stored as chapter.revise.N-JOB.md; the dossier/queue regexes only know draft|revision."""
    from kdp_pipeline.workspace.review import inspect_review
    from kdp_pipeline.chapters.service import chapter_status
    provider = CaptureProvider()
    book = plan_title(root, provider)
    draft = asyncio.run(ChapterService.draft(root, title_id=book.title_id, chapter_number=1, provider=provider))
    revision = asyncio.run(ChapterService.revise(root, title_id=book.title_id, chapter_number=1,
                                                 source_asset_id=draft.asset.asset_id, provider=provider))
    dossier = inspect_review(root, "asset", revision.asset.asset_id)
    status = chapter_status(root, book.title_id)
    (evidence / "dossier.json").write_text(json.dumps({"file": Path(revision.output_path).name,
        "blockers": dossier["blockers"], "can_decide": dossier["can_decide"],
        "chapter_status_draft_ids": status["chapters"][0]["draft_asset_ids"]}, indent=2))
    assert dossier["can_decide"], f"AI revision cannot be accepted in the browser: {dossier['blockers']}"
