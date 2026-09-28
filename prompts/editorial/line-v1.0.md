Analyze Chapter {{chapter_number}} in {{working_title}} for sentence-level clarity and flow using all supplied context:

{{chapter_context}}

Return only JSON matching this contract: {"status":"pass|review|fail","supplied_context_confirmed":true,"summary":"...","findings":[{"severity":"note|minor|major|critical","location":"section or short locator","issue":"...","evidence":"brief exact excerpt or specific observation","recommended_action":"..."}],"required_followups":[]}. Use an empty findings array when there are no actionable line issues.

Focus on ambiguity, awkward syntax, repetition, transitions, and sentence rhythm while preserving meaning and voice. Analyze only; do not rewrite the chapter. Do not invent facts or ask for readable supplied context to be resent.
