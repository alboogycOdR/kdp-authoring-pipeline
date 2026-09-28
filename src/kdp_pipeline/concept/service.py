from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

from kdp_pipeline.context import ContextManifest
from kdp_pipeline.core.ids import new_id
from kdp_pipeline.generation import GenerationRunResult, GenerationService
from kdp_pipeline.prompts import PromptRegistry
from kdp_pipeline.providers import ModelProvider
from kdp_pipeline.storage.audit import AuditEventWriter
from kdp_pipeline.storage.approval_conditions import normalize_approval_conditions
from kdp_pipeline.storage.db import ApprovalRow, AssetRow, ConceptGateRow, ProvenanceRow, ProjectRow, TitleRow, utcnow
from kdp_pipeline.storage.files import sha256_file
from kdp_pipeline.storage.service import session_scope


CONCEPT_ARTIFACTS = {
    "audience-brief": "concept.audience-brief",
    "generate-seeds": "concept.seed-set",
    "enrich": "concept.brief",
    "score": "concept.scorecard",
    "drafting-brief": "concept.drafting-brief",
}
_WEIGHTS = {"reader_fit": .20, "emotional_charge": .20, "engine_strength": .20,
            "freshness": .15, "market_legibility": .10, "execution_feasibility": .10,
            "series_potential": .05}


@dataclass(frozen=True)
class ConceptAcceptanceResult:
    source_asset: AssetRow
    accepted_asset: AssetRow
    approval: ApprovalRow
    destination_path: Path


class ConceptService:
    @staticmethod
    async def generate(root: Path, *, title_id: str, artifact: str, provider: ModelProvider | None = None,
                       audience: str = "", concept_asset_id: str | None = None,
                       variables: dict[str, Any] | None = None, selection: str = "") -> GenerationRunResult:
        if artifact not in CONCEPT_ARTIFACTS:
            raise ValueError(f"Unknown concept artefact: {artifact}")
        if artifact == "validate":
            raise ValueError("Concept validation uses deterministic checks; use validate_concept_asset")
        context: dict[str, Any] = {"title_id": title_id, "audience": audience, "source_concept": "No source concept supplied."}
        refs: list[dict[str, str]] = []
        if concept_asset_id:
            with session_scope(root) as session:
                source = session.get(AssetRow, concept_asset_id)
                if source is None or source.title_id != title_id or not source.asset_type.startswith("concept."):
                    raise ValueError("Concept source must be a concept asset belonging to this title")
                expected_source_type = {"generate-seeds": "concept.audience-brief", "enrich": "concept.seed-set",
                                        "score": "concept.brief", "drafting-brief": "concept.brief"}.get(artifact)
                if expected_source_type and source.asset_type != expected_source_type:
                    raise ValueError(f"{artifact} requires a {expected_source_type} source asset")
                if artifact == "drafting-brief" and source.approval_status != "accepted":
                    raise ValueError("Drafting brief requires a human-approved concept brief")
                path = Path(source.path)
                if not path.is_file() or sha256_file(path) != source.sha256:
                    raise ValueError("Concept source file/hash integrity check failed")
                context["source_concept"] = path.read_text(encoding="utf-8")
                if artifact == "enrich":
                    if not selection.strip():
                        raise ValueError("Enrichment requires an explicit seed selection")
                    context["source_concept"] += "\n\nOperator-selected seed: " + selection.strip()
                refs.append({"input_ref": source.asset_id, "sha256": source.sha256,
                             "context_tier": "A", "role": "source_concept"})
        context.update(variables or {})
        task_type = f"concept.{artifact}"
        prompt = PromptRegistry(root / "prompts").render(f"concept/{artifact}", context)
        manifest = ContextManifest(title_id=title_id, task_type=task_type, inputs=refs)
        return await GenerationService.generate(
            root, title_id=title_id, task_type=task_type, rendered_prompt=prompt,
            context_manifest=manifest, provider=provider,
            system_instructions="Return the requested structured concept artefact. Keep it experimental; do not claim market validation or make approval decisions.",
            asset_type=CONCEPT_ARTIFACTS[artifact], metadata={"concept_artifact": artifact},
        )


