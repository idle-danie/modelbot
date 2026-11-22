from modelbot.config import Target
from modelbot.decision import decide
from modelbot.pricing import Price
from modelbot.report import render_markdown
from modelbot.runner import Case, run_suite

PRICES = {"m.old": Price(1.0, 5.0), "m.new": Price(0.5, 2.5)}
CASES = [Case(f"c{i}", f"input {i}", [{"type": "contains", "value": "ok"}]) for i in range(10)]


class FakeClient:
    """Answers 'ok' for the first `good` cases, then 'nope'."""

    def __init__(self, good: int, latency_ms: int):
        self.good, self.latency_ms, self.calls = good, latency_ms, 0

    def converse(self, **kwargs):
        text = "ok" if self.calls < self.good else "nope"
        self.calls += 1
        return {
            "output": {"message": {"content": [{"text": text}]}},
            "usage": {"inputTokens": 1000, "outputTokens": 100},
            "metrics": {"latencyMs": self.latency_ms},
        }


TARGET = Target(name="t", file="f", key="k", prompts=["p"], evals="e", threshold=0.8)


def test_run_suite_aggregates():
    r = run_suite(FakeClient(good=9, latency_ms=1200), "m.old", "sys", CASES)
    assert r.pass_rate == 0.9
    assert r.p95_ms == 1200
    assert round(r.cost_per_1k(PRICES), 2) == 1.5  # (1000*1 + 100*5) / 1e6 * 1000


def test_cheaper_equal_quality_candidate_is_chosen_and_rendered():
    base = run_suite(FakeClient(good=9, latency_ms=1200), "m.old", "sys", CASES)
    cand = run_suite(FakeClient(good=9, latency_ms=900), "m.new", "sys", CASES)
    rec = decide(TARGET, base, [cand], PRICES)
    assert rec.chosen is cand
    md = render_markdown(rec, PRICES)
    assert "`m.old` → `m.new`" in md and "-50%" in md


def test_urgent_without_qualifier_needs_manual_review():
    base = run_suite(FakeClient(good=9, latency_ms=1000), "m.old", "sys", CASES)
    weak = run_suite(FakeClient(good=5, latency_ms=1000), "m.new", "sys", CASES)
    rec = decide(TARGET, base, [weak], PRICES, urgent=True)
    assert rec.chosen is None and rec.manual_review
    assert "LEGACY" in render_markdown(rec, PRICES)
