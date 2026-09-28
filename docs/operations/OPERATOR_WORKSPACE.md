# Operator workspace

Sprint 14 adds a local interactive Workspace backed by SQLite inspection. Sprint 15 adds
explicit verification, chapter queue, Markdown build, and release preparation actions.
Each action calls the existing audited service; the Workspace does not write operational
state directly.

Start it from the repository root:

```powershell
kdp workspace serve
```

The server binds only to `127.0.0.1` (port `8765` by default). Open the printed local address
in a browser and stop the server with `Ctrl+C`. Use `--port` to choose another local port.
The Workspace lists work needing review, approval, verification, or unblocking first, followed
by ready titles, recent activity, projects, and titles. Project and title pages show the
existing provider/budget, planning, chapter, editorial/canon, verification/rights, build, and
release inspection data. Light, dark, and brand themes are available; status meaning is also
shown in text.

On a title page, **Workflow actions** can scan accepted chapters for Scripture placeholders,
add verification flags or pending rights records, queue/pause/resume chapter work, build a
Markdown manuscript, create a release candidate from a selected build, and export its review
packet. Queue controls never draft chapters. Scanning does not verify Scripture or edit text.
Builds and candidates retain blockers. The forms ask for an operator name where the audited
service needs one; this name is an audit label, not authentication. The server is local only,
uses a per-run form token, and rejects requests from a different origin. The Sprint 15 forms
prepare work for the human review pages described below.

## Human review and approvals

Sprint 16 adds review links in the attention queues and title records. Each review page shows
the exact artefact or candidate snapshot, provenance, linked findings, current blockers,
existing conditions, and the effect of each decision before the form. The complete text of
an approvable content artefact is displayed only after its registered file hash is checked.
If the file is missing, altered, outside the workspace, unreadable, or over 1 MB, browser
acceptance is disabled. The normal CLI and service integrity checks still apply.

The review form carries a hash of the displayed context. If another action changes the
artefact, findings, checklist, or blockers, the old form is rejected and the operator must
reload and review the current state. Decisions require a named reviewer and an explicit
acknowledgment of the consequences. A successful decision redirects to the updated record
and displays the exact accepted asset and approval ID, proposal status, verification state,
or release state. No decision is submitted by opening a page.

Concept, planning, and chapter acceptance can record up to five conditions (one per line).
A chapter with `[SCRIPTURE NEEDED]` always retains an explicit Scripture verification
condition when accepted through the Workspace. Conditions remain visible in inspection and
release blockers. Canon proposals have explicit accept/reject choices; the existing service
records the decision and does not directly mutate the canon ledger. Release review has
human checklist forms and explicit approve/hold/reject choices. Approval is disabled while
blockers remain, and final KDP upload and publication stay manual. Verification and rights
review pages use the existing human decision services and evidence requirements. There is
no Workspace authentication; reviewer names are audit labels. Keep the local server on a
trusted workstation.

If the database is absent, the Workspace shows `kdp init-db` guidance and does not initialize
the database itself.

## Static HTML export

Generate a local, static Workspace snapshot with:

```powershell
kdp workspace dashboard
```

By default it writes `reports/operator-workspace.html`. Use `--output` to choose another local
path. Open the HTML file in a browser after generation.

The static export combines existing read-only inspection services. It summarizes project and
title state, provider readiness, budget and usage, concept/planning state, chapter progress,
editorial findings and canon proposals, verification blockers, manuscript builds, release
candidates, and human review queues. The export has no server, JavaScript, provider calls, or
state-changing controls.

The report does not include API-key environment variable names or values, raw prompts, provider
response bodies, or provider headers. It is a status summary, not an approval surface; use the
audited CLI workflows for any state changes.
