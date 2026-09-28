# Roadmap

This is a concise status index. Architecture and scope detail belong in the [Master Architecture Pack](KDP_PIPELINE_MASTER_ARCHITECTURE_PACK/README.md) and linked specifications. Future work remains subject to explicit approval and task scope.

## Completed: Sprints 1–13

- **Sprint 1 — Foundation:** repository, SQLite, core models and IDs, project/title workspaces, hashing, audit, and CLI foundation.
- **Sprint 2 — Providers and prompts:** provider abstraction, prompt registry/versioning, generation jobs, provenance, and context manifests.
- **Sprint 3 — Planning pipeline:** positioning, book planning artefacts, outlines, chapter cards, and human acceptance.
- **Sprint 4 — Chapter lifecycle:** chapter drafting, continuity and developmental review, revision, accepted chapters, and canon approval.
- **Sprint 5 — Robustness:** idempotency, failure handling, state validation, audit/job inspection, and integration coverage.
- **Sprint 6 — Provider, usage, and budget controls:** selectable provider profiles, reasoning and timeout controls, usage/cost accounting, budget behavior, and hardening Sprints 6.1–6.5.
- **Sprint 7 — Concept validation:** optional human-gated concept workflow for fiction and nonfiction.
- **Sprint 8 — Chapter orchestration:** bounded queues, pause/resume, one-chapter drafting, and reviewed summaries.
- **Sprint 9 — Editorial expansion:** structured editorial passes and human-owned revision recommendations.
- **Sprint 10 — Scripture, source, and rights verification:** tracked verification items, evidence, decisions, and blockers.
- **Sprint 11 — Build and export:** deterministic Markdown manuscript assembly and hash inspection.
- **Sprint 12 — Release candidate and preflight:** frozen candidates, checklist, human review, and packet export.
- **Sprint 13 — Operator workspace:** static, read-only local dashboard.

See the [v1.0 build specification](docs/architecture/KDP_PIPELINE_SYSTEM_ARCHITECTURE_BUILD_SPEC_v1.0.md), [Sprint 7–13 implementation report](docs/operations/SPRINTS_7_TO_13_FINAL_REPORT.md), and [v0.1 release note](docs/operations/CORE_ROADMAP_V0_1_RELEASE_NOTE.md). The detailed build specification is subordinate to the Master Architecture Pack.

## Current milestone

**Core roadmap v0.1 complete.** The milestone is represented by `v0.1-core-roadmap-complete`; publication remains human-controlled.

## Future roadmap

- **v0.2 — Production Rehearsal Hardening:** current next milestone, informed by the [Pilot 1B rehearsal report](docs/operations/V0_2_PRODUCTION_REHEARSAL_REPORT.md). The report records rehearsal findings; it is not, by itself, approval to implement fixes.
- **Sprint 14 — Interactive Operator Frontend Foundation.**
- **Sprint 15 — Frontend Workflow Actions.**
- **Sprint 16 — Frontend Review & Approval UX.**

See the [Sprint 14–16 frontend specification](specs-frontend/Sprint_14_16_Frontend_Spec.md). These sprints remain planned, not completed.

## Potential later milestones

Possible candidates include DOCX/EPUB export, expanded Scripture/source evidence workflows, and further operator workspace development. These are not committed roadmap scope; evaluate them against the Master Architecture Pack and record accepted architectural decisions before implementation.
