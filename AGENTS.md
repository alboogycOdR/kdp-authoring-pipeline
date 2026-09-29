# KDP Pipeline Agent Instructions

## Architecture Documentation Hierarchy

Use this precedence when locating or evaluating architecture guidance:

1. `AGENTS.md` — repository instructions and agent boundaries.
2. `KDP_PIPELINE_MASTER_ARCHITECTURE_PACK/` — long-term architecture source of truth.
3. `docs/architecture/` — detailed architecture and build specifications.
4. `docs/operations/` — workflow procedures, sprint reports, and pilot records.
5. Other project documentation.

Architectural decisions and implementation must remain consistent with the Master Architecture Pack. If guidance conflicts, `AGENTS.md` wins, followed by the Architecture Pack, then the remaining project documentation in the order above. Do not silently change architecture. Stop and report a conflict before proceeding with work that depends on resolving it.

Use [the architecture index](docs/ARCHITECTURE_INDEX.md) to navigate the architecture pack, detailed specifications, operational documentation, ADRs, and reports.

## Project Governance Documents

These entry points work together to define project governance:

- [ARCHITECTURE.md](ARCHITECTURE.md) explains the system and points to authoritative architecture material.
- [ROADMAP.md](ROADMAP.md) summarizes completed and planned milestones; implementation scope still requires explicit task authorization.
- [DECISIONS.md](DECISIONS.md) indexes accepted architecture decisions and links to their ADRs.
- [KDP_PIPELINE_MASTER_ARCHITECTURE_PACK/](KDP_PIPELINE_MASTER_ARCHITECTURE_PACK/README.md) holds the long-term architecture baseline and decision records.

These navigation documents do not override this file's agent instructions or create authorization for future work. Keep implementation aligned with the Master Architecture Pack and raise conflicts for review.

Do not implement functionality from future sprints merely because it seems useful. Keep work within the requested sprint and scope.

## Operating Environments

Development runs in this Windows checkout. The `clawsrv` Ubuntu VPS hosts one staging installation with its own SQLite database and artefact directory. Read [the environment runbook](docs/operations/ENVIRONMENTS.md) before changing or deploying staging. The existing projects were migrated once; subsequent development and staging changes do not synchronize. The VPS Workspace is reachable only through Tailscale and has no application login; keep it off the public internet. Any future cross-platform data copy requires an explicit, integrity-checked migration.

## Mandatory design principles

- SQLite is authoritative for operational state.
- Markdown, JSON, and other files are durable content artefacts and synchronized/generated snapshots where applicable; they must not become a competing operational database.
- AI-generated output is experimental until explicitly accepted.
- No canon mutation is allowed without an approved `CanonProposal`.
- No accepted AI-generated asset is allowed without provenance.
- Every workflow state mutation must be auditable.
- Models and providers must remain replaceable.
- Deterministic tasks should use deterministic code rather than LLMs wherever practical.
- Policy, rights, quality, and approval failures must never be automatically retried into success.
- Official current Amazon/KDP documentation outranks internal research, practitioner advice, repositories, and historical notes for KDP policy.
- AI workers must never receive KDP credentials, tax information, banking credentials, identity documents, or MFA codes.
- Final KDP publication remains human-controlled.

## Engineering and change-management rules

- Preserve backwards compatibility unless a task or architecture decision explicitly authorizes a breaking change.
- Run relevant tests after making changes.
- Run the full test suite before declaring a task complete.
- Do not commit, push, merge, rebase, delete branches, or perform destructive Git operations unless explicitly instructed.
