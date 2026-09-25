from __future__ import annotations

import json
import re
import shutil
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from kdp_pipeline.core.ids import new_id
from kdp_pipeline.core.state_machine import TitleState, require_transition
from kdp_pipeline.models.planning import PlanningArtifactKind, spec_for
from kdp_pipeline.storage.audit import AuditEventWriter, list_events
from kdp_pipeline.storage.db import (
    AssetRow,
    ApprovalRow,
    AuditEventRow,
    JobRow,
    ProjectRow,
    ProvenanceRow,
    TitleRow,
    engine_for,
    init_db,
    utcnow,
)
from kdp_pipeline.storage.files import create_project_workspace, create_title_workspace, sha256_file, write_json


@contextmanager
def session_scope(root: Path):
    init_db(root)
    engine = engine_for(root)
    try:
        with Session(engine, expire_on_commit=False) as session:
            yield session
    finally:
        engine.dispose()


def _project_snapshot(row: ProjectRow) -> dict:
    return {
        "project_id": row.project_id,
        "name": row.name,
        "created_at": row.created_at.isoformat(),
        "status": row.status,
        "default_language": row.default_language,
        "default_provider_policy": json.loads(row.default_provider_policy or "{}"),
    }


def _title_snapshot(row: TitleRow) -> dict:
    return {
        "title_id": row.title_id,
        "project_id": row.project_id,
        "series_id": row.series_id,
        "working_title": row.working_title,
        "final_title": row.final_title,
        "subtitle": row.subtitle,
        "volume": row.volume,
        "edition": row.edition,
        "language": row.language,
        "format_targets": json.loads(row.format_targets_json or "[]"),
        "status": row.status,
        "target_reader": row.target_reader,
        "created_at": row.created_at.isoformat(),
    }


