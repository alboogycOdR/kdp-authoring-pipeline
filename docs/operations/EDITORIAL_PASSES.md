# Editorial passes

Developmental analysis remains available through `kdp editorial run --pass developmental`.
Sprint 9 adds focused, analysis-only passes:

- `voice` — voice, warmth, humility, and audience fit
- `line` — sentence clarity, flow, repetition, and rhythm
- `copy` — spelling, grammar, punctuation, and consistency of mechanics
- `reader-experience` — comprehension, engagement, and reader effort
- `consistency` — alignment with accepted planning, chapter cards, and supplied prior-chapter summaries

Example:

```powershell
kdp editorial run TITLE_ID 1 --asset-id AST_ID --pass voice
```

Each focused pass sends the experimental chapter text and accepted positioning, book brief,
outline, and target chapter card as text. Relevant reviewed summaries for earlier accepted
chapters are included when present. The context manifest retains each asset reference and hash.
Outputs must satisfy the structured JSON contract and confirm that the supplied context was
read. Empty, malformed, or missing-context responses fail the job and do not create findings.
The generated analysis asset remains experimental.

Inspect results with:

```powershell
kdp inspect editorial TITLE_ID
```

Editorial findings are review items; they do not alter manuscript content or canon. A human
may bundle open findings into a revision recommendation:

```powershell
kdp editorial recommend TITLE_ID 1 --asset-id AST_ID --finding-id FND_ID --owner EDITOR
```

This records a recommendation only. It does not revise the source chapter, resolve findings,
accept content, or approve canon. Revision and acceptance continue through their separate
explicit workflows.
