from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import NullPool


class Base(DeclarativeBase):
    pass


class ProjectRow(Base):
    __tablename__ = "projects"
    project_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="ACTIVE")
    default_language: Mapped[str] = mapped_column(String, default="en")
    default_provider_policy: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TitleRow(Base):
    __tablename__ = "titles"
    title_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), nullable=False)
    series_id: Mapped[str | None] = mapped_column(String, nullable=True)
    working_title: Mapped[str] = mapped_column(String, nullable=False)
    final_title: Mapped[str | None] = mapped_column(String, nullable=True)
    subtitle: Mapped[str | None] = mapped_column(String, nullable=True)
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str] = mapped_column(String, default="en")
    edition: Mapped[int] = mapped_column(Integer, default=1)
    format_targets_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String, default="IDEA")
    target_reader: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AssetRow(Base):
    __tablename__ = "assets"
    asset_id: Mapped[str] = mapped_column(String, primary_key=True)
    title_id: Mapped[str] = mapped_column(ForeignKey("titles.title_id"), nullable=False)
    asset_type: Mapped[str] = mapped_column(String, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    creator_type: Mapped[str] = mapped_column(String, nullable=False)
    creator: Mapped[str] = mapped_column(String, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_classification: Mapped[str | None] = mapped_column(String, nullable=True)
    approval_status: Mapped[str] = mapped_column(String, default="experimental")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobRow(Base):
    __tablename__ = "jobs"
    job_id: Mapped[str] = mapped_column(String, primary_key=True)
    title_id: Mapped[str] = mapped_column(ForeignKey("titles.title_id"), nullable=False)
    job_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    input_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_asset_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProvenanceRow(Base):
    __tablename__ = "provenance"
    provenance_id: Mapped[str] = mapped_column(String, primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.asset_id"), nullable=False, unique=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.job_id"), nullable=True, unique=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    prompt_template_id: Mapped[str] = mapped_column(String, nullable=False)
    prompt_template_version: Mapped[str] = mapped_column(String, nullable=False)
    rendered_prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_references_json: Mapped[str] = mapped_column(Text, default="[]")
    input_hashes_json: Mapped[str] = mapped_column(Text, default="[]")
    context_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    generation_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    human_contribution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_classification: Mapped[str | None] = mapped_column(String, nullable=True)
    disclosure_decision: Mapped[str | None] = mapped_column(String, nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String, nullable=True)


class ApprovalRow(Base):
    __tablename__ = "approvals"
    approval_id: Mapped[str] = mapped_column(String, primary_key=True)
    title_id: Mapped[str] = mapped_column(ForeignKey("titles.title_id"), nullable=False)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.asset_id"), nullable=True)
    scope: Mapped[str] = mapped_column(String, nullable=False)
    candidate_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approver: Mapped[str] = mapped_column(String, nullable=False)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    policy_baseline_version: Mapped[str | None] = mapped_column(String, nullable=True)
    conditions_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EditorialFindingRow(Base):
    __tablename__ = "editorial_findings"
    finding_id: Mapped[str] = mapped_column(String, primary_key=True)
    title_id: Mapped[str] = mapped_column(ForeignKey("titles.title_id"), nullable=False)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.asset_id"), nullable=True)
    pass_type: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    location: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    owner: Mapped[str | None] = mapped_column(String, nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CanonProposalRow(Base):
    __tablename__ = "canon_proposals"
    proposal_id: Mapped[str] = mapped_column(String, primary_key=True)
    title_id: Mapped[str] = mapped_column(ForeignKey("titles.title_id"), nullable=False)
    finding_id: Mapped[str | None] = mapped_column(ForeignKey("editorial_findings.finding_id"), nullable=True)
    entity_id: Mapped[str] = mapped_column(String, nullable=False)
    field: Mapped[str] = mapped_column(String, nullable=False)
    current_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_value: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_asset_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    affected_assets_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String, nullable=False, default="proposed")
    reviewer: Mapped[str | None] = mapped_column(String, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    snapshot_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditEventRow(Base):
    __tablename__ = "audit_events"
    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    timestamp_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_type: Mapped[str] = mapped_column(String, nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[str] = mapped_column(String, nullable=False)
    before_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    after_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False)
    result: Mapped[str] = mapped_column(String, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def engine_for(root: Path):
    state_dir = root / ".kdp"
    state_dir.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{state_dir / 'state.db'}",
        future=True,
        poolclass=NullPool,
    )


def init_db(root: Path) -> None:
    engine = engine_for(root)
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()


def session_factory(root: Path):
    return sessionmaker(bind=engine_for(root), expire_on_commit=False)
