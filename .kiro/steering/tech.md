# Tech

- Python >= 3.11, managed with uv
- boto3 (Bedrock control plane + Converse API), Strands Agents (porting agent)
- pydantic (config), typer (CLI), PyGithub (PRs), jsonschema (grader)
- Tests: pytest, no network in unit tests (fake Bedrock client)
- Lint/format: ruff
- CI: GitHub Actions; AWS auth via OIDC only
