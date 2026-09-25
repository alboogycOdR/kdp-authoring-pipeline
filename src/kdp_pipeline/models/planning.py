from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PlanningArtifactKind(StrEnum):
    POSITIONING = "positioning"
    BOOK_BRIEF = "book_brief"
    OUTLINE = "outline"
    CHAPTER_CARD = "chapter_card"


class PlanningArtifactSpec(BaseModel):
    kind: PlanningArtifactKind
    asset_type: str
    template_id: str
    destination_template: str
    required: bool = True


class PlanningArtifact(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    title_id: str
    artifact_kind: PlanningArtifactKind
    asset_id: str
    path: str
    sha256: str
    version: str
    approval_status: str
    template_id: str
    template_version: str
    chapter_number: int | None = Field(default=None, ge=1)


PLANNING_ARTIFACT_SPECS: dict[PlanningArtifactKind, PlanningArtifactSpec] = {
    PlanningArtifactKind.POSITIONING: PlanningArtifactSpec(
        kind=PlanningArtifactKind.POSITIONING,
        asset_type="planning.positioning",
        template_id="planning/positioning-brief",
        destination_template="04_plan/positioning.md",
    ),
    PlanningArtifactKind.BOOK_BRIEF: PlanningArtifactSpec(
        kind=PlanningArtifactKind.BOOK_BRIEF,
        asset_type="planning.book-brief",
        template_id="planning/book-brief",
        destination_template="04_plan/book-brief.md",
    ),
    PlanningArtifactKind.OUTLINE: PlanningArtifactSpec(
        kind=PlanningArtifactKind.OUTLINE,
        asset_type="planning.outline",
        template_id="planning/outline",
        destination_template="04_plan/outline.md",
    ),
    PlanningArtifactKind.CHAPTER_CARD: PlanningArtifactSpec(
        kind=PlanningArtifactKind.CHAPTER_CARD,
        asset_type="planning.chapter-card",
        template_id="planning/chapter-card",
        destination_template="04_plan/chapter-cards/chapter-{chapter_number:03d}.md",
    ),
}


def spec_for(kind: PlanningArtifactKind) -> PlanningArtifactSpec:
    return PLANNING_ARTIFACT_SPECS[kind]
