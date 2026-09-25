"""Run the current single-chapter pipeline with FakeProvider in an isolated workspace."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import tempfile
from pathlib import Path

from kdp_pipeline.chapter import ChapterService, accept_chapter
from kdp_pipeline.continuity import ContinuityService
from kdp_pipeline.editorial import EditorialService
from kdp_pipeline.context import ContextManifest
from kdp_pipeline.inspection import inspect_title
from kdp_pipeline.models.planning import PlanningArtifactKind
from kdp_pipeline.planning import PlanningService, accept_planning_artifact
from kdp_pipeline.providers import FakeProvider
from kdp_pipeline.storage.service import advance_to_drafting, advance_to_planned, advance_to_validated, create_project, create_title


def run(root: Path) -> dict:
    repo_root = Path(__file__).resolve().parents[1]
    if not (root / "prompts").is_dir():
        shutil.copytree(repo_root / "prompts", root / "prompts")
    project = create_project(root, "Pilot Dry Run")
    title = create_title(root, project.project_id, "Pilot Title")
    provider = FakeProvider()
    planning_results = []
    for kind, chapter_number in ((PlanningArtifactKind.POSITIONING, None), (PlanningArtifactKind.BOOK_BRIEF, None),
                                 (PlanningArtifactKind.OUTLINE, None), (PlanningArtifactKind.CHAPTER_CARD, 1)):
        result = asyncio.run(PlanningService.generate(
            root, title_id=title.title_id, artifact_kind=kind,
            context_manifest=ContextManifest(title_id=title.title_id, task_type="planning", inputs=[]),
            provider=provider, chapter_number=chapter_number,
        ))
        planning_results.append(accept_planning_artifact(root, result.asset.asset_id, reviewer="pilot", chapter_number=chapter_number))
    advance_to_validated(root, title.title_id)
    advance_to_planned(root, title.title_id)
    advance_to_drafting(root, title.title_id)
    draft = asyncio.run(ChapterService.draft(root, title_id=title.title_id, chapter_number=1, provider=provider))
    continuity = asyncio.run(ContinuityService.analyze(root, title_id=title.title_id, chapter_number=1, source_asset_id=draft.asset.asset_id, provider=provider))
    editorial = asyncio.run(EditorialService.developmental(root, title_id=title.title_id, chapter_number=1, source_asset_id=draft.asset.asset_id, provider=provider))
    revision = asyncio.run(ChapterService.revise(
        root, title_id=title.title_id, chapter_number=1, source_asset_id=draft.asset.asset_id,
        finding_ids=[continuity.finding.finding_id, editorial.finding.finding_id], provider=provider,
    ))
    accepted = accept_chapter(root, revision.asset.asset_id, chapter_number=1, reviewer="pilot",
                              finding_ids=[continuity.finding.finding_id, editorial.finding.finding_id],
                              proposal_ids=[continuity.proposal.proposal_id])
    report = inspect_title(root, title.title_id)
    return {"root": str(root), "project_id": project.project_id, "title_id": title.title_id,
            "draft_asset_id": draft.asset.asset_id, "revision_asset_id": revision.asset.asset_id,
            "accepted_asset_id": accepted.accepted_asset.asset_id, "proposal_id": continuity.proposal.proposal_id,
            "inspection": report}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="Explicit workspace root; omitted means a temporary isolated workspace")
    args = parser.parse_args()
    if args.root:
        print(json.dumps(run(args.root.resolve()), indent=2, default=str))
        return
    with tempfile.TemporaryDirectory(prefix="kdp-pilot-") as directory:
        print(json.dumps(run(Path(directory)), indent=2, default=str))


if __name__ == "__main__":
    main()

