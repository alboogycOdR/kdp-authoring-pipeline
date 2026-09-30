from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from kdp_pipeline.context import ContextInput, ContextManifest
from kdp_pipeline.core.hashing import sha256_bytes
from kdp_pipeline.core.ids import new_id
from kdp_pipeline.models.canon import CanonProposalStatus
from kdp_pipeline.models.planning import PlanningArtifactKind, spec_for
from kdp_pipeline.providers import ModelProvider
from kdp_pipeline.prompts import PromptRegistry
from kdp_pipeline.generation import GenerationRunResult, GenerationService
from kdp_pipeline.storage.audit import AuditEventWriter
from kdp_pipeline.storage.db import (ApprovalRow, AssetRow, CanonProposalRow, EditorialFindingRow,
                                     JobRow, TitleRow, utcnow)
from kdp_pipeline.storage.files import sha256_file, write_json
from kdp_pipeline.storage.service import session_scope


EMPTY_CANON_NOTE = (
    "No established canon/continuity baseline exists yet; treat this chapter as a candidate starting point "
    "and assess alignment against accepted planning artefacts."
)
REQUIRED_FIELDS = {
    "status": str, "supplied_context_confirmed": bool,
    "alignment_with_positioning": str, "alignment_with_book_brief": str,
    "alignment_with_outline": str, "alignment_with_chapter_card": str,
    "canon_baseline_assessment": str, "scripture_and_claims_check": str,
    "prosperity_or_outcome_promise_check": str, "audience_consistency_check": str,
    "continuity_findings": list, "canon_proposal_recommendation": str,
    "required_followups": list,
}


class ContinuityOutputInvalid(ValueError):
    """Raised when a provider response cannot be used as continuity analysis."""


@dataclass(frozen=True)
class ContinuityRunResult:
    generation: GenerationRunResult
    finding: EditorialFindingRow | None
    proposal: CanonProposalRow | None
    validity_status: str = "valid"


def _read_asset(asset: AssetRow, *, role: str) -> tuple[str, ContextInput]:
    path = Path(asset.path)
    if not path.is_file() or sha256_file(path) != asset.sha256:
        raise ValueError(f"Required continuity context is missing or has a hash mismatch: {asset.asset_id}")
    return path.read_text(encoding="utf-8"), ContextInput(
        input_ref=asset.asset_id, sha256=asset.sha256, context_tier="A", role=role,
    )


def _accepted_asset(session, title_id: str, kind: PlanningArtifactKind, chapter_number: int | None = None) -> AssetRow:
    spec = spec_for(kind)
    rows = session.scalars(select(AssetRow).where(
        AssetRow.title_id == title_id, AssetRow.asset_type == spec.asset_type,
        AssetRow.approval_status == "accepted",
    ))
    for asset in rows:
        if chapter_number is not None and Path(asset.path).name != f"chapter-{chapter_number:03d}.md":
            continue
        approval = session.scalar(select(ApprovalRow).where(
            ApprovalRow.asset_id == asset.asset_id, ApprovalRow.decision == "accepted",
        ))
        if approval is not None:
            return asset
    raise ValueError(f"Accepted {kind.value} context not found" + (f" for chapter {chapter_number}" if chapter_number else ""))


