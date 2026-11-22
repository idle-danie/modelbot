## ✍️ modelbot port · `email-extractor` → `amazon.nova-lite-v1:0`

Holdout pass rate (cases the agent never saw): **50% → 50%**

Full-suite pass rate on `amazon.nova-lite-v1:0`: 60% → 60%

### ✍️ Prompt porting for `amazon.nova-lite-v1:0`

No revision accepted. Holdout pass rate 50% → 50% after 4 attempt(s).

<details><summary>Rejected for changing business rules</summary>

- attempt 2: - For order IDs with leading zeros, remove the zeros (e.g. "ord#00330981" -> "ORD-330981").
- attempt 2: - For amounts with decimals, include the decimal (e.g. "$89.50" -> 89.50).
- attempt 2: - For phrases like "next Monday", calculate the exact date.
- attempt 2: - For phrases like "today", use the Received date.
- attempt 2: - For phrases like "모레" (the day after tomorrow), calculate the exact date.
</details>

<details><summary>Attempts</summary>

| # | Holdout | Regressions | Result | Changes |
|---|---|---|---|---|
| 1 | 50% | 0 | rejected: copies eval case(s) en-refund, ko-man-won, hash-id… | - Added headings to make the structure clearer.
- Emphasized the output format at the end of the prompt.
- Provided more explicit instructions and examples for  |
| 2 | 50% | 0 | rejected: changes business rules (5) | Added headings to make the structure clearer.; Emphasized the output format at the end of the prompt.; Provided more explicit instructions and examples for hand |
| 3 | 50% | 0 | rejected: copies eval case(s) next-monday, k-suffix | Added headings to make the structure clearer.; Emphasized the output format at the end of the prompt.; Provided more explicit instructions and examples for hand |
| 4 | 50% | 0 | rejected: copies eval case(s) no-order | Added headings to make the structure clearer.; Emphasized the output format at the end of the prompt.; Provided more explicit instructions and examples for hand |
</details>
