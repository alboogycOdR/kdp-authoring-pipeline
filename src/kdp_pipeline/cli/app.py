from __future__ import annotations

from pathlib import Path
import asyncio
import json
import typer
from sqlalchemy import select

from kdp_pipeline.context import ContextManifest
from kdp_pipeline.concept import (ConceptService, accept_concept, enable_concept_gate,
                                  score_concept_asset, validate_concept_asset)
from kdp_pipeline.chapters import chapter_status, queue_chapters, record_chapter_summary, resume_queue, stop_queue
from kdp_pipeline.core.state_machine import TitleState
from kdp_pipeline.chapter import ChapterService, accept_chapter
from kdp_pipeline.build import accept_matter, build_manuscript, register_matter
from kdp_pipeline.continuity import ContinuityService, approve_canon_proposal
from kdp_pipeline.editorial import EditorialService
from kdp_pipeline.editorial import StructuredEditorialService, create_revision_recommendation
from kdp_pipeline.inspection import doctor as run_doctor, inspect_title
from kdp_pipeline.verification import (add_verification_flag, decide_rights_record,
    decide_verification, record_rights, scan_scripture_placeholders)
from kdp_pipeline.models.planning import PlanningArtifactKind
from kdp_pipeline.planning import PlanningService, accept_planning_artifact
from kdp_pipeline.release import (create_release_candidate, export_release_packet,
    record_candidate_check, review_release_candidate)
from kdp_pipeline.providers.settings import ProviderProfileSettings
from kdp_pipeline.providers.configuration import (
    add_provider_profile, check_provider_profile, list_provider_profiles,
    select_provider_for_project, set_provider_enabled, set_provider_timeouts, show_provider_profile,
)
from kdp_pipeline.providers.costs import (
    list_model_pricing, project_budget_report, set_model_pricing, set_project_budget,
)
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

app = typer.Typer(help="KDP Pipeline — local-first authoring workflow")
positioning_app = typer.Typer()
brief_app = typer.Typer()
outline_app = typer.Typer()
chapter_card_app = typer.Typer()
planning_app = typer.Typer()
chapter_app = typer.Typer()
editorial_app = typer.Typer()
canon_app = typer.Typer()
inspect_app = typer.Typer()
providers_app = typer.Typer(help="Configure and inspect local provider profiles")
pricing_app = typer.Typer(help="Configure local model pricing")
budget_app = typer.Typer(help="Configure project generation budgets")
concept_app = typer.Typer(help="Develop and validate book concepts")
chapters_app = typer.Typer(help="Queue and inspect bounded chapter work")
verification_app = typer.Typer(help="Track Scripture, source, and expert verification")
rights_app = typer.Typer(help="Track rights and licensing review")
build_app = typer.Typer(help="Assemble accepted manuscript assets")
release_app = typer.Typer(help="Freeze and review release candidates")
app.add_typer(positioning_app, name="positioning")
app.add_typer(brief_app, name="brief")
app.add_typer(outline_app, name="outline")
app.add_typer(chapter_card_app, name="chapter-card")
app.add_typer(planning_app, name="planning")
app.add_typer(chapter_app, name="chapter")
app.add_typer(editorial_app, name="editorial")
app.add_typer(canon_app, name="canon")
app.add_typer(inspect_app, name="inspect")
app.add_typer(providers_app, name="providers")
app.add_typer(pricing_app, name="pricing")
app.add_typer(budget_app, name="budget")
app.add_typer(concept_app, name="concept")
app.add_typer(chapters_app, name="chapters")
app.add_typer(verification_app, name="verify")
app.add_typer(rights_app, name="rights")
app.add_typer(build_app, name="build")
app.add_typer(release_app, name="release")


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
        provider=None,
        chapter_number=chapter_number,
    )
    return asyncio.run(service)


def _print_generation_result(result) -> None:
    typer.echo(json.dumps({
        "job_id": result.job.job_id,
        "asset_id": result.asset.asset_id,
        "output_path": str(result.output_path),
    }))


