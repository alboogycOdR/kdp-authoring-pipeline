from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, inspect as sqlalchemy_inspect, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from kdp_pipeline.models.planning import PlanningArtifactKind, spec_for
from kdp_pipeline.continuity.service import ContinuityOutputInvalid, _validate_output
from kdp_pipeline.storage.db import (
    AssetRow, ApprovalRow, AuditEventRow, CanonProposalRow, ChapterQueueRow, ConceptGateRow, EditorialFindingRow,
    JobRow, ManuscriptBuildRow, ProjectRow, ProvenanceRow, RevisionRecommendationRow, TitleRow,
    ProviderProfileRow, ProjectProviderSelectionRow, ProjectBudgetRow, RightsLogRow, VerificationItemRow,
    UsageEventRow, BudgetReservationRow, ModelPricingRow,
)
from kdp_pipeline.storage.files import sha256_file


REQUIRED_TABLES = {
    "projects", "titles", "assets", "jobs", "provenance", "approvals",
    "editorial_findings", "canon_proposals", "audit_events",
    "provider_profiles", "project_provider_selections", "model_pricing",
    "project_budgets", "budget_reservations", "usage_events", "verification_items", "rights_log", "manuscript_builds",
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
    "editorial/voice-v1.0.md",
    "editorial/line-v1.0.md",
    "editorial/copy-v1.0.md",
    "editorial/reader-experience-v1.0.md",
    "editorial/consistency-v1.0.md",
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
        existing_tables = set(sqlalchemy_inspect(session.bind).get_table_names())
        title = session.get(TitleRow, title_id)
        if title is None:
            raise ValueError(f"Unknown title: {title_id}")
        project = session.get(ProjectRow, title.project_id)
        assets = list(session.scalars(select(AssetRow).where(AssetRow.title_id == title_id).order_by(AssetRow.created_at)))
        jobs = list(session.scalars(select(JobRow).where(JobRow.title_id == title_id).order_by(JobRow.created_at)))
        approvals = list(session.scalars(select(ApprovalRow).where(ApprovalRow.title_id == title_id).order_by(ApprovalRow.created_at)))
        findings = list(session.scalars(select(EditorialFindingRow).where(EditorialFindingRow.title_id == title_id).order_by(EditorialFindingRow.created_at)))
        proposals = list(session.scalars(select(CanonProposalRow).where(CanonProposalRow.title_id == title_id).order_by(CanonProposalRow.created_at)))
        revision_recommendations = (list(session.scalars(select(RevisionRecommendationRow).where(
            RevisionRecommendationRow.title_id == title_id).order_by(RevisionRecommendationRow.created_at)))
            if "revision_recommendations" in existing_tables else [])
        verification_items = (list(session.scalars(select(VerificationItemRow).where(
            VerificationItemRow.title_id == title_id).order_by(VerificationItemRow.created_at)))
            if "verification_items" in existing_tables else [])
        rights_records = (list(session.scalars(select(RightsLogRow).where(
            RightsLogRow.title_id == title_id).order_by(RightsLogRow.created_at)))
            if "rights_log" in existing_tables else [])
        manuscript_builds = (list(session.scalars(select(ManuscriptBuildRow).where(
            ManuscriptBuildRow.title_id == title_id).order_by(ManuscriptBuildRow.created_at)))
            if "manuscript_builds" in existing_tables else [])
        continuity_audits = list(session.scalars(select(AuditEventRow).where(
            AuditEventRow.action.in_(["continuity.output.validated", "continuity.output.rejected"]))))
        continuity_audits_by_job = {row.entity_id: row for row in continuity_audits}
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
        request_events = list(session.scalars(select(AuditEventRow).where(
            AuditEventRow.action == "generation.job.created",
            AuditEventRow.entity_id.in_([row.job_id for row in jobs]),
        )))
        request_diagnostics_by_job = {
            row.entity_id: json.loads(row.metadata_json or "{}").get("effective_request")
            for row in request_events
        }
        budget = session.get(ProjectBudgetRow, title.project_id)
        reservations = list(session.scalars(select(BudgetReservationRow).where(BudgetReservationRow.project_id == title.project_id)))
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        monthly_usage = [row for row in usage_rows if row.created_at.strftime("%Y-%m") == month]
        spent = sum(row.estimated_cost or 0.0 for row in monthly_usage if row.currency == "USD")
        reserved = sum(row.estimated_cost_usd or 0.0 for row in reservations if row.month == month and row.status in {"reserved", "uncertain", "unpriced", "provider_outcome_unknown"})
        reservations_by_job = {row.job_id: row for row in reservations}
        unknown_outcomes = [row for row in reservations
                            if row.month == month and row.status == "provider_outcome_unknown"
                            and any(job.job_id == row.job_id for job in jobs)]
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
        if unknown_outcomes:
            budget_warning = (
                "Provider outcome unknown for one or more failed runs; provider may have processed or billed them"
            )
        if budget and budget.monthly_limit_usd is not None:
            projected = spent + reserved
            if projected >= budget.monthly_limit_usd * budget.warning_percent / 100:
                budget_warning = (budget_warning + "; " if budget_warning else "") + f"Monthly budget warning threshold ({budget.warning_percent}%) reached"
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

        concept_assets = [asset for asset in assets if asset.asset_type.startswith("concept.")]
        accepted_concept_brief = next((asset for asset in concept_assets
            if asset.asset_type == "concept.brief" and asset.approval_status == "accepted"
            and any(a.asset_id == asset.asset_id and a.decision == "accepted" for a in approvals)), None)
        concept_warnings = []
        concept_flags = []
        concept_scorecards = []
        for asset in concept_assets:
            if asset.asset_type in {"concept.validation", "concept.scorecard"} and Path(asset.path).is_file():
                try:
                    parsed = json.loads(Path(asset.path).read_text(encoding="utf-8"))
                    if asset.asset_type == "concept.validation":
                        concept_warnings.extend(parsed.get("warnings", []))
                        concept_flags.extend(parsed.get("research_flags", []))
                        concept_flags.extend(parsed.get("content_transparency_flags", []))
                    else:
                        concept_scorecards.append({"asset_id": asset.asset_id, "approval_status": asset.approval_status,
                                                   "scorecard": parsed})
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    concept_warnings.append(f"Concept {asset.asset_type} asset {asset.asset_id} is unreadable or not structured JSON.")
        concept_gate = session.get(ConceptGateRow, title_id) if "concept_gates" in existing_tables else None
        concept_enabled = bool(concept_gate and concept_gate.enabled)
        concepts = {"enabled": concept_enabled,
                    "positioning_unlocked": (not concept_enabled or accepted_concept_brief is not None),
                    "accepted_concept_brief_asset_id": accepted_concept_brief.asset_id if accepted_concept_brief else None,
                    "artefacts": [{"asset_id": a.asset_id, "asset_type": a.asset_type,
                                   "approval_status": a.approval_status, "path": a.path, "source_ref": a.source_ref}
                                  for a in concept_assets],
                    "validation_warnings": sorted(set(concept_warnings)),
                    "scorecards": concept_scorecards,
                    "outstanding_research_content_flags": sorted(set(map(str, concept_flags)))}

        accepted_chapters = [asset for asset in assets if asset.asset_type == "chapter.accepted" and asset.approval_status == "accepted"]
        experimental_chapters = [asset for asset in assets if asset.asset_type in {"chapter.draft", "chapter.revision"} and asset.approval_status == "experimental"]
        chapter_numbers = set()
        for asset in assets:
            name = Path(asset.path).name
            match = (re.search(r"chapter-(\d{3})\.md$", name) if asset.asset_type in {"chapter.accepted", "planning.chapter-card"}
                     else re.search(r"chapter\.(?:draft|revision)\.(\d+)[-.]", name) if asset.asset_type in {"chapter.draft", "chapter.revision"} else None)
            if match:
                chapter_numbers.add(int(match.group(1)))
        queue_rows = (list(session.scalars(select(ChapterQueueRow).where(ChapterQueueRow.title_id == title_id)))
                      if "chapter_queue" in existing_tables else [])
        queue_by_number = {row.chapter_number: row for row in queue_rows}
        chapter_work_items = []
        for number in sorted(chapter_numbers | set(queue_by_number)):
            has_card = any(a.asset_type == "planning.chapter-card" and a.approval_status == "accepted"
                           and re.search(rf"chapter-{number:03d}\.md$", Path(a.path).name) for a in assets)
            accepted_for_number = any(re.search(rf"chapter-{number:03d}\.md$", Path(a.path).name) for a in accepted_chapters)
            drafts_for_number = [a.asset_id for a in experimental_chapters
                                 if re.search(rf"chapter\.(?:draft|revision)\.{number}[-.]", Path(a.path).name)]
            queued = queue_by_number.get(number)
            failed_job = any(j.status == "failed" and j.job_type.endswith(f".{number}")
                             and j.job_type.startswith(("generate:chapter.draft.", "generate:chapter.revise.")) for j in jobs)
            accepted_numbered = [(int(m.group(1)), a.asset_id) for a in accepted_chapters
                                 if (m := re.search(r"chapter-(\d{3})\.md$", Path(a.path).name))]
            summary_sources = {a.source_ref for a in assets if a.asset_type == "chapter.summary"
                               and a.approval_status == "accepted" and a.asset_id in {p.asset_id for p in provenance}
                               and any(ap.asset_id == a.asset_id and ap.decision == "accepted" for ap in approvals)
                               and Path(a.path).is_file() and sha256_file(Path(a.path)) == a.sha256}
            missing_summaries = sorted(n for n, aid in accepted_numbered if n < number and aid not in summary_sources)
            state = ("complete" if accepted_for_number else "missing_card" if not has_card
                     else "paused" if queued and queued.status == "paused" else "failed" if failed_job
                     else "awaiting_prior_summary" if missing_summaries
                     else "draft_ready" if drafts_for_number else queued.status if queued else "needs_queue")
            chapter_work_items.append({"chapter_number": number, "status": state,
                "card_present": has_card, "draft_asset_ids": drafts_for_number,
                "accepted": accepted_for_number, "queue_item_id": queued.queue_item_id if queued else None,
                "missing_prior_summaries": missing_summaries,
                "open_findings": [f.finding_id for f in findings if f.status == "open" and f.location == f"chapter-{number:03d}"]})
        chapter_workflow = {"chapter_count": len(chapter_work_items), "accepted_chapter_count": len(accepted_chapters),
            "chapters": chapter_work_items,
            "missing_cards": [c["chapter_number"] for c in chapter_work_items if c["status"] == "missing_card"],
            "failed_chapters": [c["chapter_number"] for c in chapter_work_items if c["status"] == "failed"],
            "missing_prior_summary_chapters": [c["chapter_number"] for c in chapter_work_items if c.get("missing_prior_summaries")],
            "verification_conditions": [{"approval_id": a.approval_id, "asset_id": a.asset_id,
                "conditions": json.loads(a.conditions_json or "[]")} for a in approvals if json.loads(a.conditions_json or "[]")]}
        inconsistencies = [check for asset in assets if not (check := _file_check(asset))["hash_matches"]]
        inconsistencies += [{"asset_id": asset.asset_id, "issue": "missing provenance"} for asset in assets if asset.creator_type == "ai" and not any(item.asset_id == asset.asset_id for item in provenance)]
        inconsistencies += [{"asset_id": asset.asset_id, "issue": "accepted asset missing approval"} for asset in assets if asset.approval_status == "accepted" and not any(item.asset_id == asset.asset_id and item.decision == "accepted" for item in approvals)]
        assets_by_id = {asset.asset_id: asset for asset in assets}
        for build in manuscript_builds:
            output = assets_by_id.get(build.asset_id)
            output_ok = output is not None and Path(output.path).is_file() and sha256_file(Path(output.path)) == build.output_sha256 == output.sha256
            manifest_path = Path(build.manifest_path)
            manifest_ok = manifest_path.is_file() and sha256_file(manifest_path) == build.manifest_sha256
            if not output_ok or not manifest_ok:
                inconsistencies.append({"build_id": build.build_id, "issue": "build output or manifest is missing or has a hash mismatch"})
        continuity_runs = []
        invalid_continuity_asset_ids = set()
        continuity_warnings = []
        for job in jobs:
            if not job.job_type.startswith("generate:chapter.continuity."):
                continue
            result_ids = json.loads(job.result_asset_ids_json or "[]")
            analysis = next((asset for asset in assets if asset.asset_id in result_ids), None)
            prov = next((item for item in provenance if analysis and item.asset_id == analysis.asset_id), None)
            run_audit = continuity_audits_by_job.get(job.job_id)
            valid = False
            try:
                if analysis and Path(analysis.path).is_file():
                    _validate_output(Path(analysis.path).read_text(encoding="utf-8"))
                    valid = True
            except (ContinuityOutputInvalid, UnicodeDecodeError, OSError):
                valid = False
            refs = json.loads(prov.input_references_json) if prov else []
            ref_assets = [next((asset for asset in assets if asset.asset_id == ref), None) for ref in refs]
            context_kinds = {asset.asset_type for asset in ref_assets if asset is not None}
            required_kinds = {"chapter.draft", "planning.positioning", "planning.book-brief", "planning.outline", "planning.chapter-card"}
            required_context = required_kinds.issubset(context_kinds) and run_audit is not None and run_audit.action == "continuity.output.validated"
            invalid = not valid or not required_context or (run_audit is not None and run_audit.action == "continuity.output.rejected")
            if invalid and analysis:
                invalid_continuity_asset_ids.add(analysis.asset_id)
            continuity_runs.append({"job_id": job.job_id, "analysis_asset_id": analysis.asset_id if analysis else None,
                "required_context_present": required_context, "output_valid": valid,
                "status": "valid" if valid and required_context else "invalid_or_unverified",
                "findings_from_invalid_analysis": ([row.finding_id for row in findings if row.asset_id == (analysis.asset_id if analysis else None) and row.pass_type == "continuity"] if invalid else []),
                "proposals_from_invalid_analysis": ([row.proposal_id for row in proposals if row.finding_id and any(f.finding_id == row.finding_id and f.asset_id == (analysis.asset_id if analysis else None) for f in findings)] if invalid else [])})
            if invalid or not required_context:
                continuity_warnings.append(f"Continuity attempt {job.job_id} is unusable or unverified; its findings/proposals require human review.")
        project_data = {"project_id": project.project_id, "name": project.name, "status": project.status} if project else None
        return {
            "project": project_data,
            "title": {"title_id": title.title_id, "working_title": title.working_title, "status": title.status},
            "planning": planning,
            "concept": concepts,
            "chapter_lifecycle": {"drafting_state": title.status == "DRAFTING", "experimental_chapter_assets": [asset.asset_id for asset in experimental_chapters],
                                  "accepted_chapter_assets": [asset.asset_id for asset in accepted_chapters], "accepted_chapter_count": len(accepted_chapters)},
            "chapter_workflow": chapter_workflow,
            "assets": [{"asset_id": asset.asset_id, "asset_type": asset.asset_type, "path": asset.path, "sha256": asset.sha256, "approval_status": asset.approval_status, "source_ref": asset.source_ref} for asset in assets],
            "builds": {"records": [{"build_id": build.build_id, "asset_id": build.asset_id,
                "status": build.status, "output_format": build.output_format,
                "output_sha256": build.output_sha256, "manifest_path": build.manifest_path,
                "manifest_sha256": build.manifest_sha256,
                "included_assets": json.loads(build.included_assets_json or "[]"),
                "blockers": json.loads(build.blockers_json or "[]"),
                "created_by": build.created_by,
                "output_exists": bool(assets_by_id.get(build.asset_id) and Path(assets_by_id[build.asset_id].path).is_file()),
                "manifest_exists": Path(build.manifest_path).is_file()}
                for build in manuscript_builds]},
            "jobs": [{"job_id": job.job_id, "job_type": job.job_type, "status": job.status,
                      "error": job.error, "idempotency_key": job.idempotency_key,
                      "request_diagnostics": request_diagnostics_by_job.get(job.job_id),
                      "failure_category": ("provider_transport_timeout"
                                           if job.error and "ReadTimeout" in job.error
                                           else "provider_transport_failure"
                                           if job.error and "ProviderTransportError" in job.error else None),
                      "usage_event_id": next((event.usage_event_id for event in usage_rows if event.job_id == job.job_id), None),
                      "usage_recorded": any(event.job_id == job.job_id for event in usage_rows),
                      "reservation_status": (reservations_by_job[job.job_id].status
                                             if job.job_id in reservations_by_job else None),
                      "provider_outcome_unknown": (reservations_by_job.get(job.job_id).status == "provider_outcome_unknown"
                                                   if reservations_by_job.get(job.job_id) else False),
                      "provider_billing_warning": (
                          "Provider may have processed or billed the request; local outcome is unknown"
                          if reservations_by_job.get(job.job_id)
                          and reservations_by_job[job.job_id].status == "provider_outcome_unknown" else None
                      ),
                      "usage_diagnostics": next((json.loads(event.cost_details_json or "{}").get("response_diagnostics")
                                                  for event in usage_rows if event.job_id == job.job_id
                                                  and json.loads(event.cost_details_json or "{}").get("response_diagnostics")), None)}
                     for job in jobs],
            "provenance": [{"provenance_id": row.provenance_id, "asset_id": row.asset_id, "job_id": row.job_id, "provider": row.provider, "model": row.model, "output_hash": row.output_hash} for row in provenance],
            "provider": ({"provider_id": provider.provider_id, "provider_type": provider.provider_type,
                          "display_name": provider.display_name, "enabled": provider.enabled,
                          "model": provider.model, "api_key_env": provider.api_key_env,
                          "api_key_configured": bool(os.getenv(provider.api_key_env)) if provider.api_key_env else False}
                         if provider else {"provider_id": None, "selected": False}),
            "usage": {"recent_events": [{"usage_event_id": row.usage_event_id, "job_id": row.job_id, "provider": row.provider,
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
                        "provider_outcome_unknown_runs": sum(row.status == "provider_outcome_unknown"
                                                              and row.month == month for row in reservations),
                        "warning": budget_warning}
                       if budget else {
                           "configured": False,
                           "provider_outcome_unknown_runs": sum(
                               row.status == "provider_outcome_unknown" and row.month == month
                               for row in reservations
                           ),
                           "warning": budget_warning,
                       }),
            "approvals": [{"approval_id": row.approval_id, "asset_id": row.asset_id, "scope": row.scope, "decision": row.decision, "approver": row.approver} for row in approvals],
            "findings": [{"finding_id": row.finding_id, "asset_id": row.asset_id, "pass_type": row.pass_type, "status": row.status, "snapshot_path": row.snapshot_path} for row in findings],
            "proposals": [{"proposal_id": row.proposal_id, "finding_id": row.finding_id, "status": row.status, "snapshot_path": row.snapshot_path} for row in proposals],
            "editorial": {"analyses": [{"asset_id": a.asset_id, "asset_type": a.asset_type,
                           "approval_status": a.approval_status, "source_ref": a.source_ref, "path": a.path}
                          for a in assets if a.asset_type.startswith("analysis.editorial.")],
                          "findings_by_pass": {pass_type: [f.finding_id for f in findings if f.pass_type == pass_type]
                                               for pass_type in sorted({f.pass_type for f in findings})},
                          "rejected_outputs": [{"job_id": e.entity_id, "metadata": json.loads(e.metadata_json or "{}")}
                                               for e in audit if e.action == "editorial.output.rejected"],
                          "revision_recommendations": [{"recommendation_id": r.recommendation_id,
                              "chapter_number": r.chapter_number, "source_asset_id": r.source_asset_id,
                              "finding_ids": json.loads(r.finding_ids_json or "[]"), "status": r.status,
                              "owner": r.owner, "recommendation": r.recommendation}
                              for r in revision_recommendations]},
            "verification": {
                "items": [{"verification_id": row.verification_id, "asset_id": row.asset_id,
                    "kind": row.kind, "locator": row.locator, "exact_text": row.exact_text,
                    "status": row.status, "proposed_reference": row.proposed_reference,
                    "source_policy": row.source_policy, "evidence_reference": row.evidence_reference,
                    "rationale": row.rationale, "reviewer": row.reviewer}
                    for row in verification_items],
                "rights_records": [{"rights_record_id": row.rights_record_id, "asset_id": row.asset_id,
                    "material_type": row.material_type, "description": row.description,
                    "source": row.source, "provenance_reference": row.provenance_reference,
                    "legal_basis": row.legal_basis,
                    "evidence_reference": row.evidence_reference,
                    "territories": json.loads(row.territories_json or "[]"), "term": row.term,
                    "restrictions": row.restrictions, "status": row.status,
                    "rationale": row.rationale, "reviewer": row.reviewer}
                    for row in rights_records],
                "release_blockers": ([{"type": "verification", "id": row.verification_id,
                    "kind": row.kind, "asset_id": row.asset_id, "locator": row.locator,
                    "status": row.status} for row in verification_items
                    if row.status not in {"verified", "not_applicable"}] +
                    [{"type": "rights", "id": row.rights_record_id, "asset_id": row.asset_id,
                      "material_type": row.material_type, "status": row.status}
                     for row in rights_records if row.status not in {"cleared", "not_applicable"}] +
                    [{"type": "approval_condition", "id": approval.approval_id,
                      "asset_id": approval.asset_id, "condition": condition}
                     for approval in approvals for condition in json.loads(approval.conditions_json or "[]")]),
                "legacy_approval_conditions": [{"approval_id": approval.approval_id,
                    "asset_id": approval.asset_id, "conditions": json.loads(approval.conditions_json or "[]")}
                    for approval in approvals if json.loads(approval.conditions_json or "[]")],
            },
            "continuity": {"runs": continuity_runs, "warnings": continuity_warnings,
                           "findings_from_invalid_analysis": [row.finding_id for row in findings if row.asset_id in invalid_continuity_asset_ids and row.pass_type == "continuity"],
                           "proposals_from_invalid_analysis": [row.proposal_id for row in proposals if row.finding_id and any(f.finding_id == row.finding_id and f.asset_id in invalid_continuity_asset_ids for f in findings)]},
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

