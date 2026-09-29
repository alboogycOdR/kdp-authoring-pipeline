"""Audit test harness.

Every test named ``test_KDP_AUD_###_*`` asserts the *secure / correct*
behaviour, so it FAILS on the audited baseline (91c48ad) and should pass once
the corresponding patch in ``audit/patches/`` is applied. Tests named
``test_POS_*`` are positive controls: they document a defence that held and
must keep passing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import os

AUDIT = Path(__file__).resolve().parents[1]
# KDP_AUDIT_TARGET selects the tree under test: the audited baseline (default, this checkout) or a
# checkout with audit/patches applied. Findings tests must fail on the baseline and pass on the fix.
REPO = Path(os.environ.get("KDP_AUDIT_TARGET", AUDIT.parent)).resolve()
for path in (REPO / "src", AUDIT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from lab.kdplab import make_root  # noqa: E402
from lab.mock_provider import MockProviderServer  # noqa: E402

EVIDENCE = AUDIT / "evidence"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return make_root(tmp_path / "ws")


@pytest.fixture
def mock(tmp_path: Path, request):
    log = EVIDENCE / "mock-requests" / f"{request.node.name}.jsonl"
    log.unlink(missing_ok=True)
    server = MockProviderServer(0, log).start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def evidence(request) -> Path:
    name = request.node.name
    ident = name.split("_", 1)[1] if name.startswith("test_") else name
    parts = ident.split("_")
    key = "-".join(parts[:3]) if parts[:2] == ["KDP", "AUD"] else ident
    path = EVIDENCE / key
    path.mkdir(parents=True, exist_ok=True)
    return path
