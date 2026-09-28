from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from kdp_pipeline.core.hashing import canonical_json_bytes, sha256_bytes
from kdp_pipeline.core.ids import new_id
from kdp_pipeline.storage.audit import AuditEventWriter
from kdp_pipeline.storage.db import (
    ApprovalRow, AssetRow, ManuscriptBuildRow, ProvenanceRow, ReleaseCandidateRow,
    ReleasePacketRow, RightsLogRow, TitleRow, VerificationItemRow, utcnow,
)
from kdp_pipeline.storage.files import sha256_file, write_json
from kdp_pipeline.storage.service import session_scope


METADATA_CHECKS = ("title", "subtitle", "author", "description", "keywords", "categories",
                   "language", "reader_age", "metadata_policy_current")
KDP_CHECKS = ("current_format_requirements", "current_content_guidelines",
              "metadata_requirements", "rights_and_territories", "ai_content_disclosure",
              "final_upload_settings")
_DOMAINS = {"metadata": set(METADATA_CHECKS), "kdp": set(KDP_CHECKS),
            "ai_disclosure": {"ai_use_disclosure"}}
_CHECK_DECISIONS = {"complete", "not_applicable"}
_REVIEW_DECISIONS = {"approve", "hold", "reject"}
_MANUAL_PUBLICATION_CONDITION = "KDP upload and publication remain manual human-controlled actions."


def _review_hash(candidate: ReleaseCandidateRow) -> str:
    return sha256_bytes(canonical_json_bytes({
        "candidate_sha256": candidate.candidate_sha256,
        "metadata_checks": json.loads(candidate.metadata_checks_json or "{}"),
        "ai_disclosure": json.loads(candidate.ai_disclosure_json or "{}"),
        "kdp_checks": json.loads(candidate.kdp_checks_json or "{}"),
    }))


def _frozen_hash(session, candidate: ReleaseCandidateRow) -> str | None:
    build = session.get(ManuscriptBuildRow, candidate.build_id)
    if build is None:
        return None
    frozen = {"build_id": candidate.build_id, "build_sha256": build.output_sha256,
        "manifest_sha256": build.manifest_sha256,
        "inputs": json.loads(candidate.frozen_inputs_json or "[]"),
        "metadata": json.loads(candidate.frozen_metadata_json or "{}"),
        "rights_summary": json.loads(candidate.rights_summary_json or "{}"),
        "ai_use_summary": json.loads(candidate.ai_use_summary_json or "{}"),
        "rights_state_sha256": candidate.rights_state_sha256,
        "verification_state_sha256": candidate.verification_state_sha256}
    return sha256_bytes(canonical_json_bytes(frozen))


def _state_snapshot(session, title_id: str, included_ids: set[str], model, fields: tuple[str, ...]) -> list[dict]:
    rows = list(session.scalars(select(model).where(model.title_id == title_id)))
    selected = [row for row in rows if row.asset_id is None or row.asset_id in included_ids]
    return [{field: getattr(row, field) for field in fields} for row in selected]


def _baseline_hashes(session, title_id: str, included_ids: set[str]) -> tuple[str, str, list[dict], list[dict]]:
    verification = _state_snapshot(session, title_id, included_ids, VerificationItemRow,
        ("verification_id", "asset_id", "kind", "locator", "exact_text", "status",
         "proposed_reference", "source_policy", "evidence_reference", "rationale", "reviewer"))
    rights = _state_snapshot(session, title_id, included_ids, RightsLogRow,
        ("rights_record_id", "asset_id", "material_type", "description", "source",
         "provenance_reference", "legal_basis", "evidence_reference", "territories_json",
         "term", "restrictions", "status", "rationale", "reviewer"))
    verification.sort(key=lambda row: row["verification_id"])
    rights.sort(key=lambda row: row["rights_record_id"])
    return (sha256_bytes(canonical_json_bytes(verification)),
            sha256_bytes(canonical_json_bytes(rights)), verification, rights)


