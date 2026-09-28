# Version 0.3 — Production Readiness Report

**Date:** 2026-09-28

**Branch:** `feat/v0.3-production-readiness`

**Pilot:** `PRJ-20260927-4201C302` / `BK-20260927-5D879BDB` — *A Practical Devotional for Young Christian Entrepreneurs*

## 1. Milestone summary

### Milestone 1 — Provider production readiness

- Confirmed the project selects enabled profile `openai-main-authoring-low`, model `gpt-5`, with 4,000 default output tokens, low reasoning effort, and a 180-second read timeout. `kdp providers check` reported configuration ready with `connected: false`; no connection check was requested.
- Pricing remains unset. The project budget is $5/month and $0.50/run in soft-stop mode. Usage reports 26,685 input tokens, 18,408 output tokens, 11 events with unknown cost, and $0 known USD cost. The zero is known cost only; actual cost is unknown for those events.
- Added an operator hint when `kdp pricing list` returns no rows. It explains that costs remain unknown and shows the configuration syntax without supplying or estimating rates. Added a provider readiness section to the pilot runbook.
- The offline `doctor` reports an older separate project with no selected provider and warns about unpriced Pilot usage. Both include operator actions. No profile or budget settings were changed.

When the operator supplies current official values for the exact provider and model, the syntax is:

```powershell
kdp pricing set openai-main-authoring-low gpt-5 `
  --input-usd-per-million INPUT_RATE `
  --output-usd-per-million OUTPUT_RATE `
  --cached-input-usd-per-million CACHED_INPUT_RATE
