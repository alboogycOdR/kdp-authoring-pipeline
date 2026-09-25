# KDP Pipeline v0.1 — Sprint 1 Foundation

This is the first executable scaffold for the local-first KDP authoring pipeline.

Implemented now:

- Python package + CLI
- SQLite state database
- project/title IDs
- durable project/title workspaces
- explicit title state machine
- append-only audit events
- basic project/title commands
- tests for workspace creation and state-transition integrity

Not implemented yet:

- model providers
- prompt registry
- provenance records
- planning templates
- chapter drafting
- continuity proposals
- editorial passes
- build/preflight/MCP

## Setup

```bash
python -m venv .venv
source .venv/bin/activate   # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Try it

```bash
kdp init-db
kdp init-project "Pilot Project"
# copy the returned PRJ-... ID
kdp new-title PRJ-... "Working Title"
# copy the returned BK-... ID
kdp status BK-...
kdp transition BK-... VALIDATED
kdp audit BK-...
```

## Tests

```bash
pytest -q
```

## Architectural rule already enforced

A title cannot jump directly from `IDEA` to `DRAFTING`. State changes must use the allowed workflow transitions and every accepted transition emits an audit event.
