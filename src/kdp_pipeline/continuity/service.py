from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from kdp_pipeline.chapter.service import _planning_context
from kdp_pipeline.core.ids import new_id
from kdp_pipeline.models.canon import CanonProposalStatus
from kdp_pipeline.providers import ModelProvider
from kdp_pipeline.prompts import PromptRegistry
from kdp_pipeline.generation import GenerationRunResult, GenerationService
from kdp_pipeline.storage.audit import AuditEventWriter
from kdp_pipeline.storage.db import AssetRow, CanonProposalRow, EditorialFindingRow, TitleRow, utcnow
from kdp_pipeline.storage.files import write_json
from kdp_pipeline.storage.service import session_scope


@dataclass(frozen=True)
class ContinuityRunResult:
    generation: GenerationRunResult
    finding: EditorialFindingRow
    proposal: CanonProposalRow


class ContinuityService:
    @staticmethod
    async def analyze(
        root: Path,
        *,
        title_id: str,
        chapter_number: int,
        source_asset_id: str,
        provider: ModelProvider | None = None,
    ) -> ContinuityRunResult:
        with session_scope(root) as session:
            title = session.get(TitleRow, title_id)
            source = session.get(AssetRow, source_asset_id)
            if title is None or source is None or source.title_id != title_id:
                raise ValueError("Unknown title or source chapter asset")
            if title.status != "DRAFTING":
                raise ValueError("Continuity analysis requires DRAFTING state")
            if source.approval_status != "experimental":
                raise ValueError("Continuity analysis requires an experimental chapter asset")
            manifest = _planning_context(session, title_id, source, chapter_number)
            title_values = {
                "title_id": title_id,
                "working_title": title.working_title,
                "chapter_number": str(chapter_number),
            }
        prompt = PromptRegistry(root / "prompts").render("continuity/chapter-continuity", title_values)
        generation = await GenerationService.generate(
            root, title_id=title_id, task_type=f"chapter.continuity.{chapter_number}",
            rendered_prompt=prompt, context_manifest=manifest, provider=provider,
            system_instructions="Identify continuity conflicts and separate observed evidence from proposed canon changes.",
            max_output_tokens=1200 if provider is not None else None,
            temperature=0 if provider is not None else None, asset_type="analysis.continuity",
            source_ref=source_asset_id, metadata={"chapter_number": chapter_number, "source_asset_id": source_asset_id},
        )
        with session_scope(root) as session:
            existing_finding = session.scalar(select(EditorialFindingRow).where(
                EditorialFindingRow.asset_id == generation.asset.asset_id,
                EditorialFindingRow.pass_type == "continuity",
            ))
            if existing_finding is not None:
                existing_proposal = session.scalar(select(CanonProposalRow).where(
                    CanonProposalRow.finding_id == existing_finding.finding_id,
                ))
                if existing_proposal is not None:
                    AuditEventWriter.append(
                        session, actor_id="system", action="continuity.reused", entity_type="finding",
                        entity_id=existing_finding.finding_id, correlation_id=generation.job.job_id, result="success",
                        metadata={"analysis_asset_id": generation.asset.asset_id, "proposal_id": existing_proposal.proposal_id},
                    )
                    session.commit()
                    return ContinuityRunResult(generation, existing_finding, existing_proposal)
            finding = EditorialFindingRow(
                finding_id=new_id("FND"), title_id=title_id, asset_id=generation.asset.asset_id,
                pass_type="continuity", severity="review", location=f"chapter-{chapter_number:03d}",
                description=generation.generation_result.text, evidence=generation.generation_result.text,
                recommended_action="Review the evidence and decide whether a canon proposal is warranted.",
                status="open", created_at=utcnow(),
            )
            proposal = CanonProposalRow(
                proposal_id=new_id("CAN"), title_id=title_id, finding_id=finding.finding_id,
                entity_id=f"chapter-{chapter_number:03d}", field="continuity_review",
                proposed_value=generation.generation_result.text,
                reason="Continuity analysis produced a proposed review item; no canon mutation is performed.",
                evidence_asset_ids_json=json.dumps([source_asset_id]), affected_assets_json=json.dumps([source_asset_id]),
                status=CanonProposalStatus.PROPOSED.value, created_at=utcnow(),
            )
            finding.snapshot_path = str(root / "projects" / title.project_id / "titles" / title_id / "07_editorial" / "findings" / f"{finding.finding_id}.json")
            proposal.snapshot_path = str(root / "projects" / title.project_id / "titles" / title_id / "06_canon" / "proposals" / f"{proposal.proposal_id}.json")
            session.add_all([finding, proposal])
            AuditEventWriter.append(session, actor_id="system", action="continuity.finding.created", entity_type="finding", entity_id=finding.finding_id,
                                    correlation_id=generation.job.job_id, result="success", metadata={"analysis_asset_id": generation.asset.asset_id, "source_asset_id": source_asset_id})
            AuditEventWriter.append(session, actor_id="system", action="canon.proposal.created", entity_type="canon_proposal", entity_id=proposal.proposal_id,
                                    correlation_id=generation.job.job_id, result="success", metadata={"finding_id": finding.finding_id, "status": proposal.status})
            session.commit()
            finding_data = {"finding_id": finding.finding_id, "title_id": title_id, "asset_id": source_asset_id, "pass_type": finding.pass_type,
                            "severity": finding.severity, "location": finding.location, "description": finding.description, "status": finding.status}
            proposal_data = {"proposal_id": proposal.proposal_id, "title_id": title_id, "finding_id": finding.finding_id,
                             "entity_id": proposal.entity_id, "field": proposal.field, "proposed_value": proposal.proposed_value,
                             "reason": proposal.reason, "status": proposal.status, "evidence_asset_ids": [source_asset_id]}
        write_json(Path(finding.snapshot_path), finding_data)
        write_json(Path(proposal.snapshot_path), proposal_data)
        return ContinuityRunResult(generation, finding, proposal)


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

