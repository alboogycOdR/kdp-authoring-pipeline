"""WS-F (durability/consistency) and WS-G (build/release integrity)."""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from lab.kdplab import REPO, CaptureProvider, draft_and_accept, plan_title, rows
from kdp_pipeline.build.service import build_manuscript
from kdp_pipeline.inspection import doctor, inspect_title
from kdp_pipeline.storage.db import init_db


def _non_ok(checks):
    return [c for c in checks if c["status"] != "OK"]


def test_POS_doctor_detects_corrupted_and_missing_asset_files(root, evidence):
    book = plan_title(root)
    draft, accepted = draft_and_accept(book)
    path = Path(accepted.destination_path)
    path.write_bytes(path.read_bytes() + b"x")
    Path(draft.output_path).unlink()
    bad = _non_ok(doctor(root))
    (evidence / "doctor.json").write_text(json.dumps(bad, indent=2))
    assert any("hash mismatch" in c["message"] for c in bad) and any("missing" in c["message"] for c in bad)


def test_KDP_AUD_027_relocated_workspace_breaks_every_asset(root, tmp_path, evidence):
    book = plan_title(root)
    draft_and_accept(book)
    moved = tmp_path / "restored-elsewhere"
    shutil.move(str(root), moved)
    try:  # a supported, verified relocation path must exist
        from kdp_pipeline.storage.relocate import relocate_workspace
        (evidence / "relocate.json").write_text(json.dumps(relocate_workspace(moved, str(root)), indent=2))
    except ImportError:
        pass
    bad = _non_ok(doctor(moved))
    (evidence / "doctor_after_move.json").write_text(json.dumps(bad, indent=2))
    stored = rows(moved, "select path from assets limit 3")
    (evidence / "stored_paths.json").write_text(json.dumps(stored, indent=2))
    assert not [c for c in bad if c["check"].startswith("asset:")], \
        f"Backup restored to another path: {len(bad)} FAIL checks (absolute paths in DB); no relocate command exists"


def test_KDP_AUD_040_doctor_misses_build_manifest_canon_and_approval_tampering(root, evidence):
    book = plan_title(root)
    draft_and_accept(book)
    build = build_manuscript(root, title_id=book.title_id, builder="b")
    Path(build.build.manifest_path).unlink()                                  # manifest deleted
    canon = root / "projects" / book.project_id / "titles" / book.title_id / "06_canon" / "entities.json"
    canon.write_text('{"entities":["tampered"]}')                              # canon edited
    with sqlite3.connect(root / ".kdp" / "state.db") as conn:                 # approval hash forged
        conn.execute("update approvals set candidate_hash=? where scope='chapter.1'", ("0" * 64,))
    bad = [c for c in _non_ok(doctor(root)) if not c["check"].startswith(("provider", "usage", "budget"))]
    (evidence / "doctor.json").write_text(json.dumps(_non_ok(doctor(root)), indent=2))
    assert len(bad) >= 3, f"doctor reported {len(bad)} problems for 3 independent integrity breaks"


def test_KDP_AUD_032_build_drops_every_line_equal_to_the_heading(root, evidence):
    text = "# Chapter One\n\nIntro.\n\n# Chapter One\n\nThe refrain above is part of the poem.\n"
    provider = CaptureProvider({"chapter.draft.1": text})
    book = plan_title(root, provider)
    draft_and_accept(book, provider)
    build = build_manuscript(root, title_id=book.title_id, builder="b")
    manuscript = Path(rows(root, "select path from assets where asset_id=?", build.asset.asset_id)[0]["path"]).read_text()
    (evidence / "manuscript.md").write_text(manuscript)
    assert manuscript.count("# Chapter One") == 2, "Repeated heading line silently removed from chapter body"


def test_POS_build_output_is_byte_deterministic(root):
    book = plan_title(root)
    draft_and_accept(book)
    a = build_manuscript(root, title_id=book.title_id, builder="b")
    b = build_manuscript(root, title_id=book.title_id, builder="b")
    assert a.build.output_sha256 == b.build.output_sha256


def test_KDP_AUD_043_crlf_checkout_changes_hashes_of_identical_content(root, evidence):
    """Same chapter bytes arriving via a CRLF (core.autocrlf) checkout produce a different content hash;
    write_text uses newline='' so no normalisation happens anywhere."""
    from kdp_pipeline.storage.files import write_text, sha256_file
    lf, crlf = root / "lf.md", root / "crlf.md"
    write_text(lf, "# C\n\nBody\n")
    write_text(crlf, "# C\r\n\r\nBody\r\n")
    (evidence / "hashes.json").write_text(json.dumps({"lf": sha256_file(lf), "crlf": sha256_file(crlf)}, indent=2))
    assert sha256_file(lf) == sha256_file(crlf), "No newline normalisation: Windows/Linux copies hash differently"


def test_POS_schema_upgrade_from_v0_1_database(tmp_path, evidence):
    """Create a DB with the v0.1 code, then open it with HEAD (additive migrations)."""
    old = tmp_path / "old-src"
    subprocess.run(["git", "-C", str(REPO), "worktree", "add", "--detach", str(old), "v0.1-core-roadmap"],
                   check=True, capture_output=True)
    try:
        ws = tmp_path / "ws"
        ws.mkdir()
        script = ("import sys; sys.path.insert(0, sys.argv[1]);"
                  "from pathlib import Path; from kdp_pipeline.storage.service import create_project, create_title;"
                  "p=create_project(Path(sys.argv[2]),'old'); print(create_title(Path(sys.argv[2]),p.project_id,'t').title_id)")
        out = subprocess.run([sys.executable, "-c", script, str(old / "src"), str(ws)], check=True,
                             capture_output=True, text=True).stdout.strip()
        init_db(ws)
        report = inspect_title(ws, out)
        (evidence / "upgrade.json").write_text(json.dumps({"title": report["title"]}, indent=2, default=str))
        assert report["title"]["title_id"] == out
    finally:
        subprocess.run(["git", "-C", str(REPO), "worktree", "remove", "--force", str(old)], capture_output=True)


def test_KDP_AUD_041_no_schema_version_so_newer_db_is_silently_accepted_by_older_code(root, evidence):
    with sqlite3.connect(root / ".kdp" / "state.db") as conn:
        conn.execute("create table future_feature(x)")
        version = conn.execute("pragma user_version").fetchone()[0]
        tables = [r[0] for r in conn.execute("select name from sqlite_master where name like '%version%' or name like '%migration%'")]
    (evidence / "schema.json").write_text(json.dumps({"user_version": version, "version_tables": tables}, indent=2))
    assert version or tables, "No schema version marker; upgrades/downgrades cannot be detected or ordered"


def test_KDP_AUD_042_sqlite_runs_without_foreign_keys_wal_or_busy_timeout(root, evidence):
    from kdp_pipeline.storage.db import engine_for
    engine = engine_for(root)
    with engine.connect() as conn:
        pragmas = {name: conn.exec_driver_sql(f"pragma {name}").scalar() for name in ("foreign_keys", "journal_mode", "busy_timeout", "synchronous")}
    engine.dispose()
    (evidence / "pragmas.json").write_text(json.dumps(pragmas, indent=2))
    assert pragmas["foreign_keys"] == 1, f"Foreign keys declared but not enforced: {pragmas}"
