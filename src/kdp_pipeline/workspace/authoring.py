"""Browser authoring actions routed through the existing audited services."""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
from pathlib import Path

from sqlalchemy import select

from kdp_pipeline.chapter.service import ChapterService
from kdp_pipeline.chapters.service import record_chapter_summary
from kdp_pipeline.concept.service import ConceptService, enable_concept_gate, validate_concept_asset
from kdp_pipeline.context import ContextManifest
from kdp_pipeline.continuity.service import ContinuityService
from kdp_pipeline.editorial.service import EditorialService, StructuredEditorialService, STRUCTURED_PASSES
from kdp_pipeline.models.planning import PlanningArtifactKind
from kdp_pipeline.planning.service import PlanningService
from kdp_pipeline.providers.configuration import select_provider_for_project
from kdp_pipeline.providers.costs import set_project_budget
from kdp_pipeline.storage.db import AssetRow, ModelPricingRow, ProjectRow, ProviderProfileRow, TitleRow
from kdp_pipeline.storage.db import ProvenanceRow, utcnow
from kdp_pipeline.storage.audit import AuditEventWriter
from kdp_pipeline.core.ids import new_id
from kdp_pipeline.storage.files import sha256_file, write_text
from kdp_pipeline.storage.service import (
    advance_to_drafting, advance_to_planned, advance_to_validated,
    create_project, create_title, register_asset, session_scope,
)


GENERATION_ACTIONS = {
    "audience-brief", "concept-seeds", "concept-enrich", "concept-score",
    "concept-drafting-brief", "positioning", "book-brief", "outline", "chapter-card",
    "draft-chapter", "continuity", "developmental", "editorial-pass", "revise-chapter",
}
AUTHORING_ACTIONS = GENERATION_ACTIONS | {
    "save-idea", "concept-enable", "concept-validate", "advance-validated", "advance-planned",
    "advance-drafting", "chapter-summary",
}


def _required(form: dict[str, str], key: str, limit: int = 500) -> str:
    value = form.get(key, "").strip()
    if not value or len(value) > limit:
        raise ValueError(f"{key.replace('_', ' ').title()} is required (up to {limit} characters).")
    return value


def _number(form: dict[str, str], key: str) -> int:
    value = _required(form, key, 3)
    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 999:
        raise ValueError(f"{key.replace('_', ' ').title()} must be from 1 to 999.")
    return int(value)


def _money(form: dict[str, str], key: str) -> float:
    try:
        value = float(_required(form, key, 20))
    except ValueError as exc:
        raise ValueError(f"{key.replace('_', ' ').title()} must be a USD amount.") from exc
    if not math.isfinite(value) or not 0 < value <= 10000:
        raise ValueError(f"{key.replace('_', ' ').title()} must be above zero and at most $10,000.")
    return value


def _priced_profile(root: Path, provider_id: str) -> None:
    with session_scope(root) as session:
        profile = session.get(ProviderProfileRow, provider_id)
        if profile is None or not profile.enabled:
            raise ValueError("Select an enabled provider profile.")
        if profile.provider_type == "openai-compatible" and not (profile.api_key_env and os.getenv(profile.api_key_env)):
            raise ValueError("The selected provider credential is not configured on this server.")
        if session.get(ModelPricingRow, (provider_id, profile.model)) is None:
            raise ValueError("This provider and model need configured pricing before browser generation.")


def _record_idea(root: Path, title_id: str, idea: str, audience: str, operator: str) -> str:
    path = root / "projects" / _project_id(root, title_id) / "titles" / title_id / "04_plan" / "concepts" / "operator-idea.md"
    if path.exists():
        raise ValueError("An idea note already exists for this title.")
    write_text(path, f"# Operator idea\n\n## Intended reader\n\n{audience}\n\n## Book idea\n\n{idea}\n")
    try:
        asset = register_asset(root, title_id, path, "concept.idea-note", creator=operator,
                               creator_type="human", ai_classification="not_ai_generated")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return asset.asset_id


def _project_id(root: Path, title_id: str) -> str:
    with session_scope(root) as session:
        title = session.get(TitleRow, title_id)
        if title is None:
            raise ValueError("Title not found.")
        return title.project_id


def _controls(root: Path, project_id: str, form: dict[str, str]) -> str:
    provider_id = _required(form, "provider_id", 80)
    monthly = _money(form, "monthly_usd")
    per_run = _money(form, "max_run_usd")
    if per_run > monthly:
        raise ValueError("Per-run limit must not exceed the monthly limit.")
    _priced_profile(root, provider_id)
    select_provider_for_project(root, project_id, provider_id)
    set_project_budget(root, project_id, monthly_limit_usd=monthly,
                       max_run_estimated_cost_usd=per_run,
                       warning_percent=80, hard_stop=True)
    return f"Provider {provider_id} selected; ${monthly:g}/month and ${per_run:g}/run hard limits recorded."