def _run_concept(root: Path, title_id: str, artifact: str, audience: str = "", asset_id: str | None = None,
                 selection: str = ""):
    return asyncio.run(ConceptService.generate(root, title_id=title_id, artifact=artifact,
                                               audience=audience, concept_asset_id=asset_id, selection=selection))


@concept_app.command("enable")
def concept_enable(title_id: str, root: Path | None = typer.Option(None)):
    try:
        enabled = enable_concept_gate(_root(root), title_id, True)
        typer.echo(json.dumps({"title_id": title_id, "concept_validation_enabled": enabled}))
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True); raise typer.Exit(code=2)


@concept_app.command("disable")
def concept_disable(title_id: str, root: Path | None = typer.Option(None)):
    try:
        enabled = enable_concept_gate(_root(root), title_id, False)
        typer.echo(json.dumps({"title_id": title_id, "concept_validation_enabled": enabled}))
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True); raise typer.Exit(code=2)


@concept_app.command("audience-brief")
def concept_audience_brief(title_id: str, audience: str = typer.Option("", help="Explicit reader age/stage and context"), root: Path | None = typer.Option(None)):
    try: _print_generation_result(_run_concept(_root(root), title_id, "audience-brief", audience))
    except (OSError, ValueError, RuntimeError) as e: typer.echo(f"Error: {e}", err=True); raise typer.Exit(code=2)


@concept_app.command("generate-seeds")
def concept_generate_seeds(title_id: str, asset_id: str = typer.Option(..., help="Audience brief asset"), root: Path | None = typer.Option(None)):
    try: _print_generation_result(_run_concept(_root(root), title_id, "generate-seeds", asset_id=asset_id))
    except (OSError, ValueError, RuntimeError) as e: typer.echo(f"Error: {e}", err=True); raise typer.Exit(code=2)


@concept_app.command("enrich")
def concept_enrich(title_id: str, asset_id: str = typer.Option(..., help="Seed-set asset"), selection: str = typer.Option(..., help="Explicit selected seed label/text"), root: Path | None = typer.Option(None)):
    try: _print_generation_result(_run_concept(_root(root), title_id, "enrich", asset_id=asset_id, selection=selection))
    except (OSError, ValueError, RuntimeError) as e: typer.echo(f"Error: {e}", err=True); raise typer.Exit(code=2)


@concept_app.command("validate")
def concept_validate(asset_id: str, root: Path | None = typer.Option(None)):
    try:
        report, asset = validate_concept_asset(_root(root), asset_id)
        typer.echo(json.dumps({"asset_id": asset.asset_id, "path": asset.path, "report": report}, indent=2))
    except (OSError, ValueError) as e: typer.echo(f"Error: {e}", err=True); raise typer.Exit(code=2)


@concept_app.command("score")
def concept_score(title_id: str, asset_id: str = typer.Option(..., help="Enriched concept brief asset"), root: Path | None = typer.Option(None)):
    try: _print_generation_result(_run_concept(_root(root), title_id, "score", asset_id=asset_id))
    except (OSError, ValueError, RuntimeError) as e: typer.echo(f"Error: {e}", err=True); raise typer.Exit(code=2)


@concept_app.command("approve")
def concept_approve(asset_id: str, reviewer: str = typer.Option(...), root: Path | None = typer.Option(None)):
    try:
        result = accept_concept(_root(root), asset_id, reviewer)
        typer.echo(json.dumps({"asset_id": result.accepted_asset.asset_id, "approval_id": result.approval.approval_id, "path": str(result.destination_path)}))
    except (OSError, ValueError) as e: typer.echo(f"Error: {e}", err=True); raise typer.Exit(code=2)