def _continuity_context(root: Path, session, title: TitleRow, source: AssetRow, chapter_number: int):
    if source.asset_type not in {"chapter.draft", "chapter.revision"}:
        raise ValueError("Continuity source must be a chapter draft or revision")
    source_text, source_input = _read_asset(source, role="target_chapter_draft")
    sections = [f"## Target chapter draft (asset {source.asset_id})\n{source_text}"]
    inputs = [source_input]
    labels = (
        (PlanningArtifactKind.POSITIONING, "accepted_positioning"),
        (PlanningArtifactKind.BOOK_BRIEF, "accepted_book_brief"),
        (PlanningArtifactKind.OUTLINE, "accepted_outline"),
        (PlanningArtifactKind.CHAPTER_CARD, "accepted_chapter_card"),
    )
    for kind, role in labels:
        asset = _accepted_asset(session, title.title_id, kind, chapter_number if kind == PlanningArtifactKind.CHAPTER_CARD else None)
        content, input_ref = _read_asset(asset, role=role)
        inputs.append(input_ref)
        sections.append(f"## {role.replace('_', ' ').title()} (asset {asset.asset_id})\n{content}")

    title_root = root / "projects" / title.project_id / "titles" / title.title_id
    canon_sections = []
    for relative in ("06_canon/continuity-ledger.json", "06_canon/entities.json", "06_canon/unresolved.json"):
        path = title_root / relative
        if not path.is_file():
            continue
        raw = path.read_bytes()
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Canon baseline is unreadable: {relative}") from exc
        inputs.append(ContextInput(input_ref=relative, sha256=sha256_bytes(raw), context_tier="B", role="canon_baseline"))
        canon_sections.append(f"### {relative}\n```json\n{json.dumps(value, ensure_ascii=False, indent=2)}\n```")
    if not canon_sections or all(_is_empty_canon(item) for item in canon_sections):
        canon_text = EMPTY_CANON_NOTE
    else:
        canon_text = "Established canon/continuity baseline follows. Treat it as the existing reference state:\n\n" + "\n\n".join(canon_sections)
    sections.append("## Canon/continuity baseline\n" + canon_text)
    manifest = ContextManifest(title_id=title.title_id, task_type=f"chapter.continuity.{chapter_number}", inputs=inputs)
    return manifest, "\n\n".join(sections)


def _is_empty_canon(section: str) -> bool:
    try:
        value = json.loads(section.split("```json\n", 1)[1].split("\n```", 1)[0])
    except (IndexError, json.JSONDecodeError):
        return False
    return not any(value.values()) if isinstance(value, dict) else not bool(value)


def _validate_output(text: str) -> dict:
    stripped = text.strip()
    if not stripped:
        raise ContinuityOutputInvalid("empty continuity output")
    folded = stripped.casefold()
    requests_missing_context = re.search(
        r"\b(please|kindly|send|provide|supply|resend|attach|upload)\b.{0,60}"
        r"\b(chapter(?:/entry)?(?: text)?|draft(?: text)?|context|positioning|book brief|outline|chapter card|canon baseline)\b",
        folded, re.DOTALL,
    )
    declares_missing_context = re.search(
        r"\b(missing|not supplied|unavailable|lack(?:ing)?)\b.{0,50}"
        r"\b(required )?(chapter|draft|context|positioning|book brief|outline|chapter card|canon baseline)\b",
        folded, re.DOTALL,
    )
    explicit_refusal = any(phrase in folded for phrase in (
        "i don't have the chapter", "i do not have the chapter", "send the materials", "context is missing",
    ))
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as exc:
        if requests_missing_context or declares_missing_context or explicit_refusal:
            raise ContinuityOutputInvalid("continuity output says required context is missing") from exc
        raise ContinuityOutputInvalid("continuity output is not valid JSON") from exc
    # Inside a valid JSON contract, words like "missing ... outline" are usually genuine findings
    # ("the draft is missing the outline's second beat"); only explicit requests for materials,
    # or a refusal, invalidate the analysis (KDP-AUD-011).
    if explicit_refusal or (requests_missing_context and not (isinstance(value, dict)
                                                              and value.get("supplied_context_confirmed") is True)):
        raise ContinuityOutputInvalid("continuity output says required context is missing")
    if not isinstance(value, dict):
        raise ContinuityOutputInvalid("continuity output must be a JSON object")
    missing = [key for key in REQUIRED_FIELDS if key not in value or not isinstance(value[key], REQUIRED_FIELDS[key])]
    if missing:
        raise ContinuityOutputInvalid("continuity output is missing required fields: " + ", ".join(sorted(missing)))
    if value["status"] not in {"pass", "review", "fail"}:
        raise ContinuityOutputInvalid("continuity output has an invalid status")
    if value["supplied_context_confirmed"] is not True:
        raise ContinuityOutputInvalid("continuity output did not confirm supplied context")
    return value


