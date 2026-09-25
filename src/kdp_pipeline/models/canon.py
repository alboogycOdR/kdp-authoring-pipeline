from __future__ import annotations

from enum import StrEnum

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CanonProposalStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class CanonProposal(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    proposal_id: str
    title_id: str
    finding_id: str | None = None
    entity_id: str
    field: str
    current_value: str | None = None
    proposed_value: str
    reason: str
    evidence_asset_ids: list[str] = Field(default_factory=list)
    affected_assets: list[str] = Field(default_factory=list)
    status: CanonProposalStatus = CanonProposalStatus.PROPOSED
    reviewer: str | None = None
    reviewed_at: datetime | None = None
    snapshot_path: str | None = None
