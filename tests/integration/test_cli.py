import json
from pathlib import Path

from typer.testing import CliRunner

from kdp_pipeline.cli.app import app


runner = CliRunner()


def test_cli_create_status_audit_and_jobs(tmp_path: Path):
    result = runner.invoke(app, ["init-project", "CLI Project", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    project_id = result.stdout.strip()

    result = runner.invoke(app, ["new-title", project_id, "CLI Title", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    title_id = result.stdout.strip()

    result = runner.invoke(app, ["status", title_id, "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["status"] == "IDEA"

    result = runner.invoke(app, ["jobs", title_id, "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert result.stdout == ""

    result = runner.invoke(app, ["audit", title_id, "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert '"action": "title.create"' in result.stdout


def test_cli_errors_are_user_facing(tmp_path: Path):
    result = runner.invoke(app, ["new-title", "PRJ-missing", "Title", "--root", str(tmp_path)])
    assert result.exit_code == 2
    assert "Error: Unknown project" in result.output

    result = runner.invoke(app, ["status", "BK-missing", "--root", str(tmp_path)])
    assert result.exit_code == 1
    assert "Error: Unknown title" in result.output
