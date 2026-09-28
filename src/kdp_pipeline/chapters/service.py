from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy import select

from kdp_pipeline.chapter.service import _accepted_chapter_card
from kdp_pipeline.core.hashing import canonical_json_bytes, sha256_bytes
from kdp_pipeline.core.ids import new_id
from kdp_pipeline.storage.audit import AuditEventWriter
from kdp_pipeline.storage.db import (ApprovalRow, AssetRow, ChapterQueueRow, EditorialFindingRow,
                                     JobRow, ProvenanceRow, TitleRow, utcnow)
from kdp_pipeline.storage.files import sha256_file, write_text
from kdp_pipeline.storage.service import session_scope


_CHAPTER_IN_PATH = re.compile(r"chapter\.(?:draft|revision)\.(?P<number>\d{1,3})[-.]", re.IGNORECASE)
_ACCEPTED_PATH = re.compile(r"chapter-(?P<number>\d{3})\.md$")
_MAX_BATCH = 10


def _chapter_number(asset: AssetRow) -> int | None:
    path = Path(asset.path)
    match = _ACCEPTED_PATH.search(path.name) if asset.asset_type == "chapter.accepted" else _CHAPTER_IN_PATH.search(path.name)
    return int(match.group("number")) if match else None


def queue_chapters(root: Path, title_id: str, start: int, through: int, actor_id: str = "cli-user") -> list[ChapterQueueRow]:
    if start < 1 or through < start or through - start + 1 > _MAX_BATCH:
        raise ValueError(f"Queue range must be positive and bounded to {_MAX_BATCH} chapters")
    with session_scope(root) as session:
        title = session.get(TitleRow, title_id)
        if title is None:
            raise ValueError(f"Unknown title: {title_id}")
        if title.status != "DRAFTING":
            raise ValueError("Chapter work can be queued only while title is in DRAFTING")
        rows = []
        for number in range(start, through + 1):
            item = session.scalar(select(ChapterQueueRow).where(
                ChapterQueueRow.title_id == title_id, ChapterQueueRow.chapter_number == number))
            accepted_exists = any(a.approval_status == "accepted" and _chapter_number(a) == number
                                  for a in session.scalars(select(AssetRow).where(AssetRow.title_id == title_id,
                                      AssetRow.asset_type == "chapter.accepted")))
            status = "complete" if accepted_exists else "queued" if _accepted_chapter_card(session, title_id, number) else "waiting_for_card"
            if item is None:
                item = ChapterQueueRow(queue_item_id=new_id("CHQ"), title_id=title_id,
                    chapter_number=number, status=status, created_at=utcnow(), updated_at=utcnow())
                session.add(item)
            elif item.status not in {"paused", "complete"}:
                item.status = status
                item.updated_at = utcnow()
            rows.append(item)
        AuditEventWriter.append(session, actor_id=actor_id, action="chapters.queued", entity_type="title",
            entity_id=title_id, correlation_id=title_id, result="success",
            metadata={"start": start, "through": through, "max_batch": _MAX_BATCH,
                      "items": [{"chapter_number": row.chapter_number, "status": row.status} for row in rows]})
        session.commit()
        return rows


def stop_queue(root: Path, title_id: str, actor_id: str = "cli-user") -> int:
    return _set_queue(root, title_id, "paused", actor_id)


def resume_queue(root: Path, title_id: str, actor_id: str = "cli-user") -> int:
    return _set_queue(root, title_id, "resume", actor_id)


def _set_queue(root: Path, title_id: str, action: str, actor_id: str) -> int:
    with session_scope(root) as session:
        if session.get(TitleRow, title_id) is None:
            raise ValueError(f"Unknown title: {title_id}")
        items = list(session.scalars(select(ChapterQueueRow).where(ChapterQueueRow.title_id == title_id)))
        changed = 0
        for item in items:
            if action == "paused" and item.status == "queued":
                item.status = "paused"; item.updated_at = utcnow(); changed += 1
            elif action == "resume" and item.status == "paused":
                item.status = "queued" if _accepted_chapter_card(session, title_id, item.chapter_number) else "waiting_for_card"
                item.updated_at = utcnow(); changed += 1
        AuditEventWriter.append(session, actor_id=actor_id, action=f"chapters.queue.{action}",
            entity_type="title", entity_id=title_id, correlation_id=title_id, result="success",
            metadata={"changed_items": changed})
        session.commit()
        return changed


