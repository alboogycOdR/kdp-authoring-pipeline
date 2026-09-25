import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import inspect

from kdp_pipeline.core.state_machine import TitleState
from kdp_pipeline.storage.db import AssetRow, engine_for, init_db
from kdp_pipeline.storage.service import (
    create_project,
    create_title,
    get_title,
    list_audit,
    register_asset,
    session_scope,
    transition_title,
)


def test_database_creation_and_cleanup(tmp_path: Path):
    init_db(tmp_path)
    engine = engine_for(tmp_path)
    try:
        assert set(inspect(engine).get_table_names()) == {
            "projects", "titles", "assets", "jobs", "audit_events"
        }
    finally:
        engine.dispose()
    (tmp_path / ".kdp" / "state.db").unlink()


def test_complete_workspace_and_metadata_snapshots(tmp_path: Path):
    project = create_project(tmp_path, "Foundation", "en")
    title = create_title(tmp_path, project.project_id, "First Title", "en")
    title_root = tmp_path / "projects" / project.project_id / "titles" / title.title_id

    expected = {
        "00_admin", "01_research", "02_sources", "03_rights", "04_plan",
        "05_drafts", "06_canon", "07_editorial", "08_art", "09_build",
        "10_qa", "11_release", "12_archive",
    }
    assert {path.name for path in title_root.iterdir() if path.is_dir()} == expected
    for filename in ("continuity-ledger.json", "entities.json", "unresolved.json"):
        assert (title_root / "06_canon" / filename).is_file()

    project_snapshot = json.loads((tmp_path / "projects" / project.project_id / "project.json").read_text())
    assert project_snapshot["project_id"] == project.project_id
    assert project_snapshot["default_language"] == "en"
    assert project_snapshot["status"] == "ACTIVE"

    transition_title(tmp_path, title.title_id, TitleState.VALIDATED)
    title_snapshot = json.loads((title_root / "00_admin" / "title.json").read_text())
    assert title_snapshot["status"] == "VALIDATED"
    assert get_title(tmp_path, title.title_id).status == "VALIDATED"


def test_asset_registration_persists_actual_sha256_and_audit(tmp_path: Path):
    project = create_project(tmp_path, "Assets")
    title = create_title(tmp_path, project.project_id, "Asset Title")
    asset_path = tmp_path / "sample.md"
    asset_path.write_text("asset contents\n", encoding="utf-8")
    expected_hash = hashlib.sha256(asset_path.read_bytes()).hexdigest()

    asset = register_asset(tmp_path, title.title_id, asset_path, "manuscript")
    assert asset.sha256 == expected_hash
    with session_scope(tmp_path) as session:
        persisted = session.get(AssetRow, asset.asset_id)
        assert persisted.sha256 == expected_hash

    event = list_audit(tmp_path, asset.asset_id)[0]
    assert event.action == "asset.register"
    assert event.after_hash == expected_hash
    assert json.loads(event.metadata_json)["title_id"] == title.title_id


def test_creation_compensates_when_snapshot_write_fails(tmp_path: Path, monkeypatch):
    import kdp_pipeline.storage.service as service

    original = service.write_json
    def fail_on_snapshot(path, data):
        raise OSError("simulated snapshot failure")

    monkeypatch.setattr(service, "write_json", fail_on_snapshot)
    with pytest.raises(OSError):
        create_project(tmp_path, "Compensated")
    assert list((tmp_path / "projects").iterdir()) == []