def create_book(root: Path, form: dict[str, str]) -> tuple[str, str]:
    """Create an IDEA title with a human idea note and priced, hard-stop controls."""
    operator = _required(form, "operator", 100)
    project_name = _required(form, "project_name", 200)
    title_name = _required(form, "title_name", 200)
    audience = _required(form, "audience", 1000)
    idea = _required(form, "idea", 4000)
    # Validate all operator inputs before the first durable mutation.
    if _money(form, "max_run_usd") > _money(form, "monthly_usd"):
        raise ValueError("Per-run limit must not exceed the monthly limit.")
    _priced_profile(root, _required(form, "provider_id", 80))
    project = create_project(root, project_name, actor_id=operator)
    _controls(root, project.project_id, form)
    title = create_title(root, project.project_id, title_name, actor_id=operator)
    idea_asset_id = _record_idea(root, title.title_id, idea, audience, operator)
    enable_concept_gate(root, title.title_id, True, actor_id=operator)
    return title.title_id, f"New book created. Your idea is saved as {idea_asset_id}; begin with the audience brief."


def run_project_action(root: Path, project_id: str, action: str, form: dict[str, str]) -> tuple[str | None, str]:
    with session_scope(root) as session:
        if session.get(ProjectRow, project_id) is None:
            raise ValueError("Project not found.")
    if action == "controls":
        _required(form, "operator", 100)
        return None, _controls(root, project_id, form)
    if action == "new-title":
        operator = _required(form, "operator", 100)
        title = create_title(root, project_id, _required(form, "title_name", 200), actor_id=operator)
        return title.title_id, f"Title {title.title_id} created."
    raise ValueError("Unknown project action.")


def _require_generation_controls(root: Path, title_id: str, form: dict[str, str]) -> None:
    if form.get("confirm_cost") != "yes":
        raise ValueError("Confirm that this action calls the selected provider and incurs usage cost.")
    _required(form, "operator", 100)
    project_id = _project_id(root, title_id)
    with session_scope(root) as session:
        project = session.get(ProjectRow, project_id)
        from kdp_pipeline.storage.db import ProjectBudgetRow, ProjectProviderSelectionRow
        selection = session.get(ProjectProviderSelectionRow, project_id)
        budget = session.get(ProjectBudgetRow, project_id)
        if project is None or selection is None or budget is None or not budget.hard_stop:
            raise ValueError("Select a provider and set a hard-stop project budget before generation.")
        if budget.monthly_limit_usd is None or budget.max_run_estimated_cost_usd is None:
            raise ValueError("Set monthly and per-run limits before generation.")
        provider_id = selection.provider_id
    _priced_profile(root, provider_id)


def _audit_generation_request(root: Path, title_id: str, action: str, form: dict[str, str]) -> None:
    with session_scope(root) as session:
        AuditEventWriter.append(session, actor_id=form["operator"].strip(),
            action="workspace.generation.requested", entity_type="title", entity_id=title_id,
            correlation_id=title_id, result="requested",
            metadata={"action": action, "source_asset_id": form.get("asset_id"),
                      "chapter_number": form.get("chapter_number")})
        session.commit()


def _source(root: Path, title_id: str, form: dict[str, str], key: str = "asset_id") -> str:
    asset_id = _required(form, key, 80)
    with session_scope(root) as session:
        asset = session.get(AssetRow, asset_id)
        if asset is None or asset.title_id != title_id:
            raise ValueError("Selected asset does not belong to this title.")
    return asset_id


