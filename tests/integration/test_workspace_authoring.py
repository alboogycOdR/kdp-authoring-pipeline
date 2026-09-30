from __future__ import annotations

import asyncio
import re
import shutil
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread
from urllib.parse import urlencode

from kdp_pipeline.concept.service import ConceptService, accept_concept, validate_concept_asset
from kdp_pipeline.providers.configuration import add_provider_profile
from kdp_pipeline.providers.costs import set_model_pricing
from kdp_pipeline.providers.settings import ProviderProfileSettings
from kdp_pipeline.storage.service import session_scope
from kdp_pipeline.storage.db import AssetRow, ProjectBudgetRow, ProjectProviderSelectionRow, TitleRow
from kdp_pipeline.workspace.authoring import (create_book, create_manual_revision,
    read_edit_source, run_authoring_action)
from kdp_pipeline.workspace.inspection import inspect_workspace
from kdp_pipeline.workspace.server import create_workspace_server


def _profile(root: Path) -> None:
    add_provider_profile(root, ProviderProfileSettings(
        provider_id="authoring-fake", provider_type="fake", display_name="Local fake",
        model="fake-v1", default_max_output_tokens=200))
    set_model_pricing(root, "authoring-fake", "fake-v1",
                      input_usd_per_million=1, output_usd_per_million=1)


def _fields() -> dict[str, str]:
    return {"operator": "reader-editor", "project_name": "My new book",
            "title_name": "A working title", "audience": "Adults learning a new skill",
            "idea": "A practical book about learning to repair bicycles.",
            "provider_id": "authoring-fake", "monthly_usd": "5", "max_run_usd": "0.50"}


def test_book_creation_saves_human_idea_and_hard_cost_controls(tmp_path: Path):
    shutil.copytree(Path("prompts"), tmp_path / "prompts")
    _profile(tmp_path)
    title_id, message = create_book(tmp_path, _fields())
    with session_scope(tmp_path) as session:
        title = session.get(TitleRow, title_id)
        budget = session.get(ProjectBudgetRow, title.project_id)
        selection = session.get(ProjectProviderSelectionRow, title.project_id)
        note = session.query(AssetRow).filter_by(title_id=title_id, asset_type="concept.idea-note").one()
        assert title.status == "IDEA"
        assert selection.provider_id == "authoring-fake"
        assert budget.hard_stop and budget.monthly_limit_usd == 5
        assert budget.max_run_estimated_cost_usd == 0.5
        assert note.creator_type == "human"
        assert "repair bicycles" in Path(note.path).read_text(encoding="utf-8")
        assert note.asset_id in message

    # A browser generation requires explicit cost confirmation.
    try:
        run_authoring_action(tmp_path, title_id, "audience-brief", {"audience": "Adult beginners"})
    except ValueError as exc:
        assert "usage cost" in str(exc)
    else:
        raise AssertionError("Unconfirmed provider request was allowed")

    result = asyncio.run(ConceptService.generate(tmp_path, title_id=title_id,
        artifact="audience-brief", audience="Adult beginners"))
    assert result.provenance.input_references == [note.asset_id]
    assert result.provenance.input_hashes == [note.sha256]
    assert result.asset.approval_status == "experimental"


def test_browser_start_form_creates_book_without_provider_call(tmp_path: Path):
    shutil.copytree(Path("prompts"), tmp_path / "prompts")
    _profile(tmp_path)
    server = create_workspace_server(tmp_path, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    try:
        connection.request("GET", "/")
        page = connection.getresponse().read().decode("utf-8")
        assert "Start a new book" in page
        assert "Create book and save idea" in page
        token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)

        connection.request("POST", "/books", body=urlencode(_fields()),
                           headers={"Content-Type": "application/x-www-form-urlencoded",
                                    "Sec-Fetch-Site": "same-origin"})
        response = connection.getresponse()
        response.read()
        assert response.status == 403
        assert inspect_workspace(tmp_path)["projects"] == []

        connection.request("POST", "/books", body=urlencode({**_fields(), "csrf_token": token}),
                           headers={"Content-Type": "application/x-www-form-urlencoded",
                                    "Sec-Fetch-Site": "same-origin"})
        response = connection.getresponse()
        response.read()
        assert response.status == 303
        location = response.headers["Location"]
        assert location.startswith("/titles/BK-")
        connection.request("GET", location)
        page = connection.getresponse().read().decode("utf-8")
        assert "Book authoring" in page
        assert "Your starting idea is saved" in page
        assert "Generate audience brief" in page
        assert len(inspect_workspace(tmp_path)["projects"]) == 1
        title_id = location.split("/titles/", 1)[1].split("?", 1)[0]
        connection.request("POST", f"/titles/{title_id}/actions/audience-brief",
            body=urlencode({"csrf_token": token, "operator": "reader-editor",
                            "audience": "Adult beginners"}),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Sec-Fetch-Site": "same-origin"})
        response = connection.getresponse()
        response.read()
        assert response.status == 422
        connection.request("POST", f"/titles/{title_id}/actions/audience-brief",
            body=urlencode({"csrf_token": token, "operator": "reader-editor",
                            "audience": "Adult beginners", "confirm_cost": "yes"}),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Sec-Fetch-Site": "same-origin"})
        response = connection.getresponse()
        response.read()
        assert response.status == 303
        assert response.headers["Location"].startswith(f"/titles/{title_id}?result=")
        assert any(a["asset_type"] == "concept.audience-brief"
                   for a in inspect_workspace(tmp_path)["titles"][title_id]["assets"])
    finally:
        connection.close()
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def test_manual_concept_edit_preserves_source_and_can_be_human_approved(tmp_path: Path):
    shutil.copytree(Path("prompts"), tmp_path / "prompts")
    _profile(tmp_path)
    title_id, _ = create_book(tmp_path, _fields())
    audience = asyncio.run(ConceptService.generate(tmp_path, title_id=title_id,
        artifact="audience-brief", audience="Adults learning repairs"))
    seeds = asyncio.run(ConceptService.generate(tmp_path, title_id=title_id,
        artifact="generate-seeds", concept_asset_id=audience.asset.asset_id))
    concept = asyncio.run(ConceptService.generate(tmp_path, title_id=title_id,
        artifact="enrich", concept_asset_id=seeds.asset.asset_id,
        selection="My practical bicycle repair book"))
    original, digest, _ = read_edit_source(tmp_path, title_id, concept.asset.asset_id)
    revised = '{"product_type":"nonfiction","audience":{"explicit_stage":"adult beginners"},"format":"book","distinctive_lens":"hands-on repairs","promise":"learn basic repairs","content_notes":[],"recurring_content_engine":"one repair per chapter","practical_or_spiritual_need":"maintain a bicycle"}'
    message = create_manual_revision(tmp_path, title_id, concept.asset.asset_id,
        {"operator": "reader-editor", "reason": "Clarify the practical concept",
         "source_sha256": digest, "content": revised})
    assert "experimental" in message
    with session_scope(tmp_path) as session:
        revision = session.query(AssetRow).filter_by(title_id=title_id, source_ref=concept.asset.asset_id,
            asset_type="concept.brief", approval_status="experimental").one()
        assert Path(concept.asset.path).read_text(encoding="utf-8") == original
        assert Path(revision.path).read_text(encoding="utf-8") == revised
    report, _ = validate_concept_asset(tmp_path, revision.asset_id)
    assert report["status"] == "pass"
    accepted = accept_concept(tmp_path, revision.asset_id, reviewer="reader-editor")
    assert accepted.accepted_asset.source_ref == revision.asset_id
