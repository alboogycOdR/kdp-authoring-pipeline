from __future__ import annotations

from pathlib import Path
from threading import Thread
from workspace_test_helpers import HTTPConnection

from kdp_pipeline.storage.service import create_project, create_title
from kdp_pipeline.providers.configuration import add_provider_profile, select_provider_for_project
from kdp_pipeline.providers.settings import ProviderProfileSettings
from kdp_pipeline.workspace.inspection import inspect_workspace
from kdp_pipeline.workspace.render import _assets_needing_approval, render_workspace
from kdp_pipeline.workspace.server import create_workspace_server


def _workspace(tmp_path: Path) -> tuple[str, str]:
    project = create_project(tmp_path, "Workspace project")
    title = create_title(tmp_path, project.project_id, "A test title")
    return project.project_id, title.title_id


def test_workspace_renders_attention_before_project_and_title_directories(tmp_path: Path):
    _workspace(tmp_path)
    snapshot = inspect_workspace(tmp_path)
    page = render_workspace(snapshot)

    positions = [page.index(label) for label in (
        "Needs Review", "Needs Approval", "Needs Verification", "Blocked", "Ready",
        "Recent Activity", "Projects", "Titles",
    )]
    assert positions == sorted(positions)
    assert "KDP Pipeline Workspace" in page
    assert "Dashboard" not in page
    assert "OPENAI_API_KEY" not in page
    assert "A test title" in page


def test_workspace_omits_accepted_assets_from_needs_approval_queue():
    report = {"assets": [
        {"asset_id": "DRAFT", "asset_type": "chapter.draft", "approval_status": "experimental", "source_ref": None},
        {"asset_id": "REVISION", "asset_type": "chapter.revision", "approval_status": "experimental", "source_ref": "DRAFT"},
        {"asset_id": "ACCEPTED", "asset_type": "chapter.accepted", "approval_status": "accepted", "source_ref": "REVISION"},
    ]}

    assert _assets_needing_approval(report) == []


def test_workspace_escapes_database_names(tmp_path: Path):
    project = create_project(tmp_path, '<img src=x onerror="alert(1)">')
    create_title(tmp_path, project.project_id, "Safe title")
    page = render_workspace(inspect_workspace(tmp_path))

    assert '<img src=x onerror="alert(1)">' not in page
    assert "&lt;img" in page


def test_workspace_provider_view_never_displays_secret_or_environment_variable(tmp_path: Path, monkeypatch):
    project = create_project(tmp_path, "Provider workspace")
    create_title(tmp_path, project.project_id, "Provider title")
    monkeypatch.setenv("WORKSPACE_TEST_KEY_NAME", "workspace-test-secret-value")
    add_provider_profile(tmp_path, ProviderProfileSettings(
        provider_id="workspace-provider", provider_type="openai-compatible",
        display_name="Workspace provider", model="gpt-test", api_key_env="WORKSPACE_TEST_KEY_NAME",
    ))
    select_provider_for_project(tmp_path, project.project_id, "workspace-provider")
    page = render_workspace(inspect_workspace(tmp_path))

    assert "Workspace provider" in page
    assert "configuration ready · not connected" in page
    assert "WORKSPACE_TEST_KEY_NAME" not in page
    assert "workspace-test-secret-value" not in page


def test_workspace_server_is_loopback_read_only_and_serves_packaged_assets(tmp_path: Path):
    project_id, title_id = _workspace(tmp_path)
    db_path = tmp_path / ".kdp" / "state.db"
    before = db_path.read_bytes()
    server = create_workspace_server(tmp_path, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
    try:
        assert server.server_address[0] == "127.0.0.1"

        connection.request("GET", "/")
        response = connection.getresponse()
        home = response.read().decode("utf-8")
        assert response.status == 200
        assert "Workspace project" in home
        assert "Needs Verification" in home
        assert "Content-Security-Policy" in response.headers

        connection.request("GET", f"/projects/{project_id}")
        response = connection.getresponse()
        assert response.status == 200
        assert "A test title" in response.read().decode("utf-8")

        connection.request("GET", f"/titles/{title_id}")
        response = connection.getresponse()
        title_page = response.read().decode("utf-8")
        assert response.status == 200
        assert "What do you need to do?" in title_page
        assert "Authoring journey" in title_page
        assert "Checks and rights" in title_page
        assert "stage-tracker" in title_page
        assert "Scripture" not in title_page

        connection.request("GET", f"/titles/{title_id}?view=all")
        response = connection.getresponse()
        title_page = response.read().decode("utf-8")
        assert "Provider and budget" in title_page
        assert "Verification and rights" not in title_page
        assert "Verification checks" not in title_page
        assert "Scan accepted manuscript" in title_page
        assert "Scan Scripture placeholders" not in title_page

        connection.request("GET", "/static/workspace.css")
        response = connection.getresponse()
        css = response.read().decode("utf-8")
        assert response.status == 200
        assert 'body[data-theme="light"]' in css
        assert 'body[data-theme="dark"]' in css
        assert 'body[data-theme="brand"]' in css
        assert "--accent: #000000" in css
        assert "--brand-orange: #ff940b" in css
        assert "--action-bg: #ff940b" in css
        assert "--action-ink: #000000" in css
        assert "--blocked:" in css and "--ready:" in css

        connection.request("POST", "/", headers={"Sec-Fetch-Site": "same-origin"})
        response = connection.getresponse()
        assert response.status == 405
        assert response.headers.get("Allow") == "GET, HEAD"

        connection.putrequest("GET", "/", skip_host=True)
        connection.putheader("Host", "attacker.example")
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 421
        response.read()
    finally:
        connection.close()
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()

    assert db_path.read_bytes() == before


def test_workspace_without_database_explains_cli_setup(tmp_path: Path):
    server = create_workspace_server(tmp_path, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
    try:
        connection.request("GET", "/")
        response = connection.getresponse()
        page = response.read().decode("utf-8")
        assert response.status == 200
        assert "The local workspace database is not available yet" in page
        assert "kdp init-db" in page
        assert not (tmp_path / ".kdp").exists()
    finally:
        connection.close()
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