def run_authoring_action(root: Path, title_id: str, action: str, form: dict[str, str]) -> str:
    if action not in AUTHORING_ACTIONS:
        raise ValueError("Unknown authoring action.")
    _project_id(root, title_id)
    if action == "save-idea":
        asset_id = _record_idea(root, title_id, _required(form, "idea", 4000),
                                _required(form, "audience", 1000),
                                _required(form, "operator", 100))
        enable_concept_gate(root, title_id, True, actor_id=form["operator"].strip())
        return f"Starting idea {asset_id} saved; concept review enabled."
    if action in GENERATION_ACTIONS:
        _require_generation_controls(root, title_id, form)
        _audit_generation_request(root, title_id, action, form)
    if action == "concept-enable":
        enable_concept_gate(root, title_id, True, actor_id=_required(form, "operator", 100))
        return "Concept review enabled."
    if action in {"advance-validated", "advance-planned", "advance-drafting"}:
        actor = _required(form, "operator", 100)
        fn = {"advance-validated": advance_to_validated,
              "advance-planned": advance_to_planned,
              "advance-drafting": advance_to_drafting}[action]
        row = fn(root, title_id, actor_id=actor)
        return f"Title advanced to {row.status}."
    if action == "concept-validate":
        report, asset = validate_concept_asset(root, _source(root, title_id, form))
        return f"Validation {asset.asset_id}: {report['status']}; human concept approval remains required."
    if action == "chapter-summary":
        asset = record_chapter_summary(root, title_id, _number(form, "chapter_number"),
            _source(root, title_id, form), _required(form, "summary", 3000),
            _required(form, "operator", 100))
        return f"Chapter summary {asset.asset_id} recorded."
    if action.startswith("concept-") or action == "audience-brief":
        artifact = {"audience-brief": "audience-brief", "concept-seeds": "generate-seeds",
                    "concept-enrich": "enrich", "concept-score": "score",
                    "concept-drafting-brief": "drafting-brief"}[action]
        result = asyncio.run(ConceptService.generate(root, title_id=title_id, artifact=artifact,
            audience=_required(form, "audience", 1000) if action == "audience-brief" else "",
            concept_asset_id=_source(root, title_id, form) if action != "audience-brief" else None,
            selection=_required(form, "selection", 2000) if action == "concept-enrich" else ""))
    elif action in {"positioning", "book-brief", "outline", "chapter-card"}:
        kind = {"positioning": PlanningArtifactKind.POSITIONING,
                "book-brief": PlanningArtifactKind.BOOK_BRIEF,
                "outline": PlanningArtifactKind.OUTLINE,
                "chapter-card": PlanningArtifactKind.CHAPTER_CARD}[action]
        chapter_number = _number(form, "chapter_number") if action == "chapter-card" else None
        manifest = ContextManifest(title_id=title_id, task_type=f"planning.{kind.value}", inputs=[])
        result = asyncio.run(PlanningService.generate(root, title_id=title_id,
            artifact_kind=kind, context_manifest=manifest, chapter_number=chapter_number))
    elif action == "draft-chapter":
        result = asyncio.run(ChapterService.draft(root, title_id=title_id,
                                                  chapter_number=_number(form, "chapter_number")))
    elif action == "revise-chapter":
        result = asyncio.run(ChapterService.revise(root, title_id=title_id,
            chapter_number=_number(form, "chapter_number"),
            source_asset_id=_source(root, title_id, form)))
    elif action == "continuity":
        result = asyncio.run(ContinuityService.analyze(root, title_id=title_id,
            chapter_number=_number(form, "chapter_number"),
            source_asset_id=_source(root, title_id, form)))
        return f"Continuity job {result.generation.job.job_id}; analysis asset {result.generation.asset.asset_id}."
    elif action == "developmental":
        result = asyncio.run(EditorialService.developmental(root, title_id=title_id,
            chapter_number=_number(form, "chapter_number"),
            source_asset_id=_source(root, title_id, form)))
        return f"Developmental job {result.generation.job.job_id}; analysis asset {result.generation.asset.asset_id}."
    else:
        pass_type = _required(form, "pass_type", 30)
        if pass_type not in STRUCTURED_PASSES:
            raise ValueError("Select a supported editorial pass.")
        result = asyncio.run(StructuredEditorialService.analyze(root, title_id=title_id,
            chapter_number=_number(form, "chapter_number"),
            source_asset_id=_source(root, title_id, form), pass_type=pass_type))
        return f"{pass_type} job {result.generation.job.job_id}; analysis asset {result.generation.asset.asset_id}."
    return f"Job {result.job.job_id} created experimental asset {result.asset.asset_id}. Review before acceptance."


EDITABLE_TYPES = {"concept.brief", "planning.positioning", "planning.book-brief",
                  "planning.outline", "planning.chapter-card", "chapter.draft", "chapter.revision"}


def read_edit_source(root: Path, title_id: str, asset_id: str) -> tuple[str, str, int]:
    """Return a verified experimental content artefact for the browser editor."""
    with session_scope(root) as session:
        asset = session.get(AssetRow, asset_id)
        if (asset is None or asset.title_id != title_id or
                asset.asset_type not in EDITABLE_TYPES or
                asset.approval_status != "experimental"):
            raise ValueError("Choose an experimental concept, planning, or chapter artefact from this title.")
        path = Path(asset.path)
        if (not path.resolve().is_relative_to(root.resolve()) or not path.is_file()
                or sha256_file(path) != asset.sha256 or path.stat().st_size > 100_000):
            raise ValueError("Source chapter is missing, altered, or too large for browser editing.")
        content = path.read_text(encoding="utf-8")
        return content, asset.sha256, path.stat().st_size


