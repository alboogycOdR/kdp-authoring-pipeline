# Sprints 14–16 Operator Workspace report

Branch: `feat/sprints-14-16-operator-frontend`

## Sprint 14 — Workspace foundation

- Added a local server bound to `127.0.0.1` and SQLite-backed project/title inspection.
- Put Needs Review, Needs Approval, Needs Verification, Blocked, Ready, and Recent Activity ahead of project and title directories.
- Added accessible light, dark, and brand themes with textual status labels.
- Displayed provider/budget, planning, chapter, editorial/canon, verification, build, release, and approval-condition state without secrets.

## Sprint 15 — Explicit workflow actions

- Added title-page forms for Scripture placeholder scans, verification flags, pending rights records, chapter queue control, Markdown builds, release-candidate creation, and review-packet export.
- All mutations call existing audited services. Queue actions do not draft chapters. Builds and release candidates retain blockers.
- Added local Host/Origin checks, a per-server form token, bounded form input, and a redirect after successful actions.

## Sprint 16 — Human review and approval

- Added direct links from queues and title records to review pages for concept/planning/chapter artefacts, canon proposals, release candidates, verification items, and rights records.
- Each page presents the artefact, provenance, findings, blockers, conditions, and consequences before its decision controls. Artefact and build manuscript text is shown only after file/hash checks; browser approval is unavailable if a file is unreadable, outside the workspace, or over 1 MB.
- Decision forms require a named reviewer, explicit consequence acknowledgment, and a hash of the displayed review context. A stale form is rejected and must be reloaded. The result page states the exact accepted asset/approval ID or resulting review state.
- Added optional, validated approval conditions to the existing concept, planning, and chapter acceptance services. The Workspace carries an unresolved `[SCRIPTURE NEEDED]` condition into chapter acceptance and surfaces conditions in Needs Verification instead of presenting the title as Ready.
- Marked findings from invalid or unverified continuity attempts as suspect in the attention queue. Blocked release candidates link directly to their review page.
- Added human release checklist forms and explicit approve/hold/reject choices. Approval stays disabled while blockers remain. Canon decisions use the existing service and do not directly mutate the ledger. Verification and rights decisions use their existing evidence and audit rules.

## Verification

- Sprint 14/15/16 integration tests cover route safety, form tokens, stale review state, complete decision context, condition recording, audit paths, blocked release review, and a fully checked human release approval fixture.
- A local headless Chrome visual check covered the Pilot 1B Workspace attention page and a canon review page. The canon proposal display was adjusted to separate current value, proposed value, reason, and evidence.
- Full-suite result: `pytest -q` — 120 passed in 93.87 seconds.
- Pilot dry-run result: `python scripts/pilot_dry_run.py` — passed.
- `git diff --check` — passed; Git reported only line-ending conversion warnings.

## Boundaries and remaining limits

- No real provider calls, autonomous approvals, KDP upload, or publication were added. Tests use only the fake provider.
- The local server has no authentication; reviewer names are audit labels. Run it on a trusted workstation.
- Browser review limits a single displayed artefact to 1 MB. The CLI remains available for larger artefacts after external review.
- The existing services define which decisions exist: content artefacts have acceptance, canon has accept/reject, release has approve/hold/reject, and verification/rights have their existing decision sets. No new rejection state was invented for content assets.
- The static Workspace snapshot and CLI `dashboard` command remain read-only and backward-compatible.
- Working-tree documentation predating this track was preserved. No commit, push, or merge was performed as part of this report.
