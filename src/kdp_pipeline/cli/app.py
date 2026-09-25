from __future__ import annotations

from pathlib import Path
import asyncio
import json
import typer
from sqlalchemy import select

from kdp_pipeline.context import ContextManifest
from kdp_pipeline.core.state_machine import TitleState
from kdp_pipeline.chapter import ChapterService, accept_chapter
from kdp_pipeline.continuity import ContinuityService, approve_canon_proposal
from kdp_pipeline.editorial import EditorialService
from kdp_pipeline.inspection import doctor as run_doctor, inspect_title
from kdp_pipeline.models.planning import PlanningArtifactKind
from kdp_pipeline.planning import PlanningService, accept_planning_artifact
from kdp_pipeline.providers.fake import FakeProvider
from kdp_pipeline.storage.db import init_db
from kdp_pipeline.storage.db import CanonProposalRow
from kdp_pipeline.storage.service import (
    advance_to_planned,
    advance_to_drafting,
    advance_to_validated,
    create_project,
    create_title,
    get_title,
    list_audit,
    list_jobs,
    transition_title,
)

app = typer.Typer(help="KDP Pipeline v0.1 — local-first authoring core")
positioning_app = typer.Typer()
brief_app = typer.Typer()
outline_app = typer.Typer()
chapter_card_app = typer.Typer()
planning_app = typer.Typer()
chapter_app = typer.Typer()
editorial_app = typer.Typer()
canon_app = typer.Typer()
inspect_app = typer.Typer()
app.add_typer(positioning_app, name="positioning")
app.add_typer(brief_app, name="brief")
app.add_typer(outline_app, name="outline")
app.add_typer(chapter_card_app, name="chapter-card")
app.add_typer(planning_app, name="planning")
app.add_typer(chapter_app, name="chapter")
app.add_typer(editorial_app, name="editorial")
app.add_typer(canon_app, name="canon")
app.add_typer(inspect_app, name="inspect")


def _root(root: Path | None) -> Path:
    return (root or Path.cwd()).resolve()


@app.command("init-db")
def init_db_cmd(root: Path | None = typer.Option(None, help="Repository root")):
    r = _root(root)
    init_db(r)
    typer.echo(f"Initialized {r / '.kdp' / 'state.db'}")


@app.command("init-project")
def init_project(
    name: str = typer.Argument(...),
    language: str = typer.Option("en"),
    root: Path | None = typer.Option(None),
):
    try:
        row = create_project(_root(root), name, language)
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    typer.echo(row.project_id)


@app.command("new-title")
def new_title(
    project_id: str,
    working_title: str,
    language: str = typer.Option("en"),
    root: Path | None = typer.Option(None),
):
    try:
        row = create_title(_root(root), project_id, working_title, language)
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    typer.echo(row.title_id)


@app.command("status")
def status(title_id: str, root: Path | None = typer.Option(None)):
    row = get_title(_root(root), title_id)
    if not row:
        typer.echo(f"Error: Unknown title: {title_id}", err=True)
        raise typer.Exit(code=1)
    typer.echo(json.dumps({
        "title_id": row.title_id,
        "project_id": row.project_id,
        "working_title": row.working_title,
        "status": row.status,
    }, indent=2))


@app.command("transition")
def transition(title_id: str, target: TitleState, root: Path | None = typer.Option(None)):
    try:
        row = transition_title(_root(root), title_id, target)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=2)
    typer.echo(f"{row.title_id}: {row.status}")


@app.command("audit")
def audit(entity_id: str, root: Path | None = typer.Option(None)):
    rows = list_audit(_root(root), entity_id)
    for r in rows:
        typer.echo(json.dumps({
            "event_id": r.event_id,
            "timestamp": r.timestamp_utc.isoformat(),
            "action": r.action,
            "actor_type": r.actor_type,
            "actor_id": r.actor_id,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "before_hash": r.before_hash,
            "after_hash": r.after_hash,
            "correlation_id": r.correlation_id,
            "result": r.result,
            "metadata": json.loads(r.metadata_json),
        }))


@app.command("jobs")
def jobs(title_id: str, root: Path | None = typer.Option(None)):
    try:
        rows = list_jobs(_root(root), title_id)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)
    for row in rows:
        typer.echo(json.dumps({
            "job_id": row.job_id,
            "title_id": row.title_id,
            "job_type": row.job_type,
            "status": row.status,
            "idempotency_key": row.idempotency_key,
            "input_manifest_hash": row.input_manifest_hash,
            "created_at": row.created_at.isoformat(),
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        }))


