from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from kdp_pipeline.core.ids import new_id
from kdp_pipeline.models.planning import PlanningArtifactKind, spec_for
from kdp_pipeline.storage.audit import AuditEventWriter
from kdp_pipeline.storage.db import AssetRow, ApprovalRow, ProvenanceRow, ProjectRow, TitleRow, utcnow
from kdp_pipeline.storage.files import sha256_file
from kdp_pipeline.storage.service import planning_requirements_met, session_scope


class PlanningAcceptanceError(ValueError):
    pass


@dataclass(frozen=True)
class PlanningAcceptanceResult:
    source_asset: AssetRow
    accepted_asset: AssetRow
    approval: ApprovalRow
    destination_path: Path


def _kind_for_asset(asset_type: str) -> PlanningArtifactKind:
    for kind in PlanningArtifactKind:
        if spec_for(kind).asset_type == asset_type:
            return kind
    raise PlanningAcceptanceError(f"Asset is not a Sprint 3 planning artefact: {asset_type}")


def _destination(title: TitleRow, project: ProjectRow, root: Path, kind: PlanningArtifactKind, chapter_number: int | None) -> Path:
    spec = spec_for(kind)
    if kind == PlanningArtifactKind.CHAPTER_CARD:
        if chapter_number is None or chapter_number < 1:
            raise PlanningAcceptanceError("chapter_number is required for a chapter card")
        relative = spec.destination_template.format(chapter_number=chapter_number)
    else:
        if chapter_number is not None:
            raise PlanningAcceptanceError("chapter_number is only valid for a chapter card")
        relative = spec.destination_template
    return root / "projects" / project.project_id / "titles" / title.title_id / relative


def accept_planning_artifact(
    root: Path,
    asset_id: str,
    *,
    reviewer: str,
    chapter_number: int | None = None,
) -> PlanningAcceptanceResult:
    if not reviewer.strip():
        raise PlanningAcceptanceError("reviewer is required")
    destination: Path | None = None
    try:
        with session_scope(root) as session:
            source = session.get(AssetRow, asset_id)
            if source is None:
                raise PlanningAcceptanceError(f"Unknown asset: {asset_id}")
            if source.approval_status != "experimental":
                raise PlanningAcceptanceError("Only experimental planning assets can be accepted")
            kind = _kind_for_asset(source.asset_type)
            title = session.get(TitleRow, source.title_id)
            project = session.get(ProjectRow, title.project_id) if title else None
            if title is None or project is None:
                raise PlanningAcceptanceError("Planning asset has no valid title/project")
            source_path = Path(source.path)
            if not source_path.is_file():
                raise PlanningAcceptanceError(f"Experimental source file is missing: {source_path}")
            source_hash = sha256_file(source_path)
            if source_hash != source.sha256:
                raise PlanningAcceptanceError("Experimental source hash does not match its asset record")
            provenance = session.scalar(select(ProvenanceRow).where(ProvenanceRow.asset_id == source.asset_id))
            if provenance is None:
                raise PlanningAcceptanceError("Generated planning assets require provenance before acceptance")
            destination = _destination(title, project, root, kind, chapter_number)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
            destination_hash = sha256_file(destination)
            accepted = AssetRow(
                asset_id=new_id("AST"),
                title_id=source.title_id,
                asset_type=source.asset_type,
                path=str(destination.resolve()),
                version=source.version,
                sha256=destination_hash,
                creator_type=source.creator_type,
                creator=source.creator,
                source_ref=source.asset_id,
                ai_classification=source.ai_classification,
                approval_status="accepted",
                created_at=utcnow(),
            )
            approval = ApprovalRow(
                approval_id=new_id("APR"),
                title_id=source.title_id,
                asset_id=accepted.asset_id,
                scope=f"planning.{kind.value}",
                candidate_hash=destination_hash,
                approver=reviewer,
                decision="accepted",
                conditions_json="[]",
                created_at=utcnow(),
            )
            accepted_provenance = ProvenanceRow(
                provenance_id=new_id("PROV"),
                asset_id=accepted.asset_id,
                job_id=None,
                provider=provenance.provider,
                model=provenance.model,
                prompt_template_id=provenance.prompt_template_id,
                prompt_template_version=provenance.prompt_template_version,
                rendered_prompt_sha256=provenance.rendered_prompt_sha256,
                input_references_json=provenance.input_references_json,
                input_hashes_json=provenance.input_hashes_json,
                context_manifest_hash=provenance.context_manifest_hash,
                output_hash=destination_hash,
                generation_timestamp=provenance.generation_timestamp,
                human_contribution_note=provenance.human_contribution_note,
                ai_classification=provenance.ai_classification,
                disclosure_decision=provenance.disclosure_decision,
                reviewer=reviewer,
            )
            session.add(accepted)
            session.add(approval)
            session.add(accepted_provenance)
            AuditEventWriter.append(
                session,
                actor_id=reviewer,
                action="planning.approval.created",
                entity_type="approval",
                entity_id=approval.approval_id,
                correlation_id=source.title_id,
                result="success",
                before_hash=source.sha256,
                after_hash=destination_hash,
                metadata={"asset_id": accepted.asset_id, "source_asset_id": source.asset_id, "reviewer": reviewer},
            )
            AuditEventWriter.append(
                session,
                actor_id=reviewer,
                action="planning.accepted",
                entity_type="asset",
                entity_id=accepted.asset_id,
                correlation_id=source.title_id,
                result="success",
                before_hash=source.sha256,
                after_hash=destination_hash,
                metadata={
                    "source_asset_id": source.asset_id,
                    "source_path": str(source_path),
                    "destination_path": str(destination),
                    "approval_id": approval.approval_id,
                    "reviewer": reviewer,
                    "provenance_id": accepted_provenance.provenance_id,
                },
            )
            session.commit()
            return PlanningAcceptanceResult(source, accepted, approval, destination)
    except Exception:
        if destination is not None and destination.exists():
            destination.unlink()
        raise

