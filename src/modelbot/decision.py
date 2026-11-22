"""Qualification and ranking of candidates (Requirement 6). Pure functions only."""

from __future__ import annotations

from dataclasses import dataclass, field

from modelbot.config import Target
from modelbot.pricing import Price
from modelbot.runner import SuiteResult


@dataclass
class Recommendation:
    target: str
    baseline: SuiteResult
    urgent: bool
    chosen: SuiteResult | None
    ranked: list[SuiteResult] = field(default_factory=list)
    manual_review: bool = False


def qualifies(c: SuiteResult, base: SuiteResult, target: Target, prices: dict[str, Price]) -> bool:
    base_cost = base.cost_per_1k(prices)
    return (
        c.pass_rate >= max(target.threshold, base.pass_rate - target.tolerance)
        and (base_cost == 0 or c.cost_per_1k(prices) <= base_cost * target.limits.max_cost_ratio)
        and (base.p95_ms == 0 or c.p95_ms <= base.p95_ms * target.limits.max_p95_ratio)
    )


def decide(
    target: Target,
    baseline: SuiteResult,
    candidates: list[SuiteResult],
    prices: dict[str, Price],
    urgent: bool = False,
) -> Recommendation:
    ranked = sorted(candidates, key=lambda c: (-c.pass_rate, c.cost_per_1k(prices), c.p95_ms))
    chosen = next((c for c in ranked if qualifies(c, baseline, target, prices)), None)
    return Recommendation(
        target=target.name,
        baseline=baseline,
        urgent=urgent,
        chosen=chosen,
        ranked=ranked,
        manual_review=urgent and chosen is None,
    )
