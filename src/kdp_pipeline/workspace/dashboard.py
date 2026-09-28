from __future__ import annotations

import html
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from kdp_pipeline.inspection.service import _read_only_session, inspect_title
from kdp_pipeline.storage.db import (
    ProjectBudgetRow,
    ProjectProviderSelectionRow,
    ProjectRow,
    ProviderProfileRow,
    TitleRow,
)
from kdp_pipeline.storage.files import write_text


@dataclass(frozen=True)
class DashboardResult:
    output_path: Path
    project_count: int
    title_count: int


def _e(value: object) -> str:
    return html.escape(str(value if value is not None else "—"), quote=True)


def _list(items: list[str], empty: str = "None") -> str:
    if not items:
        return f"<p class=muted>{_e(empty)}</p>"
    return "<ul>" + "".join(f"<li>{_e(item)}</li>" for item in items) + "</ul>"


def _title_card(report: dict) -> str:
    title = report["title"]
    concept = report["concept"]
    planning = report["planning"]
    chapter = report["chapter_workflow"]
    findings = report["findings"]
    proposals = report["proposals"]
    verification = report["verification"]
    build_records = report["builds"]["records"]
    release = report["release"]
    assets = report["assets"]
    pending_types = {"concept.brief", "planning.positioning", "planning.book-brief",
        "planning.outline", "planning.chapter-card", "chapter.draft", "chapter.revision"}
    pending = [f"{item['asset_type']} — {item['asset_id']}" for item in assets
        if item["approval_status"] == "experimental" and item["asset_type"] in pending_types]
    pending.extend(f"release candidate — {candidate['candidate_id']} ({candidate['status']})"
        for candidate in release["candidates"]
        if candidate["status"] in {"blocked", "pending_human_review", "held"})
    statuses = [f"Chapter {item['chapter_number']}: {item['status']}" for item in chapter["chapters"]]
    planning_summary = [f"{name.replace('_', ' ').title()}: {'complete' if item['complete'] else 'missing'}"
                        for name, item in planning.items()]
    pass_counts: dict[str, int] = {}
    for finding in findings:
        if finding["status"] == "open":
            pass_counts[finding["pass_type"]] = pass_counts.get(finding["pass_type"], 0) + 1
    editorial_summary = [f"{name}: {count} open" for name, count in sorted(pass_counts.items())]
    proposal_summary = [f"{item['proposal_id']}: {item['status']}" for item in proposals]
    verification_summary = []
    for item in verification["release_blockers"]:
        identifier = item.get("id")
        detail = item.get("kind", item.get("condition", item.get("material_type")))
        label = item["type"]
        if identifier:
            label += f" {identifier}"
        if detail:
            label += f": {detail}"
        verification_summary.append(label)
    build_summary = [f"{item['build_id']}: {item['status']} ({item['output_format']})" for item in build_records]
    release_summary = [f"{item['candidate_id']}: {item['status']} ({len(item['current_blockers'])} blockers)"
                       for item in release["candidates"]]
    accepted_plans = sum(bool(item["complete"]) for item in planning.values())
    return f"""<details class=title-card>
<summary><strong>{_e(title['working_title'])}</strong> <span class=badge>{_e(title['status'])}</span>
<span class=muted>{_e(title['title_id'])}</span></summary>
<div class=grid>
<section><h4>Concept and planning</h4><p>Concept gate: {_e('enabled' if concept['enabled'] else 'off')} · Positioning {_e('unlocked' if concept['positioning_unlocked'] else 'locked')}</p>
<p>Planning artefacts: {_e(accepted_plans)}/{_e(len(planning))} complete</p>{_list(planning_summary)}
<p>Concept flags: {_e(len(concept['outstanding_research_content_flags']))}; warnings: {_e(len(concept['validation_warnings']))}</p></section>
<section><h4>Chapters</h4><p>Accepted: {_e(chapter['accepted_chapter_count'])} · Tracked: {_e(chapter['chapter_count'])}</p>{_list(statuses)}</section>
<section><h4>Editorial and canon</h4>{_list(editorial_summary, 'No open editorial findings')}{_list(proposal_summary, 'No canon proposals')}</section>
<section><h4>Verification blockers</h4><p>{_e(len(verification['release_blockers']))} unresolved</p>{_list(verification_summary)}</section>
<section><h4>Builds</h4>{_list(build_summary, 'No manuscript builds')}</section>
<section><h4>Release candidates</h4>{_list(release_summary, 'No release candidates')}</section>
<section><h4>Human review queue</h4>{_list(pending, 'No pending asset or release review')}</section>
</div></details>"""


