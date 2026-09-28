Analyze Chapter {{chapter_number}} in {{working_title}} for copy-level correctness using all supplied context:

{{chapter_context}}

Return only JSON matching this contract: {"status":"pass|review|fail","supplied_context_confirmed":true,"summary":"...","findings":[{"severity":"note|minor|major|critical","location":"section or short locator","issue":"...","evidence":"brief exact excerpt or specific observation","recommended_action":"..."}],"required_followups":[]}. Use an empty findings array when there are no actionable copy issues.

Focus on grammar, spelling, punctuation, capitalization, usage, and mechanical consistency. Distinguish objective errors from style choices. Do not alter Scripture quotations or references; flag verification needs rather than supplying text. Analyze only; do not rewrite or ask for readable supplied context to be resent.
