from __future__ import annotations

from pathlib import Path
import json
import typer

from kdp_pipeline.core.state_machine import TitleState
from kdp_pipeline.storage.db import init_db
from kdp_pipeline.storage.service import create_project, create_title, get_title, list_audit, list_jobs, transition_title

app = typer.Typer(help="KDP Pipeline v0.1 — local-first authoring core")


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


if __name__ == "__main__":
    app()
