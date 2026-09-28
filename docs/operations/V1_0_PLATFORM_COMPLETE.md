# Version 1.0 — Platform Complete

## Executive summary

The local KDP authoring platform is complete through Sprint 16. It supports an audited path from concept and planning through chapter drafting, review, verification, deterministic Markdown builds, and human release preflight. The interactive Operator Workspace puts pending work first and explains artefacts, provenance, findings, blockers, conditions, and consequences before a human decision. Platform completion does not mean a particular title is ready to publish.

## Completed roadmap

- **Sprints 1–6:** local SQLite foundation, provider abstraction, prompt and job provenance, planning and chapter lifecycles, robustness, and provider usage/budget controls.
- **Sprints 7–13:** concept validation, bounded multi-chapter orchestration, expanded editorial passes, verification, Markdown build/export, release preflight, and static operator reporting.
- **v0.2 and v0.3:** production rehearsal hardening and backend readiness, recorded in the [v0.2](V0_2_PRODUCTION_REHEARSAL_REPORT.md) and [v0.3](V0_3_PRODUCTION_READINESS_REPORT.md) reports.
- **Sprints 14–16:** local interactive Workspace, explicit actions through existing services, and context-rich human review and approval pages. See the [completion report](SPRINTS_14_TO_16_FRONTEND_REPORT.md).

## Platform capabilities

Projects and titles have auditable state and durable artefacts. Accepted content retains hashes, provenance, and explicit approvals. Provider profiles, token usage, pricing configuration, and budgets are inspectable. Verification items and rights records expose unresolved work. Manuscript builds include asset hashes and manifests. Release candidates and review packets retain blockers. The Workspace provides attention queues, title inspection, workflow actions, and human decision pages. The CLI remains available for all supported operations.

## Architecture principles

Follow [AGENTS.md](../../AGENTS.md) and the [Master Architecture Pack](../../KDP_PIPELINE_MASTER_ARCHITECTURE_PACK/README.md). SQLite is authoritative for operational state; files are durable content artefacts and snapshots. Generated content stays experimental until accepted. Canon changes require proposal review. State changes are audited, providers are replaceable, and deterministic work uses deterministic code where practical. Human approval controls acceptance and release.

## Current operator workflow

Use `kdp doctor` and read-only `kdp inspect` commands to identify readiness and blockers. Check selected provider and pricing offline before any real generation; enter only operator-confirmed current rates. Open the local Workspace with `kdp workspace serve` or create a static snapshot with `kdp workspace dashboard`. Work through Needs Review, Needs Approval, Needs Verification, and Blocked queues. On every review page, read the artefact, provenance, findings, conditions, blockers, and stated decision effect before submitting a named human decision. The [Workspace guide](OPERATOR_WORKSPACE.md) and [pilot runbook](PILOT_WORKFLOW.md) give command details.

## Current publishing workflow

Accept planning and chapter artefacts explicitly. Record human Scripture, source/claim, research, and rights decisions with evidence. Build the accepted manuscript in Markdown, inspect its manifest and hashes, then create a release candidate and preflight packet. Resolve all blockers and complete the human checklist before release approval. The operator handles current KDP policy checks, metadata, disclosure, upload, and publication manually outside this platform.

## Known limitations and safety boundaries

- Pilot 1B remains in `DRAFTING`; its Chapter 1 `[SCRIPTURE NEEDED]` condition and other verification/rights items remain pending. Its release candidate is blocked. No content or approval was changed for this release note.
- Provider pricing is intentionally unset for the Pilot profile, so historical usage cost is unknown. Do not infer a price from a zero known-cost value.
- Export is Markdown only; DOCX and EPUB are not implemented. The local Workspace has no authentication and should run on a trusted workstation; browser review limits a displayed artefact to 1 MB.
- Generated content, canon proposals, verification, rights, release approval, and final publication require human control. No autonomous KDP upload or publication workflow exists. AI workers must never receive KDP account credentials, payment or tax data, identity documents, or MFA codes.

## Future roadmap

Future work needs separate approval. Candidate areas include additional export formats, expanded evidence workflows, and further operator usability, subject to the Master Architecture Pack and current official KDP policy. See [ROADMAP.md](../../ROADMAP.md); this release note does not authorize a new sprint.