@concept_app.command("drafting-brief")
def concept_drafting_brief(title_id: str, asset_id: str = typer.Option(..., help="Accepted concept brief asset"), root: Path | None = typer.Option(None)):
    try: _print_generation_result(_run_concept(_root(root), title_id, "drafting-brief", asset_id=asset_id))
    except (OSError, ValueError, RuntimeError) as e: typer.echo(f"Error: {e}", err=True); raise typer.Exit(code=2)


@chapters_app.command("list")
def chapters_list(title_id: str, root: Path | None = typer.Option(None)):
    try: typer.echo(json.dumps(chapter_status(_root(root), title_id), indent=2))
    except (OSError, ValueError) as e: typer.echo(f"Error: {e}", err=True); raise typer.Exit(code=2)


@chapters_app.command("status")
def chapters_status(title_id: str, root: Path | None = typer.Option(None)):
    chapters_list(title_id, root)


@chapters_app.command("queue")
def chapters_queue(title_id: str, through: int = typer.Option(..., min=1), start: int = typer.Option(1, min=1), root: Path | None = typer.Option(None)):
    try:
        rows = queue_chapters(_root(root), title_id, start, through)
        typer.echo(json.dumps([{"chapter_number": r.chapter_number, "status": r.status, "queue_item_id": r.queue_item_id} for r in rows], indent=2))
    except (OSError, ValueError) as e: typer.echo(f"Error: {e}", err=True); raise typer.Exit(code=2)


@chapters_app.command("stop")
def chapters_stop(title_id: str, root: Path | None = typer.Option(None)):
    try: typer.echo(json.dumps({"paused_items": stop_queue(_root(root), title_id)}))
    except (OSError, ValueError) as e: typer.echo(f"Error: {e}", err=True); raise typer.Exit(code=2)


@chapters_app.command("resume")
def chapters_resume(title_id: str, root: Path | None = typer.Option(None)):
    try: typer.echo(json.dumps({"resumed_items": resume_queue(_root(root), title_id)}))
    except (OSError, ValueError) as e: typer.echo(f"Error: {e}", err=True); raise typer.Exit(code=2)


@chapters_app.command("next")
def chapters_next(title_id: str, draft: bool = typer.Option(False, help="Draft only this one queued chapter"), root: Path | None = typer.Option(None)):
    try:
        report = chapter_status(_root(root), title_id)
        candidate = report["next_chapter"]
        if candidate is None:
            typer.echo(json.dumps({"next_chapter": None, "message": "No queued chapter is ready for work.", **report}))
        elif draft:
            if candidate["status"] != "queued":
                raise ValueError(f"Next chapter is {candidate['status']}; draft flag requires a queued chapter")
            _print_generation_result(asyncio.run(ChapterService.draft(_root(root), title_id=title_id,
                chapter_number=candidate["chapter_number"])))
        else:
            typer.echo(json.dumps({"next_chapter": candidate}, indent=2))
    except (OSError, ValueError, RuntimeError) as e: typer.echo(f"Error: {e}", err=True); raise typer.Exit(code=2)


@chapters_app.command("summary")
def chapters_summary(title_id: str, chapter_number: int = typer.Option(..., min=1), asset_id: str = typer.Option(...),
                     summary: str = typer.Option(...), reviewer: str = typer.Option(...), root: Path | None = typer.Option(None)):
    try:
        asset = record_chapter_summary(_root(root), title_id, chapter_number, asset_id, summary, reviewer)
        typer.echo(json.dumps({"asset_id": asset.asset_id, "path": asset.path, "sha256": asset.sha256}))
    except (OSError, ValueError) as e: typer.echo(f"Error: {e}", err=True); raise typer.Exit(code=2)


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
        return asyncio.run(ChapterService.draft(root, title_id=title_id, chapter_number=chapter_number))
    if operation == "revise":
        return asyncio.run(ChapterService.revise(root, title_id=title_id, chapter_number=chapter_number, source_asset_id=asset_id or "", finding_ids=finding_ids))
    if operation == "continuity":
        return asyncio.run(ContinuityService.analyze(root, title_id=title_id, chapter_number=chapter_number, source_asset_id=asset_id or ""))
    return asyncio.run(EditorialService.developmental(root, title_id=title_id, chapter_number=chapter_number, source_asset_id=asset_id or ""))


