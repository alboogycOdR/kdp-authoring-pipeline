# Design: deterministic DOCX/EPUB export stage (proposal only)

Status: proposal for an ADR (ROADMAP lists DOCX/EPUB as a "possible later milestone"). Not implemented.

## Why
KDP accepts EPUB, DOCX and KPF for eBooks and PDF/DOCX (among others) for paperbacks (index-extract of [G200634390](https://kdp.amazon.com/en_US/help/topic/G200634390) and [G202145060](https://kdp.amazon.com/en_US/help/topic/G202145060), retrieved 2026-09-29). The pipeline ends at Markdown, so every title needs an unaudited manual conversion — the exact place where content, headings, Scripture notices and front matter get silently altered.

## Shortest defensible path
Pandoc (pinned version, invoked as a subprocess, no network) from the **frozen build manuscript** of an approved release candidate:

```
kdp export epub  CANDIDATE_ID   -> 11_release/candidates/<id>/book.epub
kdp export docx  CANDIDATE_ID   -> 11_release/candidates/<id>/manuscript.docx
```

Inputs: `manuscript.md` (hash from the build), `export-metadata.yaml` generated from captured metadata (title, subtitle, author, language, rights notice, AI-use statement not included in book text), a pinned `reference.docx` / `epub.css` stored as versioned assets with hashes.

## What breaks in the current Markdown (observed in builds)
1. The build inserts raw HTML anchors (`<a id="chapter-001"></a>`) — Pandoc keeps them in EPUB but they are noise in DOCX; replace with Pandoc header attributes `# Title {#chapter-001}`.
2. The TOC is a Markdown list of links — KDP generates navigation from EPUB nav/DOCX headings; drop the handwritten TOC in export and use `--toc`.
3. `---` separators between sections render as horizontal rules; use `\newpage`-equivalent (`<div style="page-break-before: always">` in EPUB, section breaks in DOCX via reference doc styles).
4. Chapter headings are whatever the model wrote (`# Chapter One: …`); heading levels are not validated — add a lint: exactly one H1 per chapter, no H1 inside bodies.
5. No front/back matter structure (copyright page, Scripture permission notices, AI-use internal record) — add `front-matter.yaml` capture.
6. Images: none supported (`08_art/` unused); cover handled separately (KDP cover upload), not embedded.
7. Footnotes/Scripture references: plain text; decide on Pandoc footnotes `[^1]` and add verification-item links.

## Determinism requirements
- Pin Pandoc version; record `pandoc --version` hash in the export manifest.
- `SOURCE_DATE_EPOCH` set from the candidate's `created_at` so EPUB zip timestamps and `dc:date` are stable; `--epub-metadata` fixed; zip with sorted entries (post-process with `zip -X` ordering or Python `zipfile` rewrite).
- DOCX: strip `docProps/core.xml` timestamps / set from candidate; sort parts.
- Export manifest: input hashes (manuscript, metadata, reference doc, css), tool version, output hash; stored as an asset with provenance `creator_type="system"`.

## Tests
- Golden-file tests: same candidate → byte-identical EPUB/DOCX across two runs and across LF/CRLF inputs.
- `epubcheck` (pinned) must pass with zero errors.
- Round-trip: extract text from EPUB/DOCX; normalised text must equal build manuscript text minus markup (catches dropped paragraphs like AUD-032).
- Placeholder/unfinished-text scan runs again on exported text.

## Gates
Export only from a candidate with `approved_for_manual_kdp_action` and zero blockers; export records an audit event; the packet lists the exported files and hashes. Upload remains manual.

## Packaging prompts (`prompts/packaging/` is empty)
Blurb, keyword and category suggestions are currently produced outside the tool, unaudited. Add `packaging/description`, `packaging/keywords` (≤7 phrases), `packaging/categories` (≤3) prompt families whose outputs are experimental assets, validated deterministically (counts, banned subjective/time-sensitive terms per KDP keyword guidance), and accepted into the candidate's metadata checklist with provenance.
