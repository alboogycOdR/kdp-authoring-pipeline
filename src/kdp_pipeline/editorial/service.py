from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from kdp_pipeline.chapter.service import _planning_context
from kdp_pipeline.core.ids import new_id
from kdp_pipeline.generation import GenerationRunResult, GenerationService
from kdp_pipeline.providers import ModelProvider
from kdp_pipeline.prompts import PromptRegistry
from kdp_pipeline.storage.audit import AuditEventWriter
from kdp_pipeline.storage.db import AssetRow, EditorialFindingRow, TitleRow, utcnow
from kdp_pipeline.storage.files import write_json
from kdp_pipeline.storage.service import session_scope


@dataclass(frozen=True)
class EditorialRunResult:
    generation: GenerationRunResult
    finding: EditorialFindingRow


class EditorialService:
    @staticmethod
    async def developmental(
        root: Path,
        *,
        title_id: str,
        chapter_number: int,
        source_asset_id: str,
        provider: ModelProvider,
    ) -> EditorialRunResult:
        with session_scope(root) as session:
            title = session.get(TitleRow, title_id)
            source = session.get(AssetRow, source_asset_id)
            if title is None or source is None or source.title_id != title_id:
                raise ValueError("Unknown title or source chapter asset")
            if title.status != "DRAFTING":
                raise ValueError("Developmental editing requires DRAFTING state")
            if source.approval_status != "experimental":
                raise ValueError("Developmental editing requires an experimental chapter asset")
            manifest = _planning_context(session, title_id, source, chapter_number)
            title_values = {"title_id": title_id, "working_title": title.working_title, "chapter_number": str(chapter_number)}
        prompt = PromptRegistry(root / "prompts").render("editorial/developmental", title_values)
        generation = await GenerationService.generate(
            root, title_id=title_id, task_type=f"chapter.editorial.developmental.{chapter_number}",
            rendered_prompt=prompt, context_manifest=manifest, provider=provider,
            system_instructions="Identify developmental issues as findings; do not rewrite the chapter.",
            max_output_tokens=1200, temperature=0, asset_type="analysis.editorial.developmental",
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