@providers_app.command("list")
def providers_list(root: Path | None = typer.Option(None)):
    typer.echo(json.dumps(list_provider_profiles(_root(root)), indent=2))


@providers_app.command("show")
def providers_show(provider_id: str, root: Path | None = typer.Option(None)):
    try:
        typer.echo(json.dumps(show_provider_profile(_root(root), provider_id), indent=2))
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2)


@providers_app.command("add-openai-compatible")
def providers_add_openai_compatible(
    provider_id: str, display_name: str, model: str,
    base_url: str = typer.Option("https://api.openai.com/v1"),
    api_key_env: str = typer.Option("OPENAI_API_KEY"),
    max_output_tokens: int = typer.Option(1200, min=1),
    temperature: float = typer.Option(0.0, min=0.0, max=2.0),
    reasoning_effort: str | None = typer.Option(None, help="Lower reasoning effort for supported official OpenAI reasoning models: minimal or low."),
    connect_timeout_seconds: float = typer.Option(60.0, min=0.001),
    read_timeout_seconds: float = typer.Option(60.0, min=0.001),
    write_timeout_seconds: float = typer.Option(60.0, min=0.001),
    pool_timeout_seconds: float = typer.Option(60.0, min=0.001),
    priority: int | None = typer.Option(None),
    root: Path | None = typer.Option(None),
):
    try:
        profile = ProviderProfileSettings(
            provider_id=provider_id, provider_type="openai-compatible", display_name=display_name,
            model=model, base_url=base_url, api_key_env=api_key_env,
            default_max_output_tokens=max_output_tokens, default_temperature=temperature,
            reasoning_effort=reasoning_effort, priority=priority,
            connect_timeout_seconds=connect_timeout_seconds,
            read_timeout_seconds=read_timeout_seconds,
            write_timeout_seconds=write_timeout_seconds,
            pool_timeout_seconds=pool_timeout_seconds,
        )
        typer.echo(json.dumps(add_provider_profile(_root(root), profile), indent=2))
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2)


@providers_app.command("set-timeouts")
def providers_set_timeouts(
    provider_id: str,
    connect_timeout_seconds: float | None = typer.Option(None, min=0.001),
    read_timeout_seconds: float | None = typer.Option(None, min=0.001),
    write_timeout_seconds: float | None = typer.Option(None, min=0.001),
    pool_timeout_seconds: float | None = typer.Option(None, min=0.001),
    root: Path | None = typer.Option(None),
):
    """Update timeout values on an existing OpenAI-compatible provider profile."""
    try:
        profile = set_provider_timeouts(
            _root(root), provider_id,
            connect_timeout_seconds=connect_timeout_seconds,
            read_timeout_seconds=read_timeout_seconds,
            write_timeout_seconds=write_timeout_seconds,
            pool_timeout_seconds=pool_timeout_seconds,
        )
        typer.echo(json.dumps(profile, indent=2))
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2)


@providers_app.command("add-fake")
def providers_add_fake(provider_id: str, display_name: str, model: str = typer.Option("fake-v1"),
                       root: Path | None = typer.Option(None)):
    """Register a deterministic fake profile; selecting it is always explicit."""
    try:
        settings = ProviderProfileSettings(provider_id=provider_id, provider_type="fake",
                                           display_name=display_name, model=model)
        typer.echo(json.dumps(add_provider_profile(_root(root), settings), indent=2))
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2)


@providers_app.command("enable")
def providers_enable(provider_id: str, root: Path | None = typer.Option(None)):
    try:
        typer.echo(json.dumps(set_provider_enabled(_root(root), provider_id, True), indent=2))
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2)


