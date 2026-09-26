from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, inspect as sqlalchemy_inspect, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from kdp_pipeline.models.planning import PlanningArtifactKind, spec_for
from kdp_pipeline.storage.db import (
    AssetRow, ApprovalRow, AuditEventRow, CanonProposalRow, EditorialFindingRow,
    JobRow, ProjectRow, ProvenanceRow, TitleRow,
    ProviderProfileRow, ProjectProviderSelectionRow, ProjectBudgetRow,
    UsageEventRow, BudgetReservationRow, ModelPricingRow,
)
from kdp_pipeline.storage.files import sha256_file


REQUIRED_TABLES = {
    "projects", "titles", "assets", "jobs", "provenance", "approvals",
    "editorial_findings", "canon_proposals", "audit_events",
    "provider_profiles", "project_provider_selections", "model_pricing",
    "project_budgets", "budget_reservations", "usage_events",
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
        selection = session.get(ProjectProviderSelectionRow, title.project_id)
        provider = session.get(ProviderProfileRow, selection.provider_id) if selection and selection.provider_id else None
        usage_rows = list(session.scalars(select(UsageEventRow).where(UsageEventRow.title_id == title_id).order_by(UsageEventRow.created_at.desc())))
        related_entity_ids = ([row.asset_id for row in assets] + [row.job_id for row in jobs]
                              + [row.approval_id for row in approvals] + [row.provenance_id for row in provenance]
                              + [row.finding_id for row in findings] + [row.proposal_id for row in proposals]
                              + [row.usage_event_id for row in usage_rows])
        audit = list(session.scalars(select(AuditEventRow).where(or_(
            AuditEventRow.correlation_id.in_([title_id, title.project_id]),
            AuditEventRow.entity_id.in_(related_entity_ids),
        )).order_by(AuditEventRow.timestamp_utc.desc()).limit(25)))
        budget = session.get(ProjectBudgetRow, title.project_id)
        reservations = list(session.scalars(select(BudgetReservationRow).where(BudgetReservationRow.project_id == title.project_id)))
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        monthly_usage = [row for row in usage_rows if row.created_at.strftime("%Y-%m") == month]
        spent = sum(row.estimated_cost or 0.0 for row in monthly_usage if row.currency == "USD")
        reserved = sum(row.estimated_cost_usd or 0.0 for row in reservations if row.month == month and row.status in {"reserved", "uncertain", "unpriced"})
        usage_groups: dict[tuple[str, str], dict] = {}
        for row in usage_rows:
            group = usage_groups.setdefault((row.provider, row.model), {
                "provider": row.provider, "model": row.model, "events": 0,
                "input_tokens": 0, "output_tokens": 0, "usd_cost": 0.0,
                "unknown_cost_events": 0,
            })
            group["events"] += 1
            group["input_tokens"] += row.input_tokens or 0
            group["output_tokens"] += row.output_tokens or 0
            group["usd_cost"] += row.estimated_cost or 0.0 if row.currency == "USD" else 0.0
            group["unknown_cost_events"] += int(row.source == "unknown" or
                                                 (row.estimated_cost is not None and row.currency != "USD"))
        budget_warning = None
        if budget and budget.monthly_limit_usd is not None:
            projected = spent + reserved
            if projected >= budget.monthly_limit_usd * budget.warning_percent / 100:
                budget_warning = f"Monthly budget warning threshold ({budget.warning_percent}%) reached"
        if any(row.source == "unknown" or (row.estimated_cost is not None and row.currency != "USD")
               for row in monthly_usage):
            budget_warning = (budget_warning + "; " if budget_warning else "") + "Some usage has unknown cost or non-USD currency"

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
            "provider": ({"provider_id": provider.provider_id, "provider_type": provider.provider_type,
                          "display_name": provider.display_name, "enabled": provider.enabled,
                          "model": provider.model, "api_key_env": provider.api_key_env,
                          "api_key_configured": bool(os.getenv(provider.api_key_env)) if provider.api_key_env else False}
                         if provider else {"provider_id": None, "selected": False}),
            "usage": {"recent_events": [{"usage_event_id": row.usage_event_id, "provider": row.provider,
                        "model": row.model, "input_tokens": row.input_tokens, "output_tokens": row.output_tokens,
                        "total_tokens": row.total_tokens, "estimated_cost": row.estimated_cost,
                        "currency": row.currency, "source": row.source,
                        "cost_details": json.loads(row.cost_details_json or "{}"),
                        "created_at": row.created_at.isoformat()}
                        for row in usage_rows[:20]],
                      "monthly_input_tokens": sum(row.input_tokens or 0 for row in monthly_usage),
                      "monthly_output_tokens": sum(row.output_tokens or 0 for row in monthly_usage),
                      "monthly_cost": round(spent, 8),
                      "by_provider_model": list(usage_groups.values()),
                      "unknown_cost_events": sum(row.source == "unknown" or
                                                  (row.estimated_cost is not None and row.currency != "USD")
                                                  for row in monthly_usage)},
            "budget": ({"configured": True, "monthly_limit_usd": budget.monthly_limit_usd,
                        "max_run_estimated_cost_usd": budget.max_run_estimated_cost_usd,
                        "hard_stop": budget.hard_stop, "spent_usd": round(spent, 8),
                        "reserved_usd": round(reserved, 8),
                        "remaining_usd": round(max(0.0, budget.monthly_limit_usd - spent - reserved), 8) if budget.monthly_limit_usd is not None else None,
                        "unknown_cost_events": sum(row.source == "unknown" or
                                                    (row.estimated_cost is not None and row.currency != "USD")
                                                    for row in monthly_usage),
                        "warning": budget_warning}
                       if budget else {"configured": False}),
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
            if not missing:
                projects = list(session.scalars(select(ProjectRow)))
                for project in projects:
                    selected = session.get(ProjectProviderSelectionRow, project.project_id)
                    selected_profile = (session.get(ProviderProfileRow, selected.provider_id)
                                         if selected and selected.provider_id else None)
                    if selected_profile is None:
                        add("WARN", f"provider-selection:{project.project_id}", "no provider selected",
                            "Select an enabled provider profile before running generation.")
                    elif not selected_profile.enabled:
                        add("FAIL", f"provider-selection:{project.project_id}", "selected provider is disabled",
                            "Enable the selected profile or explicitly select another profile.")
                profiles = list(session.scalars(select(ProviderProfileRow)))
                for profile in profiles:
                    configured = bool(os.getenv(profile.api_key_env)) if profile.api_key_env else True
                    status = "OK" if configured or profile.provider_type == "fake" else "WARN"
                    message = "enabled" if profile.enabled else "disabled"
                    if profile.api_key_env:
                        message += f"; {profile.api_key_env} {'present' if configured else 'missing'}"
                    add(status, f"provider:{profile.provider_id}", message,
                        "Set the referenced environment variable or select a profile that does not require one.")
                events = list(session.scalars(select(UsageEventRow)))
                unknown = sum(event.source == "unknown" for event in events)
                add("WARN" if unknown else "OK", "usage.pricing", f"{unknown} usage event(s) have unknown cost",
                    "Configure model pricing or accept that these costs cannot be budgeted.")
                budgets = list(session.scalars(select(ProjectBudgetRow)))
                for budget in budgets:
                    project_events = [event for event in events if event.project_id == budget.project_id
                                      and event.created_at.strftime("%Y-%m") == datetime.now(timezone.utc).strftime("%Y-%m")]
                    spent_usd = sum(event.estimated_cost or 0.0 for event in project_events if event.currency == "USD")
                    status = "OK"
                    message = f"monthly usage ${spent_usd:.6f}"
                    if budget.monthly_limit_usd is not None:
                        ratio = spent_usd / budget.monthly_limit_usd
                        message += f" / ${budget.monthly_limit_usd:.6f}"
                        if ratio >= 1:
                            status = "FAIL" if budget.hard_stop else "WARN"
                        elif ratio >= budget.warning_percent / 100:
                            status = "WARN"
                    if any(event.source == "unknown" for event in project_events):
                        status = "WARN" if status == "OK" else status
                        message += "; unpriced usage exists"
                    add(status, f"budget:{budget.project_id}", message,
                        "Review project budget, pricing, and usage before continuing generation.")
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
        add("FAIL", "sqlite.read", f"database inspection failed ({type(exc).__name__})", "Stop and investigate database access before running the pilot.")
    return checks

