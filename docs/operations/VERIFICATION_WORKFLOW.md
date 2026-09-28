# Scripture, source, and rights verification

Verification records are human review work items. The workflow stores the text or claim to
check, its location, a decision, the reviewer, rationale, and evidence reference. It does not
insert quotations or decide legal or theological questions automatically.

## Scripture placeholders

Scan accepted chapter assets and queue each exact `[SCRIPTURE NEEDED]` placeholder:

```powershell
kdp verify scan-scripture TITLE_ID
```

The scan checks accepted-asset hashes, records a chapter and line locator, and is idempotent.
It does not change manuscript files. Resolve a placeholder only after a human verifies an
exact reference and the project’s translation/source policy against evidence:

```powershell
kdp verify decide VRF_ID verified --reviewer EDITOR --rationale "Reference checked" `
  --evidence-reference "approved source locator" --reference "Psalm 90:17" `
  --source-policy "Approved translation and licensed source"
```

Only reference and source policy are recorded. Verse text is never supplied by this command.
`not_verified` and `not_applicable` are auditable decisions; the latter requires a rationale.

## Claim and research flags

Create a source, research, expert-review, or sensitivity flag with `kdp verify add-flag`.
Each flag remains a release blocker until a reviewer records a supported decision and evidence.

## Rights log

Use `kdp rights add` to record an image, art, font, source, or other material and its source,
model/tool provenance reference where relevant, license basis, evidence, territory, term, and restrictions. Then use `kdp rights decide` to
record a human decision. Clearance requires a recorded legal basis and evidence reference.
This log preserves review information; it is not a legal determination.

Inspect verification items, rights records, legacy approval conditions, and unresolved release
blockers with:

```powershell
kdp inspect verification TITLE_ID
```

Build and release workflows must continue to treat pending or unresolved records as blockers.
Final platform and publication decisions remain human controlled.
