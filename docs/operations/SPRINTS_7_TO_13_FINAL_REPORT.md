# Sprints 7–13 implementation report

## Branch and commit range

- Branch: `feat/sprints-7-13-core-roadmap`
- Starting commit: `b67ceda` — Sprint 6.5 baseline
- Ending implementation commit: `2da0b7d` — Sprint 13 static operator workspace
- A separate documentation commit records this report; the implementation commits remain unchanged.
- The branch is pushed after the report commit for human review. It is not merged to `main`.

## Sprint summary and principal files

| Sprint | Result | Principal files and artefacts | Commit |
|---|---|---|---|
| 7 — Concept validation | Added an optional, human-gated concept workflow covering audience briefs, seeds, concept briefs, scorecards, validation, and drafting briefs. The model supports youth fiction and nonfiction/devotional products, with pre-Sprint-7 titles remaining usable. Added the supplied youth-book ideation guide and Pilot 1B retrospective. | `docs/research/Idea_Development_for_a_Youth-Book_KDP_Pipeline.md`; `docs/operations/CONCEPT_WORKFLOW.md`; `docs/operations/PILOT_1B_REAL_PROVIDER_RETROSPECTIVE.md`; `prompts/concept/`; `src/kdp_pipeline/concept/`; planning, inspection, CLI, and storage services; Sprint 7 tests. | `bd8f0fb` |
| 8 — Chapter orchestration | Added bounded chapter queues, pause/resume, per-chapter status, explicit one-chapter drafting, and reviewed summaries as hashed context for later chapters. Whole-book generation is not automatic. | `src/kdp_pipeline/chapters/`; `src/kdp_pipeline/chapter/service.py`; drafting prompts; CLI and inspection; `docs/operations/CHAPTER_ORCHESTRATION.md`; Sprint 8 tests. | `52e9cd3` |
| 9 — Editorial expansion | Added structured voice, line, copy, reader-experience, and consistency passes. Invalid or missing-context output is rejected before findings are registered. Human-owned revision recommendations do not modify manuscript assets. | `src/kdp_pipeline/models/editorial.py`; `src/kdp_pipeline/editorial/service.py`; five `prompts/editorial/*-v1.0.md` templates; CLI and inspection; `docs/operations/EDITORIAL_PASSES.md`; Sprint 9 tests. | `337919f` |
| 10 — Scripture, source, and rights verification | Added idempotent Scripture-placeholder scanning, human verification decisions with reference/policy/evidence, source/research/expert/sensitivity flags, rights records, audit events, and release-blocker inspection. No Scripture text is inserted. | `src/kdp_pipeline/verification/`; CLI and inspection; `docs/operations/VERIFICATION_WORKFLOW.md`; Sprint 10 tests. | `fe19d6d` |
| 11 — Build and export | Added accepted-chapter Markdown assembly, generated contents, optional separately accepted front/back matter, frozen input/output hashes, and build inspection. Builds with unresolved verification, rights, approval, or chapter-completeness issues are marked blocked; every build remains ineligible for release. | `src/kdp_pipeline/build/`; CLI and inspection; `docs/operations/BUILD_EXPORT.md`; Sprint 11 tests. | `b1ca24e` |
| 12 — Release candidate and preflight | Added frozen release candidates, metadata and AI-use disclosure records, human KDP checklist, blocker evaluation, human review, hashed packet export, and approval binding to the exact candidate/checklist state. Approval preserves the manual KDP action condition. | `src/kdp_pipeline/release/`; CLI and inspection; `docs/operations/RELEASE_CANDIDATE.md`; Sprint 12 tests. | `c4cccc3` |
| 13 — Operator workspace | Added a local static HTML dashboard generated from existing read-only inspection services. It summarizes projects, provider readiness, budgets/usage, title lifecycle, planning/concept, chapters, editorial/canon, verification, builds, release candidates, and human review queues. | `src/kdp_pipeline/workspace/`; CLI; `docs/operations/OPERATOR_WORKSPACE.md`; Sprint 13 tests. | `2da0b7d` |

The shared storage, inspection, CLI, and storage-schema test files were extended across the sprints. Each sprint is a separate local commit on the same implementation branch.

## Database and operational state

SQLite remains authoritative. New tables are created through the existing SQLAlchemy initialization path:

