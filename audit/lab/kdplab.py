"""Shared lab helpers for the KDP Pipeline audit.

Everything here runs against a throw-away root (``tmp_path``) with its own
``.kdp/state.db`` and ``projects/``. No real provider is ever contacted: the
``fake`` provider or ``audit/lab/mock_provider.py`` on 127.0.0.1 is used.
"""

from __future__ import annotations

import asyncio
import http.client
import json
import re
import shutil
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import os

REPO = Path(os.environ.get("KDP_AUDIT_TARGET", Path(__file__).resolve().parents[2])).resolve()

from kdp_pipeline.chapter import ChapterService, accept_chapter  # noqa: E402
from kdp_pipeline.context import ContextManifest  # noqa: E402
from kdp_pipeline.models.planning import PlanningArtifactKind  # noqa: E402
from kdp_pipeline.planning import PlanningService, accept_planning_artifact  # noqa: E402
from kdp_pipeline.providers import FakeProvider  # noqa: E402
from kdp_pipeline.providers.contracts import GenerationResult, UsageMetadata  # noqa: E402
from kdp_pipeline.providers.configuration import add_provider_profile, select_provider_for_project  # noqa: E402
from kdp_pipeline.providers.costs import set_model_pricing, set_project_budget  # noqa: E402
from kdp_pipeline.providers.settings import ProviderProfileSettings  # noqa: E402
from kdp_pipeline.storage.db import init_db  # noqa: E402
from kdp_pipeline.storage.service import (  # noqa: E402
    advance_to_drafting, advance_to_planned, advance_to_validated, create_project, create_title,
)
from kdp_pipeline.workspace.server import create_workspace_server  # noqa: E402

CANARY_KEY = "sk-CANARY-" + "A1b2C3d4E5f6G7h8I9j0"
CANARY_CLOUD = "canary-cloud-secret-" + "not-a-real-credential-0000"
CANARY_NOTE = "KDP-PASSWORD-CANARY-7731 bank IBAN ZA00CANARY000 MFA 424242"


def make_root(tmp: Path) -> Path:
    root = tmp.resolve()
    if not (root / "prompts").is_dir():
        shutil.copytree(REPO / "prompts", root / "prompts")
    (root / "templates").mkdir(exist_ok=True)
    (root / "projects").mkdir(exist_ok=True)
    init_db(root)
    return root


class CaptureProvider(FakeProvider):
    """FakeProvider that records every GenerationRequest and can override text per task prefix."""

    def __init__(self, overrides: dict[str, Any] | None = None, **kw: Any):
        super().__init__(**kw)
        self.requests: list[Any] = []
        self.overrides = overrides or {}

    async def generate(self, request):
        self.requests.append(request)
        for prefix, value in self.overrides.items():
            if request.task_type.startswith(prefix):
                if callable(value):
                    value = value(request)
                if isinstance(value, GenerationResult):
                    return value
                return GenerationResult(provider=self.provider_name, model=self.model_name, text=value,
                                        latency_ms=0, usage=UsageMetadata(input_tokens=10, output_tokens=10))
        return await super().generate(request)


@dataclass
class Book:
    root: Path
    project_id: str
    title_id: str
    ids: dict[str, str] = field(default_factory=dict)


def plan_title(root: Path, provider=None, *, chapters: int = 1, name: str = "Audit Book") -> Book:
    provider = provider or CaptureProvider()
    project = create_project(root, f"{name} project")
    title = create_title(root, project.project_id, name)
    book = Book(root, project.project_id, title.title_id)
    plan = [(PlanningArtifactKind.POSITIONING, None), (PlanningArtifactKind.BOOK_BRIEF, None),
            (PlanningArtifactKind.OUTLINE, None)] + [(PlanningArtifactKind.CHAPTER_CARD, n) for n in range(1, chapters + 1)]
    for kind, number in plan:
        result = asyncio.run(PlanningService.generate(
            root, title_id=title.title_id, artifact_kind=kind,
            context_manifest=ContextManifest(title_id=title.title_id, task_type=f"planning.{kind.value}", inputs=[]),
            provider=provider, chapter_number=number))
        accepted = accept_planning_artifact(root, result.asset.asset_id, reviewer="planner", chapter_number=number)
        book.ids[f"{kind.value}{number or ''}"] = accepted.accepted_asset.asset_id
    advance_to_validated(root, title.title_id)
    advance_to_planned(root, title.title_id)
    advance_to_drafting(root, title.title_id)
    return book


