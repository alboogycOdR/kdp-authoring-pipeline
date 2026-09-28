Analyze the voice of Chapter {{chapter_number}} in {{working_title}} using the supplied chapter, accepted planning artefacts, chapter card, and prior summaries where present:

{{chapter_context}}

Return only JSON matching this contract: {"status":"pass|review|fail","supplied_context_confirmed":true,"summary":"...","findings":[{"severity":"note|minor|major|critical","location":"section or short locator","issue":"...","evidence":"brief exact excerpt or specific observation","recommended_action":"..."}],"required_followups":[]}. Use an empty findings array when there are no actionable voice issues.

Focus on consistency of voice, warmth, humility, clarity, audience fit, and any style constraints in accepted context. Do not rewrite prose, invent facts, infer author identity, or convert preferences into errors. If supplied context is readable, analyze it; do not ask for it to be resent.
