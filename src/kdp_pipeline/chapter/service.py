from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

from kdp_pipeline.context import ContextInput, ContextManifest
from kdp_pipeline.core.hashing import canonical_json_bytes, sha256_bytes
from kdp_pipeline.core.ids import new_id
from kdp_pipeline.core.state_machine import TitleState
from kdp_pipeline.generation import GenerationRunResult, GenerationService
from kdp_pipeline.models.chapter import ChapterAssetKind
from kdp_pipeline.models.planning import PlanningArtifactKind, spec_for
from kdp_pipeline.prompts import PromptRegistry
from kdp_pipeline.providers import ModelProvider
from kdp_pipeline.storage.audit import AuditEventWriter
from kdp_pipeline.storage.approval_conditions import normalize_approval_conditions
from kdp_pipeline.storage.db import (
    AssetRow,
    ApprovalRow,
    ChapterQueueRow,
    EditorialFindingRow,
    ProjectRow,
    ProvenanceRow,
    TitleRow,
    utcnow,
)
from kdp_pipeline.storage.files import sha256_file, write_json
from kdp_pipeline.storage.service import session_scope


_CHAPTER_CARD_NAME = re.compile(r"chapter-(?P<number>\d{3})\.md$")


class ChapterAcceptanceError(ValueError):
    pass


@dataclass(frozen=True)
class ChapterAcceptanceResult:
    source_asset: AssetRow
    accepted_asset: AssetRow
    approval: ApprovalRow
    destination_path: Path


_CHAPTER_NUMBER_FROM_SOURCE = re.compile(r"chapter\.(?:draft|revision|revise)\.(?P<number>\d{1,3})[-.]", re.IGNORECASE)


def _accepted_chapter_card(session, title_id: str, chapter_number: int) -> AssetRow | None:
    rows = session.scalars(select(AssetRow).where(
        AssetRow.title_id == title_id,
        AssetRow.asset_type == spec_for(PlanningArtifactKind.CHAPTER_CARD).asset_type,
        AssetRow.approval_status == "accepted",
    ))
    for asset in rows:
        match = _CHAPTER_CARD_NAME.search(Path(asset.path).name)
        approval = session.scalar(select(ApprovalRow).where(
            ApprovalRow.asset_id == asset.asset_id,
            ApprovalRow.decision == "accepted",
        ))
        if match and int(match.group("number")) == chapter_number and approval and Path(asset.path).is_file():
            if sha256_file(Path(asset.path)) == asset.sha256:
                return asset
    return None


def _planning_context(session, title_id: str, chapter_card: AssetRow, chapter_number: int) -> ContextManifest:
    refs = [chapter_card]
    for kind in (
        PlanningArtifactKind.POSITIONING,
        PlanningArtifactKind.BOOK_BRIEF,
        PlanningArtifactKind.OUTLINE,
    ):
        spec = spec_for(kind)
        candidate = session.scalar(select(AssetRow).where(
            AssetRow.title_id == title_id,
            AssetRow.asset_type == spec.asset_type,
            AssetRow.approval_status == "accepted",
        ))
        if candidate and Path(candidate.path).is_file() and sha256_file(Path(candidate.path)) == candidate.sha256:
            refs.append(candidate)
    return ContextManifest(
        title_id=title_id,
        task_type=f"chapter.{chapter_number}",
        inputs=[ContextInput(input_ref=asset.asset_id, sha256=asset.sha256, context_tier="A", role=asset.asset_type) for asset in refs],
    )


