from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def create_project_workspace(root: Path, project_id: str, project_name: str) -> Path:
    p = root / "projects" / project_id
    if p.exists():
        raise FileExistsError(f"Project workspace already exists: {p}")
    (p / "series").mkdir(parents=True, exist_ok=True)
    (p / "titles").mkdir(parents=True, exist_ok=True)
    write_json(p / "project.json", {"project_id": project_id, "name": project_name})
    return p


def create_title_workspace(root: Path, project_id: str, title_id: str, working_title: str) -> Path:
    p = root / "projects" / project_id / "titles" / title_id
    if p.exists():
        raise FileExistsError(f"Title workspace already exists: {p}")
    dirs = [
        "00_admin", "01_research", "02_sources", "03_rights", "04_plan/chapter-cards",
        "05_drafts/experimental", "05_drafts/accepted", "06_canon", "07_editorial",
        "08_art", "09_build", "10_qa", "11_release", "12_archive"
    ]
    for d in dirs:
        (p / d).mkdir(parents=True, exist_ok=True)
    write_json(p / "00_admin" / "title.json", {
        "title_id": title_id,
        "project_id": project_id,
        "working_title": working_title,
        "status": "IDEA",
    })
    write_json(p / "06_canon" / "continuity-ledger.json", {"entities": [], "facts": [], "unresolved": []})
    write_json(p / "06_canon" / "entities.json", {"entities": []})
    write_json(p / "06_canon" / "unresolved.json", {"unresolved": []})
    return p
