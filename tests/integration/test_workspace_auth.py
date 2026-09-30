from __future__ import annotations

import re
from pathlib import Path
from threading import Thread

from workspace_test_helpers import HTTPConnection
from kdp_pipeline.workspace.auth import WorkspaceAuth, hash_password, verify_password
from kdp_pipeline.workspace.server import create_workspace_server


def _serve(server):
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def _request(server, method, path, *, body=None, headers=None):
    port = server.server_address[1]
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    values = {"Host": f"127.0.0.1:{port}"}
    values.update(headers or {})
    if body is not None:
        values.setdefault("Content-Type", "application/x-www-form-urlencoded")
        values.setdefault("Origin", f"http://127.0.0.1:{port}")
    connection.request(method, path, body=body, headers=values)
    response = connection.getresponse()
    result = response.status, dict(response.getheaders()), response.read().decode("utf-8", "replace")
    connection.close()
    return result


def test_password_hash_is_slow_salted_and_verifies():
    stored = hash_password("a very good test password")
    assert stored.startswith("scrypt-v1$")
    assert stored != hash_password("a very good test password")
    assert verify_password("a very good test password", stored)
    assert not verify_password("wrong password", stored)


def test_workspace_requires_login_and_remember_me_session_can_logout(tmp_path: Path):
    server = create_workspace_server(tmp_path, port=0)
    thread = _serve(server)
    port = server.server_address[1]
    origin = f"http://127.0.0.1:{port}"
    try:
        status, _, _ = _request(server, "GET", "/titles/PRIVATE", headers={"Cookie": ""})
        assert status == 303
        status, _, login = _request(server, "GET", "/login?next=%2Ftitles%2FPRIVATE", headers={"Cookie": ""})
        assert status == 200
        assert "Welcome back" in login
        assert "Remember me on this device for 30 days" in login
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', login).group(1)

        from urllib.parse import urlencode
        status, _, rejected = _request(server, "POST", "/login", body=urlencode({
            "csrf_token": csrf, "username": "test-operator", "password": "wrong password",
            "remember_me": "yes", "next": "/titles/PRIVATE",
        }), headers={"Cookie": "", "Origin": origin})
        assert status == 401
        assert "Username or password was not recognized." in rejected
        assert "wrong password" not in rejected

        status, headers, _ = _request(server, "POST", "/login", body=urlencode({
            "csrf_token": csrf, "username": "test-operator", "password": "correct horse battery staple",
            "remember_me": "yes", "next": "/titles/PRIVATE",
        }), headers={"Cookie": "", "Origin": origin})
        assert status == 303
        assert headers["Location"] == "/titles/PRIVATE"
        set_cookie = headers["Set-Cookie"]
        assert "HttpOnly" in set_cookie and "SameSite=Strict" in set_cookie
        assert "Max-Age=2592000" in set_cookie
        cookie = set_cookie.split(";", 1)[0]

        status, _, _ = _request(server, "GET", "/", headers={"Cookie": cookie})
        assert status == 200
        status, _, _ = _request(server, "GET", "/", headers={"Cookie": cookie[:-1] + "x"})
        assert status == 303

        csrf_page_status, _, workspace = _request(server, "GET", "/", headers={"Cookie": cookie})
        assert csrf_page_status == 200
        csrf = re.search(r'action="/logout"[^>]*>.*?name="csrf_token" value="([^"]+)"',
                         workspace, re.DOTALL).group(1)
        status, headers, _ = _request(server, "POST", "/logout", body=urlencode({"csrf_token": csrf}),
                                      headers={"Cookie": cookie, "Origin": origin})
        assert status == 303
        assert "Max-Age=0" in headers["Set-Cookie"]
        status, _, _ = _request(server, "GET", "/", headers={"Cookie": ""})
        assert status == 303
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def test_secure_cookie_and_empty_or_bad_credentials_fail_closed(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KDP_WORKSPACE_COOKIE_SECURE", "true")
    server = create_workspace_server(tmp_path, port=0)
    thread = _serve(server)
    try:
        status, _, login = _request(server, "GET", "/login", headers={"Cookie": ""})
        assert status == 200
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', login).group(1)
        from urllib.parse import urlencode
        status, headers, _ = _request(server, "POST", "/login", body=urlencode({
            "csrf_token": csrf, "username": "test-operator", "password": "correct horse battery staple",
            "remember_me": "yes", "next": "/",
        }), headers={"Cookie": ""})
        assert status == 303
        assert headers["Set-Cookie"].startswith("__Host-KDPWorkspace=")
        assert "; Secure" in headers["Set-Cookie"]
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()

    monkeypatch.delenv("KDP_WORKSPACE_USERNAME")
    monkeypatch.delenv("KDP_WORKSPACE_PASSWORD_HASH")
    missing = create_workspace_server(tmp_path / "unconfigured", port=0)
    thread = _serve(missing)
    try:
        status, _, page = _request(missing, "GET", "/")
        assert status == 503
        assert "Workspace access is not configured" in page
    finally:
        missing.shutdown()
        thread.join(timeout=3)
        missing.server_close()


def test_login_rate_limit_and_signed_session_expiration(tmp_path: Path):
    auth = WorkspaceAuth.from_environment()
    token, duration = auth.issue(remember=False, now=1000)
    assert duration == 12 * 60 * 60
    assert auth.validate(token, now=1001) == "test-operator"
    assert auth.validate(token, now=1000 + duration) is None

    server = create_workspace_server(tmp_path, port=0)
    thread = _serve(server)
    try:
        from urllib.parse import urlencode
        status, _, login = _request(server, "GET", "/login", headers={"Cookie": ""})
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', login).group(1)
        for attempt in range(5):
            status, _, _ = _request(server, "POST", "/login", body=urlencode({
                "csrf_token": csrf, "username": "test-operator", "password": "incorrect", "next": "/",
            }), headers={"Cookie": ""})
            assert status == 401, attempt
        status, _, message = _request(server, "POST", "/login", body=urlencode({
            "csrf_token": csrf, "username": "test-operator", "password": "incorrect", "next": "/",
        }), headers={"Cookie": ""})
        assert status == 429
        assert "Wait 15 minutes" in message
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def test_configured_session_secret_persists_and_password_rotation_invalidates_sessions(monkeypatch):
    auth = WorkspaceAuth.from_environment()
    token, _ = auth.issue(remember=True, now=1000)
    reloaded = WorkspaceAuth.from_environment()
    assert reloaded.validate(token, now=1001) == "test-operator"

    monkeypatch.setenv("KDP_WORKSPACE_PASSWORD_HASH", hash_password("a different test passphrase"))
    rotated = WorkspaceAuth.from_environment()
    assert rotated.validate(token, now=1001) is None
