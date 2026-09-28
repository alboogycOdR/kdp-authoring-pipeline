# Concept workflow

Concept validation is opt-in per title for backward compatibility. Enable it while the title is in `IDEA`, before accepting positioning:

```text
kdp concept enable TITLE_ID
kdp concept audience-brief TITLE_ID --audience "YA readers, ages 13–17; independent reading"
kdp concept generate-seeds TITLE_ID --asset-id AUDIENCE_ASSET_ID
kdp concept enrich TITLE_ID --asset-id SEED_SET_ASSET_ID --selection "Selected seed label and text"
kdp concept validate CONCEPT_BRIEF_ASSET_ID
kdp concept score TITLE_ID --asset-id CONCEPT_BRIEF_ASSET_ID
kdp concept approve CONCEPT_BRIEF_ASSET_ID --reviewer REVIEWER
kdp concept drafting-brief TITLE_ID --asset-id ACCEPTED_CONCEPT_BRIEF_ASSET_ID
kdp inspect concept TITLE_ID
```

Generated concepts remain experimental. `validate` performs deterministic completeness and risk checks; it cannot establish originality, market demand, legal clearance, suitability, or factual accuracy. Scorecards are advisory. A human must review and explicitly approve an enriched concept brief before it unlocks positioning or can be used for a drafting brief. The concept gate can be disabled while the title remains in `IDEA`.

Use explicit age bands and reading stages. In particular, distinguish YA teens (roughly ages 13–17) from emerging adults (18–25); avoid relying on the ambiguous label “young adult.” For nonfiction and devotionals, state the reader's practical or spiritual need, repeatable content engine, and bounded promise. Preserve research, source, Scripture, faith/theology, rights, and content-transparency flags for human follow-up.

Prompts and validation rules draw on the repository's `docs/research/Idea_Development_for_a_Youth-Book_KDP_Pipeline.md` guide. Comparable books are positioning references only and must not become imitation instructions.