def _parse_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Concept artefact must contain readable JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("Concept artefact root must be an object")
    return value


def validate_concept(data: dict[str, Any]) -> dict[str, Any]:
    """Run transparent completeness and consistency checks; this is not market/legal validation."""
    kind = str(data.get("product_type", "fiction")).lower()
    required = ["audience", "format", "distinctive_lens", "promise", "content_notes"]
    required += ["story_engine", "emotional_need"] if kind in {"fiction", "youth-fiction"} else ["recurring_content_engine", "practical_or_spiritual_need"]
    missing = [key for key in required if key not in data or data.get(key) is None
               or (isinstance(data.get(key), str) and not data[key].strip())]
    audience = data.get("audience") if isinstance(data.get("audience"), dict) else {}
    age = audience.get("age_range")
    warnings: list[str] = []
    if not age and not audience.get("explicit_stage"):
        warnings.append("Specify an explicit reader age range or life/reading stage; do not rely on a broad youth label.")
    if kind not in {"fiction", "youth-fiction", "nonfiction", "devotional", "practical-guide"}:
        warnings.append("product_type is not one of the supported fiction/nonfiction lanes.")
    if data.get("comparables") and not isinstance(data["comparables"], list):
        warnings.append("comparables must be positioning notes in a list, never imitation instructions.")
    text = json.dumps(data, ensure_ascii=False).lower()
    derivative_terms = ["write like ", "in the style of ", "same style as ", "continue the series"]
    derivative_flags = [term for term in derivative_terms if term in text]
    if derivative_flags:
        warnings.append("Potential imitation/derivative-language instruction detected; use comparables only for positioning observations.")
    if any(term in text for term in ("guaranteed sales", "guaranteed success", "best-selling guarantee")):
        warnings.append("Unsupported market or outcome guarantee language detected.")
    return {"status": "review" if missing or warnings else "pass", "missing_fields": missing,
            "warnings": warnings, "research_flags": data.get("research_flags", []),
            "content_transparency_flags": data.get("content_notes", []),
            "human_review_required": True,
            "limitations": "Automated checks do not establish originality, market demand, suitability, factual accuracy, or rights clearance."}


def score_concept(scores: dict[str, Any], rationale: dict[str, str]) -> dict[str, Any]:
    if set(scores) - set(_WEIGHTS) or set(_WEIGHTS) - set(scores):
        raise ValueError("Scorecard must include exactly the seven defined dimensions")
    if any(not isinstance(value, int) or value < 1 or value > 5 for value in scores.values()):
        raise ValueError("Scores must be whole numbers from 1 to 5")
    if any(not str(rationale.get(key, "")).strip() for key in _WEIGHTS):
        raise ValueError("Each score requires a traceable rationale")
    total = round(sum(scores[key] * weight for key, weight in _WEIGHTS.items()), 2)
    action = "advance_to_brief_and_prototype" if total >= 4.3 else "revise_and_retest" if total >= 3.7 else "retain_in_idea_bank" if total >= 3.0 else "archive_or_combine"
    return {"scores": scores, "weights": _WEIGHTS, "weighted_total": total,
            "suggested_action": action, "rationale": rationale,
            "reader_page_one_reason": "Human editorial response required.",
            "human_decision_required": True}


