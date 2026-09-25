from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ChapterAssetKind(StrEnum):
    DRAFT = "chapter.draft"
    REVISION = "chapter.revision"
    ACCEPTED = "chapter.accepted"


class ChapterArtifact(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    title_id: str
    chapter_number: int = Field(ge=1)
    asset_id: str
    asset_type: ChapterAssetKind
    path: str
    sha256: str
    approval_status: str
    source_asset_id: str | None = None
    provenance_id: str | None = None


class ChapterFindingLink(BaseModel):
    finding_id: str
    proposal_id: str | None = None

