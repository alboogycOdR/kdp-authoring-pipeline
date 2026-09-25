from pathlib import Path

from kdp_pipeline.core.state_machine import TitleState
from kdp_pipeline.storage.service import create_project, create_title, get_title, list_audit, transition_title


def test_project_title_workspace_and_audit(tmp_path: Path):
    project = create_project(tmp_path, "Pilot Project")
    title = create_title(tmp_path, project.project_id, "Working Title")

    assert (tmp_path / "projects" / project.project_id / "project.json").exists()
    assert (tmp_path / "projects" / project.project_id / "titles" / title.title_id / "06_canon" / "continuity-ledger.json").exists()
    assert get_title(tmp_path, title.title_id).status == "IDEA"

    transition_title(tmp_path, title.title_id, TitleState.VALIDATED)
    assert get_title(tmp_path, title.title_id).status == "VALIDATED"

    events = list_audit(tmp_path, title.title_id)
    assert len(events) == 2
    assert events[-1].action == "title.transition"
    assert events[-1].correlation_id == title.title_id
    assert events[-1].metadata_json == '{"after": "VALIDATED", "before": "IDEA"}'
