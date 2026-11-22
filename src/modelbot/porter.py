"""Agent-driven prompt porting (Requirement 5, design D3/D7).

The Strands agent proposes prompt revisions and may test them on the *development* split via the
`evaluate_prompt` tool. Acceptance is decided outside the agent, on the *holdout* split, so the rule is
deterministic and the agent cannot overfit to the cases that judge it.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from modelbot.runner import Case

PORTER_SYSTEM_PROMPT = """\
You adapt an existing system prompt so that it performs well on a different foundation model.
Rules:
- Preserve the task, output format, and every business rule in the original prompt.
- Change wording, structure, examples, and explicitness only.
- Use the evaluate_prompt tool to test hypotheses before answering.
- Answer with the full revised prompt between <prompt> tags, then a short rationale between <rationale> tags.
"""


@dataclass
class PortingResult:
    original: str
    revised: str | None
    rationale: str
    holdout_before: float
    holdout_after: float
    iterations: int


def split_cases(
    cases: list[Case], holdout_ratio: float = 0.4, seed: int = 7
) -> tuple[list[Case], list[Case]]:
    """Deterministic dev/holdout split (task 6.1)."""
    shuffled = cases[:]
    random.Random(seed).shuffle(shuffled)
    n_holdout = max(1, round(len(shuffled) * holdout_ratio))
    return shuffled[n_holdout:], shuffled[:n_holdout]


def port_prompt(*args, **kwargs) -> PortingResult:
    # TODO(task 6.2): build strands.Agent(model=BedrockModel(porting_model), tools=[evaluate_prompt],
    #                 system_prompt=PORTER_SYSTEM_PROMPT) and feed it the failing dev cases.
    # TODO(task 6.3): outer loop — accept only if holdout improves and regressions <= max_regressions.
    raise NotImplementedError("prompt porting is not implemented yet (tasks 6.2–6.4)")