- `concept_gates`
- `chapter_queue`
- `revision_recommendations`
- `verification_items`
- `rights_log`
- `manuscript_builds`
- `release_candidate_records`
- `release_packets`

The Sprint 12 workflow uses `release_candidate_records` so it does not collide with an older `release_candidates` table already present in the Pilot database. Inspection reads a safe summary from that legacy table when its old schema is present; it does not migrate or rewrite it. New verification/build/release inspection sections tolerate databases where those newer tables are absent.

## CLI and inspection changes

- Concept: `kdp concept ...`; `kdp inspect concept TITLE_ID`.
- Chapters: bounded queue, status, pause/resume, next-chapter draft, and summary commands under `kdp chapters`.
- Editorial: `kdp editorial run --pass` supports the five new structured passes alongside developmental analysis; `kdp editorial recommend`; `kdp inspect editorial`.
- Verification and rights: `kdp verify scan-scripture|add-flag|decide`; `kdp rights add|decide`; `kdp inspect verification`.
- Build: `kdp build manuscript|matter-add|matter-accept`; `kdp inspect builds`.
- Release: `kdp release candidate|check|review|packet`; `kdp inspect release`.
- Workspace: `kdp workspace dashboard` writes `reports/operator-workspace.html` by default.

Inspection and doctor checks were extended for the new prompts, tables, workflow state, blockers, and artefact hashes. Inspection remains read-only and includes legacy-table guards.

## Prompts and tests

Sprint 7 added six concept prompt templates. Sprint 8 updated chapter draft/revision prompts to include supplied planning and prior-summary context. Sprint 9 added five versioned editorial prompts. No Sprint 10–13 provider prompt templates were needed.

Tests use fake or local fixture providers. The final suite result was **102 passed** (`pytest -v`). Sprint boundary results were 86 (Sprint 7), 88 (Sprint 8), 91 (Sprint 9), 96 (Sprint 10), 98 (Sprint 11), 100 (Sprint 12), and 102 (Sprint 13) passing tests. `git diff --check` completed without whitespace errors.

The final pilot dry run completed successfully with zero inspection inconsistencies. The Sprint 13 dashboard CLI smoke command completed against the existing local workspace and generated an HTML report for 2 projects and 2 titles. The report was written to a temporary path outside the repository.

## Known limitations and deferred work

- Provider/model pricing is still unconfigured in the repository; historical and future usage costs may remain unknown.
- Scripture verification records references, translation/source policy, evidence, and human decisions. It does not supply or verify verse wording automatically; no Scripture quotation source/licensing workflow is implemented.
- Claim verification and rights/licensing decisions require human-supplied evidence and judgment. The system does not provide legal, theological, or expert determinations.
- DOCX and EPUB export are deferred. Markdown is the implemented deterministic export.
- The release checklist is a human review structure. It does not hard-code unstable KDP policy or independently establish current KDP compliance.
- Release approval authorizes only the reviewed candidate for manual KDP action. Upload and publication remain human-controlled and are not automated.
- The operator workspace is static and read-only. There is no local web server, authentication layer, or interactive state-changing interface.
- Chapter work remains deliberately bounded and per-chapter; there is no blind whole-book generation or multi-chapter autonomous orchestration.

## Safety boundaries preserved

- No real provider calls were made during Sprints 7–13.
- No API keys, tokens, headers, or provider secrets were printed or committed. The dashboard reports readiness without exposing environment-variable names or values.
- AI-generated concepts, chapters, analyses, builds, and packets remain experimental until the existing explicit human workflows accept them.
- Canon proposals remain human-review only. No AI output is auto-approved.
- Scripture placeholders, verification flags, rights records, and release blockers remain visible through the build and preflight stages.
- No KDP upload or publication automation was added, and no branch was merged to `main`.

## Human review checklist

1. Review the complete branch diff and commit sequence before merging.
2. Review concept decisions and chapter-by-chapter summaries before continuing manuscript work.
3. Resolve Scripture placeholders against the project’s approved translation and licensed source; keep exact references and evidence attached.
4. Review source/claim, expert/sensitivity, and rights records with appropriate human reviewers.
5. Rebuild after any accepted manuscript or verification-state change, then create a new release candidate so its hashes are current.
6. Verify current KDP requirements against official KDP documentation and complete the metadata, rights, and AI-use disclosure checks.
7. Keep final KDP credentials, declarations, upload settings, and publication actions with the human operator.