@providers_app.command("disable")
def providers_disable(provider_id: str, root: Path | None = typer.Option(None)):
    try:
        typer.echo(json.dumps(set_provider_enabled(_root(root), provider_id, False), indent=2))
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2)


@providers_app.command("select")
def providers_select(provider_id: str, project_id: str = typer.Option(...), root: Path | None = typer.Option(None)):
    try:
        typer.echo(json.dumps(select_provider_for_project(_root(root), project_id, provider_id)))
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2)


@providers_app.command("check")
def providers_check(provider_id: str, connect: bool = typer.Option(False, "--connect"), root: Path | None = typer.Option(None)):
    try:
        result = check_provider_profile(_root(root), provider_id, connect=connect)
        typer.echo(result.model_dump_json(indent=2))
        if not result.ready:
            raise typer.Exit(code=1)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2)


@pricing_app.command("list")
def pricing_list(provider_id: str | None = typer.Option(None), root: Path | None = typer.Option(None)):
    typer.echo(json.dumps(list_model_pricing(_root(root), provider_id), indent=2))


@pricing_app.command("set")
def pricing_set(
    provider_id: str, model: str,
    input_usd_per_million: float = typer.Option(..., min=0),
    output_usd_per_million: float = typer.Option(..., min=0),
    cached_input_usd_per_million: float | None = typer.Option(None, min=0),
    currency: str = typer.Option("USD"), root: Path | None = typer.Option(None),
):
    try:
        result = set_model_pricing(_root(root), provider_id, model,
                                   input_usd_per_million=input_usd_per_million,
                                   output_usd_per_million=output_usd_per_million,
                                   cached_input_usd_per_million=cached_input_usd_per_million,
                                   currency=currency)
        typer.echo(json.dumps(result, indent=2))
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2)


@budget_app.command("set")
def budget_set(
    project_id: str, monthly_usd: float | None = typer.Option(None, min=0.000001),
    max_run_usd: float | None = typer.Option(None, min=0.000001),
    warning_percent: int = typer.Option(80, min=1, max=100),
    hard_stop: bool = typer.Option(True, "--hard-stop/--soft"),
    root: Path | None = typer.Option(None),
):
    try:
        result = set_project_budget(_root(root), project_id, monthly_limit_usd=monthly_usd,
                                    max_run_estimated_cost_usd=max_run_usd,
                                    warning_percent=warning_percent, hard_stop=hard_stop)
        typer.echo(json.dumps(result, indent=2))
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2)


@budget_app.command("show")
def budget_show(project_id: str, root: Path | None = typer.Option(None)):
    typer.echo(json.dumps(project_budget_report(_root(root), project_id), indent=2))


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
    try:
        if pass_name == "developmental":
            result = _run_chapter(_root(root), title_id, chapter_number, "editorial", asset_id=asset_id)
            typer.echo(json.dumps({"finding_id": result.finding.finding_id, "analysis_asset_id": result.generation.asset.asset_id}))
            return
        result = asyncio.run(StructuredEditorialService.analyze(_root(root), title_id=title_id,
            chapter_number=chapter_number, source_asset_id=asset_id, pass_type=pass_name))
    except (OSError, ValueError, RuntimeError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    typer.echo(json.dumps({"job_id": result.generation.job.job_id, "analysis_asset_id": result.generation.asset.asset_id,
        "pass_type": pass_name, "status": result.output.status,
        "findings": [finding.finding_id for finding in result.findings]}))


@editorial_app.command("recommend")
def editorial_recommend(title_id: str, chapter_number: int, asset_id: str = typer.Option(...),
                        finding_ids: list[str] = typer.Option(..., "--finding-id"), owner: str = typer.Option(...),
                        root: Path | None = typer.Option(None)):
    try:
        result = create_revision_recommendation(_root(root), title_id=title_id, chapter_number=chapter_number,
            source_asset_id=asset_id, finding_ids=finding_ids, owner=owner)
        typer.echo(json.dumps({"recommendation_id": result.recommendation_id, "status": result.status,
                               "finding_ids": finding_ids}))
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)


