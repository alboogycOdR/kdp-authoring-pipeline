from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from kdp_pipeline.core.hashing import canonical_json_bytes, sha256_bytes
from kdp_pipeline.core.ids import new_id
from kdp_pipeline.storage.audit import AuditEventWriter
from kdp_pipeline.storage.db import (
    ApprovalRow,
    AssetRow,
    ManuscriptBuildRow,
    ProjectRow,
    ProvenanceRow,
    RightsLogRow,
    TitleRow,
    VerificationItemRow,
    utcnow,
)
from kdp_pipeline.storage.files import sha256_file, write_json, write_text
from kdp_pipeline.storage.service import register_asset, session_scope


_CHAPTER_NAME = re.compile(r"chapter-(?P<number>\d{3})\.md$", re.IGNORECASE)
_SCRIPTURE_PLACEHOLDER = re.compile(r"\[SCRIPTURE NEEDED\]", re.IGNORECASE)
_MATTER_TYPES = {"front": "manuscript.front_matter", "back": "manuscript.back_matter"}


@dataclass(frozen=True)
class BuildResult:
    build: ManuscriptBuildRow
    asset: AssetRow
    manifest: dict


def register_matter(root: Path, *, title_id: str, section: str, source_path: Path,
                    creator: str) -> AssetRow:
    if section not in _MATTER_TYPES or not creator.strip():
        raise ValueError("Matter section must be front or back and creator is required")
    if not source_path.is_file():
        raise ValueError("Matter source file does not exist")
    text = source_path.read_text(encoding="utf-8")
    with session_scope(root) as session:
        title = session.get(TitleRow, title_id)
        if title is None:
            raise ValueError(f"Unknown title: {title_id}")
        project_id = title.project_id
    source_id = new_id("AST")
    path = root / "projects" / project_id / "titles" / title_id / "09_build" / "matter" / "experimental" / f"{section}-{source_id}.md"
    write_text(path, text)
    return register_asset(root, title_id, path, _MATTER_TYPES[section],
        creator_type="human", creator=creator.strip())


