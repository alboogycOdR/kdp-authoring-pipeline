from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path
from threading import Thread
from urllib.parse import urlencode
from workspace_test_helpers import HTTPConnection

import pytest

from kdp_pipeline.storage.service import create_project, create_title
from kdp_pipeline.workspace.server import create_workspace_server


def _request(server, method: str, path: str, *, body: dict[str, str] | None = None,
             headers: dict[str, str] | None = None):
    port = server.server_address[1]
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    values = {"Host": f"127.0.0.1:{port}"}
    values.update(headers or {})
    encoded = urlencode(body) if body is not None else None
    if body is not None:
        values.setdefault("Content-Type", "application/x-www-form-urlencoded")
        values.setdefault("Content-Length", str(len(encoded.encode("utf-8"))))
    connection.request(method, path, body=encoded, headers=values)
    response = connection.getresponse()
    result = response.status, dict(response.getheaders()), response.read().decode("utf-8", "replace")
    connection.close()
    return result


def _serve(server):
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def test_configured_proxy_identity_is_required_and_overrides_typed_actor(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KDP_WORKSPACE_OPERATOR_HEADER", "X-KDP-Operator")
    project = create_project(tmp_path, "Identity test")
    title = create_title(tmp_path, project.project_id, "Identity test title")
    server = create_workspace_server(tmp_path, port=0)
    thread = _serve(server)
    try:
        port = server.server_address[1]
        _, _, page = _request(server, "GET", f"/titles/{title.title_id}")
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page)
        assert csrf
        form = {"csrf_token": csrf.group(1), "operator": "forged-name", "kind": "source_claim",
                "locator": "chapter-001:paragraph-1", "exact_text": "A claim for review"}
        origin = f"http://127.0.0.1:{port}"
        status, _, _ = _request(server, "POST", f"/titles/{title.title_id}/actions/add-flag",
                                body=form, headers={"Origin": origin})
        assert status == 401

        status, _, _ = _request(server, "POST", f"/titles/{title.title_id}/actions/add-flag",
                                body=form, headers={"Origin": origin, "X-KDP-Operator": "owner@example.test"})
        assert status == 303
        with sqlite3.connect(tmp_path / ".kdp" / "state.db") as connection:
            reviewer = connection.execute("select reviewer from verification_items").fetchone()[0]
            actor = connection.execute(
                "select actor_id from audit_events where action='verification.flag.created'").fetchone()[0]
        assert reviewer == actor == "owner@example.test"
        assert reviewer != form["operator"]
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def test_workspace_limits_idle_connection_timeout_and_logs_only_url_path(tmp_path: Path, caplog):
    server = create_workspace_server(tmp_path, port=0)
    assert server.RequestHandlerClass.timeout == 30
    thread = _serve(server)
    caplog.set_level(logging.INFO, logger="kdp_pipeline.workspace.access")
    try:
        status, _, _ = _request(server, "GET", "/help?search=private-search-term")
        assert status == 200
        records = [record.getMessage() for record in caplog.records
                   if record.name == "kdp_pipeline.workspace.access"]
        assert any("GET /help 200" in record for record in records)
        assert all("private-search-term" not in record for record in records)
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def test_workspace_rejects_cross_site_fetch_even_if_proxy_normalizes_origin(tmp_path: Path):
    server = create_workspace_server(tmp_path, port=0)
    thread = _serve(server)
    try:
        port = server.server_address[1]
        status, _, _ = _request(server, "POST", "/", body={}, headers={
            "Origin": f"http://127.0.0.1:{port}", "Sec-Fetch-Site": "cross-site",
        })
        assert status == 403
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def test_unexpected_workspace_error_returns_safe_service_unavailable(tmp_path: Path, monkeypatch, caplog):
    def raise_locked(_root):
        raise sqlite3.OperationalError("database is locked; secret form content")

    monkeypatch.setattr("kdp_pipeline.workspace.server.inspect_workspace", raise_locked)
    server = create_workspace_server(tmp_path, port=0)
    thread = _serve(server)
    caplog.set_level(logging.ERROR, logger="kdp_pipeline.workspace.access")
    try:
        status, headers, body = _request(server, "GET", "/")
        assert status == 503
        assert "Check the current records before trying again." in body
        assert "database is locked" not in body
        assert "secret form content" not in body
        assert headers.get("X-Content-Type-Options") == "nosniff"
        assert "database is locked" not in caplog.text
        assert "secret form content" not in caplog.text
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def test_invalid_identity_header_configuration_fails_closed(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KDP_WORKSPACE_OPERATOR_HEADER", "bad header name")
    with pytest.raises(ValueError, match="valid HTTP header name"):
        create_workspace_server(tmp_path, port=0)
