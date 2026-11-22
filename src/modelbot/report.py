"""Markdown / JSON reports (Requirement 7.1–7.2)."""

from __future__ import annotations

import difflib

from modelbot.decision import Recommendation
from modelbot.porter import PortingResult
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
            first = s.errored[0].error or ""
            notes.append(
                f"- `{s.model_id}`: {len(s.errored)} case(s) errored and count as failed "
                f"(e.g. `{first[:140]}`)"
            )
        if s.partial:
            notes.append(f"- `{s.model_id}`: budget exhausted — evaluated {len(s.results)} case(s) only")
    return ["", "**Caveats**", "", *notes] if notes else []


def _cell(text: str, limit: int = 160) -> str:
    """Single-line, pipe-safe Markdown table cell."""
    return " ".join(text.split()).replace("|", "\\|")[:limit]


def _bullets(items: list[str]) -> list[str]:
    """Judges sometimes pack several findings into one string; split them into separate bullets."""
    out = []
    for item in items:
        for line in item.splitlines():
            line = line.strip().lstrip("-• ").strip()
            if line:
                out.append(line)
    return out


def porting_section(pr: PortingResult) -> list[str]:
    head = f"### ✍️ Prompt porting for `{pr.model_id}`"
    summary = (
        f"Holdout pass rate {pr.holdout_before:.0%} → {pr.holdout_after:.0%} "
        f"after {len(pr.attempts)} attempt(s)."
    )
    lines = ["", head, "", summary if pr.accepted else f"No revision accepted. {summary}"]
    if pr.accepted:
        diff = difflib.unified_diff(
            pr.original.splitlines(),
            pr.revised.splitlines(),
            "prompt (current)",
            "prompt (ported)",
            lineterm="",
        )
        lines += [
            "",
            f"**Why:** {pr.rationale}",
            "",
            "<details><summary>Prompt diff</summary>",
            "",
            "```diff",
            *diff,
            "```",
            "</details>",
        ]
    rows = [
        f"| {a.iteration} | {a.holdout_pass_rate:.0%} | {a.regressions} | {_cell(a.reason)} | "
        f"{_cell('; '.join(_bullets(a.changes))) or '–'} |"
        for a in pr.attempts
    ]
    violations = [f"- attempt {a.iteration}: {v}" for a in pr.attempts for v in _bullets(a.violations)]
    if violations:
        lines += [
            "",
            "<details><summary>Rejected for changing business rules</summary>",
            "",
            *violations,
            "</details>",
        ]
    lines += [
        "",
        "<details><summary>Attempts</summary>",
        "",
        "| # | Holdout | Regressions | Result | Changes |",
        "|---|---|---|---|---|",
        *rows,
        "</details>",
    ]
    return lines


def candidates_table(rec: Recommendation, prices: dict[str, Price]) -> list[str]:
    rows = []
    for s in [rec.baseline, *rec.ranked]:
        pr = rec.ported.get(s.model_id)
        label = f"`{s.model_id}`" + (" (ported prompt)" if pr and pr.accepted else "")
        label += " ⭐" if s is rec.chosen else ""
        rows.append(
            f"| {label} | {s.pass_rate:.0%} | {s.p95_ms / 1000:.1f}s | ${s.cost_per_1k(prices):.2f} |"
        )
    return [
        "",
        "<details><summary>All evaluated models</summary>",
        "",
        "| Model | Pass rate | p95 | Cost / 1k |",
        "|---|---|---|---|",
        *rows,
        "</details>",
    ]


def render_markdown(rec: Recommendation, prices: dict[str, Price]) -> str:
    lines = [f"## 🤖 modelbot · `{rec.target}`", ""]
    if rec.baseline_status == "MISSING":
        lines += [
            "> ⛔ **Baseline model is no longer listed in the Bedrock catalog for this region.** "
            "It has likely reached end-of-life and calls to it will fail.",
            "",
        ]
    elif rec.urgent:
        lines += ["> ⚠️ **Baseline model is LEGACY on Amazon Bedrock.** Plan the migration now.", ""]
    if rec.chosen is None:
        lines += ["**No candidate met the quality, cost, and latency policy.**"]
        if rec.manual_review:
            lines += ["", "Manual review required: the baseline is deprecated."]
        if rec.ranked:
            lines += ["", "Best candidate:", "", comparison_table(rec.baseline, rec.ranked[0], prices)]
        lines += candidates_table(rec, prices)
        for pr in rec.ported.values():
            lines += porting_section(pr)
        lines += _caveats([rec.baseline, *rec.ranked])
        return "\n".join(lines) + "\n"
    lines += [
        f"**Recommended:** `{rec.baseline.model_id}` → `{rec.chosen.model_id}`",
        "",
        comparison_table(rec.baseline, rec.chosen, prices),
        "",
        f"<sub>eval suite `{rec.baseline.suite_hash}` · {len(rec.baseline.results)} cases</sub>",
    ]
    lines += candidates_table(rec, prices)
    for pr in rec.ported.values():
        lines += porting_section(pr)
    lines += _caveats([rec.baseline, rec.chosen])
    # TODO(task 8.2): failing-case <details> section; JSON report.
    return "\n".join(lines) + "\n"
