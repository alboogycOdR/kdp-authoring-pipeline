Analyze Chapter {{chapter_number}} in {{working_title}} for internal and cross-context consistency using the supplied accepted plans, card, draft, and prior chapter summaries:

{{chapter_context}}

Return only JSON matching this contract: {"status":"pass|review|fail","supplied_context_confirmed":true,"summary":"...","findings":[{"severity":"note|minor|major|critical","location":"section or short locator","issue":"...","evidence":"brief exact excerpt or specific observation","recommended_action":"..."}],"required_followups":[]}. Use an empty findings array when there are no actionable consistency issues.

Check names, terminology, claims, sequence, audience, and commitments against supplied context. Distinguish a real contradiction from a deliberate development or unresolved proposal. Do not mutate canon, rewrite, or ask for readable supplied context to be resent.
