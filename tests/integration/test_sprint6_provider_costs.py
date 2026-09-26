import asyncio
import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from typer.testing import CliRunner

from kdp_pipeline.context import ContextManifest
from kdp_pipeline.cli.app import app
from kdp_pipeline.core.hashing import sha256_text
from kdp_pipeline.generation.service import GenerationService, GenerationServiceError
from kdp_pipeline.inspection import doctor, inspect_title
from kdp_pipeline.providers import FakeProvider, GenerationResult, RenderedPrompt, UsageMetadata
from kdp_pipeline.providers.configuration import (
    add_provider_profile, check_provider_profile, list_provider_profiles,
    resolve_project_provider, select_provider_for_project, set_provider_enabled,
)
from kdp_pipeline.providers.costs import set_model_pricing, set_project_budget
from kdp_pipeline.providers.settings import ProviderProfileSettings
from kdp_pipeline.storage.db import BudgetReservationRow, ProviderProfileRow, UsageEventRow
from kdp_pipeline.storage.service import create_project, create_title, session_scope


def profile(provider_id="pilot", model="fake-v1", **overrides):
    values = dict(provider_id=provider_id, provider_type="fake", display_name="Pilot fake", model=model)
    values.update(overrides)
    return ProviderProfileSettings(**values)


def test_provider_profiles_selection_toggle_and_no_implicit_fallback(tmp_path):
    project = create_project(tmp_path, "Profile project")
    add_provider_profile(tmp_path, profile())
    assert list_provider_profiles(tmp_path)[0]["api_key_configured"] is False
    with pytest.raises(ValueError, match="No provider is selected"):
        resolve_project_provider(tmp_path, project.project_id)
    select_provider_for_project(tmp_path, project.project_id, "pilot")
    assert resolve_project_provider(tmp_path, project.project_id).provider_name == "fake"
    assert set_provider_enabled(tmp_path, "pilot", False)["enabled"] is False
    with pytest.raises(ValueError, match="disabled"):
        resolve_project_provider(tmp_path, project.project_id)


def test_generation_without_project_selection_fails_without_fake_fallback(tmp_path):
    project = create_project(tmp_path, "No-selection project")
    title = create_title(tmp_path, project.project_id, "No-selection title")
    with pytest.raises(ValueError, match="No provider is selected"):
        run_generation(tmp_path, title.title_id)


def test_provider_cli_add_and_offline_check_missing_variable_are_safe(tmp_path, monkeypatch):
    runner = CliRunner()
    missing_name = "KDP_SPRINT6_MISSING_KEY"
    monkeypatch.delenv(missing_name, raising=False)
    added = runner.invoke(app, ["providers", "add-openai-compatible", "remote", "Remote", "model-a",
                                "--base-url", "https://provider.example/v1", "--api-key-env", missing_name,
                                "--root", str(tmp_path)])
    assert added.exit_code == 0, added.output
    checked = runner.invoke(app, ["providers", "check", "remote", "--root", str(tmp_path)])
    assert checked.exit_code == 1
    assert f"Missing environment variable {missing_name}" in checked.output
    assert "Authorization" not in checked.output
def test_api_key_env_name_only_and_checks_never_reveal_secret(tmp_path, monkeypatch):
    secret = "sk-test-secret-value-never-print"
    monkeypatch.setenv("PILOT_SECRET", secret)
    project = create_project(tmp_path, "Secret project")
    settings = ProviderProfileSettings(
        provider_id="private", provider_type="openai-compatible", display_name="Private",
        model="model-a", base_url="https://provider.example/v1", api_key_env="PILOT_SECRET",
    )
    view = add_provider_profile(tmp_path, settings)
    assert view["api_key_env"] == "PILOT_SECRET"
    assert view["api_key_configured"] is True
    assert secret not in json.dumps(view)
    with session_scope(tmp_path) as session:
        assert secret not in str(session.get(ProviderProfileRow, "private").__dict__)
    offline_result = check_provider_profile(tmp_path, "private", client=object())
    assert offline_result.ready and not offline_result.connected
    assert secret not in offline_result.message
    select_provider_for_project(tmp_path, project.project_id, "private")
    report = inspect_title(tmp_path, create_title(tmp_path, project.project_id, "Private title").title_id)
    assert secret not in json.dumps(report)


def test_provider_check_connect_is_explicit_and_mocked(tmp_path, monkeypatch):
    monkeypatch.setenv("PILOT_KEY", "safe-test-secret-value")
    add_provider_profile(tmp_path, ProviderProfileSettings(
        provider_id="remote", provider_type="openai-compatible", display_name="Remote",
        model="model-a", base_url="https://provider.example/v1", api_key_env="PILOT_KEY",
    ))
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"data": []}))
    with httpx.Client(transport=transport) as client:
        result = check_provider_profile(tmp_path, "remote", connect=True, client=client)
    assert result.ready and result.connected
    assert "safe-test-secret-value" not in result.message


