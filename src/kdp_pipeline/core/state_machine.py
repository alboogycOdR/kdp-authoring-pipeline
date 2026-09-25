from __future__ import annotations

from enum import StrEnum


class TitleState(StrEnum):
    IDEA = "IDEA"
    VALIDATED = "VALIDATED"
    PLANNED = "PLANNED"
    DRAFTING = "DRAFTING"
    EDITING = "EDITING"
    ASSET_READY = "ASSET_READY"
    PREFLIGHT_FAILED = "PREFLIGHT_FAILED"
    PREFLIGHT_PASSED = "PREFLIGHT_PASSED"
    HUMAN_RELEASE_REVIEW = "HUMAN_RELEASE_REVIEW"
    KDP_DRAFT_READY = "KDP_DRAFT_READY"
    HUMAN_SUBMITTED = "HUMAN_SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    LIVE = "LIVE"
    MONITORING = "MONITORING"
    UPDATE_ASSESSMENT = "UPDATE_ASSESSMENT"
    RIGHTS_HOLD = "RIGHTS_HOLD"
    POLICY_HOLD = "POLICY_HOLD"
    KDP_EXCEPTION = "KDP_EXCEPTION"


_ALLOWED: dict[TitleState, set[TitleState]] = {
    TitleState.IDEA: {TitleState.VALIDATED},
    TitleState.VALIDATED: {TitleState.PLANNED, TitleState.RIGHTS_HOLD},
    TitleState.PLANNED: {TitleState.DRAFTING, TitleState.RIGHTS_HOLD},
    TitleState.DRAFTING: {TitleState.EDITING, TitleState.POLICY_HOLD},
    TitleState.EDITING: {TitleState.ASSET_READY, TitleState.POLICY_HOLD},
    TitleState.ASSET_READY: {TitleState.PREFLIGHT_PASSED, TitleState.PREFLIGHT_FAILED},
    TitleState.PREFLIGHT_FAILED: {TitleState.ASSET_READY},
    TitleState.PREFLIGHT_PASSED: {TitleState.HUMAN_RELEASE_REVIEW},
    TitleState.HUMAN_RELEASE_REVIEW: {TitleState.KDP_DRAFT_READY, TitleState.POLICY_HOLD},
    TitleState.KDP_DRAFT_READY: {TitleState.HUMAN_SUBMITTED},
    TitleState.HUMAN_SUBMITTED: {TitleState.IN_REVIEW, TitleState.KDP_EXCEPTION},
    TitleState.IN_REVIEW: {TitleState.LIVE, TitleState.KDP_EXCEPTION},
    TitleState.LIVE: {TitleState.MONITORING},
    TitleState.MONITORING: {TitleState.UPDATE_ASSESSMENT},
    TitleState.RIGHTS_HOLD: {TitleState.VALIDATED},
    TitleState.POLICY_HOLD: {TitleState.HUMAN_RELEASE_REVIEW},
    TitleState.KDP_EXCEPTION: set(),
    TitleState.UPDATE_ASSESSMENT: set(),
}


def can_transition(current: TitleState, target: TitleState) -> bool:
    return target in _ALLOWED.get(current, set())


def require_transition(current: TitleState, target: TitleState) -> None:
    if not can_transition(current, target):
        raise ValueError(f"Illegal title state transition: {current} -> {target}")
