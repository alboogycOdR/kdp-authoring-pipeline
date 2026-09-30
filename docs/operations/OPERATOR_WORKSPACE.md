# Operator workspace

Sprint 14 adds a local interactive Workspace backed by SQLite inspection. Sprint 15 adds
explicit verification, chapter queue, Markdown build, and release preparation actions.
Each action calls the existing audited service; the Workspace does not write operational
state directly.

## Start and author a book in the browser

The **Help** link in the Workspace header opens a visual, plain-language guide at `/help`.
It takes a new creator from saving an idea through concept, planning, chapter drafting,
verification, and release preparation without requiring CLI or server access.

The current server requires an administrator-configured single operator account before the
Workspace can be used. There is no public sign-up page or browser password-reset flow. Generate
a password hash from a local console with:

```powershell
kdp workspace password-hash
```

The password is entered without echo and must be at least 14 characters. Generate a separate
session-signing secret with `kdp workspace session-secret`. Configure both generated values
and the chosen username in the service environment as `KDP_WORKSPACE_PASSWORD_HASH`,
`KDP_WORKSPACE_SESSION_SECRET`, and `KDP_WORKSPACE_USERNAME`, then start or restart the
Workspace. Keep the environment configuration in the operating system's protected secret
store, outside the repository and project artefacts. Capture command output directly into a
protected setting rather than leaving it in terminal scrollback. Changing either secret
invalidates existing sessions.

After signing in, actions are recorded under the configured username (or the trusted
`KDP_WORKSPACE_OPERATOR_HEADER` identity when that additional proxy check is configured).
The login offers a browser-session cookie that expires on browser close and on the server
after 12 hours, or **Remember me** for 30 days. Cookies are `HttpOnly` and `SameSite=Strict`.
For an HTTPS deployment set `KDP_WORKSPACE_COOKIE_SECURE=true`; this makes the browser require
HTTPS to send the session cookie. If no account is configured, Workspace routes fail closed
with a safe setup message. A partial or malformed configuration prevents server startup.

The Workspace home page now starts with **Start a new book**. Enter a project name, working
title, intended reader, and starting idea. Select a ready, priced provider and choose monthly
and per-request USD hard limits. Creation saves a human-authored idea note, project, title,
provider selection, and budget without making a provider call. A project page can also add a
title or change its provider and hard limits. An existing new title can save its idea on its
title page. Browser users need no CLI or server access for these tasks.

Open the new title and use **Book authoring** in order: develop and validate a concept, review
and accept its concept brief, generate and accept positioning, brief, outline, and chapter
cards, advance the planning gates, then draft one chapter at a time. Continuity,
developmental, and other editorial passes are available for an experimental chapter.
**Edit in browser** creates a new experimental manual revision of a concept, planning
artefact, or chapter while retaining the original and provenance. Review pages remain the
only browser acceptance path. A chapter summary can carry context into later chapter work.

Every browser generation form identifies that it calls the selected provider, requires the
operator's name and an explicit cost acknowledgment, and checks for configured model pricing
and a hard-stop project budget before calling. Each request and resulting job are audited.
The profile, known cost, unknown-cost events, and budget limits remain visible on the title.
The provider's billing report is authoritative for charges. Failed or unclear requests must
be inspected before any deliberate retry.

After authoring, the existing title actions and review pages cover Scripture/source/claim/
research verification, rights, Markdown build, release candidate, review packet, and human
release review. Browser actions never supply evidence or approve automatically. Final KDP
upload and publication remain manual outside the Workspace.

Start it from the repository root:

```powershell
kdp workspace serve
```

The server binds only to `127.0.0.1` (port `8765` by default). Open the printed local address
in a browser and stop the server with `Ctrl+C`. Use `--port` to choose another local port.
The Ubuntu staging installation keeps this loopback binding behind a Tailscale-bound proxy.
Its URL, service names, and data boundary are recorded in the [environment runbook](ENVIRONMENTS.md).
The current deployed staging revision must not be assumed to include this login feature until
the reviewed code is deployed with a configured account and HTTPS cookie protection.
The Workspace lists work needing review, approval, verification, or unblocking first, followed
by ready titles, recent activity, projects, and titles. Project and title pages show the
existing provider/budget, planning, chapter, editorial/canon, verification/rights, build, and
release inspection data. Light, dark, and brand themes are available; status meaning is also
shown in text.

On a title page, **Workflow actions** can scan accepted chapters for Scripture placeholders,
add verification flags or pending rights records, queue/pause/resume chapter work, build a
Markdown manuscript, create a release candidate from a selected build, and export its review
packet. Queue controls never draft chapters. Scanning does not verify Scripture or edit text.
Builds and candidates retain blockers. The Workspace records the signed-in account for
auditable actions, uses per-run form protection, and rejects requests from a different origin.
The Sprint 15 forms prepare work for the human review pages described below.

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
review pages use the existing human decision services and evidence requirements. All decisions
remain human-gated. Keep local development on loopback; authentication does not replace HTTPS
or restricting staging ingress to the intended operator.

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
