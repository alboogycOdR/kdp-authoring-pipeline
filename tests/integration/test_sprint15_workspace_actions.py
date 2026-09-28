from __future__ import annotations

import asyncio
import re
import shutil
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread
from urllib.parse import urlencode

from kdp_pipeline.chapter import ChapterService, accept_chapter
from kdp_pipeline.context import ContextManifest
from kdp_pipeline.inspection import inspect_title
from kdp_pipeline.models.planning import PlanningArtifactKind
from kdp_pipeline.planning import PlanningService, accept_planning_artifact
from kdp_pipeline.providers import FakeProvider
from kdp_pipeline.providers.contracts import GenerationResult
from kdp_pipeline.storage.files import sha256_file
from kdp_pipeline.storage.service import (
    advance_to_drafting, advance_to_planned, advance_to_validated, create_project, create_title,
)
from kdp_pipeline.workspace.server import create_workspace_server


class LocalFixtureProvider(FakeProvider):
    async def generate(self, request):
        if request.task_type == "chapter.draft.1":
            return GenerationResult(provider=self.provider_name, model=self.model_name,
                text="# Chapter One\n\nReflection: [SCRIPTURE NEEDED]\n", latency_ms=0)
        return await super().generate(request)


def _accepted_title(root: Path) -> tuple[str, str]:
    shutil.copytree(Path("prompts"), root / "prompts")
    project = create_project(root, "Workspace action fixture")
    title = create_title(root, project.project_id, "A local book")
    provider = LocalFixtureProvider()
    for kind, number in ((PlanningArtifactKind.POSITIONING, None),
                         (PlanningArtifactKind.BOOK_BRIEF, None),
                         (PlanningArtifactKind.OUTLINE, None),
                         (PlanningArtifactKind.CHAPTER_CARD, 1)):
        planned = asyncio.run(PlanningService.generate(root, title_id=title.title_id,
            artifact_kind=kind, context_manifest=ContextManifest(title_id=title.title_id,
            task_type=f"planning.{kind.value}", inputs=[]), provider=provider, chapter_number=number))
        accept_planning_artifact(root, planned.asset.asset_id, reviewer="planner", chapter_number=number)
    advance_to_validated(root, title.title_id)
    advance_to_planned(root, title.title_id)
    advance_to_drafting(root, title.title_id)
    draft = asyncio.run(ChapterService.draft(root, title_id=title.title_id,
        chapter_number=1, provider=provider))
    accepted = accept_chapter(root, draft.asset.asset_id, chapter_number=1, reviewer="editor")
    return title.title_id, accepted.accepted_asset.asset_id


def _post(connection: HTTPConnection, title_id: str, action: str, fields: dict[str, str],
          *, origin: str | None = None):
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if origin:
        headers["Origin"] = origin
    connection.request("POST", f"/titles/{title_id}/actions/{action}",
                       body=urlencode(fields), headers=headers)
    response = connection.getresponse()
    body = response.read().decode("utf-8")
    return response, body


def test_workspace_actions_require_token_and_reject_cross_origin(tmp_path: Path):
    title_id, _ = _accepted_title(tmp_path)
    server = create_workspace_server(tmp_path, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    try:
        response, _ = _post(connection, title_id, "scan-scripture", {})
        assert response.status == 403
        assert inspect_title(tmp_path, title_id)["verification"]["items"] == []

        connection.request("GET", f"/titles/{title_id}")
        page = connection.getresponse().read().decode("utf-8")
        token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
        assert "Workflow actions" in page
        assert "Create Markdown build" in page
        assert "Create release candidate" not in page  # No build exists yet.

        response, _ = _post(connection, title_id, "scan-scripture", {"csrf_token": token},
                            origin="http://attacker.example")
        assert response.status == 403
        assert inspect_title(tmp_path, title_id)["verification"]["items"] == []
    finally:
        connection.close()
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def test_workspace_actions_use_audited_services_and_keep_release_blocked(tmp_path: Path):
    title_id, accepted_id = _accepted_title(tmp_path)
    accepted_path = next(Path(a["path"]) for a in inspect_title(tmp_path, title_id)["assets"]
                         if a["asset_id"] == accepted_id)
    accepted_hash = sha256_file(accepted_path)
    server = create_workspace_server(tmp_path, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    try:
        connection.request("GET", f"/titles/{title_id}")
        page = connection.getresponse().read().decode("utf-8")
        token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)

        def submit(action: str, **fields: str) -> None:
            response, _ = _post(connection, title_id, action,
                                {"csrf_token": token, "operator": "local-operator", **fields})
            assert response.status == 303, action
            assert response.headers["Location"].startswith(f"/titles/{title_id}?done={action}")

        submit("scan-scripture")
        submit("scan-scripture")  # Existing item is reused.
        submit("add-flag", kind="research", locator="chapter-001:paragraph-2",
               exact_text="A factual claim to check", asset_id=accepted_id)
        submit("add-rights", material_type="image", description="Reference image", asset_id=accepted_id)
        submit("queue-chapters", start="1", through="1")
        submit("pause-queue")
        submit("resume-queue")
        submit("build-manuscript")
        report = inspect_title(tmp_path, title_id)
        build = report["builds"]["records"][0]
        assert build["status"] == "blocked"
        assert build["manifest_exists"] and build["output_exists"]

        submit("create-candidate", build_id=build["build_id"])
        report = inspect_title(tmp_path, title_id)
        candidate = report["release"]["candidates"][0]
        assert candidate["status"] == "blocked"
        submit("export-packet", candidate_id=candidate["candidate_id"])

        report = inspect_title(tmp_path, title_id)
        assert len([item for item in report["verification"]["items"] if item["kind"] == "scripture"]) == 1
        assert len(report["verification"]["items"]) == 2
        assert report["verification"]["rights_records"][0]["status"] == "pending"
        assert report["release"]["packets"][0]["blockers"]
        assert report["release"]["candidates"][0]["approval_id"] is None
        assert sha256_file(accepted_path) == accepted_hash
        assert report["inconsistencies"] == []
        actions = {event["action"] for event in report["audit"]}
        assert {"verification.scripture_placeholder.queued", "verification.flag.created",
                "rights.record.created", "chapters.queued", "chapters.queue.paused",
                "chapters.queue.resume", "manuscript.build.created",
                "release.candidate.created", "release.packet.exported"} <= actions
    finally:
        connection.close()
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def test_workspace_rejects_invalid_queue_without_mutation(tmp_path: Path):
    title_id, _ = _accepted_title(tmp_path)
    server = create_workspace_server(tmp_path, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    try:
        connection.request("GET", f"/titles/{title_id}")
        page = connection.getresponse().read().decode("utf-8")
        token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
        response, body = _post(connection, title_id, "queue-chapters",
            {"csrf_token": token, "operator": "local-operator", "start": "1", "through": "11"})
        assert response.status == 422
        assert "bounded to 10 chapters" in body
        assert inspect_title(tmp_path, title_id)["chapter_workflow"]["chapters"][0]["queue_item_id"] is None
    finally:
        connection.close()
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
