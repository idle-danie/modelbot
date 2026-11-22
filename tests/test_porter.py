import json

from modelbot.config import PortingPolicy
from modelbot.graders import GraderResult
from modelbot.porter import PromptRevision, port_prompt, split_cases
from modelbot.runner import Case, CaseResult, SuiteResult

CASES = [Case(f"c{i}", f"input-{i}", []) for i in range(10)]
HARD = {"c1", "c4", "c6", "c8"}  # fail unless the prompt contains FIX
FIX = "Respond with JSON only."


def evaluate(prompt: str, cases: list[Case]) -> SuiteResult:
    """Fake candidate model: hard cases need FIX; 'BREAK' in the prompt fails every other case."""
    out = SuiteResult("cand", "p", "s")
    for c in cases:
        ok = (FIX in prompt) if c.id in HARD else ("BREAK" not in prompt)
        detail = [] if ok else [GraderResult("json_schema", False, "not JSON")]
        out.results.append(CaseResult(c.id, "out", ok, detail, 10, 1, 5))
    return out


def reviser_returning(prompt_suffix: str, seen: list[str]):
    def revise(task: str, evaluate_on_dev) -> PromptRevision:
        tool_output = evaluate_on_dev("probe")
        seen.extend([task, tool_output])
        json.loads(tool_output)  # the tool returns JSON the agent can read
        base = task.split("<<<\n", 1)[1].split("\n>>>", 1)[0]
        return PromptRevision(
            prompt=base + prompt_suffix, rationale="be explicit", changes=["add format rule"]
        )

    return revise


def test_split_is_deterministic_and_disjoint():
    dev1, hold1 = split_cases(CASES)
    dev2, hold2 = split_cases(CASES)
    assert [c.id for c in dev1] == [c.id for c in dev2] and [c.id for c in hold1] == [c.id for c in hold2]
    assert not {c.id for c in dev1} & {c.id for c in hold1}


def test_helpful_revision_is_accepted():
    seen: list[str] = []
    r = port_prompt(
        model_id="cand",
        provider="amazon",
        prompt="Classify.",
        cases=CASES,
        policy=PortingPolicy(max_iterations=3),
        evaluate=evaluate,
        reviser=reviser_returning("\n" + FIX, seen),
    )
    assert r.accepted and FIX in r.revised
    assert r.holdout_after >= r.holdout_before
    assert r.attempts[0].reason == "accepted"


def test_revision_that_breaks_other_cases_is_rejected():
    r = port_prompt(
        model_id="cand",
        provider="amazon",
        prompt="Classify.",
        cases=CASES,
        policy=PortingPolicy(max_iterations=2, max_regressions=0),
        evaluate=evaluate,
        reviser=reviser_returning("\n" + FIX + " BREAK", []),
    )
    assert not r.accepted and r.revised == "Classify."
    assert all(not a.accepted for a in r.attempts)


def test_agent_never_sees_holdout_cases():
    seen: list[str] = []
    port_prompt(
        model_id="cand",
        provider="amazon",
        prompt="Classify.",
        cases=CASES,
        policy=PortingPolicy(max_iterations=3),
        evaluate=evaluate,
        reviser=reviser_returning("\nnoop", seen),
    )
    _, holdout = split_cases(CASES)
    text = "\n".join(seen)
    assert seen and not any(f'"{c.id}"' in text or c.input in text for c in holdout)


def test_stops_when_told():
    r = port_prompt(
        model_id="cand",
        provider="amazon",
        prompt="Classify.",
        cases=CASES,
        policy=PortingPolicy(max_iterations=3),
        evaluate=evaluate,
        reviser=reviser_returning("\n" + FIX, []),
        should_stop=lambda: True,
    )
    assert r.attempts == [] and not r.accepted