def create_report_asset(root: Path, source_asset_id: str, report_type: str,
                        report: dict[str, Any]) -> AssetRow:
    if report_type not in {"concept.validation", "concept.scorecard"}:
        raise ValueError("Unsupported deterministic concept report type")
    with session_scope(root) as session:
        source = session.get(AssetRow, source_asset_id)
        if source is None or not source.asset_type.startswith("concept.") or source.approval_status not in {"experimental", "accepted"}:
            raise ValueError("Report source must be a concept asset for this title")
        path = Path(source.path)
        if not path.is_file() or sha256_file(path) != source.sha256:
            raise ValueError("Concept source file/hash integrity check failed")
        title = session.get(TitleRow, source.title_id)
        if title is None:
            raise ValueError("Unknown title")
        report_id = new_id("AST")
        output = path.parent / f"{report_type.replace('.', '-')}-{report_id}.json"
        payload = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        output.write_text(payload, encoding="utf-8")
        digest = sha256_file(output)
        asset = AssetRow(asset_id=report_id, title_id=title.title_id, asset_type=report_type,
            path=str(output.resolve()), version="1.0", sha256=digest, creator_type="system",
            creator="deterministic-validation", source_ref=source_asset_id,
            ai_classification="not_ai_generated", approval_status="experimental", created_at=utcnow())
        prov = ProvenanceRow(provenance_id=new_id("PROV"), asset_id=asset.asset_id, job_id=None,
            provider="deterministic", model="concept-rules-v1", prompt_template_id=report_type,
            prompt_template_version="1.0", rendered_prompt_sha256=source.sha256,
            input_references_json=json.dumps([source_asset_id]), input_hashes_json=json.dumps([source.sha256]),
            context_manifest_hash=source.sha256, output_hash=digest, generation_timestamp=utcnow(),
            human_contribution_note="Deterministic report generated from the referenced concept artefact.",
            ai_classification="not_ai_generated", disclosure_decision="not_applicable")
        session.add_all([asset, prov])
        AuditEventWriter.append(session, actor_id="system", action="concept.report.created", entity_type="asset",
            entity_id=asset.asset_id, correlation_id=title.title_id, result="success",
            before_hash=source.sha256, after_hash=digest,
            metadata={"report_type": report_type, "source_asset_id": source_asset_id, "provenance_id": prov.provenance_id})
        session.commit()
        return asset


def validate_concept_asset(root: Path, asset_id: str) -> tuple[dict[str, Any], AssetRow]:
    with session_scope(root) as session:
        asset = session.get(AssetRow, asset_id)
        if asset is None or asset.asset_type != "concept.brief":
            raise ValueError("Validation requires a concept brief asset")
        path = Path(asset.path)
        if not path.is_file() or sha256_file(path) != asset.sha256:
            raise ValueError("Concept file/hash integrity check failed")
        report = validate_concept(_parse_json(path))
    return report, create_report_asset(root, asset_id, "concept.validation", report)


def score_concept_asset(root: Path, asset_id: str) -> tuple[dict[str, Any], AssetRow]:
    with session_scope(root) as session:
        asset = session.get(AssetRow, asset_id)
        if asset is None or asset.asset_type != "concept.brief":
            raise ValueError("Scoring requires a concept brief asset")
        path = Path(asset.path)
        if not path.is_file() or sha256_file(path) != asset.sha256:
            raise ValueError("Concept file/hash integrity check failed")
        data = _parse_json(path)
    scores = data.get("scores")
    rationale = data.get("score_rationale")
    if not isinstance(scores, dict) or not isinstance(rationale, dict):
        raise ValueError("Concept brief must contain scores and score_rationale to compute a scorecard")
    report = score_concept(scores, rationale)
    return report, create_report_asset(root, asset_id, "concept.scorecard", report)


def enable_concept_gate(root: Path, title_id: str, enabled: bool, actor_id: str = "cli-user") -> bool:
    with session_scope(root) as session:
        title = session.get(TitleRow, title_id)
        if title is None:
            raise ValueError(f"Unknown title: {title_id}")
        if enabled and title.status != "IDEA":
            raise ValueError("Concept validation can only be enabled while a title is in IDEA")
        if enabled and session.query(AssetRow).filter_by(title_id=title_id, asset_type="planning.positioning", approval_status="accepted").first():
            raise ValueError("Concept validation must be enabled before positioning is accepted")
        gate = session.get(ConceptGateRow, title_id)
        before = bool(gate.enabled) if gate else False
        if gate is None:
            gate = ConceptGateRow(title_id=title_id, enabled=enabled, updated_at=utcnow())
            session.add(gate)
        else:
            gate.enabled = enabled
            gate.updated_at = utcnow()
        AuditEventWriter.append(session, actor_id=actor_id, action="concept.gate.changed", entity_type="title",
                                entity_id=title_id, correlation_id=title_id, result="success",
                                metadata={"before": before, "after": enabled})
        session.commit()
        return enabled


