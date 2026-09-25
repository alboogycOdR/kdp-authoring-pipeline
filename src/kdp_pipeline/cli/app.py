from __future__ import annotations

from pathlib import Path
import asyncio
import json
import typer

from kdp_pipeline.context import ContextManifest
from kdp_pipeline.core.state_machine import TitleState
from kdp_pipeline.models.planning import PlanningArtifactKind
from kdp_pipeline.planning import PlanningService, accept_planning_artifact
from kdp_pipeline.providers.fake import FakeProvider
from kdp_pipeline.storage.db import init_db
from kdp_pipeline.storage.service import (
    advance_to_planned,
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
app.add_typer(positioning_app, name="positioning")
app.add_typer(brief_app, name="brief")
app.add_typer(outline_app, name="outline")
app.add_typer(chapter_card_app, name="chapter-card")
app.add_typer(planning_app, name="planning")


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


if __name__ == "__main__":
    app()
