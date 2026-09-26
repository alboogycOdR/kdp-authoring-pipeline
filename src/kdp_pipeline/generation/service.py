from __future__ import annotations

import json
import os
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
from kdp_pipeline.providers.costs import (
    calculate_usage_cost,
    evaluate_and_reserve,
    mark_reservation_uncertain,
    settle_reservation,
)
from kdp_pipeline.storage.audit import AuditEventWriter
from kdp_pipeline.storage.db import (
    AssetRow,
    ModelPricingRow,
    JobRow,
    ProjectRow,
    ProviderProfileRow,
    ProvenanceRow,
    TitleRow,
    UsageEventRow,
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
    provider_profile_id: str | None,
    provider_config_hash: str | None,
) -> dict[str, Any]:
    return {
        "title_id": title_id,
        "task_type": task_type,
        "provider_name": provider_name,
        "model_name": model_name,
        "provider_profile_id": provider_profile_id,
        "provider_config_hash": provider_config_hash,
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
    summary = _redact_environment_secrets(f"{type(error).__name__}: {str(error).strip()}")[:500]
    with session_scope(root) as session:
        job = session.get(JobRow, job_id)
        if job is None:
            return
        job.status = "failed"
        job.error = summary
        job.completed_at = utcnow()
        mark_reservation_uncertain(session, job_id)
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


def _redact_environment_secrets(message: str) -> str:
    for name, value in os.environ.items():
        if value and len(value) >= 8 and any(marker in name.lower() for marker in ("key", "token", "secret", "password")):
            message = message.replace(value, "[REDACTED]")
    return message


class GenerationService:
    @staticmethod
    async def generate(
        root: Path,
        *,
        title_id: str,
        task_type: str,
        rendered_prompt: RenderedPrompt,
        context_manifest: ContextManifest,
        provider: ModelProvider | None = None,
        system_instructions: str,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        structured_output_schema: dict[str, Any] | None = None,
        structured_output_schema_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
        asset_type: str = "generation_output",
        source_ref: str | None = None,
    ) -> GenerationRunResult:
        if provider is None:
            with session_scope(root) as session:
                title_row = session.get(TitleRow, title_id)
                if title_row is None:
                    raise ValueError(f"Unknown title: {title_id}")
                project_id = title_row.project_id
            from kdp_pipeline.providers.configuration import resolve_project_provider
            provider = resolve_project_provider(root, project_id)
        provider_profile_id = getattr(provider, "profile_id", None)
        if max_output_tokens is None:
            max_output_tokens = getattr(provider, "default_max_output_tokens", 1200)
        if temperature is None and hasattr(provider, "default_temperature"):
            temperature = provider.default_temperature
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
            provider_profile_id=provider_profile_id,
            provider_config_hash=getattr(provider, "config_hash", None),
        )
        input_manifest_hash = sha256_bytes(canonical_json_bytes(envelope))
        job_type = f"generate:{task_type}"
        idempotency_key = f"{job_type}:{input_manifest_hash}:{RULESET_VERSION}"

        budget_blocked = None
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
                session.flush()
                profile = session.get(ProviderProfileRow, provider_profile_id) if provider_profile_id else None
                if provider_profile_id and (profile is None or profile.model != model_name):
                    raise GenerationServiceError("Selected provider profile is unavailable")
                pricing = session.get(ModelPricingRow, (provider_profile_id, model_name)) if provider_profile_id else None
                budget_result = evaluate_and_reserve(
                    session, project_id=title.project_id, job_id=job.job_id, pricing=pricing,
                    system_instructions=system_instructions,
                    rendered_prompt=rendered_prompt.rendered_text,
                    max_output_tokens=max_output_tokens,
                )
                if budget_result["blocked"]:
                    budget_blocked = budget_result["blocked"]
                    session.delete(job)
                    session.flush()
                    AuditEventWriter.append(
                        session, actor_id="system", action="generation.budget.blocked",
                        entity_type="title", entity_id=title_id, correlation_id=title_id,
                        result="blocked", metadata={"provider_id": provider_profile_id,
                                                    "model": model_name,
                                                    "reason": budget_blocked},
                    )
                    session.commit()
                else:
                    AuditEventWriter.append(
                        session,
                        actor_id="system",
                        action="generation.job.created",
                        entity_type="job",
                        entity_id=job.job_id,
                        correlation_id=job.job_id,
                        result="success",
                        metadata={"idempotency_key": idempotency_key, "task_type": task_type,
                                  "provider_id": provider_profile_id,
                                  "preflight_estimated_cost_usd": budget_result["estimate"],
                                  "preflight_currency": budget_result["currency"],
                                  "reservation_id": (budget_result["reservation"].reservation_id
                                                     if budget_result["reservation"] else None)},
                    )
                    if budget_result["warning"]:
                        AuditEventWriter.append(
                            session, actor_id="system", action="generation.budget.warning",
                            entity_type="job", entity_id=job.job_id,
                            correlation_id=job.job_id, result="warning",
                            metadata={"warning": budget_result["warning"]},
                        )
                    session.commit()

        if budget_blocked:
            raise GenerationServiceError(budget_blocked)

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
            raw_message = str(error)
            safe_message = _redact_environment_secrets(raw_message)
            if safe_message != raw_message:
                raise GenerationServiceError(f"{type(error).__name__}: {safe_message}") from None
            raise

        # Record provider usage before filesystem persistence so a later file or
        # asset-write failure cannot erase costs already incurred remotely.
        with session_scope(root) as session:
            title = session.get(TitleRow, title_id)
            pricing = session.get(ModelPricingRow, (provider_profile_id, model_name)) if provider_profile_id else None
            cost_data = calculate_usage_cost(generation_result.usage, pricing)
            usage_event = UsageEventRow(
                usage_event_id=new_id("USE"), title_id=title_id, project_id=title.project_id,
                job_id=job.job_id, asset_id=None, provider_id=provider_profile_id,
                provider=generation_result.provider, model=generation_result.model,
                input_tokens=cost_data["input_tokens"], output_tokens=cost_data["output_tokens"],
                total_tokens=cost_data["total_tokens"], cached_input_tokens=cost_data["cached_input_tokens"],
                estimated_cost=cost_data["estimated_cost"], currency=cost_data["currency"],
                source=cost_data["source"],
                cost_details_json=json.dumps(cost_data["cost_details"], sort_keys=True), created_at=utcnow(),
            )
            session.add(usage_event)
            budget_cost = cost_data["estimated_cost"] if cost_data["currency"] in (None, "USD") else None
            settle_reservation(session, job.job_id, budget_cost)
            AuditEventWriter.append(
                session, actor_id="system", action="generation.usage.recorded",
                entity_type="usage_event", entity_id=usage_event.usage_event_id,
                correlation_id=job.job_id, result="success",
                metadata={"provider_id": provider_profile_id, "provider": generation_result.provider,
                          "model": generation_result.model, "input_tokens": cost_data["input_tokens"],
                          "output_tokens": cost_data["output_tokens"], "total_tokens": cost_data["total_tokens"],
                          "estimated_cost": cost_data["estimated_cost"], "currency": cost_data["currency"],
                          "source": cost_data["source"], "cost_details": cost_data["cost_details"]},
            )
            session.commit()

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
                title = session.get(TitleRow, title_id)
                asset = AssetRow(
                    asset_id=new_id("AST"),
                    title_id=title_id,
                    asset_type=asset_type,
                    path=str(output_path),
                    version="1.0",
                    sha256=output_hash,
                    creator_type="ai",
                    creator=generation_result.provider,
                    source_ref=source_ref,
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
                usage_event = session.scalar(select(UsageEventRow).where(UsageEventRow.job_id == job.job_id))
                if usage_event is not None:
                    usage_event.asset_id = asset.asset_id
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
