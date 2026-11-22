"""Run an eval suite against one model via the Bedrock Converse API (Requirement 3)."""

from __future__ import annotations

import hashlib
import json
import random
import statistics
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from modelbot import graders
from modelbot.graders import GraderResult
from modelbot.pricing import BudgetTracker, Price, cost_usd

RETRYABLE_ERRORS = frozenset(
    {
        "ThrottlingException",
        "ServiceUnavailableException",
        "ModelNotReadyException",
        "InternalServerException",
    }
)


class ConverseClient(Protocol):
    def converse(self, **kwargs: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 6
    base_delay_s: float = 1.0
    max_delay_s: float = 20.0

    def delay(self, attempt: int) -> float:
        """Exponential backoff with full jitter (attempt starts at 0)."""
        return random.uniform(0, min(self.max_delay_s, self.base_delay_s * 2**attempt))


@dataclass(frozen=True)
class Case:
    id: str
    input: str
    graders: list[dict[str, Any]]


@dataclass
class CaseResult:
    case_id: str
    output: str
    passed: bool
    grader_results: list[GraderResult]
    input_tokens: int
    output_tokens: int
    latency_ms: int
    error: str | None = None


@dataclass
class SuiteResult:
    model_id: str
    prompt_hash: str
    suite_hash: str
    results: list[CaseResult] = field(default_factory=list)
    partial: bool = False
    repeats: int = 1

    @property
    def flaky(self) -> list[str]:
        """Base case IDs that both passed and failed across repeats."""
        outcomes: dict[str, set[bool]] = {}
        for r in self.results:
            outcomes.setdefault(base_case_id(r.case_id), set()).add(r.passed)
        return sorted(cid for cid, seen in outcomes.items() if len(seen) == 2)

    @property
    def pass_rate(self) -> float:
        return sum(r.passed for r in self.results) / len(self.results) if self.results else 0.0

    @property
    def errored(self) -> list[CaseResult]:
        return [r for r in self.results if r.error]

    def _latency_quantile(self, q: float) -> float:
        lat = sorted(r.latency_ms for r in self.results if not r.error)
        if not lat:
            return 0.0
        if len(lat) == 1:
            return float(lat[0])
        return statistics.quantiles(lat, n=100, method="inclusive")[int(q * 100) - 1]

    @property
    def p50_ms(self) -> float:
        return self._latency_quantile(0.50)

    @property
    def p95_ms(self) -> float:
        return self._latency_quantile(0.95)

    def cost_per_1k(self, prices: dict[str, Price]) -> float:
        if not self.results:
            return 0.0
        total = sum(cost_usd(prices, self.model_id, r.input_tokens, r.output_tokens) for r in self.results)
        return total / len(self.results) * 1000


def load_cases(path: str | Path) -> list[Case]:
    cases = []
    for line in Path(path).read_text().splitlines():
        if line.strip():
            d = json.loads(line)
            cases.append(Case(id=d["id"], input=d["input"], graders=d["graders"]))
    return cases


def base_case_id(case_id: str) -> str:
    """Strip the '#<n>' repeat suffix."""
    return case_id.split("#", 1)[0]


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def suite_hash(cases: list[Case]) -> str:
    return digest("\n".join(json.dumps(c.__dict__, sort_keys=True) for c in cases))


def _error_code(exc: Exception) -> str | None:
    return getattr(exc, "response", {}).get("Error", {}).get("Code")


def _converse_with_retry(
    client: ConverseClient, request: dict[str, Any], retry: RetryPolicy, sleep: Callable[[float], None]
) -> dict[str, Any]:
    for attempt in range(retry.max_attempts):
        try:
            return client.converse(**request)
        except Exception as e:
            if _error_code(e) not in RETRYABLE_ERRORS or attempt == retry.max_attempts - 1:
                raise
            sleep(retry.delay(attempt))
    raise AssertionError("unreachable")


def run_case(
    client: ConverseClient,
    model_id: str,
    system_prompt: str,
    case: Case,
    retry: RetryPolicy = RetryPolicy(),
    sleep: Callable[[float], None] = time.sleep,
) -> CaseResult:
    request = {
        "modelId": model_id,
        "system": [{"text": system_prompt}],
        "messages": [{"role": "user", "content": [{"text": case.input}]}],
        "inferenceConfig": {"temperature": 0},
    }
    started = time.perf_counter()
    try:
        resp = _converse_with_retry(client, request, retry, sleep)
    except Exception as e:
        # An errored case counts as failed; the error is surfaced in the report.
        return CaseResult(case.id, "", False, [], 0, 0, 0, error=f"{_error_code(e) or type(e).__name__}: {e}")
    wall_ms = int((time.perf_counter() - started) * 1000)
    output = "".join(c.get("text", "") for c in resp["output"]["message"]["content"])
    results = [graders.get(g["type"])(output, g) for g in case.graders]
    usage = resp.get("usage", {})
    return CaseResult(
        case_id=case.id,
        output=output,
        passed=all(r.passed for r in results),
        grader_results=results,
        input_tokens=usage.get("inputTokens", 0),
        output_tokens=usage.get("outputTokens", 0),
        latency_ms=resp.get("metrics", {}).get("latencyMs", wall_ms),
    )


def run_suite(
    client: ConverseClient,
    model_id: str,
    system_prompt: str,
    cases: list[Case],
    *,
    concurrency: int = 1,
    prices: dict[str, Price] | None = None,
    budget: BudgetTracker | None = None,
    retry: RetryPolicy = RetryPolicy(),
    sleep: Callable[[float], None] = time.sleep,
    repeats: int = 1,
) -> SuiteResult:
    """Run all cases with bounded concurrency; stop submitting new cases once the budget is exhausted."""
    if budget is not None and prices is None:
        raise ValueError("budget tracking requires prices")

    original = cases
    if repeats > 1:
        # Each repeat is a separate case ('id#n') so pass rate averages over runs.
        cases = [Case(f"{c.id}#{k}", c.input, c.graders) for k in range(1, repeats + 1) for c in cases]
    queue = iter(cases)
    done_by_id: dict[str, CaseResult] = {}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        in_flight: set[Future[CaseResult]] = set()

        def submit_next() -> None:
            if budget is not None and budget.exhausted:
                return
            case = next(queue, None)
            if case is not None:
                in_flight.add(pool.submit(run_case, client, model_id, system_prompt, case, retry, sleep))

        for _ in range(concurrency):
            submit_next()
        while in_flight:
            finished, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            for fut in finished:
                in_flight.remove(fut)
                r = fut.result()
                done_by_id[r.case_id] = r
                if budget is not None:
                    budget.add(cost_usd(prices, model_id, r.input_tokens, r.output_tokens))
                submit_next()

    result = SuiteResult(model_id, digest(system_prompt), suite_hash(original), repeats=repeats)
    result.results = [done_by_id[c.id] for c in cases if c.id in done_by_id]
    result.partial = len(result.results) < len(cases)
    return result
