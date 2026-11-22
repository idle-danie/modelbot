# Design Document — modelbot

## Overview

modelbot is a Python CLI packaged as a GitHub Action. A run has four stages:

```
scan ──► evaluate ──► (port prompts) ──► decide & report ──► (open PR)
```

```
                 ┌──────────────────────── GitHub Actions (schedule / manual) ───────────────────────┐
                 │                                                                                    │
 modelbot.yaml ─►│  config ─► discovery ─► runner ─► graders ─► decision ─► report ─► github_pr       │
 prompts/        │                │           │                    ▲                                  │
 evals/*.jsonl   │                │           └──► porter (Strands agent) ──┘                         │
                 └────────────────┼───────────┼────────────────────────────────────────────────────────┘
                                  │ OIDC      │
                                  ▼           ▼
                       Bedrock control plane  Bedrock Converse API
                       (ListFoundationModels, (baseline / candidates / judge / porting model)
                        ListInferenceProfiles)
```

## Key design decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Call every model through the **Bedrock Converse API** | One request/response shape for all providers; usage and latency are returned in the response, so cost and latency need no extra instrumentation. |
| D2 | **Evals live in the user's repo** as JSONL | Versioned with the code they protect; the eval suite hash identifies "already evaluated" results. |
| D3 | **Holdout split** during porting | Prevents the agent from overfitting the prompt to the very cases it sees. A revision is accepted only on holdout improvement. |
| D4 | **Pinned judge model, different from the candidate** | Reduces self-preference bias in `llm_judge` and keeps scores comparable across runs. |
| D5 | **Static pricing table** with user override | Per-token prices are needed offline and deterministically; the table is versioned and cited in reports. |
| D6 | **GitHub Action first**, no always-on infrastructure | Zero idle cost and nothing to operate; a scheduled Lambda can be added later without changing the core. |
| D7 | Porting agent built with **Strands Agents** on Bedrock | Same SDK used by AgentCore, so the porter can later be hosted on AgentCore Runtime unchanged. |
| D8 | Graders are a **plugin registry** | Users can add domain graders; AgentCore Evaluations can be added as a grader backend later. |

## Components

### config (`config.py`)
Pydantic models for `modelbot.yaml`; validation errors name the offending field (R1.6).

```yaml
region: us-east-1
budget_usd: 5.0
judge_model: us.amazon.nova-pro-v1:0
candidates:
  providers: [anthropic, amazon]
  deny: []
targets:
  - name: ticket-classifier
    file: app/config.yaml
    key: llm.model_id               # or: pattern: 'MODEL_ID = "([^"]+)"'
    prompts: [prompts/classify.md]
    evals: evals/cases.jsonl
    threshold: 0.90                 # minimum pass rate
    tolerance: 0.02                 # allowed drop vs baseline
    porting: { margin: 0.10, max_iterations: 3, max_regressions: 1 }
    limits: { max_cost_ratio: 1.5, max_p95_ratio: 1.5 }
```

### discovery (`discovery.py`)
- Calls `ListFoundationModels` and `ListInferenceProfiles`.
- `ModelInfo(model_id, provider, lifecycle, input_modalities, output_modalities)`.
- `find_candidates(baseline, catalog, policy)` filters by provider allowlist, denylist, modalities.
- Marks targets urgent when baseline lifecycle is `LEGACY` (R2.2).

### runner (`runner.py`)
- `run_suite(model_id, prompt, cases, concurrency, budget)` → `SuiteResult`.
- Thread pool for concurrency; retry `ThrottlingException` with exponential backoff + full jitter (R3.4).
- A shared `BudgetTracker` estimates spend after every call. The runner checks `exhausted` before submitting
  each new case, so in-flight requests finish and their results are kept; the suite is marked `partial` (R3.5).
- Models without on-demand throughput are invoked through a system-defined inference profile, preferring the
  region's geographic profile (`us.`, `eu.`, `apac.`) over `global.` so data stays in-geo.

### graders (`graders.py`)
Registry: `exact`, `contains`, `regex`, `json_schema`, `llm_judge`. A case passes only if all graders pass (R4.4).

### porter (`porter.py`)
Strands agent with a single tool, `evaluate_prompt(prompt) -> dev_results`, so the agent can test its own
hypotheses on the development split. The outer loop (not the agent) evaluates on holdout and decides
acceptance (R5.4), keeping the acceptance rule deterministic and auditable.

### decision (`decision.py`)
Pure function over `SuiteResult`s implementing R6. Kept side-effect free for unit testing.

### report (`report.py`)
Renders Markdown + JSON. Markdown table: pass rate, p95 latency, cost per 1k cases, deltas, plus
collapsible sections for failing cases and prompt diffs.

### github_pr (`github_pr.py`)
Branch name `modelbot/<target>/<candidate-slug>`; finds an existing open PR on that branch and updates it
(R7.4).

## Data model

```python
Case(id, input: str | list[Message], expected: dict, graders: list[GraderSpec])
CaseResult(case_id, output, passed, grader_results, input_tokens, output_tokens, latency_ms)
SuiteResult(model_id, prompt_hash, suite_hash, results: list[CaseResult])
  .pass_rate .p50_ms .p95_ms .cost_per_1k
Recommendation(target, baseline, chosen: str | None, ranked: list[SuiteResult], urgent, ported_prompts)
```

## Error handling

| Situation | Behavior |
|---|---|
| Invalid config | Exit 2 with field path |
| Model not accessible in region / account | Skip candidate, list it under "not evaluated" with reason |
| Throttling | Backoff + jitter, then mark case errored (counts as failed) |
| Budget exceeded | Stop, report partial results, exit 0 with warning |
| GitHub API failure | Report written to `modelbot-report.md`; exit 1 |

## Testing strategy

- Unit tests for config, discovery filtering, graders, pricing, decision, report rendering — no network.
- Bedrock calls behind a small client protocol; tests use a fake client.
- An integration test (opt-in, `MODELBOT_IT=1`) runs the example project against real Bedrock with a $0.50 budget.

## IAM (minimum)

```
bedrock:ListFoundationModels, bedrock:ListInferenceProfiles, bedrock:InvokeModel,
bedrock:InvokeModelWithResponseStream   # Strands agents stream
```
(`InvokeModel` covers Converse.) Scope `InvokeModel` to allowlisted provider ARNs where possible.

## Future work

- AgentCore Evaluations as a grader backend.
- Host the porter on AgentCore Runtime; scheduled runs via EventBridge Scheduler + Lambda.
- Multi-turn / tool-using agent evals.