def accept_concept(root: Path, asset_id: str, reviewer: str,
                   conditions: list[str] | None = None) -> ConceptAcceptanceResult:
    if not reviewer.strip():
        raise ValueError("reviewer is required")
    conditions = normalize_approval_conditions(conditions)
    destination = None
    copied = False
    try:
        with session_scope(root) as session:
            source = session.get(AssetRow, asset_id)
            if source is None or not source.asset_type.startswith("concept.") or source.approval_status != "experimental":
                raise ValueError("Only experimental concept artefacts can be accepted")
            src = Path(source.path)
            provenance = session.scalar(select(ProvenanceRow).where(ProvenanceRow.asset_id == asset_id))
            title = session.get(TitleRow, source.title_id)
            project = session.get(ProjectRow, title.project_id) if title else None
            if not src.is_file() or sha256_file(src) != source.sha256 or provenance is None or title is None or project is None:
                raise ValueError("Concept asset requires a valid file/hash, provenance, and title")
            if source.asset_type != "concept.brief":
                raise ValueError("Only an enriched concept brief can unlock positioning")
            existing = session.scalar(select(AssetRow).where(AssetRow.source_ref == asset_id,
                AssetRow.asset_type == source.asset_type, AssetRow.approval_status == "accepted"))
            if existing:
                approval = session.scalar(select(ApprovalRow).where(ApprovalRow.asset_id == existing.asset_id, ApprovalRow.decision == "accepted"))
                return ConceptAcceptanceResult(source, existing, approval, Path(existing.path))
            destination = root / "projects" / project.project_id / "titles" / title.title_id / "04_plan" / "concepts" / f"concept-{asset_id}.json"
            if destination.exists():
                raise ValueError("Concept acceptance destination already exists")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, destination); copied = True
            digest = sha256_file(destination)
            accepted = AssetRow(asset_id=new_id("AST"), title_id=title.title_id, asset_type=source.asset_type,
                path=str(destination.resolve()), version=source.version, sha256=digest,
                creator_type=source.creator_type, creator=source.creator, source_ref=asset_id,
                ai_classification=source.ai_classification, approval_status="accepted", created_at=utcnow())
            approval = ApprovalRow(approval_id=new_id("APR"), title_id=title.title_id, asset_id=accepted.asset_id,
                scope="concept.brief", candidate_hash=digest, approver=reviewer, decision="accepted",
                conditions_json=json.dumps(conditions), created_at=utcnow())
            accepted_provenance = ProvenanceRow(provenance_id=new_id("PROV"), asset_id=accepted.asset_id,
                job_id=None, provider=provenance.provider, model=provenance.model,
                prompt_template_id=provenance.prompt_template_id, prompt_template_version=provenance.prompt_template_version,
                rendered_prompt_sha256=provenance.rendered_prompt_sha256,
                input_references_json=provenance.input_references_json, input_hashes_json=provenance.input_hashes_json,
                context_manifest_hash=provenance.context_manifest_hash, output_hash=digest,
                generation_timestamp=provenance.generation_timestamp, human_contribution_note=provenance.human_contribution_note,
                ai_classification=provenance.ai_classification, disclosure_decision=provenance.disclosure_decision, reviewer=reviewer)
            session.add_all([accepted, approval, accepted_provenance])
            AuditEventWriter.append(session, actor_id=reviewer, action="concept.accepted", entity_type="asset",
                entity_id=accepted.asset_id, correlation_id=title.title_id, result="success", before_hash=source.sha256,
                after_hash=digest, metadata={"source_asset_id": asset_id, "approval_id": approval.approval_id,
                "provenance_id": accepted_provenance.provenance_id, "conditions": conditions})
            session.commit()
            return ConceptAcceptanceResult(source, accepted, approval, destination)
    except Exception:
        if copied and destination is not None and destination.exists(): destination.unlink()
        raise