class UsageFake(FakeProvider):
    def __init__(self):
        super().__init__()
        self.calls = 0

    async def generate(self, request):
        self.calls += 1
        return GenerationResult(provider=self.provider_name, model=self.model_name, text="pilot result",
                                usage=UsageMetadata(input_tokens=12, output_tokens=7, total_tokens=19))


def run_generation(root: Path, title_id: str):
    prompt_text = "generate"
    return asyncio.run(GenerationService.generate(
        root, title_id=title_id, task_type="budget-check",
        rendered_prompt=RenderedPrompt(template_id="test/prompt", template_version="1.0",
                                       rendered_text=prompt_text, rendered_sha256=sha256_text(prompt_text)),
        context_manifest=ContextManifest(title_id=title_id, task_type="test", inputs=[]),
        provider=None, system_instructions="test", max_output_tokens=25, temperature=0,
    ))


def install_usage_fake(monkeypatch):
    provider = UsageFake()
    provider.profile_id = "pilot"
    provider.config_hash = "test-config"
    monkeypatch.setattr("kdp_pipeline.providers.configuration.resolve_project_provider",
                        lambda root, project_id: provider)
    return provider


def test_usage_persists_and_cost_stays_unknown_without_pricing_in_soft_budget(tmp_path, monkeypatch):
    provider = install_usage_fake(monkeypatch)
    project = create_project(tmp_path, "Usage project")
    title = create_title(tmp_path, project.project_id, "Usage title")
    add_provider_profile(tmp_path, profile())
    select_provider_for_project(tmp_path, project.project_id, "pilot")
    set_project_budget(tmp_path, project.project_id, monthly_limit_usd=10,
                       max_run_estimated_cost_usd=None, warning_percent=75, hard_stop=False)
    run_generation(tmp_path, title.title_id)
    assert provider.calls == 1
    with session_scope(tmp_path) as session:
        event = session.scalar(select(UsageEventRow).where(UsageEventRow.title_id == title.title_id))
        reservation = session.scalar(select(BudgetReservationRow).where(BudgetReservationRow.project_id == project.project_id))
        assert (event.input_tokens, event.output_tokens, event.total_tokens) == (12, 7, 19)
        assert event.estimated_cost is None and event.source == "unknown"
        assert reservation.status == "unpriced"
    report = inspect_title(tmp_path, title.title_id)
    assert report["usage"]["unknown_cost_events"] == 1
    assert "unknown cost" in report["budget"]["warning"]
    assert any(event["action"] == "generation.usage.recorded" for event in report["audit"])


def test_hard_budget_without_pricing_blocks_before_provider(tmp_path, monkeypatch):
    provider = install_usage_fake(monkeypatch)
    project = create_project(tmp_path, "Hard budget project")
    title = create_title(tmp_path, project.project_id, "Hard budget title")
    add_provider_profile(tmp_path, profile())
    select_provider_for_project(tmp_path, project.project_id, "pilot")
    set_project_budget(tmp_path, project.project_id, monthly_limit_usd=10,
                       max_run_estimated_cost_usd=None, warning_percent=80, hard_stop=True)
    with pytest.raises(GenerationServiceError, match="requires pricing"):
        run_generation(tmp_path, title.title_id)
    assert provider.calls == 0
    with session_scope(tmp_path) as session:
        assert session.scalar(select(func.count(UsageEventRow.usage_event_id))) == 0
        assert session.scalar(select(func.count(BudgetReservationRow.reservation_id))) == 0


def test_configured_pricing_estimates_cost_and_hard_budget_allows_run(tmp_path, monkeypatch):
    provider = install_usage_fake(monkeypatch)
    project = create_project(tmp_path, "Priced project")
    title = create_title(tmp_path, project.project_id, "Priced title")
    add_provider_profile(tmp_path, profile())
    select_provider_for_project(tmp_path, project.project_id, "pilot")
    set_model_pricing(tmp_path, "pilot", "fake-v1", input_usd_per_million=1,
                      output_usd_per_million=2)
    set_project_budget(tmp_path, project.project_id, monthly_limit_usd=10,
                       max_run_estimated_cost_usd=1, warning_percent=80, hard_stop=True)
    run_generation(tmp_path, title.title_id)
    assert provider.calls == 1
    with session_scope(tmp_path) as session:
        event = session.scalar(select(UsageEventRow).where(UsageEventRow.title_id == title.title_id))
        assert event.estimated_cost is not None and event.estimated_cost > 0
        assert event.source == "estimated"
        details = json.loads(event.cost_details_json)
        assert details["basis"] == "configured_model_rates"
        assert details["input_usd_per_million"] == 1
        assert details["output_usd_per_million"] == 2


def test_doctor_is_read_only_and_reports_provider_state(tmp_path, monkeypatch):
    project = create_project(tmp_path, "Doctor project")
    add_provider_profile(tmp_path, profile())
    before = (tmp_path / ".kdp" / "state.db").stat().st_mtime_ns
    checks = doctor(tmp_path)
    after = (tmp_path / ".kdp" / "state.db").stat().st_mtime_ns
    assert before == after
    assert any(row["check"] == "provider:pilot" for row in checks)
    assert not any("api key value" in row["message"].lower() for row in checks)
