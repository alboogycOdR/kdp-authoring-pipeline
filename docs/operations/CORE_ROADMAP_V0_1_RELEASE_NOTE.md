# Core Roadmap v0.1 Release Note

**Status:** Core roadmap through Sprint 13 complete
**Release scope:** Local authoring, review, verification, build, and release-preflight foundation. This milestone does not publish books to KDP.

## Completed sprints

- **Sprint 7 — Concept Validation Layer:** Optional, human-gated concept development for youth fiction and nonfiction/devotional titles, with backward compatibility for existing titles.
- **Sprint 8 — Multi-Chapter Orchestration:** Bounded chapter queues, pause/resume, per-chapter status, explicit chapter drafting, and reviewed summaries as context. Whole-book generation is not automatic.
- **Sprint 9 — Editorial Pass Expansion:** Structured voice, line, copy, reader-experience, and consistency passes, with invalid or incomplete output rejected before findings are registered.
- **Sprint 10 — Scripture / Source / Rights Verification:** Scripture-placeholder scanning, human verification decisions and evidence, research/expert/sensitivity flags, rights records, and release-blocker inspection.
- **Sprint 11 — Build & Export Pipeline:** Deterministic accepted-chapter Markdown assembly, contents generation, optional separately accepted front/back matter, and frozen input/output hashes.
- **Sprint 12 — Release Candidate / Preflight Packet:** Frozen candidates, metadata and AI-use disclosure records, a human KDP checklist, blocker evaluation, review, and hashed packet export.
- **Sprint 13 — Operator Workspace / Local UI Foundation:** Static, read-only dashboard built from inspection services to summarize project state and human review queues.

## Major capabilities

The system supports a local workflow from concept and planning through chapter-level drafting, continuity and editorial review, human acceptance, Scripture/source/rights tracking, deterministic Markdown builds, and release-candidate preflight. SQLite remains authoritative for operational state; durable manuscript and report files retain their provenance and hashes. Inspection and the local dashboard expose lifecycle state, blockers, and review work without making workflow decisions.

## Safety boundaries

- AI-generated concepts, drafts, analyses, builds, and packets remain subject to explicit human gates. Canon proposals remain human-review only.
- Invalid or missing-context analysis output is rejected before it can register findings or proposals.
- Scripture text is not inserted automatically. Verification flags, rights records, unresolved placeholders, and approval conditions remain visible as blockers.
- Release approval is tied to the reviewed candidate and checklist state; it authorizes only the human-controlled next step.
- Provider secrets are not exposed in inspection or dashboard output. The dashboard is read-only.
- KDP credentials, declarations, upload settings, and the final publication action remain with the human operator. No upload or publication automation is included.

## Known limitations

- Provider/model pricing is not configured, so usage cost may be unknown.
- Scripture verification records references, source policy, evidence, and human decisions, but does not automatically supply or verify verse wording; a quotation-source and licensing workflow is not implemented.
- Claims, expert/sensitivity concerns, and rights decisions depend on human-supplied evidence and judgment.
- Markdown is the implemented export format; DOCX and EPUB are deferred.
- The KDP checklist is a human review aid. It does not independently establish compliance with current KDP policy.
- The operator workspace is static and read-only, with no local server, authentication, or interactive state-changing controls.
- Chapter work is bounded and per chapter; there is no blind whole-book generation or autonomous multi-chapter run.

## What remains before real KDP publication

For each title, the operator still needs to complete and review the manuscript, resolve Scripture placeholders using the approved translation and licensed sources, document source/claim and rights evidence, and address every build and release blocker. After content or verification changes, rebuild and create a fresh release candidate so its hashes reflect the current accepted inputs. A human must verify current requirements against official KDP documentation, complete metadata, rights, and AI-use disclosures, and make all account declarations and upload choices. The human performs the final KDP upload and publication action.

The system does not automate or guarantee retailer acceptance, legal compliance, theological verification, or publication success.

## Recommended next operating workflow

1. Create or continue a title and complete its concept/planning gates; review and approve each decision as required.
2. Draft chapters through the bounded queue, one chapter at a time. Review supplied summaries and continuity implications before using them as later-chapter context.
3. Run the appropriate editorial passes and handle findings through human review and revision. Accept only reviewed manuscript assets with provenance.
4. Scan for Scripture placeholders; resolve references, translation/source policy, evidence, and decisions with qualified human review. Record claim, sensitivity, and rights evidence and decisions.
5. Inspect title, verification, rights, chapter, and approval state. Resolve blockers, assemble a Markdown build, and inspect its hashes and completeness.
6. Create a new release candidate from the current accepted content. Complete the checklist, inspect all blockers and disclosures, and review the frozen packet.
7. Verify current KDP requirements from official sources, then let the human operator handle account access, declarations, upload, and publication.

This is the v0.1 operating boundary: the pipeline prepares reviewable, traceable publishing materials; the human remains responsible for final compliance decisions and publication.
