import threading
import time

from modelbot.pricing import BudgetTracker, Price
from modelbot.runner import Case, RetryPolicy, run_suite

PRICES = {"m": Price(1.0, 1.0)}
CASES = [Case(f"c{i}", f"in {i}", [{"type": "contains", "value": "ok"}]) for i in range(8)]
OK = {
    "output": {"message": {"content": [{"text": "ok"}]}},
    "usage": {"inputTokens": 500_000, "outputTokens": 0},  # $0.50 per call at $1/1M
    "metrics": {"latencyMs": 10},
}


class ClientError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FlakyClient:
    def __init__(self, fail_first: int, code: str = "ThrottlingException"):
        self.fail_first, self.code, self.calls = fail_first, code, 0
        self._lock = threading.Lock()

    def converse(self, **kwargs):
        with self._lock:
            self.calls += 1
            n = self.calls
        if n <= self.fail_first:
            raise ClientError(self.code)
        return OK


def test_throttling_is_retried_with_backoff():
    sleeps: list[float] = []
    client = FlakyClient(fail_first=3)
    r = run_suite(client, "m", "sys", CASES[:1], sleep=sleeps.append)
    assert r.pass_rate == 1.0 and len(sleeps) == 3
    assert all(0 <= s <= RetryPolicy().max_delay_s for s in sleeps)


def test_non_retryable_error_marks_case_failed():
    r = run_suite(FlakyClient(fail_first=99, code="AccessDeniedException"), "m", "sys", CASES[:2])
    assert r.pass_rate == 0.0 and len(r.errored) == 2
    assert "AccessDeniedException" in r.errored[0].error


def test_retries_exhausted_marks_case_failed():
    policy = RetryPolicy(max_attempts=2)
    r = run_suite(FlakyClient(fail_first=99), "m", "sys", CASES[:1], retry=policy, sleep=lambda _: None)
    assert r.errored and r.pass_rate == 0.0


def test_budget_stops_new_requests_and_marks_partial():
    budget = BudgetTracker(cap_usd=1.0)  # two calls at $0.50 each
    client = FlakyClient(fail_first=0)
    r = run_suite(client, "m", "sys", CASES, prices=PRICES, budget=budget)
    assert r.partial and len(r.results) == 2 and client.calls == 2
    assert budget.exhausted


def test_concurrency_runs_in_parallel_and_preserves_order():
    class SlowClient:
        def converse(self, **kwargs):
            time.sleep(0.05)
            return OK

    started = time.perf_counter()
    r = run_suite(SlowClient(), "m", "sys", CASES, concurrency=8)
    assert time.perf_counter() - started < 0.05 * len(CASES) / 2
    assert [x.case_id for x in r.results] == [c.id for c in CASES]


def test_repeats_average_and_flag_flaky_cases():
    class Alternating:
        """Case c0 fails on its first call and passes on its second; every other case passes."""

        def __init__(self):
            self.seen: dict[str, int] = {}
            self._lock = threading.Lock()

        def converse(self, messages, **kwargs):
            text = messages[0]["content"][0]["text"]
            with self._lock:
                self.seen[text] = self.seen.get(text, 0) + 1
                nth = self.seen[text]
            ok = text != "in 0" or nth == 2
            return {**OK, "output": {"message": {"content": [{"text": "ok" if ok else "no"}]}}}

    r = run_suite(Alternating(), "m", "sys", CASES[:4], repeats=2)
    assert len(r.results) == 8 and r.repeats == 2
    assert r.pass_rate == 7 / 8
    assert r.flaky == ["c0"]