def _chapter_authoring_context(session, title_id: str, chapter_number: int,
                               manifest: ContextManifest) -> tuple[ContextManifest, str]:
    inputs = list(manifest.inputs)
    accepted = list(session.scalars(select(AssetRow).where(
        AssetRow.title_id == title_id, AssetRow.asset_type == ChapterAssetKind.ACCEPTED.value,
        AssetRow.approval_status == "accepted")))
    for chapter in accepted:
        match = _CHAPTER_CARD_NAME.search(Path(chapter.path).name)
        if not match or int(match.group("number")) >= chapter_number:
            continue
        number = int(match.group("number"))
        chapter_approval = session.scalar(select(ApprovalRow).where(
            ApprovalRow.asset_id == chapter.asset_id, ApprovalRow.decision == "accepted"))
        if chapter_approval is None or not Path(chapter.path).is_file() or sha256_file(Path(chapter.path)) != chapter.sha256:
            raise ValueError(f"Prior accepted chapter failed approval or integrity check: {chapter.asset_id}")
        summary = session.scalar(select(AssetRow).where(AssetRow.title_id == title_id,
            AssetRow.asset_type == "chapter.summary", AssetRow.source_ref == chapter.asset_id,
            AssetRow.approval_status == "accepted").order_by(AssetRow.created_at.desc()))
        if summary is None:
            raise ValueError(f"Accepted prior chapter {number} requires a reviewed context summary before drafting chapter {chapter_number}")
        approval = session.scalar(select(ApprovalRow).where(ApprovalRow.asset_id == summary.asset_id,
            ApprovalRow.decision == "accepted"))
        path = Path(summary.path)
        if approval is None or not path.is_file() or sha256_file(path) != summary.sha256:
            raise ValueError(f"Prior chapter summary is missing approval or failed integrity check: {summary.asset_id}")
        inputs.append(ContextInput(input_ref=summary.asset_id, sha256=summary.sha256,
                                   context_tier="A", role=f"prior_chapter_{number}_summary"))
    sections = []
    for item in inputs:
        asset = session.get(AssetRow, item.input_ref)
        if asset is None:
            finding = session.get(EditorialFindingRow, item.input_ref)
            if finding is not None and finding.title_id == title_id:
                sections.append(f"## Editorial finding {finding.finding_id}\n{finding.description}\nEvidence: {finding.evidence or ''}\nRecommended action: {finding.recommended_action or ''}")
            continue
        path = Path(asset.path)
        if not path.is_file() or sha256_file(path) != asset.sha256:
            raise ValueError(f"Authoring context file/hash integrity check failed: {asset.asset_id}")
        sections.append(f"## {item.role or asset.asset_type} (asset {asset.asset_id})\n{path.read_text(encoding='utf-8')}")
    return (ContextManifest(title_id=manifest.title_id, task_type=manifest.task_type, inputs=inputs),
            "\n\n".join(sections))


