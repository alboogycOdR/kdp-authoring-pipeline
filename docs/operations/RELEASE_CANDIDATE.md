# Release candidates and preflight packets

Create a candidate from a specific Markdown build. The candidate freezes the build and manifest
hashes, included asset IDs and hashes, metadata snapshot, rights summary, AI provenance summary,
and verification/rights state hashes:

```powershell
kdp release candidate TITLE_ID BLD_ID --creator EDITOR
```

Record metadata checks, AI-use disclosure, and current KDP checks with `kdp release check`.
Every completed check requires a reviewer, rationale, and evidence reference. AI disclosure
also requires the disclosure statement. The KDP checklist is intentionally a human checklist;
verify current requirements against official KDP documentation and record the source used.

Export a review packet at any point:

```powershell
kdp release packet REL_ID --creator EDITOR
kdp inspect release TITLE_ID
```

The packet contains the frozen inputs, build, metadata checklist, rights/provenance summary,
AI-use disclosure, KDP checklist, approval status, and unresolved blockers. Packets are durable,
hashed experimental assets; they do not publish or upload anything.

Request a release review only after the checklist is complete:

```powershell
kdp release review REL_ID approve --reviewer REVIEWER --rationale "Review decision"
```

The service refuses approval while any build, source, Scripture, rights, metadata, disclosure,
KDP-checklist, or stale-state blocker remains. Approval records bind to the frozen candidate and
the exact checklist state. An approved candidate is marked `approved_for_manual_kdp_action` and
retains the condition that final KDP upload and publication are manual human-controlled actions.
Changes to verification or rights state after candidate creation stale the candidate; create a
new build/candidate after the change.

The checklist is structural and does not encode changing KDP rules or provide legal advice.
