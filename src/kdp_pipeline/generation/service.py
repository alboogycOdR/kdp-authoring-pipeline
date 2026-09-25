from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

from kdp_pipeline.context import ContextManifest
from kdp_pipeline.core.hashing import canonical_json_bytes, sha256_bytes
from kdp_pipeline.core.ids import new_id
from kdp_pipeline.models.schemas import ProvenanceRecord
from kdp_pipeline.providers import GenerationRequest, GenerationResult, ModelProvider, RenderedPrompt
from kdp_pipeline.storage.audit import AuditEventWriter
from kdp_pipeline.storage.db import (
    AssetRow,
    JobRow,
    ProjectRow,
    ProvenanceRow,
    TitleRow,
    utcnow,
)
from kdp_pipeline.storage.files import sha256_file, write_text
from kdp_pipeline.storage.service import session_scope


RULESET_VERSION = "sprint-2b-v1"
_SAFE_TASK_TYPE = re.compile(r"[^A-Za-z0-9._-]+")


class GenerationServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class GenerationRunResult:
    job: JobRow
    asset: AssetRow
    provenance: ProvenanceRecord
    output_path: Path
    generation_result: GenerationResult
    reused: bool


def _provider_identity(provider: ModelProvider) -> tuple[str, str]:
    provider_name = getattr(provider, "provider_name", None)
    model_name = getattr(provider, "model_name", None)
    if not isinstance(provider_name, str) or not provider_name:
        raise TypeError("Provider must expose a non-empty provider_name")
    if not isinstance(model_name, str) or not model_name:
        raise TypeError("Provider must expose a non-empty model_name")
    return provider_name, model_name


def _safe_task_type(task_type: str) -> str:
    safe = _SAFE_TASK_TYPE.sub("-", task_type).strip("-._")
    return safe or "generation"


def _input_envelope(
    *,
    title_id: str,
    task_type: str,
    provider_name: str,
    model_name: str,
    rendered_prompt: RenderedPrompt,
    context_manifest: ContextManifest,
    system_instructions: str,
    max_output_tokens: int,
    temperature: float | None,
    structured_output_schema: dict[str, Any] | None,
    structured_output_schema_ref: str | None,
) -> dict[str, Any]:
    return {
        "title_id": title_id,
        "task_type": task_type,
        "provider_name": provider_name,
        "model_name": model_name,
        "rendered_prompt": {
            "template_id": rendered_prompt.template_id,
            "template_version": rendered_prompt.template_version,
            "rendered_sha256": rendered_prompt.rendered_sha256,
        },
        "context_manifest_hash": context_manifest.manifest_hash,
        "system_instructions": system_instructions,
        "max_output_tokens": max_output_tokens,
        "temperature": temperature,
        "structured_output_schema": structured_output_schema,
        "structured_output_schema_ref": structured_output_schema_ref,
    }


def _provenance_from_row(row: ProvenanceRow) -> ProvenanceRecord:
    return ProvenanceRecord(
        provenance_id=row.provenance_id,
        asset_id=row.asset_id,
        job_id=row.job_id,
        provider=row.provider,
        model=row.model,
        prompt_template_id=row.prompt_template_id,
        prompt_template_version=row.prompt_template_version,
        rendered_prompt_sha256=row.rendered_prompt_sha256,
        input_references=json.loads(row.input_references_json),
        input_hashes=json.loads(row.input_hashes_json),
        context_manifest_hash=row.context_manifest_hash,
        output_hash=row.output_hash,
        generation_timestamp=row.generation_timestamp,
        human_contribution_note=row.human_contribution_note,
        ai_classification=row.ai_classification,
        disclosure_decision=row.disclosure_decision,
        reviewer=row.reviewer,
    )


