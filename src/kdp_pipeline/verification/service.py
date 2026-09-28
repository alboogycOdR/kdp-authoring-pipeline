from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy import select

from kdp_pipeline.core.ids import new_id
from kdp_pipeline.storage.audit import AuditEventWriter
from kdp_pipeline.storage.db import (
    ApprovalRow,
    AssetRow,
    RightsLogRow,
    TitleRow,
    VerificationItemRow,
    utcnow,
)
from kdp_pipeline.storage.files import sha256_file
from kdp_pipeline.storage.service import session_scope


_SCRIPTURE_PLACEHOLDER = re.compile(r"\[SCRIPTURE NEEDED\]", re.IGNORECASE)
_FLAG_KINDS = {"source_claim", "research", "expert_review", "sensitivity"}
_ITEM_DECISIONS = {"verified", "not_verified", "not_applicable"}
_RIGHTS_DECISIONS = {"cleared", "restricted", "not_applicable"}


def _accepted_chapter_number(path: Path) -> int | None:
    match = re.search(r"chapter-(\d{3})\.md$", path.name, re.IGNORECASE)
    return int(match.group(1)) if match else None


def scan_scripture_placeholders(root: Path, title_id: str) -> dict[str, object]:
    """Queue exact Scripture placeholders found in integrity-checked accepted chapters."""
    created: list[str] = []
    existing: list[str] = []
    with session_scope(root) as session:
        if session.get(TitleRow, title_id) is None:
            raise ValueError(f"Unknown title: {title_id}")
        assets = list(session.scalars(select(AssetRow).where(
            AssetRow.title_id == title_id,
            AssetRow.asset_type == "chapter.accepted",
            AssetRow.approval_status == "accepted",
        )))
        for asset in assets:
            path = Path(asset.path)
            approval = session.scalar(select(ApprovalRow).where(
                ApprovalRow.asset_id == asset.asset_id, ApprovalRow.decision == "accepted"))
            chapter_number = _accepted_chapter_number(path)
            if approval is None or chapter_number is None:
                continue
            if not path.is_file() or sha256_file(path) != asset.sha256:
                raise ValueError(f"Accepted chapter failed integrity check: {asset.asset_id}")
            text = path.read_text(encoding="utf-8")
            for match in _SCRIPTURE_PLACEHOLDER.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                locator = f"chapter-{chapter_number:03d}:line-{line:04d}"
                item = session.scalar(select(VerificationItemRow).where(
                    VerificationItemRow.asset_id == asset.asset_id,
                    VerificationItemRow.kind == "scripture",
                    VerificationItemRow.locator == locator,
                    VerificationItemRow.exact_text == match.group(0),
                ))
                if item is not None:
                    existing.append(item.verification_id)
                    continue
                item = VerificationItemRow(
                    verification_id=new_id("VRF"), title_id=title_id, asset_id=asset.asset_id,
                    kind="scripture", locator=locator, exact_text=match.group(0), status="pending",
                    created_at=utcnow(),
                )
                session.add(item)
                AuditEventWriter.append(session, actor_id="system", action="verification.scripture_placeholder.queued",
                    entity_type="verification_item", entity_id=item.verification_id,
                    correlation_id=title_id, result="success", metadata={"asset_id": asset.asset_id,
                        "locator": locator, "placeholder": match.group(0), "verse_text_inserted": False})
                created.append(item.verification_id)
        session.commit()
    return {"created": created, "existing": existing, "created_count": len(created), "existing_count": len(existing)}


def add_verification_flag(root: Path, *, title_id: str, kind: str, locator: str,
                          exact_text: str, reviewer: str, asset_id: str | None = None) -> VerificationItemRow:
    if kind not in _FLAG_KINDS or not locator.strip() or not exact_text.strip() or not reviewer.strip():
        raise ValueError("A supported flag kind, locator, text, and reviewer are required")
    with session_scope(root) as session:
        if session.get(TitleRow, title_id) is None:
            raise ValueError(f"Unknown title: {title_id}")
        if asset_id is not None:
            asset = session.get(AssetRow, asset_id)
            if asset is None or asset.title_id != title_id:
                raise ValueError("Verification source asset must belong to the title")
        row = VerificationItemRow(verification_id=new_id("VRF"), title_id=title_id, asset_id=asset_id,
            kind=kind, locator=locator.strip(), exact_text=exact_text.strip(), status="pending",
            reviewer=reviewer.strip(), created_at=utcnow())
        session.add(row)
        AuditEventWriter.append(session, actor_id=reviewer, action="verification.flag.created",
            entity_type="verification_item", entity_id=row.verification_id,
            correlation_id=title_id, result="success", metadata={"kind": kind, "locator": locator.strip()})
        session.commit()
        return row


