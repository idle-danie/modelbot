"""Agent-driven prompt porting (Requirement 5, design D3/D7).

The Strands agent proposes prompt revisions and may test them on the *development* split via the
`evaluate_prompt` tool. Acceptance is decided outside the agent, on the *holdout* split, so the rule is
deterministic and the agent cannot overfit to the cases that judge it. Holdout cases are never shown to
the agent; it only learns whether a revision was accepted.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from modelbot.config import PortingPolicy
from modelbot.runner import Case, SuiteResult

PORTER_SYSTEM_PROMPT = """\
You adapt an existing system prompt so that it performs well on a different foundation model.

Rules:
- Preserve the task, the output format, and every business rule in the original prompt.
- Change wording, structure, ordering, examples, and explicitness only. Never weaken a requirement.
- Do not special-case the inputs you see in failures; fix the underlying instruction instead.
- Use the evaluate_prompt tool to test a hypothesis before you answer. It runs the development cases only.
- Return the complete revised prompt, a short rationale, and the list of changes you made.
"""

# Short, provider-level hints. They steer the agent; the eval suite decides.
MODEL_GUIDANCE = {
    "anthropic": "Claude models follow clearly delimited sections well (e.g. XML-style tags) and respond "
    "best to explicit statements of the output contract and of how to handle adversarial input.",
    "amazon": "Amazon Nova models benefit from a clear structure with headings, the output format stated at "
    "the end of the prompt, and an explicit instruction to output only the requested format.",
    "meta": "Llama models benefit from concise instructions, an explicit output format, and a short example.",
}
MAX_TOOL_CALLS_PER_ITERATION = 3
_MAX_FAILURES_SHOWN = 8
_MAX_CHARS = 600


class PromptRevision(BaseModel):
    prompt: str = Field(description="The complete revised system prompt")
    rationale: str = Field(description="Why these changes should help on the target model")
    changes: list[str] = Field(default_factory=list, description="Bullet list of concrete edits")


@dataclass
class PortingAttempt:
    iteration: int
    rationale: str
    changes: list[str]
    holdout_pass_rate: float
    regressions: int
    accepted: bool
    reason: str


@dataclass
class PortingResult:
    model_id: str
    original: str
    revised: str
    holdout_before: float
    holdout_after: float
    attempts: list[PortingAttempt] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return self.revised != self.original

    @property
    def rationale(self) -> str:
        return next((a.rationale for a in reversed(self.attempts) if a.accepted), "")


# (task message, evaluate_on_dev) -> revision. Swappable so tests run without a model.
Reviser = Callable[[str, Callable[[str], str]], PromptRevision]
# (prompt, cases) -> SuiteResult on the candidate model.
Evaluate = Callable[[str, list[Case]], SuiteResult]


def split_cases(
    cases: list[Case], holdout_ratio: float = 0.4, seed: int = 7
) -> tuple[list[Case], list[Case]]:
    """Deterministic dev/holdout split (task 6.1)."""
    shuffled = cases[:]
    random.Random(seed).shuffle(shuffled)
    n_holdout = max(1, round(len(shuffled) * holdout_ratio))
    return shuffled[n_holdout:], shuffled[:n_holdout]


def summarize_failures(result: SuiteResult, cases: list[Case]) -> str:
    """Compact JSON description of failing dev cases for the agent."""
    inputs = {c.id: c for c in cases}
    failures = []
    for r in result.results:
        if r.passed:
            continue
        failures.append(
            {
                "case": r.case_id,
                "input": inputs[r.case_id].input[:_MAX_CHARS],
                "output": (r.error or r.output)[:_MAX_CHARS],
                "why": [g.detail for g in r.grader_results if not g.passed] or [r.error or "failed"],
            }
        )
    return json.dumps(
        {"pass_rate": round(result.pass_rate, 3), "failures": failures[:_MAX_FAILURES_SHOWN]},
        ensure_ascii=False,
        indent=1,
    )


def regressions(before: SuiteResult, after: SuiteResult) -> int:
    passed_before = {r.case_id for r in before.results if r.passed}
    return sum(1 for r in after.results if r.case_id in passed_before and not r.passed)


def build_task(model_id: str, provider: str, prompt: str, dev_summary: str, history: list[str]) -> str:
    parts = [
        f"Target model: {model_id}",
        f"Model guidance: {MODEL_GUIDANCE.get(provider, 'No specific guidance; rely on the eval feedback.')}",
        "",
        "Current system prompt:",
        "<<<",
        prompt,
        ">>>",
        "",
        "Development-set results with this prompt on the target model:",
        dev_summary,
    ]
    if history:
        parts += ["", "Earlier attempts (judged on a hidden holdout set):", *history]
    parts += ["", "Propose a revised system prompt."]
    return "\n".join(parts)


def strands_reviser(
    model_id: str, region: str, on_usage: Callable[[str, int, int], None] | None = None
) -> Reviser:
    """Build a Reviser backed by a Strands agent on Amazon Bedrock.

    `on_usage(model_id, input_tokens, output_tokens)` is called after each attempt so the caller can count the
    agent's own LLM spend against the run budget.
    """

    def revise(task: str, evaluate_on_dev: Callable[[str], str]) -> PromptRevision:
        from strands import Agent, tool
        from strands.models import BedrockModel

        calls = {"n": 0}

        @tool
        def evaluate_prompt(prompt: str) -> str:
            """Run a candidate system prompt on the development cases and return pass rate and failures.

            Args:
                prompt: The complete system prompt to evaluate.
            """
            calls["n"] += 1
            if calls["n"] > MAX_TOOL_CALLS_PER_ITERATION:
                return "Tool budget for this attempt is used up. Give your final answer now."
            return evaluate_on_dev(prompt)

        agent = Agent(
            model=BedrockModel(model_id=model_id, region_name=region, temperature=0.3),
            system_prompt=PORTER_SYSTEM_PROMPT,
            tools=[evaluate_prompt],
            structured_output_model=PromptRevision,
            callback_handler=None,
        )
        result = agent(task)
        if on_usage is not None:
            usage = result.metrics.accumulated_usage
            on_usage(model_id, usage.get("inputTokens", 0), usage.get("outputTokens", 0))
        if not isinstance(result.structured_output, PromptRevision):
            raise RuntimeError("porting agent returned no structured revision")
        return result.structured_output

    return revise


def port_prompt(
    *,
    model_id: str,
    provider: str,
    prompt: str,
    cases: list[Case],
    policy: PortingPolicy,
    evaluate: Evaluate,
    reviser: Reviser,
    should_stop: Callable[[], bool] = lambda: False,
) -> PortingResult:
    """Iteratively revise `prompt` for `model_id`; holdout decides acceptance (tasks 6.2–6.4)."""
    dev, holdout = split_cases(cases)
    best_prompt = prompt
    best_holdout = evaluate(prompt, holdout)
    result = PortingResult(model_id, prompt, prompt, best_holdout.pass_rate, best_holdout.pass_rate)
    history: list[str] = []

    dev_now = evaluate(prompt, dev)
    for i in range(1, policy.max_iterations + 1):
        if should_stop() or (best_holdout.pass_rate == 1.0 and dev_now.pass_rate == 1.0):
            break
        task = build_task(model_id, provider, best_prompt, summarize_failures(dev_now, dev), history)
        revision = reviser(task, lambda p: summarize_failures(evaluate(p, dev), dev))

        candidate = revision.prompt.strip()
        if not candidate or candidate == best_prompt.strip():
            attempt = PortingAttempt(
                i,
                revision.rationale,
                revision.changes,
                best_holdout.pass_rate,
                0,
                False,
                "no change proposed",
            )
        else:
            trial_holdout = evaluate(candidate, holdout)
            trial_dev = evaluate(candidate, dev)
            regs = regressions(best_holdout, trial_holdout)
            # Holdout is the gate: it must improve, or hold steady while dev improves.
            improved = trial_holdout.pass_rate > best_holdout.pass_rate or (
                trial_holdout.pass_rate == best_holdout.pass_rate and trial_dev.pass_rate > dev_now.pass_rate
            )
            ok = improved and regs <= policy.max_regressions
            if ok:
                reason = "accepted"
            elif regs > policy.max_regressions:
                reason = f"{regs} regression(s) on holdout"
            else:
                reason = "no improvement"
            attempt = PortingAttempt(
                i, revision.rationale, revision.changes, trial_holdout.pass_rate, regs, ok, reason
            )
            if ok:
                best_prompt, best_holdout, dev_now = candidate, trial_holdout, trial_dev
        result.attempts.append(attempt)
        history.append(f"- attempt {i}: {attempt.reason}; changes: {'; '.join(attempt.changes) or 'n/a'}")

    result.revised = best_prompt
    result.holdout_after = best_holdout.pass_rate
    return result


def describe(result: PortingResult) -> dict[str, Any]:
    return {
        "model_id": result.model_id,
        "accepted": result.accepted,
        "holdout_before": result.holdout_before,
        "holdout_after": result.holdout_after,
        "attempts": [a.__dict__ for a in result.attempts],
    }


def porting_report(result: PortingResult, before: SuiteResult, after: SuiteResult, target: str) -> str:
    from modelbot.report import porting_section

    lines = [
        f"## ✍️ modelbot port · `{target}` → `{result.model_id}`",
        "",
        f"Full-suite pass rate on `{result.model_id}`: **{before.pass_rate:.0%} → {after.pass_rate:.0%}**",
        *porting_section(result),
    ]
    return "\n".join(lines) + "\n"
