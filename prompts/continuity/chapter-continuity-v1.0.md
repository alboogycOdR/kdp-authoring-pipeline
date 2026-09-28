# Chapter continuity analysis

Title: {{ working_title }}
Title ID: {{ title_id }}
Chapter/Entry: {{ chapter_number }}

Analyze the supplied context below. It includes the target draft and accepted planning artefacts. Do not ask the operator to resend supplied material. If a section is genuinely empty or unreadable, set `supplied_context_confirmed` to false and explain the missing material in `required_followups`.

Return only one valid JSON object with every field shown below. Use `status` = `pass`, `review`, or `fail`; report evidence and concise reasoning in each alignment/check field. Do not invent Scripture text. Check whether Scripture references are marked `[SCRIPTURE NEEDED]` or verified, whether calling is presented as discerned purpose/service rather than guaranteed divine endorsement, whether prosperity framing or business outcome guarantees appear, whether the intended audience is contradicted, and whether anything risks continuity in later entries. Canon recommendations are proposals only; do not mutate canon.

Required JSON fields and types:
```json
{
  "status": "pass|review|fail",
  "supplied_context_confirmed": true,
  "alignment_with_positioning": "string",
  "alignment_with_book_brief": "string",
  "alignment_with_outline": "string",
  "alignment_with_chapter_card": "string",
  "canon_baseline_assessment": "string",
  "scripture_and_claims_check": "string",
  "prosperity_or_outcome_promise_check": "string",
  "audience_consistency_check": "string",
  "continuity_findings": [],
  "canon_proposal_recommendation": "string",
  "required_followups": []
}
```

## Supplied context

{{ continuity_context }}
