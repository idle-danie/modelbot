# Product

modelbot is "Dependabot for LLMs": it detects deprecated or superseded Amazon Bedrock models, evaluates
candidates on the user's own eval suite, adapts prompts with an agent when needed, and opens a pull request
with a quality / latency / cost comparison.

Principles:
- The user's evals are the source of truth, not public benchmarks.
- Every recommendation must be explainable from the report alone.
- Never spend more than the configured budget.
