# Bounded chapter orchestration

Chapter queues are explicit worklists. Queueing never triggers generation; a queue operation is bounded to ten chapter numbers, and `chapters next --draft` drafts at most one queued chapter. Every chapter still requires its own accepted card and human acceptance.

```text
kdp chapters queue TITLE_ID --start 1 --through 5
kdp chapters list TITLE_ID
kdp chapters next TITLE_ID
kdp chapters next TITLE_ID --draft
kdp chapters stop TITLE_ID
kdp chapters resume TITLE_ID
kdp chapters summary TITLE_ID --chapter-number 1 --asset-id ACCEPTED_CHAPTER_ASSET --summary "Human-reviewed continuity summary" --reviewer REVIEWER
kdp inspect title TITLE_ID
```

For a later chapter, every earlier accepted chapter must have a reviewed human-authored summary. The summary is registered with provenance and approval, and its content and hash are included in the later chapter's provider prompt and context manifest. Drafting blocks if a prior accepted chapter is missing a valid summary. Summaries are continuity aids and do not replace accepted manuscript or canon context.

Queue states, per-chapter status, missing cards, failed jobs, open findings, summaries, and approval conditions are visible through inspection. Stop pauses queued items; it does not cancel a provider request already in progress. Resume rechecks card availability. Queueing ranges and drafting chapters do not advance title state or approve content.
