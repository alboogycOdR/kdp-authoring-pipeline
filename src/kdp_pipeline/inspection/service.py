from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, inspect as sqlalchemy_inspect, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from kdp_pipeline.models.planning import PlanningArtifactKind, spec_for
from kdp_pipeline.storage.db import (
    AssetRow, ApprovalRow, AuditEventRow, CanonProposalRow, EditorialFindingRow,
    JobRow, ProjectRow, ProvenanceRow, TitleRow,
)
from kdp_pipeline.storage.files import sha256_file


REQUIRED_TABLES = {
    "projects", "titles", "assets", "jobs", "provenance", "approvals",
    "editorial_findings", "canon_proposals", "audit_events",
}
REQUIRED_PROMPTS = (
    "planning/positioning-brief-v1.0.md",
    "planning/book-brief-v1.0.md",
    "planning/outline-v1.0.md",
    "planning/chapter-card-v1.0.md",
    "drafting/chapter-draft-v1.0.md",
    "drafting/chapter-revise-v1.0.md",
    "continuity/chapter-continuity-v1.0.md",
    "editorial/developmental-v1.0.md",
)


@contextmanager
def _read_only_session(root: Path):
    db_path = root / ".kdp" / "state.db"
    if not db_path.is_file():
        raise FileNotFoundError(f"SQLite database does not exist: {db_path}")
    engine = create_engine(f"sqlite:///{db_path}", future=True, poolclass=NullPool)
    try:
        with Session(engine, expire_on_commit=False) as session:
            yield session
    finally:
        engine.dispose()


def _file_check(asset: AssetRow) -> dict:
    path = Path(asset.path)
    exists = path.is_file()
    actual_hash = sha256_file(path) if exists else None
    return {"asset_id": asset.asset_id, "path": asset.path, "exists": exists,
            "recorded_sha256": asset.sha256, "actual_sha256": actual_hash,
            "hash_matches": exists and actual_hash == asset.sha256}


def inspect_title(root: Path, title_id: str) -> dict:
    with _read_only_session(root) as session:
        title = session.get(TitleRow, title_id)
        if title is None:
            raise ValueError(f"Unknown title: {title_id}")
        project = session.get(ProjectRow, title.project_id)
        assets = list(session.scalars(select(AssetRow).where(AssetRow.title_id == title_id).order_by(AssetRow.created_at)))
        jobs = list(session.scalars(select(JobRow).where(JobRow.title_id == title_id).order_by(JobRow.created_at)))
        approvals = list(session.scalars(select(ApprovalRow).where(ApprovalRow.title_id == title_id).order_by(ApprovalRow.created_at)))
        findings = list(session.scalars(select(EditorialFindingRow).where(EditorialFindingRow.title_id == title_id).order_by(EditorialFindingRow.created_at)))
        proposals = list(session.scalars(select(CanonProposalRow).where(CanonProposalRow.title_id == title_id).order_by(CanonProposalRow.created_at)))
        provenance = [row for asset in assets if (row := session.scalar(select(ProvenanceRow).where(ProvenanceRow.asset_id == asset.asset_id)))]
        audit = list(session.scalars(select(AuditEventRow).where(AuditEventRow.correlation_id == title_id).order_by(AuditEventRow.timestamp_utc.desc()).limit(25)))

        planning = {}
        title_root = root / "projects" / (project.project_id if project else "") / "titles" / title_id
        for kind in (PlanningArtifactKind.POSITIONING, PlanningArtifactKind.BOOK_BRIEF, PlanningArtifactKind.OUTLINE, PlanningArtifactKind.CHAPTER_CARD):
            spec = spec_for(kind)
            accepted = [asset for asset in assets if asset.asset_type == spec.asset_type and asset.approval_status == "accepted"]
            valid = []
            for asset in accepted:
                approval = next((item for item in approvals if item.asset_id == asset.asset_id and item.decision == "accepted"), None)
                prov = next((item for item in provenance if item.asset_id == asset.asset_id), None)
                path = Path(asset.path)
                valid.append({"asset_id": asset.asset_id, "path": asset.path, "file_exists": path.is_file(),
                              "hash_matches": path.is_file() and sha256_file(path) == asset.sha256,
                              "approval_id": approval.approval_id if approval else None,
                              "provenance_id": prov.provenance_id if prov else None})
            planning[kind.value] = {"required": True, "accepted": valid, "complete": bool(valid)}

        accepted_chapters = [asset for asset in assets if asset.asset_type == "chapter.accepted" and asset.approval_status == "accepted"]
        experimental_chapters = [asset for asset in assets if asset.asset_type in {"chapter.draft", "chapter.revision"} and asset.approval_status == "experimental"]
        inconsistencies = [check for asset in assets if not (check := _file_check(asset))["hash_matches"]]
        inconsistencies += [{"asset_id": asset.asset_id, "issue": "missing provenance"} for asset in assets if asset.creator_type == "ai" and not any(item.asset_id == asset.asset_id for item in provenance)]
        inconsistencies += [{"asset_id": asset.asset_id, "issue": "accepted asset missing approval"} for asset in assets if asset.approval_status == "accepted" and not any(item.asset_id == asset.asset_id and item.decision == "accepted" for item in approvals)]
        project_data = {"project_id": project.project_id, "name": project.name, "status": project.status} if project else None
        return {
            "project": project_data,
            "title": {"title_id": title.title_id, "working_title": title.working_title, "status": title.status},
            "planning": planning,
            "chapter_lifecycle": {"drafting_state": title.status == "DRAFTING", "experimental_chapter_assets": [asset.asset_id for asset in experimental_chapters],
                                  "accepted_chapter_assets": [asset.asset_id for asset in accepted_chapters], "accepted_chapter_count": len(accepted_chapters)},
            "assets": [{"asset_id": asset.asset_id, "asset_type": asset.asset_type, "path": asset.path, "sha256": asset.sha256, "approval_status": asset.approval_status, "source_ref": asset.source_ref} for asset in assets],
            "jobs": [{"job_id": job.job_id, "job_type": job.job_type, "status": job.status, "error": job.error, "idempotency_key": job.idempotency_key} for job in jobs],
            "provenance": [{"provenance_id": row.provenance_id, "asset_id": row.asset_id, "job_id": row.job_id, "provider": row.provider, "model": row.model, "output_hash": row.output_hash} for row in provenance],
            "approvals": [{"approval_id": row.approval_id, "asset_id": row.asset_id, "scope": row.scope, "decision": row.decision, "approver": row.approver} for row in approvals],
            "findings": [{"finding_id": row.finding_id, "asset_id": row.asset_id, "pass_type": row.pass_type, "status": row.status, "snapshot_path": row.snapshot_path} for row in findings],
            "proposals": [{"proposal_id": row.proposal_id, "finding_id": row.finding_id, "status": row.status, "snapshot_path": row.snapshot_path} for row in proposals],
            "audit": [{"event_id": row.event_id, "action": row.action, "entity_type": row.entity_type, "entity_id": row.entity_id, "result": row.result, "timestamp": row.timestamp_utc.isoformat()} for row in audit],
            "inconsistencies": inconsistencies,
        }


