## ✍️ modelbot port · `email-extractor` → `amazon.nova-lite-v1:0`

Holdout pass rate (cases the agent never saw): **50% → 50%**

Full-suite pass rate on `amazon.nova-lite-v1:0`: 55% → 55%

### ✍️ Prompt porting for `amazon.nova-lite-v1:0`

No revision accepted. Holdout pass rate 50% → 50% after 4 attempt(s).

<details><summary>Rejected for changing business rules</summary>

- attempt 1: action — new rule added: REVISED defines that `inquiry` covers 'any question or information request (e.g., shipping status, delivery date, order status),' narrowing/specifying the classification scope in a way not present in the ORIGINAL.
- attempt 1: amount — new rule added: REVISED adds 'keep decimals exactly; do NOT shift the decimal point' (illustrated by '$89.50 → 89.5'), a precision/rounding rule not present in the ORIGINAL.
- attempt 1: due_date — new rules added: REVISED adds explicit resolution mappings not implied by the ORIGINAL's 'resolved against the Received date': 'today' → Received date, 'tomorrow'/'내일' → +1 day, '모레' → +2 days, 'next [weekday]'/'다음 주 [요일]' → named weekday in the next calendar week.
- attempt 1: output format — new rule added: REVISED requires 'Output ONLY a single raw JSON object. Do not use markdown, code fences, or any extra text before or after the JSON.' The ORIGINAL imposes no such formatting restriction.
- attempt 2: ADDED rule on amount: The REVISED prompt adds 'Preserve decimal points exactly — never remove or shift them. "$89.50" → 89.50 (not 8950).' This is a new constraint not present or implied in the ORIGINAL, which only says to express the amount 'as a number without separators.'
- attempt 2: ADDED rules on due_date relative date resolution: The REVISED prompt adds an entire relative-date resolution table ('today', 'tomorrow'/'내일', '모레', 'next [Weekday]', '다음 주 [요일]') with specific day-offset semantics. None of these rules appear in the ORIGINAL.
- attempt 2: ADDED rule on priority P2 day-counting: The REVISED prompt adds explicit calendar-day counting examples and clarifies 'within 3 days' as 0–3 inclusive days (due_date minus Received ≤ 3). The ORIGINAL says 'within 3 days of the Received date' without specifying whether the boundary is inclusive or how to count, so the explicit inclusive-boundary definition and examples are additions.
- attempt 2: ADDED output format constraint: The REVISED prompt adds 'Output ONLY a single raw JSON object. No markdown, no code fences, no extra text before or after.' This formatting restriction does not appear in the ORIGINAL.
- attempt 3: ADDED relative-date resolution rules not present in the ORIGINAL: The REVISED adds specific rules for 'today' (R+0), 'tomorrow'/'내일' (R+1), '모레' (R+2), '이틀 안에/후' (R+2), 'next [Weekday]' (nearest future weekday from R+1), and '다음 주 [요일]' (weekday in the calendar week after R's week). The ORIGINAL only says due_date is resolved against the Received date with no such specific mappings.
- attempt 3: ADDED output format constraint not present in the ORIGINAL: The REVISED adds 'Output ONLY a single raw JSON object on one line. No markdown, no code fences, no extra text before or after.' The ORIGINAL specifies only the JSON field structure.
- attempt 4: AMOUNT — decimal handling rule added: The ORIGINAL says amounts are a 'number without separators' with no special rule about preserving decimals. The REVISED adds 'Preserve decimals exactly — do not multiply or shift: "$89.50" → 89.50, not 8950.' This is a new business rule not implied by the ORIGINAL (the ORIGINAL's wording and examples are silent on decimal handling, so this is an addition that could change output for decimal amounts).
- attempt 4: PRIORITY P2 — threshold changed: The ORIGINAL says P2 if 'due_date is within 3 days of the Received date', which naturally means the due_date falls on day+1, day+2, or day+3 (i.e., strictly within 3 days, exclusive of same-day). The REVISED redefines this as due_date − Received ≤ 3 calendar days, explicitly including same-day (0 days) as P2. This changes the rule's meaning for the same-day case.
- attempt 4: OUTPUT FORMAT — new formatting constraint added: The REVISED adds 'Output ONLY a single raw JSON object on one line. No markdown, no code fences, no extra text before or after.' This is a new output format requirement not present in the ORIGINAL.
</details>

<details><summary>Attempts</summary>

| # | Holdout | Regressions | Result | Changes |
|---|---|---|---|---|
| 1 | 50% | 0 | rejected: changes business rules (4) | Added explicit 'do NOT shift the decimal point' note for decimal amounts like $89.50; Added explicit definition of Korean 'morae' (모레) as Received + 2 days; Add |
| 2 | 50% | 0 | rejected: changes business rules (4) | Added markdown headings (## Role, ## Field Rules, ## Output Format) for Nova Lite's preference for clear structure; Added explicit decimal preservation rule: '$ |
| 3 | 50% | 0 | rejected: changes business rules (2) | Added markdown headings (## Role, ## Field Rules, ## Priority Worked Examples, ## Output Format) for Nova Lite's preference for clear structure; Added explicit  |
| 4 | 50% | 0 | rejected: changes business rules (3) | Restructured with markdown headings (## Role, ## Field Rules, ## Output Format) for Nova Lite's preference for clear structure; Added explicit decimal-preservat |
</details>
