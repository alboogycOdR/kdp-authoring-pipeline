from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from kdp_pipeline.inspection import doctor
from kdp_pipeline.storage import files
from kdp_pipeline.storage.db import engine_for, init_db
from kdp_pipeline.storage.service import create_project, create_title, register_asset, session_scope


def test_text_and_json_writes_fsync_and_text_is_lf_normalized(tmp_path: Path, monkeypatch):
    calls: list[int] = []
    original_fsync = files.os.fsync
    monkeypatch.setattr(files.os, "fsync", lambda fd: (calls.append(fd), original_fsync(fd))[1])

    text_path = tmp_path / "nested" / "text.md"
    json_path = tmp_path / "nested" / "data.json"
    files.write_text(text_path, "alpha\r\nbeta\rgamma\n")
    files.write_json(json_path, {"ok": True})

    assert text_path.read_bytes() == b"alpha\nbeta\ngamma\n"
    assert len(calls) >= 2


def test_sqlite_schema_version_foreign_keys_and_audit_events_are_guarded(tmp_path: Path):
    project = create_project(tmp_path, "Durability")
    engine = engine_for(tmp_path)
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() >= 1000
            assert connection.exec_driver_sql("PRAGMA user_version").scalar() == 1
            with pytest.raises(IntegrityError):
                connection.exec_driver_sql(
                    "INSERT INTO titles (title_id, project_id, working_title, created_at) "
                    "VALUES ('BK-missing', 'PRJ-missing', 'orphan', '2026-01-01')"
                )
                connection.commit()
            connection.rollback()
            with pytest.raises(IntegrityError):
                connection.exec_driver_sql("UPDATE audit_events SET result='edited'")
                connection.commit()
            connection.rollback()
            with pytest.raises(IntegrityError):
                connection.exec_driver_sql("DELETE FROM audit_events")
                connection.commit()
    finally:
        engine.dispose()

    with session_scope(tmp_path) as session:
        event_count = session.execute(text("SELECT COUNT(*) FROM audit_events")).scalar_one()
    assert event_count == 1


def test_newer_database_schema_is_rejected_before_schema_changes(tmp_path: Path):
    state = tmp_path / ".kdp" / "state.db"
    state.parent.mkdir(parents=True)
    with sqlite3.connect(state) as connection:
        connection.execute("CREATE TABLE future_data (value TEXT)")
        connection.execute("PRAGMA user_version=999")

    with pytest.raises(RuntimeError, match="newer than this code"):
        init_db(tmp_path)

    with sqlite3.connect(state) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"future_data"}


def test_verified_relocation_rebases_asset_paths_and_records_audit(tmp_path: Path):
    project = create_project(tmp_path, "Relocation")
    title = create_title(tmp_path, project.project_id, "Restored title")
    asset_path = tmp_path / "projects" / project.project_id / "titles" / title.title_id / "sample.md"
    files.write_text(asset_path, "verified content\n")
    asset = register_asset(tmp_path, title.title_id, asset_path, "chapter.draft")

    restored = tmp_path.with_name(f"{tmp_path.name}-restored")
    shutil.move(str(tmp_path), restored)
    from kdp_pipeline.storage.relocate import relocate_workspace

    result = relocate_workspace(restored, str(tmp_path))
    assert result["committed"] is True
    assert result["verification_failures"] == []
    with session_scope(restored) as session:
        relocated = session.get(type(asset), asset.asset_id)
        assert relocated.path == str(restored / Path(asset.path).relative_to(tmp_path))
    assert not [check for check in doctor(restored) if check["check"] == "paths.relocation" and check["status"] == "FAIL"]
    shutil.move(str(restored), tmp_path)


def test_failed_relocation_rolls_back_path_rewrites(tmp_path: Path):
    project = create_project(tmp_path, "Relocation failure")
    title = create_title(tmp_path, project.project_id, "Corrupt restored title")
    asset_path = tmp_path / "projects" / project.project_id / "titles" / title.title_id / "sample.md"
    files.write_text(asset_path, "before corruption\n")
    asset = register_asset(tmp_path, title.title_id, asset_path, "chapter.draft")

    restored = tmp_path.with_name(f"{tmp_path.name}-corrupt")
    shutil.move(str(tmp_path), restored)
    (restored / Path(asset.path).relative_to(tmp_path)).write_text("tampered\n", encoding="utf-8")
    from kdp_pipeline.storage.relocate import relocate_workspace

    result = relocate_workspace(restored, str(tmp_path))
    assert result["committed"] is False
    assert result["verification_failures"] == [f"asset:{asset.asset_id}"]
    with session_scope(restored) as session:
        unchanged = session.get(type(asset), asset.asset_id)
        assert unchanged.path == asset.path
    shutil.move(str(restored), tmp_path)


def test_legacy_schema_is_upgraded_additively(tmp_path: Path):
    init_db(tmp_path)
    state = tmp_path / ".kdp" / "state.db"
    with sqlite3.connect(state) as connection:
        connection.execute("PRAGMA user_version=0")
        connection.execute("ALTER TABLE provenance DROP COLUMN prompt_template_sha256")

    init_db(tmp_path)

    engine = engine_for(tmp_path)
    try:
        with engine.connect() as connection:
            columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(provenance)")}
            assert "prompt_template_sha256" in columns
            assert connection.exec_driver_sql("PRAGMA user_version").scalar() == 1
    finally:
        engine.dispose()
