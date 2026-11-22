"""Run an eval suite against one model via the Bedrock Converse API (Requirement 3)."""

from __future__ import annotations

import hashlib
import json
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from modelbot import graders
from modelbot.graders import GraderResult
from modelbot.pricing import Price, cost_usd


class ConverseClient(Protocol):
    def converse(self, **kwargs: Any) -> dict[str, Any]: ...


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


@dataclass
class SuiteResult:
    model_id: str
    prompt_hash: str
    suite_hash: str
    results: list[CaseResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return sum(r.passed for r in self.results) / len(self.results) if self.results else 0.0

    def _latency_quantile(self, q: float) -> float:
        lat = sorted(r.latency_ms for r in self.results)
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


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def run_case(client: ConverseClient, model_id: str, system_prompt: str, case: Case) -> CaseResult:
    # TODO(task 4.3): retry ThrottlingException with exponential backoff + full jitter.
    started = time.perf_counter()
    resp = client.converse(
        modelId=model_id,
        system=[{"text": system_prompt}],
        messages=[{"role": "user", "content": [{"text": case.input}]}],
        inferenceConfig={"temperature": 0},
    )
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


def run_suite(client: ConverseClient, model_id: str, system_prompt: str, cases: list[Case]) -> SuiteResult:
    # TODO(task 4.2): thread-pool concurrency + BudgetTracker integration.
    suite_hash = digest("\n".join(json.dumps(c.__dict__, sort_keys=True) for c in cases))
    result = SuiteResult(model_id, digest(system_prompt), suite_hash)
    for case in cases:
        result.results.append(run_case(client, model_id, system_prompt, case))
    return result