@verification_app.command("scan-scripture")
def verification_scan_scripture(title_id: str, root: Path | None = typer.Option(None)):
    try:
        result = scan_scripture_placeholders(_root(root), title_id)
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    typer.echo(json.dumps(result))


@verification_app.command("add-flag")
def verification_add_flag(title_id: str, kind: str, locator: str, exact_text: str,
                          reviewer: str = typer.Option(...), asset_id: str | None = typer.Option(None),
                          root: Path | None = typer.Option(None)):
    try:
        row = add_verification_flag(_root(root), title_id=title_id, kind=kind,
            locator=locator, exact_text=exact_text, reviewer=reviewer, asset_id=asset_id)
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    typer.echo(json.dumps({"verification_id": row.verification_id, "kind": row.kind, "status": row.status}))


@verification_app.command("decide")
def verification_decide(verification_id: str, decision: str, reviewer: str = typer.Option(...),
                        rationale: str = typer.Option(...), evidence_reference: str | None = typer.Option(None),
                        reference: str | None = typer.Option(None), source_policy: str | None = typer.Option(None),
                        root: Path | None = typer.Option(None)):
    try:
        row = decide_verification(_root(root), verification_id, decision=decision, reviewer=reviewer,
            rationale=rationale, evidence_reference=evidence_reference, proposed_reference=reference,
            source_policy=source_policy)
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    typer.echo(json.dumps({"verification_id": row.verification_id, "status": row.status,
                           "reference": row.proposed_reference}))


@rights_app.command("add")
def rights_add(title_id: str, material_type: str, description: str, reviewer: str = typer.Option(...),
               asset_id: str | None = typer.Option(None), source: str | None = typer.Option(None),
               provenance_reference: str | None = typer.Option(None),
               legal_basis: str | None = typer.Option(None), evidence_reference: str | None = typer.Option(None),
               territories: list[str] = typer.Option([]), term: str | None = typer.Option(None),
               restrictions: str | None = typer.Option(None), root: Path | None = typer.Option(None)):
    try:
        row = record_rights(_root(root), title_id=title_id, material_type=material_type,
            description=description, reviewer=reviewer, asset_id=asset_id, source=source,
            provenance_reference=provenance_reference,
            legal_basis=legal_basis, evidence_reference=evidence_reference,
            territories=territories, term=term, restrictions=restrictions)
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    typer.echo(json.dumps({"rights_record_id": row.rights_record_id, "status": row.status}))


@rights_app.command("decide")
def rights_decide(rights_record_id: str, decision: str, reviewer: str = typer.Option(...),
                  rationale: str = typer.Option(...), root: Path | None = typer.Option(None)):
    try:
        row = decide_rights_record(_root(root), rights_record_id, decision=decision,
            reviewer=reviewer, rationale=rationale)
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    typer.echo(json.dumps({"rights_record_id": row.rights_record_id, "status": row.status}))


@build_app.command("manuscript")
def manuscript_build(title_id: str, builder: str = typer.Option("cli-user"),
                     root: Path | None = typer.Option(None)):
    try:
        result = build_manuscript(_root(root), title_id=title_id, builder=builder)
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    typer.echo(json.dumps({"build_id": result.build.build_id, "asset_id": result.asset.asset_id,
        "status": result.build.status, "path": result.asset.path,
        "manifest_path": result.build.manifest_path, "blocker_count": len(result.manifest["blockers"])}))


@build_app.command("matter-add")
def manuscript_matter_add(title_id: str, section: str, source_file: Path,
                          creator: str = typer.Option(...), root: Path | None = typer.Option(None)):
    try:
        row = register_matter(_root(root), title_id=title_id, section=section,
            source_path=source_file, creator=creator)
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    typer.echo(json.dumps({"asset_id": row.asset_id, "asset_type": row.asset_type,
                           "approval_status": row.approval_status, "path": row.path}))


