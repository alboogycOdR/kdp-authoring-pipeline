from pathlib import Path

from kdp_pipeline.models.planning import PlanningArtifactKind, spec_for
from kdp_pipeline.prompts import PromptRegistry


def test_planning_specs_use_required_templates_and_paths():
    assert spec_for(PlanningArtifactKind.POSITIONING).template_id == "planning/positioning-brief"
    assert spec_for(PlanningArtifactKind.BOOK_BRIEF).destination_template == "04_plan/book-brief.md"
    assert spec_for(PlanningArtifactKind.OUTLINE).destination_template == "04_plan/outline.md"
    assert "chapter-{chapter_number:03d}.md" in spec_for(PlanningArtifactKind.CHAPTER_CARD).destination_template


def test_planning_prompt_registry_renders_versioned_prompt():
    prompt = PromptRegistry(Path("prompts")).render(
        "planning/positioning-brief",
        {"title_id": "BK-1", "working_title": "Test", "target_reader": "Readers", "chapter_number": ""},
    )
    assert prompt.template_version == "1.0"
    assert prompt.rendered_sha256
    assert "Test" in prompt.rendered_text