def _blockers(session, candidate: ReleaseCandidateRow) -> list[dict]:
    blockers = list(json.loads(candidate.initial_blockers_json or "[]"))
    if _frozen_hash(session, candidate) != candidate.candidate_sha256:
        blockers.append({"type": "candidate_snapshot_integrity"})
    build = session.get(ManuscriptBuildRow, candidate.build_id)
    frozen_inputs = json.loads(candidate.frozen_inputs_json or "[]")
    if build is None:
        blockers.append({"type": "missing_build", "build_id": candidate.build_id})
    else:
        output = session.get(AssetRow, build.asset_id)
        manifest_path = Path(build.manifest_path)
        if (output is None or output.asset_type != "manuscript.build" or output.sha256 != build.output_sha256
                or not Path(output.path).is_file() or sha256_file(Path(output.path)) != build.output_sha256):
            blockers.append({"type": "build_output_integrity", "build_id": build.build_id})
        if not manifest_path.is_file() or sha256_file(manifest_path) != build.manifest_sha256:
            blockers.append({"type": "build_manifest_integrity", "build_id": build.build_id})
    included_ids: set[str] = set()
    for item in frozen_inputs:
        included_ids.add(item["asset_id"])
        asset = session.get(AssetRow, item["asset_id"])
        approval = session.scalar(select(ApprovalRow).where(ApprovalRow.asset_id == item["asset_id"],
            ApprovalRow.decision == "accepted"))
        if (asset is None or asset.approval_status != "accepted" or asset.sha256 != item["sha256"]
                or approval is None or approval.candidate_hash != item["sha256"]
                or not Path(asset.path).is_file() or sha256_file(Path(asset.path)) != item["sha256"]):
            blockers.append({"type": "input_asset_integrity", "asset_id": item["asset_id"]})
    verification_hash, rights_hash, _verification, _rights = _baseline_hashes(session,
        candidate.title_id, included_ids)
    if verification_hash != candidate.verification_state_sha256:
        blockers.append({"type": "verification_state_changed", "action": "Create a new release candidate."})
    if rights_hash != candidate.rights_state_sha256:
        blockers.append({"type": "rights_state_changed", "action": "Create a new release candidate."})
    metadata_checks = json.loads(candidate.metadata_checks_json or "{}")
    for key, value in metadata_checks.items():
        if value.get("status") not in _CHECK_DECISIONS:
            blockers.append({"type": "metadata_check", "key": key, "status": value.get("status", "pending")})
    disclosure = json.loads(candidate.ai_disclosure_json or "{}")
    if disclosure.get("status") not in _CHECK_DECISIONS:
        blockers.append({"type": "ai_use_disclosure", "status": disclosure.get("status", "pending")})
    kdp_checks = json.loads(candidate.kdp_checks_json or "{}")
    for key, value in kdp_checks.items():
        if value.get("status") not in _CHECK_DECISIONS:
            blockers.append({"type": "kdp_check", "key": key, "status": value.get("status", "pending")})
    return blockers


