# Requirements Document — modelbot

## Introduction

modelbot is "Dependabot for LLMs". Teams hardcode foundation-model IDs in their applications, and those
models are regularly superseded or moved to a legacy lifecycle state on Amazon Bedrock. Upgrading is risky:
a newer model can be better on average yet regress on the team's own tasks, and prompts tuned for one model
often need adjustment for another.

modelbot watches the Bedrock model catalog, evaluates candidate models against the team's own eval suite,
lets an agent adapt prompts when a candidate underperforms, and opens a pull request containing the model
change, any prompt changes, and a quality / latency / cost comparison.

## Glossary

- **Target**: a location in the user's repository that references a model ID (file + key or pattern).
- **Baseline**: the model currently referenced by a target.
- **Candidate**: a model considered as a replacement for the baseline.
- **Eval suite**: a set of cases (input, expectation, grader) committed to the user's repository.
- **Porting**: agent-driven revision of a prompt so that it performs well on a candidate model.

## Requirements

### Requirement 1 — Configuration

**User Story:** As an application developer, I want to declare where my model IDs, prompts, and evals live
in a single file, so that modelbot can operate on my repository without code changes.

#### Acceptance Criteria

1. WHEN modelbot starts THE SYSTEM SHALL load `modelbot.yaml` from the repository root or a path given by `--config`.
2. THE SYSTEM SHALL support one or more targets, each defining a file path and either a YAML/JSON key path or a regex that captures the model ID.
3. THE SYSTEM SHALL support per-target prompt files, eval suite path, graders, and pass thresholds.
4. THE SYSTEM SHALL support a candidate policy consisting of an allowlist of providers/model families and an optional denylist of model IDs.
5. THE SYSTEM SHALL support a per-run budget cap in USD.
6. IF the configuration is invalid THEN THE SYSTEM SHALL exit with a non-zero code and a message identifying the invalid field.

### Requirement 2 — Model discovery

**User Story:** As a developer, I want modelbot to tell me when my model is deprecated or a better candidate
exists, so that I never learn about it from a production outage.

#### Acceptance Criteria

1. WHEN `modelbot scan` runs THE SYSTEM SHALL list Bedrock foundation models and inference profiles available in the configured region.
2. WHEN a baseline model has lifecycle status `LEGACY` THE SYSTEM SHALL mark the target as **urgent**.
3. THE SYSTEM SHALL select candidates that match the candidate policy, support the modalities the target needs, and are not the baseline.
4. WHEN a candidate has already been evaluated against the same eval suite version THE SYSTEM SHALL skip it unless `--force` is given.
5. THE SYSTEM SHALL output scan results as a human-readable table and as JSON.

### Requirement 3 — Evaluation

**User Story:** As a developer, I want baseline and candidates run on my own eval cases, so that the upgrade
decision reflects my workload rather than public benchmarks.

#### Acceptance Criteria

1. THE SYSTEM SHALL invoke models through the Bedrock Converse API so that every model is called through the same interface.
2. FOR EACH case THE SYSTEM SHALL record output, pass/fail per grader, input tokens, output tokens, and latency.
3. THE SYSTEM SHALL run cases concurrently up to a configurable limit.
4. WHEN Bedrock returns a throttling error THE SYSTEM SHALL retry with exponential backoff and jitter up to a configured maximum.
5. WHEN cumulative estimated spend reaches the budget cap THE SYSTEM SHALL stop issuing requests and report partial results.
6. THE SYSTEM SHALL compute per-model aggregates: pass rate, p50/p95 latency, and cost per 1,000 cases.

### Requirement 4 — Grading

**User Story:** As a developer, I want both deterministic checks and rubric-based judging, so that I can
evaluate structured and free-form outputs.

#### Acceptance Criteria

1. THE SYSTEM SHALL provide deterministic graders: `exact`, `contains`, `regex`, and `json_schema`.
2. THE SYSTEM SHALL provide an `llm_judge` grader that scores output against a rubric using a pinned judge model.
3. THE SYSTEM SHALL reject configurations where the judge model is also the candidate under evaluation.
4. THE SYSTEM SHALL allow multiple graders per case, all of which must pass for the case to pass.

### Requirement 5 — Prompt porting

**User Story:** As a developer, I want modelbot to adapt my prompt when a candidate is close but not good
enough, so that a model upgrade is not blocked by prompt tuning work.

#### Acceptance Criteria

1. WHEN a candidate's pass rate is below the threshold but within the configured porting margin THE SYSTEM SHALL start a porting loop.
2. THE SYSTEM SHALL split eval cases into a development set and a holdout set with a fixed seed.
3. THE porting agent SHALL receive the current prompt, failing development cases, and model-specific guidance, and SHALL propose a revised prompt with a rationale.
4. THE SYSTEM SHALL accept a revised prompt only IF holdout pass rate improves AND no more than a configured number of previously passing holdout cases regress.
5. THE SYSTEM SHALL stop after a configured maximum number of iterations.
6. THE SYSTEM SHALL never modify eval cases or graders during porting.

### Requirement 6 — Decision

**User Story:** As a developer, I want a clear recommendation, so that I can approve upgrades quickly.

#### Acceptance Criteria

1. THE SYSTEM SHALL recommend a candidate IF its pass rate is greater than or equal to baseline minus the configured tolerance AND its cost and p95 latency are within the configured limits.
2. WHEN several candidates qualify THE SYSTEM SHALL rank them by pass rate, then cost, then p95 latency.
3. WHEN a target is urgent and no candidate qualifies THE SYSTEM SHALL still report the best candidate and flag manual review.

### Requirement 7 — Reporting and pull requests

**User Story:** As a reviewer, I want a pull request that shows exactly what changed and why, so that I can
merge with confidence.

#### Acceptance Criteria

1. THE SYSTEM SHALL produce a Markdown report with a comparison table, the top failing cases, and prompt diffs.
2. THE SYSTEM SHALL produce a machine-readable JSON report.
3. WHEN `--open-pr` is given THE SYSTEM SHALL create a branch, update model IDs and accepted prompts, and open a pull request with the Markdown report as its body.
4. IF an open modelbot pull request already exists for the same target and candidate THEN THE SYSTEM SHALL update it instead of opening a new one.
5. WHEN `--dry-run` is given THE SYSTEM SHALL not write files or call the GitHub API.

### Requirement 8 — Interfaces

#### Acceptance Criteria

1. THE SYSTEM SHALL provide CLI commands `scan`, `eval`, and `run`.
2. THE SYSTEM SHALL ship a GitHub Action that authenticates to AWS via OIDC and runs `modelbot run --open-pr`.
3. THE SYSTEM SHALL ship an example project that a user can run end-to-end within 10 minutes of cloning.

### Requirement 9 — Security and operations

#### Acceptance Criteria

1. THE SYSTEM SHALL not require long-lived AWS credentials in CI.
2. THE SYSTEM SHALL document the minimum IAM permissions it needs.
3. THE SYSTEM SHALL not log full eval inputs or outputs unless `--verbose` is given.
4. THE SYSTEM SHALL report total requests, tokens, and estimated spend at the end of every run.