def _planning_manifest(title_id: str, task_type: str) -> ContextManifest:
    return ContextManifest(title_id=title_id, task_type=task_type, inputs=[])


def _run_planning(root: Path, title_id: str, kind: PlanningArtifactKind, chapter_number: int | None = None):
    service = PlanningService.generate(
        root,
        title_id=title_id,
        artifact_kind=kind,
        context_manifest=_planning_manifest(title_id, f"planning.{kind.value}"),
        provider=FakeProvider(),
        chapter_number=chapter_number,
    )
    return asyncio.run(service)


def _print_generation_result(result) -> None:
    typer.echo(json.dumps({
        "job_id": result.job.job_id,
        "asset_id": result.asset.asset_id,
        "output_path": str(result.output_path),
    }))


@positioning_app.command("create")
def positioning_create(title_id: str, root: Path | None = typer.Option(None)):
    try:
        _print_generation_result(_run_planning(_root(root), title_id, PlanningArtifactKind.POSITIONING))
    except (OSError, ValueError, RuntimeError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)


@brief_app.command("create")
def brief_create(title_id: str, root: Path | None = typer.Option(None)):
    try:
        _print_generation_result(_run_planning(_root(root), title_id, PlanningArtifactKind.BOOK_BRIEF))
    except (OSError, ValueError, RuntimeError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)


@outline_app.command("generate")
def outline_generate(title_id: str, root: Path | None = typer.Option(None)):
    try:
        _print_generation_result(_run_planning(_root(root), title_id, PlanningArtifactKind.OUTLINE))
    except (OSError, ValueError, RuntimeError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)


@chapter_card_app.command("generate")
def chapter_card_generate(
    title_id: str,
    chapter_number: int = typer.Option(..., min=1),
    root: Path | None = typer.Option(None),
):
    try:
        _print_generation_result(_run_planning(_root(root), title_id, PlanningArtifactKind.CHAPTER_CARD, chapter_number))
    except (OSError, ValueError, RuntimeError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)


@planning_app.command("accept")
def planning_accept(
    asset_id: str,
    reviewer: str = typer.Option(...),
    chapter_number: int | None = typer.Option(None, min=1),
    root: Path | None = typer.Option(None),
):
    try:
        result = accept_planning_artifact(_root(root), asset_id, reviewer=reviewer, chapter_number=chapter_number)
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    typer.echo(json.dumps({"asset_id": result.accepted_asset.asset_id, "approval_id": result.approval.approval_id, "path": str(result.destination_path)}))


@planning_app.command("advance-validated")
def planning_advance_validated(title_id: str, root: Path | None = typer.Option(None)):
    try:
        row = advance_to_validated(_root(root), title_id)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    typer.echo(f"{row.title_id}: {row.status}")


@planning_app.command("advance-planned")
def planning_advance_planned(title_id: str, root: Path | None = typer.Option(None)):
    try:
        row = advance_to_planned(_root(root), title_id)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    typer.echo(f"{row.title_id}: {row.status}")


@chapter_app.command("advance-drafting")
def chapter_advance_drafting(title_id: str, root: Path | None = typer.Option(None)):
    try:
        row = advance_to_drafting(_root(root), title_id)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    typer.echo(f"{row.title_id}: {row.status}")


def _run_chapter(root: Path, title_id: str, chapter_number: int, operation: str, asset_id: str | None = None, finding_ids: list[str] | None = None):
    if operation == "draft":
        return asyncio.run(ChapterService.draft(root, title_id=title_id, chapter_number=chapter_number, provider=FakeProvider()))
    if operation == "revise":
        return asyncio.run(ChapterService.revise(root, title_id=title_id, chapter_number=chapter_number, source_asset_id=asset_id or "", provider=FakeProvider(), finding_ids=finding_ids))
    if operation == "continuity":
        return asyncio.run(ContinuityService.analyze(root, title_id=title_id, chapter_number=chapter_number, source_asset_id=asset_id or "", provider=FakeProvider()))
    return asyncio.run(EditorialService.developmental(root, title_id=title_id, chapter_number=chapter_number, source_asset_id=asset_id or "", provider=FakeProvider()))


@chapter_app.command("draft")
def chapter_draft(title_id: str, chapter_number: int, root: Path | None = typer.Option(None)):
    try:
        _print_generation_result(_run_chapter(_root(root), title_id, chapter_number, "draft"))
    except (OSError, ValueError, RuntimeError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)