def doctor(root: Path) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    def add(status: str, check: str, message: str, action: str) -> None:
        checks.append({"status": status, "check": check, "message": message, "recommended_action": action})

    version_ok = sys.version_info >= (3, 12)
    add("OK" if version_ok else "FAIL", "python", sys.version.split()[0], "Use Python 3.12 or newer.")
    for relative in ("projects", "prompts", "templates"):
        exists = (root / relative).is_dir()
        add("OK" if exists else "WARN", relative, "present" if exists else "missing", f"Create or restore {relative}/ if required for the pilot.")
    for relative in REQUIRED_PROMPTS:
        exists = (root / "prompts" / relative).is_file()
        add("OK" if exists else "FAIL", f"prompt:{relative}", "present" if exists else "missing", "Restore the required versioned prompt template.")
    db_path = root / ".kdp" / "state.db"
    if not db_path.is_file():
        add("FAIL", "sqlite", "database is missing", "Run the normal project initialization workflow.")
        return checks
    add("OK", "sqlite", "database file is readable", "")
    try:
        with _read_only_session(root) as session:
            table_names = set(sqlalchemy_inspect(session.bind).get_table_names())
            missing = REQUIRED_TABLES - table_names
            add("OK" if not missing else "FAIL", "sqlite.tables", "all required tables present" if not missing else f"missing: {sorted(missing)}", "Use the approved database setup before running the pilot.")
            titles = list(session.scalars(select(TitleRow)))
            for title in titles:
                project = session.get(ProjectRow, title.project_id)
                workspace = root / "projects" / (project.project_id if project else "missing") / "titles" / title.title_id
                add("OK" if workspace.is_dir() else "FAIL", f"workspace:{title.title_id}", "present" if workspace.is_dir() else "missing", "Restore the title workspace or stop the pilot.")
                for asset in session.scalars(select(AssetRow).where(AssetRow.title_id == title.title_id)):
                    path = Path(asset.path)
                    if not path.is_file():
                        add("FAIL", f"asset:{asset.asset_id}", "file is missing", "Restore the file or remove the stale operational record through an explicit maintenance procedure.")
                    elif sha256_file(path) != asset.sha256:
                        add("FAIL", f"asset:{asset.asset_id}", "hash mismatch", "Do not repair automatically; investigate the source file and approval history.")
    except Exception as exc:
        add("FAIL", "sqlite.read", str(exc), "Stop and investigate database access before running the pilot.")
    return checks