class ContinuityService:
    @staticmethod
    async def analyze(root: Path, *, title_id: str, chapter_number: int, source_asset_id: str,
                      provider: ModelProvider | None = None) -> ContinuityRunResult:
        with session_scope(root) as session:
            title = session.get(TitleRow, title_id)
            source = session.get(AssetRow, source_asset_id)
            if title is None or source is None or source.title_id != title_id:
                raise ValueError("Unknown title or source chapter asset")
            if title.status != "DRAFTING":
                raise ValueError("Continuity analysis requires DRAFTING state")
            if source.approval_status != "experimental":
                raise ValueError("Continuity analysis requires an experimental chapter asset")
            manifest, context_text = _continuity_context(root, session, title, source, chapter_number)
            title_values = {"title_id": title_id, "working_title": title.working_title,
                            "chapter_number": str(chapter_number), "continuity_context": context_text}
        prompt = PromptRegistry(root / "prompts").render("continuity/chapter-continuity", title_values)
        generation = await GenerationService.generate(
            root, title_id=title_id, task_type=f"chapter.continuity.{chapter_number}",
            rendered_prompt=prompt, context_manifest=manifest, provider=provider,
            system_instructions="Analyze the supplied continuity context. Do not ask for materials already included. Return only the required JSON object.",
            max_output_tokens=2400 if provider is not None else None,
            temperature=0 if provider is not None else None, asset_type="analysis.continuity",
            source_ref=source_asset_id, metadata={"chapter_number": chapter_number, "source_asset_id": source_asset_id},
        )
        try:
            _validate_output(generation.generation_result.text)
        except ContinuityOutputInvalid as exc:
            with session_scope(root) as session:
                job = session.get(JobRow, generation.job.job_id)
                if job is not None:
                    job.status = "failed"
                    job.error = f"Continuity output rejected as unusable: {exc}"[:500]
                    job.completed_at = utcnow()
                AuditEventWriter.append(session, actor_id="system", action="continuity.output.rejected",
                    entity_type="job", entity_id=generation.job.job_id, correlation_id=generation.job.job_id,
                    result="failed", metadata={"reason": str(exc), "analysis_asset_id": generation.asset.asset_id,
                                                "usage_preserved": True})
                session.commit()
            raise ContinuityOutputInvalid(str(exc)) from exc

        with session_scope(root) as session:
            AuditEventWriter.append(session, actor_id="system", action="continuity.output.validated",
                entity_type="job", entity_id=generation.job.job_id, correlation_id=generation.job.job_id,
                result="success", metadata={"analysis_asset_id": generation.asset.asset_id,
                    "context_manifest_hash": manifest.manifest_hash,
                    "context_asset_ids": [item.input_ref for item in manifest.inputs if item.input_ref.startswith("AST-")],
                    "required_context_included": True, "output_contract_valid": True})
            session.commit()

        with session_scope(root) as session:
            existing_finding = session.scalar(select(EditorialFindingRow).where(
                EditorialFindingRow.asset_id == generation.asset.asset_id, EditorialFindingRow.pass_type == "continuity"))
            if existing_finding is not None:
                proposal = session.scalar(select(CanonProposalRow).where(CanonProposalRow.finding_id == existing_finding.finding_id))
                if proposal is not None:
                    session.commit()
                    return ContinuityRunResult(generation, existing_finding, proposal)
            finding = EditorialFindingRow(
                finding_id=new_id("FND"), title_id=title_id, asset_id=generation.asset.asset_id,
                pass_type="continuity", severity="review", location=f"chapter-{chapter_number:03d}",
                description=generation.generation_result.text, evidence=generation.generation_result.text,
                recommended_action="Review the structured continuity findings before deciding on canon changes.",
                status="open", created_at=utcnow())
            proposal = CanonProposalRow(
                proposal_id=new_id("CAN"), title_id=title_id, finding_id=finding.finding_id,
                entity_id=f"chapter-{chapter_number:03d}", field="continuity_review",
                proposed_value=generation.generation_result.text,
                reason="Valid structured continuity analysis produced a review item; no canon mutation is performed.",
                evidence_asset_ids_json=json.dumps([source_asset_id]), affected_assets_json=json.dumps([source_asset_id]),
                status=CanonProposalStatus.PROPOSED.value, created_at=utcnow())
            finding.snapshot_path = str(root / "projects" / title.project_id / "titles" / title_id / "07_editorial" / "findings" / f"{finding.finding_id}.json")
            proposal.snapshot_path = str(root / "projects" / title.project_id / "titles" / title_id / "06_canon" / "proposals" / f"{proposal.proposal_id}.json")
            session.add_all([finding, proposal])
            AuditEventWriter.append(session, actor_id="system", action="continuity.finding.created", entity_type="finding",
                entity_id=finding.finding_id, correlation_id=generation.job.job_id, result="success",
                metadata={"analysis_asset_id": generation.asset.asset_id, "source_asset_id": source_asset_id})
            AuditEventWriter.append(session, actor_id="system", action="canon.proposal.created", entity_type="canon_proposal",
                entity_id=proposal.proposal_id, correlation_id=generation.job.job_id, result="success",
                metadata={"finding_id": finding.finding_id, "status": proposal.status})
            session.commit()
            finding_data = {"finding_id": finding.finding_id, "title_id": title_id, "asset_id": source_asset_id,
                            "pass_type": finding.pass_type, "severity": finding.severity, "location": finding.location,
                            "description": finding.description, "status": finding.status}
            proposal_data = {"proposal_id": proposal.proposal_id, "title_id": title_id, "finding_id": finding.finding_id,
                             "entity_id": proposal.entity_id, "field": proposal.field, "proposed_value": proposal.proposed_value,
                             "reason": proposal.reason, "status": proposal.status, "evidence_asset_ids": [source_asset_id]}
        write_json(Path(finding.snapshot_path), finding_data)
        write_json(Path(proposal.snapshot_path), proposal_data)
        return ContinuityRunResult(generation, finding, proposal)