def generate_dashboard(root: Path, *, output_path: Path | None = None) -> DashboardResult:
    """Generate a read-only static workspace view from current inspection services."""
    root = root.resolve()
    with _read_only_session(root) as session:
        projects = list(session.scalars(select(ProjectRow).order_by(ProjectRow.created_at)))
        titles = list(session.scalars(select(TitleRow).order_by(TitleRow.created_at)))
        titles_by_project: dict[str, list[TitleRow]] = {}
        for title in titles:
            titles_by_project.setdefault(title.project_id, []).append(title)
        project_summaries = []
        for project in projects:
            selection = session.get(ProjectProviderSelectionRow, project.project_id)
            provider = session.get(ProviderProfileRow, selection.provider_id) if selection and selection.provider_id else None
            budget = session.get(ProjectBudgetRow, project.project_id)
            configured = bool(provider and provider.enabled)
            if provider and provider.api_key_env:
                configured = configured and bool(os.getenv(provider.api_key_env))
            project_summaries.append({"project": project, "provider": provider,
                "provider_ready": configured, "budget": budget,
                "titles": list(titles_by_project.get(project.project_id, []))})

    rendered_projects = []
    for item in project_summaries:
        project = item["project"]
        provider = item["provider"]
        budget = item["budget"]
        title_reports = [inspect_title(root, title.title_id) for title in item["titles"]]
        titles_html = "".join(_title_card(report) for report in title_reports)
        if provider is None:
            provider_text = "No provider selected"
        else:
            provider_text = (f"{provider.display_name} · {provider.model} · "
                f"{'ready' if item['provider_ready'] else 'check provider readiness'}")
        tokens_in = sum(report["usage"]["monthly_input_tokens"] for report in title_reports)
        tokens_out = sum(report["usage"]["monthly_output_tokens"] for report in title_reports)
        cost = sum(report["usage"]["monthly_cost"] for report in title_reports)
        cost_text = f"${cost:.4f}"
        unknown_cost = sum(report["usage"]["unknown_cost_events"] for report in title_reports)
        if budget is None:
            budget_text = "Budget not configured"
        else:
            budget_text = f"Monthly limit: ${_e(budget.monthly_limit_usd)} · hard stop: {_e(budget.hard_stop)}"
        provider_model = provider.model if provider else "—"
        rendered_projects.append(f"""<article class=project-card>
<header><h2>{_e(project.name)}</h2><span class=badge>{_e(project.status)}</span><p class=muted>{_e(project.project_id)}</p></header>
<div class=project-summary><div><strong>Provider readiness</strong><p>{_e(provider_text)}</p><small>Model: {_e(provider_model)}</small></div>
<div><strong>Budget and usage this month</strong><p>{_e(budget_text)}</p>
<small>Tokens in/out: {_e(tokens_in)}/{_e(tokens_out)} · Known USD cost: {_e(cost_text)} · Unknown cost events: {_e(unknown_cost)}</small></div>
<div><strong>Titles</strong><p>{_e(len(title_reports))}</p></div></div>
{titles_html if titles_html else '<p class=muted>No titles yet.</p>'}</article>""")

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>KDP Pipeline Operator Workspace</title>
<style>
:root{{color-scheme:light;--ink:#20252b;--muted:#5d6874;--line:#d8dee5;--paper:#f5f7f9;--card:#fff;--accent:#1d5d64}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 system-ui,Segoe UI,sans-serif}}
main{{max-width:1280px;margin:0 auto;padding:2rem 1.25rem 4rem}}h1{{margin:0 0 .3rem;font-size:1.8rem}}h2{{margin:0;font-size:1.3rem}}h3{{font-size:1.05rem}}h4{{margin:.2rem 0 .5rem;color:var(--accent)}}
.muted,small{{color:var(--muted)}}.notice{{padding:.8rem 1rem;background:#e9f1f0;border-left:4px solid var(--accent);margin:1rem 0 1.5rem}}
.project-card{{background:var(--card);border:1px solid var(--line);border-radius:12px;margin:1rem 0;padding:1.2rem}}
.project-card header{{display:flex;align-items:center;gap:.75rem;flex-wrap:wrap}}.project-card header p{{width:100%;margin:0}}
.project-summary{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:.8rem;margin:1rem 0}}
.project-summary>div,.grid section{{border:1px solid var(--line);border-radius:8px;padding:.8rem;background:#fff}}
.project-summary p{{margin:.25rem 0}}.title-card{{border-top:1px solid var(--line);padding:.8rem 0}}
.title-card summary{{cursor:pointer;list-style:none;display:flex;align-items:center;gap:.7rem;flex-wrap:wrap}}
.title-card summary::-webkit-details-marker{{display:none}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:.8rem;margin:1rem 0}}
.badge{{display:inline-block;background:#edf1f4;border-radius:999px;padding:.15rem .6rem;font-size:.8rem}}
ul{{margin:.3rem 0;padding-left:1.2rem}}li{{overflow-wrap:anywhere}}footer{{margin-top:2rem;border-top:1px solid var(--line);padding-top:1rem;color:var(--muted);font-size:.85rem}}
</style></head><body><main><h1>KDP Pipeline Operator Workspace</h1>
<p class=muted>Local read-only Workspace snapshot · Generated {_e(datetime.now(timezone.utc).isoformat())}</p>
<p class=notice>This report is read-only. It shows workflow status and review blockers; it does not approve content or publish to KDP.</p>
{''.join(rendered_projects) if rendered_projects else '<p>No projects found.</p>'}
<footer>Provider secrets, credentials, raw prompts, and provider response bodies are not included.</footer>
</main></body></html>"""
    destination = output_path or Path("reports/operator-workspace.html")
    if not destination.is_absolute():
        destination = root / destination
    destination = destination.resolve()
    write_text(destination, page)
    return DashboardResult(destination, len(project_summaries), len(titles))
