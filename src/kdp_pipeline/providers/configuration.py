from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import select

from kdp_pipeline.core.hashing import canonical_json_bytes, sha256_bytes
from kdp_pipeline.providers import FakeProvider, OpenAICompatibleConfig, OpenAICompatibleProvider
from kdp_pipeline.providers.settings import ProviderCheckResult, ProviderProfileSettings, ProviderProfileView
from kdp_pipeline.storage.audit import AuditEventWriter
from kdp_pipeline.storage.db import (
    ProjectProviderSelectionRow,
    ProjectRow,
    ProviderProfileRow,
    utcnow,
)
from kdp_pipeline.storage.service import session_scope


def _is_loopback(base_url: str | None) -> bool:
    hostname = urlparse(base_url or "").hostname
    return hostname in {"localhost", "127.0.0.1", "::1"}


def _profile_dict(row: ProviderProfileRow, selected_for: list[str]) -> dict:
    return {
        "provider_id": row.provider_id,
        "provider_type": row.provider_type,
        "display_name": row.display_name,
        "enabled": row.enabled,
        "base_url": row.base_url,
        "model": row.model,
        "api_key_env": row.api_key_env,
        "default_max_output_tokens": row.default_max_output_tokens,
        "default_temperature": row.default_temperature,
        "priority": row.priority,
        "notes": row.notes,
        "metadata": json.loads(row.metadata_json or "{}"),
        "api_key_configured": bool(os.getenv(row.api_key_env)) if row.api_key_env else False,
        "selected_for_projects": selected_for,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def list_provider_profiles(root: Path) -> list[dict]:
    with session_scope(root) as session:
        profiles = list(session.scalars(select(ProviderProfileRow).order_by(
            ProviderProfileRow.priority.is_(None), ProviderProfileRow.priority, ProviderProfileRow.display_name
        )))
        selections = list(session.scalars(select(ProjectProviderSelectionRow)))
        by_provider: dict[str, list[str]] = {}
        for selection in selections:
            by_provider.setdefault(selection.provider_id, []).append(selection.project_id)
        return [_profile_dict(row, sorted(by_provider.get(row.provider_id, []))) for row in profiles]


def show_provider_profile(root: Path, provider_id: str) -> dict:
    with session_scope(root) as session:
        row = session.get(ProviderProfileRow, provider_id)
        if row is None:
            raise ValueError(f"Unknown provider profile: {provider_id}")
        selected_for = list(session.scalars(select(ProjectProviderSelectionRow.project_id).where(
            ProjectProviderSelectionRow.provider_id == provider_id
        )))
        return _profile_dict(row, sorted(selected_for))


def add_provider_profile(root: Path, settings: ProviderProfileSettings) -> dict:
    payload = settings.model_dump(mode="json")
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    sensitive_markers = ("key", "token", "secret", "password", "credential", "authorization")
    secret_values = [value for name, value in os.environ.items()
                     if set(re.sub(r"[^a-z0-9]+", "_", name.lower()).split("_")) & set(sensitive_markers)
                     and len(value) >= 8]
    referenced_secret = os.getenv(settings.api_key_env) if settings.api_key_env else None
    def contains_sensitive_key(value) -> bool:
        if isinstance(value, dict):
            return any(bool(set(re.sub(r"[^a-z0-9]+", "_", str(key).lower()).split("_"))
                                & set(sensitive_markers))
                       or contains_sensitive_key(child) for key, child in value.items())
        if isinstance(value, list):
            return any(contains_sensitive_key(child) for child in value)
        return False
    if (any(value in serialized for value in secret_values)
            or (referenced_secret and referenced_secret in serialized)
            or contains_sensitive_key(settings.metadata)):
        raise ValueError("Provider settings must not contain secret values or credential-like metadata fields")
    with session_scope(root) as session:
        if session.get(ProviderProfileRow, settings.provider_id) is not None:
            raise ValueError(f"Provider profile already exists: {settings.provider_id}")
        row = ProviderProfileRow(
            provider_id=settings.provider_id,
            provider_type=settings.provider_type,
            display_name=settings.display_name,
            enabled=settings.enabled,
            base_url=settings.base_url,
            model=settings.model,
            api_key_env=settings.api_key_env,
            default_max_output_tokens=settings.default_max_output_tokens,
            default_temperature=settings.default_temperature,
            priority=settings.priority,
            notes=settings.notes,
            metadata_json=json.dumps(settings.metadata, ensure_ascii=False, sort_keys=True),
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(row)
        AuditEventWriter.append(
            session, actor_id="operator", action="provider.profile.created",
            entity_type="provider_profile", entity_id=settings.provider_id,
            correlation_id=settings.provider_id, result="success",
            after_hash=sha256_bytes(canonical_json_bytes(payload)),
            metadata={"provider_type": settings.provider_type, "model": settings.model,
                      "api_key_env": settings.api_key_env},
        )
        session.commit()
    return show_provider_profile(root, settings.provider_id)


def set_provider_enabled(root: Path, provider_id: str, enabled: bool) -> dict:
    with session_scope(root) as session:
        row = session.get(ProviderProfileRow, provider_id)
        if row is None:
            raise ValueError(f"Unknown provider profile: {provider_id}")
        before = row.enabled
        row.enabled = enabled
        row.updated_at = utcnow()
        action = "provider.profile.enabled" if enabled else "provider.profile.disabled"
        AuditEventWriter.append(
            session, actor_id="operator", action=action,
            entity_type="provider_profile", entity_id=provider_id,
            correlation_id=provider_id, result="success",
            metadata={"before": before, "after": enabled},
        )
        session.commit()
    return show_provider_profile(root, provider_id)


def select_provider_for_project(root: Path, project_id: str, provider_id: str) -> dict:
    with session_scope(root) as session:
        project = session.get(ProjectRow, project_id)
        profile = session.get(ProviderProfileRow, provider_id)
        if project is None:
            raise ValueError(f"Unknown project: {project_id}")
        if profile is None or not profile.enabled:
            raise ValueError("Provider profile is unknown or disabled")
        selection = session.get(ProjectProviderSelectionRow, project_id)
        before = selection.provider_id if selection else None
        if selection is None:
            selection = ProjectProviderSelectionRow(project_id=project_id, provider_id=provider_id, selected_at=utcnow())
            session.add(selection)
        else:
            selection.provider_id = provider_id
            selection.selected_at = utcnow()
        AuditEventWriter.append(
            session, actor_id="operator", action="provider.project.selected",
            entity_type="project", entity_id=project_id, correlation_id=project_id,
            result="success", metadata={"before_provider_id": before, "provider_id": provider_id},
        )
        session.commit()
    return {"project_id": project_id, "provider_id": provider_id, "selected": True}


def resolve_project_provider(root: Path, project_id: str):
    with session_scope(root) as session:
        selection = session.get(ProjectProviderSelectionRow, project_id)
        if selection is None:
            raise ValueError(f"No provider is selected for project {project_id}; select one with `kdp providers select`")
        row = session.get(ProviderProfileRow, selection.provider_id)
        if row is None or not row.enabled:
            raise ValueError(f"Selected provider {selection.provider_id} is missing or disabled")
        config = ProviderProfileSettings(
            provider_id=row.provider_id, provider_type=row.provider_type, display_name=row.display_name,
            enabled=row.enabled, base_url=row.base_url, model=row.model, api_key_env=row.api_key_env,
            default_max_output_tokens=row.default_max_output_tokens,
            default_temperature=row.default_temperature, priority=row.priority,
            notes=row.notes, metadata=json.loads(row.metadata_json or "{}"),
        )
    if config.provider_type == "fake":
        provider = FakeProvider(provider_name="fake", model_name=config.model)
    else:
        if config.api_key_env and not os.getenv(config.api_key_env) and not _is_loopback(config.base_url):
            raise ValueError(f"API key is missing from environment variable {config.api_key_env}")
        provider = OpenAICompatibleProvider(OpenAICompatibleConfig(
            base_url=config.base_url or "https://api.openai.com/v1",
            model=config.model,
            api_key_env=config.api_key_env or "OPENAI_API_KEY",
        ))
    provider.profile_id = config.provider_id
    provider.config_hash = sha256_bytes(canonical_json_bytes({
        "provider_type": config.provider_type,
        "base_url": config.base_url,
        "model": config.model,
        "api_key_env": config.api_key_env,
        "default_max_output_tokens": config.default_max_output_tokens,
        "default_temperature": config.default_temperature,
    }))
    provider.default_max_output_tokens = config.default_max_output_tokens
    provider.default_temperature = config.default_temperature
    return provider


def check_provider_profile(root: Path, provider_id: str, *, connect: bool = False,
                           client: httpx.Client | None = None) -> ProviderCheckResult:
    view = show_provider_profile(root, provider_id)
    settings = ProviderProfileSettings.model_validate({
        key: view[key] for key in ProviderProfileSettings.model_fields if key in view
    })
    if not settings.enabled:
        return ProviderCheckResult(provider_id=provider_id, ready=False, message="Profile is disabled")
    if settings.provider_type == "fake":
        return ProviderCheckResult(provider_id=provider_id, ready=True, message="Explicit FakeProvider profile is configured")
    if settings.api_key_env and not os.getenv(settings.api_key_env) and not _is_loopback(settings.base_url):
        return ProviderCheckResult(provider_id=provider_id, ready=False,
                                   message=f"Missing environment variable {settings.api_key_env}")
    if not connect:
        return ProviderCheckResult(provider_id=provider_id, ready=True,
                                   message=f"Configuration ready; {settings.api_key_env or 'no key'} is available")

    url = f"{settings.base_url}/models"
    headers = {"Accept": "application/json"}
    api_key = os.getenv(settings.api_key_env) if settings.api_key_env else None
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    own_client = client is None
    client = client or httpx.Client(timeout=15.0, follow_redirects=False)
    try:
        response = client.get(url, headers=headers)
        if response.status_code >= 400:
            return ProviderCheckResult(provider_id=provider_id, ready=False,
                                       message=f"Connection failed with HTTP {response.status_code}")
    except httpx.HTTPError as error:
        return ProviderCheckResult(provider_id=provider_id, ready=False,
                                   message=f"Connection failed ({type(error).__name__})")
    finally:
        if own_client:
            client.close()
    return ProviderCheckResult(provider_id=provider_id, ready=True, connected=True,
                               message="Provider model endpoint responded successfully")
