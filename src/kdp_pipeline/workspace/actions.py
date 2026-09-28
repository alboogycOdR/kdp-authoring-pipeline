from __future__ import annotations

from pathlib import Path

from kdp_pipeline.build.service import build_manuscript
from kdp_pipeline.chapter.service import accept_chapter
from kdp_pipeline.chapters.service import queue_chapters, resume_queue, stop_queue
from kdp_pipeline.concept.service import accept_concept
from kdp_pipeline.continuity.service import approve_canon_proposal
from kdp_pipeline.inspection.service import _read_only_session
from kdp_pipeline.planning.acceptance import accept_planning_artifact
from kdp_pipeline.release.service import (create_release_candidate, export_release_packet,
                                          record_candidate_check, review_release_candidate)
from kdp_pipeline.storage.db import ReleaseCandidateRow, TitleRow
from kdp_pipeline.models.planning import PlanningArtifactKind
from kdp_pipeline.verification.service import (
    add_verification_flag, decide_rights_record, decide_verification, record_rights,
    scan_scripture_placeholders,
)
from kdp_pipeline.workspace.review import inspect_review


ACTION_LABELS = {
    "scan-scripture": "Scripture placeholders scanned",
    "add-flag": "Verification flag added",
    "add-rights": "Rights record added",
    "queue-chapters": "Chapter queue updated",
    "pause-queue": "Chapter queue paused",
    "resume-queue": "Chapter queue resumed",
    "build-manuscript": "Manuscript build created",
    "create-candidate": "Release candidate created",
    "export-packet": "Release packet exported",
}


def _required(form: dict[str, str], key: str, *, limit: int = 500) -> str:
    value = form.get(key, "").strip()
    if not value or len(value) > limit:
        raise ValueError(f"{key.replace('_', ' ').title()} is required (up to {limit} characters).")
    return value


def _optional(form: dict[str, str], key: str, *, limit: int = 500) -> str | None:
    value = form.get(key, "").strip()
    if len(value) > limit:
        raise ValueError(f"{key.replace('_', ' ').title()} exceeds {limit} characters.")
    return value or None


def _number(form: dict[str, str], key: str) -> int:
    value = _required(form, key, limit=3)
    if not value.isascii() or not value.isdecimal():
        raise ValueError(f"{key.replace('_', ' ').title()} must be a positive chapter number.")
    return int(value)


def run_action(root: Path, title_id: str, action: str, form: dict[str, str]) -> str:
    """Route an explicit Workspace action to an existing audited service."""
    if action not in ACTION_LABELS:
        raise ValueError("Unknown Workspace action.")
    with _read_only_session(root) as session:
        if session.get(TitleRow, title_id) is None:
            raise ValueError("Title not found.")

    if action == "scan-scripture":
        result = scan_scripture_placeholders(root, title_id)
        return f"{result['created_count']} new, {result['existing_count']} already queued."
    if action == "add-flag":
        row = add_verification_flag(root, title_id=title_id,
            kind=_required(form, "kind", limit=30), locator=_required(form, "locator", limit=200),
            exact_text=_required(form, "exact_text", limit=2000), reviewer=_required(form, "operator", limit=100),
            asset_id=_optional(form, "asset_id", limit=80))
        return f"{row.verification_id} is pending human verification."
    if action == "add-rights":
        row = record_rights(root, title_id=title_id,
            material_type=_required(form, "material_type", limit=100),
            description=_required(form, "description", limit=2000),
            reviewer=_required(form, "operator", limit=100),
            asset_id=_optional(form, "asset_id", limit=80),
            source=_optional(form, "source", limit=500),
            provenance_reference=_optional(form, "provenance_reference", limit=500),
            legal_basis=_optional(form, "legal_basis", limit=500),
            evidence_reference=_optional(form, "evidence_reference", limit=500))
        return f"{row.rights_record_id} is pending human review."
    if action == "queue-chapters":
        rows = queue_chapters(root, title_id, _number(form, "start"), _number(form, "through"),
                              actor_id=_required(form, "operator", limit=100))
        return f"{len(rows)} chapter queue items recorded; no drafting started."
    if action == "pause-queue":
        count = stop_queue(root, title_id, actor_id=_required(form, "operator", limit=100))
        return f"{count} queued items paused."
    if action == "resume-queue":
        count = resume_queue(root, title_id, actor_id=_required(form, "operator", limit=100))
        return f"{count} paused items resumed."
    if action == "build-manuscript":
        result = build_manuscript(root, title_id=title_id,
                                  builder=_required(form, "operator", limit=100))
        return f"{result.build.build_id}: {result.build.status}; {len(result.manifest['blockers'])} blockers."
    if action == "create-candidate":
        row = create_release_candidate(root, title_id=title_id,
            build_id=_required(form, "build_id", limit=80),
            creator=_required(form, "operator", limit=100))
        return f"{row.candidate_id}: {row.status}; human review remains required."

    candidate_id = _required(form, "candidate_id", limit=80)
    with _read_only_session(root) as session:
        candidate = session.get(ReleaseCandidateRow, candidate_id)
        if candidate is None or candidate.title_id != title_id:
            raise ValueError("Release candidate does not belong to this title.")
    row, _asset = export_release_packet(root, candidate_id,
        creator=_required(form, "operator", limit=100))
    return f"{row.packet_id} exported for human review."


