# Pilot 1B Real-Provider Retrospective

**Project:** `PRJ-20260927-4201C302`
**Title:** `BK-20260927-5D879BDB` — *A Practical Devotional for Young Christian Entrepreneurs*
**Outcome:** One title progressed from concept and planning through acceptance of a single Chapter 1 manuscript asset.

## Objective and outcome

Pilot 1B exercised the real-provider authoring path while preserving human control over planning, continuity, revision, and acceptance. The accepted planning set is positioning, book brief, outline, and Chapter 1 card. Chapter 1 is accepted at `projects/PRJ-20260927-4201C302/titles/BK-20260927-5D879BDB/05_drafts/accepted/chapter-001.md` as asset `AST-20260928-FF415461`, under approval `APR-20260928-07CF378F`. The title remains `DRAFTING`; the approval explicitly records that `[SCRIPTURE NEEDED]` is unresolved and the chapter is not Scripture-complete or release-ready. Final inspection reported zero inconsistencies.

## Provider and artefact flow

The selected profile was `openai-main-authoring-low`, an OpenAI-compatible authoring profile. Low reasoning effort was needed because the earlier developmental editorial request exhausted its 1,200-token output cap entirely on reasoning (`finish_reason=length`) and returned no usable content. Sprint 6.5 removed the editorial service's hidden 1,200-token cap so the profile's 4,000-token default could apply. The profile's 180-second read timeout provided more room for longer reasoning/generation requests.

The successful artefact flow was: accepted positioning → accepted book brief → accepted outline → accepted Chapter 1 card → experimental Chapter 1 draft → valid continuity analysis → developmental editorial analysis → human manual revision → human review → accepted Chapter 1 asset. The manual revision applied two minor phrasing edits, preserved `[SCRIPTURE NEEDED]`, and retained provenance to the original, accepted planning assets, and both analyses. Acceptance copied the revision into the canonical accepted-chapter location, retained provenance, recorded the approval condition and audit events, and did not change the title's `DRAFTING` state.

## Failures and hardening

- The first continuity attempt technically succeeded but was unusable: source contents were absent from the provider request even though asset references appeared in the manifest. It incorrectly produced a finding and canon proposal. The subsequent valid run included actual draft and planning text and an explicit empty-baseline statement. Inspection marks the original attempt invalid/unverified and warns that its finding/proposal need human review; no canon proposal was approved.
- The first developmental editorial request returned empty content at the 1,200-token cap, with all output tokens used for reasoning. The empty-output guard rejected it, and no analysis asset, finding, revision, or acceptance was created. The retry after Sprint 6.5 produced a usable analysis.

Hardening delivered across the pilot:

1. **Sprint 6.1 — Empty-output hardening:** reject empty provider output and preserve failure/usage diagnostics without registering unusable content.
2. **Sprint 6.2 — Reasoning controls:** support configured reasoning effort for provider requests.
3. **Sprint 6.3 — Timeout/reservation hardening:** improve request timeout handling and budget reservation behavior.
4. **Sprint 6.4 — Continuity context/validity:** assemble actual source text alongside manifest provenance, require structured usable continuity output, and prevent invalid output from creating findings/proposals.
5. **Sprint 6.5 — Editorial provider defaults:** use the selected profile's output limit unless an explicit override is supplied and record safe effective-request diagnostics.

## Lessons and operating rules

- A manifest is provenance, not prompt context: verify that required source text reaches the provider request.
- Validate model output before creating findings, proposals, or accepted assets. A technically successful job can still produce unusable content.
- Respect profile defaults and capture effective settings and usage diagnostics; empty-output guards and audit trails are essential.
- Keep AI output experimental until reviewed and explicitly accepted. Preserve source hashes, lineage, approval conditions, and audit events.
- Make one real-provider call per authorized run, inspect the resulting job and artefacts, and do not automatically retry quality or policy failures.
- Treat canon proposals as human-review items; never infer approval from analysis or acceptance of a chapter.
- Keep Scripture placeholders until references are verified through an authorized source-verification process.
- Before each real-provider run, confirm the selected profile, effective limits/timeouts, budget state, required context, and scope. Never expose credentials in logs or reports.

## Outstanding limitations

- Provider pricing is unconfigured, so usage cost remains unknown.
- No Scripture verification pass is implemented.
- Canon proposals remain human-review only.
- Multi-chapter orchestration is not implemented.
- Release and preflight pipelines are not implemented.

## Recommended next sprint

**Sprint 7 — Concept Validation Layer**, informed by `docs/research/Idea_Development_for_a_Youth-Book_KDP_Pipeline.md`. Add a human-supervised concept validation stage before planning, with explicit evidence and uncertainty handling so a promising premise is not mistaken for validated demand. The cited research file was not present in the checked repository during this retrospective; review it when available before finalizing Sprint 7 scope.
