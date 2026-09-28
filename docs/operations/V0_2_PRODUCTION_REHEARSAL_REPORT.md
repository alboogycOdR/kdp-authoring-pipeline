# v0.2 Production Rehearsal Hardening — Final Report

**Date:** 2026-09-28
**Branch:** `feat/v0.2-production-rehearsal-hardening` (based on current `main`, after `v0.1-core-roadmap-complete`)
**Pilot:** `PRJ-20260927-4201C302` / `BK-20260927-5D879BDB` — *A Practical Devotional for Young Christian Entrepreneurs*
**Outcome:** Local production workflows were exercised and three narrow usability defects were fixed. The title remains blocked from release pending human review.

## 1. Milestone-by-milestone summary

### Milestone 1 — Provider Production Readiness

- Offline provider check returned ready with `connected: false`. The selected profile `openai-main-authoring-low` is enabled, selected for the Pilot 1B project, and consistent with model `gpt-5`.
- Profile defaults are 4,000 output tokens, low reasoning, and a 180-second read timeout. Other historical profiles are disabled and not selected.
- No pricing is configured for this profile/model. No price was invented or set. The configured budget is $5/month and $0.50/run, with soft-stop mode. Usage inspection reports 26,685 input tokens, 18,408 output tokens, 11 events of unknown cost, and $0 estimated cost; the $0 figure is not a claim that actual cost was zero.
- Safe diagnostics remain available. For example, the earlier failed editorial job records `finish_reason=length`, empty content, and 1,200 reasoning tokens. No provider request was made in this rehearsal.

### Milestone 2 — Verification Workflow

Used the accepted Chapter 1 asset `AST-20260928-FF415461`. The Scripture scan was idempotent and returned existing pending item `VRF-20260928-2D5AB5A1` at `chapter-001:line-0016`; it did not add a reference or change manuscript text.

Created pending human-review records for the other workflow paths:

- Source/claim review: `VRF-20260928-7014CE3E` (`source_claim`). The service uses one combined `source_claim` kind; there is no separate claim kind.
- Research review: `VRF-20260928-759DAA6D` (`research`).
- Authorship/rights review: `RGT-20260928-C6100DBF` (`manuscript_text`).

All remain pending, with no evidence, clearance, or automatic verification recorded. Each is surfaced as a release blocker.

### Milestone 3 — Production Rehearsal

Markdown build `BLD-20260928-B5B17DFB` includes the accepted Chapter 1 only and is **blocked**. Its output hash matches the file (`fcde4ff93e13d03e23acc1c8fc51b88643230943cddeb1d7aa7c5c52bfea92e1`); its manifest hash matches (`ebe3308e0011d66fd494ada6ee772fc7bfbc99c872235508ebfa30b0e01832f4`). The manifest records the accepted chapter asset and its input hash.

Release candidate `REL-20260928-BA66B4E2` and packet `PKT-20260928-E59F5631` were created as blocked preflight records. The packet hash matches its file. It has 22 unique blockers, no approval ID, and records `final_kdp_action_manual: true`. Pending items include Scripture, source/claim, research, rights, the accepted chapter’s Scripture condition, metadata checks, AI-use disclosure, and KDP checklist checks. No release approval, upload, or publication occurred.

### Milestone 4 — Operator Workflow

Title, verification, build, and release inspection exposed the accepted planning set, open findings, canon-proposal statuses, pending review records, build hashes, and release blockers. The generated static dashboard at `C:\Users\Nuburo\AppData\Local\Temp\kdp-v0.2-production-rehearsal-final.html` includes project/title state, provider and budget status, verification item IDs, builds, candidates, and human review queues. It remains read-only and exposes no secrets. Final inspection reported zero inconsistencies.

### Milestone 5 — Defect Sweep

Fixed only issues reproduced during the rehearsal:

1. Release candidate and packet blocker lists could duplicate the same pending verification or rights record copied from the build. Blockers are now deduplicated by stable record identity while preserving the first, more detailed entry; legacy candidate inspection is deduplicated too.
2. Dashboard verification summaries omitted record IDs. They now display the ID with blocker kind or detail.
3. `python scripts/pilot_dry_run.py` failed from an uninstalled checkout because `src` was not on `sys.path`. The script now adds the repository's local source directory before package imports.

Regression tests cover blocker uniqueness through candidate inspection and packet export, and dashboard IDs. No provider, schema, architecture, or UI redesign was introduced.

## 2. Defects discovered

- Duplicate pending verification entries inflated release blocker counts and packet contents.
- Dashboard verification summaries did not identify the records that operators needed to resolve.
- The required pilot dry-run command failed from a source checkout unless `PYTHONPATH=src` was set.
- Pricing remains unconfigured, so historical usage costs cannot be established from available records. This requires operator-supplied official pricing values, not a code change.

