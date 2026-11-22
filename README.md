# modelbot 🤖

**Dependabot for LLMs.** modelbot watches the Amazon Bedrock model catalog, runs *your* evals against
newer models, lets an agent adapt your prompts when a candidate is close but not quite there, and opens a
pull request with the evidence.

```
## 🤖 modelbot · ticket-classifier
> ⚠️ Baseline model is LEGACY on Amazon Bedrock. Plan the migration now.

Recommended: us.anthropic.claude-3-5-haiku-… → anthropic.claude-haiku-4-5-…

| Metric          | baseline | candidate | Change   |
|-----------------|----------|-----------|----------|
| Eval pass rate  | 83%      | 92%       | +9pp ✅  |
| p95 latency     | 2.4s     | 1.9s      | -21% ✅  |
| Cost / 1k cases | $1.31    | $1.64     | +25% ⚠️  |
```
<sub>Illustrative output. Real numbers come from your eval suite.</sub>

## Why

- Models get deprecated on a schedule you don't control. Hardcoded model IDs turn into outages.
- "The new model is better" is true on public benchmarks and often false on *your* task.
- Switching models often means re-tuning prompts, which is tedious work that keeps teams on old models.

## How it works

```
scan ──► evaluate ──► port prompts (agent) ──► decide ──► pull request
```

1. **Scan**: reads `ListFoundationModels`, flags baselines in `LEGACY` lifecycle, and selects candidates from your provider allowlist.
2. **Evaluate**: runs your JSONL eval suite on baseline and candidates through the **Converse API**, which gives every model the same interface and returns tokens and latency.
3. **Port**: if a candidate falls just short, a **Strands** agent rewrites the prompt and tests it on a dev split. modelbot accepts the rewrite only if a **held-out** split improves.
4. **Decide**: ranks candidates by pass rate, cost, and p95 latency against your policy.
5. **PR**: updates the model ID and any accepted prompts, and attaches the comparison report.

## Quick start

```bash
git clone https://github.com/idle-danie/modelbot && cd modelbot
uv sync
cd examples/ticket-classifier
uv run modelbot scan          # deprecated baselines + candidates (needs AWS credentials)
uv run modelbot eval          # run evals on baseline + top candidates, write modelbot-report.md
uv run modelbot eval --candidate us.anthropic.claude-haiku-4-5-20251001-v1:0   # pick candidates explicitly
uv run modelbot port --candidate amazon.nova-lite-v1:0   # adapt the prompt to one model, regardless of thresholds
```

Every run prints its request count and estimated spend, and stops issuing new requests once `budget_usd` is reached.
Candidates without an entry in `prices.yaml` are skipped. The bundled table lists us-east-1 on-demand prices taken from the
AWS Price List API; add others with `--prices my-prices.yaml`. Anthropic models on Bedrock require a one-time use-case
form per account; until it is approved those candidates are reported as errored and skipped.

## The porting agent

When a candidate lands just below the quality bar (within `porting.margin`), a Strands agent rewrites the prompt
for that model:

- Eval cases are split into **dev** and **holdout** with a fixed seed. The agent only ever sees dev cases.
- The agent can call `evaluate_prompt` (capped at 3 calls per attempt) to test ideas on dev before answering.
- modelbot, not the agent, decides whether to keep a revision. Holdout must improve, or hold steady while dev
  improves, with at most `max_regressions` previously passing holdout cases now failing.
- An accepted prompt is re-run on the full suite before the final recommendation, and the PR shows the diff and rationale.

## Configuration

```yaml
# modelbot.yaml
region: us-east-1
budget_usd: 1.0
candidates:
  providers: [anthropic, amazon]
targets:
  - name: ticket-classifier
    file: app/config.yaml
    key: llm.model_id            # or pattern: 'MODEL_ID = "([^"]+)"'
    prompts: [prompts/classify.md]
    evals: evals/cases.jsonl
    threshold: 0.90
```

Eval cases are JSONL with one or more graders (`exact`, `contains`, `regex`, `json_schema`; `llm_judge` is planned):

```json
{"id": "bug-01", "input": "Export returns 500 and our close is blocked!", "graders": [{"type": "json_schema", "schema": {"properties": {"category": {"const": "bug"}, "urgent": {"const": true}}}}]}
```

## IAM

```
bedrock:ListFoundationModels  bedrock:ListInferenceProfiles  bedrock:InvokeModel
```

## Status

Early development, built spec-first with [Kiro](https://kiro.dev). See [`.kiro/specs/modelbot`](.kiro/specs/modelbot)
for requirements, design, and the task list.

| Stage | Status |
|---|---|
| Config, discovery (incl. inference profiles), deterministic graders, decision, report | ✅ |
| `eval` command with concurrency, throttling retries, budget enforcement | ✅ |
| Prompt porting agent (Strands) with holdout-gated acceptance | ✅ |
| LLM judge | 🚧 |
| PR creation, GitHub Action | 🚧 |

## License

Apache-2.0
