from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

from sqlalchemy import select

from kdp_pipeline.chapter.service import _planning_context
from kdp_pipeline.chapter.service import _accepted_chapter_card, _chapter_authoring_context
from kdp_pipeline.context import ContextInput, ContextManifest
from kdp_pipeline.core.ids import new_id
from kdp_pipeline.generation import GenerationRunResult, GenerationService
from kdp_pipeline.providers import ModelProvider
from kdp_pipeline.prompts import PromptRegistry
from kdp_pipeline.storage.audit import AuditEventWriter
from kdp_pipeline.storage.db import (AssetRow, EditorialFindingRow, JobRow, RevisionRecommendationRow,
                                     TitleRow, utcnow)
from kdp_pipeline.storage.files import write_json
from kdp_pipeline.storage.service import session_scope
from kdp_pipeline.models.editorial import StructuredEditorialOutput
from pydantic import ValidationError


@dataclass(frozen=True)
class EditorialRunResult:
    generation: GenerationRunResult
    finding: EditorialFindingRow


@dataclass(frozen=True)
class StructuredEditorialRunResult:
    generation: GenerationRunResult
    output: StructuredEditorialOutput
    findings: list[EditorialFindingRow]


STRUCTURED_PASSES = {"voice", "line", "copy", "reader-experience", "consistency"}
_MISSING_CONTEXT = re.compile(r"(resend|provide|supply|need).{0,50}(chapter|draft|context|card|brief|outline)|\bno (chapter|draft|context) (text|was|provided|available)", re.I | re.S)
_CHAPTER_SOURCE_NUMBER = re.compile(r"chapter\.(?:draft|revision|revise)\.(?P<number>\d+)-", re.I)


def _parse_structured_output(text: str) -> StructuredEditorialOutput:
    if not text.strip() or _MISSING_CONTEXT.search(text):
        raise ValueError("Editorial output is empty or indicates required context is missing")
    try:
        output = StructuredEditorialOutput.model_validate_json(text)
    except ValidationError as exc:
        raise ValueError("Editorial output failed the structured editorial contract") from exc
    if not output.supplied_context_confirmed:
        raise ValueError("Editorial output did not confirm supplied context")
    return output


def _reject_structured_output(root: Path, job_id: str, reason: str) -> None:
    with session_scope(root) as session:
        job = session.get(JobRow, job_id)
        if job:
            job.status = "failed"
            job.error = "Editorial output rejected as unusable: " + reason[:300]
            job.completed_at = utcnow()
            AuditEventWriter.append(session, actor_id="system", action="editorial.output.rejected",
                entity_type="job", entity_id=job_id, correlation_id=job_id, result="failed",
                metadata={"reason": reason[:300], "findings_created": 0, "proposals_created": 0})
            session.commit()


