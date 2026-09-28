# Manuscript build and export

Sprint 11 provides deterministic Markdown assembly from accepted chapter assets. Experimental
drafts are never included. Each build writes a manuscript and JSON manifest under the title’s
`09_build/experimental/` directory and registers the result as an experimental `manuscript.build`
asset. The manifest freezes input asset IDs, hashes, provenance references, output hash, status,
and blockers.

Optional front and back matter follow their own human gate:

```powershell
kdp build matter-add TITLE_ID front .\front-matter.md --creator EDITOR
kdp build matter-accept AST_ID --reviewer EDITOR
```

Build an assembly and inspect its state:

```powershell
kdp build manuscript TITLE_ID --builder EDITOR
kdp inspect builds TITLE_ID
```

The build generates a contents list from accepted chapter headings and orders chapter assets by
their accepted chapter number. It checks source hashes, approval records, and provenance. A
missing chapter, Scripture placeholder, unresolved verification item, rights record, or recorded
approval condition marks the build `blocked` and `release_eligible: false`. A blocked Markdown
assembly is retained for internal review; it does not clear blockers or make the manuscript
release-ready. Build status is not a release approval.
Every Sprint 11 build has `release_eligible: false` and `release_review_required: true`; release
eligibility is reserved for the human-gated release-candidate workflow.

Only Markdown export is implemented. DOCX and EPUB remain deferred until they can be added with
maintainable local dependencies and format-specific validation.
