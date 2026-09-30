from __future__ import annotations

import pytest

from kdp_pipeline.workspace.auth import hash_password


@pytest.fixture(scope="session")
def workspace_test_password_hash() -> str:
    return hash_password("correct horse battery staple")


@pytest.fixture(autouse=True)
def configure_test_workspace_auth(monkeypatch, workspace_test_password_hash):
    monkeypatch.setenv("KDP_WORKSPACE_USERNAME", "test-operator")
    monkeypatch.setenv("KDP_WORKSPACE_PASSWORD_HASH", workspace_test_password_hash)
    monkeypatch.setenv("KDP_WORKSPACE_SESSION_SECRET", "test-only-workspace-session-key-which-is-long-enough")
    monkeypatch.setenv("KDP_WORKSPACE_COOKIE_SECURE", "false")
