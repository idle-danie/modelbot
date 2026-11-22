"""Markdown / JSON reports (Requirement 7.1–7.2)."""

from __future__ import annotations

from modelbot.decision import Recommendation
from modelbot.pricing import Price
from modelbot.runner import SuiteResult


def _delta(new: float, old: float, lower_is_better: bool) -> str:
    if old == 0:
        return "–"
    pct = (new - old) / old * 100
    good = pct <= 0 if lower_is_better else pct >= 0
    return f"{pct:+.0f}% {'✅' if good else '⚠️'}"


def _row(label: str, base: str, cand: str, delta: str) -> str:
    return f"| {label} | {base} | {cand} | {delta} |"


def comparison_table(base: SuiteResult, cand: SuiteResult, prices: dict[str, Price]) -> str:
    bc, cc = base.cost_per_1k(prices), cand.cost_per_1k(prices)
    pp = (cand.pass_rate - base.pass_rate) * 100
    return "\n".join(
        [
            f"| Metric | `{base.model_id}` | `{cand.model_id}` | Change |",
            "|---|---|---|---|",
            _row(
                "Eval pass rate",
                f"{base.pass_rate:.0%}",
                f"{cand.pass_rate:.0%}",
                f"{pp:+.0f}pp {'✅' if pp >= 0 else '⚠️'}",
            ),
            _row(
                "p95 latency",
                f"{base.p95_ms / 1000:.1f}s",
                f"{cand.p95_ms / 1000:.1f}s",
                _delta(cand.p95_ms, base.p95_ms, lower_is_better=True),
            ),
            _row("Cost / 1k cases", f"${bc:.2f}", f"${cc:.2f}", _delta(cc, bc, lower_is_better=True)),
        ]
    )


def _caveats(suites: list[SuiteResult]) -> list[str]:
    notes = []
    for s in suites:
        if s.errored:
            notes.append(f"- `{s.model_id}`: {len(s.errored)} case(s) errored and count as failed")
        if s.partial:
            notes.append(f"- `{s.model_id}`: budget exhausted — evaluated {len(s.results)} case(s) only")
    return ["", "**Caveats**", "", *notes] if notes else []


def render_markdown(rec: Recommendation, prices: dict[str, Price]) -> str:
    lines = [f"## 🤖 modelbot · `{rec.target}`", ""]
    if rec.urgent:
        lines += ["> ⚠️ **Baseline model is LEGACY on Amazon Bedrock.** Plan the migration now.", ""]
    if rec.chosen is None:
        lines += ["**No candidate met the quality, cost, and latency policy.**"]
        if rec.manual_review:
            lines += ["", "Manual review required: the baseline is deprecated."]
        if rec.ranked:
            lines += ["", "Best candidate:", "", comparison_table(rec.baseline, rec.ranked[0], prices)]
        lines += _caveats([rec.baseline, *rec.ranked])
        return "\n".join(lines) + "\n"
    lines += [
        f"**Recommended:** `{rec.baseline.model_id}` → `{rec.chosen.model_id}`",
        "",
        comparison_table(rec.baseline, rec.chosen, prices),
        "",
        f"<sub>eval suite `{rec.baseline.suite_hash}` · {len(rec.baseline.results)} cases</sub>",
        *_caveats([rec.baseline, rec.chosen]),
    ]
    # TODO(task 8.2): failing-case and prompt-diff <details> sections; JSON report.
    return "\n".join(lines) + "\n"
