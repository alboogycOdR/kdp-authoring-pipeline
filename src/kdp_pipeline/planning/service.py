from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select

from kdp_pipeline.context import ContextInput, ContextManifest
from kdp_pipeline.generation import GenerationRunResult, GenerationService
from kdp_pipeline.models.planning import PlanningArtifactKind, spec_for
from kdp_pipeline.prompts import PromptRegistry
from kdp_pipeline.providers import ModelProvider
from kdp_pipeline.storage.db import ApprovalRow, AssetRow, ConceptGateRow, TitleRow
from kdp_pipeline.storage.files import sha256_file
from kdp_pipeline.storage.service import session_scope


_PLANNING_ORDER = (PlanningArtifactKind.POSITIONING, PlanningArtifactKind.BOOK_BRIEF,
                   PlanningArtifactKind.OUTLINE, PlanningArtifactKind.CHAPTER_CARD)


def _accepted_planning_context(session, title_id: str, kind: PlanningArtifactKind,
                               manifest: ContextManifest) -> tuple[ContextManifest, str]:
    """Send the accepted upstream artefacts to the model and record them in the manifest (KDP-AUD-006).

    Upstream = the operator idea note, the accepted concept brief, and every accepted planning
    artefact earlier in the chain than ``kind`` (a chapter card also receives the outline).
    Files are integrity-checked; a mismatch fails the request instead of silently dropping context.
    """
    wanted = ["concept.idea-note", "concept.brief"] + [
        spec_for(k).asset_type for k in _PLANNING_ORDER[:_PLANNING_ORDER.index(kind)]]
    inputs, sections = list(manifest.inputs), []
    for asset_type in wanted:
        query = select(AssetRow).where(AssetRow.title_id == title_id, AssetRow.asset_type == asset_type)
        if asset_type != "concept.idea-note":
            query = query.where(AssetRow.approval_status == "accepted")
        asset = session.scalar(query.order_by(AssetRow.created_at.desc()))
        if asset is None:
            continue
        if asset_type != "concept.idea-note" and session.scalar(select(ApprovalRow).where(
                ApprovalRow.asset_id == asset.asset_id, ApprovalRow.decision == "accepted")) is None:
            continue
        path = Path(asset.path)
        if not path.is_file() or sha256_file(path) != asset.sha256:
            raise ValueError(f"Planning context file/hash integrity check failed: {asset.asset_id}")
        inputs.append(ContextInput(input_ref=asset.asset_id, sha256=asset.sha256, context_tier="A", role=asset_type))
        sections.append(f"## {asset_type} (asset {asset.asset_id})\n{path.read_text(encoding='utf-8')}")
    text = "\n\n".join(sections) if sections else "No accepted upstream context exists yet."
    return ContextManifest(title_id=manifest.title_id, task_type=manifest.task_type, inputs=inputs), text


class PlanningService:
    @staticmethod
    async def generate(
        root: Path,
        *,
        title_id: str,
        artifact_kind: PlanningArtifactKind,
        context_manifest: ContextManifest,
        provider: ModelProvider | None = None,
        variables: dict[str, Any] | None = None,
        chapter_number: int | None = None,
        system_instructions: str = "Create a planning proposal using only the supplied context.",
        max_output_tokens: int | None = None,
    ) -> GenerationRunResult:
        if context_manifest.title_id != title_id:
            raise ValueError("Context manifest title_id must match the planning title_id")
        if artifact_kind == PlanningArtifactKind.CHAPTER_CARD and (chapter_number is None or chapter_number < 1):
            raise ValueError("chapter_number is required and must be positive for a chapter card")
        if artifact_kind != PlanningArtifactKind.CHAPTER_CARD and chapter_number is not None:
            raise ValueError("chapter_number is only valid for a chapter card")

        with session_scope(root) as session:
            title = session.get(TitleRow, title_id)
            if title is None:
                raise ValueError(f"Unknown title: {title_id}")
            if title.status not in {"IDEA", "VALIDATED"}:
                raise ValueError("Planning generation requires an IDEA or VALIDATED title")
            concept_gate = session.get(ConceptGateRow, title_id)
            if artifact_kind == PlanningArtifactKind.POSITIONING and concept_gate and concept_gate.enabled:
                accepted_brief = session.query(AssetRow).filter_by(
                    title_id=title_id, asset_type="concept.brief", approval_status="accepted"
                ).first()
                approval = session.query(ApprovalRow).filter_by(
                    asset_id=accepted_brief.asset_id, decision="accepted"
                ).first() if accepted_brief else None
                if (accepted_brief is None or approval is None or not Path(accepted_brief.path).is_file()
                        or sha256_file(Path(accepted_brief.path)) != accepted_brief.sha256):
                    raise ValueError("Concept validation is enabled; accept a concept brief before generating positioning")
            title_values = {
                "title_id": title.title_id,
                "working_title": title.working_title,
                "target_reader": title.target_reader or "unspecified",
                "chapter_number": str(chapter_number or ""),
            }

            context_manifest, planning_context = _accepted_planning_context(
                session, title_id, artifact_kind, context_manifest)

        spec = spec_for(artifact_kind)
        prompt = PromptRegistry(root / "prompts").render(
            spec.template_id,
            {**title_values, "planning_context": planning_context, **(variables or {})},
            template_version="1.1",
        )
        task_type = f"planning.{artifact_kind.value}"
        if chapter_number is not None:
            task_type = f"{task_type}.{chapter_number}"
        return await GenerationService.generate(
            root,
            title_id=title_id,
            task_type=task_type,
            rendered_prompt=prompt,
            context_manifest=context_manifest,
            provider=provider,
            system_instructions=system_instructions,
            max_output_tokens=max_output_tokens if max_output_tokens is not None else (1200 if provider is not None else None),
            temperature=0 if provider is not None else None,
            asset_type=spec.asset_type,
            metadata={"planning_artifact_kind": artifact_kind.value, "chapter_number": chapter_number},
        )

    @staticmethod
    async def generate_positioning(*args, **kwargs) -> GenerationRunResult:
        return await PlanningService.generate(*args, artifact_kind=PlanningArtifactKind.POSITIONING, **kwargs)

    @staticmethod
    async def generate_book_brief(*args, **kwargs) -> GenerationRunResult:
        return await PlanningService.generate(*args, artifact_kind=PlanningArtifactKind.BOOK_BRIEF, **kwargs)

    @staticmethod
    async def generate_outline(*args, **kwargs) -> GenerationRunResult:
        return await PlanningService.generate(*args, artifact_kind=PlanningArtifactKind.OUTLINE, **kwargs)

    @staticmethod
    async def generate_chapter_card(*args, **kwargs) -> GenerationRunResult:
        return await PlanningService.generate(*args, artifact_kind=PlanningArtifactKind.CHAPTER_CARD, **kwargs)
