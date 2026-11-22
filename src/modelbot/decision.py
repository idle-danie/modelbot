"""Qualification and ranking of candidates (Requirement 6). Pure functions only."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from modelbot.config import Target
from modelbot.pricing import Price
from modelbot.runner import SuiteResult

if TYPE_CHECKING:
    from modelbot.porter import PortingResult


@dataclass
class Recommendation:
    target: str
    baseline: SuiteResult
    urgent: bool
    chosen: SuiteResult | None
    ranked: list[SuiteResult] = field(default_factory=list)
    manual_review: bool = False
    ported: dict[str, PortingResult] = field(default_factory=dict)
    baseline_status: str = "ACTIVE"


def quality_bar(base: SuiteResult, target: Target) -> float:
    return max(target.threshold, base.pass_rate - target.tolerance)


def portable(c: SuiteResult, base: SuiteResult, target: Target) -> bool:
    """Below the quality bar, but close enough that prompt porting may close the gap (R5.1)."""
    bar = quality_bar(base, target)
    return bar - target.porting.margin <= c.pass_rate < bar


def qualifies(c: SuiteResult, base: SuiteResult, target: Target, prices: dict[str, Price]) -> bool:
    base_cost = base.cost_per_1k(prices)
    return (
        c.pass_rate >= quality_bar(base, target)
        and (base_cost == 0 or c.cost_per_1k(prices) <= base_cost * target.limits.max_cost_ratio)
        and (base.p95_ms == 0 or c.p95_ms <= base.p95_ms * target.limits.max_p95_ratio)
    )


def decide(
    target: Target,
    baseline: SuiteResult,
    candidates: list[SuiteResult],
    prices: dict[str, Price],
    urgent: bool = False,
    baseline_status: str = "ACTIVE",
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
        baseline_status=baseline_status,
    )