def decide_verification(root: Path, verification_id: str, *, decision: str, reviewer: str,
                        rationale: str, evidence_reference: str | None = None,
                        proposed_reference: str | None = None,
                        source_policy: str | None = None) -> VerificationItemRow:
    if decision not in _ITEM_DECISIONS or not reviewer.strip() or not rationale.strip():
        raise ValueError("A supported decision, reviewer, and rationale are required")
    if decision == "verified" and not evidence_reference:
        raise ValueError("Verified decisions require an evidence reference")
    with session_scope(root) as session:
        row = session.get(VerificationItemRow, verification_id)
        if row is None:
            raise ValueError(f"Unknown verification item: {verification_id}")
        if row.kind == "scripture" and decision == "verified":
            citation = proposed_reference or row.proposed_reference
            if not citation or not source_policy:
                raise ValueError("Scripture verification requires an exact reference and translation/source policy")
            row.proposed_reference = citation.strip()
            row.source_policy = source_policy.strip()
        elif proposed_reference is not None:
            row.proposed_reference = proposed_reference.strip()
        if source_policy is not None:
            row.source_policy = source_policy.strip()
        row.status = decision
        row.evidence_reference = evidence_reference.strip() if evidence_reference else None
        row.rationale = rationale.strip()
        row.reviewer = reviewer.strip()
        row.reviewed_at = utcnow()
        AuditEventWriter.append(session, actor_id=reviewer, action="verification.item.decided",
            entity_type="verification_item", entity_id=row.verification_id,
            correlation_id=row.title_id, result="success", metadata={"kind": row.kind,
                "decision": decision, "evidence_reference_present": bool(evidence_reference),
                "scripture_text_inserted": False})
        session.commit()
        return row


def record_rights(root: Path, *, title_id: str, material_type: str, description: str,
                  reviewer: str, asset_id: str | None = None, source: str | None = None,
                  provenance_reference: str | None = None,
                  legal_basis: str | None = None, evidence_reference: str | None = None,
                  territories: list[str] | None = None, term: str | None = None,
                  restrictions: str | None = None) -> RightsLogRow:
    if not material_type.strip() or not description.strip() or not reviewer.strip():
        raise ValueError("Rights records require material type, description, and reviewer")
    with session_scope(root) as session:
        if session.get(TitleRow, title_id) is None:
            raise ValueError(f"Unknown title: {title_id}")
        if asset_id is not None:
            asset = session.get(AssetRow, asset_id)
            if asset is None or asset.title_id != title_id:
                raise ValueError("Rights record asset must belong to the title")
        row = RightsLogRow(rights_record_id=new_id("RGT"), title_id=title_id, asset_id=asset_id,
            material_type=material_type.strip(), description=description.strip(), source=source,
            provenance_reference=provenance_reference, legal_basis=legal_basis,
            evidence_reference=evidence_reference,
            territories_json=json.dumps(territories or []), term=term, restrictions=restrictions,
            status="pending", reviewer=reviewer.strip(), created_at=utcnow())
        session.add(row)
        AuditEventWriter.append(session, actor_id=reviewer, action="rights.record.created",
            entity_type="rights_record", entity_id=row.rights_record_id,
            correlation_id=title_id, result="success", metadata={"material_type": row.material_type,
                "asset_id": asset_id})
        session.commit()
        return row


def decide_rights_record(root: Path, rights_record_id: str, *, decision: str,
                         reviewer: str, rationale: str) -> RightsLogRow:
    if decision not in _RIGHTS_DECISIONS or not reviewer.strip() or not rationale.strip():
        raise ValueError("A supported rights decision, reviewer, and rationale are required")
    with session_scope(root) as session:
        row = session.get(RightsLogRow, rights_record_id)
        if row is None:
            raise ValueError(f"Unknown rights record: {rights_record_id}")
        if decision == "cleared" and (not row.legal_basis or not row.evidence_reference):
            raise ValueError("Rights clearance requires a recorded legal basis and evidence reference")
        row.status = decision
        row.reviewer = reviewer.strip()
        row.rationale = rationale.strip()
        row.reviewed_at = utcnow()
        AuditEventWriter.append(session, actor_id=reviewer, action="rights.record.decided",
            entity_type="rights_record", entity_id=row.rights_record_id,
            correlation_id=row.title_id, result="success", metadata={"decision": decision,
                "asset_id": row.asset_id, "evidence_reference_present": bool(row.evidence_reference)})
        session.commit()
        return row