class StructuredEditorialService:
    @staticmethod
    async def analyze(root: Path, *, title_id: str, chapter_number: int, source_asset_id: str,
                      pass_type: str, provider: ModelProvider | None = None,
                      max_output_tokens: int | None = None) -> StructuredEditorialRunResult:
        if pass_type not in STRUCTURED_PASSES:
            raise ValueError(f"Unsupported structured editorial pass: {pass_type}")
        with session_scope(root) as session:
            title = session.get(TitleRow, title_id)
            source = session.get(AssetRow, source_asset_id)
            if title is None or source is None or source.title_id != title_id:
                raise ValueError("Unknown title or source chapter asset")
            if title.status != "DRAFTING":
                raise ValueError("Editorial analysis requires DRAFTING state")
            if source.approval_status != "experimental" or source.asset_type not in {"chapter.draft", "chapter.revision"}:
                raise ValueError("Structured editorial analysis requires an experimental chapter asset")
            source_match = _CHAPTER_SOURCE_NUMBER.search(Path(source.path).name)
            if source_match is not None and int(source_match.group("number")) != chapter_number:
                raise ValueError("Source chapter asset does not match the requested chapter number")
            card = _accepted_chapter_card(session, title_id, chapter_number)
            if card is None:
                raise ValueError(f"Accepted chapter card not found for chapter {chapter_number}")
            base = _planning_context(session, title_id, card, chapter_number)
            manifest = ContextManifest(title_id=title_id, task_type=f"editorial.{pass_type}.{chapter_number}",
                inputs=base.inputs + [ContextInput(input_ref=source.asset_id, sha256=source.sha256,
                    context_tier="A", role="target_chapter_draft")])
            manifest, chapter_context = _chapter_authoring_context(session, title_id, chapter_number, manifest)
            variables = {"title_id": title_id, "working_title": title.working_title,
                         "chapter_number": str(chapter_number), "chapter_context": chapter_context}
        prompt = PromptRegistry(root / "prompts").render(f"editorial/{pass_type}", variables, template_version="1.0")
        generation = await GenerationService.generate(root, title_id=title_id,
            task_type=f"chapter.editorial.{pass_type}.{chapter_number}", rendered_prompt=prompt,
            context_manifest=manifest, provider=provider,
            system_instructions="Analyze only the supplied chapter and accepted context. Return the required JSON contract; do not rewrite or accept content.",
            max_output_tokens=max_output_tokens, asset_type=f"analysis.editorial.{pass_type}",
            source_ref=source_asset_id,
            metadata={"pass_type": pass_type, "chapter_number": chapter_number, "source_asset_id": source_asset_id})
        try:
            output = _parse_structured_output(generation.generation_result.text)
        except ValueError as exc:
            _reject_structured_output(root, generation.job.job_id, str(exc))
            raise
        findings = []
        with session_scope(root) as session:
            title = session.get(TitleRow, title_id)
            for item in output.findings:
                finding = EditorialFindingRow(finding_id=new_id("FND"), title_id=title_id,
                    asset_id=generation.asset.asset_id, pass_type=pass_type,
                    severity=item.severity, location=f"chapter-{chapter_number:03d}: {item.location}",
                    description=item.issue, evidence=item.evidence, recommended_action=item.recommended_action,
                    status="open", created_at=utcnow())
                finding.snapshot_path = str(root / "projects" / title.project_id / "titles" / title_id
                    / "07_editorial" / "findings" / f"{finding.finding_id}.json")
                session.add(finding)
                AuditEventWriter.append(session, actor_id="system", action="editorial.finding.created",
                    entity_type="finding", entity_id=finding.finding_id, correlation_id=generation.job.job_id,
                    result="success", metadata={"pass_type": pass_type, "analysis_asset_id": generation.asset.asset_id,
                        "source_asset_id": source_asset_id, "severity": item.severity})
                findings.append(finding)
            AuditEventWriter.append(session, actor_id="system", action="editorial.output.validated",
                entity_type="job", entity_id=generation.job.job_id, correlation_id=generation.job.job_id,
                result="success", metadata={"pass_type": pass_type, "status": output.status,
                    "supplied_context_confirmed": output.supplied_context_confirmed,
                    "finding_count": len(findings)})
            session.commit()
        for finding, item in zip(findings, output.findings):
            write_json(Path(finding.snapshot_path), {"finding_id": finding.finding_id, "title_id": title_id,
                "asset_id": source_asset_id, "analysis_asset_id": generation.asset.asset_id,
                "pass_type": pass_type, "severity": item.severity, "location": finding.location,
                "description": item.issue, "evidence": item.evidence,
                "recommended_action": item.recommended_action, "status": "open"})
        return StructuredEditorialRunResult(generation, output, findings)


def create_revision_recommendation(root: Path, *, title_id: str, chapter_number: int,
                                   source_asset_id: str, finding_ids: list[str], owner: str) -> RevisionRecommendationRow:
    if chapter_number < 1 or not finding_ids or not owner.strip():
        raise ValueError("Revision recommendation requires chapter, findings, and owner")
    with session_scope(root) as session:
        source = session.get(AssetRow, source_asset_id)
        if source is None or source.title_id != title_id or source.asset_type not in {"chapter.draft", "chapter.revision"} or source.approval_status != "experimental":
            raise ValueError("Recommendation source must be an experimental chapter draft/revision")
        findings = [session.get(EditorialFindingRow, finding_id) for finding_id in finding_ids]
        if any(f is None or f.title_id != title_id or f.status != "open" for f in findings):
            raise ValueError("All recommendation findings must exist, belong to the title, and remain open")
        if any(not f.location.startswith(f"chapter-{chapter_number:03d}") for f in findings):
            raise ValueError("All findings must refer to the requested chapter")
        recommendation = "\n".join(f"- {f.pass_type}: {f.recommended_action or f.description}" for f in findings)
        row = RevisionRecommendationRow(recommendation_id=new_id("RRC"), title_id=title_id,
            chapter_number=chapter_number, source_asset_id=source_asset_id,
            finding_ids_json=json.dumps(finding_ids), recommendation=recommendation,
            status="open", owner=owner, created_at=utcnow())
        session.add(row)
        AuditEventWriter.append(session, actor_id=owner, action="editorial.revision_recommendation.created",
            entity_type="revision_recommendation", entity_id=row.recommendation_id,
            correlation_id=title_id, result="success", metadata={"chapter_number": chapter_number,
                "source_asset_id": source_asset_id, "finding_ids": finding_ids})
        session.commit()
        return row