## 3. Defects fixed

- Deduplicated release blockers by stable identity in new candidate snapshots and current inspection/packet results.
- Added verification, approval-condition, and rights IDs to dashboard blocker summaries.
- Made the pilot dry-run script import the local source package without an environment workaround.

## 4. Files changed

- `src/kdp_pipeline/release/service.py`
- `src/kdp_pipeline/workspace/dashboard.py`
- `scripts/pilot_dry_run.py`
- `tests/integration/test_sprint12_release.py`
- `tests/integration/test_sprint13_dashboard.py`
- `docs/operations/V0_2_PRODUCTION_REHEARSAL_REPORT.md`

No database schema or accepted manuscript file changed. Verification records were added as pending, auditable human-review work items.

## 5. Commands executed

- Offline provider and pricing checks: `providers check openai-main-authoring-low` (without `--connect`), `pricing list --provider-id openai-main-authoring-low`, `providers show`, and `providers list`.
- Read-only inspections: `inspect provider`, `inspect budget`, `inspect usage`, `inspect title`, `inspect verification`, `inspect builds`, and `inspect release` for the Pilot 1B title; `budget show PRJ-20260927-4201C302`.
- Verification: `verify scan-scripture BK-20260927-5D879BDB` (existing item confirmed); `verify add-flag` for `source_claim` and `research`; `rights add` for pending manuscript-text review.
- Production flow: `build manuscript BK-20260927-5D879BDB`; `release candidate` for the rehearsal build; `release packet` for the candidate; `workspace dashboard --output <TEMP_PATH>`.
- `pytest -v tests/integration/test_sprint12_release.py tests/integration/test_sprint13_dashboard.py`.
- `pytest -v`.
- `python scripts/pilot_dry_run.py`.
- `git diff --check` and `git status --short`.

The dry-run script uses `FakeProvider` in a temporary isolated workspace; it does not call an external provider or create a book in the Pilot 1B project.

## 6. Tests executed

- Focused release/dashboard regression tests: **5 passed**.
- Full suite: **103 passed**.
- Pilot dry run: **passed**, with zero inspection inconsistencies.
- `git diff --check`: **passed**.

## 7. Final pytest result

`pytest -v` — **103 passed**.

## 8. Pilot dry run result

`python scripts/pilot_dry_run.py` — **passed** from the source checkout without setting `PYTHONPATH`; generated its fixture only in a temporary workspace and reported zero inspection inconsistencies.

## 9. Production rehearsal result

The existing Pilot 1B title was inspected end-to-end. One accepted planning set and one accepted chapter were present. The Markdown build, release candidate, and packet were generated with matching recorded hashes and remained blocked as expected. Dashboard and inspection surfaces showed pending review work. No inconsistencies were reported.

## 10. Remaining blockers

- A human must identify and verify an appropriate Scripture reference and approved source policy for `[SCRIPTURE NEEDED]`; no reference or verse text was supplied.
- Source/claim, research, and manuscript authorship/rights records remain pending human review.
- Provider/model pricing is unconfigured; 11 existing usage events have unknown cost. Configure it only after the operator supplies current official values. The project budget is soft-stop until an operator changes it.
- Release metadata, AI-use disclosure, and current KDP checklist entries remain pending.
- The title is still `DRAFTING`; the release candidate has no approval. Open findings remain; the superseded invalid-continuity proposal stays superseded, while the valid continuity proposal remains human-review only.

## 11. Intentionally deferred

No Scripture decision, source evidence, rights clearance, pricing, release checklist decision, or approval was fabricated. DOCX/EPUB, provider calls, content generation, new titles, UI redesign, Sprint 14–16 work, KDP upload, and publication were out of scope.

## 12. Recommendations for v0.3

- Obtain operator-approved pricing values, configure them, review unknown-cost history, and decide whether the Pilot project should use hard-stop budgeting before any further real-provider generation.
- Have qualified humans resolve the pending Scripture, source/claim, research, and rights records with evidence; then rebuild and create a fresh candidate so its frozen state is current.
- Review the metadata, AI-use disclosure, and KDP checklist against current official KDP documentation before any release approval.
- Consider separating source and claim review categories only if operator experience demonstrates a real need; the current combined `source_claim` workflow is functional.

## 13. Safety and architecture confirmation

- **Real provider calls:** none; provider readiness check was offline (`connected: false`).
- **Secrets:** no secret values were printed.
- **KDP upload/publication:** no upload or publication capability was added; final action remains manual.
- **Architecture:** not redesigned; no schema changes or new features were introduced.
- **Merge status:** branch pushed to origin and not merged to `main`.

**Readiness:** Ready for a human-supervised operator workflow rehearsal. Not ready for provider usage with known costs or for release approval/publication while the listed blockers remain. Version 0.3 work should wait for human approval.
