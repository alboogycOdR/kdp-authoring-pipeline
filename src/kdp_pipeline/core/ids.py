from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


def new_id(prefix: str) -> str:
    """Create a sortable-enough human-readable ID without external dependencies."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"{prefix}-{stamp}-{uuid4().hex[:8].upper()}"