def _existing_result(root: Path, job: JobRow, *, reused: bool) -> GenerationRunResult:
    asset_ids = json.loads(job.result_asset_ids_json or "[]")
    if not asset_ids:
        raise GenerationServiceError(f"Successful job has no result asset: {job.job_id}")
    with session_scope(root) as session:
        asset = session.get(AssetRow, asset_ids[0])
        provenance = session.scalar(select(ProvenanceRow).where(ProvenanceRow.job_id == job.job_id))
        if asset is None or provenance is None:
            raise GenerationServiceError(f"Successful job is missing persisted result data: {job.job_id}")
        output_path = Path(asset.path)
        text = output_path.read_text(encoding="utf-8")
        generation_result = GenerationResult(
            provider=job.provider or provenance.provider,
            model=job.model or provenance.model,
            text=text,
        )
        result = GenerationRunResult(
            job=job,
            asset=asset,
            provenance=_provenance_from_row(provenance),
            output_path=output_path,
            generation_result=generation_result,
            reused=reused,
        )
    if reused:
        with session_scope(root) as session:
            AuditEventWriter.append(
                session,
                actor_id="system",
                action="generation.reused",
                entity_type="job",
                entity_id=job.job_id,
                correlation_id=job.job_id,
                result="success",
                metadata={"idempotency_key": job.idempotency_key},
            )
            session.commit()
    return result


def _mark_failed(root: Path, job_id: str, error: BaseException) -> None:
    summary = f"{type(error).__name__}: {str(error).strip()}"[:500]
    with session_scope(root) as session:
        job = session.get(JobRow, job_id)
        if job is None:
            return
        job.status = "failed"
        job.error = summary
        job.completed_at = utcnow()
        AuditEventWriter.append(
            session,
            actor_id="system",
            action="generation.failed",
            entity_type="job",
            entity_id=job_id,
            correlation_id=job_id,
            result="failed",
            metadata={"error": summary},
        )
        session.commit()