def create_release_candidate(root: Path, *, title_id: str, build_id: str,
                             creator: str) -> ReleaseCandidateRow:
    if not creator.strip():
        raise ValueError("Release candidate creator is required")
    with session_scope(root) as session:
        title = session.get(TitleRow, title_id)
        build = session.get(ManuscriptBuildRow, build_id)
        if title is None or build is None or build.title_id != title_id:
            raise ValueError("A release candidate requires a build belonging to the title")
        build_asset = session.get(AssetRow, build.asset_id)
        manifest_path = Path(build.manifest_path)
        if (build_asset is None or not Path(build_asset.path).is_file()
                or sha256_file(Path(build_asset.path)) != build.output_sha256
                or build_asset.sha256 != build.output_sha256
                or not manifest_path.is_file() or sha256_file(manifest_path) != build.manifest_sha256):
            raise ValueError("Build or manifest failed integrity checks")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        frozen_inputs = manifest.get("included_assets", [])
        included_ids = {item["asset_id"] for item in frozen_inputs}
        for item in frozen_inputs:
            asset = session.get(AssetRow, item["asset_id"])
            approval = session.scalar(select(ApprovalRow).where(ApprovalRow.asset_id == item["asset_id"],
                ApprovalRow.decision == "accepted"))
            if (asset is None or asset.approval_status != "accepted" or asset.sha256 != item["sha256"]
                    or approval is None or approval.candidate_hash != item["sha256"]):
                raise ValueError(f"Build input is no longer accepted or has changed: {item['asset_id']}")
        verification_hash, rights_hash, verification, rights = _baseline_hashes(session,
            title_id, included_ids)
        metadata = {"working_title": title.working_title, "final_title": title.final_title,
            "subtitle": title.subtitle, "language": title.language,
            "format_targets": json.loads(title.format_targets_json or "[]")}
        rights_summary = {"records": rights, "record_count": len(rights),
            "unresolved_count": sum(row["status"] not in {"cleared", "not_applicable"} for row in rights)}
        provenance_summary = []
        for item in frozen_inputs:
            asset = session.get(AssetRow, item["asset_id"])
            provenance = session.scalar(select(ProvenanceRow).where(ProvenanceRow.asset_id == item["asset_id"]))
            provenance_summary.append({"asset_id": item["asset_id"],
                "creator_type": asset.creator_type if asset else None,
                "provider": provenance.provider if provenance else None,
                "model": provenance.model if provenance else None,
                "prompt_template_id": provenance.prompt_template_id if provenance else None,
                "ai_classification": provenance.ai_classification if provenance else None,
                "disclosure_decision": provenance.disclosure_decision if provenance else None})
        ai_summary = {"assets": provenance_summary,
            "ai_asset_count": sum(item["creator_type"] == "ai" for item in provenance_summary),
            "status": "pending_human_disclosure"}
        metadata_checks = {key: {"status": "pending", "evidence_reference": None,
                                 "rationale": None, "reviewer": None, "value": None}
                           for key in METADATA_CHECKS}
        kdp_checks = {key: {"status": "pending", "evidence_reference": None,
                             "rationale": None, "reviewer": None}
                      for key in KDP_CHECKS}
        ai_disclosure = {"status": "pending", "statement": None,
                         "evidence_reference": None, "rationale": None, "reviewer": None}
        blockers = list(json.loads(build.blockers_json or "[]"))
        for item in verification:
            if item["status"] not in {"verified", "not_applicable"}:
                blockers.append({"type": "verification", "verification_id": item["verification_id"],
                    "kind": item["kind"], "asset_id": item["asset_id"], "status": item["status"]})
        for item in rights:
            if item["status"] not in {"cleared", "not_applicable"}:
                blockers.append({"type": "rights", "rights_record_id": item["rights_record_id"],
                    "asset_id": item["asset_id"], "status": item["status"]})
        candidate_id = new_id("REL")
        frozen = {"build_id": build_id, "build_sha256": build.output_sha256,
            "manifest_sha256": build.manifest_sha256, "inputs": frozen_inputs,
            "metadata": metadata, "rights_summary": rights_summary,
            "ai_use_summary": ai_summary, "rights_state_sha256": rights_hash,
            "verification_state_sha256": verification_hash}
        candidate_hash = sha256_bytes(canonical_json_bytes(frozen))
        row = ReleaseCandidateRow(candidate_id=candidate_id, title_id=title_id,
            build_id=build_id, candidate_sha256=candidate_hash,
            frozen_inputs_json=json.dumps(frozen_inputs), frozen_metadata_json=json.dumps(metadata),
            rights_summary_json=json.dumps(rights_summary), ai_use_summary_json=json.dumps(ai_summary),
            verification_state_sha256=verification_hash, rights_state_sha256=rights_hash,
            metadata_checks_json=json.dumps(metadata_checks), ai_disclosure_json=json.dumps(ai_disclosure),
            kdp_checks_json=json.dumps(kdp_checks), initial_blockers_json=json.dumps(blockers),
            status="blocked", created_by=creator.strip(), created_at=utcnow())
        session.add(row)
        AuditEventWriter.append(session, actor_id=creator.strip(), action="release.candidate.created",
            entity_type="release_candidate", entity_id=candidate_id, correlation_id=title_id,
            result="blocked", after_hash=candidate_hash, metadata={"build_id": build_id,
                "blocker_count": len(blockers), "input_count": len(frozen_inputs)})
        session.commit()
        return row