@chapter_app.command("continuity")
def chapter_continuity(title_id: str, chapter_number: int, asset_id: str = typer.Option(...), root: Path | None = typer.Option(None)):
    try:
        result = _run_chapter(_root(root), title_id, chapter_number, "continuity", asset_id=asset_id)
    except (OSError, ValueError, RuntimeError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    typer.echo(json.dumps({"finding_id": result.finding.finding_id, "proposal_id": result.proposal.proposal_id, "analysis_asset_id": result.generation.asset.asset_id}))


@editorial_app.command("run")
def editorial_run(title_id: str, chapter_number: int, asset_id: str = typer.Option(...), pass_name: str = typer.Option("developmental", "--pass"), root: Path | None = typer.Option(None)):
    if pass_name != "developmental":
        typer.echo("Error: only the developmental pass is implemented in Sprint 4", err=True)
        raise typer.Exit(code=2)
    try:
        result = _run_chapter(_root(root), title_id, chapter_number, "editorial", asset_id=asset_id)
    except (OSError, ValueError, RuntimeError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    typer.echo(json.dumps({"finding_id": result.finding.finding_id, "analysis_asset_id": result.generation.asset.asset_id}))


@chapter_app.command("revise")
def chapter_revise(title_id: str, chapter_number: int, asset_id: str = typer.Option(...), root: Path | None = typer.Option(None)):
    try:
        _print_generation_result(_run_chapter(_root(root), title_id, chapter_number, "revise", asset_id=asset_id))
    except (OSError, ValueError, RuntimeError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)


@chapter_app.command("accept")
def chapter_accept(title_id: str, chapter_number: int, asset_id: str = typer.Option(...), reviewer: str = typer.Option(...), root: Path | None = typer.Option(None)):
    try:
        result = accept_chapter(_root(root), asset_id, chapter_number=chapter_number, reviewer=reviewer)
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    typer.echo(json.dumps({"asset_id": result.accepted_asset.asset_id, "approval_id": result.approval.approval_id, "path": str(result.destination_path)}))


@canon_app.command("approve")
def canon_approve(proposal_id: str, reviewer: str = typer.Option(...), decision: str = typer.Option(...), root: Path | None = typer.Option(None)):
    try:
        proposal = approve_canon_proposal(_root(root), proposal_id, reviewer=reviewer, decision=decision)
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    typer.echo(f"{proposal.proposal_id}: {proposal.status}")


@canon_app.command("proposals")
def canon_proposals(title_id: str, root: Path | None = typer.Option(None)):
    from kdp_pipeline.storage.service import session_scope

    try:
        with session_scope(_root(root)) as session:
            proposals = list(session.scalars(select(CanonProposalRow).where(CanonProposalRow.title_id == title_id)))
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    for proposal in proposals:
        typer.echo(json.dumps({"proposal_id": proposal.proposal_id, "status": proposal.status, "entity_id": proposal.entity_id, "field": proposal.field}))


def _print_inspection(title_id: str, root: Path, section: str | None = None) -> None:
    report = inspect_title(root, title_id)
    typer.echo(json.dumps(report if section is None else report[section], indent=2, default=str))


@inspect_app.command("title")
def inspect_title_cmd(title_id: str, root: Path | None = typer.Option(None)):
    try:
        _print_inspection(title_id, _root(root))
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)


@inspect_app.command("assets")
def inspect_assets(title_id: str, root: Path | None = typer.Option(None)):
    try:
        _print_inspection(title_id, _root(root), "assets")
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)


@inspect_app.command("jobs")
def inspect_jobs(title_id: str, root: Path | None = typer.Option(None)):
    try:
        _print_inspection(title_id, _root(root), "jobs")
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)


@inspect_app.command("provenance")
def inspect_provenance(title_id: str, root: Path | None = typer.Option(None)):
    try:
        _print_inspection(title_id, _root(root), "provenance")
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)


@inspect_app.command("lifecycle")
def inspect_lifecycle(title_id: str, root: Path | None = typer.Option(None)):
    try:
        report = inspect_title(_root(root), title_id)
        typer.echo(json.dumps({"title": report["title"], "planning": report["planning"], "chapter_lifecycle": report["chapter_lifecycle"], "inconsistencies": report["inconsistencies"]}, indent=2))
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)


@app.command("doctor")
def doctor(root: Path | None = typer.Option(None)):
    for check in run_doctor(_root(root)):
        typer.echo(f"{check['status']}: {check['check']} — {check['message']}")
        if check["status"] != "OK" and check["recommended_action"]:
            typer.echo(f"  Action: {check['recommended_action']}")


if __name__ == "__main__":
    app()