def _remove_workspace(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def create_project(root: Path, name: str, language: str = "en") -> ProjectRow:
    init_db(root)
    project_id = new_id("PRJ")
    workspace = root / "projects" / project_id
    try:
        create_project_workspace(root, project_id, name)
        with session_scope(root) as session:
            row = ProjectRow(
                project_id=project_id,
                name=name,
                default_language=language,
                default_provider_policy="{}",
                created_at=utcnow(),
            )
            session.add(row)
            AuditEventWriter.append(
                session,
                actor_id="cli-user",
                action="project.create",
                entity_type="project",
                entity_id=project_id,
                correlation_id=project_id,
                result="success",
            )
            session.commit()
            try:
                write_json(workspace / "project.json", _project_snapshot(row))
            except Exception:
                session.rollback()
                session.execute(delete(AuditEventRow).where(AuditEventRow.entity_id == project_id))
                session.execute(delete(ProjectRow).where(ProjectRow.project_id == project_id))
                session.commit()
                raise
            return row
    except Exception:
        _remove_workspace(workspace)
        raise


def create_title(root: Path, project_id: str, working_title: str, language: str = "en") -> TitleRow:
    title_id = new_id("BK")
    workspace = root / "projects" / project_id / "titles" / title_id
    with session_scope(root) as session:
        if not session.get(ProjectRow, project_id):
            raise ValueError(f"Unknown project: {project_id}")
    try:
        create_title_workspace(root, project_id, title_id, working_title)
        with session_scope(root) as session:
            row = TitleRow(
                title_id=title_id,
                project_id=project_id,
                working_title=working_title,
                language=language,
                status=TitleState.IDEA.value,
                created_at=utcnow(),
                format_targets_json="[]",
            )
            session.add(row)
            AuditEventWriter.append(
                session,
                actor_id="cli-user",
                action="title.create",
                entity_type="title",
                entity_id=title_id,
                correlation_id=title_id,
                result="success",
            )
            session.commit()
            try:
                write_json(workspace / "00_admin" / "title.json", _title_snapshot(row))
            except Exception:
                session.rollback()
                session.execute(delete(AuditEventRow).where(AuditEventRow.entity_id == title_id))
                session.execute(delete(TitleRow).where(TitleRow.title_id == title_id))
                session.commit()
                raise
            return row
    except Exception:
        _remove_workspace(workspace)
        raise


def get_title(root: Path, title_id: str) -> TitleRow | None:
    with session_scope(root) as session:
        return session.get(TitleRow, title_id)


_CHAPTER_CARD_NAME = re.compile(r"chapter-\d{3}\.md$")


def _accepted_planning_asset(session: Session, root: Path, title_id: str, kind: PlanningArtifactKind) -> AssetRow | None:
    spec = spec_for(kind)
    title = session.get(TitleRow, title_id)
    if title is None:
        return None
    project = session.get(ProjectRow, title.project_id)
    if project is None:
        return None
    title_root = (root / "projects" / project.project_id / "titles" / title_id).resolve()
    rows = list(session.scalars(select(AssetRow).where(
        AssetRow.title_id == title_id,
        AssetRow.asset_type == spec.asset_type,
        AssetRow.approval_status == "accepted",
    )))
    for asset in rows:
        approval = session.scalar(select(ApprovalRow).where(
            ApprovalRow.asset_id == asset.asset_id,
            ApprovalRow.decision == "accepted",
        ))
        provenance = session.scalar(select(ProvenanceRow).where(ProvenanceRow.asset_id == asset.asset_id))
        path = Path(asset.path)
        if approval is None or provenance is None or not path.is_file():
            continue
        try:
            relative = path.resolve().relative_to(title_root)
        except ValueError:
            continue
        if kind == PlanningArtifactKind.CHAPTER_CARD:
            if relative.parent.as_posix() != "04_plan/chapter-cards" or not _CHAPTER_CARD_NAME.search(path.name):
                continue
        else:
            expected = spec.destination_template
            if relative.as_posix() != expected:
                continue
        if sha256_file(path) != asset.sha256 or approval.candidate_hash != asset.sha256:
            continue
        return asset
    return None


def _planning_requirements_met(session: Session, root: Path, title_id: str) -> bool:
    return all(_accepted_planning_asset(session, root, title_id, kind) is not None for kind in (
        PlanningArtifactKind.POSITIONING,
        PlanningArtifactKind.BOOK_BRIEF,
        PlanningArtifactKind.OUTLINE,
        PlanningArtifactKind.CHAPTER_CARD,
    ))


def planning_requirements_met(root: Path, title_id: str) -> bool:
    with session_scope(root) as session:
        return _planning_requirements_met(session, root, title_id)


def transition_title(root: Path, title_id: str, target: TitleState, actor_id: str = "cli-user") -> TitleRow:
    with session_scope(root) as session:
        row = session.get(TitleRow, title_id)
        if not row:
            raise ValueError(f"Unknown title: {title_id}")
        current = TitleState(row.status)
        require_transition(current, target)
        if target == TitleState.PLANNED and not _planning_requirements_met(session, root, title_id):
            raise ValueError("Cannot transition to PLANNED: required accepted planning artefacts are incomplete")
        before = row.status
        row.status = target.value
        AuditEventWriter.append(
            session,
            actor_id=actor_id,
            action="title.transition",
            entity_type="title",
            entity_id=title_id,
            correlation_id=title_id,
            result="success",
            metadata={"before": before, "after": target.value},
        )
        session.commit()
        write_json(
            root / "projects" / row.project_id / "titles" / title_id / "00_admin" / "title.json",
            _title_snapshot(row),
        )
        return row


def advance_to_validated(root: Path, title_id: str, actor_id: str = "cli-user") -> TitleRow:
    with session_scope(root) as session:
        if session.get(TitleRow, title_id) is None:
            raise ValueError(f"Unknown title: {title_id}")
        if _accepted_planning_asset(session, root, title_id, PlanningArtifactKind.POSITIONING) is None:
            raise ValueError("Cannot advance to VALIDATED: accepted positioning is required")
    return transition_title(root, title_id, TitleState.VALIDATED, actor_id)


def advance_to_planned(root: Path, title_id: str, actor_id: str = "cli-user") -> TitleRow:
    return transition_title(root, title_id, TitleState.PLANNED, actor_id)


def advance_to_drafting(root: Path, title_id: str, actor_id: str = "cli-user") -> TitleRow:
    return transition_title(root, title_id, TitleState.DRAFTING, actor_id)


def register_asset(
    root: Path,
    title_id: str,
    path: Path,
    asset_type: str,
    *,
    version: str = "1.0",
    creator_type: str = "human",
    creator: str = "cli-user",
    source_ref: str | None = None,
    ai_classification: str | None = None,
) -> AssetRow:
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"Asset file does not exist: {path}")
    with session_scope(root) as session:
        if not session.get(TitleRow, title_id):
            raise ValueError(f"Unknown title: {title_id}")
        row = AssetRow(
            asset_id=new_id("AST"),
            title_id=title_id,
            asset_type=asset_type,
            path=str(path),
            version=version,
            sha256=sha256_file(path),
            creator_type=creator_type,
            creator=creator,
            source_ref=source_ref,
            ai_classification=ai_classification,
            approval_status="experimental",
            created_at=utcnow(),
        )
        session.add(row)
        AuditEventWriter.append(
            session,
            actor_id=creator,
            action="asset.register",
            entity_type="asset",
            entity_id=row.asset_id,
            correlation_id=title_id,
            result="success",
            after_hash=row.sha256,
            metadata={"title_id": title_id, "path": str(path)},
        )
        session.commit()
        return row


def list_jobs(root: Path, title_id: str) -> list[JobRow]:
    with session_scope(root) as session:
        if not session.get(TitleRow, title_id):
            raise ValueError(f"Unknown title: {title_id}")
        return list(session.scalars(select(JobRow).where(JobRow.title_id == title_id)))


def list_audit(root: Path, entity_id: str) -> list[AuditEventRow]:
    with session_scope(root) as session:
        return list_events(session, entity_id)