def record_candidate_check(root: Path, candidate_id: str, *, domain: str, key: str,
                           decision: str, reviewer: str, rationale: str,
                           evidence_reference: str, value: str | None = None,
                           statement: str | None = None) -> ReleaseCandidateRow:
    if domain not in _DOMAINS or key not in _DOMAINS[domain]:
        raise ValueError("Unknown release checklist domain or key")
    if decision not in _CHECK_DECISIONS or not reviewer.strip() or not rationale.strip() or not evidence_reference.strip():
        raise ValueError("Checklist decisions require a supported status, reviewer, rationale, and evidence reference")
    if domain == "ai_disclosure" and decision == "complete" and not (statement and statement.strip()):
        raise ValueError("AI disclosure completion requires the human-reviewed disclosure statement")
    with session_scope(root) as session:
        row = session.get(ReleaseCandidateRow, candidate_id)
        if row is None:
            raise ValueError(f"Unknown release candidate: {candidate_id}")
        if row.status in {"approved_for_manual_kdp_action", "rejected"}:
            raise ValueError("A reviewed terminal candidate cannot be changed; create a new candidate")
        if domain == "metadata":
            checks = json.loads(row.metadata_checks_json or "{}")
            before = checks.get(key, {})
            checks[key] = {"status": decision, "evidence_reference": evidence_reference.strip(),
                "rationale": rationale.strip(), "reviewer": reviewer.strip(), "value": value}
            row.metadata_checks_json = json.dumps(checks)
        elif domain == "kdp":
            checks = json.loads(row.kdp_checks_json or "{}")
            before = checks.get(key, {})
            checks[key] = {"status": decision, "evidence_reference": evidence_reference.strip(),
                "rationale": rationale.strip(), "reviewer": reviewer.strip()}
            row.kdp_checks_json = json.dumps(checks)
        else:
            before = json.loads(row.ai_disclosure_json or "{}")
            row.ai_disclosure_json = json.dumps({"status": decision, "statement": statement,
                "evidence_reference": evidence_reference.strip(), "rationale": rationale.strip(),
                "reviewer": reviewer.strip()})
        after = (json.loads(row.metadata_checks_json or "{}").get(key, {}) if domain == "metadata"
                 else json.loads(row.kdp_checks_json or "{}").get(key, {}) if domain == "kdp"
                 else json.loads(row.ai_disclosure_json or "{}"))
        current_blockers = _blockers(session, row)
        row.status = "blocked" if current_blockers else "pending_human_review"
        AuditEventWriter.append(session, actor_id=reviewer.strip(), action="release.candidate.check_recorded",
            entity_type="release_candidate", entity_id=candidate_id, correlation_id=row.title_id,
            result="success", before_hash=sha256_bytes(canonical_json_bytes(before)),
            after_hash=sha256_bytes(canonical_json_bytes(after)),
            metadata={"domain": domain, "key": key, "decision": decision,
                "rationale": rationale.strip(), "evidence_reference": evidence_reference.strip(),
                "blocker_count": len(current_blockers)})
        session.commit()
        return row


def review_release_candidate(root: Path, candidate_id: str, *, decision: str,
                             reviewer: str, rationale: str) -> tuple[ReleaseCandidateRow, ApprovalRow | None]:
    if decision not in _REVIEW_DECISIONS or not reviewer.strip() or not rationale.strip():
        raise ValueError("Release review requires a supported decision, reviewer, and rationale")
    with session_scope(root) as session:
        row = session.get(ReleaseCandidateRow, candidate_id)
        if row is None:
            raise ValueError(f"Unknown release candidate: {candidate_id}")
        if row.status in {"approved_for_manual_kdp_action", "rejected"}:
            raise ValueError("Release candidate has already reached a terminal review state")
        blockers = _blockers(session, row)
        if decision == "approve" and blockers:
            row.status = "blocked"
            AuditEventWriter.append(session, actor_id=reviewer.strip(), action="release.candidate.approval_blocked",
                entity_type="release_candidate", entity_id=candidate_id, correlation_id=row.title_id,
                result="blocked", metadata={"blocker_count": len(blockers),
                    "blocker_types": sorted({item.get("type", "unknown") for item in blockers})})
            session.commit()
            return row, None
        approval_decision = {"approve": "accepted", "hold": "held", "reject": "rejected"}[decision]
        status = {"approve": "approved_for_manual_kdp_action", "hold": "held", "reject": "rejected"}[decision]
        approval = ApprovalRow(approval_id=new_id("APR"), title_id=row.title_id, asset_id=None,
            scope="release_candidate", candidate_hash=_review_hash(row), approver=reviewer.strip(),
            decision=approval_decision, conditions_json=json.dumps([_MANUAL_PUBLICATION_CONDITION]),
            created_at=utcnow())
        row.status = status
        session.add(approval)
        AuditEventWriter.append(session, actor_id=reviewer.strip(), action="release.candidate.reviewed",
            entity_type="release_candidate", entity_id=candidate_id, correlation_id=row.title_id,
            result=approval_decision, metadata={"approval_id": approval.approval_id,
                "decision": decision, "rationale": rationale.strip(),
                "final_kdp_action_manual": True})
        session.commit()
        return row, approval


