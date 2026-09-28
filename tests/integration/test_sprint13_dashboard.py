from __future__ import annotations

from pathlib import Path

import pytest

from kdp_pipeline.providers.configuration import add_provider_profile, select_provider_for_project
from kdp_pipeline.providers.costs import set_project_budget
from kdp_pipeline.providers.settings import ProviderProfileSettings
from kdp_pipeline.storage.service import create_project, create_title
from kdp_pipeline.verification import add_verification_flag
from kdp_pipeline.workspace import generate_dashboard


def test_static_dashboard_shows_workflow_summaries_without_secrets(tmp_path, monkeypatch):
    project = create_project(tmp_path, "Dashboard project <script>")
    title = create_title(tmp_path, project.project_id, "Dashboard title & review")
    add_provider_profile(tmp_path, ProviderProfileSettings(provider_id="dashboard-profile",
        provider_type="openai-compatible", display_name="Dashboard provider", model="test-model",
        base_url="https://api.openai.com/v1", api_key_env="DASHBOARD_OPENAI_KEY"))
    select_provider_for_project(tmp_path, project.project_id, "dashboard-profile")
    set_project_budget(tmp_path, project.project_id, monthly_limit_usd=25.0,
        max_run_estimated_cost_usd=5.0, warning_percent=80, hard_stop=True)
    monkeypatch.setenv("DASHBOARD_OPENAI_KEY", "sk-dashboard-secret-must-never-appear")
    flag = add_verification_flag(tmp_path, title_id=title.title_id, kind="source_claim",
        locator="chapter-001:paragraph-1", exact_text="A claim requiring source review.", reviewer="editor")

    result = generate_dashboard(tmp_path)
    output = result.output_path.read_text(encoding="utf-8")
    assert result.project_count == 1
    assert result.title_count == 1
    assert "Dashboard project &lt;script&gt;" in output
    assert "Dashboard title &amp; review" in output
    assert "Provider readiness" in output and "Dashboard provider" in output
    assert "Monthly limit: $25.0" in output
    assert "Concept and planning" in output
    assert "Chapters" in output and "Editorial and canon" in output
    assert "Verification blockers" in output and "source_claim" in output
    assert flag.verification_id not in output
    assert "Builds" in output and "Release candidates" in output and "Human review queue" in output
    assert "read-only" in output
    assert "sk-dashboard-secret-must-never-appear" not in output
    assert "DASHBOARD_OPENAI_KEY" not in output
    assert "api_key_env" not in output
    assert "<script>" not in output


def test_dashboard_without_database_is_read_only_and_does_not_create_state(tmp_path):
    with pytest.raises(FileNotFoundError):
        generate_dashboard(tmp_path)
    assert not (tmp_path / ".kdp").exists()
