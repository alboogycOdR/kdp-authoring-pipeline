from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from kdp_pipeline.concept import ConceptService, accept_concept, enable_concept_gate, score_concept, validate_concept
from kdp_pipeline.models.planning import PlanningArtifactKind
from kdp_pipeline.planning import PlanningService, accept_planning_artifact
from kdp_pipeline.storage.db import ConceptGateRow, TitleRow, AuditEventRow
from kdp_pipeline.storage.service import create_project, create_title, session_scope
from kdp_pipeline.context import ContextManifest
from kdp_pipeline.providers import FakeProvider
from kdp_pipeline.providers.contracts import GenerationResult


def test_legacy_title_defaults_to_concept_gate_off_and_gate_blocks_positioning(tmp_path: Path):
    (tmp_path / "prompts").mkdir()
    project = create_project(tmp_path, "Concept test")
    title = create_title(tmp_path, project.project_id, "Legacy-compatible")
    with session_scope(tmp_path) as session:
        stored = session.get(TitleRow, title.title_id)
        assert session.get(ConceptGateRow, title.title_id) is None
    assert enable_concept_gate(tmp_path, title.title_id, True) is True
    with session_scope(tmp_path) as session:
        assert session.get(ConceptGateRow, title.title_id).enabled is True
    with pytest.raises(ValueError, match="accept a concept brief"):
        asyncio.run(PlanningService.generate(
            tmp_path, title_id=title.title_id, artifact_kind=PlanningArtifactKind.POSITIONING,
            context_manifest=ContextManifest(title_id=title.title_id, task_type="planning.positioning", inputs=[]),
            provider=FakeProvider(),
        ))
    with session_scope(tmp_path) as session:
        assert session.scalar(select(AuditEventRow).where(
            AuditEventRow.action == "concept.gate.changed", AuditEventRow.entity_id == title.title_id
        )) is not None


def test_concept_gate_also_blocks_acceptance_of_preexisting_positioning_proposal(tmp_path: Path):
    shutil.copytree(Path("prompts"), tmp_path / "prompts")
    project = create_project(tmp_path, "Concept gate")
    title = create_title(tmp_path, project.project_id, "No bypass")
    proposal = asyncio.run(PlanningService.generate(
        tmp_path, title_id=title.title_id, artifact_kind=PlanningArtifactKind.POSITIONING,
        context_manifest=ContextManifest(title_id=title.title_id, task_type="planning.positioning", inputs=[]),
        provider=FakeProvider(),
    ))
    enable_concept_gate(tmp_path, title.title_id, True)
    with pytest.raises(ValueError, match="before accepting positioning"):
        accept_planning_artifact(tmp_path, proposal.asset.asset_id, reviewer="human")


@pytest.mark.parametrize("product_type,engine_key,need_key", [
    ("youth-fiction", "story_engine", "emotional_need"),
    ("devotional", "recurring_content_engine", "practical_or_spiritual_need"),
])
def test_concept_validation_supports_fiction_and_nonfiction(product_type, engine_key, need_key):
    data = {"product_type": product_type, "audience": {"age_range": "16-18", "reading_context": "independent"},
            "format": "short chapters", "distinctive_lens": "community setting", "promise": "A specific reader promise.",
            "content_notes": [], engine_key: "A repeatable engine.", need_key: "A clear reader need."}
    report = validate_concept(data)
    assert report["status"] == "pass"
    assert report["human_review_required"] is True


def test_concept_validation_flags_underspecified_audience_and_guarantees():
    report = validate_concept({"product_type": "fiction", "promise": "guaranteed sales"})
    assert report["status"] == "review"
    assert "audience" in report["missing_fields"]
    assert any("guarantee" in warning for warning in report["warnings"])


def test_scorecard_requires_rationale_and_is_advisory():
    scores = {"reader_fit": 5, "emotional_charge": 4, "engine_strength": 4, "freshness": 3,
              "market_legibility": 4, "execution_feasibility": 3, "series_potential": 2}
    rationale = {key: "Evidence-based rationale." for key in scores}
    result = score_concept(scores, rationale)
    assert result["weighted_total"] == 3.85
    assert result["suggested_action"] == "revise_and_retest"
    assert result["human_decision_required"] is True
    with pytest.raises(ValueError, match="rationale"):
        score_concept(scores, {})


class ConceptFixtureProvider:
    provider_name = "fixture"
    model_name = "concept-test"

    def __init__(self):
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        response = {"product_type": "devotional", "audience": {"explicit_stage": "adults starting small ventures"},
                    "format": "short daily devotional", "distinctive_lens": "faithful business practice",
                    "promise": "Practical spiritual reflection for everyday decisions.", "content_notes": [],
                    "practical_or_spiritual_need": "Connect faith with work.",
                    "recurring_content_engine": "Situation, reflection, practice, optional prayer."}
        return GenerationResult(provider=self.provider_name, model=self.model_name,
                                text=json.dumps(response), latency_ms=0)


def test_concept_context_is_sent_and_brief_requires_human_approval(tmp_path: Path):
    shutil.copytree(Path("prompts"), tmp_path / "prompts")
    project = create_project(tmp_path, "Concept workflow")
    title = create_title(tmp_path, project.project_id, "Devotional concept")
    provider = ConceptFixtureProvider()
    audience = asyncio.run(ConceptService.generate(tmp_path, title_id=title.title_id,
        artifact="audience-brief", audience="Adults launching a small business", provider=provider))
    seeds = asyncio.run(ConceptService.generate(tmp_path, title_id=title.title_id,
        artifact="generate-seeds", concept_asset_id=audience.asset.asset_id, provider=provider))
    brief = asyncio.run(ConceptService.generate(tmp_path, title_id=title.title_id,
        artifact="enrich", concept_asset_id=seeds.asset.asset_id, selection="Seed 4: devotional for freelance makers", provider=provider))
    enrich_prompt = provider.requests[-1].rendered_prompt.rendered_text
    assert "Seed 4: devotional for freelance makers" in enrich_prompt
    assert "[fake" not in enrich_prompt
    assert accept_concept(tmp_path, brief.asset.asset_id, reviewer="human").accepted_asset.approval_status == "accepted"
    assert accept_concept(tmp_path, brief.asset.asset_id, reviewer="human").approval.decision == "accepted"
