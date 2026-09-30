"""Integrity-checked rebase of persisted workspace paths after restoring a backup."""
from __future__ import annotations

import re
from pathlib import Path, PurePosixPath, PureWindowsPath

from sqlalchemy import select

from kdp_pipeline.storage.audit import AuditEventWriter
from kdp_pipeline.storage.db import AssetRow, CanonProposalRow, EditorialFindingRow, ManuscriptBuildRow
from kdp_pipeline.storage.files import sha256_file


def _relative_to_old(value: str | None, old_root: str) -> tuple[str, ...] | None:
    if not value:
        return None
    windows = bool(re.match(r"^[A-Za-z]:[\\/]", old_root)) or old_root.startswith("\\\\")
    if windows:
        candidate = PureWindowsPath(value)
        old = PureWindowsPath(old_root)
        candidate_parts = candidate.parts
        old_parts = old.parts
        if len(candidate_parts) < len(old_parts):
            return None
        if tuple(part.casefold() for part in candidate_parts[:len(old_parts)]) != tuple(
            part.casefold() for part in old_parts
        ):
            return None
        return candidate_parts[len(old_parts):]

    candidate = PurePosixPath(value)
    old = PurePosixPath(old_root)
    try:
        return candidate.relative_to(old).parts
    except ValueError:
        return None


def relocate_workspace(
    root: Path,
    old_root: str,
    *,
    actor_id: str = "cli-user",
    dry_run: bool = False,
) -> dict:
    """Rebase known stored paths and commit only when all referenced files verify.

    ``root`` must be the restored workspace. Entries not rooted under ``old_root`` are left alone.
    A failed verification or dry run rolls back all database path edits.
    """
    from kdp_pipeline.storage.service import session_scope

    root = root.resolve()
    changed: dict[str, int] = {}
    failures: list[str] = []
    with session_scope(root) as session:
        targets = (
            (AssetRow, ("path", "source_ref")),
            (ManuscriptBuildRow, ("manifest_path",)),
            (EditorialFindingRow, ("snapshot_path",)),
            (CanonProposalRow, ("snapshot_path",)),
        )
        rebased: list[tuple[object, str, str, str]] = []
        for model, fields in targets:
            for row in session.scalars(select(model)):
                for field in fields:
                    old_value = getattr(row, field)
                    relative = _relative_to_old(old_value, old_root)
                    if relative is None:
                        continue
                    new_value = str(root.joinpath(*relative))
                    if new_value != old_value:
                        setattr(row, field, new_value)
                        rebased.append((row, field, old_value, new_value))
                        key = f"{model.__tablename__}.{field}"
                        changed[key] = changed.get(key, 0) + 1

        for asset in session.scalars(select(AssetRow)):
            path = Path(asset.path)
            if not path.is_relative_to(root) or asset.approval_status == "superseded":
                continue
            if not path.is_file() or sha256_file(path) != asset.sha256:
                failures.append(f"asset:{asset.asset_id}")

        for build in session.scalars(select(ManuscriptBuildRow)):
            manifest = Path(build.manifest_path)
            if not manifest.is_relative_to(root):
                continue
            if not manifest.is_file() or sha256_file(manifest) != build.manifest_sha256:
                failures.append(f"build-manifest:{build.build_id}")

        for row, field, _old_value, new_value in rebased:
            if field == "snapshot_path" and not Path(new_value).is_file():
                failures.append(f"{row.__tablename__}:{row.__dict__.get('finding_id', row.__dict__.get('proposal_id'))}")

        summary = {
            "old_root": old_root,
            "new_root": str(root),
            "rewritten": changed,
            "verification_failures": sorted(set(failures)),
            "committed": False,
        }
        if failures or dry_run:
            session.rollback()
            return summary

        AuditEventWriter.append(
            session,
            actor_id=actor_id,
            action="workspace.relocated",
            entity_type="workspace",
            entity_id=str(root),
            correlation_id=str(root),
            result="success",
            metadata={"old_root": old_root, "rewritten": changed},
        )
        session.commit()
        summary["committed"] = True
        return summary
