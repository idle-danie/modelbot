"""Compare rule-check judges on three known revisions of the email-extractor prompt.

Usage: uv run python experiments/judge_comparison.py <judge-model-id> [...]
"""

import sys
from pathlib import Path

from modelbot.porter import strands_rule_checker
from modelbot.pricing import cost_usd, load_prices

ROOT = Path(__file__).resolve().parents[1] / "examples" / "email-extractor"
ORIGINAL = (ROOT / "prompts" / "extract.md").read_text().strip()

# 1. The revision the Nova Pro porting agent actually produced: contains a wrong rule ("$89.50" -> 8950).
diff = (ROOT / "SAMPLE-port-report.md").read_text().split("```diff", 1)[1].split("```", 1)[0].splitlines()
WRONG_RULE = "\n".join(line[1:] for line in diff if line[:1] in "+ " and not line.startswith("+++"))

# 2. Correct clarifications: examples that follow the original rules exactly.
CLARIFIED = ORIGINAL.replace(
    '("12만원" -> 120000, "$1.2k" -> 1200)', '("12만원" -> 120000, "$1.2k" -> 1200, "$89.50" -> 89.5)'
).replace(
    "resolved against the Received date. null if none.",
    'resolved against the Received date (e.g. "today" is the Received date itself). null if none.',
)

# 3. Pure rewording and formatting.
REWORDED = (
    ORIGINAL.replace("<rules>", "<rules>\n## Extraction rules")
    .replace("- order_id:", "- **order_id**:")
    .replace(
        "If several are requested, use the first one mentioned.",
        "When the customer requests more than one action, return the one mentioned first.",
    )
)

CASES = [
    ("wrong rule", WRONG_RULE, False),
    ("correct clarification", CLARIFIED, True),
    ("rewording", REWORDED, True),
]
TRIALS = 2

prices = load_prices()
for judge in sys.argv[1:]:
    spent = []
    check = strands_rule_checker(
        judge, "us-east-1", on_usage=lambda m, i, o, spent=spent: spent.append(cost_usd(prices, m, i, o))
    )
    correct = 0
    print(f"\n### judge: {judge}")
    for name, revised, expected in CASES:
        verdicts = [check(ORIGINAL, revised) for _ in range(TRIALS)]
        ok = sum(v.preserved == expected for v in verdicts)
        correct += ok
        first = next((v.violations for v in verdicts if v.violations), [])
        print(
            f"- {name}: expected preserved={expected}, correct {ok}/{TRIALS}"
            + (f" | e.g. {first[0][:110]!r}" if first else "")
        )
    print(f"accuracy {correct}/{len(CASES) * TRIALS} · cost ${sum(spent):.4f}")