class EditorialService:
    @staticmethod
    async def developmental(
        root: Path,
        *,
        title_id: str,
        chapter_number: int,
        source_asset_id: str,
        provider: ModelProvider | None = None,
        max_output_tokens: int | None = None,
    ) -> EditorialRunResult:
        with session_scope(root) as session:
            title = session.get(TitleRow, title_id)
            source = session.get(AssetRow, source_asset_id)
            if title is None or source is None or source.title_id != title_id:
                raise ValueError("Unknown title or source chapter asset")
            if title.status != "DRAFTING":
                raise ValueError("Developmental editing requires DRAFTING state")
            if source.approval_status != "experimental" or source.asset_type not in {"chapter.draft", "chapter.revision"}:
                raise ValueError("Developmental editing requires an experimental chapter asset")
            card = _accepted_chapter_card(session, title_id, chapter_number)
            if card is None:
                raise ValueError(f"Accepted chapter card not found for chapter {chapter_number}")
            base = _planning_context(session, title_id, card, chapter_number)
            manifest = ContextManifest(title_id=title_id, task_type=f"editorial.developmental.{chapter_number}",
                inputs=base.inputs + [ContextInput(input_ref=source.asset_id, sha256=source.sha256,
                                                   context_tier="A", role="target_chapter_draft")])
            # The manifest must describe exactly what is sent (KDP-AUD-005): render the same inputs.
            manifest, chapter_context = _chapter_authoring_context(session, title_id, chapter_number, manifest)
            title_values = {"title_id": title_id, "working_title": title.working_title,
                            "chapter_number": str(chapter_number), "chapter_context": chapter_context}
        prompt = PromptRegistry(root / "prompts").render("editorial/developmental", title_values, template_version="1.1")
        generation = await GenerationService.generate(
            root, title_id=title_id, task_type=f"chapter.editorial.developmental.{chapter_number}",
            rendered_prompt=prompt, context_manifest=manifest, provider=provider,
            system_instructions="Identify developmental issues as findings; do not rewrite the chapter.",
            max_output_tokens=max_output_tokens,
            temperature=0 if provider is not None else None, asset_type="analysis.editorial.developmental",
            source_ref=source_asset_id, metadata={"chapter_number": chapter_number, "source_asset_id": source_asset_id, "pass_type": "developmental"},
        )
        with session_scope(root) as session:
            existing_finding = session.scalar(select(EditorialFindingRow).where(
                EditorialFindingRow.asset_id == generation.asset.asset_id,
                EditorialFindingRow.pass_type == "developmental",
            ))
            if existing_finding is not None:
                AuditEventWriter.append(
                    session, actor_id="system", action="editorial.reused", entity_type="finding",
                    entity_id=existing_finding.finding_id, correlation_id=generation.job.job_id, result="success",
                    metadata={"analysis_asset_id": generation.asset.asset_id},
                )
                session.commit()
                return EditorialRunResult(generation, existing_finding)
            finding = EditorialFindingRow(
                finding_id=new_id("FND"), title_id=title_id, asset_id=generation.asset.asset_id,
                pass_type="developmental", severity="review", location=f"chapter-{chapter_number:03d}",
                description=generation.generation_result.text, evidence=generation.generation_result.text,
                recommended_action="Review the developmental findings before deciding on a revision.",
                status="open", created_at=utcnow(),
            )
            finding.snapshot_path = str(root / "projects" / title.project_id / "titles" / title_id / "07_editorial" / "findings" / f"{finding.finding_id}.json")
            session.add(finding)
            AuditEventWriter.append(session, actor_id="system", action="editorial.finding.created", entity_type="finding", entity_id=finding.finding_id,
                                    correlation_id=generation.job.job_id, result="success", metadata={"pass_type": "developmental", "analysis_asset_id": generation.asset.asset_id, "source_asset_id": source_asset_id})
            session.commit()
            data = {"finding_id": finding.finding_id, "title_id": title_id, "asset_id": source_asset_id, "pass_type": finding.pass_type,
                    "severity": finding.severity, "location": finding.location, "description": finding.description, "status": finding.status}
            snapshot = Path(finding.snapshot_path)
        write_json(snapshot, data)
        return EditorialRunResult(generation, finding)

