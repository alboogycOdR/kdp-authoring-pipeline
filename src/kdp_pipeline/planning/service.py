from __future__ import annotations

from pathlib import Path
from typing import Any

from kdp_pipeline.context import ContextManifest
from kdp_pipeline.generation import GenerationRunResult, GenerationService
from kdp_pipeline.models.planning import PlanningArtifactKind, spec_for
from kdp_pipeline.prompts import PromptRegistry
from kdp_pipeline.providers import ModelProvider
from kdp_pipeline.storage.db import TitleRow
from kdp_pipeline.storage.service import session_scope


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
            title_values = {
                "title_id": title.title_id,
                "working_title": title.working_title,
                "target_reader": title.target_reader or "unspecified",
                "chapter_number": str(chapter_number or ""),
            }

        spec = spec_for(artifact_kind)
        prompt = PromptRegistry(root / "prompts").render(
            spec.template_id,
            {**title_values, **(variables or {})},
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
