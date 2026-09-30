from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy import select

from kdp_pipeline.core.hashing import canonical_json_bytes, sha256_bytes
from kdp_pipeline.inspection.service import _read_only_session, inspect_title
from kdp_pipeline.storage.db import (
    ApprovalRow, AssetRow, AuditEventRow, CanonProposalRow, EditorialFindingRow, ManuscriptBuildRow, ProvenanceRow,
    ReleaseCandidateRow, RightsLogRow, VerificationItemRow,
)
from kdp_pipeline.storage.files import sha256_file


_ACCEPTABLE_ASSETS = {"concept.brief", "planning.positioning", "planning.book-brief",
                      "planning.outline", "planning.chapter-card", "chapter.draft", "chapter.revision"}
_MAX_BROWSER_ASSET = 1_000_000


def _asset_info(root: Path, asset: AssetRow) -> dict:
    path = Path(asset.path).resolve()
    within_root = path.is_relative_to(root.resolve())
    readable = within_root and path.is_file() and path.stat().st_size <= _MAX_BROWSER_ASSET
    hash_matches = bool(readable and sha256_file(path) == asset.sha256)
    try:
        content = path.read_text(encoding="utf-8") if hash_matches else None
    except (UnicodeDecodeError, OSError):
        content = None
    return {"asset_id": asset.asset_id, "type": asset.asset_type, "status": asset.approval_status,
            "path": str(path.relative_to(root.resolve())) if within_root else "outside workspace",
            "sha256": asset.sha256, "hash_matches": hash_matches, "content": content,
            "source_ref": asset.source_ref, "creator_type": asset.creator_type,
            "creator": asset.creator, "version": asset.version}


def _provenance(row: ProvenanceRow | None) -> dict | None:
    if row is None:
        return None
    return {"provenance_id": row.provenance_id, "asset_id": row.asset_id,
            "provider": row.provider, "model": row.model,
            "template": row.prompt_template_id, "template_version": row.prompt_template_version,
            "input_references": json.loads(row.input_references_json or "[]"),
            "output_hash": row.output_hash, "human_note": row.human_contribution_note,
            "ai_classification": row.ai_classification, "disclosure_decision": row.disclosure_decision}


def _finding(row: EditorialFindingRow) -> dict:
    return {"id": row.finding_id, "pass": row.pass_type, "severity": row.severity,
            "location": row.location, "description": row.description, "evidence": row.evidence,
            "recommended_action": row.recommended_action, "status": row.status,
            "resolution": row.resolution}


