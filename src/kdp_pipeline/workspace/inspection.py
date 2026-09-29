from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import select

from kdp_pipeline.inspection.service import _read_only_session, inspect_title
from kdp_pipeline.providers.costs import project_budget_report
from kdp_pipeline.storage.db import (
    AuditEventRow, ModelPricingRow,
    ProjectProviderSelectionRow,
    ProjectRow,
    ProviderProfileRow,
    TitleRow,
)


def inspect_workspace(root: Path) -> dict:
    """Collect a safe, read-only snapshot for the local operator workspace."""
    root = root.resolve()
    with _read_only_session(root) as session:
        projects = list(session.scalars(select(ProjectRow).order_by(ProjectRow.created_at, ProjectRow.project_id)))
        titles = list(session.scalars(select(TitleRow).order_by(TitleRow.created_at, TitleRow.title_id)))
        titles_by_project: dict[str, list[TitleRow]] = {}
        for title in titles:
            titles_by_project.setdefault(title.project_id, []).append(title)

        project_rows = []
        for project in projects:
            selection = session.get(ProjectProviderSelectionRow, project.project_id)
            provider = session.get(ProviderProfileRow, selection.provider_id) if selection and selection.provider_id else None
            needs_key = bool(provider and provider.provider_type == "openai-compatible")
            key_configured = bool(provider and provider.api_key_env and os.getenv(provider.api_key_env))
            project_rows.append({
                "project_id": project.project_id,
                "name": project.name,
                "status": project.status,
                "provider": ({
                    "provider_id": provider.provider_id,
                    "display_name": provider.display_name,
                    "model": provider.model,
                    "enabled": provider.enabled,
                    "ready": bool(provider.enabled and (not needs_key or key_configured)),
                } if provider else None),
                "title_ids": [title.title_id for title in titles_by_project.get(project.project_id, [])],
            })

        activity_rows = list(session.scalars(
            select(AuditEventRow).order_by(AuditEventRow.timestamp_utc.desc(), AuditEventRow.event_id.desc()).limit(40)
        ))
        recent_activity = [{
            "event_id": row.event_id,
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "result": row.result,
            "timestamp": row.timestamp_utc.isoformat(),
            "correlation_id": row.correlation_id,
        } for row in activity_rows]
        profiles = list(session.scalars(select(ProviderProfileRow).where(
            ProviderProfileRow.enabled.is_(True)).order_by(ProviderProfileRow.display_name)))
        available_providers = [{
            "provider_id": row.provider_id,
            "display_name": row.display_name,
            "model": row.model,
            "ready": row.provider_type != "openai-compatible" or bool(row.api_key_env and os.getenv(row.api_key_env)),
            "priced": session.get(ModelPricingRow, (row.provider_id, row.model)) is not None,
        } for row in profiles]

    title_reports = {title_id: inspect_title(root, title_id) for title in titles for title_id in [title.title_id]}
    budgets = {project["project_id"]: project_budget_report(root, project["project_id"]) for project in project_rows}
    return {
        "projects": project_rows,
        "titles": title_reports,
        "budgets": budgets,
        "available_providers": available_providers,
        "recent_activity": recent_activity,
    }