@build_app.command("matter-accept")
def manuscript_matter_accept(asset_id: str, reviewer: str = typer.Option(...),
                             root: Path | None = typer.Option(None)):
    try:
        asset, approval = accept_matter(_root(root), asset_id, reviewer=reviewer)
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    typer.echo(json.dumps({"asset_id": asset.asset_id, "approval_id": approval.approval_id,
                           "path": asset.path}))


@release_app.command("candidate")
def release_candidate(title_id: str, build_id: str, creator: str = typer.Option(...),
                      root: Path | None = typer.Option(None)):
    try:
        row = create_release_candidate(_root(root), title_id=title_id,
            build_id=build_id, creator=creator)
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    typer.echo(json.dumps({"candidate_id": row.candidate_id, "status": row.status,
        "candidate_sha256": row.candidate_sha256}))


@release_app.command("check")
def release_check(candidate_id: str, domain: str, key: str, decision: str,
                  reviewer: str = typer.Option(...), rationale: str = typer.Option(...),
                  evidence_reference: str = typer.Option(...), value: str | None = typer.Option(None),
                  statement: str | None = typer.Option(None), root: Path | None = typer.Option(None)):
    try:
        row = record_candidate_check(_root(root), candidate_id, domain=domain, key=key,
            decision=decision, reviewer=reviewer, rationale=rationale,
            evidence_reference=evidence_reference, value=value, statement=statement)
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    typer.echo(json.dumps({"candidate_id": row.candidate_id, "status": row.status}))


@release_app.command("review")
def release_review(candidate_id: str, decision: str, reviewer: str = typer.Option(...),
                   rationale: str = typer.Option(...), root: Path | None = typer.Option(None)):
    try:
        row, approval = review_release_candidate(_root(root), candidate_id, decision=decision,
            reviewer=reviewer, rationale=rationale)
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    typer.echo(json.dumps({"candidate_id": row.candidate_id, "status": row.status,
        "approval_id": approval.approval_id if approval else None,
        "approved": approval is not None and approval.decision == "accepted"}))


@release_app.command("packet")
def release_packet(candidate_id: str, creator: str = typer.Option(...),
                   root: Path | None = typer.Option(None)):
    try:
        row, asset = export_release_packet(_root(root), candidate_id, creator=creator)
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    typer.echo(json.dumps({"packet_id": row.packet_id, "asset_id": asset.asset_id,
                           "path": asset.path, "sha256": row.sha256}))


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


@inspect_app.command("concept")
def inspect_concept(title_id: str, root: Path | None = typer.Option(None)):
    try:
        _print_inspection(title_id, _root(root), "concept")
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)


@inspect_app.command("editorial")
def inspect_editorial(title_id: str, root: Path | None = typer.Option(None)):
    try:
        _print_inspection(title_id, _root(root), "editorial")
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)


@inspect_app.command("verification")
def inspect_verification(title_id: str, root: Path | None = typer.Option(None)):
    try:
        _print_inspection(title_id, _root(root), "verification")
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)


@inspect_app.command("builds")
def inspect_builds(title_id: str, root: Path | None = typer.Option(None)):
    try:
        _print_inspection(title_id, _root(root), "builds")
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)


@inspect_app.command("release")
def inspect_release(title_id: str, root: Path | None = typer.Option(None)):
    try:
        _print_inspection(title_id, _root(root), "release")
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


@inspect_app.command("usage")
def inspect_usage(title_id: str, root: Path | None = typer.Option(None)):
    try:
        _print_inspection(title_id, _root(root), "usage")
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)


@inspect_app.command("provider")
def inspect_provider(title_id: str, root: Path | None = typer.Option(None)):
    try:
        _print_inspection(title_id, _root(root), "provider")
    except (OSError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)


@inspect_app.command("budget")
def inspect_budget(title_id: str, root: Path | None = typer.Option(None)):
    try:
        _print_inspection(title_id, _root(root), "budget")
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