def create_manual_revision(root: Path, title_id: str, asset_id: str,
                           form: dict[str, str]) -> str:
    reviewer = _required(form, "operator", 100)
    reason = _required(form, "reason", 2000)
    content = _required(form, "content", 100_000)
    source_text, source_hash, _ = read_edit_source(root, title_id, asset_id)
    if form.get("source_sha256") != source_hash:
        raise ValueError("The source changed. Reload and review the current draft before editing.")
    if content == source_text:
        raise ValueError("No text changed; nothing was saved.")
    with session_scope(root) as session:
        title = session.get(TitleRow, title_id)
        source = session.get(AssetRow, asset_id)
        source_prov = session.scalar(select(ProvenanceRow).where(ProvenanceRow.asset_id == asset_id))
        if title is None or source is None or source_prov is None:
            raise ValueError("Manual revision requires a source with provenance.")
        is_chapter = source.asset_type.startswith("chapter.")
        if is_chapter and title.status != "DRAFTING":
            raise ValueError("Chapter revision requires a drafting title.")
        if not is_chapter and title.status not in {"IDEA", "VALIDATED"}:
            raise ValueError("Concept and planning revision requires an idea or validated title.")
        if source.asset_type == "concept.brief":
            try:
                if not isinstance(json.loads(content), dict):
                    raise ValueError("Concept brief must remain a JSON object.")
            except json.JSONDecodeError as exc:
                raise ValueError("Concept brief must contain valid JSON.") from exc
        project_id = title.project_id
        chapter_number = None
        if is_chapter or source.asset_type == "planning.chapter-card":
            pattern = (r"chapter\.(?:draft|revision)\.(\d+)[-.]" if is_chapter else
                       r"(?:chapter_card|chapter-card)[-.](\d+)[-.]")
            chapter_match = re.search(pattern, Path(source.path).name)
            if chapter_match is None:
                raise ValueError("Source chapter or card number cannot be determined.")
            chapter_number = int(chapter_match.group(1))
    asset_id_new = new_id("AST")
    if is_chapter:
        name = f"chapter.revision.{chapter_number}-MANUAL-{asset_id_new}.md"
    elif source.asset_type == "planning.chapter-card":
        name = f"chapter-card.{chapter_number}-MANUAL-{asset_id_new}.md"
    else:
        suffix = ".json" if source.asset_type == "concept.brief" else ".md"
        name = f"{source.asset_type}.MANUAL-{asset_id_new}{suffix}"
    path = Path(source.path).parent / name
    write_text(path, content)
    try:
        with session_scope(root) as session:
            source = session.get(AssetRow, asset_id)
            if source is None or sha256_file(Path(source.path)) != source_hash:
                raise ValueError("Source changed while the revision was being saved.")
            digest = sha256_file(path)
            asset = AssetRow(asset_id=asset_id_new, title_id=title_id,
                asset_type="chapter.revision" if is_chapter else source.asset_type,
                path=str(path.resolve()), version="1.0",
                sha256=digest, creator_type="human", creator=reviewer, source_ref=asset_id,
                ai_classification="AI_ASSISTED", approval_status="experimental", created_at=utcnow())
            provenance = ProvenanceRow(provenance_id=new_id("PROV"), asset_id=asset_id_new,
                job_id=None, provider="human", model="manual-edit",
                prompt_template_id="workspace/manual-content-revision", prompt_template_version="1.0",
                rendered_prompt_sha256=source_hash,
                input_references_json=json.dumps([asset_id]), input_hashes_json=json.dumps([source_hash]),
                context_manifest_hash=source_hash, output_hash=digest, generation_timestamp=utcnow(),
                human_contribution_note=reason, ai_classification="AI_ASSISTED", reviewer=reviewer)
            session.add_all([asset, provenance])
            AuditEventWriter.append(session, actor_id=reviewer, action="content.manual_revision.created",
                entity_type="asset", entity_id=asset_id_new, correlation_id=title_id,
                result="success", before_hash=source_hash, after_hash=digest,
                metadata={"source_asset_id": asset_id, "provenance_id": provenance.provenance_id,
                          "reason": reason})
            session.commit()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return f"Manual revision {asset_id_new} saved as experimental. Review it before acceptance."
