# Implementation Plan — modelbot

- [x] 1. Project skeleton
  - pyproject (uv), package layout, CLI entry point, CI workflow (ruff + pytest)
  - _Requirements: 8.1_

- [x] 2. Configuration loading and validation
  - [x] 2.1 Pydantic models for `modelbot.yaml`
  - [x] 2.2 Field-path error messages and exit code 2
  - [x] 2.3 Unit tests
  - _Requirements: 1.1–1.6_

- [ ] 3. Model discovery
  - [x] 3.1 `ModelInfo` and catalog parsing from `ListFoundationModels`
  - [x] 3.2 Merge inference profiles (`us.` / `apac.` / `global.` prefixes) into the catalog
  - [x] 3.3 Candidate filtering by provider allowlist, denylist, modalities
  - [x] 3.4 Urgent flag for `LEGACY` baselines and baselines missing from the catalog (end-of-life)
  - [x] 3.7 Exclude speech-to-speech models; prefer same provider and tier (haiku → haiku)
  - [x] 3.5 `scan` command: table + JSON output
  - [ ] 3.6 Skip already-evaluated (suite hash cache in `.modelbot/state.json`)
  - _Requirements: 2.1–2.5_

- [x] 4. Evaluation runner
  - [x] 4.1 Converse call wrapper returning output, tokens, latency
  - [x] 4.2 Thread-pool concurrency
  - [x] 4.3 Throttling retry with exponential backoff + full jitter
  - [x] 4.4 Pricing table and `BudgetTracker`
  - [x] 4.5 Aggregates: pass rate, p50/p95, cost per 1k
  - [x] 4.6 `eval` command: baseline + candidates → decision → Markdown report
  - _Requirements: 3.1–3.6_

- [ ] 5. Graders
  - [x] 5.1 `exact`, `contains`, `regex`, `json_schema`
  - [ ] 5.2 `llm_judge` with pinned judge model and rubric
  - [ ] 5.3 Reject judge == candidate
  - _Requirements: 4.1–4.4_

- [x] 6. Prompt porting agent
  - [x] 6.1 Deterministic dev/holdout split
  - [x] 6.2 Strands agent with `evaluate_prompt` tool and model-specific guidance
  - [x] 6.3 Outer acceptance loop (holdout improvement, regression limit, max iterations)
  - [x] 6.4 Prompt diff + rationale in results
  - [x] 6.5 Wire porting into `eval` for near-miss candidates; `--no-port`
  - [x] 6.6 `port` command: adapt a prompt to one chosen model regardless of thresholds
  - [x] 6.7 Count the porting agent's own token usage against the run budget
  - [x] 6.8 Harder example (`examples/email-extractor`) where prompt porting measurably matters
  - [x] 6.9 Reject revisions that copy eval case text; require dev not to drop when holdout improves
  - [ ] 6.12 Vary fixtures such as the Received date across eval cases so date examples cannot flatter holdout
  - [ ] 6.10 Catch partial-phrase leakage (n-gram overlap) without false positives
  - [x] 6.11 Rule-preservation check (severity-based: contradiction/removal block, additions are surfaced): a pinned judge model compares original vs revised prompt and rejects revisions
        that add, drop, or change business rules (observed: agent wrote `"$89.50" -> 8950` into the prompt)
  - _Requirements: 5.1–5.6_

- [ ] 7. Decision
  - [x] 7.1 Qualification rules and ranking
  - [x] 7.2 Urgent-without-qualifier handling
  - _Requirements: 6.1–6.3_

- [x] 8. Reporting and PRs (JSON report pending)
  - [x] 8.1 Markdown comparison table
  - [x] 8.2a Prompt diff section, all-models table
  - [ ] 8.2b Failing-case section, JSON report
  - [x] 8.3 File rewriting for key-path and regex targets
  - [x] 8.4 GitHub PR create/update, `--dry-run`
  - _Requirements: 7.1–7.5_

- [ ] 9. Distribution
  - [x] 9.1 Composite GitHub Action with OIDC
  - [x] 9.2 CloudFormation template for the GitHub OIDC role (least privilege)
  - [ ] 9.3 Example project runnable end-to-end in 10 minutes
  - [ ] 9.4 README with demo GIF and sample PR
  - _Requirements: 8.2, 8.3, 9.1, 9.2_

- [ ] 10. Hardening
  - [x] 10.0 `repeats` option: run each case N times and report pass-rate variance (observed 1-in-~6 flakes at temperature 0)
  - [ ] 10.1 Opt-in integration test against real Bedrock
  - [ ] 10.2 Run summary (requests, tokens, spend); redact I/O unless `--verbose`
  - _Requirements: 9.3, 9.4_