def supersede_canon_proposal(root: Path, proposal_id: str, *, reason: str) -> CanonProposalRow:
    """Auditable transition for a proposed canon item invalidated by later review."""
    if not reason.strip():
        raise ValueError("reason is required")
    with session_scope(root) as session:
        proposal = session.get(CanonProposalRow, proposal_id)
        if proposal is None:
            raise ValueError(f"Unknown canon proposal: {proposal_id}")
        if proposal.status != CanonProposalStatus.PROPOSED.value:
            raise ValueError("Only proposed canon proposals can be superseded")
        proposal.status = CanonProposalStatus.SUPERSEDED.value
        proposal.reason = reason
        AuditEventWriter.append(session, actor_id="system", action="canon.proposal.superseded", entity_type="canon_proposal",
            entity_id=proposal_id, correlation_id=proposal.title_id, result="success",
            metadata={"reason": reason, "canon_mutated": False})
        session.commit()
        data = {"proposal_id": proposal.proposal_id, "title_id": proposal.title_id, "finding_id": proposal.finding_id,
                "entity_id": proposal.entity_id, "field": proposal.field, "proposed_value": proposal.proposed_value,
                "reason": proposal.reason, "status": proposal.status}
        snapshot = Path(proposal.snapshot_path) if proposal.snapshot_path else None
    if snapshot:
        write_json(snapshot, data)
    return proposal


def approve_canon_proposal(root: Path, proposal_id: str, *, reviewer: str, decision: str) -> CanonProposalRow:
    decision = decision.lower()
    if decision not in {CanonProposalStatus.ACCEPTED.value, CanonProposalStatus.REJECTED.value}:
        raise ValueError("Canon proposal decision must be accepted or rejected")
    if not reviewer.strip():
        raise ValueError("reviewer is required")
    with session_scope(root) as session:
        proposal = session.get(CanonProposalRow, proposal_id)
        if proposal is None:
            raise ValueError(f"Unknown canon proposal: {proposal_id}")
        if proposal.status != CanonProposalStatus.PROPOSED.value:
            raise ValueError("Only proposed canon proposals can be decided")
        proposal.status = decision
        proposal.reviewer = reviewer
        proposal.reviewed_at = utcnow()
        AuditEventWriter.append(session, actor_id=reviewer, action="canon.proposal.decided", entity_type="canon_proposal", entity_id=proposal_id,
                                correlation_id=proposal.title_id, result="success", metadata={"decision": decision, "canon_mutated": False})
        session.commit()
        data = {"proposal_id": proposal.proposal_id, "title_id": proposal.title_id, "finding_id": proposal.finding_id,
                "entity_id": proposal.entity_id, "field": proposal.field, "proposed_value": proposal.proposed_value,
                "reason": proposal.reason, "status": proposal.status, "reviewer": reviewer,
                "reviewed_at": proposal.reviewed_at.isoformat() if proposal.reviewed_at else None}
        snapshot = Path(proposal.snapshot_path) if proposal.snapshot_path else None
    if snapshot:
        write_json(snapshot, data)
    return proposal
