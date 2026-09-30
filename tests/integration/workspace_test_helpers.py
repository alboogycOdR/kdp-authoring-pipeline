from __future__ import annotations

import os
from http.client import HTTPConnection as _HTTPConnection

from kdp_pipeline.workspace.auth import WorkspaceAuth


def workspace_cookie_header() -> str:
    auth = WorkspaceAuth.from_environment()
    token, _ = auth.issue(remember=False)
    cookie_name = "__Host-KDPWorkspace" if os.environ.get(
        "KDP_WORKSPACE_COOKIE_SECURE", "false").casefold() == "true" else "KDPWorkspace"
    return f"{cookie_name}={token}"


class HTTPConnection(_HTTPConnection):
    """Authenticated client for the existing Workspace route tests."""

    def request(self, method, url, body=None, headers=None, *, encode_chunked=False):
        request_headers = dict(headers or {})
        if not any(key.casefold() == "cookie" for key in request_headers):
            request_headers["Cookie"] = workspace_cookie_header()
        return super().request(method, url, body=body, headers=request_headers,
                               encode_chunked=encode_chunked)
