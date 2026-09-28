# KDP Pipeline — Local Authoring Workflow

Local-first, audited, AI-assisted production workflows for KDP books, with human approval gates from concept through release preflight.

## Repository navigation

Suggested reading order for contributors and AI agents:

1. [README.md](README.md) — repository setup and quick orientation.
2. [ARCHITECTURE.md](ARCHITECTURE.md) — architectural landing page and links.
3. [AGENTS.md](AGENTS.md) — repository instructions and documentation precedence.
4. [KDP Pipeline Master Architecture Pack](KDP_PIPELINE_MASTER_ARCHITECTURE_PACK/README.md) — long-term architecture source of truth.
5. [docs/](docs/ARCHITECTURE_INDEX.md) — detailed specifications, operations, and reports.

For roadmap status and accepted architecture decisions, see [ROADMAP.md](ROADMAP.md) and [DECISIONS.md](DECISIONS.md).

Repository foundation includes:

- Python package + CLI
- SQLite state database
- project/title IDs
- durable project/title workspaces
- explicit title state machine
- append-only audit events
- basic project/title commands
- tests for workspace creation and state-transition integrity

Current workflow scope is documented in the [Master Architecture Pack](KDP_PIPELINE_MASTER_ARCHITECTURE_PACK/README.md) and its [architecture index](docs/ARCHITECTURE_INDEX.md). Operational guides cover concepts, chapter work, editorial review, verification, builds, release preflight, and the local operator dashboard.

## Architecture

The repository now contains the **KDP Pipeline Master Architecture Pack**, the long-term source of truth for architecture decisions. New contributors and AI agents should read [AGENTS.md](AGENTS.md), then the [Architecture Pack README](KDP_PIPELINE_MASTER_ARCHITECTURE_PACK/README.md) and [Master Architecture Overview](KDP_PIPELINE_MASTER_ARCHITECTURE_PACK/01_Architecture/MASTER_ARCHITECTURE_OVERVIEW.md), before reading implementation code. The older detailed build specification remains available under `docs/architecture/` and is subordinate to the pack. See [docs/ARCHITECTURE_INDEX.md](docs/ARCHITECTURE_INDEX.md) for navigation.

## Repository map

```text
AGENTS.md                              Agent instructions and documentation precedence
KDP_PIPELINE_MASTER_ARCHITECTURE_PACK/ Long-term architecture, ADRs, and planned doc areas
docs/architecture/                     Detailed architecture/build specification
docs/operations/                       Operator workflows, sprint and pilot reports
docs/research/                         Research references
prompts/                               Versioned generation and analysis prompts
src/kdp_pipeline/                      Python services, domain models, CLI, and storage
tests/                                 Unit and integration tests
projects/                              Local project/title artefacts and state snapshots
```

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
