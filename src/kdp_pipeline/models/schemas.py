from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from kdp_pipeline.core.state_machine import TitleState


class Project(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    project_id: str
    name: str
    status: str = "ACTIVE"
    default_language: str = "en"
    default_provider_policy: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class Series(BaseModel):
    series_id: str
    project_id: str
    name: str
    series_bible_version: str | None = None
    series_engine_version: str | None = None
    style_card_version: str | None = None
    visual_system_version: str | None = None


class Title(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    title_id: str
    project_id: str
    series_id: str | None = None
    working_title: str
    final_title: str | None = None
    subtitle: str | None = None
    volume: int | None = None
    language: str = "en"
    edition: int = 1
    format_targets: list[str] = Field(default_factory=list)
    status: TitleState = TitleState.IDEA
    target_reader: str | None = None
    created_at: datetime


class Asset(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    asset_id: str
    title_id: str
    asset_type: str
    path: str
    version: str
    sha256: str
    creator_type: str
    creator: str
    source_ref: str | None = None
    ai_classification: str | None = None
    approval_status: str = "experimental"
    created_at: datetime


class ProvenanceRecord(BaseModel):
    provenance_id: str
    asset_id: str
    job_id: str | None = None
    provider: str | None = None
    model: str | None = None
    prompt_template_id: str | None = None
    prompt_template_version: str | None = None
    input_asset_ids: list[str] = Field(default_factory=list)
    input_hashes: list[str] = Field(default_factory=list)
    output_hash: str
    generation_timestamp: datetime
    human_contribution_note: str | None = None
    ai_classification: str | None = None
    disclosure_decision: str | None = None
    reviewer: str | None = None


class RightsRecord(BaseModel):
    rights_id: str
    asset_id: str
    owner: str
    legal_basis: str
    territories: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    formats: list[str] = Field(default_factory=list)
    term: str | None = None
    restrictions: list[str] = Field(default_factory=list)
    evidence_path: str | None = None
    review_status: str
    reviewer: str | None = None


class EditorialFinding(BaseModel):
    finding_id: str
    title_id: str
    asset_id: str | None = None
    pass_type: str
    severity: str
    location: str
    description: str
    evidence: str | None = None
    recommended_action: str | None = None
    status: str
    owner: str | None = None
    resolution: str | None = None


class Approval(BaseModel):
    approval_id: str
    title_id: str
    scope: str
    candidate_hash: str
    approver: str
    decision: str
    policy_baseline_version: str | None = None
    conditions: list[str] = Field(default_factory=list)
    created_at: datetime
    expires_at: datetime | None = None


class Job(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    job_id: str
    title_id: str
    job_type: str
    status: str
    idempotency_key: str
    input_manifest_hash: str
    provider: str | None = None
    model: str | None = None
    started_at: datetime | None = None
    created_at: datetime
    completed_at: datetime | None = None
    result_asset_ids: list[str] = Field(default_factory=list)
    error: str | None = None


class ReleaseCandidate(BaseModel):
    candidate_id: str
    title_id: str
    manuscript_hash: str
    cover_hash: str | None = None
    ebook_hash: str | None = None
    metadata_hash: str
    policy_baseline_version: str | None = None
    preflight_report_id: str | None = None
    approval_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    frozen: bool = False


class AuditEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    event_id: str
    timestamp_utc: datetime
    actor_type: str
    actor_id: str
    action: str
    entity_type: str
    entity_id: str
    before_hash: str | None = None
    after_hash: str | None = None
    correlation_id: str
    result: str
    metadata: dict[str, Any] = Field(default_factory=dict)