def run_review_decision(root: Path, kind: str, identifier: str, form: dict[str, str]) -> tuple[str, str]:
    """Require a fresh, acknowledged dossier and delegate the decision to an audited service."""
    dossier = inspect_review(root, kind, identifier)
    if dossier is None:
        raise ValueError("Review item was not found.")
    if form.get("review_hash") != dossier["review_hash"]:
        raise ValueError("Review context changed. Reload this page and inspect the current record before deciding.")
    if form.get("confirm_consequences") != "yes":
        raise ValueError("Confirm that you reviewed the consequences before deciding.")
    if not dossier["can_decide"]:
        raise ValueError("This item is no longer available for a decision.")
    reviewer = _required(form, "reviewer", limit=100)
    decision = _required(form, "decision", limit=30)
    if kind == "asset":
        if decision != "accept":
            raise ValueError("Asset review supports explicit acceptance only.")
        raw_conditions = _optional(form, "conditions", limit=2600) or ""
        conditions = [line.strip() for line in raw_conditions.splitlines() if line.strip()]
        if dossier["artefact"]["type"].startswith("chapter."):
            mandatory = next((c for c in dossier["conditions"] if "[SCRIPTURE NEEDED]" in c), None)
            if mandatory and mandatory not in conditions:
                conditions.append(mandatory)
            result = accept_chapter(root, identifier, chapter_number=dossier["chapter_number"],
                                    reviewer=reviewer, conditions=conditions,
                                    finding_ids=[finding["id"] for finding in dossier["findings"]],
                                    proposal_ids=dossier["related_proposals"])
        elif dossier["artefact"]["type"] == "concept.brief":
            result = accept_concept(root, identifier, reviewer=reviewer, conditions=conditions)
        else:
            result = accept_planning_artifact(root, identifier, reviewer=reviewer,
                chapter_number=dossier["chapter_number"] if dossier["artefact"]["type"] == "planning.chapter-card" else None,
                conditions=conditions)
        return dossier["title_id"], f"Accepted asset {result.accepted_asset.asset_id}; approval {result.approval.approval_id}."
    if kind == "canon":
        if decision not in {"accepted", "rejected"}:
            raise ValueError("Canon decision must be accepted or rejected.")
        if decision == "accepted" and dossier["blockers"]:
            raise ValueError("A proposal from invalid continuity analysis cannot be accepted.")
        row = approve_canon_proposal(root, identifier, reviewer=reviewer, decision=decision)
        return dossier["title_id"], f"Canon proposal {row.proposal_id} recorded as {row.status}; canon ledger was not changed."
    rationale = _required(form, "rationale", limit=2000)
    if kind == "release":
        if decision not in {"approve", "hold", "reject"}:
            raise ValueError("Release decision must be approve, hold, or reject.")
        if decision == "approve" and dossier["blockers"]:
            raise ValueError("Release approval is blocked; review the listed blockers.")
        row, approval = review_release_candidate(root, identifier, decision=decision,
                                                  reviewer=reviewer, rationale=rationale)
        return dossier["title_id"], (f"Release candidate {row.candidate_id}: {row.status}; "
            f"approval {approval.approval_id if approval else 'none'}. Final KDP action remains manual.")
    if kind == "verification":
        if decision not in {"verified", "not_verified", "not_applicable"}:
            raise ValueError("Verification decision is unsupported.")
        row = decide_verification(root, identifier, decision=decision, reviewer=reviewer,
            rationale=rationale, evidence_reference=_optional(form, "evidence_reference", limit=500),
            proposed_reference=_optional(form, "proposed_reference", limit=200),
            source_policy=_optional(form, "source_policy", limit=500))
        return dossier["title_id"], f"Verification item {row.verification_id}: {row.status}."
    if kind == "rights":
        if decision not in {"cleared", "restricted", "not_applicable"}:
            raise ValueError("Rights decision is unsupported.")
        row = decide_rights_record(root, identifier, decision=decision,
                                   reviewer=reviewer, rationale=rationale)
        return dossier["title_id"], f"Rights record {row.rights_record_id}: {row.status}."
    raise ValueError("Unknown review kind.")


def run_release_check(root: Path, identifier: str, form: dict[str, str]) -> tuple[str, str]:
    dossier = inspect_review(root, "release", identifier)
    if dossier is None:
        raise ValueError("Release candidate was not found.")
    if form.get("review_hash") != dossier["review_hash"]:
        raise ValueError("Review context changed. Reload and inspect the candidate before recording a check.")
    if form.get("confirm_consequences") != "yes":
        raise ValueError("Confirm that you reviewed the candidate context before recording a check.")
    if not dossier["can_decide"]:
        raise ValueError("This candidate is no longer open for checklist updates.")
    domain = _required(form, "domain", limit=30)
    key = _required(form, "key", limit=80)
    row = record_candidate_check(root, identifier, domain=domain, key=key,
        decision=_required(form, "decision", limit=30),
        reviewer=_required(form, "reviewer", limit=100),
        rationale=_required(form, "rationale", limit=2000),
        evidence_reference=_required(form, "evidence_reference", limit=500),
        value=_optional(form, "value", limit=500),
        statement=_optional(form, "statement", limit=2000))
    return dossier["title_id"], f"Recorded {domain} check {key}; candidate is {row.status}."
