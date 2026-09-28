# AI Agent Contribution Guide

This guide complements [AGENTS.md](../AGENTS.md), which governs repository instructions and architecture-document precedence. Read it and the [Master Architecture Pack](../KDP_PIPELINE_MASTER_ARCHITECTURE_PACK/README.md) before changing project documentation or implementation.

## Working principles

- **Architecture first:** Check the Architecture Pack and [architecture index](ARCHITECTURE_INDEX.md) before designing a change. Surface conflicts instead of silently choosing a direction.
- **Service first:** Put workflow and domain behavior in the appropriate service layer. Keep CLI and user-interface code as adapters; avoid embedding business rules there.
- **SQLite is authoritative:** Use the database as the operational source of truth. Markdown, JSON, and other files are durable content artefacts or synchronized snapshots, not competing operational databases.
- **Keep approval gates:** Generated material remains experimental until accepted through the established workflow. Do not bypass review, provenance, audit, or canon-proposal approval.
- **Protect secrets:** Never print, commit, or place API keys, tokens, headers, KDP credentials, tax or banking details, identity documents, or MFA codes in prompts, logs, reports, or artefacts.
- **Provider safety:** Do not make real provider calls unless the task explicitly authorizes them. Never retry policy, rights, quality, or approval failures into success. Do not give AI workers KDP credentials or publication authority.
- **Testing:** Follow `AGENTS.md`; run relevant tests and the full `pytest -v` suite before declaring implementation work complete. Run workflow dry-runs and `git diff --check` when requested or relevant, and report exact outcomes.
- **Branch strategy:** Keep work on the requested branch or create a task-scoped branch from the requested base. Do not switch, merge, rebase, or delete branches without explicit authorization. Preserve existing user work.
- **Commit strategy:** Keep changes reviewable and scoped. Do not commit, push, merge, rebase, or delete branches unless explicitly instructed. When authorized, stage only intended files and report the resulting commit.
- **Documentation updates:** Update the architecture index and affected operator/developer docs when behavior or workflow changes. Prefer links to canonical content over copied explanations. Keep roadmap, report, and implementation status accurate.

## Before finishing

Summarize changed files, behavior and documentation updates, test results, known limitations, and any unresolved decisions. Do not claim a workflow is release-ready while blockers remain.
