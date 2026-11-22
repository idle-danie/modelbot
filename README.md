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
uv run modelbot eval --repeats 3   # run each case 3x; pass rate is averaged and flaky cases are listed
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
- Revisions that copy eval case text into the prompt are rejected outright. In real runs the agent tried this
  repeatedly ("few-shot examples" lifted from the dev set), which inflated full-suite scores without helping holdout.

First real run, `examples/email-extractor`, Nova Lite with Nova Pro as the porting agent
([full report](examples/email-extractor/SAMPLE-port-report.md)):

| | Before | After |
|---|---|---|
| Holdout (never seen by the agent) | 50% | 62% |
| Full suite | 55% | 65% |
| Attempts | | 4 (1 accepted, 3 rejected for copying eval cases) |

With 8 holdout cases a one-case change is close to run-to-run noise: at temperature 0, Nova Micro still flipped
3 of 20 cases between runs. Use `repeats` and larger suites before trusting small deltas.

> ⚠️ **Evals alone did not catch everything.** The accepted prompt in that run introduced a *wrong* business rule
> (`"$89.50" -> 8950`) and a meaningless meta-instruction. Scores did not drop because the affected case was already
> failing. Ported prompts must be reviewed by a human before merging, which is why modelbot opens a PR instead of
> pushing.

**Rule-preservation check.** Before any eval money is spent on a revision, a pinned `judge_model` compares it with the
*original* prompt and rejects revisions that add, drop, or change business rules. On the real bad revision above, a
Nova Pro judge flagged `"$89.50" -> 8950` in 2/2 runs and passed a faithful rewording in 2/2 runs. With the guards on,
the same porting run rejected all four attempts (three copied eval cases, one changed rules)
([report](examples/email-extractor/SAMPLE-port-report-with-guards.md)). The Nova Pro judge is conservative: it also
flagged a few correct clarifications. A stronger judge model reduces that.

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

## Run in GitHub Actions

1. Deploy the OIDC role (least privilege, trusted only for `main` of your repo, so PRs and forks cannot assume it):
   ```bash
   aws cloudformation deploy --template-file infra/github-oidc-role.yaml --stack-name modelbot-github \
     --capabilities CAPABILITY_IAM --parameter-overrides GitHubOwner=<you> RepositoryName=<repo>
   aws cloudformation describe-stacks --stack-name modelbot-github --query "Stacks[0].Outputs"
   ```
2. Set the repository variable `MODELBOT_ROLE_ARN` to the role ARN.
3. Settings → Actions → General → enable "Allow GitHub Actions to create and approve pull requests".
4. Add a workflow (see [`.github/workflows/modelbot.yml`](.github/workflows/modelbot.yml)):
   ```yaml
   - uses: idle-danie/modelbot@main
     with:
       role-to-assume: ${{ vars.MODELBOT_ROLE_ARN }}
       config: modelbot.yaml
   ```

Example PR opened by modelbot: [#1](https://github.com/idle-danie/modelbot/pull/1).

## IAM

```
bedrock:ListFoundationModels  bedrock:ListInferenceProfiles  bedrock:InvokeModel  bedrock:InvokeModelWithResponseStream
```
(`InvokeModelWithResponseStream` is used by the Strands porting agent.)

## Status

Early development, built spec-first with [Kiro](https://kiro.dev). See [`.kiro/specs/modelbot`](.kiro/specs/modelbot)
for requirements, design, and the task list.

| Stage | Status |
|---|---|
| Config, discovery (incl. inference profiles), deterministic graders, decision, report | ✅ |
| `eval` command with concurrency, throttling retries, budget enforcement | ✅ |
| Prompt porting agent (Strands) with holdout-gated acceptance | ✅ |
| LLM judge | 🚧 |
| `run` command, PR creation and update, GitHub Action + OIDC role template | ✅ |
| JSON report, failing-case section, eval-state cache | 🚧 |

## License

Apache-2.0
