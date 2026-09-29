# Workspace UX recommendations

Evidence: `evidence/ui/*.png` (8 pages × 1440×900, 1024×768, 768×1024, 390×844, plus dark theme), `evidence/ui/a11y_report.json` (axe: **0 violations**; overflow at 768 px on every page and at 390 px in the editor; up to 16 raw IDs visible per page).

## Prioritised UX defects

| # | Defect | Impact | Effort |
|---|---|---|---|
| U1 | "Operator name" / "Your name" asked on ~15 forms of the title page | friction; invites inconsistent names that fragment the audit trail | S (replace with authenticated identity, AUD-001) |
| U2 | Raw IDs (`AST-20260929-9F00BBAD`) used as the primary label in lists, selects and notices | non-technical operators cannot tell a positioning from an outline | S |
| U3 | No way to replace an accepted chapter; condition text promises a later fix that doesn't exist | dead end on the pilot book | M (AUD-004 + UI) |
| U4 | Developmental analysis offered as review aid though the model never saw the chapter | misleading | S (AUD-005 patch) |
| U5 | Review page doesn't show finish reason / truncation / refusal | operator may accept a cut-off chapter | S |
| U6 | Editor: 413 page on large edits loses text; content stripped; 100 KB cap undocumented | data loss | M |
| U7 | Python literals leak ("hard budget: True"), sprint jargon, state names in caps | polish | S |
| U8 | Horizontal overflow at 768 px; editor at 390 px | tablet use | S |
| U9 | Double-submit guard only on generation forms | duplicate decisions are rejected by review_hash, but the operator sees an error | S |
| U10 | Flash notices are in-memory; lost on restart and consumed by whoever loads the URL first | confusion after restart | S |
| U11 | `KDP_EXCEPTION`/`UPDATE_ASSESSMENT` have no guidance or exits | stuck states | S (docs) + M (edges) |
| U12 | Error pages reuse the "Not found" template for 400/403/409/413/415/422/503 | wrong mental model | S |

## Recommendations with low-fi wireframes

**R1 — Identity bar instead of name fields.** Header shows "Signed in as ann@tailnet (reviewer)"; all forms drop the name field.

```
┌ KDP Workspace ─────────────── Search [      ] ── ann@tailnet · reviewer ─┐
```

**R2 — Human labels first, IDs second.** `Positioning brief · accepted 29 Sep · v1` with the ID in a copy-to-clipboard chip.

**R3 — Chapter card with version timeline and "Replace accepted version".**

```
Chapter 1 — "Faith and First Customers"            [Accepted v2]
  v1 draft (AI)  ─ v2 manual edit (AI+human) ─ ★ accepted 29 Sep by ann
  Conditions: [SCRIPTURE NEEDED] line 12 → verification VRF-… pending
  [Open review]  [Replace accepted version…] (requires reason; old version archived)
```

**R4 — Generation result panel** shows: tokens, cost, finish reason (red if not `stop`), whether the context the manifest lists was included (✓ per input), and a "Re-run deliberately" button after failures (AUD-013 patch).

**R5 — Release readiness as a checklist with owners**, grouped: Manuscript · Verification · Rights · Metadata · AI disclosure · KDP settings; each row shows who checked it and blocks self-approval visibly ("You prepared this candidate; another reviewer must approve").

**R6 — Editor**: client-side size meter against the real limit, autosave draft to `localStorage` (per-viewer convenience only), server returns 422 with the submitted text on any validation error, no stripping of content.

**R7 — Next-step banner per title** derived from `chapter_status.next_chapter` and state: "Next: accept a chapter card for chapter 3".

**R8 — Consistent error page** with status-specific copy ("The database is busy — nothing was saved; reload in a moment").

**R9 — Plain-language state names** in UI ("Ready for release review" for `HUMAN_RELEASE_REVIEW`), with the code in a tooltip.

**R10 — Stack decision:** keep the stdlib server for single-owner loopback use; before a second operator, move to a small framework (Starlette/FastAPI + Jinja2 autoescape) behind the authenticating proxy — templates, middleware for identity/logging/errors, and a real test client. The current string-built HTML is correct today but relies on discipline (`REFACTOR_PLAN` step 5).
