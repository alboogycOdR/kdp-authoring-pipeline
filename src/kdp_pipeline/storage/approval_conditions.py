from __future__ import annotations


def normalize_approval_conditions(conditions: list[str] | None) -> list[str]:
    """Validate human-entered approval conditions before they enter an approval record."""
    if conditions is None:
        return []
    if len(conditions) > 5:
        raise ValueError("An approval can record at most five conditions")
    cleaned = [condition.strip() for condition in conditions]
    if any(not condition or len(condition) > 500 for condition in cleaned):
        raise ValueError("Approval conditions must contain 1–500 characters each")
    return cleaned