def export_release_packet(root: Path, candidate_id: str, *, creator: str) -> tuple[ReleasePacketRow, AssetRow]:
    if not creator.strip():
        raise ValueError("Packet creator is required")
    with session_scope(root) as session:
        candidate = session.get(ReleaseCandidateRow, candidate_id)
        if candidate is None:
            raise ValueError(f"Unknown release candidate: {candidate_id}")
        title = session.get(TitleRow, candidate.title_id)
        approval = session.scalar(select(ApprovalRow).where(ApprovalRow.title_id == candidate.title_id,
            ApprovalRow.scope == "release_candidate", ApprovalRow.candidate_hash == _review_hash(candidate),
            ApprovalRow.decision == "accepted"))
        blockers = _blockers(session, candidate)
        packet_id = new_id("PKT")
        packet = {"packet_id": packet_id, "candidate_id": candidate_id,
            "candidate_sha256": candidate.candidate_sha256, "title_id": candidate.title_id,
            "working_title": title.working_title, "build_id": candidate.build_id,
            "frozen_input_assets": json.loads(candidate.frozen_inputs_json or "[]"),
            "metadata": json.loads(candidate.frozen_metadata_json or "{}"),
            "metadata_checks": json.loads(candidate.metadata_checks_json or "{}"),
            "rights_and_provenance_summary": json.loads(candidate.rights_summary_json or "{}"),
            "ai_use_summary": json.loads(candidate.ai_use_summary_json or "{}"),
            "ai_use_disclosure": json.loads(candidate.ai_disclosure_json or "{}"),
            "kdp_human_checklist": {"source_policy": "Verify current requirements against official KDP documentation.",
                "checks": json.loads(candidate.kdp_checks_json or "{}")},
            "unresolved_blockers": blockers, "review_status": candidate.status,
            "approval_id": approval.approval_id if approval else None,
            "final_kdp_action_manual": True, "created_by": creator.strip(),
            "created_at": utcnow().isoformat()}
        path = root / "projects" / title.project_id / "titles" / candidate.title_id / "11_release" / "candidates" / candidate_id / f"packet-{packet_id}.json"
    write_json(path, packet)
    digest = sha256_file(path)
    with session_scope(root) as session:
        asset = AssetRow(asset_id=new_id("AST"), title_id=packet["title_id"],
            asset_type="release.packet", path=str(path.resolve()), version="1.0",
            sha256=digest, creator_type="system", creator=creator.strip(),
            source_ref=candidate_id, approval_status="experimental", created_at=utcnow())
        row = ReleasePacketRow(packet_id=packet_id, candidate_id=candidate_id,
            title_id=packet["title_id"], asset_id=asset.asset_id, sha256=digest,
            blockers_json=json.dumps(blockers), created_by=creator.strip(), created_at=utcnow())
        session.add_all([asset, row])
        AuditEventWriter.append(session, actor_id=creator.strip(), action="release.packet.exported",
            entity_type="release_packet", entity_id=packet_id, correlation_id=packet["title_id"],
            result="success", after_hash=digest, metadata={"candidate_id": candidate_id,
                "asset_id": asset.asset_id, "blocker_count": len(blockers)})
        session.commit()
        return row, asset