class ChapterService:
    @staticmethod
    async def draft(
        root: Path,
        *,
        title_id: str,
        chapter_number: int,
        provider: ModelProvider | None = None,
        variables: dict[str, Any] | None = None,
        max_output_tokens: int | None = None,
    ) -> GenerationRunResult:
        if chapter_number < 1:
            raise ValueError("chapter_number must be positive")
        with session_scope(root) as session:
            title = session.get(TitleRow, title_id)
            if title is None:
                raise ValueError(f"Unknown title: {title_id}")
            if title.status != TitleState.DRAFTING.value:
                raise ValueError("Chapter drafting requires an explicit PLANNED to DRAFTING transition")
            card = _accepted_chapter_card(session, title_id, chapter_number)
            if card is None:
                raise ValueError(f"Accepted chapter card not found for chapter {chapter_number}")
            context_manifest = _planning_context(session, title_id, card, chapter_number)
            context_manifest, chapter_context = _chapter_authoring_context(session, title_id, chapter_number, context_manifest)
            title_values = {
                "title_id": title_id,
                "working_title": title.working_title,
                "target_reader": title.target_reader or "unspecified",
                "chapter_number": str(chapter_number),
            }
        prompt = PromptRegistry(root / "prompts").render(
            "drafting/chapter-draft", {**title_values, "chapter_context": chapter_context, **(variables or {})}
        )
        return await GenerationService.generate(
            root,
            title_id=title_id,
            task_type=f"chapter.draft.{chapter_number}",
            rendered_prompt=prompt,
            context_manifest=context_manifest,
            provider=provider,
            system_instructions="Draft only the requested chapter using the supplied approved planning context.",
            max_output_tokens=max_output_tokens if max_output_tokens is not None else (2400 if provider is not None else None),
            temperature=0 if provider is not None else None,
            asset_type=ChapterAssetKind.DRAFT.value,
            metadata={"chapter_number": chapter_number, "chapter_card_asset_id": card.asset_id},
        )

    @staticmethod
    async def revise(
        root: Path,
        *,
        title_id: str,
        chapter_number: int,
        source_asset_id: str,
        provider: ModelProvider | None = None,
        finding_ids: list[str] | None = None,
        max_output_tokens: int | None = None,
    ) -> GenerationRunResult:
        with session_scope(root) as session:
            title = session.get(TitleRow, title_id)
            source = session.get(AssetRow, source_asset_id)
            if title is None or title.title_id != title_id:
                raise ValueError(f"Unknown title: {title_id}")
            if title.status != TitleState.DRAFTING.value:
                raise ValueError("Chapter revision requires DRAFTING state")
            if source is None or source.title_id != title_id or source.approval_status != "experimental":
                raise ValueError("Revision source must be an experimental chapter asset")
            source_path = Path(source.path)
            if not source_path.is_file() or sha256_file(source_path) != source.sha256:
                raise ValueError("Revision source file/hash integrity check failed")
            card = _accepted_chapter_card(session, title_id, chapter_number)
            if card is None:
                raise ValueError(f"Accepted chapter card not found for chapter {chapter_number}")
            context_manifest = _planning_context(session, title_id, card, chapter_number)
            finding_inputs = []
            for finding_id in finding_ids or []:
                finding = session.get(EditorialFindingRow, finding_id)
                if finding is None or finding.title_id != title_id:
                    raise ValueError(f"Unknown editorial finding for this title: {finding_id}")
                finding_payload = {"finding_id": finding.finding_id, "description": finding.description,
                                   "evidence": finding.evidence, "recommended_action": finding.recommended_action}
                finding_inputs.append(ContextInput(input_ref=finding.finding_id,
                    sha256=sha256_bytes(canonical_json_bytes(finding_payload)),
                    context_tier="B", role="editorial_finding"))
            context_manifest = ContextManifest(
                title_id=title_id,
                task_type=f"chapter.revise.{chapter_number}",
                inputs=context_manifest.inputs + [ContextInput(
                    input_ref=source.asset_id, sha256=source.sha256, context_tier="A", role="source_draft"
                )] + finding_inputs,
            )
            context_manifest, chapter_context = _chapter_authoring_context(session, title_id, chapter_number, context_manifest)
            title_values = {
                "title_id": title_id,
                "working_title": title.working_title,
                "target_reader": title.target_reader or "unspecified",
                "chapter_number": str(chapter_number),
            }
        prompt = PromptRegistry(root / "prompts").render("drafting/chapter-revise", {**title_values, "chapter_context": chapter_context})
        return await GenerationService.generate(
            root,
            title_id=title_id,
            task_type=f"chapter.revise.{chapter_number}",
            rendered_prompt=prompt,
            context_manifest=context_manifest,
            provider=provider,
            system_instructions="Revise the source chapter using the supplied findings; preserve unresolved issues as text rather than inventing canon.",
            max_output_tokens=max_output_tokens if max_output_tokens is not None else (2400 if provider is not None else None),
            temperature=0 if provider is not None else None,
            asset_type=ChapterAssetKind.REVISION.value,
            source_ref=source_asset_id,
            metadata={"chapter_number": chapter_number, "source_asset_id": source_asset_id, "finding_ids": finding_ids or []},
        )