def chapter_status(root: Path, title_id: str) -> dict:
    with session_scope(root) as session:
        title = session.get(TitleRow, title_id)
        if title is None:
            raise ValueError(f"Unknown title: {title_id}")
        assets = list(session.scalars(select(AssetRow).where(AssetRow.title_id == title_id)))
        queue = {row.chapter_number: row for row in session.scalars(select(ChapterQueueRow).where(ChapterQueueRow.title_id == title_id))}
        cards = {}
        for asset in assets:
            if asset.asset_type == "planning.chapter-card" and asset.approval_status == "accepted":
                match = re.search(r"chapter-(\d{3})\.md$", Path(asset.path).name)
                if match: cards[int(match.group(1))] = asset.asset_id
        accepted = {_chapter_number(a): a.asset_id for a in assets if a.asset_type == "chapter.accepted" and a.approval_status == "accepted"}
        summary_sources = set()
        for summary in assets:
            if summary.asset_type != "chapter.summary" or summary.approval_status != "accepted":
                continue
            approval = session.scalar(select(ApprovalRow).where(ApprovalRow.asset_id == summary.asset_id,
                ApprovalRow.decision == "accepted"))
            path = Path(summary.path)
            if approval and path.is_file() and sha256_file(path) == summary.sha256:
                summary_sources.add(summary.source_ref)
        drafts = {}
        for asset in assets:
            if asset.asset_type in {"chapter.draft", "chapter.revision"} and asset.approval_status == "experimental":
                number = _chapter_number(asset)
                if number: drafts.setdefault(number, []).append(asset.asset_id)
        jobs = list(session.scalars(select(JobRow).where(JobRow.title_id == title_id)))
        statuses = []
        numbers = sorted(set(cards) | set(accepted) | set(drafts) | set(queue))
        for number in numbers:
            item = queue.get(number)
            failed = any(job.status == "failed" and job.job_type.endswith(f".{number}")
                         and job.job_type.startswith(("generate:chapter.draft.", "generate:chapter.revise.")) for job in jobs)
            missing_summaries = sorted(prior for prior, asset_id in accepted.items()
                                       if prior is not None and prior < number and asset_id not in summary_sources)
            state = ("complete" if number in accepted else "missing_card" if number not in cards
                     else "paused" if item and item.status == "paused" else "failed" if failed
                     else "awaiting_prior_summary" if missing_summaries
                     else "draft_ready" if drafts.get(number) else item.status if item else "needs_queue")
            statuses.append({"chapter_number": number, "status": state,
                "card_asset_id": cards.get(number), "draft_asset_ids": drafts.get(number, []),
                "accepted_asset_id": accepted.get(number), "queue_item_id": item.queue_item_id if item else None,
                "missing_prior_summaries": missing_summaries,
                "open_findings": [f.finding_id for f in session.scalars(select(EditorialFindingRow).where(
                    EditorialFindingRow.title_id == title_id, EditorialFindingRow.status == "open"))
                    if f.location == f"chapter-{number:03d}"]})
        next_chapter = next((row for row in statuses if row["status"] not in {"complete", "paused", "missing_card", "waiting_for_card"}), None)
        if next_chapter:
            next_chapter["recommended_action"] = ("write_prior_chapter_summary" if next_chapter["status"] == "awaiting_prior_summary"
                else "review_existing_draft" if next_chapter["status"] == "draft_ready"
                else "draft_one_chapter" if next_chapter["status"] == "queued" else "inspect_or_queue")
        accepted_count = len(accepted)
        return {"title_id": title_id, "chapter_count": len(numbers), "accepted_chapter_count": accepted_count,
                "chapters": statuses, "next_chapter": next_chapter,
                "missing_cards": [row["chapter_number"] for row in statuses if row["status"] == "missing_card"],
                "missing_prior_summary_chapters": [row["chapter_number"] for row in statuses if row.get("missing_prior_summaries")],
                "failed_chapters": [row["chapter_number"] for row in statuses if row["status"] == "failed"]}