def accept_matter(root: Path, asset_id: str, *, reviewer: str) -> tuple[AssetRow, ApprovalRow]:
    if not reviewer.strip():
        raise ValueError("Reviewer is required")
    with session_scope(root) as session:
        source = session.get(AssetRow, asset_id)
        if source is None or source.asset_type not in set(_MATTER_TYPES.values()) or source.approval_status != "experimental":
            raise ValueError("Only experimental front or back matter can be accepted")
        source_path = Path(source.path)
        if not source_path.is_file() or sha256_file(source_path) != source.sha256:
            raise ValueError("Matter source file/hash integrity check failed")
        project = session.get(ProjectRow, session.get(TitleRow, source.title_id).project_id)
        section = "front" if source.asset_type == _MATTER_TYPES["front"] else "back"
        destination = root / "projects" / project.project_id / "titles" / source.title_id / "05_drafts" / "accepted" / "matter" / f"{section}-matter.md"
        existing = session.scalar(select(AssetRow).where(AssetRow.title_id == source.title_id,
            AssetRow.asset_type == source.asset_type, AssetRow.approval_status == "accepted"))
        if existing is not None:
            if existing.source_ref == source.asset_id and Path(existing.path).is_file() and sha256_file(Path(existing.path)) == existing.sha256:
                approval = session.scalar(select(ApprovalRow).where(ApprovalRow.asset_id == existing.asset_id,
                    ApprovalRow.decision == "accepted"))
                if approval is not None:
                    return existing, approval
            raise ValueError(f"Accepted {section} matter already exists")
        if destination.exists():
            raise ValueError(f"Accepted matter destination already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        output_hash = sha256_file(destination)
        accepted = AssetRow(asset_id=new_id("AST"), title_id=source.title_id,
            asset_type=source.asset_type, path=str(destination.resolve()), version=source.version,
            sha256=output_hash, creator_type="human", creator=source.creator,
            source_ref=source.asset_id, approval_status="accepted", created_at=utcnow())
        approval = ApprovalRow(approval_id=new_id("APR"), title_id=source.title_id,
            asset_id=accepted.asset_id, scope=f"manuscript.{section}_matter",
            candidate_hash=output_hash, approver=reviewer, decision="accepted",
            conditions_json="[]", created_at=utcnow())
        session.add_all([accepted, approval])
        AuditEventWriter.append(session, actor_id=reviewer, action="manuscript.matter.accepted",
            entity_type="asset", entity_id=accepted.asset_id, correlation_id=source.title_id,
            result="success", before_hash=source.sha256, after_hash=output_hash,
            metadata={"source_asset_id": source.asset_id, "approval_id": approval.approval_id,
                "section": section})
        session.commit()
        return accepted, approval


def _accepted_assets(session, title_id: str, asset_type: str) -> list[AssetRow]:
    return list(session.scalars(select(AssetRow).where(AssetRow.title_id == title_id,
        AssetRow.asset_type == asset_type, AssetRow.approval_status == "accepted").order_by(AssetRow.created_at)))


def build_manuscript(root: Path, *, title_id: str, builder: str = "cli-user") -> BuildResult:
    if not builder.strip():
        raise ValueError("Builder is required")
    with session_scope(root) as session:
        title = session.get(TitleRow, title_id)
        if title is None:
            raise ValueError(f"Unknown title: {title_id}")
        if title.status != "DRAFTING":
            raise ValueError("Manuscript builds require a title in DRAFTING state")
        project_id = title.project_id
        chapter_assets = _accepted_assets(session, title_id, "chapter.accepted")
        matter_assets = _accepted_assets(session, title_id, _MATTER_TYPES["front"]) + _accepted_assets(session, title_id, _MATTER_TYPES["back"])
        accepted_cards = _accepted_assets(session, title_id, "planning.chapter-card")
        items = list(session.scalars(select(VerificationItemRow).where(VerificationItemRow.title_id == title_id)))
        rights_records = list(session.scalars(select(RightsLogRow).where(RightsLogRow.title_id == title_id)))
        all_approvals = list(session.scalars(select(ApprovalRow).where(ApprovalRow.title_id == title_id,
            ApprovalRow.decision == "accepted")))
        if not chapter_assets:
            raise ValueError("Cannot build a manuscript without accepted chapter assets")

        chapters: list[tuple[int, AssetRow, str]] = []
        included: list[dict] = []
        included_ids: set[str] = set()
        blockers: list[dict] = []
        for asset in chapter_assets:
            path = Path(asset.path)
            match = _CHAPTER_NAME.search(path.name)
            approval = next((item for item in all_approvals if item.asset_id == asset.asset_id), None)
            provenance = session.scalar(select(ProvenanceRow).where(ProvenanceRow.asset_id == asset.asset_id))
            if match is None or approval is None or not path.is_file() or sha256_file(path) != asset.sha256 or approval.candidate_hash != asset.sha256:
                raise ValueError(f"Accepted chapter failed approval or integrity checks: {asset.asset_id}")
            number = int(match.group("number"))
            text = path.read_text(encoding="utf-8")
            chapters.append((number, asset, text))
            included_ids.add(asset.asset_id)
            included.append({"asset_id": asset.asset_id, "asset_type": asset.asset_type,
                "chapter_number": number, "sha256": asset.sha256,
                "provenance_id": provenance.provenance_id if provenance else None,
                "lineage_source_asset_id": asset.source_ref})
            if asset.creator_type == "ai" and provenance is None:
                blockers.append({"type": "missing_provenance", "asset_id": asset.asset_id})
            for placeholder in _SCRIPTURE_PLACEHOLDER.finditer(text):
                line = text.count("\n", 0, placeholder.start()) + 1
                blockers.append({"type": "scripture_placeholder", "asset_id": asset.asset_id,
                    "locator": f"chapter-{number:03d}:line-{line:04d}", "text": placeholder.group(0)})
        chapters.sort(key=lambda item: item[0])
        numbers = [item[0] for item in chapters]
        if len(numbers) != len(set(numbers)):
            raise ValueError("More than one accepted chapter asset maps to the same chapter number")
        gaps = sorted(set(range(1, max(numbers) + 1)) - set(numbers))
        if gaps:
            blockers.append({"type": "missing_chapters", "chapter_numbers": gaps})
        planned_numbers = set()
        for card in accepted_cards:
            card_path = Path(card.path)
            card_match = _CHAPTER_NAME.search(card_path.name)
            card_approval = next((item for item in all_approvals if item.asset_id == card.asset_id), None)
            if card_match is None or card_approval is None or not card_path.is_file() or sha256_file(card_path) != card.sha256 or card_approval.candidate_hash != card.sha256:
                blockers.append({"type": "planning_card_integrity", "asset_id": card.asset_id})
                continue
            planned_numbers.add(int(card_match.group("number")))
        planned_numbers = sorted(planned_numbers)
        unaccepted_planned = sorted(set(planned_numbers) - set(numbers))
        if unaccepted_planned:
            blockers.append({"type": "planned_chapters_not_accepted", "chapter_numbers": unaccepted_planned})

        accepted_matter: dict[str, str] = {}
        for asset in matter_assets:
            path = Path(asset.path)
            approval = next((item for item in all_approvals if item.asset_id == asset.asset_id), None)
            if approval is None or not path.is_file() or sha256_file(path) != asset.sha256:
                raise ValueError(f"Accepted matter failed approval or integrity checks: {asset.asset_id}")
            section = "front" if asset.asset_type == _MATTER_TYPES["front"] else "back"
            if section in accepted_matter:
                raise ValueError(f"More than one accepted {section} matter asset exists")
            accepted_matter[section] = path.read_text(encoding="utf-8")
            included_ids.add(asset.asset_id)
            included.append({"asset_id": asset.asset_id, "asset_type": asset.asset_type,
                "section": section, "sha256": asset.sha256, "provenance_id": None,
                "lineage_source_asset_id": asset.source_ref})

        for item in items:
            if item.status not in {"verified", "not_applicable"} and (item.asset_id is None or item.asset_id in included_ids):
                blockers.append({"type": "verification", "verification_id": item.verification_id,
                    "kind": item.kind, "asset_id": item.asset_id, "locator": item.locator,
                    "status": item.status})
        for record in rights_records:
            if record.status not in {"cleared", "not_applicable"} and (record.asset_id is None or record.asset_id in included_ids):
                blockers.append({"type": "rights", "rights_record_id": record.rights_record_id,
                    "asset_id": record.asset_id, "material_type": record.material_type,
                    "status": record.status})
        for approval in all_approvals:
            if approval.asset_id in included_ids:
                for condition in json.loads(approval.conditions_json or "[]"):
                    blockers.append({"type": "approval_condition", "approval_id": approval.approval_id,
                        "asset_id": approval.asset_id, "condition": condition})

        chapter_titles = []
        for number, _asset, text in chapters:
            heading = next((line.lstrip("#").strip() for line in text.splitlines()
                            if line.startswith("# ")), f"Chapter {number}")
            chapter_titles.append((number, heading))
        toc = "## Contents\n\n" + "\n".join(f"- [{heading}](#chapter-{number:03d})" for number, heading in chapter_titles)
        sections = []
        if accepted_matter.get("front", "").strip():
            sections.append(accepted_matter["front"].strip())
        sections.append(toc)
        for number, _asset, text in chapters:
            heading = next((line for line in text.splitlines() if line.startswith("# ")), f"# Chapter {number}")
            body = "\n".join(line for line in text.splitlines() if line != heading).strip()
            sections.append(f'<a id="chapter-{number:03d}"></a>\n\n{heading}\n\n{body}'.rstrip())
        if accepted_matter.get("back", "").strip():
            sections.append(accepted_matter["back"].strip())
        manuscript = f"# {title.working_title}\n\n" + "\n\n---\n\n".join(sections) + "\n"
        status = "blocked" if blockers else "built"
        build_id = new_id("BLD")
        base = root / "projects" / project_id / "titles" / title_id / "09_build" / "experimental" / build_id
        output_path = base / "manuscript.md"
        manifest_path = base / "manifest.json"
        included.sort(key=lambda item: (item.get("chapter_number", 0), item.get("section", "")))
        manifest = {"build_id": build_id, "title_id": title_id, "working_title": title.working_title,
            "build_type": "accepted_manuscript_assembly", "output_format": "markdown",
            "status": status, "release_eligible": False, "release_review_required": True,
            "included_assets": included,
            "blockers": blockers, "created_by": builder.strip(), "created_at": utcnow().isoformat()}
    write_text(output_path, manuscript)
    write_json(manifest_path, manifest)
    output_hash = sha256_file(output_path)
    manifest_hash = sha256_file(manifest_path)
    with session_scope(root) as session:
        asset = AssetRow(asset_id=new_id("AST"), title_id=title_id, asset_type="manuscript.build",
            path=str(output_path.resolve()), version="1.0", sha256=output_hash, creator_type="system",
            creator=builder.strip(), source_ref=str(manifest_path.resolve()), approval_status="experimental",
            created_at=utcnow())
        row = ManuscriptBuildRow(build_id=build_id, title_id=title_id, asset_id=asset.asset_id,
            status=status, output_format="markdown", output_sha256=output_hash,
            manifest_path=str(manifest_path.resolve()), manifest_sha256=manifest_hash,
            included_assets_json=json.dumps(included), blockers_json=json.dumps(blockers),
            created_by=builder.strip(), created_at=utcnow())
        session.add_all([asset, row])
        AuditEventWriter.append(session, actor_id=builder.strip(), action="manuscript.build.created",
            entity_type="manuscript_build", entity_id=build_id, correlation_id=title_id,
            result="blocked" if blockers else "success", before_hash=sha256_bytes(canonical_json_bytes(included)),
            after_hash=output_hash, metadata={"asset_id": asset.asset_id, "manifest_sha256": manifest_hash,
                "status": status, "blocker_count": len(blockers), "included_asset_ids": [i["asset_id"] for i in included]})
        session.commit()
        return BuildResult(row, asset, manifest)
