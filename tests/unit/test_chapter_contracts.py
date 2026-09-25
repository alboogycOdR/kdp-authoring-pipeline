import pytest

from kdp_pipeline.models.chapter import ChapterArtifact, ChapterAssetKind
from kdp_pipeline.models.canon import CanonProposal, CanonProposalStatus


def test_chapter_and_canon_contracts_validate():
    artifact = ChapterArtifact(
        title_id="BK-1", chapter_number=1, asset_id="AST-1", asset_type=ChapterAssetKind.DRAFT,
        path="draft.md", sha256="a" * 64, approval_status="experimental",
    )
    assert artifact.chapter_number == 1
    proposal = CanonProposal(
        proposal_id="CAN-1", title_id="BK-1", entity_id="chapter-001", field="timeline",
        proposed_value="review", reason="continuity finding",
    )
    assert proposal.status == CanonProposalStatus.PROPOSED


def test_chapter_number_must_be_positive():
    with pytest.raises(ValueError):
        ChapterArtifact(
            title_id="BK-1", chapter_number=0, asset_id="AST-1", asset_type=ChapterAssetKind.DRAFT,
            path="draft.md", sha256="a" * 64, approval_status="experimental",
        )