def record_chapter_summary(root: Path, title_id: str, chapter_number: int, source_asset_id: str,
                            summary: str, reviewer: str) -> AssetRow:
    if chapter_number < 1 or not summary.strip() or len(summary) > 4000 or not reviewer.strip():
        raise ValueError("Chapter summary requires a positive chapter number, reviewer, and 1–4000 characters")
    with session_scope(root) as session:
        title = session.get(TitleRow, title_id)
        source = session.get(AssetRow, source_asset_id)
        if title is None or source is None or source.title_id != title_id or source.asset_type != "chapter.accepted" or _chapter_number(source) != chapter_number:
            raise ValueError("Summary must reference the accepted manuscript asset for this chapter")
        approval = session.scalar(select(ApprovalRow).where(ApprovalRow.asset_id == source_asset_id, ApprovalRow.decision == "accepted"))
        if approval is None or not Path(source.path).is_file() or sha256_file(Path(source.path)) != source.sha256:
            raise ValueError("Accepted chapter source approval/file/hash check failed")
        existing = session.scalar(select(AssetRow).where(AssetRow.title_id == title_id,
            AssetRow.asset_type == "chapter.summary", AssetRow.source_ref == source_asset_id,
            AssetRow.approval_status == "accepted").order_by(AssetRow.created_at.desc()))
        asset_id = new_id("AST")
        output = Path(source.path).parent / "context-summaries" / f"chapter-{chapter_number:03d}-{asset_id}.md"
        write_text(output, summary.strip() + "\n")
        digest = sha256_file(output)
        asset = AssetRow(asset_id=asset_id, title_id=title_id, asset_type="chapter.summary", path=str(output.resolve()),
            version="1.0", sha256=digest, creator_type="human", creator=reviewer,
            source_ref=source_asset_id, ai_classification="human_created", approval_status="accepted", created_at=utcnow())
        approval_row = ApprovalRow(approval_id=new_id("APR"), title_id=title_id, asset_id=asset_id,
            scope=f"chapter.{chapter_number}.summary", candidate_hash=digest, approver=reviewer,
            decision="accepted", conditions_json="[]", created_at=utcnow())
        provenance = ProvenanceRow(provenance_id=new_id("PROV"), asset_id=asset_id, job_id=None,
            provider="human", model="manual-summary", prompt_template_id="manual/chapter-summary",
            prompt_template_version="1.0", rendered_prompt_sha256=source.sha256,
            input_references_json=json.dumps([source_asset_id]), input_hashes_json=json.dumps([source.sha256]),
            context_manifest_hash=sha256_bytes(canonical_json_bytes({"source_asset_id": source_asset_id, "source_hash": source.sha256})),
            output_hash=digest, generation_timestamp=utcnow(), human_contribution_note="Human-authored summary of the accepted chapter.",
            ai_classification="human_created", disclosure_decision="not_applicable", reviewer=reviewer)
        session.add_all([asset, approval_row, provenance])
        AuditEventWriter.append(session, actor_id=reviewer, action="chapter.summary.accepted", entity_type="asset",
            entity_id=asset_id, correlation_id=title_id, result="success", before_hash=source.sha256,
            after_hash=digest, metadata={"chapter_number": chapter_number, "source_asset_id": source_asset_id,
                                        "supersedes_summary_asset_id": existing.asset_id if existing else None,
                                        "approval_id": approval_row.approval_id, "provenance_id": provenance.provenance_id})
        session.commit()
        return asset