```

`INPUT_RATE`, `OUTPUT_RATE`, and optional `CACHED_INPUT_RATE` are placeholders for operator-verified numeric USD-per-million-token rates. Do not run this command until those values are supplied. Pricing does not retroactively establish the exact cost of historical usage.

### Milestone 2 — Verification readiness

The existing accepted Chapter 1 is tied to human-review records. The Scripture scan returned the existing pending item without creating a duplicate. Nothing was verified, and no manuscript text changed.

- Scripture: `VRF-20260928-2D5AB5A1`, pending; `[SCRIPTURE NEEDED]` remains unresolved.
- Source/claim: `VRF-20260928-7014CE3E`, pending. The current service uses one combined `source_claim` kind rather than separate source and claim kinds.
- Research: `VRF-20260928-759DAA6D`, pending.
- Rights: `RGT-20260928-C6100DBF`, pending.

The workflow records reviewer, rationale, and evidence for decisions; it does not make those decisions automatically. Inspection surfaces all four records as blockers.

### Milestone 3 — Publication readiness rehearsal

- Created Markdown build `BLD-20260928-F6F0967F` from the accepted Chapter 1 only. It is blocked with six blockers: the Scripture placeholder, its pending verification, pending source/claim and research review, pending rights review, and the accepted chapter’s Scripture condition.
- The build includes `AST-20260928-FF415461`, accepted Chapter 1, with SHA-256 `b5049e08b20c278ff0b5eaf025a53e6544aa13b16135cf7931258449a344e97f` and provenance `PROV-20260928-B657D641`.
- Build output SHA-256 is `fcde4ff93e13d03e23acc1c8fc51b88643230943cddeb1d7aa7c5c52bfea92e1`; manifest SHA-256 is `f1f23767c0a6d022ce9ea35ce331a6feb4f8d507f50ae994b1c88f90a23ac532`. All registered Markdown builds have the same output hash, confirming deterministic manuscript content. Per-build manifests differ because they record each build ID and creation time.
- Created release candidate `REL-20260928-DAD5B5F9`, blocked, and packet `PKT-20260928-2AEA5FFB`, SHA-256 `9b15cbf0d94fbd02343d81961a62f4f35d1504d0b7de8ad46cab8e8db6ab5f78`. The packet has 22 blockers, no approval ID, and remains human-review only. KDP upload/publication remains a manual human action.
- Generated dashboard at `%TEMP%\kdp-v0.3-production-readiness.html`. It lists both projects/titles, provider and budget status, 11 unknown-cost events, verification blockers and IDs, builds, candidates, and human review queues. The Pilot 1B project’s known USD cost is distinguished from its unknown-cost event count.

### Milestone 4 — Operator readiness polish

The rehearsal confirmed that the CLI, inspection, verification, build, release, and dashboard flows expose the expected state and block release. The only reproduced friction was the empty pricing list providing no next step; the CLI and runbook now explain how to proceed using operator-supplied current pricing. No other changes were justified.

### Milestone 5 — Defect sweep

The pricing guidance change is covered by a CLI regression test. The complete suite, isolated fake-provider pilot dry run, and whitespace check all passed. No production data, accepted chapter, approval, or pricing configuration was altered.

## 2. Production-readiness improvements

- Empty pricing output now clearly reports that usage costs remain unknown and points to `kdp pricing set` with placeholders, without suggesting values.
- The pilot runbook now documents offline provider checks, pricing inspection, budget/usage inspection, and the need to confirm exact current official rates.
- Rehearsal confirmed blocker IDs, content hashes, accepted-asset provenance, release gating, and dashboard summaries remain aligned.

## 3. Files changed for Version 0.3

- `src/kdp_pipeline/cli/app.py`
- `tests/integration/test_cli.py`
- `docs/operations/PILOT_WORKFLOW.md`
- `docs/operations/V0_3_PRODUCTION_READINESS_REPORT.md`

Pre-existing documentation edits and untracked files in the checkout were preserved and excluded from the Version 0.3 commits.

## 4. Commands executed

- `.venv\Scripts\kdp.exe --help` and focused command `--help` checks for providers, pricing, inspection, verification, build, release, and dashboard.
- `.venv\Scripts\kdp.exe providers list`
- `.venv\Scripts\kdp.exe providers check openai-main-authoring-low` (offline; no `--connect`)
- `.venv\Scripts\kdp.exe pricing list --provider-id openai-main-authoring-low`
- `.venv\Scripts\kdp.exe inspect provider BK-20260927-5D879BDB`
- `.venv\Scripts\kdp.exe inspect usage BK-20260927-5D879BDB`
- `.venv\Scripts\kdp.exe inspect budget BK-20260927-5D879BDB`
- `.venv\Scripts\kdp.exe inspect verification BK-20260927-5D879BDB`
- `.venv\Scripts\kdp.exe inspect title BK-20260927-5D879BDB`
- `.venv\Scripts\kdp.exe doctor`
- `.venv\Scripts\kdp.exe verify scan-scripture BK-20260927-5D879BDB` (existing item confirmed; no duplicate)
- `.venv\Scripts\kdp.exe build manuscript BK-20260927-5D879BDB --builder v0.3-rehearsal`
- `.venv\Scripts\kdp.exe release candidate BK-20260927-5D879BDB BLD-20260928-F6F0967F --creator v0.3-rehearsal`
- `.venv\Scripts\kdp.exe release packet REL-20260928-DAD5B5F9 --creator v0.3-rehearsal`
- `.venv\Scripts\kdp.exe workspace dashboard --output %TEMP%\kdp-v0.3-production-readiness.html`
- Read-only reduced inspection of the Pilot title’s build, release, verification, provider, usage, and provenance state.
- `.venv\Scripts\pytest.exe -v tests/integration/test_cli.py`
- `.venv\Scripts\pytest.exe -v`
- `.venv\Scripts\python.exe scripts\pilot_dry_run.py`
- `git diff --check`
- `git status --short --branch`

## 5. Tests

- Focused CLI tests: **5 passed**.
- Full suite: **104 passed** in 142.17 seconds.
- `scripts/pilot_dry_run.py`: **passed** in a temporary workspace using the deterministic `FakeProvider`; zero inspection inconsistencies. It made no external provider request and did not alter Pilot 1B content.
- `git diff --check`: **passed**.

## 6. Publication rehearsal result

The accepted manuscript builds deterministically and retains asset hashes and provenance. The new build, release candidate, and packet are all blocked as expected. Verification, rights, metadata, AI-use disclosure, KDP checklist, and the Scripture approval condition remain human review work. No release approval, KDP upload, or publication occurred.

## 7. Operator workflow observations

- Offline provider readiness is distinguishable from connectivity: the profile is configuration-ready while `connected` remains false.
- Provider and budget inspection show profile/model selection, token usage, known USD cost, unknown-cost counts, and soft-stop policy without exposing credential values.
- The dashboard labels known USD cost separately from unknown usage and lists verification IDs. The pending source/claim item is one combined review kind.
- `doctor` also identifies the older unconfigured project; an operator must select a profile before generating content for it.
- The failed historical continuity attempt is visible as unusable/unverified; its finding remains open and its canon proposal remains superseded. A separate valid continuity proposal remains proposed for human review.

## 8. Remaining known limitations

- Provider/model pricing remains unset; all 11 historical Pilot usage costs remain unknown. The configured soft budget can permit unpriced generation, with warnings. An operator should supply official rates and decide whether a hard stop is appropriate before future real-provider work.
- Chapter 1’s Scripture reference, source/claim, research, and rights records remain pending human review.
- The Pilot title remains `DRAFTING`; its release candidate is blocked and unapproved.
- Separate source and claim record kinds are not available; both use `source_claim`.
- Current KDP rules, metadata, AI-use disclosure, and final upload settings still require human research and decisions.
- DOCX/EPUB export, automated KDP upload/publication, and other work outside the completed backend scope remain unavailable or intentionally manual.

## 9. Intentionally deferred

Pricing values, content/rights/Scripture decisions, release approval, DOCX/EPUB, new AI workflows, frontend/UI, authentication, Sprints 15–16, and any KDP upload/publication work were not performed. No provider calls were made.

## 10. Recommendation regarding Sprint 14

**READY TO BEGIN SPRINT 14.** The backend workflows needed by an operator frontend have been exercised: state remains authoritative in SQLite, artefacts retain hashes and provenance, verification and release decisions remain human-gated, and blockers are surfaced through inspection and the dashboard. The Pilot is still not publication-ready; Sprint 14 should present unknown pricing and all pending human-review blockers clearly and must not turn them into automatic decisions.

## 11. Safety confirmation

- **Real provider calls:** none. Provider checks were offline; the pilot dry run used `FakeProvider` in an isolated temporary workspace.
- **Secrets:** no secret values were printed or recorded in this report.
- **KDP upload/publication:** none performed or added.
- **Architecture:** no redesign, schema change, or new workflow system was introduced.
- **Pilot 1B content:** no manuscript text, planning artefact, approval, verification decision, or pricing record was changed. Rehearsal build/release records were added as blocked artifacts.
- **Repository workflow:** work was committed and pushed on `feat/v0.3-production-readiness`; no merge to `main` occurred.