class GenerationService:
    @staticmethod
    async def generate(
        root: Path,
        *,
        title_id: str,
        task_type: str,
        rendered_prompt: RenderedPrompt,
        context_manifest: ContextManifest,
        provider: ModelProvider,
        system_instructions: str,
        max_output_tokens: int,
        temperature: float | None = None,
        structured_output_schema: dict[str, Any] | None = None,
        structured_output_schema_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
        asset_type: str = "generation_output",
    ) -> GenerationRunResult:
        provider_name, model_name = _provider_identity(provider)
        envelope = _input_envelope(
            title_id=title_id,
            task_type=task_type,
            provider_name=provider_name,
            model_name=model_name,
            rendered_prompt=rendered_prompt,
            context_manifest=context_manifest,
            system_instructions=system_instructions,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            structured_output_schema=structured_output_schema,
            structured_output_schema_ref=structured_output_schema_ref,
        )
        input_manifest_hash = sha256_bytes(canonical_json_bytes(envelope))
        job_type = f"generate:{task_type}"
        idempotency_key = f"{job_type}:{input_manifest_hash}:{RULESET_VERSION}"

        with session_scope(root) as session:
            title = session.get(TitleRow, title_id)
            if title is None:
                raise ValueError(f"Unknown title: {title_id}")
            existing = session.scalar(select(JobRow).where(JobRow.idempotency_key == idempotency_key))
            if existing is not None:
                if existing.status == "success":
                    existing_job = existing
                else:
                    raise GenerationServiceError(
                        f"Generation idempotency key already exists with status {existing.status}: {existing.job_id}"
                    )
            else:
                existing_job = None
                job = JobRow(
                    job_id=new_id("JOB"),
                    title_id=title_id,
                    job_type=job_type,
                    status="queued",
                    idempotency_key=idempotency_key,
                    input_manifest_hash=input_manifest_hash,
                    provider=provider_name,
                    model=model_name,
                    created_at=utcnow(),
                )
                session.add(job)
                AuditEventWriter.append(
                    session,
                    actor_id="system",
                    action="generation.job.created",
                    entity_type="job",
                    entity_id=job.job_id,
                    correlation_id=job.job_id,
                    result="success",
                    metadata={"idempotency_key": idempotency_key, "task_type": task_type},
                )
                session.commit()

        if existing_job is not None:
            return _existing_result(root, existing_job, reused=True)

        with session_scope(root) as session:
            job = session.get(JobRow, job.job_id)
            job.status = "running"
            job.started_at = utcnow()
            AuditEventWriter.append(
                session,
                actor_id="system",
                action="generation.started",
                entity_type="job",
                entity_id=job.job_id,
                correlation_id=job.job_id,
                result="success",
            )
            session.commit()

        request = GenerationRequest(
            task_type=task_type,
            system_instructions=system_instructions,
            rendered_prompt=rendered_prompt,
            context_manifest_ref=context_manifest.manifest_hash,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            structured_output_schema=structured_output_schema,
            structured_output_schema_ref=structured_output_schema_ref,
            metadata=metadata or {},
        )
        try:
            generation_result = await provider.generate(request)
            if generation_result.provider != provider_name or generation_result.model != model_name:
                raise GenerationServiceError("Provider result identity does not match declared provider identity")
        except Exception as error:
            _mark_failed(root, job.job_id, error)
            raise

        output_path: Path | None = None
        try:
            with session_scope(root) as session:
                title = session.get(TitleRow, title_id)
                project = session.get(ProjectRow, title.project_id)
                output_path = (
                    root / "projects" / project.project_id / "titles" / title_id
                    / "05_drafts" / "experimental"
                    / f"{_safe_task_type(task_type)}-{job.job_id}.md"
                )
            write_text(output_path, generation_result.text)
            output_hash = sha256_file(output_path)
            input_references = [item.input_ref for item in context_manifest.inputs]
            input_hashes = [item.sha256 for item in context_manifest.inputs]
            with session_scope(root) as session:
                job = session.get(JobRow, job.job_id)
                asset = AssetRow(
                    asset_id=new_id("AST"),
                    title_id=title_id,
                    asset_type=asset_type,
                    path=str(output_path),
                    version="1.0",
                    sha256=output_hash,
                    creator_type="ai",
                    creator=generation_result.provider,
                    ai_classification="AI_GENERATED",
                    approval_status="experimental",
                    created_at=utcnow(),
                )
                provenance_row = ProvenanceRow(
                    provenance_id=new_id("PROV"),
                    asset_id=asset.asset_id,
                    job_id=job.job_id,
                    provider=generation_result.provider,
                    model=generation_result.model,
                    prompt_template_id=rendered_prompt.template_id,
                    prompt_template_version=rendered_prompt.template_version,
                    rendered_prompt_sha256=rendered_prompt.rendered_sha256,
                    input_references_json=json.dumps(input_references, ensure_ascii=False),
                    input_hashes_json=json.dumps(input_hashes, ensure_ascii=False),
                    context_manifest_hash=context_manifest.manifest_hash,
                    output_hash=output_hash,
                    generation_timestamp=utcnow(),
                    ai_classification="AI_GENERATED",
                )
                session.add(asset)
                session.add(provenance_row)
                job.status = "success"
                job.provider = generation_result.provider
                job.model = generation_result.model
                job.completed_at = utcnow()
                job.result_asset_ids_json = json.dumps([asset.asset_id])
                AuditEventWriter.append(
                    session,
                    actor_id=generation_result.provider,
                    action="asset.register",
                    entity_type="asset",
                    entity_id=asset.asset_id,
                    correlation_id=job.job_id,
                    result="success",
                    after_hash=output_hash,
                    metadata={"approval_status": "experimental", "job_id": job.job_id},
                )
                AuditEventWriter.append(
                    session,
                    actor_id="system",
                    action="provenance.create",
                    entity_type="provenance",
                    entity_id=provenance_row.provenance_id,
                    correlation_id=job.job_id,
                    result="success",
                    metadata={"asset_id": asset.asset_id, "job_id": job.job_id},
                )
                AuditEventWriter.append(
                    session,
                    actor_id="system",
                    action="generation.succeeded",
                    entity_type="job",
                    entity_id=job.job_id,
                    correlation_id=job.job_id,
                    result="success",
                    after_hash=output_hash,
                    metadata={"asset_id": asset.asset_id, "provenance_id": provenance_row.provenance_id},
                )
                session.commit()
                return GenerationRunResult(
                    job=job,
                    asset=asset,
                    provenance=_provenance_from_row(provenance_row),
                    output_path=output_path,
                    generation_result=generation_result,
                    reused=False,
                )
        except Exception as error:
            if output_path is not None and output_path.exists():
                output_path.unlink()
            _mark_failed(root, job.job_id, error)
            raise


async def generate(*args, **kwargs) -> GenerationRunResult:
    return await GenerationService.generate(*args, **kwargs)
