# KDP Pipeline — Local Authoring Workflow

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

## Provider profiles, usage, and budgets

Generation requires an explicitly selected provider profile for the project. Add a profile, check it (offline by default), then select it:

```powershell
kdp providers add-openai-compatible openai "OpenAI" "gpt-5" --base-url https://api.openai.com/v1 --api-key-env OPENAI_API_KEY
kdp providers check openai
kdp providers select openai --project-id PRJ-...
```

`kdp providers check PROFILE --connect` is the only check command that makes a network request. API-key values are read from the named environment variable at request time; only the variable name is saved. Set credentials in the launching shell/session; `.env.example` is reference-only and is not auto-loaded. Never place credentials in profile notes or metadata. Configure operator-supplied prices with `kdp pricing set`; no current provider prices are built in. Project limits use USD: `kdp budget set PROJECT_ID --monthly-usd 25 --hard-stop` (or `--soft`). With hard-stop enabled, an unpriced model is blocked before invocation. Soft budgets permit it, recording unknown cost and a warning. `kdp inspect usage TITLE_ID`, `kdp inspect provider TITLE_ID`, `kdp inspect budget TITLE_ID`, and `kdp doctor` are read-only.

## Architectural rule already enforced

A title cannot jump directly from `IDEA` to `DRAFTING`. State changes must use the allowed workflow transitions and every accepted transition emits an audit event.
