import pytest
from kdp_pipeline.core.state_machine import TitleState, can_transition, require_transition


def test_idea_can_only_advance_to_validated():
    assert can_transition(TitleState.IDEA, TitleState.VALIDATED)
    assert not can_transition(TitleState.IDEA, TitleState.DRAFTING)


def test_illegal_transition_raises():
    with pytest.raises(ValueError):
        require_transition(TitleState.IDEA, TitleState.DRAFTING)


def test_rights_hold_and_recovery_are_legal():
    assert can_transition(TitleState.VALIDATED, TitleState.RIGHTS_HOLD)
    assert can_transition(TitleState.RIGHTS_HOLD, TitleState.VALIDATED)


def test_policy_hold_and_recovery_are_legal():
    assert can_transition(TitleState.DRAFTING, TitleState.POLICY_HOLD)
    assert can_transition(TitleState.POLICY_HOLD, TitleState.HUMAN_RELEASE_REVIEW)


def test_hold_states_block_unrelated_automation():
    assert not can_transition(TitleState.RIGHTS_HOLD, TitleState.PLANNED)
    assert not can_transition(TitleState.POLICY_HOLD, TitleState.ASSET_READY)