def accept_chapter(
    root: Path,
    asset_id: str,
    *,
    chapter_number: int,
    reviewer: str,
    finding_ids: list[str] | None = None,
    proposal_ids: list[str] | None = None,
    conditions: list[str] | None = None,
    supersede: bool = False,
    supersede_reason: str | None = None,
) -> ChapterAcceptanceResult:
    if chapter_number < 1:
        raise ChapterAcceptanceError("chapter_number must be positive")
    if not reviewer.strip():
        raise ChapterAcceptanceError("reviewer is required")
    if supersede and not (supersede_reason and supersede_reason.strip()):
        raise ChapterAcceptanceError("Superseding an accepted chapter requires a reason")
    conditions = normalize_approval_conditions(conditions)
    destination: Path | None = None
    copied = False
    archived_path: Path | None = None
    try:
        with session_scope(root) as session:
            source = session.get(AssetRow, asset_id)
            if source is None or source.approval_status != "experimental":
                raise ChapterAcceptanceError("Only an experimental chapter asset can be accepted")
            if source.asset_type not in {ChapterAssetKind.DRAFT.value, ChapterAssetKind.REVISION.value}:
                raise ChapterAcceptanceError("Asset is not a chapter draft or revision")
            source_number = _CHAPTER_NUMBER_FROM_SOURCE.search(Path(source.path).name)
            if source_number is None or int(source_number.group("number")) != chapter_number:
                raise ChapterAcceptanceError("Chapter number does not match the source draft")
            source_path = Path(source.path)
            if not source_path.is_file() or sha256_file(source_path) != source.sha256:
                raise ChapterAcceptanceError("Source file/hash integrity check failed")
            provenance = session.scalar(select(ProvenanceRow).where(ProvenanceRow.asset_id == source.asset_id))
            if provenance is None:
                raise ChapterAcceptanceError("Generated chapter requires provenance before acceptance")
            title = session.get(TitleRow, source.title_id)
            project = session.get(ProjectRow, title.project_id) if title else None
            if title is None or project is None:
                raise ChapterAcceptanceError("Chapter asset has no valid title/project")
            if title.status != TitleState.DRAFTING.value:
                raise ChapterAcceptanceError("Chapter acceptance requires the title to be in DRAFTING")
            destination = root / "projects" / project.project_id / "titles" / title.title_id / "05_drafts" / "accepted" / f"chapter-{chapter_number:03d}.md"
            existing = session.scalar(select(AssetRow).where(
                AssetRow.source_ref == source.asset_id,
                AssetRow.asset_type == ChapterAssetKind.ACCEPTED.value,
                AssetRow.approval_status == "accepted",
            ))
            if existing is not None:
                existing_approval = session.scalar(select(ApprovalRow).where(
                    ApprovalRow.asset_id == existing.asset_id,
                    ApprovalRow.decision == "accepted",
                ))
                existing_provenance = session.scalar(select(ProvenanceRow).where(ProvenanceRow.asset_id == existing.asset_id))
                existing_path = Path(existing.path)
                if (
                    existing_approval is not None
                    and existing_provenance is not None
                    and existing_path.resolve() == destination.resolve()
                    and existing_path.is_file()
                    and sha256_file(existing_path) == existing.sha256 == source.sha256
                ):
                    queue_item = session.scalar(select(ChapterQueueRow).where(
                        ChapterQueueRow.title_id == source.title_id, ChapterQueueRow.chapter_number == chapter_number))
                    if queue_item and queue_item.status != "complete":
                        queue_item.status = "complete"
                        queue_item.updated_at = utcnow()
                    AuditEventWriter.append(
                        session, actor_id=reviewer, action="chapter.reused", entity_type="asset",
                        entity_id=existing.asset_id, correlation_id=source.title_id, result="success",
                        metadata={"source_asset_id": source.asset_id, "approval_id": existing_approval.approval_id},
                    )
                    session.commit()
                    return ChapterAcceptanceResult(source, existing, existing_approval, existing_path)
                raise ChapterAcceptanceError("An accepted chapter already exists with conflicting destination or hash")
            superseded = None
            if destination.exists() and supersede:
                superseded = session.scalar(select(AssetRow).where(
                    AssetRow.title_id == title.title_id,
                    AssetRow.asset_type == ChapterAssetKind.ACCEPTED.value,
                    AssetRow.approval_status == "accepted",
                    AssetRow.path == str(destination.resolve()),
                ))
                if superseded is None or sha256_file(destination) != superseded.sha256:
                    raise ChapterAcceptanceError("Accepted chapter destination does not match its accepted record")
                archive_dir = destination.parents[2] / "12_archive" / "accepted-chapters"
                archived_path = archive_dir / f"{superseded.asset_id}-{destination.name}"
                if archived_path.exists():
                    raise ChapterAcceptanceError("Archive destination already exists; refusing to overwrite it")
                archive_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(destination), archived_path)
                superseded.approval_status = "superseded"
                superseded.path = str(archived_path.resolve())
            elif destination.exists():
                if sha256_file(destination) != source.sha256:
                    raise ChapterAcceptanceError("Accepted chapter destination exists with a conflicting hash")
                raise ChapterAcceptanceError("Accepted chapter destination exists without matching accepted state")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
            copied = True
            output_hash = sha256_file(destination)
            accepted = AssetRow(
                asset_id=new_id("AST"), title_id=source.title_id, asset_type=ChapterAssetKind.ACCEPTED.value,
                path=str(destination.resolve()), version=source.version, sha256=output_hash,
                creator_type=source.creator_type, creator=source.creator, source_ref=source.asset_id,
                ai_classification=source.ai_classification, approval_status="accepted", created_at=utcnow(),
            )
            approval = ApprovalRow(
                approval_id=new_id("APR"), title_id=source.title_id, asset_id=accepted.asset_id,
                scope=f"chapter.{chapter_number}", candidate_hash=output_hash, approver=reviewer,
                decision="accepted", conditions_json=json.dumps(conditions), created_at=utcnow(),
            )
            accepted_provenance = ProvenanceRow(
                provenance_id=new_id("PROV"), asset_id=accepted.asset_id, job_id=None,
                provider=provenance.provider, model=provenance.model,
                prompt_template_id=provenance.prompt_template_id, prompt_template_version=provenance.prompt_template_version,
                rendered_prompt_sha256=provenance.rendered_prompt_sha256,
                input_references_json=provenance.input_references_json, input_hashes_json=provenance.input_hashes_json,
                context_manifest_hash=provenance.context_manifest_hash, output_hash=output_hash,
                generation_timestamp=provenance.generation_timestamp, human_contribution_note=provenance.human_contribution_note,
                ai_classification=provenance.ai_classification, disclosure_decision=provenance.disclosure_decision,
                reviewer=reviewer,
            )
            session.add_all([accepted, approval, accepted_provenance])
            queue_item = session.scalar(select(ChapterQueueRow).where(
                ChapterQueueRow.title_id == source.title_id, ChapterQueueRow.chapter_number == chapter_number))
            if queue_item is not None:
                queue_item.status = "complete"
                queue_item.updated_at = utcnow()
                AuditEventWriter.append(session, actor_id=reviewer, action="chapters.queue.item_completed",
                    entity_type="chapter_queue_item", entity_id=queue_item.queue_item_id,
                    correlation_id=source.title_id, result="success",
                    metadata={"chapter_number": chapter_number, "accepted_asset_id": accepted.asset_id})
            metadata = {
                "source_asset_id": source.asset_id, "source_path": str(source_path),
                "destination_path": str(destination), "approval_id": approval.approval_id,
                "reviewer": reviewer, "finding_ids": finding_ids or [], "proposal_ids": proposal_ids or [],
                "provenance_id": accepted_provenance.provenance_id, "conditions": conditions,
                "superseded_asset_id": superseded.asset_id if superseded is not None else None,
                "supersede_reason": supersede_reason.strip() if superseded is not None and supersede_reason else None,
                "superseded_archive_path": str(archived_path) if archived_path is not None else None,
            }
            AuditEventWriter.append(session, actor_id=reviewer, action="chapter.accepted", entity_type="asset", entity_id=accepted.asset_id,
                                    correlation_id=source.title_id, result="success", before_hash=source.sha256, after_hash=output_hash, metadata=metadata)
            session.commit()
            return ChapterAcceptanceResult(source, accepted, approval, destination)
    except Exception:
        if copied and destination is not None and destination.exists():
            destination.unlink()
        if archived_path is not None and archived_path.exists() and destination is not None and not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(archived_path), destination)
        raise

