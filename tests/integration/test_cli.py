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


def test_cli_inspection_and_read_only_doctor(tmp_path: Path):
    result = runner.invoke(app, ["doctor", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "FAIL: sqlite" in result.output
    assert not (tmp_path / ".kdp").exists()

    result = runner.invoke(app, ["init-project", "Inspect Project", "--root", str(tmp_path)])
    project_id = result.stdout.strip()
    result = runner.invoke(app, ["new-title", project_id, "Inspect Title", "--root", str(tmp_path)])
    title_id = result.stdout.strip()
    db_before = (tmp_path / ".kdp" / "state.db").read_bytes()
    result = runner.invoke(app, ["inspect", "title", title_id, "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["title"]["status"] == "IDEA"
    assert (tmp_path / ".kdp" / "state.db").read_bytes() == db_before


def test_verification_cli_groups_and_empty_inspection(tmp_path: Path):
    project_id = runner.invoke(app, ["init-project", "Verification CLI", "--root", str(tmp_path)]).stdout.strip()
    title_id = runner.invoke(app, ["new-title", project_id, "Verification Title", "--root", str(tmp_path)]).stdout.strip()
    help_result = runner.invoke(app, ["verify", "--help"])
    assert help_result.exit_code == 0
    assert "scan-scripture" in help_result.stdout
    assert "add-flag" in help_result.stdout
    rights_help = runner.invoke(app, ["rights", "--help"])
    assert rights_help.exit_code == 0
    assert "add" in rights_help.stdout
    inspection = runner.invoke(app, ["inspect", "verification", title_id, "--root", str(tmp_path)])
    assert inspection.exit_code == 0
    assert json.loads(inspection.stdout)["release_blockers"] == []
