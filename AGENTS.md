# KDP Pipeline Agent Instructions

## Architectural source of truth

The current architectural source of truth is:

`docs/architecture/KDP_PIPELINE_SYSTEM_ARCHITECTURE_BUILD_SPEC_v1.0.md`

Do not silently change the architecture. If an implementation conflicts with the architecture specification, stop and report the conflict before proceeding.

Do not implement functionality from future sprints merely because it seems useful. Keep work within the requested sprint and scope.

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