def draft_and_accept(book: Book, provider=None, *, chapter: int = 1, reviewer: str = "editor",
                     conditions: list[str] | None = None):
    provider = provider or CaptureProvider()
    draft = asyncio.run(ChapterService.draft(book.root, title_id=book.title_id, chapter_number=chapter, provider=provider))
    accepted = accept_chapter(book.root, draft.asset.asset_id, chapter_number=chapter, reviewer=reviewer,
                              conditions=conditions)
    book.ids[f"draft{chapter}"] = draft.asset.asset_id
    book.ids[f"accepted{chapter}"] = accepted.accepted_asset.asset_id
    return draft, accepted


def add_fake_priced_profile(root: Path, provider_id: str = "fake-priced", *, project_id: str | None = None,
                            monthly: float | None = None, per_run: float | None = None) -> str:
    add_provider_profile(root, ProviderProfileSettings(provider_id=provider_id, provider_type="fake",
                                                       display_name="Fake priced", model="fake-v1"))
    set_model_pricing(root, provider_id, "fake-v1", input_usd_per_million=1.0, output_usd_per_million=10.0)
    if project_id:
        select_provider_for_project(root, project_id, provider_id)
        if monthly or per_run:
            set_project_budget(root, project_id, monthly_limit_usd=monthly, max_run_estimated_cost_usd=per_run,
                               warning_percent=80, hard_stop=True)
    return provider_id


def add_mock_profile(root: Path, base_url: str, *, provider_id: str = "mock", api_key_env: str | None = "MOCK_API_KEY",
                     project_id: str | None = None, model: str = "mock-model", priced: bool = True,
                     max_output: int = 1200) -> str:
    add_provider_profile(root, ProviderProfileSettings(
        provider_id=provider_id, provider_type="openai-compatible", display_name=f"Mock {provider_id}",
        base_url=base_url, model=model, api_key_env=api_key_env, default_max_output_tokens=max_output,
        read_timeout_seconds=10, connect_timeout_seconds=5, write_timeout_seconds=5, pool_timeout_seconds=5))
    if priced:
        set_model_pricing(root, provider_id, model, input_usd_per_million=1.25, output_usd_per_million=10.0,
                          cached_input_usd_per_million=0.125)
    if project_id:
        select_provider_for_project(root, project_id, provider_id)
    return provider_id


def db(root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(root / ".kdp" / "state.db")
    conn.row_factory = sqlite3.Row
    return conn


def rows(root: Path, sql: str, *args: Any) -> list[dict]:
    with db(root) as conn:
        return [dict(r) for r in conn.execute(sql, args)]


class Workspace:
    """Run the real Workspace server on an ephemeral loopback port in a thread."""

    def __init__(self, root: Path, port: int = 0):
        self.root = root
        self.server = create_workspace_server(root, port=port)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "Workspace":
        self.thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.server.shutdown()
        self.server.server_close()

    @property
    def host(self) -> str:
        return f"127.0.0.1:{self.port}"

    def request(self, method: str, path: str, body: bytes | str | None = None, headers: dict | None = None,
                *, connect_port: int | None = None, timeout: float = 30) -> tuple[int, dict, str]:
        conn = http.client.HTTPConnection("127.0.0.1", connect_port or self.port, timeout=timeout)
        hdrs = {"Host": self.host}
        hdrs.update(headers or {})
        if isinstance(body, str):
            body = body.encode("utf-8")
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for key, value in hdrs.items():
            if value is not None:
                conn.putheader(key, value)
        if body is not None and "Content-Length" not in hdrs:
            conn.putheader("Content-Length", str(len(body)))
        conn.endheaders(body)
        response = conn.getresponse()
        data = response.read().decode("utf-8", "replace")
        headers_out = {k: v for k, v in response.getheaders()}
        conn.close()
        return response.status, headers_out, data

    def get(self, path: str, **kw: Any) -> tuple[int, dict, str]:
        return self.request("GET", path, **kw)

    def csrf(self, path: str = "/") -> str:
        _, _, page = self.get(path)
        match = re.search(r'name="csrf_token" value="([^"]+)"', page)
        assert match, "no csrf token on page"
        return match.group(1)

    def post(self, path: str, fields: dict[str, str], headers: dict | None = None, **kw: Any) -> tuple[int, dict, str]:
        # Default to a same-origin Origin, as a real browser form post does; callers override to
        # simulate cross-site or legacy (no-Origin) clients. `Origin: None` drops the header.
        hdrs = {"Content-Type": "application/x-www-form-urlencoded", "Origin": f"http://{self.host}"}
        hdrs.update(headers or {})
        if hdrs.get("Origin") is None:
            hdrs.pop("Origin", None)
        return self.request("POST", path, urlencode(fields), hdrs, **kw)

    def review_hash(self, kind: str, identifier: str) -> str:
        _, _, page = self.get(f"/reviews/{kind}/{identifier}")
        match = re.search(r'name="review_hash" value="([^"]+)"', page)
        assert match, f"no review hash on /reviews/{kind}/{identifier}"
        return match.group(1)


def jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
