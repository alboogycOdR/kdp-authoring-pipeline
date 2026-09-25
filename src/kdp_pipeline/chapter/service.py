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
from kdp_pipeline.storage.db import (
    AssetRow,
    ApprovalRow,
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


class ChapterService:
    @staticmethod
    async def draft(
        root: Path,
        *,
        title_id: str,
        chapter_number: int,
        provider: ModelProvider,
        variables: dict[str, Any] | None = None,
        max_output_tokens: int = 2400,
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
            title_values = {
                "title_id": title_id,
                "working_title": title.working_title,
                "target_reader": title.target_reader or "unspecified",
                "chapter_number": str(chapter_number),
            }
        prompt = PromptRegistry(root / "prompts").render(
            "drafting/chapter-draft", {**title_values, **(variables or {})}
        )
        return await GenerationService.generate(
            root,
            title_id=title_id,
            task_type=f"chapter.draft.{chapter_number}",
            rendered_prompt=prompt,
            context_manifest=context_manifest,
            provider=provider,
            system_instructions="Draft only the requested chapter using the supplied approved planning context.",
            max_output_tokens=max_output_tokens,
            temperature=0,
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
        provider: ModelProvider,
        finding_ids: list[str] | None = None,
        max_output_tokens: int = 2400,
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
            context_manifest = ContextManifest(
                title_id=title_id,
                task_type=f"chapter.revise.{chapter_number}",
                inputs=context_manifest.inputs + [ContextInput(
                    input_ref=source.asset_id, sha256=source.sha256, context_tier="A", role="source_draft"
                )] + [ContextInput(
                    input_ref=finding_id, sha256=sha256_bytes(canonical_json_bytes({"finding_id": finding_id})), context_tier="B", role="editorial_finding"
                ) for finding_id in (finding_ids or [])],
            )
            title_values = {
                "title_id": title_id,
                "working_title": title.working_title,
                "target_reader": title.target_reader or "unspecified",
                "chapter_number": str(chapter_number),
            }
        prompt = PromptRegistry(root / "prompts").render("drafting/chapter-revise", title_values)
        return await GenerationService.generate(
            root,
            title_id=title_id,
            task_type=f"chapter.revise.{chapter_number}",
            rendered_prompt=prompt,
            context_manifest=context_manifest,
            provider=provider,
            system_instructions="Revise the source chapter using the supplied findings; preserve unresolved issues as text rather than inventing canon.",
            max_output_tokens=max_output_tokens,
            temperature=0,
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
) -> ChapterAcceptanceResult:
    if chapter_number < 1:
        raise ChapterAcceptanceError("chapter_number must be positive")
    if not reviewer.strip():
        raise ChapterAcceptanceError("reviewer is required")
    destination: Path | None = None
    copied = False
    try:
        with session_scope(root) as session:
            source = session.get(AssetRow, asset_id)
            if source is None or source.approval_status != "experimental":
                raise ChapterAcceptanceError("Only an experimental chapter asset can be accepted")
            if source.asset_type not in {ChapterAssetKind.DRAFT.value, ChapterAssetKind.REVISION.value}:
                raise ChapterAcceptanceError("Asset is not a chapter draft or revision")
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
                    AuditEventWriter.append(
                        session, actor_id=reviewer, action="chapter.reused", entity_type="asset",
                        entity_id=existing.asset_id, correlation_id=source.title_id, result="success",
                        metadata={"source_asset_id": source.asset_id, "approval_id": existing_approval.approval_id},
                    )
                    session.commit()
                    return ChapterAcceptanceResult(source, existing, existing_approval, existing_path)
                raise ChapterAcceptanceError("An accepted chapter already exists with conflicting destination or hash")
            if destination.exists():
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
                decision="accepted", conditions_json="[]", created_at=utcnow(),
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
            metadata = {
                "source_asset_id": source.asset_id, "source_path": str(source_path),
                "destination_path": str(destination), "approval_id": approval.approval_id,
                "reviewer": reviewer, "finding_ids": finding_ids or [], "proposal_ids": proposal_ids or [],
                "provenance_id": accepted_provenance.provenance_id,
            }
            AuditEventWriter.append(session, actor_id=reviewer, action="chapter.accepted", entity_type="asset", entity_id=accepted.asset_id,
                                    correlation_id=source.title_id, result="success", before_hash=source.sha256, after_hash=output_hash, metadata=metadata)
            session.commit()
            return ChapterAcceptanceResult(source, accepted, approval, destination)
    except Exception:
        if copied and destination is not None and destination.exists():
            destination.unlink()
        raise