def _parsed_value(value: str | None) -> object:
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def inspect_review(root: Path, kind: str, identifier: str) -> dict | None:
    """Read the complete decision context without changing operational state."""
    root = root.resolve()
    if kind not in {"asset", "canon", "release", "verification", "rights"}:
        return None
    with _read_only_session(root) as session:
        if kind == "asset":
            row = session.get(AssetRow, identifier)
            if row is None or row.asset_type not in _ACCEPTABLE_ASSETS:
                return None
            title_id = row.title_id
        elif kind == "canon":
            row = session.get(CanonProposalRow, identifier)
            title_id = row.title_id if row else None
        elif kind == "release":
            row = session.get(ReleaseCandidateRow, identifier)
            title_id = row.title_id if row else None
        elif kind == "verification":
            row = session.get(VerificationItemRow, identifier)
            title_id = row.title_id if row else None
        else:
            row = session.get(RightsLogRow, identifier)
            title_id = row.title_id if row else None
        if row is None or title_id is None:
            return None

    report = inspect_title(root, title_id)
    with _read_only_session(root) as session:
        row = session.get({"asset": AssetRow, "canon": CanonProposalRow,
                           "release": ReleaseCandidateRow, "verification": VerificationItemRow,
                           "rights": RightsLogRow}[kind], identifier)
        if row is None:
            return None
        conditions = [condition for entry in report.get("chapter_workflow", {}).get("verification_conditions", [])
                      for condition in entry.get("conditions", [])]
        blockers: list[str] = []
        findings: list[dict] = []
        related_proposals: list[str] = []
        provenance: list[dict] = []
        artefact: dict
        status: str
        consequence: str
        can_decide = False
        chapter_number = None
        if kind == "asset":
            artefact = _asset_info(root, row)
            status = row.approval_status
            accepted_copy = session.scalar(select(AssetRow).where(
                AssetRow.source_ref == row.asset_id, AssetRow.approval_status == "accepted"))
            artefact["accepted_asset_id"] = accepted_copy.asset_id if accepted_copy else None
            if accepted_copy:
                prior_approval = session.scalar(select(ApprovalRow).where(
                    ApprovalRow.asset_id == accepted_copy.asset_id,
                    ApprovalRow.decision == "accepted"))
                artefact["approval_id"] = prior_approval.approval_id if prior_approval else None
            source_ids = {row.asset_id}
            source_ref = row.source_ref
            while source_ref and source_ref not in source_ids:
                source_ids.add(source_ref)
                ancestor = session.get(AssetRow, source_ref)
                source_ref = ancestor.source_ref if ancestor else None
            analysis_ids = {a.asset_id for a in session.scalars(select(AssetRow).where(
                AssetRow.title_id == title_id)) if a.source_ref in source_ids and a.asset_type.startswith("analysis.")}
            findings = [_finding(f) for f in session.scalars(select(EditorialFindingRow).where(
                EditorialFindingRow.title_id == title_id)) if f.asset_id in source_ids | analysis_ids]
            for recommendation in report.get("editorial", {}).get("revision_recommendations", []):
                if recommendation.get("source_asset_id") in source_ids:
                    findings.append({"id": recommendation["recommendation_id"],
                        "pass": "revision recommendation", "severity": "review",
                        "location": f"chapter-{recommendation['chapter_number']:03d}",
                        "description": recommendation["recommendation"],
                        "status": recommendation["status"]})
            if row.asset_type == "concept.brief":
                artefact["scorecards"] = [score for score in report.get("concept", {}).get("scorecards", [])
                                          if score.get("asset_id") == row.asset_id]
                findings.extend({"id": f"concept-warning-{index}", "pass": "concept validation",
                    "severity": "review", "location": "concept brief", "description": warning,
                    "status": "open"} for index, warning in enumerate(
                        report.get("concept", {}).get("validation_warnings", []), start=1))
            if row.asset_type.startswith("chapter."):
                findings.extend({"id": f"continuity-warning-{index}", "pass": "continuity inspection",
                    "severity": "review", "location": "title", "description": warning,
                    "status": "open"} for index, warning in enumerate(
                        report.get("continuity", {}).get("warnings", []), start=1))
            finding_ids = {finding["id"] for finding in findings}
            related_proposals = [proposal.proposal_id for proposal in session.scalars(select(CanonProposalRow).where(
                CanonProposalRow.title_id == title_id)) if proposal.finding_id in finding_ids]
            provenance_row = session.scalar(select(ProvenanceRow).where(ProvenanceRow.asset_id == row.asset_id))
            provenance = [_provenance(provenance_row)] if provenance_row else []
            if artefact["content"] is None:
                blockers.append("Artefact content is missing, outside the workspace, too large, unreadable, or does not match its registered hash.")
            if provenance_row is None:
                blockers.append("The source artefact has no provenance record.")
            if row.approval_status != "experimental":
                blockers.append("This artefact is no longer experimental.")
            if accepted_copy:
                blockers.append(f"This artefact was already accepted as {accepted_copy.asset_id}.")
            if row.asset_type in {"chapter.draft", "chapter.revision"}:
                match = re.search(r"chapter\.(?:draft|revision|revise)\.(\d+)[-.]", Path(row.path).name)
                chapter_number = int(match.group(1)) if match else None
                if chapter_number is None:
                    blockers.append("The chapter number cannot be determined from the artefact path.")
            elif row.asset_type == "planning.chapter-card":
                match = re.search(r"(?:chapter_card|chapter-card)[-.](\d+)[-.]", Path(row.path).name)
                chapter_number = int(match.group(1)) if match else None
                if chapter_number is None:
                    blockers.append("The chapter card number cannot be determined from the artefact path.")
            if row.asset_type.startswith("chapter.") and "[SCRIPTURE NEEDED]" in (artefact["content"] or ""):
                conditions.append("[SCRIPTURE NEEDED] remains unresolved; a later verification pass is required before release.")
            can_decide = not blockers
            consequence = ("Accepting copies this exact artefact into the accepted manuscript or planning location, "
                           "creates an approval and provenance lineage, and records any conditions. "
                           "Conditions remain release blockers; acceptance does not verify them.")
        elif kind == "canon":
            status = row.status
            artefact = {"proposal_id": row.proposal_id, "entity_id": row.entity_id, "field": row.field,
                        "current_value": _parsed_value(row.current_value),
                        "proposed_value": _parsed_value(row.proposed_value),
                        "reason": row.reason, "reviewer": row.reviewer,
                        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
                        "evidence_asset_ids": json.loads(row.evidence_asset_ids_json or "[]"),
                        "affected_assets": json.loads(row.affected_assets_json or "[]")}
            if row.finding_id:
                finding = session.get(EditorialFindingRow, row.finding_id)
                if finding:
                    findings.append(_finding(finding))
                    analysis = session.get(AssetRow, finding.asset_id) if finding.asset_id else None
                    prov = session.scalar(select(ProvenanceRow).where(ProvenanceRow.asset_id == analysis.asset_id)) if analysis else None
                    if prov:
                        provenance.append(_provenance(prov))
            if identifier in report.get("continuity", {}).get("proposals_from_invalid_analysis", []):
                blockers.append("This proposal came from an invalid or unverified continuity analysis; acceptance is disabled.")
            if status != "proposed":
                blockers.append("This proposal is no longer proposed.")
            can_decide = status == "proposed"
            consequence = ("Accepting or rejecting records a human decision on this proposal. "
                           "The existing service does not directly mutate the canon ledger; a separate approved workflow is required.")
        elif kind == "release":
            status = row.status
            inspected = next((c for c in report["release"]["candidates"] if c["candidate_id"] == identifier), None)
            if inspected is None:
                return None
            artefact = {"candidate_id": identifier, "candidate_sha256": row.candidate_sha256,
                        "build_id": row.build_id, "frozen_inputs": inspected["frozen_inputs"],
                        "metadata": inspected["metadata"], "metadata_checks": inspected["metadata_checks"],
                        "rights_summary": inspected["rights_summary"], "ai_use_summary": inspected["ai_use_summary"],
                        "ai_disclosure": inspected["ai_disclosure"], "kdp_checks": inspected["kdp_checks"]}
            review_id = inspected.get("approval_id")
            review_row = session.get(ApprovalRow, review_id) if review_id else None
            review_event = session.scalar(select(AuditEventRow).where(
                AuditEventRow.entity_id == identifier,
                AuditEventRow.action == "release.candidate.reviewed"
            ).order_by(AuditEventRow.timestamp_utc.desc()))
            artefact["human_review"] = ({"review_id": review_row.approval_id,
                "decision": review_row.decision, "reviewer": review_row.approver,
                "conditions": json.loads(review_row.conditions_json or "[]"),
                "recorded_at": review_row.created_at.isoformat(),
                "rationale": json.loads(review_event.metadata_json or "{}").get("rationale") if review_event else None}
                if review_row else None)
            blockers = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in inspected["current_blockers"]]
            build_row = session.get(ManuscriptBuildRow, row.build_id)
            build_asset = session.get(AssetRow, build_row.asset_id) if build_row else None
            manuscript = _asset_info(root, build_asset) if build_asset else None
            artefact["manuscript"] = manuscript
            if manuscript is None or manuscript["content"] is None:
                blockers.append("The complete build manuscript cannot be displayed with a matching hash; browser approval is disabled.")
            findings = [_finding(f) for f in session.scalars(select(EditorialFindingRow).where(
                EditorialFindingRow.title_id == title_id)) if f.status == "open"]
            for item in inspected["frozen_inputs"]:
                prov = session.scalar(select(ProvenanceRow).where(ProvenanceRow.asset_id == item["asset_id"]))
                if prov:
                    provenance.append(_provenance(prov))
            conditions.append("Final KDP upload and publication remain manual human actions, even after approval.")
            can_decide = status not in {"approved_for_manual_kdp_action", "rejected"}
            consequence = ("Approve authorizes only manual KDP action after all blockers clear. "
                           "Hold or reject records a human decision. No upload or publication occurs here.")
        elif kind == "verification":
            status = row.status
            artefact = {"verification_id": row.verification_id, "kind": row.kind, "asset_id": row.asset_id,
                        "locator": row.locator, "exact_text": row.exact_text,
                        "proposed_reference": row.proposed_reference, "source_policy": row.source_policy,
                        "evidence_reference": row.evidence_reference, "rationale": row.rationale,
                        "reviewer": row.reviewer}
            if row.asset_id:
                source = session.get(AssetRow, row.asset_id)
                prov = session.scalar(select(ProvenanceRow).where(ProvenanceRow.asset_id == row.asset_id)) if source else None
                if prov:
                    provenance.append(_provenance(prov))
            can_decide = status == "pending"
            consequence = ("A human verification decision records evidence and rationale. "
                           "It does not insert Scripture text or modify the accepted chapter. "
                           "A remaining [SCRIPTURE NEEDED] placeholder continues to block release until a separate verified manuscript update resolves it.")
        else:
            status = row.status
            artefact = {"rights_record_id": row.rights_record_id, "material_type": row.material_type,
                        "description": row.description, "source": row.source,
                        "legal_basis": row.legal_basis, "evidence_reference": row.evidence_reference,
                        "restrictions": row.restrictions, "asset_id": row.asset_id,
                        "reviewer": row.reviewer, "rationale": row.rationale}
            if row.asset_id:
                prov = session.scalar(select(ProvenanceRow).where(ProvenanceRow.asset_id == row.asset_id))
                if prov:
                    provenance.append(_provenance(prov))
            if not row.legal_basis or not row.evidence_reference:
                blockers.append("Rights clearance requires a recorded legal basis and evidence reference. Add a corrected rights record with that information before clearing.")
            can_decide = status == "pending"
            consequence = ("A human rights decision records its rationale. "
                           "Clearance requires documented legal basis and evidence; no legal conclusion is made automatically.")

    dossier = {"kind": kind, "id": identifier, "title_id": title_id,
               "title": report["title"]["working_title"], "status": status,
               "artefact": artefact, "provenance": provenance, "findings": findings,
               "related_proposals": related_proposals,
               "blockers": blockers, "conditions": conditions, "consequence": consequence,
               "can_decide": can_decide, "chapter_number": chapter_number}
    dossier["review_hash"] = sha256_bytes(canonical_json_bytes(dossier))
    return dossier
